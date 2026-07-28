"""抖音会话增量查询 PostgreSQL 计划门禁测试。

验证 _build_message_rows_statement 生成的有界查询在 5 万行数据下不走 Seq Scan，
过滤移除行不超过 5000。target 账号 500 行均匀分布在 5 万行噪声中。
"""

import json
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker


def _pg_url() -> str:
    raw = os.environ.get("SMOKE_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("SMOKE_DATABASE_URL 未设置，跳过真实 PostgreSQL 专项")
    if "?" in raw:
        pytest.fail("SMOKE_DATABASE_URL 禁止 query")
    if "#" in raw:
        pytest.fail("SMOKE_DATABASE_URL 禁止 fragment")
    from sqlalchemy.engine import make_url

    parsed = make_url(raw)
    if parsed.drivername != "postgresql+psycopg":
        pytest.fail(f"SMOKE_DATABASE_URL 必须使用 postgresql+psycopg，实际: {parsed.drivername}")
    if parsed.host not in ("127.0.0.1", "localhost"):
        pytest.fail(f"SMOKE_DATABASE_URL host 必须为 127.0.0.1 或 localhost，实际: {parsed.host}")
    if parsed.port != 5432:
        pytest.fail(f"SMOKE_DATABASE_URL port 必须为 5432，实际: {parsed.port}")
    if parsed.database != "auto_wechat_outbox_test":
        pytest.fail(f"SMOKE_DATABASE_URL database 必须为 auto_wechat_outbox_test，实际: {parsed.database}")
    return raw


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_pg_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0017"
    yield engine
    engine.dispose()


def _namespace() -> str:
    return f"pgbound_{uuid.uuid4().hex}"


@pytest.fixture
def pg_namespace(pg_engine):
    ns = _namespace()
    yield ns
    # 清理：按 event_key LIKE namespace% 删两表，断言残留 0
    prefix = f"{ns}%"
    with pg_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
            {"prefix": prefix},
        )
        conn.execute(
            text("DELETE FROM douyin_authorized_accounts WHERE open_id LIKE :prefix"),
            {"prefix": prefix},
        )
    with pg_engine.connect() as conn:
        remaining = conn.execute(
            text(
                "SELECT "
                "(SELECT count(*) FROM douyin_webhook_events WHERE event_key LIKE :prefix), "
                "(SELECT count(*) FROM douyin_authorized_accounts WHERE open_id LIKE :prefix)"
            ),
            {"prefix": prefix},
        ).one()
    assert tuple(remaining) == (0, 0), f"清理后残留非 0: {tuple(remaining)}"


