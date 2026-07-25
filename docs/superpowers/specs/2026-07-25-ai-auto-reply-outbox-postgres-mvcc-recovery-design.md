# AI 自动回复 outbox PostgreSQL/MVCC 重启恢复验证设计

## 1. 元数据

- Task-ID：`DY-CS-AUTO-REPLY-OUTBOX-PG-MVCC-RECOVERY-1`
- 设计版本：`R1`
- 风险等级：`HIGH`
- 基线：远端 `master@f751985090c348d92bed6f1873952dc572b44659`
- 目标：在本地专用 PostgreSQL 测试库上验证 outbox 的跨进程可见性、领取竞争、租约恢复和发送对账语义。

## 2. 已确认方案

采用固定本地专用数据库方案：

- 复用 `docker-compose.dev.yml` 的 PostgreSQL profile。
- 固定测试数据库名为 `auto_wechat_outbox_test`。
- 仅通过 `SMOKE_DATABASE_URL` 显式传入 `postgresql+psycopg` 连接。
- pytest 不负责启动、停止或删除 Docker 容器和数据库。
- PostgreSQL schema 只允许通过 Alembic 初始化到 head，禁止 `Base.metadata.create_all()`。
- 测试只清理自身唯一 namespace 的数据，不删除其他开发数据，不执行 drop、truncate 或整表 delete。

## 3. 范围边界

### 3.1 本阶段允许

- 扩展 `tests/helpers/outbox_restart_worker.py`，让现有有限命令入口在不接收命令行 URL 的前提下支持安全 PostgreSQL 测试模式。
- 新增 `tests/test_ai_auto_reply_outbox_postgres_mvcc.py`，承载 PostgreSQL/MVCC 专项、安全门和稳定性测试。
- 运行本地专用 PostgreSQL 测试库的 Alembic、测试数据写入、精确清理和只读诊断。

### 3.2 本阶段禁止

- 不修改 `app/` 业务代码、模型、0016 或其他迁移、Compose、环境模板和配置默认值。
- 不连接默认开发库、staging、production 或任何非白名单 host。
- 不读取隐式 `DATABASE_URL`，不把连接 URL、密码或 token 放入命令行、日志、断言或提交。
- 除连接专用 PostgreSQL 测试库所需的数据库传输外，不调用 LLM、9100、抖音、微信或其他 socket；不发送真实消息，不创建非测试预置的发送流水。
- 不在发现缺陷后顺手修改业务实现；出现业务或迁移缺陷时停止并回传 `REPAIR_REQUIRED`。
- 不修改、取消暂存或提交当前已有的两份治理计划。

## 4. 方案选择

### 4.1 采用：扩展现有 Worker + 新增 PostgreSQL 专项

现有 Worker 已具备有限动作、结构化 JSON、文件审计、安全终态处理器、外部调用零容忍和子进程退出码合同。扩展它比新建第二套 Worker 更少重复，也避免把 SQLite R1-R11 全量复制到 PostgreSQL。

### 4.2 未采用：新增独立 PostgreSQL Worker

隔离清晰，但会复制安全处理器、审计、日志、退出码和外部调用拦截，后续两套协议容易漂移。

### 4.3 未采用：R1-R11 全量双后端参数化

覆盖更广，但大量场景与 MVCC 无关，执行时间和返修面接近翻倍。本阶段只验证 PostgreSQL 特有风险，SQLite R1-R11 继续作为相邻回归。

## 5. 安全数据库合同

`SMOKE_DATABASE_URL` 必须同时满足：

1. scheme 精确为 `postgresql+psycopg`。
2. host 只能是 `127.0.0.1`、`localhost`、`postgres` 或 `auto-wechat-postgres-dev`。
3. database 必须精确为 `auto_wechat_outbox_test`。
4. 禁止 query 和 fragment，避免通过附加参数改变连接目标。
5. 缺失变量时，日常测试收集允许跳过真实 PostgreSQL 用例；本任务指定验证必须设置变量并达到 `0 skipped`。
6. 所有诊断只输出脱敏 URL，不输出 password。

运行前用该 URL 执行 9000 PostgreSQL Alembic `upgrade head` 和 `current`。测试必须确认当前 revision 包含 0016，并检查 `ai_auto_reply_runs` 的 5 个 outbox 字段与 2 个索引。PostgreSQL 测试路径不得导入后调用 `create_all`。

## 6. 子进程协议

### 6.1 Worker 扩展

现有 `--database <sqlite-path>` 模式保持不变。解析器新增与 `--database` 互斥的 `--postgres-smoke` 标志；该模式只从继承环境读取并校验 `SMOKE_DATABASE_URL`，再在导入 `app.database` 前将其映射为子进程 `DATABASE_URL`。URL 不进入 argv。

Worker 新增 `--namespace`、`--ready-file` 和 `--start-file` 三个有限字符串/路径参数；PostgreSQL 专项必须传唯一 namespace，并只允许 ready/start 文件位于 pytest 临时目录。Worker 继续只接受枚举动作，不接受任意 SQL、模块名、Python 表达式、URL 或 shell 命令。

