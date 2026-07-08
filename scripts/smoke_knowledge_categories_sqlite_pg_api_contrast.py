"""GET /knowledge-categories SQLite / PostgreSQL API 对照 smoke。

本脚本只使用 synthetic 数据：先写临时 SQLite，再通过 P3-C5 迁移脚本 apply 到 dev
PostgreSQL，最后分别调用 FastAPI 路由的 SQLite 默认路径和 async PG pilot 路径。
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping, Sequence

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import (
    Base,
    close_async_database_runtime,
    get_db,
    init_async_database_runtime,
)
from app.database_url import parse_database_url
from app.models import KnowledgeCategory
from scripts.migrate_knowledge_categories_sqlite_to_postgres import (
    build_synthetic_source_rows,
    main as migration_main,
    mask_database_url as _mask_database_url,
    to_asyncpg_dsn,
    write_synthetic_sqlite_database,
)


SMOKE_MERCHANT_ID = "p3_c6_smoke_merchant"
POSTGRES_ENV_NAME = "SMOKE_DATABASE_URL"


class SmokeConfigurationError(RuntimeError):
    """smoke 运行前置配置缺失或不符合 dev 边界。"""


@dataclass(frozen=True)
class ApiContrastResult:
    ok: bool
    normalized_sqlite: list[dict[str, object]]
    normalized_postgres: list[dict[str, object]]
    mismatch_diff: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="对照 GET /knowledge-categories 的 SQLite 与 async PG 响应语义。")
    parser.add_argument("--postgres-url", help="dev PostgreSQL URL；未传时只读取 SMOKE_DATABASE_URL。")
    return parser.parse_args(argv)


def mask_database_url(database_url: str) -> str:
    return _mask_database_url(database_url)


def resolve_postgres_url(env: Mapping[str, str] | None = None, explicit_url: str | None = None) -> str:
    if explicit_url:
        database_url = explicit_url.strip()
    else:
        values = env if env is not None else os.environ
        database_url = (values.get(POSTGRES_ENV_NAME) or "").strip()
    if not database_url:
        raise SmokeConfigurationError(
            "缺少 --postgres-url 或 SMOKE_DATABASE_URL；不会读取 DATABASE_URL，避免误用默认/生产配置"
        )
    parsed = parse_database_url(database_url)
    if parsed.backend != "postgresql" or not database_url.startswith("postgresql+asyncpg://"):
        raise SmokeConfigurationError("P3-C6 API contrast smoke 仅支持 postgresql+asyncpg:// dev URL")
    return database_url


def normalize_category_response(payload) -> list[dict[str, object]]:
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    normalized: list[dict[str, object]] = []
    for item in data:
        category_key = str(item.get("category_key") or item.get("key") or "")
        normalized.append(
            {
                "category_key": category_key,
                "key": str(item.get("key") or category_key),
                "name": item.get("name"),
                "description": item.get("description"),
                "scope_type": item.get("scope_type"),
                "is_base": bool(item.get("is_base", False)),
                "status": item.get("status"),
                "sort_order": item.get("sort_order"),
                "merchant_id": item.get("merchant_id"),
                "has_created_at": bool(item.get("created_at")),
                "has_updated_at": bool(item.get("updated_at")),
            }
        )
    return normalized


def compare_category_responses(sqlite_payload, postgres_payload) -> ApiContrastResult:
    normalized_sqlite = normalize_category_response(sqlite_payload)
    normalized_postgres = normalize_category_response(postgres_payload)
    if normalized_sqlite == normalized_postgres:
        return ApiContrastResult(True, normalized_sqlite, normalized_postgres, "")
    sqlite_lines = json.dumps(normalized_sqlite, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    postgres_lines = json.dumps(normalized_postgres, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    diff = "\n".join(
        difflib.unified_diff(sqlite_lines, postgres_lines, fromfile="sqlite", tofile="postgres", lineterm="")
    )
    return ApiContrastResult(False, normalized_sqlite, normalized_postgres, diff)


def build_cleanup_sql(merchant_id: str) -> tuple[str, tuple[str]]:
    return "DELETE FROM knowledge_categories WHERE merchant_id = $1", (merchant_id,)


def _context() -> RequestContext:
    return RequestContext(
        user_id="p3-c6-smoke-user",
        username="p3-c6-smoke-user",
        merchant_id=SMOKE_MERCHANT_ID,
        merchant_ids=[SMOKE_MERCHANT_ID],
        permission_codes=["auto_wechat:ai_agents"],
    )


def _seed_sqlite_for_api(sqlite_db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{sqlite_db_path}", connect_args={"check_same_thread": False})
    try:
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        try:
            for row in build_synthetic_source_rows(merchant_id=SMOKE_MERCHANT_ID):
                db.add(
                    KnowledgeCategory(
                        tenant_id=row["tenant_id"],
                        merchant_id=row["merchant_id"],
                        category_key=row["category_key"],
                        name=row["name"],
                        scope_type=row["scope_type"],
                        is_base=1 if row["is_base"] else 0,
                        status=row["status"],
                        sort_order=row["sort_order"],
                        created_at=_sqlite_datetime(row["created_at"]),
                        updated_at=_sqlite_datetime(row["updated_at"]),
                        deleted_at=_sqlite_datetime(row["deleted_at"]),
                        created_by=row["created_by"],
                        updated_by=row["updated_by"],
                    )
                )
            db.commit()
        finally:
            db.close()
    finally:
        engine.dispose()


def _sqlite_datetime(value: object) -> datetime | date | None:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date)):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T", 1))


def run_sqlite_api_probe(sqlite_db_path: Path) -> dict:
    _seed_sqlite_for_api(sqlite_db_path)
    engine = create_engine(f"sqlite:///{sqlite_db_path}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    try:
        def _override_get_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        from app.main import create_app

        app = create_app()
        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_request_context_required] = lambda: _context()
        client = TestClient(app)
        response = client.get("/knowledge-categories")
        response.raise_for_status()
        return response.json()
    finally:
        engine.dispose()


def apply_synthetic_rows(sqlite_db_path: Path, postgres_url: str) -> int:
    return migration_main(
        [
            "--sqlite-db-path",
            str(sqlite_db_path),
            "--postgres-url",
            postgres_url,
            "--merchant-id",
            SMOKE_MERCHANT_ID,
            "--apply",
            "--yes",
        ]
    )


async def run_postgres_api_probe(postgres_url: str) -> dict:
    import app.routers.knowledge_categories as router

    old_enabled = config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED
    old_router_enabled = router.config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED
    try:
        config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED = True
        router.config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED = True
        init_async_database_runtime(postgres_url)

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
        router.config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED = old_router_enabled
        await close_async_database_runtime()


async def cleanup_synthetic_postgres_rows(postgres_url: str, merchant_id: str = SMOKE_MERCHANT_ID) -> int:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - 由运行环境依赖决定
        raise SmokeConfigurationError("缺少 asyncpg，无法清理 synthetic PG 数据") from exc

    sql, params = build_cleanup_sql(merchant_id)
    conn = await asyncpg.connect(to_asyncpg_dsn(postgres_url))
    try:
        result = await conn.execute(sql, *params)
        return int(result.rsplit(" ", 1)[-1])
    finally:
        await conn.close()


def print_run_instructions() -> None:
    print("启动 PostgreSQL profile:")
    print("  docker compose -f docker-compose.dev.yml --profile postgres up -d postgres")
    print("确认 schema:")
    print("  python scripts/smoke_auto_wechat_alembic_knowledge_categories.py")
    print("运行 API contrast smoke:")
    print("  python scripts/smoke_knowledge_categories_sqlite_pg_api_contrast.py --postgres-url $env:SMOKE_DATABASE_URL")
    print("停止 PostgreSQL:")
    print("  docker compose -f docker-compose.dev.yml stop postgres")


def main(argv: Sequence[str] | None = None) -> int:
    print_run_instructions()
    args = parse_args(argv)
    try:
        postgres_url = resolve_postgres_url(explicit_url=args.postgres_url)
    except SmokeConfigurationError as exc:
        print(f"SMOKE_SKIP: {exc}")
        return 2

    print(f"PostgreSQL URL: {mask_database_url(postgres_url)}")
    with tempfile.TemporaryDirectory(prefix="p3-c6-knowledge-categories-") as temp_dir:
        sqlite_api_path = Path(temp_dir) / "api.sqlite"
        sqlite_migration_path = Path(temp_dir) / "migration.sqlite"
        write_synthetic_sqlite_database(str(sqlite_migration_path), merchant_id=SMOKE_MERCHANT_ID)

        migration_exit_code = apply_synthetic_rows(sqlite_migration_path, postgres_url)
        if migration_exit_code != 0:
            print(f"SMOKE_FAIL: synthetic SQLite -> dev PostgreSQL apply 失败，exit={migration_exit_code}")
            return 1

        sqlite_payload = run_sqlite_api_probe(sqlite_api_path)
        try:
            postgres_payload = asyncio.run(run_postgres_api_probe(postgres_url))
            contrast = compare_category_responses(sqlite_payload, postgres_payload)
        finally:
            deleted_count = asyncio.run(cleanup_synthetic_postgres_rows(postgres_url))
            print(f"synthetic PG cleanup deleted rows: {deleted_count}")

    print(f"SQLite 分类数量: {len(normalize_category_response(sqlite_payload))}")
    print(f"PostgreSQL 分类数量: {len(normalize_category_response(postgres_payload))}")
    print(f"mismatch diff: {contrast.mismatch_diff or '<empty>'}")
    if not contrast.ok:
        print("SMOKE_FAIL: GET /knowledge-categories SQLite 与 PostgreSQL 响应语义不一致")
        return 1
    print("SMOKE_PASS: GET /knowledge-categories SQLite 与 PostgreSQL 响应语义一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
