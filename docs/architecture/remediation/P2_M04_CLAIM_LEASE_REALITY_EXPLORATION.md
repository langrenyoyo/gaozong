# P2 — M04 Claim/Lease Reality Exploration

> 窗口：P2 M04 Claim/Lease Reality Exploration
> 模式：READ ONLY / EXPLORATION ONLY — 不实施、不迁移、不改状态机、不提交、不 push
> 基线 commit：`1d7f1f5`（P1 FINAL CLOSURE COMMIT，COMPUTE-IDEMPOTENCY-001=CLOSED）
> 探索日期：2026-08-12
> 审查对象：M04 微信任务执行权（claim/lease/retry/crash recovery）— current code & DB facts
> 前序：`docs/architecture/CROSS_MODULE_RISK_REGISTER.md` HIGH-02 / ISSUE-M04-001
> 裁定：见 §33

---

## 1. Governance Baseline

```
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED（commit 1d7f1f5，未 push）
TECHNICAL_CLOSURE = VERIFIED
P2 M04 CLAIM/LEASE = EXPLORATION_COMPLETE / DESIGN_PENDING
```

本轮仅探索。P1 CLOSED 不重新打开。P2 不得标 RESOLVED / IMPLEMENTED。

P1↔P2 边界（§27）：即使重复 M04 task 导致两次 AI 调用，P1 只保证"同一 Business Event Identity → compute billing 不重复"；外部微信副作用仍可能重复。P1 不解决 M04 任务执行 exactly-once。

---

## 2. Scope

从当前代码 + DB 事实重建 M04 微信任务执行模型：任务如何被发现、领取、执行、重试、恢复、完成；判断是否真实存在多 worker / scheduler / recovery cycle 对同一任务产生重复执行副作用的路径。

**不得**从"没有 claim/lease"直接推导"duplicate execution definitely exists"。以 current code 为准。

---

## 3. M04 Architecture

- **M04 = 小高AI微信助手**（WeChat task execution）。前端 nav `ai-agent`/`wechat-config`/`wechat-tasks`；后端 router `wechat_tasks.py`/`replies.py`/`daily_report_deliveries.py`/`agent.py`；service `wechat_task_service.py`/`wechat_ui_reply_service.py`/`daily_report_delivery_service.py`；Local Agent `app/local_agent_main.py`（19000 进程，小高AI微信助手.exe，宿主机 Windows，不进容器）。
- 数据 Owner：WechatTask、执行结果、Local Agent 身份/状态、ReplyCheck、销售反馈。
- **任务分发模型：POLL**（19000 主动向 9000 GET pending 任务），不是 push。9000 从不主动推任务给 19000。
- 三类 task_type：
  - `notify_sales` — 销售通知（可真实发送微信消息）
  - `detect_reply` — 检测销售是否已回复（read_only，无外部副作用）
  - `send_report_attachment` — 报表附件投递（**整条链路 DORMANT，见 §5/§10**）

---

## 4. Task Schema

`WechatTask` 定义于 `app/models.py:290-336`（`__tablename__="wechat_tasks"`）。唯一约束：`UniqueConstraint("report_delivery_id","delivery_attempt_no",name="uk_wechat_tasks_delivery_attempt")`（仅 send_report_attachment 用）。

| 字段 | 类型 | 行 | 说明 |
|---|---|---|---|
| id | Integer PK autoincrement | 297 | |
| task_type | String(30) default="notify_sales" | 298 | notify_sales / detect_reply / send_report_attachment |
| lead_id | FK→douyin_leads.id | 300 | 创建后不可变，永久绑定 |
| staff_id | FK→sales_staff.id | 301 | |
| reply_check_id | FK→reply_checks.id | 302 | |
| target_nickname | String(100) | 303 | |
| message | Text | 304 | |
| mode | String(20) default="paste_only" | 305 | paste_only / single_send / read_only |
| status | String(20) default="pending" | 307 | 注释列 pending/running/pasted/sent/failed/blocked/cancelled |
| failure_stage | String(100) | 309 | |
| raw_result | _JSONStringJSONB | 310 | |
| agent_hostname | String(100) | 311 | **事后审计**（回写时填，非领取前绑定） |
| agent_pid | Integer | 312 | **事后审计** |
| pasted_at / sent_at | DateTime | 313-314 | |
| created_at / updated_at | DateTime | 315-316 | |
| Phase 8-B 附件投递专用 | 多字段 | 318-331 | execution_token_hash / execution_started_at / download_ticket_hash / download_ticket_expires_at / send_nonce_hash / send_nonce_expires_at / send_authorized_at / attachment_* 等（仅 send_report_attachment） |

**所有权/租约字段判定（重点）**：

- `claim_token` / `worker_id` / `claimed_at` / `heartbeat` / `locked_until` / `processing_since` / `owner` / `lease_expires_at` → **对 notify_sales / detect_reply 全部不存在**。
- `agent_hostname`/`agent_pid` 存在但**仅回写时填充**（`wechat_task_service.py:351-352`），拉取时不写、不参与所有权判定。
- `execution_token_hash`/`execution_started_at`/`download_ticket_expires_at`/`send_nonce_expires_at` 等"claim 级"字段**只服务于 send_report_attachment**，对 notify_sales/detect_reply 完全不适用。
- `running` 状态：模型注释列出（`models.py:307`），但**全代码库无任何位置把 status 写成 `running`**——`create_wechat_task` 直接 pending，`submit_wechat_task_result` 一次性写终态。`running` 是从未被使用的状态。

**Schema/ORM 漂移**：迁移 `migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py:138-139` 在 DB 层创建了 `tenant_id` + `merchant_id` 列并建索引 `idx_wechat_tasks_merchant_status_created`，但 **ORM 模型未定义这两列**，写路径 `create_wechat_task`/`retry_delivery` 均不填 → task 表自身 merchant_id/tenant_id 列恒 NULL，商户隔离完全靠 `lead.merchant_id` + `staff.merchant_id` 的 INNER JOIN AND 双重过滤（`wechat_task_service.py:122-130,150-161`）。未来 claim 设计若需 `WHERE merchant_id=... AND status='pending'` 的 index，**DB 层已有该 index 但 ORM 列未映射**——属设计输入，本轮不提结论。

---

## 5. Task Producers

