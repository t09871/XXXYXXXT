# smokeMegaDetectorWrapper.py | v0.3 | 2026-07-06 PDT | Step 4 MegaDetector wrapper smoke with balanced detector input selection

import csv
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path


VERSION = "v0.3"


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


def as_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except Exception:
        return default


def as_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(str(value))
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


def clean_text(value, default=""):
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


def deterministic_id(prefix, *parts):
    import hashlib
    text = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def bool_text(value):
    return "true" if bool(value) else "false"


def normalize_role(class_name):
    text = str(class_name or "").strip().lower()
    if "animal" in text or "bird" in text:
        return "animal"
    if "person" in text or "human" in text:
        return "person"
    if "vehicle" in text or "car" in text or "truck" in text or "bus" in text:
        return "vehicle"
    return "other"


def resolve_source_video(sampler_output_dir, sampler_manifest, session_manifest, sampled_rows):
    candidates = []

    for source in (sampler_manifest, session_manifest):
        if isinstance(source, dict):
            for key in ("source_video", "source_video_path", "input_video", "video_path"):
                value = clean_text(source.get(key))
                if value:
                    candidates.append(value)

            camera_files = source.get("camera_files")
            if isinstance(camera_files, list):
                for item in camera_files:
                    if isinstance(item, dict):
                        for key in ("source_video", "source_video_path", "path", "file_path", "video_path"):
                            value = clean_text(item.get(key))
                            if value:
                                candidates.append(value)

    for row in sampled_rows:
        for key in ("source_video", "source_video_path", "input_video", "video_path"):
            value = clean_text(row.get(key))
            if value:
                candidates.append(value)
        if candidates:
            break

    # Preserve the first usable path, but also allow the first recorded path even if missing.
    for candidate in candidates:
        if Path(candidate).exists():
            return str(Path(candidate)), True

    if candidates:
        return candidates[0], Path(candidates[0]).exists()

    return "", False


def index_extracted_frames(extracted_rows):
    by_frame_id = {}
    by_source_frame_index = {}

    for row in extracted_rows:
        path_value = clean_text(pick(row, [
            "output_frame_path",
            "extracted_frame_path",
            "frame_path",
            "path",
        ]))
        if not path_value:
            continue

        frame_id = clean_text(pick(row, ["frame_id", "sampled_frame_id"]))
        source_frame_index = clean_text(pick(row, ["source_frame_index"]))

        if frame_id:
            by_frame_id[frame_id] = row
        if source_frame_index:
            by_source_frame_index[source_frame_index] = row

    return by_frame_id, by_source_frame_index


def get_existing_extracted_path(frame_row, extracted_by_id, extracted_by_index):
    frame_id = clean_text(pick(frame_row, ["frame_id", "sampled_frame_id"]))
    source_frame_index = clean_text(pick(frame_row, ["source_frame_index"]))

    extracted_row = None
    if frame_id and frame_id in extracted_by_id:
        extracted_row = extracted_by_id[frame_id]
    elif source_frame_index and source_frame_index in extracted_by_index:
        extracted_row = extracted_by_index[source_frame_index]

    if not extracted_row:
        return "", None

    path_value = clean_text(pick(extracted_row, [
        "output_frame_path",
        "extracted_frame_path",
        "frame_path",
        "path",
    ]))

    if path_value and Path(path_value).exists():
        return path_value, extracted_row

    return "", extracted_row


def materialize_frame(source_video, source_frame_index, output_path, jpeg_quality):
    import cv2

    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        return False, "could not open source video"

    cap.set(cv2.CAP_PROP_POS_FRAMES, int(source_frame_index))
    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        return False, f"could not read source frame {source_frame_index}"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = cv2.imwrite(str(output_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])

    if not written:
        return False, f"could not write detector input frame: {output_path}"

    return True, ""


def infer_with_ultralytics(model, image_path, confidence_threshold, device):
    results = model(str(image_path), conf=float(confidence_threshold), device=device, verbose=False)
    detections = []

    if not results:
        return detections

    result = results[0]
    names = getattr(result, "names", {}) or getattr(model, "names", {}) or {}
    boxes = getattr(result, "boxes", None)

    if boxes is None:
        return detections

    for box in boxes:
        xyxy = box.xyxy[0].detach().cpu().numpy().tolist()
        conf = float(box.conf[0].detach().cpu().item()) if getattr(box, "conf", None) is not None else 0.0
        cls = int(box.cls[0].detach().cpu().item()) if getattr(box, "cls", None) is not None else -1
        class_name = str(names.get(cls, cls))

        detections.append({
            "class_id": cls,
            "class_name": class_name,
            "confidence": conf,
            "x1": float(xyxy[0]),
            "y1": float(xyxy[1]),
            "x2": float(xyxy[2]),
            "y2": float(xyxy[3]),
        })

    return detections


