$PythonExe = "python"
if ($args.Count -ge 2 -and $args[0] -eq "-PythonExe") {
    $PythonExe = $args[1]
}

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EntryFile = Join-Path $ProjectRoot "app\local_agent_exe_entry.py"
$BuildInfoFile = Join-Path $ProjectRoot "app\local_agent_build_info.py"
$AppName = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("5bCP6auYQUnlvq7kv6HliqnmiYs="))
$DistDir = Join-Path $ProjectRoot ("dist\{0}" -f $AppName)
$OutputExe = Join-Path $DistDir ("{0}.exe" -f $AppName)
$ModelSourceRelative = "resources\easyocr_models"
$ModelSource = Join-Path $ProjectRoot $ModelSourceRelative
$ModelTarget = Join-Path $DistDir "models\easyocr"

# 预期输出：dist\小高AI微信助手\小高AI微信助手.exe
# 如果缺少模型，请先运行：python scripts\prepare_easyocr_models.py
# 分发时请复制完整 dist\小高AI微信助手\ 目录，不要只复制 exe。

# ============================================================
# 1. 生成版本戳
# ============================================================

$BuildVersion = "P0-4A-6B-3"
$BuildTime = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")

$GitCommit = "unknown"
try {
    $GitCommit = & git rev-parse --short HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { $GitCommit = "unknown" }
} catch {
    $GitCommit = "unknown"
}

Write-Host "Generating build info: $BuildInfoFile"
# Use ASCII-only docstring to avoid encoding issues with Out-File
$buildInfoContent = @"
""""""
Local Agent build info - auto generated.
""""

BUILD_VERSION = "$BuildVersion"
BUILD_TIME = "$BuildTime"
GIT_COMMIT = "$GitCommit"
"@
[System.IO.File]::WriteAllText($BuildInfoFile, $buildInfoContent, [System.Text.Encoding]::UTF8)

Write-Host "BUILD_VERSION: $BuildVersion"
Write-Host "BUILD_TIME: $BuildTime"
Write-Host "GIT_COMMIT: $GitCommit"

# ============================================================
# 2. 检查环境
# ============================================================

Write-Host "Checking Python environment..."
& $PythonExe --version

Write-Host "Checking PyInstaller..."
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pyinstallerCheck = & $PythonExe -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
$pyinstallerExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($pyinstallerExitCode -ne 0) {
    Write-Host "PyInstaller is missing. Please run: pip install pyinstaller"
    exit 1
}
Write-Host "PyInstaller version: $pyinstallerCheck"

Write-Host "Checking EasyOCR model directory: $ModelSource"
if (-not (Test-Path $ModelSource)) {
    Write-Host "Missing $ModelSourceRelative"
    Write-Host "Please run first: python scripts\prepare_easyocr_models.py"
    exit 1
}

$modelFiles = Get-ChildItem -Path $ModelSource -Recurse -File
if ($modelFiles.Count -eq 0) {
    Write-Host "EasyOCR model directory is empty: $ModelSource"
    Write-Host "Please run first: python scripts\prepare_easyocr_models.py"
    exit 1
}
$modelSizeMb = [Math]::Round((($modelFiles | Measure-Object -Property Length -Sum).Sum / 1MB), 2)
Write-Host "Model source: $ModelSource"
Write-Host "Model file count: $($modelFiles.Count)"
Write-Host "Model total size: $modelSizeMb MB"

# ============================================================
# 3. PyInstaller 打包
# ============================================================

Write-Host "Building $AppName.exe (version $BuildVersion)..."
Push-Location $ProjectRoot
try {
    & $PythonExe -m PyInstaller `
        --name $AppName `
        --onedir `
        --console `
        --noconfirm `
        --collect-all easyocr `
        --collect-all torch `
        --collect-all torchvision `
        --collect-all PIL `
        --collect-all cv2 `
        "app\local_agent_exe_entry.py"
}
finally {
    Pop-Location
}

if (-not (Test-Path $OutputExe)) {
    Write-Host "Build failed: output exe not found: $OutputExe"
    exit 1
}

# ============================================================
# 4. 复制 OCR 模型
# ============================================================

Write-Host "Copying EasyOCR models to: $ModelTarget"
New-Item -ItemType Directory -Force -Path $ModelTarget | Out-Null
Copy-Item -Path (Join-Path $ModelSource "*") -Destination $ModelTarget -Recurse -Force

$copiedFiles = Get-ChildItem -Path $ModelTarget -Recurse -File
$copiedSizeMb = [Math]::Round((($copiedFiles | Measure-Object -Property Length -Sum).Sum / 1MB), 2)
Write-Host "Model target: $ModelTarget"
Write-Host "Copied model file count: $($copiedFiles.Count)"
Write-Host "Copied model total size: $copiedSizeMb MB"

# ============================================================
# 5. 验证路由包含 search-result-debug
# ============================================================

Write-Host "Verifying routes in built exe..."
$verifyResult = & $PythonExe -c "
import sys
sys.path.insert(0, r'$ProjectRoot')
from app.local_agent_main import create_local_agent_app, get_route_paths
app = create_local_agent_app()
routes = get_route_paths(app)
found = '/agent/wechat/search-result-debug' in routes
found_version = '/agent/version' in routes
print(f'routes_count={len(routes)}')
print(f'search_result_debug={found}')
print(f'agent_version={found_version}')
for r in routes:
    print(f'  route: {r}')
" 2>&1
Write-Host $verifyResult

# ============================================================
# 6. 完成
# ============================================================

Write-Host ""
Write-Host "=========================================="
Write-Host "构建完成"
Write-Host "=========================================="
Write-Host "build_version: $BuildVersion"
Write-Host "build_time: $BuildTime"
Write-Host "git_commit: $GitCommit"
Write-Host "输出目录: $DistDir"
Write-Host "exe: $OutputExe"
Write-Host "模型大小: $copiedSizeMb MB"
Write-Host ""
Write-Host "分发步骤："
Write-Host "  1. 结束目标电脑上旧的小高AI微信助手.exe 进程"
Write-Host "  2. 删除旧目录"
Write-Host "  3. 复制完整 dist\$AppName\ 目录"
Write-Host "  4. 启动新 $AppName.exe"
Write-Host "  5. 检查控制台确认 版本：$BuildVersion"
Write-Host "=========================================="
