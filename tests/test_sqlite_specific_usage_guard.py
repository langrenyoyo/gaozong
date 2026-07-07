from pathlib import Path

from scripts import check_sqlite_specific_usage as guard


def test_guard_reports_core_sqlite_only_usage(tmp_path: Path) -> None:
    target = tmp_path / "app" / "services" / "new_service.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import sqlite3\n"
        "def run(path):\n"
        "    return sqlite3.connect(path)\n",
        encoding="utf-8",
    )

    result = guard.scan_paths([target], repo_root=tmp_path)

    assert result.error_count == 1
    assert result.findings[0].relative_path == "app/services/new_service.py"
    assert result.findings[0].pattern_id == "sqlite3_connect"


def test_guard_allows_legacy_sqlite_files_as_warning(tmp_path: Path) -> None:
    target = tmp_path / "migrations" / "migrate_sqlite.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "import sqlite3\n"
        "def connect(path):\n"
        "    return sqlite3.connect(path)\n",
        encoding="utf-8",
    )

    result = guard.scan_paths([target], repo_root=tmp_path)

    assert result.error_count == 0
    assert result.warning_count == 1
    assert result.findings[0].allowed is True


def test_guard_detects_service_sql_placeholder_usage(tmp_path: Path) -> None:
    target = tmp_path / "apps" / "xg_douyin_ai_cs" / "services" / "new_service.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "def run(conn, value):\n"
        "    return conn.execute(\"SELECT * FROM t WHERE id=?\", (value,))\n",
        encoding="utf-8",
    )

    result = guard.scan_paths([target], repo_root=tmp_path)

    assert result.error_count == 1
    assert result.findings[0].pattern_id == "service_sql_qmark"
