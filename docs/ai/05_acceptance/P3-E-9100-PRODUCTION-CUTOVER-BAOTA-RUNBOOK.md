# P3-E-9100 生产 PostgreSQL 切换宝塔执行 Runbook

- 编号：P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1
- 文档用途：供人工（执行者 VHwwsf / 回滚 LNZS / 审批 Waston）在宝塔生产服务器按序执行 PostgreSQL 切换
- 固定生产基准：方案 A（一个 PG 实例，两个 database）
  - 9000 主库：`auto_wechat`，Alembic head = `0007_lead_type_widen`
  - 9100 RAG metadata 库：`xg_douyin_ai_cs`，Alembic head = `0002_create_rag_metadata`
  - `RAG_VECTOR_BACKEND=sqlite`，9100 单实例，保留 SQLite 向量副本，排除 Milvus / 全局时区 / 类型重构
- ⚠️ 本 Runbook 由本地（非生产环境）生成，未经生产环境实际执行验证。所有标注 `[宝塔现场确认]` 的值必须在宝塔现场确认后填入。

---

## 0. 角色与职责

| 角色 | 人员 | 职责 |
|------|------|------|
| 审批者 | Waston | 批准切换、持有密码、不在执行现场操作 |
| 执行者 | VHwwsf | 在宝塔按 Runbook 执行脚本，记录输出 |
| 回滚者 | LNZS | 仅在触发回滚时介入，执行 `production_pg_rollback.sh` |
| 密码所有者 | Waston | 提供 PG 密码 / token，不在脚本/日志中明文留存 |

**审批 ≠ 执行**：审批者不得同时是执行者。所有写操作脚本（apply / rollback）强制校验 `--approver != --operator`。

---

## 1. 执行顺序总览

```text
步骤 1-4   前置准备与确认
步骤 5     SQLite 冻结基线快照（before）
步骤 6     preflight 预检查（18 项）
步骤 7     backup 备份（SQLite + PG + .env）
步骤 8     ensure_databases 第二库确认/创建
步骤 9-10  Alembic upgrade（9000 → 0007，9100 → 0002）
步骤 11-12 cutover dry-run（只读，不写数据）
步骤 13-14 cutover apply（写操作，需审批三参数）
步骤 15    切换 .env 至 PostgreSQL（人工编辑）
步骤 16    switch_and_verify 启动 + 就绪检查
步骤 17    smoke 只读业务接口验证
步骤 18    SQLite 冻结对比（before vs after）
步骤 19    收尾、观察期、归档
```

---

## 2. 全局回滚触发条件

出现以下任一情况，**立即停止前进并执行回滚**（步骤详见 §13 / `production_pg_rollback.sh`）：

1. preflight 任意 `[FAIL]`（第 6 步）
2. backup 关键项失败（SQLite 或 .env 备份失败）（第 7 步）
3. Alembic upgrade 失败或未达目标 revision（第 9-10 步）
4. cutover apply 失败或未输出 `APPLY_PASS`（第 13-14 步）
5. switch_and_verify 的 readiness 检查超时（9000/9100 /ready 或 PG health）（第 16 步）
6. smoke 关键端点 `[FAIL]`（第 17 步）
7. SQLite 冻结对比发现元数据 SQLite 增长（存在未切净写入路径）（第 18 步）
8. 任何步骤出现非预期错误且无法现场定位

---

## 步骤 1：确认 Git 提交基线

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  git fetch --all
  git log --oneline -5
  # 确认 HEAD 是 P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 的提交（见本地报告 §1 Git 基线）
  git rev-parse HEAD
  ```
- **成功标准**：HEAD commit 与本地报告记录的 Git 基线一致
- **失败停止**：HEAD 不一致 → 停止，确认 `git pull` 是否成功
- **日志**：`/tmp/step01_git.log`
- **回滚触发**：无（只读）

## 步骤 2：SSH 登录宝塔

- **执行者**：VHwwsf
- **操作**：通过宝塔面板或 SSH 登录生产服务器
- **成功标准**：能执行 `docker ps`、`docker compose version`、`psql --version`
- **失败停止**：无法登录或工具缺失 → 停止，联系运维
- **日志**：无
- **回滚触发**：无

## 步骤 3：拉取代码到目标提交

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  git status                          # 确认无未提交改动
  git pull origin master              # 拉取含本发布包的提交
  git log --oneline -1
  ```
