# G0 — RELEASE GOVERNANCE P0 HARDENING — EXPLORATION 1（只读探索 + 技术设计）

> 任务：`G0-RELEASE-GOVERNANCE-P0-HARDENING-EXPLORATION-1`
> MODE = READ-ONLY EXPLORATION + TECHNICAL DESIGN；CODE_MUTATION = NOT AUTHORIZED；PRODUCTION_MUTATION = NOT AUTHORIZED；SCOPE_EXPANSION = NOT AUTHORIZED。
> 本轮未执行任何 restart / recreate / build / compose up / migration / env edit / source edit；未触碰当前生产（9000=4b4f96fc/DB0034/healthy，9100=93094f0/DB0003/healthy）。
> 结论日期：2026-08-13。基于真实代码 + 生产执行链证据（`PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_EXECUTION.md`），非对话摘要。

---

## 1. Executive Verdict

**EXPLORATION_COMPLETE_DESIGN_READY**

未触发停止条件（不需要 DB schema change / NewCarProject 修改 / 生产 env 立即修改 / 9100 业务逻辑改变 / 大规模 compose 重构），因此**不输出 OWNER_DECISION_REQUIRED**。

四个 P0 的现状一句话总结：

| P0 | 现状 | 缺口 | 归属批次 |
|---|---|---|---|
| P0-1 Auth Fail-Closed | **缺**。`NEWCAR_AUTH_ENABLED` 默认 False、`NEWCAR_AUTH_MOCK_ENABLED` 默认 True，production 缺 env 时 `/auth/me` 返回 HTTP200 mock | 无任何 production fail-closed 校验；mock 有 4 个生产可达入口 | Batch A |
| P0-2 Immutable Image Identity | **大部已有**。S10-B wrapper preflight P1~P6 已拒绝 missing/empty/:latest/相同共享 mutable/expected mismatch | preflight 不校验 APP_ENV；`.env.production.example` 模板默认 `:latest` | Batch B/C |
| P0-3 Canonical Runner | **有雏形但缺关键绑定**。`release_9000_s10b.py` 已是 9000-only wrapper（--no-deps --no-build） | 缺 COMPOSE_PROJECT_NAME 绑定（M8-G7 已证缺口）；缺 runtime env file 存在校验 | Batch B |
| P0-4 Unified Preflight | **有分散资产**。`production_pg_preflight.sh`（18 项）+ `db_readiness.py`（运行时 DB compat）+ S10-B preflight | 无统一入口覆盖 4 类 identity；Image/Project/Runtime/DB 四类校验分散在 3 处 | Batch B |

最小修改路线（ponytail 原则：复用、不建抽象、不新建部署框架）：
- **P0-1** = `app/config.py` 加一段模块级 fail-closed 校验（startup 拒启动）+ `app/auth/newcar_client.py` 两处 mock 入口 production 拒构造（请求层兜底），合计约 20 行。
- **P0-3/P0-4** = 扩展现有 `scripts/release_9000_s10b.py` 的 preflight，追加 P7（project identity）/P8（runtime env 存在）/P9（APP_ENV+auth 配置）/P10（DB compat 参数化），并给 `canonical_up_command()` 注入 `-p xg_ai_system`。**禁止新建并行部署框架**。
- **P0-2** = 已落地，仅需修正 `.env.production.example` 模板默认值。

---

## 2. Current Reality Matrix（4 行）

### 2.1 P0-1 — Production Auth Fail-Closed

**根因代码（已逐行确认）**：

