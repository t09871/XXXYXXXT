# visualid.py | HBMR visual identity module v0.1.1 | 2026-06-20 PDT
# Owns DINOv2 crop embeddings, visual similarity, and provisional identity assignment.
#
# v0.1.1 change:
# - excludes special evidence statuses from identity matching evidence
# - keeps multibird / low_quality / false_positive crops from strengthening Bird### identities
# - keeps visual_embeddings as cache/provenance, not biological truth

import json
import sqlite3
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

from autoname import allocate_bird_name


MODEL_NAME = "facebook/dinov2-small"
MODEL_VERSION = "dinov2-small-v0.1"
MATCH_THRESHOLD = 0.79

EXCLUDED_MATCH_STATUSES = {
    "multibird",
    "low_quality",
    "false_positive",
    "junk",
}

_processor = None
_model = None


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn, table_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.OperationalError:
        return []
    return [row[1] for row in rows]


def ensure_visual_tables(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visual_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crop_path TEXT NOT NULL UNIQUE,
                identity TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def load_model():
    global _processor, _model

    if _processor is None or _model is None:
        print("Loading DINOv2 visual identity model...")
        _processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
        _model = AutoModel.from_pretrained(MODEL_NAME)
        _model.eval()

    return _processor, _model


def compute_embedding(crop_path):
    processor, model = load_model()

    image = Image.open(crop_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")

    with torch.no_grad():
        outputs = model(**inputs)

    embedding = outputs.last_hidden_state.mean(dim=1)
    embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

    return embedding.squeeze(0).tolist()


def cosine_similarity_list(a, b):
    tensor_a = torch.tensor(a).unsqueeze(0)
    tensor_b = torch.tensor(b).unsqueeze(0)
    return torch.nn.functional.cosine_similarity(tensor_a, tensor_b).item()


def get_existing_embeddings(db_path):
    ensure_visual_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        if table_exists(conn, "crop_queue"):
            crop_cols = table_columns(conn, "crop_queue")
            if "crop_path" in crop_cols and "identity_status" in crop_cols:
                rows = conn.execute(
                    """
                    SELECT
                        ve.crop_path,
                        ve.identity,
                        ve.embedding_json,
                        cq.identity_status
                    FROM visual_embeddings ve
                    LEFT JOIN crop_queue cq
                        ON cq.crop_path = ve.crop_path
                    WHERE ve.model_version = ?
                      AND COALESCE(cq.identity_status, '') NOT IN (?, ?, ?, ?)
                    """,
                    (
                        MODEL_VERSION,
                        "multibird",
                        "low_quality",
                        "false_positive",
                        "junk",
                    ),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT crop_path, identity, embedding_json, NULL AS identity_status
                    FROM visual_embeddings
                    WHERE model_version = ?
                    """,
                    (MODEL_VERSION,),
                ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT crop_path, identity, embedding_json, NULL AS identity_status
                FROM visual_embeddings
                WHERE model_version = ?
                """,
                (MODEL_VERSION,),
            ).fetchall()

    existing = []
    for row in rows:
        existing.append(
            {
                "crop_path": row["crop_path"],
                "identity": row["identity"],
                "embedding": json.loads(row["embedding_json"]),
                "identity_status": row["identity_status"],
            }
        )

    return existing


def store_embedding(db_path, crop_path, identity, embedding):
    ensure_visual_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO visual_embeddings
            (crop_path, identity, model_name, model_version, embedding_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(crop_path),
                identity,
                MODEL_NAME,
                MODEL_VERSION,
                json.dumps(embedding),
            ),
        )
        conn.commit()


def assign_identity(db_path, crop_path):
    crop_path = Path(crop_path)
    ensure_visual_tables(db_path)

    embedding = compute_embedding(crop_path)
    existing = get_existing_embeddings(db_path)

    best_identity = None
    best_score = None
    best_crop_path = None

    for row in existing:
        score = cosine_similarity_list(embedding, row["embedding"])

        if best_score is None or score > best_score:
            best_score = score
            best_identity = row["identity"]
            best_crop_path = row["crop_path"]

    if best_score is not None and best_score >= MATCH_THRESHOLD:
        identity = best_identity
        decision = "match"
    else:
        identity = allocate_bird_name(db_path)
        decision = "new"

    store_embedding(db_path, crop_path, identity, embedding)

    return {
        "identity": identity,
        "score": best_score,
        "decision": decision,
        "threshold": MATCH_THRESHOLD,
        "matched_crop_path": best_crop_path,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
    }
