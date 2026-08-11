# P1-PG-RAGQ-0005 — RAG Query Consumer PostgreSQL 验证独立审批报告

> 任务：`P1-PG-RAGQ-0005 — xg_douyin_ai_cs RAG Query Consumer PostgreSQL Verification` 独立审批
> 审批窗口：P1-PG-RAGQ-0005 独立审批窗口
> 审查对象：`P1_PG_RAG_QUERY_0005_CONSUMER_VERIFICATION.md` / `docs/ai/05_PROJECT_CONTEXT.md` / `P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md` / 实际 git diff / 真实 PG runtime
> 基线 commit：`803a452`（验证：闭环AI回复预览0034 PostgreSQL幂等计费）
> 审批日期：2026-08-11
> Source of Truth：真实 PG runtime 证据（独立审批窗口自有 fixture，不采信执行窗口自述） > 冻结文档 > 推测

---

## Technical Decision

```text
APPROVED_WITH_CORRECTIONS
```

runtime idempotency 成立（独立审批窗口用独立 merchant `rq5-approval` / 独立端口 9001 复现全部核心命题），13 个 RQ Gate 全部 PASS。但报告存在不改变核心结论的方法论/措辞修正：Q-R `fallback_embedding` stage 的 runtime 计费证据经 consumer usage-report seam（`_embed_with_usage` 直接传 `embedding_stage="fallback_embedding"`）获得，**非通过自然 Milvus primary 超时路径 runtime 触发**；其自然可达性由静态代码证明。报告须如实标注该证据等级。

冻结结论（与执行窗口候选一致，经独立核验）：

```text
RAG QUERY 0005 CONSUMER:
PG_RUNTIME_VERIFIED

Business Event Identity:
rag_search_execution:{search_execution_id}:{embedding_stage}

Same execution + same stage:
NO_DOUBLE_CHARGE_VERIFIED

Distinct execution separation:
VERIFIED

Distinct stage separation:
VERIFIED（计费分离 runtime + 自然触发 code-verified，非 runtime-naturally-triggered）

COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED
RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED
```

```text
HISTORICAL BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT:
RESOLVED
```

---

## Git / Scope（RQ-0）

```text
HEAD = 803a4522d1f6f460db86bf842d62cd9b70fc6df6
```

`git status --short`：

```text
 M docs/ai/05_PROJECT_CONTEXT.md
 M docs/architecture/remediation/P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md
?? docs/architecture/remediation/P1_PG_RAG_QUERY_0005_CONSUMER_VERIFICATION.md
```

`git diff --stat`：2 文件 modified（共 +2/-1 行）+ 1 新报告。独立确认：

- ✅ 无业务代码修改（`apps/` / `app/` 无 diff）
- ✅ migration 0005 文件未修改（`migrations/postgres/xg_douyin_ai_cs/versions/0005_rag_search_executions.py` 仍在 git 历史中，未出现在 working tree diff）
- ✅ migration graph 未修改
- ✅ M07 Core 未修改
- ✅ DB-BL 未修改
- ✅ 无 credentials / dump / snapshot 入库
- ✅ 验证脚本不在 worktree（`e:/work/tmp/rq5/`，worktree 外，`git status` clean）

05_PROJECT_CONTEXT.md diff：第 159 行 9100 Alembic 描述补 `0004` + `0005` + `head=0005` + 本地 upgrade 事实。checkpoint 11/11 diff：Blocker B 补 2026-08-11 更新段。两者均属本轮 current-facing 治理 scope，措辞准确。

**RQ-0 = PASS**

---

## Authorized Migration Upgrade Classification

执行窗口本轮 `alembic upgrade 0004→0005`（`xg_douyin_ai_cs` 库）经用户明确授权。分类为：

```text
AUTHORIZED LOCAL ENVIRONMENT REMEDIATION
```

而非 `UNAUTHORIZED SCOPE EXPANSION`。独立确认它严格只做 `alembic upgrade`：

- ✅ 无 blind stamp（before=0004 真实落后，upgrade 后 current=0005 真实前进）
- ✅ 无手工 CREATE TABLE / ALTER（`rag_search_executions` 由 0005 `op.create_table` 创建，结构独立核验与 migration 文件一致）
- ✅ 未修改 migration 脚本（0005 文件内容与 git 一致）
- ✅ 未修改 Alembic graph（0005 revision=`0005` / down_revision=`0004` 合法后继，单链）
- ✅ 无 downgrade / rewrite 历史

执行窗口报告对此分类准确（§2/§4 明确"经用户授权 upgrade"），未把 upgrade 错误描述成"纯 verification"。

---

## Migration 0005 Integrity（RQ-5）

独立读取 `migrations/postgres/xg_douyin_ai_cs/versions/0005_rag_search_executions.py`：

```text
revision      = "0005"
down_revision = "0004"
branch_labels = None
depends_on    = None
create_date   = 2026-08-10
```

合法后继 revision（0004→0005 单链）。`upgrade()` 创建 `rag_search_executions` 表（6 列 + PK + CHECK + merchant 索引），`downgrade()` 对称 drop。设计约束：无 `is_billed` / 无 `billing_status` 列（billing truth 只归 M07 committed ComputeTransaction）。

`rag_search_executions` 等本轮 consumer 依赖对象确实由 0005 合法创建/演进（非手工建表、非仅表名存在）。

**RQ-5 = PASS**（STATIC_SCHEMA_VERIFIED + runtime apply 见 RQ-1）

---

## 9100 Current / Head（RQ-1）

独立查询（`postgres` superuser catalog inspection，仅 inspection 不做 consumer 写入）：

```text
DB-A xg_douyin_ai_cs:
  alembic_version.current = 0005
  rag_search_executions   = EXISTS（to_regclass 返回表名）
  public base tables      = 10

DB-B auto_wechat:
  alembic_version.current = 0034
  public base tables      = 61
```

`0005` 当前是 head（migration graph 单链 head=0005）。current satisfies required RAG Query schema（`rag_search_executions` 表 + 列 + 约束 + 索引落地，见下表）。current/head relationship healthy。

before=0004（表不存在）证据来自执行窗口留存的命令输出（§2：upgrade 前 `to_regclass('rag_search_executions')` = 空）。审批未为"复现 before 状态"而 downgrade 0005→0004——不扰动 canonical DB（符合审批纪律第 5 节）。

表结构独立 catalog 核验（与 migration 0005 文件逐项比对）：

