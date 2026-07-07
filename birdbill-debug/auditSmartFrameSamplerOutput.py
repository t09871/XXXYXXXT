# auditSmartFrameSamplerOutput.py | v0.1 | 2026-07-06 PDT | Validate Smart Frame Sampler smoke output schema/storage contract

import csv
import json
import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

RUNNER_NAME = "auditSmartFrameSamplerOutput.py"
RUNNER_VERSION = "v0.1"

REQUIRED_FILES = {
    "manifest": "manifest.json",
    "session_manifest": "session-manifest.json",
    "sampled_sequences": "sampled-sequences.csv",
    "sampled_frames": "sampled-frames.csv",
    "extracted_frames": "extracted-frames.csv",
    "storage_ledger": "storage-ledger.json",
}

CONTEXT_FIELDS = [
    "session_id",
    "camera_id",
    "camera_file_id",
    "camera_role",
    "location_id",
    "evidence_mode",
    "evidence_purpose",
    "feeder_reference_id",
    "feeder_reference_status",
    "local_scale_reference_type",
    "local_scale_confidence",
    "calibration_state_id",
    "calibration_status",
    "marker_status",
    "sync_status",
    "sync_segment_id",
    "sync_offset_seconds",
    "sync_uncertainty_seconds",
]

REQUIRED_SEQUENCE_FIELDS = CONTEXT_FIELDS + [
    "sequence_id",
    "source_video",
    "source_video_name",
    "sequence_type",
    "sample_mode",
    "anchor_type",
    "sample_reason",
    "anchor_index",
    "anchor_frame_index",
    "anchor_time_seconds",
    "start_frame_index",
    "end_frame_index",
    "start_time_seconds",
    "end_time_seconds",
    "sequence_stride_frames",
    "sequence_frame_count_expected",
    "sequence_frames_planned",
    "sequence_frames_selected_for_extraction",
    "sequence_frames_written",
    "storage_mode",
    "extraction_plan",
    "frame_folder_path",
    "mini_video_path",
    "cache_policy",
    "source_video_is_canonical",
    "extracted_frames_are_purgeable",
    "durable_evidence_written",
    "database_mutation",
]

REQUIRED_FRAME_FIELDS = CONTEXT_FIELDS + [
    "frame_id",
    "sequence_id",
    "source_video",
    "source_video_name",
    "source_frame_index",
    "camera_local_time_seconds",
    "sync_corrected_time_seconds",
    "frame_role",
    "anchor_index",
    "anchor_frame_index",
    "offset_from_anchor_frames",
    "offset_from_anchor_seconds",
    "anchor_type",
    "sample_reason",
    "storage_mode",
    "frame_selected_for_extraction",
    "frame_materialization_status",
    "materialization_reason",
    "output_frame_path",
    "output_frame_name",
    "output_file_size_bytes",
    "jpeg_quality",
    "cache_policy",
    "source_video_is_canonical",
    "extracted_frames_are_purgeable",
    "durable_evidence_written",
    "database_mutation",
]

REQUIRED_MANIFEST_KEYS = [
    "component",
    "runner",
    "runner_version",
    "status",
    "database_mutation",
    "source_video",
    "output_dir",
    "session_id",
    "camera_id",
    "camera_file_id",
    "fps",
    "frame_count",
    "duration_seconds",
    "sequence_count",
    "frame_records_written",
    "frames_selected_for_extraction",
    "frames_written",
    "bytes_written",
    "storage_mode",
    "debug_outputs_are_purgeable",
    "durable_evidence_written",
    "evidence_mode",
    "evidence_purpose",
    "feeder_reference_status",
    "local_scale_reference_type",
    "calibration_status",
    "marker_status",
    "sync_status",
]

