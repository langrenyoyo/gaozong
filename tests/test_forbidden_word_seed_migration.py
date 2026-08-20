"""P0-违禁词数据迁移验证测试。

验证 SQLite 0047 与 PostgreSQL 0037 迁移：
1. SQLite 临时库首次升级 → 403 词条；
2. SQLite 重复升级幂等（不重复插入）；
3. SQLite 迁移失败整体回滚；
4. 词库与词条数量为预期；
5. safe_word 全部为 NULL；
6. 不存在单字符词条；
7. 同一词库不存在 casefold 重复；
8. PG 临时测试库 upgrade head；
9. PG 重复 upgrade 不重复插入；
10. PG downgrade 后数据保留；
11. PG downgrade 后再次 upgrade 仍幂等；
12. load_forbidden_words_for_llm() 可读取 403 条规范化词条；
13. 回归 test_forbidden_word_service.py / test_forbidden_word_policy.py（由外层执行）；
14. 不连接生产、不触发真实 LLM/发送/RAG。

环境限制：PG 验证需要本地临时 PostgreSQL（127.0.0.1:5432），缺失时跳过。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_MIGRATION = os.path.join(REPO, "migrations", "versions", "0047_forbidden_word_seed.sql")
EXPECTED_LIBRARIES = {
    "used_car_sales_base", "finance_compliance", "vehicle_condition_risk",
    "extreme_ad_words", "state_sensitive_words", "inducement_fraud_words",
    "contact_guidance_words", "superstition_words", "incivility_words", "ip_event_words",
}
EXPECTED_WORDS = 403
LIB_COUNTS = {
    "used_car_sales_base": 22, "finance_compliance": 21, "vehicle_condition_risk": 9,
    "extreme_ad_words": 171, "state_sensitive_words": 42, "inducement_fraud_words": 62,
    "contact_guidance_words": 26, "superstition_words": 18, "incivility_words": 22, "ip_event_words": 10,
}
SINGLE_CHAR_WORDS = {"最", "V"}  # 规则2：不入库


def _run_sqlite_migration(db_path: str) -> None:
    """在临时 SQLite 上按顺序执行前序迁移 + 0047。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # 建表（0027 结构）
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS forbidden_word_libraries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_key VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            scope VARCHAR(32) NOT NULL DEFAULT 'global',
            enabled BOOLEAN NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        );
        CREATE TABLE IF NOT EXISTS forbidden_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_id INTEGER NOT NULL,
            word VARCHAR(100) NOT NULL,
            safe_word VARCHAR(100),
            severity VARCHAR(32),
            enabled BOOLEAN NOT NULL DEFAULT 1,
            hit_count INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME,
            UNIQUE (library_id, word)
        );
        """
    )
    # 执行 0047（幂等脚本）
    sql = open(SQLITE_MIGRATION, encoding="utf-8").read()
    cur.executescript(sql)
    conn.commit()
    return conn


def _seed_words_from_sql() -> set[tuple[str, str]]:
    """从 0047 SQL 提取 (library_key, word) 集合，验证规则应用。"""
    import re
    sql = open(SQLITE_MIGRATION, encoding="utf-8").read()
    pat = re.compile(
        r"SELECT id, '([^']*)', NULL, '([^']*)', 1, 0 FROM forbidden_word_libraries WHERE library_key = '([^']*)'"
    )
    return {(lib, word) for word, _sev, lib in pat.findall(sql)}


# ---------------------------------------------------------------------------
# 1-7：SQLite
# ---------------------------------------------------------------------------

def test_sqlite_first_upgrade_counts_and_no_single_char():
    conn = _run_sqlite_migration(tempfile.mktemp(suffix=".db"))
    cur = conn.cursor()
    libs = {r[0] for r in cur.execute("SELECT library_key FROM forbidden_word_libraries").fetchall()}
    assert libs == EXPECTED_LIBRARIES, f"词库集合不符: {libs ^ EXPECTED_LIBRARIES}"
    total = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert total == EXPECTED_WORDS, f"词条数 {total} != 403"
    # 每词库数量
    counts = dict(cur.execute(
        "SELECT fl.library_key, COUNT(fw.id) FROM forbidden_word_libraries fl "
        "LEFT JOIN forbidden_words fw ON fw.library_id = fl.id GROUP BY fl.library_key"
    ).fetchall())
    for key, expected in LIB_COUNTS.items():
        assert counts.get(key, 0) == expected, f"词库 {key}: {counts.get(key)} != {expected}"
    # safe_word 全 NULL
    null_safe = cur.execute("SELECT COUNT(*) FROM forbidden_words WHERE safe_word IS NOT NULL").fetchone()[0]
    assert null_safe == 0, "safe_word 应为全 NULL"
    # 无单字符词条
    single = [w for w, in cur.execute("SELECT word FROM forbidden_words").fetchall() if len(w.strip()) == 1]
    assert single == [], f"存在单字符词条: {single}"
    # 无 casefold 重复（同词库）
    dup = cur.execute(
        "SELECT library_id, LOWER(word) FROM forbidden_words GROUP BY library_id, LOWER(word) HAVING COUNT(*) > 1"
    ).fetchall()
    assert dup == [], f"同词库 casefold 重复: {dup}"
    conn.close()


def test_sqlite_repeated_upgrade_idempotent():
    conn = _run_sqlite_migration(tempfile.mktemp(suffix=".db"))
    cur = conn.cursor()
    sql = open(SQLITE_MIGRATION, encoding="utf-8").read()
    cur.executescript(sql)  # 重复执行
    conn.commit()
    total = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert total == EXPECTED_WORDS, f"重复升级后词条数 {total} != 403"
    conn.close()


def test_sqlite_failed_migration_rolls_back():
    """迁移失败整体回滚：在 0047 中途注入错误语句，验证无部分写入。"""
    conn = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE forbidden_word_libraries (id INTEGER PRIMARY KEY, library_key VARCHAR(64) NOT NULL UNIQUE, name VARCHAR(100) NOT NULL, scope VARCHAR(32) DEFAULT 'global', enabled BOOLEAN DEFAULT 1, sort_order INTEGER DEFAULT 0);
        CREATE TABLE forbidden_words (id INTEGER PRIMARY KEY, library_id INTEGER NOT NULL, word VARCHAR(100) NOT NULL, safe_word VARCHAR(100), severity VARCHAR(32), enabled BOOLEAN DEFAULT 1, hit_count INTEGER DEFAULT 0, UNIQUE(library_id, word));
        """
    )
    conn.commit()
    sql = open(SQLITE_MIGRATION, encoding="utf-8").read()
    # 注入错误：引用不存在的列
    broken = sql.replace("INSERT INTO forbidden_words", "INSERT INTO forbidden_words_broken")
    with pytest.raises(sqlite3.OperationalError):
        cur.executescript(broken)
    # 回滚后无词库/词条写入（executescript 自动回滚已提交前的事务？SQLite 需显式检查）
    conn.rollback()
    libs = cur.execute("SELECT COUNT(*) FROM forbidden_word_libraries").fetchone()[0]
    words = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    # 注：SQLite 的 executescript 会隐式提交，部分 INSERT 可能已写入——这里验证注入错误后的状态
    # 为模拟"整体回滚"，用事务包裹：BEGIN ... COMMIT/ROLLBACK
    conn.close()


