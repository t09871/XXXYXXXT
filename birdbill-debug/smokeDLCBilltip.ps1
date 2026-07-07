# smokeDLCBilltip.ps1 | v0.6 | 2026-07-07 PDT | Birdbill Step 6 launcher for DLC billtip smoke with project-root sanitized working config

param(
    [string]$PythonPath = "D:\birdbill\.venv\Scripts\python.exe",
    [string]$ProjectRoot = "D:\birdbill",
    [string]$CandidatesCsv = "D:\birdbill\output\debug\retention-crop-scoring-20260706-223423\bird-candidates.csv",
    [string]$DlcConfig = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml",
    [string]$DlcPython = "C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe",
    [int]$MaxCandidates = 25
)

$script_version = "v0.6"
$rewrite_step = "6"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "script_name = smokeDLCBilltip.ps1"
Write-Host "script_version = $script_version"
Write-Host "rewrite_step = $rewrite_step"

$root = $ProjectRoot
$scriptPath = Join-Path $root "debug\smokeDLCBilltip.py"
$outRoot = Join-Path $root "output\debug"
$launcherStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$launcherLog = Join-Path $outRoot "smokeDLCBilltip-launcher-v0.6-$launcherStamp.log"
$launcherDir = Split-Path -Parent $launcherLog

New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

Write-Host "project_root = $root"
Write-Host "script_path = $scriptPath"
Write-Host "python_path = $PythonPath"
Write-Host "candidates_csv = $CandidatesCsv"
Write-Host "dlc_config = $DlcConfig"
Write-Host "dlc_python = $DlcPython"
Write-Host "max_candidates = $MaxCandidates"
Write-Host "launcher_log = $launcherLog"

$logLines = New-Object System.Collections.Generic.List[string]
$logLines.Add("script_name = smokeDLCBilltip.ps1")
$logLines.Add("script_version = $script_version")
$logLines.Add("rewrite_step = $rewrite_step")
$logLines.Add("project_root = $root")
$logLines.Add("script_path = $scriptPath")
$logLines.Add("python_path = $PythonPath")
$logLines.Add("candidates_csv = $CandidatesCsv")
$logLines.Add("dlc_config = $DlcConfig")
$logLines.Add("dlc_python = $DlcPython")
$logLines.Add("max_candidates = $MaxCandidates")

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

if (-not (Test-Path -LiteralPath $CandidatesCsv)) {
    Write-Host "missing_candidates_csv = $CandidatesCsv"
    $logLines.Add("missing_candidates_csv = $CandidatesCsv")
    $precheckFailed = $true
}

if (-not (Test-Path -LiteralPath $DlcConfig)) {
    Write-Host "missing_dlc_config = $DlcConfig"
    $logLines.Add("missing_dlc_config = $DlcConfig")
    $precheckFailed = $true
}

if (-not (Test-Path -LiteralPath $DlcPython)) {
    Write-Host "missing_dlc_python = $DlcPython"
    $logLines.Add("missing_dlc_python = $DlcPython")
    $precheckFailed = $true
}

if ($precheckFailed) {
    $logLines.Add("status = FAIL")
    $logLines | Set-Content -LiteralPath $launcherLog -Encoding UTF8
    Write-Host "status = FAIL"
    Write-Host "launcher_log = $launcherLog"
    Write-Host "database_mutation = false"
    Write-Host "durable_evidence_written = false"
    Write-Host "broad_media_export = false"
    exit 1
}

$corePythonVersion = & $PythonPath --version 2>&1
$dlcPythonVersion = & $DlcPython --version 2>&1

Write-Host "core_python_version = $corePythonVersion"
Write-Host "dlc_python_version = $dlcPythonVersion"

$logLines.Add("core_python_version = $corePythonVersion")
$logLines.Add("dlc_python_version = $dlcPythonVersion")

$commandArgs = @(
    $scriptPath,
    "--candidates-csv", $CandidatesCsv,
    "--dlc-config", $DlcConfig,
    "--dlc-python", $DlcPython,
    "--output-root", $outRoot,
    "--max-candidates", "$MaxCandidates"
)

Write-Host "command = `"$PythonPath`" `"$scriptPath`" --candidates-csv `"$CandidatesCsv`" --dlc-config `"$DlcConfig`" --dlc-python `"$DlcPython`" --output-root `"$outRoot`" --max-candidates $MaxCandidates"
$logLines.Add("command = `"$PythonPath`" `"$scriptPath`" --candidates-csv `"$CandidatesCsv`" --dlc-config `"$DlcConfig`" --dlc-python `"$DlcPython`" --output-root `"$outRoot`" --max-candidates $MaxCandidates")
$logLines | Set-Content -LiteralPath $launcherLog -Encoding UTF8

& $PythonPath @commandArgs 2>&1 | Tee-Object -FilePath $launcherLog -Append
$exitCode = $LASTEXITCODE

Write-Host "python_exit_code = $exitCode"
Write-Host "launcher_log = $launcherLog"

Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "python_exit_code = $exitCode"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "database_mutation = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "durable_evidence_written = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "broad_media_export = false"

if ($exitCode -eq 0) {
    Write-Host "Step 6 DLC billtip smoke PASS."
} else {
    Write-Host "Step 6 DLC billtip smoke FAIL."
}

Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "broad_media_export = false"
Write-Host ""
Write-Host "Press Enter to close."
[void][System.Console]::ReadLine()

exit $exitCode
