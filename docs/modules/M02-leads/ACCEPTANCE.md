# M02 验收基线

> source_baseline: c26ec227e70d | 本任务只制定验收基线，不要求为了通过验收修改代码。

## 当前测试覆盖

| 能力 | 状态 | 测试文件 |
|---|---|---|
| Lead create | COVERED | test_douyin_webhook.py:407（webhook 创建） |
| Lead update | COVERED | test_douyin_webhook.py（pending 更新 / 非 pending skip） |
| Lead dedupe | COVERED | test_douyin_webhook_atomic_idempotency.py（会话维度幂等） |
| cross-merchant isolation | COVERED | test_douyin_leads_session_isolation.py / test_douyin_workbench_tenant_isolation_r2.py |
| assignment | COVERED | test_leads_management.py（分配/转派） |
| transfer | COVERED | test_leads_management.py（is_reassign → record_type="reassign"） |
| recycle | MISSING | 无 /unassign 或 /recycle 测试（功能 NOT_IMPLEMENTED） |
| sales data scope | PARTIAL | 商户内全部可见已验证；无"仅本人"强制逻辑测试 |
| contact update | COVERED | test_douyin_webhook.py（best-effort 回填） |
| M01 integration | COVERED | test_douyin_webhook.py（webhook→Lead 写入完整） |
| M04 integration | PARTIAL | record_manual_reply 回写有测试；微信通知任务创建无集成测试（auto_notify_disabled） |
| feedback parse | COVERED | test_sales_feedback_parser.py（三类模板解析） |
| status transition | PARTIAL | pending→assigned→replied 有测试；timeout→? 无审计/无约束验证 |
| audit | PARTIAL | assign/reassign 有 LeadFollowupRecord；replied/timeout 状态变更无显式审计 |
| failure/retry | PARTIAL | 通知失败有 LeadNotification.send_status；Lead 操作失败无 retry 机制 |

## E2E 验真结果（2-M02.2 Docker，2026-08-07）

环境：docker compose dev（9000 + PG + 能力中心）

| E2E | 域 | 结果 | 证据 |
|---|---|---|---|
| 1 | Webhook Identity/Aggregation Matrix | **PASS** | Webhook create→created；同会话重复→duplicate_event；同客户新会话→created（新建）；Manual create→200 |
| 1 | Legacy sync identity | NOT_VERIFIED | sync-leads 未在 Docker E2E 中触发（dry_run=false 写库路径未测） |
| 1 | Manual create identity | PARTIAL | Manual create→200 成功，但未携带相同业务身份验证是否产生重复 Lead；ISSUE-M02-002 不升级 HIGH |
| 2 | Cross-merchant | **TEST_GAP** | list 只返回 dev-merchant，但测试库无第二 merchant fixture（mock auth 固定 dev-merchant），无法构造跨商户场景 |
| 3 | Assignment 真实算法 | **TEST_FIXTURE_GAP** | 0 staff（docker dev 无销售 fixture），无法验证轮询/少者优先；需补 staff fixture 重测 |
| 4 | Reassign | **TEST_FIXTURE_GAP** | 0 assigned lead + 0 staff，无法验证转派/reassign_count；需补 fixture 重测 |
| 5 | Feedback Parse | **TEST_INPUT_GAP** | POST /sales-feedback/parse 返回 400（feedback_no 格式或上下文问题）；需找到正式接受格式构造合法/非法输入 |
| 6 | Data Scope | **CODE_VERIFIED + PENDING_E2E** | 代码确认无"仅本人"强制（assigned_staff_id 可选过滤）；但未用两 Sales + 两 Lead 真实 API 验证 |
| 7 | Status 自由字符串 | **DB_VERIFIED + APPLICATION_PENDING** | DB 无约束已验证（models.py:164）；但 API/service 写入链对未知 status 的行为需 E2E |

### ISSUE-M02-002 升级条件检查

