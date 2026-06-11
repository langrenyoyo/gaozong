"""P0-3A 微信 Render Ready / 灰屏首次出现步骤诊断脚本

本脚本只做诊断采集，不发送消息，不调用联系人验证，不修改业务流程。
"""

import argparse
import ctypes
import ctypes.wintypes
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.wechat_ui.clipboard_utils import (  # noqa: E402
    get_clipboard_text as _get_clipboard_text,
    get_clipboard_text_win32 as _get_clipboard_text_win32,
    set_clipboard_text as _set_clipboard_text,
    set_clipboard_text_win32 as _set_clipboard_text_win32,
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "render_state"

logger = logging.getLogger("debug_wechat_render_state")
user32 = ctypes.windll.user32


STEPS = [
    "step_01_initial_state",
    "step_02_activate",
    "step_03_click_search_box",
    "step_04_ctrl_a",
    "step_05_backspace",
    "step_06_paste_nickname",
    "step_07_wait_search_results",
    "step_08_down",
    "step_09_enter",
    "step_10_wait_chat_open",
    "step_11_before_contact_verify",
    "step_12_before_send",
]


def setup_logging(run_dir: Path) -> None:
    """配置日志输出。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(run_dir / "render_state.log"), encoding="utf-8"),
        ],
    )


def parse_bool(value: str | bool) -> bool:
    """解析命令行布尔值。"""
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError(f"无法解析布尔值: {value}")


def parse_manual_observation(value: str) -> str | None:
    """解析人工观察输入。"""
    mapping = {
        "y": "normal",
        "g": "gray",
        "h": "hidden",
        "n": "other",
        "": None,
    }
    return mapping.get((value or "").strip().lower(), "other")


def safe_name(value: str) -> str:
    """生成安全文件名片段。"""
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in value)


def get_text(hwnd: int) -> str:
    """读取窗口标题。"""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def get_class_name(hwnd: int) -> str:
    """读取窗口类名。"""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_rect(hwnd: int) -> dict | None:
    """读取窗口矩形。"""
    if not hwnd:
        return None
    rect = ctypes.wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return {
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
        "width": rect.right - rect.left,
        "height": rect.bottom - rect.top,
    }


def find_wechat_hwnd() -> tuple[int | None, list[str]]:
    """定位微信窗口句柄。"""
    notes = []
    try:
        from app.wechat_ui.window_locator import find_wechat_window

        window = find_wechat_window()
        return window.NativeWindowHandle, notes
    except Exception as exc:
        notes.append(f"微信窗口定位失败: {exc}")
        return None, notes


def calculate_client_center_rect(rect: dict) -> tuple[int, int, int, int]:
    """计算客户区中心截图区域。"""
    width = rect["width"]
    height = rect["height"]
    left = rect["left"] + int(width * 0.20)
    top = rect["top"] + int(height * 0.18)
    right = rect["right"] - int(width * 0.10)
    bottom = rect["bottom"] - int(height * 0.12)
    return (left, top, right, bottom)


def save_image(img, path: Path) -> str:
    """保存图片并返回路径。"""
    img.save(str(path))
    return str(path)


def capture_images(hwnd: int, step: str, run_dir: Path) -> tuple[dict, object | None, list[str]]:
    """保存 full_window 和 client_center 两张截图。"""
    notes = []
    paths = {"full_window": None, "client_center": None}
    rect = get_rect(hwnd)
    if not rect or rect["width"] <= 0 or rect["height"] <= 0:
        return paths, None, ["窗口尺寸无效，跳过截图"]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_step = safe_name(step)

    try:
        from app.wechat_ui.screenshot_debug import grab_screen

        full_bbox = (rect["left"], rect["top"], rect["right"], rect["bottom"])
        full_img = grab_screen(bbox=full_bbox)
        paths["full_window"] = save_image(
            full_img,
            run_dir / f"{ts}_{safe_step}_full.png",
        )
    except Exception as exc:
        notes.append(f"full_window 截图失败: {exc}")

    center_img = None
    try:
        from app.wechat_ui.screenshot_debug import grab_screen

        center_bbox = calculate_client_center_rect(rect)
        center_img = grab_screen(bbox=center_bbox)
        paths["client_center"] = save_image(
            center_img,
            run_dir / f"{ts}_{safe_step}_center.png",
        )
    except Exception as exc:
        notes.append(f"client_center 截图失败: {exc}")

    return paths, center_img, notes


def calculate_pixel_metrics(img) -> dict:
    """计算截图像素指标。"""
    rgb = img.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    total = width * height
    if total <= 0:
        return {
            "white_ratio": 0.0,
            "gray_ratio": 0.0,
            "dark_ratio": 0.0,
            "low_contrast_ratio": 0.0,
            "edge_score": 0,
            "mean_rgb": [0, 0, 0],
            "std_rgb": [0, 0, 0],
        }

    sum_r = sum_g = sum_b = 0
    sum_sq_r = sum_sq_g = sum_sq_b = 0
    white_count = gray_count = dark_count = low_contrast_count = 0

    sample_stride = max(1, int((total / 120000) ** 0.5))
    sampled = 0
    values = []

    for y in range(0, height, sample_stride):
        for x in range(0, width, sample_stride):
            r, g, b = pixels[x, y]
            sampled += 1
            sum_r += r
            sum_g += g
            sum_b += b
            sum_sq_r += r * r
            sum_sq_g += g * g
            sum_sq_b += b * b
            values.append((r, g, b))

            max_c = max(r, g, b)
            min_c = min(r, g, b)
            brightness = (r + g + b) / 3
            if r > 240 and g > 240 and b > 240:
                white_count += 1
            if max_c - min_c <= 12 and 80 <= brightness <= 210:
                gray_count += 1
            if r < 45 and g < 45 and b < 45:
                dark_count += 1
            if max_c - min_c <= 10:
                low_contrast_count += 1

    mean_r = sum_r / sampled
    mean_g = sum_g / sampled
    mean_b = sum_b / sampled
    std_r = ((sum_sq_r / sampled) - mean_r * mean_r) ** 0.5
    std_g = ((sum_sq_g / sampled) - mean_g * mean_g) ** 0.5
    std_b = ((sum_sq_b / sampled) - mean_b * mean_b) ** 0.5

    edge_score = calculate_edge_score(rgb, sample_stride)

    return {
        "white_ratio": round(white_count / sampled, 4),
        "gray_ratio": round(gray_count / sampled, 4),
        "dark_ratio": round(dark_count / sampled, 4),
        "low_contrast_ratio": round(low_contrast_count / sampled, 4),
        "edge_score": int(edge_score),
        "mean_rgb": [round(mean_r, 2), round(mean_g, 2), round(mean_b, 2)],
        "std_rgb": [round(std_r, 2), round(std_g, 2), round(std_b, 2)],
    }


def calculate_edge_score(img, stride: int = 1) -> int:
    """用相邻像素差分近似边缘强度。"""
    width, height = img.size
    pixels = img.load()
    if width < 2 or height < 2:
        return 0

    total_diff = 0
    count = 0
    step = max(1, stride)
    for y in range(0, height - 1, step):
        for x in range(0, width - 1, step):
            r, g, b = pixels[x, y]
            r1, g1, b1 = pixels[x + 1, y]
            r2, g2, b2 = pixels[x, y + 1]
            total_diff += abs(r - r1) + abs(g - g1) + abs(b - b1)
            total_diff += abs(r - r2) + abs(g - g2) + abs(b - b2)
            count += 2

    return int(total_diff / count) if count else 0


def is_render_suspect(visible: bool, iconic: bool, metrics: dict) -> bool:
    """根据启发式规则判断是否疑似未渲染。"""
    if not visible or iconic:
        return False

    white_ratio = metrics.get("white_ratio", 0)
    gray_ratio = metrics.get("gray_ratio", 0)
    edge_score = metrics.get("edge_score", 0)
    std_rgb = metrics.get("std_rgb", [0, 0, 0])
    avg_std = sum(std_rgb) / len(std_rgb) if std_rgb else 0

    if white_ratio > 0.85:
        return True
    if gray_ratio > 0.75 and edge_score < 5:
        return True
    if avg_std < 8 and edge_score < 5:
        return True
    return False


def collect_state(step: str, run_dir: Path) -> dict:
    """采集单步窗口状态、截图和像素指标。"""
    hwnd, notes = find_wechat_hwnd()
    fg_hwnd = user32.GetForegroundWindow()
    rect = get_rect(hwnd) if hwnd else None
    visible = bool(user32.IsWindowVisible(hwnd)) if hwnd else False
    iconic = bool(user32.IsIconic(hwnd)) if hwnd else False

    screenshot_paths = {"full_window": None, "client_center": None}
    metrics = {
        "white_ratio": 0.0,
        "gray_ratio": 0.0,
        "dark_ratio": 0.0,
        "low_contrast_ratio": 0.0,
        "edge_score": 0,
        "mean_rgb": [0, 0, 0],
        "std_rgb": [0, 0, 0],
    }

    if hwnd:
        screenshot_paths, center_img, screenshot_notes = capture_images(hwnd, step, run_dir)
        notes.extend(screenshot_notes)
        if center_img is not None:
            metrics = calculate_pixel_metrics(center_img)
        else:
            notes.append("缺少中心区域截图，像素指标使用默认值")

    return {
        "step": step,
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "hwnd": hwnd,
        "wechat_title": get_text(hwnd) if hwnd else None,
        "wechat_class": get_class_name(hwnd) if hwnd else None,
        "visible": visible,
        "iconic": iconic,
        "foreground_hwnd": fg_hwnd,
        "foreground_title": get_text(fg_hwnd),
        "foreground_class": get_class_name(fg_hwnd),
        "is_foreground_wechat": bool(hwnd and fg_hwnd == hwnd),
        "window_rect": rect,
        "screenshot_path": screenshot_paths["full_window"],
        "screenshot_paths": screenshot_paths,
        "pixel_metrics": metrics,
        "render_suspect": is_render_suspect(visible, iconic, metrics),
        "manual_observation": None,
        "notes": notes,
    }


def calc_search_box_center(rect: dict) -> tuple[int, int]:
    """按当前微信左侧搜索框大致位置计算点击坐标。"""
    width = rect["width"]
    height = rect["height"]
    x = rect["left"] + int(width * 0.18)
    y = rect["top"] + int(height * 0.08)
    return x, y


def click_search_box() -> None:
    """点击搜索框坐标。"""
    hwnd, notes = find_wechat_hwnd()
    if not hwnd:
        raise RuntimeError("; ".join(notes) or "微信窗口未找到")
    rect = get_rect(hwnd)
    if not rect:
        raise RuntimeError("无法读取微信窗口位置")
    x, y = calc_search_box_center(rect)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def prompt_manual_observation(step: str) -> str | None:
    """请求人工观察输入。"""
    print("")
    print(f"[{step}] 请人工观察微信窗口：")
    print("* 是否灰屏？")
    print("* 是否内容正常？")
    print("* 是否搜索框出现？")
    print("* 是否搜索词出现？")
    print("* 是否聊天窗口切换？")
    raw = input("输入 y=正常, g=灰屏/灰底, h=窗口隐藏, n=其他异常, enter=继续: ")
    return parse_manual_observation(raw)


def get_clipboard_text() -> str | None:
    """读取剪贴板文本，优先使用 pyperclip，失败时使用 Win32。"""
    return _get_clipboard_text()


def set_clipboard_text(text: str) -> None:
    """设置剪贴板文本，优先使用 pyperclip，失败时使用 Win32。"""
    _set_clipboard_text(text)


def get_clipboard_text_win32() -> str | None:
    """使用 Win32 API 读取 Unicode 文本剪贴板。"""
    return _get_clipboard_text_win32()


def set_clipboard_text_win32(text: str) -> None:
    """使用 Win32 API 写入 Unicode 文本剪贴板。"""
    _set_clipboard_text_win32(text)


def first_render_suspect_step(records: list[dict]) -> str | None:
    """返回第一次 render_suspect 的步骤。"""
    for record in records:
        if record.get("render_suspect"):
            return record.get("step")
    return None


def first_manual_abnormal_step(records: list[dict]) -> str | None:
    """返回第一次人工标记 gray/hidden/other 的步骤。"""
    for record in records:
        if record.get("manual_observation") in {"gray", "hidden", "other"}:
            return record.get("step")
    return None


def append_guard_result(records: list[dict], step: str, guard_result: dict | None) -> list[str]:
    """记录前台守卫结果，返回可追加到 notes 的文本。"""
    if guard_result is None:
        return []
    records.append({
        "step": step,
        "guard_result": guard_result,
    })
    return [
        "foreground_guard: success={success}, reason={reason}, foreground={foreground}".format(
            success=guard_result.get("success"),
            reason=guard_result.get("reason"),
            foreground=guard_result.get("foreground_hwnd"),
        )
    ]


def write_json_report(run_dir: Path, report: dict) -> Path:
    """写入 JSON 报告。"""
    path = run_dir / "render_state_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_markdown_summary(run_dir: Path, report: dict) -> Path:
    """写入 Markdown 摘要。"""
    records = report["records"]
    lines = [
        "# P0-3A Render Ready 诊断摘要",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- nickname: `{report['nickname']}`",
        f"- position: `{report['position']}`",
        f"- manual_confirm: `{report['manual_confirm']}`",
        f"- use_foreground_guard: `{report.get('use_foreground_guard')}`",
        f"- require_visible_initial: `{report.get('require_visible_initial')}`",
        f"- initial_not_ready: `{report.get('initial_not_ready')}`",
        f"- screenshot_dir: `{run_dir}`",
        f"- first_render_suspect_step: `{report.get('first_render_suspect_step')}`",
        f"- first_manual_abnormal_step: `{report.get('first_manual_abnormal_step')}`",
        "",
        "| step | visible | iconic | foreground | guard_success | render_suspect | manual_observation |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in records:
        lines.append(
            "| {step} | {visible} | {iconic} | {fg} | {guard} | {suspect} | {manual} |".format(
                step=item.get("step"),
                visible=item.get("visible"),
                iconic=item.get("iconic"),
                fg=item.get("is_foreground_wechat"),
                guard=(item.get("guard_result") or {}).get("success"),
                suspect=item.get("render_suspect"),
                manual=item.get("manual_observation"),
            )
        )
    lines.append("")
    path = run_dir / "render_state_summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def ensure_foreground_for_step(step: str, reason: str) -> dict:
    """诊断脚本中按步骤执行前台守卫。"""
    from app.wechat_ui.window_locator import ensure_wechat_foreground

    hwnd, notes = find_wechat_hwnd()
    if not hwnd:
        return {
            "success": False,
            "reason": reason,
            "message": "; ".join(notes) or "微信窗口未找到",
        }
    result = ensure_wechat_foreground(hwnd, reason=reason)
    result["step"] = step
    return result


def run_step(
    step: str,
    nickname: str,
    position: str,
    use_foreground_guard: bool = True,
) -> tuple[list[str], dict | None]:
    """执行指定诊断步骤，返回 notes 和 guard_result。"""
    notes = []
    guard_result = None
    if step == "step_01_initial_state":
        return notes, guard_result
    if step == "step_02_activate":
        from app.wechat_ui.window_locator import activate_wechat_window

        result = activate_wechat_window(position=position)
        notes.append(f"activate_result: success={result.get('success')}, message={result.get('message')}")
        return notes, guard_result
    if step == "step_03_click_search_box":
        click_search_box()
        return notes, guard_result
    if step == "step_04_ctrl_a":
        import uiautomation as uia

        if use_foreground_guard:
            guard_result = ensure_foreground_for_step(step, "before_ctrl_a")
            if not guard_result.get("success"):
                return notes, guard_result
        uia.SendKeys("{Ctrl}a", waitTime=0.05)
        return notes, guard_result
    if step == "step_05_backspace":
        import uiautomation as uia

        if use_foreground_guard:
            guard_result = ensure_foreground_for_step(step, "before_backspace")
            if not guard_result.get("success"):
                return notes, guard_result
        uia.SendKeys("{Back}", waitTime=0.05)
        return notes, guard_result
    if step == "step_06_paste_nickname":
        import uiautomation as uia

        set_clipboard_text(nickname)
        time.sleep(0.1)
        if use_foreground_guard:
            guard_result = ensure_foreground_for_step(step, "before_paste_nickname")
            if not guard_result.get("success"):
                return notes, guard_result
        uia.SendKeys("{Ctrl}v", waitTime=0.05)
        return notes, guard_result
    if step == "step_07_wait_search_results":
        time.sleep(1.0)
        return notes, guard_result
    if step == "step_08_down":
        import uiautomation as uia

        if use_foreground_guard:
            guard_result = ensure_foreground_for_step(step, "before_down")
            if not guard_result.get("success"):
                return notes, guard_result
        uia.SendKeys("{Down}", waitTime=0.05)
        return notes, guard_result
    if step == "step_09_enter":
        import uiautomation as uia

        if use_foreground_guard:
            guard_result = ensure_foreground_for_step(step, "before_enter")
            if not guard_result.get("success"):
                return notes, guard_result
        uia.SendKeys("{Enter}", waitTime=0.05)
        return notes, guard_result
    if step == "step_10_wait_chat_open":
        time.sleep(2.0)
        return notes, guard_result
    if step in {"step_11_before_contact_verify", "step_12_before_send"}:
        return notes, guard_result
    notes.append(f"未知步骤: {step}")
    return notes, guard_result


def run_diagnosis(args: argparse.Namespace) -> dict:
    """执行完整诊断流程。"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(run_dir)

    logger.info(
        "开始 P0-3A Render Ready 诊断: run_id=%s, nickname=%s, position=%s",
        run_id,
        args.nickname,
        args.position,
    )

    old_clipboard = None
    try:
        old_clipboard = get_clipboard_text()
    except Exception:
        old_clipboard = None

    records = []
    guard_records = []
    initial_not_ready = False
    try:
        for step in STEPS:
            operation_notes = []
            guard_result = None
            try:
                operation_notes, guard_result = run_step(
                    step,
                    args.nickname,
                    args.position,
                    use_foreground_guard=args.use_foreground_guard,
                )
            except Exception as exc:
                operation_notes.append(f"步骤执行异常: {exc}")
                logger.exception("步骤执行异常: %s", step)

            if args.pause > 0:
                time.sleep(args.pause)

            record = collect_state(step, run_dir)
            record["guard_result"] = guard_result
            record["notes"].extend(operation_notes)
            record["notes"].extend(append_guard_result(guard_records, step, guard_result))

            if args.manual_confirm:
                record["manual_observation"] = prompt_manual_observation(step)

            records.append(record)
            logger.info(
                "%s: visible=%s iconic=%s foreground=%s render_suspect=%s manual=%s",
                step,
                record.get("visible"),
                record.get("iconic"),
                record.get("is_foreground_wechat"),
                record.get("render_suspect"),
                record.get("manual_observation"),
            )

            if (
                step == "step_01_initial_state"
                and getattr(args, "require_visible_initial", True)
                and (record.get("visible") is False or record.get("iconic") is True)
            ):
                initial_not_ready = True
                record["initial_not_ready"] = True
                record["notes"].append("请先手动打开微信主窗口，再运行诊断")
                logger.warning(
                    "初始微信窗口不可自动化: visible=%s, iconic=%s；诊断提前停止",
                    record.get("visible"),
                    record.get("iconic"),
                )
                break

    finally:
        if old_clipboard is not None:
            try:
                set_clipboard_text(old_clipboard)
            except Exception:
                pass

    report = {
        "run_id": run_id,
        "nickname": args.nickname,
        "position": args.position,
        "manual_confirm": args.manual_confirm,
        "pause": args.pause,
        "use_foreground_guard": args.use_foreground_guard,
        "require_visible_initial": getattr(args, "require_visible_initial", True),
        "initial_not_ready": initial_not_ready,
        "output_dir": str(run_dir),
        "first_render_suspect_step": first_render_suspect_step(records),
        "first_manual_abnormal_step": first_manual_abnormal_step(records),
        "guard_records": guard_records,
        "records": records,
    }
    json_path = write_json_report(run_dir, report)
    md_path = write_markdown_summary(run_dir, report)
    logger.info("JSON 报告: %s", json_path)
    logger.info("Markdown 摘要: %s", md_path)
    return report


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="P0-3A 微信 Render Ready / 灰屏首次出现步骤诊断",
    )
    parser.add_argument("--nickname", default="文件传输助手", help="测试联系人昵称")
    parser.add_argument("--position", choices=["left", "right"], default="right", help="微信窗口位置")
    parser.add_argument("--manual-confirm", type=parse_bool, default=True, help="是否每步暂停人工确认")
    parser.add_argument("--use-foreground-guard", type=parse_bool, default=True, help="键盘动作前是否执行前台焦点守卫")
    parser.add_argument("--require-visible-initial", type=parse_bool, default=True, help="初始微信不可见/最小化时是否停止诊断")
    parser.add_argument("--pause", type=float, default=1.0, help="每步操作后额外等待秒数")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出目录",
    )
    return parser


def main() -> int:
    """命令行入口。"""
    parser = build_parser()
    args = parser.parse_args()
    run_diagnosis(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
