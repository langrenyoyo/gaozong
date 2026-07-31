"""视频媒体探测：用 ffprobe 探测时长、分辨率、帧率。

上传素材时对临时文件跑 ffprobe，提取 duration/width/height/fps，
写入 AiEditMaterial 的媒体属性字段。
"""
from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def probe_video(file_path: str) -> dict[str, Any]:
    """用 ffprobe 探测视频元数据，返回 {duration_seconds, width, height, fps}。

    失败时返回空 dict（不阻断上传流程，仅记 warning）。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe 失败 returncode=%s stderr=%s", result.returncode, result.stderr[:200])
            return {}
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as exc:
        logger.warning("ffprobe 异常 error_type=%s: %s", type(exc).__name__, exc)
        return {}

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

    duration = None
    dur_raw = fmt.get("duration")
    if dur_raw:
        try:
            duration = float(dur_raw)
        except (TypeError, ValueError):
            pass

    width = video_stream.get("width") if video_stream else None
    height = video_stream.get("height") if video_stream else None
    fps = None
    if video_stream and video_stream.get("r_frame_rate"):
        # r_frame_rate 格式如 "30/1"
        try:
            num, den = video_stream["r_frame_rate"].split("/")
            den_f = float(den) if float(den) != 0 else 1
            fps = round(float(num) / den_f, 2)
        except (ValueError, ZeroDivisionError):
            pass

    return {
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "fps": fps,
    }
