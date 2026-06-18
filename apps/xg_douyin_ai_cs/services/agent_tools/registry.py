"""Agent tool 注册表。"""

from __future__ import annotations

from typing import Any

from apps.xg_douyin_ai_cs.services.agent_context import AgentContext
from apps.xg_douyin_ai_cs.services.agent_tools.base import (
    BaseToolAdapter,
    ToolRunResult,
)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseToolAdapter] = {}

    def register(self, tool: BaseToolAdapter) -> None:
        if not tool.name:
            raise ValueError("tool name must not be empty")
        self._tools[tool.name] = tool

    def get_enabled_tools(self, context: AgentContext) -> list[BaseToolAdapter]:
        return [tool for tool in self._tools.values() if tool.is_enabled(context)]

    def run_tool(
        self,
        name: str,
        context: AgentContext,
        args: dict[str, Any],
    ) -> ToolRunResult:
        tool = self._tools.get(name)
        if not tool or not tool.is_enabled(context):
            raise KeyError(name)
        return tool.run(context, args)
