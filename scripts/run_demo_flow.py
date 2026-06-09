"""运行端到端演示流程"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import SalesStaff, DouyinLead, ReplyCheck
from app.services.assign_service import assign_lead
from app.services.reply_checker import record_manual_reply, run_checks
from app.services.report_service import get_summary


def demo():
    db = SessionLocal()

    print("=" * 60)
    print("  抖音线索销售微信回复检测系统 MVP — 端到端演示")
    print("=" * 60)

    # --- 第一步：查看线索和销售 ---
    print("\n【第1步】查看当前线索和销售人员")
    leads = db.query(DouyinLead).order_by(DouyinLead.id).all()
    staffs = db.query(SalesStaff).all()
    print(f"  线索数: {len(leads)}, 销售数: {len(staffs)}")

    # --- 第二步：分配线索 ---
    print("\n【第2步】将线索分配给销售")
    if len(leads) >= 3 and len(staffs) >= 2:
        # 分配前3条线索
        assignments = [
            (leads[0].id, staffs[0].id),
            (leads[1].id, staffs[0].id),
            (leads[2].id, staffs[1].id),
        ]
        for lead_id, staff_id in assignments:
            lead = assign_lead(db, lead_id, staff_id)
            staff = db.get(SalesStaff, staff_id)
            print(f"  线索 #{lead_id} ({lead.customer_name}) → {staff.name}")
    else:
        print("  数据不足，请先运行 seed_demo_data.py")
        return

    # --- 第三步：模拟销售回复 ---
    print("\n【第3步】模拟销售微信回复")

    # 模拟有效回复
    check1 = record_manual_reply(db, leads[0].id, staffs[0].id, "收到，已添加微信，正在沟通方案")
    print(f"  线索 #{leads[0].id} 回复: '收到，已添加微信，正在沟通方案'")
    print(f"    → 检测结果: {'有效' if check1.is_effective else '无效'} ({check1.effectiveness_reason})")

    # 模拟无效回复
    check2 = record_manual_reply(db, leads[1].id, staffs[0].id, "不知道")
    print(f"  线索 #{leads[1].id} 回复: '不知道'")
    print(f"    → 检测结果: {'有效' if check2.is_effective else '无效'} ({check2.effectiveness_reason})")

    # 线索3不回复，留给超时检测

    # --- 第四步：手动触发超时检测 ---
    print("\n【第4步】手动触发超时检测（将截止时间改为过去）")
    pending_checks = db.query(ReplyCheck).filter(ReplyCheck.check_status == "pending").all()
    for c in pending_checks:
        c.reply_deadline = datetime.now() - timedelta(minutes=1)
    db.commit()

    updated = run_checks(db)
    for c in updated:
        lead = db.get(DouyinLead, c.lead_id)
        print(f"  线索 #{c.lead_id} ({lead.customer_name}): {c.check_status} - {c.effectiveness_reason}")

    # --- 第五步：查看报表 ---
    print("\n【第5步】汇总报表")
    summary = get_summary(db)
    print(f"  总线索数: {summary['total_leads']}")
    print(f"  已分配:   {summary['assigned_count']}")
    print(f"  已有效回复: {summary['replied_count']}")
    print(f"  超时:     {summary['timeout_count']}")
    print(f"  待处理:   {summary['pending_count']}")
    print()
    print("  各销售统计:")
    for s in summary["staff_stats"]:
        print(f"    {s['staff_name']}: 分配 {s['total_assigned']}, "
              f"有效回复 {s['replied_count']}, 超时 {s['timeout_count']}, "
              f"回复率 {s['reply_rate']}%")

    print("\n" + "=" * 60)
    print("  端到端演示完成！")
    print("=" * 60)

    db.close()


if __name__ == "__main__":
    demo()
