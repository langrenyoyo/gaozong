from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
PROJECT_CONTEXT = ROOT / "docs/ai/05_PROJECT_CONTEXT.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _entry_contexts() -> str:
    return _read(AGENTS) + "\n" + _read(PROJECT_CONTEXT)


def _obsolete_phrases() -> list[str]:
    return [
        "业务自动派单" + "发送仍禁止",
        "sent " + "必须为 false",
        "AI 回复 auto_send " + "恒为 false",
        "reply_decision_service 全路径 " + "auto_send=False",
    ]


def test_entry_contexts_do_not_keep_obsolete_send_hard_gates():
    combined = _entry_contexts()
    leaked = [phrase for phrase in _obsolete_phrases() if phrase in combined]
    assert leaked == []


def test_entry_contexts_keep_runtime_safety_boundaries():
    combined = _entry_contexts()
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


def test_entry_contexts_include_phase1_confirmed_scope():
    combined = _entry_contexts()
    required = [
        "AI剪辑",
        "一键过审",
        "auto_edit",
        "douyinAPI",
        "auto_wechat:ai_edit",
        "all_extracted_contacts",
        "短视频/直播留资管理表",
        "每日线索销售反馈表",
        "线索溯源表",
        "销售单车成本表",
    ]
    missing = [item for item in required if item not in combined]
    assert missing == []
