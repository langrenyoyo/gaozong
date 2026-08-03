"""TOS 对象存储上传客户端（喂给 LAS speech_auto）。

迁移自甲方已验证的 demo E:\\work\\demo\\las_speech_auto\\file_uploader.py。
用火山引擎 TOS SDK 把本地视频文件直传到自有 Bucket，再生成预签名 https URL 喂给 LAS。

为什么不用方舟 Files API：方舟托管存储只返回 file id，不产出 tos:// 或可访问 https 地址，
而 LAS 只接受 tos:// 或 https 预签名地址。TOS 直传 + 预签名是唯一能打通自动链路的方式。

对应文档：https://docs.volcengine.com/docs/6349/74836
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from typing import Iterable

import requests

from app import config

logger = logging.getLogger(__name__)

# 递归列举目录时识别的视频扩展名
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".flv", ".webm")

# 视频上传时的 Content-Type 兜底映射
_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".flv": "video/x-flv",
    ".webm": "video/webm",
}


class UploadError(Exception):
    """上传过程中的错误，附带 metadata 便于排查。"""

    def __init__(self, message: str, metadata: dict | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


class TOSUploader:
    """封装 TOS SDK 的上传与预签名 URL 生成。

    从 config 取凭证/endpoint/region/bucket，测试可注入。
    tos SDK 在 __init__ 内延迟 import，避免未安装环境 import 本模块即崩溃。
    """

    def __init__(
        self,
        endpoint: str | None = None,
        region: str | None = None,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        prefix: str = "",
        url_expire: int | None = None,
    ):
        endpoint = endpoint or config.TOS_ENDPOINT
        region = region or config.TOS_REGION
        bucket = bucket or config.TOS_BUCKET
        access_key = access_key or config.TOS_ACCESS_KEY
        secret_key = secret_key or config.TOS_SECRET_KEY
        url_expire = url_expire or config.LAS_TOS_PRESIGN_EXPIRES_SECONDS

        if not all([endpoint, region, bucket, access_key, secret_key]):
            raise UploadError(
                "TOS 配置不完整：需要 endpoint/region/bucket/access_key/secret_key"
            )
        self.bucket = bucket
        # 统一 prefix 为带斜杠尾的形式，便于拼接 key
        self.prefix = prefix.strip().lstrip("/").rstrip("/") + "/" if prefix.strip() else ""
        self.url_expire = url_expire
        try:
            import tos  # 延迟 import：未安装 tos 时本模块仍可被 import

            auth = tos.Auth(access_key, secret_key, region)
            self.client = tos.TosClient(auth, endpoint)
        except UploadError:
            raise
        except Exception as e:
            raise UploadError(f"创建 TOS 客户端失败：{e}") from e

    def _key_for(self, filename: str) -> str:
        """把本地文件名映射为 Bucket 内的 object key。"""
        return self.prefix + os.path.basename(filename)

    def upload(self, file_path: str) -> str:
        """上传单个本地文件，返回其 object key。"""
        path = os.path.abspath(file_path)
        if not os.path.isfile(path):
            raise UploadError(f"文件不存在：{path}")

        key = self._key_for(path)
        content_type = _CONTENT_TYPES.get(
            os.path.splitext(path)[1].lower(), "application/octet-stream"
        )

        try:
            with open(path, "rb") as f:
                self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=f, ContentType=content_type
                )
        except Exception as e:
            # 统一捕获 TosServerError/TosClientError/TosError，提取稳定字段
            status_code = getattr(e, "status_code", "")
            code = getattr(e, "code", "")
            raise UploadError(
                f"上传 {os.path.basename(path)} 失败：{status_code} {code}: {e}",
                metadata={"status_code": status_code, "code": code},
            ) from e

        return key

    def presign(self, key: str) -> str:
        """为 object 生成预签名 https GET URL。"""
        try:
            url = self.client.generate_presigned_url(
                Method="GET", Bucket=self.bucket, Key=key, ExpiresIn=self.url_expire
            )
        except Exception as e:
            raise UploadError(f"生成预签名 URL 失败：{key}：{e}") from e
        if not isinstance(url, str):
            # 某些 SDK 版本返回带 .url 属性的对象
            url = getattr(url, "url", str(url))
        return url

    def upload_and_presign(self, file_path: str) -> str:
        """上传单个文件并返回预签名 https URL。"""
        key = self.upload(file_path)
        return self.presign(key)

    def upload_file_stream(self, src_path: str, key: str, content_type: str = "video/mp4") -> None:
        """流式上传本地文件到指定 key（用于归档临时文件到自有 TOS）。

        使用分块读取避免大文件整体载入内存。
        """
        try:
            with open(src_path, "rb") as f:
                self.client.put_object(
                    Bucket=self.bucket, Key=key, Body=f, ContentType=content_type
                )
        except Exception as e:
            status_code = getattr(e, "status_code", "")
            code = getattr(e, "code", "")
            raise UploadError(
                f"流式上传 {key} 失败：{status_code} {code}: {e}",
                metadata={"status_code": status_code, "code": code},
            ) from e

    def delete_object(self, key: str) -> None:
        """删除自有 TOS 对象（用于删除归档最终视频）。"""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            status_code = getattr(e, "status_code", "")
            code = getattr(e, "code", "")
            raise UploadError(
                f"删除 {key} 失败：{status_code} {code}: {e}",
                metadata={"status_code": status_code, "code": code},
            ) from e

    def head_object(self, key: str) -> dict | None:
        """查询对象元信息（大小/类型），不存在返回 None。"""
        try:
            resp = self.client.head_object(Bucket=self.bucket, Key=key)
            return {
                "content_length": getattr(resp, "content_length", None),
                "content_type": getattr(resp, "content_type", None),
            }
        except Exception:
            return None

    @staticmethod
    def download_https_to_temp(
        url: str,
        *,
        dest_dir: str | None = None,
        timeout: int = 120,
        max_size_bytes: int = 600 * 1024 * 1024,
    ) -> tuple[str, int]:
        """下载 https URL 到受控临时文件，返回 (临时路径, 文件大小)。

        流式下载避免大文件载入内存；校验 HTTP 状态、内容类型与大小上限，
        防止把 HTML 错误页当 MP4 上传。临时文件名唯一，调用方负责清理。
        """
        os.makedirs(dest_dir or tempfile.gettempdir(), exist_ok=True)
        fname = f"ai-edit-arch-{uuid.uuid4().hex}.mp4"
        path = os.path.join(dest_dir or tempfile.gettempdir(), fname)
        total = 0
        try:
            with requests.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "")
                # 拒绝非视频内容类型（HTML 错误页/JSON 错误等）
                if ctype and not ctype.startswith("video/") and not ctype.startswith("application/octet-stream"):
                    raise UploadError(
                        f"下载内容类型非视频：{ctype}（可能为错误页）",
                        metadata={"content_type": ctype, "url": url[:80]},
                    )
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 16):
                        if chunk:
                            total += len(chunk)
                            if total > max_size_bytes:
                                raise UploadError(
                                    f"下载超出大小上限 {max_size_bytes} 字节",
                                    metadata={"max_size_bytes": max_size_bytes},
                                )
                            f.write(chunk)
        except UploadError:
            raise
        except requests.RequestException as e:
            raise UploadError(f"下载失败：{e}", metadata={"url": url[:80]}) from e
        finally:
            # 失败时清理半成品临时文件
            pass
        return path, total

    def upload_many(self, file_paths: Iterable[str]) -> list[tuple[str, str | None]]:
        """顺序上传多个文件，返回 [(本地路径, 预签名URL)]。

        单个失败不中断整体，失败项 URL 为 None 并记 warning。
        """
        results: list[tuple[str, str | None]] = []
        for idx, fp in enumerate(file_paths, 1):
            name = os.path.basename(fp)
            try:
                url = self.upload_and_presign(fp)
            except UploadError as e:
                logger.warning("TOS 上传 %s 失败：%s", name, e)
                results.append((fp, None))
                continue
            logger.info("TOS 上传 [%s] %s OK", idx, name)
            results.append((fp, url))
        return results


def expand_local_files(specs) -> list[str]:
    """把配置项解析为具体本地文件路径列表。

    支持逗号/换行分隔的多项；每项可为文件路径或目录（递归列举视频）。
    去重并保持顺序。空输入返回 []。
    """
    if isinstance(specs, (list, tuple)):
        items = list(specs)
    else:
        items = []
        for chunk in str(specs).replace("\n", ",").split(","):
            chunk = chunk.strip()
            if chunk:
                items.append(chunk)

    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if os.path.isdir(item):
            for root, _dirs, files in os.walk(item):
                for fn in sorted(files):
                    if fn.lower().endswith(VIDEO_EXTS):
                        _add_unique(result, seen, os.path.join(root, fn))
        elif os.path.isfile(item):
            _add_unique(result, seen, item)
        else:
            logger.warning("TOS 路径不存在，跳过：%s", item)
    return result


def _add_unique(result: list[str], seen: set[str], path: str) -> None:
    p = os.path.abspath(path)
    if p not in seen:
        seen.add(p)
        result.append(p)
