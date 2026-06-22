"""FastAPI 应用入口"""

import logging
logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import engine, Base
from app.routers import (
    agent,
    staff,
    leads,
    checks,
    reports,
    integrations,
    wechat_auto_detect,
    automation_control,
    wechat_tasks,
    webhook_events,
    douyin_live_check,
    auth,
    douyin_ai_cs_proxy,
    ai_reply_decision_logs,
    douyin_autoreply_settings,
    ai_auto_reply_runs,
    douyin_accounts,
    agents,
    knowledge_categories,
    compute,
    capability_gateway,
)

# Windows 专用路由：依赖 comtypes / uiautomation，Linux/Docker 环境跳过
try:
    from app.routers import replies, feedback, lead_notifications
    _WINDOWS_ROUTERS_AVAILABLE = True
except ImportError:
    _WINDOWS_ROUTERS_AVAILABLE = False
    logger.warning("Windows 专用路由（replies/feedback/lead_notifications）导入跳过，当前平台不支持微信 UI 自动化")
from app.scheduler.check_scheduler import scheduler
from app.scheduler.wechat_auto_detect_scheduler import wechat_auto_detect_scheduler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


class UTF8JSONResponse(JSONResponse):
    """显式声明 charset=utf-8 的 JSON 响应。

    解决 Windows PowerShell 5.1 Invoke-RestMethod 对
    Content-Type: application/json（无 charset）按系统代码页解码导致中文乱码。
    """
    media_type = "application/json; charset=utf-8"


def create_app() -> FastAPI:
    """创建并返回 FastAPI 应用实例"""
    # 创建数据库表
    Base.metadata.create_all(bind=engine)

    app = FastAPI(
        title="抖音线索销售微信回复检测系统 MVP",
        version="0.1.0",
        description="实现 抖音线索→分配销售→录入回复→检测有效性→超时判断→报表统计 的 MVP 闭环",
        default_response_class=UTF8JSONResponse,
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

    # 注册路由（跨平台）
    app.include_router(staff.router)
    app.include_router(leads.router)
    app.include_router(checks.router)
    app.include_router(reports.router)
    app.include_router(integrations.router)
    app.include_router(integrations.legacy_webhook_router)
    app.include_router(wechat_auto_detect.router)
    app.include_router(automation_control.router)
    app.include_router(wechat_tasks.router)
    app.include_router(webhook_events.router)
    app.include_router(agent.router)
    app.include_router(douyin_live_check.router)
    app.include_router(auth.router)
    app.include_router(douyin_ai_cs_proxy.router)
    app.include_router(ai_reply_decision_logs.router)
    app.include_router(douyin_autoreply_settings.router)
    app.include_router(ai_auto_reply_runs.router)
    app.include_router(douyin_accounts.router)
    app.include_router(agents.router)
    app.include_router(knowledge_categories.router)
    app.include_router(compute.router)
    app.include_router(compute.admin_router)
    app.include_router(compute.internal_router)
    app.include_router(capability_gateway.router)

    # Windows 专用路由（微信 UI 自动化，Linux/Docker 不可用）
    if _WINDOWS_ROUTERS_AVAILABLE:
        app.include_router(replies.router)
        app.include_router(feedback.router)
        app.include_router(lead_notifications.router)

    @app.on_event("startup")
    def on_startup():
        scheduler.start()

        # P0-END-2A：旧 wechat_auto_detect_scheduler 默认禁用。
        # 新主线使用 19000 Local Agent 操作微信，旧调度器会在 9000 所在电脑直接操作微信导致冲突。
        # 如需恢复旧调度器（仅供开发调试或回退），设置环境变量 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1。
        from app.config import AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT
        if AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT:
            wechat_auto_detect_scheduler.start()
            logger.warning(
                "旧链路 wechat_auto_detect_scheduler 已通过环境变量启用。"
                "新主线应使用 19000 Local Agent 进行微信自动检测。"
            )
        else:
            logger.info(
                "旧链路 wechat_auto_detect_scheduler 默认禁用。"
                "新主线请使用 19000 Local Agent 进行微信自动检测。"
                "如需启用旧调度器，设置环境变量 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1。"
            )

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