| Producer | Entry Point | Task Type | Initial Status | Business Identity | 重复创建防护 |
|---|---|---|---|---|---|
| P1 `create_wechat_task` | `lead_notification_actions.py:42` `POST /lead-notifications/send-to-staff` → `wechat_task_service.py:35,74-89` | notify_sales | pending | 9000，已鉴权用户，mode=single_send | `evaluate_lead_wechat_notify_eligibility` 前置判定（EXISTING_PENDING_TASK/ALREADY_SENT/RATE_LIMITED）`lead_notification_actions.py:51-83` |
| P2 `_auto_create_detect_reply_task` | `wechat_task_service.py:1023,1088-1103`（notify_sales pasted/sent 成功后内部调用 `:429,461`） | detect_reply | pending | 9000 内部（非 HTTP），mode=read_only | 同 lead_id+staff_id 已有 pending detect_reply 则跳过 `:1074-1085` |
| P3 `retry_delivery` | `daily_report_delivery_service.py:212,240-251` | send_report_attachment | pending | 9000 | `uk_wechat_tasks_delivery_attempt` 唯一约束 + IntegrityError 回滚 `:256-262` |
| P4 `ensure_deliveries_for_job` | `daily_report_delivery_service.py:132`（`daily_report_job_service.py:410` 调用） | **不创建 WechatTask**，只建 DailyReportDelivery | — | — | — |

**P3 ★ DORMANT**：`retry_delivery` 在生产代码中**无任何调用者**——`daily_report_job_service.py:45-50` 未 import 它，`daily_report_deliveries.py` 路由只有 agent 机器接口（pending/claim/attachment/send-intent/result）无 retry/dispatch 端点。send_report_attachment WechatTask 在生产中从不被创建。

**已禁用生产者**：
- 抖音线索同步自动创建 `douyin_sync_service.py:204` → 永久走 `auto_create_wechat_task_disabled` 分支（`:206-213`），即使 `auto_create_wechat_task=true` 也不创建。
- 通用 HTTP `POST /wechat-tasks` → `wechat_tasks.py:35-48` `create_wechat_task_disabled()` 永久 410 `DIRECT_WECHAT_TASK_CREATE_DISABLED`（Phase 7-FIX2）。

**"同一业务事件是否可能创建多个 task"**：活跃路径（P1/P2）均有前置去重判定；P3 有唯一约束。**生产者侧多创建风险低**（前提：判定逻辑正确，属 P2 设计需复核项，但本轮未发现明显重复创建路径）。

---

## 6. Task Consumers

| Consumer | Process | Selection Query | Status Filter | Lock/Claim | Executes Side Effect |
|---|---|---|---|---|---|
| C1 19000 poll-and-execute (notify_sales) | 19000 Local Agent | `GET /wechat-tasks/pending?task_type=notify_sales&limit=1` → `get_pending_wechat_tasks` `wechat_task_service.py:100-132` | status==pending | **进程内 `_wechat_task_lock`**（`local_agent_main.py:1898`）；**无 DB claim** | 是（UIA 粘贴/发送） |
| C2 19000 poll-and-detect (detect_reply) | 19000 Local Agent | 同上，task_type=detect_reply | pending | 进程内 `_wechat_task_lock`；无 DB claim | 否（read_only） |
| C3 19000 poll-and-send-report (send_report_attachment) | 19000 Local Agent | `GET /daily-report-deliveries/agent/pending?limit=1` → `list_pending_delivery_tasks` `daily_report_delivery_service.py:388-417` | pending | 进程内锁 + **DB 原子 claim** `claim_delivery_task` `:433-469` | dry_run=true 强制（`local_agent_main.py:2513,2521-2525`）；dry_run=false blocked |
| C4 9000 submit_wechat_task_result (notify_sales/detect_reply 回写) | 9000 | `POST /wechat-tasks/{task_id}/result` → `wechat_task_service.submit_wechat_task_result` `:302-474` | — | 无 CAS、无 status 当前值检查 | 写 status + 联动通知 + 上报算力 |
| C5 9000 agent-write-back (detect_reply 回写) | 9000 | `POST /replies/agent-write-back` `replies.py:84-172` | — | 无 | 写 ReplyCheck/LeadNotification，不直接写 task.status |
| C6 9000 claim_delivery_task (send_report_attachment claim) | 9000 | `POST .../claim` → `claim_delivery_task` `:433-469` | pending | **原子 UPDATE WHERE status=pending + rowcount==0 → ClaimConflictError** | 生成 token/download_ticket（仅 hash） |
| C7 authorize_send_intent | 9000 | `POST .../send-intent` `:504-552` | running | — | running→send_authorized |
| C8 submit_delivery_result | 9000 | `POST .../result` `:555-611` | — | — | running→sent/verify_pending/blocked/failed |
| C9 consume_download_ticket | 9000 | `GET .../attachment` `:472-501` | — | 原子 UPDATE WHERE downloaded_at IS NULL | 写 downloaded_at |
| C10 reclaim_stale_leases | （无生产调用者） | `daily_report_delivery_service.py:614-648` | running/send_authorized | — | running→failed / send_authorized→verify_pending ★ DORMANT |
| C11 9000 历史只读查询 | 9000 | `GET /wechat-tasks`、`/{task_id}`、deliveries agent tasks/{task_id} | — | — | 无 |

**UNKNOWN CONSUMER = 0**。全仓 grep 确认：9000 无 APScheduler/Celery/background worker 消费 wechat_tasks；`background_tasks.add_task` 仅用于 ai_edit/replies return_visit/integrations outbox，均与 wechat_tasks 无关；`daily_report_scheduler.py` 注释明确"只生成报表，不创建 WechatTask"；无 startup recovery 扫描 pending task。`check_scheduler.py` 只对 `reply_checks` 表做 timeout，不碰 `wechat_tasks`；`wechat_auto_detect_scheduler.py` 只读单点 `active_check_id` 配置，不扫 wechat_tasks 队列。

---

## 7. State Machine

### 7.1 notify_sales（无 pending→running 转换）

