"""P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R2 聚焦测试。

覆盖：
- ReplySuggestionRequest 顶层未知字段严格拒绝（extra=forbid）；
- AgentConfig.system_prompt 完全删除（携带即 422）；
- 地址为空时固定 Prompt 不生成"未填写/未配置"占位作为客户可见示例；
- 价格/优惠/最低价/落地价/金融数字/审批/资质输出确定性自动发送阻断
  （覆盖 direct、trusted RAG、retry、post-process 后的最终资格计算 _direct_llm_auto_send_allowed）；
- 预算事实输入不误判为 AI 报价；
- 创建 Agent 错误消息（MERCHANT_ID_REQUIRED vs store_name 校验分开）。

全部确定性/纯函数检测，不调 LLM、不触网、不真实发送。
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. ReplySuggestionRequest 顶层未知字段严格拒绝
# ---------------------------------------------------------------------------

def test_reply_suggestion_request_rejects_unknown_top_level():
    from fastapi.testclient import TestClient
    from apps.xg_douyin_ai_cs.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "t", "merchant_id": "m", "account_id": 1,
            "latest_message": "hello",
            "unknown_top_level_field": "x",
        },
        headers={"X-Internal-Service-Token": "test"},
    )
    assert resp.status_code == 422  # extra=forbid 严格拒绝


# ---------------------------------------------------------------------------
# 2. AgentConfig.system_prompt 完全删除
# ---------------------------------------------------------------------------

def test_agent_config_rejects_system_prompt():
    from fastapi.testclient import TestClient
    from apps.xg_douyin_ai_cs.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "t", "merchant_id": "m", "account_id": 1,
            "latest_message": "hello",
            "agent_id": "agent-1",
            "agent_config": {
                "agent_id": "agent-1", "agent_name": "AI客服",
                "system_prompt": "引导留资", "status": "active",
            },
        },
        headers={"X-Internal-Service-Token": "test"},
    )
    assert resp.status_code == 422  # AgentConfig extra=forbid 拒绝 system_prompt


def test_agent_config_has_no_system_prompt_field():
    """AgentConfig schema 不再声明 system_prompt 字段。"""
    from apps.xg_douyin_ai_cs.schemas import AgentConfig
    assert "system_prompt" not in AgentConfig.model_fields


def test_resolve_reply_agent_output_has_no_system_prompt():
    """resolve_reply_agent 输出的 agent dict 不再含 system_prompt 键。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import resolve_reply_agent
    from apps.xg_douyin_ai_cs.schemas import ReplySuggestionRequest, AgentConfig

    request = ReplySuggestionRequest(
        tenant_id="t", merchant_id="m", account_id=1, latest_message="hi",
        agent_id="agent-1",
        agent_config=AgentConfig(agent_id="agent-1", agent_name="AI客服", status="active"),
    )
    agent, _ = resolve_reply_agent(request, 1)
    assert agent is not None
    assert "system_prompt" not in agent