唯一新增枚举动作是 `claim-once`：等待 start 文件后调用一次真实 `claim_next_batch`，提交并输出领取到的 run_id、lease_owner 和进程 PID。其余场景继续复用现有动作与真实 service 入口：

- 读取已提交状态。
- claim 后按既有退出码异常退出。
- 执行安全 cycle、恢复、guarded 状态推进。

### 6.2 并发门禁

父进程用临时目录中的 ready 标记确认所有 20 个子进程已启动，再创建 start 标记同时放行。子进程等待门禁有固定超时；父进程对每个子进程设置 30 秒总超时。失败、超时或断言异常时必须终止并回收全部子进程。

## 7. 数据隔离与清理

每个测试生成唯一 namespace，并写入 `merchant_id`、`account_open_id`、`trigger_event_key` 和审计记录。清理时先按 `auto_reply_run_id` 删除该 namespace 的测试发送流水，再删除对应 outbox 行。

清理必须放在 `finally` 中；失败前先记录脱敏状态快照，再执行精确清理。清理失败只记录独立诊断，不得覆盖原始测试异常。测试结束后断言：

- namespace 对应 outbox 行为 0。
- namespace 对应发送流水为 0。
- 所有子进程已退出。
- SQLAlchemy engine 和 Session 已关闭。

## 8. 验收矩阵

| ID | 场景 | 验收要求 |
|---|---|---|
| P1 | 安全 URL | 非 psycopg、非白名单 host、非专用库、query/fragment 均失败关闭；日志不含密码 |
| P2 | Alembic/schema | revision 到 head 且含 0016；5 字段、时区类型、2 索引存在；未调用 create_all |
| P3 | 提交可见性 | 进程 A 提交 pending，进程 B 使用新连接读取同一 run 与 pending 状态 |
| P4 | 20 路 claim 竞争 | 同一 pending run 只允许 1 个进程胜出，19 个返回空；attempt_count 精确为 1；连续 10 轮 |
| P5 | 异常退出与租约 | claim 提交后进程异常退出；未过期时 0 个新领取；过期后恢复并安全处理 1 次 |
| P6 | retry_wait | 未到期时 0 个领取；父进程推进为到期后仅领取 1 次 |
| P7 | send_authorized 对账 | 有 sent 流水时变为 sent；无流水时变为 send_unknown；两者均清租约且不进入处理器 |
| P8 | 旧 Worker 防覆盖 | 新 Worker 接管后，旧 owner guarded update 的 rowcount 为 0，新状态、owner 和租约保持不变 |
| P9 | 外部副作用为零 | 所有 cycle 的 business_external_calls=0；除 P7 显式预置外无发送流水；不调用 LLM/9100/抖音/微信或非数据库 socket；专用 PostgreSQL 连接不计为业务外部调用 |

## 9. 回归与稳定性

执行窗口必须完成：

1. PostgreSQL P1-P9 专项全部通过且真实 PG 用例 `0 skipped`。
2. P4 连续 10 轮全部通过，无超时、死锁、重复领取或遗留子进程。
3. 现有 SQLite 重启恢复 R1-R11：`11 passed, 0 failed`。
4. outbox、send、dry-run、webhook 相邻回归：Candidate 0 个新增失败；范围外基线必须用 Base/Candidate 同环境对照。
5. 两个测试文件 `py_compile` 通过。
6. `git diff --check` 通过，候选 name-status 只包含允许的测试文件。

## 10. 失败处理

- 缺少安全 PostgreSQL 环境：`TEST_BLOCKED`，不得写 PASS。
- Alembic 未到 head、0016 schema 不一致：`REPAIR_REQUIRED`，停止并保留脱敏证据。
- 出现重复 claim、租约未过期被领取、旧 owner 覆盖或自动重发：P0 并发安全缺陷，停止，不修改业务代码。
- 子进程超时：终止全部子进程，记录动作、PID、run_id、stage 和 failure_stage，不记录 URL 或敏感值。
- 业务外部调用计数非零、出现非数据库 socket 或产生意外发送流水：测试立即失败。

## 11. 候选与闭环顺序

1. 测试候选仅包含 Worker helper 与 PostgreSQL 专项测试文件。
2. 候选经独立测试窗口验证 P1-P9、稳定性和相邻回归。
3. 独立测试通过后才允许普通快进推送；禁止 force。
4. 推送后另起文档闭环，原位更新 `docs/ai/05_PROJECT_CONTEXT.md`、`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md` 和已过期的 `docs/ai/03_data_and_migration/POSTGRESQL_MIGRATION_NOTES.md`。
5. 文档闭环独立测试并推送后，最后单独同步 `E:\work\2026-07-22 auto_wechat 今日 TODO.md`。

## 12. 完成定义

只有同时满足以下条件，本任务才能结论为 PASS：

- P1-P9 全部通过，P4 十轮稳定。
- 真实 PostgreSQL 用例 0 skipped。
- Candidate 0 个新增回归失败。
- 业务外部调用、非数据库 socket 和意外发送流水均为 0；只允许专用 PostgreSQL 数据库连接。
- 测试数据精确清理，无遗留子进程。
- 未修改业务代码、迁移、Compose、环境模板或配置。
- 未连接 staging/production，未部署、未发布、未生产迁移、未真实发送。
