# G4 Controlled Decoupling 最终报告（G4-CONTROLLED-DECOUPLING-1）

> 任务书：G4-CONTROLLED-DECOUPLING-1（§40~§44 格式）
> BASE_SHA：`1f556978ba856a1d330e8e26376326c3e7aed8b5`（= G3 交付 commit）
> 治理基线：G0=COMPLETE / G1=COMPLETE_AND_CURRENT / G2=COMPLETE / G3=COMPLETE
> 机器验收：`python scripts/validate_g4_coupling_registry.py` → G4_VALIDATION = PASS

---

## 一、最终机器指标（§43）

```text
COUPLING_CANDIDATES          = 65
CLASSIFIED_TOTAL             = 65

CONTROLLED                   = 20
BOUNDARY                     = 33
UNCONTROLLED                 = 11
CRITICAL_UNCONTROLLED        = 1（COUPLING-001，PHASE B 已 REMEDIATED）

CRITICAL_FOUND_BEFORE        = 1
CRITICAL_REMEDIATED          = 1
CRITICAL_BLOCKED             = 0
CRITICAL_REMAINING           = 0

UNKNOWN_COUPLING             = 0
OWNER_CONFLICT               = 0
INVALID_CLASSIFICATION       = 0
MISSING_EVIDENCE             = 0
MISSING_RISK                 = 0
MISSING_EXIT_CONDITION       = 0

BOUNDARY_TESTS               = 7（tests/test_g4_automation_auth_boundary.py 7/7 PASS）

BUSINESS_BEHAVIOR_DELTA      = 0
DB_SCHEMA_DELTA              = 0
PUBLIC_API_DELTA             = 0
NEW_REGRESSION               = 0
```

## 二、G4 最终报告字段（§44）

