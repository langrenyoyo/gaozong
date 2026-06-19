# P6 抖音AI客服结构化回复建议闭环验收文档

## 阶段名称

Phase 6-G：智能客服回复建议闭环验收文档

## 验收日期

2026-06-19

## 1. 阶段背景

一期 PRD 中包含“AI 托管模式 / 自动回复”的方向，但当前系统在权限、审计、托管配置、频控、风险识别和发送前二次校验方面尚未形成完整门禁。因此 Phase 6 先将目标拆为：

```text
RAG + LLM 生成结构化智能回复建议
  -> 9000 可信代理做安全后处理
  -> 前端展示给客服
  -> 客服人工确认发送
```

当前产品定位是“结构化智能回复建议 + 人工确认发送”，不是自动发送。`auto_send=false` 仍是强制安全边界。

## 2. Phase 6-A 到 6-F-B 实现链路

| 阶段 | 结论 |
|------|------|
| Phase 6-A | 完成 LLM + RAG 智能客服自动回复能力落地前只读审计，确认已有 RAG + LLM 回复建议，但 LLM 输出仍是自由文本，不适合直接自动发送。 |
| Phase 6-B | 9100 reply-suggestion 实现结构化回复决策，返回 `reply_text`、意图、意向等级、标签、风险、人工原因、知识来源等字段，并继续强制 `auto_send=false`。 |
| Phase 6-C | 9000 reply-suggestion 可信代理透传 9100 结构化字段，同时继续注入真实 Agent / `allowed_category_keys`，并在最终响应中强制 `auto_send=false`。 |
| Phase 6-D | 前端工作台展示结构化智能回复决策，包括安全状态、回复正文、意图、意向等级、风险提示、人工原因、知识来源和调试信息；保留复制回复和人工确认发送。 |
| Phase 6-E | 完成 AI 托管模式 / 自动发送安全门禁只读审计，结论是不建议直接进入真实自动发送，应先补日志、查询、托管配置和 dry-run。 |
| Phase 6-F-B | 9000 新增 `ai_reply_decision_logs` 最小落库能力，记录 9100 原始响应、9000 最终安全后处理、RAG 来源、风险标记和 Agent 分类权限。 |

## 3. 当前真实调用链

```text
前端工作台 DouyinAiCsWorkbenchPage
  -> getTrustedReplySuggestion()
  -> 9000 reply-suggestion proxy
  -> 9000 校验权限、商户上下文、企业号和 Agent 绑定
  -> 9000 读取真实 AiAgent
  -> 9000 注入真实 agent_config / allowed_category_keys
  -> 9100 reply-suggestion
  -> 9100 RAG category_key 过滤检索
  -> 9100 RAG context + Agent prompt 注入 LLM
  -> 9100 结构化回复决策
  -> 9100 强制 auto_send=false
  -> 9000 接收 9100 原始响应
  -> 9000 强制 auto_send=false，并追加必要 risk_flags / warnings
  -> 9000 写 ai_reply_decision_logs
  -> 前端展示结构化回复建议
  -> 客服复制回复或人工确认发送
```

## 4. 当前结构化字段

reply-suggestion 当前保留旧字段兼容，并新增结构化决策字段。

核心字段：

- `reply_text`
- `intent`
- `lead_level`
- `tags`
- `detected_vehicle`
- `detected_contacts`
- `manual_required`
- `manual_required_reason`
- `risk_flags`
- `rag_sources`
- `decision_version`
- `llm_used`
- `rag_used`
- `auto_send=false`

兼容字段：

- `match_level`
- `target_category`
- `target_vehicle_name`
- `recommended_vehicles`
- `lead_capture_required`
- `confidence`
- `source_chunks`
- `warnings`
- `agent_id`
- `agent_name`
- `agent_category`

## 5. 安全边界

当前必须保持以下安全边界：

1. 9100 只提供结构化回复建议，不决定真实自动发送。
2. 9100 服务端最终强制 `auto_send=false`。
3. 9000 作为可信代理再次强制 `auto_send=false`。
4. 前端不向 reply-suggestion 请求传 `auto_send`。
5. 前端不向 reply-suggestion 请求传 `allowed_category_keys`。
6. `allowed_category_keys` 只能由 9000 根据 Agent 分类绑定注入。
7. `agent_config` 只能由 9000 基于真实 `AiAgent` 构造。
8. 人工发送必须保持 `manual_confirmed=true`。
9. AI 回复决策日志写入失败不影响 reply-suggestion 主链路返回。
10. 当前没有 AI 托管自动发送路径，没有自动发送按钮，没有自动发送接口放开。

