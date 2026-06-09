"""微信消息截图 + 像素/气泡位置识别实验脚本

目的：判断是否可以通过截图识别消息气泡方向和颜色，
从而区分主机消息（self，绿色气泡靠右）和销售消息（friend，白色气泡靠左）。

主机微信场景：
  - self（主机发出）= 绿色气泡，靠右侧
  - friend（销售发来）= 白色/灰色气泡，靠左侧
  - 销售回复"收到，已添加微信"应出现在左侧

使用方法：
    cd E:\work\project\auto_wechat
    python scripts/debug_wechat_screenshot.py
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


def safe_str(s: str, max_len: int = 60) -> str:
    if not s:
        return ""
    if len(s) > max_len:
        s = s[:max_len] + "..."
    return s.encode("gbk", errors="replace").decode("gbk")


def take_screenshot(hwnd, rect) -> "PIL.Image":
    """通过 Win32 API 截取指定区域"""
    import ctypes.wintypes

    user32 = ctypes.windll.user32
    # 获取窗口 DC
    hwnd_int = int(hwnd) if not isinstance(hwnd, int) else hwnd

    # 使用 PrintWindow 截取窗口
    from PIL import ImageGrab

    # 直接用 ImageGrab 截取指定区域
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    img = ImageGrab.grab(bbox)
    return img


def analyze_green_bubbles(img, list_rect_dict: dict):
    """
    在截图中检测绿色气泡区域。

    微信绿色气泡典型 RGB 范围：
      R: 80-180, G: 180-255, B: 80-160
    """
    from PIL import Image
    import numpy as np

    arr = np.array(img)
    h, w = arr.shape[:2]

    # 绿色气泡颜色范围（微信典型值）
    green_mask = (
        (arr[:, :, 0] >= 60) & (arr[:, :, 0] <= 200) &   # R
        (arr[:, :, 1] >= 170) & (arr[:, :, 1] <= 255) &   # G（高）
        (arr[:, :, 2] >= 60) & (arr[:, :, 2] <= 180) &    # B
        (arr[:, :, 1] > arr[:, :, 0]) &                    # G > R
        (arr[:, :, 1] > arr[:, :, 2])                      # G > B
    )

    # 白色气泡颜色范围
    white_mask = (
        (arr[:, :, 0] >= 230) & (arr[:, :, 0] <= 255) &
        (arr[:, :, 1] >= 230) & (arr[:, :, 1] <= 255) &
        (arr[:, :, 2] >= 230) & (arr[:, :, 2] <= 255)
    )

    green_count = int(green_mask.sum())
    white_count = int(white_mask.sum())

    # 找绿色区域的水平分布
    mid_x = w // 2
    green_left = int(green_mask[:, :mid_x].sum())
    green_right = int(green_mask[:, mid_x:].sum())

    # 找白色区域的水平分布
    white_left = int(white_mask[:, :mid_x].sum())
    white_right = int(white_mask[:, mid_x:].sum())

    results = {
        "image_size": {"width": w, "height": h},
        "green_pixel_count": green_count,
        "white_pixel_count": white_count,
        "green_distribution": {
            "left_half": green_left,
            "right_half": green_right,
            "ratio": round(green_right / green_left, 2) if green_left > 0 else float('inf'),
        },
        "white_distribution": {
            "left_half": white_left,
            "right_half": white_right,
            "ratio": round(white_right / white_left, 2) if white_left > 0 else float('inf'),
        },
    }

    # 推断
    if green_right > green_left * 2:
        results["green_side"] = "right（绿色气泡靠右 = self 消息）"
    elif green_left > green_right * 2:
        results["green_side"] = "left（绿色气泡靠左，不符合预期）"
    else:
        results["green_side"] = "even（均匀分布，无法判断）"

    if white_left > white_right * 2:
        results["white_side"] = "left（白色气泡靠左 = friend 消息）"
    elif white_right > white_left * 2:
        results["white_side"] = "right（白色气泡靠右，不符合预期）"
    else:
        results["white_side"] = "even（均匀分布，无法判断）"

    # 用连通区域分析找气泡候选框
    bubbles = _find_bubble_regions(green_mask, "green", min_area=500)
    white_bubbles = _find_bubble_regions(white_mask, "white", min_area=500)

    results["green_bubbles"] = bubbles[:10]
    results["white_bubbles"] = white_bubbles[:10]

    return results


def _find_bubble_regions(mask, color_type: str, min_area: int = 500) -> list[dict]:
    """用简单行扫描找连通区域（不依赖 OpenCV）"""
    import numpy as np

    h, w = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    regions = []

    # 简单的 flood fill 找连通区域
    for y in range(0, h, 4):  # 步长4加速
        for x in range(0, w, 4):
            if mask[y, x] and not visited[y, x]:
                # BFS
                queue = [(y, x)]
                min_r, min_c = y, x
                max_r, max_c = y, x
                area = 0
                visited[y, x] = True

                while queue and area < 50000:
                    cy, cx = queue.pop(0)
                    area += 1
                    min_r = min(min_r, cy)
                    min_c = min(min_c, cx)
                    max_r = max(max_r, cy)
                    max_c = max(max_c, cx)

                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            queue.append((ny, nx))

                if area >= min_area:
                    center_x = (min_c + max_c) / 2
                    regions.append({
                        "color": color_type,
                        "rect": {"top": int(min_r), "left": int(min_c),
                                 "bottom": int(max_r), "right": int(max_c)},
                        "area": int(area),
                        "center_x": round(center_x, 1),
                    })

    # 按面积降序
    regions.sort(key=lambda r: r["area"], reverse=True)
    return regions


def main():
    from PIL import Image

    print("=" * 80)
    print("  微信消息截图 + 像素/气泡位置识别实验")
    print("=" * 80)
    print()

    # 确保输出目录存在
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "debug")
    os.makedirs(output_dir, exist_ok=True)

    # 定位微信窗口
    print("【定位微信窗口】")
    try:
        window = find_wechat_window()
        print(f"  ✓ 窗口已定位: Name='{safe_str(window.Name)}'")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return

    # 定位消息列表
    print("\n【定位消息列表】")
    try:
        msg_list = find_message_list(window, timeout=5)
        list_rect = msg_list.BoundingRectangle
        print(f"  ✓ 消息列表已找到")
        print(f"    Rect: ({list_rect.left}, {list_rect.top}) - ({list_rect.right}, {list_rect.bottom}) "
              f"[{list_rect.width()}x{list_rect.height()}]")
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return

    # 截取消息列表区域
    print("\n【截取消息列表区域】")
    try:
        img = take_screenshot(window.NativeWindowHandle, list_rect)
        screenshot_path = os.path.join(output_dir, "wechat_chat_area.png")
        img.save(screenshot_path)
        print(f"  ✓ 截图已保存: {screenshot_path}")
        print(f"    图片大小: {img.width}x{img.height}")
    except Exception as e:
        print(f"  ✗ 截图失败: {e}")
        return

    # 像素分析
    print("\n【像素分析：绿色/白色气泡识别】")
    list_rect_dict = {
        "left": list_rect.left, "top": list_rect.top,
        "right": list_rect.right, "bottom": list_rect.bottom,
    }
    try:
        analysis = analyze_green_bubbles(img, list_rect_dict)

        print(f"  绿色像素总数: {analysis['green_pixel_count']}")
        print(f"  白色像素总数: {analysis['white_pixel_count']}")
        print(f"  绿色分布: 左={analysis['green_distribution']['left_half']}, "
              f"右={analysis['green_distribution']['right_half']}, "
              f"左右比={analysis['green_distribution']['ratio']}")
        print(f"  绿色侧: {analysis['green_side']}")
        print()
        print(f"  白色分布: 左={analysis['white_distribution']['left_half']}, "
              f"右={analysis['white_distribution']['right_half']}, "
              f"左右比={analysis['white_distribution']['ratio']}")
        print(f"  白色侧: {analysis['white_side']}")
        print()

        # 气泡候选框
        print(f"  绿色气泡候选: {len(analysis['green_bubbles'])} 个")
        for b in analysis['green_bubbles'][:5]:
            r = b['rect']
            print(f"    rect=({r['left']},{r['top']})-({r['right']},{r['bottom']}) "
                  f"area={b['area']} center_x={b['center_x']}")

        print(f"\n  白色气泡候选: {len(analysis['white_bubbles'])} 个")
        for b in analysis['white_bubbles'][:5]:
            r = b['rect']
            print(f"    rect=({r['left']},{r['top']})-({r['right']},{r['bottom']}) "
                  f"area={b['area']} center_x={b['center_x']}")

        # 综合推断
        print("\n  【综合推断】")
        mid_x = img.width // 2
        green_right = sum(1 for b in analysis['green_bubbles'] if b['center_x'] > mid_x)
        green_left = sum(1 for b in analysis['green_bubbles'] if b['center_x'] <= mid_x)
        white_right = sum(1 for b in analysis['white_bubbles'] if b['center_x'] > mid_x)
        white_left = sum(1 for b in analysis['white_bubbles'] if b['center_x'] <= mid_x)

        print(f"    绿色气泡: 左侧={green_left} 右侧={green_right}")
        print(f"    白色气泡: 左侧={white_left} 右侧={white_right}")

        if green_right > green_left and white_left > white_right:
            print(f"    ✓ 结论：绿色靠右(self=主机)，白色靠左(friend=销售)")
            print(f"    ✓ 截图方案可行！")
        elif green_right > green_left:
            print(f"    △ 结论：绿色靠右(self=主机)，但白色分布不明确")
            print(f"    △ 截图方案部分可行，需结合消息文本定位")
        else:
            print(f"    ✗ 结论：气泡分布不符合预期，截图方案暂不可用")

    except Exception as e:
        print(f"  ✗ 像素分析失败: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("  实验完成")
    print(f"  截图路径: {screenshot_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
