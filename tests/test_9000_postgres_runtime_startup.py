import sys


def _reload_main(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import app.config as config

    monkeypatch.setattr(config, "DATABASE_URL", "sqlite:///data/auto_wechat.db", raising=False)
    for name in ["app.main", "app.database"]:
        sys.modules.pop(name, None)

    import app.database as database

    monkeypatch.setattr(database.Base.metadata, "create_all", lambda bind: None)

    import app.main as main

    return main


def test_postgresql_runtime_does_not_auto_create_schema(monkeypatch):
    main = _reload_main(monkeypatch)

    calls = []
    monkeypatch.setattr(
        main,
        "get_database_runtime",
        lambda: type("Runtime", (), {"backend": "postgresql", "safe_url": "postgresql://user:***@postgres/auto_wechat"})(),
    )
    monkeypatch.setattr(main.Base.metadata, "create_all", lambda bind: calls.append(bind))

    main.ensure_runtime_schema()

    assert calls == []


def test_sqlite_runtime_keeps_auto_create_schema(monkeypatch):
    main = _reload_main(monkeypatch)

    engine = object()
    calls = []
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(
        main,
        "get_database_runtime",
        lambda: type("Runtime", (), {"backend": "sqlite", "safe_url": "sqlite:///data/auto_wechat.db"})(),
    )
    monkeypatch.setattr(main.Base.metadata, "create_all", lambda bind: calls.append(bind))

    main.ensure_runtime_schema()

    assert calls == [engine]
