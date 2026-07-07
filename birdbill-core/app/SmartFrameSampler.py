# SmartFrameSampler.py | v0.4 | 2026-07-07 PDT | Birdbill early pipeline sampler + raw-crop candidate gate

from __future__ import annotations

import argparse
import configparser
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCRIPT_NAME = "SmartFrameSampler.py"
SCRIPT_VERSION = "v0.4"
REWRITE_STEP = "early-pipeline-promotion-candidate"
COMPONENT_NAME = "SmartFrameSampler"

RAW_CROP_SCORING_POLICY = "raw_crop_candidate_retention_v0.4"


@dataclass(frozen=True)
class SamplerSettings:
    sample_every_seconds: float = 2.0
    max_frame_records: int = 120
    burst_offsets_seconds: tuple[float, ...] = (-0.12, 0.0, 0.12)
    preview_frame_limit: int = 24
    jpeg_quality: int = 92
    clear_output: bool = False
    source_media_context: str = "app_sampler"


@dataclass(frozen=True)
class DetectorInputSettings:
    max_detector_frames: int = 24
    selection_policy: str = "balanced_preview_sequence"
    detector_jpeg_quality: int = 92
    crop_padding_px: int = 20
    detector_confidence_threshold: float = 0.15
    detector_device: str = "cpu"
    detector_model_path: str = r"D:\birdbill\modules\megadetector\models\MDV6b-yolov9-c.pt"
    run_megadetector: bool = False
    megadetector_output_dir: str = ""


@dataclass(frozen=True)
class RawCropScoringSettings:
    best_score_min: float = 75.0
    usable_score_min: float = 55.0
    weak_debug_score_min: float = 30.0

    animal_role_points: float = 18.0

    high_confidence_min: float = 0.70
    medium_confidence_min: float = 0.40
    low_confidence_min: float = 0.15
    high_confidence_points: float = 30.0
    medium_confidence_points: float = 24.0
    low_confidence_points: float = 16.0
    very_low_confidence_points: float = 8.0

    large_bbox_min_px: int = 160
    medium_bbox_min_px: int = 80
    small_bbox_min_px: int = 40
    large_bbox_points: float = 18.0
    medium_bbox_points: float = 14.0
    small_bbox_points: float = 8.0
    very_small_bbox_points: float = 2.0

    large_area_min_px: int = 30000
    moderate_area_min_px: int = 8000
    small_area_min_px: int = 1500
    large_area_points: float = 10.0
    moderate_area_points: float = 7.0
    small_area_points: float = 3.0

    crop_available_points: float = 16.0
    crop_readable_points: float = 4.0
    usable_crop_dimension_min_px: int = 120
    usable_crop_dimension_points: float = 5.0
    small_crop_dimension_points: float = 2.0

    sharpness_ok_min: float = 100.0
    sharpness_ok_points: float = 4.0
    sharpness_low_points: float = 1.0

    allow_person_context: bool = True
    penalize_person_dominant_frames: bool = False
    person_dominance_area_ratio: float = 0.60
    person_dominance_penalty: float = 12.0

    dlc_candidate_min_decision: str = "usable"
    mmpose_candidate_min_decision: str = "weak_debug"


@dataclass
class FrameRecord:
    frame_id: str
    sequence_id: str
    source_video: str
    source_media_context: str
    source_video_is_canonical: bool
    source_video_available: bool
    source_frame_index: int
    frame_time_seconds: float
    anchor_index: int
    anchor_frame_index: int
    anchor_time_seconds: float
    burst_index: int
    burst_offset_seconds: float
    offset_from_anchor_frames: int
    is_anchor: bool
    frame_path: str
    frame_materialized: bool
    frame_cache_role: str
    purgeable: bool
    width: int
    height: int
    fps: float
    duration_seconds: float
    total_source_frames: int
    sync_session_id: str
    synced_time_ms: str
    calibration_id: str
    feeder_zone_id: str


def utc_timestamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def local_run_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sanitize_name(value: str, fallback: str = "source") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip(".-_")
    return cleaned or fallback


def deterministic_id(prefix: str, *parts: Any) -> str:
    text = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def bool_from_text(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_float_tuple(value: str | None, default: tuple[float, ...]) -> tuple[float, ...]:
    if not value:
        return default
    parsed: list[float] = []
    for piece in value.replace(";", ",").split(","):
        piece = piece.strip()
        if piece:
            parsed.append(float(piece))
    return tuple(parsed) if parsed else default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value))
    except Exception:
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value)))
    except Exception:
        return default