| 对象 | migration 0005 定义 | runtime catalog 核验 |
|---|---|---|
| `rag_search_executions` 表 | `op.create_table` | ✅ EXISTS |
| `id` integer PK autoincrement | `sa.Column(primary_key=True)` | ✅ `nextval('rag_search_executions_id_seq')` |
| `merchant_id` varchar(128) NOT NULL | 0005 | ✅ NOT NULL |
| `query` text NOT NULL | 0005 | ✅ NOT NULL |
| `lifecycle_status` varchar(20) NOT NULL default 'running' | 0005 server_default | ✅ default 'running' |
| `created_at` timestamptz NOT NULL default now() | 0005 | ✅ NOT NULL default now() |
| `completed_at` timestamptz nullable | 0005 | ✅ nullable |
| `ck_rag_search_executions_status` CHECK | 0005 | ✅ CHECK IN (running/completed/failed) |
| `rag_search_executions_pkey` | 0005 primary_key | ✅ PK (id) |
| `idx_rag_search_executions_merchant` | 0005 op.create_index | ✅ btree(merchant_id) |
| 无 `is_billed` / 无 `billing_status` 列 | 0005 设计约束 | ✅ 无 |
| table owner | — | ✅ `xg_douyin_ai_cs` |

**schema 存在 ≠ PG_VERIFIED**（仅 STATIC_SCHEMA_VERIFIED），consumer runtime 仍需真实执行（见 RQ-6~RQ-12）。

**RQ-1 = PASS**（before=0004 表不存在 → upgrade → after=0005 表存在；migration graph 0001-0005 单链 head=0005）

---

## Historical Blocker

此前 0005 曾被错误宣称为已验证（identity 设计文档"Stage 5H-2 实施落记"写 `0005 PG = PG_VERIFIED`），随后正式纠正为 `PENDING_PG_VERIFICATION / BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT`（checkpoint 11/11 Charge Path #11 权威状态）。

本轮独立审批确认全部前置条件满足：

```text
Docker/local runtime available       = YES（auto-wechat-postgres-dev Up 24h healthy）
9100 canonical PG reachable          = YES（127.0.0.1:5432 xg_douyin_ai_cs）
required migration applied           = YES（current=0005，rag_search_executions 表落地）
runtime principal usable              = YES（xg_douyin_ai_cs 角色，非 superuser）
consumer real runtime PASS            = YES（独立 fixture 复现，见 RQ-6~RQ-12）
```

正式关闭：

```text
HISTORICAL LOCAL RUNTIME BLOCKER:
BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT = RESOLVED
```

非"仅因 Docker 启动了就关闭"——Docker 启动是必要条件，本轮另完成 migration upgrade + 真实双库 consumer runtime 验证。

---

## Dual Database Reality

独立确认两个责任域，不混写为一个 PG 验证：

```text
DB-A — RAG Execution 持久化
  database           = xg_douyin_ai_cs
  runtime principal  = xg_douyin_ai_cs（独立 catalog 核验：current_user=xg_douyin_ai_cs）
  database owner     = xg_douyin_ai_cs（pg_databaseowner）
  engine             = 9100 get_rag_engine()（settings.rag_database_url → create_rag_engine PG 分支）
  对象               = rag_search_executions 表（migration 0005）

DB-B — Compute Ledger / Balance 持久化
  database           = auto_wechat
  runtime principal  = auto_wechat（独立 catalog 核验：current_user=auto_wechat）
  database owner     = postgres
  revision           = 0034
  physical tables    = 61
  engine             = 9000（DATABASE_URL）
  对象               = compute_transactions / compute_accounts（migration 0030）
```

```text
DB-A != DB-B（不同 database / 不同 owner / 不同 application principal）
```

RAG Query 跨双库：execution identity 在 DB-A 创建持久化，billing 在 DB-B 原子扣费。两库 identity 不串错（独立 fixture 验证：DB-A exec_id 与 DB-B idempotency_key 一一对应，无跨 execution 串号）。

---

## 9100 Runtime Principal（RQ-2）

独立 catalog inspection（`pg_roles` / `pg_database` / `pg_class`）：

```text
9100 runtime database principal = xg_douyin_ai_cs

  current_user        = xg_douyin_ai_cs（consumer runtime 写入经此角色）
  SUPERUSER?          = False（rolsuper=f）
  rolcreatedb         = False
  rolcreaterole       = False
  database owner?     = xg_douyin_ai_cs（pg_databaseowner）
  schema CREATE?      = True（public schema CREATE 隐式持于 pg_database_owner 成员）
  required DML?       = INSERT/SELECT/UPDATE/DELETE on rag_search_executions ✅
  table owner         = xg_douyin_ai_cs
```

### RUNTIME_PRINCIPAL_CAPABILITY_OBSERVATION（治理观察，不阻断本轮）

`xg_douyin_ai_cs` 角色权限较 9000 已批准的 `auto_wechat` application-role model 更宽：持有 CREATE（schema 隐式）/ TRUNCATE / REFERENCES / TRIGGER，而 `auto_wechat` 是 DML-only / CREATE=false / TRUNCATE DENIED 的最小权限 model（`P1_PG_APPLICATION_ROLE_PERMISSION_IMPLEMENTATION_APPROVAL.md`，2026-08-10 APPROVED）。

9100 侧**未单独审批 application-role model**——本轮不顺手设计/整改 9100 IAM（NO BUSINESS CODE CHANGE，任务约束）。因此本轮如实写：

```text
RAG_EXECUTION_DB_RUNTIME_PRINCIPAL: xg_douyin_ai_cs
Evidence: RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED
```

**不写** `APPLICATION_ROLE_RUNTIME_VERIFIED`（9100 侧无已批准 application-role model 与本轮 runtime 证据配对）。不写 `least privilege verified`。

**登记为 future least-privilege governance gap**：9100 `xg_douyin_ai_cs` role model 收敛（CREATE/TRUNCATE 收紧）属独立任务，不在本轮 RAG Query consumer 验证范围。无冻结规则要求 9100 本轮必须 non-superuser 且最小权限——本轮 superuser=False 已确认，权限较宽如实记录。

**RQ-2 = PASS**

---

## 9000 Compute Principal（RQ-3 / RQ-12 Application Role Hard Gate）

DB-B compute ledger 核心写入全程由已批准的 `auto_wechat` Application Principal 执行：

