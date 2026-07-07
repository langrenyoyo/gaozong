"""数据库 URL 解析与脱敏工具。"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit


POSTGRESQL_SCHEMES = {
    "postgresql",
    "postgresql+psycopg",
    "postgresql+asyncpg",
}


@dataclass(frozen=True)
class ParsedDatabaseUrl:
    backend: str
    raw_url: str
    safe_url: str
    sqlite_path: str | None = None


def parse_database_url(raw_url: str) -> ParsedDatabaseUrl:
    """解析数据库 URL；本轮只识别类型，不创建连接。"""
    url = (raw_url or "").strip()
    if not url:
        raise ValueError("数据库 URL 不能为空")

    if url.startswith("sqlite:///"):
        sqlite_path = unquote(url.removeprefix("sqlite:///"))
        if not sqlite_path:
            raise ValueError("sqlite 数据库 URL 缺少文件路径")
        return ParsedDatabaseUrl(
            backend="sqlite",
            raw_url=url,
            safe_url=url,
            sqlite_path=sqlite_path,
        )

    parts = urlsplit(url)
    if parts.scheme in POSTGRESQL_SCHEMES:
        return ParsedDatabaseUrl(
            backend="postgresql",
            raw_url=url,
            safe_url=_mask_password(parts),
        )

    scheme = parts.scheme or "unknown"
    raise ValueError(f"不支持的数据库 URL scheme: {scheme}")


def sqlite_url_from_path(path: str) -> str:
    """把文件路径转换为 SQLite URL，保留当前 SQLite 默认运行方式。"""
    normalized = str(path)
    if normalized.startswith("/"):
        return f"sqlite:///{quote(normalized)}"
    return f"sqlite:///{quote(normalized)}"


def _mask_password(parts) -> str:
    username = parts.username or ""
    password = parts.password
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""

    if username:
        userinfo = quote(username)
        if password is not None:
            userinfo = f"{userinfo}:***"
        netloc = f"{userinfo}@{hostname}{port}"
    else:
        netloc = parts.netloc

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
