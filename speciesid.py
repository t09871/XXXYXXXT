# speciesid.py | HBMR Species ID v0.1.12 | 2026-06-22 PDT
# Lightweight SpeciesNet wrapper for HBMR crop-level species annotations.
# Contract:
# - Species ID is optional crop annotation only.
# - Species ID must not merge, split, rename, or authorize Bird### identities.
# - Species ID must not write visual_embeddings.
# - GUI summary is emitted only between HBMR_SPECIES_SUMMARY_BEGIN / END.
#
# v0.1.12 change:
# - treats non-hummingbird weak guesses as weak_non_hbmr_guess for display/review safety
# - preserves the raw SpeciesNet species label and confidence in crop_species and debug JSON
# - keeps confidence band as weak_guess so the low-confidence nature remains visible
# - does not change SpeciesNet execution, geography, staging, parser extraction, upsert, or GUI markers
#
# v0.1.11 change:
# - adds richer candidate-list diagnostics to speciesid-debug.json
# - records per-crop classifier top candidates, ranks, scores, and rejectability
# - counts whether hummingbird/trochilidae-style candidates appear anywhere in parsed classifier lists
# - preserves v0.1.10 geography, parser decisions, confidence bands, staging, upsert, and GUI summary contract
#
# v0.1.10 change:
# - adds SpeciesNet geography/geofence arguments: --country and --admin1_region
# - reads Country / Admin1Region from settings.ini when present
# - allows CLI override with --country and --admin1-region
# - preserves v0.1.9 parser, confidence bands, staging, upsert, and GUI summary contract

from __future__ import annotations

import argparse
import configparser
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

APP_NAME = "HBMR Species ID"
APP_VERSION = "v0.1.12"
SUMMARY_BEGIN = "HBMR_SPECIES_SUMMARY_BEGIN"
SUMMARY_END = "HBMR_SPECIES_SUMMARY_END"

DEFAULT_DB_REL = Path("output") / "database" / "mr-review.db"
DEFAULT_SPECIES_DIR_REL = Path("output") / "species"
DEFAULT_INPUT_DIRNAME = "speciesnet-input"
DEFAULT_PREDICTIONS_NAME = "speciesnet-predictions.json"
DEFAULT_DEBUG_NAME = "speciesid-debug.json"
DEFAULT_LOG_REL = Path("output") / "logs" / "speciesid.log"

CROP_QUEUE_TABLE = "crop_queue"
SPECIES_TABLE = "crop_species"

DEFAULT_HIGH_CONFIDENCE = 0.70
DEFAULT_MEDIUM_CONFIDENCE = 0.30
DEFAULT_COUNTRY = "USA"
DEFAULT_ADMIN1_REGION = "CA"


@dataclass
class Settings:
    project_root: Path
    settings_path: Path
    db_path: Path
    species_python: Path
    species_python_source: str
    species_dir: Path
    input_dir: Path
    predictions_json: Path
    debug_json: Path
    log_path: Path
    country: str
    admin1_region: str


@dataclass
class CropCandidate:
    crop_path: str
    source_id: str


@dataclass
class ParsedPrediction:
    source_id: str
    crop_path: str
    label: str
    confidence: Optional[float]
    broad_label: str
    broad_confidence: Optional[float]
    classifier_label: str
    classifier_confidence: Optional[float]
    detector_label: str
    detector_confidence: Optional[float]
    decision_label: str
    decision_rank: str
    review_status: str
    confidence_band: str
    proposed_candidate: str
    raw_prediction: Dict[str, Any]


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def safe_print(text: str = "") -> None:
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)


def append_log(settings: Settings, message: str) -> None:
    try:
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        with settings.log_path.open("a", encoding="utf-8") as f:
            f.write(f"[{now_stamp()}] {message}\n")
        max_bytes = 512_000
        keep_bytes = 250_000
        if settings.log_path.exists() and settings.log_path.stat().st_size > max_bytes:
            data = settings.log_path.read_bytes()[-keep_bytes:]
            settings.log_path.write_bytes(data)
    except Exception:
        pass


def find_project_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / "settings.ini").exists():
        return cwd
    here = Path(__file__).resolve().parent
    if (here / "settings.ini").exists():
        return here
    return cwd


def first_existing_config_value(config: configparser.ConfigParser, keys: Iterable[str]) -> Optional[str]:
    lowered = {k.lower() for k in keys}
    for section in config.sections():
        for key, value in config.items(section):
            if key.lower() in lowered and value.strip():
                return value.strip()
    return None


