# COMPUTE-OPT-01 真实 Token 计量实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将所有真实聊天模型调用从“字符数计费”改为“优先使用供应商真实 Token、缺失时才估算”，并为抖音首轮与每次重试分别保存可审计的调用阶段。

**架构：** 9100 继续负责解析模型响应中的 `usage`，通过现有内部接口把单次调用的计量结果上报给 9000；9000 继续作为算力账户和流水真源，统一校验、应用上浮比例并原子入账。保留 `actual_tokens` 和旧请求兼容，新字段只解释计量来源和单次调用明细，不改变自动回复、安全门禁或余额不足策略。

**技术栈：** Python 3、FastAPI、Pydantic、SQLAlchemy、PostgreSQL/Alembic、SQLite 迁移脚本、pytest。

---

## 0. 阶段边界与完成门禁

### 0.1 本阶段允许范围

- 真实聊天模型用量解析与缺失用量估算。
- PostgreSQL `0014`、SQLite `0033` 及 SQLite 回滚脚本。
- 9000、9205 内部算力上报合同和流水字段。
- 抖音自动回复首轮、已知客户信息纠正、手机号目标纠正的独立计费阶段。
- 日报摘要、回访判定、知识问答、AI 剪辑规划的真实 Token 计量。
- 现有 embedding 字符计量继续保留，但明确标记为 `estimated_tokens`。

### 0.2 本阶段禁止事项

- 不改商户算力流水页面。
- 不接管理员算力配置导航和权限。
- 不压缩提示词、不缩短历史窗口、不合并两类抖音重试。
- 不用固定模板绕过真实模型调用。
- 不改自动发送、人工接管、违禁词、限频、幂等和失败回写。
- 不连接生产 PostgreSQL、生产 SQLite、生产 Milvus，不执行生产迁移。
- 不清理或提交当前无关工作区改动：`app/phase12_test_launcher.py`、一期 PRD、`docs/待确认事项.md` 及执行期间新增的其他并发改动。

### 0.3 固定数据合同

```python
USAGE_MEASUREMENT_METHODS = {
    "provider_tokens",
    "estimated_tokens",
    "legacy_characters",
}

LLM_CALL_STAGES = {
    "primary",
    "retry_known_customer",
    "retry_phone_goal",
    "retry_combined",
}
```

`compute_transactions` 新增五个可空字段：

```text
usage_measurement_method VARCHAR(32)
prompt_tokens BIGINT
completion_tokens BIGINT
cached_tokens BIGINT
llm_call_stage VARCHAR(32)
```

- `actual_tokens` 继续表示应用上浮前的基础用量。
- 供应商返回有效总量时，`actual_tokens=usage.total_tokens`。
- 缺总量但输入和输出 Token 都有效时，`actual_tokens=prompt_tokens+completion_tokens`。
- 供应商没有有效用量时才估算，`usage_measurement_method=estimated_tokens`。
- 旧调用只传 `tokens` 时，按 `legacy_characters` 入账，不能拒绝。
- 历史 `source IN ('llm', 'embedding')` 的消费流水只回填 `legacy_characters`，不得伪造输入、输出、缓存或调用阶段。
- 每次成功模型调用独立上报；上报失败仍不得影响回复主链路。

### 0.4 基线命令

- [x] 记录起点和脏工作区，不修改任何文件：

```powershell
git rev-parse --short HEAD
git status --short
git merge-base --is-ancestor 2ae0930 HEAD
if ($LASTEXITCODE -ne 0) { throw "HEAD 未包含已确认设计提交 2ae0930" }
```

- [x] 运行阶段基线：

```powershell
python -m pytest tests/test_compute_usage_client.py tests/test_compute_service.py tests/test_compute_app.py tests/test_compute_client.py tests/test_xg_douyin_ai_cs_llm.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_phase12_ai_edit_planner.py -q
```

预期：全部通过；若失败，先用当前 HEAD 复现并记录为既有问题，不得在 Task 0 顺手修复。

---

## Task 1：真实 Token 解析与估算纯函数

**文件：**

- Modify: `apps/xg_douyin_ai_cs/services/compute_usage_client.py`
- Modify: `tests/test_compute_usage_client.py`
- Modify: `tests/test_phase10_compute_no_network.py`

- [x] **Step 1：先写真实用量优先级红灯测试**

在 `tests/test_compute_usage_client.py` 增加：

