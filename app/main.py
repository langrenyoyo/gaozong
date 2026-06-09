"""FastAPI 应用入口"""

import logging

from fastapi import FastAPI

from app.database import engine, Base
from app.routers import staff, leads, replies, checks, reports
from app.scheduler.check_scheduler import scheduler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def create_app() -> FastAPI:
    """创建并返回 FastAPI 应用实例"""
    # 创建数据库表
    Base.metadata.create_all(bind=engine)

    app = FastAPI(
        title="抖音线索销售微信回复检测系统 MVP",
        version="0.1.0",
        description="实现 抖音线索→分配销售→录入回复→检测有效性→超时判断→报表统计 的 MVP 闭环",
    )

    # 注册路由
    app.include_router(staff.router)
    app.include_router(leads.router)
    app.include_router(replies.router)
    app.include_router(checks.router)
    app.include_router(reports.router)

    @app.on_event("startup")
    def on_startup():
        scheduler.start()

    @app.on_event("shutdown")
    def on_shutdown():
        scheduler.stop()

    @app.get("/")
    def root():
        return {
            "name": "抖音线索销售微信回复检测系统 MVP",
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app


app = create_app()
