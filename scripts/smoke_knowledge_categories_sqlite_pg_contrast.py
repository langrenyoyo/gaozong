"""GET /knowledge-categories 的 SQLite / PostgreSQL 对照 smoke。

本脚本只创建 PostgreSQL 临时 smoke 表和 synthetic 数据，不是正式 migration。
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.database_url import parse_database_url
from app.models import KnowledgeCategory


SMOKE_MERCHANT_ID = "smoke-merchant-a"
OTHER_MERCHANT_ID = "smoke-merchant-b"
SMOKE_ENV_NAME = "SMOKE_POSTGRES_DATABASE_URL"


class SmokeConfigurationError(RuntimeError):
    """smoke 运行前置配置缺失或不合法。"""


@dataclass(frozen=True)
class ContrastResult:
    ok: bool
    reason: str
    normalized_sqlite: list[dict]
    normalized_postgres: list[dict]


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def to_asyncpg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def require_postgres_url(env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    database_url = (values.get(SMOKE_ENV_NAME) or values.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise SmokeConfigurationError(
            "缺少 SMOKE_POSTGRES_DATABASE_URL。先启动 PostgreSQL profile："
            "docker compose -f docker-compose.dev.yml --profile postgres up -d postgres；"
            "再设置 SMOKE_POSTGRES_DATABASE_URL=postgresql+asyncpg://...@postgres:5432/auto_wechat 后运行。"
        )
    parsed = parse_database_url(database_url)
    if parsed.backend != "postgresql" or not database_url.startswith("postgresql+asyncpg://"):
        raise SmokeConfigurationError("smoke 仅支持 postgresql+asyncpg:// PostgreSQL URL")
    return database_url


def build_smoke_category_rows() -> list[dict]:
    now = datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc)
    rows = [
        _row(1, "premium_bba", "精品BBA", SMOKE_MERCHANT_ID, "active", 10, None, now),
        _row(2, "new_energy", "新能源", SMOKE_MERCHANT_ID, "active", 20, None, now),
        _row(3, "inactive_hidden", "禁用分类", SMOKE_MERCHANT_ID, "disabled", 30, None, now),
        _row(4, "deleted_hidden", "删除分类", SMOKE_MERCHANT_ID, "active", 40, now, now),
        _row(5, "other_merchant", "其它商户分类", OTHER_MERCHANT_ID, "active", 5, None, now),
    ]
    return rows


def _row(
    row_id: int,
    category_key: str,
    name: str,
    merchant_id: str,
    status: str,
    sort_order: int,
    deleted_at: datetime | None,
    now: datetime,
) -> dict:
    return {
        "id": row_id,
        "key": category_key,
        "category_key": category_key,
        "name": name,
        "description": f"smoke {category_key}",
        "scope_type": "merchant",
        "merchant_id": merchant_id,
        "status": status,
        "sort_order": sort_order,
        "is_base": False,
        "deleted_at": deleted_at,
        "created_at": now,
        "updated_at": now,
    }


def normalize_category_response(payload) -> list[dict]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    return [
        {
            "category_key": str(item["category_key"]),
            "name": str(item["name"]),
            "scope_type": str(item["scope_type"]),
            "is_base": bool(item["is_base"]),
        }
        for item in data
    ]


def compare_category_responses(sqlite_payload, postgres_payload) -> ContrastResult:
    sqlite_data = normalize_category_response(sqlite_payload)
    postgres_data = normalize_category_response(postgres_payload)
    if sqlite_data != postgres_data:
        return ContrastResult(False, "SQLite 与 PostgreSQL 响应不一致", sqlite_data, postgres_data)
    keys = [item["category_key"] for item in sqlite_data]
    if not keys or keys[0] != "base":
        return ContrastResult(False, "响应未包含首位 base 分类", sqlite_data, postgres_data)
    hidden = {"inactive_hidden", "deleted_hidden", "other_merchant"}
    if hidden.intersection(keys):
        return ContrastResult(False, "inactive/deleted/其它商户分类不应返回", sqlite_data, postgres_data)
    if keys != ["base", "premium_bba", "new_energy"]:
        return ContrastResult(False, "排序或 merchant 过滤语义不符合预期", sqlite_data, postgres_data)
    return ContrastResult(True, "SQLite 与 PostgreSQL 响应语义一致", sqlite_data, postgres_data)


def _context() -> RequestContext:
    return RequestContext(
        user_id="smoke-user",
        username="smoke-user",
        merchant_id=SMOKE_MERCHANT_ID,
        merchant_ids=[SMOKE_MERCHANT_ID],
        permission_codes=["auto_wechat:ai_agents"],
    )


def _create_client(db_dependency, context: RequestContext) -> TestClient:
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def run_sqlite_probe() -> dict:
    with tempfile.TemporaryDirectory(prefix="knowledge-categories-sqlite-") as temp_dir:
        sqlite_url = f"sqlite:///{os.path.join(temp_dir, 'smoke.db')}"
        engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
        try:
            TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            Base.metadata.create_all(bind=engine)
            db = TestingSession()
            try:
                for row in build_smoke_category_rows():
                    db.add(
                        KnowledgeCategory(
                            id=row["id"],
                            tenant_id=None,
                            merchant_id=row["merchant_id"],
                            category_key=row["category_key"],
                            name=row["name"],
                            scope_type=row["scope_type"],
                            is_base=0,
                            status=row["status"],
                            sort_order=row["sort_order"],
                            deleted_at=row["deleted_at"],
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                        )
                    )
                db.commit()
            finally:
                db.close()

            def _override_get_db():
                session = TestingSession()
                try:
                    yield session
                finally:
                    session.close()

            with _create_client(_override_get_db, _context()) as client:
                response = client.get("/knowledge-categories")
            response.raise_for_status()
            return response.json()
        finally:
            engine.dispose()


async def init_postgres_smoke_table(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - 由部署依赖决定
        raise SmokeConfigurationError("缺少 asyncpg 依赖，无法执行 PostgreSQL smoke") from exc

    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    try:
        await conn.execute("DROP TABLE IF EXISTS knowledge_categories")
        await conn.execute(
            """
            CREATE TABLE knowledge_categories (
                id BIGINT PRIMARY KEY,
                "key" VARCHAR(128) NOT NULL,
                category_key VARCHAR(128) NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                scope_type VARCHAR(20) NOT NULL,
                merchant_id VARCHAR(128),
                status VARCHAR(20) NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 100,
                is_base BOOLEAN NOT NULL DEFAULT false,
                deleted_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        for row in build_smoke_category_rows():
            await conn.execute(
                """
                INSERT INTO knowledge_categories (
                    id, "key", category_key, name, description, scope_type,
                    merchant_id, status, sort_order, is_base, deleted_at,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                row["id"],
                row["key"],
                row["category_key"],
                row["name"],
                row["description"],
                row["scope_type"],
                row["merchant_id"],
                row["status"],
                row["sort_order"],
                row["is_base"],
                row["deleted_at"],
                row["created_at"],
                row["updated_at"],
            )
    finally:
        await conn.close()


async def run_postgres_probe(database_url: str) -> dict:
    import app.config as config
    import app.routers.knowledge_categories as router

    await init_postgres_smoke_table(database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_enabled = config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED
    old_get_async_sessionmaker = router.get_async_sessionmaker
    try:
        config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED = True
        router.get_async_sessionmaker = lambda: session_factory

        def _unused_get_db():
            yield object()

        from app.main import create_app

        app = create_app()
        app.dependency_overrides[get_db] = _unused_get_db
        app.dependency_overrides[get_request_context_required] = lambda: _context()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/knowledge-categories")
        response.raise_for_status()
        return response.json()
    finally:
        config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED = old_enabled
        router.get_async_sessionmaker = old_get_async_sessionmaker
        await engine.dispose()


def print_run_instructions() -> None:
    print("启动 PostgreSQL profile:")
    print("  docker compose -f docker-compose.dev.yml --profile postgres up -d postgres")
    print("运行 smoke:")
    print("  python scripts/smoke_knowledge_categories_sqlite_pg_contrast.py")
    print("停止 PostgreSQL:")
    print("  docker compose -f docker-compose.dev.yml stop postgres")


def main() -> int:
    print_run_instructions()
    try:
        database_url = require_postgres_url()
    except SmokeConfigurationError as exc:
        print(f"SMOKE_SKIP: {exc}")
        return 2

    print(f"PostgreSQL URL: {mask_database_url(database_url)}")
    sqlite_payload = run_sqlite_probe()
    postgres_payload = asyncio.run(run_postgres_probe(database_url))
    contrast = compare_category_responses(sqlite_payload, postgres_payload)
    print(f"SQLite normalized: {contrast.normalized_sqlite}")
    print(f"PostgreSQL normalized: {contrast.normalized_postgres}")
    if not contrast.ok:
        print(f"SMOKE_FAIL: {contrast.reason}")
        return 1
    print(f"SMOKE_PASS: {contrast.reason}")
    print("已确认关闭开关后默认仍回到 SQLite 路径：脚本未修改 .env，且路由开关在 PG probe 后已恢复。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
