# M01 运行时依赖

> source_baseline: c26ec227e70d

## M01 → M02（data，双向各自单向维护）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M01→M02 writes | D | direct DB | webhook upsert DouyinLead + recover_contact_valid（douyin_webhook.py:678,1194） |
| M01→M02 reads | D | service call | 客服工作台读 customer_profiles（douyin_workbench_conversation_service.py:28） |
| M04→M02 writes | D | direct DB | agent_write_back_reply 更新 ReplyCheck+DouyinLead（wechat_ui_reply_service.py:332） |

## M01 → M03（contract，非 runtime）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M01←M03 | X | payload | agent_config 随 HTTP payload 传入 9100（reply_decision_service.py:832），三处组装（dry_run_service.py:315-336 / douyin_ai_cs_proxy.py:322-343 / agents.py:241-262） |

## M01 → M07（runtime）

| 边 | 类型 | mechanism | 证据 |
|---|---|---|---|
| M01→M07 | R | HTTP | compute_usage_client.report_usage 到 9000 /internal/compute/usage（compute_usage_client.py:172,199） |

## M01 → 平台公共底座

| 底座 | 依赖方式 |
|---|---|
| auth/RBAC | auto_wechat:douyin_ai_cs 权限（工作台/设置/记录/灰度） |
| 数据库 | 11 张表 ORM |
| 发送 gate | douyin_autoreply_gate_service.py（pre-LLM + post-LLM + real_send） |
| outbox | ai_auto_reply_outbox_service.py（claim/lease/retry/compensate/alert） |
| 调度器 | outbox + return_visit_silent_scan + contact_invalid_followup |
| 商户隔离 | webhook 事件归属 + run/decision_log 查询过滤 |

## M01 → 外部系统

| 外部系统 | 集成方式 | 证据 |
|---|---|---|
| 抖音 GMP | webhook 直收 + OpenAPI（send_msg/download_resource/decode_msg_content） | integrations.py:845 / douyin_openapi_client.py |
| Milvus | 9100 RAG 向量检索 | reply_decision_service.py:678（仅向量副本非真源） |

## 8 子域间依赖

```
M01-A 入口与会话 ──→ M01-B 编排（enqueue run + wake outbox）
M01-B 编排 ──→ M01-C 9100 Contract（agent_config + suggest_reply）
                ──→ M01-D 客户事实（build_reply_conversation_context + contact_state）
                ──→ M01-E 决策门禁（pre_gate + post_gate）
                ──→ M01-F 发送（send_ai_auto_reply_for_run）
M01-D 客户事实 ──→ M01-G 后续能力（contact_invalid 注入 + 空号追问）
M01-G 后续能力 ──→ M01-F 发送（追问 Worker 走 send_msg）
M01-B 编排 ──→ M01-H 可观测（decision_log + run status + error stage）
M01-F 发送 ──→ M01-H 可观测（send_latency + failure_stage）
M01-A 入口 ──→ M01-G（webhook 恢复 contact_valid + im_send_msg 标记 manual_takeover）
```
