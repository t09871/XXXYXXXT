# wildid.py | HBMR / Birdbill WildID Probe v0.1.0 | 2026-06-25 PDT
"""
WildID Probe GUI for HBMR / Birdbill.

Purpose:
- Standalone animal re-ID embedding probe using MegaDescriptor via timm/Hugging Face.
- Lets the user select an existing crop folder through a GUI.
- Computes embeddings for image crops in place.
- Produces nearest-neighbor similarity reports without modifying HBMR databases.

Canonical intended location:
D:\HBMR\wildid\wildid.py

Outputs:
D:\HBMR\wildid\output\wildid-nearest-neighbors.csv
D:\HBMR\wildid\output\wildid-embeddings.json
D:\HBMR\wildid\output\wildid-report.html
D:\HBMR\wildid\output\thumbs\

Dependencies:
torch
torchvision
timm
pillow
"""

from __future__ import annotations

import csv
import html
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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "HBMR / Birdbill WildID Probe"
APP_VERSION = "v0.1.0"
APP_DATE = "2026-06-25 PDT"

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
THUMBS_DIR = OUTPUT_DIR / "thumbs"

DEFAULT_MODEL_NAME = "hf-hub:BVRA/MegaDescriptor-T-224"
DEFAULT_TOP_K = 8

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"
}


@dataclass
class ImageRecord:
    index: int
    path: Path


@dataclass
class MatchRecord:
    query_index: int
    query_path: str
    rank: int
    match_index: int
    match_path: str
    score: float


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if platform.system().lower().startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def collect_images(folder: Path, recursive: bool = True) -> list[ImageRecord]:
    if not folder.exists() or not folder.is_dir():
        return []

    if recursive:
        paths = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    else:
        paths = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]

    paths = sorted(paths, key=lambda p: str(p).lower())
    return [ImageRecord(index=i, path=p) for i, p in enumerate(paths)]


def import_dependencies():
    missing = []
    try:
        import torch  # noqa: F401
    except Exception:
        missing.append("torch")

    try:
        import timm  # noqa: F401
    except Exception:
        missing.append("timm")

    try:
        from PIL import Image  # noqa: F401
    except Exception:
        missing.append("pillow")

    if missing:
        raise RuntimeError(
            "Missing dependencies: "
            + ", ".join(missing)
            + "\n\nInstall these in the Python environment used to run this GUI."
        )

    import torch
    import timm
    from PIL import Image, ImageOps
    return torch, timm, Image, ImageOps


def make_transform(image_size: int):
    import torchvision.transforms as T

    return T.Compose([
        T.Resize((image_size, image_size)),
        T.ToTensor(),
        T.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ])


def infer_image_size(model_name: str) -> int:
    if "518" in model_name:
        return 518
    if "384" in model_name:
        return 384
    if "288" in model_name:
        return 288
    return 224


def compute_embeddings(
    images: list[ImageRecord],
    model_name: str,
    progress: Callable[[str], None],
) -> tuple[list[list[float]], dict]:
    torch, timm, Image, ImageOps = import_dependencies()

    if not images:
        raise RuntimeError("No images found.")

    image_size = infer_image_size(model_name)
    progress(f"Loading model: {model_name}")
    progress("First run may download model weights if they are not already cached.")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    progress(f"Device: {device}")

    model = timm.create_model(model_name, num_classes=0, pretrained=True)
    model.eval()
    model.to(device)

    transform = make_transform(image_size)
    embeddings: list[list[float]] = []
    started = time.time()

    with torch.no_grad():
        for n, rec in enumerate(images, start=1):
            try:
                img = Image.open(rec.path)
                img = ImageOps.exif_transpose(img).convert("RGB")
                tensor = transform(img).unsqueeze(0).to(device)
                feat = model(tensor)
                if isinstance(feat, (list, tuple)):
                    feat = feat[0]
                feat = feat.flatten(start_dim=1)
                feat = torch.nn.functional.normalize(feat, p=2, dim=1)
                embeddings.append(feat.squeeze(0).detach().cpu().float().tolist())

                if n == 1 or n % 5 == 0 or n == len(images):
                    progress(f"Embedded {n}/{len(images)} images ({time.time() - started:.1f}s)")
            except Exception as exc:
                raise RuntimeError(f"Failed on image:\n{rec.path}\n\n{exc}") from exc

    meta = {
        "app": APP_NAME,
        "app_version": APP_VERSION,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model_name": model_name,
        "image_size": image_size,
        "device": device,
        "embedding_count": len(embeddings),
        "embedding_dim": len(embeddings[0]) if embeddings else 0,
        "source_folder": str(images[0].path.parent) if images else "",
    }
    return embeddings, meta


