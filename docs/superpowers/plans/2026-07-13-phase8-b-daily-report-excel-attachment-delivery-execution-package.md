# Phase 8-B Excel 附件真实分发执行计划

> **文档状态（2026-07-14 审查）：部分执行后冻结的追溯执行包，不能直接恢复执行。** Phase 8-B 已从制定时的 `NOT_STARTED` 进入 `PARTIAL_BLOCKED_DEFERRED`：投递服务、状态机和灰度门禁已落地，Qt UIA 未暴露可靠文件气泡控件，真机验证转 `verify_pending` 人工审计。未勾选项不是当前进度；恢复任何真实发送任务前必须重新审批。当前项目事实以 `docs/ai/05_PROJECT_CONTEXT.md` 为准。
>
> **执行窗口必读：** 实施时必须使用 `subagent-driven-development`（推荐）或 `executing-plans`，逐任务执行并在检查点暂停。本文步骤使用复选框跟踪。

**目标：** 按 `SalesStaff` 的 4 个报表开关，把 Phase 8-A 生成的 Excel 通过 Local Agent 真实发送给对应销售，并以可验证的微信文件消息作为成功依据。

**架构：** `DailyReportJob` 继续只负责生成；新增 `DailyReportDelivery` 负责某份报表到某名销售的幂等投递。`WechatTask(task_type=send_report_attachment)` 仅承载一次执行尝试，不保存服务器路径。Local Agent 原子 claim 后通过双令牌头下载钉住版本的文件，校验后用 Windows `CF_HDROP` 粘贴；发送前二次授权，发送后必须识别新增的本人文件气泡才能回写 `sent`。

**技术栈：** FastAPI、SQLAlchemy、SQLite、PostgreSQL/Alembic、React/TypeScript、Windows ctypes、微信 UI Automation、pytest。

---

## 0. 阶段冻结

### 0.1 固定起点

```text
Phase 8-A：DONE
sample_alignment=VERIFIED（甲方于 2026-07-13 确认 6 份虚构视觉样本）
Phase 8-B（计划制定时）：NOT_STARTED
阶段代码起点：ff60d4b9ef5c3144dd3d944565442973d0f82052
```

执行窗口开始前运行：

```powershell
git rev-parse HEAD
git merge-base --is-ancestor dfc35d6 HEAD
git status --short
```

现有用户残留不得清理、提交或回滚。

### 0.2 首次真机硬停止门禁

以下六项必须由审批窗口写入非版本控制验收记录。任一缺失，允许完成 Task 1-7 的代码和无发送验证，但 **禁止执行 Task 8，阶段状态必须为 `BLOCKED`**：

1. 专用测试联系人：不是销售、客户或生产群；昵称已实测可得到 `verified=true`。
2. 专用测试微信及所在测试电脑；不使用开发主机微信冒充结果。
3. 无敏感虚构 Excel；文件名含“虚构视觉样本”。
4. Windows 完整版本和位数。
5. 微信桌面版完整版本号。
6. 成功信号可行：该微信版本 UIA 控件树可读取新增、本人侧、文件名精确匹配的文件消息。

首测只允许专用联系人。销售侧确认只用于后续受控验收，不能替代系统成功证据。

### 0.3 允许范围

```text
app/models.py
app/schemas.py
app/config.py
app/main.py
app/services/daily_report_delivery_service.py（新建）
app/services/daily_report_job_service.py
app/services/wechat_task_service.py
app/routers/daily_report_deliveries.py（新建）
app/local_agent_main.py
app/wechat_ui/file_attachment_sender.py（新建）
app/wechat_ui/file_message_verifier.py（新建）
app/wechat_ui/clipboard_utils.py
app/scheduler/daily_report_scheduler.py
migrations/versions/0029_daily_report_deliveries.sql（新建）
migrations/postgres/auto_wechat/versions/0010_daily_report_deliveries.py（新建）
.env.development.example / .env.lan.example / .env.production.example
frontend/src/api/dailyReports.ts
frontend/src/api/types.ts
frontend/src/features/wechat-assistant/pages/DailyReports.tsx
frontend/scripts/check-phase8b-report-delivery-contract.mjs（新建）
scripts/smoke_phase8b_postgres_delivery.py（新建）
scripts/smoke_phase8b_real_wechat_attachment.py（新建）
对应专项测试
```

