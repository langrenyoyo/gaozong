"""AI 剪辑素材库 TOS 预签名 URL 惰性重签（HIGH-03 / M05-004）单测。

覆盖 ai_edit.py 中 _refresh_expired_presigned_urls / _object_key_from_presigned_url：
- 未过期 URL 直接透传，不重签；
- 过期 URL 用 cloud_storage_key（或从 URL 解析回填）重新签名并刷新过期时间；
- presign 失败 / TOSUploader 初始化失败不阻断列表，透传旧值。
纯对象 + mock，不连数据库、不连网络。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models import AiEditMaterial
from app.routers.ai_edit import _object_key_from_presigned_url, _refresh_expired_presigned_urls

_URL = (
    "https://videoedit.tos-cn-guangzhou.volces.com/ai-edit/m_nc_1/"
    "ai-edit-tos-abc.mp4?X-Tos-Signature=sig"
)
_KEY = "ai-edit/m_nc_1/ai-edit-tos-abc.mp4"


class _FakeUploader:
    def __init__(self, *args, **kwargs):
        self.calls = []

    def presign(self, key: str) -> str:
        self.calls.append(key)
        return f"https://videoedit.tos-cn-guangzhou.volces.com/{key}?X-Tos-Signature=new"


def _material(*, url=_URL, expires_at=None, cloud_key=None) -> AiEditMaterial:
    m = AiEditMaterial(
        material_id="mat-1",
        scope="merchant",
        media_type="video",
        storage_mode="cloud_available",
        source_sha256="0" * 64,
        analysis_status="pending",
        stabilization_status="pending",
    )
    m.tos_presigned_url = url
    m.tos_presigned_expires_at = expires_at
    m.cloud_storage_key = cloud_key
    return m


@pytest.fixture
def fake_uploader(monkeypatch):
    uploader = _FakeUploader()
    monkeypatch.setattr("app.services.las_tos_uploader.TOSUploader", lambda *a, **k: uploader)
    return uploader


def test_object_key_from_presigned_url():
    assert _object_key_from_presigned_url(_URL) == _KEY


def test_object_key_from_presigned_url_bad_inputs():
    assert _object_key_from_presigned_url("") is None
    assert _object_key_from_presigned_url("https://host/") is None


def test_refresh_skips_unexpired(fake_uploader):
    m = _material(expires_at=datetime.now() + timedelta(hours=1))
    db = MagicMock()
    _refresh_expired_presigned_urls(db, [m])
    assert fake_uploader.calls == []
    assert m.tos_presigned_url == _URL
    db.commit.assert_not_called()


def test_refresh_resigns_expired_with_cloud_key(fake_uploader):
    m = _material(expires_at=datetime.now() - timedelta(hours=1), cloud_key=_KEY)
    db = MagicMock()
    _refresh_expired_presigned_urls(db, [m])
    assert fake_uploader.calls == [_KEY]
    assert m.tos_presigned_url.endswith(f"{_KEY}?X-Tos-Signature=new")
    assert m.cloud_storage_key == _KEY
    assert m.tos_presigned_expires_at > datetime.now()
    db.commit.assert_called_once()


def test_refresh_backfills_key_from_url(fake_uploader):
    # 存量数据 cloud_storage_key 为空：应从 URL 解析 key 回填并重签
    m = _material(expires_at=datetime.now() - timedelta(hours=1))
    db = MagicMock()
    _refresh_expired_presigned_urls(db, [m])
    assert m.cloud_storage_key == _KEY
    assert fake_uploader.calls == [_KEY]
    db.commit.assert_called_once()


def test_refresh_tolerates_presign_failure(fake_uploader):
    def _boom(key):
        raise RuntimeError("presign failed")

    fake_uploader.presign = _boom
    m = _material(expires_at=datetime.now() - timedelta(hours=1), cloud_key=_KEY)
    db = MagicMock()
    _refresh_expired_presigned_urls(db, [m])  # 不抛异常
    assert m.tos_presigned_url == _URL  # 透传旧值
    db.commit.assert_not_called()


def test_refresh_skips_without_url(fake_uploader):
    m = _material(url="", expires_at=datetime.now() - timedelta(hours=1))
    db = MagicMock()
    _refresh_expired_presigned_urls(db, [m])
    assert fake_uploader.calls == []
    db.commit.assert_not_called()


def test_refresh_init_failure_tolerated(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("no tos config")

    monkeypatch.setattr("app.services.las_tos_uploader.TOSUploader", _boom)
    m = _material(expires_at=datetime.now() - timedelta(hours=1), cloud_key=_KEY)
    db = MagicMock()
    _refresh_expired_presigned_urls(db, [m])  # 不抛异常
    db.commit.assert_not_called()
