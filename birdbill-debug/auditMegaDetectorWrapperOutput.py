# auditMegaDetectorWrapperOutput.py | v0.2 | 2026-07-06 PDT | MegaDetector wrapper output audit with actionable console details

import csv
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path


VERSION = "v0.2"


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def read_json(path):
    path = Path(path)
    if not path.exists():
        return None, f"missing file: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except Exception as exc:
        return None, f"could not read JSON {path}: {exc}"


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return [], [], f"missing file: {path}"
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            return rows, list(reader.fieldnames or []), None
    except Exception as exc:
        return [], [], f"could not read CSV {path}: {exc}"


def write_json(path, data):
    path = Path(path)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "yes", "1"):
        return True
    if text in ("false", "no", "0"):
        return False
    return None


def as_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except Exception:
        return default


def as_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(str(value))
    except Exception:
        return default


def pick(mapping, names, default=None):
    if not isinstance(mapping, dict):
        return default
    for name in names:
        if name in mapping:
            return mapping.get(name)
    return default


def row_key(row, candidates):
    for name in candidates:
        if name in row and str(row.get(name, "")).strip() != "":
            return str(row.get(name)).strip()
    return None


def count_by_role(rows):
    counts = {"animal": 0, "person": 0, "vehicle": 0, "other": 0, "unknown": 0}
    for row in rows:
        role = row_key(row, ["detection_role", "role", "downstream_role", "class_role"])
        class_name = (row_key(row, ["class_name", "detector_class_name", "name", "label"]) or "").lower()
        if role:
            key = role.lower()
        elif "animal" in class_name or "bird" in class_name:
            key = "animal"
        elif "person" in class_name or "human" in class_name:
            key = "person"
        elif "vehicle" in class_name or "car" in class_name or "truck" in class_name:
            key = "vehicle"
        elif class_name:
            key = "other"
        else:
            key = "unknown"
        if key not in counts:
            key = "other"
        counts[key] += 1
    return counts


def find_bbox(row):
    x1 = pick(row, ["bbox_x1", "x1", "xmin", "left"])
    y1 = pick(row, ["bbox_y1", "y1", "ymin", "top"])
    x2 = pick(row, ["bbox_x2", "x2", "xmax", "right"])
    y2 = pick(row, ["bbox_y2", "y2", "ymax", "bottom"])
    width = pick(row, ["bbox_width", "width", "w"])
    height = pick(row, ["bbox_height", "height", "h"])
    cx = pick(row, ["bbox_center_x", "center_x", "cx"])
    cy = pick(row, ["bbox_center_y", "center_y", "cy"])
    area = pick(row, ["bbox_area_px", "bbox_area", "area_px", "area"])
    return {
        "x1": as_float(x1),
        "y1": as_float(y1),
        "x2": as_float(x2),
        "y2": as_float(y2),
        "width": as_float(width),
        "height": as_float(height),
        "center_x": as_float(cx),
        "center_y": as_float(cy),
        "area": as_float(area),
    }


def row_id(row, prefix, index):
    value = row_key(row, [
        "detection_id",
        "detector_detection_id",
        "crop_id",
        "frame_id",
        "detector_input_id",
        "sampled_frame_id",
    ])
    if value:
        return value
    return f"{prefix}-{index}"


