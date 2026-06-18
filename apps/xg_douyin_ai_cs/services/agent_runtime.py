"""抖音 AI 客服 Agent Runtime 门面。

当前为默认关闭的骨架，不引入 LangChain，不调用真实 tool。
"""

from __future__ import annotations

import os

from apps.xg_douyin_ai_cs.services.agent_context import (
    AgentContext,
    AgentRuntimeResult,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AgentRuntimeFacade:
    """业务层访问 Agent Runtime 的稳定门面。"""

    def __init__(self, enabled: bool | None = None):
        self._enabled = enabled

    def is_enabled(self) -> bool:
        if self._enabled is not None:
            return bool(self._enabled)
        return _env_bool("XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED", False)

    def suggest_reply(self, context: AgentContext) -> AgentRuntimeResult:
        """生成回复建议。

        关闭态不会进入本方法；若被显式调用，返回 fallback 结果，保证不发送。
        """
        return AgentRuntimeResult(
            reply_text="",
            tool_used=False,
            fallback_used=True,
            manual_required=False,
            auto_send=False,
            warnings=["agent_runtime_not_implemented"],
            audit={
                "tenant_id": context.tenant_id,
                "merchant_id": context.merchant_id,
                "douyin_account_id": context.douyin_account_id,
                "agent_id": context.agent_id,
                "conversation_id": context.conversation_id,
            },
        )
