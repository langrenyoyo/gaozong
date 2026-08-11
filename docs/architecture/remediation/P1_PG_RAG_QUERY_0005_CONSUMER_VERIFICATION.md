# P1-PG-RAGQ-0005 — RAG Query Consumer PostgreSQL 验证报告

> 任务：`P1-PG-RAGQ-0005 — xg_douyin_ai_cs RAG Query Consumer PostgreSQL Verification`
> 所属：`P1 COMPUTE-IDEMPOTENCY-001 — TECHNICAL_CLOSURE` 的剩余 consumer-level PG verification
> 基线 commit：`803a452`（验证：闭环AI回复预览0034 PostgreSQL幂等计费）
> 日期：2026-08-11
> 窗口：P1-PG-RAGQ-0005 RAG Query Consumer PG 验证执行/验证窗口
> Source of Truth：真实 PG runtime 证据（双库：xg_douyin_ai_cs execution 库 + auto_wechat compute ledger 库，真实 consumer 调用链 + 应用角色） > 冻结文档 > 推测

---

## 结论速览

| Gate | 结论 |
|---|---|
| RQ-0 Git / environment | ✅ PASS |
| RQ-1 9100 PG environment | ✅ PASS（0004→0005 upgrade 执行，before=0004 / after=0005）|
| RQ-2 9100 runtime principal | ✅ PASS（RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED）|
| RQ-3 9000 compute ledger preconditions | ✅ PASS |
| RQ-4 Business Event Identity | ✅ PASS（无 CONTRACT_DRIFT）|
| RQ-5 Migration 0005 / schema | ✅ PASS（STATIC_SCHEMA_VERIFIED + runtime apply）|
| RQ-6 Q-A first execution | ✅ PASS |
| RQ-7 Q-A same-stage replay（NO_DOUBLE_CHARGE）| ✅ PASS |
| RQ-8 Q-B distinct execution | ✅ PASS |
| RQ-9 stage separation（primary + fallback_embedding）| ✅ PASS |
| RQ-10 non-null identity | ✅ PASS |
| RQ-11 execution persistence | ✅ PASS |
| RQ-12 transaction / balance closure | ✅ PASS |
| RQ-13 cleanup / residual | ✅ PASS（residual=0）|

**Verdict（候选）**：`RAG QUERY 0005 CONSUMER: PG_VERIFICATION_COMPLETE_PENDING_APPROVAL`

Business Event Identity：`rag_search_execution:{search_execution_id}:{embedding_stage}`（与冻结 contract 一致，当前代码无 drift）。

```text
RAG_EXECUTION_DB_RUNTIME_PRINCIPAL: xg_douyin_ai_cs
COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED: auto_wechat
```

---

## 1. Baseline

```text
HEAD = 803a4522d1f6f460db86bf842d62cd9b70fc6df6（验证：闭环AI回复预览0034 PostgreSQL幂等计费）
worktree = clean（验证前无未提交改动）
```

前置状态：

```text
DB-BL                       = REPAIR_VERIFIED / COMPLETE
AUTO_WECHAT_DEV_PG          = CANONICAL_ALEMBIC_BASELINE@0034
APPLICATION_ROLE_PERMISSION_GAP = RESOLVED — LOCAL DEVELOPMENT
0032 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED
0033 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED
0034 = PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED
RAG Query 0005 = PENDING_PG_VERIFICATION / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT（本轮验证目标）
P1 = COMPUTE-IDEMPOTENCY-001 OPEN / TECHNICAL_CLOSURE=PENDING
```

---

## 2. Historical Blocker

此前 0005 曾被错误宣称为已验证（identity 设计文档末尾"Stage 5H-2 实施落记"写 `0005 PG = PG_VERIFIED`），随后正式纠正为：

```text
PENDING_PG_VERIFICATION
BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT
```

checkpoint 11/11（`P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md`）Charge Path #11 的权威状态为 `PENDING_PG_VERIFICATION / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT`，Blocker B 明确下一步："待 Docker Desktop 恢复后独立补：0004→0005 upgrade + table/PK/CHECK/索引 + SearchExecution lifecycle"。

本轮避免的错误模式：**静态代码存在 + migration 存在 = PG runtime verified**。本轮以真实 runtime 证据为准，不套用 0032/0034 模板，独立从当前代码重新核验 identity。

本轮实测发现：**Docker 已恢复**（`auto-wechat-postgres-dev` Up 23h healthy），但 9100 PG runtime 实际落后：
- PG `xg_douyin_ai_cs` 库 `alembic_version = 0004`（head=0005，0005 未 apply）
- `to_regclass('rag_search_executions')` = 空（表不存在）
- 9100 本地 `.env.lan.local` `RAG_DATABASE_URL=sqlite:///...`（连 SQLite，不连 PG）

经用户授权（upgrade + 完整 runtime 验证），本轮执行 alembic upgrade 0004→0005 后补齐 runtime 证据。

---

## 3. Dual Database Reality

本轮第一件事独立确认双库归属，不假设相同：

```text
DB-A: RAG Query execution 持久化
  database = xg_douyin_ai_cs
  owner    = xg_douyin_ai_cs 角色
  engine   = 9100 get_rag_engine()（RAG_DATABASE_URL）
  对象     = rag_search_executions 表（migration 0005）

DB-B: compute ledger / balance 持久化
  database = auto_wechat
  owner    = postgres
  app principal = auto_wechat（已 PG_RUNTIME_VERIFIED）
  engine   = 9000（DATABASE_URL）
  对象     = compute_transactions / compute_accounts（migration 0030）
```

RAG Query 跨双库：execution identity 在 DB-A 创建持久化，billing 在 DB-B 原子扣费。两库不同 database、不同 owner、不同 application principal。

---

## 4. 9100 Environment / Principal（RQ-1 / RQ-2）

### RQ-1 9100 PG Environment Revalidation

```text
container/service  = auto-wechat-postgres-dev (Up 23h, healthy)
backend            = PostgreSQL 16.x
database (DB-A)    = xg_douyin_ai_cs
runtime principal  = xg_douyin_ai_cs（非 superuser / 非 postgres）
PG network         = 127.0.0.1:5432（宿主机直连，psycopg）

migration graph    = 0001→0002→0003→0004→0005（单链，head=0005）
MIGRATION_0005_EXISTS = True
RUNTIME_DATABASE_HAS_APPLIED_REQUIRED_SCHEMA:
    before = 0004（rag_search_executions 表不存在）
    after  = 0005（rag_search_executions 表存在，本轮 upgrade 执行）
```

