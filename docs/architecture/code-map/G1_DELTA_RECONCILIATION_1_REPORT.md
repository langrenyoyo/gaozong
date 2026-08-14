# G1 代码现实地图增量对账报告（G1-DELTA-RECONCILIATION-1）

> 任务：G1-DELTA-RECONCILIATION-1（GOVERNANCE_CODE_REALITY_MAP_DELTA / AUDIT_UPDATE_VERIFY）
> 结论：G1 = **COMPLETE_AND_CURRENT**（2026-08-14）
> 范围：G1 candidate（d1fbd04）→ CURRENT HEAD（44c5914）之间真实发生的代码/治理增量
> 本报告对账增量，不重做 G1（原 G1 基线见 `G1_CODE_REALITY_MAP_BUILD_REPORT.md`）

---

## 1. 基线

| 项 | 值 |
|---|---|
| G1_ORIGINAL_BASE | `88235b5bba363fd0dec4945b8e38aba1e82e2d9b` |
| G1_SCOPE_COMMIT | `8317778` |
| G1_CANDIDATE | `d1fbd046da9f9c63b17912f0311d7201441ffdfe` |
| G1_TREE | `f8825e092b3bfa005bc633dca0c63335c4d871ee` |
| BASE_G1_SHA | `d1fbd046da9f9c63b17912f0311d7201441ffdfe` |
| CURRENT_HEAD_BEFORE | `44c591434f5c968a2b06c7a46cf33e43c88c5e6e` |
| DELTA_RANGE | `d1fbd04..44c5914`（4 commits，全非 docs 变更） |

DELTA_RANGE 内 commits（倒序）：
- `44c5914` fix: 补齐前端不可变镜像发布链路（D4）
- `8968c8f` fix: 修复素材上传成功后的前端假失败提示（D3）
- `97528ae` fix: 修正发布预检镜像迁移目录识别（D2）
- `ace33f1` 修复: 修复素材库历史视频签名过期（D1）

分母演进验证：88235b5..d1fbd04 之间非 docs 变更 = 0（仅 docs-only），故 G1 的 957 分母在 d1fbd04 时精确成立；d1fbd04..HEAD 新增 8 个非 docs 文件、0 删除。

## 2. 增量对账（D1~D4）

### D1 — M05 历史素材 presign hotfix（owner=M05，非 PLATFORM/非 M06）

- commit：`ace33f1`（master delta 内，业务源码）。
- 生产分支补充：`0ceee54f`（"测试: 补充素材重签商户隔离验证（MERCHANT_ISOLATION）"，+64 行测试）位于 `a633b48`（生产追平发布）分支之上，**不在 master 线性历史**；该分支版本 HEAD 的 `tests/test_ai_edit_presign_refresh.py` 不含 MERCHANT_ISOLATION 用例（0 occurrences），但 HEAD 业务代码 `app/routers/ai_edit.py` 已含 merchant isolation（`_merchant(context)` + `list_materials(db, merchant_id=)` + 幂等刷新同 `merchant_id + source_sha256`）。本对账如实记录该分支差异，不影响 master reality map。
- 文件：`app/routers/ai_edit.py`（M 修改，仍 MIXED BC-02，ownership/dependency 不变）+ `tests/test_ai_edit_presign_refresh.py`（A 新增 → FILE-000963，MODULE/M05/TEST）。
- 能力：历史 TOS presigned URL 过期刷新（`_refresh_expired_presigned_urls`）、cloud_storage_key 持久化、历史 object key recovery（`_object_key_from_presigned_url`）、merchant isolation。
- 结论：**M05 historical material presign = CLOSED**。

### D2 — G0-R2 migration probe path fix（owner=PLATFORM / release governance）

