param(
    [Parameter(Mandatory = $true)][string]$Python311Exe,
    [Parameter(Mandatory = $true)][string]$FfmpegDir,
    [Parameter(Mandatory = $true)][string]$ModelDir,
    [Parameter(Mandatory = $true)][string]$FontDir,
    [ValidateSet("Development", "Customer")][string]$DistributionMode = "Development"
)

# Phase 12 Task 8 AI 剪辑 Worker 独立打包脚本（Python 3.11 双运行时）。
# 冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §12.2。
# 执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 8。
#
# 边界：
# - 强制校验 Python 3.11（不接受 3.10，不修改 local_agent.spec 的 3.10）。
# - 字体目录强制非空（中文字幕烧录依赖预检字体）。
# - DistributionMode=Customer 时强制校验全部许可证已确认，否则 throw 禁止形成客户安装包。
# - Development 模式仅源码级本地测试，不要求许可证完整。

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SpecFile = Join-Path $ProjectRoot "ai_edit_worker.spec"
$DistDir = Join-Path $ProjectRoot "dist\local-agent"
$WorkerExe = Join-Path $DistDir "ai_edit_worker.exe"
$LicenseFile = Join-Path $ProjectRoot "docs\ai\13_ai_edit\THIRD_PARTY_NOTICES.md"
# 许可证确认标记文件（Customer 模式必须存在，标识所有组件可分发依据已确认）
$LicenseConfirmedFile = Join-Path $ProjectRoot "docs\ai\13_ai_edit\LICENSE_CONFIRMED.txt"

# ---------------------------------------------------------------------------
# 强制校验 Python 3.11
# ---------------------------------------------------------------------------
if (-not $Python311Exe) {
    throw "Python311Exe 参数必填：必须指向 Python 3.11 可执行文件"
}
$pyVersion = & $Python311Exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pyVersion -ne "3.11") {
    throw "Worker 必须用 Python 3.11 构建，当前为 $pyVersion（local_agent 用 3.10，双运行时隔离）"
}

# ---------------------------------------------------------------------------
# 缺失组件明确失败（字体与模型强制非空）
# ---------------------------------------------------------------------------
if (-not (Test-Path $SpecFile)) {
    throw "Worker spec 缺失：$SpecFile"
}
if (-not (Test-Path (Join-Path $FfmpegDir "ffmpeg.exe"))) {
    throw "FFmpeg 缺失：$FfmpegDir\ffmpeg.exe（Vid.Stab 增稳依赖 libvidstab）"
}
if (-not (Test-Path (Join-Path $FfmpegDir "ffprobe.exe"))) {
    throw "ffprobe 缺失：$FfmpegDir\ffprobe.exe（媒体强门探测依赖）"
}
# Vid.Stab 校验：ffmpeg -filters 含 vidstab
$filters = & (Join-Path $FfmpegDir "ffmpeg.exe") -filters 2>&1
if ($filters -notmatch "vidstab") {
    throw "FFmpeg 缺少 libvidstab 滤镜（Vid.Stab 增稳不可用）"
}
if (-not (Test-Path $ModelDir)) {
    throw "模型目录缺失：$ModelDir（FunASR/YOLO/open_clip 权重）"
}
# FIX1-8：字体目录强制非空（不再可空）
if (-not $FontDir -or -not (Test-Path $FontDir)) {
    throw "字体目录缺失或为空：FontDir（中文字幕烧录依赖预检字体，不可省略）"
}
$fontFiles = Get-ChildItem -Path $FontDir -File -ErrorAction SilentlyContinue
if (-not $fontFiles -or $fontFiles.Count -eq 0) {
    throw "字体目录为空：$FontDir（必须包含确定的中文字体文件）"
}
if (-not (Test-Path $LicenseFile)) {
    throw "第三方许可证文件缺失：$LicenseFile（缺可分发依据禁止形成客户安装包）"
}

# FIX1-8：Customer 分发模式门禁——所有组件许可证必须已确认
if ($DistributionMode -eq "Customer") {
    if (-not (Test-Path $LicenseConfirmedFile)) {
        throw "Customer 分发模式要求 LICENSE_CONFIRMED.txt 存在：所有第三方组件（FFmpeg/libvidstab/libx264/FunASR/PyTorch/YOLO/open_clip/字体）商用可分发依据必须确认完毕。当前未确认，禁止形成客户安装包。"
    }
    Write-Host "[build_ai_edit_worker] DistributionMode=Customer：许可证已确认，允许形成客户安装包"
} else {
    Write-Host "[build_ai_edit_worker] DistributionMode=Development：仅源码级本地测试，不形成客户安装包"
}

Write-Host "[build_ai_edit_worker] Python=$pyVersion FfmpegDir=$FfmpegDir ModelDir=$ModelDir FontDir=$FontDir Mode=$DistributionMode"

# ---------------------------------------------------------------------------
# 安装 Worker 重依赖（Python 3.11 独立环境）
# ---------------------------------------------------------------------------
& $Python311Exe -m pip install -r (Join-Path $ProjectRoot "requirements-ai-edit-worker.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Worker 依赖安装失败（requirements-ai-edit-worker.txt）"
}

# ---------------------------------------------------------------------------
# PyInstaller 构建
# ---------------------------------------------------------------------------
& $Python311Exe -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $Python311Exe -m pip install pyinstaller
}

Push-Location $ProjectRoot
try {
    & $Python311Exe -m PyInstaller $SpecFile --distpath $DistDir --workpath (Join-Path $ProjectRoot "build\ai_edit_worker") --noconfirm
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller 构建 ai_edit_worker.exe 失败"
    }

    # 复制 FFmpeg/ffprobe、字体、模型、许可证到安装目录
    Copy-Item -Path (Join-Path $FfmpegDir "ffmpeg.exe") -Destination $DistDir -Force
    Copy-Item -Path (Join-Path $FfmpegDir "ffprobe.exe") -Destination $DistDir -Force
    Copy-Item -Path $ModelDir -Destination (Join-Path $DistDir "models") -Recurse -Force
    if ($FontDir) {
        Copy-Item -Path $FontDir -Destination (Join-Path $DistDir "fonts") -Recurse -Force
    }
    Copy-Item -Path $LicenseFile -Destination (Join-Path $DistDir "THIRD_PARTY_NOTICES.md") -Force

    Write-Host "[build_ai_edit_worker] 产物: $WorkerExe"
    Write-Host "[build_ai_edit_worker] 安装目录包含: ai_edit_worker.exe, 小高AI微信助手.exe, ffmpeg, ffprobe, fonts, models, THIRD_PARTY_NOTICES.md"
}
finally {
    Pop-Location
}
