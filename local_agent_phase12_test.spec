# -*- mode: python ; coding: utf-8 -*-
"""Phase 12 Task 11 轻量 Local Agent 测试 spec（Python 3.10 onefile）。

与 local_agent.spec 的区别：
- onefile（单 exe，供外层 phase12_test_launcher.spec 作为随包资源收集）；
- 排除当前 AI 剪辑测试不使用的 OCR/视觉重依赖（easyocr/torch/torchvision/PIL/cv2/numpy/
  ultralytics/funasr/open_clip）——这些在 Local Agent 侧均为函数内惰性 import，
  AI 剪辑路径不触发；Worker 侧重依赖由独立 ai_edit_worker.spec 打包，不在此收集。

token 安全：token 运行时由外层启动器经环境变量注入，不进源码/spec/argv。
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ["app.local_agent_build_info"]

# 仅收集 Local Agent 启动必需的纯 Python 包；重依赖按需排除。
for package_name in ("pydantic",):
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
        # OCR/视觉重依赖：Local Agent 侧惰性 import，AI 剪辑测试不触发。
        # 注意 numpy 不可排除：wechat_ui.contact_searcher 顶层 import numpy，
        # 排除会导致 EXE 启动即 ModuleNotFoundError 崩溃。
        "easyocr", "torch", "torchvision", "PIL", "cv2",
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
