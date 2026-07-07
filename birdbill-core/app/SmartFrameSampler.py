# SmartFrameSampler.py | v0.3 | 2026-07-07 PDT | Birdbill Step 7 promoted SmartFrameSampler app module
from __future__ import annotations

import argparse
import configparser
import csv
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
SCRIPT_VERSION = "v0.3"
REWRITE_STEP = "7"
COMPONENT_NAME = "SmartFrameSampler"


@dataclass(frozen=True)
class SamplerSettings:
    sample_every_seconds: float = 2.0
    max_frame_records: int = 120
    burst_offsets_seconds: tuple[float, ...] = (-0.12, 0.0, 0.12)
    preview_frame_limit: int = 24
    jpeg_quality: int = 92
    clear_output: bool = False
    source_media_context: str = "app_sampler"


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
    anchor_time_seconds: float
    burst_index: int
    burst_offset_seconds: float
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
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return cleaned or fallback


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


def load_settings(settings_path: Path | None, cli: argparse.Namespace) -> SamplerSettings:
    defaults = SamplerSettings()
    config = configparser.ConfigParser()
    if settings_path is not None and settings_path.exists():
        config.read(settings_path, encoding="utf-8")
    video = config["video"] if config.has_section("video") else {}

    sample_every_seconds = float(
        cli.sample_every_seconds if cli.sample_every_seconds is not None else video.get("sample_every_seconds", defaults.sample_every_seconds)
    )
    max_frame_records = int(
        cli.max_frame_records
        if cli.max_frame_records is not None
        else video.get("max_frame_records", video.get("max_frames_per_video", defaults.max_frame_records))
    )
    burst_offsets_seconds = parse_float_tuple(
        cli.burst_offsets_seconds if cli.burst_offsets_seconds is not None else video.get("burst_offsets_seconds", None),
        defaults.burst_offsets_seconds,
    )
    preview_frame_limit = int(
        cli.preview_frame_limit if cli.preview_frame_limit is not None else video.get("preview_frame_limit", defaults.preview_frame_limit)
    )
    jpeg_quality = int(cli.jpeg_quality if cli.jpeg_quality is not None else video.get("jpeg_quality", defaults.jpeg_quality))
    clear_output = bool_from_text(
        str(cli.clear_output) if cli.clear_output else video.get("clear_old_sampled_frames", None),
        defaults.clear_output,
    )
    source_media_context = cli.source_media_context or video.get("source_media_context", defaults.source_media_context)

    if sample_every_seconds <= 0:
        raise ValueError("sample_every_seconds must be greater than zero")
    if max_frame_records <= 0:
        raise ValueError("max_frame_records must be greater than zero")
    if preview_frame_limit < 0:
        raise ValueError("preview_frame_limit must be zero or greater")
    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be between 1 and 100")

    return SamplerSettings(
        sample_every_seconds=sample_every_seconds,
        max_frame_records=max_frame_records,
        burst_offsets_seconds=burst_offsets_seconds,
        preview_frame_limit=preview_frame_limit,
        jpeg_quality=jpeg_quality,
        clear_output=clear_output,
        source_media_context=source_media_context,
    )


def open_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except Exception as exc:
        raise RuntimeError(
            "OpenCV import failed. SmartFrameSampler needs cv2 in the selected Python environment. "
            f"Original error: {exc}"
        ) from exc


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
                    "anchor_time_seconds": anchor_time,
                    "burst_index": burst_index,
                    "burst_offset_seconds": offset,
                    "is_anchor": abs(offset) < 1e-9,
                }
            )
            if len(planned) >= settings.max_frame_records:
                return planned
    return planned


def materialize_preview_frames(source_video: Path, output_frames_dir: Path, planned: list[dict[str, Any]], settings: SamplerSettings) -> dict[int, str]:
    if settings.preview_frame_limit <= 0:
        return {}
    cv2 = open_cv2()
    output_frames_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video for frame materialization: {source_video}")
    materialized: dict[int, str] = {}
    try:
        for item in planned[: settings.preview_frame_limit]:
            frame_index = int(item["source_frame_index"])
            frame_path = output_frames_dir / f"{item['frame_id']}.jpg"
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            written = cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(settings.jpeg_quality)])
            if written:
                materialized[frame_index] = str(frame_path)
    finally:
        cap.release()
    return materialized


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


