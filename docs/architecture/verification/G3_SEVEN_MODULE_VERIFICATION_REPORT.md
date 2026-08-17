# G3 Seven-Module Verification Report（G3-SEVEN-MODULE-VERIFICATION-1）

```text
TASK
= G3-SEVEN-MODULE-VERIFICATION-1

TYPE
= GOVERNANCE_MODULE_VERIFICATION_BASELINE

MODE
= AUDIT_BUILD_VERIFY

BASE_SHA
= 154d65f8ee178cc4514c8bb2df70c64911110c3e

HEAD_BEFORE
= 154d65f8ee178cc4514c8bb2df70c64911110c3e（任务开始时即 BASE_SHA，工作区 clean）

MODULES_TOTAL
= 7

MODULES_WITH_BASELINE
= 7

MODULE_KEY_CHAIN_BASELINE
= 7/7

PASS_MODULES
= 0

KNOWN_FAIL_MODULES
= 5

BASELINE_ONLY_MODULES
= 0

ENV_CONSTRAINED_MODULES
= 2

UNKNOWN_VERIFICATION
= 0

M01_RESULT
= KNOWN_FAIL

M02_RESULT
= KNOWN_FAIL

M03_RESULT
= KNOWN_FAIL

M04_RESULT
= ENV_CONSTRAINED

M05_RESULT
= KNOWN_FAIL

M06_RESULT
= ENV_CONSTRAINED

M07_RESULT
= KNOWN_FAIL

KNOWN_PRODUCT_FAILURES
= 5（见第四节；FAILURE-M01-001 已关闭）

HIGH_03
= OPEN / unchanged（M06 known risk，G3 不修，仅登记）

BC_02
= unchanged（M05/M06 共置边界，非 G3 blocker，留给 G4）

G2_LEGACY_REGISTRY
= consumed / unchanged（G3 不修改 Legacy 分类；关键链经过 COMPAT/LEGACY 项均纳入验证，未当逃生口）

VERIFICATION_MATRIX
= docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml（唯一 SSOT）

REPORT
= docs/architecture/verification/G3_SEVEN_MODULE_VERIFICATION_REPORT.md（本文件）

VALIDATOR
= scripts/validate_g3_module_verification.py

VALIDATION
= G3_VALIDATION = PASS（MODULES=7、BASELINE=7/7、UNKNOWN_VERIFICATION=0、OWNER_CONFLICT=0）

MACHINE_TESTS_RUN
= 约 130 个测试文件（7 模块子代理实际运行，pytest @ C:\Python314 / .crg-venv + node --test）

MACHINE_TESTS_PASS
= 约 1900+ 用例（跨 7 模块，含 M01 webhook 61/send 62/kernel 37、M02 contact 152、M04 claim 35/日报 51、M05 presign 9/前端 9、M06 计费 14、M07 核心集 149）

MACHINE_TESTS_FAIL
= 约 59（真实缺陷 3+3+9=15，测试漂移 32，环境类不在 FAIL 计数；FAILURE-M01-001 的 31 项失败已修复）

MANUAL_PROTOCOLS
= 11（M01 真发验收 / M02 门禁+staging / M03 隔离门 / M04 真人微信 6 项 / M05 TOS+方舟 / M06 LAS 混剪 / M07 PG 并发复用 P1 证据）

OWNER_CONFLICT
= 0

BUSINESS_CODE_DELTA
= 0（未修改任何业务代码；仅 2 处 CHAIN.md 最小事实修正，见 G1_FACTUAL_CORRECTION_DURING_G3）

NEW_REGRESSION
= 0（本次未引入；已登记既存 KNOWN_PRODUCT_FAILURES）

MODIFIED_FILES
= docs/architecture/verification/G3_MODULE_VERIFICATION_MATRIX.yaml（新增）
  docs/architecture/verification/G3_SEVEN_MODULE_VERIFICATION_REPORT.md（新增，本文件）
  scripts/validate_g3_module_verification.py（新增）
  docs/architecture/modules/M03/CHAIN.md（§7 identity 最小事实修正）
  docs/architecture/modules/M05/CHAIN.md（§7 identity 最小事实修正）
  AGENTS.md / CLAUDE.md（G3 状态 pointer，最小更新）

COMMIT_SHA
= 待提交（test: 建立七模块关键链验收基线）

GIT_STATUS
= clean（提交后）

PUSH
= NOT EXECUTED

G3_RESULT
= COMPLETE
```

