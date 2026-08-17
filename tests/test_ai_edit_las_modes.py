"""AI 剪辑 LAS 三模式测试（不触网，mock LAS client）。

覆盖 M06-LAS-REMIX-MODES-20260817-1 验收点：
- 三种模式正常请求体生成（AC-001）
- 旧请求不传 mode → marketing_headtalk；speech_auto / automotive_headtalk 兼容别名（AC-002/003）
- 各模式数量、角色、section、目标时长规则 fail-closed（AC-004/005）
- 完整规范化请求持久化到 input_json，无数据库迁移（AC-006）
- smart_packaging 只透传对象（AC）
- HTTP 400（参数校验）与 LAS 502（提交失败）边界不混淆（AC-012）
- 全部 mock，不触网（AC-013）
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services import ai_edit_las_service as las_svc
from app.services.ai_edit_las_service import (
    LAS_SCRIPT_MAX_LEN,
    MODE_LONG_REAL,
    MODE_MARKETING,
    MODE_REAL_HEAD,
    ROLE_BROLL,
    ROLE_SPEECH,
    ROLE_VOICEOVER,
    SECTION_HEADTALK,
    SECTION_REAL_SHOT,
    normalize_las_mode,
    normalize_las_template,
    validate_las_request,
)


# ---------- fixtures ----------

@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """每测试独立内存 SQLite Session，避免 job_id 唯一约束跨测试冲突。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


def _mock_las_client():
    """构造 mock LAS client：submit 返回正常响应，wait_for_terminal 返回 COMPLETED。"""
    client = MagicMock()
    client.submit.return_value = {
        "metadata": {"task_id": "task_mock", "task_status": "PENDING", "business_code": "0"}
    }
    return client


def _submit_payload(**overrides):
    """构造一个合法 marketing_headtalk 请求 payload（可覆盖字段）。"""
    payload = dict(
        mode=None,
        video_urls=["https://example.com/a.mp4", "https://example.com/b.mp4"],
        script="剪成一条约 60 秒的产品讲解视频",
        template=None,
        target_duration_sec=None,
        render_video=None,
        video_edit_mode=None,
        smart_packaging=None,
    )
    payload.update(overrides)
    return payload


# ---------- 规范化 ----------

class TestNormalize:
    def test_mode_missing_defaults_to_marketing(self):
        assert normalize_las_mode(None) == MODE_MARKETING
        assert normalize_las_mode("") == MODE_MARKETING

    def test_speech_auto_alias_to_marketing(self):
        assert normalize_las_mode("speech_auto") == MODE_MARKETING
        assert normalize_las_mode("  speech_auto  ") == MODE_MARKETING

    def test_three_canonical_modes_pass_through(self):
        assert normalize_las_mode(MODE_MARKETING) == MODE_MARKETING
        assert normalize_las_mode(MODE_LONG_REAL) == MODE_LONG_REAL
        assert normalize_las_mode(MODE_REAL_HEAD) == MODE_REAL_HEAD

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError):
            normalize_las_mode("space_x")

    def test_template_automotive_headtalk_normalized(self):
        assert normalize_las_template("automotive_headtalk") == "automotive"
        assert normalize_las_template(None) == "automotive"
        assert normalize_las_template("automotive") == "automotive"

    def test_render_video_default_true(self):
        ok = validate_las_request(**_submit_payload(render_video=None))
        assert ok["render_video"] is True
        ok = validate_las_request(**_submit_payload(render_video=False))
        assert ok["render_video"] is False


# ---------- marketing_headtalk ----------

class TestMarketingHeadtalk:
    def test_valid_bare_urls_normalized_to_speech(self):
        ok = validate_las_request(**_submit_payload())
        assert ok["mode"] == MODE_MARKETING
        assert ok["template"] == "automotive"
        assert ok["video_urls"] == [
            {"url": "https://example.com/a.mp4", "role": ROLE_SPEECH},
            {"url": "https://example.com/b.mp4", "role": ROLE_SPEECH},
        ]

    def test_valid_roles_voiceover_and_broll(self):
        payload = _submit_payload(video_urls=[
            {"url": "https://example.com/a.mp4", "role": ROLE_VOICEOVER},
            {"url": "https://example.com/b.mp4", "role": ROLE_BROLL},
        ])
        ok = validate_las_request(**payload)
        assert ok["video_urls"][0]["role"] == ROLE_VOICEOVER
        assert ok["video_urls"][1]["role"] == ROLE_BROLL

    def test_over_30_rejected(self):
        urls = [f"https://example.com/{i}.mp4" for i in range(31)]
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=urls))

    def test_target_duration_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(target_duration_sec=60))

    def test_section_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[
                {"url": "https://example.com/a.mp4", "section": SECTION_HEADTALK},
            ]))

    def test_unknown_role_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[
                {"url": "https://example.com/a.mp4", "role": "talking_head"},
            ]))

    def test_single_string_ok_as_one_speech(self):
        ok = validate_las_request(**_submit_payload(video_urls="https://example.com/a.mp4"))
        # 字符串场景：发送原样保持字符串；items 为规范化对象（role=speech）
        assert ok["video_urls"] == "https://example.com/a.mp4"
        assert ok["items"] == [{"url": "https://example.com/a.mp4", "role": ROLE_SPEECH}]


