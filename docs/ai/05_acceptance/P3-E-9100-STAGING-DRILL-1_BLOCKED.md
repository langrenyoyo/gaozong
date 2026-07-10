# P3-E-9100-STAGING-DRILL-1 BLOCKED 报告

| 项 | 内容 |
|----|------|
| 任务 | P3-E-9100-STAGING-DRILL-1（9000 + 9100 staging PostgreSQL 切换演练） |
| 结论 | **STAGING_BLOCKED** |
| 日期 | 2026-07-10 |
| 上一轮 | P3-PGSQL-PRECUTOVER-REMEDIATION-1（readiness / 旧版隔离 / .env.example / Runbook / 向量后端，已就绪） |

## 1. 执行前硬性检查（10 项门禁）

| # | 检查项 | 结果 | 证据 |
|---|--------|------|------|
| 1 | 主机/Docker context/环境变量属于 staging | ❌ FAIL | 主机=192.168.110.113（CLAUDE.md 登记的开发主机）；docker context=`desktop-linux`；`APP_ENV=development` |
| 2 | 9000 staging database 名=auto_wechat | ❌ FAIL | 9000 容器实测 `backend=sqlite`，无 staging PG database 可核对 |
| 3 | 9100 staging database 名=xg_douyin_ai_cs | ❌ FAIL | 9100 容器实测 `backend=sqlite`，无 staging PG database 可核对 |
| 4 | DATABASE_URL 与 RAG_DATABASE_URL 指向不同 database | ❌ FAIL | `.env` 未设两变量；9000/9100 当前均走 SQLite 路径 |
| 5 | URL 不使用 localhost 跨容器 | ⚠️ N/A | 当前无 PG 连接 |
| 6 | APP_ENV 明确为 staging | ❌ FAIL | `APP_ENV=development` |
| 7 | 使用 docker-compose.yml + 有效 backend Dockerfile | ⚠️ 部分 | 文件存在，但当前 auto_wechat 容器实测 SQLite，非生产 PG compose 真实生效 |
| 8 | 禁用 docker-compose.auto-wechat.yml + 根 Dockerfile | ✅ PASS | 当前未使用这两个废弃入口 |
| 9 | 9100 向量后端已人工明确 | ❌ FAIL | `.env` `RAG_VECTOR_BACKEND=sqlite` 是默认值非人工确认；上一轮 B3 标记"人工确认，本轮不定" |
| 10 | staging 备份路径/执行人/回滚负责人已记录 | ❌ FAIL | 无 staging 环境；AI 不得登记人类角色 |

**小计：8 FAIL / 1 N/A / 1 PASS。** 门禁未通过，全部迁移与演练步骤不得执行。

## 2. 环境证据（只读探查）

- **Git HEAD**：`39e282a`（上轮 P3-E 提交），工作区有未提交 remediation 改动（8 modified + 3 untracked）
- **Docker context**：`desktop-linux`（本机 Docker Desktop，非远端 staging）
- **运行容器**：`xg-auto-wechat-api` / `xg-douyin-ai-cs` / `xg-auto-wechat-frontend`（均 Up 38h healthy，实测 SQLite 后端）；**无 postgres 容器**
- **compose 文件**：`docker-compose.yml` / `docker-compose.dev.yml` / `docker-compose.auto-wechat.yml`（**无 staging**）
- **.env**：`APP_ENV=development`；无 `DATABASE_URL` / `RAG_DATABASE_URL` / `PG_PASSWORD`
- **9000 实测**：`backend=sqlite`，`/workspace/data/auto_wechat.db`
- **9100 实测**：`backend=sqlite`，`/data/xg_douyin_ai_cs.db`

## 3. 根本阻塞

**staging 环境在当前项目中不存在。** 开发主机（dev，192.168.110.113）与 production（宝塔）之间没有独立 staging 部署。当前 docker ps 的 auto_wechat 项目是 dev 联调环境（SQLite，38h），不是 staging。

## 4. 未执行项（明确声明）

本轮**未执行**任何以下操作（因门禁未通过，按任务第二节指令立即停止）：

- ❌ 未执行 Alembic upgrade（9000 / 9100 均未跑）
- ❌ 未执行 cutover dry-run / apply
- ❌ 未重启任何容器
- ❌ 未修改任何数据库
- ❌ 未删除任何 SQLite 文件
- ❌ 未连接 production

## 5. 阻塞解除条件（B1–B8）

| 阻塞 | 解除条件 | 对应后续任务 |
|------|----------|--------------|
| B1 | 建立独立 staging 部署（独立 PG 实例 + 独立 compose project + 独立 volume） | P3-E-9100-STAGING-ENV-BOOTSTRAP-1 |
| B2 | staging `.env` 设 `APP_ENV=staging` | 同上 |
| B3 | staging PG 就绪 + 创建两个 database | 同上 |
| B4 | staging 显式设 `DATABASE_URL` / `RAG_DATABASE_URL`（不同 database，host=compose service） | 同上 |
| B5 | 人工明确 staging 向量后端（sqlite 或 milvus） | 同上（本轮 sqlite） |
| B6 | 登记三角色（执行人 / 回滚负责人 / 审批人，审批人≠执行人） | 待人类指派 |
| B7 | 提交 remediation 改动，基于 clean commit 构建 staging 镜像 | P3-E-9100-STAGING-ENV-BOOTSTRAP-1 |
| B8 | 确认 dev 联调环境（38h）可与新 staging 隔离互不影响 | 同上 |

## 6. 准入结论

**STAGING_BLOCKED**。门禁 8 项 FAIL，staging 演练未开始、未执行任何迁移 / 备份 / cutover / 回滚。**未输出 READY_FOR_PRODUCTION**。

下一步：执行 `P3-E-9100-STAGING-ENV-BOOTSTRAP-1` 解除 B1–B8 环境阻塞（B6 人类角色除外），再重跑本演练。