```text
auto_wechat role: rolsuper=f / rolcreatedb=f / rolcreaterole=f
DB owner = postgres（非 auto_wechat）
```

幂等前置对象独立 catalog 核验：

| 对象 | 核验 |
|---|---|
| `uk_compute_transactions_merchant_idempotency` | ✅ UNIQUE (merchant_id, idempotency_key) |
| `compute_transactions.idempotency_key` | ✅ varchar nullable |
| `compute_transactions.payload_evidence` | ✅ text nullable |
| `compute_transactions.llm_call_stage` | ✅ varchar nullable（RAG embedding 报 NULL）|
| `compute_markup_ratios(knowledge)` | ✅ enabled=true / markup_basis_points=0 / consumption_mode=actual / fixed_tokens_per_call=NULL |
| `compute_markup_ratios(douyin-cs)` | ✅ 对照存在 |
| `auto_wechat` 角色 DML on compute_transactions/compute_accounts | ✅ INSERT/SELECT/UPDATE/DELETE |

9000 `/ready`（独立审批 fixture 启动的 9001 端口实例，DATABASE_URL=auto_wechat 应用角色）：HTTP 200 / `backend=postgresql / db_connect=pass / database_name=auto_wechat`。

独立 fixture runtime 证据：consumer 写入经 `auto_wechat` 角色（`db_b_principal=auto_wechat`），非 superuser-as-consumer。`postgres` 仅用于 catalog inspection / schema 前提核验。

```text
COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED: auto_wechat
postgres PASS(catalog inspection only) / auto_wechat PASS(consumer write)
```

若 `postgres PASS / auto_wechat FAIL` 则 RAG Query 0005 FAIL。本验证为 `auto_wechat PASS`。

**RQ-3 = PASS**

---

## Static Consumer Chain（RQ-4）

独立阅读当前代码（Explore agent 全链核验 + 审批窗口抽检），真实文件/函数：

```text
9100 POST /rag/search                       apps/xg_douyin_ai_cs/routers/rag.py:38
  → require_internal_service_token           dependencies.py:18（X-Internal-Service-Token == XG_DOUYIN_AI_CS_SERVICE_TOKEN）
  → repository.search(payload)               repository.py:953
    → search_with_diagnostics(payload)      repository.py:923
      → :929 _create_search_execution(merchant_id, query)   [durable before embedding]
        → :1063-1081 INSERT INTO rag_search_executions(...) RETURNING id + conn.commit()
        → return int(row["id"])             [PG 自增 PK = durable execution identity]
      → :936-941 SQLite-only 分支：_search_sqlite(embedding_stage="primary")
      → :931-934 Milvus 分支：_search_milvus_or_fallback_with_diagnostics(execution_id=...)
      → :945 _finalize_search_execution(execution_id, "completed")  [lifecycle=整次请求结果]
      → :949 except → _finalize(..., "failed")

_create_search_execution                    repository.py:1063-1081（INSERT + conn.commit 返回 int id）
_finalize_search_execution                  repository.py:1084-1106（UPDATE lifecycle_status + completed_at=CURRENT_TIMESTAMP）

_search_sqlite(payload, *, execution_id, embedding_stage)  repository.py:1231
  → :1270-1276 if query_embedding is None:
      _run_embed_with_hard_timeout(..., search_execution_id, embedding_stage)
        → _worker（daemon 线程）repository.py:444
          → _embed_with_usage(...)          repository.py:469
            → :494-516 identity matrix 严格互斥判定
              → :504 idempotency_key = f"rag_search_execution:{search_execution_id}:{embedding_stage}"
            → :518 client.embed(text)        [★ 唯一外部 mock 边界]
            → :519-521 if model != "mock_for_test_only" and merchant_id:
                  tokens = count_embedding_characters(text)   [len(text)]
            → :523-533 ComputeUsageClient().report_usage(
                  source="embedding", capability_key="knowledge",
                  usage_measurement_method="estimated_tokens", llm_call_stage=None,
                  idempotency_key=...)       [9100→9000 HTTP]
                → compute_usage_client.py:160-166 base_url=AUTO_WECHAT_9000_BASE_URL
                → :172 USAGE_PATH="/internal/compute/usage"
                → POST {base_url}/internal/compute/usage（X-Internal-Token）
                  → app/routers/compute.py:458 internal_router.post("/compute/usage")
                    → :463 _require_internal（X-Internal-Token 校验）
                    → :482 compute_service.record_usage(idempotency_key=payload.idempotency_key)
                      → apps/compute/services.py:615 record_usage()
                        → :683-689 payload_evidence 计算
                        → :692-716 db.add(ComputeTransaction) + flush + 原子扣费 + commit
                        → :728-756 IntegrityError → rollback → existing.payload_evidence == payload_evidence → idempotent_replay
                        → :757-769 不同 → idempotency_conflict
```

Milvus fallback path（`_search_milvus_or_fallback_with_diagnostics` repository.py:1116-1228）：

- :1152-1156 primary embedding（`embedding_stage="primary"`）
- :1206-1224 except 块：`fallback_stage = "fallback_embedding" if not query_embedding else None`（行 1219）
  - `query_embedding` 为 None（primary 超时/返回空）→ `fallback_stage="fallback_embedding"` → `_search_sqlite(query_embedding=None, stage=fallback_embedding)` → :1270 `query_embedding is None` 触发二次 embedding → `_embed_with_usage(stage="fallback_embedding")`
  - `query_embedding` 非 None（primary 成功但 Milvus search 失败）→ `fallback_stage=None` → 复用已算 embedding，不计费

**fallback_embedding 是真实可达分支，非 dead branch**（repository.py:1219 真实可达）。

全程未发现 CONTRACT_DRIFT：identity 仍为 `rag_search_execution:{search_execution_id}:{embedding_stage}`（repository.py:504）。

`get_rag_engine()`（database.py:57-70）用 `settings.rag_database_url`（PG URL）→ `create_rag_engine`（database.py:73-115）PG 分支 `create_engine(postgresql+psycopg)`。PG 下 consumer 业务路径不碰 SQLite 专属的 `rag_db_path`（config.py:47-51，PG 下 raise）/ `connect()`（database.py:118-135，PG 下 raise）。**consumer 在 PG 下正常工作，非造假。**

---

## Search Execution Durability（RQ-11）

