"""Phase 12 Task 7 19000 AI 剪辑监管器（FIX2：复合任务键 + 商户隔离）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7。

FIX2 核心变更：
- 任务键为 (merchant_id, job_id) 复合键，不再仅 job_id；
- _job_states / _processes / _cancelled 全部以复合键索引；
- cancel / get_job_state / writeback 必须校验 merchant_id 匹配（跨商户不可操作）；
- status 按 merchant_id 过滤计数。

职责：单任务队列 + 子进程监管 + 恢复（跳过终态与 cancel_requested，保留 manifest_path）。
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

_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
# FIX2-4：cancel_requested 不跳过恢复——取消后到队列归一为 cancelled 前进程退出，
# 重启必须重新入队（drain 时归一 cancelled + 回写 9000），否则永久停在 cancel_requested。
_SKIP_RECOVER_STATUSES = _TERMINAL_STATUSES

# FIX1-4：终态回写失败的有界重试上限（recover 时补偿），超过则放弃记日志。
_MAX_WRITEBACK_ATTEMPTS = 3


@dataclass
class LocalAiEditJob:
    job_id: str
    attempt_id: str
    manifest_path: str
    merchant_id: str = ""
    # §5 下发通道：9000 agent-create 返回的执行令牌与 attempt，供终态回写。
    execution_token_hash: str = ""
    attempt_count: int = 0


@dataclass
class LocalAiEditStatus:
    total_enqueued: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    running_count: int = 0
    queued_count: int = 0


Executor = Callable[[LocalAiEditJob], dict]


def _task_key(merchant_id: str, job_id: str) -> str:
    """复合任务键：merchant_id/job_id（两段都已安全校验，斜杠为分隔符）。"""
    return f"{merchant_id}/{job_id}"


class AiEditSupervisor:
    """19000 AI 剪辑任务监管器（队列 + 子进程监管 + 恢复，商户隔离复合键）。"""

    def __init__(
        self,
        *,
        work_root: Path,
        executor: Executor,
        concurrency: int | None = None,
        on_job_terminal: Callable[[LocalAiEditJob, str], None] | None = None,
    ):
        self.work_root = Path(work_root)
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.executor = executor
        self.concurrency = concurrency or int(
            os.getenv("AI_EDIT_CONCURRENCY", str(_DEFAULT_CONCURRENCY))
        )
        # FIX2-7：任务终态回调（释放活动素材引用等），签名 (job, status)
        self._on_job_terminal = on_job_terminal
        # ponytail: RLock 可重入——enqueue/drain 持锁时调用 _persist_job_state 再取同一锁。
        self._lock = threading.RLock()
        self._queue: deque[LocalAiEditJob] = deque()
        # 复合键 -> 取消标记 / 进程句柄 / 状态
        self._cancelled: set[str] = set()
        self._processes: dict[str, object] = {}
        self._status = LocalAiEditStatus()
        self._job_states: dict[str, dict] = self._load_jobs()
        self._drain_thread: threading.Thread | None = None
        self._auto_start = False

    # ------------------------------------------------------------------
    # 持久化（键为复合 key，保留 manifest_path / merchant_id / job_id / attempt_id）
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
        self, key: str, *, status: str, attempt_id: str,
        manifest_path: str = "", merchant_id: str = "", job_id: str = "",
        execution_token_hash: str | None = None,
        attempt_count: int | None = None,
        pending_writeback: bool | None = None,
        writeback_attempts: int | None = None,
    ) -> None:
        with self._lock:
            existing = self._job_states.get(key, {})
            self._job_states[key] = {
                "job_id": job_id or existing.get("job_id", ""),
                "merchant_id": merchant_id or existing.get("merchant_id", ""),
                "status": status,
                "attempt_id": attempt_id,
                "manifest_path": manifest_path or existing.get("manifest_path", ""),
                # FIX1-3：持久化回写凭证（令牌+attempt），否则重启后无法回写 9000
                "execution_token_hash": execution_token_hash
                    if execution_token_hash is not None
                    else existing.get("execution_token_hash", ""),
                "attempt_count": attempt_count
                    if attempt_count is not None
                    else existing.get("attempt_count", 0),
                # FIX1-4：待回写标记 + 重试次数，recover 时补偿重试
                "pending_writeback": pending_writeback
                    if pending_writeback is not None
                    else existing.get("pending_writeback", False),
                "writeback_attempts": writeback_attempts
                    if writeback_attempts is not None
                    else existing.get("writeback_attempts", 0),
            }
            self._save_jobs()

    # ------------------------------------------------------------------
    # 队列与执行
    # ------------------------------------------------------------------

    def enqueue(self, job: LocalAiEditJob) -> None:
        if not job.merchant_id:
            raise ValueError("enqueue 需要 merchant_id")
        key = _task_key(job.merchant_id, job.job_id)
        with self._lock:
            self._queue.append(job)
            self._status.total_enqueued += 1
            self._status.queued_count += 1
            self._persist_job_state(
                key, status="queued", attempt_id=job.attempt_id,
                manifest_path=job.manifest_path,
                merchant_id=job.merchant_id, job_id=job.job_id,
                execution_token_hash=job.execution_token_hash,
                attempt_count=job.attempt_count,
            )
        if self._auto_start:
            self._ensure_drain_thread()

    def start(self) -> None:
        self._auto_start = True
        self._ensure_drain_thread()

    def is_cancelled(self, merchant_id: str, job_id: str) -> bool:
        with self._lock:
            return _task_key(merchant_id, job_id) in self._cancelled

    def cancel(self, *, merchant_id: str, job_id: str) -> bool:
        """取消任务（商户隔离：merchant_id 必须匹配持久化记录）。"""
        with self._lock:
            key = _task_key(merchant_id, job_id)
            state = self._job_states.get(key)
            if state is None:
                return False  # 任务不存在或不属于该商户
            if state.get("merchant_id") != merchant_id:
                return False  # 跨商户
            if state.get("status") in _TERMINAL_STATUSES:
                return False
            self._cancelled.add(key)
            self._persist_job_state(
                key, status="cancel_requested",
                attempt_id=state.get("attempt_id", ""),
                manifest_path=state.get("manifest_path", ""),
                merchant_id=merchant_id, job_id=job_id,
                execution_token_hash=state.get("execution_token_hash", ""),
                attempt_count=state.get("attempt_count", 0),
            )
            proc = self._processes.get(key)
        if proc is not None:
            try:
                from apps.ai_edit.media_tools import terminate_process_tree
                terminate_process_tree(proc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ai_edit_supervisor stage=cancel_terminate error=%s", exc)
        return True

    def _ensure_drain_thread(self) -> None:
        with self._lock:
            if self._drain_thread is not None and self._drain_thread.is_alive():
                return
            self._drain_thread = threading.Thread(
                target=self._drain_loop, name="ai-edit-supervisor", daemon=True,
            )
            self._drain_thread.start()

    def _drain_loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    break
                job = self._queue.popleft()
                key = _task_key(job.merchant_id, job.job_id)
                self._status.queued_count -= 1
                if key in self._cancelled:
                    self._status.cancelled_count += 1
                    self._persist_job_state(
                        key, status="cancelled", attempt_id=job.attempt_id,
                        manifest_path=job.manifest_path,
                        merchant_id=job.merchant_id, job_id=job.job_id,
                        execution_token_hash=job.execution_token_hash,
                        attempt_count=job.attempt_count,
                        pending_writeback=True,
                    )
                    term_job = LocalAiEditJob(
                        job_id=job.job_id, attempt_id=job.attempt_id,
                        manifest_path=job.manifest_path, merchant_id=job.merchant_id,
                        execution_token_hash=job.execution_token_hash,
                        attempt_count=job.attempt_count,
                    )
                    self._fire_terminal(term_job, "cancelled")
                    continue
                self._status.running_count += 1
                self._persist_job_state(
                    key, status="running", attempt_id=job.attempt_id,
                    manifest_path=job.manifest_path,
                    merchant_id=job.merchant_id, job_id=job.job_id,
                )
            status = self._execute_job(job)
            with self._lock:
                self._status.running_count -= 1
                self._processes.pop(key, None)
                # FIX3-1：取消终态归一——复合键在 _cancelled 则 final_status 必为 cancelled，
                # 不用 executor 返回的原始 status（Worker 被终止后通常返回 failed）。
                if key in self._cancelled:
                    final_status = "cancelled"
                    self._status.cancelled_count += 1
                elif status == "succeeded":
                    final_status = "succeeded"
                    self._status.completed_count += 1
                else:
                    final_status = "failed"
                    self._status.failed_count += 1
                # FIX1-4：终态标记 pending_writeback，on_job_terminal 回写成功后清除；
                # 回写失败则 recover 时补偿重试（有界），避免 19000 succeeded/9000 queued 永久分叉。
                self._persist_job_state(
                    key, status=final_status, attempt_id=job.attempt_id,
                    manifest_path=job.manifest_path,
                    merchant_id=job.merchant_id, job_id=job.job_id,
                    execution_token_hash=job.execution_token_hash,
                    attempt_count=job.attempt_count,
                    pending_writeback=True,
                )
                # 终态任务把令牌带给 on_job_terminal 回调（回写 9000 用）
                term_job = LocalAiEditJob(
                    job_id=job.job_id, attempt_id=job.attempt_id,
                    manifest_path=job.manifest_path, merchant_id=job.merchant_id,
                    execution_token_hash=job.execution_token_hash,
                    attempt_count=job.attempt_count,
                )
            self._fire_terminal(term_job, final_status)

    def _fire_terminal(self, job: LocalAiEditJob, status: str) -> None:
        """触发终态回调（释放活动素材引用等）。异常隔离不影响主流程。"""
        if self._on_job_terminal is None:
            return
        try:
            self._on_job_terminal(job, status)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_edit_supervisor stage=terminal_callback error=%s", exc)

    def _execute_job(self, job: LocalAiEditJob) -> str:
        try:
            result = self.executor(job)
            status = str(result.get("status", "failed")) if isinstance(result, dict) else "failed"
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_edit_supervisor stage=executor_error job_id=%s error=%s",
                           job.job_id, exc)
            status = "failed"
        return status

    def drain(self) -> None:
        """同步处理完队列（测试用）。生产路径走 start() 异步。"""
        self._drain_loop()

    def register_process(self, merchant_id: str, job_id: str, process: object) -> None:
        with self._lock:
            self._processes[_task_key(merchant_id, job_id)] = process

    def recover(self) -> int:
        """重启恢复：跳过终态与 cancel_requested，重新入队 running/queued。

        FIX1-3：恢复 execution_token_hash + attempt_count 到 LocalAiEditJob（否则回写缺凭证）。
        FIX1-4：对终态但 pending_writeback=True 的任务，触发 on_job_terminal 补偿回写
        （有界 _MAX_WRITEBACK_ATTEMPTS 次），避免 19000 succeeded/9000 queued 永久分叉。
        """
        recovered = 0
        pending: list[tuple[LocalAiEditJob, str]] = []
        with self._lock:
            for key, state in list(self._job_states.items()):
                if state.get("status") in _SKIP_RECOVER_STATUSES:
                    # 终态但待回写：补偿重试（有界）
                    if state.get("pending_writeback") and state.get("execution_token_hash"):
                        attempts = int(state.get("writeback_attempts", 0) or 0)
                        if attempts < _MAX_WRITEBACK_ATTEMPTS:
                            job = LocalAiEditJob(
                                job_id=state.get("job_id", ""),
                                attempt_id=state.get("attempt_id", ""),
                                manifest_path=state.get("manifest_path", ""),
                                merchant_id=state.get("merchant_id", ""),
                                execution_token_hash=state.get("execution_token_hash", ""),
                                attempt_count=int(state.get("attempt_count", 0) or 0),
                            )
                            pending.append((job, state.get("status", "failed")))
                            self._persist_job_state(
                                key, status=state.get("status", ""),
                                attempt_id=state.get("attempt_id", ""),
                                manifest_path=state.get("manifest_path", ""),
                                merchant_id=state.get("merchant_id", ""),
                                job_id=state.get("job_id", ""),
                                execution_token_hash=state.get("execution_token_hash", ""),
                                attempt_count=int(state.get("attempt_count", 0) or 0),
                                pending_writeback=True,
                                writeback_attempts=attempts + 1,
                            )
                    continue
                job = LocalAiEditJob(
                    job_id=state.get("job_id", ""),
                    attempt_id=state.get("attempt_id", ""),
                    manifest_path=state.get("manifest_path", ""),
                    merchant_id=state.get("merchant_id", ""),
                    execution_token_hash=state.get("execution_token_hash", ""),
                    attempt_count=int(state.get("attempt_count", 0) or 0),
                )
                # FIX2-4：cancel_requested 恢复时把 key 加入 _cancelled，drain 归一 cancelled + 回写
                if state.get("status") == "cancel_requested":
                    self._cancelled.add(key)
                # FIX3-3：retry_preparing 恢复时作为 queued 重新入队（令牌可能已被 9000 推进，
                # 回写若 409 则 on_job_terminal 记日志，最终由 pending_writeback 补偿或人工）
                self._queue.append(job)
                self._status.total_enqueued += 1
                self._status.queued_count += 1
                recovered += 1
        if recovered and self._auto_start:
            self._ensure_drain_thread()
        # 补偿待回写（锁外触发回调，避免持锁调 HTTP）
        for job, status in pending:
            self._fire_terminal(job, status)
        return recovered

    def get_job_state(self, *, merchant_id: str, job_id: str) -> dict | None:
        """查询任务状态（商户隔离：merchant_id 不匹配返回 None）。"""
        with self._lock:
            state = self._job_states.get(_task_key(merchant_id, job_id))
            if state is None:
                return None
            if state.get("merchant_id") != merchant_id:
                return None
            return dict(state)

    def status(self, *, merchant_id: str | None = None) -> LocalAiEditStatus:
        """状态统计；merchant_id 给定时只计该商户任务。"""
        with self._lock:
            if merchant_id is None:
                return LocalAiEditStatus(
                    total_enqueued=self._status.total_enqueued,
                    completed_count=self._status.completed_count,
                    failed_count=self._status.failed_count,
                    cancelled_count=self._status.cancelled_count,
                    running_count=self._status.running_count,
                    queued_count=self._status.queued_count,
                )
            # 按商户过滤持久化状态计数
            total = completed = failed = cancelled = running = queued = 0
            for state in self._job_states.values():
                if state.get("merchant_id") != merchant_id:
                    continue
                total += 1
                st = state.get("status")
                if st == "succeeded":
                    completed += 1
                elif st == "failed":
                    failed += 1
                elif st == "cancelled":
                    cancelled += 1
                elif st == "running":
                    running += 1
                elif st in ("queued", "cancel_requested"):
                    queued += 1
            return LocalAiEditStatus(
                total_enqueued=total, completed_count=completed, failed_count=failed,
                cancelled_count=cancelled, running_count=running, queued_count=queued,
            )

    def writeback(self, *, merchant_id: str, job_id: str, attempt_id: str, result: dict) -> bool:
        """任务结果回写（商户隔离 + attempt 校验，防陈旧回写）。"""
        with self._lock:
            key = _task_key(merchant_id, job_id)
            state = self._job_states.get(key)
            if state is None:
                return False
            if state.get("merchant_id") != merchant_id:
                return False
            if state.get("status") in _TERMINAL_STATUSES:
                return False
            if state.get("attempt_id") != attempt_id:
                return False
            status = str(result.get("status", "failed")) if isinstance(result, dict) else "failed"
            self._persist_job_state(
                key, status=status, attempt_id=attempt_id,
                manifest_path=state.get("manifest_path", ""),
                merchant_id=merchant_id, job_id=job_id,
            )
            return True

    def clear_pending_writeback(self, *, merchant_id: str, job_id: str) -> bool:
        """on_job_terminal 回写 9000 成功后清除待回写标记（FIX1-4）。"""
        with self._lock:
            key = _task_key(merchant_id, job_id)
            state = self._job_states.get(key)
            if state is None or state.get("merchant_id") != merchant_id:
                return False
            self._persist_job_state(
                key, status=state.get("status", ""),
                attempt_id=state.get("attempt_id", ""),
                manifest_path=state.get("manifest_path", ""),
                merchant_id=merchant_id, job_id=job_id,
                execution_token_hash=state.get("execution_token_hash", ""),
                attempt_count=state.get("attempt_count", 0),
                pending_writeback=False,
            )
            return True

    def can_retry(self, *, merchant_id: str, job_id: str) -> bool:
        """前置可重试检查（不落盘）：任务存在、归属本商户、非运行中、非重试中。

        FIX3-3：拒 running 与 retry_preparing（防并发重复重试 + 跨系统分叉）。
        允许终态（succeeded/failed/cancelled/queued/cancel_requested）重试。
        """
        with self._lock:
            key = _task_key(merchant_id, job_id)
            state = self._job_states.get(key)
            if state is None or state.get("merchant_id") != merchant_id:
                return False
            return state.get("status") not in ("running", "retry_preparing")

    def claim_retry(self, *, merchant_id: str, job_id: str) -> dict | None:
        """原子 claim 为 retry_preparing（持锁 CAS，防并发重试）。

        FIX3-3：远端推进前先冻结本地状态为 retry_preparing，第二个并发请求会被 can_retry
        拒（retry_preparing）。返回原状态快照供失败时回退。非 running/retry_preparing 才允许。
        """
        with self._lock:
            key = _task_key(merchant_id, job_id)
            state = self._job_states.get(key)
            if state is None or state.get("merchant_id") != merchant_id:
                return None
            if state.get("status") in ("running", "retry_preparing"):
                return None
            snapshot = dict(state)
            self._persist_job_state(
                key, status="retry_preparing", attempt_id=state.get("attempt_id", ""),
                manifest_path=state.get("manifest_path", ""),
                merchant_id=merchant_id, job_id=job_id,
                execution_token_hash=state.get("execution_token_hash", ""),
                attempt_count=int(state.get("attempt_count", 0) or 0),
            )
            return snapshot

    def revert_retry_claim(self, *, merchant_id: str, job_id: str, snapshot: dict) -> None:
        """远端推进失败时回退 retry_preparing 到原状态（可恢复，FIX3-3）。"""
        with self._lock:
            key = _task_key(merchant_id, job_id)
            self._persist_job_state(
                key, status=snapshot.get("status", "failed"),
                attempt_id=snapshot.get("attempt_id", ""),
                manifest_path=snapshot.get("manifest_path", ""),
                merchant_id=merchant_id, job_id=job_id,
                execution_token_hash=snapshot.get("execution_token_hash", ""),
                attempt_count=int(snapshot.get("attempt_count", 0) or 0),
            )

    def requeue(
        self, *, merchant_id: str, job_id: str, attempt_id: str,
        execution_token_hash: str, attempt_count: int,
    ) -> bool:
        """重试重新入队：校验任务存在且非运行中，更新令牌/attempt/状态后重新排队。

        FIX1：19000 retry 唯一入口——9000 已轮换令牌，这里把新令牌写回持久化状态再入队，
        使 on_job_terminal 终态回写能用新令牌命中 9000 当前 attempt。
        """
        with self._lock:
            key = _task_key(merchant_id, job_id)
            state = self._job_states.get(key)
            if state is None or state.get("merchant_id") != merchant_id:
                return False
            if state.get("status") == "running":
                return False  # 运行中不可重试
            # 取消标记清除（重试覆盖取消）
            self._cancelled.discard(key)
            job = LocalAiEditJob(
                job_id=job_id, attempt_id=attempt_id,
                manifest_path=state.get("manifest_path", ""),
                merchant_id=merchant_id,
                execution_token_hash=execution_token_hash,
                attempt_count=attempt_count,
            )
            self._queue.append(job)
            self._status.total_enqueued += 1
            self._status.queued_count += 1
            self._persist_job_state(
                key, status="queued", attempt_id=attempt_id,
                manifest_path=state.get("manifest_path", ""),
                merchant_id=merchant_id, job_id=job_id,
                execution_token_hash=execution_token_hash,
                attempt_count=attempt_count,
                pending_writeback=False, writeback_attempts=0,
            )
        if self._auto_start:
            self._ensure_drain_thread()
        return True
