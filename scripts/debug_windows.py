"""Windows 顶层窗口探测脚本

用于诊断微信窗口定位失败的问题。
打印所有顶层窗口信息，重点标记疑似微信窗口。

使用方法：
    cd E:\work\project\auto_wechat
    python scripts/debug_windows.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ctypes
import comtypes

# 初始化 COM
try:
    comtypes.CoInitialize()
except Exception:
    pass

import uiautomation as uia


# 疑似微信窗口的匹配规则
WECHAT_NAME_EXACT = {"Weixin", "微信", "WeChat"}
WECHAT_NAME_CONTAINS = ["微信", "Weixin", "WeChat", "wechat"]
WECHAT_CLASS_CONTAINS = ["mmui", "WeChat", "Weixin", "Qt", "Chrome_WidgetWin"]


def is_suspected_wechat(name: str, class_name: str) -> bool:
    """判断是否为疑似微信窗口"""
    if not name:
        name = ""
    if not class_name:
        class_name = ""

    name_lower = name.lower()
    class_lower = class_name.lower()

    # 精确匹配
    if name in WECHAT_NAME_EXACT:
        return True

    # 模糊匹配 Name
    for keyword in WECHAT_NAME_CONTAINS:
        if keyword.lower() in name_lower:
            return True

    # 模糊匹配 ClassName
    for keyword in WECHAT_CLASS_CONTAINS:
        if keyword.lower() in class_lower:
            return True

    return False


def format_rect(rect) -> str:
    """格式化矩形区域"""
    if rect is None:
        return "(无)"
    return f"({rect.left}, {rect.top}) - ({rect.right}, {rect.bottom}) [{rect.width()}x{rect.height()}]"


def safe_str(s: str) -> str:
    """安全转字符串，避免 GBK 编码错误"""
    if not s:
        return ""
    return s.encode("gbk", errors="replace").decode("gbk")


def main():
    print("=" * 80)
    print("  Windows 顶层窗口探测 - 微信窗口诊断")
    print("=" * 80)

    # 方式1：通过 FindWindowW 尝试
    print("\n【方式1】ctypes.FindWindowW 尝试：")
    for title in ["Weixin", "微信", "WeChat"]:
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        print(f"  FindWindowW(None, '{title}') → HWND = {hwnd}")

    # 方式2：通过 Desktop 遍历所有顶层窗口
    print("\n【方式2】Desktop 顶层窗口列表：")
    desktop = uia.GetRootControl()
    children = desktop.GetChildren()

    print(f"  顶层窗口总数: {len(children)}")
    print()

    suspected = []

    for i, child in enumerate(children):
        name = child.Name or ""
        class_name = child.ClassName or ""
        auto_id = child.AutomationId or ""
        ctrl_type = child.ControlTypeName
        hwnd = child.NativeWindowHandle
        is_offscreen = child.IsOffscreen

        try:
            rect = child.BoundingRectangle
            rect_str = format_rect(rect)
            area = rect.width() * rect.height() if rect else 0
        except Exception:
            rect_str = "(异常)"
            area = 0

        suspected_flag = is_suspected_wechat(name, class_name)

        if suspected_flag:
            suspected.append({
                "index": i,
                "name": name,
                "class_name": class_name,
                "hwnd": hwnd,
                "is_offscreen": is_offscreen,
                "area": area,
            })

        # 只打印疑似微信窗口，或者有名字且面积较大的窗口
        if suspected_flag:
            marker = "★ 微信疑似"
        elif name and area > 10000:
            marker = ""
        else:
            continue

        print(f"  [{i:3d}] {safe_str(marker)}")
        print(f"        Name:            {safe_str(name)}")
        print(f"        ClassName:       {safe_str(class_name)}")
        print(f"        ControlType:     {ctrl_type}")
        print(f"        AutomationId:    {safe_str(auto_id)}")
        print(f"        HWND:            {hwnd} (0x{hwnd:X})" if hwnd else f"        HWND:            (none)")
        print(f"        IsOffscreen:     {is_offscreen}")
        print(f"        BoundingRect:    {rect_str}")
        print()

    # 汇总疑似微信窗口
    print("=" * 80)
    print(f"  疑似微信窗口: {len(suspected)} 个")
    print("=" * 80)

    for s in suspected:
        print(f"  [{s['index']}] Name={safe_str(s['name'])}, Class={safe_str(s['class_name'])}, "
              f"HWND={s['hwnd']}, Offscreen={s['is_offscreen']}, Area={s['area']}")

    if not suspected:
        print("\n  未找到任何疑似微信窗口。请检查微信是否已启动。")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