```text
TASK
= G4-CONTROLLED-DECOUPLING-1

BASE_SHA
= 1f556978ba856a1d330e8e26376326c3e7aed8b5

HEAD_BEFORE
= 1f556978ba856a1d330e8e26376326c3e7aed8b5

DISCOVERY_METHOD
= 消费 G1（code_index.yaml / M01~M07 CHAIN.md / DEPENDENCY_MATRIX 11 条 Canonical Edge）+ G2（LEGACY_REGISTER 62 条）+ G3（VERIFICATION_MATRIX / REPORT）；
  8 个并行子代理（A1 M01/M02、A2 M03、A3 M04、A4 M05/M06 BC-02、A5 M07、A6 PLATFORM/DOMAIN_SHARED、A7 前端、A8 cross-cutting 环+对账）只读静态审计；
  主窗口统一分类/去重/severity/owner/remediation 决策；A8 额外运行 Tarjan SCC import 环扫描（267 文件）与 E1~E11 逐条对账

COUPLING_CANDIDATES
= 65（原始 70 条，去重合并 3 组：E8 回写链 4→1、空号追问私有函数 2→1、proxy→agents 私有 helper 2→1）

CLASSIFIED_TOTAL
= 65

CONTROLLED
= 20

BOUNDARY
= 33

UNCONTROLLED
= 11

CRITICAL_UNCONTROLLED_BEFORE
= 1

CRITICAL_REMEDIATED
= 1（COUPLING-001 /automation/* 无鉴权 → 挂 get_request_context_required）

CRITICAL_BLOCKED
= 0

CRITICAL_UNCONTROLLED_REMAINING
= 0

UNKNOWN_COUPLING
= 0

BC_02
= UNCONTROLLED / severity MEDIUM / classification_before=UNCONTROLLED / classification_after=unchanged（登记不强制拆目录）
  证据：CODE_INDEX.yaml:326 文件级归 M05 vs DEPENDENCY_MATRIX.md:42,84 功能级归 M06 的 owner 漂移；
        ai_edit_service.py:214-220 soft_delete_material 直接读 M06 ai_edit_jobs 表（G1 未登记 M05→M06 DATABASE 读依赖）；
        ai_edit.py 三段落（materials/jobs/las）共用 _require_ai_edit 权限门；las_tos_uploader.py 文件归 M06 但 M05 是主要消费者
  action：为 ai_edit_service 素材/任务函数补 owner 契约登记 + M05→M06 活动引用检查补 boundary test；不强制拆 router/feature 目录（物理共址非关键风险）

M01_M02_BOUNDARY
= webhook 入口 MIXED（BOUNDARY，COUPLING-002）+ E8 回写链（UNCONTROLLED，COUPLING-006）+ E2 工作台双轨（BOUNDARY，COUPLING-005）
  + E1 upsert/recover（CONTROLLED，COUPLING-003/004）+ 事件-线索同事务一致性（CONTROLLED，COUPLING-010）

M03_CAPABILITY_BOUNDARY
= E4/E5/E6 智能体配置链路（CONTROLLED，COUPLING-014~016）+ 双 HTTP 计费回环（CONTROLLED，COUPLING-017）
  + proxy→agents 私有 billing helper（UNCONTROLLED，COUPLING-018）+ capability_gateway 空壳（BOUNDARY，COUPLING-019）

M04_LOCAL_AGENT_BOUNDARY
= /automation/* 无鉴权（CRITICAL→REMEDIATED，COUPLING-001）+ 紧急停止跨进程状态分裂（UNCONTROLLED HIGH，COUPLING-023）
  + 9000 侧 wechat_ui 执行 import（BOUNDARY，COUPLING-024）+ 日报直写 WechatTask（BOUNDARY，COUPLING-025）
  + 19000 入站无鉴权 loopback 信任（BOUNDARY，COUPLING-026）+ /replies/manual 无鉴权（UNCONTROLLED，COUPLING-027）

M05_M06_BOUNDARY
= BC-02 整体（UNCONTROLLED，COUPLING-028）+ TOS 工具归属（BOUNDARY，COUPLING-029）+ 前端共址（BOUNDARY，COUPLING-030）
  + 计费 identity（CONTROLLED，COUPLING-031）+ 素材双写入口（BOUNDARY，COUPLING-032）+ 测试独立性（BOUNDARY，COUPLING-033）
  + model 表归属（BOUNDARY，COUPLING-034）+ 互写 ai_edit_jobs（BOUNDARY，COUPLING-065）

M07_COMPUTE_BOUNDARY
= E3/E11 计费上报（CONTROLLED，COUPLING-035/036）+ admin 放行规则（CONTROLLED，COUPLING-037）
  + COMPAT-012 兼容入口（BOUNDARY，COUPLING-038）+ F-2 DORMANT（BOUNDARY，COUPLING-039）+ 9205 dev（BOUNDARY，COUPLING-040）
  + 幂等 enforcement（BOUNDARY，COUPLING-041）+ record_usage 消费者矩阵缺口（BOUNDARY，COUPLING-064）

PLATFORM_DEPENDENCIES
= auth/RBAC、merchant isolation、outbox、scheduler、DB 底座、config 单点均核查为正式 Platform 边界（CONTROLLED，无反向业务依赖）
  DOMAIN_SHARED contact 只读域 CONTROLLED（COUPLING-012）；唯一缺口：空号追问 Worker import M01 私有发送函数（UNCONTROLLED，COUPLING-009）

CYCLES_FOUND
= 2（均非运行时环）：A8-C01 M01/M02/PLATFORM 8 文件交织环（BOUNDARY，COUPLING-054，函数级 import 打破，实质问题=解析工具共址 M02 webhook 文件 + PLATFORM 底座依赖方向反转）；
  A8-C02 9100 内部 rag↔vector_store 环（CONTROLLED，COUPLING-055）

G2_LEGACY_DEPENDENCIES
= consumed / unchanged（62 条 registry 作为证据与 exit_condition 输入；LEGACY-012/025/027/045 等作为耦合的 legacy_dependencies 关联，均未删除未迁移）

G3_VERIFICATION_MATRIX
= consumed（7 模块 key_chain 作为 key_chain_impact 判定基准；KNOWN_FAIL 基线用于 BASE vs CANDIDATE 对比）

G3_PROTECTED_FAILURES
= unchanged（6 项全部未触碰，仅作 evidence 引用）
  FAILURE-M01-001 = unchanged（dry_run UnboundLocalError）
  FAILURE-M02-001 = unchanged（latest_message 脱敏）
  FAILURE-M03-001 = unchanged（COMPAT POST /api/agents 500）
  FAILURE-M05-001 = unchanged（register_material 500；COUPLING-032 引作双写入口证据）
  FAILURE-M05-002 = unchanged（回收站）
  FAILURE-M05-003 = unchanged（人工覆盖）

HIGH_03
= unchanged（M06 LAS long queued video_urls 过期风险，独立于 coupling，不修）

RG_FOLLOWUP_01
= unchanged（canonical command 人因误执行风险，PLATFORM-RELEASE 自身治理项，非跨 owner coupling）

RG_FOLLOWUP_02
= unchanged（frontend production VITE fail-closed，A7 核查为 CONTROLLED，COUPLING-053）

COUPLING_REGISTRY
= docs/architecture/coupling/G4_COUPLING_REGISTRY.yaml（唯一 SSOT，schema_version 1.0）

REPORT
= docs/architecture/coupling/G4_CONTROLLED_DECOUPLING_REPORT.md（本文件）

VALIDATOR
= scripts/validate_g4_coupling_registry.py

VALIDATION
= G4_VALIDATION = PASS（exit 0）

REMEDIATIONS
= 1（COUPLING-001 /automation/* 挂 get_request_context_required；文件：app/routers/automation_control.py，约 12 行变更）

BOUNDARY_TESTS
= 7（tests/test_g4_automation_auth_boundary.py：行为保持 3 + fail-closed 3 + 静态契约 1，7/7 PASS）

BASE_TEST_RESULT
= G3 基线（test_automation_control.py + test_agent_status.py 相关用例在 BASE_SHA 上：17P/1F，1F=FAILURE-M04-002 已废弃端点漂移）

CANDIDATE_TEST_RESULT
= 同组测试在 CANDIDATE（remediation 后）：17P/1F（同一 FAILURE-M04-002 漂移 unchanged）+ boundary test 7/7 PASS
  → 无新回归（BASE known fail ≠ CANDIDATE new regression；G3 基线对比通过）

BUSINESS_BEHAVIOR_DELTA
= 0

DB_SCHEMA_DELTA
= 0

PUBLIC_API_DELTA
= 0

NEW_REGRESSION
= 0

NONCRITICAL_COUPLING_BACKLOG
= 11 条 UNCONTROLLED（按 risk/cost/dependency 排序，不实施，见 §六）

MODIFIED_FILES
= app/routers/automation_control.py（PHASE B remediation）
  tests/test_g4_automation_auth_boundary.py（新增 boundary test）
  docs/architecture/coupling/G4_COUPLING_REGISTRY.yaml（新增，SSOT）
  docs/architecture/coupling/G4_CONTROLLED_DECOUPLING_REPORT.md（新增）
  scripts/validate_g4_coupling_registry.py（新增 validator）
  AGENTS.md / CLAUDE.md（G4 coupling registry pointer 同步）

COMMIT_SHA
= 9ffb95e（refactor: 建立G4耦合治理总账并收敛关键跨模块依赖边界（G4-CONTROLLED-DECOUPLING-1），7 files changed, 2417 insertions(+), 4 deletions(-)）

GIT_STATUS
= clean

PUSH
= NOT EXECUTED

G4_RESULT
= COMPLETE
```

