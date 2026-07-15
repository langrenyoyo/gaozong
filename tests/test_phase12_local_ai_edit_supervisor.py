"""Phase 12 Task 7 19000 AI 剪辑监管器测试（FIX2 复合任务键）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7。

覆盖：
- 单任务队列（默认并发 1）；
- 取消终止 Worker 进程树（商户隔离：跨商户不可取消）；
- 重启恢复（跳过终态与 cancel_requested，保留 manifest_path）；
- 状态查询（按商户过滤）；
- writeback 拒陈旧 attempt；
- Worker 失败隔离不影响微信路由。
替身：注入假 executor，不启动真实 Worker 子进程。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.local_agent_ai_edit_supervisor import (
    AiEditSupervisor,
    LocalAiEditJob,
    LocalAiEditStatus,
)


def _job(job_id: str = "job-1", *, merchant_id: str = "m1",
         manifest_path: str = "/tmp/manifest.json") -> LocalAiEditJob:
    return LocalAiEditJob(
        job_id=job_id, attempt_id="att-1",
        manifest_path=manifest_path, merchant_id=merchant_id,
    )


# ---------------------------------------------------------------------------
# 单任务队列（默认并发 1）
# ---------------------------------------------------------------------------


def test_supervisor_default_concurrency_one(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    assert sup.concurrency == 1


def test_supervisor_enqueues_and_completes(tmp_path):
    completed: list[str] = []

    def executor(job):
        completed.append(job.job_id)
        return {"status": "succeeded"}

    sup = AiEditSupervisor(work_root=tmp_path, executor=executor)
    sup.enqueue(_job("job-1"))
    sup.drain()
    assert "job-1" in completed
    assert sup.status(merchant_id="m1").completed_count == 1


def test_supervisor_single_task_queue_serializes(tmp_path):
    running: list[str] = []
    max_concurrent = {"v": 0}
    current = {"v": 0}

    def executor(job):
        current["v"] += 1
        running.append(job.job_id)
        max_concurrent["v"] = max(max_concurrent["v"], current["v"])
        current["v"] -= 1
        return {"status": "succeeded"}

    sup = AiEditSupervisor(work_root=tmp_path, executor=executor)
    sup.enqueue(_job("job-1"))
    sup.enqueue(_job("job-2"))
    sup.enqueue(_job("job-3"))
    sup.drain()
    assert max_concurrent["v"] == 1


# ---------------------------------------------------------------------------
# FIX2-1：取消商户隔离——跨商户不可取消
# ---------------------------------------------------------------------------


def test_supervisor_cancel_marks_cancelled(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1", merchant_id="m1"))
    assert sup.cancel(merchant_id="m1", job_id="job-1") is True
    sup.drain()
    assert sup.status(merchant_id="m1").cancelled_count >= 1


def test_supervisor_cancel_normalizes_failed_to_cancelled(tmp_path):
    """FIX3-1：任务被取消后，即使 executor 返回 failed（Worker 被终止），
    终态持久化与计数必须归一为 cancelled，不能记 failed。"""
    sup = AiEditSupervisor(
        work_root=tmp_path,
        executor=lambda j: {"status": "failed"},  # Worker 被终止后通常返回 failed
    )
    sup.enqueue(_job("job-1", merchant_id="m1"))
    assert sup.cancel(merchant_id="m1", job_id="job-1") is True
    sup.drain()
    state = sup.get_job_state(merchant_id="m1", job_id="job-1")
    assert state["status"] == "cancelled"  # 归一为 cancelled，非 failed
    assert sup.status(merchant_id="m1").cancelled_count == 1
    assert sup.status(merchant_id="m1").failed_count == 0


def test_supervisor_cancel_cross_merchant_rejected(tmp_path):
    """m2 不能取消 m1 的任务（复合键隔离）。"""
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1", merchant_id="m1"))
    # m2 尝试取消 m1 的任务 → False
    assert sup.cancel(merchant_id="m2", job_id="job-1") is False


# ---------------------------------------------------------------------------
# 重启恢复
# ---------------------------------------------------------------------------


def test_supervisor_recover_requeues_running(tmp_path):
    sup1 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup1.enqueue(_job("job-1"))
    sup1._persist_job_state("m1/job-1", status="running", attempt_id="att-1",
                            manifest_path="/m.json", merchant_id="m1", job_id="job-1")
    sup2 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    recovered = sup2.recover()
    assert recovered == 1
    sup2.drain()
    assert sup2.status(merchant_id="m1").completed_count >= 1


def test_supervisor_recover_preserves_manifest_path(tmp_path):
    sup1 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup1._persist_job_state("m1/j1", status="running", attempt_id="att-1",
                            manifest_path="/work/j1/manifest.json",
                            merchant_id="m1", job_id="j1")
    sup2 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup2.recover()
    state = sup2.get_job_state(merchant_id="m1", job_id="j1")
    assert state["manifest_path"] == "/work/j1/manifest.json"


def test_supervisor_recover_skips_cancelled(tmp_path):
    sup1 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup1.enqueue(_job("j1", merchant_id="m1"))
    sup1.enqueue(_job("j2", merchant_id="m1"))
    sup1.cancel(merchant_id="m1", job_id="j2")
    sup1._persist_job_state("m1/j1", status="running", attempt_id="a1",
                            manifest_path="/m.json", merchant_id="m1", job_id="j1")
    executed: list[str] = []
    sup2 = AiEditSupervisor(
        work_root=tmp_path,
        executor=lambda j: executed.append(j.job_id) or {"status": "succeeded"},
    )
    sup2.recover()
    sup2.drain()
    assert "j1" in executed
    assert "j2" not in executed


def test_supervisor_recover_skips_terminal(tmp_path):
    sup1 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup1._persist_job_state("m1/done", status="succeeded", attempt_id="a",
                            manifest_path="/m.json", merchant_id="m1", job_id="done")
    sup1._persist_job_state("m1/fail", status="failed", attempt_id="b",
                            manifest_path="/m2.json", merchant_id="m1", job_id="fail")
    sup2 = AiEditSupervisor(
        work_root=tmp_path,
        executor=lambda j: pytest.fail(f"不应重执终态任务 {j.job_id}"),
    )
    assert sup2.recover() == 0


# ---------------------------------------------------------------------------
# 状态查询（FIX2-9：按商户过滤）
# ---------------------------------------------------------------------------


def test_supervisor_status_filtered_by_merchant(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1", merchant_id="m1"))
    sup.enqueue(_job("job-2", merchant_id="m2"))
    sup.drain()
    # m1 只看到自己的 1 个
    s1 = sup.status(merchant_id="m1")
    assert s1.completed_count == 1
    s2 = sup.status(merchant_id="m2")
    assert s2.completed_count == 1


def test_supervisor_status_returns_type(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1"))
    sup.drain()
    assert isinstance(sup.status(merchant_id="m1"), LocalAiEditStatus)


# ---------------------------------------------------------------------------
# Worker 失败隔离
# ---------------------------------------------------------------------------


def test_supervisor_executor_failure_isolated(tmp_path):
    def failing_executor(job):
        raise RuntimeError("worker exe missing")
    sup = AiEditSupervisor(work_root=tmp_path, executor=failing_executor)
    sup.enqueue(_job("job-1"))
    sup.drain()
    assert sup.status(merchant_id="m1").failed_count >= 1


def test_supervisor_rejects_stale_attempt_writeback(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1", manifest_path="/tmp/m.json"))
    sup.drain()
    accepted = sup.writeback(
        merchant_id="m1", job_id="job-1", attempt_id="stale-att",
        result={"status": "succeeded"},
    )
    assert accepted is False


def test_supervisor_writeback_cross_merchant_rejected(tmp_path):
    """跨商户 writeback 被拒。"""
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1", merchant_id="m1"))
    accepted = sup.writeback(
        merchant_id="m2", job_id="job-1", attempt_id="att-1",
        result={"status": "succeeded"},
    )
    assert accepted is False


# ---------------------------------------------------------------------------
# FIX2-7：终态回调释放活动引用
# ---------------------------------------------------------------------------


def test_supervisor_fires_terminal_callback(tmp_path):
    fired: list[tuple] = []
    sup = AiEditSupervisor(
        work_root=tmp_path,
        executor=lambda j: {"status": "succeeded"},
        on_job_terminal=lambda job, status: fired.append((job.job_id, status)),
    )
    sup.enqueue(_job("job-1"))
    sup.drain()
    assert ("job-1", "succeeded") in fired
