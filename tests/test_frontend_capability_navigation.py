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
        "knowledge",
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


def test_frontend_app_and_sidenav_consume_feature_aggregation():
    app_source = Path("frontend/src/App.tsx").read_text(encoding="utf-8")
    sidenav_source = Path("frontend/src/components/SideNav.tsx").read_text(encoding="utf-8")

    assert './features/routes' in app_source
    assert '../features/capabilities' in sidenav_source
    assert './navigation/capabilityRoutes' not in app_source
    assert '../navigation/capabilityNav' not in sidenav_source


def test_frontend_api_clients_are_reexported_from_features():
    legacy_douyin = Path("frontend/src/api/douyinCs.ts").read_text(encoding="utf-8")
    legacy_knowledge = Path("frontend/src/api/knowledge.ts").read_text(encoding="utf-8")
    feature_douyin = Path("frontend/src/features/douyin-cs/api.ts").read_text(encoding="utf-8")

    assert '../features/douyin-cs/api' in legacy_douyin
    assert '../features/knowledge/api' in legacy_knowledge
    assert "/rag/" not in feature_douyin
    assert "createRagDocument" not in feature_douyin
    assert "trainRag" not in feature_douyin


def test_frontend_does_not_expose_internal_service_token():
    frontend_root = Path("frontend/src")
    env_example = Path("frontend/.env.example")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in frontend_root.rglob("*")
        if path.is_file() and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".env"}
    )
    if env_example.exists():
        combined = f"{combined}\n{env_example.read_text(encoding='utf-8')}"

    assert "XG_DOUYIN_AI_CS_SERVICE_TOKEN" not in combined
    assert "VITE_XG_DOUYIN_AI_CS_SERVICE_TOKEN" not in combined
    assert "VITE_INTERNAL_SERVICE_TOKEN" not in combined
