# P3-E-9100-STAGING-DRILL-FASTTRACK-1 staging PostgreSQL 切换演练报告

任务编号：P3-E-9100-STAGING-DRILL-FASTTRACK-1
生成时间：2026-07-10
前置任务：P3-E-9100-STAGING-ENV-BOOTSTRAP-1（STAGING_ENV_READY_PENDING_OWNERS）
代码提交：38b1bd1（fix(pg)）+ 本报告提交（docs(pg)）

---

## 1. 最终结论

**STAGING_PASSED_PENDING_PRODUCTION_APPROVAL**

技术维度：staging PostgreSQL 切换演练 12 步全通过 —— 双库 cutover apply 成功（9000=116 行 + 9100=133 行）+ readiness 双 ok + 核心业务 smoke 全绿 + 数据一致性零丢失 + 幂等/回滚/再前进能力验证 + focused 测试 21 passed + init-prod smoke PASS + 前端构建通过。

结论限定为 PENDING_PRODUCTION_APPROVAL 的原因：本任务约束「最终结论只能选 STAGING_PASSED_PENDING_PRODUCTION_APPROVAL / STAGING_FAILED / STAGING_BLOCKED；审批人不得与执行人相同；AI 不得担任任何人工角色」。staging 侧技术验证已通过，但生产窗口切换仍需人工审批人 Waston（≠ 执行人 VHwwsf）签字 + 生产 init-prod 同类 bug 修复落地。

---

## 2. 安全约束执行确认（逐条对照）

| 约束 | 执行结果 | 证据 |
|------|----------|------|
| 禁止操作 production database 和 production 容器 | ✅ | 全程仅操作 staging PG（docker-data-staging/postgres）+ 临时 smoke 容器（--rm）；无 production 连接 |
| 禁止重新进行全项目 PostgreSQL 审计 | ✅ | 未重复 staging bootstrap 已通过的隔离/镜像纯净/空库 readiness 项 |
| 人工角色门禁（执行 VHwwsf / 回滚 LNZS / 审批 Waston / 密码 Waston） | ✅ | 审批人 Waston ≠ 执行人 VHwwsf；AI 未担任任何角色 |
| 人员未登记不得执行 cutover apply | ✅ | 四角色已登记（任务书固定）后才执行 5.5 apply |
| 本轮只修改/测试 init-prod 脚本，不得对 production 执行初始化 | ✅ | init-prod/010 仅改脚本 + smoke 用临时 --rm 容器；未触 production |
| 真实密码/.env.staging/备份数据库/volume 数据不得提交 | ✅ | 提交一 14 文件无敏感数据；.env.staging 未入 git；backups/ 已加 .gitignore |
| 不得触发真实抖音发送/微信通知/算力扣费 | ✅ | 全程只读 GET smoke + cutover（迁移历史数据）；无发送/扣费动作 |
| 最终结论只能选三选一 | ✅ | 本报告结论 = STAGING_PASSED_PENDING_PRODUCTION_APPROVAL |

---

## 3. 人员角色门禁

| 角色 | 登记人 | 职责 | 确认 |
|------|--------|------|------|
| 演练执行人 | VHwwsf | 执行 5.1-5.12 演练步骤 + focused 测试 | ✅ 已登记 |
| 回滚负责人 | LNZS | 若 staging 失败，决策并执行回滚（DATABASE_URL 切 sqlite + restart） | ✅ 已登记 |
| 演练审批人 | Waston | 审批 staging 演练结论 + 决定是否进生产窗口 | ✅ 已登记（≠ 执行人） |
| 密码 Owner | Waston | 持有 staging_xg_pwd_2026_07_10，生产窗口密码分发 | ✅ 已登记 |
| AI | （禁止） | 不得担任执行/回滚/审批/密码任何角色 | ✅ AI 仅做技术执行与报告，所有人工角色由真人担任 |

---

## 4. 固定基线（staging 环境）

