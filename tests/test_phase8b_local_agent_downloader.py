"""Phase 8-B Task 5：Local Agent 安全下载器测试。

覆盖执行包 Task 5 测试矩阵：正常流式下载、30x 拒绝、Content-Length 超限、实际字节超限、
截断、MIME 错误、大小不符、哈希不符、文件名穿越、符号链接、网络中断、原子替换、失败清理。

token/ticket 只进 header；日志只记 task_id/code/exception_type。不接入微信发送器、不触发真实发送。
"""

from __future__ import annotations

import hashlib
import http.server
import platform
import socketserver
import threading
from pathlib import Path

import pytest

try:
    from app.local_agent_main import DownloadError, _download_report_attachment
except ImportError:
    _download_report_attachment = None
    DownloadError = None  # type: ignore[assignment]


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
OK_BYTES = b"xlsx_content_ok_for_phase8b"
OK_SHA = hashlib.sha256(OK_BYTES).hexdigest()
OK_SIZE = len(OK_BYTES)
WRONG_BYTES = b"wrong_content_phase8b"
WRONG_SIZE = len(WRONG_BYTES)


def _require():
    if _download_report_attachment is None:
        pytest.fail("app.local_agent_main._download_report_attachment 未实现（Task 5 红灯）")


class _MockHandler(http.server.BaseHTTPRequestHandler):
    """按 path 中的 task_id 返回不同场景响应。"""

    def log_message(self, *a):  # 静默
        pass

    def _task_id(self) -> int:
        parts = self.path.split("/")
        for i, p in enumerate(parts):
            if p == "tasks" and i + 1 < len(parts) and parts[i + 1].isdigit():
                return int(parts[i + 1])
        return 1

    def do_GET(self):  # noqa: N802  http.server 协议方法
        tid = self._task_id()
        if tid == 2:  # 302 重定向（必须被拒）
            self.send_response(302)
            self.send_header("Location", "/daily-report-deliveries/agent/tasks/1/attachment")
            self.end_headers()
            return
        if tid == 3:  # Content-Length 声明超限
            self.send_response(200)
            self.send_header("Content-Type", XLSX_MIME)
            self.send_header("Content-Length", "999999")
            self.end_headers()
            return
        if tid == 4:  # 截断：声明 1024 实际 100
            self.send_response(200)
            self.send_header("Content-Type", XLSX_MIME)
            self.send_header("Content-Length", "1024")
            self.end_headers()
            self.wfile.write(b"x" * 100)
            return
        if tid == 5:  # MIME 错误
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(OK_SIZE))
            self.end_headers()
            self.wfile.write(OK_BYTES)
            return
        if tid == 6:  # 内容不符（size/hash 都不匹配 expected）
            data = WRONG_BYTES
            self.send_response(200)
            self.send_header("Content-Type", XLSX_MIME)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if tid == 7:  # 500
            self.send_response(500)
            self.end_headers()
            return
        if tid == 8:  # 实际字节超限（不发 Content-Length，流式累计触发）
            data = b"x" * 50
            self.send_response(200)
            self.send_header("Content-Type", XLSX_MIME)
            self.end_headers()
            self.wfile.write(data)
            return
        if tid == 9:  # 写一半中断连接
            self.send_response(200)
            self.send_header("Content-Type", XLSX_MIME)
            self.send_header("Content-Length", str(OK_SIZE + 100))
            self.end_headers()
            self.wfile.write(OK_BYTES[:10])
            self.wfile.flush()
            self._close_connection = True  # type: ignore[attr-defined]
            return
        # 默认 ok（task_id == 1 或其他）
        self.send_response(200)
        self.send_header("Content-Type", XLSX_MIME)
        self.send_header("Content-Disposition", 'attachment; filename="r.xlsx"')
        self.send_header("Content-Length", str(OK_SIZE))
        self.end_headers()
        self.wfile.write(OK_BYTES)


@pytest.fixture
def mock_server():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _MockHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _tmp_root(tmp_path, monkeypatch):
    """隔离临时目录（xg_agent_attachments 在 tmp_path 下）。"""
    import tempfile
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    yield


