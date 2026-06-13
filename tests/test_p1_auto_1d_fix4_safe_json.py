"""P1-AUTO-1D-FIX4：_safe_json_serialize 及 debug 端点安全序列化测试

覆盖：
1. 基本类型原样返回
2. dict/list 递归处理
3. Exception → {"type": ..., "message": ...}
4. UIA 控件对象 → 安全字段子集
5. 循环引用 → "<circular_ref>"
6. numpy 标量/ndarray
7. 未知对象 → {"type": ..., "repr": ...}
8. depth 超限截断
9. search-debug 端点异常时返回 200 success=false
10. search-result-debug 端点异常时返回 200 success=false
11. 不影响 poll-and-execute
12. 不影响 poll-and-detect
"""

import json
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.local_agent_main import (
    create_local_agent_app,
    _safe_json_serialize,
)


# ========== 1. _safe_json_serialize 单元测试 ==========


def test_safe_json_primitives():
    """基本类型原样返回。"""
    assert _safe_json_serialize(None) is None
    assert _safe_json_serialize("hello") == "hello"
    assert _safe_json_serialize(42) == 42
    assert _safe_json_serialize(3.14) == 3.14
    assert _safe_json_serialize(True) is True
    assert _safe_json_serialize(False) is False


def test_safe_json_dict():
    """dict 递归处理。"""
    data = {"a": 1, "b": "two", "c": None}
    result = _safe_json_serialize(data)
    assert result == data
    # 嵌套 dict
    assert _safe_json_serialize({"nested": {"deep": 42}}) == {"nested": {"deep": 42}}


def test_safe_json_list():
    """list/tuple/set 递归处理。"""
    assert _safe_json_serialize([1, 2, 3]) == [1, 2, 3]
    assert _safe_json_serialize((1, 2)) == [1, 2]
    assert sorted(_safe_json_serialize({1, 2})) == [1, 2]


def test_safe_json_exception():
    """Exception → {"type": ..., "message": ...}。"""
    exc = ValueError("something went wrong")
    result = _safe_json_serialize(exc)
    assert result["type"] == "ValueError"
    assert result["message"] == "something went wrong"


def test_safe_json_nested_exception():
    """嵌套在 dict 中的 Exception。"""
    data = {"error": RuntimeError("boom")}
    result = _safe_json_serialize(data)
    assert result["error"]["type"] == "RuntimeError"
    assert result["error"]["message"] == "boom"


def test_safe_json_circular_ref():
    """循环引用 → "<circular_ref>"。"""
    a: dict = {"name": "A"}
    b: dict = {"name": "B", "partner": a}
    a["partner"] = b
    result = _safe_json_serialize(a)
    assert result["name"] == "A"
    assert result["partner"]["name"] == "B"
    # a → b → a 的循环引用应被截断
    assert result["partner"]["partner"] == "<circular_ref>"


def test_safe_json_self_ref():
    """自引用 dict → "<circular_ref>"。"""
    d: dict = {"key": "value"}
    d["self"] = d
    result = _safe_json_serialize(d)
    assert result["key"] == "value"
    assert result["self"] == "<circular_ref>"


def test_safe_json_unknown_object():
    """未知对象 → {"type": ..., "repr": ...}。"""
    class Foo:
        def __repr__(self):
            return "Foo(bar=123)"
    result = _safe_json_serialize(Foo())
    assert result["type"] == "Foo"
    assert "Foo(bar=123)" in result["repr"]


def test_safe_json_uia_control():
    """UIA 控件对象 → 只保留安全字段。"""
    class FakeControl:
        __module__ = "uiautomation"
        Name = "搜索"
        ClassName = "Edit"
        ControlTypeName = "EditControl"
        class BoundingRectangle:
            left = 100
            top = 200
            right = 300
            bottom = 250

    result = _safe_json_serialize(FakeControl())
    assert result["_uia_control"] is True
    assert result["name"] == "搜索"
    assert result["classname"] == "Edit"
    assert result["controltypename"] == "EditControl"
    assert result["bounding_rectangle"]["left"] == 100
    assert result["bounding_rectangle"]["top"] == 200


def test_safe_json_uia_control_exception_on_attr():
    """UIA 控件读取属性异常时不崩溃。"""
    class BrokenControl:
        __module__ = "uiautomation"
        @property
        def Name(self):
            raise RuntimeError("broken")
        ClassName = "Edit"
        ControlTypeName = "EditControl"

    result = _safe_json_serialize(BrokenControl())
    assert result["name"] is None  # 异常时填 None


def test_safe_json_depth_limit():
    """depth 超限时截断为字符串。"""
    deep = {"level": 0}
    current = deep
    for i in range(1, 10):
        current["child"] = {"level": i}
        current = current["child"]
    result = _safe_json_serialize(deep)
    # 最深层应被截断为字符串而非继续递归
    assert isinstance(result, dict)
    # 验证整体可 JSON 序列化
    json_str = json.dumps(result, ensure_ascii=False)
    assert isinstance(json_str, str)


