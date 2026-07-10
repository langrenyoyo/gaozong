from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRD_CONTEXT = ROOT / "docs/ai/01_product_prd/小高AI系统一期_需求理解与VibeCoding指令.md"
CLAUDE = ROOT / "CLAUDE.md"
CAPABILITIES = ROOT / "frontend/src/features/capabilities.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase1_context_includes_confirmed_scope():
    text = _read(PRD_CONTEXT)
    required = [
        "AI剪辑",
        "一键过审",
        "auto_edit",
        "douyinAPI",
        "auto_wechat:ai_edit",
        "短视频/直播留资管理表",
        "每日线索销售反馈表",
        "线索溯源表",
        "销售单车成本表",
        "all_extracted_contacts",
    ]
    missing = [item for item in required if item not in text]
    assert missing == []


def test_phase1_context_removes_obsolete_hard_gates():
    combined = _read(PRD_CONTEXT) + "\n" + _read(CLAUDE)
    obsolete = [
        "AI剪辑是独立需求",
        "不属于本项目一期交付",
        "业务自动派单发送仍禁止",
        "sent 必须为 false",
        "AI 回复 auto_send 恒为 false",
        "系统最终保持 auto_send=false",
    ]
    leaked = [item for item in obsolete if item in combined]
    assert leaked == []


def test_phase1_context_keeps_runtime_safety_boundaries():
    combined = _read(PRD_CONTEXT) + "\n" + _read(CLAUDE)
    required = [
        "违禁词",
        "人工接管",
        "限频",
        "失败回写",
        "幂等",
        "紧急停止",
        "不读取微信数据库",
        "不 DLL 注入",
        "不微信协议逆向",
        "127.0.0.1:19000",
    ]
    missing = [item for item in required if item not in combined]
    assert missing == []


def test_phase1_reuses_existing_permission_codes():
    text = _read(CAPABILITIES)
    assert 'aiEdit: "auto_wechat:ai_edit"' in text
    assert 'douyinAiCs: "auto_wechat:douyin_ai_cs"' in text
    assert 'agent: "auto_wechat:agent"' in text
    assert "auto_wechat:ai_video" not in text
    assert "auto_wechat:ad_review" not in text
