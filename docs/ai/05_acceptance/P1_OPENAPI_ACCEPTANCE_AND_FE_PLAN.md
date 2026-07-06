# P1 OpenAPI 阶段性验收清单与前端人工入口设计

## 1. 当前阶段完成情况

P1-E 到 P1-K 已完成抖音私信 OpenAPI 核心后端能力收口：

| 阶段 | 能力 | 当前结论 |
| --- | --- | --- |
| P1-E | 获取授权页 `get_aweme_auth_url`、签名、配置读取 | 已接入统一签名，请求使用秒级时间戳、`Authorization` 纯签名、同一份 JSON body 用于签名和发送 |
| P1-E-FIX1 | OpenAPI 地址优先级和调试信息 | 已优先使用 `DY_OPENAPI_BASE_URL + DY_OPENAPI_PREFIX`，旧 `DY_BASE_URL` 只作兼容降级 |
| P1-F | `/list_bind_info` 授权账号同步和持久化 | 已落库 `douyin_authorized_accounts`，账号列表优先持久化授权账号，并保留 live-check/event fallback |
| P1-G | callback 私信回调解析和入库 | 已规范化 `conversation_short_id`、`server_message_id`、用户昵称头像、消息类型等字段 |
| P1-H | 人工确认 `/send_msg` 文本发送 | 已完成纯后端，必须 `manual_confirmed=true`，记录强制 `auto_send=0` |
| P1-I | `/download_resource` 多媒体下载 | 已完成纯后端，只处理 image/video，不保存大文件内容 |
| P1-J | `/upload_image_file` 图片上传 | 已完成纯后端，校验 jpg/png/bmp/webp 和 10MB，不保存完整 base64 |
| P1-K | 统一 OpenAPI client、安全错误、日志、文档 | 已统一 `app/services/douyin_openapi_client.py`，错误详情只返回脱敏调试信息 |

本轮只做验收和前端入口设计，不修改业务代码、前端代码、数据库、9100、19000，也不改变 `auto_send=false`。

## 2. 后端接口验收表

