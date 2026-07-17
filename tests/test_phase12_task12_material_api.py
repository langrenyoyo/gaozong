"""Phase 12 Task 12 素材库控制面 API/Service 合同红灯。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-1 Step 2。

冻结 Task 12-3 才实现的行为：
- 回收站与活跃素材互斥（list_materials lifecycle=trash 仅返回已软删+purge_after 非空）。
- 同商户同 SHA 注册收敛到同一规范 ID（不插第二行）。
- 跨商户同 SHA 可并存（不同规范 ID）。
- 公共响应不泄露 merchant_id / storage_key / 绝对路径。
- 平台素材对普通商户只读。

红灯策略：list_materials 当前签名无 lifecycle/scope 参数 → TypeError 转断言失败；
register_material 当前按 material_id 区分不做规范 ID 去重 → 断言失败。
不出现收集/导入错误（只 import 已存在的 service/schema/异常）。只用内存 SQLite。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import AiEditMaterial
from app.services import ai_edit_service as svc
import app.models  # noqa: F401  触发全部 ORM 注册

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ctx(
    *,
    merchant_id: str = "m1",
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
) -> RequestContext:
    return RequestContext(
        user_id="u1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:ai_edit"],
        super_admin=super_admin,
        auth_mode="mock",
    )


def _client(context: RequestContext | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def _canonical_id(merchant_id: str, sha: str) -> str:
    digest = hashlib.sha256(f"{merchant_id}:{sha}".encode("utf-8")).hexdigest()
    return f"mat_{digest[:40]}"


def _try_list_trash(db, merchant_id: str):
    """调用 Task 12-3 的 list_materials 新签名；当前签名不支持 lifecycle → TypeError。"""
    return svc.list_materials(
        db, merchant_id=merchant_id, scope="merchant", lifecycle="trash",
        query=None, category=None, tag=None, min_duration=None, max_duration=None,
        created_from=None, created_to=None, sort="created_desc",
        stage=None, process_status=None, page=1, page_size=20,
    )


def test_list_trash_returns_only_deleted_materials():
    db = TestSession()
    try:
        # 活跃素材
        svc.register_material(
            db, merchant_id="m1", material_id="mat-active", media_type="video",
            source_sha256="a" * 64, agent_client_id="ax",
        )
        # 回收站素材：先注册再软删
        trash = svc.register_material(
            db, merchant_id="m1", material_id="mat-trash", media_type="video",
            source_sha256="b" * 64, agent_client_id="ax",
        )
        db.flush()
        trash.deleted_at = __import__("datetime").datetime.now()
        trash.purge_after = __import__("datetime").datetime.now()
        db.flush()
        try:
            total, rows = _try_list_trash(db, "m1")
        except TypeError:
            pytest.fail("list_materials 未支持 lifecycle=trash 回收站过滤")
        ids = [r.material_id for r in rows]
        assert "mat-trash" in ids, "回收站查询必须返回已软删素材"
        assert "mat-active" not in ids, "回收站查询不得返回活跃素材"
    finally:
        db.close()


def test_same_merchant_same_sha_returns_canonical_material():
    """同商户同 SHA 两次注册必须收敛到同一规范 ID，不插入第二行。"""
    db = TestSession()
    try:
        first = svc.register_material(
            db, merchant_id="m1", material_id="mat-a", media_type="video",
            source_sha256="a" * 64, agent_client_id="ax",
        )
        second = svc.register_material(
            db, merchant_id="m1", material_id="mat-b", media_type="video",
            source_sha256="a" * 64, agent_client_id="ax",
        )
        # 两次注册同 SHA → 同一规范 ID
        assert second.material_id == first.material_id, (
            "同商户同 SHA 必须返回同一规范 ID（当前仍按 material_id 区分）"
        )
        assert db.query(AiEditMaterial).count() == 1, "同商户同 SHA 不得插入第二行"
        # 规范 ID 由可信商户 + SHA 确定性生成
        assert first.material_id == _canonical_id("m1", "a" * 64)
    finally:
        db.close()


def test_cross_merchant_same_sha_can_coexist():
    """跨商户同 SHA 必须可并存，规范 ID 不同。"""
    db = TestSession()
    try:
        m1 = svc.register_material(
            db, merchant_id="m1", material_id="x", media_type="video",
            source_sha256="a" * 64, agent_client_id="ax",
        )
        m2 = svc.register_material(
            db, merchant_id="m2", material_id="y", media_type="video",
            source_sha256="a" * 64, agent_client_id="ax",
        )
        assert m1.material_id != m2.material_id, "跨商户同 SHA 规范 ID 必须不同"
        assert db.query(AiEditMaterial).count() == 2
    finally:
        db.close()


def test_material_out_does_not_leak_in_api_response():
    """GET /ai-edit/materials 响应不返回 internal 字段。"""
    client = _client(_ctx(merchant_id="m1"))
    db = TestSession()
    try:
        svc.register_material(
            db, merchant_id="m1", material_id="mat-1", media_type="video",
            source_sha256="a" * 64, agent_client_id="ax",
        )
        db.commit()
    finally:
        db.close()
    resp = client.get("/ai-edit/materials")
    assert resp.status_code == 200, resp.text
    body_text = resp.text
    for forbidden in ("storage_key", "merchant_id", "local_path", "absolute_path"):
        assert forbidden not in body_text, f"响应泄露内部字段: {forbidden}"


def test_platform_lifecycle_read_only_for_merchant():
    """普通商户访问 scope=platform 只允许 lifecycle=active；其他 lifecycle 拒绝。"""
    db = TestSession()
    try:
        try:
            # 商户对平台素材请求回收站视图 → AiEditStatusConflict PLATFORM_LIFECYCLE_READ_ONLY
            svc.list_materials(
                db, merchant_id="m1", scope="platform", lifecycle="trash",
                query=None, category=None, tag=None, min_duration=None, max_duration=None,
                created_from=None, created_to=None, sort="created_desc",
                stage=None, process_status=None, page=1, page_size=20,
            )
        except svc.AiEditStatusConflict as exc:
            assert "PLATFORM_LIFECYCLE_READ_ONLY" in str(exc)
        except TypeError:
            pytest.fail("list_materials 未支持 scope/lifecycle 参数")
        else:
            pytest.fail("商户不得查询平台回收站视图，必须抛 PLATFORM_LIFECYCLE_READ_ONLY")
    finally:
        db.close()
