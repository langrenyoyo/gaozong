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

## 实施期需正视的事实：run_id commit 时机

**当前事实**：`_create_training_run`（L1456 INSERT RETURNING id）**未单独 commit**。run_id 在 train_document/train_scope 事务内生成，但 `conn.commit()` 在 L630（整个 run 完成时）。即 run_id 在 embedding 调用（L546）时**事务内可读但未持久化提交**。

**与 Training Ask Execution（5D-2）的区别**：5D-2 的 execution 在 RAG search 前**单独 commit**（identity 持久化先于 charge 点）。5E-2 的 run_id 当前**未单独 commit**——若进程在 embedding 后、L630 commit 前崩溃，rag_training_runs 行回滚，run_id"消失"。

**影响**：
- 正常路径（无崩溃）：run_id 在事务内可读，identity 构造正确，RI-1~RI-5 成立。
- 崩溃路径：run_id 未持久化 → 已提交的 ComputeTransaction（HTTP→9000 commit）与回滚的 rag_training_runs 不一致 → Execution=unbilled/孤儿。

**设计态度（不冻结实施方式）**：
- 选项 A：在 `_create_training_run` 后、embedding 前显式 `conn.commit()`（run_id 先持久化，类比 5D-2 C1）。代价：commit 打断事务，run 行的 status='completed' UPDATE 需在后续事务。
- 选项 B：保持当前单事务（run_id 未提前 commit），接受崩溃路径的 run_id 不一致，由 M07 IDEMPOTENCY_CONFLICT 兜底（若崩溃后重跑同 run 不可能，因 run_id 未持久化 → 新 run → 新 key → 不冲突也不 replay，只是孤儿 txn）。

**此为实施期决策，不冻结。** 本设计只要求：identity 维度（run_id/document_id/chunk_index）在 embedding 前可得（已满足）；run_id 持久化时机由实施窗口权衡。

---

## 验收 Gate（5 个，实施时验证）

| Gate | 场景 | 预期 |
|---|---|---|
| RI-1 | Same Chunk Replay：Run1/Doc10/Chunk3 report twice | 1 txn / replay / 1 debit |
| RI-2 | Different Chunks：Run1/Doc10/Chunk3 + Chunk4 | 2 identities / 2 charges |
| RI-3 | Identical Content Different Occurrence：Chunk3 text==Chunk11 text | 2 keys / 2 txn（chunk_index 不同） |
| RI-4 | Same Chunk New Run：Run1/Doc10/Chunk3 + Run2/Doc10/Chunk3 | 2 legitimate charges（run_id 不同） |
| RI-5 | Ingest None=0 / Query 仍 None | Ingest None=0 / Query None≠0（独立 #10a） |

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

## 待审批决策点

1. identity key 形态 → **冻结 APPROVED**：`rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`
2. `_embed_with_usage` 签名扩展方式（三可选参数 vs 新增 helper）→ **倾向三可选参数**（YAGNI，共享函数最小改动）
3. run_id commit 时机（选项 A 提前 commit vs 选项 B 保持单事务）→ **实施期决策，不冻结**
4. 审查通过后授权实施（`_embed_with_usage` 签名扩展 + train_document/train_scope 透传三参数 + 5 Gate）
