# 9000 PostgreSQL JSONB / ORM 一致性首批返修实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 webhook、抖音发送流水和 AI 决策日志共 10 个高优先级 JSONB 字段的 ORM 映射，并在真实本地 PostgreSQL 下闭合写入、读取、文本筛选和 webhook 原子占位合同。

**Architecture:** 将现有 `_GateResultsJSON` 最小泛化为保持 `str | None` 业务合同的 `_JSONStringJSONB`，PostgreSQL 使用 JSONB、SQLite 使用 TEXT。webhook 原子占位删除手工 JSONB CAST，现有 JSON 文本筛选使用显式 `cast(column, Text).like(...)`，不改变 API、发送门禁、幂等或事务边界。

**Tech Stack:** Python 3.14、SQLAlchemy 2.x、PostgreSQL 及 psycopg、SQLite、Alembic、pytest。

---

## 执行合同

- Task-ID：`P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1`
- Plan-Revision：`R1`
- Risk-Level：`L3 / HIGH`
- Functional-Base：`f3944a1c7368f3ae2ce529a718cd905e345d736c`
- Execution-Base：`1042a07`（已批准设计规格提交）
- 设计规格：`docs/superpowers/specs/2026-07-27-9000-postgres-jsonb-orm-parity-repair-design.md`
- 执行方式：必须另开执行窗口；本审批窗口不执行本计划。
- 工作区偏好：按项目入口规则原地执行，不创建 worktree、不新建分支。

执行窗口开始前必须完整阅读：

```text
CLAUDE.md
docs/ai/01_READING_RULES.md
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/02_EXECUTION_RULES.md
docs/ai/03_TESTING_RULES.md
docs/ai/04_OUTPUT_RULES.md
docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md
docs/superpowers/specs/2026-07-27-9000-postgres-jsonb-orm-parity-repair-design.md
本计划
```

禁止修改、取消暂存或提交执行窗口开始时已有的四份治理计划。提交实现时一律使用：

```powershell
git commit --only -m "中文提交信息" -- <本提交允许文件>
```

## 文件职责与允许范围

| 文件 | 职责 |
|---|---|
| `app/models.py` | 定义共享 `_JSONStringJSONB`，映射原 gate 字段和首批 10 个字段 |
| `app/services/douyin_webhook_idempotency_service.py` | 保留原子占位，删除手工 JSONB CAST |
| `app/services/webhook_event_service.py` | webhook JSON 文本筛选显式转 TEXT |
| `app/services/douyin_merchant_isolation.py` | 客户归属兜底筛选显式转 TEXT |
| `app/services/douyin_workbench_conversation_service.py` | 工作台会话兼容筛选显式转 TEXT |
| `app/services/ai_reply_decision_log_query_service.py` | 风险标记筛选显式转 TEXT |
| `tests/test_douyin_webhook_atomic_idempotency.py` | 更新 PostgreSQL 原子语句静态合同并保护既有幂等回归 |
| `tests/test_9000_postgres_jsonb_orm_parity.py` | 新增跨方言合同及真实 PostgreSQL 行为、并发、清理测试 |

不得修改 `migrations/**`、Docker、Compose、环境模板、第二批 11 个字段或冻结模块 6 个字段。

### Task 1: 预检并建立共享类型静态合同

**Files:**
- Create: `tests/test_9000_postgres_jsonb_orm_parity.py`
- Read: `app/models.py:1-60`
- Read: `tests/helpers/outbox_restart_worker.py`

- [ ] **Step 1: 核验执行基线和治理文件隔离**

运行：

```powershell
git rev-parse HEAD
git status --short
git show --no-patch --format=%H%n%P HEAD
```

预期：

```text
HEAD = 1042a07...
工作区只有四份 docs/superpowers/plans/*.md 已暂存
HEAD 为单父提交，父提交是 f3944a1...
```

若出现任何业务文件改动、额外未跟踪文件或基线不一致，停止并回传审批窗口。

- [ ] **Step 2: 创建首批字段静态合同测试**

创建 `tests/test_9000_postgres_jsonb_orm_parity.py`，内容如下：