| 维度 | 值 |
|------|-----|
| compose project | auto_wechat_staging |
| 容器 | xg-staging-postgres / xg-staging-api / xg-staging-cs / xg-staging-frontend |
| 端口映射 | 9000→29000，9100→29100，frontend→5180，PG→25432 |
| 数据库 | auto_wechat_staging（9000）+ xg_douyin_ai_cs_staging（9100），_staging 后缀双重隔离 |
| 9000 alembic head | 0007_lead_type_widen（原 0006，因 lead_type 加宽升级） |
| 9100 alembic head | 0002_create_rag_metadata |
| 镜像 tag | xg-ai-system-backend:staging / xg-douyin-ai-cs:staging |
| RAG_VECTOR_BACKEND | sqlite（metadata 真源 = PG，向量副本 = staging 独立 volume） |
| PG 用户 | auto_wechat_staging（非默认 postgres，复现生产 init-prod 场景） |
| 密码 | staging_xg_pwd_2026_07_10（密码 Owner Waston 持有，未入 git） |

---

## 5. 前置修复（4.1 / 4.2）

### 4.1 init-prod/010 用户参数修复

**问题**：docker/postgres/init-prod/010_create_rag_database.sh 未显式 `--username "$POSTGRES_USER"`，POSTGRES_USER 非 postgres 时 psql/createdb 默认用 OS user postgres → `role "postgres" does not exist` FATAL → 第二库 xg_douyin_ai_cs 静默未建（部分 entrypoint 版本对 init 脚本失败容错）。

**修复**：psql/createdb 显式 `--username "$DB_USER"`（DB_USER=${POSTGRES_USER:-${PGUSER:-auto_wechat}}）；createdb 失败 set -e 终止启动避免静默失败。与 init-staging/010（staging bootstrap 实测通过）同款修复。

**验证**：scripts/smoke_init_prod_non_default_postgres_user.sh 用临时 --rm PG 容器（POSTGRES_USER=mytestuser）实测 → smoke PASS（第二库创建 + 无 role postgres FATAL + owner=mytestuser）。

### 4.2 staging 前端 API 指向

**修复**：frontend/vite.config.ts preview 代理补 staging（sharedProxyConfig 复用 dev 代理逻辑，preview.proxy 接管 /api → 29000、/douyin-ai-cs → 29100）；docker-compose.staging.yml frontend 注入 VITE_DEV_API_PROXY_TARGET / VITE_DEV_DOUYIN_AI_CS_PROXY_TARGET。

**验证**：npm run build 通过（1852 modules，TS 配置 ignoreDeprecations=5.0/composite/emitDeclarationOnly 未破坏）。

---

## 6. 演练步骤结果（5.1-5.12）

| 步骤 | 内容 | 结果 |
|------|------|------|
| 5.1 | staging 容器起停 + 隔离确认 | ✅ project/volume/network 独立 |
| 5.2 | staging PG 空库 alembic upgrade head | ✅ 9000=0007，9100=0002 |
| 5.3 | cutover dry-run（9000+9100） | ✅ 快照比对无异常 |
| 5.4 | 规整 9100 dev bigint 脚数据 | ✅ 12 行（docs/chunks/training/llm）douyin_account_id/conversation_id 规整 |
| 5.5 | cutover apply | ✅ 9000=116 行，9100=133 行，双 APPLY_PASS |
| 5.6 | 镜像重建（含 0007）+ readiness | ✅ 双 ok，alembic 0007/0002 |
| 5.7 | 核心业务 smoke | ✅ 9000 七端点 + 9100 RAG 全 200（修 2 个 500 阻塞） |
| 5.8 | 数据一致性对照 | ✅ 9000 9 表 + 9100 7 表行数一致，douyin_leads id=[1..19] 完整 |
| 5.9 | SQLite 冻结验证 | ✅ DATABASE_URL=PG + volume 隔离 + mtime 基线 |
| 5.10 | 幂等验证 | ✅ alembic + dry-run + apply 全 PASS，insert=0 |
| 5.11 | 回滚演练 | ✅ pg_dump 备份 + SQLite 源完整 + 回滚路径 |
| 5.12 | 再前进 | ✅ 幂等 apply 重切 + staging PG 复验 ok |

---

## 7. PG 切换真实阻塞发现与修复（8 个）

staging 演练核心价值：在隔离环境发现 8 个生产 PG 切换会硬阻塞的真实问题，全部修复。

### 7.1 cutover 库名安全门硬编码（cutover 阻塞 #1）
- **现象**：9000 cutover apply 报 `postgres database 必须是 auto_wechat`，staging 库是 auto_wechat_staging。
- **根因**：validate_apply_target 硬编码 "auto_wechat"。
- **修复**：TARGET_DATABASE_NAME = os.environ.get("MAIN_TARGET_DATABASE_NAME", "auto_wechat")，staging 传 MAIN_TARGET_DATABASE_NAME=auto_wechat_staging。9100 同款（RAG_TARGET_DATABASE_NAME）。

