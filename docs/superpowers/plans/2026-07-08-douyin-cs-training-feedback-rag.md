# AI 抖音客服训练反馈闭环改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实现本计划。步骤使用 checkbox（`- [ ]`）语法跟踪。

**Goal:** 把“AI 抖音客服自动回复训练”的反馈入库从“标准回答样本”改成“本次 AI 回复评价样本”，让 RAG 后续召回时能按 `有用 > 一般 > 不准` 学习和避坑。

**Architecture:** 保持现有三段代理链路：`car-porject-main 8788 -> auto_wechat 9000 -> 9100 -> Milvus/SQLite`。9100 仍是训练反馈 metadata 真源，Milvus 只保存训练后的 chunk 副本；不让前端直连 9000、9100 或 Milvus，不改端口，不触发真实私信发送。

**Tech Stack:** Python、FastAPI、SQLite/PostgreSQL 迁移兼容思路、Milvus 向量库、car-porject-main 原生前端 `frontend/assets/app.js`、pytest。

---

## 文件结构

本次按最小改动推进，不新增业务表。

- 修改 `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\knowledge_training_service.py`
  - 负责 9100 训练问答、反馈保存、反馈文档生成、自动训练入库。
  - 把反馈文档内容改成“客户问题 + AI 原始回复 + 人工反馈 + 人工评价 + 可选人工修正 + 来源”。
  - 所有 `useful/normal/wrong` 反馈都允许进入 RAG，其中 `wrong` 作为避坑样本。

- 修改 `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\rag\repository.py`
  - 负责 RAG 搜索排序。
  - 在候选结果内识别反馈样本，并在相关性相近时按 `有用 > 一般 > 不准` 重排。
  - 不修改 Milvus schema，优先通过 chunk 文本标记实现兼容。

- 修改 `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\reply_decision_service.py`
  - 负责真实抖音客服回复建议的提示词。
  - 告诉 LLM 如何使用反馈样本：有用可借鉴，一般需改写，不准只能避坑。

- 修改 `E:\work\project\car-porject-main\frontend\assets\app.js`
  - 负责“AI 抖音客服自动回复训练”页面反馈 UI。
  - 把当前“修正后的标准回答”单输入改成“人工评价 + 可选修正回复”。
  - 提交 `comment`，保留 `corrected_answer` 兼容能力。

- 视情况修改 `E:\work\project\car-porject-main\backend\app.py`
  - 当前已读取并透传 `comment`，重点检查是否需要增强返回 metadata。
  - 不改鉴权、不改端口、不透传前端 tenant/merchant 给 9000。

- 新增 `E:\work\project\auto_wechat\scripts\repair_douyin_cs_training_feedback_documents.py`
  - 默认 dry-run。
  - 用于修复历史错误入库的反馈文档，例如 `【标准回答】一般`。
  - 通过 `metadata_json.training_id` 找回 `knowledge_training_sessions.answer` 和 `knowledge_training_feedbacks.comment` 后重建文档正文。

- 修改测试：
  - `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_training_feedback_auto_ingest.py`
  - `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_rag.py`
  - `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_app.py`
  - `E:\work\project\car-porject-main\tests\test_douyin_cs_autoreply_9000_proxy.py`

---

## 数据模型判断

现有表已经够用，不建议新增表或迁移字段。

9100 真源：

```text
knowledge_training_sessions
  training_id
  tenant_id
  merchant_id
  question
  answer

knowledge_training_feedbacks
  training_id
  rating
  comment
  corrected_answer
  ingestion_status
  ingested_document_id
  ingestion_training_run_id
  answer_hash

knowledge_documents
  content
  source_type
  metadata_json
```

本次只调整语义：

