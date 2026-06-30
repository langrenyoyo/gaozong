"""微信联系人 OCR 身份验证。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import re
import subprocess
from pathlib import Path

from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname
from app.wechat_ui.window_locator import check_wechat_ready_for_automation


DEFAULT_OUTPUT_DIR = Path("data/debug_screenshots/contact_ocr")


def safe_name(value: str) -> str:
    """生成 Windows 友好的文件名片段。"""
    output = []
    for ch in value or "":
        if re.match(r"[A-Za-z0-9_-]", ch):
            output.append(ch)
        elif ord(ch) > 127:
            if output:
                output.append("_")
            output.append(f"u{ord(ch):04x}")
        else:
            if output and output[-1] != "_":
                output.append("_")
    return "".join(output).strip("_") or "empty"


def json_safe(value):
    """把 OCR 引擎返回值转换为 JSON 可序列化结构。"""
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def calculate_region(rect: dict, region: str) -> tuple[int, int, int, int]:
    """计算 OCR 截图区域。"""
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
    raise ValueError(f"不支持的 OCR 区域: {region}")


def capture_region(region_bbox: tuple[int, int, int, int], path: Path) -> dict:
    """保存指定区域截图，失败时返回结构化错误。"""
    from app.wechat_ui.screenshot_debug import capture_screen_result

    result = capture_screen_result(bbox=region_bbox, path=path)
    return {
        "success": result["success"],
        "path": result["path"],
        "error": result["error"],
        "stage": result["stage"],
    }


def preprocess_top_title_image(cropped_path: str, output_path: Path) -> str:
    """对顶部标题截图做最小预处理，提升小字号 OCR 稳定性。"""
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
    """运行 EasyOCR，未安装时返回清晰错误。"""
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
        results.append({"box": json_safe(box), "text": str(text), "confidence": conf})
    confidence = max(confidences) if confidences else 0.0
    return " ".join(texts).strip(), confidence, "easyocr", results, None, None


def run_tesseract_if_available(image_path: str) -> tuple[str, float, str, list, str | None, str | None]:
    """尝试调用本机 tesseract。"""
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
    return text, 0.85 if text else 0.0, "tesseract", [{"text": text, "confidence": 0.85 if text else 0.0}], None, None


def run_paddleocr(image_path: str) -> tuple[str, float, str, list, str | None, str | None]:
    """运行 PaddleOCR，未安装时返回清晰错误。"""
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
    """按指定引擎运行 OCR。"""
    if engine == "none":
        return "", 0.0, "none", [], "OCR engine=none，未执行识别", None
    if engine == "easyocr":
        return run_easyocr(image_path)
    if engine == "paddleocr":
        return run_paddleocr(image_path)
    if engine == "tesseract":
        return run_tesseract_if_available(image_path)
    return "", 0.0, engine, [], f"不支持的 OCR 引擎: {engine}", "ocr_engine_error"


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
    min_confidence: float = 0.75,
) -> dict:
    """构建统一 OCR 验证结果。"""
    match = match_ocr_text_to_nickname(
        ocr_text=ocr_text,
        expected_nickname=expected_nickname,
        confidence=confidence,
        min_confidence=min_confidence,
    )
    strong_title_match = (
        region == "top_title"
        and match.get("matched")
        and match.get("match_method") in {
            "exact_match",
            "exact_case_insensitive_match",
            "exact_normalized_match",
        }
        and not failure_stage
    )
    if strong_title_match:
        match.update({
            "verified": True,
            "manual_review_required": False,
            "failure_stage": None,
        })
    if failure_stage:
        match.update({
            "verified": False,
            "matched": False,
            "matched_text": None,
            "partial_match": False,
            "manual_review_required": True,
            "failure_stage": failure_stage,
        })
    return {
        "verified": match["verified"],
        "strategy": "ocr_top_title" if region == "top_title" else f"ocr_{region}",
        "expected_nickname": expected_nickname,
        "region": region,
        "engine": engine,
        "ocr_text": ocr_text or "",
        "raw_results": raw_results or [],
        "matched": match["matched"],
        "matched_text": match.get("matched_text") or (ocr_text if match["matched"] else None),
        "match_method": match.get("match_method"),
        "partial_match": match["partial_match"],
        "confidence": float(confidence or 0),
        "manual_review_required": match["manual_review_required"],
        "failure_stage": match["failure_stage"],
        "screenshot_path": screenshot_path,
        "cropped_path": cropped_path,
        "preprocessed_path": preprocessed_path,
        "error": error,
    }


def _get_window_rect(hwnd: int) -> dict:
    rect = ctypes.wintypes.RECT()
    ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if not ok:
        raise RuntimeError("读取微信窗口位置失败")
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}


def verify_contact_by_top_title_ocr(
    expected_nickname: str,
    hwnd: int,
    position: str = "right",
    engine: str = "easyocr",
    min_confidence: float = 0.75,
    output_dir: str | Path | None = None,
) -> dict:
    """通过聊天顶部标题 OCR 验证联系人身份。"""
    ready = check_wechat_ready_for_automation(hwnd)
    if not ready.get("success"):
        result = build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=None,
            engine=engine,
            error=ready.get("message"),
            failure_stage="wechat_not_ready",
            min_confidence=min_confidence,
        )
        result["ready_check"] = ready
        return result

    from datetime import datetime

    run_dir = Path(output_dir or DEFAULT_OUTPUT_DIR) / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        rect = _get_window_rect(hwnd)
    except Exception as exc:
        return build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=None,
            engine=engine,
            error=str(exc),
            failure_stage="window_rect_failed",
            min_confidence=min_confidence,
        )

    nickname_safe = safe_name(expected_nickname)
    full_bbox = (int(rect["left"]), int(rect["top"]), int(rect["right"]), int(rect["bottom"]))
    title_bbox = calculate_region(rect, "top_title")
    screenshot_path = run_dir / f"{nickname_safe}_top_title_{engine}_full.png"
    cropped_path = run_dir / f"{nickname_safe}_top_title_{engine}_crop.png"

    full_capture = capture_region(full_bbox, screenshot_path)
    crop_capture = capture_region(title_bbox, cropped_path)
    if not full_capture["success"] or not crop_capture["success"]:
        return build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=full_capture.get("path"),
            cropped_path=crop_capture.get("path"),
            engine=engine,
            error=full_capture.get("error") or crop_capture.get("error"),
            failure_stage="screenshot_failed",
            min_confidence=min_confidence,
        )

    preprocessed_path = None
    ocr_input_path = crop_capture["path"]
    if engine != "none":
        try:
            preprocessed_path = preprocess_top_title_image(
                crop_capture["path"],
                run_dir / f"{nickname_safe}_top_title_{engine}_preprocessed.png",
            )
            ocr_input_path = preprocessed_path
        except Exception:
            preprocessed_path = None

    ocr_text, confidence, actual_engine, raw_results, error, failure_stage = run_ocr_engine(
        ocr_input_path,
        engine,
    )
    result = build_ocr_result(
        expected_nickname=expected_nickname,
        region="top_title",
        ocr_text=ocr_text,
        confidence=confidence,
        screenshot_path=full_capture["path"],
        cropped_path=crop_capture["path"],
        preprocessed_path=preprocessed_path,
        engine=actual_engine,
        raw_results=raw_results,
        error=error,
        failure_stage=failure_stage,
        min_confidence=min_confidence,
    )
    result["position"] = position
    return result