alembic upgrade 0004→0005 执行记录（用 `xg_douyin_ai_cs` 角色从仓库根运行，env.py 读 `RAG_DATABASE_URL`）：

```text
$ RAG_DATABASE_URL=postgresql+psycopg://xg_douyin_ai_cs:change_me@127.0.0.1:5432/xg_douyin_ai_cs \
    python -m alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini current
  0004
$ ... upgrade head
  （无报错输出）
$ ... current
  0005 (head)
```

**0005 migration 存在 ≠ current 是 0005**——本轮实测验证了这一区分：upgrade 前 current=0004（表不存在），upgrade 后 current=0005（表存在）。

### RQ-2 9100 Runtime Principal Reality

独立确认 9100 RAG execution DB 的 runtime principal，不机械套用 9000 已批准的 `auto_wechat` application-role contract：

```text
9100 runtime database principal = xg_douyin_ai_cs

current_user        = xg_douyin_ai_cs
SUPERUSER?          = False（rolsuper=f）
database owner?     = xg_douyin_ai_cs（pg_databaseowner）
schema CREATE?      = True（public schema CREATE 隐式持于 pg_database_owner 成员）
required DML?       = INSERT/SELECT/UPDATE/DELETE on rag_search_executions ✅
                     TRUNCATE/REFERENCES/TRIGGER 也持有（权限较 auto_wechat 更宽）
table owner         = xg_douyin_ai_cs（rag_search_executions）
```

**9100 application-role model 与 9000 不同**：9000 的 `auto_wechat` 角色已独立审批为 DML-only / CREATE=false / TRUNCATE DENIED 的最小权限 application-role model（`P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md`，APPROVED）。9100 的 `xg_douyin_ai_cs` 角色**未单独审批 application-role model**——本窗口不顺手设计新的 9100 role model（NO BUSINESS CODE CHANGE，任务第 6 节约束）。

本轮使用 9100 当前真实 local runtime 配置所对应的 principal（`xg_douyin_ai_cs`）执行 RAG consumer，如实记录：

```text
RAG EXECUTION DB RUNTIME PRINCIPAL: xg_douyin_ai_cs
Evidence: RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED
```

本窗口**不**写 `APPLICATION_ROLE_RUNTIME_VERIFIED`（9100 侧无已批准的 application-role model 与本轮 runtime 证据配对）。9000 compute ledger 侧沿用已批准的 `auto_wechat` application principal（见 RQ-3 / RQ-12）。

```text
NOT SQLite / NOT postgres-as-consumer（execution 写入经 xg_douyin_ai_cs 角色）/ NOT staging / NOT production
```

---

## 5. 9000 Compute Preconditions（RQ-3）

RAG Query usage 经 9100 `ComputeUsageClient` HTTP 上报到 9000 compute 服务。复用已正式批准的 `auto_wechat` canonical PG@0034 + application principal：

```text
environment        = LOCAL DEVELOPMENT ONLY
container          = auto-wechat-postgres-dev
database (DB-B)    = auto_wechat
revision           = 0034
physical tables    = 61
database owner     = postgres
application principal = auto_wechat（已 PG_RUNTIME_VERIFIED + APPLICATION_ROLE_RUNTIME_VERIFIED）
PG network         = 127.0.0.1:5432

APPLICATION_ROLE_PERMISSION_GAP = RESOLVED — LOCAL DEVELOPMENT
```

幂等前置对象（`postgres` catalog inspection）：

| 对象 | 核验 |
|---|---|
| `compute_transactions` UNIQUE `uk_compute_transactions_merchant_idempotency` | ✅ UNIQUE (merchant_id, idempotency_key) |
| `compute_transactions.idempotency_key` 列 | ✅ varchar(255) nullable |
| `compute_transactions.payload_evidence` 列 | ✅ text nullable |
| `compute_markup_ratios` 行 `knowledge` | ✅ enabled=true / markup_basis_points=0 / consumption_mode=actual / fixed_tokens_per_call=NULL |
| `compute_markup_ratios` 行 `douyin-cs` | ✅（对照存在） |
| `auto_wechat` 角色 DML on compute_transactions/compute_accounts | ✅ INSERT/SELECT/UPDATE/DELETE |

RAG embedding 用 `capability_key="knowledge"`（非 `douyin-cs`），`usage_measurement_method="estimated_tokens"`（`count_embedding_characters=len(text)`，非 provider_tokens）。`knowledge` 行 consumption_mode=actual / markup=0 → `billed_tokens = calculate_billed_tokens(len(text), 0) = len(text)`。

9000 `/ready`（以 `auto_wechat` 应用角色）：HTTP 200 / `backend=postgresql / db_connect=pass / database_name=auto_wechat`。9000 启动日志确认 `db_schema stage=startup_skip_create_all backend=postgresql`（PG 分支不调 create_all，满足 CLAUDE.md 硬约束 #2）。

---

## 6. Static Consumer Chain（RQ-4）

以当前代码重新建立（非复制旧报告），真实文件/函数。**关键事实：RAG Query 是 9100 内部 RAG 能力**——execution identity 在 9100 创建（与 0034 Preview 的 9000 创建不同），usage 经 9100→9000 单 hop HTTP 上报（与 0032 Daily Report 同模式）。

