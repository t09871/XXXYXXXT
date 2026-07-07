# mmposeGUI.py | HBMR / Birdbill MMPose Probe v0.1.3 | 2026-06-25 PDT
from __future__ import annotations

import csv
import html
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "HBMR / Birdbill MMPose Probe"
APP_VERSION = "v0.1.3"
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
VISUALS_DIR = OUTPUT_DIR / "visuals"
REPORT_HTML = OUTPUT_DIR / "mmpose-report.html"
PREDICTIONS_JSON = OUTPUT_DIR / "mmpose-predictions.json"
PREDICTIONS_CSV = OUTPUT_DIR / "mmpose-predictions.csv"
BILL_CANDIDATES_CSV = OUTPUT_DIR / "mmpose-bill-tip-candidates.csv"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_DEVICE = "cpu"
DEFAULT_SCORE_THRESHOLD = 0.15
DEFAULT_BILL_SEARCH_LENGTH_PX = 0  # 0 = auto from crop size

AP10K_LABELS = [
    "L_Eye", "R_Eye", "Nose", "Neck", "Tail_Root",
    "L_Shoulder", "L_Elbow", "L_F_Paw",
    "R_Shoulder", "R_Elbow", "R_F_Paw",
    "L_Hip", "L_Knee", "L_B_Paw",
    "R_Hip", "R_Knee", "R_B_Paw",
]

BIRDBILL_LABELS = [
    "head anchor / eye?", "head anchor / eye?", "bill-head front anchor",
    "neck / gorget-top proxy", "tail base / rear body",
    "left wing root / shoulder", "left wing mid / blur proxy", "left wingtip/artifact candidate",
    "right wing root / shoulder", "right wing mid / blur proxy", "right wingtip/artifact candidate",
    "left rear body / flank", "left lower body / tail proxy", "left tail/wing/artifact candidate",
    "right rear body / flank", "right lower body / tail proxy", "right tail/wing/artifact candidate",
]

BIRDBILL_USEFULNESS = [
    "useful if on head", "useful if on head", "high priority", "high priority", "high priority",
    "high priority", "unstable", "risky", "high priority", "unstable", "risky",
    "medium priority", "unstable", "risky", "medium priority", "unstable", "risky",
]


@dataclass
class ImageRecord:
    index: int
    path: Path


@dataclass
class KeypointRecord:
    index: int
    ap10k_label: str
    birdbill_label: str
    usefulness: str
    x: float
    y: float
    score: float
    visible: bool


@dataclass
class DerivedBillTipRecord:
    name: str
    base_x: float
    base_y: float
    tip_x: float
    tip_y: float
    axis_x: float
    axis_y: float
    bill_length_px: float
    confidence: float
    method: str
    ok: bool
    message: str


@dataclass
class PoseResult:
    image_index: int
    image_path: str
    ok: bool
    error: str
    keypoints: list[list[float]]
    scores: list[float]
    keypoint_records: list[KeypointRecord]
    backend: str
    derived_bill_tip_candidates: list[DerivedBillTipRecord] = field(default_factory=list)


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VISUALS_DIR.mkdir(parents=True, exist_ok=True)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if platform.system().lower().startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def collect_images(folder: Path, recursive: bool = True, limit: int = 0) -> list[ImageRecord]:
    if recursive:
        paths = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    else:
        paths = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    paths = sorted(paths, key=lambda p: str(p).lower())
    if limit and limit > 0:
        paths = paths[:limit]
    return [ImageRecord(index=i, path=p) for i, p in enumerate(paths)]


def clean_jsonable(value: Any) -> Any:
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (np.floating, np.integer)):
            return value.item()
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
    try:
        pred_instances = getattr(result, "pred_instances", None)
        if pred_instances is None:
            return [], []
        kpts_j = clean_jsonable(getattr(pred_instances, "keypoints", None))
        sc_j = clean_jsonable(getattr(pred_instances, "keypoint_scores", None))
        keypoints: list[list[float]] = []
        scores: list[float] = []
        if isinstance(kpts_j, list) and kpts_j:
            first = kpts_j[0]
            if isinstance(first, list) and first and isinstance(first[0], list):
                keypoints = [[float(x[0]), float(x[1])] for x in first if len(x) >= 2]
            elif isinstance(first, list) and len(first) >= 2:
                keypoints = [[float(x[0]), float(x[1])] for x in kpts_j if len(x) >= 2]
        if isinstance(sc_j, list) and sc_j:
            if isinstance(sc_j[0], list):
                scores = [float(x) for x in sc_j[0]]
            else:
                scores = [float(x) for x in sc_j]
        return keypoints, scores
    except Exception:
        return [], []


def build_keypoint_records(keypoints: list[list[float]], scores: list[float], score_threshold: float) -> list[KeypointRecord]:
    records: list[KeypointRecord] = []
    for i, kp in enumerate(keypoints):
        if len(kp) < 2:
            continue
        score = scores[i] if i < len(scores) else 1.0
        records.append(KeypointRecord(
            index=i,
            ap10k_label=AP10K_LABELS[i] if i < len(AP10K_LABELS) else f"kp{i}",
            birdbill_label=BIRDBILL_LABELS[i] if i < len(BIRDBILL_LABELS) else "unknown",
            usefulness=BIRDBILL_USEFULNESS[i] if i < len(BIRDBILL_USEFULNESS) else "unknown",
            x=float(kp[0]),
            y=float(kp[1]),
            score=float(score),
            visible=float(score) >= float(score_threshold),
        ))
    return records


