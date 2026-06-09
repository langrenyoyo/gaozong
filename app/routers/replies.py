"""回复相关 API"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ManualReply, CheckOut, WechatDetectRequest, WechatDetectResponse
from app.services import reply_checker
from app.services import wechat_ui_reply_service
from app.wechat_ui.window_locator import list_suspected_windows, find_wechat_window, find_message_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/replies", tags=["回复管理"])


@router.post("/manual", response_model=CheckOut)
def manual_reply(data: ManualReply, db: Session = Depends(get_db)):
    """手动录入/模拟销售微信回复"""
    return reply_checker.record_manual_reply(
        db, lead_id=data.lead_id, staff_id=data.staff_id, reply_content=data.reply_content,
    )


@router.post("/current-wechat-detect", response_model=WechatDetectResponse)
def wechat_current_detect(data: WechatDetectRequest, db: Session = Depends(get_db)):
    """
    通过微信 UI 自动化检测当前聊天窗口中是否存在销售有效回复。

    前提条件：
    - 当前电脑已登录微信 PC 客户端（主机微信）
    - 已手动打开目标客户的聊天窗口
    - 销售已在该聊天窗口中回复主机微信

    检测流程：
    1. 定位微信窗口（主机微信）
    2. 读取当前聊天窗口最近 max_messages 条消息
    3. 筛选销售发送的消息
    4. 判断是否存在有效回复
    5. 有效回复时更新 reply_checks 和 douyin_leads
    """
    result = wechat_ui_reply_service.detect_reply_from_wechat(
        db=db,
        lead_id=data.lead_id,
        staff_id=data.staff_id,
        max_messages=data.max_messages,
    )
    return WechatDetectResponse(**result)


@router.get("/debug/windows")
def debug_windows():
    """
    调试接口：列出所有疑似微信窗口。

    用于排查微信窗口定位失败的问题。
    返回候选窗口列表，包含 Name、ClassName、HWND 等信息。
    """
    try:
        windows = list_suspected_windows()
        return {
            "count": len(windows),
            "windows": windows,
        }
    except Exception as e:
        return {
            "count": 0,
            "error": str(e),
            "windows": [],
        }


@router.get("/debug/messages")
def debug_messages(max_messages: int = Query(10, ge=1, le=50, description="最多读取的消息条数")):
    """
    调试接口：返回当前聊天窗口消息的原始控件结构。

    用于排查消息发送方识别失败的问题。
    返回每条消息的子控件详情和各级识别策略结果。
    """
    try:
        # 定位微信窗口
        window = find_wechat_window()
        # 定位消息列表
        msg_list = find_message_list(window, timeout=5)
        list_rect = msg_list.BoundingRectangle
        mid_x = (list_rect.left + list_rect.right) / 2

        # 读取消息
        children = msg_list.GetChildren()
        total = len(children)
        start_idx = max(0, total - max_messages)
        recent = children[start_idx:]

        messages = []
        list_rect_dict = _rect_to_dict(list_rect)
        for i, child in enumerate(recent):
            msg_info = _inspect_message_control(child, mid_x, start_idx + i, list_rect_dict)
            messages.append(msg_info)

        return {
            "success": True,
            "total_messages": total,
            "showing": len(recent),
            "list_rect": _rect_to_dict(list_rect),
            "chat_mid_x": mid_x,
            "messages": messages,
        }

    except Exception as e:
        logger.error(f"调试消息接口异常: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "messages": [],
        }


def _rect_to_dict(rect) -> dict:
    """将 BoundingRectangle 转为字典"""
    return {
        "left": rect.left,
        "top": rect.top,
        "right": rect.right,
        "bottom": rect.bottom,
        "width": rect.width(),
        "height": rect.height(),
    }


def _inspect_message_control(child, mid_x: float, index: int, list_rect_dict: dict | None = None) -> dict:
    """
    检查单个消息控件的完整结构，返回调试信息。
    包含：基本属性、子控件列表、各级识别策略结果。
    """
    import uiautomation as uia

    name = child.Name or ""
    class_name = child.ClassName or ""
    ctrl_type = child.ControlTypeName

    try:
        rect = child.BoundingRectangle
        rect_dict = _rect_to_dict(rect)
        child_mid_x = (rect.left + rect.right) / 2
    except Exception:
        rect_dict = None
        child_mid_x = 0

    # 子控件数量
    try:
        sub_children = child.GetChildren()
        sub_count = len(sub_children)
    except Exception:
        sub_children = []
        sub_count = -1

    # 子控件详情
    children_info = []
    for sub in sub_children:
        sub_info = {
            "name": sub.Name or "",
            "class_name": sub.ClassName or "",
            "control_type": sub.ControlTypeName,
        }
        try:
            sub_rect = sub.BoundingRectangle
            sub_info["rect"] = _rect_to_dict(sub_rect)
            sub_info["center_x"] = (sub_rect.left + sub_rect.right) / 2
            sub_info["side"] = "右" if sub_info["center_x"] > mid_x else "左"
        except Exception:
            sub_info["rect"] = None

        children_info.append(sub_info)

    # 各级识别策略
    sender_debug = {}

    # 策略1：ButtonControl
    try:
        btn = child.ButtonControl(searchDepth=2)
        if btn.Exists(0):
            btn_rect = btn.BoundingRectangle
            sender_debug["button_control"] = {
                "found": True,
                "rect": _rect_to_dict(btn_rect),
                "center_x": (btn_rect.left + btn_rect.right) / 2,
            }
        else:
            sender_debug["button_control"] = {"found": False}
    except Exception as e:
        sender_debug["button_control"] = {"found": False, "error": str(e)}

    # 策略2：ImageControl
    try:
        img = child.ImageControl(searchDepth=2)
        if img.Exists(0):
            img_rect = img.BoundingRectangle
            w, h = img_rect.width(), img_rect.height()
            sender_debug["image_control"] = {
                "found": True,
                "rect": _rect_to_dict(img_rect),
                "width": w,
                "height": h,
                "is_avatar_size": 20 <= w <= 80 and 20 <= h <= 80,
            }
        else:
            sender_debug["image_control"] = {"found": False}
    except Exception as e:
        sender_debug["image_control"] = {"found": False, "error": str(e)}

    # 策略3：文本位置
    text_x_list = []
    for sub in sub_children:
        if sub.ControlTypeName == "TextControl":
            try:
                tc_rect = sub.BoundingRectangle
                tc_center = (tc_rect.left + tc_rect.right) / 2
                text_x_list.append(tc_center)
            except Exception:
                pass

    if text_x_list:
        avg_text_x = sum(text_x_list) / len(text_x_list)
        if avg_text_x > mid_x + 50:
            text_result = "self"
        elif avg_text_x < mid_x - 50:
            text_result = "friend"
        else:
            text_result = "unknown"
        sender_debug["text_position"] = {
            "text_control_count": len(text_x_list),
            "avg_center_x": round(avg_text_x, 1),
            "threshold": 50,
            "result": text_result,
        }
    else:
        sender_debug["text_position"] = {"text_control_count": 0}

    # 策略4：Item 边缘位置（PRIMARY）
    if rect_dict and list_rect_dict:
        right_gap = list_rect_dict["right"] - rect_dict["right"]
        left_gap = rect_dict["left"] - list_rect_dict["left"]
        threshold = 80
        is_right_edge = right_gap < threshold
        is_left_edge = left_gap < threshold
        if is_right_edge and not is_left_edge:
            edge_result = "self"
        elif is_left_edge and not is_right_edge:
            edge_result = "friend"
        elif is_right_edge and is_left_edge:
            edge_result = "full_width"
        else:
            edge_result = "unknown"
        sender_debug["item_edges"] = {
            "item_right": rect_dict["right"],
            "list_right": list_rect_dict["right"],
            "right_gap": right_gap,
            "item_left": rect_dict["left"],
            "list_left": list_rect_dict["left"],
            "left_gap": left_gap,
            "threshold": threshold,
            "is_right_edge": is_right_edge,
            "is_left_edge": is_left_edge,
            "result": edge_result,
        }

    return {
        "index": index,
        "name": name,
        "class_name": class_name,
        "control_type": ctrl_type,
        "rect": rect_dict,
        "child_count": sub_count,
        "children": children_info,
        "sender_debug": sender_debug,
    }
