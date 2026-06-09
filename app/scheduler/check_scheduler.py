"""定时回复检测调度器

后台线程定期扫描 pending 状态的 reply_checks，将超时未回复的标记为 timeout。

线程安全：
- 使用独立 Session，不复用 HTTP 请求的 Session
- 每轮 finally 确保关闭 Session
- 异常不中断调度循环
- 通过 threading.Lock 防止重复启动
"""

import threading
import time as _time
import logging
import traceback

from app.database import SessionLocal
from app.services import reply_checker
from app.models import CheckConfig

logger = logging.getLogger(__name__)


class CheckScheduler:
    """定时检测调度器，后台守护线程运行"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._start_lock = threading.Lock()

    def start(self):
        """启动调度器（防重入：多次调用只启动一个线程）"""
        with self._start_lock:
            if self._running:
                logger.info("调度器已在运行，跳过重复启动")
                return
            self._running = True
            self._thread = threading.Thread(target=self._loop, daemon=True, name="check-scheduler")
            self._thread.start()
            logger.info("定时检测调度器已启动")

    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("定时检测调度器已停止")

    def _loop(self):
        """调度主循环"""
        while self._running:
            try:
                interval = self._get_interval()
                logger.debug("调度器等待 %d 分钟后执行检测", interval)
                _time.sleep(interval * 60)

                if not self._running:
                    break

                self._run_once()
            except Exception as exc:
                logger.error("定时检测外层异常: %s\n%s", exc, traceback.format_exc())

    def _run_once(self):
        """执行一轮检测，使用独立 Session"""
        db = SessionLocal()
        try:
            logger.info("开始执行定时检测")
            updated = reply_checker.run_checks(db)
            if updated:
                logger.info("定时检测完成，更新 %d 条记录", len(updated))
            else:
                logger.debug("定时检测完成，无超时记录")
        except Exception as exc:
            logger.error("定时检测执行异常: %s\n%s", exc, traceback.format_exc())
        finally:
            db.close()
            logger.debug("定时检测 Session 已关闭")

    def _get_interval(self) -> int:
        """从数据库读取检测间隔（分钟），默认 5"""
        db = SessionLocal()
        try:
            cfg = db.query(CheckConfig).filter(
                CheckConfig.config_key == "check_interval_minutes"
            ).first()
            if cfg:
                return int(cfg.config_value)
        except Exception as exc:
            logger.warning("读取检测间隔失败，使用默认值 5 分钟: %s", exc)
        finally:
            db.close()
        return 5


# 全局单例
scheduler = CheckScheduler()
