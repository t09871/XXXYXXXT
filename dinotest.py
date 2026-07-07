# dinotest.py | HBMR DINOv2 probe v0.1.0 | 2026-06-18 PDT

import sys
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel


MODEL_NAME = "facebook/dinov2-small"


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("python dinotest.py path_to_crop_image")
        return 1

    image_path = Path(sys.argv[1])

    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        return 1

    print("HBMR DINOv2 probe v0.1.0")
    print(f"Model: {MODEL_NAME}")
    print(f"Image: {image_path}")
    print()

    print("Loading DINOv2 model...")
    processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME)
    model.eval()

    print("Loading image...")
    image = Image.open(image_path).convert("RGB")

    print("Computing embedding...")
    inputs = processor(images=image, return_tensors="pt")

    with torch.no_grad():
        outputs = model(**inputs)

    embedding = outputs.last_hidden_state.mean(dim=1)
    embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

    print()
    print("Success.")
    print(f"Embedding shape: {tuple(embedding.shape)}")
    print(f"Embedding norm: {embedding.norm().item():.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())