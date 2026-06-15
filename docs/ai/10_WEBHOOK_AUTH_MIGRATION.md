# auto_wechat / 小高AI微信助手 Webhook 验签迁移技术方案

版本：P0-WEBHOOK-AUTH-1

依据：

1. `docs/ai/06_PRD_AUTO_WECHAT.md`
2. `docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`
3. `docs/ai/08_DATA_MODEL_AUTO_WECHAT.md`
4. `docs/ai/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`
5. `E:\work\project\douyinAPI` 真实代码只读探索结论

范围：本文只做 Webhook 验签迁移技术方案，不修改业务代码、不修改配置默认值、不改接口实现、不改数据库模型、不新增测试代码、不引入依赖。

------

## 1. douyinAPI 验签实现探索结论

### 1.1 探索路径

已确认 `E:\work\project\douyinAPI` 存在。

重点阅读文件：

1. `E:\work\project\douyinAPI\app.py`
2. `E:\work\project\douyinAPI\test_webhook.py`
3. `E:\work\project\douyinAPI\README.md`
4. `E:\work\project\douyinAPI\.env.example`

### 1.2 入站 webhook 验签代码

douyinAPI 入站验签位置：

```text
E:\work\project\douyinAPI\app.py
```

核心函数：

```text
verify_signature()
```

路由：

```text
POST /webhook/douyin
```

接入方式：

```python
_: None = Depends(verify_signature)
```

结论：douyinAPI 在 FastAPI 依赖层做 webhook 入站验签。

### 1.3 签名算法

douyinAPI 入站验签算法为：

```text
signature = sha256Hex(DY_SECRET_KEY + body + "-" + timestamp)
```

代码事实：

1. 从 Header 读取 `X-Auth-Timestamp`。
2. 从 Header 读取 `Authorization`。
3. 使用 `await request.body()` 读取原始 body。
4. 使用 `hashlib.sha256()` 计算十六进制签名。
5. 使用 `hmac.compare_digest()` 比较签名。

这与新 PRD 冻结的签名规则一致。

### 1.4 SECRET_KEY 来源

douyinAPI 使用全局环境变量：

```text
DY_SECRET_KEY = os.getenv("DY_SECRET_KEY", "")
```

`.env.example` 中也只提供全局 `DY_SECRET_KEY`，未发现按客户 / 商户维度配置密钥的实现。

### 1.5 原始 body 读取

douyinAPI 在两个位置读取原始 body：

1. `webhook_request_logger()` 中先 `await request.body()` 记录请求，再重建 `Request`，避免 body 被消费后下游无法读取。
2. `verify_signature()` 中再次 `await request.body()` 参与签名计算。

结论：douyinAPI 明确使用 HTTP 原始请求体参与验签，不使用 JSON 解析后重新序列化的内容。

### 1.6 timestamp 过期处理

douyinAPI 使用：

```text
DY_ALLOWED_DRIFT_SECONDS = int(os.getenv("DY_ALLOWED_DRIFT_SECONDS", "300"))
```

规则：

```text
abs(now_ts - ts) > DY_ALLOWED_DRIFT_SECONDS → HTTP 401 Request expired
```

### 1.7 验签失败处理

douyinAPI 当前行为：

| 场景 | 当前处理 |
|---|---|
| 缺少 `X-Auth-Timestamp` 或 `Authorization` | 记录 warning 后直接 return，等同放行 |
| `DY_SECRET_KEY` 缺失 | HTTP 500 |
| timestamp 非法 | HTTP 401 |
| timestamp 过期 | HTTP 401 |
| 签名不匹配 | HTTP 401 |

重要结论：缺少签名头时直接放行是 douyinAPI demo 兼容行为，不能迁移为 auto_wechat 生产行为。

### 1.8 日志现状

douyinAPI 会记录：

1. webhook 入站 headers。
2. webhook 入站 body 前 4000 字符。
3. 验签开始日志，包含 body 前 2000 字符。
4. 签名不匹配日志，包含 expected 和 actual。
5. webhook 处理响应。

安全差距：

1. `Authorization` 当前可能以全文进入日志。
2. 签名不匹配时 expected 和 actual 可能全文记录。
3. 生产化方案不得记录 `SECRET_KEY`，`Authorization` 建议只记录脱敏值或 hash。

