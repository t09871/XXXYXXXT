# billtipTrainerGUI.py | HBMR / Birdbill Bill Base + Tip Trainer | v0.6.0 | 2026-06-30
"""
HBMR / Birdbill Bill Base + Tip Trainer v0.6.0

Purpose:
    Review hummingbird crops and collect high-quality corrected bill base + bill tip labels.

Key v0.6.0 changes:
    - Adds GPT-assisted prediction import as a review layer, not gold labels.
    - Stores GPT bill_base, bill_tip, gorget, label, confidence, reject reason, and notes.
    - Adds overlay toggles and accept buttons for fast human review.
    - Keeps premium export human-approved only; GPT rows are audit/provenance unless accepted.

Key v0.5.1 changes:
    - Adds direct SamplerGUI manifest import for sampler v0.2.x CSV/JSON outputs.
    - Uses sampler candidate_path as the image source without copying images.
    - Imports sampler bill_base_x/bill_base_y as MMPose bill-base hints when available.
    - Keeps temporal neighborhood metadata, best-frame marking, and premium export schema.
    - Adds Next Unreviewed navigation to reduce final training friction.

Recommended workflow:
    1. Start with the existing v0.1.0 billtip-training.json from round one.
    2. Correct base + tip only when the full bill is visible in side view.
    3. Reject aggressively when the tip is missing, cropped, face-on, blurry, occluded, or base is unclear.
    4. Use the premium export for future bill geometry training.

No command line is required. Run with:
    python billtipTrainerGUI.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import subprocess
import tempfile
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except Exception as exc:  # pragma: no cover
    raise RuntimeError("Tkinter is required for billtipTrainerGUI.py") from exc

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

APP_NAME = "HBMR / Birdbill Bill Base + Tip Trainer"
APP_VERSION = "v0.6.0"

LABEL_VALID = "valid_full_bill_side_view"
LABEL_REJECT_TIP_MISSING = "reject_tip_missing"
LABEL_REJECT_BAD_BASE = "reject_bad_base"
LABEL_REJECT_FACE_ON = "reject_face_on"
LABEL_REJECT_BLUR_OCCLUSION = "reject_blur_occlusion"
LABEL_REJECT_OTHER = "reject_other"

LABELS = [
    LABEL_VALID,
    LABEL_REJECT_TIP_MISSING,
    LABEL_REJECT_BAD_BASE,
    LABEL_REJECT_FACE_ON,
    LABEL_REJECT_BLUR_OCCLUSION,
    LABEL_REJECT_OTHER,
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


OUTPUT_COLUMNS = [
    "created_at",
    "updated_at",
    "image_path",
    "image_index",
    "source_row_index",
    "source_video_key",
    "frame_number",
    "time_sec",
    "sequence_id",
    "sequence_position",
    "neighbor_count",
    "best_bill_frame",
    "mmpose_bill_base_x",
    "mmpose_bill_base_y",
    "mmpose_bill_base_score",
    "gpt_label",
    "gpt_bill_base_x",
    "gpt_bill_base_y",
    "gpt_bill_tip_x",
    "gpt_bill_tip_y",
    "gpt_gorget_x",
    "gpt_gorget_y",
    "gpt_confidence",
    "gpt_reject_reason",
    "gpt_notes",
    "gpt_imported_at",
    "gpt_accepted",
    "corrected_bill_base_x",
    "corrected_bill_base_y",
    "clicked_tip_x",
    "clicked_tip_y",
    "corrected_bill_length_px",
    "corrected_bill_angle_deg",
    "label",
    "training_use",
    "is_premium_training_row",
    "old_v01_accepted",
    "old_v01_bill_length_px",
    "old_v01_bill_angle_deg",
    "old_v01_nearest_candidate_method",
    "old_v01_nearest_candidate_distance_px",
    "notes",
]


@dataclass
class ReviewRow:
    created_at: str = ""
    updated_at: str = ""
    image_path: str = ""
    image_index: int = -1
    source_row_index: int = -1

    source_video_key: str = ""
    frame_number: int = -1
    time_sec: float = -1.0
    sequence_id: str = ""
    sequence_position: int = -1
    neighbor_count: int = 0
    best_bill_frame: bool = False

    mmpose_bill_base_x: float = -1.0
    mmpose_bill_base_y: float = -1.0
    mmpose_bill_base_score: float = -1.0

    # GPT-assist prediction layer. These fields are provenance/review hints only.
    # Premium training export still requires human-approved corrected points.
    gpt_label: str = ""
    gpt_bill_base_x: float = -1.0
    gpt_bill_base_y: float = -1.0
    gpt_bill_tip_x: float = -1.0
    gpt_bill_tip_y: float = -1.0
    gpt_gorget_x: float = -1.0
    gpt_gorget_y: float = -1.0
    gpt_confidence: str = ""
    gpt_reject_reason: str = ""
    gpt_notes: str = ""
    gpt_imported_at: str = ""
    gpt_accepted: bool = False

    corrected_bill_base_x: float = -1.0
    corrected_bill_base_y: float = -1.0
    clicked_tip_x: float = -1.0
    clicked_tip_y: float = -1.0

    corrected_bill_length_px: float = -1.0
    corrected_bill_angle_deg: float = -1.0

    label: str = ""
    training_use: str = "unreviewed"
    is_premium_training_row: bool = False

    old_v01_accepted: bool = False
    old_v01_bill_length_px: float = -1.0
    old_v01_bill_angle_deg: float = -1.0
    old_v01_nearest_candidate_method: str = ""
    old_v01_nearest_candidate_distance_px: float = -1.0
    notes: str = ""

    extra: Dict[str, Any] = field(default_factory=dict)

    def update_geometry(self) -> None:
        if self.corrected_bill_base_x >= 0 and self.corrected_bill_base_y >= 0 and self.clicked_tip_x >= 0 and self.clicked_tip_y >= 0:
            dx = self.clicked_tip_x - self.corrected_bill_base_x
            dy = self.clicked_tip_y - self.corrected_bill_base_y
            self.corrected_bill_length_px = math.hypot(dx, dy)
            self.corrected_bill_angle_deg = math.degrees(math.atan2(dy, dx))
        else:
            self.corrected_bill_length_px = -1.0
            self.corrected_bill_angle_deg = -1.0

    def update_training_status(self) -> None:
        self.update_geometry()
        self.is_premium_training_row = (
            self.label == LABEL_VALID
            and self.corrected_bill_base_x >= 0
            and self.corrected_bill_base_y >= 0
            and self.clicked_tip_x >= 0
            and self.clicked_tip_y >= 0
            and self.corrected_bill_length_px > 0
        )
        self.training_use = "bill_base_and_tip" if self.is_premium_training_row else ("exclude" if self.label else "unreviewed")

    def to_dict(self) -> Dict[str, Any]:
        self.update_training_status()
        d = {col: getattr(self, col) for col in OUTPUT_COLUMNS}
        return d


def as_float(value: Any, default: float = -1.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def as_int(value: Any, default: int = -1) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")



def parse_hbmr_crop_identity(image_path: str) -> Dict[str, Any]:
    """Best-effort parser for HBMR crop filenames.

    Expected examples:
        20260125_154811_001-HBMR-frame-00001740-t0057.94-animal-002-conf057-pad20.png
        20250704_174952_001-Percy-HBMR-frame-00000238-t0003.99-animal-001-conf021-pad20.png

    The parser is intentionally forgiving. If it cannot parse a field, it leaves it blank/-1.
    """
    name = Path(image_path).name
    stem = Path(image_path).stem
    frame_match = re.search(r"(?:^|-)frame-(\d+)", stem, flags=re.IGNORECASE)
    time_match = re.search(r"(?:^|-)t(\d+(?:\.\d+)?)", stem, flags=re.IGNORECASE)
    frame_number = as_int(frame_match.group(1), -1) if frame_match else -1
    time_sec = as_float(time_match.group(1), -1.0) if time_match else -1.0
    if frame_match:
        source_key = stem[:frame_match.start()].rstrip("-")
    else:
        source_key = stem
    if not source_key:
        source_key = str(Path(image_path).parent)
    return {
        "source_video_key": source_key,
        "frame_number": frame_number,
        "time_sec": time_sec,
    }

def fill_sequence_identity(row: ReviewRow) -> None:
    parsed = parse_hbmr_crop_identity(row.image_path)
    if not row.source_video_key:
        row.source_video_key = str(parsed.get("source_video_key") or "")
    if row.frame_number < 0:
        row.frame_number = as_int(parsed.get("frame_number"), -1)
    if row.time_sec < 0:
        row.time_sec = as_float(parsed.get("time_sec"), -1.0)


def row_from_v01(raw: Dict[str, Any], idx: int) -> ReviewRow:
    # Preserve v0.1.0 values while creating new corrected fields.
    old_accepted = as_bool(raw.get("accepted"))
    old_tip_x = as_float(raw.get("clicked_tip_x"))
    old_tip_y = as_float(raw.get("clicked_tip_y"))
    old_base_x = as_float(raw.get("bill_base_x"))
    old_base_y = as_float(raw.get("bill_base_y"))

    row = ReviewRow(
        created_at=str(raw.get("created_at") or now_stamp()),
        updated_at="",
        image_path=str(raw.get("image_path") or ""),
        image_index=as_int(raw.get("image_index"), idx),
        source_row_index=idx,
        mmpose_bill_base_x=old_base_x,
        mmpose_bill_base_y=old_base_y,
        mmpose_bill_base_score=as_float(raw.get("bill_base_score")),
        corrected_bill_base_x=-1.0,
        corrected_bill_base_y=-1.0,
        clicked_tip_x=-1.0,
        clicked_tip_y=-1.0,
        label="",
        training_use="unreviewed",
        is_premium_training_row=False,
        old_v01_accepted=old_accepted,
        old_v01_bill_length_px=as_float(raw.get("bill_length_px")),
        old_v01_bill_angle_deg=as_float(raw.get("bill_angle_deg")),
        old_v01_nearest_candidate_method=str(raw.get("nearest_candidate_method") or ""),
        old_v01_nearest_candidate_distance_px=as_float(raw.get("nearest_candidate_distance_px")),
        notes=str(raw.get("notes") or ""),
        extra=dict(raw),
    )

    # Convenience prefill: old accepted rows get their old tip shown, but still require review.
    # The corrected base is NOT blindly filled because the point of v0.2.0 is to correct it.
    if old_accepted and old_tip_x >= 0 and old_tip_y >= 0:
        row.clicked_tip_x = old_tip_x
        row.clicked_tip_y = old_tip_y
    fill_sequence_identity(row)
    return row


def row_from_v02(raw: Dict[str, Any], idx: int) -> ReviewRow:
    row = ReviewRow(
        created_at=str(raw.get("created_at") or now_stamp()),
        updated_at=str(raw.get("updated_at") or ""),
        image_path=str(raw.get("image_path") or ""),
        image_index=as_int(raw.get("image_index"), idx),
        source_row_index=as_int(raw.get("source_row_index"), idx),
        mmpose_bill_base_x=as_float(raw.get("mmpose_bill_base_x", raw.get("bill_base_x"))),
        mmpose_bill_base_y=as_float(raw.get("mmpose_bill_base_y", raw.get("bill_base_y"))),
        mmpose_bill_base_score=as_float(raw.get("mmpose_bill_base_score", raw.get("bill_base_score"))),
        gpt_label=str(raw.get("gpt_label") or ""),
        gpt_bill_base_x=as_float(raw.get("gpt_bill_base_x")),
        gpt_bill_base_y=as_float(raw.get("gpt_bill_base_y")),
        gpt_bill_tip_x=as_float(raw.get("gpt_bill_tip_x", raw.get("gpt_tip_x"))),
        gpt_bill_tip_y=as_float(raw.get("gpt_bill_tip_y", raw.get("gpt_tip_y"))),
        gpt_gorget_x=as_float(raw.get("gpt_gorget_x")),
        gpt_gorget_y=as_float(raw.get("gpt_gorget_y")),
        gpt_confidence=str(raw.get("gpt_confidence") or ""),
        gpt_reject_reason=str(raw.get("gpt_reject_reason") or ""),
        gpt_notes=str(raw.get("gpt_notes") or ""),
        gpt_imported_at=str(raw.get("gpt_imported_at") or ""),
        gpt_accepted=as_bool(raw.get("gpt_accepted")),
        corrected_bill_base_x=as_float(raw.get("corrected_bill_base_x")),
        corrected_bill_base_y=as_float(raw.get("corrected_bill_base_y")),
        clicked_tip_x=as_float(raw.get("clicked_tip_x")),
        clicked_tip_y=as_float(raw.get("clicked_tip_y")),
        label=str(raw.get("label") or ""),
        training_use=str(raw.get("training_use") or "unreviewed"),
        is_premium_training_row=as_bool(raw.get("is_premium_training_row")),
        old_v01_accepted=as_bool(raw.get("old_v01_accepted")),
        old_v01_bill_length_px=as_float(raw.get("old_v01_bill_length_px")),
        old_v01_bill_angle_deg=as_float(raw.get("old_v01_bill_angle_deg")),
        old_v01_nearest_candidate_method=str(raw.get("old_v01_nearest_candidate_method") or ""),
        old_v01_nearest_candidate_distance_px=as_float(raw.get("old_v01_nearest_candidate_distance_px")),
        notes=str(raw.get("notes") or ""),
        extra=dict(raw),
    )
    row.source_video_key = str(raw.get("source_video_key") or row.source_video_key)
    row.frame_number = as_int(raw.get("frame_number"), row.frame_number)
    row.time_sec = as_float(raw.get("time_sec"), row.time_sec)
    row.sequence_id = str(raw.get("sequence_id") or "")
    row.sequence_position = as_int(raw.get("sequence_position"), -1)
    row.neighbor_count = as_int(raw.get("neighbor_count"), 0)
    row.best_bill_frame = as_bool(raw.get("best_bill_frame"))
    fill_sequence_identity(row)
    row.update_training_status()
    return row


def load_rows(path: Path) -> List[ReviewRow]:
    rows: List[ReviewRow] = []
    suffix = path.suffix.lower()
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        raw_rows = data.get("rows", data if isinstance(data, list) else [])
        if not isinstance(raw_rows, list):
            raise ValueError("JSON did not contain a rows list.")
        for idx, raw in enumerate(raw_rows):
            if not isinstance(raw, dict):
                continue
            if "mmpose_bill_base_x" in raw or "corrected_bill_base_x" in raw or "label" in raw:
                rows.append(row_from_v02(raw, idx))
            else:
                rows.append(row_from_v01(raw, idx))
    else:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for idx, raw in enumerate(reader):
                if "mmpose_bill_base_x" in raw or "corrected_bill_base_x" in raw or "label" in raw:
                    rows.append(row_from_v02(raw, idx))
                else:
                    rows.append(row_from_v01(raw, idx))
    return rows


def make_blank_row_from_image(path: Path, idx: int) -> ReviewRow:
    row = ReviewRow(
        created_at=now_stamp(),
        updated_at="",
        image_path=str(path),
        image_index=idx,
        source_row_index=idx,
        mmpose_bill_base_x=-1.0,
        mmpose_bill_base_y=-1.0,
        mmpose_bill_base_score=-1.0,
        corrected_bill_base_x=-1.0,
        corrected_bill_base_y=-1.0,
        clicked_tip_x=-1.0,
        clicked_tip_y=-1.0,
        label="",
        training_use="unreviewed",
        is_premium_training_row=False,
        notes="imported crop; no mmpose base",
        extra={"imported_as_crop_only": True},
    )
    fill_sequence_identity(row)
    return row


def row_from_sampler_record(raw: Dict[str, Any], idx: int) -> ReviewRow:
    """Create a bill-tip review row from a SamplerGUI v0.2.x manifest row.

    SamplerGUI is allowed to select and score evidence, but this trainer keeps
    the existing bill base + bill tip training schema. No image copies are made;
    image_path points at the sampler candidate saved once under D:\HBMR\output.
    """
    image_path = str(raw.get("candidate_path") or raw.get("image_path") or "")
    row = ReviewRow(
        created_at=now_stamp(),
        updated_at="",
        image_path=image_path,
        image_index=as_int(raw.get("evidence_rank"), idx),
        source_row_index=idx,
        source_video_key=str(raw.get("source_key") or raw.get("source_video_key") or ""),
        frame_number=as_int(raw.get("frame_number"), -1),
        time_sec=as_float(raw.get("time_sec"), -1.0),
        sequence_id=str(raw.get("sequence_id") or raw.get("source_key") or ""),
        sequence_position=-1,
        neighbor_count=as_int(raw.get("neighbor_count"), 0),
        best_bill_frame=str(raw.get("evidence_bucket") or "").lower() == "best",
        # SamplerGUI v0.2.x may contain placeholder/derived bill_base fields.
        # They are NOT trusted as trainer MMPose output because bad placeholder
        # points can block Run MMPose Missing and contaminate labels.
        mmpose_bill_base_x=-1.0,
        mmpose_bill_base_y=-1.0,
        mmpose_bill_base_score=-1.0,
        corrected_bill_base_x=-1.0,
        corrected_bill_base_y=-1.0,
        clicked_tip_x=-1.0,
        clicked_tip_y=-1.0,
        label="",
        training_use="unreviewed",
        is_premium_training_row=False,
        notes=(
            f"sampler manifest import; bucket={raw.get('evidence_bucket','')}; "
            f"rank={raw.get('evidence_rank','')}; score={raw.get('identity_evidence_score','')}"
        ),
        extra=dict(raw),
    )
    fill_sequence_identity(row)
    return row


def load_sampler_manifest(path: Path) -> List[ReviewRow]:
    suffix = path.suffix.lower()
    raw_rows: List[Dict[str, Any]] = []
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            raw_rows = data.get("records") or data.get("rows") or data.get("candidates") or []
        elif isinstance(data, list):
            raw_rows = data
    else:
        with path.open("r", encoding="utf-8", newline="") as f:
            raw_rows = list(csv.DictReader(f))
    rows = [row_from_sampler_record(raw, idx) for idx, raw in enumerate(raw_rows) if isinstance(raw, dict) and (raw.get("candidate_path") or raw.get("image_path"))]
    rows.sort(key=lambda r: (as_int(r.extra.get("evidence_rank"), 10**9), -as_float(r.extra.get("identity_evidence_score"), -1.0), r.source_video_key, r.frame_number))
    for idx, row in enumerate(rows):
        row.image_index = idx
    return rows

def normalize_path_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("\\", "/")
    return text.lower()


def image_match_keys(image_path: str) -> set[str]:
    p = Path(str(image_path))
    stem = p.stem.lower()
    name = p.name.lower()
    full = normalize_path_key(image_path)
    keys = {full, name, stem}
    # Candidate manifests may preserve only source crop basename without absolute path.
    if full:
        keys.add(full.split("/")[-1])
    return {k for k in keys if k}


def gpt_prediction_rows_from_file(path: Path) -> List[Dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            rows = data.get("predictions") or data.get("rows") or data.get("records") or data.get("items") or []
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
    else:
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    return [r for r in rows if isinstance(r, dict)]


def gpt_get_float(raw: Dict[str, Any], *names: str) -> float:
    for name in names:
        if name in raw:
            value = as_float(raw.get(name))
            if value >= 0:
                return value
    # Support nested forms: bill_base: {x, y}, bill_tip: {x, y}, gorget: {x, y}
    if names:
        first = names[0]
        if "base" in first:
            nested = raw.get("bill_base") or raw.get("base") or raw.get("gpt_bill_base")
            coord = "x" if first.endswith("_x") else "y"
        elif "tip" in first:
            nested = raw.get("bill_tip") or raw.get("tip") or raw.get("gpt_bill_tip")
            coord = "x" if first.endswith("_x") else "y"
        elif "gorget" in first:
            nested = raw.get("gorget") or raw.get("gpt_gorget")
            coord = "x" if first.endswith("_x") else "y"
        else:
            nested = None
            coord = ""
        if isinstance(nested, dict):
            return as_float(nested.get(coord))
    return -1.0


def apply_gpt_prediction_to_row(row: ReviewRow, raw: Dict[str, Any], imported_at: str) -> None:
    row.gpt_label = str(raw.get("gpt_label") or raw.get("label") or raw.get("prediction_label") or "")
    row.gpt_bill_base_x = gpt_get_float(raw, "gpt_bill_base_x", "bill_base_x", "base_x", "corrected_bill_base_x")
    row.gpt_bill_base_y = gpt_get_float(raw, "gpt_bill_base_y", "bill_base_y", "base_y", "corrected_bill_base_y")
    row.gpt_bill_tip_x = gpt_get_float(raw, "gpt_bill_tip_x", "gpt_tip_x", "bill_tip_x", "tip_x", "clicked_tip_x")
    row.gpt_bill_tip_y = gpt_get_float(raw, "gpt_bill_tip_y", "gpt_tip_y", "bill_tip_y", "tip_y", "clicked_tip_y")
    row.gpt_gorget_x = gpt_get_float(raw, "gpt_gorget_x", "gorget_x", "throat_x")
    row.gpt_gorget_y = gpt_get_float(raw, "gpt_gorget_y", "gorget_y", "throat_y")
    row.gpt_confidence = str(raw.get("gpt_confidence") or raw.get("confidence") or raw.get("annotation_confidence") or "")
    row.gpt_reject_reason = str(raw.get("gpt_reject_reason") or raw.get("reject_reason") or raw.get("rejection_reason") or "")
    row.gpt_notes = str(raw.get("gpt_notes") or raw.get("notes") or raw.get("reasoning") or "")
    row.gpt_imported_at = imported_at
    row.gpt_accepted = False
    row.updated_at = now_stamp()
    row.extra["gpt_raw_prediction"] = dict(raw)


def find_images_in_folder(folder: Path, recursive: bool = True) -> List[Path]:
    if recursive:
        candidates = folder.rglob("*")
    else:
        candidates = folder.glob("*")
    return sorted([p for p in candidates if p.is_file() and p.suffix.lower() in IMAGE_EXTS])



MMPPOSE_HELPER_CODE = """
from __future__ import annotations
import argparse, json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--checkpoint', required=True)
    ap.add_argument('--images', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    image_paths = json.loads(Path(args.images).read_text(encoding='utf-8'))
    results = []

    try:
        import cv2
        import numpy as np
        from mmpose.apis import init_model, inference_topdown
        model = init_model(args.config, args.checkpoint, device='cpu')
        for image_path in image_paths:
            item = {'image_path': image_path, 'ok': False}
            try:
                img = cv2.imread(image_path)
                if img is None:
                    item['error'] = 'cv2 could not read image'
                    results.append(item)
                    continue
                h, w = img.shape[:2]
                bbox = np.array([[0, 0, w, h]], dtype=np.float32)
                try:
                    preds = inference_topdown(model, image_path, bboxes=bbox, bbox_format='xyxy')
                except TypeError:
                    preds = inference_topdown(model, image_path, bbox)
                if not preds:
                    item['error'] = 'no pose result'
                    results.append(item)
                    continue
                pred = preds[0]
                if hasattr(pred, 'pred_instances'):
                    inst = pred.pred_instances
                    keypoints = getattr(inst, 'keypoints', None)
                    scores = getattr(inst, 'keypoint_scores', None)
                    if keypoints is not None:
                        kp = keypoints[0][0] if len(keypoints.shape) == 3 else keypoints[0]
                        sc = scores[0][0] if scores is not None and len(scores.shape) == 2 else (scores[0] if scores is not None else -1.0)
                        item.update({'ok': True, 'nose_x': float(kp[0]), 'nose_y': float(kp[1]), 'nose_score': float(sc)})
                    else:
                        item['error'] = 'no keypoints in pred_instances'
                elif isinstance(pred, dict):
                    kps = pred.get('keypoints') or pred.get('preds')
                    scores = pred.get('keypoint_scores') or pred.get('scores')
                    if kps is not None:
                        kp = kps[0]
                        sc = scores[0] if scores is not None else -1.0
                        item.update({'ok': True, 'nose_x': float(kp[0]), 'nose_y': float(kp[1]), 'nose_score': float(sc)})
                    else:
                        item['error'] = 'dict result had no keypoints'
                else:
                    item['error'] = 'unknown result type: ' + type(pred).__name__
            except Exception as exc:
                item['error'] = str(exc)
            results.append(item)
    except Exception as exc:
        Path(args.output).write_text(json.dumps({'fatal_error': str(exc), 'results': results}, indent=2), encoding='utf-8')
        raise

    Path(args.output).write_text(json.dumps({'results': results}, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
"""

class BillTrainerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.rows: List[ReviewRow] = []
        self.current_index = 0
        self.current_image = None
        self.current_photo = None
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.click_mode = tk.StringVar(value="base")
        self.label_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Open a training JSON/CSV, or import a folder of crop images to begin.")
        self.notes_var = tk.StringVar(value="")
        self.show_old_var = tk.BooleanVar(value=True)
        self.show_mmpose_var = tk.BooleanVar(value=True)
        self.show_gpt_var = tk.BooleanVar(value=True)
        self.show_corrected_var = tk.BooleanVar(value=True)
        self.autosave_var = tk.BooleanVar(value=False)
        self.source_path: Optional[Path] = None
        self.last_save_path: Optional[Path] = None
        self._build_ui()
        self._bind_keys()

    def _build_ui(self) -> None:
        top = tk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)

        tk.Button(top, text="Open JSON/CSV", command=self.open_file).pack(side=tk.LEFT)
        tk.Button(top, text="Open Sampler Manifest", command=self.open_sampler_manifest).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Import GPT Predictions", command=self.import_gpt_predictions).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Import Crop Folder", command=self.import_crop_folder).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Run MMPose Missing", command=self.run_mmpose_missing_bases).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Force MMPose All", command=self.run_mmpose_all_force).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Run MMPose Current", command=self.run_mmpose_current).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Clear MMPose Bases", command=self.clear_all_mmpose_bases).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Prev Neighbor ([)", command=self.prev_neighbor).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Next Neighbor (])", command=self.next_neighbor).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Mark Best (G)", command=self.mark_best_frame).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Next Unreviewed (N)", command=self.next_unreviewed).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Save All", command=self.save_all).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(top, text="Save Premium Only", command=self.save_premium_only).pack(side=tk.LEFT, padx=(6, 0))
        tk.Checkbutton(top, text="Autosave on Next", variable=self.autosave_var).pack(side=tk.LEFT, padx=(12, 0))

        tk.Button(top, text="Prev", command=self.prev_row).pack(side=tk.RIGHT, padx=(0, 6))
        tk.Button(top, text="Next", command=self.next_row).pack(side=tk.RIGHT)

        mid = tk.Frame(self.root)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.canvas = tk.Canvas(mid, width=900, height=620, bg="#202020")
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self.on_canvas_click)

        side = tk.Frame(mid, width=330)
        side.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

        tk.Label(side, text="Click mode", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Radiobutton(side, text="Corrected bill base (B)", variable=self.click_mode, value="base").pack(anchor="w")
        tk.Radiobutton(side, text="Bill tip (T)", variable=self.click_mode, value="tip").pack(anchor="w")
        tk.Button(side, text="Use MMPose Base (U)", command=self.use_mmpose_base).pack(anchor="w", pady=(6, 0), fill=tk.X)
        tk.Button(side, text="Accept GPT Points (A)", command=self.accept_gpt_points).pack(anchor="w", pady=(4, 0), fill=tk.X)
        tk.Button(side, text="Accept GPT Label", command=self.accept_gpt_label).pack(anchor="w", pady=(4, 0), fill=tk.X)
        tk.Button(side, text="Clear Points (Delete)", command=self.clear_current_points).pack(anchor="w", pady=(4, 0), fill=tk.X)

        tk.Label(side, text="Strict label", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        for lbl in LABELS:
            tk.Radiobutton(side, text=lbl, variable=self.label_var, value=lbl, command=self.apply_label_from_var).pack(anchor="w")

        row_buttons = tk.Frame(side)
        row_buttons.pack(anchor="w", pady=(8, 0), fill=tk.X)
        tk.Button(row_buttons, text="Valid + Next (V)", command=lambda: self.set_label_and_next(LABEL_VALID)).pack(fill=tk.X)
        tk.Button(row_buttons, text="Tip Missing (M)", command=lambda: self.set_label_and_next(LABEL_REJECT_TIP_MISSING)).pack(fill=tk.X, pady=(4, 0))
        tk.Button(row_buttons, text="Bad Base (X)", command=lambda: self.set_label_and_next(LABEL_REJECT_BAD_BASE)).pack(fill=tk.X, pady=(4, 0))
        tk.Button(row_buttons, text="Face-on (F)", command=lambda: self.set_label_and_next(LABEL_REJECT_FACE_ON)).pack(fill=tk.X, pady=(4, 0))
        tk.Button(row_buttons, text="Blur/Occlusion (O)", command=lambda: self.set_label_and_next(LABEL_REJECT_BLUR_OCCLUSION)).pack(fill=tk.X, pady=(4, 0))
        tk.Button(row_buttons, text="Other Reject (R)", command=lambda: self.set_label_and_next(LABEL_REJECT_OTHER)).pack(fill=tk.X, pady=(4, 0))

        tk.Label(side, text="Notes", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        self.notes_entry = tk.Entry(side, textvariable=self.notes_var)
        self.notes_entry.pack(fill=tk.X)
        tk.Button(side, text="Apply Notes", command=self.apply_notes).pack(anchor="w", pady=(4, 0))

        tk.Label(side, text="Display", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        tk.Checkbutton(side, text="Show MMPose base", variable=self.show_mmpose_var, command=self.draw).pack(anchor="w")
        tk.Checkbutton(side, text="Show GPT predictions", variable=self.show_gpt_var, command=self.draw).pack(anchor="w")
        tk.Checkbutton(side, text="Show corrected points", variable=self.show_corrected_var, command=self.draw).pack(anchor="w")
        tk.Checkbutton(side, text="Show old v0.1 tip", variable=self.show_old_var, command=self.draw).pack(anchor="w")

        tk.Label(side, text="Legend", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12, 0))
        legend = (
            "red circle = MMPose/AP-10K nose\n"
            "orange circle = GPT bill base/tip/gorget\n"
            "cyan cross = corrected bill base\n"
            "yellow cross = clicked bill tip\n"
            "green line = corrected bill vector\n"
            "magenta dot = old v0.1 accepted tip"
        )
        tk.Label(side, text=legend, justify=tk.LEFT).pack(anchor="w")

        self.info_text = tk.Text(side, width=42, height=13, wrap=tk.WORD)
        self.info_text.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        bottom = tk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(bottom, textvariable=self.status_var, anchor="w").pack(fill=tk.X)

    def _bind_keys(self) -> None:
        self.root.bind("<Right>", lambda e: self.next_row())
        self.root.bind("<Left>", lambda e: self.prev_row())
        self.root.bind("b", lambda e: self.click_mode.set("base"))
        self.root.bind("B", lambda e: self.click_mode.set("base"))
        self.root.bind("t", lambda e: self.click_mode.set("tip"))
        self.root.bind("T", lambda e: self.click_mode.set("tip"))
        self.root.bind("v", lambda e: self.set_label_and_next(LABEL_VALID))
        self.root.bind("V", lambda e: self.set_label_and_next(LABEL_VALID))
        self.root.bind("m", lambda e: self.set_label_and_next(LABEL_REJECT_TIP_MISSING))
        self.root.bind("M", lambda e: self.set_label_and_next(LABEL_REJECT_TIP_MISSING))
        self.root.bind("x", lambda e: self.set_label_and_next(LABEL_REJECT_BAD_BASE))
        self.root.bind("X", lambda e: self.set_label_and_next(LABEL_REJECT_BAD_BASE))
        self.root.bind("f", lambda e: self.set_label_and_next(LABEL_REJECT_FACE_ON))
        self.root.bind("F", lambda e: self.set_label_and_next(LABEL_REJECT_FACE_ON))
        self.root.bind("o", lambda e: self.set_label_and_next(LABEL_REJECT_BLUR_OCCLUSION))
        self.root.bind("O", lambda e: self.set_label_and_next(LABEL_REJECT_BLUR_OCCLUSION))
        self.root.bind("r", lambda e: self.set_label_and_next(LABEL_REJECT_OTHER))
        self.root.bind("R", lambda e: self.set_label_and_next(LABEL_REJECT_OTHER))
        self.root.bind("<Delete>", lambda e: self.clear_current_points())
        self.root.bind("u", lambda e: self.use_mmpose_base())
        self.root.bind("U", lambda e: self.use_mmpose_base())
        self.root.bind("a", lambda e: self.accept_gpt_points())
        self.root.bind("A", lambda e: self.accept_gpt_points())
        self.root.bind("[", lambda e: self.prev_neighbor())
        self.root.bind("]", lambda e: self.next_neighbor())
        self.root.bind("g", lambda e: self.mark_best_frame())
        self.root.bind("G", lambda e: self.mark_best_frame())
        self.root.bind("n", lambda e: self.next_unreviewed())
        self.root.bind("N", lambda e: self.next_unreviewed())


    def rebuild_sequence_metadata(self) -> None:
        if not self.rows:
            return
        for r in self.rows:
            fill_sequence_identity(r)
        groups: Dict[str, List[int]] = {}
        for i, r in enumerate(self.rows):
            key = r.source_video_key or str(Path(r.image_path).parent)
            groups.setdefault(key, []).append(i)
        for key, indices in groups.items():
            indices.sort(key=lambda i: (self.rows[i].frame_number if self.rows[i].frame_number >= 0 else 10**12, self.rows[i].time_sec if self.rows[i].time_sec >= 0 else 10**12, i))
            count = len(indices)
            for pos, idx in enumerate(indices):
                r = self.rows[idx]
                r.sequence_id = key
                r.sequence_position = pos
                r.neighbor_count = count

    def current_group_indices(self) -> List[int]:
        row = self.current_row()
        if row is None:
            return []
        key = row.sequence_id or row.source_video_key
        indices = [i for i, r in enumerate(self.rows) if (r.sequence_id or r.source_video_key) == key]
        indices.sort(key=lambda i: (self.rows[i].frame_number if self.rows[i].frame_number >= 0 else 10**12, self.rows[i].time_sec if self.rows[i].time_sec >= 0 else 10**12, i))
        return indices

    def prev_neighbor(self) -> None:
        indices = self.current_group_indices()
        if not indices:
            return
        try:
            pos = indices.index(self.current_index)
        except ValueError:
            return
        if pos > 0:
            self.apply_notes()
            self.current_index = indices[pos - 1]
            self.load_current()

    def next_neighbor(self) -> None:
        indices = self.current_group_indices()
        if not indices:
            return
        try:
            pos = indices.index(self.current_index)
        except ValueError:
            return
        if pos < len(indices) - 1:
            self.apply_notes()
            self.current_index = indices[pos + 1]
            self.load_current()

    def mark_best_frame(self) -> None:
        row = self.current_row()
        if row is None:
            return
        # Only one best flag per temporal source group. This marks best evidence frame, not necessarily valid label.
        for idx in self.current_group_indices():
            self.rows[idx].best_bill_frame = False
        row.best_bill_frame = True
        row.updated_at = now_stamp()
        self.update_info()
        self.status_var.set(f"Marked best bill-evidence frame for sequence: {row.sequence_id}")

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open bill base/tip training JSON/CSV",
            filetypes=[("Training files", "*.json *.csv"), ("JSON", "*.json"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.rows = load_rows(Path(path))
            if not self.rows:
                raise ValueError("No rows found.")
            self.source_path = Path(path)
            self.rebuild_sequence_metadata()
            self.current_index = 0
            self.status_var.set(f"Loaded {len(self.rows)} rows from {path}")
            self.load_current()
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))

    def open_sampler_manifest(self) -> None:
        path = filedialog.askopenfilename(
            title="Open SamplerGUI candidate manifest JSON/CSV",
            filetypes=[("Sampler manifests", "*.json *.csv"), ("JSON", "*.json"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            rows = load_sampler_manifest(Path(path))
            if not rows:
                raise ValueError("No sampler candidate rows found. Expected candidate_path/image_path fields.")
            self.rows = rows
            self.source_path = Path(path)
            self.rebuild_sequence_metadata()
            self.current_index = 0
            self.status_var.set(f"Loaded {len(self.rows)} sampler candidate rows from {path}")
            self.load_current()
        except Exception as exc:
            messagebox.showerror("Sampler manifest open failed", str(exc))

    def import_crop_folder(self) -> None:
        folder = filedialog.askdirectory(title="Import crop image folder")
        if not folder:
            return
        recursive = messagebox.askyesno(
            "Recursive import?",
            "Import images from subfolders too?\n\nYes = include subfolders\nNo = only this folder",
        )
        try:
            paths = find_images_in_folder(Path(folder), recursive=recursive)
            if not paths:
                messagebox.showwarning("No images found", "No PNG/JPG/WEBP/BMP/TIF crop images were found in that folder.")
                return
            existing = {str(Path(r.image_path)).lower() for r in self.rows if r.image_path}
            new_paths = [p for p in paths if str(p).lower() not in existing]
            start_len = len(self.rows)
            for p in new_paths:
                self.rows.append(make_blank_row_from_image(p, len(self.rows)))
            if self.source_path is None:
                self.source_path = Path(folder) / "billbase-billtip-training-v050.json"
            self.rebuild_sequence_metadata()
            if self.rows:
                self.current_index = start_len if new_paths else min(self.current_index, len(self.rows) - 1)
                self.load_current()
            messagebox.showinfo(
                "Import complete",
                f"Found {len(paths)} image files.\nAdded {len(new_paths)} new rows.\nSkipped {len(paths) - len(new_paths)} duplicates.",
            )
            self.status_var.set(f"Imported {len(new_paths)} new crop rows from {folder}")
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))


    def import_gpt_predictions(self) -> None:
        if not self.rows:
            messagebox.showwarning("No review rows", "Open/import crop rows before importing GPT predictions.")
            return
        path = filedialog.askopenfilename(
            title="Import GPT prediction JSON/CSV",
            filetypes=[("GPT prediction files", "*.json *.csv"), ("JSON", "*.json"), ("CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            raw_rows = gpt_prediction_rows_from_file(Path(path))
            if not raw_rows:
                raise ValueError("No GPT prediction rows found. Expected predictions/rows/records/items or CSV rows.")
            row_by_key: Dict[str, ReviewRow] = {}
            for row in self.rows:
                for key in image_match_keys(row.image_path):
                    row_by_key.setdefault(key, row)
            imported_at = now_stamp()
            matched = 0
            unmatched = 0
            for raw in raw_rows:
                keys = set()
                for field in ("image_path", "candidate_path", "crop_path", "filename", "image_name", "source_image"):
                    value = raw.get(field)
                    if value:
                        keys.update(image_match_keys(str(value)))
                target = None
                for key in keys:
                    if key in row_by_key:
                        target = row_by_key[key]
                        break
                if target is None:
                    unmatched += 1
                    continue
                apply_gpt_prediction_to_row(target, raw, imported_at)
                matched += 1
            self.load_current()
            messagebox.showinfo("GPT import complete", f"Matched {matched} prediction row(s).\nUnmatched {unmatched} row(s).")
            self.status_var.set(f"Imported GPT predictions: matched {matched}; unmatched {unmatched}")
        except Exception as exc:
            messagebox.showerror("GPT prediction import failed", str(exc))

    def _mmpose_default_python(self) -> str:
        default = r"C:\Users\autom\miniconda3\envs\openmmlab\python.exe"
        return default if Path(default).exists() else sys.executable

    def _ask_mmpose_paths(self) -> Optional[Tuple[str, str, str]]:
        py = filedialog.askopenfilename(
            title="Select OpenMMLab Python executable",
            initialfile="python.exe",
            filetypes=[("Python executable", "python.exe"), ("All files", "*.*")],
        )
        if not py:
            py = self._mmpose_default_python()
        config = filedialog.askopenfilename(
            title="Select MMPose AP-10K config .py",
            filetypes=[("MMPose config", "*.py"), ("All files", "*.*")],
        )
        if not config:
            return None
        checkpoint = filedialog.askopenfilename(
            title="Select MMPose checkpoint .pth/.pt",
            filetypes=[("Checkpoint", "*.pth *.pt"), ("All files", "*.*")],
        )
        if not checkpoint:
            return None
        return py, config, checkpoint


    def clear_all_mmpose_bases(self) -> None:
        if not self.rows:
            return
        if not messagebox.askyesno(
            "Clear MMPose bases",
            "Clear MMPose bill-base points for all loaded rows?\n\n"
            "Use this when imported sampler rows contain placeholder/garbage base points."
        ):
            return
        for row in self.rows:
            row.mmpose_bill_base_x = -1.0
            row.mmpose_bill_base_y = -1.0
            row.mmpose_bill_base_score = -1.0
            row.extra["mmpose_v052_status"] = "cleared"
            row.updated_at = now_stamp()
        self.load_current()
        self.status_var.set(f"Cleared MMPose bases for {len(self.rows)} row(s).")

    def run_mmpose_all_force(self) -> None:
        if not self.rows:
            return
        indices = [i for i, r in enumerate(self.rows) if r.image_path and Path(r.image_path).exists()]
        if not indices:
            messagebox.showwarning("No images", "No existing image paths were found.")
            return
        if not messagebox.askyesno(
            "Force MMPose All",
            f"Force rerun MMPose on all {len(indices)} existing image row(s)?\n\n"
            "This overwrites current MMPose bill-base points and is intended for clearing bad sampler/import placeholders."
        ):
            return
        self._run_mmpose_for_rows(indices)

    def run_mmpose_current(self) -> None:
        row = self.current_row()
        if row is None:
            return
        if not row.image_path or not Path(row.image_path).exists():
            messagebox.showwarning("Missing image", "Current row image path does not exist.")
            return
        self._run_mmpose_for_rows([self.current_index])

    def run_mmpose_missing_bases(self) -> None:
        if not self.rows:
            return
        indices = [i for i, r in enumerate(self.rows) if r.image_path and Path(r.image_path).exists() and (r.mmpose_bill_base_x < 0 or r.mmpose_bill_base_y < 0)]
        if not indices:
            messagebox.showinfo("No missing bases", "No rows with missing MMPose bases were found.")
            return
        if not messagebox.askyesno("Run MMPose", f"Run MMPose on {len(indices)} rows with missing bill bases?\n\nThis can take a while in the OpenMMLab environment."):
            return
        self._run_mmpose_for_rows(indices)

    def _run_mmpose_for_rows(self, indices: List[int]) -> None:
        paths = self._ask_mmpose_paths()
        if paths is None:
            return
        py_exe, config_path, checkpoint_path = paths
        try:
            with tempfile.TemporaryDirectory() as td:
                td_path = Path(td)
                image_list = td_path / "images.json"
                output_json = td_path / "mmpose-output.json"
                helper_py = td_path / "run_mmpose_billbase.py"
                image_list.write_text(json.dumps([self.rows[i].image_path for i in indices], indent=2), encoding="utf-8")
                helper_py.write_text(MMPPOSE_HELPER_CODE, encoding="utf-8")
                cmd = [py_exe, str(helper_py), "--config", config_path, "--checkpoint", checkpoint_path, "--images", str(image_list), "--output", str(output_json)]
                self.status_var.set(f"Running MMPose on {len(indices)} image(s)...")
                self.root.update_idletasks()
                proc = subprocess.run(cmd, text=True, capture_output=True)
                if proc.returncode != 0:
                    messagebox.showerror("MMPose failed", (proc.stderr or proc.stdout or "Unknown MMPose error")[-4000:])
                    self.status_var.set("MMPose failed")
                    return
                data = json.loads(output_json.read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("MMPose failed", str(exc))
            self.status_var.set("MMPose failed")
            return

        by_path = {str(item.get("image_path")): item for item in data.get("results", []) if isinstance(item, dict)}
        updated = 0
        failed = 0
        for i in indices:
            row = self.rows[i]
            item = by_path.get(row.image_path)
            if not item or not item.get("ok"):
                failed += 1
                continue
            row.mmpose_bill_base_x = as_float(item.get("nose_x"))
            row.mmpose_bill_base_y = as_float(item.get("nose_y"))
            row.mmpose_bill_base_score = as_float(item.get("nose_score"))
            row.updated_at = now_stamp()
            row.extra["mmpose_v041_status"] = "generated"
            row.extra["mmpose_v052_status"] = "generated"
            row.extra["mmpose_v041_config"] = str(config_path)
            row.extra["mmpose_v041_checkpoint"] = str(checkpoint_path)
            updated += 1
        self.load_current()
        messagebox.showinfo("MMPose complete", f"Updated {updated} row(s).\nFailed/no pose: {failed}.")
        self.status_var.set(f"MMPose updated {updated} row(s); failed/no pose {failed}")

    def current_row(self) -> Optional[ReviewRow]:
        if not self.rows:
            return None
        return self.rows[self.current_index]

    def load_current(self) -> None:
        row = self.current_row()
        if row is None:
            self.canvas.delete("all")
            return
        self.label_var.set(row.label)
        self.notes_var.set(row.notes)
        self.current_image = None
        self.current_photo = None

        path = Path(row.image_path)
        if path.exists() and Image is not None and ImageTk is not None:
            try:
                img = Image.open(path).convert("RGB")
                self.current_image = img
            except Exception:
                self.current_image = None
        elif path.exists() and Image is None:
            # Tk native PhotoImage can handle PNG/GIF only. It is enough as a last resort.
            try:
                self.current_photo = tk.PhotoImage(file=str(path))
            except Exception:
                self.current_photo = None
        self.draw()
        self.update_info()

    def draw(self) -> None:
        self.canvas.delete("all")
        row = self.current_row()
        if row is None:
            return
        cw = max(100, self.canvas.winfo_width() or 900)
        ch = max(100, self.canvas.winfo_height() or 620)

        if self.current_image is not None and Image is not None and ImageTk is not None:
            iw, ih = self.current_image.size
            self.scale = min((cw - 20) / iw, (ch - 20) / ih, 1.0 if max(iw, ih) < 900 else 999)
            new_w = max(1, int(iw * self.scale))
            new_h = max(1, int(ih * self.scale))
            display = self.current_image.resize((new_w, new_h))
            self.current_photo = ImageTk.PhotoImage(display)
            self.offset_x = (cw - new_w) // 2
            self.offset_y = (ch - new_h) // 2
            self.canvas.create_image(self.offset_x, self.offset_y, anchor="nw", image=self.current_photo)
        elif self.current_photo is not None:
            self.scale = 1.0
            self.offset_x = 10
            self.offset_y = 10
            self.canvas.create_image(self.offset_x, self.offset_y, anchor="nw", image=self.current_photo)
        else:
            self.scale = 1.0
            self.offset_x = 0
            self.offset_y = 0
            msg = "Image not found or Pillow unavailable.\n\n" + row.image_path
            self.canvas.create_text(cw // 2, ch // 2, text=msg, fill="white", width=cw - 40)

        if self.show_mmpose_var.get():
            self.draw_point(row.mmpose_bill_base_x, row.mmpose_bill_base_y, "red", "M")
        if self.show_gpt_var.get():
            self.draw_point(row.gpt_bill_base_x, row.gpt_bill_base_y, "orange", "GPT-B")
            self.draw_point(row.gpt_bill_tip_x, row.gpt_bill_tip_y, "orange", "GPT-T")
            self.draw_point(row.gpt_gorget_x, row.gpt_gorget_y, "orange", "GPT-G")
            if row.gpt_bill_base_x >= 0 and row.gpt_bill_tip_x >= 0:
                gx1, gy1 = self.image_to_canvas(row.gpt_bill_base_x, row.gpt_bill_base_y)
                gx2, gy2 = self.image_to_canvas(row.gpt_bill_tip_x, row.gpt_bill_tip_y)
                self.canvas.create_line(gx1, gy1, gx2, gy2, fill="orange", width=2, dash=(4, 3))
        if self.show_old_var.get() and row.old_v01_accepted:
            old_tip_x = as_float(row.extra.get("clicked_tip_x"))
            old_tip_y = as_float(row.extra.get("clicked_tip_y"))
            self.draw_point(old_tip_x, old_tip_y, "magenta", "old")
        if self.show_corrected_var.get():
            self.draw_point(row.corrected_bill_base_x, row.corrected_bill_base_y, "cyan", "B", cross=True)
            self.draw_point(row.clicked_tip_x, row.clicked_tip_y, "yellow", "T", cross=True)
            if row.corrected_bill_base_x >= 0 and row.clicked_tip_x >= 0:
                x1, y1 = self.image_to_canvas(row.corrected_bill_base_x, row.corrected_bill_base_y)
                x2, y2 = self.image_to_canvas(row.clicked_tip_x, row.clicked_tip_y)
                self.canvas.create_line(x1, y1, x2, y2, fill="green", width=2)

    def image_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        return self.offset_x + x * self.scale, self.offset_y + y * self.scale

    def canvas_to_image(self, x: float, y: float) -> Tuple[float, float]:
        if self.scale == 0:
            return x, y
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def draw_point(self, x: float, y: float, color: str, label: str, cross: bool = False) -> None:
        if x < 0 or y < 0:
            return
        cx, cy = self.image_to_canvas(x, y)
        r = 6
        if cross:
            self.canvas.create_line(cx - r, cy, cx + r, cy, fill=color, width=2)
            self.canvas.create_line(cx, cy - r, cx, cy + r, fill=color, width=2)
        else:
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=2)
        self.canvas.create_text(cx + 10, cy - 10, text=label, fill=color, anchor="w")

    def on_canvas_click(self, event: tk.Event) -> None:
        row = self.current_row()
        if row is None:
            return
        ix, iy = self.canvas_to_image(event.x, event.y)
        if self.click_mode.get() == "base":
            row.corrected_bill_base_x = ix
            row.corrected_bill_base_y = iy
            # Fast workflow: after base click, switch to tip.
            self.click_mode.set("tip")
        else:
            row.clicked_tip_x = ix
            row.clicked_tip_y = iy
        row.updated_at = now_stamp()
        row.update_training_status()
        self.draw()
        self.update_info()

    def has_complete_bill_points(self, row: ReviewRow) -> bool:
        return (
            row.corrected_bill_base_x >= 0
            and row.corrected_bill_base_y >= 0
            and row.clicked_tip_x >= 0
            and row.clicked_tip_y >= 0
        )

    def validate_valid_label_ready(self, row: ReviewRow, show_warning: bool = True) -> bool:
        if self.has_complete_bill_points(row):
            return True
        if show_warning:
            messagebox.showwarning(
                "Valid row is incomplete",
                "valid_full_bill_side_view requires both a corrected bill base and a bill tip.\n\n"
                "Click the corrected base and tip, or use the MMPose base if it is correct enough.",
            )
        return False

    def apply_label_from_var(self) -> None:
        row = self.current_row()
        if row is None:
            return
        new_label = self.label_var.get()
        if new_label == LABEL_VALID and not self.validate_valid_label_ready(row):
            self.label_var.set(row.label or "")
            return
        row.label = new_label
        row.updated_at = now_stamp()
        row.update_training_status()
        self.update_info()

    def set_label_and_next(self, label: str) -> None:
        row = self.current_row()
        if row is None:
            return
        if label == LABEL_VALID and not self.validate_valid_label_ready(row):
            self.label_var.set(row.label or "")
            return
        row.label = label
        row.updated_at = now_stamp()
        row.update_training_status()
        self.label_var.set(label)
        self.apply_notes()
        self.next_row()

    def apply_notes(self) -> None:
        row = self.current_row()
        if row is None:
            return
        row.notes = self.notes_var.get()
        row.updated_at = now_stamp()
        row.update_training_status()
        self.update_info()

    def use_mmpose_base(self) -> None:
        row = self.current_row()
        if row is None:
            return
        if row.mmpose_bill_base_x < 0 or row.mmpose_bill_base_y < 0:
            messagebox.showwarning("No MMPose base", "This row does not have a usable MMPose base point.")
            return
        row.corrected_bill_base_x = row.mmpose_bill_base_x
        row.corrected_bill_base_y = row.mmpose_bill_base_y
        row.updated_at = now_stamp()
        row.update_training_status()
        self.draw()
        self.update_info()

    def accept_gpt_points(self) -> None:
        row = self.current_row()
        if row is None:
            return
        accepted_any = False
        if row.gpt_bill_base_x >= 0 and row.gpt_bill_base_y >= 0:
            row.corrected_bill_base_x = row.gpt_bill_base_x
            row.corrected_bill_base_y = row.gpt_bill_base_y
            accepted_any = True
        if row.gpt_bill_tip_x >= 0 and row.gpt_bill_tip_y >= 0:
            row.clicked_tip_x = row.gpt_bill_tip_x
            row.clicked_tip_y = row.gpt_bill_tip_y
            accepted_any = True
        if not accepted_any:
            messagebox.showwarning("No GPT points", "This row does not have usable GPT bill-base or bill-tip points.")
            return
        row.gpt_accepted = True
        row.updated_at = now_stamp()
        row.update_training_status()
        self.draw()
        self.update_info()
        self.status_var.set("Accepted GPT points into human-corrected fields; verify before marking valid.")

    def accept_gpt_label(self) -> None:
        row = self.current_row()
        if row is None:
            return
        if not row.gpt_label:
            messagebox.showwarning("No GPT label", "This row does not have a GPT label.")
            return
        if row.gpt_label == LABEL_VALID and not self.validate_valid_label_ready(row):
            self.label_var.set(row.label or "")
            return
        row.label = row.gpt_label
        row.gpt_accepted = True
        row.updated_at = now_stamp()
        row.update_training_status()
        self.label_var.set(row.label)
        self.update_info()

    def clear_current_points(self) -> None:
        row = self.current_row()
        if row is None:
            return
        row.corrected_bill_base_x = -1.0
        row.corrected_bill_base_y = -1.0
        row.clicked_tip_x = -1.0
        row.clicked_tip_y = -1.0
        row.updated_at = now_stamp()
        row.update_training_status()
        self.draw()
        self.update_info()

    def next_unreviewed(self) -> None:
        if not self.rows:
            return
        self.apply_notes()
        start = self.current_index + 1
        for i in range(start, len(self.rows)):
            if not self.rows[i].label:
                self.current_index = i
                self.load_current()
                return
        for i in range(0, min(start, len(self.rows))):
            if not self.rows[i].label:
                self.current_index = i
                self.load_current()
                return
        self.status_var.set("No unreviewed rows remain.")

    def prev_row(self) -> None:
        if not self.rows:
            return
        self.apply_notes()
        self.current_index = max(0, self.current_index - 1)
        self.load_current()

    def next_row(self) -> None:
        if not self.rows:
            return
        self.apply_notes()
        if self.autosave_var.get():
            self.autosave_quiet()
        self.current_index = min(len(self.rows) - 1, self.current_index + 1)
        self.load_current()

    def update_info(self) -> None:
        row = self.current_row()
        if row is None:
            return
        row.update_training_status()
        reviewed = sum(1 for r in self.rows if r.label)
        premium = sum(1 for r in self.rows if r.is_premium_training_row)
        old_ok = sum(1 for r in self.rows if r.old_v01_accepted)
        info = []
        info.append(f"Row {self.current_index + 1} / {len(self.rows)}")
        info.append(f"Reviewed: {reviewed} | Premium: {premium} | Old accepted: {old_ok}")
        info.append("")
        info.append(f"Image index: {row.image_index}")
        info.append(f"Source: {row.source_video_key or 'unknown'}")
        info.append(f"Frame: {row.frame_number} | t={row.time_sec:.2f}s")
        info.append(f"Temporal group: {row.sequence_position + 1 if row.sequence_position >= 0 else '?'} / {row.neighbor_count}")
        info.append(f"Best bill frame: {row.best_bill_frame}")
        info.append(f"Old accepted: {row.old_v01_accepted}")
        info.append(f"MMPose base: ({row.mmpose_bill_base_x:.1f}, {row.mmpose_bill_base_y:.1f}) score={row.mmpose_bill_base_score:.3f}")
        info.append(f"GPT label: {row.gpt_label or 'none'} | conf={row.gpt_confidence or 'none'} | accepted={row.gpt_accepted}")
        info.append(f"GPT base/tip: ({row.gpt_bill_base_x:.1f}, {row.gpt_bill_base_y:.1f}) -> ({row.gpt_bill_tip_x:.1f}, {row.gpt_bill_tip_y:.1f})")
        info.append(f"GPT gorget: ({row.gpt_gorget_x:.1f}, {row.gpt_gorget_y:.1f}) reject={row.gpt_reject_reason or 'none'}")
        if row.gpt_notes:
            info.append(f"GPT notes: {row.gpt_notes[:180]}")
        info.append(f"Corrected base: ({row.corrected_bill_base_x:.1f}, {row.corrected_bill_base_y:.1f})")
        info.append(f"Tip: ({row.clicked_tip_x:.1f}, {row.clicked_tip_y:.1f})")
        info.append(f"Corrected length: {row.corrected_bill_length_px:.2f}px")
        info.append(f"Corrected angle: {row.corrected_bill_angle_deg:.2f} deg")
        info.append(f"Label: {row.label or 'unreviewed'}")
        info.append(f"Training use: {row.training_use}")
        info.append("")
        info.append(row.image_path)
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", "\n".join(info))
        self.status_var.set(f"{APP_VERSION} | {reviewed}/{len(self.rows)} reviewed | {premium} premium full-bill side-view rows")

    def default_output_base(self) -> Path:
        # Training exports are canonical Birdbill outputs, not subtool/debug-folder artifacts.
        out_root = Path(r"D:\HBMR\output\billtip-training")
        if not out_root.exists():
            try:
                out_root.mkdir(parents=True, exist_ok=True)
                return out_root / "billbase-billtip-training-v060"
            except Exception:
                pass
        if self.source_path:
            parent = self.source_path.parent
        else:
            parent = Path.cwd()
        return parent / "billbase-billtip-training-v060"

    def save_all(self) -> None:
        if not self.rows:
            return
        base = filedialog.asksaveasfilename(
            title="Save full v0.6.0 training review JSON",
            defaultextension=".json",
            initialfile=self.default_output_base().name + ".json",
            filetypes=[("JSON", "*.json")],
        )
        if not base:
            return
        json_path = Path(base)
        csv_path = json_path.with_suffix(".csv")
        self.write_outputs(json_path, csv_path, premium_only=False)
        self.last_save_path = json_path
        messagebox.showinfo("Saved", f"Saved full review:\n{json_path}\n{csv_path}")

    def save_premium_only(self) -> None:
        if not self.rows:
            return
        base = filedialog.asksaveasfilename(
            title="Save premium training rows JSON",
            defaultextension=".json",
            initialfile=self.default_output_base().name + "-premium.json",
            filetypes=[("JSON", "*.json")],
        )
        if not base:
            return
        json_path = Path(base)
        csv_path = json_path.with_suffix(".csv")
        self.write_outputs(json_path, csv_path, premium_only=True)
        messagebox.showinfo("Saved", f"Saved premium rows only:\n{json_path}\n{csv_path}")

    def autosave_quiet(self) -> None:
        try:
            base = self.last_save_path or (self.default_output_base().with_suffix(".json"))
            self.write_outputs(base, base.with_suffix(".csv"), premium_only=False)
            self.last_save_path = base
        except Exception as exc:
            self.status_var.set(f"Autosave failed: {exc}")

    def write_outputs(self, json_path: Path, csv_path: Path, premium_only: bool = False) -> None:
        for row in self.rows:
            row.update_training_status()
        out_rows = [r for r in self.rows if (r.is_premium_training_row or not premium_only)]
        payload = {
            "metadata": {
                "app": APP_NAME,
                "app_version": APP_VERSION,
                "created_at": now_stamp(),
                "python_executable": sys.executable,
                "source_path": str(self.source_path or ""),
                "row_count": len(out_rows),
                "full_review_row_count": len(self.rows),
                "premium_training_row_count": sum(1 for r in self.rows if r.is_premium_training_row),
                "premium_only_export": premium_only,
                "valid_incomplete_row_count": sum(1 for r in self.rows if r.label == LABEL_VALID and not r.is_premium_training_row),
                "missing_image_count": sum(1 for r in self.rows if r.image_path and not Path(r.image_path).exists()),
                "imported_crop_only_row_count": sum(1 for r in self.rows if r.extra.get("imported_as_crop_only")),
                "missing_mmpose_base_count": sum(1 for r in self.rows if r.mmpose_bill_base_x < 0 or r.mmpose_bill_base_y < 0),
                "generated_mmpose_base_count": sum(1 for r in self.rows if r.extra.get("mmpose_v041_status") == "generated" or r.extra.get("mmpose_v052_status") == "generated"),
                "gpt_prediction_count": sum(1 for r in self.rows if r.gpt_label or r.gpt_bill_tip_x >= 0 or r.gpt_bill_base_x >= 0),
                "gpt_accepted_count": sum(1 for r in self.rows if r.gpt_accepted),
                "gpt_gorget_prediction_count": sum(1 for r in self.rows if r.gpt_gorget_x >= 0 and r.gpt_gorget_y >= 0),
                "temporal_sequence_count": len({(r.sequence_id or r.source_video_key) for r in self.rows if (r.sequence_id or r.source_video_key)}),
                "best_bill_frame_count": sum(1 for r in self.rows if r.best_bill_frame),
                "label_counts": {label: sum(1 for r in self.rows if r.label == label) for label in LABELS},
            },
            "schema_note": "v0.6.0 corrected_bill_base is human-corrected true bill base. clicked_tip is human-clicked true visible bill tip. GPT fields are imported prediction/provenance hints only. valid_full_bill_side_view is blocked in the GUI unless both corrected points exist. Only complete human-approved valid rows are premium bill geometry training rows. Gorget predictions are stored for future AutoRefine training review but do not affect premium bill geometry status.",
            "labels": LABELS,
            "rows": [r.to_dict() for r in out_rows],
        }
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for r in out_rows:
                writer.writerow(r.to_dict())


def main() -> None:
    root = tk.Tk()
    root.geometry("1460x820")
    app = BillTrainerApp(root)
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            try:
                try:
                    app.rows = load_sampler_manifest(p) if "sampler" in p.name.lower() else load_rows(p)
                except Exception:
                    app.rows = load_rows(p)
                app.source_path = p
                app.rebuild_sequence_metadata()
                app.current_index = 0
                app.load_current()
            except Exception as exc:
                messagebox.showerror("Open failed", str(exc))
    root.mainloop()


if __name__ == "__main__":
    main()
