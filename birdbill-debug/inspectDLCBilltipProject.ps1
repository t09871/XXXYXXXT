# inspectDLCBilltipProject.ps1 | v0.1 | 2026-07-07 PDT | Birdbill Step 8 launcher for read-only DLC billtip project inspector

param(
    [string]$PythonPath = "D:\birdbill\.venv\Scripts\python.exe",
    [string]$ProjectRoot = "D:\birdbill",
    [string]$DlcProjectDir = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30",
    [string]$DlcConfig = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml",
    [string]$DlcPython = "C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe",
    [string]$TrainerSource = "D:\birdbill\app\billtipTrainerGUI.py"
)

$script_version = "v0.1"
$rewrite_step = "8"

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "script_name = inspectDLCBilltipProject.ps1"
Write-Host "script_version = $script_version"
Write-Host "rewrite_step = $rewrite_step"

$root = $ProjectRoot
$scriptPath = Join-Path $root "debug\inspectDLCBilltipProject.py"
$outRoot = Join-Path $root "output\debug"
$launcherStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$launcherLog = Join-Path $outRoot "inspectDLCBilltipProject-launcher-v0.1-$launcherStamp.log"
$launcherDir = Split-Path -Parent $launcherLog

New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

Write-Host "project_root = $root"
Write-Host "script_path = $scriptPath"
Write-Host "python_path = $PythonPath"
Write-Host "dlc_project_dir = $DlcProjectDir"
Write-Host "dlc_config = $DlcConfig"
Write-Host "dlc_python = $DlcPython"
Write-Host "trainer_source = $TrainerSource"
Write-Host "launcher_log = $launcherLog"
Write-Host "read_only = true"
Write-Host "inference_run = false"

$logLines = New-Object System.Collections.Generic.List[string]
$logLines.Add("script_name = inspectDLCBilltipProject.ps1")
$logLines.Add("script_version = $script_version")
$logLines.Add("rewrite_step = $rewrite_step")
$logLines.Add("project_root = $root")
$logLines.Add("script_path = $scriptPath")
$logLines.Add("python_path = $PythonPath")
$logLines.Add("dlc_project_dir = $DlcProjectDir")
$logLines.Add("dlc_config = $DlcConfig")
$logLines.Add("dlc_python = $DlcPython")
$logLines.Add("trainer_source = $TrainerSource")
$logLines.Add("read_only = true")
$logLines.Add("inference_run = false")

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

if (-not (Test-Path -LiteralPath $DlcProjectDir)) {
    Write-Host "missing_dlc_project_dir = $DlcProjectDir"
    $logLines.Add("missing_dlc_project_dir = $DlcProjectDir")
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

if (-not (Test-Path -LiteralPath $TrainerSource)) {
    Write-Host "warning_missing_trainer_source = $TrainerSource"
    $logLines.Add("warning_missing_trainer_source = $TrainerSource")
}

if ($precheckFailed) {
    $logLines.Add("status = FAIL")
    $logLines.Add("database_mutation = false")
    $logLines.Add("durable_evidence_written = false")
    $logLines.Add("media_files_written = 0")
    $logLines | Set-Content -LiteralPath $launcherLog -Encoding UTF8
    Write-Host "status = FAIL"
    Write-Host "launcher_log = $launcherLog"
    Write-Host "database_mutation = false"
    Write-Host "durable_evidence_written = false"
    Write-Host "media_files_written = 0"
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
    "--project-root", $root,
    "--dlc-project-dir", $DlcProjectDir,
    "--dlc-config", $DlcConfig,
    "--dlc-python", $DlcPython,
    "--trainer-source", $TrainerSource,
    "--output-root", $outRoot
)

Write-Host "command = `"$PythonPath`" `"$scriptPath`" --project-root `"$root`" --dlc-project-dir `"$DlcProjectDir`" --dlc-config `"$DlcConfig`" --dlc-python `"$DlcPython`" --trainer-source `"$TrainerSource`" --output-root `"$outRoot`""
$logLines.Add("command = `"$PythonPath`" `"$scriptPath`" --project-root `"$root`" --dlc-project-dir `"$DlcProjectDir`" --dlc-config `"$DlcConfig`" --dlc-python `"$DlcPython`" --trainer-source `"$TrainerSource`" --output-root `"$outRoot`"")
$logLines | Set-Content -LiteralPath $launcherLog -Encoding UTF8

& $PythonPath @commandArgs 2>&1 | Tee-Object -FilePath $launcherLog -Append
$exitCode = $LASTEXITCODE

Write-Host "python_exit_code = $exitCode"
Write-Host "launcher_log = $launcherLog"

Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "python_exit_code = $exitCode"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "read_only = true"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "inference_run = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "database_mutation = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "durable_evidence_written = false"
Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value "media_files_written = 0"

if ($exitCode -eq 0) {
    Write-Host "Step 8 DLC billtip project inspector PASS."
} else {
    Write-Host "Step 8 DLC billtip project inspector FAIL or PARTIAL."
}

Write-Host "read_only = true"
Write-Host "inference_run = false"
Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "media_files_written = 0"
Write-Host ""
Write-Host "Press Enter to close."
[void][System.Console]::ReadLine()

exit $exitCode
