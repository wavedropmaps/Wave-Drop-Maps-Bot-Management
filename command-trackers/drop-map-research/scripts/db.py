"""
Database setup and queries for drop-map-research.
Data lives inside command-trackers/drop-map-research/data/ — tracked in git so it
syncs across all machines (Mac + Windows bot) via push/pull.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "data.db"

INITIAL_SERVERS = [
    ("Wave Free Dropmaps", "Wave Free Dropmaps"),
    ("DROPMAPS EHLAN", "DROPMAPS EHLAN"),
    ("Royal Drop Maps", "Royal Drop Maps"),
    ("Free Dropmaps", "Free Dropmaps"),
    ("Nova Free Dropmaps & Tips", "Nova Free Dropmaps"),
    ("Titan Free Dropmaps & Tips", "Titan Free Dropmaps"),
    ("NA Drops", "NA Drops"),
    ("DROP MAZTER", "DROP MAZTER"),
    ("dropmap.net", "dropmap.net"),
    ("SenanF Improvement Server", "SenanF"),
]


def get_conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            search_query TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            invite_code TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            member_count INTEGER,
            online_count INTEGER,
            captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (server_id) REFERENCES servers(id)
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL,
            predicted_at DATE NOT NULL,
            target_date DATE NOT NULL,
            members_at_prediction INTEGER NOT NULL,
            predicted_members INTEGER NOT NULL,
            actual_members INTEGER,
            hit INTEGER,
            FOREIGN KEY (server_id) REFERENCES servers(id)
        );
    """)
    # migrations
    cols = [r[1] for r in c.execute("PRAGMA table_info(servers)").fetchall()]
    if "invite_code" not in cols:
        c.execute("ALTER TABLE servers ADD COLUMN invite_code TEXT DEFAULT NULL")
    if "guild_id" not in cols:
        c.execute("ALTER TABLE servers ADD COLUMN guild_id TEXT DEFAULT NULL")

    snap_cols = [r[1] for r in c.execute("PRAGMA table_info(snapshots)").fetchall()]
    if "discovery_rank" not in snap_cols:
        c.execute("ALTER TABLE snapshots ADD COLUMN discovery_rank INTEGER DEFAULT NULL")

    for name, query in INITIAL_SERVERS:
        c.execute(
            "INSERT OR IGNORE INTO servers (name, search_query) VALUES (?, ?)",
            (name, query),
        )
    conn.commit()
    conn.close()


def add_server(name, search_query=None):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO servers (name, search_query) VALUES (?, ?)",
            (name, search_query or name),
        )
        conn.commit()
        print(f"Added server: {name}")
    except sqlite3.IntegrityError:
        conn.execute("UPDATE servers SET active=1 WHERE name=?", (name,))
        conn.commit()
        print(f"Re-activated server: {name}")
    finally:
        conn.close()


def remove_server(name):
    conn = get_conn()
    conn.execute("UPDATE servers SET active=0 WHERE name=?", (name,))
    conn.commit()
    conn.close()
    print(f"Deactivated server: {name}")


def list_servers():
    conn = get_conn()
    rows = conn.execute(
        "SELECT name, search_query, active, invite_code FROM servers ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_guild_id(name, guild_id):
    conn = get_conn()
    cur = conn.execute("UPDATE servers SET guild_id=? WHERE name=?", (guild_id, name))
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"Set guild ID for '{name}': {guild_id}")
    else:
        print(f"Server not found: {name}")


def set_invite_code(name, invite_code):
    conn = get_conn()
    cur = conn.execute("UPDATE servers SET invite_code=? WHERE name=?", (invite_code, name))
    conn.commit()
    conn.close()
    if cur.rowcount:
        print(f"Set invite code for '{name}': {invite_code}")
    else:
        print(f"Server not found: {name}")