def run_smart_frame_sampler(
    source_video: str | Path,
    output_root: str | Path,
    run_id: str | None = None,
    settings: SamplerSettings | None = None,
    settings_path: str | Path | None = None,
) -> dict[str, Any]:
    source_video = Path(source_video)
    output_root = Path(output_root)
    settings = settings or SamplerSettings()
    started_at = utc_timestamp()

    if not source_video.exists():
        raise FileNotFoundError(f"Source video missing: {source_video}")

    output_dir = prepare_output_dir(output_root, make_run_id(source_video, run_id), settings.clear_output)
    frames_dir = output_dir / "preview-frames"
    metadata = read_video_metadata(source_video)
    planned = build_frame_plan(source_video, settings, metadata)
    materialized = materialize_preview_frames(source_video, frames_dir, planned, settings)

    records: list[FrameRecord] = []
    for item in planned:
        frame_index = int(item["source_frame_index"])
        frame_path = materialized.get(frame_index, "")
        records.append(
            FrameRecord(
                frame_id=str(item["frame_id"]),
                sequence_id=str(item["sequence_id"]),
                source_video=str(source_video),
                source_media_context=settings.source_media_context,
                source_video_is_canonical=True,
                source_video_available=True,
                source_frame_index=frame_index,
                frame_time_seconds=round(float(item["frame_time_seconds"]), 6),
                anchor_index=int(item["anchor_index"]),
                anchor_time_seconds=round(float(item["anchor_time_seconds"]), 6),
                burst_index=int(item["burst_index"]),
                burst_offset_seconds=round(float(item["burst_offset_seconds"]), 6),
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

    rows = [asdict(record) for record in records]
    fieldnames = list(FrameRecord.__dataclass_fields__.keys())
    sampled_csv = output_dir / "sampled-frames.csv"
    sampled_jsonl = output_dir / "sampled-frames.jsonl"
    manifest_path = output_dir / "manifest.json"
    ledger_path = output_dir / "SmartFrameSampler-storage-ledger.json"
    status_path = output_dir / "status.txt"

    write_csv(sampled_csv, rows, fieldnames)
    write_jsonl(sampled_jsonl, rows)
    media_files_written = len(materialized)

    manifest = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
        "component": COMPONENT_NAME,
        "status": "PASS",
        "started_at": started_at,
        "completed_at": utc_timestamp(),
        "source_video": str(source_video),
        "source_media_context": settings.source_media_context,
        "source_video_is_canonical": True,
        "source_video_available": True,
        "settings_path": str(settings_path) if settings_path else "",
        "settings": asdict(settings),
        "output_dir": str(output_dir),
        "sampled_frames_csv": str(sampled_csv),
        "sampled_frames_jsonl": str(sampled_jsonl),
        "manifest_path": str(manifest_path),
        "storage_ledger_path": str(ledger_path),
        "frame_records_written": len(records),
        "preview_frames_written": media_files_written,
        "media_files_written": media_files_written,
        "database_mutation": False,
        "durable_evidence_written": False,
        "broad_media_export": False,
        "outputs_are_purgeable": True,
        "metadata": metadata,
    }

    ledger = {
        "script_name": SCRIPT_NAME,
        "script_version": SCRIPT_VERSION,
        "rewrite_step": REWRITE_STEP,
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
                "files_written": media_files_written,
            },
            "manifest_and_ledger": {
                "paths": [str(manifest_path), str(ledger_path), str(status_path)],
                "role": "audit report",
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
        f"source_video = {source_video}",
        f"source_media_context = {settings.source_media_context}",
        "source_video_is_canonical = true",
        "source_video_available = true",
        f"output_dir = {output_dir}",
        f"sampled_frames_csv = {sampled_csv}",
        f"sampled_frames_jsonl = {sampled_jsonl}",
        f"manifest_path = {manifest_path}",
        f"storage_ledger_path = {ledger_path}",
        f"frame_records_written = {len(records)}",
        f"preview_frames_written = {media_files_written}",
        f"media_files_written = {media_files_written}",
        "database_mutation = false",
        "durable_evidence_written = false",
        "broad_media_export = false",
        "outputs_are_purgeable = true",
    ]
    status_path.write_text("\n".join(status_lines) + "\n", encoding="utf-8")
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Birdbill SmartFrameSampler app module")
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
        settings = load_settings(settings_path, args)
        manifest = run_smart_frame_sampler(
            source_video=Path(args.source),
            output_root=Path(args.output_root),
            run_id=args.run_id,
            settings=settings,
            settings_path=settings_path,
        )
        print("status = PASS")
        print(f"output_dir = {manifest['output_dir']}")
        print(f"sampled_frames_csv = {manifest['sampled_frames_csv']}")
        print(f"frame_records_written = {manifest['frame_records_written']}")
        print(f"preview_frames_written = {manifest['preview_frames_written']}")
        print("database_mutation = false")
        print("durable_evidence_written = false")
        print("broad_media_export = false")
        return 0
    except Exception as exc:
        print("status = FAIL")
        print(f"error_type = {type(exc).__name__}")
        print(f"error = {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
