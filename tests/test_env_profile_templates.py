from pathlib import Path


ROOT = Path(".")


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


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
    legacy = read("docker-compose.auto-wechat.yml")

    assert ".env.production.local" in production
    assert "./frontend/.env" not in production
    assert "${AUTO_WECHAT_ENV_FILE:-.env.development.local}" in development
    assert "XG_DOUYIN_AI_CS_DB_PATH:" not in development
    assert "RAG_DATABASE_URL: sqlite:////data/xg_douyin_ai_cs.db" in development
    assert ".env.staging.local" in staging
    assert "env_file:\n      - .env" not in legacy

    assert 'NEWCAR_AUTH_ENABLED: "${NEWCAR_AUTH_ENABLED:-false}"' in development
    assert 'NEWCAR_AUTH_MOCK_ENABLED: "${NEWCAR_AUTH_MOCK_ENABLED:-true}"' in development


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


def test_templates_have_separate_environment_responsibilities():
    production = read(".env.production.example")
    development = read(".env.development.example")
    lan = read(".env.lan.example")

    assert "APP_ENV=production" in production
    assert "DATABASE_URL=postgresql+psycopg://" in production
    assert "RAG_DATABASE_URL=postgresql+psycopg://" in production
    assert "RAG_VECTOR_BACKEND=sqlite" in production
    assert "NEWCAR_AUTH_ENABLED=true" in production
    assert "NEWCAR_AUTH_MOCK_ENABLED=false" in production
    assert "sqlite:///" not in production.lower()
    assert "localhost" not in production.lower()
    assert "127.0.0.1" not in production
    assert "VITE_XG_DOUYIN_AI_CS_SERVICE_TOKEN" not in production

    assert "APP_ENV=development" in development
    assert "DATABASE_URL=sqlite:///" in development
    assert "RAG_DATABASE_URL=sqlite:///" in development
    assert "XG_DOUYIN_AI_CS_DB_PATH" not in development
    assert "NEWCAR_AUTH_ENABLED=false" in development
    assert "NEWCAR_AUTH_MOCK_ENABLED=true" in development
    assert "PG_PASSWORD" not in development
    assert "production" not in development.lower()

    assert "APP_ENV=development" in lan
    assert "NEWCAR_AUTH_ENABLED=true" in lan
    assert "NEWCAR_AUTH_MOCK_ENABLED=false" in lan
    assert "XG_DOUYIN_AI_CS_DB_PATH" not in lan
    assert "VITE_LOCAL_WECHAT_AGENT_BASE_URL=http://127.0.0.1:19000" in lan
    assert "auto_wechat_staging" not in lan
    assert "xg_douyin_ai_cs_staging" not in lan
    assert "postgresql+psycopg://" not in lan
    assert "production" not in lan.lower()
