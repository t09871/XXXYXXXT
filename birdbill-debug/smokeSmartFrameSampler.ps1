# smokeSmartFrameSampler.ps1 | v0.5 | 2026-07-06 PDT | Thin launcher for storage-disciplined Smart Frame Sampler smoke test

param(
    [Parameter(Position = 0)]
    [string]$VideoPath = "",

    [double]$SampleEverySeconds = 5.0,
    [int]$MaxSequences = 8,
    [double]$SequencePreSeconds = 0.25,
    [double]$SequencePostSeconds = 0.75,
    [int]$SequenceStrideFrames = 1,
    [int]$JpegQuality = 92,

    [ValidateSet("metadata_only", "preview", "bounded_sequence_cache")]
    [string]$StorageMode = "preview",
    [int]$MaxPreviewFramesTotal = 40,
    [int]$PreviewFramesPerSequence = 3,
    [int]$MaxCacheFramesTotal = 250,
    [double]$MaxBytesTotalMB = 250.0,

    [string]$SessionId = "",
    [string]$CameraId = "camera-unknown-01",
    [string]$CameraFileId = "",
    [string]$CameraRole = "primary_unknown",
    [string]$LocationId = "unknown",
    [string]$EvidenceMode = "normal_single_camera",
    [string]$EvidencePurpose = "sampler_smoke",

    [string]$FeederReferenceId = "unknown",
    [string]$FeederReferenceStatus = "not_checked",
    [string]$LocalScaleReferenceType = "feeder_assembly",
    [string]$LocalScaleConfidence = "unknown",
    [string]$CalibrationStateId = "",
    [string]$CalibrationStatus = "not_checked",
    [string]$MarkerStatus = "not_checked",
    [string]$SyncStatus = "unsynced",

    [switch]$ContactSheet
)

$ErrorActionPreference = "Stop"

$root = "D:\birdbill"
$debugDir = Join-Path $root "debug"
$outputDebugDir = Join-Path $root "output\debug"
$py = "D:\birdbill\.venv\Scripts\python.exe"
$script = Join-Path $debugDir "smokeSmartFrameSampler.py"
$expectedLauncherPath = Join-Path $debugDir "smokeSmartFrameSampler.ps1"
$actualLauncherPath = if ($PSCommandPath) { $PSCommandPath } else { $MyInvocation.MyCommand.Path }
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $outputDebugDir "smart-frame-sampler-$timestamp"
$stdoutPath = Join-Path $outDir "python-stdout.txt"
$stderrPath = Join-Path $outDir "python-stderr.txt"
$summaryPath = Join-Path $outDir "smoke-summary.txt"
$configPath = Join-Path $outDir "smoke-config.json"
$previousConfigEnv = $env:BIRDBILL_SMOKE_CONFIG

Write-Host ""
Write-Host "Smart Frame Sampler smoke test launcher"
Write-Host "launcher_expected        = $expectedLauncherPath"
Write-Host "launcher_actual          = $actualLauncherPath"
Write-Host "python_runner            = $script"
Write-Host "project_root             = $root"
Write-Host "python                   = $py"
Write-Host "output_dir               = $outDir"
Write-Host "database_mutation        = false"
Write-Host "storage_mode             = $StorageMode"
Write-Host "debug_outputs_purgeable  = true"
Write-Host "durable_evidence_written = false"
Write-Host ""

if (-not (Test-Path $root)) {
    throw "Missing project root: $root"
}

if (-not (Test-Path $debugDir)) {
    throw "Missing debug script folder: $debugDir"
}

if (-not (Test-Path $outputDebugDir)) {
    New-Item -ItemType Directory -Path $outputDebugDir -Force | Out-Null
}

New-Item -ItemType Directory -Path $outDir -Force | Out-Null