```text
9100 POST /rag/search                       apps/xg_douyin_ai_cs/routers/rag.py:38
  → require_internal_service_token           dependencies.py:18（X-Internal-Service-Token == XG_DOUYIN_AI_CS_SERVICE_TOKEN）
  → :40 repository.search(payload)           repository.py:953
    → search_with_diagnostics(payload)      repository.py:923  [统一入口]
      → :929 _create_search_execution(merchant_id, query)   [RQ-0 durable before embedding]
        → :1063-1081 INSERT INTO rag_search_executions(...) RETURNING id + conn.commit()
        → return int(row["id"])             [PG 自增 PK = durable execution identity]
      → :935-941 SQLite-only 分支：_search_sqlite(embedding_stage="primary")  [R1: SQLite-only=primary]
      → :931-934 Milvus 分支：_search_milvus_or_fallback_with_diagnostics(execution_id=...)
      → :945 _finalize_search_execution(execution_id, "completed")  [C1: lifecycle=整次请求结果]
      → :949 except → _finalize(..., "failed")

_search_sqlite(payload, *, execution_id, embedding_stage)  repository.py:1231
  → :1270-1276 if query_embedding is None:
      _run_embed_with_hard_timeout(client, text, merchant_id, remark,
                                   search_execution_id=execution_id, embedding_stage=embedding_stage)
        → _worker（daemon 线程）repository.py:439
          → _embed_with_usage(client, text, merchant_id, remark,
                              search_execution_id=execution_id, embedding_stage=embedding_stage)
            repository.py:469
            → :494-516 identity matrix 严格互斥判定
              → :502 query_count==2 and ingest_count==0
                → :504 idempotency_key = f"rag_search_execution:{search_execution_id}:{embedding_stage}"
            → :518 client.embed(text)                 [★ 唯一 mock 边界：外部 embedding API]
            → :520-521 if model != "mock_for_test_only" and merchant_id:
                  tokens = count_embedding_characters(text)   [len(text)]
            → :523-533 ComputeUsageClient().report_usage(
                  source="embedding", capability_key="knowledge",
                  usage_measurement_method="estimated_tokens", llm_call_stage=None,
                  idempotency_key=...)             [9100→9000 HTTP]
                → apps/xg_douyin_ai_cs/services/compute_usage_client.py:199 report_usage()
                  → :163 base_url=os.environ["AUTO_WECHAT_9000_BASE_URL"]
                  → :172 USAGE_PATH="/internal/compute/usage"
                  → POST {base_url}/internal/compute/usage（payload 含 idempotency_key，X-Internal-Token）
                    → app/routers/compute.py:458 internal_router.post("/compute/usage")
                      → :463 _require_internal（X-Internal-Token 校验）
                      → :482 compute_service.record_usage(idempotency_key=payload.idempotency_key)
                        → apps/compute/services.py:615 record_usage()
                          → :681-689 if idempotency_key: payload_evidence = _compute_payload_evidence(...)
                          → :692-716 db.add(ComputeTransaction(...)) + db.flush()  [INSERT 尝试]
                          → :718-727 flush 成功 → get_or_create_account + _write_transaction_balance_only（原子扣费）+ db.commit()
                          → :728-769 IntegrityError → rollback → 读已存在行
                            → :747 existing.payload_evidence == payload_evidence → idempotent_replay（:756 return）
                            → :757 不同 → idempotency_conflict
                          → PostgreSQL compute_transactions / compute_accounts (auto_wechat 库)
```

Milvus fallback path（`_search_milvus_or_fallback_with_diagnostics` repository.py:1109）：
- :1152-1156 primary embedding（`embedding_stage="primary"`）
- :1219 `fallback_stage = "fallback_embedding" if not query_embedding else None`（query_embedding 复用则 stage=None 不计费；为空才 fallback_embedding）
- :1220-1224 失败回退 `_search_sqlite(query_embedding=已算, embedding_stage=fallback_stage)`

**全程未发现 CONTRACT_DRIFT**：当前代码实际生成的 identity 仍是 `rag_search_execution:{search_execution_id}:{embedding_stage}`（[repository.py:504](../../../apps/xg_douyin_ai_cs/rag/repository.py)），与冻结 contract（`P1_RAG_QUERY_EMBEDDING_IDENTITY_DESIGN.md` + checkpoint 11/11 Charge Path #11）一致。

### Same Execution 真正含义

正式幂等事件 = `search_execution_id` + `embedding_stage`：
- same execution + same stage → dedupe（replay）
- different search_execution_id → independent charge
- same execution + different legitimate billable stage（primary vs fallback_embedding）→ independent charge（RQ-9）

### Replay 路径合法性

RAG Query 的 `/rag/search` 每次调 `search_with_diagnostics` 都新建 execution（re-search = 新 execution = 新合法消费），无法通过对同一 query 再次调 `/rag/search` 复用同一 execution_id。

RAG Query 的 same-execution replay seam 是 consumer 侧 usage-report 路径 `_embed_with_usage` 对同一 `search_execution_id` + 同 `embedding_stage` 再次调用（identity 由 [repository.py:504](../../../apps/xg_douyin_ai_cs/rag/repository.py) f-string 自然重新生成，非手工构造 key，非直接调 `record_usage`）。对应 daemon timeout 后 primary usage report 晚到重发场景（identity 设计 Q5：`_run_embed_with_hard_timeout` 的 daemon 线程在 timeout 前若已完成 `_embed_with_usage`（含 report_usage），则 primary charge 已 committed；timeout 后主流程返回空 embedding 但 daemon 线程继续，usage report 已发出；若 daemon 在 timeout 后才完成，则 primary charge 晚到但仍用同一 key，M07 replay 保护）。

类比 0033 M05 的 same-execution replay：`_report_analysis_usage` 对同一 `execution_id` 再次调用（对应 crash 后 usage report 重试场景）。RAG Query 同模式：`_embed_with_usage` 对同一 `search_execution_id` 同 `embedding_stage` 再次调用。

---

## 7. Execution Identity（RQ-4 cont.）

identity 来源：`rag_search_executions.id`（PG 自增 PK），由 9100 `_create_search_execution`（[repository.py:1063-1081](../../../apps/xg_douyin_ai_cs/rag/repository.py)）在 embedding worker 启动前 durable commit（RQ-0）。

- 非时间戳推导（`datetime.now`/`time.time` 不参与 key 构造，经源码核验）。
- 非随机 UUID per call（`uuid` / `random` 不参与 execution_id 生成，execution_id = PG 序列 `nextval`）。
- 非 HTTP attempt / retry attempt / worker retry number（execution_id 持久在 PG，进程重启/重试后稳定复用）。
- billing truth 归 M07 `ComputeTransaction`（`rag_search_executions` 无 `is_billed`/`billing_status` 字段，经 migration 0005 列定义 + 代码核验：`_create/_finalize_search_execution` 不传 `is_billed`）。
- C4 mixed identity 防护：`run_id`/`document_id`/`chunk_index`（Ingest）与 `search_execution_id`/`embedding_stage`（Query）同时存在 → warning + 退 None（[repository.py:508-516](../../../apps/xg_douyin_ai_cs/rag/repository.py)）。

```text
rag_search_execution:{search_execution_id}:{embedding_stage}
```

与冻结 contract 一致，无 drift。

---

## 8. embedding_stage Contract（RQ-4 cont.）

当前所有 active billable embedding_stage（从代码实际调用点核验，非从旧设计猜）：

| stage | 生成位置 | 触发条件 |
|---|---|---|
| `primary` | [repository.py:940](../../../apps/xg_douyin_ai_cs/rag/repository.py)（SQLite-only）/ [repository.py:1155](../../../apps/xg_douyin_ai_cs/rag/repository.py)（Milvus）| 首次 query embedding |
| `fallback_embedding` | [repository.py:1219](../../../apps/xg_douyin_ai_cs/rag/repository.py) | Milvus fallback 且 primary embedding 为空（超时）时重新 embedding |

