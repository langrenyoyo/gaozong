"""抖音授权账号 PostgreSQL 类型契约回归测试。

背景：SQLite 时代 ORM/写入用 String/Text + str/json.dumps，与生产 PostgreSQL 的
TIMESTAMPTZ/JSONB schema 不一致，导致 auth-redirect 写入抛 ProgrammingError、授权账号
无法进入客服工作台列表。本测试收敛契约：上游时间写 aware datetime，JSON 写 dict。

设计（R2 返修审批要求）：
1. 时间解析 helper 单元测试（纯逻辑，无 DB，本地必须可跑）。
2. 真实 PostgreSQL 集成测试：用 Alembic 初始化到 0015 的一次性库，禁止 ORM 建表/删表，
   只写入并清理唯一测试行；真实调用 sync_bind_info_accounts 与 bind_authorized_account_by_open_id
   两条 service 路径，验证新增/更新/时间类型/JSONB 往返。
3. 安全门：PG URL 只允许 postgresql+psycopg + 白名单 host + 库名 _test/_staging 后缀；
   缺安全 PG 环境时守卫测试 fail（代表 TEST_BLOCKED），不假通过。
"""

import logging
import os
import sys
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config
from app.routers.douyin_live_check import _safe_sqlstate
from app.services.douyin_live_check_service import parse_upstream_datetime

logger = logging.getLogger(__name__)

# 固定测试商户；写入与清理都用它，与共享 _staging 库的其他行隔离。
TEST_MERCHANT_ID = "merchant_test_r2"


# ---------------------------------------------------------------------------
# 1. 时间解析 helper 单元测试（无 DB，本地可跑）
# ---------------------------------------------------------------------------

def test_parse_none_and_empty_returns_none():
    assert parse_upstream_datetime(None) is None
    assert parse_upstream_datetime("") is None


def test_parse_space_separated_naive_interpreted_as_shanghai():
    result = parse_upstream_datetime("2025-12-15 16:12:46")
    assert result is not None and result.tzinfo is not None
    # 2025-12-15 16:12:46 +08:00 == 08:12:46 UTC
    assert result == datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)


def test_parse_t_separator():
    assert parse_upstream_datetime("2025-12-15T16:12:46") == \
        datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)


def test_parse_z_suffix_keeps_instant_as_utc():
    assert parse_upstream_datetime("2025-12-15T08:12:46Z") == \
        datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)


def test_parse_offset_keeps_instant_and_converts_to_utc():
    assert parse_upstream_datetime("2025-12-15T16:12:46+08:00") == \
        datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)


def test_parse_invalid_raises():
    with pytest.raises(Exception):
        parse_upstream_datetime("not-a-date")


def test_parse_result_is_aware_for_pg_timestamptz():
    for raw in ("2025-12-15 16:12:46", "2025-12-15T16:12:46",
                "2025-12-15T08:12:46Z", "2025-12-15T16:12:46+08:00"):
        result = parse_upstream_datetime(raw)
        assert result is not None and result.tzinfo is not None


# ---------------------------------------------------------------------------
# 2. 安全 PG URL 守卫
# ---------------------------------------------------------------------------

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres"}


def _safe_pg_url() -> str | None:
    """校验 SMOKE_DATABASE_URL：postgresql+psycopg + 白名单 host + 库名 _test/_staging。

    用 SQLAlchemy 标准解析（make_url），避免手写 partition("@") 把 user:pass 当 host。
    不合规返回 None（仅缺 env 时）；协议/host/库名/query/fragment 不合规直接 fail。
    """
    url = os.getenv("SMOKE_DATABASE_URL", "").strip()
    if not url:
        return None
    # 拒绝 query/fragment：连接目标不得被额外参数改变
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
    """带账号密码 URL：标准解析 host=非 user 信息，放行。"""
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


def test_safe_sqlstate_unwraps_driver_attribute():
    """psycopg 驱动异常直接属性 exc.sqlstate 优先于 diag.sqlstate。

    复现：DatatypeMismatch 时 exception.sqlstate='42804'，exception.diag.sqlstate=None。
    旧实现只读 diag.sqlstate 会得到 None（日志丢失根因码）。
    """
    class _FakeDiag:
        sqlstate = None  # 服务器异常有时只留直接属性，diag 为空

    class _FakeOrig:
        sqlstate = "42804"  # psycopg 驱动异常直接属性
        diag = _FakeDiag()

    class _Wrapped(Exception):
        pass

    wrapped = _Wrapped("programming error")
    wrapped.orig = _FakeOrig()
    # 包装异常本身无 sqlstate，但 .orig 有 → 必须取到 42804
    assert _safe_sqlstate(wrapped) == "42804"