## 三、Coupling 摘要表（§44）

| ID | Source | Target | Type | Classification Before | Classification After | Severity | Critical? | Action | Evidence 摘要 |
|---|---|---|---|---|---|---|---|---|---|
| COUPLING-001 | M04 | PLATFORM | API | CRITICAL_UNCONTROLLED | CONTROLLED | HIGH | YES | **REMEDIATED**（挂鉴权） | automation_control.py:43-83 无鉴权 → 挂 get_request_context_required |
| COUPLING-002 | M02 | M01 | IMPORT | BOUNDARY | BOUNDARY | MEDIUM | NO | keep+登记 | webhook 入口 MIXED，Reality Map 归属 drift |
| COUPLING-003 | M01 | M02 | DATABASE | CONTROLLED | CONTROLLED | LOW | NO | keep | E1 upsert 契约完整（R2-6/R4/R5） |
| COUPLING-004 | M01 | M02 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | recover_contact_valid 经 M02 门面 |
| COUPLING-005 | M01 | M02 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | 可选优化 | 工作台读 M02 双轨（service+ORM） |
| COUPLING-006 | M04 | M02 | DATABASE | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | E8 回写链 5 写入点直接 ORM，DouyinLead.status 双 owner |
| COUPLING-007 | M02 | M04 | DATABASE | UNCONTROLLED | UNCONTROLLED | LOW | NO | REQUIRED（后续） | 通知资格直读 wechat_tasks |
| COUPLING-008 | M02 | M04 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | E7 自动建任务已 auto_notify_disabled |
| COUPLING-009 | DOMAIN_SHARED | M01 | IMPORT | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | 空号追问 import 私有发送函数 |
| COUPLING-010 | M01 | M02 | DATABASE | CONTROLLED | CONTROLLED | LOW | NO | keep | 事件+线索同事务一致性 |
| COUPLING-011 | M02 | M01 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | 可选优化 | 事件表展示直读 |
| COUPLING-012 | DOMAIN_SHARED | DOMAIN_SHARED | SHARED_STATE | CONTROLLED | CONTROLLED | LOW | NO | keep | contact 只读域 |
| COUPLING-013 | M02 | M03 | CONFIG | CONTROLLED | CONTROLLED | LOW | NO | keep | E6 agent_config 经 payload |
| COUPLING-014 | M03 | M01 | IMPORT | CONTROLLED | CONTROLLED | MEDIUM | NO | keep | E4 suggest_reply 统一 client |
| COUPLING-015 | M01 | M03 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | E5 agent_config 只读消费 |
| COUPLING-016 | M02 | M03 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | E6 绑定解析收敛 |
| COUPLING-017 | M03 | M07 | API | CONTROLLED | CONTROLLED | MEDIUM | NO | keep（P1 已收口） | 9000→9100→9000 计费回环 |
| COUPLING-018 | M01 | M03 | IMPORT | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | proxy→agents 私有 billing helper |
| COUPLING-019 | PLATFORM | M03 | OTHER | BOUNDARY | BOUNDARY | LOW | NO | 保留 health | capability_gateway 空壳 |
| COUPLING-020 | M03 | M03 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | PG cutover 消除 | dev 共享 SQLite |
| COUPLING-021 | M02 | M02 | IMPORT | BOUNDARY | BOUNDARY | LOW | NO | 随 COMPAT 退役 | apps/leads 委托 9000 核心 |
| COUPLING-022 | M03 | M03 | IMPORT | BOUNDARY | BOUNDARY | LOW | NO | 保留 re-export | apps/ 实现层 + app re-export |
| COUPLING-023 | M04 | M04 | SHARED_STATE | UNCONTROLLED | UNCONTROLLED | HIGH | NO | REQUIRED（后续） | 紧急停止跨进程状态分裂 |
| COUPLING-024 | M04 | M04 | IMPORT | BOUNDARY | BOUNDARY | MEDIUM | NO | 删除/硬禁用 | 9000 侧 wechat_ui 执行 import |
| COUPLING-025 | M04 | M04 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | 收敛统一入口 | 日报直写 WechatTask |
| COUPLING-026 | M04 | PLATFORM | API | BOUNDARY | BOUNDARY | MEDIUM | NO | 增加入站校验 | 19000 loopback 信任模型 |
| COUPLING-027 | M04 | M02 | API | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | /replies/manual 无鉴权 |
| COUPLING-028 | M05 | M06 | DATABASE | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | **BC-02 整体**：owner 漂移+未登记读依赖 |
| COUPLING-029 | M05 | M06 | FILE_STORAGE | BOUNDARY | BOUNDARY | LOW | NO | 保持/归底座 | TOS 工具归属 |
| COUPLING-030 | M05 | M06 | API | BOUNDARY | BOUNDARY | LOW | NO | 可拆分 api.ts | 前端共址 |
| COUPLING-031 | M05 | M07 | SHARED_STATE | CONTROLLED | CONTROLLED | LOW | NO | keep | 计费 identity 双 owner 同 capability |
| COUPLING-032 | M05 | M05 | OTHER | BOUNDARY | BOUNDARY | MEDIUM | NO | 收敛写入口 | 素材双写入口 |
| COUPLING-033 | M05 | M06 | OTHER | BOUNDARY | BOUNDARY | LOW | NO | 保持 | 测试独立性 |
| COUPLING-034 | M05 | M06 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | CODE_INDEX 补注 | model 表归属 |
| COUPLING-035 | M01 | M07 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | E3 跨进程计费上报 |
| COUPLING-036 | M06 | M07 | IMPORT | CONTROLLED | CONTROLLED | LOW | NO | keep | E11 同进程 record_usage |
| COUPLING-037 | PLATFORM | M07 | CAPABILITY | CONTROLLED | CONTROLLED | LOW | NO | 观察项 | admin 放行规则 |
| COUPLING-038 | M07 | M07 | IMPORT | BOUNDARY | BOUNDARY | LOW | NO | 保留 COMPAT | COMPAT-012 re-export |
| COUPLING-039 | M07 | M07 | API | BOUNDARY | BOUNDARY | MEDIUM | NO | 收敛/禁用 | F-2 DORMANT |
| COUPLING-040 | PLATFORM | M07 | API | BOUNDARY | BOUNDARY | LOW | NO | dev 标注 | 9205 header 信任 |
| COUPLING-041 | M07 | M07 | CAPABILITY | BOUNDARY | BOUNDARY | MEDIUM | NO | 未来 fail-closed | 幂等 enforcement |
| COUPLING-042 | DOMAIN_SHARED | PLATFORM | CONFIG | BOUNDARY | BOUNDARY | LOW | NO | 并入 config 单点 | 空号追问 env 直读 |
| COUPLING-043 | M01 | M04 | CAPABILITY | BOUNDARY | BOUNDARY | LOW | NO | 文档登记 | M01→M04 create_wechat_task |
| COUPLING-044 | PLATFORM | M01 | API | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | 前端 douyinAiCsClient 直连 9100 |
| COUPLING-045 | PLATFORM | M05 | IMPORT | UNCONTROLLED | UNCONTROLLED | LOW | NO | REQUIRED（后续） | App.tsx import feature localApi |
| COUPLING-046 | PLATFORM | M01 | IMPORT | BOUNDARY | BOUNDARY | LOW | NO | 删除死壳 | api/douyinCs 反向 re-export |
| COUPLING-047 | PLATFORM | M02 | UI | BOUNDARY | BOUNDARY | LOW | NO | 可选优化 | Index 聚合页 |
| COUPLING-048 | PLATFORM | M02 | UI | BOUNDARY | BOUNDARY | LOW | NO | 批量删除 | pages/components re-export 壳 |
| COUPLING-049 | M04 | M02 | API | BOUNDARY | BOUNDARY | LOW | NO | 显式化 import | feature api 聚合层 |
| COUPLING-050 | M02 | M04 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | M02 UI 调 M04 HTTP contract |
| COUPLING-051 | M05 | M06 | IMPORT | BOUNDARY | BOUNDARY | LOW | NO | 可拆分 | ai-edit 共享模块 |
| COUPLING-052 | PLATFORM | M04 | API | CONTROLLED | CONTROLLED | LOW | NO | keep | 19000 三层优先级 |
| COUPLING-053 | PLATFORM | M01 | OTHER | CONTROLLED | CONTROLLED | LOW | NO | keep | vite proxy fail-closed |
| COUPLING-054 | M01 | M02 | IMPORT | BOUNDARY | BOUNDARY | MEDIUM | NO | 下沉解析工具 | 8 文件交织环（非运行时） |
| COUPLING-055 | M01 | M01 | IMPORT | CONTROLLED | CONTROLLED | LOW | NO | keep | 9100 内部环（非运行时） |
| COUPLING-056 | M02 | M07 | CAPABILITY | BOUNDARY | BOUNDARY | MEDIUM | NO | 补登消费者 | LEGACY-012 4 模块消费 |
| COUPLING-057 | M01 | M03 | CAPABILITY | BOUNDARY | BOUNDARY | LOW | NO | 迁移直连 | LEGACY-045 re-export 桥 |
| COUPLING-058 | M01 | M07 | CAPABILITY | CONTROLLED | CONTROLLED | LOW | NO | keep | LEGACY-025 None 退路 |
| COUPLING-059 | PLATFORM | M01 | IMPORT | CONTROLLED | CONTROLLED | LOW | NO | keep | META 启动期 import |
| COUPLING-060 | M02 | M02 | EVENT | BOUNDARY | BOUNDARY | LOW | NO | 随 LEGACY-001/029 退役 | 9202 兼容桥 |
| COUPLING-061 | M02 | M04 | DATABASE | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | sales_feedback 直写 sales_daily_summaries |
| COUPLING-062 | M02 | M01 | DATABASE | UNCONTROLLED | UNCONTROLLED | MEDIUM | NO | REQUIRED（后续） | resource_download 直写 M01 表 |
| COUPLING-063 | M01 | M03 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | E5 补例外 | 设置视图直查 AiAgent |
| COUPLING-064 | M02 | M07 | CAPABILITY | BOUNDARY | BOUNDARY | LOW | NO | 补登矩阵 | record_usage 消费者矩阵缺口 |
| COUPLING-065 | M05 | M06 | DATABASE | BOUNDARY | BOUNDARY | LOW | NO | 补登写边 | M05→M06 互写 ai_edit_jobs |

