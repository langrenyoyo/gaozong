# P3-E-9100-STAGING-ENV-BOOTSTRAP-1 staging 环境准入报告

任务编号：P3-E-9100-STAGING-ENV-BOOTSTRAP-1
生成时间：2026-07-10
前置任务：P3-E-9100-STAGING-DRILL-1（STAGING_BLOCKED，B1-B8 阻塞）

---

## 1. 最终结论

**STAGING_ENV_READY_PENDING_OWNERS**

技术维度：staging 独立环境已建设完成 + 空库全链路准入验证通过（alembic upgrade head + /ready fail→pass + 双库隔离 + 镜像纯净 + dev 未受影响）。

结论限定为 PENDING_OWNERS 的原因：本任务约束「AI 不得将自己登记为执行人 / 回滚负责人 / 审批人；真实人员尚未确定时，结论只能是 STAGING_ENV_READY_PENDING_OWNERS」。当前 staging 回滚负责人与「staging 是否进入下一步正式 staging drill」审批人的人工角色均未指定。

---

## 2. 安全约束执行确认（逐条对照）

| 约束 | 执行结果 | 证据 |
|------|----------|------|
| 只建设 staging 环境和执行环境准入检查 | ✅ | 全部改动集中在 staging 新增文件，不动 dev/生产 |
| 禁止执行 SQLite→PG cutover apply | ✅ | staging 是全新 PG 空库（非从 dev SQLite cutover），未跑任何 cutover 脚本 |
| 禁止导入正式业务数据 | ✅ | auto_wechat_staging.douyin_leads=0 行，xg_douyin_ai_cs_staging.knowledge_documents=0 行 |
| 禁止执行 production Alembic | ✅ | alembic 仅对两个 staging 库执行；无 production 库连接 |
| 禁止连接/修改 production database | ✅ | staging 独立 PG 实例（docker-data-staging/postgres），未连任何 production URL |
| 禁止重启 production 服务 | ✅ | production 未部署；dev 容器保持 Up 39 hours healthy 未动 |
| 禁止中断 dev 联调环境 | ✅ | dev 容器（xg-auto-wechat-api/cs/frontend）全 healthy，dev SQLite 仍在 |
| 禁止删除任何 SQLite 文件 | ✅ | docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db 完好 |
| 禁止输出 production ready 结论 | ✅ | 本结论只针对 staging，未对 production 做任何判断 |
| 向量后端本轮 = sqlite | ✅ | RAG_VECTOR_BACKEND=sqlite；未引入 Milvus |
| 禁止输出数据库密码/完整 URL | ✅ | 本报告 + config 检查全部脱敏（只显 backend/host/port/database/username 是否存在） |

---

## 3. staging 拓扑

| 维度 | dev（基线） | staging（本轮） |
|------|-------------|-----------------|
| compose project | auto_wechat | auto_wechat_staging |
| network | auto_wechat_default | auto_wechat_staging_default |
| postgres 容器 | xg-auto-wechat-postgres（未起） | xg-staging-postgres |
| api 容器 | xg-auto-wechat-api | xg-staging-api |
| cs 容器 | xg-douyin-ai-cs | xg-staging-cs |
| frontend 容器 | xg-auto-wechat-frontend | xg-staging-frontend（本轮未启动） |
| host ports | 9000 / 9100 / 5173 | 29000 / 29100 / 5180 / 25432(pg) |
| volume root | docker-data/ | docker-data-staging/ |
| 9000 database | auto_wechat | auto_wechat_staging |
| 9100 database | xg_douyin_ai_cs | xg_douyin_ai_cs_staging |
| backend image | xg-ai-system-backend:latest | xg-ai-system-backend:staging |
| env_file | .env | .env.staging（本地真实密码，已 gitignore） |
| APP_ENV | development | staging |

隔离层级：compose project 隔离 + 独立 PG 实例（独立 volume）+ database 名带 _staging 后缀（实例+名双重隔离）。

---

## 4. 新增/修改文件清单

