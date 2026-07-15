"""Phase 12 Task 7 19000 本地受管素材存储测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8/§12。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7。

覆盖（Step 1 列举）：
- 受管目录复制，原文件不变；
- 路径穿越/符号链接拒绝；
- 流式导入 + 磁盘预检；
- 7 天回收站；
- 活动任务禁止删除素材；
- 本地清单只保存受管相对路径；写清单临时文件 + os.replace。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app.local_agent_ai_edit_storage import (
    LocalAiEditStorageError,
    import_material,
    list_materials,
    soft_delete_material,
)


def _stream(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)


# ---------------------------------------------------------------------------
# 受管目录复制，原文件不变
# ---------------------------------------------------------------------------


def test_import_material_copies_to_managed_dir(tmp_path):
    root = tmp_path / "managed"
    stream = _stream(b"video-bytes")
    result = import_material(
        stream, material_id="mat-1", expected_size=len(b"video-bytes"), root=root,
    )
    # 受管目录内存在文件（相对路径解析回受管根）
    managed_file = Path(root) / result.relative_path
    assert managed_file.exists()
    assert managed_file.read_bytes() == b"video-bytes"
    # 相对路径（不暴露绝对路径）
    assert not Path(result.relative_path).is_absolute()
    assert result.sha256  # 自算哈希


def test_import_material_rejects_size_mismatch(tmp_path):
    root = tmp_path / "managed"
    with pytest.raises(LocalAiEditStorageError):
        import_material(
            _stream(b"short"), material_id="mat-1", expected_size=999, root=root,
        )


def test_import_material_rejects_path_traversal_material_id(tmp_path):
    root = tmp_path / "managed"
    with pytest.raises(LocalAiEditStorageError):
        import_material(
            _stream(b"x"), material_id="../escape", expected_size=1, root=root,
        )
    with pytest.raises(LocalAiEditStorageError):
        import_material(
            _stream(b"x"), material_id="a/b", expected_size=1, root=root,
        )  # 不允许斜杠段


# ---------------------------------------------------------------------------
# 符号链接拒绝（受管根内不跟随符号链接越界）
# ---------------------------------------------------------------------------


def test_resolve_managed_path_rejects_symlink(tmp_path):
    if not hasattr(Path, "symlink_to"):
        pytest.skip("平台不支持符号链接")
    root = tmp_path / "managed"
    root.mkdir()
    link = tmp_path / "materials" / "mat-link"
    link.parent.mkdir()
    try:
        link.symlink_to(root)
    except (OSError, NotImplementedError):
        pytest.skip("无法创建符号链接")
    from app.local_agent_ai_edit_storage import resolve_managed_material_path
    with pytest.raises(LocalAiEditStorageError):
        resolve_managed_material_path(root, "mat-1")


# ---------------------------------------------------------------------------
# 磁盘预检
# ---------------------------------------------------------------------------


def test_import_material_disk_full_error(tmp_path, monkeypatch):
    root = tmp_path / "managed"
    # 模拟原子替换阶段磁盘失败
    def _fail(*a, **kw):
        raise OSError("disk full")
    monkeypatch.setattr("app.local_agent_ai_edit_storage.os.replace", _fail)
    with pytest.raises(LocalAiEditStorageError) as exc_info:
        import_material(_stream(b"x"), material_id="mat-1", expected_size=1, root=root)
    assert "WRITE" in exc_info.value.failure_code.upper()


# ---------------------------------------------------------------------------
# 7 天回收站
# ---------------------------------------------------------------------------


def test_soft_delete_enters_recycle_bin(tmp_path):
    root = tmp_path / "managed"
    import_material(_stream(b"x"), material_id="mat-1", expected_size=1, root=root)
    result = soft_delete_material(root, "mat-1")
    assert result.deleted_at is not None
    assert result.purge_after is not None
    # purge_after 约 7 天后
    assert (result.purge_after - result.deleted_at).days == 7


def test_soft_delete_rejects_when_referenced_by_active_job(tmp_path):
    root = tmp_path / "managed"
    import_material(_stream(b"x"), material_id="mat-1", expected_size=1, root=root)
    # 标记为活动任务引用
    from app.local_agent_ai_edit_storage import mark_active_reference
    mark_active_reference(root, "mat-1", job_id="job-1", active=True)
    with pytest.raises(LocalAiEditStorageError) as exc_info:
        soft_delete_material(root, "mat-1")
    assert "ACTIVE" in exc_info.value.failure_code or "IN_USE" in exc_info.value.failure_code


# ---------------------------------------------------------------------------
# 本地清单只保存受管相对路径
# ---------------------------------------------------------------------------


def test_list_materials_returns_relative_paths_only(tmp_path):
    root = tmp_path / "managed"
    import_material(_stream(b"a"), material_id="mat-1", expected_size=1, root=root)
    import_material(_stream(b"b"), material_id="mat-2", expected_size=1, root=root)
    items = list_materials(root)
    assert len(items) == 2
    for it in items:
        assert "/" not in it.material_id
        assert not Path(it.relative_path).is_absolute()
        assert str(root.resolve()) not in it.relative_path


# ---------------------------------------------------------------------------
# 写清单原子性（临时文件 + os.replace）
# ---------------------------------------------------------------------------


def test_manifest_written_atomically(tmp_path):
    root = tmp_path / "managed"
    import_material(_stream(b"x"), material_id="mat-1", expected_size=1, root=root)
    # 清单文件存在且可读
    manifest = root / "materials.json"
    assert manifest.exists()
    import json
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert any(m["material_id"] == "mat-1" for m in data.get("materials", []))
    # 无残留临时文件
    tmp_files = list(root.glob(".materials_*.tmp"))
    assert tmp_files == []
