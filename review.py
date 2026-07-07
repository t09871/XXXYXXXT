# review.py | HBMR v2.5.5 | 2026-06-18 PDT

import configparser
import os
import sqlite3
from pathlib import Path
from datetime import datetime

from autoname import allocate_bird_name


DB_NAME = "mr-review.db"
SETTINGS_NAME = "settings.ini"

NEW = "new"
AUTO = "auto"
REVIEWED = "reviewed"
SKIPPED = "skipped"

PROVISIONAL = "provisional"
ACTIVE = "active"
FALSE_POSITIVE = "false_positive"


def root_dir():
    return Path(__file__).resolve().parent


def settings_path():
    return root_dir() / SETTINGS_NAME


def load_settings():
    config = configparser.ConfigParser()

    path = settings_path()
    if path.exists():
        config.read(path, encoding="utf-8")

    return {
        "open_review_page": config.getboolean("review", "OpenReviewPage", fallback=False),
        "open_review_contact_sheet": config.getboolean("review", "OpenReviewContactSheet", fallback=False),
        "review_sheet_max_images": config.getint("review", "ReviewSheetMaxImages", fallback=80),
    }


def db_path():
    d = root_dir() / "output" / "database"
    d.mkdir(parents=True, exist_ok=True)
    return d / DB_NAME


def review_sheet_path():
    return root_dir() / "output" / "review" / "current-review.jpg"


def review_page_path():
    return root_dir() / "output" / "review" / "review.html"


def connect():
    path = db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn, path


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crop_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT,
            source_video TEXT,
            crop_path TEXT UNIQUE,
            review_status TEXT DEFAULT 'auto',
            identity TEXT DEFAULT '',
            identity_status TEXT DEFAULT 'provisional',
            training_label TEXT DEFAULT '',
            species_or_type TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            reviewed_at TEXT
        )
        """
    )

    cols = [
        r["name"]
        for r in conn.execute(
            "PRAGMA table_info(crop_queue)"
        ).fetchall()
    ]

    required = {
        "created": "TEXT",
        "source_video": "TEXT",
        "crop_path": "TEXT",
        "review_status": "TEXT DEFAULT 'auto'",
        "identity": "TEXT DEFAULT ''",
        "identity_status": "TEXT DEFAULT 'provisional'",
        "training_label": "TEXT DEFAULT ''",
        "species_or_type": "TEXT DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "reviewed_at": "TEXT",
    }

    for col, spec in required.items():
        if col not in cols:
            conn.execute(
                f"ALTER TABLE crop_queue ADD COLUMN {col} {spec}"
            )

    legacy_cols = set(cols)

    if "individual_name" in legacy_cols:
        conn.execute(
            """
            UPDATE crop_queue
            SET identity = TRIM(individual_name)
            WHERE COALESCE(TRIM(identity), '') = ''
              AND COALESCE(TRIM(individual_name), '') != ''
            """
        )

    if "name" in legacy_cols:
        conn.execute(
            """
            UPDATE crop_queue
            SET identity = TRIM(name)
            WHERE COALESCE(TRIM(identity), '') = ''
              AND COALESCE(TRIM(name), '') != ''
            """
        )

    conn.commit()


def open_if_exists(path, label):
    if not path.exists():
        print(f"{label} not found: {path}")
        return False

    try:
        os.startfile(str(path))
        print(f"Opened {label}: {path}")
        return True
    except Exception:
        print(f"Could not open {label}: {path}")
        return False


def autoname_unassigned_rows(conn, path):
    rows = conn.execute(
        """
        SELECT id
        FROM crop_queue
        WHERE COALESCE(TRIM(identity), '') = ''
        ORDER BY id
        """
    ).fetchall()

    if not rows:
        return 0

    now = datetime.now().isoformat(timespec="seconds")
    changed = 0

    for row in rows:
        bird_name = allocate_bird_name(path)

        conn.execute(
            """
            UPDATE crop_queue
            SET identity = ?,
                identity_status = ?,
                review_status = ?,
                reviewed_at = COALESCE(reviewed_at, ?)
            WHERE id = ?
            """,
            (
                bird_name,
                PROVISIONAL,
                AUTO,
                now,
                row["id"],
            ),
        )

        changed += 1
        print(f"Autonamed legacy row {row['id']}: {bird_name}")

    conn.commit()
    return changed


def convert_new_rows_to_auto(conn):
    now = datetime.now().isoformat(timespec="seconds")

    cur = conn.execute(
        """
        UPDATE crop_queue
        SET review_status = ?,
            identity_status = COALESCE(NULLIF(TRIM(identity_status), ''), ?),
            reviewed_at = COALESCE(reviewed_at, ?)
        WHERE COALESCE(review_status, 'new') = ?
        """,
        (
            AUTO,
            PROVISIONAL,
            now,
            NEW,
        ),
    )

    conn.commit()
    return cur.rowcount


def count_value(conn, column, value):
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS n
        FROM crop_queue
        WHERE COALESCE({column}, '') = ?
        """,
        (value,),
    ).fetchone()

    return row["n"]


