# AI 自动回复 outbox 服务重启恢复测试设计

> Task-ID：`DY-CS-AUTO-REPLY-OUTBOX-RESTART-RECOVERY-1`
>
> Spec-Revision：`S1`
>
> Base-Commit：`cb11bc1c8856d62f470e4ad9641233772579d3ee`
>
> 目标分支：`master`
>
> 风险等级：`L2`
>
> 治理方式：`full-three-authority`
>
> 状态：`SPEC_APPROVED`
>
> 日期：2026-07-25

本设计只冻结本地开发机上的跨进程重启恢复测试合同。它不授权修改 outbox 业务逻辑、连接生产环境、执行生产迁移或发送真实消息。

------

## 1. 目标与非目标

### 1.1 测试目标

验证 AI 自动回复 outbox 在原进程内存、线程锁和数据库连接全部消失后，仅依赖已提交的数据库状态，能够由全新进程正确完成恢复、领取、对账和去重。

测试必须证明：

- 进程 A 和恢复进程 B 使用不同 PID；
- 进程 A 的持久状态能被进程 B 读取；
- `pending`、过期 `processing`、过期 `send_processing` 和到期 `retry_wait` 只被处理一次；
- `send_authorized` 只做发送流水对账，禁止自动重发；
- 连续两次重启不会产生重复处理副作用；
- 调度器关闭时不会领取任务；
- 非法租约状态失败关闭，并产生可诊断日志。

### 1.2 非目标

本任务不验证：

- 真实 PostgreSQL 或 PostgreSQL MVCC 并发；
- 生产调度器、生产迁移、部署或发布；
- 真实 LLM、9100、抖音私信、自动回复或微信发送；
- outbox 业务逻辑返修；
- 全仓测试。

SQLite 跨进程结果只能证明本地持久化与进程重启语义，不能写成 PostgreSQL 或生产恢复已经验证。

------

## 2. 当前事实与测试缺口

当前启动调用链为：

```text
app.main.on_startup
  -> start_outbox_scheduler()
  -> _scheduler_loop() 启动立即扫描
  -> run_outbox_cycle()
  -> recover_expired_leases()
  -> claim_next_batch()
  -> _process_one()
```

`run_outbox_cycle()` 已使用进程内非阻塞单飞锁，`claim_next_batch()` 会提交线程唯一租约，`recover_expired_leases()` 会恢复过期 `processing`/`send_processing`，并对账过期 `send_authorized`。现有测试覆盖这些函数及线程竞争，但都在同一个 pytest 解释器内运行，无法证明全新进程能仅凭落盘数据恢复。

------

## 3. 方案选择

采用独立测试工作进程方案：pytest 父进程只负责编排、时间字段推进和最终断言；进程 A、B、C 均通过 `subprocess` 启动全新 Python 解释器，并共享同一个临时文件 SQLite。

不采用以下方案：

- 不启动完整 9000 服务。完整启动会同时触发热键、桌面提示和其他调度器，扩大本地副作用和不稳定面。
- 不使用同一 pytest 进程内的模块重载。模块重载不能证明进程锁、线程局部状态和连接池已完全消失。
- 不直接使用 pytest fixture 对象跨进程。Windows `spawn` 与测试上下文耦合较强，诊断性不如显式命令入口。

------

## 4. 组件与职责

### 4.1 pytest 父进程

文件：`tests/test_ai_auto_reply_outbox_restart_recovery.py`

职责：

- 使用 `tmp_path` 创建每个测试独占的 SQLite 文件、日志文件和审计标记文件；
- 启动测试工作进程并设置明确的安全环境变量；
- 校验子进程退出码、结构化 JSON、PID 和日志；
- 使用全新 SQLAlchemy Session 检查最终数据库状态；
- 直接更新测试库的租约或重试时间字段，避免真实等待 60/300 秒；
- 统计测试审计标记，证明安全处理器只执行一次。

### 4.2 测试工作进程

文件：`tests/helpers/outbox_restart_worker.py`

