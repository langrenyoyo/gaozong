"""消息解析：发送方识别 + 内容提取

核心前提：系统运行在主机微信所在电脑上。
当前电脑登录的是主机微信，系统检测的是销售对主机微信的回复。

发送方语义（主机微信场景）：
  self   = 主机微信发出的消息（不是销售回复）
  friend = 销售发送给主机微信的消息（才是销售回复）

当前微信版本无法稳定区分 self/friend（item 跨满列表宽度，
无 ButtonControl/ImageControl/TextControl 子控件），
因此 MVP 启用 fallback_current_window_text 模式。

发送方识别策略（根据实际微信控件结构调试结果优化）：

调试结论：
  - ButtonControl(searchDepth=2) → 不存在
  - ImageControl(searchDepth=2) → 不存在
  - TextControl 子控件 → 数量为 0
  - 消息文本存在于 ListItemControl.Name 属性中
  - item 整体可能跨满整个列表宽度，需用边缘距离判断

识别优先级：
  1. 先判 system（时间分割线 / 系统提示 / 无文本）
  2. item 边缘位置（PRIMARY）：item.right 接近 list.right → self
  3. ButtonControl / ImageControl 头像（保留兼容）
  4. TextControl 中心位置（辅助）
  5. 无法识别 → unknown

内容提取规则：
  - 子控件为空时，直接用 ListItemControl.Name 或 Name+Value
  - 合并可读文本作为消息内容
  - 过滤时间分割线、系统提示、特殊消息标记
"""

import logging
import re

import uiautomation as uia

logger = logging.getLogger(__name__)

# 特殊消息标记（非文本消息，应跳过）
SPECIAL_MSG_MARKERS = [
    "[图片]", "[视频]", "[语音]", "[位置]", "[链接]",
    "[文件]", "[名片]", "[笔记]", "[动画表情]", "[聊天记录]",
    "[引用]", "[红包]", "[转账]", "[语音通话]", "[视频通话]",
]

# 系统提示关键词（匹配到则为系统消息）
SYSTEM_MSG_KEYWORDS = [
    "撤回了一条消息",
    "以下是新消息",
    "你已添加了",
    "以上是打招呼内容",
    "邀请你加入了",
    "你将",
    "加入了群聊",
    "修改群名为",
]

# 时间文本正则
_TIME_PATTERN = re.compile(
    r"(\d{1,2}:\d{2}|"                           # 12:30
    r"昨天|前天|"                                  # 昨天
    r"星期[一二三四五六七日]|周[一二三四五六七日]|"     # 星期一
    r"\d{4}年\d{1,2}月\d{1,2}日|"                 # 2024年1月1日
    r"上午|下午|凌晨|早上|中午|晚上|夜里|"            # 上午/下午
    r"\d{1,2}月\d{1,2}日)"                        # 1月1日
)

# item 边缘判断阈值（像素）：item 边缘距 list 边缘在此范围内视为"贴近"
_EDGE_THRESHOLD = 80


