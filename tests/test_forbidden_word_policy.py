"""G1-DELTA 违禁词处理策略聚焦测试。

覆盖最终行为契约：
1. AI 回复违禁词命中并入 retry_combined（总模型调用 ≤2），第 2 次请求包含具体命中词；
   retry 后仍命中 → manual_required=true / auto_send=false（9100 探针子进程隔离验证）。
2. 回访话术发送给抖音客户前做只检测，命中阻断不发送（9000）。
3. 回访模板命中 → 400 FORBIDDEN_WORD_HIT + hits，不落库（9000）。

全部使用 Mock，不触网、不真实发送、不产生费用。
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.database import Base
from app.models import (
    DouyinAuthorizedAccount,
    ForbiddenWord,
    ForbiddenWordLibrary,
    ReturnVisitPrompt,
    ReturnVisitRun,
)
from app.auth.context import RequestContext

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_PROBE = pathlib.Path(__file__).parent / "helpers" / "forbidden_word_policy_probe.py"


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _network_sentinel(monkeypatch):
    """网络哨兵：未打桩的 HTTP 调用立即 raise，真实网络调用恒为 0。"""

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵触发：禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)


def _seed_forbidden_words(db) -> ForbiddenWordLibrary:
    lib = ForbiddenWordLibrary(
        library_key="used_car_sales_base",
        name="二手车销售基础违禁词",
        scope="global",
        enabled=True,
        sort_order=1,
    )
    db.add(lib)
    db.flush()
    db.add(
        ForbiddenWord(
            library_id=lib.id,
            word="现车",
            safe_word="可到店详询",
            enabled=True,
            hit_count=0,
        )
    )
    db.commit()
    return lib


def _seed_authorized_account(db) -> None:
    db.add(
        DouyinAuthorizedAccount(
            main_account_id=1,
            open_id="account-open-1",
            bind_status=1,
            merchant_id="merchant-1",
        )
    )
    db.commit()


def _run_probe(scenario: str) -> dict:
    """子进程调用探针，返回 JSON。父进程不 import 9100 App。"""
    env = os.environ.copy()
    for var in ("RAG_DATABASE_URL", "RAG_VECTOR_BACKEND", "MILVUS_HOST", "MILVUS_PORT",
                "XG_DOUYIN_AI_CS_DB_PATH", "XG_DOUYIN_AI_CS_SERVICE_TOKEN",
                "DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"):
        env.pop(var, None)
    proc = subprocess.run(
        [sys.executable, str(_PROBE), scenario],
        capture_output=True, text=True, env=env, check=False,
    )
    out_lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip().startswith("{")]
    if not out_lines:
        return {"ok": False, "error_code": f"probe_no_json stderr={proc.stderr[-300:]}"}
    return json.loads(out_lines[-1])


# ---------------------------------------------------------------------------
# 9100：AI 回复违禁词并入 retry_combined（验收 1/2/3）
# ---------------------------------------------------------------------------

def test_ai_reply_forbidden_first_hit_triggers_retry_then_ok():
    """首调命中违禁词 → 触发 retry_combined（第 2 次注入命中词）→ 第 2 次合规 → 不阻断。"""
    result = _run_probe("forbidden_first_hit_retry_ok")
    assert result.get("ok") is True, result
    assert result["llm_call_count"] == 2          # 验收 1：总模型调用 ≤2
    assert result["retry_payload_includes_hit_word"] is True   # 验收 2：第 2 次请求含命中词
    assert result["forbidden_word_hit"] is False
    assert result["manual_required"] is False


def test_ai_reply_forbidden_retry_still_hit_blocks():
    """首调命中 → retry 仍命中 → manual_required=true / auto_send=false（验收 3）。"""
    result = _run_probe("forbidden_first_hit_retry_still_hit")
    assert result.get("ok") is True, result
    assert result["llm_call_count"] == 2          # 验收 1：总模型调用 ≤2（不第三次调用）
    assert result["retry_payload_includes_hit_word"] is True   # 验收 2
    assert result["forbidden_word_hit"] is True
    assert result["manual_required"] is True      # 验收 3
    assert result["auto_send"] is False           # 验收 3


def test_ai_reply_no_forbidden_no_retry():
    """首调未命中违禁词 → 不触发 retry（总调用 =1）。"""
    result = _run_probe("forbidden_first_hit_none")
    assert result.get("ok") is True, result
    assert result["llm_call_count"] == 1
    assert result["forbidden_word_hit"] is False


def test_ai_reply_contact_conflict_rewrite_blocked_by_final_gate():
    """B-1 确定性测试：门禁必须位于 _check_valid_contact_conflict 改写之后。

    首调 reply 含冲突短语"号码不完整"（不含违禁词）→ 不触发 retry → 通过门禁位置 →
    _check_valid_contact_conflict 改写为固定模板"收到老板，我这边联系您。"（含"联系"）→
    最终门禁必须捕获模板内违禁词 → 阻断转人工。
    """
    result = _run_probe("forbidden_contact_conflict_rewrite_blocked")
    assert result.get("ok") is True, result
    assert result["llm_call_count"] == 1          # 首调未命中违禁词，不触发 retry
    assert result["forbidden_word_hit"] is True   # 门禁在改写后捕获模板内"联系"
    assert result["manual_required"] is True
    assert result["auto_send"] is False


# ---------------------------------------------------------------------------
# 9000：回访话术发送前只检测，命中阻断（验收 7）
# ---------------------------------------------------------------------------

def _make_run(db) -> ReturnVisitRun:
    run = ReturnVisitRun(
        merchant_id="merchant-1",
        send_status="send_authorized",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_return_visit_send_blocked_on_forbidden_word():
    """发送给抖音客户的回访话术命中违禁词 → 阻断不发送（status=blocked）。"""
    db = TestSession()
    _seed_forbidden_words(db)
    _seed_authorized_account(db)
    run = _make_run(db)
    db.close()

    from app.services.return_visit_run_service import _send_and_classify
    from unittest.mock import patch

    send_context = {
        "conversation_id": "conv-id-1", "msg_id": "msg-1",
        "customer_open_id": "customer-open-1", "account_open_id": "account-open-1",
        "conversation_short_id": "conv-1", "server_message_id": "server-msg-1",
        "scene": "im_receive_msg", "message_create_time": None,
    }
    db2 = TestSession()
    with patch(
        "app.services.return_visit_run_service._send_private_message_with_context"
    ) as send_mock:
        outcome = _send_and_classify(
            db2, run_id=run.id, run=run,
            content="我们现车很多，方便到店看看",
            send_context=send_context,
        )
        db2.close()

    assert outcome["status"] == "blocked"
    assert outcome["failure_stage"] == "forbidden_word_hit"
    # 命中阻断时不得调用底层发送
    send_mock.assert_not_called()


def test_return_visit_send_clean_content_sends():
    """合规回访话术正常发送（不误伤）。"""
    db = TestSession()
    _seed_forbidden_words(db)
    _seed_authorized_account(db)
    run = _make_run(db)
    db.close()

    from app.services.return_visit_run_service import _send_and_classify
    from unittest.mock import patch

    send_context = {
        "conversation_id": "conv-id-1", "msg_id": "msg-1",
        "customer_open_id": "customer-open-1", "account_open_id": "account-open-1",
        "conversation_short_id": "conv-1", "server_message_id": "server-msg-1",
        "scene": "im_receive_msg", "message_create_time": None,
    }
    db2 = TestSession()
    with patch(
        "app.services.return_visit_run_service._send_private_message_with_context",
        return_value={"upstream_msg_id": "upstream-msg-9"},
    ) as send_mock:
        outcome = _send_and_classify(
            db2, run_id=run.id, run=run,
            content="老板，方便到店看看车吗？",
            send_context=send_context,
        )
        db2.close()

    assert outcome["status"] == "sent"
    assert outcome["send_id"] == "upstream-msg-9"
    send_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 9000：回访模板命中 → 400 FORBIDDEN_WORD_HIT，不落库（验收 8）
# ---------------------------------------------------------------------------

def _admin_context() -> RequestContext:
    return RequestContext(
        user_id="admin-1",
        username="admin-1",
        display_name="管理员",
        merchant_id="merchant-1",
        merchant_ids=["merchant-1"],
        permission_codes=["auto_wechat:admin:return_visit_prompts"],
        super_admin=False,
    )


def test_return_visit_prompt_create_rejects_forbidden_word():
    """回访模板新增命中违禁词 → 400 FORBIDDEN_WORD_HIT + hits，不落库。"""
    db = TestSession()
    _seed_forbidden_words(db)
    db.close()

    from app.routers.admin_return_visits import create_prompt
    from app.schemas import ReturnVisitPromptCreateRequest
    from fastapi import HTTPException

    payload = ReturnVisitPromptCreateRequest(
        name="测试场景",
        scene_description="测试描述",
        template_text="我们现车很多，欢迎到店",
        fallback_message="稍后联系您",
        confidence_threshold=0.6,
        reason="测试创建",
    )
    db2 = TestSession()
    try:
        with pytest.raises(HTTPException) as excinfo:
            create_prompt(payload, db=db2, context=_admin_context())
        assert excinfo.value.status_code == 400
        detail = excinfo.value.detail
        assert detail["code"] == "FORBIDDEN_WORD_HIT"
        assert any(h["word"] == "现车" for h in detail["hits"])
    finally:
        db2.rollback()
        db2.close()

    # 不落库
    db3 = TestSession()
    assert db3.query(ReturnVisitPrompt).count() == 0
    db3.close()


def test_return_visit_prompt_create_clean_content_saves():
    """合规回访模板正常保存（不误伤）。"""
    db = TestSession()
    _seed_forbidden_words(db)
    db.close()

    from app.routers.admin_return_visits import create_prompt
    from app.schemas import ReturnVisitPromptCreateRequest

    payload = ReturnVisitPromptCreateRequest(
        name="正常场景",
        scene_description="正常描述",
        template_text="老板，方便到店看看车吗？",
        fallback_message="稍后联系您",
        confidence_threshold=0.6,
        reason="测试创建",
    )
    db2 = TestSession()
    try:
        prompt = create_prompt(payload, db=db2, context=_admin_context())
        assert prompt is not None
        db2.rollback()  # 不污染后续
    finally:
        db2.close()
