# P1 RAG Ingest Chunk Embedding 幂等技术设计（Stage 5E-2）

> 状态：TECHNICAL_DESIGN_APPROVED（只设计，不实施）
> 前置：Register #10b RAG Ingest Chunk Embedding 当前 = CHILD_EXECUTION_IDENTITY_DESIGN_GAP（Parent TrainingRun.id VERIFIED，缺 child discriminator）
> 关联：`P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md` Charge Path #10b；边界涉及 #10a RAG Query Embedding
> 范围：设计 RAG Ingest chunk embedding 计费点的稳定幂等身份，回答"什么构成一次 chunk embedding 计费的唯一身份"
> 下一步：审查通过后授权实施（不在本 Stage 实施）

## 硬需求（开篇）

**P1 需要在 RAG Ingest chunk embedding 计费点构造稳定幂等身份。**

- Parent（TrainingRun.id）已验证：embedding 前已生成（`_create_training_run` INSERT RETURNING id）。
- Child discriminator（document_id + chunk_index）在 embedding 前已可得（`enumerate(chunk_text(...), start=1)`）。
- **不新增表、不预 INSERT chunk row，最小改动**：现有 `rag_training_runs` / `knowledge_chunks` / `_embed_with_usage` 结构充分。
- billing truth 仍只归 M07 committed ComputeTransaction。

## 当前事实（已验证，file:line）

两条 Ingest 路径共用 `_embed_with_usage`：

### 路径 1：train_document（`repository.py:496`）
```
train_document(document_id) L496
  conn = get_rag_engine().connect() L504
  doc = SELECT knowledge_documents WHERE id=... L505
  run_id = _create_training_run(conn, payload, document_id) L522   # INSERT RETURNING id（事务内，未单独 commit）
  UPDATE knowledge_chunks SET is_active=false WHERE document_id L534
  for index, chunk in enumerate(chunk_text(doc["content"]), start=1) L544
    digest = sha256(chunk) L545
    embedding = _embed_with_usage(client, chunk, merchant_id, remark="knowledge_training_ingest") L546  # ★ 计费点
    INSERT knowledge_chunks ON CONFLICT (document_id, content_hash) DO NOTHING L550-561
    UPDATE knowledge_chunks SET is_active=true, embedding_json=... L577-595  # 重跑：复用旧行 + UPDATE
  UPDATE rag_training_runs SET status='completed' WHERE id=run_id L619-629
  conn.commit() L630  # ★ 整个 run（含 run_id 行）在此 commit
```

### 路径 2：train_scope（`repository.py:653`）
```
train_scope(payload) L653
  conn = get_rag_engine().connect() L655
  run_id = _create_training_run(conn, payload) L656   # INSERT RETURNING id（事务内，未单独 commit）
  docs = SELECT knowledge_documents WHERE scope=... L657
  UPDATE knowledge_chunks SET is_active=false WHERE scope L675
  for doc in docs L689
    for index, chunk in enumerate(chunk_text(doc["content"]), start=1) L690
      digest = sha256(chunk) L691
      embedding = _embed_with_usage(client, chunk, merchant_id, remark="knowledge_training_ingest") L692  # ★ 计费点
      INSERT knowledge_chunks ON CONFLICT (document_id, content_hash) DO NOTHING L696-707
      UPDATE ...（同 train_document 结构）
```

### 共享 helper：_embed_with_usage（`repository.py:463`）
```python
def _embed_with_usage(*, client, text, merchant_id, remark=None) -> dict:
    result = client.embed(text)
    model = ...
    if model and model != "mock_for_test_only" and merchant_id:
        tokens = count_embedding_characters(text)
        ComputeUsageClient().report_usage(
            merchant_id=..., tokens=tokens, source="embedding",
            capability_key="knowledge", model=model, remark=remark,
            usage_measurement_method="estimated_tokens", llm_call_stage=None,
            # ★ 当前无 idempotency_key（P1 待迁移）
        )
    return result
```

### Query 路径也调用 _embed_with_usage（`repository.py:441`）
search path 的超时保护 wrapper `_embed_with_usage` 在 `:441` 被调用，remark 为 query 维度。**Ingest 与 Query 共享同一 helper。**