- `comment` 作为“人工评价”。
- `corrected_answer` 作为“人工修正回复，可选”。
- `answer_hash` 继续复用，但 hash 内容从“被选答案”改为“完整反馈文档正文”，避免相同 AI 回复但不同评价被错误去重。
- `knowledge_documents.metadata_json.rating` 继续记录 `useful/normal/wrong`，但 RAG 不依赖 metadata；向量库 chunk 文本里也写入中文反馈标签，保证 Milvus 不改 schema 也能召回语义。

---

### Task 1: 9100 反馈文档格式改造

**Files:**
- Modify: `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\knowledge_training_service.py`
- Test: `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_training_feedback_auto_ingest.py`

- [ ] **Step 1: 写失败测试，确认 useful 入库内容包含完整评价样本**

在 `tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py` 增加测试：

```python
def test_useful_feedback_ingests_ai_reply_feedback_sample(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch, answer="您好，可以分期，建议先确认预算和首付比例。")
    ask_data = _ask(
        client,
        question="这台车可以分期吗？首付多少，流程是什么？",
        answer="您好，可以分期，建议先确认预算和首付比例。",
    )

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": "useful",
            "comment": "回答方向可用，但需要更自然一点。",
        },
    )

    assert response.status_code == 200
    assert response.json()["rag_ingestion"]["status"] == "completed"

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        document = conn.execute(
            "SELECT content, source_type FROM knowledge_documents WHERE id=?",
            (int(response.json()["rag_ingestion"]["document_id"]),),
        ).fetchone()

    assert document["source_type"] == "douyin_cs_training_feedback"
    assert "【客户问题】" in document["content"]
    assert "这台车可以分期吗？首付多少，流程是什么？" in document["content"]
    assert "【AI原始回复】" in document["content"]
    assert "您好，可以分期，建议先确认预算和首付比例。" in document["content"]
    assert "【人工反馈】" in document["content"]
    assert "有用" in document["content"]
    assert "【人工评价】" in document["content"]
    assert "回答方向可用，但需要更自然一点。" in document["content"]
    assert "【来源】" in document["content"]
    assert "AI 抖音客服自动回复训练反馈" in document["content"]
    assert "【标准回答】" not in document["content"]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py::test_useful_feedback_ingests_ai_reply_feedback_sample -q
```

Expected:

```text
FAILED，因为当前文档仍使用【标准回答】格式，且没有【AI原始回复】/【人工反馈】/【人工评价】。
```

- [ ] **Step 3: 实现反馈标签和文档内容函数**

在 `knowledge_training_service.py` 顶部常量附近增加：

```python
FEEDBACK_RATING_LABELS = {
    "useful": "有用",
    "normal": "一般",
    "wrong": "不准",
}

FEEDBACK_RATING_USAGE = {
    "useful": "优先学习：这类回复方向可复用。",
    "normal": "谨慎参考：保留有效信息，但表达方式需要优化。",
    "wrong": "避坑提醒：不要照抄这类回复，应根据人工评价规避问题。",
}
```

把 `_feedback_document_content` 改成：

```python
def _feedback_document_content(
    *,
    question: str,
    original_answer: str,
    rating: str,
    comment: str | None,
    corrected_answer: str | None,
) -> str:
    rating_label = FEEDBACK_RATING_LABELS.get(rating, rating or "未知")
    usage = FEEDBACK_RATING_USAGE.get(rating, "")
    comment_text = _clean_text(comment, limit=2000) or "未填写"
    corrected_text = _clean_text(corrected_answer, limit=3000)
    parts = [
        "【客户问题】",
        question,
        "",
        "【AI原始回复】",
        original_answer,
        "",
        "【人工反馈】",
        rating_label,
        "",
        "【反馈使用规则】",
        usage,
        "",
        "【人工评价】",
        comment_text,
    ]
    if corrected_text:
        parts.extend(["", "【人工修正回复】", corrected_text])
    parts.extend(["", "【来源】", "AI 抖音客服自动回复训练反馈"])
    return "\n".join(parts)
```

- [ ] **Step 4: 调整 submit_feedback 生成完整反馈文档**