## 四、PHASE B Remediation 详情（§30/§44）

| ID | Before Contract | After Contract | Files Changed | Boundary Test | Behavior Parity |
|---|---|---|---|---|---|
| COUPLING-001 | /automation/* 无鉴权（匿名可调用，可解除紧急停止/绕过人工接管） | Depends(get_request_context_required)（登录态必需，生产 fail-closed） | app/routers/automation_control.py（import + 3 端点挂依赖，约 12 行） | tests/test_g4_automation_auth_boundary.py 7/7 PASS（行为保持 3 + fail-closed 3 + 静态契约 1） | mock auth 下 3 端点行为与修复前一致（200）；前端 automation.ts 经 apiClient 带 token 不受影响；G3 已知失败 FAILURE-M04-002 unchanged |

## 五、执行边界确认（§28/§34/§37）

- **BUSINESS_CODE_DELTA = 0**（业务逻辑零改动；唯一 remediation 是安全边界硬化，非业务行为变更）
- **REMEDIATION_FILE_COUNT = 1**（app/routers/automation_control.py）；**REMEDIATION_LINES_CHANGED ≈ 12**
- **G3 Protected Failures 6 项全部 unchanged**（仅作 evidence 引用，未修复未触碰）
- **G3 基线对比**：BASE 17P/1F vs CANDIDATE 17P/1F（同一 FAILURE-M04-002 漂移）+ 新增 boundary test 7P → **NEW_REGRESSION=0**；BASE known fail ≠ CANDIDATE new regression
- **环境约束**：测试于沙箱内运行（C:\Python314 + DATABASE_URL 重定向 + NEWCAR_AUTH_ENABLED=false）；tmp_path 类测试仍 ENV_CONSTRAINED（与 G3 相同，非本次引入）
- **G2 registry = consumed / unchanged**；**HIGH-03 = unchanged**；**RG-FOLLOWUP-01/02 = unchanged**
- **未创建任何 Interface/Facade/Repository 空壳层**（§十八纪律：先复用已有 contract——本次 remediation 直接复用已有 get_request_context_required）

## 六、NONCRITICAL_COUPLING_BACKLOG（§39，不实施）

按 risk/cost/dependency/timing 排序的 11 条 UNCONTROLLED：

| 优先级 | Coupling | 风险 | 成本 | 依赖 | 建议时机 |
|---|---|---|---|---|---|
| P1 | COUPLING-023 紧急停止跨进程状态分裂 | HIGH | 中（跨进程协议） | 19000 心跳协议 | 与 M04 稳定性治理同批 |
| P1 | COUPLING-006 E8 回写链 | MEDIUM | 中（M02 状态机 facade） | M02 状态机契约 | 与 S1/S4 同批 |
| P2 | COUPLING-018 proxy→agents 私有 helper | MEDIUM | 低（抽 service） | M03 重构窗口 | 任意治理窗口 |
| P2 | COUPLING-027 /replies/manual 无鉴权 | MEDIUM | 低（挂鉴权/守卫） | 无 | 任意治理窗口 |
| P2 | COUPLING-028 BC-02 owner 契约 | MEDIUM | 中（契约登记+测试） | M05/M06 边界 | 与 E9 解耦同批 |
| P2 | COUPLING-044 前端直连 9100 | MEDIUM | 低（删直连函数） | 前端清理 | 任意治理窗口 |
| P2 | COUPLING-061/062 M02 直写未登记表 | MEDIUM | 低（登记/收敛） | 文档治理 | 任意治理窗口 |
| P3 | COUPLING-009 空号追问私有函数 | MEDIUM | 低（提公开 API） | 发送门面 | 与发送安全治理同批 |
| P3 | COUPLING-007 通知资格直读 | LOW | 低 | 无 | 任意治理窗口 |
| P3 | COUPLING-045 App.tsx import localApi | LOW | 低（上移共享层） | 前端清理 | 任意治理窗口 |
| P3 | COUPLING-024 9000 侧 wechat_ui 执行 import | MEDIUM | 低（删除/硬禁用） | Windows-only 验证 | 与 LEGACY-007 同批 |

## 七、E1~E11 对账结果（A8 cross-cutting，登记于 registry）

STILL_VALID=5（E2/E3/E4/E5/E9）+ 禁用态成立=1（E7）+ CHANGED=5（E1 归属错误、E6 source 错、E8/E11 范围缺口、E10 方向缺口）+ REMOVED=0。
系统性发现：DEPENDENCY_MATRIX 对 record_usage 消费者登记严重不全（E11 只登记 1 个，实际 4 个跨模块消费者，见 COUPLING-064）；M02↔M04 直接表写登记不全（COUPLING-006/061）。

## 八、Git

```text
COMMIT_SHA = 9ffb95e（refactor: 建立G4耦合治理总账并收敛关键跨模块依赖边界）
GIT_STATUS = clean
PUSH = NOT EXECUTED
```

---

## 九、G4 判定（§43 完成标准）

```text
CRITICAL_UNCONTROLLED_COUPLING = 0（1 发现 → 1 REMEDIATED） ✅
UNKNOWN_COUPLING               = 0 ✅
OWNER_CONFLICT                 = 0 ✅
NEW_REGRESSION                 = 0 ✅
BUSINESS_BEHAVIOR_DELTA        = 0 ✅
DB_SCHEMA_DELTA                = 0 ✅
PUBLIC_API_DELTA               = 0 ✅
G3_PROTECTED_FAILURES          = 6/6 unchanged ✅
BOUNDARY_TESTS                 = 7 ✅
G4_VALIDATION                  = PASS ✅

G4_RESULT
= COMPLETE

STOP
```

**不得自动进入 GC — Governance Baseline Closure。等待 Owner 批准。**