def clean(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def pick(row: dict[str, Any] | None, names: list[str], default: str = "") -> Any:
    if not isinstance(row, dict):
        return default
    for name in names:
        if name in row and str(row.get(name, "")).strip() != "":
            return row.get(name)
    return default


def open_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except Exception as exc:
        raise RuntimeError(
            "OpenCV import failed. SmartFrameSampler needs cv2 in the selected Python environment. "
            f"Original error: {exc}"
        ) from exc


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_settings(
    settings_path: Path | None,
    cli: argparse.Namespace,
) -> tuple[SamplerSettings, DetectorInputSettings, RawCropScoringSettings]:
    sampler_defaults = SamplerSettings()
    detector_defaults = DetectorInputSettings()
    scoring_defaults = RawCropScoringSettings()

    config = configparser.ConfigParser()
    if settings_path is not None and settings_path.exists():
        config.read(settings_path, encoding="utf-8")

    video = config["video"] if config.has_section("video") else {}
    detector = config["detector_input"] if config.has_section("detector_input") else {}
    scoring = config["raw_crop_scoring"] if config.has_section("raw_crop_scoring") else {}

    sampler_settings = SamplerSettings(
        sample_every_seconds=float(
            cli.sample_every_seconds
            if cli.sample_every_seconds is not None
            else video.get("sample_every_seconds", sampler_defaults.sample_every_seconds)
        ),
        max_frame_records=int(
            cli.max_frame_records
            if cli.max_frame_records is not None
            else video.get("max_frame_records", video.get("max_frames_per_video", sampler_defaults.max_frame_records))
        ),
        burst_offsets_seconds=parse_float_tuple(
            cli.burst_offsets_seconds
            if cli.burst_offsets_seconds is not None
            else video.get("burst_offsets_seconds", None),
            sampler_defaults.burst_offsets_seconds,
        ),
        preview_frame_limit=int(
            cli.preview_frame_limit
            if cli.preview_frame_limit is not None
            else video.get("preview_frame_limit", sampler_defaults.preview_frame_limit)
        ),
        jpeg_quality=int(
            cli.jpeg_quality
            if cli.jpeg_quality is not None
            else video.get("jpeg_quality", sampler_defaults.jpeg_quality)
        ),
        clear_output=bool_from_text(
            str(cli.clear_output) if cli.clear_output else video.get("clear_old_sampled_frames", None),
            sampler_defaults.clear_output,
        ),
        source_media_context=cli.source_media_context
        or video.get("source_media_context", sampler_defaults.source_media_context),
    )

    detector_settings = DetectorInputSettings(
        max_detector_frames=int(
            cli.max_detector_frames
            if cli.max_detector_frames is not None
            else detector.get("max_detector_frames", detector_defaults.max_detector_frames)
        ),
        selection_policy=cli.detector_selection_policy
        or detector.get("selection_policy", detector_defaults.selection_policy),
        detector_jpeg_quality=int(
            cli.detector_jpeg_quality
            if cli.detector_jpeg_quality is not None
            else detector.get("detector_jpeg_quality", detector_defaults.detector_jpeg_quality)
        ),
        crop_padding_px=int(
            cli.crop_padding_px
            if cli.crop_padding_px is not None
            else detector.get("crop_padding_px", detector_defaults.crop_padding_px)
        ),
        detector_confidence_threshold=float(
            cli.detector_confidence_threshold
            if cli.detector_confidence_threshold is not None
            else detector.get("detector_confidence_threshold", detector_defaults.detector_confidence_threshold)
        ),
        detector_device=cli.detector_device
        or detector.get("detector_device", detector_defaults.detector_device),
        detector_model_path=cli.detector_model
        or detector.get("detector_model_path", detector_defaults.detector_model_path),
        run_megadetector=bool_from_text(
            str(cli.run_megadetector) if cli.run_megadetector else detector.get("run_megadetector", None),
            detector_defaults.run_megadetector,
        ),
        megadetector_output_dir=cli.megadetector_output_dir
        or detector.get("megadetector_output_dir", detector_defaults.megadetector_output_dir),
    )

    scoring_settings = RawCropScoringSettings(
        best_score_min=float(scoring.get("best_score_min", scoring_defaults.best_score_min)),
        usable_score_min=float(scoring.get("usable_score_min", scoring_defaults.usable_score_min)),
        weak_debug_score_min=float(scoring.get("weak_debug_score_min", scoring_defaults.weak_debug_score_min)),
        animal_role_points=float(scoring.get("animal_role_points", scoring_defaults.animal_role_points)),
        high_confidence_min=float(scoring.get("high_confidence_min", scoring_defaults.high_confidence_min)),
        medium_confidence_min=float(scoring.get("medium_confidence_min", scoring_defaults.medium_confidence_min)),
        low_confidence_min=float(scoring.get("low_confidence_min", scoring_defaults.low_confidence_min)),
        high_confidence_points=float(scoring.get("high_confidence_points", scoring_defaults.high_confidence_points)),
        medium_confidence_points=float(scoring.get("medium_confidence_points", scoring_defaults.medium_confidence_points)),
        low_confidence_points=float(scoring.get("low_confidence_points", scoring_defaults.low_confidence_points)),
        very_low_confidence_points=float(scoring.get("very_low_confidence_points", scoring_defaults.very_low_confidence_points)),
        large_bbox_min_px=int(scoring.get("large_bbox_min_px", scoring_defaults.large_bbox_min_px)),
        medium_bbox_min_px=int(scoring.get("medium_bbox_min_px", scoring_defaults.medium_bbox_min_px)),
        small_bbox_min_px=int(scoring.get("small_bbox_min_px", scoring_defaults.small_bbox_min_px)),
        large_bbox_points=float(scoring.get("large_bbox_points", scoring_defaults.large_bbox_points)),
        medium_bbox_points=float(scoring.get("medium_bbox_points", scoring_defaults.medium_bbox_points)),
        small_bbox_points=float(scoring.get("small_bbox_points", scoring_defaults.small_bbox_points)),
        very_small_bbox_points=float(scoring.get("very_small_bbox_points", scoring_defaults.very_small_bbox_points)),
        large_area_min_px=int(scoring.get("large_area_min_px", scoring_defaults.large_area_min_px)),
        moderate_area_min_px=int(scoring.get("moderate_area_min_px", scoring_defaults.moderate_area_min_px)),
        small_area_min_px=int(scoring.get("small_area_min_px", scoring_defaults.small_area_min_px)),
        large_area_points=float(scoring.get("large_area_points", scoring_defaults.large_area_points)),
        moderate_area_points=float(scoring.get("moderate_area_points", scoring_defaults.moderate_area_points)),
        small_area_points=float(scoring.get("small_area_points", scoring_defaults.small_area_points)),
        crop_available_points=float(scoring.get("crop_available_points", scoring_defaults.crop_available_points)),
        crop_readable_points=float(scoring.get("crop_readable_points", scoring_defaults.crop_readable_points)),
        usable_crop_dimension_min_px=int(scoring.get("usable_crop_dimension_min_px", scoring_defaults.usable_crop_dimension_min_px)),
        usable_crop_dimension_points=float(scoring.get("usable_crop_dimension_points", scoring_defaults.usable_crop_dimension_points)),
        small_crop_dimension_points=float(scoring.get("small_crop_dimension_points", scoring_defaults.small_crop_dimension_points)),
        sharpness_ok_min=float(scoring.get("sharpness_ok_min", scoring_defaults.sharpness_ok_min)),
        sharpness_ok_points=float(scoring.get("sharpness_ok_points", scoring_defaults.sharpness_ok_points)),
        sharpness_low_points=float(scoring.get("sharpness_low_points", scoring_defaults.sharpness_low_points)),
        allow_person_context=bool_from_text(scoring.get("allow_person_context", None), scoring_defaults.allow_person_context),
        penalize_person_dominant_frames=bool_from_text(
            scoring.get("penalize_person_dominant_frames", None),
            scoring_defaults.penalize_person_dominant_frames,
        ),
        person_dominance_area_ratio=float(scoring.get("person_dominance_area_ratio", scoring_defaults.person_dominance_area_ratio)),
        person_dominance_penalty=float(scoring.get("person_dominance_penalty", scoring_defaults.person_dominance_penalty)),
        dlc_candidate_min_decision=scoring.get("dlc_candidate_min_decision", scoring_defaults.dlc_candidate_min_decision),
        mmpose_candidate_min_decision=scoring.get("mmpose_candidate_min_decision", scoring_defaults.mmpose_candidate_min_decision),
    )

    validate_settings(sampler_settings, detector_settings, scoring_settings)
    return sampler_settings, detector_settings, scoring_settings


def validate_settings(
    sampler: SamplerSettings,
    detector: DetectorInputSettings,
    scoring: RawCropScoringSettings,
) -> None:
    if sampler.sample_every_seconds <= 0:
        raise ValueError("sample_every_seconds must be greater than zero")
    if sampler.max_frame_records <= 0:
        raise ValueError("max_frame_records must be greater than zero")
    if sampler.preview_frame_limit < 0:
        raise ValueError("preview_frame_limit must be zero or greater")
    if not 1 <= sampler.jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be between 1 and 100")
    if detector.max_detector_frames <= 0:
        raise ValueError("max_detector_frames must be greater than zero")
    if not 1 <= detector.detector_jpeg_quality <= 100:
        raise ValueError("detector_jpeg_quality must be between 1 and 100")
    if detector.crop_padding_px < 0:
        raise ValueError("crop_padding_px must be zero or greater")
    if not 0 <= detector.detector_confidence_threshold <= 1:
        raise ValueError("detector_confidence_threshold must be between zero and one")
    if not (scoring.best_score_min >= scoring.usable_score_min >= scoring.weak_debug_score_min):
        raise ValueError("scoring thresholds must satisfy best >= usable >= weak_debug")


def read_video_metadata(source_video: Path) -> dict[str, Any]:
    cv2 = open_cv2()
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video: {source_video}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()

    if fps <= 0:
        raise RuntimeError(f"Video FPS was not readable or was zero: {source_video}")
    if total_frames <= 0:
        raise RuntimeError(f"Video frame count was not readable or was zero: {source_video}")

    return {
        "fps": fps,
        "total_source_frames": total_frames,
        "duration_seconds": total_frames / fps,
        "width": width,
        "height": height,
    }


def choose_anchor_times(duration_seconds: float, sample_every_seconds: float, max_anchors: int) -> list[float]:
    if duration_seconds <= 0:
        return [0.0]

    raw_times: list[float] = []
    t = 0.0
    while t < duration_seconds:
        raw_times.append(t)
        t += sample_every_seconds

    if not raw_times:
        raw_times = [0.0]

    last_reasonable = max(0.0, duration_seconds - 0.001)
    if last_reasonable - raw_times[-1] >= sample_every_seconds * 0.50:
        raw_times.append(last_reasonable)

    if len(raw_times) <= max_anchors:
        return raw_times

    if max_anchors == 1:
        return [raw_times[0]]

    return [raw_times[round(i * (len(raw_times) - 1) / (max_anchors - 1))] for i in range(max_anchors)]


def build_frame_plan(source_video: Path, settings: SamplerSettings, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    fps = float(metadata["fps"])
    total_frames = int(metadata["total_source_frames"])
    duration_seconds = float(metadata["duration_seconds"])

    burst_offsets = settings.burst_offsets_seconds or (0.0,)
    max_anchors = max(1, math.ceil(settings.max_frame_records / max(1, len(burst_offsets))))
    anchors = choose_anchor_times(duration_seconds, settings.sample_every_seconds, max_anchors=max_anchors)

    planned: list[dict[str, Any]] = []
    seen_frame_indexes: set[int] = set()
    source_id = sanitize_name(source_video.stem)

    for anchor_index, anchor_time in enumerate(anchors):
        anchor_frame_index = min(max(int(round(anchor_time * fps)), 0), total_frames - 1)
        sequence_id = f"seq-{anchor_index + 1:05d}"

        for burst_index, offset in enumerate(burst_offsets):
            target_time = min(max(anchor_time + offset, 0.0), max(0.0, duration_seconds - 0.001))
            frame_index = int(round(target_time * fps))
            frame_index = min(max(frame_index, 0), total_frames - 1)

            if frame_index in seen_frame_indexes:
                continue
            seen_frame_indexes.add(frame_index)

            exact_time = frame_index / fps
            planned.append(
                {
                    "frame_id": f"{source_id}-frame-{frame_index:08d}",
                    "sequence_id": sequence_id,
                    "source_frame_index": frame_index,
                    "frame_time_seconds": exact_time,
                    "anchor_index": anchor_index,
                    "anchor_frame_index": anchor_frame_index,
                    "anchor_time_seconds": anchor_time,
                    "burst_index": burst_index,
                    "burst_offset_seconds": offset,
                    "offset_from_anchor_frames": frame_index - anchor_frame_index,
                    "is_anchor": frame_index == anchor_frame_index,
                }
            )

            if len(planned) >= settings.max_frame_records:
                return planned

    return planned


def materialize_frame(source_video: Path, source_frame_index: int, output_path: Path, jpeg_quality: int) -> tuple[bool, str]:
    cv2 = open_cv2()
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        return False, "could not open source video"
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(source_frame_index))
        ok, frame = cap.read()
    finally:
        cap.release()

    if not ok or frame is None:
        return False, f"could not read source frame {source_frame_index}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = cv2.imwrite(str(output_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not written:
        return False, f"could not write frame: {output_path}"

    return True, ""


def materialize_preview_frames(
    source_video: Path,
    output_frames_dir: Path,
    planned: list[dict[str, Any]],
    settings: SamplerSettings,
) -> dict[int, str]:
    if settings.preview_frame_limit <= 0:
        return {}

    output_frames_dir.mkdir(parents=True, exist_ok=True)
    materialized: dict[int, str] = {}

    for item in planned[: settings.preview_frame_limit]:
        frame_index = int(item["source_frame_index"])
        frame_path = output_frames_dir / f"{item['frame_id']}.jpg"
        ok, _message = materialize_frame(source_video, frame_index, frame_path, settings.jpeg_quality)
        if ok:
            materialized[frame_index] = str(frame_path)

    return materialized


def make_run_id(source_video: Path, provided: str | None) -> str:
    if provided:
        return sanitize_name(provided, fallback=f"SmartFrameSampler-{local_run_stamp()}")
    return f"{sanitize_name(source_video.stem)}-{local_run_stamp()}"


def prepare_output_dir(output_root: Path, run_id: str, clear_output: bool) -> Path:
    output_dir = output_root / run_id
    if output_dir.exists() and clear_output:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def row_identity(row: dict[str, Any]) -> str:
    frame_id = clean(pick(row, ["frame_id", "sampled_frame_id"]))
    if frame_id:
        return "frame_id:" + frame_id
    source_frame_index = clean(pick(row, ["source_frame_index"]))
    if source_frame_index:
        return "source_frame_index:" + source_frame_index
    return deterministic_id("row", row)


def row_sequence_id(row: dict[str, Any]) -> str:
    return clean(pick(row, ["sequence_id"]), "sequence-unknown")


def row_source_frame_index(row: dict[str, Any]) -> int:
    return as_int(pick(row, ["source_frame_index"]), 0)


def row_offset_abs(row: dict[str, Any]) -> int:
    offset = clean(pick(row, ["offset_from_anchor_frames"]))
    if offset != "":
        return abs(as_int(offset, 999999))
    anchor = clean(pick(row, ["anchor_frame_index"]))
    frame = clean(pick(row, ["source_frame_index"]))
    if anchor and frame:
        return abs(as_int(frame, 0) - as_int(anchor, 0))
    return 999999


def row_is_anchor(row: dict[str, Any]) -> bool:
    return row_offset_abs(row) == 0


def group_rows_for_selection(rows: list[dict[str, Any]], sort_key=None) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row_sequence_id(row), []).append(row)
    if sort_key is not None:
        for key in list(groups.keys()):
            groups[key] = sorted(groups[key], key=sort_key)
    return groups


