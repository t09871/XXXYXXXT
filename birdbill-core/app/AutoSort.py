# AutoSort.py | v0.2 | 2026-07-07 PDT | Birdbill promoted AutoSort read-only recipe-based Sandbox clustering stage
from __future__ import annotations

import argparse
import configparser
import csv
import itertools
import json
import html as html_lib
import math
import re
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCRIPT_NAME = "AutoSort.py"
SCRIPT_VERSION = "v0.2"
SCRIPT_PURPOSE = "Birdbill promoted AutoSort read-only recipe-based Sandbox clustering stage"

DINO_MODEL_NAME_DEFAULT = "facebook/dinov2-small"
DINO_MODEL_VERSION_LABEL = "dinov2-small-v0.1"
DINO_BACKEND_ROOT = "old_hbmr_visualid_dinosim_transformers_mean_last_hidden_state"
LIGHTGLUE_BACKEND_ROOT = "old_hbmr_lightgluetest_autosortgui_superpoint_lightglue"
LIGHTGLUE_FEATURES_DEFAULT = "superpoint"
LIGHTGLUE_MAX_KEYPOINTS_DEFAULT = 2048

# Rough diagnostic labels only; copied from old HBMR lightgluetest.py behavior.
# These are not canonical identity thresholds.
LIGHTGLUE_WEAK_MATCHES = 8
LIGHTGLUE_POSSIBLE_MATCHES = 20
LIGHTGLUE_STRONG_MATCHES = 45
LIGHTGLUE_WEAK_MEAN_SCORE = 0.15
LIGHTGLUE_POSSIBLE_MEAN_SCORE = 0.30
LIGHTGLUE_STRONG_MEAN_SCORE = 0.50

AUTOSORT_RECIPES = ("dino", "lightglue", "fusion", "metrics", "fusion-metrics")

# This is an evidence/ranking inspector only.
# It does not assign identities, allocate Bird##### names, mutate the DB, or write durable evidence.
# Temporal continuity is explicitly disabled as an identity signal.
# Same-frame / co-present birds can only create known-different relations when manifest evidence supports it.


