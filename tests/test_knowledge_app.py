"""统一知识库训练独立能力服务测试（Phase 3-C）。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  触发 ORM 注册
from app.database import Base, get_db
from app.models import DouyinAuthorizedAccount, KnowledgeCategory


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    """每个测试前重建表，保证独立能力服务测试隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client(*, merchant_id: str | None = "merchant-a", permissions: list[str] | None = None) -> TestClient:
    from apps.knowledge.dependencies import get_gateway_context
    from apps.knowledge.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": merchant_id,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "super_admin": False,
        "permission_codes": permissions or ["auto_wechat:ai_agents"],
        "source_system": "new_car_project",
    }
    return TestClient(app)


def _insert_category(*, merchant_id: str, category_key: str, name: str) -> None:
    db = TestSession()
    try:
        db.add(
            KnowledgeCategory(
                merchant_id=merchant_id,
                tenant_id=None,
                category_key=category_key,
                name=name,
                scope_type="merchant",
                is_base=0,
                status="active",
                sort_order=100,
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_account(*, open_id: str = "account-open-1", merchant_id: str = "merchant-a") -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id=open_id,
                merchant_id=merchant_id,
                bind_status=1,
                account_name="测试企业号",
            )
        )
        db.commit()
    finally:
        db.close()


class FakeRagClient:
    """模拟 9100 RAG client。"""

    def __init__(self):
        self.calls = []

    def create_rag_document(self, *, context, request):
        self.calls.append({"method": "create_rag_document", "context": context, "request": request})
        return {"document_id": 101, "status": "created"}

    def train_rag(self, *, context, request):
        self.calls.append({"method": "train_rag", "context": context, "request": request})
        return {"training_run_id": 202, "status": "completed"}


def test_knowledge_app_root_health_openapi_and_categories():
    _insert_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")
    _insert_category(merchant_id="merchant-b", category_key="premium_bba", name="商户B-BBA")
    client = _client()

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "knowledge"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "统一知识库训练"

    categories = client.get("/api/knowledge/categories?merchant_id=merchant-b")
    assert categories.status_code == 200
    data = categories.json()["data"]
    assert [item["category_key"] for item in data] == ["base", "premium_bba"]
    assert data[1]["name"] == "精品BBA"


def test_knowledge_app_create_category_is_locked_and_rejects_missing_context():
    response = _client().post(
        "/api/knowledge/categories",
        json={"merchant_id": "merchant-b", "category_key": " premium_bba ", "name": "精品BBA"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_APP_CATEGORY_WRITE_DISABLED"

    db = TestSession()
    try:
        assert db.query(KnowledgeCategory).filter_by(category_key="premium_bba").count() == 0
    finally:
        db.close()

    missing = _client(merchant_id=None).get("/api/knowledge/categories")
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "MERCHANT_ID_REQUIRED"


def test_knowledge_app_categories_keep_legacy_ai_agents_permission_compatible():
    response = _client(permissions=["auto_wechat:ai_agents"]).get("/api/knowledge/categories")

    assert response.status_code == 200
    assert response.json()["data"][0]["category_key"] == "base"


def test_knowledge_app_rejects_historical_knowledge_permission():
    response = _client(permissions=["auto_wechat:knowledge"]).get("/api/knowledge/categories")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_knowledge_app_rag_document_write_is_locked(monkeypatch):
    from apps.knowledge import routers

    fake_client = FakeRagClient()
    monkeypatch.setattr(routers, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account(open_id="account-open-1", merchant_id="merchant-a")

    response = _client(permissions=["auto_wechat:douyin_ai_cs"]).post(
        "/api/knowledge/rag/documents",
        json={
            "account_open_id": "account-open-1",
            "tenant_id": "forged-tenant",
            "merchant_id": "forged-merchant",
            "douyin_account_id": "forged-account",
            "allowed_category_keys": ["forged"],
            "title": "精品BBA话术",
            "content": "客户咨询宝马5系时，引导留下联系方式。",
            "category_key": "base",
            "category": "旧分类展示",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_APP_RAG_WRITE_DISABLED"
    assert fake_client.calls == []

def test_knowledge_app_rag_train_is_locked(monkeypatch):
    from apps.knowledge import routers

    fake_client = FakeRagClient()
    monkeypatch.setattr(routers, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account(open_id="account-open-1", merchant_id="merchant-a")
    _insert_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")

    response = _client(permissions=["auto_wechat:douyin_ai_cs"]).post(
        "/api/knowledge/rag/train",
        json={
            "account_open_id": "account-open-1",
            "tenant_id": "forged-tenant",
            "merchant_id": "forged-merchant",
            "category_key": "premium_bba",
            "force_rebuild": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_APP_RAG_TRAIN_DISABLED"
    assert fake_client.calls == []