def _record_by_index(records: list[KeypointRecord], index: int, score_threshold: float) -> KeypointRecord | None:
    for rec in records:
        if rec.index == index and rec.score >= score_threshold:
            return rec
    return None


def estimate_bill_tip_candidates(image_path: Path, records: list[KeypointRecord], score_threshold: float, search_length_px: int = 0) -> list[DerivedBillTipRecord]:
    """Generate multiple derived bill-tip hypotheses from AP-10K Nose/bill-base.

    This intentionally does NOT select one winning landmark. v0.1.3 is a visual
    test harness: output competing derived tips so the user can see which method
    works under side-view, oblique, and face-on cases. Face-on bills are allowed
    to remain ambiguous rather than forcing a bad bill-tip estimate.
    """
    from math import atan2, cos, hypot, pi, sin
    from statistics import mean
    from PIL import Image, ImageFilter, ImageOps

    def candidate(name: str, base_x: float, base_y: float, tip_x: float, tip_y: float, axis_x: float, axis_y: float,
                  confidence: float, method: str, ok: bool, message: str) -> DerivedBillTipRecord:
        return DerivedBillTipRecord(
            name=name,
            base_x=float(base_x),
            base_y=float(base_y),
            tip_x=float(tip_x),
            tip_y=float(tip_y),
            axis_x=float(axis_x),
            axis_y=float(axis_y),
            bill_length_px=float(hypot(tip_x - base_x, tip_y - base_y)),
            confidence=float(max(0.0, min(1.0, confidence))),
            method=method,
            ok=bool(ok),
            message=message,
        )

    nose = _record_by_index(records, 2, score_threshold)
    if nose is None:
        return []

    neck = _record_by_index(records, 3, score_threshold)
    leye = _record_by_index(records, 0, score_threshold)
    reye = _record_by_index(records, 1, score_threshold)
    shoulders = [r for r in (_record_by_index(records, 5, score_threshold), _record_by_index(records, 8, score_threshold)) if r]

    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("L")
    w, h = img.size
    pix = img.load()
    edges = img.filter(ImageFilter.FIND_EDGES)
    epix = edges.load()

    candidates: list[DerivedBillTipRecord] = []
    axis_sources: list[tuple[str, float, float, float]] = []

    def add_axis(label: str, vx: float, vy: float, quality: float) -> None:
        n = hypot(vx, vy)
        if n >= 3.0:
            axis_sources.append((label, vx / n, vy / n, max(0.0, min(1.0, quality))))

    if neck is not None:
        add_axis("nose-minus-neck", nose.x - neck.x, nose.y - neck.y, 0.85)
    if leye is not None and reye is not None:
        eye_x = (leye.x + reye.x) / 2.0
        eye_y = (leye.y + reye.y) / 2.0
        eye_dist = hypot(leye.x - reye.x, leye.y - reye.y)
        nose_eye = hypot(nose.x - eye_x, nose.y - eye_y)
        face_on_risk = eye_dist > max(6.0, nose_eye * 1.8)
        add_axis("nose-minus-eye-midpoint", nose.x - eye_x, nose.y - eye_y, 0.45 if face_on_risk else 0.75)
    if shoulders:
        sx = mean([r.x for r in shoulders])
        sy = mean([r.y for r in shoulders])
        add_axis("nose-minus-shoulder-midpoint", nose.x - sx, nose.y - sy, 0.55)

    max_len = int(search_length_px) if search_length_px and search_length_px > 0 else int(max(35, min(max(w, h) * 0.42, 180)))
    max_len = max(12, min(max_len, 500))

    def in_bounds(x: float, y: float, pad: int = 1) -> bool:
        return pad <= x < w - pad and pad <= y < h - pad

    def strip_score(ax: float, ay: float, t: int, use_edges: bool = False) -> tuple[float, bool]:
        px, py = -ay, ax
        cx = nose.x + ax * t
        cy = nose.y + ay * t
        if not in_bounds(cx, cy):
            return 0.0, False
        narrow_vals: list[int] = []
        surround_vals: list[int] = []
        edge_vals: list[int] = []
        narrow_half = 2
        surround_half = int(min(11, 4 + t * 0.04))
        for off in range(-surround_half, surround_half + 1):
            sx = int(round(cx + px * off))
            sy = int(round(cy + py * off))
            if sx < 0 or sy < 0 or sx >= w or sy >= h:
                continue
            val = int(pix[sx, sy])
            edge_val = int(epix[sx, sy])
            if abs(off) <= narrow_half:
                narrow_vals.append(val)
                edge_vals.append(edge_val)
            else:
                surround_vals.append(val)
        if not narrow_vals or not surround_vals:
            return 0.0, False
        narrow_min = min(narrow_vals)
        narrow_mean = mean(narrow_vals)
        surround_mean = mean(surround_vals)
        dark_line = max(0.0, surround_mean - narrow_min)
        mean_line = max(0.0, surround_mean - narrow_mean)
        darkness_bonus = max(0.0, (135.0 - narrow_min) / 135.0) * 13.0
        edge_bonus = mean(edge_vals) * 0.18 if edge_vals else 0.0
        score = max(dark_line, mean_line) + darkness_bonus + (edge_bonus if use_edges else 0.0)
        present = score >= (21.0 if use_edges else 18.0) or (narrow_min <= 72 and dark_line >= 8.0)
        return float(score), bool(present)

    def endpoint_scan(axis_label: str, ax: float, ay: float, quality: float, use_edges: bool) -> DerivedBillTipRecord:
        best_t = 0
        score_sum = 0.0
        score_n = 0
        seen = False
        absent = 0
        peak = 0.0
        for t in range(4, max_len + 1):
            score, present = strip_score(ax, ay, t, use_edges=use_edges)
            peak = max(peak, score)
            if present:
                seen = True
                absent = 0
                best_t = t
                score_sum += min(score, 70.0)
                score_n += 1
            elif seen:
                absent += 1
                if absent >= 8 and t > 14:
                    break
        if best_t <= 0:
            fallback_len = min(max_len, 24)
            return candidate(
                name=("edge_axis_fallback" if use_edges else "dark_axis_fallback"),
                base_x=nose.x, base_y=nose.y, tip_x=nose.x + ax * fallback_len, tip_y=nose.y + ay * fallback_len,
                axis_x=ax, axis_y=ay, confidence=0.08 * quality, method=f"{axis_label}; no endpoint evidence",
                ok=False, message="No visible endpoint evidence along this axis; shown only as a directional fallback.",
            )
        length_factor = min(1.0, best_t / max(18.0, max_len * 0.35))
        evidence_factor = min(1.0, (score_sum / max(1, score_n)) / 42.0)
        confidence = quality * (0.35 * length_factor + 0.65 * evidence_factor)
        return candidate(
            name=("edge_endpoint" if use_edges else "dark_line_endpoint"),
            base_x=nose.x, base_y=nose.y, tip_x=nose.x + ax * best_t, tip_y=nose.y + ay * best_t,
            axis_x=ax, axis_y=ay, confidence=confidence, method=f"{axis_label}; {'edge+dark' if use_edges else 'dark-line'} endpoint scan",
            ok=True, message=f"Furthest continuous bill-like evidence at {best_t}px; peak score {peak:.1f}.",
        )

    # 1) Pose-axis candidates at several fixed lengths. These deliberately show
    # what the pure MMPose geometry implies before image evidence is considered.
    for axis_label, ax, ay, quality in axis_sources:
        for length, tag, conf in [(18, "short", 0.18), (32, "medium", 0.14), (48, "long", 0.10)]:
            if length <= max_len:
                candidates.append(candidate(
                    name=f"pose_axis_{tag}",
                    base_x=nose.x, base_y=nose.y, tip_x=nose.x + ax * length, tip_y=nose.y + ay * length,
                    axis_x=ax, axis_y=ay, confidence=conf * quality, method=axis_label,
                    ok=False, message="Pose-only length hypothesis; useful for direction sanity-check, not final bill tip.",
                ))
        candidates.append(endpoint_scan(axis_label, ax, ay, quality, use_edges=False))
        candidates.append(endpoint_scan(axis_label, ax, ay, quality, use_edges=True))
        # Also test the opposite direction once. If AP-10K head/body geometry is
        # inverted or face-on, this makes the failure visible rather than hidden.
        candidates.append(endpoint_scan(axis_label + " reversed", -ax, -ay, quality * 0.45, use_edges=True))

    # 2) Radial sweep independent of pose direction. This is slower but helps
    # reveal whether any bill-like line exists from the Nose point at all.
    radial_best: tuple[float, int, float, float, float] | None = None
    for deg in range(0, 360, 10):
        theta = deg * pi / 180.0
        ax, ay = cos(theta), sin(theta)
        best_t = 0
        total = 0.0
        n_seen = 0
        gap = 0
        for t in range(5, max_len + 1):
            score, present = strip_score(ax, ay, t, use_edges=True)
            if present:
                best_t = t
                total += min(score, 70.0)
                n_seen += 1
                gap = 0
            elif best_t > 0:
                gap += 1
                if gap >= 7 and t > 14:
                    break
        if best_t > 0:
            avg = total / max(1, n_seen)
            rank = best_t * 0.55 + avg * 0.45
            if radial_best is None or rank > radial_best[0]:
                radial_best = (rank, best_t, ax, ay, avg)
    if radial_best is not None:
        _rank, best_t, ax, ay, avg = radial_best
        confidence = min(0.72, 0.25 + avg / 90.0 + min(best_t, 80) / 220.0)
        candidates.append(candidate(
            name="radial_sweep_best",
            base_x=nose.x, base_y=nose.y, tip_x=nose.x + ax * best_t, tip_y=nose.y + ay * best_t,
            axis_x=ax, axis_y=ay, confidence=confidence, method="360-degree radial edge/dark sweep from Nose",
            ok=True, message=f"Best unconstrained radial candidate at angle {atan2(ay, ax) * 180.0 / pi:.1f} deg, length {best_t}px, avg score {avg:.1f}.",
        ))

    # 3) Local contour/farthest-edge candidate. This often fails with feeder or
    # finger overlap, but may reveal a visible bill tip when the shaft is broken.
    roi = int(max(28, min(max_len, 90)))
    farthest: tuple[float, float, float, float] | None = None
    base_val = int(pix[int(max(0, min(w - 1, round(nose.x)))) , int(max(0, min(h - 1, round(nose.y))))])
    for yy in range(max(1, int(nose.y - roi)), min(h - 1, int(nose.y + roi))):
        for xx in range(max(1, int(nose.x - roi)), min(w - 1, int(nose.x + roi))):
            dist = hypot(xx - nose.x, yy - nose.y)
            if dist < 8 or dist > roi:
                continue
            val = int(pix[xx, yy])
            ev = int(epix[xx, yy])
            if ev >= 45 or val <= min(95, base_val + 8):
                score = dist + ev * 0.08 + max(0, 120 - val) * 0.04
                if farthest is None or score > farthest[0]:
                    farthest = (score, float(xx), float(yy), dist)
    if farthest is not None:
        score, tx, ty, dist = farthest
        ax = (tx - nose.x) / max(1e-6, dist)
        ay = (ty - nose.y) / max(1e-6, dist)
        candidates.append(candidate(
            name="local_contour_farthest",
            base_x=nose.x, base_y=nose.y, tip_x=tx, tip_y=ty,
            axis_x=ax, axis_y=ay, confidence=min(0.55, 0.12 + score / 240.0), method="local edge/dark contour farthest point near Nose",
            ok=True, message="Risky candidate: may select feeder/finger/background if connected near bill base.",
        ))

    if not candidates:
        candidates.append(candidate(
            name="bill_tip_unavailable", base_x=nose.x, base_y=nose.y, tip_x=nose.x, tip_y=nose.y,
            axis_x=0.0, axis_y=0.0, confidence=0.0, method="unavailable", ok=False,
            message="Need Nose plus at least one usable orientation cue, or visible image evidence near Nose.",
        ))

    # Add a face-on/ambiguous diagnostic candidate when the geometry suggests risk.
    if leye is not None and reye is not None and neck is not None:
        eye_dist = hypot(leye.x - reye.x, leye.y - reye.y)
        nose_neck = hypot(nose.x - neck.x, nose.y - neck.y)
        if eye_dist > max(8.0, nose_neck * 0.95):
            candidates.append(candidate(
                name="ambiguous_face_on_warning", base_x=nose.x, base_y=nose.y, tip_x=nose.x, tip_y=nose.y,
                axis_x=0.0, axis_y=0.0, confidence=0.0, method="pose geometry diagnostic", ok=False,
                message="Face-on/near-face-on risk: visible bill tip may be genuinely ambiguous even for a human.",
            ))

    # Stable report order: high-confidence candidates first, but keep warnings at bottom.
    candidates.sort(key=lambda c: (c.name.startswith("ambiguous"), -c.confidence, c.name))
    return candidates


