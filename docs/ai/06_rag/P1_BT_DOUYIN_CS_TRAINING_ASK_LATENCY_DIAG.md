# P1-BT-DOUYIN-CS-TRAINING-ASK-LATENCY-DIAG

## 1. 目标与边界

目标：优化宝塔环境下 AI 抖音客服自动回复训练对话 `POST /knowledge-training/ask` 响应慢的问题，并为 9100 ask 增加分段耗时日志。

本轮只修改 9100 训练问答链路、测试和本文档；不修改 8788、9000 gate、NewCarProject、自动回复真实发送 gate，也不把 ask 改成 search-preview。

## 2. 优化前耗时基线

已知运行态基线：

| 链路 | 优化前耗时 |
|---|---:|
| 浏览器 Network | 约 17.71s |
| 8788 完整链路 | 约 13.98s |
| 8788 -> 9000 | 约 14.53s |
| 9000 -> 9100 ask | 约 16.12s |
| 9100 search-preview | 约 5.60s |

判断慢点主要在 9100：空知识库或无命中时仍执行 RAG 检索，之后再调用 LLM 生成回答。

## 3. 根因判断

`apps/xg_douyin_ai_cs/services/knowledge_training_service.py` 中的 `ask()` 原逻辑在 `use_xiaogao_knowledge_base=true` 时直接调用 `search()`。

当统一知识库 `base` 下没有 active chunk 时，检索无法带来命中，但仍会进入 embedding / Milvus 或 SQLite 检索路径，造成约 5 到 6 秒无效耗时。

## 4. 修改内容

1. `ask()` 增加 active base chunk 计数。
2. 当 `active_doc_count == 0` 时跳过 RAG search，继续走 LLM 生成建议回答。
3. 当无法安全判断 active chunk 数量时，保守执行原 RAG 检索。
4. 保持原响应结构不变，仍返回 `training_id`、`answer`、`used_knowledge_base`、`status=answered`。
5. 保持 session 写入不变。

## 5. 9100 timing log 字段

新增 INFO 日志事件：

```text
knowledge_training_ask_timing
```

字段包括：

```text
request_id
training_id
total_ms
active_doc_count
rag_skipped
rag_skip_reason
rag_ms
embedding_ms
milvus_ms
llm_ms
db_ms
match_count
used_knowledge_base
fallback
error_type
rag_query_source
rag_query_chars
prompt_chars
```

日志不打印 question、answer、prompt、source chunk 全文，也不打印 token、key、Authorization、Milvus URI。

## 6. 空知识库跳过 RAG 逻辑

跳过条件：

```text
use_xiaogao_knowledge_base=true
base active chunk count == 0
```

跳过结果：

```text
rag_skipped=true
rag_skip_reason=no_active_documents
rag_ms=0
match_count=0
used_knowledge_base=false
```

如果 active chunk 数量大于 0，仍执行原 RAG search。`search-preview`、文档训练、feedback 均不受该跳过逻辑影响。

## 7. RAG query 构造审计

本轮确认 9100 ask 的 RAG 检索 query 来源为 `question_only`。

规则：

1. embedding/search 阶段只使用 `question` 或极短空白清洗后的 `question`。
2. 不把 prompt、智能体人设、系统提示词、知识库提示词或完整 session history 拼入 RAG query。
3. prompt 只进入 LLM 生成阶段。
4. timing log 只记录 `rag_query_source`、`rag_query_chars`、`prompt_chars`，不打印 query 全文。

## 8. 测试结果

已执行：

```text
python -m pytest tests/test_xg_douyin_ai_cs_knowledge_training_ask_latency.py -q
5 passed
```

覆盖：

1. active chunk 为 0 时 ask 跳过 RAG。
2. active chunk 大于 0 时 ask 仍执行 RAG。
3. RAG query 只使用 question，不包含 prompt。
4. LLM 失败时仍返回 fallback answer 并写入 session。
5. search-preview 不受 ask 跳过逻辑影响。
6. timing log 不包含 question / answer / prompt 全文。

## 9. 宝塔 runtime 验证

本地代码修改已完成；宝塔部署与运行态耗时需在部署后执行：

```text
docker compose -f docker-compose.dev.yml up -d --build xg-douyin-ai-cs
```

待复验字段：

```text
status
elapsed
training_id
has_answer
used_knowledge_base
rag_skipped
rag_skip_reason
knowledge_training_ask_timing
```

优化后 9100 ask、8788 ask 和浏览器耗时待宝塔环境复测后补充。

## 10. 安全确认

本轮未触发：

```text
抖音发送
私信发送
自动回复真实发送 gate
真实客户数据写入
真实业务知识写入
Qdrant
```

本轮未提交真实 token、cookie、secret、password、Milvus URI 或 Qdrant URI。

## 11. 未改内容

未修改：

```text
car-porject-main
NewCarProject
9000 gate
8788 训练页面逻辑
search-preview 业务逻辑
文档训练链路
feedback 链路
自动回复真实发送 gate
```

## 12. 残留风险

1. 优化后真实耗时仍受 LLM provider 响应影响。
2. 如果 base active chunk 计数查询失败，会保守执行原 RAG 检索，不会误跳过。
3. 宝塔环境需确认日志中出现 `knowledge_training_ask_timing`，并记录优化后 9100 / 8788 / 浏览器耗时。

## 13. 下一步建议

部署到宝塔后执行 9100 ask、8788 完整链路和浏览器 Network 复测；如果空库场景仍慢，下一步再基于 timing log 分析 LLM provider 耗时和超时配置。
