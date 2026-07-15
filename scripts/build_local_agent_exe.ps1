param(
    [string]$PythonExe = "python",
    [string]$ServerUrl = "https://callback.misanduo.com",
    # Phase 12 Task 8：是否同时构建 AI 剪辑 Worker（Python 3.11 独立运行时）。
    # 默认开启；Worker 重依赖（PyTorch/FunASR）较大，可传 -BuildWorker:$false 跳过。
    [bool]$BuildWorker = $true,
    [string]$Python311Exe = "python3.11",
    [string]$FfmpegDir = "",
    [string]$ModelDir = (Join-Path $PSScriptRoot "..\resources\ai_edit_models"),
    [string]$FontDir = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildInfoFile = Join-Path $ProjectRoot "app\local_agent_build_info.py"
$SpecFile = Join-Path $ProjectRoot "local_agent.spec"
$AppName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5bCP6auYQUnlvq7kv6HliqnmiYs="))
$DistDir = Join-Path $ProjectRoot "dist\local-agent"
$OutputExe = Join-Path $DistDir "$AppName.exe"
$EnvFile = Join-Path $DistDir ".env"
$LogDir = Join-Path $DistDir "logs"
$StopScriptSource = Join-Path $ProjectRoot "scripts\stop_local_agent.ps1"
$StopScriptTarget = Join-Path $DistDir "停止小高AI微信助手.ps1"
$ModelSourceRelative = "resources\easyocr_models"
$ModelSource = Join-Path $ProjectRoot $ModelSourceRelative
$ModelTarget = Join-Path $DistDir "models\easyocr"

Push-Location $ProjectRoot
try {
    $BuildVersion = "P0-LOCAL-AGENT-EXE-1"
    $BuildTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $GitCommit = "unknown"
    try {
        $GitCommit = & git rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -ne 0) { $GitCommit = "unknown" }
    } catch {
        $GitCommit = "unknown"
    }

    function ConvertTo-PythonStringLiteral {
        param([string]$Value)
        return ($Value | ConvertTo-Json -Compress)
    }

    $buildInfoLines = @(
        '"""',
        'Local Agent build info - auto generated.',
        '"""',
        '',
        ("BUILD_VERSION = {0}" -f (ConvertTo-PythonStringLiteral $BuildVersion)),
        ("BUILD_TIME = {0}" -f (ConvertTo-PythonStringLiteral $BuildTime)),
        ("GIT_COMMIT = {0}" -f (ConvertTo-PythonStringLiteral $GitCommit))
    )
    [System.IO.File]::WriteAllText(
        $BuildInfoFile,
        (($buildInfoLines -join [Environment]::NewLine) + [Environment]::NewLine),
        [System.Text.Encoding]::UTF8
    )

    Write-Host "BUILD_VERSION: $BuildVersion"
    Write-Host "BUILD_TIME: $BuildTime"
    Write-Host "GIT_COMMIT: $GitCommit"

    & $PythonExe -m py_compile "app\local_agent_build_info.py"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Build info validation failed: app\local_agent_build_info.py is not valid Python"
        exit 1
    }

    & $PythonExe --version
    Write-Host "Verifying OCR runtime dependencies..."
    $ocrDependencyCheck = @'