### 1.9 原始 payload 与事件入库

douyinAPI 原始事件表：

```text
webhook_events
```

相关函数：

```text
build_event_key()
persist_event()
find_existing_event_by_key()
```

入库字段包括：

```text
event
from_user_id
to_user_id
conversation_short_id
server_message_id
message_type
create_time
raw_body
raw_content
event_key
is_duplicate
created_at
```

douyinAPI 对重复事件也会调用 `persist_event()` 写入一条 `is_duplicate=1` 的记录。

### 1.10 测试脚本

douyinAPI 存在测试脚本：

```text
E:\work\project\douyinAPI\test_webhook.py
```

脚本行为：

1. 读取 `sample_webhook_payload.json`。
2. 使用 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 生成 body。
3. 计算 `sha256(secret + body + "-" + timestamp)`。
4. 携带 `Content-Type`、`X-Auth-Timestamp`、`Authorization` 请求 `/webhook/douyin`。

结论：该脚本可作为 auto_wechat 后续签名对照测试样例的参考，但不应直接复制为生产代码。

### 1.11 上游 OpenAPI 主动调用签名

douyinAPI 还存在：

```text
signed_post()
```

该函数用于主动调用 GMP OpenAPI：

1. 使用同一类签名规则生成请求。
2. 使用 `DY_SECRET_KEY`。
3. 发送 Header `X-Auth-Timestamp` 和 `Authorization`。
4. 记录 `api_call_logs`。

结论：主动调用 OpenAPI 的签名生成思路可参考，但 auto_wechat 本轮只处理入站 webhook 验签迁移。

### 1.12 巨量一键过审和私信鉴权复用

douyinAPI 中存在巨量 / OceanEngine 相关配置和接口，例如：

```text
REVIEW_BASE_URL
REVIEW_APP_ID
REVIEW_SECRET
REVIEW_AUTH_TOKEN_PATH
review_auth_records
```

这些属于 AI小高剪辑 / 巨量一键过审方向，不进入 auto_wechat 第一版 Webhook 验签实现。本文只记录其存在，不把它作为小高AI微信助手正式依赖。

### 1.13 可迁移与不可迁移内容

可以参考：

1. `sha256Hex(SECRET_KEY + body + "-" + timestamp)` 计算方式。
2. 使用原始 body 验签。
3. timestamp 过期窗口。
4. `hmac.compare_digest()` 常量时间比较。
5. `test_webhook.py` 的签名样例生成方式。
6. `build_event_key()` 的事件幂等键思路。

不能直接迁移：

1. 缺少签名头直接放行。
2. 全局 `DY_SECRET_KEY` 固化为长期方案。
3. 在日志中全文记录 `Authorization`、expected signature、actual signature。
4. 直接依赖 douyinAPI 运行时服务。
5. 巨量一键过审和 OceanEngine 授权逻辑。

------

## 2. auto_wechat 当前验签现状

### 2.1 当前 webhook 路径

当前已存在：

```text
POST /webhook/douyin
POST /integrations/douyin/webhook
```

代码位置：

```text
app/routers/integrations.py
```

两个路径复用：

```text
_handle_douyin_webhook()
```

### 2.2 当前原始 body 读取

当前两个路由均使用：

```python
body = await request.body()
```

然后把 `body` 传入 `_handle_douyin_webhook()`。

结论：当前已经满足“验签必须使用原始请求体”的基础条件。

### 2.3 当前验签函数

当前已存在：

```text
app/integrations/douyin_webhook.py::verify_signature()
```

当前规则：

```text
SHA256(DY_SECRET_KEY + body + "-" + timestamp)
```

当前处理：

1. 缺少 `X-Auth-Timestamp` 或 `Authorization`：抛 `WebhookSignatureError`，HTTP 401。
2. `DY_SECRET_KEY` 缺失：抛 `WebhookSignatureError`，HTTP 500。
3. timestamp 非法：HTTP 401。
4. timestamp 过期：HTTP 401。
5. 签名不匹配：HTTP 401。

结论：auto_wechat 当前验签函数比 douyinAPI 的入站验签更接近生产安全要求，因为缺少签名头不会放行。

### 2.4 当前配置

`app/config.py` 当前读取：

