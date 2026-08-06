$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$dashboardUrl = "http://127.0.0.1:8000/"
$logDir = Join-Path $projectRoot "logs"
$stdoutLog = Join-Path $logDir "dashboard.out.log"
$stderrLog = Join-Path $logDir "dashboard.error.log"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Test-Dashboard {
    try {
        $response = Invoke-WebRequest -Uri $dashboardUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match "每日AI岗位精读"
    } catch {
        return $false
    }
}

if (-not (Test-Dashboard)) {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show("没有找到本机运行环境：$python", "AI岗位面板") | Out-Null
        exit 1
    }

    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "job_matcher.web:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog

    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-Dashboard) {
            break
        }
    }
}

if (Test-Dashboard) {
    Start-Process $dashboardUrl
    exit 0
}

$errorText = "本机面板启动失败。错误日志：$stderrLog"
if (Test-Path -LiteralPath $stderrLog) {
    $tail = (Get-Content -LiteralPath $stderrLog -Tail 8 -ErrorAction SilentlyContinue) -join [Environment]::NewLine
    if ($tail) {
        $errorText += [Environment]::NewLine + [Environment]::NewLine + $tail
    }
}
Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show($errorText, "AI岗位面板") | Out-Null
exit 1
