"""微信消息控件结构调试脚本

用于诊断消息发送方识别失败的问题。
打印当前聊天窗口最近 10 条消息的完整控件结构。

使用方法：
    1. 打开微信 PC 客户端并登录
    2. 手动进入目标客户的聊天窗口
    3. 运行脚本：
       cd E:\work\project\auto_wechat
       python scripts/debug_wechat_messages.py
"""

import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ctypes
import comtypes

# 初始化 COM
try:
    comtypes.CoInitialize()
except Exception:
    pass

import uiautomation as uia

from app.wechat_ui.window_locator import find_wechat_window, find_message_list


def format_rect(rect) -> str:
    """格式化矩形区域"""
    if rect is None:
        return "(无)"
    return (f"({rect.left}, {rect.top}) - ({rect.right}, {rect.bottom}) "
            f"[{rect.width()}x{rect.height()}]")


def safe_str(s: str) -> str:
    """安全转字符串，避免 GBK 编码错误"""
    if not s:
        return ""
    return s.encode("gbk", errors="replace").decode("gbk")


def get_sub_control_count(control: uia.Control) -> int:
    """获取子控件数量（参考 wxauto 的 FindAll 方式）"""
    try:
        sub_controls = control.FindAll(return_pointer=True)
        return sub_controls.Length - 1
    except Exception:
        try:
            return len(control.GetChildren())
        except Exception:
            return -1


def find_avatar_candidates(msg_control: uia.Control):
    """
    在消息控件中尝试多种策略查找头像控件。
    返回所有候选控件的列表。
    """
    candidates = []

    # 策略1：ButtonControl（wxauto 原始方式）
    try:
        btn = msg_control.ButtonControl(searchDepth=2)
        if btn.Exists(0):
            rect = btn.BoundingRectangle
            w, h = rect.width(), rect.height()
            candidates.append({
                "strategy": "ButtonControl(searchDepth=2)",
                "found": True,
                "control_type": btn.ControlTypeName,
                "name": btn.Name or "",
                "class_name": btn.ClassName or "",
                "rect": format_rect(rect),
                "width": w,
                "height": h,
                "is_avatar_size": 20 <= w <= 80 and 20 <= h <= 80,
            })
        else:
            candidates.append({"strategy": "ButtonControl(searchDepth=2)", "found": False})
    except Exception as e:
        candidates.append({"strategy": "ButtonControl(searchDepth=2)", "found": False, "error": str(e)})

    # 策略2：ImageControl
    try:
        img = msg_control.ImageControl(searchDepth=2)
        if img.Exists(0):
            rect = img.BoundingRectangle
            w, h = rect.width(), rect.height()
            candidates.append({
                "strategy": "ImageControl(searchDepth=2)",
                "found": True,
                "control_type": img.ControlTypeName,
                "name": img.Name or "",
                "class_name": img.ClassName or "",
                "rect": format_rect(rect),
                "width": w,
                "height": h,
                "is_avatar_size": 20 <= w <= 80 and 20 <= h <= 80,
            })
        else:
            candidates.append({"strategy": "ImageControl(searchDepth=2)", "found": False})
    except Exception as e:
        candidates.append({"strategy": "ImageControl(searchDepth=2)", "found": False, "error": str(e)})

    # 策略3：遍历子控件找小尺寸头像
    try:
        children = msg_control.GetChildren()
        for child in children:
            try:
                rect = child.BoundingRectangle
                w, h = rect.width(), rect.height()
                # 头像特征：宽高接近正方形，尺寸在 20-80px 之间
                if 20 <= w <= 80 and 20 <= h <= 80 and abs(w - h) <= 10:
                    candidates.append({
                        "strategy": f"GetChildren 遍历 (头像尺寸检测)",
                        "found": True,
                        "control_type": child.ControlTypeName,
                        "name": child.Name or "",
                        "class_name": child.ClassName or "",
                        "rect": format_rect(rect),
                        "width": w,
                        "height": h,
                        "is_avatar_size": True,
                    })
            except Exception:
                pass
    except Exception:
        pass

    return candidates


