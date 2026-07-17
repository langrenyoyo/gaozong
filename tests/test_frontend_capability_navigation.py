import re
from pathlib import Path


def test_frontend_capability_navigation_has_only_product_centers_without_knowledge_management():
    source = Path("frontend/src/features/capabilities.ts").read_text(encoding="utf-8")

    expected_centers = [
        "抖音AI小高客服",
        "AI小高线索",
        "AI小高智能体",
        "小高AI微信助手",
        "小高算力",
    ]
    for center in expected_centers:
        assert f'title: "{center}"' in source

    configured_titles = re.findall(r'^\s+title: "', source, flags=re.MULTILINE)
    assert len(configured_titles) == 5
    assert "统一知识库训练" not in source
    assert "auto_wechat:knowledge" not in source


def test_frontend_legacy_routes_are_declared_as_redirects():
    source = Path("frontend/src/features/routes.ts").read_text(encoding="utf-8")

    expected_redirects = {
        "/douyin-ai-cs": "/douyin-cs/workbench",
        "/douyin-ai-cs-test": "/douyin-cs/workbench",
        "/ai-agent": "/wechat-assistant",
        "/compute": "/compute/center",
        "/knowledge-base": "/douyin-cs/workbench",
        "/knowledge-categories": "/douyin-cs/workbench",
    }
    for old_path, new_path in expected_redirects.items():
        assert f'from: "{old_path}"' in source
        assert f'to: "{new_path}"' in source


def test_frontend_feature_directories_have_required_entrypoints():
    feature_root = Path("frontend/src/features")
    expected_features = [
        "douyin-cs",
        "leads",
        "agents",
        "wechat-assistant",
        "compute",
    ]
    expected_files = ["api.ts", "types.ts", "routes.ts"]
    expected_dirs = ["pages", "components"]

    for feature in expected_features:
        feature_dir = feature_root / feature
        assert feature_dir.is_dir(), f"missing feature directory: {feature_dir}"
        for filename in expected_files:
            assert (feature_dir / filename).is_file(), f"missing feature entrypoint: {feature}/{filename}"
        for dirname in expected_dirs:
            assert (feature_dir / dirname).is_dir(), f"missing feature folder: {feature}/{dirname}"


def test_frontend_removes_historical_knowledge_management_and_debug_pages():
    removed_paths = [
        "frontend/src/features/knowledge/api.ts",
        "frontend/src/features/knowledge/routes.ts",
        "frontend/src/features/knowledge/pages/KnowledgeBasePage.tsx",
        "frontend/src/features/knowledge/pages/KnowledgeCategoriesPage.tsx",
        "frontend/src/pages/KnowledgeBasePage.tsx",
        "frontend/src/pages/KnowledgeCategoriesPage.tsx",
        "frontend/src/pages/DouyinAiCsTestPage.tsx",
        "frontend/src/features/douyin-cs/pages/DouyinAiCsTestPage.tsx",
        "frontend/src/api/knowledge.ts",
    ]
    for path in removed_paths:
        assert not Path(path).exists(), f"historical knowledge/debug entry should be removed: {path}"


def test_frontend_app_and_sidenav_consume_feature_aggregation():
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    sidenav_source = Path("frontend/src/components/SideNav.tsx").read_text(encoding="utf-8")

    assert './features/routes' in app_source
    assert '../features/capabilities' in sidenav_source
    assert './navigation/capabilityRoutes' not in app_source
    assert '../navigation/capabilityNav' not in sidenav_source


def test_frontend_api_clients_are_reexported_from_features():
    legacy_douyin = Path("frontend/src/api/douyinCs.ts").read_text(encoding="utf-8")
    feature_douyin = Path("frontend/src/features/douyin-cs/api.ts").read_text(encoding="utf-8")

    assert '../features/douyin-cs/api' in legacy_douyin
    assert "/rag/" not in feature_douyin
    assert "createRagDocument" not in feature_douyin
    assert "trainRag" not in feature_douyin


def test_frontend_does_not_expose_internal_service_token():
    frontend_root = Path("frontend/src")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in frontend_root.rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".env"}
    )

    assert "XG_DOUYIN_AI_CS_SERVICE_TOKEN" not in combined
    for env_example in [
        Path(".env.development.example"),
        Path(".env.lan.example"),
        Path(".env.production.example"),
    ]:
        env_source = env_example.read_text(encoding="utf-8")
        assert "VITE_XG_DOUYIN_AI_CS_SERVICE_TOKEN" not in env_source
        assert "VITE_INTERNAL_SERVICE_TOKEN" not in env_source


