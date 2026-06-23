"""SQLite 迁移执行器（P2-A 骨架）。

职责
----
- 在指定数据库上执行版本化迁移（首批 PRD 基础字段）。
- 默认 dry-run（只打印，不写库）；仅显式 ``--apply`` 才写库。
- 幂等：依赖 ``schema_migrations`` 版本表 + 列存在性检查双重保护。
- 副本隔离：``--db-path`` 默认禁止指向主线开发测试库。

安全边界
--------
- 不修改 ``app/models.py``（``schema_migrations`` 不进入 ORM 模型）。
- 不对 ``data/auto_wechat.db`` 主线库执行真实迁移（除非显式 ``--allow-mainline``）。
- dry-run / verify 使用只读连接（``?mode=ro``），apply 使用读写连接。
- apply 在单一事务内执行全部 DDL + 版本记录，任一失败整体回滚。

本脚本自包含，不 import app 包，可在测试电脑上独立运行。
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("migrate_sqlite")

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

# 项目根 = migrations/ 的父目录（与 app/config.py 的 BASE_DIR 一致）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 主线开发测试库（P2-A 阶段禁止直接迁移，只能在其副本上验证）
MAINLINE_DB = PROJECT_ROOT / "data" / "auto_wechat.db"
# 版本 SQL 目录
VERSIONS_DIR = Path(__file__).resolve().parent / "versions"
# 默认加载的首批版本 SQL
DEFAULT_SQL_FILE = VERSIONS_DIR / "0001_prd_base_fields.sql"

# 当前首批版本号与说明
CURRENT_VERSION = "0001"
CURRENT_DESCRIPTION = "PRD 基础字段：schema_migrations 基础设施 + douyin_leads 9 列 + sales_staff 2 列"


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class MigrationError(RuntimeError):
    """迁移执行过程中出现的可预期错误（如目标表缺失、目标为主线库等）。"""


# ---------------------------------------------------------------------------
# SQL 解析
# ---------------------------------------------------------------------------


@dataclass
class ParsedStmt:
    """解析后的单条 SQL 语句。"""

    raw: str  # 原始文本（已 strip）
    kind: str  # create_table / add_column / other
    table: str | None = None
    column: str | None = None
    column_def: str | None = None  # ADD COLUMN 的类型定义部分


# CREATE TABLE [IF NOT EXISTS] <name>
_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?",
    re.IGNORECASE,
)
# ALTER TABLE <name> ADD COLUMN <col> <def>
_ALTER_RE = re.compile(
    r"ALTER\s+TABLE\s+[`\"']?(\w+)[`\"']?\s+ADD\s+COLUMN\s+[`\"']?(\w+)[`\"']?\s+(.*)",
    re.IGNORECASE | re.DOTALL,
)


def parse_sql(sql_text: str) -> list[ParsedStmt]:
    """解析 SQL 文本为结构化语句列表。

    - 去除 ``--`` 注释行。
    - 按分号分割为独立语句。
    - 识别 CREATE TABLE / ALTER TABLE ADD COLUMN 两类。
    """
    kept_lines: list[str] = []
    for line in sql_text.splitlines():
        if line.strip().startswith("--"):
            continue
        kept_lines.append(line)
    cleaned = "\n".join(kept_lines)

    result: list[ParsedStmt] = []
    for chunk in cleaned.split(";"):
        stmt = chunk.strip()
        if not stmt:
            continue
        create_m = _CREATE_RE.match(stmt)
        alter_m = _ALTER_RE.match(stmt)
        if create_m:
            result.append(ParsedStmt(stmt, "create_table", table=create_m.group(1)))
        elif alter_m:
            result.append(
                ParsedStmt(
                    stmt,
                    "add_column",
                    table=alter_m.group(1),
                    column=alter_m.group(2),
                    column_def=alter_m.group(3).strip(),
                )
            )
        else:
            result.append(ParsedStmt(stmt, "other"))
    return result


# ---------------------------------------------------------------------------
# 连接与基础查询
# ---------------------------------------------------------------------------


def _file_uri(path: str | os.PathLike) -> str:
    """把本地路径转成 file URI（跨平台，含 Windows 盘符）。"""
    return Path(path).resolve().as_uri()


def connect_readonly(path: str | os.PathLike) -> sqlite3.Connection:
    """以只读模式打开数据库（dry-run / verify 使用，绝不写）。"""
    uri = _file_uri(path) + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def connect_readwrite(path: str | os.PathLike) -> sqlite3.Connection:
    """以读写模式打开数据库（apply 使用）。

    关闭隐式事务（isolation_level=None），由 apply_migration 显式管理事务，
    确保 DDL 也在事务内、异常整体回滚。
    """
    conn = sqlite3.connect(str(Path(path).resolve()))
    conn.isolation_level = None
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def get_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({_ident(table)})")}


def _ident(name: str) -> str:
    """简单标识符校验，避免 PRAGMA 拼接注入。"""
    if not re.fullmatch(r"\w+", name):
        raise MigrationError(f"非法表名标识符: {name!r}")
    return name


def version_applied(conn: sqlite3.Connection, version: str) -> bool:
    """检查某版本是否已在 schema_migrations 记录。"""
    if not table_exists(conn, "schema_migrations"):
        return False
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version_num=?", (version,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# 迁移规划与执行
# ---------------------------------------------------------------------------


@dataclass
class MigrationPlan:
    """迁移规划结果（dry-run 与 apply 共用）。"""

    version: str
    already_applied: bool  # 整个版本是否已应用（整体跳过）
    will_run: list[ParsedStmt] = field(default_factory=list)
    skipped: list[tuple[ParsedStmt, str]] = field(default_factory=list)  # (stmt, reason)
    errors: list[tuple[ParsedStmt, str]] = field(default_factory=list)  # (stmt, reason)


@dataclass(frozen=True)
class MigrationFile:
    """单个版本迁移文件。"""

    version: str
    path: Path
    description: str


def plan_migration(
    conn: sqlite3.Connection, stmts: list[ParsedStmt], version: str
) -> MigrationPlan:
    """规划迁移：决定每条语句执行 / 跳过 / 报错。不写库。"""
    plan = MigrationPlan(version=version, already_applied=version_applied(conn, version))

    for s in stmts:
        if s.kind == "create_table":
            if plan.already_applied:
                plan.skipped.append((s, "version_already_applied"))
            elif s.table and table_exists(conn, s.table):
                plan.skipped.append((s, "table_exists"))
            else:
                plan.will_run.append(s)
        elif s.kind == "add_column":
            if not s.table or not table_exists(conn, s.table):
                plan.errors.append((s, "target_table_missing"))
            elif s.column and s.column in get_columns(conn, s.table):
                plan.skipped.append((s, "column_exists"))
            else:
                # 已登记版本仍允许补偿缺失列，用于修复历史迁移登记与实际 schema 不一致。
                plan.will_run.append(s)
        else:
            if plan.already_applied:
                plan.skipped.append((s, "version_already_applied"))
            else:
                plan.will_run.append(s)
    return plan


def discover_migrations(versions_dir: str | os.PathLike = VERSIONS_DIR) -> list[MigrationFile]:
    """扫描 versions 目录并按版本号升序返回迁移文件。"""
    root = Path(versions_dir)
    migrations: list[MigrationFile] = []
    for path in root.glob("*.sql"):
        match = re.match(r"^(\d{4})_(.+)\.sql$", path.name)
        if not match:
            continue
        migrations.append(
            MigrationFile(
                version=match.group(1),
                path=path,
                description=match.group(2).replace("_", " "),
            )
        )
    migrations.sort(key=lambda item: item.version)
    return migrations


def infer_migration_metadata(
    sql_file: str | os.PathLike,
    version: str | None = None,
) -> MigrationFile:
    """从版本文件名推导单文件迁移元数据，避免误复用 0001 默认描述。"""
    path = Path(sql_file)
    if path.resolve() == DEFAULT_SQL_FILE.resolve():
        return MigrationFile(
            version=version or CURRENT_VERSION,
            path=path,
            description=CURRENT_DESCRIPTION,
        )

    match = re.match(r"^(\d{4})_(.+)\.sql$", path.name)
    if match:
        return MigrationFile(
            version=version or match.group(1),
            path=path,
            description=match.group(2).replace("_", " "),
        )

    return MigrationFile(
        version=version or CURRENT_VERSION,
        path=path,
        description=CURRENT_DESCRIPTION,
    )


def plan_all_migrations(
    conn: sqlite3.Connection,
    migrations: list[MigrationFile] | None = None,
) -> list[MigrationPlan]:
    """规划全部版本迁移；只读，不修改数据库。"""
    result: list[MigrationPlan] = []
    for migration in migrations or discover_migrations():
        stmts = _load_stmts(migration.path)
        result.append(plan_migration(conn, stmts, migration.version))
    return result


def apply_all_migrations(
    conn: sqlite3.Connection,
    migrations: list[MigrationFile] | None = None,
) -> list[MigrationPlan]:
    """按版本顺序显式执行所有未应用迁移。"""
    result: list[MigrationPlan] = []
    for migration in migrations or discover_migrations():
        stmts = _load_stmts(migration.path)
        plan = apply_migration(conn, stmts, migration.version, migration.description)
        result.append(plan)
    return result


def get_migration_status(
    conn: sqlite3.Connection,
    migrations: list[MigrationFile] | None = None,
) -> dict:
    """返回已执行版本和待执行版本。"""
    all_migrations = migrations or discover_migrations()
    known_versions = [item.version for item in all_migrations]
    applied_versions: list[str] = []
    if table_exists(conn, "schema_migrations"):
        applied_versions = [
            row[0]
            for row in conn.execute(
                "SELECT version_num FROM schema_migrations ORDER BY version_num"
            )
        ]
    applied_set = set(applied_versions)
    pending_versions = [version for version in known_versions if version not in applied_set]
    unknown_applied_versions = [
        version for version in applied_versions if version not in set(known_versions)
    ]
    return {
        "known_versions": known_versions,
        "applied_versions": applied_versions,
        "pending_versions": pending_versions,
        "unknown_applied_versions": unknown_applied_versions,
    }


def apply_migration(
    conn: sqlite3.Connection,
    stmts: list[ParsedStmt],
    version: str,
    description: str,
) -> MigrationPlan:
    """在单一事务内执行迁移 + 记录版本；任一失败整体回滚。"""
    plan = plan_migration(conn, stmts, version)

    if plan.errors:
        for s, reason in plan.errors:
            logger.error("迁移中止：目标缺失 reason=%s table=%s stmt=%s",
                         reason, s.table, _one_line(s.raw))
        raise MigrationError(
            f"迁移中止：{len(plan.errors)} 条语句目标表缺失（{plan.errors[0][1]}），"
            f"已整体回滚，未写入任何变更"
        )

    if plan.already_applied:
        current_description = _get_migration_description(conn, version)
        should_update_description = current_description != description
        if not plan.will_run and not should_update_description:
            logger.info("版本 %s 已应用，整体跳过（执行 0 条，跳过 %d 条）",
                        version, len(plan.skipped))
            return plan

        logger.warning(
            "版本 %s 已登记但需要补偿：执行 %d 条，更新描述=%s",
            version,
            len(plan.will_run),
            should_update_description,
        )
        try:
            conn.execute("BEGIN")
            for s in plan.will_run:
                logger.warning("补偿执行 DDL: %s", _one_line(s.raw))
                conn.execute(s.raw)
            if should_update_description:
                conn.execute(
                    "UPDATE schema_migrations SET description=? WHERE version_num=?",
                    (description, version),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception("补偿 apply 失败，已回滚")
            raise
        return plan

    logger.info("apply 版本 %s：将执行 %d 条，跳过 %d 条",
                version, len(plan.will_run), len(plan.skipped))

    try:
        conn.execute("BEGIN")
        for s in plan.will_run:
            logger.debug("执行 DDL: %s", _one_line(s.raw))
            conn.execute(s.raw)
        conn.execute(
            "INSERT INTO schema_migrations (version_num, applied_at, description) "
            "VALUES (?,?,?)",
            (version, datetime.now().isoformat(sep=" "), description),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        logger.exception("apply 失败，已回滚")
        raise

    logger.info("apply 完成：版本 %s 已记录", version)
    return plan


def _get_migration_description(conn: sqlite3.Connection, version: str) -> str | None:
    """读取已登记迁移描述；schema_migrations 不存在时返回空。"""
    if not table_exists(conn, "schema_migrations"):
        return None
    row = conn.execute(
        "SELECT description FROM schema_migrations WHERE version_num=?",
        (version,),
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 副本生成（sqlite3 backup API，WAL 安全）
# ---------------------------------------------------------------------------


def backup_database(src_path: str | os.PathLike, dst_path: str | os.PathLike) -> None:
    """使用 sqlite3 backup API 生成一致性副本。

    - 源库以只读方式打开，不执行任何 DDL。
    - backup API 会正确处理 WAL 内容，生成完整一致的快照
      （不依赖 shutil.copy2 单独拷贝 -wal / -shm）。
    - 若目标已存在则先删除，避免脏副本。
    """
    src_path = Path(src_path).resolve()
    dst_path = Path(dst_path).resolve()
    if not src_path.exists():
        raise MigrationError(f"源库不存在: {src_path}")

    if dst_path.exists():
        dst_path.unlink()
        logger.warning("目标副本已存在，已覆盖: %s", dst_path)

    src = connect_readonly(src_path)
    dst = sqlite3.connect(str(dst_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    logger.info("副本已生成（backup API）：%s -> %s", src_path, dst_path)


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------


def verify_migration(conn: sqlite3.Connection) -> dict:
    """只读验证迁移结果，返回结构化诊断信息。"""
    result: dict = {
        "schema_migrations_exists": table_exists(conn, "schema_migrations"),
        "versions": [],
        "douyin_leads_exists": table_exists(conn, "douyin_leads"),
        "sales_staff_exists": table_exists(conn, "sales_staff"),
        "douyin_leads_columns": [],
        "sales_staff_columns": [],
        "douyin_leads_count": None,
        "reassign_count_distinct": [],
    }
    if result["schema_migrations_exists"]:
        result["versions"] = [
            r[0] for r in conn.execute("SELECT version_num FROM schema_migrations ORDER BY version_num")
        ]
    if result["douyin_leads_exists"]:
        cols = sorted(get_columns(conn, "douyin_leads"))
        result["douyin_leads_columns"] = cols
        result["douyin_leads_count"] = conn.execute(
            "SELECT count(*) FROM douyin_leads"
        ).fetchone()[0]
        result["reassign_count_distinct"] = sorted(
            {r[0] for r in conn.execute("SELECT DISTINCT reassign_count FROM douyin_leads")}
        ) if "reassign_count" in cols else []
    if result["sales_staff_exists"]:
        result["sales_staff_columns"] = sorted(get_columns(conn, "sales_staff"))
    return result


# ---------------------------------------------------------------------------
# 主线防护
# ---------------------------------------------------------------------------


def assert_not_mainline(db_path: str | os.PathLike, allow_mainline: bool) -> None:
    """拒绝直接迁移主线开发测试库（除非显式 --allow-mainline）。"""
    real = Path(db_path).resolve()
    main = MAINLINE_DB.resolve()
    if real == main and not allow_mainline:
        raise MigrationError(
            f"拒绝：--db-path 指向主线开发测试库 {main}。\n"
            f"P2-A 禁止直接迁移主线库，请在副本上验证。\n"
            f"如确需迁移主线（P2-C 阶段），请显式加 --allow-mainline。"
        )


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _load_stmts(sql_file: str | os.PathLike) -> list[ParsedStmt]:
    return parse_sql(Path(sql_file).read_text(encoding="utf-8"))


def _print_plan(plan: MigrationPlan) -> None:
    print(f"[dry-run] 版本 {plan.version} 已应用={plan.already_applied}")
    print(f"[dry-run] 将执行 {len(plan.will_run)} 条：")
    for s in plan.will_run:
        print(f"  + [{s.kind}] {_one_line(s.raw)}")
    print(f"[dry-run] 跳过 {len(plan.skipped)} 条：")
    for s, reason in plan.skipped:
        print(f"  - [{s.kind}] {reason}: {_one_line(s.raw)}")
    if plan.errors:
        print(f"[dry-run] 错误 {len(plan.errors)} 条（apply 会中止）：")
        for s, reason in plan.errors:
            print(f"  ! [{s.kind}] {reason}: {_one_line(s.raw)}")


def _print_verify(result: dict) -> None:
    print("[verify] schema_migrations_exists =", result["schema_migrations_exists"])
    print("[verify] versions =", result["versions"])
    print("[verify] douyin_leads_exists =", result["douyin_leads_exists"])
    print("[verify] douyin_leads_count =", result["douyin_leads_count"])
    print("[verify] douyin_leads_columns =", result["douyin_leads_columns"])
    print("[verify] reassign_count_distinct =", result["reassign_count_distinct"])
    print("[verify] sales_staff_columns =", result["sales_staff_columns"])


def _print_all_plans(plans: list[MigrationPlan]) -> None:
    print("[all] versions =", [plan.version for plan in plans])
    for plan in plans:
        status = "applied" if plan.already_applied else "pending"
        print(
            f"[all] {plan.version} status={status} "
            f"will_run={len(plan.will_run)} skipped={len(plan.skipped)} errors={len(plan.errors)}"
        )
        if plan.errors:
            for stmt, reason in plan.errors:
                print(f"  ! [{stmt.kind}] {reason}: {_one_line(stmt.raw)}")


def _print_status(status: dict) -> None:
    print("[status] known_versions =", status["known_versions"])
    print("[status] applied_versions =", status["applied_versions"])
    print("[status] pending_versions =", status["pending_versions"])
    print("[status] unknown_applied_versions =", status["unknown_applied_versions"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="SQLite 迁移执行器（P2-A 骨架，默认 dry-run）"
    )
    p.add_argument("--db-path", help="目标数据库路径（应为副本）")
    p.add_argument("--sql-file", default=str(DEFAULT_SQL_FILE),
                   help=f"版本 SQL 文件（默认 {DEFAULT_SQL_FILE}）")
    p.add_argument("--version", default=None, help="迁移版本号；默认从 SQL 文件名推导")
    p.add_argument("--allow-mainline", action="store_true",
                   help="允许直接迁移主线库（P2-A 不使用，P2-C 阶段才用）")
    p.add_argument("--dry-run", action="store_true", help="只打印，不写库（默认）")
    p.add_argument("--apply", action="store_true", help="实际写库（单一事务）")
    p.add_argument("--verify", action="store_true", help="只读验证迁移结果")
    p.add_argument("--all", action="store_true", help="按 versions 目录顺序 dry-run/apply 所有迁移")
    p.add_argument("--status", action="store_true", help="只读输出已执行版本和待执行版本")
    p.add_argument("--backup-src", help="副本生成：源库路径（使用 backup API）")
    p.add_argument("--backup-dst", help="副本生成：目标副本路径")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)

    # 副本生成子模式
    if args.backup_src or args.backup_dst:
        if not (args.backup_src and args.backup_dst):
            logger.error("--backup-src 与 --backup-dst 必须同时提供")
            return 2
        backup_database(args.backup_src, args.backup_dst)
        return 0

    if not args.db_path:
        logger.error("缺少 --db-path（或使用 --backup-src/--backup-dst 生成副本）")
        return 2

    assert_not_mainline(args.db_path, args.allow_mainline)

    if args.status:
        conn = connect_readonly(args.db_path)
        try:
            _print_status(get_migration_status(conn))
        finally:
            conn.close()
        return 0

    if args.all:
        if args.apply:
            conn = connect_readwrite(args.db_path)
            try:
                _print_all_plans(apply_all_migrations(conn))
            finally:
                conn.close()
            return 0

        conn = connect_readonly(args.db_path)
        try:
            _print_all_plans(plan_all_migrations(conn))
        finally:
            conn.close()
        return 0

    migration = infer_migration_metadata(args.sql_file, args.version)
    stmts = _load_stmts(migration.path)

    if args.verify:
        conn = connect_readonly(args.db_path)
        try:
            _print_verify(verify_migration(conn))
        finally:
            conn.close()
        return 0

    if args.apply:
        conn = connect_readwrite(args.db_path)
        try:
            apply_migration(conn, stmts, migration.version, migration.description)
        finally:
            conn.close()
        return 0

    # 默认 dry-run
    conn = connect_readonly(args.db_path)
    try:
        _print_plan(plan_migration(conn, stmts, migration.version))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
