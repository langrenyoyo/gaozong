"""抖音 webhook is_duplicate 布尔契约 PG 回归测试。

背景：生产 PostgreSQL `douyin_webhook_events.is_duplicate` 列是
`BOOLEAN NOT NULL DEFAULT false`（迁移 0003），但 ORM 曾是 `Integer`，且查询写
`is_duplicate == 0`、写入 `0/1`、判断 `== 1`。PG 上 `boolean = integer` 隐式转换失败，
未读数路径（get_account_unread_counts → _load_messages）抛 ProgrammingError。

本测试收敛契约：ORM 改为 Boolean，查询用 .is_(False)/.is_(True)，写入用 False/True。

设计（R1 返修要求）：
1. 纯逻辑单测（无 DB）：验证 is_duplicate 列类型与默认值、布尔过滤编译为 IS 非 =integer。
2. 真实 PostgreSQL 集成：用 Alembic 初始化到 head 的一次性库（禁 ORM 建表/删表），
   用原生 SQL `CAST(:raw_body AS jsonb)` 写 JSONB 列（绕过 ORM Text 契约，不触碰
   未纳入本任务的 raw_body/parsed_content_json JSONB 收敛）。
   - 未读数测试直接验证 `_query_message_rows()` 返回的非重复行数量，不走
     `_parse_raw_body`（PG 返回 dict 与 json.loads 不兼容，是另立 JSONB 契约问题）；
   - 筛选测试直接验证 `_apply_db_filters()` 生成的查询结果 event_key 集合；
   - 保留对 `.is_(False)/.is_(True)` 的真实 PG 执行验证。
3. 安全门：PG URL 只允许 postgresql+psycopg + 白名单 host + 库名 _test/_staging；
   拒绝 query/fragment；库名不满足后缀时拒绝；缺安全 PG 环境时守卫 fail（TEST_BLOCKED），不假通过。
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import DouyinWebhookEvent

logger = logging.getLogger(__name__)

# 固定测试企业与客户 open_id，写入与清理都用，与共享 _staging 库其他行隔离。
TEST_ACCOUNT_OPEN_ID = "account_open_id_bool_r1"
TEST_CUSTOMER_OPEN_ID = "customer_open_id_bool_r1"

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres"}


# ---------------------------------------------------------------------------
# 1. 纯逻辑单测（无 DB，本地必须可跑）
# ---------------------------------------------------------------------------

def test_is_duplicate_column_is_boolean():
    """A8 代码盘点：ORM 列类型必须是 Boolean，默认值 False，非 Integer。"""
    col = DouyinWebhookEvent.__table__.columns["is_duplicate"]
    type_name = type(col.type).__name__
    assert type_name == "Boolean", f"is_duplicate 列应为 Boolean，实际 {type_name}"
    default_val = col.default.arg if col.default is not None else None
    assert default_val is False, f"is_duplicate 默认值应为 False，实际 {default_val!r}"


def test_is_false_filter_compiles_to_boolean_not_integer():
    """A1：.is_(False) 在 PG 方言下编译为 IS false，不是 = 0 / = integer。

    红灯语义：旧实现 is_duplicate == 0 在 PG 会生成 `boolean = integer` 抛
    ProgrammingError；新实现 .is_(False) 生成 `IS false` 不抛。本断言验证编译产物
    不含整数比较，是 PG 安全的直接证据（无需连库）。
    """
    from sqlalchemy.dialects import postgresql
    stmt = DouyinWebhookEvent.is_duplicate.is_(False)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    upper = compiled.upper()
    assert "IS" in upper, f".is_(False) 应编译为 IS，实际 {compiled!r}"
    assert "= 0" not in upper and "INTEGER" not in upper, (
        f".is_(False) 不得退化为整数比较，实际 {compiled!r}"
    )


def test_is_true_filter_compiles_to_boolean():
    from sqlalchemy.dialects import postgresql
    stmt = DouyinWebhookEvent.is_duplicate.is_(True)
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "IS" in compiled.upper()


# ---------------------------------------------------------------------------
# 2. 安全 PG URL 守卫（标准 URL 解析，避免 userinfo 当 host）
# ---------------------------------------------------------------------------

def _safe_pg_url() -> str | None:
    """校验 SMOKE_DATABASE_URL：postgresql+psycopg + 白名单 host + 库名 _test/_staging。

    用 SQLAlchemy make_url 标准解析，避免手写 partition 把 userinfo 当 host。
    缺 env 返回 None；协议/host/库名/query/fragment 不合规直接 fail。
    """
    url = os.getenv("SMOKE_DATABASE_URL", "").strip()
    if not url:
        return None
    if "?" in url or "#" in url:
        pytest.fail("SMOKE_DATABASE_URL 禁止带 query(?) 或 fragment(#) 参数")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg":
        pytest.fail("SMOKE_DATABASE_URL 必须使用 postgresql+psycopg 协议")
    if parsed.host not in ALLOWED_HOSTS:
        pytest.fail(f"PG host 必须在白名单 {ALLOWED_HOSTS}，实际: {parsed.host}")
    if not (parsed.database and (
        parsed.database.endswith("_test") or parsed.database.endswith("_staging")
    )):
        pytest.fail(f"测试目标库必须以 _test/_staging 结尾，实际: {parsed.database}")
    return url


def test_safe_pg_url_accepts_authenticated_url(monkeypatch):
    """带账号密码 URL：标准解析 host 正确为 localhost（旧 partition bug 会错解成 user）。"""
    monkeypatch.setenv(
        "SMOKE_DATABASE_URL",
        "postgresql+psycopg://user:pass@localhost/auto_wechat_test",
    )
    assert _safe_pg_url() == \
        "postgresql+psycopg://user:pass@localhost/auto_wechat_test"


def test_safe_pg_url_rejects_non_whitelist_host(monkeypatch):
    monkeypatch.setenv(
        "SMOKE_DATABASE_URL",
        "postgresql+psycopg://user:pass@10.0.0.5/auto_wechat_test",
    )
    with pytest.raises(pytest.fail.Exception):
        _safe_pg_url()


def test_safe_pg_url_rejects_non_test_db_suffix(monkeypatch):
    """安全门：库名不满足 _test/_staging 时拒绝（避免误连生产库）。"""
    monkeypatch.setenv(
        "SMOKE_DATABASE_URL",
        "postgresql+psycopg://user:pass@localhost/auto_wechat",  # 生产库，禁止
    )
    with pytest.raises(pytest.fail.Exception):
        _safe_pg_url()


def test_safe_pg_url_rejects_query_and_fragment(monkeypatch):
    base = "postgresql+psycopg://user:pass@localhost/auto_wechat_test"
    monkeypatch.setenv("SMOKE_DATABASE_URL", base + "?sslmode=require")
    with pytest.raises(pytest.fail.Exception):
        _safe_pg_url()
    monkeypatch.setenv("SMOKE_DATABASE_URL", base + "#frag")
    with pytest.raises(pytest.fail.Exception):
        _safe_pg_url()


def test_blocks_when_no_safe_pg_environment():
    """安全门：无安全 PG 环境时必须 fail（TEST_BLOCKED），不能假通过。"""
    if os.getenv("SMOKE_DATABASE_URL", "").strip():
        pytest.skip("存在 PG 测试环境，本守卫测试不适用")
    pytest.fail(
        "TEST_BLOCKED: 缺少安全 PG 测试环境（SMOKE_DATABASE_URL 未设置）。"
        "请用一次性 Docker PG（库名以 _test/_staging 结尾）并 alembic 初始化到 head 后重跑。"
    )


# ---------------------------------------------------------------------------
# 3. 真实 PostgreSQL 集成测试（需安全 PG，一次性库，禁 ORM 建表/删表）
# ---------------------------------------------------------------------------

pg_required = pytest.mark.skipif(
    not os.getenv("SMOKE_DATABASE_URL", "").strip(),
    reason="缺少安全 PG 测试环境（SMOKE_DATABASE_URL 未设置）",
)


def _ensure_alembic_head(url: str) -> str:
    """用 Alembic 把一次性库初始化到 head。禁 ORM 建表，schema 由迁移声明。"""
    import subprocess
    env = {**os.environ, "DATABASE_URL": url}
    up = subprocess.run(
        [sys.executable, "-m", "alembic", "-c",
         "migrations/postgres/auto_wechat/alembic.ini", "upgrade", "head"],
        env=env, capture_output=True, text=True,
    )
    if up.returncode != 0:
        pytest.fail(f"alembic upgrade head 失败: {up.stderr[:500]}")
    cur = subprocess.run(
        [sys.executable, "-m", "alembic", "-c",
         "migrations/postgres/auto_wechat/alembic.ini", "current"],
        env=env, capture_output=True, text=True,
    )
    return cur.stdout.strip().splitlines()[-1] if cur.returncode == 0 else "unknown"


def _insert_event_sql(db, *, event_key: str, is_duplicate: bool,
                      server_message_id: str, create_time_ms: str,
                      account_open_id: str = TEST_ACCOUNT_OPEN_ID) -> None:
    """原生 SQL 插入事件行。

    用 CAST(:raw_body AS jsonb) 写 JSONB 列 raw_body/parsed_content_json，
    绕过 ORM Text 契约（这两列的 JSONB 收敛是另立独立任务，不在本任务范围）。
    is_duplicate 用 Python bool 绑定到 PG boolean 列（A2/A3 写入契约验证）。
    """
    from sqlalchemy import text
    raw_body = {
        "event": "im_receive_msg",
        "from_user_id": TEST_CUSTOMER_OPEN_ID,
        "to_user_id": account_open_id,
        "content": (
            '{"event":"im_receive_msg","content":{'
            f'"conversation_short_id":"conv_{server_message_id}",'
            f'"server_message_id":"{server_message_id}",'
            f'"create_time":{create_time_ms},"text":"hello"}}'
        ),
    }
    parsed_content = {
        "conversation_short_id": f"conv_{server_message_id}",
        "server_message_id": server_message_id,
        "create_time": int(create_time_ms),
        "text": "hello",
    }
    import json as _json
    db.execute(
        text(
            """
            INSERT INTO douyin_webhook_events
              (event, from_user_id, to_user_id, conversation_short_id, server_message_id,
               message_create_time, parsed_content_json, parse_status, event_key,
               is_duplicate, raw_body, created_at)
            VALUES
              (:event, :from_user_id, :to_user_id, :conversation_short_id, :server_message_id,
               :message_create_time, CAST(:parsed_content AS jsonb), :parse_status, :event_key,
               :is_duplicate, CAST(:raw_body AS jsonb), :created_at)
            """
        ),
        {
            "event": "im_receive_msg",
            "from_user_id": TEST_CUSTOMER_OPEN_ID,
            "to_user_id": account_open_id,
            "conversation_short_id": f"conv_{server_message_id}",
            "server_message_id": server_message_id,
            "message_create_time": datetime.fromtimestamp(
                int(create_time_ms) / 1000, tz=timezone.utc),
            "parsed_content": _json.dumps(parsed_content, ensure_ascii=False),
            "parse_status": "parsed",
            "event_key": event_key,
            "is_duplicate": is_duplicate,  # bool 绑定 PG boolean，A2/A3
            "raw_body": _json.dumps(raw_body, ensure_ascii=False),
            "created_at": datetime.now(),
        },
    )
    db.commit()


def _cleanup_events(db):
    """精确清理测试行：企业号 open_id + event_key 前缀锁定。

    清理前先 rollback（避免查询抛 ProgrammingError 后会话失败事务，直接删会抛
    PendingRollbackError 遮蔽真正类型错误）；synchronize_session=False；
    清理失败仅 warning 不 re-raise 覆盖原始测试异常。
    """
    db.rollback()
    try:
        db.query(DouyinWebhookEvent).filter(
            DouyinWebhookEvent.to_user_id == TEST_ACCOUNT_OPEN_ID,
            DouyinWebhookEvent.event_key.like("bool%"),
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("PG 测试清理失败", exc_info=True)


@pg_required
def test_pg_unread_count_excludes_duplicate():
    """A1/A2/A3/A5：未读数路径只统计非重复消息；重复事件不计入；不抛 boolean=integer。

    直接调 `_query_message_rows()` 验证返回的非重复行数量，不走 `_parse_raw_body`
    （PG 返回 dict 与 json.loads 不兼容，raw_body JSONB 收敛是另立独立任务）。
    红灯：旧 ORM Integer + is_duplicate==0 在 PG 抛 ProgrammingError；新 .is_(False) 通过。
    """
    url = _safe_pg_url()
    rev = _ensure_alembic_head(url)
    assert rev != "unknown", f"PG 库未初始化，当前: {rev}"

    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker
    from app.services.douyin_workbench_conversation_service import _query_message_rows

    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    try:
        _cleanup_events(db)
        # A2：非重复事件写入 is_duplicate=False
        _insert_event_sql(db, event_key="bool_normal_1", is_duplicate=False,
                         server_message_id="srv_normal_1", create_time_ms="1700000000000")
        # A3：重复事件写入 is_duplicate=True，不应计入未读
        _insert_event_sql(db, event_key="bool_dup_1", is_duplicate=True,
                         server_message_id="srv_dup_1", create_time_ms="1700000001000")
        _insert_event_sql(db, event_key="bool_normal_2", is_duplicate=False,
                         server_message_id="srv_normal_2", create_time_ms="1700000002000")

        # A1/A5：未读数查询不抛 ProgrammingError。_query_message_rows 不读 raw_body 内容，
        # 只返回行（含 is_duplicate 过滤后的非重复行）。
        rows = _query_message_rows(
            db,
            account_open_id=None,
            account_open_ids=[TEST_ACCOUNT_OPEN_ID],
            conversation_key=None,
            events={"im_receive_msg"},
            limit=None,
            lookback_days=None,
        )
        # 非重复 im_receive_msg = 2 条；重复的 1 条被 .is_(False) 过滤掉
        assert len(rows) == 2, (
            f"未读数应只统计非重复消息=2，实际 {len(rows)}（重复事件未被过滤）"
        )
        # 验证返回行都是非重复（用 server_message_id 区分，select 列表含该字段）
        msg_ids = {row.server_message_id for row in rows}
        assert msg_ids == {"srv_normal_1", "srv_normal_2"}, (
            f"未读数应只含非重复事件，实际 {msg_ids}"
        )

        # 列类型确认是原生 BOOLEAN（未走 INTEGER）
        cols = {c["name"]: c["type"]
                for c in inspect(engine).get_columns("douyin_webhook_events")}
        assert "BOOLEAN" in str(cols["is_duplicate"]).upper()
    finally:
        _cleanup_events(db)
        db.close()
        engine.dispose()


@pg_required
def test_pg_query_filters_is_duplicate_true_and_false():
    """A6：webhook 事件筛选 is_duplicate=true/false 均正确，不抛 ProgrammingError。

    直接验证 `_apply_db_filters()` 生成的查询结果 event_key 集合，不读 raw_body 内容
    （避免触发未纳入本任务的 _parse_raw_body / JSONB 解析路径）。
    """
    url = _safe_pg_url()
    _ensure_alembic_head(url)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.webhook_event_service import _apply_db_filters, WebhookEventFilters

    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    try:
        _cleanup_events(db)
        _insert_event_sql(db, event_key="bool_filter_normal", is_duplicate=False,
                         server_message_id="srv_filter_n", create_time_ms="1700000010000")
        _insert_event_sql(db, event_key="bool_filter_dup", is_duplicate=True,
                         server_message_id="srv_filter_d", create_time_ms="1700000011000")

        # is_duplicate=true 只返回重复事件（只取 event_key，不读 JSONB 列内容）
        query_true = _apply_db_filters(
            db.query(DouyinWebhookEvent.id, DouyinWebhookEvent.event_key, DouyinWebhookEvent.is_duplicate),
            WebhookEventFilters(page=1, page_size=50, is_duplicate=True),
        )
        rows_true = query_true.all()
        keys_true = {row.event_key for row in rows_true}
        assert keys_true == {"bool_filter_dup"}, f"is_duplicate=true 应只返回重复事件，实际 {keys_true}"
        assert all(row.is_duplicate is True for row in rows_true)

        # is_duplicate=false 只返回非重复事件
        query_false = _apply_db_filters(
            db.query(DouyinWebhookEvent.id, DouyinWebhookEvent.event_key, DouyinWebhookEvent.is_duplicate),
            WebhookEventFilters(page=1, page_size=50, is_duplicate=False),
        )
        rows_false = query_false.all()
        keys_false = {row.event_key for row in rows_false}
        assert "bool_filter_normal" in keys_false
        assert "bool_filter_dup" not in keys_false
        assert all(row.is_duplicate is False for row in rows_false)
    finally:
        _cleanup_events(db)
        db.close()
        engine.dispose()