REQUIRED_STORAGE_KEYS = [
    "component",
    "runner_version",
    "database_mutation",
    "storage_mode",
    "source_video_is_canonical",
    "debug_outputs_are_purgeable",
    "frames_folder_purgeable",
    "extracted_frames_are_purgeable",
    "durable_evidence_written",
    "promotion_status",
    "cache_policy",
    "source_video",
    "output_dir",
    "sequence_records_written",
    "frame_records_written",
    "frames_selected_for_extraction",
    "frames_written",
    "bytes_written",
    "max_preview_frames_total",
    "preview_frames_per_sequence",
    "max_cache_frames_total",
    "max_bytes_total_mb",
]

ALLOWED_STORAGE_MODES = {"metadata_only", "preview", "bounded_sequence_cache"}
ALLOWED_EVIDENCE_MODES = {"normal_single_camera", "same_feeder_3d", "cross_location_exclusion", "sync_only"}
ALLOWED_SYNC_STATUS = {"unsynced", "sync_placeholder", "sync_estimated", "sync_reviewed", "sync_accepted", "not_applicable"}
ALLOWED_BOOLEAN_TEXT = {"true", "false"}


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_csv(path):
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return reader.fieldnames or [], rows


def as_text(value):
    if value is None:
        return ""
    return str(value)


