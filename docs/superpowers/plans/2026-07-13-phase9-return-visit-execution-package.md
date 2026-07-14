# Phase 9 微信到抖音回访逐任务执行包

> **文档状态（2026-07-14 审查）：已执行的追溯执行包，保留原路径供源码和测试引用。** Phase 9 代码与模拟闭环为 `DONE`，阶段总状态为 `DONE_WITH_CONCERNS`，唯一遗留项是 `baota_production_send_not_verified`。未勾选项保留原执行顺序，不得据此重复执行；当前项目事实以 `docs/ai/05_PROJECT_CONTEXT.md` 为准。
>
> **执行窗口必读：** 必须使用 `subagent-driven-development`（推荐）或 `executing-plans`，严格按任务顺序执行；每个步骤使用 `- [ ]` 跟踪，先红灯、再最小实现、再绿灯、再提交、再暂停回传。

**目标：** 在不恢复 Phase 8-B、不启动 Phase 11 一键过审、不做任何宝塔或抖音真实发送测试的前提下，完成“销售微信回复触发 → 9100 严格判定 → 9000 安全门禁 → 抖音回访发送代码路径 → 崩溃恢复 → 超管配置与审计”的代码与全替身自动测试闭环。

**架构：** 9000 从已校验 Local Agent 回写中锚定派单通知后的 `sender=friend` 文本，先持久化既有 `ReturnVisitRun`，再通过统一入口异步处理。9100 独占场景判定、关键词和 LLM 降级语义；9000 独占可信商户上下文、状态机、门禁、限频、冷却和底层发送。三张既有表只做增量迁移，不新建业务表；发送复用 `_send_private_message_with_context`，测试中必须替换 `call_douyin_openapi`，真实网络调用数恒为 0。

**技术栈：** FastAPI、Pydantic、SQLAlchemy、SQLite 迁移 runner、PostgreSQL/Alembic、React 19、TypeScript、pytest、Node 合同脚本。

---

## 0. 冻结输入与总门禁

### 0.1 权威输入

- 冻结设计：`docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md`
- 冻结提交：`b077feb 文档：修正 Phase 9 回访拒答与服务边界`
- 权威总控：`docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md` Phase 9
- 当前既有表：`ReturnVisitPrompt`、`ReturnVisitRun`、`DouyinPrivateMessageSend`
- 当前既有内部鉴权：`require_internal_service_token` + `XgDouyinAiCsClient` + `X-Internal-Service-Token`
- 当前既有底层发送：`app/services/douyin_private_message_send_service.py::_send_private_message_with_context`

设计若与本包冲突，以 `b077feb` 的冻结业务语义为准；执行窗口不得自行改业务口径。唯一文件名勘误：本仓库 SQLite runner 只发现 `migrations/versions/*.sql`，因此升级文件必须是 `0030_return_visit_phase9.sql`，不是设计章节标题中的 `.py`。SQLite 真实回滚放独立、不会被升级 runner 自动发现的 `migrations/downgrades/0030_return_visit_phase9.sql`。

### 0.2 当前阶段状态不得漂移

| 项目 | 执行期间状态 |
|---|---|
| Phase 8-B | `PARTIAL_BLOCKED_DEFERRED`，不恢复 |
| Phase 8-B Task 8 | `NOT_STARTED` |
| Phase 11 一键过审 | `CANCELLED_BY_CUSTOMER`，不恢复 |
| Phase 9 代码与模拟闭环 | 完成 Task 10 后才可记 `DONE` |
| Phase 9 | 最终目标 `DONE_WITH_CONCERNS` |
| 唯一 concern | `baota_production_send_not_verified` |

### 0.3 本阶段真实测试后置

本执行包只允许：临时 SQLite、隔离 `_test` PostgreSQL（若现成可用）、FastAPI `TestClient`、9100 LLM 替身、抖音 OpenAPI 替身、前端静态合同与构建。

本执行包明确禁止：

- 宝塔部署、生产数据库迁移、真实抖音账号或客户数据。
- 调用真实 `/send_msg`、真实 LLM 网络、真实微信发送或 Local Agent 自动化。
- 扫描抖音会话时间线、增加“沉默客户”周期扫描器；沉默场景仍只由销售微信反馈触发。
- 使用真实 token、cookie、secret、客户手机号、微信号或回复原文作为 fixture。
- 为了“验证”而开启 `DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED` 或生产 DB `real_send_enabled`。
- 因宝塔真实验证未做而阻塞代码阶段；该项只保留为唯一 concern。

每个发送相关测试都必须先安装网络哨兵：

```python
def forbid_real_openapi(*args, **kwargs):
    raise AssertionError("自动测试禁止真实抖音 OpenAPI 网络调用")

monkeypatch.setattr(
    "app.services.douyin_private_message_send_service.call_douyin_openapi",
    forbid_real_openapi,
)
```

只有测试明确需要模拟成功或失败时，才把该哨兵替换为受控函数；任何未打桩调用都应立即失败。

### 0.4 脏工作区保护

会话开始前已有修改和未跟踪文件，执行窗口不得清理、回滚、暂存或混入提交：

- `.gitignore`
- `docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md`
- `docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md`
- `docs/待确认事项.md`
- `tests/test_phase8b_local_agent_downloader.py`
- 三份既有未跟踪执行包
- `scripts/generate_phase8_visual_samples.py`

每次提交必须显式 `git add <本任务白名单文件>`，禁止 `git add .`、`git add -A`。

