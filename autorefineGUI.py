# autorefineGUI.py | HBMR / Birdbill AutoRefine Probe v0.1.0 | 2026-06-25 PDT
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "HBMR / Birdbill AutoRefine Probe"
APP_VERSION = "v0.1.0"
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "autorefine"
VISUALS_DIR = OUTPUT_DIR / "visuals"
REGIONS_JSON = OUTPUT_DIR / "autorefine-regions.json"
REGIONS_CSV = OUTPUT_DIR / "autorefine-regions.csv"
REPORT_HTML = OUTPUT_DIR / "autorefine-report.html"

REGION_NAMES = ["head", "throat", "body", "tail"]
REGION_DIRS = {name: OUTPUT_DIR / name for name in REGION_NAMES}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_DEVICE = "cpu"
DEFAULT_SCORE_THRESHOLD = 0.15
DEFAULT_CROP_SCALE = 1.0

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

REGION_PRIORITY = {
    "head": 1,
    "throat": 2,
    "body": 3,
    "tail": 4,
}

REGION_NOTES = {
    "head": "highest-priority AutoRefine crop; expected useful for local verification",
    "throat": "high-priority gorget/throat proxy; diagnostic but pose/lighting dependent",
    "body": "high-priority body crop; likely best initial LightGlue evidence region",
    "tail": "lowest-priority retained candidate; diagnostic when visible but anatomically unstable",
}


@dataclass
class ImageRecord:
    index: int
    path: Path


@dataclass
class KeypointRecord:
    index: int
    ap10k_label: str
    birdbill_label: str
    x: float
    y: float
    score: float
    visible: bool


@dataclass
class RegionRecord:
    image_index: int
    image_path: str
    region: str
    priority: int
    ok: bool
    reason: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    width: int
    height: int
    crop_path: str
    recipe: str
    note: str


@dataclass
class PoseResult:
    image_index: int
    image_path: str
    ok: bool
    error: str
    keypoints: list[list[float]]
    scores: list[float]
    keypoint_records: list[KeypointRecord]
    regions: list[RegionRecord]
    backend: str


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VISUALS_DIR.mkdir(parents=True, exist_ok=True)
    for folder in REGION_DIRS.values():
        folder.mkdir(parents=True, exist_ok=True)


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
            x=float(kp[0]),
            y=float(kp[1]),
            score=float(score),
            visible=float(score) >= float(score_threshold),
        ))
    return records


def rec_by_index(records: list[KeypointRecord], idx: int, score_threshold: float) -> KeypointRecord | None:
    for rec in records:
        if rec.index == idx and rec.score >= score_threshold:
            return rec
    return None


def available_points(records: list[KeypointRecord], indexes: list[int], score_threshold: float) -> list[KeypointRecord]:
    out = []
    for idx in indexes:
        rec = rec_by_index(records, idx, score_threshold)
        if rec is not None:
            out.append(rec)
    return out