def as_bool_text(value):
    text = as_text(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def as_int(value, default=None):
    text = as_text(value).strip()
    if text == "":
        return default
    try:
        return int(float(text))
    except Exception:
        return default


def as_float(value, default=None):
    text = as_text(value).strip()
    if text == "":
        return default
    try:
        return float(text)
    except Exception:
        return default


def add_issue(issues, level, code, message, detail=None):
    issues.append({
        "level": level,
        "code": code,
        "message": message,
        "detail": detail,
    })


def missing_items(required, actual):
    actual_set = set(actual or [])
    return [item for item in required if item not in actual_set]


def check_required_files(output_dir, issues):
    paths = {}
    for label, filename in REQUIRED_FILES.items():
        path = output_dir / filename
        paths[label] = path
        if not path.exists():
            add_issue(issues, "error", "missing_required_file", f"Missing required file: {filename}", str(path))
    return paths


def validate_boolean_columns(rows, fields, issues, table_name):
    for i, row in enumerate(rows, start=1):
        for field in fields:
            if field not in row:
                continue
            text = as_text(row.get(field)).strip().lower()
            if text not in ALLOWED_BOOLEAN_TEXT:
                add_issue(
                    issues,
                    "error",
                    "invalid_boolean_text",
                    f"{table_name} row {i} has invalid boolean text in {field}: {row.get(field)!r}",
                )


def validate_no_database_mutation(manifest, storage, sequence_rows, frame_rows, extracted_rows, issues):
    checks = [
        ("manifest.database_mutation", manifest.get("database_mutation")),
        ("storage_ledger.database_mutation", storage.get("database_mutation")),
    ]

    for i, row in enumerate(sequence_rows, start=1):
        checks.append((f"sampled_sequences row {i}.database_mutation", row.get("database_mutation")))

    for i, row in enumerate(frame_rows, start=1):
        checks.append((f"sampled_frames row {i}.database_mutation", row.get("database_mutation")))

    for i, row in enumerate(extracted_rows, start=1):
        checks.append((f"extracted_frames row {i}.database_mutation", row.get("database_mutation")))

    for label, value in checks:
        parsed = as_bool_text(value)
        if parsed is not False:
            add_issue(issues, "error", "database_mutation_not_false", f"{label} must be false.", value)


def validate_storage_contract(manifest, storage, sequence_rows, frame_rows, extracted_rows, output_dir, issues):
    storage_mode = as_text(manifest.get("storage_mode") or storage.get("storage_mode")).strip()

    if storage_mode not in ALLOWED_STORAGE_MODES:
        add_issue(issues, "error", "invalid_storage_mode", "Storage mode is not recognized.", storage_mode)

    if as_bool_text(manifest.get("durable_evidence_written")) is not False:
        add_issue(issues, "error", "durable_evidence_written", "manifest.durable_evidence_written must be false.")

    if as_bool_text(storage.get("durable_evidence_written")) is not False:
        add_issue(issues, "error", "durable_evidence_written", "storage-ledger.durable_evidence_written must be false.")

    for key in ["source_video_is_canonical", "debug_outputs_are_purgeable", "frames_folder_purgeable", "extracted_frames_are_purgeable"]:
        if as_bool_text(storage.get(key)) is not True:
            add_issue(issues, "error", "storage_flag_not_true", f"storage-ledger.{key} must be true.", storage.get(key))

    frame_records_written = as_int(manifest.get("frame_records_written"), -1)
    sequence_count = as_int(manifest.get("sequence_count"), -1)
    frames_selected = as_int(manifest.get("frames_selected_for_extraction"), -1)
    frames_written = as_int(manifest.get("frames_written"), -1)
    bytes_written = as_int(manifest.get("bytes_written"), -1)

    if sequence_count != len(sequence_rows):
        add_issue(issues, "error", "sequence_count_mismatch", "manifest.sequence_count does not match sampled-sequences.csv row count.", {"manifest": sequence_count, "csv_rows": len(sequence_rows)})

    if frame_records_written != len(frame_rows):
        add_issue(issues, "error", "frame_count_mismatch", "manifest.frame_records_written does not match sampled-frames.csv row count.", {"manifest": frame_records_written, "csv_rows": len(frame_rows)})

    if frames_written != len(extracted_rows):
        add_issue(issues, "error", "extracted_count_mismatch", "manifest.frames_written does not match extracted-frames.csv row count.", {"manifest": frames_written, "csv_rows": len(extracted_rows)})

    if frames_written > frames_selected:
        add_issue(issues, "error", "written_exceeds_selected", "frames_written cannot exceed frames_selected_for_extraction.")

    if storage_mode == "metadata_only":
        if frames_selected != 0 or frames_written != 0 or len(extracted_rows) != 0 or bytes_written != 0:
            add_issue(
                issues,
                "error",
                "metadata_only_materialized_frames",
                "metadata_only mode must not select, write, or report extracted frames/bytes.",
                {"frames_selected": frames_selected, "frames_written": frames_written, "extracted_rows": len(extracted_rows), "bytes_written": bytes_written},
            )

    if storage_mode == "preview":
        max_preview = as_int(manifest.get("max_preview_frames_total") or storage.get("max_preview_frames_total"), 0)
        preview_per_sequence = as_int(manifest.get("preview_frames_per_sequence") or storage.get("preview_frames_per_sequence"), 0)
        allowed_by_sequence = max(0, preview_per_sequence) * max(0, sequence_count)
        allowed_total = min(max_preview, allowed_by_sequence) if max_preview > 0 and allowed_by_sequence > 0 else max_preview

        if max_preview >= 0 and frames_written > max_preview:
            add_issue(issues, "error", "preview_frame_budget_exceeded", "preview mode wrote more frames than max_preview_frames_total.", {"frames_written": frames_written, "max_preview_frames_total": max_preview})

        if allowed_total >= 0 and frames_written > allowed_total:
            add_issue(issues, "error", "preview_sequence_budget_exceeded", "preview mode wrote more frames than sequence preview budget allows.", {"frames_written": frames_written, "allowed_total": allowed_total})

    max_bytes_total_mb = as_float(manifest.get("max_bytes_total_mb") or storage.get("max_bytes_total_mb"), None)
    if max_bytes_total_mb is not None and max_bytes_total_mb >= 0:
        max_bytes_total = int(max_bytes_total_mb * 1024 * 1024)
        if bytes_written > max_bytes_total:
            add_issue(issues, "error", "byte_budget_exceeded", "bytes_written exceeds max_bytes_total_mb.", {"bytes_written": bytes_written, "max_bytes_total": max_bytes_total})

    # Verify extracted image file size accounting when files are present on this machine.
    actual_bytes = 0
    missing_written_paths = 0
    for row in extracted_rows:
        output_frame_path = as_text(row.get("output_frame_path")).strip()
        if output_frame_path == "":
            add_issue(issues, "error", "extracted_row_missing_path", "Extracted row has no output_frame_path.", row.get("frame_id"))
            continue
        path = Path(output_frame_path)
        if path.exists():
            actual_bytes += path.stat().st_size
        else:
            missing_written_paths += 1

    if missing_written_paths:
        add_issue(issues, "error", "missing_extracted_frame_files", "One or more extracted frame paths do not exist on this machine.", missing_written_paths)

    if extracted_rows and missing_written_paths == 0 and actual_bytes != bytes_written:
        add_issue(issues, "warning", "byte_accounting_mismatch", "Actual extracted frame bytes differ from manifest.bytes_written.", {"actual_bytes": actual_bytes, "manifest_bytes_written": bytes_written})

    frames_root = output_dir / "frames"
    if storage_mode == "metadata_only":
        if frames_root.exists() and any(frames_root.rglob("*")):
            add_issue(issues, "error", "metadata_only_nonempty_frames_folder", "metadata_only mode should not leave a non-empty frames folder.", str(frames_root))


def validate_source_video(manifest, storage, sequence_rows, frame_rows, issues):
    source_video = as_text(manifest.get("source_video") or storage.get("source_video")).strip()

    if source_video == "":
        add_issue(issues, "error", "missing_source_video", "Manifest/storage ledger must include source_video.")
        return

    if not Path(source_video).exists():
        add_issue(issues, "error", "source_video_missing", "Source video is not available at recorded path; records are not recoverable on this machine.", source_video)

    for table_name, rows in [("sampled_sequences", sequence_rows), ("sampled_frames", frame_rows)]:
        unique_sources = sorted({as_text(row.get("source_video")).strip() for row in rows if as_text(row.get("source_video")).strip()})
        if len(unique_sources) != 1 or unique_sources[0] != source_video:
            add_issue(issues, "error", "source_video_mismatch", f"{table_name} source_video values must match manifest source_video.", unique_sources)


def validate_session_manifest(session_manifest, manifest, issues):
    if as_bool_text(session_manifest.get("database_mutation")) is not False:
        add_issue(issues, "error", "session_manifest_database_mutation", "session-manifest.database_mutation must be false.")

    if session_manifest.get("session_id") != manifest.get("session_id"):
        add_issue(issues, "error", "session_id_mismatch", "session-manifest.session_id must match manifest.session_id.", {"session_manifest": session_manifest.get("session_id"), "manifest": manifest.get("session_id")})

    camera_files = session_manifest.get("camera_files")
    if not isinstance(camera_files, list) or not camera_files:
        add_issue(issues, "error", "missing_camera_files", "session-manifest.camera_files must contain at least one camera file record.")
    else:
        first = camera_files[0]
        for key in ["camera_file_id", "camera_id", "source_video", "fps", "frame_count", "duration_seconds"]:
            if key not in first:
                add_issue(issues, "error", "camera_file_key_missing", f"camera_files[0] is missing {key}.")

    feeder_reference = session_manifest.get("feeder_reference")
    if not isinstance(feeder_reference, dict):
        add_issue(issues, "error", "missing_feeder_reference", "session-manifest.feeder_reference must be an object.")
    else:
        if feeder_reference.get("local_scale_reference_type") != "feeder_assembly":
            add_issue(issues, "warning", "feeder_not_primary_reference", "feeder_reference.local_scale_reference_type should default to feeder_assembly for Birdbill Step 1.", feeder_reference.get("local_scale_reference_type"))

    for placeholder_key in ["sync_events", "sync_segments", "calibration_assets"]:
        value = session_manifest.get(placeholder_key)
        if not isinstance(value, list):
            add_issue(issues, "error", "placeholder_list_missing", f"session-manifest.{placeholder_key} must exist as a list, even if empty.")


def validate_enumerations(manifest, sequence_rows, frame_rows, issues):
    evidence_mode = as_text(manifest.get("evidence_mode")).strip()
    if evidence_mode not in ALLOWED_EVIDENCE_MODES:
        add_issue(issues, "error", "invalid_evidence_mode", "manifest.evidence_mode is not recognized.", evidence_mode)

    sync_status = as_text(manifest.get("sync_status")).strip()
    if sync_status not in ALLOWED_SYNC_STATUS:
        add_issue(issues, "warning", "unrecognized_sync_status", "manifest.sync_status is not in the current audit allowlist.", sync_status)

    for table_name, rows in [("sampled_sequences", sequence_rows), ("sampled_frames", frame_rows)]:
        for i, row in enumerate(rows, start=1):
            row_evidence_mode = as_text(row.get("evidence_mode")).strip()
            if row_evidence_mode not in ALLOWED_EVIDENCE_MODES:
                add_issue(issues, "error", "invalid_row_evidence_mode", f"{table_name} row {i} has unrecognized evidence_mode.", row_evidence_mode)
            row_storage_mode = as_text(row.get("storage_mode")).strip()
            if row_storage_mode not in ALLOWED_STORAGE_MODES:
                add_issue(issues, "error", "invalid_row_storage_mode", f"{table_name} row {i} has unrecognized storage_mode.", row_storage_mode)


def validate_sequence_frame_integrity(sequence_rows, frame_rows, extracted_rows, issues):
    sequence_by_id = {}
    for i, row in enumerate(sequence_rows, start=1):
        sequence_id = as_text(row.get("sequence_id")).strip()
        if sequence_id == "":
            add_issue(issues, "error", "blank_sequence_id", f"sampled_sequences row {i} has blank sequence_id.")
            continue
        if sequence_id in sequence_by_id:
            add_issue(issues, "error", "duplicate_sequence_id", f"Duplicate sequence_id: {sequence_id}")
        sequence_by_id[sequence_id] = row

        start_frame = as_int(row.get("start_frame_index"), None)
        end_frame = as_int(row.get("end_frame_index"), None)
        anchor_frame = as_int(row.get("anchor_frame_index"), None)
        planned = as_int(row.get("sequence_frames_planned"), None)
        expected = as_int(row.get("sequence_frame_count_expected"), None)
        selected = as_int(row.get("sequence_frames_selected_for_extraction"), 0)
        written = as_int(row.get("sequence_frames_written"), 0)

        if start_frame is None or end_frame is None or anchor_frame is None:
            add_issue(issues, "error", "sequence_numeric_parse_failed", f"sampled_sequences row {i} has invalid frame indexes.")
            continue

        if start_frame > end_frame:
            add_issue(issues, "error", "sequence_start_after_end", f"sampled_sequences row {i} start_frame_index > end_frame_index.")

        if not (start_frame <= anchor_frame <= end_frame):
            add_issue(issues, "error", "anchor_outside_sequence", f"sampled_sequences row {i} anchor frame is outside sequence bounds.", {"start": start_frame, "anchor": anchor_frame, "end": end_frame})

        if planned is not None and expected is not None and planned != expected:
            add_issue(issues, "warning", "planned_expected_mismatch", f"sampled_sequences row {i} planned and expected frame counts differ.", {"planned": planned, "expected": expected})

        if written > selected:
            add_issue(issues, "error", "sequence_written_exceeds_selected", f"sampled_sequences row {i} written frames exceed selected frames.", {"written": written, "selected": selected})

    frame_by_id = {}
    frames_by_sequence = {sequence_id: [] for sequence_id in sequence_by_id}
    for i, row in enumerate(frame_rows, start=1):
        frame_id = as_text(row.get("frame_id")).strip()
        sequence_id = as_text(row.get("sequence_id")).strip()
        if frame_id == "":
            add_issue(issues, "error", "blank_frame_id", f"sampled_frames row {i} has blank frame_id.")
            continue
        if frame_id in frame_by_id:
            add_issue(issues, "error", "duplicate_frame_id", f"Duplicate frame_id: {frame_id}")
        frame_by_id[frame_id] = row

        if sequence_id not in sequence_by_id:
            add_issue(issues, "error", "frame_missing_sequence", f"sampled_frames row {i} references unknown sequence_id.", {"frame_id": frame_id, "sequence_id": sequence_id})
            continue
        frames_by_sequence.setdefault(sequence_id, []).append(row)

        sequence = sequence_by_id[sequence_id]
        source_frame_index = as_int(row.get("source_frame_index"), None)
        anchor_frame = as_int(row.get("anchor_frame_index"), None)
        offset = as_int(row.get("offset_from_anchor_frames"), None)
        start_frame = as_int(sequence.get("start_frame_index"), None)
        end_frame = as_int(sequence.get("end_frame_index"), None)

        if None in [source_frame_index, anchor_frame, offset, start_frame, end_frame]:
            add_issue(issues, "error", "frame_numeric_parse_failed", f"sampled_frames row {i} has invalid frame indexes.", frame_id)
            continue

        if not (start_frame <= source_frame_index <= end_frame):
            add_issue(issues, "error", "frame_outside_sequence", f"sampled_frames row {i} source frame is outside linked sequence bounds.", {"frame_id": frame_id, "sequence_id": sequence_id})

        if source_frame_index - anchor_frame != offset:
            add_issue(issues, "error", "offset_mismatch", f"sampled_frames row {i} offset_from_anchor_frames does not match source_frame_index - anchor_frame_index.", frame_id)

        selected = as_bool_text(row.get("frame_selected_for_extraction"))
        materialized = as_text(row.get("frame_materialization_status")).strip()
        output_path = as_text(row.get("output_frame_path")).strip()

        if selected is True and materialized == "written_debug_cache" and output_path == "":
            add_issue(issues, "error", "written_frame_missing_output_path", f"sampled_frames row {i} says written_debug_cache but output_frame_path is blank.", frame_id)

        if selected is False and materialized == "written_debug_cache":
            add_issue(issues, "error", "unselected_frame_written", f"sampled_frames row {i} is not selected but says written_debug_cache.", frame_id)

    for sequence_id, sequence in sequence_by_id.items():
        expected_count = as_int(sequence.get("sequence_frames_planned"), None)
        observed_count = len(frames_by_sequence.get(sequence_id, []))
        if expected_count is not None and expected_count != observed_count:
            add_issue(issues, "error", "sequence_frame_count_mismatch", "sampled_frames row count for sequence_id does not match sequence_frames_planned.", {"sequence_id": sequence_id, "expected": expected_count, "observed": observed_count})

    extracted_frame_ids = set()
    for i, row in enumerate(extracted_rows, start=1):
        frame_id = as_text(row.get("frame_id")).strip()
        if frame_id == "":
            add_issue(issues, "error", "blank_extracted_frame_id", f"extracted_frames row {i} has blank frame_id.")
            continue
        if frame_id in extracted_frame_ids:
            add_issue(issues, "error", "duplicate_extracted_frame_id", f"Duplicate extracted frame_id: {frame_id}")
        extracted_frame_ids.add(frame_id)
        if frame_id not in frame_by_id:
            add_issue(issues, "error", "extracted_frame_not_in_sampled_frames", "extracted-frames.csv row does not exist in sampled-frames.csv.", frame_id)


def run(config):
    issues = []
    output_dir = Path(config.get("output_dir", "")).expanduser()
    timestamp = now_stamp()

    if not output_dir.exists():
        add_issue(issues, "error", "output_dir_missing", "Selected sampler output directory does not exist.", str(output_dir))
        return finalize(config, output_dir, timestamp, issues, loaded=False)

    paths = check_required_files(output_dir, issues)

    if any(issue["level"] == "error" and issue["code"] == "missing_required_file" for issue in issues):
        return finalize(config, output_dir, timestamp, issues, loaded=False)

    try:
        manifest = read_json(paths["manifest"])
        session_manifest = read_json(paths["session_manifest"])
        storage = read_json(paths["storage_ledger"])
        sequence_fields, sequence_rows = read_csv(paths["sampled_sequences"])
        frame_fields, frame_rows = read_csv(paths["sampled_frames"])
        extracted_fields, extracted_rows = read_csv(paths["extracted_frames"])
    except Exception as exc:
        add_issue(issues, "error", "load_failed", "Could not load one or more sampler output files.", {"exception": str(exc), "traceback": traceback.format_exc()})
        return finalize(config, output_dir, timestamp, issues, loaded=False)

    for label, required, actual in [
        ("manifest", REQUIRED_MANIFEST_KEYS, manifest.keys()),
        ("storage-ledger", REQUIRED_STORAGE_KEYS, storage.keys()),
        ("sampled-sequences.csv", REQUIRED_SEQUENCE_FIELDS, sequence_fields),
        ("sampled-frames.csv", REQUIRED_FRAME_FIELDS, frame_fields),
        ("extracted-frames.csv", REQUIRED_FRAME_FIELDS, extracted_fields),
    ]:
        missing = missing_items(required, actual)
        if missing:
            add_issue(issues, "error", "missing_required_fields", f"{label} is missing required fields.", missing)

    validate_boolean_columns(sequence_rows, ["source_video_is_canonical", "extracted_frames_are_purgeable", "durable_evidence_written", "database_mutation"], issues, "sampled_sequences")
    validate_boolean_columns(frame_rows, ["frame_selected_for_extraction", "source_video_is_canonical", "extracted_frames_are_purgeable", "durable_evidence_written", "database_mutation"], issues, "sampled_frames")
    validate_boolean_columns(extracted_rows, ["frame_selected_for_extraction", "source_video_is_canonical", "extracted_frames_are_purgeable", "durable_evidence_written", "database_mutation"], issues, "extracted_frames")

    validate_no_database_mutation(manifest, storage, sequence_rows, frame_rows, extracted_rows, issues)
    validate_storage_contract(manifest, storage, sequence_rows, frame_rows, extracted_rows, output_dir, issues)
    validate_source_video(manifest, storage, sequence_rows, frame_rows, issues)
    validate_session_manifest(session_manifest, manifest, issues)
    validate_enumerations(manifest, sequence_rows, frame_rows, issues)
    validate_sequence_frame_integrity(sequence_rows, frame_rows, extracted_rows, issues)

    return finalize(
        config,
        output_dir,
        timestamp,
        issues,
        loaded=True,
        manifest=manifest,
        storage=storage,
        sequence_rows=sequence_rows,
        frame_rows=frame_rows,
        extracted_rows=extracted_rows,
    )


def finalize(config, output_dir, timestamp, issues, loaded, manifest=None, storage=None, sequence_rows=None, frame_rows=None, extracted_rows=None):
    errors = [issue for issue in issues if issue.get("level") == "error"]
    warnings = [issue for issue in issues if issue.get("level") == "warning"]
    status = "PASS" if not errors else "FAIL"

    report_path = output_dir / f"schema-audit-report-{timestamp}.json"
    summary_path = output_dir / f"schema-audit-summary-{timestamp}.txt"

    report = {
        "component": "Smart Frame Sampler schema/storage audit",
        "runner": RUNNER_NAME,
        "runner_version": RUNNER_VERSION,
        "status": status,
        "database_mutation": False,
        "durable_evidence_written": False,
        "created_at": now_iso(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "config": config,
        "output_dir": str(output_dir),
        "loaded": loaded,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
        "counts": {
            "sequence_rows": len(sequence_rows or []),
            "sampled_frame_rows": len(frame_rows or []),
            "extracted_frame_rows": len(extracted_rows or []),
        },
        "storage_mode": (manifest or {}).get("storage_mode") if manifest else None,
        "frames_written": (manifest or {}).get("frames_written") if manifest else None,
        "bytes_written": (manifest or {}).get("bytes_written") if manifest else None,
        "source_video": (manifest or {}).get("source_video") if manifest else None,
        "source_video_available": Path((manifest or {}).get("source_video", "")).exists() if manifest else False,
        "audit_report_path": str(report_path),
        "audit_summary_path": str(summary_path),
    }

    if output_dir.exists():
        write_json(report_path, report)

        summary_lines = []
        summary_lines.append(f"auditSmartFrameSamplerOutput.py | {RUNNER_VERSION} | 2026-07-06 PDT")
        summary_lines.append(f"status = {status}")
        summary_lines.append("database_mutation = false")
        summary_lines.append("durable_evidence_written = false")
        summary_lines.append(f"output_dir = {output_dir}")
        summary_lines.append(f"storage_mode = {report.get('storage_mode')}")
        summary_lines.append(f"sequence_rows = {report['counts']['sequence_rows']}")
        summary_lines.append(f"sampled_frame_rows = {report['counts']['sampled_frame_rows']}")
        summary_lines.append(f"extracted_frame_rows = {report['counts']['extracted_frame_rows']}")
        summary_lines.append(f"frames_written = {report.get('frames_written')}")
        summary_lines.append(f"bytes_written = {report.get('bytes_written')}")
        summary_lines.append(f"source_video_available = {str(report.get('source_video_available')).lower()}")
        summary_lines.append(f"error_count = {len(errors)}")
        summary_lines.append(f"warning_count = {len(warnings)}")
        summary_lines.append(f"audit_report = {report_path}")
        summary_lines.append(f"audit_summary = {summary_path}")

        if issues:
            summary_lines.append("")
            summary_lines.append("issues:")
            for issue in issues:
                summary_lines.append(f"[{issue['level']}] {issue['code']}: {issue['message']}")
                if issue.get("detail") not in [None, ""]:
                    summary_lines.append(f"  detail = {issue.get('detail')}")

        summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"status = {status}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print(f"output_dir = {output_dir}")
    print(f"storage_mode = {report.get('storage_mode')}")
    print(f"sequence_rows = {report['counts']['sequence_rows']}")
    print(f"sampled_frame_rows = {report['counts']['sampled_frame_rows']}")
    print(f"extracted_frame_rows = {report['counts']['extracted_frame_rows']}")
    print(f"frames_written = {report.get('frames_written')}")
    print(f"bytes_written = {report.get('bytes_written')}")
    print(f"source_video_available = {str(report.get('source_video_available')).lower()}")
    print(f"error_count = {len(errors)}")
    print(f"warning_count = {len(warnings)}")

    if output_dir.exists():
        print(f"audit_report = {report_path}")
        print(f"audit_summary = {summary_path}")

    if issues:
        print("issues:")
        for issue in issues:
            print(f"[{issue['level']}] {issue['code']}: {issue['message']}")

    return 0 if status == "PASS" else 20


def load_config_from_env():
    config_path = os.environ.get("BIRDBILL_SFS_AUDIT_CONFIG", "").strip()
    if not config_path:
        print("Missing BIRDBILL_SFS_AUDIT_CONFIG environment variable.", file=sys.stderr)
        return None, 90

    path = Path(config_path)
    if not path.exists():
        print(f"Audit config file does not exist: {path}", file=sys.stderr)
        return None, 91

    try:
        config = read_json(path)
    except Exception as exc:
        print(f"Could not read audit config: {exc}", file=sys.stderr)
        return None, 92

    config["config_path"] = str(path)
    return config, 0


def main():
    config, code = load_config_from_env()
    if config is None:
        return code
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