并发窗口在执行期间新增的无关文件一律视为用户所有并排除；只有当它与当前 Task 白名单文件重叠、导致无法安全合并时才暂停询问，不得擅自删除或回滚。

### 0.5 固定合同

```python
PROMPT_KEYS = (
    "retain_contact_conversion",
    "finance_plan_followup",
    "silent_customer_wakeup",
)

RECOVERABLE_STATUSES = {
    "pending_judgement",
    "processing",
    "send_authorized",
}

TERMINAL_STATUSES = {
    "not_needed",
    "confidence_low",
    "prompt_disabled",
    "rate_limited",
    "blocked",
    "sent",
    "send_unknown",
    "failed",
}

RISK_FLAGS = {
    "prompt_injection",
    "sensitive_info",
    "off_topic",
    "duplicate",
    "policy_violation",
    "model_refusal",
}
```

三条迁移回填文案必须逐字一致：

```text
retain_contact_conversion：您好，刚才留存的联系方式似乎无法正常联系。麻烦您重新发送一个常用手机号或微信号，方便我们继续为您服务。
finance_plan_followup：您好，关于您关注的金融方案，我们可以继续为您说明。您更想了解首付、月供还是分期期限？
silent_customer_wakeup：您好，之前的咨询还需要我们继续协助吗？方便时告诉我您目前最关心的问题，我们再为您跟进。
```

### 0.6 每任务固定流程

- [ ] 阅读本任务涉及的现有调用链，使用 `rg` 查全调用方。
- [ ] 只写本任务专项测试并运行，确认因目标能力缺失而失败。
- [ ] 实现最小代码，不顺手重构。
- [ ] 跑专项、关联回归、`git diff --check`。
- [ ] 检查 `git diff --name-only` 只含白名单。
- [ ] 使用本包指定中文提交信息提交。
- [ ] 暂停并回传：提交哈希、文件、红灯、绿灯、关联回归、残留风险。

---

## Task 0：起点确认与基线冻结

**文件：** 无改动、无提交。

- [ ] 确认起点是冻结设计提交或其后代：

```powershell
git rev-parse --short HEAD
git merge-base --is-ancestor b077feb HEAD
if ($LASTEXITCODE -ne 0) { throw "HEAD 不包含冻结设计 b077feb" }
git status --short
```

预期：祖先检查退出码 0；工作区只显示 0.4 所列既有改动。若出现未知业务代码改动，暂停，不自行处理。

- [ ] 跑基线回归：

```powershell
python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_admin_autoreply_rollout_api.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_xiaogao_phase1_context_contract.py -q
```

预期：全部通过；任何失败先用 `git stash --keep-index` 等只读对照确认是否 pre-existing，不修复无关失败。

- [ ] 确认现阶段没有 Phase 9 业务实现：

```powershell
rg -n "process_return_visit_run|decide-and-generate|return_visit_auto" app apps frontend/src
```

预期：不存在完整 Phase 9 链路；既有模型、权限或文档命中可以保留。

**暂停点：** 回传起点、基线测试和脏工作区清单；经审批后进入 Task 1。

---

## Task 1：冻结数据合同红灯

**文件：**

- Create: `tests/test_phase9_return_visit_schema.py`
- Create: `tests/test_phase9_return_visit_postgres_contract.py`

- [ ] 在 `test_phase9_return_visit_schema.py` 固定以下合同：
  - 三个 ORM 类只扩展既有表，不出现第四张 Phase 9 表。
  - `ReturnVisitPrompt.confidence_threshold` 为非空浮点，默认 0.90；`fallback_message` 非空文本。
  - `ReturnVisitRun` 精确增加设计 §4.2 的 16 列；`account_open_id` 为 `VARCHAR(255)`；`idempotency_key` 唯一。
  - `DouyinPrivateMessageSend.return_visit_run_id` 唯一，既有 `auto_reply_run_id` 不变。
  - SQLite `0030_return_visit_phase9.sql` 和显式回滚脚本存在。
  - 从临时 0029 基线执行 0030 后，三表数据多重集一致、三条文案逐字一致、空值为 0、索引与唯一约束存在。
  - 对含第四个未知 `prompt_key` 的基线执行 0030，事务整体回滚且不登记 0030。
  - 重复 apply 0030 整体跳过。
  - 显式执行 downgrade 后精确恢复 0027/0008 原列集，新列全部消失，旧数据不丢，`schema_migrations` 删除 0030 登记；随后可再次 upgrade。

- [ ] 在 `test_phase9_return_visit_postgres_contract.py` 固定：
  - 文件 `migrations/postgres/auto_wechat/versions/0011_return_visit_phase9.py` 存在。
  - `revision="0011_return_visit_phase9"`，`down_revision="0010_daily_report_deliveries"`。
  - 先校验三键 seed 精确存在，再加可空 `fallback_message`，按三键回填，校验零空值，再 `SET NOT NULL`；无占位默认。
  - upgrade 不创建三张既有表，不改既有列类型。
  - downgrade 删除全部 Phase 9 新列和约束，不删除历史表。

- [ ] 运行红灯：

```powershell
python -m pytest tests/test_phase9_return_visit_schema.py tests/test_phase9_return_visit_postgres_contract.py -q
```

预期：因 ORM 新列和 0030/0011 文件不存在而失败；不得接受导入错误、fixture 错误或测试自身语法错误。

- [ ] 提交测试合同：

```powershell
git add tests/test_phase9_return_visit_schema.py tests/test_phase9_return_visit_postgres_contract.py
git diff --cached --check
git commit -m "测试：冻结 Phase 9 回访数据合同"
```

**暂停点：** 回传红灯数量和失败原因；不提前实现 Task 2。

