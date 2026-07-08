# MMPose.py | v0.1 | 2026-07-07 PDT | Run MMPose AP-10K keypoint inference from Birdbill candidate manifest

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SCRIPT_NAME = "MMPose.py"
SCRIPT_VERSION = "v0.1"
COMPONENT = "MMPose"

DEFAULT_MANIFEST = Path(r"D:\birdbill\output\debug\current-frame-sampler-detector-full-gate\mmpose-input-manifest.csv")
DEFAULT_CONFIG = Path(r"D:\birdbill\modules\mmpose\models\rtmpose-m_8xb64-210e_ap10k-256x256.py")
DEFAULT_CHECKPOINT = Path(r"D:\birdbill\modules\mmpose\models\rtmpose-m_simcc-ap10k_pt-aic-coco_210e-256x256-7a041aa1_20230206.pth")
DEFAULT_OUTPUT_DIR = Path(r"D:\birdbill\output\debug\current-mmpose")
DEFAULT_DEVICE = "cpu"
DEFAULT_SCORE_THRESHOLD = 0.15
DEFAULT_LIMIT = 0

DATABASE_MUTATION = False
DURABLE_EVIDENCE_WRITTEN = False

AP10K_LABELS = [
    "L_Eye",
    "R_Eye",
    "Nose",
    "Neck",
    "Tail_Root",
    "L_Shoulder",
    "L_Elbow",
    "L_F_Paw",
    "R_Shoulder",
    "R_Elbow",
    "R_F_Paw",
    "L_Hip",
    "L_Knee",
    "L_B_Paw",
    "R_Hip",
    "R_Knee",
    "R_B_Paw",
]

BIRDBILL_LABELS = [
    "head anchor / eye?",
    "head anchor / eye?",
    "bill-head front anchor",
    "neck / gorget-top proxy",
    "tail base / rear body",
    "left wing root / shoulder",
    "left wing mid / blur proxy",
    "left wingtip/artifact candidate",
    "right wing root / shoulder",
    "right wing mid / blur proxy",
    "right wingtip/artifact candidate",
    "left rear body / flank",
    "left lower body / tail proxy",
    "left tail/wing/artifact candidate",
    "right rear body / flank",
    "right lower body / tail proxy",
    "right tail/wing/artifact candidate",
]

BIRDBILL_USEFULNESS = [
    "useful if on head",
    "useful if on head",
    "high priority",
    "high priority",
    "high priority",
    "high priority",
    "unstable",
    "risky",
    "high priority",
    "unstable",
    "risky",
    "medium priority",
    "unstable",
    "risky",
    "medium priority",
    "unstable",
    "risky",
]


@dataclass
class CandidateInput:
    row_index: int
    mmpose_input_id: str
    retention_score_id: str
    detection_id: str
    frame_id: str
    source_video: str
    source_frame_index: str
    camera_local_time_seconds: str
    raw_crop_path: Path
    detector_input_frame_path: str
    retention_decision: str
    retention_score: str


@dataclass
class KeypointRecord:
    candidate_index: int
    mmpose_input_id: str
    detection_id: str
    raw_crop_path: str
    keypoint_index: int
    ap10k_label: str
    birdbill_label: str
    usefulness: str
    x: float
    y: float
    score: float
    visible: bool


@dataclass
class CandidateResult:
    candidate_index: int
    mmpose_input_id: str
    detection_id: str
    raw_crop_path: str
    ok: bool
    error: str
    keypoint_count: int
    visible_keypoint_count: int
    nose_visible: bool
    neck_visible: bool
    backend: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run MMPose AP-10K keypoint inference from a Birdbill mmpose-input-manifest.csv."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--score-threshold", type=float, default=DEFAULT_SCORE_THRESHOLD)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Maximum manifest rows to process. Use 0 for all rows.",
    )
    parser.add_argument("--no-overlays", action="store_true")
    parser.add_argument(
        "--clear-output",
        action="store_true",
        help="Delete and recreate the output directory before running.",
    )
    return parser.parse_args()


