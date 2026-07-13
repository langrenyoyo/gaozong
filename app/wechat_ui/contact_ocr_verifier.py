"""微信联系人 OCR 身份验证。"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import re
import subprocess
import unicodedata
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
    """把 OCR 引擎返回值转成 JSON 可序列化结构。"""
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    return value


def build_ocr_title_regions(rect: dict) -> dict[str, tuple[int, int, int, int]]:
    """构建微信窗口顶部标题 OCR 的两个候选区域。"""
    left = int(rect["left"])
    top = int(rect["top"])
    right = int(rect["right"])
    bottom = int(rect["bottom"])
    width = max(1, right - left)
    height = max(1, bottom - top)

    tight_local = get_chat_title_ocr_region(width, height)
    chat_panel_left = _estimate_chat_panel_left(width)
    standard_local = (
        max(chat_panel_left + 8, tight_local[0] - 12),
        8,
        min(chat_panel_left + 332, width - 20),
        min(78, height),
    )

    def _clamp_region(region: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        local_x1, local_y1, local_x2, local_y2 = region
        x1 = left + local_x1
        y1 = top + local_y1
        x2 = left + local_x2
        y2 = top + local_y2
        x1 = max(left, min(x1, right - 1))
        y1 = max(top, min(y1, bottom - 1))
        x2 = max(x1 + 1, min(x2, right))
        y2 = max(y1 + 1, min(y2, top + 78, bottom))
        return x1, y1, x2, y2

    return {
        "title_left_tight": _clamp_region(tight_local),
        "title_left_standard": _clamp_region(standard_local),
    }


def _estimate_chat_panel_left(window_width: int) -> int:
    """估算右侧聊天面板左边界，避免裁到左侧搜索框和会话列表。"""
    left_sidebar_width = 68
    conversation_list_width = 240
    return min(max(left_sidebar_width + conversation_list_width, int(window_width * 0.34)), max(0, window_width - 320))


def get_chat_title_ocr_region(window_width: int, window_height: int) -> tuple[int, int, int, int]:
    """
    返回完整微信窗口截图内部坐标系下的联系人标题 OCR 区域。
    坐标格式: left, top, right, bottom
    """
    chat_panel_left = _estimate_chat_panel_left(window_width)
    left = chat_panel_left + 12
    top = 10
    right = min(chat_panel_left + 280, window_width - 20)
    bottom = min(72, window_height)
    return left, top, max(left + 1, right), max(top + 1, bottom)


def calculate_region(rect: dict, region: str) -> tuple[int, int, int, int]:
    """计算 OCR 裁剪区域。"""
    width = int(rect["right"] - rect["left"])
    height = int(rect["bottom"] - rect["top"])
    if region == "top_title":
        return build_ocr_title_regions(rect)["title_left_standard"]
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


def _strip_trailing_pure_symbols(text: str) -> str:
    """只去掉尾部纯空白或符号，不碰字母、数字、中文。"""
    value = (text or "").rstrip()
    while value:
        ch = value[-1]
        if ch.isspace():
            value = value[:-1]
            continue
        if unicodedata.category(ch).startswith("P") or ch in "[]（）()【】<>《》『』「」":
            value = value[:-1]
            continue
        break
    return value


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


def _preprocess_top_title_image(image):
    """在内存中对标题区域做最小预处理。"""
    from PIL import ImageEnhance, ImageOps

    image = image.convert("RGB")
    width, height = image.size
    roi = image.crop((0, int(height * 0.20), int(width * 0.45), height))
    roi = roi.resize((roi.width * 4, roi.height * 4))
    return ImageEnhance.Contrast(ImageOps.grayscale(roi)).enhance(2.0)


def preprocess_top_title_image(cropped_path: str, output_path: Path) -> str:
    """对标题区域做最小预处理并保存调试文件。"""
    from PIL import Image

    with Image.open(cropped_path) as img:
        roi = _preprocess_top_title_image(img)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    roi.save(str(output_path))
    roi.close()
    return str(output_path)


def save_title_region_overlay(
    full_window_path: str,
    window_rect: dict,
    title_regions: dict[str, tuple[int, int, int, int]],
    output_path: Path,
) -> str | None:
    """在完整窗口截图上画出联系人 OCR 裁剪框。"""
    try:
        from PIL import Image, ImageDraw

        img = Image.open(full_window_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        origin_x = int(window_rect["left"])
        origin_y = int(window_rect["top"])
        colors = {
            "title_left_tight": "red",
            "title_left_standard": "orange",
        }
        for name, bbox in title_regions.items():
            x1, y1, x2, y2 = bbox
            local_box = (x1 - origin_x, y1 - origin_y, x2 - origin_x, y2 - origin_y)
            draw.rectangle(local_box, outline=colors.get(name, "red"), width=3)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path))
        return str(output_path)
    except Exception:
        return None


def run_easyocr(image_input) -> tuple[str, float, str, list, str | None, str | None]:
    """运行 EasyOCR。"""
    try:
        import easyocr
    except ImportError:
        return "", 0.0, "easyocr", [], "未安装 easyocr", "engine_not_installed"

    try:
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        if not isinstance(image_input, (str, Path)):
            import numpy as np

            image_input = np.asarray(image_input)
        raw = reader.readtext(str(image_input) if isinstance(image_input, Path) else image_input)
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
    """运行 PaddleOCR。"""
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


def run_ocr_engine(image_input, engine: str) -> tuple[str, float, str, list, str | None, str | None]:
    """按指定引擎运行 OCR。"""
    if engine == "none":
        return "", 0.0, "none", [], "OCR engine=none，未执行识别", None
    if engine == "easyocr":
        return run_easyocr(image_input)
    if engine == "paddleocr":
        return run_paddleocr(image_input)
    if engine == "tesseract":
        return run_tesseract_if_available(image_input)
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
    ocr_title_regions_tried: list[str] | None = None,
    ocr_title_region: str | None = None,
    ocr_title_candidates_by_region: dict | None = None,
) -> dict:
    """构建统一 OCR 验证结果。"""
    match = match_ocr_text_to_nickname(
        ocr_text=ocr_text,
        expected_nickname=expected_nickname,
        confidence=confidence,
        min_confidence=min_confidence,
    )
    stripped_text = _strip_trailing_pure_symbols(ocr_text)
    if stripped_text and stripped_text != (ocr_text or "").strip():
        stripped_match = match_ocr_text_to_nickname(
            ocr_text=stripped_text,
            expected_nickname=expected_nickname,
            confidence=confidence,
            min_confidence=min_confidence,
        )
        if stripped_match.get("matched") and stripped_match.get("match_method") in {
            "exact_match",
            "exact_case_insensitive_match",
            "exact_normalized_match",
        }:
            match = stripped_match

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
        "ocr_title_regions_tried": ocr_title_regions_tried or [],
        "ocr_title_region": ocr_title_region,
        "ocr_title_candidates_by_region": ocr_title_candidates_by_region or {},
    }


def _get_window_rect(hwnd: int) -> dict:
    rect = ctypes.wintypes.RECT()
    ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if not ok:
        raise RuntimeError("读取微信窗口位置失败")
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}


def _verify_top_title_ocr_in_memory(
    expected_nickname: str,
    hwnd: int,
    position: str,
    engine: str,
    min_confidence: float,
) -> dict:
    """只在内存中截取和识别标题，禁止生成任何截图或中间文件。"""
    if engine != "easyocr":
        result = build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=None,
            engine=engine,
            error="内存 OCR 仅支持 easyocr",
            failure_stage="memory_ocr_engine_unsupported",
            min_confidence=min_confidence,
        )
        result["position"] = position
        return result

    try:
        rect = _get_window_rect(hwnd)
    except Exception as exc:
        result = build_ocr_result(
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
        result["position"] = position
        return result

    from app.wechat_ui.screenshot_debug import capture_screen_result

    tried_regions: list[str] = []
    candidates_by_region: dict[str, list[str]] = {}
    best_result: dict | None = None
    last_error: str | None = None
    last_failure_stage: str | None = None

    for region_name, bbox in build_ocr_title_regions(rect).items():
        tried_regions.append(region_name)
        capture = capture_screen_result(bbox=bbox, path=None)
        image = capture.get("image")
        if not capture.get("success") or image is None:
            candidates_by_region[region_name] = []
            last_error = capture.get("error")
            last_failure_stage = capture.get("stage")
            continue

        processed = None
        try:
            processed = _preprocess_top_title_image(image)
            ocr_text, confidence, actual_engine, raw_results, error, failure_stage = run_ocr_engine(
                processed,
                engine,
            )
        finally:
            if processed is not None:
                processed.close()
            image.close()

        candidates = [
            value
            for value in (ocr_text, _strip_trailing_pure_symbols(ocr_text))
            if (value or "").strip()
        ]
        candidates_by_region[region_name] = list(dict.fromkeys(candidates))
        best_result = build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text=ocr_text,
            confidence=confidence,
            screenshot_path=None,
            cropped_path=None,
            preprocessed_path=None,
            engine=actual_engine,
            raw_results=raw_results,
            error=error,
            failure_stage=failure_stage,
            min_confidence=min_confidence,
            ocr_title_regions_tried=tried_regions[:],
            ocr_title_region=region_name,
            ocr_title_candidates_by_region=dict(candidates_by_region),
        )
        best_result["position"] = position
        if best_result.get("verified"):
            return best_result

    if best_result is None:
        best_result = build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=None,
            engine=engine,
            error=last_error,
            failure_stage=last_failure_stage or "screenshot_failed",
            min_confidence=min_confidence,
            ocr_title_regions_tried=tried_regions,
            ocr_title_candidates_by_region=candidates_by_region,
        )
    best_result["position"] = position
    return best_result


def verify_contact_by_top_title_ocr(
    expected_nickname: str,
    hwnd: int,
    position: str = "right",
    engine: str = "easyocr",
    min_confidence: float = 0.75,
    output_dir: str | Path | None = None,
    persist_artifacts: bool = True,
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

    if not persist_artifacts:
        return _verify_top_title_ocr_in_memory(
            expected_nickname=expected_nickname,
            hwnd=hwnd,
            position=position,
            engine=engine,
            min_confidence=min_confidence,
        )

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
    screenshot_path = run_dir / f"{nickname_safe}_top_title_{engine}_full.png"
    full_capture = capture_region(full_bbox, screenshot_path)
    if not full_capture["success"]:
        return build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=full_capture.get("path"),
            engine=engine,
            error=full_capture.get("error"),
            failure_stage="screenshot_failed",
            min_confidence=min_confidence,
        )

    title_regions = build_ocr_title_regions(rect)
    overlay_path = save_title_region_overlay(
        full_capture["path"],
        rect,
        title_regions,
        run_dir / "full_window_with_contact_ocr_box.png",
    )
    tried_regions: list[str] = []
    candidates_by_region: dict[str, list[str]] = {}
    cropped_paths_by_region: dict[str, str | None] = {}
    preprocessed_paths_by_region: dict[str, str | None] = {}
    best_result: dict | None = None
    last_error: str | None = None
    last_failure_stage: str | None = None
    actual_engine = engine

    for region_name in ("title_left_tight", "title_left_standard"):
        tried_regions.append(region_name)
        bbox = title_regions[region_name]
        cropped_path = run_dir / f"{nickname_safe}_top_title_{region_name}_{engine}_crop.png"
        crop_capture = capture_region(bbox, cropped_path)
        cropped_paths_by_region[region_name] = crop_capture.get("path")
        if not crop_capture["success"]:
            candidates_by_region[region_name] = []
            last_error = crop_capture.get("error")
            last_failure_stage = crop_capture.get("stage")
            continue

        preprocessed_path = None
        ocr_input_path = crop_capture["path"]
        if engine != "none":
            try:
                preprocessed_path = preprocess_top_title_image(
                    crop_capture["path"],
                    run_dir / f"{nickname_safe}_top_title_{region_name}_{engine}_preprocessed.png",
                )
                ocr_input_path = preprocessed_path
            except Exception:
                preprocessed_path = None
        preprocessed_paths_by_region[region_name] = preprocessed_path

        ocr_text, confidence, actual_engine, raw_results, error, failure_stage = run_ocr_engine(
            ocr_input_path,
            engine,
        )
        candidate_texts = [value for value in (ocr_text, _strip_trailing_pure_symbols(ocr_text)) if (value or "").strip()]
        candidates_by_region[region_name] = list(dict.fromkeys(candidate_texts))
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
            ocr_title_regions_tried=tried_regions[:],
            ocr_title_region=region_name,
            ocr_title_candidates_by_region={**candidates_by_region},
        )
        result["cropped_paths_by_region"] = dict(cropped_paths_by_region)
        result["preprocessed_paths_by_region"] = dict(preprocessed_paths_by_region)
        result["overlay_path"] = overlay_path
        best_result = result
        if result.get("verified"):
            break

    if best_result is None:
        best_result = build_ocr_result(
            expected_nickname=expected_nickname,
            region="top_title",
            ocr_text="",
            confidence=0.0,
            screenshot_path=full_capture.get("path"),
            cropped_path=cropped_paths_by_region.get("title_left_tight") or cropped_paths_by_region.get("title_left_standard"),
            engine=engine,
            error=last_error,
            failure_stage=last_failure_stage or "screenshot_failed",
            min_confidence=min_confidence,
            ocr_title_regions_tried=tried_regions,
            ocr_title_region=None,
            ocr_title_candidates_by_region=candidates_by_region,
        )
        best_result["cropped_paths_by_region"] = dict(cropped_paths_by_region)
        best_result["preprocessed_paths_by_region"] = dict(preprocessed_paths_by_region)
        best_result["overlay_path"] = overlay_path

    best_result["position"] = position
    best_result["overlay_path"] = overlay_path
    return best_result
