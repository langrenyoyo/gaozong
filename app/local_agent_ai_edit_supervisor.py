"""Phase 12 Task 7 19000 AI 剪辑监管器。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7。

职责：
- 单任务队列（默认并发 1，配置允许大于 1）；
- 后台线程异步 drain，不阻塞 19000 HTTP 请求；
- 持有运行中 Worker 进程句柄，取消终止进程树；
- 重启恢复：跳过终态与 cancel_requested，重新入队 running/queued，保留 manifest_path；
- writeback 拒陈旧 attempt 回写；
- Worker 启动失败/缺失不影响微信路由（异常捕获记 failed）。

状态持久化到 work_root/jobs.json（含 manifest_path / merchant_id / attempt_id）。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_JOBS_FILE = "jobs.json"
_DEFAULT_CONCURRENCY = 1

# 终态：不再重执
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
# 恢复时跳过：终态 + cancel_requested（避免重跑已取消任务）
_SKIP_RECOVER_STATUSES = _TERMINAL_STATUSES + ("cancel_requested",)


@dataclass
class LocalAiEditJob:
    job_id: str
    attempt_id: str
    manifest_path: str
    merchant_id: str = ""


@dataclass
class LocalAiEditStatus:
    total_enqueued: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    running_count: int = 0
    queued_count: int = 0


Executor = Callable[[LocalAiEditJob], dict]


class AiEditSupervisor:
    """19000 AI 剪辑任务监管器（队列 + 子进程监管 + 恢复）。

    executor 负责启动 Worker 子进程并返回结果 dict；真实 executor 由
    local_agent_main 注入（启动 ai_edit_worker.exe，测试注入替身）。
    持有运行中进程句柄供取消终止进程树；drain 异步在后台线程执行，不阻塞 HTTP。
    """

    def __init__(
        self,
        *,
        work_root: Path,
        executor: Executor,
        concurrency: int | None = None,
    ):
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        self.concurrency = concurrency or int(
            os.getenv("AI_EDIT_CONCURRENCY", str(_DEFAULT_CONCURRENCY))
        )
        # ponytail: RLock 可重入——enqueue/drain 持锁时调用 _persist_job_state
        # 再取同一锁；普通 Lock 会死锁。升级路径：并发>1 需细粒度锁可拆分。
        self._lock = threading.RLock()
        self._queue: deque[LocalAiEditJob] = deque()
        self._cancelled: set[str] = set()
        self._status = LocalAiEditStatus()
        self._job_states: dict[str, dict] = self._load_jobs()
        # 运行中任务的 Worker 进程句柄（job_id -> Popen），供取消终止进程树
        self._processes: dict[str, object] = {}
        self._drain_thread: threading.Thread | None = None
        self._auto_start = False  # 显式 start() 后才自动触发后台 drain

    # ------------------------------------------------------------------
    # 持久化（保留 manifest_path / merchant_id / attempt_id）
    # ------------------------------------------------------------------

    def _jobs_file(self) -> Path:
        return self.work_root / _JOBS_FILE

    def _load_jobs(self) -> dict[str, dict]:
        path = self._jobs_file()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_jobs(self) -> None:
        path = self._jobs_file()
        fd, tmp = tempfile.mkstemp(prefix=".jobs_", suffix=".tmp", dir=str(self.work_root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._job_states, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _persist_job_state(
        self, job_id: str, *, status: str, attempt_id: str,
        manifest_path: str = "", merchant_id: str = "",
    ) -> None:
        """持久化任务状态（保留 manifest_path 供恢复使用）。"""
        with self._lock:
            # 保留既有 manifest_path/merchant_id（若本次未传）
            existing = self._job_states.get(job_id, {})
            self._job_states[job_id] = {
                "job_id": job_id,
                "status": status,
                "attempt_id": attempt_id,
                "manifest_path": manifest_path or existing.get("manifest_path", ""),
                "merchant_id": merchant_id or existing.get("merchant_id", ""),
            }
            self._save_jobs()

    # ------------------------------------------------------------------
    # 队列与执行
    # ------------------------------------------------------------------

    def enqueue(self, job: LocalAiEditJob) -> None:
        with self._lock:
            self._queue.append(job)
            self._status.total_enqueued += 1
            self._status.queued_count += 1
            self._persist_job_state(
                job.job_id, status="queued", attempt_id=job.attempt_id,
                manifest_path=job.manifest_path, merchant_id=job.merchant_id,
            )
        # 异步触发后台 drain（若已 start），不阻塞 HTTP 请求线程
        # 测试路径不 start，走显式 drain()；生产路径由 local_agent_main 启动时 start()
        if self._drain_thread is not None and self._drain_thread.is_alive():
            return
        if self._auto_start:
            self._ensure_drain_thread()

    def start(self) -> None:
        """启动后台 drain 线程（生产路径由 local_agent_main 启动时调用）。"""
        self._auto_start = True
        self._ensure_drain_thread()

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def cancel(self, job_id: str) -> bool:
        """取消任务：标记 cancel_requested + 终止运行中 Worker 进程树。

        不存在的任务或已终态任务 → 返回 False（不可取消）。
        """
        with self._lock:
            state = self._job_states.get(job_id)
            if state is None:
                return False  # 任务不存在
            if state.get("status") in _TERMINAL_STATUSES:
                return False  # 已终态，不可取消
            self._cancelled.add(job_id)
            self._persist_job_state(
                job_id, status="cancel_requested",
                attempt_id=state.get("attempt_id", ""),
                manifest_path=state.get("manifest_path", ""),
                merchant_id=state.get("merchant_id", ""),
            )
            # 终止运行中 Worker 进程树
            proc = self._processes.get(job_id)
        if proc is not None:
            try:
                from apps.ai_edit.media_tools import terminate_process_tree
                terminate_process_tree(proc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ai_edit_supervisor stage=cancel_terminate error=%s", exc)
        return True

    def _ensure_drain_thread(self) -> None:
        """确保后台 drain 线程运行（异步处理队列，不阻塞 HTTP）。"""
        with self._lock:
            if self._drain_thread is not None and self._drain_thread.is_alive():
                return
            self._drain_thread = threading.Thread(
                target=self._drain_loop, name="ai-edit-supervisor", daemon=True,
            )
            self._drain_thread.start()

    def _drain_loop(self) -> None:
        """后台循环：串行处理队列（并发 1）。"""
        while True:
            with self._lock:
                if not self._queue:
                    break
                job = self._queue.popleft()
                self._status.queued_count -= 1
                if job.job_id in self._cancelled:
                    self._status.cancelled_count += 1
                    self._persist_job_state(
                        job.job_id, status="cancelled", attempt_id=job.attempt_id,
                        manifest_path=job.manifest_path, merchant_id=job.merchant_id,
                    )
                    continue
                self._status.running_count += 1
                self._persist_job_state(
                    job.job_id, status="running", attempt_id=job.attempt_id,
                    manifest_path=job.manifest_path, merchant_id=job.merchant_id,
                )
            status = self._execute_job(job)
            with self._lock:
                self._status.running_count -= 1
                self._processes.pop(job.job_id, None)
                if status == "succeeded":
                    self._status.completed_count += 1
                elif status == "cancelled" or job.job_id in self._cancelled:
                    self._status.cancelled_count += 1
                else:
                    self._status.failed_count += 1
                self._persist_job_state(
                    job.job_id, status=status, attempt_id=job.attempt_id,
                    manifest_path=job.manifest_path, merchant_id=job.merchant_id,
                )

    def _execute_job(self, job: LocalAiEditJob) -> str:
        """执行单个任务（调用 executor，捕获异常）。"""
        try:
            result = self.executor(job)
            status = str(result.get("status", "failed")) if isinstance(result, dict) else "failed"
        except Exception as exc:  # noqa: BLE001  Worker 失败隔离，不影响微信路由
            logger.warning("ai_edit_supervisor stage=executor_error job_id=%s error=%s",
                           job.job_id, exc)
            status = "failed"
        return status

    def drain(self) -> None:
        """同步处理完队列（测试用）。生产路径走 _ensure_drain_thread 异步。"""
        self._drain_loop()

    def register_process(self, job_id: str, process: object) -> None:
        """注册运行中 Worker 进程句柄（executor 内调用，供取消终止进程树）。"""
        with self._lock:
            self._processes[job_id] = process

    def recover(self) -> int:
        """重启恢复：跳过终态与 cancel_requested，重新入队 running/queued。

        保留持久化的 manifest_path（不丢失），不重执已取消任务。
        """
        recovered = 0
        with self._lock:
            for job_id, state in list(self._job_states.items()):
                if state.get("status") in _SKIP_RECOVER_STATUSES:
                    continue  # 跳过终态与 cancel_requested
                job = LocalAiEditJob(
                    job_id=job_id,
                    attempt_id=state.get("attempt_id", ""),
                    manifest_path=state.get("manifest_path", ""),
                    merchant_id=state.get("merchant_id", ""),
                )
                self._queue.append(job)
                self._status.total_enqueued += 1
                self._status.queued_count += 1
                recovered += 1
        if recovered and self._auto_start:
            self._ensure_drain_thread()
        return recovered

    def status(self) -> LocalAiEditStatus:
        with self._lock:
            return LocalAiEditStatus(
                total_enqueued=self._status.total_enqueued,
                completed_count=self._status.completed_count,
                failed_count=self._status.failed_count,
                cancelled_count=self._status.cancelled_count,
                running_count=self._status.running_count,
                queued_count=self._status.queued_count,
            )

    def get_job_state(self, job_id: str, *, merchant_id: str) -> dict | None:
        """查询任务状态（商户隔离：merchant_id 必须匹配持久化的 merchant_id）。"""
        with self._lock:
            state = self._job_states.get(job_id)
            if state is None:
                return None
            if state.get("merchant_id") and state.get("merchant_id") != merchant_id:
                return None  # 跨商户不暴露存在性
            return dict(state)

    def writeback(self, *, job_id: str, attempt_id: str, result: dict) -> bool:
        """任务结果回写：attempt 不匹配或已终态 → 拒绝（防陈旧 attempt 回写）。"""
        with self._lock:
            state = self._job_states.get(job_id)
            if state is None:
                return False
            if state.get("status") in _TERMINAL_STATUSES:
                return False  # 已终态，拒陈旧回写
            if state.get("attempt_id") != attempt_id:
                return False  # attempt 不匹配
            status = str(result.get("status", "failed")) if isinstance(result, dict) else "failed"
            self._persist_job_state(
                job_id, status=status, attempt_id=attempt_id,
                manifest_path=state.get("manifest_path", ""),
                merchant_id=state.get("merchant_id", ""),
            )
            if status == "succeeded":
                self._status.completed_count += 1
            elif status == "cancelled":
                self._status.cancelled_count += 1
            else:
                self._status.failed_count += 1
            return True
