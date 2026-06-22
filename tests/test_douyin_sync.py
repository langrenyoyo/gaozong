"""P4-1/P4-2/P4-3：douyinAPI 线索同步测试

P4-1：dry_run=true 预览模式
P4-2：dry_run=false 写库模式
P4-3：auto_assign=true 自动分配联动

使用 mock，不依赖真实 douyinAPI 服务。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import DouyinLead, SalesStaff, CheckConfig, ReplyCheck
from app.config import DEFAULT_CONFIGS
from app.schemas import DouyinSyncRequest, DouyinSyncResponse
from app.services.douyin_sync_service import preview_sync_leads
from app.integrations.douyin_api_client import DouyinApiError

# 使用内存数据库
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _db():
    """创建测试用数据库会话"""
    return TestSession()


def _db_session():
    """API 测试专用数据库会话，避免误连默认开发库。"""
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def setup_module(module):
    """模块级初始化"""
    Base.metadata.create_all(bind=test_engine)
    db = _db()
    # 写入默认配置
    for key, value in DEFAULT_CONFIGS.items():
        db.add(CheckConfig(config_key=key, config_value=value, description=f"测试配置: {key}"))
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


# ---------- 测试用的 mock 数据 ----------

MOCK_LEADS_RESPONSE = {
    "items": [
        {
            "id": 1,
            "open_id": "test_open_id_001",
            "display_name": "张三",
            "phone": "13800138001",
            "last_interaction_record": "你好，我想咨询产品价格",
            "lead_status": "pending",
            "lead_type": "私信",
            "lead_channel": "企业号",
        },
    ],
    "total": 1,
    "page": 1,
    "page_size": 50,
}


# ========== 测试用例 ==========


def test_douyin_sync_preview_create():
    """测试 1：新线索 → action=create"""
    db = _db()

    # mock fetch_leads 返回新 open_id
    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_LEADS_RESPONSE

        request = DouyinSyncRequest(dry_run=True, limit=50, lead_status="pending")
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.dry_run is True
    assert result.fetched == 1
    assert result.mapped == 1
    assert result.created == 0  # dry_run 不写库
    assert len(result.items) == 1

    item = result.items[0]
    assert item.action == "create"
    assert item.source_id == "test_open_id_001"
    assert item.customer_name == "张三"
    assert item.content == "你好，我想咨询产品价格"
    assert item.source == "douyin"
    assert item.lead_type == "私信"
    assert item.customer_contact == "13800138001"

    db.close()


def test_douyin_sync_preview_update_pending():
    """测试 2：本地已有 pending 线索 → action=update"""
    db = _db()

    # 先在本地创建一条 pending 线索
    existing = DouyinLead(
        source="douyin",
        source_id="test_open_id_001",
        customer_name="旧名称",
        status="pending",
    )
    db.add(existing)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_LEADS_RESPONSE

        request = DouyinSyncRequest(dry_run=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.mapped == 1

    item = result.items[0]
    assert item.action == "update"
    assert "pending" in item.reason

    # 确认本地数据未变（dry_run 不写库）
    db.refresh(existing)
    assert existing.customer_name == "旧名称"

    # 清理
    db.delete(existing)
    db.commit()
    db.close()


def test_douyin_sync_preview_skip_assigned():
    """测试 3：本地已有 assigned 线索 → action=skip"""
    db = _db()

    # 创建一条 assigned 线索
    staff = SalesStaff(name="测试销售")
    db.add(staff)
    db.commit()

    existing = DouyinLead(
        source="douyin",
        source_id="test_open_id_001",
        customer_name="张三",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add(existing)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_LEADS_RESPONSE

        request = DouyinSyncRequest(dry_run=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.mapped == 1

    item = result.items[0]
    assert item.action == "skip"
    assert "assigned" in item.reason
    assert result.skipped == 1

    # 清理
    db.delete(existing)
    db.delete(staff)
    db.commit()
    db.close()


def test_douyin_sync_non_dry_run_rejected():
    """测试 4：dry_run=false 执行写库（P4-2 已支持）"""
    db = _db()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_LEADS_RESPONSE

        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    # P4-2: dry_run=false 现在正常执行
    assert result.success is True
    assert result.dry_run is False
    assert result.fetched == 1
    assert result.mapped == 1
    assert result.created == 1
    assert result.updated == 0

    # 验证数据库中确实写入了
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "test_open_id_001").first()
    assert lead is not None
    assert lead.source == "douyin"
    assert lead.customer_name == "张三"
    assert lead.content == "你好，我想咨询产品价格"
    assert lead.lead_type == "私信"
    assert lead.customer_contact == "13800138001"
    assert lead.status == "pending"

    # 清理
    db.delete(lead)
    db.commit()
    db.close()


def test_douyin_sync_api():
    """测试 5：POST /integrations/douyin/sync-leads API 层测试"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _db_session
    client = TestClient(app)

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "api_test_001",
                    "display_name": "API测试用户",
                    "phone": None,
                    "last_interaction_record": "API测试消息",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        resp = client.post(
            "/integrations/douyin/sync-leads",
            json={"dry_run": True, "limit": 50, "lead_status": "pending"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["dry_run"] is True
    assert data["fetched"] == 1
    assert data["mapped"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["source_id"] == "api_test_001"
    assert data["items"][0]["action"] == "create"


def test_douyin_sync_api_error():
    """测试 6：上游不可达时返回友好错误"""
    db = _db()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.side_effect = DouyinApiError("无法连接 douyinAPI")

        request = DouyinSyncRequest(dry_run=True)
        result = preview_sync_leads(db, request)

    assert result.success is False
    assert "无法连接" in result.message

    db.close()


def test_douyin_sync_empty_phone():
    """测试 7：phone 为 null 时映射正确"""
    db = _db()

    response = {
        "items": [
            {
                "open_id": "no_phone_001",
                "display_name": "无手机号用户",
                "phone": None,
                "last_interaction_record": "你好",
                "lead_type": "私信",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = response

        request = DouyinSyncRequest(dry_run=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    item = result.items[0]
    assert item.customer_contact is None

    db.close()


def test_douyin_sync_missing_display_name():
    """测试 8：display_name 为空时用默认值"""
    db = _db()

    response = {
        "items": [
            {
                "open_id": "no_name_001",
                "display_name": None,
                "phone": None,
                "last_interaction_record": "你好",
                "lead_type": None,
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = response

        request = DouyinSyncRequest(dry_run=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    item = result.items[0]
    assert item.customer_name == "未命名客户"
    assert item.lead_type == "私信"  # 空值默认

    db.close()


# ========== P4-2：写库测试 ==========


def test_douyin_sync_write_create():
    """P4-2 测试 1：dry_run=false 新建线索"""
    db = _db()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "write_create_001",
                    "display_name": "新建用户",
                    "phone": "13900139001",
                    "last_interaction_record": "新建测试消息",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.dry_run is False
    assert result.created == 1
    assert result.updated == 0
    assert result.skipped == 0

    # 验证数据库记录
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "write_create_001").first()
    assert lead is not None
    assert lead.source == "douyin"
    assert lead.source_id == "write_create_001"
    assert lead.customer_name == "新建用户"
    assert lead.customer_contact == "13900139001"
    assert lead.content == "新建测试消息"
    assert lead.lead_type == "私信"
    assert lead.status == "pending"
    assert lead.raw_data is not None

    # 清理
    db.delete(lead)
    db.commit()
    db.close()


def test_douyin_sync_write_update_pending():
    """P4-2 测试 2：dry_run=false 更新 pending 线索"""
    db = _db()

    # 先在本地创建一条 pending 线索
    existing = DouyinLead(
        source="douyin",
        source_id="write_update_001",
        customer_name="旧名称",
        content="旧内容",
        customer_contact="13800001111",
        lead_type="comment",
        status="pending",
    )
    db.add(existing)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "write_update_001",
                    "display_name": "新名称",
                    "phone": "13900002222",
                    "last_interaction_record": "新内容",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 0
    assert result.updated == 1
    assert result.skipped == 0

    # 验证更新后的数据
    db.refresh(existing)
    assert existing.customer_name == "新名称"
    assert existing.customer_contact == "13900002222"
    assert existing.content == "新内容"
    assert existing.lead_type == "私信"
    assert existing.status == "pending"  # status 不变
    assert existing.source_id == "write_update_001"  # source_id 不变

    # 清理
    db.delete(existing)
    db.commit()
    db.close()


def test_douyin_sync_write_skip_assigned():
    """P4-2 测试 3：dry_run=false 跳过 assigned 线索"""
    db = _db()

    # 创建一条 assigned 线索
    staff = SalesStaff(name="测试销售")
    db.add(staff)
    db.commit()

    existing = DouyinLead(
        source="douyin",
        source_id="write_skip_001",
        customer_name="原名称",
        content="原内容",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add(existing)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "write_skip_001",
                    "display_name": "新名称",
                    "phone": "13900003333",
                    "last_interaction_record": "新内容",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 0
    assert result.updated == 0
    assert result.skipped == 1

    # 验证数据未被覆盖
    db.refresh(existing)
    assert existing.customer_name == "原名称"
    assert existing.content == "原内容"
    assert existing.status == "assigned"

    # 清理
    db.delete(existing)
    db.delete(staff)
    db.commit()
    db.close()


def test_douyin_sync_write_multiple_mixed():
    """P4-2 测试 4：混合场景（新增 + 更新 + 跳过）"""
    db = _db()

    # 准备本地数据：一条 pending，一条 assigned
    staff = SalesStaff(name="混合测试销售")
    db.add(staff)
    db.commit()

    existing_pending = DouyinLead(
        source="douyin",
        source_id="mixed_pending_001",
        customer_name="旧名称",
        content="旧内容",
        status="pending",
    )
    existing_assigned = DouyinLead(
        source="douyin",
        source_id="mixed_assigned_001",
        customer_name="已分配用户",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add_all([existing_pending, existing_assigned])
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                # 新线索
                {
                    "open_id": "mixed_new_001",
                    "display_name": "全新用户",
                    "phone": None,
                    "last_interaction_record": "新线索消息",
                    "lead_type": "私信",
                },
                # pending 更新
                {
                    "open_id": "mixed_pending_001",
                    "display_name": "更新名称",
                    "phone": "13800004444",
                    "last_interaction_record": "更新内容",
                    "lead_type": "私信",
                },
                # assigned 跳过
                {
                    "open_id": "mixed_assigned_001",
                    "display_name": "跳过用户",
                    "phone": None,
                    "last_interaction_record": "跳过内容",
                    "lead_type": "私信",
                },
            ],
            "total": 3,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.fetched == 3
    assert result.mapped == 3
    assert result.created == 1
    assert result.updated == 1
    assert result.skipped == 1
    assert result.assigned == 0

    # 验证新线索
    new_lead = db.query(DouyinLead).filter(DouyinLead.source_id == "mixed_new_001").first()
    assert new_lead is not None
    assert new_lead.customer_name == "全新用户"

    # 验证 pending 更新
    db.refresh(existing_pending)
    assert existing_pending.customer_name == "更新名称"
    assert existing_pending.content == "更新内容"
    assert existing_pending.status == "pending"

    # 验证 assigned 未变
    db.refresh(existing_assigned)
    assert existing_assigned.customer_name == "已分配用户"
    assert existing_assigned.status == "assigned"

    # 清理
    db.delete(new_lead)
    db.delete(existing_pending)
    db.delete(existing_assigned)
    db.delete(staff)
    db.commit()
    db.close()


def test_douyin_sync_auto_assign_ignored_in_p4_2():
    """P4-2 测试 5：auto_assign=true 但无活跃销售，线索保持 pending"""
    db = _db()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "auto_assign_001",
                    "display_name": "自动分配测试",
                    "phone": None,
                    "last_interaction_record": "测试",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False, auto_assign=True)
        result = preview_sync_leads(db, request)

    # P4-3: auto_assign=true 执行了分配尝试，但无活跃销售所以 assigned=0
    assert result.success is True
    assert result.created == 1
    assert result.assigned == 0
    assert "no_active_staff" in result.items[0].reason

    # 线索已创建，保持 pending
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "auto_assign_001").first()
    assert lead is not None
    assert lead.status == "pending"

    # 清理
    db.delete(lead)
    db.commit()
    db.close()


# ========== P4-3：自动分配联动测试 ==========


def test_douyin_sync_auto_assign_created_lead():
    """P4-3 测试 1：auto_assign=true，新线索自动分配成功"""
    db = _db()

    # 预置活跃销售
    staff = SalesStaff(name="自动分配销售", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "assign_create_001",
                    "display_name": "待分配用户",
                    "phone": "13800005555",
                    "last_interaction_record": "请分配",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False, auto_assign=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 1
    assert result.assigned == 1

    # 验证线索已分配
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "assign_create_001").first()
    assert lead is not None
    assert lead.status == "assigned"
    assert lead.assigned_staff_id == staff.id
    assert lead.assigned_at is not None

    # 验证 reply_check 已创建
    check = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).first()
    assert check is not None
    assert check.staff_id == staff.id
    assert check.check_status == "pending"

    # 验证 reason 包含 auto_assigned
    assert "auto_assigned" in result.items[0].reason

    # 清理
    db.delete(check)
    db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_douyin_sync_auto_assign_only_new_created():
    """P4-3 测试 2：auto_assign=true 仅对新建线索分配，update/skip 不分配"""
    db = _db()

    # 预置活跃销售
    staff = SalesStaff(name="选择性分配销售", status="active")
    db.add(staff)
    db.commit()

    # 本地已有 pending 和 assigned 线索
    existing_pending = DouyinLead(
        source="douyin",
        source_id="sel_pending_001",
        customer_name="待更新",
        content="旧内容",
        status="pending",
    )
    existing_assigned = DouyinLead(
        source="douyin",
        source_id="sel_assigned_001",
        customer_name="已分配",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add_all([existing_pending, existing_assigned])
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                # 新线索 → 应自动分配
                {
                    "open_id": "sel_new_001",
                    "display_name": "新建用户",
                    "phone": None,
                    "last_interaction_record": "新消息",
                    "lead_type": "私信",
                },
                # pending 更新 → 不自动分配
                {
                    "open_id": "sel_pending_001",
                    "display_name": "更新用户",
                    "phone": None,
                    "last_interaction_record": "更新消息",
                    "lead_type": "私信",
                },
                # assigned 跳过 → 不自动分配
                {
                    "open_id": "sel_assigned_001",
                    "display_name": "跳过用户",
                    "phone": None,
                    "last_interaction_record": "跳过消息",
                    "lead_type": "私信",
                },
            ],
            "total": 3,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False, auto_assign=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 1
    assert result.updated == 1
    assert result.skipped == 1
    assert result.assigned == 1  # 仅新建的 1 条被分配

    # 验证新线索已分配
    new_lead = db.query(DouyinLead).filter(DouyinLead.source_id == "sel_new_001").first()
    assert new_lead.status == "assigned"
    assert new_lead.assigned_staff_id == staff.id

    # 验证 pending 线索未被分配（仅更新内容）
    db.refresh(existing_pending)
    assert existing_pending.status == "pending"
    assert existing_pending.assigned_staff_id is None

    # 清理
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == new_lead.id).all()
    for c in checks:
        db.delete(c)
    db.delete(new_lead)
    db.delete(existing_pending)
    db.delete(existing_assigned)
    db.delete(staff)
    db.commit()
    db.close()


def test_douyin_sync_auto_assign_no_active_staff():
    """P4-3 测试 3：auto_assign=true 但无活跃销售，线索保持 pending"""
    db = _db()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "no_staff_001",
                    "display_name": "无销售用户",
                    "phone": None,
                    "last_interaction_record": "测试",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False, auto_assign=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 1
    assert result.assigned == 0
    assert "no_active_staff" in result.items[0].reason

    # 线索已创建但保持 pending
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "no_staff_001").first()
    assert lead is not None
    assert lead.status == "pending"
    assert lead.assigned_staff_id is None

    # 清理
    db.delete(lead)
    db.commit()
    db.close()


def test_douyin_sync_dry_run_auto_assign_not_executed():
    """P4-3 测试 4：dry_run=true + auto_assign=true，不创建不分配"""
    db = _db()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "dry_assign_001",
                    "display_name": "预览用户",
                    "phone": None,
                    "last_interaction_record": "预览",
                    "lead_type": "私信",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=True, auto_assign=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.dry_run is True
    assert result.created == 0  # dry_run 不写库
    assert result.assigned == 0  # dry_run 不分配
    assert "dry_run 未执行自动分配" in result.items[0].reason

    # 确认数据库中无记录
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "dry_assign_001").first()
    assert lead is None

    db.close()


# ========== wechat fallback 测试 ==========


def test_douyin_sync_wechat_fallback_when_phone_empty():
    """phone 为空但 wechat 有值时，customer_contact 取 wechat"""
    db = _db()

    response = {
        "items": [
            {
                "open_id": "wechat_fb_001",
                "display_name": "微信用户",
                "phone": None,
                "wechat": "wx_test_001",
                "last_interaction_record": "你好",
                "lead_type": "私信",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = response
        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 1

    # 验证 customer_contact 取了 wechat 值
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wechat_fb_001").first()
    assert lead is not None
    assert lead.customer_contact == "wx_test_001"

    # 清理
    db.delete(lead)
    db.commit()
    db.close()


def test_douyin_sync_phone_priority_over_wechat():
    """phone 和 wechat 都有值时，customer_contact 优先取 phone"""
    db = _db()

    response = {
        "items": [
            {
                "open_id": "phone_pri_001",
                "display_name": "双值用户",
                "phone": "13800006666",
                "wechat": "wx_test_002",
                "last_interaction_record": "你好",
                "lead_type": "私信",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = response
        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 1

    # 验证 customer_contact 取了 phone 而非 wechat
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "phone_pri_001").first()
    assert lead is not None
    assert lead.customer_contact == "13800006666"

    # 清理
    db.delete(lead)
    db.commit()
    db.close()


def test_douyin_sync_both_phone_and_wechat_empty():
    """phone 和 wechat 都为空时，customer_contact 为 None"""
    db = _db()

    response = {
        "items": [
            {
                "open_id": "both_empty_001",
                "display_name": "无联系方式用户",
                "phone": None,
                "wechat": None,
                "last_interaction_record": "你好",
                "lead_type": "私信",
            }
        ],
        "total": 1,
        "page": 1,
        "page_size": 50,
    }

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = response
        request = DouyinSyncRequest(dry_run=False)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.created == 1

    # 验证 customer_contact 为 None，同步不报错
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "both_empty_001").first()
    assert lead is not None
    assert lead.customer_contact is None

    # 清理
    db.delete(lead)
    db.commit()
    db.close()