在 `submit_feedback()` 中保留写入 `knowledge_training_feedbacks`，但把原来的 `selected_answer/answer_source` 选择逻辑改成面向完整文档：

```python
original_answer = _clean_text(session["answer"], limit=3000)
feedback_document_content = _feedback_document_content(
    question=session["question"],
    original_answer=original_answer,
    rating=payload.rating,
    comment=payload.comment,
    corrected_answer=corrected_answer,
)
answer_hash = _answer_hash(feedback_document_content)
answer_source = "feedback_sample"
```

保留 `auto_ingest=false` 的跳过逻辑；删除 `normal/wrong` 因没有修正回答而跳过的逻辑。

- [ ] **Step 5: 调整 _ingest_feedback_document 参数**

把 `_ingest_feedback_document()` 参数中的 `selected_answer` 替换为 `content`，调用 `repository.create_document()` 时使用完整内容：

```python
content=content,
source_type="douyin_cs_training_feedback",
metadata={
    "source": "douyin_cs_training_feedback",
    "training_id": training_id,
    "feedback_id": str(feedback_id),
    "rating": rating,
    "answer_source": answer_source,
    "auto_ingest": True,
}
```

- [ ] **Step 6: 运行测试确认通过**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py::test_useful_feedback_ingests_ai_reply_feedback_sample -q
```

Expected:

```text
1 passed
```

---

### Task 2: normal/wrong 也作为反馈样本入库

**Files:**
- Modify: `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\knowledge_training_service.py`
- Test: `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_training_feedback_auto_ingest.py`

- [ ] **Step 1: 改写现有跳过测试**

把原 `test_normal_or_wrong_without_corrected_answer_only_saves_feedback` 替换为：

```python
@pytest.mark.parametrize(
    ("rating", "label", "usage_text"),
    [
        ("normal", "一般", "谨慎参考"),
        ("wrong", "不准", "避坑提醒"),
    ],
)
def test_normal_or_wrong_feedback_auto_ingests_as_feedback_sample(
    tmp_path,
    monkeypatch,
    rating,
    label,
    usage_text,
):
    client = _client(tmp_path, monkeypatch)
    _patch_llm(monkeypatch, answer="您好~我这边帮您详细核实下哦。")
    ask_data = _ask(
        client,
        question="这台车可以分期吗？首付多少？",
        answer="您好~我这边帮您详细核实下哦。",
    )

    response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": rating,
            "comment": "AI回复太长太礼貌，机器人感太强。",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["rag_ingestion"]["status"] == "completed"

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        document = conn.execute(
            "SELECT content FROM knowledge_documents WHERE id=?",
            (int(data["rag_ingestion"]["document_id"]),),
        ).fetchone()

    assert f"【人工反馈】\n{label}" in document["content"]
    assert usage_text in document["content"]
    assert "AI回复太长太礼貌，机器人感太强。" in document["content"]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py::test_normal_or_wrong_feedback_auto_ingests_as_feedback_sample -q
```

Expected:

```text
FAILED，因为当前 normal/wrong 无修正回答时返回 rag_ingestion.status=skipped。
```

- [ ] **Step 3: 保留 auto_ingest=false 跳过**

确认 `auto_ingest=false` 分支仍返回：

```python
{
    "enabled": True,
    "triggered": False,
    "status": "skipped",
    "reason": "auto_ingest_disabled",
}
```

不要再使用 `rating_not_ingestable` 作为 normal/wrong 默认跳过原因。

- [ ] **Step 4: 运行相关测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py -q
```

Expected:

```text
全部通过；原 normal/wrong 跳过测试已替换为入库测试。
```

---

### Task 3: RAG 召回结果按反馈优先级重排

**Files:**
- Modify: `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\rag\repository.py`
- Test: `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_rag.py`

- [ ] **Step 1: 写失败测试，确认同类反馈按 有用 > 一般 > 不准 排序**

在 `tests/test_xg_douyin_ai_cs_rag.py` 增加：

