"""企业微信第三方应用回调路由（P0 Probe，仅协议 transport）。

GET  = 后台保存回调 URL 时的验证：验签 + AES 解密 echostr + 校验 suite identity
       + 返回解密明文（纯文本，无 JSON/引号/换行/BOM）。
POST = 指令/数据回调：验签 + 解密 + 识别最小事件 + 安全 metadata 日志 + ACK "success"。

本路由不写数据库、不调用业务服务、不访问 Lead / Sales / WechatTask；
ACK 前禁止调用企微其它 API / RAG / LLM / 复杂 DB 查询（企业微信要求授权类事件
1000ms 内、一般回调 5s 内响应，否则可能重试）。

正式 callback business service / durable inbox 属后续 P1/P4，不在本 Probe 实现。
"""

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

from app import config
from app.integrations.wecom import crypto
from app.integrations.wecom.crypto import WeComCallbackError
from app.services import wecom_callback_service

logger = logging.getLogger("wecom_callback_router")

# 9000 内部路由不带 /api 前缀（项目惯例：nginx 剥离 /api/ 后转发到 9000）。
# 外部 endpoint 保持 /api/integrations/wecom/callback（任务书指定，由反代剥离 /api 匹配）。
router = APIRouter(prefix="/integrations/wecom", tags=["企业微信回调"])

# 指令类事件（receiveid 需 == suite_id）；数据类（template_card_event）按 ToUserName 解析 merchant
_COMMAND_INFO_TYPES = frozenset(
    {"suite_ticket", "create_auth", "change_auth", "cancel_auth"}
)