```
pending ──(pasted=true, sent=false, verified=true)──→ pasted         [wechat_task_service.py:~440]
pending ──(sent=true, verified=true, mode=single_send)──→ sent        [~454]
pending ──(verified=false)──→ blocked [failure_stage=verified_false_blocked]
pending ──(partial_match)──→ blocked [partial_match_blocked]          [384]
pending ──(manual_review_required)──→ blocked                          [394]
pending ──(paste_only + sent=true)──→ blocked [task_mode_send_mismatch]
pending ──(success=false)──→ failed [failure_stage]                    [370]
pending ──(unhandled)──→ blocked [unhandled_result_combination]
```
- 写入者：`submit_wechat_task_result`（9000），由 19000 `POST /result` 触发。
- 事务：每分支独立 `db.commit()`（373/386/398/409/454/469）。
- ★ **无 pending→running**：19000 拉到 pending 后直接执行，回写时跳终态。执行期间 status 恒 pending。

### 7.2 detect_reply

```
pending ──(detected_status=replied)──→ completed                      [~710]
pending ──(detected_status=manual_review)──→ completed [manual_review]
pending ──(detected_status=pending 未命中)──→ pending（回退，pasted_at=检测时间）[736-748]
pending ──(detected_status=failed)──→ failed
pending ──(success=false)──→ failed
pending ──(verified=false / partial_match / manual_review_required)──→ blocked
pending ──(detect_count >= 30)──→ completed [max_detect_count_exceeded]
pending ──(关联 check 已非 pending)──→ completed [check_already_{status}]
pending ──(unknown detected_status)──→ blocked
```
- 写入者：`_submit_detect_reply_result` `wechat_task_service.py:614-764`。
- ★ `pending→pending` 回退：Agent 未检测到回复时，task 回退 pending 等下次重拉。

### 7.3 send_report_attachment（DORMANT，状态机存在但不运转）

```
pending ──(claim_delivery_task 原子 UPDATE WHERE status=pending)──→ running
running ──(authorize_send_intent gates pass)──→ send_authorized
running/send_authorized ──(submit_delivery_result fully verified)──→ sent
running ──(probe / 未 fully verified)──→ verify_pending
running ──(blocked)──→ blocked
running ──(else)──→ failed
running ──(reclaim_stale_leases lease 过期无 nonce)──→ failed ★ 无生产调用者
running/send_authorized ──(reclaim_stale_leases nonce 过期)──→ verify_pending ★ 无生产调用者
verify_pending/blocked/failed ──(retry_delivery 手动)──→ pending（新行 attempt 递增）★ 无生产调用者
```

---

## 8. Scheduler Model

- 9000 scheduler_runtime_model = `in_process_thread`（`RUNTIME_ENTRYPOINTS.md:40`）：全部 `threading.Thread(daemon=True)` + `time.sleep` 自实现循环，无 APScheduler，无 leader election。多副本部署会重复调度。
- **但**：与 wechat_tasks 消费相关的不是 9000 scheduler，而是 19000 的 `_runtime_poll_loop`（`local_agent_main.py:1591-1621`）：daemon 线程，按 `LOCAL_AGENT_TASK_POLL_INTERVAL_SECONDS`（默认 5s）周期调 `poll_once()` = `agent_poll_and_execute` + `agent_poll_and_detect`。
- **`poll_once()` 是同步阻塞调用**——内部 acquire `_wechat_task_lock` 执行整个微信自动化（可耗时数十秒到数分钟），期间 runtime_poll_loop 卡在 `poll_once()` 内，根本不触发下一轮，直到锁释放 + `time.sleep(interval)`。→ **单进程内不会发生"执行耗时 > interval 导致下一轮选到同一 task"**。

---

## 9. Local Agent / 19000 Contract

- **POLL**。19000 三个 poll 端点（`local_agent_main.py:1871/2246/2482`）。
- notify_sales/detect_reply：`GET /wechat-tasks/pending?task_type=...&limit=1`（`local_agent_main.py:1953`）→ 9000 `get_pending_wechat_tasks`。也支持指定 task_id：`GET /wechat-tasks/agent/{task_id}`（`:1921`）。
- **返回任务之前是否已形成 durable claim？notify_sales/detect_reply = 否**。9000 `GET /pending` 只纯 SELECT 返回，不修改 status、不开事务、无 FOR UPDATE。task 返回后仍为 pending，任何其他 Agent 仍可拉到。
  - 两个 Local Agent 实例 / 两次 poll 可以获得同一 task。这是 `NO_CLAIM` 的根本。
- send_report_attachment：19000 先 `GET .../pending` 拿 task_id，再 `POST .../claim` 原子认领。claim 返回前任务仍 pending（claim 调用才转 running），但 claim 是原子 CAS，并发只一者成功。**此路径有 durable claim**。

---

## 10. Current Claim Mechanism

**notify_sales / detect_reply = NO_CLAIM**（`wechat_task_service.py:100-132` 纯 SELECT；`wechat_tasks.py:99-119` 路由层仅 token 鉴权 + 商户隔离，无 status 翻转）。

无 `FOR UPDATE`（全仓 FOR UPDATE/with_for_update 仅 `lead_wechat_notify_eligibility_service.py:96` 对 SalesStaff 行加锁用于通知限频，与任务 claim 无关）。无 `RETURNING` 用于 claim（仅 `douyin_webhook_idempotency_service.py:32` webhook 占位，M02）。

单进程并发防护 = **PROCESS_LOCAL_GUARD**：`_wechat_task_lock`（`local_agent_main.py:139,1898-1902,2242`），`threading.Lock.acquire(blocking=False)`，从拉取到回写全程持有。同进程 runtime_poll_loop 在锁占用时 `agent_busy` 直接返回。**跨进程无防护**。

**send_report_attachment = ATOMIC_CLAIM**（`claim_delivery_task` `daily_report_delivery_service.py:433-469`：`db.query(WechatTask).filter(id==task_id, status==STATUS_PENDING).update({status:STATUS_RUNNING, ...}, synchronize_session=False)` + rowcount==0 → `ClaimConflictError`）。但整条链路 DORMANT（§5 P3 无生产调用者）。

**Claim Contract Classification 汇总**：

| Consumer Path | Classification |
|---|---|
| C1 notify_sales poll-and-execute | NO_CLAIM + PROCESS_LOCAL_GUARD |
| C2 detect_reply poll-and-detect | NO_CLAIM + PROCESS_LOCAL_GUARD |
| C3/C6 send_report_attachment claim | ATOMIC_CLAIM |
| C4 submit_wechat_task_result 回写 | NON_ATOMIC_STATUS_TRANSITION（无 CAS，后写覆盖先写） |
| C8 submit_delivery_result 回写 | NON_ATOMIC_STATUS_TRANSITION |
| C10 reclaim_stale_leases | UNKNOWN_REACHABLE（无生产调用者，DORMANT） |

