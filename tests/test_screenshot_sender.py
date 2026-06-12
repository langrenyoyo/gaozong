"""P0-REPLY-3B：截图像素颜色分析 sender 识别测试

测试 _sender_by_screenshot_color 函数对不同像素模式的判断：
- 右侧绿色像素 → self
- 左侧白色/浅灰像素 → friend
- 纯背景 → None（unknown）
- 异常 → None（unknown）
"""

import pytest
from PIL import Image

from app.wechat_ui.message_parser import (
    _sender_by_screenshot_color,
    _is_green_pixel,
    _is_background_pixel,
)

# 微信实际像素值
WECHAT_GREEN = (157, 242, 159)      # self 气泡绿色
WECHAT_FRIEND_BUBBLE = (238, 238, 240)  # friend 气泡白色
WECHAT_BACKGROUND = (250, 250, 250)     # 聊天背景
WECHAT_TEXT_DARK = (50, 50, 50)         # 文字颜色


# ========== 像素判断辅助函数测试 ==========


class TestPixelClassification:
    """测试像素分类辅助函数。"""

    def test_green_pixel_detected(self):
        """微信绿色气泡像素应被判为绿色"""
        assert _is_green_pixel(157, 242, 159) is True

    def test_green_pixel_similar_shades(self):
        """相近的绿色也应被检测到"""
        assert _is_green_pixel(140, 200, 130) is True  # G>R+30=170✓ G>B+30=160✓

    def test_background_not_green(self):
        """背景色不应被判为绿色"""
        assert _is_green_pixel(250, 250, 250) is False

    def test_friend_bubble_not_green(self):
        """friend 气泡色不应被判为绿色"""
        assert _is_green_pixel(238, 238, 240) is False

    def test_text_not_green(self):
        """文字颜色不应被判为绿色"""
        assert _is_green_pixel(50, 50, 50) is False

    def test_background_pixel_detected(self):
        """微信背景色应被判为背景"""
        assert _is_background_pixel(250, 250, 250) is True
        assert _is_background_pixel(248, 249, 250) is True

    def test_friend_bubble_not_background(self):
        """friend 气泡不是背景（R=238 < 245）"""
        assert _is_background_pixel(238, 238, 240) is False

    def test_green_not_background(self):
        """绿色气泡不是背景"""
        assert _is_background_pixel(157, 242, 159) is False

    def test_text_not_background(self):
        """文字不是背景"""
        assert _is_background_pixel(50, 50, 50) is False


# ========== 截图像素 sender 识别测试 ==========


def _make_item_image(
    w: int = 200,
    h: int = 50,
    left_zone_color: tuple | None = None,
    left_zone_width: float = 0.3,
    right_zone_color: tuple | None = None,
    right_zone_width: float = 0.3,
    bg_color: tuple = WECHAT_BACKGROUND,
) -> Image.Image:
    """创建模拟消息 item 截图。

    Args:
        w: 宽度
        h: 高度
        left_zone_color: 左侧区域颜色（None=全部背景）
        left_zone_width: 左侧区域占比（0-1）
        right_zone_color: 右侧区域颜色（None=全部背景）
        right_zone_width: 右侧区域占比（0-1）
        bg_color: 背景颜色
    """
    img = Image.new("RGB", (w, h), bg_color)
    pixels = img.load()

    if left_zone_color:
        left_end = int(w * left_zone_width)
        for y in range(h):
            for x in range(left_end):
                pixels[x, y] = left_zone_color

    if right_zone_color:
        right_start = int(w * (1 - right_zone_width))
        for y in range(h):
            for x in range(right_start, w):
                pixels[x, y] = right_zone_color

    return img


