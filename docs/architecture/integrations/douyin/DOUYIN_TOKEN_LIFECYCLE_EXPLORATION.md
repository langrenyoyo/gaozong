# 抖音授权生命周期治理探索报告（P0.5-DOUYIN-TOKEN-LIFECYCLE-EXPLORATION-1）

> 状态：EXPLORATION_COMPLETE（仅探索，未修改代码/数据库/迁移/生产配置，未提交未部署）
> 背景：2026-08-20 生产事故——抖音 AI 自动回复真实发送失败（send_msg upstream_code=400，refresh_token 已过期），
> 主账号授权 2026-07-21，refresh_token 预计 2026-08-20 过期（30 天）。

## # 1. 当前事实

- 抖音真实私信发送走 **GMP（gmp.bytedanceapi.com）签名认证**，`Authorization: sha256(DY_GMP_SECRET_KEY + body + timestamp)`（[douyin_openapi_client.py:94-114](app/services/douyin_openapi_client.py)）。
- send_msg 请求 payload **不包含 access_token / refresh_token**（[douyin_private_message_send_service.py:135-143](app/services/douyin_private_message_send_service.py)）。
- 授权经 GMP：`/auth-redirect` 回跳 → `/list_bind_info` 同步账号 → upsert `douyin_authorized_accounts`（[douyin_live_check.py:231](app/routers/douyin_live_check.py) / [douyin_live_check_service.py:680](app/services/douyin_live_check_service.py)）。
- **本系统不结构化保存 OAuth access_token / refresh_token**（无对应模型列）。
- "refresh_token 已过期" 错误来自 **GMP 上游**（agent 授权 refresh_token 30 天过期），本系统不持有该 token、无续期能力。
- `authorized_at`（工作台展示）由 `bind_time`/`created_at` 派生（[douyin_live_check_service.py:742](app/services/douyin_live_check_service.py)），**不是 token 过期时间**。

## # 2. 调用链

```
真实发送：
  ai_auto_reply_send_service / 回访 / 人工 → douyin_private_message_send_service.send_private_message(:114)
    → call_douyin_openapi("/send_msg", request_payload)（:190）
    → build_signed_openapi_request_body_and_headers（GMP 签名，无 token）
    → requests.post(gmp.bytedanceapi.com/.../send_msg)
    → 上游返回 code!=0 → HTTPException(502) → send_msg 记录 status=failed + error_code/error_message

授权同步：
  GMP authorize → /auth-redirect（douyin_live_check.py:231）→ sync_bind_info_accounts
    → call_douyin_openapi("/list_bind_info")（douyin_live_check_service.py:466）
    → upsert douyin_authorized_accounts（raw_body_json = list_bind_info 原始 item）
```

## # 3. 数据模型

### douyin_authorized_accounts（[models.py:382](app/models.py)）

```
存在字段：merchant_id / tenant_id / main_account_id / open_id / user_id / union_id / account_name /
         avatar_url / bind_status(0/1/2/3) / account_type / bind_time / unbind_time /
         source_created_at / last_synced_at / raw_body_json(JSONB) / created_at / updated_at
缺失字段：access_token / refresh_token / access_token_expire_at / refresh_token_expire_at
         / authorization_health / last_success_at / token_error 等
```

### 相关表

- `douyin_oauth_states`：授权回跳 state（一次性绑定可信商户上下文），无 token。
- `ad_review_oauth_accounts`（一键过审，models.py:1507）：有 `access_token_cipher / refresh_token_cipher / token_expires_at`——**与抖音 AI 客服无关**（AdReview 业务域）。
- `raw_body_json`：存 list_bind_info 原始 item（`SENSITIVE_KEYS` 含 access_token/refresh_token 用于日志脱敏，[douyin_live_check_service.py:29-35](app/services/douyin_live_check_service.py)），**未结构化建模**。

## # 4. 已存在能力

