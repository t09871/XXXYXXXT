# cleanupGUI-v4.0.2.py | HBMR / Birdbill v4.0.2 | 2026-06-24 PDT
# Canonical human identity cleanup GUI.
#
# v4.0.2 change:
# - removes return-inside-finally warning from Refinement Lab standard-set save path
# - paired with lightgluetest.py v0.2.1 filename-stem cap for Windows LightGlue report path crashes
#
# v4.0.1 change:
# - adds live/debounced Crop Refinement Lab preview behavior
# - adds recipe presets for multi-view evidence experiments such as body-tight and gorget/head-tight
# - saves refined crops into recipe-specific subfolders with JSON sidecar parameters
# - adds a small standard-set generator for paired body/gorget refinement testing without database writes
# Uses crop_queue.identity as canonical identity field.
#
# v4.0.0 change:
# - adds Crop Refinement Lab inside Auto-sorting workspace
# - creates derived refined crop artifacts in output/refined-crops while preserving raw crop evidence
# - supports recipe-style preprocessing experiments before LightGlue/DINO testing
# - lets latest saved refined crop be used as LightGlue Image A or B without command line/drag-drop
# - keeps refinement outputs file-only for this first pass: no database writes, no identity assignment
#
# v3.1.10 change:
# - adds GUI-based LightGlue local-feature testing inside Auto-sorting workspace
# - keeps LightGlue read-only: no database writes, no identity assignment, no ingestion integration
# - runs existing lightgluetest.py from GUI so testing no longer depends on command line or drag/drop
#
# v3.1.9 change:
# - migrates provisional display language from Bird##### to Bird#####
# - imports autoname_sort_key so GUI identity ordering follows autoname.py instead of raw string order
# - separates Manual Sorting J=junk from F=false positive for dataset integrity
# - treats sampled frames as future cache/retention-policy issue, not permanent user-facing profile truth
#
# v3.1.7 change:
# - adds Manual Sorting tab with keyboard-friendly slideshow workflow for Raw Groups, Sandbox, and True Names
# - adds shortcuts: Space skip, L low-quality bird, M multibird, J junk/non-bird, A AI/suspicious placeholder, S sandbox, T true name, R raw, B back
# v3.1.7 change:
# - adds Manual Sorting tab with keyboard-friendly slideshow workflow for Raw Groups, Sandbox, and True Names
# - adds shortcuts: Space skip, L low quality, N false positive/non-bird, S sandbox, T true name, R return to raw, B back
# - keeps each mutation explicit, logged, backed up, and routed through existing lifecycle helpers
# v3.1.6 change:
# - improves Move To True Names UX with New vs Existing choice before mutation
# - adds existing True Name dropdown so canonical names do not need to be typed perfectly every time
# - allows selected crops or whole current identity to be moved into an existing true-name lane with explicit confirmation
# - keeps True Names backed by identity_status='active' and review_status='reviewed'
# v3.1.5 change:
# - hardens Undo Last Action with restore verification and skips undo/pre-undo backup noise
# - adds details/thumbnails toggles to Stage Names Sandbox and True Names crop views
# - adds guarded lane-removal actions for sandbox/true-name crops and profiles back to Raw Groups
# - keeps removals non-destructive: crop files and rows are preserved, identity_status returns to provisional
# v3.1.4 change:
# - turns True Names into a real filtered workspace instead of placeholder text
# - hides fully sandbox/true-name identities from Raw Groups so remaining raw/provisional work is less cluttered
# - adds True Names refresh/list/crop inspection view backed by identity_status='active'
# - adds first practical Undo Last Action button using the database backup path logged for the latest cleanup action
# - keeps canonical identity field as crop_queue.identity and does not change schema
# v3.1.3 change:
# - cleans up Identity Lab button language around identity lifecycle actions
# - replaces Bird##### move/merge wording with Move To Sandbox and Move To True Names actions
# - hides 3 Bird Compare from the visible Raw Groups workflow; tabled as future ML/multicandidate comparison work
# - adds explicit logged selected-crop and selected-identity promotion paths for sandbox/true-name workflow
# v3.1.2 change:
# - renames the main Reconciliation tab label to Identity Lab while keeping cleanupGUI filename for now
# - adds Identity Lab sub-tabs: Raw Groups, Stage Names Sandbox, and True Names
# - adds logged sandbox action path for DINO proposal crops
# - lets selected DINO proposals send source/target evidence crops into the sandbox bucket
# - adds sandbox refresh/list view so staged crops can be inspected without changing true identities
# - keeps all true-name/canonical identity actions manual and logged
# v3.1.1 change:
# - keeps cleanupGUI filename for now; renaming deferred until contract migration pass
# - moves SpeciesID/SpeciesNet runner out of main toolbar into its own tab
# - adds Auto-sorting module sub-tabs so DINO is one module workspace, not the whole sorter surface
# - adds DINO results view toggle: detail table vs thumbnail evidence view
# - adds read-only suggested_action to DINO proposal output
# - adds beta-core AI Detection tab skeleton for future conservative fake/AI-video cues
#
# v3.1.0 change:
# - starts Birdbill v3 sorter-era numbering
# - keeps Auto-sorting workspace read-only
# - improves DINO sorter workflow before WBIA plugin work
# - adds direct profile selection inside Auto-sorting workspace
# - adds single-anchor profile analysis for large profiles
# - adds selected-profile set pairwise analysis
# - adds current reconciliation profile analysis
# - keeps threshold slider + Analyze button, not live recomputation
# - does not add drag-and-drop merging
#
# v2.5.19 change:
# - renames the overall GUI/product surface to Birdbill
# - renames the Identity Lab tab to Auto-sorting workspace
# - adds first practical DINO similarity sorting analyzer using existing visual_embeddings
# - supports selected-profile, current-profile, and all-visible-profile analysis scopes
# - keeps sorting analysis read-only; it proposes compare targets but does not mutate identities
#
# Important architecture rule:
# models propose; GUI compares; user authorizes; database records.

import configparser
import os
import json
import shutil
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    from PIL import Image, ImageTk, ImageFilter, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    from autoname import allocate_bird_name, autoname_sort_key
    AUTONAME_AVAILABLE = True
except Exception:
    AUTONAME_AVAILABLE = False

    def autoname_sort_key(identity):
        text = str(identity or "").strip()
        return (1, text.lower())


APP_VERSION = "Birdbill / HBMR cleanupGUI v4.0.2"
PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "output" / "database" / "mr-review.db"
BACKUP_DIR = PROJECT_ROOT / "output" / "database" / "backups"
JUNK_ARCHIVE_DIR = PROJECT_ROOT / "output" / "junk-crops"
REFINED_CROPS_DIR = PROJECT_ROOT / "output" / "refined-crops"

REFINEMENT_RECIPE_PRESETS = {
    "current/custom": None,
    "raw-square-control-v0": {
        "crop_percent": 0.0,
        "focus_x": 0.0,
        "focus_y": 0.0,
        "square": True,
        "background": "none",
        "blur_radius": 0.0,
        "resize_max_side": 512,
    },
    "center-tight-v0": {
        "crop_percent": 18.0,
        "focus_x": 0.0,
        "focus_y": 0.0,
        "square": True,
        "background": "blur outside ellipse",
        "blur_radius": 8.0,
        "resize_max_side": 512,
    },
    "body-tight-v0": {
        "crop_percent": 30.0,
        "focus_x": 0.0,
        "focus_y": 8.0,
        "square": True,
        "background": "blur outside ellipse",
        "blur_radius": 10.0,
        "resize_max_side": 512,
    },
    "gorget-head-tight-v0": {
        "crop_percent": 36.0,
        "focus_x": 0.0,
        "focus_y": -18.0,
        "square": True,
        "background": "blur outside ellipse",
        "blur_radius": 10.0,
        "resize_max_side": 512,
    },
    "background-suppressed-v0": {
        "crop_percent": 22.0,
        "focus_x": 0.0,
        "focus_y": 0.0,
        "square": True,
        "background": "neutral fill outside ellipse",
        "blur_radius": 0.0,
        "resize_max_side": 512,
    },
}

REFINEMENT_STANDARD_SET = ("body-tight-v0", "gorget-head-tight-v0")
PROFILES_SCRIPT = PROJECT_ROOT / "profiles.py"
SPECIES_SCRIPT = PROJECT_ROOT / "speciesid.py"
LIGHTGLUE_SCRIPT = PROJECT_ROOT / "lightgluetest.py"
SETTINGS_FILE = PROJECT_ROOT / "settings.ini"

THUMB_SIZE = 145
GRID_COLUMNS = 5
COMPARE_THUMBS_PER_IDENTITY = 12
MULTIBIRD_GROUP = "[MULTIBIRD CROPS]"


def identity_display_sort_key(value):
    return autoname_sort_key(value)


def row_identity_sort_key(row):
    try:
        identity = row["identity"]
    except Exception:
        identity = ""
    return identity_display_sort_key(identity)


def sort_rows_by_identity(rows):
    return sorted(rows, key=lambda row: (row_identity_sort_key(row), str(row["identity"] or ""), int(row["id"]) if "id" in row.keys() else 0, str(row["crop_path"] or "") if "crop_path" in row.keys() else ""))


def now_stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn, table_name):
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.OperationalError:
        return []
    return [row["name"] for row in rows]


def ensure_column(conn, table_name, column_name, column_def):
    cols = table_columns(conn, table_name)
    if column_name not in cols:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")


