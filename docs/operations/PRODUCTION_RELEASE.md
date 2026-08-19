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
DB_MIGRATION_ATTESTATION = MISSING_OR_INVALID
DEPLOY = BLOCKED
REASON = MANUAL_DB_RELEASE_GATE_REQUIRED
```

绝不自动执行 `alembic upgrade head`；数据库发布单独审批。

数据库迁移完成后，必须由独立数据库执行流程生成与目标 `SOURCE_SHA` 精确绑定的证明文件：

```text
/root/.xg-ai-release/db-attestations/<full-source-sha>-<utc>.json
```

证明至少包含：`status=VERIFIED`、目标 API 镜像及 digest、9000/9100 数据库
expected/actual revision、迁移清单摘要、备份引用与校验值、执行/验证时间和操作人。
证明不得包含数据库 URL、密码或 token。

只有在证明源码为当前 `HEAD`，或为当前 `HEAD` 的祖先且两者之间无新增迁移，且证明自身的目标 API
镜像与证明源码匹配、数据库 revision 内部一致时，
`DB_MIGRATION_ATTESTATION = PASS` 才能放行下一阶段；迁移提交存在时必须先发布 `api`，
禁止 frontend/9100 抢先发布。若同一 `SOURCE_SHA` 的 API 已发布后才完成经审批的 9100
迁移，发布脚本必须以该 SHA 的最新有效证明刷新两个 expected revision，再发布 9100；
不得继承旧 release identity 的过期 revision。正式 release identity 由发布脚本生成，禁止人工编辑；
生成内容必须包含：

```text
AUTO_WECHAT_API_EXPECTED_REVISION
XG_DOUYIN_AI_CS_EXPECTED_REVISION
```

数据库迁移失败或服务发布失败时，优先使用已验证备份恢复；不得把 Alembic downgrade
当作本批生产回滚方案。

## Verify（平台级验证）

```bash
python3 scripts/prod_release.py verify --service api
python3 scripts/prod_release.py verify --service douyin-ai-cs
python3 scripts/prod_release.py verify --service frontend
```

- 容器识别（R2.2）：优先实际生产容器名 `container_name`（如 `xg-auto-wechat-frontend`），回退 compose service 名（dev 环境）；两处都查不到 → `CONTAINER_NOT_FOUND`（fail-closed）。
- 镜像 identity（R2.1/R2.2）：`docker inspect <container> --format {{.Config.Image}}` 与最新有效 release identity 严格字符串比较（禁止前缀/缩写/自动补 repository）；真正不同 → `IDENTITY_MISMATCH`（fail-closed）。
- api：container running（`.State.Status`）/ `/ready` HTTP 200 / `/auth/me` 未认证 401 fail-closed（200 = mock 泄漏失败）/ image identity
- douyin-ai-cs：container running / `/ready` HTTP 200 / image identity
- frontend：container running / 127.0.0.1:5173 HTTP 200（不可达或非 200 均 → `READY_FAILED`，fail-closed）/ image identity
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
