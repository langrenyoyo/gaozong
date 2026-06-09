"""定时回复检测调度器"""

import threading
import time as _time
import logging

from app.database import SessionLocal
from app.services import reply_checker
from app.models import CheckConfig

logger = logging.getLogger(__name__)


class CheckScheduler:
    """简单的定时检测调度器，后台线程运行"""

    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("定时检测调度器已启动")

    def stop(self):
        self._running = False
        logger.info("定时检测调度器已停止")

    def _loop(self):
        while self._running:
            try:
                interval = self._get_interval()
                _time.sleep(interval * 60)

                db = SessionLocal()
                try:
                    updated = reply_checker.run_checks(db)
                    if updated:
                        logger.info(f"定时检测完成，更新 {len(updated)} 条记录")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"定时检测异常: {e}")

    def _get_interval(self) -> int:
        """从数据库读取检测间隔（分钟），默认 5"""
        try:
            db = SessionLocal()
            cfg = db.query(CheckConfig).filter(
                CheckConfig.config_key == "check_interval_minutes"
            ).first()
            db.close()
            if cfg:
                return int(cfg.config_value)
        except Exception:
            pass
        return 5


# 全局单例
scheduler = CheckScheduler()
