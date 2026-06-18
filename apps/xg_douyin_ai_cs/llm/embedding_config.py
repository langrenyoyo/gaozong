"""9100 embedding 独立配置（与 chat/LLM 配置分离）。

设计要点：
- chat 走 XG_DOUYIN_AI_LLM_*（OpenRouter / OpenAI 兼容对话端点）；
- embedding 走 XG_DOUYIN_AI_EMBEDDING_*（火山方舟 Ark 多模态 embedding）；
- 两套 base_url / api_key / model 完全独立，避免互相污染。
- 兼容：当新的 XG_DOUYIN_AI_EMBEDDING_ENABLED 未设置时，
  回退读取旧变量 XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED，平滑过渡。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EmbeddingConfig:
    """火山方舟 Ark 多模态 embedding 配置。"""

    enabled: bool
    provider: str
    api_key: str
    base_url: str
    endpoint: str
    model: str
    dimensions: str  # 空字符串=不传，使用服务端默认
    encoding_format: str
    sparse_enabled: bool
    timeout_seconds: float

    @property
    def real_enabled(self) -> bool:
        """是否走真实 Ark 调用；否则回落 mock_embedding。

        三个条件全部满足才真实调用：
        1. enabled=True；
        2. api_key 非空；
        3. provider=='ark'。
        任一不满足都走 mock，保证零费用、零外部调用、零启动报错。
        """
        return (
            self.enabled
            and bool(self.api_key.strip())
            and self.provider == "ark"
        )


def _resolve_enabled() -> bool:
    """enabled 开关解析：新变量优先；未设置时回退旧变量。

    XG_DOUYIN_AI_EMBEDDING_ENABLED（新）优先；
    仅当新变量未设置（None 或空串）时，
    才回退读取 XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED（旧），
    以兼容 docker-compose.dev.yml / .env 中已写死的旧变量。
    """
    new_raw = os.environ.get("XG_DOUYIN_AI_EMBEDDING_ENABLED")
    if new_raw is not None and new_raw.strip() != "":
        return _env_bool("XG_DOUYIN_AI_EMBEDDING_ENABLED", False)
    return _env_bool("XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED", False)


def load_embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        enabled=_resolve_enabled(),
        provider=(
            os.environ.get("XG_DOUYIN_AI_EMBEDDING_PROVIDER", "ark").strip().lower()
            or "ark"
        ),
        api_key=os.environ.get("XG_DOUYIN_AI_EMBEDDING_API_KEY", "").strip(),
        base_url=os.environ.get(
            "XG_DOUYIN_AI_EMBEDDING_BASE_URL",
            "https://ark.cn-beijing.volces.com/api/v3",
        ).rstrip("/"),
        endpoint=(
            os.environ.get(
                "XG_DOUYIN_AI_EMBEDDING_ENDPOINT", "/embeddings/multimodal"
            ).strip()
            or "/embeddings/multimodal"
        ),
        model=(
            os.environ.get(
                "XG_DOUYIN_AI_EMBEDDING_MODEL", "doubao-embedding-vision-250615"
            ).strip()
            or "doubao-embedding-vision-250615"
        ),
        dimensions=os.environ.get("XG_DOUYIN_AI_EMBEDDING_DIMENSIONS", "").strip(),
        encoding_format=(
            os.environ.get("XG_DOUYIN_AI_EMBEDDING_ENCODING_FORMAT", "float").strip()
            or "float"
        ),
        sparse_enabled=_env_bool("XG_DOUYIN_AI_EMBEDDING_SPARSE_ENABLED", False),
        timeout_seconds=float(
            os.environ.get("XG_DOUYIN_AI_EMBEDDING_TIMEOUT_SECONDS", "120") or 120
        ),
    )