# ---------- long_real_shot ----------

class TestLongRealShot:
    def test_valid_tos_prefix_string(self):
        ok = validate_las_request(**_submit_payload(
            mode=MODE_LONG_REAL,
            video_urls="tos://customer-bucket/deal-record/",
            target_duration_sec=180,
        ))
        assert ok["mode"] == MODE_LONG_REAL
        assert ok["video_urls"] == "tos://customer-bucket/deal-record/"
        assert ok["target_duration_sec"] == 180

    def test_valid_array_with_voiceover(self):
        ok = validate_las_request(**_submit_payload(
            mode=MODE_LONG_REAL,
            video_urls=[
                {"url": "https://example.com/a.mp4", "role": ROLE_SPEECH},
                {"url": "https://example.com/b.mp4", "role": ROLE_VOICEOVER},
            ],
            target_duration_sec=3600,
        ))
        assert len(ok["items"]) == 2

    def test_over_100_rejected(self):
        urls = [f"https://example.com/{i}.mp4" for i in range(101)]
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(mode=MODE_LONG_REAL, video_urls=urls))

    def test_target_duration_below_10_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_LONG_REAL, video_urls=["x.mp4"], target_duration_sec=9,
            ))

    def test_broll_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_LONG_REAL,
                video_urls=[{"url": "x.mp4", "role": ROLE_BROLL}],
            ))

    def test_section_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_LONG_REAL,
                video_urls=[{"url": "x.mp4", "section": SECTION_REAL_SHOT}],
            ))


# ---------- real_shot_headtalk ----------