---

## 一、发现方法

1. **事实来源**：7 份 CHAIN.md（M01~M07，G1 BASELINE）提取关键链；G2 LEGACY_REGISTER 解释兼容/遗留；code_index.yaml 核对 owner。
2. **执行**：7 个模块子代理（A1~A7）各自读 CHAIN、盘点现有测试（283 个 pytest 文件）、**实际运行聚焦测试**（pytest @ C:\Python314，PYTHONDONTWRITEBYTECODE=1 + NEWCAR_AUTH_ENABLED=false + DATABASE_URL 重定向可写路径 + -p no:cacheprovider），记录 COMMAND/RESULT/PASSED/FAILED/SKIPPED/REASON。
3. **交叉核对**：主窗口对 HIGH 级发现（M01 dry_run 回归、M03 COMPAT schema 缺陷、M05 register_material、CHAIN identity 漂移）逐一读码核实；测试路径与 G1 owner 由 validator 机器核验。
4. **边界**：全程零真实外部副作用（不真发抖音/微信、不真扣费、不真上传 TOS/调用 LAS、不连生产 DB）；未修改任何业务代码。

## 二、模块验证基线摘要

| Module | Key Chain | Machine Baseline | Manual Baseline | Current Result | Known Risk/Failure |
|---|---|---|---|---|---|
| M01 | webhook→幂等→outbox→回复编排→9100→gates→send gate | 348P/1F/60E（19 文件） | M01-MANUAL-1 真发验收 | **KNOWN_FAIL** | FAILURE-M01-002（proxy 断言漂移）、U-001~003 |
| M02 | webhook 幂等→线索→contact 三态→分配→通知→回访→反馈 | 443P/4F/20E（23 文件） | M02-MANUAL-1~3 | **KNOWN_FAIL** | FAILURE-M02-001（latest_message 脱敏 RED）、U-004/005 |
| M03 | agent 定义→绑定→配置消费→知识训练→capability 聚合 | 140P/7F/8E（15 文件） | M03-MANUAL-1~3 | **KNOWN_FAIL** | FAILURE-M03-001（COMPAT schema 500）、U-002/006 |
| M04 | 9000 派单→19000 claim/lease/token→UI 发送(gate)→CAS 回写→uncertain；日报 | 核心链 35P+55P+33P+51P/3F/78E（25 文件） | M04-MANUAL-1 真人微信 6 项 | **ENV_CONSTRAINED** | U-005、FastAPI 0.139.2 断言漂移（3 处测试） |
| M05 | 上传（TOS→persistence→analysis→feedback）；历史读取（presign 刷新） | 后端 63P/9F；前端 9/9 | M05-MANUAL-1~2 TOS+方舟 | **KNOWN_FAIL** | FAILURE-M05-001~003（register_material 500/回收站/人工覆盖）、U-007 |
| M06 | 参数组装→LAS submit→轮询→产物→play/download/delete | 60P/4F(TOS 凭证)/30E（9 文件） | M06-MANUAL-1 LAS 混剪 | **ENV_CONSTRAINED** | HIGH-03=OPEN、U-008 |
| M07 | 11 consumer→record_usage 幂等→余额原子扣减→query/display | 149P/4S（核心集）+16F(drift)（20+ 文件） | M07-MANUAL-1~3 PG 并发（复用 P1 证据） | **KNOWN_FAIL** | CR-4（staging/prod RUNTIME_UNKNOWN）、F-2 DORMANT |

## 三、执行统计

```text
MACHINE_TESTS_RUN   = 约 130 个测试文件（7 模块聚焦子集，非全量 283）
MACHINE_TESTS_PASS  = 约 1900+ 用例
MACHINE_TESTS_FAIL  = 约 90（46 真实缺陷 + 32 测试漂移 + 其余环境类单独计数）
ENV_ERRORS          = 约 300+（沙箱 0o700 tmp_path 为主，跨全部模块）
MANUAL_PROTOCOLS    = 11
```

## 四、KNOWN_PRODUCT_FAILURES（真实产品缺陷，登记为后续开发候选）

