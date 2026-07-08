# DLCBilltip.py | v0.4 | 2026-07-07 PDT | Promoted Birdbill DLC billtip inference from PoseMap candidates with H5-first parsing
from __future__ import annotations

import argparse
import csv
import inspect
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_NAME = "DLCBilltip.py"
SCRIPT_VERSION = "v0.4"
COMPONENT_NAME = "DLCBilltip"
SCHEMA_VERSION = "dlc_billtip_from_pose_map_v0.4"
PIPELINE_COMPLETION_STATE = "dlc_billtip_evidence_ready"

DEFAULT_ROOT = Path(r"D:\birdbill")
DEFAULT_POSE_MAP_MANIFEST = DEFAULT_ROOT / "output" / "debug" / "current-pose-map" / "pose-map-manifest.csv"
DEFAULT_DLC_CONFIG = DEFAULT_ROOT / "modules" / "dlc" / "billtip" / "billtip-HB-2026-06-30" / "config.yaml"
DEFAULT_OUTPUT_DIR = DEFAULT_ROOT / "output" / "debug" / "current-dlc-billtip-from-pose-map"

DATABASE_MUTATION = False
DURABLE_EVIDENCE_WRITTEN = False

POSE_MAP_PRESERVE_FIELDS = [
    "pose_map_schema_version",
    "mmpose_input_id",
    "detection_id",
    "frame_id",
    "source_video",
    "source_frame_index",
    "camera_local_time_seconds",
    "raw_crop_path",
    "raw_crop_width",
    "raw_crop_height",
    "retention_decision",
    "retention_score",
    "mmpose_ok",
    "mmpose_keypoint_count",
    "mmpose_visible_keypoint_count",
    "visible_head_keypoint_count",
    "visible_body_keypoint_count",
    "nose_visible",
    "neck_visible",
    "tail_root_visible",
    "bill_base_proxy_x",
    "bill_base_proxy_y",
    "neck_proxy_x",
    "neck_proxy_y",
    "tail_root_proxy_x",
    "tail_root_proxy_y",
    "head_roi_x1",
    "head_roi_y1",
    "head_roi_x2",
    "head_roi_y2",
    "body_roi_x1",
    "body_roi_y1",
    "body_roi_x2",
    "body_roi_y2",
    "dlc_billtip_candidate",
    "smart_cropper_candidate",
    "pose_map_decision",
    "pose_handoff_decision",
    "notes",
]


def configure_runtime() -> None:
    os.environ.setdefault("DLClight", "True")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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


def safe_name(value: str, fallback: str) -> str:
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


def sanitize_config_copy(original_config: Path, working_config: Path) -> dict[str, Any]:
    raw = original_config.read_text(encoding="utf-8-sig", errors="replace")
    sanitized = raw.replace("Ã¯Â»Â¿Task", "Task").replace("\ufeffTask", "Task")

    project_path_text = original_config.parent.as_posix()
    project_path_line = f"project_path: '{project_path_text}'"

    if re.search(r"(?m)^project_path\s*:", sanitized):
        sanitized = re.sub(r"(?m)^project_path\s*:.*$", lambda _match: project_path_line, sanitized)
    else:
        sanitized = sanitized.rstrip() + "\n" + project_path_line + "\n"

    if "Task:" not in sanitized:
        raise RuntimeError("Sanitized DLC config does not contain a normal Task: key.")

    working_config.write_text(sanitized, encoding="utf-8", newline="\n")

    return {
        "original_config": str(original_config),
        "working_config": str(working_config),
        "original_config_mutated": False,
        "working_config_written": True,
        "working_config_parent_is_dlc_project_dir": working_config.parent == original_config.parent,
        "task_key_present": "Task:" in sanitized,
        "project_path_rewritten_to": project_path_text,
        "original_size_bytes": original_config.stat().st_size,
        "working_size_bytes": working_config.stat().st_size,
    }


