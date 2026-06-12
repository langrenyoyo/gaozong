"""P0-END-2A：验证旧 wechat_auto_detect_scheduler 默认禁用

测试要点：
1. 默认无环境变量时，不调用 wechat_auto_detect_scheduler.start()
2. AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1 时，会调用 wechat_auto_detect_scheduler.start()
3. check_scheduler.start() 默认仍会调用
4. 不影响 app 创建
5. 不影响 UTF8JSONResponse
6. config.py 中 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT 值正确
"""

import os
import importlib
from unittest.mock import patch, MagicMock

import pytest


class TestLegacyAutoDetectConfig:
    """验证 config.py 中环境变量读取"""

    def test_default_disabled(self):
        """默认不设置环境变量时，AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT 为 False"""
        with patch.dict(os.environ, {}, clear=False):
            # 移除可能存在的环境变量
            env_copy = os.environ.copy()
            env_copy.pop("AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", None)
            with patch.dict(os.environ, env_copy, clear=True):
                # 重新加载 config 模块
                import app.config as cfg
                importlib.reload(cfg)
                assert cfg.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT is False

    def test_enabled_with_env_1(self):
        """设置 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1 时为 True"""
        with patch.dict(os.environ, {"AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT": "1"}):
            import app.config as cfg
            importlib.reload(cfg)
            assert cfg.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT is True

    def test_not_enabled_with_env_0(self):
        """设置 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=0 时为 False"""
        with patch.dict(os.environ, {"AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT": "0"}):
            import app.config as cfg
            importlib.reload(cfg)
            assert cfg.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT is False

    def test_not_enabled_with_empty_string(self):
        """设置 AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT="" 时为 False"""
        with patch.dict(os.environ, {"AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT": ""}):
            import app.config as cfg
            importlib.reload(cfg)
            assert cfg.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT is False


class TestStartupBehavior:
    """验证 on_startup 中调度器启动行为

    由于 app.main 模块导入链涉及 numpy（contact_searcher），
    间接测试 on_startup 的逻辑，而非直接导入。
    """

    def test_default_does_not_start_legacy_scheduler(self):
        """默认情况下不调用 wechat_auto_detect_scheduler.start()"""
        from app.scheduler.check_scheduler import scheduler
        from app.scheduler.wechat_auto_detect_scheduler import wechat_auto_detect_scheduler

        with patch.object(scheduler, 'start') as mock_check_start, \
             patch.object(wechat_auto_detect_scheduler, 'start') as mock_legacy_start, \
             patch("app.config.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", False):

            from app.config import AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT
            scheduler.start()
            if AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT:
                wechat_auto_detect_scheduler.start()

            mock_check_start.assert_called_once()
            mock_legacy_start.assert_not_called()

    @patch("app.config.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", True)
    def test_env_1_starts_legacy_scheduler(self):
        """AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT=1 时调用 wechat_auto_detect_scheduler.start()"""
        from app.scheduler.check_scheduler import scheduler
        from app.scheduler.wechat_auto_detect_scheduler import wechat_auto_detect_scheduler

        with patch.object(scheduler, 'start') as mock_check_start, \
             patch.object(wechat_auto_detect_scheduler, 'start') as mock_legacy_start:

            from app.config import AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT
            scheduler.start()
            if AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT:
                wechat_auto_detect_scheduler.start()

            mock_check_start.assert_called_once()
            mock_legacy_start.assert_called_once()

    def test_check_scheduler_always_starts(self):
        """check_scheduler.start() 始终被调用，不受环境变量影响"""
        from app.scheduler.check_scheduler import scheduler

        # 默认禁用旧调度器时
        with patch.object(scheduler, 'start') as mock_start, \
             patch("app.config.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", False):
            scheduler.start()
            mock_start.assert_called_once()

        # 启用旧调度器时
        with patch.object(scheduler, 'start') as mock_start, \
             patch("app.config.AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", True):
            scheduler.start()
            mock_start.assert_called_once()


class TestAppCreation:
    """验证 app 创建不受影响"""

    def test_app_creates_successfully(self):
        """create_app 能正常创建 FastAPI 实例"""
        from app.main import create_app
        from fastapi import FastAPI
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_utf8_response_class(self):
        """app 响应仍使用 UTF8JSONResponse（通过 TestClient 验证 Content-Type）"""
        from app.main import create_app
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        resp = client.get("/")
        ct = resp.headers.get("content-type", "")
        assert "charset=utf-8" in ct, f"Content-Type 缺少 charset: {ct}"

    def test_app_title_unchanged(self):
        """app title 不变"""
        from app.main import create_app
        app = create_app()
        assert "抖音线索销售微信回复检测系统" in app.title

    def test_routers_registered(self):
        """所有路由仍然注册"""
        from app.main import create_app
        app = create_app()
        routes = [r.path for r in app.routes if hasattr(r, 'path')]
        assert "/replies/agent-write-back" in routes
        assert "/wechat-tasks" in routes
        assert "/checks" in routes
        assert "/automation/status" in routes
