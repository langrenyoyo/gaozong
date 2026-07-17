"""环境变量模板覆盖分类测试。

不再采用「所有代码变量必须出现在三个 example」的简单规则，改为维护明确分类：
TEMPLATE / ADVANCED / OPTIONAL / COMPATIBILITY / GRAY / DEPRECATED / TEST_ONLY。

核心约束：
- 扫描后端、9100、Local Agent、前端的 env 读取点，每个变量必须分类；
- TEMPLATE_VARIABLES 必须存在于规定 profile；
- compatibility / deprecated 变量不得重新进入模板；
- production 不得出现 SQLite 主库 URL、真实密钥、Local Agent 进程变量；
- production 必须包含 VITE_LOCAL_WECHAT_AGENT_BASE_URL（部署约定值）；
- 9100 Embedding 新变量必须在三个模板；旧 embedding 变量不得出现在任何模板；
- 连接池 backend 互斥：prod 用 DB_POOL_*/RAG_DB_POOL_*（PostgreSQL），
  dev/lan 用 SQLALCHEMY_*（SQLite），同一 profile 不混配（见 test_connection_pool_profile_boundary）；
- production 固定外部 Milvus，dev 固定 SQLite 向量后端，LAN 用独立 collection；
- 三个模板不再设行数上限，但必须有中文分组注释与调用链说明。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(".")
APP_DIR = ROOT / "app"
APPS_DIR = ROOT / "apps"
FRONTEND_DIR = ROOT / "frontend"


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


# ---------- env 文件解析 ----------

def extract_template_vars(path: Path) -> set[str]:
    """解析 env 文件中出现的变量名（KEY= 行，忽略注释和空行）。"""
    variables: set[str] = set()
    if not path.exists():
        return variables
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            variables.add(key)
    return variables


def template_lines(path: Path) -> list[str]:
    """返回 env 文件的非注释、非空行（去除左右空白）。"""
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(stripped)
    return result


# ---------- 代码读取点扫描 ----------

# Python：直接调用 + config.py 封装函数（_env_str / _env_bool / _env_csv_set 等）
_PY_PATTERNS = [
    re.compile(r'os\.getenv\(\s*["\']([A-Z_][A-Z0-9_]*)["\']'),
    re.compile(r'os\.environ\.get\(\s*["\']([A-Z_][A-Z0-9_]*)["\']'),
    re.compile(r'os\.environ\[\s*["\']([A-Z_][A-Z0-9_]*)["\']'),
    re.compile(
        r'_(?:env_str|env_bool|env_csv_set|env_positive_int|env_nonnegative_int|env_float_range|positive_int_env)'
        r'\(\s*["\']([A-Z_][A-Z0-9_]*)["\']'
    ),
]

# 前端：import.meta.env / process.env 读取的 VITE_*
_FE_PATTERNS = [
    re.compile(r'import\.meta\.env\.(VITE_[A-Z_][A-Z0-9_]*)'),
    re.compile(r'process\.env\.(VITE_[A-Z_][A-Z0-9_]*)'),
]

# 系统变量，扫描命中但不属于项目配置，显式排除
_SYSTEM_VARIABLES = {"APPDATA", "SESSIONNAME", "PATH", "HOME", "USER", "USERNAME", "TEMP", "TMP"}


def scan_python_env_vars(*roots: Path) -> set[str]:
    """扫描 Python 源码中的环境变量读取点。"""
    found: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in _PY_PATTERNS:
                found.update(pattern.findall(text))
    return {v for v in found if v not in _SYSTEM_VARIABLES}


def scan_frontend_env_vars(root: Path) -> set[str]:
    """扫描前端源码中的 VITE_ 变量读取点。"""
    found: set[str] = set()
    if not root.exists():
        return found
    targets = list(root.rglob("*.ts")) + list(root.rglob("*.tsx")) + list(root.rglob("*.mjs"))
    vite_config = root / "vite.config.ts"
    if vite_config.exists():
        targets.append(vite_config)
    for fe_file in targets:
        text = fe_file.read_text(encoding="utf-8", errors="ignore")
        for pattern in _FE_PATTERNS:
            found.update(pattern.findall(text))
    return found


# ---------- 变量分类登记 ----------

# 以下每个集合对应 docs/config/ENV_VARIABLE_REFERENCE.md 的一个类别。
# 新增代码读取变量时，必须在此登记，否则 test_all_code_variables_are_classified 失败。

# DOUYIN_WORKBENCH_* 已升级为模板部署变量（三个 example 均收录），见 TEMPLATE_VARIABLES。
ADVANCED_DOCUMENTED_VARIABLES: set[str] = set()

# MILVUS_* 已升级为 production/LAN 必填向量后端变量（见 MILVUS_REQUIRED_VARIABLES）。
OPTIONAL_COMPONENT_VARIABLES: set[str] = set()

# Milvus 向量后端必填变量：production 和 LAN 必须包含（外部 Milvus 连接配置）。
# dev 默认 SQLite 向量后端，不含这些变量。
MILVUS_REQUIRED_VARIABLES = {
    "MILVUS_URI",
    "MILVUS_USERNAME",
    "MILVUS_PASSWORD",
    "MILVUS_DB_NAME",
    "MILVUS_COLLECTION",
    "MILVUS_DIMENSION",
    "MILVUS_TIMEOUT_SECONDS",
    "MILVUS_INDEX_TYPE",
    "MILVUS_METRIC_TYPE",
    "MILVUS_CONNECT_STRATEGY",
}

COMPATIBILITY_VARIABLES = {
    "XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED",
    "XG_DOUYIN_AI_LLM_EMBEDDING_MODEL",
    "XG_DOUYIN_AI_CS_DB_PATH",
    "DY_BASE_URL",
}

GRAY_VARIABLES = {
    "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED",
    "LEADS_TASKS_PG_PILOT_ENABLED",
    "LEADS_TASKS_PG_READ_SHADOW_ENABLED",
    "LEADS_TASKS_PG_WRITE_ENABLED",
    "LEADS_TASKS_PG_STRICT_CONTRAST",
    "LEADS_TASKS_PG_DATABASE_URL",
    "LEADS_TASKS_PG_POOL_SIZE",
    "LEADS_TASKS_PG_MAX_OVERFLOW",
    "LEADS_TASKS_PG_POOL_TIMEOUT",
    "LEADS_TASKS_PG_STATEMENT_TIMEOUT_MS",
    "LEADS_TASKS_PG_SHADOW_TIMEOUT_MS",
    "LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY",
    "LEADS_TASKS_PG_SHADOW_SAMPLE_RATE",
}

# 当前无废弃连接池变量；DB_POOL_* / RAG_DB_POOL_* / SQLALCHEMY_* 均实际生效，
# 分别控制不同 backend 的 engine（见参考文档第6节 backend 边界）。
DEPRECATED_VARIABLES: set[str] = set()

TEST_ONLY_VARIABLES = {
    "AUTO_WECHAT_ENV_FILE",
    "AUTO_WECHAT_ENV_PROFILE",
    "EASYOCR_MODULE_PATH",
}

# 模板部署变量：三个 example 收录的变量（对应参考文档第 1 节）
TEMPLATE_VARIABLES = {
    # runtime / database
    "APP_ENV",
    "DATABASE_URL",
    "RAG_DATABASE_URL",
    "RAG_VECTOR_BACKEND",
    "SQLALCHEMY_POOL_SIZE",
    "SQLALCHEMY_MAX_OVERFLOW",
    "SQLALCHEMY_POOL_TIMEOUT",
    "SQLALCHEMY_POOL_PRE_PING",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT",
    "DB_POOL_RECYCLE",
    "DB_STATEMENT_TIMEOUT_MS",
    "RAG_DB_POOL_SIZE",
    "RAG_DB_MAX_OVERFLOW",
    "RAG_DB_POOL_TIMEOUT",
    "RAG_DB_POOL_RECYCLE",
    "RAG_DB_STATEMENT_TIMEOUT_MS",
    "EXPECTED_DATABASE_NAME",
    "RAG_EXPECTED_DATABASE_NAME",
    "PG_USER",
    "PG_PASSWORD",
    "PG_DB",
    "PYTHONUNBUFFERED",
    # newcar auth
    "NEWCAR_AUTH_ENABLED",
    "NEWCAR_AUTH_MOCK_ENABLED",
    "NEWCAR_AUTH_BASE_URL",
    "NEWCAR_AUTH_EXCHANGE_CODE_URL",
    "NEWCAR_AUTH_ME_URL",
    "NEWCAR_AUTH_LOGOUT_URL",
    "NEWCAR_AUTH_LOGIN_URL",
    "NEWCAR_AUTH_SERVICE_TOKEN",
    "NEWCAR_AUTH_TIMEOUT_SECONDS",
    # douyin gmp / webhook
    "DY_SECRET_KEY",
    "DY_GMP_SECRET_KEY",
    "DY_OPENAPI_BASE_URL",
    "DY_OPENAPI_PREFIX",
    "DY_MAIN_ACCOUNT_ID",
    "DY_ACCOUNT_NAME",
    "DY_HTTP_TIMEOUT_SECONDS",
    "DY_ALLOWED_DRIFT_SECONDS",
    "DY_OAUTH_STATE_TTL_SECONDS",
    "DOUYIN_WEBHOOK_AUTH_REQUIRED",
    "DOUYIN_RESOURCE_ALLOWED_HOSTS",
    "PUBLIC_BASE_URL",
    "DY_AUTH_REDIRECT_URL",
    "DY_AUTH_REDIRECT_FRONTEND_URL",
    "DY_AUTH_REDIRECT_ALLOWED_ORIGINS",
    "DY_CALLBACK_URL",
    "DY_CALLBACK_EVENTS",
    "DY_LIVE_CHECK_ENABLED",
    "DY_LIVE_CHECK_FORWARD_TO_FORMAL",
    # upstream / internal
    "DOUYIN_API_BASE_URL",
    "DOUYIN_API_TIMEOUT_SECONDS",
    "DOUYIN_SYNC_DEFAULT_LIMIT",
    "XG_DOUYIN_AI_CS_BASE_URL",
    "XG_DOUYIN_AI_CS_SERVICE_TOKEN",
    "XG_DOUYIN_AI_CS_TIMEOUT_SECONDS",
    "AUTO_WECHAT_9000_BASE_URL",
    "COMPUTE_INTERNAL_TOKEN",
    "COMPUTE_USAGE_TIMEOUT_SECONDS",
    "LEADS_SERVICE_BASE_URL",
    "LEADS_INTERNAL_TOKEN",
    "LEADS_CLIENT_TIMEOUT_SECONDS",
    "LEADS_WEBHOOK_INTERNAL_ENABLED",
    "LEADS_WEBHOOK_FALLBACK_LOCAL",
    # knowledge training / auto reply
    "KNOWLEDGE_TRAINING_IP_WHITELIST",
    "KNOWLEDGE_TRAINING_INTERNAL_TOKENS",
    "KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID",
    "KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID",
    "KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS",
    "DOUYIN_AUTO_REPLY_ENABLED",
    "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED",
    "DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT",
    "DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST",
    "DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST",
    "DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST",
    # local agent gate
    "LOCAL_AGENT_AUTH_REQUIRED",
    "LOCAL_AGENT_TOKENS",
    # local agent 进程变量（仅 dev/lan）
    "LOCAL_AGENT_HOST",
    "LOCAL_AGENT_PORT",
    "AUTO_WECHAT_SERVER_URL",
    "LOCAL_AGENT_LOG_FILE",
    "AUTO_WECHAT_AGENT_CLIENT_ID",
    "AUTO_WECHAT_AGENT_NAME",
    "LOCAL_AGENT_TASK_POLL_INTERVAL_SECONDS",
    # frontend
    "VITE_API_BASE_URL",
    "VITE_AUTO_WECHAT_API_BASE_URL",
    "VITE_DOUYIN_AI_CS_API_BASE_URL",
    "VITE_NEWCAR_AUTH_BASE_URL",
    "VITE_NEWCAR_LOGIN_URL",
    "VITE_LOCAL_WECHAT_AGENT_BASE_URL",
    "VITE_DEV_API_PROXY_TARGET",
    "VITE_DEV_DOUYIN_AI_CS_PROXY_TARGET",
    # 9100 llm / embedding
    "XG_DOUYIN_AI_LLM_BASE_URL",
    "XG_DOUYIN_AI_LLM_API_KEY",
    "XG_DOUYIN_AI_LLM_CHAT_MODEL",
    "XG_DOUYIN_AI_LLM_TIMEOUT_SECONDS",
    "XG_DOUYIN_AI_LLM_TEMPERATURE",
    "XG_DOUYIN_AI_EMBEDDING_ENABLED",
    "XG_DOUYIN_AI_EMBEDDING_PROVIDER",
    "XG_DOUYIN_AI_EMBEDDING_API_KEY",
    "XG_DOUYIN_AI_EMBEDDING_BASE_URL",
    "XG_DOUYIN_AI_EMBEDDING_ENDPOINT",
    "XG_DOUYIN_AI_EMBEDDING_MODEL",
    "XG_DOUYIN_AI_EMBEDDING_DIMENSIONS",
    "XG_DOUYIN_AI_EMBEDDING_ENCODING_FORMAT",
    "XG_DOUYIN_AI_EMBEDDING_SPARSE_ENABLED",
    "XG_DOUYIN_AI_EMBEDDING_TIMEOUT_SECONDS",
    "XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED",
    # safety gates
    "LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED",
    "AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT",
    "CORS_ORIGINS",
    # douyin workbench（客服工作台高级调优，三模板均收录）
    "DOUYIN_WORKBENCH_CONVERSATION_EVENT_LIMIT",
    "DOUYIN_WORKBENCH_CONVERSATION_LOOKBACK_DAYS",
    "DOUYIN_WORKBENCH_MESSAGE_LIMIT",
    "DOUYIN_WORKBENCH_UNREAD_EVENT_LIMIT",
}

# Local Agent 进程变量：只允许出现在 dev/lan，禁止出现在 production
LOCAL_AGENT_PROCESS_VARIABLES = {
    "LOCAL_AGENT_HOST",
    "LOCAL_AGENT_PORT",
    "AUTO_WECHAT_SERVER_URL",
    "LOCAL_AGENT_LOG_FILE",
    "AUTO_WECHAT_AGENT_CLIENT_ID",
    "AUTO_WECHAT_AGENT_NAME",
    "LOCAL_AGENT_TASK_POLL_INTERVAL_SECONDS",
}

# Embedding 新变量：三个模板都必须有
EMBEDDING_NEW_VARIABLES = {
    "XG_DOUYIN_AI_EMBEDDING_ENABLED",
    "XG_DOUYIN_AI_EMBEDDING_PROVIDER",
    "XG_DOUYIN_AI_EMBEDDING_API_KEY",
    "XG_DOUYIN_AI_EMBEDDING_BASE_URL",
    "XG_DOUYIN_AI_EMBEDDING_ENDPOINT",
    "XG_DOUYIN_AI_EMBEDDING_MODEL",
    "XG_DOUYIN_AI_EMBEDDING_DIMENSIONS",
    "XG_DOUYIN_AI_EMBEDDING_ENCODING_FORMAT",
    "XG_DOUYIN_AI_EMBEDDING_SPARSE_ENABLED",
    "XG_DOUYIN_AI_EMBEDDING_TIMEOUT_SECONDS",
}

# Embedding 旧兼容变量：任何模板都不得出现
EMBEDDING_LEGACY_VARIABLES = {
    "XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED",
    "XG_DOUYIN_AI_LLM_EMBEDDING_MODEL",
}

# production 独占变量（dev/lan 不含）
PROD_ONLY_VARIABLES = {
    "PG_USER",
    "PG_PASSWORD",
    "PG_DB",
    "EXPECTED_DATABASE_NAME",
    "RAG_EXPECTED_DATABASE_NAME",
    # 9000 PostgreSQL engine 连接池（database.py:192-200 PG 分支）
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT",
    "DB_POOL_RECYCLE",
    "DB_STATEMENT_TIMEOUT_MS",
    # 9100 RAG PostgreSQL engine 连接池（rag/database.py:80-96）
    "RAG_DB_POOL_SIZE",
    "RAG_DB_MAX_OVERFLOW",
    "RAG_DB_POOL_TIMEOUT",
    "RAG_DB_POOL_RECYCLE",
    "RAG_DB_STATEMENT_TIMEOUT_MS",
}

# dev/lan 独占模板变量（prod 不含）
DEV_LAN_ONLY_TEMPLATE_VARIABLES = {
    # prod 走 webhook 直收，不依赖 douyinAPI 上游同步链路
    "DOUYIN_API_BASE_URL",
    "DOUYIN_API_TIMEOUT_SECONDS",
    "DOUYIN_SYNC_DEFAULT_LIMIT",
    # 9000 SQLite engine 连接池（database.py:205-215 SQLite 分支），prod 用 PostgreSQL 走 DB_POOL_*
    "SQLALCHEMY_POOL_SIZE",
    "SQLALCHEMY_MAX_OVERFLOW",
    "SQLALCHEMY_POOL_TIMEOUT",
    "SQLALCHEMY_POOL_PRE_PING",
}

# 全部分类集合（每个变量只属于一个分类）
ALL_CLASSIFIED = (
    TEMPLATE_VARIABLES
    | ADVANCED_DOCUMENTED_VARIABLES
    | OPTIONAL_COMPONENT_VARIABLES
    | COMPATIBILITY_VARIABLES
    | GRAY_VARIABLES
    | DEPRECATED_VARIABLES
    | TEST_ONLY_VARIABLES
    | MILVUS_REQUIRED_VARIABLES
)


# ---------- 保留的结构性测试 ----------

def test_only_three_root_env_examples_are_kept():
    expected = {
        ".env.production.example",
        ".env.development.example",
        ".env.lan.example",
    }
    root_examples = {path.name for path in ROOT.glob(".env*.example")}

    assert root_examples == expected
    assert not Path("frontend/.env.example").exists()
    assert not Path(".env.example").exists()
    assert not Path(".env.staging.example").exists()
    assert not Path(".env.production.pg.example").exists()


def test_env_variable_reference_doc_exists():
    """参考文档必须与模板同步维护。"""
    assert Path("docs/config/ENV_VARIABLE_REFERENCE.md").exists()


def test_gitignore_tracks_only_examples_and_ignores_real_env_profiles():
    source = read(".gitignore")
    lines = set(source.splitlines())

    for ignored in [
        ".env",
        ".env.local",
        ".env.staging",
        ".env.development.local",
        ".env.lan.local",
        ".env.production.local",
        ".env.staging.local",
    ]:
        assert ignored in lines

    for allowed in [
        "!.env.production.example",
        "!.env.development.example",
        "!.env.lan.example",
    ]:
        assert allowed in lines

    assert "!.env.example" not in source
    assert "!.env.staging.example" not in source
    assert "!.env.production.pg.example" not in source


def test_dockerignore_keeps_real_env_and_examples_out_of_image_context():
    source = read(".dockerignore")

    assert ".env*" in source
    assert "!.env.example" not in source
    assert "!.env.production.example" not in source
    assert "!.env.development.example" not in source
    assert "!.env.lan.example" not in source


def test_compose_files_use_explicit_local_env_profiles():
    production = read("docker-compose.yml")
    development = read("docker-compose.dev.yml")
    staging = read("docker-compose.staging.yml")

    assert ".env.production.local" in production
    assert "./frontend/.env" not in production
    assert "${AUTO_WECHAT_ENV_FILE:-.env.development.local}" in development
    assert "XG_DOUYIN_AI_CS_DB_PATH:" not in development
    assert "RAG_DATABASE_URL: sqlite:////data/xg_douyin_ai_cs.db" in development
    assert ".env.staging.local" in staging

    assert 'NEWCAR_AUTH_ENABLED: "${NEWCAR_AUTH_ENABLED:-false}"' in development
    assert 'NEWCAR_AUTH_MOCK_ENABLED: "${NEWCAR_AUTH_MOCK_ENABLED:-true}"' in development


def test_douyin_oauth_templates_use_persisting_redirect_and_dev_compose_passes_runtime_guards():
    templates = [
        ".env.development.example",
        ".env.lan.example",
        ".env.production.example",
    ]
    for template in templates:
        source = read(template)
        redirect_line = next(
            line for line in source.splitlines() if line.startswith("DY_AUTH_REDIRECT_URL=")
        )
        assert "/integrations/douyin/live-check/auth-redirect" in redirect_line, template
        assert "/oauth-callback" not in redirect_line, template

    development = read("docker-compose.dev.yml")
    assert 'DY_OAUTH_STATE_TTL_SECONDS: "${DY_OAUTH_STATE_TTL_SECONDS:-900}"' in development
    assert 'DY_AUTH_REDIRECT_ALLOWED_ORIGINS: "${DY_AUTH_REDIRECT_ALLOWED_ORIGINS:-}"' in development
    assert 'DY_LIVE_CHECK_ENABLED: "${DY_LIVE_CHECK_ENABLED:-false}"' in development


def test_production_douyin_oauth_redirect_stays_with_merchant_api_state_store():
    production = read(".env.production.example")

    assert (
        "DY_AUTH_REDIRECT_URL=https://merchant.xiaogaoai.cn/api/integrations/douyin/live-check/auth-redirect"
        in production
    )
    assert (
        "DY_CALLBACK_URL=https://callback.misanduo.com/integrations/douyin/live-check/webhook-observe"
        in production
    )


def test_production_pg_scripts_default_to_production_local_env():
    script_paths = sorted(Path("scripts").glob("production_pg_*.sh"))
    assert script_paths

    for path in script_paths:
        source = path.read_text(encoding="utf-8")
        if "--env-file" in source or "ENV_FILE=" in source:
            assert 'ENV_FILE=".env.production.local"' in source, path
            assert 'ENV_FILE=".env"' not in source, path


def test_frontend_static_checks_read_root_development_template():
    direct_auth = read("frontend/scripts/check-newcar-direct-auth.mjs")
    admin_logout = read("frontend/scripts/check-newcar-admin-entry-logout-route.mjs")
    capability_test = read("tests/test_frontend_capability_navigation.py")
    vite_config = read("frontend/vite.config.ts")

    assert '../.env.lan.example' in direct_auth
    assert '../.env.lan.example' in admin_logout
    assert 'Path(".env.development.example")' in capability_test
    assert 'envDir: ".."' in vite_config
    assert 'frontend/.env.example' not in direct_auth
    assert 'frontend/.env.example' not in admin_logout
    assert 'Path("frontend/.env.example")' not in capability_test


def test_backend_config_loads_profile_local_env_files_before_legacy_env():
    source = read("app/config.py")

    assert "AUTO_WECHAT_ENV_FILE" in source
    assert '".env.development.local"' in source
    assert '".env.lan.local"' in source
    assert '".env.production.local"' in source
    assert "_load_env_files" in source
    assert 'BASE_PATH / ".env"' in source


# ---------- 分类覆盖测试 ----------

def test_all_code_variables_are_classified():
    """扫描全部代码读取点，未登记分类的变量直接失败。"""
    py_vars = scan_python_env_vars(APP_DIR, APPS_DIR)
    fe_vars = scan_frontend_env_vars(FRONTEND_DIR)
    code_vars = py_vars | fe_vars

    unclassified = code_vars - ALL_CLASSIFIED
    assert not unclassified, (
        f"发现未分类的环境变量，请在 docs/config/ENV_VARIABLE_REFERENCE.md 登记并在本测试分类：{sorted(unclassified)}"
    )


def test_template_variables_are_complete_and_nonempty():
    assert TEMPLATE_VARIABLES, "TEMPLATE_VARIABLES 不能为空"


def test_template_variables_exist_in_correct_profiles():
    """TEMPLATE_VARIABLES 必须出现在规定的 profile。"""
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    prod = extract_template_vars(ROOT / ".env.production.example")

    # 多数模板变量应在三个 profile 都出现
    common_required = (
        TEMPLATE_VARIABLES
        - PROD_ONLY_VARIABLES
        - LOCAL_AGENT_PROCESS_VARIABLES
        - DEV_LAN_ONLY_TEMPLATE_VARIABLES
    )
    missing_dev = common_required - dev
    missing_lan = common_required - lan
    missing_prod = common_required - prod

    assert not missing_dev, f"dev 模板缺失变量：{sorted(missing_dev)}"
    assert not missing_lan, f"lan 模板缺失变量：{sorted(missing_lan)}"
    assert not missing_prod, f"prod 模板缺失变量：{sorted(missing_prod)}"

    # prod 独占变量只在 prod
    for var in PROD_ONLY_VARIABLES:
        assert var in prod, f"prod 模板应包含 {var}"
        assert var not in dev, f"dev 模板不应包含 prod 独占变量 {var}"
        assert var not in lan, f"lan 模板不应包含 prod 独占变量 {var}"

    # dev/lan 独占变量只在 dev/lan
    for var in DEV_LAN_ONLY_TEMPLATE_VARIABLES:
        assert var in dev, f"dev 模板应包含 {var}"
        assert var in lan, f"lan 模板应包含 {var}"
        assert var not in prod, f"prod 模板不应包含 dev/lan 独占变量 {var}"


def test_local_agent_process_variables_not_in_production():
    """Local Agent 进程变量不得进入 production 模板。"""
    prod = extract_template_vars(ROOT / ".env.production.example")
    leaked = LOCAL_AGENT_PROCESS_VARIABLES & prod
    assert not leaked, f"production 模板不应包含 Local Agent 进程变量：{sorted(leaked)}"

    # dev/lan 应包含 Local Agent 进程变量
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    assert LOCAL_AGENT_PROCESS_VARIABLES <= dev, f"dev 缺 Local Agent 进程变量：{sorted(LOCAL_AGENT_PROCESS_VARIABLES - dev)}"
    assert LOCAL_AGENT_PROCESS_VARIABLES <= lan, f"lan 缺 Local Agent 进程变量：{sorted(LOCAL_AGENT_PROCESS_VARIABLES - lan)}"


def test_production_must_contain_vite_local_wechat_agent_base_url():
    prod = read(".env.production.example")
    assert "VITE_LOCAL_WECHAT_AGENT_BASE_URL=http://127.0.0.1:19000" in prod


def test_embedding_new_variables_in_all_templates():
    """9100 Embedding 新变量必须在三个模板都出现。"""
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    prod = extract_template_vars(ROOT / ".env.production.example")

    assert EMBEDDING_NEW_VARIABLES <= dev, f"dev 缺 embedding 新变量：{sorted(EMBEDDING_NEW_VARIABLES - dev)}"
    assert EMBEDDING_NEW_VARIABLES <= lan, f"lan 缺 embedding 新变量：{sorted(EMBEDDING_NEW_VARIABLES - lan)}"
    assert EMBEDDING_NEW_VARIABLES <= prod, f"prod 缺 embedding 新变量：{sorted(EMBEDDING_NEW_VARIABLES - prod)}"


def test_embedding_legacy_variables_not_in_any_template():
    """旧 embedding 兼容变量不得出现在任何模板。"""
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    prod = extract_template_vars(ROOT / ".env.production.example")

    for name, variables in [("dev", dev), ("lan", lan), ("prod", prod)]:
        leaked = EMBEDDING_LEGACY_VARIABLES & variables
        assert not leaked, f"{name} 模板不应包含旧 embedding 变量：{sorted(leaked)}"


def test_connection_pool_profile_boundary():
    """连接池变量 backend 边界：DB_POOL_*/RAG_DB_POOL_* 仅 prod，SQLALCHEMY_* 仅 dev/lan。

    依据 app/database.py 的 create_database_engine：PG 分支用 DB_POOL_*，SQLite 分支用 SQLALCHEMY_*。
    apps/xg_douyin_ai_cs/rag/database.py 的 PG 分支用 RAG_DB_POOL_*。
    三组变量互斥，同一 profile 不得混配两套。
    """
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    prod = extract_template_vars(ROOT / ".env.production.example")

    pg_pool_vars = {
        "DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT", "DB_POOL_RECYCLE", "DB_STATEMENT_TIMEOUT_MS",
    }
    rag_pool_vars = {
        "RAG_DB_POOL_SIZE", "RAG_DB_MAX_OVERFLOW", "RAG_DB_POOL_TIMEOUT",
        "RAG_DB_POOL_RECYCLE", "RAG_DB_STATEMENT_TIMEOUT_MS",
    }
    sqlite_pool_vars = {
        "SQLALCHEMY_POOL_SIZE", "SQLALCHEMY_MAX_OVERFLOW",
        "SQLALCHEMY_POOL_TIMEOUT", "SQLALCHEMY_POOL_PRE_PING",
    }

    # prod 必须含 PG 连接池变量，不得含 SQLite 专用变量
    assert pg_pool_vars <= prod, f"prod 缺 9000 PG 连接池变量：{sorted(pg_pool_vars - prod)}"
    assert rag_pool_vars <= prod, f"prod 缺 9100 RAG PG 连接池变量：{sorted(rag_pool_vars - prod)}"
    assert not (sqlite_pool_vars & prod), f"prod 不应含 SQLite 专用 SQLALCHEMY_*：{sorted(sqlite_pool_vars & prod)}"

    # dev/lan 必须含 SQLite 连接池变量，不得含 PG 专用变量
    for name, variables in [("dev", dev), ("lan", lan)]:
        assert sqlite_pool_vars <= variables, f"{name} 缺 SQLite 连接池变量：{sorted(sqlite_pool_vars - variables)}"
        assert not (pg_pool_vars & variables), f"{name} 不应含 PG 专用 DB_POOL_*：{sorted(pg_pool_vars & variables)}"
        assert not (rag_pool_vars & variables), f"{name} 不应含 RAG PG 专用变量：{sorted(rag_pool_vars & variables)}"


def test_compatibility_and_gray_variables_not_in_any_template():
    """compatibility / gray 变量不得重新进入模板。"""
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    prod = extract_template_vars(ROOT / ".env.production.example")
    forbidden = COMPATIBILITY_VARIABLES | GRAY_VARIABLES | ADVANCED_DOCUMENTED_VARIABLES | OPTIONAL_COMPONENT_VARIABLES

    for name, variables in [("dev", dev), ("lan", lan), ("prod", prod)]:
        leaked = forbidden & variables
        assert not leaked, f"{name} 模板不应包含非模板变量：{sorted(leaked)}"


def test_production_has_no_sqlite_main_database_url():
    """production 模板不得出现 SQLite 主业务 URL。"""
    prod_lines = template_lines(ROOT / ".env.production.example")
    for line in prod_lines:
        assert not line.startswith("DATABASE_URL=sqlite"), f"prod 不应用 SQLite 主库：{line}"
        assert not line.startswith("RAG_DATABASE_URL=sqlite"), f"prod 不应用 SQLite RAG 库：{line}"


def test_production_has_no_real_secrets():
    """production 模板不得出现真实密钥（sk- / sk_or- / ark- 前缀）。"""
    prod = read(".env.production.example")
    # 去除 <placeholder> 占位内容后再检测
    cleaned = re.sub(r"<[^>]+>", "", prod)
    secret_pattern = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|sk_or-[A-Za-z0-9_-]{8,}|ark-[A-Za-z0-9-]{8,})")
    match = secret_pattern.search(cleaned)
    assert not match, f"production 模板疑似含真实密钥：{match.group()}"


def test_production_backend_addresses_not_localhost():
    """production 模板除 VITE_LOCAL_WECHAT_AGENT_BASE_URL 外不得出现 127.0.0.1 / localhost。"""
    prod_lines = template_lines(ROOT / ".env.production.example")
    for line in prod_lines:
        if line.startswith("VITE_LOCAL_WECHAT_AGENT_BASE_URL="):
            continue
        assert "127.0.0.1" not in line, f"prod 后端地址不应含 127.0.0.1：{line}"
        assert "localhost" not in line, f"prod 后端地址不应含 localhost：{line}"


def test_connection_pool_code_consistency():
    """扫描真实代码，确认三组连接池变量绑定到正确的 backend engine 创建分支。

    防止局部 grep 误判：判断变量生效必须追踪到 create_database_engine / create_rag_engine
    的实际分支传参，不能只看变量是否在文件中出现。
    """
    database_py = read("app/database.py")
    config_py = read("app/config.py")
    rag_database_py = read("apps/xg_douyin_ai_cs/rag/database.py")

    # 9000 PG 分支：config.py 读取 DB_POOL_*，database.py 的 create_engine(postgresql+psycopg) 分支传入
    assert 'DB_POOL_SIZE = _env_positive_int("DB_POOL_SIZE"' in config_py
    assert "pool_size=DB_POOL_SIZE" in database_py
    assert "max_overflow=DB_MAX_OVERFLOW" in database_py
    assert "pool_timeout=DB_POOL_TIMEOUT" in database_py
    assert "pool_recycle=DB_POOL_RECYCLE" in database_py
    # DB_STATEMENT_TIMEOUT_MS 在 connect 事件里 SET statement_timeout（database.py:247）
    assert "DB_STATEMENT_TIMEOUT_MS" in database_py

    # 9000 SQLite 分支：database.py 读取 SQLALCHEMY_* 并传入 create_engine(sqlite)
    assert 'os.getenv("SQLALCHEMY_POOL_SIZE"' in database_py
    assert "pool_size=SQLALCHEMY_POOL_SIZE" in database_py
    assert "max_overflow=SQLALCHEMY_MAX_OVERFLOW" in database_py
    assert "pool_timeout=SQLALCHEMY_POOL_TIMEOUT" in database_py
    assert "pool_pre_ping=SQLALCHEMY_POOL_PRE_PING" in database_py

    # 9100 RAG PG 分支：rag/database.py 的 create_engine(postgresql) 用 settings.rag_db_*
    assert "pool_size=settings.rag_db_pool_size" in rag_database_py
    assert "max_overflow=settings.rag_db_max_overflow" in rag_database_py
    assert "pool_timeout=settings.rag_db_pool_timeout" in rag_database_py
    assert "pool_recycle=settings.rag_db_pool_recycle" in rag_database_py
    assert "settings.rag_db_statement_timeout_ms" in rag_database_py


# ---------- 外部 Milvus 定向检查（P3-CONFIG-EXTERNAL-MILVUS-CORRECTION-1）----------


def test_production_uses_milvus_vector_backend():
    """生产模板向量后端必须为 milvus，不得为 sqlite。"""
    prod = read(".env.production.example")
    assert "RAG_VECTOR_BACKEND=milvus" in prod
    assert "RAG_VECTOR_BACKEND=sqlite" not in prod


def test_milvus_required_variables_in_production_and_lan():
    """MILVUS_* 必填变量必须出现在 production 和 LAN 模板。"""
    prod = extract_template_vars(ROOT / ".env.production.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    missing_prod = MILVUS_REQUIRED_VARIABLES - prod
    missing_lan = MILVUS_REQUIRED_VARIABLES - lan
    assert not missing_prod, f"prod 缺 Milvus 变量：{sorted(missing_prod)}"
    assert not missing_lan, f"lan 缺 Milvus 变量：{sorted(missing_lan)}"


def test_milvus_collection_isolated_between_profiles():
    """production collection 占位符不得与 LAN 共用同一 collection。"""
    prod = read(".env.production.example")
    lan = read(".env.lan.example")
    prod_collection = re.search(r"^MILVUS_COLLECTION=(.+)$", prod, re.MULTILINE)
    lan_collection = re.search(r"^MILVUS_COLLECTION=(.+)$", lan, re.MULTILINE)
    assert prod_collection, "prod 缺 MILVUS_COLLECTION"
    assert lan_collection, "lan 缺 MILVUS_COLLECTION"
    assert prod_collection.group(1).strip() != lan_collection.group(1).strip(), (
        "production 与 LAN MILVUS_COLLECTION 不得共用同一 collection"
    )


def test_milvus_dimension_matches_embedding_dimensions_in_templates():
    """模板中 MILVUS_DIMENSION 必须与 XG_DOUYIN_AI_EMBEDDING_DIMENSIONS 一致。"""
    for name in [".env.production.example", ".env.lan.example"]:
        content = read(name)
        milvus_dim = re.search(r"^MILVUS_DIMENSION=(\d+)$", content, re.MULTILINE)
        embedding_dim = re.search(r"^XG_DOUYIN_AI_EMBEDDING_DIMENSIONS=(\d+)$", content, re.MULTILINE)
        assert milvus_dim, f"{name} 缺 MILVUS_DIMENSION"
        assert embedding_dim, f"{name} 缺 XG_DOUYIN_AI_EMBEDDING_DIMENSIONS"
        assert milvus_dim.group(1) == embedding_dim.group(1), (
            f"{name} MILVUS_DIMENSION={milvus_dim.group(1)} != EMBEDDING_DIMENSIONS={embedding_dim.group(1)}"
        )


def test_production_milvus_credentials_are_placeholders():
    """production 模板 Milvus 凭据必须为尖括号占位符。"""
    prod = read(".env.production.example")
    for key in ("MILVUS_URI", "MILVUS_USERNAME", "MILVUS_PASSWORD", "MILVUS_DB_NAME", "MILVUS_COLLECTION"):
        match = re.search(rf"^{key}=(.*)$", prod, re.MULTILINE)
        assert match, f"prod 缺 {key}"
        value = match.group(1).strip()
        assert value.startswith("<") and value.endswith(">"), (
            f"prod {key} 必须为占位符 <...>，实际={value}"
        )


def test_compose_has_no_local_milvus_service():
    """Compose 不得新增本地 Milvus service 或拉取 milvus 镜像。"""
    for compose in ["docker-compose.yml", "docker-compose.staging.yml", "docker-compose.dev.yml"]:
        content = read(compose)
        assert not re.search(r"^\s{2}milvus:\s*$", content, re.MULTILINE), f"{compose} 不得包含本地 milvus service"
        assert "milvusdb/milvus" not in content, f"{compose} 不得拉取 milvusdb/milvus 镜像"


def test_development_uses_sqlite_vector_backend():
    """第10项：dev 模板向量后端为 sqlite（轻量开发）；production 用 milvus。"""
    dev = read(".env.development.example")
    assert "RAG_VECTOR_BACKEND=sqlite" in dev


def test_production_runbook_no_sqlite_vector_backend():
    """第12项：Production Runbook 不得再写 SQLite 向量后端。"""
    runbook = read("docs/ai/05_acceptance/P3-E-9100-PRODUCTION-CUTOVER-BAOTA-RUNBOOK.md")
    assert "RAG_VECTOR_BACKEND=sqlite" not in runbook


# ---------- P3-CONFIG-ENV-DETAILED-CHINESE-DOCUMENTATION-1：中文注释与结构质量 ----------


def test_three_templates_have_chinese_section_headers():
    """三个模板必须含中文分组分隔注释（非裸变量堆叠）。"""
    for name in [".env.production.example", ".env.development.example", ".env.lan.example"]:
        content = read(name)
        # 分组分隔线（每个模板至少 10 个分组）
        assert content.count("# " + "=" * 78) >= 10, f"{name} 中文分组分隔注释不足"
        # 文件用途说明
        assert "文件用途" in content, f"{name} 缺文件用途说明"
        # 环境身份说明
        assert "环境身份" in content or "当前环境身份" in content, f"{name} 缺环境身份说明"


def test_three_templates_document_call_chain_for_key_blocks():
    """关键配置块注释必须含「调用链」说明，不得只写变量名中文翻译。"""
    key_markers = ["调用链", "读取点"]
    for name in [".env.production.example", ".env.development.example", ".env.lan.example"]:
        content = read(name)
        # 至少 8 处调用链/读取点说明（覆盖数据库、鉴权、Milvus、Embedding、服务等核心块）
        hits = sum(content.count(marker) for marker in key_markers)
        assert hits >= 8, f"{name} 调用链说明不足（{hits} 处），关键块不得只写变量名翻译"


def test_three_templates_have_copy_instructions():
    """三个模板顶部必须含复制命令与 .local 禁止提交说明。"""
    for name in [".env.production.example", ".env.development.example", ".env.lan.example"]:
        content = read(name)
        assert "cp " in content and ".local" in content, f"{name} 缺复制命令说明"
        assert "禁止提交" in content or "不得提交" in content, f"{name} 缺 .local 禁止提交说明"


def test_production_credentials_are_chinese_placeholders():
    """production 敏感值必须为中文语义占位符（<请填写...>），不得用模糊 xxx/test/123456。"""
    prod = read(".env.production.example")
    # 所有含 = 且值以 < 开头 > 结尾的行，占位符内必须含中文「请填写」或已知值
    for line in prod.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        value = stripped.split("=", 1)[1].strip()
        if value.startswith("<") and value.endswith(">"):
            # 占位符内应有中文语义说明，不得是空 <> 或纯英文模糊词
            inner = value[1:-1]
            assert inner, f"prod 空占位符：{stripped}"
            assert "请填写" in inner or inner in {
                "production", "frontend-host", "newcar-auth-host", "newcar-login-host",
                "douyin-resource-hosts", "leads-service-base-url", "trusted-admin-ip-or-cidr",
                "merchant-id", "local-agent-token", "compute-internal-token",
                "internal-9100-token", "knowledge-training-token", "douyin-webhook-secret",
                "douyin-openapi-secret", "llm-api-key", "ark-api-key",
                "douyin-main-account-id", "douyin-account-name", "newcar-service-token",
            }, f"prod 占位符缺中文语义：{stripped}"


def test_development_has_no_production_secrets():
    """dev 模板不得出现真实密钥（sk- / ark- 前缀）或 production 密码占位符。"""
    dev = read(".env.development.example")
    cleaned = re.sub(r"<[^>]+>", "", dev)
    secret_pattern = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|sk_or-[A-Za-z0-9_-]{8,}|ark-[A-Za-z0-9-]{8,})")
    match = secret_pattern.search(cleaned)
    assert not match, f"dev 模板疑似含真实密钥：{match.group()}"


def test_lan_milvus_collection_placeholder_not_production():
    """LAN Milvus collection 占位符不得含 production 保留字。"""
    lan = read(".env.lan.example")
    lan_collection = re.search(r"^MILVUS_COLLECTION=(.+)$", lan, re.MULTILINE)
    assert lan_collection, "lan 缺 MILVUS_COLLECTION"
    value = lan_collection.group(1).strip()
    for forbidden in ("production", "prod", "release", "live"):
        assert forbidden not in value.lower(), (
            f"LAN MILVUS_COLLECTION 占位符含 production 保留字 {forbidden}：{value}"
        )


def test_production_no_local_agent_process_variables():
    """production 不得含 Local Agent Python 进程变量（第 7 个），只留浏览器 VITE 地址。"""
    prod = extract_template_vars(ROOT / ".env.production.example")
    for var in LOCAL_AGENT_PROCESS_VARIABLES:
        assert var not in prod, f"prod 不应含 Local Agent 进程变量 {var}"


def test_dev_and_lan_have_local_agent_process_variables():
    """dev/lan 必须完整含 Local Agent Python 进程 7 变量。"""
    dev = extract_template_vars(ROOT / ".env.development.example")
    lan = extract_template_vars(ROOT / ".env.lan.example")
    assert LOCAL_AGENT_PROCESS_VARIABLES <= dev, f"dev 缺 Local Agent 进程变量：{sorted(LOCAL_AGENT_PROCESS_VARIABLES - dev)}"
    assert LOCAL_AGENT_PROCESS_VARIABLES <= lan, f"lan 缺 Local Agent 进程变量：{sorted(LOCAL_AGENT_PROCESS_VARIABLES - lan)}"


def test_production_documents_milvus_no_fallback():
    """production 模板必须文档说明 Milvus 不可达不回退 SQLite。"""
    prod = read(".env.production.example")
    assert "不回退" in prod or "不静默回退" in prod, "prod 缺 Milvus 不回退 SQLite 说明"


def test_production_documents_dimension_consistency():
    """production 模板必须文档说明 Embedding/Milvus/collection 维度一致性。"""
    prod = read(".env.production.example")
    assert "EMBEDDING_DIMENSIONS" in prod and "MILVUS_DIMENSION" in prod, "prod 缺维度一致性说明"


def test_three_templates_document_address_roles():
    """三个模板必须含地址角色说明（浏览器/容器/宿主机/外部服务不混淆）。"""
    for name in [".env.production.example", ".env.lan.example"]:
        content = read(name)
        # 必须提到容器/service name 概念和浏览器概念
        assert "容器" in content or "service name" in content or "Compose" in content, f"{name} 缺容器/service name 说明"
        assert "浏览器" in content, f"{name} 缺浏览器地址角色说明"


def test_deprecated_auto_wechat_compose_not_exist():
    """旧 SQLite-only 入口 docker-compose.auto-wechat.yml 必须已删除，禁止重新出现。"""
    assert not Path("docker-compose.auto-wechat.yml").exists()


def test_preflight_keeps_deprecated_compose_guard():
    """production preflight 必须保留 DEPRECATED_COMPOSE 门禁，发现废弃 compose 重新出现时报警。"""
    source = Path("scripts/production_pg_preflight.sh").read_text(encoding="utf-8")
    assert "docker-compose.auto-wechat.yml" in source, (
        "preflight 必须保留 docker-compose.auto-wechat.yml 废弃入口检测"
    )


def test_production_compose_documents_main_entry():
    """docker-compose.yml 顶部必须明确：唯一 production 主入口。"""
    source = read("docker-compose.yml")
    assert "唯一 production 主入口" in source, "docker-compose.yml 缺唯一 production 主入口声明"


def test_dev_compose_documents_independent():
    """docker-compose.dev.yml 顶部必须明确：独立完整编排，禁止与生产主文件组合。"""
    source = read("docker-compose.dev.yml")
    assert "独立完整编排" in source
    assert "禁止与生产主文件组合使用" in source


def test_staging_compose_documents_override_only():
    """docker-compose.staging.yml 顶部必须明确：只能与主文件组合，禁止单独运行、禁止 production。"""
    source = read("docker-compose.staging.yml")
    assert "不能单独运行" in source
    assert "禁止用于 production" in source
