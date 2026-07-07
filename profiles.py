# profiles.py | HBMR / Birdbill v3.1.9 | 2026-06-23 PDT

import csv
import html
import json
import re
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    from autoname import autoname_sort_key
except Exception:
    def autoname_sort_key(identity):
        if identity is None:
            return (1, "")
        return (1, str(identity).strip().lower())


APP_VERSION = "v3.1.9"

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
DATABASE_DIR = OUTPUT_DIR / "database"
PROFILES_DIR = OUTPUT_DIR / "profiles"
PROFILES_DATA_DIR = PROFILES_DIR / "data"

REVIEW_DB = DATABASE_DIR / "mr-review.db"

UNKNOWN_NAME = "Unknown"

SINGLE_PORT_FEEDER_HEIGHT_MM = 152.4
AVERAGE_FINGER_WIDTH_MM = 14.0

MAX_PROFILE_CROPS_TO_COPY = 300
MAX_PROFILE_CROPS_TO_SHOW = 80

DEFAULT_ESTIMATES = {
    "estimated_weight_g": 4.2,
    "estimated_weight_error_g": 1.1,
    "bill_length_mm": 18,
    "bill_length_error_mm": 3,
    "body_length_mm": 85,
    "body_length_error_mm": 10,
    "wing_length_mm": 43,
    "wing_length_error_mm": 6,
}

DEFAULT_AWARDS = {
    "Most Talkative": "TBD",
    "Most Frequent Visitor": "TBD",
    "Longest Visit": "TBD",
    "Most Curious": "TBD",
    "Finger Landing Pro": "TBD",
    "Longest Gulp": "TBD",
    "Biggest Power Drinking Session": "TBD",
    "Most Perching Time": "TBD",
    "Most Feeder Time": "TBD",
}

DEFAULT_BEHAVIOR_STATS = {
    "Finger landings": "TBD",
    "Hand visits": "TBD",
    "Feeder visits": "TBD",
    "Multi-bird events": "TBD",
    "Chase / courtship / conflict": "TBD",
    "Drinking time": "TBD",
    "Perching time": "TBD",
    "Drinking / perching ratio": "TBD",
}

DEFAULT_PERSONALITY = {
    "Tolerance": 50,
    "Territoriality": 50,
    "Romance": 50,
}

DEFAULT_GENDER = {
    "gender": "TBD",
    "gender_confidence": "TBD",
}

DEFAULT_NESTING = {
    "has_egg": "TBD",
    "has_babies": "TBD",
    "has_juveniles": "TBD",
    "nesting_confidence": "TBD",
    "visible_on_profile": False,
}


def safe_name(value):
    value = (value or UNKNOWN_NAME).strip()
    keep = []
    for ch in value:
        if ch.isalnum() or ch in (" ", "-", "_"):
            keep.append(ch)
    cleaned = "".join(keep).strip()
    return cleaned or UNKNOWN_NAME


def db_connect():
    if not REVIEW_DB.exists():
        raise FileNotFoundError(f"Database not found: {REVIEW_DB}")
    return sqlite3.connect(REVIEW_DB)


def get_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def get_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def pick_table(conn):
    tables = get_tables(conn)

    preferred = [
        "crop_queue",
        "observations",
        "review_items",
        "detections",
        "crops",
        "events",
    ]

    for name in preferred:
        if name in tables:
            return name

    for table in tables:
        cols = set(get_columns(conn, table))
        if {"crop_path", "name"} & cols or {"image_path", "name"} & cols:
            return table

    if tables:
        return tables[0]

    raise RuntimeError("No tables found in review database.")


def row_value(row, keys, default=None):
    for key in keys:
        if key in row.keys():
            value = row[key]
            if value not in (None, ""):
                return value
    return default


def load_rows(conn):
    table = pick_table(conn)
    conn.row_factory = sqlite3.Row

    cols = set(get_columns(conn, table))

    if table == "crop_queue":
        where_parts = []

        if "identity" in cols:
            where_parts.append("COALESCE(TRIM(identity), '') != ''")

        if "identity_status" in cols:
            where_parts.append("COALESCE(identity_status, '') NOT IN ('false_positive', 'junk', 'low_quality')")

        where_clause = ""
        if where_parts:
            where_clause = " WHERE " + " AND ".join(where_parts)

        rows = conn.execute(f"SELECT * FROM {table}{where_clause}").fetchall()
    else:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()

    return table, rows


