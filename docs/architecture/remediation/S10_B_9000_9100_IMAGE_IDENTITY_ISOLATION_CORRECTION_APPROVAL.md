# S10-B：9000/9100 部署镜像身份隔离 — Focused Correction Approval

> 本窗口为 **S10-B Image Identity Isolation Focused Correction Approval**（独立复核窗口）。
> 唯一职责：独立复核 **C1～C5** 与 Correction-1 的实际 diff，不重新审 RE-B 设计、0028→0034、P1/P2、9100 0003→0005。
> 产物为本审批报告，**未 commit / 未 push / 未修改 correction candidate / 未操作 Merchant / 未跑 rehearsal / 未建未推镜像**。

```text
窗口模式   = STRICT APPROVAL（只读 + 静态/动态机制验证，禁止 candidate 修改）
Git 纪律  = DO NOT COMMIT / DO NOT PUSH
生产纪律  = 禁止 Merchant docker/env/git/DB，禁止 tag/build/recreate
```

---

## 1. Focused Scope

本窗口只独立复核：

```text
C1 canonical 9000-only release command
C2 fail-closed image identity preflight
C3 host environment pollution closure
C4 real Git diff / migration side-effect audit
C5 evidence/documentation correction
```

明确不重新审批（除非 Correction-1 破坏既有边界，复核未发现破坏）：

```text
RE-B architecture / S10-B design strategy / 0028→0034 migration chain
P1 correctness / P2 correctness / 9100 0003→0005
```

## 2. Prior Verdict（前序独立审批）

```text
C3_IMPLEMENTATION              = APPROVED_WITH_CORRECTIONS
C3                             = NOT_CLOSED_PENDING_CORRECTIONS
REHEARSAL_ENTRY_GATE           = BLOCKED_BY_MANDATORY_CORRECTIONS_C1_TO_C5
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

## 3. Candidate Files（Correction-1 涉及）

```text
scripts/release_9000_s10b.py                                                新增
tests/test_s10_b_image_identity_isolation.py                                新增（原实施）+ correction 扩展
.env.production.example                                                      修改（02-A 分组）
docker-compose.yml                                                          修改（两处 image env 化 + 注释）
docs/config/ENV_VARIABLE_REFERENCE.md                                       修改（Compose 镜像身份小节）
docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md  修改（C5 修正 + Correction-1 章节）
```

均经真实 Read / `git diff` 核实，非仅引用报告。

## 4. Real Diff Ownership

`git status --short` / `git diff --name-only` / `git diff --stat` 真实输出：

```text
tracked modified (3):
  .env.production.example          +41 -0
  docker-compose.yml               +13 -2
  docs/config/ENV_VARIABLE_REFERENCE.md  +33 -0
untracked (7):
  docs/architecture/remediation/P2_M04_COORDINATED_CUTOVER_READINESS.md         PRE_EXISTING
  docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md        PRE_EXISTING
  docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md PRE_EXISTING
  docs/architecture/remediation/PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md PRE_EXISTING
  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md       S10_B_IMPLEMENTATION
  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md S10_B_IMPLEMENTATION + CORRECTION_1
  scripts/release_9000_s10b.py                                                               S10_B_CORRECTION_1
  tests/test_s10_b_image_identity_isolation.py                                              S10_B_IMPLEMENTATION + CORRECTION_1
