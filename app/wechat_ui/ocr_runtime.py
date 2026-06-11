"""Shared OCR runtime state for the local WeChat agent."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_READER: Any | None = None
_INITIALIZING = False
_LAST_ERROR: str | None = None
_THREAD: threading.Thread | None = None

REQUIRED_MODEL_FILES = ("craft_mlt_25k.pth", "zh_sim_g2.pth")
MISSING_MODEL_MESSAGE = "小高AI微信助手缺少 OCR 模型文件，请重新复制完整 dist\\小高AI微信助手 目录，不要只复制 exe"


def _is_exe_mode() -> bool:
    return bool(getattr(sys, "frozen", False))


def _executable_path() -> Path:
    return Path(sys.executable)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _project_model_dir() -> Path:
    return _project_root() / "resources" / "easyocr_models"


def _default_cache_model_dir() -> Path:
    env_dir = os.environ.get("EASYOCR_MODULE_PATH")
    if env_dir:
        return Path(env_dir) / "model"
    return Path.home() / ".EasyOCR" / "model"


def _exe_model_dir() -> Path:
    return _executable_path().parent / "models" / "easyocr"


def _easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401

        return True
    except Exception:
        return False


def _model_stats(model_dir: Path) -> tuple[int, float, list[str]]:
    files = [path for path in model_dir.rglob("*") if path.is_file()] if model_dir.exists() else []
    total_size = sum(path.stat().st_size for path in files)
    return len(files), round(total_size / (1024 * 1024), 2), [str(path) for path in files]


def _has_required_models(model_dir: Path) -> bool:
    return model_dir.exists() and all((model_dir / name).is_file() for name in REQUIRED_MODEL_FILES)


def _missing_model_result(model_dir: Path) -> dict:
    count, total_size_mb, _ = _model_stats(model_dir)
    return {
        "success": False,
        "failure_stage": "ocr_model_missing",
        "model_source": "missing",
        "model_dir": str(model_dir),
        "download_enabled": False,
        "model_files_count": count,
        "model_total_size_mb": total_size_mb,
        "message": MISSING_MODEL_MESSAGE,
    }


def get_easyocr_model_dir() -> dict:
    """Return the model directory EasyOCR may use without downloading."""
    if _is_exe_mode():
        model_dir = _exe_model_dir()
        if not _has_required_models(model_dir):
            return _missing_model_result(model_dir)
        count, total_size_mb, _ = _model_stats(model_dir)
        return {
            "success": True,
            "model_source": "bundled",
            "model_dir": str(model_dir),
            "download_enabled": False,
            "model_files_count": count,
            "model_total_size_mb": total_size_mb,
        }

    bundled_dir = _project_model_dir()
    if _has_required_models(bundled_dir):
        count, total_size_mb, _ = _model_stats(bundled_dir)
        return {
            "success": True,
            "model_source": "bundled",
            "model_dir": str(bundled_dir),
            "download_enabled": False,
            "model_files_count": count,
            "model_total_size_mb": total_size_mb,
        }

    cache_dir = _default_cache_model_dir()
    if _has_required_models(cache_dir):
        count, total_size_mb, _ = _model_stats(cache_dir)
        return {
            "success": True,
            "model_source": "cache/dev",
            "model_dir": str(cache_dir),
            "download_enabled": False,
            "model_files_count": count,
            "model_total_size_mb": total_size_mb,
        }

    return _missing_model_result(bundled_dir)


def get_ocr_status() -> dict:
    """Return OCR readiness without initializing or downloading models."""
    global _LAST_ERROR
    available = _easyocr_available()
    if not available:
        _LAST_ERROR = "easyocr is not available"

    model_info = get_easyocr_model_dir()
    with _LOCK:
        initialized = _READER is not None
        initializing = _INITIALIZING
        last_error = _LAST_ERROR

    status = {
        **model_info,
        "ocr_available": available,
        "ocr_initialized": initialized,
        "model_ready": bool(available and model_info.get("success")),
        "initializing": initializing,
        "last_error": last_error,
        "engine": "easyocr",
        "cache_dir": str(_default_cache_model_dir()),
        "notes": ["OCR 模型已随 小高AI微信助手 打包，测试机不会联网下载模型"],
    }
    if not model_info.get("success"):
        status["model_ready"] = False
    return status


def _build_easyocr_reader(model_dir: str) -> Any:
    import easyocr

    return easyocr.Reader(
        ["ch_sim", "en"],
        gpu=False,
        model_storage_directory=model_dir,
        download_enabled=False,
        verbose=False,
    )


def _initialize_easyocr(model_dir: str) -> None:
    global _READER, _INITIALIZING, _LAST_ERROR
    try:
        reader = _build_easyocr_reader(model_dir)
        with _LOCK:
            _READER = reader
            _LAST_ERROR = None
    except Exception as exc:
        with _LOCK:
            _LAST_ERROR = str(exc)
    finally:
        with _LOCK:
            _INITIALIZING = False


def _start_background_initialization(model_dir: str) -> None:
    global _THREAD
    _THREAD = threading.Thread(target=_initialize_easyocr, args=(model_dir,), name="easyocr-warmup", daemon=True)
    _THREAD.start()


def start_ocr_warmup() -> dict:
    """Start EasyOCR initialization in a background thread and return immediately."""
    global _INITIALIZING
    status = get_ocr_status()
    if not status.get("ocr_available"):
        return {
            **status,
            "started": False,
            "message": "OCR 依赖不可用，请确认 easyocr 已打包或安装",
        }
    if status.get("failure_stage") == "ocr_model_missing":
        return {
            **status,
            "started": False,
            "message": MISSING_MODEL_MESSAGE,
        }
    if status.get("ocr_initialized"):
        return {
            **status,
            "started": False,
            "message": "OCR 已就绪",
        }
    if status.get("initializing"):
        return {
            **status,
            "started": False,
            "message": "OCR 模型正在初始化，请稍候",
        }

    with _LOCK:
        if _INITIALIZING:
            return {
                **get_ocr_status(),
                "started": False,
                "message": "OCR 模型正在初始化，请稍候",
            }
        _INITIALIZING = True
        _start_background_initialization(str(status["model_dir"]))

    next_status = get_ocr_status()
    return {
        **next_status,
        "started": True,
        "message": "OCR 模型正在初始化，请稍候",
    }


def get_easyocr_reader() -> Any | None:
    """Return the warmed EasyOCR reader if available."""
    with _LOCK:
        return _READER
