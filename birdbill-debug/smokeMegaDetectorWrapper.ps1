# smokeMegaDetectorWrapper.ps1 | v0.3 | 2026-07-06 PDT | Step 4 thin launcher for MegaDetector wrapper smoke with balanced detector input selection

param(
    [string]$SamplerOutputDir = "",
    [int]$MaxDetectorInputFrames = 20,
    [double]$DetectorConfidenceThreshold = 0.05,
    [string]$CropExportMode = "animal_preview",
    [int]$MaxCropExportsTotal = 30,
    [int]$CropPaddingPx = 24,
    [int]$JpegQuality = 92,
    [double]$MaxBytesTotalMB = 250,
    [string]$Device = "cpu",
    [string]$SourceMediaContext = "debug_smoke",
    [string]$DetectorInputSelectionPolicy = "balanced_preview_sequence"
)

$ErrorActionPreference = "Stop"

$root = "D:\birdbill"
$debugDir = Join-Path $root "debug"
$outputDebugDir = Join-Path $root "output\debug"
$pythonRunner = Join-Path $debugDir "smokeMegaDetectorWrapper.py"
$py = "D:\birdbill\modules\megadetector\megadetector-env\Scripts\python.exe"
$modelPath = "D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt"
$expectedLauncherPath = Join-Path $debugDir "smokeMegaDetectorWrapper.ps1"
$actualLauncherPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $outputDebugDir "megadetector-wrapper-$timestamp"
$stdoutPath = Join-Path $outDir "megadetector-stdout.txt"
$stderrPath = Join-Path $outDir "megadetector-stderr.txt"
$launcherSummaryPath = Join-Path $outDir "megadetector-launcher-summary.txt"
$configPath = Join-Path $outDir "megadetector-smoke-config.json"

Write-Host ""
Write-Host "MegaDetector wrapper smoke test launcher"
Write-Host "script_version                 = v0.3"
Write-Host "rewrite_step                   = 4"
Write-Host "launcher_expected              = $expectedLauncherPath"
Write-Host "launcher_actual                = $actualLauncherPath"
Write-Host "python_runner                  = $pythonRunner"
Write-Host "project_root                   = $root"
Write-Host "python                         = $py"
Write-Host "model_path                     = $modelPath"
Write-Host "output_dir                     = $outDir"
Write-Host "database_mutation              = false"
Write-Host "durable_evidence_written       = false"
Write-Host "debug_outputs_purgeable        = true"
Write-Host "crop_exports_purgeable         = true"
Write-Host "source_media_context           = $SourceMediaContext"
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
    throw "Missing MegaDetector Python interpreter: $py"
}

if (-not (Test-Path $modelPath)) {
    throw "Missing MegaDetector model: $modelPath"
}

if ([string]::IsNullOrWhiteSpace($SamplerOutputDir)) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Select validated Smart Frame Sampler output folder"
    $dialog.ShowNewFolderButton = $false

    if (Test-Path $outputDebugDir) {
        $dialog.SelectedPath = $outputDebugDir
    }

    $result = $dialog.ShowDialog()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host "Smoke test cancelled: no sampler output folder selected."
        exit 1
    }

    $SamplerOutputDir = $dialog.SelectedPath
}

if (-not (Test-Path $SamplerOutputDir)) {
    throw "Sampler output folder does not exist: $SamplerOutputDir"
}

New-Item -ItemType Directory -Path $outDir -Force | Out-Null

$config = [ordered]@{
    tool = "smokeMegaDetectorWrapper.ps1"
    version = "v0.2"
    launcher_expected = $expectedLauncherPath
    launcher_actual = $actualLauncherPath
    project_root = $root
    python_runner = $pythonRunner
    python = $py
    model_path = $modelPath
    sampler_output_dir = $SamplerOutputDir
    output_dir = $outDir
    max_detector_input_frames = $MaxDetectorInputFrames
    detector_input_selection_policy = $DetectorInputSelectionPolicy
    detector_confidence_threshold = $DetectorConfidenceThreshold
    crop_export_mode = $CropExportMode
    max_crop_exports_total = $MaxCropExportsTotal
    crop_padding_px = $CropPaddingPx
    jpeg_quality = $JpegQuality
    max_bytes_total_mb = $MaxBytesTotalMB
    device = $Device
    source_media_context = $SourceMediaContext
    database_mutation = $false
    durable_evidence_written = $false
    debug_outputs_are_purgeable = $true
    crop_exports_are_purgeable = $true
}

$config | ConvertTo-Json -Depth 8 | Set-Content -Path $configPath -Encoding UTF8

Write-Host "sampler_output_dir             = $SamplerOutputDir"
Write-Host "max_detector_input_frames      = $MaxDetectorInputFrames"
Write-Host "detector_input_selection_policy= $DetectorInputSelectionPolicy"
Write-Host "detector_confidence_threshold  = $DetectorConfidenceThreshold"
Write-Host "crop_export_mode               = $CropExportMode"
Write-Host "max_crop_exports_total         = $MaxCropExportsTotal"
Write-Host "crop_padding_px                = $CropPaddingPx"
Write-Host "jpeg_quality                   = $JpegQuality"
Write-Host "max_bytes_total_mb             = $MaxBytesTotalMB"
Write-Host "device                         = $Device"
Write-Host "source_media_context           = $SourceMediaContext"
Write-Host "config_path                    = $configPath"
Write-Host ""

$env:BIRDBILL_MD_WRAPPER_CONFIG = $configPath
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
    Remove-Item Env:\BIRDBILL_MD_WRAPPER_CONFIG -ErrorAction SilentlyContinue
}

$status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }

$summary = @()
$summary += "smokeMegaDetectorWrapper.ps1 | v0.3 | 2026-07-06 PDT"
$summary += "status = $status"
$summary += "rewrite_step = 4"
$summary += "database_mutation = false"
$summary += "durable_evidence_written = false"
$summary += "debug_outputs_are_purgeable = true"
$summary += "crop_exports_are_purgeable = true"
$summary += "launcher_expected = $expectedLauncherPath"
$summary += "launcher_actual = $actualLauncherPath"
$summary += "project_root = $root"
$summary += "python = $py"
$summary += "python_runner = $pythonRunner"
$summary += "model_path = $modelPath"
$summary += "sampler_output_dir = $SamplerOutputDir"
$summary += "output_dir = $outDir"
$summary += "source_media_context = $SourceMediaContext"
$summary += "detector_input_selection_policy = $DetectorInputSelectionPolicy"
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
Write-Host "MegaDetector wrapper smoke status: $status"
Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
Write-Host "debug_outputs_are_purgeable = true"
Write-Host "launcher_summary = $launcherSummaryPath"
Write-Host "manifest = $(Join-Path $outDir 'manifest.json')"
Write-Host "detections = $(Join-Path $outDir 'megadetector-detections.csv')"
Write-Host "storage_ledger = $(Join-Path $outDir 'megadetector-storage-ledger.json')"
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