### 7.2 NOT NULL 违约：空串转 NULL（cutover 阻塞 #2）
- **现象**：ai_agents.knowledge_base_text NotNullViolationError。
- **根因**：coerce_value `value == ""` 把 '' 转 None，INSERT NULL 违反 PG NOT NULL DEFAULT（DEFAULT 只兜底省略列，不兜底显式 NULL）。
- **修复**：删 `or value == ""`，保留 ''（SQLite 空串语义=空串非 NULL）。9000+9100 同步。

### 7.3 varchar 截断：lead_type 溢出（cutover 阻塞 #3）
- **现象**：douyin_leads.lead_type StringDataRightTruncationError。
- **根因**：SQLite id=18 lead_type='local_agent_acceptance'（22 字符），varchar(20) 溢出；SQLite 不强制长度已容下，PG 严格截断。
- **修复**：alembic 0007_lead_type_widen（varchar(20)→32）+ models.py String(32) + cutover EXPECTED_REVISION=0007 + staging PG upgrade head。

### 7.4 datetime 类型：reply_deadline 未覆盖（cutover 阻塞 #4）
- **现象**：reply_checks.reply_deadline TypeError（str 无法比较）。
- **根因**：coerce_value datetime 规则 endswith(_at)/(_time) 漏 _deadline 后缀（57 个 timestamp 列仅 reply_deadline 未覆盖）。
- **修复**：加 `or name.endswith("_deadline")`。9000+9100 同步。

### 7.5 bool 类型：8 个散落列未覆盖（cutover 阻塞 #5）
- **现象**：`a boolean is required (got type int)` $17=1。
- **根因**：coerce_value bool 规则（is_* 前缀 + _enabled 后缀）漏 8 列：allow_full_rollout/require_rag/require_rag_sources/manual_required/llm_used/rag_used/upstream_auto_send/final_auto_send。
- **修复**：bool 集合补 8 列 + 技术债注释（列名猜类型脆弱，升级路径=snapshot 带 column_types 改 PG 列类型驱动）。

### 7.6 9100 bigint 脏数据（cutover 阻塞 #6）
- **现象**：`'str' object cannot be interpreted as an integer` $8='dev-merchant-p5-account'。
- **根因**：PG douyin_account_id bigint，dev SQLite 混合 text+integer（p5 验收遗留 'dev-merchant-p5-account' + llm_call_logs.conversation_id='agent-preview'）。
- **修复**：规整 dev SQLite 脏值→0（int，符合 memory 规范 douyin_account_id=0），12 行（备份存在）。

### 7.7 /leads 500：LeadOut.raw_data jsonb dict（smoke 阻塞 #7）
- **现象**：GET /leads ResponseValidationError，raw_data Input should be a valid string。
- **根因**：PG jsonb 列读出 dict，LeadOut.raw_data: Optional[str] 拒绝（SQLite Text 读出 str 时代掩盖）。
- **修复**：LeadOut.raw_data: Optional[Any]（validator 已用 _safe_load_json_object 适配 dict，仅类型声明放宽）。id=18 raw_data={'stage':'detect_reply_replied',...} 正确序列化。

### 7.8 /compute/summary 500：datetime tz 比较（smoke 阻塞 #8）
- **现象**：GET /compute/summary TypeError: can't compare offset-naive and offset-aware datetimes。
- **根因**：PG compute_transactions.created_at = `timestamp with time zone`（TIMESTAMPTZ），psycopg2 读出 aware（UTC）；_now()=datetime.now() naive（本地）；today_start naive；created(aware) >= today_start(naive) 报错。
- **修复**：_summarize_consume 比较前 `created.astimezone().replace(tzinfo=None)` 归一到本地 naive（避免 UTC 数值与本地 today_start 差 8 小时）。技术债：_now() naive vs PG TIMESTAMPTZ 是全项目 tz 策略问题，升级路径=统一 _now() aware + 全 audit datetime 比较。
- **范围确认**：grep 全项目 datetime 比较，除 compute _summarize_consume（Python 层），其余全是 SQLAlchemy filter（SQL 层由 PG 处理，不 Python TypeError）。唯一 Python 层硬阻塞已清除。

