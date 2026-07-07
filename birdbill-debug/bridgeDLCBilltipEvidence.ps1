# bridgeDLCBilltipEvidence.ps1 | v0.1 | 2026-07-07 PDT | Birdbill Step 9 launcher for DLC billtip evidence/schema bridge preview

param(
    [string]$PythonPath = "D:\birdbill\.venv\Scripts\python.exe",
    [string]$ProjectRoot = "D:\birdbill",
    [string]$OutputRoot = "D:\birdbill\output\debug",
    [string]$DlcRecordsCsv = "",
    [string]$Step8ReportJson = "",
    [string]$TrainerSource = "D:\birdbill\app\billtipTrainerGUI.py"
)

$script_version = "v0.1"
$rewrite_step = "9"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "script_name = bridgeDLCBilltipEvidence.ps1"
Write-Host "script_version = $script_version"
Write-Host "rewrite_step = $rewrite_step"

$root = $ProjectRoot
$scriptPath = Join-Path $root "debug\bridgeDLCBilltipEvidence.py"
$launcherStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$launcherLog = Join-Path $OutputRoot "bridgeDLCBilltipEvidence-launcher-v0.1-$launcherStamp.log"
$launcherDir = Split-Path -Parent $launcherLog

New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

Write-Host "project_root = $root"
Write-Host "script_path = $scriptPath"
Write-Host "python_path = $PythonPath"
Write-Host "output_root = $OutputRoot"
Write-Host "dlc_records_csv = $DlcRecordsCsv"
Write-Host "step8_report_json = $Step8ReportJson"
Write-Host "trainer_source = $TrainerSource"
Write-Host "launcher_log = $launcherLog"
Write-Host "inference_run = false"
Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "media_files_written = 0"

$logLines = New-Object System.Collections.Generic.List[string]
$logLines.Add("script_name = bridgeDLCBilltipEvidence.ps1")
$logLines.Add("script_version = $script_version")
$logLines.Add("rewrite_step = $rewrite_step")
$logLines.Add("project_root = $root")
$logLines.Add("script_path = $scriptPath")
$logLines.Add("python_path = $PythonPath")
$logLines.Add("output_root = $OutputRoot")
$logLines.Add("dlc_records_csv = $DlcRecordsCsv")
$logLines.Add("step8_report_json = $Step8ReportJson")
$logLines.Add("trainer_source = $TrainerSource")
$logLines.Add("inference_run = false")
$logLines.Add("database_mutation = false")
$logLines.Add("durable_evidence_written = false")
$logLines.Add("media_files_written = 0")

$precheckFailed = $false

if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "missing_project_root = $root"
    $logLines.Add("missing_project_root = $root")
    $precheckFailed = $true
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
    Write-Host "missing_script_path = $scriptPath"
    $logLines.Add("missing_script_path = $scriptPath")
    $precheckFailed = $true
}

if (-not (Test-Path -LiteralPath $PythonPath)) {
    Write-Host "missing_python_path = $PythonPath"
    $logLines.Add("missing_python_path = $PythonPath")
    $precheckFailed = $true
}

if (-not (Test-Path -LiteralPath $OutputRoot)) {
    Write-Host "missing_output_root = $OutputRoot"
    $logLines.Add("missing_output_root = $OutputRoot")
    $precheckFailed = $true
}

if ($TrainerSource -and -not (Test-Path -LiteralPath $TrainerSource)) {
    Write-Host "warning_missing_trainer_source = $TrainerSource"
    $logLines.Add("warning_missing_trainer_source = $TrainerSource")
}

if ($precheckFailed) {
    $logLines.Add("status = FAIL")
    $logLines | Set-Content -LiteralPath $launcherLog -Encoding UTF8
    Write-Host "status = FAIL"
    Write-Host "launcher_log = $launcherLog"
    Write-Host "inference_run = false"
    Write-Host "database_mutation = false"
    Write-Host "durable_evidence_written = false"
    Write-Host "media_files_written = 0"
    exit 1
}

$corePythonVersion = & $PythonPath --version 2>&1
Write-Host "core_python_version = $corePythonVersion"
$logLines.Add("core_python_version = $corePythonVersion")

$commandArgs = @(
    $scriptPath,
    "--project-root", $root,
    "--output-root", $OutputRoot,
    "--trainer-source", $TrainerSource
)

if ($DlcRecordsCsv -ne "") {
    $commandArgs += @("--dlc-records-csv", $DlcRecordsCsv)
}

if ($Step8ReportJson -ne "") {
    $commandArgs += @("--step8-report-json", $Step8ReportJson)
}

Write-Host "command = `"$PythonPath`" `"$scriptPath`" --project-root `"$root`" --output-root `"$OutputRoot`" --trainer-source `"$TrainerSource`""
$logLines.Add("command = `"$PythonPath`" `"$scriptPath`" --project-root `"$root`" --output-root `"$OutputRoot`" --trainer-source `"$TrainerSource`"")
$logLines | Set-Content -LiteralPath $launcherLog -Encoding UTF8

& $PythonPath @commandArgs 2>&1 | Tee-Object -FilePath $launcherLog -Append
$exitCode = $LASTEXITCODE

Write-Host "python_exit_code = $exitCode"
Write-Host "launcher_log = $launcherLog"

Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "python_exit_code = $exitCode"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "inference_run = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "database_mutation = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "durable_evidence_written = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "media_files_written = 0"

if ($exitCode -eq 0) {
    Write-Host "Step 9 DLC billtip evidence/schema bridge PASS."
} else {
    Write-Host "Step 9 DLC billtip evidence/schema bridge FAIL."
}

Write-Host "inference_run = false"
Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "media_files_written = 0"
Write-Host ""
Write-Host "Press Enter to close."
[void][System.Console]::ReadLine()

exit $exitCode
