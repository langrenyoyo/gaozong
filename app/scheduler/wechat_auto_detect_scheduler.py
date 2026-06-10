"""微信自动检测调度器

后台线程周期性读取 active_check_id，
对目标 check 执行微信 UI 检测。

调度器不识别销售、不切换窗口、不发送消息。
仅对用户指定的 active_check_id 执行检测。

线程安全：
- 使用独立 Session，不复用 HTTP 请求的 Session
- 每轮 finally 确保关闭 Session
- 异常不中断调度循环
- 通过 threading.Lock 防止重复启动

与 check_scheduler 的关系：
- check_scheduler：扫描所有 pending check，超时 → timeout
- wechat_auto_detect_scheduler：检测 active check，命中 → replied
- 两者独立运行，互不干扰
"""

import threading
import time as _time
import logging
import traceback
from datetime import datetime

from app.database import SessionLocal
from app.models import CheckConfig, ReplyCheck, DouyinLead, LeadNotification

logger = logging.getLogger(__name__)

# check_configs 存储的 key（与 wechat_auto_detect 路由保持一致）
_CFG_ENABLED = "wechat_auto_detect_enabled"
_CFG_ACTIVE_CHECK_ID = "wechat_active_check_id"
_CFG_INTERVAL = "wechat_auto_detect_interval_seconds"
_CFG_LAST_DETECT_AT = "wechat_auto_detect_last_detect_at"
_CFG_LAST_RESULT = "wechat_auto_detect_last_result"

# 安全限制
_MIN_INTERVAL_SECONDS = 5


