# S10-B：9000/9100 镜像身份隔离独立实施审批

> 审批时间：2026-08-12 17:17:08 +08:00  
> 审批角色：Independent Implementation Approval  
> 最终裁决：`APPROVED_WITH_CORRECTIONS`  
> 证据边界：仅达到 `COMPOSE_CONFIG_VERIFIED / STATIC_TEST_VERIFIED / DESIGN_CONTRACT_VERIFIED`；未达到容器运行、演练或生产运行验证。

```text
C3_IMPLEMENTATION              = APPROVED_WITH_CORRECTIONS
C3_INDEPENDENT_APPROVAL        = APPROVED_WITH_CORRECTIONS
C3                             = NOT_CLOSED_PENDING_CORRECTIONS
REHEARSAL_ENTRY_GATE           = BLOCKED_BY_MANDATORY_CORRECTIONS_C1_TO_C5
ISOLATED_REHEARSAL_ENTRY       = NOT_AUTHORIZED_UNTIL_CORRECTIONS_REVIEWED
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

---

## 1. Approval Scope

本窗口只独立审查 S10-B implementation candidate 是否实现：

```text
9000 runtime image identity 可独立指定
9100 runtime image identity 可独立指定
9000 target / rollback 不改变 9100 resolved image identity
9000 可按 service 定向处理且不隐式包含 9100
9100 不迁移、不改业务、不升级 0003→0005
BR-24~BR-30 具备下一阶段可执行的配置机制
```

本窗口未执行：

- baseline rehearsal、0028→0034 migration 或 BR-01~30；
- 容器真实 recreate/restart、镜像 pull/build/tag；
- Merchant `.env.production.local` 修改；
- 生产、staging 或本地数据库操作；
- 9100 migration、RAG、Milvus、Prompt 或业务验证；
- commit、push 或发布。

风险等级：`L3 / HIGH`。原因是该机制直接约束生产发布身份、9100 冻结边界与数据库迁移隔离。

---

## 2. Governance Baseline

审批采用以下冻结基线：

```text
PREFERRED_STRATEGY             = SCHEMA_FIRST_WITH_MAINTENANCE_WINDOW
CURRENT_PRODUCTION_9000_CODE   = f453f44
TARGET_0034_CODE_COMMIT        = 9db3f58
P2 migration 0035             = OUT OF CURRENT CATCH-UP

PRODUCTION_9100_DB             = 0003
PRODUCTION_9100_RUNTIME_IMAGE  = sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68
9100 0003→0005                = OUT OF CURRENT SCOPE

