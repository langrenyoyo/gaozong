"""抖音AI小高客服 P0 配置。"""

from dataclasses import dataclass
import os
from pathlib import Path

from .constants import DEFAULT_HOST, DEFAULT_PORT, SERVICE_NAME, SERVICE_VERSION


@dataclass(frozen=True)
class Settings:
    """9100 独立服务配置。

    P0 不读取数据库、LLM、队列或 9000/19000 地址，避免启动副作用。
    """

    service_name: str = SERVICE_NAME
    version: str = SERVICE_VERSION
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @property
    def rag_db_path(self) -> Path:
        raw = os.environ.get("XG_DOUYIN_AI_CS_DB_PATH", "").strip()
        if raw:
            return Path(raw)
        return Path(__file__).resolve().parent / "data" / "xg_douyin_ai_cs.db"

    @property
    def rag_vector_backend(self) -> str:
        return os.environ.get("RAG_VECTOR_BACKEND", "sqlite").strip().lower() or "sqlite"

    @property
    def milvus_uri(self) -> str:
        return os.environ.get("MILVUS_URI", "").strip()

    @property
    def milvus_username(self) -> str:
        return os.environ.get("MILVUS_USERNAME", "").strip()

    @property
    def milvus_password(self) -> str:
        return os.environ.get("MILVUS_PASSWORD", "").strip()

    @property
    def milvus_db_name(self) -> str:
        return os.environ.get("MILVUS_DB_NAME", "").strip()

    @property
    def milvus_collection(self) -> str:
        return os.environ.get("MILVUS_COLLECTION", "").strip()

    @property
    def milvus_dimension(self) -> int | None:
        raw = os.environ.get("MILVUS_DIMENSION", "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value > 0 else None

    @property
    def milvus_timeout_seconds(self) -> float:
        raw = os.environ.get("MILVUS_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return 5.0
        try:
            value = float(raw)
        except ValueError:
            return 5.0
        return value if value > 0 else 5.0

    @property
    def milvus_index_type(self) -> str:
        return os.environ.get("MILVUS_INDEX_TYPE", "AUTOINDEX").strip() or "AUTOINDEX"

    @property
    def milvus_metric_type(self) -> str:
        return os.environ.get("MILVUS_METRIC_TYPE", "COSINE").strip().upper() or "COSINE"


settings = Settings()