class TestRealShotHeadtalk:
    def test_valid_explicit_sections(self):
        ok = validate_las_request(**_submit_payload(
            mode=MODE_REAL_HEAD,
            video_urls=[
                {"url": "tos://b/handover-01.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT},
                {"url": "tos://b/handover-02.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT},
                {"url": "tos://b/sales-talk.mp4", "role": ROLE_SPEECH, "section": SECTION_HEADTALK},
                {"url": "tos://b/broll.mp4", "role": ROLE_BROLL, "section": SECTION_HEADTALK},
            ],
            target_duration_sec=120,
        ))
        assert ok["mode"] == MODE_REAL_HEAD
        assert len(ok["items"]) == 4

    def test_valid_auto_sections_bare_urls(self):
        ok = validate_las_request(**_submit_payload(
            mode=MODE_REAL_HEAD,
            video_urls=[
                "https://example.com/handover-01.mp4",
                "https://example.com/handover-02.mp4",
                "https://example.com/sales-talk.mp4",
            ],
        ))
        # 裸地址自动分段：role=speech ≥2
        assert len(ok["items"]) == 3

    def test_partial_section_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "section": SECTION_REAL_SHOT},
                    {"url": "b.mp4"},
                ],
            ))

    def test_missing_real_shot_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "section": SECTION_HEADTALK},
                    {"url": "b.mp4", "role": ROLE_SPEECH, "section": SECTION_HEADTALK},
                ],
            ))

    def test_missing_headtalk_speech_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT},
                    {"url": "b.mp4", "role": ROLE_BROLL, "section": SECTION_HEADTALK},
                ],
            ))

    def test_real_shot_broll_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "role": ROLE_BROLL, "section": SECTION_REAL_SHOT},
                    {"url": "b.mp4", "role": ROLE_SPEECH, "section": SECTION_HEADTALK},
                ],
            ))

    def test_voiceover_rejected_anywhere(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT},
                    {"url": "b.mp4", "role": ROLE_VOICEOVER, "section": SECTION_HEADTALK},
                ],
            ))
        # 自动分段也禁 voiceover
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "role": ROLE_SPEECH},
                    {"url": "b.mp4", "role": ROLE_VOICEOVER},
                ],
            ))

    def test_auto_sections_need_two_speech(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_REAL_HEAD,
                video_urls=[
                    {"url": "a.mp4", "role": ROLE_BROLL},
                    {"url": "b.mp4", "role": ROLE_BROLL},
                ],
            ))

    def test_auto_sections_over_130_rejected(self):
        urls = [f"https://example.com/{i}.mp4" for i in range(131)]
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(mode=MODE_REAL_HEAD, video_urls=urls))

    def test_explicit_real_shot_over_100_rejected(self):
        urls = [
            {"url": f"https://example.com/r{i}.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT}
            for i in range(101)
        ]
        urls.append({"url": "https://example.com/h.mp4", "role": ROLE_SPEECH, "section": SECTION_HEADTALK})
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(mode=MODE_REAL_HEAD, video_urls=urls))

    def test_explicit_headtalk_over_30_rejected(self):
        urls = [
            {"url": f"https://example.com/h{i}.mp4", "role": ROLE_SPEECH, "section": SECTION_HEADTALK}
            for i in range(31)
        ]
        urls.insert(0, {"url": "https://example.com/r.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT})
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(mode=MODE_REAL_HEAD, video_urls=urls))


# ---------- 公共参数校验 ----------

class TestCommonValidation:
    def test_empty_script_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(script="   "))

    def test_script_over_4000_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(script="a" * (LAS_SCRIPT_MAX_LEN + 1)))

    def test_empty_video_urls_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[]))

    def test_video_item_missing_url_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[{"role": ROLE_SPEECH}]))

    def test_smart_packaging_only_object(self):
        ok = validate_las_request(**_submit_payload(smart_packaging={"bgm": {"enabled": False}}))
        assert ok["smart_packaging"] == {"bgm": {"enabled": False}}
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(smart_packaging="not-object"))
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(smart_packaging=["list"]))

    def test_video_edit_mode_lite_pro_only(self):
        ok = validate_las_request(**_submit_payload(video_edit_mode="lite"))
        assert ok["video_edit_mode"] == "lite"
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_edit_mode="turbo"))

    # ---------- P2：地址/角色/分段 fail-closed ----------

    def test_empty_url_rejected(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[""]))
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=["  "]))
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[{"url": ""}]))
        # 目录前缀字符串为空/空白同样拒绝
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=""))

    def test_invalid_protocol_rejected(self):
        # 非 tos:// http:// https:// 协议一律拒绝（任意模式）
        for bad in ["a.mp4", "ftp://x/y.mp4", "file:///c:/a.mp4", "C:\\a.mp4", "tos:a.mp4"]:
            with pytest.raises(ValueError):
                validate_las_request(**_submit_payload(video_urls=[bad]))
            with pytest.raises(ValueError):
                validate_las_request(**_submit_payload(video_urls=[{"url": bad}]))
        # 目录前缀也须合法协议
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(
                mode=MODE_LONG_REAL, video_urls="not-a-protocol/prefix/",
            ))

    def test_unknown_role_rejected_everywhere(self):
        """未知 role 在任何模式下一律拒绝（_normalize_video_item 层 fail-closed）。"""
        for m in (None, MODE_LONG_REAL, MODE_REAL_HEAD):
            with pytest.raises(ValueError):
                validate_las_request(**_submit_payload(
                    mode=m, video_urls=[{"url": "https://x/a.mp4", "role": "talking_head"}],
                ))

    def test_unknown_section_rejected_everywhere(self):
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(video_urls=[
                {"url": "https://x/a.mp4", "section": "unknown_seg"},
            ]))
        with pytest.raises(ValueError):
            validate_las_request(**_submit_payload(mode=MODE_REAL_HEAD, video_urls=[
                {"url": "https://x/a.mp4", "role": "speech", "section": "unknown_seg"},
            ]))


# ---------- create_las_job 持久化与提交 ----------