| 接口 | 阶段 | 作用 | 调用上游 | 副作用 | 人工确认 | 写库 | 对应表 | 拒绝路径怎么测 | 成功路径怎么测 | 安全注意事项 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `GET /integrations/douyin/live-check/auth-url` | P1-E/P1-K | 获取抖音授权页 URL | 是，`/get_aweme_auth_url` | 无业务写库 | 不需要 | 否 | 无 | 关闭 `DY_LIVE_CHECK_ENABLED` 应 403；缺 `DY_CALLBACK_URL`/`DY_AUTH_REDIRECT_URL` 应 400；上游 403 应 502 且不泄露 secret | 配置齐全并 mock 上游 `code=0,data.auth_url`，应返回 `auth_url` | 不返回 `DY_GMP_SECRET_KEY`、完整签名、完整 canonical string |
| `POST /integrations/douyin/live-check/accounts/sync-bind-info` | P1-F/P1-K | 从上游同步已授权抖音号 | 是，`/list_bind_info` | 更新授权账号快照 | 不需要 | 是 | `douyin_authorized_accounts` | live-check 关闭应 403；上游非 0 或缺 `data.bind_list` 应 502 | mock `bind_list` 后应按 `main_account_id + open_id` upsert | 只保存账号绑定元数据和上游 item JSON，不保存密钥 |
| `GET /integrations/douyin/live-check/accounts` | P1-F/P1-D 修复 | 给工作台返回抖音号列表 | 否 | 无 | 不需要 | 否 | 读 `douyin_authorized_accounts`、`douyin_webhook_events` | live-check 关闭应 403；无授权账号且无事件应返回空数组 | 有持久化授权账号时优先返回；无授权账号但有历史私信事件时返回 `source=webhook_events` 账号 | event-derived 账号只能标记为事件来源，不能伪装成已授权账号 |
| `POST /integrations/douyin/webhook` | P1-G | 接收 GMP 私信回调并入库 | 否 | 写入事件；文本且提取到联系方式时写/更新线索 | 不需要 | 是 | `douyin_webhook_events`、可能写 `douyin_leads` | 生产验签开启时缺签名或签名错误应 401；非法 JSON 应 400；重复事件应标记 duplicate | 发送真实/测试 `im_receive_msg`，应入库事件并按联系方式生成线索 | 保留原始 payload；验签错误不泄露密钥；重复事件不重复生成线索 |
| `GET /webhook-events` | P1-G/原始事件页 | 只读查询 webhook 事件 | 否 | 无 | 不需要 | 否 | 读 `douyin_webhook_events` | 过滤条件无匹配应返回空列表；分页参数越界由 FastAPI 校验 | 按 `event`、`open_id`、`conversation_short_id` 等查询应返回事件摘要 | 原始详情接口才返回 `raw_body`；列表只返回摘要字段 |
| `POST /integrations/douyin/live-check/messages/send` | P1-H/P1-K | 人工确认后发送文本私信 | 是，`/send_msg` | 会发送真实私信；记录发送尝试 | 必须 | 是 | `douyin_private_message_sends` | `manual_confirmed=false` 应 400 且不请求上游；内容为空应 400；找不到上下文应 404；上下文超过 24 小时应 400 | 有 `conversation_short_id`、`server_message_id`、双方 open_id 且 mock 上游成功时，记录 `sent` 并返回 `auto_send=false` | 后端强制 `auto_send=0`；前端只能用户点击触发；失败记录只能保存安全错误 |
| `POST /integrations/douyin/live-check/resources/download` | P1-I/P1-K | 下载私信图片/视频资源 | 是，`/download_resource` | 记录下载尝试和上游下载地址 | 用户点击触发 | 是 | `douyin_message_resource_downloads` | `conversation_short_id` 缺失应 400；非 image/video 应 400；找不到资源 URL 应 400；找不到事件上下文应 404 | 有 image/video 事件和资源 URL，mock 上游成功后返回 `download_url` 并记录 success | 不保存图片/视频二进制；只保存源 URL、下载 URL、响应摘要 |
| `POST /integrations/douyin/live-check/resources/upload-image` | P1-J/P1-K | 上传图片到抖音，获取 `image_id` | 是，`/upload_image_file` | 上传真实图片到上游；记录上传尝试 | 用户点击触发 | 是 | `douyin_image_uploads` | 空 base64、非法类型、扩展名和文件头不匹配、超过 10MB 应 400 且不请求上游 | 合法 jpg/png/bmp/webp 且 mock 上游返回 `data.image_id`，应记录 success | 数据库不保存完整 base64 或二进制，只保存 MD5、sha256、大小、类型和上游 image_id |

## 3. 数据表验收表

| 表 | 来源阶段 | 用途 | 关键字段 | 幂等策略 | 是否保存敏感数据 | 是否保存完整 base64/二进制 | 是否和前端展示有关 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `douyin_authorized_accounts` | P1-F | 持久化 `/list_bind_info` 返回的授权抖音号 | `main_account_id`、`open_id`、`account_name`、`avatar_url`、`bind_status`、`last_synced_at`、`raw_body_json` | 唯一约束 `main_account_id + open_id`，同步时 upsert | 保存 open_id、昵称、头像、绑定状态；不保存 secret/token | 否 | 是，工作台左侧账号列表优先读取 |
| `douyin_webhook_events` | P1-G | 保存真实私信回调原始事件和规范化字段 | `event`、`from_user_id`、`to_user_id`、`conversation_short_id`、`server_message_id`、`message_type`、`parsed_content_json`、`event_key`、`is_duplicate`、`raw_body` | `event_key` 唯一；重复事件写派生 key 且 `is_duplicate=1` | 保存 open_id、消息内容、原始 payload，属于业务敏感数据 | 不主动保存媒体二进制；可能保存上游 payload 中的资源 URL | 是，会话列表、消息详情、原始事件页、发送/下载上下文都依赖 |
| `douyin_private_message_sends` | P1-H | 记录人工文本私信发送尝试和结果 | `conversation_short_id`、`server_message_id`、`from_user_id`、`to_user_id`、`content`、`status`、`manual_confirmed`、`auto_send`、`upstream_msg_id` | 当前按发送尝试追加记录，不做去重；用于审计人工操作 | 保存发送文本和 open_id，不保存 secret | 否 | 后续可用于前端发送结果和审计列表，当前工作台尚未读取 |
| `douyin_message_resource_downloads` | P1-I | 记录资源下载尝试、源 URL、下载 URL 和上游错误 | `webhook_event_id`、`conversation_short_id`、`server_message_id`、`open_id`、`media_type`、`source_url`、`download_url`、`resource_status` | 当前按下载尝试追加记录，不做去重；可追踪每次人工下载 | 保存 open_id 和资源 URL，不保存 secret | 否，不保存大文件内容 | 后续资源下载按钮成功后可展示 `download_url` |
| `douyin_image_uploads` | P1-J | 记录图片上传尝试和上游 `image_id` | `open_id`、`file_name`、`file_ext`、`mime_type`、`file_size_bytes`、`local_md5`、`image_base64_sha256`、`upstream_image_id`、`upload_status` | 当前按上传尝试追加记录，不做去重；可用 MD5/sha256 辅助排查 | 保存文件名、摘要、可选 open_id 和上游 image_id | 否，明确不保存完整 base64/二进制 | 后续上传入口成功后可展示 `image_id`，但不能自动发送图片 |

