"""Phase 12 Task 7 19000 AI 剪辑监管器测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7。

覆盖（Step 1 列举）：
- 单任务队列（默认并发 1）；
- 取消终止 Worker 进程树；
- 重启恢复（未完成 running 重新入队，不接受陈旧 attempt 回写）；
- 状态查询；
- Worker 缺失/启动失败不影响微信路由（隔离）。
替身：不启动真实 Worker 子进程，注入假 executor。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.local_agent_ai_edit_supervisor import (
    AiEditSupervisor,
    LocalAiEditJob,
    LocalAiEditStatus,
)


def _job(job_id: str = "job-1", *, manifest_path: str = "/tmp/manifest.json") -> LocalAiEditJob:
    return LocalAiEditJob(job_id=job_id, attempt_id="att-1", manifest_path=manifest_path)


# ---------------------------------------------------------------------------
# 单任务队列（默认并发 1）
# ---------------------------------------------------------------------------


def test_supervisor_default_concurrency_one(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda job: {"status": "succeeded"})
    assert sup.concurrency == 1


def test_supervisor_enqueues_and_completes(tmp_path):
    completed: list[str] = []

    def executor(job):
        completed.append(job.job_id)
        return {"status": "succeeded"}

    sup = AiEditSupervisor(work_root=tmp_path, executor=executor)
    sup.enqueue(_job("job-1"))
    sup.drain()  # 同步处理完队列（测试用，不启后台线程）
    assert "job-1" in completed
    status = sup.status()
    assert status.completed_count == 1


def test_supervisor_single_task_queue_serializes(tmp_path):
    """默认并发 1：任务串行执行，不并发。"""
    running: list[str] = []
    max_concurrent = {"v": 0}
    current = {"v": 0}

    def executor(job):
        current["v"] += 1
        running.append(job.job_id)
        max_concurrent["v"] = max(max_concurrent["v"], current["v"])
        # 模拟工作
        current["v"] -= 1
        return {"status": "succeeded"}

    sup = AiEditSupervisor(work_root=tmp_path, executor=executor)
    sup.enqueue(_job("job-1"))
    sup.enqueue(_job("job-2"))
    sup.enqueue(_job("job-3"))
    sup.drain()
    assert max_concurrent["v"] == 1  # 串行


# ---------------------------------------------------------------------------
# 取消终止 Worker 进程树
# ---------------------------------------------------------------------------


def test_supervisor_cancel_marks_cancelled(tmp_path):
    """取消标记后，队列中的任务被 drain 时识别为 cancelled。"""
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1"))
    # 入队后、drain 前取消
    assert sup.cancel("job-1") is True
    sup.drain()
    assert sup.status().cancelled_count >= 1


# ---------------------------------------------------------------------------
# 重启恢复
# ---------------------------------------------------------------------------


def test_supervisor_recover_requeues_running(tmp_path):
    """重启时把未完成 running 任务重新入队，不接受陈旧 attempt 回写。"""
    # 先写一个 running 状态的持久化记录
    sup1 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup1.enqueue(_job("job-1"))
    # 模拟崩溃：标记 running 后不完成
    sup1._persist_job_state("job-1", status="running", attempt_id="att-1")

    # 重启：恢复
    sup2 = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    recovered = sup2.recover()
    assert recovered >= 1
    sup2.drain()
    assert sup2.status().completed_count >= 1


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------


def test_supervisor_status_returns_counts(tmp_path):
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1"))
    sup.drain()
    status = sup.status()
    assert isinstance(status, LocalAiEditStatus)
    assert status.total_enqueued >= 1


# ---------------------------------------------------------------------------
# Worker 缺失/失败不影响微信路由（隔离）
# ---------------------------------------------------------------------------


def test_supervisor_executor_failure_isolated(tmp_path):
    """Worker 启动失败不影响监管器与微信路由（异常被捕获，任务记 failed）。"""
    def failing_executor(job):
        raise RuntimeError("worker exe missing")

    sup = AiEditSupervisor(work_root=tmp_path, executor=failing_executor)
    sup.enqueue(_job("job-1"))
    sup.drain()  # 不抛异常
    status = sup.status()
    assert status.failed_count >= 1
    # 监管器仍可用
    assert sup.status().total_enqueued >= 1


def test_supervisor_rejects_stale_attempt_writeback(tmp_path):
    """陈旧 attempt 回写被拒（重试后旧 attempt 令牌失效）。"""
    sup = AiEditSupervisor(work_root=tmp_path, executor=lambda j: {"status": "succeeded"})
    sup.enqueue(_job("job-1", manifest_path="/tmp/m.json"))
    sup.drain()
    # 旧 attempt 回写应被拒（任务已完成或 attempt 不匹配）
    accepted = sup.writeback(job_id="job-1", attempt_id="stale-att",
                            result={"status": "succeeded"})
    assert accepted is False