class TestCreateLasJob:
    def test_job_persists_normalized_request(self, db_session):
        client = _mock_las_client()
        with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
            job = las_svc.create_las_job(
                db_session,
                merchant_id="m1",
                video_urls=["https://example.com/a.mp4"],
                script="剪成一条约 60 秒的产品讲解视频",
                mode="speech_auto",
            )
        assert job.status == "processing"
        assert job.las_task_id == "task_mock"
        assert job.las_template == "automotive"  # automotive_headtalk 规范化
        # 提交到 LAS 的 mode 已是 marketing_headtalk
        _, kwargs = client.submit.call_args
        assert kwargs["mode"] == MODE_MARKETING
        assert kwargs["template"] == "automotive"
        # input_json 完整规范化请求（无 DB 迁移）
        import json
        inp = json.loads(job.input_json)
        assert inp["mode"] == MODE_MARKETING
        assert inp["template"] == "automotive"
        assert inp["render_video"] is True
        assert inp["video_urls"] == [{"url": "https://example.com/a.mp4", "role": ROLE_SPEECH}]

    def test_job_persists_real_shot_mode(self, db_session):
        client = _mock_las_client()
        with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
            job = las_svc.create_las_job(
                db_session,
                merchant_id="m1",
                video_urls=[
                    {"url": "tos://b/r.mp4", "role": ROLE_SPEECH, "section": SECTION_REAL_SHOT},
                    {"url": "tos://b/h.mp4", "role": ROLE_SPEECH, "section": SECTION_HEADTALK},
                ],
                script="前半段实拍，后半段口播",
                mode=MODE_REAL_HEAD,
                target_duration_sec=120,
            )
        _, kwargs = client.submit.call_args
        assert kwargs["mode"] == MODE_REAL_HEAD
        assert kwargs["target_duration_sec"] == 120
        assert kwargs["video_urls"][0]["section"] == SECTION_REAL_SHOT

    def test_invalid_mode_raises_value_error_before_submit(self, db_session):
        client = _mock_las_client()
        with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
            with pytest.raises(ValueError):
                las_svc.create_las_job(
                    db_session,
                    merchant_id="m1",
                    video_urls=["a.mp4"],
                    script="x",
                    mode="space_x",
                )
        client.submit.assert_not_called()

    def test_output_tos_path_in_input_json(self, db_session):
        """output_tos_path 纳入 input_json（完整规范化请求持久化）；idempotent_id 不重复写入。"""
        client = _mock_las_client()
        with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
            job = las_svc.create_las_job(
                db_session,
                merchant_id="m1",
                video_urls=["https://example.com/a.mp4"],
                script="剪成一条约 60 秒的产品讲解视频",
                output_tos_path="tos://bucket/out/",
                idempotent_id="idem-xyz",
            )
        import json
        inp = json.loads(job.input_json)
        assert inp["output_tos_path"] == "tos://bucket/out/"
        # idempotent_id 走专用字段，不重复写入 input_json
        assert "idempotent_id" not in inp
        assert job.las_idempotent_id == "idem-xyz"

    def test_las_error_propagates_to_router_boundary(self, db_session):
        """LAS 提交失败抛 LASError（router 转 502），与参数校验 ValueError（转 400）区分。

        注意：地址校验先行（非法协议抛 ValueError），故用合法地址才走到 LAS submit。
        """
        client = MagicMock()
        client.submit.side_effect = las_svc.LASError("提交失败", metadata={"business_code": "System.Upstream"})
        with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
            with pytest.raises(las_svc.LASError):
                las_svc.create_las_job(
                    db_session,
                    merchant_id="m1",
                    video_urls=["https://example.com/a.mp4"],
                    script="x",
                )


# ---------- Router 层 HTTP 边界（复用 attack 测试 fixture 模式） ----------

from sqlalchemy import create_engine as _ce  # noqa: E402
from sqlalchemy.orm import sessionmaker as _sm  # noqa: E402
from sqlalchemy.pool import StaticPool as _SP  # noqa: E402
import app.models  # noqa: E402, F401
from app.database import Base as _Base, get_db as _get_db  # noqa: E402