def main():
    config_path = os.environ.get("BIRDBILL_MEGAAUDIT_CONFIG", "").strip()

    if not config_path:
        print("Missing BIRDBILL_MEGAAUDIT_CONFIG environment variable.", file=sys.stderr)
        return 90

    config, config_error = read_json(config_path)

    if config_error:
        print(config_error, file=sys.stderr)
        return 91

    output_dir = Path(config.get("output_dir", "")).resolve()

    if not output_dir.exists():
        print(f"Output folder does not exist: {output_dir}", file=sys.stderr)
        return 92

    stamp = now_stamp()
    report_path = output_dir / f"megadetector-output-audit-report-{stamp}.json"
    summary_path = output_dir / f"megadetector-output-audit-summary-{stamp}.txt"

    errors = []
    warnings = []
    notes = []

    required_files = {
        "manifest": output_dir / "manifest.json",
        "storage_ledger": output_dir / "megadetector-storage-ledger.json",
        "detector_inputs": output_dir / "detector-input-frames.csv",
        "frame_results": output_dir / "detector-frame-results.csv",
        "detections": output_dir / "megadetector-detections.csv",
        "detections_json": output_dir / "megadetector-detections.json",
        "crop_exports": output_dir / "crop-exports.csv",
    }

    for label, path in required_files.items():
        if not path.exists():
            if label == "crop_exports":
                warnings.append(f"Optional/empty crop export file is missing: {path}")
            else:
                errors.append(f"Required file missing: {path}")

    manifest, err = read_json(required_files["manifest"])
    if err:
        errors.append(err)
        manifest = {}

    storage, err = read_json(required_files["storage_ledger"])
    if err:
        errors.append(err)
        storage = {}

    detector_inputs, detector_input_headers, err = read_csv(required_files["detector_inputs"])
    if err:
        errors.append(err)

    frame_results, frame_result_headers, err = read_csv(required_files["frame_results"])
    if err:
        errors.append(err)

    detections, detection_headers, err = read_csv(required_files["detections"])
    if err:
        errors.append(err)

    crop_exports, crop_export_headers, err = read_csv(required_files["crop_exports"])
    if err:
        warnings.append(err)
        crop_exports = []
        crop_export_headers = []

    # Mutation/durable evidence checks.
    for source_name, source_obj in (("manifest", manifest), ("storage_ledger", storage)):
        database_mutation = as_bool(pick(source_obj, ["database_mutation"], None))
        durable_evidence = as_bool(pick(source_obj, ["durable_evidence_written"], None))

        if database_mutation is True:
            errors.append(f"{source_name}: database_mutation is true; Step 2B audit requires false.")
        elif database_mutation is None:
            warnings.append(f"{source_name}: database_mutation field missing or not boolean.")

        if durable_evidence is True:
            errors.append(f"{source_name}: durable_evidence_written is true; smoke output must be debug/cache only.")
        elif durable_evidence is None:
            warnings.append(f"{source_name}: durable_evidence_written field missing or not boolean.")

    # Source video checks.
    source_video = pick(manifest, ["source_video"], None) or pick(storage, ["source_video"], None)
    source_available_flag = as_bool(pick(manifest, ["source_video_available"], None))
    storage_source_available = as_bool(pick(storage, ["source_video_available"], None))

    if source_video:
        if Path(str(source_video)).exists():
            notes.append(f"source video exists: {source_video}")
        else:
            errors.append(f"source video path recorded but file is missing: {source_video}")
    elif source_available_flag is True or storage_source_available is True:
        warnings.append("source_video_available is true, but source_video path was not found in manifest/storage ledger.")
    else:
        warnings.append("No source_video path found in manifest/storage ledger.")

    # Count agreement checks.
    manifest_expected = {
        "detector_input_frames": as_int(pick(manifest, ["detector_input_frames", "detector_input_rows"])),
        "detections_written": as_int(pick(manifest, ["detections_written", "detection_rows"])),
        "crop_exports_written": as_int(pick(manifest, ["crop_exports_written", "crop_export_rows"])),
    }

    storage_expected = {
        "detector_input_frames": as_int(pick(storage, ["detector_input_frames", "detector_input_rows"])),
        "detections_written": as_int(pick(storage, ["detections_written", "detection_rows"])),
        "crop_exports_written": as_int(pick(storage, ["crop_exports_written", "crop_export_rows"])),
    }

    actual_counts = {
        "detector_input_frames": len(detector_inputs),
        "frame_results": len(frame_results),
        "detections_written": len(detections),
        "crop_exports_written": len(crop_exports),
    }

    for key in ("detector_input_frames", "detections_written", "crop_exports_written"):
        if manifest_expected.get(key) is not None and manifest_expected[key] != actual_counts[key]:
            errors.append(f"manifest count mismatch for {key}: manifest={manifest_expected[key]} actual={actual_counts[key]}")
        if storage_expected.get(key) is not None and storage_expected[key] != actual_counts[key]:
            errors.append(f"storage ledger count mismatch for {key}: ledger={storage_expected[key]} actual={actual_counts[key]}")

    if len(frame_results) != len(detector_inputs):
        warnings.append(f"detector-frame-results rows ({len(frame_results)}) do not equal detector-input rows ({len(detector_inputs)}).")

    # Header/schema checks: fail only on blocking absence, warn for preferred fields.
    preferred_detection_fields = [
        "detection_id",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_frame_index",
        "camera_local_time_seconds",
        "class_name",
        "class_id",
        "confidence",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "bbox_center_x",
        "bbox_center_y",
        "bbox_area_px",
    ]

    for field in preferred_detection_fields:
        if field not in detection_headers:
            warnings.append(f"detections CSV missing preferred field: {field}")

    bbox_any = any(field in detection_headers for field in ["bbox_x1", "x1", "xmin", "left"])
    bbox_any = bbox_any and any(field in detection_headers for field in ["bbox_y1", "y1", "ymin", "top"])
    bbox_any = bbox_any and any(field in detection_headers for field in ["bbox_x2", "x2", "xmax", "right"])
    bbox_any = bbox_any and any(field in detection_headers for field in ["bbox_y2", "y2", "ymax", "bottom"])

    if detections and not bbox_any:
        errors.append("detections CSV has rows but no recognizable bbox x1/y1/x2/y2 fields.")

    # Bbox geometry checks.
    bbox_error_limit = 20
    bbox_error_count = 0

    for i, row in enumerate(detections):
        bbox = find_bbox(row)
        rid = row_id(row, "detection", i)

        if bbox["x1"] is None or bbox["y1"] is None or bbox["x2"] is None or bbox["y2"] is None:
            bbox_error_count += 1
            if bbox_error_count <= bbox_error_limit:
                errors.append(f"{rid}: missing required bbox coordinate(s).")
            continue

        if bbox["x2"] <= bbox["x1"] or bbox["y2"] <= bbox["y1"]:
            bbox_error_count += 1
            if bbox_error_count <= bbox_error_limit:
                errors.append(f"{rid}: invalid bbox order x1/y1/x2/y2 = {bbox['x1']}, {bbox['y1']}, {bbox['x2']}, {bbox['y2']}")

        calc_width = bbox["x2"] - bbox["x1"]
        calc_height = bbox["y2"] - bbox["y1"]

        if bbox["width"] is not None and abs(calc_width - bbox["width"]) > 1.01:
            warnings.append(f"{rid}: bbox_width differs from x2-x1 by more than 1px.")
        if bbox["height"] is not None and abs(calc_height - bbox["height"]) > 1.01:
            warnings.append(f"{rid}: bbox_height differs from y2-y1 by more than 1px.")
        if bbox["area"] is not None and abs((calc_width * calc_height) - bbox["area"]) > max(2.0, 0.02 * max(1.0, bbox["area"])):
            warnings.append(f"{rid}: bbox_area_px differs from width*height by more than tolerance.")

    if bbox_error_count > bbox_error_limit:
        errors.append(f"{bbox_error_count - bbox_error_limit} additional bbox coordinate errors suppressed.")

    # Link checks.
    input_ids = set()
    for i, row in enumerate(detector_inputs):
        key = row_key(row, ["detector_input_id", "frame_id", "sampled_frame_id", "input_frame_id"])
        if key:
            input_ids.add(key)

    detection_link_candidates = ["detector_input_id", "frame_id", "sampled_frame_id", "input_frame_id"]
    detection_link_field = next((name for name in detection_link_candidates if name in detection_headers), None)

    if input_ids and detection_link_field:
        missing_links = []
        for i, row in enumerate(detections):
            link_value = row_key(row, [detection_link_field])
            if link_value and link_value not in input_ids:
                missing_links.append((i, link_value))
        if missing_links:
            preview = ", ".join([f"row {i}: {value}" for i, value in missing_links[:10]])
            errors.append(f"detection rows reference unknown detector input ids via {detection_link_field}: {preview}")
    elif detections:
        warnings.append("Could not verify detection-to-detector-input links because link fields were missing or unmatched.")

    detection_ids = set()
    for i, row in enumerate(detections):
        did = row_key(row, ["detection_id", "detector_detection_id"])
        if did:
            detection_ids.add(did)

    crop_detection_link_field = next((name for name in ["detection_id", "detector_detection_id"] if name in crop_export_headers), None)
    if crop_exports and detection_ids and crop_detection_link_field:
        missing_crop_links = []
        for i, row in enumerate(crop_exports):
            link_value = row_key(row, [crop_detection_link_field])
            if link_value and link_value not in detection_ids:
                missing_crop_links.append((i, link_value))
        if missing_crop_links:
            preview = ", ".join([f"row {i}: {value}" for i, value in missing_crop_links[:10]])
            errors.append(f"crop rows reference unknown detection ids via {crop_detection_link_field}: {preview}")
    elif crop_exports:
        warnings.append("Could not fully verify crop-to-detection links because detection_id fields were missing or unmatched.")

    # Role checks.
    role_counts = count_by_role(detections)
    manifest_animal = as_int(pick(manifest, ["animal_detections"]))
    manifest_person = as_int(pick(manifest, ["person_detections"]))
    manifest_vehicle = as_int(pick(manifest, ["vehicle_detections"]))
    manifest_other = as_int(pick(manifest, ["other_detections"]))

    if manifest_animal is not None and manifest_animal != role_counts["animal"]:
        warnings.append(f"animal count differs from audit role calculation: manifest={manifest_animal} audit={role_counts['animal']}")
    if manifest_person is not None and manifest_person != role_counts["person"]:
        warnings.append(f"person count differs from audit role calculation: manifest={manifest_person} audit={role_counts['person']}")
    if manifest_vehicle is not None and manifest_vehicle != role_counts["vehicle"]:
        warnings.append(f"vehicle count differs from audit role calculation: manifest={manifest_vehicle} audit={role_counts['vehicle']}")
    if manifest_other is not None and manifest_other != role_counts["other"]:
        warnings.append(f"other count differs from audit role calculation: manifest={manifest_other} audit={role_counts['other']}")

    if role_counts["person"] > 0:
        notes.append(f"person/context detections preserved: {role_counts['person']}")

    # Crop export checks.
    crop_export_mode = pick(manifest, ["crop_export_mode"], None) or pick(storage, ["crop_export_mode"], None) or "unknown"
    crop_bytes_actual = 0
    crop_file_missing = 0
    crop_size_mismatch = 0

    for i, row in enumerate(crop_exports):
        crop_path_value = row_key(row, ["crop_path", "output_crop_path", "path"])
        if not crop_path_value:
            warnings.append(f"crop row {i}: missing crop_path/output_crop_path field.")
            continue

        crop_path = Path(crop_path_value)
        if not crop_path.exists():
            crop_file_missing += 1
            errors.append(f"crop row {i}: crop file missing: {crop_path}")
            continue

        actual_bytes = crop_path.stat().st_size
        crop_bytes_actual += actual_bytes
        recorded_bytes = as_int(pick(row, ["crop_bytes", "bytes_written", "file_size_bytes", "size_bytes"]))

        if recorded_bytes is not None and recorded_bytes != actual_bytes:
            crop_size_mismatch += 1
            warnings.append(f"crop row {i}: recorded bytes {recorded_bytes} != actual bytes {actual_bytes}")

        if str(crop_export_mode).lower() == "animal_preview":
            role = (row_key(row, ["detection_role", "role", "downstream_role"]) or "").lower()
            cls = (row_key(row, ["class_name", "detector_class_name", "name", "label"]) or "").lower()
            if role and role != "animal":
                errors.append(f"crop row {i}: crop_export_mode=animal_preview but crop role is {role}")
            elif (not role) and cls and ("animal" not in cls and "bird" not in cls):
                warnings.append(f"crop row {i}: animal_preview crop class_name does not look animal/bird: {cls}")

    ledger_crop_bytes = as_int(pick(storage, ["crop_export_bytes_written", "crop_bytes_written", "bytes_written"]))
    manifest_crop_bytes = as_int(pick(manifest, ["crop_export_bytes_written", "crop_bytes_written"]))

    if ledger_crop_bytes is not None and ledger_crop_bytes != crop_bytes_actual:
        errors.append(f"crop byte total mismatch: ledger={ledger_crop_bytes} actual={crop_bytes_actual}")
    if manifest_crop_bytes is not None and manifest_crop_bytes != crop_bytes_actual:
        errors.append(f"crop byte total mismatch: manifest={manifest_crop_bytes} actual={crop_bytes_actual}")

    max_crop_exports_total = as_int(pick(storage, ["max_crop_exports_total"]) or pick(manifest, ["max_crop_exports_total"]))
    if max_crop_exports_total is not None and len(crop_exports) > max_crop_exports_total:
        errors.append(f"crop export count exceeds budget: rows={len(crop_exports)} max={max_crop_exports_total}")

    max_bytes_total_mb = as_float(pick(storage, ["max_bytes_total_mb"]) or pick(manifest, ["max_bytes_total_mb"]))
    if max_bytes_total_mb is not None:
        max_bytes = max_bytes_total_mb * 1024 * 1024
        if crop_bytes_actual > max_bytes:
            errors.append(f"crop bytes exceed max_bytes_total_mb: actual={crop_bytes_actual} max={max_bytes_total_mb} MB")

    status = "PASS" if not errors else "FAIL"

    report = {
        "tool": "auditMegaDetectorWrapperOutput.py",
        "version": VERSION,
        "status": status,
        "database_mutation": False,
        "durable_evidence_written": False,
        "created_at": now_iso(),
        "output_dir": str(output_dir),
        "source_video": source_video,
        "source_video_available": bool(source_video and Path(str(source_video)).exists()) if source_video else (source_available_flag or storage_source_available),
        "detector_backend": pick(manifest, ["detector_backend"], "unknown"),
        "crop_export_mode": crop_export_mode,
        "detector_input_rows": len(detector_inputs),
        "frame_result_rows": len(frame_results),
        "detection_rows": len(detections),
        "role_counts": role_counts,
        "crop_export_rows": len(crop_exports),
        "crop_export_bytes_actual": crop_bytes_actual,
        "errors": errors,
        "warnings": warnings,
        "notes": notes,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "note_count": len(notes),
        "files": {label: str(path) for label, path in required_files.items()},
        "headers": {
            "detector_inputs": detector_input_headers,
            "frame_results": frame_result_headers,
            "detections": detection_headers,
            "crop_exports": crop_export_headers,
        },
    }

    write_json(report_path, report)

    summary_lines = []
    summary_lines.append(f"auditMegaDetectorWrapperOutput.py | {VERSION} | MegaDetector wrapper output audit")
    summary_lines.append(f"status = {status}")
    summary_lines.append("database_mutation = false")
    summary_lines.append("durable_evidence_written = false")
    summary_lines.append(f"output_dir = {output_dir}")
    summary_lines.append(f"detector_input_rows = {len(detector_inputs)}")
    summary_lines.append(f"frame_result_rows = {len(frame_results)}")
    summary_lines.append(f"detection_rows = {len(detections)}")
    summary_lines.append(f"animal_detections = {role_counts['animal']}")
    summary_lines.append(f"person_detections = {role_counts['person']}")
    summary_lines.append(f"vehicle_detections = {role_counts['vehicle']}")
    summary_lines.append(f"other_detections = {role_counts['other']}")
    summary_lines.append(f"unknown_role_detections = {role_counts['unknown']}")
    summary_lines.append(f"crop_export_rows = {len(crop_exports)}")
    summary_lines.append(f"crop_export_bytes_actual = {crop_bytes_actual}")
    summary_lines.append(f"error_count = {len(errors)}")
    summary_lines.append(f"warning_count = {len(warnings)}")
    summary_lines.append("")
    summary_lines.append("ERRORS:")
    if errors:
        for item in errors:
            summary_lines.append(f"- {item}")
    else:
        summary_lines.append("- none")
    summary_lines.append("")
    summary_lines.append("WARNINGS:")
    if warnings:
        for item in warnings:
            summary_lines.append(f"- {item}")
    else:
        summary_lines.append("- none")
    summary_lines.append("")
    summary_lines.append("NOTES:")
    if notes:
        for item in notes:
            summary_lines.append(f"- {item}")
    else:
        summary_lines.append("- none")
    summary_lines.append("")
    summary_lines.append(f"audit_report = {report_path}")

    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"status = {status}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print(f"output_dir = {output_dir}")
    print(f"source_video_available = {str(report['source_video_available']).lower()}")
    print(f"detector_backend = {report['detector_backend']}")
    print(f"crop_export_mode = {crop_export_mode}")
    print(f"detector_input_rows = {len(detector_inputs)}")
    print(f"frame_result_rows = {len(frame_results)}")
    print(f"detection_rows = {len(detections)}")
    print(f"animal_detections = {role_counts['animal']}")
    print(f"person_detections = {role_counts['person']}")
    print(f"vehicle_detections = {role_counts['vehicle']}")
    print(f"other_detections = {role_counts['other']}")
    print(f"crop_export_rows = {len(crop_exports)}")
    print(f"crop_export_bytes_actual = {crop_bytes_actual}")
    print(f"error_count = {len(errors)}")
    print(f"warning_count = {len(warnings)}")
    print(f"audit_report = {report_path}")
    print(f"audit_summary = {summary_path}")

    if errors:
        print("")
        print("ERROR DETAILS:")
        for item in errors[:25]:
            print(f"- {item}")
        if len(errors) > 25:
            print(f"- ... {len(errors) - 25} additional errors omitted from console; see audit summary.")

    if warnings:
        print("")
        print("WARNING DETAILS:")
        for item in warnings[:25]:
            print(f"- {item}")
        if len(warnings) > 25:
            print(f"- ... {len(warnings) - 25} additional warnings omitted from console; see audit summary.")

    return 0 if status == "PASS" else 20


if __name__ == "__main__":
    raise SystemExit(main())
