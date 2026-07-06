# P1-END-2 抖音 GMP Webhook 直连接入验收文档

## 阶段名称

抖音/GMP 私信事件回调直连接入 auto_wechat + 入站鉴权策略修正

## 验收日期

2026-06-13

## 背景

线上联调确认了 dev 阶段遗漏的鉴权策略问题：GMP 推送到 callback_url 的入站事件回调不需要鉴权，auto_wechat 初版误将其配置为强制验签，导致真实回调返回 401。

## 核心链路

```text
抖音平台 / GMP 私信事件
    ↓
https://callback.misanduo.com/webhook/douyin
    ↓
宝塔整站反代（callback.misanduo.com → http://127.0.0.1:9000）
    ↓
http://127.0.0.1:9000/webhook/douyin
    ↓
auto_wechat 旧路径兼容路由（douyin_webhook_legacy）
    ↓
_handle_douyin_webhook（共享处理函数）
    ↓
process_webhook_event
    ↓
douyin_webhook_events + DouyinLead
```

## 正式 callback_url

事件回调链接保持不变：

```text
https://callback.misanduo.com/webhook/douyin
```

禁止改为 `/integrations/douyin/webhook`、`douyinapi.misanduo.com`、`127.0.0.1:9000` 等地址。

## 双入口

| 路径 | 角色 |
|------|------|
| `POST /webhook/douyin` | 客户旧路径兼容入口（GMP 实际推送目标） |
| `POST /integrations/douyin/webhook` | 内部/新路径入口（联调测试用） |

两个入口复用同一个 `_handle_douyin_webhook()`，行为完全一致。

## 鉴权策略

| 配置 | 默认值 | 含义 |
|------|--------|------|
| `DOUYIN_WEBHOOK_AUTH_REQUIRED` | `false` | 入站 webhook 不强制签名校验 |

- `false`：GMP 推送直接解析处理，符合业务确认
- `true`：恢复 `X-Auth-Timestamp` + `Authorization` 签名校验（调试/审计用）

**关键约束**：

1. 文档鉴权章节适用于外部系统主动调用 GMP OpenAPI，**不适用**于 GMP 推送 callback_url 的入站 webhook。
2. 不允许默认改回强制鉴权。
3. `verify_signature` 逻辑保留，通过开关控制。

## 授权返回链接（与事件回调无关）

`https://douyinapi.misanduo.com/auth/callback` 是授权流程的 redirect/callback，不等同于事件回调 webhook。本次只确认事件回调链路，`/auth/callback` 迁移待后续单独探索。

## 事件处理规则

| 事件类型 | 行为 |
|----------|------|
| `im_receive_msg` | 创建/更新 DouyinLead |
| `im_send_msg` | 记录事件，不创建线索 |
| `im_enter_direct_msg` | 记录事件，不创建线索 |
| 重复事件 | event_key 幂等去重，不重复创建线索 |

## 已验证结果

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | `POST /webhook/douyin` 已部署到 OpenAPI | ✅ |
| 2 | `https://callback.misanduo.com/webhook/douyin` 保持客户原地址不变 | ✅ |
| 3 | 宝塔整站反代到 9000 | ✅ |
| 4 | `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` 生效 | ✅ |
| 5 | 真实/有效 payload 返回 200 | ✅ |
| 6 | `im_receive_msg` 创建 DouyinLead（lead_id=4, customer_name=正本清源, lead_action=created） | ✅ |
| 7 | `im_send_msg` / `im_enter_direct_msg` 记录但不创建线索 | ✅ |
| 8 | 无效空 body 返回 400（正常行为） | ✅ |

### 日志示例

```text
webhook 鉴权已关闭: source_path=/webhook/douyin, webhook_auth_required=false
webhook 接收成功: event=im_receive_msg
webhook 新建线索: lead_id=4, customer_name=正本清源
POST /webhook/douyin HTTP/1.1 200 OK
```

## 测试结果

```bash
python -m pytest tests/test_douyin_sync.py tests/test_douyin_webhook.py -v
# 45 passed, 0 failed
```

覆盖场景：

- `false` + 主路径无签名 → 200
- `false` + 兼容路径无签名 → 200 + 创建线索
- `false` + 跨路径幂等（共享 event_key）
- `true` + 正确签名 → 200
- `true` + 无签名 → 401
- `true` + 错签名 → 401
- `true` + 兼容路径无签名 → 401

## 问题复盘

**问题**：dev 阶段误将 GMP 文档鉴权章节理解为入站 webhook 必须强制鉴权。

**影响**：GMP 真实回调无签名头时返回 401，私信事件无法入库。

**原因**：未区分"外部系统主动调用 GMP API"与"GMP 推送事件到 callback_url"。

**修复**：新增 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false`，默认关闭入站强制鉴权。

**状态**：已修复，线上日志验证通过。

## 后续待办

| 优先级 | 待办 |
|--------|------|
| P1 | 观察真实私信回调持续稳定性 |
| P1 | 服务器 `.env` 显式保留 `DOUYIN_WEBHOOK_AUTH_REQUIRED=false` |
| P2 | 处理旧 8081 douyinAPI 残留同步链路（建议 `DOUYIN_SYNC_LEGACY_API_ENABLED`） |
| P2 | 授权返回链接 `/auth/callback` 迁移探索 |
