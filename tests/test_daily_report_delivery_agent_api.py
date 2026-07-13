"""Phase 8-B Task 4：9000 Local Agent 附件协议红灯测试。

覆盖执行包 Task 4 合同：
- 6 端点全部 require_local_agent_context（无 token 401、错 token 401、跨商户 404）。
- claim 原子：pending→running，一次性返回 execution_token + download_ticket 明文 +
  task/delivery/attempt/target/file_name/hash/size/expires；并发/旧 attempt/另 Agent 409。
- 下载三头（X-Local-Agent-Token/X-Report-Execution-Token/X-Report-Download-Ticket）：
  常量时间比较、单次消费、过期拒绝、跨商户 404、hash/size 校验、ticket 禁止进 query。
- send-intent：二次检查 execution/downloaded/attempt/rollout/allowlist/staff active+开关+昵称/
  merchant/取消/同商户同销售 10 秒限频；通过签发 15 秒 nonce。
- result：未触发失败可重试；已触发未验证 verify_pending；全门禁+nonce 有效才 sent；
  旧 token/nonce 409；重复 sent 幂等。
- 租约回收：running 过期 + send_nonce_hash IS NULL → failed；曾签发 nonce 超时 → verify_pending。
- 旧 /wechat-tasks/{id}/result 对 send_report_attachment 返回 409/422（禁旁路）。

四层令牌只存 SHA-256，常量时间比较，响应/日志不泄露原文。不实现 Local Agent 下载客户端/
微信发送器/真实发送（Task 5-7 范围）。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import DailyReportDelivery, DailyReportJob, SalesStaff, WechatTask
from app.services import daily_report_storage as storage

# Task 4 红灯：router 未实现时 _require() 触发 pytest.fail（干净 FAIL）
try:
    from app.routers import daily_report_deliveries as _router
except ImportError:
    _router = None


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    """Local Agent 鉴权环境 + 存储目录 + get_db override。"""
    monkeypatch.setattr(storage, "DAILY_REPORT_STORAGE_DIR", tmp_path)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "LOCAL_AGENT_TOKENS",
        "merchant-a:token-a-xxx,merchant-b:token-b-yyy",
    )
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")
    import app.config as cfg
    # send-intent 二次检查需要 delivery 开启（_setup_claimable 直接建 pending 绕过 ensure 灰度）
    monkeypatch.setattr(cfg, "DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED", True)
    monkeypatch.setattr(cfg, "DAILY_REPORT_ATTACHMENT_ALLOW_FULL_ROLLOUT", True)
    monkeypatch.setattr(cfg, "DAILY_REPORT_ATTACHMENT_STAFF_ALLOWLIST", set())
    if _router is not None:
        monkeypatch.setattr("app.routers.daily_report_deliveries.require_local_agent_context", _ctx_a)
    yield


def _ctx_a(request=None):
    """测试默认返回 merchant-a 鉴权上下文（绕过真实 token 解析，聚焦协议层）。"""
    from app.auth.local_agent_auth import LocalAgentAuthContext
    return LocalAgentAuthContext(authenticated=True, merchant_id="merchant-a", auth_mode="token")


def _ctx_b(request=None):
    from app.auth.local_agent_auth import LocalAgentAuthContext
    return LocalAgentAuthContext(authenticated=True, merchant_id="merchant-b", auth_mode="token")


def _client():
    from app.main import app

    def _override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _setup_claimable(merchant_id="merchant-a", *, delivery_status="pending",
                     task_status="pending", nonce_signed=False,
                     reuse_staff_id=None, report_day=date(2026, 7, 12)) -> tuple[int, int]:
    """建 staff（或复用）+ job + delivery + WechatTask(send_report_attachment)，返回 (task_id, delivery_id)。"""
    storage_key = f"short_video_live_lead/{report_day.isoformat()}/t1.xlsx"
    db = TestSession()
    try:
        if reuse_staff_id is not None:
            s = db.get(SalesStaff, reuse_staff_id)
        else:
            s = SalesStaff(
                name="销售A", wechat_nickname="Aw3", merchant_id=merchant_id, status="active",
                enable_short_video_live_lead_report=True,
            )
            db.add(s)
            db.flush()
        job = DailyReportJob(
            merchant_id=merchant_id, report_day=report_day,
            report_type="short_video_live_lead", report_variant="default", status="generated",
            artifact_status="available", file_storage_key=storage_key,
            file_name="short_video_live_lead.xlsx", content_sha256="a" * 64, file_size_bytes=1024,
            generated_at=datetime.now(),
        )
        db.add(job)
        db.flush()
        d = DailyReportDelivery(
            merchant_id=merchant_id, report_job_id=job.id, receiver_staff_id=s.id,
            status=delivery_status, artifact_storage_key=job.file_storage_key,
            artifact_file_name=job.file_name, artifact_sha256=job.content_sha256,
            artifact_size_bytes=job.file_size_bytes, attempt_count=1,
        )
        db.add(d)
        db.flush()
        t = WechatTask(
            task_type="send_report_attachment", status=task_status,
            staff_id=s.id, target_nickname="Aw3", mode="paste_only",
            report_delivery_id=d.id, delivery_attempt_no=1,
            attachment_file_name=d.artifact_file_name, attachment_sha256=d.artifact_sha256,
            attachment_size_bytes=d.artifact_size_bytes,
        )
        if nonce_signed:
            t.send_nonce_hash = hashlib.sha256(b"nonce1").hexdigest()
            t.send_nonce_expires_at = datetime.now() + timedelta(seconds=15)
            t.send_authorized_at = datetime.now()
            t.status = "send_authorized"
        db.add(t)
        db.commit()
        return t.id, d.id
    finally:
        db.close()


def _require():
    if _router is None:
        pytest.fail("app.routers.daily_report_deliveries 未实现（Task 4 红灯）")


# ---------------------------------------------------------------------------
# pending + detail + 鉴权
# ---------------------------------------------------------------------------


def test_agent_pending_returns_tasks():
    _require()
    tid, _ = _setup_claimable()
    resp = _client().get("/daily-report-deliveries/agent/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert any(t["id"] == tid for t in data), "pending 应返回本商户 send_report_attachment 任务"


def test_agent_task_detail_cross_merchant_404(monkeypatch):
    _require()
    tid, _ = _setup_claimable("merchant-a")
    monkeypatch.setattr("app.routers.daily_report_deliveries.require_local_agent_context", _ctx_b)
    resp = _client().get(f"/daily-report-deliveries/agent/tasks/{tid}")
    assert resp.status_code == 404, "跨商户统一 404"


# ---------------------------------------------------------------------------
# claim
# ---------------------------------------------------------------------------


def test_claim_returns_tokens_and_metadata():
    _require()
    tid, _ = _setup_claimable()
    resp = _client().post(f"/daily-report-deliveries/agent/tasks/{tid}/claim")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["task_id"] == tid
    assert body["execution_token"] and len(body["execution_token"]) >= 32
    assert body["download_ticket"] and len(body["download_ticket"]) >= 32
    assert body["file_name"] == "short_video_live_lead.xlsx"
    assert body["sha256"] == "a" * 64
    assert body["size"] == 1024
    assert body["attempt_no"] == 1
    assert body["target_nickname"] == "Aw3"
    # 不泄露 storage key
    assert "storage_key" not in body


def test_claim_concurrent_409():
    _require()
    tid, _ = _setup_claimable()
    c = _client()
    first = c.post(f"/daily-report-deliveries/agent/tasks/{tid}/claim")
    second = c.post(f"/daily-report-deliveries/agent/tasks/{tid}/claim")
    assert first.status_code == 200
    assert second.status_code == 409, "并发 claim 第二个必须 409"


def test_claim_cross_merchant_404(monkeypatch):
    _require()
    tid, _ = _setup_claimable("merchant-a")
    monkeypatch.setattr("app.routers.daily_report_deliveries.require_local_agent_context", _ctx_b)
    resp = _client().post(f"/daily-report-deliveries/agent/tasks/{tid}/claim")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# attachment 下载（三头 + 单次消费 + 过期 + 跨商户）
# ---------------------------------------------------------------------------


def _claim_first(tid: int) -> dict:
    resp = _client().post(f"/daily-report-deliveries/agent/tasks/{tid}/claim")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _dl_headers(claim_body: dict, agent_token="token-a-xxx") -> dict:
    return {
        "X-Local-Agent-Token": agent_token,
        "X-Report-Execution-Token": claim_body["execution_token"],
        "X-Report-Download-Ticket": claim_body["download_ticket"],
    }


def test_download_single_use():
    _require()
    # 预置真实文件（download 会校验存在 + hash/size）
    tid, _ = _setup_claimable()
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    first = _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body),
    )
    second = _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 409, "下载票据单次消费，第二次必须拒绝"


def test_download_missing_header_rejected():
    _require()
    tid, _ = _setup_claimable()
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    # 缺 download ticket
    resp = _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment",
        headers={"X-Local-Agent-Token": "token-a-xxx", "X-Report-Execution-Token": body["execution_token"]},
    )
    assert resp.status_code in (400, 401, 422)


def test_download_cross_merchant_404(monkeypatch):
    _require()
    tid, _ = _setup_claimable("merchant-a")
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    monkeypatch.setattr("app.routers.daily_report_deliveries.require_local_agent_context", _ctx_b)
    resp = _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body, "token-b-yyy"),
    )
    assert resp.status_code == 404


def _write_artifact_file(rel: str, content: bytes) -> None:
    """写文件到 storage 模块的受控根（被 monkeypatch），并同步 delivery/task 的实际 hash/size。"""
    import hashlib as _h
    from pathlib import Path
    from app.services import daily_report_storage as st
    root = Path(st.DAILY_REPORT_STORAGE_DIR)
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    actual_sha = _h.sha256(content).hexdigest()
    db = TestSession()
    try:
        for d in db.query(DailyReportDelivery).filter_by(artifact_storage_key=rel).all():
            d.artifact_sha256 = actual_sha
            d.artifact_size_bytes = len(content)
        for t in db.query(WechatTask).filter(WechatTask.report_delivery_id.in_(
            db.query(DailyReportDelivery.id).filter_by(artifact_storage_key=rel)
        )).all():
            t.attachment_sha256 = actual_sha
            t.attachment_size_bytes = len(content)
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# send-intent（二次检查 + nonce）
# ---------------------------------------------------------------------------


def test_send_intent_issues_nonce():
    _require()
    tid, _ = _setup_claimable()
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    # 先下载（send-intent 要求 downloaded）
    _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body),
    )
    resp = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/send-intent",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={"execution_token": body["execution_token"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["send_nonce"] and len(resp.json()["send_nonce"]) >= 32


def test_send_intent_rate_limit():
    _require()
    tid, _ = _setup_claimable()
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body),
    )
    first = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/send-intent",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={"execution_token": body["execution_token"]},
    )
    assert first.status_code == 200
    # 复用同 staff 建第二 task，触发同商户同销售 10s 限频
    db = TestSession()
    staff_id = db.get(WechatTask, tid).staff_id
    db.close()
    tid2, _ = _setup_claimable(reuse_staff_id=staff_id, report_day=date(2026, 7, 13))
    _write_artifact_file("short_video_live_lead/2026-07-13/t1.xlsx", b"x" * 1024)
    body2 = _claim_first(tid2)
    _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid2}/attachment", headers=_dl_headers(body2),
    )
    second = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid2}/send-intent",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={"execution_token": body2["execution_token"]},
    )
    assert second.status_code == 429, "同商户同销售 10s 内重复 send-intent 应限频"


# ---------------------------------------------------------------------------
# result（状态规则）
# ---------------------------------------------------------------------------


def test_result_sent_when_all_gates_pass():
    _require()
    tid, _ = _setup_claimable()
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body),
    )
    si = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/send-intent",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={"execution_token": body["execution_token"]},
    )
    nonce = si.json()["send_nonce"]
    resp = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/result",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={
            "execution_token": body["execution_token"], "send_nonce": nonce,
            "success": True, "contact_verified": True,
            "downloaded": True, "pasted": True, "send_triggered": True, "message_verified": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "sent"
    assert resp.json()["delivery_status"] == "sent"


def test_result_verify_pending_when_triggered_unverified():
    _require()
    tid, _ = _setup_claimable()
    _write_artifact_file("short_video_live_lead/2026-07-12/t1.xlsx", b"x" * 1024)
    body = _claim_first(tid)
    _client().get(
        f"/daily-report-deliveries/agent/tasks/{tid}/attachment", headers=_dl_headers(body),
    )
    si = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/send-intent",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={"execution_token": body["execution_token"]},
    )
    nonce = si.json()["send_nonce"]
    # send_triggered=True 但 message_verified=False → verify_pending（不能假设 Enter 未发生）
    resp = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/result",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={
            "execution_token": body["execution_token"], "send_nonce": nonce,
            "success": True, "contact_verified": True,
            "downloaded": True, "pasted": True, "send_triggered": True, "message_verified": False,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "verify_pending"


def test_result_failed_when_not_triggered():
    _require()
    tid, _ = _setup_claimable()
    body = _claim_first(tid)
    # 未触发发送（send_triggered=False）的失败 → failed（可重试）
    resp = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/result",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={
            "execution_token": body["execution_token"], "send_nonce": None,
            "success": False, "contact_verified": False, "send_triggered": False,
            "failure_stage": "paste_failed",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "failed"


def test_result_old_execution_token_409():
    _require()
    tid, _ = _setup_claimable()
    body = _claim_first(tid)
    # 用错误 execution_token
    resp = _client().post(
        f"/daily-report-deliveries/agent/tasks/{tid}/result",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={
            "execution_token": "0" * 64, "send_nonce": None,
            "success": False, "send_triggered": False,
        },
    )
    assert resp.status_code == 409, "旧/错误 execution_token 必须 409"


# ---------------------------------------------------------------------------
# 旧通用 result 对 send_report_attachment 拒绝
# ---------------------------------------------------------------------------


def test_legacy_result_rejects_attachment_task():
    _require()
    tid, _ = _setup_claimable()
    resp = _client().post(
        f"/wechat-tasks/{tid}/result",
        headers={"X-Local-Agent-Token": "token-a-xxx"},
        json={"success": True, "verified": True, "sent": True, "raw_result": "{}"},
    )
    assert resp.status_code in (409, 422), "旧 result 对 send_report_attachment 必须拒绝"


# ---------------------------------------------------------------------------
# 租约回收
# ---------------------------------------------------------------------------


def test_reclaim_stale_running_to_failed():
    _require()
    from app.services import daily_report_delivery_service as svc
    tid, _ = _setup_claimable(task_status="running")
    db = TestSession()
    try:
        t = db.query(WechatTask).get(tid)
        t.execution_started_at = datetime.now() - timedelta(seconds=3600)
        db.commit()
    finally:
        db.close()
    svc.reclaim_stale_leases(db := TestSession(), lease_seconds=300)
    db2 = TestSession()
    try:
        t = db2.query(WechatTask).get(tid)
        assert t.status == "failed", "running 过期且未签发 nonce → failed"
    finally:
        db2.close()


def test_reclaim_stale_send_authorized_to_verify_pending():
    _require()
    from app.services import daily_report_delivery_service as svc
    tid, _ = _setup_claimable(nonce_signed=True)
    db = TestSession()
    try:
        t = db.query(WechatTask).get(tid)
        t.send_authorized_at = datetime.now() - timedelta(seconds=3600)
        db.commit()
    finally:
        db.close()
    svc.reclaim_stale_leases(TestSession(), lease_seconds=300)
    db2 = TestSession()
    try:
        t = db2.query(WechatTask).get(tid)
        assert t.status == "verify_pending", "曾签发 nonce 的超时任务保守转 verify_pending"
    finally:
        db2.close()
