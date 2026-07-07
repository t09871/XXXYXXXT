# migrateDlcBilltipProject.ps1 | v0.2 | 2026-07-03 PDT | Exact-path DLC billtip project migration into Birdbill

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = "D:\birdbill"

$sourceProjectDir = "D:\HBMR\dlc\billtip\billtip-HB-2026-06-30"
$sourceConfig = "D:\HBMR\dlc\billtip\billtip-HB-2026-06-30\config.yaml"

$targetProjectDir = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30"
$targetConfig = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml"

$debugDir = "D:\birdbill\output\debug"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $debugDir "dlc-billtip-migration-$stamp.txt"

Write-Host ""
Write-Host "Birdbill DLC billtip migration v0.2"
Write-Host "Root:               $root"
Write-Host "Source project dir: $sourceProjectDir"
Write-Host "Source config:      $sourceConfig"
Write-Host "Target project dir: $targetProjectDir"
Write-Host "Target config:      $targetConfig"
Write-Host "Debug report:       $report"
Write-Host ""

New-Item -ItemType Directory -Force -Path $debugDir | Out-Null

$lines = New-Object System.Collections.ArrayList

function Add-Line {
    param([string]$text)
    [void]$script:lines.Add($text)
}

function Stop-With-Report {
    param([string]$message)

    Add-Line ""
    Add-Line "STOP: $message"
    $script:lines | Set-Content -LiteralPath $script:report -Encoding UTF8

    Write-Host ""
    Write-Host "STOP: $message"
    Write-Host "Report:"
    Write-Host $script:report
    Write-Host ""

    exit 1
}

Add-Line "Birdbill DLC billtip migration | v0.2 | $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))"
Add-Line ""
Add-Line "Purpose:"
Add-Line "Copy the existing DLC billtip project from HBMR into Birdbill so no new live Birdbill contract points to D:\HBMR."
Add-Line ""
Add-Line "Source project dir: $sourceProjectDir"
Add-Line "Source config:      $sourceConfig"
Add-Line "Target project dir: $targetProjectDir"
Add-Line "Target config:      $targetConfig"
Add-Line ""
Add-Line "Rules:"
Add-Line "- Exact paths only."
Add-Line "- No recursive guessing."
Add-Line "- No environment moves."
Add-Line "- No installs."
Add-Line "- No Conda changes."
Add-Line "- Debug output goes directly to D:\birdbill\output\debug."
Add-Line ""

if (-not (Test-Path -LiteralPath $root)) {
    Stop-With-Report "Birdbill root does not exist: $root"
}

if (-not (Test-Path -LiteralPath $sourceProjectDir)) {
    Stop-With-Report "Source DLC project directory does not exist: $sourceProjectDir"
}

if (-not (Test-Path -LiteralPath $sourceConfig)) {
    Stop-With-Report "Source DLC config does not exist: $sourceConfig"
}

$targetParent = Split-Path -Parent $targetProjectDir

if (-not (Test-Path -LiteralPath $targetParent)) {
    Add-Line "Creating target parent directory: $targetParent"
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
}

if (Test-Path -LiteralPath $targetProjectDir) {
    $backupDir = Join-Path $debugDir "dlc-billtip-existing-target-backup-$stamp"

    Add-Line "Existing target project directory found."
    Add-Line "Moving existing target aside to:"
    Add-Line $backupDir

    Move-Item -LiteralPath $targetProjectDir -Destination $backupDir
}

Add-Line ""
Add-Line "Copying DLC billtip project directory..."
Add-Line "From: $sourceProjectDir"
Add-Line "To:   $targetProjectDir"

Copy-Item -LiteralPath $sourceProjectDir -Destination $targetProjectDir -Recurse -Force

if (-not (Test-Path -LiteralPath $targetConfig)) {
    Stop-With-Report "Copy finished, but target config does not exist: $targetConfig"
}

Add-Line "Copy complete."
Add-Line ""

$sourceHash = Get-FileHash -LiteralPath $sourceConfig -Algorithm SHA256
$targetHashBeforeRewrite = Get-FileHash -LiteralPath $targetConfig -Algorithm SHA256

Add-Line "Source config SHA256:              $($sourceHash.Hash)"
Add-Line "Target config SHA256 before edit:  $($targetHashBeforeRewrite.Hash)"

if ($sourceHash.Hash -eq $targetHashBeforeRewrite.Hash) {
    Add-Line "Initial config copy hash check: OK"
} else {
    Add-Line "Initial config copy hash check: WARNING, hashes differ before rewrite."
}

Add-Line ""

$configText = Get-Content -LiteralPath $targetConfig -Raw

