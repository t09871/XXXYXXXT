# billtipToDLC.py | HBMR / Birdbill v0.1.0 | 2026-06-30 PDT | Birdbill JSON to DeepLabCut labeled-data converter

"""
Convert Birdbill bill-base / bill-tip premium JSON into DeepLabCut labeled-data files.

Purpose:
    Birdbill JSON remains the canonical annotation/provenance export.
    DeepLabCut receives generated training artifacts only.

Default Birdbill source folder:
    D:\\HBMR\\output\\billtip-trainer

Default DLC config path:
    D:\\HBMR\\dlc\\billtip\\billtip-HB-2026-06-30\\config.yaml

Generated DLC output folder:
    <DLC project root>\\labeled-data\\billtip

Generated files:
    CollectedData_Birdbill.csv
    CollectedData_Birdbill.h5
    birdbill-dlc-conversion-report.txt

Run with DLC env Python, for example:
    C:\\Users\\autom\\miniconda3\\envs\\DEEPLABCUT\\python.exe D:\\HBMR\\billtipToDLC.py

Optional examples:
    C:\\Users\\autom\\miniconda3\\envs\\DEEPLABCUT\\python.exe D:\\HBMR\\billtipToDLC.py --limit 10
    C:\\Users\\autom\\miniconda3\\envs\\DEEPLABCUT\\python.exe D:\\HBMR\\billtipToDLC.py --json D:\\HBMR\\output\\billtip-trainer\\billbase-billtip-training-v062-premium.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback handled below
    yaml = None


APP_NAME = "HBMR / Birdbill JSON to DLC Converter"
APP_VERSION = "v0.1.0"

DEFAULT_SOURCE_DIR = Path(r"D:\HBMR\output\billtip-trainer")
DEFAULT_CONFIG_PATH = Path(r"D:\HBMR\dlc\billtip\billtip-HB-2026-06-30\config.yaml")
DEFAULT_SCORER = "Birdbill"
DEFAULT_DATASET_NAME = "billtip"
BODY_PARTS = ["bill_base", "bill_tip"]
COORDS = ["x", "y"]
HDF_KEY = "df_with_missing"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass(frozen=True)
class ExportRow:
    source_image: Path
    output_filename: str
    relative_index: str
    bill_base_x: float
    bill_base_y: float
    bill_tip_x: float
    bill_tip_y: float
    source_row_index: int | None
    image_index: int | None
    sequence_id: str


def info(message: str) -> None:
    print(f"[billtipToDLC] {message}")


def fail(message: str, exit_code: int = 1) -> None:
    print(f"[billtipToDLC ERROR] {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Path to Birdbill premium JSON. If omitted, newest *premium*.json in --source-dir is used.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Folder containing Birdbill training JSON exports. Default: {DEFAULT_SOURCE_DIR}",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"DLC config.yaml path. Default: {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument(
        "--scorer",
        default=DEFAULT_SCORER,
        help=f"DLC scorer name used in CollectedData files. Default: {DEFAULT_SCORER}",
    )
    parser.add_argument(
        "--dataset-name",
        default=DEFAULT_DATASET_NAME,
        help=f"DLC labeled-data folder name. Default: {DEFAULT_DATASET_NAME}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional test limit. Use 10 for a small smoke-test conversion. Default 0 means all rows.",
    )
    parser.add_argument(
        "--no-copy",
        action="store_true",
        help="Do not copy image files; write labels for expected target filenames only. Not recommended for DLC training.",
    )
    parser.add_argument(
        "--overwrite-images",
        action="store_true",
        help="Overwrite already-copied images in DLC labeled-data folder.",
    )
    parser.add_argument(
        "--no-config-patch",
        action="store_true",
        help="Do not patch DLC config.yaml bodyparts/scorer fields.",
    )
    return parser.parse_args()


def find_latest_json(source_dir: Path) -> Path:
    if not source_dir.exists():
        fail(f"Source folder does not exist: {source_dir}")

    candidates = sorted(
        [p for p in source_dir.glob("*.json") if "premium" in p.name.lower()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        fail(f"No premium JSON files found in: {source_dir}")
    return candidates[0]


def load_json(json_path: Path) -> dict[str, Any]:
    if not json_path.exists():
        fail(f"JSON file does not exist: {json_path}")
    try:
        with json_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        fail(f"Could not read JSON: {json_path}\n{exc}")

    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        fail("JSON does not look like a Birdbill training export with a top-level rows list.")
    return data


def safe_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key, -1)
    try:
        number = float(value)
    except Exception:
        return None
    if number < 0:
        return None
    return number


def safe_filename(path: Path, row_number: int) -> str:
    """Avoid collisions while preserving the source crop filename as much as possible."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip(".-") or "crop"
    suffix = path.suffix.lower() if path.suffix.lower() in IMAGE_EXTENSIONS else ".png"
    return f"{row_number:05d}-{stem}{suffix}"