def test_agent_page_describes_knowledge_as_reply_scope_not_management():
    source = Path("frontend/src/features/agents/pages/SuperMerchantAgent.tsx").read_text(encoding="utf-8")

    expected_copy = [
        "AI 客服知识范围",
        "参考小高知识库",
        "小高知识库由管理员统一维护",
        "已关闭知识库参考",
    ]
    for text in expected_copy:
        assert text in source

    forbidden_copy = [
        "统一知识库训练预览",
        "输入训练问题",
        "发送训练问题",
        "知识库管理",
        "训练知识库",
        "上传知识库",
        "创建分类",
        "管理分类",
        "文档管理",
    ]
    for text in forbidden_copy:
        assert text not in source


def test_wechat_assistant_uses_browser_pending_task_api_instead_of_agent_poll_endpoint():
    api_source = Path("frontend/src/api/wechatTasks.ts").read_text(encoding="utf-8")
    feature_api_source = Path("frontend/src/features/wechat-assistant/api.ts").read_text(encoding="utf-8")
    page_source = Path("frontend/src/features/wechat-assistant/pages/WechatAgent.tsx").read_text(encoding="utf-8")
    panel_source = Path("frontend/src/features/wechat-assistant/components/WechatTaskPanel.tsx").read_text(encoding="utf-8")

    assert "fetchBrowserPendingWechatTasks" in api_source
    assert 'status: "pending"' in api_source
    assert "fetchBrowserPendingWechatTasks" in feature_api_source
    assert "fetchPendingWechatTasks" not in feature_api_source
    assert "fetchBrowserPendingWechatTasks" in page_source
    assert "fetchBrowserPendingWechatTasks" in panel_source
    assert "fetchPendingWechatTasks" not in page_source
    assert "fetchPendingWechatTasks" not in panel_source


def test_wechat_assistant_test_nickname_is_user_editable():
    source = Path("frontend/src/features/wechat-assistant/pages/WechatAgent.tsx").read_text(encoding="utf-8")

    assert "DEFAULT_TEST_NICKNAME" not in source
    assert "value={testNickname}" in source
    assert "setTestNickname(event.target.value)" in source
    assert "nickname: testNickname.trim()" in source
    assert "!testNickname.trim()" in source


def test_wechat_assistant_online_status_never_falls_back_to_server_heartbeat():
    source = Path("frontend/src/features/wechat-assistant/pages/WechatAgent.tsx").read_text(encoding="utf-8")

    assert "function agentOnlineText" not in source
    assert 'const onlineText = localAgentOnline ? "在线" : "离线";' in source


def test_wechat_assistant_status_and_version_are_shared_with_side_nav():
    index_source = Path("frontend/src/pages/Index.tsx").read_text(encoding="utf-8")
    side_nav_source = Path("frontend/src/components/SideNav.tsx").read_text(encoding="utf-8")

    assert "checkLocalAgentHealth" in index_source
    assert "fetchLocalAgentRuntimeStatus" in index_source
    assert index_source.count("localAgentOnline={localAgentOnline}") == 2
    assert "localAgentRuntimeStatus={localAgentRuntimeStatus}" in index_source
    assert "localAgentVersion={localAgentRuntimeStatus?.version || null}" in index_source
    assert "window.setInterval" in index_source

    assert "小高AI系统测试版" in side_nav_source
    assert 'localAgentOnline ? "在线" : "离线"' in side_nav_source
    assert "localAgentVersion || \"-\"" in side_nav_source
    assert "v3.8" not in side_nav_source


def test_frontend_docker_dev_uses_browser_api_proxy_instead_of_loopback_9000():
    compose_source = Path("docker-compose.dev.yml").read_text(encoding="utf-8")
    env_example_source = Path(".env.development.example").read_text(encoding="utf-8")

    assert "VITE_API_BASE_URL=${VITE_API_BASE_URL:-/api}" in compose_source
    assert "VITE_AUTO_WECHAT_API_BASE_URL=${VITE_AUTO_WECHAT_API_BASE_URL:-/api}" in compose_source
    assert "VITE_DOUYIN_AI_CS_API_BASE_URL=${VITE_DOUYIN_AI_CS_API_BASE_URL:-/ai-cs-api}" in compose_source
    assert "VITE_API_BASE_URL=http://127.0.0.1:9000" not in compose_source
    assert "VITE_AUTO_WECHAT_API_BASE_URL=http://127.0.0.1:9000" not in compose_source

    assert "VITE_API_BASE_URL=/api" in env_example_source
    assert "VITE_AUTO_WECHAT_API_BASE_URL=/api" in env_example_source