def identify_sender(
    msg_control: uia.Control,
    chat_mid_x: float,
    list_rect=None,
    item_img=None,
    debug: dict | None = None,
) -> str:
    """
    判断消息发送方。

    优先级：
      1. system 判定（时间分割线 / 系统提示 / 无文本）
      2. item 边缘位置（PRIMARY）
      3. ButtonControl / ImageControl 头像
      4. TextControl 位置（辅助）
      5. 截图像素颜色分析（P0-REPLY-3B 新增）
      6. unknown

    Args:
        msg_control: 消息控件（ListItemControl）
        chat_mid_x: 聊天区域水平中线 X 坐标
        list_rect: 消息列表的 BoundingRectangle（用于 item 边缘判断）
        item_img: item 区域的截图 PIL Image（用于像素颜色分析）
        debug: 可选字典，接收各策略的调试信息

    Returns:
        "self" | "friend" | "system" | "unknown"
    """
    try:
        # 获取 item 自身矩形（后续多次使用）
        item_rect = msg_control.BoundingRectangle

        logger.debug(
            f"identify_sender: Name='{_safe_name(msg_control)}', "
            f"item_rect=({item_rect.left},{item_rect.top},{item_rect.right},{item_rect.bottom}), "
            f"mid_x={chat_mid_x:.1f}"
        )

        # ====== 步骤一：system 判定 ======
        system_reason = _check_is_system(msg_control, item_rect)
        if system_reason:
            logger.debug(f"  → system: {system_reason}")
            if debug is not None:
                debug["strategy"] = "system"
                debug["reason"] = system_reason
            return "system"

        # ====== 步骤二：item 边缘位置（PRIMARY） ======
        if list_rect is not None:
            result = _sender_by_item_edges(msg_control, item_rect, list_rect)
            if result:
                logger.debug(f"  → {result} (item 边缘位置)")
                if debug is not None:
                    debug["strategy"] = "item_edges"
                    debug["reason"] = "边缘距离判断"
                return result

        # ====== 步骤三：ButtonControl / ImageControl 头像 ======
        result = _sender_by_button_avatar(msg_control, chat_mid_x)
        if result:
            logger.debug(f"  → {result} (ButtonControl 头像)")
            if debug is not None:
                debug["strategy"] = "button_avatar"
                debug["reason"] = "ButtonControl 头像位置"
            return result

        result = _sender_by_other_avatar(msg_control, chat_mid_x)
        if result:
            logger.debug(f"  → {result} (其他头像控件)")
            if debug is not None:
                debug["strategy"] = "other_avatar"
                debug["reason"] = "ImageControl/子控件头像位置"
            return result

        # ====== 步骤四：TextControl 位置（辅助） ======
        result = _sender_by_text_position(msg_control, chat_mid_x)
        if result:
            logger.debug(f"  → {result} (TextControl 位置)")
            if debug is not None:
                debug["strategy"] = "text_position"
                debug["reason"] = "TextControl 中心位置"
            return result

        # ====== 步骤五：截图像素颜色分析（P0-REPLY-3B） ======
        # 仅对文本消息应用（ChatTextItemView），跳过图片/特殊消息
        class_name = getattr(msg_control, "ClassName", "") or ""
        if item_img is not None and "ChatTextItemView" in class_name:
            result = _sender_by_screenshot_color(item_img, debug=debug)
            if result:
                logger.debug(f"  → {result} (截图像素颜色)")
                return result

        # 所有策略都未命中
        child_summary = _get_child_summary(msg_control)
        logger.debug(
            f"  → unknown。子控件: {child_summary}"
        )
        if debug is not None:
            debug["strategy"] = "unknown"
            debug["reason"] = f"所有策略未命中，子控件: {child_summary}"
        return "unknown"

    except Exception as e:
        logger.debug(f"发送方识别异常: {e}")
        if debug is not None:
            debug["strategy"] = "exception"
            debug["reason"] = str(e)
        return "unknown"


# ============================================================
# system 判定
# ============================================================

def _check_is_system(msg_control: uia.Control, item_rect) -> str | None:
    """
    检查是否为系统消息 / 时间分割线。

    Returns:
        如果是系统消息，返回原因字符串；否则返回 None。
    """
    # 获取子控件数量
    try:
        children = msg_control.GetChildren()
        child_count = len(children)
    except Exception:
        children = []
        child_count = -1

    name = (msg_control.Name or "").strip()

    # 子控件 ≤ 2 且文本像时间 → 时间分割线
    if 0 <= child_count <= 2:
        if _is_time_text(name):
            return f"时间分割线: '{name}' (子控件={child_count})"
        # 子控件极少且无文本
        if not name:
            return f"无内容 (子控件={child_count})"

    # 文本匹配时间格式
    if name and _is_time_text(name):
        return f"时间文本: '{name}'"

    # 文本匹配系统提示关键词
    if name:
        for kw in SYSTEM_MSG_KEYWORDS:
            if kw in name:
                return f"系统提示: 匹配 '{kw}'"

    # 无任何可读文本
    if not name:
        # 检查子控件是否有文本
        has_any_text = False
        for child in children:
            if child.Name and child.Name.strip():
                has_any_text = True
                break
        if not has_any_text and child_count <= 3:
            return f"无有效文本 (子控件={child_count})"

    # item 高度很小（< 30px）且无有意义文本 → 疑似系统消息
    try:
        item_height = item_rect.height()
        if item_height > 0 and item_height < 30 and (not name or _is_time_text(name)):
            return f"高度过小: {item_height}px"
    except Exception:
        pass

    return None


