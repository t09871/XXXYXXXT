# SmartCropper.py | v0.2 | 2026-07-07 PDT | Promoted Birdbill SmartCropper from DLC billtip evidence into refined anatomical crops
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except Exception as exc:  # pragma: no cover - runtime environment check
    Image = None
    PIL_IMPORT_ERROR = exc
else:
    PIL_IMPORT_ERROR = None


SCRIPT_NAME = "SmartCropper.py"
SCRIPT_VERSION = "v0.2"
COMPONENT_NAME = "SmartCropper"
SCHEMA_VERSION = "smart_cropper_v0.2"

DEFAULT_ROOT = Path(r"D:\birdbill")
DEFAULT_DLC_EVIDENCE_CSV = DEFAULT_ROOT / "output" / "debug" / "current-dlc-billtip-from-pose-map" / "dlc-billtip-evidence.csv"
DEFAULT_OUTPUT_DIR = DEFAULT_ROOT / "output" / "debug" / "current-smart-cropper"

DATABASE_MUTATION = False
DURABLE_EVIDENCE_WRITTEN = False


def configure_runtime() -> None:
    for stream_name in ["stdout", "stderr"]:
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def utc_text() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\ufeff", "").strip()


def truthy(value: Any) -> bool:
    return clean(value).lower() in {"true", "1", "yes", "y"}


def safe_float(value: Any) -> float | None:
    text = clean(value)
    if not text:
        return None
    try:
        parsed = float(text)
        if math.isnan(parsed):
            return None
        return parsed
    except Exception:
        return None


def safe_int(value: Any) -> int | None:
    parsed = safe_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.{digits}f}"
    return str(value)


def safe_name(value: str, fallback: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return cleaned or fallback


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)


def reset_output_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def as_box_text(box: tuple[int, int, int, int] | None) -> str:
    if box is None:
        return ""
    return ",".join(str(v) for v in box)


def parse_box_from_roi(row: dict[str, Any], prefix: str) -> tuple[float, float, float, float] | None:
    x1 = safe_float(row.get(f"{prefix}_x1"))
    y1 = safe_float(row.get(f"{prefix}_y1"))
    x2 = safe_float(row.get(f"{prefix}_x2"))
    y2 = safe_float(row.get(f"{prefix}_y2"))
    if None in {x1, y1, x2, y2}:
        return None
    assert x1 is not None and y1 is not None and x2 is not None and y2 is not None
    return x1, y1, x2, y2


def clamp_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    image_width: int,
    image_height: int,
    pad: float = 0.0,
) -> tuple[int, int, int, int] | None:
    left = min(x1, x2) - pad
    top = min(y1, y2) - pad
    right = max(x1, x2) + pad
    bottom = max(y1, y2) + pad

    left_i = max(0, int(math.floor(left)))
    top_i = max(0, int(math.floor(top)))
    right_i = min(image_width, int(math.ceil(right)))
    bottom_i = min(image_height, int(math.ceil(bottom)))

    if right_i <= left_i or bottom_i <= top_i:
        return None
    if (right_i - left_i) < 4 or (bottom_i - top_i) < 4:
        return None
    return left_i, top_i, right_i, bottom_i


def compute_head_bill_box(row: dict[str, Any], image_width: int, image_height: int) -> tuple[tuple[int, int, int, int] | None, str]:
    head_roi = parse_box_from_roi(row, "head_roi")
    base_x = safe_float(row.get("bill_base_x_raw_crop"))
    base_y = safe_float(row.get("bill_base_y_raw_crop"))
    tip_x = safe_float(row.get("bill_tip_x_raw_crop"))
    tip_y = safe_float(row.get("bill_tip_y_raw_crop"))
    bill_len = safe_float(row.get("dlc_bill_length_px"))

    points_x: list[float] = []
    points_y: list[float] = []

    if head_roi is not None:
        hx1, hy1, hx2, hy2 = head_roi
        points_x.extend([hx1, hx2])
        points_y.extend([hy1, hy2])

    if base_x is not None and base_y is not None:
        points_x.append(base_x)
        points_y.append(base_y)
    if tip_x is not None and tip_y is not None:
        points_x.append(tip_x)
        points_y.append(tip_y)

    if not points_x or not points_y:
        return None, "missing head ROI and DLC bill points"

    span_w = max(points_x) - min(points_x)
    span_h = max(points_y) - min(points_y)
    pad = max(6.0, 0.12 * max(image_width, image_height), 0.25 * max(span_w, span_h))
    if bill_len is not None:
        pad = max(pad, 0.35 * bill_len)

    box = clamp_box(min(points_x), min(points_y), max(points_x), max(points_y), image_width, image_height, pad)
    if box is None:
        return None, "computed head_bill crop box invalid after clamping"
    return box, ""


