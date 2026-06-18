"""火山方舟 Ark 多模态 embedding 客户端。

设计约束：
- 本模块【禁止】反向导入 client.py，避免与 client.py 的门面委托形成循环导入；
- 所有异常统一抛出 ArkEmbeddingError，由 client.py 的 embed() 门面捕获
  并转换为 LLMRequestError，保持对外契约不变；
- 仅使用标准库 urllib，不引入 requests 依赖；
- 本阶段只构造 text 类型 input，不支持 image / video 训练入口。
"""

from __future__ import annotations

import json
import logging
import time
from urllib import error as urllib_error
from urllib import request as urllib_request

from apps.xg_douyin_ai_cs.llm.embedding_config import EmbeddingConfig

_logger = logging.getLogger("apps.xg_douyin_ai_cs.embedding")

# 响应摘要最大长度，避免日志刷屏或泄露敏感内容
_RESP_SUMMARY_LEN = 200


class ArkEmbeddingError(RuntimeError):
    """Ark embedding 调用异常（HTTP / 超时 / 解析 / 空向量等统一异常）。"""


class ArkEmbeddingClient:
    """火山方舟 Ark 多模态 embedding 客户端。"""

    def __init__(self, config: EmbeddingConfig):
        self.cfg = config

    def embed_text(self, text: str) -> dict:
        """对单段纯文本生成 embedding，返回 {embedding, model, embedding_provider}。"""
        payload = self._build_payload(text)
        url = f"{self.cfg.base_url.rstrip('/')}{self.cfg.endpoint}"
        text_len = len(str(text or ""))
        started = time.perf_counter()
        data = self._post(url, payload, text_len)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        embedding, model = self._parse(data)

        if not embedding:
            resp_summary = self._safe_summary(data)
            _logger.error(
                "embedding branch=ark stage=empty_vector provider=ark model=%s "
                "endpoint=%s input_type=text text_len=%d timeout=%s "
                "dimensions_passed=%s sparse=%s resp_keys=%s resp_summary=%s",
                self.cfg.model,
                url,
                text_len,
                self.cfg.timeout_seconds,
                bool(self.cfg.dimensions),
                self.cfg.sparse_enabled,
                list(data.keys()) if isinstance(data, dict) else type(data).__name__,
                resp_summary,
            )
            raise ArkEmbeddingError("ark_embedding_empty_vector")

        _logger.info(
            "embedding branch=ark stage=ok provider=ark model=%s endpoint=%s "
            "input_type=text text_len=%d timeout=%s dimensions_passed=%s "
            "dimensions_value=%s sparse=%s encoding_format=%s elapsed_ms=%d vector_dim=%d",
            model,
            url,
            text_len,
            self.cfg.timeout_seconds,
            bool(self.cfg.dimensions),
            self.cfg.dimensions or "server_default",
            self.cfg.sparse_enabled,
            self.cfg.encoding_format,
            elapsed_ms,
            len(embedding),
        )
        return {
            "embedding": [float(item) for item in embedding],
            "model": model or self.cfg.model,
            "embedding_provider": "ark_multimodal",
        }

    # ---------- payload 构造 ----------
    def _build_payload(self, text: str) -> dict:
        payload = {
            "model": self.cfg.model,
            "encoding_format": self.cfg.encoding_format,
            # 本阶段只处理纯文本；image / video 入口后续再扩展
            "input": [{"type": "text", "text": str(text or "")}],
        }
        # dimensions 为空则不传，使用服务端默认（Ark doubao-embedding-vision 默认 2024 维）
        if self.cfg.dimensions:
            payload["dimensions"] = int(self.cfg.dimensions)
        # sparse_embedding 本阶段默认关闭；关闭时不传该字段，也不写入数据库
        if self.cfg.sparse_enabled:
            payload["sparse_embedding"] = "enabled"
        return payload

    # ---------- HTTP 请求（urllib，不引入 requests）----------
    def _post(self, url: str, payload: dict, text_len: int) -> dict:
        req = urllib_request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                # Authorization 仅用于请求，日志永不打印该 header
                "Authorization": f"Bearer {self.cfg.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(
                req, timeout=self.cfg.timeout_seconds
            ) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                body = resp.read().decode("utf-8") or "{}"
        except urllib_error.HTTPError as exc:
            body = self._safe_read_httperror(exc)
            _logger.error(
                "embedding branch=ark stage=http_error provider=ark status=%s "
                "endpoint=%s text_len=%d timeout=%s resp_summary=%s",
                exc.code,
                url,
                text_len,
                self.cfg.timeout_seconds,
                body[:_RESP_SUMMARY_LEN],
            )
            raise ArkEmbeddingError(
                f"ark_http_{exc.code}: {body[:_RESP_SUMMARY_LEN]}"
            ) from exc
        except (urllib_error.URLError, TimeoutError) as exc:
            _logger.error(
                "embedding branch=ark stage=timeout_or_conn provider=ark error=%s "
                "endpoint=%s text_len=%d timeout=%s",
                type(exc).__name__,
                url,
                text_len,
                self.cfg.timeout_seconds,
            )
            raise ArkEmbeddingError(f"ark_timeout: {exc}") from exc

        # 防御性状态码检查（urllib 对 4xx/5xx 已抛 HTTPError，正常路径此处恒为 2xx）
        if not (200 <= int(status) < 300):
            _logger.error(
                "embedding branch=ark stage=http_status provider=ark status=%s "
                "endpoint=%s text_len=%d resp_summary=%s",
                status,
                url,
                text_len,
                body[:_RESP_SUMMARY_LEN],
            )
            raise ArkEmbeddingError(
                f"ark_http_{status}: {body[:_RESP_SUMMARY_LEN]}"
            )

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            _logger.error(
                "embedding branch=ark stage=parse_error provider=ark endpoint=%s "
                "text_len=%d resp_summary=%s",
                url,
                text_len,
                body[:_RESP_SUMMARY_LEN],
            )
            raise ArkEmbeddingError(f"ark_parse_error: {exc}") from exc

    # ---------- 响应解析（兼容 data 为 list / dict 两种形态）----------
    def _parse(self, data: dict) -> tuple[list, str]:
        data_obj = data.get("data") if isinstance(data, dict) else None
        embedding: list = []
        if isinstance(data_obj, list) and data_obj:
            item = data_obj[0]
            if isinstance(item, dict):
                embedding = item.get("embedding") or []
        elif isinstance(data_obj, dict):
            embedding = data_obj.get("embedding") or []
        model = data.get("model") if isinstance(data, dict) else None
        return embedding, str(model or "")

    # ---------- 工具 ----------
    @staticmethod
    def _safe_read_httperror(exc: urllib_error.HTTPError) -> str:
        try:
            return exc.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    @staticmethod
    def _safe_summary(data) -> str:
        try:
            return json.dumps(data, ensure_ascii=False)[:_RESP_SUMMARY_LEN]
        except Exception:
            return str(data)[:_RESP_SUMMARY_LEN]