```
UNKNOWN = 0
```

---

## 11. Current Lease Mechanism

**notify_sales / detect_reply = 不存在**。`wechat_task_service.py`/`wechat_tasks.py` 中 `lease/expires/heartbeat/locked_until/processing_since/claimed_at/worker_id/owner` 全空命中（附件专用 `download_ticket_expires_at`/`send_nonce_expires_at` 与 notify_sales/detect_reply 无关）。

- Heartbeat 不回写任务所有权：`_build_agent_heartbeat_payload`（`local_agent_main.py:488-499`）`current_task_id` 硬编码 None；`receive_agent_heartbeat`（`agent.py:23-27`）只更新 agent 状态快照，不写 wechat_tasks、不更新任何 claimed_at/lease_expires_at。
- processing timeout recovery = 不存在：无机制把卡在执行中的 wechat_task 重置回 pending（因为根本不会有 task 被标 running/processing——任务一直 pending 直到一次性写终态）。
- send_report_attachment 有 lease 语义（`execution_started_at` + `reclaim_stale_leases` 回收），但 `reclaim_stale_leases` 无生产调用者 → running/send_authorized 状态无自动回收。

**claim（§10）≠ lease（§11）≠ recovery timeout**——三者分开，本轮不混为一谈。

---

## 12. Retry Model

- **Manual retry**：`wechat_tasks` 路由无 retry/requeue/reset 端点（全仓 retry_task/requeue 仅作用于 AiAutoReplyRun/AiEditJob，非 WechatTask）。notify_sales failed 后无自动 requeue，人工"重试"= 重新走 `POST /lead-notifications/send-to-staff` 建全新 WechatTask（新 id），非回退旧 task status。→ **不存在 processing→pending 回退与在途 worker 冲突**。但 `detect_reply` 的 `pending→pending` 回退（`wechat_task_service.py:736-748`）有双写覆盖窗口：Agent A 回写设回 pending，Agent B 更早拉到同 task 在执行中，两者同时写 `submit_wechat_task_result`，无 CAS、无 affected rows、无版本号 → 后写覆盖先写。
- **Automatic retry**：仅 detect_reply 有 `_MAX_DETECT_COUNT=30`（`wechat_task_service.py:32,676,736-748`），attempt 计数存 `raw_result` JSON（`_get_detect_count` `:767-775`），**Agent 上报、非服务端原子自增**。notify_sales 无任何自动重试。
- **Stable attempt identity**：不存在。无 `attempt_count`/`attempt_id` 列，服务端无法区分同一 task 的第 N 次执行。每次回退 pending 再拉取，Agent 拿到同 task（同 id），但无 attempt_id/run_id 区分"第几次尝试"。

---

## 13. Crash Recovery

场景：worker 成功拉到 task → 执行副作用 → 进程崩溃 → status 永不到 completed。

- 由于服务端拉取不修改 status，**task 在 DB 始终为 pending**。
- Agent 崩溃后：DB task 仍 pending → 下次 `_runtime_poll_loop`（或外部触发再次 `poll-and-execute`）**再次拉到同一 pending task 并重新执行**。
- 这是一种"隐式重投"，但**无幂等保护**：若原 Agent 已粘贴/发送消息到微信、但崩溃在 `POST /result` 之前，下次重拉会**再次粘贴/发送同一条消息给同一销售**。
- 无 timeout reset（无 task 被标 running）、无 manual retry（无端点）。ISSUE-M04-003（任务永久停留 pending）/ ISSUE-M04-004（notify_sales failed 无自动 requeue）登记。

---

## 14. Manual Retry

见 §12。不存在 wechat_tasks 重试端点。失败建新 task。`detect_reply` pending→pending 回退的双写覆盖窗口是真实风险（但 detect_reply 是 read_only 无外部副作用，覆盖危害限于状态正确性）。

---

## 15. Automatic Retry

见 §12。仅 detect_reply `_MAX_DETECT_COUNT=30`，存 JSON，非原子自增，无稳定 attempt identity。notify_sales 无自动重试。

---

## 16. External Side Effects

| Task Type | External Side Effect | Idempotent? | Has External Receipt/ID? | Repeat Harm | 证据 |
|---|---|---|---|---|---|
| notify_sales (mode=single_send) | 剪贴板写入 + Ctrl+V 粘贴 + **Enter 发送** | 否 | 否（UIA SendKeys 无 message ID） | **重复发送真实微信消息给客户** | `local_agent_main.py:2202` → `input_writer.py:477` `uia.SendKeys("{Enter}")` |
| notify_sales (mode=paste_only) | Ctrl+V 粘贴文本到输入框（不回车） | 否 | 否 | 重复粘贴（用户看到多条相同文本在输入框，不自动发出） | `input_writer.py:387,423` |
| detect_reply (read_only) | 只读取微信消息列表（OCR/UIA） | 是（纯读） | N/A | 无 | `local_agent_main.py:1220-1383`（注释 :1234"安全约束：只读取，不写入，不粘贴，不发送"） |
| send_report_attachment (dry_run=true) | 下载附件 + 文件校验 + gate，不 CF_HDROP/Ctrl+V/Enter | 是（无真实发送） | N/A | 无 | `local_agent_main.py:640-783` |
| send_report_attachment (dry_run=false) | CF_HDROP 文件入剪贴板 + Ctrl+V + Enter 发送文件 | 否 | 否 | **重复发送真实文件给客户** | `file_attachment_sender.py:117-155` |

**活跃副作用面**：生产中实际可达的真实发送副作用 = **notify_sales single_send（Enter 发消息）**。detect_reply 是 read_only；send_report_attachment 链路 DORMANT（无生产者创建 task）。paste_only 不自动发出（危害低）。附件 dry_run 强制 true（`local_agent_main.py:2513,2521-2525`），dry_run=false blocked。

---

## 17. Side-Effect Idempotency

