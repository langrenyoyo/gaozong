# M04 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| WeChat task create | COVERED | test_manual_notify_sales_task.py / test_lead_wechat_notify_eligibility_service.py |
| task polling | MISSING | 无 19000 poll 路径集成测试 |
| task claim | MISSING | 无 lease/claim 测试（功能不存在） |
| result report | PARTIAL | test_p0_reply_2_agent_write_back.py（回写路径）；无幂等性测试 |
| result idempotency | MISSING | 无重复回写幂等测试 |
| merchant isolation | COVERED | test_p0_5a_wechat_tasks.py（商户隔离） |
| sales mapping | PARTIAL | 代码确认 staff_id FK 绑定；无 E2E |
| lead mapping | COVERED | 代码确认 lead_id FK 永久绑定 |
| send task | MISSING | 无真实微信发送测试（需 Windows+微信） |
| retry | MISSING | 无自动重试机制（功能不存在） |
| offline behavior | MISSING | 无 Agent 离线场景测试 |
| feedback collection | PARTIAL | test_p0_reply_2_agent_write_back.py；test_sales_feedback_parser.py（parser 单测） |
| feedback parse | COVERED | test_sales_feedback_parser.py（三类模板解析） |
| feedback persistence | PARTIAL | parser 单测 PASS；parse_and_persist API 400（ISSUE-M02-007） |
| M02 integration | COVERED | test_phase7_fix2_assign_atomic_timezone.py / test_phase7_fix2_dispatch_trust_boundary.py |
| 19000 integration | EXTERNAL_ENV_REQUIRED | 需 Windows + 微信 + 19000 运行 |
| Legacy guard | COVERED | test_p0_end_2a_legacy_scheduler_disable.py / test_legacy_wechat_debug_lockdown.py |

## E2E 验真结果（2-M04.2 Docker，2026-08-07）

环境：docker compose dev（9000 + PG + 能力中心，无 19000）

### Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| A Task Create | PARTIAL | send-to-staff 创建成功（task_id=1, notification_id=1, feedback_no=XGF-7-1），但后续 GET /wechat-tasks 查询返回 0 条（可能是查询权限/路由问题，非创建失败） |
| B Poll Merchant Isolation | ENVIRONMENT_BLOCKED | agent token 401（docker dev LOCAL_AGENT_TOKEN 非 "dev"，无法用 agent header poll） |
| C Concurrent Poll | ENVIRONMENT_BLOCKED | 同 B，agent token 401 无法 poll；无 pending task 可拉取 |
| D Result State Transition | ENVIRONMENT_BLOCKED | agent token 401 无法回写 result |
| E Duplicate Result | ENVIRONMENT_BLOCKED | 同 D |
| F Invalid Task Result | CODE_VERIFIED | 代码确认 task_belongs_to_merchant 双校验（wechat_task_service.py:179-180） |
| G Lead/Staff Consistency | CODE_VERIFIED | 代码确认 lead_id+staff_id FK 创建时固化（models.py:300-301） |
| H Manual send-to-staff | **PASS** | Lead+Staff+联系方式→send-to-staff→200 created（task_id=1, notification_id=1, feedback_no=XGF-7-1, 通知文本含完整模板） |
| I Feedback Full Context | PENDING | 需完整 detect_reply 路径 + parse_and_persist 进程内调用（Docker 不含 19000） |

### 环境限制说明

- **LOCAL_AGENT_TOKEN**：docker dev 配置的 token 非 "dev"，agent header 401，无法用 Local Agent 身份 poll/result
- **19000 不在 docker compose**：19000 是宿主机 Windows 进程，docker dev 无法模拟
- **GET /wechat-tasks 查询**：send-to-staff 返回 task_id=1 但列表查询返回 0 条，可能需要 agent token 或其他查询条件
- Gate B/C/D/E 的核心验证需正确配置 LOCAL_AGENT_TOKEN 或在真实 19000 环境进行

### ISSUE-M04-001/002 升级条件检查

- **Concurrent Poll（C）**：ENVIRONMENT_BLOCKED，未证明两 Agent 同时获取同一 Task
- **Duplicate Result（E）**：ENVIRONMENT_BLOCKED，未证明重复回写产生重复副作用
- 两个 ISSUE 保持 MEDIUM，升级条件未满足

### ISSUE-M02-007 检查

- Gate I PENDING，需完整 feedback context + 真实 detect_reply 路径
- 保持 MEDIUM，ISSUE-M02-007 不关闭

**E2E 状态：`M04_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_WINDOWS`**（无 BLOCKER，Gate H PASS + F/G CODE_VERIFIED + I PENDING，B/C/D/E ENVIRONMENT_BLOCKED 需 Windows 19000）

## E2E 验收清单（待 2-M04.2 Windows / Staging）

### CODE_VERIFIED
- WechatTask 数据模型 + 状态机
- 9000→19000 HTTP 通信 + token 认证
- 商户隔离双层（token→merchant_id + lead/staff FK 反查）
- feedback_no 生成+校验（XGF-{lead_id}-{staff_id}）
- ISSUE-M02-007 CONTRACT_MATCHES（M04 输出格式与 parse_and_persist 一致）

### DOCKER_TESTABLE
- WechatTask CRUD（API 层）
- 手动 send-to-staff 创建任务
- result report 状态流转
- merchant isolation（跨商户 task_id → 404）

### WINDOWS_LOCAL_AGENT_REQUIRED
- 19000 poll → 微信 UI 自动化执行 → result 回传
- detect_reply → 微信消息读取 → 反馈采集
- foreground guard / search_focus / OCR 验证
- heartbeat → online/offline 判断

### REAL_WECHAT_REQUIRED
- 真实微信发送（paste_only/single_send）
- 真实销售反馈采集（模板回填）
- 空号反馈写入 CustomerProfile

### STAGING_REQUIRED
- M02 webhook→M04 自动通知（auto_notify 当前 disabled）
- M04→M02 真实反馈持久化全链路

### POLICY_PENDING
- super_admin Local Agent 访问行为