若需修改 `input_writer.py`、`contact_searcher.py`、Phase 9-13、抖音发送链路或其他迁移，必须停止并重新审批。

### 0.4 禁止事项

- 不把附件伪装成 `notify_sales` 文本任务。
- 不让 9000 直接操作微信；只允许客户电脑 Local Agent 操作本机微信。
- 不向前端返回 storage key、绝对路径、Local Agent token、下载票据、执行 token 或发送 nonce。
- token 不进 URL query、文件名、日志或 `raw_result`。
- 下载、剪贴板、粘贴或按 Enter 成功均不能单独证明 `sent`。
- 不绕过前台焦点、联系人验证、人工复核、紧急停止、限频或幂等。
- 不读取微信数据库，不注入 DLL，不逆向微信协议。
- 不保存截图作为发送证据；只保存 UIA 最小结构化摘要。
- 不发送 caption。当前只发固定服务端文件名的 Excel；未来增加文本必须另审并走违禁词服务。
- 不向真实销售或客户做首测。

### 0.5 默认关闭和灰度

```text
DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED=false
DAILY_REPORT_ATTACHMENT_ALLOW_FULL_ROLLOUT=false
DAILY_REPORT_ATTACHMENT_STAFF_ALLOWLIST_IDS=
DAILY_REPORT_ATTACHMENT_MAX_BYTES=20971520
DAILY_REPORT_ATTACHMENT_DOWNLOAD_TTL_SECONDS=120
DAILY_REPORT_ATTACHMENT_SEND_AUTH_TTL_SECONDS=15
DAILY_REPORT_ATTACHMENT_EXECUTION_LEASE_SECONDS=300
LOCAL_AGENT_ATTACHMENT_ALLOW_INSECURE_PRIVATE_HTTP=false
```

总开关关闭时只创建 `held` 投递，不创建可执行任务。总开关开启但全量关闭时，仅 allowlist 销售进入 `pending`。production 禁止 insecure HTTP；LAN 首测若显式开启，只允许 loopback 或 RFC1918 私网 host。

---

## 1. 固定设计

### 1.1 实体关系

```text
DailyReportJob 1 ── N DailyReportDelivery 1 ── N WechatTask
                      每个接收销售唯一        每次重试一个 attempt
```

当前 `DailyReportJob` 重生成会切换当前文件并删除旧文件，因此 delivery 必须快照并钉住：

```text
artifact_storage_key（仅 9000 内部）
artifact_file_name
artifact_sha256
artifact_size_bytes
```

WechatTask 只保存 delivery 关联、attempt、令牌 hash 和状态。

### 1.2 状态机

```text
held -> pending -> running -> send_authorized -> sent
  |        |          |              |
  +-> blocked          +-> failed     +-> verify_pending
  +-> cancelled
```

- `verify_pending` 表示已触发发送但未能可靠验证，禁止自动重试。
- `failed/blocked` 显式重试创建新 attempt。
- `verify_pending` 重试必须人工确认未收到并传 `confirm_not_sent=true`。
- `sent/cancelled` 是终态。
- `running` 租约过期且从未签发 send nonce：可回收为 failed 后人工重试。
- `send_authorized` 租约过期或 Agent 失联：保守转为 verify_pending，不能假设 Enter 未发生。
- 已 sent 的 delivery 不因 job 重生成而自动重发；仍钉住实际发送版本。页面标记“报表已有新版本”，重复发送需另开显式审批，不复用 retry 绕过幂等。

### 1.3 `sent` 定义

