"""微信联系人二次确认模块

P0-2E：在 open_chat_by_nickname 成功后、write_text_to_input 发送前，
确认当前聊天窗口的联系人就是目标微信昵称。

核心约束：
  - 截图只能作为人工复核证据，不能作为 verified=true 的依据
  - 只有通过 UIA/窗口文本读取到 expected_nickname 才能 verified=true
  - 无法确认时必须返回 verified=false, manual_review_required=true

确认策略（按优先级）：

  策略 A：顶部标题确认
    - 使用 find_current_chat_title() 读取顶部标题
    - 如果标题包含 expected_nickname → verified=true
    - 成本最低，优先执行
    - 成功则不再点击资料卡

  策略 B：点击顶部标题 → 右侧资料卡
    - 点击聊天窗口顶部标题区域
    - 等待右侧资料卡弹出
    - 尝试通过 UIA 读取资料卡中的文本
    - 如果文本包含 expected_nickname → verified=true
    - 验证后按 Esc 关闭资料卡

  策略 C：点击联系人头像 → 资料卡昵称
    - 点击聊天区中对方头像
    - 等待资料卡弹出
    - 尝试通过 UIA 读取资料卡文本
    - 如果文本包含 expected_nickname → verified=true
    - 验证后按 Esc 关闭资料卡
"""

import ctypes
import logging
import time

import uiautomation as uia

from app.wechat_ui.window_locator import (
    find_wechat_window,
    find_current_chat_title,
    ensure_wechat_visible,
    check_wechat_ready_for_automation,
    WECHAT_MANUAL_OPEN_MESSAGE,
)
from app.wechat_ui.screenshot_debug import save_debug_screenshot
from app.wechat_ui.contact_ocr_verifier import verify_contact_by_top_title_ocr
from app.wechat_ui.ocr_matcher import (
    build_contact_aliases,
    normalize_wechat_contact_name,
)

logger = logging.getLogger(__name__)


