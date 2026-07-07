# discoverBirdbillState-v0.1.ps1 | v0.1 | 2026-07-07 PDT | Read-only current-state discovery for D:\birdbill

$ErrorActionPreference = "Continue"

$scriptVersion = "v0.1"
$scriptName = "discoverBirdbillState-v0.1.ps1"
$root = "D:\birdbill"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outDir = Join-Path $root "output\debug\birdbill-discovery-$stamp"

$statusPath = Join-Path $outDir "status.txt"
$keyPathsPath = Join-Path $outDir "key-paths-check.txt"
$treePath = Join-Path $outDir "directory-tree-depth-4.txt"
$topSummaryPath = Join-Path $outDir "top-folder-summary.csv"
$depth2SummaryPath = Join-Path $outDir "depth-2-folder-summary.csv"
$sourceInventoryPath = Join-Path $outDir "source-config-inventory.csv"
$allFilesPath = Join-Path $outDir "all-files-inventory.csv"
$pythonEnvPath = Join-Path $outDir "python-env-check.txt"
$classifyPath = Join-Path $outDir "likely-module-classification.csv"
$uploadListPath = Join-Path $outDir "upload-these-files.txt"

function Add-ReportLine {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Text
    )
    Add-Content -LiteralPath $Path -Value $Text -Encoding UTF8
}

