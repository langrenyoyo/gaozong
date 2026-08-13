# 0028→0034 生产追平 — Release Manifest（冻结制品）

> 窗口：PRODUCTION-BASELINE-CATCHUP-0028-TO-0034 / RELEASE-PACKAGE-FREEZE
> 冻结时间：2026-08-12
> Manifest 归属：本窗口产物，**不进入 release commit**（记录 RELEASE_TREE_COMMIT 的审计文件，避免自引用歧义）。
> 上游治理：`S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md`（APPROVED_WITH_CORRECTIONS）+ `S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md`（APPROVED，C1~C5 CLOSED）。

```text
RELEASE_ID                        = B7-0034-S10B-FREEZE-001
APPLICATION_BASE_COMMIT           = 9db3f5854095e483a55724e66d452792b354ff53
RELEASE_TREE_COMMIT               = a633b4860b818ab48fda5e22f39aa311eb96e9eb
RELEASE_BRANCH                    = release/b7-0034-s10b-freeze（LOCAL ONLY，DO NOT PUSH）
MIGRATION_TARGET                  = 0034
MIGRATION_HEAD                    = 0034（release tree 中 auto_wechat postgres Alembic head）
S10_B_ARTIFACT_IDENTITY           = RE-B per-service image env var + release_9000_s10b.py wrapper（C1/C2/C3 已审批闭环）
CREATION_TIMESTAMP                = 2026-08-12
GIT_TREE_IDENTITY                 = a633b48^{tree}（见下方 git tree hash）
REPRODUCIBILITY                   = VERIFIED（fresh reconstruction PASS，详见 Freeze 报告 §RF-T15）
```

---

## 1. 身份分离（三 identity 契约）

| identity | 值 | 说明 |
|---|---|---|
| APPLICATION_BASE | `9db3f58` | 0028→0034 追平目标应用代码基线，**业务代码目标不变** |
| RELEASE_ENGINEERING_OVERLAY | S10-B approved artifact | 已独立 APPROVED（实施 + Correction-1 C1~C5 CLOSED）的 release-engineering 机制 |
| MIGRATION_TARGET | `0034` | 9000 PostgreSQL Alembic target revision |

```text
RELEASE_TREE = 9db3f58（application base） + S10-B overlay（release engineering only）
RELEASE_TREE ≠ 36fe68a（current master，含 0035 / P2，禁止作 target tree）
```

---

## 2. Release Tree 相对 9db3f58 的完整差异

`git diff --name-status 9db3f58 <RELEASE_TREE_COMMIT>`：

```text
M  .env.production.example
M  docker-compose.yml
M  docs/config/ENV_VARIABLE_REFERENCE.md
A  scripts/release_9000_s10b.py
A  tests/test_s10_b_image_identity_isolation.py
A  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md
A  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md
A  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md
```

```text
APPROVED_S10B_RUNTIME = docker-compose.yml、scripts/release_9000_s10b.py
APPROVED_S10B_DOC     = .env.production.example（template）、docs/config/ENV_VARIABLE_REFERENCE.md、
                        S10-B 三份审批/实施报告（audit-only）
APPROVED_S10B_TEST    = tests/test_s10_b_image_identity_isolation.py
UNKNOWN               = 0
```

---

## 3. 每文件 SHA256（从 release tree blob 计算）

| 路径 | SHA256 | 分类 |
|---|---|---|
| `.env.production.example` | `9981c2cd75f969bae54fa09191430259de88f46ac5c307f43856f3a5a7203e69` | DOC / template |
| `docker-compose.yml` | `bde9d8334a0575495398725071ce5f928ba96d0e0a1484a6190efe49a9e6425d` | RUNTIME |
| `docs/config/ENV_VARIABLE_REFERENCE.md` | `4b2804fe6bd561800aac37e1f44f42f4a0f4d572f22ce35d4843e53523baf10d` | DOC |
| `scripts/release_9000_s10b.py` | `38a65f270963a712e13fce163ff85f43e3263743cf56ee20fc3d882725fa399c` | RUNTIME |
| `tests/test_s10_b_image_identity_isolation.py` | `f7c278b6bac48f884632ed0e754b516fb3603d478eb14ceee9e29e3ca316140d` | TEST |
| `docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md` | `6a5781acdce7334b963aaf5bdf45d3836a5288c53b835947103f813106b14650` | AUDIT |
| `docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md` | `4cdb5cde2731391c03393b60a59c968198864f78763f1b56a707226ebab19fb5` | AUDIT |
| `docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md` | `91f4fe6aa74df5b484b4f708a2f4ec6ecddb53e7b7e0bca303eb7fe8d85d33a0` | AUDIT |