identity 来源：`rag_search_executions.id`（PG 自增 PK），由 `_create_search_execution`（repository.py:1063-1081）在 embedding worker 启动前 durable commit（RQ-0）。

独立 fixture 证据（`rq5-approval` merchant，3 行 PG 持久）：

| id | merchant_id | lifecycle_status | created_at NOT NULL | completed_at NOT NULL |
|----|---|---|---|---|
| 7 | rq5-approval | completed | True | True |
| 8 | rq5-approval | completed | True | True |
| 9 | rq5-approval | completed | True | True |

- execution `id` 持久存在，replay 复用同一 `execution.id`（Q-A replay 复用 exec_id=7，非重新产生新 execution）。
- merchant ownership：`rag_search_executions.merchant_id` = consumer 调用传入的 `rq5-approval`（受控 fixture），非前端传入。
- `lifecycle_status=completed` 稳定持久（`_finalize_search_execution` 主动填 `completed_at = CURRENT_TIMESTAMP`，与 0034 Preview 的 completed_at 现状未填不同）。
- 非 request attempt id / retry id / 临时 UUID / embedding 调用次数（execution_id = PG 序列 `nextval`，进程重启/重试后稳定复用）。
- billing truth 归 M07 `ComputeTransaction`（`rag_search_executions` 无 `is_billed`/`billing_status` 列，migration 0005 + 代码核验一致）。
- C4 mixed identity 防护：`run_id`/`document_id`/`chunk_index`（Ingest）与 `search_execution_id`/`embedding_stage`（Query）同时存在 → warning + 退 None（repository.py:508-516）。

**RQ-11 = PASS**

---

## Business Event Identity（RQ-4）

真实生成代码 repository.py:494-516：

```python
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
    _logger.warning("rag_embed stage=identity_violation ...")
    idempotency_key = None
```

独立 fixture 产生的 identity 全部与冻结 contract 一致：

```text
rag_search_execution:7:primary
rag_search_execution:8:primary
rag_search_execution:9:primary
rag_search_execution:9:fallback_embedding
```

无 drift。identity 来自稳定 execution.id（非时间戳/UUID/attempt），identity matrix 严格互斥（query_count==2 and ingest_count==0 才构造 Query key）。

**RQ-4 = PASS**

---

## embedding_stage Contract（RQ-4 cont. / RQ-9 适用性）

当前所有 active billable embedding_stage（从代码实际调用点核验）：

| stage | 生成位置 | 触发条件 |
|---|---|---|
| `primary` | repository.py:940（SQLite-only）/ :1155（Milvus）| 首次 query embedding |
| `fallback_embedding` | repository.py:1219 | Milvus fallback 且 primary embedding 为空（超时/返回空）时重新 embedding |

cardinality = 1 SearchExecution : up to 2 embedding charge events（primary + fallback_embedding）。

**存在 2 个 active legitimate billable embedding stage** → RQ-9 Stage Separation **适用**（非 N/A）。两者均 ACTIVE / LEGITIMATE / BILLABLE（非 dead branch，非仅日志 label）——`primary` 由 runtime 自然触发（独立 fixture Q-A/Q-B/Q-R primary 均真实产生），`fallback_embedding` 由代码核验真实可达（repository.py:1219）。

**注意**：`embedding_stage` ≠ `compute_transactions.llm_call_stage` 列。RAG embedding 上报 `llm_call_stage=None`（repository.py:531 硬编码），stage 信息编码进 `idempotency_key` 而非 `llm_call_stage` 列。`LLM_CALL_STAGES = primary/retry_known_customer/retry_phone_goal/retry_combined`（services.py:35-40）用于 LLM chat consumer（如 0034 Preview），不含 `fallback_embedding`，不适用于 embedding consumer。独立 fixture 证据：4 consume txn `llm_call_stage` 全部 NULL（见 RQ-12 表）。

---

## Mock Boundary

独立确认：仅 mock `OpenAICompatibleClient.embed`（9100 最终外部 embedding API 边界）。mock 返回固定可审计结果（`model="rq5-approval-mock-embed"`，非 `"mock_for_test_only"`，否则 repository.py:519-520 跳过计费）。

**允许 mock**：外部 embedding provider（非确定性 + 网络不稳定 + 收费）。

**以下链全程真实，未 mock**：

