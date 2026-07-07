# envInventory.ps1 | v0.1 | 2026-07-03 PDT | Read-only Birdbill Python environment inventory

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\birdbill"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ReportDir = Join-Path $ProjectRoot "output\reports\summaries"
$JsonReport = Join-Path $ReportDir "env-inventory-$RunStamp.json"
$TextReport = Join-Path $ReportDir "env-inventory-$RunStamp.txt"

New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

Write-Host ""
Write-Host "Birdbill environment inventory v0.1"
Write-Host "Project root: $ProjectRoot"
Write-Host "Report dir:   $ReportDir"
Write-Host ""

$Candidates = New-Object System.Collections.ArrayList
$SeenCandidateKeys = @{}

function Add-Candidate {
    param(
        [string]$Label,
        [string]$Path,
        [string]$Source
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return
    }

    $NormalizedKey = $Path.ToLowerInvariant()

    if ($SeenCandidateKeys.ContainsKey($NormalizedKey)) {
        return
    }

    $SeenCandidateKeys[$NormalizedKey] = $true

    $Exists = Test-Path -LiteralPath $Path

    $Resolved = $Path
    if ($Exists) {
        try {
            $Resolved = (Resolve-Path -LiteralPath $Path).Path
        } catch {
            $Resolved = $Path
        }
    }

    [void]$Candidates.Add([ordered]@{
        label = $Label
        path = $Path
        resolved_path = $Resolved
        exists = $Exists
        source = $Source
    })
}

function Get-CommandPath {
    param([string]$CommandName)

    try {
        $Command = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($null -ne $Command) {
            return $Command.Source
        }
    } catch {
        return $null
    }

    return $null
}

