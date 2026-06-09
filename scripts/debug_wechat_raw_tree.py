"""微信消息 UIA 深层控件树探测实验脚本

目的：探测消息 ListItemControl 的完整子孙控件树，
判断是否有可用于区分 self/friend 的深层控件（头像、气泡、文本）。

使用方法：
    1. 打开微信 PC 客户端并登录（主机微信）
    2. 手动进入目标客户的聊天窗口
    3. 运行脚本：
       cd E:\work\project\auto_wechat
       python scripts/debug_wechat_raw_tree.py

实验内容：
    - 实验1：GetChildren() 常规探测
    - 实验2：WalkControl 深层遍历
    - 实验3：FindAll 返回所有子孙控件
    - 实验4：ControlFromPoint 点采样
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ctypes
import comtypes

try:
    comtypes.CoInitialize()
except Exception:
    pass

import uiautomation as uia

from app.wechat_ui.window_locator import find_wechat_window, find_message_list


def format_rect(rect) -> str:
    if rect is None:
        return "(无)"
    return (f"({rect.left}, {rect.top}) - ({rect.right}, {rect.bottom}) "
            f"[{rect.width()}x{rect.height()}]")


def safe_str(s: str, max_len: int = 60) -> str:
    if not s:
        return ""
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s.encode("gbk", errors="replace").decode("gbk")


# ========== 实验1：GetChildren 常规探测 ==========

def experiment_get_children(msg_control, label: str):
    """实验1：常规 GetChildren() 探测"""
    print(f"\n  【实验1】GetChildren() 常规探测 ({label})")
    try:
        children = msg_control.GetChildren()
        print(f"    GetChildren() 返回: {len(children)} 个子控件")
        for j, child in enumerate(children):
            print(f"      [{j}] {child.ControlTypeName} "
                  f"Name='{safe_str(child.Name)}' "
                  f"Class='{safe_str(child.ClassName)}' "
                  f"Rect={format_rect(child.BoundingRectangle)}")
        return children
    except Exception as e:
        print(f"    GetChildren() 异常: {e}")
        return []


# ========== 实验2：WalkControl 深层遍历 ==========

def experiment_walk_control(msg_control, label: str):
    """实验2：WalkControl 遍历所有子孙控件"""
    print(f"\n  【实验2】WalkControl 深层遍历 ({label})")
    count = 0
    found_controls = []
    try:
        # WalkControl 遍历所有子孙
        for ctrl, depth in msg_control.WalkControl(maxDepth=10):
            count += 1
            if count <= 50:  # 最多打印 50 个
                indent = "    " + "  " * depth
                name = safe_str(ctrl.Name, 40)
                class_name = safe_str(ctrl.ClassName, 40)
                rect = format_rect(ctrl.BoundingRectangle)
                print(f"{indent}[d{depth}] {ctrl.ControlTypeName} "
                      f"Name='{name}' Class='{class_name}' Rect={rect}")
                found_controls.append({
                    "depth": depth,
                    "type": ctrl.ControlTypeName,
                    "name": ctrl.Name or "",
                    "class_name": ctrl.ClassName or "",
                    "rect": rect,
                })
        print(f"    总计子孙控件: {count}")
    except Exception as e:
        print(f"    WalkControl 异常: {e}")

    return found_controls


# ========== 实验3：FindAll 获取所有子孙 ==========

def experiment_find_all(msg_control, label: str):
    """实验3：FindAll 获取子孙控件指针"""
    print(f"\n  【实验3】FindAll 子孙控件 ({label})")
    try:
        ptrs = msg_control.FindAll(return_pointer=True)
        length = ptrs.Length
        print(f"    FindAll Length = {length}（含自身，子孙数 = {length - 1}）")

        # 尝试读取前 30 个
        for i in range(min(length, 30)):
            try:
                ctrl = ptrs.GetElement(i)
                name = safe_str(ctrl.Name, 40)
                class_name = safe_str(ctrl.ClassName, 40)
                rect = format_rect(ctrl.BoundingRectangle)
                print(f"    [{i}] {ctrl.ControlTypeName} "
                      f"Name='{name}' Class='{class_name}' Rect={rect}")
            except Exception as e:
                print(f"    [{i}] 读取失败: {e}")
        return length
    except Exception as e:
        print(f"    FindAll 异常: {e}")
        return -1


# ========== 实验4：ControlFromPoint 点采样 ==========

def experiment_point_sampling(msg_control, label: str):
    """实验4：在消息控件不同区域进行 ControlFromPoint 采样"""
    print(f"\n  【实验4】ControlFromPoint 点采样 ({label})")
    try:
        rect = msg_control.BoundingRectangle
        w = rect.width()
        h = rect.height()

        # 采样点：左1/4、中心、右1/4
        points = [
            ("左侧区域", rect.left + w // 4, rect.top + h // 2),
            ("中心区域", rect.left + w // 2, rect.top + h // 2),
            ("右侧区域", rect.left + 3 * w // 4, rect.top + h // 2),
        ]

        for label_pt, px, py in points:
            try:
                hit = uia.ControlFromPoint(px, py)
                hit_name = safe_str(hit.Name, 40)
                hit_class = safe_str(hit.ClassName, 40)
                hit_type = hit.ControlTypeName
                hit_rect = format_rect(hit.BoundingRectangle)
                print(f"    {label_pt} ({px},{py}) → {hit_type} "
                      f"Name='{hit_name}' Class='{hit_class}' Rect={hit_rect}")

                # 判断是否命中了比 ListItemControl 更深层的控件
                if hit_type != "ListItemControl":
                    print(f"      ★ 命中了更深层控件！可能可用于发送方识别")
            except Exception as e:
                print(f"    {label_pt} ({px},{py}) → 失败: {e}")

    except Exception as e:
        print(f"    点采样异常: {e}")


# ========== 汇总分析 ==========

def analyze_findings(all_results: list[dict]):
    """汇总所有消息的分析结果"""
    print("\n" + "=" * 80)
    print("  汇总分析")
    print("=" * 80)

    has_deep_controls = False
    has_avatar = False
    has_bubble = False
    has_positional = False

    for r in all_results:
        deep = r.get("walk_controls", [])
        if deep and len(deep) > 0:
            has_deep_controls = True
            for ctrl in deep:
                name_lower = ctrl.get("name", "").lower()
                class_lower = ctrl.get("class_name", "").lower()
                type_lower = ctrl.get("type", "").lower()
                # 检查头像特征
                if "头像" in name_lower or "avatar" in name_lower or "head" in name_lower:
                    has_avatar = True
                if "image" in type_lower and 20 <= ctrl.get("w", 0) <= 80:
                    has_avatar = True
                # 检查气泡特征
                if "气泡" in name_lower or "bubble" in name_lower:
                    has_bubble = True
                # 检查位置特征
                if ctrl.get("rect"):
                    has_positional = True

    print(f"\n  发现深层控件: {'是' if has_deep_controls else '否'}")
    print(f"  发现头像控件: {'是' if has_avatar else '否'}")
    print(f"  发现气泡控件: {'是' if has_bubble else '否'}")
    print(f"  有位置信息: {'是' if has_positional else '否'}")

    print("\n  推荐方案：")
    if has_avatar:
        print("    → 可通过头像控件位置区分 self/friend（推荐）")
    elif has_deep_controls:
        print("    → 有深层控件，需进一步分析位置特征")
    else:
        print("    → UIA 控件树无法区分，建议截图/视觉方案")
        print("    → 或保留 fallback_current_window_text + strict_mode")


def main():
    print("=" * 80)
    print("  微信消息 UIA 深层控件树探测实验")
    print("=" * 80)
    print()
    print("请确认：")
    print("  1. 微信 PC 客户端已启动并登录（主机微信）")
    print("  2. 已手动打开某个联系人的聊天窗口")
    print()

    # 定位微信窗口
    print("【定位微信窗口】")
    try:
        window = find_wechat_window()
        print(f"  ✓ 窗口已定位: Name='{safe_str(window.Name)}' Class='{safe_str(window.ClassName)}'")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return

    # 定位消息列表
    print("\n【定位消息列表】")
    try:
        msg_list = find_message_list(window, timeout=5)
        list_rect = msg_list.BoundingRectangle
        print(f"  ✓ 消息列表已找到")
        print(f"    Rect: {format_rect(list_rect)}")
        print(f"    中心线 X: {(list_rect.left + list_rect.right) / 2:.1f}")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return

    # 读取最近 5 条消息
    children = msg_list.GetChildren()
    total = len(children)
    max_msg = 5
    start_idx = max(0, total - max_msg)
    recent = children[start_idx:]

    print(f"\n  消息总数: {total}，探测最后 {len(recent)} 条")

    all_results = []

    for i, child in enumerate(recent):
        idx = start_idx + i
        name = child.Name or ""
        class_name = child.ClassName or ""
        ctrl_type = child.ControlTypeName

        try:
            rect = child.BoundingRectangle
            rect_str = format_rect(rect)
        except Exception:
            rect_str = "(异常)"

        print(f"\n{'=' * 70}")
        print(f"  消息 [{idx}] Name='{safe_str(name)}' "
              f"Class='{safe_str(class_name)}' Type={ctrl_type}")
        print(f"  Rect: {rect_str}")
        print(f"{'=' * 70}")

        # 运行所有实验
        experiment_get_children(child, f"消息[{idx}]")
        walk_controls = experiment_walk_control(child, f"消息[{idx}]")
        experiment_find_all(child, f"消息[{idx}]")
        experiment_point_sampling(child, f"消息[{idx}]")

        all_results.append({
            "index": idx,
            "name": name,
            "walk_controls": walk_controls,
        })

    # 汇总
    analyze_findings(all_results)

    print("\n" + "=" * 80)
    print("  探测完成")
    print("=" * 80)


if __name__ == "__main__":
    main()