---

## Task 2：ORM 与双数据库迁移

**文件：**

- Modify: `app/models.py`
- Create: `migrations/versions/0030_return_visit_phase9.sql`
- Create: `migrations/downgrades/0030_return_visit_phase9.sql`
- Create: `migrations/postgres/auto_wechat/versions/0011_return_visit_phase9.py`
- Modify: `tests/test_phase9_return_visit_schema.py`
- Modify: `tests/test_phase9_return_visit_postgres_contract.py`

- [ ] 按冻结设计扩展 ORM，核心形态如下：

```python
class ReturnVisitPrompt(Base):
    # 既有列保持不变
    confidence_threshold = Column(Float, nullable=False, default=0.90)
    fallback_message = Column(Text, nullable=False)


class ReturnVisitRun(Base):
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uk_return_visit_runs_idempotency_key"),
        Index(
            "idx_return_visit_runs_cooldown",
            "merchant_id", "account_open_id", "conversation_short_id",
            "customer_open_id", "prompt_key",
        ),
        Index("idx_return_visit_runs_dispatch_notification", "dispatch_notification_id"),
    )
    dispatch_notification_id = Column(Integer)
    trigger_message_fp = Column(String(64))
    idempotency_key = Column(String(128))
    account_open_id = Column(String(255))
    conversation_short_id = Column(String(255))
    customer_open_id = Column(String(255))
    context_server_message_id = Column(String(255))
    confidence = Column(Float)
    model = Column(String(128))
    risk_flags_json = Column(Text)
    gate_results_json = Column(Text)
    last_failure_stage = Column(String(100))
    manual_takeover = Column(Boolean, nullable=False, default=False)
    lease_owner = Column(String(64))
    lease_expires_at = Column(DateTime)
    attempt_count = Column(Integer, nullable=False, default=0)


class DouyinPrivateMessageSend(Base):
    # 既有列保持不变
    return_visit_run_id = Column(Integer, unique=True, index=True)
```

- [ ] 编写 SQLite 0030 安全重建：
  - 只重建三张既有表；正式表名不得被当成新业务表创建。
  - 先校验 prompt key 精确等于三键集合；未知键触发 `_guard` CHECK 失败并回滚。
  - `CASE prompt_key` 只有三个 `WHEN`，没有 `ELSE`。
  - 每张表执行行数、`max(id)`、旧列双向 `GROUP BY ... EXCEPT` 多重集守卫。
  - 0030 登记只由既有 runner 完成；脚本自身不写 `schema_migrations`。

- [ ] 编写 SQLite 显式 downgrade：仅供回滚命令和测试显式执行，不放 `versions` 目录；按迁移前完整结构安全重建三表并做行数、`max(id)`、旧列多重集守卫；同一事务最后删除 `schema_migrations.version_num='0030'`，验证 downgrade 后可再次 upgrade。

- [ ] 编写 PostgreSQL 0011：使用 Alembic `op.add_column`/约束/索引；先校验三键 seed 精确存在，`fallback_message` 再按“可空、回填、零空值检查、设非空”执行；downgrade 逆序删除。

- [ ] 跑专项与迁移 runner 回归：

```powershell
python -m pytest tests/test_phase9_return_visit_schema.py tests/test_phase9_return_visit_postgres_contract.py tests/test_phase8b_delivery_schema.py tests/test_db_migration_runner.py -q
```

预期：全部通过。不得对当前共享 Docker DB 或生产 DB 执行迁移。

- [ ] 提交：

```powershell
git add app/models.py migrations/versions/0030_return_visit_phase9.sql migrations/downgrades/0030_return_visit_phase9.sql migrations/postgres/auto_wechat/versions/0011_return_visit_phase9.py tests/test_phase9_return_visit_schema.py tests/test_phase9_return_visit_postgres_contract.py
git diff --cached --check
git commit -m "功能：增加 Phase 9 回访数据迁移"
```

**暂停点：** 回传三表升级、回滚、未知键回滚和数据守卫证据。

---

## Task 3：扩展底层抖音发送流水

**文件：**

- Modify: `app/services/douyin_private_message_send_service.py`
- Create: `tests/test_phase9_return_visit_send_service.py`
- Modify: `tests/test_ai_auto_reply_send_service.py`

- [ ] 先写红灯，覆盖：
  - `return_visit_run_id` 写入统一发送流水。
  - `send_source="return_visit_auto"` 映射违禁词 source=`douyin_return_visit`。
  - 成功桩写 `status=sent` 和 `sent_at`；明确业务失败写 failed；网络/非法响应仍由上层判定不确定性。
  - 同一 `return_visit_run_id` 第二次发送被唯一约束阻断。
  - 既有 manual/ai_auto 发送 source、`auto_reply_run_id`、回归结果不变。
  - 未打桩时网络哨兵立即失败。

- [ ] 将 source 映射集中为一个固定字典，未知 source 拒绝，不再默认为 manual：

```python
_FORBIDDEN_SOURCE_BY_SEND_SOURCE = {
    "manual": "douyin_manual",
    "ai_auto": "douyin_ai_auto",
    "return_visit_auto": "douyin_return_visit",
}
```

- [ ] 给 `_send_private_message_with_context` 增加尾参：

```python
return_visit_run_id: int | None = None
```