必须同时满足：当前 claim/attempt；单次票据已消费；本地 hash/size/name/MIME 正确；联系人 verified；粘贴前和 Enter 前焦点正确；紧急停止关闭；9000 `send-intent` 二次检查通过；Enter 后出现相对 baseline 新增的 sender=self 且文件名精确匹配的文件气泡。

---

## Task 0：冻结真机环境

**修改文件：无。**

- [ ] 记录 0.2 六项实际值，不把联系人昵称或 token 写入 Git。
- [ ] 用 `openpyxl` 只读扫描测试 Excel 的可见/隐藏表、批注、超链接、文档属性和外部链接；不得含 11 位手机号、wxid、真实名称、本机路径、宏或外部连接。
- [ ] 任一项未满足：禁止 Task 8，回传 `BLOCKED`。

---

## Task 1：数据库合同红灯

**Files:**

- Create: `tests/test_phase8b_delivery_schema.py`

- [ ] 写 ORM 合同：`DailyReportDelivery`、`uk_daily_report_deliveries_job_staff`、artifact 快照、状态/attempt；WechatTask delivery/令牌 hash、attempt 文件元数据快照和 `uk_wechat_tasks_delivery_attempt`。
- [ ] 写 SQLite 0029、PG 0010 合同：FK、约束、索引、PG TIMESTAMPTZ/BIGINT，downgrade 不删旧业务行。
- [ ] 运行红灯：

```powershell
python -m pytest tests/test_phase8b_delivery_schema.py tests/test_phase8_daily_report_schema.py -v
```

Expected：8-B 新断言失败，8-A 原断言通过。

- [ ] 提交：

```powershell
git add tests/test_phase8b_delivery_schema.py
git commit -m "测试：冻结日报附件投递数据合同"
```

---

## Task 2：迁移与 ORM

**Files:**

- Modify: `app/models.py`
- Create: `migrations/versions/0029_daily_report_deliveries.sql`
- Create: `migrations/postgres/auto_wechat/versions/0010_daily_report_deliveries.py`
- Modify: `tests/test_phase8b_delivery_schema.py`

- [ ] 新增 `DailyReportDelivery`：

```text
id, merchant_id, report_job_id, receiver_staff_id
status(default held), artifact_storage_key, artifact_file_name
artifact_sha256, artifact_size_bytes, attempt_count
last_failure_stage, delivered_at, created_at, updated_at
```

约束：`uk_daily_report_deliveries_job_staff(report_job_id, receiver_staff_id)`、merchant/status 与 staff/status 索引、size > 0。

- [ ] 扩展 `WechatTask`：

```text
report_delivery_id, delivery_attempt_no
execution_token_hash, execution_started_at
download_ticket_hash, download_ticket_expires_at, downloaded_at
send_nonce_hash, send_nonce_expires_at, send_authorized_at
attachment_verified_at
attachment_file_name
attachment_sha256
attachment_size_bytes
```

所有令牌仅存 SHA-256。WechatTask 不存 storage key；attempt 文件名/hash/size 用于保留每次实际发送证据，且必须与 claim 时 delivery 快照一致。

- [ ] SQLite 0029 必须事务内重建 `wechat_tasks`，不能用普通 `ALTER TABLE` 伪造 FK。重建前后守卫至少比较总行数、`max(id)`、按全部旧列分组的双向多重集差异；守卫失败整体 rollback 且不登记 0029。重建后恢复全部旧索引、旧 FK 和新增约束。PG 0010 使用正常 `ALTER TABLE`。

- [ ] 在仓库内临时 SQLite 副本演练，禁止操作 `data/auto_wechat.db`：

```powershell
python -m pytest tests/test_phase8b_delivery_schema.py tests/test_db_migration_runner.py -v
```

- [ ] 提交：

```powershell
git add app/models.py migrations/versions/0029_daily_report_deliveries.sql migrations/postgres/auto_wechat/versions/0010_daily_report_deliveries.py tests/test_phase8b_delivery_schema.py
git commit -m "功能：增加日报附件投递数据模型"
```

