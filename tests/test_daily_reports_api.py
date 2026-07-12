"""Phase 8 Task 7：日报生成任务、列表、重试与安全下载 API 测试。

覆盖执行包 Task 7 Step 4 红灯项（含审批补充的两类符号链接端到端用例）。
全部用临时内存库 + 临时存储目录 + mock 9100 摘要客户端，不启动服务、不触网。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DailyReportJob
from app.services import daily_report_storage as storage

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


class _FakeSummaryClient:
    """不触网的 9100 摘要客户端替身。"""

    def summarize_daily_sales_feedback(self, payload: dict) -> dict:
        return {"llm_used": True, "summary_text": "今日整体平稳"}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """每测试隔离存储目录 + 注入 mock 摘要客户端。"""
    monkeypatch.setattr(storage, "DAILY_REPORT_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        "app.routers.daily_reports._get_summary_client",
        lambda: _FakeSummaryClient(),
    )
    yield


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permissions: list[str] | None = None,
    user_id: str = "user-1",
    username: str = "operator-a",
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        username=username,
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permissions
        if permissions is not None
        else ["auto_wechat:agent", "auto_wechat:leads"],
    )


def _client(
    context: RequestContext | None = None,
    *,
    merchant_id: str | None = "merchant-a",
    permissions: list[str] | None = None,
) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    resolved = context or _context(merchant_id=merchant_id, permissions=permissions)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_request_context_required] = lambda: resolved
    return TestClient(app)


def _db():
    return TestSession()


# ============================================================================
# 1. 单类生成成功 + 幂等
# ============================================================================

def test_generate_single_short_video_lead_success():
    client = _client()
    resp = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10",
        "report_type": "short_video_live_lead",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["jobs"]) == 1
    job = body["jobs"][0]
    assert job["report_type"] == "short_video_live_lead"
    assert job["report_variant"] == "default"
    assert job["status"] in ("generated", "partial")
    assert job["artifact_status"] == "available"
    assert job["download_available"] is True
    # 文件实际落盘
    db = _db()
    try:
        row = db.query(DailyReportJob).first()
        assert row.file_storage_key is not None
        assert row.content_sha256 is not None
        assert row.file_size_bytes > 0
        assert row.generation_token is None  # 终态清空 token
        assert row.generation_started_at is None
    finally:
        db.close()


def test_generate_idempotent_same_business_key():
    """同 (merchant, day, type, variant) 重复生成只产生一个任务行。"""
    client = _client()
    for _ in range(3):
        resp = client.post("/daily-reports/generate", json={
            "report_day": "2026-07-10",
            "report_type": "short_video_live_lead",
        })
        assert resp.status_code == 200, resp.text
    db = _db()
    try:
        assert db.query(DailyReportJob).count() == 1
    finally:
        db.close()


# ============================================================================
# 2. 默认集：有 leads 生成 4 个；无 leads 跳过 trace
# ============================================================================

def test_generate_default_set_with_leads_has_four_jobs():
    client = _client()  # 默认 agent + leads
    resp = client.post("/daily-reports/generate", json={"report_day": "2026-07-10"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = sorted(j["report_type"] for j in body["jobs"])
    assert types == sorted([
        "short_video_live_lead", "daily_sales_feedback",
        "sales_unit_cost", "lead_trace",
    ])
    assert body["skipped"] == []


def test_generate_default_set_without_leads_skips_trace():
    client = _client(permissions=["auto_wechat:agent"])  # 缺 leads
    resp = client.post("/daily-reports/generate", json={"report_day": "2026-07-10"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = sorted(j["report_type"] for j in body["jobs"])
    assert types == sorted([
        "short_video_live_lead", "daily_sales_feedback", "sales_unit_cost",
    ])
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["report_type"] == "lead_trace"
    assert body["skipped"][0]["reason"] == "PERMISSION_DENIED"


# ============================================================================
# 3. 显式 trace 权限
# ============================================================================

def test_generate_explicit_trace_without_leads_returns_403():
    client = _client(permissions=["auto_wechat:agent"])
    resp = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "lead_trace",
    })
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_generate_explicit_trace_with_leads_succeeds():
    client = _client()
    resp = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "lead_trace",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["report_type"] == "lead_trace"
    assert body["jobs"][0]["report_variant"] == "created"


# ============================================================================
# 4. 请求不接受 merchant_id（extra=forbid）
# ============================================================================

def test_generate_request_rejects_merchant_id_in_body():
    client = _client()
    resp = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "merchant_id": "merchant-fake",
    })
    assert resp.status_code == 422


# ============================================================================
# 5. 重试
# ============================================================================

def test_regenerate_success_updates_job():
    client = _client()
    created = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()
    job_id = created["jobs"][0]["id"]
    resp = client.post(f"/daily-reports/{job_id}/regenerate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["id"] == job_id


def test_regenerate_cross_merchant_returns_404():
    """跨商户统一按不存在，避免泄露任务是否存在。"""
    client_a = _client(merchant_id="merchant-a")
    created = client_a.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()
    job_id = created["jobs"][0]["id"]
    client_b = _client(merchant_id="merchant-b")
    resp = client_b.post(f"/daily-reports/{job_id}/regenerate")
    assert resp.status_code == 404


def test_regenerate_active_generating_returns_409():
    """未超时 generating 租约不被抢占。"""
    client = _client()
    created = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()
    job_id = created["jobs"][0]["id"]
    # 手动置为活跃 generating（未超时）
    db = _db()
    try:
        db.query(DailyReportJob).filter_by(id=job_id).update({
            DailyReportJob.status: "generating",
            DailyReportJob.generation_token: "occupied-token",
            DailyReportJob.generation_started_at: datetime.now(),
        })
        db.commit()
    finally:
        db.close()
    resp = client.post(f"/daily-reports/{job_id}/regenerate")
    assert resp.status_code == 409


def test_regenerate_stale_generating_is_reclaimed():
    """超时（>30 分钟）generating 可被回收。"""
    client = _client()
    created = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()
    job_id = created["jobs"][0]["id"]
    db = _db()
    try:
        db.query(DailyReportJob).filter_by(id=job_id).update({
            DailyReportJob.status: "generating",
            DailyReportJob.generation_token: "stale-token",
            DailyReportJob.generation_started_at: datetime.now() - timedelta(minutes=40),
        })
        db.commit()
    finally:
        db.close()
    resp = client.post(f"/daily-reports/{job_id}/regenerate")
    assert resp.status_code == 200, resp.text


# ============================================================================
# 6. 列表：商户过滤 + 分页 + 日期/状态筛选 + 稳定排序
# ============================================================================

def test_list_filters_by_merchant():
    """列表只返回当前商户任务，不跨商户。"""
    _client(merchant_id="merchant-a").post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    })
    _client(merchant_id="merchant-b").post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    })
    resp = _client(merchant_id="merchant-a").get("/daily-reports/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1


def test_list_filters_by_date_and_status():
    client = _client()
    client.post("/daily-reports/generate", json={
        "report_day": "2026-07-09", "report_type": "short_video_live_lead",
    })
    client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    })
    # 日期过滤
    resp = client.get("/daily-reports/", params={"report_day_from": "2026-07-10"})
    assert resp.json()["total"] == 1
    # 状态过滤（generated 或 partial 都算完成态）
    for status in ("generated", "partial"):
        r = client.get("/daily-reports/", params={"status": status})
        assert r.status_code == 200


def test_list_pagination_and_stable_order():
    client = _client()
    for day in ("2026-07-09", "2026-07-10", "2026-07-11"):
        client.post("/daily-reports/generate", json={
            "report_day": day, "report_type": "short_video_live_lead",
        })
    resp = client.get("/daily-reports/", params={"page": 1, "page_size": 2})
    body = resp.json()
    assert body["total"] == 3
    assert len(body["records"]) == 2
    # report_day DESC 稳定排序
    days = [r["report_day"] for r in body["records"]]
    assert days == ["2026-07-11", "2026-07-10"]


# ============================================================================
# 7. 下载成功 + 安全头 + 中文文件名编码
# ============================================================================

def test_download_success_chinese_filename_and_headers():
    client = _client()
    job_id = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    resp = client.get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    cd = resp.headers["content-disposition"]
    assert "attachment" in cd
    assert "UTF-8''" in cd  # RFC 5987 编码
    assert "\n" not in cd and "\r" not in cd  # 拒绝换行注入
    # 不暴露绝对路径 / storage_key
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        assert row.file_storage_key not in cd
    finally:
        db.close()
    # body 为 xlsx 字节（PK 签名）
    assert resp.content[:2] == b"PK"
    # 缓存抑制头
    assert resp.headers.get("cache-control") == "no-store"
    assert resp.headers.get("x-content-type-options") == "nosniff"


def test_download_cross_merchant_returns_404():
    client_a = _client(merchant_id="merchant-a")
    job_id = client_a.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    client_b = _client(merchant_id="merchant-b")
    resp = client_b.get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 404


def test_download_trace_without_leads_returns_403():
    # 用有 leads 的账号生成 trace 任务
    job_id = _client().post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "lead_trace",
    }).json()["jobs"][0]["id"]
    # 切到无 leads 账号下载，必须 403
    resp = _client(permissions=["auto_wechat:agent"]).get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 403


# ============================================================================
# 8. 下载完整性：无文件 / 被篡改 / 符号链接（两类）
# ============================================================================

def test_download_tampered_sha_returns_404():
    """文件被篡改（SHA 不符）不得返回内容。"""
    client = _client()
    job_id = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        path = storage.resolve_storage_path(row.file_storage_key)
        path.write_bytes(b"tampered content")
    finally:
        db.close()
    resp = client.get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 404


def test_download_missing_file_returns_404():
    """文件被删除（缺失）不得返回内容。"""
    client = _client()
    job_id = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        path = storage.resolve_storage_path(row.file_storage_key)
        path.unlink()
    finally:
        db.close()
    resp = client.get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 404


def test_download_symlink_to_outside_returns_404(monkeypatch):
    """存储目录内符号链接指向目录外文件，下载拒绝（404）。

    Windows 当前账号无 symlink 权限（WinError 1314）时，降级为
    monkeypatch validate_artifact_path 抛 ValueError，验证下载端点拒绝路径。
    """
    client = _client()
    job_id = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        path = storage.resolve_storage_path(row.file_storage_key)
        path.unlink()
        outside = path.parent.parent / "outside_evil.xlsx"
        outside.write_bytes(b"PKfake")
        real_symlink_ok = False
        try:
            os.symlink(outside, path)
            real_symlink_ok = True
        except (OSError, NotImplementedError):
            real_symlink_ok = False
    finally:
        db.close()
    if not real_symlink_ok:
        # 无权限环境：validate_artifact_path 仍会按 is_symlink 拒绝（见下方单元测试），
        # 此处直接模拟该拒绝结果，验证下载端点收到拒绝后返回 404
        def _reject(storage_key, root=None):
            raise ValueError("symlink to outside rejected")
        monkeypatch.setattr(
            "app.routers.daily_reports.validate_artifact_path", _reject,
        )
    resp = client.get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 404


def test_download_file_is_symlink_returns_404(monkeypatch):
    """最终文件本身是符号链接（指向受控目录内另一文件），下载拒绝（404）。

    无 symlink 权限时同样降级为 validate_artifact_path 拒绝。
    """
    client = _client()
    job_id = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        path = storage.resolve_storage_path(row.file_storage_key)
        real_target = path.parent / "real_target.xlsx"
        real_target.write_bytes(b"PKfake")
        path.unlink()
        real_symlink_ok = False
        try:
            os.symlink(real_target, path)
            real_symlink_ok = True
        except (OSError, NotImplementedError):
            real_symlink_ok = False
    finally:
        db.close()
    if not real_symlink_ok:
        def _reject(storage_key, root=None):
            raise ValueError("file is symlink rejected")
        monkeypatch.setattr(
            "app.routers.daily_reports.validate_artifact_path", _reject,
        )
    resp = client.get(f"/daily-reports/{job_id}/download")
    assert resp.status_code == 404


def test_validate_artifact_path_rejects_symlink_file(monkeypatch, tmp_path):
    """validate_artifact_path 对符号链接文件拒绝（is_symlink 分支，全平台覆盖）。

    不依赖系统 symlink 权限：直接 monkeypatch Path.is_symlink 让目标命中，
    验证下载链路依赖的受控校验对 symlink 文件一律拒绝。
    """
    import pathlib

    key = storage.build_storage_key(
        "short_video_live_lead", date(2026, 7, 10), storage.generate_storage_token(),
    )
    target = storage.resolve_storage_path(key, tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"PKfake")
    real_is_symlink = pathlib.Path.is_symlink

    def _fake_is_symlink(self):
        if self.resolve() == target.resolve():
            return True
        return real_is_symlink(self)

    monkeypatch.setattr(pathlib.Path, "is_symlink", _fake_is_symlink)
    with pytest.raises(ValueError):
        storage.validate_artifact_path(key, tmp_path)


# ============================================================================
# 9. 失败语义：首次失败 artifact=none；重试失败保留旧文件
# ============================================================================

def test_first_generation_failure_status_failed_artifact_none(monkeypatch):
    """build_daily_report 抛异常：status=failed，artifact=none，无文件指针。"""
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated aggregation failure")
    monkeypatch.setattr(
        "app.services.daily_report_job_service.build_daily_report", _boom,
    )
    client = _client()
    resp = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    })
    assert resp.status_code == 200, resp.text
    job = resp.json()["jobs"][0]
    assert job["status"] == "failed"
    assert job["artifact_status"] == "none"
    assert job["download_available"] is False
    db = _db()
    try:
        row = db.query(DailyReportJob).first()
        assert row.file_storage_key is None  # 不保留无效文件元数据
        assert row.content_sha256 is None
        assert row.generation_token is None  # 终态清空 token
        # 诊断结构化 code/count + 异常类型名（不暴露正文）
        diag = json.loads(row.diagnostics_json)
        assert diag[0]["code"] == "generation_failed"
        assert diag[0]["exception_type"] == "RuntimeError"
        # 响应诊断同样结构化
        assert job["diagnostics"][0]["code"] == "generation_failed"
    finally:
        db.close()


def test_regenerate_failure_keeps_previous_artifact(monkeypatch):
    """已有成功文件的重试失败：status=failed，artifact=available，保留旧 sha/size。"""
    client = _client()
    job_id = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()["jobs"][0]["id"]
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        prev_key = row.file_storage_key
        prev_sha = row.content_sha256
        prev_size = row.file_size_bytes
    finally:
        db.close()
    # 重试时聚合抛异常
    monkeypatch.setattr(
        "app.services.daily_report_job_service.build_daily_report",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("regen boom")),
    )
    resp = client.post(f"/daily-reports/{job_id}/regenerate")
    assert resp.status_code == 200, resp.text
    job = resp.json()["job"]
    assert job["status"] == "failed"
    assert job["artifact_status"] == "available"  # 保留旧文件
    assert job["download_available"] is True
    assert job["is_previous_artifact"] is True
    db = _db()
    try:
        row = db.query(DailyReportJob).filter_by(id=job_id).first()
        assert row.file_storage_key == prev_key  # 旧指针未变
        assert row.content_sha256 == prev_sha
        assert row.file_size_bytes == prev_size
    finally:
        db.close()


# ============================================================================
# 10. 响应不泄露敏感字段
# ============================================================================

def test_response_excludes_sensitive_fields():
    """DailyReportJobItem 不含 merchant_id/file_storage_key/token/绝对路径/异常正文。"""
    client = _client()
    body = client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    }).json()
    job_blob = json.dumps(body["jobs"][0])
    for sensitive in ("merchant_id", "file_storage_key", "generation_token",
                      "content_sha256", "file_size_bytes", "error_message"):
        assert sensitive not in job_blob, f"响应泄露 {sensitive}"


def test_list_response_excludes_sensitive_fields():
    client = _client()
    client.post("/daily-reports/generate", json={
        "report_day": "2026-07-10", "report_type": "short_video_live_lead",
    })
    body = _client().get("/daily-reports/").json()
    job_blob = json.dumps(body["records"])
    for sensitive in ("merchant_id", "file_storage_key", "generation_token"):
        assert sensitive not in job_blob