```text
9100 search_with_diagnostics orchestration（execution 创建 + backend 分支 + finalize）
search execution persistence（rag_search_executions durable commit）
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

关键 compute 路径未被 mock——本轮达到 `PG_RUNTIME_VERIFIED`（DB-A execution 库）+ `APPLICATION_ROLE_RUNTIME_VERIFIED`（DB-B compute ledger 库）。9100 consumer 与 9000 经真实 loopback HTTP（urllib → TCP → uvicorn → FastAPI → route → record_usage），非 TestClient 旁路。

### Milvus Boundary

本轮 `RAG_VECTOR_BACKEND=sqlite`（9100 config），`search_with_diagnostics` 走 SQLite-only 分支（primary embedding + PG 词法 search），不依赖 Milvus。这是合法配置（非 mock consumer 逻辑、非绕过检索），9100 默认 `rag_vector_backend=sqlite`。本轮不修改生产 Milvus collection / 不写正式知识库 / 不重建 collection。

---

## Q-A First（RQ-6）— 独立 fixture

从真实 consumer 入口 `repository.search_with_diagnostics`（query="奥迪A6价格"，merchant_id=`rq5-approval`）执行一次 primary embedding 计费（`RAG_VECTOR_BACKEND=sqlite` → SQLite-only 分支 → `embedding_stage="primary"`）：

```text
Q-A execution_id    = 7（rag_search_executions.id，真实 PG 序列持久化，非硬编码）
lifecycle_status    = completed
identity            = rag_search_execution:7:primary（consumer 自然生成，非手工构造 key）
```

**A. Consumer 执行成功** ✅（execution COMPLETED，`_embed_with_usage` 被调用，`OpenAICompatibleClient.embed` mock 返回非 mock model → 计费路径触发）

**B. Compute Transaction = exactly 1**（独立 PG 查询，auto_wechat 库）：

```text
id=54 | idempotency_key=rag_search_execution:7:primary | transaction_type=consume | delta_tokens=-6
balance_after_tokens=99994 | capability_key=knowledge | model=rq5-approval-mock-embed
llm_call_stage=NULL | actual_tokens=6 | usage_measurement_method=estimated_tokens | payload_evidence IS NOT NULL
```

**C. Idempotency Identity 一致** ✅：`rag_search_execution:7:primary`

**D. Balance**（markup=0 → billed=actual=6；"奥迪A6价格" 6 字符）：

```text
balance_before = 100000   （fixture 充值后）
charge_delta   = -6       （billed_tokens=calculate_billed_tokens(6,0)=6）
balance_after  = 99994    （= 100000 + (-6)）✓
```

expected delta 由本 fixture 真实 usage contract 推导（`count_embedding_characters("奥迪A6价格")=6`，knowledge markup=0 → billed=6），非硬编码执行窗口 `-6`。独立推导结果一致。

**RQ-6 = PASS**

---

## Q-A Replay（RQ-7）— 独立 fixture NO_DOUBLE_CHARGE

对同一个 `execution_id=7`、同一 `primary` stage，经 consumer usage-report 路径 `_embed_with_usage(search_execution_id=7, embedding_stage="primary")` 再次调用（same identity，identity 由 repository.py:504 f-string 自然重新生成，模拟 daemon timeout 后 primary usage report 晚到重发 / crash 后 usage report 重试场景）：

**PostgreSQL 权威证据**（不靠 HTTP 200）：

```text
compute_transactions WHERE idempotency_key='rag_search_execution:7:primary' count = 1（未产生第 2 行）✓
account balance 仍 = 99994（replay 后未变）✓
balance_after_replay = 99994 = balance_after_first_execution ✓
no_double_charge = True ✓
```

**法证细节**：`compute_transactions.id` 序列为 54, 56, 57, 58（id=55 缺失）。id=55 被 replay 的 INSERT 占用后因 `uk_compute_transactions_merchant_idempotency` 唯一冲突触发 `IntegrityError` → rollback（PG 序列不回退，故 id 被消耗但无行）→ 进入 services.py:728-756 `idempotent_replay` 分支。该 id gap 印证 IntegrityError 幂等路径真实执行，而非"未尝试 INSERT"。

```text
same event → same idempotency identity → duplicate charge suppressed（replay）✓
NO_DOUBLE_CHARGE_VERIFIED
```

**Sequence Gap Classification**：id gap=55（独立 fixture）/ id gap=49（执行窗口）。两者均分类为 `SUPPLEMENTARY_RUNTIME_EVIDENCE ONLY`。sequence gap 不是幂等硬证据——正式硬证据仍是 same identity + one ledger transaction + unchanged balance（已满足）。id gap 仅印证 IntegrityError rollback 路径真实执行。

**RQ-7 = PASS**

---

## Q-B Distinct Execution（RQ-8）— 独立 fixture

创建另一 search execution（query="宝马X5多少钱"），同一 `primary` stage，从真实 consumer 入口执行：

```text
Q-B execution_id    = 8（≠ 7）
lifecycle_status    = completed
identity            = rag_search_execution:8:primary（consumer 自然生成）
```

**PostgreSQL 证据**：

```text
compute_transactions WHERE idempotency_key='rag_search_execution:8:primary' count = 1  ✓
id=56 | idempotency_key=rag_search_execution:8:primary | delta_tokens=-7 | balance_after_tokens=99987
```

两个不同 execution 合计 **2 个 distinct business-event identities**（`:7:primary` / `:8:primary`），无 collision / 共享 / 互相吞没：

```text
identity(Q-A) = rag_search_execution:7:primary
identity(Q-B) = rag_search_execution:8:primary
identity_distinct = True
different execution → different Business Event → independent charge  ✓
```

**RQ-8 = PASS**

---

## Q-R Stage Separation（RQ-9）— 独立 fixture + 方法论修正

Q-R 用 query="奔驰C级报价" 创建 execution_id=9，primary stage 由真实 `search_with_diagnostics` 产生（id=57）；同 execution_id 补 `fallback_embedding` stage：

```text
Q-R execution_id    = 9
lifecycle_status    = completed
```

同一 `execution_id=9`，两个不同 legitimate billable stage：

**Q-R primary**：
```text
identity = rag_search_execution:9:primary
transaction count = 1  ✓
id=57 | delta_tokens=-6 | balance_after_tokens=99981 | payload_evidence IS NOT NULL
```

**Q-R fallback_embedding**：
```text
identity = rag_search_execution:9:fallback_embedding
transaction count = 1  ✓
id=58 | delta_tokens=-6 | balance_after_tokens=99975 | payload_evidence IS NOT NULL
```

```text
identity(Q-R primary)          = rag_search_execution:9:primary
identity(Q-R fallback_embedding) = rag_search_execution:9:fallback_embedding
identity_distinct = True（same execution + different legitimate billable stage）
2 distinct Business Events / 2 legitimate charges / same execution 不互相吞没
same execution + different legitimate billable stage → independent billing events  VERIFIED
```

### ★ 方法论修正（APPROVED_WITH_CORRECTIONS 核心项）

**Stage Trigger Evidence 必须如实记录**：

本轮 Q-R `fallback_embedding` stage 的 runtime 计费证据是通过 **consumer usage-report seam**（`repository._embed_with_usage(search_execution_id=9, embedding_stage="fallback_embedding")` 直接传 stage 参数）获得，**非通过自然 Milvus primary 超时路径 runtime 触发**。

原因：本轮 `RAG_VECTOR_BACKEND=sqlite`（避免 Milvus 外部依赖），`search_with_diagnostics` 走 SQLite-only 分支（repository.py:936-941），该分支只产生 `primary`，不产生 `fallback_embedding`。`fallback_embedding` 仅在 Milvus 分支（`_search_milvus_or_fallback_with_diagnostics` repository.py:1116-1228）的 except 块（行 1219）当 `query_embedding` 为 None（primary 超时/返回空）时自然触发。本轮无 Milvus 治理任务（审批纪律第 18 节：Milvus 部分不是本轮治理任务），故 fallback 的"自然 Milvus 超时触发"runtime 证据不可得。

**分层证据**：

| 命题 | 证据等级 |
|---|---|
| `fallback_embedding` 是 ACTIVE/LEGITIMATE/BILLABLE stage（非 dead branch） | code-verified（repository.py:1219 真实可达，非仅日志 label）✅ |
| 同 execution + primary vs fallback_embedding → 2 distinct identity | runtime VERIFIED（独立 fixture：`:9:primary` ≠ `:9:fallback_embedding`）✅ |
| 各计费 1 次（不互相吞没） | runtime VERIFIED（独立 fixture：primary_count=1, fallback_count=1）✅ |
| `fallback_embedding` 经自然 Milvus primary 超时路径 runtime 触发 | **未验证**（本轮 sqlite backend + 无 Milvus 治理；仅 code-verified 可达）|

**identity 由 repository.py:504 f-string 自然重新生成**（非手工构造 fallback key 字符串）；`_embed_with_usage` 是真实 consumer 函数（非直接调 `record_usage`，非 monkeypatch stage selector）。这些符合审批纪律第 22 节。但 stage 参数 `"fallback_embedding"` 是脚本手工传入，而非自然 Milvus 超时产生——报告须明确标注。

**未来升级路径**（不阻断本轮）：若要将 RQ-9 升级到"runtime-naturally-triggered"证据等级，需用 `RAG_VECTOR_BACKEND=milvus` + Milvus test collection（非生产 collection，审批纪律第 18 节）+ mock primary embedding 返回 None（模拟 `_run_embed_with_hard_timeout` 超时，repository.py:463）→ Milvus search 抛异常 → except 块自然 fallback。属独立 Milvus 治理任务。

**裁定**：RQ-9 的核心命题（fallback_embedding 是 legitimate billable stage + 同 execution 不同 stage → 不同 identity → 各计费 1 次）由"code-verified 可达 + runtime 计费分离"共同支撑，不导致 double charge，不影响核心幂等结论。RQ-9 = PASS，但证据等级须标注为 `stage identity + 计费分离 runtime VERIFIED + 自然触发路径 code-verified（非 runtime-naturally-triggered）`。

**RQ-9 = PASS（with evidence-level correction）**

---

## Transaction / Balance（RQ-12）— 独立 fixture

独立 fixture（`rq5-approval` merchant）全部 consume txns（`auto_wechat` 应用角色只读）：

| id | idempotency_key | type | delta | balance_after | capability | model | stage | actual | method | payload_evidence |
|----|---|---|---|---|---|---|---|---|---|---|
| 54 | `rag_search_execution:7:primary` | consume | -6 | 99994 | knowledge | rq5-approval-mock-embed | NULL | 6 | estimated_tokens | NOT NULL |
| 56 | `rag_search_execution:8:primary` | consume | -7 | 99987 | knowledge | rq5-approval-mock-embed | NULL | 7 | estimated_tokens | NOT NULL |
| 57 | `rag_search_execution:9:primary` | consume | -6 | 99981 | knowledge | rq5-approval-mock-embed | NULL | 6 | estimated_tokens | NOT NULL |
| 58 | `rag_search_execution:9:fallback_embedding` | consume | -6 | 99975 | knowledge | rq5-approval-mock-embed | NULL | 6 | estimated_tokens | NOT NULL |

按 identity 计数：

| idempotency_key | txn_count |
|---|---|
| `rag_search_execution:7:primary` | 1 |
| `rag_search_execution:8:primary` | 1 |
| `rag_search_execution:9:primary` | 1 |
| `rag_search_execution:9:fallback_embedding` | 1 |

账户：

```text
merchant_id=rq5-approval / balance_tokens=99975
```

balance 推进（由本 fixture 真实 usage 推导，非硬编码执行窗口 99975）：

```text
100000 →(Q-A first -6)→ 99994 →(Q-A replay, 不变)→ 99994 →(Q-B -7)→ 99987 →(Q-R primary -6)→ 99981 →(Q-R fallback_embedding -6)→ 99975 ✓
final balance = initial(100000) + delta(Q-A primary -6) + delta(Q-B primary -7) + delta(Q-R primary -6) + delta(Q-R fallback_embedding -6)
              = 100000 + (-25) = 99975 ✓