def test_safe_sqlstate_prefers_direct_attr_over_diag():
    """顺序：exc.sqlstate → exc.diag.sqlstate → exc.orig.sqlstate → exc.orig.diag.sqlstate。"""
    class _Diag:
        sqlstate = None

    class _Orig:
        sqlstate = None
        diag = _Diag()

    class _Wrapped(Exception):
        pass

    wrapped = _Wrapped()
    wrapped.orig = _Orig()
    assert _safe_sqlstate(wrapped) is None


def test_blocks_when_no_safe_pg_environment():
    """安全门：无安全 PG 环境时必须 fail（代表 TEST_BLOCKED），不能假通过。"""
    if os.getenv("SMOKE_DATABASE_URL", "").strip():
        pytest.skip("存在 PG 测试环境，本守卫测试不适用")
    pytest.fail(
        "TEST_BLOCKED: 缺少安全 PG 测试环境（SMOKE_DATABASE_URL 未设置）。"
        "请用一次性 Docker PG（库名以 _test/_staging 结尾）并 alembic 初始化到 0015 后重跑。"
    )


# ---------------------------------------------------------------------------
# 3. 真实 PostgreSQL 集成测试（需安全 PG，一次性库，禁 ORM 建表/删表）
# ---------------------------------------------------------------------------

pg_required = pytest.mark.skipif(
    not os.getenv("SMOKE_DATABASE_URL", "").strip(),
    reason="缺少安全 PG 测试环境（SMOKE_DATABASE_URL 未设置）",
)


def _ensure_alembic_head(url: str) -> str:
    """用 Alembic 把一次性库初始化到 0015 head。禁 ORM 建表，schema 由 0004 迁移声明。"""
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


def _make_context(merchant_id: str = TEST_MERCHANT_ID):
    """构造可信 RequestContext，merchant_id 来自服务端（非前端）。

    RequestContext 无 tenant_id 字段；service 用 getattr(context,'tenant_id',None) 安全取。
    """
    from app.auth.context import RequestContext
    return RequestContext(
        user_id="user_test_r2",
        merchant_id=merchant_id,
        source_system="new_car_project",
    )


def _cleanup_test_row(db, open_id: str):
    """精确清理唯一测试行：main_account_id + open_id + 固定测试商户三重锁定。

    清理前先 rollback（避免 service 抛 ProgrammingError 后会话处于失败事务，
    直接查询/删除会抛 PendingRollbackError 遮蔽真正的类型错误）；
    清理用 synchronize_session=False 避免触发会话内对象同步；
    清理失败仅记录，不 re-raise，避免覆盖原始测试异常。
    """
    from app.models import DouyinAuthorizedAccount
    db.rollback()
    try:
        db.query(DouyinAuthorizedAccount).filter_by(
            main_account_id=config.DY_MAIN_ACCOUNT_ID,
            open_id=open_id,
            merchant_id=TEST_MERCHANT_ID,
        ).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        # 清理失败不得覆盖原始测试异常；仅记录
        logger.warning("PG 测试清理失败 open_id=%s", bool(open_id), exc_info=True)


def _patch_upstream(monkeypatch, upstream_item):
    """monkeypatch service 模块内的 call_douyin_openapi，返回固定上游 /list_bind_info。"""
    from app.services import douyin_live_check_service as svc

    def _fake_call(path, payload):
        if path == "/list_bind_info":
            return {"payload": {"code": 0, "msg": "success",
                                "data": {"bind_list": [upstream_item]}},
                    "debug": {"upstream_url": "test"}}
        raise AssertionError(f"非预期上游调用: {path}")

    monkeypatch.setattr(svc, "call_douyin_openapi", _fake_call)


