# 生产发布 Runbook（PROD-RELEASE-AUTOMATION-MINIMAL-1）

> 统一 CLI：`python3 scripts/prod_release.py`（L3 / OWNER=PLATFORM-RELEASE）
> 底层严格（fail-closed），日常操作简单（deploy 默认 dry-run）。
> 本 Runbook 只讲操作；安全 gate 细节见脚本源码与 G0 治理文档。

## 快速开始

```bash
# 1. 查看生产发布事实（只读，安全）
python3 scripts/prod_release.py inspect

# 2. 预览发布 frontend（默认 dry-run，不执行任何变更）
python3 scripts/prod_release.py deploy --service frontend --dry-run

# 3. 确认后执行（Owner 明确输入 --apply）
python3 scripts/prod_release.py deploy --service frontend --apply

# 4. 验证
python3 scripts/prod_release.py verify --service frontend
```

## Inspect（只读）

```bash
python3 scripts/prod_release.py inspect
```

输出：SOURCE_REPO / CURRENT_HEAD / WORKTREE_STATUS / ORIGIN_STATUS / 当前三镜像 / 容器 ID / release identity / DB migration change。

**不执行**：git pull、docker build、compose up、restart、修改 release identity。

## Deploy（单服务，默认 dry-run）

```bash
python3 scripts/prod_release.py deploy --service api [--dry-run|--apply]
python3 scripts/prod_release.py deploy --service douyin-ai-cs [--dry-run|--apply]
python3 scripts/prod_release.py deploy --service frontend [--dry-run|--apply]
```

- 一次只能一个 service（禁止 all / auto / 多服务）。
- 默认 **dry-run**：preflight + 打印安全摘要 + 逐 token 命令预览，不执行任何生产变更。
- `--apply` 才执行单服务 immutable recreate（`--no-deps --no-build`），未更新服务继承当前生产 image identity。
- 硬性 gate（任一失败 → 退出非 0，不执行）：
  - `DIRTY_WORKTREE`：工作树不干净 → BLOCK
  - `ORIGIN_UNREACHABLE` / `NON_FAST_FORWARD`：git 状态不明确或非 ff → BLOCK（只允许 fetch / pull --ff-only）
  - `DB_MIGRATION_DETECTED`：本次发布涉及 `migrations/**` 等 → **BLOCK（MANUAL_DB_RELEASE_GATE_REQUIRED）**
  - `MISSING_RUNTIME_ENV` / `MISSING_PRODUCTION_TREE` / `MISSING_COMPOSE_FILE`：路径缺失 → BLOCK（不创建）
  - `FRONTEND_BUILD_CONFIG_MISSING`（仅 frontend）：生产关键 VITE build 配置为空 → BLOCK
- 禁止逃生参数：无 `--force` / `--skip-checks` / `--ignore-dirty` / `--ignore-db`。

### DB migration 行为

```text
DB_MIGRATION_DETECTED = YES
DEPLOY = BLOCKED
REASON = MANUAL_DB_RELEASE_GATE_REQUIRED
```

绝不自动执行 `alembic upgrade head`；数据库发布单独审批。

## Verify（平台级验证）

```bash
python3 scripts/prod_release.py verify --service api
python3 scripts/prod_release.py verify --service douyin-ai-cs
python3 scripts/prod_release.py verify --service frontend
```

- api：container running / restart count / `/ready` HTTP 200 / `/auth/me` 未认证 401 fail-closed（200 = mock 泄漏失败）/ image identity
- douyin-ai-cs：container running / `/ready` HTTP 200 / image identity
- frontend：container running / 127.0.0.1:5173 reachable / image identity
- 输出 `BUSINESS_ACCEPTANCE = REQUIRED` + G3 提示：**发布关闭前请运行受影响模块 G3 smoke/manual acceptance**（脚本不猜 TASK_OWNER）。
- verify 失败 → `ROLLBACK_RECOMMENDED = YES`，但**不自动回滚**（AUTO_ROLLBACK=NO）。

## Rollback（基于 previous immutable identity）

```bash
python3 scripts/prod_release.py rollback --service api [--dry-run|--apply]
```

- 基于 `/root/.xg-ai-release/` 中 previous release identity 记录（不 git reset / 不重新 build）。
- 无法唯一确定 previous identity → `ROLLBACK = BLOCKED`（不猜测）。
- 默认 dry-run；`--apply` 才执行单服务回滚。

## 路径事实

```text
release identity：/root/.xg-ai-release/<release>.env（非 secret；image/revision 身份键）
runtime env：    /www/wwwroot/XG_AI_System/.env.production.local（脚本绝不写入；secrets 不落 release identity）
compose 树：     /www/wwwroot/XG_AI_System（docker-compose.yml + docker-compose.frontend-prod.yml）
```

## 安全边界

- subprocess 一律 argv 数组化（shell=False），不拼接用户输入形成 shell 命令。
- canonical 命令以逐 token 预览输出（防误粘贴执行）。
- release identity 只保存 image/身份等非 secret 信息；绝不生成/覆盖 production secrets。
- 本 CLI 只做发布机械流程；生产应用本任务未执行（PRODUCTION_APPLY = NOT AUTHORIZED，等待 Owner 单独审批）。