并在 `DouyinPrivateMessageSend` 构造时写入；不得改变既有公开手动发送函数签名。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase9_return_visit_send_service.py tests/test_ai_auto_reply_send_service.py tests/test_forbidden_word_send_integration.py -q
```

预期：全部通过，测试中的 OpenAPI 调用全部来自替身。

- [ ] 提交：

```powershell
git add app/services/douyin_private_message_send_service.py tests/test_phase9_return_visit_send_service.py tests/test_ai_auto_reply_send_service.py
git diff --cached --check
git commit -m "功能：扩展抖音回访发送流水"
```

**暂停点：** 回传发送流水与既有 ai_auto/manual 回归；不得接入触发路由。

---

## Task 4：9100 严格判定协议

**文件：**

- Create: `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py`
- Create: `apps/xg_douyin_ai_cs/routers/return_visits.py`
- Modify: `apps/xg_douyin_ai_cs/schemas.py`
- Modify: `apps/xg_douyin_ai_cs/main.py`
- Create: `tests/test_phase9_return_visit_judge.py`
- Create: `tests/test_phase9_return_visit_internal_api.py`

- [ ] 先写判定与内部鉴权红灯。请求/响应必须是严格 Pydantic 模型，`extra="forbid"`，核心结构：

```python
from typing import Annotated


class ReturnVisitPromptInput(BaseModel):
    model_config = {"extra": "forbid"}
    template_text: str = Field(..., min_length=1, max_length=500)
    fallback_message: str = Field(..., min_length=1, max_length=500)
    confidence_threshold: float = Field(..., ge=0.50, le=1.00)
    enabled: bool


class ReturnVisitJudgeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    tenant_id: str | None = Field(default=None, max_length=128)
    merchant_id: str = Field(..., min_length=1, max_length=128)
    lead_id: int
    prompts: dict[str, ReturnVisitPromptInput]
    sales_reply_text: str = Field(..., min_length=1)
    dispatch_context: dict


RiskFlag = Annotated[str, Field(max_length=32)]


class ReturnVisitJudgment(BaseModel):
    prompt_key: str | None
    confidence: float = Field(..., ge=0, le=1)
    should_trigger: bool
    suggested_message: str | None = Field(default=None, max_length=500)
    judgement_source: str
    judgement_result: str
    model: str | None
    risk_flags: list[RiskFlag] = Field(default_factory=list, max_length=8)
    ambiguous: bool = False
```

- [ ] 在 9100 模块定义三键、抑制词、否定触发词、肯定触发词和提示词注入模式。9000 不得复制这些常量。

- [ ] 实现固定顺序：
  1. 提示词注入预检，命中直接 `prompt_injection`，不调用 LLM、不兜底。
  2. 抑制词预检，命中 `suppress_hit`。
  3. LLM 最多调用一次；严格解析 JSON。
  4. `model_refusal` 和其它风险返回阻断结果；未知风险归一 `policy_violation`。
  5. 仅未配置、超时、网络、空输出、普通格式错误、置信度越界进入关键词兜底。
  6. 多场景命中 `ambiguous`；关键词单场景命中使用 `fallback_message`、confidence=0.5，且检查 enabled，不经过阈值。

- [ ] 复用 `OpenAICompatibleClient`；日志只记 `lead_id/prompt_key/confidence/judgement_source/judgement_result/model/risk_flags`，不得记录 `sales_reply_text`、模板或兜底文案。

- [ ] 路由固定为：

```python
router = APIRouter(prefix="/internal/return-visits", tags=["回访判定"])

@router.post("/decide-and-generate", response_model=ReturnVisitJudgment)
def decide_and_generate(
    request: ReturnVisitJudgeRequest,
    _token: None = Depends(require_internal_service_token),
): ...
```

- [ ] 测试至少覆盖：三场景、抑制、多命中、无命中、低置信、disabled、技术故障兜底、未知键、越界置信、空输出、超时、网络、格式错误、提示词注入、模型拒答、未知 risk、risk 数量/长度、正确/缺失/错误内部 token、日志无原文。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_internal_api.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_xg_douyin_ai_cs_app.py -q
```

- [ ] 提交：

```powershell
git add apps/xg_douyin_ai_cs/services/return_visit_judge_service.py apps/xg_douyin_ai_cs/routers/return_visits.py apps/xg_douyin_ai_cs/schemas.py apps/xg_douyin_ai_cs/main.py tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_internal_api.py
git diff --cached --check
git commit -m "功能：增加 9100 回访严格判定协议"
```

### 检查点 A：无触发、无发送评审

- [ ] Spec Reviewer 核对 C1/C6/C7/C11/F15：三键、阈值、拒答/注入、关键词归属、内部鉴权。
- [ ] Code Quality Reviewer 核对：LLM 一次、结构解析、风险归一、日志脱敏、既有 9100 回归。
- [ ] 静态确认尚无 `replies.py → process_return_visit_run` 接线，启动钩子未改；没有运行路径能触发回访发送。

**暂停点：** 两位 reviewer 都 PASS 才进入 Task 5；任何 Must-Fix 单开 `Task 4-FIX`。

---

## Task 5：9000 触发持久化与内部客户端

**文件：**

- Modify: `app/services/xg_douyin_ai_cs_client.py`
- Create: `app/services/return_visit_run_service.py`
- Modify: `app/schemas.py`
- Modify: `app/local_agent_main.py`
- Create: `tests/test_phase9_return_visit_trigger.py`
- Create: `tests/test_phase9_return_visit_client.py`

- [ ] 先扩展 `AgentMessage.index: int | None`，并让 Local Agent 两处 `agent-write-back` payload 透传 `read_recent_messages` 的 index。触发算法只接受非负整数 index，缺失或非法 index 保守不触发；不得透传截图、控件树或新原文副本。