def parse_filename_timestamp(value):
    text = str(value or "")
    name = Path(text).name

    patterns = [
        r"(20\d{2})(\d{2})(\d{2})[_\- ]?(\d{2})(\d{2})(\d{2})",
        r"(20\d{2})[_\-](\d{2})[_\-](\d{2})[_\- ](\d{2})[_\-](\d{2})[_\-](\d{2})",
        r"(20\d{2})[_\-](\d{2})[_\-](\d{2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, name)
        if not match:
            continue

        parts = match.groups()

        try:
            if len(parts) == 6:
                dt = datetime(
                    int(parts[0]),
                    int(parts[1]),
                    int(parts[2]),
                    int(parts[3]),
                    int(parts[4]),
                    int(parts[5]),
                )
            else:
                dt = datetime(int(parts[0]), int(parts[1]), int(parts[2]))

            return dt.isoformat(timespec="seconds")
        except Exception:
            pass

    return ""


def parse_any_timestamp(*values):
    for value in values:
        if not value:
            continue

        text = str(value)

        try:
            return datetime.fromisoformat(text).isoformat(timespec="seconds")
        except Exception:
            pass

        parsed = parse_filename_timestamp(text)
        if parsed:
            return parsed

    return ""


def normalize_observations(rows):
    observations = []

    for row in rows:
        name = row_value(
            row,
            ["identity", "bird_name", "profile_name", "individual_name", "name", "label"],
            UNKNOWN_NAME,
        )

        crop_path = row_value(
            row,
            ["crop_path", "image_path", "file_path", "path", "filename"],
            "",
        )

        event_id = row_value(
            row,
            ["event_id", "group_id", "visit_id", "review_group", "id"],
            "",
        )

        source_video = row_value(
            row,
            ["source_video", "video_path", "video", "input_video"],
            "",
        )

        raw_timestamp = row_value(
            row,
            ["timestamp", "frame_time", "time_seconds", "seconds", "created_at"],
            "",
        )

        duration = row_value(
            row,
            ["duration", "duration_seconds", "visit_duration", "event_duration"],
            "",
        )

        parsed_timestamp = parse_any_timestamp(raw_timestamp, source_video, crop_path)

        observations.append(
            {
                "name": safe_name(name),
                "crop_path": str(crop_path or ""),
                "event_id": str(event_id or ""),
                "source_video": str(source_video or ""),
                "timestamp": str(raw_timestamp or ""),
                "parsed_timestamp": parsed_timestamp,
                "duration": str(duration or ""),
            }
        )

    return observations


def group_by_profile(observations):
    grouped = {}

    for obs in observations:
        name = safe_name(obs["name"])
        grouped.setdefault(name, []).append(obs)

    return grouped


def resolve_crop_path(crop_path):
    if not crop_path:
        return None

    p = Path(crop_path)

    if p.exists():
        return p

    candidates = [
        PROJECT_ROOT / crop_path,
        OUTPUT_DIR / crop_path,
        OUTPUT_DIR / "crops" / Path(crop_path).name,
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def copy_profile_images(profile_name, observations):
    profile_data_dir = PROFILES_DATA_DIR / profile_name
    best_dir = profile_data_dir / "best-crops"
    best_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    hero = None
    copied_count = 0

    for obs in observations:
        if copied_count >= MAX_PROFILE_CROPS_TO_COPY:
            break

        src = resolve_crop_path(obs["crop_path"])
        if not src:
            continue

        dst = best_dir / src.name

        if not dst.exists():
            shutil.copy2(src, dst)

        rel = dst.relative_to(PROFILES_DIR).as_posix()
        copied.append(rel)
        copied_count += 1

        if hero is None:
            hero_dst = profile_data_dir / "hero.jpg"
            shutil.copy2(src, hero_dst)
            hero = hero_dst.relative_to(PROFILES_DIR).as_posix()

    return hero, copied


def iso_to_display(value):
    if not value:
        return "TBD"

    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return "TBD"


def estimate_profile_stats(profile_name, observations):
    event_ids = [o["event_id"] for o in observations if o["event_id"]]
    unique_events = sorted(set(event_ids))

    durations = []
    for obs in observations:
        try:
            durations.append(float(obs["duration"]))
        except Exception:
            pass

    parsed_times = []
    for obs in observations:
        value = obs.get("parsed_timestamp")
        if not value:
            continue
        try:
            parsed_times.append(datetime.fromisoformat(value))
        except Exception:
            pass

    parsed_times.sort()

    first_seen = parsed_times[0].isoformat(timespec="seconds") if parsed_times else ""
    last_seen = parsed_times[-1].isoformat(timespec="seconds") if parsed_times else ""

    total_duration = sum(durations) if durations else None
    avg_duration = total_duration / len(durations) if durations else None
    longest_duration = max(durations) if durations else None

    chronology_confidence = "TBD"
    if parsed_times:
        chronology_confidence = "filename-derived"

    stats = {
        "name": profile_name,
        "total_observations": len(observations),
        "total_events": len(unique_events) if unique_events else len(observations),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "community_member_since": first_seen,
        "chronology_confidence": chronology_confidence,
        "total_observed_seconds": total_duration,
        "average_visit_seconds": avg_duration,
        "longest_visit_seconds": longest_duration,
        "measurement_mode": "automatic reference estimate",
        "identity_label_format": "Bird##### provisional labels supported",
        "scale_references": {
            "single_port_feeder_height_mm": SINGLE_PORT_FEEDER_HEIGHT_MM,
            "average_finger_width_mm": AVERAGE_FINGER_WIDTH_MM,
        },
        "personality_score": DEFAULT_PERSONALITY.copy(),
        "personality_basis": {
            "Tolerance": "starts at 50; future observations may raise/lower",
            "Territoriality": "starts at 50; future observations may raise/lower",
            "Romance": "starts at 50; future observations may raise/lower",
        },
        "gender": DEFAULT_GENDER.copy(),
        "nesting": DEFAULT_NESTING.copy(),
        "awards": DEFAULT_AWARDS.copy(),
        "behavior_stats": DEFAULT_BEHAVIOR_STATS.copy(),
    }

    stats.update(DEFAULT_ESTIMATES)
    return stats


def fmt_seconds(value):
    if value is None:
        return "TBD"
    try:
        value = float(value)
    except Exception:
        return "TBD"

    if value < 60:
        return f"{value:.1f} sec"

    minutes = int(value // 60)
    seconds = int(value % 60)
    return f"{minutes} min {seconds} sec"


def write_profile_data(profile_name, observations, stats, hero, copied_images):
    profile_data_dir = PROFILES_DATA_DIR / profile_name
    profile_data_dir.mkdir(parents=True, exist_ok=True)

    profile_json = {
        **stats,
        "hero_image": hero,
        "images": copied_images,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    with open(profile_data_dir / "profile.json", "w", encoding="utf-8") as f:
        json.dump(profile_json, f, indent=2)

    with open(profile_data_dir / "events.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "event_id",
                "timestamp",
                "parsed_timestamp",
                "duration",
                "source_video",
                "crop_path",
            ],
        )
        writer.writeheader()
        for obs in observations:
            writer.writerow(obs)


def confidence_class(value):
    text = str(value or "").lower()

    if "filename" in text or "estimate" in text:
        return "confidence-medium"

    if text in ("tbd", "", "none"):
        return "confidence-tbd"

    return "confidence-high"


def html_page(title, body):
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{
    font-family: Arial, sans-serif;
    margin: 28px;
    background: #f7f3ec;
    color: #222;
}}
a {{
    color: #245a7a;
}}
.card {{
    background: white;
    border-radius: 16px;
    padding: 18px;
    margin: 14px 0;
    box-shadow: 0 2px 10px rgba(0,0,0,0.12);
}}
.profile-top {{
    display: grid;
    grid-template-columns: minmax(260px, 380px) minmax(260px, 1fr) minmax(260px, 360px);
    gap: 22px;
    align-items: start;
}}
.hero {{
    max-width: 360px;
    max-height: 360px;
    border-radius: 14px;
}}
.grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
}}
.thumb {{
    width: 180px;
    height: 180px;
    object-fit: cover;
    border-radius: 12px;
}}
.stat {{
    font-size: 1.05em;
    margin: 8px 0;
}}
.small {{
    color: #666;
    font-size: 0.92em;
}}
.badge {{
    display: inline-block;
    background: #f1e2b8;
    border-radius: 999px;
    padding: 6px 10px;
    margin: 4px 4px 4px 0;
}}
.personality-badge {{
    display: block;
    background: #e8edf4;
    border-radius: 12px;
    padding: 10px 12px;
    margin: 8px 0;
}}
.score-bar {{
    background: #ddd;
    border-radius: 999px;
    height: 12px;
    overflow: hidden;
    margin-top: 5px;
}}
.score-fill {{
    background: #8aa6c8;
    height: 12px;
}}
.two-column {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
}}
.confidence-high {{
    color: #226b2f;
}}
.confidence-medium {{
    color: #8a6500;
}}
.confidence-tbd {{
    color: #777;
}}
@media (max-width: 1000px) {{
    .profile-top {{
        grid-template-columns: 1fr;
    }}
}}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def dict_to_badges(values, class_name="badge"):
    parts = []
    for key, value in values.items():
        parts.append(
            f'<div class="{class_name}"><b>{html.escape(str(key))}:</b> {html.escape(str(value))}</div>'
        )
    return "\n".join(parts)


