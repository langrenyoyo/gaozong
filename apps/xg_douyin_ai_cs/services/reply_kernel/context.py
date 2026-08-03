"""ReplyContext 与 FactMetadata 数据结构（P0-B 纯业务模块）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class FactMetadata:
    """客户事实来源信息。"""

    source_type: Literal[
        "DATABASE_VERIFIED",
        "CUSTOMER_STATED",
        "MESSAGE_EXTRACTED",
        "PREVIEW_SIMULATED",
        "TRAINING_FIXTURE",
        "AI_INFERRED",
        "UNAVAILABLE",
    ]
    source_message_id: str | None = None
    confidence: float = 0.0
    confirmed_at: str | None = None
    persisted: bool = False
    profile_version: int | None = None


@dataclass(frozen=True)
class ReplyContext:
    """统一请求上下文（纯数据，无副作用）。

    P0-B 不含 contact_request_status 持久状态（P0-C 才有），默认占位 "UNKNOWN"。
    """

    context_mode: Literal["live", "live_preview", "simulated_preview", "training"]
    latest_customer_message: str
    contact_state: str  # NONE/PARTIAL/VALID/INVALID/AMBIGUOUS
    contact_state_source: str  # request/local_fallback/training_default
    # P0-B 占位，policy 关闭不消费；P0-C 才有真实交互状态
    contact_request_status: str = "UNKNOWN"
    agent_phone_goal: bool = False
    scene_suitable_for_lead: bool = True
    customer_refused_lead: bool = False
    # 客户事实（可选，P0-B 仅透传 known_customer 已有字段）
    known_customer_info: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReplyMessage:
    """统一输出消息。P0-B 严格 sequence=1。"""

    sequence: int  # 必须等于 1
    purpose: str  # answer/follow_up/contact_request/handoff
    text: str
