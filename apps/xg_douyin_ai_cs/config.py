"""抖音AI小高客服 P0 配置。"""

from dataclasses import dataclass
import os
from pathlib import Path

from app.database_url import parse_database_url
from .constants import DEFAULT_HOST, DEFAULT_PORT, SERVICE_NAME, SERVICE_VERSION


def _positive_int_env(name: str, default: int) -> int:
    """读取正整数配置；非法值回落默认，避免脏环境变量阻断服务启动。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


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
    def rag_database_url(self) -> str:
        raw_url = os.environ.get("RAG_DATABASE_URL", "").strip()
        if raw_url:
            return raw_url
        raw_path = os.environ.get("XG_DOUYIN_AI_CS_DB_PATH", "").strip()
        if raw_path:
            return f"sqlite:///{raw_path}"
        default_path = Path(__file__).resolve().parent / "data" / "xg_douyin_ai_cs.db"
        return f"sqlite:///{default_path}"

    @property
    def rag_db_path(self) -> Path:
        parsed = parse_database_url(self.rag_database_url)
        if parsed.backend != "sqlite" or not parsed.sqlite_path:
            raise ValueError("当前 9100 SQLite 运行路径只支持 sqlite RAG_DATABASE_URL")
        return Path(parsed.sqlite_path)

    @property
    def rag_db_pool_size(self) -> int:
        return _positive_int_env("RAG_DB_POOL_SIZE", 20)

    @property
    def rag_db_max_overflow(self) -> int:
        return _positive_int_env("RAG_DB_MAX_OVERFLOW", 40)

    @property
    def rag_db_pool_timeout(self) -> int:
        return _positive_int_env("RAG_DB_POOL_TIMEOUT", 30)

    @property
    def rag_db_pool_recycle(self) -> int:
        return _positive_int_env("RAG_DB_POOL_RECYCLE", 1800)

    @property
    def rag_db_statement_timeout_ms(self) -> int:
        return _positive_int_env("RAG_DB_STATEMENT_TIMEOUT_MS", 5000)

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

    @property
    def milvus_connect_strategy(self) -> str:
        return os.environ.get("MILVUS_CONNECT_STRATEGY", "orm").strip().lower() or "orm"


settings = Settings()
