# autosortGUI.py | HBMR / Birdbill AutoSort Probe v0.1.2 | 2026-06-25 PDT
from __future__ import annotations

import csv
import html
import itertools
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from dataclasses import dataclass, asdict
import re
from pathlib import Path
from typing import Any, Protocol

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "HBMR / Birdbill AutoSort Probe"
APP_VERSION = "v0.1.2"
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "autosort"
VISUALS_DIR = OUTPUT_DIR / "visuals"
REPORT_HTML = OUTPUT_DIR / "autosort-report.html"
PAIRS_CSV = OUTPUT_DIR / "autosort-pairs.csv"
PAIRS_JSON = OUTPUT_DIR / "autosort-pairs.json"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_DEVICE = "cpu"
DEFAULT_MAX_IMAGES = 50
DEFAULT_MAX_PAIRS = 500
DEFAULT_TOP_N = 100


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    VISUALS_DIR.mkdir(parents=True, exist_ok=True)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if platform.system().lower().startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def collect_images(folder: Path, recursive: bool = True, limit: int = 0) -> list[Path]:
    if recursive:
        paths = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    else:
        paths = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    paths = sorted(paths, key=lambda p: str(p).lower())
    if limit and limit > 0:
        paths = paths[:limit]
    return paths


def safe_rel(path: Path, base: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except Exception:
        return str(path)




def image_source_key(path: Path) -> str:
    """Best-effort source video/session key from HBMR/AutoRefine-style filenames.

    This is intentionally conservative. It strips common frame/crop/region suffixes so
    AutoSort can avoid spending its best matches on adjacent frames from the same video.
    """
    stem = path.stem
    # AutoRefine files often preserve original crop names with region suffixes.
    for suffix in ["-head", "-throat", "-body", "-tail", "_head", "_throat", "_body", "_tail"]:
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    patterns = [
        r"-frame-\d{6,10}-t\d+(?:\.\d+)?-animal-\d+.*$",
        r"-frame-\d{6,10}.*$",
        r"_frame_\d{6,10}.*$",
        r"-animal-\d+.*$",
    ]
    for pat in patterns:
        new = re.sub(pat, "", stem, flags=re.IGNORECASE)
        if new != stem:
            stem = new
            break
    return stem or path.parent.name


def image_frame_number(path: Path) -> int | None:
    m = re.search(r"(?:-|_)frame(?:-|_)(\d{6,10})", path.stem, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def should_skip_pair(a: Path, b: Path, skip_same_source: bool, skip_near_frames: bool, near_frame_window: int) -> tuple[bool, str]:
    sa = image_source_key(a)
    sb = image_source_key(b)
    if skip_same_source and sa == sb:
        return True, "same_source"
    if skip_near_frames and sa == sb:
        fa = image_frame_number(a)
        fb = image_frame_number(b)
        if fa is not None and fb is not None and abs(fa - fb) <= near_frame_window:
            return True, "near_frame"
    return False, ""

def check_environment_text() -> str:
    lines = [
        f"{APP_NAME} {APP_VERSION}",
        f"Python executable: {sys.executable}",
        f"Python version: {sys.version.split()[0]}",
        f"Working folder: {ROOT}",
        f"Output folder: {OUTPUT_DIR}",
        "",
    ]
    for mod in ["torch", "lightglue", "cv2", "PIL", "numpy"]:
        try:
            imported = __import__(mod)
            lines.append(f"{mod}: {getattr(imported, '__version__', 'installed')}")
        except Exception as exc:
            lines.append(f"{mod}: NOT FOUND ({type(exc).__name__}: {exc})")
    lines.append("")
    lines.append("LightGlue import note:")
    lines.append("AutoSort must run inside the same Python environment where LightGlue is installed.")
    lines.append("If LightGlue says NOT FOUND here, edit autosortGUI.bat PYTHON_EXE or install LightGlue into this interpreter.")
    lines.append(f"Install target command would be: \"{sys.executable}\" -m pip install lightglue")
    try:
        import torch
        lines.append(f"torch.cuda.is_available: {torch.cuda.is_available()}")
    except Exception:
        pass
    return "\n".join(lines)


@dataclass
class PairScore:
    rank: int
    image_a: str
    image_b: str
    image_a_name: str
    image_b_name: str
    image_a_source: str
    image_b_source: str
    comparison_mode: str
    scorer: str
    score: float
    score_label: str
    matches: int
    mean_match_score: float
    keypoints_a: int
    keypoints_b: int
    decision_hint: str
    error: str
    visual_path: str


class Scorer(Protocol):
    name: str
    def score_pair(self, image_a: Path, image_b: Path) -> dict[str, Any]: ...


class OrbScorer:
    """Small dependency-light local feature scorer.

    This is not intended to replace LightGlue. It exists as a v0.1 fallback and
    sanity check so the AutoSort workbench still runs if LightGlue is missing.
    """
    name = "orb-fallback-v0.1"

    def __init__(self, max_features: int = 1500) -> None:
        import cv2
        self.cv2 = cv2
        self.orb = cv2.ORB_create(nfeatures=max_features)
        self.cache: dict[str, tuple[Any, Any]] = {}

    def features(self, path: Path):
        key = str(path.resolve())
        if key in self.cache:
            return self.cache[key]
        img = self.cv2.imread(str(path), self.cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError(f"Could not read image: {path}")
        kps, desc = self.orb.detectAndCompute(img, None)
        kps = kps or []
        self.cache[key] = (kps, desc)
        return kps, desc

    def score_pair(self, image_a: Path, image_b: Path) -> dict[str, Any]:
        kpa, da = self.features(image_a)
        kpb, db = self.features(image_b)
        if da is None or db is None or len(kpa) < 4 or len(kpb) < 4:
            return {"score": 0.0, "matches": 0, "mean_match_score": 0.0, "keypoints_a": len(kpa), "keypoints_b": len(kpb)}
        matcher = self.cv2.BFMatcher(self.cv2.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(da, db)
        if not matches:
            return {"score": 0.0, "matches": 0, "mean_match_score": 0.0, "keypoints_a": len(kpa), "keypoints_b": len(kpb)}
        distances = [float(m.distance) for m in matches]
        good = [d for d in distances if d <= 64.0]
        mean_dist = sum(distances) / max(1, len(distances))
        mean_quality = max(0.0, 1.0 - mean_dist / 96.0)
        coverage = len(good) / max(1.0, min(len(kpa), len(kpb)))
        score = max(0.0, min(1.0, 0.65 * mean_quality + 0.35 * min(1.0, coverage * 4.0)))
        return {
            "score": score,
            "matches": len(good),
            "mean_match_score": mean_quality,
            "keypoints_a": len(kpa),
            "keypoints_b": len(kpb),
        }


class LightGlueScorer:
    name = "lightglue-superpoint-v0.1"

    def __init__(self, device: str = DEFAULT_DEVICE, max_keypoints: int = 2048) -> None:
        import torch
        try:
            from lightglue import LightGlue, SuperPoint
            from lightglue.utils import load_image, rbd
        except Exception as exc:
            raise RuntimeError(
                "LightGlue import failed in this Python interpreter. "
                f"Python executable: {sys.executable}. "
                "Run Check Environment, then point autosortGUI.bat at the interpreter where LightGlue is installed. "
                f"Original import error: {type(exc).__name__}: {exc}"
            ) from exc
        self.torch = torch
        self.load_image = load_image
        self.rbd = rbd
        self.device = device
        self.extractor = SuperPoint(max_num_keypoints=max_keypoints).eval().to(device)
        self.matcher = LightGlue(features="superpoint").eval().to(device)
        self.cache: dict[str, Any] = {}

    def features(self, path: Path) -> Any:
        key = str(path.resolve())
        if key in self.cache:
            return self.cache[key]
        image = self.load_image(str(path)).to(self.device)
        with self.torch.no_grad():
            feats = self.extractor.extract(image)
        self.cache[key] = feats
        return feats

    def score_pair(self, image_a: Path, image_b: Path) -> dict[str, Any]:
        try:
            feats_a = self.features(image_a)
            feats_b = self.features(image_b)
            with self.torch.no_grad():
                matches01 = self.matcher({"image0": feats_a, "image1": feats_b})
            fa, fb, m01 = [self.rbd(x) for x in [feats_a, feats_b, matches01]]
            matches = m01.get("matches", [])
            scores = m01.get("scores", [])
            try:
                match_count = int(matches.shape[0])
            except Exception:
                match_count = len(matches)
            try:
                mean_score = float(scores.float().mean().item()) if match_count else 0.0
            except Exception:
                mean_score = 0.0
            try:
                kpa = int(fa["keypoints"].shape[0])
                kpb = int(fb["keypoints"].shape[0])
            except Exception:
                kpa = kpb = 0
            # Conservative v0.1 normalized ranking score. This is not a final identity threshold.
            coverage = match_count / max(1.0, min(kpa or 1, kpb or 1))
            score = max(0.0, min(1.0, 0.70 * mean_score + 0.30 * min(1.0, coverage * 6.0)))
            return {"score": score, "matches": match_count, "mean_match_score": mean_score, "keypoints_a": kpa, "keypoints_b": kpb}
        except Exception as exc:
            raise RuntimeError(f"LightGlue scoring failed: {exc}") from exc


def make_scorer(kind: str, device: str, max_keypoints: int, log) -> Scorer:
    if kind == "LightGlue SuperPoint":
        log("Loading LightGlue/SuperPoint scorer.")
        return LightGlueScorer(device=device, max_keypoints=max_keypoints)
    if kind == "ORB fallback":
        log("Loading ORB fallback scorer.")
        return OrbScorer(max_features=max_keypoints)
    if kind == "Auto: LightGlue then ORB":
        try:
            log("Trying LightGlue/SuperPoint scorer.")
            return LightGlueScorer(device=device, max_keypoints=max_keypoints)
        except Exception as exc:
            log(f"LightGlue unavailable in Python executable: {sys.executable}")
            log(f"Using ORB fallback. Reason: {exc}")
            log("To force failure instead of fallback, choose scorer: LightGlue SuperPoint.")
            return OrbScorer(max_features=max_keypoints)
    raise RuntimeError(f"Unknown scorer: {kind}")


def decision_hint(score: float, matches: int, scorer_name: str) -> str:
    if matches <= 0 or score <= 0.05:
        return "no_local_evidence"
    if score >= 0.72:
        return "strong_candidate"
    if score >= 0.50:
        return "medium_candidate"
    if score >= 0.30:
        return "weak_candidate"
    return "low_candidate"


def label_score(score: float) -> str:
    return f"{score:.4f}"


def make_pair_visual(image_a: Path, image_b: Path, out_path: Path, score: PairScore) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    ia = ImageOps.exif_transpose(Image.open(image_a)).convert("RGB")
    ib = ImageOps.exif_transpose(Image.open(image_b)).convert("RGB")
    max_side = 360
    ia.thumbnail((max_side, max_side))
    ib.thumbnail((max_side, max_side))
    w = ia.width + ib.width + 18
    h = max(ia.height, ib.height) + 70
    canvas = Image.new("RGB", (w, h), "white")
    canvas.paste(ia, (0, 45))
    canvas.paste(ib, (ia.width + 18, 45))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
        small = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        font = ImageFont.load_default()
        small = ImageFont.load_default()
    draw.text((6, 4), f"#{score.rank} {score.decision_hint} score={score.score:.4f} matches={score.matches} mean={score.mean_match_score:.3f}", fill=(0, 0, 0), font=font)
    draw.text((6, 24), score.image_a_name, fill=(40, 40, 40), font=small)
    draw.text((ia.width + 24, 24), score.image_b_name, fill=(40, 40, 40), font=small)
    canvas.save(out_path, quality=92)


def write_pairs_csv(pairs: list[PairScore]) -> Path:
    with PAIRS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "image_a", "image_b", "image_a_name", "image_b_name", "image_a_source", "image_b_source", "comparison_mode", "scorer", "score", "score_label", "matches", "mean_match_score", "keypoints_a", "keypoints_b", "decision_hint", "error", "visual_path"])
        for p in pairs:
            writer.writerow([p.rank, p.image_a, p.image_b, p.image_a_name, p.image_b_name, p.image_a_source, p.image_b_source, p.comparison_mode, p.scorer, f"{p.score:.6f}", p.score_label, p.matches, f"{p.mean_match_score:.6f}", p.keypoints_a, p.keypoints_b, p.decision_hint, p.error, p.visual_path])
    return PAIRS_CSV


def write_pairs_json(pairs: list[PairScore], meta: dict[str, Any]) -> Path:
    payload = {"metadata": meta, "schema": {"purpose": "AutoSort pair ranking only; no identity decisions or DB writes."}, "pairs": [asdict(p) for p in pairs]}
    PAIRS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return PAIRS_JSON


def rel_for_output(path: Path) -> str:
    try:
        return path.resolve().relative_to(OUTPUT_DIR.resolve()).as_posix()
    except Exception:
        return path.resolve().as_uri()


def write_report_html(pairs: list[PairScore], meta: dict[str, Any]) -> Path:
    rows = []
    for p in pairs:
        visual = Path(p.visual_path)
        img = f'<img src="{html.escape(rel_for_output(visual))}" />' if visual.exists() else ""
        rows.append(f"""
<section class='card'>
<h2>#{p.rank} {html.escape(p.decision_hint)} — score {p.score:.4f}</h2>
<div class='sub'><b>{html.escape(p.image_a_name)}</b> ↔ <b>{html.escape(p.image_b_name)}</b></div>
<div class='sub'>sources: {html.escape(p.image_a_source)} ↔ {html.escape(p.image_b_source)} | mode={html.escape(p.comparison_mode)}</div>
<div class='sub'>matches={p.matches} | mean_match_score={p.mean_match_score:.3f} | keypoints={p.keypoints_a}/{p.keypoints_b} | scorer={html.escape(p.scorer)}</div>
<div class='error'>{html.escape(p.error)}</div>
<div class='image'>{img}</div>
</section>""")
    text = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Birdbill AutoSort Probe</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #fafafa; color: #222; }}
.meta, .card {{ background: white; border: 1px solid #ddd; border-radius: 12px; padding: 14px; margin: 14px 0; }}
.sub {{ color: #444; font-size: 13px; margin: 4px 0; overflow-wrap: anywhere; }}
.error {{ color: #8a0000; font-size: 13px; margin: 6px 0; white-space: pre-wrap; }}
.image img {{ max-width: 760px; border: 1px solid #ccc; border-radius: 8px; object-fit: contain; }}
</style></head><body>
<h1>HBMR / Birdbill AutoSort Probe Report</h1>
<div class='meta'>
<div><b>App:</b> {html.escape(str(meta.get('app')))} {html.escape(str(meta.get('app_version')))}</div>
<div><b>Created:</b> {html.escape(str(meta.get('created_at')))}</div>
<div><b>Input folder:</b> {html.escape(str(meta.get('folder')))}</div>
<div><b>Reference folder:</b> {html.escape(str(meta.get('reference_folder', '')))}</div>
<div><b>Mode:</b> {html.escape(str(meta.get('comparison_mode', '')))}</div>
<div><b>Images:</b> {html.escape(str(meta.get('image_count')))}</div>
<div><b>Pairs scored:</b> {html.escape(str(meta.get('pair_count')))}</div>
<div><b>Scorer:</b> {html.escape(str(meta.get('scorer')))}</div>
<div><b>Device:</b> {html.escape(str(meta.get('device')))}</div>
</div>
<div class='meta'><b>Interpretation:</b> This report ranks likely same-bird candidate pairs for human review. It does not write identities and does not modify the HBMR database. Refined AutoRefine crops such as head, throat, body, and tail folders are preferred inputs.</div>
{''.join(rows)}
</body></html>"""
    REPORT_HTML.write_text(text, encoding="utf-8")
    return REPORT_HTML


class AutoSortGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1120x820")
        self.folder_var = tk.StringVar(value="")
        self.reference_folder_var = tk.StringVar(value="")
        self.comparison_mode_var = tk.StringVar(value="All vs all")
        self.skip_same_source_var = tk.BooleanVar(value=True)
        self.skip_near_frames_var = tk.BooleanVar(value=False)
        self.near_frame_window_var = tk.IntVar(value=180)
        self.recursive_var = tk.BooleanVar(value=True)
        self.max_images_var = tk.IntVar(value=DEFAULT_MAX_IMAGES)
        self.max_pairs_var = tk.IntVar(value=DEFAULT_MAX_PAIRS)
        self.top_n_var = tk.IntVar(value=DEFAULT_TOP_N)
        self.device_var = tk.StringVar(value=DEFAULT_DEVICE)
        self.max_keypoints_var = tk.IntVar(value=2048)
        self.scorer_var = tk.StringVar(value="Auto: LightGlue then ORB")
        self._build_ui()
        self.log(f"{APP_NAME} {APP_VERSION}")
        self.log("Standalone AutoSort pair-ranking probe. No HBMR database will be modified.")
        self.log("Recommended input: AutoRefine evidence folders. Use Cross-source or Query vs Reference to avoid adjacent-frame rediscovery.")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        ttk.Label(outer, text="AutoSort Probe: local evidence pair ranking", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Goal: rank likely same-bird crop pairs from AutoRefine evidence crops before any DB integration.").pack(anchor="w", pady=(2, 12))

        folder_frame = ttk.LabelFrame(outer, text="Evidence crop folders")
        folder_frame.pack(fill=tk.X, pady=(0, 8))
        row = ttk.Frame(folder_frame, padding=(8, 8, 8, 4))
        row.pack(fill=tk.X)
        ttk.Label(row, text="Query / input:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.folder_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(row, text="Choose", command=self.choose_folder).pack(side=tk.LEFT)
        row2 = ttk.Frame(folder_frame, padding=(8, 4, 8, 8))
        row2.pack(fill=tk.X)
        ttk.Label(row2, text="Reference:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.reference_folder_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(row2, text="Choose", command=self.choose_reference_folder).pack(side=tk.LEFT)
        ttk.Button(row2, text="Count Images", command=self.count_images).pack(side=tk.LEFT, padx=(8, 0))

        options = ttk.LabelFrame(outer, text="Run settings")
        options.pack(fill=tk.X, pady=(0, 8))
        opt = ttk.Frame(options, padding=8)
        opt.pack(fill=tk.X)
        ttk.Label(opt, text="Mode:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opt, textvariable=self.comparison_mode_var, values=["All vs all", "Cross-source only", "Query folder vs reference folder"], width=27).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Scorer:").grid(row=0, column=2, sticky="w")
        ttk.Combobox(opt, textvariable=self.scorer_var, values=["Auto: LightGlue then ORB", "LightGlue SuperPoint", "ORB fallback"], width=24).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Device:").grid(row=0, column=4, sticky="w")
        ttk.Combobox(opt, textvariable=self.device_var, values=["cpu", "cuda:0"], width=10).grid(row=0, column=5, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Max images:").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(opt, from_=2, to=5000, textvariable=self.max_images_var, width=8).grid(row=0, column=7, sticky="w", padx=(8, 16))
        ttk.Label(opt, text="Max pairs:").grid(row=0, column=8, sticky="w")
        ttk.Spinbox(opt, from_=1, to=200000, textvariable=self.max_pairs_var, width=9).grid(row=0, column=9, sticky="w", padx=(8, 16))
        ttk.Checkbutton(opt, text="Recursive", variable=self.recursive_var).grid(row=0, column=10, sticky="w")

        opt2 = ttk.Frame(options, padding=(8, 0, 8, 8))
        opt2.pack(fill=tk.X)
        ttk.Label(opt2, text="Top report pairs:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(opt2, from_=1, to=5000, textvariable=self.top_n_var, width=8).grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(opt2, text="Max keypoints/features:").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(opt2, from_=128, to=8192, increment=128, textvariable=self.max_keypoints_var, width=8).grid(row=0, column=3, sticky="w", padx=(8, 16))
        ttk.Checkbutton(opt2, text="Skip same source", variable=self.skip_same_source_var).grid(row=0, column=4, sticky="w", padx=(8, 16))
        ttk.Checkbutton(opt2, text="Skip near frames", variable=self.skip_near_frames_var).grid(row=0, column=5, sticky="w", padx=(8, 8))
        ttk.Label(opt2, text="Frame window:").grid(row=0, column=6, sticky="w")
        ttk.Spinbox(opt2, from_=0, to=100000, increment=30, textvariable=self.near_frame_window_var, width=8).grid(row=0, column=7, sticky="w", padx=(8, 16))

        buttons = ttk.Frame(outer)
        buttons.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(buttons, text="Check Environment", command=self.check_env).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Run AutoSort Probe", command=self.run_threaded).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Report", command=self.open_report).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Output Folder", command=lambda: open_folder(OUTPUT_DIR)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear Log", command=self.clear_log).pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(outer, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(log_frame, wrap=tk.WORD)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=scroll.set)

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose query/input AutoRefine evidence crop folder", initialdir=self.folder_var.get() or str(Path.home()))
        if folder:
            self.folder_var.set(folder)
            self.count_images()

    def choose_reference_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose reference/profile evidence crop folder", initialdir=self.reference_folder_var.get() or str(Path.home()))
        if folder:
            self.reference_folder_var.set(folder)
            self.count_images()

    def get_folder(self) -> Path:
        text = self.folder_var.get().strip().strip('"')
        if not text:
            raise RuntimeError("Choose an evidence crop folder first.")
        folder = Path(text)
        if not folder.exists() or not folder.is_dir():
            raise RuntimeError(f"Evidence crop folder does not exist:\n{folder}")
        return folder

    def get_reference_folder(self) -> Path:
        text = self.reference_folder_var.get().strip().strip('"')
        if not text:
            raise RuntimeError("Choose a reference folder first, or use All vs all / Cross-source only mode.")
        folder = Path(text)
        if not folder.exists() or not folder.is_dir():
            raise RuntimeError(f"Reference folder does not exist:\n{folder}")
        return folder

    def count_images(self) -> None:
        try:
            q = len(collect_images(self.get_folder(), self.recursive_var.get(), 0))
            msg = f"Query/input images: {q}"
            if self.reference_folder_var.get().strip():
                r = len(collect_images(self.get_reference_folder(), self.recursive_var.get(), 0))
                msg += f" | reference images: {r}"
            self.log(msg)
        except Exception as exc:
            messagebox.showerror("Count Images", str(exc))

    def check_env(self) -> None:
        self.log("")
        self.log(check_environment_text())

    def run_threaded(self) -> None:
        threading.Thread(target=self.run, daemon=True).start()

    def run(self) -> None:
        try:
            ensure_dirs()
            folder = self.get_folder()
            max_images = int(self.max_images_var.get())
            max_pairs = int(self.max_pairs_var.get())
            top_n = int(self.top_n_var.get())
            device = self.device_var.get().strip() or DEFAULT_DEVICE
            max_keypoints = int(self.max_keypoints_var.get())
            scorer_kind = self.scorer_var.get().strip()
            comparison_mode = self.comparison_mode_var.get().strip() or "All vs all"
            skip_same_source = bool(self.skip_same_source_var.get()) or comparison_mode == "Cross-source only"
            skip_near_frames = bool(self.skip_near_frames_var.get())
            near_frame_window = int(self.near_frame_window_var.get())
            images = collect_images(folder, self.recursive_var.get(), max_images)
            reference_images: list[Path] = []
            skipped_count = 0
            if comparison_mode == "Query folder vs reference folder":
                ref_folder = self.get_reference_folder()
                reference_images = collect_images(ref_folder, self.recursive_var.get(), max_images)
                if not images or not reference_images:
                    raise RuntimeError("Need at least one query image and one reference image.")
                raw_pairs = [(a, b) for a in images for b in reference_images if a.resolve() != b.resolve()]
            else:
                ref_folder = None
                if len(images) < 2:
                    raise RuntimeError("Need at least two images for AutoSort pair ranking.")
                raw_pairs = list(itertools.combinations(images, 2))
            all_pairs = []
            for a, b in raw_pairs:
                skip, reason = should_skip_pair(a, b, skip_same_source, skip_near_frames, near_frame_window)
                if skip:
                    skipped_count += 1
                    continue
                all_pairs.append((a, b))
            if max_pairs and len(all_pairs) > max_pairs:
                all_pairs = all_pairs[:max_pairs]
            if not all_pairs:
                raise RuntimeError("No eligible pairs after filters. Try disabling Skip same source or use Query folder vs reference folder.")

            self.log_threadsafe("\n============================================================")
            self.log_threadsafe(f"Starting AutoSort probe | mode={comparison_mode} | query_images={len(images)} | reference_images={len(reference_images)} | pairs={len(all_pairs)} | skipped={skipped_count} | scorer={scorer_kind}")
            scorer = make_scorer(scorer_kind, device, max_keypoints, self.log_threadsafe)
            started = time.time()
            scored: list[PairScore] = []

            for i, (a, b) in enumerate(all_pairs, start=1):
                err = ""
                try:
                    data = scorer.score_pair(a, b)
                    score = float(data.get("score", 0.0))
                    matches = int(data.get("matches", 0))
                    mean = float(data.get("mean_match_score", 0.0))
                    kpa = int(data.get("keypoints_a", 0))
                    kpb = int(data.get("keypoints_b", 0))
                except Exception as exc:
                    score, matches, mean, kpa, kpb = 0.0, 0, 0.0, 0, 0
                    err = str(exc)
                scored.append(PairScore(
                    rank=0,
                    image_a=str(a),
                    image_b=str(b),
                    image_a_name=a.name,
                    image_b_name=b.name,
                    image_a_source=image_source_key(a),
                    image_b_source=image_source_key(b),
                    comparison_mode=comparison_mode,
                    scorer=getattr(scorer, "name", scorer_kind),
                    score=score,
                    score_label=label_score(score),
                    matches=matches,
                    mean_match_score=mean,
                    keypoints_a=kpa,
                    keypoints_b=kpb,
                    decision_hint=decision_hint(score, matches, getattr(scorer, "name", scorer_kind)),
                    error=err,
                    visual_path="",
                ))
                if i == 1 or i % 25 == 0 or i == len(all_pairs):
                    self.log_threadsafe(f"Scored {i}/{len(all_pairs)} pairs | elapsed={time.time()-started:.1f}s")

            scored.sort(key=lambda p: (p.score, p.matches, p.mean_match_score), reverse=True)
            report_pairs = scored[:max(1, min(top_n, len(scored)))]
            for rank, p in enumerate(scored, start=1):
                p.rank = rank
            for p in report_pairs:
                out = VISUALS_DIR / f"pair-{p.rank:05d}.jpg"
                try:
                    make_pair_visual(Path(p.image_a), Path(p.image_b), out, p)
                    p.visual_path = str(out)
                except Exception as exc:
                    p.error = (p.error + "\n" if p.error else "") + f"Pair visual failed: {exc}"

            meta = {
                "app": APP_NAME,
                "app_version": APP_VERSION,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "python_executable": sys.executable,
                "folder": str(folder),
                "reference_folder": str(ref_folder) if ref_folder else "",
                "comparison_mode": comparison_mode,
                "skip_same_source": skip_same_source,
                "skip_near_frames": skip_near_frames,
                "near_frame_window": near_frame_window,
                "image_count": len(images),
                "reference_image_count": len(reference_images),
                "pair_count": len(scored),
                "reported_pairs": len(report_pairs),
                "scorer": getattr(scorer, "name", scorer_kind),
                "device": device,
                "max_keypoints": max_keypoints,
                "note": "Ranks candidate same-bird pairs only; no identity decisions or database writes.",
            }
            self.log_threadsafe(f"Wrote pairs CSV: {write_pairs_csv(scored)}")
            self.log_threadsafe(f"Wrote pairs JSON: {write_pairs_json(scored, meta)}")
            report = write_report_html(report_pairs, meta)
            self.log_threadsafe(f"Wrote report: {report}")
            webbrowser.open(report.resolve().as_uri())
        except Exception as exc:
            self.log_threadsafe("\nERROR:\n" + str(exc) + "\n\n" + traceback.format_exc())
            messagebox.showerror("AutoSort Probe failed", str(exc))

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
    AutoSortGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