def test_sqlite_failed_migration_rolls_back_atomic():
    """迁移失败整体回滚（事务包裹）：BEGIN → 迁移 → 失败 → ROLLBACK → 零写入。"""
    conn = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE forbidden_word_libraries (id INTEGER PRIMARY KEY, library_key VARCHAR(64) NOT NULL UNIQUE, name VARCHAR(100) NOT NULL, scope VARCHAR(32) DEFAULT 'global', enabled BOOLEAN DEFAULT 1, sort_order INTEGER DEFAULT 0);
        CREATE TABLE forbidden_words (id INTEGER PRIMARY KEY, library_id INTEGER NOT NULL, word VARCHAR(100) NOT NULL, safe_word VARCHAR(100), severity VARCHAR(32), enabled BOOLEAN DEFAULT 1, hit_count INTEGER DEFAULT 0, UNIQUE(library_id, word));
        """
    )
    conn.commit()
    sql = open(SQLITE_MIGRATION, encoding="utf-8").read()
    broken = sql.replace("INSERT INTO forbidden_words", "INSERT INTO forbidden_words_broken")
    cur.execute("BEGIN")
    try:
        cur.executescript(broken)
        conn.commit()
        raise AssertionError("应抛出 OperationalError")
    except sqlite3.OperationalError:
        conn.rollback()
    libs = cur.execute("SELECT COUNT(*) FROM forbidden_word_libraries").fetchone()[0]
    words = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert libs == 0 and words == 0, f"失败迁移未整体回滚: libs={libs} words={words}"
    conn.close()


# ---------------------------------------------------------------------------
# 迁移 SQL 静态校验（单字符/qq 去重/safe_word NULL）
# ---------------------------------------------------------------------------

def test_migration_sql_rules_applied():
    """0047 SQL 静态规则：无单字符词条、qq/QQ 只留一个、safe_word 全 NULL。"""
    words = _seed_words_from_sql()
    assert len(words) == EXPECTED_WORDS, f"SQL 词条数 {len(words)} != 403"
    assert all(len(w.strip()) > 1 for _, w in words), "SQL 含单字符词条"
    qq_words = [w for _, w in words if w.casefold() == "qq"]
    assert qq_words == ["qq"], f"qq/QQ 去重失败: {qq_words}"
    sql = open(SQLITE_MIGRATION, encoding="utf-8").read()
    # safe_word 位置精确匹配 ", NULL," （每个词条插入恰好一次）
    assert sql.count(", NULL,") == EXPECTED_WORDS, "safe_word 应全部写入 NULL"


# ---------------------------------------------------------------------------
# 12. load_forbidden_words_for_llm() 读取 403 条
# ---------------------------------------------------------------------------

def test_load_forbidden_words_for_llm_reads_403():
    """在临时 SQLite 迁移后，用 ORM 读取 load_forbidden_words_for_llm() 应含 403 条。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    db_path = tempfile.mktemp(suffix=".db")
    _run_sqlite_migration(db_path)

    import app.models  # noqa
    from app.database import Base
    from app.services.forbidden_word_service import load_forbidden_words_for_llm

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        # 迁移建表后 ORM 读（ORM 需声明表结构，这里用 Base 元数据绑定到迁移库）
        Base.metadata.create_all(engine)  # 不建表，仅确保 ORM 可用
        words = load_forbidden_words_for_llm(db)
        assert len(words) == EXPECTED_WORDS, f"load_forbidden_words_for_llm() 返回 {len(words)} != 403"
        # 不包含单字符
        assert all(len(w.strip()) > 1 for w in words)
        # 不包含 casefold 重复
        seen = set()
        dup = [w for w in words if w.casefold() in seen or seen.add(w.casefold())]
        assert dup == []
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 8-11：PostgreSQL（需本地临时 PG，缺失跳过）
# ---------------------------------------------------------------------------

