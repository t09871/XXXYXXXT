
# FrameSamplerDetector.py | v0.1 | 2026-07-07 PDT | Birdbill frame sampler + MegaDetector raw-crop candidate gate

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

SCRIPT_NAME = "FrameSamplerDetector.py"
SCRIPT_VERSION = "v0.1"
REWRITE_STEP = "early-pipeline-promotion-candidate"
COMPONENT_NAME = "FrameSamplerDetector"
RAW_CROP_SCORING_POLICY = "raw_crop_candidate_retention_v0.1"

DATABASE_MUTATION = False
DURABLE_EVIDENCE_WRITTEN = False


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
            "OpenCV import failed. FrameSamplerDetector needs cv2 in the selected Python environment. "
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
        detector_device=cli.detector_device or detector.get("detector_device", detector_defaults.detector_device),
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
        usable_crop_dimension_min_px=int(
            scoring.get("usable_crop_dimension_min_px", scoring_defaults.usable_crop_dimension_min_px)
        ),
        usable_crop_dimension_points=float(
            scoring.get("usable_crop_dimension_points", scoring_defaults.usable_crop_dimension_points)
        ),
        small_crop_dimension_points=float(
            scoring.get("small_crop_dimension_points", scoring_defaults.small_crop_dimension_points)
        ),
        sharpness_ok_min=float(scoring.get("sharpness_ok_min", scoring_defaults.sharpness_ok_min)),
        sharpness_ok_points=float(scoring.get("sharpness_ok_points", scoring_defaults.sharpness_ok_points)),
        sharpness_low_points=float(scoring.get("sharpness_low_points", scoring_defaults.sharpness_low_points)),
        allow_person_context=bool_from_text(
            scoring.get("allow_person_context", None),
            scoring_defaults.allow_person_context,
        ),
        penalize_person_dominant_frames=bool_from_text(
            scoring.get("penalize_person_dominant_frames", None),
            scoring_defaults.penalize_person_dominant_frames,
        ),
        person_dominance_area_ratio=float(
            scoring.get("person_dominance_area_ratio", scoring_defaults.person_dominance_area_ratio)
        ),
        person_dominance_penalty=float(
            scoring.get("person_dominance_penalty", scoring_defaults.person_dominance_penalty)
        ),
        dlc_candidate_min_decision=scoring.get(
            "dlc_candidate_min_decision",
            scoring_defaults.dlc_candidate_min_decision,
        ),
        mmpose_candidate_min_decision=scoring.get(
            "mmpose_candidate_min_decision",
            scoring_defaults.mmpose_candidate_min_decision,
        ),
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
        return sanitize_name(provided, fallback=f"frame-sampler-detector-{local_run_stamp()}")

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
    additional_media_written = 0

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
                additional_media_written += 1
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

    return detector_rows, additional_media_written


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
        raise FileNotFoundError(f"MegaDetector model path does not exist: {model_path}")

    crop_dir = output_dir / "raw-megadetector-crops"
    detections: list[dict[str, Any]] = []
    crop_exports: list[dict[str, Any]] = []
    crop_files_written = 0

    model = YOLO(str(model_path))

    for detector_row in detector_rows:
        image_path = Path(clean(detector_row.get("detector_input_frame_path")))
        if not image_path.exists():
            continue

        frame_detections = infer_with_ultralytics(
            model=model,
            image_path=image_path,
            confidence_threshold=detector_settings.detector_confidence_threshold,
            device=detector_settings.detector_device,
        )

        for detection_index, detection in enumerate(frame_detections, start=1):
            role = normalize_detection_role(detection.get("class_name"))
            x1 = as_float(detection.get("x1"))
            y1 = as_float(detection.get("y1"))
            x2 = as_float(detection.get("x2"))
            y2 = as_float(detection.get("y2"))
            bbox_width = max(0.0, x2 - x1)
            bbox_height = max(0.0, y2 - y1)
            bbox_area = bbox_width * bbox_height

            detection_id = deterministic_id(
                "detection",
                detector_row.get("detector_input_id"),
                detection_index,
                role,
                f"{as_float(detection.get('confidence')):.5f}",
                f"{x1:.2f}",
                f"{y1:.2f}",
                f"{x2:.2f}",
                f"{y2:.2f}",
            )

            detection_row = {
                "detection_id": detection_id,
                "detector_input_id": detector_row.get("detector_input_id", ""),
                "frame_id": detector_row.get("frame_id", ""),
                "sequence_id": detector_row.get("sequence_id", ""),
                "source_video": detector_row.get("source_video", ""),
                "source_media_context": detector_row.get("source_media_context", ""),
                "source_frame_index": detector_row.get("source_frame_index", ""),
                "camera_local_time_seconds": detector_row.get("camera_local_time_seconds", ""),
                "detector_input_frame_path": str(image_path),
                "class_id": detection.get("class_id", ""),
                "class_name": detection.get("class_name", ""),
                "detection_role": role,
                "confidence": f"{as_float(detection.get('confidence')):.6f}",
                "bbox_x1": f"{x1:.3f}",
                "bbox_y1": f"{y1:.3f}",
                "bbox_x2": f"{x2:.3f}",
                "bbox_y2": f"{y2:.3f}",
                "bbox_width": f"{bbox_width:.3f}",
                "bbox_height": f"{bbox_height:.3f}",
                "bbox_area": f"{bbox_area:.3f}",
                "database_mutation": "false",
                "durable_evidence_written": "false",
                "purgeable": "true",
            }
            detections.append(detection_row)

            if role != "animal":
                continue

            crop_name = f"{clean(detector_row.get('frame_id'), 'frame')}-{detection_id}-animal.jpg"
            crop_path = crop_dir / crop_name
            ok, size_bytes, error = export_raw_crop(
                image_path=image_path,
                bbox=detection,
                crop_path=crop_path,
                padding_px=detector_settings.crop_padding_px,
                jpeg_quality=detector_settings.detector_jpeg_quality,
            )
            if ok:
                crop_files_written += 1

            crop_exports.append(
                {
                    "crop_export_id": deterministic_id("raw-crop", detection_id, crop_path),
                    "detection_id": detection_id,
                    "detector_input_id": detector_row.get("detector_input_id", ""),
                    "frame_id": detector_row.get("frame_id", ""),
                    "sequence_id": detector_row.get("sequence_id", ""),
                    "source_video": detector_row.get("source_video", ""),
                    "source_media_context": detector_row.get("source_media_context", ""),
                    "source_frame_index": detector_row.get("source_frame_index", ""),
                    "camera_local_time_seconds": detector_row.get("camera_local_time_seconds", ""),
                    "detector_input_frame_path": str(image_path),
                    "raw_crop_path": str(crop_path) if ok else "",
                    "crop_ok": bool_text(ok),
                    "crop_file_bytes": str(size_bytes),
                    "crop_padding_px": str(detector_settings.crop_padding_px),
                    "crop_error": error,
                    "detection_role": role,
                    "class_name": detection.get("class_name", ""),
                    "confidence": f"{as_float(detection.get('confidence')):.6f}",
                    "bbox_x1": f"{x1:.3f}",
                    "bbox_y1": f"{y1:.3f}",
                    "bbox_x2": f"{x2:.3f}",
                    "bbox_y2": f"{y2:.3f}",
                    "bbox_width": f"{bbox_width:.3f}",
                    "bbox_height": f"{bbox_height:.3f}",
                    "bbox_area": f"{bbox_area:.3f}",
                    "database_mutation": "false",
                    "durable_evidence_written": "false",
                    "purgeable": "true",
                }
            )

    detection_fields = [
        "detection_id",
        "detector_input_id",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "detector_input_frame_path",
        "class_id",
        "class_name",
        "detection_role",
        "confidence",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "bbox_area",
        "database_mutation",
        "durable_evidence_written",
        "purgeable",
    ]
    crop_export_fields = [
        "crop_export_id",
        "detection_id",
        "detector_input_id",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "detector_input_frame_path",
        "raw_crop_path",
        "crop_ok",
        "crop_file_bytes",
        "crop_padding_px",
        "crop_error",
        "detection_role",
        "class_name",
        "confidence",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "bbox_area",
        "database_mutation",
        "durable_evidence_written",
        "purgeable",
    ]

    detections_csv = output_dir / "megadetector-detections.csv"
    crop_exports_csv = output_dir / "crop-exports.csv"
    stage_manifest = output_dir / "megadetector-stage-manifest.json"

    write_csv(detections_csv, detections, detection_fields)
    write_csv(crop_exports_csv, crop_exports, crop_export_fields)
    write_json(
        stage_manifest,
        {
            "script_name": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "component": COMPONENT_NAME,
            "stage": "megadetector",
            "status": "PASS",
            "model_path": str(model_path),
            "detector_input_rows": len(detector_rows),
            "detection_rows": len(detections),
            "animal_crop_export_rows": len(crop_exports),
            "raw_megadetector_crops_written": crop_files_written,
            "database_mutation": DATABASE_MUTATION,
            "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
            "outputs_are_purgeable": True,
        },
    )

    return {
        "detections": detections,
        "crop_exports": crop_exports,
        "detections_csv": str(detections_csv),
        "crop_exports_csv": str(crop_exports_csv),
        "stage_manifest": str(stage_manifest),
        "raw_megadetector_crops_written": crop_files_written,
    }


