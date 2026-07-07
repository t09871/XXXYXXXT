# smokeMegaDetectorOneImage.ps1 | v0.1 | 2026-07-06 PDT | One-image MegaDetector inference smoke test for Birdbill

param(
    [string]$ImagePath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = "D:\birdbill"
$scriptDir = "D:\birdbill\debug"
$debugOutDir = "D:\birdbill\output\debug"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

$py = "D:\birdbill\modules\megadetector\megadetector-env\Scripts\python.exe"
$modelPath = "D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt"

$report = Join-Path $debugOutDir "megadetector-one-image-smoke-$stamp.txt"
$jsonOut = Join-Path $debugOutDir "megadetector-one-image-smoke-$stamp.json"
$overlayOut = Join-Path $debugOutDir "megadetector-one-image-smoke-$stamp.jpg"

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

function Pick-Image-File {
    Add-Type -AssemblyName System.Windows.Forms

    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = "Select one image for Birdbill MegaDetector smoke test"
    $dialog.Filter = "Image files (*.jpg;*.jpeg;*.png;*.bmp;*.webp)|*.jpg;*.jpeg;*.png;*.bmp;*.webp|All files (*.*)|*.*"
    $dialog.Multiselect = $false

    $result = $dialog.ShowDialog()

    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        return $dialog.FileName
    }

    return ""
}

function Invoke-Python-Captured {
    param(
        [string]$python,
        [string]$scriptPath,
        [string[]]$commandArgs,
        [int]$timeoutSeconds = 600
    )

    $quotedArgs = @()
    foreach ($item in $commandArgs) {
        $quotedArgs += ('"' + $item + '"')
    }

    $argText = '"' + $scriptPath + '" ' + ($quotedArgs -join " ")

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $python
    $psi.Arguments = $argText
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

Add-Line "Birdbill MegaDetector one-image smoke test | v0.1 | $((Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))"
Add-Line "Root:         $root"
Add-Line "Script dir:   $scriptDir"
Add-Line "Debug output: $debugOutDir"
Add-Line "Report:       $report"
Add-Line "JSON output:  $jsonOut"
Add-Line "Overlay:      $overlayOut"
Add-Line "Python:       $py"
Add-Line "Model:        $modelPath"
Add-Blank
Add-Line "Rules:"
Add-Line "- Script lives in D:\birdbill\debug."
Add-Line "- Generated report/json/overlay go to D:\birdbill\output\debug."
Add-Line "- No guessed image paths."
Add-Line "- If no ImagePath parameter is supplied, use a file picker."
Add-Line "- Run local Ultralytics model test and PytorchWildlife API test separately."
Add-Line "- Normalize detections into Birdbill fields where possible."
Add-Blank

Test-Path-Report "Birdbill root" $root | Out-Null
Test-Path-Report "MegaDetector Python" $py | Out-Null
Test-Path-Report "MegaDetector local model" $modelPath | Out-Null

if (-not (Test-Path -LiteralPath $root)) {
    Stop-With-Report "Birdbill root missing."
}

if (-not (Test-Path -LiteralPath $py)) {
    Stop-With-Report "MegaDetector Python missing."
}

if (-not (Test-Path -LiteralPath $modelPath)) {
    Stop-With-Report "MegaDetector local model missing."
}

if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    Add-Line "No ImagePath parameter supplied. Opening file picker..."
    $ImagePath = Pick-Image-File
}

if ([string]::IsNullOrWhiteSpace($ImagePath)) {
    Stop-With-Report "No image selected."
}

Add-Line "Selected image: $ImagePath"

if (-not (Test-Path -LiteralPath $ImagePath)) {
    Stop-With-Report "Selected image does not exist."
}

$ext = [System.IO.Path]::GetExtension($ImagePath).ToLowerInvariant()
$allowed = @(".jpg", ".jpeg", ".png", ".bmp", ".webp")

if ($allowed -notcontains $ext) {
    Add-Line "WARNING: selected file extension is not a normal image extension: $ext"
}

$pythonCode = @'
import sys
import os
import json
import time
import traceback
from pathlib import Path

image_path = sys.argv[1]
model_path = sys.argv[2]
json_out = sys.argv[3]
overlay_out = sys.argv[4]

start_all = time.time()

report = {
    "script": "smokeMegaDetectorOneImage.ps1",
    "version": "0.1",
    "python": sys.executable,
    "image_path": image_path,
    "model_path": model_path,
    "json_out": json_out,
    "overlay_out": overlay_out,
    "tests": {},
    "normalized_detections_source": None,
    "normalized_detections": [],
}

CLASS_ID_TO_NAME = {
    0: "animal",
    1: "person",
    2: "vehicle",
}

def as_float(x):
    try:
        return float(x)
    except Exception:
        return None

def as_int(x):
    try:
        return int(x)
    except Exception:
        return None

