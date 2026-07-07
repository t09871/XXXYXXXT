# smokeDLCBilltip.py | v0.6 | 2026-07-07 PDT | Birdbill Step 6 DLC billtip smoke with project-root sanitized working config
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_NAME = "smokeDLCBilltip.py"
SCRIPT_VERSION = "v0.6"
REWRITE_STEP = "6"
COMPONENT_NAME = "DLC billtip smoke"

DEFAULT_ROOT = Path(r"D:\birdbill")
DEFAULT_CANDIDATES_CSV = DEFAULT_ROOT / "output" / "debug" / "retention-crop-scoring-20260706-223423" / "bird-candidates.csv"
DEFAULT_DLC_CONFIG = DEFAULT_ROOT / "modules" / "dlc" / "billtip" / "billtip-HB-2026-06-30" / "config.yaml"
DEFAULT_DLC_PYTHON = Path(r"C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe")
DEFAULT_OUTPUT_ROOT = DEFAULT_ROOT / "output" / "debug"

CORE_PRESERVE_FIELDS = [
    "source_video",
    "source_media_context",
    "frame_id",
    "sequence_id",
    "detection_id",
    "crop_path",
    "detector_input_frame_path",
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_status(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(clean_text(line) for line in lines) + "\n", encoding="utf-8")


def read_text_lossless(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def sanitize_dlc_config_copy(original_config: Path, audit_config: Path, working_config: Path) -> dict[str, Any]:
    original_text = read_text_lossless(original_config)
    sanitized_text = original_text

    # Fix both true UTF BOM and mojibaked BOM forms that can appear as a YAML key prefix.
    sanitized_text = sanitized_text.replace("\ufeffTask:", "Task:")
    sanitized_text = sanitized_text.replace("ï»¿Task:", "Task:")

    # Also remove any remaining BOM characters at the start of the file.
    sanitized_text = sanitized_text.lstrip("\ufeff")
    sanitized_text = sanitized_text.replace("\ufeff", "")

    audit_config.parent.mkdir(parents=True, exist_ok=True)
    audit_config.write_text(sanitized_text, encoding="utf-8", newline="\n")

    # DLC 3 resolves project metadata relative to the config file's parent folder.
    # Therefore the working config must live beside the real project config, even
    # though an audit copy also lives under output\debug. This does not mutate
    # the original config.yaml and is removed after the smoke unless requested.
    working_config.write_text(sanitized_text, encoding="utf-8", newline="\n")

    original_has_task = bool(re.search(r"(?m)^\s*Task\s*:", original_text))
    original_has_bom_task = bool(re.search(r"(?m)^\s*(?:\ufeff|ï»¿)Task\s*:", original_text))
    sanitized_has_task = bool(re.search(r"(?m)^\s*Task\s*:", sanitized_text))
    sanitized_has_bom_task = bool(re.search(r"(?m)^\s*(?:\ufeff|ï»¿)Task\s*:", sanitized_text))

    return {
        "original_config": str(original_config),
        "audit_sanitized_config": str(audit_config),
        "working_sanitized_config": str(working_config),
        "working_sanitized_config_parent_is_original_project": working_config.parent == original_config.parent,
        "original_has_task_key": original_has_task,
        "original_has_bom_or_mojibake_task_key": original_has_bom_task,
        "sanitized_has_task_key": sanitized_has_task,
        "sanitized_has_bom_or_mojibake_task_key": sanitized_has_bom_task,
        "original_size_bytes": original_config.stat().st_size,
        "audit_sanitized_size_bytes": audit_config.stat().st_size,
        "working_sanitized_size_bytes": working_config.stat().st_size,
        "original_config_mutated": False,
    }


def choose_crop_path(row: dict[str, str]) -> str:
    for key in ["crop_path", "retained_crop_path", "crop_export_path", "image_path"]:
        value = row.get(key, "").strip()
        if value:
            return value
    return ""


def stage_candidates(candidates: list[dict[str, str]], input_dir: Path, max_candidates: int) -> tuple[list[dict[str, Any]], int]:
    input_dir.mkdir(parents=True, exist_ok=True)
    candidate_map: list[dict[str, Any]] = []
    media_files_written = 0

    for index, row in enumerate(candidates[:max_candidates], start=1):
        crop_path_text = choose_crop_path(row)
        crop_path = Path(crop_path_text) if crop_path_text else None

        detection_id = row.get("detection_id", "").strip() or f"candidate-{index:05d}"
        frame_id = row.get("frame_id", "").strip() or f"frame-unknown-{index:05d}"
        stage_stem = safe_name(f"{index:05d}-{frame_id}-{detection_id}", f"candidate-{index:05d}")
        staged_path = input_dir / f"{stage_stem}.jpg"

        exists = bool(crop_path and crop_path.exists())
        copied = False
        reason = ""

        if exists and crop_path is not None:
            shutil.copy2(crop_path, staged_path)
            copied = True
            media_files_written += 1
        else:
            reason = f"crop_path missing or does not exist: {crop_path_text}"

        mapped: dict[str, Any] = {
            "candidate_index": index,
            "candidate_id": f"dlc-candidate-{index:05d}",
            "staged_filename": staged_path.name,
            "staged_path": str(staged_path) if copied else "",
            "staged_media_written": copied,
            "stage_failure_reason": reason,
        }

        for field in CORE_PRESERVE_FIELDS:
            mapped[field] = row.get(field, "")

        for key, value in row.items():
            mapped.setdefault(f"src_{key}", value)

        candidate_map.append(mapped)

    return candidate_map, media_files_written


def make_dlc_child_runner(path: Path) -> None:
    child_code = '''# runDLCBilltipChild.py | generated by smokeDLCBilltip.py v0.6 | Runs inside DLC environment
from __future__ import annotations

import inspect
import json
import sys
import traceback
from pathlib import Path


def configure_stdio() -> None:
    for stream_name in ["stdout", "stderr"]:
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def clean_text(value) -> str:
    text = str(value)
    return text.replace("\\ufeff", "").replace("ï»¿", "")


def safe_print(value) -> None:
    print(clean_text(value))


def main() -> int:
    configure_stdio()

    config_path = Path(sys.argv[1])
    input_dir = Path(sys.argv[2])
    output_dir = Path(sys.argv[3])
    frametype = sys.argv[4]

    safe_print("child_script = runDLCBilltipChild.py")
    safe_print("child_script_version = generated-v0.6")
    safe_print(f"child_python_executable = {sys.executable}")
    safe_print(f"config_path = {config_path}")
    safe_print(f"input_dir = {input_dir}")
    safe_print(f"output_dir = {output_dir}")
    safe_print(f"frametype = {frametype}")

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import deeplabcut
        safe_print("deeplabcut_import = PASS")
        safe_print(f"deeplabcut_version = {getattr(deeplabcut, '__version__', 'unknown')}")

        from deeplabcut.utils import auxiliaryfunctions
        try:
            cfg = auxiliaryfunctions.read_config(str(config_path))
            safe_print("dlc_read_config = PASS")
            safe_print("dlc_config_keys = " + ",".join(sorted(str(k) for k in cfg.keys())))
            safe_print(f"dlc_config_task = {cfg.get('Task', '')}")
            safe_print(f"dlc_config_bodyparts = {json.dumps(cfg.get('bodyparts', []), default=str)}")
            safe_print(f"dlc_config_project_path = {cfg.get('project_path', '')}")
        except Exception as cfg_exc:
            safe_print("dlc_read_config = FAIL")
            safe_print(f"dlc_read_config_error_type = {type(cfg_exc).__name__}")
            safe_print(f"dlc_read_config_error = {cfg_exc}")
            raise

        func = deeplabcut.analyze_time_lapse_frames
        signature = inspect.signature(func)
        params = list(signature.parameters.keys())
        safe_print(f"analyze_time_lapse_frames_signature = {signature}")
        safe_print("analyze_time_lapse_frames_params = " + ",".join(params))

        kwargs = {
            "frametype": frametype,
            "save_as_csv": True,
            "shuffle": 1,
            "trainingsetindex": 0,
        }
        if "destfolder" in params:
            kwargs["destfolder"] = str(output_dir)

        safe_print("dlc_call_kwargs = " + json.dumps(kwargs, default=str))
        result = func(str(config_path), str(input_dir), **kwargs)

        safe_print("dlc_inference = PASS")
        try:
            safe_print("dlc_result_json = " + json.dumps(result, default=str))
        except Exception:
            safe_print(f"dlc_result_repr = {repr(result)}")
        return 0

    except Exception as exc:
        safe_print("dlc_inference = FAIL")
        safe_print(f"error_type = {type(exc).__name__}")
        safe_print(f"error = {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(child_code, encoding="utf-8")


def list_prediction_outputs(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    ignored = {"candidate-map.csv", "dlc-billtip-records.csv"}
    for base in paths:
        if not base.exists():
            continue
        for suffix in ["*.csv", "*.h5", "*.hdf5"]:
            found.extend(base.rglob(suffix))
    return sorted(
        [p for p in found if p.name not in ignored],
        key=lambda p: (str(p.parent).lower(), p.name.lower()),
    )


def normalize_name(value: str) -> str:
    return Path(value.replace("\\", "/")).name.lower()


def parse_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        parsed = float(value)
        if math.isnan(parsed):
            return None
        return parsed
    except Exception:
        return None


def parse_dlc_prediction_csv(csv_path: Path, candidate_map: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))

    if len(rows) < 4:
        return []

    scorer_row = rows[0]
    bodyparts_row = rows[1]
    coords_row = rows[2]
    data_rows = rows[3:]

    by_stage_name = {
        str(item.get("staged_filename", "")).lower(): item
        for item in candidate_map
        if item.get("staged_filename")
    }

    records: list[dict[str, Any]] = []

    for data in data_rows:
        if not data:
            continue

        image_ref = data[0]
        image_name = normalize_name(image_ref)
        item = by_stage_name.get(image_name)

        if item is None:
            image_stem = Path(image_name).stem.lower()
            for stage_name, candidate in by_stage_name.items():
                if Path(stage_name).stem.lower() == image_stem:
                    item = candidate
                    break

        base: dict[str, Any] = {}
        if item is not None:
            for field in CORE_PRESERVE_FIELDS:
                base[field] = item.get(field, "")
            base["candidate_id"] = item.get("candidate_id", "")
            base["candidate_index"] = item.get("candidate_index", "")
            base["staged_filename"] = item.get("staged_filename", "")
            base["staged_path"] = item.get("staged_path", "")
        else:
            base["candidate_id"] = ""
            base["candidate_index"] = ""
            base["staged_filename"] = image_name
            base["staged_path"] = image_ref

        values: dict[str, Any] = {}
        max_cols = min(len(data), len(bodyparts_row), len(coords_row), len(scorer_row))
        scorer = ""
        for col in range(1, max_cols):
            bodypart = bodyparts_row[col].strip()
            coord = coords_row[col].strip()
            if not bodypart or not coord:
                continue
            if not scorer:
                scorer = scorer_row[col].strip()
            values[f"{bodypart}_{coord}"] = parse_float(data[col])

        bill_base_x = values.get("bill_base_x")
        bill_base_y = values.get("bill_base_y")
        bill_tip_x = values.get("bill_tip_x")
        bill_tip_y = values.get("bill_tip_y")

        bill_vector_dx = None
        bill_vector_dy = None
        bill_length_px = None
        if None not in [bill_base_x, bill_base_y, bill_tip_x, bill_tip_y]:
            bill_vector_dx = float(bill_tip_x) - float(bill_base_x)
            bill_vector_dy = float(bill_tip_y) - float(bill_base_y)
            bill_length_px = math.sqrt((bill_vector_dx ** 2) + (bill_vector_dy ** 2))

        records.append(
            {
                **base,
                "dlc_prediction_csv": str(csv_path),
                "dlc_image_ref": image_ref,
                "dlc_scorer": scorer,
                "bill_base_x": values.get("bill_base_x"),
                "bill_base_y": values.get("bill_base_y"),
                "bill_base_likelihood": values.get("bill_base_likelihood"),
                "bill_tip_x": values.get("bill_tip_x"),
                "bill_tip_y": values.get("bill_tip_y"),
                "bill_tip_likelihood": values.get("bill_tip_likelihood"),
                "bill_vector_dx": bill_vector_dx,
                "bill_vector_dy": bill_vector_dy,
                "bill_length_px": bill_length_px,
                "bodyparts_seen": sorted({bp.strip() for bp in bodyparts_row if bp.strip() and bp.strip().lower() != "bodyparts"}),
            }
        )

    return records


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Birdbill Step 6 DLC billtip smoke")
    parser.add_argument("--candidates-csv", default=str(DEFAULT_CANDIDATES_CSV))
    parser.add_argument("--dlc-config", default=str(DEFAULT_DLC_CONFIG))
    parser.add_argument("--dlc-python", default=str(DEFAULT_DLC_PYTHON))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--max-candidates", type=int, default=25)
    parser.add_argument("--diagnostic-only", action="store_true")
    parser.add_argument("--keep-working-config", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = build_arg_parser().parse_args(argv)

    started_at = utc_now()
    run_stamp = now_stamp()
    output_dir = Path(args.output_root) / f"dlc-billtip-{run_stamp}"
    input_dir = output_dir / "dlc-input"
    dlc_output_dir = output_dir / "dlc-output"
    config_dir = output_dir / "config"
    audit_sanitized_config = config_dir / "config-sanitized-audit.yaml"
    child_runner = output_dir / "runDLCBilltipChild.py"
    child_stdout = output_dir / "dlc-child-stdout.txt"
    child_stderr = output_dir / "dlc-child-stderr.txt"
    candidate_map_path = output_dir / "candidate-map.csv"
    records_csv_path = output_dir / "dlc-billtip-records.csv"
    records_jsonl_path = output_dir / "dlc-billtip-records.jsonl"
    manifest_path = output_dir / "manifest.json"
    ledger_path = output_dir / "dlc-billtip-storage-ledger.json"
    status_path = output_dir / "status.txt"

    candidates_csv = Path(args.candidates_csv)
    original_dlc_config = Path(args.dlc_config)
    dlc_python = Path(args.dlc_python)
    working_sanitized_config = original_dlc_config.parent / f"config-birdbill-smoke-v0.6-{run_stamp}.yaml"

    for line in [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"python_executable = {sys.executable}",
        f"candidates_csv = {candidates_csv}",
        f"original_dlc_config = {original_dlc_config}",
        f"audit_sanitized_config = {audit_sanitized_config}",
        f"working_sanitized_config = {working_sanitized_config}",
        f"dlc_python = {dlc_python}",
        f"output_dir = {output_dir}",
        "database_mutation = false",
        "durable_evidence_written = false",
        "broad_media_export = false",
    ]:
        safe_print(line)

    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
        "component": COMPONENT_NAME,
        "started_at": started_at,
        "completed_at": "",
        "status": "FAIL",
        "failure_reasons": [],
        "python_executable": sys.executable,
        "candidates_csv": str(candidates_csv),
        "original_dlc_config": str(original_dlc_config),
        "audit_sanitized_config": str(audit_sanitized_config),
        "working_sanitized_config": str(working_sanitized_config),
        "working_sanitized_config_removed": False,
        "dlc_python": str(dlc_python),
        "output_dir": str(output_dir),
        "database_mutation": False,
        "durable_evidence_written": False,
        "broad_media_export": False,
        "media_files_written": 0,
        "records_written": 0,
        "dlc_child_exit_code": None,
        "prediction_outputs": [],
    }

    status_lines = [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"python_executable = {sys.executable}",
        f"candidates_csv = {candidates_csv}",
        f"original_dlc_config = {original_dlc_config}",
        f"audit_sanitized_config = {audit_sanitized_config}",
        f"working_sanitized_config = {working_sanitized_config}",
        f"dlc_python = {dlc_python}",
        f"output_dir = {output_dir}",
        "database_mutation = false",
        "durable_evidence_written = false",
        "broad_media_export = false",
    ]

    return_code = 1

    try:
        checks = {
            "candidates_csv_exists": candidates_csv.exists(),
            "original_dlc_config_exists": original_dlc_config.exists(),
            "dlc_python_exists": dlc_python.exists(),
            "original_dlc_project_dir_exists": original_dlc_config.parent.exists(),
        }
        manifest["checks"] = checks

        for name, ok in checks.items():
            status_lines.append(f"{name} = {str(ok).lower()}")
            if not ok:
                manifest["failure_reasons"].append(f"{name}=false")

        if manifest["failure_reasons"]:
            raise RuntimeError("; ".join(manifest["failure_reasons"]))

        sanitize_info = sanitize_dlc_config_copy(original_dlc_config, audit_sanitized_config, working_sanitized_config)
        manifest["config_sanitize_info"] = sanitize_info
        for key, value in sanitize_info.items():
            status_lines.append(f"config_{key} = {value}")

        if not sanitize_info["sanitized_has_task_key"]:
            raise RuntimeError("Sanitized config still does not contain a normal Task key")
        if not sanitize_info["working_sanitized_config_parent_is_original_project"]:
            raise RuntimeError("Working sanitized config is not in the original DLC project directory")

        candidates = read_csv_dicts(candidates_csv)
        manifest["input_candidate_rows"] = len(candidates)
        if not candidates:
            raise RuntimeError("bird-candidates.csv has no rows")

        candidate_map, media_files_written = stage_candidates(candidates, input_dir, args.max_candidates)
        manifest["candidate_rows_staged"] = len(candidate_map)
        manifest["media_files_written"] = media_files_written
        write_csv(candidate_map_path, candidate_map)

        staged_ok = [row for row in candidate_map if row.get("staged_media_written")]
        manifest["staged_media_ok_count"] = len(staged_ok)
        if not staged_ok:
            raise RuntimeError("No candidate crop images could be staged for DLC input")

        make_dlc_child_runner(child_runner)

        if args.diagnostic_only:
            manifest["status"] = "PASS"
            manifest["diagnostic_only"] = True
            status_lines.append("diagnostic_only = true")
            status_lines.append("status = PASS")
            return_code = 0
        else:
            command = [
                str(dlc_python),
                str(child_runner),
                str(working_sanitized_config),
                str(input_dir),
                str(dlc_output_dir),
                ".jpg",
            ]
            manifest["dlc_child_command"] = command

            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"

            completed = subprocess.run(
                command,
                cwd=str(output_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )

            child_stdout.write_text(completed.stdout, encoding="utf-8", errors="replace")
            child_stderr.write_text(completed.stderr, encoding="utf-8", errors="replace")

            manifest["dlc_child_exit_code"] = completed.returncode
            status_lines.append(f"dlc_child_exit_code = {completed.returncode}")

            safe_print("----- dlc-child-stdout -----")
            safe_print(completed.stdout)
            safe_print("----- end dlc-child-stdout -----")
            safe_print("----- dlc-child-stderr -----")
            safe_print(completed.stderr)
            safe_print("----- end dlc-child-stderr -----")

            if completed.returncode != 0:
                raise RuntimeError(f"DLC child process failed with exit code {completed.returncode}")

            prediction_outputs = list_prediction_outputs([dlc_output_dir, input_dir, output_dir])
            manifest["prediction_outputs"] = [str(path) for path in prediction_outputs]
            status_lines.append(f"prediction_outputs_count = {len(prediction_outputs)}")

            prediction_csvs = [path for path in prediction_outputs if path.suffix.lower() == ".csv"]
            if not prediction_csvs:
                raise RuntimeError("DLC produced no prediction CSV")

            records: list[dict[str, Any]] = []
            for prediction_csv in prediction_csvs:
                records.extend(parse_dlc_prediction_csv(prediction_csv, candidate_map))

            if not records:
                raise RuntimeError("No DLC prediction records could be parsed")

            write_csv(records_csv_path, records)
            write_jsonl(records_jsonl_path, records)
            manifest["records_written"] = len(records)
            status_lines.append(f"records_written = {len(records)}")
            manifest["status"] = "PASS"
            status_lines.append("status = PASS")
            return_code = 0

    except Exception as exc:
        manifest["status"] = "FAIL"
        manifest["failure_reasons"].append(f"{type(exc).__name__}: {exc}")
        manifest["traceback"] = traceback.format_exc()
        status_lines.append("status = FAIL")
        status_lines.append("failure_reasons = " + " | ".join(str(x) for x in manifest["failure_reasons"]))
        status_lines.append(f"error_type = {type(exc).__name__}")
        status_lines.append(f"error = {exc}")
        return_code = 1

    finally:
        if working_sanitized_config.exists() and not args.keep_working_config:
            try:
                working_sanitized_config.unlink()
                manifest["working_sanitized_config_removed"] = True
            except Exception as cleanup_exc:
                manifest["working_sanitized_config_cleanup_error"] = f"{type(cleanup_exc).__name__}: {cleanup_exc}"

        manifest["completed_at"] = utc_now()

        ledger = {
            "script_name": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "rewrite_step": REWRITE_STEP,
            "component": COMPONENT_NAME,
            "source_of_truth": {
                "source_video_remains_canonical": True,
                "candidate_csv": str(candidates_csv),
                "candidate_csv_role": "Step 5 retained/scored bird candidates",
                "original_dlc_config": str(original_dlc_config),
                "original_dlc_config_mutated": False,
                "audit_sanitized_config": str(audit_sanitized_config),
                "working_sanitized_config": str(working_sanitized_config),
                "working_sanitized_config_removed": manifest.get("working_sanitized_config_removed", False),
            },
            "storage_classes": {
                "audit_sanitized_config_copy": {
                    "path": str(audit_sanitized_config),
                    "role": "debug audit copy of sanitized DLC config",
                    "purgeable": True,
                    "durable_evidence": False,
                },
                "project_root_working_config_copy": {
                    "path": str(working_sanitized_config),
                    "role": "temporary project-root DLC config copy so DLC can find model metadata",
                    "purgeable": True,
                    "durable_evidence": False,
                    "removed_after_run": manifest.get("working_sanitized_config_removed", False),
                },
                "staged_dlc_input_images": {
                    "path": str(input_dir),
                    "role": "temporary DLC debug working copies",
                    "purgeable": True,
                    "durable_evidence": False,
                    "files_written": manifest.get("media_files_written", 0),
                },
                "dlc_raw_outputs": {
                    "path": str(dlc_output_dir),
                    "role": "DLC debug inference output",
                    "purgeable": True,
                    "durable_evidence": False,
                },
                "records": {
                    "paths": [str(records_csv_path), str(records_jsonl_path)],
                    "role": "Step 6 DLC billtip smoke records",
                    "purgeable": True,
                    "durable_evidence": False,
                },
                "manifests_logs_ledgers": {
                    "paths": [str(manifest_path), str(ledger_path), str(status_path), str(child_stdout), str(child_stderr)],
                    "role": "audit/debug reporting",
                    "purgeable": True,
                    "durable_evidence": False,
                },
            },
            "database_mutation": False,
            "durable_evidence_written": False,
            "broad_media_export": False,
            "media_files_written": manifest.get("media_files_written", 0),
        }

        write_json(manifest_path, manifest)
        write_json(ledger_path, ledger)

        status_lines.extend(
            [
                f"manifest = {manifest_path}",
                f"storage_ledger = {ledger_path}",
                f"child_stdout = {child_stdout}",
                f"child_stderr = {child_stderr}",
                f"candidate_map = {candidate_map_path}",
                f"records_csv = {records_csv_path}",
                f"records_jsonl = {records_jsonl_path}",
                "database_mutation = false",
                "durable_evidence_written = false",
                "broad_media_export = false",
                f"media_files_written = {manifest.get('media_files_written', 0)}",
            ]
        )
        write_status(status_path, status_lines)

        for line in [
            f"manifest = {manifest_path}",
            f"storage_ledger = {ledger_path}",
            f"child_stdout = {child_stdout}",
            f"child_stderr = {child_stderr}",
            f"candidate_map = {candidate_map_path}",
            f"records_csv = {records_csv_path}",
            f"records_jsonl = {records_jsonl_path}",
            f"working_sanitized_config_removed = {str(manifest.get('working_sanitized_config_removed', False)).lower()}",
            "database_mutation = false",
            "durable_evidence_written = false",
            "broad_media_export = false",
            f"media_files_written = {manifest.get('media_files_written', 0)}",
            f"smoke_status = {manifest['status']}",
            "failure_reasons = " + " | ".join(str(x) for x in manifest.get("failure_reasons", [])),
        ]:
            safe_print(line)

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