cardinality = 1 SearchExecution : up to 2 embedding charge events（primary + fallback_embedding）。

**存在 2 个 active legitimate billable embedding stage** → RQ-9 Stage Separation **适用**（非 N/A）。

注意：`embedding_stage` ≠ `compute_transactions.llm_call_stage` 列。RAG embedding 上报 `llm_call_stage=None`（[repository.py:531](../../../apps/xg_douyin_ai_cs/rag/repository.py)），stage 信息编码进 `idempotency_key` 而非 `llm_call_stage` 列。`llm_call_stage` 受控值 `LLM_CALL_STAGES = primary/retry_known_customer/retry_phone_goal/retry_combined`（[apps/compute/services.py:35-40](../../../apps/compute/services.py)）用于 LLM chat consumer（如 0034 Preview），不适用于 embedding consumer。

---

## 9. Business Event Identity（RQ-4 cont.）

真实生成代码 [apps/xg_douyin_ai_cs/rag/repository.py:494-516](../../../apps/xg_douyin_ai_cs/rag/repository.py)：

```python
# P1 Stage 5H-2：identity matrix 严格互斥判定（R3）
ingest_args = [run_id, document_id, chunk_index]
query_args = [search_execution_id, embedding_stage]
ingest_count = sum(1 for v in ingest_args if v is not None)
query_count = sum(1 for v in query_args if v is not None)
if ingest_count == 3 and query_count == 0:
    idempotency_key = f"rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest"
elif query_count == 2 and ingest_count == 0:
    idempotency_key = f"rag_search_execution:{search_execution_id}:{embedding_stage}"
elif ingest_count == 0 and query_count == 0:
    idempotency_key = None
else:
    # partial or mixed → identity contract violation，显式 warning 不构造畸形 key
    _logger.warning("rag_embed stage=identity_violation ...")
    idempotency_key = None
```

不变式（3 条，来自 identity 设计文档）：
1. same execution + same stage billing replay → same key → REPLAY
2. same execution + different stage（primary vs fallback_embedding）→ different key → up to 2 charges
3. explicit new search request → NEW execution → NEW key（合法新消费）

---

## 10. Migration 0005 / Schema（RQ-5）

canonical PG@0005（upgrade 后）中确认 0005 所需对象真实存在（`postgres` catalog inspection）：

| 对象 | 来源 | 核验 |
|---|---|---|
| `rag_search_executions` 表 | migration 0005 `op.create_table` | ✅ EXISTS（6 列）|
| `id` integer PK + `rag_search_executions_pkey` | 0005 sa.Column primary_key | ✅ autoincrement `nextval('rag_search_executions_id_seq')` |
| `merchant_id` varchar(128) NOT NULL | 0005 | ✅ |
| `query` text NOT NULL | 0005 | ✅ |
| `lifecycle_status` varchar(20) NOT NULL default 'running' | 0005 server_default | ✅ |
| `created_at` timestamptz NOT NULL default now() | 0005 | ✅ |
| `completed_at` timestamptz nullable | 0005 | ✅ |
| `ck_rag_search_executions_status` CHECK | 0005 lifecycle_status ∈ (running/completed/failed) | ✅ |
| `idx_rag_search_executions_merchant` index | 0005 op.create_index(merchant_id) | ✅ |
| 无 `is_billed` / 无 `billing_status` 列 | 0005 设计约束 | ✅（billing truth 归 M07）|
| `xg_douyin_ai_cs` 角色对表 INSERT/SELECT/UPDATE/DELETE | db owner 隐式 | ✅ |
| table owner | catalog | ✅ `xg_douyin_ai_cs` |

migration 0005：`migrations/postgres/xg_douyin_ai_cs/versions/0005_rag_search_executions.py`，revision=`0005`，down_revision=`0004`，create_date=2026-08-10。新建对象：`rag_search_executions` 表（6 列 + PK + CHECK + merchant 索引），不引入 is_billed，不引入 attempt_count。

**schema 存在 ≠ PG_VERIFIED**（仅 `STATIC_SCHEMA_VERIFIED`），consumer runtime 仍需真实执行（见 §12-§17）。

---

## 11. Mock Boundaries（RQ-5 cont.）

**允许并仅 mock**：`OpenAICompatibleClient.embed`（9100 最终外部 embedding API 边界）。mock 返回固定可审计结果：

```text
embedding = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]（8 维，与 knowledge_chunks 无需匹配维度，_search_sqlite 走词法）
model = rq5-verify-mock-embed（非 "mock_for_test_only"，否则 _embed_with_usage L520 跳过计费）
embedding_provider = rq5-mock
```

mock 目的：避免真实 embedding API 收费 / 网络不稳定 / 非确定性 usage / vector search 不可控，且不调用生产外部 embedding / 不修改实际业务状态。

**以下链全程真实，未 mock**：

```text
9100 search_with_diagnostics orchestration（execution 创建 + backend 分支 + finalize）
search execution persistence（rag_search_executions durable commit，RQ-0）
9100 _search_sqlite embedding orchestration
_run_embed_with_hard_timeout daemon 调度
_embed_with_usage（identity matrix 判定 + f-string key 构造 + count_embedding_characters）
Business Event Identity 生成（f-string 构造，非手工注入 key）
ComputeUsageClient.report_usage（9100→9000 HTTP，真实 urllib → TCP → uvicorn → FastAPI）
9000 /internal/compute/usage（真实 route + _require_internal token 校验）
record_usage INSERT / 原子扣费 / IntegrityError 幂等路径
PostgreSQL uniqueness（uk_compute_transactions_merchant_idempotency）
compute account balance
```

关键 compute 路径未被 mock——本轮不是 unit/integration test，达到 `PG_RUNTIME_VERIFIED`（DB-A execution 库）+ `APPLICATION_ROLE_RUNTIME_VERIFIED`（DB-B compute ledger 库）。9100 consumer 与 9000 经真实 loopback HTTP（urllib → TCP → uvicorn → FastAPI → route → record_usage），非 TestClient 旁路。现有 `tests/test_rag_query_compute_idempotency_migration.py` 为 SQLite + 直接调 `record_usage` 的 unit test（checkpoint 11/11 标注 RQ-0/2/3/6 = CODE_VERIFIED，RQ-1/4/5 = SQLite unit test 实跑），本轮以真实双库 PG + 真实 HTTP consumer 路径 + 应用角色升级证据等级。

### Milvus 边界