# ============================================================
# 发送方识别策略
# ============================================================

def _sender_by_item_edges(msg_control: uia.Control, item_rect, list_rect) -> str | None:
    """
    PRIMARY 策略：基于消息 item 边缘与列表边缘的距离判断。

    规则：
      - item.right 接近 list.right（差值 < 阈值）→ self（消息靠右）
      - item.left 接近 list.left（差值 < 阈值）→ friend（消息靠左）

    两者都满足时（item 跨满整个列表宽度），用 item 内部内容位置辅助：
      - 如果 item 内有可读文本，检查文本水平位置偏向哪侧
      - 无文本时返回 unknown
    """
    try:
        list_width = list_rect.right - list_rect.left
        if list_width <= 0:
            return None

        right_gap = list_rect.right - item_rect.right   # item 右边缘到 list 右边缘的距离
        left_gap = item_rect.left - list_rect.left       # item 左边缘到 list 左边缘的距离

        is_right_edge = right_gap < _EDGE_THRESHOLD
        is_left_edge = left_gap < _EDGE_THRESHOLD

        logger.debug(
            f"  item_edges: left_gap={left_gap}, right_gap={right_gap}, "
            f"is_left={is_left_edge}, is_right={is_right_edge}"
        )

        # 只有右侧贴近 → self
        if is_right_edge and not is_left_edge:
            return "self"

        # 只有左侧贴近 → friend
        if is_left_edge and not is_right_edge:
            return "friend"

        # 两侧都贴近（item 跨满）→ 用文本水平位置辅助判断
        if is_right_edge and is_left_edge:
            # 尝试在 Name 文本中寻找线索：检查 item 的内部子控件
            return _sender_by_content_position_in_full_width(msg_control, list_rect)

        return None

    except Exception:
        return None


def _sender_by_content_position_in_full_width(
    msg_control: uia.Control,
    list_rect,
) -> str | None:
    """
    当 item 跨满整个列表宽度时，通过内部子控件位置判断。

    遍历所有子控件，找最靠左和最靠右的可读内容控件，
    比较它们的中心 X 与列表中心 X。
    """
    mid_x = (list_rect.left + list_rect.right) / 2

    try:
        children = msg_control.GetChildren()
        if not children:
            return None

        # 收集所有有意义的子控件中心 X
        content_x_positions = []
        for child in children:
            try:
                child_name = child.Name or ""
                # 跳过空名、时间文本、特殊标记
                if not child_name.strip():
                    continue
                if _is_time_text(child_name) or _is_special_message(child_name):
                    continue
                rect = child.BoundingRectangle
                center_x = (rect.left + rect.right) / 2
                content_x_positions.append(center_x)
            except Exception:
                continue

        if not content_x_positions:
            return None

        avg_x = sum(content_x_positions) / len(content_x_positions)
        if avg_x > mid_x + _EDGE_THRESHOLD:
            return "self"
        if avg_x < mid_x - _EDGE_THRESHOLD:
            return "friend"

    except Exception:
        pass

    return None


def _sender_by_button_avatar(msg_control: uia.Control, chat_mid_x: float) -> str | None:
    """ButtonControl 头像位置判断（wxauto 原始方式，保留兼容）"""
    try:
        head_btn = msg_control.ButtonControl(searchDepth=2)
        if not head_btn.Exists(0):
            return None

        head_rect = head_btn.BoundingRectangle
        if head_rect.left <= 0 and head_rect.right <= 0:
            return None

        if head_rect.left > chat_mid_x:
            return "self"
        if head_rect.right < chat_mid_x:
            return "friend"
    except Exception:
        pass
    return None


