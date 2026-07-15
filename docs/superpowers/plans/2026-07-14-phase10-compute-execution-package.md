# Phase 10 小高算力补齐逐任务执行包

> **文档状态（2026-07-14 审查）：当前有效执行包。** 执行进度必须以 Git 提交、测试证据和最终验收文档为准，未勾选项不得被解释为允许重复执行已完成任务；当前项目事实以 `docs/ai/05_PROJECT_CONTEXT.md` 为准。本文件已被 Phase 10 数据合同测试直接引用，必须保持当前路径。
>
> **执行窗口必读：** 必须使用 `subagent-driven-development`（推荐）或 `executing-plans`，严格按 Task 0-7 顺序执行。每项使用 `- [ ]` 跟踪，先红灯、再最小实现、再绿灯、再提交；检查点 A、B 和最终验收必须硬暂停回传。

**目标：** 在不连接宝塔、不迁移生产数据库、不调用真实 LLM/Embedding 网络的前提下，完成小高算力三套餐与六能力配置校验、按字符计量、上浮计费快照、可信商户 AI 埋点、管理权限和前端展示的本地/模拟闭环。

**架构：** 继续复用 `apps.compute.services` 作为算力业务真实现，9000 旧路由与 9205 能力路由共享同一 DTO 和服务，不新建计费服务。9100 在每次成功 AI 调用后只上报字符数、能力、模型和稳定上下文，不上报提示词或输出原文；9000 按全局能力比例计算计费量，并在同一流水中保存实际量、比例快照和计费量。SQLite 0031 与 PostgreSQL 0012 只扩展既有算力表。

**技术栈：** FastAPI、Pydantic、SQLAlchemy、SQLite 迁移 runner、PostgreSQL/Alembic、React 19、TypeScript、pytest、Node 静态合同脚本。

---

## 0. 冻结输入与总门禁

### 0.1 权威输入与状态

- 权威总控：`docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md` Phase 10。
- Phase 9 最低祖先提交：`265d719`。
- 当前真实实现：`apps/compute/services.py`；`app/services/compute_service.py` 只是兼容转发层。
- 当前基础迁移：SQLite `0027_xiaogao_phase1_core.sql`、PostgreSQL `0008_xiaogao_phase1_core.py`。
- 当前三个套餐 seed 已存在，不重复造 seed：基础版 99/100000、标准版 299/350000、专业版 699/900000。
- 当前六能力 seed 已存在：`douyin-cs`、`leads`、`agents`、`wechat-assistant`、`compute`、`knowledge`。
- Phase 9 保持 `DONE_WITH_CONCERNS`，其 concern 仍为 `baota_production_send_not_verified`。
- Phase 8-B 保持 `PARTIAL_BLOCKED_DEFERRED`；日报真实分发 Task 8 保持 `NOT_STARTED`。
- Phase 11 一键过审保持 `CANCELLED_BY_CUSTOMER`，不得因总控旧文本而恢复。

### 0.2 甲方已批准的 Phase 10 计费合同

#### 字符计量

```python
def count_chat_characters(messages: list[dict], reply_text: str) -> int:
    request_chars = sum(
        len(item["content"])
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    )
    return request_chars + len(reply_text)
```

- “字符”固定为 Python `len(str)` 的 Unicode 字符数量，不按 UTF-8 字节、不读取供应商 tokenizer。
- Chat 实际量 = 本次真实发给模型的所有 message `content` 字符数 + 本次原始 `reply_text` 字符数；不先 `strip`。
- Embedding 实际量 = 本次送入 embedding 的文本字符数。
- 供应商 `usage.total_tokens` 可继续透传作诊断，但禁止参与 Phase 10 余额或流水计算。
- 同一业务中的模型重试是多次 AI 操作；每次成功返回都分别上报，不能只上报最后一次。
- Provider 抛错、未返回结果时不扣费；Mock embedding `model=mock_for_test_only` 不扣费。

#### 上浮和快照

```python
BASIS_POINT_DENOMINATOR = 10_000
POSTGRES_INTEGER_MAX = 2_147_483_647
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807

def calculate_billed_tokens(actual_tokens: int, markup_basis_points: int) -> int:
    numerator = actual_tokens * (BASIS_POINT_DENOMINATOR + markup_basis_points)
    billed_tokens = (numerator + BASIS_POINT_DENOMINATOR - 1) // BASIS_POINT_DENOMINATOR
    if billed_tokens > POSTGRES_BIGINT_MAX:
        raise ValueError("COMPUTE_VALUE_OUT_OF_RANGE")
    return billed_tokens
```

- 上浮后固定向上取整。
- 产品层不设置上浮比例上限；仅受当前 PostgreSQL `INTEGER` 列的技术表示边界 `0..2147483647` 基点约束。该边界不是产品套餐规则，不得另加 100% 或 1000% 上限。
- 计费结果和新余额必须处于 PostgreSQL `BIGINT` 范围；超出时整笔拒绝且不得写流水或改余额。
- `ComputeTransaction.actual_tokens` 保存实际字符量。
- `ComputeTransaction.capability_key` 保存本次能力。
- `ComputeTransaction.markup_basis_points` 保存本次生效比例快照。
- 既有 `delta_tokens` 继续是带符号计费量：消费为 `-billed_tokens`，充值/发放保持正数。
- 历史 consume 流水回填 `actual_tokens=abs(delta_tokens)`、`markup_basis_points=0`；历史能力无法证明，`capability_key=NULL`，禁止伪造。
- 比例行 `enabled=false` 表示本能力暂不上浮，仍按实际量计费，快照记 0；比例行缺失或能力非法则拒绝本次 usage，不静默按 0 处理。
- 余额不足仍不阻断；负 `balance_after_tokens` 本身是持久化风险证据，并写结构化 warning，不新增余额拦截。

