from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_WECHAT = ROOT / "migrations" / "postgres" / "auto_wechat"
XG_DOUYIN_AI_CS = ROOT / "migrations" / "postgres" / "xg_douyin_ai_cs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_postgres_alembic_directories_exist():
    assert AUTO_WECHAT.is_dir()
    assert (AUTO_WECHAT / "versions").is_dir()
    assert XG_DOUYIN_AI_CS.is_dir()
    assert (XG_DOUYIN_AI_CS / "versions").is_dir()


def test_postgres_alembic_env_files_exist():
    assert (AUTO_WECHAT / "alembic.ini").is_file()
    assert (AUTO_WECHAT / "env.py").is_file()
    assert (XG_DOUYIN_AI_CS / "alembic.ini").is_file()
    assert (XG_DOUYIN_AI_CS / "env.py").is_file()


def test_empty_baseline_revisions_do_not_create_business_tables_or_indexes():
    for base in [AUTO_WECHAT, XG_DOUYIN_AI_CS]:
        revision = base / "versions" / "0001_empty_baseline.py"
        assert revision.is_file()
        content = _read(revision)
        lowered = content.lower()
        assert "create_table" not in lowered
        assert "drop_table" not in lowered
        assert "create_index" not in lowered
        assert "drop_index" not in lowered
        assert "def upgrade()" in content
        assert "def downgrade()" in content


def test_env_files_use_separate_database_url_environment_variables():
    assert "DATABASE_URL" in _read(AUTO_WECHAT / "env.py")
    assert "RAG_DATABASE_URL" not in _read(AUTO_WECHAT / "env.py")
    assert "RAG_DATABASE_URL" in _read(XG_DOUYIN_AI_CS / "env.py")


def test_env_files_reject_sqlite_and_require_postgresql():
    for env_file in [AUTO_WECHAT / "env.py", XG_DOUYIN_AI_CS / "env.py"]:
        content = _read(env_file)
        assert "sqlite" in content.lower()
        assert "PostgreSQL migration 目标必须使用 PostgreSQL URL" in content


def test_skeleton_files_do_not_contain_real_secrets_or_fixed_database_uri():
    forbidden = [
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "Bearer ",
        "postgresql://",
        "postgresql+asyncpg://",
        "mysql://",
        "mongodb://",
    ]
    files = [
        AUTO_WECHAT / "alembic.ini",
        AUTO_WECHAT / "env.py",
        AUTO_WECHAT / "versions" / "0001_empty_baseline.py",
        XG_DOUYIN_AI_CS / "alembic.ini",
        XG_DOUYIN_AI_CS / "env.py",
        XG_DOUYIN_AI_CS / "versions" / "0001_empty_baseline.py",
    ]
    for path in files:
        content = _read(path)
        for item in forbidden:
            assert item not in content