- **成功标准**：`git log` 显示 P3-E-9100-PRODUCTION-RELEASE-PACKAGE-1 提交
- **失败停止**：`git status` 有未提交改动 → 停止，确认是否生产本地临时改动；`git pull` 冲突 → 停止
- **日志**：`/tmp/step03_pull.log`
- **回滚触发**：无

## 步骤 4：确认 .env 当前是 SQLite 配置（切换前）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  grep -E "^(DATABASE_URL|RAG_DATABASE_URL|APP_ENV)=" .env
  # 预期：DATABASE_URL / RAG_DATABASE_URL 为 sqlite:// 或未设；APP_ENV=production
  ```
- **成功标准**：`DATABASE_URL` 不是 `postgresql://`（确认当前确为 SQLite，待切换）
- **失败停止**：`DATABASE_URL` 已是 postgresql → 停止，确认是否已部分切换
- **日志**：`/tmp/step04_env_before.log`（**注意：grep 输出可能含密码，日志需脱敏后留存**）
- **回滚触发**：无

## 步骤 5：SQLite 冻结基线快照（before）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_sqlite_freeze_check.sh \
    --snapshot /tmp/freeze_before.json
  ```
- **成功标准**：输出 `[OK] 快照已写入：/tmp/freeze_before.json`，JSON 含 9000/9100 SQLite size + 关键表行数
- **失败停止**：SQLite 文件不存在或无法读取 → 停止，确认 `docker-data/` 路径
- **日志**：`/tmp/step05_freeze_before.log`
- **回滚触发**：无（只读）

## 步骤 6：preflight 预检查（18 项）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_preflight.sh \
    --project-root "$(pwd)" --env-file .env 2>&1 | tee /tmp/step06_preflight.log
  ```
- **成功标准**：所有 18 项检查无 `[FAIL]`（`[WARN]` 需人工评估是否阻塞）
- **失败停止**：任意 `[FAIL]` → 停止，修复后重跑
- **日志**：`/tmp/step06_preflight.log`
- **回滚触发**：是（preflight FAIL）

## 步骤 7：backup 备份

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  export PROD_CUTOVER_OPERATOR=VHwwsf PROD_CUTOVER_TICKET=[宝塔现场确认单号]
  bash scripts/production_pg_backup.sh 2>&1 | tee /tmp/step07_backup.log
  echo "BACKUP_DIR:"; grep -oE 'backups/cutover-[0-9-]+' /tmp/step07_backup.log | tail -1
  ```
- **成功标准**：输出 `BACKUP_DONE`；`MANIFEST.txt` 含 9000/9100 SQLite + .env + PG dump 路径与 SHA-256
- **失败停止**：SQLite 源备份失败或 .env 备份失败 → 停止，回滚（无需切回，备份前未改数据）
- **日志**：`/tmp/step07_backup.log` + `backups/cutover-YYYYMMDD-HHMMSS/MANIFEST.txt`
- **回滚触发**：关键备份失败
- **⚠️ 提示**：备份目录含 .env（密码）和 PG dump，建议加密后存外部安全存储

## 步骤 8：ensure_databases 第二库确认

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  # 只读检查
  bash scripts/production_pg_ensure_databases.sh 2>&1 | tee /tmp/step08_ensure_check.log
  # 若 9100 第二库缺失，显式创建（需审批确认）：
  # bash scripts/production_pg_ensure_databases.sh --create --yes 2>&1 | tee /tmp/step08_ensure_create.log
  ```
- **成功标准**：9000 库 `已存在`；9100 库 `已存在` 或显式 `--create` 创建成功
- **失败停止**：9000 库缺失且无法创建 → 停止（POSTGRES_DB 应已自动建）
- **日志**：`/tmp/step08_ensure_*.log`
- **回滚触发**：创建失败（无数据损坏，可停止）

