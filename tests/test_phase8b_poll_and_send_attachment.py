"""Phase 8-B Task 7：Local Agent 日报附件投递编排测试（dry_run 探针，无发送）。

全替身：替身 HTTP 服务模拟 9000 delivery 协议；TestClient 驱动 Local Agent；
monkeypatch 微信 gate（前台/联系人/紧停/窗口）、下载器、剪贴板。
不启动真实微信、不访问真实联系人、不请求真实 9000/9100、不真实 Enter。

覆盖执行包 Task 7 测试矩阵：
dry_run 默认/显式、dry_run=false 阻断、无任务、探针成功 verify_pending、
下载失败、文件校验失败、gate 失败（紧停/前台/联系人/窗口）→ blocked、
探针不 send-intent 不 Enter、并发锁、server_url 缺失、claim 409、
指定 task_id 404/非 pending、跨商户 404、下载文件清理、probe 脚本自检。
"""

from __future__ import annotations

import http.server
import json
import re
import socketserver
import tempfile
import threading

import pytest

from app import local_agent_main as la


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_server_state: dict = {}


class _Mock9000Handler(http.server.BaseHTTPRequestHandler):
    """替身 9000：处理 delivery pending/detail/claim/result/send-intent。"""

    def log_message(self, *a):
        pass

    def _send_json(self, status, obj):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path.endswith("/agent/pending"):
            return self._send_json(200, _server_state.get("pending", []))
        m = re.match(r"/daily-report-deliveries/agent/tasks/(\d+)$", path)
        if m:
            tid = int(m.group(1))
            detail = _server_state.get("details", {}).get(tid)
            if detail is None:
                return self._send_json(404, {"detail": "not found"})
            return self._send_json(200, detail)
        return self._send_json(404, {"detail": "unknown"})

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length)) if length else {}

        m_claim = re.match(r"/daily-report-deliveries/agent/tasks/(\d+)/claim$", path)
        if m_claim:
            tid = int(m_claim.group(1))
            _server_state.setdefault("claim_calls", []).append(tid)
            cs = _server_state.get("claim_status", 200)
            if cs == 409:
                return self._send_json(409, {"detail": "conflict"})
            if cs == 404:
                return self._send_json(404, {"detail": "not found"})
            resp = dict(_server_state.get("claim_resp", {
                "task_id": tid, "delivery_id": 1, "attempt_no": 1,
                "target_nickname": "Aw3", "file_name": "r.xlsx",
                "sha256": "a" * 64, "size": 10,
                "execution_token": "et-1", "download_ticket": "dt-1",
                "expires_at": "2026-07-13T00:00:00",
            }))
            resp.setdefault("task_id", tid)
            return self._send_json(200, resp)

        m_intent = re.match(r"/daily-report-deliveries/agent/tasks/(\d+)/send-intent$", path)
        if m_intent:
            _server_state.setdefault("intent_calls", []).append(int(m_intent.group(1)))
            return self._send_json(200, {"send_nonce": "n", "expires_at": "2026-07-13T00:00:00"})

        m_result = re.match(r"/daily-report-deliveries/agent/tasks/(\d+)/result$", path)
        if m_result:
            tid = int(m_result.group(1))
            _server_state.setdefault("result_calls", []).append({"task_id": tid, "payload": payload})
            if payload.get("send_triggered") and payload.get("message_verified"):
                status = "sent"
            elif payload.get("blocked"):
                status = "blocked"
            elif payload.get("probe"):
                status = "verify_pending"
            elif payload.get("send_triggered"):
                status = "verify_pending"
            else:
                status = "failed"
            return self._send_json(200, {
                "task_id": tid, "status": status, "delivery_id": 1,
                "delivery_status": status, "attempt_no": 1,
            })
        return self._send_json(404, {"detail": "unknown"})