def cosine(a: list[float], b: list[float]) -> float:
    dot = aa = bb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        aa += x * x
        bb += y * y
    if aa <= 0.0 or bb <= 0.0:
        return 0.0
    return dot / math.sqrt(aa * bb)


def nearest_neighbors(
    images: list[ImageRecord],
    embeddings: list[list[float]],
    top_k: int,
    progress: Callable[[str], None],
) -> list[MatchRecord]:
    if len(images) != len(embeddings):
        raise RuntimeError("Image/embedding count mismatch.")

    top_k = max(1, min(top_k, max(1, len(images) - 1)))
    matches: list[MatchRecord] = []

    for i, emb in enumerate(embeddings):
        scored: list[tuple[float, int]] = []
        for j, other in enumerate(embeddings):
            if i == j:
                continue
            scored.append((cosine(emb, other), j))
        scored.sort(reverse=True, key=lambda x: x[0])

        for rank, (score, j) in enumerate(scored[:top_k], start=1):
            matches.append(MatchRecord(
                query_index=i,
                query_path=str(images[i].path),
                rank=rank,
                match_index=j,
                match_path=str(images[j].path),
                score=score,
            ))

        if (i + 1) % 20 == 0 or i + 1 == len(images):
            progress(f"Compared {i + 1}/{len(images)} images")

    return matches


