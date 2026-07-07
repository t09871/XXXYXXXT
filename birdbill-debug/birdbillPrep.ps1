# birdbillPrep.ps1 | v0.2 | 2026-07-06 PDT | Birdbill settings + robust grouped smoke checks

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = "D:\birdbill"
$scriptDir = "D:\birdbill\debug"
$debugOutDir = "D:\birdbill\output\debug"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $debugOutDir "birdbill-prep-$stamp.txt"
$settingsPath = Join-Path $root "settings.ini"

$corePy = "D:\birdbill\.venv\Scripts\python.exe"
$dlcPy = "C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe"
$mmposePy = "C:\Users\autom\miniconda3\envs\openmmlab\python.exe"
$speciesNetPy = "D:\birdbill\modules\speciesnet\speciesnet-env\Scripts\python.exe"

$dlcProjectDir = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30"
$dlcConfig = "D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml"

$megaDetectorModel = "D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt"

New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null
New-Item -ItemType Directory -Force -Path $debugOutDir | Out-Null

$lines = New-Object System.Collections.ArrayList

function Add-Line {
    param([string]$text)
    [void]$script:lines.Add($text)
    Write-Host $text
}

function Add-Blank {
    Add-Line ""
}

function Test-Path-Report {
    param(
        [string]$label,
        [string]$path
    )

    $exists = Test-Path -LiteralPath $path
    if ($exists) {
        Add-Line "OK      $label -> $path"
    } else {
        Add-Line "MISSING $label -> $path"
    }
    return $exists
}