- commit：`97528ae`。
- 文件：`scripts/release_9000_s10b.py`（M 修改，owner PLATFORM-RELEASE 不变）+ `tests/test_release_g0_hardening.py`（M 修改，owner PLATFORM-RELEASE 不变）+ `tests/test_release_g0_r2_migration_dirs.py`（A 新增 → FILE-000964，PLATFORM/RELEASE/TEST）。
- 能力：9000 migration dir = `/workspace/migrations/postgres/auto_wechat`；9100 = `/workspace/migrations/postgres/xg_douyin_ai_cs`（预检迁移目录识别修正）。
- 归属：PLATFORM / release governance，非业务模块。

### D3 — 上传假失败 frontend fix（owner=M05，不得因路径含 ai-edit 误归 M06）

- commit：`8968c8f`。
- 文件：
  - `frontend/src/features/ai-edit/uploadFeedback.ts`（A 新增 → FILE-000960，MODULE/M05/ACTIVE，DIR_RULES `frontend/src/features/ai-edit/` 前缀归 M05）
  - `frontend/tests/uploadFeedback.test.ts`（A 新增 → FILE-000961，MODULE/M05/TEST）
  - `frontend/src/features/ai-edit/api.ts`（M 修改，owner M05 不变）
  - `frontend/src/features/ai-edit/pages/MaterialLibrary.tsx`（M 修改，owner M05 不变）
  - `frontend/package.json`（M 修改，owner PLATFORM-RELEASE 不变）
- 能力/语义：uploadMaterialToTos → 显式 120s timeout → runUpload → SUCCESS / FAILED / UNKNOWN → MaterialLibrary 反馈。**UNKNOWN ≠ backend failed**（UNKNOWN = client 无法确认最终结果，不伪造失败）。
- 归属：Material Library = **M05**。

### D4 — G0-R3 frontend immutable release（owner=PLATFORM / release governance，即使由 M05 incident 触发）

- commit：`44c5914`（= CURRENT HEAD）。
- 文件：
  - `Dockerfile.frontend.prod`（A 新增 → FILE-000958，PLATFORM/RELEASE/ACTIVE）
  - `docker-compose.frontend-prod.yml`（A 新增 → FILE-000959，PLATFORM/RELEASE/ACTIVE）
  - `scripts/release_frontend_immutable.py`（A 新增 → FILE-000962，PLATFORM/RELEASE/ACTIVE）
  - `tests/test_release_g0_r3_frontend_immutable.py`（A 新增 → FILE-000965，PLATFORM/RELEASE/TEST）
  - `docs/config/ENV_VARIABLE_REFERENCE.md`（M 修改，docs/ 下，不在 eligible 分母）
- 归属：PLATFORM / release governance，**不得归 M05**。

## 3. eligible universe 重算（HEAD）

| 项 | G1（d1fbd04） | 当前（HEAD） |
|---|---|---|
| tracked 总数 | 1327 | 1349 |
| docs（排除） | 379 | 393（+14 docs-only：G1 11 + contract 3） |
| non-docs | 948 | 956 |
| 静态资产 + lock（排除） | 4 | 4 |
| 标准文件 | 944 | 952 |
| 中文 docs（纳入） | 13 | 13 |
| **ELIGIBLE** | **957** | **965** |

- CURRENT_ELIGIBLE = 965（= CURRENT_MAPPED），CURRENT_UNMAPPED = 0，COVERAGE = 100%。
- +8 全部来自 D1~D4 新增；0 删除；13 中文 docs 保持不变（已逐项核对）。

## 4. code_index.yaml 更新（stable ID append-only）

- 既有 957 条 **ID 全部保持不变**（复用 d1fbd04 canonical path→id 映射，OD-G1-02）。
- 8 个新文件追加 **FILE-000958 ~ FILE-000965**（连续，append-only）。
- 头部/summary 更新：eligible 957→965 + `delta_reconciliation_1` 节（base/head/delta_range/delta_commits/eligible_delta/g1_result）。
- 既有条目内容零改动（ownership/dependency/path_history 无变化 → 不更新）。
- 8 新条目归属：M05 ×3（D1 测试、D3 前端 ×2）、PLATFORM-RELEASE ×5（D2 测试、D4 ×4），全部与任务给定 ownership 一致。