- [ ] 用 `unicodedata.normalize("NFKC", text)` + 折叠连续空白实现标准化；按 UI index 升序，用 `\n` 拼成完整 `sender=friend` 回复包。

- [ ] 锚点算法必须保守：
  1. 查当前商户、lead、staff 最新 `send_status="sent"` 的 `LeadNotification`。
  2. 在消息列表中找最后一条 `sender=self` 且标准化 content 精确等于该通知 `notification_text` 的消息。
  3. 只取其后 `sender=friend` 且非空的文本；锚点不存在、只有 unknown/self/system、或没有新 friend 文本时不建 run。
  4. ReplyCheck 是否 pending/replied/timeout 不参与触发判定。

- [ ] 从可信 `DouyinLead` 取 merchant/account/conversation/customer，再用 `get_send_msg_context` 固定 `context_server_message_id`；任一上下文缺失不建 run，只写稳定阶段码日志，不写原文。

- [ ] 实现：

```python
trigger_message_fp = sha256(normalized_bundle.encode("utf-8")).hexdigest()
idempotency_key = sha256(
    f"{merchant_id}:{notification.id}:{trigger_message_fp}".encode("utf-8")
).hexdigest()
```

创建 run 时：`trigger_source="wechat_sales_reply"`、`trigger_text=normalized_bundle`、`send_status="pending_judgement"`、`attempt_count=1`。唯一冲突返回既有 run，不新建第二行。

- [ ] `XgDouyinAiCsClient` 只新增一个窄方法：

```python
def judge_return_visit(self, request: dict) -> dict:
    return self._post_json("/internal/return-visits/decide-and-generate", request)
```

- [ ] 本任务不改 `app/routers/replies.py`，不调度 processor，不调用 9100 或发送函数；只完成可测试的持久化与客户端。

- [ ] 测试覆盖：精确锚点、锚点前 friend 排除、锚点后多条拼包、index 透传、unknown 排除、无锚点、通知未 sent、跨商户、上下文缺失、ReplyCheck timeout 仍建 run、同包幂等、同派单不同包新 run、触发原文不进日志、client 路径和 token header 复用。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase9_return_visit_trigger.py tests/test_phase9_return_visit_client.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_phase7_fix2_local_agent_auth.py -q
```

- [ ] 提交：

```powershell
git add app/services/xg_douyin_ai_cs_client.py app/services/return_visit_run_service.py app/schemas.py app/local_agent_main.py tests/test_phase9_return_visit_trigger.py tests/test_phase9_return_visit_client.py
git diff --cached --check
git commit -m "功能：增加销售微信回复回访触发持久化"
```

**暂停点：** 回传锚点、ReplyCheck 解耦、幂等和原文脱敏证据。

---

## Task 6：统一处理入口、十一项门禁与全替身发送闭环

**文件：**

- Modify: `app/services/return_visit_run_service.py`
- Modify: `app/routers/replies.py`
- Modify: `app/services/douyin_private_message_send_service.py`（仅发现 Task 3 遗漏时允许；正常应零改）
- Create: `tests/test_phase9_return_visit_run_service.py`
- Create: `tests/test_phase9_return_visit_e2e.py`
- Modify: `tests/test_phase9_return_visit_trigger.py`

- [ ] 先写 processor 红灯，固定唯一公开入口：

```python
def process_return_visit_run(run_id: int) -> None:
    """自行创建并关闭 DB Session；终态和 claim 冲突直接返回。"""
```

- [ ] 用条件 UPDATE 原子 claim：仅 `pending_judgement → processing`，设置随机 `lease_owner` 和短租约；rowcount=0 直接返回。禁止对 8 个终态继续。

- [ ] 从 DB 重读 `trigger_text` 和三条 prompt，调用 `XgDouyinAiCsClient.judge_return_visit`；响应再次由 9000 Pydantic schema 校验，不能信任 9100 任意 JSON。

- [ ] 严格映射判定结果：`no_match/ambiguous/suppress_hit → not_needed`，`below_threshold → confidence_low`，disabled → prompt_disabled，risk → blocked；关键词分支 confidence=0.5 不过阈值。

- [ ] 在 `send_authorized` 前按固定顺序执行 G1-G10：
  1. `config.DOUYIN_AUTO_REPLY_ENABLED` 和 `config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED`。
  2. 直接查询 global `AutoReplyRolloutConfig.real_send_enabled`；不调用白名单 rollout 聚合。
  3. lead/account/merchant 可信归属。
  4. `evaluate_manual_takeover_gate`。
  5. `get_latest_private_message_state` 三条件分别输出 `outbound_after_trigger/latest_not_customer/context_drifted`。
  6. 实际发送流水一小时计数，source 只含 `ai_auto/return_visit_auto`，设置缺失、None 或 <=0 回落 60。
  7. 24h 冷却 JOIN `DouyinPrivateMessageSend.return_visit_run_id`，只计 run/send 均 sent，时间只用 `send.sent_at`。
  8. 幂等已由唯一键保证，不创建新 run。
  9. 只对 `judgement_source="llm"` 检查 prompt 阈值。
  10. 非空话术、长度 <=500、risk_flags 固定枚举；底层负责违禁词替换。

不得调用：`is_automation_allowed`、账号/客户白名单、`ai_auto_reply_send_service`、`_frequency_snapshot`。

- [ ] `gate_results_json` 只保存稳定 gate/code/布尔值，不保存 open_id、回复包、话术、token 或异常正文。

- [ ] 所有 gate 通过后先提交 `send_status="send_authorized"`，再调用底层函数：

```python
_send_private_message_with_context(
    db,
    content=run.generated_content,
    send_context=send_context,
    manual_confirmed=False,
    auto_send=True,
    send_source="return_visit_auto",
    return_visit_run_id=run.id,
)
```

- [ ] 发送结果分类：code=0 → sent；明确 `upstream_business_error` → failed；网络、超时、HTTP、非法/空响应等“请求可能已到上游”的结果 → send_unknown。send_unknown 永不重发。

- [ ] 修改 `/replies/agent-write-back`：保留现有 ReplyCheck 返回语义；完成既有回写后独立调用触发持久化。新建 pending run 才 `BackgroundTasks.add_task(process_return_visit_run, run.id)`；触发失败不得回滚或伪造既有回复检测结果。

- [ ] E2E 测试全部替身：构造 sent 派单通知 + UI index 消息 + 9100 判定替身 + OpenAPI 成功桩，断言单行 run、单行发送流水、sent；再覆盖抑制、低置信、disabled、所有 gate、rate_limited、send_unknown、ReplyCheck timeout 解耦和并发幂等。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase9_return_visit_run_service.py tests/test_phase9_return_visit_e2e.py tests/test_phase9_return_visit_trigger.py tests/test_ai_auto_reply_send_service.py tests/test_p1_auto_1c_poll_and_detect.py -q
```