Q-A replay does not contribute another delta ✓
```

4 distinct legitimate Business Events / 4 legitimate compute charges / replay 不二次计费。id=55 缺失（Q-A replay IntegrityError 消耗序列）。

**Balance Closure**：

```text
B_final(99975) = B_initial(100000) + Σ(distinct legitimate Business Event deltas: -6-7-6-6 = -25)
Q-A replay contributes 0 extra delta ✓
```

**RQ-12 = PASS**

---

## Non-null Identity（RQ-10）

独立 fixture 范围：

```text
compute_transactions WHERE merchant_id='rq5-approval' AND transaction_type='consume'
  AND (idempotency_key IS NULL OR idempotency_key = '') count = 0  ✓
```

RAG Query active charge path 产生的 identity 全部 NOT NULL / NOT EMPTY，且与冻结 contract 一致。无 `idempotency_key=None` 走旧兼容路径。

**Global Active None Audit 仍保留后续全局 Gate**（本轮仅审 RAG Query consumer + 本轮 fixture 范围，非全局所有 charge path）。

**RQ-10 = PASS**

---

## Cleanup（RQ-13）— 独立 fixture

独立 fixture 全部清理（分别以对应 principal）：

```text
DB-A xg_douyin_ai_cs（xg 角色）:
  DELETE FROM rag_search_executions WHERE merchant_id='rq5-approval'   → 已清

DB-B auto_wechat（auto_wechat 角色）:
  DELETE FROM compute_transactions WHERE merchant_id='rq5-approval'     → 已清
  DELETE FROM compute_accounts WHERE merchant_id='rq5-approval'         → 已清