function Invoke-Python-Captured {
    param(
        [string]$python,
        [string]$scriptPath,
        [int]$timeoutSeconds = 120
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $python
    $psi.Arguments = "`"$scriptPath`""
    $psi.WorkingDirectory = $script:root
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    [void]$proc.Start()

    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()

    $exited = $proc.WaitForExit($timeoutSeconds * 1000)

    if (-not $exited) {
        try {
            $proc.Kill()
        } catch {
        }

        return [ordered]@{
            ok = $false
            exit_code = -999
            stdout = ""
            stderr = "TIMEOUT after $timeoutSeconds seconds."
        }
    }

    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result

    return [ordered]@{
        ok = ($proc.ExitCode -eq 0)
        exit_code = $proc.ExitCode
        stdout = $stdout
        stderr = $stderr
    }
}

function Run-Smoke {
    param(
        [string]$label,
        [string]$python,
        [string]$code,
        [int]$timeoutSeconds = 120
    )

    Add-Blank
    Add-Line "SMOKE: $label"
    Add-Line "Python: $python"

    if (-not (Test-Path -LiteralPath $python)) {
        Add-Line "RESULT: MISSING interpreter"
        return $false
    }

    $tmp = Join-Path $env:TEMP ("birdbill-smoke-" + [guid]::NewGuid().ToString() + ".py")

    try {
        Set-Content -LiteralPath $tmp -Value $code -Encoding UTF8

        $result = Invoke-Python-Captured -python $python -scriptPath $tmp -timeoutSeconds $timeoutSeconds

        if (-not [string]::IsNullOrWhiteSpace($result.stdout)) {
            Add-Line "STDOUT:"
            foreach ($line in ($result.stdout -split "`r?`n")) {
                if (-not [string]::IsNullOrWhiteSpace($line)) {
                    Add-Line ("  " + $line)
                }
            }
        }

        if (-not [string]::IsNullOrWhiteSpace($result.stderr)) {
            Add-Line "STDERR:"
            foreach ($line in ($result.stderr -split "`r?`n")) {
                if (-not [string]::IsNullOrWhiteSpace($line)) {
                    Add-Line ("  " + $line)
                }
            }
        }

        if ($result.ok) {
            Add-Line "RESULT: OK"
            return $true
        } else {
            Add-Line "RESULT: FAIL exit code $($result.exit_code)"
            return $false
        }
    } finally {
        if (Test-Path -LiteralPath $tmp) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }
}

Add-Line "Birdbill prep | v0.2 | $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))"
Add-Line "Root:          $root"
Add-Line "Script dir:    $scriptDir"
Add-Line "Debug output:  $debugOutDir"
Add-Line "Report:        $report"
Add-Line "Settings path: $settingsPath"
Add-Blank
Add-Line "Rules:"
Add-Line "- Scripts live in D:\birdbill\debug."
Add-Line "- Generated reports/logs go to D:\birdbill\output\debug."
Add-Line "- New live Birdbill settings must not point to D:\HBMR."
Add-Line "- This script captures Python stderr and continues after failed smoke tests."
Add-Blank

Add-Line "Creating/verifying required folders..."

$requiredDirs = @(
    "D:\birdbill\debug",
    "D:\birdbill\output\debug",
    "D:\birdbill\modules\megadetector\models",
    "D:\birdbill\modules\speciesnet",
    "D:\birdbill\modules\dlc\billtip",
    "D:\birdbill\modules\mmpose",
    "D:\birdbill\output\database",
    "D:\birdbill\output\frames",
    "D:\birdbill\output\crops",
    "D:\birdbill\output\smart-cropper",
    "D:\birdbill\output\smart-cropper\bill",
    "D:\birdbill\output\smart-cropper\head",
    "D:\birdbill\output\smart-cropper\throat",
    "D:\birdbill\output\smart-cropper\body",
    "D:\birdbill\output\smart-cropper\tail",
    "D:\birdbill\output\smart-cropper\visuals",
    "D:\birdbill\output\reports",
    "D:\birdbill\output\profiles",
    "D:\birdbill\output\training",
    "D:\birdbill\output\trash"
)

foreach ($dir in $requiredDirs) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Add-Line "OK      dir -> $dir"
}

Add-Blank
Add-Line "Exact contract path checks..."
$corePathOk = Test-Path-Report "Core Python" $corePy
$dlcPyOk = Test-Path-Report "DLC Python" $dlcPy
$dlcProjectOk = Test-Path-Report "DLC project dir" $dlcProjectDir
$dlcConfigOk = Test-Path-Report "DLC config" $dlcConfig
$mmposePyOk = Test-Path-Report "MMPose/OpenMMLab Python" $mmposePy
$megaModelOk = Test-Path-Report "MegaDetector model" $megaDetectorModel
$speciesPyOk = Test-Path-Report "SpeciesNet Python" $speciesNetPy

Add-Blank
Add-Line "Writing settings.ini before smoke tests..."

$settings = @"
; settings.ini | Birdbill v0.2 | 2026-07-06 PDT | Live path contract
; Rule: no new live Birdbill contract points to HBMR root. 
; Scripts live in D:\birdbill\debug. Generated debug reports/logs go to D:\birdbill\output\debug.

[project]
name = Birdbill
root = D:\birdbill
mode = dev
schema_version = 0.2

[paths]
app_dir = app
modules_dir = modules
output_dir = output
debug_scripts_dir = debug
debug_output_dir = output\debug
database_dir = output\database
frames_dir = output\frames
crops_dir = output\crops
smart_cropper_dir = output\smart-cropper
reports_dir = output\reports
profiles_dir = output\profiles
training_dir = output\training
trash_dir = output\trash

[python.core]
enabled = yes
role = first-party Birdbill GUI/app code
python = D:\birdbill\.venv\Scripts\python.exe
working_dir = D:\birdbill
allow_sys_executable_fallback = no
print_interpreter = yes

[tool.megadetector]
enabled = yes
role = animal detector on sampled frames
python = D:\birdbill\.venv\Scripts\python.exe
working_dir = D:\birdbill
module_dir = modules\megadetector
model_path = D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt
output_dir = output\crops
debug_dir = output\debug
allow_sys_executable_fallback = no
print_interpreter = yes
required_for_minimal_pipeline = yes

[tool.dlc_billtip]
enabled = yes
role = precision bill_base and bill_tip specialist
python = C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe
working_dir = D:\birdbill
module_dir = modules\dlc\billtip
project_root = D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30
config_path = D:\birdbill\modules\dlc\billtip\billtip-HB-2026-06-30\config.yaml
expected_points = bill_base,bill_tip
output_dir = output\smart-cropper\bill
debug_dir = output\debug
allow_sys_executable_fallback = no
print_interpreter = yes
required_for_minimal_pipeline = yes

[tool.mmpose]
enabled = yes
role = broad anatomical scout for pose and smart crop regions
python = C:\Users\autom\miniconda3\envs\openmmlab\python.exe
working_dir = D:\birdbill
module_dir = modules\mmpose
config_path =
checkpoint_path =
device = cpu
output_dir = output\smart-cropper
debug_dir = output\debug
allow_sys_executable_fallback = no
print_interpreter = yes
required_for_minimal_pipeline = no

[tool.speciesnet]
enabled = yes
role = optional species classification metadata
python = D:\birdbill\modules\speciesnet\speciesnet-env\Scripts\python.exe
working_dir = D:\birdbill
module_dir = modules\speciesnet
input_staging_dir = output\debug\speciesnet-input
predictions_path = output\debug\speciesnet-predictions.json
debug_dir = output\debug
allow_sys_executable_fallback = no
print_interpreter = yes
required_for_minimal_pipeline = no

[tool.lightglue]
enabled = no
role = local feature pair scorer for AutoSort
python = D:\birdbill\.venv\Scripts\python.exe
working_dir = D:\birdbill
module_dir = modules\lightglue
output_dir = output\reports
debug_dir = output\debug
allow_sys_executable_fallback = no
print_interpreter = yes
required_for_minimal_pipeline = no

[tool.wildid]
enabled = no
role = external/prewritten WildID-style identity support
python = D:\birdbill\.venv\Scripts\python.exe
working_dir = D:\birdbill
module_dir = modules\wildid
output_dir = output\reports
debug_dir = output\debug
allow_sys_executable_fallback = no
print_interpreter = yes
required_for_minimal_pipeline = no

[smart_sampler]
burst_enabled = yes
frames_are_cache = yes
default_skip_processed_inputs = yes
allow_force_reprocess = yes
cache_output_dir = output\frames
debug_dir = output\debug

[smart_cropper]
enabled = yes
durable_output_dir = output\smart-cropper
bill_dir = output\smart-cropper\bill
head_dir = output\smart-cropper\head
throat_dir = output\smart-cropper\throat
body_dir = output\smart-cropper\body
tail_dir = output\smart-cropper\tail
visuals_dir = output\smart-cropper\visuals
debug_dir = output\debug

[storage]
retain_best_crops = yes
retain_usable_crops = yes
retain_weak_debug_crops = dev_only
discard_blurry_redundant_cache = yes
debug_purgeable = yes
profiles_rebuildable = yes
reports_rebuildable = yes

[subprocess]
print_command = yes
print_interpreter = yes
capture_stdout = yes
capture_stderr = yes
fail_parent_on_child_error = no
timeout_seconds_default = 600
write_run_logs = yes
run_log_dir = output\debug

[minimal_pipeline_v0_1]
select_tiny_video_batch = yes
run_smart_sampler = yes
run_megadetector = yes
score_and_retain_crops = yes
run_dlc_billtip = yes
write_database_records = yes
generate_overlay_report = yes
generate_contact_sheet = yes
show_pipeline_alive_output = yes
"@

Set-Content -LiteralPath $settingsPath -Value $settings -Encoding UTF8
Add-Line "OK      Wrote settings.ini: $settingsPath"

$settingsText = Get-Content -LiteralPath $settingsPath -Raw
if ($settingsText -match "D:\\HBMR") {
    Add-Line "FAIL    settings.ini contains D:\HBMR"
} else {
    Add-Line "OK      settings.ini contains no D:\HBMR references"
}

$coreSmoke = @'
import sys
print("sys.executable =", sys.executable)
import cv2
import PIL
import numpy
import pandas
print("cv2 =", cv2.__version__)
print("PIL =", PIL.__version__)
print("numpy =", numpy.__version__)
print("pandas =", pandas.__version__)
'@

$megaSmoke = @'
import sys
print("sys.executable =", sys.executable)

mods = [
    "torch",
    "torchvision",
    "ultralytics",
    "PytorchWildlife",
]

for name in mods:
    try:
        mod = __import__(name)
        version = getattr(mod, "__version__", "version-not-found")
        print(name, "OK", version)
    except Exception as exc:
        print(name, "FAIL", repr(exc))
        raise

try:
    from PytorchWildlife.models import detection
    print("from PytorchWildlife.models import detection -> OK")
except Exception as exc:
    print("from PytorchWildlife.models import detection -> FAIL", repr(exc))
    raise
'@

$dlcSmoke = @"
import sys
import os
print("sys.executable =", sys.executable)
config = r"$dlcConfig"
print("config =", config)
print("config_exists =", os.path.exists(config))
if not os.path.exists(config):
    raise SystemExit(2)
import deeplabcut
print("deeplabcut import OK")
"@

$mmposeSmoke = @'
import sys
print("sys.executable =", sys.executable)
import torch
import mmpose
import mmcv
import mmengine
print("torch =", torch.__version__)
print("mmpose import OK")
print("mmcv import OK")
print("mmengine import OK")
'@

$speciesSmoke = @'
import sys
print("sys.executable =", sys.executable)
try:
    import speciesnet
    print("speciesnet import OK")
except Exception as exc:
    print("speciesnet import FAIL", repr(exc))
    raise
'@

$coreOk = Run-Smoke "Birdbill core imports" $corePy $coreSmoke 120
$megaOk = Run-Smoke "MegaDetector/PytorchWildlife imports" $corePy $megaSmoke 180
$dlcOk = Run-Smoke "DLC billtip import/config" $dlcPy $dlcSmoke 180
$mmposeOk = Run-Smoke "MMPose/OpenMMLab imports" $mmposePy $mmposeSmoke 180
$speciesOk = Run-Smoke "SpeciesNet copied env import" $speciesNetPy $speciesSmoke 180

Add-Blank
Add-Line "Summary:"
Add-Line "Core path:        $corePathOk"
Add-Line "DLC path:         $dlcPyOk"
Add-Line "DLC config path:  $dlcConfigOk"
Add-Line "MMPose path:      $mmposePyOk"
Add-Line "Mega model path:  $megaModelOk"
Add-Line "Species path:     $speciesPyOk"
Add-Line "Core smoke:       $coreOk"
Add-Line "MegaDetector:     $megaOk"
Add-Line "DLC smoke:        $dlcOk"
Add-Line "MMPose smoke:     $mmposeOk"
Add-Line "SpeciesNet smoke: $speciesOk"
Add-Line "Settings written: $settingsPath"
Add-Line "Report:           $report"

$lines | Set-Content -LiteralPath $report -Encoding UTF8

Write-Host ""
Write-Host "Birdbill prep v0.2 finished."
Write-Host "Paste this report next:"
Write-Host $report
Write-Host ""