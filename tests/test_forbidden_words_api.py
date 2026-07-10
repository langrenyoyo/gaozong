"""违禁词超管管理 API 测试。

覆盖 Phase 2 执行包 Task 3 要求的 8 个场景：
登录校验、权限校验、词库列表、创建词条、大小写等价查重、更新、启停、条件查询。
权限码复用既有 auto_wechat:admin:forbidden_words，不新增权限码。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import ForbiddenWord, ForbiddenWordLibrary


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(
    *,
    super_admin: bool = True,
    user_id: str = "admin-1",
    permission_codes: list[str] | None = None,
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        username=user_id,
        display_name="管理员",
        merchant_id="admin-merchant",
        merchant_ids=["admin-merchant"],
        permission_codes=permission_codes
        if permission_codes is not None
        else ["auto_wechat:admin:forbidden_words"],
        super_admin=super_admin,
    )


def _client(context: RequestContext | None = None, *, auth_error: HTTPException | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if auth_error is not None:
        app.dependency_overrides[get_request_context_required] = lambda: (
            _ for _ in ()
        ).throw(auth_error)
    elif context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def _seed_library(db, *, library_key: str = "used_car_sales_base", enabled: bool = True) -> ForbiddenWordLibrary:
    lib = ForbiddenWordLibrary(
        library_key=library_key,
        name="二手车销售基础违禁词",
        scope="global",
        enabled=enabled,
        sort_order=1,
    )
    db.add(lib)
    db.commit()
    return lib


def test_admin_forbidden_word_api_requires_login():
    client = _client(
        auth_error=HTTPException(status_code=401, detail={"code": "TOKEN_MISSING", "message": "未登录"}),
    )
    resp = client.get("/admin/forbidden-word-libraries")
    assert resp.status_code == 401


def test_admin_forbidden_word_api_requires_permission():
    client = _client(
        _context(super_admin=False, permission_codes=["auto_wechat:admin:ai_reply_records"]),
    )
    resp = client.get("/admin/forbidden-word-libraries")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_admin_lists_libraries():
    db = TestSession()
    _seed_library(db)
    db.close()

    client = _client(_context())
    resp = client.get("/admin/forbidden-word-libraries")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    keys = [item["library_key"] for item in items]
    assert "used_car_sales_base" in keys


def test_admin_creates_word_under_library_key():
    db = TestSession()
    _seed_library(db)
    db.close()

    client = _client(_context())
    resp = client.post(
        "/admin/forbidden-words",
        json={
            "library_key": "used_car_sales_base",
            "word": "现车很多",
            "safe_word": "可到店详询",
            "severity": "medium",
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["word"] == "现车很多"
    assert resp.json()["data"]["safe_word"] == "可到店详询"

    # 校验已落库
    db2 = TestSession()
    word = db2.query(ForbiddenWord).filter_by(word="现车很多").first()
    assert word is not None
    assert word.safe_word == "可到店详询"
    assert word.severity == "medium"
    db2.close()


def test_admin_rejects_duplicate_word_case_insensitive():
    db = TestSession()
    lib = _seed_library(db)
    db.add(ForbiddenWord(library_id=lib.id, word="Loan", safe_word="financing", enabled=True))
    db.commit()
    db.close()

    client = _client(_context())
    resp = client.post(
        "/admin/forbidden-words",
        json={
            "library_key": "used_car_sales_base",
            "word": "loan",
            "safe_word": "other",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "WORD_DUPLICATED"


def test_admin_updates_word_and_safe_word():
    db = TestSession()
    lib = _seed_library(db)
    word = ForbiddenWord(library_id=lib.id, word="现车", safe_word="现货", enabled=True)
    db.add(word)
    db.commit()
    word_id = word.id
    db.close()

    client = _client(_context())
    resp = client.put(
        f"/admin/forbidden-words/{word_id}",
        json={"safe_word": "可咨询"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["safe_word"] == "可咨询"


def test_admin_toggles_word_enabled():
    db = TestSession()
    lib = _seed_library(db)
    word = ForbiddenWord(library_id=lib.id, word="现车", safe_word="现货", enabled=True)
    db.add(word)
    db.commit()
    word_id = word.id
    db.close()

    client = _client(_context())
    resp = client.post(
        f"/admin/forbidden-words/{word_id}/toggle",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False


def test_admin_lists_words_with_filters():
    db = TestSession()
    lib = _seed_library(db)
    db.add(ForbiddenWord(library_id=lib.id, word="现车", safe_word="现货", enabled=True))
    db.add(ForbiddenWord(library_id=lib.id, word="贷款", safe_word="金融方案", enabled=False))
    db.commit()
    db.close()

    client = _client(_context())
    # enabled=true 过滤
    resp = client.get("/admin/forbidden-words?enabled=true")
    assert resp.status_code == 200
    words = [item["word"] for item in resp.json()["data"]["items"]]
    assert "现车" in words
    assert "贷款" not in words

    # library_key 过滤
    resp2 = client.get("/admin/forbidden-words?library_key=used_car_sales_base")
    assert resp2.status_code == 200
    assert resp2.json()["data"]["total"] >= 1