本轮 `RAG_VECTOR_BACKEND=sqlite`（9100 config），`search_with_diagnostics` 走 SQLite-only 分支（primary embedding + PG 词法 search），不依赖 Milvus。这是合法配置（非 mock consumer 逻辑、非绕过检索），9100 默认 `rag_vector_backend=sqlite`。本轮不修改生产 Milvus collection / 不写正式知识库 / 不重建 collection。

---

## 12. Controlled Fixture（RQ-6 setup）

完全受控 fixture，双库分别以对应 principal 写入：

```text
merchant_id       = rq5-merchant（受控 fixture 商户）
recharge          = create_mock_recharge_order 等价（auto_wechat 应用角色），custom_tokens=100000
compute account   = 首次建账 balance=0 → 充值后 balance=100000（auto_wechat 库）
rag_search_executions = 空（xg_douyin_ai_cs 库，baseline 0）
```

预充值目的：RAG embedding 上报 `record_usage` 走 consume 路径（delta 为负），首账 balance=0 时扣费后变负。预充值模拟真实商户有余额，**非 mock consumer 逻辑、非绕过余额门禁**（RAG embedding 路径无 `check_balance` 余额门禁——与 0034 Preview 的 LLM `check_balance` 不同，embedding consumer 直接上报扣费，`record_usage` 一期不拦截余额允许负）。

baseline（计费前）：

```text
compute_accounts(rq5-merchant)        = 0（不存在，充值时建账）
compute_transactions consume(rq5-merchant) = 0
rag_search_executions(rq5-merchant)  = 0
balance_after_recharge                = 100000
```

未使用真实客户数据；query 为合成检索文本（"奥迪A6价格"/"宝马X5多少钱"/"奔驰C级报价"）。未调用真实 LLM / embedding / 抖音 / 微信 / 外部 API（embedding 为唯一 mock）。

---

## 13. Q-A First Execution（RQ-6）

从真实 consumer 入口 `repository.search_with_diagnostics`（query="奥迪A6价格"，merchant_id=rq5-merchant）执行一次 primary embedding 计费（`RAG_VECTOR_BACKEND=sqlite` → SQLite-only 分支 → `embedding_stage="primary"`）：

```text
Q-A execution_id    = 4（rag_search_executions.id，真实 PG 序列持久化，非硬编码）
lifecycle_status    = completed
identity            = rag_search_execution:4:primary（consumer 自然生成，非手工构造 key）
```

**A. Consumer 执行成功** ✅（execution COMPLETED，`_embed_with_usage` 被调用，`OpenAICompatibleClient.embed` mock 返回非 mock model → 计费路径触发）

**B. Compute Transaction = exactly 1**（PG 查询证据，auto_wechat 库）：

```text
id=48 | idempotency_key=rag_search_execution:4:primary | transaction_type=consume | delta_tokens=-6
balance_after_tokens=99994 | capability_key=knowledge | model=rq5-verify-mock-embed
llm_call_stage=NULL | actual_tokens=6 | usage_measurement_method=estimated_tokens | payload_evidence IS NOT NULL
```

**C. Idempotency Identity 一致** ✅：`rag_search_execution:4:primary` = `rag_search_execution:{execution_id=4}:primary`

**D. Balance**（consume `delta_tokens` 为负，markup=0 → billed=actual=6）：

```text
balance_before = 100000   （fixture 充值后）
charge_delta   = -6       （billed_tokens=calculate_billed_tokens(6,0)=6；"奥迪A6价格" 6 字符）
balance_after  = 99994    （= 100000 + (-6)）✓
```

**E. Usage Metadata**：

```text
capability_key=knowledge / model=rq5-verify-mock-embed / llm_call_stage=NULL
actual_tokens=6 / usage_measurement_method=estimated_tokens / payload_evidence IS NOT NULL
```

---

## 14. Q-A Replay（RQ-7）

对同一个 `execution_id=4`、同一 `primary` stage，经 consumer usage-report 路径 `_embed_with_usage(search_execution_id=4, embedding_stage="primary")` 再次调用（same identity，identity 由 [repository.py:504](../../../apps/xg_douyin_ai_cs/rag/repository.py) f-string 自然重新生成，模拟 daemon timeout 后 primary usage report 晚到重发 / crash 后 usage report 重试场景）：

```text
调用：_embed_with_usage(search_execution_id=4, embedding_stage="primary") [same identity]
identity 自然重新生成：rag_search_execution:4:primary
HTTP：9100→9000 /internal/compute/usage（经 ComputeUsageClient.report_usage 真实 HTTP）
```

**PostgreSQL 权威证据**（不靠 HTTP 200）：

```text
compute_transactions WHERE idempotency_key='rag_search_execution:4:primary' count = 1（未产生第 2 行）✓
account balance 仍 = 99994（replay 后未变）✓
balance_after_replay = 99994 = balance_after_first_execution ✓
```

**法证细节**：`compute_transactions.id` 序列为 48, 50, 51, 52（id=49 缺失）。id=49 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退，故 id 被消耗但无行）→ 进入 [apps/compute/services.py:728-756](../../../apps/compute/services.py) `idempotent_replay` 分支。该 id gap 印证 IntegrityError 幂等路径真实执行，而非"未尝试 INSERT"。

```text
same event → same idempotency identity → duplicate charge suppressed（replay）✓
NO_DOUBLE_CHARGE_VERIFIED
```

SUPPLEMENTARY_RUNTIME_EVIDENCE：id gap=49（IntegrityError rollback 副证）。sequence id gap 不是幂等硬证据——正式硬证据仍是 same identity + one transaction + balance unchanged（已满足）。

---

## 15. Q-B Distinct Execution（RQ-8）

创建另一 search execution（query="宝马X5多少钱"），同一 `primary` stage，从真实 consumer 入口执行：

```text
Q-B execution_id    = 5（≠ 4）
lifecycle_status    = completed
identity            = rag_search_execution:5:primary（consumer 自然生成）
```

**PostgreSQL 证据**：

```text
compute_transactions WHERE idempotency_key='rag_search_execution:5:primary' count = 1  ✓
id=50 | idempotency_key=rag_search_execution:5:primary | delta_tokens=-7 | balance_after_tokens=99987
```

两个不同 execution 合计 **2 个 distinct business-event identities**（`:4:primary` / `:5:primary`），无 collision / 共享 / 互相吞没：

```text
identity(Q-A) = rag_search_execution:4:primary
identity(Q-B) = rag_search_execution:5:primary
identity_distinct = True
same event → dedupe；different event → independent charge  ✓
```

---

## 16. Stage Separation（RQ-9）