#### 能力映射

| 现有 AI 操作 | capability_key | source |
|---|---|---|
| 抖音回复决策（含每次重试） | `douyin-cs` | `llm` |
| 每日销售摘要 | `wechat-assistant` | `llm` |
| Phase 9 微信到抖音回访判定 | `wechat-assistant` | `llm` |
| 知识库问答生成 | `knowledge` | `llm` |
| 知识库训练/检索 Embedding | `knowledge` | `embedding` |

`leads`、`agents`、`compute` 本阶段只保留配置，不制造不存在的 AI 调用。Phase 12 AI 剪辑、ASR 尚未进入本仓库，本阶段不提前写占位埋点。

### 0.3 真实验证统一后置

Phase 13 完成前，本包明确禁止：

- 连接宝塔、生产 PostgreSQL、生产 SQLite、生产 Milvus。
- 执行真实迁移、Docker 重建、Nginx 调整或部署脚本。
- 调用真实 OpenAI/OpenRouter/Ark、抖音 OpenAPI、微信 Local Agent。
- 使用真实 token、cookie、secret、客户原文作为测试数据。
- 因未做生产验证而阻塞 Phase 10 本地/模拟完成，也不得据此提前制定生产操作。

允许范围仅为：临时 SQLite、迁移静态合同、FastAPI `TestClient`、LLM/Embedding/usage 全替身、前端静态合同、类型检查和构建。

### 0.4 脏工作区保护

制定本包时已存在下列用户或并发窗口改动，执行窗口不得清理、回滚、暂存或混入：

```text
.gitignore
app/db_readiness.py
app/routers/health.py
docker-compose.dev.yml
docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md
docs/ai/05_PROJECT_CONTEXT.md -> docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md
docs/superpowers/plans/2026-07-10-xiaogao-ai-phase1-master-plan.md
docs/待确认事项.md
migrations/migrate_sqlite.py
tests/test_db_readiness.py
tests/test_phase8b_local_agent_downloader.py
docs/superpowers/plans/2026-07-12-phase7-fix2-task8-blocker-remediation-execution-package.md
docs/superpowers/plans/2026-07-12-phase8-daily-automatic-reports-execution-package.md
docs/superpowers/plans/2026-07-13-phase8-b-daily-report-excel-attachment-delivery-execution-package.md
docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md
scripts/generate_phase8_visual_samples.py
tests/test_local_sqlite_startup_integration.py
```

本执行包文件也由审批窗口创建，执行 Task 时不得把它与业务提交混在一起。每次只能 `git add <本任务白名单>`，禁止 `git add .` 和 `git add -A`。执行期间出现的新无关改动同样视为用户所有；只有白名单文件发生无法合并的并发改动时才暂停。

### 0.5 预期文件边界

本阶段最多涉及以下文件，Task 未列出的文件不得顺手修改：

```text
app/models.py
app/schemas.py
app/services/compute_service.py
app/routers/compute.py
apps/compute/dependencies.py
apps/compute/schemas.py
apps/compute/services.py
apps/compute/routers.py
packages/clients/compute_client.py
apps/xg_douyin_ai_cs/services/compute_usage_client.py
apps/xg_douyin_ai_cs/schemas.py
apps/xg_douyin_ai_cs/services/reply_decision_service.py
apps/xg_douyin_ai_cs/services/daily_report_summary_service.py
apps/xg_douyin_ai_cs/services/return_visit_judge_service.py
apps/xg_douyin_ai_cs/services/knowledge_training_service.py
apps/xg_douyin_ai_cs/rag/repository.py
migrations/versions/0031_compute_billing.sql
migrations/downgrades/0031_compute_billing.sql
migrations/postgres/auto_wechat/versions/0012_compute_billing.py
frontend/src/api/compute.ts
frontend/src/api/types.ts
frontend/src/features/compute/pages/ComputeCenter.tsx
frontend/src/features/compute/pages/SuperComputeConfig.tsx
frontend/scripts/check-phase10-compute-contract.mjs
frontend/package.json
docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md
本包明确列出的专项测试
```

禁止修改历史迁移 `0010/0027/0005/0008`，禁止修改当前脏文件 `migrations/migrate_sqlite.py`。

### 0.6 固定执行节奏

- Task 0-1 可连续执行，Task 1 提交后回传红灯证据。
- Task 2 完成后进入**检查点 A：数据合同复审**，未通过不得进入 Task 3。
- Task 3-5 可在检查点 A 通过后连续执行。
- Task 5 完成后进入**检查点 B：计费与全埋点复审**，未通过不得进入前端。
- Task 6-7 可在检查点 B 通过后连续执行。
- Task 7 完成后硬暂停；不进入宝塔验证。

每个 Task 固定回传：提交哈希、精确文件、红灯、绿灯、关联回归、网络调用数、脏工作区保护和残留风险。

---

## Task 0：起点、调用点与基线冻结

**文件：** 无修改、无提交。

- [ ] 确认 Phase 9 最终提交在祖先链，并记录当前工作区：

```powershell
git rev-parse --short HEAD
git merge-base --is-ancestor 265d719 HEAD
if ($LASTEXITCODE -ne 0) { throw "HEAD 不包含 Phase 9 最终提交 265d719" }
git status --short
```

