# buildPoseHandoff-v0.1.py | v0.1 | 2026-07-07 PDT | Build Birdbill pose handoff from MMPose smoke outputs

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


SCRIPT_NAME = "buildPoseHandoff-v0.1.py"
SCRIPT_VERSION = "v0.1"
COMPONENT = "PoseHandoffBuilder"

DEFAULT_MMP_INPUT_MANIFEST = Path(r"D:\birdbill\output\debug\smart-frame-sampler-v04-md-consume-001\mmpose-input-manifest.csv")
DEFAULT_KEYPOINTS_CSV = Path(r"D:\birdbill\output\debug\mmpose-manifest-smoke-001\mmpose-keypoints.csv")
DEFAULT_CANDIDATE_RESULTS_CSV = Path(r"D:\birdbill\output\debug\mmpose-manifest-smoke-001\mmpose-candidate-results.csv")
DEFAULT_OUTPUT_DIR = Path(r"D:\birdbill\output\debug\current-pose-handoff")

HEAD_KEYPOINTS = {0, 1, 2, 3}
BODY_KEYPOINTS = {3, 4, 5, 8, 11, 14}
NOSE_INDEX = 2
NECK_INDEX = 3
TAIL_ROOT_INDEX = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a compact Birdbill pose handoff manifest from MMPose candidate/keypoint outputs."
    )
    parser.add_argument("--mmpose-input-manifest", type=Path, default=DEFAULT_MMP_INPUT_MANIFEST)
    parser.add_argument("--keypoints-csv", type=Path, default=DEFAULT_KEYPOINTS_CSV)
    parser.add_argument("--candidate-results-csv", type=Path, default=DEFAULT_CANDIDATE_RESULTS_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--score-threshold", type=float, default=0.15)
    parser.add_argument("--roi-pad-ratio", type=float, default=0.35)
    parser.add_argument("--min-roi-pad-px", type=float, default=24.0)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def to_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def get_image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return None, None


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return f"{value:.3f}"
    return str(value)


@dataclass
class PoseHandoffRow:
    mmpose_input_id: str
    detection_id: str
    frame_id: str
    source_video: str
    source_frame_index: str
    camera_local_time_seconds: str
    raw_crop_path: str
    raw_crop_width: str
    raw_crop_height: str
    retention_decision: str
    retention_score: str

    mmpose_ok: bool
    mmpose_keypoint_count: int
    mmpose_visible_keypoint_count: int
    visible_head_keypoint_count: int
    visible_body_keypoint_count: int
    nose_visible: bool
    neck_visible: bool
    tail_root_visible: bool

    bill_base_proxy_x: str
    bill_base_proxy_y: str
    neck_proxy_x: str
    neck_proxy_y: str
    tail_root_proxy_x: str
    tail_root_proxy_y: str

    head_roi_x1: str
    head_roi_y1: str
    head_roi_x2: str
    head_roi_y2: str
    body_roi_x1: str
    body_roi_y1: str
    body_roi_x2: str
    body_roi_y2: str

    dlc_billtip_candidate: bool
    smart_cropper_candidate: bool
    pose_handoff_decision: str
    notes: str


def make_roi(points: list[tuple[float, float]], image_w: int | None, image_h: int | None, pad_ratio: float, min_pad: float) -> tuple[float, float, float, float] | None:
    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1 = min(xs)
    y1 = min(ys)
    x2 = max(xs)
    y2 = max(ys)

    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    pad = max(min_pad, max(width, height) * pad_ratio)

    x1 -= pad
    y1 -= pad
    x2 += pad
    y2 += pad

    if image_w is not None:
        x1 = max(0.0, min(float(image_w), x1))
        x2 = max(0.0, min(float(image_w), x2))
    if image_h is not None:
        y1 = max(0.0, min(float(image_h), y1))
        y2 = max(0.0, min(float(image_h), y2))

    return x1, y1, x2, y2


def main() -> int:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "pose-handoff-report.txt"
    handoff_csv = output_dir / "pose-handoff-manifest.csv"

    report_lines: list[str] = []

    def report(line: str = "") -> None:
        report_lines.append(line)

    started = time.time()
    status = "FAIL"
    failure_reason = ""

    report(f"{SCRIPT_NAME} | {SCRIPT_VERSION} | 2026-07-07 PDT | Build Birdbill pose handoff from MMPose smoke outputs")
    report(f"generated={time.strftime('%Y-%m-%d %H:%M:%S')}")
    report(f"script_name={SCRIPT_NAME}")
    report(f"script_version={SCRIPT_VERSION}")
    report(f"component={COMPONENT}")
    report(f"python_executable={sys.executable}")
    report(f"mmpose_input_manifest={args.mmpose_input_manifest}")
    report(f"keypoints_csv={args.keypoints_csv}")
    report(f"candidate_results_csv={args.candidate_results_csv}")
    report(f"output_dir={output_dir}")
    report(f"score_threshold={args.score_threshold}")
    report("database_mutation=false")
    report("durable_evidence_written=false")
    report("media_files_written=0")
    report("")

    try:
        required = [
            ("mmpose_input_manifest", args.mmpose_input_manifest),
            ("keypoints_csv", args.keypoints_csv),
            ("candidate_results_csv", args.candidate_results_csv),
        ]
        missing = []
        report("PATH CHECKS")
        for label, path in required:
            exists = path.exists()
            report(f"{label}_exists={exists} path={path}")
            if not exists:
                missing.append(label)
        if missing:
            raise RuntimeError("Missing required input(s): " + ", ".join(missing))

        input_rows = read_csv(args.mmpose_input_manifest)
        keypoint_rows = read_csv(args.keypoints_csv)
        candidate_result_rows = read_csv(args.candidate_results_csv)

        report("")
        report("INPUT COUNTS")
        report(f"mmpose_input_rows={len(input_rows)}")
        report(f"keypoint_rows={len(keypoint_rows)}")
        report(f"candidate_result_rows={len(candidate_result_rows)}")

        input_by_id = {r.get("mmpose_input_id", ""): r for r in input_rows}
        result_by_id = {r.get("mmpose_input_id", ""): r for r in candidate_result_rows}

        keypoints_by_id: dict[str, list[dict[str, str]]] = {}
        for row in keypoint_rows:
            keypoints_by_id.setdefault(row.get("mmpose_input_id", ""), []).append(row)

        handoff_rows: list[PoseHandoffRow] = []

        for mmpose_input_id, input_row in input_by_id.items():
            result_row = result_by_id.get(mmpose_input_id, {})
            kps = keypoints_by_id.get(mmpose_input_id, [])

            visible_kps = [kp for kp in kps if truthy(kp.get("visible")) and to_float(kp.get("score"), 0.0) >= args.score_threshold]
            visible_head = [kp for kp in visible_kps if int(to_float(kp.get("keypoint_index"), -1)) in HEAD_KEYPOINTS]
            visible_body = [kp for kp in visible_kps if int(to_float(kp.get("keypoint_index"), -1)) in BODY_KEYPOINTS]

            def kp_by_index(index: int) -> dict[str, str] | None:
                for kp in visible_kps:
                    if int(to_float(kp.get("keypoint_index"), -1)) == index:
                        return kp
                return None

            nose = kp_by_index(NOSE_INDEX)
            neck = kp_by_index(NECK_INDEX)
            tail_root = kp_by_index(TAIL_ROOT_INDEX)

            raw_crop_path = Path(input_row.get("raw_crop_path", ""))
            image_w, image_h = get_image_size(raw_crop_path)

            head_points = [(to_float(kp.get("x")), to_float(kp.get("y"))) for kp in visible_head]
            head_points = [(x, y) for x, y in head_points if not math.isnan(x) and not math.isnan(y)]

            body_points = [(to_float(kp.get("x")), to_float(kp.get("y"))) for kp in visible_body]
            body_points = [(x, y) for x, y in body_points if not math.isnan(x) and not math.isnan(y)]

            head_roi = make_roi(head_points, image_w, image_h, args.roi_pad_ratio, args.min_roi_pad_px)
            body_roi = make_roi(body_points, image_w, image_h, args.roi_pad_ratio, args.min_roi_pad_px)

            mmpose_ok = truthy(result_row.get("ok"))
            nose_visible = nose is not None
            neck_visible = neck is not None
            tail_root_visible = tail_root is not None

            dlc_billtip_candidate = mmpose_ok and (nose_visible or len(visible_head) >= 2)
            smart_cropper_candidate = mmpose_ok and (len(visible_body) >= 2 or (neck_visible and tail_root_visible))

            if dlc_billtip_candidate and smart_cropper_candidate:
                decision = "dlc_billtip_and_smart_cropper_candidate"
            elif dlc_billtip_candidate:
                decision = "dlc_billtip_candidate"
            elif smart_cropper_candidate:
                decision = "smart_cropper_candidate"
            elif mmpose_ok:
                decision = "mmpose_ok_but_low_pose_utility"
            else:
                decision = "mmpose_failed"

            notes = []
            if not raw_crop_path.exists():
                notes.append("raw_crop_missing")
            if image_w is None or image_h is None:
                notes.append("image_size_unreadable")
            if not nose_visible:
                notes.append("nose_not_visible")
            if not neck_visible:
                notes.append("neck_not_visible")

            row = PoseHandoffRow(
                mmpose_input_id=mmpose_input_id,
                detection_id=input_row.get("detection_id", ""),
                frame_id=input_row.get("frame_id", ""),
                source_video=input_row.get("source_video", ""),
                source_frame_index=input_row.get("source_frame_index", ""),
                camera_local_time_seconds=input_row.get("camera_local_time_seconds", ""),
                raw_crop_path=str(raw_crop_path),
                raw_crop_width=fmt(float(image_w) if image_w is not None else math.nan),
                raw_crop_height=fmt(float(image_h) if image_h is not None else math.nan),
                retention_decision=input_row.get("retention_decision", ""),
                retention_score=input_row.get("retention_score", ""),

                mmpose_ok=mmpose_ok,
                mmpose_keypoint_count=int(to_float(result_row.get("keypoint_count"), len(kps))),
                mmpose_visible_keypoint_count=int(to_float(result_row.get("visible_keypoint_count"), len(visible_kps))),
                visible_head_keypoint_count=len(visible_head),
                visible_body_keypoint_count=len(visible_body),
                nose_visible=nose_visible,
                neck_visible=neck_visible,
                tail_root_visible=tail_root_visible,

                bill_base_proxy_x=fmt(to_float(nose.get("x")) if nose else math.nan),
                bill_base_proxy_y=fmt(to_float(nose.get("y")) if nose else math.nan),
                neck_proxy_x=fmt(to_float(neck.get("x")) if neck else math.nan),
                neck_proxy_y=fmt(to_float(neck.get("y")) if neck else math.nan),
                tail_root_proxy_x=fmt(to_float(tail_root.get("x")) if tail_root else math.nan),
                tail_root_proxy_y=fmt(to_float(tail_root.get("y")) if tail_root else math.nan),

                head_roi_x1=fmt(head_roi[0] if head_roi else math.nan),
                head_roi_y1=fmt(head_roi[1] if head_roi else math.nan),
                head_roi_x2=fmt(head_roi[2] if head_roi else math.nan),
                head_roi_y2=fmt(head_roi[3] if head_roi else math.nan),
                body_roi_x1=fmt(body_roi[0] if body_roi else math.nan),
                body_roi_y1=fmt(body_roi[1] if body_roi else math.nan),
                body_roi_x2=fmt(body_roi[2] if body_roi else math.nan),
                body_roi_y2=fmt(body_roi[3] if body_roi else math.nan),

                dlc_billtip_candidate=dlc_billtip_candidate,
                smart_cropper_candidate=smart_cropper_candidate,
                pose_handoff_decision=decision,
                notes=";".join(notes),
            )
            handoff_rows.append(row)

        fieldnames = list(asdict(handoff_rows[0]).keys()) if handoff_rows else list(PoseHandoffRow.__dataclass_fields__.keys())
        write_csv(handoff_csv, [asdict(r) for r in handoff_rows], fieldnames)

        dlc_count = sum(1 for r in handoff_rows if r.dlc_billtip_candidate)
        cropper_count = sum(1 for r in handoff_rows if r.smart_cropper_candidate)

        report("")
        report("SUMMARY")
        report(f"pose_handoff_rows={len(handoff_rows)}")
        report(f"dlc_billtip_candidate_rows={dlc_count}")
        report(f"smart_cropper_candidate_rows={cropper_count}")
        report(f"pose_handoff_manifest={handoff_csv}")
        status = "PASS" if handoff_rows else "FAIL"

    except Exception as exc:
        failure_reason = str(exc)
        report("")
        report("ERROR")
        report(f"error={failure_reason}")

    elapsed = time.time() - started
    report("")
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
    print(f"pose_handoff_manifest = {handoff_csv}")
    print("database_mutation = false")
    print("durable_evidence_written = false")
    print("media_files_written = 0")

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