def verify_current_chat_contact(
    expected_nickname: str,
    win_rect: dict = None,
    wechat_id: str | None = None,
    remark: str | None = None,
    search_keyword_used: str | None = None,
    select_method: str | None = None,
    focus_after_select: str | None = None,
    candidate_source: str | None = None,
    candidate_is_normalized_fallback: bool = False,
) -> dict:
    """
    确认当前微信聊天窗口的联系人是否为目标微信昵称。

    Args:
        expected_nickname: 期望的微信昵称
        win_rect: 窗口矩形（可选，用于计算点击坐标）

    Returns:
        {
            "verified": bool,
            "expected_nickname": str,
            "matched_text": str | None,
            "strategy": str | None,
            "manual_review_required": bool,
            "failure_stage": str | None,
            "debug_screenshots": list[str],
            "warning": str | None,
            "message": str,
        }
    """
    result = {
        "verified": False,
        "expected_nickname": expected_nickname,
        "matched_text": None,
        "strategy": None,
        "manual_review_required": True,
        "failure_stage": None,
        "debug_screenshots": [],
        "warning": None,
        "message": "",
        "confidence": None,
        "ocr_text": None,
        "partial_match": False,
        "evidence": {},
        "target_nickname": expected_nickname,
        "search_keyword_used": search_keyword_used,
        "expected_aliases": [],
        "normalized_expected_aliases": [],
        "observed_contact_texts": [],
        "normalized_observed_contact_texts": [],
        "select_method": select_method,
        "focus_after_select": focus_after_select,
        "candidate_source": candidate_source,
        "candidate_is_normalized_fallback": bool(candidate_is_normalized_fallback),
        "verify_method": None,
        "verify_result": None,
        "manual_review_reason": None,
        "uia_title_candidates": [],
        "normalized_uia_title_candidates": [],
        "ocr_title_candidates": [],
        "normalized_ocr_title_candidates": [],
    }

    if not expected_nickname or not expected_nickname.strip():
        result["failure_stage"] = "empty_nickname"
        result["message"] = "期望昵称为空，无法验证"
        return result

    expected_nickname = expected_nickname.strip()
    expected_aliases = build_contact_aliases(
        expected_nickname,
        wechat_id=wechat_id,
        remark=remark,
        search_keyword_used=search_keyword_used,
    )
    normalized_expected_aliases = list(dict.fromkeys(
        item for item in (normalize_wechat_contact_name(alias) for alias in expected_aliases) if item
    ))
    result["expected_aliases"] = expected_aliases
    result["normalized_expected_aliases"] = normalized_expected_aliases

    hwnd = None
    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
        if isinstance(hwnd, int):
            ready = check_wechat_ready_for_automation(hwnd)
            if not ready.get("success"):
                result["failure_stage"] = "wechat_not_ready"
                result["message"] = WECHAT_MANUAL_OPEN_MESSAGE
                result["ready_check"] = ready
                return result
        else:
            ready = {"success": True, "message": "non-win32 test window"}
    except Exception as exc:
        result["failure_stage"] = "wechat_not_ready"
        result["message"] = f"{WECHAT_MANUAL_OPEN_MESSAGE}（{exc}）"
        return result

    # =====================================================
    # 策略 A：读取顶部标题（成本最低，优先执行）
    # =====================================================
    logger.info("联系人确认 策略A: 读取顶部标题, expected='%s'", expected_nickname)

    try:
        uia_title_result = get_current_chat_title_by_uia(window)
        result["uia_title_candidates"] = uia_title_result.get("candidates") or []
        result["normalized_uia_title_candidates"] = _normalized_texts(result["uia_title_candidates"])
        chat_title = uia_title_result.get("title")

        if chat_title:
            logger.info("策略A: 读取到标题='%s'", chat_title)
            _add_observed_text(result, chat_title)

            title_match = _match_contact_text(chat_title, expected_aliases)
            if title_match.get("matched"):
                if _is_ambiguous_normalized_fallback(
                    title_match,
                    chat_title,
                    expected_nickname,
                    candidate_is_normalized_fallback,
                ):
                    result["strategy"] = "uia_chat_title"
                    result["verify_method"] = "uia_chat_title"
                    result["verify_result"] = "manual_review_required"
                    result["manual_review_reason"] = "ambiguous_normalized_fallback_title"
                    result["failure_stage"] = "manual_review_required"
                    result["message"] = "标准化兜底候选只取得去标点标题，需人工复核"
                    return result
                result["verified"] = True
                result["matched_text"] = chat_title
                result["strategy"] = "uia_chat_title"
                result["manual_review_required"] = False
                result["verify_method"] = "uia_chat_title"
                result["verify_result"] = title_match.get("method")
                result["message"] = f"策略A成功: 标题'{chat_title}'匹配'{expected_nickname}'"
                logger.info("策略A成功: title='%s' 匹配 '%s'", chat_title, expected_nickname)
                return result
            else:
                logger.info(
                    "策略A: 标题'%s'不匹配'%s'，继续尝试策略B",
                    chat_title, expected_nickname,
                )
        else:
            logger.info("策略A: 未读取到标题，继续策略B")
    except Exception as e:
        logger.warning("策略A异常: %s", e)

    # =====================================================
    # 策略 B：顶部标题 OCR。只截图识别，不点击资料卡，不发送 Esc。
    # =====================================================
    if isinstance(hwnd, int):
        try:
            ocr_result = get_current_chat_title_by_ocr_title_region(
                expected_nickname=expected_nickname,
                hwnd=hwnd,
                position="right",
                engine="easyocr",
            )
            result["strategy"] = ocr_result.get("strategy") or "ocr_top_title"
            result["confidence"] = ocr_result.get("confidence")
            result["ocr_text"] = ocr_result.get("ocr_text")
            result["partial_match"] = bool(ocr_result.get("partial_match"))
            result["matched_text"] = ocr_result.get("matched_text") or ocr_result.get("ocr_text")
            result["manual_review_required"] = bool(ocr_result.get("manual_review_required", True))
            result["failure_stage"] = ocr_result.get("failure_stage")
            result["verify_method"] = result["strategy"]
            result["verify_result"] = ocr_result.get("match_method")
            ocr_candidates = [
                value for value in (ocr_result.get("ocr_text"), ocr_result.get("matched_text"))
                if (value or "").strip()
            ]
            result["ocr_title_candidates"] = list(dict.fromkeys(ocr_candidates))
            result["normalized_ocr_title_candidates"] = _normalized_texts(result["ocr_title_candidates"])
            _add_observed_text(result, ocr_result.get("ocr_text"))
            _add_observed_text(result, ocr_result.get("matched_text"))
            result["evidence"] = {
                "screenshot_path": ocr_result.get("screenshot_path"),
                "cropped_path": ocr_result.get("cropped_path"),
                "preprocessed_path": ocr_result.get("preprocessed_path"),
            }
            for key in ("screenshot_path", "cropped_path", "preprocessed_path"):
                path = ocr_result.get(key)
                if path:
                    result["debug_screenshots"].append(path)

            if ocr_result.get("verified"):
                if _is_ambiguous_normalized_fallback(
                    {"method": ocr_result.get("match_method")},
                    ocr_result.get("matched_text") or ocr_result.get("ocr_text") or "",
                    expected_nickname,
                    candidate_is_normalized_fallback,
                ):
                    result["verified"] = False
                    result["manual_review_required"] = True
                    result["failure_stage"] = "manual_review_required"
                    result["verify_result"] = "manual_review_required"
                    result["manual_review_reason"] = "ambiguous_normalized_fallback_title"
                    result["message"] = "标准化兜底候选只取得去标点标题，需人工复核"
                    return result
                result["verified"] = True
                result["manual_review_required"] = False
                result["failure_stage"] = None
                result["verify_result"] = ocr_result.get("match_method") or "ocr_verified"
                result["message"] = f"OCR 顶部标题确认成功: {ocr_result.get('ocr_text')}"
                return result

            result["verified"] = False
            result["manual_review_reason"] = "title_evidence_not_matched"
            result["warning"] = "OCR 顶部标题未能确认联系人，已阻止后续自动发送"
            result["message"] = "OCR 顶部标题未能确认联系人，需要人工复核"
            result["verify_result"] = (
                "partial_match"
                if result["partial_match"]
                else "manual_review_required"
                if result["manual_review_required"]
                else "unverified"
            )
            return result
        except Exception as e:
            logger.warning("策略B OCR 顶部标题异常: %s", e)
            result["strategy"] = "ocr_top_title"
            result["failure_stage"] = "ocr_top_title_exception"
            result["manual_review_required"] = True
            result["manual_review_reason"] = "ocr_title_exception"
            result["message"] = f"OCR 顶部标题异常，需要人工复核: {e}"
            return result

    # =====================================================
    # 策略 B：点击顶部标题 → 右侧资料卡
    # =====================================================
    logger.info("联系人确认 策略B: 点击顶部标题获取资料卡")

    if win_rect:
        try:
            # 保存点击前截图
            ss_before = save_debug_screenshot(
                "verify_contact", "before_title_click",
            )
            if ss_before:
                result["debug_screenshots"].append(ss_before)

            # 点击顶部标题区域（右侧聊天区域的顶部中心）
            # 标题区域：聊天区水平中心偏右、顶部 5-8% 高度
            chat_left = win_rect["left"] + int((win_rect["right"] - win_rect["left"]) * 0.4)
            chat_center_x = (chat_left + win_rect["right"]) // 2
            title_y = win_rect["top"] + int((win_rect["bottom"] - win_rect["top"]) * 0.06)

            logger.info("策略B: 点击标题区域 (%d, %d)", chat_center_x, title_y)

            ctypes.windll.user32.SetCursorPos(chat_center_x, title_y)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
            time.sleep(1.0)  # 等待资料卡弹出

            # 保存资料卡截图
            ss_card = save_debug_screenshot(
                "verify_contact", "title_profile_card",
                region=(win_rect["left"], win_rect["top"],
                        win_rect["right"], win_rect["bottom"]),
            )
            if ss_card:
                result["debug_screenshots"].append(ss_card)

            # 尝试通过 UIA 读取资料卡文本
            card_text = _try_read_profile_card_text(expected_nickname)

            # P0-2G：点击聊天区空白区域关闭资料卡（优先于 Esc）
            # 原因：Esc 可能导致 Qt5 微信窗口被隐藏
            close_result = _close_profile_card_safe(win_rect)
            if close_result.get("automation_allowed") is False:
                result["failure_stage"] = "profile_card_close_unverified"
                result["warning"] = close_result.get("message")
                result["message"] = close_result.get("message")
                return result

            _add_observed_text(result, card_text)
            card_match = _match_contact_text(card_text or "", expected_aliases)
            if card_match.get("matched"):
                result["verified"] = True
                result["matched_text"] = card_text
                result["strategy"] = "title_profile_card"
                result["manual_review_required"] = False
                result["verify_method"] = "title_profile_card"
                result["verify_result"] = card_match.get("method")
                result["message"] = f"策略B成功: 资料卡文本'{card_text}'匹配'{expected_nickname}'"
                logger.info("策略B成功: card_text='%s'", card_text)
                return result

            logger.info("策略B: 资料卡未匹配 (card_text='%s')", card_text)

        except Exception as e:
            logger.warning("策略B异常: %s", e)
            # 确保关闭可能打开的资料卡
            try:
                _close_profile_card_safe(win_rect)
            except Exception:
                pass
    else:
        logger.info("策略B: 无 win_rect，跳过")

    # =====================================================
    # 策略 C：点击联系人头像 → 资料卡昵称
    # =====================================================
    logger.info("联系人确认 策略C: 点击联系人头像获取资料卡")

    if win_rect:
        try:
            # 对方头像在聊天区域左侧，约水平 45%、垂直 60% 位置
            # （消息一般在下半部分，头像在消息左侧）
            avatar_x = win_rect["left"] + int((win_rect["right"] - win_rect["left"]) * 0.45)
            avatar_y = win_rect["top"] + int((win_rect["bottom"] - win_rect["top"]) * 0.60)

            logger.info("策略C: 点击头像区域 (%d, %d)", avatar_x, avatar_y)

            ctypes.windll.user32.SetCursorPos(avatar_x, avatar_y)
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(1.0)

            # 保存头像资料卡截图
            ss_avatar = save_debug_screenshot(
                "verify_contact", "avatar_profile_card",
                region=(win_rect["left"], win_rect["top"],
                        win_rect["right"], win_rect["bottom"]),
            )
            if ss_avatar:
                result["debug_screenshots"].append(ss_avatar)

            # 尝试读取资料卡文本
            card_text = _try_read_profile_card_text(expected_nickname)

            # P0-2G：安全关闭资料卡
            close_result = _close_profile_card_safe(win_rect)
            if close_result.get("automation_allowed") is False:
                result["failure_stage"] = "profile_card_close_unverified"
                result["warning"] = close_result.get("message")
                result["message"] = close_result.get("message")
                return result

            _add_observed_text(result, card_text)
            card_match = _match_contact_text(card_text or "", expected_aliases)
            if card_match.get("matched"):
                result["verified"] = True
                result["matched_text"] = card_text
                result["strategy"] = "avatar_profile_card"
                result["manual_review_required"] = False
                result["verify_method"] = "avatar_profile_card"
                result["verify_result"] = card_match.get("method")
                result["message"] = f"策略C成功: 资料卡文本'{card_text}'匹配'{expected_nickname}'"
                logger.info("策略C成功: card_text='%s'", card_text)
                return result

            logger.info("策略C: 资料卡未匹配 (card_text='%s')", card_text)

        except Exception as e:
            logger.warning("策略C异常: %s", e)
            try:
                _close_profile_card_safe(win_rect)
            except Exception:
                pass
    else:
        logger.info("策略C: 无 win_rect，跳过")

    # =====================================================
    # 三种策略都无法确认 → 不允许发送
    # =====================================================
    result["failure_stage"] = "contact_not_verified"
    result["verify_result"] = "manual_review_required"
    result["manual_review_reason"] = "title_evidence_not_matched"
    result["warning"] = f"无法确认当前聊天对象为目标销售 '{expected_nickname}'，已阻止自动发送"
    result["message"] = (
        f"三种确认策略均无法验证联系人 '{expected_nickname}'。"
        f"截图已保存供人工复核。"
    )
    logger.warning(
        "联系人确认失败: expected='%s', 三种策略均未匹配",
        expected_nickname,
    )
    return result