def save_snapshot(data: dict):
    conn  = get_conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now   = datetime.now(timezone.utc).isoformat()
    saved = []
    for name, counts in data.items():
        row = conn.execute("SELECT id FROM servers WHERE name=?", (name,)).fetchone()
        if not row:
            print(f"  WARNING: server '{name}' not in DB, skipping")
            continue
        conn.execute(
            "DELETE FROM snapshots WHERE server_id=? AND DATE(captured_at)=?",
            (row["id"], today),
        )
        conn.execute(
            "INSERT INTO snapshots (server_id, member_count, online_count, captured_at, discovery_rank) VALUES (?,?,?,?,?)",
            (row["id"], counts.get("members"), counts.get("online"), now, counts.get("discovery_rank")),
        )
        saved.append(name)
    conn.commit()
    conn.close()
    print(f"Saved snapshot for: {', '.join(saved)}")
    return saved


def get_active_servers():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, search_query, added_at FROM servers WHERE active=1 ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_roster_added_by_name() -> dict[str, str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT name, added_at FROM servers WHERE active=1"
    ).fetchall()
    conn.close()
    return {r["name"]: (r["added_at"] or "")[:10] for r in rows}


def today_coverage() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    roster = get_active_servers()
    expected = len(roster)
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.name FROM snapshots sn
           JOIN servers s ON s.id = sn.server_id
           WHERE DATE(sn.captured_at)=? AND s.active=1""",
        (today,),
    ).fetchall()
    conn.close()
    saved_names = {r["name"] for r in rows}
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


def get_history(days=90):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT s.name, sn.member_count, sn.online_count, sn.captured_at, sn.discovery_rank
        FROM snapshots sn
        JOIN servers s ON s.id = sn.server_id
        WHERE sn.captured_at >= datetime('now', ?)
          AND s.active = 1
        ORDER BY sn.captured_at ASC
        """,
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_per_server():
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT s.name, s.added_at, s.invite_code, sn.member_count, sn.online_count, sn.captured_at, sn.discovery_rank
        FROM snapshots sn
        JOIN servers s ON s.id = sn.server_id
        WHERE sn.id IN (
            SELECT MAX(id) FROM snapshots GROUP BY server_id
        ) AND s.active = 1
        ORDER BY sn.member_count DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_and_resolve_predictions(snapshot_data: dict):
    conn = get_conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    due = conn.execute(
        """SELECT p.id, s.name, p.predicted_members
           FROM predictions p JOIN servers s ON s.id = p.server_id
           WHERE p.hit IS NULL AND p.target_date <= ?""",
        (today,)
    ).fetchall()
    for row in due:
        actual = snapshot_data.get(row["name"], {}).get("members")
        if actual is not None:
            hit = 1 if actual >= row["predicted_members"] else 0
            conn.execute(
                "UPDATE predictions SET actual_members=?, hit=? WHERE id=?",
                (actual, hit, row["id"])
            )
    conn.commit()
    conn.close()


def maybe_create_predictions(snapshot_data: dict):
    conn = get_conn()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")

    for name, data in snapshot_data.items():
        srv = conn.execute("SELECT id FROM servers WHERE name=?", (name,)).fetchone()
        if not srv:
            continue

        pending = conn.execute(
            "SELECT id FROM predictions WHERE server_id=? AND hit IS NULL",
            (srv["id"],)
        ).fetchone()
        if pending:
            continue

        current = data["members"]

        snaps = conn.execute(
            """SELECT DATE(captured_at) as day, member_count
               FROM snapshots
               WHERE server_id=? AND member_count IS NOT NULL
               GROUP BY DATE(captured_at)
               ORDER BY day DESC LIMIT 14""",
            (srv["id"],)
        ).fetchall()

        slope = 0.0
        if len(snaps) >= 2:
            newest = snaps[0]
            oldest = snaps[-1]
            days_diff = (datetime.fromisoformat(newest["day"]) -
                         datetime.fromisoformat(oldest["day"])).days
            if days_diff > 0:
                slope = (newest["member_count"] - oldest["member_count"]) / days_diff

        projected = max(0, round(current + slope * 30))
        conn.execute(
            """INSERT INTO predictions
               (server_id, predicted_at, target_date, members_at_prediction, predicted_members)
               VALUES (?, ?, ?, ?, ?)""",
            (srv["id"], today, future, current, projected)
        )

    conn.commit()
    conn.close()


def get_predictions():
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.name, p.predicted_at, p.target_date,
                  p.members_at_prediction, p.predicted_members,
                  p.actual_members, p.hit
           FROM predictions p JOIN servers s ON s.id = p.server_id
           ORDER BY p.predicted_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