- 所有微信发送类动作经 Windows UIA `SendKeys`，fire-and-forget：`input_writer.py:423` `SendKeys("{Ctrl}v")`、`:477` `SendKeys("{Enter}")`、`file_attachment_sender.py:121/149`。
- **微信 UIA 不提供 external receipt / message client ID / 发送回执**。UIA SendKeys 无返回值确认消息是否真发出、是否重复。
- `task_id` 是唯一 dedup 键，但**只保护 status writeback（`submit_wechat_task_result` 按 task_id 找 task 改 status），不保护外部执行**：两个 Agent 同时拉到同一 pending task 各自执行 Enter 发送，回写时第二个覆盖 status，**两条微信消息已真实发出**。
- send_report_attachment 有 15s 单次 nonce（`authorize_send_intent` `daily_report_delivery_service.py:504-552`），但保护的是"Enter 前二次检查"，不保护"两 Agent 同时拉到同一 task"——后者已被原子 claim 解决。

```
EXACTLY_ONCE EXTERNAL SIDE EFFECT for WeChat send actions = IMPOSSIBLE
  微信外部系统无幂等接口，UIA 无发送回执，19000 无法知道消息是否已被另一 Agent 实例发送过。
  唯一有效防护 = Local Agent 单实例 + 运行锁（进程级，非分布式幂等）。
```

---

## 18. Transaction Boundaries

**notify_sales / detect_reply**：

```
1. 拉取 task        — 无事务（纯 SELECT，status 不变，task 保持 pending）   [wechat_task_service.py:115]
2. 外部执行          — 无 DB 事务保护（19000 UIA 自动化，可耗时数分钟，期间 task 仍 pending）
3. 回写结果          — db.commit() AFTER 外部执行                              [wechat_task_service.py:373/454/...]
```

→ **DB commit AFTER external execution。无 claim 事务 BEFORE 外部执行。** Agent 在外部执行后、回写前崩溃 → task 卡 pending → 被另一 Agent 重拉重发。

**send_report_attachment**：

```
1. claim            — db.commit() BEFORE 外部执行（原子 UPDATE pending→running）[daily_report_delivery_service.py:433-469]
2. 外部执行          — task 已 running，其他 Agent 不会拉到
3. 回写结果          — db.commit() AFTER                                       [submit_delivery_result :555-611]
4. 租约回收          — reclaim_stale_leases（DORMANT，无生产调用者）
```

外部副作用不可能真正放在数据库事务内——这是 §13 crash recovery 的根因窗口，准确描述如上。

---

## 19. Multi-Process / Multi-Instance

- **9000**：`docker-compose.dev.yml:125` + `Dockerfile.backend.dev:38` + `Dockerfile:54` 均 `uvicorn app.main:app --host 0.0.0.0 --port 9000`，**无 `--workers`**，默认单 worker。无 gunicorn（全仓零命中）。
- **19000**：`local_agent_main.py:2894-2897` `uvicorn.run` 无 workers；`local_agent_exe_entry.py:186-190` 启动前 `_port_is_available` 检查端口占用，占用则拒绝启动——**唯一单实例保障，基于端口独占，非 mutex/named pipe**。19000 不在任何 Docker compose（依赖宿主机 Windows 微信窗口/UIA/OCR）。

```
CURRENT_DEPLOYMENT = SINGLE_INSTANCE（9000 单 worker + 19000 单进程端口独占）
```

但代码层：

```
notify_sales / detect_reply MULTI_INSTANCE_SAFE = NO
  无 durable claim，task 执行期间 pending，多实例可同时拉同一 task 重复执行副作用
send_report_attachment MULTI_INSTANCE_SAFE = YES（但 DORMANT）
  原子 claim 保证只一 Agent 获得 task
```

单客户 1 个 Local Agent 不是正确性证明：进程重启 / scheduler overlap / HTTP retry / manual retry / server duplicate dispatch / Local Agent reconnect / 旧实例未退出 + 新实例启动 均需以技术 ownership 合同判断，不靠部署假设。

---

## 20. Race R1 — Two workers pick same pending task

```
T0  task=pending（notify_sales single_send）
T1  Agent A GET /pending → 拿到 task（status 仍 pending，无 claim）
T2  Agent B GET /pending → 拿到同一 task（status 仍 pending，无 claim）
T3  A 执行 UIA：Ctrl+V + Enter → 消息1 已发
T4  B 执行 UIA：Ctrl+V + Enter → 消息2 已发（重复！）
T5  A POST /result → task.status=sent
T6  B POST /result → task.status=sent（覆盖，无 CAS）
```

```
REACHABILITY = REACHABLE（条件：≥2 个 19000 实例 / 2 台机器用同商户 token）
EVIDENCE = CODE_VERIFIED + ROUTE_VERIFIED
  get_pending_wechat_tasks 纯 SELECT [wechat_task_service.py:115]
  submit_wechat_task_result 无 CAS [wechat_task_service.py:370-454]
  跨进程 _wechat_task_lock 无效 [local_agent_main.py:139]
RUNTIME_EVIDENCE = E2E_VERIFIED（Gate 2 Concurrent Poll：两客户端同时 GET pending → A1=1 A2=1 same=True）
  但注意：Gate 2 是 Docker 环境两 HTTP 客户端模拟并发 GET，非真实两 19000 进程
  → 证明"服务端无 lease 时并发 GET 返回同一 task"，不直接证明生产重复发送
  → 生产重复发送需"≥2 真实 19000 实例"前提，当前单实例部署下未发生
SEVERITY（见 §26）
```

---

## 21. Race R2 — Scheduler overlap

```
单进程内：poll_once() 同步阻塞 + _wechat_task_lock → 下一轮不启动 → NOT REACHABLE
跨进程 / 多触发源（runtime_poll_loop + 手动 POST /agent/tasks/poll-and-execute + 外部触发）：
  各自 _wechat_task_lock.acquire(blocking=False)：同进程 agent_busy，跨进程各自独立 → 同 R1
```

```
REACHABILITY = NOT REACHABLE（单进程内）
REACHABILITY = REACHABLE（跨进程，同 R1 条件）
EVIDENCE = CODE_VERIFIED [local_agent_main.py:1591-1621 poll_once 同步阻塞]
```

---

## 22. Race R3 — Crash after side effect

```
T0  Agent A GET /pending → task（status pending）
T1  A 执行 Enter → 消息已发
T2  A 崩溃（POST /result 之前）
T3  task 仍 pending（无 claim，无 running 标记，无 timeout reset）
T4  下次 poll / 新 Agent 重拉同一 pending task
T5  再次执行 Enter → 重复发送
```

