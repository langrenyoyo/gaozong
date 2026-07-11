"""9100 Milvus readiness 只读检查逻辑测试。

P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1 / 任务第四节、第八节。
全程 mock pymilvus，不连接真实 Milvus，不创建/修改/写入/删除任何 collection 或向量。

覆盖：
- 全绿 readiness（配置完整 → 认证 → collection → schema 维度 → 轻量探测）
- MILVUS_URI / COLLECTION 缺失 → MILVUS_CONFIG_MISSING（第3、5项）
- database 不存在 → MILVUS_DB_NOT_FOUND（第4项）
- 认证失败 → MILVUS_AUTH_FAILED（第6项）
- 维度不一致 → MILVUS_DIMENSION_MISMATCH（第7项，含配置层 + collection 实际层）
- collection 不存在 → MILVUS_COLLECTION_NOT_FOUND（第8项）
- Milvus 不可达不回退 SQLite（第9项）
- 轻量探测失败 → MILVUS_QUERY_FAILED
- 只读约束（不调用 create_index/load/upsert/delete）
- 不泄露密码或完整 URI
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


# ---------- mock pymilvus 构造 ----------

def _make_schema_fields(dim: int = 2048):
    """构造能通过 _validate_collection_schema 的完整 field 列表。"""
    field_defs = [
        "chunk_id", "embedding", "chunk_text", "document_id", "chunk_index",
        "tenant_id", "merchant_id", "douyin_account_id", "category_key",
        "category_id", "source_type", "source_title", "source_hash",
        "content_hash", "status", "created_at", "updated_at",
    ]
    fields = []
    for name in field_defs:
        field = MagicMock()
        field.name = name
        field.params = {"dim": dim} if name == "embedding" else {}
        fields.append(field)
    return fields


class _FailingQueryCollection:
    """num_entities 访问抛异常的 collection（模拟轻量探测失败）。"""

    def __init__(self, dim: int = 2048) -> None:
        self.schema = MagicMock()
        self.schema.fields = _make_schema_fields(dim)

    @property
    def num_entities(self):
        raise Exception("query timeout")


def _make_mock_pymilvus(
    *,
    dim: int = 2048,
    has_collection: bool = True,
    connect_side_effect=None,
    query_ok: bool = True,
):
    """构造可控 mock pymilvus 模块。"""
    mock = MagicMock()
    if connect_side_effect is not None:
        mock.connections.connect.side_effect = connect_side_effect
    mock.utility.has_collection.return_value = has_collection
    if query_ok:
        collection = MagicMock()
        collection.num_entities = 100
        collection.schema.fields = _make_schema_fields(dim)
    else:
        collection = _FailingQueryCollection(dim)
    mock.Collection.return_value = collection
    return mock


# ---------- 环境隔离 + 配置构造 ----------

@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """每个测试前清理 Milvus / embedding / backend 环境变量，避免互相污染。"""
    for key in list(os.environ):
        if key.startswith("MILVUS_") or key in (
            "XG_DOUYIN_AI_EMBEDDING_DIMENSIONS",
            "RAG_VECTOR_BACKEND",
        ):
            monkeypatch.delenv(key, raising=False)


def _make_config(monkeypatch, **overrides):
    """构造默认有效的 Milvus readiness 配置环境，返回 Settings。"""
    base = {
        "RAG_VECTOR_BACKEND": "milvus",
        "MILVUS_URI": "http://milvus.test:19530",
        "MILVUS_USERNAME": "testuser",
        "MILVUS_PASSWORD": "testpass",
        "MILVUS_DB_NAME": "test_db",
        "MILVUS_COLLECTION": "test_collection",
        "MILVUS_DIMENSION": "2048",
        "XG_DOUYIN_AI_EMBEDDING_DIMENSIONS": "2048",
    }
    base.update(overrides)
    for key, val in base.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)
    from apps.xg_douyin_ai_cs.config import Settings
    return Settings()


@pytest.fixture
def milvus_patch():
    """patch _load_pymilvus 返回默认可控 mock。"""
    from apps.xg_douyin_ai_cs.services import vector_store
    mock = _make_mock_pymilvus()
    with patch.object(vector_store, "_load_pymilvus", return_value=mock):
        yield mock


def _run(config):
    from apps.xg_douyin_ai_cs.services.vector_store import run_milvus_readiness
    return run_milvus_readiness(config)


# ---------- 全绿 ----------

def test_readiness_all_ok(milvus_patch, monkeypatch):
    """全部正常时 readiness 全绿，无 error_code。"""
    config = _make_config(monkeypatch)
    result = _run(config)
    assert result["backend"] == "milvus"
    assert result["connected"] is True
    assert result["collection_exists"] is True
    assert result["schema_match"] is True
    assert result["query_ok"] is True
    assert "error_code" not in result


# ---------- 第3、5项：配置缺失 ----------

def test_uri_missing_returns_config_missing(milvus_patch, monkeypatch):
    """第3项：MILVUS_URI 缺失 → MILVUS_CONFIG_MISSING。"""
    config = _make_config(monkeypatch, MILVUS_URI=None)
    result = _run(config)
    assert result["error_code"] == "MILVUS_CONFIG_MISSING"
    assert result["query_ok"] is False


def test_collection_config_missing_returns_config_missing(milvus_patch, monkeypatch):
    """第5项（配置层）：MILVUS_COLLECTION 缺失 → MILVUS_CONFIG_MISSING。"""
    config = _make_config(monkeypatch, MILVUS_COLLECTION=None)
    result = _run(config)
    assert result["error_code"] == "MILVUS_CONFIG_MISSING"


# ---------- 第4项：database 不存在 ----------

def test_database_not_found(milvus_patch, monkeypatch):
    """第4项：连接时 database 不存在 → MILVUS_DB_NOT_FOUND。"""
    milvus_patch.connections.connect.side_effect = Exception("database not found: test_db")
    config = _make_config(monkeypatch)
    result = _run(config)
    assert result["error_code"] == "MILVUS_DB_NOT_FOUND"
    assert result["connected"] is False


# ---------- 第6项：认证失败 ----------

def test_auth_failed(milvus_patch, monkeypatch):
    """第6项：认证失败 → MILVUS_AUTH_FAILED。"""
    milvus_patch.connections.connect.side_effect = Exception(
        "auth failed: invalid credential"
    )
    config = _make_config(monkeypatch)
    result = _run(config)
    assert result["error_code"] == "MILVUS_AUTH_FAILED"
    assert result["connected"] is False


# ---------- 第7项：维度不一致 ----------

def test_embedding_milvus_dimension_mismatch(milvus_patch, monkeypatch):
    """第7项（配置层）：EMBEDDING_DIMENSIONS != MILVUS_DIMENSION → MILVUS_DIMENSION_MISMATCH。"""
    config = _make_config(
        monkeypatch, MILVUS_DIMENSION="1024", XG_DOUYIN_AI_EMBEDDING_DIMENSIONS="2048"
    )
    result = _run(config)
    assert result["error_code"] == "MILVUS_DIMENSION_MISMATCH"


def test_embedding_dimension_missing(milvus_patch, monkeypatch):
    """EMBEDDING_DIMENSIONS 未设 → MILVUS_DIMENSION_MISMATCH。"""
    config = _make_config(monkeypatch, XG_DOUYIN_AI_EMBEDDING_DIMENSIONS=None)
    result = _run(config)
    assert result["error_code"] == "MILVUS_DIMENSION_MISMATCH"


def test_collection_dimension_mismatch(monkeypatch):
    """第7项（collection 层）：collection 实际 dim != MILVUS_DIMENSION → MILVUS_DIMENSION_MISMATCH。"""
    from apps.xg_douyin_ai_cs.services import vector_store
    mock = _make_mock_pymilvus(dim=1024)  # collection 实际 1024，配置 2048
    with patch.object(vector_store, "_load_pymilvus", return_value=mock):
        config = _make_config(monkeypatch)
        result = _run(config)
    assert result["error_code"] == "MILVUS_DIMENSION_MISMATCH"
    assert result["schema_match"] is False


# ---------- 第8项：collection 不存在 ----------

def test_collection_not_found(monkeypatch):
    """第8项：collection 不存在 → MILVUS_COLLECTION_NOT_FOUND。"""
    from apps.xg_douyin_ai_cs.services import vector_store
    mock = _make_mock_pymilvus(has_collection=False)
    with patch.object(vector_store, "_load_pymilvus", return_value=mock):
        config = _make_config(monkeypatch)
        result = _run(config)
    assert result["error_code"] == "MILVUS_COLLECTION_NOT_FOUND"
    assert result["collection_exists"] is False


# ---------- 第9项：不可达不回退 SQLite ----------

def test_connect_failed_no_sqlite_fallback(milvus_patch, monkeypatch):
    """第9项：Milvus 不可达 → MILVUS_CONNECT_FAILED，backend 仍 milvus，不回退 sqlite。"""
    milvus_patch.connections.connect.side_effect = Exception("connection refused")
    config = _make_config(monkeypatch)
    result = _run(config)
    assert result["error_code"] == "MILVUS_CONNECT_FAILED"
    assert result["backend"] == "milvus"
    assert result["connected"] is False


# ---------- 轻量探测失败 ----------

def test_query_failed(monkeypatch):
    """轻量只读探测失败 → MILVUS_QUERY_FAILED。"""
    from apps.xg_douyin_ai_cs.services import vector_store
    mock = _make_mock_pymilvus(query_ok=False)
    with patch.object(vector_store, "_load_pymilvus", return_value=mock):
        config = _make_config(monkeypatch)
        result = _run(config)
    assert result["error_code"] == "MILVUS_QUERY_FAILED"
    assert result["query_ok"] is False


# ---------- 只读约束 ----------

def test_readiness_is_read_only(milvus_patch, monkeypatch):
    """readiness 不得调用 create_index/load/upsert/delete/create_collection。"""
    config = _make_config(monkeypatch)
    _run(config)
    collection = milvus_patch.Collection.return_value
    collection.create_index.assert_not_called()
    collection.load.assert_not_called()
    collection.upsert.assert_not_called()
    collection.delete.assert_not_called()
    milvus_patch.utility.create_collection.assert_not_called()


# ---------- 脱敏 ----------

def test_no_password_leak_in_result(milvus_patch, monkeypatch):
    """readiness 结果不得泄露密码或完整 URI。"""
    milvus_patch.connections.connect.side_effect = Exception(
        "connect failed: password=testpass uri=http://milvus.test:19530"
    )
    config = _make_config(monkeypatch)
    result = _run(config)
    result_str = str(result)
    assert "testpass" not in result_str
    assert "milvus.test" not in result_str