```python
def test_feedback_chunks_are_reranked_by_rating_priority(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.rag import repository
    from apps.xg_douyin_ai_cs.rag.database import connect, init_db
    from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest

    init_db()
    with connect() as conn:
        for title, rating in [
            ("不准样本", "不准"),
            ("一般样本", "一般"),
            ("有用样本", "有用"),
        ]:
            cur = conn.execute(
                """
                INSERT INTO knowledge_documents(
                  tenant_id, merchant_id, douyin_account_id, title, content,
                  source_type, category_key, is_active
                ) VALUES('xiaogao_system','xiaogao_base',0,?,?, 'douyin_cs_training_feedback','base',1)
                """,
                (title, f"【客户问题】分期首付\n【AI原始回复】示例\n【人工反馈】\n{rating}\n【人工评价】示例"),
            )
            conn.execute(
                """
                INSERT INTO knowledge_chunks(
                  document_id, tenant_id, merchant_id, douyin_account_id,
                  chunk_text, chunk_index, embedding_json, embedding_model,
                  category_key, content_hash, is_active
                ) VALUES(?,?,?,?,?,?,?,?,?,?,1)
                """,
                (
                    int(cur.lastrowid),
                    "xiaogao_system",
                    "xiaogao_base",
                    0,
                    f"分期 首付 【人工反馈】\n{rating}",
                    1,
                    "",
                    "test",
                    "base",
                    f"hash-{rating}",
                ),
            )
        conn.commit()

    results = repository.search(
        RagSearchRequest(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            douyin_account_id=0,
            query="分期首付",
            top_k=3,
            category_keys=["base"],
        )
    )

    assert [item.title for item in results] == ["有用样本", "一般样本", "不准样本"]
```

- [ ] **Step 2: 运行失败测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_rag.py::test_feedback_chunks_are_reranked_by_rating_priority -q
```

Expected:

```text
FAILED，当前只按分数排序。
```

- [ ] **Step 3: 增加反馈优先级解析函数**

在 `repository.py` 中增加：

```python
FEEDBACK_RATING_PRIORITY = {
    "有用": 3,
    "一般": 2,
    "不准": 1,
}


def _feedback_priority_from_text(text: str) -> int:
    normalized = str(text or "")
    for label, priority in FEEDBACK_RATING_PRIORITY.items():
        if f"【人工反馈】\n{label}" in normalized or f"【人工反馈】 {label}" in normalized:
            return priority
    return 0
```

- [ ] **Step 4: SQLite 搜索排序加入反馈优先级**

把 `vector_scored.sort(key=lambda item: item[0], reverse=True)` 调整为：

```python
vector_scored.sort(
    key=lambda item: (
        round(float(item[0]), 2),
        _feedback_priority_from_text(str(item[1]["chunk_text"] or "")),
        float(item[0]),
    ),
    reverse=True,
)
```

把 lexical 的 `scored.sort(key=lambda item: item[0], reverse=True)` 同样调整。

- [ ] **Step 5: Milvus 搜索候选扩大后重排**

在 `_search_milvus_or_fallback()` 中，把传给 Milvus 的 top_k 扩大为候选集，再重排截断：

```python
candidate_top_k = min(20, max(payload.top_k, payload.top_k * 3))
candidate_payload = payload.model_copy(update={"top_k": candidate_top_k})
result = get_vector_store().search(candidate_payload, query_embedding=query_embedding)
return _rerank_search_items(result, payload.top_k)
```

新增：

```python
def _rerank_search_items(items: list[RagSearchItem], top_k: int) -> list[RagSearchItem]:
    ranked = sorted(
        items,
        key=lambda item: (
            round(float(item.score), 2),
            _feedback_priority_from_text(item.chunk_text),
            float(item.score),
        ),
        reverse=True,
    )
    return ranked[:top_k]
```

- [ ] **Step 6: 运行 RAG 测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_rag.py::test_feedback_chunks_are_reranked_by_rating_priority -q
```