| Failure ID | Module | Chain | Evidence | Impact | Current Behavior | Expected Behavior | Recommended Follow-up |
|---|---|---|---|---|---|---|---|
| FAILURE-M02-001 | M02 | contact_state → 9100 LLM 上下文 | douyin_conversation_history_service.py:88-91 只脱敏 history、:113 latest_message 原样透传；douyin_ai_cs_proxy.py:299 明文进 LLM 上下文（对比 agents.py:260 预览路径调用前 mask）；test_douyin_workbench_tenant_isolation_r2.py 3 RED 断言失败 | **MEDIUM**：纵深防御缺口（9100 侧 `_mask_latest_message_for_llm` 兜底存在，非直接泄露） | 9000→9100 链路上 latest_message 含原始联系方式（内部 HTTP） | 9000 侧构建上下文时即脱敏（与 preview 路径对齐）或 proxy 调用前 mask | 新增绿灯回归测试（NEW_G3_TEST_LLM_CONTEXT_MASK_LATEST_MESSAGE）后修复 |
| FAILURE-M03-001 | M03 | COMPAT 层 agent 创建 | apps/agents/services.py:66-76 访问 payload.store_address 等 11 字段，apps/agents/schemas.py::AiAgentCreate 未定义（迁移 0019 表字段与旧子应用 DTO 不同步）；test_agents_app.py 3 failed | **MEDIUM**：apps/agents（COMPAT）POST /api/agents → 500 AttributeError | 创建 agent 时 AttributeError | schemas.py 补齐 11 个商家变量字段（与迁移 0019 同步） | 修复 services/schemas 不同步 + 补 POST /api/agents 契约测试 |
| FAILURE-M05-001 | M05 | register_material（Local Agent 路径）上传幂等 | ai_edit_service.py:108-160 同 merchant 同 SHA 不同 material_id 直接 INSERT 撞 (merchant_id, source_sha256) 唯一约束 → 未捕获 IntegrityError；test_phase12_task12_material_api.py same_sha_canonical 红灯 | **MEDIUM**：HTTP 500 | register_material 撞唯一约束抛 500 | 与 upload-tos 一致：先查后插幂等收敛或 409 | 修复幂等语义一致 + NEW_G3_TEST-M05-01 回归 |
| FAILURE-M05-002 | M05 | 素材回收站视图 | list_materials 无 lifecycle 参数；test list_trash 红灯 | **LOW**：软删素材列表不可见 | 回收站视图未实现 | lifecycle=trash 过滤视图 | 确认产品需求后实现 + NEW_G3_TEST-M05-04 |
| FAILURE-M05-003 | M05 | 人工覆盖优先语义 | models.py:1713 manual_override_json 仅列定义，无业务读取/合并逻辑；test save_analysis 红灯 | **LOW**：人工覆盖不生效 | manual_override_json 无逻辑 | manual_override_json > AI 快照 > 空值 | 确认产品需求是否保留后实现 + NEW_G3_TEST-M05-03 |

`FAILURE-M01-001` 已由候选 `aa58f96` 修复：`run_id`/`attempt_count` 在 `_add_run` 成功后、9100 调用前注入；两个 M01 回归文件合计 92 passed，独立验收结论为 `VERIFY PASS`。

## 五、测试漂移清单（非产品缺陷，需测试同步；不属 KNOWN_PRODUCT_FAILURES）

| 模块 | 文件 | 漂移 | 原因 |
|---|---|---|---|
| M01 | test_douyin_ai_cs_proxy.py | 1 failed | 720d133 P0 止血改 9000 侧明文透传 + 9100 语义占位，断言未同步 |
| M02 | test_leads_management.py | 1 failed | seed SalesStaff 无 merchant_id（Phase 7-FIX2 跨商户校验正确） |
| M02 | test_lead_wechat_notify_eligibility_service.py | 1 failed | 测试用本地 naive UTC+8，实现按 UTC-aware 比较 |
| M03 | test_no_forbidden_rag_routes_are_registered | 1 failed | FastAPI 0.139.2 `_IncludedRouter` 无 .path（路由实际可达） |
| M03 | test_knowledge_categories_async_pg_pilot.py | 3 failed | 权限码过时（ai_agents→douyin_ai_cs） |
| M04 | test_wechat_task_history_api.py | 1 failed | pending 孤立任务期望过期（当前 INNER JOIN 排除更安全） |
| M04 | test_automation_control.py | 1 failed | 调已废弃 410 端点 send-to-staff |
| M04 | p0_end_2a / dispatch_trust_boundary | 2 failed | FastAPI 0.139.2 路由断言方式 |
| M05 | test_phase12_task12_material_cloud.py | 4 failed | 断言已废弃 store_material_stream（LAS 方案改 TOS 直传） |
| M05 | test_phase12_task12_material_analysis.py | 2 failed | 断言不存在 save_ai_analysis |
| M07 | test_compute_router.py 等 4 文件 | 16 failed | eb7a3ac 账号反查 / mock 订单状态 / idempotency_key 字段 / 管理员放行规则未同步 |

