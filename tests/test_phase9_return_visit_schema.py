"""Phase 9 微信到抖音回访数据合同测试（Task 1 红灯）。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 1。

锁定（Task 2 实现后全部通过）：
- ReturnVisitPrompt 扩展：confidence_threshold（非空浮点，默认 0.90）、fallback_message（非空文本，
  无 server_default 占位，NOT NULL）。
- ReturnVisitRun 扩展设计 §4.2 的 16 列；account_open_id 为 VARCHAR(255)；idempotency_key 唯一；
  会话级冷却索引 (merchant_id, account_open_id, conversation_short_id, customer_open_id, prompt_key)；
  dispatch_notification_id 索引。
- DouyinPrivateMessageSend.return_visit_run_id 唯一索引；既有 auto_reply_run_id 不变。
- 不新建第四张 Phase 9 业务表（只扩展三张既有表）。
- SQLite 0030 upgrade + 独立 downgrade 文件存在；从 0029 基线 apply 0030 后三表数据多重集一致、
  三条文案逐字一致、空值为 0、索引/唯一约束存在；未知 prompt_key 整体回滚不登记；幂等；
  显式 downgrade 精确恢复 0027 原列集、旧数据不丢、删除 0030 登记，随后可再次 upgrade。

Task 1 红灯：ORM 新列/约束/索引及 0030/downgrade 迁移文件均未实现，合同断言 FAIL；
迁移内容与 apply/downgrade 测试在文件存在前 SKIP（避免 ERROR 噪音）。
红灯只来自被测对象缺失，不来自测试语法、导入或 fixture 错误。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from migrations import migrate_sqlite


ROOT = Path(__file__).resolve().parents[1]
SQLITE_VERSIONS = ROOT / "migrations" / "versions"
SQLITE_DOWNGRADES = ROOT / "migrations" / "downgrades"

SQLITE_FILE_PHASE9 = SQLITE_VERSIONS / "0030_return_visit_phase9.sql"
SQLITE_DOWNGRADE_PHASE9 = SQLITE_DOWNGRADES / "0030_return_visit_phase9.sql"

# 设计 §4.1 已批准三条 fallback_message（逐字，F10）。迁移回填必须与此完全一致。
FALLBACK_MESSAGES = {
    "retain_contact_conversion": (
        "您好，刚才留存的联系方式似乎无法正常联系。"
        "麻烦您重新发送一个常用手机号或微信号，方便我们继续为您服务。"
    ),
    "finance_plan_followup": (
        "您好，关于您关注的金融方案，我们可以继续为您说明。"
        "您更想了解首付、月供还是分期期限？"
    ),
    "silent_customer_wakeup": (
        "您好，之前的咨询还需要我们继续协助吗？"
        "方便时告诉我您目前最关心的问题，我们再为您跟进。"
    ),
}

# 设计 §4.2 ReturnVisitRun 增量 16 列（精确）
RETURN_VISIT_RUN_NEW_COLUMNS = [
    "dispatch_notification_id",
    "trigger_message_fp",
    "idempotency_key",
    "account_open_id",
    "conversation_short_id",
    "customer_open_id",
    "context_server_message_id",
    "confidence",
    "model",
    "risk_flags_json",
    "gate_results_json",
    "last_failure_stage",
    "manual_takeover",
    "lease_owner",
    "lease_expires_at",
    "attempt_count",
]


def _unique_groups(cls):
    """返回 cls __table__ 上所有 UniqueConstraint 的列名元组（sorted 规范化）。"""
    from sqlalchemy import UniqueConstraint

    return {
        tuple(sorted(col.name for col in const.columns))
        for const in cls.__table__.constraints
        if isinstance(const, UniqueConstraint)
    }


def _index_column_sets(cls):
    """返回 cls __table__ 上所有索引的列名元组（sorted 规范化）。"""
    return {
        tuple(sorted(col.name for col in idx.columns))
        for idx in cls.__table__.indexes
    }


# ---------------------------------------------------------------------------
# ReturnVisitPrompt ORM 合同
# ---------------------------------------------------------------------------


def test_return_visit_prompt_confidence_threshold_column():
    """confidence_threshold：非空浮点，Python 默认 0.90（C6 阈值仅约束 LLM）。"""
    import app.models as models

    cols = models.ReturnVisitPrompt.__table__.columns
    assert "confidence_threshold" in cols.keys(), "ReturnVisitPrompt 缺少 confidence_threshold"
    col = cols["confidence_threshold"]
    assert not col.nullable, "confidence_threshold 必须 NOT NULL"
    assert col.default is not None and col.default.arg == 0.90, (
        "confidence_threshold Python 默认必须为 0.90"
    )


def test_return_visit_prompt_fallback_message_column():
    """fallback_message：非空文本，NOT NULL 无占位 server_default（F10）。"""
    import app.models as models

    cols = models.ReturnVisitPrompt.__table__.columns
    assert "fallback_message" in cols.keys(), "ReturnVisitPrompt 缺少 fallback_message"
    col = cols["fallback_message"]
    assert not col.nullable, "fallback_message 必须 NOT NULL"
    # 禁止 server_default 占位（F10：迁移回填已批准文案，不保留占位默认）
    assert col.server_default is None, "fallback_message 不得带 server_default 占位"


# ---------------------------------------------------------------------------
# ReturnVisitRun ORM 合同
# ---------------------------------------------------------------------------


def test_return_visit_run_new_columns():
    """设计 §4.2 的 16 列必须全部存在。"""
    import app.models as models

    cols = set(models.ReturnVisitRun.__table__.columns.keys())
    missing = [c for c in RETURN_VISIT_RUN_NEW_COLUMNS if c not in cols]
    assert not missing, f"ReturnVisitRun 缺少 Phase 9 新列: {missing}"


def test_return_visit_run_account_open_id_is_varchar255():
    """account_open_id 必须为 VARCHAR(255)（非 INTEGER，设计 §4.2）。"""
    import app.models as models

    col = models.ReturnVisitRun.__table__.columns["account_open_id"]
    type_name = col.type.__class__.__name__
    assert type_name in {"String", "VARCHAR"}, (
        f"account_open_id 必须是 String/VARCHAR，实际 {type_name}"
    )
    assert getattr(col.type, "length", None) == 255, (
        f"account_open_id 长度应为 255，实际 {getattr(col.type, 'length', None)}"
    )


def test_return_visit_run_idempotency_key_unique():
    """idempotency_key 唯一约束（uk_return_visit_runs_idempotency_key，C8/F11）。"""
    import app.models as models

    assert ("idempotency_key",) in _unique_groups(models.ReturnVisitRun), (
        "ReturnVisitRun 必须有 idempotency_key UniqueConstraint"
    )


def test_return_visit_run_cooldown_index():
    """会话级 24h 冷却索引（C8）：merchant/account/conversation/customer/prompt_key。"""
    import app.models as models

    expected = tuple(sorted((
        "merchant_id", "account_open_id", "conversation_short_id",
        "customer_open_id", "prompt_key",
    )))
    assert expected in _index_column_sets(models.ReturnVisitRun), (
        "ReturnVisitRun 缺少会话级冷却索引"
    )


def test_return_visit_run_dispatch_notification_index():
    """dispatch_notification_id 索引（锚点查询）。"""
    import app.models as models

    idx_sets = _index_column_sets(models.ReturnVisitRun)
    assert any("dispatch_notification_id" in idx for idx in idx_sets), (
        "ReturnVisitRun 缺少 dispatch_notification_id 索引"
    )


def test_return_visit_run_manual_takeover_not_null_default_false():
    """manual_takeover NOT NULL 默认 False（门禁标记）。"""
    import app.models as models

    col = models.ReturnVisitRun.__table__.columns["manual_takeover"]
    assert not col.nullable, "manual_takeover 必须 NOT NULL"


def test_return_visit_run_attempt_count_not_null_default_zero():
    """attempt_count NOT NULL 默认 0（崩溃恢复计数）。"""
    import app.models as models

    col = models.ReturnVisitRun.__table__.columns["attempt_count"]
    assert not col.nullable, "attempt_count 必须 NOT NULL"


# ---------------------------------------------------------------------------
# DouyinPrivateMessageSend ORM 合同
# ---------------------------------------------------------------------------


def test_douyin_private_message_send_return_visit_run_id():
    """return_visit_run_id 列存在且 unique=True（镜像 auto_reply_run_id，C12）。"""
    import app.models as models

    cols = models.DouyinPrivateMessageSend.__table__.columns
    assert "return_visit_run_id" in cols.keys(), (
        "DouyinPrivateMessageSend 缺少 return_visit_run_id"
    )
    col = cols["return_visit_run_id"]
    assert col.unique, "return_visit_run_id 必须 unique=True"


def test_douyin_private_message_send_auto_reply_run_id_preserved():
    """既有 auto_reply_run_id 不得被 Phase 9 改动。"""
    import app.models as models

    cols = models.DouyinPrivateMessageSend.__table__.columns
    assert "auto_reply_run_id" in cols.keys(), "auto_reply_run_id 必须保留"
    assert cols["auto_reply_run_id"].unique, "auto_reply_run_id 必须保持 unique"
    assert "sent_at" in cols.keys(), "sent_at 必须保留（限频/冷却时间基准）"


# ---------------------------------------------------------------------------
# 守护：不新建第四张 Phase 9 业务表
# ---------------------------------------------------------------------------


def test_no_fourth_phase9_business_table():
    """Phase 9 只扩展三张既有表，不得新建第四张业务表（F1/N6）。

    现在即 PASS（守护）；Task 2 实现后仍应 PASS，验证未越界建表。
    """
    import app.models as models

    # 既有 Phase 9 相关 ORM 类只应为这两张（DouyinPrivateMessageSend 是更早已有的表）
    allowed = {"ReturnVisitPrompt", "ReturnVisitRun"}
    found = {
        name for name, obj in vars(models).items()
        if name.startswith("ReturnVisit") and hasattr(obj, "__tablename__")
    }
    assert found == allowed, f"Phase 9 出现越界 ORM 类: {found - allowed}"


# ---------------------------------------------------------------------------
# 迁移文件存在性（红灯）
# ---------------------------------------------------------------------------


def test_sqlite_0030_upgrade_file_exists():
    assert SQLITE_FILE_PHASE9.is_file(), (
        "SQLite 迁移 0030_return_visit_phase9.sql 必须存在（versions 目录）"
    )


def test_sqlite_0030_downgrade_file_exists():
    assert SQLITE_DOWNGRADE_PHASE9.is_file(), (
        "SQLite 回滚 0030_return_visit_phase9.sql 必须存在（downgrades 目录，独立不被 runner 发现）"
    )


# ---------------------------------------------------------------------------
# SQLite apply/downgrade 行为测试（0030 未实现时 SKIP）
# ---------------------------------------------------------------------------


def _create_phase1_predecessor_tables(conn):
    """临时库 Phase 1 前置表（与 test_phase8b_delivery_schema 一致）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, "
        "applied_at DATETIME NOT NULL, "
        "description VARCHAR(200));"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales_staff ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_reply_decision_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS compute_packages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name VARCHAR(100), price_yuan INTEGER, token_amount INTEGER, "
        "enabled BOOLEAN DEFAULT 1, created_at DATETIME, updated_at DATETIME);"
    )


