# smokeRetentionCropScoring.ps1 | v0.1 | 2026-07-06 PDT | Step 5 thin launcher for retention/crop scoring smoke

param(
    [string]$MegaDetectorOutputDir = "",
    [string]$ScoringPolicy = "v0.1_conservative_detector_crop_score"
)

$ErrorActionPreference = "Stop"

$scriptVersion = "v0.1"
$rewriteStep = 5
$root = "D:\birdbill"
$debugDir = Join-Path $root "debug"
$outputDebugDir = Join-Path $root "output\debug"
$pythonRunner = Join-Path $debugDir "smokeRetentionCropScoring.py"
$py = "D:\birdbill\.venv\Scripts\python.exe"
$expectedLauncherPath = Join-Path $debugDir "smokeRetentionCropScoring.ps1"
$actualLauncherPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $outputDebugDir "retention-crop-scoring-$timestamp"
$stdoutPath = Join-Path $outDir "retention-stdout.txt"
$stderrPath = Join-Path $outDir "retention-stderr.txt"
$launcherSummaryPath = Join-Path $outDir "retention-launcher-summary.txt"
$configPath = Join-Path $outDir "retention-smoke-config.json"

Write-Host ""
Write-Host "Retention / crop scoring smoke test launcher"
Write-Host "script_version              = $scriptVersion"
Write-Host "rewrite_step                = $rewriteStep"
Write-Host "launcher_expected           = $expectedLauncherPath"
Write-Host "launcher_actual             = $actualLauncherPath"
Write-Host "python_runner               = $pythonRunner"
Write-Host "project_root                = $root"
Write-Host "python                      = $py"
Write-Host "output_dir                  = $outDir"
Write-Host "database_mutation           = false"
Write-Host "durable_evidence_written    = false"
Write-Host "media_files_written         = 0"
Write-Host "debug_outputs_purgeable     = true"
Write-Host ""

if (-not (Test-Path $root)) {
    throw "Missing project root: $root"
}

if (-not (Test-Path $debugDir)) {
    throw "Missing debug folder: $debugDir"
}

if (-not (Test-Path $outputDebugDir)) {
    New-Item -ItemType Directory -Path $outputDebugDir -Force | Out-Null
}

if (-not (Test-Path $pythonRunner)) {
    throw "Missing Python runner: $pythonRunner"
}

if (-not (Test-Path $py)) {
    throw "Missing core Python interpreter: $py"
}

if ([string]::IsNullOrWhiteSpace($MegaDetectorOutputDir)) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select MegaDetector wrapper output folder for retention/crop scoring"
    $dialog.ShowNewFolderButton = $false

    if (Test-Path $outputDebugDir) {
        $dialog.SelectedPath = $outputDebugDir
    }

    $result = $dialog.ShowDialog()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host "Smoke test cancelled: no MegaDetector output folder selected."
        exit 1
    }

    $MegaDetectorOutputDir = $dialog.SelectedPath
}

if (-not (Test-Path $MegaDetectorOutputDir)) {
    throw "MegaDetector output folder does not exist: $MegaDetectorOutputDir"
}

New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$config = [ordered]@{
    tool = "smokeRetentionCropScoring.ps1"
    version = $scriptVersion
    rewrite_step = $rewriteStep
    launcher_expected = $expectedLauncherPath
    launcher_actual = $actualLauncherPath
    project_root = $root
    python_runner = $pythonRunner
    python = $py
    megadetector_output_dir = $MegaDetectorOutputDir
    output_dir = $outDir
    scoring_policy = $ScoringPolicy
    database_mutation = $false
    durable_evidence_written = $false
    media_files_written = 0
    debug_outputs_are_purgeable = $true
}

$config | ConvertTo-Json -Depth 8 | Set-Content -Path $configPath -Encoding UTF8

Write-Host "megadetector_output_dir    = $MegaDetectorOutputDir"
Write-Host "scoring_policy             = $ScoringPolicy"
Write-Host "config_path                = $configPath"
Write-Host ""

$env:BIRDBILL_RETENTION_CONFIG = $configPath
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
    Remove-Item Env:\BIRDBILL_RETENTION_CONFIG -ErrorAction SilentlyContinue
}

$status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }

$summary = @()
$summary += "smokeRetentionCropScoring.ps1 | $scriptVersion | 2026-07-06 PDT"
$summary += "status = $status"
$summary += "rewrite_step = $rewriteStep"
$summary += "database_mutation = false"
$summary += "durable_evidence_written = false"
$summary += "media_files_written = 0"
$summary += "debug_outputs_are_purgeable = true"
$summary += "launcher_expected = $expectedLauncherPath"
$summary += "launcher_actual = $actualLauncherPath"
$summary += "project_root = $root"
$summary += "python = $py"
$summary += "python_runner = $pythonRunner"
$summary += "megadetector_output_dir = $MegaDetectorOutputDir"
$summary += "output_dir = $outDir"
$summary += "scoring_policy = $ScoringPolicy"
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

Write-Host ""
Write-Host "Retention / crop scoring smoke status: $status"
Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "media_files_written = 0"
Write-Host "launcher_summary = $launcherSummaryPath"
Write-Host "manifest = $(Join-Path $outDir 'manifest.json')"
Write-Host "retention_scores = $(Join-Path $outDir 'retention-scores.csv')"
Write-Host "bird_candidates = $(Join-Path $outDir 'bird-candidates.csv')"
Write-Host "context_detections = $(Join-Path $outDir 'context-detections.csv')"
Write-Host "storage_ledger = $(Join-Path $outDir 'retention-storage-ledger.json')"
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