Expected:

```text
1 passed
```

---

### Task 4: 提示词明确反馈样本使用规则

**Files:**
- Modify: `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\knowledge_training_service.py`
- Modify: `E:\work\project\auto_wechat\apps\xg_douyin_ai_cs\services\reply_decision_service.py`
- Test: `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_app.py`

- [ ] **Step 1: 给训练页 ask 的 prompt 增加规则**

在 `_build_user_prompt()` 的 `parts` 中，加入：

```python
"如果小高知识库命中 AI 抖音客服自动回复训练反馈：有用样本优先借鉴；一般样本只吸收有效信息并优化表达；不准样本只能作为避坑提醒，禁止照抄其中的 AI 原始回复。",
```

- [ ] **Step 2: 给真实回复建议 prompt 增加规则**

在 `reply_decision_service.py` 的 `build_llm_messages()` system prompt 中加入：

```python
"rag_results 可能包含 AI 抖音客服自动回复训练反馈；有用反馈优先借鉴，一般反馈谨慎改写，不准反馈只用于规避同类错误，禁止照抄不准样本里的 AI 原始回复。",
```

- [ ] **Step 3: 写提示词测试**

在 `tests/test_xg_douyin_ai_cs_app.py` 或现有 prompt 相关测试中增加：

```python
def test_knowledge_training_prompt_mentions_feedback_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    captured = {}

    def fake_chat(self, messages):
        captured["messages"] = messages
        return {"reply_text": "好的回复", "model": "mock-chat", "elapsed_ms": 1, "usage": None}

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.embed",
        lambda self, text: {"embedding": [1.0, 0.0], "model": "mock"},
    )

    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "question": "分期首付怎么说",
            "use_xiaogao_knowledge_base": True,
        },
    )

    assert response.status_code == 200
    prompt_text = "\n".join(message["content"] for message in captured["messages"])
    assert "有用样本优先借鉴" in prompt_text
    assert "不准样本只能作为避坑提醒" in prompt_text
```

- [ ] **Step 4: 运行提示词测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_app.py::test_knowledge_training_prompt_mentions_feedback_priority -q
```

Expected:

```text
1 passed
```

---

### Task 5: car-porject-main 前端反馈 UI 改造

**Files:**
- Modify: `E:\work\project\car-porject-main\frontend\assets\app.js`

- [ ] **Step 1: 修改反馈面板 markup**

在 `douyinTrainingFeedbackMarkup()` 中，把单个 `data-douyin-training-corrected-answer` textarea 改为两个输入：

```javascript
<textarea class="director-feedback-note" data-douyin-training-feedback-comment placeholder="填写人工评价，例如：AI回复太长太礼貌，机器人感太强" ${disabledAttr}>${escapeHtml(feedback.comment || "")}</textarea>
<textarea class="director-feedback-note" data-douyin-training-corrected-answer placeholder="可选：填写更合适的回复示例" ${disabledAttr}>${escapeHtml(feedback.corrected_answer || "")}</textarea>
```

- [ ] **Step 2: 提交 payload 带上 comment**

在 `bindDouyinTrainingFeedbackEvents()` 中读取：

```javascript
const comment = panel.querySelector("[data-douyin-training-feedback-comment]")?.value.trim() || "";
const correctedAnswer = panel.querySelector("[data-douyin-training-corrected-answer]")?.value.trim() || "";
```

提交 payload 改为：

```javascript
body: JSON.stringify({
  merchant_id: state.selectedMerchantId,
  message_id: messageId,
  rating,
  comment,
  corrected_answer: correctedAnswer,
}),
```

- [ ] **Step 3: 反馈提交后禁用两个输入**

把禁用 selector 改为：

```javascript
panel.querySelectorAll("[data-douyin-training-feedback-rating], [data-douyin-training-feedback-comment], [data-douyin-training-corrected-answer], [data-douyin-training-feedback-submit]")
  .forEach((item) => { item.disabled = true; });