## 步骤 9：Alembic upgrade 9000（→ 0007_lead_type_widen）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_alembic_upgrade.sh --service 9000 2>&1 | tee /tmp/step09_alembic_9000.log
  ```
- **成功标准**：`[PASS] 9000 达 0007_lead_type_widen` + `ALEMBIC_UPGRADE_DONE`
- **失败停止**：upgrade 失败或未达目标 → 停止，**触发回滚**（Alembic 部分升级需评估）
- **日志**：`/tmp/step09_alembic_9000.log`
- **回滚触发**：是

## 步骤 10：Alembic upgrade 9100（→ 0002_create_rag_metadata）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_alembic_upgrade.sh --service 9100 2>&1 | tee /tmp/step10_alembic_9100.log
  ```
- **成功标准**：`[PASS] 9100 达 0002_create_rag_metadata` + `ALEMBIC_UPGRADE_DONE`
- **失败停止**：同步骤 9
- **日志**：`/tmp/step10_alembic_9100.log`
- **回滚触发**：是

## 步骤 11：cutover dry-run 9000（只读）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_cutover_dry_run.sh --service 9000 2>&1 | tee /tmp/step11_dryrun_9000.log
  ```
- **成功标准**：日志含 `DRY_RUN_PASS` + `DRY_RUN_ALL_DONE`
- **失败停止**：dry-run 未输出 `DRY_RUN_PASS` → 停止，检查表级 insert/update/skip/error 统计
- **日志**：`/tmp/step11_dryrun_9000.log`（**含 dry-run 统计，提交给审批者审阅**）
- **回滚触发**：dry-run 失败（尚未写数据，可停止）

## 步骤 12：cutover dry-run 9100（只读）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_cutover_dry_run.sh --service 9100 2>&1 | tee /tmp/step12_dryrun_9100.log
  ```
- **成功标准**：日志含 `DRY_RUN_PASS` + `DRY_RUN_ALL_DONE`
- **失败停止**：同步骤 11
- **日志**：`/tmp/step12_dryrun_9100.log`
- **回滚触发**：dry-run 失败

## 步骤 13：cutover apply 9000（写操作，需审批）

- **执行者**：VHwwsf（执行）+ Waston（审批，现场或离线确认）
- **前置**：审批者 Waston 审阅步骤 7 备份 MANIFEST + 步骤 11 dry-run 统计，批准单号 `[宝塔现场确认单号]`
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  BACKUP_DIR=$(grep -oE 'backups/cutover-[0-9-]+' /tmp/step07_backup.log | tail -1)
  bash scripts/production_pg_cutover_apply.sh \
    --approver Waston --operator VHwwsf \
    --ticket [宝塔现场确认单号] \
    --backup-dir "$BACKUP_DIR" \
    --dry-run-log /tmp/step11_dryrun_9000.log \
    --service 9000 2>&1 | tee /tmp/step13_apply_9000.log
  ```
- **成功标准**：`[PASS] 9000 apply 成功` + `APPLY_ALL_DONE`
- **失败停止**：未输出 `APPLY_PASS` → 停止，**触发回滚**
- **日志**：`/tmp/step13_apply_9000.log` + `markers/cutover_apply_audit_*.log`
- **回滚触发**：是

## 步骤 14：cutover apply 9100（写操作，需审批）

- **执行者**：VHwwsf（执行）+ Waston（审批）
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  BACKUP_DIR=$(grep -oE 'backups/cutover-[0-9-]+' /tmp/step07_backup.log | tail -1)
  bash scripts/production_pg_cutover_apply.sh \
    --approver Waston --operator VHwwsf \
    --ticket [宝塔现场确认单号] \
    --backup-dir "$BACKUP_DIR" \
    --dry-run-log /tmp/step12_dryrun_9100.log \
    --service 9100 2>&1 | tee /tmp/step14_apply_9100.log
  ```
- **成功标准**：`[PASS] 9100 apply 成功` + `APPLY_ALL_DONE`
- **失败停止**：未输出 `APPLY_PASS` → 停止，**触发回滚**（9000 已切，9100 未切，需评估）
- **日志**：`/tmp/step14_apply_9100.log` + `markers/cutover_apply_audit_*.log`
- **回滚触发**：是

## 步骤 15：切换 .env 至 PostgreSQL（人工编辑）

