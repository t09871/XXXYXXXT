# main.py | HBMR / Birdbill v2.5.10 | 2026-06-26 PDT

import configparser
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from visualid import assign_identity


APP_NAME = "HBMR / Birdbill v2.5.10"
APP_VERSION = "v2.5.10"
ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = ROOT / "settings.ini"
MEGADETECTOR_FILE = ROOT / "megadetector.py"

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}

AUTO = "auto"
PROVISIONAL = "provisional"
PROCESSED_INPUT_TAG = "-HBMR"


def load_settings():
    config = configparser.ConfigParser()

    if not SETTINGS_FILE.exists():
        raise FileNotFoundError(f"Missing settings file: {SETTINGS_FILE}")

    config.read(SETTINGS_FILE, encoding="utf-8")

    return {
        "sample_every_seconds": config.getfloat("video", "sample_every_seconds", fallback=2.0),
        "max_frames_per_video": config.getint("video", "max_frames_per_video", fallback=300),
        "jpeg_quality": config.getint("video", "jpeg_quality", fallback=95),
        "clear_old_sampled_frames": config.getboolean("video", "clear_old_sampled_frames", fallback=True),
        "tag_input_videos": config.getboolean("video", "tag_input_videos", fallback=True),
        "processed_input_tag": config.get("video", "processed_input_tag", fallback=PROCESSED_INPUT_TAG),
    }


def safe_stem(path):
    return "".join(c for c in path.stem if c not in '<>:"/\\|?*').strip()


def has_processed_input_tag(path, tag=PROCESSED_INPUT_TAG):
    return path.stem.lower().endswith(tag.lower())


def tagged_input_path(path, tag=PROCESSED_INPUT_TAG):
    if has_processed_input_tag(path, tag):
        return path

    return path.with_name(f"{path.stem}{tag}{path.suffix}")


def tag_input_video_path(video_path, tag=PROCESSED_INPUT_TAG):
    video_path = Path(video_path).resolve()

    if has_processed_input_tag(video_path, tag):
        print(f"Input already tagged with {tag}; re-processing without renaming: {video_path.name}")
        return video_path

    target = tagged_input_path(video_path, tag)

    if target.exists():
        print(f"Tagged input already exists, leaving original name in place: {target.name}")
        print("Processing original input path to avoid overwrite.")
        return video_path

    try:
        video_path.rename(target)
        print(f"Tagged input video: {video_path.name} -> {target.name}")
        return target.resolve()

    except OSError as exc:
        print(f"Input tagging warning: could not rename {video_path.name} to {target.name}")
        print(exc)
        print("Continuing with original input path.")
        return video_path


def collect_videos(paths):
    videos = []

    for raw in paths:
        path = Path(raw).resolve()

        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(path)

        elif path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append(child)

    return videos


def init_database():
    db_dir = ROOT / "output" / "database"
    db_dir.mkdir(parents=True, exist_ok=True)

    db_path = db_dir / "mr-review.db"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crop_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT NOT NULL,
            source_video TEXT NOT NULL,
            crop_path TEXT NOT NULL UNIQUE,
            review_status TEXT NOT NULL DEFAULT 'auto',
            identity TEXT DEFAULT '',
            identity_status TEXT DEFAULT 'provisional',
            training_label TEXT DEFAULT '',
            species_or_type TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            reviewed_at TEXT
        )
    """)

    existing_cols = [
        row[1]
        for row in cur.execute("PRAGMA table_info(crop_queue)").fetchall()
    ]

    required_cols = {
        "created": "TEXT",
        "source_video": "TEXT",
        "crop_path": "TEXT",
        "review_status": "TEXT DEFAULT 'auto'",
        "identity": "TEXT DEFAULT ''",
        "identity_status": "TEXT DEFAULT 'provisional'",
        "training_label": "TEXT DEFAULT ''",
        "species_or_type": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "reviewed_at": "TEXT",
        "visual_score": "REAL",
        "visual_decision": "TEXT DEFAULT ''",
        "visual_threshold": "REAL",
        "visual_matched_crop_path": "TEXT DEFAULT ''",
        "visual_model_name": "TEXT DEFAULT ''",
        "visual_model_version": "TEXT DEFAULT ''",
    }

    for col, spec in required_cols.items():
        if col not in existing_cols:
            cur.execute(f"ALTER TABLE crop_queue ADD COLUMN {col} {spec}")

    conn.commit()
    conn.close()

    return db_path


def crop_already_queued(db_path, crop):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM crop_queue
            WHERE crop_path = ?
            LIMIT 1
        """, (str(crop),))

        row = cur.fetchone()

    return row is not None