- [ ] 确认现有套餐、能力和真实服务位置，禁止重复实现：

```powershell
rg -n "基础版|标准版|专业版|compute_markup_ratios|douyin-cs|wechat-assistant|knowledge" migrations/versions/0027_xiaogao_phase1_core.sql migrations/postgres/auto_wechat/versions/0008_xiaogao_phase1_core.py
rg -n "def record_usage|def _write_transaction|class ComputeTransaction|class ComputeMarkupRatio" apps/compute/services.py app/models.py
```

- [ ] 固定当前 AI 调用点清单：

```powershell
rg -n "\.chat\(|\.embed\(" apps/xg_douyin_ai_cs -g "*.py"
```

预期生产调用只落在回复决策、日报摘要、回访判定、知识问答和 `rag/repository.py` 的 embedding 路径；脚本/测试命中单独记录，不纳入生产埋点。

- [ ] 跑算力与相邻 Phase 9 基线：

```powershell
python -m pytest tests/test_compute_models.py tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_usage_client.py tests/test_phase9_return_visit_judge.py tests/test_xg_douyin_ai_cs_daily_report_summary.py -q
```

失败必须用当前 HEAD 对照证明是否既有；不得在 Task 0 修无关问题。

---

## Task 1：冻结 Phase 10 数据合同红灯

**文件：**

- Create: `tests/test_phase10_compute_schema.py`
- Create: `tests/test_phase10_compute_postgres_contract.py`

- [ ] 在 SQLite/ORM 合同测试中先写以下红灯：

```python
def test_compute_transaction_declares_billing_snapshot_columns():
    columns = ComputeTransaction.__table__.columns
    assert {"actual_tokens", "capability_key", "markup_basis_points"} <= set(columns.keys())
    assert isinstance(columns["actual_tokens"].type, BigInteger)
    assert columns["actual_tokens"].nullable is True
    assert columns["capability_key"].type.length == 64


def test_phase10_sqlite_migration_files_exist():
    assert (SQLITE_VERSIONS / "0031_compute_billing.sql").is_file()
    assert (SQLITE_DOWNGRADES / "0031_compute_billing.sql").is_file()
```

测试还必须固定：

- 0031 只安全重建 `compute_transactions` 与 `compute_markup_ratios`，不新建第四张算力业务表。
- 从临时 0030 基线升级后，历史 consume 的实际量/0 比例正确回填，能力保持空；充值和套餐流水三个新字段保持空。
- 两表升级前后行数、最大 ID、旧列双向多重集一致；旧索引和六能力唯一约束保留。
- 0031 重复 apply 由 runner 幂等跳过。
- downgrade 恢复 0030 列集、数据不丢、删除 0031 登记，随后可再次 upgrade。
- 迁移中途守卫失败时整体 rollback，不留 `_backup_0031` 或 `_new_0031`。
- 三套餐和六能力 seed 仍精确存在且不会重复；0031 不重复插入它们。

- [ ] 在 PostgreSQL 静态合同中固定：

```python
def test_postgres_0012_revision_chain():
    content = PG_FILE.read_text(encoding="utf-8")
    assert 'revision = "0012_compute_billing"' in content
    assert 'down_revision = "0011_return_visit_phase9"' in content


def test_postgres_0012_adds_only_billing_snapshot_columns():
    content = PG_FILE.read_text(encoding="utf-8")
    assert '"actual_tokens"' in content
    assert '"capability_key"' in content
    assert '"markup_basis_points"' in content
    assert 'op.create_table("compute_' not in content
```

同时断言 PostgreSQL 使用 `BIGINT` 保存实际量，比例快照与既有比例列保持 `INTEGER`，upgrade 回填历史 consume，downgrade 只删除 3 个新列/约束，不删除任何算力表。

- [ ] 运行红灯：

```powershell
python -m pytest tests/test_phase10_compute_schema.py tests/test_phase10_compute_postgres_contract.py -q
```

预期：因 ORM 新列和 0031/0012 文件不存在而失败；不接受语法、导入或 fixture 错误。

- [ ] 提交测试合同：

```powershell
git add tests/test_phase10_compute_schema.py tests/test_phase10_compute_postgres_contract.py
git diff --cached --check
git commit -m "测试：冻结 Phase 10 算力数据合同"
```

---

## Task 2：ORM、SQLite 0031 与 PostgreSQL 0012

**文件：**

- Modify: `app/models.py`
- Create: `migrations/versions/0031_compute_billing.sql`
- Create: `migrations/downgrades/0031_compute_billing.sql`
- Create: `migrations/postgres/auto_wechat/versions/0012_compute_billing.py`
- Modify: `tests/test_phase10_compute_schema.py`
- Modify: `tests/test_phase10_compute_postgres_contract.py`

- [ ] 最小扩展 ORM：

```python
class ComputeTransaction(Base):
    __table_args__ = (
        Index("idx_compute_transactions_merchant_created", "merchant_id", "created_at"),
        CheckConstraint(
            "actual_tokens IS NULL OR actual_tokens > 0",
            name="ck_compute_transactions_actual_positive",
        ),
        CheckConstraint(
            "markup_basis_points IS NULL OR markup_basis_points >= 0",
            name="ck_compute_transactions_markup_nonnegative",
        ),
    )

    actual_tokens = Column(BigInteger, nullable=True, comment="AI 实际字符量")
    capability_key = Column(String(64), nullable=True, comment="六能力 key；历史未知允许空")
    markup_basis_points = Column(Integer, nullable=True, comment="本次计费上浮基点快照")


class ComputeMarkupRatio(Base):
    __table_args__ = (
        UniqueConstraint("capability_key", name="uk_compute_markup_ratios_capability_key"),
        CheckConstraint(
            "markup_basis_points >= 0",
            name="ck_compute_markup_ratios_basis_points_nonnegative",
        ),
    )
```