def get_current_chat_title_by_uia(window=None) -> dict:
    """结构化读取当前聊天标题，失败只返回诊断。"""
    raw = {}
    try:
        if window is None:
            window = find_wechat_window()
        title = (find_current_chat_title(window) or "").strip()
        raw = {
            "window_name": getattr(window, "Name", None),
            "window_class": getattr(window, "ClassName", None),
            "window_control_type": getattr(window, "ControlTypeName", None),
        }
        return {
            "ok": bool(title),
            "title": title or None,
            "method": "uia_chat_title",
            "candidates": [title] if title else [],
            "raw": raw,
            "reason": None if title else "uia_title_not_found",
        }
    except Exception as exc:
        return {
            "ok": False,
            "title": None,
            "method": "uia_chat_title",
            "candidates": [],
            "raw": raw,
            "reason": "uia_title_exception",
            "error": str(exc),
        }


def get_current_chat_title_by_ocr_title_region(
    expected_nickname: str,
    hwnd: int,
    position: str = "right",
    engine: str = "easyocr",
) -> dict:
    """只识别微信顶部标题区域的 OCR 兜底。"""
    return verify_contact_by_top_title_ocr(
        expected_nickname=expected_nickname,
        hwnd=hwnd,
        position=position,
        engine=engine,
    )


