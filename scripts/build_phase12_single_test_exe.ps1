param(
    [Parameter(Mandatory = $true)][string]$Python310Exe,
    [Parameter(Mandatory = $true)][string]$Python311Exe,
    [Parameter(Mandatory = $true)][string]$FfmpegDir,
    [Parameter(Mandatory = $true)][string]$TestApiUrl,
    [Parameter(Mandatory = $true)][string]$TestFrontendUrl,
    [Parameter(Mandatory = $true)][string]$MerchantId
)

# Phase 12 Task 11 单入口测试 EXE 构建脚本。
# 计划：docs/superpowers/plans/2026-07-16-phase12-task11-single-entry-test-exe-execution-package.md Task 11-2。
#
# 边界（计划 §2 / §5）：
# - 缺 PyInstaller 时直接安装，不锁版本。
# - 不读取 LICENSE_CONFIRMED.txt / THIRD_PARTY_NOTICES.md，不做许可证/Defender/archive/FFmpeg buildconf 检查。
# - 输出 dist\phase12-task11\小高AI系统测试版.exe，打印 SHA-256。
# - token 运行时输入，不进源码/spec/argv/EXE。

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DistRoot = Join-Path $ProjectRoot "dist\phase12-task11"
$BundleDir = Join-Path $ProjectRoot "build\phase12-task11-bundle"
$InnerLocalAgentSpec = Join-Path $ProjectRoot "local_agent_phase12_test.spec"
$WorkerSpec = Join-Path $ProjectRoot "ai_edit_worker.spec"
$OuterLauncherSpec = Join-Path $ProjectRoot "phase12_test_launcher.spec"
$AppName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5bCP6auYQUnns7vnu5/mtYvor5XniYg="))
$OutputExe = Join-Path $DistRoot "$AppName.exe"

function Ensure-PyInstaller([string]$PyExe) {
    & $PyExe -m PyInstaller --version 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[build] 安装 PyInstaller（$PyExe）"
        & $PyExe -m pip install pyinstaller
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败：$PyExe" }
    }
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path (Join-Path $FfmpegDir "ffmpeg.exe"))) {
        throw "FFmpeg 缺失：$FfmpegDir\ffmpeg.exe"
    }
    if (-not (Test-Path (Join-Path $FfmpegDir "ffprobe.exe"))) {
        throw "ffprobe 缺失：$FfmpegDir\ffprobe.exe"
    }
    if (-not (Test-Path $InnerLocalAgentSpec)) { throw "spec 缺失：$InnerLocalAgentSpec" }
    if (-not (Test-Path $WorkerSpec)) { throw "spec 缺失：$WorkerSpec" }
    if (-not (Test-Path $OuterLauncherSpec)) { throw "spec 缺失：$OuterLauncherSpec" }

    New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null
    New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null

    # ---- 1. 内部 Local Agent（Python 3.10 轻量 onefile）----
    Write-Host "[build] 1/3 内部 Local Agent（Python 3.10）"
    Ensure-PyInstaller $Python310Exe
    & $Python310Exe -m PyInstaller $InnerLocalAgentSpec `
        --distpath $BundleDir --workpath (Join-Path $ProjectRoot "build\local_agent_test") --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "内部 Local Agent 构建失败" }
    $InnerLocalAgentExe = Join-Path $BundleDir "local_agent_phase12_test.exe"
    if (-not (Test-Path $InnerLocalAgentExe)) { throw "内部 Local Agent 产物缺失：$InnerLocalAgentExe" }

    # ---- 2. Worker（Python 3.11，复用 ai_edit_worker.spec）----
    Write-Host "[build] 2/3 Worker（Python 3.11）"
    Ensure-PyInstaller $Python311Exe
    & $Python311Exe -m PyInstaller $WorkerSpec `
        --distpath $BundleDir --workpath (Join-Path $ProjectRoot "build\ai_edit_worker_test") --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "Worker 构建失败" }
    $WorkerExe = Join-Path $BundleDir "ai_edit_worker.exe"
    if (-not (Test-Path $WorkerExe)) { throw "Worker 产物缺失：$WorkerExe" }

    # ---- 3. 收集 FFmpeg / ffprobe 到 bundle 目录 ----
    Copy-Item -Path (Join-Path $FfmpegDir "ffmpeg.exe") -Destination $BundleDir -Force
    Copy-Item -Path (Join-Path $FfmpegDir "ffprobe.exe") -Destination $BundleDir -Force

    # ---- 3.5 烘焙测试配置 JSON（URL 进 EXE，运行时不依赖环境变量）----
    $configJson = @{
        test_api_url    = $TestApiUrl
        frontend_url    = $TestFrontendUrl
        merchant_id     = $MerchantId
    } | ConvertTo-Json -Compress
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        (Join-Path $BundleDir "phase12_test_config.json"),
        $configJson, $utf8NoBom
    )

    # ---- 4. 外层启动器（Python 3.10 onefile，收集内部 exe + 媒体工具 + 配置）----
    Write-Host "[build] 3/3 外层启动器（Python 3.10）"
    $env:PHASE12_TEST_BUNDLE_DIR = $BundleDir
    & $Python310Exe -m PyInstaller $OuterLauncherSpec `
        --distpath $DistRoot --workpath (Join-Path $ProjectRoot "build\phase12_launcher") --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "外层启动器构建失败" }
    if (-not (Test-Path $OutputExe)) { throw "外层启动器产物缺失：$OutputExe" }

    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $OutputExe
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "构建完成：小高AI系统测试版"
    Write-Host "=========================================="
    Write-Host "exe: $OutputExe"
    Write-Host "sha256: $($hash.Hash)"
    Write-Host "test_api_url: $TestApiUrl"
    Write-Host "test_frontend_url: $TestFrontendUrl"
    Write-Host "merchant_id: $MerchantId"
    Write-Host "=========================================="
}
finally {
    Pop-Location
}