```text
DY_SECRET_KEY = os.getenv("DY_SECRET_KEY", "")
DY_ALLOWED_DRIFT_SECONDS = int(os.getenv("DY_ALLOWED_DRIFT_SECONDS", "300"))
DOUYIN_WEBHOOK_AUTH_REQUIRED = os.getenv("DOUYIN_WEBHOOK_AUTH_REQUIRED", "false").lower() == "true"
```

`.env.example` 当前配置：

```text
DY_SECRET_KEY=
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

当前注释说明：

```text
GMP 推送 callback_url 不携带签名，默认 false（不鉴权）
置为 true 时恢复 X-Auth-Timestamp + Authorization 校验（仅调试/安全审计用）
```

与新 PRD 冲突：PRD 已冻结为生产环境必须按 OpenAPI 签名规则验签。

### 2.5 当前事件入库

当前原始事件表：

```text
douyin_webhook_events
```

ORM：

```text
app/models.py::DouyinWebhookEvent
```

当前字段：

```text
id
event
from_user_id
to_user_id
event_key
is_duplicate
lead_id
raw_body
created_at
```

当前写入函数：

```text
app/integrations/douyin_webhook.py::persist_webhook_event()
```

当前逻辑：

1. `process_webhook_event()` 先构建 `event_key`。
2. 如果已存在非重复事件，直接返回原事件，不新增重复记录。
3. 如果首次收到事件，写入 `douyin_webhook_events`。
4. 仅 `im_receive_msg` 创建 / 更新 `douyin_leads`。
5. `im_send_msg` 等非线索事件只记录原始事件，不创建线索。

与数据模型目标差异：当前重复事件不新增重复审计记录，事件表未记录 `auth_required / auth_passed / auth_error / timestamp_header / signature_checked_at`。

### 2.6 当前是否具备商户级 SECRET_KEY

当前未发现：

1. `customers` 表。
2. `external_customer_id` 字段。
3. 商户级 `secret_key`。
4. 按抖音账号维度选择 `SECRET_KEY` 的能力。

结论：当前只能使用全局 `DY_SECRET_KEY` 过渡，不能满足最终商户级密钥目标。

### 2.7 当前测试覆盖

当前存在：

```text
tests/test_douyin_webhook.py
```

已覆盖：

1. 正确签名通过。
2. 缺少签名头失败。
3. 缺少 timestamp 失败。
4. 错误签名失败。
5. timestamp 过期失败。
6. 鉴权关闭时两个 webhook 路径可无签名接收。
7. 鉴权开启时 `/integrations/douyin/webhook` 正确签名成功。
8. 鉴权开启时缺签名或错签名失败。
9. 鉴权开启时 `/webhook/douyin` 无签名失败。
10. 两个路径共享幂等。

当前测试仍保留“默认免验签”场景，用于开发 / 联调兼容。

### 2.8 当前测试 / 联调是否依赖免验签

是。`tests/test_douyin_webhook.py` 明确存在：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=false，默认
```

相关用例验证无签名请求可成功。这是旧联调能力的一部分，后续迁移不能直接删除，但必须限定在开发 / 联调环境。

------

## 3. douyinAPI 与 auto_wechat 差异分析

### 3.1 定位差异

douyinAPI 定位：

```text
demo / 参考实现 / 历史代码沉淀
```

auto_wechat 定位：

```text
小高AI微信助手，负责线索消费、销售分配、微信通知、回复检测、超时处理、人工处理、导出
```

结论：auto_wechat 不能把 douyinAPI 作为运行时正式生产依赖，只能参考其验签代码和测试样例。

### 3.2 验签严格度差异

douyinAPI：

1. 缺少签名头时记录 warning 后放行。
2. 适合 demo 联调。
3. 不符合 auto_wechat 生产强制验签要求。

auto_wechat：