class WechatAutoDetectScheduler:
    """微信自动检测调度器，后台守护线程运行"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._start_lock = threading.Lock()

    def start(self):
        """启动调度器（防重入：多次调用只启动一个线程）"""
        with self._start_lock:
            if self._running:
                logger.info("微信自动检测调度器已在运行，跳过重复启动")
                return
            self._running = True
            self._thread = threading.Thread(
                target=self._loop,
                daemon=True,
                name="wechat-auto-detect-scheduler",
            )
            self._thread.start()
            logger.info("微信自动检测调度器已启动")

    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("微信自动检测调度器已停止")

    def _loop(self):
        """调度主循环"""
        while self._running:
            try:
                interval = self._get_interval()
                logger.debug("微信自动检测调度器等待 %d 秒", interval)
                _time.sleep(interval)

                if not self._running:
                    break

                self.run_once()
            except Exception as exc:
                logger.error("微信自动检测外层异常: %s\n%s", exc, traceback.format_exc())

    def _get_interval(self) -> int:
        """从数据库读取检测间隔（秒），默认 10，最小 5"""
        db = SessionLocal()
        try:
            cfg = db.query(CheckConfig).filter(
                CheckConfig.config_key == _CFG_INTERVAL
            ).first()
            if cfg and cfg.config_value:
                interval = int(cfg.config_value)
                return max(interval, _MIN_INTERVAL_SECONDS)
        except Exception as exc:
            logger.warning("读取检测间隔失败，使用默认值 10 秒: %s", exc)
        finally:
            db.close()
        return 10

    def run_once(self):
        """执行一轮自动检测，使用独立 Session"""
        db = SessionLocal()
        try:
            # --- 0. 紧急停止检查 ---
            from app.services.automation_control import is_automation_allowed
            if not is_automation_allowed():
                logger.debug("自动化已紧急停止，跳过本轮检测")
                return

            # --- 1. 读取配置 ---
            enabled = self._read_config(db, _CFG_ENABLED, "true")
            if enabled != "true":
                logger.debug("微信自动检测未启用，跳过")
                return

            raw_check_id = self._read_config(db, _CFG_ACTIVE_CHECK_ID, "")
            if not raw_check_id or not raw_check_id.isdigit():
                logger.debug("无自动检测目标，跳过")
                return

            active_check_id = int(raw_check_id)

            # --- 2. 查询 check ---
            check = db.query(ReplyCheck).filter(ReplyCheck.id == active_check_id).first()
            if not check:
                logger.info("自动检测目标 check #%d 不存在，自动清除", active_check_id)
                self._clear_target(db, "check_not_found")
                return

            if check.check_status != "pending":
                logger.info(
                    "自动检测目标 check #%d 状态为 %s，自动清除",
                    active_check_id, check.check_status,
                )
                self._clear_target(db, f"check_finished:{check.check_status}")
                return

            # --- 3. 查询 lead ---
            lead = db.get(DouyinLead, check.lead_id)
            if not lead or lead.status != "assigned":
                logger.info(
                    "自动检测目标 lead #%d 状态为 %s，自动清除",
                    check.lead_id, lead.status if lead else "不存在",
                )
                self._clear_target(db, "lead_not_assigned")
                return

            # --- 4. 查询所有已发送通知（用于静默期和排除列表） ---
            notifications = db.query(LeadNotification).filter(
                LeadNotification.lead_id == check.lead_id,
                LeadNotification.staff_id == check.staff_id,
                LeadNotification.send_status == "sent",
            ).order_by(LeadNotification.sent_at.desc()).all()

            # --- 4a. 静默期检查（P7-BUG-1 修复） ---
            if notifications and notifications[0].sent_at:
                silent_seconds = self._get_silent_seconds(db)
                elapsed = (datetime.now() - notifications[0].sent_at).total_seconds()
                if elapsed < silent_seconds:
                    logger.info(
                        "通知发送后 %.1f 秒，静默期内跳过检测（阈值 %d 秒）: check #%d",
                        elapsed, silent_seconds, check.id,
                    )
                    self._write_config(db, _CFG_LAST_DETECT_AT, datetime.now().isoformat())
                    self._write_config(db, _CFG_LAST_RESULT, "silent_period")
                    db.commit()
                    return

            # --- 5. 执行检测 ---
            logger.info(
                "开始自动检测: check #%d, lead #%d (%s), staff #%d",
                check.id, lead.id, lead.customer_name, check.staff_id,
            )

            # 构造排除列表（所有通知文本，避免旧通知也触发误判）
            exclude_texts = None
            if notifications:
                exclude_texts = [
                    n.notification_text
                    for n in notifications
                    if n.notification_text
                ]
                if not exclude_texts:
                    exclude_texts = None

            result = self._do_detect(
                db, check.lead_id, check.staff_id,
                exclude_text_list=exclude_texts,
            )

            # --- 5. 处理结果 ---
            now_str = datetime.now().isoformat()
            is_effective = result.get("is_effective", 0)
            check_status = result.get("check_status", "")
            matched = result.get("matched_content", "")

            if is_effective == 1 or check_status == "replied":
                # 检测命中：清空目标
                self._clear_target(db, f"replied:{matched}")
                logger.info(
                    "自动检测命中: check #%d, matched=%s", check.id, matched,
                )
            elif result.get("success"):
                # 检测未命中：保留目标，等待下一轮
                self._write_config(db, _CFG_LAST_DETECT_AT, now_str)
                self._write_config(db, _CFG_LAST_RESULT, "not_matched")
                db.commit()
                logger.info("自动检测未命中: check #%d", check.id)
            else:
                # 检测失败（微信未启动等）：保留目标
                error_msg = result.get("message", "未知错误")[:80]
                self._write_config(db, _CFG_LAST_DETECT_AT, now_str)
                self._write_config(db, _CFG_LAST_RESULT, f"error:{error_msg}")
                db.commit()
                logger.warning("自动检测失败: check #%d, %s", check.id, error_msg)

        except Exception as exc:
            # 异常不清空目标，等待下一轮重试
            logger.error("微信自动检测执行异常: %s\n%s", exc, traceback.format_exc())
            try:
                now_str = datetime.now().isoformat()
                self._write_config(db, _CFG_LAST_DETECT_AT, now_str)
                self._write_config(db, _CFG_LAST_RESULT, f"error:{str(exc)[:80]}")
                db.commit()
            except Exception:
                pass
        finally:
            db.close()
            logger.debug("微信自动检测 Session 已关闭")

    def _do_detect(self, db, lead_id: int, staff_id: int,
                   exclude_text_list: list[str] | None = None) -> dict:
        """调用现有检测服务（分离方法便于 mock 测试）"""
        from app.services.wechat_ui_reply_service import detect_reply_from_wechat
        return detect_reply_from_wechat(
            db=db,
            lead_id=lead_id,
            staff_id=staff_id,
            max_messages=20,
            confirm_current_chat=True,
            exclude_text_list=exclude_text_list,
        )

    def _clear_target(self, db: SessionLocal, reason: str):
        """清空 active_check_id 并写入结果"""
        self._write_config(db, _CFG_ACTIVE_CHECK_ID, "")
        self._write_config(db, _CFG_LAST_DETECT_AT, datetime.now().isoformat())
        self._write_config(db, _CFG_LAST_RESULT, reason)
        db.commit()

    def _get_silent_seconds(self, db) -> int:
        """从数据库读取通知静默期（秒），默认 8，最小 3"""
        try:
            val = self._read_config(db, "p7_notification_silent_seconds", "8")
            seconds = int(val)
            return max(seconds, 3)
        except (ValueError, Exception):
            return 8

    def _read_config(self, db, key: str, default: str = "") -> str:
        """读取配置值"""
        cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
        return cfg.config_value if cfg else default

    def _write_config(self, db, key: str, value: str):
        """写入配置值（不存在则创建）"""
        cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
        if cfg:
            cfg.config_value = value
            cfg.updated_at = datetime.now()
        else:
            cfg = CheckConfig(config_key=key, config_value=value)
            db.add(cfg)
        db.flush()


# 全局单例
wechat_auto_detect_scheduler = WechatAutoDetectScheduler()