```

分类结果：

```text
PRE_EXISTING_WORKTREE          = 4（catch-up / P2 remediation 文档）
S10_B_IMPLEMENTATION_DIFF      = docker-compose.yml + .env.production.example + docs/config/ENV_VARIABLE_REFERENCE.md + 2 份 S10-B 报告 + tests
S10_B_CORRECTION_1_DIFF        = scripts/release_9000_s10b.py + tests 扩展 + .env.production.example/docs/config 修正 + 实施报告 C5 修正章节
UNKNOWN_OWNERSHIP              = 0
```

DIRTY WORKTREE ≠ FAIL（前序 candidate 未 commit，符合预期）；所有 changed file 可分类。

## 5. C1 Review — Canonical Command

### 6. Canonical Command（§4/§5）

`scripts/release_9000_s10b.py::canonical_up_command()` 真实代码（line 181-185）：

```python
return _pick_compose_cmd() + [
    "--env-file", str(env_file),
    "-f", str(COMPOSE_FILE),
    "up", "-d", "--no-deps", "--no-build", "auto-wechat-api",
]
```

语义等价于：

```text
docker compose --env-file <explicit env file> -f docker-compose.yml up -d --no-deps --no-build auto-wechat-api
```

C1 六点独立确认（§5）：

| 项 | 验证 | 结论 |
|---|---|---|
| C1-A 显式 `--env-file` | line 182 | ✅ |
| C1-B 显式 `-f docker-compose.yml` | line 183（COMPOSE_FILE = ROOT/docker-compose.yml, line 37） | ✅ |
| C1-C `up -d` | line 184 | ✅ |
| C1-D `--no-deps` | line 184 | ✅ |
| C1-E `--no-build` | line 184 | ✅ |
| C1-F 唯一 service target = `auto-wechat-api` | line 184，`cmd.count("auto-wechat-api")==1`（test_c1_canonical_command_contract） | ✅ |

### 7. Sanitized Environment Propagation（§7/§8 最高优先级）

**这是本次审批最高优先级之一。** 必须证明 `compose_env()` sanitization 不只用于 preflight/test，也传给真正 canonical `up` subprocess。

真实调用链追踪：

```text
main(argv)
  ├─ preflight(args.env_file, expected)                # line 212
  │    └─ resolve_images → compose_config(env_file, host_env=None)
  │         └─ subprocess.run(..., env=compose_env(host_env))   # line 94  ← sanitized
  └─ run_apply(args.env_file)  [仅 --apply]            # line 223
       └─ canonical_up_command(env_file)
            └─ subprocess.run(cmd, env=compose_env(host_env), ...)  # line 191  ← SAME sanitized