```python
from apps.xg_douyin_ai_cs.services.compute_usage_client import measure_chat_usage


def test_measure_chat_usage_prefers_provider_total_tokens():
    result = {
        "reply_text": "您好",
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 3,
            "total_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 7},
        },
    }
    usage = measure_chat_usage([{"role": "user", "content": "你好"}], result)
    assert usage.tokens == 20
    assert usage.measurement_method == "provider_tokens"
    assert usage.prompt_tokens == 11
    assert usage.completion_tokens == 3
    assert usage.cached_tokens == 7


def test_measure_chat_usage_sums_input_and_output_aliases_without_total():
    result = {
        "reply_text": "ok",
        "usage": {"input_tokens": 9, "output_tokens": 4},
    }
    usage = measure_chat_usage([{"role": "user", "content": "test"}], result)
    assert usage.tokens == 13
    assert usage.measurement_method == "provider_tokens"
    assert usage.prompt_tokens == 9
    assert usage.completion_tokens == 4


def test_measure_chat_usage_falls_back_to_estimate_for_invalid_usage():
    result = {"reply_text": "回复", "usage": {"total_tokens": "unknown"}}
    usage = measure_chat_usage([{"role": "user", "content": "你好abcde"}], result)
    assert usage.tokens > 0
    assert usage.measurement_method == "estimated_tokens"
    assert usage.prompt_tokens is None
    assert usage.completion_tokens is None
    assert usage.cached_tokens is None


def test_measure_chat_usage_rejects_bool_and_negative_counts():
    result = {
        "reply_text": "ok",
        "usage": {"total_tokens": True, "prompt_tokens": -1, "completion_tokens": 2},
    }
    assert measure_chat_usage([], result).measurement_method == "estimated_tokens"
```

- [x] **Step 2：运行红灯**

```powershell
python -m pytest tests/test_compute_usage_client.py -q
```

预期：因 `measure_chat_usage` 尚不存在而失败。

- [x] **Step 3：实现最小纯函数**

在 `compute_usage_client.py` 中复用现有 `count_chat_characters`，新增：

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatUsageMeasurement:
    tokens: int
    measurement_method: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None


