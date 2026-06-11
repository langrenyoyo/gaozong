"""FastAPI 应用入口"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base
from app.routers import staff, leads, replies, checks, reports, feedback, integrations, wechat_auto_detect, lead_notifications, automation_control, wechat_tasks
from app.scheduler.check_scheduler import scheduler
from app.scheduler.wechat_auto_detect_scheduler import wechat_auto_detect_scheduler

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

    # 开发环境 CORS：允许本机和局域网 React 开发服务器跨域访问
    # 注意：局域网地址和主机名仅用于临时开发测试，上线前需移除
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://192.168.110.113:5173",
            "http://DESKTOP-T0HA3GO:5173",
        ],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(staff.router)
    app.include_router(leads.router)
    app.include_router(replies.router)
    app.include_router(checks.router)
    app.include_router(reports.router)
    app.include_router(feedback.router)
    app.include_router(integrations.router)
    app.include_router(wechat_auto_detect.router)
    app.include_router(lead_notifications.router)
    app.include_router(automation_control.router)
    app.include_router(wechat_tasks.router)

    @app.on_event("startup")
    def on_startup():
        scheduler.start()
        wechat_auto_detect_scheduler.start()
        # P8-4：全局热键 + 桌面提示
        from app.services.hotkey_listener import start_hotkey_listener
        from app.services.desktop_overlay import start_desktop_overlay
        start_hotkey_listener()
        start_desktop_overlay()

    @app.on_event("shutdown")
    def on_shutdown():
        scheduler.stop()
        wechat_auto_detect_scheduler.stop()
        # P8-4：释放热键 + 关闭桌面提示
        from app.services.hotkey_listener import stop_hotkey_listener
        from app.services.desktop_overlay import stop_desktop_overlay
        stop_hotkey_listener()
        stop_desktop_overlay()

    @app.get("/")
    def root():
        return {
            "name": "抖音线索销售微信回复检测系统 MVP",
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app


app = create_app()
