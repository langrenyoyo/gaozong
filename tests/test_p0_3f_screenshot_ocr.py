"""P0-3F 截图链路与联系人 OCR 调试测试。"""

from pathlib import Path


class _FakeFunc:
    def __init__(self, func):
        self.func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.func(*args)


class _FakeUser32:
    def __init__(self, dc_handle):
        self.dc_handle = dc_handle
        self.ReleaseDC = _FakeFunc(lambda hwnd, hdc: 1)
        self.GetDC = _FakeFunc(lambda hwnd: dc_handle)
        self.GetSystemMetrics = _FakeFunc(lambda index: 100)


class _FakeGdi32:
    def __init__(self):
        self.mem_dc = 0x100000000 + 11
        self.bitmap = 0x100000000 + 22
        self.old_obj = 0x100000000 + 33
        self.restored = False
        self.CreateCompatibleDC = _FakeFunc(lambda hdc: self.mem_dc)
        self.DeleteDC = _FakeFunc(lambda hdc: 1)
        self.CreateCompatibleBitmap = _FakeFunc(lambda hdc, width, height: self.bitmap)
        self.SelectObject = _FakeFunc(self._select_object)
        self.BitBlt = _FakeFunc(lambda *args: 1)
        self.GetDIBits = _FakeFunc(lambda *args: 1)
        self.DeleteObject = _FakeFunc(lambda handle: 1)

    def _select_object(self, hdc, obj):
        if obj == self.old_obj:
            self.restored = True
        return self.old_obj


def test_screenshot_handles_64bit_handles(monkeypatch):
    from app.wechat_ui import screenshot_debug

    user32 = _FakeUser32(dc_handle=0x100000000 + 1)
    gdi32 = _FakeGdi32()

    monkeypatch.setattr(screenshot_debug, "_get_screenshot_api", lambda: (user32, gdi32))

    img = screenshot_debug.grab_screen(bbox=(0, 0, 2, 2))

    assert img.size == (2, 2)
    assert user32.GetDC.restype is screenshot_debug.wintypes.HDC
    assert gdi32.BitBlt.restype is screenshot_debug.wintypes.BOOL
    assert gdi32.GetDIBits.restype == screenshot_debug.ctypes.c_int
    assert gdi32.restored is True


def test_screenshot_failure_returns_error_not_exception(monkeypatch):
    from app.wechat_ui import screenshot_debug

    user32 = _FakeUser32(dc_handle=1)
    gdi32 = _FakeGdi32()
    gdi32.BitBlt = _FakeFunc(lambda *args: 0)
    monkeypatch.setattr(screenshot_debug, "_get_screenshot_api", lambda: (user32, gdi32))

    result = screenshot_debug.capture_screen_result(bbox=(0, 0, 2, 2))

    assert result["success"] is False
    assert result["path"] is None
    assert result["stage"] == "bitblt_failed"
    assert "BitBlt" in result["error"]


def test_screenshot_stability_report_format(tmp_path):
    from scripts.debug_screenshot_stability import build_stability_report

    entries = [
        {"success": True, "mode": "full_window", "elapsed_ms": 10, "path": "a.png"},
        {"success": False, "mode": "center_region", "elapsed_ms": 3, "error": "失败"},
    ]
    report = build_stability_report(
        run_id="unit",
        repeat=1,
        output_dir=tmp_path,
        entries=entries,
    )

    assert report["run_id"] == "unit"
    assert report["total"] == 2
    assert report["success_count"] == 1
    assert report["failure_count"] == 1
    assert report["success_rate"] == 0.5
    assert Path(report["json_path"]).name == "screenshot_stability_report.json"
    assert Path(report["markdown_path"]).name == "screenshot_stability_summary.md"


def test_contact_ocr_result_schema():
    from scripts.debug_contact_ocr import build_ocr_result

    result = build_ocr_result(
        expected_nickname="Aw3",
        region="top_title",
        ocr_text="Aw3",
        confidence=0.91,
        screenshot_path="shot.png",
        engine="mock",
    )

    assert result["expected_nickname"] == "Aw3"
    assert result["region"] == "top_title"
    assert result["matched"] is True
    assert result["manual_review_required"] is False
    assert result["failure_stage"] is None