$oldProjectPathA = "D:\HBMR\dlc\billtip\billtip-HB-2026-06-30"
$oldProjectPathB = "D:/HBMR/dlc/billtip/billtip-HB-2026-06-30"
$newProjectPath = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30"

$containsOldProjectA = $configText.Contains($oldProjectPathA)
$containsOldProjectB = $configText.Contains($oldProjectPathB)

Add-Line "Config path rewrite scan:"
Add-Line "Contains old Windows project path: $containsOldProjectA"
Add-Line "Contains old slash project path:   $containsOldProjectB"
Add-Line ""

if ($containsOldProjectA -or $containsOldProjectB) {
    Add-Line "Rewriting exact old DLC project path to Birdbill project path."

    $configText = $configText.Replace($oldProjectPathA, $newProjectPath)
    $configText = $configText.Replace($oldProjectPathB, $newProjectPath)

    Set-Content -LiteralPath $targetConfig -Value $configText -Encoding UTF8
} else {
    Add-Line "No exact old DLC project path found in config."
    Add-Line "No config rewrite performed."
}

Add-Line ""

$rewrittenConfigText = Get-Content -LiteralPath $targetConfig -Raw
$remainingHbmrLines = New-Object System.Collections.ArrayList
$configLines = Get-Content -LiteralPath $targetConfig

for ($i = 0; $i -lt $configLines.Count; $i++) {
    $lineNumber = $i + 1
    $line = $configLines[$i]

    if ($line -match "D:\\HBMR|D:/HBMR|HBMR") {
        [void]$remainingHbmrLines.Add(("Line " + $lineNumber + ": " + $line))
    }
}

Add-Line "Remaining HBMR reference scan:"

if ($remainingHbmrLines.Count -eq 0) {
    Add-Line "OK: No HBMR text references remain in copied config.yaml."
} else {
    Add-Line "WARNING: HBMR text references remain in copied config.yaml."
    Add-Line "Do not treat DLC config migration as complete until reviewed."
    Add-Line ""

    foreach ($item in $remainingHbmrLines) {
        Add-Line $item
    }
}

Add-Line ""

$targetHashAfterRewrite = Get-FileHash -LiteralPath $targetConfig -Algorithm SHA256
Add-Line "Target config SHA256 after rewrite: $($targetHashAfterRewrite.Hash)"
Add-Line ""

$targetFiles = Get-ChildItem -LiteralPath $targetProjectDir -Recurse -File -ErrorAction Stop
$totalBytes = 0

foreach ($file in $targetFiles) {
    $totalBytes += $file.Length
}

Add-Line "Copied project file count: $($targetFiles.Count)"
Add-Line "Copied project total bytes: $totalBytes"
Add-Line ""

Add-Line "Recommended settings.ini contract after successful review:"
Add-Line ""
Add-Line "[tool.dlc_billtip]"
Add-Line "enabled = yes"
Add-Line "role = precision bill_base and bill_tip specialist"
Add-Line "python = C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe"
Add-Line "working_dir = D:\birdbill"
Add-Line "module_dir = modules\dlc\billtip"
Add-Line "project_root = D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30"
Add-Line "config_path = D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml"
Add-Line "expected_points = bill_base,bill_tip"
Add-Line "output_dir = output\smart-cropper\bill"
Add-Line "debug_dir = output\debug"
Add-Line "allow_sys_executable_fallback = no"
Add-Line "print_interpreter = yes"
Add-Line "required_for_minimal_pipeline = yes"
Add-Line ""

if ($remainingHbmrLines.Count -eq 0) {
    Add-Line "RESULT: OK"
    Add-Line "The DLC billtip project was copied into Birdbill and config.yaml has no HBMR text references."
} else {
    Add-Line "RESULT: REVIEW NEEDED"
    Add-Line "The DLC billtip project was copied into Birdbill, but config.yaml still contains HBMR text references."
}

Add-Line ""
Add-Line "No installs performed."
Add-Line "No Conda env moved."
Add-Line "No recursive search performed."

$lines | Set-Content -LiteralPath $report -Encoding UTF8

Write-Host ""
Write-Host "DLC billtip migration script finished."
Write-Host "Target project:"
Write-Host $targetProjectDir
Write-Host ""
Write-Host "Target config:"
Write-Host $targetConfig
Write-Host ""
Write-Host "Report:"
Write-Host $report
Write-Host ""

if ($remainingHbmrLines.Count -eq 0) {
    Write-Host "RESULT: OK - copied config has no HBMR text references."
} else {
    Write-Host "RESULT: REVIEW NEEDED - copied config still contains HBMR text references."
}

Write-Host ""