def round_robin_groups(
    groups: dict[str, list[dict[str, Any]]],
    max_count: int,
    seen: set[str],
    reason: str,
    selected: list[dict[str, Any]],
) -> int:
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


def select_detector_sample_rows(
    frame_rows: list[dict[str, Any]],
    max_count: int,
) -> list[dict[str, Any]]:
    max_count = max(1, int(max_count))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    rows_with_existing_preview: list[dict[str, Any]] = []
    anchor_rows: list[dict[str, Any]] = []
    near_anchor_rows: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    for row in frame_rows:
        all_rows.append(row)
        if clean(row.get("frame_path")) and Path(clean(row.get("frame_path"))).exists():
            rows_with_existing_preview.append(row)
        if row_is_anchor(row):
            anchor_rows.append(row)
        if row_offset_abs(row) <= 3:
            near_anchor_rows.append(row)

    round_robin_groups(
        group_rows_for_selection(rows_with_existing_preview, sort_key=lambda r: (row_offset_abs(r), row_source_frame_index(r))),
        max_count,
        seen,
        "existing_sampler_preview_round_robin",
        selected,
    )
    if len(selected) < max_count:
        round_robin_groups(
            group_rows_for_selection(anchor_rows, sort_key=lambda r: row_source_frame_index(r)),
            max_count,
            seen,
            "anchor_center_round_robin",
            selected,
        )
    if len(selected) < max_count:
        round_robin_groups(
            group_rows_for_selection(near_anchor_rows, sort_key=lambda r: (row_offset_abs(r), row_source_frame_index(r))),
            max_count,
            seen,
            "near_anchor_round_robin",
            selected,
        )
    if len(selected) < max_count:
        round_robin_groups(
            group_rows_for_selection(all_rows, sort_key=lambda r: (row_offset_abs(r), row_source_frame_index(r))),
            max_count,
            seen,
            "sequence_balanced_coverage",
            selected,
        )

    selected = sorted(selected, key=lambda item: (row_sequence_id(item["row"]), row_source_frame_index(item["row"])))
    return selected