def consume_existing_megadetector_output(megadetector_output_dir: Path) -> dict[str, Any]:
    detections_csv = megadetector_output_dir / "megadetector-detections.csv"
    crop_exports_csv = megadetector_output_dir / "crop-exports.csv"

    if not detections_csv.exists() or not crop_exports_csv.exists():
        raise FileNotFoundError(
            "Existing MegaDetector output must contain megadetector-detections.csv and crop-exports.csv. "
            f"Checked: {megadetector_output_dir}"
        )

    detections, _detection_fields = read_csv(detections_csv)
    crop_exports, _crop_fields = read_csv(crop_exports_csv)

    return {
        "detections": detections,
        "crop_exports": crop_exports,
        "detections_csv": str(detections_csv),
        "crop_exports_csv": str(crop_exports_csv),
        "stage_manifest": "",
        "raw_megadetector_crops_written": 0,
    }


def measure_crop(raw_crop_path: Path) -> dict[str, Any]:
    cv2 = open_cv2()
    if not raw_crop_path.exists():
        return {
            "crop_available": False,
            "crop_readable": False,
            "crop_width": 0,
            "crop_height": 0,
            "crop_sharpness_proxy": 0.0,
            "crop_error": "crop path missing",
        }

    image = cv2.imread(str(raw_crop_path))
    if image is None:
        return {
            "crop_available": True,
            "crop_readable": False,
            "crop_width": 0,
            "crop_height": 0,
            "crop_sharpness_proxy": 0.0,
            "crop_error": "crop unreadable",
        }

    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    return {
        "crop_available": True,
        "crop_readable": True,
        "crop_width": int(width),
        "crop_height": int(height),
        "crop_sharpness_proxy": sharpness,
        "crop_error": "",
    }