## 5. 模块与平台 taxonomy 保持

- **BC-02（M05/M06 边界耦合）**：保持记录。`frontend/src/features/ai-edit/**`、`app/routers/ai_edit.py` 物理共址但 **M05=素材库 / M06=剪辑** ownership 不合并。D1/D3 均归 M05（presign 刷新与上传反馈是素材域能力）。真实 dependency 无变化 → evidence 未改，不重定义模块。
- **Platform taxonomy 保持**：auth/RBAC、DB base、generic sending gate、generic outbox、generic schedulers、merchant isolation、release governance 仍属 PLATFORM；contact_extraction = DOMAIN_SHARED / owner M02 不变。
- **D2/D4 归 PLATFORM-RELEASE**（不得归业务模块）。

## 6. 已知 release-governance follow-up（只登记，不实施）

- **RG-FOLLOWUP-01 = REGISTERED**：canonical command 输出存在"整段终端输出误粘贴后被 shell 执行"的人因风险。owner = PLATFORM / release governance。
- **RG-FOLLOWUP-02 = REGISTERED**：frontend production critical VITE build args 尚缺少完整 fail-closed build-config gate。owner = PLATFORM / release governance。
- 两者均 ≠ UNKNOWN（owner 明确为 PLATFORM / release governance），不阻止 G1 完成。实施属后续授权窗口（G4 范畴）。

## 7. HIGH-03 检查（必须分开）

- **M05 historical material presign = CLOSED**（D1 已覆盖历史 TOS URL 过期刷新）。
- **M06 LAS long-queued temporary URL expiry = OPEN**（HIGH-03 = LAS long queued video_urls can still expire >7 days；归属 M06/LAS 长任务链，D1 不覆盖 LAS 任务产物临时 URL 的长队列过期）。不得因 M05 presign 修复误标关闭。
- 已分别登记入 M05 CHAIN §13 与 M06 CHAIN §13。

## 8. capability.py raw dependency drift 检查（§10）

- 当前仍存在：`FILE-000592 packages/common/capability.py`，`owner_type=PLATFORM / owner_id=null / dependencies[0]={type: "module", target: "PLATFORM", reason: "capability 合同"}`。
- 定性：**known nonblocking documentation/schema drift**（target=PLATFORM 非合法平台 ID 枚举，不参与 depended_by 反向校验；capability.py 为能力合同，实际由 M03 capability_gateway 消费）。本轮仅登记，**不修改业务实现**（禁止范围）。
- 未自然消失 → 如实记录为存在。

## 9. 验收结果（重跑 G1 原验收机制）

独立验证器 `e:/tmp/g1_build/verify_code_index.py` 重算：

| # | 验收项 | 结果 |
|---|---|---|
| 1 | eligible_count = 965 | PASS |
| 2 | mapped_count = 965 | PASS |
| 3 | missing = 0 | PASS |
| 4 | duplicate_path = 0 | PASS |
| 5 | duplicate_id = 0 | PASS |
| 6 | invalid_owner_id = 0 | PASS |
| 7 | unknown_without_reason = 0 | PASS |
| 8 | missing_evidence = 0 | PASS |
| 9 | invalid_module_id = 0 | PASS |
| 10 | invalid_platform_id = 0 | PASS |
| 11 | schema_errors = 0 | PASS |
| + | depended_by_persisted | PASS |
| + | modules_M01-M07_present（7/7） | PASS |
| + | 7_module_chains_exist（7/7） | PASS |
| + | boundary_conflicts_registered | PASS |
| + | mixed_with_section_evidence | PASS |
| + | unknown_explicit_and_limited | PASS |
| + | generated_represented | PASS |