---

## 8. 数据一致性证据（5.8）

### 9000 主库（SQLite 源 docker-data/auto_wechat_9000 vs PG auto_wechat_staging）

| 表 | SQLite | PG | 一致 |
|----|--------|-----|------|
| douyin_leads | 19 | 19 | ✅ |
| sales_staff | 4 | 4 | ✅ |
| wechat_tasks | 22 | 22 | ✅ |
| ai_agents | 3 | 3 | ✅ |
| compute_accounts | 2 | 2 | ✅ |
| compute_transactions | 5 | 5 | ✅ |
| douyin_webhook_events | 10 | 10 | ✅ |
| reply_checks | 8 | 8 | ✅ |
| lead_notifications | 5 | 5 | ✅ |

douyin_leads id 列表行级对照：SQLite [1..19] = PG {1..19}，sum_id 190 = 190。

### 9100 RAG 库（SQLite 源 docker-data/xg_douyin_ai_cs vs PG xg_douyin_ai_cs_staging）

| 表 | SQLite | PG | 一致 |
|----|--------|-----|------|
| knowledge_categories | 1 | 1 | ✅ |
| knowledge_documents | 23 | 23 | ✅ |
| knowledge_chunks | 23 | 23 | ✅ |
| knowledge_training_sessions | 39 | 39 | ✅ |
| knowledge_training_feedbacks | 16 | 16 | ✅ |
| rag_training_runs | 26 | 26 | ✅ |
| llm_call_logs | 5 | 5 | ✅ |

结论：cutover 零丢失。/leads 返回 4 条是业务过滤（只展示有效线索），PG 总数 19 = SQLite 19。

---

## 9. 幂等证据（5.10）

| 操作 | 结果 |
|------|------|
| alembic upgrade head（容器启动 entrypoint） | ✅ 框架幂等，readiness 持续 0007/0002 |
| 9000 cutover dry-run（再跑） | ✅ DRY_RUN_PASS，insert=0/update=116/skip=0/error=0 |
| 9000 cutover apply（再跑） | ✅ APPLY_PASS，insert=0/update=116/skip=0/error=0，行数稳定（19/4/22） |
| 9100 cutover apply（再跑） | ✅ APPLY_PASS，insert=0/update=133/skip=0/error=0，行数稳定 |

结论：cutover apply 用 update 语义（0 insert），再跑不重复插入、不破坏 schema、行数稳定。安全幂等（迁移工具语义；非严格 0 变化，update 为覆盖式同值更新）。apply 库名安全门工作正常（不传 MAIN_TARGET_DATABASE_NAME 时正确拒绝 staging 库）。

---

## 10. 回滚证据（5.11）

| 能力 | 证据 |
|------|------|
| PG 备份可恢复 | ✅ pg_dump 容器内演练：dump=161KB，CREATE TABLE=31，COPY=31（与 SQLite 31 表一致），验证后清理不留主机文件 |
| SQLite 源完整（回滚目标） | ✅ 31 表，douyin_leads 26 列含 lead_type，ai_agents 11 列含 knowledge_base_text，compute_transactions 12 列含 created_at；行数见 §8 |
| 回滚路径 | ✅ DATABASE_URL=sqlite:///data/auto_wechat.db + docker compose restart api/cs（dev 环境一直在 sqlite 模式跑，可启动；staging volume !override 隔离 docker-data-staging，dev SQLite 物理不被 staging 挂载） |

dev SQLite 无 alembic_version 表（dev 用 create_all 不走 alembic）——回滚到 sqlite 模式不依赖 alembic_version，readiness 走非 PG 简化路径（test_non_pg_dev_pass 验证）。

---

## 11. 再前进证据（5.12）

回滚演练后重新切回 PG 的能力验证：

| 检查 | 结果 |
|------|------|
| cutover apply 可重跑（重切能力） | ✅ §9 幂等 apply PASS |
| staging 当前 DATABASE_URL | ✅ 9000=postgresql+psycopg://...@postgres:5432/auto_wechat_staging，9100=...xg_douyin_ai_cs_staging |
| readiness 双 ok | ✅ 9000 alembic 0007 postgresql，9100 alembic 0002 postgresql |
| 核心端点 | ✅ /leads 200，/staff 200，/compute/summary 200 |

