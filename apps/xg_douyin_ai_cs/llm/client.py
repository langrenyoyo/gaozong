"""OpenAI-compatible client using the Python standard library."""

from __future__ import annotations

import json
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

from apps.xg_douyin_ai_cs.llm.config import LLMConfig, load_llm_config


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    pass


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or load_llm_config()

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
        }

    def embed(self, text: str) -> dict:
        if not self.config.real_embedding_configured:
            return {
                "embedding": mock_embedding(text),
                "model": "mock_for_test_only",
                "embedding_provider": "mock_for_test_only",
            }
        data = self._post_json(
            "/embeddings",
            {"model": self.config.embedding_model, "input": text},
        )
        embedding = ((data.get("data") or [{}])[0].get("embedding")) or []
        if not embedding:
            raise LLMRequestError("embedding endpoint returned empty vector")
        return {
            "embedding": [float(item) for item in embedding],
            "model": data.get("model") or self.config.embedding_model,
            "embedding_provider": "openai_compatible",
        }

    def _post_json(self, path: str, payload: dict) -> dict:
        req = urllib_request.Request(
            f"{self.config.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMRequestError(str(exc)) from exc


def mock_embedding(text: str, size: int = 16) -> list[float]:
    vector = [0.0] * size
    for index, char in enumerate(str(text or "")):
        vector[index % size] += (ord(char) % 97) / 97.0
    magnitude = sum(item * item for item in vector) ** 0.5 or 1.0
    return [round(item / magnitude, 6) for item in vector]