RQ-9 适用（静态代码证明存在 ≥2 active legitimate billable embedding stage：primary + fallback_embedding，见 §8）。

Q-R 用 query="奔驰C级报价" 创建 execution_id=6，primary stage 由真实 `search_with_diagnostics` 产生（id=51）；同 execution_id 补 `fallback_embedding` stage（经 consumer usage-report seam `_embed_with_usage(search_execution_id=6, embedding_stage="fallback_embedding")`，对应 Milvus primary 超时后 fallback 重新 embedding 场景）：

```text
Q-R execution_id    = 6
lifecycle_status    = completed
```

同一 `execution_id=6`，两个不同 legitimate billable stage：

**Q-R primary**：
```text
identity = rag_search_execution:6:primary
transaction count = 1  ✓
id=51 | delta_tokens=-6 | balance_after_tokens=99981 | payload_evidence IS NOT NULL
```

**Q-R fallback_embedding**：
```text
identity = rag_search_execution:6:fallback_embedding
transaction count = 1  ✓
id=52 | delta_tokens=-6 | balance_after_tokens=99975 | payload_evidence IS NOT NULL
```

```text
identity(Q-R primary)          = rag_search_execution:6:primary
identity(Q-R fallback_embedding) = rag_search_execution:6:fallback_embedding
identity_distinct = True（same execution + different legitimate billable stage）
2 distinct Business Events / 2 legitimate charges / same execution 不互相吞没
```

```text
same execution + different legitimate billable stage → independent billing events  VERIFIED
```

fallback_embedding 由真实 consumer usage-report seam `_embed_with_usage` 产生（identity f-string 自然重新生成），**非手工构造 fallback key、非 monkeypatch stage selector、非直接调 `record_usage`**。

### 方法论限制（独立审批 correction，2026-08-11）

本轮 Q-R `fallback_embedding` stage 的 runtime 计费证据是通过 **consumer usage-report seam**（`_embed_with_usage(search_execution_id=6, embedding_stage="fallback_embedding")` 直接传 stage 参数）获得，**非通过自然 Milvus primary 超时路径 runtime 触发**。原因：本轮 `RAG_VECTOR_BACKEND=sqlite`（避免 Milvus 外部依赖），`search_with_diagnostics` 走 SQLite-only 分支（repository.py:936-941），该分支只产生 `primary`；`fallback_embedding` 仅在 Milvus 分支（`_search_milvus_or_fallback_with_diagnostics` repository.py:1116-1228）的 except 块（行 1219）当 `query_embedding` 为 None（primary 超时/返回空）时自然触发。本轮无 Milvus 治理任务，故 fallback 的"自然 Milvus 超时触发"runtime 证据不可得。

分层证据等级（如实标注）：

| 命题 | 证据等级 |
|---|---|
| `fallback_embedding` 是 ACTIVE/LEGITIMATE/BILLABLE stage（非 dead branch） | code-verified（repository.py:1219 真实可达） |
| 同 execution + primary vs fallback_embedding → 2 distinct identity | runtime VERIFIED |
| 各计费 1 次（不互相吞没） | runtime VERIFIED |
| `fallback_embedding` 经自然 Milvus primary 超时路径 runtime 触发 | **未验证**（仅 code-verified 可达） |

RQ-9 证据等级 = `stage identity + 计费分离 runtime VERIFIED + 自然触发路径 code-verified（非 runtime-naturally-triggered）`。未来升级到 runtime-naturally-triggered 需 `RAG_VECTOR_BACKEND=milvus` + Milvus test collection + mock primary embedding 返回 None（模拟超时）→ Milvus search 抛异常 → except 自然 fallback，属独立 Milvus 治理任务。此限制不改变核心幂等结论（RQ-9 不导致 double charge，同 execution 不同 stage 计费分离 runtime 真实）。

---

## 17. Transaction / Balance（RQ-12）

PG 查询（`auto_wechat` 应用角色只读）全部 consume txns for `rq5-merchant`：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|
| 48 | `rag_search_execution:4:primary` | consume | -6 | 99994 | knowledge | rq5-verify-mock-embed | NULL | 6 | estimated_tokens | NOT NULL |
| 50 | `rag_search_execution:5:primary` | consume | -7 | 99987 | knowledge | rq5-verify-mock-embed | NULL | 7 | estimated_tokens | NOT NULL |
| 51 | `rag_search_execution:6:primary` | consume | -6 | 99981 | knowledge | rq5-verify-mock-embed | NULL | 6 | estimated_tokens | NOT NULL |
| 52 | `rag_search_execution:6:fallback_embedding` | consume | -6 | 99975 | knowledge | rq5-verify-mock-embed | NULL | 6 | estimated_tokens | NOT NULL |

按 identity 计数：

| idempotency_key | txn_count |
|---|---|
| `rag_search_execution:4:primary` | 1 |
| `rag_search_execution:5:primary` | 1 |
| `rag_search_execution:6:primary` | 1 |
| `rag_search_execution:6:fallback_embedding` | 1 |

账户：

```text
merchant_id=rq5-merchant / balance_tokens=99975
```

balance 推进：

```text
100000 →(Q-A first)→ 99994 →(Q-A replay, 不变)→ 99994 →(Q-B)→ 99987 →(Q-R primary)→ 99981 →(Q-R fallback_embedding)→ 99975 ✓
final balance = initial(100000) + delta(Q-A primary -6) + delta(Q-B primary -7) + delta(Q-R primary -6) + delta(Q-R fallback_embedding -6)
              = 100000 + (-25) = 99975 ✓
Q-A replay does not contribute another delta ✓
```

4 distinct legitimate Business Events / 4 legitimate compute charges / replay 不二次计费。id=49 缺失（Q-A replay IntegrityError 消耗序列）。

### Application Role Hard Gate

**DB-B compute ledger 侧**：核心 consumer 写入链全程由 `auto_wechat` Application Principal 执行：

```text
postgres catalog inspection → PASS
auto_wechat consumer runtime 写入 → PASS（record_usage 经 DATABASE_URL=auto_wechat 角色 → PG）
superuser-as-consumer 替代 → 无（postgres 仅用于 catalog inspection / schema 前提核验）
```

若 `postgres PASS / auto_wechat FAIL` 则 RAG Query 0005 FAIL。本验证为 `auto_wechat PASS`。

```text
COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED: auto_wechat
postgres PASS / auto_wechat PASS（非 postgres PASS / auto_wechat FAIL）
```

**DB-A RAG execution 侧**：execution 写入由 `xg_douyin_ai_cs` runtime principal 执行（见 §4 RQ-2）。

