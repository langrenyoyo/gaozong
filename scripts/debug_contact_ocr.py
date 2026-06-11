"""P0-3F 联系人身份 OCR 可行性调试脚本。

本脚本只做截图和 OCR 结果评估，不接入发送流程。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.wechat_ui.ocr_matcher import (  # noqa: E402
    SPECIAL_SYMBOLS,
    contains_special_symbol,
    match_ocr_text_to_nickname,
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "contact_ocr"
LOW_CONFIDENCE_THRESHOLD = 0.80


def safe_name(value: str) -> str:
    """生成 Windows 友好的 ASCII 文件名片段。"""
    output = []
    previous_encoded = False
    for ch in value or "":
        if re.match(r"[A-Za-z0-9_-]", ch):
            output.append(ch)
            previous_encoded = False
        elif ord(ch) > 127:
            if output:
                output.append("_")
            output.append(f"u{ord(ch):04x}")
            previous_encoded = True
        else:
            if output and output[-1] != "_":
                output.append("_")
            previous_encoded = False
    return "".join(output).strip("_") or "empty"


def contains_special_symbol(value: str) -> bool:
    """判断昵称中是否包含需要严格保留的特殊符号。"""
    return any(ch in SPECIAL_SYMBOLS for ch in value or "")


def json_safe(value):
    """将 OCR 引擎返回值转换为 JSON 可序列化结构。"""
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def evaluate_ocr_match(
    expected_nickname: str,
    ocr_text: str,
    confidence: float | None,
) -> dict:
    """评估 OCR 文本是否可确认联系人身份。"""
    match = match_ocr_text_to_nickname(
        ocr_text=ocr_text,
        expected_nickname=expected_nickname,
        confidence=confidence,
        min_confidence=LOW_CONFIDENCE_THRESHOLD,
    )
    return {
        "matched": match["matched"],
        "partial_match": match["partial_match"],
        "manual_review_required": match["manual_review_required"],
        "failure_stage": match["failure_stage"],
        "verified": match["verified"],
        "matched_text": match.get("matched_text"),
    }


def build_ocr_result(
    expected_nickname: str,
    region: str,
    ocr_text: str,
    confidence: float | None,
    screenshot_path: str | None,
    engine: str,
    cropped_path: str | None = None,
    preprocessed_path: str | None = None,
    raw_results: list | None = None,
    error: str | None = None,
    failure_stage: str | None = None,
) -> dict:
    """构建统一 OCR 调试结果。"""
    match = evaluate_ocr_match(expected_nickname, ocr_text, confidence)
    if failure_stage:
        match.update({
            "matched": False,
            "partial_match": False,
            "manual_review_required": True,
            "failure_stage": failure_stage,
        })
    return {
        "expected_nickname": expected_nickname,
        "region": region,
        "engine": engine,
        "ocr_text": ocr_text or "",
        "raw_results": raw_results or [],
        "matched": match["matched"],
        "partial_match": match["partial_match"],
        "confidence": float(confidence or 0),
        "manual_review_required": match["manual_review_required"],
        "failure_stage": match["failure_stage"],
        "screenshot_path": screenshot_path,
        "cropped_path": cropped_path,
        "preprocessed_path": preprocessed_path,
        "error": error,
    }


def get_wechat_rect(position: str) -> dict:
    from app.wechat_ui.window_locator import activate_wechat_window

    result = activate_wechat_window(position=position)
    if not result.get("success"):
        raise RuntimeError(result.get("message") or "微信窗口激活失败")
    rect = result.get("actual_rect")
    if not rect:
        raise RuntimeError("无法读取微信窗口位置")
    return rect


def check_ocr_window_readiness() -> dict:
    """Business-mode OCR preflight. Does not restore or activate WeChat."""
    from app.wechat_ui.window_locator import (
        check_wechat_ready_for_automation,
        find_wechat_window,
    )

    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
    except Exception:
        hwnd = None
    if isinstance(hwnd, int):
        return check_wechat_ready_for_automation(hwnd)
    if hwnd is None:
        return check_wechat_ready_for_automation()
    return {"success": True, "message": "non-win32 test window"}


def calculate_region(rect: dict, region: str) -> tuple[int, int, int, int]:
    """计算联系人 OCR 截图区域。"""
    width = int(rect["right"] - rect["left"])
    height = int(rect["bottom"] - rect["top"])
    if region == "top_title":
        return (
            int(rect["left"] + width * 0.36),
            int(rect["top"] + height * 0.00),
            int(rect["right"] - width * 0.06),
            int(rect["top"] + height * 0.13),
        )
    if region == "right_profile_card":
        return (
            int(rect["left"] + width * 0.58),
            int(rect["top"] + height * 0.08),
            int(rect["right"] - width * 0.02),
            int(rect["bottom"] - height * 0.08),
        )
    if region == "avatar_profile_card":
        return (
            int(rect["left"] + width * 0.36),
            int(rect["top"] + height * 0.08),
            int(rect["right"] - width * 0.10),
            int(rect["bottom"] - height * 0.10),
        )
    raise ValueError(f"不支持的区域: {region}")


def capture_region(region_bbox: tuple[int, int, int, int], path: Path) -> dict:
    from app.wechat_ui.screenshot_debug import capture_screen_result

    result = capture_screen_result(bbox=region_bbox, path=path)
    return {
        "success": result["success"],
        "path": result["path"],
        "error": result["error"],
        "stage": result["stage"],
    }


def preprocess_top_title_image(cropped_path: str, output_path: Path) -> str:
    """
    对顶部标题截图做最小预处理。

    保留左侧标题区域，裁掉右侧按钮，放大并增强对比度，
    用于改善小字号标题的 OCR 识别。
    """
    from PIL import Image, ImageEnhance, ImageOps

    img = Image.open(cropped_path).convert("RGB")
    width, height = img.size
    roi = img.crop((0, int(height * 0.20), int(width * 0.45), height))
    roi = roi.resize((roi.width * 4, roi.height * 4))
    roi = ImageEnhance.Contrast(ImageOps.grayscale(roi)).enhance(2.0)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    roi.save(str(output_path))
    return str(output_path)


def run_easyocr(image_path: str) -> tuple[str, float, str, list, str | None, str | None]:
    """运行 EasyOCR，未安装时返回 engine_not_installed。"""
    try:
        import easyocr
    except ImportError:
        return "", 0.0, "easyocr", [], "未安装 easyocr", "engine_not_installed"

    try:
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        raw = reader.readtext(image_path)
    except Exception as exc:
        return "", 0.0, "easyocr", [], str(exc), "ocr_engine_error"

    results = []
    texts = []
    confidences = []
    for item in raw:
        box, text, confidence = item
        conf = float(confidence or 0)
        texts.append(str(text))
        confidences.append(conf)
        results.append({
            "box": json_safe(box),
            "text": str(text),
            "confidence": conf,
        })
    confidence = max(confidences) if confidences else 0.0
    return " ".join(texts).strip(), confidence, "easyocr", results, None, None


def run_tesseract_if_available(image_path: str) -> tuple[str, float, str, list, str | None, str | None]:
    """
    尝试调用本机 tesseract。

    未安装时返回清晰错误；不新增依赖、不下载模型。
    """
    try:
        completed = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", "chi_sim+eng"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except FileNotFoundError:
        return "", 0.0, "tesseract", [], "本机未安装 tesseract，OCR 未执行", "engine_not_installed"
    except Exception as exc:
        return "", 0.0, "tesseract", [], str(exc), "ocr_engine_error"

    if completed.returncode != 0:
        return "", 0.0, "tesseract", [], completed.stderr.strip() or "tesseract 执行失败", "ocr_engine_error"
    text = (completed.stdout or "").strip()
    raw = [{"text": text, "confidence": 0.85 if text else 0.0}]
    return text, 0.85 if text else 0.0, "tesseract", raw, None, None


def run_paddleocr(image_path: str) -> tuple[str, float, str, list, str | None, str | None]:
    """运行 PaddleOCR，未安装时返回 engine_not_installed。"""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return "", 0.0, "paddleocr", [], "未安装 paddleocr", "engine_not_installed"

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        raw = ocr.ocr(image_path, cls=True)
    except Exception as exc:
        return "", 0.0, "paddleocr", [], str(exc), "ocr_engine_error"

    results = []
    texts = []
    confidences = []
    for page in raw or []:
        for item in page or []:
            box = item[0]
            text = item[1][0]
            conf = float(item[1][1] or 0)
            texts.append(str(text))
            confidences.append(conf)
            results.append({"box": json_safe(box), "text": str(text), "confidence": conf})
    confidence = max(confidences) if confidences else 0.0
    return " ".join(texts).strip(), confidence, "paddleocr", results, None, None


def run_ocr_engine(image_path: str, engine: str) -> tuple[str, float, str, list, str | None, str | None]:
    """按指定 engine 运行 OCR。"""
    if engine == "none":
        return "", 0.0, "none", [], "OCR engine=none，未执行识别", None
    if engine == "easyocr":
        return run_easyocr(image_path)
    if engine == "paddleocr":
        return run_paddleocr(image_path)
    if engine == "tesseract":
        return run_tesseract_if_available(image_path)
    return "", 0.0, engine, [], f"不支持的 OCR 引擎: {engine}", "ocr_engine_error"


def run_debug(args: argparse.Namespace) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = Path(args.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    mode = getattr(args, "mode", "debug")

    if mode == "business":
        ready = check_ocr_window_readiness()
        if not ready.get("success"):
            result = build_ocr_result(
                expected_nickname=args.nickname,
                region=args.region,
                ocr_text="",
                confidence=0.0,
                screenshot_path=None,
                engine=args.engine,
                error=ready.get("message"),
                failure_stage="wechat_not_ready",
            )
            result["debug_only"] = False
            result["ready_check"] = ready
            output_path = run_dir / "contact_ocr_result.json"
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            result["result_path"] = str(output_path)
            return result

    rect = get_wechat_rect(args.position)
    bbox = calculate_region(rect, args.region)
    nickname_safe = safe_name(args.nickname)
    full_bbox = (
        int(rect["left"]), int(rect["top"]),
        int(rect["right"]), int(rect["bottom"]),
    )
    screenshot_path = run_dir / f"{nickname_safe}_{args.region}_{args.engine}_full.png"
    cropped_path = run_dir / f"{nickname_safe}_{args.region}_{args.engine}_crop.png"
    full_capture = capture_region(full_bbox, screenshot_path)
    crop_capture = capture_region(bbox, cropped_path)

    if not full_capture["success"] or not crop_capture["success"]:
        error = full_capture.get("error") or crop_capture.get("error")
        result = build_ocr_result(
            expected_nickname=args.nickname,
            region=args.region,
            ocr_text="",
            confidence=0.0,
            screenshot_path=full_capture.get("path"),
            cropped_path=crop_capture.get("path"),
            engine=args.engine,
            error=error,
            failure_stage="screenshot_failed",
        )
    else:
        preprocessed_path = None
        ocr_input_path = crop_capture["path"]
        if args.engine != "none" and args.region == "top_title":
            try:
                preprocessed_path = preprocess_top_title_image(
                    crop_capture["path"],
                    run_dir / f"{nickname_safe}_{args.region}_{args.engine}_preprocessed.png",
                )
                ocr_input_path = preprocessed_path
            except Exception as exc:
                print(f"预处理失败，回退原始裁剪图: {exc}", file=sys.stderr)

        ocr_text, confidence, engine, raw_results, error, failure_stage = run_ocr_engine(
            ocr_input_path,
            args.engine,
        )
        result = build_ocr_result(
            expected_nickname=args.nickname,
            region=args.region,
            ocr_text=ocr_text,
            confidence=confidence,
            screenshot_path=full_capture["path"],
            cropped_path=crop_capture["path"],
            preprocessed_path=preprocessed_path,
            engine=engine,
            raw_results=raw_results,
            error=error,
            failure_stage=failure_stage,
        )

    output_path = run_dir / "contact_ocr_result.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["debug_only"] = mode != "business"
    result["result_path"] = str(output_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P0-3G 联系人 OCR 调试")
    parser.add_argument("--nickname", required=True, help="期望联系人昵称")
    parser.add_argument(
        "--region",
        choices=["top_title", "right_profile_card", "avatar_profile_card"],
        default="top_title",
        help="截图识别区域",
    )
    parser.add_argument("--position", choices=["left", "right"], default="right", help="微信窗口位置")
    parser.add_argument(
        "--engine",
        choices=["easyocr", "paddleocr", "tesseract", "none"],
        default="none",
        help="OCR 引擎",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument(
        "--mode",
        choices=["debug", "business"],
        default="debug",
        help="debug allows manual diagnostics; business refuses hidden/minimized WeChat",
    )
    return parser


def main() -> int:
    result = run_debug(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