def draw_keypoints(image_path: Path, out_path: Path, records: list[KeypointRecord], label_mode: str, score_threshold: float, bill_tip_candidates: list[DerivedBillTipRecord] | None = None) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font = ImageFont.load_default()

    for rec in records:
        visible = rec.score >= score_threshold
        r = 4 if visible else 3
        fill = (255, 0, 0) if visible else (255, 180, 0)
        draw.ellipse((rec.x - r, rec.y - r, rec.x + r, rec.y + r), fill=fill, outline=(255, 255, 255))

        if label_mode == "Index":
            label = str(rec.index)
        elif label_mode == "AP-10K":
            label = f"{rec.index}:{rec.ap10k_label}"
        elif label_mode == "Birdbill":
            label = f"{rec.index}:{rec.birdbill_label}"
        elif label_mode == "Confidence":
            label = f"{rec.index}:{rec.score:.2f}"
        else:
            label = f"{rec.index}:{rec.ap10k_label}:{rec.score:.2f}"

        tx, ty = rec.x + 5, rec.y + 5
        try:
            bbox = draw.textbbox((tx, ty), label, font=font)
            draw.rectangle(bbox, fill=(0, 0, 0))
        except Exception:
            pass
        draw.text((tx, ty), label, fill=(255, 255, 255), font=font)

    candidates = bill_tip_candidates or []
    # High-contrast fixed palette; intentionally local to visualization only.
    palette = [
        (0, 220, 255), (255, 0, 255), (0, 255, 0), (255, 255, 0),
        (255, 128, 0), (0, 128, 255), (255, 80, 80), (180, 180, 180),
    ]
    visible_candidates = [c for c in candidates if c.name != "ambiguous_face_on_warning"][:12]
    for i, c in enumerate(visible_candidates):
        color = palette[i % len(palette)] if c.ok else (150, 150, 150)
        base = (c.base_x, c.base_y)
        tip = (c.tip_x, c.tip_y)
        if c.bill_length_px > 0.5:
            draw.line((base[0], base[1], tip[0], tip[1]), fill=color, width=2)
        r = 4 if c.ok else 3
        draw.ellipse((tip[0] - r, tip[1] - r, tip[0] + r, tip[1] + r), fill=color, outline=(0, 0, 0))
        label = f"{chr(65+i)} {c.name} {c.confidence:.2f}"
        tx, ty = tip[0] + 6, tip[1] + 6 + (i % 3) * 9
        try:
            bbox = draw.textbbox((tx, ty), label, font=font)
            draw.rectangle(bbox, fill=(0, 0, 0))
        except Exception:
            pass
        draw.text((tx, ty), label, fill=(255, 255, 255), font=font)

    img.save(out_path, quality=92)