def count_all(conn):
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM crop_queue
        """
    ).fetchone()

    return row["n"]


def latest_rows(conn, limit):
    return conn.execute(
        """
        SELECT id, identity, identity_status, review_status, crop_path
        FROM crop_queue
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def print_latest_rows(conn, limit):
    rows = latest_rows(conn, limit)

    if not rows:
        print()
        print("No profile pictures in database.")
        return

    print()
    print(f"Latest profile pictures ({len(rows)} shown)")
    print("-----------------------")

    for row in rows:
        identity = row["identity"] or "(no identity)"
        identity_status = row["identity_status"] or "(no identity_status)"
        review_status = row["review_status"] or "(no review_status)"
        crop_path = row["crop_path"] or "(no crop path)"

        print(f"{row['id']}. {identity} | {identity_status} | {review_status}")
        print(f"   {crop_path}")


def print_summary(conn, path, settings):
    total = count_all(conn)

    auto_count = count_value(conn, "review_status", AUTO)
    new_count = count_value(conn, "review_status", NEW)
    reviewed_count = count_value(conn, "review_status", REVIEWED)
    skipped_count = count_value(conn, "review_status", SKIPPED)

    provisional_count = count_value(conn, "identity_status", PROVISIONAL)
    active_count = count_value(conn, "identity_status", ACTIVE)
    false_positive_count = count_value(conn, "identity_status", FALSE_POSITIVE)

    print()
    print("HBMR review")
    print("Autoname mode: enabled")
    print("Human prompts: disabled")
    print(f"Open review page: {settings['open_review_page']}")
    print(f"Open review contact sheet: {settings['open_review_contact_sheet']}")
    print(f"Review sheet max images: {settings['review_sheet_max_images']}")
    print(f"Database: {path}")

    print()
    print("Database summary")
    print("----------------")
    print(f"Total profile pictures: {total}")
    print(f"review_status={AUTO}: {auto_count}")
    print(f"review_status={NEW}: {new_count}")
    print(f"review_status={REVIEWED}: {reviewed_count}")
    print(f"review_status={SKIPPED}: {skipped_count}")
    print(f"identity_status={PROVISIONAL}: {provisional_count}")
    print(f"identity_status={ACTIVE}: {active_count}")
    print(f"identity_status={FALSE_POSITIVE}: {false_positive_count}")


def maybe_open_outputs(settings):
    print()
    print("Review output opening")
    print("---------------------")

    if settings["open_review_contact_sheet"]:
        open_if_exists(review_sheet_path(), "review contact sheet")
    else:
        print("Review contact sheet opening disabled by settings.ini")

    if settings["open_review_page"]:
        open_if_exists(review_page_path(), "review page")
    else:
        print("Review page opening disabled by settings.ini")


def main():
    settings = load_settings()
    conn, path = connect()

    try:
        assigned = autoname_unassigned_rows(conn, path)
        converted = convert_new_rows_to_auto(conn)

        print_summary(conn, path, settings)

        print()
        print("Autoname maintenance")
        print("--------------------")
        print(f"Unassigned rows autonamed: {assigned}")
        print(f"New review rows converted to auto: {converted}")

        print_latest_rows(conn, settings["review_sheet_max_images"])
        maybe_open_outputs(settings)

        print()
        print("Review complete. No human input requested.")

    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print()
        print("Review crashed:")
        print(e)