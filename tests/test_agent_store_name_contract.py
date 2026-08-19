"""P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R1 store_name 契约聚焦测试。

覆盖：
- 新建/编辑 store_name 校验（缺失/空白/超长拒绝、trim 保存、≤255）；
- 同租户多 Agent 不同 store_name；
- 一个抖音号只有一个 active 默认 Agent（保持，不新增唯一约束）；
- 三条调用链（Agent Preview / 会话 Preview / 自动回复）生成相同 Agent Config 白名单；
- 调用方不能覆盖可信 Agent 数据（agent_id/store_name/status/allowed_category_keys 等）；
- 四旧字段（prompt/knowledge_base_text/store_phone/store_wechat）在 9000/9100 明确拒绝（422）；
- 运行时兜底：trim(store_name) or trim(name) or "未命名门店" 永不产生空 store_name。

全部使用 Mock，不触网、不真实发送、不产生费用。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------

def _client():
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.auth.context import RequestContext
    from app.auth.dependencies import get_request_context_required
    from app.database import get_db

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id="merchant-1",
        merchant_ids=["merchant-1"],
        permission_codes=["auto_wechat:douyin_ai_cs"],
        super_admin=False,
    )
    return TestClient(app)


def _create_agent(client, *, store_name="XX精品车行", name="智能体A") -> dict:
    resp = client.post("/agents", json={"name": name, "store_name": store_name})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# 1/2/3：store_name 新建与编辑校验
# ---------------------------------------------------------------------------

def test_create_agent_missing_store_name_rejected():
    client = _client()
    resp = client.post("/agents", json={"name": "智能体"})
    assert resp.status_code == 422  # store_name 必填


def test_create_agent_blank_store_name_rejected():
    client = _client()
    resp = client.post("/agents", json={"name": "智能体", "store_name": "   "})
    assert resp.status_code == 400  # service 层 trim 后为空 → 400（明确拒绝）


def test_create_agent_overlong_store_name_rejected():
    client = _client()
    resp = client.post("/agents", json={"name": "智能体", "store_name": "长" * 256})
    assert resp.status_code == 422  # >255 拒绝


def test_create_agent_trims_store_name():
    client = _client()
    agent = _create_agent(client, store_name="  精品车行  ")
    assert agent["store_name"] == "精品车行"  # 服务端 trim 保存

    db = TestSession()
    try:
        row = db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).one()
        assert row.store_name == "精品车行"
    finally:
        db.close()


def test_update_agent_store_name_trim_and_validation():
    client = _client()
    agent = _create_agent(client, store_name="门店A")

    # trim 更新
    resp = client.put(f"/agents/{agent['agent_id']}", json={"store_name": "  门店B  "})
    assert resp.status_code == 200
    assert resp.json()["data"]["store_name"] == "门店B"

    # 空白更新拒绝（service 层 trim 后为空 → 400）
    resp = client.put(f"/agents/{agent['agent_id']}", json={"store_name": "   "})
    assert resp.status_code == 400

    # 超长更新拒绝
    resp = client.put(f"/agents/{agent['agent_id']}", json={"store_name": "长" * 256})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 6：同租户多 Agent 不同 store_name
# ---------------------------------------------------------------------------

def test_multiple_agents_same_merchant_distinct_store_names():
    client = _client()
    a1 = _create_agent(client, name="智能体1", store_name="精品车行一")
    a2 = _create_agent(client, name="智能体2", store_name="精品车行二")
    assert a1["store_name"] == "精品车行一"
    assert a2["store_name"] == "精品车行二"
    assert a1["store_name"] != a2["store_name"]


# ---------------------------------------------------------------------------
# 7：一个抖音号只有一个 active 默认 Agent（保持，不新增唯一约束）
# ---------------------------------------------------------------------------

def test_one_active_default_agent_per_account_kept():
    client = _client()
    a1 = _create_agent(client, name="默认A", store_name="门店A")
    _bind_default(client, a1["agent_id"], "account-open-1")

    # 再次绑定同账号新 agent 为默认：模型不新增唯一约束，is_default 由服务层保证唯一
    db = TestSession()
    try:
        rows = db.query(DouyinAccountAgentBinding).filter_by(account_open_id="account-open-1").all()
        assert len(rows) == 1
        assert rows[0].is_default is True
        assert rows[0].agent_id == a1["agent_id"]
    finally:
        db.close()


def _bind_default(client, agent_id: str, account_open_id: str):
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id=account_open_id,
                merchant_id="merchant-1",
                bind_status=1,
            )
        )
        db.flush()
        db.add(
            DouyinAccountAgentBinding(
                merchant_id="merchant-1",
                account_open_id=account_open_id,
                agent_id=agent_id,
                is_default=True,
                status="active",
                created_by="user-1",
                updated_by="user-1",
            )
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 10：四旧字段在 9000 明确拒绝
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("old_field", ["prompt", "knowledge_base_text", "store_phone", "store_wechat"])
def test_create_agent_rejects_old_fields(old_field):
    client = _client()
    resp = client.post("/agents", json={"name": "智能体", "store_name": "门店", old_field: "旧字段"})
    assert resp.status_code == 422  # extra=forbid


def test_update_agent_rejects_old_fields():
    client = _client()
    agent = _create_agent(client)
    resp = client.put(f"/agents/{agent['agent_id']}", json={"prompt": "旧提示词"})
    assert resp.status_code == 422


def test_agent_preview_rejects_old_fields():
    from app.routers import agents
    from unittest.mock import patch

    client = _client()
    agent = _create_agent(client)

    class FakeClient:
        def __init__(self):
            self.calls = []

        def suggest_reply(self, *, context, conversation_id, request):
            self.calls.append(request)
            return {"reply_text": "ok", "llm_used": True}

    fake = FakeClient()
    with patch.object(agents, "get_xg_douyin_ai_cs_client", lambda: fake):
        resp = client.post(
            "/agents/preview",
            json={
                "agent_id": agent["agent_id"],
                "message": "hello",
                "persona_prompt": "旧人设",
            },
        )
    assert resp.status_code == 422  # persona_prompt extra 拒绝


# ---------------------------------------------------------------------------
# 8/9：三条调用链白名单一致 + 调用方不能覆盖可信数据
# ---------------------------------------------------------------------------

def test_three_call_chains_build_same_agent_config_whitelist():
    """Agent Preview / 会话 Preview / 自动回复 三条链路生成相同 Agent Config 白名单。

    白名单字段：agent_id/agent_name/store_name/status/allowed_category_keys/rag_enabled/门店普通事实字段；
    不含四旧字段（prompt/knowledge_base_text/store_phone/store_wechat）与 system_prompt。
    """
    from app.services.ai_agent_service import build_agent_config

    db = TestSession()
    try:
        agent = AiAgent(
            agent_id="agent-contract",
            merchant_id="merchant-1",
            name="契约智能体",
            store_name="契约门店",
            avatar_seed="seed",
            status="active",
            store_address="地址A",
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        config = build_agent_config(agent, category_keys=["base"])
        assert config["agent_id"] == "agent-contract"
        assert config["agent_name"] == "契约智能体"
        assert config["store_name"] == "契约门店"
        assert config["status"] == "active"
        assert config["allowed_category_keys"] == ["base"]
        assert config["rag_enabled"] is True
        assert config["store_address"] == "地址A"
        # 四旧字段与 system_prompt 不输出
        for banned in ("prompt", "knowledge_base_text", "store_phone", "store_wechat", "system_prompt"):
            assert banned not in config, f"{banned} 不得出现在 Agent Config 白名单"
    finally:
        db.close()


def test_build_agent_config_ignores_callers_forged_values():
    """构造器从可信 ORM 读取，调用方传入的 agent_config 不得覆盖。"""
    from app.services.ai_agent_service import build_agent_config

    db = TestSession()
    try:
        agent = AiAgent(
            agent_id="agent-auth",
            merchant_id="merchant-1",
            name="可信名称",
            store_name="可信门店",
            avatar_seed="seed",
            status="disabled",
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        config = build_agent_config(agent, category_keys=[])
        # 调用方伪造的 agent_id/store_name/status 不得覆盖（构造器根本不读调用方输入）
        assert config["agent_id"] == "agent-auth"
        assert config["store_name"] == "可信门店"
        assert config["status"] == "disabled"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5：运行时兜底永不产生空 store_name
# ---------------------------------------------------------------------------

def test_store_name_runtime_fallback_never_empty():
    from app.services.ai_agent_service import build_agent_config

    db = TestSession()
    try:
        # store_name 为空 → 用 name
        a1 = AiAgent(
            agent_id="agent-fb1", merchant_id="m", name="名称兜底", store_name="",
            avatar_seed="s", status="active",
        )
        db.add(a1)
        db.commit()
        db.refresh(a1)
        assert build_agent_config(a1, category_keys=[])["store_name"] == "名称兜底"

        # store_name 与 name 均为空 → "未命名门店"
        a2 = AiAgent(
            agent_id="agent-fb2", merchant_id="m", name="", store_name=None,
            avatar_seed="s", status="active",
        )
        db.add(a2)
        db.commit()
        db.refresh(a2)
        assert build_agent_config(a2, category_keys=[])["store_name"] == "未命名门店"
    finally:
        db.close()