def personality_html(values):
    parts = []
    for key, value in values.items():
        try:
            score = int(value)
        except Exception:
            score = 50

        score = max(0, min(100, score))

        parts.append(
            f"""
<div class="personality-badge">
    <b>{html.escape(str(key))}:</b> {score}/100
    <div class="score-bar">
        <div class="score-fill" style="width: {score}%"></div>
    </div>
</div>
"""
        )

    return "\n".join(parts)


def write_profile_html(profile_name, stats, hero, copied_images):
    hero_html = ""
    if hero:
        hero_html = f'<img class="hero" src="{html.escape(hero)}">'

    thumbs = "\n".join(
        f'<img class="thumb" src="{html.escape(src)}">'
        for src in copied_images[:MAX_PROFILE_CROPS_TO_SHOW]
    )

    if len(copied_images) > MAX_PROFILE_CROPS_TO_SHOW:
        thumbs += f"""
<p class="small">Showing {MAX_PROFILE_CROPS_TO_SHOW} of {len(copied_images)} copied crops.</p>
"""

    awards_html = dict_to_badges(stats["awards"])
    behavior_html = dict_to_badges(stats["behavior_stats"])
    personality_block = personality_html(stats["personality_score"])

    chronology_class = confidence_class(stats["chronology_confidence"])
    gender_class = confidence_class(stats["gender"]["gender_confidence"])

    nesting_html = ""
    if stats["nesting"].get("visible_on_profile"):
        nesting_html = f"""
<div class="card">
    <h2>Nesting</h2>
    <p class="stat"><b>Egg:</b> {html.escape(str(stats["nesting"]["has_egg"]))}</p>
    <p class="stat"><b>Babies:</b> {html.escape(str(stats["nesting"]["has_babies"]))}</p>
    <p class="stat"><b>Juveniles:</b> {html.escape(str(stats["nesting"]["has_juveniles"]))}</p>
</div>
"""

    body = f"""
<p><a href="index.html">← Back to profiles</a></p>
<h1>{html.escape(profile_name)}</h1>

<div class="card">
    <div class="profile-top">
        <div>
            {hero_html}
        </div>

        <div>
            <h2>Awards / Superlatives</h2>
            {awards_html}
        </div>

        <div>
            <h2>Personality Score</h2>
            {personality_block}
        </div>
    </div>
</div>

<div class="two-column">
    <div class="card">
        <h2>Observation Stats</h2>
        <p class="stat"><b>Community Member Since:</b> <span class="{chronology_class}">{iso_to_display(stats["community_member_since"])}</span></p>
        <p class="stat"><b>Visits/events:</b> {stats["total_events"]}</p>
        <p class="stat"><b>Observations:</b> {stats["total_observations"]}</p>
        <p class="stat"><b>Total observed time:</b> {fmt_seconds(stats["total_observed_seconds"])}</p>
        <p class="stat"><b>Average visit:</b> {fmt_seconds(stats["average_visit_seconds"])}</p>
        <p class="stat"><b>Longest visit:</b> {fmt_seconds(stats["longest_visit_seconds"])}</p>
    </div>

    <div class="card">
        <h2>Estimated Measurements</h2>
        <p class="stat"><b>Estimated weight:</b> {stats["estimated_weight_g"]:.1f} g ± {stats["estimated_weight_error_g"]:.1f} g</p>
        <p class="stat"><b>Bill length:</b> {stats["bill_length_mm"]:.0f} mm ± {stats["bill_length_error_mm"]:.0f} mm</p>
        <p class="stat"><b>Body length:</b> {stats["body_length_mm"]:.0f} mm ± {stats["body_length_error_mm"]:.0f} mm</p>
        <p class="stat"><b>Wing length:</b> {stats["wing_length_mm"]:.0f} mm ± {stats["wing_length_error_mm"]:.0f} mm</p>
    </div>
</div>

<div class="two-column">
    <div class="card">
        <h2>Gender</h2>
        <p class="stat"><b>Gender:</b> <span class="{gender_class}">{html.escape(str(stats["gender"]["gender"]))}</span></p>
    </div>

    <div class="card">
        <h2>Behavior Stats</h2>
        {behavior_html}
    </div>
</div>

{nesting_html}

<h2>Gallery</h2>
<div class="grid">
{thumbs}
</div>
"""

    with open(PROFILES_DIR / f"{profile_name}.html", "w", encoding="utf-8") as f:
        f.write(html_page(profile_name, body))


