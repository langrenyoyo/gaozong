"""企业微信 P1 调度器（SPEC v1.0 §7.3）：callback worker + 授权对账循环。

运行形态：单实例 9000 进程内，复用项目 scheduler 现有 start/stop 模式；
仅 capability 启用时启动（WECOM_SUITE_SECRET + WECOM_CREDENTIAL_MASTER_KEY 均已配置）。

- callback worker：轮询领取 RECEIVED / FAILED_RETRYABLE 事件（lease 行锁 + backoff），
  处理后写终态；崩溃恢复靠 lease 过期重新领取。
- 授权对账：小时级（WECOM_AUTH_RECONCILE_INTERVAL_MINUTES，默认 60），仅 ACTIVE/CHANGED，
  对 CANCELLED/INVALID/FAILED 不发起官方调用（B4 兜底，D8）。
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time

from app import config
from app.services import wecom_authorization_service, wecom_callback_service

logger = logging.getLogger("wecom_scheduler")

_WORKER_POLL_SECONDS = 10


def _capability_enabled() -> bool:
    return bool(config.WECOM_SUITE_SECRET and config.WECOM_CREDENTIAL_MASTER_KEY)


class WeComScheduler:
    """企微 callback worker + 对账循环（守护线程，防重复启动）。"""

    def __init__(self) -> None:
        self._running = False
        self._worker_thread: threading.Thread | None = None
        self._reconcile_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._identity = f"{socket.gethostname()}:{os.getpid()}"

    def start(self) -> None:
        if not _capability_enabled():
            logger.info("wecom_scheduler stage=start_skip reason=capability_disabled")
            return
        with self._lock:
            if self._running:
                logger.info("wecom_scheduler stage=start_skip reason=already_running")
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop, name="wecom-callback-worker", daemon=True
            )
            self._reconcile_thread = threading.Thread(
                target=self._reconcile_loop, name="wecom-auth-reconcile", daemon=True
            )
            self._worker_thread.start()
            self._reconcile_thread.start()
            logger.info("wecom_scheduler stage=started identity=%s", self._identity)

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while self._running:
            try:
                stats = wecom_callback_service.claim_and_process_batch(identity=self._identity)
                if stats.get("claimed"):
                    logger.info(
                        "wecom_scheduler stage=worker_batch claimed=%s processed=%s retryable=%s permanent=%s",
                        stats["claimed"], stats["processed"], stats["retryable"], stats["permanent"],
                    )
            except Exception:  # noqa: BLE001  单轮失败不中断循环
                logger.exception("wecom_scheduler stage=worker_batch_error")
            time.sleep(_WORKER_POLL_SECONDS)

    def _reconcile_loop(self) -> None:
        interval = max(int(config.WECOM_AUTH_RECONCILE_INTERVAL_MINUTES or 60), 1)
        while self._running:
            time.sleep(interval * 60)
            if not self._running:
                break
            try:
                result = wecom_authorization_service.reconcile_authorizations()
                logger.info(
                    "wecom_scheduler stage=reconcile scanned=%s cancelled=%s changed=%s kept=%s errors=%s",
                    result["scanned"], result["cancelled"], result["changed"],
                    result["kept"], result["errors"],
                )
            except Exception:  # noqa: BLE001
                logger.exception("wecom_scheduler stage=reconcile_error")


# 模块级单例（main.py startup 挂接）
wecom_scheduler = WeComScheduler()