- [ ] SQLite 0031 必须单事务安全重建两表：
  - 开头 `BEGIN`，结尾登记 0031 后 `COMMIT`。
  - 重建前检查两表列集符合 0030 状态，并检查 `compute_markup_ratios` 六键精确存在、无未知键。
  - `compute_transactions` 复制时只对历史 consume 回填 `actual_tokens=abs(delta_tokens)`、`markup_basis_points=0`、`capability_key=NULL`。
  - 每张表在删除 backup 前依次校验行数、`max(id)`、按全部旧列的双向 `EXCEPT`；任何失败整体回滚。
  - 恢复 `uk_compute_markup_ratios_capability_key` 和已有 transaction 索引，不增加套餐 seed。

- [ ] SQLite downgrade 使用相同事务和多重集守卫，删除三个新列并精确恢复 0030 表结构；先校验当前列集，禁止在未升级或二次降级状态运行。

- [ ] PostgreSQL 0012：
  - `actual_tokens BIGINT NULL`、`capability_key VARCHAR(64) NULL`、`markup_basis_points INTEGER NULL`。
  - 添加两个非负/正数 CHECK。
  - 历史 consume 回填实际量和 0 比例，能力不回填。
  - upgrade 不建表、不修改既有 `delta_tokens`/余额类型、不重写套餐或六能力 seed。
  - downgrade 先删 CHECK，再删三个新列；不删除历史表或 seed。

- [ ] 只在 `tmp_path` 临时 SQLite 执行升级、故障回滚、降级、再升级；PostgreSQL 本 Task 仅静态合同，不连接任何实例。

- [ ] 运行绿灯和迁移回归：

```powershell
python -m pytest tests/test_phase10_compute_schema.py tests/test_phase10_compute_postgres_contract.py tests/test_db_migration_0010_compute.py tests/test_xiaogao_phase1_schema.py tests/test_phase9_return_visit_schema.py tests/test_db_migration_runner.py -q
python -m py_compile app/models.py migrations/postgres/auto_wechat/versions/0012_compute_billing.py
git diff --check
```

- [ ] 提交：

```powershell
git add app/models.py migrations/versions/0031_compute_billing.sql migrations/downgrades/0031_compute_billing.sql migrations/postgres/auto_wechat/versions/0012_compute_billing.py tests/test_phase10_compute_schema.py tests/test_phase10_compute_postgres_contract.py
git diff --cached --check
git commit -m "功能：增加 Phase 10 算力计费快照迁移"
```

### 检查点 A：数据合同复审

必须由 Spec Reviewer 与数据库 Reviewer 双 PASS：

- 历史流水不丢、不伪造 capability；三套餐与六能力不重复。
- SQLite 故障整体回滚，downgrade 后可再 upgrade。
- PostgreSQL 0012 只 ALTER 既有表，revision 链正确。
- 未修改迁移 runner、历史迁移、共享库、Docker 或生产配置。

任一 Must-Fix 单开 `Task 2-FIX`，双 PASS 前不得进入 Task 3。

---

## Task 3：上浮计费核心与内部 usage 严格合同

**文件：**

- Modify: `apps/compute/services.py`
- Modify: `app/services/compute_service.py`
- Modify: `app/schemas.py`
- Modify: `apps/compute/schemas.py`
- Modify: `app/routers/compute.py`
- Modify: `apps/compute/routers.py`
- Modify: `packages/clients/compute_client.py`
- Modify: `tests/test_compute_service.py`
- Modify: `tests/test_compute_router.py`
- Modify: `tests/test_compute_app.py`
- Modify: `tests/test_compute_client.py`

- [ ] 先补红灯，至少覆盖：
  - 实际 1000、3300 基点得到 1330。
  - 实际 1、1 基点向上取整为 2。
  - 比例 disabled 时计费量等于实际量、快照为 0。
  - 非六能力、缺比例行、空 model、超长 model 均不写流水、不改余额。
  - 计费值或新余额超过 BIGINT 时整笔拒绝。
  - 余额不足仍写消费流水并允许负余额。
  - `delta_tokens` 是负计费值，三个新字段保存实际值、能力和比例快照。
  - PostgreSQL 写账户前对该商户账户行使用 `SELECT ... FOR UPDATE`，并发消费不能基于同一旧余额产生丢失更新。
  - `/internal/compute/usage` 与 `/api/compute/internal/usage` 合同一致。

- [ ] 在 `apps/compute/services.py` 增加固定常量和纯函数：

```python
COMPUTE_CAPABILITY_KEYS = (
    "douyin-cs",
    "leads",
    "agents",
    "wechat-assistant",
    "compute",
    "knowledge",
)
BASIS_POINT_DENOMINATOR = 10_000
POSTGRES_INTEGER_MAX = 2_147_483_647
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807


def calculate_billed_tokens(actual_tokens: int, markup_basis_points: int) -> int:
    if actual_tokens <= 0:
        raise ValueError("TOKENS_MUST_BE_POSITIVE")
    if not 0 <= markup_basis_points <= POSTGRES_INTEGER_MAX:
        raise ValueError("MARKUP_OUT_OF_RANGE")
    billed = (
        actual_tokens * (BASIS_POINT_DENOMINATOR + markup_basis_points)
        + BASIS_POINT_DENOMINATOR - 1
    ) // BASIS_POINT_DENOMINATOR
    if billed > POSTGRES_BIGINT_MAX:
        raise ValueError("COMPUTE_VALUE_OUT_OF_RANGE")
    return billed
```

