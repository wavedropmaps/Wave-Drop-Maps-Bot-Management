"""
Database for guild-stats — tracks member counts and key stats for the bot's own Discord guilds.
Data lives in command-trackers/guild-stats/data/ — tracked in git so it syncs across machines.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH  = DATA_DIR / "data.db"

# Guilds tracked by default — names are updated from the API on each collect
INITIAL_GUILDS = [
    ("988564962802810961", "Source Guild 1"),
    ("971731167621574666", "Source Guild 2"),
]


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS guilds (
            guild_id   TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            active     INTEGER DEFAULT 1,
            added_at   TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id       TEXT NOT NULL,
            captured_at    TEXT NOT NULL,
            member_count   INTEGER,
            online_count   INTEGER,
            boost_count    INTEGER,
            boost_tier     INTEGER,
            channel_count  INTEGER,
            role_count     INTEGER,
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id)
        );
    """)
    for guild_id, name in INITIAL_GUILDS:
        conn.execute(
            "INSERT OR IGNORE INTO guilds (guild_id, name) VALUES (?, ?)",
            (guild_id, name)
        )
    conn.commit()
    conn.close()


def upsert_guild(guild_id: str, name: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO guilds (guild_id, name) VALUES (?, ?) "
        "ON CONFLICT(guild_id) DO UPDATE SET name=excluded.name",
        (guild_id, name)
    )
    conn.commit()
    conn.close()


def get_active_guilds():
    conn = get_conn()
    rows = conn.execute(
        "SELECT guild_id, name, added_at FROM guilds WHERE active=1 ORDER BY guild_id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_roster_added_by_name() -> dict[str, str]:
    return {r["name"]: (r.get("added_at") or "")[:10] for r in get_active_guilds()}


def today_coverage() -> dict:
    """Distinct guilds with a snapshot today vs active roster."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    roster = get_active_guilds()
    expected = len(roster)
    conn = get_conn()
    rows = conn.execute(
        """SELECT g.name FROM snapshots s
           JOIN guilds g ON g.guild_id = s.guild_id
           WHERE DATE(s.captured_at)=? AND g.active=1""",
        (today,),
    ).fetchall()
    conn.close()
    saved_names = {r["name"] for r in rows}
    missing = [g["name"] for g in roster if g["name"] not in saved_names]
    saved = len(saved_names)
    return {
        "expected": expected,
        "saved": saved,
        "complete": saved >= expected and expected > 0,
        "missing": missing,
    }


def is_day_complete_today() -> bool:
    return today_coverage()["complete"]


def save_snapshot(guild_id: str, data: dict):
    conn  = get_conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now   = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "DELETE FROM snapshots WHERE guild_id=? AND DATE(captured_at)=?",
        (guild_id, today),
    )
    conn.execute(
        """INSERT INTO snapshots
           (guild_id, captured_at, member_count, online_count,
            boost_count, boost_tier, channel_count, role_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            guild_id, now,
            data.get("member_count"), data.get("online_count"),
            data.get("boost_count"),  data.get("boost_tier"),
            data.get("channel_count"), data.get("role_count"),
        )
    )
    conn.commit()
    conn.close()


def get_history(days: int = 90):
    """One row per snapshot within the window, all active guilds."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT g.name, g.guild_id,
                  s.member_count, s.online_count,
                  s.boost_count,  s.boost_tier,
                  s.channel_count, s.role_count,
                  s.captured_at
           FROM snapshots s
           JOIN guilds g ON g.guild_id = s.guild_id
           WHERE s.captured_at >= datetime('now', ?)
             AND g.active = 1
           ORDER BY s.captured_at ASC""",
        (f"-{days} days",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_per_guild():
    conn = get_conn()
    rows = conn.execute(
        """SELECT g.name, g.guild_id,
                  s.member_count, s.online_count,
                  s.boost_count,  s.boost_tier,
                  s.channel_count, s.role_count,
                  s.captured_at
           FROM snapshots s
           JOIN guilds g ON g.guild_id = s.guild_id
           WHERE s.id IN (
               SELECT MAX(id) FROM snapshots GROUP BY guild_id
           ) AND g.active = 1
           ORDER BY s.member_count DESC NULLS LAST"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
