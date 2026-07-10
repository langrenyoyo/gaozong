"""FastAPI 应用入口"""

import logging
logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app import config
from app.database import (
    Base,
    close_async_database_runtime,
    engine,
    get_database_runtime,
    init_async_database_runtime,
)
from app.config import CORS_ORIGINS
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
    admin_autoreply_rollout,
    douyin_accounts,
    agents,
    knowledge_categories,
    knowledge_training,
    compute,
    capability_gateway,
    replies,
    lead_notification_actions,
    lead_notification_records,
    admin_debug,
    health,
)

# Windows 专用路由：依赖 comtypes / uiautomation，Linux/Docker 环境跳过
try:
    from app.routers import feedback, lead_notifications
    _WINDOWS_ROUTERS_AVAILABLE = True
except ImportError:
    _WINDOWS_ROUTERS_AVAILABLE = False
    logger.warning("Windows 专用路由（feedback/lead_notifications）导入跳过，当前平台不支持微信 UI 自动化")
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
    ensure_runtime_schema()

    app = FastAPI(
        title="抖音线索销售微信回复检测系统 MVP",
        version="0.1.0",
        description="实现 抖音线索→分配销售→录入回复→检测有效性→超时判断→报表统计 的 MVP 闭环",
        default_response_class=UTF8JSONResponse,
    )

    @app.exception_handler(SQLAlchemyTimeoutError)
    async def sqlalchemy_timeout_handler(request, exc):
        logger.error(
            "db_pool_timeout stage=db_pool_timeout endpoint=%s method=%s error_type=%s",
            request.url.path,
            request.method,
            type(exc).__name__,
        )
        return UTF8JSONResponse(
            status_code=503,
            content={
                "success": False,
                "message": "数据库连接繁忙，请稍后重试",
                "code": "DB_POOL_TIMEOUT",
            },
        )

    # 开发环境 CORS：允许本机和局域网 React 开发服务器跨域访问
    # 注意：局域网地址和主机名仅用于临时开发测试，上线前需移除
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
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
    app.include_router(auth.router, prefix="/api")
    app.include_router(douyin_ai_cs_proxy.router)
    app.include_router(ai_reply_decision_logs.router)
    app.include_router(douyin_autoreply_settings.router)
    app.include_router(ai_auto_reply_runs.router)
    app.include_router(admin_autoreply_rollout.router)
    app.include_router(douyin_accounts.router)
    app.include_router(agents.router)
    app.include_router(knowledge_categories.router)
    app.include_router(knowledge_training.router)
    app.include_router(compute.router)
    app.include_router(compute.admin_router)
    app.include_router(compute.internal_router)
    app.include_router(capability_gateway.router)
    app.include_router(replies.router)
    app.include_router(lead_notification_actions.router)
    app.include_router(lead_notification_records.router)
    app.include_router(admin_debug.router)
    app.include_router(health.router)

    # Windows 专用路由（微信 UI 自动化，Linux/Docker 不可用）
    if _WINDOWS_ROUTERS_AVAILABLE:
        app.include_router(feedback.router)
        app.include_router(lead_notifications.router)

    @app.on_event("startup")
    def on_startup():
        if config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED:
            database_runtime = get_database_runtime()
            if database_runtime.backend == "postgresql":
                init_async_database_runtime(database_runtime.raw_url)
            else:
                logger.info(
                    "async_db_runtime stage=startup_skip reason=database_backend_not_postgresql backend=%s",
                    database_runtime.backend,
                )

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
    async def on_shutdown():
        await close_async_database_runtime()
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


def ensure_runtime_schema() -> None:
    """SQLite 兼容路径自动建表；PostgreSQL 必须先通过 Alembic 初始化。"""
    database_runtime = get_database_runtime()
    if database_runtime.backend == "sqlite":
        Base.metadata.create_all(bind=engine)
        return
    if database_runtime.backend == "postgresql":
        logger.info(
            "db_schema stage=startup_skip_create_all backend=postgresql url=%s",
            getattr(database_runtime, "safe_url", "<unavailable>"),
        )
        return
    raise RuntimeError(f"不支持的数据库后端: {database_runtime.backend}")


app = create_app()