- **执行者**：VHwwsf（编辑）+ Waston（提供密码）
- **操作**：人工编辑 `.env`，设置以下变量（参考 `.env.production.pg.example`）：
  ```bash
  APP_ENV=production
  DATABASE_URL=postgresql://[宝塔现场确认PG_USER]:[宝塔现场确认PG密码]@postgres:5432/auto_wechat
  RAG_DATABASE_URL=postgresql://[宝塔现场确认PG_USER]:[宝塔现场确认PG密码]@postgres:5432/xg_douyin_ai_cs
  EXPECTED_DATABASE_NAME=auto_wechat
  RAG_EXPECTED_DATABASE_NAME=xg_douyin_ai_cs
  RAG_VECTOR_BACKEND=sqlite
  ```
- **成功标准**：`.env` 含上述变量；`grep DATABASE_URL .env` 显示 `postgresql://`
- **失败停止**：密码错误或变量缺失 → 停止，不启动容器
- **日志**：无（.env 不打印到日志）
- **回滚触发**：无（配置改动，下一步验证）
- **⚠️ 安全**：`.env` 改动前已在步骤 7 备份；编辑后不 echo 明文密码

## 步骤 16：switch_and_verify 启动 + 就绪检查

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_switch_and_verify.sh 2>&1 | tee /tmp/step16_switch.log
  ```
- **成功标准**：
  - `APP_ENV=production` PASS
  - `DATABASE_URL` / `RAG_DATABASE_URL` 均为 `postgresql://`
  - 两库名不同
  - `compose config` PASS
  - PostgreSQL healthy
  - 9000 `/health` + `/ready` PASS
  - 9100 `/health` + `/ready` PASS
  - frontend PASS
  - 输出 `SWITCH_AND_VERIFY_DONE`
- **失败停止**：任一 readiness 超时 → **触发回滚**
- **日志**：`/tmp/step16_switch.log`
- **回滚触发**：是

## 步骤 17：smoke 只读业务接口验证

- **执行者**：VHwwsf（+ Waston 提供 token）
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  bash scripts/production_pg_smoke.sh \
    --token "[宝塔现场确认JWT]" 2>&1 | tee /tmp/step17_smoke.log
  ```
- **成功标准**：`SMOKE_DONE`，`FAIL=0`（`WARN` 项为权限/路径差异，现场确认）
- **失败停止**：`FAIL > 0` → 评估是否触发回滚
- **日志**：`/tmp/step17_smoke.log`
- **回滚触发**：关键端点（leads / staff / rag-documents）FAIL → 回滚
- **⚠️ 安全**：token 仅通过参数传入，不写入日志

## 步骤 18：SQLite 冻结对比（before vs after）

- **执行者**：VHwwsf
- **命令**：
  ```bash
  cd [宝塔项目根目录]
  # 先拍 after 快照（切换后、运行一段时间后）
  bash scripts/production_pg_sqlite_freeze_check.sh \
    --snapshot /tmp/freeze_after.json 2>&1 | tee /tmp/step18_freeze_after.log
  # 对比
  bash scripts/production_pg_sqlite_freeze_check.sh \
    --compare /tmp/freeze_before.json /tmp/freeze_after.json 2>&1 | tee /tmp/step18_freeze_compare.log
  ```
- **成功标准**：`FREEZE_CHECK_DONE`；元数据 SQLite size/行数未增长（向量副本可增长，记 INFO）
- **失败停止**：元数据 SQLite 增长 → **触发回滚**（存在未切净写入路径）
- **日志**：`/tmp/step18_freeze_*.log`
- **回滚触发**：是（元数据增长）

## 步骤 19：收尾、观察期、归档

- **执行者**：VHwwsf
- **操作**：
  1. 确认步骤 1-18 全部 PASS
  2. 收集 `/tmp/step*.log` + `markers/*.log` + `backups/cutover-*/MANIFEST.txt`，归档到安全存储
  3. 进入观察期（建议 24-48 小时）：
     - 监控 9000/9100 /ready 健康
     - 监控元数据 SQLite 是否仍冻结
     - 监控业务接口可用性
  4. 观察期结束，确认无异常后，通知审批者切换稳定
- **成功标准**：归档完成；观察期无回滚事件
- **失败停止**：观察期内触发回滚条件 → 执行回滚
- **日志**：归档目录
- **回滚触发**：观察期内任意回滚条件

---

## 3. 回滚执行（由 LNZS 执行）

当 §2 任一触发条件满足时，回滚者 LNZS 介入：

```bash
cd [宝塔项目根目录]
# 1. 先打印回滚计划
bash scripts/production_pg_rollback.sh

