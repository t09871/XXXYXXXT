# smokeSmartFrameSamplerApp.ps1 | v0.3 | 2026-07-07 PDT | Birdbill Step 7 launcher for promoted SmartFrameSampler smoke

param(
    [string]$PythonPath = "",
    [string]$ProjectRoot = "D:\birdbill",
    [string]$SourceVideo = "D:\birdbill\debug\20250704_174952_001-Percy-HBMR.mp4"
)

$script_version = "v0.3"
$rewrite_step = "7"

Write-Host "script_name = smokeSmartFrameSamplerApp.ps1"
Write-Host "script_version = $script_version"
Write-Host "rewrite_step = $rewrite_step"

$root = $ProjectRoot
$scriptPath = Join-Path $root "debug\smokeSmartFrameSamplerApp.py"
$appPath = Join-Path $root "app\SmartFrameSampler.py"
$legacyAppPath = Join-Path $root "app\smartFrameSampler.py"
$outRoot = Join-Path $root "output\debug"
$launcherStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$launcherOutDir = Join-Path $outRoot "SmartFrameSampler-app-launcher-$launcherStamp"
$stdoutPath = Join-Path $launcherOutDir "stdout.txt"
$stderrPath = Join-Path $launcherOutDir "stderr.txt"
$exitPath = Join-Path $launcherOutDir "exit-code.txt"

Write-Host "project_root = $root"
Write-Host "script_path = $scriptPath"
Write-Host "app_path = $appPath"
Write-Host "legacy_app_path = $legacyAppPath"
Write-Host "source_video = $SourceVideo"
Write-Host "launcher_output_dir = $launcherOutDir"

New-Item -ItemType Directory -Force -Path $launcherOutDir | Out-Null

if (-not (Test-Path -LiteralPath $root)) {
    Write-Host "status = FAIL"
    Write-Host "missing_project_root = $root"
    "missing_project_root = $root" | Set-Content -LiteralPath $stderrPath
    "1" | Set-Content -LiteralPath $exitPath
    exit 1
}

if (-not (Test-Path -LiteralPath $scriptPath)) {
    Write-Host "status = FAIL"
    Write-Host "missing_script_path = $scriptPath"
    "missing_script_path = $scriptPath" | Set-Content -LiteralPath $stderrPath
    "1" | Set-Content -LiteralPath $exitPath
    exit 1
}

if (-not (Test-Path -LiteralPath $appPath)) {
    Write-Host "status = FAIL"
    Write-Host "missing_app_path = $appPath"
    "missing_app_path = $appPath" | Set-Content -LiteralPath $stderrPath
    "1" | Set-Content -LiteralPath $exitPath
    exit 1
}

if (Test-Path -LiteralPath $legacyAppPath) {
    Write-Host "warning = old lowercase app file exists: $legacyAppPath"
    Write-Host "warning = canonical app file is now: $appPath"
}

if (-not (Test-Path -LiteralPath $SourceVideo)) {
    Write-Host "status = FAIL"
    Write-Host "missing_source_video = $SourceVideo"
    "missing_source_video = $SourceVideo" | Set-Content -LiteralPath $stderrPath
    "1" | Set-Content -LiteralPath $exitPath
    exit 1
}

$py = $PythonPath
$pythonSource = "provided"

if ([string]::IsNullOrWhiteSpace($py)) {
    $candidateProjectVenv = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $candidateProjectVenv) {
        $py = $candidateProjectVenv
        $pythonSource = "project_venv"
    } else {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($null -eq $cmd) {
            Write-Host "status = FAIL"
            Write-Host "missing_python = No PythonPath provided, no project venv found, and python was not found on PATH."
            "missing_python = No PythonPath provided, no project venv found, and python was not found on PATH." | Set-Content -LiteralPath $stderrPath
            "1" | Set-Content -LiteralPath $exitPath
            exit 1
        }
        $py = $cmd.Source
        $pythonSource = "PATH"
    }
}

Write-Host "python_source = $pythonSource"
Write-Host "python_path = $py"

if ($pythonSource -ne "PATH" -and -not (Test-Path -LiteralPath $py)) {
    Write-Host "status = FAIL"
    Write-Host "missing_python_path = $py"
    "missing_python_path = $py" | Set-Content -LiteralPath $stderrPath
    "1" | Set-Content -LiteralPath $exitPath
    exit 1
}

$pythonVersion = & $py --version 2>&1
Write-Host "python_version = $pythonVersion"

$commandArgs = @($scriptPath)
Write-Host "command = `"$py`" `"$scriptPath`""

& $py @commandArgs > $stdoutPath 2> $stderrPath
$exitCode = $LASTEXITCODE
"$exitCode" | Set-Content -LiteralPath $exitPath

Write-Host "stdout_path = $stdoutPath"
Write-Host "stderr_path = $stderrPath"
Write-Host "exit_code = $exitCode"
Write-Host ""
Write-Host "----- stdout -----"
Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue
Write-Host "----- stderr -----"
Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue
Write-Host "------------------"

if ($exitCode -eq 0) {
    Write-Host "status = PASS"
} else {
    Write-Host "status = FAIL"
}

Write-Host "database_mutation = false"
Write-Host "durable_evidence_written = false"
exit $exitCode