职责：

- 在导入 `app.database` 前接收临时 `DATABASE_URL` 和安全配置；
- 只接受冻结的有限动作：准备状态、领取后异常退出、执行恢复、执行一轮周期、验证调度器关闭、触发非法租约入口；
- 调用真实 `claim_next_batch()`、`recover_expired_leases()`、`run_outbox_cycle()`、`start_outbox_scheduler()` 和 `_process_one()`；
- 周期处理时仅替换 `_run_with_session_for_outbox`，使用真实 guarded 状态更新将任务推进到安全终态 `blocked` 并清租约；
- 每次安全处理向测试审计标记文件追加一条结构化记录；
- 向标准输出写一条最终 JSON，包含 PID、动作、run ID、状态和处理数量。

测试工作进程不是通用管理脚本，不进入 `scripts/`，不得接受任意 Python 表达式、SQL、模块路径、URL 或 shell 命令。

------

## 5. 数据流与异常退出

标准跨进程流程：

```text
pytest 父进程
  -> 创建临时文件 SQLite 和 schema
  -> 启动进程 A，写入并提交指定状态
  -> processing 场景由 A 在 claim 提交后调用 os._exit() 非正常退出
  -> 父进程确认 A 已退出，并把租约时间设为过去
  -> 启动全新进程 B，执行真实 recover/cycle
  -> 可选启动全新进程 C，再执行一轮 cycle
  -> 父进程以新 Session 校验状态、租约、流水和审计标记
```

`os._exit()` 只用于测试工作进程，且必须发生在 claim 已提交之后。父进程必须设置超时并确保回收所有子进程；测试失败时不得遗留后台进程。

------

## 6. 安全门禁

每个子进程必须显式设置：

- `DATABASE_URL` 指向当前测试的临时 SQLite 文件；
- `AI_AUTO_REPLY_OUTBOX_ENABLED=false`，仅调度关闭专用场景显式验证该值；
- 抖音自动回复、真实发送和其它可能触发外部动作的总开关为关闭态；
- 不继承生产数据库地址、生产 token 或真实发送授权。

测试处理器必须满足：

- LLM、9100、抖音、微信和通用网络调用全部为“调用即测试失败”；
- 不生成伪造的 `sent` 终态；测试处理成功只写 `blocked` 和测试专用原因；
- `send_authorized` 场景只能调用真实恢复对账，不进入处理器；
- 日志与 JSON 不输出手机号、微信号、open_id、token、数据库秘密或原始消息正文。

------

## 7. 验收矩阵

| ID | 场景 | 操作 | 预期结果 |
|---|---|---|---|
| R1 | 进程隔离与落盘 | A 提交状态后退出，B 读取同一临时库 | A/B PID 不同；B 读到 A 的 run ID 与状态 |
| R2 | `pending` 重启 | A 写 `pending` 后退出，B 执行 cycle | B 领取并安全处理一次；终态 `blocked`；租约清空 |
| R3 | 过期 `processing` | A 真实 claim 后 `os._exit()`，父进程推进租约过期，B 执行 cycle | 先恢复为可处理态，再领取并安全处理一次；`last_failure_stage` 经过 `lease_expired` |
| R4 | 过期 `send_processing` | A 提交过期状态后退出，B 执行 cycle | 恢复、领取、安全处理一次；旧 owner 不保留 |
| R5 | `retry_wait` 退避 | B 在未来 `next_attempt_at` 扫描；父进程推进到期后 C 再扫描 | B 不领取；C 领取且只处理一次 |
| R6 | `send_authorized` 有流水 | A 提交过期授权态和 `sent` 流水，B 恢复 | 状态变为 `sent`，租约清空，安全处理器与真实发送均为 0 次 |
| R7 | `send_authorized` 无流水 | A 提交过期授权态且无流水，B 恢复 | 状态变为 `send_unknown`，`last_failure_stage=send_authorized_crash_unknown`，不重发 |
| R8 | 连续两次重启 | B 完成 R2/R3/R4 任一恢复后，C 再执行 cycle | C 不再处理该任务；审计标记总数仍为 1 |
| R9 | 调度器关闭 | 待处理任务存在时调用 `start_outbox_scheduler()` | 不创建有效扫描线程、不领取任务，日志含 `reason=disabled` |
| R10 | 空租约失败关闭 | 对 `lease_owner` 为空的 processing 任务调用真实 `_process_one()` | 非零受控结果；状态不被覆盖；日志含 `stage=process_one` 和 `failure_stage=missing_lease_owner` |
| R11 | 外部副作用阻断 | 汇总全部场景 | LLM、9100、抖音、微信及网络调用均为 0；无真实发送记录 |