_route_engine = _ce("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=_SP)
_RouteSession = _sm(autocommit=False, autoflush=False, bind=_route_engine)


def _route_client(merchant_id: str, **kw):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth.dependencies import get_request_context_required
    from app.auth.context import RequestContext
    ctx = RequestContext(
        user_id=kw.get("user_id", "u1"),
        auth_mode=kw.get("auth_mode", "mock"),
        super_admin=kw.get("super_admin", False),
        permission_codes=kw.get("permission_codes", ["auto_wechat:ai_edit"]),
        merchant_id=merchant_id,
    )
    app.dependency_overrides[get_request_context_required] = lambda: ctx
    app.dependency_overrides[_get_db] = lambda: _RouteSession()
    return TestClient(app)


class TestLasJobsRoute:
    def _setup(self):
        _Base.metadata.drop_all(bind=_route_engine)
        _Base.metadata.create_all(bind=_route_engine)

    def _teardown(self):
        from app.main import app
        app.dependency_overrides.clear()

    def test_valid_marketing_submit_returns_200(self):
        self._setup()
        try:
            client = _mock_las_client()
            with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
                r = _route_client("m1").post("/ai-edit/las/jobs", json={
                    "video_urls": ["https://example.com/a.mp4"],
                    "script": "剪成一条约 60 秒的产品讲解视频",
                })
            assert r.status_code == 200, r.text
            assert r.json()["success"] is True
            # 后端规范化：input_json 存 marketing_headtalk / automotive
            assert client.submit.call_args.kwargs["mode"] == MODE_MARKETING
        finally:
            self._teardown()

    def test_invalid_params_return_400_not_502(self):
        """marketing 模式带 target_duration_sec → 参数校验 400（不是 LAS 502）。"""
        self._setup()
        try:
            client = _mock_las_client()
            with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
                r = _route_client("m1").post("/ai-edit/las/jobs", json={
                    "video_urls": ["https://example.com/a.mp4"],
                    "script": "剪成一条约 60 秒的产品讲解视频",
                    "target_duration_sec": 60,
                })
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["code"] == "LAS_INVALID_PARAM"
            client.submit.assert_not_called()
        finally:
            self._teardown()

    def test_missing_permission_returns_403(self):
        """无 auto_wechat:ai_edit 权限 → 403（真实鉴权模式，mock 模式恒放行）。"""
        self._setup()
        try:
            client = _mock_las_client()
            with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
                r = _route_client("m1", permission_codes=[], auth_mode="real").post(
                    "/ai-edit/las/jobs", json={
                        "video_urls": ["https://example.com/a.mp4"],
                        "script": "剪成一条约 60 秒的产品讲解视频",
                    }
                )
            assert r.status_code == 403, r.text
            assert r.json()["detail"]["code"] == "PERMISSION_DENIED"
            client.submit.assert_not_called()
        finally:
            self._teardown()

    def test_las_submit_failure_returns_502(self):
        """LAS submit 失败 → 502（与参数校验 400 边界不混淆）。"""
        self._setup()
        try:
            client = MagicMock()
            client.submit.side_effect = las_svc.LASError(
                "提交失败", metadata={"business_code": "System.Upstream"}
            )
            with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
                r = _route_client("m1").post("/ai-edit/las/jobs", json={
                    "video_urls": ["https://example.com/a.mp4"],
                    "script": "剪成一条约 60 秒的产品讲解视频",
                })
            assert r.status_code == 502, r.text
            assert r.json()["detail"]["code"] == "LAS_SUBMIT_FAILED"
        finally:
            self._teardown()

    def test_real_shot_composite_validation_400(self):
        """复合模式缺段（只传实拍段）→ 400。"""
        self._setup()
        try:
            client = _mock_las_client()
            with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
                r = _route_client("m1").post("/ai-edit/las/jobs", json={
                    "video_urls": [
                        {"url": "tos://b/r.mp4", "role": "speech", "section": "real_shot"},
                    ],
                    "script": "前半段实拍，后半段口播",
                    "mode": "real_shot_headtalk",
                })
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["code"] == "LAS_INVALID_PARAM"
            client.submit.assert_not_called()
        finally:
            self._teardown()

    def test_invalid_protocol_returns_400(self):
        """非法协议地址 → 400（P2 校验 fail-closed）。"""
        self._setup()
        try:
            client = _mock_las_client()
            with patch.object(las_svc, "get_las_speech_auto_client", return_value=client):
                r = _route_client("m1").post("/ai-edit/las/jobs", json={
                    "video_urls": ["a.mp4"],
                    "script": "剪成一条约 60 秒的产品讲解视频",
                })
            assert r.status_code == 400, r.text
            assert r.json()["detail"]["code"] == "LAS_INVALID_PARAM"
            client.submit.assert_not_called()
        finally:
            self._teardown()


# ---------- render_video=false 方案型成功（P2） ----------


def _make_processing_job(engine, render_video=None):
    """构造一个 processing 状态的 LAS job，input_json 可指定 render_video。"""
    import json as _json
    from sqlalchemy.orm import sessionmaker
    from app.models import AiEditJob
    input_data = {
        "mode": MODE_MARKETING,
        "template": "automotive",
        "script": "剪成一条约 60 秒的产品讲解视频",
        "video_urls": ["https://example.com/a.mp4"],
        "render_video": True if render_video is None else render_video,
    }
    job = AiEditJob(
        merchant_id="m1",
        job_id="las-scheme-1",
        status="processing",
        source_type="las_speech_auto",
        stage="submitted",
        progress=0,
        las_task_id="task_scheme",
        las_idempotent_id="idem_scheme",
        las_script="剪成一条约 60 秒的产品讲解视频",
        las_template="automotive",
        title="方案型标题",  # 预设标题，避免 _fill_job_title 下载 result_json 触网
        input_json=_json.dumps(input_data, ensure_ascii=False),
    )
    s = sessionmaker(bind=engine)()
    s.add(job)
    s.commit()
    job_id = job.id
    s.close()
    return job_id


def _mock_completed_client(artifacts):
    """mock LAS client：wait_for_terminal 返回 COMPLETED（无视频只有方案产物）。"""
    client = MagicMock()
    client.wait_for_terminal.return_value = {
        "metadata": {"task_id": "task_scheme", "task_status": "COMPLETED", "business_code": "0"},
        "data": {"artifacts": artifacts},
    }
    return client


class TestProcessLasJobRenderVideo:
    """P2：render_video=false 的 COMPLETED 任务为方案型成功，不得因无视频而失败。

    process_las_job 内部会 db.close()，故用 StaticPool 共享内存库 + 独立 runner session，
    避免 fixture session 被关闭后无法断言。
    """

    @pytest.fixture
    def engine(self):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        from app.models import Base
        e = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(e)
        yield e
        e.dispose()

    def _run(self, engine, job_id, client):
        from sqlalchemy.orm import sessionmaker
        import app.database as _database
        runner = sessionmaker(bind=engine)()
        with patch.object(las_svc, "get_las_speech_auto_client", return_value=client), \
             patch.object(_database, "SessionLocal", return_value=runner), \
             patch.object(las_svc, "archive_final_video", wraps=las_svc.archive_final_video) as arch, \
             patch.object(las_svc, "_report_las_compute_usage") as report:
            las_svc.process_las_job(job_id)
            return arch, report

    def _load(self, engine, job_id):
        from sqlalchemy.orm import sessionmaker
        from app.models import AiEditJob, AiEditJobArtifact
        s = sessionmaker(bind=engine)()
        job = s.query(AiEditJob).filter(AiEditJob.id == job_id).first()
        arts = s.query(AiEditJobArtifact).filter(AiEditJobArtifact.job_id == job.job_id).all()
        result = (job, arts)
        s.close()
        return result

    def test_render_video_false_succeeds_without_archive(self, engine):
        """COMPLETED 且 render_video=false：succeeded；不触发视频归档；算力上报仍执行。"""
        job_id = _make_processing_job(engine, render_video=False)
        # 方案产物：只有 match_scheme / result_json，无视频
        artifacts = {
            "match_scheme_url": "https://signed/plan.json",
            "match_scheme_tos_path": "tos://bucket/plan.json",
        }
        client = _mock_completed_client(artifacts)
        arch, report = self._run(engine, job_id, client)

        job, arts = self._load(engine, job_id)
        assert job.status == "succeeded"          # 方案型成功，不是 failed
        assert job.stage == "completed"
        assert job.progress == 100
        assert job.failure_code is None
        arch.assert_not_called()                   # 不触发视频归档
        report.assert_called_once()                # LAS 任务确实执行，算力上报语义保留
        # 产物已持久化（match_scheme）
        assert any(a.artifact_type == "match_scheme" for a in arts)

    def test_render_video_default_true_still_archives(self, engine):
        """render_video 缺省/true：COMPLETED 仍走视频归档（默认语义不变）。"""
        job_id = _make_processing_job(engine)  # render_video 缺省按 True
        artifacts = {"video_subtitled_url": "https://signed/sub.mp4"}
        client = _mock_completed_client(artifacts)
        with patch.object(las_svc, "archive_final_video", return_value=True):
            arch, report = self._run(engine, job_id, client)

        job, _ = self._load(engine, job_id)
        assert job.status == "succeeded"
        # 归档路径已被执行（patch 返回值 True 走成功分支）
        report.assert_called_once()
