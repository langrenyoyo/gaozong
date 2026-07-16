# -*- mode: python ; coding: utf-8 -*-
"""Phase 12 Task 11 Local Agent 测试 spec（Python 3.10 onefile）。

与 local_agent.spec 的区别：
- onefile（单 exe，供外层 phase12_test_launcher.spec 作为随包资源收集）；
- 收集微信测试需要的 EasyOCR、PyTorch、Pillow 与 OpenCV；
- AI 剪辑 Worker 侧的 ultralytics/funasr/open_clip 仍由独立 ai_edit_worker.spec 管理。

token 安全：token 运行时由外层启动器经环境变量注入，不进源码/spec/argv。
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ["app.local_agent_build_info"]
OCR_RUNTIME_PACKAGES = ("easyocr", "torch", "torchvision", "PIL", "cv2")

# EasyOCR 在业务代码中惰性导入，必须显式收集，否则 EXE 能启动但文字识别不可用。
for package_name in ("pydantic", *OCR_RUNTIME_PACKAGES):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


a = Analysis(
    ["app\\local_agent_exe_entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # AI 剪辑 Worker 专属重依赖不进入 Local Agent。
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
    name="local_agent_phase12_test",
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