def resolve_path(value: Optional[str], base: Path, fallback: Path) -> Path:
    if not value:
        return fallback.resolve()
    p = Path(value.strip().strip('"'))
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def load_settings(settings_arg: Optional[str], country_arg: Optional[str] = None, admin1_arg: Optional[str] = None) -> Settings:
    project_root = find_project_root()
    settings_path = resolve_path(settings_arg, project_root, project_root / "settings.ini")

    config = configparser.ConfigParser()
    if settings_path.exists():
        config.read(settings_path, encoding="utf-8")

    db_value = first_existing_config_value(
        config,
        [
            "database",
            "database_path",
            "db_path",
            "review_db",
            "review_database",
            "mr_review_db",
            "observations_db",
        ],
    )
    species_python_value = first_existing_config_value(
        config,
        [
            "species_python",
            "speciesnet_python",
            "speciesnet_python_path",
            "speciesnet_interpreter",
            "python_speciesnet",
        ],
    )
    species_dir_value = first_existing_config_value(
        config,
        ["species_dir", "species_output_dir", "speciesnet_output_dir", "species_output"],
    )
    country_value = country_arg or first_existing_config_value(config, ["country", "species_country", "speciesnet_country"])
    admin1_value = admin1_arg or first_existing_config_value(config, ["admin1region", "admin1_region", "species_admin1_region", "speciesnet_admin1_region"])

    db_path = resolve_path(db_value, project_root, project_root / DEFAULT_DB_REL)
    species_dir = resolve_path(species_dir_value, project_root, project_root / DEFAULT_SPECIES_DIR_REL)

    if species_python_value:
        species_python = resolve_path(species_python_value, project_root, project_root / "speciesnet-env" / "Scripts" / "python.exe")
        species_python_source = "configured_species_python"
    else:
        species_python = (project_root / "speciesnet-env" / "Scripts" / "python.exe").resolve()
        species_python_source = "default_project_speciesnet_env"

    input_dir = species_dir / DEFAULT_INPUT_DIRNAME
    predictions_json = species_dir / DEFAULT_PREDICTIONS_NAME
    debug_json = species_dir / DEFAULT_DEBUG_NAME
    log_path = (project_root / DEFAULT_LOG_REL).resolve()

    country = (country_value or DEFAULT_COUNTRY).strip().upper()
    admin1_region = (admin1_value or DEFAULT_ADMIN1_REGION).strip().upper()

    return Settings(
        project_root=project_root,
        settings_path=settings_path,
        db_path=db_path,
        species_python=species_python,
        species_python_source=species_python_source,
        species_dir=species_dir,
        input_dir=input_dir,
        predictions_json=predictions_json,
        debug_json=debug_json,
        log_path=log_path,
        country=country,
        admin1_region=admin1_region,
    )


def speciesnet_help_available(settings: Settings) -> Tuple[bool, str]:
    cmd = [str(settings.species_python), "-m", "speciesnet.scripts.run_model", "--help"]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return False, str(exc)
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    help_looks_valid = "speciesnet" in output.lower() and ("predictions_json" in output or "--folders" in output)
    return completed.returncode == 0 or help_looks_valid, output


def connect_db(settings: Settings) -> sqlite3.Connection:
    if not settings.db_path.exists():
        raise FileNotFoundError(f"Database not found: {settings.db_path}")
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(r[1]) for r in rows]