```

- `compose_config`（preflight 路径）line 94：`env=compose_env(host_env)`
- `run_apply`（actual up 路径）line 191：`env=compose_env(host_env)`

**SAME_SANITIZED_ENV = CONFIRMED**：preflight 与 actual canonical up subprocess 走**同一** `compose_env()` 函数。actual up subprocess 不会重新继承原始宿主 IMAGE 变量——§8 描述的 blocking bug（preflight 用 sanitized env、actual up 用原宿主 env）**不存在**。

`main()` 调用 preflight 与 run_apply 均不传 host_env（`host_env=None`），二者均用 `compose_env(None)` = 以 `os.environ` 为基底移除两个 IMAGE 变量。一致。

### 8. C1 旁路检查（§6）

搜索 wrapper / docs / helper，未发现另一同级受支持路径。`.env.production.example` 02-A、`docs/config/ENV_VARIABLE_REFERENCE.md`、实施报告均只文档化**单一** canonical 命令 + wrapper 入口；`docker compose restart auto-wechat-api` / 无 `--no-deps` 的 `up -d` / 全服务 `up -d` / `build + up` 均未作为正式推荐路径（`test_c1_restart_not_used_as_image_switch` 断言 canonical 不含 `restart`）。

```text
SUPPORTED_9000_ONLY_RELEASE_COMMAND = ONE CANONICAL CONTRACT（无旁路）
```

## 9. C2 Review — Fail-Closed Preflight

### 10. Resolved Compose Identity（§9/§10）

`preflight()` → `resolve_images()` → `compose_config()` 真实执行 `docker compose --env-file <ENV> -f docker-compose.yml config --format json`（line 87-99），从**最终 Compose resolution** 取 `services[svc]["image"]`，而非仅解析 `.env` 文本。

```text
RESOLVED_9000_IMAGE = services["auto-wechat-api"]["image"]
RESOLVED_9100_IMAGE = services["xg-douyin-ai-cs"]["image"]
来源 = 最终 Compose resolution ✅
```

### 11. Fail-Closed Cases（§11/§12/§13/§14）

测试 `TestPreflightFailClosed`（C2-T01~T11 + P4 边界 + digest）37 passed 独立执行确认。逐项：

| Case | 测试 | 结果 |
|---|---|---|
| missing 9000 image（回落 :latest） | C2-T02 | FAIL ✅ |
| empty 9000 image | C2-T04 | FAIL ✅ |
| missing 9100 image | C2-T03 | FAIL ✅ |
| empty 9100 image | C2-T05 | FAIL ✅ |
| 9000 ambiguous :latest | C2-T06 | FAIL ✅ |
| 9100 ambiguous :latest | C2-T07 | FAIL ✅ |
| expected9000 mismatch | C2-T09 | FAIL ✅ |
| expected frozen9100 mismatch | C2-T08 | FAIL ✅ |
| env file missing | C2-T10 | FAIL ✅（exit code 1 独立复现） |
| compose config failure（非法 env 语法） | C2-T11 | FAIL ✅ |
| 相同共享 mutable :latest | C2-P4 | FAIL ✅ |
| 相同 immutable（rollback/freeze 合法） | C2-P4-same-immutable | PASS ✅（§12 边界正确：不误禁 immutable 相同） |
| `repo@sha256:<digest>` | C2-digest | PASS ✅ |

`exit code != 0` 独立 CLI 验证：missing env file → exit 1；expected mismatch → exit 1。

### 12. 相同 Image Identity 边界（§12）

P4 实现仅拒绝「相同 **shared mutable** identity」（`not is_immutable` 条件，line 151-161），相同 immutable 是合法状态（STATE A/C：9000 rollback old image == 9100 frozen old image），不拒绝。未临时扩大规则为「same immutable digest always invalid」。✅

### 13. Mutable Latest 检查（§13）

`is_immutable`（line 108-115）拒绝精确 known mutable `:latest` 后缀（`MUTABLE_LATEST_RE = re.compile(r":latest$")`），覆盖 `xg-ai-system-backend:latest`。文档与代码均诚实声明：只拒绝 known mutable default，**不声称验证 registry-side immutability / digest 存在性**（实施报告 §17.5 / §12）。

### 14. Expected Identity Verification（§14）

wrapper 支持 `--expected-9000` / `--expected-9100`（line 204-205），preflight line 162-166 显式比较 `expected` 与 `resolved`，不一致即 fail。operator 写错 env 时即便非 `:latest` 也 fail closed。✅

### 15. C2 Side-Effect Boundary（§15）

preflight 默认 static 模式只 `compose config` + 校验，无 `docker pull` / `build` / `compose up` / `restart` / `tag` / `alembic` / DB write。`--dry-run` 打印命令不执行；`--apply` 才执行 canonical up。grep `release_9000_s10b.py` 命中 `build/pull/tag/restart` 仅出现在 docstring/help 文本，无 subprocess 调用。✅

## 16. C3 Review — Host Pollution 根因与修复

### 17. Compose Precedence Reproduction（§16 独立复现）

本窗口用 dummy values 独立可控复现（真实 `docker compose config`，compose version v5.3.0）：

```text
host shell env:
  AUTO_WECHAT_API_IMAGE=host-wrong-9000
  XG_DOUYIN_AI_CS_IMAGE=host-wrong-9100
env file:
  AUTO_WECHAT_API_IMAGE=file-target-9000
  XG_DOUYIN_AI_CS_IMAGE=file-frozen-9100
