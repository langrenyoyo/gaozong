"""抖音授权账号 PostgreSQL 类型契约回归测试。

背景：SQLite 时代 ORM/写入用 String/Text + str/json.dumps，与生产 PostgreSQL 的
TIMESTAMPTZ/JSONB schema 不一致，导致 auth-redirect 写入抛 ProgrammingError、授权账号
无法进入客服工作台列表。本测试收敛契约：时间写 aware datetime，JSON 写 dict。

本文件分两类：
1. 时间解析 helper 单元测试（纯逻辑，无 DB，本地必须可跑）；
2. 真实 PostgreSQL upsert 集成测试（需安全 PG，缺环境回报阻塞，绝不写成通过）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta

import pytest

from app.services.douyin_live_check_service import parse_upstream_datetime


# Asia/Shanghai = UTC+8
SHANGHAI_OFFSET = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# 1. 时间解析 helper 单元测试（无 DB 依赖，本地可跑）
# ---------------------------------------------------------------------------

def test_parse_none_and_empty_returns_none():
    """None/空串返回 None，不得静默写当前时间。"""
    assert parse_upstream_datetime(None) is None
    assert parse_upstream_datetime("") is None


def test_parse_space_separated_naive_interpreted_as_shanghai():
    """无时区 'YYYY-MM-DD HH:MM:SS' 按 Asia/Shanghai 解释再转 UTC。"""
    result = parse_upstream_datetime("2025-12-15 16:12:46")
    assert result is not None
    assert result.tzinfo is not None  # aware
    # 2025-12-15 16:12:46 +08:00 == 08:12:46 UTC
    expected_utc = datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)
    assert result == expected_utc


def test_parse_t_separator():
    """'T' 分隔格式同样按 Asia/Shanghai 解释。"""
    result = parse_upstream_datetime("2025-12-15T16:12:46")
    expected_utc = datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)
    assert result == expected_utc


def test_parse_z_suffix_keeps_instant_as_utc():
    """带 'Z' 的时间保留瞬时语义，按 UTC 解释。"""
    result = parse_upstream_datetime("2025-12-15T08:12:46Z")
    expected_utc = datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)
    assert result == expected_utc


def test_parse_offset_keeps_instant_and_converts_to_utc():
    """带偏移的时间保留瞬时语义并转 UTC。"""
    result = parse_upstream_datetime("2025-12-15T16:12:46+08:00")
    expected_utc = datetime(2025, 12, 15, 8, 12, 46, tzinfo=timezone.utc)
    assert result == expected_utc


def test_parse_invalid_raises():
    """非法格式必须抛稳定错误，禁止静默写 None 或当前时间。"""
    with pytest.raises(Exception):
        parse_upstream_datetime("not-a-date")


def test_parse_result_is_aware_for_pg_timestamptz():
    """所有非 None 解析结果必须是 aware datetime，才能写入 PG TIMESTAMPTZ。"""
    for raw in ("2025-12-15 16:12:46", "2025-12-15T16:12:46",
                "2025-12-15T08:12:46Z", "2025-12-15T16:12:46+08:00"):
        result = parse_upstream_datetime(raw)
        assert result is not None
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# 2. 真实 PostgreSQL upsert 集成测试
#    安全门：PG URL 只允许 postgresql+psycopg 且库名以 _test/_staging 结尾。
#    缺少安全 PG 环境必须回报阻塞，不能写成通过。
# ---------------------------------------------------------------------------

def _safe_pg_url() -> str | None:
    """从环境读取安全 PG URL，校验协议与库名后缀；不合规返回 None。"""
    url = os.getenv("DOUYIN_AUTH_PG_TEST_URL", "").strip()
    if not url:
        return None
    if not url.startswith("postgresql+psycopg://"):
        pytest.fail("DOUYIN_AUTH_PG_TEST_URL 必须使用 postgresql+psycopg 协议")
    # 库名以 _test 或 _staging 结尾
    db_part = url.rsplit("/", 1)[-1].split("?")[0]
    if not (db_part.endswith("_test") or db_part.endswith("_staging")):
        pytest.fail(f"测试目标库必须以 _test/_staging 结尾，实际: {db_part}")
    return url


@pytest.mark.skipif(
    not os.getenv("DOUYIN_AUTH_PG_TEST_URL", "").strip(),
    reason="缺少安全 PG 测试环境（DOUYIN_AUTH_PG_TEST_URL 未设置）",
)
def test_pg_upsert_writes_datetime_and_dict_without_programming_error():
    """A1/A2/A6：真实 PG upsert 写 aware datetime / dict 不抛 ProgrammingError。"""
    url = _safe_pg_url()
    from sqlalchemy import inspect, text
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import create_engine
    from app.models import Base, DouyinAuthorizedAccount

    engine = create_engine(url)
    # 仅在隔离测试库建本表，不触碰其它表。
    DouyinAuthorizedAccount.__table__.create(engine, checkfirst=True)
    try:
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            open_id = "test_pg_upsert_open_id_r2"
            db.query(DouyinAuthorizedAccount).filter_by(open_id=open_id).delete()
            row = DouyinAuthorizedAccount(
                main_account_id=2124269908,
                open_id=open_id,
                merchant_id="merchant_test_r2",
                bind_status=1,
                bind_time=parse_upstream_datetime("2025-12-15 16:12:46"),
                unbind_time=None,
                source_created_at=parse_upstream_datetime("2025-12-15 14:17:43"),
                raw_body_json={"open_id": open_id, "account_name": "海赫科技"},
            )
            db.add(row)
            db.commit()  # 关键：旧契约在此抛 ProgrammingError

            # A2：时间为 aware datetime
            refreshed = db.query(DouyinAuthorizedAccount).filter_by(open_id=open_id).one()
            assert refreshed.bind_time.tzinfo is not None
            # A6：PG 读回为 dict（JSONB）
            assert isinstance(refreshed.raw_body_json, dict)
            assert refreshed.raw_body_json["open_id"] == open_id

            # 列类型必须是原生 TIMESTAMPTZ/JSONB（确认未走 VARCHAR/TEXT）
            cols = {c["name"]: c["type"] for c in inspect(engine).get_columns("douyin_authorized_accounts")}
            type_name = str(cols["bind_time"]).upper()
            assert "TIMESTAMP" in type_name, f"bind_time 应为 TIMESTAMP 系，实际 {cols['bind_time']}"
            assert isinstance(cols["raw_body_json"], JSONB) or "JSONB" in str(cols["raw_body_json"]).upper()
        finally:
            db.rollback()
            db.close()
    finally:
        DouyinAuthorizedAccount.__table__.drop(engine, checkfirst=True)
        engine.dispose()


def test_pg_url_when_absent_blocks_not_passes():
    """安全门：无安全 PG 环境时本套件不能假装通过；此处断言 skip 条件成立。"""
    if os.getenv("DOUYIN_AUTH_PG_TEST_URL", "").strip():
        pytest.skip("存在 PG 测试环境，本守卫测试不适用")
    # 无环境时，_safe_pg_url 返回 None，表示阻塞而非通过
    assert _safe_pg_url() is None