- [ ] `record_usage` 新合同固定为：

```python
def record_usage(
    db: Session,
    merchant_id: str,
    tokens: int,
    *,
    capability_key: str,
    source: str = "llm",
    model: str,
    agent_id: str | None = None,
    conversation_id: int | None = None,
    remark: str | None = None,
) -> ComputeAccount:
    if capability_key not in COMPUTE_CAPABILITY_KEYS:
        raise ValueError("INVALID_CAPABILITY")
    model_name = str(model or "").strip()
    if not model_name or len(model_name) > 128:
        raise ValueError("MODEL_INVALID")
    if source not in USAGE_SOURCES:
        raise ValueError("INVALID_SOURCE")
    ratio = (
        db.query(ComputeMarkupRatio)
        .filter(ComputeMarkupRatio.capability_key == capability_key)
        .one_or_none()
    )
    if ratio is None:
        raise ValueError("MARKUP_RATIO_NOT_FOUND")
    effective_markup = ratio.markup_basis_points if ratio.enabled else 0
    billed_tokens = calculate_billed_tokens(tokens, effective_markup)
    account = get_or_create_account(db, merchant_id)
    _write_transaction(
        db,
        account,
        transaction_type=CONSUME_TYPE,
        delta_tokens=-billed_tokens,
        source=source,
        remark=remark,
        model=model_name,
        agent_id=agent_id,
        conversation_id=conversation_id,
        actual_tokens=tokens,
        capability_key=capability_key,
        markup_basis_points=effective_markup,
    )
    return account
```

其中 `tokens` 继续作为内部协议字段以减少兼容改动，但语义已冻结为实际字符量。服务必须读取唯一比例行、计算计费量、预检新余额范围，再一次 commit 写账户和流水；负余额只写稳定 warning，不抛余额不足。`_write_transaction` 必须重新查询账户并调用 `with_for_update()`，让 PostgreSQL 的充值、发放和消费共用同一行锁；SQLite 继续依赖本地写事务，不另造全局进程锁。

- [ ] `_write_transaction` 增加 `actual_tokens/capability_key/markup_basis_points` 尾参数；充值和套餐调用保持三个值为空。

- [ ] `ComputeUsageRequest` 使用 `extra="forbid"`，`capability_key` 为六值 `Literal`，`model` 必填且 1-128 字符，`source` 限 `llm/embedding/other`。`ComputeTransactionOut` 返回三个新字段，历史空值必须可序列化。

- [ ] 9000 与 9205 两条内部路由都传递 capability/model；错误稳定映射为 400/422，绝不把 SQL 异常或原始输入回显。

- [ ] `packages/clients/compute_client.py::report_usage` 同步把 `capability_key` 与必填 `model` 放入 payload，不改变现有 URL 和鉴权头。

- [ ] 运行：

```powershell
python -m pytest tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_models.py tests/test_phase10_compute_schema.py -q
python -m py_compile apps/compute/services.py app/services/compute_service.py app/schemas.py apps/compute/schemas.py app/routers/compute.py apps/compute/routers.py packages/clients/compute_client.py
git diff --check
```

- [ ] 提交：

```powershell
git add apps/compute/services.py app/services/compute_service.py app/schemas.py apps/compute/schemas.py app/routers/compute.py apps/compute/routers.py packages/clients/compute_client.py tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_client.py
git commit -m "功能：实现小高算力按字符上浮计费"
```

---

## Task 4：六能力上浮管理 API 与精确权限

**文件：**

- Modify: `app/schemas.py`
- Modify: `apps/compute/schemas.py`
- Modify: `apps/compute/services.py`
- Modify: `app/services/compute_service.py`
- Modify: `app/routers/compute.py`
- Modify: `apps/compute/dependencies.py`
- Modify: `apps/compute/routers.py`
- Create: `tests/test_phase10_compute_markup_api.py`

- [ ] 红灯固定以下路由：

```text
GET /admin/compute/markup-ratios
PUT /admin/compute/markup-ratios/{capability_key}
GET /api/compute/admin/markup-ratios
PUT /api/compute/admin/markup-ratios/{capability_key}
```

- [ ] 固定权限矩阵：
  - 精确权限 `auto_wechat:admin:compute_config` 可读写。
  - `super_admin` 与本地 mock 鉴权继续可读写。
  - 只有 `auto_wechat:compute`、普通商户或其他 admin 权限均返回 403。
  - 前端不能直连 9205；9205 只信任 gateway 注入的权限头。

- [ ] DTO 固定：

```python
class ComputeMarkupRatioUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    markup_basis_points: int = Field(..., ge=0, le=2_147_483_647)
    enabled: bool


class ComputeMarkupRatioOut(BaseModel):
    id: int
    capability_key: Literal[
        "douyin-cs", "leads", "agents", "wechat-assistant", "compute", "knowledge"
    ]
    markup_basis_points: int
    enabled: bool
    model_config = {"from_attributes": True}


class ComputeMarkupRatioListResponse(BaseModel):
    success: bool = True
    data: list[ComputeMarkupRatioOut]
    message: str = "success"


class ComputeMarkupRatioResponse(BaseModel):
    success: bool = True
    data: ComputeMarkupRatioOut
    message: str = "success"
```