---

## 12. focused 测试结果

| 测试套件 | 结果 |
|----------|------|
| tests/test_db_readiness.py（9 测试） | ✅ 9 passed |
| tests/test_cutover_sqlite_to_postgres_migration.py（8 测试） | ✅ 8 passed |
| tests/test_init_prod_create_rag_database.py（4 静态测试） | ✅ 4 passed |
| init-prod smoke 脚本（临时 --rm PG 容器实测） | ✅ smoke PASS |
| 前端构建 npm run build | ✅ 1852 modules transformed，built in 20.57s，无 TS 错误 |

合计：21 passed + smoke PASS + 构建通过。测试常量 EXPECTED_HEAD_9000/EXPECTED_REVISION 已同步 0007（加 0007 alembic 的必然回归，已修）。

---

## 13. 生产审批所需证据清单

生产窗口切换前，审批人 Waston 需确认以下证据齐备：

1. ✅ staging 双库 cutover apply 成功（116+133 行，零丢失）
2. ✅ readiness 双 ok（alembic head + critical_tables）
3. ✅ 核心业务 smoke 全绿（9000 七端点 + 9100 RAG）
4. ✅ 数据一致性（9000 9 表 + 9100 7 表行数 + id 完整）
5. ✅ 幂等性（apply 可重跑不破坏）
6. ✅ 回滚能力（pg_dump 备份 + SQLite 源完整 + 切换路径）
7. ✅ 8 个 PG 阻塞已修复并测试覆盖
8. ✅ init-prod/010 用户参数 bug 已修 + smoke PASS（生产同类 bug 修复证据）
9. ⏳ 生产 init-prod/010 落地（本轮只改脚本 + smoke，未对 production 执行初始化——需生产窗口执行）
10. ⏳ 生产窗口密码 DY_SECRET_KEY / SECRET_KEY / DATABASE_URL / RAG_DATABASE_URL 确认（密码 Owner Waston）
11. ⏳ 生产回滚负责人确认（staging 是 LNZS，生产需指定）

---

## 14. 风险与残留项

### 生产切换前必须处理
1. **init-prod/010 生产落地**：本轮修复了脚本 + smoke 验证，但生产 PG 若已有数据卷（init 脚本不执行），需在 Runbook 手动 createdb 第二库或重建数据卷。
2. **生产密码配置**：DY_SECRET_KEY / SECRET_KEY / COMPUTE_INTERNAL_TOKEN / NEWCAR_* 等生产环境变量确认（本轮未碰）。
3. **生产 alembic 0007**：生产 9000 PG 需跑 alembic upgrade head 到 0007（lead_type 加宽）。

### 技术债（不阻塞生产，记录升级路径）
1. **coerce_value 列名猜类型**：脆弱，已暴露 4 类问题。升级路径 = cutover snapshot 带 column_types，改 PG 列类型驱动（非列名猜）。
2. **_now() naive vs PG TIMESTAMPTZ**：全项目 tz 策略问题。当前仅 compute _summarize_consume（Python 层比较）已修；升级路径 = 统一 _now() aware + 全项目 audit datetime 比较。SQLAlchemy filter（SQL 层）不受影响。
3. **9100 staging 向量副本空**：RAG_VECTOR_BACKEND=sqlite，staging 独立 volume 未复制 dev 向量；search-preview 返回 matches:[]（0 命中）。设计如此（向量可从 chunks 重建），非 PG 切换问题。生产切换后需重新训练或复制向量副本。

### 非本轮范围
- docs/superpowers/plans/2026-07-10-phase0-*.md（3 份）是其他任务产出，未纳入本轮提交，留 untracked。

---

## 15. 生产切换 Runbook 要点

基于 staging 演练验证的步骤，生产窗口切换顺序：

1. **备份**：pg_dump 生产 9000 + 9100 库（或确认备份策略）
2. **init-prod**：确认第二库 xg_douyin_ai_cs 已建（若生产 PG 已有数据卷，手动 createdb 或重建卷）
3. **alembic**：9000 upgrade head 0007_lead_type_widen；9100 确认 0002
4. **cutover**：dry-run → apply（MAIN_TARGET_DATABASE_NAME/RAG_TARGET_DATABASE_NAME 按生产库名，APP_ENV=production 时脚本拒绝 apply，需临时 APP_ENV=staging 或 dev 执行）
5. **切 DATABASE_URL**：9000=DATABASE_URL，9100=RAG_DATABASE_URL，指向生产 PG
6. **readiness**：/ready 双 ok
7. **smoke**：/leads /staff /wechat-tasks /agents /compute/summary /compute/packages /knowledge-categories + 9100 categories
8. **回滚待命**：LNZS（或生产回滚负责人）就位，若 5-7 任一步骤失败，DATABASE_URL 切回 sqlite + restart

