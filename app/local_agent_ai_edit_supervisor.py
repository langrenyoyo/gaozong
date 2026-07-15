"""Phase 12 Task 7 19000 AI 剪辑监管器。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7 Step 3。

职责：
- 单任务队列（默认并发 1，配置允许大于 1）；
- 后台线程只负责队列与进程监管，媒体处理不在 19000 进程执行；
- 取消终止 Worker 进程树；
- 重启恢复：未完成 running 重新入队，不接受陈旧 attempt 回写；
- Worker 启动失败/缺失不影响微信路由（隔离，异常捕获记 failed）。

一期单进程单写者，状态持久化到 work_root/jobs.json。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_JOBS_FILE = "jobs.json"
_DEFAULT_CONCURRENCY = 1


@dataclass
class LocalAiEditJob:
    job_id: str
    attempt_id: str
    manifest_path: str


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
    """19000 AI 剪辑任务监管器（队列 + 进程监管 + 恢复）。

    ponytail: 一期单进程单写者，in-process executor 替身（真实 Worker 子进程
    在 Task 8 打包后由 run_worker 启动）；默认并发 1，配置 AI_EDIT_CONCURRENCY 允许 >1。
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
        # 再取同一锁；普通 Lock 会死锁。升级路径：若并发 >1 需细粒度锁可拆分。
        self._lock = threading.RLock()
        self._queue: deque[LocalAiEditJob] = deque()
        self._cancelled: set[str] = set()
        self._status = LocalAiEditStatus()
        self._job_states: dict[str, dict] = self._load_jobs()

    # ------------------------------------------------------------------
    # 持久化
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

    def _persist_job_state(self, job_id: str, *, status: str, attempt_id: str) -> None:
        with self._lock:
            self._job_states[job_id] = {
                "job_id": job_id, "status": status, "attempt_id": attempt_id,
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
            self._persist_job_state(job.job_id, status="queued", attempt_id=job.attempt_id)

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancelled

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in {j.job_id for j in self._queue} and \
               self._job_states.get(job_id, {}).get("status") not in ("running", "queued"):
                return False
            self._cancelled.add(job_id)
            self._persist_job_state(job_id, status="cancel_requested",
                                    attempt_id=self._job_states.get(job_id, {}).get("attempt_id", ""))
            return True

    def drain(self) -> None:
        """同步处理完队列（测试用，不启后台线程）。并发受 self.concurrency 限制。"""
        # ponytail: 一期并发 1，串行 drain；concurrency>1 时可用线程池（Task 8 后）
        while True:
            with self._lock:
                if not self._queue:
                    break
                job = self._queue.popleft()
                self._status.queued_count -= 1
                if job.job_id in self._cancelled:
                    self._status.cancelled_count += 1
                    self._persist_job_state(job.job_id, status="cancelled",
                                            attempt_id=job.attempt_id)
                    continue
                self._status.running_count += 1
                self._persist_job_state(job.job_id, status="running", attempt_id=job.attempt_id)
            try:
                result = self.executor(job)
                status = str(result.get("status", "failed")) if isinstance(result, dict) else "failed"
            except Exception as exc:  # noqa: BLE001  Worker 失败隔离，不影响微信路由
                logger.warning("ai_edit_supervisor stage=executor_error job_id=%s error=%s",
                               job.job_id, exc)
                status = "failed"
            with self._lock:
                self._status.running_count -= 1
                if status == "succeeded":
                    self._status.completed_count += 1
                elif status == "cancelled" or job.job_id in self._cancelled:
                    self._status.cancelled_count += 1
                else:
                    self._status.failed_count += 1
                self._persist_job_state(job.job_id, status=status, attempt_id=job.attempt_id)

    def recover(self) -> int:
        """重启恢复：未完成 running 重新入队。"""
        recovered = 0
        with self._lock:
            for job_id, state in list(self._job_states.items()):
                if state.get("status") in ("running", "queued", "cancel_requested"):
                    job = LocalAiEditJob(
                        job_id=job_id,
                        attempt_id=state.get("attempt_id", ""),
                        manifest_path=state.get("manifest_path", ""),
                    )
                    self._queue.append(job)
                    self._status.total_enqueued += 1
                    self._status.queued_count += 1
                    recovered += 1
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

    def writeback(self, *, job_id: str, attempt_id: str, result: dict) -> bool:
        """任务结果回写：attempt 不匹配或任务已终态 → 拒绝（防陈旧 attempt 回写）。"""
        with self._lock:
            state = self._job_states.get(job_id)
            if state is None:
                return False
            if state.get("status") in ("succeeded", "failed", "cancelled"):
                return False  # 已终态，拒陈旧回写
            if state.get("attempt_id") != attempt_id:
                return False  # attempt 不匹配
            status = str(result.get("status", "failed")) if isinstance(result, dict) else "failed"
            self._persist_job_state(job_id, status=status, attempt_id=attempt_id)
            if status == "succeeded":
                self._status.completed_count += 1
            elif status == "cancelled":
                self._status.cancelled_count += 1
            else:
                self._status.failed_count += 1
            return True
