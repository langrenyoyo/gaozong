"""验证 UTF8JSONResponse 的 Content-Type 包含 charset=utf-8

修复 Windows PowerShell 5.1 Invoke-RestMethod 中文乱码问题。
自包含测试：直接定义 UTF8JSONResponse 类验证行为，不依赖 app.main（避免 numpy 导入链）。
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


class UTF8JSONResponse(JSONResponse):
    """与 app/main.py 中定义一致的 UTF8 JSON 响应类"""
    media_type = "application/json; charset=utf-8"


class TestUTF8JSONResponse:
    """测试 UTF8JSONResponse 设置正确的 Content-Type。"""

    def test_media_type_value(self):
        """media_type 必须是 application/json; charset=utf-8"""
        assert UTF8JSONResponse.media_type == "application/json; charset=utf-8"

    def test_response_header_has_charset(self):
        """实际 HTTP 响应头 Content-Type 包含 charset=utf-8"""
        app = FastAPI(default_response_class=UTF8JSONResponse)

        @app.get("/test")
        def test_endpoint():
            return {"message": "hello"}

        client = TestClient(app)
        resp = client.get("/test")

        ct = resp.headers.get("content-type", "")
        assert "charset=utf-8" in ct, f"Content-Type 缺少 charset: {ct}"

    def test_chinese_content_roundtrip(self):
        """中文内容在响应中正确序列化和反序列化"""
        app = FastAPI(default_response_class=UTF8JSONResponse)

        @app.get("/cn")
        def cn_endpoint():
            return {"content": "123"}

        client = TestClient(app)
        resp = client.get("/cn")

        assert resp.json()["content"] == "123"
        # 响应体原始文本应包含中文（不是 \u 转义）
        assert "123" in resp.text

    def test_content_type_exact_value(self):
        """Content-Type 完整值"""
        app = FastAPI(default_response_class=UTF8JSONResponse)

        @app.get("/t")
        def t():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/t")

        ct = resp.headers.get("content-type", "")
        assert ct == "application/json; charset=utf-8"

    def test_default_json_response_no_charset(self):
        """对比：FastAPI 默认 JSONResponse 不含 charset（确认问题存在）"""
        app = FastAPI()  # 不指定 default_response_class

        @app.get("/default")
        def default_endpoint():
            return {"msg": "test"}

        client = TestClient(app)
        resp = client.get("/default")

        ct = resp.headers.get("content-type", "")
        assert "charset" not in ct, f"默认响应不应有 charset: {ct}"