def clamp_box(box: tuple[float, float, float, float], image_w: int, image_h: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1i = max(0, min(image_w - 1, int(round(min(x1, x2)))))
    y1i = max(0, min(image_h - 1, int(round(min(y1, y2)))))
    x2i = max(1, min(image_w, int(round(max(x1, x2)))))
    y2i = max(1, min(image_h, int(round(max(y1, y2)))))
    if x2i <= x1i:
        x2i = min(image_w, x1i + 1)
    if y2i <= y1i:
        y2i = min(image_h, y1i + 1)
    return x1i, y1i, x2i, y2i


def bbox_from_points(points: list[KeypointRecord], image_w: int, image_h: int, pad_ratio: float, min_size: int, scale: float = 1.0) -> tuple[int, int, int, int]:
    xs = [p.x for p in points]
    ys = [p.y for p in points]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    w = max(1.0, x2 - x1)
    h = max(1.0, y2 - y1)
    side_w = max(w * (1.0 + pad_ratio * 2.0) * scale, float(min_size))
    side_h = max(h * (1.0 + pad_ratio * 2.0) * scale, float(min_size))
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return clamp_box((cx - side_w / 2.0, cy - side_h / 2.0, cx + side_w / 2.0, cy + side_h / 2.0), image_w, image_h)


def box_centered(cx: float, cy: float, w: float, h: float, image_w: int, image_h: int) -> tuple[int, int, int, int]:
    return clamp_box((cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0), image_w, image_h)


def distance(a: KeypointRecord, b: KeypointRecord) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def median(values: list[float], fallback: float) -> float:
    vals = sorted(v for v in values if v > 0)
    if not vals:
        return fallback
    mid = len(vals) // 2
    if len(vals) % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def pose_scale(records: list[KeypointRecord], image_w: int, image_h: int, score_threshold: float) -> float:
    pairs = [(0, 1), (2, 3), (3, 4), (5, 8), (11, 14), (5, 11), (8, 14)]
    vals = []
    for a_idx, b_idx in pairs:
        a = rec_by_index(records, a_idx, score_threshold)
        b = rec_by_index(records, b_idx, score_threshold)
        if a and b:
            vals.append(distance(a, b))
    return max(24.0, median(vals, min(image_w, image_h) * 0.22))


def make_region_records(image_index: int, image_path: Path, records: list[KeypointRecord], image_w: int, image_h: int, score_threshold: float, crop_scale: float) -> list[RegionRecord]:
    regions: list[RegionRecord] = []
    scale_px = pose_scale(records, image_w, image_h, score_threshold)

    def add_region(region: str, ok: bool, reason: str, confidence: float, box: tuple[int, int, int, int] | None, recipe: str) -> None:
        if box is None:
            x1 = y1 = x2 = y2 = width = height = 0
            crop_path = ""
        else:
            x1, y1, x2, y2 = box
            width, height = x2 - x1, y2 - y1
            crop_path = str((REGION_DIRS[region] / f"{image_index:05d}-{image_path.stem}-{region}.jpg").resolve())
        regions.append(RegionRecord(
            image_index=image_index,
            image_path=str(image_path),
            region=region,
            priority=REGION_PRIORITY[region],
            ok=ok,
            reason=reason,
            confidence=max(0.0, min(1.0, float(confidence))),
            x1=x1, y1=y1, x2=x2, y2=y2,
            width=width, height=height,
            crop_path=crop_path,
            recipe=recipe,
            note=REGION_NOTES[region],
        ))

    head_points = available_points(records, [0, 1, 2, 3], score_threshold)
    if len(head_points) >= 2:
        scores = [p.score for p in head_points]
        box = bbox_from_points(head_points, image_w, image_h, pad_ratio=0.75, min_size=int(scale_px * 1.15), scale=crop_scale)
        add_region("head", True, "made from visible eye/nose/neck anchors", sum(scores) / len(scores), box, "bbox AP10K 0/1/2/3 with generous padding")
    else:
        add_region("head", False, "not enough visible head anchors", 0.0, None, "requires at least two of AP10K 0/1/2/3")

    nose = rec_by_index(records, 2, score_threshold)
    neck = rec_by_index(records, 3, score_threshold)
    shoulders = available_points(records, [5, 8], score_threshold)
    if neck and (nose or shoulders):
        pts = [neck] + ([nose] if nose else []) + shoulders
        scores = [p.score for p in pts]
        # Bias throat/gorget below bill/head and around neck/shoulder triangle.
        if shoulders:
            sx = sum(p.x for p in shoulders) / len(shoulders)
            sy = sum(p.y for p in shoulders) / len(shoulders)
            cx = (neck.x * 0.55) + (sx * 0.45)
            cy = (neck.y * 0.55) + (sy * 0.45)
        elif nose:
            cx = (neck.x * 0.70) + (nose.x * 0.30)
            cy = (neck.y * 0.70) + (nose.y * 0.30)
        else:
            cx, cy = neck.x, neck.y
        box = box_centered(cx, cy, scale_px * 1.15 * crop_scale, scale_px * 1.15 * crop_scale, image_w, image_h)
        add_region("throat", True, "made from neck with nose/shoulder support", sum(scores) / len(scores), box, "center between neck and shoulders/nose; square crop")
    else:
        add_region("throat", False, "neck/gorget proxy not reliable", 0.0, None, "requires AP10K 3 plus nose or shoulders")

    body_points = available_points(records, [3, 4, 5, 8, 11, 14], score_threshold)
    if len(body_points) >= 3:
        scores = [p.score for p in body_points]
        box = bbox_from_points(body_points, image_w, image_h, pad_ratio=0.45, min_size=int(scale_px * 1.85), scale=crop_scale)
        add_region("body", True, "made from neck/tail/shoulder/flank anchors", sum(scores) / len(scores), box, "bbox AP10K 3/4/5/8/11/14 with body padding")
    else:
        add_region("body", False, "not enough visible body anchors", 0.0, None, "requires at least three of AP10K 3/4/5/8/11/14")

    tail = rec_by_index(records, 4, score_threshold)
    rear_points = available_points(records, [4, 11, 14, 12, 15], score_threshold)
    if tail and len(rear_points) >= 2:
        scores = [p.score for p in rear_points]
        box = bbox_from_points(rear_points, image_w, image_h, pad_ratio=0.90, min_size=int(scale_px * 1.35), scale=crop_scale)
        add_region("tail", True, "tail-root/rear-body estimate; low-priority diagnostic", min(scores) * 0.85, box, "bbox AP10K 4/11/14/12/15 with large padding")
    elif tail:
        box = box_centered(tail.x, tail.y, scale_px * 1.25 * crop_scale, scale_px * 1.25 * crop_scale, image_w, image_h)
        add_region("tail", True, "tail-root only; very tentative", tail.score * 0.55, box, "centered on AP10K 4 only")
    else:
        add_region("tail", False, "tail root not visible/reliable", 0.0, None, "requires AP10K 4")

    return regions


def save_region_crops(image_path: Path, regions: list[RegionRecord]) -> None:
    from PIL import Image, ImageOps
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    for region in regions:
        if not region.ok or not region.crop_path:
            continue
        crop = img.crop((region.x1, region.y1, region.x2, region.y2))
        out = Path(region.crop_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out, quality=94)


def draw_visual(image_path: Path, out_path: Path, keypoints: list[KeypointRecord], regions: list[RegionRecord], score_threshold: float) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 13)
        small_font = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    # Pillow supports named colors; keep this visual simple and legible for manual review.
    region_style = {
        "head": ("red", "head"),
        "throat": ("purple", "throat"),
        "body": ("lime", "body"),
        "tail": ("cyan", "tail"),
    }
    for region in sorted(regions, key=lambda r: r.priority):
        if not region.ok:
            continue
        color, label = region_style.get(region.region, ("white", region.region))
        for offset in range(2):
            draw.rectangle((region.x1 + offset, region.y1 + offset, region.x2 - offset, region.y2 - offset), outline=color)
        txt = f"{label} {region.confidence:.2f}"
        tx, ty = region.x1 + 4, region.y1 + 4
        try:
            bbox = draw.textbbox((tx, ty), txt, font=font)
            draw.rectangle(bbox, fill="black")
        except Exception:
            pass
        draw.text((tx, ty), txt, fill="white", font=font)

    for rec in keypoints:
        visible = rec.score >= score_threshold
        r = 3 if visible else 2
        fill = "yellow" if visible else "orange"
        draw.ellipse((rec.x - r, rec.y - r, rec.x + r, rec.y + r), fill=fill, outline="black")
        if rec.index in [0, 1, 2, 3, 4, 5, 8, 11, 14]:
            label = f"{rec.index}"
            draw.text((rec.x + 4, rec.y + 4), label, fill="white", font=small_font)
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

    def infer_one(self, image_path: Path, score_threshold: float, crop_scale: float) -> PoseResult:
        try:
            from PIL import Image, ImageOps
            from mmpose.apis import inference_topdown
            raw = inference_topdown(self.model, str(image_path))
            result = raw[0] if isinstance(raw, list) and raw else raw
            keypoints, scores = extract_keypoints_from_result(result)
            kp_records = build_keypoint_records(keypoints, scores, score_threshold)
            img = Image.open(image_path)
            img = ImageOps.exif_transpose(img)
            regions = make_region_records(-1, image_path, kp_records, img.width, img.height, score_threshold, crop_scale)
            return PoseResult(-1, str(image_path), True, "", keypoints, scores, kp_records, regions, self.backend)
        except Exception as exc:
            return PoseResult(-1, str(image_path), False, str(exc), [], [], [], [], self.backend)


