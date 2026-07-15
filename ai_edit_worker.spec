# -*- mode: python ; coding: utf-8 -*-
"""Phase 12 Task 8 AI 剪辑 Worker PyInstaller spec（Python 3.11 独立运行时）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §12.2。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 8。

边界：
- 独立于 local_agent.spec（后者固定 Python 3.10），Worker 固定 Python 3.11；
- Worker 是子进程，由 19000 监管器启动，不监听端口、不引入 uvicorn server；
- 重依赖（PyTorch/FunASR/OpenCV/YOLO/open_clip）单独 requirements-ai-edit-worker.txt；
- 不把 Worker 重依赖收进 local_agent.spec（双运行时隔离）。

构建由 scripts/build_ai_edit_worker_exe.ps1 驱动，校验 Python 3.11 + FFmpeg + 字体 + 模型。
"""

block_cipher = None

a = Analysis(
    ['apps/ai_edit/worker_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 字体与模型目录由构建脚本动态注入（--add-data 或运行时复制），
        # 此处仅声明 Worker 自身源码数据。
    ],
    hiddenimports=[
        # 视觉/ASR 重依赖按需隐藏导入（打包后由构建脚本验证）
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除 uvicorn/FastAPI server（Worker 不监听端口，是子进程）
        'uvicorn',
        'fastapi',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ai_edit_worker',
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