- [ ] 服务只允许 list/update 已有六行，不提供 create/delete，不允许改 `capability_key`。列表按冻结六能力顺序返回；缺行视为配置漂移并返回稳定错误，不自动补写。

- [ ] `apps/compute/dependencies.py` 新增 `require_compute_config_admin`，判断 `super_admin` 或精确权限；现有套餐、充值、发放的 `require_super_admin` 行为不顺手改变。

- [ ] 测试 0、3300、2_147_483_647 可保存；负数、超技术边界、未知 capability、额外字段被拒绝。更新后新 usage 使用新比例，旧流水快照不变化。

- [ ] 运行：

```powershell
python -m pytest tests/test_phase10_compute_markup_api.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_service.py tests/test_auth_context.py -q
git diff --check
```

- [ ] 提交：

```powershell
git add app/schemas.py apps/compute/schemas.py apps/compute/services.py app/services/compute_service.py app/routers/compute.py apps/compute/dependencies.py apps/compute/routers.py tests/test_phase10_compute_markup_api.py
git commit -m "功能：增加六能力算力上浮配置接口"
```

---

## Task 5：9100 按字符计量与全部现有 AI 埋点

**文件：**

- Modify: `apps/xg_douyin_ai_cs/services/compute_usage_client.py`
- Modify: `apps/xg_douyin_ai_cs/schemas.py`
- Modify: `apps/xg_douyin_ai_cs/services/reply_decision_service.py`
- Modify: `apps/xg_douyin_ai_cs/services/daily_report_summary_service.py`
- Modify: `apps/xg_douyin_ai_cs/services/return_visit_judge_service.py`
- Modify: `apps/xg_douyin_ai_cs/services/knowledge_training_service.py`
- Modify: `apps/xg_douyin_ai_cs/rag/repository.py`
- Modify: `tests/test_compute_usage_client.py`
- Modify: `tests/test_xg_douyin_ai_cs_app.py`
- Modify: `tests/test_xg_douyin_ai_cs_daily_report_summary.py`
- Modify: `tests/test_phase9_return_visit_judge.py`
- Modify: `tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py`
- Modify: `tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py`
- Modify: `tests/test_xg_douyin_ai_cs_rag.py`
- Create: `tests/test_phase10_compute_metering.py`
- Create: `tests/test_phase10_compute_no_network.py`

- [ ] 先写红灯证明：
  - 中文、ASCII、换行均按 Python 字符数精确计量。
  - provider `usage.total_tokens=999999` 与字符数冲突时仍使用字符数。
  - 回复决策发生两次 chat 时产生两次独立 usage。
  - 日报、回访、知识问答各上报一次正确能力。
  - 每次真实知识库 embedding 成功都按输入字符数上报；mock embedding 不上报。
  - 缺可信 merchant_id 时不伪造商户、不调用 usage。
  - usage 上报异常不改变原 AI 返回或既有 fallback。
  - payload、日志不包含提示词、销售回复、模型输出或知识片段原文。

- [ ] 在 `compute_usage_client.py` 提供唯一计量 helper，避免各调用点重复算法：

```python
def count_chat_characters(messages: list[dict], reply_text: str) -> int:
    return sum(
        len(item["content"])
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    ) + len(reply_text)


def count_embedding_characters(text: str) -> int:
    return len(text)
```

`ComputeUsageClient.report_usage` 增加必填 `capability_key` 和 `model`；仍保持“成功 True，跳过/失败 False，绝不抛异常”。日志只写 merchant_id、字符数、capability、model、状态，不写原文。

- [ ] `ReplySuggestionRequest.merchant_id` 删除现有 `"demo_bba"` 默认值，改为必填、1-128 字符；日报、回访和知识请求已经是必填，保持不变。9000 proxy 回归必须证明 merchant_id 来自登录态/绑定后的内部请求，而不是 9100 自行补默认商户。

- [ ] Chat 调用必须在每次 `client.chat(messages)` 成功返回后立即上报，再做 JSON 解析或业务判断。这样模型拒答、格式错误和重试均按真实成功调用计量，网络异常不计量。

- [ ] 替换现有 `_report_llm_usage` 的 provider token 逻辑；`reply_decision_service.py`、`daily_report_summary_service.py` 中不得再用 `usage.total_tokens` 决定扣费。

- [ ] `return_visit_judge_service.py` 使用请求中的可信 `merchant_id`，capability 固定 `wechat-assistant`；不得把 `sales_reply_text` 放进 usage payload 或日志。

- [ ] `knowledge_training_service.py` 在问答 chat 成功后按 `knowledge/llm` 上报。`rag/repository.py` 提取一个 `_embed_with_usage` 窄 helper，所有训练和查询 embedding 调用统一经过它；helper 需要显式 merchant_id，`mock_for_test_only` 直接跳过。

- [ ] 安装网络哨兵：

```python
def forbid_network(*args, **kwargs):
    raise AssertionError("Phase 10 自动测试禁止真实网络")

monkeypatch.setattr("urllib.request.urlopen", forbid_network)
monkeypatch.setattr("requests.sessions.Session.request", forbid_network)
```

具体用例只允许用局部 stub 替换 LLM、Embedding 和 usage HTTP；不得通过关闭测试来绕过哨兵。

- [ ] 运行：

