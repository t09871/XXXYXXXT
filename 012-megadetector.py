# megadetector.py | HBMR v2.2.9 Step 3 | 2026-06-30 PDT

from pathlib import Path
import sys
import traceback
import argparse

from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_VERSION = "MDV6-yolov9-c"
LOCAL_MODEL_FILE = PROJECT_DIR / "models" / "MDV6b-yolov9-c.pt"
OUTPUT_CROPS_DIR = PROJECT_DIR / "output" / "crops"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

ANIMAL_CLASS_ID = 0
CONFIDENCE_THRESHOLD = 0.20
CROP_PADDING_RATIO = 0.20


def pause_before_exit(no_pause=False):
    if no_pause:
        return
    print()
    try:
        input("Press Enter to close...")
    except EOFError:
        # Safe when called from another program/subprocess with no stdin.
        return



def load_model():
    print(f"Loading MegaDetector model: {MODEL_VERSION}")
    print(f"Local model file: {LOCAL_MODEL_FILE}")

    if not LOCAL_MODEL_FILE.exists():
        raise FileNotFoundError(
            "Local MegaDetector weights file not found.\n"
            f"Expected file here:\n{LOCAL_MODEL_FILE}\n\n"
            "Run v2.2.4 safeguard mode first to create the local model file."
        )

    try:
        from PytorchWildlife.models import detection as pw_detection
    except Exception as e:
        raise RuntimeError(f"Could not import PytorchWildlife detection module: {e}")

    try:
        model = pw_detection.MegaDetectorV6(
            weights=str(LOCAL_MODEL_FILE),
            device="cpu",
            pretrained=False,
            version=MODEL_VERSION,
        )
    except Exception as e:
        raise RuntimeError(f"Could not load MegaDetectorV6 from local weights: {e}")

    print("Model loaded from local file.")
    return model


def collect_image_paths(input_paths):
    image_paths = []

    for input_path in input_paths:
        path = Path(input_path)

        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            image_paths.append(path)

        elif path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
                    image_paths.append(child)

        else:
            print(f"Skipping unsupported input: {path}")

    return image_paths


def run_detector(model, image_path):
    print()
    print(f"Running detector on: {image_path}")

    try:
        return model.single_image_detection(str(image_path))
    except AttributeError:
        try:
            return model.single_image_detection(image_path=str(image_path))
        except Exception as e:
            raise RuntimeError(f"Detector call failed: {e}")
    except Exception as e:
        raise RuntimeError(f"Detector call failed: {e}")


def normalize_animal_detections(raw_results):
    if not isinstance(raw_results, dict):
        raise RuntimeError(f"Expected raw detector result to be dict, got: {type(raw_results)}")

    detections_object = raw_results.get("detections")

    if detections_object is None:
        raise RuntimeError("Raw detector result did not contain a 'detections' field.")

    xyxy = getattr(detections_object, "xyxy", None)
    confidence = getattr(detections_object, "confidence", None)
    class_id = getattr(detections_object, "class_id", None)

    if xyxy is None:
        raise RuntimeError("Detections object did not contain xyxy boxes.")
    if confidence is None:
        raise RuntimeError("Detections object did not contain confidence values.")
    if class_id is None:
        raise RuntimeError("Detections object did not contain class_id values.")

    normalized = []

    for index in range(len(xyxy)):
        this_class_id = int(class_id[index])
        this_confidence = float(confidence[index])

        if this_class_id != ANIMAL_CLASS_ID:
            continue

        if this_confidence < CONFIDENCE_THRESHOLD:
            continue

        x1, y1, x2, y2 = [float(value) for value in xyxy[index]]

        normalized.append({
            "class_name": "animal",
            "class_id": this_class_id,
            "confidence": this_confidence,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
        })

    return normalized


def make_padded_box(detection, image_width, image_height):
    x1 = float(detection["x1"])
    y1 = float(detection["y1"])
    x2 = float(detection["x2"])
    y2 = float(detection["y2"])

    box_width = x2 - x1
    box_height = y2 - y1

    if box_width <= 0 or box_height <= 0:
        return None

    pad_x = box_width * CROP_PADDING_RATIO
    pad_y = box_height * CROP_PADDING_RATIO

    padded_x1 = max(0, int(round(x1 - pad_x)))
    padded_y1 = max(0, int(round(y1 - pad_y)))
    padded_x2 = min(image_width, int(round(x2 + pad_x)))
    padded_y2 = min(image_height, int(round(y2 + pad_y)))

    if padded_x2 <= padded_x1 or padded_y2 <= padded_y1:
        return None

    return padded_x1, padded_y1, padded_x2, padded_y2