- **ACCEPTANCE = 11/11 公式 PASS + 机器验收清单 = 18/18 TOTAL PASS**（公式数量未变，仍 11 项；仅公式 1/2 的期望值从 957 更新为 965，属对账后分母演进，非自改验收）。
- UNKNOWN_MODULE_OWNER = 0；INVALID_DEPENDENCY_TARGET = 0。
- **PRODUCTION_CODE_CHANGED=0 / BUSINESS_TEST_CODE_CHANGED=0**：本轮仅 docs/architecture 变更；`git diff 88235b5 HEAD -- . ':!docs/'` 中的增量（D1~D4）为对账前已存在的提交，本任务未触碰任何业务/测试/配置/迁移文件。
- NEW_REGRESSION = 0（code_index.yaml 全量重建后验证器 18/18 PASS；无测试行为变更）。

## 10. 文档影响检查（AI 文档自治维护要求）

- **更新**：`docs/architecture/code-map/code_index.yaml`（对账至 965）、`M05/CHAIN.md`（presign 刷新链 + 上传反馈链 + HIGH-03 分离）、`M06/CHAIN.md`（HIGH-03 OPEN 登记）、本报告（新建）。
- **保持构建时快照**：`G1_CODE_REALITY_MAP_BUILD_REPORT.md`（957/957 为 d1fbd04 时正确结论，非错误结论；本报告 §1/§3 记录演进，`G1_CODE_REALITY_MAP_BUILD_REPORT.md` 头部已加对账指针）。
- **无影响**：01~04 治理规则、05_PROJECT_CONTEXT、旧 CODE_INDEX.yaml（READ ONLY）、SYSTEM_MAP、G0 hardening 设计文档（G0-R1，不涉及 R2/R3 实现细节）。
- 构建/验证脚本在 `e:/tmp/g1_build/`（不入库）。

## 11. Candidate Manifest（docs-only）

修改：
1. `docs/architecture/code-map/code_index.yaml`（957→965 entries，+8 append-only）

新增：
2. `docs/architecture/code-map/G1_DELTA_RECONCILIATION_1_REPORT.md`（本报告）

修改：
3. `docs/architecture/modules/M05/CHAIN.md`（presign 刷新链 / 上传反馈链 / HIGH-03 分离）
4. `docs/architecture/modules/M06/CHAIN.md`（HIGH-03 OPEN 登记）
5. `docs/architecture/code-map/G1_CODE_REALITY_MAP_BUILD_REPORT.md`（头部对账指针，最小更新）

建议 commit：`docs: 对账G1代码现实地图增量`（不 push，要求 clean）。

## 12. 最终状态

```
TASK                 = G1-DELTA-RECONCILIATION-1
BASE_G1_SHA          = d1fbd046da9f9c63b17912f0311d7201441ffdfe
CURRENT_HEAD_BEFORE  = 44c591434f5c968a2b06c7a46cf33e43c88c5e6e
DELTA_RANGE          = d1fbd04..44c5914
CURRENT_ELIGIBLE     = 965
CURRENT_MAPPED       = 965
CURRENT_UNMAPPED     = 0
COVERAGE             = 100%
MODULES              = 7/7
CHAINS               = 7/7
CHAIN_ACCEPTANCE     = 11/11（公式）+ 18/18（公式 + 机器验收）
M05_DELTA            = presign CLOSED + 上传反馈 + 3 新文件（D1/D3，owner=M05）
M06_HIGH_03          = OPEN（LAS long queued video_urls expire >7 days）
PLATFORM_RELEASE_DELTA = D2 migration dirs + D4 frontend immutable（5 新文件 + 2 修改）
RG_FOLLOWUP_01       = REGISTERED
RG_FOLLOWUP_02       = REGISTERED
BC_02                = 保持（M05/M06 边界耦合，evidence 未变）
RAW_PLATFORM_DEPENDENCY_DRIFT = 仍在（FILE-000592 capability.py target=PLATFORM，known nonblocking）
PUSH                 = NOT EXECUTED
G1_RESULT            = COMPLETE_AND_CURRENT
```

Stop criterion 满足：ownership map complete（957→965 全映射），而非逐行解释；HIGH-03 OPEN / RG-FOLLOWUP OPEN / BC-02 存在 / Legacy 未处理均不阻止 G1 完成（分属后续问题或 G2/G4 范围）。
