"""视频媒体探测：用 mutagen 纯 Python 库探测时长。

上传素材时对临时文件跑 mutagen 探测 duration，
写入 AiEditMaterial 的 duration_seconds 字段。
不依赖 ffmpeg/ffprobe，纯 Python 库，Docker 镜像无需装系统包。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def probe_video(file_path: str) -> dict[str, Any]:
    """用 mutagen 探测视频元数据，返回 {duration_seconds, width, height, fps}。

    失败时返回空 dict（不阻断上传流程，仅记 warning）。
    mutagen 主要可靠探测时长；分辨率/帧率无法从纯音频/视频容器元数据获取，留空。
    """
    try:
        from mutagen.mp4 import MP4
        from mutagen import File as MutagenFile
    except ImportError:
        logger.warning("media_probe_skip reason=no_mutagen")
        return {}

    try:
        # 优先用 MP4 解析器（支持 .mp4/.m4v/.mov）
        if file_path.lower().endswith((".mp4", ".m4v", ".mov", ".3gp", ".3g2")):
            media = MP4(file_path)
        else:
            # 其它格式用通用 File 解析
            media = MutagenFile(file_path)

        if media is None:
            return {}

        duration = None
        if hasattr(media, "info") and media.info is not None:
            dur_raw = getattr(media.info, "length", None)
            if dur_raw is not None:
                try:
                    duration = float(dur_raw)
                except (TypeError, ValueError):
                    pass

        result: dict[str, Any] = {}
        if duration is not None:
            result["duration_seconds"] = duration

        # MP4 可提取分辨率
        if isinstance(media, MP4) and hasattr(media, "info"):
            width = getattr(media.info, "width", None)
            height = getattr(media.info, "height", None)
            if width:
                result["width"] = width
            if height:
                result["height"] = height

        return result
    except Exception as exc:
        logger.warning("media_probe_error error_type=%s: %s", type(exc).__name__, exc)
        return {}
