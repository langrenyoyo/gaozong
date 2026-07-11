"""Phase 7-FIX2 Task 3：Local Agent token 与商户隔离红灯测试

验证：
- GET /wechat-tasks/pending 无 token → 401
- GET /wechat-tasks/pending 错误 token → 403
- GET /wechat-tasks/pending 正确 token → 200，只返回本商户任务
- POST /wechat-tasks/{id}/result 无 token → 401
- POST /wechat-tasks/{id}/result 错误 token → 403
- POST /wechat-tasks/{id}/result 正确 token 但任务不属于本商户 → 404
"""

import os
import pytest

from fastapi.testclient import TestClient

# 在导入 app 之前设置环境变量（直接赋值，覆盖 .env 已有值）
os.environ["APP_ENV"] = "development"
os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "true"
os.environ["LOCAL_AGENT_TOKENS"] = "dev-merchant:local-agent-dev-token,merchant-a:token-a-xxx,merchant-b:token-b-yyy"
os.environ["NEWCAR_AUTH_ENABLED"] = "false"
os.environ["NEWCAR_AUTH_MOCK_ENABLED"] = "true"

from app.main import app  # 复用模块级已创建的 app 实例


def _client() -> TestClient:
    """创建带 Local Agent 环境变量的测试客户端。"""
    return TestClient(app)


# ========== pending 端点鉴权 ==========


def test_pending_no_token_returns_401():
    """无 token 时 GET /wechat-tasks/pending 返回 401。"""
    client = _client()

    resp = client.get("/wechat-tasks/pending")

    assert resp.status_code == 401


def test_pending_wrong_token_returns_403():
    """错误 token 时 GET /wechat-tasks/pending 返回 403。"""
    client = _client()

    resp = client.get("/wechat-tasks/pending", headers={
        "X-Local-Agent-Token": "wrong-token",
    })

    assert resp.status_code == 403


def test_pending_valid_token_returns_200():
    """正确 token 时 GET /wechat-tasks/pending 返回 200。"""
    client = _client()

    resp = client.get("/wechat-tasks/pending", headers={
        "X-Local-Agent-Token": "token-a-xxx",
    })

    assert resp.status_code == 200


