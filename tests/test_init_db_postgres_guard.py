"""init_db.py PostgreSQL 守卫 focused verification（DB-BL-2D §2 / DBR-9）。

验证：
  - PostgreSQL → init_db 拒绝 create_all（sys.exit(1)，create_all 不被调用）
  - SQLite → 保留既有 create_all 行为

与 tests/test_9000_postgres_runtime_startup.py（ensure_runtime_schema PG skip）对齐，
共同形成 runtime + bootstrap 工具双重 PG create_all 拦截的最小可运行 check。
"""

import importlib.util
import sys
from pathlib import Path


def _load_init_db(monkeypatch):
    """以独立模块名加载 scripts/init_db.py，避免与主进程 app.database 状态耦合。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import app.config as config

    monkeypatch.setattr(config, "DATABASE_URL", "sqlite:///data/auto_wechat.db", raising=False)
    sys.modules.pop("app.database", None)

    spec = importlib.util.spec_from_file_location(
        "init_db_under_test",
        Path(__file__).resolve().parent.parent / "scripts" / "init_db.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeSession:
    """最小 seed 路径替身：query().filter().first() 恒为 None，add/commit/close no-op。"""

    def query(self, _model):
        return self

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return None

    def add(self, _obj):
        pass

    def commit(self):
        pass

    def close(self):
        pass


def test_init_db_refuses_postgresql(monkeypatch):
    init_db = _load_init_db(monkeypatch)

    calls = []
    monkeypatch.setattr(init_db.Base.metadata, "create_all", lambda bind: calls.append(bind))
    monkeypatch.setattr(
        init_db,
        "get_database_runtime",
        lambda: type("R", (), {"backend": "postgresql", "safe_url": "postgresql://u:***@h/db"})(),
    )

    try:
        init_db.init_db()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("PostgreSQL 下 init_db 应 sys.exit(1) 拒绝 create_all")

    # create_all 不应被调用（守卫生效）
    assert calls == []


def test_init_db_allows_sqlite(monkeypatch):
    init_db = _load_init_db(monkeypatch)

    calls = []
    monkeypatch.setattr(init_db.Base.metadata, "create_all", lambda bind: calls.append(bind))
    monkeypatch.setattr(init_db, "SessionLocal", _FakeSession)
    monkeypatch.setattr(
        init_db,
        "get_database_runtime",
        lambda: type("R", (), {"backend": "sqlite", "safe_url": "sqlite:///data/auto_wechat.db"})(),
    )

    init_db.init_db()

    # SQLite 保留既有 create_all 行为
    assert calls == [init_db.engine]
