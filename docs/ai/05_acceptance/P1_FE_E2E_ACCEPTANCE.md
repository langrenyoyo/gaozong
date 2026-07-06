# P1-P 前端联调整体验收记录

## 1. 验收信息

验收日期：2026-06-18

任务名称：P1-P-FE-E2E-ACCEPTANCE

验收范围：

1. 抖音AI小高客服工作台人工文本发送入口。
2. 图片/视频资源下载入口。
3. 图片上传入口。
4. 自动发送安全边界。
5. 前端构建基线。

本轮只做前端联调验收记录和静态安全审计，不新增业务能力，不修改后端、数据库、9100、19000，不新增 migration。

## 2. 当前前端入口位置

页面文件：

```text
frontend/src/pages/DouyinAiCsWorkbenchPage.tsx
```

API client：

```text
frontend/src/api/douyinAiCsClient.ts
```

入口位置：

| 入口 | 位置 | 显示条件 | 后端接口 |
| --- | --- | --- | --- |
| 人工确认发送 | “AI 回复建议”卡片标题栏右侧 | 选中会话后显示；缺少账号时禁用 | `POST /integrations/douyin/live-check/messages/send` |
| 下载资源 | 单条媒体消息气泡内 | 仅 image/video/user_local_image/user_local_video 且 `downloadable_resource=true` 时显示 | `POST /integrations/douyin/live-check/resources/download` |
| 暂无资源链接 | 单条媒体消息气泡内 | 媒体消息但 `downloadable_resource=false` 时显示 | 不调用下载接口 |
| 上传图片 | “AI 回复建议”卡片标题栏右侧 | 选中会话后显示；缺少账号时禁用 | `POST /integrations/douyin/live-check/resources/upload-image` |

## 3. 人工文本发送验收结果

代码级验收结果：

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 点击“人工确认发送”后弹窗出现 | 通过 | `openSendDialog()` 只打开弹窗，不调用接口 |
| 弹窗内可人工编辑文本 | 通过 | `textarea` 绑定 `draftReplyText` |
| 点击取消不调用 `/messages/send` | 通过 | 取消按钮只执行 `setSendDialogOpen(false)` |
| 空内容不调用 `/messages/send` | 通过 | `confirmManualSend()` 在内容为空时 `setSendError` 后 `return` |
| 缺少 `conversation_short_id` 不调用 `/messages/send` | 通过 | `confirmManualSend()` 在缺少会话短 ID 时 `return` |
| 确认发送时传 `manual_confirmed=true` | 通过 | `sendDouyinManualMessage({ ..., manual_confirmed: true })` |
| 前端不传 `auto_send` | 通过 | `SendDouyinManualMessageRequest` 无 `auto_send` 字段，调用体未包含该字段 |
| 成功后刷新会话详情和会话列表 | 通过 | 成功后调用 `loadConversationDetail()` 和 `loadConversations()` |
| 失败时不清空用户输入 | 通过 | catch 仅设置 `sendError`，未清空 `draftReplyText` |

未执行真实发送：

```text
为避免误发真实私信，本轮未在真实会话上点击“确认发送”完成上游发送路径。
```

人工 Network 验收要求：

1. 仅使用允许发送的测试会话。
2. 点击“确认发送”后确认请求 URL 为 `/integrations/douyin/live-check/messages/send`。
3. 请求体必须包含 `manual_confirmed=true`。
4. 请求体必须不包含 `auto_send`。

## 4. 资源下载验收结果

代码级验收结果：

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 文本消息不显示下载入口 | 通过 | `mediaTypeForDownload()` 对非 image/video 返回 `null` |
| image/video 且无资源 URL 时不显示“下载资源”按钮 | 通过 | 按钮显示条件为 `downloadableResource` |
| 无资源 URL 的媒体消息显示“暂无资源链接” | 通过 | `mediaType && !downloadableResource` 时显示 `resourceMissingText()` |
| 无资源 URL 不调用 `/resources/download` | 通过 | `downloadMessageResource()` 只由“下载资源”按钮触发；无按钮即无触发入口 |
| 有资源 URL 时显示“下载资源” | 通过 | `downloadable_resource=true` 时显示按钮 |
| 成功后展示 `download_url` | 通过 | `downloadState.downloadUrl` 分支展示链接和复制按钮 |
| 复制链接失败有提示 | 通过 | `copyDownloadUrl()` catch 设置错误提示 |

未执行真实下载：

```text
当前本轮没有确认可安全调用的真实 resource_url 媒体消息，成功下载路径待真实 resource_url 事件验证。
已通过代码审计确认：file_Url/resource_url 为空时不会误触发下载。
```

## 5. 图片上传验收结果