def _add_observed_text(result: dict, text: str | None) -> None:
    text = (text or "").strip()
    if not text:
        return
    if text not in result["observed_contact_texts"]:
        result["observed_contact_texts"].append(text)
    normalized = normalize_wechat_contact_name(text)
    if normalized and normalized not in result["normalized_observed_contact_texts"]:
        result["normalized_observed_contact_texts"].append(normalized)


def _normalized_texts(values: list[str]) -> list[str]:
    return list(dict.fromkeys(
        normalized
        for normalized in (normalize_wechat_contact_name(value) for value in values)
        if normalized
    ))


def _is_ambiguous_normalized_fallback(
    match: dict,
    actual: str,
    expected_nickname: str,
    candidate_is_normalized_fallback: bool,
) -> bool:
    if not candidate_is_normalized_fallback:
        return False
    if match.get("method") != "exact_normalized_match":
        return False
    expected = (expected_nickname or "").strip()
    actual = (actual or "").strip()
    if not expected or actual == expected:
        return False
    return normalize_wechat_contact_name(expected) != expected


def _match_contact_text(actual: str, expected_aliases: list[str]) -> dict:
    """只允许原文或标准化后的完全匹配，不做包含匹配。"""
    actual = (actual or "").strip()
    if not actual:
        return {"matched": False, "method": None}
    for alias in expected_aliases:
        if actual == alias:
            return {"matched": True, "method": "exact_match", "alias": alias}
        if actual.isascii() and alias.isascii() and actual.lower() == alias.lower():
            return {"matched": True, "method": "exact_case_insensitive_match", "alias": alias}
        normalized_actual = normalize_wechat_contact_name(actual)
        normalized_alias = normalize_wechat_contact_name(alias)
        if normalized_actual and normalized_actual == normalized_alias:
            return {"matched": True, "method": "exact_normalized_match", "alias": alias}
    return {"matched": False, "method": None}


