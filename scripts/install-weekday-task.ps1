param(
    [string]$ResumePath = "",
    [string]$TaskName = "AIJobMatcherWeekdays"
)

$ErrorActionPreference = "Stop"
$runner = Join-Path $PSScriptRoot "run-weekday.ps1"
if ($ResumePath -and -not (Test-Path -LiteralPath $ResumePath)) {
    throw "Resume file not found: $ResumePath"
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
if ($ResumePath) { $arguments += " -ResumePath `"$ResumePath`"" }
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Read-only AI job matching report on weekdays" -Force
Write-Output "Scheduled task installed: $TaskName"