```

- [ ] **Step 4: 轻量静态检查**

Run:

```bash
rg -n "data-douyin-training-feedback-comment|comment,|corrected_answer: correctedAnswer" frontend/assets/app.js
```

Expected:

```text
能看到新增 comment 输入、payload comment 和保留 corrected_answer。
```

---

### Task 6: 8788 后端代理测试补齐

**Files:**
- Modify: `E:\work\project\car-porject-main\tests\test_douyin_cs_autoreply_9000_proxy.py`
- Check: `E:\work\project\car-porject-main\backend\app.py`

- [ ] **Step 1: 增加 feedback comment 透传断言**

在现有 `test_douyin_training_feedback_forwards_corrected_answer_and_rag_ingestion` 中补充：

```python
self.assertEqual(captured["body"]["comment"], "AI回复太长太礼貌，机器人感太强")
```

并把请求体 comment 设置为：

```python
"comment": "AI回复太长太礼貌，机器人感太强",
```

- [ ] **Step 2: 运行代理测试**

Run:

```bash
python -m pytest tests/test_douyin_cs_autoreply_9000_proxy.py -q
```

Expected:

```text
全部通过。若失败，优先修正测试数据和现有透传逻辑，不改 9000 鉴权。
```

---

### Task 7: 历史错误反馈文档 dry-run 修复脚本

**Files:**
- Create: `E:\work\project\auto_wechat\scripts\repair_douyin_cs_training_feedback_documents.py`
- Test: `E:\work\project\auto_wechat\tests\test_xg_douyin_ai_cs_training_feedback_auto_ingest.py`

- [ ] **Step 1: 写脚本核心逻辑**

脚本默认只输出待修复项，不写库：

```python
from __future__ import annotations

import argparse
import json

from apps.xg_douyin_ai_cs.rag.database import connect
from apps.xg_douyin_ai_cs.rag import repository
from apps.xg_douyin_ai_cs.services.knowledge_training_service import _feedback_document_content


BAD_LABELS = {"有用", "一般", "不准"}


def _metadata(row) -> dict:
    try:
        return json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _is_bad_feedback_content(content: str) -> bool:
    text = str(content or "").strip()
    return "【标准回答】" in text and any(f"【标准回答】\n{label}" in text for label in BAD_LABELS)


def collect_repairs() -> list[dict]:
    repairs = []
    with connect() as conn:
        docs = conn.execute(
            """
            SELECT id, tenant_id, merchant_id, content, metadata_json
            FROM knowledge_documents
            WHERE source_type='douyin_cs_training_feedback' AND is_active=1
            """
        ).fetchall()
        for doc in docs:
            if not _is_bad_feedback_content(doc["content"]):
                continue
            metadata = _metadata(doc)
            training_id = str(metadata.get("training_id") or "").strip()
            if not training_id:
                repairs.append({"document_id": doc["id"], "status": "skipped", "reason": "missing_training_id"})
                continue
            session = conn.execute(
                "SELECT question, answer FROM knowledge_training_sessions WHERE training_id=?",
                (training_id,),
            ).fetchone()
            feedback = conn.execute(
                """
                SELECT rating, comment, corrected_answer
                FROM knowledge_training_feedbacks
                WHERE training_id=?
                ORDER BY id DESC LIMIT 1
                """,
                (training_id,),
            ).fetchone()
            if not session or not feedback:
                repairs.append({"document_id": doc["id"], "status": "skipped", "reason": "missing_session_or_feedback"})
                continue
            new_content = _feedback_document_content(
                question=session["question"],
                original_answer=session["answer"],
                rating=feedback["rating"],
                comment=feedback["comment"],
                corrected_answer=feedback["corrected_answer"],
            )
            repairs.append(
                {
                    "document_id": int(doc["id"]),
                    "tenant_id": doc["tenant_id"],
                    "merchant_id": doc["merchant_id"],
                    "status": "ready",
                    "content": new_content,
                }
            )
    return repairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际更新文档并重训")
    args = parser.parse_args()
    repairs = collect_repairs()
    print(json.dumps([{k: v for k, v in item.items() if k != "content"} for item in repairs], ensure_ascii=False, indent=2))
    if not args.apply:
        return
    with connect() as conn:
        for item in repairs:
            if item["status"] != "ready":
                continue
            conn.execute(
                "UPDATE knowledge_documents SET content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item["content"], item["document_id"]),
            )
        conn.commit()
    for item in repairs:
        if item["status"] == "ready":
            repository.train_document(
                tenant_id=item["tenant_id"],
                merchant_id=item["merchant_id"],
                document_id=item["document_id"],
            )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: dry-run 验证命令**

