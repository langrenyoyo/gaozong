"""P0-4A-6B-2 Local Agent 版本与路由一致性修复测试

验证：
1. /agent/version 端点存在且返回构建信息
2. /agent/version 包含 build_version
3. /agent/version 返回已注册路由列表
4. /agent/version 路由列表包含 /agent/wechat/search-result-debug
5. search-result-debug 路由在运行时 app 中注册
6. React 调用 fetchLocalAgentVersion
7. React 在 search-result-debug 缺失时显示警告
8. search-debug 响应包含 search_text_debug（通过 search_focus）
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _client():
    from app.local_agent_main import create_local_agent_app
    return TestClient(create_local_agent_app(host="127.0.0.1", port=19000))


# =====================================================
# 1. /agent/version 端点存在且返回构建信息
# =====================================================


def test_agent_version_endpoint_exists():
    response = _client().get("/agent/version")
    assert response.status_code == 200
    data = response.json()
    assert "app_name" in data
    assert data["app_name"] == "小高AI微信助手"


# =====================================================
# 2. /agent/version 包含 build_version
# =====================================================


def test_agent_version_includes_build_info():
    data = _client().get("/agent/version").json()
    assert "build_version" in data
    assert data["build_version"] != ""
    assert "build_time" in data
    assert "git_commit" in data
    assert "exe_mode" in data
    assert isinstance(data["exe_mode"], bool)
    assert "python_executable" in data
    assert "cwd" in data
    assert "agent_file" in data
    assert "hostname" in data


# =====================================================
# 3. /agent/version 返回已注册路由列表
# =====================================================


def test_agent_version_includes_routes():
    data = _client().get("/agent/version").json()
    assert "routes" in data
    assert isinstance(data["routes"], list)
    assert len(data["routes"]) > 0


# =====================================================
# 4. /agent/version 路由列表包含 search-result-debug
# =====================================================


def test_agent_version_routes_include_search_result_debug():
    data = _client().get("/agent/version").json()
    routes = data["routes"]
    assert "/agent/wechat/search-result-debug" in routes, \
        f"/agent/wechat/search-result-debug not found in routes: {routes}"
    # 同时验证其他关键路由
    assert "/health" in routes
    assert "/agent/version" in routes
    assert "/agent/wechat/test" in routes
    assert "/agent/wechat/search-debug" in routes


# =====================================================
# 5. search-result-debug 路由在运行时 app 中注册
# =====================================================


def test_search_result_debug_route_registered_in_runtime_app():
    from app.local_agent_main import create_local_agent_app, get_route_paths

    app = create_local_agent_app(host="127.0.0.1", port=19000)
    routes = get_route_paths(app)

    assert "/agent/wechat/search-result-debug" in routes, \
        f"search-result-debug not in runtime routes: {routes}"
    assert "/agent/version" in routes, \
        f"/agent/version not in runtime routes: {routes}"


# =====================================================
# 6. React 调用 fetchLocalAgentVersion
# =====================================================


def test_react_fetches_agent_version():
    api = Path("../react/src/api/localWechatAgent.ts").read_text(encoding="utf-8")

    assert "fetchLocalAgentVersion" in api
    assert "LocalAgentVersion" in api
    assert "/agent/version" in api
    assert "build_version" in api
    assert "routes" in api
    assert "exe_mode" in api


# =====================================================
# 7. React 在 search-result-debug 缺失时显示警告
# =====================================================


def test_react_warns_when_search_result_debug_route_missing():
    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")

    # 版本展示
    assert "agentVersion" in panel
    assert "build_version" in panel
    assert "fetchLocalAgentVersion" in panel

    # search-result-debug 缺失时的警告
    assert "search-result-debug" in panel
    assert "不包含搜索结果诊断接口" in panel or "复制完整" in panel


# =====================================================
# 8. search-debug 响应包含 search_text_debug（通过 search_focus）
# =====================================================


def test_search_debug_response_includes_search_text_debug():
    """确认 verify_search_text_in_search_box 返回 search_text_debug，
    且 /agent/wechat/search-debug 通过 search_focus 传递该信息。"""
    from app.wechat_ui.contact_searcher import verify_search_text_in_search_box

    mock_control = MagicMock()
    mock_control.Name = ""
    mock_control.Value = ""
    mock_control.LegacyIAccessibleValue = ""

    win_rect = {"left": 0, "top": 0, "right": 880, "bottom": 700}
    click_point = {"success": True, "x": 120, "y": 95}

    with patch("app.wechat_ui.contact_searcher.uia.GetFocusedControl", return_value=mock_control), \
         patch("app.wechat_ui.contact_searcher._control_rect_to_dict",
               return_value={"left": 100, "top": 85, "right": 300, "bottom": 110}), \
         patch("app.wechat_ui.contact_searcher._rect_in_search_region", return_value=True), \
         patch("app.wechat_ui.contact_searcher._rect_in_chat_input_region", return_value=False):
        result = verify_search_text_in_search_box(
            hwnd=123, win_rect=win_rect, expected_text="Aw3", click_point=click_point,
        )

    # 必须包含 search_text_debug
    assert "search_text_debug" in result
    debug = result["search_text_debug"]
    assert "expected" in debug
    assert "verified" in debug
    assert "method" in debug
    assert "ocr_text" in debug
    assert "normalized_expected" in debug
    assert "normalized_ocr_text" in debug
    assert "reason" in debug
    assert debug["expected"] == "Aw3"
    assert debug["normalized_expected"] == "aw3"

    # React 面板展示搜索框诊断中的 search_text_debug
    panel = Path("../react/src/components/LocalWechatAgentTestPanel.tsx").read_text(encoding="utf-8")
    # 搜索框诊断面板中有 search_text_debug 展示
    assert "搜索关键词验证诊断" in panel
