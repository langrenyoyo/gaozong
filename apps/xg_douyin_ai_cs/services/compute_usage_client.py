"""9100 → 9000 小高算力 Token 消耗上报客户端（P1-COMPUTE-USAGE-1）。

职责：
- 将 9100 LLM chat 成功后的 token 消耗上报到 9000 /internal/compute/usage。
- 上报失败（网络错误/9000 错误/缺配置）只记日志，**绝不抛异常**，避免影响 AI 回复主流程。
- 缺 base_url 或 COMPUTE_INTERNAL_TOKEN 时跳过上报（本地开发友好）。

边界（一期）：
- 仅 chat token 消耗（source=llm），不含 embedding。
- 不做余额拦截、不重试、不阻塞主流程、不自动发送任何消息。
- 与 9000 通过 HTTP 通信，不共享数据库。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from urllib import error as urllib_error
from urllib import request as urllib_request

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatUsageMeasurement:
    """单次聊天模型调用的计量结果。"""

    tokens: int
    measurement_method: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None


def _nonnegative_int(value: object) -> int | None:
    """只接受非负整数，显式排除 bool。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _estimate_text_tokens(text: str) -> int:
    """供应商未返回用量时的保守估算，不引入模型专用分词依赖。"""
    total = 0
    ascii_run = 0
    for char in text:
        if ord(char) < 128:
            ascii_run += 1
            continue
        total += (ascii_run + 3) // 4
        ascii_run = 0
        total += 1
    return max(1, total + (ascii_run + 3) // 4)


def measure_chat_usage(messages: list[dict], result: dict) -> ChatUsageMeasurement:
    """优先使用供应商真实 Token，缺失时回退字符估算。"""
    raw_usage = result.get("usage") if isinstance(result, dict) else None
    usage = raw_usage if isinstance(raw_usage, dict) else {}

    prompt_tokens = _nonnegative_int(usage.get("prompt_tokens"))
    if prompt_tokens is None:
        prompt_tokens = _nonnegative_int(usage.get("input_tokens"))
    completion_tokens = _nonnegative_int(usage.get("completion_tokens"))
    if completion_tokens is None:
        completion_tokens = _nonnegative_int(usage.get("output_tokens"))
    total_tokens = _nonnegative_int(usage.get("total_tokens"))

    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    cached_tokens = (
        _nonnegative_int(details.get("cached_tokens"))
        if isinstance(details, dict)
        else None
    )

    if total_tokens is not None and total_tokens > 0:
        return ChatUsageMeasurement(
            total_tokens,
            "provider_tokens",
            prompt_tokens,
            completion_tokens,
            cached_tokens,
        )
    if (
        prompt_tokens is not None
        and completion_tokens is not None
        and prompt_tokens + completion_tokens > 0
    ):
        return ChatUsageMeasurement(
            prompt_tokens + completion_tokens,
            "provider_tokens",
            prompt_tokens,
            completion_tokens,
            cached_tokens,
        )

    request_text = "".join(
        item["content"]
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    )
    reply_text = str(result.get("reply_text") or "") if isinstance(result, dict) else ""
    return ChatUsageMeasurement(
        _estimate_text_tokens(request_text + reply_text),
        "estimated_tokens",
    )


def count_chat_characters(messages: list[dict], reply_text: str) -> int:
    """Phase 10 §0.2 计费合同：chat 消息内容字符数总和 + 回复字符数，不做 strip。

    所有业务服务的 chat 上报必须经过本 helper，避免算法重复漂移。
    """
    return sum(
        len(item["content"])
        for item in messages
        if isinstance(item, dict) and isinstance(item.get("content"), str)
    ) + len(reply_text)


def count_embedding_characters(text: str) -> int:
    """Phase 10 §0.2 计费合同：embedding 按输入文本 Python 字符数计量。"""
    return len(text)


def _normalize_conversation_id(value) -> int | None:
    """Phase 10 §0.2：会话 ID 归一为 int 或 None。

    正式链路用字符串 conversation_short_id（非纯数字）；9000 整数 DTO 收到非数字会
    int_parsing 422，导致 AI 正常返回但消费漏记。归一在 9100 计费元数据层完成，
    不扩表、不改 9000 现有整数列：纯数字（含数字字符串）→ int，其余 → None。
    """
    if isinstance(value, bool):  # bool 是 int 子类，必须先排除
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = value.strip()
        if digits.isdigit():
            return int(digits)
    return None


@dataclass(frozen=True)
class ComputeUsageConfig:
    """算力上报配置（环境变量驱动，与 llm/config.py 风格一致）。"""

    base_url: str
    internal_token: str
    timeout_seconds: float

    @property
    def enabled(self) -> bool:
        """base_url 与 internal_token 均配置才启用上报。"""
        return bool(self.base_url.strip()) and bool(self.internal_token.strip())


def load_compute_usage_config() -> ComputeUsageConfig:
    """从环境变量加载算力上报配置。"""
    return ComputeUsageConfig(
        base_url=os.environ.get("AUTO_WECHAT_9000_BASE_URL", "").strip().rstrip("/"),
        internal_token=os.environ.get("COMPUTE_INTERNAL_TOKEN", "").strip(),
        timeout_seconds=float(os.environ.get("COMPUTE_USAGE_TIMEOUT_SECONDS", "5") or 5),
    )


class ComputeUsageClient:
    """9100 → 9000 算力消耗上报客户端。"""

    USAGE_PATH = "/internal/compute/usage"

    def __init__(self, config: ComputeUsageConfig | None = None):
        self.config = config or load_compute_usage_config()

    def report_usage(
        self,
        *,
        merchant_id: str,
        tokens: int,
        capability_key: str,
        model: str,
        source: str = "llm",
        agent_id: str | None = None,
        conversation_id: int | None = None,
        remark: str | None = None,
    ) -> bool:
        """上报一次算力消耗。成功返回 True，跳过/失败返回 False，**绝不抛异常**。

        跳过条件：配置未启用（缺 base_url 或 internal_token）、tokens<=0、缺 merchant_id、
        缺 capability_key 或 model。调用方无需 try/except，上报失败不影响 AI 回复主流程。
        Phase 10 §0.2：capability_key/model 必填；payload 与日志只记 merchant_id、字符数、
        capability、model、状态，不含提示词、销售回复、模型输出或知识片段原文。
        """
        if not self.config.enabled:
            _logger.info(
                "compute_usage stage=skipped reason=not_configured "
                "base_url_set=%s token_set=%s",
                bool(self.config.base_url),
                bool(self.config.internal_token),
            )
            return False

        # FIX2 §0.2：空白 merchant_id（" "）strip 后为空，拒绝上报（零网络尝试），不伪造计费归属
        merchant_id = str(merchant_id or "").strip()
        if tokens <= 0 or not merchant_id or not capability_key or not model:
            _logger.info(
                "compute_usage stage=skipped reason=invalid_payload "
                "merchant_id_set=%s tokens=%s capability=%s model_set=%s",
                bool(merchant_id),
                tokens,
                capability_key,
                bool(model),
            )
            return False

        payload = {
            "merchant_id": merchant_id,
            "tokens": int(tokens),
            "capability_key": capability_key,
            "source": source,
            "model": model,
            "agent_id": agent_id,
            "conversation_id": _normalize_conversation_id(conversation_id),
            "remark": remark,
        }
        req = urllib_request.Request(
            f"{self.config.base_url}{self.USAGE_PATH}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Token": self.config.internal_token,
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                body = resp.read().decode("utf-8", errors="replace")
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            _logger.warning(
                "compute_usage stage=request_failed error=%s merchant_id=%s",
                exc,
                merchant_id,
            )
            return False
        except Exception as exc:  # noqa: BLE001  上报失败绝不能影响 AI 回复主流程
            _logger.warning(
                "compute_usage stage=unexpected_error error=%s merchant_id=%s",
                exc,
                merchant_id,
            )
            return False

        if status != 200:
            _logger.warning(
                "compute_usage stage=bad_status status=%s merchant_id=%s body=%s",
                status,
                merchant_id,
                body[:200],
            )
            return False

        _logger.info(
            "compute_usage stage=reported merchant_id=%s tokens=%s capability=%s model=%s",
            merchant_id,
            tokens,
            capability_key,
            model,
        )
        return True
