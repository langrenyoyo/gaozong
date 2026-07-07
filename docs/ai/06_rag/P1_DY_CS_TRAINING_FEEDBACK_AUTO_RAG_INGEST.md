# P1-DY-CS-TRAINING-FEEDBACK-AUTO-RAG-INGEST

## 1. 目标与边界

本轮实现 AI 抖音客服自动回复训练页的 feedback 自动入库闭环：用户点击“有用”，或提交修正回答后，9100 自动创建统一知识库文档并触发现有文档训练能力。

边界：

- 不触发抖音发送、私信发送、自动回复 gate。
- 不把 ask 链路改成 search-preview。
- 不让前端直连 9000、9100、Milvus。
- 不让前端持有 internal token。
- 不写入真实客户数据。
- 不连接真实 Milvus 做单元测试。

## 2. 修改前链路

修改前 feedback 只写入 `knowledge_training_feedbacks`：

```text
car-porject-main 前端
  -> 8788 /api/douyin-cs-training/feedback
  -> 9000 /knowledge-training/{training_id}/feedback
  -> 9100 knowledge_training_feedbacks
```

它不会创建 `knowledge_documents`，也不会触发 `train_document` 或 Milvus upsert。

## 3. 修改后链路

```text
car-porject-main 前端
  -> 8788 /api/douyin-cs-training/feedback
  -> 9000 /knowledge-training/{training_id}/feedback
  -> 9100 submit_feedback
  -> create_document
  -> train_document
  -> 现有 vector backend
```

当 `RAG_VECTOR_BACKEND=milvus` 时，训练链路复用已有 Milvus upsert 能力；默认 SQLite 行为不变。

## 4. 自动入库触发规则

- `rating=useful` 且无修正回答：入库 `question + 原 AI answer`。
- `corrected_answer` 非空且不同于原 AI answer：入库 `question + corrected_answer`。
- `rating=normal` 且无修正回答：只保存 feedback，`rag_ingestion.status=skipped`。
- `rating=wrong` 且无修正回答：只保存 feedback，`rag_ingestion.status=skipped`。
- `auto_ingest=false`：只保存 feedback，跳过入库。

## 5. 数据结构与幂等设计

9100 新增/补列：

- `knowledge_documents.metadata_json`
- `knowledge_training_feedbacks.corrected_answer`
- `knowledge_training_feedbacks.auto_ingest`
- `knowledge_training_feedbacks.ingestion_status`
- `knowledge_training_feedbacks.ingested_document_id`
- `knowledge_training_feedbacks.ingestion_training_run_id`
- `knowledge_training_feedbacks.ingestion_error`
- `knowledge_training_feedbacks.answer_hash`

8788 本地反馈表新增/补列：

- `corrected_answer`
- `rag_ingestion_status`
- `rag_document_id`
- `rag_training_run_id`

幂等策略：9100 使用 `tenant_id + merchant_id + training_id + answer_hash + ingestion_status=completed` 查重。重复点击同一条 useful 或相同修正回答时返回既有 `document_id` / `training_run_id`，不重复创建文档。

## 6. 9100 实现

入口：`apps/xg_douyin_ai_cs/services/knowledge_training_service.py`

- `submit_feedback()` 先保存 feedback，再按规则执行自动入库。
- 文档内容包含客户问题、标准回答和来源说明。
- 文档 metadata 记录 `source=douyin_cs_training_feedback`、`training_id`、`feedback_id`、`rating`、`answer_source`。
- 入库失败时 feedback 仍保存，返回 `rag_ingestion.status=failed`，不向前端暴露敏感配置。

## 7. 9000 实现

入口：`app/routers/knowledge_training.py`

