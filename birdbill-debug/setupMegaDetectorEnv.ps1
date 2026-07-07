# setupMegaDetectorEnv.ps1 | v0.2 | 2026-07-06 PDT | Dedicated MegaDetector/PytorchWildlife venv setup for Birdbill

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = "D:\birdbill"
$scriptDir = "D:\birdbill\debug"
$debugOutDir = "D:\birdbill\output\debug"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$report = Join-Path $debugOutDir "megadetector-env-setup-$stamp.txt"

$pyLauncher = "C:\Users\autom\AppData\Local\Microsoft\WindowsApps\py.exe"

$envDir = "D:\birdbill\modules\megadetector\megadetector-env"
$py = "D:\birdbill\modules\megadetector\megadetector-env\Scripts\python.exe"

$modelPath = "D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt"
$settingsPath = "D:\birdbill\settings.ini"

New-Item -ItemType Directory -Force -Path $scriptDir | Out-Null
New-Item -ItemType Directory -Force -Path $debugOutDir | Out-Null
New-Item -ItemType Directory -Force -Path "D:\birdbill\modules\megadetector" | Out-Null
New-Item -ItemType Directory -Force -Path "D:\birdbill\modules\megadetector\models" | Out-Null

$lines = New-Object System.Collections.ArrayList

function Add-Line {
    param([string]$text)
    [void]$script:lines.Add($text)
    Write-Host $text
}

function Add-Blank {
    Add-Line ""
}

function Save-Report {
    $script:lines | Set-Content -LiteralPath $script:report -Encoding UTF8
}

function Stop-With-Report {
    param([string]$message)

    Add-Blank
    Add-Line "STOP: $message"
    Save-Report

    Write-Host ""
    Write-Host "Report:"
    Write-Host $script:report
    Write-Host ""

    exit 1
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
        [int]$timeoutSeconds = 180
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

    return [ordered]@{
        ok = ($proc.ExitCode -eq 0)
        exit_code = $proc.ExitCode
        stdout = $stdoutTask.Result
        stderr = $stderrTask.Result
    }
}

function Run-Smoke {
    param(
        [string]$label,
        [string]$python,
        [string]$code,
        [int]$timeoutSeconds = 180
    )

    Add-Blank
    Add-Line "SMOKE: $label"
    Add-Line "Python: $python"

    if (-not (Test-Path -LiteralPath $python)) {
        Add-Line "RESULT: MISSING interpreter"
        return $false
    }

    $tmp = Join-Path $env:TEMP ("birdbill-megadetector-smoke-" + [guid]::NewGuid().ToString() + ".py")

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

function Run-Pip {
    param(
        [string]$label,
        [string[]]$pipArgs,
        [int]$timeoutSeconds = 900
    )

    Add-Blank
    Add-Line "PIP: $label"

    if ($null -eq $pipArgs -or $pipArgs.Count -eq 0) {
        Add-Line "RESULT: FAIL - empty pipArgs list. Refusing to run bare pip."
        return $false
    }

    if ($pipArgs[0] -ne "install") {
        Add-Line "RESULT: FAIL - pipArgs must begin with install for this setup script."
        Add-Line "Received: $($pipArgs -join ' ')"
        return $false
    }

    if (-not (Test-Path -LiteralPath $py)) {
        Add-Line "RESULT: MISSING interpreter"
        return $false
    }

    $argumentText = "-m pip " + ($pipArgs -join " ")

    Add-Line "Command: $py $argumentText"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $py
    $psi.Arguments = $argumentText
    $psi.WorkingDirectory = $root
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

        Add-Line "RESULT: TIMEOUT after $timeoutSeconds seconds"
        return $false
    }

    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result

    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        Add-Line "STDOUT:"
        foreach ($line in ($stdout -split "`r?`n")) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                Add-Line ("  " + $line)
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($stderr)) {
        Add-Line "STDERR:"
        foreach ($line in ($stderr -split "`r?`n")) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                Add-Line ("  " + $line)
            }
        }
    }

    if ($proc.ExitCode -eq 0) {
        Add-Line "RESULT: OK"
        return $true
    } else {
        Add-Line "RESULT: FAIL exit code $($proc.ExitCode)"
        return $false
    }
}

