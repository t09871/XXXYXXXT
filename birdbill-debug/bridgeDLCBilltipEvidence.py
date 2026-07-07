# bridgeDLCBilltipEvidence.py | v0.1 | 2026-07-07 PDT | Birdbill Step 9 DLC billtip evidence/schema bridge preview
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_NAME = "bridgeDLCBilltipEvidence.py"
SCRIPT_VERSION = "v0.1"
REWRITE_STEP = "9"
COMPONENT_NAME = "DLC billtip evidence/schema bridge preview"

DEFAULT_ROOT = Path(r"D:\birdbill")
DEFAULT_OUTPUT_ROOT = DEFAULT_ROOT / "output" / "debug"
DEFAULT_TRAINER_SOURCE = DEFAULT_ROOT / "app" / "billtipTrainerGUI.py"

# These are the fields that the current uploaded billtipTrainerGUI import path can consume
# through its GPT/prediction review layer. They are hints, not gold labels.
TRAINER_PREDICTION_IMPORT_COLUMNS = [
    "image_path",
    "candidate_path",
    "crop_path",
    "filename",
    "source_image",
    "gpt_label",
    "gpt_bill_base_x",
    "gpt_bill_base_y",
    "gpt_bill_tip_x",
    "gpt_bill_tip_y",
    "gpt_confidence",
    "gpt_reject_reason",
    "gpt_notes",
    "source_model",
    "source_model_version",
    "source_step",
    "source_records_csv",
]


LO_SCHEMA_COLUMNS = [
    "observation_id",
    "source_video",
    "source_media_context",
    "frame_id",
    "sequence_id",
    "detection_id",
    "detector_input_frame_path",
    "crop_path",
    "staged_path",
    "dlc_image_ref",
    "bbox",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "bbox_width",
    "bbox_height",
    "bbox_center_x",
    "bbox_center_y",
    "sync_session_id",
    "synced_time_ms",
    "calibration_id",
    "feeder_zone_id",
    "dlc_project_path",
    "dlc_config_path",
    "dlc_engine",
    "dlc_task",
    "dlc_scorer",
    "dlc_model_family",
    "dlc_training_fraction",
    "dlc_shuffle",
    "dlc_trainingsetindex",
    "dlc_prediction_csv",
    "dlc_bodyparts_seen",
    "dlc_bill_base_x",
    "dlc_bill_base_y",
    "dlc_bill_base_likelihood",
    "dlc_bill_tip_x",
    "dlc_bill_tip_y",
    "dlc_bill_tip_likelihood",
    "bill_vector_dx",
    "bill_vector_dy",
    "bill_length_px",
    "bill_angle_deg",
    "billtip_min_likelihood",
    "billtip_quality_band",
    "dlc_billtip_present",
    "biometrics_eligible",
    "trainer_review_recommended",
    "evidence_status",
    "notes",
]


def configure_stdio() -> None:
    for stream_name in ["stdout", "stderr"]:
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def clean_text(value: Any) -> str:
    text = str(value)
    return (
        text.replace("\ufeff", "")
        .replace("ï»¿", "")
        .encode("utf-8", errors="replace")
        .decode("utf-8", errors="replace")
    )


def safe_print(value: Any) -> None:
    print(clean_text(value))


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(clean_text(line) for line in lines) + "\n", encoding="utf-8")


def parse_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if text == "":
            return default
        parsed = float(text)
        if math.isnan(parsed):
            return default
        return parsed
    except Exception:
        return default


def find_latest_file(output_root: Path, pattern: str) -> Path | None:
    if not output_root.exists():
        return None
    candidates = [p for p in output_root.glob(pattern) if p.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.stat().st_mtime, str(p).lower()), reverse=True)
    return candidates[0]


def find_latest_nested_file(output_root: Path, dir_glob: str, filename: str) -> Path | None:
    if not output_root.exists():
        return None
    candidates: list[Path] = []
    for folder in output_root.glob(dir_glob):
        if folder.is_dir():
            target = folder / filename
            if target.exists() and target.is_file():
                candidates.append(target)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.stat().st_mtime, str(p).lower()), reverse=True)
    return candidates[0]


