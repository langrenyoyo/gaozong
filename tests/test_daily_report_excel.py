"""Phase 8 Task 6：日报 Excel 生成与安全文件存储测试。

覆盖执行包 Task 6 Step 3（工作簿合同）+ Step 4（存储安全）。
所有存储操作在 tmp_path 内，不触网、不连生产 DB。
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.services import daily_report_excel as excel
from app.services import daily_report_storage as storage
from app.services.daily_report_service import (
    REPORT_DAILY_SALES_FEEDBACK,
    REPORT_LEAD_TRACE,
    REPORT_SALES_UNIT_COST,
    REPORT_SHORT_VIDEO_LIVE_LEAD,
    ReportBuildResult,
)

_REPORT_DAY = date(2026, 7, 10)


# ---------------------------------------------------------------------------
# ReportBuildResult 构造 helper
# ---------------------------------------------------------------------------

def _sv_result(*, rows=None, diagnostics=()):
    return ReportBuildResult(
        report_type=REPORT_SHORT_VIDEO_LIVE_LEAD,
        report_variant="default",
        report_day=_REPORT_DAY,
        columns=("content_type", "lead_count", "retained_count", "retained_rate", "spend_amount", "private_message_count"),
        rows=rows or [],
        diagnostics=diagnostics,
    )


def _feedback_result(*, rows=None, extra_sheets=None, diagnostics=()):
    return ReportBuildResult(
        report_type=REPORT_DAILY_SALES_FEEDBACK,
        report_variant="default",
        report_day=_REPORT_DAY,
        columns=("sales_name", "overall_quality", "main_problem", "car_model_summary",
                 "budget_summary", "cooperation_level", "today_suggestion", "extra_feedback"),
        rows=rows or [],
        extra_sheets=extra_sheets or {"汇总": [], "原始总结": []},
        diagnostics=diagnostics,
    )


def _trace_result(*, rows=None, diagnostics=()):
    return ReportBuildResult(
        report_type=REPORT_LEAD_TRACE,
        report_variant="created",
        report_day=_REPORT_DAY,
        columns=("lead_id", "customer_name", "traffic_type", "content_type",
                 "ad_id", "material_id", "trace_url", "assigned_staff_name", "followup_content"),
        rows=rows or [],
        diagnostics=diagnostics,
    )


def _cost_result(*, rows=None, diagnostics=()):
    return ReportBuildResult(
        report_type=REPORT_SALES_UNIT_COST,
        report_variant="default",
        report_day=_REPORT_DAY,
        columns=("sales_name", "assigned_count", "visit_count", "deal_count", "visit_cost", "deal_cost"),
        rows=rows or [],
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# Step 3：工作簿合同
# ---------------------------------------------------------------------------

def test_workbook_short_video_live_lead_columns_and_order():
    result = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 10, "retained_count": 6,
        "retained_rate": 0.6, "spend_amount": Decimal("100.00"), "private_message_count": 5,
    }])
    wb = excel.build_daily_report_workbook(result)
    assert wb.sheetnames == ["留资管理"]
    ws = wb["留资管理"]
    headers = [c.value for c in ws[1]]
    assert headers == ["内容类型", "线索数", "留资数", "留资率", "消耗金额", "私信量"]


def test_workbook_daily_feedback_has_summary_and_raw_sheets():
    result = _feedback_result(
        rows=[{"sales_name": "张三", "overall_quality": "良好", "main_problem": "价格高",
               "car_model_summary": "宝马5系", "budget_summary": "10万",
               "cooperation_level": "高", "today_suggestion": "跟紧", "extra_feedback": "无"}],
        extra_sheets={
            "汇总": [{"summary_text": "今日整体良好"}],
            "原始总结": [{"sales_name": "张三", "raw_text": "今日总结"}],
        },
    )
    wb = excel.build_daily_report_workbook(result)
    assert wb.sheetnames == ["销售反馈", "汇总", "原始总结"]
    # 汇总：row 1 表头，row 2 数据
    assert wb["汇总"][1][0].value == "汇总"  # 表头
    assert wb["汇总"][2][0].value == "今日整体良好"  # 数据
    # 原始总结：表头 + 提交者数据
    assert wb["原始总结"][1][0].value == "销售"
    assert wb["原始总结"][1][1].value == "原始总结"
    assert wb["原始总结"][2][0].value == "张三"
    assert wb["原始总结"][2][1].value == "今日总结"


def test_workbook_missing_values_show_text_not_zero():
    result = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 5, "retained_count": 2,
        "retained_rate": None, "spend_amount": None, "private_message_count": None,
    }])
    wb = excel.build_daily_report_workbook(result)
    ws = wb["留资管理"]
    row = [c.value for c in ws[2]]
    # 留资率/消耗/私信量 None → 缺失文案，不是 0
    assert row[3] == excel.MISSING_TEXT
    assert row[4] == excel.MISSING_TEXT
    assert row[5] == excel.MISSING_TEXT
    # 已知数值保留
    assert row[1] == 5
    assert row[2] == 2


def test_workbook_rate_and_money_number_format():
    result = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 10, "retained_count": 5,
        "retained_rate": 0.5, "spend_amount": Decimal("1234.50"), "private_message_count": 7,
    }])
    wb = excel.build_daily_report_workbook(result)
    ws = wb["留资管理"]
    rate_cell = ws.cell(row=2, column=4)
    money_cell = ws.cell(row=2, column=5)
    assert rate_cell.number_format == "0.00%"
    assert money_cell.number_format == "¥#,##0.00"
    assert rate_cell.value == 0.5
    assert money_cell.value == Decimal("1234.50")


def test_workbook_no_formula_cells_formula_injection_guard():
    """销售文本/车型/备注以 = + - @ 开头，写入前置单引号，工作簿不存在公式单元格。"""
    result = _feedback_result(rows=[{
        "sales_name": "=HYPERLINK(\"https://evil\")",
        "overall_quality": "+1OVERRIDE",
        "main_problem": "-malicious",
        "car_model_summary": "@SUM(A1)",
        "budget_summary": "10万",
        "cooperation_level": "\t TAB_PREFIX",
        "today_suggestion": "\n NEWLINE_PREFIX",
        "extra_feedback": "正常文本",
    }])
    wb = excel.build_daily_report_workbook(result)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"发现公式单元格 {cell.coordinate}: {cell.value!r}"


def test_workbook_sanitize_cell_value():
    assert excel._sanitize_cell_value("=foo").startswith("'")
    assert excel._sanitize_cell_value("  +bar").startswith("'")
    assert excel._sanitize_cell_value("-baz").startswith("'")
    assert excel._sanitize_cell_value("@qux").startswith("'")
    assert excel._sanitize_cell_value("正常") == "正常"
    assert excel._sanitize_cell_value(123) == 123
    assert excel._sanitize_cell_value(None) is None


def test_workbook_freeze_panes_and_autofilter():
    result = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 1, "retained_count": 1,
        "retained_rate": 1.0, "spend_amount": Decimal("1.00"), "private_message_count": 1,
    }])
    wb = excel.build_daily_report_workbook(result)
    ws = wb["留资管理"]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref is not None


def test_workbook_empty_data_still_valid():
    """空数据仍生成合法文件。"""
    result = _sv_result(rows=[])
    wb = excel.build_daily_report_workbook(result)
    # 能保存并在 tmp_path 读回
    path = Path(__file__).resolve().parent / "_tmp_empty.xlsx"
    try:
        wb.save(path)
        loaded = load_workbook(path)
        assert loaded.sheetnames == ["留资管理"]
        assert loaded["留资管理"].max_row == 1  # 只有表头
    finally:
        path.unlink(missing_ok=True)


def test_workbook_chinese_filename_and_content(tmp_path):
    """中文文件名和内容无乱码。"""
    result = _trace_result(rows=[{
        "lead_id": 1, "customer_name": "张三", "traffic_type": "paid",
        "content_type": "short_video", "ad_id": "AD1", "material_id": "M1",
        "trace_url": "https://h/p", "assigned_staff_name": "李四",
        "followup_content": "首次分配备注中文",
    }])
    wb = excel.build_daily_report_workbook(result)
    path = tmp_path / "线索溯源_2026-07-10.xlsx"
    wb.save(path)
    loaded = load_workbook(path)
    ws = loaded["线索溯源"]
    assert ws.cell(row=2, column=2).value == "张三"
    assert ws.cell(row=2, column=8).value == "李四"
    assert ws.cell(row=2, column=9).value == "首次分配备注中文"


def test_workbook_four_report_types_all_buildable():
    """4 类报表均能构建工作簿。"""
    for result in [
        _sv_result(rows=[]),
        _feedback_result(rows=[]),
        _trace_result(rows=[]),
        _cost_result(rows=[]),
    ]:
        wb = excel.build_daily_report_workbook(result)
        assert len(wb.sheetnames) >= 1


# ---------------------------------------------------------------------------
# Step 4：存储安全
# ---------------------------------------------------------------------------

def test_storage_key_no_merchant_no_drive_no_dotdot():
    token = storage.generate_storage_token()
    key = storage.build_storage_key(REPORT_SHORT_VIDEO_LIVE_LEAD, _REPORT_DAY, token)
    assert "merchant" not in key.lower()
    assert ":" not in key
    assert ".." not in key
    assert "\\" not in key
    assert key.endswith(".xlsx")
    assert key.startswith(f"{REPORT_SHORT_VIDEO_LIVE_LEAD}/2026-07-10/")
    # token 不可预测（32 hex）
    assert re.fullmatch(r"[0-9a-f]{32}", token)


def test_storage_token_unpredictable():
    tokens = {storage.generate_storage_token() for _ in range(20)}
    assert len(tokens) == 20  # 无碰撞


def test_storage_rejects_traversal(tmp_path):
    root = tmp_path
    with pytest.raises(ValueError):
        storage.resolve_storage_path("../secret.xlsx", root)
    with pytest.raises(ValueError):
        storage.resolve_storage_path("a/../../secret.xlsx", root)
    with pytest.raises(ValueError):
        storage.resolve_storage_path("a/b/../../etc/passwd.xlsx", root)


def test_storage_rejects_absolute_and_backslash(tmp_path):
    root = tmp_path
    with pytest.raises(ValueError):
        storage.resolve_storage_path("C:/evil.xlsx", root)
    with pytest.raises(ValueError):
        storage.resolve_storage_path("a\\b.xlsx", root)
    with pytest.raises(ValueError):
        storage.resolve_storage_path("/abs/path.xlsx", root)


def test_storage_rejects_hidden_segment_and_non_xlsx(tmp_path):
    root = tmp_path
    with pytest.raises(ValueError):
        storage.resolve_storage_path(".hidden/secret.xlsx", root)
    with pytest.raises(ValueError):
        storage.resolve_storage_path("a/b/secret.txt", root)
    with pytest.raises(ValueError):
        storage.resolve_storage_path("", root)


def test_storage_resolves_within_root(tmp_path):
    root = tmp_path
    key = storage.build_storage_key(REPORT_LEAD_TRACE, _REPORT_DAY, storage.generate_storage_token())
    target = storage.resolve_storage_path(key, root)
    assert target.resolve().is_relative_to(root.resolve())


def test_storage_atomic_write_sha_and_size(tmp_path):
    root = tmp_path
    result = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 3, "retained_count": 2,
        "retained_rate": 0.6667, "spend_amount": Decimal("99.50"), "private_message_count": 4,
    }])
    wb = excel.build_daily_report_workbook(result)
    key = storage.build_storage_key(REPORT_SHORT_VIDEO_LIVE_LEAD, _REPORT_DAY, storage.generate_storage_token())
    sha256, size = storage.save_workbook_to_storage(wb, key, root)
    # sha256 与磁盘一致
    target = storage.resolve_storage_path(key, root)
    assert target.exists()
    disk_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert disk_sha == sha256
    assert size == target.stat().st_size
    assert size > 0


def test_save_workbook_version_no_temp_left(tmp_path):
    """成功写入后无临时文件残留。"""
    result = _cost_result(rows=[{
        "sales_name": "合计", "assigned_count": 2, "visit_count": 1,
        "deal_count": 0, "visit_cost": Decimal("300.0"), "deal_cost": None,
    }])
    wb = excel.build_daily_report_workbook(result)
    target = tmp_path / "cost.xlsx"
    excel.save_workbook_version(wb, target)
    tmp_files = [p for p in tmp_path.iterdir() if p.name.startswith(".daily_report_")]
    assert tmp_files == []
    assert target.exists()


def test_save_workbook_version_failed_write_cleans_temp(tmp_path, monkeypatch):
    """写入失败时清理临时文件，不留半成品。"""
    result = _sv_result(rows=[])
    wb = excel.build_daily_report_workbook(result)
    target = tmp_path / "sub" / "out.xlsx"

    # 让 workbook.save 抛错模拟失败
    def _boom(path):
        raise OSError("simulated write failure")
    monkeypatch.setattr(wb, "save", _boom)

    with pytest.raises(OSError):
        excel.save_workbook_version(wb, target)
    # 临时文件被清理
    tmp_files = [p for p in tmp_path.iterdir() if p.name.startswith(".daily_report_")]
    assert tmp_files == []
    # 目标未生成
    assert not target.exists()


def test_save_workbook_version_overwrites_atomically(tmp_path):
    """重生成同 path 用原子替换；旧内容被新内容覆盖。"""
    result1 = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 1, "retained_count": 1,
        "retained_rate": 1.0, "spend_amount": Decimal("1.00"), "private_message_count": 1,
    }])
    result2 = _sv_result(rows=[{
        "content_type": "短视频", "lead_count": 2, "retained_count": 2,
        "retained_rate": 1.0, "spend_amount": Decimal("2.00"), "private_message_count": 2,
    }])
    target = tmp_path / "v.xlsx"
    wb1 = excel.build_daily_report_workbook(result1)
    excel.save_workbook_version(wb1, target)
    first_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    wb2 = excel.build_daily_report_workbook(result2)
    excel.save_workbook_version(wb2, target)
    second_sha = hashlib.sha256(target.read_bytes()).hexdigest()
    assert first_sha != second_sha


def test_verify_workbook_has_no_formulas_helper(tmp_path):
    """落盘文件无公式单元格。"""
    result = _feedback_result(rows=[{
        "sales_name": "=evil", "overall_quality": "好", "main_problem": "x",
        "car_model_summary": "x", "budget_summary": "x", "cooperation_level": "x",
        "today_suggestion": "x", "extra_feedback": "x",
    }])
    wb = excel.build_daily_report_workbook(result)
    path = tmp_path / "guard.xlsx"
    wb.save(path)
    assert excel.verify_workbook_has_no_formulas(path) is True


def test_validate_artifact_rejects_symlink_and_dir(tmp_path):
    root = tmp_path
    key = storage.build_storage_key(REPORT_SALES_UNIT_COST, _REPORT_DAY, storage.generate_storage_token())
    target = storage.resolve_storage_path(key, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 目录代替文件
    target.mkdir()
    with pytest.raises(ValueError):
        storage.validate_artifact_path(key, root)
    target.rmdir()