### chunk_text（确定性切分）
`chunk_text` 纯函数，固定 `chunk_size=500, overlap=80`，同一 content 永远切成相同序列（同序同内容同 index）。

### ON CONFLICT DO NOTHING + UPDATE 复用
重跑同一 run/document 时（L560 ON CONFLICT DO NOTHING），旧行被复用，但 embedding 重新计算并 UPDATE（L577-595）→ 同 run 同 chunk 重跑 = 技术 replay（应 REPLAY）；new run 同 chunk = 合法新消费。

---

## Q1. train_document / train_scope 如何把 run_id / document_id / chunk_index 传入 _embed_with_usage？（透传链路）

**当前缺失**：`_embed_with_usage(client, text, merchant_id, remark)` 签名不含 run_id / document_id / chunk_index。`report_usage` 不传 `idempotency_key`。

**实施方向（不冻结字段名）**：
- `_embed_with_usage` 签名扩展三个可选参数（向后兼容 Query 路径）：
  - `run_id: int | None = None`
  - `document_id: int | None = None`
  - `chunk_index: int | None = None`
- 三者非空 → Ingest 路径 → 构造 identity key
- 任一为 None → 不构造 key（Query 路径 / 旧调用 / 测试双打兼容）

**透传链路**：
```
train_document L546:
  _embed_with_usage(client, chunk, merchant_id, remark="knowledge_training_ingest",
                    run_id=run_id, document_id=doc["id"], chunk_index=index)
train_scope L692:
  _embed_with_usage(client, chunk, merchant_id, remark="knowledge_training_ingest",
                    run_id=run_id, document_id=doc["id"], chunk_index=index)
```
`run_id`（L522/L656 已生成）、`doc["id"]`（L505/L657 已 SELECT）、`index`（L544/L690 enumerate 可得）三者在 `_embed_with_usage` 调用前均已可得——**identity 维度 embedding 前已齐备**。

---

## Q2. _embed_with_usage 同时服务 Query + Ingest，如何只让 Ingest 构造 identity 不误伤 Query？（P4）

**答**：通过参数存在性区分，不改 Query 行为。

