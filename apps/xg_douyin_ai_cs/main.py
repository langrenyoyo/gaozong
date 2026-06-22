"""抖音AI小高客服 9100 独立 FastAPI 入口。"""

from __future__ import annotations

import argparse
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.xg_douyin_ai_cs.config import settings
from apps.xg_douyin_ai_cs.routers import (
    accounts,
    ai_reply,
    categories,
    conversations,
    health,
    knowledge_training,
    rag,
)

logger = logging.getLogger(__name__)

LOCAL_FRONTEND_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


def create_app() -> FastAPI:
    """创建 9100 独立应用。

    P0 不导入 9000、19000、微信 UI、数据库或队列模块。
    """
    app = FastAPI(
        title="抖音AI小高客服",
        version=settings.version,
        description="抖音AI小高客服 9100 独立功能系统 P0 骨架",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_FRONTEND_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(categories.router)
    app.include_router(accounts.router)
    app.include_router(conversations.router)
    app.include_router(ai_reply.router)
    app.include_router(rag.router)
    app.include_router(knowledge_training.router)
    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动抖音AI小高客服 9100 服务")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    return parser


def main() -> int:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    args = build_parser().parse_args()
    logger.info(
        "starting %s: host=%s port=%s",
        settings.service_name,
        args.host,
        args.port,
    )
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


app = create_app()


if __name__ == "__main__":
    raise SystemExit(main())
