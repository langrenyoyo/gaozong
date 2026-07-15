"""Phase 12 Task 10 最终合同（检查点 C 自动化证据）。

执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 10 Step 1/检查点 C。
冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §2-15。

验证设计各节有对应实现与自动化证据（静态/集成断言），不重复单元测试细节：
- §5：19000↔9000 通信（agent-create 下发令牌 + on_job_terminal 回写）。
- §9：Worker 不直接访问 9100（plan 为注入 deps）；9100 plan_ai_edit 在独立服务。
- §10：9000 商户公共 Out 不返回执行令牌；agent-create 内部下发令牌给可信 19000。
- §11：9000/19000 路由清单存在。
- §15.2：pipeline 媒体强门（原素材哈希不变 + verify 音频/时长/分辨率）。
"""

from __future__ import annotations

import inspect


def test_section5_19000_communicates_with_9000():
    """§5：19000 与 9000 通信并转发安全进度——agent-create 下发 + on_job_terminal 回写。"""
    from app.routers import ai_edit as router_mod

    # 9000 下发令牌路由存在
    assert hasattr(router_mod, "agent_create_job"), "9000 缺 agent_create_job（§5 下发通道）"

    from app.local_agent_ai_edit_routes import create_ai_edit_router, Nine000ControlClient

    # 19000 create_ai_edit_router 接受 nine000_client（下发/回写通道）
    sig = inspect.signature(create_ai_edit_router)
    assert "nine000_client" in sig.parameters, "19000 router 缺 nine000_client 注入（§5）"
    # Nine000ControlClient 协议含下发 + 回写
    assert hasattr(Nine000ControlClient, "agent_create_job")
    assert hasattr(Nine000ControlClient, "update_job_status")


def test_section5_on_job_terminal_writebacks():
    """§5：local_agent_main _on_job_terminal 含 9000 状态回写。"""
    import app.local_agent_main as lam

    src = inspect.getsource(lam)
    # on_job_terminal 回调存在且调用 update_job_status
    assert "_on_job_terminal" in src, "缺 _on_job_terminal"
    assert "update_job_status" in src, "_on_job_terminal 未回写 9000 status（§5）"


def test_section9_worker_does_not_directly_access_9100():
    """§9：Worker 不直接访问 9100——plan 为注入 deps，不硬调 9100/模型令牌。"""
    from apps.ai_edit import pipeline

    src = inspect.getsource(pipeline)
    # pipeline.plan 来自 deps（注入），不直接 import 9100 服务
    assert "deps.plan" in src or "deps.plan(" in src, "pipeline plan 应为注入 deps（§9）"
    # 不直接 import 9100 planner service 或 LLM client
    assert "ai_edit_planner_service" not in src, "Worker 不应直接 import 9100 planner（§9）"
    assert "OpenAICompatibleClient" not in src, "Worker 不应直接 import LLM client（§9）"


def test_section9_plan_lives_in_9100():
    """§9：9100 plan_ai_edit 在独立服务，注入替身 LLM。"""
    from apps.xg_douyin_ai_cs.services.ai_edit_planner_service import plan_ai_edit

    sig = inspect.signature(plan_ai_edit)
    assert "llm_client" in sig.parameters, "plan_ai_edit 应可注入 LLM 替身（§9）"


def test_section10_public_out_no_token():
    """§10：9000 商户 create_job 公共 Out 不返回执行令牌；agent-create 内部下发。"""
    from app.services import ai_edit_service as svc

    # to_job_out 字段不含 execution_token_hash
    fields = svc.AiEditJobOut.model_fields  # type: ignore[attr-defined]
    assert "execution_token_hash" not in fields, "公共 AiEditJobOut 不得含执行令牌（§10）"
    assert "merchant_id" not in fields, "公共 Out 不得含 merchant_id（§10）"
    assert "storage_key" not in fields, "公共 Out 不得含 storage_key（§10）"

    from app.routers import ai_edit as router_mod

    # agent_create_job 路由源码：响应含 execution_token_hash（仅 Local Agent 内部下发）
    src = inspect.getsource(router_mod.agent_create_job)
    assert "execution_token_hash" in src, "agent-create 应下发执行令牌给 19000（§5/§10）"


def test_section11_route_inventory():
    """§11：9000/19000 路由清单存在。"""
    from app.routers.ai_edit import router as r9000

    paths = {route.path for route in r9000.routes}
    for p in ["/ai-edit/templates", "/ai-edit/materials", "/ai-edit/jobs",
              "/ai-edit/jobs/agent-create", "/ai-edit/jobs/{job_id}",
              "/ai-edit/jobs/{job_id}/cancel", "/ai-edit/jobs/{job_id}/retry",
              "/ai-edit/jobs/{job_id}/status"]:
        assert p in paths, f"9000 缺路由 {p}（§11）"


def test_section15_2_media_strong_gate():
    """§15.2：pipeline 媒体强门——原素材哈希校验 + verify 音频/时长/分辨率。"""
    from apps.ai_edit import pipeline

    src = inspect.getsource(pipeline)
    assert "SOURCE_HASH_DRIFT" in src, "pipeline 应校验原素材哈希不变（§15.2）"
    assert "AUDIO_MISSING" in src, "verify 应检查音频存在（§15.2）"
    assert "INVALID_DURATION" in src, "verify 应检查时长（§15.2）"
    assert "RESOLUTION_MISMATCH" in src, "verify 应检查分辨率（§15.2）"


def test_section15_2_stabilizer_preserves_audio():
    """§15.2/§7.3：增稳保留音频（不 -an），输出衍生文件。"""
    from apps.ai_edit import stabilizer

    src = inspect.getsource(stabilizer)
    assert '"-an"' not in src and "'-an'" not in src, "增稳不得静默丢音轨 -an（§7.3）"