```text
RAG_EXECUTION_DB_RUNTIME_PRINCIPAL: xg_douyin_ai_cs
Evidence: RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED
```

---

## 18. Non-null Identity（RQ-10）

```text
compute_transactions WHERE merchant_id='rq5-merchant' AND transaction_type='consume'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0  ✓
全局 rag_search_execution:% identity NULL/EMPTY count = 0  ✓
全局 consume NULL/EMPTY count = 0（本轮 rq5-merchant 范围） ✓
```

RAG Query active charge path 产生的 identity 全部 NOT NULL / NOT EMPTY，且与冻结 contract 一致。无 `idempotency_key=None` 走旧兼容路径（record_usage 的 idempotency_key=None warning 路径未触发）。

Global Active None Audit 仍保留后续全局 Gate（本轮仅审 RAG Query consumer + 本轮 fixture 范围，非全局所有 charge path）。

---

## 19. Execution Persistence（RQ-11）

本轮 RAG search execution 在 PG（xg_douyin_ai_cs 库）真实持久化并被复用：

| id | merchant_id | lifecycle_status | has_created | has_completed |
|----|---|---|---|---|
| 4 | rq5-merchant | completed | True | True |
| 5 | rq5-merchant | completed | True | True |
| 6 | rq5-merchant | completed | True | True |

- execution `id` 持久存在，replay 复用同一 `execution.id` 作 identity 来源（Q-A replay 复用 execution_id=4，非重新产生新 execution）。
- merchant ownership：`rag_search_executions.merchant_id` = consumer 调用传入的 `rq5-merchant`（受控 fixture），非前端传入。
- `lifecycle_status=completed` 稳定持久（search_with_diagnostics 成功 → completed；C1：lifecycle=整次请求结果，非 stage 状态）。
- `created_at` NOT NULL（durable commit 生效，RQ-0）；`completed_at` NOT NULL（`_finalize_search_execution` 填充 `completed_at = CURRENT_TIMESTAMP`，与 0034 Preview 的 completed_at 现状未填不同——RAG Query 的 `_finalize_search_execution` 主动填 completed_at）。

```text
Business Event Identity 基于真实、稳定的 PG execution identity（execution.id）✓
```

---

## 20. Runtime Principal Evidence（RQ-2 cont.）

```text
RAG EXECUTION DB RUNTIME PRINCIPAL: xg_douyin_ai_cs
Evidence: RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED

  current_user        = xg_douyin_ai_cs
  SUPERUSER?          = False
  database owner?     = xg_douyin_ai_cs
  schema CREATE?      = True（pg_database_owner 隐式）
  required DML?       = INSERT/SELECT/UPDATE/DELETE on rag_search_executions ✅

COMPUTE LEDGER DB RUNTIME PRINCIPAL: auto_wechat
Evidence: APPLICATION_ROLE_RUNTIME_VERIFIED（已批准，2026-08-10 APPROVED）

  current_user        = auto_wechat
  SUPERUSER?          = False
  database owner?     = postgres
  schema CREATE?      = False
  required DML?       = INSERT/SELECT/UPDATE/DELETE on compute_transactions/compute_accounts ✅
```

本窗口未在 9100 侧建立独立 role contract，故 9100 侧写 `RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED`（非 `APPLICATION_ROLE_RUNTIME_VERIFIED`）。9100 application-role model 设计属独立任务（不在本窗口范围）。

---

## 21. Cleanup（RQ-13）

测试完成后分别以对应 principal 清理受控 fixture：

```text
DB-A xg_douyin_ai_cs（xg 角色）:
  DELETE FROM rag_search_executions WHERE merchant_id='rq5-merchant'   → 3

DB-B auto_wechat（auto_wechat 角色）:
  DELETE FROM compute_transactions WHERE merchant_id='rq5-merchant'    → 5（4 consume + 1 recharge）
  DELETE FROM compute_accounts WHERE merchant_id='rq5-merchant'        → 1
```

residual 检查（全部 0，clean baseline 恢复）：

```text
compute_txns(rq5-merchant)         = 0
compute_accounts(rq5-merchant)     = 0
rag_search_executions(rq5-merchant) = 0
```

DB Baseline 保持：

```text
auto_wechat:       revision=0034 / physical tables=61（不变）
xg_douyin_ai_cs:   revision=0005（本轮 upgrade 后，before=0004 / after=0005）
```

验证脚本位于 worktree 外（`e:/work/tmp/rq5/`），未入 worktree（`git status` clean，零业务代码改动）。临时 9000 uvicorn 进程已停止移除。

```text
residual test data = 0
```

---

## 22. RQ Gate Table

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| RQ-0 | Git / environment | ✅ PASS | HEAD=803a452 / clean；LOCAL DEV，双 PG 库，PG 16.x |
| RQ-1 | 9100 PG environment | ✅ PASS | before=0004（表不存在）→ upgrade → after=0005（表存在）；migration graph 0001-0005 单链 |
| RQ-2 | 9100 runtime principal | ✅ PASS | RAG_EXECUTION_DB_RUNTIME_PRINCIPAL=xg_douyin_ai_cs（非 superuser，非 postgres-as-consumer） |
| RQ-3 | 9000 compute ledger preconditions | ✅ PASS | auto_wechat canonical@0034/61表；uk 唯一约束存在；knowledge markup ratio 存在；app role DML PASS |
| RQ-4 | Business Event Identity | ✅ PASS | `rag_search_execution:{search_execution_id}:{embedding_stage}`，来自稳定 execution.id，identity matrix 严格互斥，无 drift |
| RQ-5 | Migration 0005 / schema | ✅ PASS | 0005 表/列/约束/索引存在；compute 幂等唯一约束存在；knowledge markup ratio 存在；xg 角色有权限 |
| RQ-6 | Q-A first execution | ✅ PASS | Q-A(id=4) → 1 consume txn(id=48)，identity 一致，balance 100000→99994，actual_tokens=6，payload_evidence NOT NULL |
| RQ-7 | Q-A same-stage replay | ✅ PASS | Q-A replay → txn count 仍 1，balance 不变(99994)；id gap=49 印证 IntegrityError rollback |
| RQ-8 | Q-B distinct execution | ✅ PASS | Q-B(id=5) → 1 独立 txn(id=50)，2 distinct identities，无 collision |
| RQ-9 | stage separation（primary+fallback_embedding）| ✅ PASS | Q-R(id=6) → primary(id=51)+fallback_embedding(id=52)，2 distinct stage identities |
| RQ-10 | non-null identity | ✅ PASS | 0 null/empty idempotency_key（本轮 + 全局 rag_search_execution:%）|
| RQ-11 | execution persistence | ✅ PASS | 3 行 PG 持久，lifecycle=completed，created_at NOT NULL，completed_at NOT NULL，identity 基于稳定 execution.id |
| RQ-12 | transaction / balance closure | ✅ PASS | 4 consume txns(id 48,50,51,52)，delta=-6/-7/-6/-6，balance=99975=100000-25，replay 不贡献 delta，app role PASS |
| RQ-13 | cleanup / residual | ✅ PASS | residual=0，DB-BL auto_wechat 不变(0034/61)，xg_douyin_ai_cs=0005，临时进程清理，worktree clean |