def ensure_species_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SPECIES_TABLE} (
            crop_path TEXT UNIQUE,
            species_label TEXT,
            confidence REAL,
            broad_label TEXT,
            broad_confidence REAL,
            classifier_label TEXT,
            classifier_confidence REAL,
            detector_label TEXT,
            detector_confidence REAL,
            decision_label TEXT,
            decision_rank TEXT,
            review_status TEXT,
            confidence_band TEXT,
            proposed_candidate TEXT,
            source_id TEXT,
            model_name TEXT,
            model_version TEXT,
            status TEXT,
            raw_json TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()

    existing = set(table_columns(conn, SPECIES_TABLE))
    wanted = {
        "crop_path": "TEXT",
        "species_label": "TEXT",
        "confidence": "REAL",
        "broad_label": "TEXT",
        "broad_confidence": "REAL",
        "classifier_label": "TEXT",
        "classifier_confidence": "REAL",
        "detector_label": "TEXT",
        "detector_confidence": "REAL",
        "decision_label": "TEXT",
        "decision_rank": "TEXT",
        "review_status": "TEXT",
        "confidence_band": "TEXT",
        "proposed_candidate": "TEXT",
        "source_id": "TEXT",
        "model_name": "TEXT",
        "model_version": "TEXT",
        "status": "TEXT",
        "raw_json": "TEXT",
        "updated_at": "TEXT",
    }
    for col, typ in wanted.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE {SPECIES_TABLE} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass
    conn.commit()

    try:
        conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{SPECIES_TABLE}_crop_path ON {SPECIES_TABLE}(crop_path)")
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    except sqlite3.OperationalError:
        pass


def choose_crop_path_column(conn: sqlite3.Connection) -> str:
    cols = table_columns(conn, CROP_QUEUE_TABLE)
    for name in ["crop_path", "path", "filepath", "file_path", "image_path"]:
        if name in cols:
            return name
    raise RuntimeError(f"Could not find crop path column in {CROP_QUEUE_TABLE}. Columns: {', '.join(cols)}")


def select_candidates(conn: sqlite3.Connection, limit: int, force: bool) -> List[CropCandidate]:
    crop_col = choose_crop_path_column(conn)
    where_exists = f"{crop_col} IS NOT NULL AND TRIM({crop_col}) != ''"

    if force:
        sql = f"SELECT {crop_col} AS crop_path FROM {CROP_QUEUE_TABLE} WHERE {where_exists} ORDER BY rowid LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        sql = f"""
            SELECT q.{crop_col} AS crop_path
            FROM {CROP_QUEUE_TABLE} q
            LEFT JOIN {SPECIES_TABLE} s ON s.crop_path = q.{crop_col}
            WHERE q.{crop_col} IS NOT NULL
              AND TRIM(q.{crop_col}) != ''
              AND s.crop_path IS NULL
            ORDER BY q.rowid
            LIMIT ?
        """
        rows = conn.execute(sql, (limit,)).fetchall()

    candidates: List[CropCandidate] = []
    seen: set[str] = set()
    for row in rows:
        crop_path = str(row["crop_path"])
        if crop_path in seen:
            continue
        seen.add(crop_path)
        if Path(crop_path).exists():
            candidates.append(CropCandidate(crop_path=crop_path, source_id=str(uuid.uuid4())))
    return candidates


def clean_staging(input_dir: Path) -> None:
    if input_dir.exists():
        shutil.rmtree(input_dir, ignore_errors=True)
    input_dir.mkdir(parents=True, exist_ok=True)


def safe_extension(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"]:
        return suffix
    return ".jpg"


def stage_candidates(settings: Settings, candidates: List[CropCandidate]) -> Tuple[Dict[str, CropCandidate], Dict[str, int]]:
    clean_staging(settings.input_dir)
    staged_map: Dict[str, CropCandidate] = {}
    counts = {"hardlink": 0, "symlink": 0, "copy": 0, "failed": 0}

    for idx, cand in enumerate(candidates, 1):
        src = Path(cand.crop_path)
        ext = safe_extension(src)
        stage_name = f"hbmr_species_{idx:06d}_{cand.source_id}{ext}"
        dst = settings.input_dir / stage_name

        done = False
        try:
            os.link(src, dst)
            counts["hardlink"] += 1
            done = True
        except Exception:
            pass

        if not done:
            try:
                os.symlink(src, dst)
                counts["symlink"] += 1
                done = True
            except Exception:
                pass

        if not done:
            try:
                shutil.copy2(src, dst)
                counts["copy"] += 1
                done = True
            except Exception:
                counts["failed"] += 1
                append_log(settings, f"Failed to stage crop: {src}")

        if done:
            staged_map[str(dst.resolve())] = cand
            staged_map[str(dst)] = cand
            staged_map[dst.name] = cand

    return staged_map, counts


def remove_predictions_on_force(settings: Settings, force: bool) -> bool:
    if force and settings.predictions_json.exists():
        try:
            settings.predictions_json.unlink()
            return True
        except Exception as exc:
            append_log(settings, f"Could not delete old predictions JSON on force: {exc}")
    return False


def run_speciesnet(settings: Settings) -> Tuple[int, str, str]:
    cmd = [
        str(settings.species_python),
        "-m",
        "speciesnet.scripts.run_model",
        "--folders",
        str(settings.input_dir),
        "--predictions_json",
        str(settings.predictions_json),
    ]

    if settings.country:
        cmd.extend(["--country", settings.country])
    if settings.admin1_region:
        cmd.extend(["--admin1_region", settings.admin1_region])

    cmd_text = " ".join(cmd)
    safe_print(f"SpeciesNet command: {cmd_text}")
    append_log(settings, f"SpeciesNet command: {cmd_text}")
    completed = subprocess.run(cmd, capture_output=True, text=True)
    output = (completed.stdout or "") + (completed.stderr or "")
    if output:
        safe_print(output.rstrip())
    return completed.returncode, cmd_text, output


def load_predictions(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_prediction_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []

    for key in ["predictions", "outputs", "images", "results", "detections"]:
        val = data.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
        if isinstance(val, dict):
            return [x for x in val.values() if isinstance(x, dict)]

    if all(isinstance(v, dict) for v in data.values()):
        records: List[Dict[str, Any]] = []
        for k, v in data.items():
            rec = dict(v)
            rec.setdefault("filepath", k)
            records.append(rec)
        return records

    return []


def normalize_label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ["label", "class", "name", "common_name", "scientific_name", "taxon", "prediction", "category"]:
            if key in value and value[key]:
                return normalize_label(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def normalize_confidence(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def get_first(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in d and d[key] not in [None, ""]:
            return d[key]
    return None


def best_from_prediction_list(items: Any) -> Tuple[str, Optional[float]]:
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or not items:
        return "", None
    best_label = ""
    best_conf: Optional[float] = None
    for item in items:
        if not isinstance(item, dict):
            label = normalize_label(item)
            conf = None
        else:
            label = normalize_label(get_first(item, ["label", "class", "name", "common_name", "scientific_name", "taxon", "prediction", "category"]))
            conf = normalize_confidence(get_first(item, ["confidence", "score", "probability", "prob", "p"]))
        if label and (best_conf is None or (conf is not None and conf > best_conf)):
            best_label = label
            best_conf = conf
    return best_label, best_conf


def extract_nested_label(rec: Dict[str, Any], parent_keys: Iterable[str]) -> Tuple[str, Optional[float]]:
    for parent in parent_keys:
        if parent not in rec:
            continue
        val = rec[parent]
        if isinstance(val, dict):
            direct_label = normalize_label(get_first(val, ["label", "class", "name", "common_name", "scientific_name", "taxon", "prediction", "category"]))
            direct_conf = normalize_confidence(get_first(val, ["confidence", "score", "probability", "prob", "p"]))
            if direct_label:
                return direct_label, direct_conf
            for list_key in ["predictions", "classes", "labels", "top", "top_k", "candidates"]:
                if list_key in val:
                    label, conf = best_from_prediction_list(val[list_key])
                    if label:
                        return label, conf
        elif isinstance(val, list):
            label, conf = best_from_prediction_list(val)
            if label:
                return label, conf
        else:
            label = normalize_label(val)
            if label:
                return label, None
    return "", None


def file_key_from_record(rec: Dict[str, Any]) -> str:
    val = get_first(rec, ["filepath", "file", "filename", "path", "image", "image_path", "input_path", "location"])
    return normalize_label(val)


def map_record_to_candidate(rec: Dict[str, Any], staged_map: Dict[str, CropCandidate]) -> Optional[CropCandidate]:
    file_key = file_key_from_record(rec)
    if not file_key:
        return None
    possibilities = [file_key, str(Path(file_key)), str(Path(file_key).resolve())]
    try:
        possibilities.append(Path(file_key).name)
    except Exception:
        pass
    for p in possibilities:
        if p in staged_map:
            return staged_map[p]
    return None


def label_is_only_broad_animal(label: str) -> bool:
    cleaned = label.strip().lower()
    return cleaned in {"animal", "1", "1;;;;;;animal", "1f689929-883d-4dae-958c-3d57ab5b6c16;;;;;;animal"} or cleaned.endswith(";;;;;;animal")


def label_parts(label: str) -> List[str]:
    return [part.strip() for part in normalize_label(label).split(";")]


def common_name_from_label(label: str) -> str:
    parts = label_parts(label)
    if len(parts) >= 7 and parts[6]:
        return parts[6].strip()
    return normalize_label(label)


def taxon_rank(label: str) -> str:
    parts = label_parts(label)
    while len(parts) < 7:
        parts.append("")
    common = parts[6].strip().lower()
    if not normalize_label(label):
        return "unavailable"
    if common in {"blank", "human", "animal", "no cv result", "unknown"}:
        return common
    if parts[4] and parts[5]:
        return "species"
    if parts[4]:
        return "genus"
    if parts[3]:
        return "family"
    if parts[2]:
        return "order"
    if parts[1]:
        return "class"
    return "broad"


def label_is_rejectable(label: str) -> bool:
    rank = taxon_rank(label)
    common = common_name_from_label(label).lower()
    cleaned = normalize_label(label).lower()
    return (
        not cleaned
        or rank in {"blank", "human", "animal", "no cv result", "unavailable"}
        or label_is_only_broad_animal(label)
        or common in {"blank", "human", "animal", "no cv result"}
    )


def rank_priority(label: str) -> int:
    rank = taxon_rank(label)
    return {
        "species": 80,
        "genus": 70,
        "family": 60,
        "order": 50,
        "class": 40,
        "broad": 20,
    }.get(rank, 0)


def best_speciesnet_classification(rec: Dict[str, Any]) -> Tuple[str, Optional[float], str]:
    classifications = rec.get("classifications")
    if not isinstance(classifications, dict):
        return "", None, "unavailable"
    classes = classifications.get("classes")
    scores = classifications.get("scores")
    if not isinstance(classes, list):
        return "", None, "unavailable"
    if not isinstance(scores, list):
        scores = [None] * len(classes)

    best_label = ""
    best_score: Optional[float] = None
    best_rank = "unavailable"
    best_weight = -1.0

    for idx, raw_label in enumerate(classes):
        label = normalize_label(raw_label)
        score = normalize_confidence(scores[idx] if idx < len(scores) else None)
        if label_is_rejectable(label):
            continue
        weight = rank_priority(label) + (score or 0.0)
        if weight > best_weight:
            best_label = label
            best_score = score
            best_rank = taxon_rank(label)
            best_weight = weight

    if best_label:
        return best_label, best_score, best_rank

    for idx, raw_label in enumerate(classes):
        label = normalize_label(raw_label)
        common = common_name_from_label(label).lower()
        score = normalize_confidence(scores[idx] if idx < len(scores) else None)
        if common == "bird" or label.endswith(";;;;;bird"):
            return label, score, "class"

    return "", None, "unavailable"



def label_mentions_hummingbird(label: str) -> bool:
    cleaned = normalize_label(label).lower()
    common = common_name_from_label(label).lower()
    return (
        "hummingbird" in cleaned
        or "hummingbird" in common
        or "trochilidae" in cleaned
        or "trochil" in cleaned
    )


def speciesnet_classification_candidates(rec: Dict[str, Any], limit: int = 12) -> List[Dict[str, Any]]:
    classifications = rec.get("classifications")
    if not isinstance(classifications, dict):
        return []

    classes = classifications.get("classes")
    scores = classifications.get("scores")
    if not isinstance(classes, list):
        return []
    if not isinstance(scores, list):
        scores = [None] * len(classes)

    candidates: List[Dict[str, Any]] = []
    for idx, raw_label in enumerate(classes):
        label = normalize_label(raw_label)
        score = normalize_confidence(scores[idx] if idx < len(scores) else None)
        rank = taxon_rank(label)
        common = common_name_from_label(label)
        candidates.append(
            {
                "index": idx,
                "label": label,
                "common_name": common,
                "score": score,
                "rank": rank,
                "rejectable": label_is_rejectable(label),
                "broad_animal_only": label_is_only_broad_animal(label),
                "mentions_hummingbird": label_mentions_hummingbird(label),
            }
        )

    return candidates[:max(limit, 1)]


def summarize_candidate_diagnostics(data: Any, parsed: List[ParsedPrediction]) -> Dict[str, Any]:
    records = iter_prediction_records(data)
    total_classifier_candidates = 0
    hummingbird_candidate_records = 0
    hummingbird_candidate_total = 0
    top_common_counts: Dict[str, int] = {}

    for rec in records:
        candidates = speciesnet_classification_candidates(rec, limit=1000)
        if not candidates:
            continue
        total_classifier_candidates += len(candidates)
        rec_hummingbirds = [c for c in candidates if c.get("mentions_hummingbird")]
        if rec_hummingbirds:
            hummingbird_candidate_records += 1
            hummingbird_candidate_total += len(rec_hummingbirds)
        for candidate in candidates[:5]:
            name = str(candidate.get("common_name") or candidate.get("label") or "").strip() or "unknown"
            top_common_counts[name] = top_common_counts.get(name, 0) + 1

    return {
        "record_count": len(records),
        "parsed_count": len(parsed),
        "total_classifier_candidates_seen": total_classifier_candidates,
        "records_with_hummingbird_candidate": hummingbird_candidate_records,
        "hummingbird_candidate_total": hummingbird_candidate_total,
        "top_common_counts_from_first_5_per_record": dict(
            sorted(top_common_counts.items(), key=lambda item: (-item[1], item[0]))[:25]
        ),
    }

def confidence_band(confidence: Optional[float], review_status: str, high: float, medium: float) -> str:
    if review_status in {"unknown", "unknown_bird"}:
        return review_status
    if confidence is None:
        return "confidence_unknown"
    if confidence >= high:
        return "proposed_high"
    if confidence >= medium:
        return "proposed_low"
    return "weak_guess"


def proposed_candidate_status(review_status: str, band: str) -> str:
    if review_status == "unknown_bird":
        return "unknown_bird"
    if review_status == "unknown":
        return "unknown"
    if band == "proposed_high":
        return "proposed_candidate_high"
    if band == "proposed_low":
        return "proposed_candidate_low"
    if band == "weak_guess":
        return "weak_guess"
    return "proposed_candidate_unscored"


def parse_one_prediction(rec: Dict[str, Any], cand: CropCandidate, high_threshold: float, medium_threshold: float) -> ParsedPrediction:
    broad_label = normalize_label(get_first(rec, ["prediction", "label", "class", "category", "class_name", "taxon", "species"]))
    broad_conf = normalize_confidence(get_first(rec, ["prediction_score", "confidence", "score", "probability", "prob"]))

    classifier_label, classifier_conf, classifier_rank = best_speciesnet_classification(rec)

    if not classifier_label:
        classifier_label, classifier_conf = extract_nested_label(
            rec,
            [
                "classifier",
                "classification",
                "classifications",
                "classifier_prediction",
                "classifier_predictions",
                "species_prediction",
                "species_predictions",
                "speciesnet_classifier",
            ],
        )
        classifier_rank = taxon_rank(classifier_label)

    detector_label, detector_conf = extract_nested_label(
        rec,
        ["detector", "detection", "detections", "detector_prediction", "detector_predictions", "speciesnet_detector"],
    )

    if not classifier_label:
        classifier_label, classifier_conf = extract_nested_label(rec, ["predictions", "classes", "labels", "top", "top_k", "candidates"])

    final_label = classifier_label or broad_label or detector_label or "unavailable"
    final_conf = classifier_conf if classifier_label else broad_conf
    decision_rank = classifier_rank if classifier_label else taxon_rank(final_label)
    decision_label = common_name_from_label(final_label)
    review_status = "proposed"
    if decision_rank in {"blank", "human", "animal", "no cv result", "unavailable"} or label_is_only_broad_animal(final_label):
        review_status = "unknown"
    elif decision_label.lower() == "bird":
        review_status = "unknown_bird"

    band = confidence_band(final_conf, review_status, high_threshold, medium_threshold)
    proposed_candidate = proposed_candidate_status(review_status, band)

    # Safety display rule:
    # SpeciesNet can return very specific but biologically implausible labels on HBMR crops.
    # When a low-confidence species-level guess does not even mention hummingbird/trochilidae,
    # keep the raw label for provenance but surface it as an unsafe/non-HBMR weak guess.
    if band == "weak_guess" and not label_mentions_hummingbird(final_label):
        decision_label = "unknown bird"
        proposed_candidate = "weak_non_hbmr_guess"

    return ParsedPrediction(
        source_id=cand.source_id,
        crop_path=cand.crop_path,
        label=final_label,
        confidence=final_conf,
        broad_label=broad_label,
        broad_confidence=broad_conf,
        classifier_label=classifier_label,
        classifier_confidence=classifier_conf,
        detector_label=detector_label,
        detector_confidence=detector_conf,
        decision_label=decision_label,
        decision_rank=decision_rank,
        review_status=review_status,
        confidence_band=band,
        proposed_candidate=proposed_candidate,
        raw_prediction=rec,
    )


def parse_predictions(data: Any, staged_map: Dict[str, CropCandidate], high_threshold: float, medium_threshold: float) -> List[ParsedPrediction]:
    records = iter_prediction_records(data)
    parsed: List[ParsedPrediction] = []
    for rec in records:
        cand = map_record_to_candidate(rec, staged_map)
        if cand is None:
            continue
        parsed.append(parse_one_prediction(rec, cand, high_threshold, medium_threshold))
    return parsed


def upsert_annotations(conn: sqlite3.Connection, parsed: List[ParsedPrediction]) -> int:
    ensure_species_table(conn)
    existing_cols = set(table_columns(conn, SPECIES_TABLE))
    written = 0
    for pred in parsed:
        values = {
            "crop_path": pred.crop_path,
            "species_label": pred.label,
            "confidence": pred.confidence,
            "broad_label": pred.broad_label,
            "broad_confidence": pred.broad_confidence,
            "classifier_label": pred.classifier_label,
            "classifier_confidence": pred.classifier_confidence,
            "detector_label": pred.detector_label,
            "detector_confidence": pred.detector_confidence,
            "decision_label": pred.decision_label,
            "decision_rank": pred.decision_rank,
            "review_status": pred.review_status,
            "confidence_band": pred.confidence_band,
            "proposed_candidate": pred.proposed_candidate,
            "source_id": pred.source_id,
            "model_name": "SpeciesNet",
            "model_version": "v4.0.3a",
            "status": "complete" if pred.label and pred.label != "unavailable" else "unavailable",
            "raw_json": json.dumps(pred.raw_prediction, ensure_ascii=False, sort_keys=True),
            "updated_at": now_stamp(),
        }
        usable = {k: v for k, v in values.items() if k in existing_cols}
        cols = list(usable.keys())

        update_cols = [c for c in cols if c != "crop_path"]
        if update_cols:
            set_clause = ", ".join([f"{c} = ?" for c in update_cols])
            params = [usable[c] for c in update_cols] + [pred.crop_path]
            cur = conn.execute(f"UPDATE {SPECIES_TABLE} SET {set_clause} WHERE crop_path = ?", params)
            if cur.rowcount and cur.rowcount > 0:
                written += 1
                continue

        placeholders = ", ".join(["?" for _ in cols])
        col_clause = ", ".join(cols)
        params = [usable[c] for c in cols]
        try:
            conn.execute(f"INSERT INTO {SPECIES_TABLE} ({col_clause}) VALUES ({placeholders})", params)
            written += 1
        except sqlite3.IntegrityError:
            if update_cols:
                set_clause = ", ".join([f"{c} = ?" for c in update_cols])
                params = [usable[c] for c in update_cols] + [pred.crop_path]
                conn.execute(f"UPDATE {SPECIES_TABLE} SET {set_clause} WHERE crop_path = ?", params)
                written += 1
    conn.commit()
    return written


def write_debug(settings: Settings, data: Any, parsed: List[ParsedPrediction], stage_counts: Dict[str, int]) -> None:
    try:
        records = iter_prediction_records(data)
        candidate_diagnostics = summarize_candidate_diagnostics(data, parsed)
        sample_records: List[Dict[str, Any]] = []
        for rec in records[:5]:
            sample_records.append({
                "keys": sorted(list(rec.keys())),
                "file_key": file_key_from_record(rec),
                "classification_candidates_top12": speciesnet_classification_candidates(rec, limit=12),
                "raw_sample": rec,
            })
        payload = {
            "app": APP_NAME,
            "version": APP_VERSION,
            "written_at": now_stamp(),
            "country": settings.country,
            "admin1_region": settings.admin1_region,
            "prediction_record_count": len(records),
            "parsed_count": len(parsed),
            "stage_counts": stage_counts,
            "candidate_diagnostics": candidate_diagnostics,
            "parsed_samples": [
                {
                    "crop_path": p.crop_path,
                    "label": p.label,
                    "confidence": p.confidence,
                    "broad_label": p.broad_label,
                    "broad_confidence": p.broad_confidence,
                    "classifier_label": p.classifier_label,
                    "classifier_confidence": p.classifier_confidence,
                    "detector_label": p.detector_label,
                    "detector_confidence": p.detector_confidence,
                    "decision_label": p.decision_label,
                    "decision_rank": p.decision_rank,
                    "review_status": p.review_status,
                    "confidence_band": p.confidence_band,
                    "proposed_candidate": p.proposed_candidate,
                    "classification_candidates_top12": speciesnet_classification_candidates(p.raw_prediction, limit=12),
                }
                for p in parsed[:10]
            ],
            "record_samples": sample_records,
        }
        settings.species_dir.mkdir(parents=True, exist_ok=True)
        settings.debug_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        append_log(settings, f"Failed to write debug JSON: {exc}")


def summarize(status: str, candidates: int, staged: int, written: int, unknown: int, top_result: str, settings: Settings, message: str) -> None:
    safe_print(SUMMARY_BEGIN)
    safe_print("HBMR Species ID Summary")
    safe_print(f"Status: {status}")
    safe_print(f"Crop candidates: {candidates}")
    safe_print(f"Staged crops: {staged}")
    safe_print(f"Annotations written: {written}")
    safe_print(f"Unknown/unavailable: {unknown}")
    safe_print(f"Top result: {top_result}")
    safe_print(f"Predictions JSON: {settings.predictions_json}")
    safe_print(f"Debug JSON: {settings.debug_json}")
    safe_print(f"Geography: country={settings.country or 'none'} admin1_region={settings.admin1_region or 'none'}")
    safe_print(f"Message: {message}")
    safe_print(SUMMARY_END)


def print_header(settings: Settings) -> None:
    safe_print(f"{APP_NAME} {APP_VERSION}")
    safe_print(f"Settings file: {settings.settings_path}")
    safe_print(f"SpeciesNet Python: {settings.species_python}")
    safe_print(f"SpeciesNet Python source: {settings.species_python_source}")
    safe_print(f"Database: {settings.db_path}")
    safe_print(f"Annotation table: {SPECIES_TABLE}")
    safe_print(f"Predictions JSON: {settings.predictions_json}")
    safe_print(f"Debug JSON: {settings.debug_json}")
    safe_print(f"Staging folder: {settings.input_dir}")
    safe_print(f"SpeciesNet geography: country={settings.country or 'none'} admin1_region={settings.admin1_region or 'none'}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HBMR crop-level SpeciesNet annotation wrapper")
    parser.add_argument("--settings", default=None, help="Path to settings.ini")
    parser.add_argument("--limit", type=int, default=25, help="Maximum crop candidates to process")
    parser.add_argument("--force", action="store_true", help="Refresh existing crop_species annotations")
    parser.add_argument("--high-confidence", type=float, default=DEFAULT_HIGH_CONFIDENCE, help="High-confidence proposal threshold")
    parser.add_argument("--medium-confidence", type=float, default=DEFAULT_MEDIUM_CONFIDENCE, help="Low/medium proposal threshold")
    parser.add_argument("--country", default=None, help="SpeciesNet ISO 3166-1 alpha-3 country code, e.g. USA")
    parser.add_argument("--admin1-region", dest="admin1_region", default=None, help="SpeciesNet first-level region, e.g. CA for California")
    parser.add_argument("--keep-staging", action="store_true", help="Keep temporary speciesnet-input files for debugging")
    parser.add_argument("--skip-help-check", action="store_true", help="Skip SpeciesNet help availability check")
    args = parser.parse_args(argv)

    if args.high_confidence < args.medium_confidence:
        safe_print("Warning: high confidence threshold was below medium threshold; swapping values.")
        args.high_confidence, args.medium_confidence = args.medium_confidence, args.high_confidence

    settings = load_settings(args.settings, args.country, args.admin1_region)
    settings.species_dir.mkdir(parents=True, exist_ok=True)
    print_header(settings)
    safe_print(f"Confidence bands: high>={args.high_confidence:.2f} medium>={args.medium_confidence:.2f}")
    append_log(settings, f"Started {APP_NAME} {APP_VERSION} force={args.force} limit={args.limit} high={args.high_confidence} medium={args.medium_confidence} country={settings.country} admin1_region={settings.admin1_region}")

    if not settings.species_python.exists():
        summarize("error", 0, 0, 0, 0, "none", settings, f"SpeciesNet Python not found: {settings.species_python}")
        return 2

    if not args.skip_help_check:
        ok, help_output = speciesnet_help_available(settings)
        if not ok:
            append_log(settings, "SpeciesNet help check failed")
            summarize("error", 0, 0, 0, 0, "none", settings, "SpeciesNet CLI help check failed.")
            return 3

    conn: Optional[sqlite3.Connection] = None
    try:
        conn = connect_db(settings)
        ensure_species_table(conn)
        candidates = select_candidates(conn, max(args.limit, 1), args.force)
    except Exception as exc:
        summarize("error", 0, 0, 0, 0, "none", settings, f"Database/candidate error: {exc}")
        return 4

    safe_print(f"Crop candidates: {len(candidates)}")
    if not candidates:
        summarize("no_candidates", 0, 0, 0, 0, "none", settings, "No crop candidates found.")
        if conn:
            conn.close()
        return 0

    old_deleted = remove_predictions_on_force(settings, args.force)
    if old_deleted:
        safe_print("Force mode: deleted old predictions JSON before SpeciesNet run.")

    staged_map: Dict[str, CropCandidate] = {}
    stage_counts = {"hardlink": 0, "symlink": 0, "copy": 0, "failed": 0}
    try:
        staged_map, stage_counts = stage_candidates(settings, candidates)
        staged_count = len({c.source_id for c in staged_map.values()})
        safe_print(f"Staged crops: {staged_count}")
        safe_print(
            "Staging method counts: "
            f"hardlink={stage_counts['hardlink']} symlink={stage_counts['symlink']} "
            f"copy={stage_counts['copy']} failed={stage_counts['failed']}"
        )
        if staged_count == 0:
            summarize("error", len(candidates), 0, 0, 0, "none", settings, "No crops could be staged.")
            return 5

        returncode, _cmd_text, _output = run_speciesnet(settings)
        if returncode != 0:
            summarize("error", len(candidates), staged_count, 0, staged_count, "none", settings, f"SpeciesNet exited with code {returncode}.")
            return 6

        if not settings.predictions_json.exists():
            summarize("error", len(candidates), staged_count, 0, staged_count, "none", settings, "SpeciesNet did not write predictions JSON.")
            return 7

        data = load_predictions(settings.predictions_json)
        parsed = parse_predictions(data, staged_map, args.high_confidence, args.medium_confidence)
        write_debug(settings, data, parsed, stage_counts)
        diagnostics = summarize_candidate_diagnostics(data, parsed)

        if conn is None:
            raise RuntimeError("Database connection was not available for annotation write.")
        written = upsert_annotations(conn, parsed)
        unknown = sum(1 for p in parsed if p.review_status in {"unknown", "unknown_bird"} or not p.label or p.label == "unavailable")
        broad_only = sum(1 for p in parsed if label_is_only_broad_animal(p.label))
        proposed = sum(1 for p in parsed if p.review_status == "proposed")
        proposed_high = sum(1 for p in parsed if p.confidence_band == "proposed_high")
        proposed_low = sum(1 for p in parsed if p.confidence_band == "proposed_low")
        weak_guess = sum(1 for p in parsed if p.confidence_band == "weak_guess")
        unknown_bird = sum(1 for p in parsed if p.review_status == "unknown_bird")
        weak_non_hbmr_guess = sum(1 for p in parsed if p.proposed_candidate == "weak_non_hbmr_guess")
        top = "none"
        best = sorted(parsed, key=lambda p: rank_priority(p.label) + (p.confidence or 0.0), reverse=True)
        if best:
            p0 = best[0]
            conf = "confidence n/a" if p0.confidence is None else f"confidence {p0.confidence:.4f}"
            top = f"{p0.decision_label} [{p0.decision_rank}] / {conf}"
            top += f" | band: {p0.confidence_band}"
            top += f" | review: {p0.proposed_candidate}"
            top += f" | raw: {p0.label}"
            if p0.broad_label and p0.broad_label != p0.label:
                top += f" | broad: {p0.broad_label}"

        message = (
            "Species annotation complete; "
            f"proposed={proposed}, proposed_high={proposed_high}, "
            f"proposed_low={proposed_low}, weak_guess={weak_guess}, "
            f"unknown_bird={unknown_bird}, unknown={unknown}, "
            f"weak_non_hbmr_guess={weak_non_hbmr_guess}, "
            f"records_with_hummingbird_candidate={diagnostics.get('records_with_hummingbird_candidate', 0)}."
        )
        if broad_only and broad_only == len(parsed):
            message = "SpeciesNet completed, but parsed labels are broad animal-only. Check Debug JSON for classifier fields."

        summarize("complete", len(candidates), staged_count, written, unknown, top, settings, message)
        return 0

    except Exception as exc:
        append_log(settings, f"Unhandled error: {exc}")
        summarize("error", len(candidates), 0, 0, len(candidates), "none", settings, f"Unhandled error: {exc}")
        return 9
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass
        if not args.keep_staging:
            shutil.rmtree(settings.input_dir, ignore_errors=True)
            safe_print("Cleaned staging folder.")
        append_log(settings, "Finished speciesid run")


if __name__ == "__main__":
    raise SystemExit(main())
