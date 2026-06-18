"""Agent tool 适配器基类。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.xg_douyin_ai_cs.services.agent_context import AgentContext


@dataclass(frozen=True)
class ToolRunResult:
    ok: bool
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    elapsed_ms: int | None = None


class BaseToolAdapter:
    name: str = ""
    timeout_seconds: float = 2.0

    def is_enabled(self, context: AgentContext) -> bool:
        return False

    def run(self, context: AgentContext, args: dict[str, Any]) -> ToolRunResult:
        raise NotImplementedError