新增（提交 e9a8e47 + a99c25a）：
- docker-compose.staging.yml — staging override（!override 替换 ports/volumes/env_file）
- docker/postgres/init-staging/010_create_rag_database.sh — 建 xg_douyin_ai_cs_staging 第二库（含 --username 修复）
- .env.staging.example — staging 模板（APP_ENV=staging + PG 专用 role/密码位 + 向量后端 sqlite）
- docs/ai/05_acceptance/P3-E-9100-STAGING-ENV-BOOTSTRAP-1_READY.md — 本报告

修改：
- app/routers/health.py — 支持 EXPECTED_DATABASE_NAME 覆盖预期库名
- apps/xg_douyin_ai_cs/routers/health.py — 支持 RAG_EXPECTED_DATABASE_NAME 覆盖预期库名
- .gitignore — 放行 .env.staging.example；排除 docker-data-staging/

未提交（本地运行数据/非本轮）：
- .env.staging（含真实密码，gitignore 排除）
- docker-data-staging/（staging PG 运行数据，gitignore 排除）

---

## 5. compose config 防串环境检查

`docker compose --project-name auto_wechat_staging --env-file .env.staging -f docker-compose.yml -f docker-compose.staging.yml config` 退出码 0，关键字段全部符合隔离预期：

- container_name 全 xg-staging-* 前缀（非 xg-auto-wechat-*）✅
- host ports 29000/29100/5180/25432，全部 127.0.0.1 绑定，与 dev 9000/9100/5173 无冲突 ✅
- volumes 全部 docker-data-staging/ 根（非 docker-data/）✅
- DATABASE_URL → auto_wechat_staging，RAG_DATABASE_URL → xg_douyin_ai_cs_staging（均带 _staging 后缀）✅
- APP_ENV=staging（9000 + 9100）✅
- env_file=.env.staging（非 dev .env）✅
- image=xg-ai-system-backend:staging（非 :latest）✅
- 容器内 host=postgres（compose service name，非 localhost）✅
- XG_DOUYIN_AI_CS_DB_PATH="" 留空（禁用 SQLite metadata fallback）✅
- RAG_VECTOR_BACKEND=sqlite ✅
- EXPECTED_DATABASE_NAME / RAG_EXPECTED_DATABASE_NAME 指向带后缀库名 ✅
- postgres init 目录 = docker/postgres/init-staging（非 init-prod）✅

---

## 6. staging 镜像构建 + 纯净度

镜像构建：`docker compose ... build auto-wechat-api` 成功，产物 `xg-ai-system-backend:staging`（含 alembic 1.17.2 / psycopg 3.3.4 / asyncpg 0.31.0 / pymilvus 2.6.12 等依赖；COPY app/ apps/ packages/ scripts/ migrations/）。

镜像纯净度（`docker run --rm xg-ai-system-backend:staging sh -c '...'`）：
- 无 .env / .env.staging / .env.local / .env.example ✅
- 无 *.db / *.sqlite / *.sqlite3 文件 ✅
- app/ apps/ migrations/ 存在 ✅

---

## 7. PG 双 database 初始化

postgres 启动后 healthy（36s）。init-staging/010 成功执行：
- auto_wechat_staging（postgres 镜像 POSTGRES_DB 自动建）
- xg_douyin_ai_cs_staging（init-staging/010 createdb）

两个 staging database 均存在且可连（4 库总览：auto_wechat_staging + xg_douyin_ai_cs_staging + postgres + template1）。

---

## 8. init-staging role postgres bug 修复（根因 + 验证）

**现象**：首次 init-staging/010 日志 echo「创建 database xg_douyin_ai_cs_staging」，但 SELECT pg_database 查不到该库。

**根因**：脚本 `psql -tAc` / `createdb --owner` 未显式 `--username`，docker-entrypoint init 脚本以 OS user postgres 运行，而 POSTGRES_USER=auto_wechat_staging 导致 role "postgres" 不存在：
```
FATAL: role "postgres" does not exist
createdb: error: ... FATAL: role "postgres" does not exist
```
entrypoint 对 init 脚本失败容错，postgres 继续 healthy，但第二库实际未建。

**修复**（提交 a99c25a）：psql/createdb 显式 `--username "$POSTGRES_USER" --dbname postgres`。