def stage_pose_map_candidates(
    pose_rows: list[dict[str, str]],
    input_dir: Path,
    max_candidates: int,
) -> tuple[list[dict[str, Any]], int]:
    input_dir.mkdir(parents=True, exist_ok=True)
    staged_rows: list[dict[str, Any]] = []
    media_files_written = 0

    eligible = [row for row in pose_rows if truthy(row.get("dlc_billtip_candidate"))]

    for index, row in enumerate(eligible[:max_candidates], start=1):
        raw_crop_text = clean(row.get("raw_crop_path"))
        raw_crop_path = Path(raw_crop_text) if raw_crop_text else None
        exists = bool(raw_crop_path and raw_crop_path.exists())

        frame_id = clean(row.get("frame_id")) or f"frame-unknown-{index:05d}"
        detection_id = clean(row.get("detection_id")) or f"detection-unknown-{index:05d}"
        stage_stem = safe_name(f"{index:05d}-{frame_id}-{detection_id}", f"pose-map-candidate-{index:05d}")
        staged_path = input_dir / f"{stage_stem}.jpg"

        copied = False
        failure_reason = ""

        if exists and raw_crop_path is not None:
            shutil.copy2(raw_crop_path, staged_path)
            copied = True
            media_files_written += 1
        else:
            failure_reason = f"raw_crop_path missing or does not exist: {raw_crop_text}"

        mapped: dict[str, Any] = {
            "dlc_input_index": index,
            "dlc_input_id": f"dlc-input-{index:05d}",
            "dlc_input_filename": staged_path.name,
            "dlc_input_path": str(staged_path) if copied else "",
            "dlc_stage_ok": copied,
            "dlc_stage_failure_reason": failure_reason,
        }

        for field in POSE_MAP_PRESERVE_FIELDS:
            mapped[field] = row.get(field, "")

        for key, value in row.items():
            mapped.setdefault(f"src_{key}", value)

        staged_rows.append(mapped)

    return staged_rows, media_files_written


def run_dlc(
    config_path: Path,
    input_dir: Path,
    dlc_output_dir: Path,
    frametype: str,
) -> dict[str, Any]:
    import deeplabcut  # type: ignore

    func = deeplabcut.analyze_time_lapse_frames
    signature = inspect.signature(func)
    params = list(signature.parameters.keys())

    kwargs: dict[str, Any] = {}
    if "frametype" in params:
        kwargs["frametype"] = frametype
    if "save_as_csv" in params:
        kwargs["save_as_csv"] = True
    if "shuffle" in params:
        kwargs["shuffle"] = 1
    if "trainingsetindex" in params:
        kwargs["trainingsetindex"] = 0
    if "destfolder" in params:
        kwargs["destfolder"] = str(dlc_output_dir)
    if "gputouse" in params:
        kwargs["gputouse"] = None

    started = time.time()
    result = func(str(config_path), str(input_dir), **kwargs)

    return {
        "dlc_function": "deeplabcut.analyze_time_lapse_frames",
        "analyze_time_lapse_frames_signature": str(signature),
        "analyze_time_lapse_frames_params": params,
        "dlc_call_kwargs": kwargs,
        "dlc_result_repr": repr(result),
        "elapsed_seconds": round(time.time() - started, 3),
    }


def find_prediction_outputs(search_roots: list[Path], started_at: float) -> list[Path]:
    outputs: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for suffix in ["*.h5", "*.hdf5", "*.csv"]:
            for path in root.rglob(suffix):
                if path.name.lower() in {"dlc-input-map.csv", "dlc-billtip-evidence.csv"}:
                    continue
                try:
                    if path.stat().st_mtime >= started_at - 2:
                        outputs.append(path)
                except OSError:
                    continue

    unique: dict[str, Path] = {}
    for path in outputs:
        unique[str(path).lower()] = path

    return sorted(unique.values(), key=lambda p: (p.suffix.lower() != ".h5", str(p).lower()))


def read_dlc_h5(path: Path) -> Any:
    import pandas as pd  # type: ignore

    try:
        return pd.read_hdf(path)
    except Exception:
        with pd.HDFStore(path, mode="r") as store:
            keys = store.keys()
            if not keys:
                raise RuntimeError(f"H5 has no readable keys: {path}")
            return store[keys[0]]


