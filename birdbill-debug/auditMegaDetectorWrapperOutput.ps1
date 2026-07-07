# auditMegaDetectorWrapperOutput.ps1 | v0.2 | 2026-07-06 PDT | Thin launcher for MegaDetector wrapper output audit

param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"

$root = "D:\birdbill"
$debugDir = Join-Path $root "debug"
$py = "D:\birdbill\.venv\Scripts\python.exe"
$pythonRunner = Join-Path $debugDir "auditMegaDetectorWrapperOutput.py"
$expectedLauncherPath = Join-Path $debugDir "auditMegaDetectorWrapperOutput.ps1"
$actualLauncherPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }

Write-Host ""
Write-Host "MegaDetector wrapper output audit launcher"
Write-Host "launcher_expected        = $expectedLauncherPath"
Write-Host "launcher_actual          = $actualLauncherPath"
Write-Host "python_runner            = $pythonRunner"
Write-Host "project_root             = $root"
Write-Host "python                   = $py"
Write-Host "database_mutation        = false"
Write-Host "durable_evidence_written = false"
Write-Host ""

if (-not (Test-Path $root)) {
    throw "Missing project root: $root"
}

if (-not (Test-Path $debugDir)) {
    throw "Missing debug folder: $debugDir"
}

if (-not (Test-Path $py)) {
    throw "Missing Python interpreter: $py"
}

if (-not (Test-Path $pythonRunner)) {
    throw "Missing Python audit runner: $pythonRunner"
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select MegaDetector wrapper output folder to audit"
    $dialog.ShowNewFolderButton = $false

    $defaultParent = Join-Path $root "output\debug"
    if (Test-Path $defaultParent) {
        $dialog.SelectedPath = $defaultParent
    }

    $result = $dialog.ShowDialog()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host "Audit cancelled: no folder selected."
        exit 1
    }

    $OutputDir = $dialog.SelectedPath
}

if (-not (Test-Path $OutputDir)) {
    throw "Selected output folder does not exist: $OutputDir"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$configPath = Join-Path $OutputDir "megadetector-output-audit-config-$timestamp.json"
$stdoutPath = Join-Path $OutputDir "megadetector-output-audit-stdout-$timestamp.txt"
$stderrPath = Join-Path $OutputDir "megadetector-output-audit-stderr-$timestamp.txt"
$launcherSummaryPath = Join-Path $OutputDir "megadetector-output-audit-launcher-summary-$timestamp.txt"

$auditConfig = [ordered]@{
    tool = "auditMegaDetectorWrapperOutput.ps1"
    version = "v0.2"
    launcher_expected = $expectedLauncherPath
    launcher_actual = $actualLauncherPath
    project_root = $root
    python = $py
    python_runner = $pythonRunner
    output_dir = $OutputDir
    database_mutation = $false
    durable_evidence_written = $false
}

$auditConfig | ConvertTo-Json -Depth 8 | Set-Content -Path $configPath -Encoding UTF8

Write-Host "output_dir               = $OutputDir"
Write-Host "config_path              = $configPath"
Write-Host "stdout_path              = $stdoutPath"
Write-Host "stderr_path              = $stderrPath"
Write-Host ""

$env:BIRDBILL_MEGAAUDIT_CONFIG = $configPath
$exitCode = 999

try {
    & $py $pythonRunner 1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE
}
catch {
    $exitCode = 998
    $_ | Out-File -FilePath $stderrPath -Encoding utf8
}
finally {
    Remove-Item Env:\BIRDBILL_MEGAAUDIT_CONFIG -ErrorAction SilentlyContinue
}

$status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }

$summary = @()
$summary += "auditMegaDetectorWrapperOutput.ps1 | v0.2 | 2026-07-06 PDT"
$summary += "status = $status"
$summary += "database_mutation = false"
$summary += "durable_evidence_written = false"
$summary += "launcher_expected = $expectedLauncherPath"
$summary += "launcher_actual = $actualLauncherPath"
$summary += "project_root = $root"
$summary += "python = $py"
$summary += "python_runner = $pythonRunner"
$summary += "output_dir = $OutputDir"
$summary += "config_path = $configPath"
$summary += "stdout_path = $stdoutPath"
$summary += "stderr_path = $stderrPath"
$summary += "python_exit_code = $exitCode"
$summary += ""
$summary += "stdout:"
if (Test-Path $stdoutPath) {
    $summary += Get-Content $stdoutPath
}
$summary += ""
$summary += "stderr:"
if (Test-Path $stderrPath) {
    $summary += Get-Content $stderrPath
}

$summary | Out-File -FilePath $launcherSummaryPath -Encoding utf8

Write-Host "Audit status: $status"
Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "launcher_summary = $launcherSummaryPath"
Write-Host ""

if (Test-Path $stdoutPath) {
    Get-Content $stdoutPath | ForEach-Object { Write-Host $_ }
}

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "stderr:"
    if (Test-Path $stderrPath) {
        Get-Content $stderrPath | ForEach-Object { Write-Host $_ }
    }
}

exit $exitCode