```

residual 检查（独立 fixture 范围，全部 0）：

```text
compute_txns(rq5-approval)         = 0
compute_accounts(rq5-approval)     = 0
rag_search_executions(rq5-approval) = 0
```

DB Baseline 保持（migration state 不变）：

```text
auto_wechat:     revision=0034 / physical tables=61（不变）
xg_douyin_ai_cs: revision=0005（本轮 upgrade 后，审批未扰动）
```

临时 9001 端口 9000 uvicorn 进程已 terminate。验证脚本位于 worktree 外（`e:/work/tmp/rq5/`），未入 worktree（`git status` clean）。

```text
residual test data = 0
```

**RQ-13 = PASS**

---

## RQ Gate Verdict 汇总

| Gate | 验证内容 | 结论 | 证据 |
|---|---|---|---|
| RQ-0 | Git / environment | ✅ PASS | HEAD=803a452 / clean；2 文档 modified + 1 新报告；无业务代码/migration/M07/DB-BL 改动；LOCAL DEV，双 PG 库，PG 16.x |
| RQ-1 | 9100 PG environment | ✅ PASS | before=0004（表不存在）→ upgrade → after=0005（表存在）；migration graph 0001-0005 单链 head=0005 |
| RQ-2 | 9100 runtime principal | ✅ PASS | RAG_EXECUTION_DB_RUNTIME_PRINCIPAL=xg_douyin_ai_cs（非 superuser，非 postgres-as-consumer）；权限较宽登记为 future least-privilege gap |
| RQ-3 | 9000 compute ledger preconditions | ✅ PASS | auto_wechat canonical@0034/61表；uk 唯一约束存在；knowledge markup ratio 存在；app role DML PASS；/ready 200 postgresql |
| RQ-4 | Business Event Identity | ✅ PASS | `rag_search_execution:{search_execution_id}:{embedding_stage}` repository.py:504，来自稳定 execution.id，identity matrix 严格互斥，无 drift |
| RQ-5 | Migration 0005 / schema | ✅ PASS | 0005 revision 链合法；表/列/约束/索引/owner 与 migration 文件逐项一致；无 is_billed 列 |
| RQ-6 | Q-A first execution | ✅ PASS | 独立 Q-A(id=7) → 1 consume txn(id=54)，identity 一致，balance 100000→99994，actual_tokens=6，payload_evidence NOT NULL |
| RQ-7 | Q-A same-stage replay | ✅ PASS | 独立 Q-A replay → txn count 仍 1，balance 不变(99994)；id gap=55 印证 IntegrityError rollback；NO_DOUBLE_CHARGE_VERIFIED |
| RQ-8 | Q-B distinct execution | ✅ PASS | 独立 Q-B(id=8) → 1 独立 txn(id=56)，2 distinct identities，无 collision |
| RQ-9 | stage separation（primary+fallback_embedding）| ✅ PASS（with evidence-level correction）| 独立 Q-R(id=9) → primary(id=57)+fallback_embedding(id=58)，2 distinct stage identities；fallback 自然触发 code-verified（非 runtime-naturally-triggered） |
| RQ-10 | non-null identity | ✅ PASS | 0 null/empty idempotency_key（独立 fixture 范围）|
| RQ-11 | execution persistence | ✅ PASS | 独立 3 行 PG 持久(id=7/8/9)，lifecycle=completed，created_at NOT NULL，completed_at NOT NULL，identity 基于稳定 execution.id |
| RQ-12 | transaction / balance closure | ✅ PASS | 独立 4 consume txns(id 54,56,57,58)，delta=-6/-7/-6/-6，balance=99975=100000-25，replay 不贡献 delta，app role PASS |
| RQ-13 | cleanup / residual | ✅ PASS | 独立 residual=0，DB-BL auto_wechat 不变(0034/61)，xg_douyin_ai_cs=0005，临时进程清理，worktree clean |

`RQ-6 / RQ-7 / RQ-8 / RQ-9 / RQ-12` 均为独立审批窗口自有 fixture 的真实 `PG_RUNTIME_VERIFIED`（独立 merchant / 独立端口 / 独立 txn id，非采信执行窗口 48/50/51/52）。

---

## Historical Blocker Final Status

```text
HISTORICAL BLOCKED_BY_LOCAL_DOCKER_ENVIRONMENT:
RESOLVED（2026-08-11 独立审批 APPROVED_WITH_CORRECTIONS）

前置条件全部满足：
- Docker/local runtime available
- 9100 canonical PG reachable（xg_douyin_ai_cs）
- required migration applied（current=0005）
- runtime principal usable（xg_douyin_ai_cs，非 superuser）
- consumer real runtime PASS（独立 fixture 复现）
```

非"仅因 Docker 启动了就关闭"——Docker 启动是必要非充分条件。

---

## RAG Query Final Status

```text
RAG QUERY 0005 CONSUMER:
PG_RUNTIME_VERIFIED（APPROVED_WITH_CORRECTIONS，2026-08-11）

Business Event Identity:
rag_search_execution:{search_execution_id}:{embedding_stage}

Same execution + same stage:
NO_DOUBLE_CHARGE_VERIFIED（独立 Q-A replay → 1 txn / balance 不变 / id gap=55 印证 IntegrityError）

Distinct execution separation:
VERIFIED（独立 Q-B → 独立 charge / 2 distinct identities / 无 collision）

Distinct stage separation:
VERIFIED（独立 Q-R primary + fallback_embedding → 同 execution 不同 stage → 2 独立 charge；
         fallback 自然触发 code-verified，非 runtime-naturally-triggered）

RAG_EXECUTION_DB_RUNTIME_PRINCIPAL:
xg_douyin_ai_cs（非 superuser；权限较宽登记为 future least-privilege gap；
                不写 APPLICATION_ROLE_RUNTIME_VERIFIED）

COMPUTE_LEDGER_APPLICATION_ROLE_RUNTIME_VERIFIED:
auto_wechat（已批准 application-role model，2026-08-10 APPROVED）
```

---

## Corrections 清单（不改变核心结论）

1. **Q-R fallback_embedding 触发性质**（核心 correction）：报告 `P1_PG_RAG_QUERY_0005_CONSUMER_VERIFICATION.md` §16 须明确标注 `fallback_embedding` 的 runtime 计费证据经 consumer usage-report seam（`_embed_with_usage` 直接传 `embedding_stage` 参数）获得，非通过自然 Milvus primary 超时路径 runtime 触发。fallback 自然可达性由静态代码（repository.py:1219）证明（code-verified reachable），runtime 仅证明 stage identity 分离 + 计费分离行为。RQ-9 证据等级标注为 `stage identity + 计费分离 runtime VERIFIED + 自然触发路径 code-verified（非 runtime-naturally-triggered）`。未来升级到 runtime-naturally-triggered 需 Milvus test collection + 模拟 primary 超时（独立 Milvus 治理任务）。

2. **9100 principal 权限较宽**：`xg_douyin_ai_cs` 角色持有 CREATE/TRUNCATE/REFERENCES/TRIGGER（较 `auto_wechat` DML-only model 宽）。登记为 `RUNTIME_PRINCIPAL_CAPABILITY_OBSERVATION` / future least-privilege governance gap。不得写 `least privilege verified`。本轮如实写 `RAG_EXECUTION_DB_RUNTIME_PRINCIPAL_VERIFIED`（非 `APPLICATION_ROLE_RUNTIME_VERIFIED`）。报告 §4 已部分提及，本审批正式登记。

3. **9100 canonical dev config 默认 SQLite**：`.env.development.example` / `.env.lan.local` 的 `RAG_DATABASE_URL=sqlite`，本轮 consumer PG runtime 证据用 env override（`RAG_DATABASE_URL=postgresql+psycopg://...`）产生，等价生产 runtime path（`.env.production.example` 即 PG）。非造假，但说明 9100 本地 dev 默认不走 PG——dev/prod config 分裂事实，如实记录。