1. `verify_signature()` 缺头时会 401。
2. 但总开关默认 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`。
3. 生产环境强制验签尚未落地。

### 3.3 密钥模型差异

douyinAPI：

```text
全局 DY_SECRET_KEY
```

auto_wechat 目标：

```text
第一版按客户 / 商户维度 SECRET_KEY
后续扩展到抖音账号维度
```

当前 auto_wechat 还没有 `customers` 表和商户密钥配置能力，因此第一阶段可以全局密钥过渡，但文档和后续数据模型必须保留商户级目标。

### 3.4 事件入库差异

douyinAPI：

1. 表名 `webhook_events`。
2. 重复事件也写入 `is_duplicate=1`。
3. 保存 `conversation_short_id`、`server_message_id` 等字段。

auto_wechat：

1. 表名 `douyin_webhook_events`。
2. 重复事件返回原事件，不新增重复审计记录。
3. 当前字段较少。
4. 数据模型目标要求语义承接 `lead_source_events`。

### 3.5 日志安全差异

douyinAPI 当前日志可能暴露签名全文。auto_wechat 迁移方案必须：

1. 不记录 `SECRET_KEY`。
2. 不记录完整 `Authorization`。
3. 不记录完整 expected signature。
4. 需要时只记录脱敏值或 hash。

------

## 4. 新 PRD 验签规则

正式签名规则：

```text
signature = sha256Hex(SECRET_KEY + body + "-" + timestamp)
```

Header：

```text
Authorization: signature
X-Auth-Timestamp: timestamp
Content-Type: application/json
```

要求：

1. `body` 必须是 HTTP 请求原始 body。
2. 不允许使用 JSON 解析后重新序列化的 body。
3. `timestamp` 是秒级时间戳。
4. `SECRET_KEY` 第一版按客户 / 商户维度配置。
5. 后续如果每个抖音账号需要不同 `SECRET_KEY`，再扩展到账号维度。
6. 签名失败返回 401。
7. timestamp 过期返回 401。
8. 请求格式错误返回 400。
9. 系统异常返回 500。
10. 成功、重复、非线索、无效线索均返回 200。

------

## 5. 推荐迁移策略

### 5.1 总体方向

推荐策略：

```text
参考 douyinAPI 的签名计算和测试样例；
保留 auto_wechat 当前更严格的缺头拒绝行为；
在 auto_wechat 内部抽象独立 webhook_auth 工具或 service；
开发 / 联调环境保留免验签能力；
生产环境强制验签；
第一阶段使用全局 DY_SECRET_KEY 过渡；
数据模型继续预留商户级 SECRET_KEY。
```

### 5.2 可参考 douyinAPI 的代码逻辑

1. 原始 body 参与签名。
2. `sha256(SECRET_KEY + body + "-" + timestamp)` 计算方式。
3. `hmac.compare_digest()`。
4. `DY_ALLOWED_DRIFT_SECONDS=300` 默认窗口。
5. `test_webhook.py` 的签名生成方式。
6. `signed_post()` 中对 body 使用紧凑 JSON 的测试写法。

### 5.3 auto_wechat 需要自己实现 / 改造的逻辑

1. 环境识别，例如 `APP_ENV=development/staging/production`。
2. 生产环境强制 `DOUYIN_WEBHOOK_AUTH_REQUIRED=true`。
3. 生产环境缺少 `SECRET_KEY` 时拒绝启动或拒绝请求。
4. 商户级 `SECRET_KEY` 获取策略。
5. 安全日志脱敏。
6. 事件表验签审计字段。
7. 两个 webhook 路径共用同一验签结果对象。
8. 与 `douyin_webhook_events` / `lead_source_events` 语义兼容。

### 5.4 模块建议

后续代码方案建议新增等价模块：

```text
app/services/webhook_auth_service.py
```

或放在现有：

```text
app/integrations/douyin_webhook.py
```

推荐前者，原因：

1. 验签属于安全 / 接入层能力，不应和线索 upsert 深耦合。
2. 后续商户级密钥选择、日志脱敏、测试 helper 都可以集中维护。
3. `/webhook/douyin` 与 `/integrations/douyin/webhook` 可复用同一个 service。

建议函数：

```text
calculate_douyin_signature(secret_key, raw_body, timestamp)
verify_douyin_webhook_signature(raw_body, timestamp, signature, secret_key, allowed_drift_seconds)
mask_signature(signature)
build_webhook_auth_context(...)
```

### 5.5 路由复用建议

两个路径：

```text
POST /webhook/douyin
POST /integrations/douyin/webhook
```

必须：

1. 复用同一个 `_handle_douyin_webhook()`。
2. 复用同一套验签函数。
3. 生产环境都不能绕过验签。
4. 日志记录 `source_path`。
5. 正式对外文档只推荐 `/webhook/douyin`。

### 5.6 request_id 和测试 helper

建议：

1. webhook 入口生成或读取 `X-Request-Id`。
2. 日志均带 `request_id`、`source_path`、`auth_required`、`auth_passed`。
3. 提供签名生成测试 helper，确保 auto_wechat 与 douyinAPI 同 body / timestamp / secret 下结果一致。

------

## 6. 环境策略

### 6.1 开发环境

允许：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
```