```python
"""9000 PostgreSQL JSONB / ORM 一致性首批返修测试。"""

import json

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models import (
    AiAutoReplyRun,
    AiReplyDecisionLog,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    _JSONStringJSONB,
)


JSON_STRING_COLUMNS = (
    (AiAutoReplyRun, "gate_results_json"),
    (DouyinWebhookEvent, "raw_body"),
    (DouyinWebhookEvent, "parsed_content_json"),
    (DouyinPrivateMessageSend, "request_body_json"),
    (DouyinPrivateMessageSend, "response_body_json"),
    (AiReplyDecisionLog, "risk_flags_json"),
    (AiReplyDecisionLog, "tags_json"),
    (AiReplyDecisionLog, "rag_sources_json"),
    (AiReplyDecisionLog, "source_chunks_json"),
    (AiReplyDecisionLog, "allowed_category_keys_json"),
    (AiReplyDecisionLog, "raw_response_json"),
)


@pytest.mark.parametrize(("model", "column_name"), JSON_STRING_COLUMNS)
def test_j1_j2_shared_type_compiles_to_jsonb_and_text(model, column_name):
    column_type = model.__table__.c[column_name].type
    assert isinstance(column_type, _JSONStringJSONB)
    assert str(column_type.compile(dialect=postgresql.dialect())).upper() == "JSONB"
    assert str(column_type.compile(dialect=sqlite.dialect())).upper() == "TEXT"


def test_j3_shared_type_preserves_string_json_contract():
    column_type = _JSONStringJSONB()
    pg = postgresql.dialect()
    sq = sqlite.dialect()

    assert column_type.process_bind_param(None, pg) is None
    assert column_type.process_bind_param(None, sq) is None
    assert column_type.process_bind_param('{"a":1}', pg) == {"a": 1}
    assert column_type.process_bind_param('["x"]', pg) == ["x"]
    assert column_type.process_bind_param('"scalar"', pg) == "scalar"
    assert column_type.process_bind_param('{"a":1}', sq) == '{"a":1}'
    assert json.loads(column_type.process_result_value({"a": 1}, pg)) == {"a": 1}
    assert column_type.process_result_value('{"a":1}', sq) == '{"a":1}'

    with pytest.raises(json.JSONDecodeError):
        column_type.process_bind_param("{bad", pg)
```

- [ ] **Step 3: 运行测试并确认先失败**

运行：

```powershell
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q
```

预期：测试收集失败，原因是 `app.models` 尚无 `_JSONStringJSONB`。

### Task 2: 泛化共享类型并映射首批字段

**Files:**
- Modify: `app/models.py:1-60`
- Modify: `app/models.py:301-330`
- Modify: `app/models.py:408-479`
- Modify: `app/models.py:488-520`
- Test: `tests/test_9000_postgres_jsonb_orm_parity.py`

- [ ] **Step 1: 将 `_GateResultsJSON` 原位替换为共享类型**

将现有类型类替换为：

```python
class _JSONStringJSONB(TypeDecorator):
    """保持字符串 JSON 业务合同的方言感知类型。

    业务层统一写入和读取 ``str | None``。PostgreSQL 使用 JSONB，写入前解析
    JSON 字符串以避免双重编码，读回后重新序列化为字符串；SQLite 继续使用
    TEXT。``None`` 保持 SQL NULL，PostgreSQL 非法 JSON 直接失败。
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB(none_as_null=True))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # PostgreSQL 保存原生 JSON 值，禁止把 JSON 文本再次编码成字符串标量。
            return json.loads(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # 业务层仍按字符串 JSON 消费，不扩散 dict/list 合同。
            return json.dumps(value, ensure_ascii=False)
        return value
```

- [ ] **Step 2: 将原 gate 字段和首批 10 个字段改用共享类型**

严格使用以下字段声明：

```python
class DouyinWebhookEvent(Base):
    parsed_content_json = Column(_JSONStringJSONB(), comment="Parsed content JSON object")
    raw_body = Column(_JSONStringJSONB(), nullable=False, comment="原始 payload JSON")


class DouyinPrivateMessageSend(Base):
    request_body_json = Column(_JSONStringJSONB(), comment="Sanitized upstream request JSON")
    response_body_json = Column(_JSONStringJSONB(), comment="Upstream response JSON")


class AiReplyDecisionLog(Base):
    risk_flags_json = Column(_JSONStringJSONB(), comment="最终风险标记 JSON")
    tags_json = Column(_JSONStringJSONB(), comment="客户标签 JSON")
    rag_sources_json = Column(_JSONStringJSONB(), comment="RAG 来源 JSON")
    source_chunks_json = Column(_JSONStringJSONB(), comment="旧版 source_chunks JSON")
    allowed_category_keys_json = Column(_JSONStringJSONB(), comment="9000 注入的可信知识分类 key JSON")
    raw_response_json = Column(_JSONStringJSONB(), comment="9100 原始响应 JSON 副本")


class AiAutoReplyRun(Base):
    gate_results_json = Column(_JSONStringJSONB())
```

不得修改 `ReturnVisitRun.gate_results_json` 或其他 `Text` JSON 字段。