## 4. 安全边界

1. `auto_send` 必须继续保持 `false`，后端发送记录必须为 `auto_send=0`。
2. `/messages/send` 只能由人工点击触发，且请求体必须 `manual_confirmed=true`。
3. 前端不得传 `auto_send=true`，即使传了也不能影响后端强制值。
4. AI 回复建议只能作为草稿来源，不能自动触发真实发送。
5. 图片上传只获取 `image_id`，不能自动进入发送接口。
6. 资源下载不保存大文件到前端或后端数据库。
7. 任何错误详情不得包含 `DY_GMP_SECRET_KEY`、完整 `Authorization`、完整签名原文、完整 `image_base64`。
8. 上游 OpenAPI 调用统一走 `douyin_openapi_client.py`，禁止在新入口里复制签名逻辑。
9. 继续保留 9100 RAG/LLM 回复建议服务边界，不让 9100 直接触发发送。
10. 不做真实生产 key 切换，配置仍通过现有环境变量和部署流程管理。

## 5. 前端现状审计

### 页面和数据流

当前“抖音AI小高客服”页面位于：

```text
frontend/src/pages/DouyinAiCsWorkbenchPage.tsx
```

当前相关 API 封装位于：

```text
frontend/src/api/douyinAiCsClient.ts
frontend/src/api/douyinLiveCheck.ts
```

当前结构结论：

| 问题 | 结论 |
| --- | --- |
| 当前会话列表数据来自哪个 API | `GET /integrations/douyin/accounts/{account_id}/conversations`，由 `getDouyinAccountConversations()` 调用 9000 |
| 当前消息详情数据来自哪个 API | `GET /integrations/douyin/conversation-messages?conversation_key=...&account_open_id=...`，由 `getDouyinConversationMessages()` 调用 9000 |
| 当前账号列表数据来自哪个 API | `GET /integrations/douyin/live-check/accounts`，由 `fetchDouyinLiveCheckAccounts()` 调用 9000 |
| 当前是否已有发送按钮 | 有禁用按钮，文案为“人工确认发送暂未接入”，尚未接入 `/messages/send` |
| 当前是否已有 AI 建议回复入口 | 有，“生成回复建议”调用 9100 的 `/douyin/conversations/{id}/reply-suggestion`；返回后可复制回复 |
| 当前是否已有资源下载按钮 | 没有 |
| 当前是否已有图片上传入口 | 没有 |
| 当前页面如何识别 `conversation_short_id` | 会话对象有 `conversation_short_id`；消息详情请求用 `conversation.id`/`conversation_key` |
| 当前页面如何识别 `server_message_id` | `DouyinMessageItem` 有 `server_message_id`，消息气泡当前未展示也未用于操作 |
| 当前前端是否能拿到 `customer_open_id` | 会话对象 `open_id` 即客户 open_id；消息对象当前没有单独 `customer_open_id` |
| 当前前端是否能拿到 `account_open_id` | 账号对象有 `account_open_id`；会话详情请求也传入该字段 |
| 当前是否具备接入 `/messages/send` 必要上下文 | 基本具备：`selectedConversation.conversation_short_id`、`selectedConversation.open_id`、`reply.reply_text`/人工输入文本、账号 `account_open_id` 都可获得；后端会通过 `conversation_short_id + customer_open_id` 解析发送上下文 |

### 当前前端缺口