---

## Task 3：投递服务、灰度与 artifact 钉住

**Files:**

- Create: `app/services/daily_report_delivery_service.py`
- Modify: `app/services/daily_report_job_service.py`
- Modify: `app/scheduler/daily_report_scheduler.py`
- Modify: `app/config.py`
- Modify: `.env.development.example`, `.env.lan.example`, `.env.production.example`
- Create: `tests/test_daily_report_delivery_service.py`
- Modify: `tests/test_daily_report_scheduler.py`, `tests/test_daily_reports_api.py`

- [ ] 红灯覆盖：仅 generated/partial+artifact 可投递；4 个 report_type 对应 4 个 staff 开关；同商户 active 销售；job/staff 并发唯一；总开关/allowlist；昵称缺失 blocked；活跃投递阻断重生成；held 随重生成刷新；失败重试显式刷新；sent 不重发并标记 artifact outdated；被引用 artifact 不删除；投递失败不回滚报表；并发 retry 通过锁 delivery 后原子递增 attempt，只创建一个新 WechatTask。

- [ ] 固定接口：

```python
def ensure_deliveries_for_job(db, *, job_id: int) -> dict: ...
def reconcile_job_deliveries(db, *, merchant_id: str, job_id: int) -> dict: ...
def retry_delivery(db, *, merchant_id: str, delivery_id: int, confirm_not_sent: bool): ...
def cancel_delivery(db, *, merchant_id: str, delivery_id: int): ...
def artifact_is_pinned(db, *, storage_key: str) -> bool: ...
```

- [ ] `generate_one()` finalize 后用独立短事务 ensure；失败不改变成功报表。删除旧 artifact 前检查 pin。活跃 delivery 时 `regenerate_job()` 返回 `DAILY_REPORT_DELIVERY_ACTIVE`。
- [ ] 调度器成功生成后 reconcile；不启动发送线程，单商户投递失败不阻断其他商户。
- [ ] 运行并提交：

```powershell
python -m pytest tests/test_daily_report_delivery_service.py tests/test_daily_report_scheduler.py tests/test_daily_reports_api.py -v
git add app/services/daily_report_delivery_service.py app/services/daily_report_job_service.py app/scheduler/daily_report_scheduler.py app/config.py .env.development.example .env.lan.example .env.production.example tests/test_daily_report_delivery_service.py tests/test_daily_report_scheduler.py tests/test_daily_reports_api.py
git commit -m "功能：增加日报附件投递与灰度门禁"
```

---

## Task 4：9000 Local Agent 附件协议

**Files:**

- Create: `app/routers/daily_report_deliveries.py`
- Modify: `app/schemas.py`, `app/main.py`, `app/services/daily_report_delivery_service.py`
- Create: `tests/test_daily_report_delivery_agent_api.py`

- [ ] 固定端点：

```text
GET  /daily-report-deliveries/agent/pending
GET  /daily-report-deliveries/agent/tasks/{task_id}
POST /daily-report-deliveries/agent/tasks/{task_id}/claim
GET  /daily-report-deliveries/agent/tasks/{task_id}/attachment
POST /daily-report-deliveries/agent/tasks/{task_id}/send-intent
POST /daily-report-deliveries/agent/tasks/{task_id}/result
```

全部强制 `require_local_agent_context()`；SQL JOIN 同时验证 task、delivery、job、staff 的可信 merchant。关联缺失或跨商户统一 404。

- [ ] 原子 claim：`pending -> running`，生成 execution token 和 download ticket，只存 hash。响应一次性返回明文及 task/delivery/attempt/target/file_name/hash/size/expires。并发、旧 attempt、另 Agent claim 均 409。

- [ ] 单次下载请求头：

```text
X-Local-Agent-Token
X-Report-Execution-Token
X-Report-Download-Ticket
```

