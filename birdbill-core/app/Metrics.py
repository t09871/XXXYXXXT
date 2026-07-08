# Metrics.py | v0.1 | 2026-07-07 PDT | Birdbill promoted length metrics with app metrics feeder support path

from __future__ import annotations

import argparse
import configparser
import csv
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCRIPT_NAME = "Metrics.py"
SCRIPT_VERSION = "v0.1"
COMPONENT = "Metrics"
SCHEMA_VERSION = "metrics_v0.7"

DEFAULT_PROJECT_ROOT = Path(r"D:\birdbill")
DEFAULT_SMART_CROP_MANIFEST = DEFAULT_PROJECT_ROOT / "output" / "debug" / "current-smart-cropper" / "smart-crop-manifest.csv"
DEFAULT_OUTPUT_DIR = DEFAULT_PROJECT_ROOT / "output" / "debug" / "current-metrics"
DEFAULT_SETTINGS_INI = DEFAULT_PROJECT_ROOT / "settings.ini"
DEFAULT_FEEDER_PROFILE = DEFAULT_PROJECT_ROOT / "app" / "metrics" / "feeder-single.json"

PATH_FIELDS = [
    "raw_crop_path",
    "whole_candidate_crop_path",
    "head_bill_crop_path",
    "body_crop_path",
]

OBSERVATION_FIELDS = [
    "metrics_schema_version",
    "metrics_decision",
    "metrics_note",
    "metric_input_index",
    "metric_family",
    "measurement_type",
    "measurement_method",
    "metric_observation_state",
    "metric_use_class",
    "length_px_role",
    "range_support_class",
    "metric_px_ready",
    "aggregation_eligible",
    "lower_bound_eligible",
    "autosort_feature_eligible",
    "metric_blockers",
    "metric_warnings",
    "metric_scale_ready",
    "metric_scale_state",
    "scale_source",
    "scale_confidence",
    "px_per_mm",
    "calibration_profile_path",
    "calibration_profile_name",
    "calibration_profile_status",
    "calibration_profile_units",
    "calibration_profile_has_front_px_per_mm",
    "calibration_profile_front_px_per_mm",
    "value_px",
    "value_px_recomputed",
    "value_px_recompute_delta",
    "value_px_visible_lower_bound",
    "value_px_for_range",
    "value_mm",
    "value_mm_visible_lower_bound",
    "value_mm_for_range",
    "length_axis_angle_deg",
    "point_bounds_state",
    "visibility_state",
    "whole_feature_visibility_state",
    "base_outside_raw_crop_px",
    "tip_outside_raw_crop_px",
    "visible_lower_bound_clip_x",
    "visible_lower_bound_clip_y",
    "visible_lower_bound_clip_t",
    "likelihood_quality_band",
    "min_point_likelihood",
    "base_x_raw_crop",
    "base_y_raw_crop",
    "base_likelihood",
    "tip_x_raw_crop",
    "tip_y_raw_crop",
    "tip_likelihood",
    "raw_crop_width_px",
    "raw_crop_height_px",
    "source_video",
    "frame_id",
    "source_frame_index",
    "camera_local_time_seconds",
    "detection_id",
    "raw_crop_path",
    "whole_candidate_crop_path",
    "head_bill_crop_path",
    "body_crop_path",
    "smart_cropper_decision",
    "smart_cropper_note",
    "metric_eligible_bill_length",
    "metric_eligibility_reason",
    "autosort_visual_ready",
    "autosort_metric_ready",
    "dlc_billtip_decision",
    "dlc_prediction_note",
    "dlc_h5_path",
    "dlc_row_index",
    "dlc_match_method",
    "dlc_bill_base_bodypart_used",
    "dlc_bill_tip_bodypart_used",
    "bill_tip_in_head_roi",
    "bill_base_in_head_roi",
    "retention_decision",
    "retention_score",
    "mmpose_ok",
    "pose_map_decision",
    "pose_handoff_decision",
    "notes",
]