def add_crops_to_database(db_path, video_path, crops):
    added = 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for crop in crops:
        try:
            if crop_already_queued(db_path, crop):
                print(f"Already queued crop, skipping visual identity: {crop.name}")
                continue

            identity_result = assign_identity(db_path, crop)

            identity = identity_result["identity"]
            visual_score = identity_result["score"]
            visual_decision = identity_result["decision"]
            visual_threshold = identity_result["threshold"]
            visual_matched_crop_path = identity_result["matched_crop_path"]
            visual_model_name = identity_result["model_name"]
            visual_model_version = identity_result["model_version"]

            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()

                cur.execute("""
                    INSERT OR IGNORE INTO crop_queue
                    (
                        created,
                        source_video,
                        crop_path,
                        review_status,
                        identity,
                        identity_status,
                        reviewed_at,
                        visual_score,
                        visual_decision,
                        visual_threshold,
                        visual_matched_crop_path,
                        visual_model_name,
                        visual_model_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now,
                    str(video_path),
                    str(crop),
                    AUTO,
                    identity,
                    PROVISIONAL,
                    now,
                    visual_score,
                    visual_decision,
                    visual_threshold,
                    visual_matched_crop_path or "",
                    visual_model_name,
                    visual_model_version,
                ))

                if cur.rowcount > 0:
                    added += 1

                    if visual_score is None:
                        score_text = "no prior crops"
                    else:
                        score_text = f"{visual_score:.6f}"

                    print(
                        f"Visual ID crop: {identity} "
                        f"decision={visual_decision} "
                        f"score={score_text} "
                        f"threshold={visual_threshold:.2f} "
                        f"-> {crop.name}"
                    )

        except sqlite3.Error as e:
            print(f"Database warning for crop: {crop}")
            print(e)

        except Exception as e:
            print(f"Visual identity warning for crop: {crop}")
            print(e)

    return added


def build_review_page(db_path):
    review_dir = ROOT / "output" / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    html_path = review_dir / "review.html"

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id,
                created,
                source_video,
                crop_path,
                review_status,
                identity,
                identity_status,
                visual_score,
                visual_decision,
                visual_threshold
            FROM crop_queue
            ORDER BY id DESC
        """)

        rows = cur.fetchall()

    cards = []

    for row in rows:
        (
            crop_id,
            created,
            source_video,
            crop_path,
            review_status,
            identity,
            identity_status,
            visual_score,
            visual_decision,
            visual_threshold,
        ) = row

        crop = Path(crop_path)

        score_text = "None"

        if visual_score is not None:
            score_text = f"{visual_score:.6f}"

        cards.append(f"""
        <div class="card">
            <img src="{crop.as_uri()}" alt="{identity}">
            <div class="meta">
                <b>ID:</b> {crop_id}<br>
                <b>Identity:</b> {identity}<br>
                <b>Identity status:</b> {identity_status}<br>
                <b>Review status:</b> {review_status}<br>
                <b>Visual decision:</b> {visual_decision}<br>
                <b>Visual score:</b> {score_text}<br>
                <b>Visual threshold:</b> {visual_threshold}<br>
                <b>Created:</b> {created}<br>
                <b>Source:</b> {source_video}<br>
                <b>Path:</b> {crop_path}
            </div>
        </div>
        """)

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>HummingbirdMindreader Profiles | HBMR {APP_VERSION}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 20px;
    background: #f5f5f5;
}}

h1 {{
    margin-bottom: 5px;
}}

.summary {{
    margin-bottom: 20px;
}}

.grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
}}

.card {{
    background: white;
    border: 1px solid #ccc;
    padding: 10px;
}}

.card img {{
    width: 100%;
    height: auto;
    display: block;
    margin-bottom: 8px;
}}

.meta {{
    font-size: 12px;
    word-break: break-word;
}}
</style>
</head>
<body>

<h1>HummingbirdMindreader Profiles</h1>

<div class="summary">
HBMR version: {APP_VERSION}<br>
Visual identity mode: enabled<br>
DINOv2 threshold: 0.79<br>
Human prompts: disabled<br>
Total profile pictures: {len(rows)}<br>
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
</div>