| 路径 | run_id/document_id/chunk_index | idempotency_key | None count |
|---|---|---|---|
| Ingest（train_document/train_scope） | 均非空 | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` | Ingest None=0 |
| Query（search L441） | 均 None（不传） | None | Query 仍 None（独立 #10a Charge Path） |

**P4 约束**：`_embed_with_usage` 是共享函数，**只有 Ingest 构造 identity；Query 路径仍 None**。Query Embedding 是独立 #10a Charge Path，不合并、不迁移。None count 只记 "RAG Ingest None=0"，不宣称 Query Embedding 已迁移。

实施要点：identity 构造逻辑写在 `_embed_with_usage` 内（三参数非空时），Query 调用点（L441）不传这三个参数 → 自动走 None 兼容路径。**不新增第二个 helper**（YAGNI，共享函数加可选参数最小改动）。

---

## Q3. final key namespace/operation string 是什么？（冻结）

```
event_namespace = rag_embedding
business_event_id = {run_id}:{document_id}:{chunk_index}:ingest
idempotency_key = f"rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest"
```

- **Parent**: TrainingRun.id（VERIFIED，`_create_training_run` INSERT RETURNING id，embedding 前生成）
- **Child discriminator**: document_id + deterministic chunk_index（`enumerate(chunk_text(...), start=1)`，embedding 前可得）
- **Operation**: `ingest`（区分 Query Embedding 的 query 维度，不同 Charge Path 不合并）
- **chunk_hash**: 不进入 billing 唯一性主维度（P3），保持 content_hash 数据去重 / semantic evidence

---

## Q4. same chunk billing replay 如何验证？（RI-1）

**RI-1 Same Chunk Replay**：Run1 / Doc10 / Chunk3，`report_usage` 两次 → 1 txn / replay / 1 debit。

时序：L546 `_embed_with_usage` 构造 `rag_embedding:1:10:3:ingest` → HTTP → 9000 `record_usage` INSERT → commit。重跑同 run/doc/chunk → ON CONFLICT DO NOTHING（L560）复用旧行 + UPDATE embedding（L577）→ `_embed_with_usage` 再构造同一 key → M07 `IDEMPOTENT_REPLAY`，不重复扣。

**前提**：重跑必须是同 run（同 run_id）。若 new run → 新 run_id → 新 key → 新消费（RI-4）。

---

## Q5. different chunk in same run 如何验证？（RI-2）

**RI-2 Different Chunks**：Run1 / Doc10 / Chunk3 + Chunk4 → 2 identities / 2 charges。

`chunk_index` 是 enumerate 序号（L544），Chunk3→key=`...:3:ingest`，Chunk4→key=`...:4:ingest`。不同 chunk_index → 不同 business_event_id → 不同 key → 2 条独立 ComputeTransaction。

---

## Q6. same chunk in different run 如何验证？（RI-4）

**RI-4 Same Chunk New Run**：Run1 / Doc10 / Chunk3 + Run2 / Doc10 / Chunk3 → 2 legitimate charges（run_id 不同）。

每次 `train_document`/`train_scope` 调用 `_create_training_run` 生成新 run_id（L522/L656）。同 content 重新 ingest = 新 run = 新 run_id → 不同 key → 2 条独立合法消费。**非 defect**（重新训练是合法新消费，与 Daily Report regenerate 同语义）。

---

## Q7. identical-content different chunk occurrence 如何验证？（RI-3，本轮新发现）

**RI-3 Identical Content Different Occurrence**：Chunk3 text == Chunk11 text → 2 keys / 2 txn（chunk_index 不同）。

**场景**：同一文档内 chunk_text 切分可能产生内容完全相同的两个 chunk（如重复段落），但它们是不同的 chunk occurrence（不同 chunk_index）。即使 content_hash 相同，`document_id + chunk_index` 不同 → 不同 business_event_id → 不同 key。

**ON CONFLICT (document_id, content_hash) DO NOTHING（L560）的影响**：相同 content_hash 的第二个 chunk INSERT 被跳过（DO NOTHING），但 **embedding 已在 L546 计算**（INSERT 前）。计费发生在 embedding 调用时（L546），不在 INSERT 时——故 content_hash 重复导致 INSERT 跳过，但 embedding 计费已发生且 key 不同（chunk_index 不同）→ 2 条 txn。

**这是正确的**：两个 occurrence 各自调用了一次 embedding API（真实供应商成本），各自计费。chunk_hash 去重只影响数据行（knowledge_chunks 表），不影响计费幂等（P3：chunk_hash 不进 billing key）。

---

## Q8. Ingest normal charge-producing None count 如何归零？（RI-5）

**RI-5 Ingest None=0**：RAG Ingest 正式链（train_document L546 / train_scope L692）`idempotency_key ≠ None` → Ingest None=0。Query 仍 None（独立 #10a）。

实施后：Ingest 两条路径都传 `run_id`/`document_id`/`chunk_index` → 构造 key → None=0。Query 路径（L441）不传 → None 仍存在但属 #10a 范围，不计入 #10b 的 None=0 口径。

**None count 口径声明**：仅 "#10b RAG Ingest None=0"，不宣称 "#10a RAG Query None=0"。

---

## 实施前置条件（冻结为硬约束）

- **P1**：Within one TrainingRun, same logical document → same document_id；distinct logical documents → distinct document_id。未来 document_id 生成方式变化须重评 identity 合同。
- **P2**：同一 TrainingRun 技术重放不得中途改变 chunking configuration（chunk_size/overlap/chunker）。Run 内 chunking 配置稳定是业务不变量（不塞 key，作为不变量约束）。
- **P3**：chunk_hash 不进入 billing uniqueness identity（保持 semantic/debug evidence）。
- **P4**：`_embed_with_usage` 共享函数，只有 Ingest 构造 identity；Query 路径仍 None（独立 #10a Charge Path，不合并）。None count 只写 "RAG Ingest None=0"。

---

## 不变式（3 条）

1. **same run + same chunk occurrence retry → same key（REPLAY）**：run_id + document_id + chunk_index 均不变 → 同一 idempotency_key → M07 IDEMPOTENT_REPLAY。
2. **same run + different chunk（even if identical content）→ different chunk_index → different key**：chunk_index 维度区分不同 occurrence，即使 content_hash 相同（RI-3）。
3. **new run + same content → different run_id → different key（合法新消费，非 defect）**：重新训练产生新 run = 新 run_id = 新合法消费（RI-4）。

---

## TrainingRun durability：选项 A 冻结（5E-2R1 APPROVED）

**当前事实**：`_create_training_run`（L1456 INSERT RETURNING id）**未单独 commit**。run_id 在 train_document/train_scope 事务内生成，但 `conn.commit()` 在 L630（整个 run 完成时）。即 run_id 在 embedding 调用（L546）时**事务内可读但未持久化提交**。

**与 Training Ask Execution（5D-2）的区别**：5D-2 的 execution 在 RAG search 前**单独 commit**（identity 持久化先于 charge 点）。5E-2 的 run_id 当前**未单独 commit**——若进程在 embedding 后、L630 commit 前崩溃，rag_training_runs 行回滚，run_id"消失"。

### 选项 A 冻结（5E-2R1 APPROVED）

```
_create_training_run
  → INSERT status='running' RETURNING id
  → 显式 COMMIT              ← 新的 durable boundary
  → chunk iteration / embedding / report_usage / chunk persistence
  → completed / failed finalize（后续事务）