1. 消息详情类型当前固定为文本展示，`DouyinMessageItem` 没有暴露 `message_type`、`media_type`、资源 URL，因此资源下载入口无法可靠判断 image/video。
2. 上传图片入口没有 UI，也没有 9000 API 封装。
3. 当前 AI 回复区只有“复制回复”和禁用发送按钮，没有人工编辑区、确认弹窗、发送中状态和失败 safe_message 展示。
4. 当前 9100 仍只负责建议回复，不能作为发送触发方。

## 6. 前端人工入口设计

### 入口 A：人工发送文本私信

建议按钮名称：

```text
人工确认发送
```

设计：

1. 入口放在现有 AI 回复建议卡片底部，替换当前禁用的“人工确认发送暂未接入”按钮。
2. 用户生成 AI 回复后，可先复制，也可在文本框中人工编辑待发送内容。
3. 点击“人工确认发送”前弹出确认框，展示接收客户昵称、客户 open_id 后 6 位、发送文本摘要。
4. 确认后调用：

```text
POST /integrations/douyin/live-check/messages/send
```

请求体：

```json
{
  "conversation_short_id": "当前会话 conversation_short_id",
  "customer_open_id": "当前会话 open_id",
  "content": "人工确认后的文本",
  "manual_confirmed": true,
  "operator_id": "可选，当前登录用户或空"
}
```

5. 前端不传 `auto_send` 字段。
6. 后端仍强制 `auto_send=false`。
7. 成功后刷新当前消息详情和会话列表。
8. 失败优先展示后端 `safe_message`，没有时展示 HTTP 错误摘要。

可做结论：可以做，适合作为 P1-M。

### 入口 B：下载私信图片/视频资源

建议按钮名称：

```text
下载资源
```

设计：

1. 入口放在单条消息气泡旁，仅 image/video 消息展示。
2. 文本消息不展示下载按钮。
3. 优先请求：

```text
POST /integrations/douyin/live-check/resources/download
```

请求体：

```json
{
  "conversation_short_id": "当前会话 conversation_short_id",
  "server_message_id": "当前消息 server_message_id"
}
```

4. 如果消息详情未来已暴露 `media_type` 和资源 URL，可一并传入以减少后端反查：

```json
{
  "conversation_short_id": "当前会话 conversation_short_id",
  "server_message_id": "当前消息 server_message_id",
  "media_type": "image",
  "url": "上游资源 URL"
}
```

5. 成功后展示 `download_url`，提供复制按钮，不把大文件内容保存到前端状态。

当前能否做：暂不建议直接做完整入口。需要先让消息详情接口或前端模型可靠获得 `message_type/media_type`，否则无法做到“只对 image/video 展示”。

建议拆为 P1-N：先补消息详情媒体字段，再接资源下载按钮。

### 入口 C：上传图片到抖音

建议按钮名称：

```text
上传图片
```

设计：

1. 入口可放在 AI 回复建议区旁边或独立“附件工具”区域。
2. 只做上传，不自动发送图片。
3. 前端限制类型：jpg、jpeg、png、bmp、webp。
4. 前端限制大小：10MB。
5. 读取文件为 base64 后调用：

```text
POST /integrations/douyin/live-check/resources/upload-image
```

请求体：

```json
{
  "file_name": "example.png",
  "image_base64": "去掉 data URL 前缀后的 base64 或完整 data URL",
  "open_id": "可选，当前客户 open_id"
}
```

6. 成功后展示 `image_id`、尺寸、文件大小，并提供复制按钮。
7. 不把 `image_id` 自动传给 `/messages/send`。
8. 图片发送能力后续单独规划，不在 P1-O 实现。

可做结论：可以做上传工具，但必须明确“上传不等于发送”。适合作为 P1-O。

## 7. 暂不做事项

1. 不做 AI 自动发送。
2. 不做图片自动发送。
3. 不做批量群发。
4. 不做定时发送。
5. 不做 9100 自动决策触发发送。
6. 不做前端自动调用 `/messages/send`。
7. 不做文件长期存储。
8. 不做真实生产 key 切换。
9. 不做 `/send_msg` 图片发送扩展。
10. 不改微信助手 19000。
11. 不改 9100 RAG/LLM 业务逻辑。
12. 不新增数据库 migration。

## 8. 人工验证命令

### 8.1 授权页

拒绝路径：

```bash
curl -i https://douyinapi.misanduo.com/api/integrations/douyin/live-check/auth-url
```

当配置缺失或上游失败时，期望返回 400/502，响应不得包含真实密钥或完整签名。