预期：全部通过，网络哨兵调用数 0；成功桩只在明确成功用例被调用。

- [ ] 提交：

```powershell
git add app/services/return_visit_run_service.py app/routers/replies.py tests/test_phase9_return_visit_run_service.py tests/test_phase9_return_visit_e2e.py tests/test_phase9_return_visit_trigger.py
git diff --cached --check
git commit -m "功能：完成 Phase 9 回访安全处理闭环"
```

**暂停点：** 回传 G1-G11、真实网络为 0、send_unknown 禁重发及 ReplyCheck 解耦证据。

---

## Task 7：分层崩溃恢复与启动一次性执行器

**文件：**

- Modify: `app/services/return_visit_run_service.py`
- Modify: `app/main.py`
- Create: `tests/test_phase9_return_visit_recovery.py`
- Modify: `tests/test_phase9_return_visit_run_service.py`

- [ ] 先写恢复红灯：pending 重调度；过期 processing 回 pending 且 `attempt_count += 1`；send_authorized 有 sent 流水对账 sent，无 sent 流水对账 send_unknown；8 终态不动。

- [ ] 实现 `reconcile_return_visit_runs_on_startup()`：
  - 模块级非阻塞 Lock 保证单飞；获取失败直接记录 stable code 后返回。
  - 启动时固定 eligible 最大 id 快照，按 100 条分页，内存与并发有界；只处理快照内记录，直到清空后退出。
  - 先原子回收过期 processing，再对账 send_authorized，最后依次调用 `process_return_visit_run` 处理 pending。
  - 不使用 `BackgroundTasks`，不建周期线程、不 sleep、不轮询。

- [ ] 在既有 `on_startup` 中只创建一次后台线程任务，不能阻塞应用启动。使用标准库：

```python
threading.Thread(
    target=reconcile_return_visit_runs_on_startup,
    name="return-visit-recovery-once",
    daemon=True,
).start()
```

若项目已有同等一次性线程 helper，优先复用；不得新增 scheduler 或依赖。

- [ ] 测试启动钩子只启动一次、函数返回后无线程循环；processor 用替身，禁止真实 9100/抖音网络。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase9_return_visit_recovery.py tests/test_phase9_return_visit_run_service.py tests/test_9000_async_pg_lifecycle.py tests/test_daily_report_scheduler.py -q
```

- [ ] 提交：

```powershell
git add app/services/return_visit_run_service.py app/main.py tests/test_phase9_return_visit_recovery.py tests/test_phase9_return_visit_run_service.py
git diff --cached --check
git commit -m "功能：增加回访任务分层崩溃恢复"
```

### 检查点 B：完整代码路径无真实网络双重评审

- [ ] Spec Reviewer 核对 C3-C5/C8-C10/C12：锚点、ReplyCheck 解耦、持久化优先、幂等、冷却、11 态、恢复和底层发送。
- [ ] Code Quality Reviewer 核对：原子 claim、事务边界、并发唯一、send_authorized 保守恢复、Session 生命周期、线程单飞、日志脱敏。
- [ ] Security Reviewer 静态确认不使用微信熔断/灰度白名单/上层 auto-reply service，不存在未打桩网络测试。

**暂停点：** 三方 PASS 才进入管理端；任何 Must-Fix 单开定向修复，不用 concern 包住代码缺陷。

---

## Task 8：管理 API、审计与响应脱敏

**文件：**

- Create: `app/routers/admin_return_visits.py`
- Modify: `app/main.py`
- Modify: `app/schemas.py`
- Create: `tests/test_phase9_return_visit_admin_api.py`

- [ ] 定义 PUT 请求，严格限制：`template_text/fallback_message` 1..500、threshold 0.50..1.00、enabled bool、reason 非空；未知字段 422。

- [ ] 所有端点使用既有 `get_request_context_required`，权限精确为 `auto_wechat:admin:return_visit_prompts`。

- [ ] 实现固定路由：

```text
GET /admin/return-visit-prompts
PUT /admin/return-visit-prompts/{prompt_key}
GET /admin/return-visit-runs
GET /admin/return-visit-runs/stats
GET /admin/return-visit-runs/{run_id}
```

注意 `/stats` 必须定义在 `/{run_id}` 之前，避免路径被整数路由吞掉。

- [ ] prompt 只接受三键、scope 必须 global。PUT 同一事务：调用 `replace_forbidden_words(merchant_id=context.merchant_id or "global", source="return_visit_prompt_edit")` 只用于命中日志和告警，数据库仍保存管理员提交原文；再 `record_admin_audit(action="return_visit_prompt_update", target_type="return_visit_prompt", target_id=prompt_key, before=旧摘要, after=新摘要, reason=reason)`，最后一次 commit。

- [ ] runs 列表支持 `send_status/prompt_key/judgement_source/page/page_size`；super_admin 可看全部，其他管理员只看 `context.merchant_ids`。详情不在授权 merchant 集合统一 404。

- [ ] 列表和详情均不得返回 `trigger_text`；列表不返回 `customer_open_id/generated_content/final_content`；详情可返回 customer_open_id 和生成/最终话术，但不返回手机号、token、原始异常。JSON 字段解析失败返回空列表/空对象和稳定诊断，不回显原串。

- [ ] 不实现 retry/send/requeue/立即发送端点。

- [ ] 测试：三条 prompt、逐字 fallback、PUT reason/范围/审计/违禁词告警、无权限 403、未知 key 404、runs 过滤与统计、商户隔离 404、trigger_text 零回显、无写发送端点。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase9_return_visit_admin_api.py tests/test_admin_autoreply_rollout_api.py tests/test_autoreply_admin_rollout_service.py tests/test_ai_reply_decision_logs_api.py -q
```

