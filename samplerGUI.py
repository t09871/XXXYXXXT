# samplerGUI.py | HBMR / Birdbill v0.2.4 | 2026-06-30 PDT
"""
Birdbill SamplerGUI v0.2.4

Purpose:
    Debug bridge sampler that produces detector-cropped bird evidence for bill-tip training.

Key v0.2.4 correction:
    v0.2.2 saved full-frame sampler candidates. That made MMPose/AP-10K run on uncropped
    archive frames and produced garbage bill-base/nose points. v0.2.4 samples/cache-preps
    source frames/photos, runs MegaDetector on those images, and emits a manifest whose
    candidate_path points to MegaDetector bird crops, not raw full frames.

Storage discipline:
    - Outputs remain under D:/HBMR/output by default.
    - Full sampled frames are saved once under output/sampler-frames as detector input/cache.
    - Bird crops are not copied into sampler folders; MegaDetector owns output/crops.
    - Manifests route evidence; folders are not duplicated for best/weak/trainer.
    - samplerGUI does not call mmposeGUI.py or any other GUI.

Recommended immediate workflow:
    samplerGUI v0.2.4 -> newest output/sampler-reports/*-sampler-candidates.json
    -> billtipTrainerGUI v0.5.2 manifest import -> Force MMPose All on detector crops.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except Exception as exc:
    raise RuntimeError("tkinter is required for samplerGUI.py") from exc

try:
    import cv2
except Exception:
    cv2 = None

try:
    from PIL import Image, ImageOps
except Exception:
    Image = None
    ImageOps = None

APP_NAME = "Birdbill SamplerGUI"
APP_VERSION = "v0.2.4"
HEADER = f"samplerGUI.py | HBMR / Birdbill {APP_VERSION} | 2026-06-30 PDT"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

DEFAULT_OUTPUT_ROOT = r"D:/HBMR/output"
DEFAULT_HBMR_ROOT = r"D:\HBMR"
DEFAULT_HBMR_PYTHON = r"D:\HBMR\hbmr-env\Scripts\python.exe"
DEFAULT_MEGADETECTOR = r"D:\HBMR\megadetector.py"
DEFAULT_SAMPLE_SECONDS = 2.0
DEFAULT_BURST_SECONDS = 0.35
DEFAULT_BURST_RADIUS = 2
DEFAULT_MAX_BASE_FRAMES = 160
DEFAULT_JPEG_QUALITY = 95
DEFAULT_BEST_LIMIT = 80
DEFAULT_WEAK_LIMIT = 40


@dataclass
class CandidateRecord:
    run_id: str
    source_type: str
    source_path: str
    source_key: str
    sampled_frame_path: str
    candidate_path: str
    candidate_kind: str
    detector_confidence: float
    detector_index: int
    frame_number: Optional[int]
    time_sec: Optional[float]
    sequence_id: str
    burst_id: str
    neighbor_count: int
    sharpness_score: float
    brightness_score: float
    contrast_score: float
    edge_penalty: float
    identity_evidence_score: float
    evidence_rank: int
    evidence_bucket: str
    pose_found: str
    bill_base_x: float
    bill_base_y: float
    archive_context: str
    human_present: str
    hand_present: str
    human_contact_type: str
    friendship_score_delta: str
    friendship_reason: str
    notes: str


def now_stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def project_root() -> Path:
    return Path(__file__).resolve().parent


def default_hbmr_root() -> Path:
    p = project_root()
    if p.name.lower() == "hbmr":
        return p
    if p.parent.name.lower() == "hbmr":
        return p.parent
    return Path(DEFAULT_HBMR_ROOT)


def default_output_root() -> Path:
    root = default_hbmr_root()
    if root.exists():
        return root / "output"
    return Path(DEFAULT_OUTPUT_ROOT)


def safe_stem(path: Path) -> str:
    text = path.stem.strip().replace(" ", "-")
    out = []
    for ch in text:
        out.append(ch if ch.isalnum() or ch in "-_." else "-")
    return "".join(out).strip("-_.") or "source"


def short_hash(path: Path) -> str:
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    return hashlib.sha1(resolved.encode("utf-8", errors="ignore")).hexdigest()[:10]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_run_dirs(output_root: Path) -> dict[str, Path]:
    root = ensure_dir(output_root)
    return {
        "output_root": root,
        "frames": ensure_dir(root / "sampler-frames"),
        "crops": ensure_dir(root / "crops"),
        "reports": ensure_dir(root / "sampler-reports"),
        "logs": ensure_dir(root / "sampler-logs"),
    }


def collect_paths(raw_paths: Iterable[str], include_folders: bool) -> list[Path]:
    found: list[Path] = []
    for raw in raw_paths:
        if not raw:
            continue
        p = Path(str(raw).strip('"')).expanduser()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS | PHOTO_EXTENSIONS:
            found.append(p)
        elif p.is_dir() and include_folders:
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS | PHOTO_EXTENSIONS:
                    found.append(child)
    out, seen = [], set()
    for p in found:
        key = str(p.resolve()).lower() if p.exists() else str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def image_quality(path: Path) -> tuple[float, float, float, float, float]:
    if cv2 is None:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return (0.0, 0.0, 0.0, 1.0, 0.0)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean = float(gray.mean())
    std = float(gray.std())
    brightness = max(0.0, 1.0 - abs(mean - 128.0) / 128.0)
    contrast = min(std / 64.0, 1.5)
    sharp_norm = min(math.log1p(max(sharp, 0.0)) / 8.0, 1.5)
    h, w = gray.shape[:2]
    margin = max(4, int(min(h, w) * 0.04))
    center = gray[margin:-margin, margin:-margin] if h > margin * 2 and w > margin * 2 else gray
    edge_band = gray[:margin, :].std() + gray[-margin:, :].std() + gray[:, :margin].std() + gray[:, -margin:].std()
    edge_penalty = min(max((edge_band / 4.0 - center.std()) / 128.0, 0.0), 0.5) if center.size else 0.0
    evidence = (sharp_norm * 0.55) + (brightness * 0.15) + (contrast * 0.25) - (edge_penalty * 0.20)
    return (round(sharp_norm, 4), round(brightness, 4), round(contrast, 4), round(edge_penalty, 4), round(max(0.0, min(evidence, 1.5)), 4))


def write_frame(path: Path, frame, jpeg_quality: int) -> bool:
    if cv2 is None:
        return False
    ensure_dir(path.parent)
    return bool(cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]))


def normalize_photo(src: Path, dst: Path, jpeg_quality: int) -> bool:
    ensure_dir(dst.parent)
    if Image is None:
        shutil.copy2(src, dst)
        return True
    try:
        with Image.open(src) as im:
            if ImageOps is not None:
                im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(dst, quality=jpeg_quality)
        return True
    except Exception:
        shutil.copy2(src, dst)
        return True


def prep_video_frames(source: Path, dirs: dict[str, Path], run_id: str, sample_seconds: float, burst_seconds: float, burst_radius: int, max_base_frames: int, jpeg_quality: int, log) -> list[dict]:
    prepared: list[dict] = []
    if cv2 is None:
        log("ERROR: cv2 unavailable; cannot sample video.")
        return prepared
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        log(f"ERROR: Could not open video: {source}")
        return prepared
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    stem = safe_stem(source)
    skey = f"{stem}-{short_hash(source)}"
    seq = f"video-{skey}"
    stride = max(1, int(round(sample_seconds * fps)))
    burst_step = max(1, int(round(burst_seconds * fps)))
    base_frames = list(range(0, frame_count, stride)) if frame_count > 0 else []
    if max_base_frames > 0 and len(base_frames) > max_base_frames:
        step = len(base_frames) / max_base_frames
        base_frames = [base_frames[int(i * step)] for i in range(max_base_frames)]
    wanted: dict[int, tuple[str, str, int]] = {}
    for idx, base in enumerate(base_frames):
        burst_id = f"{seq}-burst-{idx:05d}"
        for offset in range(-burst_radius, burst_radius + 1):
            frame_no = base + offset * burst_step
            if frame_no < 0 or (frame_count > 0 and frame_no >= frame_count):
                continue
            wanted[frame_no] = ("base" if offset == 0 else "burst", burst_id, burst_radius * 2 + 1)
    log(f"Video prep: {source.name} | fps={fps:.2f} frames={frame_count} detector-inputs={len(wanted)}")
    for n, frame_no in enumerate(sorted(wanted), start=1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        role, burst_id, neighbor_count = wanted[frame_no]
        time_sec = frame_no / fps
        out_name = f"{run_id}-{stem}-frame-{frame_no:08d}-t{time_sec:07.2f}-{role}.jpg"
        out_path = dirs["frames"] / out_name
        if write_frame(out_path, frame, jpeg_quality):
            prepared.append({
                "source_type": "video", "source_path": str(source), "source_key": skey,
                "sampled_frame_path": str(out_path), "sampled_stem": out_path.stem,
                "frame_number": frame_no, "time_sec": round(time_sec, 4), "sequence_id": seq,
                "burst_id": burst_id, "neighbor_count": neighbor_count,
            })
        if n % 50 == 0:
            log(f"  prepared {n}/{len(wanted)} detector inputs")
    cap.release()
    return prepared


def prep_photo(source: Path, dirs: dict[str, Path], run_id: str, jpeg_quality: int, log) -> list[dict]:
    stem = safe_stem(source)
    skey = f"{stem}-{short_hash(source)}"
    out_path = dirs["frames"] / f"{run_id}-{stem}-photo-{skey}.jpg"
    normalize_photo(source, out_path, jpeg_quality)
    log(f"Photo prep: {source.name} -> {out_path.name}")
    return [{
        "source_type": "photo", "source_path": str(source), "source_key": skey,
        "sampled_frame_path": str(out_path), "sampled_stem": out_path.stem,
        "frame_number": None, "time_sec": None, "sequence_id": f"photo-{skey}",
        "burst_id": f"photo-{skey}", "neighbor_count": 1,
    }]


def run_megadetector(python_exe: Path, megadetector_py: Path, frame_dir: Path, hbmr_root: Path, log) -> bool:
    if not python_exe.exists():
        log(f"ERROR: MegaDetector Python not found: {python_exe}")
        return False
    if not megadetector_py.exists():
        log(f"ERROR: megadetector.py not found: {megadetector_py}")
        return False
    cmd = [str(python_exe), str(megadetector_py), str(frame_dir), "--no-pause"]
    log("Running MegaDetector on sampler detector-input frames...")
    log(" ".join(f'"{x}"' if " " in x else x for x in cmd))
    proc = subprocess.run(cmd, cwd=str(hbmr_root), text=True, capture_output=True)
    if proc.stdout.strip():
        log(proc.stdout.strip()[-4000:])
    if proc.stderr.strip():
        log("MegaDetector stderr: " + proc.stderr.strip()[-4000:])
    if proc.returncode != 0:
        log(f"ERROR: MegaDetector exited with code {proc.returncode}")
        return False
    return True


def parse_crop_conf(path: Path) -> tuple[int, float]:
    stem = path.stem
    idx = -1
    conf = 0.0
    import re
    m = re.search(r"-animal-(\d+)", stem)
    if m:
        try: idx = int(m.group(1))
        except Exception: pass
    m = re.search(r"-conf(\d+)", stem)
    if m:
        try: conf = int(m.group(1)) / 100.0
        except Exception: pass
    return idx, conf


def build_records_from_crops(prepared: list[dict], dirs: dict[str, Path], run_id: str, metadata: dict[str, str], best_limit: int, weak_limit: int, log) -> list[CandidateRecord]:
    records: list[CandidateRecord] = []
    crop_dir = dirs["crops"]
    for item in prepared:
        crops = sorted(crop_dir.glob(f"{item['sampled_stem']}-animal-*.png"))
        if not crops:
            continue
        for crop in crops:
            idx, conf = parse_crop_conf(crop)
            sharp, bright, contrast, edge, quality = image_quality(crop)
            # Basic detector-crop score. MMPose/bill scoring happens downstream.
            score = round(min(1.5, quality * 0.78 + min(conf, 1.0) * 0.22), 4)
            records.append(CandidateRecord(
                run_id=run_id,
                source_type=item["source_type"],
                source_path=item["source_path"],
                source_key=item["source_key"],
                sampled_frame_path=item["sampled_frame_path"],
                candidate_path=str(crop),
                candidate_kind="megadetector_crop",
                detector_confidence=round(conf, 4),
                detector_index=idx,
                frame_number=item["frame_number"],
                time_sec=item["time_sec"],
                sequence_id=item["sequence_id"],
                burst_id=item["burst_id"],
                neighbor_count=item["neighbor_count"],
                sharpness_score=sharp,
                brightness_score=bright,
                contrast_score=contrast,
                edge_penalty=edge,
                identity_evidence_score=score,
                evidence_rank=0,
                evidence_bucket="unranked",
                pose_found="no",
                bill_base_x=-1.0,
                bill_base_y=-1.0,
                archive_context=metadata["archive_context"],
                human_present=metadata["human_present"],
                hand_present=metadata["hand_present"],
                human_contact_type=metadata["human_contact_type"],
                friendship_score_delta=metadata["friendship_score_delta"],
                friendship_reason=metadata["friendship_reason"],
                notes="candidate_path is a MegaDetector crop; MMPose should run on this crop, not the sampled full frame",
            ))
    ranked = sorted(records, key=lambda r: r.identity_evidence_score, reverse=True)
    weak_ids = set(id(r) for r in list(reversed(ranked[-weak_limit:])) if weak_limit > 0)
    for rank, rec in enumerate(ranked, start=1):
        rec.evidence_rank = rank
        if rank <= best_limit:
            rec.evidence_bucket = "best"
        elif id(rec) in weak_ids:
            rec.evidence_bucket = "weak"
        else:
            rec.evidence_bucket = "middle"
    log(f"Detector crops found: {len(records)} from {len(prepared)} detector-input frames/photos")
    return records


def write_manifests(records: list[CandidateRecord], dirs: dict[str, Path], run_id: str, settings: dict) -> tuple[Path, Path, Path, Path]:
    report_dir = dirs["reports"]
    csv_path = report_dir / f"{run_id}-sampler-candidates.csv"
    json_path = report_dir / f"{run_id}-sampler-candidates.json"
    summary_path = report_dir / f"{run_id}-sampler-summary.txt"
    latest_json = dirs["output_root"] / "sampler-latest.json"
    latest_csv = dirs["output_root"] / "sampler-latest.csv"
    rows = [asdict(r) for r in sorted(records, key=lambda x: x.evidence_rank or 999999)]
    fieldnames = list(CandidateRecord.__dataclass_fields__.keys())
    for path in (csv_path, latest_csv):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for row in rows:
                w.writerow(row)
    for path in (json_path, latest_json):
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in records:
        counts[r.evidence_bucket] = counts.get(r.evidence_bucket, 0) + 1
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"{HEADER}\n")
        f.write(f"Run ID: {run_id}\nCreated: {_dt.datetime.now().isoformat(timespec='seconds')}\n\n")
        f.write("Critical correction:\n")
        f.write("  candidate_path points to MegaDetector bird crops in output\\crops, not full sampler frames.\n")
        f.write("  MMPose/billtip training should use candidate_path crop images.\n\n")
        f.write("Counts:\n")
        f.write(f"  total_detector_crops: {len(records)}\n")
        for k, v in sorted(counts.items()):
            f.write(f"  {k}: {v}\n")
        f.write("\nSettings:\n")
        for k, v in settings.items():
            f.write(f"  {k}: {v}\n")
        f.write("\nOutput folders:\n")
        for k, v in dirs.items():
            f.write(f"  {k}: {v}\n")
        f.write(f"\nLatest manifest copy: {latest_json}\n")
    return csv_path, json_path, summary_path, latest_json


class SamplerGUI(tk.Tk):
    def __init__(self, initial_paths: list[str]):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1000x740")
        self.minsize(920, 640)
        self.paths: list[str] = []
        self.worker: Optional[threading.Thread] = None
        self._build_ui()
        self.add_paths(initial_paths)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        top = ttk.LabelFrame(outer, text="Selected input videos/photos")
        top.pack(fill="both", expand=False)
        self.listbox = tk.Listbox(top, height=8, selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scroll = ttk.Scrollbar(top, command=self.listbox.yview)
        scroll.pack(side="right", fill="y", pady=8)
        self.listbox.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=6)
        ttk.Button(buttons, text="Add files", command=self.pick_files).pack(side="left")
        ttk.Button(buttons, text="Add folder shallow", command=self.pick_folder).pack(side="left", padx=5)
        ttk.Button(buttons, text="Clear", command=self.clear_paths).pack(side="left", padx=5)
        ttk.Button(buttons, text="Open output", command=self.open_output).pack(side="right")

        paths = ttk.LabelFrame(outer, text="Canonical paths")
        paths.pack(fill="x", pady=6)
        self.output_root = tk.StringVar(value=str(default_output_root()))
        self.hbmr_root = tk.StringVar(value=str(default_hbmr_root()))
        self.detector_python = tk.StringVar(value=DEFAULT_HBMR_PYTHON)
        self.megadetector_py = tk.StringVar(value=DEFAULT_MEGADETECTOR)
        self._path_row(paths, "output root", self.output_root)
        self._path_row(paths, "HBMR root", self.hbmr_root)
        self._path_row(paths, "MegaDetector Python", self.detector_python)
        self._path_row(paths, "megadetector.py", self.megadetector_py)

        settings = ttk.LabelFrame(outer, text="Sampling settings")
        settings.pack(fill="x", pady=6)
        row = ttk.Frame(settings)
        row.pack(fill="x", padx=8, pady=6)
        self.sample_seconds = tk.StringVar(value=str(DEFAULT_SAMPLE_SECONDS))
        self.burst_seconds = tk.StringVar(value=str(DEFAULT_BURST_SECONDS))
        self.burst_radius = tk.StringVar(value=str(DEFAULT_BURST_RADIUS))
        self.max_base_frames = tk.StringVar(value=str(DEFAULT_MAX_BASE_FRAMES))
        self.jpeg_quality = tk.StringVar(value=str(DEFAULT_JPEG_QUALITY))
        self.best_limit = tk.StringVar(value=str(DEFAULT_BEST_LIMIT))
        self.weak_limit = tk.StringVar(value=str(DEFAULT_WEAK_LIMIT))
        self._entry(row, "sample sec", self.sample_seconds, 7)
        self._entry(row, "burst sec", self.burst_seconds, 7)
        self._entry(row, "burst radius", self.burst_radius, 5)
        self._entry(row, "max base/video", self.max_base_frames, 7)
        self._entry(row, "jpg", self.jpeg_quality, 5)
        self._entry(row, "best rows", self.best_limit, 5)
        self._entry(row, "weak rows", self.weak_limit, 5)

        context = ttk.LabelFrame(outer, text="Archive/context metadata")
        context.pack(fill="x", pady=6)
        self.archive_context = tk.StringVar(value="finger_landing")
        self.human_present = tk.BooleanVar(value=True)
        self.hand_present = tk.BooleanVar(value=True)
        self.human_contact_type = tk.StringVar(value="finger_landing")
        self.friendship_score_delta = tk.StringVar(value="+1")
        self.friendship_reason = tk.StringVar(value="archive context indicates human/finger landing footage")
        c1 = ttk.Frame(context)
        c1.pack(fill="x", padx=8, pady=6)
        ttk.Label(c1, text="archive_context").pack(side="left")
        ttk.Combobox(c1, textvariable=self.archive_context, width=18, values=["finger_landing", "birdbath", "miss", "unknown", "other"]).pack(side="left", padx=4)
        ttk.Checkbutton(c1, text="human_present", variable=self.human_present).pack(side="left", padx=8)
        ttk.Checkbutton(c1, text="hand_present", variable=self.hand_present).pack(side="left", padx=8)
        ttk.Label(c1, text="contact_type").pack(side="left")
        ttk.Entry(c1, textvariable=self.human_contact_type, width=18).pack(side="left", padx=4)
        ttk.Label(c1, text="friendship_delta").pack(side="left")
        ttk.Entry(c1, textvariable=self.friendship_score_delta, width=8).pack(side="left", padx=4)
        c2 = ttk.Frame(context)
        c2.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(c2, text="friendship_reason").pack(side="left")
        ttk.Entry(c2, textvariable=self.friendship_reason).pack(side="left", fill="x", expand=True, padx=4)

        action = ttk.Frame(outer)
        action.pack(fill="x", pady=6)
        self.run_button = ttk.Button(action, text="Run samplerGUI v0.2.4", command=self.run_sampler)
        self.run_button.pack(side="left")
        self.status = ttk.Label(action, text="Ready. This version outputs detector crops for billtip training.")
        self.status.pack(side="left", padx=10)

        logframe = ttk.LabelFrame(outer, text="Log")
        logframe.pack(fill="both", expand=True)
        self.log_text = tk.Text(logframe, wrap="word", height=16)
        self.log_text.pack(side="left", fill="both", expand=True)
        logscroll = ttk.Scrollbar(logframe, command=self.log_text.yview)
        logscroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=logscroll.set)

    def _path_row(self, parent, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=8, pady=2)
        ttk.Label(row, text=label, width=20).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=4)

    def _entry(self, parent, label: str, var: tk.StringVar, width: int) -> None:
        ttk.Label(parent, text=label).pack(side="left")
        ttk.Entry(parent, textvariable=var, width=width).pack(side="left", padx=(3, 10))

    def log(self, msg: str) -> None:
        def append() -> None:
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
            self.status.configure(text=msg[:100])
        self.after(0, append)

    def pick_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select videos/photos",
            filetypes=[("Video/photo files", "*.mp4 *.mov *.avi *.mkv *.m4v *.wmv *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff"), ("All files", "*.*")],
        )
        self.add_paths(paths)

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select a folder for shallow import")
        if folder:
            self.add_paths([str(p) for p in collect_paths([folder], include_folders=True)])

    def add_paths(self, paths: Iterable[str]) -> None:
        for p in paths:
            s = str(p).strip('"')
            if s and s not in self.paths:
                self.paths.append(s)
                self.listbox.insert("end", s)

    def clear_paths(self) -> None:
        self.paths.clear()
        self.listbox.delete(0, "end")

    def open_output(self) -> None:
        out = ensure_dir(Path(self.output_root.get().strip() or str(default_output_root())))
        try:
            os.startfile(str(out))  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["explorer", str(out)])

    def metadata(self) -> dict[str, str]:
        return {
            "archive_context": self.archive_context.get().strip() or "unknown",
            "human_present": "yes" if self.human_present.get() else "no",
            "hand_present": "yes" if self.hand_present.get() else "no",
            "human_contact_type": self.human_contact_type.get().strip() or "unknown",
            "friendship_score_delta": self.friendship_score_delta.get().strip(),
            "friendship_reason": self.friendship_reason.get().strip(),
        }

    def parse_settings(self) -> dict:
        return {
            "output_root": self.output_root.get().strip() or str(default_output_root()),
            "hbmr_root": self.hbmr_root.get().strip() or str(default_hbmr_root()),
            "detector_python": self.detector_python.get().strip(),
            "megadetector_py": self.megadetector_py.get().strip(),
            "sample_seconds": float(self.sample_seconds.get()),
            "burst_seconds": float(self.burst_seconds.get()),
            "burst_radius": int(self.burst_radius.get()),
            "max_base_frames": int(self.max_base_frames.get()),
            "jpeg_quality": int(self.jpeg_quality.get()),
            "best_limit": int(self.best_limit.get()),
            "weak_limit": int(self.weak_limit.get()),
            **self.metadata(),
        }

    def run_sampler(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "Sampler is already running.")
            return
        if not self.paths:
            messagebox.showwarning(APP_NAME, "Add selected videos/photos first.")
            return
        try:
            settings = self.parse_settings()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Invalid settings: {exc}")
            return
        self.run_button.configure(state="disabled")
        self.worker = threading.Thread(target=self._run_worker, args=(settings,), daemon=True)
        self.worker.start()

    def _run_worker(self, settings: dict) -> None:
        try:
            run_id = f"samplerGUI-{now_stamp()}"
            dirs = make_run_dirs(Path(settings["output_root"]))
            log_file_path = dirs["logs"] / f"{run_id}-sampler-log.txt"
            def run_log(message: str) -> None:
                self.log(message)
                try:
                    with open(log_file_path, "a", encoding="utf-8") as lf:
                        lf.write(str(message) + "\n")
                except Exception:
                    pass
            hbmr_root = Path(settings["hbmr_root"])
            run_log(HEADER)
            run_log(f"Persistent log: {log_file_path}")
            run_log(f"Run ID: {run_id}")
            run_log(f"Output root: {dirs['output_root']}")
            paths = collect_paths(self.paths, include_folders=False)
            videos = [p for p in paths if p.suffix.lower() in VIDEO_EXTENSIONS]
            photos = [p for p in paths if p.suffix.lower() in PHOTO_EXTENSIONS]
            run_log(f"Selected inputs: {len(paths)} total | {len(videos)} videos | {len(photos)} photos")
            prepared: list[dict] = []
            for video in videos:
                prepared.extend(prep_video_frames(video, dirs, run_id, settings["sample_seconds"], settings["burst_seconds"], settings["burst_radius"], settings["max_base_frames"], settings["jpeg_quality"], self.log))
            for photo in photos:
                prepared.extend(prep_photo(photo, dirs, run_id, settings["jpeg_quality"], self.log))
            if not prepared:
                run_log("No detector-input frames/photos were prepared. Stopping.")
                return
            ok = run_megadetector(Path(settings["detector_python"]), Path(settings["megadetector_py"]), dirs["frames"], hbmr_root, self.log)
            if not ok:
                run_log("MegaDetector failed; no crop manifest written.")
                return
            records = build_records_from_crops(prepared, dirs, run_id, self.metadata(), settings["best_limit"], settings["weak_limit"], self.log)
            csv_path, json_path, summary_path, latest_json = write_manifests(records, dirs, run_id, settings)
            run_log(f"CSV manifest: {csv_path}")
            run_log(f"JSON manifest: {json_path}")
            run_log(f"Latest manifest: {latest_json}")
            run_log(f"Summary: {summary_path}")
            run_log("Done. Use sampler-latest.json or the run JSON in billtipTrainerGUI v0.5.2 manifest import.")
            self.open_output()
        except Exception:
            try:
                run_log("ERROR during sampler run:")
                run_log(traceback.format_exc())
            except Exception:
                self.log("ERROR during sampler run:")
                self.log(traceback.format_exc())
        finally:
            self.after(0, lambda: self.run_button.configure(state="normal"))


def main(argv: list[str]) -> int:
    app = SamplerGUI(argv[1:])
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
