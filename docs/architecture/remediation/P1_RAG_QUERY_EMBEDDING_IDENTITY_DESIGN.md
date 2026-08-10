# P1 RAG Query Embedding Execution Identity 技术设计（Stage 5H-1）

> 状态：TECHNICAL_DESIGN_IN_PROGRESS（只设计，不实施）
> 前置：Register #10a RAG Query Embedding 当前 = EXECUTION_IDENTITY_DESIGN_GAP
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #10a；边界涉及 #10b RAG Ingest（共用 `_embed_with_usage`）
> 范围：设计 RAG Query Embedding 计费点的稳定幂等身份，回答"什么构成一次 query embedding 的独立计费身份"
> 核心难点：daemon timeout 边界（primary daemon 晚完成时 usage report 与 SearchExecution lifecycle 的关系）
> 下一步：审查通过后授权实施（不在本 Stage 实施）

## 硬需求（开篇）

**P1 需要在 RAG Query Embedding 计费点构造稳定幂等身份。**

- 当前 `_embed_with_usage`（Query 路径，L441）不传三参数 → `idempotency_key=None`（无 M07 保护）。
- RAG Query 是 **9100 内部 RAG 能力**，可能被多 consumer 调用（reply_decision_service / training ask / 其他 RAG consumer）。
- Query 无 run/document/chunk 概念，**不能复用** RAG Ingest 的三参数（`run_id`/`document_id`/`chunk_index`），需独立 identity。
- billing truth 仍只归 M07 committed ComputeTransaction；Execution 无 is_billed。

## 当前事实（已验证，file:line）

### 统一入口 search_with_diagnostics（L908）
```
search_with_diagnostics(payload, llm_client) L908
  if settings.rag_vector_backend == "milvus":
    return _search_milvus_or_fallback_with_diagnostics(payload, ...) L913   # Milvus path
  return RagSearchResult(items=_search_sqlite(payload, ...), ...) L914-917  # SQLite-only path
```
- `search`（L920）= `search_with_diagnostics(...).items`（统一入口包装）

### Milvus path：_search_milvus_or_fallback_with_diagnostics（L1037）
```
_search_milvus_or_fallback_with_diagnostics(payload) L1037
  query_embedding = None L1068  # 预初始化，供 except 安全引用
  try:
    client = OpenAICompatibleClient() L1070
    query_embedding_payload = _run_embed_with_hard_timeout(client, payload.query, ...) L1071  # ★ primary embedding（计费源 1）
    query_embedding = _coerce_embedding(...) L1075
    if not query_embedding: raise ValueError("query embedding is empty") L1076-1077  # primary 超时返回空
    # Milvus daemon 线程搜索
    _milvus_worker（daemon thread）L1090-1098
    _milvus_done.wait(timeout=_MILVUS_SEARCH_TIMEOUT_SECONDS) L1102  # 超时 raise TimeoutError
    ranked_result = ... L1109
    return RagSearchResult(items=ranked_result, ...) L1120-1123  # ★ 1:1 正常（只 primary embedding 计费）
  except Exception as exc: L1124
    # fallback：复用已算 embedding（避免 120s 重复累积）
    return RagSearchResult(
        items=_search_sqlite(payload, query_embedding=query_embedding), ... L1135-1139  # ★ fallback
    )
```

### 两种 fallback 计费形态（★关键）

| 场景 | query_embedding 状态 | _search_sqlite 内部 | 计费次数 |
|---|---|---|---|
| Milvus search 失败（embedding 已算成功） | 非空（L1075） | 复用，不重新 embedding（L1180 `if query_embedding is None` 不成立） | 1:1（只 primary 计费） |
| primary embedding 本身超时（返回空） | None（L1068 初始 / L1075 coerce 空 → L1077 raise） | `query_embedding is None` → L1182 重新 embedding | 1:2（primary + fallback_embedding 两次计费） |

### _search_sqlite 内部 embedding（L1143）
```
_search_sqlite(payload, *, query_embedding=None) L1143
  ...
  if query_embedding is None: L1180
    query_embedding_payload = _run_embed_with_hard_timeout(client, payload.query, ...) L1182  # ★ fallback embedding（计费源 2）
    query_embedding = _coerce_embedding(...) L1186
  if query_embedding: L1206
    vector_scored = cosine_similarity(...) L1212
    return _to_search_items(vector_scored[:top_k]) L1232
```

### _embed_with_usage（L463）Query 路径
- `_run_embed_with_hard_timeout`（L419）的 `_worker`（L439）调用 `_embed_with_usage(client, text, merchant_id, remark)`（L441）
- Query 路径不传 `run_id`/`document_id`/`chunk_index` → 三参数全 None → `idempotency_key=None`（5E-3 partial identity 三态的 ALL ABSENT 分支）
- **Query 需独立 identity**（不能复用 Ingest 三参数，Query 无 run/document/chunk）

