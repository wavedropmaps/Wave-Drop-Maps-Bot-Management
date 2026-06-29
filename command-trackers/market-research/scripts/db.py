"""
SQLite layer for the market research skill.
Tracks competitor improvement cord member/online counts over time.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
DATA_DIR   = SCRIPT_DIR.parent / "data"
DB_PATH    = DATA_DIR / "data.db"

SERVERS = [
    {"key": "wave",        "name": "Wave Improvement Cord",         "invite": "https://discord.gg/dropmaps"},
    {"key": "pro_reality", "name": "The Pro Reality",               "invite": "https://discord.com/invite/the-pro-reality-1-free-fn-improvement-hub-1120390152343269409"},
    {"key": "cloud",       "name": "Cloud Improvement",             "invite": "https://discord.gg/yR325b8nyE"},
    {"key": "xr",          "name": "XR Improvement Cord",           "invite": "https://discord.com/invite/N4eZxPxrF9"},
    {"key": "imp_hub",     "name": "Improvement HUB",               "invite": "https://discord.com/invite/improvement-hub-1306006683306426388"},
    {"key": "fn_comp",     "name": "Fortnite Competitive Improvement","invite": "https://disboard.org/server/999133722886549564"},
    {"key": "virtuous",    "name": "Virtuous Improvement Cord",     "invite": "https://discord.gg/fortnitetrainingpro"},
]

CONSECUTIVE_FAIL_LIMIT = 3


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS servers (
            key        TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            invite     TEXT NOT NULL,
            is_us      INTEGER NOT NULL DEFAULT 0,
            active     INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            server_key   TEXT NOT NULL,
            member_count INTEGER,
            online_count INTEGER,
            captured_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_key ON snapshots(server_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_ts  ON snapshots(captured_at)")

    for s in SERVERS:
        conn.execute("""
            INSERT INTO servers(key, name, invite, is_us) VALUES (?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET name=excluded.name, invite=excluded.invite
        """, (s["key"], s["name"], s["invite"], 1 if s["key"] == "wave" else 0))

    conn.commit()
    conn.close()


def get_active_servers():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM servers WHERE active=1 ORDER BY is_us DESC, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_snapshot(server_key: str, member_count, online_count):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now   = datetime.now(timezone.utc).isoformat()
    conn  = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "DELETE FROM snapshots WHERE server_key=? AND DATE(captured_at)=?",
        (server_key, today),
    )
    conn.execute(
        "INSERT INTO snapshots(server_key, member_count, online_count, captured_at) VALUES (?,?,?,?)",
        (server_key, member_count, online_count, now),
    )
    conn.commit()
    conn.close()


def get_latest_per_server():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT s.key, s.name, s.invite, s.is_us,
               sn.member_count, sn.online_count, sn.captured_at
        FROM servers s
        LEFT JOIN snapshots sn ON sn.id = (
            SELECT id FROM snapshots WHERE server_key=s.key ORDER BY captured_at DESC LIMIT 1
        )
        WHERE s.active=1
        ORDER BY sn.member_count DESC NULLS LAST
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_history(days: int = 90):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT sn.*, s.name, s.is_us
        FROM snapshots sn
        JOIN servers s ON s.key = sn.server_key
        WHERE sn.captured_at >= datetime('now', ?)
          AND s.active=1
        ORDER BY sn.captured_at ASC
    """, (f"-{days} days",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def record_fail(server_key: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("ALTER TABLE servers ADD COLUMN consecutive_fails INTEGER NOT NULL DEFAULT 0") if not _col_exists(conn, "servers", "consecutive_fails") else None
    conn.execute("UPDATE servers SET consecutive_fails = consecutive_fails + 1 WHERE key=?", (server_key,))
    conn.commit()
    fails = conn.execute("SELECT consecutive_fails FROM servers WHERE key=?", (server_key,)).fetchone()
    conn.close()
    return fails[0] if fails else 0


def record_success(server_key: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("ALTER TABLE servers ADD COLUMN consecutive_fails INTEGER NOT NULL DEFAULT 0") if not _col_exists(conn, "servers", "consecutive_fails") else None
    conn.execute("UPDATE servers SET consecutive_fails = 0 WHERE key=?", (server_key,))
    conn.commit()
    conn.close()


def deactivate_server(server_key: str):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("UPDATE servers SET active=0 WHERE key=?", (server_key,))
    conn.commit()
    conn.close()


def _col_exists(conn, table, col):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return col in cols


def already_collected_today() -> bool:
    return is_day_complete_today()


def today_coverage() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    roster = get_active_servers()
    expected = len(roster)
    if not DB_PATH.exists():
        return {"expected": expected, "saved": 0, "complete": False, "missing": [s["name"] for s in roster]}
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """SELECT s.name FROM snapshots sn
           JOIN servers s ON s.key = sn.server_key
           WHERE DATE(sn.captured_at)=? AND s.active=1""",
        (today,),
    ).fetchall()
    conn.close()
    saved_names = {r[0] for r in rows}
    missing = [s["name"] for s in roster if s["name"] not in saved_names]
    saved = len(saved_names)
    return {
        "expected": expected,
        "saved": saved,
        "complete": saved >= expected and expected > 0,
        "missing": missing,
    }


def is_day_complete_today() -> bool:
    return today_coverage()["complete"]


# ── Predictions ───────────────────────────────────────────────────────────────

def _ensure_predictions_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            server_key            TEXT NOT NULL,
            predicted_at          DATE NOT NULL,
            target_date           DATE NOT NULL,
            members_at_prediction INTEGER NOT NULL,
            predicted_members     INTEGER NOT NULL,
            actual_members        INTEGER,
            hit                   INTEGER
        )
    """)
    conn.commit()


def maybe_create_predictions(snapshot_results: dict):
    """Create a 30-day prediction for each server that has no pending prediction."""
    from datetime import timedelta
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_predictions_table(conn)
    today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    for key, stats in snapshot_results.items():
        current = stats.get("member_count")
        if not current:
            continue
        pending = conn.execute(
            "SELECT id FROM predictions WHERE server_key=? AND hit IS NULL",
            (key,)
        ).fetchone()
        if pending:
            continue

        snaps = conn.execute(
            """SELECT DATE(captured_at) as day, member_count
               FROM snapshots
               WHERE server_key=? AND member_count IS NOT NULL
               ORDER BY captured_at DESC LIMIT 14""",
            (key,)
        ).fetchall()

        slope = 0.0
        if len(snaps) >= 2:
            newest, oldest = snaps[0], snaps[-1]
            from datetime import datetime as _dt
            days_diff = (_dt.fromisoformat(newest[0]) - _dt.fromisoformat(oldest[0])).days
            if days_diff > 0:
                slope = (newest[1] - oldest[1]) / days_diff

        projected = max(0, round(current + slope * 30))
        conn.execute(
            """INSERT INTO predictions
               (server_key, predicted_at, target_date, members_at_prediction, predicted_members)
               VALUES (?,?,?,?,?)""",
            (key, today, future, current, projected)
        )

    conn.commit()
    conn.close()


def check_and_resolve_predictions(snapshot_results: dict):
    """Mark pending predictions as hit/miss if their target date has passed."""
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_predictions_table(conn)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    due   = conn.execute(
        "SELECT id, server_key, predicted_members FROM predictions WHERE hit IS NULL AND target_date <= ?",
        (today,)
    ).fetchall()
    for row in due:
        pid, key, target = row
        stats = snapshot_results.get(key, {})
        actual = stats.get("member_count")
        if actual is not None:
            hit = 1 if actual >= target else 0
            conn.execute(
                "UPDATE predictions SET actual_members=?, hit=? WHERE id=?",
                (actual, hit, pid)
            )
    conn.commit()
    conn.close()


def get_predictions():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _ensure_predictions_table(conn)
    rows = conn.execute("""
        SELECT p.id, s.name, s.key as server_key,
               p.predicted_at, p.target_date,
               p.members_at_prediction, p.predicted_members,
               p.actual_members, p.hit
        FROM predictions p
        JOIN servers s ON s.key = p.server_key
        ORDER BY p.predicted_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
