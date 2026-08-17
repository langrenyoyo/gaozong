# 启用规则

Three-Authority VibeCoding Governance 是风险驱动的可选工作流，不以修改文件数量、代码行数或所用模型作为启用依据。

## 风险判定

风险同时考虑：生产影响、数据可逆性、权限边界、跨模块合同、真实外部动作、回滚难度和故障可观测性。命中多个等级时取最高等级。

| 等级 | 典型任务 | 默认治理方式 |
|---|---|---|
| L0 低风险 | 文档、文案、注释、格式调整、不改变运行语义的修改 | 单节点可承载多种 Authority；执行最小有效验证 |
| L1 普通开发 | 局部页面、非核心 CRUD、小范围 Bug、非敏感配置 | 可用两个节点承载三权；独立验证范围可缩减 |
| L2 重要业务 | 跨模块修改、前后端联动、多服务合同、数据写入、大范围重构 | 推荐完整三权分离 |
| L3 高风险 | 鉴权、权限、商户或租户隔离、数据库迁移、数据删除/恢复、支付和算力、真实消息发送、生产配置、生产发布 | 必须完整三权分离；生产发布保留人工 Owner 批准权 |

## 启用条件

满足以下任一条件时至少按 L2 评估：

- 一个错误可能跨越多个服务或破坏对外合同；
- 变更会写入不可轻易恢复的数据；
- 施工者的自测无法提供独立证据；
- 回滚需要迁移、补偿任务或人工干预；
- 任务同时触及权限、隔离、安全或真实外部动作；
- 项目 Owner、审计制度或发布制度明确要求职责分离。

## 轻量流程边界

L0/L1 可以减少承载节点、交接轮次和测试矩阵，但必须保留：

- 明确范围与验收标准；
- 差异和工作区检查；
- 与风险相称的验证证据；
- 推送、合并或发布权限不得由未获授权的执行上下文自行扩大。

轻量流程不得用于掩盖 L2/L3 风险，也不得把环境阻塞写成通过。

## Authority 分配方式

- 普通开发者可以只操作 Decision Authority，由它动态生成 IMPLEMENTATION_AUTHORITY_INSTRUCTION；候选审查通过后再生成 VERIFICATION_AUTHORITY_INSTRUCTION。
- 可以使用两个、三个或更多窗口/Agent 承载三权；窗口数量不是风险等级或合规性的判断依据。
- 同一操作者可以协调多个 Authority，但中高风险任务中，承担某个 Candidate 实施的承载主体不得对同一 Candidate 输出 `ACCEPTED` 或 `DONE`；独立 Verification 也不得由该实施主体承担。
- 模型选择是调度策略而非安全边界；不同模型家族有助于独立判断，但不能替代候选哈希、验收矩阵和证据隔离。

## 启用记录

Decision Authority 在 PLAN_DRAFT 中记录：

~~~text
Risk-Level:
Workflow-Mode: combined-authority / dual-node / light-three-authority / full-three-authority
Activation-Reasons:
Owner-Constraints:
~~~

L2 若选择轻量模式，Decision Authority 必须记录理由、补偿验证和残余风险，不能静默降级。L3 若不能采用完整三权分离，必须由 Decision Authority 输出 REPLAN 或 REJECT_SCOPE。
