# Phase 5-E-G 抖音AI客服知识分类与知识库 E2E 验收收口

更新时间：2026-06-20

## 1. 验收结论

Phase 5 主链路 E2E 验收通过。

已完成并通过运行态验收的范围：

1. `9000` `knowledge_categories` 主表与商户分类管理。
2. 前端“知识分类”页面：分类列表与创建 merchant 分类。
3. 前端“知识库”页面：知识文档创建与手动训练。
4. `9000` RAG documents/train 可信代理。
5. Agent 分类绑定与 `allowed_category_keys` 可信注入。
6. `9100` RAG 按分类约束召回。
7. reply-suggestion 返回 `auto_send=false`，仍需人工确认。
8. 企业号解绑 Agent 后重新绑定运行态验证通过。

本轮未做：

1. 文档列表。
2. 文档详情。
3. 文档编辑。
4. 文档删除。
5. chunk 展示。
6. 正式搜索入口。
7. `p5_blocked_test` 负向分类边界运行态验证。

## 2. 验收环境

验收发生时 HEAD：

```text
ad2fdef1abb9e41f14347fb3de2ab51d324c98f0
```

服务状态：

1. `9000 /openapi.json`：200。
2. `9100 /health`：`{"status":"ok"}`。
3. `frontend 5173`：200。

本轮 E2E 验收未修改代码、未执行 migration、未插入/删除/修改运行态数据。

## 3. 测试数据与分类

`GET /knowledge-categories` 返回：

1. `base`。
2. `p5_ec_route_probe`。
3. `p5_acceptance_test`。

说明：

1. `p5_acceptance_test` 已存在，本轮复用。
2. `p5_ec_route_probe` 未删除。
3. `dev-merchant-p5-account` 已授权。
4. `dev-merchant-p5-agent` 存在且状态为 active。

## 4. 知识文档创建与训练

知识文档创建成功：

```text
POST /integrations/douyin-ai-cs/rag/documents
document_id=2
```

请求体只包含业务字段，未传：

1. `tenant_id`。
2. `merchant_id`。
3. `douyin_account_id`。

训练成功：

```text
POST /integrations/douyin-ai-cs/rag/train
training_run_id=2
status=completed
document_count=2
chunk_count=2
```

创建和训练状态保持分离：文档创建只代表 `knowledge_documents` 写入成功；训练成功才代表 `knowledge_chunks` / embedding 已生成或刷新。

## 5. Agent 分类绑定

Agent 分类绑定成功：

```text
agent_id=dev-merchant-p5-agent
manual category_keys=["p5_acceptance_test"]
effective=["base","p5_acceptance_test"]
```

结论：

1. `base` 作为有效分类默认生效。
2. `p5_acceptance_test` 作为 merchant 分类手动绑定生效。
3. `base` 不作为手动绑定分类落库。

## 6. 企业号解绑重绑验证

企业号解绑再重绑成功：

1. 解绑后：`binding_status=unbound`、`bound_agent_id=null`。
2. 重绑后：返回同一条绑定记录 `id=3`。
3. 重绑后：`default_agent_id=dev-merchant-p5-agent`。

结论：后端重绑复活旧记录逻辑在运行态生效，不再新增第二条相同 `account_open_id + agent_id` 历史记录。

## 7. reply-suggestion 分类召回验收

调用路径：

```text
POST /integrations/douyin-ai-cs/conversations/1/reply-suggestion
```

验收结果：

1. 请求未传 `allowed_category_keys`。
2. `9000` 注入 `allowed_category_keys`。
3. 返回内容命中“蓝色星河套餐”。
4. `rag_used=true`。
5. `llm_used=true`。
6. `manual_required=true`。
7. `auto_send=false`。

决策日志确认：

```text
allowed_category_keys=["base","p5_acceptance_test"]
final_auto_send=false
upstream_auto_send=false
```

结论：分类权限由 `9000` 可信注入，并真实参与 RAG 召回链路；前端未向 reply-suggestion 传 `allowed_category_keys`。

## 8. 小插曲与技术债

使用字符串会话 `p5_acceptance_conv` 触发 reply-suggestion 时，`9100` 返回 422。

原因：`9100` 路由当前要求数字型 `conversation_id`。

处理：改用 `conversation_id=1` 后通过。

结论：这是 `9000` / `9100` conversation_id 契约差异，不是分类召回失败。该问题不阻塞 Phase 5，应作为后续契约收敛项记录。

## 9. 安全边界复核

已确认：

1. 未改 `9000` / `9100` / `19000` 业务逻辑。
2. 未改前端业务逻辑。
3. 未改 `auto_send`。
4. 未向 reply-suggestion 传 `allowed_category_keys`。
5. 未使用 `9100` 直连 search 作为正式验收依据。
6. documents/train 请求未传 `tenant_id` / `merchant_id` / `douyin_account_id`。
7. reply-suggestion 返回 `auto_send=false`。
8. 工作台仍是人工确认链路，不是真实自动发送私信系统。

## 10. 后续建议

建议进入 Phase 5 文档收口后的稳定化阶段：

1. 暂缓文档列表、编辑、删除。
2. 暂缓正式搜索入口。
3. 后续补充 `p5_blocked_test` 负向分类边界运行态验收。
4. 收敛 `9000` / `9100` conversation_id 数字型契约差异。
5. 继续保持 `auto_send=false` 作为抖音AI客服强安全边界。