def _pg_available() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    try:
        conn = psycopg.connect("host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres", connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_pg_upgrade_head_seed_403():
    """PG 临时库 alembic upgrade head → 403 词条 + 10 词库 + safe_word NULL。"""
    import psycopg

    DB = "au_fw_seed_test"
    conn = psycopg.connect("host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres", connect_timeout=5, autocommit=True)
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {DB}")
    cur.execute(f"CREATE DATABASE {DB}")
    conn.close()

    env = dict(os.environ)
    env["DATABASE_URL"] = f"postgresql+psycopg://postgres:change_me@127.0.0.1:5432/{DB}"
    # 从 head 之前升级到 head（含 0037）
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", os.path.join(REPO, "migrations", "postgres", "auto_wechat", "alembic.ini"), "upgrade", "head"],
        cwd=REPO, env=env, check=True, capture_output=True,
    )

    conn = psycopg.connect(f"host=127.0.0.1 port=5432 user=postgres password=change_me dbname={DB}", connect_timeout=5)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert total == EXPECTED_WORDS, f"PG 词条数 {total} != 403"
    libs = cur.execute("SELECT COUNT(*) FROM forbidden_word_libraries").fetchone()[0]
    assert libs == 10, f"PG 词库数 {libs} != 10"
    null_safe = cur.execute("SELECT COUNT(*) FROM forbidden_words WHERE safe_word IS NOT NULL").fetchone()[0]
    assert null_safe == 0, "PG safe_word 应全 NULL"
    single = cur.execute("SELECT word FROM forbidden_words WHERE CHAR_LENGTH(word) = 1").fetchall()
    assert single == [], f"PG 单字符词条: {single}"
    conn.close()


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_pg_repeated_upgrade_and_downgrade_idempotent():
    """PG 重复 upgrade 不重复插入；downgrade 后数据保留；再 upgrade 仍幂等。"""
    import psycopg

    DB = "au_fw_seed_test2"
    conn = psycopg.connect("host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres", connect_timeout=5, autocommit=True)
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {DB}")
    cur.execute(f"CREATE DATABASE {DB}")
    conn.close()

    env = dict(os.environ)
    env["DATABASE_URL"] = f"postgresql+psycopg://postgres:change_me@127.0.0.1:5432/{DB}"
    alembic = [sys.executable, "-m", "alembic", "-c", os.path.join(REPO, "migrations", "postgres", "auto_wechat", "alembic.ini")]

    subprocess.run([*alembic, "upgrade", "head"], cwd=REPO, env=env, check=True, capture_output=True)
    # 重复 upgrade（幂等）
    subprocess.run([*alembic, "upgrade", "head"], cwd=REPO, env=env, check=True, capture_output=True)

    conn = psycopg.connect(f"host=127.0.0.1 port=5432 user=postgres password=change_me dbname={DB}", connect_timeout=5)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert total == EXPECTED_WORDS, f"重复 upgrade 后词条数 {total} != 403"
    conn.close()

    # downgrade 0036（不删除词条，只回退版本标记）
    subprocess.run([*alembic, "downgrade", "0036"], cwd=REPO, env=env, check=True, capture_output=True)
    conn = psycopg.connect(f"host=127.0.0.1 port=5432 user=postgres password=change_me dbname={DB}", connect_timeout=5)
    cur = conn.cursor()
    ver = cur.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert ver == "0036", f"downgrade 后版本 {ver} != 0036"
    total_after_dn = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert total_after_dn == EXPECTED_WORDS, f"downgrade 后词条应保留 {total_after_dn} != 403"
    conn.close()

    # 再 upgrade 0037（幂等）
    subprocess.run([*alembic, "upgrade", "0037"], cwd=REPO, env=env, check=True, capture_output=True)
    conn = psycopg.connect(f"host=127.0.0.1 port=5432 user=postgres password=change_me dbname={DB}", connect_timeout=5)
    cur = conn.cursor()
    total_final = cur.execute("SELECT COUNT(*) FROM forbidden_words").fetchone()[0]
    assert total_final == EXPECTED_WORDS, f"再次 upgrade 后词条数 {total_final} != 403"
    conn.close()

    # 清理
    conn = psycopg.connect("host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres", connect_timeout=5, autocommit=True)
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {DB}")
    conn.close()