用途：

1. 本地开发。
2. 手动 curl 测试。
3. 历史 demo 联调。
4. 临时排查请求体解析问题。

要求：

1. 日志必须明确输出“当前 webhook 验签关闭”。
2. 只能用于开发 / 联调。
3. 不得作为正式验收口径。
4. 关闭验签时仍需要记录 `source_path`。

### 6.2 联调 / staging 环境

建议：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=true
```

如果外部平台尚未带签名，可以短时间关闭，但必须：

1. 有明确联调时间窗口。
2. 日志记录关闭原因。
3. 不进入正式验收报告。
4. 联调结束恢复开启。

### 6.3 生产环境

必须：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=true
```

要求：

1. 生产环境不得默认关闭验签。
2. 生产环境缺少 `SECRET_KEY` 时不得静默放行。
3. 生产环境 `SECRET_KEY` 缺失时应启动失败，或 webhook 请求直接拒绝。
4. 生产日志必须记录验签开启状态。
5. 签名失败不得记录 `SECRET_KEY`。
6. `Authorization` 只能脱敏或 hash 后记录。

建议增加：

```text
APP_ENV=development | staging | production
```

生产规则：

```text
APP_ENV=production 且 DOUYIN_WEBHOOK_AUTH_REQUIRED=false → 启动失败或 webhook 拒绝
APP_ENV=production 且 SECRET_KEY 缺失 → 启动失败或 webhook 拒绝
```

------

## 7. SECRET_KEY 策略

### 7.1 目标策略

PRD 目标：

```text
第一版按客户 / 商户维度配置 SECRET_KEY
后续如每个抖音账号需要不同 SECRET_KEY，再扩展到账号维度
```

### 7.2 当前过渡策略

当前代码没有 `customers` 表，也没有商户级密钥表。

因此：

1. 单客户验收阶段允许使用全局 `DY_SECRET_KEY` 过渡。
2. 产品化多商户阶段必须迁移到客户 / 商户维度。
3. 不得把全局 `DY_SECRET_KEY` 固化为长期正式方案。

### 7.3 安全要求

1. 不得把 `SECRET_KEY` 写入日志。
2. 不得把 `SECRET_KEY` 写入前端响应。
3. 不得把 `SECRET_KEY` 保存到 webhook 事件表。
4. `Authorization` 不保存全文。
5. 事件表中如需记录签名，默认保存脱敏值或 hash。

### 7.4 商户级密钥选择预留

后续可按以下顺序选择密钥：

1. 根据反代域名或路径绑定默认商户。
2. 根据 payload 中 `to_user_id / account_open_id / client_key` 定位抖音账号。
3. 根据抖音账号映射到 `customer_id`。
4. 从 `customers.secret_key` 或 `douyin_accounts.secret_key` 读取密钥。
5. 找不到商户时，单客户阶段可 fallback 到全局 `DY_SECRET_KEY`；多商户生产阶段不建议 fallback。

------

## 8. 原始 body 读取策略

FastAPI / Starlette 中使用：

```python
raw_body = await request.body()
```

规则：

1. 验签必须在 JSON 解析前完成。
2. 验签后再解析 JSON。
3. raw body 用于计算签名。
4. raw payload 可用于原始事件入库。
5. 不允许使用解析后的 JSON 重新 `dumps` 再验签。

风险：

```text
如果使用解析后的 JSON 重新 dumps 再验签，字段顺序、空格、转义差异会导致签名不一致。
```

对 douyinAPI 的参考：

1. 入站使用 `await request.body()`。
2. 本地测试脚本使用紧凑 JSON 生成签名。
3. auto_wechat 后续对照测试应使用完全相同的 body bytes。

------

## 9. 错误处理策略