**验证**：`down` + 清空 docker-data-staging/postgres + 重新 up，init 日志显示 `CREATE DATABASE` + `[init-staging] 创建 database xg_douyin_ai_cs_staging`，role postgres FATAL 计数=0，双库均存在。

**附带发现（不在本轮范围）**：init-prod/010 存在同类 bug（生产高风险部署脚本，CLAUDE.md 高风险区域）。本轮不修改生产脚本，记录到第 17 节待跟进。

---

## 9. alembic upgrade head

9000（容器内 exec，PYTHONPATH=/workspace）：
```
docker exec -e PYTHONPATH=/workspace xg-staging-api \
  alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head
```
结果：alembic_version = 0006_runtime_cutover_gap（= 代码 head）

9100：
```
docker exec -e PYTHONPATH=/workspace xg-staging-cs \
  alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head
```
结果：alembic_version = 0002_create_rag_metadata（= 代码 head）

env.py 分别读 DATABASE_URL / RAG_DATABASE_URL，校验 backend=postgresql（拒绝 SQLite）。

---

## 10. /ready fail→pass 验证

**迁移前（空库）**：
- api /ready = HTTP 503 not_ready，error_code=DB_CONNECT_FAILED，`relation "alembic_version" does not exist`
- cs /ready = HTTP 503 not_ready，同上

**迁移后（upgrade head）**：
- api /ready = HTTP 200 ok
  - backend=postgresql ✅
  - database_name expected=auto_wechat_staging / actual=auto_wechat_staging ✅
  - alembic_revision expected=0006_runtime_cutover_gap / actual=0006_runtime_cutover_gap ✅
  - critical_tables: douyin_leads pass, sales_staff pass ✅
- cs /ready = HTTP 200 ok
  - backend=postgresql（非 SQLite fallback）✅
  - database_name expected/actual=xg_douyin_ai_cs_staging ✅
  - alembic_revision expected/actual=0002_create_rag_metadata ✅
  - critical_tables: knowledge_documents pass, knowledge_chunks pass ✅

---

## 11. PG 双库表隔离 + 交叉污染确认

auto_wechat_staging（30 表，9000 业务）：douyin_leads, sales_staff, wechat_tasks, douyin_webhook_events, reply_checks, lead_notifications, knowledge_categories, agent_knowledge_categories, ai_agents, compute_*, autoreply_*, alembic_version 等。

xg_douyin_ai_cs_staging（8 表，9100 RAG）：knowledge_documents, knowledge_chunks, knowledge_categories, knowledge_training_sessions, knowledge_training_feedbacks, rag_training_runs, llm_call_logs, alembic_version。

精确交叉污染确认（pg_tables 查询）：
- 9000 库不含 9100 独有表（knowledge_documents/knowledge_chunks/knowledge_training_*/rag_training_runs/llm_call_logs）→ 0 行 ✅
- 9100 库不含 9000 独有表（douyin_leads/sales_staff/wechat_tasks/douyin_webhook_events/reply_checks/lead_notifications/douyin_authorized_accounts）→ 0 行 ✅

注：knowledge_categories 同名表在两库各自由各自 alembic 建立，属不同 database 的独立 schema，同名不冲突，为预期行为（非污染）。

---

## 12. staging 无 dev SQLite + dev 未受影响

- staging cs 容器 XG_DOUYIN_AI_CS_DB_PATH=[]（空，禁用 SQLite metadata fallback）✅
- staging cs 容器内 `find / -name xg_douyin_ai_cs.db` 无结果 ✅
- dev docker-data/xg_douyin_ai_cs/xg_douyin_ai_cs.db 仍在 ✅
- dev 容器（xg-auto-wechat-api / xg-douyin-ai-cs / xg-auto-wechat-frontend）保持 Up 39 hours healthy，端口 9000/9100/5173 未被抢占 ✅

---

## 13. 回归

- compile：app/routers/health.py + apps/xg_douyin_ai_cs/routers/health.py + app/db_readiness.py 全部通过 ✅
- import：9000 + 9100 health router 导入成功 ✅
- pytest tests/test_db_readiness.py：9 passed（EXPECTED_DATABASE_NAME 改动无回归）✅

