"""项目配置"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

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


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def parse_bool(value: object, default: bool = False, *, name: str | None = None) -> bool:
    """严格解析布尔配置；未知值回落默认，避免拼写错误误启高风险能力。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", ""}:
        return False

    if name:
        logger.warning("Invalid boolean value for %s=%r, fallback to %s", name, value, default)
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    return parse_bool(os.getenv(name), default, name=name)


def _env_positive_int(name: str, default: int) -> int:
    """读取正整数配置；非法值回落默认，避免脏环境变量阻断服务启动。"""
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_nonnegative_int(name: str, default: int) -> int:
    """读取非负整数配置；用于 0 有明确语义的限流开关。"""
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _env_float_range(name: str, default: float, *, minimum: float, maximum: float) -> float:
    """读取浮点范围配置；非法值回落默认，避免误拼写放大灰度范围。"""
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if minimum <= parsed <= maximum else default


def _env_csv_set(name: str) -> set[str]:
    """解析逗号分隔白名单，自动忽略空值和多余空格。"""
    result: set[str] = set()
    for item in os.getenv(name, "").split(","):
        text = item.strip()
        if text:
            result.add(text)
    return result

# 默认跨域来源地址
DEFAULT_CORS_ORIGINS = {
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://192.168.110.113:5173",
    "http://192.168.110.113:9000",
    "http://192.168.110.19:5174",
    "http://DESKTOP-T0HA3GO:5173",
}
CORS_ORIGINS = tuple(sorted(_env_csv_set("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS))

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据库路径
DATABASE_DIR = os.path.join(BASE_DIR, "data")
DATABASE_PATH = os.path.join(DATABASE_DIR, "auto_wechat.db")

# 数据库连接 URL
# P2-A 仅引入配置抽象；默认仍使用当前 SQLite 文件，PostgreSQL 连接池留到后续阶段。
DATABASE_URL = _env_str("DATABASE_URL", f"sqlite:///{DATABASE_PATH}")

# PostgreSQL async pool 预留配置。P2-E 只读取配置，不创建连接池。
DB_POOL_SIZE = _env_positive_int("DB_POOL_SIZE", 20)
DB_MAX_OVERFLOW = _env_positive_int("DB_MAX_OVERFLOW", 40)
DB_POOL_TIMEOUT = _env_positive_int("DB_POOL_TIMEOUT", 30)
DB_POOL_RECYCLE = _env_positive_int("DB_POOL_RECYCLE", 1800)
DB_STATEMENT_TIMEOUT_MS = _env_positive_int("DB_STATEMENT_TIMEOUT_MS", 5000)

# P2-F3 试点开关：默认关闭，GET /knowledge-categories 继续走现有 SQLite 同步路径。
KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED = _env_bool("KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", False)

# P3-D4 leads/tasks PostgreSQL shadow read 试点：默认全关闭。
LEADS_TASKS_PG_PILOT_ENABLED = _env_bool("LEADS_TASKS_PG_PILOT_ENABLED", False)
LEADS_TASKS_PG_READ_SHADOW_ENABLED = _env_bool("LEADS_TASKS_PG_READ_SHADOW_ENABLED", False)
LEADS_TASKS_PG_WRITE_ENABLED = _env_bool("LEADS_TASKS_PG_WRITE_ENABLED", False)
LEADS_TASKS_PG_STRICT_CONTRAST = _env_bool("LEADS_TASKS_PG_STRICT_CONTRAST", False)
LEADS_TASKS_PG_DATABASE_URL = _env_str("LEADS_TASKS_PG_DATABASE_URL", "")
LEADS_TASKS_PG_POOL_SIZE = _env_positive_int("LEADS_TASKS_PG_POOL_SIZE", 5)
LEADS_TASKS_PG_MAX_OVERFLOW = _env_positive_int("LEADS_TASKS_PG_MAX_OVERFLOW", 5)
LEADS_TASKS_PG_POOL_TIMEOUT = _env_positive_int("LEADS_TASKS_PG_POOL_TIMEOUT", 3)
LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS = _env_positive_int("LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS", 1500)
LEADS_TASKS_PG_SHADOW_TIMEOUT_MS = _env_positive_int("LEADS_TASKS_PG_SHADOW_TIMEOUT_MS", 800)
LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY = _env_nonnegative_int("LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY", 10)
LEADS_TASKS_PG_SHADOW_SAMPLE_RATE = _env_float_range(
    "LEADS_TASKS_PG_SHADOW_SAMPLE_RATE",
    1.0,
    minimum=0.0,
    maximum=1.0,
)

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
DY_OPENAPI_BASE_URL = _env_str("DY_OPENAPI_BASE_URL", "https://gmp.bytedanceapi.com").rstrip("/")
DY_OPENAPI_PREFIX = _env_str("DY_OPENAPI_PREFIX", "/ai_chat_agent_api/v1/openapi")
DY_BASE_URL_LEGACY = _env_str("DY_BASE_URL", "").rstrip("/")
DY_BASE_URL = (DY_BASE_URL_LEGACY or f"{DY_OPENAPI_BASE_URL}{DY_OPENAPI_PREFIX}").rstrip("/")
DY_MAIN_ACCOUNT_ID = int(os.getenv("DY_MAIN_ACCOUNT_ID", "0"))
DY_ACCOUNT_NAME = os.getenv("DY_ACCOUNT_NAME", "")
DY_HTTP_TIMEOUT_SECONDS = int(os.getenv("DY_HTTP_TIMEOUT_SECONDS", "20"))
DY_ALLOWED_DRIFT_SECONDS = int(os.getenv("DY_ALLOWED_DRIFT_SECONDS", "300"))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
DY_LIVE_CHECK_ENABLED = os.getenv("DY_LIVE_CHECK_ENABLED", "false").lower() == "true"
DY_LIVE_CHECK_FORWARD_TO_FORMAL = os.getenv("DY_LIVE_CHECK_FORWARD_TO_FORMAL", "false").lower() == "true"
DOUYIN_RESOURCE_ALLOWED_HOSTS_SET = _env_csv_set("DOUYIN_RESOURCE_ALLOWED_HOSTS")
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
DY_OAUTH_STATE_TTL_SECONDS = int(os.getenv("DY_OAUTH_STATE_TTL_SECONDS", "900"))
# 授权成功后 302 回前端的基址（auth-redirect 同步完成后跳转目标）。
# 必须与 DY_AUTH_REDIRECT_URL（传给上游、由后端 auth-redirect 接收）区分，避免循环。
DY_AUTH_REDIRECT_FRONTEND_URL = os.getenv("DY_AUTH_REDIRECT_FRONTEND_URL", "").strip() or None
DY_AUTH_REDIRECT_ALLOWED_ORIGINS_SET = _env_csv_set("DY_AUTH_REDIRECT_ALLOWED_ORIGINS")

# ---------- NewCarProject 登录权限对接配置 ----------
# P0 默认不强制拦截既有业务接口，mock 仅用于本地开发和测试。
NEWCAR_AUTH_ENABLED = _env_bool("NEWCAR_AUTH_ENABLED", False)
NEWCAR_AUTH_MOCK_ENABLED = _env_bool("NEWCAR_AUTH_MOCK_ENABLED", True)
NEWCAR_AUTH_BASE_URL = os.getenv("NEWCAR_AUTH_BASE_URL", "").strip().rstrip("/")
NEWCAR_AUTH_EXCHANGE_CODE_URL = os.getenv("NEWCAR_AUTH_EXCHANGE_CODE_URL", "").strip()
NEWCAR_AUTH_ME_URL = os.getenv("NEWCAR_AUTH_ME_URL", "").strip()
NEWCAR_AUTH_LOGOUT_URL = os.getenv("NEWCAR_AUTH_LOGOUT_URL", "").strip()
NEWCAR_AUTH_LOGIN_URL = os.getenv("NEWCAR_AUTH_LOGIN_URL", "").strip()
NEWCAR_AUTH_SERVICE_TOKEN = os.getenv("NEWCAR_AUTH_SERVICE_TOKEN", "").strip()
NEWCAR_AUTH_TIMEOUT_SECONDS = int(os.getenv("NEWCAR_AUTH_TIMEOUT_SECONDS", "5"))

# ---------- 9000 调用 9100 抖音AI客服可信代理配置 ----------
XG_DOUYIN_AI_CS_BASE_URL = os.getenv("XG_DOUYIN_AI_CS_BASE_URL", "http://localhost:9100").strip().rstrip("/")
XG_DOUYIN_AI_CS_SERVICE_TOKEN = os.getenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "").strip()
XG_DOUYIN_AI_CS_TIMEOUT_SECONDS = int(os.getenv("XG_DOUYIN_AI_CS_TIMEOUT_SECONDS", "75"))

# ---------- 小高知识库内部训练接口配置 ----------
KNOWLEDGE_TRAINING_IP_WHITELIST = os.getenv(
    "KNOWLEDGE_TRAINING_IP_WHITELIST",
    "127.0.0.1,::1,localhost",
).strip()
KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID = os.getenv(
    "KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID",
    "xiaogao_system",
).strip()
KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID = os.getenv(
    "KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID",
    "xiaogao_base",
).strip()
KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS = (
    os.getenv("KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS", "false").strip().lower() == "true"
)
KNOWLEDGE_TRAINING_INTERNAL_TOKENS = os.getenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", "").strip()

# ---------- 抖音 AI 客服真实自动回复门禁 ----------
# 默认全部关闭；真实发送必须同时打开总开关和真实发送开关，并命中后端白名单。
DOUYIN_AUTO_REPLY_ENABLED = _env_bool("DOUYIN_AUTO_REPLY_ENABLED", False)
DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED = _env_bool("DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", False)
DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT = _env_bool("DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT", False)
DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET = _env_csv_set("DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST")
DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET = _env_csv_set("DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST")
DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET = _env_csv_set("DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST")

# ---------- 9000 调用 9202 AI小高线索 internal webhook 配置 ----------
# 默认关闭，确保正式 webhook 行为与旧链路一致。
LEADS_WEBHOOK_INTERNAL_ENABLED = os.getenv("LEADS_WEBHOOK_INTERNAL_ENABLED", "false").lower() == "true"
LEADS_WEBHOOK_FALLBACK_LOCAL = os.getenv("LEADS_WEBHOOK_FALLBACK_LOCAL", "true").lower() == "true"
LEADS_SERVICE_BASE_URL = os.getenv("LEADS_SERVICE_BASE_URL", "http://127.0.0.1:9202").strip().rstrip("/")
LEADS_INTERNAL_TOKEN = os.getenv("LEADS_INTERNAL_TOKEN", "").strip()
LEADS_CLIENT_TIMEOUT_SECONDS = float(os.getenv("LEADS_CLIENT_TIMEOUT_SECONDS", "5") or 5)

# ---------- Local Agent 机器身份鉴权配置 ----------
# 兼容模式默认关闭强制拦截，避免旧 19000 现场 Agent 掉线。
LOCAL_AGENT_AUTH_REQUIRED = os.getenv("LOCAL_AGENT_AUTH_REQUIRED", "false").lower() == "true"
LOCAL_AGENT_TOKENS = os.getenv("LOCAL_AGENT_TOKENS", "").strip()

# ---------- 历史微信调试接口开关 ----------
# 默认关闭；production 始终关闭。仅本地排查时显式开启。
LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED = (
    os.getenv("LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED", "false").strip().lower() == "true"
)

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
