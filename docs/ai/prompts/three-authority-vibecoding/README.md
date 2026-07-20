# Three-Authority VibeCoding Prompts

这些 Prompt 仅在项目按风险启用 Three-Authority VibeCoding Governance 后使用。先阅读[工作流入口](../../workflows/three-authority-vibecoding/README.md)和[交接契约](../../workflows/three-authority-vibecoding/handoff-contract.md)。

1. 从[审批窗口 Prompt](approver-window.md)开始。
2. 审批窗口动态生成 EXECUTION_WINDOW_INSTRUCTION，交给[执行窗口 Prompt](executor-window.md)。
3. 候选提交审查通过后，审批窗口再生成 TEST_WINDOW_INSTRUCTION，交给[测试窗口 Prompt](tester-window.md)。

三个 Prompt 不绑定模型或服务商。不得把三份 Prompt 加入项目默认 Required Reading。
