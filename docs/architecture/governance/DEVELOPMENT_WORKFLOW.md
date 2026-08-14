# Development Workflow（受治理开发工作流，DEV-WORKFLOW-SIMPLIFICATION-1）

> 本文件是把 Governance Baseline 的使用方式简化为日常可执行流程的入口。
> 治理事实与 SSOT 不变（见 `GOVERNANCE_BASELINE.yaml`）；改变的是"什么时候读取多少"。
> 默认开发模式：GOVERNED_FEATURE_DEVELOPMENT，默认任务等级 **L1**。

---

## 一、L1 / L2 / L3 三档任务模型

### L1 — 普通任务（默认）

适用（全部满足）：

```text
单一业务模块
无 DB schema change
无 public API breaking change
无跨模块新依赖
无 Legacy lifecycle change
无关键 Coupling change
无 Auth / merchant isolation 修改
无真实发送/扣费/删除等高风险副作用
无生产发布机制修改
```

默认流程：

```text
需求 → 确认模块 → 预计修改文件 → 测试方案 → Owner确认 → 最小实现 → 相关测试 → Review
```

不要求完整 Impact Contract。首轮输出建议 10~20 行：

```text
TASK_LEVEL               = L1
OWNER                    = Mxx
AFFECTED_AREA            = ...
EXPECTED_FILES           = ...
TEST_PLAN                = ...
KEY_RISK                 = LOW / ...
GOVERNANCE_DELTA_EXPECTED= NONE
IMPLEMENTATION           = WAITING_FOR_OWNER_APPROVAL
```

### L2 — 受控任务

以下任一成立时使用：

```text
跨模块修改
涉及现有 Legacy（引用 G2 legacy_id）
涉及现有 Coupling（引用 G4 coupling_id）
改变关键 CHAIN
新增/删除/移动正式代码导致 ownership 变化
重要业务链行为修改
需要同步 Governance Delta
```

流程：

```text
简版 Impact Contract → Owner确认 → 实施 → 对应 G3 verification → 必要 G1/G2/G3/G4 Delta → Review
```

简版 Impact Contract：

```text
TASK_LEVEL               = L2
OWNER                    = ...
AFFECTED_CHAIN           = ...
EXPECTED_FILES           = ...
LEGACY_IMPACT            = ...
COUPLING_IMPACT          = ...
VERIFICATION             = ...
DB_SCHEMA_CHANGE         = ...
PUBLIC_API_CHANGE        = ...
PRODUCTION_SIDE_EFFECT   = ...
MINIMAL_SCOPE            = ...
OUT_OF_SCOPE             = ...
IMPLEMENTATION           = WAITING_FOR_OWNER_APPROVAL
```

不要自动扩展成 G0~GC 审计报告。

### L3 — 高风险任务

以下任一成立时使用：

```text
DB schema / migration
Auth / RBAC
merchant isolation
真实抖音发送
真实微信操作
算力余额/扣费
Outbox / 高风险 scheduler
生产数据删除
公开 API breaking change
生产发布机制
重大跨模块架构调整
```

流程：

```text
完整 Impact Contract → 严格审批 → 执行窗口 → 独立测试/验收 → 审批 → 必要 Governance Delta
```

L3 可读取 `GOVERNANCE_BASELINE.yaml`、G1 Code Map、G2 Legacy Registry、G3 Verification Matrix、G4 Coupling Registry、Governance Backlog；但只读取与任务有关的事实，禁止为单个 L3 任务重扫全仓库建立"新现实地图"。

---

## 二、默认规则（最重要）

```text
DEFAULT_TASK_LEVEL = L1
```

- Governance Baseline 的存在本身，**不构成**将任务升级为 L2/L3 的理由。
- 禁止"所有任务 → 自动完整读取 G1/G2/G3/G4 → 自动输出长篇 Impact Contract"。
- 只有任务实际触碰相关风险时才展开对应治理读取。

---

## 三、Governance Delta 触发式（§七/§八）

```text
新增/删除/移动正式代码或 owner 事实变化   → G1 Delta
Legacy classification/lifecycle 变化      → G2 Delta
关键 CHAIN / verification baseline 变化   → G3 Delta
跨 owner dependency / coupling 变化       → G4 Delta
```

否则：

```text
GOVERNANCE_DELTA = NONE
```

**NO FACT CHANGE → NO GOVERNANCE DELTA**。例如 M01 单文件 bug fix（owner/CHAIN/Legacy/Coupling/Verification 方法均未变）：

```text
G1_DELTA = NO
G2_DELTA = NO
G3_DELTA = NO
G4_DELTA = NO
```

只运行相关 G3 测试即可。普通业务修改 ≠ 自动更新 G1/G2/G3/G4。

---

## 四、三权分离按风险启用

```text
L1：同一 VibeCoding 窗口（分析 → Owner确认 → 实施 → 测试），最终由 Owner/审批方 review
L2：视风险决定（同窗口实施 + 独立 review，或三权分离）
L3：默认 审批 → 执行 → 测试 → 审批
```

---

## 五、Owner 确认门（保留）

即使 L1，也保持：

```text
分析 → Owner确认 → 执行
```

不得变成"用户提出需求 → VibeCoding 自动直接修改"。这是执行窗口协作纪律的延续。

---

## 六、Governance Baseline 继续是后台事实源（保留）

```text
docs/architecture/governance/GOVERNANCE_BASELINE.yaml   （Manifest SSOT）
docs/architecture/governance/GOVERNANCE_BACKLOG.yaml    （开放问题索引）
G1 Code Map（code_index.yaml）｜G2 Legacy Registry（LEGACY_REGISTER.md）
G3 Verification Matrix（G3_MODULE_VERIFICATION_MATRIX.yaml）
G4 Coupling Registry（G4_COUPLING_REGISTRY.yaml）
```

改变的是"什么时候读取多少"，不是"把治理资产删掉"。

---

## 七、典型任务分级自检（验收场景）

| Case | 任务 | 预期等级 | 说明 |
|---|---|---|---|
| A | 修改 M05 素材库按钮文案 | **L1** | 单模块、无 schema/API/coupling/legacy/副作用 |
| B | 修 M01 一个内部函数 bug（不改 DB/API/模块边界） | **L1** | 单模块内部修复，Delta=NONE |
| C | M02 新增依赖 M04 私有 service | **L2** | 跨模块 + coupling review（引用 G4） |
| D | 删除 LEGACY-xxx | **L2** | 检查 G2 deletion condition + G3 affected verification |
| E | 新增 PostgreSQL migration | **L3** | DB schema 变更 |
| F | 修改抖音真实发送 gate | **L3** | 真实发送/安全 gate |
| G | 修改生产发布脚本 | **L3** | 生产发布机制（下一任务 PROD-RELEASE-AUTOMATION-MINIMAL-1 另行处理） |

---

## 八、设计方向

```text
80% 左右普通开发 → L1
较少跨边界开发   → L2
少数高风险开发   → L3
```

（设计方向，不创建 KPI / 机器统计。）
