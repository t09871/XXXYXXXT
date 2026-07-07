# lightgluetest.py | HBMR / Birdbill LightGlue probe v0.2.1 | 2026-06-24 PDT
# Standalone pairwise local-feature test for two HBMR crop images.
# Does not read or write the HBMR database.
# Does not assign identities.
#
# v0.2.0 change:
# - adds annotated match visualization output
# - adds timing metrics
# - adds configurable draw limits near top of file
# - keeps drag/drop pair workflow
#
# v0.2.1 change:
# - caps LightGlue report/match-image filename stems and adds short hashes to avoid Windows path-length crashes

import hashlib
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path


APP_VERSION = "HBMR / Birdbill LightGlue probe v0.2.1"
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "lightglue"

MAX_KEYPOINTS = 2048
FEATURES = "superpoint"

DRAW_MATCH_IMAGE = True
DRAW_MAX_MATCHES = 120
DRAW_LINE_WIDTH = 2
DRAW_DOT_RADIUS = 3

# Rough diagnostic labels only. Not canonical identity thresholds.
WEAK_MATCHES = 8
POSSIBLE_MATCHES = 20
STRONG_MATCHES = 45

WEAK_MEAN_SCORE = 0.15
POSSIBLE_MEAN_SCORE = 0.30
STRONG_MEAN_SCORE = 0.50


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def safe_stem(path):
    text = Path(path).stem
    keep = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            keep.append(ch)
        else:
            keep.append("-")
    cleaned = "".join(keep).strip("-_")
    return cleaned or "image"


def short_output_stem(path, max_base_chars=48):
    """
    Return a Windows-safe short stem for report filenames.

    Refined crop filenames can already include recipe names, source video names,
    frame numbers, detector confidence, and timestamps. Pairwise reports combine
    two crop names, so uncapped stems can exceed Windows path limits even though
    the LightGlue comparison itself succeeded.
    """

    base = safe_stem(path)
    digest = hashlib.sha1(str(Path(path)).encode("utf-8", errors="replace")).hexdigest()[:10]
    if len(base) > max_base_chars:
        base = base[:max_base_chars].rstrip("-_")
    return f"{base}-{digest}" if base else f"image-{digest}"


def format_float(value):
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.6f}"
    except Exception:
        return "n/a"


def fail(message, detail=None):
    print()
    print("LightGlue probe failed")
    print("======================")
    print(message)
    if detail:
        print()
        print(detail)
    print()
    print("Press Enter to close this window if launched from the .bat file.")
    try:
        input()
    except Exception:
        pass
    raise SystemExit(1)


def import_dependencies():
    try:
        import torch
    except Exception:
        fail("PyTorch could not be imported.", "Install or activate the same Python environment used for HBMR ML modules.")

    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        fail("Pillow could not be imported.", f"Install with: python -m pip install pillow\n\nOriginal error:\n{exc}")

    try:
        from lightglue import LightGlue, SuperPoint
        from lightglue.utils import load_image, rbd
    except Exception as exc:
        fail(
            "LightGlue could not be imported.",
            "Install LightGlue in the active Python environment first.\n\n"
            "Expected install pattern:\n"
            "git clone https://github.com/cvg/LightGlue.git\n"
            "cd LightGlue\n"
            "python -m pip install -e .\n\n"
            f"Original import error:\n{exc}",
        )

    return torch, Image, ImageDraw, LightGlue, SuperPoint, load_image, rbd


def normalize_tensor_to_list(value):
    if value is None:
        return []
    try:
        if hasattr(value, "detach"):
            value = value.detach().cpu()
        if hasattr(value, "tolist"):
            value = value.tolist()
    except Exception:
        return []
    if isinstance(value, list):
        return value
    return []


def tensor_points_to_list(value):
    out = []
    values = normalize_tensor_to_list(value)
    for item in values:
        if isinstance(item, list) and len(item) >= 2:
            try:
                out.append((float(item[0]), float(item[1])))
            except Exception:
                pass
    return out


def tensor_matches_to_pairs(value):
    pairs = []
    values = normalize_tensor_to_list(value)
    for item in values:
        if isinstance(item, list) and len(item) >= 2:
            try:
                pairs.append((int(item[0]), int(item[1])))
            except Exception:
                pass
    return pairs