```
REACHABILITY = REACHABLE（条件：Agent 崩溃在副作用后、回写前）
EVIDENCE = CODE_VERIFIED
  task 执行期间恒 pending [wechat_task_service.py:115 + 370-454 无 running]
  无 timeout recovery（无 task 被标 running）
  无幂等键保护外部执行（§17）
RUNTIME_EVIDENCE = HYPOTHESIS（无生产崩溃 incident 记录）
SEVERITY（见 §26）
```

---

## 23. Race R4 — Retry while old worker still alive

```
notify_sales 无 retry 端点 → 不存在 processing→pending 回退 → NOT REACHABLE（无此路径）
detect_reply pending→pending 回退：Agent A 回写设回 pending，Agent B 早一刻已拉到在执行 →
  两者同时 submit，无 CAS → 后写覆盖先写
  但 detect_reply 是 read_only 无外部副作用 → 危害限于状态正确性
```

```
REACHABILITY = REACHABLE（detect_reply 双写覆盖窗口）
EVIDENCE = CODE_VERIFIED [wechat_task_service.py:736-748 + 302-474 无 status 检查]
SEVERITY = LOW（read_only 无外部副作用，仅状态正确性）
```

---

## 24. Race R5 — Local Agent reconnect / duplicate poll

```
旧 19000 实例未退出 + 新实例启动 → 端口占用检查会拒绝新实例（_port_is_available）
  → 同端口不会两实例；但不同端口 / 不同机器可两实例
两实例各自 _runtime_poll_loop 独立轮询 → 同 R1
HTTP retry：19000 GET /pending 重试若 9000 已返回 task 但 19000 未收到响应 → 重试再 GET
  → 可能拿到同一 task 或下一条（取决于 9000 是否已标记，但 9000 不标记）→ 可能同一 task
```

```
REACHABILITY = REACHABLE（条件：同端口被拒绝故需不同端口/不同机器两实例，或 HTTP retry 场景）
EVIDENCE = CODE_VERIFIED [local_agent_exe_entry.py:186-190 端口独占；无服务端 claim]
SEVERITY（见 §26，归 R1 同类）
```

---

## 25. Findings

### P2-F1：notify_sales / detect_reply 服务端无 atomic claim（NO_CLAIM）

- 事实：`get_pending_wechat_tasks` 纯 SELECT（`wechat_task_service.py:100-132`）；无 pending→running 转换（`running` 状态从未使用）；无 FOR UPDATE / RETURNING / claim_token / worker_id。
- 跨进程/多 Agent 可同时拉同一 pending task。
- 证据等级：CODE_VERIFIED + ROUTE_VERIFIED + SCHEMA_VERIFIED（无 claim 字段）+ E2E_VERIFIED（Gate 2 Concurrent Poll 证服务端无 lease 时并发 GET 返回同一 task，但为 HTTP 客户端模拟非真实两 19000）。
- 与同仓对比：M01 AiAutoReplyRun（attempt_count+lease_owner+manual_retry）、M06 AiEditJob（attempt_count+execution_token_hash+retry_job）、ReturnVisitRun（attempt_count+lease_expires_at+reclaim_stale_processing）均有 claim/lease/retry 三件套；WechatTask 是同仓少数完全缺失者。

### P2-F2：无 lease / 无 crash recovery timeout

- 事实：无 lease_expires_at/heartbeat 回写任务所有权（`current_task_id` 硬编码 None）；无 processing timeout recovery（无 task 被标 running）；task 执行期间恒 pending，崩溃后隐式重拉重发无幂等保护。
- 证据等级：CODE_VERIFIED + SCHEMA_VERIFIED。
- 已知登记：ISSUE-M04-003（任务永久停留 pending）/ ISSUE-M04-004（notify_sales failed 无自动 requeue）。

### P2-F3：外部副作用重复发送不可幂等

- 事实：notify_sales single_send 的 Enter 发送 + send_report_attachment 的 CF_HDROP+Enter 均为 UIA fire-and-forget，无 external receipt/message ID；task_id 只保护 status writeback 不保护外部执行；两 Agent 同时拉到同一 pending task 各自执行 → 重复发送真实微信消息。
- 证据等级：CODE_VERIFIED。
- 结论：EXACTLY_ONCE EXTERNAL SIDE EFFECT 对微信发送动作不可能（外部系统无幂等接口）。

### P2-F4：detect_reply pending→pending 回退双写覆盖（NON_ATOMIC_STATUS_TRANSITION）

- 事实：`submit_wechat_task_result` 不检查当前 status、无 CAS/affected rows/版本号；detect_reply 回退 pending 时两 Agent 同时回写 → 后写覆盖先写。
- 证据等级：CODE_VERIFIED。
- 危害：detect_reply read_only 无外部副作用，危害限于状态正确性（detect_count 可能丢失/覆盖）。

### P2-F5：send_report_attachment 已有正确 ATOMIC_CLAIM 但整条链路 DORMANT

- 事实：`claim_delivery_task` 原子 UPDATE WHERE status=pending + rowcount + ClaimConflictError（`daily_report_delivery_service.py:433-469`）；但 `retry_delivery`（唯一创建该 task 的函数）生产无调用者，`reclaim_stale_leases` 也无生产调用者 → 链路 DORMANT，状态机存在但不运转。
- 证据等级：CODE_VERIFIED。
- 含义：**P2 风险不覆盖 send_report_attachment 路径**（已有 claim，且 dormant）。未来若启用该链路，claim 机制已就绪，但 lease 回收（reclaim_stale_leases）需接生产调度器。

### P2-F6：Schema/ORM merchant_id 漂移（设计输入，非执行风险）

- 事实：DB 层有 `merchant_id`/`tenant_id` 列 + `idx_wechat_tasks_merchant_status_created` 索引，ORM 未映射、恒 NULL，商户隔离靠 JOIN。
- 证据等级：SCHEMA_VERIFIED + CODE_VERIFIED。
- 含义：未来 claim 设计若需 `WHERE merchant_id=... AND status='pending'` 索引，DB 层已具备，但 ORM 需补映射 + 写路径需填值。本轮不提 migration 结论。

---

## 26. Severity