@pytest.fixture
def mock_server():
    _server_state.clear()
    _server_state.update({
        "pending": [], "details": {}, "claim_calls": [],
        "intent_calls": [], "result_calls": [], "claim_status": 200,
    })
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Mock9000Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def gate_patches(monkeypatch):
    """微信 gate 默认全通过。"""
    monkeypatch.setattr(la, "is_automation_allowed", lambda: True)
    fake_window = type("W", (), {"NativeWindowHandle": 12345, "ClassName": "WeChatMainWndForPC"})()
    monkeypatch.setattr(la, "find_wechat_window", lambda: fake_window)
    monkeypatch.setattr(la, "check_wechat_ready_for_automation", lambda hwnd: {"success": True, "message": "ok"})
    monkeypatch.setattr(la, "ensure_wechat_foreground", lambda hwnd, reason="": {"success": True, "message": "ok"})
    monkeypatch.setattr(la, "verify_current_chat_contact", lambda nick: {
        "verified": True, "partial_match": False, "manual_review_required": False,
    })


@pytest.fixture
def download_patch(monkeypatch, tmp_path):
    """替身下载器：写受控目录内合法 xlsx。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    def _fake_download(*, server_url, task_id, execution_token, download_ticket,
                       expected_name, expected_sha256, expected_size,
                       local_agent_token, max_bytes=None):
        d = tmp_path / "xg_agent_attachments" / f"task{task_id}"
        d.mkdir(parents=True, exist_ok=True)
        f = d / (expected_name or "r.xlsx")
        f.write_bytes(b"fake xlsx content")
        return f

    monkeypatch.setattr(la, "_download_report_attachment", _fake_download)
    return _fake_download


@pytest.fixture
def agent_app(mock_server, monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "test-token")
    monkeypatch.setattr(la, "start_heartbeat_loop", lambda url: None)
    from fastapi.testclient import TestClient
    app = la.create_local_agent_app(server_url=mock_server)
    return TestClient(app)


def _add_pending_task(task_id=10, nickname="Aw3"):
    _server_state["pending"] = [{
        "id": task_id, "task_type": "send_report_attachment", "status": "pending",
        "staff_id": 1, "target_nickname": nickname,
        "report_delivery_id": 1, "delivery_attempt_no": 1,
    }]


# ---------- 探针成功 / dry_run ----------

def test_probe_success_verify_pending(agent_app, gate_patches, download_patch):
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["probe"]["completed"] is True
    assert body["failure_stage"] is None
    # 回写 probe（不 sent）
    assert len(_server_state["result_calls"]) == 1
    payload = _server_state["result_calls"][0]["payload"]
    assert payload["probe"] is True
    assert payload["send_triggered"] is False
    assert payload["send_nonce"] is None
    assert _server_state["result_calls"][0]["payload"]["blocked"] is False


def test_probe_does_not_call_send_intent(agent_app, gate_patches, download_patch):
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    assert resp.json()["probe"]["completed"] is True
    assert _server_state["intent_calls"] == []  # 探针绝不 send-intent


def test_dry_run_default_true(agent_app, gate_patches, download_patch):
    """不传 dry_run 时默认 true（探针，不真实发送）。"""
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body.get("blocked") is False
    assert body["probe"]["completed"] is True


def test_dry_run_false_blocked(agent_app, gate_patches, download_patch):
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={"dry_run": False})
    body = resp.json()
    assert body["failure_stage"] == "real_send_not_enabled_in_task7"
    assert body["blocked"] is True
    assert _server_state["claim_calls"] == []  # 不 claim，不消耗任务


# ---------- 无任务 / server_url / 锁 ----------

def test_no_pending_task(agent_app, gate_patches, download_patch):
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["task_found"] is False
    assert _server_state["claim_calls"] == []


def test_server_url_not_configured(monkeypatch, gate_patches, download_patch):
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "test-token")
    monkeypatch.setattr(la, "start_heartbeat_loop", lambda url: None)
    app = la.create_local_agent_app(server_url=None)
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["failure_stage"] == "server_url_not_configured"


def test_agent_busy(agent_app, gate_patches, download_patch, monkeypatch):
    """锁被占用 → agent_busy。"""
    assert la._wechat_task_lock is not None
    la._wechat_task_lock.acquire()  # 占用锁
    try:
        resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
        assert resp.json()["failure_stage"] == "agent_busy"
    finally:
        la._wechat_task_lock.release()


# ---------- 下载 / 文件校验失败 → failed ----------

def test_probe_download_failed(agent_app, gate_patches, monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    def _raise(**kw):
        raise la.DownloadError("hash_mismatch")
    monkeypatch.setattr(la, "_download_report_attachment", _raise)
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["failure_stage"] == "download_hash_mismatch"
    assert len(_server_state["result_calls"]) == 1
    assert _server_state["result_calls"][0]["payload"]["probe"] is False
    assert _server_state["result_calls"][0]["payload"]["blocked"] is False  # failed，非 blocked


def test_probe_file_validation_failed(agent_app, gate_patches, monkeypatch, tmp_path):
    """下载文件在受控目录外 → validate_attachment_file file_outside_allowed_dir → failed。"""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    def _bad_download(**kw):
        outside = tmp_path / "evil.xlsx"  # 在 xg_agent_attachments 外
        outside.write_bytes(b"x")
        return outside
    monkeypatch.setattr(la, "_download_report_attachment", _bad_download)
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["failure_stage"] == "file_outside_allowed_dir"
    assert len(_server_state["result_calls"]) == 1


def test_probe_cleans_download_file(agent_app, gate_patches, download_patch, tmp_path):
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    assert resp.json()["probe"]["completed"] is True
    # 下载文件已清理（探针不复用）
    files = list((tmp_path / "xg_agent_attachments").rglob("*.xlsx"))
    assert files == []


# ---------- gate 失败 → blocked ----------

def test_probe_emergency_stop_blocked(agent_app, download_patch, monkeypatch):
    monkeypatch.setattr(la, "is_automation_allowed", lambda: False)
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["failure_stage"] == "emergency_stop"
    assert _server_state["result_calls"][0]["payload"]["blocked"] is True


def test_probe_wechat_window_not_found_blocked(agent_app, download_patch, gate_patches, monkeypatch):
    monkeypatch.setattr(la, "find_wechat_window", lambda: (_ for _ in ()).throw(OSError("no window")))
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    assert resp.json()["failure_stage"] == "wechat_window_not_found"
    assert _server_state["result_calls"][0]["payload"]["blocked"] is True


def test_probe_foreground_lost_blocked(agent_app, download_patch, gate_patches, monkeypatch):
    monkeypatch.setattr(la, "ensure_wechat_foreground", lambda hwnd, reason="": {"success": False, "message": "lost"})
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    assert resp.json()["failure_stage"] == "foreground_lost"
    assert _server_state["result_calls"][0]["payload"]["blocked"] is True


def test_probe_contact_not_verified_blocked(agent_app, download_patch, gate_patches, monkeypatch):
    monkeypatch.setattr(la, "verify_current_chat_contact", lambda nick: {
        "verified": False, "partial_match": True, "manual_review_required": False,
    })
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    assert resp.json()["failure_stage"] == "contact_not_verified"
    assert _server_state["result_calls"][0]["payload"]["blocked"] is True


# ---------- claim 冲突 / 指定 task_id ----------

def test_claim_conflict_409(agent_app, gate_patches, download_patch):
    _server_state["claim_status"] = 409
    _add_pending_task()
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={})
    body = resp.json()
    assert body["failure_stage"] == "claim_conflict"
    assert _server_state["result_calls"] == []  # 未回写（任务被占，无 execution_token）


def test_specified_task_not_found_404(agent_app, gate_patches, download_patch):
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={"task_id": 999})
    body = resp.json()
    assert body["failure_stage"] == "task_not_found"


def test_specified_task_not_pending(agent_app, gate_patches, download_patch):
    _server_state["details"][10] = {
        "id": 10, "status": "running", "delivery_id": 1, "attempt_no": 1,
        "target_nickname": "Aw3", "file_name": "r.xlsx", "sha256": "a" * 64, "size": 10,
    }
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={"task_id": 10})
    assert resp.json()["failure_stage"] == "task_not_pending"


def test_specified_task_probe_success(agent_app, gate_patches, download_patch):
    _server_state["details"][10] = {
        "id": 10, "status": "pending", "delivery_id": 1, "attempt_no": 1,
        "target_nickname": "Aw3", "file_name": "r.xlsx", "sha256": "a" * 64, "size": 10,
    }
    resp = agent_app.post("/agent/tasks/poll-and-send-report", json={"task_id": 10})
    assert resp.json()["probe"]["completed"] is True
    assert _server_state["claim_calls"] == [10]


# ---------- submit_delivery_result blocked/probe 分支（service 层） ----------

def test_service_submit_blocked_and_probe_branches():
    """service.submit_delivery_result 的 blocked/probe 分支与 task 状态映射。"""
    from datetime import date, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from app.models import DailyReportDelivery, DailyReportJob, SalesStaff, WechatTask
    from app.services import daily_report_delivery_service as svc
    from app.services.daily_report_delivery_service import DeliveryNotFoundError

    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, autocommit=False, autoflush=False)
    db = S()
    try:
        staff = SalesStaff(name="s1", wechat_nickname="Aw3", merchant_id="m1", status="active")
        db.add(staff); db.flush()
        job = DailyReportJob(
            merchant_id="m1", report_day=date(2026, 7, 13), report_type="short_video_live_lead",
            report_variant="default", status="generated", artifact_status="available",
            file_storage_key="k", file_name="r.xlsx", content_sha256="a" * 64,
            file_size_bytes=10, generated_at=datetime.now(),
        )
        db.add(job); db.flush()
        d = DailyReportDelivery(
            merchant_id="m1", report_job_id=job.id, receiver_staff_id=staff.id,
            artifact_storage_key="k", artifact_file_name="r.xlsx",
            artifact_sha256="a" * 64, artifact_size_bytes=10, status="running", attempt_count=1,
        )
        db.add(d); db.flush()
        t = WechatTask(
            task_type="send_report_attachment", status="running",
            staff_id=staff.id, target_nickname="Aw3", report_delivery_id=d.id,
            delivery_attempt_no=1, execution_token_hash=svc._hash_token("et-1"),
        )
        db.add(t); db.commit()

        # blocked 分支（gate 失败未触发发送 → STATUS_BLOCKED）
        r = svc.submit_delivery_result(
            db, merchant_id="m1", task_id=t.id, execution_token="et-1",
            send_nonce=None, success=False, blocked=True, failure_stage="foreground_lost",
        )
        assert r["status"] == "blocked"
        assert r["delivery_status"] == "blocked"

        # 重置 running 测 probe 分支（探针成功 → verify_pending，绝不 sent）
        db.query(WechatTask).filter_by(id=t.id).update({"status": "running"})
        db.query(DailyReportDelivery).filter_by(id=d.id).update({"status": "running"})
        db.commit()
        r2 = svc.submit_delivery_result(
            db, merchant_id="m1", task_id=t.id, execution_token="et-1",
            send_nonce=None, success=False, probe=True,
        )
        assert r2["status"] == "verify_pending"
        assert r2["delivery_status"] == "verify_pending"

        # 跨商户不可见（统一 DeliveryNotFoundError，不泄露存在性）
        with pytest.raises(DeliveryNotFoundError):
            svc.submit_delivery_result(
                db, merchant_id="other", task_id=t.id, execution_token="et-1",
                send_nonce=None, success=False, probe=True,
            )
    finally:
        db.close()


# ---------- probe 脚本自检 ----------

def test_probe_script_self_check():
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "scripts/probe_phase8b_wechat_file_message_controls.py", "--self-check"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0
    assert "self-check OK" in r.stdout
    # 脱敏：原文不出现在输出
    assert "收到" not in r.stdout