@pg_required
def test_pg_sync_bind_info_accounts_writes_datetime_and_dict(monkeypatch):
    """A1/A2/A6：sync_bind_info_accounts 真实路径写 aware datetime/dict 不抛 ProgrammingError。"""
    url = _safe_pg_url()
    rev = _ensure_alembic_head(url)
    assert "0015" in rev, f"PG 库未初始化到 0015，当前: {rev}"

    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker
    from app.models import DouyinAuthorizedAccount
    from app.services.douyin_live_check_service import sync_bind_info_accounts

    open_id = "test_pg_sync_open_id_r2"
    upstream_item = {
        "open_id": open_id,
        "user_id": "2106745398",
        "union_id": "union-test-r2",
        "account_name": "海赫科技",
        "avatar_url": "https://avatar.example.com/a.png",
        "bind_status": 1,
        "account_type": 1,
        "bind_time": "2025-12-15 16:12:46",  # 无时区，按 Asia/Shanghai 解释
        "unbind_time": None,
        "created_at": "2025-12-15 14:17:43",
    }
    _patch_upstream(monkeypatch, upstream_item)

    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    try:
        # 只清唯一测试行，禁删表
        _cleanup_test_row(db, open_id)

        # A1：不抛 ProgrammingError（走到这里即通过 A1）
        result = sync_bind_info_accounts(db, page_num=1, page_size=20,
                                         name_or_open_id=open_id,
                                         context=_make_context())
        assert result["upserted"] >= 1
        assert result["active_count"] >= 1

        row = db.query(DouyinAuthorizedAccount).filter_by(open_id=open_id).one()
        # A2：时间为 aware datetime
        assert row.bind_time is not None
        assert row.bind_time.tzinfo is not None, "bind_time 必须是 aware datetime"
        assert row.bind_time == datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)
        # A6：PG 读回 raw_body_json 为 dict（JSONB）
        assert isinstance(row.raw_body_json, dict)
        assert row.raw_body_json["open_id"] == open_id

        # 列类型确认是原生 TIMESTAMPTZ/JSONB（未走 VARCHAR/TEXT）
        cols = {c["name"]: c["type"]
                for c in inspect(engine).get_columns("douyin_authorized_accounts")}
        assert "TIMESTAMP" in str(cols["bind_time"]).upper()
        assert "JSONB" in str(cols["raw_body_json"]).upper()

        # 更新路径：account_name 变更应更新同一行，时间仍 aware
        upstream_item["account_name"] = "海赫科技-更新"
        sync_bind_info_accounts(db, page_num=1, page_size=20,
                                name_or_open_id=open_id, context=_make_context())
        row2 = db.query(DouyinAuthorizedAccount).filter_by(open_id=open_id).one()
        assert row2.account_name == "海赫科技-更新"
        assert row2.bind_time.tzinfo is not None
    finally:
        _cleanup_test_row(db, open_id)
        db.close()
        engine.dispose()


@pg_required
def test_pg_bind_authorized_account_by_open_id_writes_datetime_and_dict(monkeypatch):
    """A1/A2/A6：bind_authorized_account_by_open_id 第二条真实路径。"""
    url = _safe_pg_url()
    _ensure_alembic_head(url)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import DouyinAuthorizedAccount
    from app.services.douyin_live_check_service import bind_authorized_account_by_open_id

    open_id = "test_pg_bind_open_id_r2"
    upstream_item = {
        "open_id": open_id,
        "user_id": "u2",
        "union_id": "union2",
        "account_name": "测试绑定",
        "avatar_url": "",
        "bind_status": 1,
        "account_type": 1,
        "bind_time": "2025-12-15 20:16:39",
        "unbind_time": None,
        "created_at": "2025-12-15 16:44:56",
    }
    _patch_upstream(monkeypatch, upstream_item)

    engine = create_engine(url)
    db = sessionmaker(bind=engine)()
    try:
        _cleanup_test_row(db, open_id)

        result = bind_authorized_account_by_open_id(db, open_id=open_id,
                                                    context=_make_context())
        assert result is not None

        row = db.query(DouyinAuthorizedAccount).filter_by(open_id=open_id).one()
        assert row.bind_time.tzinfo is not None
        assert isinstance(row.raw_body_json, dict)
        assert row.raw_body_json["account_name"] == "测试绑定"
        assert str(row.merchant_id) == "merchant_test_r2"
    finally:
        _cleanup_test_row(db, open_id)
        db.close()
        engine.dispose()
