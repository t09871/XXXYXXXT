# smokeSmartFrameSamplerApp.py | v0.3 | 2026-07-07 PDT | Birdbill Step 7 smoke for promoted SmartFrameSampler app module
from __future__ import annotations

import csv
import importlib.util
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_NAME = "smokeSmartFrameSamplerApp.py"
SCRIPT_VERSION = "v0.3"
REWRITE_STEP = "7"
COMPONENT_NAME = "SmartFrameSampler app promotion smoke"

DEFAULT_ROOT = Path(r"D:\birdbill")
DEFAULT_SOURCE_VIDEO = DEFAULT_ROOT / "debug" / "20250704_174952_001-Percy-HBMR.mp4"
APP_MODULE_PATH = DEFAULT_ROOT / "app" / "SmartFrameSampler.py"
LEGACY_APP_MODULE_PATH = DEFAULT_ROOT / "app" / "smartFrameSampler.py"
DEBUG_OUTPUT_ROOT = DEFAULT_ROOT / "output" / "debug"

REQUIRED_RECORD_COLUMNS = {
    "frame_id",
    "sequence_id",
    "source_video",
    "source_media_context",
    "source_video_is_canonical",
    "source_video_available",
    "source_frame_index",
    "frame_time_seconds",
    "frame_path",
    "frame_materialized",
    "frame_cache_role",
    "purgeable",
    "sync_session_id",
    "synced_time_ms",
    "calibration_id",
    "feeder_zone_id",
}


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def load_app_module(module_path: Path):
    if not module_path.exists():
        raise FileNotFoundError(f"Promoted app module missing: {module_path}")
    spec = importlib.util.spec_from_file_location("birdbill_SmartFrameSampler", str(module_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create import spec for: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["birdbill_SmartFrameSampler"] = module
    spec.loader.exec_module(module)
    return module


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    run_stamp = stamp()
    smoke_output_dir = DEBUG_OUTPUT_ROOT / f"SmartFrameSampler-app-{run_stamp}"
    status_path = smoke_output_dir / "smokeSmartFrameSamplerApp-status.txt"
    audit_path = smoke_output_dir / "smokeSmartFrameSamplerApp-audit.json"

    print(f"script_name = {SCRIPT_NAME}")
    print(f"script_version = {SCRIPT_VERSION}")
    print(f"rewrite_step = {REWRITE_STEP}")
    print(f"component = {COMPONENT_NAME}")
    print(f"python_executable = {sys.executable}")
    print(f"project_root = {DEFAULT_ROOT}")
    print(f"app_module_path = {APP_MODULE_PATH}")
    print(f"legacy_app_module_path = {LEGACY_APP_MODULE_PATH}")
    print(f"source_video = {DEFAULT_SOURCE_VIDEO}")
    print(f"smoke_output_dir = {smoke_output_dir}")
    print("database_mutation = false")
    print("durable_evidence_written = false")

    legacy_path_exists = LEGACY_APP_MODULE_PATH.exists()
    status_lines = [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        f"python_executable = {sys.executable}",
        f"project_root = {DEFAULT_ROOT}",
        f"app_module_path = {APP_MODULE_PATH}",
        f"legacy_app_module_path = {LEGACY_APP_MODULE_PATH}",
        f"legacy_app_module_path_exists = {str(legacy_path_exists).lower()}",
        f"source_video = {DEFAULT_SOURCE_VIDEO}",
        f"smoke_output_dir = {smoke_output_dir}",
        "database_mutation = false",
        "durable_evidence_written = false",
    ]
    audit: dict[str, Any] = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
        "component": COMPONENT_NAME,
        "python_executable": sys.executable,
        "project_root": str(DEFAULT_ROOT),
        "app_module_path": str(APP_MODULE_PATH),
        "legacy_app_module_path": str(LEGACY_APP_MODULE_PATH),
        "legacy_app_module_path_exists": legacy_path_exists,
        "source_video": str(DEFAULT_SOURCE_VIDEO),
        "smoke_output_dir": str(smoke_output_dir),
        "database_mutation": False,
        "durable_evidence_written": False,
        "broad_media_export": False,
        "checks": {},
    }

    try:
        smoke_output_dir.mkdir(parents=True, exist_ok=True)
        if legacy_path_exists:
            warning = (
                "Old lowercase app file still exists. Canonical app file is "
                "D:\\birdbill\\app\\SmartFrameSampler.py. Remove/archive the old lowercase file "
                "after this smoke passes to avoid stale-file confusion."
            )
            print(f"warning = {warning}")
            status_lines.append(f"warning = {warning}")
            audit["warning"] = warning

        if not DEFAULT_ROOT.exists():
            raise FileNotFoundError(f"Project root missing: {DEFAULT_ROOT}")
        if not DEFAULT_SOURCE_VIDEO.exists():
            raise FileNotFoundError(f"Default smoke source video missing: {DEFAULT_SOURCE_VIDEO}")

        module = load_app_module(APP_MODULE_PATH)
        audit["checks"]["module_import"] = "PASS"

        expected_app_name = "SmartFrameSampler.py"
        expected_app_version = "v0.3"
        actual_script_name = getattr(module, "SCRIPT_NAME", "")
        actual_script_version = getattr(module, "SCRIPT_VERSION", "")
        if actual_script_name != expected_app_name:
            raise RuntimeError(f"App module SCRIPT_NAME mismatch: expected {expected_app_name}, got {actual_script_name}")
        if actual_script_version != expected_app_version:
            raise RuntimeError(f"App module SCRIPT_VERSION mismatch: expected {expected_app_version}, got {actual_script_version}")
        audit["checks"]["app_header_contract"] = "PASS"

        required_attrs = ["SamplerSettings", "run_smart_frame_sampler", "SCRIPT_VERSION", "REWRITE_STEP"]
        for attr in required_attrs:
            if not hasattr(module, attr):
                raise RuntimeError(f"Promoted module missing required attribute: {attr}")
        audit["checks"]["required_attributes"] = "PASS"

        settings = module.SamplerSettings(
            sample_every_seconds=2.0,
            max_frame_records=60,
            burst_offsets_seconds=(-0.12, 0.0, 0.12),
            preview_frame_limit=20,
            jpeg_quality=92,
            clear_output=False,
            source_media_context="debug_smoke",
        )
        manifest = module.run_smart_frame_sampler(
            source_video=DEFAULT_SOURCE_VIDEO,
            output_root=smoke_output_dir / "app-output",
            run_id=f"SmartFrameSampler-app-smoke-{run_stamp}",
            settings=settings,
            settings_path=None,
        )
        audit["app_manifest"] = manifest

        sampled_csv = Path(manifest["sampled_frames_csv"])
        manifest_path = Path(manifest["manifest_path"])
        ledger_path = Path(manifest["storage_ledger_path"])
        for output_path in [sampled_csv, manifest_path, ledger_path]:
            if not output_path.exists():
                raise FileNotFoundError(f"Expected output missing: {output_path}")
        audit["checks"]["expected_outputs_exist"] = "PASS"

        rows = read_csv_rows(sampled_csv)
        if not rows:
            raise RuntimeError("sampled-frames.csv has no rows")
        actual_columns = set(rows[0].keys())
        missing = sorted(REQUIRED_RECORD_COLUMNS - actual_columns)
        if missing:
            raise RuntimeError(f"sampled-frames.csv missing required columns: {missing}")
        if "crop_path" in actual_columns:
            raise RuntimeError("sampled-frames.csv unexpectedly contains crop_path; sampler should not create crop records")
        audit["checks"]["sampled_frame_schema"] = "PASS"

        if manifest.get("database_mutation") is not False:
            raise RuntimeError("Manifest did not report database_mutation=false")
        if manifest.get("durable_evidence_written") is not False:
            raise RuntimeError("Manifest did not report durable_evidence_written=false")
        if manifest.get("broad_media_export") is not False:
            raise RuntimeError("Manifest did not report broad_media_export=false")
        audit["checks"]["mutation_and_storage_flags"] = "PASS"

        media_files_written = int(manifest.get("media_files_written", -1))
        preview_limit = int(settings.preview_frame_limit)
        if media_files_written < 0 or media_files_written > preview_limit:
            raise RuntimeError(f"media_files_written out of bounds: {media_files_written}; preview limit was {preview_limit}")
        audit["checks"]["bounded_preview_frames"] = "PASS"

        status_lines.extend(
            [
                "status = PASS",
                f"app_script_name = {actual_script_name}",
                f"app_script_version = {actual_script_version}",
                f"app_rewrite_step = {getattr(module, 'REWRITE_STEP', '')}",
                f"app_output_dir = {manifest['output_dir']}",
                f"sampled_frames_csv = {sampled_csv}",
                f"frame_records_written = {manifest['frame_records_written']}",
                f"preview_frames_written = {manifest['preview_frames_written']}",
                f"media_files_written = {manifest['media_files_written']}",
                "database_mutation = false",
                "durable_evidence_written = false",
                "broad_media_export = false",
            ]
        )
        audit["status"] = "PASS"
        write_json(audit_path, audit)
        write_text(status_path, status_lines)

        print("status = PASS")
        print(f"app_script_name = {actual_script_name}")
        print(f"app_script_version = {actual_script_version}")
        print(f"app_output_dir = {manifest['output_dir']}")
        print(f"sampled_frames_csv = {sampled_csv}")
        print(f"frame_records_written = {manifest['frame_records_written']}")
        print(f"preview_frames_written = {manifest['preview_frames_written']}")
        print(f"status_path = {status_path}")
        print(f"audit_path = {audit_path}")
        return 0
    except Exception as exc:
        audit["status"] = "FAIL"
        audit["error_type"] = type(exc).__name__
        audit["error"] = str(exc)
        audit["traceback"] = traceback.format_exc()
        status_lines.extend(
            [
                "status = FAIL",
                f"error_type = {type(exc).__name__}",
                f"error = {exc}",
                "database_mutation = false",
                "durable_evidence_written = false",
            ]
        )
        try:
            write_json(audit_path, audit)
            write_text(status_path, status_lines)
        except Exception:
            pass
        print("status = FAIL")
        print(f"error_type = {type(exc).__name__}")
        print(f"error = {exc}")
        print(f"status_path = {status_path}")
        print(f"audit_path = {audit_path}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