```

**Case A（未经 sanitization，宿主 env + --env-file）**：

```text
resolved 9000 = host-wrong-9000   ← 宿主胜出
resolved 9100 = host-wrong-9100
```

**确认 Compose precedence：宿主 shell env > --env-file**。原候选声称「--env-file 覆盖宿主环境」不成立，C3 根因真实。

### 18. Sanitization Verification（§17）

**Case B（wrapper `compose_env()` sanitization，移除宿主 IMAGE 变量后 + --env-file）**：

```text
resolved 9000 = file-target-9000   ← env-file 生效
resolved 9100 = file-frozen-9100
```

```text
HOST_ENV_POLLUTION_REGRESSION = VERIFIED_CLOSED
```

### 19/20/21. Sequence / 断言 / Test Isolation（§18~§21）

`TestUpgradeFreezeRollbackSequence.test_full_sequence_with_real_resolution` 用真实 compose config resolution 验证 STATE A/B/C，逐项断言（非模糊链式）：

```text
A.9100 == B.9100 == C.9100 == FROZEN_9100_IMAGE   ✅（9100 全程冻结）
A.9000 != B.9000                                    ✅（升级变化）
B.9000 != C.9000                                    ✅（回滚变化）
C.9000 == A.9000                                    ✅（回滚还原）
```

Test Isolation（§20）：每个测试经 `_write_env_file` 写临时 env file + `compose_env(host_env=...)` / `host_env` 参数显式控制，不依赖 `os.environ` 的 IMAGE 值。`TestHostEnvPollutionRegression` 为**专门**针对 pre-set hostile IMAGE env 的回归测试（§21，非「其他测试顺便通过」）：pre-set hostile host env 下 preflight 与真实 compose config 仍解析到 testcase 指定值。✅

## 22. Targeted Test Results（§22 独立执行）

本窗口独立运行：

```text
python -m pytest tests/test_s10_b_image_identity_isolation.py -q
→ 37 passed, 1 warning in 3.65s
```

实际：**37 passed / 0 failed**。动态测试（依赖 docker）全 PASS，静态契约测试全 PASS。

## 23/24/25. C4 Scope Audit / Hard Scope Guard（§23~§25）

`git diff --name-only` 真实输出 tracked modified 仅 3 文件（§4）。S10-B candidate/correction **未引入** `app/**` / `apps/**` / `migrations/**` / `frontend/**` 任何修改。无 pre-existing diff 在这些目录需证明无关。✅

```text
SCOPE_VIOLATION = NONE_DETECTED
```

### 26/27/28/29. Migration Side-Effect Audit（§26~§29）

grep `release_9000_s10b.py` for `alembic|upgrade head|downgrade|0004|0005|0035` → **No matches**。wrapper 无 `alembic upgrade` / DB access / 9100 DB command。docker-compose.yml diff 仅改 `image:` 字段 + 注释，无 migration 命令。

```text
S10_B_EXECUTABLE_MIGRATION_SIDE_EFFECT = NONE
9100_DB_CHANGE = NONE
9100_MIGRATION_SIDE_EFFECT = NONE
```

canonical up 使用 `--no-build`；wrapper 无 `docker build` / `pull` / `tag`（§28）。9100 不作为 Compose service target，仅 `compose config` 过程中读取其配置（§29，`canonical_up_command` 仅含 `auto-wechat-api`）。

### 30/31/32. Pre-existing Failure Evidence（§30~§32）

独立运行 `tests/test_env_profile_templates.py` → **48 passed, 2 failed**，与报告声称一致：

```text
1. test_all_code_variables_are_classified
2. test_outbox_ten_variables_exact_defaults  → .env.development.example AI_AUTO_REPLY_OUTBOX_INTERVAL_SECONDS=10 期望 60
```

证据等级（§31，本窗口未做完整 baseline checkout 重跑，使用强静态证据，如实标注）：

```text
PRE_EXISTING_FAILURE_EVIDENCE = STATIC_CAUSAL_VERIFIED + GIT_HISTORY_VERIFIED
```

- **outbox failure**：`git diff --name-only -- .env.development.example` 输出**空**（S10-B 未触碰 dev example）；`git log` 显示该文件最近提交为 `d351455 decode超时收紧` / `1939da1 抖音客服联系方式` / `5e6c4a0 统一回复内核`，均非 S10-B。当前 dev example 的 `AI_AUTO_REPLY_OUTBOX_INTERVAL_SECONDS=10` 是其他窗口引入的既有事实。
- **classification failure**：该测试扫描 app/apps/frontend 代码读取点；S10-B 两个变量（`AUTO_WECHAT_API_IMAGE` / `XG_DOUYIN_AI_CS_IMAGE`）为 compose 级插值，不被 app 代码读取，且 S10-B 未改 app/apps/frontend 代码。未分类清单为既有 `LAS_*` / `TOS_*` / `ARK_*` / `DAILY_REPORT_*` 等变量，非本窗口。

**NOT REGRESSION**（§32）。

## 33/34/35. C5 Documentation Review / Evidence Level / BR-24~30（§33~§35）

实施报告 `S10_B_..._IMPLEMENTATION.md` 经 C5 原位修正后准确反映 Correction-1 事实：

- 计数修正 `3 修改 + 2 新增`（§1）
- 证据等级仅使用 `COMPOSE_CONFIG_VERIFIED / STATIC_TEST_VERIFIED / DESIGN_CONTRACT_VERIFIED / PREFLIGHT_STATIC_VERIFIED / COMMAND_CONTRACT_VERIFIED / MECHANISM_READY_FOR_REHEARSAL`（§7/§14），**未出现** `CONTAINER_RUNTIME_VERIFIED` / `PRODUCTION_RUNTIME_VERIFIED`（test_c5_report_evidence_levels_not_overstated PASS）。
- BR-24~BR-30 统一 `MECHANISM_READY_FOR_REHEARSAL = NOT EXECUTED`，未写成 `PASS` / `VERIFIED` / `CLOSED` 作为 runtime 结果（§14）。

## 36. Env Docs Accuracy（§36/§37/§38）

`.env.production.example` 02-A + `docs/config/ENV_VARIABLE_REFERENCE.md` 准确描述：

- per-service image 变量 / dev 默认行为 / production-rehearsal 显式 identity 要求
- 宿主 env precedence 警告（宿主 shell env > --env-file，已真实验证）
- wrapper sanitization + canonical 命令 + fail-closed preflight
- 公共模板值保持 `:latest`（非生产硬编码 SHA），仅在注释声明 catch-up 必须替换为 immutable identity（§37：生产 identity 不泄露为公共模板默认值；历史 remediation 报告中 `sha256:93094f0...` 作为已验证事实存在，未进入公共模板）。✅
- Secret safety（§38）：wrapper 输出仅 resolved image identity + `identity isolation PASS` / reason，不打印完整 env file / secret / DB password / API key。✅

## 39/40. Canonical CLI Error Handling / Dry-Run Boundary（§39/§40）

独立 CLI 验证：

| 场景 | exit | 行为 |
|---|---|---|
| missing env file | 1 | clear reason，无副作用 ✅ |
| expected mismatch | 1 | clear reason ✅ |
| valid dry-run | 0 | 打印 canonical 命令，**不执行 up** ✅ |

dry-run 仍做 sanitize → resolve → preflight → show canonical command，不跑 compose up。✅

## 41. Test Matrix — 独立验证结果

```text
FA-C1-01 canonical command exact semantics        PASS
FA-C1-02 same sanitized env reaches up subprocess PASS（§7，SAME_SANITIZED_ENV）
FA-C2-01 valid identities PASS                    PASS
FA-C2-02 latest FAIL                              PASS
FA-C2-03 expected9000 mismatch FAIL              PASS
FA-C2-04 frozen9100 mismatch FAIL                PASS
FA-C2-05 missing env file FAIL                   PASS
FA-C3-01 reproduce host precedence               PASS（Case A 宿主胜出）
FA-C3-02 sanitization defeats hostile host env   PASS（Case B file 胜出）
FA-C3-03 baseline A/B                            PASS
FA-C3-04 upgrade C/B                             PASS
FA-C3-05 rollback A/B                            PASS
FA-C3-06 9100 stable across all states           PASS
FA-C4-01 real diff ownership                     PASS（UNKNOWN_OWNERSHIP=0）
FA-C4-02 no business diff                        PASS（app/apps/migrations/frontend=ZERO）
FA-C4-03 no migration side effect               PASS（NONE）
FA-C4-04 pre-existing two failures evidence      PASS（STATIC_CAUSAL + GIT_HISTORY，非 regression）
FA-C5-01 evidence levels accurate                PASS
FA-C5-02 BR-24~30 marked NOT EXECUTED           PASS
FA-C5-03 env docs accurate                       PASS
```

## 42/43. 未运行 BR-24~30 / 未运行 0028→0034（§42/§43）

本窗口未 start containers / recreate9000 / verify container IDs / run target9000 / run frozen9100，未 create drifted0028 fixture / alembic upgrade0029…。仅机制验证。✅

## 44/45/46. Blocking / Non-Blocking Findings

### 23. Blocking Findings

```text
NONE
```

C1～C5 全部独立闭环，未发现需 CHANGES_REQUIRED 的安全机制缺陷。

### 24. Non-Blocking Findings

```text
N1  Pre-existing failure 证据等级为 STATIC_CAUSAL_VERIFIED + GIT_HISTORY_VERIFIED（未做完整 baseline checkout 重跑）。
    非阻断：git diff --name-only 证明 .env.development.example 未被 S10-B 触碰，outbox=10 为其他窗口既有事实；
    classification 未分类变量不含 S10-B compose 变量。符合 §31 强静态证据口径。

N2  is_immutable 仅拒绝精确 :latest 后缀，不验证 registry-side immutability / digest 存在性。
    非阻断：文档已诚实声明此范围（§13/§17.5），符合 §13「不要求完整 registry immutability proof」。

N3  P4 与 per-service P3 在「两服务均 :latest」场景下会产生重复 error 记录（多个 fail reason）。
    非阻断：仍 fail-closed（exit 1），仅 error 列表略冗余，不影响安全判定。
```

以上均为文档已声明的已知范围或行为冗余，**不涉及 sanitization / preflight / canonical command / scope / test reliability** 的实际机制修改，不影响安全闭环。

## 25. Verdict

```text
APPROVED
```

## 26. C1-C5 Final Status

```text
C1 = CLOSED   （canonical 唯一合同 + SAME_SANITIZED_ENV + 无旁路）
C2 = CLOSED   （resolved compose identity + fail-closed 全 case + expected 校验 + 无副作用）
C3 = CLOSED   （host precedence 独立复现 + sanitization 修复 + 序列断言 + 专门回归测试）
C4 = CLOSED   （real diff ownership 可分类/UNKNOWN=0 + scope ZERO 业务/migration + pre-existing 非 regression）
C5 = CLOSED   （报告/env 文档准确 + 证据等级不超限 + BR-24~30 NOT EXECUTED + 无 SHA 泄露 + secret safe）

HOST_ENV_POLLUTION_GAP = CLOSED
```

## 27. C3 Final Status

```text
C3_IMPLEMENTATION = APPROVED
C3                 = CLOSED
```

## 28. Rehearsal Entry Gate

```text
S10_SHARED_IMAGE_COUPLING = MITIGATION_IMPLEMENTED_AND_APPROVED
REHEARSAL_ENTRY_GATE      = OPEN
ISOLATED_REHEARSAL_ENTRY  = AUTHORIZED
```

## 29. Production Authorization

```text
PRODUCTION_MIGRATION_AUTHORIZED = NO
```

REHEARSAL AUTHORIZED ≠ PRODUCTION AUTHORIZED，不跨级。

## 30. Next Stage

```text
下一阶段：PRODUCTION-BASELINE-CATCHUP-0028-TO-0034-ISOLATED-REHEARSAL（BR-24~30 独立 Rehearsal 窗口）
  → 在隔离环境真实验证容器运行：target9000 + schema0034 → /ready 200，frozen9100 不 recreate / DB 保持 0003
  → Rehearsal 通过后由独立窗口授权生产 cutover（不在本窗口范围）
```

---

## Git / 生产纪律

```text
DO NOT COMMIT
DO NOT PUSH
未修改 correction candidate（本窗口只新增本审批报告）
未操作 Merchant docker/env/git/DB
未 build/tag/recreate 任何镜像或容器
未跑 baseline rehearsal / 0028→0034 / 9100 0003→0005 / 0035
```

审批窗口只报告，不边审边修。N1/N2/N3 为 non-blocking 已知范围，无需在本窗口处理。
