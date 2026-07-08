# migrateMMPoseAssets-v0.1.ps1 | v0.1 | 2026-07-07 PDT | Copy minimum legacy HBMR MMPose model assets into current Birdbill

$ErrorActionPreference = "Continue"

$scriptName = "migrateMMPoseAssets-v0.1.ps1"
$scriptVersion = "v0.1"

$sourceModelDir = "D:\HBMR\mmpose\models"
$destModelDir = "D:\birdbill\modules\mmpose\models"
$outDir = "D:\birdbill\output\debug"
$reportPath = Join-Path $outDir "mmpose-migration-report-001.txt"

$configName = "rtmpose-m_8xb64-210e_ap10k-256x256.py"
$checkpointName = "rtmpose-m_simcc-ap10k_pt-aic-coco_210e-256x256-7a041aa1_20230206.pth"

$configSource = Join-Path $sourceModelDir $configName
$checkpointSource = Join-Path $sourceModelDir $checkpointName

$configDest = Join-Path $destModelDir $configName
$checkpointDest = Join-Path $destModelDir $checkpointName

function Add-ReportLine {
    param(
        [Parameter(Mandatory=$true)][string]$Text
    )
    Add-Content -LiteralPath $reportPath -Value $Text -Encoding UTF8
}

New-Item -ItemType Directory -Force -Path $outDir | Out-Null

"$scriptName | $scriptVersion | 2026-07-07 PDT | Copy minimum legacy HBMR MMPose model assets into current Birdbill" | Set-Content -LiteralPath $reportPath -Encoding UTF8
Add-ReportLine "generated=$(Get-Date -Format o)"
Add-ReportLine "script_path=$PSCommandPath"
Add-ReportLine "working_directory=$(Get-Location)"
Add-ReportLine "database_mutation=false"
Add-ReportLine "durable_evidence_written=false"
Add-ReportLine "media_files_written=0"
Add-ReportLine "source_model_dir=$sourceModelDir"
Add-ReportLine "dest_model_dir=$destModelDir"
Add-ReportLine ""

Write-Host "MMPose asset migration"
Write-Host "Source: $sourceModelDir"
Write-Host "Dest:   $destModelDir"
Write-Host "Report: $reportPath"
Write-Host ""

$sourceDirExists = Test-Path -LiteralPath $sourceModelDir
$destDirExistsBefore = Test-Path -LiteralPath $destModelDir
$configSourceExists = Test-Path -LiteralPath $configSource
$checkpointSourceExists = Test-Path -LiteralPath $checkpointSource

Add-ReportLine "PRECHECK"
Add-ReportLine "source_model_dir_exists=$sourceDirExists"
Add-ReportLine "dest_model_dir_exists_before=$destDirExistsBefore"
Add-ReportLine "config_source_exists=$configSourceExists"
Add-ReportLine "checkpoint_source_exists=$checkpointSourceExists"
Add-ReportLine ""

if (-not $sourceDirExists) {
    Add-ReportLine "status=FAIL"
    Add-ReportLine "reason=source_model_dir_missing"
    Write-Host "status=FAIL"
    Write-Host "Missing source model dir: $sourceModelDir"
    exit 1
}

if (-not $configSourceExists -or -not $checkpointSourceExists) {
    Add-ReportLine "SOURCE MODEL DIRECTORY LISTING"
    Get-ChildItem -LiteralPath $sourceModelDir -File -Force -ErrorAction SilentlyContinue |
        Select-Object Name, Length, LastWriteTime |
        Format-Table -AutoSize |
        Out-String |
        ForEach-Object { Add-ReportLine $_ }

    Add-ReportLine "status=FAIL"
    Add-ReportLine "reason=expected_config_or_checkpoint_missing"
    Write-Host "status=FAIL"
    Write-Host "Expected config/checkpoint missing. See report:"
    Write-Host $reportPath
    exit 1
}

New-Item -ItemType Directory -Force -Path $destModelDir | Out-Null

$copyResults = @()

foreach ($pair in @(
    @{ label = "config"; source = $configSource; dest = $configDest },
    @{ label = "checkpoint"; source = $checkpointSource; dest = $checkpointDest }
)) {
    $label = $pair.label
    $source = $pair.source
    $dest = $pair.dest

    try {
        Copy-Item -LiteralPath $source -Destination $dest -Force
        $destItem = Get-Item -LiteralPath $dest -Force

        $copyResults += [PSCustomObject]@{
            label = $label
            source = $source
            dest = $dest
            copied = $true
            bytes = $destItem.Length
            modified = $destItem.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            error = ""
        }
    }
    catch {
        $copyResults += [PSCustomObject]@{
            label = $label
            source = $source
            dest = $dest
            copied = $false
            bytes = ""
            modified = ""
            error = $_.Exception.Message
        }
    }
}

Add-ReportLine "COPY RESULTS"
$copyResults |
    Format-Table -AutoSize |
    Out-String |
    ForEach-Object { Add-ReportLine $_ }

$configDestExists = Test-Path -LiteralPath $configDest
$checkpointDestExists = Test-Path -LiteralPath $checkpointDest

Add-ReportLine ""
Add-ReportLine "POSTCHECK"
Add-ReportLine "config_dest_exists=$configDestExists"
Add-ReportLine "checkpoint_dest_exists=$checkpointDestExists"

if ($configDestExists) {
    $item = Get-Item -LiteralPath $configDest -Force
    Add-ReportLine "config_dest_bytes=$($item.Length)"
}

if ($checkpointDestExists) {
    $item = Get-Item -LiteralPath $checkpointDest -Force
    Add-ReportLine "checkpoint_dest_bytes=$($item.Length)"
}

Add-ReportLine ""
Add-ReportLine "MIGRATION POLICY"
Add-ReportLine "copied_only_minimum_mmpose_model_assets=true"
Add-ReportLine "copied_old_mmpose_output=false"
Add-ReportLine "copied_old_generated_visuals=false"
Add-ReportLine "copied_old_gui_source=false"
Add-ReportLine "note=old mmposeGUI.py remains a legacy reference from GitHub/HBMR, not migrated as active Birdbill code"

if ($configDestExists -and $checkpointDestExists) {
    Add-ReportLine ""
    Add-ReportLine "status=PASS"
    Write-Host "status=PASS"
    Write-Host "Copied MMPose config/checkpoint."
    Write-Host "Report:"
    Write-Host $reportPath
    exit 0
} else {
    Add-ReportLine ""
    Add-ReportLine "status=FAIL"
    Add-ReportLine "reason=copy_postcheck_failed"
    Write-Host "status=FAIL"
    Write-Host "Copy postcheck failed. See report:"
    Write-Host $reportPath
    exit 1
}