def _safe_timestamp() -> str:
    """仅用于日志的 UTC 时间戳（不依赖系统时区）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ticket_hash_prefix(ticket: str) -> str:
    """suite_ticket 脱敏指纹：SHA256 前 8 位。可验证"收到新 ticket"又不泄露明文。"""
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:8]


def _load_wecom_config() -> tuple[str, str, str]:
    """读取企微回调配置；任一缺失即 fail-closed（不 500、不泄露原因）。"""
    token = (config.WECOM_CALLBACK_TOKEN or "").strip()
    aes_key = (config.WECOM_CALLBACK_ENCODING_AES_KEY or "").strip()
    suite_id = (config.WECOM_SUITE_ID or "").strip()
    if not token or not aes_key or not suite_id:
        raise WeComCallbackError("config_missing")
    return token, aes_key, suite_id


def _fail_closed(exc: WeComCallbackError, stage: str) -> PlainTextResponse:
    """安全失败响应：日志只记 stage/result/error_code/timestamp；响应不含细节。"""
    logger.warning(
        "wecom_callback stage=%s result=failed error_code=%s ts=%s",
        stage,
        exc.code,
        _safe_timestamp(),
    )
    return PlainTextResponse("verification failed", status_code=400)


def _log_event_metadata(stage: str, envelope: dict) -> None:
    """安全记录 P0 evidence metadata：只记 event_type / suite_id / 脱敏指纹 / 时间。

    禁止：日志打印 SuiteTicket 明文、permanent_code、Token、AESKey、内部错误细节。
    """
    info_type = envelope.get("info_type") or "unknown"
    suite_id = envelope.get("suite_id") or "-"
    extra = envelope.get("extra") or {}
    ts = _safe_timestamp()
    if info_type == "suite_ticket" and extra.get("SuiteTicket"):
        logger.info(
            "wecom_callback stage=%s result=ok event_type=suite_ticket suite_id=%s ticket_hash=%s ts=%s",
            stage,
            suite_id,
            _ticket_hash_prefix(extra["SuiteTicket"]),
            ts,
        )
    elif info_type in ("create_auth", "change_auth", "cancel_auth"):
        # AuthCorpId 为加密 corpid（不可直接反解业务），仅作事件识别元数据
        logger.info(
            "wecom_callback stage=%s result=ok event_type=%s suite_id=%s auth_corp_id=%s ts=%s",
            stage,
            info_type,
            suite_id,
            extra.get("AuthCorpId") or "-",
            ts,
        )
    else:
        logger.info(
            "wecom_callback stage=%s result=ok event_type=%s suite_id=%s ts=%s",
            stage,
            info_type,
            suite_id,
            ts,
        )


@router.get("/callback", response_class=PlainTextResponse)
async def callback_verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
) -> PlainTextResponse:
    """企业微信后台保存回调 URL 时的 GET 验证（URL Verification）。

    要求：参数完整 → 验签（签名用 echostr 密文参与）→ AES 解密 → 原样返回解密明文
    （纯文本，无任何包装）。

    注意：企微 verifyURL 的 echostr 加密 receiveid 是 corpid（实测 wwaa...），不是
    suite_id（suite_ticket 推送才用 suite_id）；因此本场景协议上无法按 suite_id 校验
    （任务书：suite identity mismatch 仅在协议能够验证时校验）。来源可信由
    msg_signature 验签保证——只有持有 Token 的企微后台才能通过验签。
    """
    stage = "wecom.callback.get"
    try:
        token, aes_key, _suite_id = _load_wecom_config()
        if not crypto.verify_signature(token, timestamp, nonce, echostr, msg_signature):
            raise WeComCallbackError("signature_invalid")
        msg, _receiveid = crypto.decrypt_message(echostr, aes_key)
        try:
            plaintext = msg.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise WeComCallbackError("invalid_plaintext", detail=str(exc)) from exc
    except WeComCallbackError as exc:
        return _fail_closed(exc, stage)
    logger.info("wecom_callback stage=%s result=ok ts=%s", stage, _safe_timestamp())
    return PlainTextResponse(plaintext)


def _to_int(value) -> int | None:
    """事件 TimeStamp（秒）转 int；非法返回 None。"""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


@router.post("/callback", response_class=PlainTextResponse)
async def callback_receive(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
) -> PlainTextResponse:
    """企业微信指令/数据回调（P1 Durable Inbox）。

    验签 → AES 解密 → 指令类 receiveid==suite_id 校验（数据类按 ToUserName 解析 merchant）→
    解析 envelope → 事件落库（幂等）→ ACK "success"。
    签名/解密有效但未知事件 / 未知 corpid → 落库 IGNORED + ACK（§5.3 安全拒绝矩阵）。
    """
    stage = "wecom.callback.post"
    try:
        token, aes_key, suite_id = _load_wecom_config()
        body = await request.body()
        encrypt = crypto.parse_outer_xml(body)
        if not crypto.verify_signature(token, timestamp, nonce, encrypt, msg_signature):
            raise WeComCallbackError("signature_invalid")
        msg, receiveid = crypto.decrypt_message(encrypt, aes_key)
        try:
            plaintext = msg.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise WeComCallbackError("invalid_plaintext", detail=str(exc)) from exc
        envelope = crypto.parse_envelope(plaintext)
        info_type = envelope.get("info_type") or ""
        # 指令类：receiveid == suite_id + 内层 SuiteId 双校验；数据类不按 suite_id 强校验
        # （数据类 ToUserName 即密文 corpid，P0 实测 receiveid 为 corpid）
        if info_type in _COMMAND_INFO_TYPES:
            if receiveid != suite_id:
                raise WeComCallbackError("suite_mismatch")
            inner_suite_id = envelope.get("suite_id")
            if inner_suite_id and inner_suite_id != suite_id:
                raise WeComCallbackError("suite_mismatch")
        # 事件落库（幂等 + 安全分类，§5.3）
        extra = envelope.get("extra") or {}
        try:
            result = wecom_callback_service.receive_event(
                info_type=info_type,
                suite_id=envelope.get("suite_id"),
                auth_corp_id=extra.get("AuthCorpId") or extra.get("ToUserName"),
                from_user_name=extra.get("FromUserName"),
                event_create_time=_to_int(envelope.get("timestamp")),
                change_type=extra.get("ChangeType"),
                extra=extra,
            )
        except Exception as exc:  # noqa: BLE001  落库失败 → 服务端错误（企微重试）
            logger.error(
                "wecom_callback stage=%s result=inbox_failed ts=%s",
                stage, _safe_timestamp(), exc_info=True,
            )
            return PlainTextResponse("internal error", status_code=500)
        logger.info(
            "wecom_callback stage=%s result=%s event_type=%s suite_id=%s ts=%s",
            stage, result.get("result"), info_type or "unknown",
            envelope.get("suite_id") or "-", _safe_timestamp(),
        )
    except WeComCallbackError as exc:
        return _fail_closed(exc, stage)
    return PlainTextResponse("success")