function Update-SettingsMegaDetectorPython {
    Add-Blank
    Add-Line "SETTINGS: update [tool.megadetector] python path"

    if (-not (Test-Path -LiteralPath $settingsPath)) {
        Add-Line "MISSING settings.ini -> $settingsPath"
        Add-Line "No settings update performed."
        return $false
    }

    $text = Get-Content -LiteralPath $settingsPath -Raw

    $pattern = "(?ms)(^\[tool\.megadetector\]\s*.*?^python\s*=\s*).*$"
    $replacement = "`${1}$py"

    if ($text -match $pattern) {
        $newText = [regex]::Replace($text, $pattern, $replacement, 1)
        Set-Content -LiteralPath $settingsPath -Value $newText -Encoding UTF8
        Add-Line "OK      Updated [tool.megadetector] python = $py"
        return $true
    } else {
        Add-Line "WARNING Could not find [tool.megadetector] python line."
        Add-Line "Manual settings.ini value should be:"
        Add-Line "python = $py"
        return $false
    }
}

Add-Line "Birdbill MegaDetector env setup | v0.2 | $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))"
Add-Line "Root:         $root"
Add-Line "Script dir:   $scriptDir"
Add-Line "Debug output: $debugOutDir"
Add-Line "Report:       $report"
Add-Line "Env dir:      $envDir"
Add-Line "Python:       $py"
Add-Line "Model:        $modelPath"
Add-Blank
Add-Line "Rules:"
Add-Line "- Dedicated MegaDetector/PytorchWildlife venv."
Add-Line "- Avoid one-package-at-a-time dependency loops."
Add-Line "- Use Python 3.11 through py launcher."
Add-Line "- Do not modify Birdbill core env."
Add-Line "- Scripts live in D:\birdbill\debug."
Add-Line "- Generated reports/logs go to D:\birdbill\output\debug."
Add-Line "- Smoke tests capture failures and continue to final report."
Add-Line "- Do not update settings.ini unless env smoke tests pass."
Add-Line "- Refuse to run bare pip with an empty argument list."
Add-Blank

Test-Path-Report "Birdbill root" $root | Out-Null
Test-Path-Report "py launcher" $pyLauncher | Out-Null
Test-Path-Report "MegaDetector model" $modelPath | Out-Null

if (-not (Test-Path -LiteralPath $root)) {
    Stop-With-Report "Birdbill root missing."
}

if (-not (Test-Path -LiteralPath $pyLauncher)) {
    Stop-With-Report "py launcher missing at expected path."
}

if (-not (Test-Path -LiteralPath $modelPath)) {
    Stop-With-Report "MegaDetector model missing from Birdbill modules path."
}

Add-Blank
Add-Line "Checking existing MegaDetector env..."

if (Test-Path -LiteralPath $py) {
    Add-Line "OK      Existing MegaDetector env interpreter found."
    Add-Line "No venv recreation performed."
} else {
    if (Test-Path -LiteralPath $envDir) {
        Add-Line "WARNING Env directory exists but interpreter is missing:"
        Add-Line $envDir
        Stop-With-Report "Partial/broken env directory found. Rename or delete it before rerunning."
    }

    Add-Line "Creating MegaDetector venv:"
    Add-Line "$pyLauncher -3.11 -m venv $envDir"

    & $pyLauncher -3.11 -m venv $envDir 2>&1 | ForEach-Object { Add-Line ("  " + $_) }

    if (-not (Test-Path -LiteralPath $py)) {
        Stop-With-Report "venv creation did not produce expected interpreter."
    }

    Add-Line "OK      Created MegaDetector env interpreter."
}

$baselineSmoke = @'
import sys
print("sys.executable =", sys.executable)
print("sys.version =", sys.version)
'@

$preOk = Run-Smoke "MegaDetector env Python baseline" $py $baselineSmoke 120

