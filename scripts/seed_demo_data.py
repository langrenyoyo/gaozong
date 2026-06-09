"""插入演示数据"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import SalesStaff, DouyinLead


def seed():
    db = SessionLocal()

    # 创建 3 个销售人员
    staff_list = [
        SalesStaff(name="张三", wechat_id="zhangsan_wx", wechat_nickname="张三-销售顾问", phone="13800001111"),
        SalesStaff(name="李四", wechat_id="lisi_wx", wechat_nickname="李四-高级销售", phone="13800002222"),
        SalesStaff(name="王五", wechat_id="wangwu_wx", wechat_nickname="王五-客户经理", phone="13800003333"),
    ]
    for s in staff_list:
        db.add(s)
    db.commit()
    print(f"已创建 {len(staff_list)} 个销售人员")

    # 创建 5 条模拟线索
    leads_data = [
        {
            "source": "douyin",
            "lead_type": "comment",
            "customer_name": "用户A_装修咨询",
            "customer_contact": "13900001111",
            "content": "请问全屋定制多少钱一平米？北京地区",
            "source_url": "https://www.douyin.com/video/xxx1",
            "source_id": "dy_comment_001",
        },
        {
            "source": "douyin",
            "lead_type": "chat",
            "customer_name": "用户B_私信咨询",
            "customer_contact": "13900002222",
            "content": "我想了解一下你们的装修套餐，三室两厅大概多少钱？",
            "source_url": "https://www.douyin.com/video/xxx2",
            "source_id": "dy_chat_002",
        },
        {
            "source": "douyin",
            "lead_type": "lead",
            "customer_name": "用户C_表单留资",
            "customer_contact": "13900003333",
            "content": "留资: 上海浦东 120平 新房装修",
            "source_url": "https://www.douyin.com/video/xxx3",
            "source_id": "dy_lead_003",
        },
        {
            "source": "douyin",
            "lead_type": "comment",
            "customer_name": "用户D_评论区互动",
            "customer_contact": None,
            "content": "效果不错，能加个微信聊聊吗？",
            "source_url": "https://www.douyin.com/video/xxx4",
            "source_id": "dy_comment_004",
        },
        {
            "source": "douyin",
            "lead_type": "chat",
            "customer_name": "用户E_私信询价",
            "customer_contact": "13900005555",
            "content": "你们做旧房翻新吗？大概工期多久？",
            "source_url": "https://www.douyin.com/video/xxx5",
            "source_id": "dy_chat_005",
        },
    ]
    for data in leads_data:
        lead = DouyinLead(**data)
        db.add(lead)
    db.commit()
    print(f"已创建 {len(leads_data)} 条模拟线索")

    db.close()
    print("演示数据插入完成！")


if __name__ == "__main__":
    seed()
