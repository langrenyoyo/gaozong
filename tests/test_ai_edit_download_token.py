"""AI剪辑短期下载 token 安全闭环测试（非平凡安全逻辑的最小可运行 check）。

覆盖：
1. 正常生成 → 校验通过
2. 跨 job_id / 跨 merchant_id 被拒
3. 篡改签名被拒
4. 过期 token 被拒
5. secret 缺失时 fail-closed：generate 抛 RuntimeError，verify 返回 False（不 500）

约定：模块顶层零业务 import，业务模块在测试函数内延迟 import（避免收集阶段触发 app.config）。
"""
import base64
import hashlib
import hmac

import pytest


def _import_las_svc(monkeypatch, secret: str | None):
    """延迟 import 并控制 DY_SECRET_KEY（运行时 patch config 模块属性）。"""
    from app.services import ai_edit_las_service as las_svc

    monkeypatch.setattr(las_svc.config, "DY_SECRET_KEY", secret or "", raising=False)
    return las_svc


def test_token_roundtrip_ok(monkeypatch):
    las_svc = _import_las_svc(monkeypatch, "test-secret-1234")
    token = las_svc.generate_download_token(job_id=42, merchant_id="m_a")
    assert las_svc.verify_download_token(token, job_id=42, merchant_id="m_a") is True


def test_token_cross_job_rejected(monkeypatch):
    las_svc = _import_las_svc(monkeypatch, "test-secret-1234")
    token = las_svc.generate_download_token(job_id=42, merchant_id="m_a")
    # 换 job_id：被拒
    assert las_svc.verify_download_token(token, job_id=999, merchant_id="m_a") is False


def test_token_cross_merchant_rejected(monkeypatch):
    las_svc = _import_las_svc(monkeypatch, "test-secret-1234")
    token = las_svc.generate_download_token(job_id=42, merchant_id="m_a")
    # 换 merchant_id：被拒（防跨商户下载）
    assert las_svc.verify_download_token(token, job_id=42, merchant_id="m_b") is False


def test_token_tampered_signature_rejected(monkeypatch):
    las_svc = _import_las_svc(monkeypatch, "test-secret-1234")
    token = las_svc.generate_download_token(job_id=42, merchant_id="m_a")
    # 篡改签名末位
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert las_svc.verify_download_token(tampered, job_id=42, merchant_id="m_a") is False


def test_token_expired_rejected(monkeypatch):
    las_svc = _import_las_svc(monkeypatch, "test-secret-1234")
    # 手造过期 token：exp=1000（早已过期）+ 正确签名
    payload = "42:m_a:1000"
    sig = hmac.new(b"test-secret-1234", payload.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(payload.encode()).decode() + "." + sig
    assert las_svc.verify_download_token(token, job_id=42, merchant_id="m_a") is False


def test_generate_fail_closed_when_secret_missing(monkeypatch):
    """DY_SECRET_KEY 未配置时，签发必须 fail-closed 抛错，绝不退化到硬编码公开值。"""
    las_svc = _import_las_svc(monkeypatch, None)
    with pytest.raises(RuntimeError):
        las_svc.generate_download_token(job_id=42, merchant_id="m_a")


def test_verify_fail_closed_when_secret_missing(monkeypatch):
    """secret 缺失时校验返回 False（安全拒绝下载，不抛 500）。"""
    las_svc = _import_las_svc(monkeypatch, "test-secret-1234")
    token = las_svc.generate_download_token(job_id=42, merchant_id="m_a")
    # 生成后清掉 secret，模拟配置丢失：校验应返回 False 而非抛错
    _import_las_svc(monkeypatch, None)
    assert las_svc.verify_download_token(token, job_id=42, merchant_id="m_a") is False