$pipUpgradeOk = Run-Pip `
    -label "upgrade pip/setuptools/wheel" `
    -pipArgs @("install", "--upgrade", "pip", "setuptools", "wheel") `
    -timeoutSeconds 900

$clusterInstallOk = Run-Pip `
    -label "install detector dependency cluster" `
    -pipArgs @(
        "install",
        "--upgrade",
        "PytorchWildlife",
        "ultralytics",
        "opencv-python",
        "pillow",
        "numpy",
        "pandas",
        "matplotlib",
        "tqdm",
        "librosa",
        "soundfile",
        "audioread",
        "soxr"
    ) `
    -timeoutSeconds 2400

$importSmoke = @"
import sys
import os
print("sys.executable =", sys.executable)

model = r"$modelPath"
print("model_path =", model)
print("model_exists =", os.path.exists(model))
if not os.path.exists(model):
    raise SystemExit(2)

imports = [
    "torch",
    "torchvision",
    "ultralytics",
    "cv2",
    "PIL",
    "numpy",
    "pandas",
    "matplotlib",
    "tqdm",
    "librosa",
    "soundfile",
    "audioread",
    "soxr",
    "PytorchWildlife",
]

for name in imports:
    try:
        mod = __import__(name)
        version = getattr(mod, "__version__", "version-not-found")
        print(name, "OK", version)
    except Exception as exc:
        print(name, "FAIL", repr(exc))
        raise

from PytorchWildlife.models import detection
print("from PytorchWildlife.models import detection -> OK")
"@

$importOk = Run-Smoke "MegaDetector/PytorchWildlife full import cluster" $py $importSmoke 240

$modelSmoke = @"
import sys
import os
print("sys.executable =", sys.executable)

model_path = r"$modelPath"
print("model_path =", model_path)
print("model_exists =", os.path.exists(model_path))
if not os.path.exists(model_path):
    raise SystemExit(2)

from PytorchWildlife.models import detection
print("detection import OK")

print("model load test deferred to next smoke test with a real tiny image/frame.")
"@

$modelOk = Run-Smoke "MegaDetector package/model path readiness" $py $modelSmoke 240

$settingsOk = $false

if ($importOk -and $modelOk) {
    $settingsOk = Update-SettingsMegaDetectorPython
} else {
    Add-Blank
    Add-Line "SETTINGS: skipped"
    Add-Line "Reason: MegaDetector env did not pass import/model readiness smoke tests."
    Add-Line "Current settings.ini may still point to a not-ready env from the previous v0.1 run."
}

Add-Blank
Add-Line "FREEZE: writing installed package list"
$freezePath = Join-Path $debugOutDir "megadetector-env-freeze-$stamp.txt"

if (Test-Path -LiteralPath $py) {
    $freeze = & $py -m pip freeze 2>&1
    $freeze | Set-Content -LiteralPath $freezePath -Encoding UTF8
    Add-Line "OK      pip freeze written:"
    Add-Line $freezePath
} else {
    Add-Line "SKIP    pip freeze because interpreter missing."
}

Add-Blank
Add-Line "Summary:"
Add-Line "Baseline Python smoke:         $preOk"
Add-Line "Pip upgrade:                   $pipUpgradeOk"
Add-Line "Dependency cluster install:    $clusterInstallOk"
Add-Line "Import cluster smoke:          $importOk"
Add-Line "Model readiness smoke:         $modelOk"
Add-Line "settings.ini update:           $settingsOk"
Add-Line "MegaDetector Python candidate: $py"
Add-Line "MegaDetector model contract:   $modelPath"
Add-Line "Report:                        $report"

if ($importOk -and $modelOk) {
    Add-Line "RESULT: OK - MegaDetector dedicated env is ready for an image inference smoke test."
} else {
    Add-Line "RESULT: REPAIR NEEDED - review the failed install/import details above."
}

Save-Report

Write-Host ""
Write-Host "MegaDetector env setup finished."
Write-Host "Paste this report next:"
Write-Host $report
Write-Host ""