| 能力 | 位置 | 说明 |
|---|---|---|
| 授权回跳同步账号 | routers/douyin_live_check.py:231 `/auth-redirect` | 授权后 list_bind_info 同步 + upsert |
| 账号绑定状态 | models.py:398 `bind_status` | 0 unbound / 1 success / 2 failed / 3 unbound |
| 授权状态展示 | douyin_account_agent_binding_service.py:630 `_authorization_status` | **仅按 bind_status==1 判断 authorized/unauthorized** |
| 发送失败记录 | douyin_private_message_send_service.py:191-198 | status=failed + error_code(upstream_code) + error_message(upstream_msg) |
| 发送流水 | DouyinPrivateMessageSend | status / error_code / error_message / request/response_body_json |
| token 脱敏 | SENSITIVE_KEYS | 日志/诊断不记 access_token/refresh_token/secret |

## # 5. 缺失能力

```
1. OAuth token 结构化存储：access_token / refresh_token / 双过期时间列（无）
2. token 健康状态：token_status / authorization_health / last_success_at（无）
3. 提前过期提醒：refresh_token 到期前 N 天预警（无）
4. 自动续期：renew_refresh_token / 刷新调用（无代码引用）
5. 失败根因分类：refresh_token expired 与其它 400 同 generic 处理（无 token 特定错误码识别/提示）
6. 前端授权失效提示：仅发送流水 failed + 错误串（无"需重新授权"引导）
7. 主动健康检查：无定期 ping / 授权有效性探测
```

## # 6. 风险分析

| 风险 | 等级 | 说明 |
|---|---|---|
| refresh_token 过期导致发送全失败 | 高 | GMP agent 授权 30 天过期，无提前预警；事故 2026-08-20 已发生 |
| 失败暴露滞后 | 高 | token 失效后才在发送流水暴露，运营无预防性可见性 |
| 无自动恢复 | 中 | 过期后需人工经 GMP 重新授权（auth-redirect），无续期/自愈 |
| 无根因分类 | 中 | 400/10010 与 refresh_token expired 同 generic 记录，难以对账 |
| 多模块连带 | 中 | 抖音真实发送（自动回复/回访/人工）共享 send_msg 链路，一个 token 失效全链路阻塞 |

## # 7. UNKNOWN 事项

```
1. GMP 官方是否提供 renew_refresh_token / refresh_token 刷新接口（平台能力）——项目代码无引用，需官方文档确认
2. list_bind_info 上游响应是否含 token/expire 字段（raw_body_json 存原始 item，SENSITIVE_KEYS 提示可能含）——需抽样核对实际响应
3. GMP agent 授权 refresh_token 的确切有效期与续期策略（当前 30 天为事故观测推断）
4. 生产 GMP 授权/agent 的管理入口（重授权操作路径，运维/NewCar 侧）
```

## # 8. 不进入实施的建议方向

> 以下仅为探索后的方向建议，**不实施**，等待 Decision Authority 决策。

```
方向 A：授权状态可见性
  在 douyin_authorized_accounts 增加 token 健康字段（如 last_success_at / token_error / refresh_expire_at），
  由 send_msg 成功/失败回写；前端账号列表展示"授权正常/需重新授权"——需 migration + 写入链路改动。

方向 B：失败根因分类
  send_msg 错误处理按 upstream_code 分类（如 refresh_token expired / 10010），
  单独标记 token 失效 + 记录需重授权；不改变发送语义。

方向 C：提前预警
  基于授权时间（bind_time/created_at）+ 已知 30 天窗口，到期前 N 天告警（需确认 GMP 过期规则）。

方向 D：平台续期对接
  若 GMP 提供 renew_refresh_token，评估自动续期（需官方文档确认 + 授权范围变更）。

优先级建议：A/B 低风险高价值（可见性 + 分类）；C/D 依赖平台能力确认。
```

---
TASK_STATUS: EXPLORATION_COMPLETE
CODE_CHANGE=0 / DB_CHANGE=0 / MIGRATION=0 / DEPLOYMENT=0 / COMMIT=0
等待 Decision Authority 下一步决策