def decision_rank(decision: str) -> int:
    ranks = {
        "discardable": 0,
        "weak_debug": 1,
        "usable": 2,
        "best": 3,
    }
    return ranks.get(decision, 0)


def decision_meets(decision: str, minimum: str) -> bool:
    return decision_rank(decision) >= decision_rank(minimum)


def score_decision(score: float, settings: RawCropScoringSettings) -> str:
    if score >= settings.best_score_min:
        return "best"
    if score >= settings.usable_score_min:
        return "usable"
    if score >= settings.weak_debug_score_min:
        return "weak_debug"
    return "discardable"


def score_one_crop(
    crop_row: dict[str, Any],
    detections_by_frame: dict[str, list[dict[str, Any]]],
    settings: RawCropScoringSettings,
) -> dict[str, Any]:
    raw_crop_path = Path(clean(crop_row.get("raw_crop_path")))
    crop_metrics = measure_crop(raw_crop_path) if clean(crop_row.get("raw_crop_path")) else {
        "crop_available": False,
        "crop_readable": False,
        "crop_width": 0,
        "crop_height": 0,
        "crop_sharpness_proxy": 0.0,
        "crop_error": "crop path empty",
    }

    confidence = as_float(crop_row.get("confidence"))
    bbox_width = as_float(crop_row.get("bbox_width"))
    bbox_height = as_float(crop_row.get("bbox_height"))
    bbox_area = as_float(crop_row.get("bbox_area"), bbox_width * bbox_height)
    largest_bbox_dimension = max(bbox_width, bbox_height)

    score = 0.0
    reasons: list[str] = []

    if normalize_detection_role(crop_row.get("detection_role")) == "animal":
        score += settings.animal_role_points
        reasons.append("animal_role")

    if confidence >= settings.high_confidence_min:
        score += settings.high_confidence_points
        reasons.append("high_confidence")
    elif confidence >= settings.medium_confidence_min:
        score += settings.medium_confidence_points
        reasons.append("medium_confidence")
    elif confidence >= settings.low_confidence_min:
        score += settings.low_confidence_points
        reasons.append("low_confidence")
    else:
        score += settings.very_low_confidence_points
        reasons.append("very_low_confidence")

    if largest_bbox_dimension >= settings.large_bbox_min_px:
        score += settings.large_bbox_points
        reasons.append("large_bbox")
    elif largest_bbox_dimension >= settings.medium_bbox_min_px:
        score += settings.medium_bbox_points
        reasons.append("medium_bbox")
    elif largest_bbox_dimension >= settings.small_bbox_min_px:
        score += settings.small_bbox_points
        reasons.append("small_bbox")
    else:
        score += settings.very_small_bbox_points
        reasons.append("very_small_bbox")

    if bbox_area >= settings.large_area_min_px:
        score += settings.large_area_points
        reasons.append("large_bbox_area")
    elif bbox_area >= settings.moderate_area_min_px:
        score += settings.moderate_area_points
        reasons.append("moderate_bbox_area")
    elif bbox_area >= settings.small_area_min_px:
        score += settings.small_area_points
        reasons.append("small_bbox_area")

    if crop_metrics["crop_available"]:
        score += settings.crop_available_points
        reasons.append("crop_available")

    if crop_metrics["crop_readable"]:
        score += settings.crop_readable_points
        reasons.append("crop_readable")

        smallest_crop_dimension = min(int(crop_metrics["crop_width"]), int(crop_metrics["crop_height"]))
        if smallest_crop_dimension >= settings.usable_crop_dimension_min_px:
            score += settings.usable_crop_dimension_points
            reasons.append("usable_crop_dimension")
        else:
            score += settings.small_crop_dimension_points
            reasons.append("small_crop_dimension")

        if float(crop_metrics["crop_sharpness_proxy"]) >= settings.sharpness_ok_min:
            score += settings.sharpness_ok_points
            reasons.append("sharpness_ok")
        else:
            score += settings.sharpness_low_points
            reasons.append("sharpness_low")

    person_penalty_applied = False
    if settings.penalize_person_dominant_frames:
        frame_id = clean(crop_row.get("frame_id"))
        person_rows = [row for row in detections_by_frame.get(frame_id, []) if normalize_detection_role(row.get("detection_role")) == "person"]
        if person_rows and bbox_area > 0:
            largest_person_area = max(as_float(row.get("bbox_area")) for row in person_rows)
            if largest_person_area / max(1.0, bbox_area) >= settings.person_dominance_area_ratio:
                score -= settings.person_dominance_penalty
                person_penalty_applied = True
                reasons.append("person_dominance_penalty")

    decision = score_decision(score, settings)
    dlc_candidate = decision_meets(decision, settings.dlc_candidate_min_decision)
    mmpose_candidate = decision_meets(decision, settings.mmpose_candidate_min_decision)

    return {
        "retention_score_id": deterministic_id("raw-crop-score", crop_row.get("detection_id"), raw_crop_path),
        "crop_export_id": crop_row.get("crop_export_id", ""),
        "detection_id": crop_row.get("detection_id", ""),
        "detector_input_id": crop_row.get("detector_input_id", ""),
        "frame_id": crop_row.get("frame_id", ""),
        "sequence_id": crop_row.get("sequence_id", ""),
        "source_video": crop_row.get("source_video", ""),
        "source_media_context": crop_row.get("source_media_context", ""),
        "source_frame_index": crop_row.get("source_frame_index", ""),
        "camera_local_time_seconds": crop_row.get("camera_local_time_seconds", ""),
        "detector_input_frame_path": crop_row.get("detector_input_frame_path", ""),
        "raw_crop_path": crop_row.get("raw_crop_path", ""),
        "detection_role": normalize_detection_role(crop_row.get("detection_role")),
        "class_name": crop_row.get("class_name", ""),
        "confidence": f"{confidence:.6f}",
        "bbox_x1": crop_row.get("bbox_x1", ""),
        "bbox_y1": crop_row.get("bbox_y1", ""),
        "bbox_x2": crop_row.get("bbox_x2", ""),
        "bbox_y2": crop_row.get("bbox_y2", ""),
        "bbox_width": f"{bbox_width:.3f}",
        "bbox_height": f"{bbox_height:.3f}",
        "bbox_area": f"{bbox_area:.3f}",
        "crop_available": bool_text(crop_metrics["crop_available"]),
        "crop_readable": bool_text(crop_metrics["crop_readable"]),
        "crop_width": str(crop_metrics["crop_width"]),
        "crop_height": str(crop_metrics["crop_height"]),
        "crop_sharpness_proxy": f"{float(crop_metrics['crop_sharpness_proxy']):.3f}",
        "crop_error": crop_metrics["crop_error"],
        "person_penalty_applied": bool_text(person_penalty_applied),
        "retention_score": f"{score:.1f}",
        "retention_decision": decision,
        "dlc_candidate": bool_text(dlc_candidate),
        "mmpose_candidate": bool_text(mmpose_candidate),
        "score_reasons": "|".join(reasons),
        "raw_crop_scoring_policy": RAW_CROP_SCORING_POLICY,
        "database_mutation": "false",
        "durable_evidence_written": "false",
        "input_purgeable": "true",
    }