def check_environment_text() -> str:
    lines = [
        f"{APP_NAME} {APP_VERSION}",
        f"Python executable: {sys.executable}",
        f"Python version: {sys.version.split()[0]}",
        f"Working folder: {ROOT}",
        f"Output folder: {OUTPUT_DIR}",
        "",
    ]
    for mod in ["torch", "mmcv", "mmengine", "mmpose", "mmdet", "PIL"]:
        try:
            imported = __import__(mod)
            lines.append(f"{mod}: {getattr(imported, '__version__', 'installed')}")
        except Exception as exc:
            lines.append(f"{mod}: NOT FOUND ({exc})")
    try:
        import torch
        lines.append(f"torch.cuda.is_available: {torch.cuda.is_available()}")
    except Exception:
        pass
    return "\n".join(lines)


class MMPoseRunner:
    def __init__(self, config: Path, checkpoint: Path, device: str, log):
        self.config = config
        self.checkpoint = checkpoint
        self.device = device
        self.log = log
        self.backend = ""
        self.model = None

    def load(self) -> None:
        if not self.config.exists():
            raise RuntimeError(f"Config file does not exist:\n{self.config}")
        if not self.checkpoint.exists():
            raise RuntimeError(f"Checkpoint file does not exist:\n{self.checkpoint}")
        from mmpose.apis import init_model
        self.log("Loading MMPose model with mmpose.apis.init_model")
        self.model = init_model(str(self.config), str(self.checkpoint), device=self.device)
        self.backend = "mmpose-1.x-init_model"
        self.log(f"Loaded model with backend: {self.backend}")

    def infer_one(self, image_path: Path, score_threshold: float) -> PoseResult:
        try:
            from mmpose.apis import inference_topdown
            raw = inference_topdown(self.model, str(image_path))
            result = raw[0] if isinstance(raw, list) and raw else raw
            keypoints, scores = extract_keypoints_from_result(result)
            records = build_keypoint_records(keypoints, scores, score_threshold)
            return PoseResult(-1, str(image_path), True, "", keypoints, scores, records, self.backend)
        except Exception as exc:
            return PoseResult(-1, str(image_path), False, str(exc), [], [], [], self.backend)