常量时间比较、过期/重放校验、`validate_artifact_path()`、重算 hash/size、最大大小、原子消费 ticket；响应使用 XLSX MIME、安全 Content-Disposition、no-store/nosniff。ticket 禁止进 query。

- [ ] `send-intent` 二次检查 execution、downloaded、attempt、rollout、allowlist、staff active/开关/昵称、merchant、取消状态、同商户同销售 10 秒限频；PG 锁 staff。通过后签发 15 秒单次 nonce，只存 hash。

- [ ] 结果字段固定为：execution token、send nonce、success、contact verified、partial/manual、downloaded/pasted/send_triggered/message_verified、failure_stage、agent identity、最小 evidence。状态规则：未触发发送的失败可重试；已触发未验证为 verify_pending；全部门禁和 nonce 有效才 sent；旧 token/nonce 409；重复 sent 幂等。
- [ ] 增加租约回收：running 过期且 `send_nonce_hash IS NULL` 转 failed；任何曾签发 nonce 的超时任务转 verify_pending。回收使用数据库条件更新并写安全审计，不由 Agent 本地时钟决定。
- [ ] 旧通用 `/wechat-tasks/{task_id}/result` 对 `send_report_attachment` 必须返回 409/422，禁止绕过附件专用 nonce、气泡验证和 delivery 状态机。

- [ ] 运行并提交：

```powershell
python -m pytest tests/test_daily_report_delivery_agent_api.py tests/test_phase7_fix2_local_agent_auth.py tests/test_p0_5a_wechat_tasks.py -v
git add app/routers/daily_report_deliveries.py app/schemas.py app/main.py app/services/daily_report_delivery_service.py tests/test_daily_report_delivery_agent_api.py
git commit -m "功能：增加 Local Agent 附件下载与回写协议"
```

---

## Task 5：Local Agent 安全下载器

**Files:**

- Modify: `app/local_agent_main.py`
- Create: `tests/test_phase8b_local_agent_downloader.py`

- [ ] 测试并实现：token/ticket 仅 header；拒绝 30x redirect；production/公网 HTTP 拒绝；测试 override 只允许 loopback/RFC1918；流式限大小；先写 `.part`；校验 name/hash/size/MIME 后原子 rename；文件名 basename 化且仅 `.xlsx`；任何失败 finally 删除临时目录；日志无 token、query、路径或内容。

固定 helper：

```python
def _download_report_attachment(
    *, server_url: str, task_id: int, execution_token: str,
    download_ticket: str, expected_name: str,
    expected_sha256: str, expected_size: int,
) -> Path: ...
```

- [ ] 运行并提交：

```powershell
python -m pytest tests/test_phase8b_local_agent_downloader.py tests/test_phase7_fix2_local_agent_auth.py -v
git add app/local_agent_main.py tests/test_phase8b_local_agent_downloader.py
git commit -m "功能：增加 Local Agent 安全附件下载器"
```

---

## Task 6：Windows CF_HDROP 与文件气泡验证

**Files:**

- Create: `app/wechat_ui/file_attachment_sender.py`
- Create: `app/wechat_ui/file_message_verifier.py`
- Modify: `app/wechat_ui/clipboard_utils.py`
- Create: `tests/test_phase8b_file_attachment_sender.py`
- Create: `tests/test_phase8b_file_message_verifier.py`

- [ ] CF_HDROP 测试：`DROPFILES` 宽字符、`fWide=1`、双 NUL；只接受单个已存在 `.xlsx` 普通文件；拒绝目录/symlink/UNC/控制字符；无法安全恢复的非文本剪贴板则阻断；原剪贴板为空或仅文本时发送后恢复；Win32 失败正确释放句柄。

- [ ] 验证器测试：baseline 记录消息数、本人侧精确文件名匹配数和最后索引。after 只有新增项 sender=self、文件名精确匹配且不是历史同名项才通过；unknown 不通过。