- [ ] **Step 3: 运行静态合同和既有 gate 合同**

运行：

```powershell
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q
python -m pytest tests/test_9000_postgres_ai_auto_reply_outbox_schema.py -q
```

预期：新文件静态合同全部通过；既有 outbox schema 合同 11 passed。

- [ ] **Step 4: 运行最小 SQLite 字符串合同回归**

运行：

```powershell
python -m pytest tests/test_ai_reply_decision_logs_api.py tests/test_ai_auto_reply_send_service.py tests/test_webhook_events.py -q
```

预期：0 failed，原有字符串相等断言和非法字符串兼容测试不回归。

- [ ] **Step 5: 提交共享类型与静态合同**

运行：

```powershell
git commit --only -m "修复：统一高优先级JSONB ORM映射" -- app/models.py tests/test_9000_postgres_jsonb_orm_parity.py
```

预期：单父提交；四份既有治理计划仍保持暂存。

### Task 3: 消除 webhook 手工 CAST 与双重编码

**Files:**
- Modify: `app/services/douyin_webhook_idempotency_service.py:10-55`
- Modify: `tests/test_douyin_webhook_atomic_idempotency.py:1-17`
- Modify: `tests/test_douyin_webhook_atomic_idempotency.py:196-210`
- Modify: `tests/test_9000_postgres_jsonb_orm_parity.py`

- [ ] **Step 1: 更新旧 A1 测试为新 SQL 合同**

替换旧 A1 测试，并同步更新文件头部的 A1 描述：

```python
def test_a1_claim_statement_uses_postgresql_on_conflict_returning_without_manual_jsonb_cast():
    """A1：由列类型完成 JSONB 参数绑定，语句保留原子占位且没有手工 CAST。"""
    statement = build_webhook_claim_statement("postgresql", _claim_values())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (event_key) DO NOTHING" in sql
    assert "RETURNING" in sql and "douyin_webhook_events.id" in sql
    assert "CAST(" not in sql
    assert " AS JSONB" not in sql
```

- [ ] **Step 2: 运行新 A1 并确认失败**

运行：

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py::test_a1_claim_statement_uses_postgresql_on_conflict_returning_without_manual_jsonb_cast -q
```

预期：失败，因为实现仍生成两个手工 CAST。

- [ ] **Step 3: 删除 webhook 原子语句的手工 CAST**

将导入改为：

```python
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
```

将 PostgreSQL 分支替换为：

```python
if dialect_name == "postgresql":
    return (
        postgresql_insert(table)
        .values(**values)
        .on_conflict_do_nothing(index_elements=[table.c.event_key])
        .returning(table.c.id)
    )
```

Update the docstring to state that both dialects use the table column type for JSON binding. Remove unused `cast` and `JSONB` imports.

- [ ] **Step 4: 在新测试文件中加入安全 PostgreSQL 夹具**

把以下导入合并到 `tests/test_9000_postgres_jsonb_orm_parity.py` 顶部，并加入辅助函数：

```python
import importlib.util
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tests" / "helpers" / "outbox_restart_worker.py"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("jsonb_parity_worker_contract", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pg_url() -> str:
    raw = os.environ.get("SMOKE_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("SMOKE_DATABASE_URL 未设置，跳过真实 PostgreSQL 专项")
    return _load_worker_module()._validate_smoke_database_url(raw)


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_pg_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
    yield engine
    engine.dispose()


def _namespace() -> str:
    return f"jsonb_parity_{uuid.uuid4().hex}"


def _cleanup_namespace(engine, namespace: str) -> None:
    prefix = f"{namespace}%"
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM douyin_private_message_sends "
                "WHERE conversation_short_id LIKE :prefix OR decision_log_id IN "
                "(SELECT id FROM ai_reply_decision_logs WHERE merchant_id = :namespace)"
            ),
            {"prefix": prefix, "namespace": namespace},
        )
        conn.execute(
            text("DELETE FROM ai_reply_decision_logs WHERE merchant_id = :namespace"),
            {"namespace": namespace},
        )
        conn.execute(
            text("DELETE FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
            {"prefix": prefix},
        )
        conn.execute(
            text("DELETE FROM douyin_authorized_accounts WHERE open_id LIKE :prefix"),
            {"prefix": prefix},
        )


@pytest.fixture
def pg_case(pg_engine):
    namespace = _namespace()
    session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    db = session_factory()
    try:
        yield db, namespace, session_factory
    finally:
        db.rollback()
        db.close()
        _cleanup_namespace(pg_engine, namespace)
        with pg_engine.connect() as conn:
            remaining = conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM douyin_private_message_sends "
                    " WHERE conversation_short_id LIKE :prefix), "
                    "(SELECT count(*) FROM ai_reply_decision_logs "
                    " WHERE merchant_id = :namespace), "
                    "(SELECT count(*) FROM douyin_webhook_events "
                    " WHERE event_key LIKE :prefix), "
                    "(SELECT count(*) FROM douyin_authorized_accounts "
                    " WHERE open_id LIKE :prefix)"
                ),
                {"prefix": f"{namespace}%", "namespace": namespace},
            ).one()
        assert tuple(remaining) == (0, 0, 0, 0)