def collect_export_rows(data: dict[str, Any], dataset_name: str, limit: int) -> tuple[list[ExportRow], list[str]]:
    rows: list[ExportRow] = []
    skipped: list[str] = []

    for idx, row in enumerate(data.get("rows", [])):
        if not isinstance(row, dict):
            skipped.append(f"row {idx}: not an object")
            continue

        if row.get("label") != "valid_full_bill_side_view":
            skipped.append(f"row {idx}: label={row.get('label')!r}")
            continue

        if not bool(row.get("is_premium_training_row", False)):
            skipped.append(f"row {idx}: is_premium_training_row is not true")
            continue

        image_path_raw = str(row.get("image_path", "")).strip()
        if not image_path_raw:
            skipped.append(f"row {idx}: missing image_path")
            continue

        base_x = safe_float(row, "corrected_bill_base_x")
        base_y = safe_float(row, "corrected_bill_base_y")
        tip_x = safe_float(row, "clicked_tip_x")
        tip_y = safe_float(row, "clicked_tip_y")
        if None in (base_x, base_y, tip_x, tip_y):
            skipped.append(f"row {idx}: missing corrected base/tip coordinates")
            continue

        source_image = Path(image_path_raw)
        output_filename = safe_filename(source_image, len(rows) + 1)
        relative_index = f"labeled-data/{dataset_name}/{output_filename}"

        rows.append(
            ExportRow(
                source_image=source_image,
                output_filename=output_filename,
                relative_index=relative_index,
                bill_base_x=float(base_x),
                bill_base_y=float(base_y),
                bill_tip_x=float(tip_x),
                bill_tip_y=float(tip_y),
                source_row_index=row.get("source_row_index"),
                image_index=row.get("image_index"),
                sequence_id=str(row.get("sequence_id", "")),
            )
        )

        if limit and len(rows) >= limit:
            break

    return rows, skipped


def project_root_from_config(config_path: Path) -> Path:
    if not config_path.exists():
        fail(f"DLC config.yaml does not exist: {config_path}")
    return config_path.parent


def copy_images(rows: list[ExportRow], output_dir: Path, overwrite: bool) -> tuple[int, list[str]]:
    copied = 0
    missing: list[str] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        target = output_dir / row.output_filename
        if not row.source_image.exists():
            missing.append(str(row.source_image))
            continue
        if target.exists() and not overwrite:
            continue
        try:
            shutil.copy2(row.source_image, target)
            copied += 1
        except Exception as exc:
            missing.append(f"{row.source_image} -> {target}: {exc}")
    return copied, missing


def build_dataframe(rows: list[ExportRow], scorer: str) -> pd.DataFrame:
    columns = pd.MultiIndex.from_product(
        [[scorer], BODY_PARTS, COORDS],
        names=["scorer", "bodyparts", "coords"],
    )

    data: list[list[float]] = []
    index: list[str] = []
    for row in rows:
        index.append(row.relative_index)
        data.append([row.bill_base_x, row.bill_base_y, row.bill_tip_x, row.bill_tip_y])

    df = pd.DataFrame(data, index=index, columns=columns)
    df.index.name = None
    return df


def write_labels(df: pd.DataFrame, output_dir: Path, scorer: str) -> tuple[Path, Path]:
    csv_path = output_dir / f"CollectedData_{scorer}.csv"
    h5_path = output_dir / f"CollectedData_{scorer}.h5"

    df.to_csv(csv_path)
    df.to_hdf(h5_path, key=HDF_KEY, mode="w")
    return csv_path, h5_path


