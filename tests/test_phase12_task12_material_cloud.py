"""Phase 12 Task 12 云端原子存储合同红灯。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-1 Step 3（云端部分）/ Task 12-6。

冻结 Task 12-6 才实现的行为：
- 流式上传大小/SHA 不符 → AiEditStorageError，临时文件清理。
- store_material_stream 不存在 → getattr 返回 None → 断言失败。

红灯策略：store_material_stream / make_storage_service 当前不存在 → 断言失败，不收集错误。
只用临时目录，不连任何数据库或网络。
"""

from __future__ import annotations

import io

import pytest

from app.services.ai_edit_storage import AiEditStorageError


def test_store_material_stream_function_exists():
    from app.services import ai_edit_storage as storage

    func = getattr(storage, "store_material_stream", None)
    assert func is not None, "store_material_stream 缺失（Task 12-6 实现）"


def test_build_material_storage_key_function_exists():
    from app.services import ai_edit_storage as storage

    func = getattr(storage, "build_material_storage_key", None)
    assert func is not None, "build_material_storage_key 缺失（Task 12-6 实现）"


def test_cloud_upload_failure_keeps_local_only(tmp_path):
    """大小/SHA 不符的上传必须抛 AiEditStorageError 并清理临时文件。"""
    from app.services import ai_edit_storage as storage

    store = getattr(storage, "store_material_stream", None)
    if store is None:
        pytest.fail("store_material_stream 缺失（Task 12-6 实现）")
    # 构造一个同步可调用的失败路径：用错误的 expected_sha256
    import inspect

    async def _run():
        async def _chunks():
            yield b"bad"
        try:
            await store(
                root=tmp_path, merchant_id="m1", material_id="mat1",
                chunks=_chunks(), expected_size=4,
                expected_sha256="0" * 64, suffix="mp4",
                max_bytes=1024 * 1024 * 1024,
            )
        except AiEditStorageError:
            return True
        return False

    import asyncio
    ok = asyncio.run(_run())
    assert ok, "大小/SHA 不符必须抛 AiEditStorageError"
    # 临时文件不得残留（target 未原子替换成功）
    uploads = [p for p in tmp_path.rglob("*") if p.name.startswith(".upload_")]
    assert uploads == [], "上传失败必须清理临时文件"


def test_material_storage_key_uses_merchant_hash():
    """存储键不得含明文 merchant_id，必须用不可逆商户哈希目录。"""
    from app.services import ai_edit_storage as storage

    build = getattr(storage, "build_material_storage_key", None)
    if build is None:
        pytest.fail("build_material_storage_key 缺失")
    key = build(merchant_id="m_secret_123", material_id="mat1", suffix="mp4")
    assert "m_secret_123" not in key, "存储键不得含明文 merchant_id"
    assert key.startswith("materials/"), "存储键必须以 materials/ 开头"
    assert key.endswith("/source.mp4")