```

- [ ] **Step 5: 加入真实 PostgreSQL webhook 对象存储与并发测试**

加入以下测试：

```python
from app.services.douyin_webhook_idempotency_service import claim_webhook_event


def _claim_values(namespace: str, suffix: str = "event") -> dict:
    content = {
        "conversation_short_id": f"{namespace}_conversation",
        "server_message_id": f"{namespace}_message",
        "message_type": "text",
        "text": "JSONB 一致性测试",
    }
    payload = {
        "event": "im_receive_msg",
        "from_user_id": f"{namespace}_customer",
        "to_user_id": f"{namespace}_account",
        "content": json.dumps(content, ensure_ascii=False),
    }
    return {
        "event": payload["event"],
        "from_user_id": payload["from_user_id"],
        "to_user_id": payload["to_user_id"],
        "conversation_short_id": content["conversation_short_id"],
        "server_message_id": content["server_message_id"],
        "parsed_content_json": json.dumps(content, ensure_ascii=False),
        "event_key": f"{namespace}_{suffix}",
        "is_duplicate": False,
        "merchant_id": namespace,
        "tenant_id": f"{namespace}_tenant",
        "raw_body": json.dumps(payload, ensure_ascii=False),
    }


def test_j4_postgres_orm_writes_and_reads_webhook_json_strings(pg_case, pg_engine):
    db, namespace, _ = pg_case
    raw_body = json.dumps({"event": "im_receive_msg", "source": "orm"}, ensure_ascii=False)
    parsed_content = json.dumps({"message_type": "text", "text": "ORM 写入"}, ensure_ascii=False)
    event = DouyinWebhookEvent(
        event="im_receive_msg",
        event_key=f"{namespace}_orm",
        is_duplicate=False,
        raw_body=raw_body,
        parsed_content_json=parsed_content,
        merchant_id=namespace,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    assert json.loads(event.raw_body)["source"] == "orm"
    assert json.loads(event.parsed_content_json)["text"] == "ORM 写入"
    with pg_engine.connect() as conn:
        types = conn.execute(
            text(
                "SELECT jsonb_typeof(raw_body), jsonb_typeof(parsed_content_json) "
                "FROM douyin_webhook_events WHERE id = :event_id"
            ),
            {"event_id": event.id},
        ).one()
    assert tuple(types) == ("object", "object")


def test_j5_j6_postgres_webhook_claim_stores_objects_not_string_scalars(pg_case, pg_engine):
    db, namespace, _ = pg_case
    claim = claim_webhook_event(db, values=_claim_values(namespace))
    assert claim.won is True
    db.commit()

    assert isinstance(claim.event.raw_body, str)
    assert isinstance(claim.event.parsed_content_json, str)
    assert json.loads(claim.event.raw_body)["event"] == "im_receive_msg"
    assert json.loads(claim.event.parsed_content_json)["message_type"] == "text"

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT jsonb_typeof(raw_body), jsonb_typeof(parsed_content_json) "
                "FROM douyin_webhook_events WHERE event_key = :event_key"
            ),
            {"event_key": f"{namespace}_event"},
        ).one()
    assert tuple(row) == ("object", "object")


def test_j7_postgres_twenty_way_claim_has_one_winner_for_ten_rounds(pg_case):
    _, namespace, session_factory = pg_case

    for round_no in range(10):
        values = _claim_values(namespace, suffix=f"race_{round_no}")
        barrier = Barrier(20)

        def worker() -> bool:
            db = session_factory()
            try:
                barrier.wait(timeout=10)
                claim = claim_webhook_event(db, values=values)
                db.commit()
                return claim.won
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=20) as executor:
            winners = list(executor.map(lambda _: worker(), range(20)))

        assert sum(winners) == 1
        verify_db = session_factory()
        try:
            assert (
                verify_db.query(DouyinWebhookEvent)
                .filter(DouyinWebhookEvent.event_key == values["event_key"])
                .count()
            ) == 1
        finally:
            verify_db.close()