def test_ocr_match_requires_expected_nickname():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("Aw3", "当前聊天 Aw3", 0.9)

    assert result["matched"] is True
    assert result["partial_match"] is False
    assert result["manual_review_required"] is False


def test_ocr_partial_match_requires_manual_review():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("啊东、", "啊东", 0.9)

    assert result["matched"] is False
    assert result["partial_match"] is True
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "partial_match_special_symbol_missing"


def test_ocr_low_confidence_requires_manual_review():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("Aw3", "Aw3", 0.5)

    assert result["matched"] is True
    assert result["verified"] is False
    assert result["manual_review_required"] is True
    assert result["failure_stage"] == "low_confidence"


def test_special_symbol_nickname_requires_exact_match():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("啊东、", "资料卡：啊东", 0.95)

    assert result["matched"] is False
    assert result["partial_match"] is True
    assert result["manual_review_required"] is True


def test_debug_contact_ocr_supports_engine_arg():
    from scripts.debug_contact_ocr import build_parser

    args = build_parser().parse_args([
        "--nickname", "Aw3",
        "--region", "top_title",
        "--position", "right",
        "--engine", "easyocr",
    ])

    assert args.engine == "easyocr"


def test_easyocr_result_schema():
    from scripts.debug_contact_ocr import build_ocr_result

    result = build_ocr_result(
        expected_nickname="Aw3",
        region="top_title",
        ocr_text="aw3",
        confidence=0.91,
        screenshot_path="full.png",
        cropped_path="crop.png",
        engine="easyocr",
        raw_results=[{"text": "aw3", "confidence": 0.91}],
    )

    assert result["engine"] == "easyocr"
    assert result["raw_results"] == [{"text": "aw3", "confidence": 0.91}]
    assert result["cropped_path"] == "crop.png"
    assert result["matched"] is True


def test_aw3_case_insensitive_match():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("Aw3", "聊天标题 aw3", 0.9)

    assert result["matched"] is True
    assert result["manual_review_required"] is False


def test_chinese_special_symbol_requires_exact_match():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("啊东、", "啊东、", 0.9)

    assert result["matched"] is True
    assert result["partial_match"] is False


def test_chinese_partial_match_requires_manual_review_p0_3g():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("啊东、", "啊东", 0.9)

    assert result["matched"] is False
    assert result["partial_match"] is True
    assert result["failure_stage"] == "partial_match_special_symbol_missing"
    assert result["manual_review_required"] is True


def test_ocr_empty_text_failure_stage():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("Aw3", "", 0.9)

    assert result["matched"] is False
    assert result["failure_stage"] == "ocr_text_empty"


def test_ocr_wrong_text_failure_stage():
    from scripts.debug_contact_ocr import evaluate_ocr_match

    result = evaluate_ocr_match("啊东、", "AW3", 0.9)

    assert result["matched"] is False
    assert result["failure_stage"] == "ocr_text_wrong"


def test_crop_path_is_saved(tmp_path, monkeypatch):
    import argparse
    from scripts import debug_contact_ocr

    def fake_capture(bbox, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")
        return {"success": True, "path": str(path), "error": None, "stage": None}

    monkeypatch.setattr(
        debug_contact_ocr,
        "get_wechat_rect",
        lambda position: {"left": 0, "top": 0, "right": 100, "bottom": 100},
    )
    monkeypatch.setattr(debug_contact_ocr, "capture_region", fake_capture)

    args = argparse.Namespace(
        nickname="Aw3",
        region="top_title",
        position="right",
        engine="none",
        output_dir=str(tmp_path),
    )
    result = debug_contact_ocr.run_debug(args)

    assert Path(result["screenshot_path"]).exists()
    assert Path(result["cropped_path"]).exists()
    assert "Aw3_top_title_none_crop" in Path(result["cropped_path"]).name


def test_nickname_safe_filename():
    from scripts.debug_contact_ocr import safe_name

    assert safe_name("Aw3") == "Aw3"
    assert safe_name("啊东、") == "u554a_u4e1c_u3001"


def test_ocr_raw_result_is_json_safe():
    import json
    from scripts.debug_contact_ocr import json_safe

    class FakeInt32:
        def item(self):
            return 123

    converted = json_safe([[FakeInt32(), FakeInt32()]])

    assert converted == [[123, 123]]
    json.dumps(converted)
