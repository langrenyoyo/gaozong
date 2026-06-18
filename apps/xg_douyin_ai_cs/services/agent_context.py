"""9100 Agent Runtime 上下文对象。

本模块只定义内存数据结构，不读取数据库、不调用外部系统。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    """Agent Runtime 的可信上下文载体。

    当前字段由 reply-suggestion 请求与服务端解析结果组装；后续接入
    NewCarProject / 9000 时，merchant_id 等字段必须改为服务端可信来源。
    """

    tenant_id: str | None
    merchant_id: str | None
    douyin_account_id: int | str | None
    agent_id: str | None
    conversation_id: str | int
    customer_open_id: str | None
    latest_message: str | None
    max_history_messages: int = 20
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRuntimeResult:
    """Agent Runtime 的统一返回结构。

    一期关闭态不替代现有 ReplySuggestionResponse，只作为二期扩展契约。
    """

    reply_text: str
    tool_used: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    fallback_used: bool = False
    manual_required: bool = False
    auto_send: bool = False
    warnings: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)
