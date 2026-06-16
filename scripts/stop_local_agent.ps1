param(
    [int]$Port = 19000,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$AssistantName = "小高AI微信助手"
$ScriptRootPath = (Resolve-Path $PSScriptRoot).Path

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Get-ListeningConnection {
    param([int]$TargetPort)
    try {
        return Get-NetTCPConnection -LocalAddress "127.0.0.1" -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue
    } catch {
        Write-Info "无法查询端口占用信息：$($_.Exception.Message)"
        Write-Info "请右键 PowerShell 以管理员身份运行。"
        exit 1
    }
}

function Get-ChildProcessIds {
    param([int[]]$ParentIds)
    $result = New-Object System.Collections.Generic.List[int]
    $queue = New-Object System.Collections.Generic.Queue[int]
    foreach ($id in $ParentIds) {
        $queue.Enqueue($id)
    }

    while ($queue.Count -gt 0) {
        $parentId = $queue.Dequeue()
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            if (-not $result.Contains([int]$child.ProcessId)) {
                $result.Add([int]$child.ProcessId)
                $queue.Enqueue([int]$child.ProcessId)
            }
        }
    }
    return $result.ToArray()
}

function Test-IsLocalAgentProcess {
    param($ProcessInfo)

    $name = [string]$ProcessInfo.Name
    $path = [string]$ProcessInfo.ExecutablePath
    $commandLine = [string]$ProcessInfo.CommandLine
    $combined = "$name $path $commandLine"

    if ($combined -like "*$AssistantName*") {
        return $true
    }
    if ($combined -like "*local_agent*") {
        return $true
    }
    if ($path -and $path.StartsWith($ScriptRootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $false
}

$connections = @(Get-ListeningConnection -TargetPort $Port)
if ($connections.Count -eq 0) {
    Write-Info "当前未检测到小高AI微信助手正在运行。"
    exit 0
}

$agentPids = @($connections | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($agentPid in $agentPids) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$agentPid" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        Write-Info "端口 $Port 的进程 PID=$agentPid 已不存在，跳过。"
        continue
    }

    $safeToStop = Test-IsLocalAgentProcess -ProcessInfo $processInfo
    if (-not $safeToStop -and -not $Force) {
        Write-Info "端口 $Port 当前被其他进程占用，未能确认是小高AI微信助手。"
        Write-Info "PID=$agentPid 进程=$($processInfo.Name)"
        Write-Info "为避免误杀其他程序，已停止操作。如确认需要强制停止，请追加 -Force。"
        exit 2
    }

    $childIds = @(Get-ChildProcessIds -ParentIds @([int]$agentPid))
    $stopIds = @($childIds + @([int]$agentPid) | Select-Object -Unique)
    [array]::Reverse($stopIds)

    foreach ($stopId in $stopIds) {
        try {
            Stop-Process -Id $stopId -Force -ErrorAction Stop
            Write-Info "已停止进程 PID=$stopId。"
        } catch {
            Write-Info "停止进程 PID=$stopId 失败：$($_.Exception.Message)"
            Write-Info "请右键 PowerShell 以管理员身份运行。"
            exit 1
        }
    }
}

Start-Sleep -Seconds 1
$remaining = @(Get-ListeningConnection -TargetPort $Port)
if ($remaining.Count -eq 0) {
    Write-Info "小高AI微信助手已停止，端口 $Port 已释放。"
    exit 0
}

Write-Info "已尝试停止小高AI微信助手，但端口 $Port 仍被占用。"
Write-Info "请右键 PowerShell 以管理员身份运行后重试。"
exit 1