---

## 14. 本轮修复的 bug 清单

1. compose !reset → !override：初版 docker-compose.staging.yml 用 `!reset` 清空 ports/volumes，导致这些段丢失（!reset 只清空不重设）。改为 `!override` 完全替换后 ports/volumes 恢复。
2. init-staging/010 role postgres FATAL：psql/createdb 未显式 --username，加 `--username "$POSTGRES_USER" --dbname postgres` 修复。
3. .gitignore 两处：放行 .env.staging.example（原 .env.* 规则误忽略模板）；排除 docker-data-staging/（staging 运行数据）。

---

## 15. 向量后端口径

本轮 staging 向量后端 = sqlite（RAG_VECTOR_BACKEND=sqlite）：
- 检索直接读 PG metadata chunks.embedding_json + Python cosine 相似度（O(n)）
- 无独立向量文件/向量库；staging PG volume 独立即满足隔离
- 未引入 Milvus；若后续切 milvus，须独立审批窗口（见 Runbook 34.11），不在本轮

---

## 16. STAGING_ENV_READY_PENDING_OWNERS 理由

技术准入已全部通过，但以下人工角色未指定，按任务约束不得由 AI 登记：

1. staging 回滚负责人：如需销毁 staging（down -v + rm -rf docker-data-staging/postgres），由谁执行与确认。
2. staging 演练审批人：staging 是否进入下一步「正式 staging drill」（P3-E 的 staging cutover 演练），由谁审批。
3. staging 密码 owner：.env.staging 本地真实密码文件，由谁保管与轮换。

以上三项 owner 确认后，结论可升级为 STAGING_ENV_READY。

---

## 17. 待跟进项

1. **init-prod/010 同类 role postgres bug**（生产高风险）：init-prod/010_create_rag_database.sh 同样 psql/createdb 未显式 --username，POSTGRES_USER 非 postgres 时会 FATAL。属 CLAUDE.md 高风险部署脚本区域，不在本轮 staging 范围，后续生产窗口需独立审批修复。
2. **frontend staging VITE 指向**：本轮 frontend 容器未启动（后端 PG 准入是重点）。如需 staging 前端，需评估 VITE_API_BASE_URL/VITE_DOUYIN_AI_CS_API_BASE_URL 指向 staging 29000/29100 的配置。
3. **staging owners 指定**（见第 16 节）。
4. **staging 用于正式 drill**：本环境为准入验证空库，未导入任何业务数据；正式 staging drill 需另起任务并明确演练数据策略。

---

## 附：启动/销毁命令（staging Runbook）

```bash
# 构建 + 启动（postgres + api + cs）
docker compose --project-name auto_wechat_staging --env-file .env.staging \
  -f docker-compose.yml -f docker-compose.staging.yml up -d --build postgres auto-wechat-api xg-douyin-ai-cs

# 启动 frontend（可选，需先评估 VITE 指向）
docker compose --project-name auto_wechat_staging --env-file .env.staging \
  -f docker-compose.yml -f docker-compose.staging.yml up -d auto-wechat-frontend

# alembic upgrade head（空库初始化）
docker exec -e PYTHONPATH=/workspace xg-staging-api \
  alembic -c migrations/postgres/auto_wechat/alembic.ini upgrade head
docker exec -e PYTHONPATH=/workspace xg-staging-cs \
  alembic -c migrations/postgres/xg_douyin_ai_cs/alembic.ini upgrade head

# /ready 验证
curl -s -w "\nHTTP=%{http_code}\n" http://127.0.0.1:29000/ready
curl -s -w "\nHTTP=%{http_code}\n" http://127.0.0.1:29100/ready

# 销毁（保留数据）
docker compose --project-name auto_wechat_staging --env-file .env.staging \
  -f docker-compose.yml -f docker-compose.staging.yml down

# 销毁（清空 PG 数据，下次 up 重新 init；dev 不受影响）
docker compose --project-name auto_wechat_staging --env-file .env.staging \
  -f docker-compose.yml -f docker-compose.staging.yml down
rm -rf docker-data-staging/postgres
```
