"""Environment-only LLM configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    chat_model: str
    embedding_model: str
    timeout_seconds: float
    temperature: float

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip())


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url=os.environ.get("XG_DOUYIN_AI_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        api_key=os.environ.get("XG_DOUYIN_AI_LLM_API_KEY", "").strip(),
        chat_model=os.environ.get("XG_DOUYIN_AI_LLM_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        embedding_model=os.environ.get("XG_DOUYIN_AI_LLM_EMBEDDING_MODEL", "text-embedding-3-small").strip()
        or "text-embedding-3-small",
        timeout_seconds=float(os.environ.get("XG_DOUYIN_AI_LLM_TIMEOUT_SECONDS", "20") or 20),
        temperature=float(os.environ.get("XG_DOUYIN_AI_LLM_TEMPERATURE", "0.2") or 0.2),
    )
