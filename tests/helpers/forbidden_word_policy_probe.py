"""G1-DELTA 违禁词处理策略探针（子进程隔离，供 test_forbidden_word_policy.py 调用）。

验证 9100 侧违禁词行为：
- 首调命中违禁词 → 并入 retry_combined（最多 1 次，总模型调用 ≤2）；
- 第 2 次请求注入具体命中词；
- retry 后仍命中 → manual_required=true / auto_send=false / risk_flags 含 forbidden_word_hit；
- 未命中不触发 retry（总调用 =1）。

复用 p0_2_contact_trust_probe 的隔离模式：子进程受控 env + TestClient + mock chat。
"""

import json
import os
import pathlib
import sys
import tempfile

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _setup_isolated_env(db_path: str) -> None:
    """子进程受控环境：覆盖 .env.lan.local 的 setdefault，避免仓库 DB / Milvus 污染。"""
    for var in ("RAG_DATABASE_URL", "RAG_VECTOR_BACKEND", "MILVUS_HOST", "MILVUS_PORT",
                "MILVUS_COLLECTION", "MILVUS_DIMENSION", "MILVUS_URI"):
        os.environ.pop(var, None)
    os.environ["XG_DOUYIN_AI_CS_DB_PATH"] = db_path
    os.environ["XG_DOUYIN_AI_CS_SERVICE_TOKEN"] = "forbidden_policy_test_token"
    os.environ["RAG_VECTOR_BACKEND"] = "sqlite"  # 不连 Milvus
    os.environ["XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED"] = "false"
    os.environ["DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED"] = ""
    os.environ["DOUYIN_REPLY_KERNEL_SHADOW"] = ""
    os.environ["DOUYIN_CONTACT_REQUEST_POLICY_ENABLED"] = ""
    os.environ["XG_DOUYIN_AI_LLM_API_KEY"] = "test-key"


def _mock_reply(reply_text, intent="general_inquiry", confidence=0.85):
    return {
        "reply_text": json.dumps(
            {
                "reply_text": reply_text, "intent": intent, "lead_level": "medium",
                "tags": [], "manual_required": False, "manual_required_reason": "",
                "risk_flags": [], "confidence": confidence, "auto_send": False,
            },
            ensure_ascii=False,
        ),
        "model": "mock-chat", "elapsed_ms": 1,
    }


_AGENT_CONFIG = {"agent_id": "agent-1", "agent_name": "AI客服", "system_prompt": "", "status": "active"}


def _run_forbidden_app_scenario(scenario: str) -> dict:
    from fastapi.testclient import TestClient
    from apps.xg_douyin_ai_cs.main import create_app
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient

    scenarios = {
        # 首调命中违禁词 → retry 合规 → 不阻断
        "forbidden_first_hit_retry_ok": {
            "reply_first": "我们现车很多，您方便到店看车吗？",
            "reply_retry": "老板，建议您到店详聊，我帮您核实车源，您方便留个联系方式吗？",
            "forbidden_words": ["现车"],
            "expect_llm_calls": 2,
            "expect_manual_required": False,
            "expect_auto_send_false": False,
            "expect_forbidden_hit_flag": False,
        },
        # 首调命中 → retry 仍命中 → 阻断转人工
        "forbidden_first_hit_retry_still_hit": {
            "reply_first": "我们现车很多，您方便到店看车吗？",
            "reply_retry": "现车的话建议您到店详聊。",
            "forbidden_words": ["现车"],
            "expect_llm_calls": 2,
            "expect_manual_required": True,
            "expect_auto_send_false": True,
            "expect_forbidden_hit_flag": True,
        },
        # 首调未命中 → 不触发 retry（总调用 =1）
        "forbidden_first_hit_none": {
            "reply_first": "老板，建议您到店了解，我帮您核实车源。",
            "forbidden_words": ["现车"],
            "expect_llm_calls": 1,
            "expect_manual_required": False,
            "expect_auto_send_false": False,
            "expect_forbidden_hit_flag": False,
        },
        # B-1 确定性测试：首调不含违禁词 → 通过门禁位置 → _check_valid_contact_conflict 改写为
        # 固定模板"收到老板，我这边联系您。"（含"联系"）→ 门禁（位于改写之后）必须捕获 → 阻断。
        "forbidden_contact_conflict_rewrite_blocked": {
            "reply_first": "好的，号码不完整，请重新发一下。",
            "forbidden_words": ["联系"],
            "expect_llm_calls": 1,
            "expect_manual_required": True,
            "expect_auto_send_false": True,
            "expect_forbidden_hit_flag": True,
        },
    }
    cfg = scenarios.get(scenario)
    if cfg is None:
        return {"ok": False, "scenario": scenario, "error_code": "unknown_scenario"}

    td = tempfile.mkdtemp(prefix="forbidden_policy_probe_")
    db_path = os.path.join(td, "probe.db")
    _setup_isolated_env(db_path)

    client = TestClient(create_app())

    call_count = {"n": 0}
    captured_retry_text = {"value": None}

    def fake_chat(self, messages):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            # 捕获第二次请求的 user 内容（应包含命中词注入）
            for m in messages:
                if m.get("role") == "user":
                    captured_retry_text["value"] = m.get("content", "")
            return _mock_reply(cfg["reply_retry"])
        return _mock_reply(cfg["reply_first"])

    from unittest.mock import patch
    with patch.object(OpenAICompatibleClient, "chat", fake_chat):
        payload = {
            "tenant_id": "tenant-1", "merchant_id": "merchant-1", "account_id": "acc-1",
            "agent_id": _AGENT_CONFIG["agent_id"], "agent_config": _AGENT_CONFIG,
            "latest_message": "有现车吗？",
            "forbidden_words": cfg["forbidden_words"],
        }
        headers = {"X-Internal-Service-Token": "forbidden_policy_test_token"}
        response = client.post("/douyin/conversations/1/reply-suggestion", json=payload, headers=headers)

    if response.status_code != 200:
        return {"ok": False, "scenario": scenario, "error_code": f"http_{response.status_code}"}

    data = response.json()
    risk_flags = data.get("risk_flags", [])
    return {
        "ok": True,
        "scenario": scenario,
        "llm_call_count": data.get("llm_call_count"),
        "manual_required": bool(data.get("manual_required")),
        "auto_send": bool(data.get("auto_send")),
        "forbidden_word_hit": "forbidden_word_hit" in risk_flags,
        "retry_payload_includes_hit_word": (
            "现车" in (captured_retry_text["value"] or "")
            if captured_retry_text["value"] is not None else False
        ),
        "reply_text": data.get("reply_text", ""),
    }


def main() -> int:
    scenario = sys.argv[1]
    result = _run_forbidden_app_scenario(scenario)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
