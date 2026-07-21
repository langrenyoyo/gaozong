# Auto WeChat 管理员切换与退出主线集成计划 P3

## 身份

- Task-ID：`P1-AUTO-WECHAT-ADMIN-SWITCH-LOCAL-LOGOUT-1`
- Plan-Revision：`P3`
- Master-Integration-Base：`137db8ecc4de6c23b5579101fc0d4ae43ef9e392`
- Plan-Commit：由本计划审批提交的完整哈希确定，并作为执行窗口 Base-Commit。
- Source-Candidate：`6dfd2f5047c1bdf43750a78fa62d4a0973a7254a`
- 风险等级：L3，继续使用完整三权分离。

## 重规划原因

P2/R1 独立测试通过后，`master` 已从共同基线
`105a4abaa52e440519e4e44c09aa11bb9c5ae2a4` 前进到新的 PostgreSQL / 抖音授权账号修正及 plan 原地执行规则提交，
不再是 P2 候选的祖先。禁止直接在主工作区生成未经测试的合并结果，因此先在隔离集成分支产生新候选并重新验收。

## 集成策略

1. 审批窗口先把本计划单独提交；该 Plan-Commit 的唯一父提交必须是 Master-Integration-Base。
2. 新执行窗口必须直接以审批窗口已经创建的计划工作树 `E:\work\project\auto_wechat\.worktrees\auto-wechat-admin-switch-logout-integration-p3` 作为启动目录，在现有 `plan/auto-wechat-admin-switch-logout-p3` 分支原地执行；不得再创建或切换工作树、分支或目录。Plan-Commit 即正式 Base-Commit。
3. 使用非快进合并引入 Source-Candidate，集成提交第一父提交必须是 Plan-Commit，第二父提交必须是 Source-Candidate。
4. 双方业务源码不重叠；唯一共同修改文件是 `docs/ai/05_PROJECT_CONTEXT.md`。预检显示 Git 可自动合并；若实际合并发生冲突，执行窗口必须停止并回传，不得自行改写。
5. 集成候选通过代码审查、自动测试和独立浏览器测试后，审批窗口才能签发本地集成批准；主工作区 `master` 只能使用 `--ff-only` 前进到该精确哈希。
6. 不推送、不发布；不修改 `E:\work\project\used-car`。
7. Master-Integration-Base 已包含 plan 原地执行偏好。本轮用户已明确批准继续使用审批窗口先前创建的现有计划工作树；执行窗口不得新建其它工作树或分支，也不得进入、暂存、恢复或改写主工作区。最终更新 `master` 前由审批窗口重新核验主工作区状态和主线哈希。

## 允许范围

- `frontend/src/api/client.ts`
- `frontend/src/api/auth.ts`
- `frontend/src/App.tsx`
- `frontend/src/pages/Index.tsx`
- `frontend/src/components/SideNav.tsx`
- `frontend/scripts/check-newcar-direct-auth.mjs`
- `frontend/scripts/check-newcar-admin-entry-logout-route.mjs`
- `frontend/scripts/check-newcar-admin-permission-e2e.mjs`
- `docs/external-auth-integration.md`
- `docs/ai/05_PROJECT_CONTEXT.md`
- `docs/superpowers/plans/2026-07-20-auto-wechat-admin-switch-logout-implementation-plan.md`
- `docs/superpowers/plans/2026-07-20-auto-wechat-admin-switch-logout-replan-p2.md`
- `docs/superpowers/plans/2026-07-21-auto-wechat-admin-switch-logout-integration-p3.md`。

其中 Git 自动合并后的 `docs/ai/05_PROJECT_CONTEXT.md` 只读核验；实际发生冲突时停止并返回审批窗口，不在 P3 内人工解决。

禁止新增依赖、修改后端鉴权实现、数据库、迁移、环境变量、部署文件、权限码或 `used-car/**`。

## 执行窗口步骤