def write_predictions_json(results: list[PoseResult], meta: dict[str, Any]) -> Path:
    payload = {
        "metadata": meta,
        "schema": {
            "source_model_schema": "AP-10K 17 keypoints",
            "ap10k_labels": AP10K_LABELS,
            "birdbill_interpretation_labels": BIRDBILL_LABELS,
            "birdbill_usefulness": BIRDBILL_USEFULNESS,
            "derived_landmarks": ["bill_tip_candidates"],
            "derived_bill_tip_note": "Birdbill AutoRefine candidate landmarks inferred from AP-10K Nose/bill-base plus multiple image/pose methods; not MMPose-predicted keypoints.",
        },
        "results": [
            {
                "image_index": r.image_index,
                "image_path": r.image_path,
                "ok": r.ok,
                "error": r.error,
                "backend": r.backend,
                "keypoints": r.keypoints,
                "scores": r.scores,
                "keypoint_records": [kp.__dict__ for kp in r.keypoint_records],
                "bill_tip_candidates": [c.__dict__ for c in r.derived_bill_tip_candidates],
            }
            for r in results
        ],
    }
    PREDICTIONS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return PREDICTIONS_JSON


def write_predictions_csv(results: list[PoseResult]) -> Path:
    with PREDICTIONS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_index", "image_path", "ok", "keypoint_index", "ap10k_label", "birdbill_label", "usefulness", "x", "y", "score", "visible", "backend", "error", "bill_tip_candidate_count", "top_bill_candidate", "top_bill_confidence"])
        for r in results:
            top = r.derived_bill_tip_candidates[0] if r.derived_bill_tip_candidates else None
            if r.keypoint_records:
                for kp in r.keypoint_records:
                    writer.writerow([r.image_index, r.image_path, r.ok, kp.index, kp.ap10k_label, kp.birdbill_label, kp.usefulness, f"{kp.x:.3f}", f"{kp.y:.3f}", f"{kp.score:.4f}", kp.visible, r.backend, r.error, len(r.derived_bill_tip_candidates), top.name if top else "", f"{top.confidence:.4f}" if top else ""])
            else:
                writer.writerow([r.image_index, r.image_path, r.ok, "", "", "", "", "", "", "", "", r.backend, r.error, len(r.derived_bill_tip_candidates), top.name if top else "", f"{top.confidence:.4f}" if top else ""])
    return PREDICTIONS_CSV


def write_bill_candidates_csv(results: list[PoseResult]) -> Path:
    with BILL_CANDIDATES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_index", "image_path", "candidate_rank", "candidate_name", "ok", "base_x", "base_y", "tip_x", "tip_y", "axis_x", "axis_y", "bill_length_px", "confidence", "method", "message"])
        for r in results:
            for rank, c in enumerate(r.derived_bill_tip_candidates, start=1):
                writer.writerow([r.image_index, r.image_path, rank, c.name, c.ok, f"{c.base_x:.3f}", f"{c.base_y:.3f}", f"{c.tip_x:.3f}", f"{c.tip_y:.3f}", f"{c.axis_x:.5f}", f"{c.axis_y:.5f}", f"{c.bill_length_px:.3f}", f"{c.confidence:.4f}", c.method, c.message])
    return BILL_CANDIDATES_CSV