### primary daemon 边界
- `_milvus_worker`（L1090）是 daemon 线程，超时后主流程不 join（L1102 wait 超时即 raise），底层 gRPC 线程自行结束（可能晚完成）。
- **embedding daemon**（`_run_embed_with_hard_timeout` 的 `_worker` L439）同理：超时返回空 embedding，但底层 embedding API 线程可能晚完成 → primary usage report 可能晚到。

---

## Q1. RagSearchExecution 由 9100 创建还是上游调用方创建？

**答：9100 创建（倾向）。**

理由：
- RAG Query 是 **9100 内部 RAG 能力**（非 9000→9100 跨进程），`search_with_diagnostics`（L908）入口在 9100。
- 可能被**多 consumer** 调用（reply_decision_service / training ask / 其他 RAG consumer），9100 统一创建避免每个上游调用方自己建 identity（职责错位 + 重复）。
- 与 RAG Ingest（9100 内部，TrainingRun 在 9100 创建）同模式：9100 自有能力的 identity 在 9100 创建。

**对比**：Daily Report / Return Visit / Preview 是 9000→9100 跨进程，identity 在 9000 创建 + 透传。RAG Query 是 9100 内部，identity 在 9100 创建。

---

## Q2. 哪个统一入口代表"一次 logical search"，避免 fallback 误建第二 Execution？

**答：`search_with_diagnostics`（L908）是统一入口。SearchExecution 必须在该函数开头创建，先于进入 `_search_milvus_or_fallback_with_diagnostics`（L913）或 `_search_sqlite`（L915）。**

**★关键约束：不得在 `_search_sqlite`（L1143）内创建 SearchExecution。**

理由：
- Milvus path 的 fallback 走 `_search_sqlite(query_embedding=已算)`（L1136）——此时 primary embedding 已计费，fallback 复用 embedding 不计费（1:1）。
- 若在 `_search_sqlite` 内创建 SearchExecution，则 fallback 会建第二个 Execution → primary（L1071）与 fallback（L1182）分属不同 Execution → 失去共同 parent → 无法表达"同一次搜索的 primary + fallback_embedding" → cardinality 错乱。
- **SearchExecution 必须在统一入口 `search_with_diagnostics`（L908）创建**，primary 与 fallback 共用同一 execution_id。

```
search_with_diagnostics(payload) L908
  execution = RagSearchExecution(merchant_id=payload.merchant_id, ...)  # ★ 统一入口创建
  db.add(execution); db.commit()                                          # durable before primary daemon
  if settings.rag_vector_backend == "milvus":
    return _search_milvus_or_fallback_with_diagnostics(payload, execution_id=execution.id)
  return RagSearchResult(items=_search_sqlite(payload, execution_id=execution.id), ...)
```

---

## Q3. SearchExecution 必须在 primary daemon 启动前 durable commit

**答：是。** SearchExecution 在 `search_with_diagnostics`（L908）开头创建并 commit，先于 `_search_milvus_or_fallback_with_diagnostics`（L913）内的 primary embedding daemon（L1071 `_run_embed_with_hard_timeout`）。

满足 P1 硬约束：Business Event Identity 必须在收费副作用前稳定持久存在。primary embedding（计费源）在 L1071，execution commit 在其前。

---

## Q4. primary 与 fallback 必须复用同一 search_execution_id

**答：是。** execution_id 从 `search_with_diagnostics`（L908）透传到 `_search_milvus_or_fallback_with_diagnostics`（L1037）→ 透传到 `_search_sqlite`（L1143）→ 透传到 `_embed_with_usage`（L463，fallback 重新 embedding 时 L1182）。

- primary embedding（L1071）：`_embed_with_usage(..., search_execution_id=execution.id, embedding_stage="primary")`
- fallback embedding（L1182）：`_embed_with_usage(..., search_execution_id=execution.id, embedding_stage="fallback_embedding")`
- 两者共用同一 `search_execution_id`，不同 `embedding_stage` → 不同 key → 最多 2 条独立合法 ComputeTransaction。

---

## Q5. timeout 后 primary daemon 晚完成时，usage report 如何继续使用原来的 primary key

**答：primary daemon 晚完成的 usage report 仍用原来的 `primary` key（`rag_search_execution:{execution_id}:primary`），是合法独立 charge。**