- [ ] 固定发送顺序：readiness -> 联系人 verified -> baseline -> 焦点 -> CF_HDROP -> Ctrl+V -> 附件预览 -> 焦点/紧停二次检查 -> 9000 send-intent -> Enter -> 新增本人文件气泡 -> 恢复剪贴板/清临时文件。单元测试全部 mock，不真实按 Enter。

- [ ] 运行并提交：

```powershell
python -m pytest tests/test_phase8b_file_attachment_sender.py tests/test_phase8b_file_message_verifier.py tests/test_p0_3d_clipboard.py tests/test_p0_3b_focus_guard.py tests/test_p0_2c_safety.py -v
git add app/wechat_ui/file_attachment_sender.py app/wechat_ui/file_message_verifier.py app/wechat_ui/clipboard_utils.py tests/test_phase8b_file_attachment_sender.py tests/test_phase8b_file_message_verifier.py
git commit -m "功能：增加微信 Excel 附件安全发送器"
```

---

## Task 7：Local Agent 集成与无发送探针

**Files:**

- Modify: `app/local_agent_main.py`, `app/services/wechat_task_service.py`
- Create: `tests/test_phase8b_poll_and_send_attachment.py`
- Create: `scripts/probe_phase8b_wechat_file_message_controls.py`

- [ ] 新增 `POST /agent/tasks/poll-and-send-report`，与 execute/detect 共用 `_wechat_task_lock`，每次只处理一条 `send_report_attachment`。
- [ ] 总开关关闭时只能拉元数据：不 claim、不下载、不搜索联系人、不设置剪贴板、不按 Enter。
- [ ] probe 脚本只读人工打开的专用测试聊天窗口，输出脱敏控件摘要；不保存截图、不写输入框。
- [ ] 总开关和 allowlist 均通过才执行 claim -> download -> verify -> CF_HDROP -> send-intent -> Enter -> verify -> result。异常也回写安全失败摘要。
- [ ] 本 Task 不接后台 runtime loop；Task 8 单发通过前禁止自动轮询。
- [ ] 运行并提交：

```powershell
python -m pytest tests/test_phase8b_poll_and_send_attachment.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_legacy_wechat_debug_lockdown.py -v
git add app/local_agent_main.py app/services/wechat_task_service.py tests/test_phase8b_poll_and_send_attachment.py scripts/probe_phase8b_wechat_file_message_controls.py
git commit -m "功能：接入 Local Agent 日报附件任务"
```

---

## 检查点 A：无发送评审

Task 1-7 后暂停。Spec 与 Code Quality Reviewer 必须确认：测试未真实按 Enter；默认配置无可执行任务；协议无 token 泄露；旧 notify/detect 全绿；探针能在目标微信识别精确文件名和 sender=self。探针不可行则 `BLOCKED`，不得进入 Task 8。

---

## Task 8：专用联系人首次真实单发

**Files:**

- Create: `scripts/smoke_phase8b_real_wechat_attachment.py`
- Create: `tests/test_phase8b_real_wechat_smoke_contract.py`

- [ ] 合同要求显式 `--allow-real-wechat-send`、Task 0 六项、虚构 `.xlsx`、allowlist 命中、全量开关 false；拒绝生产数据库/merchant；日志不打印 token、昵称、路径或内容。
- [ ] 先跑只下载 smoke：claim/download/hash/temp cleanup，不操作剪贴板和微信；全绿后再次暂停。
- [ ] 唯一一次真实发送：

```powershell
python scripts/smoke_phase8b_real_wechat_attachment.py --allow-real-wechat-send
```

Expected：contact verified、downloaded、pasted、send_triggered、message_verified 全 true；task/delivery sent；临时残留 0。

- [ ] Enter 前失败可新 attempt；Enter 后未验证必须 verify_pending，先人工确认对端是否收到；只有明确未收到才 `confirm_not_sent=true` 重试。不得放宽 sender、文件名、联系人或焦点。
- [ ] 提交：

```powershell
git add scripts/smoke_phase8b_real_wechat_attachment.py tests/test_phase8b_real_wechat_smoke_contract.py
git commit -m "测试：增加日报附件专用联系人真机冒烟"
```

