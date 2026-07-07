# cleanup.py | HBMR v2.5.3 | 2026-06-18 PDT

import csv
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


APP_NAME = "HBMR cleanup"
APP_VERSION = "v2.5.3"

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "output" / "database" / "mr-review.db"
PROFILES_FILE = ROOT / "profiles.py"
TRAINING_DIR = ROOT / "output" / "training"
TRAINING_CSV = TRAINING_DIR / "false-positive-training.csv"

TABLE = "crop_queue"

NEW = "new"
REVIEWED = "reviewed"
SKIPPED = "skipped"

ACTIVE = "active"
FALSE_POSITIVE = "false_positive"
PROVISIONAL = "provisional"


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def ensure_schema(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT,
            source_video TEXT,
            crop_path TEXT,
            review_status TEXT DEFAULT 'new',
            species_or_type TEXT DEFAULT '',
            individual_name TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            name TEXT,
            reviewed_at TEXT,
            identity_status TEXT DEFAULT 'active',
            training_label TEXT DEFAULT '',
            cleanup_notes TEXT DEFAULT ''
        )
        """
    )

    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({TABLE})").fetchall()]

    required = {
        "created": "TEXT",
        "source_video": "TEXT",
        "crop_path": "TEXT",
        "review_status": "TEXT DEFAULT 'new'",
        "species_or_type": "TEXT DEFAULT ''",
        "individual_name": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "name": "TEXT",
        "reviewed_at": "TEXT",
        "identity_status": "TEXT DEFAULT 'active'",
        "training_label": "TEXT DEFAULT ''",
        "cleanup_notes": "TEXT DEFAULT ''",
    }

    for col, spec in required.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {spec}")

    conn.commit()


def bird_expr():
    return "COALESCE(NULLIF(TRIM(individual_name), ''), NULLIF(TRIM(name), ''), 'Unknown')"


def get_birds(conn):
    return conn.execute(
        f"""
        SELECT
            {bird_expr()} AS bird,
            COALESCE(NULLIF(TRIM(identity_status), ''), 'active') AS identity_status,
            COALESCE(NULLIF(TRIM(training_label), ''), '') AS training_label,
            COUNT(*) AS n,
            SUM(CASE WHEN COALESCE(review_status, 'new') = 'reviewed' THEN 1 ELSE 0 END) AS reviewed_n,
            SUM(CASE WHEN COALESCE(review_status, 'new') = 'new' THEN 1 ELSE 0 END) AS new_n,
            SUM(CASE WHEN COALESCE(review_status, 'new') = 'skipped' THEN 1 ELSE 0 END) AS skipped_n
        FROM {TABLE}
        GROUP BY bird, identity_status, training_label
        ORDER BY
            CASE WHEN identity_status = 'false_positive' THEN 1 ELSE 0 END,
            LOWER(bird)
        """
    ).fetchall()


def print_birds(rows):
    print()
    print("Bird identities")
    print("---------------")

    if not rows:
        print("No identities found.")
        return

    for i, row in enumerate(rows, start=1):
        label = row["training_label"] or "-"
        print(
            f"{i}. {row['bird']} | status={row['identity_status']} | "
            f"training={label} | total={row['n']} | reviewed={row['reviewed_n']} | "
            f"new={row['new_n']} | skipped={row['skipped_n']}"
        )


def choose_bird(conn, prompt="Choose identity number"):
    rows = get_birds(conn)
    print_birds(rows)

    if not rows:
        return None

    raw = input(f"{prompt}: ").strip()

    if not raw.isdigit():
        print("No valid number selected.")
        return None

    idx = int(raw)
    if idx < 1 or idx > len(rows):
        print("Number out of range.")
        return None

    return rows[idx - 1]["bird"]


def update_identity(conn, old_name, new_name=None, identity_status=None, training_label=None, review_status=None, note=None):
    sets = []
    params = []

    if new_name is not None:
        sets.append("individual_name = ?")
        params.append(new_name)
        sets.append("name = ?")
        params.append(new_name)

    if identity_status is not None:
        sets.append("identity_status = ?")
        params.append(identity_status)

    if training_label is not None:
        sets.append("training_label = ?")
        params.append(training_label)

    if review_status is not None:
        sets.append("review_status = ?")
        params.append(review_status)

    if note is not None:
        sets.append("cleanup_notes = TRIM(COALESCE(cleanup_notes, '') || ' ' || ?)")
        params.append(f"[{now_text()}] {note}")

    sets.append("reviewed_at = COALESCE(reviewed_at, ?)")
    params.append(now_text())

    if not sets:
        return 0

    params.extend([old_name, old_name])

    cur = conn.execute(
        f"""
        UPDATE {TABLE}
        SET {", ".join(sets)}
        WHERE TRIM(COALESCE(individual_name, '')) = ?
           OR TRIM(COALESCE(name, '')) = ?
           OR ({bird_expr()} = ?)
        """,
        params + [old_name],
    )

    conn.commit()
    return cur.rowcount


def rename_identity(conn):
    old = choose_bird(conn, "Rename which identity number")
    if not old:
        return

    new = input(f"New name for {old}: ").strip()
    if not new:
        print("Rename cancelled.")
        return

    n = update_identity(conn, old, new_name=new, identity_status=ACTIVE, training_label="")
    print(f"Renamed rows: {n}")


def merge_identity(conn):
    source = choose_bird(conn, "Merge FROM identity number")
    if not source:
        return

    target = choose_bird(conn, "Merge INTO identity number")
    if not target:
        return

    if source == target:
        print("Source and target are the same.")
        return

    confirm = input(f"Merge {source} into {target}? Type MERGE: ").strip()
    if confirm != "MERGE":
        print("Merge cancelled.")
        return

    n = update_identity(conn, source, new_name=target, identity_status=ACTIVE, training_label="")
    print(f"Merged rows: {n}")


def mark_identity_false_positive(conn):
    name = choose_bird(conn, "Mark which identity as false positive")
    if not name:
        return

    fp_label = input("False-positive label, e.g. leaf, feeder-sway, shadow, blur: ").strip()
    if not fp_label:
        fp_label = "false_positive"

    new_name = f"FalsePositive-{fp_label}"

    confirm = input(f"Preserve rows and tag {name} as {new_name}? Type FP: ").strip()
    if confirm != "FP":
        print("False-positive tagging cancelled.")
        return

    n = update_identity(
        conn,
        name,
        new_name=new_name,
        identity_status=FALSE_POSITIVE,
        training_label=fp_label,
        review_status=REVIEWED,
        note=f"tagged false positive from identity {name}",
    )

    print(f"False-positive rows tagged: {n}")


def restore_identity_active(conn):
    name = choose_bird(conn, "Restore which identity to active")
    if not name:
        return

    new = input(f"Active bird name for {name}: ").strip()
    if not new:
        new = name.replace("FalsePositive-", "").strip() or name

    n = update_identity(
        conn,
        name,
        new_name=new,
        identity_status=ACTIVE,
        training_label="",
        review_status=REVIEWED,
        note="restored to active bird identity",
    )

    print(f"Rows restored: {n}")


def mark_identity_status(conn, status):
    name = choose_bird(conn, f"Set which identity to review_status={status}")
    if not name:
        return

    n = update_identity(
        conn,
        name,
        review_status=status,
        note=f"review_status set to {status}",
    )

    print(f"Rows updated: {n}")


def list_recent(conn, limit=40):
    rows = conn.execute(
        f"""
        SELECT id, review_status, identity_status, training_label, individual_name, name, crop_path
        FROM {TABLE}
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    print()
    print(f"Recent rows, newest {limit}")
    print("----------------------")

    for row in rows:
        bird = row["individual_name"] or row["name"] or "Unknown"
        label = row["training_label"] or "-"
        print(
            f"{row['id']} | review={row['review_status']} | identity={row['identity_status']} | "
            f"training={label} | {bird} | {row['crop_path']}"
        )