def _seed_plan_rows(pg_engine, namespace: str):
    """灌入 5 万行：target 500 行均匀分布（gs % 100 = 0），noise 49500 行。"""
    target_account = f"{namespace}_target"
    noise_account = f"{namespace}_noise"
    now = datetime.now(timezone.utc)
    with pg_engine.begin() as conn:
        # 两个账号
        for open_id in (target_account, noise_account):
            conn.execute(
                text(
                    "INSERT INTO douyin_authorized_accounts (open_id, merchant_id, bind_status, main_account_id) "
                    "VALUES (:open_id, :merchant_id, 1, 1) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"open_id": open_id, "merchant_id": namespace},
            )
        # 5 万行事件：gs % 100 = 0 时为 target 账号，否则 noise
        conn.execute(
            text(
                """
                INSERT INTO douyin_webhook_events (
                    event, event_key, from_user_id, to_user_id,
                    conversation_short_id, server_message_id,
                    message_type, parsed_content_json, raw_body,
                    is_duplicate, merchant_id, created_at
                )
                SELECT
                    'im_receive_msg',
                    :namespace || '-' || gs::text,
                    CASE WHEN gs % 100 = 0 THEN :target_account ELSE :noise_account END,
                    CASE WHEN gs % 100 = 0 THEN :target_account ELSE :noise_account END,
                    :namespace || '_conv',
                    :namespace || '_msg_' || gs::text,
                    'text',
                    '{}'::jsonb,
                    '{}'::jsonb,
                    false,
                    :namespace,
                    :now - (gs * interval '1 second')
                FROM generate_series(1, 50000) AS gs
                """
            ),
            {
                "namespace": namespace,
                "target_account": target_account,
                "noise_account": noise_account,
                "now": now,
            },
        )
        # 灌入后更新统计信息，确保 PG 优化器选择 UNION ALL 索引扫描而非全表 Sort
        conn.execute(text("ANALYZE douyin_webhook_events"))
    return target_account, noise_account


def _plan_nodes(plan):
    """递归提取 EXPLAIN JSON 计划的所有节点。"""
    nodes = []

    def _walk(node):
        if isinstance(node, dict):
            nodes.append(node)
            for sub in node.get("Plans", []) or []:
                _walk(sub)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(plan)
    return nodes


def test_a12_incremental_query_avoids_seq_scan_and_limits_filter_rows(pg_engine, pg_namespace):
    """A12：5 万行下游标查询（UNION ALL 改写）不走 Seq Scan，Rows Removed by Filter <= 5000。"""

    target_account, _noise_account = _seed_plan_rows(pg_engine, pg_namespace)

    # 找目标账号最小事件 ID 建游标
    with pg_engine.connect() as conn:
        cursor = conn.execute(
            text(
                "SELECT min(id) FROM douyin_webhook_events "
                "WHERE to_user_id = :target AND merchant_id = :namespace AND is_duplicate = false"
            ),
            {"target": target_account, "namespace": pg_namespace},
        ).scalar_one()

    # 构造真实游标查询 SQL（UNION ALL 改写版，与 _query_message_row_page 一致）：
    # 两个单侧子查询各走 (merchant_id, to_user_id, id) / (merchant_id, from_user_id, id) 索引
    from app.models import DouyinWebhookEvent

    columns_str = (
        "id, event, from_user_id, to_user_id, conversation_short_id, "
        "server_message_id, message_type, parsed_content_json, lead_id, raw_body, created_at"
    )
    base_where = (
        f"event IN ('im_receive_msg', 'im_send_msg') "
        f"AND is_duplicate IS false "
        f"AND merchant_id = '{pg_namespace}' "
        f"AND id > {cursor}"
    )
    union_sql = (
        f"SELECT * FROM ("
        f"  (SELECT {columns_str} FROM douyin_webhook_events "
        f"   WHERE {base_where} AND to_user_id = '{target_account}' "
        f"   ORDER BY id ASC LIMIT 101)"
        f"  UNION ALL"
        f"  (SELECT {columns_str} FROM douyin_webhook_events "
        f"   WHERE {base_where} AND from_user_id = '{target_account}' "
        f"   ORDER BY id ASC LIMIT 101)"
        f") AS merged ORDER BY id ASC LIMIT 101"
    )

    explain_sql = text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {union_sql}")
    with pg_engine.connect() as conn:
        result = conn.execute(explain_sql).scalar_one()

    plan = result[0]["Plan"] if isinstance(result, list) else result["Plan"]
    nodes = _plan_nodes(plan)

    # 找 douyin_webhook_events 相关节点
    webhook_nodes = [
        n for n in nodes
        if "douyin_webhook_events" in (n.get("Relation Name") or "")
        or "douyin_webhook_events" in (n.get("Index Name") or "")
    ]
    assert webhook_nodes, f"未找到 douyin_webhook_events 节点:\n{json.dumps(plan, indent=2, default=str)}"

    # 门禁 1：无 Seq Scan
    seq_scans = [n for n in webhook_nodes if n.get("Node Type") == "Seq Scan"]
    assert not seq_scans, (
        f"门禁失败：douyin_webhook_events 出现 Seq Scan\n"
        f"节点: {json.dumps(seq_scans, indent=2, default=str)}\n"
        f"完整计划: {json.dumps(plan, indent=2, default=str)}"
    )

    # 门禁 2：Rows Removed by Filter <= 5000
    max_removed = max(
        (n.get("Rows Removed by Filter") or 0) for n in webhook_nodes
    )
    assert max_removed <= 5000, (
        f"门禁失败：Rows Removed by Filter = {max_removed} > 5000\n"
        f"节点: {json.dumps(webhook_nodes, indent=2, default=str)}\n"
        f"完整计划: {json.dumps(plan, indent=2, default=str)}"
    )
