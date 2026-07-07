from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_SCAN_ROOTS = (
    "app",
    "apps/xg_douyin_ai_cs",
    "scripts",
    "migrations",
    "tests",
)

ALLOWLIST_PATTERNS = (
    "migrations/**",
    "tests/**",
    "apps/xg_douyin_ai_cs/rag/database.py",
    "apps/xg_douyin_ai_cs/rag/repository.py",
    "apps/xg_douyin_ai_cs/services/knowledge_training_service.py",
    "scripts/check_sqlite_specific_usage.py",
)

CORE_BUSINESS_PATTERNS = (
    "app/services/**",
    "app/routers/**",
    "apps/xg_douyin_ai_cs/services/**",
    "apps/xg_douyin_ai_cs/routers/**",
)

PATTERNS = (
    (
        "sqlite3_connect",
        re.compile(r"\bsqlite3\.connect\s*\("),
        "业务代码不应直接连接 SQLite，应后续收口到 database/repository 层。",
    ),
    (
        "pragma_table_info",
        re.compile(r"\bPRAGMA\s+table_info\b", re.IGNORECASE),
        "PRAGMA table_info 是 SQLite schema introspection 写法。",
    ),
    (
        "insert_or_ignore",
        re.compile(r"\bINSERT\s+OR\s+IGNORE\b", re.IGNORECASE),
        "INSERT OR IGNORE 是 SQLite 幂等写法，PostgreSQL 需改为唯一约束 + ON CONFLICT。",
    ),
    (
        "insert_or_replace",
        re.compile(r"\bINSERT\s+OR\s+REPLACE\b", re.IGNORECASE),
        "INSERT OR REPLACE 是 SQLite upsert 写法，可能改变删除/插入语义。",
    ),
    (
        "rowid",
        re.compile(r"\browid\b", re.IGNORECASE),
        "rowid 是 SQLite 隐式行标识，不应进入可迁移业务逻辑。",
    ),
    (
        "integer_primary_key_autoincrement",
        re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.IGNORECASE),
        "INTEGER PRIMARY KEY AUTOINCREMENT 是 SQLite 自增主键写法。",
    ),
    (
        "autoincrement",
        re.compile(r"\bAUTOINCREMENT\b"),
        "AUTOINCREMENT 是 SQLite 迁移期 DDL 写法，不应在新业务逻辑中扩散。",
    ),
)


@dataclass(frozen=True)
class Finding:
    relative_path: str
    line_number: int
    pattern_id: str
    risk: str
    allowed: bool
    line_preview: str


@dataclass(frozen=True)
class ScanResult:
    findings: list[Finding]

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.findings if not item.allowed)

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.findings if item.allowed)


def _to_posix(path: Path) -> str:
    return path.as_posix()


def _relative_path(path: Path, repo_root: Path) -> str:
    try:
        return _to_posix(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return _to_posix(path)


def _matches_any(relative_path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def _is_allowed(relative_path: str) -> bool:
    return _matches_any(relative_path, ALLOWLIST_PATTERNS)


def _is_core_business_path(relative_path: str) -> bool:
    return _matches_any(relative_path, CORE_BUSINESS_PATTERNS)


def _iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix in {".py", ".sql"}:
                yield path
            continue
        for child in path.rglob("*"):
            if child.is_file() and child.suffix in {".py", ".sql"}:
                yield child


def _detect_line_patterns(line: str, relative_path: str) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for pattern_id, pattern, risk in PATTERNS:
        if pattern.search(line):
            matches.append((pattern_id, risk))

    if _is_core_business_path(relative_path):
        has_sql_keyword = re.search(r"\b(SELECT|INSERT|UPDATE|DELETE|VALUES)\b", line, re.IGNORECASE)
        has_qmark_placeholder = "?" in line and re.search(r"\bexecute(?:many)?\s*\(", line)
        if has_sql_keyword and has_qmark_placeholder:
            matches.append(
                (
                    "service_sql_qmark",
                    "核心 service/router 中散落 SQL ? 占位符，后续应收口到 repository/database 层。",
                )
            )

    if re.search(r"active_.*count.*==\s*0|==\s*0.*active_.*count", line) and "rag" in line.lower():
        matches.append(
            (
                "sqlite_active_count_rag_skip",
                "RAG 路径不应在 Milvus 模式下仅凭 SQLite active count=0 跳过检索。",
            )
        )

    return matches


def scan_paths(paths: Iterable[Path | str], *, repo_root: Path | str | None = None) -> ScanResult:
    root = Path(repo_root or Path.cwd())
    normalized_paths = [Path(path) for path in paths]
    findings: list[Finding] = []

    for file_path in _iter_files(normalized_paths):
        relative_path = _relative_path(file_path, root)
        if relative_path == "scripts/check_sqlite_specific_usage.py":
            continue
        allowed = _is_allowed(relative_path)
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()

        for index, line in enumerate(lines, start=1):
            for pattern_id, risk in _detect_line_patterns(line, relative_path):
                findings.append(
                    Finding(
                        relative_path=relative_path,
                        line_number=index,
                        pattern_id=pattern_id,
                        risk=risk,
                        allowed=allowed,
                        line_preview=line.strip()[:160],
                    )
                )

    return ScanResult(findings=findings)


def _print_result(result: ScanResult) -> None:
    if not result.findings:
        print("SQLite 专属写法检查通过：未发现命中。")
        return

    for item in result.findings:
        level = "WARNING" if item.allowed else "ERROR"
        print(
            f"{level} {item.relative_path}:{item.line_number} "
            f"{item.pattern_id} - {item.risk}"
        )
        print(f"  {item.line_preview}")

    print(
        f"SQLite 专属写法检查完成：errors={result.error_count}, "
        f"warnings={result.warning_count}"
    )


def _default_paths(repo_root: Path) -> list[Path]:
    return [repo_root / item for item in DEFAULT_SCAN_ROOTS]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查新增 SQLite-only 写法是否进入核心业务代码。")
    parser.add_argument(
        "paths",
        nargs="*",
        help="可选扫描路径；默认扫描 app、apps/xg_douyin_ai_cs、scripts、migrations、tests。",
    )
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    paths = [Path(item) for item in args.paths] if args.paths else _default_paths(repo_root)
    result = scan_paths(paths, repo_root=repo_root)
    _print_result(result)
    return 1 if result.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