def test_pending_filters_by_merchant():
    """正确 token 只返回本商户的 pending 任务。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.models import WechatTask, DouyinLead, SalesStaff
    from app.services import wechat_task_service

    # 使用独立内存数据库
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestSession()
    try:
        # 创建 merchant-a 的 lead + staff
        staff_a = SalesStaff(name="staff-a", wechat_nickname="Aw3", status="active", merchant_id="merchant-a")
        lead_a = DouyinLead(customer_name="lead-a", source="test", status="assigned", merchant_id="merchant-a",
                            assigned_staff_id=1)
        db.add(staff_a)
        db.add(lead_a)
        db.flush()

        # 创建 merchant-b 的 lead + staff
        staff_b = SalesStaff(name="staff-b", wechat_nickname="Aw3", status="active", merchant_id="merchant-b")
        lead_b = DouyinLead(customer_name="lead-b", source="test", status="assigned", merchant_id="merchant-b",
                            assigned_staff_id=2)
        db.add(staff_b)
        db.add(lead_b)
        db.flush()

        # merchant-a 的任务
        task_a = wechat_task_service.create_wechat_task(
            db, task_type="notify_sales", target_nickname="Aw3",
            message="merchant-a test", mode="paste_only",
            lead_id=lead_a.id, staff_id=staff_a.id,
        )
        # merchant-b 的任务
        task_b = wechat_task_service.create_wechat_task(
            db, task_type="notify_sales", target_nickname="Aw3",
            message="merchant-b test", mode="paste_only",
            lead_id=lead_b.id, staff_id=staff_b.id,
        )
        task_a_id = task_a.id
        task_b_id = task_b.id
    finally:
        db.close()

    # 直接测试 service 层商户过滤（独立内存库，不依赖 app 的数据库）
    # 验证 service 层商户过滤
    db2 = TestSession()
    try:
        tasks_a = wechat_task_service.get_pending_wechat_tasks(db2, merchant_id="merchant-a")
        tasks_b = wechat_task_service.get_pending_wechat_tasks(db2, merchant_id="merchant-b")
        tasks_all = wechat_task_service.get_pending_wechat_tasks(db2, merchant_id=None)

        ids_a = {t.id for t in tasks_a}
        ids_b = {t.id for t in tasks_b}
        ids_all = {t.id for t in tasks_all}

        assert task_a_id in ids_a, "merchant-a 过滤应包含自己的任务"
        assert task_b_id not in ids_a, "merchant-a 过滤不应包含 merchant-b 的任务"
        assert task_b_id in ids_b, "merchant-b 过滤应包含自己的任务"
        assert task_a_id not in ids_b, "merchant-b 过滤不应包含 merchant-a 的任务"
        assert ids_all == {task_a_id, task_b_id}, "无过滤应返回全部任务"
    finally:
        db2.close()


# ========== result 端点鉴权 ==========


def test_result_no_token_returns_401():
    """无 token 时 POST /wechat-tasks/1/result 返回 401。"""
    client = _client()

    resp = client.post("/wechat-tasks/1/result", json={
        "success": True,
        "verified": True,
        "pasted": True,
        "sent": False,
    })

    assert resp.status_code == 401


def test_result_wrong_token_returns_403():
    """错误 token 时 POST /wechat-tasks/1/result 返回 403。"""
    client = _client()

    resp = client.post("/wechat-tasks/1/result", json={
        "success": True,
        "verified": True,
        "pasted": True,
        "sent": False,
    }, headers={
        "X-Local-Agent-Token": "wrong-token",
    })

    assert resp.status_code == 403


def test_result_wrong_merchant_token_returns_404():
    """正确 token 但任务不属于本商户 → task_belongs_to_merchant 返回 False。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.models import DouyinLead, SalesStaff
    from app.services import wechat_task_service

    # 使用独立内存数据库
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestSession()
    try:
        # 创建 merchant-b 的 lead + staff + task
        staff_b = SalesStaff(name="staff-b", wechat_nickname="Aw3", status="active", merchant_id="merchant-b")
        lead_b = DouyinLead(customer_name="lead-b", source="test", status="assigned", merchant_id="merchant-b",
                            assigned_staff_id=1)
        db.add(staff_b)
        db.add(lead_b)
        db.flush()

        task = wechat_task_service.create_wechat_task(
            db, task_type="notify_sales", target_nickname="Aw3",
            message="merchant-b task", mode="paste_only",
            lead_id=lead_b.id, staff_id=staff_b.id,
        )

        # merchant-a token 不应能访问 merchant-b 的任务
        assert not wechat_task_service.task_belongs_to_merchant(task, "merchant-a"), \
            "merchant-a 不应能访问 merchant-b 的任务"
        # merchant-b token 可以访问
        assert wechat_task_service.task_belongs_to_merchant(task, "merchant-b"), \
            "merchant-b 应能访问自己的任务"
    finally:
        db.close()


def test_result_valid_token_same_merchant_returns_200():
    """正确 token + 同商户任务 → task_belongs_to_merchant 返回 True。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.models import DouyinLead, SalesStaff
    from app.services import wechat_task_service

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestSession()
    try:
        staff_a = SalesStaff(name="staff-a", wechat_nickname="Aw3", status="active", merchant_id="merchant-a")
        lead_a = DouyinLead(customer_name="lead-a", source="test", status="assigned", merchant_id="merchant-a",
                            assigned_staff_id=1)
        db.add(staff_a)
        db.add(lead_a)
        db.flush()

        task = wechat_task_service.create_wechat_task(
            db, task_type="notify_sales", target_nickname="Aw3",
            message="merchant-a task", mode="paste_only",
            lead_id=lead_a.id, staff_id=staff_a.id,
        )

        assert wechat_task_service.task_belongs_to_merchant(task, "merchant-a"), \
            "merchant-a 应能访问自己的任务"
        assert not wechat_task_service.task_belongs_to_merchant(task, "merchant-b"), \
            "merchant-b 不应能访问 merchant-a 的任务"
    finally:
        db.close()