---

## Aggregate Consumer PG Status

```text
0032 Daily Report          ✅ PG_RUNTIME_VERIFIED
0033 M05 Material Analysis ✅ PG_RUNTIME_VERIFIED
0034 AI Preview            ✅ PG_RUNTIME_VERIFIED
RAG Query 0005             ✅ PG_RUNTIME_VERIFIED（本轮，APPROVED_WITH_CORRECTIONS）

P1 ACTIVE CONSUMER PG VERIFICATION:
COMPLETE（4/4）
```

```text
COMPUTE-IDEMPOTENCY-001 = OPEN
TECHNICAL_CLOSURE        = PENDING
```

RAG Query 0005 consumer PG verification 完成 ≠ P1 Technical Closure Complete（≠ E2E_VERIFIED_FIXED）。

---

## P1 Remaining Technical Closure

若 RAG Query 审批通过，剩余正式 P1 Technical Closure 工作：

```text
1. LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP   = OPEN
   （init SQL 仍 OWNER auto_wechat，当前运行库 COMPLIANT 但 fresh bootstrap NOT YET COMPLIANT；
    不阻断当前 consumer PG verification，须在 next clean bootstrap 或 P1 final closure 前关闭）

2. Global Active None Audit                       = OPEN
   （重新全局搜索所有 charge-producing 路径，确认 idempotency_key=None 的 active 生产路径 = 0；
    本轮仅审 RAG Query + fixture 范围，非全局）

3. Final PostgreSQL Concurrent Closure Gate       = OPEN
   （duplicate same business event / same payload / different payload conflict / consumer identity preservation；
    最终 PG 并发闭环验证）
```

```text
A.   auto_wechat schema baseline              = REMEDIATED（DB-BL-2D，canonical@0034）
A′.  LOCAL_PG_BOOTSTRAP_DATABASE_OWNER_DRIFT_GAP = OPEN（本轮未改）
B.   RAG Query 0005 PG                        = 本轮完成（PG_RUNTIME_VERIFIED，APPROVED_WITH_CORRECTIONS）
C.   Global Active None Audit                 = OPEN（本轮仅审 RAG Query + fixture 范围）
D.   Final PostgreSQL Concurrent Closure Gate = OPEN
```

---

## RAG_QUERY_REQUEST_RECOVERY_GAP

```text
RAG_QUERY_REQUEST_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1
（保持冻结，本轮未触碰、未扩大、未修）
```

本轮 same-execution replay（Q-A replay）验证的是 **same execution + same stage 的技术重放幂等**（idempotent replay safety = VERIFIED），对应 daemon timeout 后 primary usage report 晚到重发 / crash 后 usage report 重试路径——证明同一 execution_id 重报不会 double charge（`NO_DOUBLE_CHARGE_VERIFIED`）。

本轮**不**验证 / 不解决：

- whole search request retry（上游重新调 `search_with_diagnostics`）→ 新 Execution → 新 key → 新 charge（`RAG_QUERY_REQUEST_RECOVERY_GAP` 关注的 full-request retry 识别）
- crash recovery / lost request recovery / worker restart recovery / retry orchestration redesign

不写 `Request recovery orchestration = RESOLVED`。这些属 `Final PostgreSQL Concurrent Closure Gate` 与 reliability gap 范畴，不阻断 RAG Query 0005 consumer PG verification。

---

## RB-10 Classification

```text
RB-10 CLEANUP = NOT AUTHORIZED（继续保持）
```

不把 RB-10 列为 COMPUTE-IDEMPOTENCY-001 技术闭环的必过项，除非后续有新的正式治理决策修改该范围。

---

## Commit Authorization

审批通过（APPROVED_WITH_CORRECTIONS），授权执行窗口做独立 RAG Query closure checkpoint。允许：

```text
docs/architecture/remediation/P1_PG_RAG_QUERY_0005_CONSUMER_VERIFICATION.md（须按 Corrections 清单修正 §16 措辞）
docs/architecture/remediation/P1_PG_RAG_QUERY_0005_CONSUMER_APPROVAL.md（本审批报告）
docs/ai/05_PROJECT_CONTEXT.md
docs/architecture/remediation/P1_CHECKPOINT_11_OF_11_CONSUMER_MIGRATION_COMPLETE.md
```

不得混入：

- 业务代码
- migration 修改
- Bootstrap Owner Drift 修复
- Global Active None Audit
- Final Concurrent Closure
- RB-10

建议 commit message：

```text
验证：闭环RAG Query 0005 PostgreSQL幂等计费
```

---

## 审批窗口纪律遵守

- ✅ 不采信执行窗口自述：独立 fixture（`rq5-approval` merchant / 端口 9001 / 独立 txn id 54/56/57/58）复现全部核心命题
- ✅ 不扰动 canonical DB：独立 fixture 写入后全部清理（residual=0），alembic state 不变（0005/0034/61表）
- ✅ 未为"复现 before=0004"而 downgrade 0005→0004
- ✅ 未修改业务代码 / migration 0005 内容 / M07 Core / DB-BL / `_embed_with_usage` / `record_usage` / 余额门禁
- ✅ 未设计/整改 9100 IAM（如实登记 future least-privilege gap）
- ✅ 未开始 Global Active None Audit / Final Concurrent Closure / RB-10 / bootstrap owner drift 修复
- ✅ DB-B compute ledger 侧未用 superuser 替代 app role 完成 consumer 核心写入（postgres 仅 catalog inspection）
- ✅ consumer 验证仅 mock 外部 embedding API
- ✅ 未触碰 `RAG_QUERY_REQUEST_RECOVERY_GAP`（OUT_OF_P1）
- ✅ 未真实发送抖音私信 / 微信 / 未修改 lead/customer facts / 未调用真实 LLM / embedding / Milvus

---

> 审批完成。按指令第 40 节：完成后停止。
> 不自行开始 Bootstrap Owner Drift、Global Active None Audit 或 Final Concurrent Closure。
