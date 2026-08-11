param(
    [string]$ResumePath = $env:JOB_MATCHER_RESUME,
    [string]$Address = "",
    [int]$Pages = 2
)

$ErrorActionPreference = "Stop"
if ((Get-Date).DayOfWeek -in @("Saturday", "Sunday")) {
    Write-Output "Weekend: skipped."
    exit 0
}

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Run: python -m venv .venv"
}
if ($ResumePath -and -not (Test-Path -LiteralPath $ResumePath)) {
    throw "Resume file not found: $ResumePath"
}

$reportDate = Get-Date -Format "yyyy-MM-dd"
$candidateOutput = Join-Path $projectRoot "reports\$reportDate-candidates.json"
Push-Location $projectRoot
try {
    & $python -m job_matcher.zhilian_validation --report-date $reportDate
    if ($LASTEXITCODE -ne 0) { throw "Zhilian validation failed." }
    $dailyArgs = @("-m", "job_matcher.daily_report", "--pages", $Pages, "--report-date", $reportDate, "--prepare-output", $candidateOutput)
    if ($ResumePath) { $dailyArgs += @("--resume", $ResumePath) }
    if ($Address) { $dailyArgs += @("--address", $Address) }
    & $python @dailyArgs
    if ($LASTEXITCODE -ne 0) { throw "Candidate preparation failed." }
    Write-Output "Candidates: $candidateOutput"
    Write-Output "Prompt: $([IO.Path]::ChangeExtension($candidateOutput, '.prompt.md'))"
    Write-Output "Next: create the greetings JSON, then run the final render command documented in README.md."
} finally {
    Pop-Location
}