<div class="grid">
{''.join(cards)}
</div>

</body>
</html>
"""

    html_path.write_text(html, encoding="utf-8")

    return html_path, len(rows)


def fit_image_into_tile(image, tile_w, tile_h):
    h, w = image.shape[:2]

    if w <= 0 or h <= 0:
        return np.zeros((tile_h, tile_w, 3), dtype=np.uint8)

    scale = min(tile_w / w, tile_h / h)

    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))

    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

    tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)

    x = (tile_w - new_w) // 2
    y = (tile_h - new_h) // 2

    tile[y:y + new_h, x:x + new_w] = resized

    return tile


def build_review_contact_sheet(db_path):
    review_dir = ROOT / "output" / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    sheet_path = review_dir / "current-review.jpg"

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT id, identity, crop_path
            FROM crop_queue
            ORDER BY id DESC
            LIMIT 80
        """)

        rows = list(reversed(cur.fetchall()))

    if not rows:
        if sheet_path.exists():
            sheet_path.unlink()

        return sheet_path, 0

    cols = 4
    tile_w = 300
    tile_h = 300
    label_h = 34
    margin = 16

    cell_w = tile_w + margin
    cell_h = tile_h + label_h + margin

    sheet_cols = min(cols, len(rows))
    sheet_rows = (len(rows) + sheet_cols - 1) // sheet_cols

    sheet_w = sheet_cols * cell_w + margin
    sheet_h = sheet_rows * cell_h + margin

    sheet = np.zeros((sheet_h, sheet_w, 3), dtype=np.uint8)

    for idx, row in enumerate(rows, start=1):
        crop_id, identity, crop_path = row

        path = Path(crop_path)

        image = cv2.imread(str(path))

        if image is None:
            image = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)

            cv2.putText(
                image,
                "missing image",
                (30, tile_h // 2),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

        tile = fit_image_into_tile(image, tile_w, tile_h)

        zero_idx = idx - 1

        row_i = zero_idx // sheet_cols
        col_i = zero_idx % sheet_cols

        x = margin + col_i * cell_w
        y = margin + row_i * cell_h

        sheet[y:y + tile_h, x:x + tile_w] = tile

        label = identity if identity else f"Crop {crop_id}"

        cv2.putText(
            sheet,
            label,
            (x, y + tile_h + 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )

    cv2.imwrite(str(sheet_path), sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

    return sheet_path, len(rows)


def sample_video(video_path, settings):
    stem = safe_stem(video_path)

    output_dir = ROOT / "output" / "frames" / stem

    if settings["clear_old_sampled_frames"] and output_dir.exists():
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        print(f"Could not open video: {video_path}")
        return output_dir, 0, 0.0, 0, 0

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if not fps or fps <= 0:
        fps = 30.0

    step_frames = max(1, int(round(fps * settings["sample_every_seconds"])))

    max_frames = settings["max_frames_per_video"]
    jpeg_quality = settings["jpeg_quality"]

    print()
    print("=" * 72)
    print(f"Sampling video: {video_path}")
    print(f"FPS: {fps:.2f}")
    print(f"Total frames: {total_frames}")
    print(f"Sample every seconds: {settings['sample_every_seconds']}")
    print(f"Frame step: {step_frames}")
    print(f"Frame output: {output_dir}")

    saved = 0
    frame_index = 0

    while True:
        if saved >= max_frames:
            print(f"Frame sampling stopped at max_frames_per_video={max_frames}")
            break

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

        ok, frame = cap.read()

        if not ok:
            break

        timestamp_seconds = frame_index / fps

        out_name = f"{stem}-frame-{frame_index:08d}-t{timestamp_seconds:07.2f}.jpg"
        out_path = output_dir / out_name

        cv2.imwrite(
            str(out_path),
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
        )

        saved += 1
        frame_index += step_frames

    cap.release()

    print(f"Frames exported: {saved}")

    return output_dir, saved, fps, total_frames, step_frames


def run_megadetector_on_folder(frame_folder):
    print()
    print("Running MegaDetector crop exporter on sampled frames...")
    print(f"Frame folder: {frame_folder}")

    result = subprocess.run(
        [sys.executable, str(MEGADETECTOR_FILE), str(frame_folder)],
        cwd=str(ROOT),
        input="\n",
        text=True,
    )

    return result.returncode == 0


def get_recent_crops(video_stem, run_started_at):
    crop_dir = ROOT / "output" / "crops"

    if not crop_dir.exists():
        return []

    crops = []

    for path in crop_dir.glob(f"{video_stem}-frame-*-animal-*.png"):
        try:
            if path.stat().st_mtime >= run_started_at:
                crops.append(path)

        except OSError:
            pass

    return sorted(crops)


def write_video_summary(
    video_path,
    frame_count,
    crop_count,
    fps,
    total_frames,
    step_frames,
    db_path,
    review_html,
    review_sheet,
):
    reports_dir = ROOT / "output" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    stem = safe_stem(video_path)

    report_path = reports_dir / f"{stem}-summary.txt"

    lines = [
        "HBMR / Birdbill v2.5.10 summary",
        f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Visual identity mode: enabled",
        "Visual model: facebook/dinov2-small",
        "Visual threshold: 0.79",
        "Human prompts: disabled",
        f"Input tag: {PROCESSED_INPUT_TAG}",
        "",
        f"Input video: {video_path}",
        f"FPS: {fps:.2f}",
        f"Total frames: {total_frames}",
        f"Frame step: {step_frames}",
        f"Sampled frames exported: {frame_count}",
        f"New animal crops added: {crop_count}",
        "",
        f"Frame folder: {ROOT / 'output' / 'frames' / stem}",
        f"Crop folder: {ROOT / 'output' / 'crops'}",
        f"Internal database: {db_path}",
        f"Review page: {review_html}",
        f"Review contact sheet: {review_sheet}",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")

    return report_path


def main():
    print(APP_NAME)
    print("Video sampler -> MegaDetector animal crops -> DINOv2 provisional identities")
    print("Human prompts disabled.")
    print(f"Project root: {ROOT}")

    if len(sys.argv) < 2:
        print()
        print("Drag video files or a folder onto HBMR.bat")
        return

    settings = load_settings()

    videos = collect_videos(sys.argv[1:])

    db_path = init_database()

    print()
    print(f"Videos queued: {len(videos)}")

    if not videos:
        print("No supported videos found.")
        return

    total_frames_exported = 0
    total_new_crops = 0
    successful_videos = 0

    last_report = None
    last_review_sheet = None

    for i, video in enumerate(videos, start=1):
        print()
        print("=" * 72)
        print(f"Video {i} of {len(videos)}")
        print(f"Input: {video}")

        if settings.get("tag_input_videos", True):
            video = tag_input_video_path(video, str(settings.get("processed_input_tag") or PROCESSED_INPUT_TAG))

        stem = safe_stem(video)

        frame_folder, frame_count, fps, total_video_frames, step_frames = sample_video(video, settings)

        total_frames_exported += frame_count

        if frame_count <= 0:
            print("No frames exported; skipping detector.")
            continue

        run_started_at = time.time() - 1.0

        ok = run_megadetector_on_folder(frame_folder)

        recent_crops = get_recent_crops(stem, run_started_at)

        new_records = add_crops_to_database(db_path, video, recent_crops)

        review_html, total_queued = build_review_page(db_path)

        review_sheet, sheet_count = build_review_contact_sheet(db_path)

        last_review_sheet = review_sheet

        last_report = write_video_summary(
            video,
            frame_count,
            new_records,
            fps,
            total_video_frames,
            step_frames,
            db_path,
            review_html,
            review_sheet,
        )

        total_new_crops += new_records

        print()
        print("Video summary:")
        print(f"Sampled frames: {frame_count}")
        print(f"New crops added: {new_records}")
        print(f"Total profile pictures: {total_queued}")
        print(f"Review page: {review_html}")
        print(f"Review contact sheet: {review_sheet} ({sheet_count} latest profile pictures)")
        print(f"Report: {last_report}")

        if ok:
            successful_videos += 1

    print()
    print("=" * 72)
    print("v2.5.10 complete.")
    print(f"Videos processed: {successful_videos} of {len(videos)}")
    print(f"Sampled frames exported: {total_frames_exported}")
    print(f"New profile pictures added: {total_new_crops}")
    print(f"Internal database: {db_path}")
    print(f"Review page: {ROOT / 'output' / 'review' / 'review.html'}")

    if last_review_sheet:
        print(f"Review contact sheet: {last_review_sheet}")

    print(f"Reports folder: {ROOT / 'output' / 'reports'}")
    print()


if __name__ == "__main__":
    main()