| 场景 | HTTP | 响应体建议 | 是否入业务事件表 | 日志等级 | 是否报警 |
|---|---:|---|---|---|---|
| 成功接收 | 200 | `{"code":0,"msg":"success"}` | 是 | INFO | 否 |
| 重复事件 | 200 | `{"code":0,"msg":"success"}` | 可记录重复命中 | INFO | 否 |
| 非线索事件 | 200 | `{"code":0,"msg":"success"}` | 是 | INFO | 否 |
| 无效线索 | 200 | `{"code":0,"msg":"success"}` | 是 | INFO | 否 |
| body 非法 JSON | 400 | `{"code":400,"msg":"invalid json"}` | 否，或进入安全失败日志 | WARNING | 否 |
| 缺少 Authorization | 401 | `{"code":401,"msg":"unauthorized"}` | 否 | WARNING | 高频报警 |
| 缺少 X-Auth-Timestamp | 401 | `{"code":401,"msg":"unauthorized"}` | 否 | WARNING | 高频报警 |
| timestamp 非法 | 401 | `{"code":401,"msg":"invalid timestamp"}` | 否 | WARNING | 高频报警 |
| timestamp 过期 | 401 | `{"code":401,"msg":"request expired"}` | 否 | WARNING | 高频报警 |
| 签名不匹配 | 401 | `{"code":401,"msg":"signature mismatch"}` | 否 | WARNING | 是 |
| SECRET_KEY 缺失 | 500 或启动失败 | `{"code":500,"msg":"secret key missing"}` | 否 | ERROR | 是 |
| 系统异常 | 500 | `{"code":500,"msg":"internal error"}` | 视发生阶段 | ERROR | 是 |

说明：

1. 验签失败不进入业务原始事件表。
2. 业务成功类结果都返回 200，避免外部平台重复重试。
3. 对外错误信息不暴露内部密钥、期望签名、堆栈。

------

## 10. 入库策略

### 10.1 验签失败

规则：

1. 不进入 `douyin_webhook_events`。
2. 不创建 / 更新 `douyin_leads`。
3. 记录安全日志。
4. 生产环境高频失败需要告警。

### 10.2 验签通过但 JSON 解析失败

规则：

1. 可进入安全 / 失败日志。
2. 不一定进入 `douyin_webhook_events`。
3. 不创建 / 更新有效线索。
4. 返回 400。

### 10.3 验签通过且 JSON 解析成功

规则：

1. 所有事件进入 `douyin_webhook_events`。
2. `douyin_webhook_events` 第一版语义承接 `lead_source_events`。
3. `im_receive_msg` 文本经过联系方式提取后再决定是否进入有效线索。
4. `im_send_msg` 等非线索事件只记录原始事件，不进入分配。
5. 重复事件返回 200，并记录幂等命中结果。

### 10.4 建议补充字段

后续数据模型落地时建议在事件域补充：

```text
auth_required
auth_passed
auth_error
timestamp_header
signature_checked_at
signature_header_hash
source_path
request_id
```

安全规则：

1. 不保存 `SECRET_KEY`。
2. `Authorization` 不保存全文。
3. 如需排查，可保存脱敏值或 hash。

------

## 11. 路由兼容策略

当前接口契约已确认：

```text
正式入口：POST /webhook/douyin
兼容入口：POST /integrations/douyin/webhook
```

技术方案：

1. 两个路径继续复用同一个处理函数。
2. 两个路径都执行同一套验签逻辑。
3. 生产环境两个路径都不能绕过验签。
4. 日志必须记录入口路径 `source_path`。
5. 后续将 `/integrations/douyin/webhook` 标记为兼容路径，不作为对外正式主入口。
6. 正式反代继续保持：

```text
callback.misanduo.com/webhook/douyin
  ↓
auto_wechat:9000/webhook/douyin
```

------

## 12. 测试矩阵

本轮不写测试代码。后续测试至少覆盖以下场景。

### 12.1 验签开启

| 场景 | 输入 | 预期 |
|---|---|---|
| 正确签名 | 原始 body + 正确 timestamp + 正确 signature | HTTP 200 |
| 错误签名 | signature 任意改动 | HTTP 401 |
| 缺少 Authorization | 无 `Authorization` | HTTP 401 |
| 缺少 X-Auth-Timestamp | 无 `X-Auth-Timestamp` | HTTP 401 |
| timestamp 非数字 | `X-Auth-Timestamp=abc` | HTTP 401 |
| timestamp 过期 | 超过允许窗口 | HTTP 401 |
| body 改一个空格 | 签名使用旧 body，请求发送新 body | HTTP 401 |
| SECRET_KEY 缺失 | 生产环境无密钥 | 启动失败或 HTTP 500 |