def export_crop(image_path, bbox, crop_path, padding_px, jpeg_quality):
    import cv2

    image = cv2.imread(str(image_path))
    if image is None:
        return False, 0, "could not read image for crop export"

    height, width = image.shape[:2]
    x1 = max(0, int(round(bbox["x1"])) - int(padding_px))
    y1 = max(0, int(round(bbox["y1"])) - int(padding_px))
    x2 = min(width, int(round(bbox["x2"])) + int(padding_px))
    y2 = min(height, int(round(bbox["y2"])) + int(padding_px))

    if x2 <= x1 or y2 <= y1:
        return False, 0, "invalid padded crop bounds"

    crop = image[y1:y2, x1:x2]
    crop_path = Path(crop_path)
    crop_path.parent.mkdir(parents=True, exist_ok=True)

    ok = cv2.imwrite(str(crop_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])

    if not ok:
        return False, 0, "could not write crop"

    return True, crop_path.stat().st_size, ""


def frame_row_value(row, key, default=""):
    return clean_text(row.get(key), default)




def row_identity(row):
    frame_id = clean_text(pick(row, ["frame_id", "sampled_frame_id"]))
    source_frame_index = clean_text(pick(row, ["source_frame_index"]))
    sequence_id = clean_text(pick(row, ["sequence_id"]))
    if frame_id:
        return "frame_id:" + frame_id
    if source_frame_index:
        return "source_frame_index:" + source_frame_index
    return "row:" + sequence_id + ":" + str(id(row))


def row_sequence_id(row):
    return clean_text(pick(row, ["sequence_id"]), "sequence-unknown")


def row_source_frame_index(row):
    return as_int(pick(row, ["source_frame_index"]), 0)


def row_offset_abs(row):
    if clean_text(pick(row, ["offset_from_anchor_frames"])) != "":
        return abs(as_int(pick(row, ["offset_from_anchor_frames"]), 999999))
    anchor = as_int(pick(row, ["anchor_frame_index"]), None)
    frame = as_int(pick(row, ["source_frame_index"]), None)
    if anchor is not None and frame is not None:
        return abs(frame - anchor)
    return 999999


def row_is_anchor(row):
    if row_offset_abs(row) == 0:
        return True
    anchor = clean_text(pick(row, ["anchor_frame_index"]))
    frame = clean_text(pick(row, ["source_frame_index"]))
    return bool(anchor and frame and anchor == frame)


def round_robin_groups(groups, max_count, seen, reason, selected):
    added = 0
    keys = sorted(groups.keys())
    positions = {key: 0 for key in keys}

    while len(selected) < max_count:
        any_added = False
        for key in keys:
            rows = groups[key]
            pos = positions[key]
            while pos < len(rows):
                row = rows[pos]
                pos += 1
                ident = row_identity(row)
                if ident in seen:
                    continue
                seen.add(ident)
                selected.append({"row": row, "reason": reason})
                added += 1
                any_added = True
                break
            positions[key] = pos
            if len(selected) >= max_count:
                break
        if not any_added:
            break
    return added


def group_rows_for_selection(rows, sort_key=None):
    groups = {}
    for row in rows:
        groups.setdefault(row_sequence_id(row), []).append(row)
    if sort_key is not None:
        for key in list(groups.keys()):
            groups[key] = sorted(groups[key], key=sort_key)
    return groups