daemon timeout 边界时序：
```
SearchExecution E1 durable commit
→ primary embedding daemon starts（_run_embed_with_hard_timeout L1071）
→ primary times out from caller perspective（返回空 embedding，L1075 coerce 空）
→ caller raises ValueError（L1077）→ except（L1124）
→ fallback_embedding starts（_search_sqlite L1182 重新 embedding）
  → _embed_with_usage(..., stage="fallback_embedding")  # E1:fallback_embedding key
→ fallback succeeds → search completes → E1 = completed

稍后：
primary daemon actually completes（底层 embedding API 返回）
→ primary usage report arrives（daemon 线程内 _embed_with_usage 已在 timeout 前调用 report_usage）
  → E1:primary（rag_search_execution:{E1}:primary key，合法独立 charge）
→ E1.status=completed 不因 daemon 晚报告而无效
```

**★ 关键不变量：SearchExecution.status ≠ individual embedding stage status ≠ billing truth。**

- E1.status=completed 表示整次搜索请求完成（fallback 已成功返回结果）。
- primary daemon 晚完成的 usage report 是独立的 billing 事件（E1:primary key），不受 E1.status 影响。
- M07 committed ComputeTransaction 是唯一账本；E1.status 不回滚/否认已 committed 的 primary charge。

> **实施注记**：当前 `_run_embed_with_hard_timeout` 的 daemon 线程（L439 `_worker`）在 timeout 前若已完成 `_embed_with_usage`（含 report_usage），则 primary charge 已 committed；timeout 后主流程返回空 embedding 但 daemon 线程继续，usage report 已发出。若 daemon 在 timeout 后才完成 `_embed_with_usage`，则 primary charge 晚到但仍用同一 key（M07 幂等保护 replay）。设计不改变此 daemon 行为，只确保 identity 维度可用。

---

## Q6. SearchExecution 的 completed/failed 表示整个搜索请求，而非某个 embedding stage

**答：是。** SearchExecution lifecycle = 整次搜索请求结果：

| 场景 | E1.status | 计费 |
|---|---|---|
| Milvus 正常（primary embedding + Milvus search 成功） | completed | 1 charge（primary） |
| primary embedding 成功 + Milvus search 失败 + fallback 复用 embedding 成功 | completed | 1 charge（primary；fallback 复用不计费） |
| primary embedding 超时 + fallback 重新 embedding 成功 | completed | 2 charges（primary + fallback_embedding） |
| primary + fallback 都失败（搜索失败） | failed | 2 charges（若两者 embedding 都计费）或 0/1（视失败点） |

**★ E1.status ≠ billing truth**：E1=completed 不意味着"只 1 charge"，E1=failed 不意味着"0 charge"。committed ComputeTransaction 是唯一账本（类比 M05/Preview C1 红线：已成功计费不因后续失败回滚）。

---

## Q7. whole-request retry 创建新 Execution 的问题登记 RAG_QUERY_REQUEST_RECOVERY_GAP

**答：whole-request retry 创建新 Execution 是 OUT_OF_P1 的可靠性 Gap。**

- **same execution + same stage replay → P1 保护**（同 key → M07 IDEMPOTENT_REPLAY）。
- **whole-request retry（上游重新调 `search_with_diagnostics`）→ 新 Execution → 新 key → 新 charge**：无 durable client request identity 证明 E1==E2（同 DAILY_REPORT/TRAINING/PREVIEW_REQUEST_RECOVERY_GAP）。

**RAG_QUERY_REQUEST_RECOVERY_GAP = OPEN / RELIABILITY / OUT_OF_P1**：whole search request retry 后无法识别新调用是旧 request replay。与已登记的 REQUEST_RECOVERY_GAP 同口径，P1 不解决。

---

## Q8. Query 正式链完成后 idempotency_key=None=0，不影响 RAG Ingest 已冻结 key

**答：是。** Query 用独立 namespace `rag_search_execution`，不触碰 RAG Ingest 的 `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`。

- `_embed_with_usage`（L463）共享函数：Query 与 Ingest identity 各自构造（类比 5E-3 已落地的 partial identity 规则）。
- Query 路径传 `search_execution_id` + `embedding_stage`（非 run_id/document_id/chunk_index）。
- Ingest 路径传 `run_id`/`document_id`/`chunk_index`（已冻结，5E-3）。
- partial identity 三态需扩展：Query 的 `search_execution_id`/`embedding_stage` 与 Ingest 的三参数互斥（mixed → warning 不构造畸形 key）。

---

## 候选 identity（设计阶段，不登记最终 contract）

```
event_namespace = rag_search_execution
business_event_id = {search_execution_id}:{embedding_stage}
idempotency_key = f"rag_search_execution:{search_execution_id}:{embedding_stage}"

embedding_stage = primary / fallback_embedding
cardinality = 1 SearchExecution : up to 2 embedding charge events
```