```powershell
python -m pytest tests/test_compute_usage_client.py tests/test_phase10_compute_metering.py tests/test_phase10_compute_no_network.py tests/test_xg_douyin_ai_cs_app.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_xg_douyin_ai_cs_rag.py tests/test_douyin_ai_cs_proxy.py -q
python -m py_compile apps/xg_douyin_ai_cs/services/compute_usage_client.py apps/xg_douyin_ai_cs/schemas.py apps/xg_douyin_ai_cs/services/reply_decision_service.py apps/xg_douyin_ai_cs/services/daily_report_summary_service.py apps/xg_douyin_ai_cs/services/return_visit_judge_service.py apps/xg_douyin_ai_cs/services/knowledge_training_service.py apps/xg_douyin_ai_cs/rag/repository.py
rg -n "usage\.total_tokens|total_tokens" apps/xg_douyin_ai_cs/services/reply_decision_service.py apps/xg_douyin_ai_cs/services/daily_report_summary_service.py apps/xg_douyin_ai_cs/services/return_visit_judge_service.py apps/xg_douyin_ai_cs/services/knowledge_training_service.py
git diff --check
```

最后一条 `rg` 预期零命中；供应商 usage 可继续存在于 `llm/client.py`，但不得参与四个业务服务计费。

- [ ] 提交：

```powershell
git add apps/xg_douyin_ai_cs/services/compute_usage_client.py apps/xg_douyin_ai_cs/schemas.py apps/xg_douyin_ai_cs/services/reply_decision_service.py apps/xg_douyin_ai_cs/services/daily_report_summary_service.py apps/xg_douyin_ai_cs/services/return_visit_judge_service.py apps/xg_douyin_ai_cs/services/knowledge_training_service.py apps/xg_douyin_ai_cs/rag/repository.py tests/test_compute_usage_client.py tests/test_xg_douyin_ai_cs_app.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_xg_douyin_ai_cs_rag.py tests/test_phase10_compute_metering.py tests/test_phase10_compute_no_network.py
git commit -m "功能：补齐现有 AI 操作算力字符埋点"
```

### 检查点 B：计费与全埋点复审

必须由 Spec Reviewer、Code Quality Reviewer、Security Reviewer 三方 PASS：

- Spec：字符公式、向上取整、快照、六能力映射、余额不拦截符合 0.2。
- Quality：每次 retry 单独计量；服务错误不污染 AI 主流程；历史流水和旧客户端兼容边界明确。
- Security：merchant_id 来自可信内部请求；usage payload/日志无原文；真实 LLM、Embedding、9000 网络调用均为 0。
- 静态枚举所有生产 `.chat()`/`.embed()` 调用点，确认没有当前可信场景漏埋，也没有给脚本或 mock 伪造消耗。

任一 Must-Fix 单开 `Task 3-5-FIX`，三方 PASS 前不得进入 Task 6。

---

## Task 6：商户流水与超管上浮配置前端闭环

**文件：**

- Modify: `frontend/src/api/compute.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/features/compute/pages/ComputeCenter.tsx`
- Modify: `frontend/src/features/compute/pages/SuperComputeConfig.tsx`
- Create: `frontend/scripts/check-phase10-compute-contract.mjs`
- Modify: `frontend/package.json`

- [ ] 先写静态合同脚本并运行红灯。脚本必须断言：
  - API 层存在两个冻结的 9000 管理路径。
  - `ComputeTransaction` 有 `actual_tokens/capability_key/markup_basis_points`。
  - 超管页读取、编辑六能力比例；商户页展示实际量与计费量。
  - 前端源码不出现 `/api/compute/admin/markup-ratios`、internal token 或 9100/9205 直连地址。

- [ ] 类型与 API：

```typescript
export type ComputeCapabilityKey =
  | "douyin-cs"
  | "leads"
  | "agents"
  | "wechat-assistant"
  | "compute"
  | "knowledge";

export interface ComputeMarkupRatio {
  id: number;
  capability_key: ComputeCapabilityKey;
  markup_basis_points: number;
  enabled: boolean;
}

export interface ComputeMarkupRatioUpdateRequest {
  markup_basis_points: number;
  enabled: boolean;
}
```

新增 `fetchAdminComputeMarkupRatios()` 与 `updateAdminComputeMarkupRatio()`，只调用 `/admin/compute/markup-ratios`。

- [ ] `SuperComputeConfig.tsx` 在既有套餐区旁增加一个不嵌套卡片的“能力上浮比例”区：
  - 固定六行和中文能力标签。
  - 百分比输入保存为字符串，接受非负整数或最多两位小数；使用字符串算法转为基点，禁止浮点误差。
  - 每行使用开关控制 enabled，保存按钮只提交该行。
  - 不设置 100%/1000% 产品上限；超过后端技术边界时显示后端稳定错误。
  - 加载、空、失败、保存中和保存成功状态完整；失败不覆盖原值。

- [ ] `ComputeCenter.tsx` 的消费流水显示能力中文名、model、实际字符量和计费消耗；历史 `capability_key=NULL` 显示“历史未归类”，充值/套餐行不伪造实际量。余额为负时显示风险提示，但不写“服务已停用”。

- [ ] `package.json` 增加：

```json
"phase10-compute:check": "node scripts/check-phase10-compute-contract.mjs"
```

- [ ] 运行：

```powershell
Set-Location frontend
npm run phase10-compute:check
npx tsc -b
npm run build
Set-Location ..
git diff --check
```

- [ ] 提交：

```powershell
git add frontend/src/api/compute.ts frontend/src/api/types.ts frontend/src/features/compute/pages/ComputeCenter.tsx frontend/src/features/compute/pages/SuperComputeConfig.tsx frontend/scripts/check-phase10-compute-contract.mjs frontend/package.json
git commit -m "功能：完成小高算力上浮配置前端闭环"
```

---

## Task 7：本地模拟总验收与阶段固化