def clean_jsonable(value: Any) -> Any:
    try:
        import numpy as np

        if isinstance(value, (np.floating, np.integer)):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:
        pass

    try:
        import torch

        if isinstance(value, torch.Tensor):
            return value.detach().cpu().tolist()
    except Exception:
        pass

    if isinstance(value, dict):
        return {str(k): clean_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return clean_jsonable(value.__dict__)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def extract_keypoints_from_result(result: Any) -> tuple[list[list[float]], list[float]]:
    pred_instances = getattr(result, "pred_instances", None)
    if pred_instances is None:
        return [], []

    keypoints_json = clean_jsonable(getattr(pred_instances, "keypoints", None))
    scores_json = clean_jsonable(getattr(pred_instances, "keypoint_scores", None))

    keypoints: list[list[float]] = []
    scores: list[float] = []

    if isinstance(keypoints_json, list) and keypoints_json:
        first = keypoints_json[0]
        if isinstance(first, list) and first and isinstance(first[0], list):
            keypoints = [[float(x[0]), float(x[1])] for x in first if len(x) >= 2]
        elif isinstance(first, list) and len(first) >= 2:
            keypoints = [[float(x[0]), float(x[1])] for x in keypoints_json if len(x) >= 2]

    if isinstance(scores_json, list) and scores_json:
        if isinstance(scores_json[0], list):
            scores = [float(x) for x in scores_json[0]]
        else:
            scores = [float(x) for x in scores_json]

    return keypoints, scores


def read_manifest(path: Path, limit: int) -> list[CandidateInput]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if limit > 0:
        rows = rows[:limit]

    candidates: list[CandidateInput] = []
    for row_index, row in enumerate(rows):
        candidates.append(
            CandidateInput(
                row_index=row_index,
                mmpose_input_id=row.get("mmpose_input_id", ""),
                retention_score_id=row.get("retention_score_id", ""),
                detection_id=row.get("detection_id", ""),
                frame_id=row.get("frame_id", ""),
                source_video=row.get("source_video", ""),
                source_frame_index=row.get("source_frame_index", ""),
                camera_local_time_seconds=row.get("camera_local_time_seconds", ""),
                raw_crop_path=Path(row.get("raw_crop_path", "")),
                detector_input_frame_path=row.get("detector_input_frame_path", ""),
                retention_decision=row.get("retention_decision", ""),
                retention_score=row.get("retention_score", ""),
            )
        )

    return candidates


def build_keypoint_records(
    candidate: CandidateInput,
    keypoints: list[list[float]],
    scores: list[float],
    threshold: float,
) -> list[KeypointRecord]:
    records: list[KeypointRecord] = []

    for keypoint_index, keypoint in enumerate(keypoints):
        if len(keypoint) < 2:
            continue

        score = scores[keypoint_index] if keypoint_index < len(scores) else 1.0
        records.append(
            KeypointRecord(
                candidate_index=candidate.row_index,
                mmpose_input_id=candidate.mmpose_input_id,
                detection_id=candidate.detection_id,
                raw_crop_path=str(candidate.raw_crop_path),
                keypoint_index=keypoint_index,
                ap10k_label=AP10K_LABELS[keypoint_index]
                if keypoint_index < len(AP10K_LABELS)
                else f"kp{keypoint_index}",
                birdbill_label=BIRDBILL_LABELS[keypoint_index]
                if keypoint_index < len(BIRDBILL_LABELS)
                else "unknown",
                usefulness=BIRDBILL_USEFULNESS[keypoint_index]
                if keypoint_index < len(BIRDBILL_USEFULNESS)
                else "unknown",
                x=float(keypoint[0]),
                y=float(keypoint[1]),
                score=float(score),
                visible=float(score) >= float(threshold),
            )
        )

    return records


def draw_overlay(image_path: Path, output_path: Path, records: list[KeypointRecord], threshold: float) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(image)

        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        for record in records:
            if record.score < threshold:
                continue

            radius = 4
            x = record.x
            y = record.y
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline="red", width=2)
            label = f"{record.keypoint_index}:{record.ap10k_label} {record.score:.2f}"
            draw.text((x + 6, y + 2), label, fill="yellow", font=font)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, quality=92)
        return True

    except Exception:
        return False


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()

    output_dir: Path = args.output_dir
    if args.clear_output and output_dir.exists():
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "mmpose-report.txt"
    predictions_csv = output_dir / "mmpose-keypoints.csv"
    predictions_json = output_dir / "mmpose-predictions.json"
    results_csv = output_dir / "mmpose-candidate-results.csv"
    overlays_dir = output_dir / "overlays"

    report_lines: list[str] = []

    def report(line: str = "") -> None:
        report_lines.append(line)

    started = time.time()
    status = "FAIL"
    failure_reason = ""
    candidate_results: list[CandidateResult] = []
    keypoint_records: list[KeypointRecord] = []
    overlay_count = 0
    backend = "not_loaded"

    report(f"{SCRIPT_NAME} | {SCRIPT_VERSION} | 2026-07-07 PDT | Run MMPose AP-10K keypoint inference from Birdbill candidate manifest")
    report(f"generated={time.strftime('%Y-%m-%d %H:%M:%S')}")
    report(f"script_name={SCRIPT_NAME}")
    report(f"script_version={SCRIPT_VERSION}")
    report(f"component={COMPONENT}")
    report(f"python_executable={sys.executable}")
    report(f"manifest={args.manifest}")
    report(f"config={args.config}")
    report(f"checkpoint={args.checkpoint}")
    report(f"output_dir={output_dir}")
    report(f"device={args.device}")
    report(f"score_threshold={args.score_threshold}")
    report(f"limit={args.limit}")
    report(f"database_mutation={str(DATABASE_MUTATION).lower()}")
    report(f"durable_evidence_written={str(DURABLE_EVIDENCE_WRITTEN).lower()}")
    report("source_video_modified=false")
    report("")

    try:
        report("PATH CHECKS")
        required_paths = [
            ("manifest", args.manifest),
            ("config", args.config),
            ("checkpoint", args.checkpoint),
        ]

        missing = []
        for label, path in required_paths:
            exists = path.exists()
            report(f"{label}_exists={exists} path={path}")
            if not exists:
                missing.append(label)

        if missing:
            raise RuntimeError("Missing required path(s): " + ", ".join(missing))

        candidates = read_manifest(args.manifest, args.limit)

        report("")
        report("INPUT MANIFEST")
        report(f"candidate_rows_loaded={len(candidates)}")

        for candidate in candidates:
            report(
                f"candidate[{candidate.row_index}] "
                f"mmpose_input_id={candidate.mmpose_input_id} "
                f"raw_crop_exists={candidate.raw_crop_path.exists()} "
                f"raw_crop_path={candidate.raw_crop_path}"
            )

        missing_crops = [str(candidate.raw_crop_path) for candidate in candidates if not candidate.raw_crop_path.exists()]
        if missing_crops:
            raise RuntimeError("Missing raw crop path(s): " + " | ".join(missing_crops))

        if not candidates:
            raise RuntimeError("No candidate rows were loaded from manifest.")

        report("")
        report("IMPORT / MODEL LOAD")

        from mmpose.apis import inference_topdown, init_model

        model = init_model(str(args.config), str(args.checkpoint), device=args.device)
        backend = "mmpose-1.x-init_model/inference_topdown"
        report(f"backend={backend}")

        report("")
        report("INFERENCE")

        for candidate in candidates:
            try:
                raw_result = inference_topdown(model, str(candidate.raw_crop_path))
                result = raw_result[0] if isinstance(raw_result, list) and raw_result else raw_result
                keypoints, scores = extract_keypoints_from_result(result)
                records = build_keypoint_records(candidate, keypoints, scores, args.score_threshold)
                keypoint_records.extend(records)

                visible_count = sum(1 for record in records if record.visible)
                nose_visible = any(record.keypoint_index == 2 and record.visible for record in records)
                neck_visible = any(record.keypoint_index == 3 and record.visible for record in records)

                overlay_written = False
                if not args.no_overlays:
                    overlay_path = overlays_dir / f"mmpose-{candidate.row_index:03d}-{candidate.detection_id}.jpg"
                    overlay_written = draw_overlay(candidate.raw_crop_path, overlay_path, records, args.score_threshold)
                    if overlay_written:
                        overlay_count += 1

                candidate_results.append(
                    CandidateResult(
                        candidate_index=candidate.row_index,
                        mmpose_input_id=candidate.mmpose_input_id,
                        detection_id=candidate.detection_id,
                        raw_crop_path=str(candidate.raw_crop_path),
                        ok=True,
                        error="",
                        keypoint_count=len(records),
                        visible_keypoint_count=visible_count,
                        nose_visible=nose_visible,
                        neck_visible=neck_visible,
                        backend=backend,
                    )
                )

                report(
                    f"candidate[{candidate.row_index}] ok=True "
                    f"keypoints={len(records)} visible={visible_count} "
                    f"nose_visible={nose_visible} neck_visible={neck_visible} "
                    f"overlay_written={overlay_written}"
                )

            except Exception as exc:
                error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                candidate_results.append(
                    CandidateResult(
                        candidate_index=candidate.row_index,
                        mmpose_input_id=candidate.mmpose_input_id,
                        detection_id=candidate.detection_id,
                        raw_crop_path=str(candidate.raw_crop_path),
                        ok=False,
                        error=error_text,
                        keypoint_count=0,
                        visible_keypoint_count=0,
                        nose_visible=False,
                        neck_visible=False,
                        backend=backend,
                    )
                )
                report(f"candidate[{candidate.row_index}] ok=False error={error_text}")

        write_csv(
            predictions_csv,
            [asdict(record) for record in keypoint_records],
            [
                "candidate_index",
                "mmpose_input_id",
                "detection_id",
                "raw_crop_path",
                "keypoint_index",
                "ap10k_label",
                "birdbill_label",
                "usefulness",
                "x",
                "y",
                "score",
                "visible",
            ],
        )

        write_csv(
            results_csv,
            [asdict(record) for record in candidate_results],
            [
                "candidate_index",
                "mmpose_input_id",
                "detection_id",
                "raw_crop_path",
                "ok",
                "error",
                "keypoint_count",
                "visible_keypoint_count",
                "nose_visible",
                "neck_visible",
                "backend",
            ],
        )

        predictions_json.write_text(
            json.dumps(
                {
                    "metadata": {
                        "script_name": SCRIPT_NAME,
                        "script_version": SCRIPT_VERSION,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "python_executable": sys.executable,
                        "manifest": str(args.manifest),
                        "config": str(args.config),
                        "checkpoint": str(args.checkpoint),
                        "device": args.device,
                        "score_threshold": args.score_threshold,
                        "limit": args.limit,
                        "backend": backend,
                        "database_mutation": DATABASE_MUTATION,
                        "durable_evidence_written": DURABLE_EVIDENCE_WRITTEN,
                    },
                    "schema": {
                        "source_model_schema": "AP-10K 17 keypoints",
                        "ap10k_labels": AP10K_LABELS,
                        "birdbill_interpretation_labels": BIRDBILL_LABELS,
                        "birdbill_usefulness": BIRDBILL_USEFULNESS,
                    },
                    "candidate_results": [asdict(record) for record in candidate_results],
                    "keypoint_records": [asdict(record) for record in keypoint_records],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        ok_count = sum(1 for record in candidate_results if record.ok)
        visible_total = sum(record.visible_keypoint_count for record in candidate_results)
        status = "PASS" if ok_count == len(candidate_results) and ok_count > 0 else "PARTIAL"

        report("")
        report("SUMMARY")
        report(f"candidate_rows={len(candidate_results)}")
        report(f"ok_count={ok_count}")
        report(f"keypoint_rows={len(keypoint_records)}")
        report(f"visible_keypoint_total={visible_total}")
        report(f"overlay_images_written={overlay_count}")
        report(f"predictions_csv={predictions_csv}")
        report(f"candidate_results_csv={results_csv}")
        report(f"predictions_json={predictions_json}")

    except Exception as exc:
        failure_reason = str(exc)
        report("")
        report("ERROR")
        report(f"error={failure_reason}")
        report("traceback:")
        report(traceback.format_exc())

    elapsed = time.time() - started

    report("")
    report(f"media_files_written={overlay_count}")
    report(f"elapsed_seconds={elapsed:.3f}")
    report(f"status={status}")
    if failure_reason:
        report(f"failure_reason={failure_reason}")

    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"script_name = {SCRIPT_NAME}")
    print(f"script_version = {SCRIPT_VERSION}")
    print(f"status = {status}")
    print(f"output_dir = {output_dir}")
    print(f"report = {report_path}")
    print(f"predictions_csv = {predictions_csv}")
    print(f"candidate_results_csv = {results_csv}")
    print(f"predictions_json = {predictions_json}")
    print(f"media_files_written = {overlay_count}")
    print(f"database_mutation = {str(DATABASE_MUTATION).lower()}")
    print(f"durable_evidence_written = {str(DURABLE_EVIDENCE_WRITTEN).lower()}")

    return 0 if status in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