```

TrainingRun.id 在首次 `_embed_with_usage` / `report_usage` 前 **durable committed**，满足 P1 硬约束：**Business Event Identity 必须在收费副作用前稳定且持久存在**。

代价：commit 打断单事务，run 行的 `status='completed'` / `status='failed'` UPDATE 需在后续事务执行（见 RI-6A/RI-6B finalize 要求）。

### 选项 B（保持单事务）NOT APPROVED

run_id 未持久化时崩溃会 rollback 消失，无法承担 P1 稳定父级 Business Event Identity。已否决。

---

## 验收 Gate（7 个，实施时验证）

| Gate | 场景 | 预期 |
|---|---|---|
| RI-0 | **Parent Identity Durable Before Charge**：TrainingRun 在首次 `_embed_with_usage`/`report_usage` 前 durable committed | 独立事务可见可恢复（非仅事务内可读） |
| RI-1 | Same Chunk Replay：Run1/Doc10/Chunk3 report twice | 1 txn / replay / 1 debit |
| RI-2 | Different Chunks：Run1/Doc10/Chunk3 + Chunk4 | 2 identities / 2 charges |
| RI-3 | Identical Content Different Occurrence：Chunk3 text==Chunk11 text | 2 keys / 2 txn（chunk_index 不同） |
| RI-4 | Same Chunk New Run：Run1/Doc10/Chunk3 + Run2/Doc10/Chunk3 | 2 legitimate charges（run_id 不同） |
| RI-5 | Ingest None=0 / Query 仍 None | Ingest None=0 / Query None≠0（独立 #10a） |
| RI-6A | **External/Normal Workflow Failure**：Run R1 durable → embedding/Milvus/normal workflow error → finalize R1=failed | R1 仍存在 / status=failed / 已 commit 的 M07 交易不受影响 |
| RI-6B | **DB Transaction Unusable（★PG 失败边界）**：后续工作事务进入 aborted state | rollback 失败工作事务 → fresh transaction → UPDATE durable Run→failed → commit（★不得依赖现有 except 的 UPDATE+commit 原样足够；PG aborted 后须 rollback→fresh tx→finalize）。账务红线：已 committed ComputeTransaction 绝不因 Run failed 被删除/否认（与 TR-5B 同原则） |

---

## PostgreSQL SQL 失败 finalize 要求（5E-2R1 REQUIRED-1）

当后续工作事务因 SQL 执行错误进入 **aborted state** 时，当前 except 块的 `UPDATE` + `commit` 可能失败（事务已不可用）。

**实施时必须保证**（Stage 5E-3 实施时必须检查的事务处理细节）：
```
rollback 失败工作事务
  → fresh transaction
  → UPDATE durable TrainingRun → status='failed'
  → commit