- `POST /knowledge-training/{training_id}/feedback` 接收 `corrected_answer` 和 `auto_ingest`。
- 继续走 `require_unified_knowledge_training_access`。
- 继续固定注入 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`。
- 不信任外部 `tenant_id` / `merchant_id`。
- 不在 9000 直接写 RAG，只做可信代理。

## 8. 8788 / 前端实现

`car-porject-main/backend/app.py`：

- `/api/douyin-cs-training/feedback` 接收并 trim `corrected_answer`。
- `corrected_answer` 最长 3000 字。
- 修正回答为空或与原回答一致时不传给 9000。
- 不透传前端 tenant / merchant 上下文。
- 保存本地 feedback 与 `rag_ingestion` 摘要。

`car-porject-main/frontend/assets/app.js`：

- 反馈面板增加可选修正回答输入框。
- payload 增加 `corrected_answer`。
- 根据 `rag_ingestion.status` 展示 completed / skipped / failed 文案。
- 移除“反馈已提交到训练素材池”的误导性成功提示。

## 9. 测试结果

已执行：

```text
python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py tests/test_knowledge_training_api.py -q
23 passed

python -m pytest tests/test_knowledge_training_unified_api.py tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py -q
21 passed

python -m py_compile app/routers/knowledge_training.py app/services/xg_douyin_ai_cs_client.py apps/xg_douyin_ai_cs/services/knowledge_training_service.py apps/xg_douyin_ai_cs/routers/knowledge_training.py
passed
```

car-porject-main 已执行：

```text
python tests\test_douyin_cs_autoreply_9000_proxy.py -v
5 passed

python -m py_compile backend\app.py
passed

python -m unittest discover -s gold\tests -v
11 passed

node --check frontend\assets\app.js
passed
```

## 10. runtime smoke

本轮未执行真实 runtime smoke，未连接真实 Milvus，未触发真实 LLM。

建议后续在已注入测试环境配置后执行：

1. 通过 `/api/douyin-cs-training/ask` 获取 `training_id` 与 assistant message。
2. 对该 message 提交 useful feedback，确认 `rag_ingestion.status=completed`。
3. 通过 search-preview 搜索 synthetic 问题或答案关键字，确认可命中。
4. 重复提交同一 feedback，确认不创建重复文档。
5. 提交 normal / wrong 且无修正，确认 `status=skipped`。

## 11. 安全确认

- 未触发抖音发送。
- 未触发私信发送。
- 未修改自动回复真实发送 gate。
- 未把前端改成直连 9000 / 9100 / Milvus。
- 未提交真实 token / cookie / secret / password / Milvus URI / Qdrant URI。
- 单元测试使用 fake / mock，不连接真实 Milvus。

## 12. 未改内容

- 未修改 NewCarProject。
- 未修改 Qdrant 链路。
- 未修改其他训练标签。
- 未改 ask 为 search-preview。
- 未新增自动发送入口。

## 13. 残留风险

- 如果文档创建成功但训练失败，当前会保留已创建文档并返回 `rag_ingestion.status=failed`，后续需要管理员清理能力。
- 自动入库会影响统一知识库 base 范围，后续需要管理员可见、可删除、可审计。
- 本轮未做真实 Milvus search-preview 命中 smoke，需要部署环境复验。

## 14. 下一步建议

- 做 synthetic runtime smoke，确认 useful / corrected_answer 入库后 search-preview 可命中。
- 增加管理员查看和删除自动入库文档能力。
- 增加 feedback 自动入库审计页或导出能力，降低知识污染风险。

## 统一小高知识库 douyin_account_id=0 检索作用域修复

问题现象：
- AI 抖音客服自动回复训练页面 ask 可能传入 `douyin_account_id=1`。
- 反馈自动入库文档写入统一小高知识库时固定使用 `douyin_account_id=0`。
- ask 检索阶段如果使用前端传入账号 1，会导致 active chunk count 和 RAG search 都查不到已入库的 base 知识，表现为 `used_knowledge_base=false`。

根因：
- 9100 `apps/xg_douyin_ai_cs/services/knowledge_training_service.py` 的 `ask()` 曾使用 `payload.douyin_account_id` 参与 active chunk count 和 `RagSearchRequest`。
- 9000 `app/routers/knowledge_training.py` 曾把前端传入的 `douyin_account_id` 继续透传给 9100 ask。
- 8788 页面曾展示“抖音账号ID”输入框，默认值为 1，容易污染统一知识库检索 scope。

修复策略：
- 9100 `/knowledge-training/ask` 的 RAG 检索 scope 固定为 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=0`、`category_keys=["base"]`。
- 9000 `/knowledge-training/ask` 不再向 9100 透传 `douyin_account_id`。
- `/knowledge-training/search-preview` 已通过 `repository.search_unified_preview()` 固定使用 `UNIFIED_KB_DOUYIN_ACCOUNT_ID=0`，本轮保持不变。
- feedback auto-ingest 继续写入 `douyin_account_id=0`，不改变 useful / corrected_answer / skipped / 幂等逻辑。