# ---------------------------------------------------------------------------
# General utilities
# ---------------------------------------------------------------------------

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_key(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[\s\-]+", "_", value)
    value = re.sub(r"[^a-z0-9_]+", "", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value


def str_clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def as_float(value: Any) -> Optional[float]:
    text = str_clean(value)
    if not text:
        return None
    try:
        number = float(text)
    except Exception:
        return None
    if math.isfinite(number):
        return number
    return None


def csv_read_dicts(path: Path) -> Tuple[List[Dict[str, str]], List[str], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        original_headers = list(reader.fieldnames or [])
        normalized_headers = [normalize_key(h) for h in original_headers]
        rows: List[Dict[str, str]] = []
        for idx, raw_row in enumerate(reader, start=1):
            row: Dict[str, str] = {"__source_row_number": str(idx)}
            for original_header, normalized_header in zip(original_headers, normalized_headers):
                row[normalized_header] = str_clean(raw_row.get(original_header, ""))
            rows.append(row)
    return rows, original_headers, normalized_headers


def csv_write_dicts(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str_clean(row.get(key, "")) for key in fieldnames})


def write_text(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_path_under(child: Path, parent: Path) -> bool:
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
        return child_resolved == parent_resolved or parent_resolved in child_resolved.parents
    except Exception:
        try:
            child_text = str(child.absolute()).lower()
            parent_text = str(parent.absolute()).lower().rstrip("\\/")
            return child_text.startswith(parent_text)
        except Exception:
            return False


def clear_directory_safely(output_dir: Path, project_root: Path) -> None:
    output_dir = output_dir.resolve()
    project_root = project_root.resolve()

    if output_dir == project_root:
        raise RuntimeError(f"Refusing to clear project root: {output_dir}")
    if not is_path_under(output_dir, project_root):
        raise RuntimeError(f"Refusing to clear output outside project root: {output_dir}")

    if output_dir.exists():
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def compact_unique(values: Iterable[str], max_items: int = 12) -> str:
    seen: List[str] = []
    for value in values:
        text = str_clean(value)
        if not text:
            continue
        if text not in seen:
            seen.append(text)
        if len(seen) >= max_items:
            break
    return ";".join(seen)


def first_existing_key(row: Dict[str, str], keys: Sequence[str]) -> str:
    for key in keys:
        if str_clean(row.get(key, "")):
            return key
    return ""


def resolve_possible_path(raw_value: str, project_root: Path, manifest_dir: Path) -> Tuple[str, bool, str]:
    value = str_clean(raw_value)
    if not value:
        return "", False, "blank"

    path = Path(value)
    candidates: List[Tuple[Path, str]] = []

    if path.is_absolute():
        candidates.append((path, "absolute"))
    else:
        candidates.append((project_root / value, "relative_to_project_root"))
        candidates.append((manifest_dir / value, "relative_to_manifest_dir"))

    for candidate, source in candidates:
        try:
            if candidate.exists():
                return str(candidate), True, source
        except Exception:
            pass

    if candidates:
        candidate, source = candidates[0]
        return str(candidate), False, f"{source}_missing"
    return value, False, "unresolved_missing"


def normalize_metric_key(value: str) -> str:
    text = str_clean(value)
    if not text:
        return ""
    text = text.replace("/", "\\")
    text = re.sub(r"\\+", r"\\", text)
    return text.lower()


def vector_to_json(values: Sequence[float], precision: int = 8) -> str:
    return json.dumps([round(float(v), precision) for v in values], separators=(",", ":"))


# ---------------------------------------------------------------------------
# Manifest / metric column handling
# ---------------------------------------------------------------------------

ROW_ID_KEYS = [
    "autosort_row_id",
    "smart_crop_id",
    "smartcrop_id",
    "crop_id",
    "candidate_id",
    "detection_id",
    "observation_id",
    "row_id",
    "id",
]

IMAGE_PATH_KEYS = [
    "smart_crop_path",
    "smartcrop_path",
    "refined_crop_path",
    "anatomical_crop_path",
    "crop_path",
    "retained_crop_path",
    "raw_crop_path",
    "candidate_path",
    "image_path",
    "frame_crop_path",
    "output_crop_path",
]

RAW_CROP_PATH_KEYS = [
    "raw_crop_path",
    "crop_path",
    "candidate_path",
    "retained_crop_path",
    "image_path",
]

SOURCE_KEYS = [
    "source_video",
    "source_video_path",
    "video_path",
    "source_media",
    "source_media_path",
    "media_path",
    "source_path",
    "original_video",
    "video",
    "source_filename",
]

FRAME_KEYS = [
    "frame_path",
    "source_frame_path",
    "raw_frame_path",
    "frame_file",
    "frame_filename",
]

FRAME_INDEX_KEYS = [
    "frame_index",
    "frame_number",
    "frame_num",
    "frame",
    "source_frame_index",
    "source_frame_number",
]

TIMESTAMP_KEYS = [
    "timestamp",
    "timestamp_s",
    "time_s",
    "time_seconds",
    "t_seconds",
    "t_sec",
    "source_time_s",
]

ANIMAL_INDEX_KEYS = [
    "animal_index",
    "animal_id",
    "detection_index",
    "detection_number",
    "candidate_index",
    "crop_index",
]

BILL_STATE_KEYS = [
    "bill_length_state",
    "length_bill_state",
    "observation_state",
    "metric_state",
    "bill_state",
    "readiness_state",
]

BILL_PX_KEYS = [
    "bill_length_px",
    "length_bill_px",
    "bill_px",
]

BILL_MM_KEYS = [
    "bill_length_mm",
    "length_bill_mm",
    "bill_mm",
]

METRIC_JOIN_KEYS = [
    "autosort_row_id",
    "smart_crop_id",
    "smartcrop_id",
    "crop_id",
    "candidate_id",
    "detection_id",
    "observation_id",
    "image_path",
    "smart_crop_path",
    "crop_path",
    "raw_crop_path",
]


def make_row_id(row: Dict[str, str]) -> Tuple[str, str]:
    key = first_existing_key(row, ROW_ID_KEYS)
    if key:
        return str_clean(row[key]), key
    source_row = str_clean(row.get("__source_row_number", ""))
    return f"row-{source_row.zfill(6)}", "__source_row_number"


def detect_best_path(row: Dict[str, str], project_root: Path, manifest_dir: Path) -> Dict[str, str]:
    image_col = first_existing_key(row, IMAGE_PATH_KEYS)
    raw_image_value = str_clean(row.get(image_col, "")) if image_col else ""
    image_path, image_exists, image_source = resolve_possible_path(raw_image_value, project_root, manifest_dir)

    raw_col = first_existing_key(row, RAW_CROP_PATH_KEYS)
    raw_value = str_clean(row.get(raw_col, "")) if raw_col else ""
    raw_path, raw_exists, raw_source = resolve_possible_path(raw_value, project_root, manifest_dir)

    return {
        "image_path_column": image_col,
        "image_path_raw": raw_image_value,
        "image_path_resolved": image_path,
        "image_path_exists": "true" if image_exists else "false",
        "image_path_resolve_source": image_source,
        "raw_crop_path_column": raw_col,
        "raw_crop_path_raw": raw_value,
        "raw_crop_path_resolved": raw_path,
        "raw_crop_path_exists": "true" if raw_exists else "false",
        "raw_crop_path_resolve_source": raw_source,
    }


def make_source_key(row: Dict[str, str]) -> Tuple[str, str]:
    col = first_existing_key(row, SOURCE_KEYS)
    if col:
        return str_clean(row.get(col, "")), col

    image_col = first_existing_key(row, IMAGE_PATH_KEYS)
    image_value = str_clean(row.get(image_col, "")) if image_col else ""
    if image_value:
        parent = str(Path(image_value).parent)
        return parent, f"derived_parent_of_{image_col}"

    return "", ""


def make_frame_key(row: Dict[str, str], source_value: str) -> Tuple[str, str]:
    frame_col = first_existing_key(row, FRAME_KEYS)
    frame_value = str_clean(row.get(frame_col, "")) if frame_col else ""
    if frame_value:
        return frame_value, frame_col

    frame_index_col = first_existing_key(row, FRAME_INDEX_KEYS)
    frame_index_value = str_clean(row.get(frame_index_col, "")) if frame_index_col else ""
    if source_value and frame_index_value:
        return f"{source_value}::frame::{frame_index_value}", f"source+{frame_index_col}"

    timestamp_col = first_existing_key(row, TIMESTAMP_KEYS)
    timestamp_value = str_clean(row.get(timestamp_col, "")) if timestamp_col else ""
    if source_value and timestamp_value:
        return f"{source_value}::time::{timestamp_value}", f"source+{timestamp_col}"

    return "", ""


def make_animal_key(row: Dict[str, str]) -> Tuple[str, str]:
    col = first_existing_key(row, ANIMAL_INDEX_KEYS)
    if col:
        return str_clean(row.get(col, "")), col
    return "", ""


def build_metric_index(metric_rows: List[Dict[str, str]], metric_headers: Sequence[str]) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    candidate_keys = [key for key in METRIC_JOIN_KEYS if key in set(metric_headers)]
    index: Dict[str, Dict[str, str]] = {}

    for row in metric_rows:
        for key in candidate_keys:
            value = normalize_metric_key(row.get(key, ""))
            if value and value not in index:
                index[value] = row

    return index, candidate_keys


def find_metric_for_manifest_row(
    manifest_row: Dict[str, str],
    metric_index: Dict[str, Dict[str, str]],
    metric_join_columns: Sequence[str],
) -> Tuple[Optional[Dict[str, str]], str, str]:
    for key in metric_join_columns:
        value = normalize_metric_key(manifest_row.get(key, ""))
        if value and value in metric_index:
            return metric_index[value], key, value

    for key in METRIC_JOIN_KEYS:
        value = normalize_metric_key(manifest_row.get(key, ""))
        if value and value in metric_index:
            return metric_index[value], key, value

    return None, "", ""


def summarize_metric(metric_row: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not metric_row:
        return {
            "metric_joined": "false",
            "metric_bill_state": "",
            "metric_bill_length_px": "",
            "metric_bill_length_mm": "",
            "metric_aggregation_eligible": "",
            "metric_lower_bound_eligible": "",
        }

    state_col = first_existing_key(metric_row, BILL_STATE_KEYS)
    px_col = first_existing_key(metric_row, BILL_PX_KEYS)
    mm_col = first_existing_key(metric_row, BILL_MM_KEYS)

    aggregation = ""
    lower_bound = ""
    for key in ("aggregation_eligible", "is_aggregation_eligible", "full_length_px_ready", "full_bill_ready"):
        if str_clean(metric_row.get(key, "")):
            aggregation = str_clean(metric_row.get(key, ""))
            break
    for key in ("lower_bound_eligible", "is_lower_bound_eligible", "partial_length_lower_bound"):
        if str_clean(metric_row.get(key, "")):
            lower_bound = str_clean(metric_row.get(key, ""))
            break

    return {
        "metric_joined": "true",
        "metric_bill_state": str_clean(metric_row.get(state_col, "")) if state_col else "",
        "metric_bill_length_px": str_clean(metric_row.get(px_col, "")) if px_col else "",
        "metric_bill_length_mm": str_clean(metric_row.get(mm_col, "")) if mm_col else "",
        "metric_aggregation_eligible": aggregation,
        "metric_lower_bound_eligible": lower_bound,
    }


def metric_pair_summary(row_a: Dict[str, str], row_b: Dict[str, str]) -> str:
    state_a = row_a.get("metric_bill_state", "")
    state_b = row_b.get("metric_bill_state", "")
    px_a = as_float(row_a.get("metric_bill_length_px", ""))
    px_b = as_float(row_b.get("metric_bill_length_px", ""))
    joined_a = row_a.get("metric_joined", "") == "true"
    joined_b = row_b.get("metric_joined", "") == "true"

    if not joined_a or not joined_b:
        return "not_compared_missing_metric_join"
    if px_a is None or px_b is None:
        return "not_compared_missing_numeric_bill_px"
    diff = abs(px_a - px_b)
    return f"available_not_identity_decision_v0_7:{state_a}|{state_b}:bill_px_abs_diff={diff:.6f}"


def co_present_reason(row_a: Dict[str, str], row_b: Dict[str, str]) -> Tuple[bool, str]:
    frame_a = row_a.get("frame_key", "")
    frame_b = row_b.get("frame_key", "")
    if not frame_a or not frame_b or frame_a != frame_b:
        return False, ""

    animal_a = row_a.get("animal_key", "")
    animal_b = row_b.get("animal_key", "")
    if animal_a and animal_b and animal_a == animal_b:
        return False, "same_frame_same_animal_key"

    if animal_a and animal_b and animal_a != animal_b:
        return True, "same_frame_different_animal_key"

    return True, "same_frame_multiple_rows_animal_key_missing_or_partial"


def load_settings(settings_ini: Path) -> Dict[str, str]:
    result: Dict[str, str] = {
        "settings_exists": "true" if settings_ini.exists() else "false",
        "settings_read_method": "",
        "settings_sections": "",
        "settings_autosort_keys_seen": "",
        "settings_identity_keys_seen": "",
    }
    if not settings_ini.exists():
        return result

    parser = configparser.ConfigParser()
    try:
        parser.read(settings_ini, encoding="utf-8")
        result["settings_read_method"] = "configparser"
        result["settings_sections"] = ";".join(parser.sections())
        if parser.has_section("autosort"):
            result["settings_autosort_keys_seen"] = ";".join(parser.options("autosort"))
        if parser.has_section("identity"):
            result["settings_identity_keys_seen"] = ";".join(parser.options("identity"))
    except Exception as exc:
        result["settings_read_method"] = f"configparser_error:{type(exc).__name__}:{exc}"
    return result


def make_normalized_rows(
    manifest_rows: List[Dict[str, str]],
    project_root: Path,
    manifest_dir: Path,
    metric_index: Dict[str, Dict[str, str]],
    metric_join_columns: Sequence[str],
) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []

    for row in manifest_rows:
        row_id, row_id_source = make_row_id(row)
        path_info = detect_best_path(row, project_root, manifest_dir)
        source_value, source_col = make_source_key(row)
        frame_value, frame_col = make_frame_key(row, source_value)
        animal_value, animal_col = make_animal_key(row)
        metric_row, metric_join_column, metric_join_value = find_metric_for_manifest_row(row, metric_index, metric_join_columns)
        metric_info = summarize_metric(metric_row)

        normalized_row = {
            "autosort_row_id": row_id,
            "autosort_row_id_source": row_id_source,
            "source_row_number": row.get("__source_row_number", ""),
            "source_key": source_value,
            "source_key_column": source_col,
            "frame_key": frame_value,
            "frame_key_column": frame_col,
            "animal_key": animal_value,
            "animal_key_column": animal_col,
            "metric_join_column": metric_join_column,
            "metric_join_value": metric_join_value,
            "dino_embedding_status": "not_run",
            "dino_embedding_dim": "",
            "dino_model_name": "",
            "dino_model_version": "",
        }
        normalized_row.update(path_info)
        normalized_row.update(metric_info)
        normalized.append(normalized_row)

    return normalized


def column_presence_report(headers: Sequence[str]) -> Dict[str, str]:
    header_set = set(headers)
    return {
        "row_id_columns_seen": compact_unique([key for key in ROW_ID_KEYS if key in header_set]),
        "image_path_columns_seen": compact_unique([key for key in IMAGE_PATH_KEYS if key in header_set]),
        "source_columns_seen": compact_unique([key for key in SOURCE_KEYS if key in header_set]),
        "frame_columns_seen": compact_unique([key for key in FRAME_KEYS if key in header_set]),
        "frame_index_columns_seen": compact_unique([key for key in FRAME_INDEX_KEYS if key in header_set]),
        "timestamp_columns_seen": compact_unique([key for key in TIMESTAMP_KEYS if key in header_set]),
        "animal_columns_seen": compact_unique([key for key in ANIMAL_INDEX_KEYS if key in header_set]),
    }


# ---------------------------------------------------------------------------
# DINOv2 old-HBMR-rooted scoring
# ---------------------------------------------------------------------------

def cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> Optional[float]:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return None
    value = sum(float(a) * float(b) for a, b in zip(vec_a, vec_b))
    if not math.isfinite(value):
        return None
    return value


def choose_device(torch_module: Any, requested: str) -> str:
    requested_clean = str_clean(requested).lower()
    if requested_clean and requested_clean != "auto":
        return requested_clean
    try:
        if torch_module.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def probe_dino_imports() -> Tuple[Dict[str, str], Dict[str, Any]]:
    diagnostics: Dict[str, str] = {
        "dino_backend": DINO_BACKEND_ROOT,
        "dino_import_torch": "not_checked",
        "dino_import_pil": "not_checked",
        "dino_import_transformers": "not_checked",
        "dino_import_error_module": "",
        "dino_import_error_type": "",
        "dino_import_error_message": "",
    }
    modules: Dict[str, Any] = {}

    try:
        import torch  # type: ignore
        diagnostics["dino_import_torch"] = f"ok:{getattr(torch, '__version__', 'version_unknown')}"
        modules["torch"] = torch
    except Exception as exc:
        diagnostics["dino_import_torch"] = f"fail:{type(exc).__name__}:{exc}"
        diagnostics["dino_import_error_module"] = "torch"
        diagnostics["dino_import_error_type"] = type(exc).__name__
        diagnostics["dino_import_error_message"] = str(exc)
        return diagnostics, modules

    try:
        from PIL import Image  # type: ignore
        diagnostics["dino_import_pil"] = "ok"
        modules["Image"] = Image
    except Exception as exc:
        diagnostics["dino_import_pil"] = f"fail:{type(exc).__name__}:{exc}"
        diagnostics["dino_import_error_module"] = "PIL.Image"
        diagnostics["dino_import_error_type"] = type(exc).__name__
        diagnostics["dino_import_error_message"] = str(exc)
        return diagnostics, modules

    try:
        from transformers import AutoImageProcessor, AutoModel  # type: ignore
        diagnostics["dino_import_transformers"] = "ok"
        modules["AutoImageProcessor"] = AutoImageProcessor
        modules["AutoModel"] = AutoModel
    except Exception as exc:
        diagnostics["dino_import_transformers"] = f"fail:{type(exc).__name__}:{exc}"
        diagnostics["dino_import_error_module"] = "transformers"
        diagnostics["dino_import_error_type"] = type(exc).__name__
        diagnostics["dino_import_error_message"] = str(exc)
        return diagnostics, modules

    return diagnostics, modules


def load_dino_model(
    modules: Dict[str, Any],
    model_name: str,
    requested_device: str,
    local_files_only: bool,
) -> Tuple[Dict[str, str], Any, Any, str]:
    torch = modules["torch"]
    AutoImageProcessor = modules["AutoImageProcessor"]
    AutoModel = modules["AutoModel"]

    diagnostics: Dict[str, str] = {
        "dino_model_name": model_name,
        "dino_model_version": DINO_MODEL_VERSION_LABEL,
        "dino_model_load_status": "not_loaded",
        "dino_model_load_error_type": "",
        "dino_model_load_error_message": "",
        "dino_device": "",
        "dino_local_files_only": "true" if local_files_only else "false",
    }

    device = choose_device(torch, requested_device)
    diagnostics["dino_device"] = device

    try:
        if local_files_only:
            processor = AutoImageProcessor.from_pretrained(model_name, local_files_only=True)
            model = AutoModel.from_pretrained(model_name, local_files_only=True)
        else:
            # Matches the old HBMR visualid.py / dinosim.py behavior: no local-only restriction.
            processor = AutoImageProcessor.from_pretrained(model_name)
            model = AutoModel.from_pretrained(model_name)
        model.eval()
        model.to(device)
        diagnostics["dino_model_load_status"] = "loaded"
        return diagnostics, processor, model, device
    except Exception as exc:
        diagnostics["dino_model_load_status"] = "fail"
        diagnostics["dino_model_load_error_type"] = type(exc).__name__
        diagnostics["dino_model_load_error_message"] = str(exc)
        return diagnostics, None, None, device


def compute_one_dino_embedding_old_hbmr(
    image_path: Path,
    modules: Dict[str, Any],
    processor: Any,
    model: Any,
    device: str,
) -> List[float]:
    # Rooted in old HBMR visualid.py / dinosim.py:
    # Image.open(...).convert("RGB")
    # processor(images=image, return_tensors="pt")
    # outputs.last_hidden_state.mean(dim=1)
    # torch.nn.functional.normalize(..., p=2, dim=1)
    torch = modules["torch"]
    Image = modules["Image"]

    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    inputs = {key: value.to(device) for key, value in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        embedding = outputs.last_hidden_state.mean(dim=1)
        embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

    return [float(v) for v in embedding.squeeze(0).detach().cpu().tolist()]


def compute_dino_embeddings(
    rows: List[Dict[str, str]],
    model_name: str,
    requested_device: str,
    local_files_only: bool,
    max_images: int,
) -> Tuple[List[Dict[str, str]], Dict[str, List[float]], Dict[str, str]]:
    import_diagnostics, modules = probe_dino_imports()
    diagnostics: Dict[str, str] = dict(import_diagnostics)
    diagnostics.update({
        "dino_model_name": model_name,
        "dino_model_version": DINO_MODEL_VERSION_LABEL,
        "dino_model_load_status": "not_attempted",
        "dino_device": "",
        "dino_local_files_only": "true" if local_files_only else "false",
        "dino_eligible_image_rows": "0",
        "dino_max_images_applied": str(max_images),
        "dino_embedding_ready_count": "0",
        "dino_embedding_output_rows": "0",
    })

    embedding_rows: List[Dict[str, str]] = []
    embeddings: Dict[str, List[float]] = {}

    if diagnostics.get("dino_import_error_module"):
        for row in rows:
            row["dino_embedding_status"] = "not_run_dino_import_failed"
        diagnostics["dino_model_load_status"] = "not_attempted_import_failed"
        return embedding_rows, embeddings, diagnostics

    model_diagnostics, processor, model, device = load_dino_model(
        modules=modules,
        model_name=model_name,
        requested_device=requested_device,
        local_files_only=local_files_only,
    )
    diagnostics.update(model_diagnostics)

    if processor is None or model is None:
        for row in rows:
            row["dino_embedding_status"] = "not_run_dino_model_load_failed"
        return embedding_rows, embeddings, diagnostics

    eligible_rows = [row for row in rows if row.get("image_path_exists") == "true" and row.get("image_path_resolved")]
    if max_images > 0:
        eligible_rows = eligible_rows[:max_images]
    diagnostics["dino_eligible_image_rows"] = str(len(eligible_rows))

    for index, row in enumerate(eligible_rows, start=1):
        row_id = row["autosort_row_id"]
        image_path = Path(row.get("image_path_resolved", ""))
        try:
            vector = compute_one_dino_embedding_old_hbmr(
                image_path=image_path,
                modules=modules,
                processor=processor,
                model=model,
                device=device,
            )
            embeddings[row_id] = vector
            row["dino_embedding_status"] = "ready"
            row["dino_embedding_dim"] = str(len(vector))
            row["dino_model_name"] = model_name
            row["dino_model_version"] = DINO_MODEL_VERSION_LABEL
            embedding_rows.append({
                "autosort_row_id": row_id,
                "image_path_resolved": str(image_path),
                "dino_status": "ready",
                "dino_backend": DINO_BACKEND_ROOT,
                "dino_model_name": model_name,
                "dino_model_version": DINO_MODEL_VERSION_LABEL,
                "dino_embedding_dim": str(len(vector)),
                "dino_embedding_json": vector_to_json(vector),
            })
        except Exception as exc:
            row["dino_embedding_status"] = f"fail_embedding:{type(exc).__name__}:{exc}"
            embedding_rows.append({
                "autosort_row_id": row_id,
                "image_path_resolved": str(image_path),
                "dino_status": row["dino_embedding_status"],
                "dino_backend": DINO_BACKEND_ROOT,
                "dino_model_name": model_name,
                "dino_model_version": DINO_MODEL_VERSION_LABEL,
                "dino_embedding_dim": "",
                "dino_embedding_json": "",
            })

    for row in rows:
        if row.get("dino_embedding_status") == "not_run":
            if row.get("image_path_exists") != "true":
                row["dino_embedding_status"] = "not_run_image_path_missing"
            else:
                row["dino_embedding_status"] = "not_run_not_in_max_images_subset"

    diagnostics["dino_embedding_ready_count"] = str(len(embeddings))
    diagnostics["dino_embedding_output_rows"] = str(len(embedding_rows))
    return embedding_rows, embeddings, diagnostics


def dino_disabled_rows(rows: List[Dict[str, str]], reason: str) -> Tuple[List[Dict[str, str]], Dict[str, List[float]], Dict[str, str]]:
    for row in rows:
        row["dino_embedding_status"] = reason
    diagnostics = {
        "dino_backend": "none",
        "dino_model_name": "",
        "dino_model_version": "",
        "dino_import_torch": "not_checked",
        "dino_import_pil": "not_checked",
        "dino_import_transformers": "not_checked",
        "dino_import_error_module": "",
        "dino_import_error_type": "",
        "dino_import_error_message": "",
        "dino_model_load_status": reason,
        "dino_device": "",
        "dino_local_files_only": "",
        "dino_embedding_ready_count": "0",
        "dino_embedding_output_rows": "0",
    }
    return [], {}, diagnostics


# ---------------------------------------------------------------------------
# LightGlue verifier rooted in old HBMR lightgluetest.py / autosortGUI.py
# ---------------------------------------------------------------------------

def normalize_tensor_to_list(value: Any) -> List[Any]:
    if value is None:
        return []
    try:
        if hasattr(value, "detach"):
            value = value.detach().cpu()
        if hasattr(value, "tolist"):
            value = value.tolist()
    except Exception:
        return []
    if isinstance(value, list):
        return value
    return []


def flatten_float_values(value: Any) -> List[float]:
    values = normalize_tensor_to_list(value)
    flat: List[Any] = []
    for item in values:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    out: List[float] = []
    for item in flat:
        try:
            number = float(item)
            if math.isfinite(number):
                out.append(number)
        except Exception:
            pass
    return out


def lightglue_score_list_from_matches(matches01: Dict[str, Any], match_count: int) -> List[float]:
    for key in ("scores", "matching_scores", "match_scores", "confidence", "confidences"):
        if key in matches01:
            scores = flatten_float_values(matches01[key])
            if scores:
                return scores[:match_count] if match_count else scores
    return []


def lightglue_summarize_scores(scores: Sequence[float]) -> Dict[str, Optional[float]]:
    if not scores:
        return {"mean_score": None, "median_score": None, "min_score": None, "max_score": None}
    sorted_scores = sorted(float(s) for s in scores)
    n = len(sorted_scores)
    if n % 2:
        median = sorted_scores[n // 2]
    else:
        median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2.0
    return {
        "mean_score": sum(sorted_scores) / n,
        "median_score": median,
        "min_score": sorted_scores[0],
        "max_score": sorted_scores[-1],
    }


def lightglue_decision_label(match_count: int, mean_score: Optional[float]) -> str:
    if mean_score is None:
        if match_count >= LIGHTGLUE_STRONG_MATCHES:
            return "possible_local_match"
        if match_count >= LIGHTGLUE_POSSIBLE_MATCHES:
            return "weak_possible_local_match"
        return "weak_or_no_local_match"

    if match_count >= LIGHTGLUE_STRONG_MATCHES and mean_score >= LIGHTGLUE_STRONG_MEAN_SCORE:
        return "strong_local_match"
    if match_count >= LIGHTGLUE_POSSIBLE_MATCHES and mean_score >= LIGHTGLUE_POSSIBLE_MEAN_SCORE:
        return "possible_local_match"
    if match_count >= LIGHTGLUE_WEAK_MATCHES and mean_score >= LIGHTGLUE_WEAK_MEAN_SCORE:
        return "weak_possible_local_match"
    return "weak_or_no_local_match"


def lightglue_normalized_ranking_score(match_count: int, mean_score: Optional[float], keypoints_a: int, keypoints_b: int) -> float:
    score_value = 0.0 if mean_score is None else max(0.0, min(1.0, float(mean_score)))
    coverage = match_count / max(1.0, float(min(max(1, keypoints_a), max(1, keypoints_b))))
    return max(0.0, min(1.0, 0.70 * score_value + 0.30 * min(1.0, coverage * 6.0)))


def probe_lightglue_imports() -> Tuple[Dict[str, str], Dict[str, Any]]:
    diagnostics: Dict[str, str] = {
        "lightglue_backend": LIGHTGLUE_BACKEND_ROOT,
        "lightglue_import_torch": "not_checked",
        "lightglue_import_lightglue": "not_checked",
        "lightglue_import_utils": "not_checked",
        "lightglue_import_error_module": "",
        "lightglue_import_error_type": "",
        "lightglue_import_error_message": "",
    }
    modules: Dict[str, Any] = {}

    try:
        import torch  # type: ignore
        diagnostics["lightglue_import_torch"] = f"ok:{getattr(torch, '__version__', 'version_unknown')}"
        modules["torch"] = torch
    except Exception as exc:
        diagnostics["lightglue_import_torch"] = f"fail:{type(exc).__name__}:{exc}"
        diagnostics["lightglue_import_error_module"] = "torch"
        diagnostics["lightglue_import_error_type"] = type(exc).__name__
        diagnostics["lightglue_import_error_message"] = str(exc)
        return diagnostics, modules

    try:
        from lightglue import LightGlue, SuperPoint  # type: ignore
        diagnostics["lightglue_import_lightglue"] = "ok"
        modules["LightGlue"] = LightGlue
        modules["SuperPoint"] = SuperPoint
    except Exception as exc:
        diagnostics["lightglue_import_lightglue"] = f"fail:{type(exc).__name__}:{exc}"
        diagnostics["lightglue_import_error_module"] = "lightglue"
        diagnostics["lightglue_import_error_type"] = type(exc).__name__
        diagnostics["lightglue_import_error_message"] = str(exc)
        return diagnostics, modules

    try:
        from lightglue.utils import load_image, rbd  # type: ignore
        diagnostics["lightglue_import_utils"] = "ok"
        modules["load_image"] = load_image
        modules["rbd"] = rbd
    except Exception as exc:
        diagnostics["lightglue_import_utils"] = f"fail:{type(exc).__name__}:{exc}"
        diagnostics["lightglue_import_error_module"] = "lightglue.utils"
        diagnostics["lightglue_import_error_type"] = type(exc).__name__
        diagnostics["lightglue_import_error_message"] = str(exc)
        return diagnostics, modules

    return diagnostics, modules


class LightGluePairVerifier:
    def __init__(self, modules: Dict[str, Any], device: str, max_keypoints: int) -> None:
        self.torch = modules["torch"]
        self.LightGlue = modules["LightGlue"]
        self.SuperPoint = modules["SuperPoint"]
        self.load_image = modules["load_image"]
        self.rbd = modules["rbd"]
        self.device = device
        self.max_keypoints = max_keypoints
        self.extractor = self.SuperPoint(max_num_keypoints=max_keypoints).eval().to(device)
        self.matcher = self.LightGlue(features=LIGHTGLUE_FEATURES_DEFAULT).eval().to(device)
        self.feature_cache: Dict[str, Any] = {}

    def features(self, image_path: Path) -> Any:
        key = str(image_path.resolve())
        if key in self.feature_cache:
            return self.feature_cache[key]
        image = self.load_image(str(image_path)).to(self.device)
        with self.torch.no_grad():
            feats = self.extractor.extract(image)
        self.feature_cache[key] = feats
        return feats

    def score_pair(self, image_a: Path, image_b: Path) -> Dict[str, Any]:
        start = time.perf_counter()
        feats_a = self.features(image_a)
        feats_b = self.features(image_b)

        with self.torch.no_grad():
            matches01 = self.matcher({"image0": feats_a, "image1": feats_b})

        feats_a_rbd = self.rbd(feats_a)
        feats_b_rbd = self.rbd(feats_b)
        matches_rbd = self.rbd(matches01)

        matches_tensor = matches_rbd.get("matches", [])
        try:
            match_count = int(matches_tensor.shape[0])
        except Exception:
            match_count = len(normalize_tensor_to_list(matches_tensor))

        try:
            keypoints_a = int(feats_a_rbd["keypoints"].shape[0])
            keypoints_b = int(feats_b_rbd["keypoints"].shape[0])
        except Exception:
            keypoints_a = 0
            keypoints_b = 0

        scores = lightglue_score_list_from_matches(matches_rbd, match_count)
        score_summary = lightglue_summarize_scores(scores)
        mean_score = score_summary["mean_score"]
        decision = lightglue_decision_label(match_count, mean_score)
        ranking_score = lightglue_normalized_ranking_score(match_count, mean_score, keypoints_a, keypoints_b)

        return {
            "lightglue_status": "scored",
            "lightglue_backend": LIGHTGLUE_BACKEND_ROOT,
            "lightglue_features": LIGHTGLUE_FEATURES_DEFAULT,
            "lightglue_device": str(self.device),
            "lightglue_max_keypoints": str(self.max_keypoints),
            "lightglue_keypoints_a": str(keypoints_a),
            "lightglue_keypoints_b": str(keypoints_b),
            "lightglue_matches": str(match_count),
            "lightglue_scores_available": "true" if scores else "false",
            "lightglue_mean_score": "" if mean_score is None else f"{mean_score:.8f}",
            "lightglue_median_score": "" if score_summary["median_score"] is None else f"{score_summary['median_score']:.8f}",
            "lightglue_min_score": "" if score_summary["min_score"] is None else f"{score_summary['min_score']:.8f}",
            "lightglue_max_score": "" if score_summary["max_score"] is None else f"{score_summary['max_score']:.8f}",
            "lightglue_ranking_score": f"{ranking_score:.8f}",
            "lightglue_decision": decision,
            "lightglue_seconds": f"{(time.perf_counter() - start):.6f}",
            "lightglue_error_type": "",
            "lightglue_error_message": "",
        }


def select_lightglue_pair_indices(pair_rows: List[Dict[str, str]], max_pairs: int) -> List[int]:
    eligible: List[Tuple[int, float]] = []
    fallback: List[int] = []

    for idx, row in enumerate(pair_rows):
        if row.get("co_present_known_different_identity") == "true":
            continue
        image_ok = bool(row.get("row_a")) and bool(row.get("row_b"))
        if not image_ok:
            continue
        fallback.append(idx)
        dino_similarity = as_float(row.get("dino_similarity", ""))
        if dino_similarity is not None:
            eligible.append((idx, dino_similarity))

    if eligible:
        ordered = [idx for idx, _score in sorted(eligible, key=lambda item: item[1], reverse=True)]
    else:
        ordered = fallback

    if max_pairs > 0:
        return ordered[:max_pairs]
    return ordered


def run_lightglue_verifier(
    pair_rows: List[Dict[str, str]],
    row_by_id: Dict[str, Dict[str, str]],
    requested_device: str,
    max_keypoints: int,
    max_pairs: int,
) -> Dict[str, str]:
    diagnostics, modules = probe_lightglue_imports()
    diagnostics.update({
        "lightglue_mode": "run",
        "lightglue_device": "",
        "lightglue_model_load_status": "not_attempted",
        "lightglue_model_load_error_type": "",
        "lightglue_model_load_error_message": "",
        "lightglue_pairs_selected_count": "0",
        "lightglue_pair_scored_count": "0",
        "lightglue_pair_failed_count": "0",
        "lightglue_pair_skipped_count": "0",
        "lightglue_max_pairs": str(max_pairs),
        "lightglue_max_keypoints": str(max_keypoints),
    })

    for row in pair_rows:
        row["lightglue_status"] = "not_selected"

    if diagnostics.get("lightglue_import_error_module"):
        for row in pair_rows:
            row["lightglue_status"] = "not_run_lightglue_import_failed"
        diagnostics["lightglue_model_load_status"] = "not_attempted_import_failed"
        return diagnostics

    torch = modules["torch"]
    device = choose_device(torch, requested_device)
    diagnostics["lightglue_device"] = device

    try:
        verifier = LightGluePairVerifier(modules=modules, device=device, max_keypoints=max_keypoints)
        diagnostics["lightglue_model_load_status"] = "loaded"
    except Exception as exc:
        diagnostics["lightglue_model_load_status"] = "fail"
        diagnostics["lightglue_model_load_error_type"] = type(exc).__name__
        diagnostics["lightglue_model_load_error_message"] = str(exc)
        for row in pair_rows:
            row["lightglue_status"] = "not_run_lightglue_model_load_failed"
        return diagnostics

    selected_indices = select_lightglue_pair_indices(pair_rows, max_pairs=max_pairs)
    diagnostics["lightglue_pairs_selected_count"] = str(len(selected_indices))

    scored = 0
    failed = 0
    skipped = 0

    for idx in selected_indices:
        pair = pair_rows[idx]
        row_a = row_by_id.get(pair.get("row_a", ""))
        row_b = row_by_id.get(pair.get("row_b", ""))
        if not row_a or not row_b:
            pair["lightglue_status"] = "skipped_missing_row_lookup"
            skipped += 1
            continue

        path_a_text = row_a.get("image_path_resolved", "")
        path_b_text = row_b.get("image_path_resolved", "")
        path_a = Path(path_a_text)
        path_b = Path(path_b_text)
        if not path_a.exists() or not path_b.exists():
            pair["lightglue_status"] = "skipped_missing_image_path"
            pair["lightglue_error_message"] = f"{path_a_text} | {path_b_text}"
            skipped += 1
            continue

        try:
            result = verifier.score_pair(path_a, path_b)
            pair.update(result)
            scored += 1
        except Exception as exc:
            pair["lightglue_status"] = "fail_pair_scoring"
            pair["lightglue_error_type"] = type(exc).__name__
            pair["lightglue_error_message"] = str(exc)
            failed += 1

    diagnostics["lightglue_pair_scored_count"] = str(scored)
    diagnostics["lightglue_pair_failed_count"] = str(failed)
    diagnostics["lightglue_pair_skipped_count"] = str(skipped)
    return diagnostics


def lightglue_disabled_rows(pair_rows: List[Dict[str, str]], reason: str) -> Dict[str, str]:
    for row in pair_rows:
        row["lightglue_status"] = reason
    return {
        "lightglue_backend": "none",
        "lightglue_mode": reason,
        "lightglue_import_torch": "not_checked",
        "lightglue_import_lightglue": "not_checked",
        "lightglue_import_utils": "not_checked",
        "lightglue_import_error_module": "",
        "lightglue_import_error_type": "",
        "lightglue_import_error_message": "",
        "lightglue_model_load_status": reason,
        "lightglue_device": "",
        "lightglue_pairs_selected_count": "0",
        "lightglue_pair_scored_count": "0",
        "lightglue_pair_failed_count": "0",
        "lightglue_pair_skipped_count": "0",
        "lightglue_max_pairs": "0",
        "lightglue_max_keypoints": "",
    }


def lightglue_probe_only(requested_device: str, max_keypoints: int) -> Dict[str, str]:
    diagnostics, modules = probe_lightglue_imports()
    diagnostics.update({
        "lightglue_mode": "probe",
        "lightglue_device": "",
        "lightglue_model_load_status": "not_attempted",
        "lightglue_model_load_error_type": "",
        "lightglue_model_load_error_message": "",
        "lightglue_pairs_selected_count": "0",
        "lightglue_pair_scored_count": "0",
        "lightglue_pair_failed_count": "0",
        "lightglue_pair_skipped_count": "0",
        "lightglue_max_pairs": "0",
        "lightglue_max_keypoints": str(max_keypoints),
    })

    if diagnostics.get("lightglue_import_error_module"):
        diagnostics["lightglue_model_load_status"] = "not_attempted_import_failed"
        return diagnostics

    torch = modules["torch"]
    device = choose_device(torch, requested_device)
    diagnostics["lightglue_device"] = device

    try:
        _verifier = LightGluePairVerifier(modules=modules, device=device, max_keypoints=max_keypoints)
        diagnostics["lightglue_model_load_status"] = "loaded"
    except Exception as exc:
        diagnostics["lightglue_model_load_status"] = "fail"
        diagnostics["lightglue_model_load_error_type"] = type(exc).__name__
        diagnostics["lightglue_model_load_error_message"] = str(exc)

    return diagnostics


# ---------------------------------------------------------------------------
# Pairing / known-different relations
# ---------------------------------------------------------------------------

def make_pairs(
    normalized_rows: List[Dict[str, str]],
    embeddings: Dict[str, List[float]],
    max_pairs: int,
) -> Tuple[List[Dict[str, str]], bool]:
    pairs: List[Dict[str, str]] = []
    truncated = False

    for index, (row_a, row_b) in enumerate(itertools.combinations(normalized_rows, 2), start=1):
        if max_pairs > 0 and len(pairs) >= max_pairs:
            truncated = True
            break

        co_present, co_reason = co_present_reason(row_a, row_b)
        vector_a = embeddings.get(row_a["autosort_row_id"])
        vector_b = embeddings.get(row_b["autosort_row_id"])
        similarity = cosine_similarity(vector_a, vector_b) if vector_a is not None and vector_b is not None else None

        if similarity is None:
            dino_pair_status = "not_scored_missing_embedding"
            dino_similarity = ""
        else:
            dino_pair_status = "scored"
            dino_similarity = f"{similarity:.8f}"

        pairs.append({
            "pair_id": f"pair-{index:08d}",
            "row_a": row_a["autosort_row_id"],
            "row_b": row_b["autosort_row_id"],
            "source_a": row_a.get("source_key", ""),
            "source_b": row_b.get("source_key", ""),
            "same_source": "true" if row_a.get("source_key", "") and row_a.get("source_key", "") == row_b.get("source_key", "") else "false",
            "frame_key_a": row_a.get("frame_key", ""),
            "frame_key_b": row_b.get("frame_key", ""),
            "co_present_known_different_identity": "true" if co_present else "false",
            "co_present_reason": co_reason,
            "dino_status": dino_pair_status,
            "dino_backend": DINO_BACKEND_ROOT if dino_pair_status == "scored" else "",
            "dino_model_name": row_a.get("dino_model_name", "") or row_b.get("dino_model_name", ""),
            "dino_model_version": row_a.get("dino_model_version", "") or row_b.get("dino_model_version", ""),
            "dino_similarity": dino_similarity,
            "dino_similarity_rank_desc": "",
            "lightglue_status": "not_run_v0_7",
            "lightglue_backend": "",
            "lightglue_features": "",
            "lightglue_device": "",
            "lightglue_max_keypoints": "",
            "lightglue_keypoints_a": "",
            "lightglue_keypoints_b": "",
            "lightglue_matches": "",
            "lightglue_scores_available": "",
            "lightglue_mean_score": "",
            "lightglue_median_score": "",
            "lightglue_min_score": "",
            "lightglue_max_score": "",
            "lightglue_ranking_score": "",
            "lightglue_decision": "",
            "lightglue_seconds": "",
            "lightglue_error_type": "",
            "lightglue_error_message": "",
            "metric_pair_summary": metric_pair_summary(row_a, row_b),
            "autosort_identity_decision": "none_read_only_provisional_cluster_preview",
        })

    scored_pairs = [row for row in pairs if row.get("dino_status") == "scored" and as_float(row.get("dino_similarity")) is not None]
    scored_pairs_sorted = sorted(scored_pairs, key=lambda r: as_float(r.get("dino_similarity")) or -999.0, reverse=True)
    for rank, row in enumerate(scored_pairs_sorted, start=1):
        row["dino_similarity_rank_desc"] = str(rank)

    return pairs, truncated


def make_conflicts(pair_rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    conflicts: List[Dict[str, str]] = []
    for row in pair_rows:
        if row.get("co_present_known_different_identity", "") == "true":
            conflicts.append({
                "relation_id": row["pair_id"],
                "row_a": row["row_a"],
                "row_b": row["row_b"],
                "relation": "known_different_identity_by_copresence",
                "reason": row.get("co_present_reason", ""),
                "frame_key": row.get("frame_key_a", ""),
                "source_a": row.get("source_a", ""),
                "source_b": row.get("source_b", ""),
            })
    return conflicts



# ---------------------------------------------------------------------------
# Read-only recipe scoring / ranked pair evidence
# ---------------------------------------------------------------------------

def clamp01(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return max(0.0, min(1.0, float(value)))


def normalize_dino_similarity_for_rank(value: Any) -> Tuple[str, str]:
    raw = as_float(value)
    if raw is None:
        return "", "missing"
    normalized = clamp01(raw)
    if normalized is None:
        return "", "invalid"
    return f"{normalized:.8f}", "available_raw_cosine_clamped_0_1"


def normalize_lightglue_for_rank(pair: Dict[str, str]) -> Tuple[str, str]:
    ranking = as_float(pair.get("lightglue_ranking_score", ""))
    if ranking is not None:
        normalized = clamp01(ranking)
        if normalized is not None:
            return f"{normalized:.8f}", "available_lightglue_ranking_score"

    mean_score = as_float(pair.get("lightglue_mean_score", ""))
    if mean_score is not None:
        normalized = clamp01(mean_score)
        if normalized is not None:
            return f"{normalized:.8f}", "fallback_mean_score"

    matches = as_float(pair.get("lightglue_matches", ""))
    if matches is not None:
        normalized = clamp01(matches / 80.0)
        if normalized is not None:
            return f"{normalized:.8f}", "fallback_match_count_scaled"

    return "", "missing"


def metric_annotation_for_pair(pair: Dict[str, str]) -> Tuple[str, str, str]:
    summary = str_clean(pair.get("metric_pair_summary", ""))
    if not summary:
        return "not_available", "", "metrics_not_joined_or_no_summary"
    if "not_compared" in summary:
        return "not_compared", "", summary
    diff_match = re.search(r"bill_px_abs_diff=([0-9.]+)", summary)
    if not diff_match:
        return "available_unparsed", "", summary
    diff_px = as_float(diff_match.group(1))
    if diff_px is None:
        return "available_unparsed", "", summary

    if diff_px <= 10.0:
        label = "bill_px_very_close_provisional"
    elif diff_px <= 25.0:
        label = "bill_px_close_provisional"
    elif diff_px <= 60.0:
        label = "bill_px_moderate_difference_provisional"
    else:
        label = "bill_px_large_difference_provisional_review"
    return label, f"{diff_px:.6f}", summary


def metric_similarity_for_recipe(pair: Dict[str, str], tolerance_px: float) -> Tuple[str, str, str]:
    label, diff_px_text, note = metric_annotation_for_pair(pair)
    diff_px = as_float(diff_px_text)

    if diff_px is None:
        return "", "missing_or_unusable_metric_difference", note

    # Metrics are provisional. This score is only for explicit metrics recipes,
    # and only as image-space bill-length compatibility. It is not calibrated truth.
    safe_tolerance = max(0.001, float(tolerance_px))
    similarity = clamp01(1.0 - (diff_px / safe_tolerance))
    if similarity is None:
        return "", "invalid_metric_similarity", note

    if similarity <= 0.0:
        return "0.00000000", f"bill_px_diff_exceeds_tolerance_{safe_tolerance:.3f}", note
    return f"{similarity:.8f}", f"bill_px_similarity_tolerance_{safe_tolerance:.3f}", note


def metric_adjustment_for_fusion_metrics(metric_similarity: Optional[float]) -> Tuple[float, str]:
    if metric_similarity is None:
        return 0.0, "no_metric_adjustment_missing_or_partial"
    if metric_similarity >= 0.80:
        return 0.05, "small_metric_boost_compatible"
    if metric_similarity >= 0.50:
        return 0.02, "tiny_metric_boost_moderately_compatible"
    if metric_similarity <= 0.05:
        return -0.12, "metric_penalty_large_bill_px_difference"
    if metric_similarity <= 0.25:
        return -0.06, "metric_penalty_low_bill_px_similarity"
    return 0.0, "no_metric_adjustment_ambiguous"


def recipe_score_for_pair(pair: Dict[str, str], recipe: str, metric_tolerance_px: float) -> Tuple[Optional[float], str, Dict[str, str]]:
    recipe_clean = str_clean(recipe).lower()
    dino_norm_text, dino_norm_source = normalize_dino_similarity_for_rank(pair.get("dino_similarity", ""))
    lightglue_norm_text, lightglue_norm_source = normalize_lightglue_for_rank(pair)
    metric_label, metric_diff_px, metric_note = metric_annotation_for_pair(pair)
    metric_norm_text, metric_norm_source, metric_recipe_note = metric_similarity_for_recipe(pair, metric_tolerance_px)

    dino_norm = as_float(dino_norm_text)
    lightglue_norm = as_float(lightglue_norm_text)
    metric_norm = as_float(metric_norm_text)

    evidence_fields = {
        "fusion_dino_normalized": dino_norm_text,
        "fusion_dino_source": dino_norm_source,
        "fusion_lightglue_normalized": lightglue_norm_text,
        "fusion_lightglue_source": lightglue_norm_source,
        "fusion_metric_normalized": metric_norm_text,
        "fusion_metric_source": metric_norm_source,
        "fusion_metric_annotation": metric_label,
        "fusion_metric_bill_px_abs_diff": metric_diff_px,
        "fusion_metric_note": metric_note,
        "recipe_metric_note": metric_recipe_note,
    }

    if pair.get("co_present_known_different_identity", "") == "true":
        return None, "blocked_by_known_different_copresence", evidence_fields

    if recipe_clean == "dino":
        if dino_norm is None:
            return None, "recipe_dino_missing_dino_score", evidence_fields
        return dino_norm, "recipe_dino_only", evidence_fields

    if recipe_clean == "lightglue":
        if lightglue_norm is None:
            return None, "recipe_lightglue_missing_lightglue_score", evidence_fields
        return lightglue_norm, "recipe_lightglue_only", evidence_fields

    if recipe_clean == "metrics":
        if metric_norm is None:
            return None, "recipe_metrics_missing_comparable_bill_px", evidence_fields
        return metric_norm, "recipe_metrics_bill_px_similarity_only_provisional", evidence_fields

    if recipe_clean == "fusion-metrics":
        base_score: Optional[float] = None
        base_source = ""
        if lightglue_norm is not None and dino_norm is not None:
            base_score = 0.70 * lightglue_norm + 0.30 * dino_norm
            base_source = "base_0_70_lightglue_0_30_dino"
        elif lightglue_norm is not None:
            base_score = lightglue_norm
            base_source = "base_lightglue_only"
        elif dino_norm is not None:
            base_score = dino_norm
            base_source = "base_dino_only"

        if base_score is None:
            if metric_norm is None:
                return None, "recipe_fusion_metrics_missing_all_scores", evidence_fields
            return metric_norm, "recipe_fusion_metrics_metric_only_fallback_provisional", evidence_fields

        adjustment, adjustment_reason = metric_adjustment_for_fusion_metrics(metric_norm)
        adjusted = clamp01(base_score + adjustment)
        if adjusted is None:
            return None, "recipe_fusion_metrics_invalid_adjusted_score", evidence_fields
        return adjusted, f"recipe_fusion_metrics:{base_source}:{adjustment_reason}", evidence_fields

    # Default fusion recipe.
    if lightglue_norm is not None and dino_norm is not None:
        return 0.70 * lightglue_norm + 0.30 * dino_norm, "recipe_fusion_weighted_0_70_lightglue_0_30_dino", evidence_fields
    if lightglue_norm is not None:
        return lightglue_norm, "recipe_fusion_lightglue_only", evidence_fields
    if dino_norm is not None:
        return dino_norm, "recipe_fusion_dino_only", evidence_fields
    return None, "recipe_fusion_missing_dino_and_lightglue", evidence_fields


def fusion_review_bucket(score: Optional[float], pair: Dict[str, str], recipe: str) -> str:
    if pair.get("co_present_known_different_identity", "") == "true":
        return "blocked_known_different_copresence"
    if score is None:
        return "unranked_missing_recipe_inputs"
    if recipe == "metrics":
        if score >= 0.80:
            return "metrics_review_top_candidate"
        if score >= 0.50:
            return "metrics_review_candidate"
        if score > 0.0:
            return "metrics_review_weak_candidate"
        return "metrics_low_priority_candidate"
    if score >= 0.80:
        return "review_top_candidate"
    if score >= 0.65:
        return "review_candidate"
    if score >= 0.50:
        return "review_weak_candidate"
    return "low_priority_candidate"


def apply_pair_fusion(pair_rows: List[Dict[str, str]], recipe: str, metric_tolerance_px: float) -> Dict[str, str]:
    ranked_candidates: List[Dict[str, str]] = []
    recipe_clean = str_clean(recipe).lower()
    if recipe_clean not in AUTOSORT_RECIPES:
        recipe_clean = "fusion"

    for pair in pair_rows:
        recipe_score, recipe_source, evidence_fields = recipe_score_for_pair(pair, recipe_clean, metric_tolerance_px)
        pair.update(evidence_fields)
        pair["autosort_recipe"] = recipe_clean
        pair["metric_bill_px_tolerance"] = f"{float(metric_tolerance_px):.6f}"
        pair["fusion_score"] = "" if recipe_score is None else f"{recipe_score:.8f}"
        pair["fusion_source"] = recipe_source
        pair["fusion_rank_desc"] = ""
        pair["fusion_review_bucket"] = fusion_review_bucket(recipe_score, pair, recipe_clean)
        pair["fusion_identity_decision"] = "none_read_only_recipe_ranked_evidence"

        if recipe_score is not None:
            ranked_candidates.append(pair)

    ranked_candidates_sorted = sorted(ranked_candidates, key=lambda row: as_float(row.get("fusion_score")) or -999.0, reverse=True)
    for rank, pair in enumerate(ranked_candidates_sorted, start=1):
        pair["fusion_rank_desc"] = str(rank)

    top_score = ""
    if ranked_candidates_sorted:
        top_score = str_clean(ranked_candidates_sorted[0].get("fusion_score", ""))

    bucket_counts: Dict[str, int] = {}
    for pair in pair_rows:
        bucket = str_clean(pair.get("fusion_review_bucket", ""))
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    metric_score_available_count = sum(1 for pair in pair_rows if str_clean(pair.get("fusion_metric_normalized", "")))
    metric_positive_count = sum(1 for pair in pair_rows if (as_float(pair.get("fusion_metric_normalized", "")) or 0.0) > 0.0)

    return {
        "autosort_recipe": recipe_clean,
        "metric_bill_px_tolerance": f"{float(metric_tolerance_px):.6f}",
        "fusion_ranked_pair_count": str(len(ranked_candidates_sorted)),
        "fusion_top_score": top_score,
        "fusion_bucket_counts": ";".join(f"{key}:{bucket_counts[key]}" for key in sorted(bucket_counts)),
        "fusion_identity_assignment": "none_read_only_recipe_ranked_evidence",
        "fusion_metric_role": "explicit_recipe_or_adjustment_only_provisional_not_hard_identity_gate",
        "fusion_metric_score_available_count": str(metric_score_available_count),
        "fusion_metric_positive_count": str(metric_positive_count),
        "fusion_temporal_continuity_identity_signal": "disabled",
    }


def sorted_ranked_pairs(pair_rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    def sort_key(row: Dict[str, str]) -> Tuple[int, float, str]:
        score = as_float(row.get("fusion_score", ""))
        if score is None:
            return (1, 0.0, row.get("pair_id", ""))
        return (0, -score, row.get("pair_id", ""))
    return sorted([dict(row) for row in pair_rows], key=sort_key)


# ---------------------------------------------------------------------------
# Read-only provisional clustering and HTML preview
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent: Dict[str, str] = {item: item for item in items}

    def find(self, item: str) -> str:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def members_for_root(self, root: str) -> List[str]:
        return sorted([item for item in self.parent if self.find(item) == root])

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        # Deterministic root.
        if root_b < root_a:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a


def pair_key(a: str, b: str) -> Tuple[str, str]:
    return tuple(sorted((str_clean(a), str_clean(b))))  # type: ignore[return-value]


def has_known_different_conflict(members: Sequence[str], known_different: set[Tuple[str, str]]) -> bool:
    member_list = list(members)
    for left, right in itertools.combinations(member_list, 2):
        if pair_key(left, right) in known_different:
            return True
    return False


def cluster_edge_reason(pair: Dict[str, str], threshold: float) -> Tuple[bool, str]:
    if pair.get("co_present_known_different_identity", "") == "true":
        return False, "blocked_known_different_copresence"
    score = as_float(pair.get("fusion_score", ""))
    if score is None:
        return False, "not_used_missing_fusion_score"
    if score < threshold:
        return False, f"not_used_below_cluster_threshold_{threshold:.3f}"
    bucket = str_clean(pair.get("fusion_review_bucket", ""))
    if bucket in {"low_priority_candidate", "unranked_missing_fusion_inputs", "blocked_known_different_copresence"}:
        return False, f"not_used_bucket_{bucket}"
    return True, "eligible_fusion_edge"


def build_provisional_clusters(
    normalized_rows: List[Dict[str, str]],
    pair_rows: List[Dict[str, str]],
    cluster_threshold: float,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], Dict[str, str]]:
    row_ids = [row["autosort_row_id"] for row in normalized_rows]
    uf = UnionFind(row_ids)
    known_different: set[Tuple[str, str]] = set()

    for pair in pair_rows:
        pair["cluster_edge_decision"] = "not_evaluated"
        pair["cluster_edge_reason"] = ""
        if pair.get("co_present_known_different_identity", "") == "true":
            known_different.add(pair_key(pair.get("row_a", ""), pair.get("row_b", "")))

    candidate_pairs = sorted(
        pair_rows,
        key=lambda row: as_float(row.get("fusion_score", "")) if as_float(row.get("fusion_score", "")) is not None else -999.0,
        reverse=True,
    )

    accepted_edges = 0
    skipped_edges = 0
    blocked_conflicts = 0

    for pair in candidate_pairs:
        row_a = str_clean(pair.get("row_a", ""))
        row_b = str_clean(pair.get("row_b", ""))
        if not row_a or not row_b or row_a not in uf.parent or row_b not in uf.parent:
            pair["cluster_edge_decision"] = "not_used"
            pair["cluster_edge_reason"] = "missing_row_lookup"
            skipped_edges += 1
            continue

        eligible, reason = cluster_edge_reason(pair, cluster_threshold)
        if not eligible:
            pair["cluster_edge_decision"] = "not_used"
            pair["cluster_edge_reason"] = reason
            skipped_edges += 1
            continue

        merged_members = sorted(set(uf.members_for_root(uf.find(row_a))) | set(uf.members_for_root(uf.find(row_b))))
        if has_known_different_conflict(merged_members, known_different):
            pair["cluster_edge_decision"] = "blocked"
            pair["cluster_edge_reason"] = "blocked_would_merge_known_different_members"
            blocked_conflicts += 1
            continue

        if uf.find(row_a) == uf.find(row_b):
            pair["cluster_edge_decision"] = "already_connected"
            pair["cluster_edge_reason"] = "same_existing_cluster"
            continue

        uf.union(row_a, row_b)
        pair["cluster_edge_decision"] = "used"
        pair["cluster_edge_reason"] = reason
        accepted_edges += 1

    root_to_members: Dict[str, List[str]] = {}
    for row_id in row_ids:
        root = uf.find(row_id)
        root_to_members.setdefault(root, []).append(row_id)

    row_by_id = {row["autosort_row_id"]: row for row in normalized_rows}
    cluster_records: List[Dict[str, str]] = []
    cluster_summaries: List[Dict[str, str]] = []

    def cluster_sort_key(item: Tuple[str, List[str]]) -> Tuple[int, str]:
        root, members = item
        return (-len(members), min(members) if members else root)

    for cluster_index, (_root, members) in enumerate(sorted(root_to_members.items(), key=cluster_sort_key), start=1):
        label = f"AutoSortCluster{cluster_index:05d}"
        member_set = set(members)
        internal_pairs = [
            pair for pair in pair_rows
            if pair.get("row_a") in member_set and pair.get("row_b") in member_set
        ]
        used_edges = [pair for pair in internal_pairs if pair.get("cluster_edge_decision") in {"used", "already_connected"}]
        best_pair = None
        best_score = -999.0
        for pair in internal_pairs:
            score = as_float(pair.get("fusion_score", ""))
            if score is not None and score > best_score:
                best_pair = pair
                best_score = score

        cluster_status = "singleton_review_candidate" if len(members) == 1 else "multirow_review_candidate"
        best_score_text = "" if best_pair is None or best_score == -999.0 else f"{best_score:.8f}"
        best_pair_id = "" if best_pair is None else str_clean(best_pair.get("pair_id", ""))

        cluster_summaries.append({
            "provisional_cluster_label": label,
            "cluster_status": cluster_status,
            "cluster_size": str(len(members)),
            "member_rows": ";".join(members),
            "used_edge_count": str(len(used_edges)),
            "internal_pair_count": str(len(internal_pairs)),
            "best_internal_pair_id": best_pair_id,
            "best_internal_fusion_score": best_score_text,
            "identity_assignment": "none_read_only_provisional_cluster",
            "autoname_commit": "false",
            "db_mutation": "false",
        })

        for member in members:
            source_row = row_by_id.get(member, {})
            cluster_records.append({
                "provisional_cluster_label": label,
                "cluster_status": cluster_status,
                "cluster_size": str(len(members)),
                "autosort_row_id": member,
                "source_key": source_row.get("source_key", ""),
                "frame_key": source_row.get("frame_key", ""),
                "animal_key": source_row.get("animal_key", ""),
                "image_path_resolved": source_row.get("image_path_resolved", ""),
                "image_path_exists": source_row.get("image_path_exists", ""),
                "metric_bill_state": source_row.get("metric_bill_state", ""),
                "metric_bill_length_px": source_row.get("metric_bill_length_px", ""),
                "metric_bill_length_mm": source_row.get("metric_bill_length_mm", ""),
                "dino_embedding_status": source_row.get("dino_embedding_status", ""),
                "best_internal_pair_id": best_pair_id,
                "best_internal_fusion_score": best_score_text,
                "identity_assignment": "none_read_only_provisional_cluster",
                "autoname_commit": "false",
                "db_mutation": "false",
            })

    multirow_clusters = sum(1 for row in cluster_summaries if int(row.get("cluster_size", "0") or "0") > 1)
    singleton_clusters = len(cluster_summaries) - multirow_clusters
    largest_cluster_size = 0
    if cluster_summaries:
        largest_cluster_size = max(int(row.get("cluster_size", "0") or "0") for row in cluster_summaries)

    diagnostics = {
        "cluster_mode": "read_only_provisional_review_clusters",
        "cluster_threshold": f"{cluster_threshold:.6f}",
        "cluster_input_row_count": str(len(normalized_rows)),
        "cluster_pair_count": str(len(pair_rows)),
        "cluster_known_different_relation_count": str(len(known_different)),
        "cluster_edge_accepted_count": str(accepted_edges),
        "cluster_edge_skipped_count": str(skipped_edges),
        "cluster_edge_blocked_conflict_count": str(blocked_conflicts),
        "provisional_cluster_count": str(len(cluster_summaries)),
        "provisional_multirow_cluster_count": str(multirow_clusters),
        "provisional_singleton_cluster_count": str(singleton_clusters),
        "provisional_largest_cluster_size": str(largest_cluster_size),
        "cluster_identity_assignment": "none_read_only_provisional_cluster",
        "cluster_autoname_commit": "false",
        "cluster_db_mutation": "false",
    }

    return cluster_records, cluster_summaries, diagnostics


def local_path_to_file_uri(path_text: str) -> str:
    text = str_clean(path_text)
    if not text:
        return ""
    try:
        path = Path(text)
        if path.exists():
            return path.resolve().as_uri()
    except Exception:
        pass

    # Windows absolute paths when rendered by local browser.
    if re.match(r"^[A-Za-z]:[\\/]", text):
        uri = text.replace("\\", "/")
        uri = "/" + uri
        return "file://" + uri.replace(" ", "%20")
    return text.replace("\\", "/")


def esc(value: Any) -> str:
    return html_lib.escape(str_clean(value), quote=True)


def make_cluster_preview_html(
    path: Path,
    cluster_summaries: Sequence[Dict[str, str]],
    cluster_records: Sequence[Dict[str, str]],
    ranked_pair_rows: Sequence[Dict[str, str]],
    diagnostics: Dict[str, str],
    script_version: str,
) -> None:
    records_by_cluster: Dict[str, List[Dict[str, str]]] = {}
    for record in cluster_records:
        records_by_cluster.setdefault(record["provisional_cluster_label"], []).append(record)

    top_pairs = [row for row in ranked_pair_rows if str_clean(row.get("fusion_rank_desc", ""))]
    top_pairs = sorted(top_pairs, key=lambda row: int(row.get("fusion_rank_desc", "999999") or "999999"))[:20]

    lines: List[str] = []
    lines.append("<!doctype html>")
    lines.append("<html><head><meta charset='utf-8'>")
    lines.append(f"<title>Birdbill AutoSort Cluster Preview {esc(script_version)}</title>")
    lines.append("""
<style>
body { font-family: Arial, sans-serif; margin: 24px; background: #f7f7f7; color: #222; }
h1, h2, h3 { margin-bottom: 0.25rem; }
.small { color: #555; font-size: 0.9rem; }
.cluster { background: white; border: 1px solid #ccc; border-radius: 8px; margin: 18px 0; padding: 14px; }
.member-grid { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; }
.member { width: 220px; background: #fafafa; border: 1px solid #ddd; border-radius: 6px; padding: 8px; }
.member img { max-width: 200px; max-height: 180px; display: block; margin-bottom: 6px; border: 1px solid #ccc; }
table { border-collapse: collapse; width: 100%; background: white; margin-top: 8px; }
th, td { border: 1px solid #ccc; padding: 5px 7px; font-size: 0.9rem; vertical-align: top; }
th { background: #eee; }
.badge { display: inline-block; padding: 2px 6px; border-radius: 999px; background: #e8e8e8; margin-left: 6px; font-size: 0.85rem; }
.warn { color: #7a4b00; }
</style>
""")
    lines.append("</head><body>")
    lines.append(f"<h1>Birdbill AutoSort Cluster Preview <span class='badge'>{esc(script_version)}</span></h1>")
    lines.append("<p class='warn'><b>Read-only preview:</b> no DB mutation, no Autoname commit, no durable identity assignment. These are review candidates only.</p>")

    lines.append("<h2>Run Summary</h2>")
    lines.append("<table>")
    for key in sorted(diagnostics):
        lines.append(f"<tr><th>{esc(key)}</th><td>{esc(diagnostics[key])}</td></tr>")
    lines.append("</table>")

    lines.append("<h2>Provisional Clusters</h2>")
    for summary in cluster_summaries:
        label = summary["provisional_cluster_label"]
        records = records_by_cluster.get(label, [])
        lines.append("<div class='cluster'>")
        lines.append(
            f"<h3>{esc(label)} <span class='badge'>{esc(summary.get('cluster_status', ''))}</span> "
            f"<span class='badge'>size {esc(summary.get('cluster_size', ''))}</span></h3>"
        )
        lines.append(
            f"<div class='small'>best pair: {esc(summary.get('best_internal_pair_id', ''))} | "
            f"best fusion: {esc(summary.get('best_internal_fusion_score', ''))} | "
            f"used edges: {esc(summary.get('used_edge_count', ''))}</div>"
        )
        lines.append("<div class='member-grid'>")
        for record in records:
            img_uri = local_path_to_file_uri(record.get("image_path_resolved", ""))
            lines.append("<div class='member'>")
            if img_uri:
                lines.append(f"<img src='{esc(img_uri)}' alt='{esc(record.get('autosort_row_id', ''))}'>")
            lines.append(f"<b>{esc(record.get('autosort_row_id', ''))}</b><br>")
            lines.append(f"<span class='small'>bill state: {esc(record.get('metric_bill_state', ''))}</span><br>")
            lines.append(f"<span class='small'>bill px: {esc(record.get('metric_bill_length_px', ''))}</span><br>")
            lines.append(f"<span class='small'>frame: {esc(record.get('frame_key', ''))}</span><br>")
            lines.append(f"<span class='small'>image: {esc(record.get('image_path_resolved', ''))}</span>")
            lines.append("</div>")
        lines.append("</div>")
        lines.append("</div>")

    lines.append("<h2>Top Ranked Pair Evidence</h2>")
    lines.append("<table>")
    lines.append("<tr><th>Rank</th><th>Pair</th><th>Rows</th><th>Fusion</th><th>DINO</th><th>LightGlue</th><th>Decision Bucket</th><th>Cluster Edge</th><th>Metrics</th></tr>")
    for pair in top_pairs:
        lines.append(
            "<tr>"
            f"<td>{esc(pair.get('fusion_rank_desc', ''))}</td>"
            f"<td>{esc(pair.get('pair_id', ''))}</td>"
            f"<td>{esc(pair.get('row_a', ''))} ↔ {esc(pair.get('row_b', ''))}</td>"
            f"<td>{esc(pair.get('fusion_score', ''))}</td>"
            f"<td>{esc(pair.get('dino_similarity', ''))}</td>"
            f"<td>{esc(pair.get('lightglue_decision', ''))}; matches={esc(pair.get('lightglue_matches', ''))}; mean={esc(pair.get('lightglue_mean_score', ''))}</td>"
            f"<td>{esc(pair.get('fusion_review_bucket', ''))}</td>"
            f"<td>{esc(pair.get('cluster_edge_decision', ''))}: {esc(pair.get('cluster_edge_reason', ''))}</td>"
            f"<td>{esc(pair.get('fusion_metric_annotation', ''))}; diff_px={esc(pair.get('fusion_metric_bill_px_abs_diff', ''))}</td>"
            "</tr>"
        )
    lines.append("</table>")

    lines.append("</body></html>")
    path.write_text("\n".join(lines), encoding="utf-8")



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Birdbill promoted AutoSort app v0.2 read-only recipe-based Sandbox clustering stage."
    )
    parser.add_argument("--project-root", default=r"D:\birdbill", help="Birdbill project root.")
    parser.add_argument(
        "--smart-crop-manifest",
        default=r"D:\birdbill\output\debug\current-smart-cropper\smart-crop-manifest.csv",
        help="SmartCropper manifest CSV.",
    )
    parser.add_argument(
        "--metrics-observations",
        default=r"D:\birdbill\output\debug\current-metrics\metric-observations.csv",
        help="Optional Metrics observations CSV.",
    )
    parser.add_argument("--settings-ini", default=r"D:\birdbill\settings.ini", help="Optional settings.ini for diagnostics.")
    parser.add_argument(
        "--output-dir",
        default=r"D:\birdbill\output\debug\current-autosort",
        help="Output directory for AutoSort artifacts.",
    )
    parser.add_argument("--max-pairs", type=int, default=50000, help="Maximum pair rows to write. Use 0 for no cap.")
    parser.add_argument(
        "--dino-mode",
        choices=["run", "off", "probe"],
        default="run",
        help="run computes DINO embeddings; off writes scaffold only; probe imports/loads model without embedding images.",
    )
    parser.add_argument("--dino-model", default=DINO_MODEL_NAME_DEFAULT, help="Hugging Face DINOv2 model name.")
    parser.add_argument("--dino-device", default="auto", help="DINO device: auto, cpu, cuda, etc.")
    parser.add_argument(
        "--dino-local-files-only",
        action="store_true",
        help="Force local model cache only. Default matches old HBMR behavior and does not pass local_files_only.",
    )
    parser.add_argument("--dino-max-images", type=int, default=0, help="Maximum image rows to embed. Use 0 for no cap.")
    parser.add_argument(
        "--lightglue-mode",
        choices=["run", "off", "probe"],
        default="run",
        help="run verifies top DINO-ranked pairs with LightGlue; off writes DINO scaffold only; probe imports/loads LightGlue without scoring pairs.",
    )
    parser.add_argument("--lightglue-device", default="auto", help="LightGlue device: auto, cpu, cuda, etc.")
    parser.add_argument("--lightglue-max-pairs", type=int, default=15, help="Maximum DINO-ranked pairs to verify with LightGlue. Use 0 for all eligible pairs.")
    parser.add_argument(
        "--recipe",
        choices=list(AUTOSORT_RECIPES),
        default="fusion",
        help="AutoSort recipe used for ranking/clustering: dino, lightglue, fusion, metrics, or fusion-metrics.",
    )
    parser.add_argument("--metric-bill-px-tolerance", type=float, default=15.0, help="Bill length pixel tolerance for metrics recipes.")
    parser.add_argument("--lightglue-max-keypoints", type=int, default=LIGHTGLUE_MAX_KEYPOINTS_DEFAULT, help="SuperPoint maximum keypoints per image.")
    parser.add_argument("--cluster-threshold", type=float, default=0.65, help="Minimum selected recipe score for provisional cluster edges.")
    parser.add_argument("--clear-output", action="store_true", help="Clear output dir first. Refuses outside project root.")
    return parser


def run(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root)
    smart_crop_manifest = Path(args.smart_crop_manifest)
    metrics_observations = Path(args.metrics_observations)
    settings_ini = Path(args.settings_ini)
    output_dir = Path(args.output_dir)

    if args.clear_output:
        clear_directory_safely(output_dir, project_root)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    report_lines: List[str] = []
    report_lines.append(f"{SCRIPT_NAME} {SCRIPT_VERSION}")
    report_lines.append(f"purpose = {SCRIPT_PURPOSE}")
    report_lines.append(f"timestamp = {now_stamp()}")
    report_lines.append(f"script = {Path(__file__).resolve()}")
    report_lines.append(f"python = {sys.executable}")
    report_lines.append(f"project_root = {project_root}")
    report_lines.append(f"smart_crop_manifest = {smart_crop_manifest}")
    report_lines.append(f"metrics_observations = {metrics_observations}")
    report_lines.append(f"settings_ini = {settings_ini}")
    report_lines.append(f"output_dir = {output_dir}")
    report_lines.append("database_mutation = false")
    report_lines.append("durable_evidence_written = false")
    report_lines.append("media_files_written = 0")
    report_lines.append("temporal_continuity_identity_signal = disabled")
    report_lines.append("copresence_known_different_identity_signal = enabled_if_same_frame_evidence_available")
    report_lines.append("identity_assignment = none_read_only_provisional_cluster_preview")
    report_lines.append(f"autosort_recipe = {args.recipe}")
    report_lines.append(f"metric_bill_px_tolerance = {args.metric_bill_px_tolerance}")
    report_lines.append(f"dino_backend_root = {DINO_BACKEND_ROOT}")
    report_lines.append(f"lightglue_backend_root = {LIGHTGLUE_BACKEND_ROOT}")
    report_lines.append("")

    status = "UNKNOWN"
    exit_code = 0

    manifest_rows: List[Dict[str, str]] = []
    manifest_headers_original: List[str] = []
    manifest_headers_normalized: List[str] = []
    metric_rows: List[Dict[str, str]] = []
    metric_headers_original: List[str] = []
    metric_headers_normalized: List[str] = []
    metric_index: Dict[str, Dict[str, str]] = {}
    metric_join_columns: List[str] = []
    normalized_rows: List[Dict[str, str]] = []
    dino_embedding_rows: List[Dict[str, str]] = []
    dino_embeddings: Dict[str, List[float]] = {}
    dino_diagnostics: Dict[str, str] = {}
    lightglue_diagnostics: Dict[str, str] = {}
    fusion_diagnostics: Dict[str, str] = {}
    cluster_diagnostics: Dict[str, str] = {}
    pair_rows: List[Dict[str, str]] = []
    ranked_pair_rows: List[Dict[str, str]] = []
    conflict_rows: List[Dict[str, str]] = []
    cluster_records: List[Dict[str, str]] = []
    cluster_summary_rows: List[Dict[str, str]] = []
    pairs_truncated = False

    normalized_csv = output_dir / "autosort-input-normalized.csv"
    pairs_csv = output_dir / "autosort-candidate-pairs.csv"
    ranked_pairs_csv = output_dir / "autosort-ranked-pairs.csv"
    clusters_csv = output_dir / "autosort-provisional-clusters.csv"
    cluster_summary_csv = output_dir / "autosort-cluster-summary.csv"
    cluster_preview_html = output_dir / "autosort-cluster-preview.html"
    conflicts_csv = output_dir / "autosort-known-different-relations.csv"
    embeddings_csv = output_dir / "autosort-dino-embeddings.csv"
    manifest_json = output_dir / "manifest.json"
    report_path = output_dir / "autosort-report.txt"

    try:
        if not smart_crop_manifest.exists():
            raise FileNotFoundError(f"SmartCropper manifest not found: {smart_crop_manifest}")

        manifest_rows, manifest_headers_original, manifest_headers_normalized = csv_read_dicts(smart_crop_manifest)

        if metrics_observations.exists():
            metric_rows, metric_headers_original, metric_headers_normalized = csv_read_dicts(metrics_observations)
            metric_index, metric_join_columns = build_metric_index(metric_rows, metric_headers_normalized)

        settings_info = load_settings(settings_ini)
        normalized_rows = make_normalized_rows(
            manifest_rows=manifest_rows,
            project_root=project_root,
            manifest_dir=smart_crop_manifest.parent,
            metric_index=metric_index,
            metric_join_columns=metric_join_columns,
        )

        if args.dino_mode == "off":
            dino_embedding_rows, dino_embeddings, dino_diagnostics = dino_disabled_rows(normalized_rows, "not_run_dino_mode_off")
        elif args.dino_mode == "probe":
            import_diagnostics, modules = probe_dino_imports()
            dino_diagnostics = dict(import_diagnostics)
            if not dino_diagnostics.get("dino_import_error_module"):
                model_diagnostics, _processor, _model, _device = load_dino_model(
                    modules=modules,
                    model_name=str_clean(args.dino_model) or DINO_MODEL_NAME_DEFAULT,
                    requested_device=args.dino_device,
                    local_files_only=bool(args.dino_local_files_only),
                )
                dino_diagnostics.update(model_diagnostics)
            dino_embedding_rows, dino_embeddings = [], {}
            for row in normalized_rows:
                row["dino_embedding_status"] = "not_run_dino_probe_mode"
        else:
            dino_embedding_rows, dino_embeddings, dino_diagnostics = compute_dino_embeddings(
                rows=normalized_rows,
                model_name=str_clean(args.dino_model) or DINO_MODEL_NAME_DEFAULT,
                requested_device=args.dino_device,
                local_files_only=bool(args.dino_local_files_only),
                max_images=int(args.dino_max_images),
            )

        # Preserve v0.3 behavior: always write pair scaffold after row normalization, even if DINO failed.
        pair_rows, pairs_truncated = make_pairs(normalized_rows, dino_embeddings, int(args.max_pairs))
        row_by_id = {row["autosort_row_id"]: row for row in normalized_rows}

        if args.lightglue_mode == "off":
            lightglue_diagnostics = lightglue_disabled_rows(pair_rows, "not_run_lightglue_mode_off")
        elif args.lightglue_mode == "probe":
            lightglue_diagnostics = lightglue_probe_only(
                requested_device=args.lightglue_device,
                max_keypoints=int(args.lightglue_max_keypoints),
            )
            for pair in pair_rows:
                pair["lightglue_status"] = "not_run_lightglue_probe_mode"
        else:
            lightglue_diagnostics = run_lightglue_verifier(
                pair_rows=pair_rows,
                row_by_id=row_by_id,
                requested_device=args.lightglue_device,
                max_keypoints=int(args.lightglue_max_keypoints),
                max_pairs=int(args.lightglue_max_pairs),
            )

        fusion_diagnostics = apply_pair_fusion(
            pair_rows=pair_rows,
            recipe=args.recipe,
            metric_tolerance_px=float(args.metric_bill_px_tolerance),
        )
        ranked_pair_rows = sorted_ranked_pairs(pair_rows)
        cluster_records, cluster_summary_rows, cluster_diagnostics = build_provisional_clusters(
            normalized_rows=normalized_rows,
            pair_rows=pair_rows,
            cluster_threshold=float(args.cluster_threshold),
        )
        ranked_pair_rows = sorted_ranked_pairs(pair_rows)
        conflict_rows = make_conflicts(pair_rows)

        normalized_fieldnames = [
            "autosort_row_id",
            "autosort_row_id_source",
            "source_row_number",
            "source_key",
            "source_key_column",
            "frame_key",
            "frame_key_column",
            "animal_key",
            "animal_key_column",
            "image_path_column",
            "image_path_raw",
            "image_path_resolved",
            "image_path_exists",
            "image_path_resolve_source",
            "raw_crop_path_column",
            "raw_crop_path_raw",
            "raw_crop_path_resolved",
            "raw_crop_path_exists",
            "raw_crop_path_resolve_source",
            "metric_joined",
            "metric_join_column",
            "metric_join_value",
            "metric_bill_state",
            "metric_bill_length_px",
            "metric_bill_length_mm",
            "metric_aggregation_eligible",
            "metric_lower_bound_eligible",
            "dino_embedding_status",
            "dino_embedding_dim",
            "dino_model_name",
            "dino_model_version",
        ]
        pair_fieldnames = [
            "pair_id",
            "row_a",
            "row_b",
            "source_a",
            "source_b",
            "same_source",
            "frame_key_a",
            "frame_key_b",
            "co_present_known_different_identity",
            "co_present_reason",
            "dino_status",
            "dino_backend",
            "dino_model_name",
            "dino_model_version",
            "dino_similarity",
            "dino_similarity_rank_desc",
            "lightglue_status",
            "lightglue_backend",
            "lightglue_features",
            "lightglue_device",
            "lightglue_max_keypoints",
            "lightglue_keypoints_a",
            "lightglue_keypoints_b",
            "lightglue_matches",
            "lightglue_scores_available",
            "lightglue_mean_score",
            "lightglue_median_score",
            "lightglue_min_score",
            "lightglue_max_score",
            "lightglue_ranking_score",
            "lightglue_decision",
            "lightglue_seconds",
            "lightglue_error_type",
            "lightglue_error_message",
            "metric_pair_summary",
            "autosort_recipe",
            "metric_bill_px_tolerance",
            "fusion_dino_normalized",
            "fusion_dino_source",
            "fusion_lightglue_normalized",
            "fusion_lightglue_source",
            "fusion_metric_normalized",
            "fusion_metric_source",
            "fusion_metric_annotation",
            "fusion_metric_bill_px_abs_diff",
            "fusion_metric_note",
            "recipe_metric_note",
            "fusion_score",
            "fusion_source",
            "fusion_rank_desc",
            "fusion_review_bucket",
            "fusion_identity_decision",
            "cluster_edge_decision",
            "cluster_edge_reason",
            "autosort_identity_decision",
        ]
        conflict_fieldnames = ["relation_id", "row_a", "row_b", "relation", "reason", "frame_key", "source_a", "source_b"]
        embedding_fieldnames = [
            "autosort_row_id",
            "image_path_resolved",
            "dino_status",
            "dino_backend",
            "dino_model_name",
            "dino_model_version",
            "dino_embedding_dim",
            "dino_embedding_json",
        ]
        cluster_fieldnames = [
            "provisional_cluster_label",
            "cluster_status",
            "cluster_size",
            "autosort_row_id",
            "source_key",
            "frame_key",
            "animal_key",
            "image_path_resolved",
            "image_path_exists",
            "metric_bill_state",
            "metric_bill_length_px",
            "metric_bill_length_mm",
            "dino_embedding_status",
            "best_internal_pair_id",
            "best_internal_fusion_score",
            "identity_assignment",
            "autoname_commit",
            "db_mutation",
        ]
        cluster_summary_fieldnames = [
            "provisional_cluster_label",
            "cluster_status",
            "cluster_size",
            "member_rows",
            "used_edge_count",
            "internal_pair_count",
            "best_internal_pair_id",
            "best_internal_fusion_score",
            "identity_assignment",
            "autoname_commit",
            "db_mutation",
        ]

        csv_write_dicts(normalized_csv, normalized_rows, normalized_fieldnames)
        csv_write_dicts(pairs_csv, pair_rows, pair_fieldnames)
        csv_write_dicts(ranked_pairs_csv, ranked_pair_rows, pair_fieldnames)
        csv_write_dicts(conflicts_csv, conflict_rows, conflict_fieldnames)
        csv_write_dicts(embeddings_csv, dino_embedding_rows, embedding_fieldnames)
        csv_write_dicts(clusters_csv, cluster_records, cluster_fieldnames)
        csv_write_dicts(cluster_summary_csv, cluster_summary_rows, cluster_summary_fieldnames)
        preview_diagnostics = {}
        preview_diagnostics.update(dino_diagnostics)
        preview_diagnostics.update(lightglue_diagnostics)
        preview_diagnostics.update(fusion_diagnostics)
        preview_diagnostics.update(cluster_diagnostics)
        make_cluster_preview_html(
            path=cluster_preview_html,
            cluster_summaries=cluster_summary_rows,
            cluster_records=cluster_records,
            ranked_pair_rows=ranked_pair_rows,
            diagnostics=preview_diagnostics,
            script_version=SCRIPT_VERSION,
        )

        image_exists_count = sum(1 for row in normalized_rows if row.get("image_path_exists") == "true")
        image_missing_count = len(normalized_rows) - image_exists_count
        metric_joined_count = sum(1 for row in normalized_rows if row.get("metric_joined") == "true")
        frame_key_count = sum(1 for row in normalized_rows if row.get("frame_key"))
        dino_ready_count = sum(1 for row in normalized_rows if row.get("dino_embedding_status") == "ready")
        dino_pair_scored_count = sum(1 for row in pair_rows if row.get("dino_status") == "scored")
        dino_pair_missing_count = len(pair_rows) - dino_pair_scored_count
        lightglue_pair_scored_count = sum(1 for row in pair_rows if row.get("lightglue_status") == "scored")
        lightglue_pair_failed_count = sum(1 for row in pair_rows if str(row.get("lightglue_status", "")).startswith("fail"))
        lightglue_pair_selected_count = int(lightglue_diagnostics.get("lightglue_pairs_selected_count", "0") or "0")
        scored_similarities = [as_float(row.get("dino_similarity")) for row in pair_rows if as_float(row.get("dino_similarity")) is not None]
        top_dino_similarity = f"{max(scored_similarities):.8f}" if scored_similarities else ""
        lightglue_scores = [as_float(row.get("lightglue_ranking_score")) for row in pair_rows if as_float(row.get("lightglue_ranking_score")) is not None]
        top_lightglue_score = f"{max(lightglue_scores):.8f}" if lightglue_scores else ""

        dino_import_error_module = dino_diagnostics.get("dino_import_error_module", "")
        dino_model_load_status = dino_diagnostics.get("dino_model_load_status", "")
        lightglue_import_error_module = lightglue_diagnostics.get("lightglue_import_error_module", "")
        lightglue_model_load_status = lightglue_diagnostics.get("lightglue_model_load_status", "")
        if args.dino_mode == "off" and args.lightglue_mode == "off":
            status = "PASS_AUTOSORT_SCAFFOLD_READY_DINO_OFF_LIGHTGLUE_OFF"
            exit_code = 0
        elif args.dino_mode == "probe" and dino_import_error_module:
            status = f"FAIL_AUTOSORT_DINO_PROBE_IMPORT_{dino_import_error_module}"
            exit_code = 1
        elif args.dino_mode == "probe" and dino_model_load_status == "fail":
            status = "FAIL_AUTOSORT_DINO_PROBE_MODEL_LOAD"
            exit_code = 1
        elif args.lightglue_mode == "probe" and lightglue_import_error_module:
            status = f"FAIL_AUTOSORT_LIGHTGLUE_PROBE_IMPORT_{lightglue_import_error_module}"
            exit_code = 1
        elif args.lightglue_mode == "probe" and lightglue_model_load_status == "fail":
            status = "FAIL_AUTOSORT_LIGHTGLUE_PROBE_MODEL_LOAD"
            exit_code = 1
        elif args.dino_mode == "probe" or args.lightglue_mode == "probe":
            status = "PASS_AUTOSORT_MODEL_PROBE_READY"
            exit_code = 0
        elif dino_import_error_module:
            status = f"FAIL_AUTOSORT_DINO_IMPORT_{dino_import_error_module}"
            exit_code = 1
        elif dino_model_load_status == "fail":
            status = "FAIL_AUTOSORT_DINO_MODEL_LOAD"
            exit_code = 1
        elif args.lightglue_mode == "run" and lightglue_import_error_module:
            status = f"FAIL_AUTOSORT_LIGHTGLUE_IMPORT_{lightglue_import_error_module}"
            exit_code = 1
        elif args.lightglue_mode == "run" and lightglue_model_load_status == "fail":
            status = "FAIL_AUTOSORT_LIGHTGLUE_MODEL_LOAD"
            exit_code = 1
        elif not normalized_rows:
            status = "PARTIAL_AUTOSORT_READY_NO_INPUT_ROWS"
            exit_code = 0
        elif image_exists_count == 0:
            status = "PARTIAL_AUTOSORT_READY_NO_EXISTING_IMAGE_PATHS"
            exit_code = 0
        elif args.dino_mode == "run" and dino_ready_count == 0:
            status = "FAIL_AUTOSORT_DINO_NO_EMBEDDINGS_READY"
            exit_code = 1
        elif args.lightglue_mode == "run" and lightglue_pair_selected_count > 0 and lightglue_pair_scored_count == 0:
            status = "FAIL_AUTOSORT_LIGHTGLUE_NO_PAIRS_SCORED"
            exit_code = 1
        elif args.lightglue_mode == "run" and lightglue_pair_failed_count > 0:
            status = "PARTIAL_AUTOSORT_RECIPE_CLUSTERS_READY_WITH_PAIR_FAILURES"
            exit_code = 0
        elif args.lightglue_mode == "run":
            status = "PASS_AUTOSORT_RECIPE_CLUSTERS_READY"
            exit_code = 0
        elif dino_ready_count < image_exists_count:
            status = "PARTIAL_AUTOSORT_DINO_READY_WITH_IMAGE_OR_INFERENCE_FAILURES"
            exit_code = 0
        else:
            status = "PASS_AUTOSORT_DINO_READY"
            exit_code = 0

        column_report = column_presence_report(manifest_headers_normalized)

        report_lines.append("github_hbmr_source_basis:")
        report_lines.append("dino_embedding_basis = visualid.py/dinosim.py transformers AutoImageProcessor AutoModel mean last_hidden_state")
        report_lines.append("lightglue_basis = lightgluetest.py/autosortGUI.py SuperPoint + LightGlue local feature matching")
        report_lines.append("pair_ranking_boundary_basis = autosortGUI.py pair ranking only no identity decision")
        report_lines.append("")

        report_lines.append("input_summary:")
        report_lines.append(f"smart_crop_manifest_exists = {smart_crop_manifest.exists()}")
        report_lines.append(f"smart_crop_manifest_rows = {len(manifest_rows)}")
        report_lines.append(f"smart_crop_manifest_original_columns = {';'.join(manifest_headers_original)}")
        report_lines.append(f"smart_crop_manifest_normalized_columns = {';'.join(manifest_headers_normalized)}")
        for key, value in column_report.items():
            report_lines.append(f"{key} = {value}")
        report_lines.append("")

        report_lines.append("settings_summary:")
        for key in sorted(settings_info):
            report_lines.append(f"{key} = {settings_info[key]}")
        report_lines.append("")

        report_lines.append("metrics_summary:")
        report_lines.append(f"metrics_observations_exists = {metrics_observations.exists()}")
        report_lines.append(f"metrics_observation_rows = {len(metric_rows)}")
        report_lines.append(f"metrics_original_columns = {';'.join(metric_headers_original)}")
        report_lines.append(f"metrics_normalized_columns = {';'.join(metric_headers_normalized)}")
        report_lines.append(f"metrics_join_columns_seen = {';'.join(metric_join_columns)}")
        report_lines.append(f"metrics_index_keys = {len(metric_index)}")
        report_lines.append("metrics_identity_scoring = not_scored_v0_7_metric_pair_summary_only")
        report_lines.append("")

        report_lines.append("dino_summary:")
        report_lines.append(f"dino_mode = {args.dino_mode}")
        report_lines.append(f"dino_backend_root = {DINO_BACKEND_ROOT}")
        report_lines.append(f"dino_model_requested = {args.dino_model}")
        report_lines.append(f"dino_local_files_only = {'true' if args.dino_local_files_only else 'false_old_hbmr_default'}")
        for key in sorted(dino_diagnostics):
            report_lines.append(f"{key} = {dino_diagnostics[key]}")
        report_lines.append(f"dino_embedding_ready_count = {dino_ready_count}")
        report_lines.append(f"dino_pair_scored_count = {dino_pair_scored_count}")
        report_lines.append(f"dino_pair_missing_count = {dino_pair_missing_count}")
        report_lines.append(f"dino_top_similarity = {top_dino_similarity}")
        report_lines.append("dino_identity_authority = none_recall_ranking_only")
        report_lines.append("")

        report_lines.append("lightglue_summary:")
        report_lines.append(f"lightglue_mode = {args.lightglue_mode}")
        report_lines.append(f"lightglue_backend_root = {LIGHTGLUE_BACKEND_ROOT}")
        for key in sorted(lightglue_diagnostics):
            report_lines.append(f"{key} = {lightglue_diagnostics[key]}")
        report_lines.append(f"lightglue_pair_scored_count = {lightglue_pair_scored_count}")
        report_lines.append(f"lightglue_pair_failed_count = {lightglue_pair_failed_count}")
        report_lines.append(f"lightglue_top_ranking_score = {top_lightglue_score}")
        report_lines.append("lightglue_identity_authority = none_verification_evidence_only")
        report_lines.append("")

        report_lines.append("autosort_output_summary:")
        report_lines.append(f"autosort_input_normalized_rows = {len(normalized_rows)}")
        report_lines.append(f"autosort_image_path_exists_count = {image_exists_count}")
        report_lines.append(f"autosort_image_path_missing_count = {image_missing_count}")
        report_lines.append(f"autosort_metric_joined_count = {metric_joined_count}")
        report_lines.append(f"autosort_frame_key_available_count = {frame_key_count}")
        report_lines.append(f"autosort_candidate_pair_rows = {len(pair_rows)}")
        report_lines.append(f"lightglue_pair_scored_count = {lightglue_pair_scored_count}")
        report_lines.append(f"lightglue_pair_failed_count = {lightglue_pair_failed_count}")
        report_lines.append(f"autosort_pair_rows_truncated = {'true' if pairs_truncated else 'false'}")
        report_lines.append(f"autosort_known_different_relation_rows = {len(conflict_rows)}")
        report_lines.append(f"autosort_input_normalized_csv = {normalized_csv}")
        report_lines.append(f"autosort_candidate_pairs_csv = {pairs_csv}")
        report_lines.append(f"autosort_ranked_pairs_csv = {ranked_pairs_csv}")
        report_lines.append(f"autosort_provisional_clusters_csv = {clusters_csv}")
        report_lines.append(f"autosort_cluster_summary_csv = {cluster_summary_csv}")
        report_lines.append(f"autosort_cluster_preview_html = {cluster_preview_html}")
        report_lines.append(f"autosort_known_different_relations_csv = {conflicts_csv}")
        report_lines.append(f"autosort_dino_embeddings_csv = {embeddings_csv}")
        report_lines.append(f"manifest_json = {manifest_json}")
        report_lines.append(f"autosort_report = {report_path}")
        report_lines.append(f"status = {status}")

        manifest_payload = {
            "script": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "status": status,
            "timestamp": now_stamp(),
            "project_root": str(project_root),
            "smart_crop_manifest": str(smart_crop_manifest),
            "metrics_observations": str(metrics_observations),
            "settings_ini": str(settings_ini),
            "output_dir": str(output_dir),
            "database_mutation": False,
            "durable_evidence_written": False,
            "media_files_written": 0,
            "temporal_continuity_identity_signal": "disabled",
            "copresence_known_different_identity_signal": "enabled_if_same_frame_evidence_available",
            "identity_assignment": "none_read_only_provisional_cluster_preview",
            "autosort_recipe": args.recipe,
            "metric_bill_px_tolerance": float(args.metric_bill_px_tolerance),
            "github_hbmr_source_basis": {
                "dino": "visualid.py/dinosim.py transformers mean last_hidden_state",
                "pair_boundary": "autosortGUI.py pair ranking only no identity decision",
            },
            "dino": dino_diagnostics,
            "lightglue": "not_run_v0_7",
            "counts": {
                "smart_crop_manifest_rows": len(manifest_rows),
                "metrics_observation_rows": len(metric_rows),
                "autosort_input_normalized_rows": len(normalized_rows),
                "autosort_image_path_exists_count": image_exists_count,
                "autosort_image_path_missing_count": image_missing_count,
                "autosort_metric_joined_count": metric_joined_count,
                "autosort_frame_key_available_count": frame_key_count,
                "autosort_candidate_pair_rows": len(pair_rows),
                "autosort_pair_rows_truncated": pairs_truncated,
                "autosort_known_different_relation_rows": len(conflict_rows),
                "dino_embedding_ready_count": dino_ready_count,
                "dino_pair_scored_count": dino_pair_scored_count,
                "dino_pair_missing_count": dino_pair_missing_count,
                "lightglue_pair_scored_count": lightglue_pair_scored_count,
                "lightglue_pair_failed_count": lightglue_pair_failed_count,
                "lightglue_pairs_selected_count": lightglue_pair_selected_count,
                "fusion_ranked_pair_count": int(fusion_diagnostics.get("fusion_ranked_pair_count", "0") or "0"),
                "provisional_cluster_count": int(cluster_diagnostics.get("provisional_cluster_count", "0") or "0"),
                "provisional_multirow_cluster_count": int(cluster_diagnostics.get("provisional_multirow_cluster_count", "0") or "0"),
                "provisional_singleton_cluster_count": int(cluster_diagnostics.get("provisional_singleton_cluster_count", "0") or "0"),
            },
            "outputs": {
                "autosort_input_normalized_csv": str(normalized_csv),
                "autosort_candidate_pairs_csv": str(pairs_csv),
                "autosort_ranked_pairs_csv": str(ranked_pairs_csv),
                "autosort_provisional_clusters_csv": str(clusters_csv),
                "autosort_cluster_summary_csv": str(cluster_summary_csv),
                "autosort_cluster_preview_html": str(cluster_preview_html),
                "autosort_known_different_relations_csv": str(conflicts_csv),
                "autosort_dino_embeddings_csv": str(embeddings_csv),
                "manifest_json": str(manifest_json),
                "autosort_report": str(report_path),
            },
            "column_report": column_report,
            "settings": settings_info,
        }

        manifest_json.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
        write_text(report_path, report_lines)

    except Exception as exc:
        output_dir.mkdir(parents=True, exist_ok=True)
        if status == "UNKNOWN":
            status = f"FAIL_AUTOSORT_DINO_EXCEPTION_{type(exc).__name__}"

        report_lines.append("error:")
        report_lines.append(f"error_type = {type(exc).__name__}")
        report_lines.append(f"error_message = {exc}")
        report_lines.append("traceback:")
        report_lines.append(traceback.format_exc())
        report_lines.append(f"status = {status}")
        write_text(report_path, report_lines)

        manifest_payload = {
            "script": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "status": status,
            "timestamp": now_stamp(),
            "project_root": str(project_root),
            "smart_crop_manifest": str(smart_crop_manifest),
            "metrics_observations": str(metrics_observations),
            "settings_ini": str(settings_ini),
            "output_dir": str(output_dir),
            "database_mutation": False,
            "durable_evidence_written": False,
            "media_files_written": 0,
            "temporal_continuity_identity_signal": "disabled",
            "copresence_known_different_identity_signal": "enabled_if_same_frame_evidence_available",
            "identity_assignment": "none_read_only_provisional_cluster_preview",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "outputs": {"autosort_report": str(report_path)},
        }
        try:
            manifest_json.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
        except Exception:
            pass
        exit_code = 1

    dino_ready_count_console = sum(1 for row in normalized_rows if row.get("dino_embedding_status") == "ready")
    dino_pair_scored_count_console = sum(1 for row in pair_rows if row.get("dino_status") == "scored")
    dino_pair_missing_count_console = len(pair_rows) - dino_pair_scored_count_console
    lightglue_pair_scored_count_console = sum(1 for row in pair_rows if row.get("lightglue_status") == "scored")
    lightglue_pair_failed_count_console = sum(1 for row in pair_rows if str(row.get("lightglue_status", "")).startswith("fail"))

    print(f"AutoSort {SCRIPT_VERSION}")
    print(f"script = {Path(__file__).resolve()}")
    print(f"python = {sys.executable}")
    print(f"project_root = {project_root}")
    print(f"smart_crop_manifest = {smart_crop_manifest}")
    print(f"metrics_observations = {metrics_observations}")
    print(f"settings_ini = {settings_ini}")
    print(f"output_dir = {output_dir}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("media_files_written = 0")
    print("temporal_continuity_identity_signal = disabled")
    print("copresence_known_different_identity_signal = enabled_if_same_frame_evidence_available")
    print("identity_assignment = none_read_only_provisional_cluster_preview")
    print(f"autosort_recipe = {args.recipe}")
    print(f"metric_bill_px_tolerance = {args.metric_bill_px_tolerance}")
    print(f"dino_mode = {args.dino_mode}")
    print(f"dino_backend_root = {DINO_BACKEND_ROOT}")
    print(f"dino_model_requested = {args.dino_model}")
    print(f"dino_local_files_only = {'true' if args.dino_local_files_only else 'false_old_hbmr_default'}")
    for key in (
        "dino_import_torch",
        "dino_import_pil",
        "dino_import_transformers",
        "dino_import_error_module",
        "dino_import_error_type",
        "dino_import_error_message",
        "dino_device",
        "dino_model_load_status",
        "dino_model_load_error_type",
        "dino_model_load_error_message",
    ):
        print(f"{key} = {dino_diagnostics.get(key, '')}")
    print(f"smart_crop_manifest_rows = {len(manifest_rows)}")
    print(f"metrics_observation_rows = {len(metric_rows)}")
    print(f"autosort_input_normalized_rows = {len(normalized_rows)}")
    print(f"autosort_candidate_pair_rows = {len(pair_rows)}")
    print(f"autosort_known_different_relation_rows = {len(conflict_rows)}")
    print(f"dino_embedding_ready_count = {dino_ready_count_console}")
    print(f"dino_pair_scored_count = {dino_pair_scored_count_console}")
    print(f"dino_pair_missing_count = {dino_pair_missing_count_console}")
    print(f"lightglue_mode = {args.lightglue_mode}")
    print(f"lightglue_backend_root = {LIGHTGLUE_BACKEND_ROOT}")
    for key in (
        "lightglue_import_torch",
        "lightglue_import_lightglue",
        "lightglue_import_utils",
        "lightglue_import_error_module",
        "lightglue_import_error_type",
        "lightglue_import_error_message",
        "lightglue_device",
        "lightglue_model_load_status",
        "lightglue_model_load_error_type",
        "lightglue_model_load_error_message",
        "lightglue_pairs_selected_count",
    ):
        print(f"{key} = {lightglue_diagnostics.get(key, '')}")
    print(f"lightglue_pair_scored_count = {lightglue_pair_scored_count_console}")
    print(f"lightglue_pair_failed_count = {lightglue_pair_failed_count_console}")
    print(f"fusion_ranked_pair_count = {fusion_diagnostics.get('fusion_ranked_pair_count', '')}")
    print(f"fusion_top_score = {fusion_diagnostics.get('fusion_top_score', '')}")
    print(f"fusion_bucket_counts = {fusion_diagnostics.get('fusion_bucket_counts', '')}")
    print(f"cluster_threshold = {cluster_diagnostics.get('cluster_threshold', '')}")
    print(f"provisional_cluster_count = {cluster_diagnostics.get('provisional_cluster_count', '')}")
    print(f"provisional_multirow_cluster_count = {cluster_diagnostics.get('provisional_multirow_cluster_count', '')}")
    print(f"provisional_singleton_cluster_count = {cluster_diagnostics.get('provisional_singleton_cluster_count', '')}")
    print(f"cluster_edge_accepted_count = {cluster_diagnostics.get('cluster_edge_accepted_count', '')}")
    print(f"cluster_edge_blocked_conflict_count = {cluster_diagnostics.get('cluster_edge_blocked_conflict_count', '')}")
    print(f"autosort_ranked_pairs_csv = {ranked_pairs_csv}")
    print(f"autosort_provisional_clusters_csv = {clusters_csv}")
    print(f"autosort_cluster_preview_html = {cluster_preview_html}")
    print(f"autosort_pair_rows_truncated = {'true' if pairs_truncated else 'false'}")
    print(f"autosort_report = {report_path}")
    print(f"manifest_json = {manifest_json}")
    print(f"status = {status}")

    return exit_code


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
