"""项目配置"""

import os
from pathlib import Path

BASE_PATH = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_PATH / ".env"


def _load_env_file(env_file: Path) -> None:
    """Load project .env without overriding explicit environment variables."""
    if not env_file.exists():
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(ENV_FILE)

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
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
DY_SECRET_KEY = os.getenv("DY_SECRET_KEY", "")
DY_GMP_SECRET_KEY = os.getenv("DY_GMP_SECRET_KEY", "")
DY_BASE_URL = os.getenv(
    "DY_BASE_URL",
    "https://gmp.bytedanceapi.com/ai_chat_agent_api/v1/openapi",
)
DY_MAIN_ACCOUNT_ID = int(os.getenv("DY_MAIN_ACCOUNT_ID", "0"))
DY_ACCOUNT_NAME = os.getenv("DY_ACCOUNT_NAME", "")
DY_HTTP_TIMEOUT_SECONDS = int(os.getenv("DY_HTTP_TIMEOUT_SECONDS", "20"))
DY_ALLOWED_DRIFT_SECONDS = int(os.getenv("DY_ALLOWED_DRIFT_SECONDS", "300"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
DY_LIVE_CHECK_ENABLED = os.getenv("DY_LIVE_CHECK_ENABLED", "false").lower() == "true"
DY_LIVE_CHECK_FORWARD_TO_FORMAL = os.getenv("DY_LIVE_CHECK_FORWARD_TO_FORMAL", "false").lower() == "true"
# 入站 webhook 是否强制签名鉴权
# development 可关闭用于本地开发 / 联调；production 始终强制验签
DOUYIN_WEBHOOK_AUTH_REQUIRED = os.getenv("DOUYIN_WEBHOOK_AUTH_REQUIRED", "false").lower() == "true"
DY_CALLBACK_EVENTS = [
    item.strip()
    for item in os.getenv("DY_CALLBACK_EVENTS", "").split(",")
    if item.strip()
]
DY_CALLBACK_URL = os.getenv("DY_CALLBACK_URL", "").strip() or None
DY_AUTH_REDIRECT_URL = os.getenv("DY_AUTH_REDIRECT_URL", "").strip() or None

def is_production_env() -> bool:
    """判断当前是否为生产环境。"""
    return APP_ENV == "production"


def is_douyin_webhook_auth_required() -> bool:
    """返回当前 webhook 是否需要验签。

    production 环境强制验签，避免 DOUYIN_WEBHOOK_AUTH_REQUIRED=false 静默放行。
    """
    return is_production_env() or DOUYIN_WEBHOOK_AUTH_REQUIRED

# ---------- 旧链路开关 ----------
# P0-END-2A：旧 wechat_auto_detect_scheduler 默认禁用。
# 新主线使用 19000 Local Agent 操作微信，旧调度器会在 9000 所在电脑直接操作微信导致冲突。
# 设置为 "1" 可恢复旧行为（仅供开发调试或回退使用）。
AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT = os.getenv("AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT", "0") == "1"