前端调整：
- `car-porject-main/frontend/assets/app.js` 移除 AI 抖音客服训练页面的“抖音账号ID”输入框。
- ask 提交 payload 不再携带 `douyin_account_id`。
- `car-porject-main/backend/app.py` 在缺少账号字段时默认按 `"0"` 处理，并兼容旧本地配置中遗留的默认 `"1"`。

测试结果：
- `python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py -q`：11 passed。
- `python -m pytest tests/test_knowledge_training_api.py -q`：13 passed。
- `python -m pytest tests/test_knowledge_training_unified_api.py -q`：13 passed。
- `python -m pytest tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py -q`：8 passed。
- `python tests\test_douyin_cs_autoreply_9000_proxy.py -v`：7 passed。
- `python -m py_compile backend\app.py`：passed。
- `node --check frontend\assets\app.js`：passed。

runtime smoke：
- 本节追加时未重新执行真实 runtime smoke。
- 建议复验：已有 `douyin_account_id=0`、`category_key=base` 的 synthetic 文档后，从 8788 页面或 `/api/douyin-cs-training/ask` 提问，预期 `used_knowledge_base=true`；再用 search-preview 搜同一关键词，预期命中文档。

## 15. P1-DY-CS-TRAINING-FEEDBACK-AUTO-RAG-INGEST-RUNTIME-SMOKE-1

本轮在本地 Docker runtime 中验证 8788 -> 9000 -> 9100 -> 统一知识库闭环，只使用 synthetic 测试问题和测试回答。

部署服务：
- `auto-wechat-api`
- `xg-douyin-ai-cs`
- `knowledge-train`

runtime 结果：
- useful 自动入库：通过，`rag_ingestion.status=completed`，生成 `document_id=17`，`training_run_id=20`。
- useful search-preview：通过，搜索 synthetic 关键词命中 `document_id=17`。
- corrected_answer 自动入库：通过，`rating=wrong` + `corrected_answer` 生成 `document_id=18`，`training_run_id=21`。
- corrected_answer search-preview：通过，搜索 synthetic 修正回答关键词返回 `document_id=18`。
- normal 无修正：通过，`rag_ingestion.status=skipped`，`reason=rating_not_ingestable`。
- wrong 无修正：通过，`rag_ingestion.status=skipped`，`reason=rating_not_ingestable`。
- auto_ingest=false：首次 smoke 发现 8788 转发层将 `auto_ingest` 写死为 true，已最小修复；复测通过，`rag_ingestion.status=skipped`，`reason=auto_ingest_disabled`。
- 幂等：通过，重复提交同一 useful feedback 返回同一个 `document_id=17` / `training_run_id=20`，`reason=already_ingested`。
- 重复检索：通过，search-preview 返回中 `document_id=17` 只出现 1 次。

DB 抽查：
- `knowledge_training_feedbacks` 已具备 `corrected_answer`、`ingestion_status`、`ingested_document_id`、`ingestion_training_run_id`、`answer_hash`。
- `knowledge_documents` 中自动入库文档 `source_type=douyin_cs_training_feedback`、`category_key=base`、`metadata_json` 存在。
- `knowledge_chunks` 已生成对应 chunk。
- 修复前误入库的 synthetic `document_id=19` 已通过删除接口清理，当前 `is_active=0`。