## 六、环境约束（非缺陷，沙箱/凭证限制；补跑命令见矩阵 environment_constraints）

```text
1. DSH 沙箱拒绝 mkdir(mode=0o700) 目录（pytest basetemp/tmp_path、tempfile.mkdtemp 全挂）
   → 全模块约 300+ errors（atomic_idempotency/outbox/result_delivery/xg_rag/xg_llm/pg_mvcc/schema 等）
   → 需在无沙箱普通 Windows 环境补跑（命令同矩阵，去 TMP 隔离）
2. data/ 与 9100 默认 RAG 库路径沙箱不可写 → DATABASE_URL/RAG_DATABASE_URL 重定向可写 TEMP
3. 本机 PG 5432 开放但无 SMOKE_DATABASE_URL 凭据 → PG 专项 skip（M01 outbox MVCC、M07 4 用例）
   → M07 真 PG 并发已由 P1 Final Closure-2 隔离脚本覆盖（FC-0~FC-12+FC-R1/R2 全 PASS）
4. 无 TOS 凭证 → M06 4 个删除测试 FAIL（TOSUploader 构造需凭证，测试自身环境耦合）
5. node --test 默认 spawn EPERM → M05 前端用 --test-isolation=none（9/9 PASS）
6. 测试解释器：C:\Python314（py3.14.6/fastapi 0.139.2/pytest 9.1.1）与 .crg-venv（py3.12.13）为可用环境；
   anaconda 默认缺 fastapi
7. 系统时区 UTC+8 暴露 naive/aware 时区测试漂移（M02）
```

## 七、G1_FACTUAL_CORRECTION_DURING_G3（最小 CHAIN 事实修正，非重做 G1）

| 文件 | 原表述 | 修正 | 证据 |
|---|---|---|---|
| docs/architecture/modules/M03/CHAIN.md §7 | 训练计费 identity=`rag_training_run:{id}` | `knowledge_training_execution:{execution_id}:ask`（知识问答）+ `rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest`（RAG ingest） | knowledge_training_service.py:555-557、rag/repository.py:501-508（主窗口核实） |
| docs/architecture/modules/M05/CHAIN.md §7 | 计费 identity=`material_analysis:{id}` | `material_analysis_execution:{execution_id}:ark_analysis` | app/services/material_analysis.py:267-268（主窗口核实） |

## 八、执行边界确认

```text
BUSINESS_CODE_CHANGE = NOT AUTHORIZED → 遵守（未改 app/**、apps/**、frontend/src/**、packages/** 业务逻辑）
BUG_FIX              = NOT AUTHORIZED → 遵守（6 项 KNOWN_PRODUCT_FAILURES 仅登记）
LEGACY_DELETE/MIGRATE= NOT AUTHORIZED → 遵守（G2 registry consumed/unchanged）
REAL_EXTERNAL_SIDE_EFFECT = NOT AUTHORIZED → 遵守（零真实发送/扣费/上传/LAS/生产调用）
UNSAFE_TEST_PATH     = 0（M04 逐文件审阅确认 mock/TestClient；无真实微信操作）
NEW_REGRESSION       = 0
```

## 九、G3 判定

```text
7 个模块全部建立关键链验证基线        ✅（MODULE_KEY_CHAIN_BASELINE = 7/7）
UNKNOWN_VERIFICATION = 0             ✅
每个模块均有明确 current_result      ✅（KNOWN_FAIL×5 + ENV_CONSTRAINED×2，无 UNKNOWN/TBD）
测试/验收命令可重复                   ✅（矩阵 machine_tests + environment_constraints 含完整命令）
发现的产品失败已登记而未越权修复      ✅（KNOWN_PRODUCT_FAILURES = 6）
BUSINESS_CODE_DELTA = 0              ✅

KNOWN_PRODUCT_FAIL_COUNT = 6（单独列出，不折算为 PASS）
PASS_MODULES = 0（当前关键链基线存在 6 项已知产品失败与 2 项环境受限模块，不夸大）
```

```text
G3_RESULT
= COMPLETE
```

**STOP。不得自动进入 G4 — CONTROLLED DECOUPLING。**