def test_agent_requires_phone_lead_capture_not_depend_on_system_prompt():
    """R2：留资目标判定不再依赖 system_prompt（恒 False，模板第二节承载留资引导）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _agent_requires_phone_lead_capture
    # 含旧 system_prompt 键的 agent dict 也不应触发（键被忽略）
    agent = {
        "agent_id": "agent-phone", "agent_name": "留资智能体",
        "agent_category": "bound_agent",
        "system_prompt": "每次回复都要自然引导客户留下手机号。",
        "business_scope": "", "reply_style": "",
    }
    assert _agent_requires_phone_lead_capture(agent) is False


# ---------------------------------------------------------------------------
# 3. 地址为空时不生成占位文本
# ---------------------------------------------------------------------------

def test_prompt_address_empty_no_placeholder():
    """地址为空时固定 Prompt 不生成"未填写/未配置"占位作为客户可见示例（invariant 9）。

    第一节"地址：未配置（规则说明）"是内部商家事实（LLM 据此知道无地址，不输出占位），
    不允许的是客户可见示例（"老板，我们店在（未填写，留资承接）"）这类占位渲染。
    """
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_fixed_prompt_template
    # 地址空
    s = _build_fixed_prompt_template({})
    # 客户可见示例：地址空时用留资承接示例，不渲染"我们店在（占位）"
    assert "客户：发个定位 → 老板，你留个联系方式，我发你" in s
    assert "我们店在（" not in s
    # 不允许"老板，我们店在未填写/未配置"这类客户可见占位
    assert "我们店在未填写" not in s
    assert "我们店在未配置" not in s

    # 地址有值：如实渲染
    s2 = _build_fixed_prompt_template({"store_address": "广州市天河区XXX"})
    assert "地址：广州市天河区XXX" in s2
    assert "客户：店铺在哪 → 老板，我们店在广州市天河区XXX" in s2


# ---------------------------------------------------------------------------
# 4. 价格/金融输出确定性自动发送阻断（最终资格计算）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [
    "首付3万就可以", "月供3000元", "利率3.5%", "能批下来的", "征信不好也能做",
    "这台车30万", "优惠2万", "最低价28万", "落地价30万", "裸车价25万",
])
def test_direct_llm_auto_send_allowed_blocks_price_finance_claim(reply):
    """最终资格收敛点阻断价格/金融事实断言（覆盖 trusted RAG 路径）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _direct_llm_auto_send_allowed
    decision = {
        "manual_required": False,
        "reply_text": reply,
        "risk_flags": [],
    }
    # rag_used=True（trusted RAG）也不放行——R2 关键覆盖
    assert _direct_llm_auto_send_allowed(
        decision, rag_used=True, direct_llm_policy={}
    ) is False


@pytest.mark.parametrize("reply", [
    "老板这个不太方便在这里说，你留个联系方式我+你",
    "老板，这里不方便展开，留个联系方式我+你",
    "有的老板，你想了解混动还是纯电",
    "老板，我们店在广州市天河区XXX",
])
def test_direct_llm_auto_send_allowed_allows_compliant_reply(reply):
    """合规话术（含'分期/价格'语义但无数字/承诺）不阻断自动发送候选。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _direct_llm_auto_send_allowed
    decision = {"manual_required": False, "reply_text": reply, "risk_flags": []}
    assert _direct_llm_auto_send_allowed(
        decision, rag_used=True, direct_llm_policy={}
    ) is True


def test_trusted_rag_price_claim_blocked_not_just_manual_required():
    """trusted RAG 路径：LLM 返回价格事实但 risk_flags 为空 → 最终 auto_send 仍阻断。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _direct_llm_auto_send_allowed
    decision = {"manual_required": False, "reply_text": "这台宝马530Li落地价28万", "risk_flags": []}
    assert _direct_llm_auto_send_allowed(decision, rag_used=True, direct_llm_policy={}) is False


# ---------------------------------------------------------------------------
# 5. 预算事实不误判为价格询问（invariant 8：输入意图层）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "我预算20万", "20万左右有吗", "预算30个", "20万左右有合适的车吗",
])
def test_budget_fact_not_treated_as_price_inquiry(msg):
    """客户预算陈述不触发 OFF_PLATFORM_DETAIL_HANDOFF（价格询问）路由。

    预算保护在输入意图层（Reply Kernel _is_off_platform_request），
    与输出 claim 检测（_reply_has_price_or_finance_claim 测 AI 回复）分离。
    """
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert _is_off_platform_request(msg) is False


# ---------------------------------------------------------------------------
# 6. 创建 Agent 错误消息
# ---------------------------------------------------------------------------

def test_create_agent_store_name_error_message_accurate():
    """store_name 校验错误不再误报为'缺少可信商户上下文'。"""
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.auth.context import RequestContext
    from app.auth.dependencies import get_request_context_required
    from app.database import get_db
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.models  # noqa
    from app.database import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="user-1", username="user-1", merchant_id="merchant-1",
        merchant_ids=["merchant-1"], permission_codes=["auto_wechat:douyin_ai_cs"],
        super_admin=False,
    )
    client = TestClient(app)

    # 空白 store_name → 400，code/message 为 store_name 校验错误（非"缺少可信商户上下文"）
    resp = client.post("/agents", json={"name": "智能体", "store_name": "   "})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "store_name" in str(detail.get("code", ""))
    assert "缺少可信商户上下文" not in str(detail.get("message", ""))