> **完成状态（2026-07-15）：Task 7 已完成（提交 `47884ba`），Phase 10 终态 `DONE_WITH_CONCERNS`（唯一 concern = `baota_production_compute_not_verified`，不阻塞 Phase 12/13）。"发起三方评审"待人工 Spec/Code Quality/Security 复审。**

**文件：**

- Create: `docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md`
- Modify: `tests/test_phase10_compute_no_network.py`（仅当总验收发现覆盖缺口时，先红灯再补）

- [x] 后端专项：

```powershell
python -m pytest tests/test_phase10_compute_schema.py tests/test_phase10_compute_postgres_contract.py tests/test_phase10_compute_markup_api.py tests/test_phase10_compute_metering.py tests/test_phase10_compute_no_network.py tests/test_compute_models.py tests/test_compute_service.py tests/test_compute_router.py tests/test_compute_app.py tests/test_compute_client.py tests/test_compute_usage_client.py -q
```

- [x] AI 相邻回归：

```powershell
python -m pytest tests/test_xg_douyin_ai_cs_app.py tests/test_xg_douyin_ai_cs_daily_report_summary.py tests/test_phase9_return_visit_judge.py tests/test_phase9_return_visit_internal_api.py tests/test_phase9_return_visit_no_network.py tests/test_xg_douyin_ai_cs_rag.py tests/test_xg_douyin_ai_cs_rag_workflow.py tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py tests/test_xg_douyin_ai_cs_embedding_ark.py tests/test_douyin_ai_cs_proxy.py -q
```

- [x] 迁移回归：

```powershell
python -m pytest tests/test_db_migration_0010_compute.py tests/test_xiaogao_phase1_schema.py tests/test_phase9_return_visit_schema.py tests/test_db_migration_runner.py tests/test_sqlite_specific_usage_guard.py -q
```

- [x] 前端：

```powershell
Set-Location frontend
npm run phase10-compute:check
npm run encoding:check
npx tsc -b
npm run build
Set-Location ..
```

- [x] 静态硬门禁：

```powershell
git diff --check
git diff --check 265d719..HEAD
rg -n "https?://|OPENAI_API_KEY|ARK_API_KEY" tests/test_phase10_compute_*.py
rg -n "usage\.total_tokens|total_tokens" apps/xg_douyin_ai_cs/services/reply_decision_service.py apps/xg_douyin_ai_cs/services/daily_report_summary_service.py apps/xg_douyin_ai_cs/services/return_visit_judge_service.py apps/xg_douyin_ai_cs/services/knowledge_training_service.py
git diff --unified=0 265d719..HEAD -- app/models.py app/schemas.py apps/compute apps/xg_douyin_ai_cs frontend/src/features/compute | Select-String '^\+[^+].*(ad_review|ai_edit|input_writer|poll-and-send-report)'
```

预期：第一条无空白错误；第二条只允许测试哨兵使用的虚构 `.test` URL，禁止真实域名或密钥；后两条零命中。

- [x] 对已知无关失败采用起点对照，不修改 Phase 10 白名单外文件。回传必须列出“起点同样失败”的命令和结果，不能只写 pre-existing。

- [x] 生成验收文档，精确记录：
  - 提交链和文件范围。
  - 字符计量、比例、快照、能力映射和权限合同。
  - 后端、迁移、前端测试数量。
  - 真实 LLM/Embedding/抖音/宝塔/生产数据库调用均为 0。
  - Phase 10 代码与模拟闭环 `DONE`。
  - Phase 10 总状态 `DONE_WITH_CONCERNS`，唯一 Phase 10 concern 为 `baota_production_compute_not_verified`。
  - 该 concern 不阻塞 Phase 12/13；统一宝塔验证只能在 Phase 13 完成后另开执行包。
  - Phase 9、Phase 8-B、Phase 11、日报真实分发状态保持 0.1，不得改写。

- [ ] 发起最终 Spec、Code Quality、Security 三方评审；任一 Must-Fix 必须修复并重跑对应测试后再更新验收文档。

- [x] 提交验收：

```powershell
git add docs/ai/05_acceptance/PHASE10_COMPUTE_ACCEPTANCE.md
if (Test-Path tests/test_phase10_compute_no_network.py) {
  git add tests/test_phase10_compute_no_network.py
}
git diff --cached --check
git commit -m "测试：固化 Phase 10 小高算力模拟验收"
```

**最终硬暂停：** 不启动服务、不连接宝塔、不执行真实迁移、不进入任何真实 AI/抖音验证。回传 Phase 10 最终报告后，等待审批窗口制定下一有效阶段执行包。

---

## 8. 完成定义

Phase 10 只有同时满足以下条件才可结束：

- 三套餐和六能力 seed 经临时库验证幂等，没有重复建设。
- usage 强制可信 merchant、六能力、model、实际字符量；供应商 token 不参与计费。
- 上浮向上取整，流水同时保存实际、比例快照和计费值；历史流水不伪造能力。
- 余额不足不阻断，技术溢出不产生半写入。
- 当前五类 AI 操作全部埋点，重试逐次计量，Mock/失败不扣费。
- 上浮配置仅精确权限或超管可改；普通商户不能越权。
- 商户和超管页面完成真实 API 闭环，支付仍为 mock。
- SQLite/PG 合同、后端、AI 相邻回归、前端合同/类型/构建全部通过。
- 全部测试真实外部网络调用为 0；宝塔验证保持未启动。

未满足任何一项时不得用“时间紧”跳过，也不得把生产验证缺失误写为本地代码阻塞。