def normalize_key(value: Any) -> str:
    return str(value).strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def choose_bodyparts(columns: Any) -> tuple[dict[str, str], list[str], str]:
    if not hasattr(columns, "nlevels") or columns.nlevels < 2:
        return {}, [], "DLC columns are not a MultiIndex with bodypart/coord levels."

    bodypart_level = columns.nlevels - 2
    bodyparts = sorted({str(v) for v in columns.get_level_values(bodypart_level)})

    wanted = {
        "bill_base": {"billbase", "billbase1", "bill_base", "bill-base", "base", "beakbase", "beak_base"},
        "bill_tip": {"billtip", "billtip1", "bill_tip", "bill-tip", "tip", "beaktip", "beak_tip"},
    }

    normalized_to_actual = {normalize_key(part): part for part in bodyparts}
    selected: dict[str, str] = {}
    notes: list[str] = []

    for canonical, aliases in wanted.items():
        for alias in aliases:
            actual = normalized_to_actual.get(normalize_key(alias))
            if actual:
                selected[canonical] = actual
                break

    if "bill_tip" not in selected and len(bodyparts) == 1:
        selected["bill_tip"] = bodyparts[0]
        notes.append("Only one DLC bodypart found; using it as bill_tip.")

    if "bill_tip" not in selected:
        notes.append("No bill_tip-like DLC bodypart found.")

    if "bill_base" not in selected:
        notes.append("No bill_base-like DLC bodypart found.")

    return selected, bodyparts, "; ".join(notes)


def get_coord(series: Any, actual_bodypart: str, coord: str) -> float | None:
    for col in series.index:
        if not isinstance(col, tuple) or len(col) < 2:
            continue
        if str(col[-2]) == actual_bodypart and str(col[-1]).lower() == coord.lower():
            return safe_float(series[col])
    return None


def basename_from_index(index_value: Any) -> str:
    if isinstance(index_value, tuple) and index_value:
        index_value = index_value[-1]
    return Path(str(index_value).replace("\\", "/")).name


def compute_distance(ax: float | None, ay: float | None, bx: float | None, by: float | None) -> float | None:
    if ax is None or ay is None or bx is None or by is None:
        return None
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def inside_roi(x: float | None, y: float | None, x1: float | None, y1: float | None, x2: float | None, y2: float | None) -> str:
    if x is None or y is None or x1 is None or y1 is None or x2 is None or y2 is None:
        return ""
    return str(x1 <= x <= x2 and y1 <= y <= y2)


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.3f}"
    return str(value)


