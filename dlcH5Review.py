# dlcH5Review.py | HBMR / Birdbill DLC H5 review converter v0.1 | 2026-07-02 PDT
# Converts the newest DLC prediction .h5 in a crop folder into:
# 1) flat CSV
# 2) overlay images with bill_base / bill_tip points
# 3) contact sheets for fast visual review
#
# Default input folder:
# D:\HBMR\output\crops-DLC test1

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


DEFAULT_INPUT_DIR = r"D:\HBMR\output\crops-DLC test1"
DEFAULT_OUTPUT_SUFFIX = "-review"
DEFAULT_PCUTOFF = 0.60
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def find_newest_h5(input_dir: Path) -> Path:
    h5_files = sorted(input_dir.glob("*.h5"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not h5_files:
        raise FileNotFoundError(f"No .h5 files found in: {input_dir}")
    return h5_files[0]


def read_h5_any_key(h5_path: Path) -> pd.DataFrame:
    try:
        return pd.read_hdf(h5_path)
    except (ValueError, KeyError):
        with pd.HDFStore(h5_path, mode="r") as store:
            keys = store.keys()
            if not keys:
                raise ValueError(f"No readable keys found in H5 file: {h5_path}")
            return store[keys[0]]


def list_images(input_dir: Path) -> list[Path]:
    images = [
        p for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(images, key=lambda p: p.name.lower())


def resolve_image_for_row(index_value: Any, row_number: int, images_by_name: dict[str, Path], images_sorted: list[Path]) -> Path | None:
    text = str(index_value)

    candidate = Path(text)
    if candidate.exists():
        return candidate

    name = candidate.name
    if name in images_by_name:
        return images_by_name[name]

    if text in images_by_name:
        return images_by_name[text]

    if row_number < len(images_sorted):
        return images_sorted[row_number]

    return None


def get_font(size: int = 14) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def normalize_column_tuple(col: Any) -> tuple[str, ...]:
    if isinstance(col, tuple):
        return tuple(str(x) for x in col)
    return (str(col),)


def find_bodypart_columns(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """
    Returns:
      {
        "bill_base": {"x": col, "y": col, "likelihood": col},
        "bill_tip": {"x": col, "y": col, "likelihood": col}
      }

    Handles common DLC layouts:
      scorer/bodypart/coord
      scorer/individual/bodypart/coord
    """
    found: dict[str, dict[str, Any]] = {}

    for col in df.columns:
        parts = normalize_column_tuple(col)
        coord = parts[-1].lower()

        if coord not in {"x", "y", "likelihood"}:
            continue

        if len(parts) < 2:
            continue

        bodypart = parts[-2]
        bodypart_key = bodypart.lower()

        if bodypart_key not in found:
            found[bodypart_key] = {}

        found[bodypart_key][coord] = col

    return found


def choose_bodypart(found: dict[str, dict[str, Any]], wanted: str) -> str:
    wanted_lower = wanted.lower()

    if wanted_lower in found:
        return wanted_lower

    for key in found:
        if wanted_lower in key:
            return key

    if wanted_lower == "bill_base":
        for key in found:
            if "base" in key:
                return key

    if wanted_lower == "bill_tip":
        for key in found:
            if "tip" in key:
                return key

    raise KeyError(f"Could not find bodypart matching {wanted!r}. Found bodyparts: {sorted(found.keys())}")


def safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def draw_point(draw: ImageDraw.ImageDraw, x: float, y: float, label: str, color: tuple[int, int, int]) -> None:
    r = 5
    draw.ellipse((x - r, y - r, x + r, y + r), outline=color, width=3)
    draw.text((x + 7, y - 7), label, fill=color, font=get_font(14))


def make_overlay(
    image_path: Path,
    output_path: Path,
    base_x: float | None,
    base_y: float | None,
    base_l: float | None,
    tip_x: float | None,
    tip_y: float | None,
    tip_l: float | None,
    pcutoff: float,
) -> None:
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    base_ok = base_x is not None and base_y is not None and (base_l is None or base_l >= pcutoff)
    tip_ok = tip_x is not None and tip_y is not None and (tip_l is None or tip_l >= pcutoff)

    base_color = (0, 255, 0) if base_ok else (255, 180, 0)
    tip_color = (255, 0, 0) if tip_ok else (255, 180, 0)

    if base_x is not None and base_y is not None:
        draw_point(draw, base_x, base_y, "base", base_color)

    if tip_x is not None and tip_y is not None:
        draw_point(draw, tip_x, tip_y, "tip", tip_color)

    if base_x is not None and base_y is not None and tip_x is not None and tip_y is not None:
        draw.line((base_x, base_y, tip_x, tip_y), fill=(0, 200, 255), width=3)

    label = f"base_l={base_l:.3f} tip_l={tip_l:.3f}" if base_l is not None and tip_l is not None else "likelihood unavailable"
    draw.rectangle((0, 0, min(img.width, 520), 24), fill=(0, 0, 0))
    draw.text((6, 4), label, fill=(255, 255, 255), font=get_font(14))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, quality=92)


def make_contact_sheets(overlay_paths: list[Path], output_dir: Path, cols: int = 4, thumb_w: int = 260, label_h: int = 28) -> None:
    if not overlay_paths:
        return

    font = get_font(12)
    rows = 5
    per_sheet = cols * rows

    for sheet_index in range(math.ceil(len(overlay_paths) / per_sheet)):
        chunk = overlay_paths[sheet_index * per_sheet:(sheet_index + 1) * per_sheet]
        thumbs: list[tuple[Image.Image, str]] = []

        max_cell_h = 0
        for path in chunk:
            img = Image.open(path).convert("RGB")
            ratio = thumb_w / img.width
            thumb_h = max(1, int(img.height * ratio))
            img = img.resize((thumb_w, thumb_h))
            max_cell_h = max(max_cell_h, thumb_h + label_h)
            thumbs.append((img, path.name))

        sheet_w = cols * thumb_w
        sheet_h = rows * max_cell_h
        sheet = Image.new("RGB", (sheet_w, sheet_h), (245, 245, 245))
        draw = ImageDraw.Draw(sheet)

        for i, (thumb, name) in enumerate(thumbs):
            col = i % cols
            row = i // cols
            x = col * thumb_w
            y = row * max_cell_h

            sheet.paste(thumb, (x, y))
            short_name = name[:42]
            draw.rectangle((x, y + thumb.height, x + thumb_w, y + thumb.height + label_h), fill=(230, 230, 230))
            draw.text((x + 4, y + thumb.height + 6), short_name, fill=(0, 0, 0), font=font)

        out_path = output_dir / f"contactsheet-{sheet_index + 1:03d}.jpg"
        sheet.save(out_path, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert DLC prediction H5 into Birdbill-friendly review outputs.")
    parser.add_argument("--input", default=DEFAULT_INPUT_DIR, help="Folder containing crop images and DLC .h5 output.")
    parser.add_argument("--h5", default="", help="Optional exact DLC .h5 path. If omitted, newest .h5 in input folder is used.")
    parser.add_argument("--pcutoff", type=float, default=DEFAULT_PCUTOFF, help="Likelihood cutoff for visual warning coloring.")
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input folder does not exist: {input_dir}")

    h5_path = Path(args.h5) if args.h5 else find_newest_h5(input_dir)
    if not h5_path.exists():
        raise FileNotFoundError(f"H5 file does not exist: {h5_path}")

    output_dir = Path(str(input_dir) + DEFAULT_OUTPUT_SUFFIX)
    overlay_dir = output_dir / "overlays"
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

    print(f"Input folder: {input_dir}")
    print(f"H5 file:      {h5_path}")
    print(f"Output dir:   {output_dir}")

    df = read_h5_any_key(h5_path)
    print(f"Rows loaded:  {len(df)}")
    print(f"Columns:      {len(df.columns)}")

    found = find_bodypart_columns(df)
    print(f"Bodyparts:    {sorted(found.keys())}")

    base_key = choose_bodypart(found, "bill_base")
    tip_key = choose_bodypart(found, "bill_tip")

    images_sorted = list_images(input_dir)
    images_by_name = {p.name: p for p in images_sorted}

    rows_out: list[dict[str, Any]] = []
    overlay_paths: list[Path] = []

    for row_number, (idx, row) in enumerate(df.iterrows()):
        image_path = resolve_image_for_row(idx, row_number, images_by_name, images_sorted)

        base_cols = found[base_key]
        tip_cols = found[tip_key]

        base_x = safe_float(row.get(base_cols.get("x")))
        base_y = safe_float(row.get(base_cols.get("y")))
        base_l = safe_float(row.get(base_cols.get("likelihood")))
        tip_x = safe_float(row.get(tip_cols.get("x")))
        tip_y = safe_float(row.get(tip_cols.get("y")))
        tip_l = safe_float(row.get(tip_cols.get("likelihood")))

        bill_length_px = None
        if base_x is not None and base_y is not None and tip_x is not None and tip_y is not None:
            bill_length_px = math.hypot(tip_x - base_x, tip_y - base_y)

        min_likelihood = None
        likelihoods = [v for v in [base_l, tip_l] if v is not None]
        if likelihoods:
            min_likelihood = min(likelihoods)

        review_status = "usable_candidate" if min_likelihood is not None and min_likelihood >= args.pcutoff else "low_confidence_review"

        overlay_path = None
        if image_path is not None and image_path.exists():
            overlay_path = overlay_dir / f"{image_path.stem}-dlc-overlay.jpg"
            make_overlay(
                image_path,
                overlay_path,
                base_x,
                base_y,
                base_l,
                tip_x,
                tip_y,
                tip_l,
                args.pcutoff,
            )
            overlay_paths.append(overlay_path)

        rows_out.append({
            "row_number": row_number,
            "dlc_index": str(idx),
            "image_path": str(image_path) if image_path else "",
            "image_name": image_path.name if image_path else "",
            "bill_base_x": base_x,
            "bill_base_y": base_y,
            "bill_base_likelihood": base_l,
            "bill_tip_x": tip_x,
            "bill_tip_y": tip_y,
            "bill_tip_likelihood": tip_l,
            "bill_length_px": bill_length_px,
            "min_likelihood": min_likelihood,
            "pcutoff": args.pcutoff,
            "review_status": review_status,
            "overlay_path": str(overlay_path) if overlay_path else "",
        })

    flat_csv = output_dir / "dlc-predictions-flat.csv"
    pd.DataFrame(rows_out).to_csv(flat_csv, index=False)

    make_contact_sheets(overlay_paths, output_dir)

    print("")
    print("Done.")
    print(f"Flat CSV:      {flat_csv}")
    print(f"Overlays:      {overlay_dir}")
    print(f"Contact sheets:{output_dir}")
    print("")
    print("Review categories:")
    print("  usable_candidate       = both likelihoods >= pcutoff")
    print("  low_confidence_review  = one or both points below pcutoff")


if __name__ == "__main__":
    main()