| Finding | Likelihood | Impact | Runtime Reachability | Data/External Side Effect | Recovery Difficulty | Severity |
|---|---|---|---|---|---|---|
| P2-F1 NO_CLAIM | 中（需≥2 Agent 实例/2 机器同商户） | 高（重复发送真实微信消息） | 单实例部署下未发生；多实例/重启/HTTP retry 下可达 | 真实微信消息重复 | 无法撤回（微信无撤回 API 对已发） | **HIGH** |
| P2-F2 无 lease/crash recovery | 中（Agent 崩溃在副作用后回写前） | 高（重拉重发） | 崩溃场景可达 | 真实微信消息重复 | 无法撤回 | **HIGH** |
| P2-F3 副作用不可幂等 | —（结构性事实） | 高 | 同 F1/F2 | 真实微信消息/文件重复 | 无法撤回 | **HIGH**（与 F1/F2 共因，非独立修复项） |
| P2-F4 detect_reply 双写覆盖 | 低（需两 Agent 同 task 回退窗口） | 低（状态正确性） | 可达但 read_only | 无外部副作用 | 可人工补状态 | **LOW** |
| P2-F5 send_report_attachment DORMANT | —（不运转） | — | 不可达（无生产者） | — | — | **FUTURE**（链路启用时 claim 已就绪，需接 reclaim 调度） |
| P2-F6 merchant_id 漂移 | —（设计输入） | — | — | — | — | **FUTURE**（claim 设计依赖） |

**活跃 HIGH 风险 = P2-F1 + P2-F2 + P2-F3（共因：notify_sales NO_CLAIM + 无 lease + 副作用不可幂等）**，集中在 `notify_sales single_send` 路径。P2-F3 是 F1/F2 的结构性根因（微信外部系统无幂等接口），非独立修复项。

---

## 27. P1 / P2 Boundary

```
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED
  → 只保证：同 Business Event Identity → compute billing 不重复
  ≠ M04 task execution exactly-once
  ≠ 外部微信副作用不重复

即使重复 M04 task 导致两次 AI 调用：
  P1 保证 wechat_task:{task.id}:result_usage 幂等键下不重复计费
  但外部微信消息仍可能重复发送（P2 范畴）
```

不重新打开 P1。P2 不依赖 P1 解决。

---

## 28. Schema / Index Constraints

- `uk_wechat_tasks_delivery_attempt` UNIQUE(report_delivery_id, delivery_attempt_no) — 仅 send_report_attachment。
- `idx_wechat_tasks_merchant_status_created`(merchant_id, status, created_at) — DB 层存在，但 ORM 未映射 merchant_id（§4 漂移）。
- 未来 claim 设计可能需要 `status + next_retry_at` 或 `(merchant_id, status, id)` 复合索引——本轮不提 migration 结论，仅记录现状：DB 层 merchant_id 索引已存在但列未填值。

---

## 29. Deployment Assumptions

- 当前部署：9000 单 uvicorn worker（无 --workers），19000 单进程 + 端口独占（不同端口/不同机器可两实例）。
- 单实例部署下 R1/R2 未发生；但代码层 MULTI_INSTANCE_SAFE=NO（notify_sales）。
- scheduler=in_process_thread，无 leader election——多副本部署会重复调度（当前仅 daily_report_scheduler 等生成报表，不消费 wechat_tasks）。
- 单客户 1 个 Local Agent 不是正确性证明（重启/HTTP retry/旧实例未退出+新实例启动需以 ownership 合同判断）。

---

## 30. Open Questions

1. 生产是否计划部署多 19000 实例 / 多机器？（决定 R1 是否从"理论"转"生产可达"）
2. notify_sales single_send 是否是生产唯一活跃发送路径？paste_only 是否仍生产使用？（影响修复优先级）
3. detect_reply `_MAX_DETECT_COUNT=30` 存 JSON 非 atomic 自增——是否需服务端原子 attempt？（属 P2-F4 范畴，低优先）
4. 19000 HTTP retry 策略：GET /pending 重试时是否会重复拿同一 task？（需 19000 客户端代码细化，本轮未深挖）
5. send_report_attachment 链路是否有启用计划？（决定 P2-F5 是否转活跃）

---

## 31. Candidate Design Families — NOT APPROVED

仅列可能方向，**均 NOT APPROVED**，本轮不选实现：

- **DF-A：notify_sales 加服务端原子 claim**（复用 `claim_delivery_task` 同款 `UPDATE WHERE status=pending` + rowcount + ClaimConflictError），复用仓库内已验证模式（ReturnVisitRun/AiEditJob）。最小改动：拉取端点后插 claim 步骤。
- **DF-B：lease + reclaim**（`execution_started_at` + `lease_expires_at` + 定时 `reclaim_stale_leases` 接生产调度器），复用 send_report_attachment 已有字段语义。
- **DF-C：at-most-one active executor + best-effort crash recovery + manual uncertainty state**（承认 EXACTLY_ONCE 对微信不可能，crash 后进"不确定态"人工确认而非自动重发）。
- **DF-D：19000 单实例强约束 + 启动互斥**（named pipe / 文件锁替代端口独占，强化现有单实例保障）。
- **DF-E：复用同仓 ReturnVisitRun 的 claim/lease/attempt/reclaim 四件套迁移到 WechatTask**（最大复用，但改动面较大）。

未来设计窗口须独立审批后才选型。

---

## 32. Recommended Next Design Scope

下一设计窗口应聚焦：

```
Current execution model:    notify_sales POLL + NO_CLAIM，task 执行期间恒 pending，回写才跳终态
Current ownership mechanism: 仅进程内 _wechat_task_lock（PROCESS_LOCAL_GUARD），跨进程无防护
Current recovery mechanism:  无 lease、无 timeout reset、无 manual retry 端点；崩溃隐式重拉无幂等
Current side-effect semantics: UIA fire-and-forget，无 external receipt，EXACTLY_ONCE 不可能
Confirmed races:             R1（两 Agent 同 task）、R3（crash 后重发）REACHABLE
Non-races:                   R2 单进程内 NOT REACHABLE（poll_once 同步阻塞）；R4 仅 detect_reply 低危
Deployment assumptions:      单实例部署，代码层 MULTI_INSTANCE_SAFE=NO（notify_sales）
Schema constraints:          无 claim/lease 字段（notify_sales/detect_reply）；DB merchant_id 索引存在但 ORM 未映射
External API limitations:    微信 UIA 无幂等接口、无发送回执
```

设计须先回答 Open Questions（§30），尤其 Q1（多实例计划）决定 R1 严重度定级。设计应复用仓库内已验证 claim/lease 模式（ReturnVisitRun/AiEditJob/claim_delivery_task），承认 EXACTLY_ONCE 外部副作用不可能，采用 at-most-one active executor + 不确定态人工确认，而非虚假宣称 exactly-once。

