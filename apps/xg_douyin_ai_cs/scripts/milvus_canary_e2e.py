"""Milvus synthetic canary 写入、检索、删除闭环验证脚本。"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import uuid
from typing import Any

from apps.xg_douyin_ai_cs.config import Settings
from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
from apps.xg_douyin_ai_cs.services.vector_store import (
    VectorStoreError,
    get_vector_store,
    sanitize_milvus_diagnostic,
)

CANARY_TENANT_ID = "xiaogao_system"
CANARY_MERCHANT_ID = "xiaogao_base"
CANARY_ACCOUNT_ID = "canary_account"
CANARY_CATEGORY_KEY = "base"


def run_canary_e2e(
    *,
    config: Settings,
    store: Any | None = None,
    document_id: str | None = None,
    chunk_id: str | None = None,
    marker: str | None = None,
) -> dict[str, Any]:
    store = store or get_vector_store(config)
    document_id = document_id or _new_canary_id("doc")
    chunk_id = chunk_id or _new_canary_id("chunk")
    marker = marker or f"CANARY_MILVUS_E2E_{uuid.uuid4().hex}"
    result = _base_result(document_id)
    upserted = False

    try:
        check = store.ensure_collection(create_if_missing=False)
        result.update(
            connected=check.get("connected", True),
            collection_exists=check.get("collection_exists", True),
            schema_match=check.get("schema_match", True),
            phase="collection_check",
        )
        dimension = _resolve_dimension(config, check)
        embedding = _fake_embedding(dimension)
        chunk = _build_canary_chunk(
            document_id=document_id,
            chunk_id=chunk_id,
            marker=marker,
            embedding=embedding,
        )

        store.upsert_chunks([chunk])
        upserted = True
        result.update(upsert_ok=True, phase="search")

        result["search_hit"] = _contains_canary_hit(
            store.search(_search_payload(), query_embedding=embedding),
            marker=marker,
            document_id=document_id,
            chunk_id=chunk_id,
        )
        result["phase"] = "delete"
        store.delete_document(
            document_id=document_id,
            tenant_id=CANARY_TENANT_ID,
            merchant_id=CANARY_MERCHANT_ID,
        )
        result.update(delete_ok=True, cleanup_ok=True, phase="search_after_delete")
        result["search_after_delete_hit"] = _contains_canary_hit(
            store.search(_search_payload(), query_embedding=embedding),
            marker=marker,
            document_id=document_id,
            chunk_id=chunk_id,
        )
        result.update(phase="complete", error_code="OK")
        return result
    except VectorStoreError as exc:
        result.update(_error_result(exc.code, exc.phase, exc.error_type or type(exc).__name__))
    except Exception as exc:
        result.update(_error_result(_phase_error_code(result["phase"]), result["phase"], type(exc).__name__))
    finally:
        if upserted and not result["delete_ok"]:
            try:
                store.delete_document(
                    document_id=document_id,
                    tenant_id=CANARY_TENANT_ID,
                    merchant_id=CANARY_MERCHANT_ID,
                )
            except Exception as exc:  # pragma: no cover - 真实环境兜底清理失败只做脱敏报告
                result.update(cleanup_ok=False, cleanup_error_type=type(exc).__name__)
            else:
                result.update(delete_ok=True, cleanup_ok=True)
    return sanitize_milvus_diagnostic(result, config)


def cleanup_only(*, config: Settings, document_id: str) -> dict[str, Any]:
    result = _base_result(document_id)
    try:
        store = get_vector_store(config)
        store.delete_document(
            document_id=document_id,
            tenant_id=CANARY_TENANT_ID,
            merchant_id=CANARY_MERCHANT_ID,
        )
    except VectorStoreError as exc:
        result.update(_error_result(exc.code, exc.phase, exc.error_type or type(exc).__name__))
    except Exception as exc:
        result.update(_error_result("MILVUS_CANARY_CLEANUP_FAILED", "cleanup", type(exc).__name__))
    else:
        result.update(delete_ok=True, cleanup_ok=True, phase="cleanup", error_code="OK")
    return sanitize_milvus_diagnostic(result, config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 Milvus synthetic canary E2E 验证")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true", help="执行 upsert/search/delete 闭环")
    mode.add_argument("--cleanup-only", metavar="DOCUMENT_ID", help="按固定 canary scope 清理指定文档")
    args = parser.parse_args(argv)

    config = Settings()
    if config.rag_vector_backend != "milvus":
        print("Milvus canary 未执行：RAG_VECTOR_BACKEND 不是 milvus")
        return 1

    result = (
        cleanup_only(config=config, document_id=args.cleanup_only)
        if args.cleanup_only
        else run_canary_e2e(config=config)
    )
    print(_format_result(result))
    return 0 if result.get("error_code") == "OK" and result.get("cleanup_ok") is True else 1


def _base_result(document_id: str) -> dict[str, Any]:
    return {
        "canary_document_id": _short_id(document_id),
        "connected": "unknown",
        "collection_exists": "unknown",
        "schema_match": "unknown",
        "upsert_ok": False,
        "search_hit": False,
        "delete_ok": False,
        "search_after_delete_hit": "unknown",
        "cleanup_ok": False,
        "phase": "config",
        "error_code": "MILVUS_CANARY_FAILED",
        "error_type": "",
    }


def _build_canary_chunk(*, document_id: str, chunk_id: str, marker: str, embedding: list[float]) -> dict[str, Any]:
    now = int(time.time())
    content_hash = hashlib.sha256(marker.encode("utf-8")).hexdigest()
    return {
        "chunk_id": chunk_id,
        "embedding": embedding,
        "chunk_text": f"{marker}：这是非业务测试文本，用于验证向量写入和检索。",
        "document_id": document_id,
        "chunk_index": 0,
        "tenant_id": CANARY_TENANT_ID,
        "merchant_id": CANARY_MERCHANT_ID,
        "douyin_account_id": CANARY_ACCOUNT_ID,
        "category_key": CANARY_CATEGORY_KEY,
        "category_id": "",
        "source_type": "test_canary",
        "source_title": "Milvus Canary Test",
        "source_hash": content_hash,
        "content_hash": content_hash,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }


def _search_payload() -> RagSearchRequest:
    return RagSearchRequest(
        tenant_id=CANARY_TENANT_ID,
        merchant_id=CANARY_MERCHANT_ID,
        douyin_account_id=CANARY_ACCOUNT_ID,
        query="synthetic canary vector verification",
        top_k=5,
        category_keys=[CANARY_CATEGORY_KEY],
    )


def _contains_canary_hit(items: list[Any], *, marker: str, document_id: str, chunk_id: str) -> bool:
    for item in items:
        if str(getattr(item, "document_id", "")) == document_id:
            return True
        if str(getattr(item, "chunk_id", "")) == chunk_id:
            return True
        if marker in str(getattr(item, "chunk_text", "")):
            return True
    return False


def _resolve_dimension(config: Settings, check: dict[str, Any]) -> int:
    value = config.milvus_dimension or check.get("dimension")
    if not value:
        raise RuntimeError("MILVUS_DIMENSION missing")
    return int(value)


def _fake_embedding(dimension: int) -> list[float]:
    # 固定非零向量，避免 COSINE 检索遇到全零向量。
    return [0.01 if index % 2 == 0 else 0.02 for index in range(dimension)]


def _new_canary_id(kind: str) -> str:
    return f"canary_{kind}_{int(time.time())}_{uuid.uuid4().hex[:12]}"


def _short_id(value: str) -> str:
    return value if len(value) <= 18 else f"{value[:12]}...{value[-6:]}"


def _error_result(error_code: str, phase: str, error_type: str) -> dict[str, Any]:
    return {
        "phase": phase,
        "error_code": error_code,
        "error_type": error_type,
    }


def _phase_error_code(phase: str) -> str:
    return {
        "collection_check": "MILVUS_CANARY_COLLECTION_CHECK_FAILED",
        "search": "MILVUS_CANARY_SEARCH_FAILED",
        "delete": "MILVUS_CANARY_DELETE_FAILED",
        "search_after_delete": "MILVUS_CANARY_SEARCH_AFTER_DELETE_FAILED",
    }.get(phase, "MILVUS_CANARY_FAILED")


def _format_result(result: dict[str, Any]) -> str:
    safe_keys = (
        "canary_document_id",
        "connected",
        "collection_exists",
        "schema_match",
        "upsert_ok",
        "search_hit",
        "delete_ok",
        "search_after_delete_hit",
        "cleanup_ok",
        "phase",
        "error_code",
        "error_type",
    )
    return "Milvus canary E2E：" + ", ".join(f"{key}={result[key]}" for key in safe_keys if key in result)


if __name__ == "__main__":
    sys.exit(main())