def write_regions_json(results: list[PoseResult], meta: dict[str, Any]) -> Path:
    payload = {
        "metadata": meta,
        "schema": {
            "source_model_schema": "AP-10K 17 keypoints",
            "ap10k_labels": AP10K_LABELS,
            "birdbill_interpretation_labels": BIRDBILL_LABELS,
            "region_names": REGION_NAMES,
            "region_priority": REGION_PRIORITY,
            "lightglue_direction": "These region crops are derived evidence artifacts intended for later local verification tests.",
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
                "regions": [region.__dict__ for region in r.regions],
            }
            for r in results
        ],
    }
    REGIONS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return REGIONS_JSON


def write_regions_csv(results: list[PoseResult]) -> Path:
    with REGIONS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "image_index", "image_path", "region", "priority", "ok", "reason", "confidence",
            "x1", "y1", "x2", "y2", "width", "height", "crop_path", "recipe", "note",
        ])
        for result in results:
            if result.regions:
                for region in result.regions:
                    writer.writerow([
                        region.image_index, region.image_path, region.region, region.priority, region.ok,
                        region.reason, f"{region.confidence:.4f}", region.x1, region.y1, region.x2, region.y2,
                        region.width, region.height, region.crop_path, region.recipe, region.note,
                    ])
            else:
                writer.writerow([result.image_index, result.image_path, "", "", False, result.error, "", "", "", "", "", "", "", "", "", ""])
    return REGIONS_CSV