SUMMARY_FIELDS = [
    "metrics_schema_version",
    "summary_group_key",
    "source_video",
    "metric_family",
    "measurement_type",
    "metric_scale_ready",
    "metric_scale_state",
    "scale_source",
    "scale_confidence",
    "px_per_mm",
    "calibration_profile_name",
    "observation_count",
    "recorded_observation_count",
    "full_length_count",
    "partial_lower_bound_count",
    "diagnostic_count",
    "rejected_count",
    "aggregation_eligible_count",
    "lower_bound_eligible_count",
    "full_length_min_px",
    "full_length_mean_px",
    "full_length_max_px",
    "full_length_upper_percentile_px",
    "partial_lower_bound_min_px",
    "partial_lower_bound_mean_px",
    "partial_lower_bound_max_px",
    "observed_range_floor_px",
    "observed_range_ceiling_px",
    "full_length_min_mm",
    "full_length_mean_mm",
    "full_length_max_mm",
    "full_length_upper_percentile_mm",
    "partial_lower_bound_min_mm",
    "partial_lower_bound_mean_mm",
    "partial_lower_bound_max_mm",
    "observed_range_floor_mm",
    "observed_range_ceiling_mm",
    "observed_range_note",
]


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def parse_bool_text(value: Any) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def fmt_float(value: Optional[float], digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def first_present(row: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value)
    return ""


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def summarize_values(values: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not values:
        return None, None, None
    return min(values), sum(values) / len(values), max(values)


def mm_from_px(value_px: Optional[float], px_per_mm: Optional[float]) -> Optional[float]:
    if value_px is None or px_per_mm is None or px_per_mm <= 0:
        return None
    return value_px / px_per_mm


def norm_path_text(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def is_inside_project(path: Path, project_root: Path) -> bool:
    path_text = norm_path_text(path)
    root_text = norm_path_text(project_root)
    return path_text == root_text or path_text.startswith(root_text.rstrip("\\/") + os.sep)


def relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except Exception:
        return str(path)


def parse_settings_fallback_text(settings_path: Path) -> Dict[str, Any]:
    """Small INI fallback parser for the [metrics] block.

    This is intentionally narrow. It prevents calibration from silently staying uncalibrated if
    ConfigParser fails to see a simple metrics key in a hand-edited settings.ini.
    """
    found: Dict[str, Any] = {
        "px_per_mm": None,
        "scale_state": "",
        "scale_source": "",
        "scale_confidence": "",
        "feeder_profile": "",
        "source_key": "",
        "metrics_keys_seen": "",
        "warnings": [],
    }

    try:
        raw = settings_path.read_text(encoding="utf-8-sig")
    except Exception as exc:
        found["warnings"].append(f"fallback_failed_to_read_settings_ini error={exc}")
        return found

    in_metrics = False
    for original_line in raw.splitlines():
        line = original_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue

        section_match = re.match(r"^\[([^\]]+)\]\s*$", line)
        if section_match:
            in_metrics = section_match.group(1).strip().lower() == "metrics"
            continue

        if not in_metrics or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        seen = [part for part in str(found.get("metrics_keys_seen", "")).split(";") if part]
        seen.append(key)
        found["metrics_keys_seen"] = ";".join(dict.fromkeys(seen))

        if key in {"bill_length_px_per_mm", "feeder1_px_per_mm", "front_px_per_mm", "px_per_mm", "pixels_per_mm"}:
            candidate = parse_float(value)
            if candidate is not None and candidate > 0:
                found["px_per_mm"] = candidate
                found["source_key"] = f"fallback.metrics.{key}"
        elif key in {"metric_scale_state", "scale_state", "calibration_state"}:
            found["scale_state"] = value
        elif key in {"scale_source", "calibration_source"}:
            found["scale_source"] = value
        elif key in {"scale_confidence", "calibration_confidence"}:
            found["scale_confidence"] = value
        elif key in {"feeder_profile", "feeder_profile_path", "calibration_profile"}:
            found["feeder_profile"] = value

    return found


def load_settings(settings_path: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "settings_path": str(settings_path),
        "settings_exists": settings_path.exists(),
        "settings_read_method": "",
        "settings_sections": "",
        "metrics_keys_seen": "",
        "px_per_mm": None,
        "scale_state": "",
        "scale_source": "",
        "scale_confidence": "",
        "feeder_profile": "",
        "warnings": [],
        "source_key": "",
    }
    if not settings_path.exists():
        info["settings_read_method"] = "missing"
        return info

    parser = configparser.ConfigParser()
    try:
        read_files = parser.read(settings_path, encoding="utf-8-sig")
        info["settings_read_method"] = "configparser"
        info["settings_sections"] = ";".join(parser.sections())
        if not read_files:
            info["warnings"].append("configparser_read_returned_no_files")
    except Exception as exc:
        info["settings_read_method"] = "configparser_failed"
        info["warnings"].append(f"failed_to_read_settings_ini error={exc}")

    section_names = ["metrics", "Metrics", "calibration", "Calibration", "biometrics", "Biometrics"]
    px_keys = ["bill_length_px_per_mm", "feeder1_px_per_mm", "front_px_per_mm", "px_per_mm", "pixels_per_mm"]
    state_keys = ["metric_scale_state", "scale_state", "calibration_state"]
    source_keys = ["scale_source", "calibration_source"]
    confidence_keys = ["scale_confidence", "calibration_confidence"]
    profile_keys = ["feeder_profile", "feeder_profile_path", "calibration_profile"]

    for section in section_names:
        if not parser.has_section(section):
            continue

        if section.lower() == "metrics":
            try:
                info["metrics_keys_seen"] = ";".join(parser.options(section))
            except Exception:
                pass

        for key in px_keys:
            if parser.has_option(section, key):
                candidate = parse_float(parser.get(section, key))
                if candidate is not None and candidate > 0:
                    info["px_per_mm"] = candidate
                    info["source_key"] = f"{section}.{key}"
                    break

        for key in state_keys:
            if parser.has_option(section, key):
                info["scale_state"] = parser.get(section, key).strip()
                break

        for key in source_keys:
            if parser.has_option(section, key):
                info["scale_source"] = parser.get(section, key).strip()
                break

        for key in confidence_keys:
            if parser.has_option(section, key):
                info["scale_confidence"] = parser.get(section, key).strip()
                break

        for key in profile_keys:
            if parser.has_option(section, key):
                info["feeder_profile"] = parser.get(section, key).strip()
                break

        if info["px_per_mm"] is not None or info["feeder_profile"]:
            break

    if info["px_per_mm"] is None or not info["feeder_profile"]:
        fallback = parse_settings_fallback_text(settings_path)
        info["settings_read_method"] = f"{info['settings_read_method']}+fallback"
        info["warnings"].extend(fallback.get("warnings", []))
        for key in ["px_per_mm", "scale_state", "scale_source", "scale_confidence", "feeder_profile", "source_key", "metrics_keys_seen"]:
            if fallback.get(key) and not info.get(key):
                info[key] = fallback[key]

    if info["px_per_mm"] is None:
        info["warnings"].append("settings_metrics_px_per_mm_not_found")
    if not info["feeder_profile"]:
        info["warnings"].append("settings_metrics_feeder_profile_not_found")

    info["warnings"] = list(dict.fromkeys(info["warnings"]))
    return info


def count_nullish_values(mapping: Dict[str, Any]) -> int:
    total = 0
    for value in mapping.values():
        if value is None:
            total += 1
        elif isinstance(value, str) and value.strip() == "":
            total += 1
        elif isinstance(value, list) and len(value) == 0:
            total += 1
    return total


def load_feeder_profile(profile_path: Optional[Path], project_root: Path) -> Dict[str, Any]:
    default_feeder_profile = project_root / "app" / "metrics" / "feeder-single.json"
    result: Dict[str, Any] = {
        "profile_found": False,
        "profile_path": "",
        "profile_name": "",
        "profile_status": "",
        "profile_units": "",
        "has_front_px_per_mm": False,
        "front_px_per_mm": None,
        "warnings": [],
        "candidate_paths": [],
    }

    candidates: List[Path] = []
    if profile_path is not None:
        candidates.append(profile_path)
    candidates.append(default_feeder_profile)

    seen: set[str] = set()
    for candidate in candidates:
        candidate_abs = Path(candidate)
        candidate_key = norm_path_text(candidate_abs)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)

        result["candidate_paths"].append(str(candidate_abs))

        if not is_inside_project(candidate_abs, project_root):
            result["warnings"].append(f"ignored_profile_outside_project_root path={candidate_abs}")
            continue

        if not candidate_abs.exists():
            continue

        try:
            profile = read_json(candidate_abs)
        except Exception as exc:
            result["warnings"].append(f"failed_to_read_profile path={candidate_abs} error={exc}")
            continue

        result["profile_found"] = True
        result["profile_path"] = str(candidate_abs)
        result["profile_name"] = str(profile.get("profile_name", ""))
        result["profile_status"] = str(profile.get("status", ""))
        result["profile_units"] = str(profile.get("units", ""))

        scale_estimates = profile.get("scale_estimates", {})
        front_px_per_mm = None
        if isinstance(scale_estimates, dict):
            front_px_per_mm = parse_float(scale_estimates.get("front_px_per_mm"))
            if front_px_per_mm is None:
                front_px_per_mm = parse_float(scale_estimates.get("px_per_mm"))

        result["front_px_per_mm"] = front_px_per_mm
        result["has_front_px_per_mm"] = bool(front_px_per_mm is not None and front_px_per_mm > 0)

        physical = profile.get("physical_dimensions_mm", {})
        if isinstance(physical, dict):
            null_count = count_nullish_values(physical)
            if null_count:
                result["warnings"].append(f"physical_dimensions_mm_null_count={null_count}")

        landmarks_front = profile.get("landmarks_front_image_px", {})
        if isinstance(landmarks_front, dict):
            null_count = count_nullish_values(landmarks_front)
            if null_count:
                result["warnings"].append(f"landmarks_front_image_px_empty_or_null_count={null_count}")

        landmarks_top = profile.get("landmarks_top_image_px", {})
        if isinstance(landmarks_top, dict):
            null_count = count_nullish_values(landmarks_top)
            if null_count:
                result["warnings"].append(f"landmarks_top_image_px_empty_or_null_count={null_count}")

        if result["profile_units"] and result["profile_units"] != "mm":
            result["warnings"].append("profile_units_not_mm")

        if not result["has_front_px_per_mm"]:
            result["warnings"].append("scale_estimates.front_px_per_mm_missing")

        if result["profile_status"] != "validated_calibration_profile":
            result["warnings"].append(f"profile_status_not_validated status={result['profile_status']}")

        return result

    return result


def resolve_profile_path(args: argparse.Namespace, settings_info: Dict[str, Any], project_root: Path) -> Optional[Path]:
    if str(args.feeder_profile).strip():
        candidate = Path(args.feeder_profile).resolve()
    elif str(settings_info.get("feeder_profile") or "").strip():
        candidate = Path(str(settings_info.get("feeder_profile"))).resolve()
    else:
        candidate = DEFAULT_FEEDER_PROFILE

    if not is_inside_project(candidate, project_root):
        return candidate
    return candidate


def resolve_calibration(args: argparse.Namespace, settings_info: Dict[str, Any], feeder_profile_info: Dict[str, Any]) -> Dict[str, Any]:
    explicit_px_per_mm = parse_float(args.px_per_mm)
    settings_px_per_mm = settings_info.get("px_per_mm")
    profile_px_per_mm = feeder_profile_info.get("front_px_per_mm")

    px_per_mm = None
    scale_source = ""

    if explicit_px_per_mm is not None and explicit_px_per_mm > 0:
        px_per_mm = explicit_px_per_mm
        scale_source = "cli_px_per_mm"
    elif settings_px_per_mm is not None and settings_px_per_mm > 0:
        px_per_mm = settings_px_per_mm
        source_key = settings_info.get("source_key") or "metrics.px_per_mm"
        scale_source = settings_info.get("scale_source") or f"settings_ini:{source_key}"
    elif profile_px_per_mm is not None and profile_px_per_mm > 0:
        px_per_mm = profile_px_per_mm
        scale_source = feeder_profile_info.get("profile_name") or "feeder_profile_scale_estimate"

    if str(args.scale_source).strip():
        scale_source = str(args.scale_source).strip()

    scale_state = str(args.scale_state).strip() or str(settings_info.get("scale_state") or "").strip()
    scale_confidence = str(args.scale_confidence).strip() or str(settings_info.get("scale_confidence") or "").strip()

    if px_per_mm is not None and px_per_mm > 0:
        metric_scale_ready = True
        if not scale_state:
            scale_state = "same_plane_feeder1_candidate"
        if not scale_confidence:
            scale_confidence = "validated" if scale_state == "same_plane_feeder1_validated" else "provisional"
    else:
        metric_scale_ready = False
        if feeder_profile_info.get("profile_found"):
            scale_state = "calibration_assets_found_but_no_px_per_mm"
            scale_source = feeder_profile_info.get("profile_name") or "feeder_profile"
        else:
            scale_state = "uncalibrated_px_only"
            scale_source = "none"
        scale_confidence = "none"

    warnings: List[str] = []
    warnings.extend(settings_info.get("warnings", []))
    warnings.extend(feeder_profile_info.get("warnings", []))
    if metric_scale_ready and scale_state != "same_plane_feeder1_validated":
        warnings.append(f"scale_not_validated state={scale_state}")
    if metric_scale_ready and scale_confidence != "validated":
        warnings.append(f"scale_confidence_not_validated confidence={scale_confidence}")

    return {
        "metric_scale_ready": metric_scale_ready,
        "metric_scale_state": scale_state,
        "scale_source": scale_source,
        "scale_confidence": scale_confidence,
        "px_per_mm": px_per_mm,
        "warnings": list(dict.fromkeys(warnings)),
        "settings_info": settings_info,
    }


def distance_outside_bounds(x: Optional[float], y: Optional[float], width: Optional[float], height: Optional[float]) -> Optional[float]:
    if x is None or y is None or width is None or height is None:
        return None
    dx = 0.0
    dy = 0.0
    if x < 0:
        dx = abs(x)
    elif x > width:
        dx = x - width
    if y < 0:
        dy = abs(y)
    elif y > height:
        dy = y - height
    return math.hypot(dx, dy)


def point_inside_bounds(x: Optional[float], y: Optional[float], width: Optional[float], height: Optional[float]) -> Optional[bool]:
    if x is None or y is None or width is None or height is None:
        return None
    return x >= 0 and y >= 0 and x <= width and y <= height


def likelihood_quality_band(min_likelihood: Optional[float], min_required: float) -> str:
    if min_likelihood is None:
        return "missing_likelihood"
    if min_likelihood < min_required:
        return "below_minimum"
    if min_likelihood >= 0.70:
        return "high"
    if min_likelihood >= 0.30:
        return "medium"
    return "low"


def clip_ray_from_inside_to_rectangle(
    x0: Optional[float],
    y0: Optional[float],
    x1: Optional[float],
    y1: Optional[float],
    width: Optional[float],
    height: Optional[float],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    if None in (x0, y0, x1, y1, width, height):
        return None, None, None, None

    x0f = float(x0)
    y0f = float(y0)
    x1f = float(x1)
    y1f = float(y1)
    wf = float(width)
    hf = float(height)

    dx = x1f - x0f
    dy = y1f - y0f
    full_len = math.hypot(dx, dy)
    if full_len <= 0:
        return None, None, None, None

    candidates: List[Tuple[float, float, float]] = []

    if abs(dx) > 1e-12:
        for x_edge in (0.0, wf):
            t = (x_edge - x0f) / dx
            if t >= 0:
                y_at = y0f + t * dy
                if y_at >= -1e-6 and y_at <= hf + 1e-6:
                    candidates.append((t, x_edge, min(max(y_at, 0.0), hf)))

    if abs(dy) > 1e-12:
        for y_edge in (0.0, hf):
            t = (y_edge - y0f) / dy
            if t >= 0:
                x_at = x0f + t * dx
                if x_at >= -1e-6 and x_at <= wf + 1e-6:
                    candidates.append((t, min(max(x_at, 0.0), wf), y_edge))

    valid = [(t, x, y) for (t, x, y) in candidates if t > 1e-9]
    if not valid:
        return None, None, None, None

    t_clip, x_clip, y_clip = sorted(valid, key=lambda item: item[0])[0]
    visible_len = min(t_clip, 1.0) * full_len
    return x_clip, y_clip, t_clip, visible_len


def classify_bill_length(
    width: Optional[float],
    height: Optional[float],
    base_x: Optional[float],
    base_y: Optional[float],
    tip_x: Optional[float],
    tip_y: Optional[float],
    min_likelihood: Optional[float],
    min_bill_point_likelihood: float,
    path_blockers: List[str],
    recompute_blockers: List[str],
) -> Dict[str, Any]:
    blockers: List[str] = []
    warnings: List[str] = []
    blockers.extend(path_blockers)
    blockers.extend(recompute_blockers)

    if width is None or height is None or width <= 0 or height <= 0:
        blockers.append("invalid_raw_crop_dimensions")
    if base_x is None or base_y is None:
        blockers.append("missing_bill_base_xy")
    if tip_x is None or tip_y is None:
        blockers.append("missing_bill_tip_xy")
    if min_likelihood is None:
        blockers.append("missing_bill_point_likelihood")
    elif min_likelihood < min_bill_point_likelihood:
        blockers.append("low_bill_point_likelihood")

    base_inside = point_inside_bounds(base_x, base_y, width, height)
    tip_inside = point_inside_bounds(tip_x, tip_y, width, height)
    base_outside_px = distance_outside_bounds(base_x, base_y, width, height)
    tip_outside_px = distance_outside_bounds(tip_x, tip_y, width, height)

    point_bounds_state = "unknown_bounds_state"
    visibility_state = "unknown"
    whole_feature_visibility_state = "unknown"
    observation_state = "diagnostic_only"
    metric_use_class = "diagnostic_only"
    length_px_role = "diagnostic_predicted_extension"
    range_support_class = "diagnostic_only"
    metric_px_ready = False
    aggregation_eligible = False
    lower_bound_eligible = False
    autosort_feature_eligible = False
    x_clip = None
    y_clip = None
    t_clip = None
    visible_lower_bound = None

    geometry_blocked = any(
        blocker in blockers
        for blocker in [
            "invalid_raw_crop_dimensions",
            "missing_bill_base_xy",
            "missing_bill_tip_xy",
            "missing_bill_point_likelihood",
            "low_bill_point_likelihood",
            "zero_length",
            "length_recompute_mismatch",
        ]
    )

    if base_inside is True and tip_inside is True:
        point_bounds_state = "inside_raw_crop_bounds"
        visibility_state = "whole_bill_points_inside_raw_crop"
        whole_feature_visibility_state = "bill_points_inside_raw_crop"
        if not geometry_blocked and not path_blockers:
            observation_state = "full_length_px_ready"
            metric_use_class = "biometrics_candidate"
            length_px_role = "full_length_candidate"
            range_support_class = "range_candidate"
            metric_px_ready = True
            aggregation_eligible = True
            autosort_feature_eligible = True
        else:
            observation_state = "rejected_geometry"
            metric_use_class = "reject"
            length_px_role = "rejected_geometry"
            range_support_class = "reject"

    elif base_inside is True and tip_inside is False:
        point_bounds_state = "tip_outside_raw_crop_bounds"
        visibility_state = "partial_bill_tip_outside_raw_crop"
        whole_feature_visibility_state = "blocked_bill_tip_outside_raw_crop"
        if not geometry_blocked and not path_blockers:
            x_clip, y_clip, t_clip, visible_lower_bound = clip_ray_from_inside_to_rectangle(
                base_x, base_y, tip_x, tip_y, width, height
            )
            if visible_lower_bound is not None:
                observation_state = "partial_length_lower_bound"
                metric_use_class = "biometrics_lower_bound"
                length_px_role = "partial_length_lower_bound"
                range_support_class = "range_floor_support"
                lower_bound_eligible = True
                autosort_feature_eligible = True
                warnings.append("tip_outside_raw_crop_bounds")
            else:
                observation_state = "diagnostic_predicted_extension"
                warnings.append("tip_outside_raw_crop_bounds_no_clip_intersection")
        else:
            observation_state = "rejected_geometry"
            metric_use_class = "reject"
            length_px_role = "rejected_geometry"
            range_support_class = "reject"

    elif base_inside is False and tip_inside is True:
        point_bounds_state = "base_outside_raw_crop_bounds"
        visibility_state = "partial_bill_base_outside_raw_crop"
        whole_feature_visibility_state = "blocked_bill_base_outside_raw_crop"
        if not geometry_blocked and not path_blockers:
            x_clip, y_clip, t_clip, visible_lower_bound = clip_ray_from_inside_to_rectangle(
                tip_x, tip_y, base_x, base_y, width, height
            )
            if visible_lower_bound is not None:
                observation_state = "partial_length_lower_bound"
                metric_use_class = "biometrics_lower_bound"
                length_px_role = "partial_length_lower_bound"
                range_support_class = "range_floor_support"
                lower_bound_eligible = True
                autosort_feature_eligible = True
                warnings.append("base_outside_raw_crop_bounds")
            else:
                observation_state = "diagnostic_predicted_extension"
                warnings.append("base_outside_raw_crop_bounds_no_clip_intersection")
        else:
            observation_state = "rejected_geometry"
            metric_use_class = "reject"
            length_px_role = "rejected_geometry"
            range_support_class = "reject"

    elif base_inside is False and tip_inside is False:
        point_bounds_state = "points_outside_raw_crop_bounds"
        visibility_state = "points_outside_raw_crop"
        whole_feature_visibility_state = "blocked_points_outside_raw_crop"
        observation_state = "diagnostic_predicted_extension"
        warnings.append("points_outside_raw_crop_bounds")

    else:
        observation_state = "rejected_geometry"
        metric_use_class = "reject"
        length_px_role = "rejected_geometry"
        range_support_class = "reject"

    if observation_state in {"partial_length_lower_bound", "diagnostic_predicted_extension"}:
        metric_px_ready = False
        aggregation_eligible = False

    if observation_state.startswith("rejected"):
        metric_px_ready = False
        aggregation_eligible = False
        lower_bound_eligible = False
        autosort_feature_eligible = False

    return {
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "point_bounds_state": point_bounds_state,
        "visibility_state": visibility_state,
        "whole_feature_visibility_state": whole_feature_visibility_state,
        "metric_observation_state": observation_state,
        "metric_use_class": metric_use_class,
        "length_px_role": length_px_role,
        "range_support_class": range_support_class,
        "metric_px_ready": metric_px_ready,
        "aggregation_eligible": aggregation_eligible,
        "lower_bound_eligible": lower_bound_eligible,
        "autosort_feature_eligible": autosort_feature_eligible,
        "base_outside_px": base_outside_px,
        "tip_outside_px": tip_outside_px,
        "clip_x": x_clip,
        "clip_y": y_clip,
        "clip_t": t_clip,
        "visible_lower_bound": visible_lower_bound,
    }


def make_bill_length_observation(
    row: Dict[str, str],
    row_index: int,
    min_bill_point_likelihood: float,
    feeder_profile_info: Dict[str, Any],
    calibration: Dict[str, Any],
) -> Dict[str, Any]:
    path_blockers: List[str] = []
    recompute_blockers: List[str] = []
    warnings: List[str] = []

    input_index = first_present(row, ["smart_cropper_input_index", "dlc_input_index"])
    if input_index == "":
        input_index = str(row_index)

    output: Dict[str, Any] = {field: "" for field in OBSERVATION_FIELDS}
    output["metrics_schema_version"] = SCHEMA_VERSION
    output["metric_input_index"] = input_index
    output["metric_family"] = "length"
    output["measurement_type"] = "bill_length"
    output["measurement_method"] = "dlc_bill_base_to_bill_tip_px_from_smart_crop_manifest"
    output["metric_scale_ready"] = str(bool(calibration.get("metric_scale_ready", False)))
    output["metric_scale_state"] = calibration.get("metric_scale_state", "")
    output["scale_source"] = calibration.get("scale_source", "")
    output["scale_confidence"] = calibration.get("scale_confidence", "")
    output["px_per_mm"] = fmt_float(calibration.get("px_per_mm"), 9)
    output["calibration_profile_path"] = feeder_profile_info.get("profile_path", "")
    output["calibration_profile_name"] = feeder_profile_info.get("profile_name", "")
    output["calibration_profile_status"] = feeder_profile_info.get("profile_status", "")
    output["calibration_profile_units"] = feeder_profile_info.get("profile_units", "")
    output["calibration_profile_has_front_px_per_mm"] = str(bool(feeder_profile_info.get("has_front_px_per_mm", False)))
    output["calibration_profile_front_px_per_mm"] = fmt_float(feeder_profile_info.get("front_px_per_mm"), 6)

    passthrough_fields = [
        "source_video",
        "frame_id",
        "source_frame_index",
        "camera_local_time_seconds",
        "detection_id",
        "raw_crop_path",
        "whole_candidate_crop_path",
        "head_bill_crop_path",
        "body_crop_path",
        "smart_cropper_decision",
        "smart_cropper_note",
        "metric_eligible_bill_length",
        "metric_eligibility_reason",
        "autosort_visual_ready",
        "autosort_metric_ready",
        "dlc_billtip_decision",
        "dlc_prediction_note",
        "dlc_h5_path",
        "dlc_row_index",
        "dlc_match_method",
        "dlc_bill_base_bodypart_used",
        "dlc_bill_tip_bodypart_used",
        "bill_tip_in_head_roi",
        "bill_base_in_head_roi",
        "retention_decision",
        "retention_score",
        "mmpose_ok",
        "pose_map_decision",
        "pose_handoff_decision",
        "notes",
    ]
    for field in passthrough_fields:
        output[field] = row.get(field, "")

    for path_field in PATH_FIELDS:
        path_text = str(row.get(path_field, "")).strip()
        if path_text == "":
            path_blockers.append(f"missing_path:{path_field}")
        elif not Path(path_text).exists():
            path_blockers.append(f"unreadable_path:{path_field}")

    width = parse_float(first_present(row, ["raw_crop_width_actual", "raw_crop_width"]))
    height = parse_float(first_present(row, ["raw_crop_height_actual", "raw_crop_height"]))
    base_x = parse_float(row.get("bill_base_x_raw_crop"))
    base_y = parse_float(row.get("bill_base_y_raw_crop"))
    tip_x = parse_float(row.get("bill_tip_x_raw_crop"))
    tip_y = parse_float(row.get("bill_tip_y_raw_crop"))
    base_likelihood = parse_float(row.get("bill_base_likelihood"))
    tip_likelihood = parse_float(row.get("bill_tip_likelihood"))
    reported_length_px = parse_float(row.get("dlc_bill_length_px"))
    reported_angle_deg = parse_float(row.get("bill_axis_angle_deg"))
    px_per_mm = calibration.get("px_per_mm")

    output["raw_crop_width_px"] = fmt_float(width, 3)
    output["raw_crop_height_px"] = fmt_float(height, 3)
    output["base_x_raw_crop"] = fmt_float(base_x, 3)
    output["base_y_raw_crop"] = fmt_float(base_y, 3)
    output["base_likelihood"] = fmt_float(base_likelihood, 6)
    output["tip_x_raw_crop"] = fmt_float(tip_x, 3)
    output["tip_y_raw_crop"] = fmt_float(tip_y, 3)
    output["tip_likelihood"] = fmt_float(tip_likelihood, 6)
    output["value_px"] = fmt_float(reported_length_px, 6)
    output["length_axis_angle_deg"] = fmt_float(reported_angle_deg, 6)

    likelihood_values = [value for value in [base_likelihood, tip_likelihood] if value is not None]
    min_likelihood = min(likelihood_values) if len(likelihood_values) == 2 else None
    output["min_point_likelihood"] = fmt_float(min_likelihood, 6)
    output["likelihood_quality_band"] = likelihood_quality_band(min_likelihood, min_bill_point_likelihood)

    recomputed_length_px = None
    delta_px = None
    if None not in (base_x, base_y, tip_x, tip_y):
        recomputed_length_px = math.hypot(float(tip_x) - float(base_x), float(tip_y) - float(base_y))
        if recomputed_length_px <= 0:
            recompute_blockers.append("zero_length")
        if reported_length_px is not None:
            delta_px = abs(recomputed_length_px - reported_length_px)
            if delta_px > 0.02:
                recompute_blockers.append("length_recompute_mismatch")
        else:
            warnings.append("missing_reported_length_px")

    output["value_px_recomputed"] = fmt_float(recomputed_length_px, 6)
    output["value_px_recompute_delta"] = fmt_float(delta_px, 6)

    classification = classify_bill_length(
        width=width,
        height=height,
        base_x=base_x,
        base_y=base_y,
        tip_x=tip_x,
        tip_y=tip_y,
        min_likelihood=min_likelihood,
        min_bill_point_likelihood=min_bill_point_likelihood,
        path_blockers=path_blockers,
        recompute_blockers=recompute_blockers,
    )

    all_warnings = list(warnings)
    all_warnings.extend(classification["warnings"])

    if str(row.get("smart_cropper_decision", "")).strip() != "smart_cropper_ready":
        all_warnings.append("smart_cropper_decision_not_ready")

    metric_eligible = parse_bool_text(row.get("metric_eligible_bill_length"))
    if metric_eligible is False:
        all_warnings.append("smart_cropper_metric_eligible_bill_length_false")

    all_warnings.append(str(calibration.get("metric_scale_state", "")))
    for calibration_warning in calibration.get("warnings", []):
        all_warnings.append(f"calibration:{calibration_warning}")

    blockers_unique = classification["blockers"]
    warnings_unique = list(dict.fromkeys(all_warnings))

    output["metric_observation_state"] = classification["metric_observation_state"]
    output["metric_use_class"] = classification["metric_use_class"]
    output["length_px_role"] = classification["length_px_role"]
    output["range_support_class"] = classification["range_support_class"]
    output["metric_px_ready"] = str(bool(classification["metric_px_ready"]))
    output["aggregation_eligible"] = str(bool(classification["aggregation_eligible"]))
    output["lower_bound_eligible"] = str(bool(classification["lower_bound_eligible"]))
    output["autosort_feature_eligible"] = str(bool(classification["autosort_feature_eligible"]))
    output["metric_blockers"] = ";".join(blockers_unique)
    output["metric_warnings"] = ";".join(warnings_unique)
    output["point_bounds_state"] = classification["point_bounds_state"]
    output["visibility_state"] = classification["visibility_state"]
    output["whole_feature_visibility_state"] = classification["whole_feature_visibility_state"]
    output["base_outside_raw_crop_px"] = fmt_float(classification["base_outside_px"], 6)
    output["tip_outside_raw_crop_px"] = fmt_float(classification["tip_outside_px"], 6)
    output["visible_lower_bound_clip_x"] = fmt_float(classification["clip_x"], 6)
    output["visible_lower_bound_clip_y"] = fmt_float(classification["clip_y"], 6)
    output["visible_lower_bound_clip_t"] = fmt_float(classification["clip_t"], 6)
    output["value_px_visible_lower_bound"] = fmt_float(classification["visible_lower_bound"], 6)

    value_px_for_range = None
    if bool(classification["aggregation_eligible"]):
        value_px_for_range = recomputed_length_px or reported_length_px
    elif bool(classification["lower_bound_eligible"]):
        value_px_for_range = classification["visible_lower_bound"]
    elif classification["metric_observation_state"] == "diagnostic_predicted_extension":
        value_px_for_range = recomputed_length_px or reported_length_px

    output["value_px_for_range"] = fmt_float(value_px_for_range, 6)

    value_mm = None
    value_mm_visible_lower_bound = None
    value_mm_for_range = None
    if bool(calibration.get("metric_scale_ready", False)):
        if classification["metric_observation_state"] == "full_length_px_ready":
            value_mm = mm_from_px(recomputed_length_px or reported_length_px, px_per_mm)
        value_mm_visible_lower_bound = mm_from_px(classification["visible_lower_bound"], px_per_mm)
        value_mm_for_range = mm_from_px(value_px_for_range, px_per_mm)

    output["value_mm"] = fmt_float(value_mm, 6)
    output["value_mm_visible_lower_bound"] = fmt_float(value_mm_visible_lower_bound, 6)
    output["value_mm_for_range"] = fmt_float(value_mm_for_range, 6)

    if classification["metric_observation_state"] == "full_length_px_ready":
        output["metrics_decision"] = "metric_observation_recorded"
        output["metrics_note"] = "full bill length observation with scale" if calibration.get("metric_scale_ready") else "full bill length px-ready observation; metric_scale_ready false"
    elif classification["metric_observation_state"] == "partial_length_lower_bound":
        output["metrics_decision"] = "metric_observation_recorded"
        output["metrics_note"] = "partial bill lower-bound observation retained; not aggregation-ready"
    elif classification["metric_observation_state"] == "diagnostic_predicted_extension":
        output["metrics_decision"] = "metric_observation_recorded"
        output["metrics_note"] = "diagnostic predicted-extension observation retained; not biometrics-ready"
    else:
        output["metrics_decision"] = "metric_observation_rejected"
        output["metrics_note"] = "metric observation rejected: " + ";".join(blockers_unique) if blockers_unique else "metric observation rejected"

    return output


def build_range_summary(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, str, str, str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for row in observations:
        key = (
            str(row.get("source_video", "")),
            str(row.get("metric_family", "")),
            str(row.get("measurement_type", "")),
            str(row.get("metric_scale_state", "")),
            str(row.get("scale_source", "")),
            str(row.get("scale_confidence", "")),
            str(row.get("px_per_mm", "")),
            str(row.get("calibration_profile_name", "")),
        )
        grouped[key].append(row)

    summaries: List[Dict[str, Any]] = []

    for key, rows in sorted(grouped.items(), key=lambda item: str(item[0])):
        source_video, metric_family, measurement_type, scale_state, scale_source, scale_confidence, px_per_mm_text, profile_name = key

        full_px_values: List[float] = []
        partial_px_values: List[float] = []
        full_mm_values: List[float] = []
        partial_mm_values: List[float] = []

        for row in rows:
            state = str(row.get("metric_observation_state", ""))
            value_px = parse_float(row.get("value_px_for_range"))
            value_mm = parse_float(row.get("value_mm_for_range"))

            if state == "full_length_px_ready":
                if value_px is not None:
                    full_px_values.append(value_px)
                if value_mm is not None:
                    full_mm_values.append(value_mm)
            elif state == "partial_length_lower_bound":
                if value_px is not None:
                    partial_px_values.append(value_px)
                if value_mm is not None:
                    partial_mm_values.append(value_mm)

        full_px_min, full_px_mean, full_px_max = summarize_values(full_px_values)
        partial_px_min, partial_px_mean, partial_px_max = summarize_values(partial_px_values)
        full_mm_min, full_mm_mean, full_mm_max = summarize_values(full_mm_values)
        partial_mm_min, partial_mm_mean, partial_mm_max = summarize_values(partial_mm_values)

        observed_floor_px = None
        observed_ceiling_px = None
        observed_floor_mm = None
        observed_ceiling_mm = None

        if full_px_values and partial_px_values:
            observed_floor_px = max(partial_px_values)
            observed_ceiling_px = max(full_px_values)
            observed_note = "full length candidates plus partial lower-bound support"
        elif full_px_values:
            observed_floor_px = min(full_px_values)
            observed_ceiling_px = max(full_px_values)
            observed_note = "full length candidates only"
        elif partial_px_values:
            observed_floor_px = max(partial_px_values)
            observed_note = "partial lower-bound support only; no full length candidate"
        else:
            observed_note = "no usable range values"

        if full_mm_values and partial_mm_values:
            observed_floor_mm = max(partial_mm_values)
            observed_ceiling_mm = max(full_mm_values)
        elif full_mm_values:
            observed_floor_mm = min(full_mm_values)
            observed_ceiling_mm = max(full_mm_values)
        elif partial_mm_values:
            observed_floor_mm = max(partial_mm_values)

        if scale_state != "same_plane_feeder1_validated":
            observed_note += "; mm values are provisional unless same-plane calibration is validated"

        summary: Dict[str, Any] = {field: "" for field in SUMMARY_FIELDS}
        summary["metrics_schema_version"] = SCHEMA_VERSION
        summary["summary_group_key"] = "|".join(key)
        summary["source_video"] = source_video
        summary["metric_family"] = metric_family
        summary["measurement_type"] = measurement_type
        summary["metric_scale_ready"] = str(bool(px_per_mm_text))
        summary["metric_scale_state"] = scale_state
        summary["scale_source"] = scale_source
        summary["scale_confidence"] = scale_confidence
        summary["px_per_mm"] = px_per_mm_text
        summary["calibration_profile_name"] = profile_name
        summary["observation_count"] = str(len(rows))
        summary["recorded_observation_count"] = str(sum(1 for row in rows if str(row.get("metrics_decision", "")) == "metric_observation_recorded"))
        summary["full_length_count"] = str(sum(1 for row in rows if str(row.get("metric_observation_state", "")) == "full_length_px_ready"))
        summary["partial_lower_bound_count"] = str(sum(1 for row in rows if str(row.get("metric_observation_state", "")) == "partial_length_lower_bound"))
        summary["diagnostic_count"] = str(sum(1 for row in rows if str(row.get("metric_observation_state", "")) == "diagnostic_predicted_extension"))
        summary["rejected_count"] = str(sum(1 for row in rows if str(row.get("metrics_decision", "")) == "metric_observation_rejected"))
        summary["aggregation_eligible_count"] = str(sum(1 for row in rows if str(row.get("aggregation_eligible", "")).lower() == "true"))
        summary["lower_bound_eligible_count"] = str(sum(1 for row in rows if str(row.get("lower_bound_eligible", "")).lower() == "true"))
        summary["full_length_min_px"] = fmt_float(full_px_min, 6)
        summary["full_length_mean_px"] = fmt_float(full_px_mean, 6)
        summary["full_length_max_px"] = fmt_float(full_px_max, 6)
        summary["full_length_upper_percentile_px"] = fmt_float(percentile(full_px_values, 0.90), 6)
        summary["partial_lower_bound_min_px"] = fmt_float(partial_px_min, 6)
        summary["partial_lower_bound_mean_px"] = fmt_float(partial_px_mean, 6)
        summary["partial_lower_bound_max_px"] = fmt_float(partial_px_max, 6)
        summary["observed_range_floor_px"] = fmt_float(observed_floor_px, 6)
        summary["observed_range_ceiling_px"] = fmt_float(observed_ceiling_px, 6)
        summary["full_length_min_mm"] = fmt_float(full_mm_min, 6)
        summary["full_length_mean_mm"] = fmt_float(full_mm_mean, 6)
        summary["full_length_max_mm"] = fmt_float(full_mm_max, 6)
        summary["full_length_upper_percentile_mm"] = fmt_float(percentile(full_mm_values, 0.90), 6)
        summary["partial_lower_bound_min_mm"] = fmt_float(partial_mm_min, 6)
        summary["partial_lower_bound_mean_mm"] = fmt_float(partial_mm_mean, 6)
        summary["partial_lower_bound_max_mm"] = fmt_float(partial_mm_max, 6)
        summary["observed_range_floor_mm"] = fmt_float(observed_floor_mm, 6)
        summary["observed_range_ceiling_mm"] = fmt_float(observed_ceiling_mm, 6)
        summary["observed_range_note"] = observed_note
        summaries.append(summary)

    return summaries


def determine_status(observations: List[Dict[str, Any]], summaries: List[Dict[str, Any]], calibration: Dict[str, Any]) -> str:
    if not observations:
        return "FAIL_METRICS_NO_OBSERVATIONS"

    recorded_count = sum(1 for row in observations if str(row.get("metrics_decision", "")) == "metric_observation_recorded")
    full_count = sum(1 for row in observations if str(row.get("metric_observation_state", "")) == "full_length_px_ready")
    partial_count = sum(1 for row in observations if str(row.get("metric_observation_state", "")) == "partial_length_lower_bound")

    if recorded_count == 0:
        return "FAIL_METRICS_NO_RECORDED_OBSERVATIONS"

    if full_count > 0 and summaries:
        if calibration.get("metric_scale_ready"):
            if calibration.get("metric_scale_state") == "same_plane_feeder1_validated":
                return "PASS_METRICS_LENGTH_OBSERVATIONS_READY_VALIDATED_SCALE"
            return "PASS_METRICS_LENGTH_OBSERVATIONS_READY_PROVISIONAL_SCALE"
        return "PASS_METRICS_LENGTH_OBSERVATIONS_READY_UNCALIBRATED"

    if partial_count > 0 and summaries:
        return "PARTIAL_METRICS_LOWER_BOUND_ONLY"

    return "PARTIAL_METRICS_DIAGNOSTIC_ONLY"


def write_report(
    report_path: Path,
    args: argparse.Namespace,
    project_root: Path,
    input_rows: List[Dict[str, str]],
    observations: List[Dict[str, Any]],
    summaries: List[Dict[str, Any]],
    feeder_profile_info: Dict[str, Any],
    calibration: Dict[str, Any],
    status: str,
) -> None:
    decision_counts = Counter(str(row.get("metrics_decision", "")) for row in observations)
    state_counts = Counter(str(row.get("metric_observation_state", "")) for row in observations)
    use_class_counts = Counter(str(row.get("metric_use_class", "")) for row in observations)
    range_counts = Counter(str(row.get("range_support_class", "")) for row in observations)

    blocker_counts: Counter[str] = Counter()
    warning_counts: Counter[str] = Counter()

    for row in observations:
        for blocker in str(row.get("metric_blockers", "")).split(";"):
            blocker = blocker.strip()
            if blocker:
                blocker_counts[blocker] += 1
        for warning in str(row.get("metric_warnings", "")).split(";"):
            warning = warning.strip()
            if warning:
                warning_counts[warning] += 1

    settings_info = calibration.get("settings_info", {})
    outdir = Path(args.output_dir).resolve()

    lines: List[str] = []
    lines.append("Metrics | v0.1 | 2026-07-07 PDT | Birdbill promoted length metrics with app metrics feeder support path")
    lines.append(f"generated={now_text()}")
    lines.append(f"script_name={SCRIPT_NAME}")
    lines.append(f"script_version={SCRIPT_VERSION}")
    lines.append(f"component={COMPONENT}")
    lines.append(f"metrics_schema_version={SCHEMA_VERSION}")
    lines.append(f"python_executable={sys.executable}")
    lines.append("database_mutation=false")
    lines.append("durable_evidence_written=false")
    lines.append("media_files_written=0")
    lines.append("")
    lines.append("INPUTS")
    lines.append(f"project_root={project_root}")
    lines.append(f"smart_crop_manifest={Path(args.smart_crop_manifest).resolve()}")
    lines.append(f"output_dir={outdir}")
    lines.append(f"settings_ini={Path(args.settings_ini).resolve()}")
    lines.append(f"default_feeder_profile={project_root / 'metrics' / 'feeder-single.json'}")
    lines.append(f"min_bill_point_likelihood={args.min_bill_point_likelihood}")
    lines.append("")
    lines.append("CALIBRATION")
    lines.append(f"metric_scale_ready={calibration.get('metric_scale_ready')}")
    lines.append(f"metric_scale_state={calibration.get('metric_scale_state')}")
    lines.append(f"scale_source={calibration.get('scale_source')}")
    lines.append(f"scale_confidence={calibration.get('scale_confidence')}")
    lines.append(f"px_per_mm={calibration.get('px_per_mm')}")
    lines.append(f"settings_exists={settings_info.get('settings_exists')}")
    lines.append(f"settings_read_method={settings_info.get('settings_read_method')}")
    lines.append(f"settings_sections={settings_info.get('settings_sections')}")
    lines.append(f"settings_metrics_keys_seen={settings_info.get('metrics_keys_seen')}")
    lines.append(f"settings_source_key={settings_info.get('source_key')}")
    lines.append(f"settings_px_per_mm={settings_info.get('px_per_mm')}")
    lines.append(f"settings_feeder_profile={settings_info.get('feeder_profile')}")
    lines.append(f"profile_found={feeder_profile_info.get('profile_found')}")
    lines.append(f"profile_path={feeder_profile_info.get('profile_path', '')}")
    lines.append(f"profile_name={feeder_profile_info.get('profile_name', '')}")
    lines.append(f"profile_status={feeder_profile_info.get('profile_status', '')}")
    lines.append(f"profile_units={feeder_profile_info.get('profile_units', '')}")
    if feeder_profile_info.get("candidate_paths"):
        lines.append("candidate_paths_checked:")
        for path in feeder_profile_info.get("candidate_paths", []):
            lines.append(f"  {path}")
    if calibration.get("warnings"):
        lines.append("calibration_warnings:")
        for warning in calibration.get("warnings", []):
            lines.append(f"  {warning}")
    lines.append("")
    lines.append("ENABLED METRIC FAMILIES")
    lines.append("length.bill_length=enabled")
    lines.append("length.wing_length=not_enabled_no_reliable_endpoints_in_current_manifest")
    lines.append("length.body_length=not_enabled_no_reliable_endpoints_in_current_manifest")
    lines.append("")
    lines.append("SUMMARY")
    lines.append(f"input_rows={len(input_rows)}")
    lines.append(f"metric_observation_rows={len(observations)}")
    lines.append(f"range_summary_rows={len(summaries)}")
    lines.append(f"recorded_observation_count={sum(1 for row in observations if str(row.get('metrics_decision', '')) == 'metric_observation_recorded')}")
    lines.append(f"full_length_px_ready_count={sum(1 for row in observations if str(row.get('metric_observation_state', '')) == 'full_length_px_ready')}")
    lines.append(f"partial_length_lower_bound_count={sum(1 for row in observations if str(row.get('metric_observation_state', '')) == 'partial_length_lower_bound')}")
    lines.append(f"diagnostic_predicted_extension_count={sum(1 for row in observations if str(row.get('metric_observation_state', '')) == 'diagnostic_predicted_extension')}")
    lines.append(f"rejected_count={sum(1 for row in observations if str(row.get('metrics_decision', '')) == 'metric_observation_rejected')}")
    lines.append(f"aggregation_eligible_count={sum(1 for row in observations if str(row.get('aggregation_eligible', '')).lower() == 'true')}")
    lines.append(f"lower_bound_eligible_count={sum(1 for row in observations if str(row.get('lower_bound_eligible', '')).lower() == 'true')}")
    lines.append("decision_counts:")
    for key, value in sorted(decision_counts.items()):
        lines.append(f"  {key}={value}")
    lines.append("metric_observation_state_counts:")
    for key, value in sorted(state_counts.items()):
        lines.append(f"  {key}={value}")
    lines.append("metric_use_class_counts:")
    for key, value in sorted(use_class_counts.items()):
        lines.append(f"  {key}={value}")
    lines.append("range_support_class_counts:")
    for key, value in sorted(range_counts.items()):
        lines.append(f"  {key}={value}")
    lines.append("blocker_counts:")
    if blocker_counts:
        for key, value in sorted(blocker_counts.items()):
            lines.append(f"  {key}={value}")
    else:
        lines.append("  none=0")
    lines.append("warning_counts_top:")
    if warning_counts:
        for key, value in sorted(warning_counts.items(), key=lambda item: (-item[1], item[0]))[:20]:
            lines.append(f"  {key}={value}")
    else:
        lines.append("  none=0")
    lines.append("")
    lines.append("RANGE SUMMARY PREVIEW")
    for row in summaries:
        lines.append(
            "  "
            + f"measurement_type={row.get('measurement_type')} "
            + f"full_count={row.get('full_length_count')} "
            + f"partial_count={row.get('partial_lower_bound_count')} "
            + f"full_max_px={row.get('full_length_max_px')} "
            + f"full_max_mm={row.get('full_length_max_mm')} "
            + f"partial_max_px={row.get('partial_lower_bound_max_px')} "
            + f"partial_max_mm={row.get('partial_lower_bound_max_mm')} "
            + f"range_floor_px={row.get('observed_range_floor_px')} "
            + f"range_ceiling_px={row.get('observed_range_ceiling_px')} "
            + f"range_floor_mm={row.get('observed_range_floor_mm')} "
            + f"range_ceiling_mm={row.get('observed_range_ceiling_mm')} "
            + f"scale_state={row.get('metric_scale_state')}"
        )
    lines.append("")
    lines.append("OUTPUTS")
    lines.append(f"metric_observations_csv={outdir / 'metric-observations.csv'}")
    lines.append(f"metric_range_summary_csv={outdir / 'metric-range-summary.csv'}")
    lines.append(f"metrics_report={report_path}")
    lines.append(f"manifest_json={outdir / 'manifest.json'}")
    lines.append("")
    lines.append("FINAL STATUS")
    lines.append(f"status={status}")
    lines.append("database_mutation=false")
    lines.append("durable_evidence_written=false")
    lines.append("media_files_written=0")
    lines.append("promotion_state=promoted_app_candidate_from_debug_v0.7")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Birdbill length metrics from SmartCropper manifest.")
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--smart-crop-manifest", default=str(DEFAULT_SMART_CROP_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--settings-ini", default=str(DEFAULT_SETTINGS_INI))
    parser.add_argument("--feeder-profile", default="")
    parser.add_argument("--px-per-mm", default="")
    parser.add_argument("--scale-state", default="")
    parser.add_argument("--scale-source", default="")
    parser.add_argument("--scale-confidence", default="")
    parser.add_argument("--min-bill-point-likelihood", type=float, default=0.10)
    parser.add_argument("--clear-output", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    manifest_path = Path(args.smart_crop_manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    settings_path = Path(args.settings_ini).resolve()

    observations_path = output_dir / "metric-observations.csv"
    summary_path = output_dir / "metric-range-summary.csv"
    report_path = output_dir / "metrics-report.txt"
    manifest_json_path = output_dir / "manifest.json"

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.clear_output:
        for path in [observations_path, summary_path, report_path, manifest_json_path]:
            if path.exists():
                path.unlink()

    print(f"{COMPONENT} {SCRIPT_VERSION}")
    print(f"script = {Path(__file__).resolve()}")
    print(f"python = {sys.executable}")
    print(f"project_root = {project_root}")
    print(f"smart_crop_manifest = {manifest_path}")
    print(f"output_dir = {output_dir}")
    print(f"settings_ini = {settings_path}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("media_files_written = 0")
    print()

    settings_info = load_settings(settings_path)
    requested_profile = resolve_profile_path(args, settings_info, project_root)
    feeder_profile_info = load_feeder_profile(requested_profile, project_root)
    calibration = resolve_calibration(args, settings_info, feeder_profile_info)

    if not manifest_path.exists():
        status = "FAIL_MISSING_SMART_CROP_MANIFEST"
        write_report(report_path, args, project_root, [], [], [], feeder_profile_info, calibration, status)
        write_json(manifest_json_path, {
            "script_name": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "component": COMPONENT,
            "metrics_schema_version": SCHEMA_VERSION,
            "status": status,
            "database_mutation": False,
            "durable_evidence_written": False,
            "media_files_written": 0,
            "error": f"missing smart crop manifest: {manifest_path}",
        })
        print(f"status = {status}")
        print(f"report = {report_path}")
        return 2

    input_rows = read_csv(manifest_path)
    observations = [
        make_bill_length_observation(
            row=dict(row),
            row_index=index,
            min_bill_point_likelihood=args.min_bill_point_likelihood,
            feeder_profile_info=feeder_profile_info,
            calibration=calibration,
        )
        for index, row in enumerate(input_rows, start=1)
    ]

    summaries = build_range_summary(observations)
    status = determine_status(observations, summaries, calibration)

    write_csv(observations_path, observations, OBSERVATION_FIELDS)
    write_csv(summary_path, summaries, SUMMARY_FIELDS)
    write_report(report_path, args, project_root, input_rows, observations, summaries, feeder_profile_info, calibration, status)

    full_ready_count = sum(1 for row in observations if str(row.get("metric_observation_state", "")) == "full_length_px_ready")
    lower_bound_count = sum(1 for row in observations if str(row.get("metric_observation_state", "")) == "partial_length_lower_bound")
    diagnostic_count = sum(1 for row in observations if str(row.get("metric_observation_state", "")) == "diagnostic_predicted_extension")
    rejected_count = sum(1 for row in observations if str(row.get("metrics_decision", "")) == "metric_observation_rejected")
    aggregation_count = sum(1 for row in observations if str(row.get("aggregation_eligible", "")).lower() == "true")
    lower_bound_eligible_count = sum(1 for row in observations if str(row.get("lower_bound_eligible", "")).lower() == "true")

    manifest_data = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "component": COMPONENT,
        "promotion_source": "Metrics-v0.7.py PASS_METRICS_LENGTH_OBSERVATIONS_READY_PROVISIONAL_SCALE",
        "metrics_schema_version": SCHEMA_VERSION,
        "generated": now_text(),
        "status": status,
        "database_mutation": False,
        "durable_evidence_written": False,
        "media_files_written": 0,
        "project_root": str(project_root),
        "smart_crop_manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "settings_ini": str(settings_path),
        "settings_info": settings_info,
        "default_feeder_profile": str(project_root / "app" / "metrics" / "feeder-single.json"),
        "feeder_profile": feeder_profile_info,
        "calibration": calibration,
        "path_contract": {
            "metrics_support_dir": str(project_root / "app" / "metrics"),
            "feeder_profile_expected": str(project_root / "app" / "metrics" / "feeder-single.json"),
            "legacy_external_feeder_profiles": "ignored",
        },
        "enabled_metric_families": {
            "length.bill_length": "enabled",
            "length.wing_length": "not_enabled_no_reliable_endpoints_in_current_manifest",
            "length.body_length": "not_enabled_no_reliable_endpoints_in_current_manifest",
        },
        "counts": {
            "input_rows": len(input_rows),
            "metric_observation_rows": len(observations),
            "range_summary_rows": len(summaries),
            "full_length_px_ready_count": full_ready_count,
            "partial_length_lower_bound_count": lower_bound_count,
            "diagnostic_predicted_extension_count": diagnostic_count,
            "rejected_count": rejected_count,
            "aggregation_eligible_count": aggregation_count,
            "lower_bound_eligible_count": lower_bound_eligible_count,
        },
        "outputs": {
            "metric_observations_csv": str(observations_path),
            "metric_range_summary_csv": str(summary_path),
            "metrics_report": str(report_path),
            "manifest_json": str(manifest_json_path),
        },
    }
    write_json(manifest_json_path, manifest_data)

    print(f"settings_exists = {settings_info.get('settings_exists')}")
    print(f"settings_read_method = {settings_info.get('settings_read_method')}")
    print(f"settings_sections = {settings_info.get('settings_sections')}")
    print(f"settings_metrics_keys_seen = {settings_info.get('metrics_keys_seen')}")
    print(f"settings_source_key = {settings_info.get('source_key')}")
    print(f"settings_px_per_mm = {settings_info.get('px_per_mm')}")
    print(f"settings_feeder_profile = {settings_info.get('feeder_profile')}")
    print(f"input_rows = {len(input_rows)}")
    print(f"metric_observation_rows = {len(observations)}")
    print(f"range_summary_rows = {len(summaries)}")
    print(f"full_length_px_ready_count = {full_ready_count}")
    print(f"partial_length_lower_bound_count = {lower_bound_count}")
    print(f"diagnostic_predicted_extension_count = {diagnostic_count}")
    print(f"rejected_count = {rejected_count}")
    print(f"aggregation_eligible_count = {aggregation_count}")
    print(f"lower_bound_eligible_count = {lower_bound_eligible_count}")
    print(f"metric_scale_ready = {str(bool(calibration.get('metric_scale_ready'))).lower()}")
    print(f"metric_scale_state = {calibration.get('metric_scale_state')}")
    print(f"scale_source = {calibration.get('scale_source')}")
    print(f"scale_confidence = {calibration.get('scale_confidence')}")
    print(f"px_per_mm = {calibration.get('px_per_mm')}")
    print(f"feeder_profile_path = {feeder_profile_info.get('profile_path', '')}")
    print("length.bill_length = enabled")
    print("length.wing_length = not_enabled_no_reliable_endpoints_in_current_manifest")
    print("length.body_length = not_enabled_no_reliable_endpoints_in_current_manifest")
    print(f"metric_observations_csv = {observations_path}")
    print(f"metric_range_summary_csv = {summary_path}")
    print(f"metrics_report = {report_path}")
    print(f"manifest_json = {manifest_json_path}")
    print(f"status = {status}")

    if status.startswith("FAIL"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