def delete_rows(conn):
    raw = input("Row IDs to delete, comma-separated: ").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip().isdigit()]

    if not ids:
        print("No valid row IDs.")
        return

    confirm = input("Type DELETE to remove these database rows: ").strip()
    if confirm != "DELETE":
        print("Delete cancelled.")
        return

    placeholders = ",".join("?" for _ in ids)
    cur = conn.execute(f"DELETE FROM {TABLE} WHERE id IN ({placeholders})", ids)
    conn.commit()
    print(f"Rows deleted: {cur.rowcount}")


def export_false_positive_training(conn):
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)

    rows = conn.execute(
        f"""
        SELECT
            id,
            created,
            source_video,
            crop_path,
            individual_name,
            name,
            identity_status,
            training_label,
            cleanup_notes
        FROM {TABLE}
        WHERE COALESCE(identity_status, '') = ?
           OR COALESCE(training_label, '') != ''
        ORDER BY id
        """,
        (FALSE_POSITIVE,),
    ).fetchall()

    with open(TRAINING_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "created",
                "source_video",
                "crop_path",
                "individual_name",
                "name",
                "identity_status",
                "training_label",
                "cleanup_notes",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    print()
    print(f"False-positive training rows exported: {len(rows)}")
    print(f"Training CSV: {TRAINING_CSV}")


def rebuild_profiles():
    if not PROFILES_FILE.exists():
        print(f"profiles.py not found: {PROFILES_FILE}")
        return

    print()
    print("Rebuilding profiles...")
    result = subprocess.run([sys.executable, str(PROFILES_FILE)], cwd=str(ROOT))

    if result.returncode == 0:
        print("Profiles rebuilt.")
    else:
        print(f"Profile rebuild failed with code: {result.returncode}")


def menu():
    print()
    print(APP_NAME)
    print(f"Version: {APP_VERSION}")
    print(f"Database: {DB_PATH}")
    print()
    print("1. List identities")
    print("2. List recent rows")
    print("3. Rename identity")
    print("4. Merge identities")
    print("5. Tag identity as false positive")
    print("6. Restore false positive to active bird")
    print("7. Mark identity reviewed")
    print("8. Mark identity skipped")
    print("9. Mark identity new")
    print("10. Delete specific database rows")
    print("11. Export false-positive training CSV")
    print("12. Rebuild profiles")
    print("Q. Quit")


def main():
    conn = connect()

    try:
        while True:
            menu()
            choice = input("> ").strip().lower()

            if choice == "1":
                print_birds(get_birds(conn))
            elif choice == "2":
                list_recent(conn)
            elif choice == "3":
                rename_identity(conn)
            elif choice == "4":
                merge_identity(conn)
            elif choice == "5":
                mark_identity_false_positive(conn)
            elif choice == "6":
                restore_identity_active(conn)
            elif choice == "7":
                mark_identity_status(conn, REVIEWED)
            elif choice == "8":
                mark_identity_status(conn, SKIPPED)
            elif choice == "9":
                mark_identity_status(conn, NEW)
            elif choice == "10":
                delete_rows(conn)
            elif choice == "11":
                export_false_positive_training(conn)
            elif choice == "12":
                rebuild_profiles()
            elif choice == "q":
                return
            else:
                print("Unknown choice.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print()
        print("cleanup.py crashed:")
        print(e)
        input("Press Enter to close...")