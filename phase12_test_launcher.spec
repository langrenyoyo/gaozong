# -*- mode: python ; coding: utf-8 -*-
"""Phase 12 Task 11 外层单入口启动器 spec（Python 3.10 onefile）。

把随包内部 Local Agent exe、Worker exe、FFmpeg、ffprobe 收进一个 onefile EXE：
- 运行时 PyInstaller 解压到 sys._MEIPASS，启动器从 _MEIPASS 定位并子进程启动它们。
- 启动器仅用标准库 + ctypes（Job Object），不引入额外重依赖。

内部 exe 与媒体工具路径由构建脚本经环境变量 ``PHASE12_TEST_BUNDLE_DIR`` 注入：
该目录需含 local_agent_phase12_test.exe / ai_edit_worker.exe / ffmpeg.exe / ffprobe.exe。
"""
import os
from pathlib import Path

app_name = "小高AI系统测试版"

bundle_dir = Path(os.environ.get("PHASE12_TEST_BUNDLE_DIR", "."))
datas = []
for name in ("local_agent_phase12_test.exe", "ai_edit_worker.exe",
             "ffmpeg.exe", "ffprobe.exe", "phase12_test_config.json"):
    src = bundle_dir / name
    if not src.exists():
        # 构建脚本应保证文件就位；缺失在构建期即报错，不静默跳过。
        raise SystemExit(f"phase12_test_launcher.spec: 随包资源缺失 {src}")
    datas.append((str(src), "."))

REQUIRED_OCR_MODEL_FILES = ("craft_mlt_25k.pth", "zh_sim_g2.pth")
ocr_model_dir = bundle_dir / "models" / "easyocr"
ocr_model_target = Path("models/easyocr")
for name in REQUIRED_OCR_MODEL_FILES:
    src = ocr_model_dir / name
    if not src.exists():
        raise SystemExit(f"phase12_test_launcher.spec: OCR 模型缺失 {src}")
    datas.append((str(src), str(ocr_model_target)))


a = Analysis(
    ["app\\phase12_test_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "easyocr", "torch", "torchvision", "PIL", "cv2", "numpy",
        "ultralytics", "funasr", "open_clip",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