def test_safe_json_numpy_scalar():
    """numpy 标量转 Python 原生类型。"""
    try:
        import numpy as np
    except ImportError:
        return  # 无 numpy 则跳过
    assert _safe_json_serialize(np.int32(42)) == 42
    assert _safe_json_serialize(np.float64(3.14)) == 3.14
    assert _safe_json_serialize(np.bool_(True)) is True


def test_safe_json_numpy_ndarray():
    """numpy ndarray 转嵌套 list。"""
    try:
        import numpy as np
    except ImportError:
        return
    arr = np.array([1, 2, 3])
    result = _safe_json_serialize(arr)
    assert result == [1, 2, 3]


def test_safe_json_overall_serializable():
    """复杂混合结构整体可 json.dumps。"""
    a: dict = {"x": 1}
    b: dict = {"y": 2, "ref": a}
    a["ref"] = b
    data = {
        "primitives": [None, True, 42, "hello"],
        "exception": ValueError("oops"),
        "circular": a,
        "nested": {"deep": {"deeper": {"deepest": "end"}}},
        "unknown": object(),
    }
    result = _safe_json_serialize(data)
    json_str = json.dumps(result, ensure_ascii=False)
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["exception"]["type"] == "ValueError"
    assert parsed["circular"]["ref"]["ref"] == "<circular_ref>"


# ========== 2. Debug 端点测试 ==========

app = create_local_agent_app(host="127.0.0.1", port=19000, server_url="http://test:9000")
client = TestClient(app)


@patch("app.local_agent_main.run_search_box_debug")
def test_search_debug_exception_returns_200(mock_debug):
    """search-debug 内部异常时返回 200 + success=false，不抛 500。"""
    mock_debug.side_effect = RuntimeError("search crashed")
    resp = client.post("/agent/wechat/search-debug", json={"nickname": "Aw3"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "search_debug_exception"
    assert "search crashed" in data["message"]


@patch("app.local_agent_main.run_search_box_debug")
def test_search_debug_returns_non_serializable(mock_debug):
    """search-debug 返回含不可序列化对象时仍返回 200。"""
    class UiaLike:
        __module__ = "uiautomation"
        Name = "搜索"
        ClassName = "Edit"
        ControlTypeName = "EditControl"

    # 构造含 UIA 对象和循环引用的返回值
    circular: dict = {"a": 1}
    circular["self"] = circular
    mock_debug.return_value = {
        "success": True,
        "focus_control": UiaLike(),
        "circular": circular,
        "error": ValueError("test error"),
    }
    resp = client.post("/agent/wechat/search-debug", json={"nickname": "Aw3"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # UIA 对象被转为安全字段
    assert data["focus_control"]["_uia_control"] is True
    # 循环引用被截断
    assert data["circular"]["self"] == "<circular_ref>"
    # Exception 被安全处理
    assert data["error"]["type"] == "ValueError"


@patch("app.local_agent_main.run_search_result_debug")
def test_search_result_debug_exception_returns_200(mock_debug):
    """search-result-debug 内部异常时返回 200 + success=false。"""
    mock_debug.side_effect = RuntimeError("result debug crashed")
    resp = client.post("/agent/wechat/search-result-debug", json={"nickname": "Aw3"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "search_result_debug_exception"


@patch("app.local_agent_main.run_search_result_debug")
def test_search_result_debug_non_serializable(mock_debug):
    """search-result-debug 返回含不可序列化对象时仍返回 200。"""
    mock_debug.return_value = {
        "success": True,
        "search_focus": {"control": object()},
    }
    resp = client.post("/agent/wechat/search-result-debug", json={"nickname": "Aw3"})
    assert resp.status_code == 200
    # object() 被转为 {"type": ..., "repr": ...}
    data = resp.json()
    assert data["success"] is True
    control = data["search_focus"]["control"]
    assert "type" in control
    assert "repr" in control


# ========== 3. 主链路不受影响 ==========


def test_poll_and_execute_still_works():
    """search-debug 修改不影响 poll-and-execute。"""
    # 无 server_url 的 client
    app_no_server = create_local_agent_app(host="127.0.0.1", port=19000, server_url=None)
    client_no_server = TestClient(app_no_server)
    resp = client_no_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_url_not_configured"


def test_poll_and_detect_still_works():
    """search-debug 修改不影响 poll-and-detect。"""
    app_no_server = create_local_agent_app(host="127.0.0.1", port=19000, server_url=None)
    client_no_server = TestClient(app_no_server)
    resp = client_no_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_url_not_configured"