if (-not (Test-Path $py)) {
    $summary = @()
    $summary += "smokeSmartFrameSampler.ps1 | v0.5 | 2026-07-06 PDT"
    $summary += "status = FAIL"
    $summary += "database_mutation = false"
    $summary += "failure_stage = launcher_preflight"
    $summary += "reason = missing core Python interpreter"
    $summary += "python = $py"
    $summary += "launcher_expected = $expectedLauncherPath"
    $summary += "launcher_actual = $actualLauncherPath"
    $summary += "python_runner = $script"
    $summary += "output_dir = $outDir"
    $summary | Out-File -FilePath $summaryPath -Encoding utf8

    Write-Host "Smoke test status: FAIL"
    Write-Host "Missing core Python interpreter: $py"
    Write-Host "summary = $summaryPath"
    exit 2
}

if (-not (Test-Path $script)) {
    $summary = @()
    $summary += "smokeSmartFrameSampler.ps1 | v0.5 | 2026-07-06 PDT"
    $summary += "status = FAIL"
    $summary += "database_mutation = false"
    $summary += "failure_stage = launcher_preflight"
    $summary += "reason = missing Python smoke runner"
    $summary += "python = $py"
    $summary += "launcher_expected = $expectedLauncherPath"
    $summary += "launcher_actual = $actualLauncherPath"
    $summary += "python_runner = $script"
    $summary += "output_dir = $outDir"
    $summary | Out-File -FilePath $summaryPath -Encoding utf8

    Write-Host "Smoke test status: FAIL"
    Write-Host "Missing Python smoke runner: $script"
    Write-Host "summary = $summaryPath"
    exit 3
}

if ([string]::IsNullOrWhiteSpace($VideoPath)) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select source video for Smart Frame Sampler smoke test"
    $dialog.Filter = "Video files (*.mp4;*.mov;*.m4v;*.avi;*.mkv)|*.mp4;*.mov;*.m4v;*.avi;*.mkv|All files (*.*)|*.*"
    $dialog.Multiselect = $false
    $result = $dialog.ShowDialog()

    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        $summary = @()
        $summary += "smokeSmartFrameSampler.ps1 | v0.5 | 2026-07-06 PDT"
        $summary += "status = CANCELLED"
        $summary += "database_mutation = false"
        $summary += "reason = no video selected"
        $summary += "launcher_expected = $expectedLauncherPath"
        $summary += "launcher_actual = $actualLauncherPath"
        $summary += "python_runner = $script"
        $summary += "project_root = $root"
        $summary += "python = $py"
        $summary += "output_dir = $outDir"
        $summary | Out-File -FilePath $summaryPath -Encoding utf8

        Write-Host "Smoke test cancelled: no video selected."
        Write-Host "summary = $summaryPath"
        exit 1
    }

    $VideoPath = $dialog.FileName
}

if (-not (Test-Path $VideoPath)) {
    $summary = @()
    $summary += "smokeSmartFrameSampler.ps1 | v0.5 | 2026-07-06 PDT"
    $summary += "status = FAIL"
    $summary += "database_mutation = false"
    $summary += "failure_stage = launcher_preflight"
    $summary += "reason = missing selected source video"
    $summary += "input_video = $VideoPath"
    $summary += "launcher_expected = $expectedLauncherPath"
    $summary += "launcher_actual = $actualLauncherPath"
    $summary += "python_runner = $script"
    $summary += "project_root = $root"
    $summary += "python = $py"
    $summary += "output_dir = $outDir"
    $summary | Out-File -FilePath $summaryPath -Encoding utf8

    Write-Host "Smoke test status: FAIL"
    Write-Host "Missing selected source video: $VideoPath"
    Write-Host "summary = $summaryPath"
    exit 4
}