`RQ-6 / RQ-7 / RQ-8 / RQ-9 / RQ-12` 均为真实 `PG_RUNTIME_VERIFIED`（非 unit test，非 SQLite）。

---

## 23. OUT_OF_P1 Recovery Gap

```text
RAG_QUERY_REQUEST_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1（保持冻结，本轮未触碰、未扩大、未修）
```

本轮 same-execution replay（§14）验证的是 **same execution + same stage 的技术重放幂等**（idempotent replay safety = VERIFIED），对应 daemon timeout 后 primary usage report 晚到重发 / crash 后 usage report 重试路径——证明同一 execution_id 重报不会 double charge（`NO_DOUBLE_CHARGE_VERIFIED`），即 recovery 路径的幂等性已满足。

本轮**不**验证 / 不解决：
- whole search request retry（上游重新调 `search_with_diagnostics`）→ 新 Execution → 新 key → 新 charge（`RAG_QUERY_REQUEST_RECOVERY_GAP` 关注的 full-request retry 识别）
- crash recovery / lost request recovery / worker restart recovery / retry orchestration redesign

这些属 `Final PostgreSQL Concurrent Closure Gate` 与 reliability gap 范畴，不阻断 RAG Query 0005 consumer PG verification。本轮范围内未观察到新 reliability 问题。

并发边界：本轮未执行全局 concurrent closure（`Final PostgreSQL Concurrent Closure Gate` 后续独立执行）。txn id gap（48,50,51,52，缺 49）为 replay INSERT-rollback 的法证副证，非正式 concurrent test。`lack of concurrent test` 不阻断 RAG Query 0005。

---

## 24. Verdict

```text
RAG QUERY 0005 CONSUMER:
PG_VERIFICATION_COMPLETE_PENDING_APPROVAL

Business Event Identity:
rag_search_execution:{search_execution_id}:{embedding_stage}

Same execution + same stage:
NO_DOUBLE_CHARGE_VERIFIED（Q-A replay → 1 txn / balance 不变 / id gap=49 印证 IntegrityError）

Distinct execution separation:
VERIFIED（Q-B → 独立 charge / 2 distinct identities / 无 collision）

Distinct stage separation:
VERIFIED（Q-R primary + fallback_embedding → 同 execution 不同 stage → 2 独立 charge）

RAG_EXECUTION_DB_RUNTIME_PRINCIPAL:
xg_douyin_ai_cs

COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED:
auto_wechat
```

**不得自行**：`RAG QUERY 0005 = PG_VERIFIED`（须独立审批窗口裁定）。

---

## 25. P1 Status

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

本轮完成的是 **RAG Query 0005 consumer PostgreSQL verification**（候选 PG_VERIFICATION_COMPLETE_PENDING_APPROVAL），不是整个 P1 closure。

Technical Closure Blockers 剩余：

```text
A.   auto_wechat schema baseline              = REMEDIATED（DB-BL-2D，canonical@0034）
A′.  LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = OPEN（init SQL 仍 OWNER auto_wechat，本轮未改）
B.   RAG Query 0005 PG                        = 本轮完成（候选 PENDING_APPROVAL）
C.   Global Active None Audit                 = OPEN（本轮仅审 RAG Query + fixture 范围，非全局）
D.   Final PostgreSQL Concurrent Closure Gate = OPEN
```

既有 OUT_OF_P1 reliability gaps（DAILY_REPORT/TRAINING/RAG_INGEST_RUN/RAG_INGEST_REQUEST/M05_ANALYSIS_USAGE_REPORT/PREVIEW_REQUEST/RAG_QUERY_REQUEST）继续保持原分类。RB-10 = NOT AUTHORIZED。

---

## 26. 边界遵守

- ✅ 未修改业务代码（NO BUSINESS CODE CHANGE）——验证脚本经 stdin / 外部目录执行，未入 worktree；
- ✅ migration 0005 schema precondition 经 alembic upgrade 0004→0005 执行（用户授权），未新增 repair migration / 未 stamp / 未手工 schema 修复；xg_douyin_ai_cs 库 revision 0004→0005 真实前进，如实记录 before/after；
- ✅ 未修改 9100 application-role model（未设计新 role / 未改 GRANT / 未建新角色）；9100 侧如实记录 `RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED`（非 `APPLICATION_ROLE_RUNTIME_VERIFIED`）；
- ✅ 未开始 Global Active None Audit / Final Concurrent Closure / RB-10 / bootstrap owner drift 修复；
- ✅ DB-B compute ledger 侧未用 superuser 替代 app role 完成 consumer 核心写入（postgres 仅 catalog inspection）；
- ✅ 未提交（candidate diff 保持，数据库证据/凭据/dump 未入库）；
- ✅ consumer 验证仅 mock 外部 embedding API（外部非确定性边界），未 mock consumer orchestration / identity 生成 / usage reporting / compute charge / PG 幂等路径；
- ✅ 未触碰 `RAG_QUERY_REQUEST_RECOVERY_GAP`（OUT_OF_P1）；
- ✅ 未真实发送抖音私信 / 微信 / 未修改 lead/customer facts / 未调用真实 LLM / embedding / Milvus；
- ✅ 未修改 RAG Query 业务代码 / migration 0005 内容 / M07 Core / DB-BL / `_embed_with_usage` / `record_usage` / 余额门禁。

---

## 27. Git / Commit

按指令：**不自行 commit**。本报告为 candidate diff（`docs/architecture/remediation/P1_PG_RAG_QUERY_0005_CONSUMER_VERIFICATION.md`），供独立审批窗口复核。数据库测试证据已清理（residual=0），无凭据/dump/probe 残留。验证脚本位于 worktree 外（`e:/work/tmp/rq5/`），未入 worktree（`git status` clean）。

提交：**P1-PG-RAGQ-0005 独立审批窗口。**