def safe_thumb_name(index: int, path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return f"thumb-{index:05d}{suffix}"


def make_thumbnails(images: list[ImageRecord], progress: Callable[[str], None]) -> dict[int, Path]:
    _, _, Image, ImageOps = import_dependencies()
    thumb_paths: dict[int, Path] = {}

    for n, rec in enumerate(images, start=1):
        out = THUMBS_DIR / safe_thumb_name(rec.index, rec.path)
        try:
            img = Image.open(rec.path)
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((220, 220))
            img.save(out, quality=88)
            thumb_paths[rec.index] = out
        except Exception:
            pass

        if n % 50 == 0 or n == len(images):
            progress(f"Prepared thumbnails {n}/{len(images)}")

    return thumb_paths


def write_embeddings_json(images: list[ImageRecord], embeddings: list[list[float]], meta: dict) -> Path:
    ensure_dirs()
    out = OUTPUT_DIR / "wildid-embeddings.json"
    payload = {
        "metadata": meta,
        "items": [
            {"index": rec.index, "path": str(rec.path), "embedding": embeddings[i]}
            for i, rec in enumerate(images)
        ],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def write_matches_csv(matches: list[MatchRecord]) -> Path:
    ensure_dirs()
    out = OUTPUT_DIR / "wildid-nearest-neighbors.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["query_index", "query_path", "rank", "match_index", "match_path", "score"])
        for m in matches:
            writer.writerow([m.query_index, m.query_path, m.rank, m.match_index, m.match_path, f"{m.score:.6f}"])
    return out


def relpath_for_html(path: Path) -> str:
    try:
        return path.resolve().relative_to(OUTPUT_DIR.resolve()).as_posix()
    except Exception:
        return path.resolve().as_uri()


def write_report_html(
    images: list[ImageRecord],
    matches: list[MatchRecord],
    meta: dict,
    thumb_paths: dict[int, Path],
) -> Path:
    ensure_dirs()
    out = OUTPUT_DIR / "wildid-report.html"

    by_query: dict[int, list[MatchRecord]] = {}
    for m in matches:
        by_query.setdefault(m.query_index, []).append(m)

    rows = []
    for rec in images:
        q_thumb = thumb_paths.get(rec.index)
        q_img = f'<img src="{html.escape(relpath_for_html(q_thumb))}" />' if q_thumb else ""
        cards = []
        for m in by_query.get(rec.index, [])[:DEFAULT_TOP_K]:
            match_thumb = thumb_paths.get(m.match_index)
            match_img = f'<img src="{html.escape(relpath_for_html(match_thumb))}" />' if match_thumb else ""
            cards.append(
                "<div class='match-card'>"
                f"{match_img}"
                f"<div><b>Rank {m.rank}</b></div>"
                f"<div>Score: {m.score:.4f}</div>"
                f"<div class='path'>{html.escape(Path(m.match_path).name)}</div>"
                "</div>"
            )
        rows.append(
            "<section class='query'>"
            "<div class='query-head'>"
            f"<div class='query-img'>{q_img}</div>"
            "<div>"
            f"<h2>{html.escape(rec.path.name)}</h2>"
            f"<div class='path'>{html.escape(str(rec.path))}</div>"
            "</div></div>"
            "<div class='matches'>" + "\n".join(cards) + "</div>"
            "</section>"
        )

    html_text = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>WildID Probe Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #222; background: #fafafa; }}
h1 {{ margin-bottom: 0.2em; }}
.meta {{ background: white; border: 1px solid #ddd; border-radius: 10px; padding: 12px 16px; margin: 16px 0 24px 0; }}
.query {{ background: white; border: 1px solid #ddd; border-radius: 12px; margin: 18px 0; padding: 14px; }}
.query-head {{ display: flex; gap: 14px; align-items: center; border-bottom: 1px solid #eee; padding-bottom: 12px; margin-bottom: 12px; }}
.query-img img, .match-card img {{ max-width: 180px; max-height: 180px; border-radius: 8px; border: 1px solid #ccc; object-fit: contain; background: #f3f3f3; }}
.matches {{ display: flex; flex-wrap: wrap; gap: 12px; }}
.match-card {{ width: 210px; border: 1px solid #ddd; border-radius: 10px; padding: 8px; background: #fcfcfc; }}
.path {{ font-size: 12px; color: #555; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<h1>HBMR / Birdbill WildID Probe Report</h1>
<div class="meta">
  <div><b>App:</b> {html.escape(APP_NAME)} {html.escape(APP_VERSION)}</div>
  <div><b>Created:</b> {html.escape(str(meta.get('created_at', '')))}</div>
  <div><b>Model:</b> {html.escape(str(meta.get('model_name', '')))}</div>
  <div><b>Device:</b> {html.escape(str(meta.get('device', '')))}</div>
  <div><b>Embeddings:</b> {html.escape(str(meta.get('embedding_count', '')))} × {html.escape(str(meta.get('embedding_dim', '')))}</div>
  <div><b>Source folder:</b> {html.escape(str(meta.get('source_folder', '')))}</div>
</div>
{''.join(rows)}
</body>
</html>
"""
    out.write_text(html_text, encoding="utf-8")
    return out


def check_python_environment() -> str:
    lines = [
        f"{APP_NAME} {APP_VERSION}",
        f"Python: {sys.executable}",
        f"Python version: {sys.version.split()[0]}",
        f"Working folder: {ROOT}",
        f"Output folder: {OUTPUT_DIR}",
    ]

    for mod in ["torch", "torchvision", "timm", "PIL"]:
        try:
            imported = __import__(mod)
            version = getattr(imported, "__version__", "installed")
            lines.append(f"{mod}: {version}")
        except Exception as exc:
            lines.append(f"{mod}: NOT FOUND ({exc})")

    try:
        import torch
        lines.append(f"torch.cuda.is_available: {torch.cuda.is_available()}")
    except Exception:
        pass

    return "\n".join(lines)


class WildIDApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("960x700")

        self.folder_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value=DEFAULT_MODEL_NAME)
        self.recursive_var = tk.BooleanVar(value=True)
        self.topk_var = tk.IntVar(value=DEFAULT_TOP_K)
        self.last_report: Optional[Path] = None

        self._build_ui()
        self.log(f"{APP_NAME} {APP_VERSION}")
        self.log("Select a crop folder, then run the MegaDescriptor nearest-neighbor probe.")
        self.log("No HBMR database will be modified.")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(outer, text="WildID Probe: MegaDescriptor nearest-neighbor test", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(outer, text="Standalone crop-folder test. Reads source crops in place; writes reports to wildid/output.")
        subtitle.pack(anchor="w", pady=(2, 12))

        folder_frame = ttk.LabelFrame(outer, text="Crop folder")
        folder_frame.pack(fill=tk.X, pady=(0, 10))
        folder_row = ttk.Frame(folder_frame, padding=8)
        folder_row.pack(fill=tk.X)
        folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(folder_row, text="Choose Folder", command=self.choose_folder).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(folder_row, text="Count Images", command=self.count_images).pack(side=tk.LEFT, padx=(8, 0))

        options = ttk.LabelFrame(outer, text="Probe settings")
        options.pack(fill=tk.X, pady=(0, 10))
        opt = ttk.Frame(options, padding=8)
        opt.pack(fill=tk.X)
        ttk.Label(opt, text="Model:").grid(row=0, column=0, sticky="w")
        ttk.Entry(opt, textvariable=self.model_var, width=56).grid(row=0, column=1, sticky="ew", padx=(8, 12))
        ttk.Label(opt, text="Top matches:").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(opt, from_=1, to=20, textvariable=self.topk_var, width=5).grid(row=0, column=3, sticky="w", padx=(8, 12))
        ttk.Checkbutton(opt, text="Recursive", variable=self.recursive_var).grid(row=0, column=4, sticky="w")
        opt.columnconfigure(1, weight=1)

        buttons = ttk.Frame(outer)
        buttons.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(buttons, text="Check Environment", command=self.check_env).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Run WildID Probe", command=self.run_probe_threaded).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Report", command=self.open_report).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Open Output Folder", command=lambda: open_folder(OUTPUT_DIR)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(buttons, text="Clear Log", command=self.clear_log).pack(side=tk.RIGHT)

        status_frame = ttk.LabelFrame(outer, text="Log")
        status_frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(status_frame, wrap=tk.WORD, height=25)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=scroll.set)

    def choose_folder(self) -> None:
        initial = self.folder_var.get().strip() or str(Path.home())
        folder = filedialog.askdirectory(title="Choose HBMR crop folder for WildID probe", initialdir=initial if Path(initial).exists() else str(Path.home()))
        if folder:
            self.folder_var.set(folder)
            self.count_images()

    def get_folder(self) -> Path:
        text = self.folder_var.get().strip().strip('"')
        if not text:
            raise RuntimeError("Choose a crop folder first.")
        folder = Path(text)
        if not folder.exists() or not folder.is_dir():
            raise RuntimeError(f"Folder does not exist:\n{folder}")
        return folder

    def count_images(self) -> None:
        try:
            folder = self.get_folder()
            images = collect_images(folder, recursive=self.recursive_var.get())
            self.log(f"Found {len(images)} image crops in: {folder}")
        except Exception as exc:
            messagebox.showerror("Count Images", str(exc))

    def check_env(self) -> None:
        self.log("")
        self.log(check_python_environment())

    def run_probe_threaded(self) -> None:
        threading.Thread(target=self.run_probe, daemon=True).start()

    def run_probe(self) -> None:
        try:
            ensure_dirs()
            folder = self.get_folder()
            model_name = self.model_var.get().strip() or DEFAULT_MODEL_NAME
            top_k = int(self.topk_var.get())
            images = collect_images(folder, recursive=self.recursive_var.get())
            if len(images) < 2:
                raise RuntimeError("Need at least 2 images for nearest-neighbor comparison.")

            self.log_threadsafe("\n============================================================")
            self.log_threadsafe("Starting WildID probe")
            self.log_threadsafe(f"Source folder: {folder}")
            self.log_threadsafe(f"Images: {len(images)}")
            self.log_threadsafe(f"Model: {model_name}")

            embeddings, meta = compute_embeddings(images, model_name, self.log_threadsafe)
            emb_path = write_embeddings_json(images, embeddings, meta)
            self.log_threadsafe(f"Wrote embeddings JSON: {emb_path}")

            matches = nearest_neighbors(images, embeddings, top_k, self.log_threadsafe)
            csv_path = write_matches_csv(matches)
            self.log_threadsafe(f"Wrote nearest-neighbor CSV: {csv_path}")

            thumbs = make_thumbnails(images, self.log_threadsafe)
            report_path = write_report_html(images, matches, meta, thumbs)
            self.last_report = report_path
            self.log_threadsafe(f"Wrote HTML report: {report_path}")
            self.log_threadsafe("WildID probe complete.")
            try:
                webbrowser.open(report_path.resolve().as_uri())
            except Exception:
                pass
        except Exception as exc:
            tb = traceback.format_exc()
            self.log_threadsafe("\nERROR:")
            self.log_threadsafe(str(exc))
            self.log_threadsafe("\n" + tb)
            messagebox.showerror("WildID Probe failed", str(exc))

    def open_report(self) -> None:
        report = self.last_report or (OUTPUT_DIR / "wildid-report.html")
        if report.exists():
            webbrowser.open(report.resolve().as_uri())
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
    WildIDApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