def relpath_for_html(path: Path) -> str:
    try:
        return path.resolve().relative_to(OUTPUT_DIR.resolve()).as_posix()
    except Exception:
        return path.resolve().as_uri()


def write_report_html(results: list[PoseResult], meta: dict[str, Any]) -> Path:
    cards = []
    for result in results:
        visual = VISUALS_DIR / f"autorefine-{result.image_index:05d}.jpg"
        visual_html = f'<img class="visual" src="{html.escape(relpath_for_html(visual))}" />' if visual.exists() else ""
        thumbs = []
        for region in sorted(result.regions, key=lambda x: x.priority):
            if region.ok and region.crop_path and Path(region.crop_path).exists():
                thumbs.append(
                    f'<div class="thumb"><div><b>{html.escape(region.region)}</b> conf {region.confidence:.2f}</div>'
                    f'<img src="{html.escape(relpath_for_html(Path(region.crop_path)))}" />'
                    f'<div class="tiny">{html.escape(region.reason)}</div></div>'
                )
            else:
                thumbs.append(
                    f'<div class="thumb missing"><div><b>{html.escape(region.region)}</b></div>'
                    f'<div class="tiny">No crop: {html.escape(region.reason)}</div></div>'
                )
        rows = []
        for region in sorted(result.regions, key=lambda x: x.priority):
            cls = "ok" if region.ok else "bad"
            rows.append(
                f"<tr class='{cls}'><td>{html.escape(region.region)}</td><td>{region.priority}</td>"
                f"<td>{region.ok}</td><td>{region.confidence:.3f}</td><td>{region.x1},{region.y1},{region.x2},{region.y2}</td>"
                f"<td>{html.escape(region.reason)}</td><td>{html.escape(region.recipe)}</td></tr>"
            )
        table = "<table><thead><tr><th>Region</th><th>Priority</th><th>OK</th><th>Confidence</th><th>Box</th><th>Reason</th><th>Recipe</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        cards.append(
            f"<section class='card'><h2>{html.escape(Path(result.image_path).name)}</h2>"
            f"<div class='path'>{html.escape(result.image_path)}</div>"
            f"<div><b>OK:</b> {result.ok} &nbsp; <b>Regions:</b> {sum(1 for r in result.regions if r.ok)}/{len(result.regions)} &nbsp; <b>Backend:</b> {html.escape(result.backend)}</div>"
            f"<div class='error'>{html.escape(result.error)}</div>"
            f"<div>{visual_html}</div><div class='thumbs'>{''.join(thumbs)}</div>{table}</section>"
        )
    text = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AutoRefine Probe Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #fafafa; color: #222; }}