1. 新窗口启动目录必须精确为 `E:\work\project\auto_wechat\.worktrees\auto-wechat-admin-switch-logout-integration-p3`。先读取项目必读规则和本计划，确认分支为 `plan/auto-wechat-admin-switch-logout-p3`、实际 HEAD 精确等于审批信封中的 Plan-Commit、工作树为空；同时只读核验 Source-Candidate 和 `used-car` 状态。不得创建或切换工作树、分支或目录。
2. 在该计划工作树原地执行：

   ```powershell
   git merge --no-ff 6dfd2f5047c1bdf43750a78fa62d4a0973a7254a -m "合并：管理员切换与退出登录修正"
   ```

   任一冲突立即停止，记录 `git status --short` 和冲突文件，不解决、不提交、不更新 `master`。
3. 合并成功后核对 `git rev-list --parents -n 1 HEAD`：第一父提交必须是 Plan-Commit，第二父提交必须是 Source-Candidate。核对 `git diff --name-only <Plan-Commit>..HEAD` 只能包含允许范围。
4. 对“主线保护”列出的路径执行精确 `git diff --exit-code <Plan-Commit>..HEAD -- <paths>`，必须无差异；原位阅读自动合并后的项目上下文，确认两组事实均存在。
5. 在 `frontend` 依次运行三个 NewCar 合同、生产构建和定向严格 ESLint；在仓库根运行：

   ```powershell
   py -m pytest -q tests/test_newcar_logout.py
   py -m pytest -q tests/test_auth_context.py
   py -m pytest -q tests/test_frontend_capability_navigation.py::test_frontend_app_and_sidenav_consume_feature_aggregation tests/test_env_profile_templates.py::test_frontend_static_checks_read_root_development_template
   git diff --check <Plan-Commit>..HEAD
   ```

6. 清理构建副产物并保证工作树为空，回传完整 `CANDIDATE_READY` 信封：Plan-Commit、Source-Candidate、集成候选完整哈希、双亲、范围、全部命令及退出码、文档核验、残余风险、`used-car` 状态。
7. 执行窗口不得输出 `APPROVE_TEST`、`PASS` 或本地集成批准，不得修改主工作区 `master`，不得推送或发布。审批窗口审查新哈希后再单独发起独立浏览器测试。

## 验收矩阵

- Git：Plan-Commit 的唯一父提交是 Master-Integration-Base；集成候选双亲顺序精确为 Plan-Commit、Source-Candidate；两者均为集成候选祖先；工作树干净；无人工冲突解决。
- 文档：保留当前主线 PostgreSQL / 抖音授权账号事实，同时保留管理员切换和普通退出的 NewCar 鉴权事实。
- 前端：三个 NewCar 合同、生产构建、修改文件严格 ESLint 均通过；`Index.tsx` 不新增 lint 问题。
- 后端：`tests/test_newcar_logout.py`、`tests/test_auth_context.py`、前端能力聚合合同和根环境模板合同通过。
- 主线保护：集成候选相对 Plan-Commit 不得修改 `.dockerignore`、`app/models.py`、`app/routers/douyin_accounts.py`、`app/routers/douyin_live_check.py`、`app/services/douyin_live_check_service.py`、`scripts/seed_dev_data.py`、`tests/test_douyin_authorized_account_pg_upsert.py`、`tests/test_douyin_live_check.py`；使用精确路径的 `git diff --exit-code` 证明内容等价。
- 浏览器：在集成候选精确 detached HEAD 上重跑 1440x900 与 1024x768 的管理员切换、503 提示、普通退出、晚到 401、内存重试、主动重新登录和未抑制 401 矩阵。
- 安全：浏览器直调 NewCar logout 为 0；关键 Bearer 匹配；Runtime 与未知控制台错误为 0；真实 9000、NewCar、19000 均不访问。

## 停止条件

出现任何合并冲突、权限/鉴权语义变化、测试失败或需要扩大允许范围时停止集成并重新裁决，不得直接更新 `master`。
