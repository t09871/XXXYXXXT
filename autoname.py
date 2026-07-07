# autoname.py | HBMR / Birdbill v3.1.9 | 2026-06-23 PDT
# Owns provisional Bird##### identity allocation, validation, parsing, and sorting.
#
# Canonical provisional identity format:
# Bird00001 -> Bird99999
#
# Important architecture rule:
# No other HBMR / Birdbill module may generate provisional Bird names directly.
# All provisional identity creation must flow through allocate_bird_name().

import re
import sqlite3
from pathlib import Path


BIRD_PREFIX = "Bird"
BIRD_DIGITS = 5
BIRD_MIN_NUMBER = 1
BIRD_MAX_NUMBER = 99999

BIRD_NAME_RE = re.compile(rf"^{BIRD_PREFIX}(\d{{{BIRD_DIGITS}}})$")

IDENTITY_TABLES_AND_COLUMNS = (
    ("crop_queue", "identity"),
    ("visual_embeddings", "identity"),
)


class AutonameError(RuntimeError):
    """Raised when Bird##### allocation cannot continue safely."""


def normalize_identity(identity):
    """
    Return a stripped identity string, or an empty string for blank/null values.
    """

    if identity is None:
        return ""
    return str(identity).strip()


def is_autoname(identity):
    """
    Return True if identity matches the canonical Bird##### format.
    """

    return BIRD_NAME_RE.match(normalize_identity(identity)) is not None


def autoname_number(identity):
    """
    Return the numeric component of a canonical Bird##### identity.

    Returns None for non-canonical identities.
    """

    match = BIRD_NAME_RE.match(normalize_identity(identity))
    if not match:
        return None
    return int(match.group(1))


def format_bird_name(number):
    """
    Format an integer as a canonical Bird##### provisional identity.
    """

    try:
        n = int(number)
    except Exception as exc:
        raise ValueError(f"Bird number must be an integer: {number!r}") from exc

    if n < BIRD_MIN_NUMBER or n > BIRD_MAX_NUMBER:
        raise ValueError(
            f"Bird number out of range: {n}. "
            f"Valid range is {BIRD_MIN_NUMBER} through {BIRD_MAX_NUMBER}."
        )

    return f"{BIRD_PREFIX}{n:0{BIRD_DIGITS}d}"


def autoname_sort_key(identity):
    """
    Sort helper for canonical Bird##### identities.

    Canonical Bird##### identities sort first by numeric value.
    Non-autoname identities sort afterward by lowercase display text.
    """

    text = normalize_identity(identity)
    number = autoname_number(text)

    if number is not None:
        return (0, number)

    return (1, text.lower())


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_has_column(conn, table_name, column_name):
    if not table_exists(conn, table_name):
        return False
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row[1] == column_name for row in rows)


def used_autoname_numbers(conn):
    """
    Return the set of canonical Bird##### numbers currently present in known identity tables.

    This intentionally checks both crop_queue.identity and visual_embeddings.identity because
    visual embeddings can briefly contain identity evidence before or beside crop_queue rows.
    """

    used = set()

    for table_name, column_name in IDENTITY_TABLES_AND_COLUMNS:
        if not table_has_column(conn, table_name, column_name):
            continue

        rows = conn.execute(
            f"""
            SELECT DISTINCT {column_name}
            FROM {table_name}
            WHERE {column_name} IS NOT NULL
              AND TRIM({column_name}) != ''
            """
        ).fetchall()

        for row in rows:
            number = autoname_number(row[0])
            if number is not None:
                used.add(number)

    return used


def next_available_number(used_numbers):
    """
    Return the first unused Bird##### number.

    Gap filling is intentional for fresh/scratch databases and keeps the allocator simple.
    Long-term UUID/entity architecture may later replace display-label allocation.
    """

    for number in range(BIRD_MIN_NUMBER, BIRD_MAX_NUMBER + 1):
        if number not in used_numbers:
            return number
    return None


def allocate_bird_name(db_path):
    """
    Return the next available provisional HBMR / Birdbill bird name.

    Canonical format:
    Bird00001
    Bird00002
    Bird00003
    ...
    Bird99999

    This function does not prompt the user.
    This function does not modify the database.
    Caller owns writing the returned name into crop_queue and/or visual_embeddings.
    """

    db_path = Path(db_path)

    used_numbers = set()

    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            used_numbers = used_autoname_numbers(conn)
        finally:
            conn.close()

    number = next_available_number(used_numbers)

    if number is None:
        raise AutonameError(
            "No available autoname slots remain. "
            f"{format_bird_name(BIRD_MIN_NUMBER)} through {format_bird_name(BIRD_MAX_NUMBER)} are already used. "
            "Long-term UUID/entity architecture is now required."
        )

    return format_bird_name(number)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python autoname.py path\\to\\mr-review.db")
        raise SystemExit(1)

    print(allocate_bird_name(sys.argv[1]))