### 12.2 验签关闭

| 场景 | 输入 | 预期 |
|---|---|---|
| 开发环境关闭验签 | 无签名合法 payload | 可接收请求 |
| 生产环境配置关闭验签 | `APP_ENV=production` 且 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` | 启动失败或强制拒绝 |
| 日志记录 | 验签关闭 | 日志明确记录 `webhook_auth_required=false` |

### 12.3 事件处理

| 场景 | 输入 | 预期 |
|---|---|---|
| `im_receive_msg` 文本包含手机号 | 用户私信文本含大陆 11 位手机号 | 创建 / 更新有效线索 |
| `im_receive_msg` 文本包含微信号 | 文本含 `微信 / wx / vx / v / 加我` 后账号 | 创建 / 更新有效线索 |
| `im_receive_msg` 文本不含联系方式 | 无手机号 / 微信号 | invalid / 原始事件 |
| `im_send_msg` | 发送事件 | 原始事件，不进入有效线索分配 |
| 重复 `server_message_id` | 同一消息重复推送 | 不重复创建线索，HTTP 200 |
| `content` 非法 JSON | content 解析失败 | 参数错误或失败事件 |

### 12.4 douyinAPI 对照测试

必须补充：

1. 使用 douyinAPI `test_webhook.py` 相同 body / timestamp / `SECRET_KEY` 生成签名。
2. 用同一组输入验证 auto_wechat 计算结果一致。
3. 如果 douyinAPI 与文档算法不一致，必须标红说明，不得擅自采用。

当前探索结论：douyinAPI 与 PRD 签名算法一致。

------

## 13. 分阶段迁移计划

### 阶段 1：douyinAPI 验签实现对照

已完成探索项：

1. 找到 douyinAPI `verify_signature()`。
2. 确认算法一致。
3. 确认原始 body 读取方式。
4. 确认 timestamp 窗口。
5. 确认测试脚本。

输出：本文档。

### 阶段 2：auto_wechat 抽象验签工具

后续代码方案：

1. 新增签名计算函数。
2. 新增签名校验函数。
3. 新增签名脱敏 / hash helper。
4. 单元测试覆盖正确签名、错误签名、timestamp 非法、timestamp 过期、body 空格变化。
5. 不直接绑定线索业务逻辑。

### 阶段 3：接入 webhook 路由

后续代码方案：

1. `/webhook/douyin` 接入统一验签 service。
2. `/integrations/douyin/webhook` 复用同一处理逻辑。
3. 保留开发环境免验签能力。
4. 增加日志字段：`request_id / source_path / auth_required / auth_passed`。

### 阶段 4：生产安全配置

后续代码方案：

1. 增加环境识别。
2. 生产环境强制验签。
3. `SECRET_KEY` 缺失时启动失败或请求拒绝。
4. 更新 `.env.example` 和部署说明。
5. 注意：配置默认值修改必须在代码修改计划和用户确认后执行。

### 阶段 5：数据与业务联动

后续代码方案：

1. 写入 `auth_required / auth_passed / auth_error`。
2. 与联系方式提取逻辑联动。
3. 保证无效线索和重复事件仍返回 200。
4. 事件表继续使用 `douyin_webhook_events` 物理表名承接 `lead_source_events` 语义。

### 阶段 6：回归与联调

后续验收：

1. 本地测试。
2. 签名 curl / Python 样例。
3. 火山 / 抖音回调联调。
4. Nginx / 宝塔反代验证。
5. 生产配置检查。

------

## 14. 风险与回滚策略

### 14.1 风险

1. 生产开启验签后，对接方未带签名导致全部 401。
2. `SECRET_KEY` 配置错误导致全部 401。
3. 原始 body 被中间件修改导致验签失败。
4. 服务器时间不同步导致 timestamp 过期。
5. 旧联调脚本不带签名导致不可用。
6. 多商户场景下无法准确定位 `SECRET_KEY`。
7. 两个 webhook 路径验签逻辑不一致。
8. douyinAPI demo 与 auto_wechat 框架差异导致不能直接复制。
9. 旧文档 `P1_END_2_WEBHOOK_ACCEPTANCE.md` 与最新 PRD 对入站验签的口径冲突。

### 14.2 回滚策略

1. 开发 / 联调环境可临时关闭验签。
2. 生产环境不建议关闭验签。
3. 若必须临时关闭生产验签，需要人工审批、时间窗口、日志记录和恢复计划。
4. 保留旧路径兼容，但不允许旧路径绕过生产验签。
5. 通过配置回滚时必须记录日志和告警。
6. 回滚不应删除已入库的原始事件。

------

## 15. 对 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 的最终处理建议

结论：

```text
保留开发 / 联调免验签能力；
生产环境禁止默认 false；
正式验收不再以 false 作为通过口径。
```

分阶段处理：

1. 当前本轮不修改默认值。
2. 下一阶段代码修改计划中引入 `APP_ENV` 或等价环境识别。
3. 开发环境允许 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`。
4. 生产环境强制验签，即使配置为 false 也应启动失败或拒绝请求。
5. `.env.example` 后续需要调整注释，明确 false 仅限开发 / 联调。