成功路径：

```bash
curl -sS https://douyinapi.misanduo.com/api/integrations/douyin/live-check/auth-url | python3 -m json.tool
```

期望返回 `data.auth_url`。

### 8.2 授权账号同步

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/accounts/sync-bind-info" \
  -H "Content-Type: application/json" \
  --data-binary '{"page_num":1,"page_size":50}' | python3 -m json.tool
```

期望返回 `fetched/upserted/active_count/inactive_count`。

### 8.3 账号列表

```bash
curl -sS https://douyinapi.misanduo.com/api/integrations/douyin/live-check/accounts | python3 -m json.tool
```

期望优先返回 `source=persisted_bind_info` 的授权账号；无授权账号但有历史事件时返回 `source=webhook_events` 的事件来源账号。

### 8.4 Webhook 原始事件

```bash
curl -sS "https://douyinapi.misanduo.com/api/webhook-events?page=1&page_size=5" | python3 -m json.tool
```

期望只读返回事件列表，不改变业务状态。

### 8.5 文本发送拒绝路径

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/messages/send" \
  -H "Content-Type: application/json" \
  --data-binary '{"conversation_short_id":"conv_test","content":"测试","manual_confirmed":false}' | python3 -m json.tool
```

期望 400，且不请求上游、不写发送记录。

### 8.6 文本发送成功路径

成功路径只能在人工确认真实会话、确认接收方和文本内容后执行：

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/messages/send" \
  -H "Content-Type: application/json" \
  --data-binary '{"conversation_short_id":"真实 conversation_short_id","customer_open_id":"真实客户 open_id","content":"人工确认后的文本","manual_confirmed":true}' | python3 -m json.tool
```

期望返回 `auto_send=false`、`manual_confirmed=true`、`status=sent`。

### 8.7 资源下载拒绝路径

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/resources/download" \
  -H "Content-Type: application/json" \
  --data-binary '{"conversation_short_id":"conv_test","server_message_id":"msg_test","media_type":"text"}' | python3 -m json.tool
```

期望 400，提示只支持 image/video。

### 8.8 图片上传拒绝路径

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/resources/upload-image" \
  -H "Content-Type: application/json" \
  --data-binary '{"file_name":"test.svg","image_base64":"PHN2Zz48L3N2Zz4="}' | python3 -m json.tool
```

期望 400，且不请求上游、不保存完整 base64。

## 9. 下一步开发任务拆分

### P1-M：前端接入人工发送文本私信入口

范围：

1. 在 `douyinAiCsClient.ts` 或新的 9000 API 封装中增加 `/messages/send` 请求。
2. 在 `DouyinAiCsWorkbenchPage.tsx` 中增加人工编辑文本、确认弹窗、发送状态和错误展示。
3. 请求必须 `manual_confirmed=true`，前端不传 `auto_send`。
4. 成功后刷新会话详情。

验收：

1. 未点击确认不调用接口。
2. 点击取消不调用接口。
3. 后端返回失败时展示 `safe_message`。
4. 页面仍显示 `auto_send=false`。

### P1-N：前端接入资源下载入口

范围：

1. 先确认或补齐消息详情中的 `message_type/media_type`。
2. 仅 image/video 消息展示“下载资源”。
3. 调用 `/resources/download` 后展示 `download_url` 和复制按钮。

验收：

1. 文本消息不展示下载按钮。
2. image/video 消息能传 `conversation_short_id + server_message_id`。
3. 不保存大文件内容到前端。

### P1-O：前端接入图片上传入口

范围：

1. 增加图片选择和本地校验。
2. 调用 `/resources/upload-image`。
3. 展示 `image_id` 和元数据。
4. 不自动发送图片。

验收：

1. 非 jpg/png/bmp/webp 拒绝。
2. 超过 10MB 拒绝。
3. 成功后只展示 `image_id`，不触发 `/messages/send`。

### P1-P：前端联调与验收

范围：

1. 对 P1-M/N/O 做端到端人工验收。
2. 验证 9100 只生成建议、不触发发送。
3. 验证 9000 所有 OpenAPI 错误展示均使用安全信息。
4. 补充前端 build 和后端回归测试记录。

验收：

1. `npm run build` 通过。
2. 后端相关 pytest 通过。
3. 手动发送必须经过用户确认。
4. `auto_send=false` 全链路保持。