- [ ] 提交：

```powershell
git add app/routers/admin_return_visits.py app/main.py app/schemas.py tests/test_phase9_return_visit_admin_api.py
git diff --cached --check
git commit -m "功能：增加回访配置与运行审计接口"
```

**暂停点：** 回传权限、审计、商户隔离和原文零回显证据。

---

## Task 9：超管回访配置与只读运行页

**文件：**

- Create: `frontend/src/api/adminReturnVisits.ts`
- Create: `frontend/src/pages/AdminReturnVisitsPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/SideNav.tsx`
- Modify: `frontend/src/pages/Index.tsx`
- Modify: `frontend/src/newcarRedirect.ts`
- Create: `frontend/scripts/check-phase9-return-visits-contract.mjs`

- [ ] 先写 Node 合同红灯，检查：权限、route、nav、默认跳转、API 路径、PUT reason、threshold 边界、页面不含 retry/send/立即发送命令。

- [ ] API 类型必须与 Task 8 响应一致；禁止 `any`，JSON 审计字段用 `Record<string, unknown>`。

- [ ] 把 `adminReturnVisitPrompts` 既有权限接到真实本地页：
  - App admin route：`/admin/return-visits`、navId=`admin-return-visits`。
  - 默认管理员路径由 `/admin/no-local-feature` 改为 `/admin/return-visits`。
  - `canAccessPath`、`newcarRedirect`、SideNav、Index 渲染同步。
  - 使用 lucide `MessagesSquareIcon` 或语义最接近的现有图标。

- [ ] 页面采用两个 tabs：`提示词配置` / `运行记录`。提示词按三条紧凑列表展示，不嵌套卡片；编辑抽屉包含模板、兜底文案、0.01 step 数字输入、enabled 开关、必填 reason。运行记录用表格 + 详情抽屉，只读。

- [ ] 状态、场景和风险码提供稳定中文映射，未知值显示原码；长文本换行且不溢出。不得添加“重试”“立即发送”按钮。

- [ ] 运行前端三检：

```powershell
Push-Location frontend
node scripts/check-phase9-return-visits-contract.mjs
npx tsc -p tsconfig.app.json --noEmit
npm run build
Pop-Location
```

预期：三条命令退出码均为 0。

- [ ] 提交：

```powershell
git add frontend/src/api/adminReturnVisits.ts frontend/src/pages/AdminReturnVisitsPage.tsx frontend/src/App.tsx frontend/src/components/SideNav.tsx frontend/src/pages/Index.tsx frontend/src/newcarRedirect.ts frontend/scripts/check-phase9-return-visits-contract.mjs
git diff --cached --check
git commit -m "功能：增加回访配置与运行记录页面"
```

**暂停点：** 回传合同、TypeScript、build；本阶段不启动浏览器做真实账号联调。

---

## Task 10：阶段总验证、网络零调用证明与双重评审

**文件：**

- Modify: `tests/test_phase9_return_visit_e2e.py`（仅补遗漏验收，不改业务语义）
- Create: `tests/test_phase9_return_visit_no_network.py`
- Create: `frontend/scripts/check-phase9-return-visit-final-contract.mjs`

不得修改 master plan、冻结设计或 `docs/待确认事项.md`；这些文件已有用户改动，最终状态由审批窗口另行登记。

- [ ] 增加全阶段网络哨兵测试：patch `requests.post/httpx.post/call_douyin_openapi/OpenAICompatibleClient.chat` 为抛错，证明普通合同与门禁用例不触网；需要成功的用例仅使用局部受控替身并断言次数。

- [ ] 补端到端矩阵：
  - 手机号不对 → retain → 模拟 sent。
  - 金融方案 → finance。
  - 长期未回复 → silent。
  - 已联系上 → suppress_hit/not_needed。
  - 注入和模型拒答 → blocked，不兜底。
  - 技术故障 → 关键词兜底。
  - timeout ReplyCheck 仍触发。
  - 相同回复包永久幂等；不同包可建新 run。
  - 24h 内 sent 冷却，非 sent 不计。
  - 重启 pending/processing/send_authorized 三分层恢复。
  - 8 终态不重试。