```

- [ ] **Step 6: 运行 webhook 合同**

运行：

```powershell
python -m pytest tests/test_douyin_webhook_atomic_idempotency.py::test_a1_claim_statement_uses_postgresql_on_conflict_returning_without_manual_jsonb_cast -q
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q -rs
```

预期：0 failed；设置 `SMOKE_DATABASE_URL` 时 0 skipped；真实 PostgreSQL 两个字段的 `jsonb_typeof` 均为 `object`，20 路竞争 10 轮每轮恰好一个胜出。

- [ ] **Step 7: 提交 webhook 返修**

运行：

```powershell
git commit --only -m "修复：消除webhook JSONB双重编码" -- app/services/douyin_webhook_idempotency_service.py tests/test_douyin_webhook_atomic_idempotency.py tests/test_9000_postgres_jsonb_orm_parity.py
```

### Task 4: 兼容 JSONB 文本筛选

**Files:**
- Modify: `app/services/webhook_event_service.py:9-10,142-173`
- Modify: `app/services/douyin_merchant_isolation.py:7-8,35-59`
- Modify: `app/services/douyin_workbench_conversation_service.py:13-15,1020-1065`
- Modify: `app/services/ai_reply_decision_log_query_service.py:15-17,152-175`
- Modify: `tests/test_9000_postgres_jsonb_orm_parity.py`

- [ ] **Step 1: 加入 PostgreSQL 文本筛选失败合同**

把以下模型和服务导入合并到测试文件顶部：

```python
from app.models import DouyinAuthorizedAccount, DouyinPrivateMessageSend
from app.services.ai_reply_decision_log_query_service import (
    AiReplyDecisionLogQuery,
    list_ai_reply_decision_logs,
)
from app.services.douyin_merchant_isolation import require_customer_open_id_for_merchant
from app.services.douyin_workbench_conversation_service import list_conversation_messages
from app.services.webhook_event_service import WebhookEventFilters, list_webhook_events
```

加入以下测试：

```python
def _seed_account(db, namespace: str) -> None:
    db.add(
        DouyinAuthorizedAccount(
            merchant_id=namespace,
            main_account_id=1,
            open_id=f"{namespace}_account",
            bind_status=1,
            raw_body_json={"source": "jsonb_parity"},
        )
    )
    db.commit()


def test_j11_webhook_and_merchant_filters_cast_jsonb_to_text(pg_case):
    db, namespace, _ = pg_case
    _seed_account(db, namespace)
    values = _claim_values(namespace, suffix="filter")
    hidden_customer = f"{namespace}_hidden_customer"
    payload = json.loads(values["raw_body"])
    payload["open_id"] = hidden_customer
    payload["account_open_id"] = f"{namespace}_account"
    values["raw_body"] = json.dumps(payload, ensure_ascii=False)
    values["from_user_id"] = f"{namespace}_other_from"
    values["to_user_id"] = f"{namespace}_other_to"
    claim_webhook_event(db, values=values)
    db.commit()

    result = list_webhook_events(
        db,
        WebhookEventFilters(keyword=hidden_customer),
        super_admin=True,
    )
    assert result["total"] == 1

    require_customer_open_id_for_merchant(
        db,
        merchant_id=namespace,
        customer_open_id=hidden_customer,
    )


def test_j11_workbench_conversation_filter_casts_jsonb_to_text(pg_case):
    db, namespace, _ = pg_case
    _seed_account(db, namespace)
    values = _claim_values(namespace, suffix="workbench")
    conversation_key = f"{namespace}_raw_only_conversation"
    parsed = json.loads(values["parsed_content_json"])
    parsed["conversation_short_id"] = conversation_key
    payload = json.loads(values["raw_body"])
    payload["content"] = json.dumps(parsed, ensure_ascii=False)
    values["conversation_short_id"] = None
    values["parsed_content_json"] = json.dumps(parsed, ensure_ascii=False)
    values["raw_body"] = json.dumps(payload, ensure_ascii=False)
    claim_webhook_event(db, values=values)
    db.commit()

    result = list_conversation_messages(
        db,
        conversation_key=conversation_key,
        account_open_id=f"{namespace}_account",
        merchant_id=namespace,
    )
    assert len(result["items"]) == 1


