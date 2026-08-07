# M04 运行时依赖

> source_baseline: c26ec227e70d

## M02 → M04（data，task 投递）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M02→M04 | D | task | 手动 send-to-staff 创建 notify_sales WechatTask（lead_notification_actions.py:120）；自动 webhook auto_notify_disabled（douyin_webhook.py:1030） |

> M02→M04 当前只有手动路径活跃，自动路径 CONFIG_DISABLED。

## M04 → M02（data，回写）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M04→M02 | D | direct DB | agent_write_back_reply 更新 ReplyCheck + DouyinLead + LeadNotification + CustomerProfile（wechat_ui_reply_service.py:332; reply_checker.py:15） |

> M04 直接操作 M02 ORM/table（DATA_COUPLING），不经正式 M02 service。

## 9000 ↔ 19000（runtime boundary）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| 9000→19000 | R | HTTP | 19000 poll 9000 HTTP API（local_agent_main.py:1953 GET /wechat-tasks/pending） |
| 19000→9000 | R | HTTP | result 回写 POST /wechat-tasks/{id}/result（local_agent_main.py:593） + heartbeat POST /agent/heartbeat（:504） |
| 认证 | — | token header | X-Local-Agent-Token（local_agent_auth.py:12）→ merchant_id 映射（:32-48） |

> 19000 不碰数据库（DATABASE_URL 从 Worker 环境剥离），所有数据访问经 9000 HTTP。

## 19000 → Windows WeChat（external runtime）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| 19000→WeChat | X | UI Automation | open_chat_by_nickname + verify_current_chat_contact（OCR）+ 文本粘贴/发送（local_agent_main.py:1094,1128） |

> 依赖：Windows + 微信客户端 + UI Automation + OCR + 本机文件系统。不容器化。

## M04 → 平台公共底座

| 底座 | 依赖方式 |
|---|---|
| auth | X-Local-Agent-Token（非普通 /auth/me） |
| 数据库 | WechatTask + ReplyCheck + LeadNotification + SalesLeadFeedback/Update/DailySummary |
| 商户隔离 | token→merchant_id + lead/staff FK 反查 |

## Legacy / Compat 交叉引用

| 项 | 与 M04 关系 | 状态 | 引用 |
|---|---|---|---|
| AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT | 旧微信自动检测调度器 | LEGACY（默认关） | LEGACY_REGISTER LEGACY-002 |
| LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED | 旧 Debug 端点 | LEGACY（默认关） | LEGACY_REGISTER LEGACY-007 |
| legacy_foreground_ok/diag | 诊断字段（非独立 guard，正式链仍用 _ensure_wechat_foreground） | ACTIVE（诊断输出），建议从 UNKNOWN→ACTIVE | LEGACY_REGISTER LEGACY-010 |
| auth_mode="legacy" | Local Agent 旧未认证回退 | LEGACY（默认关） | LEGACY_REGISTER LEGACY-009 |