def _dl(mock_server, *, task_id=1, expected_name="r.xlsx",
        expected_sha=OK_SHA, expected_size=OK_SIZE, max_bytes=None):
    return _download_report_attachment(
        server_url=mock_server, task_id=task_id,
        execution_token="et-phase8b", download_ticket="dt-phase8b",
        expected_name=expected_name, expected_sha256=expected_sha,
        expected_size=expected_size, local_agent_token="lat-phase8b",
        max_bytes=max_bytes,
    )


def test_normal_streaming_download(mock_server, tmp_path):
    _require()
    path = _dl(mock_server)
    assert path.exists()
    assert path.read_bytes() == OK_BYTES
    assert path.name == "r.xlsx"
    # .part 不残留（原子替换）
    assert not list(path.parent.glob("*.part"))


def test_redirect_rejected(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=2)
    # 30x 必须被拒（不跟随）；自定义 opener 不重定向 → urllib 抛 HTTPError → http_302
    assert exc.value.code == "http_302"


def test_content_length_exceeds_limit(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=3, max_bytes=100)
    assert exc.value.code == "content_length_exceeds_limit"


def test_byte_limit_exceeded(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=8, max_bytes=10)
    assert exc.value.code == "byte_limit_exceeded"


def test_truncated_detected(mock_server):
    _require()
    # 声明 1024 实际 100，流提前结束 → size_mismatch（total != expected_size）
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=4, expected_size=1024)
    assert exc.value.code in {"size_mismatch", "network_error"}


def test_wrong_mime_rejected(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=5)
    assert exc.value.code == "mime_mismatch"


def test_size_mismatch_rejected(mock_server):
    _require()
    # server 返回 wrong_content（19 字节），expected 用 OK_SIZE（24）→ size_mismatch
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=6, expected_size=OK_SIZE)
    assert exc.value.code == "size_mismatch"


def test_hash_mismatch_rejected(mock_server):
    _require()
    # server 返回 WRONG_BYTES，expected_size 匹配但 sha 不匹配 → hash_mismatch
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=6, expected_size=WRONG_SIZE, expected_sha="0" * 64)
    assert exc.value.code == "hash_mismatch"


def test_http_500_rejected(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=7)
    assert exc.value.code == "http_500"


def test_filename_traversal_rejected(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, expected_name="../evil.xlsx")
    assert exc.value.code == "filename_unsafe"


def test_filename_not_xlsx_rejected(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, expected_name="r.txt")
    assert exc.value.code == "filename_not_xlsx"


def test_network_interrupt_rejected(mock_server):
    _require()
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=9, expected_size=OK_SIZE + 100)
    # 写一半中断 → size_mismatch（total != expected）或 network_error/io_error
    assert exc.value.code in {"size_mismatch", "network_error", "io_error"}


def test_atomic_replace_no_part_residue(mock_server, tmp_path):
    _require()
    path = _dl(mock_server)
    assert path.exists()
    # 同目录无 .part 残留
    parts = list(path.parent.glob("*.part"))
    assert parts == []


def test_failure_cleans_part(mock_server, tmp_path):
    _require()
    with pytest.raises(DownloadError):
        _dl(mock_server, task_id=5)  # MIME 错误，写了 .part 后失败
    tmp_root = tmp_path / "xg_agent_attachments"
    parts = list(tmp_root.rglob("*.part")) if tmp_root.exists() else []
    assert parts == [], "失败后 .part 必须清理"


@pytest.mark.skipif(platform.system() == "Windows", reason="Windows 符号链接需管理员，跳过")
def test_final_path_symlink_rejected(mock_server, tmp_path):
    _require()
    import os
    tmp_root = tmp_path / "xg_agent_attachments" / "task1"
    tmp_root.mkdir(parents=True, exist_ok=True)
    target = tmp_root / "real.xlsx"
    target.write_bytes(b"real")
    link = tmp_root / "r.xlsx"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlink 不可用")
    with pytest.raises(DownloadError) as exc:
        _dl(mock_server, task_id=1)
    assert exc.value.code == "final_path_symlink"