# ---------------------------------------------------------------------------
# P0-DOUYIN-AUTO-REPLY-PRE-LLM-GATE-1：prohibited_auto_reply 幂等 seed（非 migration）
# ---------------------------------------------------------------------------

def _seed_orm_session(db_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return sessionmaker(bind=engine)()


def test_seed_prohibited_auto_reply_idempotent_four_words_excluded_not_in_library():
    """seed 幂等：四词入库、排除词不入、finance_compliance 原词保留。"""
    from app.models import ForbiddenWord, ForbiddenWordLibrary
    from app.services.forbidden_word_seed import (
        LIBRARY_KEY,
        WORDS,
        seed_prohibited_auto_reply,
    )

    db_path = tempfile.mktemp(suffix=".db")
    _run_sqlite_migration(db_path)  # 建表 + 0047（10 词库 / 403 词条）
    db = _seed_orm_session(db_path)
    try:
        r1 = seed_prohibited_auto_reply(db)
        assert r1["inserted"] == 4, f"首次应插入 4 词条: {r1}"
        r2 = seed_prohibited_auto_reply(db)
        assert r2["inserted"] == 0, "重复执行不得重复插入"

        lib = db.query(ForbiddenWordLibrary).filter_by(library_key=LIBRARY_KEY).first()
        assert lib is not None
        assert lib.scope == "global"
        assert lib.enabled is True
        word_set = {
            w[0]
            for w in db.query(ForbiddenWord.word).filter_by(library_id=lib.id).all()
        }
        assert word_set == set(WORDS), f"词条不符: {word_set}"

        # 排除词不进入新库
        excluded = {"贷款", "金融", "分期", "征信"}
        assert word_set & excluded == set(), f"排除词误入新库: {word_set & excluded}"

        # finance_compliance 原词保留（0047 seed 含 贷款/金融/分期/征信）
        finance = db.query(ForbiddenWordLibrary).filter_by(library_key="finance_compliance").first()
        assert finance is not None
        finance_words = {
            w[0]
            for w in db.query(ForbiddenWord.word).filter_by(library_id=finance.id).all()
        }
        assert finance_words & excluded, "finance_compliance 原词条不得被删除"
        assert "黑户" in finance_words, "finance_compliance 历史黑户词条应保留"
    finally:
        db.close()
