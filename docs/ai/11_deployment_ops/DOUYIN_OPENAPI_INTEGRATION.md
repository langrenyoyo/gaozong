# 抖音 OpenAPI 接入收口说明

## 配置

当前 9000 后端主动调用抖音 GMP OpenAPI 使用以下环境变量：

| 变量 | 说明 |
| --- | --- |
| `DY_OPENAPI_BASE_URL` | OpenAPI 域名，默认 `https://gmp.bytedanceapi.com` |
| `DY_OPENAPI_PREFIX` | OpenAPI 路径前缀，线上默认 `/ai_chat_agent_api/v1/openapi` |
| `DY_BASE_URL` | 旧版完整 base url，仅作为兼容降级，不建议继续配置 |
| `DY_GMP_SECRET_KEY` | 主动调用 OpenAPI 的签名密钥 |
| `DY_MAIN_ACCOUNT_ID` | 火山主账号 ID |
| `DY_ACCOUNT_NAME` | 火山账号名称 |
| `DY_AUTH_REDIRECT_URL` | 授权成功后的 302 回跳地址 |
| `DY_CALLBACK_URL` | 抖音私信事件回调地址 |
| `DY_CALLBACK_EVENTS` | 回调事件列表，逗号分隔 |

`DY_OPENAPI_BASE_URL + DY_OPENAPI_PREFIX` 优先级高于旧 `DY_BASE_URL`。

## 签名规则

统一实现位于：

```text
app/services/douyin_openapi_client.py
```

签名流程：

1. 使用 `json.dumps(payload, ensure_ascii=False, separators=(",", ":"))` 生成 `body_text`。
2. `timestamp = str(int(time.time()))`，即秒级时间戳。
3. `canonical_string = body_text + "-" + timestamp`。
4. `Authorization = sha256Hex(DY_GMP_SECRET_KEY + canonical_string)`。
5. 实际请求使用 `data=body_text.encode("utf-8")`，不使用 `json=payload`。

请求头：

```text
Content-Type: application/json
X-Auth-Timestamp: timestamp
Authorization: signature
```

## 已接入接口

| 能力 | 上游 path | 本地接口 |
| --- | --- | --- |
| 获取授权页 | `/get_aweme_auth_url` | `GET /integrations/douyin/live-check/auth-url` |
| 同步授权账号 | `/list_bind_info` | `POST /integrations/douyin/live-check/accounts/sync-bind-info` |
| 人工发送文本私信 | `/send_msg` | `POST /integrations/douyin/live-check/messages/send` |
| 下载多媒体资源 | `/download_resource` | `POST /integrations/douyin/live-check/resources/download` |
| 上传图片 | `/upload_image_file` | `POST /integrations/douyin/live-check/resources/upload-image` |

私信回调由以下接口接收：

```text
POST /integrations/douyin/webhook
POST /integrations/douyin/live-check/webhook-observe
```

当前已处理事件：

```text
im_receive_msg
im_send_msg
im_enter_direct_msg
```

## 数据表

当前相关表：

```text
douyin_authorized_accounts
douyin_webhook_events
douyin_private_message_sends
douyin_message_resource_downloads
douyin_image_uploads
```

迁移顺序：

```text
0002_douyin_authorized_accounts.sql
0003_douyin_webhook_event_parsed_fields.sql
0004_douyin_private_message_sends.sql
0005_douyin_message_resource_downloads.sql
0006_douyin_image_uploads.sql
```

## 错误码

统一 OpenAPI client 使用以下错误码：

| 错误码 | 含义 |
| --- | --- |
| `missing_config` | 配置缺失 |
| `network_error` | 网络异常或未收到上游响应 |
| `auth_failed` | HTTP 403，通常是签名或鉴权失败 |
| `upstream_http_error` | HTTP 4xx 非 403 |
| `upstream_server_error` | HTTP 5xx |
| `upstream_business_error` | HTTP 200 但 `code != 0` |
| `invalid_upstream_response` | 响应结构不符合预期 |
| `invalid_upstream_json` | 上游响应不是 JSON |
| `request_build_error` | 请求构造异常 |

## 安全边界

允许记录：

```text
upstream_url
upstream_status
upstream_code
upstream_msg
duration_ms
body_keys
body_sha256
canonical_string_sha256
authorization_preview
openapi_config_source
legacy_base_url_used
legacy_base_url_present
```

禁止记录：

```text
DY_GMP_SECRET_KEY
完整 Authorization
完整 canonical string
完整 image_base64
图片二进制
```

`send_msg` 仍必须 `manual_confirmed=true` 才允许调用上游，且返回与记录中的 `auto_send` 必须保持 `false`。

`upload_image_file` 请求上游时会携带完整 `image_base64`，但数据库只保存文件元数据、MD5 和 `image_base64_sha256`，不得保存完整 base64。

`download_resource` 只保存资源下载元数据和上游下载地址，不保存大文件内容。

## 人工验证

拒绝路径优先验证，避免误调用真实发送：

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/messages/send" \
  -H "Content-Type: application/json" \
  --data-binary '{"conversation_short_id":"@conv_test==","content":"测试","manual_confirmed":false}' | python3 -m json.tool
```

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/resources/download" \
  -H "Content-Type: application/json" \
  --data-binary '{"conversation_short_id":"@conv_test==","server_message_id":"@msg_test==","media_type":"text"}' | python3 -m json.tool
```

```bash
curl -sS -X POST "https://douyinapi.misanduo.com/api/integrations/douyin/live-check/resources/upload-image" \
  -H "Content-Type: application/json" \
  --data-binary '{"file_name":"test.svg","image_base64":"PHN2Zz48L3N2Zz4="}' | python3 -m json.tool
```

回归测试：

```bash
python -m pytest tests/test_douyin_live_check.py tests/test_webhook_events.py tests/test_douyin_workbench_conversations.py -q
```