### 3.1 Machine-readable SHA256SUMS

```text
9981c2cd75f969bae54fa09191430259de88f46ac5c307f43856f3a5a7203e69  .env.production.example
bde9d8334a0575495398725071ce5f928ba96d0e0a1484a6190efe49a9e6425d  docker-compose.yml
4b2804fe6bd561800aac37e1f44f42f4a0f4d572f22ce35d4843e53523baf10d  docs/config/ENV_VARIABLE_REFERENCE.md
38a65f270963a712e13fce163ff85f43e3263743cf56ee20fc3d882725fa399c  scripts/release_9000_s10b.py
f7c278b6bac48f884632ed0e754b516fb3603d478eb14ceee9e29e3ca316140d  tests/test_s10_b_image_identity_isolation.py
6a5781acdce7334b963aaf5bdf45d3836a5288c53b835947103f813106b14650  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_APPROVAL.md
4cdb5cde2731391c03393b60a59c968198864f78763f1b56a707226ebab19fb5  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md
91f4fe6aa74df5b484b4f708a2f4ec6ecddb53e7b7e0bca303eb7fe8d85d33a0  docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_CORRECTION_APPROVAL.md
```

---

## 4. Explicit Forbidden Content

```text
0035                                     = NOT INCLUDED（Alembic 0035_wechat_task_claim_lease.py ABSENT）
P2 M04 claim/lease application deployment = NOT INCLUDED（app/** / tests/test_p2_m04_claim_lease.py 零差异）
9100 migrations 0004/0005                = NOT TARGETED（release tree 与 9db3f58 完全一致，保持 ZERO DIFF）
business code changes                    = NONE（app/** apps/** frontend/** ZERO DIFF）
```

> 注意：`migrations/versions/0035_douyin_webhook_event_merchant_scope.sql` 是 **SQLite 轨道**迁移（`migrations/versions/`，非 PG Alembic revision graph），在 9db3f58 中已存在，属既有一致内容，**不影响** `AUTO_WECHAT POSTGRES ALEMBIC HEAD = 0034` 判断。

---

## 5. 9100 边界

```text
9100_CODE_CHANGE      = NO
9100_DB_CHANGE        = NONE
9100_MIGRATION        = NO
9100_DB_REVISION      = 0003（生产冻结保持；release tree 不引入任何 9100 升级）
9100_RECREATE         = NO（catch-up/rehearsal 操作合同，由 canonical 9000-only 命令保证）
9100 0003→0005        = NOT TARGETED
```

---

## 6. Runtime-Critical Required Files（Production Execution 必须部署）

```text
docker-compose.yml                       # 唯一 production 主入口，image 字段已 env 化
scripts/release_9000_s10b.py             # canonical 9000-only release wrapper + fail-closed preflight
.env.production.example                  # template（生产真实值由 .env.production.local / 受控 release input 注入，不打包）
```

**以下为 audit/test-only，部署可携带但不参与运行**：`tests/test_s10_b_image_identity_isolation.py`、`docs/config/ENV_VARIABLE_REFERENCE.md`、S10-B 三份报告。

---

## 7. Offline Transferability

- Release identity 为本地 git commit（`a633b48`），可 `git archive` / `git bundle` 离线转移；
- 每文件 SHA256 已在本地生成（§3），Merchant 侧可 `sha256sum -c` 本地校验；
- 不要求 Merchant maintenance 期间 `git pull / fetch / download dependency`。

---

## 8. Target Image Provenance Contract

```text
APPLICATION_BASE            = 9db3f58
RELEASE_ENGINEERING_OVERLAY = S10-B approved artifact
RELEASE_TREE                = a633b48（immutable）
TARGET_9000_IMAGE           = 未来由 Production Execution 从 RELEASE_TREE 构建，必须链接到 RELEASE_TREE_ID
（不得再只写 source=9db3f58；必须能证明 TARGET_9000_IMAGE ↔ a633b48 / 9db3f58 链）
```

---

## 9. 相关治理文档指针（不进 release commit，保留主工作区）

```text
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_DESIGN_APPROVAL.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_REHEARSAL_APPROVAL.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_ISOLATED_REHEARSAL.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_PRODUCTION_AUTHORIZATION.md
docs/architecture/remediation/PRODUCTION_SCHEMA_BASELINE_CATCHUP_0028_TO_0034_REALITY_AUDIT.md
docs/architecture/remediation/PRODUCTION_BASELINE_CATCHUP_0028_TO_0034_RELEASE_PACKAGE_FREEZE.md
docs/architecture/remediation/P2_M04_COORDINATED_CUTOVER_READINESS.md
```