---

## 检查点 B：真实单发审批

回传 Windows/微信版本、脱敏文件名/hash 前 8 位、task/delivery id、逐门禁、对端确认和临时残留 0。审批通过后才能接自动轮询。

---

## Task 9：自动轮询与管理后台

**Files:**

- Modify: `app/local_agent_main.py`, `app/routers/daily_report_deliveries.py`, `app/schemas.py`
- Modify: `frontend/src/api/dailyReports.ts`, `frontend/src/api/types.ts`
- Modify: `frontend/src/features/wechat-assistant/pages/DailyReports.tsx`
- Create: `frontend/scripts/check-phase8b-report-delivery-contract.mjs`
- Modify: `tests/test_daily_report_delivery_agent_api.py`
- Create: `tests/test_daily_report_delivery_admin_api.py`

- [ ] runtime loop 仅在总开关 true 时每轮最多一条，顺序 `notify_sales -> detect_reply -> send_report_attachment`；共用锁；verify_pending 不重试。
- [ ] 管理 API：job deliveries 列表、reconcile、delivery retry/cancel。普通报表需 agent，lead_trace 额外 leads；可信 merchant 来自上下文；跨商户 404；verify_pending retry 必须 confirm；动作写脱敏审计。
- [ ] 前端展示报表、日期、销售显示名、状态、attempt、安全失败阶段、发送时间和“当前 job 是否已有新 artifact”；提供重试/取消，但 sent 不提供重发按钮。不显示微信标识、storage/path、token/ticket/nonce/hash/raw_result。
- [ ] 运行并提交：

```powershell
python -m pytest tests/test_daily_report_delivery_admin_api.py tests/test_daily_report_delivery_agent_api.py tests/test_phase8b_poll_and_send_attachment.py -v
Set-Location frontend
node scripts/check-phase8b-report-delivery-contract.mjs
npx tsc -p tsconfig.app.json --noEmit
npm run build
Set-Location ..
git add app/local_agent_main.py app/routers/daily_report_deliveries.py app/schemas.py frontend/src/api/dailyReports.ts frontend/src/api/types.ts frontend/src/features/wechat-assistant/pages/DailyReports.tsx frontend/scripts/check-phase8b-report-delivery-contract.mjs tests/test_daily_report_delivery_agent_api.py tests/test_daily_report_delivery_admin_api.py
git commit -m "功能：增加日报附件投递后台与自动轮询"
```

---

## Task 10：PostgreSQL 真实事务冒烟

**Files:**

- Create: `scripts/smoke_phase8b_postgres_delivery.py`
- Create: `tests/test_phase8b_postgres_delivery_smoke.py`

- [ ] 复用 Phase 8-A `_validate_smoke_url`：`postgresql+psycopg`、既有 host 白名单、database 以 `_test/_staging` 结尾、无 query/fragment、不回显密码、显式破坏性确认。
- [ ] 验证 PG 0010、表/列/FK/索引/类型；两事务 ensure 唯一；并发 retry attempt 唯一；两 Agent claim 唯一；ticket/nonce 单次与过期；running 与 send_authorized 两类租约回收；旧通用 result 不能旁路；跨商户全拒绝；artifact pin/outdated；verify_pending；`_RUN_ID` 数据和文件残留 0。
- [ ] 运行：

```powershell
python -m pytest tests/test_phase8b_postgres_delivery_smoke.py -v
python scripts/smoke_phase8b_postgres_delivery.py --allow-destructive-migration-cycle
```

无安全非生产 PG 时阶段为 `BLOCKED`，不得以 SQLite 替代。

- [ ] 提交：

```powershell
git add scripts/smoke_phase8b_postgres_delivery.py tests/test_phase8b_postgres_delivery_smoke.py
git commit -m "测试：补齐日报附件投递 PostgreSQL 验收"
```

---

## Task 11：总验证与双重评审