def _nickname_matches(expected: str, actual: str) -> bool:
    """兼容旧测试入口，内部使用安全的精确/标准化精确匹配。"""
    return bool(_match_contact_text(actual, build_contact_aliases(expected)).get("matched"))


def _try_read_profile_card_text(expected_nickname: str) -> str | None:
    """
    尝试通过 UIA 读取当前窗口中与期望昵称相关的文本。

    遍历微信窗口控件树，查找包含 expected_nickname 的文本控件。
    只返回找到的匹配文本，不返回其他内容。

    Returns:
        匹配到的文本，或 None
    """
    try:
        window = find_wechat_window()
        # 在窗口中搜索包含目标昵称的文本控件
        candidates = []
        for ctrl, depth in window.WalkControl(maxDepth=10):
            name = ctrl.Name or ""
            if not name:
                continue
            if _nickname_matches(expected_nickname, name):
                candidates.append(name)
            if depth > 8:
                continue

        if candidates:
            # 优先返回最短的匹配（更精确）
            candidates.sort(key=len)
            return candidates[0]

        return None

    except Exception as e:
        logger.warning("读取资料卡文本失败: %s", e)
        return None


def _close_profile_card_safe(win_rect: dict, allow_esc_fallback: bool = False) -> dict:
    """
    P0-2G：安全关闭微信资料卡。

    优先点击聊天窗口空白区域关闭资料卡，避免使用 Esc。
    因为 Esc 可能导致 Qt5 微信窗口被隐藏（IsWindowVisible=False）。

    如果点击空白无效，回退到 Esc + ensure_wechat_visible 恢复。

    Args:
        win_rect: 窗口矩形 {"left", "top", "right", "bottom"}

    Returns:
        {"method", "esc_used", "visibility_restored", "message"}
    """
    user32 = ctypes.windll.user32

    # 策略 1：点击聊天区域底部空白处（输入框下方不太可能有关闭目标）
    # 聊天区中心偏右、底部 90% 位置（通常是消息列表的空白区域）
    try:
        chat_left = win_rect["left"] + int((win_rect["right"] - win_rect["left"]) * 0.55)
        blank_y = win_rect["top"] + int((win_rect["bottom"] - win_rect["top"]) * 0.90)
        logger.info("安全关闭资料卡: 点击空白区域 (%d, %d)", chat_left, blank_y)

        user32.SetCursorPos(chat_left, blank_y)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        time.sleep(0.3)

        # 检查微信窗口是否仍然可见
        try:
            hwnd = find_wechat_window().NativeWindowHandle
            if hwnd and user32.IsWindowVisible(hwnd):
                return {
                    "method": "click_blank",
                    "esc_used": False,
                    "visibility_restored": False,
                    "message": "点击空白区域关闭资料卡，窗口仍可见",
                }
        except Exception:
            pass

    except Exception as e:
        logger.debug("点击空白区域失败: %s", e)

    if not allow_esc_fallback:
        logger.warning("资料卡关闭未确认，业务路径不使用 Esc 回退")
        return {
            "method": "click_blank_unverified",
            "esc_used": False,
            "visibility_restored": False,
            "automation_allowed": False,
            "message": "已点击空白区域尝试关闭资料卡；业务路径禁止使用 Esc 回退，需停止后续自动化",
        }

    # 策略 2：回退到 Esc + 立即恢复可见性
    logger.warning("点击空白区域未关闭资料卡，回退到 Esc + 恢复可见性")
    try:
        uia.SendKeys("{Esc}", waitTime=0.05)
        time.sleep(0.2)

        # Esc 后立即检查并恢复窗口可见性
        vis_result = ensure_wechat_visible()
        esc_hid = not vis_result.get("was_visible", True)

        if vis_result.get("recovered"):
            logger.info("Esc 后窗口已恢复可见")
        elif esc_hid:
            logger.warning("esc_hid_wechat_window: Esc 导致微信窗口隐藏，已尝试恢复")

        return {
            "method": "esc_with_recovery",
            "esc_used": True,
            "esc_hid_window": esc_hid,
            "visibility_restored": vis_result.get("recovered", False),
            "message": f"Esc 关闭资料卡，窗口恢复: {vis_result.get('message', '')}",
        }

    except Exception as e:
        logger.error("Esc 恢复异常: %s", e)
        return {
            "method": "esc_exception",
            "esc_used": True,
            "visibility_restored": False,
            "message": f"Esc 后恢复异常: {e}",
        }