def test_j10_decision_risk_filter_casts_jsonb_to_text(pg_case):
    db, namespace, _ = pg_case
    decision = AiReplyDecisionLog(
        merchant_id=namespace,
        conversation_id=f"{namespace}_conversation",
        manual_required=1,
        risk_flags_json='["jsonb_risk"]',
    )
    db.add(decision)
    db.flush()
    db.add(
        DouyinPrivateMessageSend(
            main_account_id=1,
            conversation_short_id=f"{namespace}_conversation",
            server_message_id=f"{namespace}_server_message",
            from_user_id=f"{namespace}_account",
            to_user_id=f"{namespace}_customer",
            content="测试",
            status="sent",
            send_source="ai_auto",
            decision_log_id=decision.id,
        )
    )
    db.commit()

    result = list_ai_reply_decision_logs(
        db,
        AiReplyDecisionLogQuery(merchant_id=namespace, risk_flag="jsonb_risk"),
    )
    assert result["total"] == 1
```

- [ ] **Step 2: 运行筛选测试并确认 PostgreSQL 失败**

运行：

```powershell
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q -k "filter"
```

预期：失败，表现为模式字符串被 JSON 绑定器拒绝或 PostgreSQL JSONB 不支持直接 `LIKE`；不得通过跳过测试规避。

- [ ] **Step 3: 显式把 JSONB 列转换为 TEXT**

按以下方式修改导入和表达式：

```python
# webhook_event_service.py
from sqlalchemy import Text, cast, or_
cast(DouyinWebhookEvent.raw_body, Text).like(like)

# douyin_merchant_isolation.py
from sqlalchemy import Text, cast, or_
cast(DouyinWebhookEvent.raw_body, Text).like(f"%{customer_open_id}%")

# douyin_workbench_conversation_service.py
from sqlalchemy import Text, and_, cast, desc, or_, select, update
cast(DouyinWebhookEvent.raw_body, Text).like(f"%{conversation_key}%")

# ai_reply_decision_log_query_service.py
from sqlalchemy import Text, cast, func, or_
cast(AiReplyDecisionLog.risk_flags_json, Text).like(
    f'%"{escaped}"%', escape="\\"
)
```

替换前三个文件范围内全部 `DouyinWebhookEvent.raw_body.like(...)`，以及决策日志文件内唯一的 `risk_flags_json.like(...)`。不得修改 `DouyinLead.raw_data.like(...)`，该字段属于第二批。

- [ ] **Step 4: 运行真实 PostgreSQL 和 SQLite 查询回归**

运行：

```powershell
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q -rs
python -m pytest tests/test_webhook_events.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_conversation_service.py tests/test_ai_reply_decision_logs_api.py -q
```

预期：0 failed；真实 PostgreSQL 0 skipped；SQLite 查询结果不变。

- [ ] **Step 5: 提交文本筛选返修**

运行：

```powershell
git commit --only -m "修复：兼容JSONB字段文本筛选" -- app/services/webhook_event_service.py app/services/douyin_merchant_isolation.py app/services/douyin_workbench_conversation_service.py app/services/ai_reply_decision_log_query_service.py tests/test_9000_postgres_jsonb_orm_parity.py
```

### Task 5: 补齐发送流水、决策日志和失败边界的真实 PostgreSQL 证据

**Files:**
- Modify: `tests/test_9000_postgres_jsonb_orm_parity.py`

- [ ] **Step 1: 加入真实写入路径和异常合同测试**

把以下导入合并到测试文件顶部：

```python
from datetime import datetime
from unittest.mock import patch

from sqlalchemy.exc import StatementError

from app.auth.context import RequestContext
from app.services.ai_reply_decision_log_service import record_ai_reply_decision
from app.services.douyin_private_message_send_service import _send_private_message_with_context
```

加入以下测试：

```python
def test_j9_send_service_writes_native_jsonb_without_real_network(pg_case, pg_engine, monkeypatch):
    db, namespace, _ = pg_case
    _seed_account(db, namespace)
    monkeypatch.setattr(
        "app.services.douyin_private_message_send_service.config.DY_MAIN_ACCOUNT_ID",
        1,
    )
    send_context = {
        "conversation_short_id": f"{namespace}_send_conversation",
        "conversation_id": f"{namespace}_send_conversation",
        "server_message_id": f"{namespace}_incoming_message",
        "msg_id": f"{namespace}_incoming_message",
        "account_open_id": f"{namespace}_account",
        "customer_open_id": f"{namespace}_customer",
        "message_create_time": datetime.now(),
        "scene": "im_receive_msg",
    }
    fake_result = {
        "payload": {"code": 0, "data": {"msg_id": f"{namespace}_upstream"}}
    }

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value=fake_result,
    ) as fake_call:
        result = _send_private_message_with_context(
            db,
            content="JSONB 测试回复",
            send_context=send_context,
            manual_confirmed=True,
            auto_send=False,
            send_source="manual",
            operator_id="jsonb_parity_test",
        )

    assert fake_call.call_count == 1
    record = db.get(DouyinPrivateMessageSend, result["record_id"])
    assert json.loads(record.request_body_json)["content"] == "JSONB 测试回复"
    assert json.loads(record.response_body_json)["code"] == 0

    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT jsonb_typeof(request_body_json), jsonb_typeof(response_body_json) "
                "FROM douyin_private_message_sends WHERE id = :record_id"
            ),
            {"record_id": record.id},
        ).one()
    assert tuple(row) == ("object", "object")


