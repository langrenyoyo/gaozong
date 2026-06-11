"""Prepare EasyOCR model files for the local agent onedir package."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

REQUIRED_MODEL_FILES = ("craft_mlt_25k.pth", "zh_sim_g2.pth")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _easyocr_cache_model_dir() -> Path:
    env_dir = os.environ.get("EASYOCR_MODULE_PATH")
    if env_dir:
        return Path(env_dir) / "model"
    return Path.home() / ".EasyOCR" / "model"


def _target_model_dir() -> Path:
    return _project_root() / "resources" / "easyocr_models"


def _file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 2)


def main() -> int:
    try:
        import easyocr
    except Exception as exc:
        print(f"EasyOCR 不可用，请先安装 requirements-ocr.txt: {exc}", file=sys.stderr)
        return 1

    cache_dir = _easyocr_cache_model_dir()
    target_dir = _target_model_dir()

    print("正在初始化 EasyOCR Reader，首次运行可能需要下载模型...")
    try:
        easyocr.Reader(["ch_sim", "en"], gpu=False, model_storage_directory=str(cache_dir), verbose=False)
    except Exception as exc:
        print(f"EasyOCR 模型准备失败: {exc}", file=sys.stderr)
        return 1

    missing = [name for name in REQUIRED_MODEL_FILES if not (cache_dir / name).is_file()]
    if missing:
        print(f"EasyOCR 模型文件缺失: {', '.join(missing)}", file=sys.stderr)
        print(f"EasyOCR cache dir: {cache_dir}", file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in REQUIRED_MODEL_FILES:
        source = cache_dir / name
        target = target_dir / name
        shutil.copy2(source, target)
        copied.append(target)

    total_size = sum(path.stat().st_size for path in copied)
    print(f"EasyOCR cache dir: {cache_dir}")
    print(f"resources target dir: {target_dir}")
    print("copied files:")
    for path in copied:
        print(f"  - {path.name} ({_file_size_mb(path)} MB)")
    print(f"total size: {round(total_size / (1024 * 1024), 2)} MB")
    print("success=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