- Manual create（E2E-1）PARTIAL：不带 account_open_id/conversation_short_id 创建成功（200），但不会与 webhook 线索冲突（无相同业务身份）
- **不升级 HIGH**：未证明 Manual API 携带完全相同业务身份仍产生不可区分重复 Lead

### 仍 SKIP（需 staging/外部环境）

- 真实 webhook→Lead→M04→反馈回写全链路
- auto_notify 真实链路（当前 disabled）
- 销售数据范围真实行为（需真实商户上下文 + 多角色）
- Assignment + Reassign（需多销售数据）

**E2E 状态：`M02_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_FIXTURE_GAPS`**（无 BLOCKER，Webhook Identity PASS，Cross-merchant/Assignment/Reassign/Feedback/Data Scope/Status 有 fixture/input gap 待 R1 补）

## 2-M02.2R1 Docker Fixture Gap Closure（2026-08-07）

### Staff Fixture 补全

创建 3 个销售（A active+enable / B active+enable / C inactive），补全 fixture 缺口。

### Gate 结果

| Gate | 结果 | 证据 |
|---|---|---|
| A Assignment | **PARTIAL** | execution path PASS（Lead→分配给 A→staff_id=1 验证）；algorithm behavior PARTIAL（未验证 active 筛选/排序/连续分配） |
| B Reassign | **PASS** | A→B 转派→owner 变更 staff_id=2 验证通过；reassign_count=None（确认字段从未自增，ISSUE-M02-006 已登记） |
| C Feedback Parse | **PARTIAL** | 合法格式返回 400（feedback_no 格式问题）；非法格式返回 200 skipped（正确） |
| D Data Scope | **PASS** | list 返回 5 leads 含不同 staff_id，商户内全部可见 VERIFIED CURRENT BEHAVIOR |
| E Status Validation | **CURRENT_REALITY_PASS** | DB status constraint: ABSENT；Public standalone status mutation API: NOT EXPOSED（无独立 update status API；status 变更仅 assign_service 内部修改；不写"Application Validation PASS"因不存在状态白名单验证） |
| F Cross-merchant | **TEST_GAP** | mock auth 固定 dev-merchant，无法构造第二 merchant fixture |

### Gate C 发现

- 合法反馈格式 400 SALES_FEEDBACK_PARSE_FAILED：可能是 feedback_no 格式 `XGF-{lead_id}-{staff_id}` 与 parser 预期不匹配，或缺少必要上下文字段。需确认 sales_feedback_parser.py 的正式接受格式。
- 非法格式 200 skipped：正确行为（不匹配三类模板→不写库）。
- 不构成 BLOCKER（parser 代码逻辑完整，是输入格式/上下文问题），登记为 TEST_INPUT_GAP。

### 仍 SKIP（需 staging/外部环境）

- 真实 webhook→Lead→M04 通知→销售反馈→状态回写全链路
- Cross-merchant（需第二 merchant fixture，mock auth 限制）
- Feedback Parse 合法格式（需确认 parser 正式接受格式）

**R1 状态：`M02_DOCKER_E2E_PARTIALLY_VERIFIED_PENDING_LOCAL_GAP_CLOSURE`**（无 BLOCKER，Gate A PARTIAL algorithm behavior，Gate B/D PASS，Gate C PARTIAL，Gate E CURRENT_REALITY_PASS，Gate F TEST_GAP）

## 2-M02.2R2 Local Behavior Gap Closure（2026-08-07）

### Gate A: Assignment Algorithm Matrix

利用已有 3 Sales fixture（A active+enable / B active+enable / C disabled），补验：

| Case | 准备 | 结果 | 证据 |
|---|---|---|---|
| 1 Inactive 过滤 | C disabled | **PASS** | assign to inactive staff_id=3 → 400 拒绝（正确） |
| 2 Lead 数量比较 | A=0 / B=1 assigned | **PASS** | 新 Lead 分配给 A（min leads=0）→ assigned_staff_id=1 验证通过 |
| 3 连续分配 | — | NOT_TESTED | 仅 1 条新 pending lead，无法验证连续多条轮询行为 |