def test_j10_decision_service_preserves_six_string_json_fields(pg_case, pg_engine):
    db, namespace, _ = pg_case
    log_id = record_ai_reply_decision(
        db,
        context=RequestContext(user_id="jsonb-test", merchant_id=namespace),
        conversation_id=f"{namespace}_decision_conversation",
        account_open_id=f"{namespace}_account",
        latest_message="测试消息",
        agent_id="jsonb-agent",
        agent_name="JSONB 智能体",
        allowed_category_keys=["base"],
        upstream_raw_result={"reply_text": "回复", "source": "test"},
        final_result={
            "reply_text": "回复",
            "manual_required": True,
            "risk_flags": ["jsonb_risk"],
            "tags": ["jsonb_tag"],
            "rag_sources": [{"id": "source-1"}],
            "source_chunks": [{"id": "chunk-1"}],
        },
        upstream_auto_send=False,
    )
    assert log_id is not None

    row = db.get(AiReplyDecisionLog, log_id)
    assert json.loads(row.risk_flags_json) == ["jsonb_risk"]
    assert json.loads(row.tags_json) == ["jsonb_tag"]
    assert json.loads(row.rag_sources_json) == [{"id": "source-1"}]
    assert json.loads(row.source_chunks_json) == [{"id": "chunk-1"}]
    assert json.loads(row.allowed_category_keys_json) == ["base"]
    assert json.loads(row.raw_response_json)["source"] == "test"

    with pg_engine.connect() as conn:
        types = conn.execute(
            text(
                "SELECT jsonb_typeof(risk_flags_json), jsonb_typeof(tags_json), "
                "jsonb_typeof(rag_sources_json), jsonb_typeof(source_chunks_json), "
                "jsonb_typeof(allowed_category_keys_json), jsonb_typeof(raw_response_json) "
                "FROM ai_reply_decision_logs WHERE id = :log_id"
            ),
            {"log_id": log_id},
        ).one()
    assert tuple(types) == ("array", "array", "array", "array", "array", "object")


def test_j3_postgres_invalid_json_fails_and_none_stays_sql_null(pg_case, pg_engine):
    db, namespace, _ = pg_case
    invalid = DouyinPrivateMessageSend(
        main_account_id=1,
        conversation_short_id=f"{namespace}_invalid",
        server_message_id=f"{namespace}_invalid_message",
        from_user_id=f"{namespace}_account",
        to_user_id=f"{namespace}_customer",
        content="测试",
        request_body_json="{bad",
    )
    db.add(invalid)
    with pytest.raises(StatementError) as exc_info:
        db.commit()
    assert isinstance(exc_info.value.orig, json.JSONDecodeError)
    db.rollback()

    valid = DouyinPrivateMessageSend(
        main_account_id=1,
        conversation_short_id=f"{namespace}_null",
        server_message_id=f"{namespace}_null_message",
        from_user_id=f"{namespace}_account",
        to_user_id=f"{namespace}_customer",
        content="测试",
        request_body_json=None,
        response_body_json=None,
    )
    db.add(valid)
    db.commit()

    with pg_engine.connect() as conn:
        values = conn.execute(
            text(
                "SELECT request_body_json IS NULL, response_body_json IS NULL "
                "FROM douyin_private_message_sends WHERE id = :record_id"
            ),
            {"record_id": valid.id},
        ).one()
    assert tuple(values) == (True, True)