def patch_config(config_path: Path, scorer: str, dataset_name: str) -> str:
    """Patch the small config fields needed for this DLC project.

    Uses PyYAML if available. If not available, applies a conservative text patch for bodyparts/scorer only.
    """
    original = config_path.read_text(encoding="utf-8")
    backup_path = config_path.with_suffix(config_path.suffix + ".birdbill-backup")
    if not backup_path.exists():
        backup_path.write_text(original, encoding="utf-8")

    if yaml is not None:
        try:
            config_data = yaml.safe_load(original) or {}
            if not isinstance(config_data, dict):
                raise ValueError("config.yaml root is not a dictionary")

            config_data["scorer"] = scorer
            config_data["bodyparts"] = BODY_PARTS
            config_data["multianimalproject"] = False
            config_data["individuals"] = ["individual1"]
            config_data.setdefault("TrainingFraction", [0.95])
            config_data.setdefault("default_net_type", "resnet_50")

            # DLC-created projects usually already manage video_sets. Leave existing values alone.
            # We only record a comment-like custom field so future debugging can see the bridge source.
            config_data["birdbill_labeled_data_folder"] = f"labeled-data/{dataset_name}"

            rendered = yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True)
            config_path.write_text(rendered, encoding="utf-8")
            return f"patched with PyYAML; backup={backup_path}"
        except Exception as exc:
            info(f"PyYAML config patch failed, falling back to text patch: {exc}")

    patched = re.sub(
        r"(?ms)^bodyparts:\s*\n(?:^\s*-.*\n?)+",
        "bodyparts:\n- bill_base\n- bill_tip\n",
        original,
    )
    patched = re.sub(r"(?m)^scorer:.*$", f"scorer: {scorer}", patched)
    if patched == original:
        patched += f"\n# Birdbill DLC bridge fields\nscorer: {scorer}\nbodyparts:\n- bill_base\n- bill_tip\n"
    config_path.write_text(patched, encoding="utf-8")
    return f"patched with text fallback; backup={backup_path}"


def write_report(
    report_path: Path,
    json_path: Path,
    config_path: Path,
    output_dir: Path,
    rows: list[ExportRow],
    skipped: list[str],
    missing_images: list[str],
    csv_path: Path,
    h5_path: Path,
    config_note: str,
) -> None:
    lines = [
        f"{APP_NAME} {APP_VERSION}",
        f"created_at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"json_path: {json_path}",
        f"config_path: {config_path}",
        f"output_dir: {output_dir}",
        f"csv_path: {csv_path}",
        f"h5_path: {h5_path}",
        f"config_patch: {config_note}",
        "",
        f"exported_rows: {len(rows)}",
        f"skipped_rows: {len(skipped)}",
        f"missing_or_failed_images: {len(missing_images)}",
        "",
        "bodyparts:",
        "- bill_base",
        "- bill_tip",
        "",
        "Next likely DLC command, using the DLC environment Python:",
        rf"C:\Users\autom\miniconda3\envs\DEEPLABCUT\python.exe -c \"import deeplabcut; deeplabcut.create_training_dataset(r'{config_path}', net_type='resnet_50', augmenter_type='imgaug')\"",
        "",
    ]

    if missing_images:
        lines.append("Missing/failed images:")
        lines.extend(missing_images[:100])
        if len(missing_images) > 100:
            lines.append(f"... {len(missing_images) - 100} more omitted")
        lines.append("")

    if skipped:
        lines.append("Skipped rows sample:")
        lines.extend(skipped[:100])
        if len(skipped) > 100:
            lines.append(f"... {len(skipped) - 100} more omitted")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()

    json_path = args.json if args.json else find_latest_json(args.source_dir)
    config_path = args.config
    project_root = project_root_from_config(config_path)
    labeled_dir = project_root / "labeled-data" / args.dataset_name

    info(f"{APP_NAME} {APP_VERSION}")
    info(f"JSON: {json_path}")
    info(f"DLC config: {config_path}")
    info(f"DLC labeled-data folder: {labeled_dir}")

    data = load_json(json_path)
    rows, skipped = collect_export_rows(data, args.dataset_name, args.limit)
    if not rows:
        fail("No usable premium rows found for export.")

    copied = 0
    missing_images: list[str] = []
    if not args.no_copy:
        copied, missing_images = copy_images(rows, labeled_dir, args.overwrite_images)
        info(f"Copied/updated images: {copied}")
        if missing_images:
            info(f"Missing/failed images: {len(missing_images)}")

    df = build_dataframe(rows, args.scorer)
    labeled_dir.mkdir(parents=True, exist_ok=True)
    csv_path, h5_path = write_labels(df, labeled_dir, args.scorer)
    info(f"Wrote CSV: {csv_path}")
    info(f"Wrote H5: {h5_path}")

    config_note = "not patched (--no-config-patch)"
    if not args.no_config_patch:
        config_note = patch_config(config_path, args.scorer, args.dataset_name)
        info(f"Config {config_note}")

    report_path = labeled_dir / "birdbill-dlc-conversion-report.txt"
    write_report(
        report_path=report_path,
        json_path=json_path,
        config_path=config_path,
        output_dir=labeled_dir,
        rows=rows,
        skipped=skipped,
        missing_images=missing_images,
        csv_path=csv_path,
        h5_path=h5_path,
        config_note=config_note,
    )
    info(f"Wrote report: {report_path}")

    if missing_images:
        info("Conversion completed, but some source images were missing. DLC training may fail unless those images are present.")
    else:
        info(f"Conversion complete. Exported rows: {len(rows)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