Run:

```bash
python scripts/repair_douyin_cs_training_feedback_documents.py
```

Expected:

```text
只输出 JSON 报告，不修改数据库、不重训、不写 Milvus。
```

- [ ] **Step 3: apply 命令只在人工确认后执行**

Run:

```bash
python scripts/repair_douyin_cs_training_feedback_documents.py --apply
```

Expected:

```text
更新历史错误文档 content，并调用现有 train_document 重新 upsert 向量。
```

---

### Task 8: 全链路回归测试

**Files:**
- No new files.

- [ ] **Step 1: auto_wechat 单元测试**

Run:

```bash
python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py tests/test_xg_douyin_ai_cs_rag.py tests/test_xg_douyin_ai_cs_app.py -q
```

Expected:

```text
全部通过。
```

- [ ] **Step 2: car-porject-main 代理测试**

Run:

```bash
cd /d E:\work\project\car-porject-main
python -m pytest tests/test_douyin_cs_autoreply_9000_proxy.py -q
```

Expected:

```text
全部通过。
```

- [ ] **Step 3: 只读确认关键文本**

Run:

```bash
cd /d E:\work\project\auto_wechat
rg -n "【AI原始回复】|【人工反馈】|【人工评价】|有用样本优先借鉴|不准样本只能作为避坑提醒" apps tests
```

Expected:

```text
能定位到文档生成、提示词和测试断言。
```

- [ ] **Step 4: 手工 smoke 流程，仅限测试环境**

测试环境发起一次训练问答和反馈：

```text
car-porject-main 前端
-> AI 抖音客服自动回复训练
-> 输入“这台车可以分期吗？首付多少，流程是什么？”
-> 等 AI 生成回复
-> 选择“一般”
-> 人工评价填写“AI回复太长太过礼貌，机器人感太强”
-> 提交反馈
```

验收：

```text
反馈显示已加入小高知识库训练。
Milvus/检索预览 chunk_text 包含：
【客户问题】
【AI原始回复】
【人工反馈】
【人工评价】
【来源】
不再出现“【标准回答】一般”。
```

---

## 风险与边界

- 不改业务端口。
- 不改真实发送 gate。
- 不让前端持有 internal token。
- 不让前端直连 9100 / Milvus。
- 不新增数据库表，降低迁移风险。
- Milvus schema 不变，避免线上 collection 结构迁移。
- 历史错误数据不自动删除，先 dry-run 报告，确认后再 `--apply` 重建。

---

## 自检

- 需求“评价完入向量库”：Task 1、Task 2 覆盖。
- 需求“入库内容包含客户问题、AI 原始回复、人工反馈、人工评价、来源”：Task 1 覆盖。
- 需求“RAG 召回注入提示词”：Task 4 覆盖。
- 需求“优先级 有用 > 一般 > 不准”：Task 3、Task 4 覆盖。
- 需求“不影响当前功能”：保留现有 ask/feedback 链路、保留 `corrected_answer`、保留 9000 可信代理。
- 需求“处理当前错误样例”：Task 7 覆盖 dry-run 和人工确认 apply。