def write_index(profile_summaries):
    cards = []

    for summary in sorted(profile_summaries, key=lambda x: autoname_sort_key(x["name"])):
        name = summary["name"]
        hero = summary.get("hero")

        img = ""
        if hero:
            img = f'<img class="thumb" src="{html.escape(hero)}">'

        cards.append(
            f"""
<div class="card">
<a href="{html.escape(name)}.html">{img}</a>
<h2><a href="{html.escape(name)}.html">{html.escape(name)}</a></h2>
<p><b>Community Member Since:</b> {iso_to_display(summary["community_member_since"])}</p>
<p><b>Events:</b> {summary["total_events"]}</p>
<p><b>Observations:</b> {summary["total_observations"]}</p>
<p><b>Estimated weight:</b> {summary["estimated_weight_g"]:.1f} g ± {summary["estimated_weight_error_g"]:.1f} g</p>
</div>
"""
        )

    body = f"""
<h1>Hummingbird Mindreader Profiles</h1>
<p class="small">Generated by HBMR / Birdbill {APP_VERSION}</p>
<p class="small">Generated {html.escape(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))}</p>
<div class="grid">
{''.join(cards)}
</div>
"""

    with open(PROFILES_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(html_page(f"HummingbirdMindreader Profiles | HBMR {APP_VERSION}", body))


def build_profiles():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = db_connect()
    table, rows = load_rows(conn)
    observations = normalize_observations(rows)
    grouped = group_by_profile(observations)

    summaries = []

    for profile_name, profile_observations in grouped.items():
        hero, copied_images = copy_profile_images(profile_name, profile_observations)
        stats = estimate_profile_stats(profile_name, profile_observations)

        write_profile_data(profile_name, profile_observations, stats, hero, copied_images)
        write_profile_html(profile_name, stats, hero, copied_images)

        summaries.append(
            {
                "name": profile_name,
                "hero": hero,
                **stats,
            }
        )

    write_index(summaries)

    print()
    print("HBMR / Birdbill profiles generated")
    print(f"Database table used: {table}")
    print(f"Profiles: {len(summaries)}")
    print(f"Output: {PROFILES_DIR / 'index.html'}")
    print()


if __name__ == "__main__":
    build_profiles()