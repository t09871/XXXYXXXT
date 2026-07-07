# smokeSmartFrameSampler.py | v0.3 | 2026-07-06 PDT | Storage-disciplined sequence-first Smart Frame Sampler smoke runner

import csv
import hashlib
import json
import math
import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

RUNNER_VERSION = "v0.3"
VALID_STORAGE_MODES = {"metadata_only", "preview", "bounded_sequence_cache"}


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def bool_value(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def int_value(config, key, default):
    try:
        return int(config.get(key, default))
    except Exception:
        return int(default)


def float_value(config, key, default):
    try:
        return float(config.get(key, default))
    except Exception:
        return float(default)


def write_json(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_csv(path, rows, fieldnames):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def stable_short_id(text, prefix):
    digest = hashlib.sha1(str(text).encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def load_config():
    env_path = os.environ.get("BIRDBILL_SMOKE_CONFIG", "").strip()

    cli_path = ""
    if len(sys.argv) == 3 and sys.argv[1] == "--config":
        cli_path = sys.argv[2]
    elif len(sys.argv) == 2:
        cli_path = sys.argv[1]
    elif len(sys.argv) > 1:
        raise RuntimeError("Expected no args, one config path, or --config config-path. Received: " + repr(sys.argv[1:]))

    config_path = clean_text(cli_path or env_path)
    if not config_path:
        raise RuntimeError("No config path provided. Expected BIRDBILL_SMOKE_CONFIG or --config config-path.")

    path = Path(config_path)
    if not path.exists():
        raise RuntimeError("Config JSON does not exist: " + str(path))

    config = json.loads(path.read_text(encoding="utf-8-sig"))
    config["config_path"] = str(path)
    return config


def base_manifest(config, status, message):
    return {
        "component": "Smart Frame Sampler",
        "runner": "smokeSmartFrameSampler.py",
        "runner_version": RUNNER_VERSION,
        "status": status,
        "message": message,
        "database_mutation": False,
        "created_at": now_iso(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "config_path": clean_text(config.get("config_path", "")),
        "source_video": clean_text(config.get("source_video", "")),
        "output_dir": clean_text(config.get("output_dir", "")),
    }


def fail(config, message, exit_code, details=None):
    output_dir = Path(clean_text(config.get("output_dir", ".")) or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = base_manifest(config, "FAIL", message)
    if details:
        manifest["details"] = details

    write_json(output_dir / "manifest.json", manifest)

    print("status = FAIL")
    print("database_mutation = false")
    print("message = " + message)
    print("manifest_json = " + str(output_dir / "manifest.json"))

    return exit_code


def validate_config(config):
    sample_every_seconds = float_value(config, "sample_every_seconds", 5.0)
    max_sequences = int_value(config, "max_sequences", 8)
    sequence_pre_seconds = float_value(config, "sequence_pre_seconds", 0.25)
    sequence_post_seconds = float_value(config, "sequence_post_seconds", 0.75)
    sequence_stride_frames = int_value(config, "sequence_stride_frames", 1)
    jpeg_quality = int_value(config, "jpeg_quality", 92)
    storage_mode = clean_text(config.get("storage_mode", "preview")) or "preview"
    max_preview_frames_total = int_value(config, "max_preview_frames_total", 40)
    preview_frames_per_sequence = int_value(config, "preview_frames_per_sequence", 3)
    max_cache_frames_total = int_value(config, "max_cache_frames_total", 250)
    max_bytes_total_mb = float_value(config, "max_bytes_total_mb", 250.0)

    if sample_every_seconds <= 0:
        return "sample_every_seconds must be greater than zero."
    if max_sequences <= 0:
        return "max_sequences must be greater than zero."
    if sequence_pre_seconds < 0:
        return "sequence_pre_seconds must be zero or greater."
    if sequence_post_seconds < 0:
        return "sequence_post_seconds must be zero or greater."
    if sequence_stride_frames <= 0:
        return "sequence_stride_frames must be greater than zero."
    if jpeg_quality < 1 or jpeg_quality > 100:
        return "jpeg_quality must be between 1 and 100."
    if storage_mode not in VALID_STORAGE_MODES:
        return "storage_mode must be one of: " + ", ".join(sorted(VALID_STORAGE_MODES))
    if max_preview_frames_total < 0:
        return "max_preview_frames_total must be zero or greater."
    if preview_frames_per_sequence < 0:
        return "preview_frames_per_sequence must be zero or greater."
    if max_cache_frames_total < 0:
        return "max_cache_frames_total must be zero or greater."
    if max_bytes_total_mb < 0:
        return "max_bytes_total_mb must be zero or greater."
    return ""


def choose_preview_frames(frame_indexes, anchor_frame_index, preview_frames_per_sequence):
    if preview_frames_per_sequence <= 0 or not frame_indexes:
        return set()

    candidates = []
    candidates.append(frame_indexes[0])
    candidates.append(anchor_frame_index)
    candidates.append(frame_indexes[-1])

    if preview_frames_per_sequence > 3:
        middle = frame_indexes[len(frame_indexes) // 2]
        candidates.append(middle)

    selected = []
    frame_set = set(frame_indexes)
    for candidate in candidates:
        if candidate in frame_set and candidate not in selected:
            selected.append(candidate)
        if len(selected) >= preview_frames_per_sequence:
            return set(selected)

    for frame_index in frame_indexes:
        if frame_index not in selected:
            selected.append(frame_index)
        if len(selected) >= preview_frames_per_sequence:
            break

    return set(selected)


def make_contact_sheet(extracted_rows, out_path):
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        print("contact_sheet_status = skipped")
        print("contact_sheet_message = " + str(exc))
        return False

    usable_rows = [row for row in extracted_rows if clean_text(row.get("output_frame_path", ""))]
    if not usable_rows:
        return False

    max_images = min(len(usable_rows), 80)
    selected_rows = usable_rows[:max_images]
    thumb_w = 220
    thumb_h = 150
    label_h = 34
    cols = min(5, len(selected_rows))
    sheet_rows = int(math.ceil(len(selected_rows) / float(cols)))
    canvas = np.full((sheet_rows * (thumb_h + label_h), cols * thumb_w, 3), 255, dtype=np.uint8)

    for index, row in enumerate(selected_rows):
        image_path = row.get("output_frame_path", "")
        img = cv2.imread(image_path)
        if img is None:
            continue

        h, w = img.shape[:2]
        scale = min(thumb_w / float(max(1, w)), thumb_h / float(max(1, h)))
        resized_w = max(1, int(w * scale))
        resized_h = max(1, int(h * scale))
        thumb = cv2.resize(img, (resized_w, resized_h), interpolation=cv2.INTER_AREA)

        sheet_row = index // cols
        sheet_col = index % cols
        x = sheet_col * thumb_w + (thumb_w - resized_w) // 2
        y = sheet_row * (thumb_h + label_h) + (thumb_h - resized_h) // 2
        canvas[y:y + resized_h, x:x + resized_w] = thumb

        label = "{0} f{1}".format(row.get("sequence_id", ""), row.get("source_frame_index", ""))
        label_x = sheet_col * thumb_w + 6
        label_y = sheet_row * (thumb_h + label_h) + thumb_h + 18
        cv2.putText(canvas, label[:32], (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)

    return bool(cv2.imwrite(str(out_path), canvas))


def run(config):
    output_dir = Path(clean_text(config.get("output_dir", "")))
    output_dir.mkdir(parents=True, exist_ok=True)

    validation_message = validate_config(config)
    if validation_message:
        return fail(config, validation_message, 2)

    source_video = Path(clean_text(config.get("source_video", "")))
    if not source_video.exists():
        return fail(config, "Source video does not exist: " + str(source_video), 3)

    sample_every_seconds = float_value(config, "sample_every_seconds", 5.0)
    max_sequences = int_value(config, "max_sequences", 8)
    sequence_pre_seconds = float_value(config, "sequence_pre_seconds", 0.25)
    sequence_post_seconds = float_value(config, "sequence_post_seconds", 0.75)
    sequence_stride_frames = int_value(config, "sequence_stride_frames", 1)
    jpeg_quality = int_value(config, "jpeg_quality", 92)
    contact_sheet_requested = bool_value(config.get("contact_sheet", False))

    storage_mode = clean_text(config.get("storage_mode", "preview")) or "preview"
    max_preview_frames_total = int_value(config, "max_preview_frames_total", 40)
    preview_frames_per_sequence = int_value(config, "preview_frames_per_sequence", 3)
    max_cache_frames_total = int_value(config, "max_cache_frames_total", 250)
    max_bytes_total_mb = float_value(config, "max_bytes_total_mb", 250.0)
    max_bytes_total = int(max_bytes_total_mb * 1024 * 1024)

    try:
        import cv2
    except Exception as exc:
        return fail(config, "OpenCV import failed in selected Python environment.", 10, {"exception": str(exc)})

    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        return fail(config, "OpenCV could not open source video.", 11)

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if fps <= 0:
        cap.release()
        return fail(config, "OpenCV reported invalid FPS: " + str(fps), 12)

    if frame_count <= 0:
        cap.release()
        return fail(config, "OpenCV reported invalid frame count: " + str(frame_count), 13)

    duration_seconds = frame_count / fps
    session_id = clean_text(config.get("session_id", "")) or "debug-session-" + now_stamp()
    camera_file_id = clean_text(config.get("camera_file_id", "")) or stable_short_id(str(source_video.resolve()), "camera-file")
    camera_id = clean_text(config.get("camera_id", "camera-unknown-01")) or "camera-unknown-01"

    pre_frames = int(round(sequence_pre_seconds * fps))
    post_frames = int(round(sequence_post_seconds * fps))
    anchor_step_frames = max(1, int(round(sample_every_seconds * fps)))
    anchor_frames = list(range(0, frame_count, anchor_step_frames))[:max_sequences]

    frames_root = output_dir / "frames"
    if storage_mode != "metadata_only" and (max_preview_frames_total > 0 or max_cache_frames_total > 0):
        frames_root.mkdir(parents=True, exist_ok=True)

    sequence_rows = []
    frame_rows = []
    extracted_rows = []
    bytes_written = 0
    frames_selected_for_extraction = 0
    frames_written = 0
    frames_skipped_by_budget = 0
    budget_stop_reason = ""

    common_context = {
        "session_id": session_id,
        "camera_id": camera_id,
        "camera_file_id": camera_file_id,
        "camera_role": clean_text(config.get("camera_role", "primary_unknown")) or "primary_unknown",
        "location_id": clean_text(config.get("location_id", "unknown")) or "unknown",
        "evidence_mode": clean_text(config.get("evidence_mode", "normal_single_camera")) or "normal_single_camera",
        "evidence_purpose": clean_text(config.get("evidence_purpose", "sampler_smoke")) or "sampler_smoke",
        "feeder_reference_id": clean_text(config.get("feeder_reference_id", "unknown")) or "unknown",
        "feeder_reference_status": clean_text(config.get("feeder_reference_status", "not_checked")) or "not_checked",
        "local_scale_reference_type": clean_text(config.get("local_scale_reference_type", "feeder_assembly")) or "feeder_assembly",
        "local_scale_confidence": clean_text(config.get("local_scale_confidence", "unknown")) or "unknown",
        "calibration_state_id": clean_text(config.get("calibration_state_id", "")),
        "calibration_status": clean_text(config.get("calibration_status", "not_checked")) or "not_checked",
        "marker_status": clean_text(config.get("marker_status", "not_checked")) or "not_checked",
        "sync_status": clean_text(config.get("sync_status", "unsynced")) or "unsynced",
        "sync_segment_id": "",
        "sync_offset_seconds": "",
        "sync_uncertainty_seconds": "",
    }

    for sequence_index, anchor_frame_index in enumerate(anchor_frames):
        sequence_id = "seq-{0:04d}".format(sequence_index + 1)
        start_frame = max(0, anchor_frame_index - pre_frames)
        end_frame = min(frame_count - 1, anchor_frame_index + post_frames)
        sequence_frame_indexes = list(range(start_frame, end_frame + 1, sequence_stride_frames))

        if storage_mode == "metadata_only":
            extraction_frame_set = set()
            extraction_plan = "metadata_only_no_frame_materialization"
        elif storage_mode == "preview":
            extraction_frame_set = choose_preview_frames(sequence_frame_indexes, anchor_frame_index, preview_frames_per_sequence)
            extraction_plan = "bounded_preview_frames_only"
        else:
            extraction_frame_set = set(sequence_frame_indexes)
            extraction_plan = "bounded_sequence_cache"

        sequence_dir = frames_root / sequence_id
        if extraction_frame_set:
            sequence_dir.mkdir(parents=True, exist_ok=True)

        sequence_start_time = start_frame / fps
        sequence_end_time = end_frame / fps
        anchor_time = anchor_frame_index / fps

        sequence_row = dict(common_context)
        sequence_row.update({
            "sequence_id": sequence_id,
            "source_video": str(source_video),
            "source_video_name": source_video.name,
            "sequence_type": "baseline_regular_interval_micro_sequence",
            "sample_mode": "consecutive_window_record_with_bounded_materialization",
            "anchor_type": "regular_interval",
            "sample_reason": "baseline_regular_interval_sequence_record",
            "anchor_index": sequence_index,
            "anchor_frame_index": anchor_frame_index,
            "anchor_time_seconds": round(anchor_time, 6),
            "start_frame_index": start_frame,
            "end_frame_index": end_frame,
            "start_time_seconds": round(sequence_start_time, 6),
            "end_time_seconds": round(sequence_end_time, 6),
            "sequence_stride_frames": sequence_stride_frames,
            "sequence_frame_count_expected": len(sequence_frame_indexes),
            "sequence_frames_planned": len(sequence_frame_indexes),
            "sequence_frames_selected_for_extraction": len(extraction_frame_set),
            "sequence_frames_written": 0,
            "storage_mode": storage_mode,
            "extraction_plan": extraction_plan,
            "frame_folder_path": str(sequence_dir) if extraction_frame_set else "",
            "mini_video_path": "",
            "cache_policy": "source_video_canonical_debug_outputs_purgeable",
            "source_video_is_canonical": "true",
            "extracted_frames_are_purgeable": "true",
            "durable_evidence_written": "false",
            "database_mutation": "false",
        })

        written_for_sequence = 0
        for frame_index in sequence_frame_indexes:
            camera_local_time_seconds = frame_index / fps
            offset_frames = frame_index - anchor_frame_index
            offset_seconds = offset_frames / fps
            frame_time_ms = int(round(camera_local_time_seconds * 1000.0))
            frame_selected = frame_index in extraction_frame_set
            output_name = ""
            output_path = ""
            materialization_status = "not_requested_by_storage_mode"
            materialization_reason = extraction_plan
            file_size_bytes = 0

            if frame_selected:
                frames_selected_for_extraction += 1
                if storage_mode == "preview" and frames_written >= max_preview_frames_total:
                    materialization_status = "skipped_frame_budget"
                    materialization_reason = "max_preview_frames_total_reached"
                    frames_skipped_by_budget += 1
                    if not budget_stop_reason:
                        budget_stop_reason = "max_preview_frames_total_reached"
                elif storage_mode == "bounded_sequence_cache" and frames_written >= max_cache_frames_total:
                    materialization_status = "skipped_frame_budget"
                    materialization_reason = "max_cache_frames_total_reached"
                    frames_skipped_by_budget += 1
                    if not budget_stop_reason:
                        budget_stop_reason = "max_cache_frames_total_reached"
                elif max_bytes_total > 0 and bytes_written >= max_bytes_total:
                    materialization_status = "skipped_byte_budget"
                    materialization_reason = "max_bytes_total_reached"
                    frames_skipped_by_budget += 1
                    if not budget_stop_reason:
                        budget_stop_reason = "max_bytes_total_reached"
                else:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        materialization_status = "read_failed"
                        materialization_reason = "opencv_frame_read_failed"
                        print("frame_read_failed = " + str(frame_index), file=sys.stderr)
                    else:
                        output_name = "{0}-f{1:08d}-t{2:010d}-o{3:+05d}.jpg".format(
                            sequence_id,
                            frame_index,
                            frame_time_ms,
                            offset_frames,
                        )
                        output_file = sequence_dir / output_name
                        write_ok = cv2.imwrite(str(output_file), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
                        if write_ok:
                            output_path = str(output_file)
                            try:
                                file_size_bytes = output_file.stat().st_size
                            except Exception:
                                file_size_bytes = 0
                            bytes_written += file_size_bytes
                            frames_written += 1
                            written_for_sequence += 1
                            materialization_status = "written_debug_cache"
                            materialization_reason = "bounded_materialization_for_smoke_inspection"
                        else:
                            materialization_status = "write_failed"
                            materialization_reason = "opencv_frame_write_failed"
                            print("frame_write_failed = " + str(output_file), file=sys.stderr)

            frame_row = dict(common_context)
            frame_row.update({
                "frame_id": "frame-{0:04d}-{1:08d}".format(sequence_index + 1, frame_index),
                "sequence_id": sequence_id,
                "source_video": str(source_video),
                "source_video_name": source_video.name,
                "source_frame_index": frame_index,
                "camera_local_time_seconds": round(camera_local_time_seconds, 6),
                "sync_corrected_time_seconds": "",
                "frame_role": "sequence_member",
                "anchor_index": sequence_index,
                "anchor_frame_index": anchor_frame_index,
                "offset_from_anchor_frames": offset_frames,
                "offset_from_anchor_seconds": round(offset_seconds, 6),
                "anchor_type": "regular_interval",
                "sample_reason": "baseline_regular_interval_sequence_record",
                "storage_mode": storage_mode,
                "frame_selected_for_extraction": "true" if frame_selected else "false",
                "frame_materialization_status": materialization_status,
                "materialization_reason": materialization_reason,
                "output_frame_path": output_path,
                "output_frame_name": output_name,
                "output_file_size_bytes": file_size_bytes,
                "jpeg_quality": jpeg_quality,
                "cache_policy": "source_video_canonical_debug_outputs_purgeable",
                "source_video_is_canonical": "true",
                "extracted_frames_are_purgeable": "true",
                "durable_evidence_written": "false",
                "database_mutation": "false",
            })
            frame_rows.append(frame_row)
            if materialization_status == "written_debug_cache":
                extracted_rows.append(frame_row)

        sequence_row["sequence_frames_written"] = written_for_sequence
        sequence_rows.append(sequence_row)

    cap.release()

    sequence_fieldnames = [
        "session_id", "camera_id", "camera_file_id", "camera_role", "location_id",
        "evidence_mode", "evidence_purpose", "feeder_reference_id", "feeder_reference_status",
        "local_scale_reference_type", "local_scale_confidence", "calibration_state_id",
        "calibration_status", "marker_status", "sync_status", "sync_segment_id",
        "sync_offset_seconds", "sync_uncertainty_seconds", "sequence_id", "source_video",
        "source_video_name", "sequence_type", "sample_mode", "anchor_type", "sample_reason",
        "anchor_index", "anchor_frame_index", "anchor_time_seconds", "start_frame_index",
        "end_frame_index", "start_time_seconds", "end_time_seconds", "sequence_stride_frames",
        "sequence_frame_count_expected", "sequence_frames_planned", "sequence_frames_selected_for_extraction",
        "sequence_frames_written", "storage_mode", "extraction_plan", "frame_folder_path",
        "mini_video_path", "cache_policy", "source_video_is_canonical", "extracted_frames_are_purgeable",
        "durable_evidence_written", "database_mutation",
    ]

    frame_fieldnames = [
        "session_id", "camera_id", "camera_file_id", "camera_role", "location_id",
        "evidence_mode", "evidence_purpose", "feeder_reference_id", "feeder_reference_status",
        "local_scale_reference_type", "local_scale_confidence", "calibration_state_id",
        "calibration_status", "marker_status", "sync_status", "sync_segment_id",
        "sync_offset_seconds", "sync_uncertainty_seconds", "frame_id", "sequence_id",
        "source_video", "source_video_name", "source_frame_index", "camera_local_time_seconds",
        "sync_corrected_time_seconds", "frame_role", "anchor_index", "anchor_frame_index",
        "offset_from_anchor_frames", "offset_from_anchor_seconds", "anchor_type", "sample_reason",
        "storage_mode", "frame_selected_for_extraction", "frame_materialization_status",
        "materialization_reason", "output_frame_path", "output_frame_name", "output_file_size_bytes",
        "jpeg_quality", "cache_policy", "source_video_is_canonical", "extracted_frames_are_purgeable",
        "durable_evidence_written", "database_mutation",
    ]

    extracted_fieldnames = frame_fieldnames

    sampled_sequences_csv = output_dir / "sampled-sequences.csv"
    sampled_frames_csv = output_dir / "sampled-frames.csv"
    extracted_frames_csv = output_dir / "extracted-frames.csv"
    write_csv(sampled_sequences_csv, sequence_rows, sequence_fieldnames)
    write_csv(sampled_frames_csv, frame_rows, frame_fieldnames)
    write_csv(extracted_frames_csv, extracted_rows, extracted_fieldnames)

    contact_sheet_path = output_dir / "contact-sheet.jpg"
    contact_sheet_written = False
    if contact_sheet_requested:
        contact_sheet_written = make_contact_sheet(extracted_rows, contact_sheet_path)

    storage_ledger = {
        "component": "Smart Frame Sampler",
        "runner_version": RUNNER_VERSION,
        "created_at": now_iso(),
        "database_mutation": False,
        "storage_mode": storage_mode,
        "source_video_is_canonical": True,
        "debug_outputs_are_purgeable": True,
        "frames_folder_purgeable": True,
        "extracted_frames_are_purgeable": True,
        "durable_evidence_written": False,
        "promotion_status": "not_promoted",
        "cache_policy": "source_video_canonical_debug_outputs_purgeable",
        "source_video": str(source_video),
        "output_dir": str(output_dir),
        "frames_root": str(frames_root) if frames_root.exists() else "",
        "sequence_records_written": len(sequence_rows),
        "frame_records_written": len(frame_rows),
        "frames_selected_for_extraction": frames_selected_for_extraction,
        "frames_written": frames_written,
        "frames_skipped_by_budget": frames_skipped_by_budget,
        "bytes_written": bytes_written,
        "megabytes_written": round(bytes_written / (1024 * 1024), 6),
        "max_preview_frames_total": max_preview_frames_total,
        "preview_frames_per_sequence": preview_frames_per_sequence,
        "max_cache_frames_total": max_cache_frames_total,
        "max_bytes_total_mb": max_bytes_total_mb,
        "budget_stop_reason": budget_stop_reason,
        "storage_warning": "Sequence records are cheap; frame images are bounded purgeable debug cache only.",
    }
    write_json(output_dir / "storage-ledger.json", storage_ledger)

    session_manifest = {
        "session_id": session_id,
        "session_type": "debug_smoke_session",
        "database_mutation": False,
        "created_at": now_iso(),
        "source_video": str(source_video),
        "source_video_name": source_video.name,
        "storage_policy": storage_ledger,
        "camera_files": [
            {
                "camera_file_id": camera_file_id,
                "camera_id": camera_id,
                "source_video": str(source_video),
                "source_video_name": source_video.name,
                "fps": fps,
                "frame_count": frame_count,
                "duration_seconds": round(duration_seconds, 6),
                "width": width,
                "height": height,
                "camera_role": common_context["camera_role"],
                "location_id": common_context["location_id"],
                "evidence_mode": common_context["evidence_mode"],
                "sync_status": common_context["sync_status"],
                "calibration_status": common_context["calibration_status"],
                "marker_status": common_context["marker_status"],
                "feeder_reference_status": common_context["feeder_reference_status"],
                "local_scale_reference_type": common_context["local_scale_reference_type"],
            }
        ],
        "sync_events": [],
        "sync_segments": [],
        "calibration_assets": [],
        "feeder_reference": {
            "feeder_reference_id": common_context["feeder_reference_id"],
            "feeder_reference_status": common_context["feeder_reference_status"],
            "local_scale_reference_type": common_context["local_scale_reference_type"],
            "local_scale_confidence": common_context["local_scale_confidence"],
        },
    }

    write_json(output_dir / "session-manifest.json", session_manifest)

    status = "PASS" if sequence_rows else "FAIL"
    if storage_mode == "metadata_only" and sequence_rows:
        message = "Sequence and frame records written without frame materialization."
    elif frames_written:
        message = "Storage-disciplined sequence records and bounded frame cache written."
    else:
        message = "Sequence records written, but no frames were materialized."

    manifest = base_manifest(config, status, message)
    manifest.update({
        "session_id": session_id,
        "camera_id": camera_id,
        "camera_file_id": camera_file_id,
        "frames_root": str(frames_root) if frames_root.exists() else "",
        "session_manifest": str(output_dir / "session-manifest.json"),
        "sampled_sequences_csv": str(sampled_sequences_csv),
        "sampled_frames_csv": str(sampled_frames_csv),
        "extracted_frames_csv": str(extracted_frames_csv),
        "storage_ledger": str(output_dir / "storage-ledger.json"),
        "contact_sheet": str(contact_sheet_path) if contact_sheet_written else "",
        "opencv_version": cv2.__version__,
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": round(duration_seconds, 6),
        "width": width,
        "height": height,
        "sample_every_seconds": sample_every_seconds,
        "anchor_step_frames": anchor_step_frames,
        "max_sequences": max_sequences,
        "sequence_pre_seconds": sequence_pre_seconds,
        "sequence_post_seconds": sequence_post_seconds,
        "sequence_stride_frames": sequence_stride_frames,
        "sequence_count": len(sequence_rows),
        "frame_records_written": len(frame_rows),
        "frames_selected_for_extraction": frames_selected_for_extraction,
        "frames_written": frames_written,
        "bytes_written": bytes_written,
        "megabytes_written": round(bytes_written / (1024 * 1024), 6),
        "storage_mode": storage_mode,
        "max_preview_frames_total": max_preview_frames_total,
        "preview_frames_per_sequence": preview_frames_per_sequence,
        "max_cache_frames_total": max_cache_frames_total,
        "max_bytes_total_mb": max_bytes_total_mb,
        "debug_outputs_are_purgeable": True,
        "durable_evidence_written": False,
        "evidence_mode": common_context["evidence_mode"],
        "evidence_purpose": common_context["evidence_purpose"],
        "feeder_reference_status": common_context["feeder_reference_status"],
        "local_scale_reference_type": common_context["local_scale_reference_type"],
        "calibration_status": common_context["calibration_status"],
        "marker_status": common_context["marker_status"],
        "sync_status": common_context["sync_status"],
    })

    write_json(output_dir / "manifest.json", manifest)

    print("status = " + status)
    print("database_mutation = false")
    print("source_video = " + str(source_video))
    print("output_dir = " + str(output_dir))
    print("session_id = " + session_id)
    print("camera_file_id = " + camera_file_id)
    print("fps = " + str(fps))
    print("frame_count = " + str(frame_count))
    print("duration_seconds = {0:.3f}".format(duration_seconds))
    print("sequence_count = " + str(len(sequence_rows)))
    print("frame_records_written = " + str(len(frame_rows)))
    print("storage_mode = " + storage_mode)
    print("frames_selected_for_extraction = " + str(frames_selected_for_extraction))
    print("frames_written = " + str(frames_written))
    print("bytes_written = " + str(bytes_written))
    print("megabytes_written = {0:.6f}".format(bytes_written / (1024 * 1024)))
    print("debug_outputs_are_purgeable = true")
    print("durable_evidence_written = false")
    print("manifest_json = " + str(output_dir / "manifest.json"))
    print("session_manifest = " + str(output_dir / "session-manifest.json"))
    print("sampled_sequences_csv = " + str(sampled_sequences_csv))
    print("sampled_frames_csv = " + str(sampled_frames_csv))
    print("extracted_frames_csv = " + str(extracted_frames_csv))
    print("storage_ledger = " + str(output_dir / "storage-ledger.json"))
    if contact_sheet_written:
        print("contact_sheet = " + str(contact_sheet_path))

    return 0 if sequence_rows else 20


def main():
    config = {}
    try:
        config = load_config()
        return run(config)
    except Exception as exc:
        details = {
            "exception": str(exc),
            "traceback": traceback.format_exc(),
            "argv": sys.argv,
            "env_config": os.environ.get("BIRDBILL_SMOKE_CONFIG", ""),
        }
        if not config:
            fallback_output = Path.cwd() / ("smart-frame-sampler-failure-" + now_stamp())
            config = {"output_dir": str(fallback_output), "source_video": ""}
        return fail(config, "Unhandled Smart Frame Sampler runner exception.", 99, details)


if __name__ == "__main__":
    raise SystemExit(main())