def _create_douyin_private_message_sends_shell(conn):
    """建 douyin_private_message_sends 壳（0004 建表 + 0018 加 auto_reply_run_id 后形态）。

    SQLite 迁移链 0027-0029 不含此表；0030 需对其加 return_visit_run_id。
    壳对齐当前 ORM 列集（减 return_visit_run_id），插入 1 行旧数据验证保留。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS douyin_private_message_sends ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "main_account_id INTEGER NOT NULL, "
        "conversation_short_id VARCHAR(255) NOT NULL, "
        "server_message_id VARCHAR(255) NOT NULL, "
        "from_user_id VARCHAR(255) NOT NULL, "
        "to_user_id VARCHAR(255) NOT NULL, "
        "customer_open_id VARCHAR(255), "
        "account_open_id VARCHAR(255), "
        "scene VARCHAR(64) NOT NULL DEFAULT 'im_reply_msg', "
        "content TEXT NOT NULL, "
        "request_body_json TEXT, "
        "response_body_json TEXT, "
        "upstream_msg_id VARCHAR(255), "
        "status VARCHAR(20) NOT NULL DEFAULT 'pending', "
        "error_code VARCHAR(64), "
        "error_message VARCHAR(500), "
        "manual_confirmed INTEGER NOT NULL DEFAULT 1, "
        "auto_send INTEGER NOT NULL DEFAULT 0, "
        "decision_log_id INTEGER, "
        "auto_reply_run_id INTEGER, "
        "send_source VARCHAR(32) NOT NULL DEFAULT 'manual', "
        "operator_id VARCHAR(255), "
        "created_at DATETIME, "
        "updated_at DATETIME, "
        "sent_at DATETIME);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_conversation "
        "ON douyin_private_message_sends(conversation_short_id);"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_douyin_private_message_sends_auto_reply_run "
        "ON douyin_private_message_sends(auto_reply_run_id);"
    )
    # 旧数据：验证 0030 重建/ALTER 后保留
    conn.execute(
        "INSERT INTO douyin_private_message_sends "
        "(main_account_id, conversation_short_id, server_message_id, "
        " from_user_id, to_user_id, content, status, auto_reply_run_id, "
        " send_source, sent_at) "
        "VALUES (1, 'conv1', 'msg1', 'acc1', 'cust1', '旧发送记录', "
        "        'sent', 100, 'ai_auto', '2026-07-13 10:00:00')"
    )


def _apply_on_temp(conn, version: str):
    mig = next(m for m in migrate_sqlite.discover_migrations() if m.version == version)
    stmts = migrate_sqlite._load_stmts(mig.path)
    return migrate_sqlite.apply_migration(conn, stmts, mig.version, mig.description)


def _apply_phase9_baseline(conn):
    """apply 0027→0028→0029（Phase 9 前置基线）。"""
    for v in ["0027", "0028", "0029"]:
        _apply_on_temp(conn, v)


def test_sqlite_0030_apply_adds_columns_and_backfills_approved_text(tmp_path):
    """从 0029 基线 apply 0030：三表新列出现 + 三条文案逐字回填 + 空值为 0。"""
    if not SQLITE_FILE_PHASE9.is_file():
        pytest.skip("SQLite 0030 未实现（Task 2 才建）")
    db_path = tmp_path / "phase9_0030_apply.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _create_douyin_private_message_sends_shell(conn)
        _apply_phase9_baseline(conn)
        result = _apply_on_temp(conn, "0030")
    finally:
        conn.close()

    assert result.already_applied is False

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        # return_visit_prompts：confidence_threshold + fallback_message 列出现
        prompt_cols = migrate_sqlite.get_columns(conn, "return_visit_prompts")
        assert "confidence_threshold" in prompt_cols, "return_visit_prompts 缺 confidence_threshold"
        assert "fallback_message" in prompt_cols, "return_visit_prompts 缺 fallback_message"
        # 三条文案逐字一致 + 零空值
        rows = {
            r[0]: r[1] for r in conn.execute(
                "SELECT prompt_key, fallback_message FROM return_visit_prompts"
            )
        }
        for key, expected in FALLBACK_MESSAGES.items():
            assert rows.get(key) == expected, (
                f"fallback_message 逐字不一致 ({key}): 预期={expected!r} 实际={rows.get(key)!r}"
            )
        empty_count = conn.execute(
            "SELECT count(*) FROM return_visit_prompts "
            "WHERE fallback_message IS NULL OR fallback_message = ''"
        ).fetchone()[0]
        assert empty_count == 0, f"fallback_message 存在空值 {empty_count} 行"

        # return_visit_runs：16 新列出现
        run_cols = migrate_sqlite.get_columns(conn, "return_visit_runs")
        missing = [c for c in RETURN_VISIT_RUN_NEW_COLUMNS if c not in run_cols]
        assert not missing, f"return_visit_runs apply 后缺列 {missing}"

        # douyin_private_message_sends：return_visit_run_id 出现 + auto_reply_run_id 保留
        send_cols = migrate_sqlite.get_columns(conn, "douyin_private_message_sends")
        assert "return_visit_run_id" in send_cols, "douyin_private_message_sends 缺 return_visit_run_id"
        assert "auto_reply_run_id" in send_cols, "auto_reply_run_id 丢失"

        # 版本只登记一次
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0030'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_sqlite_0030_apply_rejects_unknown_prompt_key(tmp_path):
    """基线含第四个未知 prompt_key 时，0030 整体回滚不登记（F10 前置校验）。"""
    if not SQLITE_FILE_PHASE9.is_file():
        pytest.skip("SQLite 0030 未实现（Task 2 才建）")
    db_path = tmp_path / "phase9_0030_unknown_key.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_phase9_baseline(conn)
        # 注入第四键（违反"仅三键"前置校验）
        conn.execute(
            "INSERT INTO return_visit_prompts "
            "(prompt_key, name, scene_type, template_text, scope, enabled, sort_order, "
            " created_at, updated_at) "
            "VALUES ('unknown_fourth_key', '越界', 'x', 't', 'global', 1, 99, "
            "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0030")
    finally:
        conn.close()

    # 回滚验证：0030 未登记 + 新列未出现
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0030'"
        ).fetchone()[0] == 0, "未知键场景 0030 不应登记"
        prompt_cols = migrate_sqlite.get_columns(conn, "return_visit_prompts")
        assert "fallback_message" not in prompt_cols, (
            "回滚后 return_visit_prompts 不应出现 fallback_message"
        )
    finally:
        conn.close()


def test_sqlite_0030_apply_is_idempotent(tmp_path):
    """0030 apply 两次，第二次 already_applied=True（整体跳过）。"""
    if not SQLITE_FILE_PHASE9.is_file():
        pytest.skip("SQLite 0030 未实现（Task 2 才建）")
    db_path = tmp_path / "phase9_0030_idem.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _create_douyin_private_message_sends_shell(conn)
        _apply_phase9_baseline(conn)
        first = _apply_on_temp(conn, "0030")
        second = _apply_on_temp(conn, "0030")
    finally:
        conn.close()

    assert first.already_applied is False
    assert second.already_applied is True


def test_sqlite_0030_preserves_existing_data(tmp_path):
    """0030 apply 后 douyin_private_message_sends 旧数据行数/max(id) 不变。"""
    if not SQLITE_FILE_PHASE9.is_file():
        pytest.skip("SQLite 0030 未实现（Task 2 才建）")
    db_path = tmp_path / "phase9_0030_preserve.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _create_douyin_private_message_sends_shell(conn)
        before_count = conn.execute(
            "SELECT count(*) FROM douyin_private_message_sends"
        ).fetchone()[0]
        before_max_id = conn.execute(
            "SELECT coalesce(max(id),0) FROM douyin_private_message_sends"
        ).fetchone()[0]
        _apply_phase9_baseline(conn)
        _apply_on_temp(conn, "0030")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        after_count = conn.execute(
            "SELECT count(*) FROM douyin_private_message_sends"
        ).fetchone()[0]
        after_max_id = conn.execute(
            "SELECT coalesce(max(id),0) FROM douyin_private_message_sends"
        ).fetchone()[0]
        assert after_count == before_count, (
            f"douyin_private_message_sends 丢失行: {before_count} -> {after_count}"
        )
        assert after_max_id == before_max_id, (
            f"douyin_private_message_sends max(id) 变化: {before_max_id} -> {after_max_id}"
        )
    finally:
        conn.close()


def test_sqlite_0030_downgrade_restores_baseline_and_reupgradable(tmp_path):
    """显式执行 downgrade：新列全消失 + 旧数据不丢 + 删除 0030 登记 + 可再次 upgrade。"""
    if not SQLITE_FILE_PHASE9.is_file() or not SQLITE_DOWNGRADE_PHASE9.is_file():
        pytest.skip("SQLite 0030 upgrade/downgrade 未实现（Task 2 才建）")
    db_path = tmp_path / "phase9_0030_downgrade.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _create_douyin_private_message_sends_shell(conn)
        _apply_phase9_baseline(conn)
        _apply_on_temp(conn, "0030")
        before_count = conn.execute(
            "SELECT count(*) FROM douyin_private_message_sends"
        ).fetchone()[0]
        # 显式执行 downgrade（独立 SQL，不走 runner）
        downgrade_sql = SQLITE_DOWNGRADE_PHASE9.read_text(encoding="utf-8")
        conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        # 新列全部消失（精确恢复 0027 原列集）
        prompt_cols = migrate_sqlite.get_columns(conn, "return_visit_prompts")
        assert "confidence_threshold" not in prompt_cols, "downgrade 后 confidence_threshold 应消失"
        assert "fallback_message" not in prompt_cols, "downgrade 后 fallback_message 应消失"
        run_cols = migrate_sqlite.get_columns(conn, "return_visit_runs")
        missing_still = [c for c in RETURN_VISIT_RUN_NEW_COLUMNS if c in run_cols]
        assert not missing_still, f"downgrade 后新列应全部消失，仍存在: {missing_still}"
        send_cols = migrate_sqlite.get_columns(conn, "douyin_private_message_sends")
        assert "return_visit_run_id" not in send_cols, "downgrade 后 return_visit_run_id 应消失"
        assert "auto_reply_run_id" in send_cols, "downgrade 后 auto_reply_run_id 必须保留"
        # 旧数据不丢
        after_count = conn.execute(
            "SELECT count(*) FROM douyin_private_message_sends"
        ).fetchone()[0]
        assert after_count == before_count, "downgrade 丢失旧数据"
        # 0030 登记已删除
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0030'"
        ).fetchone()[0] == 0, "downgrade 后 0030 登记应删除"
    finally:
        conn.close()

    # 可再次 upgrade（往返验证）
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        again = _apply_on_temp(conn, "0030")
    finally:
        conn.close()
    assert again.already_applied is False, "downgrade 后应能再次 apply 0030"