def compute_body_box(row: dict[str, Any], image_width: int, image_height: int) -> tuple[tuple[int, int, int, int] | None, str]:
    body_roi = parse_box_from_roi(row, "body_roi")
    if body_roi is None:
        return None, "missing body ROI"
    x1, y1, x2, y2 = body_roi
    span_w = abs(x2 - x1)
    span_h = abs(y2 - y1)
    pad = max(6.0, 0.10 * max(span_w, span_h), 0.05 * max(image_width, image_height))
    box = clamp_box(x1, y1, x2, y2, image_width, image_height, pad)
    if box is None:
        return None, "computed body crop box invalid after clamping"
    return box, ""


def compute_whole_box(image_width: int, image_height: int) -> tuple[int, int, int, int]:
    return 0, 0, image_width, image_height


def save_crop(image: Any, box: tuple[int, int, int, int], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    crop = image.crop(box)
    crop.save(path, quality=95)


def bill_axis_angle_deg(row: dict[str, Any]) -> float | None:
    base_x = safe_float(row.get("bill_base_x_raw_crop"))
    base_y = safe_float(row.get("bill_base_y_raw_crop"))
    tip_x = safe_float(row.get("bill_tip_x_raw_crop"))
    tip_y = safe_float(row.get("bill_tip_y_raw_crop"))
    if None in {base_x, base_y, tip_x, tip_y}:
        return None
    assert base_x is not None and base_y is not None and tip_x is not None and tip_y is not None
    return math.degrees(math.atan2(tip_y - base_y, tip_x - base_x))


def metric_eligible(row: dict[str, Any], head_bill_crop_ok: bool) -> tuple[bool, str]:
    if not truthy(row.get("dlc_prediction_ok")):
        return False, "dlc_prediction_ok is false"
    if clean(row.get("dlc_billtip_decision")) != "dlc_billtip_evidence_ready":
        return False, f"dlc_billtip_decision={clean(row.get('dlc_billtip_decision'))}"
    bill_len = safe_float(row.get("dlc_bill_length_px"))
    if bill_len is None or bill_len <= 0:
        return False, "missing or non-positive dlc_bill_length_px"
    tip_l = safe_float(row.get("bill_tip_likelihood"))
    base_l = safe_float(row.get("bill_base_likelihood"))
    if tip_l is not None and tip_l < 0.10:
        return False, "bill_tip_likelihood below 0.10"
    if base_l is not None and base_l < 0.10:
        return False, "bill_base_likelihood below 0.10"
    if not head_bill_crop_ok:
        return False, "head_bill_crop not written"
    return True, "metric-ready debug bill length"


def process_rows(
    rows: list[dict[str, str]],
    output_dir: Path,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    whole_dir = output_dir / "whole-candidate-crops"
    head_bill_dir = output_dir / "head-bill-crops"
    body_dir = output_dir / "body-crops"

    manifest_rows: list[dict[str, Any]] = []
    media_files_written = 0
    input_rows_seen = 0
    input_rows_selected = 0
    crop_failure_count = 0

    selected_input_rows = [
        row for row in rows
        if truthy(row.get("smart_cropper_candidate")) and clean(row.get("dlc_billtip_decision")) == "dlc_billtip_evidence_ready"
    ][:max_candidates]

    for index, row in enumerate(selected_input_rows, start=1):
        input_rows_seen += 1
        input_rows_selected += 1

        frame_id = clean(row.get("frame_id")) or f"frame-unknown-{index:05d}"
        detection_id = clean(row.get("detection_id")) or f"detection-unknown-{index:05d}"
        stem = safe_name(f"{index:05d}-{frame_id}-{detection_id}", f"smart-crop-{index:05d}")

        raw_crop_path_text = clean(row.get("raw_crop_path"))
        raw_crop_path = Path(raw_crop_path_text) if raw_crop_path_text else None

        notes: list[str] = []
        whole_path = ""
        head_bill_path = ""
        body_path = ""
        whole_box: tuple[int, int, int, int] | None = None
        head_bill_box: tuple[int, int, int, int] | None = None
        body_box: tuple[int, int, int, int] | None = None
        whole_ok = False
        head_bill_ok = False
        body_ok = False

        image_width = safe_int(row.get("raw_crop_width")) or 0
        image_height = safe_int(row.get("raw_crop_height")) or 0

        if raw_crop_path is None or not raw_crop_path.exists():
            notes.append(f"raw_crop_path missing or unreadable: {raw_crop_path_text}")
        elif Image is None:
            notes.append(f"PIL import failed: {PIL_IMPORT_ERROR}")
        else:
            try:
                with Image.open(raw_crop_path) as image:
                    image = image.convert("RGB")
                    image_width, image_height = image.size

                    whole_box = compute_whole_box(image_width, image_height)
                    whole_out = whole_dir / f"{stem}-whole.jpg"
                    save_crop(image, whole_box, whole_out)
                    whole_path = str(whole_out)
                    whole_ok = True
                    media_files_written += 1

                    head_bill_box, head_bill_reason = compute_head_bill_box(row, image_width, image_height)
                    if head_bill_box is None:
                        notes.append(f"head_bill_crop skipped: {head_bill_reason}")
                    else:
                        head_bill_out = head_bill_dir / f"{stem}-head-bill.jpg"
                        save_crop(image, head_bill_box, head_bill_out)
                        head_bill_path = str(head_bill_out)
                        head_bill_ok = True
                        media_files_written += 1

                    body_box, body_reason = compute_body_box(row, image_width, image_height)
                    if body_box is None:
                        notes.append(f"body_crop skipped: {body_reason}")
                    else:
                        body_out = body_dir / f"{stem}-body.jpg"
                        save_crop(image, body_box, body_out)
                        body_path = str(body_out)
                        body_ok = True
                        media_files_written += 1

            except Exception as exc:
                notes.append(f"image crop exception: {type(exc).__name__}: {exc}")

        metric_ok, metric_reason = metric_eligible(row, head_bill_ok)
        autosort_visual_ready = whole_ok and head_bill_ok and body_ok
        autosort_metric_ready = metric_ok
        decision = "smart_cropper_ready" if autosort_visual_ready else "partial_crop_debug_review"
        if not autosort_visual_ready:
            crop_failure_count += 1

        out: dict[str, Any] = {
            "smart_cropper_schema_version": SCHEMA_VERSION,
            "smart_cropper_decision": decision,
            "smart_cropper_note": "; ".join(notes),
            "smart_cropper_input_index": index,
            "raw_crop_path": raw_crop_path_text,
            "raw_crop_width_actual": image_width,
            "raw_crop_height_actual": image_height,
            "whole_candidate_crop_ok": whole_ok,
            "whole_candidate_crop_path": whole_path,
            "whole_candidate_crop_box_xyxy": as_box_text(whole_box),
            "head_bill_crop_ok": head_bill_ok,
            "head_bill_crop_path": head_bill_path,
            "head_bill_crop_box_xyxy": as_box_text(head_bill_box),
            "body_crop_ok": body_ok,
            "body_crop_path": body_path,
            "body_crop_box_xyxy": as_box_text(body_box),
            "bill_axis_angle_deg": fmt(bill_axis_angle_deg(row)),
            "metric_eligible_bill_length": metric_ok,
            "metric_eligibility_reason": metric_reason,
            "autosort_visual_ready": autosort_visual_ready,
            "autosort_metric_ready": autosort_metric_ready,
        }

        for key, value in row.items():
            out[key] = value

        manifest_rows.append(out)

    summary = {
        "input_rows": len(rows),
        "selected_rows": input_rows_selected,
        "manifest_rows": len(manifest_rows),
        "smart_cropper_ready_count": sum(1 for row in manifest_rows if clean(row.get("smart_cropper_decision")) == "smart_cropper_ready"),
        "partial_crop_debug_review_count": sum(1 for row in manifest_rows if clean(row.get("smart_cropper_decision")) == "partial_crop_debug_review"),
        "metric_eligible_bill_length_count": sum(1 for row in manifest_rows if truthy(row.get("metric_eligible_bill_length"))),
        "autosort_visual_ready_count": sum(1 for row in manifest_rows if truthy(row.get("autosort_visual_ready"))),
        "autosort_metric_ready_count": sum(1 for row in manifest_rows if truthy(row.get("autosort_metric_ready"))),
        "media_files_written": media_files_written,
        "crop_failure_count": crop_failure_count,
    }
    return manifest_rows, summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create SmartCropper refined crops from DLC billtip evidence.")
    parser.add_argument("--dlc-evidence-csv", type=Path, default=DEFAULT_DLC_EVIDENCE_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-candidates", type=int, default=25)
    parser.add_argument("--clear-output", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_runtime()
    args = build_arg_parser().parse_args(argv)

    started_at = time.time()
    output_dir: Path = args.output_dir
    report_path = output_dir / "smart-cropper-report.txt"
    manifest_csv_path = output_dir / "smart-crop-manifest.csv"
    manifest_json_path = output_dir / "manifest.json"

    report_lines: list[str] = []
    run_manifest: dict[str, Any] = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "component": COMPONENT_NAME,
        "schema_version": SCHEMA_VERSION,
        "started_at": utc_text(),
        "completed_at": "",
        "status": "FAIL",
        "python_executable": sys.executable,
        "dlc_evidence_csv": str(args.dlc_evidence_csv),
        "output_dir": str(output_dir),
        "database_mutation": DATABASE_MUTATION,
        "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
        "media_files_written": 0,
    }

    def add(line: str = "") -> None:
        report_lines.append(line)

    try:
        if args.clear_output:
            reset_output_dir(output_dir)
        else:
            output_dir.mkdir(parents=True, exist_ok=True)

        add(f"{SCRIPT_NAME} | {SCRIPT_VERSION} | 2026-07-07 PDT | Promoted Birdbill SmartCropper from DLC billtip evidence into refined anatomical crops")
        add(f"generated={now_text()}")
        add(f"script_name={SCRIPT_NAME}")
        add(f"script_version={SCRIPT_VERSION}")
        add(f"component={COMPONENT_NAME}")
        add(f"smart_cropper_schema_version={SCHEMA_VERSION}")
        add("pipeline_completion_state=pending_runtime_validation")
        add(f"python_executable={sys.executable}")
        add(f"dlc_evidence_csv={args.dlc_evidence_csv}")
        add(f"output_dir={output_dir}")
        add(f"max_candidates={args.max_candidates}")
        add(f"clear_output={args.clear_output}")
        add(f"database_mutation={str(DATABASE_MUTATION).lower()}")
        add(f"durable_evidence_written={str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        add("")

        add("PATH CHECKS")
        add(f"dlc_evidence_csv_exists={args.dlc_evidence_csv.exists()} path={args.dlc_evidence_csv}")
        add(f"output_dir_exists={output_dir.exists()} path={output_dir}")
        add(f"pil_available={Image is not None}")
        if Image is None:
            add(f"pil_import_error={PIL_IMPORT_ERROR}")
        add("")

        if not args.dlc_evidence_csv.exists():
            raise FileNotFoundError(f"DLC evidence CSV not found: {args.dlc_evidence_csv}")
        if Image is None:
            raise RuntimeError(f"PIL/Pillow import failed in this interpreter: {PIL_IMPORT_ERROR}")

        rows = read_csv_dicts(args.dlc_evidence_csv)
        selected_count = sum(
            1 for row in rows
            if truthy(row.get("smart_cropper_candidate")) and clean(row.get("dlc_billtip_decision")) == "dlc_billtip_evidence_ready"
        )
        add("INPUT SUMMARY")
        add(f"input_rows={len(rows)}")
        add(f"eligible_smart_cropper_ready_rows={selected_count}")
        add("")

        crop_rows, summary = process_rows(rows, output_dir, args.max_candidates)
        write_csv(manifest_csv_path, crop_rows)
        write_json(manifest_json_path, {**run_manifest, "summary": summary, "status": "PASS"})

        run_manifest.update(summary)
        run_manifest["smart_crop_manifest_csv"] = str(manifest_csv_path)
        run_manifest["manifest_json"] = str(manifest_json_path)
        run_manifest["pipeline_completion_state"] = "smart_crops_ready_for_metric_prep" if summary["smart_cropper_ready_count"] > 0 else "smart_cropper_partial_debug_review"
        run_manifest["status"] = "PASS"

        add("CROPPER OUTPUTS")
        add(f"manifest_rows={summary['manifest_rows']}")
        add(f"smart_cropper_ready_count={summary['smart_cropper_ready_count']}")
        add(f"partial_crop_debug_review_count={summary['partial_crop_debug_review_count']}")
        add(f"metric_eligible_bill_length_count={summary['metric_eligible_bill_length_count']}")
        add(f"autosort_visual_ready_count={summary['autosort_visual_ready_count']}")
        add(f"autosort_metric_ready_count={summary['autosort_metric_ready_count']}")
        add(f"media_files_written={summary['media_files_written']}")
        add(f"smart_crop_manifest_csv={manifest_csv_path}")
        add(f"whole_candidate_crops_dir={output_dir / 'whole-candidate-crops'}")
        add(f"head_bill_crops_dir={output_dir / 'head-bill-crops'}")
        add(f"body_crops_dir={output_dir / 'body-crops'}")
        add("")

        add("SUMMARY")
        add(f"pipeline_completion_state={run_manifest['pipeline_completion_state']}")
        add(f"database_mutation={str(DATABASE_MUTATION).lower()}")
        add(f"durable_evidence_written={str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        add(f"media_files_written={summary['media_files_written']}")
        add(f"elapsed_seconds={time.time() - started_at:.3f}")
        add("status=PASS")

        return_code = 0

    except Exception as exc:
        run_manifest["status"] = "FAIL"
        run_manifest["error_type"] = type(exc).__name__
        run_manifest["error"] = str(exc)

        add("")
        add("FAILURE")
        add(f"error_type={type(exc).__name__}")
        add(f"error={exc}")
        add("")
        add("TRACEBACK")
        add(traceback.format_exc())
        add("")
        add(f"database_mutation={str(DATABASE_MUTATION).lower()}")
        add(f"durable_evidence_written={str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        add(f"media_files_written={run_manifest.get('media_files_written', 0)}")
        add("status=FAIL")
        return_code = 1

    finally:
        run_manifest["completed_at"] = utc_text()
        run_manifest["report"] = str(report_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(manifest_json_path, run_manifest)
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

        print(f"script_name = {SCRIPT_NAME}")
        print(f"script_version = {SCRIPT_VERSION}")
        print(f"status = {run_manifest.get('status')}")
        print(f"output_dir = {output_dir}")
        print(f"report = {report_path}")
        print(f"smart_crop_manifest_csv = {manifest_csv_path}")
        print(f"manifest_json = {manifest_json_path}")
        print(f"database_mutation = {str(DATABASE_MUTATION).lower()}")
        print(f"durable_evidence_written = {str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        print(f"media_files_written = {run_manifest.get('media_files_written', 0)}")

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