**算法描述冻结（以 E2E 为准，非代码推测）**：

VERIFIED:
- merchant 过滤（CODE_VERIFIED）
- active 过滤（CODE_VERIFIED）
- enable_lead_assignment 过滤（CODE_VERIFIED）
- assigned 数量统计（CODE_VERIFIED）
- min-load / 少者优先（CODE_VERIFIED + E2E_VERIFIED：A=0/B=1→分配给 A）
- disabled direct assignment rejection（E2E_VERIFIED：C disabled→400 拒绝）

NOT_VERIFIED:
- 连续多次分配
- tie-breaking
- round-robin 运行行为

candidate filtering: CODE_VERIFIED
disabled direct assignment rejection: E2E_VERIFIED

### Gate B: Feedback Valid-Input Success Path

- **使用测试文件正式格式**（test_sales_feedback_parser.py 的 `【线索反馈】反馈编号：XGF-1-1\n微信：已通过\n开口：已开口...`）
- **结果**：POST /sales-feedback/parse 返回 400 SALES_FEEDBACK_PARSE_FAILED
- **分析**：即使使用测试文件的正式字段格式（`微信：`而非`微信状态：`），API 层仍返回 400。可能原因：
  1. API 层（sales_feedback.py:37）调用 `parse_and_persist_sales_feedback` 需要额外上下文（如 staff_id/lead_id 关联验证）
  2. parser 函数 `parse_sales_feedback_text` 可能在 API 上下文中行为与单元测试不同（DB 依赖/merchant 上下文）
  3. feedback_no `XGF-1-1` 可能需要对应真实 lead_id=1 + staff_id=1 的关联验证
- **登记 ISSUE**：ISSUE-M02-007 Feedback API 输入合同不清晰
- **不强行标 PASS**

### R2 状态

**`M02_DOCKER_E2E_VERIFIED_PENDING_STAGING`**（无 BLOCKER，Gate A PASS algorithm behavior 验证，Gate B ISSUE 登记）

Gate A 从 PARTIAL 升级为 PASS（inactive 过滤 + 少者优先 E2E 验证通过；连续分配 NOT_TESTED 但不阻断）。
Gate B 登记 ISSUE-M02-007（Feedback API 输入合同不清晰），不阻断 Baseline。

---

## M02_BASELINE_CANDIDATE

> 状态：**BASELINE_CANDIDATE**（非 MODULE_BASELINE_APPROVED）
> 代码基线：c26ec227e70d
> 后续补 staging 时只补 PENDING_STAGING，不重做全套探索/E2E

### VERIFIED

- Webhook 会话聚合
- 同客户新会话→新建 Lead
- Lead Data Owner = M02（M01/M04 为 EXTERNAL_WRITER/DATA_COUPLING）
- 商户内全部可见（merchant-level data scope）
- Assignment：merchant 过滤 + active + enable_lead_assignment + assigned min-load
- Reassign：owner 变更 + LeadFollowupRecord
- Contact/identity 当前行为
- Status 当前模型：DB 无约束 + 无独立公开 mutation API
- Feedback parser core + invalid-input handling

### NOT_VERIFIED

- 连续多次分配
- tie-breaking
- round-robin 运行行为

### PENDING_STAGING

- Cross-merchant real-auth isolation
- M01 真实 webhook→M02 Lead
- M02→M04 真实微信通知
- M04→M02 真实反馈持久化

### KNOWN ISSUE

- ISSUE-M02-007 Feedback parse-and-persist contract failure（MEDIUM）
- reassign_count 未自增（LOW）

### POLICY_PENDING / CONTRACT_GAP

- Manual Create identity behavior
- Lead vs Customer identity semantics
- 同客户多会话多 Lead policy

### LEGACY

- sync-leads：Lifecycle=LEGACY + still writable + different identity

### 冻结路径

staging → 补 PENDING_STAGING → `M02_MODULE_BASELINE_APPROVED`
M04 验真期间取得合格证据可复用，但必须回填 M02 验收记录