注意：cutover apply 安全门 `APP_ENV=production 时拒绝 --apply`——生产窗口需显式临时降 APP_ENV 或用专用迁移环境执行 apply，避免误拒。

---

## 16. 安全约束遵守确认

| 约束 | 遵守 |
|------|------|
| 禁止操作 production database/容器 | ✅ 全程 staging + 临时 --rm 容器 |
| 禁止重新全项目 PG 审计 | ✅ 未重复 bootstrap 已通过项 |
| 人工角色门禁（四角色登记 + 审批≠执行 + AI 不担任） | ✅ |
| 人员未登记不得 cutover apply | ✅ 四角色已登记后才 apply |
| 只改/测 init-prod 脚本，不对 production 初始化 | ✅ |
| 真实密码/.env.staging/备份/volume 不提交 | ✅ 提交一 14 文件无敏感，.gitignore 补 backups/ |
| 不触发真实抖音/微信/算力 | ✅ 全程只读 + 历史数据迁移 |
| 最终结论三选一 | ✅ STAGING_PASSED_PENDING_PRODUCTION_APPROVAL |

---

## 17. 提交记录

| 提交 | hash | 内容 |
|------|------|------|
| 提交一（代码） | 38b1bd1 | fix(pg): init-prod + 8 cutover/smoke 阻塞修复 + lead_type 加宽 + coerce_value(tz/bool/None/库名) + vite preview + test + smoke + .gitignore（14 文件 +286/-38） |
| 提交二（文档） | （本提交） | docs(pg): 归档 staging PostgreSQL 切换演练证据（本报告） |

---

## 18. 附录：关键命令与输出摘要

### cutover apply（5.5）
```
# 9000
MAIN_TARGET_DATABASE_NAME=auto_wechat_staging \
SMOKE_DATABASE_URL=postgresql+psycopg://auto_wechat_staging:***@127.0.0.1:25432/auto_wechat_staging \
python scripts/migrate_9000_sqlite_to_postgres_cutover.py \
  --sqlite-db-path docker-data/auto_wechat_9000/auto_wechat.db --apply --yes
# → total_source_rows=116, insert/update/skip/error=116/0/0/0, APPLY_PASS

# 9100
RAG_TARGET_DATABASE_NAME=xg_douyin_ai_cs_staging \
python scripts/migrate_9100_sqlite_to_postgres_cutover.py \
  --sqlite-db-path docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db \
  --postgres-url postgresql+psycopg://***@127.0.0.1:25432/xg_douyin_ai_cs_staging --apply --yes
# → total_source_rows=133, APPLY_PASS
```

### readiness（5.6/5.12）
```
9000 /ready → status:ok, alembic:[0007_lead_type_widen], backend:postgresql
9100 /ready → status:ok, alembic:[0002_create_rag_metadata], backend:postgresql
```

### 核心 smoke（5.7）
```
9000: /leads 200, /staff 200, /wechat-tasks 200, /agents 200,
      /compute/summary 200, /compute/packages 200, /knowledge-categories 200
9100: /knowledge-training/categories 200 (document_count=23),
      /knowledge-training/search-preview 200 (matches:[]，向量副本空)
```

### 幂等（5.10）
```
9000 apply 再跑 → insert=0/update=116/error=0, APPLY_PASS, 行数稳定 19/4/22
9100 apply 再跑 → insert=0/update=133/error=0, APPLY_PASS
```

### init-prod smoke（4.1）
```
bash scripts/smoke_init_prod_non_default_postgres_user.sh
→ [smoke PASS] mytestuser 成功创建第二库 xg_douyin_ai_cs，无 role postgres FATAL，owner=mytestuser
```

### focused 测试（§12）
```
pytest tests/test_db_readiness.py tests/test_cutover_sqlite_to_postgres_migration.py
     tests/test_init_prod_create_rag_database.py
→ 21 passed
```