.meta, .card {{ background: white; border: 1px solid #ddd; border-radius: 12px; padding: 14px; margin: 14px 0; }}
.path {{ font-size: 12px; color: #555; overflow-wrap: anywhere; margin-bottom: 8px; }}
.error {{ color: #8a0000; font-size: 13px; margin: 8px 0; white-space: pre-wrap; }}
.visual {{ max-width: 900px; max-height: 700px; border: 1px solid #ccc; border-radius: 8px; object-fit: contain; }}
.thumbs {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 12px 0; align-items: flex-start; }}
.thumb {{ width: 210px; border: 1px solid #ddd; border-radius: 8px; padding: 8px; background: #fcfcfc; }}
.thumb img {{ max-width: 200px; max-height: 180px; object-fit: contain; display: block; margin: 6px auto; border: 1px solid #ddd; }}
.thumb.missing {{ background: #fff7e8; color: #666; min-height: 90px; }}
.tiny {{ font-size: 12px; color: #555; overflow-wrap: anywhere; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f0f0f0; }}
tr.bad {{ background: #fff7e8; color: #666; }}
</style></head><body>
<h1>HBMR / Birdbill AutoRefine Probe Report</h1>
<div class="meta">
<div><b>App:</b> {html.escape(APP_NAME)} {html.escape(APP_VERSION)}</div>
<div><b>Created:</b> {html.escape(str(meta.get('created_at', '')))}</div>
<div><b>Config:</b> {html.escape(str(meta.get('config', '')))}</div>
<div><b>Checkpoint:</b> {html.escape(str(meta.get('checkpoint', '')))}</div>
<div><b>Device:</b> {html.escape(str(meta.get('device', '')))}</div>
<div><b>Images:</b> {html.escape(str(meta.get('image_count', '')))}</div>
<div><b>Score threshold:</b> {html.escape(str(meta.get('score_threshold', '')))}</div>
<div><b>Crop scale:</b> {html.escape(str(meta.get('crop_scale', '')))}</div>
</div>
<div class="meta"><b>Region priorities:</b> 1 head, 2 throat/gorget, 3 body, 4 tail. Wings and bill-tip are intentionally deferred. Output crops are derived evidence artifacts intended for later LightGlue/local verification tests.</div>
{''.join(cards)}
</body></html>"""
    REPORT_HTML.write_text(text, encoding="utf-8")
    return REPORT_HTML


class AutoRefineGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1140x840")
        self.folder_var = tk.StringVar(value="")
        self.config_var = tk.StringVar(value="")
        self.checkpoint_var = tk.StringVar(value="")
        self.device_var = tk.StringVar(value=DEFAULT_DEVICE)
        self.recursive_var = tk.BooleanVar(value=True)
        self.limit_var = tk.IntVar(value=25)
        self.score_threshold_var = tk.DoubleVar(value=DEFAULT_SCORE_THRESHOLD)
        self.crop_scale_var = tk.DoubleVar(value=DEFAULT_CROP_SCALE)
        self._build_ui()
        self.log(f"{APP_NAME} {APP_VERSION}")
        self.log("Standalone pose-derived anatomical crop exporter for AutoRefine testing.")
        self.log("No HBMR database will be modified. Wings and bill-tip are intentionally deferred.")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text="AutoRefine Probe: pose-derived anatomical crops", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Goal: export head, throat/gorget, body, and tail evidence crops for later LightGlue/local verification tests.").pack(anchor="w", pady=(2, 12))

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
        ttk.Label(opt, text="Crop scale:").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(opt, from_=0.5, to=3.0, increment=0.1, textvariable=self.crop_scale_var, width=6).grid(row=0, column=7, sticky="w", padx=(8, 16))
        ttk.Checkbutton(opt, text="Recursive", variable=self.recursive_var).grid(row=0, column=8, sticky="w")

        buttons = ttk.Frame(outer); buttons.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(buttons, text="Check Environment", command=self.check_env).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Run AutoRefine Probe", command=self.run_threaded).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Report", command=self.open_report).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Output Folder", command=lambda: open_folder(OUTPUT_DIR)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear Log", command=self.clear_log).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(outer, text="Log"); log_frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(log_frame, wrap=tk.WORD); self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.text.yview); scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=scroll.set)

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose HBMR crop folder for AutoRefine probe", initialdir=self.folder_var.get() or str(Path.home()))
        if folder:
            self.folder_var.set(folder); self.count_images()

    def choose_config(self) -> None:
        path = filedialog.askopenfilename(title="Choose MMPose config .py", filetypes=[("Python config", "*.py"), ("All files", "*.*")])
        if path:
            self.config_var.set(path)

    def choose_checkpoint(self) -> None:
        path = filedialog.askopenfilename(title="Choose MMPose checkpoint .pth", filetypes=[("PyTorch checkpoint", "*.pth"), ("All files", "*.*")])
        if path:
            self.checkpoint_var.set(path)

    def get_folder(self) -> Path:
        text = self.folder_var.get().strip().strip('"')
        if not text:
            raise RuntimeError("Choose a crop folder first.")
        folder = Path(text)
        if not folder.exists() or not folder.is_dir():
            raise RuntimeError(f"Crop folder does not exist:\n{folder}")
        return folder

    def get_config(self) -> Path:
        text = self.config_var.get().strip().strip('"')
        if not text:
            raise RuntimeError("Choose an MMPose config .py file first.")
        path = Path(text)
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Config file does not exist:\n{path}")
        return path

    def get_checkpoint(self) -> Path:
        text = self.checkpoint_var.get().strip().strip('"')
        if not text:
            raise RuntimeError("Choose an MMPose checkpoint .pth file first.")
        path = Path(text)
        if not path.exists() or not path.is_file():
            raise RuntimeError(f"Checkpoint file does not exist:\n{path}")
        return path

    def count_images(self) -> None:
        try:
            self.log(f"Found {len(collect_images(self.get_folder(), self.recursive_var.get(), 0))} image crops.")
        except Exception as exc:
            messagebox.showerror("Count Images", str(exc))

    def check_env(self) -> None:
        self.log(""); self.log(check_environment_text())

    def run_threaded(self) -> None:
        threading.Thread(target=self.run_probe, daemon=True).start()

    def run_probe(self) -> None:
        try:
            ensure_dirs()
            folder, config, checkpoint = self.get_folder(), self.get_config(), self.get_checkpoint()
            device = self.device_var.get().strip() or DEFAULT_DEVICE
            limit = int(self.limit_var.get())
            score_threshold = float(self.score_threshold_var.get())
            crop_scale = float(self.crop_scale_var.get())
            images = collect_images(folder, self.recursive_var.get(), limit)
            if not images:
                raise RuntimeError("No images found in selected crop folder.")

            self.log_threadsafe("\n============================================================")
            self.log_threadsafe(f"Starting AutoRefine probe | images={len(images)} | threshold={score_threshold} | crop_scale={crop_scale}")
            self.log_threadsafe("Regions: head, throat/gorget, body, tail. Wings and bill-tip deferred.")

            runner = MMPoseRunner(config, checkpoint, device, self.log_threadsafe)
            runner.load()
            results: list[PoseResult] = []
            started = time.time()

            for n, rec in enumerate(images, start=1):
                result = runner.infer_one(rec.path, score_threshold, crop_scale)
                result.image_index = rec.index
                result.image_path = str(rec.path)
                for region in result.regions:
                    region.image_index = rec.index
                    region.image_path = str(rec.path)
                    if region.crop_path:
                        region.crop_path = str((REGION_DIRS[region.region] / f"{rec.index:05d}-{rec.path.stem}-{region.region}.jpg").resolve())
                if result.ok and result.regions:
                    try:
                        save_region_crops(rec.path, result.regions)
                        draw_visual(rec.path, VISUALS_DIR / f"autorefine-{rec.index:05d}.jpg", result.keypoint_records, result.regions, score_threshold)
                    except Exception as exc:
                        result.error = (result.error + "\n" if result.error else "") + f"AutoRefine crop/visualization failed: {exc}"
                results.append(result)
                if n == 1 or n % 5 == 0 or n == len(images):
                    ok_regions = sum(1 for r in results for region in r.regions if region.ok)
                    self.log_threadsafe(f"Processed {n}/{len(images)} | ok_region_crops={ok_regions} | {time.time()-started:.1f}s")

            meta = {
                "app": APP_NAME,
                "app_version": APP_VERSION,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "python_executable": sys.executable,
                "folder": str(folder),
                "config": str(config),
                "checkpoint": str(checkpoint),
                "device": device,
                "image_count": len(images),
                "backend": runner.backend,
                "score_threshold": score_threshold,
                "crop_scale": crop_scale,
                "regions": REGION_NAMES,
                "database_writes": False,
                "lightglue_direction": "Region crops are intended as evidence crops for later LightGlue/local verification testing.",
            }
            self.log_threadsafe(f"Wrote regions JSON: {write_regions_json(results, meta)}")
            self.log_threadsafe(f"Wrote regions CSV: {write_regions_csv(results)}")
            report = write_report_html(results, meta)
            self.log_threadsafe(f"Wrote report: {report}")
            webbrowser.open(report.resolve().as_uri())
        except Exception as exc:
            self.log_threadsafe("\nERROR:\n" + str(exc) + "\n\n" + traceback.format_exc())
            messagebox.showerror("AutoRefine Probe failed", str(exc))

    def open_report(self) -> None:
        if REPORT_HTML.exists():
            webbrowser.open(REPORT_HTML.resolve().as_uri())
        else:
            messagebox.showinfo("Open Report", "No report exists yet. Run the probe first.")

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
    AutoRefineGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