## 6. AI 回复决策日志

`ai_reply_decision_logs` 的作用是记录每次 reply-suggestion 的 AI 决策过程，为后续 AI 回复记录查询、托管 dry-run、风险审计和问题追溯打基础。

日志记录内容：

- 9100 原始响应副本，包含上游曾返回的 `auto_send`。
- 9000 最终安全后处理结果，包含最终 `final_auto_send=false`。
- `reply_text`、`intent`、`lead_level`、`confidence`、`manual_required`、`manual_required_reason`。
- `risk_flags_json`、`tags_json`、`rag_sources_json`、`source_chunks_json`。
- `allowed_category_keys_json`，来源于 9000 注入值，不来自前端或 9100。
- `llm_used`、`rag_used`、`decision_version`。
- 商户、租户、企业号、会话、客户、Agent 等追溯字段。

日志写入失败时：

- `db.rollback()`。
- 写 `logger.warning(...)`，不打印完整 `latest_message` 或完整原始响应。
- 返回值不影响用户接口响应。
- 不向 response 的 `warnings` 或 `risk_flags` 注入日志失败信息。

## 7. 对一期 PRD 的完成情况

| PRD 能力 | 当前状态 | 说明 |
|----------|----------|------|
| AI客服基于知识库生成回复建议 | 已完成 | 9100 RAG + LLM 生成结构化回复建议。 |
| 按 Agent 绑定知识分类约束知识检索 | 已完成 | 9000 注入 `allowed_category_keys`，9100 按 `category_key` 过滤 RAG。 |
| 展示意图、风险、人工原因、知识来源 | 已完成 | 前端工作台已展示结构化决策字段。 |
| 人工确认发送 | 已完成 | 保留复制回复和人工确认发送，不改变发送接口。 |
| AI 托管模式底层能力 | 部分完成 | 已有结构化决策、风险标记、日志基础，但没有托管配置和 dry-run。 |
| 真实自动发送 | 暂缓 | 当前继续保持 `auto_send=false`，不自动发送。 |

后续需要补齐托管配置、dry-run 日志、自动发送审计、频控、二次读取最新消息、灰度与回滚机制后，才可评估极小范围试点。

## 8. 部署前检查

部署前必须检查：

1. 9100 结构化决策相关测试通过：
   - 合法 JSON 结构化字段返回。
   - 坏 JSON fallback。
   - 空输出 fallback。
   - LLM 未配置 fallback。
   - 风险场景 `manual_required=true`。
   - LLM 试图返回 `auto_send=true` 时最终仍为 `false`。
2. 9000 proxy 测试通过：
   - 结构化字段透传。
   - 上游 `auto_send=true` 时最终压制为 `false`。
   - 前端伪造 `auto_send` / `allowed_category_keys` 不进入上游 payload。
   - `allowed_category_keys` 来自真实 Agent 分类绑定。
   - AI 回复决策日志成功写入。
   - 日志失败不影响 response。
3. 前端构建通过：
   - `cd frontend && npm run build`
4. 数据库迁移检查：
   - `migrations/versions/0014_ai_reply_decision_logs.sql` 未执行前，需要确认目标环境、备份和回滚策略。
   - 不得在未确认环境时直接执行 migration。
5. 安全回归：
   - `auto_send=false` 在 9100、9000、前端展示三层保持。
   - 人工发送仍要求 `manual_confirmed=true`。
   - 前端仍不传 `auto_send` / `allowed_category_keys`。

## 9. 后续路线

建议后续阶段：

| 阶段 | 建议 |
|------|------|
| Phase 7-A | AI 回复记录查询 API。 |
| Phase 7-B | 超级管理员 AI 回复记录页面。 |
| Phase 7-C | 托管配置表只读审计。 |
| Phase 7-D | 托管 dry-run，只记录将要发送的决策，不真实发送。 |
| Phase 7-E | 极小范围自动发送试点，暂缓。 |

## 10. 当前结论

Phase 6 当前闭环已达到：

```text
RAG + LLM 结构化回复决策
  -> 9000 可信代理安全压制
  -> 前端结构化展示
  -> AI 决策日志审计
  -> 人工确认发送
```

当前不是自动发送系统。继续建议保持 `auto_send=false`，在托管配置、dry-run、审计查询、频控、发送前二次校验和回滚机制完成前，不进入真实自动发送。
