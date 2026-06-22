import re
from pathlib import Path


def test_frontend_capability_navigation_has_only_six_top_level_centers():
    source = Path("frontend/src/navigation/capabilityNav.ts").read_text(encoding="utf-8")

    expected_centers = [
        "抖音AI小高客服",
        "AI小高线索",
        "AI小高智能体",
        "AI小高微信助手",
        "小高算力",
        "统一知识库训练",
    ]
    for center in expected_centers:
        assert f'title: "{center}"' in source

    configured_titles = re.findall(r'^\s+title: "', source, flags=re.MULTILINE)
    assert len(configured_titles) == 6


def test_frontend_legacy_routes_are_declared_as_redirects():
    source = Path("frontend/src/navigation/capabilityRoutes.ts").read_text(encoding="utf-8")

    expected_redirects = {
        "/douyin-ai-cs": "/douyin-cs/workbench",
        "/douyin-ai-cs-test": "/douyin-cs/test",
        "/ai-agent": "/wechat-assistant",
        "/compute": "/compute/center",
        "/knowledge-base": "/knowledge/base",
        "/knowledge-categories": "/knowledge/categories",
    }
    for old_path, new_path in expected_redirects.items():
        assert f'from: "{old_path}"' in source
        assert f'to: "{new_path}"' in source
