"""Phase 8 Task 6：日报安全文件存储。

职责：
- 生成不可预测的 storage key（不含 merchant_id 明文、盘符、.. 、绝对路径）；
- 安全校验 storage key，拒绝路径穿越，解析后必须位于受控根目录内；
- 原子写入（委托 daily_report_excel.save_workbook_version）；
- 不由静态文件服务公开存储根目录（下载由 Task 7 的受控接口提供）。

不实现下载/任务调度/重试；不保存 token/手机号/微信号/原始请求体。
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from app.config import DAILY_REPORT_STORAGE_DIR
from app.services.daily_report_excel import save_workbook_version

logger = logging.getLogger(__name__)

_SUFFIX = ".xlsx"


def generate_storage_token() -> str:
    """不可预测随机段（32 hex = 128 bit 熵）。"""
    return secrets.token_hex(16)


def build_storage_key(report_type: str, report_day, token: str) -> str:
    """构造 storage key：{report_type}/{report_day}/{token}.xlsx。

    不含 merchant_id 明文、盘符、.. 或绝对路径；merchant 隔离由 DB job 记录保证。
    """
    return f"{report_type}/{report_day.isoformat()}/{token}{_SUFFIX}"


def _is_safe_segment(segment: str) -> bool:
    """合法 storage key 段：非空、非 . / ..、不以点开头。"""
    if not segment or segment in (".", ".."):
        return False
    if segment.startswith("."):
        return False
    return True


def resolve_storage_path(storage_key: str, root: Path | str | None = None) -> Path:
    """安全解析 storage key 到受控根目录内的绝对路径。

    拒绝：空、含反斜杠/盘符、绝对路径、含 .. 或隐藏段、扩展名非 .xlsx、越界。
    """
    root_resolved = Path(root or DAILY_REPORT_STORAGE_DIR).resolve()
    if not isinstance(storage_key, str) or not storage_key:
        raise ValueError("storage key 为空")
    if "\\" in storage_key or ":" in storage_key or storage_key.startswith("/"):
        raise ValueError("storage key 含非法字符")
    parts = storage_key.split("/")
    if not all(_is_safe_segment(p) for p in parts):
        raise ValueError("storage key 含非法路径段")
    if len(parts) < 2:
        raise ValueError("storage key 层级不足")
    if not storage_key.endswith(_SUFFIX):
        raise ValueError("storage key 必须以 .xlsx 结尾")
    target = root_resolved.joinpath(*parts).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError("storage key 越界存储根目录") from exc
    return target


def save_workbook_to_storage(
    workbook, storage_key: str, root: Path | str | None = None
) -> tuple[str, int]:
    """原子写入受控目录；返回 (sha256, size_bytes)。失败不留半成品。"""
    target = resolve_storage_path(storage_key, root)
    sha256, size = save_workbook_version(workbook, target)
    logger.info(
        "daily_report_storage stage=saved size=%s sha_prefix=%s segments=%s",
        size, sha256[:8], storage_key.count("/") + 1,
    )
    return sha256, size


def validate_artifact_path(storage_key: str, root: Path | str | None = None) -> Path:
    """校验已存在文件可安全下载：普通 .xlsx 文件，非目录、非符号链接/重解析点。"""
    target = resolve_storage_path(storage_key, root)
    if not target.exists():
        raise FileNotFoundError("文件不存在")
    if not target.is_file():
        raise ValueError("目标不是普通文件")
    if target.is_symlink():
        raise ValueError("拒绝符号链接")
    if target.suffix.lower() != _SUFFIX:
        raise ValueError("文件扩展名不符")
    # Windows 重解析点兜底（POSIX 无该属性则跳过）
    attrs = getattr(target.stat(), "st_file_attributes", 0)
    if attrs and attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        raise ValueError("拒绝重解析点")
    return target