def export_crops(image_path, animal_detections):
    OUTPUT_CROPS_DIR.mkdir(parents=True, exist_ok=True)

    saved_paths = []

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image_width, image_height = image.size

        for index, detection in enumerate(animal_detections, start=1):
            box = make_padded_box(detection, image_width, image_height)

            if box is None:
                print(f"Skipping invalid crop box for detection {index}.")
                continue

            crop = image.crop(box)
            confidence_text = f"{int(round(detection['confidence'] * 100)):03d}"

            output_name = (
                f"{image_path.stem}-animal-{index:03d}-conf{confidence_text}-pad20.png"
            )
            output_path = OUTPUT_CROPS_DIR / output_name

            crop.save(output_path)
            saved_paths.append(output_path)

    return saved_paths


def print_normalized_animals(animal_detections):
    print(f"Animal detections: {len(animal_detections)}")

    for index, detection in enumerate(animal_detections, start=1):
        print(
            f"{index}: "
            f"confidence={detection['confidence']:.3f} "
            f"box=({detection['x1']:.1f}, {detection['y1']:.1f}, "
            f"{detection['x2']:.1f}, {detection['y2']:.1f})"
        )


def print_saved_crops(saved_paths):
    print(f"Crops exported: {len(saved_paths)}")

    for path in saved_paths:
        print(f"  {path}")


def process_image(model, image_path, image_index, total_images):
    print()
    print("=" * 72)
    print(f"Image {image_index} of {total_images}")
    print(f"Input: {image_path}")

    raw_results = run_detector(model, image_path)
    animal_detections = normalize_animal_detections(raw_results)

    print_normalized_animals(animal_detections)

    saved_paths = export_crops(image_path, animal_detections)
    print_saved_crops(saved_paths)

    return len(animal_detections), len(saved_paths)


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="HBMR MegaDetector folder-capable animal crop exporter",
        add_help=True,
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Image file(s) or folder(s) containing image files.",
    )
    parser.add_argument(
        "--no-pause",
        action="store_true",
        help="Do not wait for Enter before exit. Required for GUI/subprocess callers such as samplerGUI.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    no_pause = bool(args.no_pause)

    print("HBMR v2.2.9 Step 3: MegaDetector folder-capable animal crop exporter")
    print("Goal: drag image or folder onto launcher -> animal-only padded crops")
    print(f"Python executable: {sys.executable}")
    print(f"Project directory: {PROJECT_DIR}")
    print(f"No-pause mode: {no_pause}")
    print()

    if not args.inputs:
        print("No image or folder was provided.")
        print()
        print("Use:")
        print("  Drag one image file onto a MegaDetector launcher")
        print("  Drag one folder of images onto a MegaDetector launcher")
        print("  Or call from samplerGUI with --no-pause")
        pause_before_exit(no_pause)
        return

    image_paths = collect_image_paths(args.inputs)

    if not image_paths:
        print("No supported image files found.")
        pause_before_exit(no_pause)
        return

    print(f"Images queued: {len(image_paths)}")

    model = load_model()

    total_animals = 0
    total_crops = 0

    for index, image_path in enumerate(image_paths, start=1):
        animal_count, crop_count = process_image(
            model=model,
            image_path=image_path,
            image_index=index,
            total_images=len(image_paths),
        )
        total_animals += animal_count
        total_crops += crop_count

    print()
    print("=" * 72)
    print("Step 3 complete.")
    print(f"Images processed: {len(image_paths)}")
    print(f"Animal detections total: {total_animals}")
    print(f"Crops exported total: {total_crops}")
    print()
    print("Validation target: drag a small folder with bird, no-bird, and hard frames.")
    pause_before_exit(no_pause)


if __name__ == "__main__":
    no_pause_for_error = "--no-pause" in sys.argv[1:]
    try:
        main()
    except Exception:
        print()
        print("HBMR v2.2.9 crashed.")
        print()
        traceback.print_exc()
        pause_before_exit(no_pause_for_error)