def _sender_by_other_avatar(msg_control: uia.Control, chat_mid_x: float) -> str | None:
    """ImageControl / 小尺寸控件头像位置判断（保留兼容）"""
    # ImageControl
    try:
        img = msg_control.ImageControl(searchDepth=2)
        if img.Exists(0):
            img_rect = img.BoundingRectangle
            w, h = img_rect.width(), img_rect.height()
            if 20 <= w <= 80 and 20 <= h <= 80 and abs(w - h) <= 10:
                if img_rect.left > chat_mid_x:
                    return "self"
                if img_rect.right < chat_mid_x:
                    return "friend"
    except Exception:
        pass

    # 遍历子控件找头像尺寸特征
    try:
        children = msg_control.GetChildren()
        for child in children:
            try:
                rect = child.BoundingRectangle
                w, h = rect.width(), rect.height()
                if 20 <= w <= 80 and 20 <= h <= 80 and abs(w - h) <= 10:
                    if rect.left > chat_mid_x:
                        return "self"
                    if rect.right < chat_mid_x:
                        return "friend"
            except Exception:
                continue
    except Exception:
        pass

    return None


def _sender_by_text_position(msg_control: uia.Control, chat_mid_x: float) -> str | None:
    """TextControl 中心位置辅助判断"""
    text_x_positions = []

    try:
        children = msg_control.GetChildren()
        for child in children:
            if child.ControlTypeName == "TextControl":
                try:
                    tc_rect = child.BoundingRectangle
                    tc_center_x = (tc_rect.left + tc_rect.right) / 2
                    tc_name = child.Name or ""
                    if tc_name and not _is_time_text(tc_name):
                        text_x_positions.append(tc_center_x)
                except Exception:
                    continue
    except Exception:
        pass

    if not text_x_positions:
        return None

    avg_text_x = sum(text_x_positions) / len(text_x_positions)

    if avg_text_x > chat_mid_x + _EDGE_THRESHOLD:
        return "self"
    if avg_text_x < chat_mid_x - _EDGE_THRESHOLD:
        return "friend"

    return None


# ============================================================
# 辅助函数
# ============================================================

def _safe_name(control: uia.Control, max_len: int = 40) -> str:
    """安全获取控件名称（截断）"""
    name = control.Name or ""
    if len(name) > max_len:
        name = name[:max_len] + "..."
    return name


def _get_child_summary(msg_control: uia.Control) -> str:
    """获取子控件摘要信息，用于调试日志"""
    try:
        children = msg_control.GetChildren()
        types = [c.ControlTypeName for c in children]
        return f"数量={len(children)}, 类型={types}"
    except Exception:
        return "(获取失败)"


# ============================================================
# P0-REPLY-3B：截图像素颜色分析策略
# ============================================================

# 微信 self 气泡绿色 RGB 约 (157, 242, 159)
# 微信 friend 气泡白色 RGB 约 (238, 238, 240)
# 微信浅色背景 RGB 约 (245-255, 245-255, 245-255)
_SCREENSHOT_GREEN_THRESHOLD = 0.10   # 10% 绿色像素视为显著
_SCREENSHOT_NONBG_THRESHOLD = 0.05   # 5% 非背景像素视为有内容
_SCREENSHOT_MIN_SIZE = 20            # item 截图最小尺寸（像素）


def _is_green_pixel(r: int, g: int, b: int) -> bool:
    """判断像素是否为微信绿色气泡颜色。

    微信 self 气泡绿色特征：G 通道明显高于 R 和 B。
    典型值 (157, 242, 159)，G > R+30 且 G > B+30。
    """
    return g > 140 and g > r + 30 and g > b + 30 and r < 200


def _is_background_pixel(r: int, g: int, b: int) -> bool:
    """判断像素是否为微信聊天背景色。

    浅色背景特征：三通道接近且较亮（>245），用于排除气泡和文字。
    """
    return (r > 245 and g > 245 and b > 245
            and abs(r - g) < 8 and abs(g - b) < 8)