def select_detector_sample_rows(sampled_rows, extracted_by_id, extracted_by_index, max_count):
    """Select detector inputs without taking the first N sampled records.

    Policy:
    1. Prefer existing sampler preview frames, round-robin across sequences.
    2. Then add anchor/center frames, round-robin across sequences.
    3. Then add near-anchor frames, round-robin across sequences.
    4. Then fill remaining slots with broad coverage across sequences.

    This keeps storage bounded while avoiding the failure mode where one dense
    sequence window dominates the detector smoke test.
    """
    max_count = max(1, int(max_count))
    selected = []
    seen = set()

    rows_with_existing_preview = []
    anchor_rows = []
    near_anchor_rows = []
    all_rows = []

    for row in sampled_rows:
        all_rows.append(row)
        existing_path, _ = get_existing_extracted_path(row, extracted_by_id, extracted_by_index)
        if existing_path:
            rows_with_existing_preview.append(row)
        if row_is_anchor(row):
            anchor_rows.append(row)
        if row_offset_abs(row) <= 3:
            near_anchor_rows.append(row)

    preview_groups = group_rows_for_selection(
        rows_with_existing_preview,
        sort_key=lambda r: (row_offset_abs(r), row_source_frame_index(r)),
    )
    anchor_groups = group_rows_for_selection(
        anchor_rows,
        sort_key=lambda r: row_source_frame_index(r),
    )
    near_groups = group_rows_for_selection(
        near_anchor_rows,
        sort_key=lambda r: (row_offset_abs(r), row_source_frame_index(r)),
    )
    coverage_groups = group_rows_for_selection(
        all_rows,
        sort_key=lambda r: (row_offset_abs(r), row_source_frame_index(r)),
    )

    round_robin_groups(preview_groups, max_count, seen, "existing_sampler_preview_round_robin", selected)
    if len(selected) < max_count:
        round_robin_groups(anchor_groups, max_count, seen, "anchor_center_round_robin", selected)
    if len(selected) < max_count:
        round_robin_groups(near_groups, max_count, seen, "near_anchor_round_robin", selected)
    if len(selected) < max_count:
        round_robin_groups(coverage_groups, max_count, seen, "sequence_balanced_coverage", selected)

    # Stable final order by sequence then source frame makes reports easier to inspect.
    selected = sorted(
        selected,
        key=lambda item: (
            row_sequence_id(item["row"]),
            row_source_frame_index(item["row"]),
            item["reason"],
        ),
    )

    for index, item in enumerate(selected):
        item["selection_rank"] = index + 1

    return selected

def build_detector_input_row(config, sampler_frame_row, frame_path, source_kind, materialized, source_video, source_media_context, selection_rank, selection_reason):
    source_frame_index = as_int(pick(sampler_frame_row, ["source_frame_index"], 0), 0)
    frame_id = clean_text(pick(sampler_frame_row, ["frame_id", "sampled_frame_id"]))
    if not frame_id:
        frame_id = deterministic_id("frame", source_video, source_frame_index)

    detector_input_id = deterministic_id("detector-input", frame_id, source_frame_index, frame_path)

    return {
        "detector_input_id": detector_input_id,
        "detector_input_selection_policy": clean_text(config.get("detector_input_selection_policy"), "balanced_preview_sequence"),
        "detector_input_selection_rank": selection_rank,
        "detector_input_selection_reason": selection_reason,
        "frame_id": frame_id,
        "sequence_id": clean_text(pick(sampler_frame_row, ["sequence_id"])),
        "session_id": clean_text(pick(sampler_frame_row, ["session_id"])),
        "camera_id": clean_text(pick(sampler_frame_row, ["camera_id"])),
        "camera_file_id": clean_text(pick(sampler_frame_row, ["camera_file_id"])),
        "camera_role": clean_text(pick(sampler_frame_row, ["camera_role"])),
        "location_id": clean_text(pick(sampler_frame_row, ["location_id"])),
        "source_video": source_video,
        "source_media_context": source_media_context,
        "source_frame_index": source_frame_index,
        "camera_local_time_seconds": clean_text(pick(sampler_frame_row, ["camera_local_time_seconds", "frame_time_seconds"])),
        "sync_status": clean_text(pick(sampler_frame_row, ["sync_status"]), clean_text(config.get("sync_status"), "unsynced")),
        "sync_segment_id": clean_text(pick(sampler_frame_row, ["sync_segment_id"])),
        "sync_offset_seconds": clean_text(pick(sampler_frame_row, ["sync_offset_seconds"])),
        "sync_uncertainty_seconds": clean_text(pick(sampler_frame_row, ["sync_uncertainty_seconds"])),
        "sync_corrected_time_seconds": clean_text(pick(sampler_frame_row, ["sync_corrected_time_seconds"])),
        "evidence_mode": clean_text(pick(sampler_frame_row, ["evidence_mode"]), clean_text(config.get("evidence_mode"), "normal_single_camera")),
        "evidence_purpose": clean_text(pick(sampler_frame_row, ["evidence_purpose"]), clean_text(config.get("evidence_purpose"), "megadetector_smoke")),
        "feeder_reference_id": clean_text(pick(sampler_frame_row, ["feeder_reference_id"]), clean_text(config.get("feeder_reference_id"), "unknown")),
        "feeder_reference_status": clean_text(pick(sampler_frame_row, ["feeder_reference_status"]), clean_text(config.get("feeder_reference_status"), "not_checked")),
        "local_scale_reference_type": clean_text(pick(sampler_frame_row, ["local_scale_reference_type"]), clean_text(config.get("local_scale_reference_type"), "feeder_assembly")),
        "local_scale_confidence": clean_text(pick(sampler_frame_row, ["local_scale_confidence"]), clean_text(config.get("local_scale_confidence"), "unknown")),
        "calibration_state_id": clean_text(pick(sampler_frame_row, ["calibration_state_id"])),
        "calibration_status": clean_text(pick(sampler_frame_row, ["calibration_status"]), clean_text(config.get("calibration_status"), "not_checked")),
        "marker_status": clean_text(pick(sampler_frame_row, ["marker_status"]), clean_text(config.get("marker_status"), "not_checked")),
        "detector_input_frame_path": str(frame_path),
        "detector_input_source_kind": source_kind,
        "detector_input_materialized_by_wrapper": bool_text(materialized),
        "detector_input_purgeable": "true",
    }