def ensure_schema():
    with connect_db() as conn:
        cols = table_columns(conn, "crop_queue")
        required = ["id", "crop_path", "identity", "review_status", "identity_status"]
        missing = [c for c in required if c not in cols]
        if missing:
            raise RuntimeError(
                "Missing canonical crop_queue columns:\n\n"
                + "\n".join(missing)
                + "\n\nStop and reconcile canon.txt/database schema before using cleanupGUI.py."
            )

        ensure_column(conn, "crop_queue", "training_label", "TEXT")
        ensure_column(conn, "crop_queue", "cleanup_notes", "TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cleanup_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                source_identity TEXT,
                target_identity TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identity_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                crop_id INTEGER,
                crop_path TEXT,
                old_identity TEXT,
                new_identity TEXT,
                action_type TEXT NOT NULL,
                notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crop_species (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crop_path TEXT NOT NULL UNIQUE,
                species_guess TEXT,
                species_confidence REAL,
                model_name TEXT,
                model_version TEXT,
                created_at TEXT NOT NULL,
                notes TEXT
            )
            """
        )
        conn.commit()


def backup_database(reason):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        return None
    safe_reason = "".join(c for c in reason if c.isalnum() or c in "-_")[:40]
    backup_path = BACKUP_DIR / f"mr-review-{now_stamp()}-{safe_reason}.db"
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def log_action(action_type, source_identity=None, target_identity=None, details=None):
    details_json = json.dumps(details or {}, indent=2)
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO cleanup_actions
            (action_type, source_identity, target_identity, details_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (action_type, source_identity, target_identity, details_json, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def log_identity_history(rows, action_type, old_identity_key="identity", new_identity=None, notes=None):
    if not rows:
        return
    timestamp = datetime.now().isoformat(timespec="seconds")
    notes_text = json.dumps(notes or {}, indent=2)
    with connect_db() as conn:
        for row in rows:
            if isinstance(row, sqlite3.Row):
                keys = row.keys()
                crop_id = row["id"] if "id" in keys else None
                crop_path = row["crop_path"] if "crop_path" in keys else None
                old_identity = row[old_identity_key] if old_identity_key in keys else None
            else:
                crop_id = row.get("id")
                crop_path = row.get("crop_path")
                old_identity = row.get(old_identity_key)
            conn.execute(
                """
                INSERT INTO identity_history
                (timestamp, crop_id, crop_path, old_identity, new_identity, action_type, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (timestamp, crop_id, crop_path, old_identity, new_identity if new_identity is not None else old_identity, action_type, notes_text),
            )
        conn.commit()


def species_enabled():
    config = configparser.ConfigParser()
    config.read(SETTINGS_FILE)
    try:
        return config.getboolean("species", "EnableSpeciesID", fallback=False)
    except Exception:
        return False


def extract_species_summary(output_text):
    begin_marker = "HBMR_SPECIES_SUMMARY_BEGIN"
    end_marker = "HBMR_SPECIES_SUMMARY_END"
    if not output_text:
        return ""
    begin = output_text.find(begin_marker)
    end = output_text.find(end_marker)
    if begin != -1 and end != -1 and end > begin:
        return output_text[begin + len(begin_marker):end].strip()
    lines = [line.rstrip() for line in output_text.splitlines() if line.strip()]
    return "\n".join(lines[-20:]).strip() if lines else ""


def get_identities(include_false_positive=False, include_multibird=True, include_low_quality=True):
    if not DB_PATH.exists():
        return []
    query = """
        SELECT
            identity,
            COUNT(*) AS crop_count,
            SUM(CASE WHEN identity_status = 'false_positive' THEN 1 ELSE 0 END) AS fp_count,
            SUM(CASE WHEN identity_status = 'multibird' THEN 1 ELSE 0 END) AS multibird_count,
            SUM(CASE WHEN identity_status = 'low_quality' THEN 1 ELSE 0 END) AS low_quality_count,
            SUM(CASE WHEN identity_status = 'sandbox' THEN 1 ELSE 0 END) AS sandbox_count,
            SUM(CASE WHEN identity_status = 'active' THEN 1 ELSE 0 END) AS active_count,
            AVG(CASE WHEN visual_score IS NOT NULL AND visual_score != '' THEN CAST(visual_score AS REAL) ELSE NULL END) AS avg_score
        FROM crop_queue
        WHERE identity IS NOT NULL AND identity != ''
        GROUP BY identity
        ORDER BY identity
    """
    with connect_db() as conn:
        rows = conn.execute(query).fetchall()
        multibird_total = conn.execute("SELECT COUNT(*) FROM crop_queue WHERE identity_status = 'multibird'").fetchone()[0]
    rows = sorted(rows, key=lambda row: identity_display_sort_key(row["identity"]))
    results = []
    if multibird_total:
        results.append({"identity": MULTIBIRD_GROUP, "crop_count": multibird_total, "fp_count": 0, "multibird_count": multibird_total, "low_quality_count": 0, "avg_score": None, "special_group": "multibird"})
    for row in rows:
        fp_count = row["fp_count"] or 0
        multibird_count = row["multibird_count"] or 0
        low_quality_count = row["low_quality_count"] or 0
        sandbox_count = row["sandbox_count"] or 0
        active_count = row["active_count"] or 0
        crop_count = row["crop_count"]
        if active_count >= crop_count:
            continue
        if sandbox_count >= crop_count:
            continue
        if fp_count >= crop_count and not include_false_positive:
            continue
        if multibird_count >= crop_count and not include_multibird:
            continue
        if low_quality_count >= crop_count and not include_low_quality:
            continue
        results.append({
            "identity": row["identity"],
            "crop_count": crop_count,
            "fp_count": fp_count,
            "multibird_count": multibird_count,
            "low_quality_count": low_quality_count,
            "sandbox_count": sandbox_count,
            "active_count": active_count,
            "avg_score": row["avg_score"],
            "special_group": None,
        })
    return results


def get_crops(identity, limit=None):
    limit_clause = ""
    params = []
    if identity == MULTIBIRD_GROUP:
        where_clause = "identity_status = 'multibird'"
    else:
        where_clause = "identity = ?"
        params.append(identity)
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    query = f"""
        SELECT id, crop_path, identity, identity_status, review_status, training_label, cleanup_notes,
               visual_score, visual_decision, visual_matched_crop_path
        FROM crop_queue
        WHERE {where_clause}
        ORDER BY identity ASC,
            CASE
                WHEN identity_status = 'multibird' THEN 0
                WHEN identity_status = 'low_quality' THEN 1
                WHEN identity_status = 'false_positive' THEN 3
                ELSE 2
            END ASC,
            CASE WHEN visual_score IS NULL OR visual_score = '' THEN 999 ELSE CAST(visual_score AS REAL) END ASC,
            crop_path ASC
        {limit_clause}
    """
    with connect_db() as conn:
        return conn.execute(query, params).fetchall()


def identity_exists(identity):
    if identity == MULTIBIRD_GROUP:
        return True
    with connect_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM crop_queue WHERE identity = ?", (identity,)).fetchone()[0] > 0


def update_visual_embeddings_for_paths(crop_paths, new_identity):
    if not crop_paths:
        return 0
    with connect_db() as conn:
        cols = table_columns(conn, "visual_embeddings")
        if "crop_path" not in cols or "identity" not in cols:
            return 0
        qmarks = ",".join("?" for _ in crop_paths)
        cur = conn.execute(f"UPDATE visual_embeddings SET identity = ? WHERE crop_path IN ({qmarks})", [new_identity] + crop_paths)
        conn.commit()
        return cur.rowcount


def merge_identity(source_identity, target_identity):
    if source_identity == target_identity or source_identity == MULTIBIRD_GROUP:
        return
    backup_path = backup_database("merge")
    with connect_db() as conn:
        source_rows = conn.execute("SELECT id, crop_path, identity FROM crop_queue WHERE identity = ?", (source_identity,)).fetchall()
        before_count = len(source_rows)
        conn.execute("UPDATE crop_queue SET identity = ? WHERE identity = ?", (target_identity, source_identity))
        try:
            conn.execute("UPDATE visual_embeddings SET identity = ? WHERE identity = ?", (target_identity, source_identity))
        except sqlite3.OperationalError:
            pass
        conn.commit()
    log_identity_history(source_rows, "merge_identity", new_identity=target_identity, notes={"source_identity": source_identity, "target_identity": target_identity, "backup_path": str(backup_path) if backup_path else None})
    log_action("merge_identity", source_identity, target_identity, {"moved_crop_count": before_count, "backup_path": str(backup_path) if backup_path else None})


def mark_identity_status(identity, status, action_type, label="", note=""):
    backup_path = backup_database(action_type)
    with connect_db() as conn:
        if identity == MULTIBIRD_GROUP:
            where_clause = "identity_status = 'multibird'"
            params = []
        else:
            where_clause = "identity = ?"
            params = [identity]
        affected_rows = conn.execute(f"SELECT id, crop_path, identity FROM crop_queue WHERE {where_clause}", params).fetchall()
        conn.execute(
            f"""
            UPDATE crop_queue
            SET identity_status = ?, training_label = ?, cleanup_notes = CASE WHEN ? = '' THEN cleanup_notes ELSE ? END
            WHERE {where_clause}
            """,
            [status, label, note, note] + params,
        )
        conn.commit()
    log_identity_history(affected_rows, action_type, notes={"source_identity": identity, "status": status, "label": label, "note": note, "backup_path": str(backup_path) if backup_path else None})
    log_action(action_type, identity, details={"affected_crop_count": len(affected_rows), "status": status, "label": label, "note": note, "backup_path": str(backup_path) if backup_path else None})


def mark_crops_status(crop_ids, source_identity, status, action_type, label="", note=""):
    if not crop_ids:
        return
    backup_path = backup_database(action_type)
    qmarks = ",".join("?" for _ in crop_ids)
    with connect_db() as conn:
        rows = conn.execute(f"SELECT id, crop_path, identity FROM crop_queue WHERE id IN ({qmarks})", crop_ids).fetchall()
        conn.execute(
            f"""
            UPDATE crop_queue
            SET identity_status = ?, training_label = ?, cleanup_notes = CASE WHEN ? = '' THEN cleanup_notes ELSE ? END
            WHERE id IN ({qmarks})
            """,
            [status, label, note, note] + crop_ids,
        )
        conn.commit()
    log_identity_history(rows, action_type, notes={"source_identity": source_identity, "status": status, "label": label, "note": note, "backup_path": str(backup_path) if backup_path else None})
    log_action(action_type, source_identity, details={"crop_ids": crop_ids, "crop_count": len(crop_ids), "status": status, "label": label, "note": note, "backup_path": str(backup_path) if backup_path else None})


def crop_ids_for_paths(crop_paths):
    clean_paths = [str(x) for x in crop_paths if x]
    if not clean_paths:
        return []
    qmarks = ",".join("?" for _ in clean_paths)
    with connect_db() as conn:
        rows = conn.execute(f"SELECT id FROM crop_queue WHERE crop_path IN ({qmarks})", clean_paths).fetchall()
    return [row["id"] for row in rows]


def get_sandbox_crops(limit=500):
    if not DB_PATH.exists():
        return []
    with connect_db() as conn:
        return conn.execute(
            """
            SELECT id, crop_path, identity, identity_status, review_status, training_label, cleanup_notes,
                   visual_score, visual_decision, visual_matched_crop_path
            FROM crop_queue
            WHERE identity_status = 'sandbox'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()




def get_true_name_identities():
    if not DB_PATH.exists():
        return []
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                identity,
                COUNT(*) AS crop_count,
                AVG(CASE WHEN visual_score IS NOT NULL AND visual_score != '' THEN CAST(visual_score AS REAL) ELSE NULL END) AS avg_score
            FROM crop_queue
            WHERE identity_status = 'active' AND identity IS NOT NULL AND identity != ''
            GROUP BY identity
            ORDER BY identity
            """
        ).fetchall()
    return sorted(rows, key=lambda row: identity_display_sort_key(row["identity"]))


def get_true_name_crops(identity=None, limit=1000):
    if not DB_PATH.exists():
        return []
    params = []
    where_clause = "identity_status = 'active'"
    if identity:
        where_clause += " AND identity = ?"
        params.append(identity)
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    with connect_db() as conn:
        return conn.execute(
            f"""
            SELECT id, crop_path, identity, identity_status, review_status, training_label, cleanup_notes,
                   visual_score, visual_decision, visual_matched_crop_path
            FROM crop_queue
            WHERE {where_clause}
            ORDER BY identity ASC, crop_path ASC
            {limit_clause}
            """,
            params,
        ).fetchall()



def get_manual_sort_crops(source_lane, limit=2000):
    if not DB_PATH.exists():
        return []
    lane = source_lane or "Raw Groups"
    if lane == "Stage Names Sandbox":
        where_clause = "identity_status = 'sandbox'"
        params = []
    elif lane == "True Names":
        where_clause = "identity_status = 'active'"
        params = []
    else:
        where_clause = "(identity_status IS NULL OR identity_status NOT IN ('sandbox', 'active', 'false_positive', 'junk', 'low_quality', 'multibird', 'ai_suspicious'))"
        params = []
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT id, crop_path, identity, identity_status, review_status, training_label, cleanup_notes,
                   visual_score, visual_decision, visual_matched_crop_path
            FROM crop_queue
            WHERE {where_clause}
            ORDER BY identity ASC, id ASC, crop_path ASC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
    return sort_rows_by_identity(rows)


def get_crop_by_id(crop_id):
    with connect_db() as conn:
        return conn.execute(
            """
            SELECT id, crop_path, identity, identity_status, review_status, training_label, cleanup_notes,
                   visual_score, visual_decision, visual_matched_crop_path
            FROM crop_queue
            WHERE id = ?
            """,
            (crop_id,),
        ).fetchone()

def true_name_identity_names():
    return [row["identity"] for row in get_true_name_identities()]


class TrueNameTargetDialog:
    def __init__(self, parent, title, prompt, default_new_name=""):
        self.result = None
        self.existing_names = true_name_identity_names()
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.resizable(False, False)

        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=prompt, wraplength=520).pack(anchor="w", pady=(0, 10))

        self.mode = tk.StringVar(value="existing" if self.existing_names else "new")
        self.existing_value = tk.StringVar(value=self.existing_names[0] if self.existing_names else "")
        self.new_value = tk.StringVar(value=default_new_name or "")

        ttk.Radiobutton(outer, text="Use existing True Name", variable=self.mode, value="existing", command=self.update_state).pack(anchor="w")
        self.existing_combo = ttk.Combobox(outer, textvariable=self.existing_value, values=self.existing_names, state="readonly", width=48)
        self.existing_combo.pack(anchor="w", fill="x", pady=(2, 10))

        ttk.Radiobutton(outer, text="Create new True Name", variable=self.mode, value="new", command=self.update_state).pack(anchor="w")
        self.new_entry = ttk.Entry(outer, textvariable=self.new_value, width=52)
        self.new_entry.pack(anchor="w", fill="x", pady=(2, 10))

        if not self.existing_names:
            ttk.Label(outer, text="No existing True Names yet. Create the first one below.", wraplength=520).pack(anchor="w", pady=(0, 8))

        btns = ttk.Frame(outer)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(btns, text="Continue", command=self.ok).pack(side="right", padx=(0, 8))

        self.window.bind("<Return>", lambda event: self.ok())
        self.window.bind("<Escape>", lambda event: self.cancel())
        self.update_state()
        self.center(parent)
        if self.mode.get() == "new":
            self.new_entry.focus_set()
            self.new_entry.selection_range(0, tk.END)
        else:
            self.existing_combo.focus_set()
        parent.wait_window(self.window)

    def center(self, parent):
        self.window.update_idletasks()
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (self.window.winfo_width() // 2)
            y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (self.window.winfo_height() // 2)
            self.window.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def update_state(self):
        existing_state = "readonly" if self.mode.get() == "existing" and self.existing_names else "disabled"
        new_state = "normal" if self.mode.get() == "new" else "disabled"
        self.existing_combo.configure(state=existing_state)
        self.new_entry.configure(state=new_state)

    def ok(self):
        mode = self.mode.get()
        if mode == "existing":
            value = self.existing_value.get().strip()
            if not value:
                messagebox.showinfo("True Names", "Choose an existing True Name or switch to Create new True Name.", parent=self.window)
                return
        else:
            value = self.new_value.get().strip()
            if not value:
                messagebox.showinfo("True Names", "New True Name cannot be blank.", parent=self.window)
                return
        if value == MULTIBIRD_GROUP:
            messagebox.showerror("True Names", "The multibird special group cannot be used as a True Name.", parent=self.window)
            return
        self.result = {"mode": mode, "name": value}
        self.window.destroy()

    def cancel(self):
        self.result = None
        self.window.destroy()


def ask_true_name_target(parent, prompt, default_new_name=""):
    dialog = TrueNameTargetDialog(parent, "Move to True Names", prompt, default_new_name)
    return dialog.result


def latest_cleanup_action_with_backup():
    if not DB_PATH.exists():
        return None
    with connect_db() as conn:
        try:
            rows = conn.execute(
                """
                SELECT id, action_type, source_identity, target_identity, details_json, created_at
                FROM cleanup_actions
                ORDER BY id DESC
                LIMIT 50
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return None
    for row in rows:
        action_type = row["action_type"] or ""
        if action_type.startswith("undo_") or action_type.startswith("pre_undo"):
            continue
        try:
            details = json.loads(row["details_json"] or "{}")
        except Exception:
            details = {}
        backup_path = details.get("backup_path")
        if backup_path and Path(backup_path).exists():
            return {
                "id": row["id"],
                "action_type": row["action_type"],
                "source_identity": row["source_identity"],
                "target_identity": row["target_identity"],
                "created_at": row["created_at"],
                "backup_path": backup_path,
            }
    return None


def restore_database_backup(backup_path, reason="undo-last-action"):
    if not backup_path:
        raise ValueError("No backup path supplied.")
    backup = Path(backup_path)
    if not backup.exists():
        raise FileNotFoundError(str(backup))
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    pre_undo_backup = backup_database(reason)
    shutil.copyfile(str(backup), str(DB_PATH))
    with sqlite3.connect(DB_PATH) as conn:
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if check != "ok":
        raise RuntimeError(f"Restored database failed integrity check: {check}")
    return pre_undo_backup


def reset_crop_ids_to_raw(crop_ids, source_lane, action_type):
    if not crop_ids:
        return 0
    backup_path = backup_database(action_type)
    qmarks = ",".join("?" for _ in crop_ids)
    with connect_db() as conn:
        rows = conn.execute(f"SELECT id, crop_path, identity FROM crop_queue WHERE id IN ({qmarks})", crop_ids).fetchall()
        conn.execute(
            f"""
            UPDATE crop_queue
            SET identity_status = 'provisional', review_status = 'auto', training_label = '',
                cleanup_notes = CASE WHEN cleanup_notes IS NULL OR cleanup_notes = '' THEN ? ELSE cleanup_notes || ? END
            WHERE id IN ({qmarks})
            """,
            [f"returned to raw from {source_lane}", f"; returned to raw from {source_lane}"] + crop_ids,
        )
        conn.commit()
    log_identity_history(rows, action_type, notes={"source_lane": source_lane, "crop_ids": crop_ids, "backup_path": str(backup_path) if backup_path else None})
    log_action(action_type, source_lane, details={"crop_ids": crop_ids, "crop_count": len(crop_ids), "backup_path": str(backup_path) if backup_path else None})
    return len(rows)


def reset_identity_lane_to_raw(identity, required_status, source_lane, action_type):
    if not identity:
        return 0
    backup_path = backup_database(action_type)
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT id, crop_path, identity FROM crop_queue WHERE identity = ? AND identity_status = ?",
            (identity, required_status),
        ).fetchall()
        conn.execute(
            """
            UPDATE crop_queue
            SET identity_status = 'provisional', review_status = 'auto', training_label = '',
                cleanup_notes = CASE WHEN cleanup_notes IS NULL OR cleanup_notes = '' THEN ? ELSE cleanup_notes || ? END
            WHERE identity = ? AND identity_status = ?
            """,
            (f"returned to raw from {source_lane}", f"; returned to raw from {source_lane}", identity, required_status),
        )
        conn.commit()
    log_identity_history(rows, action_type, notes={"source_identity": identity, "source_lane": source_lane, "backup_path": str(backup_path) if backup_path else None})
    log_action(action_type, identity, details={"affected_crop_count": len(rows), "source_lane": source_lane, "backup_path": str(backup_path) if backup_path else None})
    return len(rows)

def add_crop_paths_to_sandbox(crop_paths, source_identity, note):
    crop_ids = crop_ids_for_paths(crop_paths)
    if not crop_ids:
        return 0
    mark_crops_status(crop_ids, source_identity, "sandbox", "add_crops_to_stage_names_sandbox", "stage_names_sandbox", note)
    return len(crop_ids)


def move_crops_to_identity(crop_ids, source_identity, target_identity, action_type):
    if not crop_ids:
        return
    move_crops_to_identity_lifecycle(crop_ids, source_identity, target_identity, "provisional", "auto", action_type)


def move_crops_to_identity_lifecycle(crop_ids, source_identity, target_identity, identity_status, review_status, action_type):
    if not crop_ids:
        return
    backup_path = backup_database(action_type)
    qmarks = ",".join("?" for _ in crop_ids)
    with connect_db() as conn:
        crop_rows = conn.execute(f"SELECT id, crop_path, identity FROM crop_queue WHERE id IN ({qmarks})", crop_ids).fetchall()
        crop_paths = [row["crop_path"] for row in crop_rows]
        conn.execute(
            f"""
            UPDATE crop_queue
            SET identity = ?, identity_status = ?, review_status = ?
            WHERE id IN ({qmarks})
            """,
            [target_identity, identity_status, review_status] + crop_ids,
        )
        conn.commit()
    visual_updates = update_visual_embeddings_for_paths(crop_paths, target_identity)
    log_identity_history(crop_rows, action_type, new_identity=target_identity, notes={"source_identity": source_identity, "target_identity": target_identity, "identity_status": identity_status, "review_status": review_status, "visual_embedding_rows_updated": visual_updates, "backup_path": str(backup_path) if backup_path else None})
    log_action(action_type, source_identity, target_identity, {"crop_ids": crop_ids, "crop_count": len(crop_ids), "identity_status": identity_status, "review_status": review_status, "visual_embedding_rows_updated": visual_updates, "backup_path": str(backup_path) if backup_path else None})


def rename_identity_profile(source_identity, target_identity):
    if not source_identity or not target_identity or source_identity == target_identity:
        return 0
    if source_identity == MULTIBIRD_GROUP:
        raise ValueError("The multibird special group cannot be renamed.")
    target_identity = target_identity.strip()
    if not target_identity:
        raise ValueError("Profile name cannot be blank.")
    if identity_exists(target_identity):
        raise ValueError(f"{target_identity} already exists.")
    backup_path = backup_database("name-profile")
    with connect_db() as conn:
        rows = conn.execute("SELECT id, crop_path, identity FROM crop_queue WHERE identity = ?", (source_identity,)).fetchall()
        crop_paths = [row["crop_path"] for row in rows]
        if not rows:
            return 0
        conn.execute("UPDATE crop_queue SET identity = ? WHERE identity = ?", (target_identity, source_identity))
        conn.commit()
    visual_updates = update_visual_embeddings_for_paths(crop_paths, target_identity)
    log_identity_history(rows, "name_identity_profile", new_identity=target_identity, notes={"source_identity": source_identity, "target_identity": target_identity, "visual_embedding_rows_updated": visual_updates, "backup_path": str(backup_path) if backup_path else None})
    log_action("name_identity_profile", source_identity, target_identity, {"affected_crop_count": len(rows), "visual_embedding_rows_updated": visual_updates, "backup_path": str(backup_path) if backup_path else None})
    return len(rows)


def parse_embedding_json(value):
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    if isinstance(parsed, dict):
        for key in ("embedding", "vector", "values"):
            if key in parsed and isinstance(parsed[key], list):
                parsed = parsed[key]
                break
    if not isinstance(parsed, list):
        return None
    out = []
    for item in parsed:
        try:
            out.append(float(item))
        except Exception:
            return None
    return out if out else None


def cosine_similarity(vec_a, vec_b):
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return None
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a)
    norm_b = sum(b * b for b in vec_b)
    if norm_a <= 0.0 or norm_b <= 0.0:
        return None
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def load_visual_embedding_records(identities=None, max_per_identity=25):
    if not DB_PATH.exists():
        return []
    with connect_db() as conn:
        cols = table_columns(conn, "visual_embeddings")
        required = {"crop_path", "identity", "embedding_json"}
        if not required.issubset(set(cols)):
            return []
        params = []
        where_clause = "identity IS NOT NULL AND identity != ''"
        if identities:
            identities = [x for x in identities if x and x != MULTIBIRD_GROUP]
            if not identities:
                return []
            qmarks = ",".join("?" for _ in identities)
            where_clause += f" AND identity IN ({qmarks})"
            params.extend(identities)
        rows = conn.execute(
            f"""
            SELECT crop_path, identity, model_name, model_version, embedding_json
            FROM visual_embeddings
            WHERE {where_clause}
            ORDER BY identity ASC, crop_path ASC
            """,
            params,
        ).fetchall()
    rows = sorted(rows, key=lambda row: (identity_display_sort_key(row["identity"]), str(row["crop_path"] or "")))
    records = []
    counts = {}
    for row in rows:
        identity = row["identity"]
        counts[identity] = counts.get(identity, 0)
        if counts[identity] >= max_per_identity:
            continue
        embedding = parse_embedding_json(row["embedding_json"])
        if embedding is None:
            continue
        records.append({"identity": identity, "crop_path": row["crop_path"], "model_name": row["model_name"] if "model_name" in row.keys() else None, "model_version": row["model_version"] if "model_version" in row.keys() else None, "embedding": embedding})
        counts[identity] += 1
    return records


def all_normal_identity_names():
    return [row["identity"] for row in get_identities(True, False, True) if row.get("special_group") is None and row["identity"] != MULTIBIRD_GROUP]


def analyze_dino_identity_similarity(identities=None, threshold=0.79, max_per_identity=25, max_results=200, anchor_identity=None):
    records = load_visual_embedding_records(identities=identities, max_per_identity=max_per_identity)
    by_identity = {}
    for record in records:
        by_identity.setdefault(record["identity"], []).append(record)
    identities_loaded = sorted(by_identity.keys(), key=identity_display_sort_key)
    results = []
    comparisons = 0

    pairs = []
    if anchor_identity:
        if anchor_identity not in by_identity:
            return {"threshold": threshold, "records_loaded": len(records), "identities_loaded": len(identities_loaded), "comparisons": 0, "results": [], "total_results": 0, "anchor_identity": anchor_identity}
        for target_identity in identities_loaded:
            if target_identity != anchor_identity:
                pairs.append((anchor_identity, target_identity))
    else:
        for i, source_identity in enumerate(identities_loaded):
            for target_identity in identities_loaded[i + 1:]:
                pairs.append((source_identity, target_identity))

    for source_identity, target_identity in pairs:
        best_score = None
        best_source = None
        best_target = None
        for source_record in by_identity.get(source_identity, []):
            for target_record in by_identity.get(target_identity, []):
                score = cosine_similarity(source_record["embedding"], target_record["embedding"])
                if score is None:
                    continue
                comparisons += 1
                if best_score is None or score > best_score:
                    best_score = score
                    best_source = source_record
                    best_target = target_record
        if best_score is not None and best_score >= threshold:
            results.append({
                "method": "dino_similarity",
                "score": best_score,
                "source_identity": source_identity,
                "target_identity": target_identity,
                "source_crop": best_source["crop_path"] if best_source else "",
                "target_crop": best_target["crop_path"] if best_target else "",
                "proposal": "compare_profiles",
                "suggested_action": "Review crop pair; if verified, add both crops to a new named profile.",
                "notes": "Read-only DINO cosine similarity proposal. DINO is context/lighting biased; use as weak evidence only.",
            })
    results.sort(key=lambda row: row["score"], reverse=True)
    return {"threshold": threshold, "records_loaded": len(records), "identities_loaded": len(identities_loaded), "comparisons": comparisons, "results": results[:max_results], "total_results": len(results), "anchor_identity": anchor_identity}


def archive_and_delete_crops(crop_ids, source_identity, label="junk"):
    if not crop_ids:
        return
    backup_path = backup_database("delete-junk-crops")
    JUNK_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    qmarks = ",".join("?" for _ in crop_ids)
    archived = []
    missing = []
    with connect_db() as conn:
        rows = conn.execute(f"SELECT id, crop_path, identity FROM crop_queue WHERE id IN ({qmarks})", crop_ids).fetchall()
    crop_paths = [row["crop_path"] for row in rows]
    for row in rows:
        old_path = Path(row["crop_path"])
        if old_path.exists():
            archive_path = JUNK_ARCHIVE_DIR / f"{now_stamp()}-id{row['id']}-{old_path.name}"
            try:
                shutil.move(str(old_path), str(archive_path))
                archived.append({"crop_id": row["id"], "old_path": str(old_path), "archive_path": str(archive_path)})
            except Exception as exc:
                missing.append({"crop_id": row["id"], "old_path": str(old_path), "error": str(exc)})
        else:
            missing.append({"crop_id": row["id"], "old_path": str(old_path), "error": "file missing before archive"})
    with connect_db() as conn:
        conn.execute(f"DELETE FROM crop_queue WHERE id IN ({qmarks})", crop_ids)
        try:
            ve_cols = table_columns(conn, "visual_embeddings")
            if "crop_path" in ve_cols and crop_paths:
                ve_qmarks = ",".join("?" for _ in crop_paths)
                conn.execute(f"DELETE FROM visual_embeddings WHERE crop_path IN ({ve_qmarks})", crop_paths)
        except sqlite3.OperationalError:
            pass
        conn.commit()
    log_identity_history(rows, "archive_and_delete_junk_crops", new_identity=None, notes={"source_identity": source_identity, "label": label, "archived": archived, "missing_or_failed": missing, "junk_archive_dir": str(JUNK_ARCHIVE_DIR), "backup_path": str(backup_path) if backup_path else None})
    log_action("archive_and_delete_junk_crops", source_identity, details={"crop_ids": crop_ids, "crop_count": len(crop_ids), "label": label, "archived": archived, "missing_or_failed": missing, "junk_archive_dir": str(JUNK_ARCHIVE_DIR), "backup_path": str(backup_path) if backup_path else None})


class CropTile:
    def __init__(self, gui, parent, row):
        self.gui = gui
        self.row = row
        self.selected = False
        self.photo = None
        self.frame = ttk.Frame(parent, borderwidth=2, relief="groove", padding=4)
        self.frame.grid_propagate(False)
        self.image_label = ttk.Label(self.frame)
        self.image_label.pack()
        filename = Path(row["crop_path"]).name
        identity = row["identity"] or "n/a"
        score = row["visual_score"]
        decision = row["visual_decision"] or "n/a"
        status = row["identity_status"] or "n/a"
        label = row["training_label"] or ""
        score_text = "n/a" if score in (None, "") else str(score)
        label_line = f"\nlabel: {label}" if label else ""
        self.text_label = ttk.Label(self.frame, text=f"{filename}\nid: {identity}\nstatus: {status}{label_line}\nscore: {score_text}\ndecision: {decision}", wraplength=THUMB_SIZE + 80, justify="center")
        self.text_label.pack(pady=(4, 0))
        self.frame.bind("<Button-1>", self.toggle)
        self.image_label.bind("<Button-1>", self.toggle)
        self.text_label.bind("<Button-1>", self.toggle)
        self.load_image()

    def load_image(self):
        path = Path(self.row["crop_path"])
        if path.exists():
            try:
                if PIL_AVAILABLE:
                    img = Image.open(path)
                    img.thumbnail((THUMB_SIZE, THUMB_SIZE))
                    self.photo = ImageTk.PhotoImage(img)
                else:
                    self.photo = tk.PhotoImage(file=str(path))
                self.image_label.configure(image=self.photo)
                self.gui.image_refs.append(self.photo)
                return
            except Exception as exc:
                self.image_label.configure(text=f"[image error]\n{exc}", width=24)
                return
        self.image_label.configure(text=f"[missing]\n{path.name}", width=24)

    def toggle(self, event=None):
        self.set_selected(not self.selected)
        self.gui.update_crop_selection_status()

    def set_selected(self, value):
        self.selected = bool(value)
        self.frame.configure(relief="sunken" if self.selected else "groove")


class CleanupGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_VERSION)
        self.root.geometry("1480x900")
        self.include_false_positive = tk.BooleanVar(value=False)
        self.include_multibird = tk.BooleanVar(value=True)
        self.include_low_quality = tk.BooleanVar(value=True)
        self.identity_rows = []
        self.active_compare_identities = []
        self.current_identity = None
        self.current_crop_rows = []
        self.crop_tiles = []
        self.image_refs = []
        self.sort_threshold = tk.DoubleVar(value=0.79)
        self.sort_scope = tk.StringVar(value="anchor_selected")
        self.sort_results = []
        self.sort_view_mode = tk.StringVar(value="details")
        self.sort_thumb_canvas = None
        self.sort_thumb_workspace = None
        self.lightglue_identity_a = tk.StringVar(value="")
        self.lightglue_identity_b = tk.StringVar(value="")
        self.lightglue_rows_a = []
        self.lightglue_rows_b = []
        self.lightglue_photo = None
        self.lightglue_match_image_path = ""
        self.lightglue_override_a = ""
        self.lightglue_override_b = ""
        self.lightglue_status = tk.StringVar(value="LightGlue tester not loaded yet.")
        self.refine_identity = tk.StringVar(value="")
        self.refine_rows = []
        self.refine_raw_photo = None
        self.refine_preview_photo = None
        self.refine_preview_image = None
        self.refine_last_saved_path = ""
        self.refine_status = tk.StringVar(value="Crop Refinement Lab not loaded yet.")
        self.refine_recipe_name = tk.StringVar(value="handheld-tight-v0")
        self.refine_crop_percent = tk.DoubleVar(value=18.0)
        self.refine_focus_x = tk.DoubleVar(value=0.0)
        self.refine_focus_y = tk.DoubleVar(value=0.0)
        self.refine_square = tk.BooleanVar(value=True)
        self.refine_background_mode = tk.StringVar(value="blur outside ellipse")
        self.refine_bg_blur_radius = tk.DoubleVar(value=8.0)
        self.refine_resize_max_side = tk.IntVar(value=512)
        self.refine_recipe_preset = tk.StringVar(value="current/custom")
        self.refine_live_preview = tk.BooleanVar(value=True)
        self.refine_preview_after_id = None
        self.sandbox_crop_list = None
        self.sandbox_thumb_canvas = None
        self.sandbox_thumb_workspace = None
        self.sandbox_rows = []
        self.sandbox_view_mode = tk.StringVar(value="details")
        self.sandbox_status = tk.StringVar(value="Sandbox not loaded yet.")
        self.true_name_list = None
        self.true_crop_list = None
        self.true_thumb_canvas = None
        self.true_thumb_workspace = None
        self.true_crop_rows = []
        self.true_view_mode = tk.StringVar(value="details")
        self.true_name_status = tk.StringVar(value="True Names not loaded yet.")
        self.manual_source_lane = tk.StringVar(value="Raw Groups")
        self.manual_rows = []
        self.manual_index = 0
        self.manual_photo = None
        self.manual_status = tk.StringVar(value="Manual Sorting not loaded yet.")
        self.manual_info = tk.StringVar(value="Load a source lane to begin keyboard sorting.")
        self.manual_shortcuts = tk.StringVar(value="Space=skip | B=back | L=low-quality bird | M=multibird | J=junk | F=false positive | A=AI/suspicious | S=sandbox | T=true name | R=raw")
        self.build_layout()
        self.refresh_identities()

    def build_layout(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=APP_VERSION).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side="right")
        ttk.Button(top, text="Rebuild Profiles", command=self.rebuild_profiles).pack(side="right", padx=6)
        ttk.Button(top, text="Undo Last Action", command=self.undo_last_action).pack(side="right", padx=6)
        ttk.Checkbutton(top, text="Show false positives", variable=self.include_false_positive, command=self.refresh_all).pack(side="right", padx=8)
        ttk.Checkbutton(top, text="Show multibird", variable=self.include_multibird, command=self.refresh_all).pack(side="right", padx=8)
        ttk.Checkbutton(top, text="Show low quality", variable=self.include_low_quality, command=self.refresh_all).pack(side="right", padx=8)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)
        self.reconcile_tab = ttk.Frame(self.notebook)
        self.identity_lab_tab = ttk.Frame(self.notebook)
        self.species_tab = ttk.Frame(self.notebook)
        self.ai_detection_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.reconcile_tab, text="Identity Lab")
        self.notebook.add(self.identity_lab_tab, text="Auto-sorting workspace")
        self.notebook.add(self.species_tab, text="SpeciesNet")
        self.notebook.add(self.ai_detection_tab, text="AI Detection")

        self.identity_lab_notebook = ttk.Notebook(self.reconcile_tab)
        self.identity_lab_notebook.pack(fill="both", expand=True)
        self.raw_groups_tab = ttk.Frame(self.identity_lab_notebook)
        self.stage_names_tab = ttk.Frame(self.identity_lab_notebook)
        self.true_names_tab = ttk.Frame(self.identity_lab_notebook)
        self.manual_sort_tab = ttk.Frame(self.identity_lab_notebook)
        self.identity_lab_notebook.add(self.raw_groups_tab, text="Raw Groups")
        self.identity_lab_notebook.add(self.stage_names_tab, text="Stage Names Sandbox")
        self.identity_lab_notebook.add(self.true_names_tab, text="True Names")
        self.identity_lab_notebook.add(self.manual_sort_tab, text="Manual Sorting")

        main = ttk.Frame(self.raw_groups_tab)
        main.pack(fill="both", expand=True)
        self.build_stage_names_tab(self.stage_names_tab)
        self.build_true_names_tab(self.true_names_tab)
        self.build_manual_sort_tab(self.manual_sort_tab)
        self.build_identity_lab_tab(self.identity_lab_tab)
        self.build_species_tab(self.species_tab)
        self.build_ai_detection_tab(self.ai_detection_tab)

        left = ttk.Frame(main, padding=8)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Raw Bird##### groups + special groups").pack(anchor="w")
        self.identity_list = tk.Listbox(left, width=50, height=35, selectmode="extended", exportselection=False)
        self.identity_list.pack(fill="y", expand=True)
        self.identity_list.bind("<<ListboxSelect>>", self.identity_selected)
        ttk.Button(left, text="Open First Selected Identity/Group", command=self.open_first_selected_identity).pack(fill="x", pady=(8, 2))
        ttk.Button(left, text="Move Identity To Sandbox", command=self.move_selected_identities_to_sandbox).pack(fill="x", pady=2)
        ttk.Button(left, text="Move Identity To True Names", command=self.move_current_identity_to_true_names).pack(fill="x", pady=2)
        ttk.Button(left, text="Compare Selected Identities", command=self.compare_selected).pack(fill="x", pady=2)
        ttk.Button(left, text="Mark Selected Identities False Positive", command=self.mark_selected_identities_fp).pack(fill="x", pady=2)
        ttk.Button(left, text="Mark Selected Identities Multibird", command=self.mark_selected_identities_multibird).pack(fill="x", pady=2)
        ttk.Button(left, text="Mark Selected Identities Low Quality", command=self.mark_selected_identities_low_quality).pack(fill="x", pady=2)
        self.status = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.status, wraplength=350).pack(anchor="w", pady=10)

        right = ttk.Frame(main, padding=8)
        right.pack(side="right", fill="both", expand=True)
        mode_bar = ttk.Frame(right)
        mode_bar.pack(fill="x", pady=(0, 6))
        self.mode_label = ttk.Label(mode_bar, text="Select a Bird##### identity or special group to inspect crops.")
        self.mode_label.pack(side="left")
        self.crop_selection_label = ttk.Label(mode_bar, text="Selected crops: 0")
        self.crop_selection_label.pack(side="right")
        action_bar = ttk.Frame(right)
        action_bar.pack(fill="x", pady=(0, 8))
        ttk.Button(action_bar, text="Select All Crops", command=self.select_all_crops).pack(side="left")
        ttk.Button(action_bar, text="Clear Crop Selection", command=self.clear_crop_selection).pack(side="left", padx=5)
        ttk.Button(action_bar, text="Move Selected To Sandbox", command=self.move_selected_crops_to_sandbox).pack(side="left", padx=(14, 5))
        ttk.Button(action_bar, text="Move Selected To True Names", command=self.move_selected_crops_to_true_names).pack(side="left", padx=5)
        ttk.Button(action_bar, text="False Positive", command=self.mark_selected_crops_fp).pack(side="left", padx=5)
        ttk.Button(action_bar, text="Multibird", command=self.mark_selected_crops_multibird).pack(side="left", padx=5)
        ttk.Button(action_bar, text="Low Quality", command=self.mark_selected_crops_low_quality).pack(side="left", padx=5)
        ttk.Button(action_bar, text="Archive/Delete Junk", command=self.delete_selected_junk_crops).pack(side="left", padx=5)
        self.canvas = tk.Canvas(right)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(right, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.workspace = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.workspace, anchor="nw")
        self.workspace.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self.on_mousewheel)

    def build_stage_names_tab(self, parent):
        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Stage Names Sandbox", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Temporary evidence bucket for crops promoted from sorter proposals before they become provisional stage identities or later true names. This uses identity_status='sandbox' and logs every add action.", wraplength=1100).pack(anchor="w", pady=(4, 10))
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Refresh Sandbox", command=self.refresh_sandbox_tab).pack(side="left")
        ttk.Button(controls, text="Open Source Profile", command=self.open_selected_sandbox_source_profile).pack(side="left", padx=6)
        ttk.Button(controls, text="Remove Selected Crop(s) From Sandbox", command=self.remove_selected_sandbox_crops_to_raw).pack(side="left", padx=6)
        ttk.Button(controls, text="Remove Selected Sandbox Profile", command=self.remove_selected_sandbox_profile_to_raw).pack(side="left", padx=6)
        ttk.Label(controls, textvariable=self.sandbox_status, wraplength=900).pack(side="left", padx=12)
        view_row = ttk.Frame(frame)
        view_row.pack(fill="x", pady=(0, 8))
        ttk.Label(view_row, text="View:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(view_row, text="Details", variable=self.sandbox_view_mode, value="details", command=self.update_sandbox_view).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(view_row, text="Thumbnails", variable=self.sandbox_view_mode, value="thumbnails", command=self.update_sandbox_view).pack(side="left", padx=(0, 8))

        content = ttk.Frame(frame)
        content.pack(fill="both", expand=True)
        columns = ("id", "identity", "status", "label", "crop")
        self.sandbox_crop_list = ttk.Treeview(content, columns=columns, show="headings", height=24, selectmode="extended")
        for col, width in (("id", 70), ("identity", 150), ("status", 110), ("label", 170), ("crop", 720)):
            self.sandbox_crop_list.heading(col, text=col)
            self.sandbox_crop_list.column(col, width=width, anchor="w")
        self.sandbox_crop_list.pack(side="left", fill="both", expand=True)
        self.sandbox_thumb_canvas = tk.Canvas(content)
        self.sandbox_thumb_workspace = ttk.Frame(self.sandbox_thumb_canvas)
        self.sandbox_thumb_window = self.sandbox_thumb_canvas.create_window((0, 0), window=self.sandbox_thumb_workspace, anchor="nw")
        self.sandbox_thumb_workspace.bind("<Configure>", lambda e: self.sandbox_thumb_canvas.configure(scrollregion=self.sandbox_thumb_canvas.bbox("all")))
        self.sandbox_thumb_canvas.bind("<Configure>", lambda e: self.sandbox_thumb_canvas.itemconfigure(self.sandbox_thumb_window, width=e.width))
        scroll = ttk.Scrollbar(content, orient="vertical", command=self.sandbox_crop_list.yview)
        scroll.pack(side="right", fill="y")
        self.sandbox_scroll = scroll
        self.sandbox_crop_list.configure(yscrollcommand=scroll.set)

    def build_true_names_tab(self, parent):
        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="True Names", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Verified/canonical identity lane. Crops moved here use identity_status='active' and review_status='reviewed'. Fully true-name identities are hidden from Raw Groups so unresolved crops remain easier to sort.", wraplength=1100).pack(anchor="w", pady=(4, 10))
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Refresh True Names", command=self.refresh_true_names_tab).pack(side="left")
        ttk.Button(controls, text="Open Selected True Name Workspace", command=self.open_selected_true_name_workspace).pack(side="left", padx=6)
        ttk.Button(controls, text="Remove Selected Crop(s) From True Names", command=self.remove_selected_true_crops_to_raw).pack(side="left", padx=6)
        ttk.Button(controls, text="Remove Selected True Name Profile", command=self.remove_selected_true_profile_to_raw).pack(side="left", padx=6)
        ttk.Label(controls, textvariable=self.true_name_status, wraplength=900).pack(side="left", padx=12)
        view_row = ttk.Frame(frame)
        view_row.pack(fill="x", pady=(0, 8))
        ttk.Label(view_row, text="Crop view:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(view_row, text="Details", variable=self.true_view_mode, value="details", command=self.update_true_view).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(view_row, text="Thumbnails", variable=self.true_view_mode, value="thumbnails", command=self.update_true_view).pack(side="left", padx=(0, 8))

        panes = ttk.Panedwindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)

        ttk.Label(left, text="True-name profiles").pack(anchor="w")
        profile_columns = ("identity", "crops", "avg")
        self.true_name_list = ttk.Treeview(left, columns=profile_columns, show="headings", height=24)
        for col, width in (("identity", 180), ("crops", 70), ("avg", 90)):
            self.true_name_list.heading(col, text=col)
            self.true_name_list.column(col, width=width, anchor="w")
        self.true_name_list.pack(side="left", fill="both", expand=True)
        self.true_name_list.bind("<<TreeviewSelect>>", self.true_name_selected)
        left_scroll = ttk.Scrollbar(left, orient="vertical", command=self.true_name_list.yview)
        left_scroll.pack(side="right", fill="y")
        self.true_name_list.configure(yscrollcommand=left_scroll.set)

        ttk.Label(right, text="Crops in selected true-name profile").pack(anchor="w")
        self.true_crop_content = ttk.Frame(right)
        self.true_crop_content.pack(fill="both", expand=True)
        crop_columns = ("id", "identity", "status", "review", "crop")
        self.true_crop_list = ttk.Treeview(self.true_crop_content, columns=crop_columns, show="headings", height=24, selectmode="extended")
        for col, width in (("id", 70), ("identity", 150), ("status", 100), ("review", 100), ("crop", 650)):
            self.true_crop_list.heading(col, text=col)
            self.true_crop_list.column(col, width=width, anchor="w")
        self.true_crop_list.pack(side="left", fill="both", expand=True)
        self.true_thumb_canvas = tk.Canvas(self.true_crop_content)
        self.true_thumb_workspace = ttk.Frame(self.true_thumb_canvas)
        self.true_thumb_window = self.true_thumb_canvas.create_window((0, 0), window=self.true_thumb_workspace, anchor="nw")
        self.true_thumb_workspace.bind("<Configure>", lambda e: self.true_thumb_canvas.configure(scrollregion=self.true_thumb_canvas.bbox("all")))
        self.true_thumb_canvas.bind("<Configure>", lambda e: self.true_thumb_canvas.itemconfigure(self.true_thumb_window, width=e.width))
        right_scroll = ttk.Scrollbar(self.true_crop_content, orient="vertical", command=self.true_crop_list.yview)
        right_scroll.pack(side="right", fill="y")
        self.true_scroll = right_scroll
        self.true_crop_list.configure(yscrollcommand=right_scroll.set)

    def make_lane_thumbnail_card(self, parent, row, lane):
        card = ttk.Frame(parent, borderwidth=2, relief="groove", padding=6)
        card.pack(fill="x", padx=4, pady=4)
        top = ttk.Frame(card)
        top.pack(fill="x")
        ttk.Label(top, text=f"id {row['id']} | {row['identity'] or 'n/a'} | {Path(row['crop_path']).name}", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        img_row = ttk.Frame(card)
        img_row.pack(anchor="w", pady=(4, 0))
        photo = self.load_sort_thumbnail(row["crop_path"])
        if photo is not None:
            image_label = ttk.Label(img_row, image=photo)
            image_label.image = photo
            image_label.pack(side="left")
            self.image_refs.append(photo)
        else:
            ttk.Label(img_row, text="[missing image]", width=24).pack(side="left")
        score = row["visual_score"]
        score_text = "n/a" if score in (None, "") else str(score)
        info = f"status: {row['identity_status'] or 'n/a'}\nreview: {row['review_status'] or 'n/a'}\nlabel: {row['training_label'] or ''}\nscore: {score_text}\n{row['crop_path']}"
        ttk.Label(img_row, text=info, wraplength=700, justify="left").pack(side="left", padx=8)

    def populate_sandbox_thumbnails(self):
        if self.sandbox_thumb_workspace is None:
            return
        for child in self.sandbox_thumb_workspace.winfo_children():
            child.destroy()
        for row in self.sandbox_rows:
            self.make_lane_thumbnail_card(self.sandbox_thumb_workspace, row, "sandbox")

    def populate_true_thumbnails(self):
        if self.true_thumb_workspace is None:
            return
        for child in self.true_thumb_workspace.winfo_children():
            child.destroy()
        for row in self.true_crop_rows:
            self.make_lane_thumbnail_card(self.true_thumb_workspace, row, "true")

    def update_sandbox_view(self):
        if self.sandbox_crop_list is None or self.sandbox_thumb_canvas is None:
            return
        if self.sandbox_view_mode.get() == "thumbnails":
            self.sandbox_crop_list.pack_forget()
            self.sandbox_thumb_canvas.pack(side="left", fill="both", expand=True)
            self.sandbox_scroll.configure(command=self.sandbox_thumb_canvas.yview)
            self.sandbox_thumb_canvas.configure(yscrollcommand=self.sandbox_scroll.set)
        else:
            self.sandbox_thumb_canvas.pack_forget()
            self.sandbox_crop_list.pack(side="left", fill="both", expand=True)
            self.sandbox_scroll.configure(command=self.sandbox_crop_list.yview)
            self.sandbox_crop_list.configure(yscrollcommand=self.sandbox_scroll.set)

    def update_true_view(self):
        if self.true_crop_list is None or self.true_thumb_canvas is None:
            return
        if self.true_view_mode.get() == "thumbnails":
            self.true_crop_list.pack_forget()
            self.true_thumb_canvas.pack(side="left", fill="both", expand=True)
            self.true_scroll.configure(command=self.true_thumb_canvas.yview)
            self.true_thumb_canvas.configure(yscrollcommand=self.true_scroll.set)
        else:
            self.true_thumb_canvas.pack_forget()
            self.true_crop_list.pack(side="left", fill="both", expand=True)
            self.true_scroll.configure(command=self.true_crop_list.yview)
            self.true_crop_list.configure(yscrollcommand=self.true_scroll.set)

    def refresh_sandbox_tab(self):
        if self.sandbox_crop_list is None:
            return
        for item in self.sandbox_crop_list.get_children():
            self.sandbox_crop_list.delete(item)
        self.sandbox_rows = get_sandbox_crops()
        for row in self.sandbox_rows:
            self.sandbox_crop_list.insert("", tk.END, iid=str(row["id"]), values=(row["id"], row["identity"] or "", row["identity_status"] or "", row["training_label"] or "", row["crop_path"] or ""))
        self.populate_sandbox_thumbnails()
        self.update_sandbox_view()
        self.sandbox_status.set(f"Loaded {len(self.sandbox_rows)} sandbox crop(s).")

    def selected_tree_int_ids(self, tree):
        if tree is None:
            return []
        ids = []
        for item in tree.selection():
            try:
                ids.append(int(item))
            except Exception:
                pass
        return ids

    def open_selected_sandbox_source_profile(self):
        if self.sandbox_crop_list is None:
            return
        selection = self.sandbox_crop_list.selection()
        if not selection:
            messagebox.showinfo("Sandbox", "Select a sandbox crop first in Details view.")
            return
        values = self.sandbox_crop_list.item(selection[0], "values")
        if len(values) < 2 or not values[1]:
            messagebox.showinfo("Sandbox", "Selected crop does not have a source identity.")
            return
        self.identity_lab_notebook.select(self.raw_groups_tab)
        self.open_identity(values[1])

    def remove_selected_sandbox_crops_to_raw(self):
        crop_ids = self.selected_tree_int_ids(self.sandbox_crop_list)
        if not crop_ids:
            messagebox.showinfo("Sandbox", "Select one or more sandbox crops in Details view first.")
            return
        if not messagebox.askyesno("Remove from Sandbox", f"Return {len(crop_ids)} selected crop(s) from Sandbox to Raw Groups?\n\nThis is non-destructive and creates a database backup."):
            return
        count = reset_crop_ids_to_raw(crop_ids, "Stage Names Sandbox", "remove_selected_sandbox_crops_to_raw")
        self.status.set(f"Returned {count} sandbox crop(s) to Raw Groups.")
        self.refresh_all()

    def remove_selected_sandbox_profile_to_raw(self):
        if self.sandbox_crop_list is None:
            return
        selection = self.sandbox_crop_list.selection()
        if not selection:
            messagebox.showinfo("Sandbox", "Select a sandbox crop from the profile you want to remove from Sandbox.")
            return
        values = self.sandbox_crop_list.item(selection[0], "values")
        identity = values[1] if len(values) > 1 else ""
        if not identity:
            messagebox.showinfo("Sandbox", "Selected sandbox crop does not have an identity/profile name.")
            return
        if not messagebox.askyesno("Remove Sandbox Profile", f"Return all sandbox crops for {identity} to Raw Groups?\n\nThis is non-destructive and creates a database backup."):
            return
        count = reset_identity_lane_to_raw(identity, "sandbox", "Stage Names Sandbox", "remove_sandbox_profile_to_raw")
        self.status.set(f"Returned {count} crop(s) from sandbox profile {identity} to Raw Groups.")
        self.refresh_all()

    def refresh_true_names_tab(self):
        if self.true_name_list is None or self.true_crop_list is None:
            return
        selected_identity = None
        if self.true_name_list.selection():
            selected_identity = self.true_name_list.selection()[0]
        for item in self.true_name_list.get_children():
            self.true_name_list.delete(item)
        for item in self.true_crop_list.get_children():
            self.true_crop_list.delete(item)
        self.true_crop_rows = []
        rows = get_true_name_identities()
        for row in rows:
            avg = row["avg_score"]
            avg_text = "n/a" if avg is None else f"{avg:.3f}"
            self.true_name_list.insert("", tk.END, iid=row["identity"], values=(row["identity"], row["crop_count"], avg_text))
        total_crops = sum(row["crop_count"] for row in rows)
        if selected_identity and selected_identity in self.true_name_list.get_children():
            self.true_name_list.selection_set(selected_identity)
            self.true_name_selected()
        else:
            self.populate_true_thumbnails()
            self.update_true_view()
        self.true_name_status.set(f"Loaded {len(rows)} true-name profile(s), {total_crops} active crop(s).")

    def true_name_selected(self, event=None):
        if self.true_name_list is None or self.true_crop_list is None:
            return
        selection = self.true_name_list.selection()
        if not selection:
            return
        identity = selection[0]
        for item in self.true_crop_list.get_children():
            self.true_crop_list.delete(item)
        self.true_crop_rows = get_true_name_crops(identity)
        for row in self.true_crop_rows:
            self.true_crop_list.insert("", tk.END, iid=str(row["id"]), values=(row["id"], row["identity"] or "", row["identity_status"] or "", row["review_status"] or "", row["crop_path"] or ""))
        self.populate_true_thumbnails()
        self.update_true_view()
        self.true_name_status.set(f"Loaded {len(self.true_crop_rows)} crop(s) for True Name {identity}.")

    def remove_selected_true_crops_to_raw(self):
        crop_ids = self.selected_tree_int_ids(self.true_crop_list)
        if not crop_ids:
            messagebox.showinfo("True Names", "Select one or more true-name crops in Details view first.")
            return
        if not messagebox.askyesno("Remove from True Names", f"Return {len(crop_ids)} selected crop(s) from True Names to Raw Groups?\n\nThis is non-destructive and creates a database backup."):
            return
        count = reset_crop_ids_to_raw(crop_ids, "True Names", "remove_selected_true_name_crops_to_raw")
        self.status.set(f"Returned {count} true-name crop(s) to Raw Groups.")
        self.refresh_all()

    def remove_selected_true_profile_to_raw(self):
        if self.true_name_list is None:
            return
        selection = self.true_name_list.selection()
        if not selection:
            messagebox.showinfo("True Names", "Select a true-name profile first.")
            return
        identity = selection[0]
        if not messagebox.askyesno("Remove True Name Profile", f"Return all active/true-name crops for {identity} to Raw Groups?\n\nThis is non-destructive and creates a database backup."):
            return
        count = reset_identity_lane_to_raw(identity, "active", "True Names", "remove_true_name_profile_to_raw")
        self.status.set(f"Returned {count} crop(s) from true-name profile {identity} to Raw Groups.")
        self.refresh_all()

    def open_selected_true_name_workspace(self):
        if self.true_name_list is None:
            return
        selection = self.true_name_list.selection()
        if not selection:
            messagebox.showinfo("True Names", "Select a true-name profile first.")
            return
        identity = selection[0]
        self.identity_lab_notebook.select(self.raw_groups_tab)
        self.open_identity(identity)

    def build_manual_sort_tab(self, parent):
        outer = ttk.Frame(parent, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Manual Sorting", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Keyboard-friendly crop slideshow for Raw Groups, Stage Names Sandbox, and True Names. Mutating shortcuts create backups and log actions before advancing.", wraplength=1150).pack(anchor="w", pady=(4, 10))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="Source lane:").pack(side="left")
        self.manual_source_combo = ttk.Combobox(controls, textvariable=self.manual_source_lane, values=("Raw Groups", "Stage Names Sandbox", "True Names"), state="readonly", width=24)
        self.manual_source_combo.pack(side="left", padx=(6, 8))
        ttk.Button(controls, text="Load Slideshow", command=self.manual_load_slideshow).pack(side="left", padx=(0, 6))
        ttk.Button(controls, text="Previous", command=self.manual_previous).pack(side="left", padx=3)
        ttk.Button(controls, text="Skip / Next", command=self.manual_skip).pack(side="left", padx=3)
        ttk.Label(controls, textvariable=self.manual_status, wraplength=650).pack(side="left", padx=12)

        action_row = ttk.Frame(outer)
        action_row.pack(fill="x", pady=(0, 8))
        ttk.Button(action_row, text="L Low-quality Bird", command=self.manual_mark_low_quality).pack(side="left", padx=3)
        ttk.Button(action_row, text="M Multibird", command=self.manual_mark_multibird).pack(side="left", padx=3)
        ttk.Button(action_row, text="J Junk", command=self.manual_mark_junk).pack(side="left", padx=3)
        ttk.Button(action_row, text="F False Positive", command=self.manual_mark_false_positive).pack(side="left", padx=3)
        ttk.Button(action_row, text="A AI / Suspicious", command=self.manual_mark_ai_suspicious).pack(side="left", padx=3)
        ttk.Button(action_row, text="S Move To Sandbox", command=self.manual_move_to_sandbox).pack(side="left", padx=3)
        ttk.Button(action_row, text="T Move To True Names", command=self.manual_move_to_true_names).pack(side="left", padx=3)
        ttk.Button(action_row, text="R Return To Raw", command=self.manual_return_to_raw).pack(side="left", padx=3)
        ttk.Label(action_row, textvariable=self.manual_shortcuts, wraplength=600).pack(side="left", padx=12)

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        self.manual_image_label = ttk.Label(body, text="Load a slideshow to begin.", anchor="center")
        self.manual_image_label.pack(side="left", fill="both", expand=True, padx=(0, 12))
        info_box = ttk.Frame(body, width=360)
        info_box.pack(side="right", fill="y")
        ttk.Label(info_box, text="Current crop", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(info_box, textvariable=self.manual_info, wraplength=340, justify="left").pack(anchor="w", pady=(8, 0))
        ttk.Label(info_box, text="Shortcut focus: click anywhere in this tab if keys stop responding.", wraplength=340).pack(anchor="w", pady=(14, 0))

        for sequence, handler in (
            ("<space>", self.manual_skip_event),
            ("l", self.manual_mark_low_quality_event),
            ("L", self.manual_mark_low_quality_event),
            ("m", self.manual_mark_multibird_event),
            ("M", self.manual_mark_multibird_event),
            ("j", self.manual_mark_junk_event),
            ("J", self.manual_mark_junk_event),
            ("f", self.manual_mark_false_positive_event),
            ("F", self.manual_mark_false_positive_event),
            ("a", self.manual_mark_ai_suspicious_event),
            ("A", self.manual_mark_ai_suspicious_event),
            ("s", self.manual_move_to_sandbox_event),
            ("S", self.manual_move_to_sandbox_event),
            ("t", self.manual_move_to_true_names_event),
            ("T", self.manual_move_to_true_names_event),
            ("r", self.manual_return_to_raw_event),
            ("R", self.manual_return_to_raw_event),
            ("b", self.manual_previous_event),
            ("B", self.manual_previous_event),
        ):
            self.root.bind(sequence, handler, add="+")

    def manual_tab_is_active(self):
        try:
            return self.identity_lab_notebook.select() == str(self.manual_sort_tab) and self.notebook.select() == str(self.reconcile_tab)
        except Exception:
            return False

    def manual_current_row(self):
        if not self.manual_rows or self.manual_index < 0 or self.manual_index >= len(self.manual_rows):
            return None
        return self.manual_rows[self.manual_index]

    def manual_load_slideshow(self):
        self.manual_rows = get_manual_sort_crops(self.manual_source_lane.get())
        self.manual_index = 0
        self.manual_show_current()

    def manual_show_current(self):
        row = self.manual_current_row()
        total = len(self.manual_rows)
        if not row:
            self.manual_photo = None
            self.manual_image_label.configure(image="", text="No crops loaded for this lane.")
            self.manual_status.set(f"{self.manual_source_lane.get()}: 0 crops loaded.")
            self.manual_info.set("No current crop.")
            return
        self.manual_status.set(f"{self.manual_source_lane.get()}: crop {self.manual_index + 1} of {total}")
        path = Path(row["crop_path"] or "")
        score = row["visual_score"]
        score_text = "n/a" if score in (None, "") else str(score)
        self.manual_info.set(
            f"id: {row['id']}\n"
            f"identity: {row['identity'] or 'n/a'}\n"
            f"status: {row['identity_status'] or 'n/a'}\n"
            f"review: {row['review_status'] or 'n/a'}\n"
            f"label: {row['training_label'] or 'n/a'}\n"
            f"score: {score_text}\n"
            f"decision: {row['visual_decision'] or 'n/a'}\n\n"
            f"{path}"
        )
        if path.exists():
            try:
                if PIL_AVAILABLE:
                    img = Image.open(path)
                    img.thumbnail((820, 680))
                    self.manual_photo = ImageTk.PhotoImage(img)
                else:
                    self.manual_photo = tk.PhotoImage(file=str(path))
                self.manual_image_label.configure(image=self.manual_photo, text="")
                return
            except Exception as exc:
                self.manual_photo = None
                self.manual_image_label.configure(image="", text=f"[image error]\n{path.name}\n{exc}")
                return
        self.manual_photo = None
        self.manual_image_label.configure(image="", text=f"[missing]\n{path.name}")

    def manual_advance_after_action(self):
        if self.manual_rows and self.manual_index < len(self.manual_rows):
            del self.manual_rows[self.manual_index]
        if self.manual_index >= len(self.manual_rows):
            self.manual_index = max(0, len(self.manual_rows) - 1)
        self.manual_show_current()
        self.refresh_all()

    def manual_skip(self):
        if not self.manual_rows:
            return
        self.manual_index = min(len(self.manual_rows) - 1, self.manual_index + 1)
        self.manual_show_current()

    def manual_previous(self):
        if not self.manual_rows:
            return
        self.manual_index = max(0, self.manual_index - 1)
        self.manual_show_current()

    def manual_mark_low_quality(self):
        row = self.manual_current_row()
        if not row:
            return
        mark_crops_status([row["id"]], row["identity"], "low_quality", "manual_sort_mark_low_quality", "low_quality", "manual sorting slideshow")
        self.status.set(f"Marked crop {row['id']} low quality.")
        self.manual_advance_after_action()

    def manual_mark_multibird(self):
        row = self.manual_current_row()
        if not row:
            return
        mark_crops_status([row["id"]], row["identity"], "multibird", "manual_sort_mark_multibird", "multibird", "manual sorting slideshow")
        self.status.set(f"Marked crop {row['id']} multibird.")
        self.manual_advance_after_action()

    def manual_mark_junk(self):
        row = self.manual_current_row()
        if not row:
            return
        mark_crops_status([row["id"]], row["identity"], "junk", "manual_sort_mark_junk", "junk", "manual sorting slideshow")
        self.status.set(f"Marked crop {row['id']} junk.")
        self.manual_advance_after_action()

    def manual_mark_false_positive(self):
        row = self.manual_current_row()
        if not row:
            return
        mark_crops_status([row["id"]], row["identity"], "false_positive", "manual_sort_mark_false_positive", "false_positive", "manual sorting slideshow")
        self.status.set(f"Marked crop {row['id']} false positive.")
        self.manual_advance_after_action()

    def manual_mark_ai_suspicious(self):
        row = self.manual_current_row()
        if not row:
            return
        mark_crops_status([row["id"]], row["identity"], "ai_suspicious", "manual_sort_mark_ai_suspicious", "ai_suspicious", "manual sorting slideshow placeholder")
        self.status.set(f"Marked crop {row['id']} AI / suspicious placeholder.")
        self.manual_advance_after_action()

    def manual_move_to_sandbox(self):
        row = self.manual_current_row()
        if not row:
            return
        mark_crops_status([row["id"]], row["identity"], "sandbox", "manual_sort_move_to_sandbox", "stage_names_sandbox", "manual sorting slideshow")
        self.status.set(f"Moved crop {row['id']} to Stage Names Sandbox.")
        self.manual_advance_after_action()

    def manual_move_to_true_names(self):
        row = self.manual_current_row()
        if not row:
            return
        prompt = f"Move crop {row['id']} from {row['identity'] or 'unknown'} to True Names.\n\nChoose an existing True Name, or create a new one."
        result = ask_true_name_target(self.root, prompt, row["identity"] or "")
        if not result:
            return
        target = result["name"]
        if result["mode"] == "new" and identity_exists(target) and target not in true_name_identity_names():
            if not messagebox.askyesno("Existing raw identity", f"{target} already exists outside True Names. Use this existing identity name as the True Name target?"):
                return
        move_crops_to_identity_lifecycle([row["id"]], row["identity"], target, "active", "reviewed", "manual_sort_move_to_true_names")
        self.status.set(f"Moved crop {row['id']} to True Name {target}.")
        self.manual_advance_after_action()

    def manual_return_to_raw(self):
        row = self.manual_current_row()
        if not row:
            return
        if not messagebox.askyesno("Return to Raw Groups", f"Return crop {row['id']} to Raw Groups?\n\nThis is non-destructive and creates a database backup."):
            return
        reset_crop_ids_to_raw([row["id"]], self.manual_source_lane.get(), "manual_sort_return_to_raw")
        self.status.set(f"Returned crop {row['id']} to Raw Groups.")
        self.manual_advance_after_action()

    def manual_skip_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_skip()
            return "break"

    def manual_previous_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_previous()
            return "break"

    def manual_mark_low_quality_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_mark_low_quality()
            return "break"

    def manual_mark_multibird_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_mark_multibird()
            return "break"

    def manual_mark_junk_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_mark_junk()
            return "break"

    def manual_mark_false_positive_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_mark_false_positive()
            return "break"

    def manual_mark_ai_suspicious_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_mark_ai_suspicious()
            return "break"

    def manual_move_to_sandbox_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_move_to_sandbox()
            return "break"

    def manual_move_to_true_names_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_move_to_true_names()
            return "break"

    def manual_return_to_raw_event(self, event=None):
        if self.manual_tab_is_active():
            self.manual_return_to_raw()
            return "break"

    def undo_last_action(self):
        action = latest_cleanup_action_with_backup()
        if not action:
            messagebox.showinfo("Undo Last Action", "No logged cleanup action with an available database backup was found.")
            return
        msg = (
            "Restore the database backup from before this action?\n\n"
            f"Action: {action['action_type']}\n"
            f"Created: {action['created_at']}\n"
            f"Source: {action['source_identity'] or ''}\n"
            f"Target: {action['target_identity'] or ''}\n\n"
            "This reverts the whole database to that backup. A pre-undo backup of the current database will also be created."
        )
        if not messagebox.askyesno("Undo Last Action", msg):
            return
        try:
            pre_undo_backup = restore_database_backup(action["backup_path"], "pre-undo")
        except Exception as exc:
            messagebox.showerror("Undo failed", str(exc))
            return
        self.current_identity = None
        self.clear_workspace()
        self.refresh_all()
        self.status.set(f"Undid {action['action_type']} by restoring backup. Pre-undo backup: {pre_undo_backup}")
        messagebox.showinfo("Undo complete", "Database backup restored and verified. The view has been refreshed.")

    def build_identity_lab_tab(self, parent):
        outer = ttk.Frame(parent, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Birdbill Auto-sorting workspace", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer, text="Read-only modular sorter workspace. DINO is now one weak/context-biased module, not default Re-ID authority.", wraplength=1050).pack(anchor="w", pady=(4, 12))

        module_notebook = ttk.Notebook(outer)
        module_notebook.pack(fill="both", expand=True)
        self.dino_sort_tab = ttk.Frame(module_notebook)
        self.crop_refinement_tab = ttk.Frame(module_notebook)
        self.local_feature_sort_tab = ttk.Frame(module_notebook)
        self.fusion_sort_tab = ttk.Frame(module_notebook)
        module_notebook.add(self.dino_sort_tab, text="DINO similarity")
        module_notebook.add(self.crop_refinement_tab, text="Crop Refinement Lab")
        module_notebook.add(self.local_feature_sort_tab, text="Local features")
        module_notebook.add(self.fusion_sort_tab, text="Fusion scoring")

        main = ttk.Frame(self.dino_sort_tab, padding=8)
        main.pack(fill="both", expand=True)
        left = ttk.LabelFrame(main, text="Profiles available to sorter", padding=8)
        left.pack(side="left", fill="y", padx=(0, 10))
        self.sort_profile_list = tk.Listbox(left, width=48, height=30, selectmode="extended", exportselection=False)
        self.sort_profile_list.pack(fill="y", expand=True)
        self.sort_profile_list.bind("<<ListboxSelect>>", self.update_sort_selection_status)
        ttk.Button(left, text="Refresh Profile List", command=self.refresh_sort_profile_list).pack(fill="x", pady=(8, 2))
        ttk.Button(left, text="Select Current Reconciliation Profile", command=self.select_current_profile_in_sorter).pack(fill="x", pady=2)
        ttk.Button(left, text="Clear Sorter Selection", command=self.clear_sort_profile_selection).pack(fill="x", pady=2)
        self.sort_selection_label = ttk.Label(left, text="Sorter-selected profiles: 0", wraplength=330)
        self.sort_selection_label.pack(anchor="w", pady=(8, 0))

        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True)
        controls = ttk.LabelFrame(right, text="DINO similarity sorter", padding=10)
        controls.pack(fill="x", anchor="n")
        threshold_row = ttk.Frame(controls)
        threshold_row.pack(fill="x", pady=(0, 6))
        ttk.Label(threshold_row, text="Threshold:").pack(side="left")
        self.sort_threshold_label = ttk.Label(threshold_row, text=f"{self.sort_threshold.get():.2f}")
        self.sort_threshold_label.pack(side="left", padx=(6, 10))
        ttk.Scale(threshold_row, from_=0.50, to=0.98, variable=self.sort_threshold, command=self.update_sort_threshold_label, length=420).pack(side="left", padx=(0, 12))
        ttk.Button(threshold_row, text="Analyze", command=self.run_dino_sort_analysis).pack(side="left")
        scope_row = ttk.Frame(controls)
        scope_row.pack(fill="x", pady=(4, 0))
        ttk.Label(scope_row, text="Scope:").pack(side="left", padx=(0, 8))
        scopes = [
            ("One selected profile vs selected/all visible", "anchor_selected"),
            ("Pairwise among selected profiles", "selected_pairwise"),
            ("Current reconciliation profile vs all visible", "current_vs_visible"),
            ("All visible profiles pairwise", "all_visible"),
        ]
        for text, value in scopes:
            ttk.Radiobutton(scope_row, text=text, variable=self.sort_scope, value=value).pack(side="left", padx=(0, 10))
        self.sort_summary = tk.StringVar(value="No DINO analysis run yet.")
        ttk.Label(controls, textvariable=self.sort_summary, wraplength=1000).pack(anchor="w", pady=(8, 0))
        ttk.Label(controls, text="All Auto-sorting results are proposals only. This tab does not merge, rename, or mutate identities.", wraplength=1000).pack(anchor="w", pady=(4, 0))
        view_row = ttk.Frame(controls)
        view_row.pack(fill="x", pady=(8, 0))
        ttk.Label(view_row, text="View:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(view_row, text="Details", variable=self.sort_view_mode, value="details", command=self.update_sort_result_view).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(view_row, text="Thumbnails", variable=self.sort_view_mode, value="thumbnails", command=self.update_sort_result_view).pack(side="left", padx=(0, 8))

        results_box = ttk.LabelFrame(right, text="Similarity proposals", padding=8)
        results_box.pack(fill="both", expand=True, pady=(10, 0))
        columns = ("score", "source", "target", "suggested_action", "method", "proposal", "source_crop", "target_crop", "notes")
        self.sort_tree = ttk.Treeview(results_box, columns=columns, show="headings", height=18)
        headings = {
            "score": "Score", "source": "Source profile", "target": "Target profile", "suggested_action": "Suggested action", "method": "Method", "proposal": "Proposal",
            "source_crop": "Source crop", "target_crop": "Target crop", "notes": "Notes",
        }
        widths = {"score": 70, "source": 125, "target": 125, "suggested_action": 260, "method": 120, "proposal": 120, "source_crop": 160, "target_crop": 160, "notes": 240}
        for col in columns:
            self.sort_tree.heading(col, text=headings[col])
            self.sort_tree.column(col, width=widths[col], anchor="w")
        self.sort_tree.pack(side="left", fill="both", expand=True)
        self.sort_thumb_canvas = tk.Canvas(results_box)
        self.sort_thumb_workspace = ttk.Frame(self.sort_thumb_canvas)
        self.sort_thumb_window = self.sort_thumb_canvas.create_window((0, 0), window=self.sort_thumb_workspace, anchor="nw")
        self.sort_thumb_workspace.bind("<Configure>", lambda e: self.sort_thumb_canvas.configure(scrollregion=self.sort_thumb_canvas.bbox("all")))
        self.sort_thumb_canvas.bind("<Configure>", lambda e: self.sort_thumb_canvas.itemconfigure(self.sort_thumb_window, width=e.width))
        sort_scroll = ttk.Scrollbar(results_box, orient="vertical", command=self.sort_tree.yview)
        sort_scroll.pack(side="right", fill="y")
        self.sort_tree.configure(yscrollcommand=sort_scroll.set)
        self.sort_thumb_canvas.configure(yscrollcommand=sort_scroll.set)
        self.sort_results_box = results_box
        self.sort_scroll = sort_scroll
        result_buttons = ttk.Frame(right)
        result_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(result_buttons, text="Compare Selected Proposal", command=self.compare_selected_sort_proposal).pack(side="left")
        ttk.Button(result_buttons, text="Add Proposal Crop(s) To Sandbox", command=self.add_selected_sort_proposal_to_sandbox).pack(side="left", padx=6)
        ttk.Button(result_buttons, text="Open Source Profile", command=self.open_source_sort_profile).pack(side="left", padx=6)
        ttk.Button(result_buttons, text="Open Target Profile", command=self.open_target_sort_profile).pack(side="left", padx=6)

        self.build_crop_refinement_tab(self.crop_refinement_tab)
        self.build_lightglue_tab(self.local_feature_sort_tab)
        self.build_sorter_placeholder(self.fusion_sort_tab, "Fusion scoring", "Reserved for combined Re-ID proposals: local features, field marks, temporal plausibility, species/annotation filters, and optional DINO as one weak vote.")

    def build_crop_refinement_tab(self, parent):
        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Crop Refinement Lab", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Derived-image recipe lab for testing whether tighter crops and background suppression make local-feature Re-ID more meaningful. Raw crops are preserved. Recipe outputs are saved in output/refined-crops/<recipe-name>/ with sidecar JSON; no database writes or identity assignment.",
            wraplength=1120,
        ).pack(anchor="w", pady=(6, 10))

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(0, 8))
        ttk.Button(top, text="Refresh Identity List", command=self.refresh_refinement_identities).pack(side="left")
        ttk.Button(top, text="Use Current Raw Profile", command=self.refinement_use_current_profile).pack(side="left", padx=6)
        ttk.Button(top, text="Preview Recipe", command=self.update_refinement_preview).pack(side="left", padx=6)
        ttk.Button(top, text="Save Refined Crop", command=self.save_refined_crop).pack(side="left", padx=6)
        ttk.Button(top, text="Save Body+Gorget Set", command=self.save_refinement_standard_set).pack(side="left", padx=6)
        ttk.Button(top, text="Use Saved As LightGlue A", command=lambda: self.use_saved_refinement_as_lightglue("A")).pack(side="left", padx=6)
        ttk.Button(top, text="Use Saved As LightGlue B", command=lambda: self.use_saved_refinement_as_lightglue("B")).pack(side="left", padx=6)
        ttk.Button(top, text="Open Refined Folder", command=self.open_refined_crops_folder).pack(side="left", padx=6)
        ttk.Label(top, textvariable=self.refine_status, wraplength=650).pack(side="left", padx=12)

        panes = ttk.Panedwindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        middle = ttk.Frame(panes, padding=(8, 0, 8, 0))
        right = ttk.Frame(panes, padding=(8, 0, 0, 0))
        panes.add(left, weight=1)
        panes.add(middle, weight=2)
        panes.add(right, weight=2)

        ttk.Label(left, text="Source identity/profile").pack(anchor="w")
        self.refine_identity_combo = ttk.Combobox(left, textvariable=self.refine_identity, state="readonly", width=34)
        self.refine_identity_combo.pack(fill="x", pady=(2, 6))
        self.refine_identity_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh_refinement_crops())
        ttk.Label(left, text="Raw crops").pack(anchor="w")
        self.refine_crop_list = tk.Listbox(left, width=56, height=24, exportselection=False)
        self.refine_crop_list.pack(fill="both", expand=True)
        self.refine_crop_list.bind("<<ListboxSelect>>", lambda event: self.load_refinement_raw_preview())
        ttk.Button(left, text="Load Crops", command=self.refresh_refinement_crops).pack(fill="x", pady=(6, 0))

        recipe = ttk.LabelFrame(middle, text="Recipe controls", padding=10)
        recipe.pack(fill="x", anchor="n")
        name_row = ttk.Frame(recipe)
        name_row.pack(fill="x", pady=(0, 6))
        ttk.Label(name_row, text="Recipe name:").pack(side="left")
        ttk.Entry(name_row, textvariable=self.refine_recipe_name, width=32).pack(side="left", padx=(6, 0), fill="x", expand=True)

        preset_row = ttk.Frame(recipe)
        preset_row.pack(fill="x", pady=(0, 6))
        ttk.Label(preset_row, text="Preset:").pack(side="left")
        self.refine_preset_combo = ttk.Combobox(preset_row, textvariable=self.refine_recipe_preset, state="readonly", width=30, values=tuple(REFINEMENT_RECIPE_PRESETS.keys()))
        self.refine_preset_combo.pack(side="left", padx=(6, 8))
        self.refine_preset_combo.bind("<<ComboboxSelected>>", lambda event: self.apply_refinement_preset())
        ttk.Checkbutton(preset_row, text="Live preview", variable=self.refine_live_preview, command=self.schedule_refinement_preview).pack(side="left", padx=(12, 0))

        crop_row = ttk.Frame(recipe)
        crop_row.pack(fill="x", pady=4)
        ttk.Label(crop_row, text="Tight crop %:").pack(side="left")
        self.refine_crop_label = ttk.Label(crop_row, text=f"{self.refine_crop_percent.get():.0f}")
        self.refine_crop_label.pack(side="left", padx=(6, 8))
        ttk.Scale(crop_row, from_=0, to=40, variable=self.refine_crop_percent, command=lambda v: self.refinement_slider_changed()).pack(side="left", fill="x", expand=True)

        fx_row = ttk.Frame(recipe)
        fx_row.pack(fill="x", pady=4)
        ttk.Label(fx_row, text="Focus X:").pack(side="left")
        self.refine_focus_x_label = ttk.Label(fx_row, text=f"{self.refine_focus_x.get():.0f}")
        self.refine_focus_x_label.pack(side="left", padx=(6, 8))
        ttk.Scale(fx_row, from_=-25, to=25, variable=self.refine_focus_x, command=lambda v: self.refinement_slider_changed()).pack(side="left", fill="x", expand=True)

        fy_row = ttk.Frame(recipe)
        fy_row.pack(fill="x", pady=4)
        ttk.Label(fy_row, text="Focus Y:").pack(side="left")
        self.refine_focus_y_label = ttk.Label(fy_row, text=f"{self.refine_focus_y.get():.0f}")
        self.refine_focus_y_label.pack(side="left", padx=(6, 8))
        ttk.Scale(fy_row, from_=-25, to=25, variable=self.refine_focus_y, command=lambda v: self.refinement_slider_changed()).pack(side="left", fill="x", expand=True)

        opts = ttk.Frame(recipe)
        opts.pack(fill="x", pady=4)
        ttk.Checkbutton(opts, text="Square normalize", variable=self.refine_square, command=self.schedule_refinement_preview).pack(side="left")
        ttk.Label(opts, text="Background:").pack(side="left", padx=(16, 6))
        self.refine_background_combo = ttk.Combobox(opts, textvariable=self.refine_background_mode, state="readonly", width=24, values=("none", "blur outside ellipse", "gray outside ellipse", "neutral fill outside ellipse"))
        self.refine_background_combo.pack(side="left")
        self.refine_background_combo.bind("<<ComboboxSelected>>", lambda event: self.schedule_refinement_preview())

        blur_row = ttk.Frame(recipe)
        blur_row.pack(fill="x", pady=4)
        ttk.Label(blur_row, text="Blur radius:").pack(side="left")
        self.refine_blur_label = ttk.Label(blur_row, text=f"{self.refine_bg_blur_radius.get():.0f}")
        self.refine_blur_label.pack(side="left", padx=(6, 8))
        ttk.Scale(blur_row, from_=0, to=24, variable=self.refine_bg_blur_radius, command=lambda v: self.refinement_slider_changed()).pack(side="left", fill="x", expand=True)

        resize_row = ttk.Frame(recipe)
        resize_row.pack(fill="x", pady=4)
        ttk.Label(resize_row, text="Resize max side:").pack(side="left")
        ttk.Spinbox(resize_row, from_=0, to=1600, increment=64, textvariable=self.refine_resize_max_side, width=8, command=self.schedule_refinement_preview).pack(side="left", padx=(6, 4))
        ttk.Label(resize_row, text="0 = keep size").pack(side="left")

        ttk.Label(middle, text="Raw crop preview").pack(anchor="w", pady=(10, 2))
        self.refine_raw_label = ttk.Label(middle, text="Select a crop to preview raw evidence.")
        self.refine_raw_label.pack(anchor="w")

        ttk.Label(right, text="Refined candidate preview").pack(anchor="w")
        self.refine_preview_label = ttk.Label(right, text="Click Preview Recipe after selecting a crop.")
        self.refine_preview_label.pack(anchor="w")
        ttk.Label(right, text="Recipe outputs are derived evidence artifacts. They are intentionally storage-heavy during experimentation and should not replace raw crops.", wraplength=520).pack(anchor="w", pady=(8, 0))

        self.refresh_refinement_identities()

    def refinement_slider_changed(self):
        self.update_refinement_control_labels()
        self.refine_recipe_preset.set("current/custom")
        self.schedule_refinement_preview()

    def update_refinement_control_labels(self):
        try:
            self.refine_crop_label.configure(text=f"{self.refine_crop_percent.get():.0f}")
            self.refine_focus_x_label.configure(text=f"{self.refine_focus_x.get():.0f}")
            self.refine_focus_y_label.configure(text=f"{self.refine_focus_y.get():.0f}")
            self.refine_blur_label.configure(text=f"{self.refine_bg_blur_radius.get():.0f}")
        except Exception:
            pass

    def schedule_refinement_preview(self):
        if not getattr(self, "refine_live_preview", None) or not self.refine_live_preview.get():
            return
        try:
            if self.refine_preview_after_id is not None:
                self.root.after_cancel(self.refine_preview_after_id)
        except Exception:
            pass
        try:
            self.refine_preview_after_id = self.root.after(250, self.update_refinement_preview)
        except Exception:
            self.update_refinement_preview()

    def refinement_recipe_state(self):
        return {
            "recipe_name": self.refine_recipe_name.get(),
            "crop_percent": float(self.refine_crop_percent.get()),
            "focus_x": float(self.refine_focus_x.get()),
            "focus_y": float(self.refine_focus_y.get()),
            "square": bool(self.refine_square.get()),
            "background": self.refine_background_mode.get(),
            "blur_radius": float(self.refine_bg_blur_radius.get()),
            "resize_max_side": int(self.refine_resize_max_side.get() or 0),
        }

    def apply_refinement_recipe_state(self, state):
        self.refine_recipe_name.set(state.get("recipe_name") or self.refine_recipe_name.get() or "recipe")
        self.refine_crop_percent.set(float(state.get("crop_percent", self.refine_crop_percent.get())))
        self.refine_focus_x.set(float(state.get("focus_x", self.refine_focus_x.get())))
        self.refine_focus_y.set(float(state.get("focus_y", self.refine_focus_y.get())))
        self.refine_square.set(bool(state.get("square", self.refine_square.get())))
        self.refine_background_mode.set(state.get("background", self.refine_background_mode.get()))
        self.refine_bg_blur_radius.set(float(state.get("blur_radius", self.refine_bg_blur_radius.get())))
        self.refine_resize_max_side.set(int(state.get("resize_max_side", self.refine_resize_max_side.get() or 0)))
        self.update_refinement_control_labels()

    def apply_refinement_preset(self):
        preset_name = self.refine_recipe_preset.get() or "current/custom"
        preset = REFINEMENT_RECIPE_PRESETS.get(preset_name)
        if not preset:
            self.schedule_refinement_preview()
            return
        state = dict(preset)
        state["recipe_name"] = preset_name
        self.apply_refinement_recipe_state(state)
        self.update_refinement_preview()

    def refresh_refinement_identities(self):
        rows = get_identities(include_false_positive=False, include_multibird=True, include_low_quality=True)
        values = [row["identity"] for row in rows if not row.get("special_group") and row["identity"] != MULTIBIRD_GROUP]
        combo = getattr(self, "refine_identity_combo", None)
        if combo is not None:
            combo.configure(values=values)
        if values and not self.refine_identity.get():
            self.refine_identity.set(values[0])
        self.refresh_refinement_crops()
        self.refine_status.set(f"Loaded {len(values)} identities for refinement testing.")

    def refresh_refinement_crops(self):
        identity = self.refine_identity.get()
        rows = get_crops(identity, limit=800) if identity else []
        self.refine_rows = rows
        if not hasattr(self, "refine_crop_list"):
            return
        self.refine_crop_list.delete(0, tk.END)
        for row in rows:
            score = row["visual_score"]
            score_text = "n/a" if score in (None, "") else str(score)
            self.refine_crop_list.insert(tk.END, f"id {row['id']} | {Path(row['crop_path']).name} | status:{row['identity_status'] or 'n/a'} | score:{score_text}")
        if rows:
            self.refine_crop_list.selection_set(0)
            self.load_refinement_raw_preview()
        else:
            self.refine_raw_label.configure(image="", text="No crops loaded for this identity.")
            self.refine_preview_label.configure(image="", text="No refined preview yet.")

    def refinement_use_current_profile(self):
        if not self.current_identity or self.current_identity == MULTIBIRD_GROUP:
            messagebox.showinfo("Crop Refinement Lab", "Open a normal Raw Groups profile first.")
            return
        self.refine_identity.set(self.current_identity)
        self.refresh_refinement_crops()

    def selected_refinement_crop_row(self):
        if not hasattr(self, "refine_crop_list"):
            return None
        selection = self.refine_crop_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index < 0 or index >= len(self.refine_rows):
            return None
        return self.refine_rows[index]

    def load_refinement_raw_preview(self):
        row = self.selected_refinement_crop_row()
        if row is None:
            return
        path = Path(row["crop_path"])
        if not path.exists():
            self.refine_raw_label.configure(image="", text=f"Missing raw crop:\n{path}")
            return
        try:
            if not PIL_AVAILABLE:
                self.refine_raw_label.configure(image="", text="Pillow is required for Crop Refinement Lab previews.")
                return
            img = Image.open(path).convert("RGB")
            preview = img.copy()
            preview.thumbnail((520, 420))
            self.refine_raw_photo = ImageTk.PhotoImage(preview)
            self.refine_raw_label.configure(image=self.refine_raw_photo, text="")
            self.update_refinement_preview()
        except Exception as exc:
            self.refine_raw_label.configure(image="", text=f"Could not load raw crop:\n{exc}")

    def make_refined_image(self, image_path):
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is required for Crop Refinement Lab.")
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        if w <= 1 or h <= 1:
            return img

        pct = max(0.0, min(45.0, float(self.refine_crop_percent.get()))) / 100.0
        keep_w = max(2, int(w * (1.0 - 2.0 * pct)))
        keep_h = max(2, int(h * (1.0 - 2.0 * pct)))
        shift_x = float(self.refine_focus_x.get()) / 100.0 * w * 0.5
        shift_y = float(self.refine_focus_y.get()) / 100.0 * h * 0.5
        cx = w / 2.0 + shift_x
        cy = h / 2.0 + shift_y
        left = int(round(cx - keep_w / 2.0))
        top = int(round(cy - keep_h / 2.0))
        left = max(0, min(w - keep_w, left))
        top = max(0, min(h - keep_h, top))
        img = img.crop((left, top, left + keep_w, top + keep_h))

        if self.refine_square.get():
            sw, sh = img.size
            side = min(sw, sh)
            left = max(0, (sw - side) // 2)
            top = max(0, (sh - side) // 2)
            img = img.crop((left, top, left + side, top + side))

        mode = (self.refine_background_mode.get() or "none").lower()
        if mode != "none":
            iw, ih = img.size
            mask = Image.new("L", (iw, ih), 0)
            from PIL import ImageDraw
            draw = ImageDraw.Draw(mask)
            pad_x = int(iw * 0.12)
            pad_y = int(ih * 0.12)
            draw.ellipse((pad_x, pad_y, iw - pad_x, ih - pad_y), fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=max(1, int(min(iw, ih) * 0.025))))
            if mode.startswith("blur"):
                bg = img.filter(ImageFilter.GaussianBlur(radius=max(0.0, float(self.refine_bg_blur_radius.get()))))
            elif mode.startswith("gray"):
                bg = ImageOps.grayscale(img).convert("RGB")
            else:
                bg = Image.new("RGB", (iw, ih), (128, 128, 128))
            img = Image.composite(img, bg, mask)

        max_side = int(self.refine_resize_max_side.get() or 0)
        if max_side > 0:
            img = img.copy()
            img.thumbnail((max_side, max_side))
        return img

    def update_refinement_preview(self):
        self.refine_preview_after_id = None
        row = self.selected_refinement_crop_row()
        if row is None:
            self.refine_preview_label.configure(image="", text="Select a raw crop first.")
            return
        path = Path(row["crop_path"])
        if not path.exists():
            self.refine_preview_label.configure(image="", text=f"Missing raw crop:\n{path}")
            return
        try:
            refined = self.make_refined_image(path)
            self.refine_preview_image = refined.copy()
            preview = refined.copy()
            preview.thumbnail((560, 500))
            self.refine_preview_photo = ImageTk.PhotoImage(preview)
            self.refine_preview_label.configure(image=self.refine_preview_photo, text="")
            self.refine_status.set(f"Previewed recipe '{self.refine_recipe_name.get().strip() or 'unnamed'}' for crop id {row['id']}.")
        except Exception as exc:
            self.refine_preview_image = None
            self.refine_preview_label.configure(image="", text=f"Could not refine crop:\n{exc}")

    def safe_recipe_name(self):
        text = (self.refine_recipe_name.get() or "recipe").strip()
        keep = []
        for ch in text:
            if ch.isalnum() or ch in ("-", "_"):
                keep.append(ch)
            else:
                keep.append("-")
        cleaned = "".join(keep).strip("-_")
        return cleaned or "recipe"

    def save_refined_crop_to_path(self, row):
        path = Path(row["crop_path"])
        refined = self.make_refined_image(path)
        identity = str(row["identity"] or "unknown")
        stem = Path(row["crop_path"]).stem
        recipe = self.safe_recipe_name()
        recipe_dir = REFINED_CROPS_DIR / recipe
        recipe_dir.mkdir(parents=True, exist_ok=True)
        stamp = now_stamp()
        out_path = recipe_dir / f"crop{row['id']}-{identity}-{recipe}-{stamp}-{stem}.png"
        refined.save(out_path)
        manifest = {
            "app_version": APP_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_crop_id": row["id"],
            "source_identity": row["identity"],
            "source_crop_path": row["crop_path"],
            "refined_crop_path": str(out_path),
            "recipe_name": recipe,
            "parameters": self.refinement_recipe_state(),
            "notes": "Derived refinement artifact for evidence testing. Raw crop remains canonical.",
        }
        out_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.refine_preview_image = refined.copy()
        return out_path

    def save_refined_crop(self):
        row = self.selected_refinement_crop_row()
        if row is None:
            messagebox.showinfo("Crop Refinement Lab", "Select a raw crop first.")
            return
        path = Path(row["crop_path"])
        if not path.exists():
            messagebox.showerror("Crop Refinement Lab", f"Raw crop is missing:\n{path}")
            return
        try:
            out_path = self.save_refined_crop_to_path(row)
            self.refine_last_saved_path = str(out_path)
            self.refine_status.set(f"Saved refined crop: {out_path}")
            self.update_lightglue_override_label()
        except Exception as exc:
            messagebox.showerror("Crop Refinement Lab", f"Could not save refined crop:\n{exc}")

    def save_refinement_standard_set(self):
        row = self.selected_refinement_crop_row()
        if row is None:
            messagebox.showinfo("Crop Refinement Lab", "Select a raw crop first.")
            return
        path = Path(row["crop_path"])
        if not path.exists():
            messagebox.showerror("Crop Refinement Lab", f"Raw crop is missing:\n{path}")
            return
        original_state = self.refinement_recipe_state()
        original_preset = self.refine_recipe_preset.get()
        saved_paths = []
        try:
            for preset_name in REFINEMENT_STANDARD_SET:
                preset = REFINEMENT_RECIPE_PRESETS.get(preset_name)
                if not preset:
                    continue
                state = dict(preset)
                state["recipe_name"] = preset_name
                self.refine_recipe_preset.set(preset_name)
                self.apply_refinement_recipe_state(state)
                saved_paths.append(self.save_refined_crop_to_path(row))
            if saved_paths:
                self.refine_last_saved_path = str(saved_paths[-1])
                self.refine_status.set("Saved standard refinement set: " + " | ".join(str(p) for p in saved_paths))
                self.update_refinement_preview()
                self.update_lightglue_override_label()
        except Exception as exc:
            messagebox.showerror("Crop Refinement Lab", f"Could not save standard refinement set:\n{exc}")

        if not saved_paths:
            self.refine_recipe_preset.set(original_preset)
            self.apply_refinement_recipe_state(original_state)

    def use_saved_refinement_as_lightglue(self, side):
        if not self.refine_last_saved_path:
            messagebox.showinfo("Crop Refinement Lab", "Save a refined crop first.")
            return
        path = Path(self.refine_last_saved_path)
        if not path.exists():
            messagebox.showerror("Crop Refinement Lab", f"Saved refined crop is missing:\n{path}")
            return
        if side == "A":
            self.lightglue_override_a = str(path)
        else:
            self.lightglue_override_b = str(path)
        self.update_lightglue_override_label()
        self.refine_status.set(f"Using latest saved refined crop as LightGlue Image {side}: {path}")

    def clear_lightglue_overrides(self):
        self.lightglue_override_a = ""
        self.lightglue_override_b = ""
        self.update_lightglue_override_label()

    def update_lightglue_override_label(self):
        label = getattr(self, "lightglue_override_label", None)
        if label is None:
            return
        a = Path(self.lightglue_override_a).name if self.lightglue_override_a else "DB crop selection"
        b = Path(self.lightglue_override_b).name if self.lightglue_override_b else "DB crop selection"
        label.configure(text=f"LightGlue inputs: A={a} | B={b}")

    def open_refined_crops_folder(self):
        REFINED_CROPS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(REFINED_CROPS_DIR))
            else:
                subprocess.Popen(["xdg-open", str(REFINED_CROPS_DIR)])
        except Exception as exc:
            messagebox.showerror("Crop Refinement Lab", f"Could not open refined crop folder:\n{exc}")

    def build_lightglue_tab(self, parent):
        frame = ttk.Frame(parent, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="LightGlue local-feature tester", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Read-only pairwise local-feature verification using existing lightgluetest.py. This does not write the database, does not assign identities, and is not part of ingestion.",
            wraplength=1100,
        ).pack(anchor="w", pady=(6, 10))

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Button(controls, text="Refresh Identity Lists", command=self.refresh_lightglue_identities).pack(side="left")
        ttk.Button(controls, text="Use Current Raw Profile As A", command=self.lightglue_use_current_as_a).pack(side="left", padx=6)
        ttk.Button(controls, text="Run LightGlue Pair Test", command=self.run_lightglue_gui_pair).pack(side="left", padx=6)
        ttk.Button(controls, text="Open Match Image", command=self.open_lightglue_match_image).pack(side="left", padx=6)
        ttk.Button(controls, text="Clear Refined A/B", command=self.clear_lightglue_overrides).pack(side="left", padx=6)
        ttk.Label(controls, textvariable=self.lightglue_status, wraplength=650).pack(side="left", padx=12)
        self.lightglue_override_label = ttk.Label(frame, text="LightGlue inputs: A=DB crop selection | B=DB crop selection", wraplength=1120)
        self.lightglue_override_label.pack(anchor="w", pady=(0, 8))

        panes = ttk.Panedwindow(frame, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        middle = ttk.Frame(panes, padding=(8, 0, 8, 0))
        right = ttk.Frame(panes, padding=(8, 0, 0, 0))
        panes.add(left, weight=1)
        panes.add(middle, weight=1)
        panes.add(right, weight=2)

        self.build_lightglue_picker(left, "A", self.lightglue_identity_a)
        self.build_lightglue_picker(middle, "B", self.lightglue_identity_b)

        ttk.Label(right, text="Result summary").pack(anchor="w")
        self.lightglue_output = tk.Text(right, height=18, wrap="word")
        self.lightglue_output.pack(fill="both", expand=True)
        self.lightglue_image_label = ttk.Label(right, text="Match visualization will appear here after a successful run.")
        self.lightglue_image_label.pack(anchor="w", pady=(8, 0))
        self.refresh_lightglue_identities()

    def build_lightglue_picker(self, parent, label, variable):
        ttk.Label(parent, text=f"Image {label}: identity/profile").pack(anchor="w")
        combo = ttk.Combobox(parent, textvariable=variable, state="readonly", width=34)
        combo.pack(fill="x", pady=(2, 6))
        crop_list = tk.Listbox(parent, width=58, height=24, exportselection=False)
        crop_list.pack(fill="both", expand=True)
        if label == "A":
            self.lightglue_identity_combo_a = combo
            self.lightglue_crop_list_a = crop_list
            combo.bind("<<ComboboxSelected>>", lambda event: self.refresh_lightglue_crops("A"))
        else:
            self.lightglue_identity_combo_b = combo
            self.lightglue_crop_list_b = crop_list
            combo.bind("<<ComboboxSelected>>", lambda event: self.refresh_lightglue_crops("B"))
        ttk.Button(parent, text=f"Load crops for {label}", command=lambda: self.refresh_lightglue_crops(label)).pack(fill="x", pady=(6, 0))

    def refresh_lightglue_identities(self):
        rows = get_identities(include_false_positive=False, include_multibird=True, include_low_quality=True)
        values = [row["identity"] for row in rows if not row.get("special_group") and row["identity"] != MULTIBIRD_GROUP]
        for combo_name in ("lightglue_identity_combo_a", "lightglue_identity_combo_b"):
            combo = getattr(self, combo_name, None)
            if combo is not None:
                combo.configure(values=values)
        if values and not self.lightglue_identity_a.get():
            self.lightglue_identity_a.set(values[0])
        if len(values) > 1 and not self.lightglue_identity_b.get():
            self.lightglue_identity_b.set(values[1])
        elif values and not self.lightglue_identity_b.get():
            self.lightglue_identity_b.set(values[0])
        self.refresh_lightglue_crops("A")
        self.refresh_lightglue_crops("B")
        self.lightglue_status.set(f"Loaded {len(values)} normal identities for LightGlue testing.")

    def refresh_lightglue_crops(self, side):
        identity = self.lightglue_identity_a.get() if side == "A" else self.lightglue_identity_b.get()
        rows = get_crops(identity, limit=500) if identity else []
        listbox = self.lightglue_crop_list_a if side == "A" else self.lightglue_crop_list_b
        listbox.delete(0, tk.END)
        for row in rows:
            score = row["visual_score"]
            score_text = "n/a" if score in (None, "") else str(score)
            listbox.insert(tk.END, f"id {row['id']} | {Path(row['crop_path']).name} | status:{row['identity_status'] or 'n/a'} | score:{score_text}")
        if rows:
            listbox.selection_set(0)
        if side == "A":
            self.lightglue_rows_a = rows
        else:
            self.lightglue_rows_b = rows

    def lightglue_use_current_as_a(self):
        if not self.current_identity or self.current_identity == MULTIBIRD_GROUP:
            messagebox.showinfo("LightGlue", "Open a normal Raw Groups profile first.")
            return
        self.lightglue_identity_a.set(self.current_identity)
        self.refresh_lightglue_crops("A")

    def selected_lightglue_crop_row(self, side):
        listbox = self.lightglue_crop_list_a if side == "A" else self.lightglue_crop_list_b
        rows = self.lightglue_rows_a if side == "A" else self.lightglue_rows_b
        selection = listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if index < 0 or index >= len(rows):
            return None
        return rows[index]

    def run_lightglue_gui_pair(self):
        row_a = self.selected_lightglue_crop_row("A")
        row_b = self.selected_lightglue_crop_row("B")
        if self.lightglue_override_a:
            image_a = Path(self.lightglue_override_a)
        else:
            if row_a is None:
                messagebox.showinfo("LightGlue", "Select one DB crop for Image A or send a refined crop from Crop Refinement Lab.")
                return
            image_a = Path(row_a["crop_path"])
        if self.lightglue_override_b:
            image_b = Path(self.lightglue_override_b)
        else:
            if row_b is None:
                messagebox.showinfo("LightGlue", "Select one DB crop for Image B or send a refined crop from Crop Refinement Lab.")
                return
            image_b = Path(row_b["crop_path"])
        if not image_a.exists() or not image_b.exists():
            messagebox.showerror("LightGlue", f"One or both selected crop files are missing.\n\nA: {image_a}\nB: {image_b}")
            return
        if not LIGHTGLUE_SCRIPT.exists():
            messagebox.showerror("LightGlue", f"lightgluetest.py was not found beside cleanupGUI.py.\n\nExpected:\n{LIGHTGLUE_SCRIPT}")
            return
        self.lightglue_status.set("Running LightGlue pair test... GUI will update when finished.")
        self.lightglue_output.delete("1.0", tk.END)
        self.lightglue_output.insert(tk.END, f"Running:\nA: {image_a}\nB: {image_b}\n\n")
        self.lightglue_image_label.configure(image="", text="Running LightGlue...")
        self.lightglue_match_image_path = ""
        thread = threading.Thread(target=self._lightglue_worker, args=(str(image_a), str(image_b)), daemon=True)
        thread.start()

    def _lightglue_worker(self, image_a, image_b):
        try:
            completed = subprocess.run(
                [sys.executable, str(LIGHTGLUE_SCRIPT), image_a, image_b],
                cwd=str(PROJECT_ROOT),
                input="\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            output = completed.stdout or ""
            parsed = self.parse_lightglue_output(output)
            parsed["returncode"] = completed.returncode
            self.root.after(0, lambda: self.finish_lightglue_run(output, parsed))
        except Exception as exc:
            self.root.after(0, lambda: self.finish_lightglue_run(f"LightGlue GUI run failed:\n{exc}", {"returncode": -1}))

    def parse_lightglue_output(self, output):
        parsed = {"report": "", "json": "", "match_image": ""}
        for line in (output or "").splitlines():
            clean = line.strip()
            if clean.startswith("Report:"):
                parsed["report"] = clean.split("Report:", 1)[1].strip()
            elif clean.startswith("JSON:"):
                parsed["json"] = clean.split("JSON:", 1)[1].strip()
            elif clean.startswith("Match image:"):
                value = clean.split("Match image:", 1)[1].strip()
                parsed["match_image"] = "" if value.lower() == "n/a" else value
        return parsed

    def finish_lightglue_run(self, output, parsed):
        self.lightglue_output.delete("1.0", tk.END)
        self.lightglue_output.insert(tk.END, output or "No LightGlue output captured.")
        code = parsed.get("returncode")
        status = "LightGlue completed." if code == 0 else f"LightGlue finished with return code {code}."
        extras = []
        if parsed.get("report"):
            extras.append(f"Report: {parsed['report']}")
        if parsed.get("json"):
            extras.append(f"JSON: {parsed['json']}")
        if parsed.get("match_image"):
            extras.append(f"Match image: {parsed['match_image']}")
        self.lightglue_status.set(status if not extras else status + " " + " | ".join(extras))
        self.lightglue_match_image_path = parsed.get("match_image") or ""
        self.load_lightglue_match_preview()

    def load_lightglue_match_preview(self):
        path = Path(self.lightglue_match_image_path) if self.lightglue_match_image_path else None
        if not path or not path.exists():
            self.lightglue_image_label.configure(image="", text="No match image available.")
            self.lightglue_photo = None
            return
        try:
            if PIL_AVAILABLE:
                img = Image.open(path)
                img.thumbnail((620, 360))
                self.lightglue_photo = ImageTk.PhotoImage(img)
            else:
                self.lightglue_photo = tk.PhotoImage(file=str(path))
            self.lightglue_image_label.configure(image=self.lightglue_photo, text="")
        except Exception as exc:
            self.lightglue_photo = None
            self.lightglue_image_label.configure(image="", text=f"Could not load match image preview:\n{exc}")

    def open_lightglue_match_image(self):
        if not self.lightglue_match_image_path:
            messagebox.showinfo("LightGlue", "No match image has been generated yet.")
            return
        path = Path(self.lightglue_match_image_path)
        if not path.exists():
            messagebox.showerror("LightGlue", f"Match image does not exist:\n{path}")
            return
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("LightGlue", f"Could not open match image:\n{exc}")

    def build_sorter_placeholder(self, parent, title, body):
        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(frame, text=body, wraplength=1000).pack(anchor="w", pady=(8, 0))
        ttk.Label(frame, text="Planned module workspace. No database writes from sorter modules unless a later explicit user-authorized action layer is implemented.", wraplength=1000).pack(anchor="w", pady=(8, 0))

    def build_species_tab(self, parent):
        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="SpeciesNet / SpeciesID annotation module", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="SpeciesID is now treated as an optional annotation/sorting module, not identity authority. SpeciesNet can write annotations, but Birdbill Re-ID remains profile/user-authorized.", wraplength=1100).pack(anchor="w", pady=(6, 12))
        button_row = ttk.Frame(frame)
        button_row.pack(fill="x")
        ttk.Button(button_row, text="Run Species ID...", command=self.run_species_id).pack(side="left")
        ttk.Label(frame, text="Future direction: expose species annotators as selectable modules alongside Re-ID sorters, with raw details kept for debugging and conservative visible labels.", wraplength=1100).pack(anchor="w", pady=(12, 0))

    def build_ai_detection_tab(self, parent):
        frame = ttk.Frame(parent, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="AI Detection workspace", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Core beta tab placeholder for conservative fake/AI-video cue detection. Early detector goal: high-confidence suspicious cues only, not broad overclaiming.", wraplength=1100).pack(anchor="w", pady=(6, 12))
        ttk.Label(frame, text="Planned inputs: imported videos, known-fake library checks, watermark/OCR cues, metadata scan, temporal artifact scan, and manual labels: likely real, suspicious, confirmed fake, unknown.", wraplength=1100).pack(anchor="w")
        ttk.Button(frame, text="Import Video(s) - planned", state="disabled").pack(anchor="w", pady=(14, 0))

    def update_sort_threshold_label(self, value=None):
        try:
            self.sort_threshold_label.configure(text=f"{float(self.sort_threshold.get()):.2f}")
        except Exception:
            pass

    def refresh_sort_profile_list(self):
        if not hasattr(self, "sort_profile_list"):
            return
        self.sort_profile_list.delete(0, tk.END)
        for row in self.identity_rows:
            if row.get("special_group") or row["identity"] == MULTIBIRD_GROUP:
                continue
            avg = row["avg_score"]
            avg_text = "n/a" if avg is None else f"{avg:.3f}"
            self.sort_profile_list.insert(tk.END, f"{row['identity']}   crops:{row['crop_count']}   avg:{avg_text}")
        self.update_sort_selection_status()

    def selected_sort_identities(self):
        selections = self.sort_profile_list.curselection() if hasattr(self, "sort_profile_list") else []
        visible_normal = [row["identity"] for row in self.identity_rows if not row.get("special_group") and row["identity"] != MULTIBIRD_GROUP]
        return [visible_normal[i] for i in selections if i < len(visible_normal)]

    def update_sort_selection_status(self, event=None):
        if hasattr(self, "sort_selection_label"):
            ids = self.selected_sort_identities()
            preview = ", ".join(ids[:4])
            if len(ids) > 4:
                preview += f", +{len(ids) - 4} more"
            suffix = "" if not preview else f"\n{preview}"
            self.sort_selection_label.configure(text=f"Sorter-selected profiles: {len(ids)}{suffix}")

    def select_current_profile_in_sorter(self):
        if not self.current_identity or self.current_identity == MULTIBIRD_GROUP:
            messagebox.showinfo("Current profile", "Open a normal reconciliation profile first.")
            return
        visible_normal = [row["identity"] for row in self.identity_rows if not row.get("special_group") and row["identity"] != MULTIBIRD_GROUP]
        self.sort_profile_list.selection_clear(0, tk.END)
        if self.current_identity in visible_normal:
            idx = visible_normal.index(self.current_identity)
            self.sort_profile_list.selection_set(idx)
            self.sort_profile_list.see(idx)
        self.update_sort_selection_status()

    def clear_sort_profile_selection(self):
        if hasattr(self, "sort_profile_list"):
            self.sort_profile_list.selection_clear(0, tk.END)
            self.update_sort_selection_status()

    def run_dino_sort_analysis(self):
        threshold = float(self.sort_threshold.get())
        scope = self.sort_scope.get()
        selected = self.selected_sort_identities()
        visible = [row["identity"] for row in self.identity_rows if not row.get("special_group") and row["identity"] != MULTIBIRD_GROUP]
        anchor = None
        identities = []
        scope_label = scope
        if scope == "anchor_selected":
            if not selected:
                messagebox.showinfo("Select profile", "Select at least one profile in the Auto-sorting profile list.")
                return
            anchor = selected[0]
            identities = selected if len(selected) >= 2 else visible
            scope_label = f"anchor {anchor} vs {'selected profiles' if len(selected) >= 2 else 'all visible profiles'}"
        elif scope == "selected_pairwise":
            if len(selected) < 2:
                messagebox.showinfo("Select profiles", "Select at least two sorter profiles for pairwise analysis.")
                return
            identities = selected
            scope_label = "selected profiles pairwise"
        elif scope == "current_vs_visible":
            if not self.current_identity or self.current_identity == MULTIBIRD_GROUP:
                messagebox.showinfo("Current profile", "Open a normal reconciliation profile first.")
                return
            anchor = self.current_identity
            identities = visible
            if anchor not in identities:
                identities.append(anchor)
            scope_label = f"current profile {anchor} vs all visible profiles"
        else:
            identities = visible
            scope_label = "all visible profiles pairwise"
        if len(identities) < 2:
            messagebox.showinfo("Not enough profiles", "DINO sorting needs at least two normal profiles with embeddings.")
            return
        self.sort_summary.set(f"Running DINO analysis: {scope_label}...")
        self.root.update_idletasks()
        analysis = analyze_dino_identity_similarity(identities=identities, threshold=threshold, max_per_identity=25, max_results=250, anchor_identity=anchor)
        self.sort_results = analysis["results"]
        for item in self.sort_tree.get_children():
            self.sort_tree.delete(item)
        self.populate_sort_results_view()
        self.sort_summary.set(
            f"DINO analysis complete: {scope_label}. Records: {analysis['records_loaded']}; profiles: {analysis['identities_loaded']}; comparisons: {analysis['comparisons']}; proposals shown: {len(self.sort_results)} of {analysis['total_results']}; threshold: {threshold:.2f}."
        )

    def populate_sort_results_view(self):
        for item in self.sort_tree.get_children():
            self.sort_tree.delete(item)
        if self.sort_thumb_workspace is not None:
            for child in self.sort_thumb_workspace.winfo_children():
                child.destroy()
        for index, row in enumerate(self.sort_results):
            self.sort_tree.insert("", tk.END, iid=str(index), values=(
                f"{row['score']:.4f}",
                row["source_identity"],
                row["target_identity"],
                row.get("suggested_action", "Review evidence before any identity action."),
                row.get("method", "dino_similarity"),
                row.get("proposal", "compare_profiles"),
                Path(row["source_crop"]).name,
                Path(row["target_crop"]).name,
                row.get("notes", ""),
            ))
            self.add_sort_thumbnail_row(index, row)
        self.update_sort_result_view()

    def update_sort_result_view(self):
        if not hasattr(self, "sort_tree") or self.sort_thumb_canvas is None:
            return
        mode = self.sort_view_mode.get()
        if mode == "thumbnails":
            self.sort_tree.pack_forget()
            self.sort_thumb_canvas.pack(side="left", fill="both", expand=True)
            self.sort_scroll.configure(command=self.sort_thumb_canvas.yview)
            self.sort_thumb_canvas.configure(yscrollcommand=self.sort_scroll.set)
        else:
            self.sort_thumb_canvas.pack_forget()
            self.sort_tree.pack(side="left", fill="both", expand=True)
            self.sort_scroll.configure(command=self.sort_tree.yview)
            self.sort_tree.configure(yscrollcommand=self.sort_scroll.set)

    def add_sort_thumbnail_row(self, index, row):
        if self.sort_thumb_workspace is None:
            return
        card = ttk.Frame(self.sort_thumb_workspace, borderwidth=2, relief="groove", padding=8)
        card.pack(fill="x", padx=4, pady=4)
        header = f"{index + 1}. {row['source_identity']} ↔ {row['target_identity']} | score {row['score']:.4f}"
        ttk.Label(card, text=header, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(card, text=row.get("suggested_action", "Review evidence before any identity action."), wraplength=1000).pack(anchor="w", pady=(2, 6))
        ttk.Button(card, text="Add These Evidence Crop(s) To Sandbox", command=lambda r=row: self.add_sort_row_to_sandbox(r)).pack(anchor="w", pady=(0, 6))
        img_row = ttk.Frame(card)
        img_row.pack(anchor="w")
        for label, path_text in (("Source", row.get("source_crop", "")), ("Target", row.get("target_crop", ""))):
            holder = ttk.Frame(img_row, padding=(0, 0, 12, 0))
            holder.pack(side="left", anchor="n")
            photo = self.load_sort_thumbnail(path_text)
            if photo is not None:
                image_label = ttk.Label(holder, image=photo)
                image_label.image = photo
                image_label.pack()
                self.image_refs.append(photo)
            else:
                ttk.Label(holder, text="[missing image]", width=24).pack()
            ttk.Label(holder, text=f"{label}: {Path(path_text).name}", wraplength=260).pack()
        ttk.Label(card, text=row.get("notes", ""), wraplength=1000).pack(anchor="w", pady=(6, 0))

    def load_sort_thumbnail(self, path_text):
        path = Path(path_text)
        if not path.exists():
            return None
        try:
            if PIL_AVAILABLE:
                img = Image.open(path)
                img.thumbnail((180, 180))
                return ImageTk.PhotoImage(img)
            return tk.PhotoImage(file=str(path))
        except Exception:
            return None

    def selected_sort_result(self):
        selection = self.sort_tree.selection()
        if not selection:
            return None
        try:
            return self.sort_results[int(selection[0])]
        except Exception:
            return None

    def add_sort_row_to_sandbox(self, result):
        if not result:
            return
        crop_paths = [result.get("source_crop"), result.get("target_crop")]
        note = (
            "Added from DINO proposal to Stage Names Sandbox; "
            f"source={result.get('source_identity')}; target={result.get('target_identity')}; "
            f"score={result.get('score')}"
        )
        count = add_crop_paths_to_sandbox(crop_paths, result.get("source_identity"), note)
        if count <= 0:
            messagebox.showinfo("Sandbox", "No matching crop rows were found for this proposal.")
            return
        self.refresh_sandbox_tab()
        self.status.set(f"Added {count} DINO proposal crop(s) to Stage Names Sandbox.")
        messagebox.showinfo("Sandbox", f"Added {count} crop(s) to Stage Names Sandbox. This did not create or merge true identities.")

    def add_selected_sort_proposal_to_sandbox(self):
        result = self.selected_sort_result()
        if not result:
            messagebox.showinfo("Sandbox", "Select a similarity proposal first.")
            return
        self.add_sort_row_to_sandbox(result)

    def compare_selected_sort_proposal(self):
        result = self.selected_sort_result()
        if not result:
            messagebox.showinfo("Compare proposal", "Select a similarity proposal first.")
            return
        self.notebook.select(self.reconcile_tab)
        self.identity_lab_notebook.select(self.raw_groups_tab)
        self.show_comparison([result["source_identity"], result["target_identity"]])

    def open_source_sort_profile(self):
        result = self.selected_sort_result()
        if not result:
            messagebox.showinfo("Open profile", "Select a similarity proposal first.")
            return
        self.notebook.select(self.reconcile_tab)
        self.identity_lab_notebook.select(self.raw_groups_tab)
        self.open_identity(result["source_identity"])

    def open_target_sort_profile(self):
        result = self.selected_sort_result()
        if not result:
            messagebox.showinfo("Open profile", "Select a similarity proposal first.")
            return
        self.notebook.select(self.reconcile_tab)
        self.identity_lab_notebook.select(self.raw_groups_tab)
        self.open_identity(result["target_identity"])

    def on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def refresh_all(self):
        current = self.current_identity
        self.refresh_identities()
        self.refresh_sort_profile_list()
        self.refresh_sandbox_tab()
        self.refresh_true_names_tab()
        if current and identity_exists(current):
            self.open_identity(current)

    def refresh_identities(self):
        self.identity_list.delete(0, tk.END)
        self.identity_rows = get_identities(self.include_false_positive.get(), self.include_multibird.get(), self.include_low_quality.get())
        for row in self.identity_rows:
            avg = row["avg_score"]
            avg_text = "n/a" if avg is None else f"{avg:.3f}"
            status_bits = []
            if row["fp_count"]:
                status_bits.append(f"fp:{row['fp_count']}")
            if row["multibird_count"]:
                status_bits.append(f"multi:{row['multibird_count']}")
            if row["low_quality_count"]:
                status_bits.append(f"lowq:{row['low_quality_count']}")
            status_text = "" if not status_bits else "   " + " ".join(status_bits)
            prefix = "★ " if row.get("special_group") else ""
            self.identity_list.insert(tk.END, f"{prefix}{row['identity']}   crops:{row['crop_count']}   avg:{avg_text}{status_text}")
        self.status.set(f"Loaded {len(self.identity_rows)} identities/groups from {DB_PATH}")
        self.refresh_sort_profile_list()
        self.refresh_sandbox_tab()
        self.refresh_true_names_tab()

    def selected_identities(self):
        return [self.identity_rows[i]["identity"] for i in self.identity_list.curselection()]

    def identity_selected(self, event=None):
        identities = self.selected_identities()
        if identities:
            self.open_identity(identities[0])

    def open_first_selected_identity(self):
        identities = self.selected_identities()
        if not identities:
            messagebox.showinfo("Select identity", "Select a Bird##### identity or special group first.")
            return
        self.open_identity(identities[0])

    def clear_workspace(self):
        for widget in self.workspace.winfo_children():
            widget.destroy()
        self.image_refs = []
        self.crop_tiles = []
        self.current_crop_rows = []
        self.update_crop_selection_status()

    def open_identity(self, identity):
        self.clear_workspace()
        self.current_identity = identity
        rows = get_crops(identity, limit=None)
        self.current_crop_rows = rows
        multi_count = sum(1 for row in rows if row["identity_status"] == "multibird")
        fp_count = sum(1 for row in rows if row["identity_status"] == "false_positive")
        lowq_count = sum(1 for row in rows if row["identity_status"] == "low_quality")
        extra = []
        if multi_count:
            extra.append(f"multibird {multi_count}")
        if lowq_count:
            extra.append(f"low_quality {lowq_count}")
        if fp_count:
            extra.append(f"false_positive {fp_count}")
        extra_text = "" if not extra else " | " + " | ".join(extra)
        self.mode_label.configure(text=f"Crop workspace: {identity} ({len(rows)} crops{extra_text})")
        if not rows:
            ttk.Label(self.workspace, text="No crops found.").pack(anchor="w")
            return
        for index, row in enumerate(rows):
            tile = CropTile(self, self.workspace, row)
            tile.frame.grid(row=index // GRID_COLUMNS, column=index % GRID_COLUMNS, padx=6, pady=6, sticky="n")
            self.crop_tiles.append(tile)
        self.update_crop_selection_status()

    def selected_crop_tiles(self):
        return [tile for tile in self.crop_tiles if tile.selected]

    def selected_crop_ids(self):
        return [tile.row["id"] for tile in self.selected_crop_tiles()]

    def update_crop_selection_status(self):
        if hasattr(self, "crop_selection_label"):
            self.crop_selection_label.configure(text=f"Selected crops: {len(self.selected_crop_tiles())}")

    def select_all_crops(self):
        for tile in self.crop_tiles:
            tile.set_selected(True)
        self.update_crop_selection_status()

    def clear_crop_selection(self):
        for tile in self.crop_tiles:
            tile.set_selected(False)
        self.update_crop_selection_status()

    def compare_selected(self):
        identities = [x for x in self.selected_identities() if x != MULTIBIRD_GROUP]
        if len(identities) < 1:
            messagebox.showinfo("Select identities", "Select one or more normal identities.")
            return
        self.show_comparison(identities[:3])

    def compare_three_selected(self):
        identities = [x for x in self.selected_identities() if x != MULTIBIRD_GROUP]
        if len(identities) != 3:
            messagebox.showinfo("3 Bird Compare", "Select exactly three normal identities.")
            return
        self.show_comparison(identities)

    def show_comparison(self, identities):
        self.clear_workspace()
        self.active_compare_identities = identities
        self.current_identity = identities[0] if identities else None
        self.mode_label.configure(text="Identity comparison: " + " | ".join(identities))
        cards = ttk.Frame(self.workspace)
        cards.pack(fill="both", expand=True)
        for identity in identities:
            self.build_identity_card(cards, identity)

    def build_identity_card(self, parent, identity):
        card = ttk.Frame(parent, borderwidth=2, relief="groove", padding=8)
        card.pack(side="left", fill="both", expand=True, padx=5, anchor="n")
        ttk.Label(card, text=identity, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        btns = ttk.Frame(card)
        btns.pack(fill="x", pady=5)
        ttk.Button(btns, text=f"Open Crop Workspace For {identity}", command=lambda: self.open_identity(identity)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Mark This Identity False Positive", command=lambda: self.mark_identity_fp(identity)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Mark This Identity Multibird", command=lambda: self.mark_identity_multibird(identity)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Mark This Identity Low Quality", command=lambda: self.mark_identity_low_quality(identity)).pack(fill="x", pady=2)
        crop_rows = get_crops(identity, limit=COMPARE_THUMBS_PER_IDENTITY)
        if not crop_rows:
            ttk.Label(card, text="No crops found.").pack(anchor="w")
            return
        for row in crop_rows:
            self.add_compare_thumbnail(card, row)

    def add_compare_thumbnail(self, parent, row):
        box = ttk.Frame(parent, padding=4)
        box.pack(anchor="w", pady=3)
        path = Path(row["crop_path"])
        if path.exists():
            try:
                if PIL_AVAILABLE:
                    img = Image.open(path)
                    img.thumbnail((THUMB_SIZE, THUMB_SIZE))
                    photo = ImageTk.PhotoImage(img)
                else:
                    photo = tk.PhotoImage(file=str(path))
                self.image_refs.append(photo)
                ttk.Label(box, image=photo).pack(side="left")
            except Exception as exc:
                ttk.Label(box, text=f"[image error]\n{path.name}\n{exc}", width=28).pack(side="left")
        else:
            ttk.Label(box, text=f"[missing]\n{path.name}", width=28).pack(side="left")
        score = row["visual_score"]
        score_text = "n/a" if score in (None, "") else str(score)
        decision_text = row["visual_decision"] or "n/a"
        status_text = row["identity_status"] or "n/a"
        label_text = row["training_label"] or ""
        label_line = f"\nlabel: {label_text}" if label_text else ""
        ttk.Label(box, text=f"{path.name}\nid: {row['identity'] or 'n/a'}\nstatus: {status_text}{label_line}\nscore: {score_text}\ndecision: {decision_text}", wraplength=260, justify="left").pack(side="left", padx=8)

    def merge_all_into(self, target_identity):
        sources = [x for x in self.active_compare_identities if x != target_identity]
        if not sources:
            return
        msg = "Merge these identities into " + target_identity + "?\n\n" + "\n".join(sources)
        if not messagebox.askyesno("Confirm merge", msg):
            return
        for source in sources:
            merge_identity(source, target_identity)
        self.status.set(f"Merged {', '.join(sources)} into {target_identity}")
        self.refresh_identities()
        self.open_identity(target_identity)

    def name_current_identity_profile(self):
        identity = self.current_identity or (self.selected_identities()[0] if self.selected_identities() else None)
        if not identity:
            messagebox.showinfo("Name bird/profile", "Open or select one identity first.")
            return
        if identity == MULTIBIRD_GROUP:
            messagebox.showinfo("Name bird/profile", "The multibird special group cannot be renamed.")
            return
        new_name = simpledialog.askstring("Name this bird/profile", f"Current identity: {identity}\n\nNew bird/profile name:")
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showinfo("Name bird/profile", "Name cannot be blank.")
            return
        if new_name == identity:
            self.status.set(f"Name unchanged: {identity}")
            return
        if identity_exists(new_name):
            messagebox.showerror("Name already exists", f"{new_name} already exists as an identity/profile.")
            return
        if not messagebox.askyesno("Confirm profile name", f"Rename all crops in {identity} to {new_name}?\n\nA database backup and identity_history entry will be created first."):
            return
        try:
            affected = rename_identity_profile(identity, new_name)
        except Exception as exc:
            messagebox.showerror("Name bird/profile failed", str(exc))
            return
        self.status.set(f"Named {identity} as {new_name} ({affected} crops).")
        self.refresh_identities()
        self.open_identity(new_name)

    def move_selected_crops_to_sandbox(self):
        crop_ids = self.selected_crop_ids()
        if not self.current_identity:
            messagebox.showinfo("No identity", "Open a crop workspace first.")
            return
        if not crop_ids:
            messagebox.showinfo("No crops selected", "Select crops to move to the sandbox first.")
            return
        if not messagebox.askyesno("Move to Sandbox", f"Move {len(crop_ids)} selected crop(s) to the Stage Names Sandbox?\n\nThis preserves their current identity name but marks them as sandbox evidence."):
            return
        mark_crops_status(crop_ids, self.current_identity, "sandbox", "move_selected_crops_to_sandbox", "stage_names_sandbox", "moved from Raw Groups crop workspace to Stage Names Sandbox")
        self.status.set(f"Moved {len(crop_ids)} crop(s) to Stage Names Sandbox.")
        self.refresh_sandbox_tab()
        self.open_identity(self.current_identity)

    def move_selected_crops_to_true_names(self):
        crop_ids = self.selected_crop_ids()
        if not self.current_identity:
            messagebox.showinfo("No identity", "Open a crop workspace first.")
            return
        if not crop_ids:
            messagebox.showinfo("No crops selected", "Select crops to move to True Names first.")
            return
        choice = ask_true_name_target(
            self.root,
            f"Move {len(crop_ids)} selected crop(s) from {self.current_identity} to True Names.\n\nChoose an existing True Name from the dropdown, or create a new one.",
            default_new_name=self.current_identity,
        )
        if not choice:
            return
        target = choice["name"]
        mode_text = "existing" if choice["mode"] == "existing" else "new"
        if choice["mode"] == "new" and identity_exists(target):
            messagebox.showerror("Name already exists", f"{target} already exists. Choose it from Existing True Name instead, or use a different new name.")
            return
        if not messagebox.askyesno("Confirm True Name move", f"Move {len(crop_ids)} selected crop(s) from {self.current_identity} to {mode_text} True Name {target}?\n\nThis sets identity_status='active' and review_status='reviewed'."):
            return
        move_crops_to_identity_lifecycle(crop_ids, self.current_identity, target, "active", "reviewed", "move_selected_crops_to_true_names")
        self.status.set(f"Moved {len(crop_ids)} crop(s) to True Name {target}.")
        self.refresh_identities()
        self.identity_lab_notebook.select(self.true_names_tab)
        if self.true_name_list is not None and target in self.true_name_list.get_children():
            self.true_name_list.selection_set(target)
            self.true_name_list.see(target)
            self.true_name_selected()

    def move_selected_identities_to_sandbox(self):
        identities = self.selected_identities()
        if not identities:
            messagebox.showinfo("Select identities", "Select one or more identities/groups first.")
            return
        if not messagebox.askyesno("Move identities to Sandbox", "Move selected identities/groups to the Stage Names Sandbox?\n\n" + "\n".join(identities)):
            return
        for identity in identities:
            mark_identity_status(identity, "sandbox", "move_identity_to_sandbox", "stage_names_sandbox", "moved from Raw Groups list to Stage Names Sandbox")
        self.status.set(f"Moved {len(identities)} identities/groups to Stage Names Sandbox.")
        self.refresh_all()
        self.clear_workspace()

    def move_current_identity_to_true_names(self):
        identity = self.current_identity or (self.selected_identities()[0] if self.selected_identities() else None)
        if not identity:
            messagebox.showinfo("Move to True Names", "Open or select one identity first.")
            return
        if identity == MULTIBIRD_GROUP:
            messagebox.showinfo("Move to True Names", "The multibird special group cannot be moved to True Names.")
            return
        target = simpledialog.askstring("Move to True Names", f"Current identity: {identity}\n\nTrue/canonical identity name:")
        if target is None:
            return
        target = target.strip()
        if not target:
            messagebox.showinfo("Move to True Names", "True name cannot be blank.")
            return
        if target != identity and identity_exists(target):
            messagebox.showerror("Name already exists", f"{target} already exists as an identity/profile. Use selected-crop moves or compare carefully before combining identities.")
            return
        if not messagebox.askyesno("Confirm True Name", f"Move {identity} to True Names as {target}?\n\nThis creates a backup, logs history, syncs visual_embeddings, and marks the identity active/reviewed."):
            return
        if target != identity:
            try:
                affected = rename_identity_profile(identity, target)
            except Exception as exc:
                messagebox.showerror("Move to True Names failed", str(exc))
                return
        else:
            affected = len(get_crops(identity))
        mark_identity_status(target, "active", "move_identity_to_true_names", "true_name", "moved to True Names / canonical identity lane")
        with connect_db() as conn:
            conn.execute("UPDATE crop_queue SET review_status = 'reviewed' WHERE identity = ?", (target,))
            conn.commit()
        self.status.set(f"Moved {identity} to True Names as {target} ({affected} crops).")
        self.refresh_identities()
        self.identity_lab_notebook.select(self.true_names_tab)
        if self.true_name_list is not None and target in self.true_name_list.get_children():
            self.true_name_list.selection_set(target)
            self.true_name_list.see(target)
            self.true_name_selected()
        else:
            self.clear_workspace()

    def split_selected_to_new_identity(self):
        crop_ids = self.selected_crop_ids()
        if not self.current_identity:
            messagebox.showinfo("No identity", "Open a crop workspace first.")
            return
        if not crop_ids:
            messagebox.showinfo("No crops selected", "Select crops to split first.")
            return
        if not AUTONAME_AVAILABLE:
            messagebox.showerror("autoname.py unavailable", "Could not import autoname.allocate_bird_name.")
            return
        try:
            new_identity = allocate_bird_name(str(DB_PATH))
        except Exception as exc:
            messagebox.showerror("Autoname failed", str(exc))
            return
        if not new_identity:
            messagebox.showerror("Autoname failed", "autoname.py returned an empty identity.")
            return
        if not messagebox.askyesno("Confirm split", f"Move {len(crop_ids)} selected crop(s) from {self.current_identity} to {new_identity}?"):
            return
        move_crops_to_identity(crop_ids, self.current_identity, new_identity, "split_selected_to_new_identity")
        self.status.set(f"Split {len(crop_ids)} crops to {new_identity}")
        self.refresh_identities()
        self.open_identity(new_identity)

    def move_selected_to_existing_identity(self):
        crop_ids = self.selected_crop_ids()
        if not self.current_identity:
            messagebox.showinfo("No identity", "Open a crop workspace first.")
            return
        if not crop_ids:
            messagebox.showinfo("No crops selected", "Select crops to move first.")
            return
        target = simpledialog.askstring("Move crops", "Move selected crops to existing identity/profile:")
        if target is None:
            return
        target = target.strip()
        if not target or target == MULTIBIRD_GROUP or not identity_exists(target):
            messagebox.showerror("Invalid target", "Target identity must already exist and cannot be the multibird special group.")
            return
        if not messagebox.askyesno("Confirm move", f"Move {len(crop_ids)} selected crop(s) from {self.current_identity} to {target}?"):
            return
        move_crops_to_identity(crop_ids, self.current_identity, target, "move_selected_to_existing_identity")
        self.status.set(f"Moved {len(crop_ids)} crops to {target}")
        self.refresh_identities()
        self.open_identity(target)

    def mark_selected_crops_status_dialog(self, status, action_type, title, prompt, confirm_word, note):
        crop_ids = self.selected_crop_ids()
        if not crop_ids:
            messagebox.showinfo("No crops selected", "Select crops first.")
            return
        label = simpledialog.askstring(title, prompt)
        if label is None:
            return
        label = label.strip()
        if not messagebox.askyesno("Confirm", f"Mark {len(crop_ids)} selected crops as {confirm_word}?"):
            return
        mark_crops_status(crop_ids, self.current_identity, status, action_type, label, note)
        self.status.set(f"Marked {len(crop_ids)} crops as {confirm_word}")
        self.open_identity(self.current_identity)

    def mark_selected_crops_fp(self):
        self.mark_selected_crops_status_dialog("false_positive", "mark_selected_crops_false_positive", "Training label", "Optional false-positive label:", "false_positive", "false positive evidence preserved")

    def mark_selected_crops_multibird(self):
        self.mark_selected_crops_status_dialog("multibird", "mark_selected_crops_multibird", "Multibird label", "Optional multibird label:", "multibird", "multibird evidence preserved")

    def mark_selected_crops_low_quality(self):
        self.mark_selected_crops_status_dialog("low_quality", "mark_selected_crops_low_quality", "Low-quality label", "Optional low-quality label:", "low_quality", "low quality evidence preserved")

    def delete_selected_junk_crops(self):
        crop_ids = self.selected_crop_ids()
        if not crop_ids:
            messagebox.showinfo("No crops selected", "Select junk crops first.")
            return
        if not messagebox.askyesno("Archive/Delete Junk", f"Archive image files and delete {len(crop_ids)} crop rows from active DB?"):
            return
        archive_and_delete_crops(crop_ids, self.current_identity)
        self.status.set(f"Archived/deleted {len(crop_ids)} junk crops")
        self.open_identity(self.current_identity)

    def mark_identity_fp(self, identity):
        mark_identity_status(identity, "false_positive", "mark_identity_false_positive", "", "false positive evidence preserved")
        self.refresh_identities()
        self.open_identity(identity)

    def mark_identity_multibird(self, identity):
        mark_identity_status(identity, "multibird", "mark_identity_multibird", "", "multibird evidence preserved")
        self.refresh_identities()
        self.open_identity(identity)

    def mark_identity_low_quality(self, identity):
        mark_identity_status(identity, "low_quality", "mark_identity_low_quality", "", "low quality evidence preserved")
        self.refresh_identities()
        self.open_identity(identity)

    def mark_selected_identities_status_dialog(self, status, action_type, title, prompt, confirm_word, note):
        identities = self.selected_identities()
        if not identities:
            messagebox.showinfo("Select identities", "Select one or more identities.")
            return
        label = simpledialog.askstring(title, prompt)
        if label is None:
            return
        label = label.strip()
        if not messagebox.askyesno("Confirm", "Mark selected identities/groups as " + confirm_word + "?\n\n" + "\n".join(identities)):
            return
        for identity in identities:
            mark_identity_status(identity, status, action_type, label, note)
        self.status.set(f"Marked {len(identities)} identities/groups as {confirm_word}")
        self.refresh_identities()
        self.clear_workspace()

    def mark_selected_identities_fp(self):
        self.mark_selected_identities_status_dialog("false_positive", "mark_identity_false_positive", "Training label", "Optional false-positive label for selected identities:", "false_positive", "false positive evidence preserved")

    def mark_selected_identities_multibird(self):
        self.mark_selected_identities_status_dialog("multibird", "mark_identity_multibird", "Multibird label", "Optional multibird label for selected identities:", "multibird", "multibird evidence preserved")

    def mark_selected_identities_low_quality(self):
        self.mark_selected_identities_status_dialog("low_quality", "mark_identity_low_quality", "Low-quality label", "Optional low-quality label for selected identities:", "low_quality", "low quality evidence preserved")

    def run_species_id(self):
        if not SPECIES_SCRIPT.exists():
            messagebox.showerror("Missing speciesid.py", f"Could not find:\n{SPECIES_SCRIPT}")
            return
        if not species_enabled():
            messagebox.showinfo("Species ID disabled", "Species ID is currently disabled in settings.ini.\n\nSet [species] EnableSpeciesID = true to run it.")
            return
        choice = messagebox.askyesnocancel("Run Species ID", "Choose Species ID mode:\n\nYes = Force Refresh existing annotations\nNo = New Only\nCancel = do not run")
        if choice is None:
            self.status.set("Species ID canceled.")
            return
        cmd = [sys.executable, str(SPECIES_SCRIPT)]
        if choice:
            cmd.append("--force")
        mode_text = "force refresh" if choice else "new only"
        self.status.set(f"Running Species ID ({mode_text})...")
        self.root.update_idletasks()
        try:
            completed = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=False)
            combined_output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
            summary = extract_species_summary(combined_output)
            messagebox.showinfo("Species ID Summary", summary or "Species ID finished, but no summary block was found.")
            if completed.returncode == 0:
                self.refresh_all()
            else:
                self.status.set(f"Species ID exited with code {completed.returncode}")
        except Exception as exc:
            messagebox.showerror("Species ID failed", str(exc))
            self.status.set("Species ID failed.")

    def rebuild_profiles(self):
        if not PROFILES_SCRIPT.exists():
            messagebox.showerror("Missing profiles.py", f"Could not find:\n{PROFILES_SCRIPT}")
            return
        self.status.set("Rebuilding profiles...")
        self.root.update_idletasks()
        try:
            completed = subprocess.run([sys.executable, str(PROFILES_SCRIPT)], cwd=str(PROJECT_ROOT), capture_output=True, text=True, check=False)
            if completed.returncode == 0:
                self.status.set("Profiles rebuilt.")
                messagebox.showinfo("Profiles", "Profiles rebuilt successfully.")
            else:
                output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
                messagebox.showerror("Profiles failed", output[-3000:] if output else f"Exit code {completed.returncode}")
                self.status.set("Profile rebuild failed.")
        except Exception as exc:
            messagebox.showerror("Profiles failed", str(exc))
            self.status.set("Profile rebuild failed.")


def main():
    ensure_schema()
    root = tk.Tk()
    app = CleanupGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
