"""A-FIX5：诊断脚本控件结构 dump 脱敏单元测试。

验证 scripts/probe_phase8b_wechat_file_message_controls.py 的两个纯函数：
  - dump_control_structure：UIA 控件树脱敏 dump（顶层 + 1-2 层子控件）
  - _sanitize_sender_debug：strategy 白名单 + 完全删除 reason + 仅数值字段

安全约束（任务硬要求）：
  1. 原始 Name 不出现在输出
  2. 目标名称只能以指纹出现
  3. 深度（max_depth）和节点数（max_nodes）上限生效
  4. 不调用 input_writer/CF_HDROP/send-intent/Enter（纯函数，无微信交互）
  5. 不保存截图或其他文件（纯内存）
  6. 先红灯，后实现

不启动真实微信；用 mock UIA 控件构造树。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

# 从 scripts/ 路径加载诊断脚本模块（scripts 非包，用 importlib）
_SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "probe_phase8b_wechat_file_message_controls.py"
)
_spec = importlib.util.spec_from_file_location("probe_phase8b_ctl_dump", _SCRIPT)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


# ---------- mock UIA 控件 ----------


class _Rect:
    """模拟 uiautomation BoundingRectangle。"""

    def __init__(self, left=0, top=0, right=100, bottom=40):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


class _MockControl:
    """模拟 uiautomation Control：支持 GetChildren/Name/ControlTypeName/ClassName/BoundingRectangle。"""

    def __init__(self, *, name="", control_type="ListItemControl", class_name="",
                 children=None, rect=None):
        self.Name = name
        self.ControlTypeName = control_type
        self.ClassName = class_name
        self.BoundingRectangle = rect or _Rect()
        self._children = children or []

    def GetChildren(self):
        return list(self._children)


# 敏感样本（模拟目标文件气泡可能携带的原文）
_SECRET_NAME = "report4_销售单车成本_销售+未分配+合计_虚构视觉样本.xlsx"


def _tree_with_depth3():
    """顶层(0) → 子(1) → 孙(2) → 曾孙(3，应被 max_depth=2 截断)。"""
    great_grand = _MockControl(
        name="深度3不应出现", control_type="TextControl", class_name="DeepLabel",
    )
    grandchild = _MockControl(
        name=_SECRET_NAME, control_type="TextControl", class_name="GrandLabel",
        children=[great_grand],
    )
    child = _MockControl(
        name="子控件正文不应泄露", control_type="PaneControl", class_name="Qt5ChildPane",
        children=[grandchild],
    )
    return _MockControl(
        name=_SECRET_NAME, control_type="ListItemControl", class_name="Qt5MsgItem",
        children=[child],
    )


# ---------- dump_control_structure 单元 ----------


def test_dump_no_raw_name():
    """安全：输出 JSON 不含任何原始 Name（只含指纹）。"""
    top = _tree_with_depth3()
    nodes = probe.dump_control_structure(top, list_rect=_Rect(0, 0, 800, 600))
    blob = json.dumps(nodes, ensure_ascii=False)
    assert _SECRET_NAME not in blob, "原始文件名泄露到 dump 输出"
    assert "子控件正文不应泄露" not in blob, "子控件正文泄露"
    assert "深度3不应出现" not in blob, "深度3节点内容泄露"


def test_dump_depth_limit():
    """max_depth=2 时，最大深度为 2（顶层0/子1/孙2），曾孙3 不出现。"""
    top = _tree_with_depth3()
    nodes = probe.dump_control_structure(top, list_rect=_Rect(0, 0, 800, 600), max_depth=2)
    depths = [n["depth"] for n in nodes]
    assert depths, "应至少返回顶层节点"
    assert max(depths) <= 2, f"深度超限: max depth={max(depths)}"
    # 曾孙（深度3）的 class_name 不应出现
    blob = json.dumps(nodes, ensure_ascii=False)
    assert "深度3不应出现" not in blob


def test_dump_node_limit():
    """max_nodes 生效：节点数 > max_nodes 时截断。"""
    kids = [_MockControl(name=f"c{i}", control_type="TextControl") for i in range(60)]
    top = _MockControl(name="top", children=kids)
    nodes = probe.dump_control_structure(top, max_nodes=50)
    assert len(nodes) <= 50, f"节点上限失效: {len(nodes)}"


def test_dump_default_limits():
    """默认 max_depth=2、max_nodes=50。"""
    top = _MockControl(name="x")
    nodes = probe.dump_control_structure(top)
    assert len(nodes) <= 50
    assert all(n["depth"] <= 2 for n in nodes)


def test_dump_node_fields():
    """每节点字段完整：path/depth/control_type/class_name/name_fp/rect。"""
    top = _MockControl(
        name="x", control_type="ListItemControl", class_name="C",
        rect=_Rect(10, 20, 110, 60),
    )
    nodes = probe.dump_control_structure(top, list_rect=_Rect(0, 0, 800, 600))
    assert len(nodes) == 1
    n = nodes[0]
    for k in ("path", "depth", "control_type", "class_name", "name_fp", "rect"):
        assert k in n, f"节点缺字段: {k}"
    assert n["depth"] == 0
    assert n["control_type"] == "ListItemControl"
    assert n["class_name"] == "C"


def test_dump_rect_relative_to_list():
    """rect 相对 list_rect：left/top 为相对偏移，width/height 为尺寸。"""
    top = _MockControl(name="x", rect=_Rect(100, 200, 300, 240))
    list_rect = _Rect(50, 50, 850, 650)
    nodes = probe.dump_control_structure(top, list_rect=list_rect)
    r = nodes[0]["rect"]
    assert r["left"] == 50, f"相对 left 错误: {r['left']}"   # 100 - 50
    assert r["top"] == 150, f"相对 top 错误: {r['top']}"      # 200 - 50
    assert r["width"] == 200, f"width 错误: {r['width']}"     # 300 - 100
    assert r["height"] == 40, f"height 错误: {r['height']}"   # 240 - 200


def test_dump_path_hierarchy():
    """path 层级路径正确：顶层 '0'，子 '0.N'，孙 '0.N.M'。"""
    grandchild = _MockControl(name="g", control_type="TextControl")
    child = _MockControl(name="c", control_type="PaneControl", children=[grandchild])
    top = _MockControl(name="t", children=[child])
    nodes = probe.dump_control_structure(top, max_depth=2)
    paths = [n["path"] for n in nodes]
    assert "0" in paths, "顶层 path 应为 '0'"
    assert "0.0" in paths, "子 path 应为 '0.0'"
    assert "0.0.0" in paths, "孙 path 应为 '0.0.0'"


def test_name_fp_format_and_empty():
    """name_fp 格式 'len=N fp=xxxxxxxx'；空 Name → 空字符串。"""
    top = _MockControl(name=_SECRET_NAME)
    fp = probe.dump_control_structure(top)[0]["name_fp"]
    assert fp.startswith("len=") and " fp=" in fp, f"指纹格式错误: {fp}"
    assert _SECRET_NAME not in fp, "指纹含原文"
    # 空 Name
    empty_fp = probe.dump_control_structure(_MockControl(name=""))[0]["name_fp"]
    assert empty_fp == "", f"空 Name 应为空指纹: {empty_fp!r}"


def test_dump_get_children_exception_safe():
    """GetChildren 抛异常时该节点不崩溃（输出该节点但不展开子控件）。"""
    class _Boom(_MockControl):
        def GetChildren(self):
            raise RuntimeError("UIA error")

    top = _Boom(name="x")
    nodes = probe.dump_control_structure(top)
    assert len(nodes) == 1, "GetChildren 异常应只返回顶层节点"


# ---------- _sanitize_sender_debug 单元 ----------


def test_sanitize_keeps_whitelist_strategy_and_numeric():
    """保留 strategy 白名单值 + 数值（int/float，非 bool）；reason 完全删除。"""
    debug = {
        "strategy": "item_edges",
        "reason": "边缘距离判断",
        "edge_left": 120,
        "edge_right": 780.5,
        "mid_x": 400.0,
    }
    out = probe._sanitize_sender_debug(debug)
    assert out is not None
    assert out["strategy"] == "item_edges"
    assert "reason" not in out, "reason 应完全删除"
    assert out["edge_left"] == 120
    assert out["edge_right"] == 780.5
    assert out["mid_x"] == 400.0


def test_sanitize_reason_content_not_leaked():
    """reason 含时间文本/文件名/异常字符串时，序列化输出不得命中任何原文。

    覆盖 message_parser identify_sender 三类动态 reason：
      - system：时间分割线原文（含 name）
      - unknown：动态子控件摘要
      - exception：str(e) 异常文本
    """
    secret_time = "2026-07-13 19:30"
    secret_file = "report4_销售单车成本_销售+未分配+合计_虚构视觉样本.xlsx"
    secret_exc = "KeyError: '某敏感键'"
    cases = [
        {"strategy": "system", "reason": f"时间分割线: '{secret_time}' (子控件=1)"},
        {"strategy": "system", "reason": f"无内容，文件: {secret_file}"},
        {"strategy": "exception", "reason": secret_exc},
        {"strategy": "unknown", "reason": f"所有策略未命中，子控件: {secret_file}"},
    ]
    for debug in cases:
        out = probe._sanitize_sender_debug(debug)
        blob = json.dumps(out, ensure_ascii=False)
        assert secret_time not in blob, f"时间原文泄露: {blob}"
        assert secret_file not in blob, f"文件名原文泄露: {blob}"
        assert secret_exc not in blob, f"异常原文泄露: {blob}"
        assert "reason" not in (out or {}), "reason 字段应被完全删除"


def test_sanitize_dynamic_strategy_to_unknown():
    """strategy 不在白名单（动态值）→ 归一为 'unknown'，不原样输出。"""
    out = probe._sanitize_sender_debug({"strategy": "dynamic_new_strategy_xyz"})
    assert out is not None
    assert out["strategy"] == "unknown"
    assert "dynamic_new_strategy_xyz" not in json.dumps(out, ensure_ascii=False)


def test_sanitize_all_whitelist_strategies_preserved():
    """strategy 白名单全部 7 个固定值原样保留。"""
    whitelist = {
        "system", "item_edges", "button_avatar",
        "other_avatar", "text_position", "unknown", "exception",
    }
    for s in whitelist:
        out = probe._sanitize_sender_debug({"strategy": s})
        assert out is not None
        assert out["strategy"] == s


def test_sanitize_drops_non_numeric_content():
    """丢弃非数值字符串内容、bool、嵌套 dict；reason 完全删除。"""
    debug = {
        "strategy": "text_position",
        "reason": "TextControl 中心位置",
        "raw_name": "某客户正文不应泄露",     # 字符串内容 → 丢弃
        "screenshot": {"r": 200, "g": 200, "b": 200},  # 嵌套 dict → 丢弃
        "has_avatar": True,                    # bool → 丢弃
        "count": 3,                            # 数值 → 保留
    }
    out = probe._sanitize_sender_debug(debug)
    assert out is not None
    assert "raw_name" not in out, "字符串正文未过滤"
    assert "screenshot" not in out, "嵌套 dict 未过滤"
    assert "has_avatar" not in out, "bool 未过滤"
    assert "reason" not in out, "reason 应完全删除"
    assert out["count"] == 3


def test_sanitize_none_and_empty():
    """None / 非 dict / 空 dict → None。"""
    assert probe._sanitize_sender_debug(None) is None
    assert probe._sanitize_sender_debug("not dict") is None
    assert probe._sanitize_sender_debug({}) is None