- [ ] 专项：

```powershell
python -m pytest tests/test_phase8b_delivery_schema.py tests/test_daily_report_delivery_service.py tests/test_daily_report_delivery_agent_api.py tests/test_daily_report_delivery_admin_api.py tests/test_phase8b_local_agent_downloader.py tests/test_phase8b_file_attachment_sender.py tests/test_phase8b_file_message_verifier.py tests/test_phase8b_poll_and_send_attachment.py tests/test_phase8b_postgres_delivery_smoke.py -v
```

- [ ] 关联：

```powershell
python -m pytest tests/test_daily_reports_api.py tests/test_daily_report_scheduler.py tests/test_p0_5a_wechat_tasks.py tests/test_p0_main_5b_poll_and_execute.py tests/test_p1_auto_1c_poll_and_detect.py tests/test_phase7_fix2_local_agent_auth.py tests/test_forbidden_word_send_integration.py tests/test_legacy_wechat_debug_lockdown.py tests/test_p0_3d_clipboard.py tests/test_p0_3b_focus_guard.py tests/test_p0_2c_safety.py -v
```

失败必须用阶段起点 worktree 跑同命令对照。

- [ ] 前端三检：

```powershell
Set-Location frontend
node scripts/check-phase8-daily-reports-contract.mjs
node scripts/check-phase8b-report-delivery-contract.mjs
npx tsc -p tsconfig.app.json --noEmit
npm run build
Set-Location ..
```

- [ ] 静态边界：

```powershell
$start = "ff60d4b9ef5c3144dd3d944565442973d0f82052"
git diff --check "$start..HEAD"
git diff --name-only "$start..HEAD"
git diff --name-only "$start..HEAD" | Select-String -Pattern "input_writer.py|contact_searcher.py|return_visit|ad_review|ai_edit"
rg -n "file_storage_key|execution_token|download_ticket|send_nonce|LOCAL_AGENT_TOKENS" frontend/src
rg -n "token=|ticket=|send_nonce=" app/local_agent_main.py app/routers/daily_report_deliveries.py
```

- [ ] Spec Reviewer：4 个开关、job/staff 唯一、artifact pin、双令牌下载、send-intent、联系人/焦点/紧停、文件气泡验证、verify_pending、默认关闭、专用联系人首测。
- [ ] Code Quality Reviewer：条件更新、SQL 商户隔离、无长事务跨 IO、令牌 hash/常量比较、artifact 生命周期、finally 清理、旧任务零回归、无无关抽象/依赖。

只有两轮 Approved、PG smoke 全绿、专用联系人真实单发全绿，Phase 8-B 才可 DONE。

---

## 回传格式

```text
阶段：Phase 8-B Excel 附件真实分发
状态：DONE / BLOCKED / DONE_WITH_CONCERNS
阶段起点：ff60d4b9ef5c3144dd3d944565442973d0f82052
提交：
变更文件：

数据库迁移：SQLite 0029 / PostgreSQL 0010 / 真实 PG smoke
新增权限码：无
新增依赖：无
新增环境变量：列出 0.5 八项

首测环境（脱敏）：Windows / 微信版本 / 专用联系人已审批 / 虚构文件
真实发送门禁：联系人 / 焦点 / 紧停 / 下载 hash / CF_HDROP / send-intent / 新增本人文件气泡 / 对端确认 / 临时残留
幂等重试：job+staff 唯一 / 并发 claim / ticket+nonce 重放 / verify_pending
测试：
Spec Reviewer：
Code Quality Reviewer：
未触碰：input_writer、contact_searcher、微信数据库、DLL、协议逆向、Phase 9-13
用户既有残留：
剩余风险：
```

最终判定：`Phase 8-A DONE + Phase 8-B DONE = 完整 Phase 8 DONE`。若代码通过但专用联系人真机发送未完成，Phase 8-B 必须 `BLOCKED`，不能写 `DONE_WITH_CONCERNS`。