```

被替换的 `call_douyin_openapi` 只是本地替身；不得发生网络请求或真实消息发送。

- [ ] **Step 2: 运行完整 PostgreSQL 专项**

运行：

```powershell
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q -rs
```

预期：0 failed、0 skipped；J1-J11、J13-J14 已由本文件直接覆盖。

- [ ] **Step 3: 编译新测试和全部修改模块**

运行：

```powershell
python -m py_compile app/models.py app/services/douyin_webhook_idempotency_service.py app/services/webhook_event_service.py app/services/douyin_merchant_isolation.py app/services/douyin_workbench_conversation_service.py app/services/ai_reply_decision_log_query_service.py tests/test_9000_postgres_jsonb_orm_parity.py
```

预期：无输出，退出码 0。

- [ ] **Step 4: 提交真实 PostgreSQL 行为测试**

运行：

```powershell
git commit --only -m "测试：补齐PostgreSQL JSONB一致性验证" -- tests/test_9000_postgres_jsonb_orm_parity.py
```

### Task 6: 完整门禁、基线对照与候选冻结

**Files:**
- Verify only; do not modify files unless a failing Candidate-owned test proves a defect inside the allowed range.

- [ ] **Step 1: 运行 JSONB 专项和 20 路十轮稳定性证据**

运行：

```powershell
python -m pytest tests/test_9000_postgres_jsonb_orm_parity.py -q -rs
```

预期：0 failed、0 skipped；并发测试内部完成 20 路 × 10 轮，每轮一个胜出，无超时或数据库锁错误。

- [ ] **Step 2: 运行 webhook 与工作台相邻回归**

运行：

```powershell
python -m pytest tests/test_douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py tests/test_webhook_events.py tests/test_douyin_accounts_router.py tests/test_douyin_workbench_conversation_service.py tests/test_douyin_workbench_conversations.py -q
```

预期：0 Candidate 新增失败。

- [ ] **Step 3: 运行发送与决策日志相邻回归**

运行：

```powershell
python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_ai_reply_decision_logs_api.py tests/test_douyin_ai_cs_proxy.py tests/test_forbidden_word_send_integration.py -q
```

预期：0 Candidate 新增失败；所有真实上游调用均由测试替身阻断。

- [ ] **Step 4: 运行 outbox 与 PostgreSQL 相邻回归**

运行：

```powershell
python -m pytest tests/test_9000_postgres_ai_auto_reply_outbox_schema.py tests/test_ai_auto_reply_outbox_restart_recovery.py -q
python -m pytest tests/test_ai_auto_reply_outbox_postgres_mvcc.py -q -rs
```

预期：SQLite 重启恢复无回归；真实 PostgreSQL MVCC 0 failed、0 skipped。

- [ ] **Step 5: 运行既有已知基线所在回归**

运行：

```powershell
python -m pytest tests/test_ai_auto_reply_outbox_service.py tests/test_ai_auto_reply_send_service.py tests/test_ai_auto_reply_dry_run.py -q
```

预期：Candidate 0 个新增失败。若 `test_active_binding_calls_9100_with_history_and_records_decision_log` 仍失败，必须在 `1042a07` 的隔离快照中用完全相同命令复现，比较测试节点、异常类型、行号和正文后才能判定为范围外基线。

- [ ] **Step 6: 核验安全、差异与线性**

运行：

```powershell
git diff --check 1042a07..HEAD
git diff --name-status 1042a07..HEAD
git log --format="%H %P %s" 1042a07..HEAD
git status --short
rg -n "create_all|已上线|已部署|生产验证通过|全仓测试全绿|全部测试通过" tests/test_9000_postgres_jsonb_orm_parity.py app/models.py app/services/douyin_webhook_idempotency_service.py app/services/webhook_event_service.py app/services/douyin_merchant_isolation.py app/services/douyin_workbench_conversation_service.py app/services/ai_reply_decision_log_query_service.py
```

预期：

- `git diff --check` 无输出。
- `1042a07..HEAD` 仅包含 8 个允许文件。
- 提交全部单父线性。
- 工作区仅四份治理计划暂存。
- 新 PostgreSQL 测试没有 `create_all`。
- 没有上线、部署、生产验证或全仓全绿等越权表述。

- [ ] **Step 7: 文档影响检查**

本执行候选不得修改活动文档，只回报：

```text
本轮业务候选通过后将使 PostgreSQL JSONB / ORM 当前事实发生变化；
05_PROJECT_CONTEXT、POSTGRESQL_MIGRATION_NOTES、12_TEST_PLAN_AUTO_WECHAT
须在独立测试和推送完成后另开文档闭环原位更新。
```

- [ ] **Step 8: 回传冻结候选**

严格按以下结构回传证据：

```text
CANDIDATE_READY
Task-ID: P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1
Plan-Revision: R1
Base-Commit: 1042a07...
Candidate-Commit: <完整哈希>
提交链: 4 个单父提交
name-status: 仅 8 个允许文件
J1-J16: 逐项结果
PostgreSQL 专项: passed / failed / skipped
20 路竞争: 10/10 轮结果
SQLite 与相邻回归: 结果及 Base/Candidate 基线对照
安全证据: 无真实外部调用、无生产连接、无 create_all、残留 0
未执行项: 未推送、未部署、未生产迁移、未真实发送
```

执行窗口不得推送、部署、发布、修改生产环境，也不得自行签发独立测试批准。
