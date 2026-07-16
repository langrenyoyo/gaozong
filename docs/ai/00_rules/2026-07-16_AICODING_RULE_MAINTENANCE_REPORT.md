# auto_wechat 规则与上下文维护报告（2026-07-16）

## 1. 审计摘要

- 基线版本：项目为自有规则（无受控区块）/ AICoding-RULE `0.1.0`。
- `Audit-AICodingRule.ps1`：2 项 INFO、0 项 WARN。两项信息分别为双入口 8 行入口措辞差异、规则文件未使用受控区块。
- `Compare-ProjectRules.ps1`：01~04 均为 `CUSTOM`，独立 `05_DOCUMENT_GOVERNANCE_RULES.md` 为 `MISSING`。
- 人工复核结论：CLAUDE.md 与 AGENTS.md 的 8 行差异均为工具入口称谓，硬约束语义一致；文档治理规则已等价内嵌在 `01_READING_RULES.md` 第 18 节，不重复安装独立治理文件。

### 1.1 人工基线复核

| 检查项 | 证据 | 处理 |
|---|---|---|
| 入口完整性 | CLAUDE.md、AGENTS.md、docs/ai README 与 01~05 均存在 | KEEP |
| 双入口漂移 | Compare-Object 仅返回 8 行 Claude/Agent 工具称谓差异 | KEEP |
| 受控区块 | 01~04 无 `AICODING-RULE:BEGIN`，项目档案 `.aicoding-rule.json` 不存在 | KEEP（成熟自有规则，不冒充已接入基线） |
| 规则/事实分层 | `01_READING_RULES.md:762`、`02_EXECUTION_RULES.md:757`、`03_TESTING_RULES.md:681` 是当前项目长期扩展；04 无项目事实 | KEEP |
| Compare 的缺失主题 | 懒惰阶梯在 CLAUDE/AGENTS；诊断安全在 02 第 22 节；最小验证与环境失败在 03 第 17、21 节；阶段复述/收口在 04 第 5A 节；治理规则在 01 第 18 节 | KEEP（标题识别差异） |
| 文档腐化 | 05 中迁移版本过期，Phase 10/12 含任务流水 | REWRITE（已原位修正） |
| 归档纪律 | 唯一 archive 文件头部明确“不是当前项目事实”；README 只在历史追溯区引用 | KEEP |
| 引用有效性 | 两次 Audit 均未报告失效引用 | KEEP |

## 2. 事实抽查结果

| 05 中的结论 | 核验证据 | 结论 |
|---|---|---|
| Phase 12 检查点 A/B/C 均通过，状态 `DONE_WITH_CONCERNS` | Git 提交 `e4adddf`；`docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md:11`、`:864` | 成立 |
| production、staging、dev 三套 Compose 职责不同 | `docker-compose.yml:6`、`docker-compose.staging.yml:30`、`docker-compose.dev.yml:24`；staging 使用 `!override` | 成立 |
| production 使用一个 PostgreSQL 实例、两个 database | `docker-compose.yml:39`、`:72`；`docker/postgres/init-prod/010_create_rag_database.sh:17` | 成立 |
| NewCar 鉴权代码默认开发态，生产模板固定真实鉴权；退出走 9000 | `app/config.py:256`、`:257`；`.env.production.example:148`、`:149`；`app/routers/auth.py:53`；`app/auth/newcar_client.py:84` | 成立 |
| 9000 PostgreSQL Alembic 版本为 0001~0010 | `migrations/postgres/auto_wechat/versions/0011_return_visit_phase9.py`、`0012_compute_billing.py`、`0013_ai_edit_local_mvp.py` | 已过期，已原位改为 0001~0013 |
| 9100 默认 SQLite，production 固定 Milvus | `apps/xg_douyin_ai_cs/config.py:36`、`:74`；`.env.production.example:384` | 成立 |
| Local Agent 默认只监听 `127.0.0.1:19000`，前端直连当前电脑 | `app/local_agent_main.py:66`、`:67`；`frontend/src/api/localWechatAgent.ts:1`、`:341` | 成立 |
| 抖音客服工作台读取本地事件、支持加载更早会话且返回页恢复缓存 | `app/services/douyin_workbench_conversation_service.py:95`、`:441`；`frontend/src/features/douyin-cs/pages/DouyinAiCsWorkbenchPage.tsx:76`、`:2513` | 成立 |
| 一键过审已由客户取消 | `CLAUDE.md:136`、`AGENTS.md:136`、`docs/ai/05_PROJECT_CONTEXT.md:34` | 成立，属于已确认业务决定 |

## 3. 本轮文档修改

- `docs/ai/05_PROJECT_CONTEXT.md`：补充抖音工作台当前事实；把 9000 PostgreSQL 迁移版本从 0010 修正到 0013；压缩 Phase 12 和 Phase 10 的任务流水，只保留当前能力、状态与风险。
- `docs/config/ENV_VARIABLE_REFERENCE.md`：修正会话事件窗口与未读回看天数的用途。
- `docs/ai/README.md`：把 `00_rules/` 从预留目录改为规则审计和周期维护报告入口。
- 替换/删除的旧结论：删除 Phase 10 提交号和 Must-Fix 过程；删除 Phase 12 已完成修复项的逐项流水；替换过期迁移版本。
- 归档内容：本轮未新增归档。活动 05 没有需搬迁的详细过程章节；已删除的过程可由现有执行包和 Git 追溯，重复生成归档会制造第二份历史真源。现有 `docs/ai/archive/2026-07-14_05_PROJECT_CONTEXT_历史里程碑流水账快照.md` 已有完整冻结声明。

## 4. 升级动作

- 受控区块升级：否。项目没有受控区块，不存在区块版本落后。
- 未运行 Install：项目 01~04 是成熟自有规则，且治理规则已有等价实现；直接安装会新增重复规则文件，不能视为安全升级。
- 项目扩展区受影响：否。

## 5. 一致性检查

- 双入口一致性：CLAUDE.md 与 AGENTS.md 仅有 8 行入口称谓差异，硬约束语义一致。
- 05 体量：约 26.1KB、319 行、14 个固定主题章节，低于 60KB 提示线和 80KB 强制瘦身线；没有按日期追加的记录型章节。
- 规则文件：未发现新增任务完成流水；P1、微信自动化和诊断安全章节属于当前长期项目扩展规则，继续保留。
- 归档纪律：唯一 archive 文件有“非当前事实”冻结声明，README 仅在历史追溯区引用。
- 引用路径有效性：Audit 未发现失效引用；维护后再次执行审计确认。
- `git diff --check`：维护提交前执行。

## 6. 遗留与人工确认

1. 是否把成熟自有规则迁移为 AICoding-RULE 受控区块，需要单独治理决策；本轮不自动迁移。
2. Compare 提示 02 缺少“产物与密钥禁提交清单”。当前项目在入口硬约束、`.gitignore` 和具体安全规则中分散覆盖，是否升级为统一治理章节需人工确认。
3. 工作区存在未跟踪的 Task 11 执行包及相关 AI剪辑文档改动，属于并发任务，本维护提交不纳入、不裁决。

## 7. 结论

- 本轮修正 1 项确定过期事实，压缩 2 处任务流水；未发现入口冲突、归档误用或需要自动升级的受控区块。
- 无文档影响的部分：业务代码、数据库迁移、部署配置、鉴权和发送门禁均未修改。
- 建议提交信息：`文档：执行 AI 规则与上下文周期维护`。
