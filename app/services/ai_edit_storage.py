"""Phase 12 AI 剪辑受控文件存储。

职责（设计 §10/§11）：
- 安全解析 storage_key 到受控根目录内的路径，拒绝路径穿越、绝对路径、盘符、
  反斜杠、符号链接与 Windows 重解析点；
- 只处理缩略图、平台公共素材和用户主动上传的云端产物；本地媒体默认留在
  小高AI微信助手所在机器，由 19000 管理，9000 不持有本地绝对路径。

复用日报存储（app/services/daily_report_storage.py）的路径穿越、哈希与大小复验语义，
不复制 .xlsx 扩展名限制（AI 剪辑素材为 .mp4/.wav/.jpg 等）。

不实现上传/下载调度；storage_key 不含 merchant_id 明文、盘符或绝对路径，
商户隔离由 DB 记录保证。
"""

from __future__ import annotations

from pathlib import Path


class AiEditStorageError(Exception):
    """受控存储解析失败。"""


def _is_safe_segment(segment: str) -> bool:
    """合法 storage_key 段：非空、非 . / ..、不以点开头。"""
    if not segment or segment in (".", ".."):
        return False
    return not segment.startswith(".")


def resolve_ai_edit_storage_key(storage_key: str, root: Path | str) -> Path:
    """安全解析 storage_key 到受控根目录内的绝对路径。

    拒绝：空、含反斜杠/盘符、绝对路径、.. 或隐藏段、层级不足、越界、符号链接/重解析点。
    ponytail: 复用 daily_report_storage 的 _is_safe_segment + relative_to 语义；
              中间目录符号链接需文件系统层加固，此处仅校验最终路径段，不覆盖中间目录攻击。
    """
    root_resolved = Path(root).resolve()
    if not isinstance(storage_key, str) or not storage_key:
        raise AiEditStorageError("AI_EDIT_STORAGE_EMPTY")
    if "\\" in storage_key or ":" in storage_key or storage_key.startswith("/"):
        raise AiEditStorageError("AI_EDIT_STORAGE_INVALID_CHAR")
    parts = storage_key.split("/")
    if not all(_is_safe_segment(p) for p in parts):
        raise AiEditStorageError("AI_EDIT_STORAGE_INVALID_SEGMENT")
    if len(parts) < 2:
        raise AiEditStorageError("AI_EDIT_STORAGE_TOO_SHALLOW")

    raw = root_resolved.joinpath(*parts)
    target = raw.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise AiEditStorageError("AI_EDIT_STORAGE_OUT_OF_ROOT") from exc
    # 拒最终路径段为符号链接（resolve 会跟随，故先查原始路径属性）
    if raw.is_symlink():
        raise AiEditStorageError("AI_EDIT_STORAGE_LINK_REJECTED")
    # Windows 重解析点兜底（POSIX 无该属性则跳过）
    attrs = getattr(raw.stat(), "st_file_attributes", 0) if raw.exists() else 0
    if attrs and attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        raise AiEditStorageError("AI_EDIT_STORAGE_LINK_REJECTED")
    return target