function Invoke-PythonProbe {
    param(
        [string]$PythonPath,
        [int]$TimeoutSeconds = 45
    )

    if (-not (Test-Path -LiteralPath $PythonPath)) {
        return [ordered]@{
            status = "missing"
            error = "Interpreter path does not exist."
        }
    }

    $ProbeCode = @'
import sys
import os
import json
import platform
import importlib.util

try:
    from importlib import metadata
except Exception:
    metadata = None

packages = [
    {"label": "python", "module": "sys", "dists": []},
    {"label": "sqlite3", "module": "sqlite3", "dists": []},
    {"label": "tkinter", "module": "tkinter", "dists": []},

    {"label": "numpy", "module": "numpy", "dists": ["numpy"]},
    {"label": "pandas", "module": "pandas", "dists": ["pandas"]},
    {"label": "Pillow", "module": "PIL", "dists": ["Pillow"]},
    {"label": "OpenCV", "module": "cv2", "dists": ["opencv-python", "opencv-contrib-python", "opencv-python-headless"]},

    {"label": "PySide6", "module": "PySide6", "dists": ["PySide6"]},
    {"label": "PyQt6", "module": "PyQt6", "dists": ["PyQt6"]},

    {"label": "torch", "module": "torch", "dists": ["torch"]},
    {"label": "torchvision", "module": "torchvision", "dists": ["torchvision"]},
    {"label": "ultralytics", "module": "ultralytics", "dists": ["ultralytics"]},
    {"label": "PytorchWildlife", "module": "PytorchWildlife", "dists": ["PytorchWildlife", "pytorchwildlife"]},

    {"label": "DeepLabCut", "module": "deeplabcut", "dists": ["deeplabcut"]},
    {"label": "TensorFlow", "module": "tensorflow", "dists": ["tensorflow", "tensorflow-intel"]},

    {"label": "MMPose", "module": "mmpose", "dists": ["mmpose"]},
    {"label": "MMCV", "module": "mmcv", "dists": ["mmcv", "mmcv-full"]},
    {"label": "MMDetection", "module": "mmdet", "dists": ["mmdet"]},
    {"label": "MMEngine", "module": "mmengine", "dists": ["mmengine"]},

    {"label": "SpeciesNet", "module": "speciesnet", "dists": ["speciesnet"]},

    {"label": "LightGlue", "module": "lightglue", "dists": ["lightglue"]},
    {"label": "Kornia", "module": "kornia", "dists": ["kornia"]},

    {"label": "scikit-learn", "module": "sklearn", "dists": ["scikit-learn"]},
    {"label": "matplotlib", "module": "matplotlib", "dists": ["matplotlib"]},
]

def module_found(module_name):
    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except Exception as exc:
        return "probe_error: " + repr(exc)

def dist_versions(dist_names):
    versions = {}
    if metadata is None:
        return versions

    for dist_name in dist_names:
        try:
            versions[dist_name] = metadata.version(dist_name)
        except Exception:
            pass

    return versions

package_results = []

for item in packages:
    package_results.append({
        "label": item["label"],
        "module": item["module"],
        "module_found": module_found(item["module"]),
        "versions": dist_versions(item["dists"]),
    })

data = {
    "status": "ok",
    "sys_executable": sys.executable,
    "sys_version": sys.version,
    "version_info": {
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
    },
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "is_venv": sys.prefix != sys.base_prefix,
    "cwd": os.getcwd(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "packages": package_results,
}

print(json.dumps(data, indent=2, sort_keys=True))
'@

    $TempScript = Join-Path $env:TEMP ("birdbill-env-probe-" + [guid]::NewGuid().ToString() + ".py")

    try {
        Set-Content -LiteralPath $TempScript -Value $ProbeCode -Encoding UTF8

        $Psi = New-Object System.Diagnostics.ProcessStartInfo
        $Psi.FileName = $PythonPath
        $Psi.Arguments = "`"$TempScript`""
        $Psi.UseShellExecute = $false
        $Psi.RedirectStandardOutput = $true
        $Psi.RedirectStandardError = $true
        $Psi.CreateNoWindow = $true

        $Proc = New-Object System.Diagnostics.Process
        $Proc.StartInfo = $Psi

        [void]$Proc.Start()

        $Exited = $Proc.WaitForExit($TimeoutSeconds * 1000)

        if (-not $Exited) {
            try {
                $Proc.Kill()
            } catch {
            }

            return [ordered]@{
                status = "timeout"
                error = "Probe timed out after $TimeoutSeconds seconds."
            }
        }

        $StdOut = $Proc.StandardOutput.ReadToEnd()
        $StdErr = $Proc.StandardError.ReadToEnd()

        if ($Proc.ExitCode -ne 0) {
            return [ordered]@{
                status = "error"
                exit_code = $Proc.ExitCode
                stdout = $StdOut
                stderr = $StdErr
            }
        }

        try {
            $Parsed = $StdOut | ConvertFrom-Json
            return $Parsed
        } catch {
            return [ordered]@{
                status = "parse_error"
                error = $_.Exception.Message
                stdout = $StdOut
                stderr = $StdErr
            }
        }
    } finally {
        if (Test-Path -LiteralPath $TempScript) {
            Remove-Item -LiteralPath $TempScript -Force -ErrorAction SilentlyContinue
        }
    }
}

function Has-Package {
    param(
        $Probe,
        [string]$ModuleName
    )

    if ($null -eq $Probe) {
        return $false
    }

    if (-not ($Probe.PSObject.Properties.Name -contains "packages")) {
        return $false
    }

    foreach ($Pkg in $Probe.packages) {
        if ($Pkg.module -eq $ModuleName -and $Pkg.module_found -eq $true) {
            return $true
        }
    }

    return $false
}

function Get-PackageVersionText {
    param(
        $Probe,
        [string]$ModuleName
    )

    if ($null -eq $Probe) {
        return ""
    }

    if (-not ($Probe.PSObject.Properties.Name -contains "packages")) {
        return ""
    }

    foreach ($Pkg in $Probe.packages) {
        if ($Pkg.module -eq $ModuleName) {
            $VersionPairs = @()

            if ($null -ne $Pkg.versions) {
                foreach ($Prop in $Pkg.versions.PSObject.Properties) {
                    $VersionPairs += ($Prop.Name + "=" + $Prop.Value)
                }
            }

            return ($VersionPairs -join "; ")
        }
    }

    return ""
}

function Infer-Roles {
    param($Probe)

    $Roles = @()

    if ($null -eq $Probe) {
        return @("unprobed")
    }

    if (-not ($Probe.PSObject.Properties.Name -contains "status")) {
        return @("unknown")
    }

    if ($Probe.status -ne "ok") {
        return @("probe-" + $Probe.status)
    }

    $HasCore =
        (Has-Package $Probe "cv2") -and
        (Has-Package $Probe "PIL") -and
        (Has-Package $Probe "numpy")

    if ($HasCore) {
        $Roles += "core-capable"
    }

    if ((Has-Package $Probe "ultralytics") -or (Has-Package $Probe "PytorchWildlife")) {
        $Roles += "megadetector-yolo-candidate"
    }

    if (Has-Package $Probe "deeplabcut") {
        $Roles += "dlc-candidate"
    }

    if ((Has-Package $Probe "mmpose") -or (Has-Package $Probe "mmcv") -or (Has-Package $Probe "mmdet") -or (Has-Package $Probe "mmengine")) {
        $Roles += "mmpose-openmmlab-candidate"
    }

    if (Has-Package $Probe "speciesnet") {
        $Roles += "speciesnet-candidate"
    }

    if ((Has-Package $Probe "lightglue") -or (Has-Package $Probe "kornia")) {
        $Roles += "lightglue-autosort-candidate"
    }

    if (Has-Package $Probe "tensorflow") {
        $Roles += "tensorflow-present"
    }

    if (Has-Package $Probe "torch") {
        $Roles += "torch-present"
    }

    if ($Roles.Count -eq 0) {
        $Roles += "python-only-or-unclassified"
    }

    return $Roles
}

function Check-Path {
    param(
        [string]$Label,
        [string]$Path,
        [string]$Kind
    )

    return [ordered]@{
        label = $Label
        path = $Path
        kind = $Kind
        exists = (Test-Path -LiteralPath $Path)
    }
}

Write-Host "Adding known candidate interpreters..."

Add-Candidate "Birdbill core target .venv" "D:\birdbill\.venv\Scripts\python.exe" "known-target"
Add-Candidate "Birdbill alternate venv" "D:\birdbill\venv\Scripts\python.exe" "known-target"
Add-Candidate "Old HBMR speciesnet-env" "D:\HBMR\speciesnet-env\Scripts\python.exe" "known-historical"
Add-Candidate "Old HBMR venv" "D:\HBMR\venv\Scripts\python.exe" "known-historical"
Add-Candidate "DLC likely miniconda env" "C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe" "known-from-project"
Add-Candidate "MMPose likely miniconda env" "C:\Users\autom\miniconda3\envs\mmpose\python.exe" "guess"
Add-Candidate "OpenMMLab likely miniconda env" "C:\Users\autom\miniconda3\envs\openmmlab\python.exe" "guess"
Add-Candidate "Base miniconda autom" "C:\Users\autom\miniconda3\python.exe" "informational"
Add-Candidate "Base anaconda autom" "C:\Users\autom\anaconda3\python.exe" "informational"

$PathPython = Get-CommandPath "python"
if (-not [string]::IsNullOrWhiteSpace($PathPython)) {
    Add-Candidate "PATH python informational only" $PathPython "path-informational-not-contract"
}

$PathPy = Get-CommandPath "py"

Write-Host "Searching common Conda env folders..."

$CondaRoots = @(
    "C:\Users\$env:USERNAME\miniconda3\envs",
    "C:\Users\$env:USERNAME\anaconda3\envs",
    "C:\Users\autom\miniconda3\envs",
    "C:\Users\autom\anaconda3\envs",
    "C:\ProgramData\miniconda3\envs",
    "C:\ProgramData\anaconda3\envs"
) | Select-Object -Unique

foreach ($Root in $CondaRoots) {
    if (Test-Path -LiteralPath $Root) {
        Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $Py = Join-Path $_.FullName "python.exe"
            Add-Candidate ("Conda env: " + $_.Name) $Py "conda-env-search"
        }
    }
}

Write-Host "Searching top-level project env-like folders..."

$ProjectEnvRoots = @("D:\birdbill", "D:\HBMR")

foreach ($Root in $ProjectEnvRoots) {
    if (Test-Path -LiteralPath $Root) {
        Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "env|venv|\.venv" } |
            ForEach-Object {
                $Py = Join-Path $_.FullName "Scripts\python.exe"
                Add-Candidate ("Project env-like folder: " + $_.FullName) $Py "project-env-search"
            }
    }
}

Write-Host ""
Write-Host "Found $($Candidates.Count) candidate interpreter path(s)."
Write-Host "Probing existing interpreters..."
Write-Host ""

$InterpreterResults = New-Object System.Collections.ArrayList

foreach ($Candidate in $Candidates) {
    Write-Host ("Probe: " + $Candidate.label)

    if (-not $Candidate.exists) {
        [void]$InterpreterResults.Add([ordered]@{
            label = $Candidate.label
            path = $Candidate.path
            resolved_path = $Candidate.resolved_path
            source = $Candidate.source
            exists = $false
            probe = [ordered]@{
                status = "missing"
                error = "Interpreter path does not exist."
            }
            inferred_roles = @("missing")
            key_versions = [ordered]@{}
        })
        continue
    }

    $Probe = Invoke-PythonProbe -PythonPath $Candidate.resolved_path
    $Roles = Infer-Roles $Probe

    $KeyVersions = [ordered]@{
        numpy = Get-PackageVersionText $Probe "numpy"
        pandas = Get-PackageVersionText $Probe "pandas"
        opencv = Get-PackageVersionText $Probe "cv2"
        pillow = Get-PackageVersionText $Probe "PIL"
        torch = Get-PackageVersionText $Probe "torch"
        ultralytics = Get-PackageVersionText $Probe "ultralytics"
        pytorchwildlife = Get-PackageVersionText $Probe "PytorchWildlife"
        deeplabcut = Get-PackageVersionText $Probe "deeplabcut"
        tensorflow = Get-PackageVersionText $Probe "tensorflow"
        mmpose = Get-PackageVersionText $Probe "mmpose"
        mmcv = Get-PackageVersionText $Probe "mmcv"
        mmengine = Get-PackageVersionText $Probe "mmengine"
        speciesnet = Get-PackageVersionText $Probe "speciesnet"
        lightglue = Get-PackageVersionText $Probe "lightglue"
        kornia = Get-PackageVersionText $Probe "kornia"
    }

    [void]$InterpreterResults.Add([ordered]@{
        label = $Candidate.label
        path = $Candidate.path
        resolved_path = $Candidate.resolved_path
        source = $Candidate.source
        exists = $true
        probe = $Probe
        inferred_roles = $Roles
        key_versions = $KeyVersions
    })
}

Write-Host ""
Write-Host "Checking Birdbill folder contract..."

$PathChecks = New-Object System.Collections.ArrayList

$RequiredPaths = @(
    @("Project root", "D:\birdbill", "dir"),
    @("Birdbill launcher", "D:\birdbill\Birdbill.bat", "file"),
    @("README", "D:\birdbill\README.txt", "file"),
    @("settings.ini", "D:\birdbill\settings.ini", "file"),
    @("canon.txt", "D:\birdbill\canon.txt", "file"),

    @("app", "D:\birdbill\app", "dir"),
    @("app main", "D:\birdbill\app\main", "dir"),
    @("app smart-sampler", "D:\birdbill\app\smart-sampler", "dir"),
    @("app smart-cropper", "D:\birdbill\app\smart-cropper", "dir"),
    @("app autosort", "D:\birdbill\app\autosort", "dir"),
    @("app autosort scorers", "D:\birdbill\app\autosort\scorers", "dir"),
    @("app identity", "D:\birdbill\app\identity", "dir"),
    @("app profiles", "D:\birdbill\app\profiles", "dir"),
    @("app biometrics", "D:\birdbill\app\biometrics", "dir"),
    @("app 3d-mapping", "D:\birdbill\app\3d-mapping", "dir"),
    @("app ai-detection", "D:\birdbill\app\ai-detection", "dir"),

    @("modules", "D:\birdbill\modules", "dir"),
    @("modules megadetector", "D:\birdbill\modules\megadetector", "dir"),
    @("modules yolo", "D:\birdbill\modules\yolo", "dir"),
    @("modules dlc", "D:\birdbill\modules\dlc", "dir"),
    @("modules dlc billtip", "D:\birdbill\modules\dlc\billtip", "dir"),
    @("modules mmpose", "D:\birdbill\modules\mmpose", "dir"),
    @("modules lightglue", "D:\birdbill\modules\lightglue", "dir"),
    @("modules wildid", "D:\birdbill\modules\wildid", "dir"),
    @("modules speciesnet", "D:\birdbill\modules\speciesnet", "dir"),

    @("output", "D:\birdbill\output", "dir"),
    @("output database", "D:\birdbill\output\database", "dir"),
    @("output frames", "D:\birdbill\output\frames", "dir"),
    @("output crops", "D:\birdbill\output\crops", "dir"),
    @("output smart-cropper", "D:\birdbill\output\smart-cropper", "dir"),
    @("output reports", "D:\birdbill\output\reports", "dir"),
    @("output profiles", "D:\birdbill\output\profiles", "dir"),
    @("output training", "D:\birdbill\output\training", "dir"),
    @("output debug", "D:\birdbill\output\debug", "dir"),
    @("output trash", "D:\birdbill\output\trash", "dir")
)

foreach ($Item in $RequiredPaths) {
    [void]$PathChecks.Add((Check-Path -Label $Item[0] -Path $Item[1] -Kind $Item[2]))
}

Write-Host "Looking for likely DLC config.yaml files..."

$DlcConfigHits = New-Object System.Collections.ArrayList
$DlcSearchRoots = @("D:\HBMR\dlc", "D:\birdbill\modules\dlc")

foreach ($Root in $DlcSearchRoots) {
    if (Test-Path -LiteralPath $Root) {
        Get-ChildItem -LiteralPath $Root -Filter "config.yaml" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 25 |
            ForEach-Object {
                [void]$DlcConfigHits.Add($_.FullName)
            }
    }
}

Write-Host "Looking for likely MegaDetector model files..."

$MegaDetectorModelHits = New-Object System.Collections.ArrayList
$ModelSearchRoots = @("D:\birdbill\modules\megadetector", "D:\HBMR\models", "D:\HBMR")

foreach ($Root in $ModelSearchRoots) {
    if (Test-Path -LiteralPath $Root) {
        Get-ChildItem -LiteralPath $Root -Filter "MDV6*.pt" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 25 |
            ForEach-Object {
                [void]$MegaDetectorModelHits.Add($_.FullName)
            }
    }
}

$PyLauncherInfo = [ordered]@{
    path = $PathPy
    note = "Informational only. Birdbill tool contracts should not rely on bare py or bare python."
    versions = $null
}

if (-not [string]::IsNullOrWhiteSpace($PathPy)) {
    try {
        $PyVersions = & $PathPy -0p 2>&1
        $PyLauncherInfo.versions = ($PyVersions -join "`n")
    } catch {
        $PyLauncherInfo.versions = "py launcher found, but py -0p failed: " + $_.Exception.Message
    }
}

$Inventory = [ordered]@{
    report_version = "0.1"
    generated_at = (Get-Date).ToString("o")
    project_root = $ProjectRoot
    report_json = $JsonReport
    report_text = $TextReport
    py_launcher = $PyLauncherInfo
    interpreters = $InterpreterResults
    path_checks = $PathChecks
    dlc_config_hits = $DlcConfigHits
    megadetector_model_hits = $MegaDetectorModelHits
    rules = [ordered]@{
        no_silent_sys_executable_fallback = $true
        no_bare_python_child_tools = $true
        existing_dlc_mmpose_envs_should_not_be_moved = $true
        inventory_only_no_installs = $true
    }
}

$Inventory | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $JsonReport -Encoding UTF8

$TextLines = New-Object System.Collections.ArrayList

[void]$TextLines.Add("Birdbill Environment Inventory | v0.1 | $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))")
[void]$TextLines.Add("Project root: $ProjectRoot")
[void]$TextLines.Add("JSON report:  $JsonReport")
[void]$TextLines.Add("Text report:  $TextReport")
[void]$TextLines.Add("")
[void]$TextLines.Add("Rule reminder:")
[void]$TextLines.Add("- No silent fallback to sys.executable.")
[void]$TextLines.Add("- No bare python in child-tool contracts.")
[void]$TextLines.Add("- Existing DLC/MMPose C: envs should not be moved unless needed.")
[void]$TextLines.Add("- This script does not install, create, or move environments.")
[void]$TextLines.Add("")
[void]$TextLines.Add("Interpreter Summary:")
[void]$TextLines.Add("")

foreach ($Result in $InterpreterResults) {
    [void]$TextLines.Add("------------------------------------------------------------")
    [void]$TextLines.Add("Label:  " + $Result.label)
    [void]$TextLines.Add("Path:   " + $Result.path)
    [void]$TextLines.Add("Exists: " + $Result.exists)
    [void]$TextLines.Add("Source: " + $Result.source)
    [void]$TextLines.Add("Roles:  " + (($Result.inferred_roles) -join ", "))

    if ($Result.exists -and $Result.probe.status -eq "ok") {
        [void]$TextLines.Add("Python executable: " + $Result.probe.sys_executable)
        [void]$TextLines.Add("Python version:    " + ($Result.probe.version_info.major.ToString() + "." + $Result.probe.version_info.minor.ToString() + "." + $Result.probe.version_info.micro.ToString()))
        [void]$TextLines.Add("Is venv:           " + $Result.probe.is_venv)
        [void]$TextLines.Add("Prefix:            " + $Result.probe.prefix)
        [void]$TextLines.Add("Base prefix:       " + $Result.probe.base_prefix)
        [void]$TextLines.Add("Key versions:")

        foreach ($Prop in $Result.key_versions.GetEnumerator()) {
            if (-not [string]::IsNullOrWhiteSpace($Prop.Value)) {
                [void]$TextLines.Add("  " + $Prop.Key + ": " + $Prop.Value)
            }
        }
    } else {
        [void]$TextLines.Add("Probe status: " + $Result.probe.status)
        if ($Result.probe.PSObject.Properties.Name -contains "error") {
            [void]$TextLines.Add("Probe error:  " + $Result.probe.error)
        }
    }

    [void]$TextLines.Add("")
}

[void]$TextLines.Add("")
[void]$TextLines.Add("Folder/File Contract Check:")
[void]$TextLines.Add("")

foreach ($Check in $PathChecks) {
    $Mark = "MISSING"
    if ($Check.exists) {
        $Mark = "OK"
    }

    [void]$TextLines.Add(($Mark.PadRight(8)) + " " + $Check.kind.PadRight(4) + " " + $Check.path + "  [" + $Check.label + "]")
}

[void]$TextLines.Add("")
[void]$TextLines.Add("DLC config.yaml hits:")
if ($DlcConfigHits.Count -eq 0) {
    [void]$TextLines.Add("  none found in searched DLC roots")
} else {
    foreach ($Hit in $DlcConfigHits) {
        [void]$TextLines.Add("  " + $Hit)
    }
}

[void]$TextLines.Add("")
[void]$TextLines.Add("MegaDetector MDV6*.pt hits:")
if ($MegaDetectorModelHits.Count -eq 0) {
    [void]$TextLines.Add("  none found in searched model roots")
} else {
    foreach ($Hit in $MegaDetectorModelHits) {
        [void]$TextLines.Add("  " + $Hit)
    }
}

[void]$TextLines.Add("")
[void]$TextLines.Add("Py launcher:")
if ([string]::IsNullOrWhiteSpace($PathPy)) {
    [void]$TextLines.Add("  py launcher not found")
} else {
    [void]$TextLines.Add("  path: " + $PathPy)
    [void]$TextLines.Add("  versions:")
    [void]$TextLines.Add("  " + (($PyLauncherInfo.versions -split "`n") -join "`n  "))
}

$TextLines | Set-Content -LiteralPath $TextReport -Encoding UTF8

Write-Host ""
Write-Host "Inventory complete."
Write-Host "Text report:"
Write-Host $TextReport
Write-Host ""
Write-Host "JSON report:"
Write-Host $JsonReport
Write-Host ""
Write-Host "Paste back the text report first; the JSON is there if we need exact package/path details."
Write-Host ""