- [ ] 后端 Phase 9 专项：

```powershell
python -m pytest tests/test_phase9_return_visit_schema.py tests/test_phase9_return_visit_postgres_contract.py tests/test_phase9_return_visit_send_service.py tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_internal_api.py tests/test_phase9_return_visit_trigger.py tests/test_phase9_return_visit_client.py tests/test_phase9_return_visit_run_service.py tests/test_phase9_return_visit_recovery.py tests/test_phase9_return_visit_admin_api.py tests/test_phase9_return_visit_e2e.py tests/test_phase9_return_visit_no_network.py -q
```

- [ ] 关联回归：

```powershell
python -m pytest tests/test_ai_auto_reply_send_service.py tests/test_admin_autoreply_rollout_api.py tests/test_autoreply_admin_rollout_service.py tests/test_forbidden_word_send_integration.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_phase7_fix2_local_agent_auth.py tests/test_daily_report_scheduler.py tests/test_9000_async_pg_lifecycle.py tests/test_xiaogao_phase1_context_contract.py -q
```

预期：不得新增失败。pre-existing 必须用起点提交对照证明，不能包装为 Phase 9 通过项。

- [ ] 前端最终合同：

```powershell
Push-Location frontend
node scripts/check-phase9-return-visits-contract.mjs
node scripts/check-phase9-return-visit-final-contract.mjs
npx tsc -p tsconfig.app.json --noEmit
npm run build
Pop-Location
```

- [ ] 静态门禁：

```powershell
$phase9Start = "b077feb"
git diff --check "$phase9Start..HEAD"
git diff --name-only "$phase9Start..HEAD"
rg -n "is_automation_allowed|_frequency_snapshot|ai_auto_reply_send_service" app/services/return_visit_run_service.py
rg -n "retry|requeue|立即发送" app/routers/admin_return_visits.py frontend/src/pages/AdminReturnVisitsPage.tsx
rg -n "trigger_text" app/routers/admin_return_visits.py frontend/src/api/adminReturnVisits.ts
```

预期：diff check 零输出；三个禁止调用在 run service 零命中；管理端无发送写操作；`trigger_text` 不进入响应/API 类型。

- [ ] 若现成隔离 PostgreSQL `_test` 库可用，可执行 0011 upgrade→downgrade→upgrade smoke；不得创建新共享环境，不得连接宝塔或生产。没有现成隔离库不阻塞本阶段，PG 结构合同仍必须通过；唯一 concern 的名称仍严格保持 `baota_production_send_not_verified`，不得另造 concern。

- [ ] 双重评审：
  - Spec Reviewer 逐条核对 C1-C13、F1-F16、G1-G11 和 §11.1-11.8。
  - Code Quality Reviewer 核对事务、并发、租约、恢复、脱敏、商户隔离、测试真实性和前端权限。
  - 任一 Must-Fix 必须关闭后重评；不能以 `DONE_WITH_CONCERNS` 包住代码缺陷。

- [ ] 提交总验收测试：

```powershell
git add tests/test_phase9_return_visit_e2e.py tests/test_phase9_return_visit_no_network.py frontend/scripts/check-phase9-return-visit-final-contract.mjs
git diff --cached --check
git commit -m "测试：完成 Phase 9 回访阶段总验证"
```

- [ ] 最终回传固定口径：

```text
Phase 9 代码与模拟闭环：DONE
Phase 9：DONE_WITH_CONCERNS
唯一 concern：baota_production_send_not_verified
Phase 8-B：PARTIAL_BLOCKED_DEFERRED
Phase 11 一键过审：CANCELLED_BY_CUSTOMER
Task 8（日报真实分发）：NOT_STARTED
真实抖音回访发送：未执行，留待宝塔生产验证执行包
```

**暂停点：** 回传最终测试、静态门禁、提交链和双重评审结论；不得继续进入宝塔真实验证。

---

## 11. 提交序列与检查点总览

| Task | 预期提交信息 | 强制暂停 |
|---|---|---|
| 0 | 无提交 | 起点/基线确认 |
| 1 | `测试：冻结 Phase 9 回访数据合同` | 红灯回传 |
| 2 | `功能：增加 Phase 9 回访数据迁移` | 数据层回传 |
| 3 | `功能：扩展抖音回访发送流水` | 底层发送回传 |
| 4 | `功能：增加 9100 回访严格判定协议` | 检查点 A 双评审 |
| 5 | `功能：增加销售微信回复回访触发持久化` | 触发/幂等回传 |
| 6 | `功能：完成 Phase 9 回访安全处理闭环` | 门禁/模拟发送回传 |
| 7 | `功能：增加回访任务分层崩溃恢复` | 检查点 B 三评审 |
| 8 | `功能：增加回访配置与运行审计接口` | API/审计回传 |
| 9 | `功能：增加回访配置与运行记录页面` | 前端三检回传 |
| 10 | `测试：完成 Phase 9 回访阶段总验证` | 最终双评审 |

执行窗口不得合并多个 Task 为一个提交；定向修复使用 `Task N-FIX` 独立提交。任何提交都不得包含 0.4 的既有工作区文件。

## 12. 宝塔后置执行包边界

本包完成后不继续做真实验证。后续必须另开“Phase 9 宝塔生产回访验证执行包”，至少重新审批：专用测试账号与客户、无敏感测试消息、单发时间窗、env 与 DB 双熔断开关顺序、账号限频、成功信号、失败回滚、监控、紧急停止、`send_unknown` 人工审计。该后置执行包不反向阻塞本包代码阶段。
