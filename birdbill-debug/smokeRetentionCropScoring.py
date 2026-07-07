# smokeRetentionCropScoring.py | v0.1 | 2026-07-06 PDT | Step 5 retention/crop scoring smoke

import csv
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


VERSION = "v0.1"
REWRITE_STEP = 5


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_csv(path):
    path = Path(path)
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def as_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(str(value))
    except Exception:
        return default


def as_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except Exception:
        return default


def as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("true", "yes", "1", "y"):
        return True
    if text in ("false", "no", "0", "n"):
        return False
    return default


def clean(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def pick(row, names, default=""):
    if not isinstance(row, dict):
        return default
    for name in names:
        if name in row and str(row.get(name, "")).strip() != "":
            return row.get(name)
    return default


def bool_text(value):
    return "true" if bool(value) else "false"


def classify_context_role(role):
    text = str(role or "").strip().lower()
    return text if text in ("animal", "person", "vehicle", "other") else "other"


def optional_crop_metrics(crop_path):
    metrics = {
        "crop_file_exists": False,
        "crop_file_bytes": 0,
        "crop_image_readable": False,
        "crop_image_width": "",
        "crop_image_height": "",
        "crop_laplacian_variance": "",
        "crop_metric_error": "",
    }

    if not crop_path:
        return metrics

    path = Path(crop_path)
    if not path.exists():
        metrics["crop_metric_error"] = f"crop file missing: {path}"
        return metrics

    metrics["crop_file_exists"] = True
    metrics["crop_file_bytes"] = path.stat().st_size

    try:
        import cv2
        image = cv2.imread(str(path))
        if image is None:
            metrics["crop_metric_error"] = "cv2 could not read crop image"
            return metrics

        height, width = image.shape[:2]
        metrics["crop_image_readable"] = True
        metrics["crop_image_width"] = width
        metrics["crop_image_height"] = height

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        metrics["crop_laplacian_variance"] = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3)
        return metrics
    except Exception as exc:
        metrics["crop_metric_error"] = str(exc)
        return metrics


def score_animal_detection(detection_row, crop_row, config):
    confidence = as_float(detection_row.get("confidence"), 0.0)
    bbox_width = as_float(detection_row.get("bbox_width"), 0.0)
    bbox_height = as_float(detection_row.get("bbox_height"), 0.0)
    bbox_area = as_float(detection_row.get("bbox_area_px"), bbox_width * bbox_height)
    crop_path = clean(pick(crop_row or {}, ["crop_path", "output_crop_path", "path"]))
    crop_metrics = optional_crop_metrics(crop_path)

    reasons = []
    cautions = []

    score = 0.0

    # The wrapper already labeled this as animal. That is useful, but not final truth.
    score += 18.0
    reasons.append("animal_role_from_detector")

    if confidence >= 0.70:
        score += 30.0
        reasons.append("high_detector_confidence")
    elif confidence >= 0.40:
        score += 24.0
        reasons.append("medium_detector_confidence")
    elif confidence >= 0.15:
        score += 16.0
        cautions.append("low_detector_confidence")
    else:
        score += 8.0
        cautions.append("very_low_detector_confidence")

    if bbox_width >= 160 and bbox_height >= 160:
        score += 18.0
        reasons.append("large_bbox")
    elif bbox_width >= 80 and bbox_height >= 80:
        score += 14.0
        reasons.append("medium_bbox")
    elif bbox_width >= 40 and bbox_height >= 40:
        score += 8.0
        cautions.append("small_bbox")
    else:
        score += 2.0
        cautions.append("very_small_bbox")

    if bbox_area >= 30000:
        score += 10.0
        reasons.append("large_bbox_area")
    elif bbox_area >= 8000:
        score += 7.0
        reasons.append("moderate_bbox_area")
    elif bbox_area >= 1500:
        score += 3.0
        cautions.append("small_bbox_area")
    else:
        cautions.append("tiny_bbox_area")

    if crop_path and crop_metrics["crop_file_exists"]:
        score += 16.0
        reasons.append("preview_crop_available")
    else:
        cautions.append("no_preview_crop_available")

    if crop_metrics["crop_image_readable"]:
        score += 4.0
        reasons.append("crop_image_readable")

        crop_w = as_int(crop_metrics["crop_image_width"], 0)
        crop_h = as_int(crop_metrics["crop_image_height"], 0)
        blur_metric = as_float(crop_metrics["crop_laplacian_variance"], 0.0)

        if crop_w >= 120 and crop_h >= 120:
            score += 5.0
            reasons.append("crop_dimensions_usable")
        elif crop_w > 0 and crop_h > 0:
            score += 2.0
            cautions.append("crop_dimensions_small")

        if blur_metric >= 100.0:
            score += 4.0
            reasons.append("crop_sharpness_metric_ok")
        elif blur_metric > 0:
            score += 1.0
            cautions.append("crop_sharpness_metric_low")
    elif crop_path:
        cautions.append("crop_image_not_readable")

    # Cap and classify.
    score = max(0.0, min(100.0, round(score, 2)))

    if score >= 75:
        retention_class = "best"
        dlc_candidate = True
        mmpose_candidate = True
    elif score >= 55:
        retention_class = "usable"
        dlc_candidate = True
        mmpose_candidate = True
    elif score >= 30:
        retention_class = "weak_debug"
        dlc_candidate = False
        mmpose_candidate = True
    else:
        retention_class = "discardable"
        dlc_candidate = False
        mmpose_candidate = False

    return score, retention_class, dlc_candidate, mmpose_candidate, reasons, cautions, crop_metrics