所有状态断言必须由父进程新建 Session 后读取，不能使用子进程返回对象代替数据库证据。

------

## 8. 错误处理与诊断

- 子进程超时：父进程终止该测试子进程并报告动作、PID、stdout/stderr 摘要，不继续后续状态断言。
- 子进程异常：返回非零退出码；父进程保留脱敏日志和最后一条结构化结果。
- JSON 缺失或格式错误：测试失败，不从自由文本猜测结果。
- 数据库锁：测试失败并报告具体动作；不得将重试掩盖为通过。
- 业务合同失败：保持红灯，回传 run 状态、租约、流水、审计次数和日志证据；禁止在本任务内修改业务服务。

日志验收至少包括正常扫描的 `stage`、非法租约的 `stage/failure_stage` 和恢复后的数据库 `last_failure_stage`。如果现有业务日志不满足冻结合同，应作为业务返修证据回传。

------

## 9. 允许与禁止范围

### 9.1 允许文件

```text
tests/test_ai_auto_reply_outbox_restart_recovery.py
tests/helpers/outbox_restart_worker.py
```

### 9.2 禁止文件

除上述两个文件外全部禁止，特别包括：

```text
app/services/ai_auto_reply_outbox_service.py
app/services/ai_auto_reply_dry_run_service.py
app/services/ai_auto_reply_send_service.py
app/main.py
app/config.py
app/database.py
app/models.py
migrations/**
.env*.example
docs/ai/**
E:/work/2026-07-22 auto_wechat 今日 TODO.md
```

既存暂存文件 `docs/superpowers/plans/2026-07-23-douyin-webhook-atomic-idempotency.md` 必须保持原样，不修改、不取消暂存、不提交。

------

## 10. 候选与验证边界

- 执行窗口必须原地执行，不创建 worktree、不新建分支；测试窗口可从冻结候选建立隔离测试副本。
- 执行窗口只允许创建测试候选提交，不允许推送、合并、部署或发布。
- 候选回传后冻结；任何修改都必须产生新候选哈希。
- 执行窗口自测至少包括新增跨进程测试、现有 outbox 专项、发送状态机和 dry-run 相关回归。
- 独立测试窗口必须从精确候选哈希重复跨进程矩阵，并确认工作树前后干净。
- 如果新增测试暴露业务缺陷，执行窗口停止并回传失败证据；审批窗口另行决定 R1/R2 或新业务返修任务。
- 只有独立测试通过且候选获批准后，才能另做活动文档和外部 TODO 状态闭环；不得在测试候选中提前写“已完成”。

------

## 11. 文档影响

本规格获批只表示测试合同冻结，不改变当前运行事实，因此本阶段不修改 `docs/ai/05_PROJECT_CONTEXT.md`、`docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md` 或外部 TODO。

跨进程测试候选通过独立验收并获准推送后，再单独执行文档闭环：原位更新 outbox 重启恢复测试状态，同时保留“未验证真实 PostgreSQL/MVCC、生产调度、生产迁移、生产恢复、真实发送和全仓测试”的限制。

------

## 12. 当前审批边界

用户已批准独立测试工作进程方案和 R1-R11 验收矩阵。本规格通过后只允许编制对应实施计划；实施计划另行批准前不得新增测试文件或执行施工。