Write-Host "input_video                = $VideoPath"
Write-Host "sample_every_seconds       = $SampleEverySeconds"
Write-Host "max_sequences              = $MaxSequences"
Write-Host "sequence_pre_seconds       = $SequencePreSeconds"
Write-Host "sequence_post_seconds      = $SequencePostSeconds"
Write-Host "sequence_stride_frames     = $SequenceStrideFrames"
Write-Host "jpeg_quality               = $JpegQuality"
Write-Host "storage_mode               = $StorageMode"
Write-Host "max_preview_frames_total   = $MaxPreviewFramesTotal"
Write-Host "preview_frames_per_sequence= $PreviewFramesPerSequence"
Write-Host "max_cache_frames_total     = $MaxCacheFramesTotal"
Write-Host "max_bytes_total_mb         = $MaxBytesTotalMB"
Write-Host "session_id                 = $SessionId"
Write-Host "camera_id                  = $CameraId"
Write-Host "camera_file_id             = $CameraFileId"
Write-Host "camera_role                = $CameraRole"
Write-Host "location_id                = $LocationId"
Write-Host "evidence_mode              = $EvidenceMode"
Write-Host "evidence_purpose           = $EvidencePurpose"
Write-Host "feeder_reference_id        = $FeederReferenceId"
Write-Host "feeder_reference_status    = $FeederReferenceStatus"
Write-Host "local_scale_reference_type = $LocalScaleReferenceType"
Write-Host "local_scale_confidence     = $LocalScaleConfidence"
Write-Host "calibration_state_id       = $CalibrationStateId"
Write-Host "calibration_status         = $CalibrationStatus"
Write-Host "marker_status              = $MarkerStatus"
Write-Host "sync_status                = $SyncStatus"
Write-Host "contact_sheet              = $($ContactSheet.IsPresent)"
Write-Host "config_path                = $configPath"
Write-Host ""

$config = [ordered]@{
    component = "Smart Frame Sampler"
    launcher_version = "v0.5"
    runner_version_expected = "v0.3"
    launcher_expected = $expectedLauncherPath
    launcher_actual = $actualLauncherPath
    python_runner = $script
    project_root = $root
    python = $py
    output_dir = $outDir
    source_video = $VideoPath
    sample_every_seconds = $SampleEverySeconds
    max_sequences = $MaxSequences
    sequence_pre_seconds = $SequencePreSeconds
    sequence_post_seconds = $SequencePostSeconds
    sequence_stride_frames = $SequenceStrideFrames
    jpeg_quality = $JpegQuality
    storage_mode = $StorageMode
    max_preview_frames_total = $MaxPreviewFramesTotal
    preview_frames_per_sequence = $PreviewFramesPerSequence
    max_cache_frames_total = $MaxCacheFramesTotal
    max_bytes_total_mb = $MaxBytesTotalMB
    session_id = $SessionId
    camera_id = $CameraId
    camera_file_id = $CameraFileId
    camera_role = $CameraRole
    location_id = $LocationId
    evidence_mode = $EvidenceMode
    evidence_purpose = $EvidencePurpose
    feeder_reference_id = $FeederReferenceId
    feeder_reference_status = $FeederReferenceStatus
    local_scale_reference_type = $LocalScaleReferenceType
    local_scale_confidence = $LocalScaleConfidence
    calibration_state_id = $CalibrationStateId
    calibration_status = $CalibrationStatus
    marker_status = $MarkerStatus
    sync_status = $SyncStatus
    contact_sheet = [bool]$ContactSheet.IsPresent
    source_video_is_canonical = $true
    debug_outputs_are_purgeable = $true
    durable_evidence_written = $false
    database_mutation = $false
}

$config | ConvertTo-Json -Depth 8 | Set-Content -Path $configPath -Encoding UTF8

$exitCode = 999

try {
    $env:BIRDBILL_SMOKE_CONFIG = $configPath
    & $py $script 1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE
}
catch {
    $exitCode = 998
    $_ | Out-File -FilePath $stderrPath -Encoding utf8
}
finally {
    if ($null -eq $previousConfigEnv) {
        Remove-Item Env:\BIRDBILL_SMOKE_CONFIG -ErrorAction SilentlyContinue
    }
    else {
        $env:BIRDBILL_SMOKE_CONFIG = $previousConfigEnv
    }
}

$status = if ($exitCode -eq 0) { "PASS" } else { "FAIL" }