function Safe-RelativePath {
    param(
        [Parameter(Mandatory=$true)][string]$BasePath,
        [Parameter(Mandatory=$true)][string]$FullPath
    )

    try {
        $baseUri = [System.Uri]((Resolve-Path -LiteralPath $BasePath).Path.TrimEnd('\') + '\')
        $fullUri = [System.Uri]((Resolve-Path -LiteralPath $FullPath).Path)
        return [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($fullUri).ToString()).Replace('/', '\')
    }
    catch {
        return $FullPath
    }
}

function Get-FolderSizeBytes {
    param(
        [Parameter(Mandatory=$true)][string]$FolderPath
    )

    try {
        $sum = Get-ChildItem -LiteralPath $FolderPath -File -Recurse -Force -ErrorAction SilentlyContinue |
            Measure-Object -Property Length -Sum
        if ($null -eq $sum.Sum) { return 0 }
        return [int64]$sum.Sum
    }
    catch {
        return 0
    }
}

function Write-DirectoryTree {
    param(
        [Parameter(Mandatory=$true)][string]$FolderPath,
        [Parameter(Mandatory=$true)][string]$OutputPath,
        [int]$MaxDepth = 4
    )

    "Directory tree depth $MaxDepth for $FolderPath" | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    if (-not (Test-Path -LiteralPath $FolderPath)) {
        Add-ReportLine -Path $OutputPath -Text "MISSING_ROOT=$FolderPath"
        return
    }

    $rootDepth = ($FolderPath.TrimEnd('\') -split '\\').Count

    Get-ChildItem -LiteralPath $FolderPath -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            $depth = ($_.FullName.TrimEnd('\') -split '\\').Count - $rootDepth
            if ($depth -le $MaxDepth) {
                $indent = "  " * [Math]::Max(0, ($depth - 1))
                $relative = Safe-RelativePath -BasePath $FolderPath -FullPath $_.FullName
                Add-ReportLine -Path $OutputPath -Text "$indent$relative"
            }
        }
}

function Get-TopFolderSummaryRows {
    param(
        [Parameter(Mandatory=$true)][string]$FolderPath,
        [int]$Depth = 1
    )

    $rows = New-Object System.Collections.Generic.List[object]

    if (-not (Test-Path -LiteralPath $FolderPath)) {
        return $rows
    }

    $rootDepth = ($FolderPath.TrimEnd('\') -split '\\').Count

    Get-ChildItem -LiteralPath $FolderPath -Directory -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            $currentDepth = ($_.FullName.TrimEnd('\') -split '\\').Count - $rootDepth
            if ($currentDepth -eq $Depth) {
                $fileCount = 0
                $folderCount = 0
                $bytes = 0

                try {
                    $fileItems = Get-ChildItem -LiteralPath $_.FullName -File -Recurse -Force -ErrorAction SilentlyContinue
                    $folderItems = Get-ChildItem -LiteralPath $_.FullName -Directory -Recurse -Force -ErrorAction SilentlyContinue
                    $fileCount = @($fileItems).Count
                    $folderCount = @($folderItems).Count
                    $sum = $fileItems | Measure-Object -Property Length -Sum
                    if ($null -ne $sum.Sum) { $bytes = [int64]$sum.Sum }
                }
                catch {
                    $fileCount = -1
                    $folderCount = -1
                    $bytes = -1
                }

                $relative = Safe-RelativePath -BasePath $FolderPath -FullPath $_.FullName

                $rows.Add([PSCustomObject]@{
                    folder = $relative
                    files = $fileCount
                    folders = $folderCount
                    bytes = $bytes
                    mb = if ($bytes -ge 0) { [Math]::Round($bytes / 1MB, 3) } else { -1 }
                    gb = if ($bytes -ge 0) { [Math]::Round($bytes / 1GB, 3) } else { -1 }
                    likely_bulk_or_generated = ($relative -match '(^|\\)(output|cache|debug|\.venv|venv|env|__pycache__|models|node_modules|dist|build)(\\|$)')
                }) | Out-Null
            }
        }

    return $rows
}

function Get-SourceConfigInventory {
    param(
        [Parameter(Mandatory=$true)][string]$FolderPath
    )

    $extensions = @(
        ".py", ".ps1", ".bat", ".cmd",
        ".txt", ".md",
        ".ini", ".cfg", ".conf",
        ".json", ".jsonl",
        ".yaml", ".yml",
        ".toml",
        ".csv",
        ".h5",
        ".db", ".sqlite", ".sqlite3"
    )

    $skipPathRegex = '\\(\.git|__pycache__|\.mypy_cache|\.pytest_cache|node_modules|dist|build)(\\|$)'

    $rows = New-Object System.Collections.Generic.List[object]

    if (-not (Test-Path -LiteralPath $FolderPath)) {
        return $rows
    }

    Get-ChildItem -LiteralPath $FolderPath -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object {
            ($extensions -contains $_.Extension.ToLowerInvariant()) -and
            ($_.FullName -notmatch $skipPathRegex)
        } |
        ForEach-Object {
            $relative = Safe-RelativePath -BasePath $FolderPath -FullPath $_.FullName
            $rows.Add([PSCustomObject]@{
                relative_path = $relative
                extension = $_.Extension
                bytes = $_.Length
                mb = [Math]::Round($_.Length / 1MB, 3)
                modified = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
                likely_role = if ($relative -match '^app\\') {
                    "app"
                } elseif ($relative -match '^debug\\') {
                    "debug-script-or-debug-note"
                } elseif ($relative -match '^modules\\') {
                    "module-or-module-config"
                } elseif ($relative -match '^output\\debug\\') {
                    "generated-debug-artifact"
                } elseif ($relative -match '^output\\cache\\') {
                    "generated-cache-artifact"
                } elseif ($relative -match '^output\\') {
                    "generated-output-or-derived-state"
                } else {
                    "root-or-uncategorized"
                }
            }) | Out-Null
        }

    return $rows
}

function Get-AllFilesInventory {
    param(
        [Parameter(Mandatory=$true)][string]$FolderPath
    )

    $rows = New-Object System.Collections.Generic.List[object]

    if (-not (Test-Path -LiteralPath $FolderPath)) {
        return $rows
    }

    Get-ChildItem -LiteralPath $FolderPath -File -Recurse -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            $relative = Safe-RelativePath -BasePath $FolderPath -FullPath $_.FullName
            $rows.Add([PSCustomObject]@{
                relative_path = $relative
                extension = $_.Extension
                bytes = $_.Length
                mb = [Math]::Round($_.Length / 1MB, 3)
                modified = $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            }) | Out-Null
        }

    return $rows
}

function Write-KeyPathChecks {
    param(
        [Parameter(Mandatory=$true)][string]$OutputPath
    )

    $keyPaths = @(
        "D:\birdbill",
        "D:\birdbill\app",
        "D:\birdbill\app\SmartFrameSampler.py",
        "D:\birdbill\debug",
        "D:\birdbill\output",
        "D:\birdbill\output\debug",
        "D:\birdbill\output\cache",
        "D:\birdbill\output\cache\SmartFrameSampler",
        "D:\birdbill\modules",
        "D:\birdbill\modules\megadetector",
        "D:\birdbill\modules\megadetector\megadetector-env\Scripts\python.exe",
        "D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt",
        "D:\birdbill\modules\dlc",
        "D:\birdbill\modules\dlc\billtip",
        "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30",
        "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml",
        "D:\birdbill\modules\speciesnet",
        "D:\birdbill\modules\speciesnet\speciesnet-env\Scripts\python.exe",
        "D:\birdbill\.venv\Scripts\python.exe",
        "C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe",
        "C:\Users\autom\miniconda3\envs\openmmlab\python.exe"
    )

    "key_path,exists,type,bytes,modified" | Set-Content -LiteralPath $OutputPath -Encoding UTF8

    foreach ($p in $keyPaths) {
        $exists = Test-Path -LiteralPath $p
        $type = "missing"
        $bytes = ""
        $modified = ""

        if ($exists) {
            try {
                $item = Get-Item -LiteralPath $p -Force
                if ($item.PSIsContainer) {
                    $type = "directory"
                } else {
                    $type = "file"
                    $bytes = $item.Length
                }
                $modified = $item.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            }
            catch {
                $type = "exists-but-read-error"
            }
        }

        $safePath = '"' + ($p -replace '"','""') + '"'
        Add-ReportLine -Path $OutputPath -Text "$safePath,$exists,$type,$bytes,$modified"
    }
}

function Write-PythonEnvChecks {
    param(
        [Parameter(Mandatory=$true)][string]$OutputPath
    )

    $pythonCandidates = @(
        "D:\birdbill\.venv\Scripts\python.exe",
        "D:\birdbill\modules\megadetector\megadetector-env\Scripts\python.exe",
        "D:\birdbill\modules\speciesnet\speciesnet-env\Scripts\python.exe",
        "C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe",
        "C:\Users\autom\miniconda3\envs\openmmlab\python.exe"
    )

    "Python environment checks" | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Add-ReportLine -Path $OutputPath -Text "database_mutation=false"
    Add-ReportLine -Path $OutputPath -Text "durable_evidence_written=false"
    Add-ReportLine -Path $OutputPath -Text "media_files_written=0"
    Add-ReportLine -Path $OutputPath -Text ""

    foreach ($py in $pythonCandidates) {
        Add-ReportLine -Path $OutputPath -Text "========================================================================"
        Add-ReportLine -Path $OutputPath -Text "python=$py"
        Add-ReportLine -Path $OutputPath -Text "exists=$(Test-Path -LiteralPath $py)"

        if (Test-Path -LiteralPath $py) {
            try {
                $versionOutput = & $py --version 2>&1
                $versionExit = $LASTEXITCODE
                Add-ReportLine -Path $OutputPath -Text "version_exit_code=$versionExit"
                Add-ReportLine -Path $OutputPath -Text "version_output=$versionOutput"
            }
            catch {
                Add-ReportLine -Path $OutputPath -Text "version_check_error=$($_.Exception.Message)"
            }

            $importCode = "import sys; print('executable=' + sys.executable); print('version=' + sys.version.replace(chr(10),' '))"
            try {
                $importOutput = & $py -c $importCode 2>&1
                $importExit = $LASTEXITCODE
                Add-ReportLine -Path $OutputPath -Text "self_report_exit_code=$importExit"
                Add-ReportLine -Path $OutputPath -Text "self_report_output:"
                foreach ($line in $importOutput) {
                    Add-ReportLine -Path $OutputPath -Text "  $line"
                }
            }
            catch {
                Add-ReportLine -Path $OutputPath -Text "self_report_error=$($_.Exception.Message)"
            }
        }

        Add-ReportLine -Path $OutputPath -Text ""
    }
}

function Write-LikelyModuleClassification {
    param(
        [Parameter(Mandatory=$true)][string]$FolderPath,
        [Parameter(Mandatory=$true)][string]$OutputPath
    )

    $rows = New-Object System.Collections.Generic.List[object]

    $interestingFiles = @(
        "app\SmartFrameSampler.py",
        "main.py",
        "settings.ini",
        "HBMR.bat",
        "Birdbill.bat",
        "debug",
        "app",
        "modules",
        "modules\megadetector",
        "modules\dlc",
        "modules\speciesnet",
        "modules\mmpose",
        "output\database",
        "output\debug",
        "output\cache\SmartFrameSampler"
    )

    foreach ($rel in $interestingFiles) {
        $full = Join-Path $FolderPath $rel
        $exists = Test-Path -LiteralPath $full
        $kind = "missing"
        $classification = "missing"
        $notes = ""

        if ($exists) {
            $item = Get-Item -LiteralPath $full -Force
            if ($item.PSIsContainer) {
                $kind = "directory"
            } else {
                $kind = "file"
            }

            if ($rel -eq "app\SmartFrameSampler.py") {
                $classification = "promoted-app-module-known-from-canon"
            } elseif ($rel -match '^debug$') {
                $classification = "debug-script-workspace"
            } elseif ($rel -match '^app$') {
                $classification = "app-workspace"
            } elseif ($rel -match '^modules') {
                $classification = "module-area"
            } elseif ($rel -match '^output\\debug') {
                $classification = "generated-debug-output"
            } elseif ($rel -match '^output\\cache') {
                $classification = "generated-cache-output"
            } elseif ($rel -match 'settings\.ini$') {
                $classification = "config-candidate"
            } elseif ($rel -match '\.bat$') {
                $classification = "launcher-candidate"
            } elseif ($rel -match '\.py$') {
                $classification = "root-python-candidate-needs-review"
            } else {
                $classification = "present-needs-review"
            }

            if (-not $item.PSIsContainer) {
                $notes = "bytes=$($item.Length); modified=$($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
            } else {
                $notes = "modified=$($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
            }
        }

        $rows.Add([PSCustomObject]@{
            relative_path = $rel
            exists = $exists
            kind = $kind
            likely_classification = $classification
            notes = $notes
        }) | Out-Null
    }

    $rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
}

try {
    if (-not (Test-Path -LiteralPath $root)) {
        Write-Host "ERROR: root does not exist: $root"
        Write-Host "No discovery packet created because root is missing."
        exit 1
    }

    New-Item -ItemType Directory -Force -Path $outDir | Out-Null

    "discoverBirdbillState-v0.1.ps1 | v0.1 | 2026-07-07 PDT | Read-only current-state discovery for D:\birdbill" | Set-Content -LiteralPath $statusPath -Encoding UTF8
    Add-ReportLine -Path $statusPath -Text "generated=$(Get-Date -Format o)"
    Add-ReportLine -Path $statusPath -Text "script_name=$scriptName"
    Add-ReportLine -Path $statusPath -Text "script_version=$scriptVersion"
    Add-ReportLine -Path $statusPath -Text "script_path=$PSCommandPath"
    Add-ReportLine -Path $statusPath -Text "working_directory=$(Get-Location)"
    Add-ReportLine -Path $statusPath -Text "root=$root"
    Add-ReportLine -Path $statusPath -Text "out_dir=$outDir"
    Add-ReportLine -Path $statusPath -Text "database_mutation=false"
    Add-ReportLine -Path $statusPath -Text "durable_evidence_written=false"
    Add-ReportLine -Path $statusPath -Text "media_files_written=0"
    Add-ReportLine -Path $statusPath -Text "source_files_modified=false"
    Add-ReportLine -Path $statusPath -Text ""

    Write-Host "Running Birdbill discovery..."
    Write-Host "Script: $scriptName $scriptVersion"
    Write-Host "Root:   $root"
    Write-Host "Output: $outDir"
    Write-Host ""

    $allFiles = Get-AllFilesInventory -FolderPath $root
    $totalFiles = @($allFiles).Count
    $totalBytes = 0
    foreach ($row in $allFiles) {
        $totalBytes += [int64]$row.bytes
    }

    $totalFolders = @(Get-ChildItem -LiteralPath $root -Directory -Recurse -Force -ErrorAction SilentlyContinue).Count
    $totalGb = [Math]::Round($totalBytes / 1GB, 3)

    Add-ReportLine -Path $statusPath -Text "total_files=$totalFiles"
    Add-ReportLine -Path $statusPath -Text "total_folders=$totalFolders"
    Add-ReportLine -Path $statusPath -Text "total_gb=$totalGb"

    Write-KeyPathChecks -OutputPath $keyPathsPath
    Write-DirectoryTree -FolderPath $root -OutputPath $treePath -MaxDepth 4

    $topRows = Get-TopFolderSummaryRows -FolderPath $root -Depth 1
    $topRows | Sort-Object -Property bytes -Descending | Export-Csv -LiteralPath $topSummaryPath -NoTypeInformation -Encoding UTF8

    $depth2Rows = Get-TopFolderSummaryRows -FolderPath $root -Depth 2
    $depth2Rows | Sort-Object -Property bytes -Descending | Export-Csv -LiteralPath $depth2SummaryPath -NoTypeInformation -Encoding UTF8

    $sourceRows = Get-SourceConfigInventory -FolderPath $root
    $sourceRows | Sort-Object -Property relative_path | Export-Csv -LiteralPath $sourceInventoryPath -NoTypeInformation -Encoding UTF8

    $allFiles | Sort-Object -Property relative_path | Export-Csv -LiteralPath $allFilesPath -NoTypeInformation -Encoding UTF8

    Write-PythonEnvChecks -OutputPath $pythonEnvPath
    Write-LikelyModuleClassification -FolderPath $root -OutputPath $classifyPath

    "Upload or share this whole folder:" | Set-Content -LiteralPath $uploadListPath -Encoding UTF8
    Add-ReportLine -Path $uploadListPath -Text $outDir
    Add-ReportLine -Path $uploadListPath -Text ""
    Add-ReportLine -Path $uploadListPath -Text "Most important files inside it:"
    Add-ReportLine -Path $uploadListPath -Text "- status.txt"
    Add-ReportLine -Path $uploadListPath -Text "- key-paths-check.txt"
    Add-ReportLine -Path $uploadListPath -Text "- directory-tree-depth-4.txt"
    Add-ReportLine -Path $uploadListPath -Text "- source-config-inventory.csv"
    Add-ReportLine -Path $uploadListPath -Text "- likely-module-classification.csv"
    Add-ReportLine -Path $uploadListPath -Text "- python-env-check.txt"
    Add-ReportLine -Path $uploadListPath -Text ""
    Add-ReportLine -Path $uploadListPath -Text "The all-files-inventory.csv may be larger. Include it if convenient."

    Add-ReportLine -Path $statusPath -Text ""
    Add-ReportLine -Path $statusPath -Text "outputs_written:"
    Add-ReportLine -Path $statusPath -Text "status_txt=$statusPath"
    Add-ReportLine -Path $statusPath -Text "key_paths_check=$keyPathsPath"
    Add-ReportLine -Path $statusPath -Text "directory_tree_depth_4=$treePath"
    Add-ReportLine -Path $statusPath -Text "top_folder_summary=$topSummaryPath"
    Add-ReportLine -Path $statusPath -Text "depth_2_folder_summary=$depth2SummaryPath"
    Add-ReportLine -Path $statusPath -Text "source_config_inventory=$sourceInventoryPath"
    Add-ReportLine -Path $statusPath -Text "all_files_inventory=$allFilesPath"
    Add-ReportLine -Path $statusPath -Text "python_env_check=$pythonEnvPath"
    Add-ReportLine -Path $statusPath -Text "likely_module_classification=$classifyPath"
    Add-ReportLine -Path $statusPath -Text "upload_list=$uploadListPath"
    Add-ReportLine -Path $statusPath -Text ""
    Add-ReportLine -Path $statusPath -Text "status=PASS"

    Write-Host "Discovery complete."
    Write-Host "status=PASS"
    Write-Host "Output folder:"
    Write-Host $outDir
    Write-Host ""
    Write-Host "Upload/share the discovery folder, or start with these files:"
    Write-Host "  status.txt"
    Write-Host "  key-paths-check.txt"
    Write-Host "  directory-tree-depth-4.txt"
    Write-Host "  source-config-inventory.csv"
    Write-Host "  likely-module-classification.csv"
    Write-Host "  python-env-check.txt"
}
catch {
    try {
        if (-not (Test-Path -LiteralPath $outDir)) {
            New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        }

        if (-not (Test-Path -LiteralPath $statusPath)) {
            "discoverBirdbillState-v0.1.ps1 | v0.1 | 2026-07-07 PDT | Read-only current-state discovery for D:\birdbill" | Set-Content -LiteralPath $statusPath -Encoding UTF8
        }

        Add-ReportLine -Path $statusPath -Text ""
        Add-ReportLine -Path $statusPath -Text "status=FAIL"
        Add-ReportLine -Path $statusPath -Text "error=$($_.Exception.Message)"
        Add-ReportLine -Path $statusPath -Text "script_path=$PSCommandPath"
        Add-ReportLine -Path $statusPath -Text "working_directory=$(Get-Location)"
        Add-ReportLine -Path $statusPath -Text "root=$root"
        Add-ReportLine -Path $statusPath -Text "out_dir=$outDir"
        Add-ReportLine -Path $statusPath -Text "database_mutation=false"
        Add-ReportLine -Path $statusPath -Text "durable_evidence_written=false"
        Add-ReportLine -Path $statusPath -Text "media_files_written=0"
        Add-ReportLine -Path $statusPath -Text "source_files_modified=false"
    }
    catch {
        Write-Host "Failed while trying to write failure report: $($_.Exception.Message)"
    }

    Write-Host "Discovery failed."
    Write-Host "status=FAIL"
    Write-Host "Output folder, if created:"
    Write-Host $outDir
    Write-Host "Error:"
    Write-Host $_.Exception.Message
    exit 1
}