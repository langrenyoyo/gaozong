# Phase 7-D 抖音 AI 客服回复记录闭环验收文档

## 阶段名称

Phase 7-D：AI 回复记录闭环文档收口

## 验收日期

2026-06-20

## 1. 阶段背景

Phase 6 已完成“结构化智能回复建议 + 人工确认发送”闭环，并在 9000 新增 `ai_reply_decision_logs` 记录每次 AI 回复建议的结构化决策结果。

Phase 7 的目标是在不进入自动发送、不进入托管模式的前提下，把 AI 回复决策沉淀为商户可查询、可审计、可追溯的记录能力。

当前产品定位保持不变：

```text
结构化智能回复建议 + AI 回复记录审计 + 人工确认发送
```

当前仍不是自动发送系统，`auto_send=false` 仍是强制安全边界。

## 2. Phase 7-A 到 7-C-B 完成链路

| 阶段 | 结论 |
|------|------|
| Phase 7-A | 完成 AI 回复记录查询 API 落地前只读审计，确认 `ai_reply_decision_logs` 已足够支撑第一版商户侧查询。 |
| Phase 7-B | 9000 新增商户侧 AI 回复记录查询 API：`GET /ai-reply-decision-logs` 和 `GET /ai-reply-decision-logs/{log_id}`。 |
| Phase 7-C-A | 完成前端商户侧 AI 回复记录页面落地前只读审计，确认页面应挂在抖音 AI 客服模块下。 |
| Phase 7-C-B | 前端新增商户侧 `AI回复记录` 只读页面，展示 AI 回复建议日志列表和详情。 |

## 3. 当前真实调用链

```text
前端商户侧 AI回复记录页面
  -> frontend/src/api/aiReplyDecisionLogs.ts
  -> 9000 GET /ai-reply-decision-logs
  -> 9000 require_permission("auto_wechat:douyin_ai_cs")
  -> 9000 RequestContext.merchant_id 商户隔离
  -> ai_reply_decision_logs
  -> 返回脱敏后的列表数据
  -> 前端展示列表、分页、筛选、风险、标签、RAG/LLM 状态

前端点击查看详情
  -> GET /ai-reply-decision-logs/{log_id}
  -> 9000 按 merchant_id + log_id 查询
  -> 返回普通商户可见详情
  -> 前端详情弹窗展示，不展示 raw_response_json
```

## 4. 当前 API 能力

商户侧接口：

- `GET /ai-reply-decision-logs`
- `GET /ai-reply-decision-logs/{log_id}`

权限与隔离：

- 必须通过 `require_permission("auto_wechat:douyin_ai_cs")`
- `merchant_id` 必须来自 `RequestContext`
- 前端传入 `merchant_id` 会被后端忽略
- 商户只能查询自己 `merchant_id` 下的日志

列表查询能力：

- `page`
- `page_size`
- `account_open_id`
- `conversation_id`
- `agent_id`
- `manual_required`
- `intent`
- `lead_level`
- `risk_flag`
- `rag_used`
- `llm_used`
- `date_from`
- `date_to`
- `keyword`

列表响应能力：

- `items`
- `total`
- `page`
- `page_size`
- `latest_message_summary`
- `reply_text_summary`
- `intent`
- `lead_level`
- `confidence`
- `manual_required`
- `manual_required_reason`
- `risk_flags`
- `tags`
- `rag_used`
- `llm_used`
- `upstream_auto_send`
- `final_auto_send`
- `decision_version`
- `created_at`

详情响应能力：

- 列表基础字段
- `latest_message`
- `reply_text`
- `rag_sources`
- `source_chunks`
- `allowed_category_keys`

普通商户详情暂不返回：

- `raw_response_json`

## 5. 当前前端能力

新增文件：

- `frontend/src/api/aiReplyDecisionLogs.ts`
- `frontend/src/pages/AiReplyDecisionLogsPage.tsx`

修改入口：

- `frontend/src/pages/Index.tsx`
- `frontend/src/components/SideNav.tsx`

菜单与页面：

- 商户侧菜单：`AI回复记录`
- 导航 key：`douyin-ai-cs-reply-records`
- 页面归属：抖音 AI 小高客服附近
- 推荐路由语义：`/douyin-ai-cs/reply-records`

页面能力：