def make_detector_input_rows(
    source_video: Path,
    output_dir: Path,
    frame_rows: list[dict[str, Any]],
    detector_settings: DetectorInputSettings,
) -> tuple[list[dict[str, Any]], int]:
    selected = select_detector_sample_rows(frame_rows, detector_settings.max_detector_frames)
    detector_dir = output_dir / "detector-input-frames"
    detector_rows: list[dict[str, Any]] = []
    media_written = 0

    for item_index, item in enumerate(selected):
        frame_row = item["row"]
        frame_id = clean(frame_row.get("frame_id"), f"frame-{item_index:05d}")
        detector_input_id = deterministic_id("detector-input", frame_id, frame_row.get("source_frame_index", ""))
        existing_path = clean(frame_row.get("frame_path"))
        detector_frame_path = ""

        if existing_path and Path(existing_path).exists():
            detector_frame_path = existing_path
            materialized_now = False
        else:
            detector_frame_path = str(detector_dir / f"{frame_id}.jpg")
            ok, message = materialize_frame(
                source_video=source_video,
                source_frame_index=as_int(frame_row.get("source_frame_index"), 0),
                output_path=Path(detector_frame_path),
                jpeg_quality=detector_settings.detector_jpeg_quality,
            )
            materialized_now = ok
            if ok:
                media_written += 1
            else:
                detector_frame_path = ""
                frame_row["detector_input_error"] = message

        detector_rows.append(
            {
                "detector_input_id": detector_input_id,
                "frame_id": frame_id,
                "sequence_id": clean(frame_row.get("sequence_id")),
                "source_video": clean(frame_row.get("source_video")),
                "source_media_context": clean(frame_row.get("source_media_context")),
                "source_frame_index": clean(frame_row.get("source_frame_index")),
                "camera_local_time_seconds": clean(frame_row.get("frame_time_seconds")),
                "frame_time_seconds": clean(frame_row.get("frame_time_seconds")),
                "anchor_frame_index": clean(frame_row.get("anchor_frame_index")),
                "offset_from_anchor_frames": clean(frame_row.get("offset_from_anchor_frames")),
                "detector_input_frame_path": detector_frame_path,
                "detector_input_materialized_now": bool_text(materialized_now),
                "selection_reason": item["reason"],
                "selection_policy": detector_settings.selection_policy,
                "width": clean(frame_row.get("width")),
                "height": clean(frame_row.get("height")),
                "fps": clean(frame_row.get("fps")),
                "duration_seconds": clean(frame_row.get("duration_seconds")),
                "sync_session_id": clean(frame_row.get("sync_session_id")),
                "synced_time_ms": clean(frame_row.get("synced_time_ms")),
                "calibration_id": clean(frame_row.get("calibration_id")),
                "feeder_zone_id": clean(frame_row.get("feeder_zone_id")),
                "database_mutation": "false",
                "durable_evidence_written": "false",
                "purgeable": "true",
            }
        )

    return detector_rows, media_written


def normalize_detection_role(class_name: Any) -> str:
    text = str(class_name or "").strip().lower()
    if "animal" in text or "bird" in text:
        return "animal"
    if "person" in text or "human" in text:
        return "person"
    if "vehicle" in text or "car" in text or "truck" in text or "bus" in text:
        return "vehicle"
    return "other"


def infer_with_ultralytics(model: Any, image_path: Path, confidence_threshold: float, device: str) -> list[dict[str, Any]]:
    results = model(str(image_path), conf=float(confidence_threshold), device=device, verbose=False)
    detections: list[dict[str, Any]] = []

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
        detections.append(
            {
                "class_id": cls,
                "class_name": class_name,
                "confidence": conf,
                "x1": float(xyxy[0]),
                "y1": float(xyxy[1]),
                "x2": float(xyxy[2]),
                "y2": float(xyxy[3]),
            }
        )

    return detections


def export_raw_crop(
    image_path: Path,
    bbox: dict[str, Any],
    crop_path: Path,
    padding_px: int,
    jpeg_quality: int,
) -> tuple[bool, int, str]:
    cv2 = open_cv2()
    image = cv2.imread(str(image_path))
    if image is None:
        return False, 0, "could not read image for crop export"

    height, width = image.shape[:2]
    x1 = max(0, int(round(as_float(bbox["x1"]))) - int(padding_px))
    y1 = max(0, int(round(as_float(bbox["y1"]))) - int(padding_px))
    x2 = min(width, int(round(as_float(bbox["x2"]))) + int(padding_px))
    y2 = min(height, int(round(as_float(bbox["y2"]))) + int(padding_px))

    if x2 <= x1 or y2 <= y1:
        return False, 0, "invalid padded crop bounds"

    crop = image[y1:y2, x1:x2]
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(crop_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        return False, 0, "could not write crop"

    return True, crop_path.stat().st_size, ""


def run_megadetector_stage(
    output_dir: Path,
    detector_rows: list[dict[str, Any]],
    detector_settings: DetectorInputSettings,
) -> dict[str, Any]:
    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "MegaDetector stage requested, but ultralytics import failed in this Python environment. "
            f"Original error: {exc}"
        ) from exc

    model_path = Path(detector_settings.detector_model_path)
    if not model_path.exists():
        raise FileNotFoundError(f"MegaDetector model not found: {model_path}")

    model = YOLO(str(model_path))
    detections: list[dict[str, Any]] = []
    crop_rows: list[dict[str, Any]] = []
    raw_crop_dir = output_dir / "raw-megadetector-crops"

    for input_row in detector_rows:
        image_path_text = clean(input_row.get("detector_input_frame_path"))
        if not image_path_text or not Path(image_path_text).exists():
            continue

        image_path = Path(image_path_text)
        detector_input_id = clean(input_row.get("detector_input_id"))
        frame_id = clean(input_row.get("frame_id"))

        raw_detections = infer_with_ultralytics(
            model=model,
            image_path=image_path,
            confidence_threshold=detector_settings.detector_confidence_threshold,
            device=detector_settings.detector_device,
        )

        for det_index, det in enumerate(raw_detections):
            detection_id = deterministic_id("detection", detector_input_id, det_index, det["class_name"], det["confidence"])
            role = normalize_detection_role(det["class_name"])
            x1 = as_float(det["x1"])
            y1 = as_float(det["y1"])
            x2 = as_float(det["x2"])
            y2 = as_float(det["y2"])
            bbox_width = max(0.0, x2 - x1)
            bbox_height = max(0.0, y2 - y1)

            crop_path = raw_crop_dir / f"{frame_id}-{detection_id}-{role}.jpg"
            crop_ok, crop_bytes, crop_error = export_raw_crop(
                image_path=image_path,
                bbox=det,
                crop_path=crop_path,
                padding_px=detector_settings.crop_padding_px,
                jpeg_quality=detector_settings.detector_jpeg_quality,
            )

            detection_row = {
                **input_row,
                "detection_id": detection_id,
                "class_id": det["class_id"],
                "class_name": det["class_name"],
                "confidence": round(as_float(det["confidence"]), 6),
                "detection_role": role,
                "bbox_x1": round(x1, 3),
                "bbox_y1": round(y1, 3),
                "bbox_x2": round(x2, 3),
                "bbox_y2": round(y2, 3),
                "bbox_width": round(bbox_width, 3),
                "bbox_height": round(bbox_height, 3),
                "bbox_center_x": round(x1 + bbox_width / 2.0, 3),
                "bbox_center_y": round(y1 + bbox_height / 2.0, 3),
                "bbox_area_px": round(bbox_width * bbox_height, 3),
                "crop_path": str(crop_path) if crop_ok else "",
                "crop_exported": bool_text(crop_ok),
                "crop_export_error": crop_error,
            }
            detections.append(detection_row)

            crop_rows.append(
                {
                    "detection_id": detection_id,
                    "detector_input_id": detector_input_id,
                    "frame_id": frame_id,
                    "crop_path": str(crop_path) if crop_ok else "",
                    "crop_exported": bool_text(crop_ok),
                    "crop_file_bytes": crop_bytes if crop_ok else 0,
                    "crop_export_error": crop_error,
                    "database_mutation": "false",
                    "durable_evidence_written": "false",
                    "purgeable": "true",
                }
            )

    detection_fields = list(dict.fromkeys([key for row in detections for key in row.keys()]))
    crop_fields = list(dict.fromkeys([key for row in crop_rows for key in row.keys()]))

    detections_csv = output_dir / "megadetector-detections.csv"
    crop_exports_csv = output_dir / "crop-exports.csv"
    write_csv(detections_csv, detections, detection_fields or ["detection_id"])
    write_csv(crop_exports_csv, crop_rows, crop_fields or ["detection_id"])

    md_manifest = {
        "component": "SmartFrameSampler.megadetector_stage",
        "status": "PASS",
        "scoring_input_ready": True,
        "detector_model_path": str(model_path),
        "detections_csv": str(detections_csv),
        "crop_exports_csv": str(crop_exports_csv),
        "detection_rows": len(detections),
        "crop_rows": len(crop_rows),
        "database_mutation": False,
        "durable_evidence_written": False,
        "media_files_written": sum(1 for row in crop_rows if row.get("crop_exported") == "true"),
    }
    write_json(output_dir / "megadetector-stage-manifest.json", md_manifest)
    return md_manifest


