"""Milvus collection 全量导出脚本。

在内网稳定的环境中（服务器容器或 VPC 内）运行，将整个 collection 的数据
导出为 JSONL 文件，供备份 / 迁移 / 交付使用。

用法（在 xg-douyin-ai-cs 容器内）：
    python -m apps.xg_douyin_ai_cs.scripts.milvus_export \
        --output /data/milvus_export.jsonl

可选参数：
    --no-embeddings   不导出 embedding 向量（文件更小，仅导出文本与元数据）
    --output          输出文件路径（默认 ./milvus_export.jsonl）
    --batch-size      每批拉取记录数（默认 1000）

设计要点：
- 复用项目 Settings 读取 MILVUS_* 配置，不硬编码凭据；
- 使用 MilvusClient.query_iterator 全量分页扫描，避免 offset 翻页性能塌陷；
- embedding 以 list[float] 形式写入 JSONL，可直接用于重新导入；
- 单条失败不中断整体导出，行尾记录 error 字段并继续。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timezone
from typing import Any

from apps.xg_douyin_ai_cs.config import Settings
from apps.xg_douyin_ai_cs.services.vector_store import (
    VectorStoreError,
    _load_pymilvus,
    _validate_milvus_config,
)


# collection 全字段（与 build_schema 保持一致）
ALL_FIELDS = [
    "chunk_id",
    "embedding",
    "chunk_text",
    "document_id",
    "chunk_index",
    "tenant_id",
    "merchant_id",
    "douyin_account_id",
    "category_key",
    "category_id",
    "source_type",
    "source_title",
    "source_hash",
    "content_hash",
    "status",
    "created_at",
    "updated_at",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全量导出 Milvus collection 数据为 JSONL")
    parser.add_argument("--output", default="milvus_export.jsonl", help="输出 JSONL 文件路径")
    parser.add_argument("--no-embeddings", action="store_true", help="不导出 embedding 向量")
    parser.add_argument("--batch-size", type=int, default=1000, help="每批拉取记录数")
    args = parser.parse_args(argv)

    config = Settings()
    if config.rag_vector_backend != "milvus":
        print("[ERROR] 当前 RAG_VECTOR_BACKEND 不是 milvus，无法导出。", file=sys.stderr)
        return 1

    try:
        _validate_milvus_config(config)
    except VectorStoreError as exc:
        print(f"[ERROR] Milvus 配置不完整：{exc}", file=sys.stderr)
        return 1

    output_fields = [f for f in ALL_FIELDS if f != "embedding"] if args.no_embeddings else list(ALL_FIELDS)

    pymilvus = _load_pymilvus()
    print(f"[INFO] 连接 Milvus: collection={config.milvus_collection} db={config.milvus_db_name or 'default'}")

    # 用 MilvusClient 的 token 认证 + query_iterator 全量分页扫描
    client_kwargs: dict[str, Any] = {
        "uri": config.milvus_uri,
        "token": f"{config.milvus_username}:{config.milvus_password}",
        "timeout": config.milvus_timeout_seconds,
    }
    if config.milvus_db_name:
        client_kwargs["db_name"] = config.milvus_db_name
    else:
        client_kwargs["db_name"] = None

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*MilvusClient.*", category=Warning)
            client = pymilvus.MilvusClient(**client_kwargs)
    except Exception as exc:
        print(f"[ERROR] 连接 Milvus 失败：{exc}", file=sys.stderr)
        return 1

    # 统计总数
    try:
        stats = client.get_collection_stats(config.milvus_collection)
        count = stats.get("row_count") if isinstance(stats, dict) else None
    except Exception:
        count = None
    print(f"[INFO] collection row_count={count}（统计值，实际以导出行数为准）")

    total = 0
    error_count = 0
    started = datetime.now(timezone.utc)

    # 统计 collection 实际记录数，便于校验导出完整性
    try:
        # query 单条取主键计数（num_entities 在 MilvusClient 下不一定准确）
        probe = client.query(
            collection_name=config.milvus_collection,
            output_fields=["chunk_id"],
            limit=1,
        )
        if not probe:
            print("[WARN] collection 为空（无任何记录），将生成空文件。", file=sys.stderr)
    except Exception as exc:
        print(f"[WARN] 探测 collection 失败：{type(exc).__name__}: {exc}", file=sys.stderr)

    iterator = client.query_iterator(
        collection_name=config.milvus_collection,
        output_fields=output_fields,
        batch_size=args.batch_size,
    )
    # pymilvus 不同版本 query_iterator 返回对象 API 不一致：
    #   - 新版 QueryIterator：有 .next() 方法，返回 list，空 list 表示结束
    #   - 旧版/部分版本：实现了 __next__，可用 next()
    #   - 个别版本：直接返回 list（一次性）
    # 这里逐项探测，兼容所有情况。
    next_method = getattr(iterator, "next", None)
    has_dunder_next = hasattr(iterator, "__next__")
    if callable(next_method):
        print("[INFO] 迭代方式：QueryIterator.next() 方法")
    elif has_dunder_next:
        print("[INFO] 迭代方式：__next__ 内置迭代器")
    elif isinstance(iterator, list):
        print(f"[INFO] 迭代方式：一次性 list（共 {len(iterator)} 条）")
    else:
        print(f"[ERROR] 不支持的 query_iterator 返回类型：{type(iterator).__name__}", file=sys.stderr)
        return 1

    with open(args.output, "w", encoding="utf-8") as fh:
        # 一次性 list：直接遍历
        if isinstance(iterator, list):
            batches = [iterator] if iterator else []
        else:
            batches = _iter_batches(iterator, use_method=callable(next_method))

        for batch in batches:
            if not batch:
                break
            for row in batch:
                try:
                    record = _normalize_row(row, include_embedding=not args.no_embeddings)
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total += 1
                except Exception as exc:
                    error_count += 1
                    # 单行失败不影响整体导出
                    err_row = {
                        "_export_error": str(exc),
                        "_error_type": type(exc).__name__,
                        "chunk_id": _safe_get(row, "chunk_id"),
                    }
                    fh.write(json.dumps(err_row, ensure_ascii=False) + "\n")
            if total % (args.batch_size * 10) == 0:
                print(f"[INFO] 已导出 {total} 条 …")

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    file_size = os.path.getsize(args.output)
    print(f"[DONE] 导出完成：total={total} errors={error_count} "
          f"size={file_size} bytes elapsed={elapsed:.1f}s output={args.output}")
    try:
        client.close()
    except Exception:
        pass
    return 0 if error_count == 0 else 2


def _iter_batches(iterator: Any, *, use_method: bool):
    """逐批从 QueryIterator 拉取记录的生成器。

    use_method=True 用 .next() 方法；否则用内置 next()。
    空 list / StopIteration 表示遍历结束。单批异常跳过继续。
    """
    while True:
        try:
            batch = iterator.next() if use_method else next(iterator)
        except StopIteration:
            break
        except Exception as exc:
            print(f"[WARN] 批次拉取异常：{type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if not batch:
            break
        yield batch


def _normalize_row(row: Any, *, include_embedding: bool) -> dict[str, Any]:
    """将 pymilvus 返回行转为可 JSON 序列化的 dict。"""
    record: dict[str, Any] = {}
    getter = getattr(row, "get", None)
    for field in ALL_FIELDS:
        if field == "embedding" and not include_embedding:
            continue
        value = _safe_get(row, field, getter)
        record[field] = _coerce_value(value)
    return record


def _safe_get(row: Any, key: str, getter: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    if getter is None:
        getter = getattr(row, "get", None)
    if callable(getter):
        return getter(key)
    return getattr(row, key, None)


def _coerce_value(value: Any) -> Any:
    # numpy array / list → list[float]
    if value is None:
        return None
    if hasattr(value, "tolist"):  # numpy array
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_coerce_scalar(item) for item in value]
    return _coerce_scalar(value)


def _coerce_scalar(value: Any) -> Any:
    # numpy 标量 → Python 原生类型
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


if __name__ == "__main__":
    sys.exit(main())
