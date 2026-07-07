# inspectDLCBilltipProject.py | v0.1 | 2026-07-07 PDT | Birdbill Step 8 read-only DLC billtip project inspector
from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_NAME = "inspectDLCBilltipProject.py"
SCRIPT_VERSION = "v0.1"
REWRITE_STEP = "8"
COMPONENT_NAME = "DLC billtip project inspector"

DEFAULT_ROOT = Path(r"D:\birdbill")
DEFAULT_DLC_PROJECT_DIR = DEFAULT_ROOT / "modules" / "dlc" / "billtip" / "billtip-HB-2026-06-30"
DEFAULT_DLC_CONFIG = DEFAULT_DLC_PROJECT_DIR / "config.yaml"
DEFAULT_DLC_PYTHON = Path(r"C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe")
DEFAULT_OUTPUT_ROOT = DEFAULT_ROOT / "output" / "debug"
DEFAULT_TRAINER_SOURCE = DEFAULT_ROOT / "app" / "billtipTrainerGUI.py"


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(clean_text(line) for line in lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_text_lossless(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"


def limited_files(base: Path, patterns: list[str], limit: int = 200) -> list[str]:
    if not base.exists():
        return []
    found: list[Path] = []
    for pattern in patterns:
        found.extend(base.rglob(pattern))
    unique = sorted({p for p in found if p.is_file()}, key=lambda p: str(p).lower())
    return [str(p) for p in unique[:limit]]


def limited_dirs(base: Path, patterns: list[str], limit: int = 200) -> list[str]:
    if not base.exists():
        return []
    found: list[Path] = []
    for pattern in patterns:
        found.extend(base.rglob(pattern))
    unique = sorted({p for p in found if p.is_dir()}, key=lambda p: str(p).lower())
    return [str(p) for p in unique[:limit]]


def scan_config_text(config_path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(config_path),
        "exists": config_path.exists(),
        "readable": False,
        "encoding_used": "",
        "size_bytes": None,
        "has_normal_task_key": False,
        "has_bom_or_mojibake_task_key": False,
        "task_key_line_preview": "",
        "top_level_key_presence": {},
        "literal_paths_seen": [],
        "project_path_text_value": "",
        "notes": [],
    }
    if not config_path.exists():
        info["notes"].append("config.yaml does not exist")
        return info

    text, encoding = read_text_lossless(config_path)
    info["readable"] = True
    info["encoding_used"] = encoding
    info["size_bytes"] = config_path.stat().st_size
    info["has_normal_task_key"] = bool(re.search(r"(?m)^\s*Task\s*:", text))
    info["has_bom_or_mojibake_task_key"] = bool(re.search(r"(?m)^\s*(?:\ufeff|ï»¿)Task\s*:", text))

    for line in text.splitlines():
        if "Task" in line:
            info["task_key_line_preview"] = clean_text(line)
            break

    for key in [
        "Task",
        "scorer",
        "project_path",
        "video_sets",
        "bodyparts",
        "TrainingFraction",
        "snapshotindex",
        "default_net_type",
        "engine",
        "multianimalproject",
        "individuals",
        "uniquebodyparts",
        "multianimalbodyparts",
        "default_track_method",
    ]:
        info["top_level_key_presence"][key] = bool(re.search(rf"(?m)^\s*{re.escape(key)}\s*:", text))

    project_match = re.search(r"(?m)^\s*project_path\s*:\s*(.+?)\s*$", text)
    if project_match:
        info["project_path_text_value"] = clean_text(project_match.group(1).strip().strip("'\""))

    literal_paths = re.findall(r"[A-Za-z]:\\[^\n\r\"']+", text)
    info["literal_paths_seen"] = [clean_text(p.strip()) for p in literal_paths[:50]]

    if info["has_bom_or_mojibake_task_key"] and not info["has_normal_task_key"]:
        info["notes"].append("Task key appears BOM/mojibake-prefixed; DLC may read it as ï»¿Task instead of Task.")

    return info


def infer_shuffle_from_name(path_text: str) -> dict[str, Any]:
    name = Path(path_text).name
    full = str(path_text)
    result: dict[str, Any] = {
        "path": path_text,
        "name": name,
        "train_fraction": "",
        "shuffle": "",
        "iteration": "",
    }

    frac_match = re.search(r"trainset(\d+)", full, flags=re.IGNORECASE)
    shuffle_match = re.search(r"shuffle(\d+)", full, flags=re.IGNORECASE)
    iteration_match = re.search(r"iteration[-_]?(\d+)", full, flags=re.IGNORECASE)

    if frac_match:
        result["train_fraction"] = frac_match.group(1)
    if shuffle_match:
        result["shuffle"] = shuffle_match.group(1)
    if iteration_match:
        result["iteration"] = iteration_match.group(1)

    return result


def inspect_project_files(project_dir: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "project_dir": str(project_dir),
        "exists": project_dir.exists(),
        "metadata_yaml_files": [],
        "dlc_model_dirs": [],
        "training_dataset_dirs": [],
        "labeled_data_dirs": [],
        "video_files": [],
        "snapshot_files": [],
        "pose_cfg_files": [],
        "pytorch_config_files": [],
        "model_folder_shuffle_inferences": [],
        "risk_notes": [],
    }
    if not project_dir.exists():
        info["risk_notes"].append("DLC project directory does not exist.")
        return info

    info["metadata_yaml_files"] = limited_files(project_dir, ["metadata.yaml"], limit=100)
    info["dlc_model_dirs"] = limited_dirs(project_dir, ["dlc-models", "*shuffle*"], limit=200)
    info["training_dataset_dirs"] = limited_dirs(project_dir, ["training-datasets", "UnaugmentedDataSet*"], limit=200)
    info["labeled_data_dirs"] = limited_dirs(project_dir, ["labeled-data", "*labeled*"], limit=200)
    info["video_files"] = limited_files(project_dir, ["*.mp4", "*.avi", "*.mov", "*.mkv"], limit=100)
    info["snapshot_files"] = limited_files(
        project_dir,
        ["snapshot*", "*.index", "*.meta", "*.data-*", "*.pt", "*.pth", "*.ckpt"],
        limit=200,
    )
    info["pose_cfg_files"] = limited_files(project_dir, ["pose_cfg.yaml", "pose_cfg.yml"], limit=100)
    info["pytorch_config_files"] = limited_files(project_dir, ["pytorch_config.yaml", "pytorch_config.yml"], limit=100)

    shuffle_sources = info["dlc_model_dirs"] + info["snapshot_files"] + info["metadata_yaml_files"]
    inferred: list[dict[str, Any]] = []
    seen = set()
    for path_text in shuffle_sources:
        item = infer_shuffle_from_name(path_text)
        key = (item.get("train_fraction"), item.get("shuffle"), item.get("iteration"), item.get("path"))
        if key not in seen:
            seen.add(key)
            inferred.append(item)
    info["model_folder_shuffle_inferences"] = inferred

    if not info["metadata_yaml_files"]:
        info["risk_notes"].append("No metadata.yaml found under project; DLC 3 may need/migrate metadata to identify shuffles.")
    if not info["snapshot_files"]:
        info["risk_notes"].append("No snapshot/checkpoint-like files found under project; inference may fail unless model files use an unrecognized naming convention.")
    if not info["dlc_model_dirs"]:
        info["risk_notes"].append("No dlc-models or shuffle-like model directory found.")

    return info


def parse_python_literal_list(node: ast.AST) -> list[Any] | None:
    if isinstance(node, (ast.List, ast.Tuple)):
        values: list[Any] = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant):
                values.append(elt.value)
            else:
                return None
        return values
    return None


def inspect_trainer_source(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "readable": False,
        "header_line": "",
        "app_version": "",
        "output_columns": [],
        "function_names": [],
        "class_names": [],
        "hardcoded_paths": [],
        "old_root_references": [],
        "birdbill_root_references": [],
        "helper_patterns": [],
        "schema_notes": [],
        "risk_notes": [],
    }

    if not path.exists():
        info["risk_notes"].append("trainer source path missing; pass --trainer-source if it lives elsewhere.")
        return info

    text, encoding = read_text_lossless(path)
    info["readable"] = True
    info["encoding_used"] = encoding
    lines = text.splitlines()
    info["header_line"] = clean_text(lines[0]) if lines else ""

    try:
        tree = ast.parse(text)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                info["function_names"].append(node.name)
            elif isinstance(node, ast.ClassDef):
                info["class_names"].append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "APP_VERSION" and isinstance(node.value, ast.Constant):
                            info["app_version"] = str(node.value.value)
                        elif target.id == "OUTPUT_COLUMNS":
                            values = parse_python_literal_list(node.value)
                            if values is not None:
                                info["output_columns"] = [str(v) for v in values]
    except Exception as exc:
        info["risk_notes"].append(f"AST parse failed: {type(exc).__name__}: {exc}")

    hardcoded_paths = sorted(set(re.findall(r"[A-Za-z]:\\[^\"'\n\r]+", text)))
    info["hardcoded_paths"] = [clean_text(p) for p in hardcoded_paths[:100]]
    info["old_root_references"] = [p for p in info["hardcoded_paths"] if "D:\\HBMR" in p]
    info["birdbill_root_references"] = [p for p in info["hardcoded_paths"] if "D:\\birdbill" in p]

    if "MMPPOSE_HELPER_CODE" in text or ("MMPose" in text and "subprocess.run" in text):
        info["helper_patterns"].append("external child/helper subprocess pattern present")
    if "candidate_path" in text and "image_path" in text:
        info["helper_patterns"].append("candidate_path/image_path import pattern present")
    if "premium" in text.lower() and "human" in text.lower():
        info["schema_notes"].append("trainer treats premium training rows as human-approved review output")
    if "gpt_accepted" in text or "GPT" in text:
        info["schema_notes"].append("assistant/model predictions are review hints, not automatically gold labels")
    if "D:\\HBMR" in text:
        info["risk_notes"].append("old-root D:\\HBMR references remain in trainer source and may need migration before Birdbill app promotion")

    return info


def make_child_script(path: Path) -> None:
    child = r'''# inspectDLCBilltipProjectChild.py | generated by inspectDLCBilltipProject.py v0.1 | Runs inside DLC environment
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
    return str(value).replace("\\ufeff", "").replace("ï»¿", "")


def safe_print(value) -> None:
    print(clean_text(value))


def safe_json_default(value):
    try:
        return str(value)
    except Exception:
        return repr(value)


def read_file_preview(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            return data.decode(encoding)[:max_chars]
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")[:max_chars]


def main() -> int:
    configure_stdio()

    config_path = Path(sys.argv[1])
    project_dir = Path(sys.argv[2])

    report = {
        "child_script": "inspectDLCBilltipProjectChild.py",
        "child_script_version": "generated-v0.1",
        "child_python_executable": sys.executable,
        "config_path": str(config_path),
        "project_dir": str(project_dir),
        "status": "FAIL",
        "deeplabcut_import": "NOT_RUN",
        "deeplabcut_version": "",
        "package_versions": {},
        "config_read": {},
        "function_signatures": {},
        "metadata_files": [],
        "metadata_previews": {},
        "errors": [],
    }

    safe_print("child_script = inspectDLCBilltipProjectChild.py")
    safe_print("child_script_version = generated-v0.1")
    safe_print(f"child_python_executable = {sys.executable}")
    safe_print(f"config_path = {config_path}")
    safe_print(f"project_dir = {project_dir}")

    try:
        for package_name in ["torch", "tensorflow", "numpy", "pandas", "yaml"]:
            try:
                module = __import__(package_name)
                report["package_versions"][package_name] = getattr(module, "__version__", "unknown")
            except Exception as exc:
                report["package_versions"][package_name] = f"IMPORT_FAIL: {type(exc).__name__}: {exc}"

        import deeplabcut
        report["deeplabcut_import"] = "PASS"
        report["deeplabcut_version"] = getattr(deeplabcut, "__version__", "unknown")
        safe_print("deeplabcut_import = PASS")
        safe_print(f"deeplabcut_version = {report['deeplabcut_version']}")

        from deeplabcut.utils import auxiliaryfunctions

        try:
            cfg = auxiliaryfunctions.read_config(str(config_path))
            config_keys = sorted(str(k) for k in cfg.keys())
            report["config_read"] = {
                "status": "PASS",
                "keys": config_keys,
                "has_Task": "Task" in cfg,
                "has_mojibake_Task": "ï»¿Task" in cfg,
                "Task": cfg.get("Task", ""),
                "mojibake_Task": cfg.get("ï»¿Task", ""),
                "bodyparts": cfg.get("bodyparts", []),
                "multianimalproject": cfg.get("multianimalproject", ""),
                "multianimalbodyparts": cfg.get("multianimalbodyparts", []),
                "uniquebodyparts": cfg.get("uniquebodyparts", []),
                "individuals": cfg.get("individuals", []),
                "project_path": cfg.get("project_path", ""),
                "TrainingFraction": cfg.get("TrainingFraction", []),
                "snapshotindex": cfg.get("snapshotindex", ""),
                "engine": cfg.get("engine", ""),
                "default_net_type": cfg.get("default_net_type", ""),
                "default_track_method": cfg.get("default_track_method", ""),
                "scorer": cfg.get("scorer", ""),
                "date": cfg.get("date", ""),
            }
            safe_print("dlc_read_config = PASS")
            safe_print("dlc_config_keys = " + ",".join(config_keys))
            safe_print("dlc_config_task = " + clean_text(report["config_read"].get("Task", "")))
            safe_print("dlc_config_mojibake_task = " + clean_text(report["config_read"].get("mojibake_Task", "")))
        except Exception as exc:
            report["config_read"] = {
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            safe_print("dlc_read_config = FAIL")
            safe_print(f"dlc_read_config_error = {type(exc).__name__}: {exc}")

        for func_name in [
            "analyze_time_lapse_frames",
            "analyze_videos",
            "create_labeled_video",
            "filterpredictions",
            "convertcsv2h5",
        ]:
            try:
                func = getattr(deeplabcut, func_name)
                sig = inspect.signature(func)
                report["function_signatures"][func_name] = {
                    "signature": str(sig),
                    "params": list(sig.parameters.keys()),
                }
                safe_print(f"{func_name}_signature = {sig}")
            except Exception as exc:
                report["function_signatures"][func_name] = {
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

        metadata_files = sorted(project_dir.rglob("metadata.yaml"), key=lambda p: str(p).lower()) if project_dir.exists() else []
        report["metadata_files"] = [str(p) for p in metadata_files]
        for p in metadata_files[:20]:
            report["metadata_previews"][str(p)] = read_file_preview(p, max_chars=3000)

        report["status"] = "PASS"
        safe_print("child_status = PASS")
        print("CHILD_REPORT_JSON_START")
        print(json.dumps(report, indent=2, ensure_ascii=False, default=safe_json_default))
        print("CHILD_REPORT_JSON_END")
        return 0

    except Exception as exc:
        report["status"] = "FAIL"
        report["errors"].append(
            {
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        safe_print("child_status = FAIL")
        safe_print(f"error_type = {type(exc).__name__}")
        safe_print(f"error = {exc}")
        traceback.print_exc()
        print("CHILD_REPORT_JSON_START")
        print(json.dumps(report, indent=2, ensure_ascii=False, default=safe_json_default))
        print("CHILD_REPORT_JSON_END")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(child, encoding="utf-8")


def extract_child_json(stdout: str) -> dict[str, Any]:
    start = "CHILD_REPORT_JSON_START"
    end = "CHILD_REPORT_JSON_END"
    if start not in stdout or end not in stdout:
        return {}
    body = stdout.split(start, 1)[1].split(end, 1)[0].strip()
    try:
        return json.loads(body)
    except Exception:
        return {"json_parse_error": "Could not parse child report JSON", "raw_preview": body[:2000]}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Birdbill Step 8 read-only DLC billtip project inspector")
    parser.add_argument("--project-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--dlc-project-dir", default=str(DEFAULT_DLC_PROJECT_DIR))
    parser.add_argument("--dlc-config", default=str(DEFAULT_DLC_CONFIG))
    parser.add_argument("--dlc-python", default=str(DEFAULT_DLC_PYTHON))
    parser.add_argument("--trainer-source", default=str(DEFAULT_TRAINER_SOURCE))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = build_arg_parser().parse_args(argv)

    started_at = utc_now()
    run_stamp = now_stamp()
    output_dir = Path(args.output_root) / f"inspect-dlc-billtip-project-{run_stamp}"
    child_script = output_dir / "inspectDLCBilltipProjectChild.py"
    child_stdout = output_dir / "dlc-child-stdout.txt"
    child_stderr = output_dir / "dlc-child-stderr.txt"
    report_json = output_dir / "inspect-dlc-billtip-project-report.json"
    report_txt = output_dir / "inspect-dlc-billtip-project-report.txt"
    file_inventory_csv = output_dir / "dlc-project-file-inventory.csv"
    status_path = output_dir / "status.txt"

    project_root = Path(args.project_root)
    dlc_project_dir = Path(args.dlc_project_dir)
    dlc_config = Path(args.dlc_config)
    dlc_python = Path(args.dlc_python)
    trainer_source = Path(args.trainer_source)

    output_dir.mkdir(parents=True, exist_ok=True)

    for line in [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"python_executable = {sys.executable}",
        f"project_root = {project_root}",
        f"dlc_project_dir = {dlc_project_dir}",
        f"dlc_config = {dlc_config}",
        f"dlc_python = {dlc_python}",
        f"trainer_source = {trainer_source}",
        f"output_dir = {output_dir}",
        "read_only = true",
        "inference_run = false",
        "database_mutation = false",
        "durable_evidence_written = false",
        "media_files_written = 0",
    ]:
        safe_print(line)

    status_lines = [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"python_executable = {sys.executable}",
        f"project_root = {project_root}",
        f"dlc_project_dir = {dlc_project_dir}",
        f"dlc_config = {dlc_config}",
        f"dlc_python = {dlc_python}",
        f"trainer_source = {trainer_source}",
        f"output_dir = {output_dir}",
        "read_only = true",
        "inference_run = false",
        "database_mutation = false",
        "durable_evidence_written = false",
        "media_files_written = 0",
    ]

    report: dict[str, Any] = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
        "component": COMPONENT_NAME,
        "started_at": started_at,
        "completed_at": "",
        "status": "FAIL",
        "read_only": True,
        "inference_run": False,
        "database_mutation": False,
        "durable_evidence_written": False,
        "media_files_written": 0,
        "paths": {
            "project_root": str(project_root),
            "dlc_project_dir": str(dlc_project_dir),
            "dlc_config": str(dlc_config),
            "dlc_python": str(dlc_python),
            "trainer_source": str(trainer_source),
            "output_dir": str(output_dir),
        },
        "preflight": {},
        "config_text_scan": {},
        "project_file_scan": {},
        "trainer_source_scan": {},
        "dlc_child_report": {},
        "risk_notes": [],
        "recommended_next_steps": [],
    }

    return_code = 1

    try:
        preflight = {
            "project_root_exists": project_root.exists(),
            "dlc_project_dir_exists": dlc_project_dir.exists(),
            "dlc_config_exists": dlc_config.exists(),
            "dlc_python_exists": dlc_python.exists(),
            "trainer_source_exists": trainer_source.exists(),
        }
        report["preflight"] = preflight
        for key, value in preflight.items():
            status_lines.append(f"{key} = {str(value).lower()}")

        report["config_text_scan"] = scan_config_text(dlc_config)
        report["project_file_scan"] = inspect_project_files(dlc_project_dir)
        report["trainer_source_scan"] = inspect_trainer_source(trainer_source)

        file_rows: list[dict[str, Any]] = []
        for category, paths in [
            ("metadata_yaml", report["project_file_scan"].get("metadata_yaml_files", [])),
            ("snapshot", report["project_file_scan"].get("snapshot_files", [])),
            ("pose_cfg", report["project_file_scan"].get("pose_cfg_files", [])),
            ("pytorch_config", report["project_file_scan"].get("pytorch_config_files", [])),
            ("video", report["project_file_scan"].get("video_files", [])),
        ]:
            for path_text in paths:
                p = Path(path_text)
                file_rows.append(
                    {
                        "category": category,
                        "path": path_text,
                        "exists": p.exists(),
                        "size_bytes": p.stat().st_size if p.exists() and p.is_file() else "",
                    }
                )
        if file_rows:
            write_csv(file_inventory_csv, file_rows)

        if report["config_text_scan"].get("has_bom_or_mojibake_task_key"):
            report["risk_notes"].append("Original config appears to contain a BOM/mojibake Task key; sanitized working config may be needed for DLC calls.")
        if report["config_text_scan"].get("project_path_text_value"):
            cfg_project = Path(str(report["config_text_scan"].get("project_path_text_value")))
            if cfg_project != dlc_project_dir:
                report["risk_notes"].append(
                    f"config project_path differs from supplied dlc_project_dir: config={cfg_project}; supplied={dlc_project_dir}"
                )
        if report["trainer_source_scan"].get("old_root_references"):
            report["risk_notes"].append("Trainer source contains D:\\HBMR old-root references that should be migrated or quarantined before app promotion.")
        report["risk_notes"].extend(report["project_file_scan"].get("risk_notes", []))
        report["risk_notes"].extend(report["trainer_source_scan"].get("risk_notes", []))

        make_child_script(child_script)

        if not dlc_python.exists():
            raise FileNotFoundError(f"DLC python missing: {dlc_python}")
        if not dlc_config.exists():
            raise FileNotFoundError(f"DLC config missing: {dlc_config}")

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        completed = subprocess.run(
            [str(dlc_python), str(child_script), str(dlc_config), str(dlc_project_dir)],
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
        report["dlc_child_exit_code"] = completed.returncode
        report["dlc_child_report"] = extract_child_json(completed.stdout)

        safe_print("----- dlc-child-stdout -----")
        safe_print(completed.stdout)
        safe_print("----- end dlc-child-stdout -----")
        safe_print("----- dlc-child-stderr -----")
        safe_print(completed.stderr)
        safe_print("----- end dlc-child-stderr -----")

        child_config_read = report.get("dlc_child_report", {}).get("config_read", {})
        if child_config_read.get("has_mojibake_Task") and not child_config_read.get("has_Task"):
            report["risk_notes"].append("DLC read_config sees mojibake Task key but no normal Task key.")
        if child_config_read.get("status") == "PASS":
            child_project_path = child_config_read.get("project_path", "")
            if child_project_path:
                try:
                    if Path(str(child_project_path)) != dlc_project_dir:
                        report["risk_notes"].append(
                            f"DLC config project_path does not match inspected project dir: {child_project_path}"
                        )
                except Exception:
                    pass

        sigs = report.get("dlc_child_report", {}).get("function_signatures", {})
        atl = sigs.get("analyze_time_lapse_frames", {})
        if atl and "params" in atl and "destfolder" not in atl.get("params", []):
            report["risk_notes"].append("Installed analyze_time_lapse_frames has no destfolder parameter; prediction files may be written beside input images.")

        report["recommended_next_steps"] = [
            "Do not write another inference wrapper until this report is reviewed.",
            "If config has mojibake Task key, fix original config deliberately or keep a controlled sanitized working-copy strategy.",
            "Use discovered TrainingFraction/shuffle/model metadata instead of hardcoding shuffle=1/trainingsetindex=0 where possible.",
            "Keep DLC config in its project-root context when invoking DLC; do not pass a debug-folder config copy to DLC inference.",
            "Decide whether Step 6 DLC output should map to labeled observation records, billtipTrainerGUI review schema, or both.",
        ]

        report["status"] = "PASS" if completed.returncode == 0 else "PARTIAL"
        status_lines.append(f"dlc_child_exit_code = {completed.returncode}")
        status_lines.append(f"risk_note_count = {len(report['risk_notes'])}")
        status_lines.append(f"status = {report['status']}")
        return_code = 0 if completed.returncode == 0 else 1

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

        readable: list[str] = []
        readable.append(f"{SCRIPT_NAME} {SCRIPT_VERSION} Step {REWRITE_STEP}")
        readable.append("=" * 72)
        readable.append(f"status = {report.get('status')}")
        readable.append(f"project_root = {project_root}")
        readable.append(f"dlc_project_dir = {dlc_project_dir}")
        readable.append(f"dlc_config = {dlc_config}")
        readable.append(f"dlc_python = {dlc_python}")
        readable.append(f"trainer_source = {trainer_source}")
        readable.append("")
        readable.append("PREFLIGHT")
        for key, value in report.get("preflight", {}).items():
            readable.append(f"- {key}: {value}")
        readable.append("")
        readable.append("CONFIG TEXT SCAN")
        cfg = report.get("config_text_scan", {})
        for key in [
            "encoding_used",
            "has_normal_task_key",
            "has_bom_or_mojibake_task_key",
            "task_key_line_preview",
            "project_path_text_value",
        ]:
            readable.append(f"- {key}: {cfg.get(key)}")
        readable.append("")
        readable.append("DLC CHILD CONFIG READ")
        child_cfg = report.get("dlc_child_report", {}).get("config_read", {})
        for key in [
            "status",
            "has_Task",
            "has_mojibake_Task",
            "Task",
            "mojibake_Task",
            "bodyparts",
            "TrainingFraction",
            "project_path",
            "engine",
            "default_net_type",
            "multianimalproject",
        ]:
            readable.append(f"- {key}: {child_cfg.get(key)}")
        readable.append("")
        readable.append("PROJECT FILE SCAN")
        pf = report.get("project_file_scan", {})
        for key in [
            "metadata_yaml_files",
            "snapshot_files",
            "pose_cfg_files",
            "pytorch_config_files",
        ]:
            value = pf.get(key, [])
            readable.append(f"- {key}: {len(value)}")
            for item in value[:10]:
                readable.append(f"  - {item}")
        readable.append("")
        readable.append("TRAINER SOURCE SCAN")
        tr = report.get("trainer_source_scan", {})
        readable.append(f"- exists: {tr.get('exists')}")
        readable.append(f"- header_line: {tr.get('header_line')}")
        readable.append(f"- app_version: {tr.get('app_version')}")
        readable.append(f"- output_columns_count: {len(tr.get('output_columns', []))}")
        readable.append(f"- old_root_references_count: {len(tr.get('old_root_references', []))}")
        for item in tr.get("old_root_references", [])[:10]:
            readable.append(f"  - {item}")
        readable.append("")
        readable.append("RISK NOTES")
        for note in report.get("risk_notes", []):
            readable.append(f"- {note}")
        readable.append("")
        readable.append("RECOMMENDED NEXT STEPS")
        for step in report.get("recommended_next_steps", []):
            readable.append(f"- {step}")
        readable.append("")
        readable.append("MUTATION / STORAGE")
        readable.append("read_only = true")
        readable.append("inference_run = false")
        readable.append("database_mutation = false")
        readable.append("durable_evidence_written = false")
        readable.append("media_files_written = 0")

        write_text(report_txt, readable)

        status_lines.extend(
            [
                f"report_json = {report_json}",
                f"report_txt = {report_txt}",
                f"file_inventory_csv = {file_inventory_csv}",
                f"child_stdout = {child_stdout}",
                f"child_stderr = {child_stderr}",
                "read_only = true",
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
            f"file_inventory_csv = {file_inventory_csv}",
            f"child_stdout = {child_stdout}",
            f"child_stderr = {child_stderr}",
            f"status_path = {status_path}",
            f"inspector_status = {report.get('status')}",
            f"risk_note_count = {len(report.get('risk_notes', []))}",
            "read_only = true",
            "inference_run = false",
            "database_mutation = false",
            "durable_evidence_written = false",
            "media_files_written = 0",
        ]:
            safe_print(line)

    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
