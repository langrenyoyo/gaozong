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


settings = Settings()