$summary = @()
$summary += "smokeSmartFrameSampler.ps1 | v0.5 | 2026-07-06 PDT"
$summary += "status = $status"
$summary += "database_mutation = false"
$summary += "launcher_expected = $expectedLauncherPath"
$summary += "launcher_actual = $actualLauncherPath"
$summary += "python_runner = $script"
$summary += "project_root = $root"
$summary += "python = $py"
$summary += "config_path = $configPath"
$summary += "input_video = $VideoPath"
$summary += "output_dir = $outDir"
$summary += "sample_every_seconds = $SampleEverySeconds"
$summary += "max_sequences = $MaxSequences"
$summary += "sequence_pre_seconds = $SequencePreSeconds"
$summary += "sequence_post_seconds = $SequencePostSeconds"
$summary += "sequence_stride_frames = $SequenceStrideFrames"
$summary += "jpeg_quality = $JpegQuality"
$summary += "storage_mode = $StorageMode"
$summary += "max_preview_frames_total = $MaxPreviewFramesTotal"
$summary += "preview_frames_per_sequence = $PreviewFramesPerSequence"
$summary += "max_cache_frames_total = $MaxCacheFramesTotal"
$summary += "max_bytes_total_mb = $MaxBytesTotalMB"
$summary += "session_id = $SessionId"
$summary += "camera_id = $CameraId"
$summary += "camera_file_id = $CameraFileId"
$summary += "camera_role = $CameraRole"
$summary += "location_id = $LocationId"
$summary += "evidence_mode = $EvidenceMode"
$summary += "evidence_purpose = $EvidencePurpose"
$summary += "feeder_reference_id = $FeederReferenceId"
$summary += "feeder_reference_status = $FeederReferenceStatus"
$summary += "local_scale_reference_type = $LocalScaleReferenceType"
$summary += "local_scale_confidence = $LocalScaleConfidence"
$summary += "calibration_state_id = $CalibrationStateId"
$summary += "calibration_status = $CalibrationStatus"
$summary += "marker_status = $MarkerStatus"
$summary += "sync_status = $SyncStatus"
$summary += "contact_sheet = $($ContactSheet.IsPresent)"
$summary += "source_video_is_canonical = true"
$summary += "debug_outputs_are_purgeable = true"
$summary += "durable_evidence_written = false"
$summary += "python_exit_code = $exitCode"
$summary += "stdout_path = $stdoutPath"
$summary += "stderr_path = $stderrPath"
$summary += "manifest_json_expected = $(Join-Path $outDir 'manifest.json')"
$summary += "session_manifest_expected = $(Join-Path $outDir 'session-manifest.json')"
$summary += "sampled_sequences_csv_expected = $(Join-Path $outDir 'sampled-sequences.csv')"
$summary += "sampled_frames_csv_expected = $(Join-Path $outDir 'sampled-frames.csv')"
$summary += "extracted_frames_csv_expected = $(Join-Path $outDir 'extracted-frames.csv')"
$summary += "storage_ledger_expected = $(Join-Path $outDir 'storage-ledger.json')"
$summary += "frames_root_expected = $(Join-Path $outDir 'frames')"
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

$summary | Out-File -FilePath $summaryPath -Encoding utf8

Write-Host ""
Write-Host "Smoke test status: $status"
Write-Host "database_mutation = false"
Write-Host "storage_mode = $StorageMode"
Write-Host "debug_outputs_are_purgeable = true"
Write-Host "durable_evidence_written = false"
Write-Host "summary = $summaryPath"
Write-Host "manifest = $(Join-Path $outDir 'manifest.json')"
Write-Host "session_manifest = $(Join-Path $outDir 'session-manifest.json')"
Write-Host "sampled_sequences = $(Join-Path $outDir 'sampled-sequences.csv')"
Write-Host "sampled_frames = $(Join-Path $outDir 'sampled-frames.csv')"
Write-Host "extracted_frames = $(Join-Path $outDir 'extracted-frames.csv')"
Write-Host "storage_ledger = $(Join-Path $outDir 'storage-ledger.json')"
Write-Host "frames = $(Join-Path $outDir 'frames')"
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