def relpath_for_html(path: Path) -> str:
    try:
        return path.resolve().relative_to(OUTPUT_DIR.resolve()).as_posix()
    except Exception:
        return path.resolve().as_uri()


def write_report_html(results: list[PoseResult], meta: dict[str, Any]) -> Path:
    parts = []
    for r in results:
        visual = VISUALS_DIR / f"pose-{r.image_index:05d}.jpg"
        img_html = f'<img src="{html.escape(relpath_for_html(visual))}" />' if visual.exists() else ""
        kp_rows = []
        for kp in r.keypoint_records:
            cls = "good" if kp.visible else "low"
            kp_rows.append(f"<tr class='{cls}'><td>{kp.index}</td><td>{html.escape(kp.ap10k_label)}</td><td>{html.escape(kp.birdbill_label)}</td><td>{html.escape(kp.usefulness)}</td><td>{kp.x:.1f}</td><td>{kp.y:.1f}</td><td>{kp.score:.3f}</td><td>{kp.visible}</td></tr>")
        table = "<table><thead><tr><th>#</th><th>AP-10K</th><th>Birdbill interpretation</th><th>Usefulness</th><th>x</th><th>y</th><th>score</th><th>visible</th></tr></thead><tbody>" + "".join(kp_rows) + "</tbody></table>"
        if r.derived_bill_tip_candidates:
            rows = []
            for rank, c in enumerate(r.derived_bill_tip_candidates, start=1):
                cls = "good" if c.ok else "low"
                rows.append(
                    f"<tr class='{cls}'><td>{rank}</td><td>{html.escape(c.name)}</td><td>{c.ok}</td>"
                    f"<td>({c.base_x:.1f}, {c.base_y:.1f})</td><td>({c.tip_x:.1f}, {c.tip_y:.1f})</td>"
                    f"<td>{c.bill_length_px:.1f}</td><td>{c.confidence:.2f}</td>"
                    f"<td>{html.escape(c.method)}</td><td>{html.escape(c.message)}</td></tr>"
                )
            derived_html = (
                "<div class='derived'><b>Bill-tip candidates:</b> competing AutoRefine hypotheses, not AP-10K keypoints. "
                "Face-on bills may be genuinely ambiguous; warnings are included as non-tip candidates."
                "<table><thead><tr><th>Rank</th><th>Name</th><th>OK</th><th>Base</th><th>Tip</th><th>Length px</th><th>Confidence</th><th>Method</th><th>Message</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></div>"
            )
        else:
            derived_html = "<div class='derived'><b>Bill-tip candidates:</b> not attempted / unavailable</div>"
        parts.append(f"<section class='card'><h2>{html.escape(Path(r.image_path).name)}</h2><div class='path'>{html.escape(r.image_path)}</div><div><b>OK:</b> {r.ok} &nbsp; <b>Keypoints:</b> {len(r.keypoint_records)} &nbsp; <b>Backend:</b> {html.escape(r.backend)}</div><div class='error'>{html.escape(r.error)}</div><div class='image'>{img_html}</div>{derived_html}{table}</section>")

    text = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MMPose Probe Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #fafafa; color: #222; }}