前端点验：
- 8788 页面可访问。
- 前端资源包含“修正后的标准回答”输入控件。
- 前端资源包含 completed / skipped / failed 三类反馈提示文案。
- 未在本轮自动化中执行真实浏览器人工点击。

安全确认：
- 未触发抖音发送。
- 未触发私信发送。
- 未修改自动回复真实发送 gate。
- 未使用真实客户数据。
- 未输出 token、password、Milvus URI、Qdrant URI。
- 9000 / 9100 最近日志敏感关键词粗查未命中。

补充修复：
- `car-porject-main/backend/app.py` 新增 `parse_bool_option()`，让 8788 feedback 转发层尊重显式 `auto_ingest=false`。
- `car-porject-main/tests/test_douyin_cs_autoreply_9000_proxy.py` 新增 `auto_ingest=false` 解析回归测试。

测试结果：
- `python -m pytest tests/test_xg_douyin_ai_cs_training_feedback_auto_ingest.py tests/test_knowledge_training_api.py -q`：23 passed。
- `python -m pytest tests/test_knowledge_training_unified_api.py tests/test_xg_douyin_ai_cs_unified_knowledge_training_api.py -q`：21 passed。
- `python tests\test_douyin_cs_autoreply_9000_proxy.py -v`：6 passed。
- `python -m py_compile backend\app.py`：passed。
- `python -m py_compile app\routers\knowledge_training.py app\services\xg_douyin_ai_cs_client.py apps\xg_douyin_ai_cs\services\knowledge_training_service.py apps\xg_douyin_ai_cs\routers\knowledge_training.py`：passed。

## 16. P1-DY-CS-TRAINING-ASK-MILVUS-SKIP-FIX-1

问题现象：
- 宝塔环境中 `/knowledge-training/search-preview` 可以命中 Milvus 中的统一知识库文档。
- 但 `/knowledge-training/ask` 返回 `used_knowledge_base=false`。
- 9100 SQLite 中统一知识库 scope 下的 active chunk 数量为 0，导致 ask 在进入 Milvus 检索前被跳过。

根因：
- `ask()` 先调用 `_active_base_chunk_count()` 查询 SQLite。
- 当 `active_doc_count=0` 时，旧逻辑直接设置 `rag_skipped=True`，不再执行 `RagSearchRequest`。
- 在 `RAG_VECTOR_BACKEND=milvus` 时，SQLite active chunk count 不能代表 Milvus 是否有可检索数据，因此该 count 不可靠。

修复策略：
- 统一知识库 ask scope 继续固定为 `tenant_id=xiaogao_system`、`merchant_id=xiaogao_base`、`douyin_account_id=0`、`category_keys=["base"]`。
- RAG query 继续只使用清洗后的 `question`，不拼接 prompt、系统提示词或 session history。
- `RAG_VECTOR_BACKEND=milvus` 时，即使 SQLite `active_doc_count=0`，也继续执行 `RagSearchRequest`。
- 仅 SQLite/local 模式下保留 `active_doc_count=0` 时的快速跳过。
- timing log 补充 `vector_backend`、`active_doc_count_source=sqlite`、`active_doc_count_reliable`，只记录长度、数量和布尔值，不打印 question、prompt、answer、chunk 全文或 Milvus URI。

测试结果：
- `python -m pytest tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py -q`：7 passed。

runtime smoke：
- 本节追加时未执行宝塔真实 smoke。
- 建议复验：9100 search-preview 查询“客户问价格还能不能便宜一点”应返回 matches；8788 ask 查询“客户问价格还能不能便宜一点，该怎么回复？”应返回 `used_knowledge_base=true`；9100 日志应显示 `vector_backend=milvus`、`rag_skipped=False`、`match_count>=1`、`used_knowledge_base=True`。

安全确认：
- 未修改 8788。
- 未修改 9000 NewCar/auth/logout。
- 未触发抖音发送或私信发送。
- 未删除已有知识文档。
- 未写入或输出真实 token、URI、password。