def fail(output_dir, message, config=None, details=None, exit_code=20):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "tool": "smokeMegaDetectorWrapper.py",
        "version": VERSION,
        "status": "FAIL",
        "message": message,
        "database_mutation": False,
        "durable_evidence_written": False,
        "debug_outputs_are_purgeable": True,
        "created_at": now_iso(),
        "details": details or {},
    }

    if config:
        report["config"] = config

    write_json(output_dir / "manifest.json", report)
    print("status = FAIL")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("message = " + message)
    print("manifest_json = " + str(output_dir / "manifest.json"))

    return exit_code


def run(config):
    sampler_output_dir = Path(config["sampler_output_dir"])
    output_dir = Path(config["output_dir"])
    model_path = Path(config["model_path"])
    source_media_context = clean_text(config.get("source_media_context"), "debug_smoke")

    output_dir.mkdir(parents=True, exist_ok=True)
    detector_input_dir = output_dir / "detector-input-frames"
    crop_dir = output_dir / "crops"
    detector_input_dir.mkdir(parents=True, exist_ok=True)
    crop_dir.mkdir(parents=True, exist_ok=True)

    if not sampler_output_dir.exists():
        return fail(output_dir, f"Sampler output folder does not exist: {sampler_output_dir}", config, exit_code=2)

    if not model_path.exists():
        return fail(output_dir, f"MegaDetector model does not exist: {model_path}", config, exit_code=3)

    sampler_manifest = read_json(sampler_output_dir / "manifest.json")
    session_manifest = read_json(sampler_output_dir / "session-manifest.json")
    sampled_rows, sampled_headers = read_csv(sampler_output_dir / "sampled-frames.csv")
    extracted_rows, extracted_headers = read_csv(sampler_output_dir / "extracted-frames.csv")

    if not sampled_rows:
        return fail(output_dir, "No sampled frame records found in sampler output.", config, exit_code=4)

    source_video, source_video_available = resolve_source_video(
        sampler_output_dir=sampler_output_dir,
        sampler_manifest=sampler_manifest,
        session_manifest=session_manifest,
        sampled_rows=sampled_rows,
    )

    if not source_video:
        return fail(output_dir, "Could not resolve source_video from sampler output.", config, exit_code=5)

    if not source_video_available:
        return fail(output_dir, f"Resolved source_video is not available: {source_video}", config, exit_code=6)

    source_video_path = Path(source_video)

    max_detector_input_frames = as_int(config.get("max_detector_input_frames"), 20)
    detector_input_selection_policy = clean_text(config.get("detector_input_selection_policy"), "balanced_preview_sequence")
    detector_confidence_threshold = as_float(config.get("detector_confidence_threshold"), 0.05)
    crop_export_mode = clean_text(config.get("crop_export_mode"), "animal_preview")
    max_crop_exports_total = as_int(config.get("max_crop_exports_total"), 30)
    crop_padding_px = as_int(config.get("crop_padding_px"), 24)
    jpeg_quality = as_int(config.get("jpeg_quality"), 92)
    max_bytes_total_mb = as_float(config.get("max_bytes_total_mb"), 250.0)
    device = clean_text(config.get("device"), "cpu")

    extracted_by_id, extracted_by_index = index_extracted_frames(extracted_rows)

    detector_input_rows = []
    detector_frame_result_rows = []
    detection_rows = []
    crop_export_rows = []

    reused_count = 0
    materialized_count = 0
    materialized_bytes = 0
    inference_failures = 0
    crop_export_bytes = 0

    selected_sampled_items = select_detector_sample_rows(
        sampled_rows=sampled_rows,
        extracted_by_id=extracted_by_id,
        extracted_by_index=extracted_by_index,
        max_count=max_detector_input_frames,
    )

    selection_report_rows = []

    for i, selected_item in enumerate(selected_sampled_items):
        sampled_row = selected_item["row"]
        selection_rank = selected_item["selection_rank"]
        selection_reason = selected_item["reason"]
        source_frame_index = as_int(pick(sampled_row, ["source_frame_index"]), 0)
        existing_path, extracted_row = get_existing_extracted_path(sampled_row, extracted_by_id, extracted_by_index)

        if existing_path:
            detector_frame_path = Path(existing_path)
            source_kind = "reused_sampler_preview_frame"
            materialized = False
            reused_count += 1
        else:
            frame_name = f"detector-input-f{source_frame_index:08d}.jpg"
            detector_frame_path = detector_input_dir / frame_name
            ok, error = materialize_frame(
                source_video=source_video_path,
                source_frame_index=source_frame_index,
                output_path=detector_frame_path,
                jpeg_quality=jpeg_quality,
            )
            if not ok:
                inference_failures += 1
                detector_frame_result_rows.append({
                    "detector_input_id": deterministic_id("detector-input-failed", source_video, source_frame_index, i),
                    "source_video": str(source_video_path),
                    "source_media_context": source_media_context,
                    "source_frame_index": source_frame_index,
                    "detector_input_frame_path": str(detector_frame_path),
                    "inference_status": "frame_materialization_failed",
                    "inference_error": error,
                    "detections_count": 0,
                })
                continue

            source_kind = "materialized_from_source_video"
            materialized = True
            materialized_count += 1
            materialized_bytes += detector_frame_path.stat().st_size

        selection_report_rows.append({
            "detector_input_selection_rank": selection_rank,
            "detector_input_selection_reason": selection_reason,
            "frame_id": clean_text(pick(sampled_row, ["frame_id", "sampled_frame_id"])),
            "sequence_id": clean_text(pick(sampled_row, ["sequence_id"])),
            "source_video": str(source_video_path),
            "source_media_context": source_media_context,
            "source_frame_index": source_frame_index,
            "camera_local_time_seconds": clean_text(pick(sampled_row, ["camera_local_time_seconds", "frame_time_seconds"])),
            "offset_from_anchor_frames": clean_text(pick(sampled_row, ["offset_from_anchor_frames"])),
            "anchor_frame_index": clean_text(pick(sampled_row, ["anchor_frame_index"])),
            "detector_input_frame_path": str(detector_frame_path),
            "detector_input_source_kind": source_kind,
            "detector_input_materialized_by_wrapper": bool_text(materialized),
        })

        detector_input_row = build_detector_input_row(
            config=config,
            sampler_frame_row=sampled_row,
            frame_path=detector_frame_path,
            source_kind=source_kind,
            materialized=materialized,
            source_video=str(source_video_path),
            source_media_context=source_media_context,
            selection_rank=selection_rank,
            selection_reason=selection_reason,
        )
        detector_input_rows.append(detector_input_row)

    try:
        from ultralytics import YOLO
    except Exception as exc:
        return fail(output_dir, "Could not import ultralytics YOLO in MegaDetector environment.", config, {"exception": str(exc)}, exit_code=10)

    try:
        model = YOLO(str(model_path))
    except Exception as exc:
        return fail(output_dir, "Could not load MegaDetector model with ultralytics YOLO.", config, {"exception": str(exc)}, exit_code=11)

    start_time = time.time()

    for detector_input_row in detector_input_rows:
        detector_input_id = detector_input_row["detector_input_id"]
        image_path = Path(detector_input_row["detector_input_frame_path"])

        frame_result = {
            "detector_input_id": detector_input_id,
            "frame_id": detector_input_row["frame_id"],
            "sequence_id": detector_input_row["sequence_id"],
            "source_video": detector_input_row["source_video"],
            "source_media_context": detector_input_row["source_media_context"],
            "source_frame_index": detector_input_row["source_frame_index"],
            "camera_local_time_seconds": detector_input_row["camera_local_time_seconds"],
            "detector_input_frame_path": str(image_path),
            "inference_status": "not_run",
            "inference_error": "",
            "detections_count": 0,
        }

        try:
            raw_detections = infer_with_ultralytics(
                model=model,
                image_path=image_path,
                confidence_threshold=detector_confidence_threshold,
                device=device,
            )
            frame_result["inference_status"] = "pass"
            frame_result["detections_count"] = len(raw_detections)
        except Exception as exc:
            inference_failures += 1
            frame_result["inference_status"] = "inference_failed"
            frame_result["inference_error"] = str(exc)
            detector_frame_result_rows.append(frame_result)
            continue

        detector_frame_result_rows.append(frame_result)

        for detection_index, det in enumerate(raw_detections):
            x1 = float(det["x1"])
            y1 = float(det["y1"])
            x2 = float(det["x2"])
            y2 = float(det["y2"])
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            center_x = x1 + width / 2.0
            center_y = y1 + height / 2.0
            area = width * height
            class_name = det["class_name"]
            detection_role = normalize_role(class_name)
            detection_id = deterministic_id(
                "detection",
                detector_input_id,
                detection_index,
                det["class_id"],
                round(det["confidence"], 6),
                round(x1, 2),
                round(y1, 2),
                round(x2, 2),
                round(y2, 2),
            )

            detection_row = {
                "detection_id": detection_id,
                "detector_input_id": detector_input_id,
                "frame_id": detector_input_row["frame_id"],
                "sequence_id": detector_input_row["sequence_id"],
                "session_id": detector_input_row["session_id"],
                "camera_id": detector_input_row["camera_id"],
                "camera_file_id": detector_input_row["camera_file_id"],
                "camera_role": detector_input_row["camera_role"],
                "location_id": detector_input_row["location_id"],
                "source_video": detector_input_row["source_video"],
                "source_media_context": detector_input_row["source_media_context"],
                "source_frame_index": detector_input_row["source_frame_index"],
                "camera_local_time_seconds": detector_input_row["camera_local_time_seconds"],
                "sync_status": detector_input_row["sync_status"],
                "sync_segment_id": detector_input_row["sync_segment_id"],
                "sync_offset_seconds": detector_input_row["sync_offset_seconds"],
                "sync_uncertainty_seconds": detector_input_row["sync_uncertainty_seconds"],
                "sync_corrected_time_seconds": detector_input_row["sync_corrected_time_seconds"],
                "evidence_mode": detector_input_row["evidence_mode"],
                "evidence_purpose": detector_input_row["evidence_purpose"],
                "feeder_reference_id": detector_input_row["feeder_reference_id"],
                "feeder_reference_status": detector_input_row["feeder_reference_status"],
                "local_scale_reference_type": detector_input_row["local_scale_reference_type"],
                "local_scale_confidence": detector_input_row["local_scale_confidence"],
                "calibration_state_id": detector_input_row["calibration_state_id"],
                "calibration_status": detector_input_row["calibration_status"],
                "marker_status": detector_input_row["marker_status"],
                "detector_input_frame_path": detector_input_row["detector_input_frame_path"],
                "detector_backend": "ultralytics_yolo_md_model",
                "detector_model_path": str(model_path),
                "detection_index_in_frame": detection_index,
                "class_name": class_name,
                "class_id": det["class_id"],
                "confidence": round(float(det["confidence"]), 6),
                "detection_role": detection_role,
                "bbox_x1": round(x1, 3),
                "bbox_y1": round(y1, 3),
                "bbox_x2": round(x2, 3),
                "bbox_y2": round(y2, 3),
                "bbox_width": round(width, 3),
                "bbox_height": round(height, 3),
                "bbox_center_x": round(center_x, 3),
                "bbox_center_y": round(center_y, 3),
                "bbox_area_px": round(area, 3),
                "crop_exported": "false",
                "crop_path": "",
                "crop_padding_px": "",
                "crop_to_frame_offset_x": "",
                "crop_to_frame_offset_y": "",
                "crop_to_frame_scale_x": "1.0",
                "crop_to_frame_scale_y": "1.0",
            }
            detection_rows.append(detection_row)

    # Crop export pass after all detections are known.
    crop_export_count = 0
    if crop_export_mode.lower() != "none":
        for detection_row in detection_rows:
            if crop_export_count >= max_crop_exports_total:
                break

            if crop_export_mode.lower() == "animal_preview" and detection_row["detection_role"] != "animal":
                continue

            crop_name = f"{detection_row['detection_id']}-{detection_row['detection_role']}.jpg"
            crop_path = crop_dir / crop_name
            ok, crop_bytes, crop_error = export_crop(
                image_path=Path(detection_row["detector_input_frame_path"]),
                bbox={
                    "x1": as_float(detection_row["bbox_x1"]),
                    "y1": as_float(detection_row["bbox_y1"]),
                    "x2": as_float(detection_row["bbox_x2"]),
                    "y2": as_float(detection_row["bbox_y2"]),
                },
                crop_path=crop_path,
                padding_px=crop_padding_px,
                jpeg_quality=jpeg_quality,
            )

            if not ok:
                continue

            crop_export_count += 1
            crop_export_bytes += crop_bytes
            detection_row["crop_exported"] = "true"
            detection_row["crop_path"] = str(crop_path)
            detection_row["crop_padding_px"] = crop_padding_px
            detection_row["crop_to_frame_offset_x"] = 0
            detection_row["crop_to_frame_offset_y"] = 0

            crop_export_rows.append({
                "crop_export_id": deterministic_id("crop", detection_row["detection_id"], crop_path),
                "detection_id": detection_row["detection_id"],
                "detector_input_id": detection_row["detector_input_id"],
                "frame_id": detection_row["frame_id"],
                "sequence_id": detection_row["sequence_id"],
                "source_video": detection_row["source_video"],
                "source_media_context": detection_row["source_media_context"],
                "source_frame_index": detection_row["source_frame_index"],
                "camera_local_time_seconds": detection_row["camera_local_time_seconds"],
                "class_name": detection_row["class_name"],
                "class_id": detection_row["class_id"],
                "confidence": detection_row["confidence"],
                "detection_role": detection_row["detection_role"],
                "crop_path": str(crop_path),
                "crop_bytes": crop_bytes,
                "crop_padding_px": crop_padding_px,
                "crop_export_mode": crop_export_mode,
                "crop_purgeable": "true",
                "durable_evidence_written": "false",
            })

    elapsed_seconds = time.time() - start_time

    animal_count = sum(1 for row in detection_rows if row["detection_role"] == "animal")
    person_count = sum(1 for row in detection_rows if row["detection_role"] == "person")
    vehicle_count = sum(1 for row in detection_rows if row["detection_role"] == "vehicle")
    other_count = sum(1 for row in detection_rows if row["detection_role"] == "other")

    detector_input_fields = [
        "detector_input_id",
        "detector_input_selection_policy",
        "detector_input_selection_rank",
        "detector_input_selection_reason",
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
        "detector_input_frame_path",
        "detector_input_source_kind",
        "detector_input_materialized_by_wrapper",
        "detector_input_purgeable",
    ]

    detector_frame_result_fields = [
        "detector_input_id",
        "detector_input_selection_policy",
        "detector_input_selection_rank",
        "detector_input_selection_reason",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "detector_input_frame_path",
        "inference_status",
        "inference_error",
        "detections_count",
    ]

    detection_fields = [
        "detection_id",
        "detector_input_id",
        "detector_input_selection_policy",
        "detector_input_selection_rank",
        "detector_input_selection_reason",
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
        "detector_input_frame_path",
        "detector_backend",
        "detector_model_path",
        "detection_index_in_frame",
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
        "crop_exported",
        "crop_path",
        "crop_padding_px",
        "crop_to_frame_offset_x",
        "crop_to_frame_offset_y",
        "crop_to_frame_scale_x",
        "crop_to_frame_scale_y",
    ]

    crop_export_fields = [
        "crop_export_id",
        "detection_id",
        "detector_input_id",
        "detector_input_selection_policy",
        "detector_input_selection_rank",
        "detector_input_selection_reason",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "class_name",
        "class_id",
        "confidence",
        "detection_role",
        "crop_path",
        "crop_bytes",
        "crop_padding_px",
        "crop_export_mode",
        "crop_purgeable",
        "durable_evidence_written",
    ]

    selection_report_fields = [
        "detector_input_selection_rank",
        "detector_input_selection_reason",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "offset_from_anchor_frames",
        "anchor_frame_index",
        "detector_input_frame_path",
        "detector_input_source_kind",
        "detector_input_materialized_by_wrapper",
    ]

    write_csv(output_dir / "detector-input-frames.csv", detector_input_rows, detector_input_fields)
    write_csv(output_dir / "detector-input-selection.csv", selection_report_rows, selection_report_fields)
    write_csv(output_dir / "detector-frame-results.csv", detector_frame_result_rows, detector_frame_result_fields)
    write_csv(output_dir / "megadetector-detections.csv", detection_rows, detection_fields)
    write_json(output_dir / "megadetector-detections.json", detection_rows)
    write_csv(output_dir / "crop-exports.csv", crop_export_rows, crop_export_fields)

    status = "PASS" if detector_input_rows and inference_failures == 0 else "FAIL"

    common_manifest = {
        "tool": "smokeMegaDetectorWrapper.py",
        "version": VERSION,
        "status": status,
        "created_at": now_iso(),
        "database_mutation": False,
        "durable_evidence_written": False,
        "debug_outputs_are_purgeable": True,
        "crop_exports_are_purgeable": True,
        "source_video_is_canonical": True,
        "source_video": str(source_video_path),
        "source_media_context": source_media_context,
        "source_video_available": source_video_path.exists(),
        "sampler_output_dir": str(sampler_output_dir),
        "output_dir": str(output_dir),
        "detector_backend": "ultralytics_yolo_md_model",
        "detector_model_path": str(model_path),
        "device": device,
        "detector_confidence_threshold": detector_confidence_threshold,
        "max_detector_input_frames": max_detector_input_frames,
        "detector_input_selection_policy": detector_input_selection_policy,
        "detector_input_frames": len(detector_input_rows),
        "detector_input_frames_reused": reused_count,
        "detector_input_frames_materialized": materialized_count,
        "materialized_frame_bytes_written": materialized_bytes,
        "detections_written": len(detection_rows),
        "animal_detections": animal_count,
        "person_detections": person_count,
        "vehicle_detections": vehicle_count,
        "other_detections": other_count,
        "crop_export_mode": crop_export_mode,
        "max_crop_exports_total": max_crop_exports_total,
        "crop_exports_written": len(crop_export_rows),
        "crop_export_bytes_written": crop_export_bytes,
        "crop_padding_px": crop_padding_px,
        "jpeg_quality": jpeg_quality,
        "max_bytes_total_mb": max_bytes_total_mb,
        "inference_failures": inference_failures,
        "elapsed_seconds": round(elapsed_seconds, 3),
    }

    manifest = dict(common_manifest)
    manifest.update({
        "files": {
            "detector_input_frames_csv": str(output_dir / "detector-input-frames.csv"),
            "detector_input_selection_csv": str(output_dir / "detector-input-selection.csv"),
            "detector_frame_results_csv": str(output_dir / "detector-frame-results.csv"),
            "detections_csv": str(output_dir / "megadetector-detections.csv"),
            "detections_json": str(output_dir / "megadetector-detections.json"),
            "crop_exports_csv": str(output_dir / "crop-exports.csv"),
            "storage_ledger": str(output_dir / "megadetector-storage-ledger.json"),
            "crop_dir": str(crop_dir),
            "detector_input_dir": str(detector_input_dir),
        },
    })

    storage_ledger = dict(common_manifest)
    storage_ledger.update({
        "source_video_is_canonical": True,
        "detector_input_frames_are_purgeable": True,
        "crop_exports_are_purgeable": True,
        "durable_evidence_written": False,
        "storage_policy": "debug_smoke_bounded_cache",
        "budget_status": "pass" if crop_export_bytes <= (max_bytes_total_mb * 1024 * 1024) else "over_budget",
    })

    write_json(output_dir / "manifest.json", manifest)
    write_json(output_dir / "megadetector-storage-ledger.json", storage_ledger)

    print(f"status = {status}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("source_video_is_canonical = true")
    print(f"source_video = {source_video_path}")
    print(f"source_media_context = {source_media_context}")
    print(f"source_video_available = {str(source_video_path.exists()).lower()}")
    print(f"sampler_output_dir = {sampler_output_dir}")
    print(f"output_dir = {output_dir}")
    print("detector_backend = ultralytics_yolo_md_model")
    print(f"detector_model_path = {model_path}")
    print(f"detector_input_selection_policy = {detector_input_selection_policy}")
    print(f"detector_input_frames = {len(detector_input_rows)}")
    print(f"detector_input_frames_reused = {reused_count}")
    print(f"detector_input_frames_materialized = {materialized_count}")
    print(f"detections_written = {len(detection_rows)}")
    print(f"animal_detections = {animal_count}")
    print(f"person_detections = {person_count}")
    print(f"vehicle_detections = {vehicle_count}")
    print(f"other_detections = {other_count}")
    print(f"crop_export_mode = {crop_export_mode}")
    print(f"crop_exports_written = {len(crop_export_rows)}")
    print(f"crop_export_bytes_written = {crop_export_bytes}")
    print(f"inference_failures = {inference_failures}")
    print(f"manifest_json = {output_dir / 'manifest.json'}")
    print(f"detections_csv = {output_dir / 'megadetector-detections.csv'}")
    print(f"detector_frame_results_csv = {output_dir / 'detector-frame-results.csv'}")
    print(f"detector_inputs_csv = {output_dir / 'detector-input-frames.csv'}")
    print(f"detector_input_selection_csv = {output_dir / 'detector-input-selection.csv'}")
    print(f"crop_exports_csv = {output_dir / 'crop-exports.csv'}")
    print(f"storage_ledger = {output_dir / 'megadetector-storage-ledger.json'}")

    return 0 if status == "PASS" else 20


def main():
    config_path = os.environ.get("BIRDBILL_MD_WRAPPER_CONFIG", "").strip()

    if not config_path:
        print("Missing BIRDBILL_MD_WRAPPER_CONFIG environment variable.", file=sys.stderr)
        return 90

    try:
        config = read_json(config_path)
    except Exception as exc:
        print(f"Could not read wrapper config: {exc}", file=sys.stderr)
        return 91

    output_dir = Path(config.get("output_dir", "."))
    try:
        return run(config)
    except Exception as exc:
        details = {
            "exception": str(exc),
            "traceback": traceback.format_exc(),
        }
        return fail(output_dir, "Unhandled MegaDetector wrapper smoke exception.", config, details, exit_code=99)


if __name__ == "__main__":
    raise SystemExit(main())
