# dinosim.py | HBMR DINOv2 batch similarity probe v0.2.0 | 2026-06-18 PDT

import csv
import html
import itertools
import shutil
import sys
from datetime import datetime
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel


MODEL_NAME = "facebook/dinov2-small"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def is_image(path):
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def load_embedding(processor, model, image_path):
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")

    with torch.no_grad():
        outputs = model(**inputs)

    embedding = outputs.last_hidden_state.mean(dim=1)
    embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

    return embedding


def cosine_similarity(a, b):
    return torch.nn.functional.cosine_similarity(a, b).item()


def safe_copy_name(index, source_path):
    clean_name = source_path.name.replace(" ", "-")
    return f"{index:04d}-{clean_name}"


def write_report(report_path, rows):
    with report_path.open("w", encoding="utf-8") as f:
        f.write("""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>HBMR DINOv2 Similarity Report</title>
<style>
body { font-family: Arial, sans-serif; margin: 28px; background: #f7f3ec; color: #222; }
.card { background: white; border-radius: 14px; padding: 16px; margin: 16px 0; box-shadow: 0 2px 10px rgba(0,0,0,0.12); }
.pair { display: grid; grid-template-columns: 220px 220px 1fr; gap: 18px; align-items: start; }
img { width: 220px; height: 220px; object-fit: contain; background: #eee; border-radius: 12px; }
.score { font-size: 2em; font-weight: bold; }
.name { font-size: 0.9em; color: #555; overflow-wrap: anywhere; }
</style>
</head>
<body>
<h1>HBMR DINOv2 Similarity Report</h1>
""")

        for row in rows:
            f.write('<div class="card"><div class="pair">\n')
            f.write(f'<div><img src="{html.escape(row["copy1"])}"><div class="name">{html.escape(row["image1"])}</div></div>\n')
            f.write(f'<div><img src="{html.escape(row["copy2"])}"><div class="name">{html.escape(row["image2"])}</div></div>\n')
            f.write(f'<div><div class="score">{row["score"]:.6f}</div><p>Cosine similarity</p></div>\n')
            f.write("</div></div>\n")

        f.write("</body>\n</html>\n")


def main():
    input_paths = [Path(arg) for arg in sys.argv[1:]]
    image_paths = [p for p in input_paths if is_image(p)]

    if len(image_paths) < 2:
        print("HBMR DINOv2 batch similarity probe v0.2.0")
        print()
        print("Drag two or more crop images onto dinosim.bat.")
        return 1

    pair_count = len(image_paths) * (len(image_paths) - 1) // 2

    print("HBMR DINOv2 batch similarity probe v0.2.0")
    print(f"Model: {MODEL_NAME}")
    print(f"Images: {len(image_paths)}")
    print(f"Pairs: {pair_count}")
    print()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path("output") / "dinosim" / timestamp
    image_dir = output_dir / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    print("Copying report images...")
    copied = {}
    for index, image_path in enumerate(image_paths, start=1):
        copy_name = safe_copy_name(index, image_path)
        copy_path = image_dir / copy_name
        shutil.copy2(image_path, copy_path)
        copied[image_path] = Path("images") / copy_name

    print("Loading model...")
    processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME)
    model.eval()

    print("Computing embeddings...")
    embeddings = {}
    for index, image_path in enumerate(image_paths, start=1):
        print(f"{index}/{len(image_paths)} {image_path.name}")
        embeddings[image_path] = load_embedding(processor, model, image_path)

    print()
    print("Computing pair scores...")

    rows = []
    for image1, image2 in itertools.combinations(image_paths, 2):
        score = cosine_similarity(embeddings[image1], embeddings[image2])
        rows.append({
            "image1": image1.name,
            "image2": image2.name,
            "path1": str(image1),
            "path2": str(image2),
            "copy1": copied[image1].as_posix(),
            "copy2": copied[image2].as_posix(),
            "score": score,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)

    csv_path = output_dir / "dinosim-scores.csv"
    html_path = output_dir / "dinosim-report.html"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["score", "image1", "image2", "path1", "path2"])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "score": f'{row["score"]:.6f}',
                "image1": row["image1"],
                "image2": row["image2"],
                "path1": row["path1"],
                "path2": row["path2"],
            })

    write_report(html_path, rows)

    print()
    print("Done.")
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())