# M04 AI小高微信助手

> 状态：CURRENT_REALITY_VERIFIED_PENDING_E2E
> 代码基线：c26ec227e70d | 验真日期：2026-08-07

## M04 是什么

M04 是微信自动化执行模块，承担 9000 服务端创建微信任务→19000 Local Agent 领取执行→结果回传→销售反馈采集与持久化的完整闭环。它连接 M02（Lead/分配）和 Windows 微信客户端（UI 自动化）。

## 正式用户能力

| 能力 | 入口 | 状态 |
|---|---|---|
| 微信助手页面 | /wechat-assistant（前端） | ACTIVE |
| Local Agent 状态展示 | GET /agent/status | ACTIVE |
| 手工通知销售 | POST /lead-notifications/send-to-staff | ACTIVE（唯一实际创建 notify_sales 任务的路径） |
| webhook 自动通知 | webhook _dispatch_lead_after_create | CONFIG_DISABLED（auto_notify_disabled） |
| 任务领取执行 | 19000 POST /agent/tasks/poll-and-execute | ACTIVE（需 19000 运行） |
| 回复检测 | 19000 POST /agent/tasks/poll-and-detect | ACTIVE（需 19000 运行） |
| 结果回传 | 9000 POST /wechat-tasks/{id}/result | ACTIVE |
| 销售反馈采集 | detect_reply 链路自动解析 | ACTIVE（需 19000 + 微信） |
| 旧微信自动检测 | wechat_auto_detect_scheduler | LEGACY（AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT 默认关） |
| 旧 Debug 端点 | replies.py 调试接口 | LEGACY（LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED 默认关） |

## Server/Local Agent 边界

- **9000**：创建持久化任务（WechatTask）、提供 poll API、接收 result、解析反馈、写 Lead/CustomerProfile
- **19000**：FastAPI 服务（127.0.0.1:19000），**不碰数据库**，纯 HTTP 轮询 9000 + 本机微信 UI 自动化
- **通信**：HTTP + `X-Local-Agent-Token` header（token→merchant_id 映射）

## Data Owner

| 数据 | Owner |
|---|---|
| WechatTask | M04（wechat_task_service.py create_wechat_task，通用 HTTP 创建已 410 关闭） |
| WechatTask 执行结果 | M04（submit_wechat_task_result） |
| Local Agent 身份/状态 | M04（agent_status_service.py，心跳驱动） |
| SalesStaff | M02/M04 共享（assign_service 创建/查询） |
| ReplyCheck | M04（reply_checker.py record_manual_reply） |
| 销售反馈原文 | M04（从微信消息提取 raw_text） |
| 解析后反馈 | M04（sales_feedback_parser.py upsert SalesLeadFeedback/Update/DailySummary） |

## 主要依赖

- ← M02（data writes）：M02 Lead→M04 创建 WechatTask（手动 send-to-staff，自动 auto_notify_disabled）
- → M02（data writes）：agent_write_back_reply 更新 ReplyCheck + DouyinLead + LeadNotification + CustomerProfile
- → 19000 Local Agent：HTTP poll + 微信 UI 自动化
- → 公共底座：auth（X-Local-Agent-Token）/数据库/商户隔离

## 当前 Runtime 状态

ACTIVE。手工通知→任务领取→执行→回传→反馈解析链路完整。**关键缺口**：无 lease/claim（多 Agent 可能重复拉取）、无崩溃恢复（任务永久停留）、result report 非严格幂等（重复回写有重复扣算力风险）。auto_notify 自动路径已禁用。
