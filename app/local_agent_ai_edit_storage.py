"""Phase 12 Task 7 19000 本地受管素材存储。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8/§12。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7 Step 2。

职责：
- 流式导入素材到受管目录，原文件不变；
- 路径穿越/符号链接/绝对路径拒绝；material_id 不允许斜杠段；
- 磁盘预检与原子写（临时文件 + os.replace）；
- 7 天回收站（deleted_at + purge_after）；
- 活动任务引用禁止删除；
- 本地清单只保存受管相对路径，不暴露绝对路径。

一期单进程单写者，不新增本地数据库。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_RECYCLE_BIN_DAYS = 7
_MANIFEST_NAME = "materials.json"


class LocalAiEditStorageError(Exception):
    """本地受管存储失败（携带稳定错误码）。"""

    def __init__(self, failure_code: str):
        super().__init__(failure_code)
        self.failure_code = failure_code


@dataclass
class MaterialRecord:
    material_id: str
    relative_path: str
    sha256: str
    size_bytes: int
    deleted_at: datetime | None = None
    purge_after: datetime | None = None


def _is_safe_segment(segment: str, *, max_len: int = 128) -> bool:
    """合法受控标识段：非空、无斜杠/反斜杠/盘符/.. 段、不以点开头。

    用于 material_id / merchant_id / job_id / attempt_id 等路径拼接段，
    防止 ../ 穿越、绝对路径、盘符注入。
    """
    if not segment or len(segment) > max_len:
        return False
    if any(c in segment for c in "/\\:"):
        return False
    if segment in (".", "..") or segment.startswith("."):
        return False
    return False if segment.startswith(" ") else True


def _is_safe_material_id(material_id: str) -> bool:
    """合法 material_id（单段，无斜杠）。"""
    return _is_safe_segment(material_id)


def merchant_storage_root(root: Path, merchant_id: str) -> Path:
    """商户隔离根：storage_root/{merchant_id}/。拒绝非法 merchant_id。"""
    if not _is_safe_segment(merchant_id):
        raise LocalAiEditStorageError("INVALID_MERCHANT_ID")
    base = Path(root).resolve()
    target = base / merchant_id
    resolved = target.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise LocalAiEditStorageError("MERCHANT_PATH_OUT_OF_ROOT") from exc
    return resolved


def resolve_managed_material_path(root: Path, material_id: str) -> Path:
    """解析受管素材路径，拒绝穿越/符号链接/绝对路径。

    root 已是商户隔离根（merchant_storage_root 的结果）。
    """
    if not _is_safe_material_id(material_id):
        raise LocalAiEditStorageError("INVALID_MATERIAL_ID")
    managed_root = Path(root).resolve() / "materials"
    target = managed_root / material_id / "source"
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(managed_root.resolve())
    except ValueError as exc:
        raise LocalAiEditStorageError("PATH_OUT_OF_ROOT") from exc
    # 拒绝符号链接（受管根内不应有符号链接）
    if target.is_symlink() or managed_root.is_symlink():
        raise LocalAiEditStorageError("SYMLINK_REJECTED")
    return target


def _write_stream_to_temp_and_replace(
    stream: io.IOBase, destination: Path, expected_size: int
) -> int:
    """流式写入临时文件，校验大小后原子替换。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".import_", suffix=".tmp", dir=str(destination.parent)
    )
    total = 0
    try:
        with os.fdopen(fd, "wb") as f:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
        if expected_size is not None and total != expected_size:
            raise LocalAiEditStorageError("SIZE_MISMATCH")
        os.replace(tmp, destination)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise LocalAiEditStorageError("DISK_WRITE_FAILED") from exc
    except LocalAiEditStorageError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return total


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest(root: Path) -> dict:
    manifest = Path(root).resolve() / _MANIFEST_NAME
    if not manifest.exists():
        return {"materials": []}
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"materials": []}