```
而非依赖"现有 except UPDATE+commit 原样一定成功"。

此要求与选项 A 的"durable boundary"配套：Run 行已 durable committed（独立事务可见），故失败 finalize 可用 fresh transaction 安全 UPDATE，不依赖已 aborted 的工作事务。

---

## Partial Identity 规则（5E-2R1 D5）

`_embed_with_usage` 三参数（`run_id`/`document_id`/`chunk_index`）identity 规则：

| 三参数状态 | 行为 | key |
|---|---|---|
| ALL PRESENT | 构造 ingest idempotency key | `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest` |
| ALL ABSENT | non-Ingest / Query legacy path | None |
| PARTIAL | **identity contract violation** → 显式 warning 诊断 + 不构造畸形 key | None（但带 warning，非静默） |

- Ingest 正式路径 partial identity count = 0（验收条件）
- 与 M01 partial identity 治理一致：**不静默退 None**（partial 时记 warning 可观测，不生成部分维度的错误 key）

---

## Reliability Gap 登记（不合并，OUT_OF_P1）

### RAG_INGEST_RUN_RECOVERY_GAP

- **TYPE**: RELIABILITY
- **SCENARIO**: durable TrainingRun created → process crash before finalize → running 孤儿行
- **问题**: 当前无 stale reconcile/resume 机制，crash 后留下 `status='running'` 孤儿 Run
- **P1**: OUT_OF_SCOPE
- ★ **准确口径**：持久孤儿 Run **不等于**未来 full-request retry 会复用该 Run——crash 后重新调用 `_create_training_run` 会建新 Run #N+1，不同 key，M07 不去重。
- ★ **same Run replay → P1 保护**；**full request retry after crash → 当前未保证复用 same Run → P1 不解决**。

### RAG_INGEST_REQUEST_RECOVERY_GAP

- **TYPE**: RELIABILITY
- **SCENARIO**: `train_document`/`train_scope` HTTP 请求失败或响应丢失 → 重新提交创建新 TrainingRun
- **问题**: 无法识别新 HTTP 调用其实是旧 request replay（无 durable client request identity 证明 Run#N+1==Run#N）
- **P1**: OUT_OF_SCOPE
- 与 `DAILY_REPORT_REQUEST_RECOVERY_GAP` / `TRAINING_REQUEST_RECOVERY_GAP` 同口径
- ★ **RUN_RECOVERY ≠ REQUEST_RECOVERY**（已有 Run 怎么恢复 vs 新 HTTP 调用怎么知道属于旧 Run），不合并。

---

## 边界注明

### RAG Query Embedding（#10a）不合并
- `_embed_with_usage` 共享于 Ingest（L546/L692）与 Query（L441），但 identity 各自构造。
- Ingest：三参数非空 → `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`
- Query：三参数 None → key=None（独立 #10a Charge Path，未迁移）
- 不宣称 Query Embedding 已迁移。

### billing truth 归 M07
- 本设计只构造 idempotency_key，不改 M07 core / `record_usage`。
- committed ComputeTransaction 是唯一 billing truth；`_embed_with_usage` 不持有 billing 状态。

### 不宣称跨进程请求级幂等
- Ingest 是 9100 进程内（`get_rag_engine()`）调用 embedding API → `ComputeUsageClient` HTTP→9000。
- 不宣称解决 full 9000←9100 响应丢失级恢复（若有，登记独立 Reliability Gap，OUT_OF_P1）。

---

## #10b 状态演进记录（D6）

```
5E-R1:  IDENTITY_VERIFIED_READY_FOR_TECHNICAL_DESIGN
5E-2 finding:  PARENT_DURABILITY_DESIGN_REQUIRED（发现 run_id 未 durable commit）
5E-2R1: OPTION A APPROVED → PARENT_DURABILITY_SOLUTION_APPROVED / READY_FOR_IMPLEMENTATION_REVIEW
```

**当前正式状态**：`IDENTITY_MODEL_VERIFIED` / `PARENT_DURABILITY_SOLUTION_APPROVED` / `READY_FOR_IMPLEMENTATION_REVIEW`

---

## 待审批决策点

1. identity key 形态 → **冻结 APPROVED**：`rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`
2. `_embed_with_usage` 签名扩展方式（三可选参数 vs 新增 helper）→ **倾向三可选参数**（YAGNI，共享函数最小改动）
3. ~~run_id commit 时机（选项 A 提前 commit vs 选项 B 保持单事务）~~ → **选项 A 已冻结 APPROVED**（5E-2R1）：`_create_training_run` 后首次 embedding 前 durable commit（RI-0）
4. 审查通过后授权实施（`_embed_with_usage` 签名扩展 + train_document/train_scope 透传三参数 + `_create_training_run` 后 durable commit + PG 失败 finalize + 7 Gate）