def main():
    print("=" * 80)
    print("  微信消息控件结构调试")
    print("=" * 80)
    print()
    print("请确认：")
    print("  1. 微信 PC 客户端已启动并登录")
    print("  2. 已手动打开某个联系人的聊天窗口")
    print()

    # 第1步：定位微信窗口
    print("【第1步】定位微信窗口...")
    try:
        window = find_wechat_window()
        print(f"  ✓ 窗口已定位: Name='{safe_str(window.Name)}', "
              f"ClassName='{safe_str(window.ClassName)}'")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return

    # 第2步：定位消息列表
    print("\n【第2步】定位消息列表...")
    try:
        msg_list = find_message_list(window, timeout=5)
        list_rect = msg_list.BoundingRectangle
        mid_x = (list_rect.left + list_rect.right) / 2
        print(f"  ✓ 消息列表已找到")
        print(f"    BoundingRect: {format_rect(list_rect)}")
        print(f"    中心线 X: {mid_x:.1f}")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return

    # 第3步：读取最近消息
    print("\n【第3步】读取最近消息控件结构...")
    max_messages = 10
    children = msg_list.GetChildren()
    total = len(children)
    start_idx = max(0, total - max_messages)
    recent = children[start_idx:]

    print(f"  消息总数: {total}，读取最后 {len(recent)} 条")
    print()

    for i, child in enumerate(recent):
        idx = start_idx + i
        name = child.Name or ""
        class_name = child.ClassName or ""
        ctrl_type = child.ControlTypeName
        auto_id = child.AutomationId or ""

        try:
            rect = child.BoundingRectangle
            rect_str = format_rect(rect)
            child_mid_x = (rect.left + rect.right) / 2
        except Exception:
            rect_str = "(异常)"
            child_mid_x = 0

        sub_count = get_sub_control_count(child)

        print(f"  ── 消息 [{idx}] ──────────────────────────────────────")
        print(f"  Name:            {safe_str(name)}")
        print(f"  ClassName:       {safe_str(class_name)}")
        print(f"  ControlType:     {ctrl_type}")
        print(f"  AutomationId:    {safe_str(auto_id)}")
        print(f"  BoundingRect:    {rect_str}")
        print(f"  Item中心X:       {child_mid_x:.1f}  (列表中心: {mid_x:.1f})")
        print(f"  子控件数量:      {sub_count}")

        # 打印子控件详情
        try:
            sub_children = child.GetChildren()
            print(f"  子控件列表 ({len(sub_children)} 个):")
            for j, sub in enumerate(sub_children):
                sub_name = sub.Name or ""
                sub_class = sub.ClassName or ""
                sub_type = sub.ControlTypeName
                try:
                    sub_rect = sub.BoundingRectangle
                    sub_w = sub_rect.width()
                    sub_h = sub_rect.height()
                    sub_mid_x = (sub_rect.left + sub_rect.right) / 2
                    pos = "左" if sub_mid_x < mid_x else "右"
                    rect_info = f" {sub_w}x{sub_h} 中X={sub_mid_x:.0f} [{pos}侧]"
                except Exception:
                    rect_info = ""

                print(f"    [{j}] {sub_type} Name='{safe_str(sub_name)}' "
                      f"Class='{safe_str(sub_class)}'{rect_info}")
        except Exception as e:
            print(f"  子控件遍历失败: {e}")

        # 尝试多种头像查找策略
        print(f"  头像查找策略:")
        avatar_candidates = find_avatar_candidates(child)
        for ac in avatar_candidates:
            if ac["found"]:
                avatar_size_mark = " ← 头像尺寸" if ac.get("is_avatar_size") else ""
                print(f"    ✓ {ac['strategy']}: {ac['control_type']} "
                      f"Name='{safe_str(ac.get('name', ''))}' "
                      f"Rect={ac.get('rect', '')}{avatar_size_mark}")
            else:
                err = ac.get('error', '')
                print(f"    ✗ {ac['strategy']}: 未找到" + (f" ({err})" if err else ""))

        # 基于位置推断发送方
        print(f"  发送方推断:")
        # 文本位置推断
        try:
            text_controls = child.GetChildren()
            text_x_positions = []
            for tc in text_controls:
                if tc.ControlTypeName == "TextControl":
                    tc_rect = tc.BoundingRectangle
                    tc_center_x = (tc_rect.left + tc_rect.right) / 2
                    text_x_positions.append(tc_center_x)

            if text_x_positions:
                avg_x = sum(text_x_positions) / len(text_x_positions)
                if avg_x > mid_x + 50:
                    sender_guess = "self (文本靠右)"
                elif avg_x < mid_x - 50:
                    sender_guess = "friend (文本靠左)"
                else:
                    sender_guess = "unknown (文本居中)"
                print(f"    文本位置推断: TextControl 平均X={avg_x:.1f}, → {sender_guess}")
            else:
                print(f"    文本位置推断: 无 TextControl")
        except Exception as e:
            print(f"    文本位置推断失败: {e}")

        print()

    print("=" * 80)
    print("  调试完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