def fail(output_dir, message, config=None, details=None, exit_code=20):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "tool": "smokeRetentionCropScoring.py",
        "version": VERSION,
        "rewrite_step": REWRITE_STEP,
        "status": "FAIL",
        "message": message,
        "database_mutation": False,
        "durable_evidence_written": False,
        "created_at": now_iso(),
        "details": details or {},
    }
    if config:
        manifest["config"] = config

    write_json(output_dir / "manifest.json", manifest)

    print("status = FAIL")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("message = " + message)
    print("manifest_json = " + str(output_dir / "manifest.json"))
    return exit_code


def run(config):
    md_output_dir = Path(config["megadetector_output_dir"]).resolve()
    output_dir = Path(config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if not md_output_dir.exists():
        return fail(output_dir, f"MegaDetector output folder does not exist: {md_output_dir}", config, exit_code=2)

    md_manifest = read_json(md_output_dir / "manifest.json")
    md_storage = read_json(md_output_dir / "megadetector-storage-ledger.json")
    detections, detection_headers = read_csv(md_output_dir / "megadetector-detections.csv")
    crops, crop_headers = read_csv(md_output_dir / "crop-exports.csv")
    detector_inputs, detector_input_headers = read_csv(md_output_dir / "detector-input-frames.csv")

    if not detections:
        return fail(output_dir, "No MegaDetector detection rows found.", config, exit_code=3)

    if as_bool(md_manifest.get("database_mutation"), False):
        return fail(output_dir, "Input MegaDetector manifest says database_mutation=true; refusing to score.", config, exit_code=4)

    if as_bool(md_manifest.get("durable_evidence_written"), False):
        return fail(output_dir, "Input MegaDetector manifest says durable_evidence_written=true; refusing debug scoring.", config, exit_code=5)

    crop_by_detection_id = {}
    for row in crops:
        did = clean(pick(row, ["detection_id", "detector_detection_id"]))
        if did:
            crop_by_detection_id[did] = row

    detector_input_by_id = {}
    for row in detector_inputs:
        iid = clean(pick(row, ["detector_input_id", "input_frame_id"]))
        if iid:
            detector_input_by_id[iid] = row

    scoring_policy = clean(config.get("scoring_policy"), "v0.1_conservative_detector_crop_score")
    candidate_rows = []
    context_rows = []
    all_rows = []

    counts = {
        "best": 0,
        "usable": 0,
        "weak_debug": 0,
        "discardable": 0,
        "context_only": 0,
        "animal": 0,
        "person": 0,
        "vehicle": 0,
        "other": 0,
        "dlc_candidate": 0,
        "mmpose_candidate": 0,
    }

    for idx, det in enumerate(detections):
        detection_id = clean(pick(det, ["detection_id"]), f"detection-row-{idx}")
        detector_input_id = clean(pick(det, ["detector_input_id"]))
        role = classify_context_role(pick(det, ["detection_role", "role"]))
        crop_row = crop_by_detection_id.get(detection_id)
        input_row = detector_input_by_id.get(detector_input_id, {})

        counts[role] = counts.get(role, 0) + 1

        common = {
            "retention_score_id": f"retention-{detection_id}",
            "detection_id": detection_id,
            "detector_input_id": detector_input_id,
            "frame_id": clean(pick(det, ["frame_id"])),
            "sequence_id": clean(pick(det, ["sequence_id"])),
            "session_id": clean(pick(det, ["session_id"])),
            "camera_id": clean(pick(det, ["camera_id"])),
            "camera_file_id": clean(pick(det, ["camera_file_id"])),
            "camera_role": clean(pick(det, ["camera_role"])),
            "location_id": clean(pick(det, ["location_id"])),
            "source_video": clean(pick(det, ["source_video"]), clean(md_manifest.get("source_video"))),
            "source_media_context": clean(pick(det, ["source_media_context"]), clean(md_manifest.get("source_media_context"), "unknown")),
            "source_frame_index": clean(pick(det, ["source_frame_index"])),
            "camera_local_time_seconds": clean(pick(det, ["camera_local_time_seconds"])),
            "sync_status": clean(pick(det, ["sync_status"])),
            "sync_segment_id": clean(pick(det, ["sync_segment_id"])),
            "sync_offset_seconds": clean(pick(det, ["sync_offset_seconds"])),
            "sync_uncertainty_seconds": clean(pick(det, ["sync_uncertainty_seconds"])),
            "sync_corrected_time_seconds": clean(pick(det, ["sync_corrected_time_seconds"])),
            "evidence_mode": clean(pick(det, ["evidence_mode"])),
            "evidence_purpose": clean(pick(det, ["evidence_purpose"])),
            "feeder_reference_id": clean(pick(det, ["feeder_reference_id"])),
            "feeder_reference_status": clean(pick(det, ["feeder_reference_status"])),
            "local_scale_reference_type": clean(pick(det, ["local_scale_reference_type"])),
            "local_scale_confidence": clean(pick(det, ["local_scale_confidence"])),
            "calibration_state_id": clean(pick(det, ["calibration_state_id"])),
            "calibration_status": clean(pick(det, ["calibration_status"])),
            "marker_status": clean(pick(det, ["marker_status"])),
            "class_name": clean(pick(det, ["class_name"])),
            "class_id": clean(pick(det, ["class_id"])),
            "confidence": clean(pick(det, ["confidence"])),
            "detection_role": role,
            "bbox_x1": clean(pick(det, ["bbox_x1"])),
            "bbox_y1": clean(pick(det, ["bbox_y1"])),
            "bbox_x2": clean(pick(det, ["bbox_x2"])),
            "bbox_y2": clean(pick(det, ["bbox_y2"])),
            "bbox_width": clean(pick(det, ["bbox_width"])),
            "bbox_height": clean(pick(det, ["bbox_height"])),
            "bbox_center_x": clean(pick(det, ["bbox_center_x"])),
            "bbox_center_y": clean(pick(det, ["bbox_center_y"])),
            "bbox_area_px": clean(pick(det, ["bbox_area_px"])),
            "detector_input_frame_path": clean(pick(det, ["detector_input_frame_path"]), clean(pick(input_row, ["detector_input_frame_path"]))),
            "crop_path": clean(pick(det, ["crop_path"]), clean(pick(crop_row or {}, ["crop_path"]))),
            "crop_exported": clean(pick(det, ["crop_exported"]), "false"),
            "scoring_policy": scoring_policy,
            "database_mutation": "false",
            "durable_evidence_written": "false",
            "retention_output_purgeable": "true",
        }

        if role == "animal":
            score, retention_class, dlc_candidate, mmpose_candidate, reasons, cautions, crop_metrics = score_animal_detection(det, crop_row, config)
            counts[retention_class] += 1
            if dlc_candidate:
                counts["dlc_candidate"] += 1
            if mmpose_candidate:
                counts["mmpose_candidate"] += 1

            row = dict(common)
            row.update({
                "retention_decision": retention_class,
                "retention_score": score,
                "candidate_kind": "bird_candidate",
                "send_to_dlc_candidate": bool_text(dlc_candidate),
                "send_to_mmpose_candidate": bool_text(mmpose_candidate),
                "context_only": "false",
                "score_reasons": ";".join(reasons),
                "score_cautions": ";".join(cautions),
                "crop_file_exists": bool_text(crop_metrics["crop_file_exists"]),
                "crop_file_bytes": crop_metrics["crop_file_bytes"],
                "crop_image_readable": bool_text(crop_metrics["crop_image_readable"]),
                "crop_image_width": crop_metrics["crop_image_width"],
                "crop_image_height": crop_metrics["crop_image_height"],
                "crop_laplacian_variance": crop_metrics["crop_laplacian_variance"],
                "crop_metric_error": crop_metrics["crop_metric_error"],
            })
            candidate_rows.append(row)
            all_rows.append(row)
        else:
            counts["context_only"] += 1
            row = dict(common)
            row.update({
                "retention_decision": "context_only",
                "retention_score": "",
                "candidate_kind": f"{role}_context",
                "send_to_dlc_candidate": "false",
                "send_to_mmpose_candidate": "false",
                "context_only": "true",
                "score_reasons": f"{role}_preserved_as_context",
                "score_cautions": "not_bird_candidate",
                "crop_file_exists": "",
                "crop_file_bytes": "",
                "crop_image_readable": "",
                "crop_image_width": "",
                "crop_image_height": "",
                "crop_laplacian_variance": "",
                "crop_metric_error": "",
            })
            context_rows.append(row)
            all_rows.append(row)

    output_fields = [
        "retention_score_id",
        "detection_id",
        "detector_input_id",
        "frame_id",
        "sequence_id",
        "session_id",
        "camera_id",
        "camera_file_id",
        "camera_role",
        "location_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "sync_status",
        "sync_segment_id",
        "sync_offset_seconds",
        "sync_uncertainty_seconds",
        "sync_corrected_time_seconds",
        "evidence_mode",
        "evidence_purpose",
        "feeder_reference_id",
        "feeder_reference_status",
        "local_scale_reference_type",
        "local_scale_confidence",
        "calibration_state_id",
        "calibration_status",
        "marker_status",
        "class_name",
        "class_id",
        "confidence",
        "detection_role",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "bbox_center_x",
        "bbox_center_y",
        "bbox_area_px",
        "detector_input_frame_path",
        "crop_path",
        "crop_exported",
        "scoring_policy",
        "retention_decision",
        "retention_score",
        "candidate_kind",
        "send_to_dlc_candidate",
        "send_to_mmpose_candidate",
        "context_only",
        "score_reasons",
        "score_cautions",
        "crop_file_exists",
        "crop_file_bytes",
        "crop_image_readable",
        "crop_image_width",
        "crop_image_height",
        "crop_laplacian_variance",
        "crop_metric_error",
        "database_mutation",
        "durable_evidence_written",
        "retention_output_purgeable",
    ]

    write_csv(output_dir / "retention-scores.csv", all_rows, output_fields)
    write_csv(output_dir / "bird-candidates.csv", candidate_rows, output_fields)
    write_csv(output_dir / "context-detections.csv", context_rows, output_fields)
    write_json(output_dir / "retention-scores.json", all_rows)

    status = "PASS"

    manifest = {
        "tool": "smokeRetentionCropScoring.py",
        "version": VERSION,
        "rewrite_step": REWRITE_STEP,
        "status": status,
        "created_at": now_iso(),
        "database_mutation": False,
        "durable_evidence_written": False,
        "debug_outputs_are_purgeable": True,
        "retention_outputs_are_purgeable": True,
        "media_files_written": 0,
        "source_video_is_canonical": True,
        "megadetector_output_dir": str(md_output_dir),
        "output_dir": str(output_dir),
        "source_video": clean(md_manifest.get("source_video")),
        "source_media_context": clean(md_manifest.get("source_media_context"), "unknown"),
        "source_video_available": as_bool(md_manifest.get("source_video_available"), False),
        "scoring_policy": scoring_policy,
        "input_detection_rows": len(detections),
        "animal_detections": counts["animal"],
        "person_detections": counts["person"],
        "vehicle_detections": counts["vehicle"],
        "other_detections": counts["other"],
        "bird_candidate_rows": len(candidate_rows),
        "context_detection_rows": len(context_rows),
        "best_count": counts["best"],
        "usable_count": counts["usable"],
        "weak_debug_count": counts["weak_debug"],
        "discardable_count": counts["discardable"],
        "context_only_count": counts["context_only"],
        "dlc_candidate_count": counts["dlc_candidate"],
        "mmpose_candidate_count": counts["mmpose_candidate"],
        "files": {
            "retention_scores_csv": str(output_dir / "retention-scores.csv"),
            "bird_candidates_csv": str(output_dir / "bird-candidates.csv"),
            "context_detections_csv": str(output_dir / "context-detections.csv"),
            "retention_scores_json": str(output_dir / "retention-scores.json"),
            "storage_ledger": str(output_dir / "retention-storage-ledger.json"),
        },
    }

    storage_ledger = {
        "tool": "smokeRetentionCropScoring.py",
        "version": VERSION,
        "rewrite_step": REWRITE_STEP,
        "database_mutation": False,
        "durable_evidence_written": False,
        "debug_outputs_are_purgeable": True,
        "retention_outputs_are_purgeable": True,
        "source_video_is_canonical": True,
        "media_files_written": 0,
        "bytes_written_media": 0,
        "storage_policy": "records_only_no_media_materialization",
        "megadetector_output_dir": str(md_output_dir),
        "output_dir": str(output_dir),
    }

    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "retention-storage-ledger.json", storage_ledger)

    print(f"status = {status}")
    print(f"rewrite_step = {REWRITE_STEP}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("media_files_written = 0")
    print("source_video_is_canonical = true")
    print(f"megadetector_output_dir = {md_output_dir}")
    print(f"output_dir = {output_dir}")
    print(f"source_video = {manifest['source_video']}")
    print(f"source_media_context = {manifest['source_media_context']}")
    print(f"input_detection_rows = {len(detections)}")
    print(f"animal_detections = {counts['animal']}")
    print(f"person_detections = {counts['person']}")
    print(f"vehicle_detections = {counts['vehicle']}")
    print(f"other_detections = {counts['other']}")
    print(f"bird_candidate_rows = {len(candidate_rows)}")
    print(f"context_detection_rows = {len(context_rows)}")
    print(f"best_count = {counts['best']}")
    print(f"usable_count = {counts['usable']}")
    print(f"weak_debug_count = {counts['weak_debug']}")
    print(f"discardable_count = {counts['discardable']}")
    print(f"dlc_candidate_count = {counts['dlc_candidate']}")
    print(f"mmpose_candidate_count = {counts['mmpose_candidate']}")
    print(f"retention_scores_csv = {output_dir / 'retention-scores.csv'}")
    print(f"bird_candidates_csv = {output_dir / 'bird-candidates.csv'}")
    print(f"context_detections_csv = {output_dir / 'context-detections.csv'}")
    print(f"storage_ledger = {output_dir / 'retention-storage-ledger.json'}")
    print(f"manifest_json = {output_dir / 'manifest.json'}")

    return 0


def main():
    config_path = os.environ.get("BIRDBILL_RETENTION_CONFIG", "").strip()

    if not config_path:
        print("Missing BIRDBILL_RETENTION_CONFIG environment variable.", file=sys.stderr)
        return 90

    try:
        config = read_json(config_path)
    except Exception as exc:
        print(f"Could not read config: {exc}", file=sys.stderr)
        return 91

    output_dir = Path(config.get("output_dir", "."))
    try:
        return run(config)
    except Exception as exc:
        details = {
            "exception": str(exc),
            "traceback": traceback.format_exc(),
        }
        return fail(output_dir, "Unhandled retention/crop scoring exception.", config, details, exit_code=99)


if __name__ == "__main__":
    raise SystemExit(main())
