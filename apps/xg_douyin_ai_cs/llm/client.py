"""OpenAI-compatible client using the Python standard library.

职责边界：
- chat() 走 XG_DOUYIN_AI_LLM_*（OpenAI / OpenRouter 兼容对话端点）；
- embed() 为门面：未配置真实 embedding 时回落 mock_embedding()，
  已配置火山方舟 Ark 时委托 ArkEmbeddingClient（见 ark_embedding_client.py）。
  embedding 与 chat 的 base_url / api_key / model 完全独立。
"""

from __future__ import annotations

import json
import logging
import time
from urllib.parse import urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request

from apps.xg_douyin_ai_cs.llm.ark_embedding_client import (
    ArkEmbeddingClient,
    ArkEmbeddingError,
)
from apps.xg_douyin_ai_cs.llm.config import LLMConfig, load_llm_config
from apps.xg_douyin_ai_cs.llm.embedding_config import load_embedding_config

_logger = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or load_llm_config()
        # embedding 配置独立于 chat/LLM 配置，避免共用 base_url/api_key/model
        self._embedding_config = load_embedding_config()

    def chat(self, messages: list[dict]) -> dict:
        if not self.config.configured:
            raise LLMNotConfiguredError("llm_not_configured")
        payload = {
            "model": self.config.chat_model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        started = time.perf_counter()
        data = self._post_json("/chat/completions", payload)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        choices = data.get("choices") or []
        message = (choices[0].get("message") if choices else {}) or {}
        return {
            "reply_text": str(message.get("content") or "").strip(),
            "model": data.get("model") or self.config.chat_model,
            "elapsed_ms": elapsed_ms,
            # P1-COMPUTE-USAGE-1：透传 OpenAI-compatible 响应中的 usage（prompt/completion/total_tokens）。
            # 响应未携带 usage 时为 None，由调用方（reply_decision_service）决定是否上报算力消耗。
            "usage": data.get("usage"),
        }

    def embed(self, text: str) -> dict:
        """生成 embedding 的门面入口。

        - 未配置真实 Ark embedding（enabled=false / key 空 / provider!=ark）
          → mock_embedding 兜底；
        - 已配置 → 委托 ArkEmbeddingClient，ArkEmbeddingError 统一转换为
          LLMRequestError，保持对外契约不变（repository /
          reply_decision_service 无需感知内部异常类型）。

        返回结构固定为 {embedding, model, embedding_provider}，
        repository.train_scope 仅读取 embedding / model，兼容无感。
        """
        cfg = self._embedding_config
        if not cfg.real_enabled:
            _logger.info(
                "embedding branch=mock provider=%s model=mock_for_test_only "
                "input_type=text text_len=%d reason=not_configured",
                cfg.provider,
                len(str(text or "")),
            )
            return {
                "embedding": mock_embedding(text),
                "model": "mock_for_test_only",
                "embedding_provider": "mock_for_test_only",
            }
        try:
            return ArkEmbeddingClient(cfg).embed_text(text)
        except ArkEmbeddingError as exc:
            _logger.warning(
                "embedding branch=ark stage=delegated_error error=%s", exc
            )
            raise LLMRequestError(str(exc)) from exc

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.config.base_url}{path}"
        req = urllib_request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib_request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except TimeoutError as exc:
            detail = self._build_timeout_detail(started)
            raise LLMRequestError("llm_provider_timeout", detail=detail) from exc
        except urllib_error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                detail = self._build_timeout_detail(started)
                raise LLMRequestError("llm_provider_timeout", detail=detail) from exc
            raise LLMRequestError(str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise LLMRequestError(str(exc)) from exc

    def _build_timeout_detail(self, started: float) -> dict:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        detail = {
            "error": "llm_provider_timeout",
            "timeout_layer": "9100_to_llm_provider",
            "elapsed_ms": elapsed_ms,
            "timeout_seconds": self.config.timeout_seconds,
            "provider": urlparse(self.config.base_url).netloc,
            "model": self.config.chat_model,
        }
        _logger.warning(
            "llm_provider_timeout stage=chat timeout_layer=9100_to_llm_provider "
            "provider=%s model=%s timeout_seconds=%s elapsed_ms=%s",
            detail["provider"],
            self.config.chat_model,
            self.config.timeout_seconds,
            elapsed_ms,
        )
        return detail


def mock_embedding(text: str, size: int = 16) -> list[float]:
    vector = [0.0] * size
    for index, char in enumerate(str(text or "")):
        vector[index % size] += (ord(char) % 97) / 97.0
    magnitude = sum(item * item for item in vector) ** 0.5 or 1.0
    return [round(item / magnitude, 6) for item in vector]