def _save_manifest_atomic(root: Path, data: dict) -> None:
    manifest = Path(root).resolve() / _MANIFEST_NAME
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".materials_", suffix=".tmp", dir=str(manifest.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, manifest)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _upsert_manifest(root: Path, record: MaterialRecord) -> None:
    data = _load_manifest(root)
    materials = data.get("materials", [])
    # 替换同 material_id 记录
    materials = [m for m in materials if m.get("material_id") != record.material_id]
    materials.append({
        "material_id": record.material_id,
        "relative_path": record.relative_path,
        "sha256": record.sha256,
        "size_bytes": record.size_bytes,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
        "purge_after": record.purge_after.isoformat() if record.purge_after else None,
    })
    data["materials"] = materials
    _save_manifest_atomic(root, data)


def _find_manifest(root: Path, material_id: str) -> dict | None:
    for m in _load_manifest(root).get("materials", []):
        if m.get("material_id") == material_id:
            return m
    return None


# 活动引用集合（一期内存 + 持久化到 active_refs.json）
_ACTIVE_REFS_NAME = "active_refs.json"


def _load_active_refs(root: Path) -> dict[str, list[str]]:
    path = Path(root).resolve() / _ACTIVE_REFS_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_active_refs(root: Path, refs: dict[str, list[str]]) -> None:
    path = Path(root).resolve() / _ACTIVE_REFS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".active_refs_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(refs, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def mark_active_reference(root: Path, material_id: str, *, job_id: str, active: bool) -> None:
    """标记/取消素材的活动任务引用（删除前校验）。"""
    refs = _load_active_refs(root)
    jobs = set(refs.get(material_id, []))
    if active:
        jobs.add(job_id)
    else:
        jobs.discard(job_id)
    refs[material_id] = sorted(jobs)
    _save_active_refs(root, refs)


def import_material(
    stream: io.IOBase, *, material_id: str, expected_size: int, root: Path
) -> MaterialRecord:
    """流式导入素材到受管目录（原文件不变），自算 SHA-256。"""
    destination = resolve_managed_material_path(root, material_id)
    try:
        size = _write_stream_to_temp_and_replace(stream, destination, expected_size)
    except LocalAiEditStorageError:
        raise
    sha = _sha256_file(destination)
    rel = destination.relative_to(Path(root).resolve()).as_posix()
    record = MaterialRecord(
        material_id=material_id, relative_path=rel,
        sha256=sha, size_bytes=size,
    )
    _upsert_manifest(root, record)
    return record


def list_materials(root: Path) -> list[MaterialRecord]:
    """列素材（只返回受管相对路径，不暴露绝对路径）。"""
    data = _load_manifest(root)
    out: list[MaterialRecord] = []
    for m in data.get("materials", []):
        out.append(MaterialRecord(
            material_id=m["material_id"],
            relative_path=m["relative_path"],
            sha256=m["sha256"],
            size_bytes=m.get("size_bytes", 0),
            deleted_at=datetime.fromisoformat(m["deleted_at"]) if m.get("deleted_at") else None,
            purge_after=datetime.fromisoformat(m["purge_after"]) if m.get("purge_after") else None,
        ))
    return out


def soft_delete_material(root: Path, material_id: str) -> MaterialRecord:
    """软删除素材：活动引用禁止删除，否则进 7 天回收站。"""
    record = _find_manifest(root, material_id)
    if record is None or record.get("deleted_at"):
        raise LocalAiEditStorageError("MATERIAL_NOT_FOUND")
    refs = _load_active_refs(root)
    if refs.get(material_id):
        raise LocalAiEditStorageError("MATERIAL_IN_USE_ACTIVE_JOB")
    now = datetime.now()
    purge_after = now + timedelta(days=_RECYCLE_BIN_DAYS)
    rec = MaterialRecord(
        material_id=record["material_id"],
        relative_path=record["relative_path"],
        sha256=record["sha256"],
        size_bytes=record.get("size_bytes", 0),
        deleted_at=now,
        purge_after=purge_after,
    )
    _upsert_manifest(root, rec)
    return rec
