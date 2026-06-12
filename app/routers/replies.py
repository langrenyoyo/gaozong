"""回复相关 API"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    ManualReply, CheckOut, WechatDetectRequest, WechatDetectResponse,
    AgentWriteBackRequest, AgentWriteBackResponse,
)
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
        confirm_current_chat=data.confirm_current_chat,
    )
    return WechatDetectResponse(**result)


@router.post("/agent-write-back", response_model=AgentWriteBackResponse)
def agent_write_back(data: AgentWriteBackRequest, db: Session = Depends(get_db)):
    """P0-REPLY-2：接收 Local Agent 从客户电脑微信读取的消息，分析关键词并回写数据库。

    调用方：Local Agent POST 19000 /agent/replies/detect 内部调用此接口。

    处理规则：
    1. 根据 lead_id + staff_id 查找 pending ReplyCheck
    2. 找不到 → failed
    3. friend 消息命中关键词 → replied
    4. unknown 消息命中关键词 → manual_review
    5. 未命中 → pending
    6. 不伪造 replied，不修改 sent_at
    """
    result = wechat_ui_reply_service.agent_write_back_reply(
        db=db,
        lead_id=data.lead_id,
        staff_id=data.staff_id,
        task_id=data.task_id,
        target_nickname=data.target_nickname,
        messages=[m.model_dump() for m in data.messages],
        agent_result=data.agent_result.model_dump(),
    )
    return AgentWriteBackResponse(**result)


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


# ========== 实验性调试端点（不影响正式检测逻辑） ==========


@router.get("/debug/raw-tree")
def debug_raw_tree(max_messages: int = Query(5, ge=1, le=20)):
    """
    实验接口：UIA 深层控件树探测。

    对最近消息进行 WalkControl / FindAll / ControlFromPoint 探测，
    判断是否存在可用于区分 self/friend 的深层控件。
    """
    import uiautomation as uia

    try:
        window = find_wechat_window()
        msg_list = find_message_list(window, timeout=5)
        list_rect = msg_list.BoundingRectangle
        mid_x = (list_rect.left + list_rect.right) / 2

        children = msg_list.GetChildren()
        total = len(children)
        start_idx = max(0, total - max_messages)
        recent = children[start_idx:]

        messages = []
        for i, child in enumerate(recent):
            msg_info = _deep_inspect(child, mid_x, start_idx + i)
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
        logger.error(f"raw-tree 探测异常: {e}", exc_info=True)
        return {"success": False, "error": str(e), "messages": []}


def _deep_inspect(msg_control, mid_x: float, index: int) -> dict:
    """
    深层探测单个消息控件：WalkControl + FindAll + ControlFromPoint。
    """
    import uiautomation as uia

    name = msg_control.Name or ""
    class_name = msg_control.ClassName or ""

    try:
        rect = msg_control.BoundingRectangle
        rect_dict = _rect_to_dict(rect)
    except Exception:
        rect_dict = None

    # --- WalkControl 深层遍历 ---
    walk_controls = []
    walk_count = 0
    try:
        for ctrl, depth in msg_control.WalkControl(maxDepth=10):
            walk_count += 1
            if walk_count <= 30:
                c_name = ctrl.Name or ""
                c_class = ctrl.ClassName or ""
                c_type = ctrl.ControlTypeName
                try:
                    c_rect = ctrl.BoundingRectangle
                    c_rect_dict = _rect_to_dict(c_rect)
                    c_center_x = (c_rect.left + c_rect.right) / 2
                    c_side = "右" if c_center_x > mid_x else "左"
                except Exception:
                    c_rect_dict = None
                    c_center_x = 0
                    c_side = ""

                walk_controls.append({
                    "depth": depth,
                    "type": c_type,
                    "name": c_name[:80],
                    "class_name": c_class[:80],
                    "rect": c_rect_dict,
                    "center_x": round(c_center_x, 1),
                    "side": c_side,
                })
    except Exception:
        pass

    # --- FindAll 子孙数量 ---
    findall_length = -1
    try:
        ptrs = msg_control.FindAll(return_pointer=True)
        findall_length = ptrs.Length
    except Exception:
        pass

    # --- ControlFromPoint 点采样 ---
    point_samples = []
    if rect_dict:
        w = rect_dict["width"]
        h = rect_dict["height"]
        points = [
            ("左侧", rect_dict["left"] + w // 4, rect_dict["top"] + h // 2),
            ("中心", rect_dict["left"] + w // 2, rect_dict["top"] + h // 2),
            ("右侧", rect_dict["left"] + 3 * w // 4, rect_dict["top"] + h // 2),
        ]
        for label_pt, px, py in points:
            try:
                hit = uia.ControlFromPoint(px, py)
                hit_type = hit.ControlTypeName
                hit_name = (hit.Name or "")[:80]
                hit_class = (hit.ClassName or "")[:80]
                try:
                    hit_rect = _rect_to_dict(hit.BoundingRectangle)
                except Exception:
                    hit_rect = None
                is_deeper = hit_type != "ListItemControl"
                point_samples.append({
                    "label": label_pt,
                    "point": [px, py],
                    "type": hit_type,
                    "name": hit_name,
                    "class_name": hit_class,
                    "rect": hit_rect,
                    "is_deeper": is_deeper,
                })
            except Exception as e:
                point_samples.append({"label": label_pt, "point": [px, py], "error": str(e)})

    return {
        "index": index,
        "name": name[:80],
        "class_name": class_name[:80],
        "rect": rect_dict,
        "walk_count": walk_count,
        "findall_length": findall_length,
        "walk_controls": walk_controls,
        "point_samples": point_samples,
    }


@router.post("/debug/sender-experiment")
def debug_sender_experiment(data: dict):
    """
    实验接口：发送方识别方案实验。

    传入已知的 self/friend 消息文本，尝试用不同方案判断发送方。

    请求体：
    {
        "max_messages": 10,
        "known_friend_text": "收到，已添加微信",
        "known_self_text": "请回复收到"
    }
    """
    import uiautomation as uia

    max_messages = data.get("max_messages", 10)
    known_friend = data.get("known_friend_text", "")
    known_self = data.get("known_self_text", "")

    try:
        window = find_wechat_window()
        msg_list = find_message_list(window, timeout=5)
        list_rect = msg_list.BoundingRectangle
        mid_x = (list_rect.left + list_rect.right) / 2

        children = msg_list.GetChildren()
        total = len(children)
        start_idx = max(0, total - max_messages)
        recent = children[start_idx:]

        results = []
        for i, child in enumerate(recent):
            msg_name = child.Name or ""

            friend_found_in_tree = False
            self_found_in_tree = False
            friend_position = None
            self_position = None

            # 在控件名中搜索已知文本
            if known_friend and known_friend in msg_name:
                friend_found_in_tree = True
                try:
                    r = child.BoundingRectangle
                    center_x = (r.left + r.right) / 2
                    friend_position = {
                        "center_x": round(center_x, 1),
                        "side": "右" if center_x > mid_x else "左",
                        "relative": "right_of_mid" if center_x > mid_x else "left_of_mid",
                    }
                except Exception:
                    pass

            if known_self and known_self in msg_name:
                self_found_in_tree = True
                try:
                    r = child.BoundingRectangle
                    center_x = (r.left + r.right) / 2
                    self_position = {
                        "center_x": round(center_x, 1),
                        "side": "右" if center_x > mid_x else "左",
                        "relative": "right_of_mid" if center_x > mid_x else "left_of_mid",
                    }
                except Exception:
                    pass

            results.append({
                "index": start_idx + i,
                "name": msg_name[:80],
                "friend_found_in_tree": friend_found_in_tree,
                "self_found_in_tree": self_found_in_tree,
                "friend_position": friend_position,
                "self_position": self_position,
            })

        # 综合判断
        recommendation = "cannot_determine"
        friend_msg = [r for r in results if r["friend_found_in_tree"]]
        self_msg = [r for r in results if r["self_found_in_tree"]]

        analysis = {
            "friend_text_searched": known_friend,
            "self_text_searched": known_self,
            "friend_found_count": len(friend_msg),
            "self_found_count": len(self_msg),
            "friend_is_left": all(
                r["friend_position"]["side"] == "左"
                for r in friend_msg if r.get("friend_position")
            ) if friend_msg else False,
            "self_is_right": all(
                r["self_position"]["side"] == "右"
                for r in self_msg if r.get("self_position")
            ) if self_msg else False,
        }

        if analysis["friend_is_left"] and analysis["self_is_right"]:
            recommendation = "screenshot_position"
        elif len(friend_msg) > 0 or len(self_msg) > 0:
            recommendation = "uia_name_search"
        else:
            recommendation = "cannot_determine"

        return {
            "success": True,
            "list_rect": _rect_to_dict(list_rect),
            "mid_x": round(mid_x, 1),
            "analysis": analysis,
            "recommendation": recommendation,
            "messages": results,
        }

    except Exception as e:
        logger.error(f"sender-experiment 异常: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