def score_list_from_matches(matches01, match_count):
    for key in ("scores", "matching_scores", "match_scores", "confidence", "confidences"):
        if key in matches01:
            values = normalize_tensor_to_list(matches01[key])
            if values:
                flat = []
                for item in values:
                    if isinstance(item, list):
                        flat.extend(item)
                    else:
                        flat.append(item)
                scores = []
                for item in flat:
                    try:
                        scores.append(float(item))
                    except Exception:
                        pass
                if scores:
                    return scores[:match_count] if match_count else scores
    return []


def summarize_scores(scores):
    if not scores:
        return {"mean_score": None, "median_score": None, "min_score": None, "max_score": None}
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    if n % 2:
        median = sorted_scores[n // 2]
    else:
        median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2.0
    return {
        "mean_score": sum(sorted_scores) / n,
        "median_score": median,
        "min_score": sorted_scores[0],
        "max_score": sorted_scores[-1],
    }


def decision_label(match_count, mean_score):
    if mean_score is None:
        if match_count >= STRONG_MATCHES:
            return "possible_local_match"
        if match_count >= POSSIBLE_MATCHES:
            return "weak_possible_local_match"
        return "weak_or_no_local_match"
    if match_count >= STRONG_MATCHES and mean_score >= STRONG_MEAN_SCORE:
        return "strong_local_match"
    if match_count >= POSSIBLE_MATCHES and mean_score >= POSSIBLE_MEAN_SCORE:
        return "possible_local_match"
    if match_count >= WEAK_MATCHES and mean_score >= WEAK_MEAN_SCORE:
        return "weak_possible_local_match"
    return "weak_or_no_local_match"


def resize_for_visual(img, max_side=720):
    w, h = img.size
    if w <= 0 or h <= 0:
        return img, 1.0
    scale = min(1.0, max_side / max(w, h))
    if scale >= 1.0:
        return img.copy(), 1.0
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return img.resize(new_size), scale


def draw_matches_image(image_a, image_b, keypoints_a, keypoints_b, match_pairs, scores, out_path, Image, ImageDraw):
    img_a = Image.open(image_a).convert("RGB")
    img_b = Image.open(image_b).convert("RGB")
    img_a_draw, scale_a = resize_for_visual(img_a)
    img_b_draw, scale_b = resize_for_visual(img_b)
    gap = 24
    width = img_a_draw.width + gap + img_b_draw.width
    height = max(img_a_draw.height, img_b_draw.height)
    canvas = Image.new("RGB", (width, height), (245, 245, 245))
    canvas.paste(img_a_draw, (0, 0))
    canvas.paste(img_b_draw, (img_a_draw.width + gap, 0))
    draw = ImageDraw.Draw(canvas)

    pairs = match_pairs[:]
    sorted_scores = []
    if scores and len(scores) == len(pairs):
        indexed = list(zip(pairs, scores))
        indexed.sort(key=lambda item: item[1], reverse=True)
        pairs = [item[0] for item in indexed]
        sorted_scores = [item[1] for item in indexed]

    pairs = pairs[:DRAW_MAX_MATCHES]

    for i, (idx_a, idx_b) in enumerate(pairs):
        if idx_a < 0 or idx_b < 0 or idx_a >= len(keypoints_a) or idx_b >= len(keypoints_b):
            continue
        ax, ay = keypoints_a[idx_a]
        bx, by = keypoints_b[idx_b]
        ax *= scale_a
        ay *= scale_a
        bx = bx * scale_b + img_a_draw.width + gap
        by *= scale_b
        if sorted_scores and i < len(sorted_scores):
            s = max(0.0, min(1.0, float(sorted_scores[i])))
            shade = int(60 + 180 * s)
        else:
            shade = 180
        color = (shade, 60, 255 - min(200, shade // 2))
        draw.line((ax, ay, bx, by), fill=color, width=DRAW_LINE_WIDTH)
        draw.ellipse((ax - DRAW_DOT_RADIUS, ay - DRAW_DOT_RADIUS, ax + DRAW_DOT_RADIUS, ay + DRAW_DOT_RADIUS), fill=color)
        draw.ellipse((bx - DRAW_DOT_RADIUS, by - DRAW_DOT_RADIUS, bx + DRAW_DOT_RADIUS, by + DRAW_DOT_RADIUS), fill=color)

    draw.text((8, 8), Path(image_a).name, fill=(0, 0, 0))
    draw.text((img_a_draw.width + gap + 8, 8), Path(image_b).name, fill=(0, 0, 0))
    draw.text((8, height - 24), f"Showing top {len(pairs)} of {len(match_pairs)} matches", fill=(0, 0, 0))
    canvas.save(out_path)
    return out_path


def run_lightglue_pair(image_a, image_b):
    torch, Image, ImageDraw, LightGlue, SuperPoint, load_image, rbd = import_dependencies()
    timing = {}
    start = time.perf_counter()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.set_grad_enabled(False)

    print(f"Device: {device}")
    t = time.perf_counter()
    print("Loading SuperPoint extractor...")
    extractor = SuperPoint(max_num_keypoints=MAX_KEYPOINTS).eval().to(device)
    print("Loading LightGlue matcher...")
    matcher = LightGlue(features=FEATURES).eval().to(device)
    timing["load_models_seconds"] = time.perf_counter() - t

    t = time.perf_counter()
    print("Loading images...")
    image0 = load_image(str(image_a)).to(device)
    image1 = load_image(str(image_b)).to(device)
    timing["load_images_seconds"] = time.perf_counter() - t

    t = time.perf_counter()
    print("Extracting local features...")
    feats0 = extractor.extract(image0)
    feats1 = extractor.extract(image1)
    timing["extract_features_seconds"] = time.perf_counter() - t

    t = time.perf_counter()
    print("Matching feature sets...")
    matches01 = matcher({"image0": feats0, "image1": feats1})
    timing["match_seconds"] = time.perf_counter() - t

    feats0 = rbd(feats0)
    feats1 = rbd(feats1)
    matches01 = rbd(matches01)

    kpts0_tensor = feats0.get("keypoints", [])
    kpts1_tensor = feats1.get("keypoints", [])
    matches_tensor = matches01.get("matches", [])

    keypoints_a_list = tensor_points_to_list(kpts0_tensor)
    keypoints_b_list = tensor_points_to_list(kpts1_tensor)
    match_pairs = tensor_matches_to_pairs(matches_tensor)

    try:
        keypoints_a = int(kpts0_tensor.shape[0])
    except Exception:
        keypoints_a = len(keypoints_a_list)
    try:
        keypoints_b = int(kpts1_tensor.shape[0])
    except Exception:
        keypoints_b = len(keypoints_b_list)

    match_count = len(match_pairs)
    scores = score_list_from_matches(matches01, match_count)
    score_summary = summarize_scores(scores)
    decision = decision_label(match_count, score_summary["mean_score"])
    timing["total_seconds"] = time.perf_counter() - start

    return {
        "app_version": APP_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "image_a": str(image_a),
        "image_b": str(image_b),
        "features": FEATURES,
        "max_keypoints": MAX_KEYPOINTS,
        "device": str(device),
        "keypoints_a": keypoints_a,
        "keypoints_b": keypoints_b,
        "matches": match_count,
        "scores_available": bool(scores),
        **score_summary,
        "decision": decision,
        "timing": timing,
        "draw_match_image": DRAW_MATCH_IMAGE,
        "draw_max_matches": DRAW_MAX_MATCHES,
        "keypoints_a_preview": keypoints_a_list[:10],
        "keypoints_b_preview": keypoints_b_list[:10],
        "match_pairs_preview": match_pairs[:10],
        "_draw_payload": {
            "Image": Image,
            "ImageDraw": ImageDraw,
            "keypoints_a": keypoints_a_list,
            "keypoints_b": keypoints_b_list,
            "match_pairs": match_pairs,
            "scores": scores,
        },
        "notes": "Diagnostic only. These labels are not identity truth. Use this to compare same-bird, different-bird, false-positive, low-quality, and multibird crop pairs.",
    }


def write_report(result):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    a = short_output_stem(result["image_a"])
    b = short_output_stem(result["image_b"])
    stamp = now_stamp()
    pair_stem = f"lightglue-{stamp}-{a}-VS-{b}"
    report_path = OUTPUT_DIR / f"{pair_stem}.txt"
    json_path = OUTPUT_DIR / f"{pair_stem}.json"
    match_image_path = OUTPUT_DIR / f"{pair_stem}-matches.jpg"

    draw_payload = result.pop("_draw_payload", None)
    if DRAW_MATCH_IMAGE and draw_payload:
        try:
            draw_matches_image(
                result["image_a"],
                result["image_b"],
                draw_payload["keypoints_a"],
                draw_payload["keypoints_b"],
                draw_payload["match_pairs"],
                draw_payload["scores"],
                match_image_path,
                draw_payload["Image"],
                draw_payload["ImageDraw"],
            )
            result["match_image"] = str(match_image_path)
        except Exception as exc:
            result["match_image"] = ""
            result["match_image_error"] = str(exc)
    else:
        result["match_image"] = ""

    timing = result.get("timing", {})
    lines = [
        result["app_version"],
        "=" * len(result["app_version"]),
        "",
        f"Created: {result['created_at']}",
        f"Image A: {result['image_a']}",
        f"Image B: {result['image_b']}",
        "",
        f"Features: {result['features']}",
        f"Max keypoints: {result['max_keypoints']}",
        f"Device: {result['device']}",
        "",
        f"Keypoints A: {result['keypoints_a']}",
        f"Keypoints B: {result['keypoints_b']}",
        f"Matches: {result['matches']}",
        f"Scores available: {result['scores_available']}",
        f"Mean score: {format_float(result['mean_score'])}",
        f"Median score: {format_float(result['median_score'])}",
        f"Min score: {format_float(result['min_score'])}",
        f"Max score: {format_float(result['max_score'])}",
        "",
        f"Diagnostic decision: {result['decision']}",
        "",
        "Timing:",
        f"  load models seconds: {format_float(timing.get('load_models_seconds'))}",
        f"  load images seconds: {format_float(timing.get('load_images_seconds'))}",
        f"  extract features seconds: {format_float(timing.get('extract_features_seconds'))}",
        f"  match seconds: {format_float(timing.get('match_seconds'))}",
        f"  total seconds: {format_float(timing.get('total_seconds'))}",
        "",
        f"Match image: {result.get('match_image') or 'n/a'}",
        "",
        result["notes"],
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return report_path, json_path, result.get("match_image") or ""


def print_result(result, report_path, json_path, match_image):
    timing = result.get("timing", {})
    print()
    print("LightGlue pair test")
    print("===================")
    print(f"Image A: {result['image_a']}")
    print(f"Image B: {result['image_b']}")
    print()
    print(f"Features: {result['features']}")
    print(f"Device: {result['device']}")
    print(f"Keypoints A: {result['keypoints_a']}")
    print(f"Keypoints B: {result['keypoints_b']}")
    print(f"Matches: {result['matches']}")
    print(f"Mean score: {format_float(result['mean_score'])}")
    print(f"Median score: {format_float(result['median_score'])}")
    print(f"Decision: {result['decision']}")
    print(f"Total seconds: {format_float(timing.get('total_seconds'))}")
    print()
    print(f"Report: {report_path}")
    print(f"JSON: {json_path}")
    print(f"Match image: {match_image or 'n/a'}")
    print()


def main():
    print(APP_VERSION)
    print("Standalone local-feature pair probe.")
    print("No database writes. No identity assignment.")
    print()

    if len(sys.argv) != 3:
        print("Usage:")
        print("  python lightgluetest.py imageA imageB")
        print()
        print("Drag/drop usage:")
        print("  Select exactly two crop images and drag them onto lightgluetest.bat.")
        print()
        print("Press Enter to close.")
        try:
            input()
        except Exception:
            pass
        return

    image_a = Path(sys.argv[1]).resolve()
    image_b = Path(sys.argv[2]).resolve()
    if not image_a.exists():
        fail(f"Image A does not exist: {image_a}")
    if not image_b.exists():
        fail(f"Image B does not exist: {image_b}")

    try:
        result = run_lightglue_pair(image_a, image_b)
        report_path, json_path, match_image = write_report(result)
        print_result(result, report_path, json_path, match_image)
    except SystemExit:
        raise
    except Exception:
        print()
        print("LightGlue probe crashed")
        print("=======================")
        traceback.print_exc()
        print()

    print("Press Enter to close this window if launched from the .bat file.")
    try:
        input()
    except Exception:
        pass


if __name__ == "__main__":
    main()