import easyocr
import torch
import cv2
from PIL import Image
print('easyocr ok', easyocr.__version__)
print('torch ok', torch.__version__)
print('cv2 ok', cv2.__version__)
print('PIL ok')
'@
    $ocrDependencyOutput = & $PythonExe -c $ocrDependencyCheck
    if ($LASTEXITCODE -ne 0) {
        Write-Host "OCR dependency validation failed"
        Write-Host "The Local Agent exe must be built with easyocr, torch, cv2 and PIL available."
        Write-Host "Recommended: -PythonExe C:\Users\A\miniconda3\envs\demo_auto_wechat\python.exe"
        exit 1
    }
    Write-Host $ocrDependencyOutput

    $pyinstallerVersion = & $PythonExe -c "import PyInstaller; print(PyInstaller.__version__)"
    Write-Host "PyInstaller version: $pyinstallerVersion"

    if (-not (Test-Path $SpecFile)) {
        Write-Host "Missing spec file: $SpecFile"
        exit 1
    }

    if (-not (Test-Path $StopScriptSource)) {
        Write-Host "Stop script missing: $StopScriptSource"
        exit 1
    }

    if (-not (Test-Path $ModelSource)) {
        Write-Host "Missing $ModelSourceRelative"
        Write-Host "Please run first: python scripts\prepare_easyocr_models.py"
        exit 1
    }

    $modelFiles = Get-ChildItem -Path $ModelSource -Recurse -File
    if ($modelFiles.Count -eq 0) {
        Write-Host "EasyOCR model directory is empty: $ModelSource"
        exit 1
    }

    Write-Host "Building $OutputExe ..."
    & $PythonExe -m PyInstaller --noconfirm $SpecFile
    if ($LASTEXITCODE -ne 0) {
        Write-Host "PyInstaller build failed"
        exit 1
    }

    if (-not (Test-Path $OutputExe)) {
        Write-Host "Build failed: output exe not found: $OutputExe"
        exit 1
    }

    New-Item -ItemType Directory -Force -Path $ModelTarget | Out-Null
    Copy-Item -Path (Join-Path $ModelSource "*") -Destination $ModelTarget -Recurse -Force

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Copy-Item -LiteralPath $StopScriptSource -Destination $StopScriptTarget -Force
    $envLines = @(
        "AUTO_WECHAT_SERVER_URL=$ServerUrl",
        "AUTO_WECHAT_AGENT_CLIENT_ID=local-agent-default",
        "AUTO_WECHAT_AGENT_NAME=$AppName",
        "LOCAL_AGENT_HOST=127.0.0.1",
        "LOCAL_AGENT_PORT=19000",
        "LOCAL_AGENT_LOG_FILE=logs/local_agent.log"
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText(
        $EnvFile,
        (($envLines -join [Environment]::NewLine) + [Environment]::NewLine),
        $utf8NoBom
    )

    Write-Host "Verifying source routes..."
    $verifyResult = & $PythonExe -c "from app.local_agent_main import create_local_agent_app, get_route_paths; routes=get_route_paths(create_local_agent_app()); print('/agent/version' in routes); print('/agent/wechat/search-result-debug' in routes); print(len(routes))"
    Write-Host $verifyResult

    Write-Host "Smoke testing built exe /health and /agent/version..."
    $smokeProcess = $null
    try {
        $smokeProcess = Start-Process -FilePath $OutputExe -WorkingDirectory $DistDir -PassThru -WindowStyle Hidden
        $health = $null
        $version = $null
        for ($i = 0; $i -lt 45; $i++) {
            if ($smokeProcess.HasExited) {
                Write-Host "Smoke failed: exe exited early with code $($smokeProcess.ExitCode)"
                exit 1
            }
            try {
                $health = Invoke-RestMethod "http://127.0.0.1:19000/health" -TimeoutSec 2
                $version = Invoke-RestMethod "http://127.0.0.1:19000/agent/version" -TimeoutSec 2
                break
            } catch {
                Start-Sleep -Seconds 1
            }
        }

        if ($null -eq $health -or $null -eq $version) {
            Write-Host "Smoke failed: /health or /agent/version did not respond"
            exit 1
        }
        if (-not $health.success) {
            Write-Host "Smoke failed: /health success=false"
            exit 1
        }
        if (-not ($version.routes -contains "/agent/version")) {
            Write-Host "Smoke failed: /agent/version route list missing /agent/version"
            exit 1
        }
        Write-Host "Smoke /health: OK"
        Write-Host "Smoke /agent/version: OK"
    }
    finally {
        if ($null -ne $smokeProcess -and -not $smokeProcess.HasExited) {
            Stop-Process -Id $smokeProcess.Id -Force
        }
    }

    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $OutputExe
    Write-Host ""
    Write-Host "=========================================="
    Write-Host "构建完成"
    Write-Host "=========================================="
    Write-Host "exe: $OutputExe"
    Write-Host "sha256: $($hash.Hash)"
    Write-Host "env: $EnvFile"
    Write-Host "log: $(Join-Path $DistDir 'logs\local_agent.log')"
    Write-Host "stop: powershell -NoProfile -ExecutionPolicy Bypass -File `"$StopScriptTarget`""
    Write-Host "start: double-click $OutputExe"
    Write-Host "health: Invoke-RestMethod http://127.0.0.1:19000/health"
    Write-Host "version: Invoke-RestMethod http://127.0.0.1:19000/agent/version"
    Write-Host "=========================================="

    # Phase 12 Task 8：构建 AI 剪辑 Worker（Python 3.11 独立 spec，不收进 local_agent.spec）
    if ($BuildWorker) {
        $WorkerBuildScript = Join-Path $PSScriptRoot "build_ai_edit_worker_exe.ps1"
        if (-not (Test-Path $WorkerBuildScript)) {
            throw "Worker 构建脚本缺失：$WorkerBuildScript"
        }
        Write-Host ""
        Write-Host "=========================================="
        Write-Host "构建 AI 剪辑 Worker（Python 3.11 独立运行时）"
        Write-Host "=========================================="
        & $WorkerBuildScript -Python311Exe $Python311Exe -FfmpegDir $FfmpegDir -ModelDir $ModelDir -FontDir $FontDir
        if ($LASTEXITCODE -ne 0) {
            throw "AI 剪辑 Worker 构建失败"
        }
    }
}
finally {
    Pop-Location
}
