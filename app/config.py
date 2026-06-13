"""项目配置"""

import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库路径
DATABASE_DIR = os.path.join(BASE_DIR, "data")
DATABASE_PATH = os.path.join(DATABASE_DIR, "auto_wechat.db")

# 数据库连接 URL
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# 服务端口
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 9000

# 默认检测配置
DEFAULT_CONFIGS = {
    "reply_deadline_minutes": "30",
    "check_interval_minutes": "5",
    "effective_reply_min_length": "2",
    "effective_keywords": "收到,已添加,已联系,已通过,通过了,OK,好的,正在处理",
    "invalid_keywords": "不知道,不清楚,等下再说,没空,无法处理",
    "expected_reply_text": "收到，已添加微信|收到，已添加|已添加微信",
    "feedback_template": "线索已跟进：\n客户：{customer_name}\n销售：{staff_name}\n回复：{reply_content}\n时间：{actual_reply_at}",
    "feedback_require_confirm": "true",
    "p7_notification_silent_seconds": "8",
    "wechat_require_visible_before_automation": "true",
}

# ---------- douyinAPI 上游对接配置 ----------
# 仅本地开发使用，不连接生产环境
DOUYIN_API_BASE_URL = os.getenv("DOUYIN_API_BASE_URL", "http://127.0.0.1:8081")
DOUYIN_API_TIMEOUT_SECONDS = int(os.getenv("DOUYIN_API_TIMEOUT_SECONDS", "10"))
DOUYIN_SYNC_DEFAULT_LIMIT = int(os.getenv("DOUYIN_SYNC_DEFAULT_LIMIT", "50"))

# ---------- 抖音 GMP 直连接入配置 ----------
# auto_wechat 自己的环境变量，不读取 douyinAPI/.env
DY_SECRET_KEY = os.getenv("DY_SECRET_KEY", "")
DY_BASE_URL = os.getenv(
    "DY_BASE_URL",
    "https://gmp.bytedanceapi.com/ai_chat_agent_test_api/v1/openapi",
)
DY_MAIN_ACCOUNT_ID = int(os.getenv("DY_MAIN_ACCOUNT_ID", "0"))
DY_ACCOUNT_NAME = os.getenv("DY_ACCOUNT_NAME", "")
DY_HTTP_TIMEOUT_SECONDS = int(os.getenv("DY_HTTP_TIMEOUT_SECONDS", "20"))
DY_ALLOWED_DRIFT_SECONDS = int(os.getenv("DY_ALLOWED_DRIFT_SECONDS", "300"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
DY_CALLBACK_EVENTS = [
    item.strip()
    for item in os.getenv("DY_CALLBACK_EVENTS", "").split(",")
    if item.strip()
]

# ---------- 旧链路开关 ----------
# P0-END-2A：旧 wechat_auto_detect_scheduler 默认禁用。
# 新主线使用 19000 Local Agent 操作微信，旧调度器会在 9000 所在电脑直接操作微信导致冲突。
# 设置为 "1" 可恢复旧行为（仅供开发调试或回退使用）。
AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT = os.getenv("AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", "0") == "1"