def safe_stem(value: str, fallback: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return stem or fallback


def row_get(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value)
    return ""


def normalize_path_for_match(value: str) -> str:
    return str(value).replace("\\", "/").lower()


def make_observation_id(row: dict[str, Any], index: int) -> str:
    parts = [
        row_get(row, "source_video", "src_source_video"),
        row_get(row, "frame_id", "src_frame_id"),
        row_get(row, "detection_id", "src_detection_id"),
        str(index),
    ]
    base = "-".join(safe_stem(str(part), "x") for part in parts if str(part).strip())
    return f"lo-dlc-{safe_stem(base, f'{index:05d}')}"


def quality_band(min_likelihood: float | None) -> str:
    if min_likelihood is None:
        return "missing"
    if min_likelihood >= 0.80:
        return "strong"
    if min_likelihood >= 0.60:
        return "usable_review"
    if min_likelihood >= 0.40:
        return "weak_review"
    return "very_weak_review"


def truthy_prediction_present(*values: float | None) -> bool:
    return all(value is not None and value >= 0 for value in values)


def load_json_if_exists(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def inspect_trainer_source(path: Path) -> dict[str, Any]:
    text = read_text_if_exists(path)
    info = {
        "path": str(path),
        "exists": path.exists(),
        "app_version": "",
        "has_gpt_prediction_import": False,
        "has_candidate_path_import": False,
        "has_premium_human_approved_comment": False,
        "old_hbmr_reference_count": 0,
        "birdbill_reference_count": 0,
        "notes": [],
    }
    if not text:
        info["notes"].append("trainer source missing or unreadable")
        return info

    m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if m:
        info["app_version"] = m.group(1)
    info["has_gpt_prediction_import"] = "import_gpt_predictions" in text and "gpt_bill_base_x" in text
    info["has_candidate_path_import"] = "candidate_path" in text and "image_path" in text
    info["has_premium_human_approved_comment"] = "Premium training export still requires human-approved" in text
    info["old_hbmr_reference_count"] = text.count(r"D:\HBMR")
    info["birdbill_reference_count"] = text.count(r"D:\birdbill")
    if info["old_hbmr_reference_count"]:
        info["notes"].append("trainer source still contains D:\\HBMR references")
    return info


def extract_dlc_context(step8_report: dict[str, Any]) -> dict[str, Any]:
    child = step8_report.get("dlc_child_report", {}) if isinstance(step8_report, dict) else {}
    cfg = child.get("config_read", {}) if isinstance(child, dict) else {}
    sigs = child.get("function_signatures", {}) if isinstance(child, dict) else {}
    return {
        "deeplabcut_version": child.get("deeplabcut_version", ""),
        "dlc_project_path": cfg.get("project_path", ""),
        "dlc_config_path": child.get("config_path", ""),
        "dlc_engine": cfg.get("engine", ""),
        "dlc_task": cfg.get("Task", ""),
        "dlc_scorer": cfg.get("scorer", ""),
        "dlc_model_family": cfg.get("default_net_type", ""),
        "dlc_training_fraction": ",".join(str(x) for x in cfg.get("TrainingFraction", [])) if isinstance(cfg.get("TrainingFraction"), list) else str(cfg.get("TrainingFraction", "")),
        "dlc_shuffle": "1",
        "dlc_trainingsetindex": "0",
        "time_lapse_has_destfolder": "destfolder" in sigs.get("analyze_time_lapse_frames", {}).get("params", []),
        "analyze_videos_has_destfolder": "destfolder" in sigs.get("analyze_videos", {}).get("params", []),
        "create_labeled_video_has_destfolder": "destfolder" in sigs.get("create_labeled_video", {}).get("params", []),
    }


def build_labeled_observation_preview(
    dlc_rows: list[dict[str, Any]],
    dlc_context: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, row in enumerate(dlc_rows, start=1):
        base_x = parse_float(row.get("bill_base_x"))
        base_y = parse_float(row.get("bill_base_y"))
        base_l = parse_float(row.get("bill_base_likelihood"))
        tip_x = parse_float(row.get("bill_tip_x"))
        tip_y = parse_float(row.get("bill_tip_y"))
        tip_l = parse_float(row.get("bill_tip_likelihood"))
        dx = parse_float(row.get("bill_vector_dx"))
        dy = parse_float(row.get("bill_vector_dy"))
        length = parse_float(row.get("bill_length_px"))

        if dx is None and base_x is not None and tip_x is not None:
            dx = tip_x - base_x
        if dy is None and base_y is not None and tip_y is not None:
            dy = tip_y - base_y
        if length is None and dx is not None and dy is not None:
            length = math.hypot(dx, dy)

        angle = math.degrees(math.atan2(dy, dx)) if dx is not None and dy is not None else None
        min_l = min([x for x in [base_l, tip_l] if x is not None], default=None)
        present = truthy_prediction_present(base_x, base_y, tip_x, tip_y)

        band = quality_band(min_l)
        biometrics_eligible = bool(present and min_l is not None and min_l >= 0.80)
        review_recommended = bool(present and min_l is not None and min_l >= 0.35)

        observation_id = make_observation_id(row, index)

        out.append(
            {
                "observation_id": observation_id,
                "source_video": row_get(row, "source_video", "src_source_video"),
                "source_media_context": row_get(row, "source_media_context", "src_source_media_context"),
                "frame_id": row_get(row, "frame_id", "src_frame_id"),
                "sequence_id": row_get(row, "sequence_id", "src_sequence_id"),
                "detection_id": row_get(row, "detection_id", "src_detection_id"),
                "detector_input_frame_path": row_get(row, "detector_input_frame_path", "src_detector_input_frame_path"),
                "crop_path": row_get(row, "crop_path", "src_crop_path"),
                "staged_path": row_get(row, "staged_path"),
                "dlc_image_ref": row_get(row, "dlc_image_ref"),
                "bbox": row_get(row, "bbox", "src_bbox"),
                "bbox_x1": row_get(row, "bbox_x1", "src_bbox_x1"),
                "bbox_y1": row_get(row, "bbox_y1", "src_bbox_y1"),
                "bbox_x2": row_get(row, "bbox_x2", "src_bbox_x2"),
                "bbox_y2": row_get(row, "bbox_y2", "src_bbox_y2"),
                "bbox_width": row_get(row, "bbox_width", "src_bbox_width"),
                "bbox_height": row_get(row, "bbox_height", "src_bbox_height"),
                "bbox_center_x": row_get(row, "bbox_center_x", "src_bbox_center_x"),
                "bbox_center_y": row_get(row, "bbox_center_y", "src_bbox_center_y"),
                "sync_session_id": row_get(row, "sync_session_id", "src_sync_session_id"),
                "synced_time_ms": row_get(row, "synced_time_ms", "src_synced_time_ms"),
                "calibration_id": row_get(row, "calibration_id", "src_calibration_id"),
                "feeder_zone_id": row_get(row, "feeder_zone_id", "src_feeder_zone_id"),
                "dlc_project_path": dlc_context.get("dlc_project_path", ""),
                "dlc_config_path": dlc_context.get("dlc_config_path", ""),
                "dlc_engine": dlc_context.get("dlc_engine", ""),
                "dlc_task": dlc_context.get("dlc_task", ""),
                "dlc_scorer": dlc_context.get("dlc_scorer", ""),
                "dlc_model_family": dlc_context.get("dlc_model_family", ""),
                "dlc_training_fraction": dlc_context.get("dlc_training_fraction", ""),
                "dlc_shuffle": dlc_context.get("dlc_shuffle", "1"),
                "dlc_trainingsetindex": dlc_context.get("dlc_trainingsetindex", "0"),
                "dlc_prediction_csv": row_get(row, "dlc_prediction_csv"),
                "dlc_bodyparts_seen": row_get(row, "bodyparts_seen"),
                "dlc_bill_base_x": base_x,
                "dlc_bill_base_y": base_y,
                "dlc_bill_base_likelihood": base_l,
                "dlc_bill_tip_x": tip_x,
                "dlc_bill_tip_y": tip_y,
                "dlc_bill_tip_likelihood": tip_l,
                "bill_vector_dx": dx,
                "bill_vector_dy": dy,
                "bill_length_px": length,
                "bill_angle_deg": angle,
                "billtip_min_likelihood": min_l,
                "billtip_quality_band": band,
                "dlc_billtip_present": present,
                "biometrics_eligible": biometrics_eligible,
                "trainer_review_recommended": review_recommended,
                "evidence_status": "debug_preview_not_db",
                "notes": "DLC billtip bridge preview; not durable evidence; not human-approved trainer label.",
            }
        )
    return out


def build_trainer_import_preview(
    dlc_rows: list[dict[str, Any]],
    dlc_records_csv: Path,
    dlc_context: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for row in dlc_rows:
        crop_path = row_get(row, "crop_path", "src_crop_path")
        staged_path = row_get(row, "staged_path")
        dlc_image_ref = row_get(row, "dlc_image_ref")
        image_path = crop_path or staged_path or dlc_image_ref
        min_l = min(
            [
                x
                for x in [
                    parse_float(row.get("bill_base_likelihood")),
                    parse_float(row.get("bill_tip_likelihood")),
                ]
                if x is not None
            ],
            default=None,
        )
        band = quality_band(min_l)

        out.append(
            {
                "image_path": image_path,
                "candidate_path": crop_path or image_path,
                "crop_path": crop_path,
                "filename": Path(image_path).name if image_path else "",
                "source_image": dlc_image_ref or staged_path or image_path,
                "gpt_label": "",
                "gpt_bill_base_x": row_get(row, "bill_base_x"),
                "gpt_bill_base_y": row_get(row, "bill_base_y"),
                "gpt_bill_tip_x": row_get(row, "bill_tip_x"),
                "gpt_bill_tip_y": row_get(row, "bill_tip_y"),
                "gpt_confidence": band,
                "gpt_reject_reason": "",
                "gpt_notes": (
                    f"DLC billtip prediction imported as review hint only; "
                    f"min_likelihood={min_l}; source_model=DeepLabCut {dlc_context.get('deeplabcut_version', '')}; "
                    f"task={dlc_context.get('dlc_task', '')}; scorer={dlc_context.get('dlc_scorer', '')}."
                ),
                "source_model": "DeepLabCut billtip",
                "source_model_version": dlc_context.get("deeplabcut_version", ""),
                "source_step": "Birdbill rewrite Step 9 bridge preview",
                "source_records_csv": str(dlc_records_csv),
            }
        )

    return out


def summarize_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bands: dict[str, int] = {}
    eligible = 0
    present = 0
    min_likelihoods: list[float] = []
    for row in rows:
        band = str(row.get("billtip_quality_band", "missing"))
        bands[band] = bands.get(band, 0) + 1
        if str(row.get("biometrics_eligible")).lower() == "true" or row.get("biometrics_eligible") is True:
            eligible += 1
        if str(row.get("dlc_billtip_present")).lower() == "true" or row.get("dlc_billtip_present") is True:
            present += 1
        value = parse_float(row.get("billtip_min_likelihood"))
        if value is not None:
            min_likelihoods.append(value)
    return {
        "rows": len(rows),
        "dlc_billtip_present_count": present,
        "biometrics_eligible_count": eligible,
        "quality_band_counts": bands,
        "min_likelihood_min": min(min_likelihoods) if min_likelihoods else None,
        "min_likelihood_max": max(min_likelihoods) if min_likelihoods else None,
    }


def build_contract_text(
    report: dict[str, Any],
    lo_rows: list[dict[str, Any]],
    trainer_rows: list[dict[str, Any]],
) -> list[str]:
    paths = report.get("paths", {})
    dlc_context = report.get("dlc_context", {})
    quality = report.get("quality_summary", {})
    trainer = report.get("trainer_source_scan", {})

    lines: list[str] = []
    lines.append("Birdbill Step 9 — DLC Billtip Evidence / Schema Bridge Preview")
    lines.append("=" * 76)
    lines.append("")
    lines.append("STATUS")
    lines.append(f"status = {report.get('status')}")
    lines.append("database_mutation = false")
    lines.append("durable_evidence_written = false")
    lines.append("media_files_written = 0")
    lines.append("")
    lines.append("INPUTS")
    lines.append(f"dlc_records_csv = {paths.get('dlc_records_csv')}")
    lines.append(f"step8_report_json = {paths.get('step8_report_json')}")
    lines.append(f"trainer_source = {paths.get('trainer_source')}")
    lines.append("")
    lines.append("DLC FACTS USED")
    lines.append(f"deeplabcut_version = {dlc_context.get('deeplabcut_version')}")
    lines.append(f"dlc_project_path = {dlc_context.get('dlc_project_path')}")
    lines.append(f"dlc_task = {dlc_context.get('dlc_task')}")
    lines.append(f"dlc_engine = {dlc_context.get('dlc_engine')}")
    lines.append(f"dlc_model_family = {dlc_context.get('dlc_model_family')}")
    lines.append(f"dlc_training_fraction = {dlc_context.get('dlc_training_fraction')}")
    lines.append(f"analyze_time_lapse_frames_has_destfolder = {dlc_context.get('time_lapse_has_destfolder')}")
    lines.append(f"analyze_videos_has_destfolder = {dlc_context.get('analyze_videos_has_destfolder')}")
    lines.append(f"create_labeled_video_has_destfolder = {dlc_context.get('create_labeled_video_has_destfolder')}")
    lines.append("")
    lines.append("BRIDGE OUTPUTS")
    lines.append(f"labeled_observation_preview_rows = {len(lo_rows)}")
    lines.append(f"trainer_import_preview_rows = {len(trainer_rows)}")
    lines.append(f"quality_summary = {json.dumps(quality, ensure_ascii=False, sort_keys=True)}")
    lines.append("")
    lines.append("TRAINER SOURCE")
    lines.append(f"exists = {trainer.get('exists')}")
    lines.append(f"app_version = {trainer.get('app_version')}")
    lines.append(f"has_gpt_prediction_import = {trainer.get('has_gpt_prediction_import')}")
    lines.append(f"has_candidate_path_import = {trainer.get('has_candidate_path_import')}")
    lines.append(f"old_hbmr_reference_count = {trainer.get('old_hbmr_reference_count')}")
    lines.append("")
    lines.append("CONTRACT DECISION")
    lines.append("- DLC billtip predictions are model evidence, not human-approved labels.")
    lines.append("- The labeled observation preview is the vNext evidence-facing shape.")
    lines.append("- The trainer import preview maps DLC points into the trainer prediction/review layer, not corrected fields.")
    lines.append("- Biometrics eligibility remains conservative; current preview requires high point likelihoods.")
    lines.append("- Future DLC implementation should support multiple modes: crop stills, short video analysis, labeled videos, filtered predictions, and separate future pose/bodypart projects.")
    lines.append("")
    lines.append("NEXT STEP RECOMMENDATION")
    lines.append("- Use this bridge preview to define the first merged labeled observation smoke.")
    lines.append("- Promote billtipTrainerGUI only after migrating old D:\\HBMR paths and preserving its human-approved premium export semantics.")
    lines.append("- Keep the current two-point billtip model frozen as a specialist asset; explore richer DLC usage as separate projects or modes.")
    return lines


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Birdbill Step 9 DLC billtip evidence/schema bridge preview")
    parser.add_argument("--project-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--dlc-records-csv", default="")
    parser.add_argument("--step8-report-json", default="")
    parser.add_argument("--trainer-source", default=str(DEFAULT_TRAINER_SOURCE))
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = build_arg_parser().parse_args(argv)

    started_at = utc_now()
    project_root = Path(args.project_root)
    output_root = Path(args.output_root)
    trainer_source = Path(args.trainer_source)

    dlc_records_csv = Path(args.dlc_records_csv) if args.dlc_records_csv else find_latest_nested_file(
        output_root,
        "dlc-billtip-*",
        "dlc-billtip-records.csv",
    )
    step8_report_json = Path(args.step8_report_json) if args.step8_report_json else find_latest_nested_file(
        output_root,
        "inspect-dlc-billtip-project-*",
        "inspect-dlc-billtip-project-report.json",
    )

    run_stamp = now_stamp()
    output_dir = output_root / f"dlc-billtip-bridge-{run_stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_json = output_dir / "dlc-billtip-bridge-report.json"
    report_txt = output_dir / "dlc-billtip-bridge-report.txt"
    status_path = output_dir / "status.txt"
    lo_csv = output_dir / "labeled-observation-dlc-billtip-preview.csv"
    lo_jsonl = output_dir / "labeled-observation-dlc-billtip-preview.jsonl"
    trainer_csv = output_dir / "billtip-trainer-dlc-import-preview.csv"
    trainer_json = output_dir / "billtip-trainer-dlc-import-preview.json"

    for line in [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"python_executable = {sys.executable}",
        f"project_root = {project_root}",
        f"output_root = {output_root}",
        f"dlc_records_csv = {dlc_records_csv}",
        f"step8_report_json = {step8_report_json}",
        f"trainer_source = {trainer_source}",
        f"output_dir = {output_dir}",
        "inference_run = false",
        "database_mutation = false",
        "durable_evidence_written = false",
        "media_files_written = 0",
    ]:
        safe_print(line)

    report: dict[str, Any] = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
        "component": COMPONENT_NAME,
        "started_at": started_at,
        "completed_at": "",
        "status": "FAIL",
        "inference_run": False,
        "database_mutation": False,
        "durable_evidence_written": False,
        "media_files_written": 0,
        "paths": {
            "project_root": str(project_root),
            "output_root": str(output_root),
            "output_dir": str(output_dir),
            "dlc_records_csv": str(dlc_records_csv) if dlc_records_csv else "",
            "step8_report_json": str(step8_report_json) if step8_report_json else "",
            "trainer_source": str(trainer_source),
            "report_json": str(report_json),
            "report_txt": str(report_txt),
            "labeled_observation_preview_csv": str(lo_csv),
            "labeled_observation_preview_jsonl": str(lo_jsonl),
            "trainer_import_preview_csv": str(trainer_csv),
            "trainer_import_preview_json": str(trainer_json),
        },
        "checks": {},
        "dlc_context": {},
        "trainer_source_scan": {},
        "quality_summary": {},
        "risk_notes": [],
        "bridge_decisions": [],
    }

    status_lines = [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"project_root = {project_root}",
        f"output_root = {output_root}",
        f"dlc_records_csv = {dlc_records_csv}",
        f"step8_report_json = {step8_report_json}",
        f"trainer_source = {trainer_source}",
        f"output_dir = {output_dir}",
        "inference_run = false",
        "database_mutation = false",
        "durable_evidence_written = false",
        "media_files_written = 0",
    ]

    return_code = 1

    try:
        checks = {
            "project_root_exists": project_root.exists(),
            "output_root_exists": output_root.exists(),
            "dlc_records_csv_exists": bool(dlc_records_csv and dlc_records_csv.exists()),
            "step8_report_json_exists": bool(step8_report_json and step8_report_json.exists()),
            "trainer_source_exists": trainer_source.exists(),
        }
        report["checks"] = checks
        for key, value in checks.items():
            status_lines.append(f"{key} = {str(value).lower()}")

        if not checks["dlc_records_csv_exists"]:
            raise FileNotFoundError("DLC records CSV not found. Pass --dlc-records-csv explicitly or run Step 6 first.")
        if not checks["step8_report_json_exists"]:
            report["risk_notes"].append("Step 8 report not found; DLC context will be incomplete.")

        dlc_rows = read_csv_dicts(dlc_records_csv)
        if not dlc_rows:
            raise RuntimeError("DLC records CSV has no rows")

        step8_report = load_json_if_exists(step8_report_json)
        dlc_context = extract_dlc_context(step8_report)
        report["dlc_context"] = dlc_context
        report["trainer_source_scan"] = inspect_trainer_source(trainer_source)

        if not trainer_source.exists():
            report["risk_notes"].append("Trainer source missing at D:\\birdbill\\app; trainer import preview still generated from known review-layer columns.")
        if report["trainer_source_scan"].get("old_hbmr_reference_count", 0):
            report["risk_notes"].append("Trainer source contains old D:\\HBMR references; migrate before promotion.")

        if dlc_context.get("time_lapse_has_destfolder") is False:
            report["risk_notes"].append("analyze_time_lapse_frames lacks destfolder; crop still predictions write beside input images.")
        if dlc_context.get("analyze_videos_has_destfolder"):
            report["risk_notes"].append("DLC video mode has destfolder and should remain a future implementation path, not be blocked by crop-only design.")

        lo_rows = build_labeled_observation_preview(dlc_rows, dlc_context)
        trainer_rows = build_trainer_import_preview(dlc_rows, dlc_records_csv, dlc_context)
        quality = summarize_quality(lo_rows)

        write_csv(lo_csv, lo_rows, fieldnames=LO_SCHEMA_COLUMNS)
        write_jsonl(lo_jsonl, lo_rows)
        write_csv(trainer_csv, trainer_rows, fieldnames=TRAINER_PREDICTION_IMPORT_COLUMNS)
        write_json(
            trainer_json,
            {
                "metadata": {
                    "script_name": SCRIPT_NAME,
                    "script_version": SCRIPT_VERSION,
                    "rewrite_step": REWRITE_STEP,
                    "created_at": utc_now(),
                    "role": "DLC billtip predictions as trainer review hints, not human-approved labels",
                    "source_records_csv": str(dlc_records_csv),
                },
                "predictions": trainer_rows,
            },
        )

        report["quality_summary"] = quality
        report["bridge_decisions"] = [
            "DLC billtip output maps to labeled observation model-evidence fields.",
            "DLC billtip output may also map to billtipTrainerGUI prediction/review hint fields.",
            "DLC billtip output must not be written as corrected/human-approved trainer points.",
            "Current still-crop DLC path is valid but must not block future video/labeled-video/filtering modes.",
            "Biometrics eligibility should be conservative and likelihood/pose/side-view gated.",
        ]
        report["status"] = "PASS"
        return_code = 0

    except Exception as exc:
        report["status"] = "FAIL"
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        status_lines.append("status = FAIL")
        status_lines.append(f"error_type = {type(exc).__name__}")
        status_lines.append(f"error = {exc}")
        return_code = 1

    finally:
        report["completed_at"] = utc_now()
        write_json(report_json, report)

        # Build text report after final status is set.
        lo_rows_for_text: list[dict[str, Any]] = []
        trainer_rows_for_text: list[dict[str, Any]] = []
        try:
            if lo_csv.exists():
                lo_rows_for_text = read_csv_dicts(lo_csv)
            if trainer_csv.exists():
                trainer_rows_for_text = read_csv_dicts(trainer_csv)
        except Exception:
            pass
        write_text(report_txt, build_contract_text(report, lo_rows_for_text, trainer_rows_for_text))

        status_lines.extend(
            [
                f"report_json = {report_json}",
                f"report_txt = {report_txt}",
                f"labeled_observation_preview_csv = {lo_csv}",
                f"labeled_observation_preview_jsonl = {lo_jsonl}",
                f"trainer_import_preview_csv = {trainer_csv}",
                f"trainer_import_preview_json = {trainer_json}",
                f"bridge_status = {report.get('status')}",
                f"quality_summary = {json.dumps(report.get('quality_summary', {}), ensure_ascii=False, sort_keys=True)}",
                "inference_run = false",
                "database_mutation = false",
                "durable_evidence_written = false",
                "media_files_written = 0",
            ]
        )
        write_text(status_path, status_lines)

        for line in [
            f"report_json = {report_json}",
            f"report_txt = {report_txt}",
            f"labeled_observation_preview_csv = {lo_csv}",
            f"labeled_observation_preview_jsonl = {lo_jsonl}",
            f"trainer_import_preview_csv = {trainer_csv}",
            f"trainer_import_preview_json = {trainer_json}",
            f"status_path = {status_path}",
            f"bridge_status = {report.get('status')}",
            f"quality_summary = {json.dumps(report.get('quality_summary', {}), ensure_ascii=False, sort_keys=True)}",
            "inference_run = false",
            "database_mutation = false",
            "durable_evidence_written = false",
            "media_files_written = 0",
        ]:
            safe_print(line)

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