def add_test_result(name, ok, message="", extra=None):
    report["tests"][name] = {
        "ok": bool(ok),
        "message": message,
        "extra": extra or {},
    }

def normalize_ultralytics_results(results):
    normalized = []

    if results is None:
        return normalized

    if not isinstance(results, (list, tuple)):
        result_list = [results]
    else:
        result_list = list(results)

    for result in result_list:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue

        xyxy = getattr(boxes, "xyxy", None)
        conf = getattr(boxes, "conf", None)
        cls = getattr(boxes, "cls", None)

        if xyxy is None:
            continue

        try:
            xyxy_list = xyxy.cpu().numpy().tolist()
        except Exception:
            xyxy_list = xyxy.tolist()

        try:
            conf_list = conf.cpu().numpy().tolist() if conf is not None else [None] * len(xyxy_list)
        except Exception:
            conf_list = conf.tolist() if conf is not None else [None] * len(xyxy_list)

        try:
            cls_list = cls.cpu().numpy().tolist() if cls is not None else [None] * len(xyxy_list)
        except Exception:
            cls_list = cls.tolist() if cls is not None else [None] * len(xyxy_list)

        names = getattr(result, "names", {}) or {}

        for idx, coords in enumerate(xyxy_list):
            class_id = as_int(cls_list[idx]) if idx < len(cls_list) else None
            class_name = None

            if class_id is not None:
                class_name = names.get(class_id, CLASS_ID_TO_NAME.get(class_id, str(class_id)))

            if class_name is None:
                class_name = "unknown"

            confidence = as_float(conf_list[idx]) if idx < len(conf_list) else None

            normalized.append({
                "source": "ultralytics_local_model",
                "class_name": class_name,
                "class_id": class_id,
                "confidence": confidence,
                "x1": as_float(coords[0]) if len(coords) > 0 else None,
                "y1": as_float(coords[1]) if len(coords) > 1 else None,
                "x2": as_float(coords[2]) if len(coords) > 2 else None,
                "y2": as_float(coords[3]) if len(coords) > 3 else None,
            })

    return normalized

def try_ultralytics_local():
    test_name = "ultralytics_local_model"
    t0 = time.time()

    try:
        from ultralytics import YOLO
        import cv2

        model = YOLO(model_path)
        results = model.predict(source=image_path, conf=0.05, save=False, verbose=False)

        normalized = normalize_ultralytics_results(results)

        # Make overlay through Ultralytics plot if possible.
        overlay_written = False
        try:
            if results and len(results) > 0:
                plotted = results[0].plot()
                cv2.imwrite(overlay_out, plotted)
                overlay_written = os.path.exists(overlay_out)
        except Exception as overlay_exc:
            overlay_written = False
            report["tests"][test_name + "_overlay_warning"] = {
                "ok": False,
                "message": repr(overlay_exc),
                "extra": {},
            }

        add_test_result(
            test_name,
            True,
            "Local Ultralytics model inference completed.",
            {
                "seconds": round(time.time() - t0, 3),
                "detection_count": len(normalized),
                "overlay_written": overlay_written,
            },
        )

        return normalized

    except Exception as exc:
        add_test_result(
            test_name,
            False,
            repr(exc),
            {
                "seconds": round(time.time() - t0, 3),
                "traceback": traceback.format_exc(),
            },
        )
        return []