# 2. 审批者 Waston 确认回滚后，执行
bash scripts/production_pg_rollback.sh \
  --execute \
  --approver Waston --operator LNZS \
  --reason "[宝塔现场填写回滚原因，如：step16 ready 超时]" \
  --ticket [宝塔现场确认单号] \
  --backup-dir backups/cutover-[宝塔现场确认TS] 2>&1 | tee /tmp/rollback.log
```

**回滚效果**：
- `.env` 中 `DATABASE_URL` / `RAG_DATABASE_URL` 被注释，9000/9100 回退读 SQLite
- 容器重启，/ready 恢复
- **PG volume 不删除**，切换期间写入 PG 的新数据保留
- **原始 SQLite 不覆盖**（cutover 未改 SQLite，回滚后读切换前状态）

**⚠️ 数据补偿**：切换期间（cutover apply → 回滚）写入 PG 的新数据（新线索/会话/检测记录）需人工从 PG 导出增量评估，不自动同步回 SQLite。补偿方式 `[宝塔现场确认]`。

---

## 4. 待宝塔现场确认的参数清单

以下值在本地无法确认，必须宝塔现场填入：

| 参数 | 用途 | 确认方 |
|------|------|--------|
| `[宝塔项目根目录]` | 所有脚本 `cd` 目标 | VHwwsf |
| `[宝塔现场确认单号]` | 审批单号，写入审计日志 | Waston |
| `[宝塔现场确认PG_USER]` | PostgreSQL 用户名 | Waston |
| `[宝塔现场确认PG密码]` | PostgreSQL 密码（写入 .env，不进日志） | Waston |
| `[宝塔现场确认JWT]` | smoke 测试 token | Waston |
| `[宝塔现场确认TS]` | 回滚时 backup-dir 时间戳 | LNZS |
| `[宝塔现场填写回滚原因]` | rollback --reason | LNZS |
| `[宝塔项目根目录]` 路径下 `docker-data/` 布局 | SQLite 路径默认值校验 | VHwwsf |

---

## 5. 脚本清单与安全门

| 脚本 | 默认行为 | 写操作 | 安全门 |
|------|---------|--------|--------|
| `production_pg_preflight.sh` | 只读 18 项检查 | 否 | FAIL 退出非零 |
| `production_pg_backup.sh` | 备份到 `backups/` | 是（备份） | SQLite/.env 缺失 FAIL |
| `production_pg_ensure_databases.sh` | 只读检查 | 否（需 `--create --yes`） | 双参数确认 |
| `production_pg_alembic_upgrade.sh` | Alembic upgrade head | 是（DDL） | 目标 revision 校验 |
| `production_pg_cutover_dry_run.sh` | 只读 dry-run | 否 | 校验 DRY_RUN_PASS |
| `production_pg_cutover_apply.sh` | 默认拒绝（打印计划） | 是（数据迁移） | 8 道安全门（见脚本头注释） |
| `production_pg_switch_and_verify.sh` | 启动+健康检查 | 是（容器重启） | readiness FAIL 退出非零；不删 volume/SQLite |
| `production_pg_smoke.sh` | 只读 GET + search-preview | 否 | 禁止端点自检；FAIL 退出非零 |
| `production_pg_sqlite_freeze_check.sh` | 快照/对比 | 否 | 元数据增长 FAIL |
| `production_pg_rollback.sh` | 默认拒绝（打印计划） | 是（改 .env+重启） | 需 `--execute`+审批≠执行 |

---

## 6. 本地验证结论（详见本地报告 §15）

本 Runbook 配套的 10 个脚本已在本地完成：
- bash 语法检查全部通过
- 默认拒绝脚本（apply / rollback / ensure_databases `--create`）无参数时均只打印计划、退出 0
- 脱敏检查：所有脚本 URL 输出经 `mask_url` 脱敏，不打印明文密码
- 禁止端点自检：smoke 脚本不含真实发送/计费端点
- Alembic 配置校验：两套 `alembic.ini` 存在，目标 revision 与基线一致

**本地验证不等于生产验证**。生产执行必须由 VHwwsf 按本 Runbook 逐步操作，Waston 审批，LNZS 待命回滚。