def score_raw_crops(
    output_dir: Path,
    detections: list[dict[str, Any]],
    crop_exports: list[dict[str, Any]],
    scoring_settings: RawCropScoringSettings,
) -> dict[str, Any]:
    detections_by_frame: dict[str, list[dict[str, Any]]] = {}
    for detection in detections:
        detections_by_frame.setdefault(clean(detection.get("frame_id")), []).append(detection)

    context_rows = [
        row for row in detections
        if normalize_detection_role(row.get("detection_role")) != "animal"
    ]

    animal_crop_rows = [
        row for row in crop_exports
        if normalize_detection_role(row.get("detection_role")) == "animal"
    ]

    scored_rows = [
        score_one_crop(row, detections_by_frame, scoring_settings)
        for row in animal_crop_rows
    ]

    scored_rows = sorted(
        scored_rows,
        key=lambda row: (
            as_int(row.get("source_frame_index"), 0),
            -as_float(row.get("retention_score"), 0.0),
            clean(row.get("detection_id")),
        ),
    )

    bird_candidate_rows = [
        row for row in scored_rows
        if decision_meets(clean(row.get("retention_decision")), "weak_debug")
    ]
    mmpose_rows = [
        row for row in scored_rows
        if bool_from_text(clean(row.get("mmpose_candidate")), False)
    ]

    score_fields = [
        "retention_score_id",
        "crop_export_id",
        "detection_id",
        "detector_input_id",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "detector_input_frame_path",
        "raw_crop_path",
        "detection_role",
        "class_name",
        "confidence",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "bbox_area",
        "crop_available",
        "crop_readable",
        "crop_width",
        "crop_height",
        "crop_sharpness_proxy",
        "crop_error",
        "person_penalty_applied",
        "retention_score",
        "retention_decision",
        "dlc_candidate",
        "mmpose_candidate",
        "score_reasons",
        "raw_crop_scoring_policy",
        "database_mutation",
        "durable_evidence_written",
        "input_purgeable",
    ]

    context_fields = [
        "detection_id",
        "detector_input_id",
        "frame_id",
        "sequence_id",
        "source_video",
        "source_media_context",
        "source_frame_index",
        "camera_local_time_seconds",
        "detector_input_frame_path",
        "class_id",
        "class_name",
        "detection_role",
        "confidence",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "bbox_area",
        "database_mutation",
        "durable_evidence_written",
        "purgeable",
    ]

    retention_scores_csv = output_dir / "raw-crop-retention-scores.csv"
    bird_candidates_csv = output_dir / "bird-candidates.csv"
    context_csv = output_dir / "context-detections.csv"
    summary_json = output_dir / "raw-crop-retention-summary.json"

    write_csv(retention_scores_csv, scored_rows, score_fields)
    write_csv(bird_candidates_csv, bird_candidate_rows, score_fields)
    write_csv(context_csv, context_rows, context_fields)

    decision_counts: dict[str, int] = {}
    for row in scored_rows:
        decision = clean(row.get("retention_decision"), "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    summary = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "component": COMPONENT_NAME,
        "raw_crop_scoring_policy": RAW_CROP_SCORING_POLICY,
        "animal_crop_rows": len(animal_crop_rows),
        "context_detection_rows": len(context_rows),
        "raw_crop_score_rows": len(scored_rows),
        "bird_candidate_rows": len(bird_candidate_rows),
        "mmpose_input_rows": len(mmpose_rows),
        "decision_counts": decision_counts,
        "database_mutation": DATABASE_MUTATION,
        "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
        "outputs_are_purgeable": True,
    }
    write_json(summary_json, summary)

    return {
        "scored_rows": scored_rows,
        "bird_candidate_rows": bird_candidate_rows,
        "mmpose_candidate_rows": mmpose_rows,
        "context_rows": context_rows,
        "retention_scores_csv": str(retention_scores_csv),
        "bird_candidates_csv": str(bird_candidates_csv),
        "context_csv": str(context_csv),
        "summary_json": str(summary_json),
        "summary": summary,
    }


