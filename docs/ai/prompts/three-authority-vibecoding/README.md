# Three-Authority VibeCoding Prompts

这些 Prompt 仅在项目按风险启用 Three-Authority VibeCoding Governance 后使用。先阅读[工作流入口](../../workflows/three-authority-vibecoding/README.md)和[交接契约](../../workflows/three-authority-vibecoding/handoff-contract.md)。

1. 从 [Decision Authority Prompt](decision-authority.md) 开始。
2. Decision Authority 生成 `IMPLEMENTATION_AUTHORITY_INSTRUCTION`，交给 [Implementation Authority Prompt](implementation-authority.md)。
3. 候选提交审查通过后，Decision Authority 生成 `VERIFICATION_AUTHORITY_INSTRUCTION`，交给 [Verification Authority Prompt](verification-authority.md)。
4. Verification 输出独立证据；Decision 才能输出 `ACCEPTED`，适用 Gate 闭合后输出 `DONE`。

旧 [审批窗口](approver-window.md)、[执行窗口](executor-window.md)、[测试窗口](tester-window.md) 文件只作为兼容入口保留。

三个 Prompt 不绑定模型或服务商。不得把三份 Prompt 加入项目默认 Required Reading。