def _sender_by_screenshot_color(item_img, debug: dict | None = None) -> str | None:
    """
    P0-REPLY-3B：截图像素颜色分析策略。

    通过分析消息 item 截图中左右区域的像素颜色分布判断发送方。

    识别规则（保守）：
      1. self：右侧区域有显著绿色像素（微信绿色气泡），右侧绿色 > 左侧绿色
      2. friend：左侧区域有显著非背景像素（白色/浅灰气泡），右侧无绿色，
         左侧非背景显著高于右侧
      3. 无法判断 → 返回 None（调用方会降级为 unknown）

    Args:
        item_img: PIL Image，消息 item 区域截图
        debug: 可选字典，接收像素分析调试信息

    Returns:
        "self" | "friend" | None（None 表示无法判断）
    """
    try:
        w, h = item_img.size
        if w < _SCREENSHOT_MIN_SIZE or h < 5:
            if debug is not None:
                debug["screenshot"] = {
                    "result": None, "reason": f"截图尺寸过小: {w}x{h}",
                }
            return None

        mid = w // 2
        pixels = item_img.load()

        left_green = 0
        right_green = 0
        left_nonbg = 0
        right_nonbg = 0
        left_total = 0
        right_total = 0

        # 自适应采样步长：每边至少采样 50 个点
        step = max(1, min(w, h) // 30)

        for y in range(0, h, step):
            for x in range(0, w, step):
                px = pixels[x, y]
                r, g, b = px[0], px[1], px[2]

                is_green = _is_green_pixel(r, g, b)
                is_bg = _is_background_pixel(r, g, b)

                if x < mid:
                    left_total += 1
                    if is_green:
                        left_green += 1
                    if not is_bg:
                        left_nonbg += 1
                else:
                    right_total += 1
                    if is_green:
                        right_green += 1
                    if not is_bg:
                        right_nonbg += 1

        left_green_pct = left_green / left_total if left_total > 0 else 0
        right_green_pct = right_green / right_total if right_total > 0 else 0
        left_nonbg_pct = left_nonbg / left_total if left_total > 0 else 0
        right_nonbg_pct = right_nonbg / right_total if right_total > 0 else 0

        result = None
        reason = ""

        max_green = max(left_green_pct, right_green_pct)

        # ---- 规则 1：绿色检测（self 气泡） ----
        if max_green > _SCREENSHOT_GREEN_THRESHOLD:
            if right_green_pct > left_green_pct:
                # 右侧绿色显著 → self（绿色气泡在右侧）
                result = "self"
                reason = (
                    f"右侧绿色={right_green_pct:.1%}"
                    f">{_SCREENSHOT_GREEN_THRESHOLD:.0%}, 右>左"
                    f"({left_green_pct:.1%})"
                )
            elif left_green_pct > right_green_pct:
                # 左侧绿色显著 → friend（理论上不应出现，保守处理）
                result = "friend"
                reason = (
                    f"左侧绿色={left_green_pct:.1%}"
                    f">{_SCREENSHOT_GREEN_THRESHOLD:.0%}, 左>右"
                    f"({right_green_pct:.1%})"
                )
            else:
                reason = (
                    f"左右绿色接近: 左={left_green_pct:.1%}"
                    f" 右={right_green_pct:.1%}"
                )
        else:
            # ---- 规则 2：无绿色时的非背景内容检测 ----
            # friend 气泡在左侧（白色/浅灰），右侧无绿色
            if (left_nonbg_pct > _SCREENSHOT_NONBG_THRESHOLD
                    and left_nonbg_pct > right_nonbg_pct * 2
                    and right_green_pct < 0.02):
                result = "friend"
                reason = (
                    f"左侧非背景={left_nonbg_pct:.1%}"
                    f">{_SCREENSHOT_NONBG_THRESHOLD:.0%}, "
                    f"左>右*2({right_nonbg_pct:.1%}), 无绿色"
                )
            # 右侧有非背景内容但无绿色（极端情况，绿色阈值未达）
            elif (right_nonbg_pct > _SCREENSHOT_NONBG_THRESHOLD
                  and right_nonbg_pct > left_nonbg_pct * 2
                  and left_green_pct < 0.02
                  and right_green_pct < 0.02):
                result = "self"
                reason = (
                    f"右侧非背景={right_nonbg_pct:.1%}"
                    f">{_SCREENSHOT_NONBG_THRESHOLD:.0%}, "
                    f"右>左*2({left_nonbg_pct:.1%}), 无绿色"
                )
            else:
                reason = (
                    f"绿色不足({max_green:.1%}"
                    f"<{_SCREENSHOT_GREEN_THRESHOLD:.0%}), "
                    f"非背景不显著(左={left_nonbg_pct:.1%}"
                    f" 右={right_nonbg_pct:.1%})"
                )

        if debug is not None:
            debug["screenshot"] = {
                "green_left_pct": round(left_green_pct, 4),
                "green_right_pct": round(right_green_pct, 4),
                "nonbg_left_pct": round(left_nonbg_pct, 4),
                "nonbg_right_pct": round(right_nonbg_pct, 4),
                "sample_total": left_total + right_total,
                "step": step,
                "result": result,
                "reason": reason,
            }

        if result:
            logger.debug(f"  截图像素: {reason}")

        return result

    except Exception as e:
        if debug is not None:
            debug["screenshot"] = {"result": None, "error": str(e)}
        logger.debug(f"  截图像素分析异常: {e}")
        return None


# ============================================================
# 文本提取
# ============================================================

def extract_text(msg_control: uia.Control) -> str | None:
    """
    提取消息文本内容。

    策略：
      - 子控件为空时，直接用 ListItemControl.Name（或 Value）
      - 子控件非空时，遍历子控件 Name 合并可读文本
      - 过滤时间分割线、系统提示、特殊消息标记

    Args:
        msg_control: 消息控件

    Returns:
        提取到的文本，或 None（非文本消息）
    """
    try:
        # 获取子控件
        try:
            children = msg_control.GetChildren()
            child_count = len(children)
        except Exception:
            children = []
            child_count = 0

        name = (msg_control.Name or "").strip()

        # ---- 子控件为空 → 直接用 Name + Value ----
        if child_count == 0:
            if not name:
                return None
            if _is_special_message(name):
                return None
            if _is_time_text(name):
                return None
            # 尝试附加 Value
            value = ""
            try:
                value = (msg_control.Value or "").strip()
            except Exception:
                pass
            if value and value != name:
                return f"{name} {value}"
            return name

        # ---- 子控件非空 → 合并可读文本 ----
        # 先检查自身 Name（微信当前版本文本主要在 Name 里）
        if name:
            if not _is_special_message(name) and not _is_time_text(name):
                return name

        # 遍历子控件 Name 合并
        texts = []
        for child in children:
            child_name = (child.Name or "").strip()
            if child_name and not _is_special_message(child_name) and not _is_time_text(child_name):
                texts.append(child_name)

        if texts:
            return " ".join(texts)

        # 最后尝试 TextControl 子控件
        for child in children:
            if child.ControlTypeName == "TextControl":
                tc_name = (child.Name or "").strip()
                if tc_name and not _is_special_message(tc_name) and not _is_time_text(tc_name):
                    return tc_name

        return None

    except Exception as e:
        logger.debug(f"消息内容提取异常: {e}")
        return None


def _is_special_message(text: str) -> bool:
    """判断是否为特殊消息标记（非文本消息）"""
    for marker in SPECIAL_MSG_MARKERS:
        if text.startswith(marker) or text == marker:
            return True
    return False


def _is_time_text(text: str) -> bool:
    """判断是否为时间分割线文本"""
    if not text:
        return False
    text = text.strip()
    # 纯时间格式
    if _TIME_PATTERN.match(text):
        return True
    # 短文本含时间字符（如 "昨天 18:30"）
    if len(text) <= 30 and _TIME_PATTERN.search(text) and not any(
        kw in text for kw in ["收到", "你好", "已添加", "谢谢", "在"]
    ):
        return True
    return False