- 列表表格
- 服务端分页
- 关键词搜索
- 筛选：`manual_required`、`intent`、`lead_level`、`rag_used`、`llm_used`
- 时间范围：`date_from`、`date_to`
- 详情弹窗
- 展示脱敏摘要
- 展示风险标记、标签、人工确认原因
- 展示 RAG/LLM 使用状态
- 展示 `final_auto_send=false` 安全状态
- `upstream_auto_send=true` 时提示“上游曾请求自动发送，已被系统关闭”

页面不提供：

- 发送按钮
- 使用该回复按钮
- 重新发送按钮
- 自动发送按钮
- 托管发送按钮
- 有效/无效标记
- 人工反馈
- 超管跨商户查询

## 6. 安全边界

当前必须保持：

1. 前端查询 AI 回复记录时不传 `merchant_id`。
2. 前端查询 AI 回复记录时不传 `auto_send`。
3. 前端查询 AI 回复记录时不传 `allowed_category_keys`。
4. API 封装层使用白名单组装查询参数，不直接 spread 原始 params。
5. 后端权限和商户隔离以 `RequestContext.merchant_id` 为准。
6. 普通商户列表和详情均不展示 `raw_response_json`。
7. 前端页面只读，不提供任何发送入口。
8. 详情弹窗只允许关闭类操作。
9. 当前没有 AI 托管自动发送路径。
10. `auto_send=false` 继续作为 9000 / 9100 / 前端展示共同确认的安全边界。

## 7. 验证记录

Phase 7-B 后端 API 验证范围：

- 商户列表只返回自己 `merchant_id` 的日志
- 前端传 `merchant_id` 被忽略
- 缺少权限返回 403
- 缺少 `merchant_id` 返回错误
- 分页正确
- `page_size` 上限生效
- `manual_required` / `intent` / `lead_level` / `rag_used` / `llm_used` 筛选正确
- `risk_flag` 筛选正确
- `keyword` 匹配 `latest_message` / `reply_text`
- `date_from` / `date_to` 筛选正确
- 详情只能查自己商户日志
- 列表不返回 `raw_response_json`
- 详情不返回 `raw_response_json`
- 坏 JSON 字段不导致 500

Phase 7-C-B 前端验证：

```bash
cd frontend
npm.cmd run build
```

构建结果：

- Vite build 通过
- 仍有既有字体路径提示：`/fonts/Barlow-Regular_2.ttf` 构建时未解析，运行时保留
- 仍有既有大 chunk 警告

说明：

- Windows PowerShell 直接执行 `npm run build` 时可能因本机执行策略拦截 `npm.ps1`
- 使用 `npm.cmd run build` 可正常完成同一构建流程

## 8. 对产品闭环的意义

Phase 7 完成后，抖音 AI 客服链路从“只生成建议”扩展为“建议可记录、可查询、可审计”：

```text
9100 RAG + LLM 结构化回复决策
  -> 9000 可信代理压制 auto_send=false
  -> 9000 写 ai_reply_decision_logs
  -> 9000 商户侧查询 API
  -> 前端商户侧 AI回复记录页面
  -> 客服/商户查看历史建议、风险、人工原因和知识来源
```

这为后续能力打基础：

- AI 回复记录查询
- 问题排查
- 商户侧审计
- 托管 dry-run
- 自动发送试点前的风控分析

但这不代表已经进入自动发送阶段。

## 9. 后续路线

建议后续阶段：

| 阶段 | 建议 |
|------|------|
| Phase 7-E | 超管侧 AI 回复记录查询 API / 页面，后置。 |
| Phase 7-F | AI 回复记录导出、筛选增强、风险统计，后置。 |
| Phase 8-A | 托管配置表只读审计。 |
| Phase 8-B | 托管 dry-run，只记录“如果开启托管会不会发送”，不真实发送。 |
| Phase 8-C | 自动发送安全门禁二次审计。 |
| Phase 8-D | 极小范围自动发送试点，继续暂缓。 |

## 10. 当前结论

Phase 7 当前闭环已达到：

```text
AI 回复决策日志落库
  -> 商户侧查询 API
  -> 商户侧只读页面
  -> 风险、标签、人工原因、RAG/LLM 状态可审计
```

当前仍然不是自动发送系统。

继续建议保持：

```text
auto_send=false
人工确认发送
前端只读查看 AI 回复记录
```