---

## 33. Verdict

```
P2_RISK_CONFIRMED_DESIGN_REQUIRED
```

理由：

- P2-F1（NO_CLAIM）+ P2-F2（无 lease/crash recovery）经 CODE_VERIFIED + SCHEMA_VERIFIED + ROUTE_VERIFIED 确认；Gate 2 E2E 证服务端无 lease 时并发 GET 返回同一 task。
- 活跃风险集中在 `notify_sales single_send`（真实微信消息发送），EXTERNAL SIDE EFFECT 不可幂等（P2-F3）。
- 与同仓其他任务表对比，WechatTask 是少数完全缺失 claim/lease/attempt 机制者，仓库内已有可复用模式。
- 当前单实例部署下 R1/R3 未发生（runtime 未验证重复发送 incident），但代码层 REACHABLE——**不因单实例部署就判 NOT_REPRODUCED**。
- send_report_attachment 路径已有 ATOMIC_CLAIM 且 DORMANT，不属 P2 活跃风险。

不选 BLOCKED_BY_MISSING_RUNTIME_FACTS：核心 claim/lease 缺失已由代码事实确证，不依赖运行时 incident。不选 P2_RISK_NOT_REPRODUCED：单实例部署是缓解非根因消除，代码层 race 可达。

---

## 34. Governance 状态

```
P1 COMPUTE-IDEMPOTENCY-001 = CLOSED（保持不动）

P2 M04 CLAIM/LEASE = EXPLORATION_COMPLETE / DESIGN_PENDING
  不得标 RESOLVED / IMPLEMENTED
  下一独立设计窗口须审批后才选型实施
```

RB-10 = NOT AUTHORIZED（保持）。7 REQUEST_RECOVERY_GAP = OUT_OF_P1（保持）。F-2 = DORMANT（保持）。

---

## 35. Git Discipline

- P1 closure commit `1d7f1f5` 已按 Stage A 授权提交（未 push）。
- **P2 exploration candidate：DO NOT COMMIT / DO NOT PUSH**——本报告交下一独立探索审批/设计确认。

---

## 36. STOP

探索报告完成。停止。不得自行：修改 M04 业务代码 / 新增 claim 字段 / 新增 lease 字段 / 新增 migration / 修改 Local Agent 协议 / 改 retry 状态机 / 加 Redis lock / 加 SKIP LOCKED / 开始实施 / RB-10 / push。

---

## 附录：证据来源（file:line）

- `app/models.py:290-336` — WechatTask 模型（无 claim/lease 字段，仅附件子类型有 token_hash；status 注释列 running 但从未使用）
- `app/services/wechat_task_service.py:100-132` — get_pending_wechat_tasks（纯 SELECT 无 FOR UPDATE）
- `app/services/wechat_task_service.py:302-474` — submit_wechat_task_result（无 CAS、无 status 当前值检查、直接赋值）
- `app/services/wechat_task_service.py:614-764` — detect_reply 专用回写（pending→pending 回退、_MAX_DETECT_COUNT=30）
- `app/services/wechat_task_service.py:31-32,767-775` — _MAX_DETECT_COUNT + _get_detect_count（存 raw_result JSON）
- `app/routers/wechat_tasks.py:99-119,159-205` — pending 拉取 + result 回写路由（仅 token 鉴权 + 商户隔离）
- `app/routers/wechat_tasks.py:35-48` — create_wechat_task_disabled（永久 410）
- `app/routers/agent.py:23-27` — heartbeat 接收（不回写任务所有权）
- `app/routers/lead_notification_actions.py:42-83,127,137` — notify_sales 手动派单生产者 + 前置去重判定
- `app/services/daily_report_delivery_service.py:388-469` — list_pending_delivery_tasks + claim_delivery_task（原子 CAS，send_report_attachment 专用）
- `app/services/daily_report_delivery_service.py:504-552,555-611,614-648` — authorize_send_intent + submit_delivery_result + reclaim_stale_leases（后者无生产调用者）
- `app/services/daily_report_delivery_service.py:212,240-262` — retry_delivery（无生产调用者，send_report_attachment DORMANT）
- `app/local_agent_main.py:139,1898-1902,2242` — _wechat_task_lock（PROCESS_LOCAL_GUARD）
- `app/local_agent_main.py:488-499` — heartbeat payload current_task_id=None
- `app/local_agent_main.py:1559-1621` — _runtime_poll_loop（poll_once 同步阻塞，单进程不重入）
- `app/local_agent_main.py:1871,1921,1953,2246,2482` — 三个 poll 端点
- `app/local_agent_main.py:2513,2521-2525` — send_report_attachment dry_run 强制 true
- `app/local_agent_main.py:2654-2657` — _default_runtime_poll_once
- `app/local_agent_main.py:2894-2897` — 19000 uvicorn 单进程
- `app/local_agent_exe_entry.py:186-190` — _port_is_available（端口独占单实例保障）
- `app/wechat_ui/input_writer.py:387,423,477` — UIA SendKeys fire-and-forget
- `app/wechat_ui/file_attachment_sender.py:117-155` — CF_HDROP + Enter 发送文件
- `app/scheduler/check_scheduler.py` — 只处理 reply_checks timeout，不碰 wechat_tasks
- `app/scheduler/wechat_auto_detect_scheduler.py` — 单点 active_check_id，不扫 wechat_tasks
- `app/scheduler/daily_report_scheduler.py` — 注释明确不创建 WechatTask
- `docker-compose.dev.yml:125` / `Dockerfile.backend.dev:38` / `Dockerfile:54` — 9000 单 uvicorn 无 --workers
- `migrations/postgres/auto_wechat/versions/0003_create_leads_tasks_core_tables.py:138-139` — DB merchant_id/tenant_id 列 + 索引（ORM 未映射）
- `docs/modules/M04-wechat-assistant/{README,CURRENT_FLOW,DATA_MODEL,RUNTIME_DEPENDENCIES,ACCEPTANCE,ISSUES}.md` — M04 冻结基线（Gate 2 E2E 证据在 ACCEPTANCE.md:126 / ISSUES.md:7-14）
- `docs/architecture/CROSS_MODULE_RISK_REGISTER.md:14,93,97` — HIGH-02 / ISSUE-M04-001 冻结定性