def build_mmpose_manifest(output_dir: Path, mmpose_candidate_rows: list[dict[str, Any]]) -> tuple[Path, list[dict[str, Any]]]:
    manifest_rows: list[dict[str, Any]] = []

    for row in mmpose_candidate_rows:
        manifest_rows.append(
            {
                "mmpose_input_id": deterministic_id(
                    "mmpose-input",
                    row.get("detection_id"),
                    row.get("raw_crop_path"),
                    row.get("retention_score_id"),
                ),
                "retention_score_id": row.get("retention_score_id", ""),
                "detection_id": row.get("detection_id", ""),
                "detector_input_id": row.get("detector_input_id", ""),
                "frame_id": row.get("frame_id", ""),
                "source_video": row.get("source_video", ""),
                "source_frame_index": row.get("source_frame_index", ""),
                "camera_local_time_seconds": row.get("camera_local_time_seconds", ""),
                "raw_crop_path": row.get("raw_crop_path", ""),
                "detector_input_frame_path": row.get("detector_input_frame_path", ""),
                "retention_decision": row.get("retention_decision", ""),
                "retention_score": row.get("retention_score", ""),
                "bbox_x1": row.get("bbox_x1", ""),
                "bbox_y1": row.get("bbox_y1", ""),
                "bbox_x2": row.get("bbox_x2", ""),
                "bbox_y2": row.get("bbox_y2", ""),
                "bbox_width": row.get("bbox_width", ""),
                "bbox_height": row.get("bbox_height", ""),
                "evidence_mode": "single_camera_2d",
                "evidence_purpose": "mmpose_candidate_input",
                "database_mutation": "false",
                "durable_evidence_written": "false",
                "input_purgeable": "true",
            }
        )

    fields = [
        "mmpose_input_id",
        "retention_score_id",
        "detection_id",
        "detector_input_id",
        "frame_id",
        "source_video",
        "source_frame_index",
        "camera_local_time_seconds",
        "raw_crop_path",
        "detector_input_frame_path",
        "retention_decision",
        "retention_score",
        "bbox_x1",
        "bbox_y1",
        "bbox_x2",
        "bbox_y2",
        "bbox_width",
        "bbox_height",
        "evidence_mode",
        "evidence_purpose",
        "database_mutation",
        "durable_evidence_written",
        "input_purgeable",
    ]

    manifest_path = output_dir / "mmpose-input-manifest.csv"
    write_csv(manifest_path, manifest_rows, fields)
    return manifest_path, manifest_rows