def optional_raw_crop_metrics(crop_path: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "crop_file_exists": False,
        "crop_file_bytes": 0,
        "crop_image_readable": False,
        "crop_image_width": "",
        "crop_image_height": "",
        "crop_laplacian_variance": "",
        "crop_metric_error": "",
    }

    if not crop_path:
        return metrics

    path = Path(crop_path)
    if not path.exists():
        metrics["crop_metric_error"] = f"raw crop file missing: {path}"
        return metrics

    metrics["crop_file_exists"] = True
    metrics["crop_file_bytes"] = path.stat().st_size

    try:
        cv2 = open_cv2()
        image = cv2.imread(str(path))
        if image is None:
            metrics["crop_metric_error"] = "cv2 could not read raw crop image"
            return metrics

        height, width = image.shape[:2]
        metrics["crop_image_readable"] = True
        metrics["crop_image_width"] = width
        metrics["crop_image_height"] = height

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        metrics["crop_laplacian_variance"] = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3)
        return metrics
    except Exception as exc:
        metrics["crop_metric_error"] = str(exc)
        return metrics


def context_index_by_detector_input(detections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in detections:
        detector_input_id = clean(pick(row, ["detector_input_id", "input_frame_id"]))
        if not detector_input_id:
            continue

        role = normalize_detection_role(pick(row, ["detection_role", "class_name"], "other"))
        entry = indexed.setdefault(
            detector_input_id,
            {
                "person_count": 0,
                "vehicle_count": 0,
                "other_count": 0,
                "person_area_px": 0.0,
                "max_person_area_px": 0.0,
            },
        )

        bbox_area = as_float(pick(row, ["bbox_area_px"]), 0.0)
        if role == "person":
            entry["person_count"] += 1
            entry["person_area_px"] += bbox_area
            entry["max_person_area_px"] = max(entry["max_person_area_px"], bbox_area)
        elif role == "vehicle":
            entry["vehicle_count"] += 1
        elif role == "other":
            entry["other_count"] += 1

    return indexed


def score_raw_animal_crop(
    detection_row: dict[str, Any],
    crop_row: dict[str, Any] | None,
    input_context: dict[str, Any],
    scoring: RawCropScoringSettings,
) -> tuple[float, str, bool, bool, list[str], list[str], dict[str, Any]]:
    confidence = as_float(pick(detection_row, ["confidence"]), 0.0)
    bbox_width = as_float(pick(detection_row, ["bbox_width"]), 0.0)
    bbox_height = as_float(pick(detection_row, ["bbox_height"]), 0.0)
    bbox_area = as_float(pick(detection_row, ["bbox_area_px"]), bbox_width * bbox_height)
    crop_path = clean(pick(crop_row or detection_row, ["crop_path", "output_crop_path", "path"]))
    crop_metrics = optional_raw_crop_metrics(crop_path)

    reasons: list[str] = []
    cautions: list[str] = []
    score = 0.0

    score += scoring.animal_role_points
    reasons.append("animal_role_from_detector")

    if confidence >= scoring.high_confidence_min:
        score += scoring.high_confidence_points
        reasons.append("high_detector_confidence")
    elif confidence >= scoring.medium_confidence_min:
        score += scoring.medium_confidence_points
        reasons.append("medium_detector_confidence")
    elif confidence >= scoring.low_confidence_min:
        score += scoring.low_confidence_points
        cautions.append("low_detector_confidence")
    else:
        score += scoring.very_low_confidence_points
        cautions.append("very_low_detector_confidence")

    if bbox_width >= scoring.large_bbox_min_px and bbox_height >= scoring.large_bbox_min_px:
        score += scoring.large_bbox_points
        reasons.append("large_bbox")
    elif bbox_width >= scoring.medium_bbox_min_px and bbox_height >= scoring.medium_bbox_min_px:
        score += scoring.medium_bbox_points
        reasons.append("medium_bbox")
    elif bbox_width >= scoring.small_bbox_min_px and bbox_height >= scoring.small_bbox_min_px:
        score += scoring.small_bbox_points
        cautions.append("small_bbox")
    else:
        score += scoring.very_small_bbox_points
        cautions.append("very_small_bbox")

    if bbox_area >= scoring.large_area_min_px:
        score += scoring.large_area_points
        reasons.append("large_bbox_area")
    elif bbox_area >= scoring.moderate_area_min_px:
        score += scoring.moderate_area_points
        reasons.append("moderate_bbox_area")
    elif bbox_area >= scoring.small_area_min_px:
        score += scoring.small_area_points
        cautions.append("small_bbox_area")
    else:
        cautions.append("tiny_bbox_area")

    if crop_path and crop_metrics["crop_file_exists"]:
        score += scoring.crop_available_points
        reasons.append("raw_crop_available")
    else:
        cautions.append("no_raw_crop_available")

    if crop_metrics["crop_image_readable"]:
        score += scoring.crop_readable_points
        reasons.append("raw_crop_image_readable")

        crop_w = as_int(crop_metrics["crop_image_width"], 0)
        crop_h = as_int(crop_metrics["crop_image_height"], 0)
        blur_metric = as_float(crop_metrics["crop_laplacian_variance"], 0.0)

        if crop_w >= scoring.usable_crop_dimension_min_px and crop_h >= scoring.usable_crop_dimension_min_px:
            score += scoring.usable_crop_dimension_points
            reasons.append("raw_crop_dimensions_usable")
        elif crop_w > 0 and crop_h > 0:
            score += scoring.small_crop_dimension_points
            cautions.append("raw_crop_dimensions_small")

        if blur_metric >= scoring.sharpness_ok_min:
            score += scoring.sharpness_ok_points
            reasons.append("raw_crop_sharpness_metric_ok")
        elif blur_metric > 0:
            score += scoring.sharpness_low_points
            cautions.append("raw_crop_sharpness_metric_low")
    elif crop_path:
        cautions.append("raw_crop_image_not_readable")

    if scoring.allow_person_context and input_context.get("person_count", 0):
        cautions.append(f"person_context_count_{input_context.get('person_count', 0)}")

    if scoring.penalize_person_dominant_frames:
        frame_area = as_float(pick(detection_row, ["width", "frame_width", "detector_input_width"]), 0.0) * as_float(
            pick(detection_row, ["height", "frame_height", "detector_input_height"]),
            0.0,
        )
        max_person_area = as_float(input_context.get("max_person_area_px"), 0.0)
        if frame_area > 0 and max_person_area / frame_area >= scoring.person_dominance_area_ratio:
            score -= scoring.person_dominance_penalty
            cautions.append("person_dominant_frame_penalty")

    score = max(0.0, min(100.0, round(score, 2)))

    if score >= scoring.best_score_min:
        retention_decision = "best"
    elif score >= scoring.usable_score_min:
        retention_decision = "usable"
    elif score >= scoring.weak_debug_score_min:
        retention_decision = "weak_debug"
    else:
        retention_decision = "discardable"

    order = {"discardable": 0, "weak_debug": 1, "usable": 2, "best": 3}
    dlc_candidate = order.get(retention_decision, 0) >= order.get(scoring.dlc_candidate_min_decision, 2)
    mmpose_candidate = order.get(retention_decision, 0) >= order.get(scoring.mmpose_candidate_min_decision, 1)

    return score, retention_decision, dlc_candidate, mmpose_candidate, reasons, cautions, crop_metrics


def score_raw_crop_candidates(
    md_output_dir: Path,
    output_dir: Path,
    scoring: RawCropScoringSettings,
) -> dict[str, Any]:
    detections, _detection_headers = read_csv(md_output_dir / "megadetector-detections.csv")
    crops, _crop_headers = read_csv(md_output_dir / "crop-exports.csv")
    detector_inputs, _detector_input_headers = read_csv(md_output_dir / "detector-input-frames.csv")

    if not detections:
        return {
            "status": "SKIPPED",
            "message": f"No megadetector-detections.csv rows found in {md_output_dir}",
            "candidate_rows": 0,
            "context_rows": 0,
            "mmpose_candidate_count": 0,
            "dlc_candidate_count": 0,
        }

    crop_by_detection_id: dict[str, dict[str, Any]] = {}
    for row in crops:
        did = clean(pick(row, ["detection_id", "detector_detection_id"]))
        if did:
            crop_by_detection_id[did] = row

    input_by_id: dict[str, dict[str, Any]] = {}
    for row in detector_inputs:
        iid = clean(pick(row, ["detector_input_id", "input_frame_id"]))
        if iid:
            input_by_id[iid] = row

    context_by_input = context_index_by_detector_input(detections)

    all_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    mmpose_rows: list[dict[str, Any]] = []

    counts = {
        "best": 0,
        "usable": 0,
        "weak_debug": 0,
        "discardable": 0,
        "context_only": 0,
        "animal": 0,
        "person": 0,
        "vehicle": 0,
        "other": 0,
        "dlc_candidate": 0,
        "mmpose_candidate": 0,
    }

    for idx, det in enumerate(detections):
        detection_id = clean(pick(det, ["detection_id"]), f"detection-row-{idx}")
        detector_input_id = clean(pick(det, ["detector_input_id", "input_frame_id"]))
        role = normalize_detection_role(pick(det, ["detection_role", "class_name"], "other"))
        input_row = input_by_id.get(detector_input_id, {})
        crop_row = crop_by_detection_id.get(detection_id, {})
        counts[role] = counts.get(role, 0) + 1

        common = {
            "retention_score_id": deterministic_id("raw-crop-score", detection_id, detector_input_id),
            "detection_id": detection_id,
            "detector_input_id": detector_input_id,
            "frame_id": clean(pick(det, ["frame_id"]), clean(pick(input_row, ["frame_id"]))),
            "sequence_id": clean(pick(det, ["sequence_id"]), clean(pick(input_row, ["sequence_id"]))),
            "source_video": clean(pick(det, ["source_video"]), clean(pick(input_row, ["source_video"]))),
            "source_media_context": clean(pick(det, ["source_media_context"]), clean(pick(input_row, ["source_media_context"]))),
            "source_frame_index": clean(pick(det, ["source_frame_index"]), clean(pick(input_row, ["source_frame_index"]))),
            "camera_local_time_seconds": clean(
                pick(det, ["camera_local_time_seconds", "frame_time_seconds"]),
                clean(pick(input_row, ["camera_local_time_seconds", "frame_time_seconds"])),
            ),
            "sync_session_id": clean(pick(det, ["sync_session_id"]), clean(pick(input_row, ["sync_session_id"]))),
            "synced_time_ms": clean(pick(det, ["synced_time_ms"]), clean(pick(input_row, ["synced_time_ms"]))),
            "calibration_id": clean(pick(det, ["calibration_id"]), clean(pick(input_row, ["calibration_id"]))),
            "feeder_zone_id": clean(pick(det, ["feeder_zone_id"]), clean(pick(input_row, ["feeder_zone_id"]))),
            "evidence_mode": "single_camera_2d",
            "evidence_purpose": "raw_crop_candidate_gate",
            "class_name": clean(pick(det, ["class_name"])),
            "class_id": clean(pick(det, ["class_id"])),
            "confidence": clean(pick(det, ["confidence"])),
            "detection_role": role,
            "bbox_x1": clean(pick(det, ["bbox_x1", "x1"])),
            "bbox_y1": clean(pick(det, ["bbox_y1", "y1"])),
            "bbox_x2": clean(pick(det, ["bbox_x2", "x2"])),
            "bbox_y2": clean(pick(det, ["bbox_y2", "y2"])),
            "bbox_width": clean(pick(det, ["bbox_width"])),
            "bbox_height": clean(pick(det, ["bbox_height"])),
            "bbox_center_x": clean(pick(det, ["bbox_center_x"])),
            "bbox_center_y": clean(pick(det, ["bbox_center_y"])),
            "bbox_area_px": clean(pick(det, ["bbox_area_px"])),
            "detector_input_frame_path": clean(
                pick(det, ["detector_input_frame_path"]),
                clean(pick(input_row, ["detector_input_frame_path"])),
            ),
            "raw_crop_path": clean(pick(det, ["crop_path"]), clean(pick(crop_row, ["crop_path"]))),
            "raw_crop_exported": clean(pick(det, ["crop_exported"]), clean(pick(crop_row, ["crop_exported"], "false"))),
            "scoring_policy": RAW_CROP_SCORING_POLICY,
            "database_mutation": "false",
            "durable_evidence_written": "false",
            "retention_output_purgeable": "true",
        }

        if role == "animal":
            score, decision, dlc_candidate, mmpose_candidate, reasons, cautions, crop_metrics = score_raw_animal_crop(
                detection_row={**input_row, **det},
                crop_row=crop_row,
                input_context=context_by_input.get(detector_input_id, {}),
                scoring=scoring,
            )
            counts[decision] += 1
            if dlc_candidate:
                counts["dlc_candidate"] += 1
            if mmpose_candidate:
                counts["mmpose_candidate"] += 1

            row = dict(common)
            row.update(
                {
                    "retention_decision": decision,
                    "retention_score": score,
                    "candidate_kind": "bird_candidate",
                    "send_to_dlc_candidate": bool_text(dlc_candidate),
                    "send_to_mmpose_candidate": bool_text(mmpose_candidate),
                    "context_only": "false",
                    "score_reasons": ";".join(reasons),
                    "score_cautions": ";".join(cautions),
                    "raw_crop_file_exists": bool_text(crop_metrics["crop_file_exists"]),
                    "raw_crop_file_bytes": crop_metrics["crop_file_bytes"],
                    "raw_crop_image_readable": bool_text(crop_metrics["crop_image_readable"]),
                    "raw_crop_image_width": crop_metrics["crop_image_width"],
                    "raw_crop_image_height": crop_metrics["crop_image_height"],
                    "raw_crop_laplacian_variance": crop_metrics["crop_laplacian_variance"],
                    "raw_crop_metric_error": crop_metrics["crop_metric_error"],
                }
            )
            candidate_rows.append(row)
            all_rows.append(row)

            if mmpose_candidate:
                mmpose_rows.append(
                    {
                        "mmpose_input_id": deterministic_id("mmpose-input", row["retention_score_id"]),
                        "retention_score_id": row["retention_score_id"],
                        "detection_id": row["detection_id"],
                        "detector_input_id": row["detector_input_id"],
                        "frame_id": row["frame_id"],
                        "source_video": row["source_video"],
                        "source_frame_index": row["source_frame_index"],
                        "camera_local_time_seconds": row["camera_local_time_seconds"],
                        "raw_crop_path": row["raw_crop_path"],
                        "detector_input_frame_path": row["detector_input_frame_path"],
                        "retention_decision": row["retention_decision"],
                        "retention_score": row["retention_score"],
                        "bbox_x1": row["bbox_x1"],
                        "bbox_y1": row["bbox_y1"],
                        "bbox_x2": row["bbox_x2"],
                        "bbox_y2": row["bbox_y2"],
                        "bbox_width": row["bbox_width"],
                        "bbox_height": row["bbox_height"],
                        "evidence_mode": row["evidence_mode"],
                        "evidence_purpose": "mmpose_candidate_input",
                        "database_mutation": "false",
                        "durable_evidence_written": "false",
                        "input_purgeable": "true",
                    }
                )
        else:
            counts["context_only"] += 1
            row = dict(common)
            row.update(
                {
                    "retention_decision": "context_only",
                    "retention_score": "",
                    "candidate_kind": f"{role}_context",
                    "send_to_dlc_candidate": "false",
                    "send_to_mmpose_candidate": "false",
                    "context_only": "true",
                    "score_reasons": f"{role}_preserved_as_context",
                    "score_cautions": "not_bird_candidate",
                    "raw_crop_file_exists": "",
                    "raw_crop_file_bytes": "",
                    "raw_crop_image_readable": "",
                    "raw_crop_image_width": "",
                    "raw_crop_image_height": "",
                    "raw_crop_laplacian_variance": "",
                    "raw_crop_metric_error": "",
                }
            )
            context_rows.append(row)
            all_rows.append(row)

    output_fields = list(dict.fromkeys([key for row in all_rows for key in row.keys()]))
    mmpose_fields = list(dict.fromkeys([key for row in mmpose_rows for key in row.keys()]))

    retention_scores_csv = output_dir / "raw-crop-retention-scores.csv"
    bird_candidates_csv = output_dir / "bird-candidates.csv"
    context_detections_csv = output_dir / "context-detections.csv"
    mmpose_input_manifest_csv = output_dir / "mmpose-input-manifest.csv"
    retention_json = output_dir / "raw-crop-retention-summary.json"

    write_csv(retention_scores_csv, all_rows, output_fields or ["retention_score_id"])
    write_csv(bird_candidates_csv, candidate_rows, output_fields or ["retention_score_id"])
    write_csv(context_detections_csv, context_rows, output_fields or ["retention_score_id"])
    write_csv(mmpose_input_manifest_csv, mmpose_rows, mmpose_fields or ["mmpose_input_id"])

    summary = {
        "status": "PASS",
        "scoring_policy": RAW_CROP_SCORING_POLICY,
        "megadetector_output_dir": str(md_output_dir),
        "input_detection_rows": len(detections),
        "bird_candidate_rows": len(candidate_rows),
        "context_detection_rows": len(context_rows),
        "mmpose_input_rows": len(mmpose_rows),
        "best_count": counts["best"],
        "usable_count": counts["usable"],
        "weak_debug_count": counts["weak_debug"],
        "discardable_count": counts["discardable"],
        "context_only_count": counts["context_only"],
        "dlc_candidate_count": counts["dlc_candidate"],
        "mmpose_candidate_count": counts["mmpose_candidate"],
        "animal_detections": counts["animal"],
        "person_detections": counts["person"],
        "vehicle_detections": counts["vehicle"],
        "other_detections": counts["other"],
        "files": {
            "raw_crop_retention_scores_csv": str(retention_scores_csv),
            "bird_candidates_csv": str(bird_candidates_csv),
            "context_detections_csv": str(context_detections_csv),
            "mmpose_input_manifest_csv": str(mmpose_input_manifest_csv),
            "raw_crop_retention_summary_json": str(retention_json),
        },
        "database_mutation": False,
        "durable_evidence_written": False,
        "outputs_are_purgeable": True,
    }

    write_json(retention_json, summary)
    return summary


def run_smart_frame_sampler(
    source_video: str | Path,
    output_root: str | Path,
    run_id: str | None,
    sampler_settings: SamplerSettings,
    detector_settings: DetectorInputSettings,
    scoring_settings: RawCropScoringSettings,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    source_video = Path(source_video)
    output_root = Path(output_root)
    started_at = utc_timestamp()

    if not source_video.exists():
        raise FileNotFoundError(f"Source video missing: {source_video}")

    output_dir = prepare_output_dir(output_root, make_run_id(source_video, run_id), sampler_settings.clear_output)
    frames_dir = output_dir / "preview-frames"

    metadata = read_video_metadata(source_video)
    planned = build_frame_plan(source_video, sampler_settings, metadata)
    materialized = materialize_preview_frames(source_video, frames_dir, planned, sampler_settings)

    records: list[FrameRecord] = []
    for item in planned:
        frame_index = int(item["source_frame_index"])
        frame_path = materialized.get(frame_index, "")
        records.append(
            FrameRecord(
                frame_id=str(item["frame_id"]),
                sequence_id=str(item["sequence_id"]),
                source_video=str(source_video),
                source_media_context=sampler_settings.source_media_context,
                source_video_is_canonical=True,
                source_video_available=True,
                source_frame_index=frame_index,
                frame_time_seconds=round(float(item["frame_time_seconds"]), 6),
                anchor_index=int(item["anchor_index"]),
                anchor_frame_index=int(item["anchor_frame_index"]),
                anchor_time_seconds=round(float(item["anchor_time_seconds"]), 6),
                burst_index=int(item["burst_index"]),
                burst_offset_seconds=round(float(item["burst_offset_seconds"]), 6),
                offset_from_anchor_frames=int(item["offset_from_anchor_frames"]),
                is_anchor=bool(item["is_anchor"]),
                frame_path=frame_path,
                frame_materialized=bool(frame_path),
                frame_cache_role="bounded_preview_cache" if frame_path else "record_only_not_materialized",
                purgeable=True,
                width=int(metadata["width"]),
                height=int(metadata["height"]),
                fps=round(float(metadata["fps"]), 6),
                duration_seconds=round(float(metadata["duration_seconds"]), 6),
                total_source_frames=int(metadata["total_source_frames"]),
                sync_session_id="",
                synced_time_ms="",
                calibration_id="",
                feeder_zone_id="",
            )
        )

    frame_rows = [asdict(record) for record in records]
    frame_fields = list(FrameRecord.__dataclass_fields__.keys())

    sampled_csv = output_dir / "sampled-frames.csv"
    sampled_jsonl = output_dir / "sampled-frames.jsonl"
    detector_input_csv = output_dir / "detector-input-frames.csv"
    manifest_path = output_dir / "manifest.json"
    ledger_path = output_dir / "SmartFrameSampler-storage-ledger.json"
    status_path = output_dir / "status.txt"

    write_csv(sampled_csv, frame_rows, frame_fields)
    write_jsonl(sampled_jsonl, frame_rows)

    detector_rows, detector_media_written = make_detector_input_rows(
        source_video=source_video,
        output_dir=output_dir,
        frame_rows=frame_rows,
        detector_settings=detector_settings,
    )
    detector_input_fields = list(dict.fromkeys([key for row in detector_rows for key in row.keys()]))
    write_csv(detector_input_csv, detector_rows, detector_input_fields or ["detector_input_id"])

    media_files_written = len(materialized) + detector_media_written
    megadetector_stage_manifest: dict[str, Any] = {}
    scoring_summary: dict[str, Any] = {}

    scoring_source_dir = Path(detector_settings.megadetector_output_dir) if detector_settings.megadetector_output_dir else None

    if detector_settings.run_megadetector:
        megadetector_stage_manifest = run_megadetector_stage(output_dir, detector_rows, detector_settings)
        scoring_source_dir = output_dir

    if scoring_source_dir:
        scoring_summary = score_raw_crop_candidates(scoring_source_dir.resolve(), output_dir, scoring_settings)

    pipeline_completion_state = "detector_input_ready"
    if scoring_summary.get("status") == "PASS":
        pipeline_completion_state = "raw_crop_candidates_ready_for_mmpose"
    elif detector_settings.run_megadetector:
        pipeline_completion_state = "megadetector_ran_no_candidate_score"

    manifest = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
        "component": COMPONENT_NAME,
        "status": "PASS",
        "pipeline_completion_state": pipeline_completion_state,
        "started_at": started_at,
        "completed_at": utc_timestamp(),
        "source_video": str(source_video),
        "source_media_context": sampler_settings.source_media_context,
        "source_video_is_canonical": True,
        "source_video_available": True,
        "settings_path": str(settings_path) if settings_path else "",
        "settings": {
            "sampler": asdict(sampler_settings),
            "detector_input": asdict(detector_settings),
            "raw_crop_scoring": asdict(scoring_settings),
        },
        "output_dir": str(output_dir),
        "sampled_frames_csv": str(sampled_csv),
        "sampled_frames_jsonl": str(sampled_jsonl),
        "detector_input_frames_csv": str(detector_input_csv),
        "manifest_path": str(manifest_path),
        "storage_ledger_path": str(ledger_path),
        "frame_records_written": len(records),
        "preview_frames_written": len(materialized),
        "detector_input_rows": len(detector_rows),
        "detector_input_frames_materialized": detector_media_written,
        "media_files_written": media_files_written,
        "megadetector_stage": megadetector_stage_manifest,
        "raw_crop_scoring_summary": scoring_summary,
        "database_mutation": False,
        "durable_evidence_written": False,
        "broad_media_export": False,
        "outputs_are_purgeable": True,
        "metadata": metadata,
    }

    ledger = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "component": COMPONENT_NAME,
        "source_video": str(source_video),
        "source_video_is_canonical": True,
        "output_dir": str(output_dir),
        "storage_classes": {
            "sampled_frame_records": {
                "paths": [str(sampled_csv), str(sampled_jsonl)],
                "role": "provenance/cache index",
                "purgeable": True,
                "durable_evidence": False,
            },
            "preview_frames": {
                "path": str(frames_dir),
                "role": "bounded preview frame cache",
                "purgeable": True,
                "durable_evidence": False,
                "files_written": len(materialized),
            },
            "detector_input_frames": {
                "path": str(output_dir / "detector-input-frames"),
                "csv": str(detector_input_csv),
                "role": "bounded detector input frame cache",
                "purgeable": True,
                "durable_evidence": False,
                "files_written": detector_media_written,
            },
            "raw_megadetector_crops": {
                "path": str(output_dir / "raw-megadetector-crops"),
                "role": "raw crop cache from MegaDetector boxes, before refined crops",
                "purgeable": True,
                "durable_evidence": False,
            },
            "candidate_handoff": {
                "paths": [
                    str(output_dir / "raw-crop-retention-scores.csv"),
                    str(output_dir / "bird-candidates.csv"),
                    str(output_dir / "context-detections.csv"),
                    str(output_dir / "mmpose-input-manifest.csv"),
                ],
                "role": "raw crop candidate gate and MMPose handoff",
                "purgeable": True,
                "durable_evidence": False,
            },
        },
        "database_mutation": False,
        "durable_evidence_written": False,
        "broad_media_export": False,
        "media_files_written": media_files_written,
    }

    write_json(manifest_path, manifest)
    write_json(ledger_path, ledger)

    status_lines = [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        "status = PASS",
        f"pipeline_completion_state = {pipeline_completion_state}",
        f"source_video = {source_video}",
        f"source_media_context = {sampler_settings.source_media_context}",
        "source_video_is_canonical = true",
        "source_video_available = true",
        f"output_dir = {output_dir}",
        f"sampled_frames_csv = {sampled_csv}",
        f"sampled_frames_jsonl = {sampled_jsonl}",
        f"detector_input_frames_csv = {detector_input_csv}",
        f"manifest_path = {manifest_path}",
        f"storage_ledger_path = {ledger_path}",
        f"frame_records_written = {len(records)}",
        f"preview_frames_written = {len(materialized)}",
        f"detector_input_rows = {len(detector_rows)}",
        f"detector_input_frames_materialized = {detector_media_written}",
        f"media_files_written = {media_files_written}",
        f"raw_crop_scoring_policy = {RAW_CROP_SCORING_POLICY}",
        f"bird_candidate_rows = {scoring_summary.get('bird_candidate_rows', '')}",
        f"mmpose_input_rows = {scoring_summary.get('mmpose_input_rows', '')}",
        "database_mutation = false",
        "durable_evidence_written = false",
        "broad_media_export = false",
        "outputs_are_purgeable = true",
    ]
    status_path.write_text("\n".join(status_lines) + "\n", encoding="utf-8")
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Birdbill early pipeline sampler: source video to detector input and optional raw-crop candidate handoff."
    )
    parser.add_argument("--source", required=True, help="Source video path. Source video remains canonical.")
    parser.add_argument("--output-root", default=r"D:\birdbill\output\cache\SmartFrameSampler")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--settings", default=None)

    parser.add_argument("--source-media-context", default=None)
    parser.add_argument("--sample-every-seconds", type=float, default=None)
    parser.add_argument("--max-frame-records", type=int, default=None)
    parser.add_argument("--burst-offsets-seconds", default=None)
    parser.add_argument("--preview-frame-limit", type=int, default=None)
    parser.add_argument("--jpeg-quality", type=int, default=None)
    parser.add_argument("--clear-output", action="store_true")

    parser.add_argument("--max-detector-frames", type=int, default=None)
    parser.add_argument("--detector-selection-policy", default=None)
    parser.add_argument("--detector-jpeg-quality", type=int, default=None)
    parser.add_argument("--crop-padding-px", type=int, default=None)
    parser.add_argument("--detector-confidence-threshold", type=float, default=None)
    parser.add_argument("--detector-device", default=None)
    parser.add_argument("--detector-model", default=None)
    parser.add_argument("--run-megadetector", action="store_true")
    parser.add_argument("--megadetector-output-dir", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    print(f"script_name = {SCRIPT_NAME}")
    print(f"script_version = {SCRIPT_VERSION}")
    print(f"rewrite_step = {REWRITE_STEP}")
    print(f"component = {COMPONENT_NAME}")
    print(f"python_executable = {sys.executable}")
    print(f"source = {args.source}")
    print(f"output_root = {args.output_root}")
    print(f"settings = {args.settings or ''}")

    try:
        settings_path = Path(args.settings) if args.settings else None
        sampler_settings, detector_settings, scoring_settings = load_settings(settings_path, args)
        manifest = run_smart_frame_sampler(
            source_video=Path(args.source),
            output_root=Path(args.output_root),
            run_id=args.run_id,
            sampler_settings=sampler_settings,
            detector_settings=detector_settings,
            scoring_settings=scoring_settings,
            settings_path=settings_path,
        )

        print("status = PASS")
        print(f"pipeline_completion_state = {manifest['pipeline_completion_state']}")
        print(f"output_dir = {manifest['output_dir']}")
        print(f"sampled_frames_csv = {manifest['sampled_frames_csv']}")
        print(f"detector_input_frames_csv = {manifest['detector_input_frames_csv']}")
        print(f"frame_records_written = {manifest['frame_records_written']}")
        print(f"detector_input_rows = {manifest['detector_input_rows']}")
        print("database_mutation = false")
        print("durable_evidence_written = false")
        print("broad_media_export = false")
        return 0

    except Exception as exc:
        print("status = FAIL")
        print(f"error_type = {type(exc).__name__}")
        print(f"error = {exc}")
        print("database_mutation = false")
        print("durable_evidence_written = false")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