.meta, .card {{ background: white; border: 1px solid #ddd; border-radius: 12px; padding: 14px; margin: 14px 0; }}
.path {{ font-size: 12px; color: #555; overflow-wrap: anywhere; margin-bottom: 8px; }}
.error {{ color: #8a0000; font-size: 13px; margin: 8px 0; white-space: pre-wrap; }}
.image img {{ max-width: 800px; max-height: 650px; border: 1px solid #ccc; border-radius: 8px; object-fit: contain; }}
.derived {{ margin: 10px 0; padding: 8px; background: #eefcff; border: 1px solid #b8e8f2; border-radius: 8px; font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
th {{ background: #f0f0f0; }}
tr.low {{ background: #fff7e8; color: #666; }}
</style></head><body>
<h1>HBMR / Birdbill MMPose Probe Report</h1>
<div class="meta">
<div><b>App:</b> {html.escape(APP_NAME)} {html.escape(APP_VERSION)}</div>
<div><b>Created:</b> {html.escape(str(meta.get("created_at", "")))}</div>
<div><b>Config:</b> {html.escape(str(meta.get("config", "")))}</div>
<div><b>Checkpoint:</b> {html.escape(str(meta.get("checkpoint", "")))}</div>
<div><b>Device:</b> {html.escape(str(meta.get("device", "")))}</div>
<div><b>Images:</b> {html.escape(str(meta.get("image_count", "")))}</div>
<div><b>Score threshold:</b> {html.escape(str(meta.get("score_threshold", "")))}</div>
<div><b>Overlay mode:</b> {html.escape(str(meta.get("label_mode", "")))}</div>
</div>
<div class="meta"><b>AP-10K → Birdbill interpretation:</b><br>
0 L_Eye / 1 R_Eye = head anchors; 2 Nose = bill-head front anchor; 3 Neck = gorget/neck proxy; 4 Tail_Root = tail base/rear body;<br>
5/8 Shoulders = wing roots/body-side anchors; 11/14 Hips = rear-body/flank anchors; limb/paw points are exploratory and must be judged visually.<br>
Bill-tip candidates are AutoRefine hypotheses from AP-10K Nose/bill-base plus local image evidence, not true AP-10K keypoints.
</div>
{''.join(parts)}
</body></html>"""
    REPORT_HTML.write_text(text, encoding="utf-8")
    return REPORT_HTML


class MMPoseGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1120x820")
        self.folder_var = tk.StringVar(value="")
        self.config_var = tk.StringVar(value="")
        self.checkpoint_var = tk.StringVar(value="")
        self.device_var = tk.StringVar(value=DEFAULT_DEVICE)
        self.recursive_var = tk.BooleanVar(value=True)
        self.limit_var = tk.IntVar(value=25)
        self.score_threshold_var = tk.DoubleVar(value=DEFAULT_SCORE_THRESHOLD)
        self.label_mode_var = tk.StringVar(value="AP-10K")
        self.estimate_bill_tip_var = tk.BooleanVar(value=True)
        self.bill_search_length_var = tk.IntVar(value=DEFAULT_BILL_SEARCH_LENGTH_PX)
        self._build_ui()
        self.log(f"{APP_NAME} {APP_VERSION}")
        self.log("Standalone MMPose keypoint probe with AP-10K/Birdbill labels.")
        self.log("v0.1.3 adds multiple bill-tip candidate hypotheses from Nose/bill-base plus pose/image evidence.")
        self.log("No HBMR database will be modified.")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text="MMPose Probe: AP-10K labels + Birdbill interpretation", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Goal: identify which existing animal keypoints are usable for hummingbird AutoRefine.").pack(anchor="w", pady=(2, 12))

        folder_frame = ttk.LabelFrame(outer, text="Crop folder")
        folder_frame.pack(fill=tk.X, pady=(0, 8))
        row = ttk.Frame(folder_frame, padding=8)
        row.pack(fill=tk.X)
        ttk.Entry(row, textvariable=self.folder_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Choose Folder", command=self.choose_folder).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row, text="Count Images", command=self.count_images).pack(side=tk.LEFT, padx=(8, 0))

        model_frame = ttk.LabelFrame(outer, text="MMPose model files")
        model_frame.pack(fill=tk.X, pady=(0, 8))
        cfg_row = ttk.Frame(model_frame, padding=(8, 8, 8, 4)); cfg_row.pack(fill=tk.X)
        ttk.Label(cfg_row, text="Config:").pack(side=tk.LEFT)
        ttk.Entry(cfg_row, textvariable=self.config_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(cfg_row, text="Choose .py", command=self.choose_config).pack(side=tk.LEFT)
        ckpt_row = ttk.Frame(model_frame, padding=(8, 4, 8, 8)); ckpt_row.pack(fill=tk.X)
        ttk.Label(ckpt_row, text="Checkpoint:").pack(side=tk.LEFT)
        ttk.Entry(ckpt_row, textvariable=self.checkpoint_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(ckpt_row, text="Choose .pth", command=self.choose_checkpoint).pack(side=tk.LEFT)

        options = ttk.LabelFrame(outer, text="Run settings")
        options.pack(fill=tk.X, pady=(0, 8))
        opt = ttk.Frame(options, padding=8); opt.pack(fill=tk.X)
        ttk.Label(opt, text="Device:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opt, textvariable=self.device_var, values=["cpu", "cuda:0"], width=10).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Max images:").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(opt, from_=1, to=5000, textvariable=self.limit_var, width=8).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Score threshold:").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(opt, from_=0.0, to=1.0, increment=0.05, textvariable=self.score_threshold_var, width=6).grid(row=0, column=5, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Overlay:").grid(row=0, column=6, sticky="w")
        ttk.Combobox(opt, textvariable=self.label_mode_var, values=["Index", "AP-10K", "Birdbill", "Confidence", "Full"], width=12).grid(row=0, column=7, sticky="w", padx=(8, 16))
        ttk.Checkbutton(opt, text="Recursive", variable=self.recursive_var).grid(row=0, column=8, sticky="w")
        ttk.Checkbutton(opt, text="Estimate bill-tip candidates", variable=self.estimate_bill_tip_var).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(opt, text="Bill search px (0=auto):").grid(row=1, column=3, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Spinbox(opt, from_=0, to=500, textvariable=self.bill_search_length_var, width=8).grid(row=1, column=5, sticky="w", padx=(8, 16), pady=(8, 0))

        buttons = ttk.Frame(outer); buttons.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(buttons, text="Check Environment", command=self.check_env).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Run Pose Probe", command=self.run_probe_threaded).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Report", command=self.open_report).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Output Folder", command=lambda: open_folder(OUTPUT_DIR)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear Log", command=self.clear_log).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(outer, text="Log"); log_frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(log_frame, wrap=tk.WORD); self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.text.yview); scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=scroll.set)

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose HBMR crop folder for MMPose probe", initialdir=self.folder_var.get() or str(Path.home()))
        if folder:
            self.folder_var.set(folder); self.count_images()

    def choose_config(self) -> None:
        path = filedialog.askopenfilename(title="Choose MMPose config .py", filetypes=[("Python config", "*.py"), ("All files", "*.*")])
        if path: self.config_var.set(path)

    def choose_checkpoint(self) -> None:
        path = filedialog.askopenfilename(title="Choose MMPose checkpoint .pth", filetypes=[("PyTorch checkpoint", "*.pth"), ("All files", "*.*")])
        if path: self.checkpoint_var.set(path)

    def get_folder(self) -> Path:
        text = self.folder_var.get().strip().strip('"')
        if not text: raise RuntimeError("Choose a crop folder first.")
        folder = Path(text)
        if not folder.exists() or not folder.is_dir(): raise RuntimeError(f"Crop folder does not exist:\n{folder}")
        return folder

    def get_config(self) -> Path:
        text = self.config_var.get().strip().strip('"')
        if not text: raise RuntimeError("Choose an MMPose config .py file first.")
        path = Path(text)
        if not path.exists() or not path.is_file(): raise RuntimeError(f"Config file does not exist:\n{path}")
        return path

    def get_checkpoint(self) -> Path:
        text = self.checkpoint_var.get().strip().strip('"')
        if not text: raise RuntimeError("Choose an MMPose checkpoint .pth file first.")
        path = Path(text)
        if not path.exists() or not path.is_file(): raise RuntimeError(f"Checkpoint file does not exist:\n{path}")
        return path

    def count_images(self) -> None:
        try:
            self.log(f"Found {len(collect_images(self.get_folder(), self.recursive_var.get(), 0))} image crops.")
        except Exception as exc:
            messagebox.showerror("Count Images", str(exc))

    def check_env(self) -> None:
        self.log(""); self.log(check_environment_text())

    def run_probe_threaded(self) -> None:
        threading.Thread(target=self.run_probe, daemon=True).start()

    def run_probe(self) -> None:
        try:
            ensure_dirs()
            folder, config, checkpoint = self.get_folder(), self.get_config(), self.get_checkpoint()
            device = self.device_var.get().strip() or DEFAULT_DEVICE
            limit = int(self.limit_var.get())
            score_threshold = float(self.score_threshold_var.get())
            label_mode = self.label_mode_var.get().strip() or "AP-10K"
            estimate_bill_tip_enabled = bool(self.estimate_bill_tip_var.get())
            bill_search_length = int(self.bill_search_length_var.get())
            images = collect_images(folder, self.recursive_var.get(), limit)
            if not images: raise RuntimeError("No images found in selected crop folder.")

            self.log_threadsafe("\n============================================================")
            self.log_threadsafe(f"Starting MMPose probe | images={len(images)} | overlay={label_mode} | threshold={score_threshold} | bill_tip_candidates={estimate_bill_tip_enabled}")

            runner = MMPoseRunner(config, checkpoint, device, self.log_threadsafe)
            runner.load()
            results: list[PoseResult] = []
            started = time.time()

            for n, rec in enumerate(images, start=1):
                result = runner.infer_one(rec.path, score_threshold)
                result.image_index = rec.index
                result.image_path = str(rec.path)
                if result.ok and result.keypoint_records:
                    if estimate_bill_tip_enabled:
                        try:
                            result.derived_bill_tip_candidates = estimate_bill_tip_candidates(rec.path, result.keypoint_records, score_threshold, bill_search_length)
                        except Exception as exc:
                            result.error = (result.error + "\n" if result.error else "") + f"Derived bill-tip estimation failed: {exc}"
                    try:
                        draw_keypoints(rec.path, VISUALS_DIR / f"pose-{rec.index:05d}.jpg", result.keypoint_records, label_mode, score_threshold, result.derived_bill_tip_candidates)
                    except Exception as exc:
                        result.error = (result.error + "\n" if result.error else "") + f"Visualization failed: {exc}"
                results.append(result)
                if n == 1 or n % 5 == 0 or n == len(images):
                    self.log_threadsafe(f"Processed {n}/{len(images)} | with_keypoints={sum(1 for r in results if r.keypoint_records)} | {time.time()-started:.1f}s")

            meta = {
                "app": APP_NAME, "app_version": APP_VERSION, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "python_executable": sys.executable, "folder": str(folder), "config": str(config),
                "checkpoint": str(checkpoint), "device": device, "image_count": len(images),
                "backend": runner.backend, "score_threshold": score_threshold, "label_mode": label_mode,
                "estimate_bill_tip_candidates": estimate_bill_tip_enabled, "bill_search_length_px": bill_search_length,
            }
            self.log_threadsafe(f"Wrote predictions JSON: {write_predictions_json(results, meta)}")
            self.log_threadsafe(f"Wrote predictions CSV: {write_predictions_csv(results)}")
            self.log_threadsafe(f"Wrote bill-tip candidates CSV: {write_bill_candidates_csv(results)}")
            report = write_report_html(results, meta)
            self.log_threadsafe(f"Wrote report: {report}")
            webbrowser.open(report.resolve().as_uri())
        except Exception as exc:
            self.log_threadsafe("\nERROR:\n" + str(exc) + "\n\n" + traceback.format_exc())
            messagebox.showerror("MMPose Probe failed", str(exc))

    def open_report(self) -> None:
        if REPORT_HTML.exists(): webbrowser.open(REPORT_HTML.resolve().as_uri())
        else: messagebox.showinfo("Open Report", "No report exists yet. Run the probe first.")

    def clear_log(self) -> None:
        self.text.delete("1.0", tk.END)

    def log(self, message: str) -> None:
        self.text.insert(tk.END, message + "\n")
        self.text.see(tk.END)
        self.root.update_idletasks()

    def log_threadsafe(self, message: str) -> None:
        self.root.after(0, lambda: self.log(message))


def main() -> int:
    ensure_dirs()
    root = tk.Tk()
    MMPoseGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