def _nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _estimate_text_tokens(text: str) -> int:
    total = 0
    ascii_run = 0
    for char in text:
        if ord(char) < 128:
            ascii_run += 1
            continue
        total += (ascii_run + 3) // 4
        ascii_run = 0
        total += 1
    return max(1, total + (ascii_run + 3) // 4)


def measure_chat_usage(messages: list[dict], result: dict) -> ChatUsageMeasurement:
    usage = result.get("usage") if isinstance(result, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    prompt = _nonnegative_int(usage.get("prompt_tokens"))
    if prompt is None:
        prompt = _nonnegative_int(usage.get("input_tokens"))
    completion = _nonnegative_int(usage.get("completion_tokens"))
    if completion is None:
        completion = _nonnegative_int(usage.get("output_tokens"))
    total = _nonnegative_int(usage.get("total_tokens"))
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached = _nonnegative_int(details.get("cached_tokens")) if isinstance(details, dict) else None
    if total and total > 0:
        return ChatUsageMeasurement(total, "provider_tokens", prompt, completion, cached)
    if prompt is not None and completion is not None and prompt + completion > 0:
        return ChatUsageMeasurement(prompt + completion, "provider_tokens", prompt, completion, cached)
    request_text = "".join(
        item["content"]
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    )
    reply_text = str(result.get("reply_text") or "") if isinstance(result, dict) else ""
    return ChatUsageMeasurement(
        _estimate_text_tokens(request_text + reply_text),
        "estimated_tokens",
    )
```

实现时不得把 `usage` 原文、提示词或回复原文写入日志。

- [x] **Step 4：补无网络哨兵并跑绿灯**

在 `tests/test_phase10_compute_no_network.py` 断言 `measure_chat_usage()` 在网络哨兵下可运行，然后执行：

```powershell
python -m pytest tests/test_compute_usage_client.py tests/test_phase10_compute_no_network.py -q
```

预期：通过，真实网络调用数为 0。

- [x] **Step 5：选择性提交**

```powershell
git add -- apps/xg_douyin_ai_cs/services/compute_usage_client.py tests/test_compute_usage_client.py tests/test_phase10_compute_no_network.py
git diff --cached --check
git commit -m "新增真实Token用量解析"
```

---

## Task 2：扩展 PostgreSQL、SQLite 和 ORM 流水合同

**文件：**

- Create: `migrations/postgres/auto_wechat/versions/0014_compute_usage_measurement.py`
- Create: `migrations/versions/0033_compute_usage_measurement.sql`
- Create: `migrations/downgrades/0033_compute_usage_measurement.sql`
- Modify: `app/models.py`
- Create: `tests/test_compute_usage_measurement_postgres_contract.py`
- Create: `tests/test_compute_usage_measurement_sqlite_migration.py`
- Modify: `tests/test_phase10_compute_schema.py`

- [x] **Step 1：写迁移与 ORM 红灯**

测试至少固定以下断言：

```python
EXPECTED_COLUMNS = {
    "usage_measurement_method",
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "llm_call_stage",
}


def test_compute_transaction_declares_usage_measurement_columns():
    columns = ComputeTransaction.__table__.columns
    assert EXPECTED_COLUMNS <= set(columns.keys())
    assert isinstance(columns["prompt_tokens"].type, BigInteger)
    assert isinstance(columns["completion_tokens"].type, BigInteger)
    assert isinstance(columns["cached_tokens"].type, BigInteger)
```

PostgreSQL 静态合同同时断言：

```python
assert 'revision = "0014_compute_usage_measurement"' in content
assert 'down_revision = "0013_ai_edit_local_mvp"' in content
for name in EXPECTED_COLUMNS:
    assert name in content
assert "legacy_characters" in upgrade
assert "source IN ('llm', 'embedding')" in upgrade
assert upgrade.index("add_column") < upgrade.index("UPDATE compute_transactions")
assert downgrade.index("drop_constraint") < downgrade.index("drop_column")
```

SQLite 临时库测试必须验证：

- 从 `0032` 升级到 `0033` 后五列存在。
- 历史 `llm`、`embedding` 消费回填 `legacy_characters`。
- 充值、套餐流水五列仍为空。
- 输入、输出、缓存 Token 拒绝负数。
- 未知计量方式和未知调用阶段被 CHECK 拒绝。
- 回滚后恢复 `0032` 列集，所有旧列数据不丢。
- `0033` 已登记时重复执行由 runner 跳过；存在 `0034+` 时禁止越序回滚。

- [x] **Step 2：运行红灯**

```powershell
python -m pytest tests/test_phase10_compute_schema.py tests/test_compute_usage_measurement_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py -q
```

预期：因 `0014`、`0033` 和 ORM 新字段不存在而失败。

- [x] **Step 3：实现 ORM 和 PostgreSQL 0014**

`ComputeTransaction` 新增：

```python
usage_measurement_method = Column(String(32), nullable=True, comment="用量计量方式")
prompt_tokens = Column(BigInteger, nullable=True, comment="供应商输入 Token")
completion_tokens = Column(BigInteger, nullable=True, comment="供应商输出 Token")
cached_tokens = Column(BigInteger, nullable=True, comment="供应商缓存命中 Token")
llm_call_stage = Column(String(32), nullable=True, comment="模型调用阶段")
```

新增数据库约束：三项 Token 为空或非负；计量方式和调用阶段为空或属于冻结枚举。`0014` 只 ALTER `compute_transactions`，回填使用参数化 `op.execute(sa.text(...))` 或固定无用户输入 SQL，不建新表、不改余额与计费列。

- [x] **Step 4：实现 SQLite 0033 升级与回滚**

按 `0031` 的安全重建模式执行：`0032` 未改变算力流水表，因此先精确校验当前 15 列、备份、重建 20 列、复制、双向数据守卫、重建索引。回滚反向恢复 15 列，并删除 `schema_migrations` 中 `0033`；不得修改 `0031`、`0032` 历史迁移。

- [x] **Step 5：运行迁移绿灯**

```powershell
python -m pytest tests/test_phase10_compute_schema.py tests/test_compute_usage_measurement_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py tests/test_phase10_compute_postgres_contract.py -q
```

预期：全部通过。

- [x] **Step 6：检查点 A，暂停复核数据合同**

回传：五列类型、CHECK、历史回填范围、SQLite 升降级数据保持、PostgreSQL revision 链。未通过前不得进入 Task 3。

- [x] **Step 7：选择性提交**

```powershell
git add -- app/models.py migrations/postgres/auto_wechat/versions/0014_compute_usage_measurement.py migrations/versions/0033_compute_usage_measurement.sql migrations/downgrades/0033_compute_usage_measurement.sql tests/test_phase10_compute_schema.py tests/test_compute_usage_measurement_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py
git diff --cached --check
git commit -m "扩展算力用量计量流水合同"
```

---

## Task 3：扩展内部上报和原子入账合同

**文件：**

- Modify: `app/schemas.py`
- Modify: `apps/compute/services.py`
- Modify: `app/routers/compute.py`
- Modify: `apps/compute/routers.py`
- Modify: `packages/clients/compute_client.py`
- Modify: `apps/xg_douyin_ai_cs/services/compute_usage_client.py`
- Modify: `tests/test_compute_service.py`
- Modify: `tests/test_compute_app.py`
- Modify: `tests/test_compute_client.py`
- Modify: `tests/test_compute_usage_client.py`

- [x] **Step 1：写请求兼容和入账红灯**

新增测试：

```python
def test_compute_usage_request_accepts_provider_measurement_details():
    payload = ComputeUsageRequest(
        merchant_id="m1",
        tokens=18,
        capability_key="douyin-cs",
        model="model-a",
        usage_measurement_method="provider_tokens",
        prompt_tokens=12,
        completion_tokens=6,
        cached_tokens=4,
        llm_call_stage="primary",
    )
    assert payload.prompt_tokens == 12


def test_compute_usage_request_keeps_legacy_client_compatible():
    payload = ComputeUsageRequest(
        merchant_id="m1", tokens=18, capability_key="douyin-cs", model="model-a"
    )
    assert payload.usage_measurement_method is None
```

`test_record_usage_snapshots_provider_measurement` 断言流水五个新字段；`test_record_usage_defaults_old_payload_to_legacy_characters` 断言旧调用落账为 `legacy_characters`；非法枚举、负明细、明细大于 PostgreSQL BIGINT 均在写流水前拒绝。

- [x] **Step 2：运行红灯**

```powershell
python -m pytest tests/test_compute_service.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_usage_client.py -q
```

- [x] **Step 3：扩展 DTO 和服务签名**

`ComputeUsageRequest` 增加可选字段：

```python
usage_measurement_method: Optional[Literal[
    "provider_tokens", "estimated_tokens", "legacy_characters"
]] = None
prompt_tokens: Optional[int] = Field(None, ge=0)
completion_tokens: Optional[int] = Field(None, ge=0)
cached_tokens: Optional[int] = Field(None, ge=0)
llm_call_stage: Optional[Literal[
    "primary", "retry_known_customer", "retry_phone_goal", "retry_combined"
]] = None
```

三项 Token 明细同时设置 `le=9_223_372_036_854_775_807`，与 PostgreSQL `BIGINT` 上限一致。服务层对绕过 Pydantic 的内部直接调用执行相同范围校验。

`record_usage()` 增加同名可选关键字参数，并使用：

```python
measurement_method = usage_measurement_method or "legacy_characters"
```

给现有 `_write_transaction()` 增加五个默认 `None` 的关键字参数，并在 `ComputeTransaction(...)` 中逐项赋值；`record_usage()` 将校验后的五项字段传入。充值和套餐调用点无需修改，默认保持为空。账户创建、流水写入和余额变更仍只有一次顶层 `commit`。

- [x] **Step 4：两个路由和两个客户端透传**

`app/routers/compute.py` 与 `apps/compute/routers.py` 必须逐字段传入 `record_usage()`；`packages/clients/compute_client.py` 与 9100 `ComputeUsageClient.report_usage()` 增加可选参数并放入请求体。9100 客户端日志只能记录计量方式、基础用量和调用阶段，不记录消息原文。

- [x] **Step 5：运行绿灯**

```powershell
python -m pytest tests/test_compute_service.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_usage_client.py tests/test_compute_router.py -q
```

预期：新旧请求均通过；旧请求入账标记 `legacy_characters`。

- [x] **Step 6：选择性提交**

```powershell
git add -- app/schemas.py apps/compute/services.py app/routers/compute.py apps/compute/routers.py packages/clients/compute_client.py apps/xg_douyin_ai_cs/services/compute_usage_client.py tests/test_compute_service.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_usage_client.py
git diff --cached --check
git commit -m "接通真实Token用量入账合同"
```

---

## Task 4：标记抖音自动回复首轮与重试用量

**文件：**

- Modify: `apps/xg_douyin_ai_cs/services/reply_decision_service.py`
- Modify: `tests/test_xg_douyin_ai_cs_llm.py`

- [x] **Step 1：写三种调用阶段红灯**

在以下三个现有测试中复用原请求和回复，不另造接口级脚手架：

```text
test_reply_suggestion_returns_structured_llm_decision
test_reply_suggestion_retries_llm_when_reply_asks_known_budget
test_bound_agent_phone_goal_retries_when_llm_omits_phone
```

每个测试先安装同一个上报替身：

```python
reports = []

def fake_report_usage(self, **kwargs):
    reports.append(kwargs)
    return True

monkeypatch.setattr(
    "apps.xg_douyin_ai_cs.services.reply_decision_service.ComputeUsageClient.report_usage",
    fake_report_usage,
)
```

首轮测试的假模型响应增加：

```python
"usage": {"prompt_tokens": 17, "completion_tokens": 4, "total_tokens": 21},
```

并增加断言：

```python
assert len(reports) == 1
assert reports[0]["tokens"] == 21
assert reports[0]["usage_measurement_method"] == "provider_tokens"
assert reports[0]["prompt_tokens"] == 17
assert reports[0]["completion_tokens"] == 4
assert reports[0]["llm_call_stage"] == "primary"
```

已知客户信息纠正测试按 `calls["count"]` 给两次响应分别增加总量 20 和 8，断言：

```python
assert [item["tokens"] for item in reports] == [20, 8]
assert [item["llm_call_stage"] for item in reports] == [
    "primary",
    "retry_known_customer",
]
```

手机号目标纠正测试按调用次数分别增加总量 19 和 7，断言：

```python
assert [item["tokens"] for item in reports] == [19, 7]
assert [item["llm_call_stage"] for item in reports] == [
    "primary",
    "retry_phone_goal",
]
```

- [x] **Step 2：运行红灯**

```powershell
python -m pytest tests/test_xg_douyin_ai_cs_llm.py -k "usage or retry" -q
```

- [x] **Step 3：最小修改统一上报函数**

`_report_llm_usage()` 增加必传 `llm_call_stage`，内部改为：

```python
usage = measure_chat_usage(messages, result)
ComputeUsageClient().report_usage(
    merchant_id=request.merchant_id,
    tokens=usage.tokens,
    capability_key=capability_key,
    source="llm",
    model=str(result.get("model") or ""),
    agent_id=agent.get("agent_id"),
    conversation_id=conversation_id,
    remark="douyin_ai_reply",
    usage_measurement_method=usage.measurement_method,
    prompt_tokens=usage.prompt_tokens,
    completion_tokens=usage.completion_tokens,
    cached_tokens=usage.cached_tokens,
    llm_call_stage=llm_call_stage,
)
```

三个调用点分别固定传：

```text
首轮：primary
已知客户信息纠正：retry_known_customer
手机号目标纠正：retry_phone_goal
```

不得合并重试、不得改变 `decision`、`warnings`、`manual_required` 或 `auto_send`。

- [x] **Step 4：运行绿灯和相邻回归**

```powershell
python -m pytest tests/test_xg_douyin_ai_cs_llm.py tests/test_douyin_autoreply_service.py tests/test_douyin_autoreply_runner.py tests/test_douyin_autoreply_settings_service.py -q
```

预期：回复决策与发送门禁测试无变化；每次成功模型调用对应一条上报。

- [x] **Step 5：选择性提交**

```powershell
git add -- apps/xg_douyin_ai_cs/services/reply_decision_service.py tests/test_xg_douyin_ai_cs_llm.py
git diff --cached --check
git commit -m "记录抖音回复每次模型调用用量"
```

---

## Task 5：统一其他模型调用方并标记 embedding 估算

**文件：**

- Modify: `apps/xg_douyin_ai_cs/services/daily_report_summary_service.py`
- Modify: `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py`
- Modify: `apps/xg_douyin_ai_cs/services/knowledge_training_service.py`
- Modify: `apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py`
- Modify: `apps/xg_douyin_ai_cs/rag/repository.py`
- Modify: `tests/test_xg_douyin_ai_cs_daily_report_summary.py`
- Modify: `tests/test_phase9_return_visit_judge.py`
- Modify: `tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py`
- Modify: `tests/test_phase12_ai_edit_planner.py`
- Modify: `tests/test_compute_usage_client.py`

- [x] **Step 1：写各调用方真实用量红灯**

在现有成功用例中给假模型结果统一增加：

```python
"usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
```

使用各文件已有的 `report_usage` 替身收集关键字参数，并在以下用例中增加完全相同的计量断言：

```text
tests/test_xg_douyin_ai_cs_daily_report_summary.py::test_compute_usage_reported_on_success
tests/test_phase9_return_visit_judge.py::test_llm_single_scene_hit
tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py::test_ask_skips_rag_when_base_has_no_active_chunks
tests/test_phase12_ai_edit_planner.py::test_compute_reported_on_success
```

回访测试给 `_StubLLM` 增加可选 `usage` 构造参数，并只在 `test_llm_single_scene_hit` 安装 `return_visit_judge_service.ComputeUsageClient.report_usage` 替身；知识问答测试让 `_patch_chat()` 接受可选 `usage`，并在指定用例安装 `knowledge_training_service.ComputeUsageClient.report_usage` 替身。两处均使用局部 monkeypatch，不移除文件现有的禁用网络环境夹具。

```python
assert report_kwargs["tokens"] == 40
assert report_kwargs["usage_measurement_method"] == "provider_tokens"
assert report_kwargs["prompt_tokens"] == 30
assert report_kwargs["completion_tokens"] == 10
assert report_kwargs["llm_call_stage"] == "primary"
```

将现有 `test_compute_usage_uses_chars_when_provider_total_tokens_zero` 原位改为供应商用量缺失测试，删除“字符数等于计费量”的旧断言，改为：

```python
assert report_kwargs["tokens"] > 0
assert report_kwargs["usage_measurement_method"] == "estimated_tokens"
assert result["llm_used"] is True
```

embedding 现有测试增加：

```python
assert report_kwargs["usage_measurement_method"] == "estimated_tokens"
assert report_kwargs["llm_call_stage"] is None
```

- [x] **Step 2：运行红灯**

```powershell
python -m pytest tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_phase12_ai_edit_planner.py tests/test_compute_usage_client.py -q
```

- [x] **Step 3：聊天调用方统一复用 `measure_chat_usage()`**

四个 `_report_usage()` 删除重复的 `count_chat_characters()`，在各自现有 `report_usage()` 调用中保留原来的商户、能力、模型和备注参数，并增加：

```python
usage = measure_chat_usage(messages, result)
ComputeUsageClient().report_usage(
    merchant_id=merchant_id,
    tokens=usage.tokens,
    usage_measurement_method=usage.measurement_method,
    prompt_tokens=usage.prompt_tokens,
    completion_tokens=usage.completion_tokens,
    cached_tokens=usage.cached_tokens,
    llm_call_stage="primary",
)
```

`return_visit_judge_service.py` 和 `ai_edit_planner_service.py` 的商户参数来自请求对象，分别继续使用 `request.merchant_id`；上述片段中的 `merchant_id` 只代表日报和知识问答现有函数参数，不得改动调用方的数据来源。

不得改变原有能力映射：日报/回访=`wechat-assistant`，知识问答=`knowledge`，AI 剪辑规划=`compute`。

- [x] **Step 4：embedding 显式标记估算**

`rag/repository.py` 保留现有 `count_embedding_characters()`，只给上报增加：

```python
usage_measurement_method="estimated_tokens",
llm_call_stage=None,
```

mock embedding 仍不得扣费；不得引入 tokenizer 依赖。

- [x] **Step 5：运行绿灯**

```powershell
python -m pytest tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_no_network.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_phase12_ai_edit_planner.py tests/test_phase10_compute_no_network.py -q
```

预期：全部通过，真实网络调用数为 0。

- [x] **Step 6：检查点 B，暂停复核调用点完整性**

```powershell
rg -n "\.chat\(|\.embed\(" apps/xg_douyin_ai_cs -g "*.py"
rg -n "count_chat_characters\(" apps/xg_douyin_ai_cs -g "*.py"
```

生产聊天调用点必须全部使用 `measure_chat_usage()`；`count_chat_characters()` 只允许保留兼容测试或历史兼容入口，不得再作为新聊天计费依据。

- [x] **Step 7：选择性提交**

```powershell
git add -- apps/xg_douyin_ai_cs/services/daily_report_summary_service.py apps/xg_douyin_ai_cs/services/return_visit_judge_service.py apps/xg_douyin_ai_cs/services/knowledge_training_service.py apps/xg_douyin_ai_cs/services/ai_edit_planner_service.py apps/xg_douyin_ai_cs/rag/repository.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_phase12_ai_edit_planner.py tests/test_compute_usage_client.py
git diff --cached --check
git commit -m "统一模型调用真实Token计量"
```

---

## Task 6：全量回归、迁移演练与文档原位更新

**文件：**

- Modify: `docs/ai/05_PROJECT_CONTEXT.md`
- Modify: `docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md`
- Modify: `docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md`（只把阶段一状态改为已实施，不追加重复过程）

- [x] **Step 1：运行算力和模型调用专项回归**

```powershell
python -m pytest tests/test_compute_models.py tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_usage_client.py tests/test_phase10_compute_schema.py tests/test_compute_usage_measurement_postgres_contract.py tests/test_compute_usage_measurement_sqlite_migration.py tests/test_phase10_compute_no_network.py tests/test_xg_douyin_ai_cs_llm.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_no_network.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_phase12_ai_edit_planner.py -q
```

- [x] **Step 2：运行完整后端回归（已执行；被无关 Local Agent 并发改动触发的 Windows 栈溢出阻断）**

```powershell
python -m pytest -q
```

预期：全部通过；若仓库已有无关失败，必须用本阶段起点提交复现并给出文件与用例证据，禁止笼统写“历史问题”。

- [x] **Step 3：本地 PostgreSQL 迁移演练（环境未配置，标记 `BLOCKED_ENVIRONMENT`）**

```powershell
alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0014_compute_usage_measurement
alembic -c migrations/postgres/auto_wechat/alembic.ini downgrade 0013_ai_edit_local_mvp
alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade 0014_compute_usage_measurement
```

未配置隔离的本地 PostgreSQL 时明确标记 `BLOCKED_ENVIRONMENT`，静态合同和 SQLite 演练仍必须通过；绝不连接生产库。

- [x] **Step 4：原位更新当前事实**

`05_PROJECT_CONTEXT.md` 必须把“字符计量”原位替换为：聊天优先供应商真实 Token、缺失时估算、旧流水为 `legacy_characters`、每次重试独立入账。`PHASE10_COMPUTE_ACCEPTANCE.md` 的第 1、2、5、7 节含有已过期的“供应商 Token 不参与计费”“实际字符量”结论，必须原位改成历史 Phase 10 验收事实与当前合同的清晰区分，禁止把历史提交描述改写成当时不存在的实现。设计文档只更新阶段一实施状态，不追加过程流水账。

- [x] **Step 5：最终差异和越界检查**

```powershell
git status --short
git diff --check
git diff --stat 2ae0930..HEAD
rg -n "actual_tokens.*字符|供应商.*禁止参与|不再使用 provider" app apps docs/ai -g "*.py" -g "*.md"
```

确认未改前端、导航、权限、提示词、重试次数、自动发送和生产配置。

- [x] **Step 6：选择性提交文档**

```powershell
git add -- docs/ai/05_PROJECT_CONTEXT.md docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md docs/superpowers/specs/2026-07-16-compute-token-optimization-design.md
git diff --cached --check
git commit -m "更新真实Token计量项目事实"
```

只暂存实际发生修改的文档；不得把当前并发 PRD 或待确认事项混入。

---

## 最终验收回传

执行窗口必须回传：

1. 本阶段全部提交哈希与精确文件清单。
2. `usage.total_tokens`、输入加输出、估算三条分支的测试证据。
3. 抖音首轮、已知客户纠正、手机号目标纠正的流水条数和阶段证据。
4. PostgreSQL `0014` 静态合同与可选本地升降级结果。
5. SQLite `0033` 升级、回滚、数据保持结果。
6. 旧请求只传 `tokens` 的兼容证据。
7. 全量测试结果与网络调用数。
8. 工作区隔离结果和未解决风险。
9. 文档影响检查结果。

最终状态只能是：

- `PASS`：专项与全量回归通过，迁移合同通过，无越界修改。
- `CONDITIONAL_PASS`：仅本地 PostgreSQL 实例不可用，其他全部通过并明确 `BLOCKED_ENVIRONMENT`。
- `FAIL`：计量优先级、独立重试计费、迁移数据保持、旧请求兼容或主业务回归任一不满足。