def parse_h5_predictions(h5_path: Path, staged_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    df = read_dlc_h5(h5_path)
    selected_bodyparts, available_bodyparts, bodypart_note = choose_bodyparts(df.columns)

    staged_ok = [row for row in staged_rows if truthy(row.get("dlc_stage_ok"))]
    staged_by_name = {clean(row.get("dlc_input_filename")).lower(): row for row in staged_ok}

    evidence_rows: list[dict[str, Any]] = []

    for row_index, (df_index, series) in enumerate(df.iterrows()):
        dlc_row_basename = basename_from_index(df_index).lower()
        staged = staged_by_name.get(dlc_row_basename)
        match_method = "basename"

        if staged is None and row_index < len(staged_ok):
            staged = staged_ok[row_index]
            match_method = "row_order"

        if staged is None:
            evidence_rows.append({
                "dlc_evidence_schema_version": SCHEMA_VERSION,
                "dlc_prediction_ok": False,
                "dlc_prediction_note": f"Could not map DLC row to staged PoseMap input: {df_index}",
                "dlc_h5_path": str(h5_path),
                "dlc_row_index": str(df_index),
                "dlc_row_basename": dlc_row_basename,
            })
            continue

        actual_base = selected_bodyparts.get("bill_base", "")
        actual_tip = selected_bodyparts.get("bill_tip", "")

        base_x = get_coord(series, actual_base, "x") if actual_base else None
        base_y = get_coord(series, actual_base, "y") if actual_base else None
        base_l = get_coord(series, actual_base, "likelihood") if actual_base else None

        tip_x = get_coord(series, actual_tip, "x") if actual_tip else None
        tip_y = get_coord(series, actual_tip, "y") if actual_tip else None
        tip_l = get_coord(series, actual_tip, "likelihood") if actual_tip else None

        head_x1 = safe_float(staged.get("head_roi_x1"))
        head_y1 = safe_float(staged.get("head_roi_y1"))
        head_x2 = safe_float(staged.get("head_roi_x2"))
        head_y2 = safe_float(staged.get("head_roi_y2"))

        proxy_base_x = safe_float(staged.get("bill_base_proxy_x"))
        proxy_base_y = safe_float(staged.get("bill_base_proxy_y"))

        tip_in_head_roi = inside_roi(tip_x, tip_y, head_x1, head_y1, head_x2, head_y2)
        base_in_head_roi = inside_roi(base_x, base_y, head_x1, head_y1, head_x2, head_y2)
        tip_distance_to_proxy_base = compute_distance(tip_x, tip_y, proxy_base_x, proxy_base_y)
        base_distance_to_proxy_base = compute_distance(base_x, base_y, proxy_base_x, proxy_base_y)
        dlc_bill_length_px = compute_distance(base_x, base_y, tip_x, tip_y)

        prediction_notes: list[str] = []
        if bodypart_note:
            prediction_notes.append(bodypart_note)
        if tip_x is None or tip_y is None:
            prediction_notes.append("missing bill_tip x/y")
        if actual_base and (base_x is None or base_y is None):
            prediction_notes.append("missing bill_base x/y")
        if tip_l is not None and tip_l < 0.10:
            prediction_notes.append("bill_tip likelihood below 0.10")
        if tip_in_head_roi == "False":
            prediction_notes.append(
                "bill_tip outside PoseMap head ROI; retained as note only in v0.4 because hummingbird bill tip may extend beyond head ROI"
            )
        if base_in_head_roi == "False":
            prediction_notes.append("bill_base outside PoseMap head ROI")

        decision = "dlc_billtip_evidence_ready"
        if tip_x is None or tip_y is None:
            decision = "missing_bill_tip_xy"
        elif tip_l is not None and tip_l < 0.10:
            decision = "low_likelihood_debug_only"

        out: dict[str, Any] = {
            "dlc_evidence_schema_version": SCHEMA_VERSION,
            "dlc_prediction_ok": tip_x is not None and tip_y is not None,
            "dlc_billtip_decision": decision,
            "dlc_prediction_note": "; ".join(prediction_notes),
            "dlc_h5_path": str(h5_path),
            "dlc_row_index": str(df_index),
            "dlc_row_basename": dlc_row_basename,
            "dlc_match_method": match_method,
            "dlc_available_bodyparts": "|".join(available_bodyparts),
            "dlc_bill_base_bodypart_used": actual_base,
            "dlc_bill_tip_bodypart_used": actual_tip,
            "bill_base_x_raw_crop": fmt(base_x),
            "bill_base_y_raw_crop": fmt(base_y),
            "bill_base_likelihood": "" if base_l is None else f"{base_l:.6f}",
            "bill_tip_x_raw_crop": fmt(tip_x),
            "bill_tip_y_raw_crop": fmt(tip_y),
            "bill_tip_likelihood": "" if tip_l is None else f"{tip_l:.6f}",
            "dlc_bill_length_px": fmt(dlc_bill_length_px),
            "bill_tip_in_head_roi": tip_in_head_roi,
            "bill_base_in_head_roi": base_in_head_roi,
            "bill_tip_distance_to_pose_bill_base_proxy": fmt(tip_distance_to_proxy_base),
            "bill_base_distance_to_pose_bill_base_proxy": fmt(base_distance_to_proxy_base),
            "dlc_input_index": staged.get("dlc_input_index", ""),
            "dlc_input_id": staged.get("dlc_input_id", ""),
            "dlc_input_filename": staged.get("dlc_input_filename", ""),
            "dlc_input_path": staged.get("dlc_input_path", ""),
        }

        for field in POSE_MAP_PRESERVE_FIELDS:
            out[field] = staged.get(field, "")

        evidence_rows.append(out)

    metadata = {
        "h5_path": str(h5_path),
        "h5_rows": len(df),
        "h5_columns_nlevels": getattr(df.columns, "nlevels", ""),
        "dlc_available_bodyparts": available_bodyparts,
        "selected_bodyparts": selected_bodyparts,
        "bodypart_note": bodypart_note,
    }
    return evidence_rows, metadata


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Birdbill DLC billtip inference from PoseMap candidates and parse native H5 predictions first."
    )
    parser.add_argument("--pose-map-manifest", type=Path, default=DEFAULT_POSE_MAP_MANIFEST)
    parser.add_argument("--dlc-config", type=Path, default=DEFAULT_DLC_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-candidates", type=int, default=25)
    parser.add_argument("--frametype", default=".jpg")
    parser.add_argument("--keep-working-config", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_runtime()
    args = build_arg_parser().parse_args(argv)

    started_at = time.time()
    started_text = utc_text()

    output_dir: Path = args.output_dir
    input_dir = output_dir / "dlc-input"
    dlc_output_dir = output_dir / "dlc-output"
    report_path = output_dir / "dlc-billtip-report.txt"
    input_map_path = output_dir / "dlc-input-map.csv"
    evidence_csv_path = output_dir / "dlc-billtip-evidence.csv"
    manifest_path = output_dir / "manifest.json"

    pose_map_manifest: Path = args.pose_map_manifest
    original_dlc_config: Path = args.dlc_config
    working_config = original_dlc_config.parent / "config-birdbill-dlc-billtip-v0.4.yaml"

    report_lines: list[str] = []
    manifest: dict[str, Any] = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "component": COMPONENT_NAME,
        "schema_version": SCHEMA_VERSION,
        "pipeline_completion_state": PIPELINE_COMPLETION_STATE,
        "started_at": started_text,
        "completed_at": "",
        "status": "FAIL",
        "python_executable": sys.executable,
        "pose_map_manifest": str(pose_map_manifest),
        "dlc_config": str(original_dlc_config),
        "working_config": str(working_config),
        "output_dir": str(output_dir),
        "database_mutation": DATABASE_MUTATION,
        "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
        "media_files_written": 0,
        "failure_reasons": [],
    }

    working_config_removed = False
    media_files_written = 0

    def add(line: str = "") -> None:
        report_lines.append(line)

    try:
        reset_output_dir(output_dir)
        input_dir.mkdir(parents=True, exist_ok=True)
        dlc_output_dir.mkdir(parents=True, exist_ok=True)

        add(f"{SCRIPT_NAME} | {SCRIPT_VERSION} | 2026-07-07 PDT | Promoted Birdbill DLC billtip inference from PoseMap candidates")
        add(f"generated={now_text()}")
        add(f"script_name={SCRIPT_NAME}")
        add(f"script_version={SCRIPT_VERSION}")
        add(f"component={COMPONENT_NAME}")
        add(f"dlc_evidence_schema_version={SCHEMA_VERSION}")
        add(f"pipeline_completion_state={PIPELINE_COMPLETION_STATE}")
        add(f"python_executable={sys.executable}")
        add(f"pose_map_manifest={pose_map_manifest}")
        add(f"dlc_config={original_dlc_config}")
        add(f"working_config={working_config}")
        add(f"output_dir={output_dir}")
        add(f"frametype={args.frametype}")
        add(f"max_candidates={args.max_candidates}")
        add(f"database_mutation={str(DATABASE_MUTATION).lower()}")
        add(f"durable_evidence_written={str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        add("")

        checks = {
            "pose_map_manifest_exists": pose_map_manifest.exists(),
            "dlc_config_exists": original_dlc_config.exists(),
            "dlc_project_dir_exists": original_dlc_config.parent.exists(),
        }
        manifest["checks"] = checks

        add("PATH CHECKS")
        for name, ok in checks.items():
            path = pose_map_manifest if name == "pose_map_manifest_exists" else original_dlc_config if name == "dlc_config_exists" else original_dlc_config.parent
            add(f"{name}={ok} path={path}")
            if not ok:
                manifest["failure_reasons"].append(f"{name}=false")
        add("")

        if manifest["failure_reasons"]:
            raise RuntimeError("; ".join(manifest["failure_reasons"]))

        sanitize_info = sanitize_config_copy(original_dlc_config, working_config)
        manifest["config_sanitize_info"] = sanitize_info

        pose_rows = read_csv_dicts(pose_map_manifest)
        eligible_rows = [row for row in pose_rows if truthy(row.get("dlc_billtip_candidate"))]
        staged_rows, media_files_written = stage_pose_map_candidates(pose_rows, input_dir, args.max_candidates)
        write_csv(input_map_path, staged_rows)
        staged_ok = [row for row in staged_rows if truthy(row.get("dlc_stage_ok"))]

        manifest["pose_map_rows"] = len(pose_rows)
        manifest["eligible_dlc_billtip_candidate_rows"] = len(eligible_rows)
        manifest["staged_rows"] = len(staged_rows)
        manifest["staged_ok_count"] = len(staged_ok)
        manifest["media_files_written"] = media_files_written
        manifest["dlc_input_map"] = str(input_map_path)

        add("INPUT / STAGING")
        add(f"pose_map_rows={len(pose_rows)}")
        add(f"eligible_dlc_billtip_candidate_rows={len(eligible_rows)}")
        add(f"staged_rows={len(staged_rows)}")
        add(f"staged_ok_count={len(staged_ok)}")
        add(f"dlc_input_map={input_map_path}")
        add(f"media_files_written={media_files_written}")
        add("")

        if not staged_ok:
            raise RuntimeError("No PoseMap candidates could be staged for DLC input.")

        dlc_info = run_dlc(working_config, input_dir, dlc_output_dir, args.frametype)
        manifest["dlc_run"] = dlc_info

        prediction_outputs = find_prediction_outputs([output_dir, input_dir, dlc_output_dir], started_at)
        h5_outputs = [path for path in prediction_outputs if path.suffix.lower() in {".h5", ".hdf5"}]
        manifest["prediction_outputs"] = [str(path) for path in prediction_outputs]
        manifest["h5_outputs"] = [str(path) for path in h5_outputs]

        add("DLC RUN")
        add(f"dlc_function={dlc_info.get('dlc_function')}")
        add(f"analyze_time_lapse_frames_signature={dlc_info.get('analyze_time_lapse_frames_signature')}")
        add(f"dlc_call_kwargs={json.dumps(dlc_info.get('dlc_call_kwargs'), default=str)}")
        add(f"dlc_elapsed_seconds={dlc_info.get('elapsed_seconds')}")
        add(f"prediction_outputs_found={len(prediction_outputs)}")
        for path in prediction_outputs:
            add(f"prediction_output={path}")
        add(f"h5_outputs_found={len(h5_outputs)}")
        add("")

        if not h5_outputs:
            raise RuntimeError("DLC ran, but no native H5/HDF5 prediction output was found. Refusing CSV-only bridge.")

        selected_h5 = h5_outputs[0]
        evidence_rows, h5_metadata = parse_h5_predictions(selected_h5, staged_rows)
        write_csv(evidence_csv_path, evidence_rows)

        prediction_ok_count = sum(1 for row in evidence_rows if truthy(row.get("dlc_prediction_ok")))
        ready_count = sum(1 for row in evidence_rows if clean(row.get("dlc_billtip_decision")) == "dlc_billtip_evidence_ready")

        manifest["selected_h5"] = str(selected_h5)
        manifest["h5_metadata"] = h5_metadata
        manifest["evidence_csv"] = str(evidence_csv_path)
        manifest["evidence_rows"] = len(evidence_rows)
        manifest["prediction_ok_count"] = prediction_ok_count
        manifest["ready_count"] = ready_count
        manifest["status"] = "PASS"

        add("H5-FIRST PARSE")
        add(f"selected_h5={selected_h5}")
        add(f"h5_rows={h5_metadata.get('h5_rows')}")
        add(f"dlc_available_bodyparts={json.dumps(h5_metadata.get('dlc_available_bodyparts'), default=str)}")
        add(f"selected_bodyparts={json.dumps(h5_metadata.get('selected_bodyparts'), default=str)}")
        add(f"bodypart_note={h5_metadata.get('bodypart_note')}")
        add("")

        add("SUMMARY")
        add(f"evidence_rows={len(evidence_rows)}")
        add(f"prediction_ok_count={prediction_ok_count}")
        add(f"ready_count={ready_count}")
        add(f"dlc_billtip_evidence_csv={evidence_csv_path}")
        add(f"database_mutation={str(DATABASE_MUTATION).lower()}")
        add(f"durable_evidence_written={str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        add(f"media_files_written={media_files_written}")
        add(f"elapsed_seconds={time.time() - started_at:.3f}")
        add("status=PASS")

        return_code = 0

    except Exception as exc:
        manifest["status"] = "FAIL"
        manifest["error_type"] = type(exc).__name__
        manifest["error"] = str(exc)

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
        add(f"media_files_written={media_files_written}")
        add("status=FAIL")
        return_code = 1

    finally:
        if working_config.exists() and not args.keep_working_config and manifest.get("status") == "PASS":
            try:
                working_config.unlink()
                working_config_removed = True
            except Exception:
                working_config_removed = False

        manifest["completed_at"] = utc_text()
        manifest["working_config_removed"] = working_config_removed
        manifest["report"] = str(report_path)
        write_json(manifest_path, manifest)
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

        print(f"script_name = {SCRIPT_NAME}")
        print(f"script_version = {SCRIPT_VERSION}")
        print(f"status = {manifest.get('status')}")
        print(f"output_dir = {output_dir}")
        print(f"report = {report_path}")
        print(f"dlc_input_map = {input_map_path}")
        print(f"dlc_billtip_evidence_csv = {evidence_csv_path}")
        print(f"manifest = {manifest_path}")
        print(f"database_mutation = {str(DATABASE_MUTATION).lower()}")
        print(f"durable_evidence_written = {str(DURABLE_EVIDENCE_WRITTEN).lower()}")
        print(f"media_files_written = {media_files_written}")

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