---

## daemon timeout 边界设计（核心难点，Q5 详述）

**核心不变量：SearchExecution.status ≠ individual embedding stage status ≠ billing truth。**

- SearchExecution E1 durable commit（整次搜索请求）
- primary embedding daemon（可能 timeout 返回空，但底层线程晚完成 → primary usage report 晚到）
- fallback_embedding（若 primary 空，重新 embedding）
- E1.status = 整次搜索请求结果（completed/failed），与 primary daemon 是否晚报告无关
- primary daemon 晚完成的 usage report 用原 `primary` key（合法独立 charge，M07 已 committed 不回滚）

---

## 不变式（3 条）

1. **same execution + same stage billing replay → same key → REPLAY**：execution_id + stage 不变 → 同 key → M07 IDEMPOTENT_REPLAY
2. **same execution + different stage（primary vs fallback_embedding）→ different key → up to 2 charges**：embedding_stage 维度区分，同一搜索请求最多 2 次合法计费
3. **explicit new search request → NEW execution → NEW key（合法新消费）**：每次 `search_with_diagnostics` 调用新建 execution → 新 execution_id → 新合法消费

---

## 边界注明

### 不影响 RAG Ingest 已冻结 key
- Query 用独立 namespace `rag_search_execution`，不触碰 Ingest 的 `rag_embedding:...:ingest`。
- `_embed_with_usage` 共享函数，Query 与 Ingest identity 各自构造（partial identity 三态扩展，互斥）。

### 统一入口避免 fallback 误建第二 Execution（★ Q2 核心）
- SearchExecution 必须在 `search_with_diagnostics`（L908）创建，不在 `_search_sqlite`（L1143）内创建。
- primary（L1071）与 fallback（L1182）共用同一 execution_id。

### billing truth 归 M07
- 本设计只构造 idempotency_key，不改 M07 core / `record_usage`。
- committed ComputeTransaction 是唯一 billing truth；SearchExecution 不持有 billing 状态。
- SearchExecution.status = 整次搜索请求结果，≠ individual embedding stage status，≠ billing truth。

### 不宣称解决 daemon timeout 后的自动 billing recovery
- daemon 晚完成的 usage report 用原 primary key（M07 replay 保护），但**不保证** daemon 一定完成或 report 一定到达。
- 若 daemon 在 `_embed_with_usage`（含 report_usage）前被 kill，则 primary charge 未发生（未 commit），不构成 billing truth——这是 daemon 线程不可靠性，属可靠性范畴。
- **不宣称**解决 daemon timeout 后的自动 billing recovery（若有独立 Gap，登记 OUT_OF_P1）。

---

## 硬约束（冻结）

1. **SearchExecution durable commit before primary embedding daemon**（identity 先于计费副作用持久化）
2. **execution_id finalize 后不清空（永久保留）**（支持 replay）
3. **统一入口 `search_with_diagnostics`（L908）创建 SearchExecution**，不在 `_search_sqlite` 内创建（避免 fallback 误建第二 Execution）
4. **primary 与 fallback 复用同一 execution_id**，不同 embedding_stage → 不同 key
5. **SearchExecution.status = 整次搜索请求结果**（非 individual embedding stage status，非 billing truth）
6. **billing truth = committed ComputeTransaction**；SearchExecution 无 is_billed
7. **不引入 attempt_count**（YAGNI，1:N(2) 用 embedding_stage 区分）
8. **用独立 namespace `rag_search_execution`**，不污染 RAG Ingest `rag_embedding` 合同
9. **登记 RAG_QUERY_REQUEST_RECOVERY_GAP**（whole-request retry，OUT_OF_P1）

---

## 待审批决策点

1. ~~RagSearchExecution owner~~ → **倾向 9100 创建**（RAG Query 是 9100 内部能力，待审查确认）
2. 库归属 → 9100 创建则 xg_douyin_ai_cs 库（与 KnowledgeTrainingExecution 同库，待方案确认）
3. `search_execution_id` / `embedding_stage` 透传方式（`_embed_with_usage` 扩展两可选参数 + partial identity 三态扩展）→ 实施期决策，不冻结
4. candidate key `rag_search_execution:{search_execution_id}:{embedding_stage}` → 审查通过后登记为最终 contract
5. daemon 晚完成 usage report 的 key 复用（primary key，M07 replay）→ 实施期确认 daemon 行为不改变，只加 identity
6. 审查通过后授权实施（新建 RagSearchExecution 实体 + migration + `search_with_diagnostics` 改造 + `_embed_with_usage` 扩展 + `_search_sqlite`/`_search_milvus_or_fallback` 透传 + 7 Gate）