代码级验收结果：

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| 入口在选中会话后显示 | 通过 | “上传图片”按钮位于 `selectedConversation ? (...) : null` 分支 |
| 支持选择本地图片 | 通过 | 文件输入 `type=file`，限制 accept 为 jpg/jpeg/png/bmp/webp |
| 前端拒绝 svg/gif | 通过 | `validateUploadImageFile()` 拒绝 `.svg`、`.gif`、`image/svg+xml`、`image/gif` |
| 前端限制 10MB | 通过 | `MAX_UPLOAD_IMAGE_BYTES = 10 * 1024 * 1024` |
| 使用 data URL 临时读取 base64 | 通过 | `readFileAsDataUrl(file)` 使用 `FileReader.readAsDataURL` |
| 请求体包含 `file_name/image_base64/open_id` | 通过 | `uploadDouyinImage({ file_name, image_base64, open_id })` |
| 请求体不包含 `auto_send` | 通过 | `UploadDouyinImageRequest` 无 `auto_send` 字段，调用体未包含该字段 |
| 成功后展示 `image_id/width/height/md5` | 通过 | `uploadResult` 成功分支展示对应字段 |
| 支持复制 `image_id` | 通过 | `copyUploadedImageId()` 调用 `navigator.clipboard.writeText` |
| 上传成功不调用 `/messages/send` | 通过 | `confirmUploadImage()` 只调用 `uploadDouyinImage()` |
| 关闭弹窗清理上传状态 | 通过 | `closeUploadDialog()` 清空 file/error/result/copied |

未执行真实上传：

```text
为避免本地随意上传真实图片到上游，本轮未执行合法图片真实上传。
非法类型、超大文件等拒绝路径可在浏览器手工选择文件验证。
```

人工 Network 验收要求：

1. 选择合法 png/jpg/webp 后点击“确认上传”。
2. 确认请求 URL 为 `/integrations/douyin/live-check/resources/upload-image`。
3. 请求体包含 `file_name/image_base64/open_id`。
4. 请求体不包含 `auto_send`。
5. 全程不出现 `/messages/send` 请求。

## 6. 自动发送安全边界验证

| 安全项 | 结果 | 证据 |
| --- | --- | --- |
| 页面加载不会自动调用 `/messages/send` | 通过 | `/messages/send` 仅在 `confirmManualSend()` 中调用 |
| 生成 AI 回复建议不会自动发送 | 通过 | `generateReply()` 只调用 `getTrustedReplySuggestion()` |
| 上传图片成功不会自动发送 | 通过 | `confirmUploadImage()` 只调用 `uploadDouyinImage()` |
| 下载资源成功不会自动发送 | 通过 | `downloadMessageResource()` 只调用 `downloadDouyinResource()` |
| 前端发送请求体不包含 `auto_send` | 通过 | 请求类型和调用体均无 `auto_send` |
| 上传请求体不包含 `auto_send` | 通过 | 请求类型和调用体均无 `auto_send` |
| 不把完整 base64 写入 localStorage/sessionStorage | 通过 | 搜索 `localStorage/sessionStorage` 未命中当前工作台上传逻辑 |
| 不 `console.log` 完整 base64 | 通过 | 搜索 `console.log` 未命中当前工作台和 API client |
| 不 `console.log` 完整发送内容或敏感上下文 | 通过 | 当前工作台无 `console.log` |

## 7. 已知限制

1. `user_local_image/user_local_video` 若 `file_Url/resource_url` 为 `null`，前端只能显示“暂无资源链接”，不会调用下载接口。
2. 成功下载路径仍需要真实带 `resource_url` 的媒体事件做人工 Network 验证。
3. 图片上传只返回并展示 `image_id`，当前不发送图片。
4. 合法图片上传成功路径需要在允许调用上游的测试账号上人工验证。
5. 当前仍不做 AI 自动发送。
6. 当前仍不做图片自动发送。
7. 当前不做批量群发、定时发送、9100 自动决策触发发送。

## 8. 测试矩阵

| 场景 | 类型 | 输入 / 操作 | 预期结果 | 验证方式 |
| --- | --- | --- | --- | --- |
| 人工发送取消路径 | 手工验收 | 打开发送弹窗后点击取消 | 不调用 `/messages/send` | 浏览器 Network |
| 人工发送空内容 | 手工验收 | 清空文本后确认发送 | 页面提示错误，不调用接口 | 页面 + Network |
| 人工发送成功路径 | 手工验收 | 测试会话输入文本后确认 | 请求包含 `manual_confirmed=true`，不含 `auto_send` | 浏览器 Network |
| 无 URL 媒体消息 | 代码审计 + 手工验收 | 查看 `file_Url=null` 的图片消息 | 显示“暂无资源链接”，无下载按钮 | 页面 + Network |
| 有 URL 媒体消息下载 | 手工验收 | 点击“下载资源” | 调用下载接口并展示 `download_url` | 浏览器 Network |
| 文本消息 | 代码审计 + 手工验收 | 查看文本消息 | 不显示下载入口 | 页面 |
| 上传非法图片 | 手工验收 | 选择 svg/gif | 前端拒绝或后端拒绝，不调用发送 | 页面 + Network |
| 上传超大图片 | 手工验收 | 选择超过 10MB 图片 | 前端拒绝，不调用上传和发送 | 页面 + Network |
| 上传合法图片 | 手工验收 | 选择 png/jpg/webp 后确认 | 调用上传接口，展示 `image_id`，不调用发送 | 浏览器 Network |
| 构建 | 自动验证 | `npm run build` | 构建通过 | 命令行 |

## 9. 待后续事项

1. 使用真实测试账号补做一次允许发送的 `/messages/send` 成功路径 Network 验收。
2. 等待真实带 `resource_url` 的 image/video 事件，补做下载成功路径验收。
3. 在允许上传的测试账号上补做合法 png/jpg/webp 上传成功路径验收。
4. 若后续要做图片发送，必须单独开新阶段，不得复用 P1-O/P1-P 验收结论直接上线。