------

## 16. 已发现的新旧文档冲突

### 16.1 明确冲突

旧文档 / 旧上下文曾记录：

```text
DOUYIN_WEBHOOK_AUTH_REQUIRED=false
入站 webhook 不强制签名校验
文档鉴权章节不适用于 GMP 推送 callback_url
```

最新 PRD / 架构 / 接口契约已冻结：

```text
生产环境 webhook 必须按 OpenAPI 签名规则验签
signature = sha256Hex(SECRET_KEY + body + "-" + timestamp)
```

处理原则：

1. 以最新冻结 PRD 为准。
2. 旧口径保留为历史联调背景。
3. `false` 只能作为开发 / 联调兼容能力。
4. 生产验收必须强制验签。

### 16.2 代码与目标差距

1. 当前默认值仍为 `false`。
2. 当前缺少环境识别。
3. 当前缺少商户级 `SECRET_KEY`。
4. 当前事件表缺少验签审计字段。
5. 当前 `process_webhook_event()` 未按 PRD 先提取联系方式再生成有效线索。

------

## 17. 后续依赖文档

P0-WEBHOOK-AUTH-1 完成后，后续顺序：

1. 代码修改计划
2. 测试验收计划
3. VibeCoding 分阶段执行计划
4. 部署 / 联调说明

后续文档必须遵守：

1. 不把 douyinAPI 写成正式生产依赖。
2. 不直接删除旧免验签联调能力。
3. 不让生产环境默认关闭验签。
4. 不直接复制 douyinAPI 代码到 auto_wechat。
5. 不修改巨量一键过审边界。
6. 不接入 LLM。

------

## 18. 本轮只读探索记录

已阅读 auto_wechat：

1. `docs/ai/01_READING_RULES.md`
2. `docs/ai/05_PROJECT_CONTEXT.md`
3. `docs/ai/06_PRD_AUTO_WECHAT.md`
4. `docs/ai/07_ARCHITECTURE_AUTO_WECHAT.md`
5. `docs/ai/08_DATA_MODEL_AUTO_WECHAT.md`
6. `docs/ai/09_INTERFACE_CONTRACT_AUTO_WECHAT.md`
7. `docs/ai/02_EXECUTION_RULES.md`
8. `docs/ai/03_TESTING_RULES.md`
9. `docs/ai/04_OUTPUT_RULES.md`
10. `CLAUDE.md`
11. `docs/ai/P1_END_1_ACCEPTANCE.md`
12. `app/main.py`
13. `app/config.py`
14. `.env.example`
15. `app/routers/integrations.py`
16. `app/integrations/douyin_webhook.py`
17. `app/models.py`
18. `tests/test_douyin_webhook.py`

已阅读 douyinAPI：

1. `E:\work\project\douyinAPI\app.py`
2. `E:\work\project\douyinAPI\test_webhook.py`
3. `E:\work\project\douyinAPI\README.md`
4. `E:\work\project\douyinAPI\.env.example`

本轮未修改业务代码、配置默认值、接口实现、数据库模型、测试代码或依赖。
