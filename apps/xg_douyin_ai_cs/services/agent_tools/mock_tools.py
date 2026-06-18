"""Agent Runtime mock tool。

仅用于单元测试和关闭态骨架验证，不调用真实库存、支付或外部系统。
"""

from __future__ import annotations

from typing import Any

from apps.xg_douyin_ai_cs.services.agent_context import AgentContext
from apps.xg_douyin_ai_cs.services.agent_runtime import _env_bool
from apps.xg_douyin_ai_cs.services.agent_tools.base import (
    BaseToolAdapter,
    ToolRunResult,
)


class MockTool(BaseToolAdapter):
    name = "mock_tool"
    timeout_seconds = 1.0

    def is_enabled(self, context: AgentContext) -> bool:
        return _env_bool("XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED", False)

    def run(self, context: AgentContext, args: dict[str, Any]) -> ToolRunResult:
        return ToolRunResult(
            ok=True,
            data={
                "tool": self.name,
                "merchant_id": context.merchant_id,
                "douyin_account_id": context.douyin_account_id,
                "agent_id": context.agent_id,
                "args": args,
            },
            elapsed_ms=0,
        )