| 位置 | 事实 | 后果 |
|---|---|---|
| [app/config.py:260](../..//app/config.py#L260) | `NEWCAR_AUTH_ENABLED = _env_bool("NEWCAR_AUTH_ENABLED", False)` | production 缺变量 → False → 鉴权关闭 |
| [app/config.py:261](../..//app/config.py#L261) | `NEWCAR_AUTH_MOCK_ENABLED = _env_bool("NEWCAR_AUTH_MOCK_ENABLED", True)` | production 缺变量 → True → mock 开启 |
| [app/config.py:223](../..//app/config.py#L223) | `APP_ENV = os.getenv("APP_ENV", "development")` | 缺变量 → development（永不 fail-closed） |
| [app/config.py:333-335](../..//app/config.py#L333-L335) | `is_production_env()` 已存在 | 可复用 |
| [app/config.py:64-72](../..//app/config.py#L64-L72) | `_load_env_files()` 模块级执行 | 校验点可放模块级（进程 import 即失败） |

**mock 生产可达入口（4 个）**：

| 入口 | 位置 | 触发条件 | 结果 |
|---|---|---|---|
| `get_request_context_optional` | [app/auth/dependencies.py:34-42](../..//app/auth/dependencies.py#L34-L42) | `not client.auth_enabled` → `build_mock_context()` | mock 上下文，绕过权限 |
| `get_request_context_required` | [app/auth/dependencies.py:45-64](../..//app/auth/dependencies.py#L45-L64) | 同上；`auth_enabled=true + mock_enabled=true` 时 introspect 也返回 mock | 同上 |
| `introspect_code/token/cookie` | [app/auth/newcar_client.py:66/74/82](../..//app/auth/newcar_client.py#L66-L82) | `not auth_enabled or mock_enabled` → `build_mock_context()` | 同上 |
| `exchange_code_for_token` | [app/auth/newcar_client.py:59](../..//app/auth/newcar_client.py#L59) | 同上 → 返回 `mock-external-token:...` | mock 登录 token |
| 权限绕过 | [app/auth/context.py:29-43](../..//app/auth/context.py#L29-L43) | `is_mock_auth()` → `has_permission` 全通过 | mock 即 super_admin |

**必现路径**：[app/routers/auth.py:65-76](../..//app/routers/auth.py#L65-L76) `/auth/me` 在 `not client.auth_enabled or client.mock_enabled` 时返回 HTTP200 + `source_system="mock"` + `role="super_admin"`——这正是任务要求"绝不能发生"的场景，代码层 100% 可复现。

**文档声称 vs 代码事实（drift）**：`.env.production.example:189-190` 与 `AGENTS.md:136` 都写"production 必须 `NEWCAR_AUTH_ENABLED=true` / `NEWCAR_AUTH_MOCK_ENABLED=false`"，但**代码没有任何强制**——文档是祈使句，代码默认值仍指向 mock 开发态。

**代码内 fail-closed 先例**：[app/routers/compute.py:439-455](../..//app/routers/compute.py#L439-L455) `_require_internal` 已有 `if is_production_env(): raise HTTPException(500, INTERNAL_TOKEN_NOT_CONFIGURED)` 模式——P0-1 设计照此先例。

### 2.2 P0-2 — Immutable Per-Service Image Identity

**已实现（S10-B）**：
- [docker-compose.yml:38/73](../..//docker-compose.yml#L38) per-service image env var：`${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}` / `${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}`。
- [scripts/release_9000_s10b.py:118-170](../..//scripts/release_9000_s10b.py#L118-L170) `preflight()` 拒绝：P5 env file 缺失 / P6 compose config 失败 / P1-P2 9000/9100 missing-empty-latest / P3 :latest / P4 相同共享 mutable / P-EXPECTED expected 不一致。
- `compose_env()`（line 65-79）移除宿主 IMAGE 变量（C3 根因修复：Compose 插值 precedence = 宿主 shell env > --env-file）。
- 测试：`tests/test_s10_b_image_identity_isolation.py` RE-T01~T11 + C2-T01~T11 + host pollution 回归 + 序列测试（docker 相关用例 `@pytest.mark.skipif(not _compose_available())`）。

**缺口**：
- preflight **不校验 env file 内 APP_ENV**（P3 注释写"production/rehearsal 模式下拒绝 :latest"，但代码不读 APP_ENV，是**无条件**拒绝 :latest——对 dev 是错杀但对生产安全无害）。
- `.env.production.example:90-91` 模板默认 `xg-ai-system-backend:latest`（对，模板里写的是 :latest，会诱导错误配置）。

### 2.3 P0-3 — Canonical Production Runner

**现状**：`release_9000_s10b.py` 已是 9000-only canonical wrapper：
- [canonical_up_command()](../..//scripts/release_9000_s10b.py#L173-L185)：`docker compose --env-file <f> -f docker-compose.yml up -d --no-deps --no-build auto-wechat-api`（禁 build、禁依赖、只动 9000）。
- 生产执行链证据（M8 apply，`PRODUCTION_EXECUTION.md:2021-2029`）：
  `COMPOSE_PROJECT_NAME=xg_ai_system python3 scripts/release_9000_s10b.py --env-file /root/.xg-ai-release/b7-0034-a633b486.env --expected-9000 xg-ai-system-backend:b7-0034-a633b486 --expected-9100 xg-ai-system-backend@sha256:93094f0... --apply`

**关键缺口（M8-G7，`PRODUCTION_EXECUTION.md:1979-1997`）**：
- `docker-compose.yml` **无 `name:` 顶级字段**（已 grep 确认），env 无 `COMPOSE_PROJECT_NAME`。
- 生产 project=`xg_ai_system`（ProjectDir=/www/wwwroot/XG_AI_System）；wrapper 从 STAGE 执行默认 project=STAGE basename（`xg_ai_system_release_0034_a633b486`）→ **会建第二套 compose project，不操作现有生产**。
- M8 用 command-scoped `COMPOSE_PROJECT_NAME=xg_ai_system` 注入闭合（`PRODUCTION_EXECUTION.md:1989/2593`）。**wrapper 源码未含此绑定**——这是 P0-3 必须补的机器强制。

**宽范围操作事实（Incident B / R0 事故）**：`docker-compose.yml` 9000/9100 均含 `build:` 块（line 39-41/74-76），`docker compose up -d --build` 会全服务按当前 source 重建。生产执行链 `PRODUCTION_EXECUTION.md:2773` 记录：M11 完成后 08:29:05Z 有人用 PROD tree + PROD env 执行 `docker compose up`（很可能 --build）→ 触发 R0/R1/R2 事故链。R1 Hard Boundary（`PRODUCTION_EXECUTION.md:2827`）禁止 --build / 全服务 up / pull。

**机器强制现状**：wrapper 只约束"通过它 apply"的路径；**没有机制阻止任何人绕过 wrapper 直接 `docker compose up -d --build`**。任务要求"至少要设计一层机器强制"——设计见 §3.3 与 §7。

### 2.4 P0-4 — Unified Production Preflight

**已有分散资产（3 处，职责不重叠但无统一入口）**：

| 资产 | 覆盖 | 缺口 |
|---|---|---|
| [scripts/release_9000_s10b.py](../..//scripts/release_9000_s10b.py#L118-L170) | Image Identity（P1-P6）+ env file 存在（P5） | 不校验 APP_ENV / auth 配置 / project / DB |
| [scripts/production_pg_preflight.sh](../..//scripts/production_pg_preflight.sh)（18 项） | git 干净、compose 存在、**APP_ENV=production 强制**、DATABASE_URL/RAG_DATABASE_URL 存在、两库名不同、Milvus 外部后端完整+TCP、PG 连接、database 存在+owner、SQLite 源、磁盘、readiness、apply 安全门 | 不校验 Image Identity / project / auth 配置；面向"PG 切换"历史场景 |
| [app/db_readiness.py:45-61/75-223](../..//app/db_readiness.py#L75-L223) | 运行时 4 步 DB compat（连接+current_database+alembic head+关键表） | 运行时（容器内 /ready），不是 pre-apply |

**DB compatibility 关键事实**：
- 9000 master head=`0035`（含 `0035_wechat_task_claim_lease.py`，已验证）；9100 head=`0005`。
- **生产现状：9000 DB=0034、9100 DB=0003**（低于 master head）——DB compat gate **必须按 release 参数化**（--expected-db-9000=0034 / --expected-db-9100=0003），不能直接比对 master head。
- pre-apply 静态读镜像内 migrations/ 目录可行（镜像含 migrations/，`docker run --rm <image>` 只读，无副作用）；运行时比对已由 /ready（ALEMBIC_REVISION_MISMATCH→503）覆盖。

---

## 3. Root Cause → Control Mapping（每事故 PREVENT / DETECT / FAIL-CLOSED 三层）

> 两个事故根因：**Incident A = 生产缺 auth env 导致 mock 鉴权上线**（配置默认值 + compose env_file required:false）；**Incident B = 宽范围 compose up --build 导致全服务按 source 重建**（共享 :latest + build 块 + 无 project 锁定 + 无机器强制）。

### 3.1 Incident A（auth 静默 mock）→ P0-1

| 层 | 机制 | 现状 | G0 改动 |
|---|---|---|---|
| PREVENT（配置正确性） | `.env.production.example` 文档 + `production_pg_preflight.sh` | 文档有、无强制 | 模板 Batch C；preflight P9 Batch B |
| **FAIL-CLOSED（进程级）** | **startup 拒启动**：`is_production_env()` + auth 配置不合法 → 模块加载即 raise | **缺（最高优先级）** | Batch A：config.py 模块级校验 |
| **FAIL-CLOSED（请求级）** | **mock 入口拒构造**：production 下 `build_mock_context` / mock token 一律抛错 | **缺** | Batch A：newcar_client.py 两处 guard |
| DETECT（运维可见） | 容器 unhealthy / /ready 503 / 启动日志报错 | 部分（若进程起不来则天然可见） | 可选：/ready 加 auth 检查（Batch B OPTIONAL） |

### 3.2 Incident B（宽范围重建）→ P0-2 / P0-3

| 层 | 机制 | 现状 | G0 改动 |
|---|---|---|---|
| PREVENT（镜像身份） | per-service image env var + immutable 校验 | **已实现**（S10-B P1-P6） | Batch B 补 APP_ENV 校验 |
| DETECT（身份漂移） | preflight expected 校验 + 运行容器 image 比对 | 已有（--expected-9000/9100） | 维持 |
| **FAIL-CLOSED（宽范围命令）** | canonical wrapper 只允许 `up -d --no-deps --no-build <9000>`；禁止 --build / 全服务 | 已有 wrapper，**但无 project 绑定** | Batch B：`-p xg_ai_system` + preflight P7 |
| **FAIL-CLOSED（错误部署后果）** | 即便绕过 wrapper 直接 compose up --build，新容器因 P0-1 startup fail-closed 无法 serving | **缺（P0-1 是 P0-3 的兜底）** | Batch A 落地后自动获得 |

> 关键设计洞察：**P0-1 的 startup fail-closed 是 P0-3"机器强制"的真正兜底**——即使 operator 绕过 wrapper 用 `docker compose up -d --build` 重建，只要重建产物沿用 production env（缺 auth 或 auth 不合法），新 9000 进程启动即拒绝，容器 unhealthy，不会 serving mock。三层叠加（P0-1 进程级 + P0-2 preflight + P0-3 wrapper）构成可论证的机器强制，**无需新建部署框架**。

### 3.3 机器强制设计（P0-3 任务要求"至少一层"）

三层阶梯（最简、可论证、不建新框架）：

1. **进程级（最强）**：P0-1 startup fail-closed。任何 production 配置错误部署的镜像无法 serving。**这一层对绕过 wrapper 的所有路径生效。**
2. **入口级**：S10-B wrapper 为唯一受支持 apply 入口，preflight 在 apply 前拒绝：非 immutable / project 不匹配 / runtime env 缺失 / auth 配置不合法 / DB 期望不匹配。
3. **文档 + 验收级**：README / AGENTS.md 声明"production 禁止直接 docker compose up/build"，staging 演练作为验收；生产执行链 M8 现场纪律继续有效（一次只动一个服务，失败不重试，禁止 --build）。

> 现实边界（如实声明）：无法用纯 compose 配置阻止有权限的 operator 直接 `docker compose up -d --build`（那不是本仓代码能控制的）；本设计通过"错误部署的后果不可服务"（第 1 层）把风险从"静默坏"降为"明显坏"。如需更强（如 GitOps 强制），属 Explicit Non-Goal。

---

## 4. Env 架构审计（任务单独要求）

### 4.1 现状：Option B 形态已落地（release identity env + runtime env + runner bridge）

| 文件 | 归属 | 职责 | 事实（生产执行链证据） |
|---|---|---|---|
| `/root/.xg-ai-release/b7-0034-a633b486.env`（release-exec.env） | **Release Identity Env** | compose 插值用的 IMAGE 两键 + 派生键；mode 600 root-only | `PRODUCTION_EXECUTION.md:589/638/700`：已迁出 STAGE → /root/.xg-ai-release |
| `.env.production.local` | **Runtime Env** | secrets/runtime 配置（DATABASE_URL、NEWCAR_AUTH_*、Milvus、PG 密码等）；**service env_file 指向它** | compose 仅容器内读取，不进入 shell env |
| `scripts/release_9000_s10b.py --env-file` | **Runner Bridge** | 把 Release Identity Env 传给 `docker compose --env-file` 做插值 | M8 实际命令见 §2.3 |

### 4.2 审计结论：**维持分离（Option B），不合并成 Option A**

理由（代码事实）：
1. **职责不同**：IMAGE/COMPOSE_PROJECT_NAME 是"部署哪个制品"（release identity），DATABASE_URL/NEWCAR_AUTH_* 是"服务怎么跑"（runtime config）。合并成单文件会让 release 产物的 SHA 依赖 runtime secrets，破坏"release 冻结"语义。
2. **M8 已证明**：wrapper 从 STAGE 执行，`--env-file` 指向 /root/.xg-ai-release 的 release env；service env_file 仍指向 STAGE 树里的 .env.production.local（runtime）。两者职责已分离且可独立冻结。
3. **合成风险**：若把 runtime secrets 塞进 release env，`docker compose config` 插值会把它带进子进程环境（C3 教训的镜像），扩大 secrets 暴露面。

### 4.3 分离形态下的缺口（P0-3/P0-4 补）

1. **runtime env 存在性无强制**：compose `env_file: path: .env.production.local required: false`（docker-compose.yml:46/81/123）→ 缺文件不失败（Incident A 形态）。**P8：wrapper preflight 校验 service env_file 指向的文件真实存在**。
2. **project identity 未进 release env**：COMPOSE_PROJECT_NAME 靠 command-scoped 注入（M8 手动）。**P7：wrapper 增加 -p/--expected-project，并注入到 compose 命令**。
3. **auth 配置校验缺失**：NEWCAR_AUTH_* 属 runtime env。**P9：wrapper preflight 校验（与 P0-1 进程级校验互补，让部署前就能发现，而不是等容器起不来）**。

---

## 5. 代码搜索分类（任务第九节要求）

### 5.1 `AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE`

| 位置 | 分类 | 说明 |
|---|---|---|
| docker-compose.yml:38/73 | **ACTIVE** | production 部署的 per-service image identity |
| docker-compose.staging.yml | **ACTIVE**（staging） | staging 独立 image `xg-ai-system-backend:staging` |
| scripts/release_9000_s10b.py:40（IMAGE_VARS） | **ACTIVE** | canonical runner 消费 |
| tests/test_s10_b_image_identity_isolation.py | **TEST** | 覆盖 RE-T01~T11 |
| .env.production.example:90-91 | **ACTIVE**（模板） | 默认 `:latest`，需改为 immutable 占位（Batch C） |
| .env.lan.example / .env.development.example | **DEV_ONLY** | 本地/LAN 开发默认 |

### 5.2 `docker compose ... up -d --build`（宽范围操作）

| 位置 | 分类 | 说明 |
|---|---|---|
| README.md:381、docs/ai/11_deployment_ops/LOCAL_DOCKER_DEV.md | **DEV_ONLY**（文档） | dev compose（docker-compose.dev.yml），与生产隔离 |
| docker-compose.staging.yml:22-23（注释） | **ACTIVE**（staging） | staging 显式 `--project-name auto_wechat_staging`——**P0-3 project 绑定先例** |
| docs/ai/09_car_project/*、docs/ai/05_acceptance/P3-E-9100-* | **COMPATIBILITY**（历史验收文档） | 历史阶段命令记录，非当前生产操作手册 |
| PRODUCTION_EXECUTION.md:2773/2827 | **LEGACY_CANDIDATE**（事故记录） | M11 后 08:29:05Z 的 `docker compose up`（很可能 --build）→ R0 事故；R1 禁止 --build 的记录 |

### 5.3 `env_file ... required: false`

| 位置 | 分类 | 说明 |
|---|---|---|
| docker-compose.yml:46/81/123 | **ACTIVE（Incident A 根因）** | 缺文件不失败 → P8 由 wrapper preflight 兜底 |
| docker-compose.dev.yml:32/82/138/317 | **DEV_ONLY** | dev 可缺文件 |
| docker-compose.staging.yml:44/59 | **ACTIVE**（staging） | staging 语义 |

### 5.4 `/ready` / `alembic_revision` / alembic head

| 位置 | 分类 | 说明 |
|---|---|---|
| app/routers/health.py:62-88（9000 /ready） | **ACTIVE** | PG 连通+database+alembic head+关键表 → 503 |
| apps/xg_douyin_ai_cs/routers/health.py（9100 /ready） | **ACTIVE** | RAG PG + Milvus readiness |
| app/db_readiness.py:45-61（load_alembic_heads） | **ACTIVE** | ScriptDirectory.get_heads() 读代码 migration 目录 |
| docker-compose.yml healthcheck:64/109 | **ACTIVE** | 容器 healthcheck 用 /ready（A1 修复后） |
| scripts/production_pg_preflight.sh:182-185 | **ACTIVE** | preflight 复用 /ready |

### 5.5 `NEWCAR_AUTH_ENABLED` / `NEWCAR_AUTH_MOCK_ENABLED`

| 位置 | 分类 | 说明 |
|---|---|---|
| app/config.py:260-261 | **ACTIVE（P0-1 根因）** | 默认 False/True（mock 开发态） |
| app/auth/newcar_client.py:40-53 + mock 分支 | **ACTIVE（mock 入口）** | 4 个生产可达 mock 分支 |
| app/auth/dependencies.py / context.py / routers/auth.py | **ACTIVE** | mock 上下文构造 + 权限绕过 + /auth/me mock 路径 |
| docker-compose.dev.yml:94-95、.env.development.example:99-100 | **DEV_ONLY** | 本地 mock 默认 |
| .env.lan.example:122-123 | **DEV_ONLY**（LAN） | LAN 真实鉴权示范 |
| .env.production.example:189-190、AGENTS.md:136、docs/config/ENV_VARIABLE_REFERENCE.md:47-48 | **ACTIVE**（文档/模板） | "production 必须 true/false"的祈使句，无代码强制 |
| tests/test_auth_context.py（多组 monkeypatch） | **TEST** | 覆盖 mock 行为 |

### 5.6 `COMPOSE_PROJECT_NAME` / project name

| 位置 | 分类 | 说明 |
|---|---|---|
| docker-compose.yml | **ACTIVE（缺口）** | 无 `name:` 顶级字段 |
| docker-compose.staging.yml:22 | **ACTIVE**（先例） | `--project-name auto_wechat_staging` |
| PRODUCTION_EXECUTION.md:1979-1997/2023/2593 | **ACTIVE（M8-G7 证据）** | 生产 project=`xg_ai_system`；command-scoped 注入闭合 |

---

## 6. Proposed Minimal Change Set

> ponytail 原则：最小 diff、复用、不建抽象。全部改动落在已存在的文件。

### 6.1 MUST_CHANGE

| # | 文件 | 改动 | 行量（估） | P0 |
|---|---|---|---|---|
| M1 | [app/config.py](../..//app/config.py) | `is_production_env()` 定义后加模块级校验：`if is_production_env() and (not NEWCAR_AUTH_ENABLED or NEWCAR_AUTH_MOCK_ENABLED): raise RuntimeError(...)`（startup fail-closed，方案 A） | ~5 | P0-1 |
| M2 | [app/auth/newcar_client.py](../..//app/auth/newcar_client.py) | `build_mock_context()` 顶部 + `exchange_code_for_token` mock 分支各加 `if is_production_env(): raise RuntimeError(...)`（请求层兜底，方案 C；覆盖全部 4 个 mock 入口） | ~6 | P0-1 |
| M3 | [scripts/release_9000_s10b.py](../..//scripts/release_9000_s10b.py) | ① `canonical_up_command()`/`compose_config()` 注入 `-p/--project-name`（默认 `xg_ai_system`，对齐生产事实）；② preflight 追加 P7（project identity：--expected-project 不一致即 FAIL）/P8（compose config 中 service env_file required:false 指向的文件必须存在）/P9（APP_ENV=production + NEWCAR_AUTH_ENABLED=true + NEWCAR_AUTH_MOCK_ENABLED=false + DATABASE_URL/RAG_DATABASE_URL 非空）/P10（--expected-db-9000/9100 参数，pre-apply 读镜像内 migrations/ alembic head 静态比对）；③ CLI 新增对应参数 | ~60 | P0-3/P0-4 |

### 6.2 OPTIONAL（纵深，可并入 Batch B 或后续）

| # | 文件 | 改动 | 说明 |
|---|---|---|---|
| O1 | [app/routers/health.py](../..//app/routers/health.py) | /ready 追加 auth 配置检查（production + auth 不合法 → 503 error_code=AUTH_CONFIG_INVALID） | 方案 B；让 staging 预检在容器起来前发现（与 M1 互补，M1 已让进程起不来，O1 主要服务诊断可读性） |
| O2 | [scripts/production_pg_preflight.sh](../..//scripts/production_pg_preflight.sh) | 追加 Image Identity（:latest 拒绝）+ COMPOSE_PROJECT_NAME + NEWCAR_AUTH_* 检查项 | 该脚本是 PG 切换历史 preflight，若保留则补齐身份校验；若未来并入 wrapper preflight 则标记 LEGACY_CANDIDATE |

### 6.3 NO_CHANGE（明确不动）

| 位置 | 理由 |
|---|---|
| docker-compose.yml 的 `build:` 块 | 移除即大规模 compose 重构（禁止）；宽范围后果由 P0-1 进程级 fail-closed 兜底（§3.3） |
| compose `env_file required: false` | 改 required:true 会破坏 dev/staging 缺文件容忍；存在性校验上移到 wrapper preflight（P8），且 P0-1 已在进程级兜底 |
| 9100 业务逻辑（apps/xg_douyin_ai_cs/） | 任务禁止 9100 业务逻辑改变；P0-1 只动 9000 侧 |
| NewCarProject | 任务禁止 |
| DB migration | 任务禁止；DB compat 走参数化校验而非改库 |
| GitOps/K8s/CI 改写 | Explicit Non-Goal |

### 6.4 方案比较（任务要求 P0-1 比较 A/B/C/D）

| 方案 | 机制 | 优点 | 缺点 | 裁决 |
|---|---|---|---|---|
| A | startup 拒启动（config 模块级 raise） | 最彻底；错误部署的镜像根本 serving 不了；实现 ~5 行 | 容器表现为 restart 循环（但这是**明显故障**，优于静默 mock） | **采用为主防线**（M1） |
| B | /readiness 503 | 容器"起来"但不接受流量（前提 readiness gate 生效） | /ready 503 不阻断反代转发；且是运行态不是启动态 | OPTIONAL（O1，诊断增强） |
| C | request 层拒 mock | 纵深；即使 A 被绕过（如 APP_ENV 被误设非 production）也不返回 mock | 改动点需覆盖 4 入口；单点漏改有风险 | **采用为兜底**（M2，集中在 build_mock_context + exchange_code_for_token 两处即可全覆盖） |
| D | A + C 组合 | 启动态 + 请求态双 fail-closed；A 防错误部署、C 防动态环境 | 略多几行 | **推荐 = D** |

---

## 7. Production Runtime Contract（Operator → Canonical Runner → 4 类 identity Gate → Apply → Post-apply）

```
Operator 持有（G0 C4 双 env 分离，2026-08-13 实现 + 2026-08-13 R1 返工后的真实契约）：
  ① Release Identity Env（release-exec.env，root-only，非敏感）：
     AUTO_WECHAT_API_IMAGE / XG_DOUYIN_AI_CS_IMAGE
     AUTO_WECHAT_API_EXPECTED_REVISION / XG_DOUYIN_AI_CS_EXPECTED_REVISION   （R1-1：expected revision canonical source，缺失 → PREFLIGHT FAIL）
  ② Runtime Env（.env.production.local）：DATABASE_URL / NEWCAR_AUTH_* / Milvus / secrets
     （不含 image identity 键、不含 expected revision 键——后者属 identity 非 runtime）

Canonical Runner（唯一受支持 apply 入口）：
  python scripts/release_9000_s10b.py \
    --env-file /root/.xg-ai-release/<release>.env \
    --runtime-env-file .env.production.local \
    --expected-9000  <immutable 9000 image> \
    --expected-9100  <immutable 9100 image> \
    --apply
  （project identity 是 runner 常量 PROJECT_NAME="xg_ai_system"，命令显式 -p 注入，不接受 --expected-project 参数；
    R1-1：expected revision 由 release identity env 强制提供，CLI --expected-*-revision 仅作可选显式断言，
    两者同时存在时强制相等，release env 缺失 → RELEASE-ENV-REVISION-MISSING FAIL、CLI 冲突 → CLI-REVISION-CONFLICT FAIL）

Unified Preflight（P1~P12，任一 FAIL 即停止）：
  P0x  Image Identity（已有 P1-P6）：missing / empty / :latest / 相同共享 mutable / expected mismatch → FAIL
  P7   Compose Project Identity：宿主 COMPOSE_PROJECT_NAME 污染（≠ xg_ai_system）→ FAIL；命令永远 -p xg_ai_system
  P8   Runtime Config Existence：--runtime-env-file 指向文件不存在 → FAIL（Incident A 形态部署前拦截）
  P9   Runtime Config Identity：APP_ENV=production + NEWCAR_AUTH_ENABLED=true + NEWCAR_AUTH_MOCK_ENABLED=false
       + DATABASE_URL/RAG_DATABASE_URL 非空 → 任一不符 FAIL
  P10  Image↔Expected（R1-1 增强）：release env expected revision 与 target image 内 migrations/ alembic head
       比对 → 不符 FAIL（不拿 master head 作 release target）
  P11  Actual Runtime Env Binding（R1-3 新增）：runner 生成临时 !override env_file 绑定（required:true，
       只写 runtime env path、mode 600、不落 secret），最终 compose service env 必须含显式 runtime env 关键值
       （9000 APP_ENV=production / NEWCAR_AUTH_* / DATABASE_URL，9100 RAG_DATABASE_URL / RAG_VECTOR_BACKEND=milvus）
       → 缺失即 FAIL（关闭 VALIDATED_RUNTIME_ENV == ACTUAL_SERVICE_RUNTIME_ENV_SOURCE）
  P12  DB Actual↔Expected（R1-2 新增）：只读 SELECT version_num FROM alembic_version（psycopg 优先 / psql
       回退），DB 连接用本次显式 --runtime-env-file 的 DATABASE_URL / RAG_DATABASE_URL，日志只记 revision/db
       名/PASS-FAIL 不落 secrets；TARGET_IMAGE_HEAD == RELEASE_EXPECTED == ACTUAL_DB 三方一致，
       compose up 前完成 → 任一不符 FAIL（0028 image + DB0034 组合在 preflight 层即被拒绝）

Service-scoped Apply（R1-3：apply 与 preflight 校验同一份 runtime env source）：
  docker compose --env-file <release-env> -p xg_ai_system -f docker-compose.yml \
    -f <g0-runtime-env-bridge-*.yml> \
    up -d --no-deps --no-build auto-wechat-api        # 只动 9000，禁 build，禁依赖；env_file !override 绑定显式 runtime env

Post-apply Readiness（既有，维持）：
  ① 容器 healthcheck /ready：PG 连通 + current_database + alembic head(代码) == DB revision + 关键表 → 200/503
  ② P0-1 进程级：9000 若 auth 配置不合法，容器根本起不来（unhealthy）
  ③ 9100 冻结：本次 release 不 touch 9100（frozen image/DB 0003）
```

---

## 8. Test Matrix（任务第十节要求 T1~T14）

> 全部为仓库内可运行测试（pytest / assert 级），不依赖生产。docker 相关用例沿用现有 `@pytest.mark.skipif(not _compose_available())` 模式。
>
> **实现后映射（2026-08-13）**：T1~T7 实际落地于 `tests/test_auth_fail_closed.py`，T8~T14 落地于 `tests/test_release_g0_hardening.py`（S10-B 既有套件 `tests/test_s10_b_image_identity_isolation.py` 回归）。因 C1 不做 import-time raise，T1/T2/T4 的"import config 模块加载 raise"实现为显式调用 `config.validate_production_auth_config()` raise；T6 请求层兜底由 `NewCarProjectAuthClient.from_env()` 覆盖（dependencies._client() 每次请求调用）。T11/T12/T14 参数按 C4 实现为 `--runtime-env-file` / `--expected-9000-revision`/`--expected-9100-revision`（project 为 runner 常量，无 `--expected-project` 参数）。
>
> **R1 返工映射（2026-08-13）**：独立测试（IT-G1/G10/G11/G12/G13）触发返工，R1 新增 T-R1-1~T-R1-10 于 `tests/test_release_g0_hardening.py`：
> - T-R1-1/2（R1-1）：release env revision 缺失 → RELEASE-ENV-REVISION-MISSING FAIL；CLI 与 release env 冲突 → CLI-REVISION-CONFLICT FAIL
> - T-R1-3~6（R1-2）：三方 gate（IMAGE_HEAD / EXPECTED / DB_ACTUAL）9000 与 9100 独立判定，T-R1-3 覆盖 Hard Acceptance（IMAGE=0028 / EXPECTED=0028 / DB=0034 → FAIL + APPLY_COUNT=0），T-R1-3b 证明 preflight FAIL 时 apply 绝不执行
> - T-R1-7/7b/8/9/10（R1-3）：STAGE 缺失 + 显式 runtime 有效 → PASS（绑定证明）；STAGE 存在但内容不同 → !override 保证显式 runtime env 胜出（T-R1-7b）；runtime env 缺失 / auth 非法 → FAIL + APPLY_COUNT=0；hostile COMPOSE_PROJECT_NAME + shell :latest → 无法污染 runner 固定身份
> - 回归基线：BASE 54 passed（G0 candidate）→ CANDIDATE 66 passed（+12，只增不减）

### 8.1 P0-1 组（Batch A，新增 `tests/test_auth_fail_closed.py`）

| ID | 场景 | 预期 |
|---|---|---|
| T1 | `APP_ENV=production` + 缺 NEWCAR_AUTH_ENABLED（默认 False）→ import config | 模块加载 raise（fail-closed） |
| T2 | `APP_ENV=production` + ENABLED=false + MOCK=true | raise |
| T3 | `APP_ENV=production` + ENABLED=true + MOCK=false | 正常加载（PASS） |
| T4 | `APP_ENV=production` + ENABLED=true + MOCK=true | raise |
| T5 | `APP_ENV=development` + 缺省 | 正常加载（mock 开发态保留） |
| T6 | `APP_ENV=production` + 配置不合法 → `GET /auth/me`（TestClient 直接构造，绕过启动） | 返回 5xx，绝不返回 200 mock（请求层兜底 M2） |
| T7 | `APP_ENV=development` + 缺省 → `GET /auth/me` | 返回 200 mock（dev 回归保障） |

### 8.2 P0-2 组（Batch B，复用现有 `test_s10_b_image_identity_isolation.py`）

| ID | 场景 | 预期 |
|---|---|---|
| T8 | preflight missing/empty/:latest/相同共享 mutable | FAIL（**已覆盖** C2-T02~T07/T10/P4，回归即可） |
| T9 | preflight 两 immutable 不同身份 | PASS（**已覆盖** C2-T01，回归即可） |

### 8.3 P0-3 组（Batch B）

| ID | 场景 | 预期 |
|---|---|---|
| T10 | `canonical_up_command()` 注入 `-p xg_ai_system`；`compose config --format json` 用注入 project 解析正确 | 命令含 `-p xg_ai_system`（或等价 project 绑定） |
| T11 | preflight P7：--expected-project 与注入 project 不一致 | FAIL |
| T12 | preflight P8：compose config 中 service env_file 指向文件不存在（模拟缺 .env.production.local） | FAIL（Incident A 形态在部署前被拦） |

### 8.4 P0-4 组（Batch B）

| ID | 场景 | 预期 |
|---|---|---|
| T13 | preflight P9：env file 内 APP_ENV != production / NEWCAR_AUTH_* 不合法 | FAIL |
| T14 | preflight P10：--expected-db-9000=0034 与镜像内 migrations/ alembic head 比对（image 侧 `docker run --rm` 只读） | 一致 PASS；不一致 FAIL（参数化，不硬编码 master head） |

> 回归说明：T8/T9 为已有测试，Batch B 落地后须确认不回归；新增 T10-T14 与 P7-P10 一一对应。

---

## 9. Migration / Compatibility Risk

| 维度 | 评估 |
|---|---|
| DB_CHANGE | **无**。P0-1~P0-4 全部应用/部署层，无 migration、无 schema 变更 |
| API_CHANGE | `/auth/me` 在 **production + 配置不合法**时从 200 mock 变为 5xx（这正是修复目标）；development 行为不变。属预期行为修复，非回归 |
| PROMPT_CHANGE | 无 |
| BUSINESS_BEHAVIOR_CHANGE | production 下错误部署无法 serving（预期收紧）；正确配置的 production 行为不变 |
| DEV_MOCK_BEHAVIOR_CHANGE | **无**。development/lan 缺省保持 mock（T5/T7 保障） |
| PRODUCTION_DEPLOYMENT_BEHAVIOR_CHANGE | S10-B wrapper 命令签名扩展（新增 --expected-project/--expected-db-*，向后兼容，旧命令仍可跑但缺校验）；apply 行为增加 `-p xg_ai_system`（与 M8 现场验证过的 command-scoped 注入等价，project 从隐式 STAGE 推导改为显式指定——**这正是修复 M8-G7 缺口**） |

**兼容要点**：所有新增 preflight 检查均为**新 FAIL 条件**，只会让原本非法/危险的部署更早失败，不会改变合法部署路径；wrapper 新增参数全部可选默认值兼容旧调用；docker-compose.yml / .env 文件本身零改动。

---

## 10. Explicit Non-Goals

明确不做（避免 scope 扩散，任务约束）：

- **NO GitOps / NO Kubernetes / NO CI/CD 流水线改写**（P0-3 机器强制只做到三层阶梯 §3.3，不建平台）。
- **NO RB-10 cleanup**（生产旧容器清理不在本任务，仍 NOT AUTHORIZED）。
- **NO G1-G4 提前实施**（本任务只做 P0-1~P0-4 四个 P0，不新增第五个 P0）。
- **NO 大规模 compose 重构**（不改 build 块、不改 env_file required 语义、不拆服务）。
- **NO 业务功能变更**（本任务全部是部署/安全硬化，不碰业务逻辑）。
- **NO DB migration / schema change**。
- **NO NewCarProject 修改**。
- **NO 9100 业务逻辑改变**。
- **NO 生产 env 立即修改**（本轮只读；生产 .env.production.local 现有配置不合法与否的修正属未来 Batch 实施窗口，需另行审批）。
- **NO 断言 registry 侧 immutability**（沿 S10-B §12 边界，只拒绝已知 mutable `:latest` 后缀，不声称验证 digest 存在性）。

---

## 11. Recommended Implementation Batches

> 最多 Batch A/B/C；每批独立可交付、独立验收。实施窗口另行审批（本轮只读，不实现）。
>
> **实现状态（2026-08-13 更新）**：A/B/C 三批已按 APPROVED_WITH_4_CONSTRAINTS（C1~C4）落地。落地时按 C1 将原设计"模块级 fail-closed（import 即失败）"调整为 **startup + auth-client 双防线**（不做 import-time raise，避免阻断 alembic/维护/诊断脚本）；按 C2 将 project identity 固定为命令行 `-p xg_ai_system`；按 C3 将 DB compat 绑定 target-image migration head ↔ expected revision；按 C4 将 release identity env 与 runtime secrets env 分离为 runner 双参数。测试见 `tests/test_auth_fail_closed.py`（T1~T7，G0-A1~A3）+ `tests/test_release_g0_hardening.py`（T8~T14，G0-B1~B5），均 PASS。

### Batch A — Auth Fail-Closed（P0-1，最高优先级，生产安全红线）

- M1：config.py 模块级 fail-closed（startup 拒启动）。
- M2：newcar_client.py 两处 mock 入口 production 拒构造（请求层兜底）。
- O1（可选）：health.py /ready 追加 auth 配置检查（诊断增强）。
- 测试：`tests/test_auth_fail_closed.py`（T1~T7）。
- 验收：pytest 全绿；development 下 /auth/me 仍 200 mock（T7）；production+缺配置下 config import 即失败 + 请求层 5xx（T1-T6）。

### Batch B — Canonical Runner + Unified Preflight（P0-3 + P0-4）

- M3：release_9000_s10b.py 扩展——`-p xg_ai_system` 注入 + preflight P7/P8/P9/P10 + CLI 参数。
- O2（可选）：production_pg_preflight.sh 补齐身份校验或标记 LEGACY_CANDIDATE。
- 测试：T8~T14（T8/T9 回归，T10-T14 新增）。
- 验收：wrapper dry-run 在"project 不匹配 / runtime env 缺失 / auth 配置不合法 / DB 期望不匹配 / :latest"任一场景 FAIL；合法 immutable 双身份 PASS；命令含 `-p xg_ai_system --no-deps --no-build auto-wechat-api`。

### Batch C — Docs / Templates / Regression

- `.env.production.example:90-91` 默认 `:latest` → immutable 占位符（如 `xg-ai-system-backend:<release-tag>`，并注释"production 必须显式指定 immutable tag/digest，preflight 拒绝 :latest"）。
- AGENTS.md / 05_PROJECT_CONTEXT.md 同步 G0 结论（auth fail-closed 强制 + canonical runner 契约 + 4 类 identity preflight）。
- 全量回归（含 test_s10_b + test_auth_context + 既有套件）。

---

## 12. 任务完成声明

**G0-RELEASE-GOVERNANCE-P0-HARDENING-EXPLORATION-1 = COMPLETE**
**TECHNICAL_DESIGN = READY_FOR_OWNER_REVIEW**
**IMPLEMENTATION = COMPLETE**（2026-08-13，APPROVED_WITH_4_CONSTRAINTS A→B→C 连续实现）
**R1 返工（2026-08-13）= COMPLETE**：G0_R1_1_REVISION_CONTRACT = PASS / G0_R1_2_DB_COMPATIBILITY = PASS /
  G0_R1_3_RUNTIME_ENV_ACTUAL_BINDING = PASS；0028_IMAGE_0028_EXPECTED_0034_DB = PREFLIGHT_REJECTED；
  APPLY_BEFORE_PREFLIGHT_PASS = IMPOSSIBLE；NEW_REGRESSION = 0；CANDIDATE_COMMIT = FROZEN
**IMPLEMENTATION STATUS = CANDIDATE_READY_FOR_INDEPENDENT_RETEST**（G0 = NOT YET COMPLETE，待独立复测）
**PRODUCTION_ROLLOUT = NOT AUTHORIZED**

只读探索 + 技术设计完成；实施窗口已按 4 约束落地 A（auth fail-closed）/B（canonical runner + unified preflight）/C（env 模板职责修正 + 文档同步）。八项验收覆盖：
- G0-A1 production auth missing → FAIL CLOSED（T1/T2b/T6）
- G0-A2 production mock=true → FAIL CLOSED（T2/T6）
- G0-A3 development mock → PASS（T5）
- G0-B1 9000/9100 :latest → PREFLIGHT FAIL（既有 S10-B P3 回归）
- G0-B2 wrong compose project → impossible via canonical runner（T10）+ 宿主环境污染 FAIL（T11）
- G0-B3 runtime env missing/wrong → PREFLIGHT FAIL（T12/T13）
- G0-B4 image revision != expected → PREFLIGHT FAIL（T14）
- G0-B5 normal frozen release → PREFLIGHT PASS（T8/T13b/T14b）

待独立测试窗口验证后 G0 = COMPLETE，随后进入 G1 CODE REALITY MAP（不插入更多 Release Governance P1/P2，不处理 RB-10）。

**文档影响检查（实现后更新）**：本实现使 3 处文档结论从"祈使句"升级为"代码强制/机器强制"，已同轮同步：① `AGENTS.md`/`CLAUDE.md` Current Hard Constraints 新增第 12 条 G0 硬化约束；② `docs/ai/05_PROJECT_CONTEXT.md` 第 4.2 节（canonical runner + 双 env 分离 + 4 类 preflight）与第 5.1 节（auth fail-closed 已代码强制）；③ `.env.production.example` 02-A 节移除 `:latest` 默认值并注明 G0 C4 职责分离。探索报告现状矩阵结论（P0-1 缺 / P0-2 大部已有 / P0-3 有雏形缺绑定 / P0-4 分散）描述的是实现前状态，实现结果见本节与前文 §11 批注，二者不冲突。