class TestSenderByScreenshotColor:
    """测试截图像素颜色分析策略。"""

    def test_right_green_bubble_self(self):
        """右侧绿色气泡 → self"""
        img = _make_item_image(
            w=200, h=50,
            right_zone_color=WECHAT_GREEN,
            right_zone_width=0.4,
        )
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        assert result == "self"
        assert debug["screenshot"]["result"] == "self"
        assert debug["screenshot"]["green_right_pct"] > 0.10

    def test_right_green_large_self(self):
        """大面积右侧绿色（长 self 消息，绿色从 ~30% 开始到 ~85%） → self

        真实 self 消息分布：绿色气泡从约 30% 宽度开始，右侧绿色占比高于左侧。
        """
        img = Image.new("RGB", (559, 189), WECHAT_BACKGROUND)
        pixels = img.load()
        # 绿色从 30% 到 85% 宽度，匹配真实 self 消息分布
        green_start = int(559 * 0.30)
        green_end = int(559 * 0.85)
        for y in range(189):
            for x in range(green_start, green_end):
                pixels[x, y] = WECHAT_GREEN

        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        # 右侧绿色应该显著高于左侧
        assert result == "self"
        assert debug["screenshot"]["green_right_pct"] > 0.10
        assert debug["screenshot"]["green_right_pct"] > debug["screenshot"]["green_left_pct"]

    def test_left_white_bubble_friend(self):
        """左侧白色/浅灰气泡，右侧无内容 → friend"""
        img = _make_item_image(
            w=200, h=50,
            left_zone_color=WECHAT_FRIEND_BUBBLE,
            left_zone_width=0.3,
        )
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        assert result == "friend"
        assert debug["screenshot"]["result"] == "friend"
        assert debug["screenshot"]["nonbg_left_pct"] > 0.05
        assert debug["screenshot"]["green_right_pct"] < 0.02

    def test_pure_background_unknown(self):
        """纯背景（系统消息） → None"""
        img = _make_item_image(w=200, h=50)
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        assert result is None
        assert debug["screenshot"]["result"] is None

    def test_both_sides_content_unknown(self):
        """左右都有内容（不应出现的异常情况） → None"""
        img = _make_item_image(
            w=200, h=50,
            left_zone_color=WECHAT_FRIEND_BUBBLE,
            left_zone_width=0.3,
            right_zone_color=WECHAT_FRIEND_BUBBLE,
            right_zone_width=0.3,
        )
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        # 左右都有非背景内容，无法判断 → None
        assert result is None

    def test_tiny_image_returns_none(self):
        """过小的截图 → None"""
        img = Image.new("RGB", (10, 5), WECHAT_BACKGROUND)
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        assert result is None
        assert "过小" in debug["screenshot"]["reason"]

    def test_debug_populated_on_success(self):
        """成功时 debug 包含完整分析数据"""
        img = _make_item_image(
            w=200, h=50,
            right_zone_color=WECHAT_GREEN,
            right_zone_width=0.4,
        )
        debug = {}
        _sender_by_screenshot_color(img, debug=debug)

        ss = debug["screenshot"]
        assert "green_left_pct" in ss
        assert "green_right_pct" in ss
        assert "nonbg_left_pct" in ss
        assert "nonbg_right_pct" in ss
        assert "sample_total" in ss
        assert "reason" in ss
        assert ss["sample_total"] > 0

    def test_no_green_but_left_dark_text_friend(self):
        """左侧有深色文字（非绿色、非背景） → friend"""
        img = _make_item_image(
            w=200, h=50,
            left_zone_color=WECHAT_TEXT_DARK,
            left_zone_width=0.15,
        )
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        # 左侧有非背景内容（深色文字），右侧无 → friend
        assert result == "friend"

    def test_mixed_green_and_background_self(self):
        """self 消息典型分布：左侧部分背景+部分绿色，右侧全绿"""
        img = Image.new("RGB", (200, 50), WECHAT_BACKGROUND)
        pixels = img.load()
        # 左侧 20-40% 填绿色，右侧 40-90% 填绿色
        for y in range(50):
            for x in range(40, 180):  # 20%-90% 位置
                pixels[x, y] = WECHAT_GREEN
        debug = {}
        result = _sender_by_screenshot_color(img, debug=debug)

        assert result == "self"


class TestSenderByScreenshotColorException:
    """测试截图分析异常处理。"""

    def test_exception_returns_none(self):
        """异常时返回 None，不伪造"""
        # 传入一个会导致异常的对象
        debug = {}
        result = _sender_by_screenshot_color(None, debug=debug)

        assert result is None
        assert "error" in debug["screenshot"]


# ========== identify_sender 截图策略集成测试 ==========


class TestIdentifySenderIntegration:
    """测试 identify_sender 在 full_width + 无子控件场景下调用截图策略。

    使用 mock 控件模拟微信扁平结构。
    """

    def _make_mock_control(self, name="测试消息", class_name="mmui::ChatTextItemView"):
        """创建模拟的 UIA 控件。"""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.Name = name
        mock.ClassName = class_name
        mock.ControlTypeName = "ListItemControl"

        # 模拟 BoundingRectangle
        rect = MagicMock()
        rect.left = 309
        rect.top = 100
        rect.right = 868
        rect.bottom = 156
        mock.BoundingRectangle = rect

        # GetChildren 返回空（微信扁平结构）
        mock.GetChildren.return_value = []
        # ButtonControl/ImageControl/TextControl 不存在
        mock.ButtonControl.return_value.Exists.return_value = False
        mock.ImageControl.return_value.Exists.return_value = False

        return mock

    def test_screenshot_self_detected(self):
        """full_width + 无子控件 + 右侧绿色截图 → self"""
        from app.wechat_ui.message_parser import identify_sender

        mock = self._make_mock_control("self消息")
        img = _make_item_image(
            w=559, h=56,
            right_zone_color=WECHAT_GREEN,
            right_zone_width=0.5,
        )

        debug = {}
        result = identify_sender(
            mock, chat_mid_x=588.5,
            list_rect=None,
            item_img=img,
            debug=debug,
        )

        assert result == "self"
        assert debug.get("strategy") == "screenshot" or debug.get("screenshot", {}).get("result") == "self"

    def test_screenshot_friend_detected(self):
        """full_width + 无子控件 + 左侧白色截图 → friend"""
        from app.wechat_ui.message_parser import identify_sender

        mock = self._make_mock_control("friend消息")
        img = _make_item_image(
            w=559, h=56,
            left_zone_color=WECHAT_FRIEND_BUBBLE,
            left_zone_width=0.3,
        )

        debug = {}
        result = identify_sender(
            mock, chat_mid_x=588.5,
            list_rect=None,
            item_img=img,
            debug=debug,
        )

        assert result == "friend"

    def test_screenshot_skipped_for_non_text_item(self):
        """非 ChatTextItemView 的控件跳过截图策略"""
        from app.wechat_ui.message_parser import identify_sender

        mock = self._make_mock_control("图片", class_name="mmui::ChatBubbleReferItemView")
        img = _make_item_image(w=559, h=100)

        debug = {}
        result = identify_sender(
            mock, chat_mid_x=588.5,
            list_rect=None,
            item_img=img,
            debug=debug,
        )

        # 非文本消息跳过截图 → unknown
        assert result == "unknown"
        assert "screenshot" not in debug

    def test_no_screenshot_still_works(self):
        """不传截图时仍能正常工作（降级为原有策略）"""
        from app.wechat_ui.message_parser import identify_sender

        mock = self._make_mock_control("消息")
        result = identify_sender(
            mock, chat_mid_x=588.5,
            list_rect=None,
            item_img=None,
        )

        # 无截图 + 无子控件 → unknown（原有行为不变）
        assert result == "unknown"