def object_to_jsonable(obj):
    try:
        json.dumps(obj)
        return obj
    except Exception:
        pass

    if isinstance(obj, dict):
        return {str(k): object_to_jsonable(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [object_to_jsonable(x) for x in obj]

    if hasattr(obj, "tolist"):
        try:
            return obj.tolist()
        except Exception:
            pass

    if hasattr(obj, "__dict__"):
        try:
            return {str(k): object_to_jsonable(v) for k, v in vars(obj).items() if not str(k).startswith("_")}
        except Exception:
            pass

    return repr(obj)

def normalize_pytorchwildlife_result(raw):
    normalized = []

    raw_json = object_to_jsonable(raw)

    # This is deliberately conservative. PytorchWildlife output structure may vary by version.
    # We store raw_json for inspection and only normalize obvious detection forms.
    candidates = []

    if isinstance(raw_json, dict):
        for key in ["detections", "prediction", "predictions", "results"]:
            value = raw_json.get(key)
            if isinstance(value, list):
                candidates.extend(value)

        if "boxes" in raw_json:
            candidates.append(raw_json)

    elif isinstance(raw_json, list):
        candidates.extend(raw_json)

    for item in candidates:
        if not isinstance(item, dict):
            continue

        bbox = item.get("bbox", item.get("box", item.get("xyxy", item.get("boxes"))))
        conf = item.get("confidence", item.get("conf", item.get("score")))
        class_id = item.get("class_id", item.get("category_id", item.get("class")))
        class_name = item.get("class_name", item.get("category", item.get("label")))

        if bbox is None:
            continue

        if isinstance(bbox, list) and len(bbox) >= 4:
            cid = as_int(class_id)
            if class_name is None and cid is not None:
                class_name = CLASS_ID_TO_NAME.get(cid, str(cid))

            normalized.append({
                "source": "pytorchwildlife_api",
                "class_name": str(class_name) if class_name is not None else "unknown",
                "class_id": cid,
                "confidence": as_float(conf),
                "x1": as_float(bbox[0]),
                "y1": as_float(bbox[1]),
                "x2": as_float(bbox[2]),
                "y2": as_float(bbox[3]),
            })

    return normalized, raw_json

def try_pytorchwildlife_api():
    test_name = "pytorchwildlife_api"
    t0 = time.time()

    try:
        import torch
        from PytorchWildlife.models import detection as pw_detection

        device = "cuda" if torch.cuda.is_available() else "cpu"

        # Use documented V6 yolov9 compact family. This may use PytorchWildlife's own weight cache.
        model = pw_detection.MegaDetectorV6(device=device, pretrained=True, version="MDV6-yolov9-c")
        raw = model.single_image_detection(image_path)

        normalized, raw_json = normalize_pytorchwildlife_result(raw)

        add_test_result(
            test_name,
            True,
            "PytorchWildlife API single_image_detection completed.",
            {
                "seconds": round(time.time() - t0, 3),
                "device": device,
                "version": "MDV6-yolov9-c",
                "normalized_detection_count": len(normalized),
                "raw_type": str(type(raw)),
                "raw_preview": object_to_jsonable(raw_json),
            },
        )

        return normalized

    except Exception as exc:
        add_test_result(
            test_name,
            False,
            repr(exc),
            {
                "seconds": round(time.time() - t0, 3),
                "traceback": traceback.format_exc(),
            },
        )
        return []

local_norm = try_ultralytics_local()
pw_norm = try_pytorchwildlife_api()

if local_norm:
    report["normalized_detections_source"] = "ultralytics_local_model"
    report["normalized_detections"] = local_norm
elif pw_norm:
    report["normalized_detections_source"] = "pytorchwildlife_api"
    report["normalized_detections"] = pw_norm
else:
    report["normalized_detections_source"] = None
    report["normalized_detections"] = []

report["summary"] = {
    "any_inference_ok": bool(local_norm or report["tests"].get("pytorchwildlife_api", {}).get("ok")),
    "normalized_detection_count": len(report["normalized_detections"]),
    "seconds_total": round(time.time() - start_all, 3),
}

Path(json_out).parent.mkdir(parents=True, exist_ok=True)

with open(json_out, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print("python =", sys.executable)
print("image_path =", image_path)
print("model_path =", model_path)
print("json_out =", json_out)
print("overlay_out =", overlay_out)
print("local_ultralytics_ok =", report["tests"].get("ultralytics_local_model", {}).get("ok"))
print("pytorchwildlife_api_ok =", report["tests"].get("pytorchwildlife_api", {}).get("ok"))
print("normalized_source =", report["normalized_detections_source"])
print("normalized_detection_count =", len(report["normalized_detections"]))
print("any_inference_ok =", report["summary"]["any_inference_ok"])

if not report["summary"]["any_inference_ok"]:
    raise SystemExit(1)
'@

$tmpPy = Join-Path $env:TEMP ("birdbill-megadetector-one-image-" + [guid]::NewGuid().ToString() + ".py")

try {
    Set-Content -LiteralPath $tmpPy -Value $pythonCode -Encoding UTF8

    Add-Blank
    Add-Line "Running Python inference smoke..."
    Add-Line "Temp Python script: $tmpPy"

    $result = Invoke-Python-Captured `
        -python $py `
        -scriptPath $tmpPy `
        -commandArgs @($ImagePath, $modelPath, $jsonOut, $overlayOut) `
        -timeoutSeconds 900

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

    Add-Blank
    Add-Line "Output checks:"
    Test-Path-Report "JSON output" $jsonOut | Out-Null
    Test-Path-Report "Overlay output" $overlayOut | Out-Null

    if ($result.ok) {
        Add-Line "RESULT: OK - at least one MegaDetector inference path completed."
    } else {
        Add-Line "RESULT: FAIL - no inference path completed."
        Add-Line "Exit code: $($result.exit_code)"
    }

} finally {
    if (Test-Path -LiteralPath $tmpPy) {
        Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
    }
}

Add-Blank
Add-Line "Report complete."
Add-Line "Report:      $report"
Add-Line "JSON output: $jsonOut"
Add-Line "Overlay:     $overlayOut"

Save-Report

Write-Host ""
Write-Host "MegaDetector one-image smoke test finished."
Write-Host "Paste this report next:"
Write-Host $report
Write-Host ""