9000_9100_RUNTIME_IMAGE_SHARED = VERIFIED（当前生产事实）
风险模型                        = MUTABLE_SHARED_IMAGE_DEPLOYMENT_IDENTITY
```

本审批没有重新引入“重指 `latest` 会自动修改正在运行的 9100”这一错误结论。真实风险是未来部署/recreate 时两个服务共用可变部署身份，可能使 9100 隐式漂移。

---

## 3. Candidate Ownership

### 3.1 Pre-existing Worktree

以下 4 个未跟踪文件在 S10-B 实施前已存在，不归属本 candidate：

```text
docs/architecture/remediation/P2_M04_COORDINATED_CUTOVER_READINESS.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md
docs/architecture/remediation/PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md
```

未执行 `git clean`、破坏性 reset 或 checkout。

### 3.2 Candidate Files

S10-B candidate 归属 5 个文件：

```text
M  .env.production.example
M  docker-compose.yml
M  docs/config/ENV_VARIABLE_REFERENCE.md
?? tests/test_s10_b_image_identity_isolation.py
?? docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md
```

准确计数为：`3 个修改 + 2 个新增`。

### 3.3 Scope Classification

```text
release-engineering / config / tests / report = IN SCOPE
app/**                                         = NO DIFF
apps/**                                        = NO DIFF
migrations/**                                  = NO DIFF
frontend/**                                    = NO DIFF
19000 business code                            = NO DIFF
Dockerfile*                                    = NO DIFF
```

结论：未发现 S10-B 业务范围越界。

---

## 4. Chosen Mechanism

实施窗口选择：

```text
CHOSEN     = RE-B（Per-Service Image Variables）
NOT_CHOSEN = RE-A（Compose Override）
```

真实 Compose 配置为：

```yaml
auto-wechat-api:
  image: ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}

xg-douyin-ai-cs:
  image: ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}
```

RE-B 与冻结设计一致：两个 service 分别消费独立 image ref；未混用 RE-A override；未新增 Dockerfile、部署框架或业务层逻辑。

---

## 5. RE-A / RE-B Consistency

| 检查项 | 结论 |
|---|---|
| 是否只选择一种机制 | PASS：只采用 RE-B |
| 是否保持默认兼容 | PASS：未设置或空值按 `:-` 回落既有 `:latest` |
| 是否能同时表达两个不同 ref | PASS |
| 是否要求拆分共享 Dockerfile | NO；共享 build definition 不属于本 Gate |
| 是否把生产 SHA 写入公共 Compose/env | NO |
| 是否改变 9100 业务或 DB | NO |

---

## 6. Compose Resolution

独立使用假 identity 执行 `docker compose config --format json`，得到：

| Case | 9000 resolved image | 9100 resolved image | 结论 |
|---|---|---|---|
| UNSET | `xg-ai-system-backend:latest` | `xg-ai-system-backend:latest` | 默认兼容 |
| EMPTY | `xg-ai-system-backend:latest` | `xg-ai-system-backend:latest` | Compose 有效；生产策略必须拒绝 |
| A | `example/9000:old` | `example/9100:frozen` | 独立解析 |
| B | `example/9000:target` | `example/9100:frozen` | 只改 9000，9100 不变 |
| ROLLBACK | `example/9000:old` | `example/9100:frozen` | 9000 独立回滚 |
| 9000_ONLY | `example/9000:target` | `xg-ai-system-backend:latest` | 9000 单变量有效 |
| 9100_ONLY | `xg-ai-system-backend:latest` | `example/9100:frozen` | 9100 单变量有效 |

证据等级：`COMPOSE_CONFIG_VERIFIED`。这不是容器运行证据。

---

## 7. Runtime Guarantees RG-1~RG-8

| RG | 独立结论 | 证据等级 | 说明 |
|---|---|---|---|
| RG-1 | PASS | COMPOSE_CONFIG_VERIFIED | `AUTO_WECHAT_API_IMAGE` 可独立指定 9000 |
| RG-2 | PASS | COMPOSE_CONFIG_VERIFIED | `XG_DOUYIN_AI_CS_IMAGE` 可独立指定 9100 |
| RG-3 | PASS | COMPOSE_CONFIG_VERIFIED | A→B 时 9100 均为 `example/9100:frozen` |
| RG-4 | PASS_WITH_CORRECTION | COMPOSE_CONFIG_VERIFIED / DRY_RUN_SEMANTICS | 9000 依赖图不含 9100；完整安全命令需补 C1 |
| RG-5 | PASS | COMPOSE_CONFIG_VERIFIED | target→old 只改变 9000 ref |
| RG-6 | PASS | CODE_VERIFIED | candidate 无 9100 migration/业务差异，无新增 migration command |
| RG-7 | PASS | COMPOSE_CONFIG_VERIFIED | unset/empty 保持既有默认；dev 独立 Compose 未改 |
| RG-8 | PASS_WITH_CORRECTION | DESIGN_CONTRACT_VERIFIED | 显式不可变 ref 可避免共享 latest；production/rehearsal 失败关闭门禁需补 C2 |

RG correctness hard gate 均未失败。RG-4/RG-8 的 correction 不改变 RE-B image selection mechanism。

---

## 8. Production Identity Contract

未来 production catch-up 必须能够且只能按受控输入表达：

```text
AUTO_WECHAT_API_IMAGE = exact immutable target built from 9db3f58
XG_DOUYIN_AI_CS_IMAGE = preserved current 9100 runtime image identity
```

正式 catch-up 禁止：

- 两服务共享歧义 mutable `:latest`；
- 任一 image identity 为空；
- 两个 image ref 完全相同且无法证明各自冻结；
- target 9000 无法追溯到 `9db3f58`；
- 用全服务 `compose up -d` 隐式处理 9100。

真实 production identity 继续由 `.env.production.local` 或受控 release input 提供，本 candidate 未修改 Merchant 文件。

---

## 9. 9100 Freeze Contract

```text
9100_CODE_CHANGE      = NO
9100_DB_CHANGE        = NONE
9100_MIGRATION        = NO
9100_DB_REVISION      = 0003（保持）
9100_RECREATE         = NO（catch-up/rehearsal 操作合同）
9100 0003→0005        = OUT OF CURRENT SCOPE
```

候选只改变 Compose image 字段选择入口，没有新增 9100 command、entrypoint、migration helper 或 Alembic revision。

---

## 10. Rollback Contract

配置机制已证明可表达：

```text
9000 old / 9100 frozen
→ 9000 target / 9100 frozen
→ 9000 old / 9100 frozen
```

```text
ROLLBACK_RUNTIME_IMAGE_IDENTITY   = VERIFIED（既有生产事实）
ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED
```

不得声称旧 runtime image 等于 `f453f44`。旧镜像来源提交未验证，不影响已保存 runtime identity 可用于回滚的事实。

完整回滚执行合同仍需按 C1/C3 固化：显式 env file、双 image 解析审计、只处理 9000，并记录 9100 container/image/DB 前后不变。

---

## 11. Target Provenance

S10-B 不负责构建 target image，但机制支持未来输入不可变 tag 或 digest。

未来必须至少具备一种：

```text
immutable tag
image digest
OCI revision label
build manifest linking 9db3f58
```

目标是能够审计：`TARGET_9000_IMAGE ↔ 9db3f58`。旧 provenance debt 不得复制到新 target。

---

## 12. Mutable Latest Boundary

```text
development/default = mutable latest allowed（保持兼容）
production baseline catch-up = shared mutable latest forbidden
```

`${VAR:-default}` 对 unset/empty 会生成有效 image ref，不存在“空字符串解析成无效 image”的 Compose correctness 问题；但它会在 catch-up 语义上失败开放到共享 `latest`。因此必须在 rehearsal/production preflight 层拒绝，而不是改变全局默认兼容合同。

---

## 13. RE-AC01~RE-AC12 Matrix

| AC | 状态 | 独立证据 |
|---|---|---|
| RE-AC01 default compose works | PASS | unset 解析为既有 `:latest`；staging 组合专项测试通过 |
| RE-AC02 independent 9000 image | PASS | 9000-only 假 identity 解析通过 |
| RE-AC03 independent 9100 image | PASS | 9100-only 假 identity 解析通过 |
| RE-AC04 different refs simultaneously | PASS | A/B 同时解析为不同 ref |
| RE-AC05 change 9000 leaves 9100 stable | PASS | old→target 时 frozen 9100 逐字不变 |
| RE-AC06 service-specific 9000 recreate | PASS | service target 与依赖图均不含 9100；命令精度见 C1 |
| RE-AC07 independent 9000 rollback | PASS | target→old 时 frozen 9100 不变 |
| RE-AC08 no migration command | PASS | candidate Compose diff 未新增可执行 migration command |
| RE-AC09 no 9100 migration | PASS | 无 `apps/**` / `migrations/**` diff，9100 command 未改 |
| RE-AC10 no business behavior change | PASS | 无业务/API/RAG/前端差异 |
| RE-AC11 production mutable-latest warning/contract | PASS_WITH_CORRECTION | 文档已禁止；可执行失败关闭门禁见 C2 |
| RE-AC12 supports BR-24~30 | PASS_WITH_CORRECTION | 配置机制齐全；操作与测试合同见 C1~C4 |

无 correctness-critical `FAIL`。修正复核前不得把 `PASS_WITH_CORRECTION` 提升为无条件 PASS。

---

## 14. IA-S10 Independent Test Matrix

| 测试 | 状态 | 证据 / 说明 |
|---|---|---|
| IA-S10-01 default compose config | PASS | unset 两服务均为默认 `:latest` |
| IA-S10-02 9000-only explicit image | PASS | `example/9000:target` 生效，9100 默认不变 |
| IA-S10-03 9100-only explicit image | PASS | `example/9100:frozen` 生效，9000 默认不变 |
| IA-S10-04 9000=A / 9100=B | PASS | `example/9000:old` / `example/9100:frozen` |
| IA-S10-05 A→C while 9100=B | PASS | 9000 改为 target，9100 逐字不变 |
| IA-S10-06 rollback C→A while 9100=B | PASS | 9000 回 old，9100 逐字不变 |
| IA-S10-07 service targeting | PASS_WITH_CORRECTION | dry-run 计划未包含 9100；推荐命令需补完整 env/no-deps/no-build |
| IA-S10-08 scope guard / no business diff | PASS | 实际 Git 差异无业务目录 |
| IA-S10-09 no migration side-effect | PASS | 实际 candidate 无 migration 文件或执行命令 |
| IA-S10-10 production explicit identity contract | PASS_WITH_CORRECTION | 文档合同存在；失败关闭 preflight 尚缺 |
| IA-S10-11 BR-24~30 mechanism coverage | PASS_WITH_CORRECTION | mechanism exists；C1~C4 应用后才可进入真实演练 |

### 14.1 Candidate Tests

执行：

```text
python -m pytest tests/test_s10_b_image_identity_isolation.py -v
```

结果：`13 passed, 1 warning`。warning 为 pytest cache 路径创建失败，不影响断言结果。

### 14.2 Independent Adversarial Test

在宿主进程预设两个 IMAGE 变量后，定向运行 RE-T01~03：

```text
3 failed
```

失败证明 candidate helper 关于“`--env-file` 覆盖宿主环境”的注释不成立，动态测试没有隔离宿主环境。该缺陷影响测试可复现性，但受控独立 Compose config 已另行证明核心 RE-B 解析正确。见 C3。

### 14.3 Existing Regression

执行：

```text
python -m pytest tests/test_env_profile_templates.py -q
```

结果：`48 passed, 2 failed`。两项失败与 candidate 报告一致：

1. 既有大量代码环境变量未进入分类集合；失败清单不含两个 S10-B Compose 变量；
2. `.env.development.example` 的 outbox interval 为 10，既有测试期望 60。

这两项不属于 S10-B 变更文件，记录为 pre-existing regression baseline，不在本审批中修复。

---

## 15. Scope Guard

独立执行 `git status --short`、`git diff --stat`、`git diff --name-only`、`git diff --check`：

- 跟踪差异只有 `.env.production.example`、`docker-compose.yml`、`docs/config/ENV_VARIABLE_REFERENCE.md`；
- S10-B 测试与 implementation report 为未跟踪 candidate 文件；
- 4 个前序 remediation 文档已单独归属；
- `git diff --name-only -- app apps migrations frontend` 为空；
- `git diff --check` 无 whitespace error，仅有 Windows LF→CRLF 提示。

结论：`SCOPE_VIOLATION = NONE_DETECTED`。

---

## 16. Migration Side-Effect Audit

独立全文搜索 candidate 中 `alembic / upgrade / 0004 / 0005 / migrate / migration`，并核对真实差异：

- 命中均为说明、测试断言或 Compose 既有 readiness 注释；
- 两个 image 字段新增行不含 migration command；
- 9000/9100 service `command`、entrypoint 未改；
- 无 `migrations/**` 或 `apps/xg_douyin_ai_cs/**` 差异；
- 未执行数据库操作。

结论：

```text
9100_DB_CHANGE = NONE
9100_MIGRATION_SIDE_EFFECT = NONE_DETECTED
```

---

## 17. BR-24~BR-30 Readiness

| BR | 当前结论 | 本窗口证据 | 下一阶段真实证据 |
|---|---|---|---|
| BR-24 identities isolated | MECHANISM_EXISTS | 不同假 ref 可同时解析 | 两容器 Image ID |
| BR-25 target9000 only | MECHANISM_EXISTS_WITH_C1 | service target 不含 9100 | 9000 Image ID 前后变化 |
| BR-26 frozen9100 unchanged | MECHANISM_EXISTS | A→C 时 9100 ref 不变 | 9100 Image ID 前后相同 |
| BR-27 9100 DB 0003 | DESIGN_CONTRACT_VERIFIED | freeze contract，无 migration path | DB current before/after=0003 |
| BR-28 no 9100 recreate/migration | MECHANISM_EXISTS_WITH_C1 | 9000 service graph 不含 9100 | container ID/start/restart/current 不变 |
| BR-29 target9000 ready | NOT_VERIFIED | target image 未构建，本窗口禁止运行 | target9000 + schema0034 `/ready` 200 |
| BR-30 rollback9000 only | MECHANISM_EXISTS_WITH_C1_C3 | 配置解析可回滚 9000 | 9000 回退且 9100 全证据不变 |

统一结论：

```text
BR-24_TO_30 = MECHANISM_READY_AFTER_CORRECTIONS
BR-24_TO_30_VERIFIED = NO
CONTAINER_RUNTIME_VERIFIED = NO
PRODUCTION_RUNTIME_VERIFIED = NO
```

---

## 18. Evidence Levels

| 结论 | 证据等级 |
|---|---|
| 两服务可独立解析 | COMPOSE_CONFIG_VERIFIED |
| 9000 A→C→A、9100 B 不变 | COMPOSE_CONFIG_VERIFIED |
| 9000 service target 不含 9100 | COMPOSE_CONFIG_VERIFIED / DRY_RUN_SEMANTICS |
| 无业务范围差异 | CODE_VERIFIED |
| 无 migration side-effect | CODE_VERIFIED |
| 文档 production/freeze/provenance 合同 | DESIGN_CONTRACT_VERIFIED |
| candidate 13 tests | STATIC_TEST_VERIFIED |
| 宿主环境污染缺陷 | STATIC_TEST_FAILED_AS_EXPECTED |
| BR-24~30 容器运行结果 | NOT_VERIFIED |
| 生产运行结果 | NOT_VERIFIED |

---

## 19. Multi-role Review Synthesis

技术、发布操作者与安全三个独立视角及交叉反驳形成以下共识：

1. RE-B 核心 image selection mechanism 成立，无需重选 RE-A 或重写策略；
2. 命令缺显式 env file、旧全服务脚本歧义、production 失败开放、测试环境污染均属真实问题；
3. 这些问题可通过命令合同、preflight、测试和文档修正闭环，不改变两处 image selection expression；
4. 因此不触发 `CHANGES_REQUIRED`，但修正完成前不得打开 rehearsal Gate；
5. 证据只能标为 Compose/config/static，不得升级为 container/production runtime。

---

## 20. Blocking Findings

### 20.1 Core Mechanism Blocking Findings

`NONE_DETECTED`。

未发现以下任一 `CHANGES_REQUIRED` 条件：

- 9000/9100 无法独立解析；
- 改 9000 会改变显式冻结的 9100 resolved ref；
- service-targeted 9000 路径会包含 9100；
- 9000 rollback 无法保持 9100 frozen；
- candidate 出现业务代码范围漂移；
- candidate 引入 9100 migration side-effect；
- 必须替换 RE-B mechanism 才能支持 BR-24~30。

### 20.2 Gate Blocking Corrections

C1~C5 在复核闭环前共同阻断 rehearsal entry。

---

## 21. Corrections — MUST_APPLY_BEFORE_REHEARSAL

### C1 — 完整且唯一的 9000-only 命令合同

必须在 S10-B/BR 执行材料中固化唯一命令链：

```text
docker compose --env-file .env.production.local -f docker-compose.yml config
docker compose --env-file .env.production.local -f docker-compose.yml up -d --no-deps --no-build auto-wechat-api
```

要求：

- config 审计先于任何动作；
- 发布与回滚均显式携带受控 env file；
- 目标/回滚 image 预先构建、拉取或加载，动作阶段禁止现场 build；
- 明确普通 `up -d auto-wechat-api` 不包含 9100，但会处理 postgres 依赖，不能写成“只触碰 9000 的所有对象”；
- 明确禁止本 catch-up 使用 `production_pg_switch_and_verify.sh`、`production_pg_rollback.sh` 以及任何无 service target 的 `compose up -d`；若未来要复用，须另行做服务定向改造与审批。

### C2 — Rehearsal / Production Identity Fail-Closed Preflight

保持 development/default fallback 不变，但在 rehearsal entry 前建立可执行或明确可复核的失败关闭检查，至少拒绝：

```text
IMAGE 变量未提供或为空
任一 ref 使用 mutable :latest
两个 service 使用相同歧义 ref
9000 target 无法关联 9db3f58 provenance
9100 ref 不是批准的 frozen identity
```

检查输出只展示必要 image ref 摘要，不输出 secrets。生产真实值仍不得写入公共仓库。

### C3 — 动态测试隔离与真实冻结/回滚序列

修正 `tests/test_s10_b_image_identity_isolation.py`：

- 子进程 env 先移除两个宿主 IMAGE 变量，再按 case 注入；
- 不再声称 `--env-file` 高于宿主环境；
- 统一检测并复用 `docker compose` / `docker-compose` 命令；
- 覆盖 unset / empty / explicit 三态；
- 覆盖 `old/frozen → target/frozen → old/frozen`，逐次断言 9100 ref 完全不变；
- 命令合同测试包含显式 `--env-file`、`--no-deps`、`--no-build` 与 `auto-wechat-api` service target。

### C4 — 真实 Diff 级 Scope / Migration Evidence

候选测试中的 RE-T08/09/10 不得继续被描述为足以独立证明 Git scope 或 migration side-effect。必须：

- 将其准确标为静态合同检查，或补充真实 candidate diff guard；
- 在 correction 复核时重新执行 `git status`、`git diff --name-only`、禁止目录审计和 migration 关键词审计；
- 保持 `app/**`、`apps/**`、`migrations/**`、`frontend/**` 零 S10-B 差异。

### C5 — 文档事实与证据精度

原位修正 implementation report、env 文档与参考文档中的不准确表述：

- `2 修改 + 3 新增` → `3 修改 + 2 新增`；
- Repository Reality 标为候选前基线事实；
- “机制防漏设”改为“提供显式隔离入口，但不防漏设/误操作”；
- “IMAGE 变量不进容器”改为：Compose 插值消费；由于 `.env.production.local` 同时是 service `env_file`，真实文件中的键也会进入容器环境，但应用不消费；
- “未写入生产 SHA”准确限定为“未把完整生产 identity 硬编码到 Compose/env 配置”；
- 只使用 `COMPOSE_CONFIG_VERIFIED / STATIC_TEST_VERIFIED / DESIGN_CONTRACT_VERIFIED`，不得声称容器或生产运行已验证。

```text
C1 = MUST_APPLY_BEFORE_REHEARSAL
C2 = MUST_APPLY_BEFORE_REHEARSAL
C3 = MUST_APPLY_BEFORE_REHEARSAL
C4 = MUST_APPLY_BEFORE_REHEARSAL
C5 = MUST_APPLY_BEFORE_REHEARSAL
```

任何 correction 若需要改变两个 service 的 image selection mechanism，当前 Verdict 失效，必须重新进入实施/审批，不得以 correction 名义重写策略。

---

## 22. Non-Blocking Debt

- `ROLLBACK_SOURCE_COMMIT_PROVENANCE = UNVERIFIED`；旧 runtime identity 可用，但不可声称等于 `f453f44`。
- target 9db3f58 image 尚未构建，digest/OCI label/build manifest 尚未产生。
- 既有全服务 PostgreSQL 切换/回滚脚本不适用于本次 9100 freeze；本轮不直接重写它们。
- `tests/test_env_profile_templates.py` 两项 pre-existing failure 不属于 S10-B。
- pytest cache path warning 不影响本轮断言，但可在后续测试环境维护中处理。

---

## 23. Verdict

```text
APPROVED_WITH_CORRECTIONS
```

裁决理由：

1. RG-1~RG-8 的 correctness hard gate 均未失败；
2. RE-AC01~12 无 correctness-critical FAIL；
3. 实际 scope 干净，无业务代码或 9100 migration side-effect；
4. RE-B 可真实表达 9000 target/rollback 与 frozen 9100；
5. 发现的问题均可在不改变 image selection mechanism 的情况下修正；
6. C1~C5 是演练入口前置，不是生产授权。

当前 candidate 不得被描述为无条件批准、C3 已闭环或演练已可执行。

---

## 24. C3 Status

```text
C3_IMPLEMENTATION       = APPROVED_WITH_CORRECTIONS
C3_INDEPENDENT_APPROVAL = APPROVED_WITH_CORRECTIONS
C3                      = NOT_CLOSED_PENDING_CORRECTIONS
```

只有 C1~C5 应用并由独立复核确认后，才允许更新为：

```text
C3 = CLOSED
```

---

## 25. Rehearsal Entry Gate

```text
REHEARSAL_ENTRY_GATE     = BLOCKED_BY_MANDATORY_CORRECTIONS_C1_TO_C5
ISOLATED_REHEARSAL_ENTRY = NOT_AUTHORIZED_UNTIL_CORRECTIONS_REVIEWED
BR-24_TO_30              = MECHANISM_READY_AFTER_CORRECTIONS
```

不得在 correction 未闭环时自行进入 baseline rehearsal。

---

## 26. Production Authorization

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
PRODUCTION_BUILD_AUTHORIZED     = NO
PRODUCTION_DEPLOY_AUTHORIZED    = NO
MERCHANT_ENV_CHANGE_AUTHORIZED  = NO
```

即使 C1~C5 闭环并完成 isolated rehearsal，仍需后续独立 rehearsal approval 与 production authorization。

---

## 27. Next Stage

唯一允许的下一步：

```text
S10-B implementation correction C1~C5
→ 独立 correction review
→ C3 CLOSED
→ REHEARSAL_ENTRY_GATE OPEN
→ PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-ISOLATED-REHEARSAL
```

本窗口不得自行进入 rehearsal。

---

## 28. Documentation Impact Check

本轮新增本独立审批报告，未修改 implementation candidate 或活动治理文档。

- `CLAUDE.md / AGENTS.md`：无硬约束变化；
- `docs/ai/01~05`：无当前事实需要原位替换；
- Reality Map：无拓扑变化；
- S10-B implementation report：存在 C1~C5 待执行修正，本审批窗口按职责只报告、不代修；
- 文档影响结论：除新增本审批记录外，无活动文档影响。

---

## 29. Git Discipline / STOP

```text
DO NOT COMMIT
DO NOT PUSH
DO NOT RUN REHEARSAL
DO NOT TOUCH MERCHANT
DO NOT MIGRATE OR RECREATE 9100
```

输出本裁决后停止。