def write_status(output_dir: Path, lines: list[str]) -> Path:
    status_path = output_dir / "status.txt"
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return status_path


def write_failure_status(
    output_dir: Path | None,
    source_video: Path | None,
    output_root: Path | None,
    exc: BaseException,
) -> None:
    lines = [
        f"script_name = {SCRIPT_NAME}",
        f"script_version = {SCRIPT_VERSION}",
        f"rewrite_step = {REWRITE_STEP}",
        f"component = {COMPONENT_NAME}",
        "status = FAIL",
        f"error_type = {type(exc).__name__}",
        f"error = {exc}",
        f"source_video = {source_video or ''}",
        f"output_root = {output_root or ''}",
        f"output_dir = {output_dir or ''}",
        "database_mutation = false",
        "durable_evidence_written = false",
        "traceback:",
        traceback.format_exc(),
    ]

    if output_dir is not None:
        write_status(output_dir, lines)

    for line in lines[:11]:
        print(line)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Birdbill frame sampler + MegaDetector raw-crop candidate gate.",
    )

    parser.add_argument("--source", required=True, help="Source video path.")
    parser.add_argument("--output-root", default=r"D:\birdbill\output\debug", help="Output root folder.")
    parser.add_argument("--run-id", default="", help="Run folder name under output root.")
    parser.add_argument("--settings", default="", help="Optional settings.ini path.")
    parser.add_argument("--source-media-context", default="", help="Source/media context label.")
    parser.add_argument("--clear-output", action="store_true", help="Clear run output folder before writing.")

    parser.add_argument("--sample-every-seconds", type=float, default=None)
    parser.add_argument("--max-frame-records", type=int, default=None)
    parser.add_argument("--burst-offsets-seconds", default=None)
    parser.add_argument("--preview-frame-limit", type=int, default=None)
    parser.add_argument("--jpeg-quality", type=int, default=None)

    parser.add_argument("--max-detector-frames", type=int, default=None)
    parser.add_argument("--detector-selection-policy", default="")
    parser.add_argument("--detector-jpeg-quality", type=int, default=None)
    parser.add_argument("--crop-padding-px", type=int, default=None)
    parser.add_argument("--detector-confidence-threshold", type=float, default=None)
    parser.add_argument("--detector-device", default="")
    parser.add_argument("--detector-model", default="")
    parser.add_argument("--run-megadetector", action="store_true")
    parser.add_argument("--megadetector-output-dir", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    output_dir: Path | None = None
    source_video: Path | None = None
    output_root: Path | None = None

    try:
        parser = build_argument_parser()
        cli = parser.parse_args(argv)

        source_video = Path(cli.source)
        output_root = Path(cli.output_root)
        settings_path = Path(cli.settings) if clean(cli.settings) else None

        if not source_video.exists():
            raise FileNotFoundError(f"Source video does not exist: {source_video}")

        sampler_settings, detector_settings, scoring_settings = load_settings(settings_path, cli)
        run_id = make_run_id(source_video, cli.run_id)
        output_dir = prepare_output_dir(output_root, run_id, sampler_settings.clear_output)

        metadata = read_video_metadata(source_video)
        planned_frames = build_frame_plan(source_video, sampler_settings, metadata)

        preview_dir = output_dir / "preview-frames"
        preview_materialized = materialize_preview_frames(source_video, preview_dir, planned_frames, sampler_settings)

        frame_records: list[FrameRecord] = []
        for item in planned_frames:
            frame_index = int(item["source_frame_index"])
            frame_path = preview_materialized.get(frame_index, "")
            frame_records.append(
                FrameRecord(
                    frame_id=item["frame_id"],
                    sequence_id=item["sequence_id"],
                    source_video=str(source_video),
                    source_media_context=sampler_settings.source_media_context,
                    source_video_is_canonical=True,
                    source_video_available=source_video.exists(),
                    source_frame_index=frame_index,
                    frame_time_seconds=float(item["frame_time_seconds"]),
                    anchor_index=int(item["anchor_index"]),
                    anchor_frame_index=int(item["anchor_frame_index"]),
                    anchor_time_seconds=float(item["anchor_time_seconds"]),
                    burst_index=int(item["burst_index"]),
                    burst_offset_seconds=float(item["burst_offset_seconds"]),
                    offset_from_anchor_frames=int(item["offset_from_anchor_frames"]),
                    is_anchor=bool(item["is_anchor"]),
                    frame_path=frame_path,
                    frame_materialized=bool(frame_path),
                    frame_cache_role="preview" if frame_path else "not_materialized",
                    purgeable=True,
                    width=int(metadata["width"]),
                    height=int(metadata["height"]),
                    fps=float(metadata["fps"]),
                    duration_seconds=float(metadata["duration_seconds"]),
                    total_source_frames=int(metadata["total_source_frames"]),
                    sync_session_id="",
                    synced_time_ms="",
                    calibration_id="",
                    feeder_zone_id="",
                )
            )

        frame_rows = [asdict(record) for record in frame_records]
        sampled_frames_csv = output_dir / "sampled-frames.csv"
        sampled_frames_jsonl = output_dir / "sampled-frames.jsonl"
        write_csv(sampled_frames_csv, frame_rows, list(frame_rows[0].keys()) if frame_rows else [])
        write_jsonl(sampled_frames_jsonl, frame_rows)

        detector_rows, additional_detector_input_frames_materialized = make_detector_input_rows(
            source_video=source_video,
            output_dir=output_dir,
            frame_rows=frame_rows,
            detector_settings=detector_settings,
        )

        detector_fields = [
            "detector_input_id",
            "frame_id",
            "sequence_id",
            "source_video",
            "source_media_context",
            "source_frame_index",
            "camera_local_time_seconds",
            "frame_time_seconds",
            "anchor_frame_index",
            "offset_from_anchor_frames",
            "detector_input_frame_path",
            "detector_input_materialized_now",
            "selection_reason",
            "selection_policy",
            "width",
            "height",
            "fps",
            "duration_seconds",
            "sync_session_id",
            "synced_time_ms",
            "calibration_id",
            "feeder_zone_id",
            "database_mutation",
            "durable_evidence_written",
            "purgeable",
        ]
        detector_input_frames_csv = output_dir / "detector-input-frames.csv"
        write_csv(detector_input_frames_csv, detector_rows, detector_fields)

        if detector_settings.run_megadetector:
            md_result = run_megadetector_stage(output_dir, detector_rows, detector_settings)
        elif clean(detector_settings.megadetector_output_dir):
            md_result = consume_existing_megadetector_output(Path(detector_settings.megadetector_output_dir))
        else:
            raise RuntimeError(
                "No MegaDetector source selected. Use --run-megadetector or --megadetector-output-dir."
            )

        scoring_result = score_raw_crops(
            output_dir=output_dir,
            detections=md_result["detections"],
            crop_exports=md_result["crop_exports"],
            scoring_settings=scoring_settings,
        )
        mmpose_manifest_path, mmpose_manifest_rows = build_mmpose_manifest(
            output_dir,
            scoring_result["mmpose_candidate_rows"],
        )

        preview_frames_written = len(preview_materialized)
        detector_input_rows = len(detector_rows)
        detector_input_frame_paths_available = sum(
            1 for row in detector_rows if clean(row.get("detector_input_frame_path")) and Path(clean(row.get("detector_input_frame_path"))).exists()
        )
        preview_frames_reused_for_detector_input = sum(
            1
            for row in detector_rows
            if clean(row.get("detector_input_frame_path"))
            and not bool_from_text(clean(row.get("detector_input_materialized_now")), False)
        )
        raw_megadetector_crops_written = int(md_result.get("raw_megadetector_crops_written", 0))
        total_media_files_written = (
            preview_frames_written
            + additional_detector_input_frames_materialized
            + raw_megadetector_crops_written
        )

        manifest_path = output_dir / "manifest.json"
        storage_ledger_path = output_dir / "FrameSamplerDetector-storage-ledger.json"

        manifest_payload = {
            "script_name": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "rewrite_step": REWRITE_STEP,
            "component": COMPONENT_NAME,
            "status": "PASS",
            "pipeline_completion_state": "raw_crop_candidates_ready_for_mmpose",
            "created_utc": utc_timestamp(),
            "source_video": str(source_video),
            "source_media_context": sampler_settings.source_media_context,
            "source_video_is_canonical": True,
            "source_video_available": source_video.exists(),
            "output_dir": str(output_dir),
            "sampled_frames_csv": str(sampled_frames_csv),
            "sampled_frames_jsonl": str(sampled_frames_jsonl),
            "detector_input_frames_csv": str(detector_input_frames_csv),
            "megadetector_detections_csv": md_result.get("detections_csv", ""),
            "crop_exports_csv": md_result.get("crop_exports_csv", ""),
            "raw_crop_retention_scores_csv": scoring_result["retention_scores_csv"],
            "bird_candidates_csv": scoring_result["bird_candidates_csv"],
            "context_detections_csv": scoring_result["context_csv"],
            "mmpose_input_manifest_csv": str(mmpose_manifest_path),
            "raw_crop_retention_summary_json": scoring_result["summary_json"],
            "frame_records_written": len(frame_rows),
            "preview_frames_written": preview_frames_written,
            "detector_input_rows": detector_input_rows,
            "detector_input_frame_paths_available": detector_input_frame_paths_available,
            "preview_frames_reused_for_detector_input": preview_frames_reused_for_detector_input,
            "additional_detector_input_frames_materialized": additional_detector_input_frames_materialized,
            "raw_megadetector_crops_written": raw_megadetector_crops_written,
            "total_media_files_written": total_media_files_written,
            "raw_crop_scoring_policy": RAW_CROP_SCORING_POLICY,
            "raw_crop_score_rows": len(scoring_result["scored_rows"]),
            "bird_candidate_rows": len(scoring_result["bird_candidate_rows"]),
            "context_detection_rows": len(scoring_result["context_rows"]),
            "mmpose_input_rows": len(mmpose_manifest_rows),
            "database_mutation": DATABASE_MUTATION,
            "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
            "broad_media_export": False,
            "outputs_are_purgeable": True,
            "sampler_settings": asdict(sampler_settings),
            "detector_settings": asdict(detector_settings),
            "raw_crop_scoring_settings": asdict(scoring_settings),
        }
        write_json(manifest_path, manifest_payload)

        storage_ledger_payload = {
            "script_name": SCRIPT_NAME,
            "script_version": SCRIPT_VERSION,
            "component": COMPONENT_NAME,
            "output_dir": str(output_dir),
            "source_video_is_canonical": True,
            "outputs_are_purgeable": True,
            "database_mutation": DATABASE_MUTATION,
            "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
            "broad_media_export": False,
            "preview_frames_written": preview_frames_written,
            "additional_detector_input_frames_materialized": additional_detector_input_frames_materialized,
            "raw_megadetector_crops_written": raw_megadetector_crops_written,
            "total_media_files_written": total_media_files_written,
            "notes": [
                "Preview frames, detector-input frames, and raw MegaDetector crops are debug/cache artifacts.",
                "The source video remains canonical.",
                "Downstream durable evidence should be committed by a later explicit stage, not here.",
            ],
        }
        write_json(storage_ledger_path, storage_ledger_payload)

        status_lines = [
            f"script_name = {SCRIPT_NAME}",
            f"script_version = {SCRIPT_VERSION}",
            f"rewrite_step = {REWRITE_STEP}",
            f"component = {COMPONENT_NAME}",
            "status = PASS",
            "pipeline_completion_state = raw_crop_candidates_ready_for_mmpose",
            f"source_video = {source_video}",
            f"source_media_context = {sampler_settings.source_media_context}",
            "source_video_is_canonical = true",
            f"source_video_available = {str(source_video.exists()).lower()}",
            f"output_dir = {output_dir}",
            f"sampled_frames_csv = {sampled_frames_csv}",
            f"sampled_frames_jsonl = {sampled_frames_jsonl}",
            f"detector_input_frames_csv = {detector_input_frames_csv}",
            f"manifest_path = {manifest_path}",
            f"storage_ledger_path = {storage_ledger_path}",
            f"frame_records_written = {len(frame_rows)}",
            f"preview_frames_written = {preview_frames_written}",
            f"detector_input_rows = {detector_input_rows}",
            f"detector_input_frame_paths_available = {detector_input_frame_paths_available}",
            f"preview_frames_reused_for_detector_input = {preview_frames_reused_for_detector_input}",
            f"additional_detector_input_frames_materialized = {additional_detector_input_frames_materialized}",
            f"raw_megadetector_crops_written = {raw_megadetector_crops_written}",
            f"total_media_files_written = {total_media_files_written}",
            f"raw_crop_scoring_policy = {RAW_CROP_SCORING_POLICY}",
            f"raw_crop_score_rows = {len(scoring_result['scored_rows'])}",
            f"bird_candidate_rows = {len(scoring_result['bird_candidate_rows'])}",
            f"context_detection_rows = {len(scoring_result['context_rows'])}",
            f"mmpose_input_rows = {len(mmpose_manifest_rows)}",
            "database_mutation = false",
            "durable_evidence_written = false",
            "broad_media_export = false",
            "outputs_are_purgeable = true",
        ]
        status_path = write_status(output_dir, status_lines)

        for line in [
            f"script_name = {SCRIPT_NAME}",
            f"script_version = {SCRIPT_VERSION}",
            f"rewrite_step = {REWRITE_STEP}",
            f"component = {COMPONENT_NAME}",
            f"python_executable = {sys.executable}",
            f"source = {source_video}",
            f"output_root = {output_root}",
            f"settings = {settings_path or ''}",
            "status = PASS",
            "pipeline_completion_state = raw_crop_candidates_ready_for_mmpose",
            f"output_dir = {output_dir}",
            f"sampled_frames_csv = {sampled_frames_csv}",
            f"detector_input_frames_csv = {detector_input_frames_csv}",
            f"mmpose_input_manifest_csv = {mmpose_manifest_path}",
            f"frame_records_written = {len(frame_rows)}",
            f"detector_input_rows = {detector_input_rows}",
            f"detector_input_frame_paths_available = {detector_input_frame_paths_available}",
            f"preview_frames_reused_for_detector_input = {preview_frames_reused_for_detector_input}",
            f"additional_detector_input_frames_materialized = {additional_detector_input_frames_materialized}",
            f"raw_megadetector_crops_written = {raw_megadetector_crops_written}",
            f"total_media_files_written = {total_media_files_written}",
            "database_mutation = false",
            "durable_evidence_written = false",
            "broad_media_export = false",
            "outputs_are_purgeable = true",
        ]:
            print(line)

        return 0

    except Exception as exc:
        write_failure_status(output_dir, source_video, output_root, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
