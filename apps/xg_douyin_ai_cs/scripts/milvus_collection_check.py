"""Milvus collection 检查 / 初始化脚本。

默认只检查；只有传入 --init 才会创建 collection。
"""

from __future__ import annotations

import argparse
import sys
import warnings
from typing import Any

from apps.xg_douyin_ai_cs.config import Settings
from apps.xg_douyin_ai_cs.services.vector_store import VectorStoreError, get_vector_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查或初始化 9100 RAG Milvus collection")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只检查 collection，不创建")
    mode.add_argument("--init", action="store_true", help="缺失时创建 collection 和索引")
    args = parser.parse_args(argv)

    config = Settings()
    if config.rag_vector_backend != "milvus":
        print("Milvus 未启用：当前 RAG_VECTOR_BACKEND 不是 milvus，未执行 collection 检查。")
        return 0

    try:
        store = get_vector_store(config)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=".*connections.connect is an ORM-style PyMilvus API.*",
                category=Warning,
            )
            result = store.ensure_collection(create_if_missing=bool(args.init))
    except VectorStoreError as exc:
        print(_format_failure(exc.to_diagnostic()))
        return 1
    except Exception as exc:
        print(
            _format_failure(
                {
                    "backend": "milvus",
                    "connected": "unknown",
                    "collection_exists": "unknown",
                    "schema_match": "unknown",
                    "phase": "unknown",
                    "error_code": "MILVUS_COLLECTION_CHECK_FAILED",
                    "error_type": type(exc).__name__,
                    "error_message": "details redacted",
                }
            )
        )
        return 1

    print(_format_result(result))
    return 0


def _format_result(result: dict[str, Any]) -> str:
    safe_keys = (
        "backend",
        "connected",
        "collection_exists",
        "created",
        "schema_match",
        "dimension",
        "metric_type",
    )
    parts = [f"{key}={result[key]}" for key in safe_keys if key in result]
    return "Milvus collection 检查完成：" + ", ".join(parts)


def _format_failure(result: dict[str, Any]) -> str:
    safe_keys = (
        "backend",
        "connected",
        "collection_exists",
        "schema_match",
        "phase",
        "error_code",
        "error_type",
        "error_message",
    )
    parts = [f"{key}={result[key]}" for key in safe_keys if key in result]
    return "Milvus collection 检查失败：" + ", ".join(parts)


if __name__ == "__main__":
    sys.exit(main())
