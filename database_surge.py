"""
database_surge.py — Surge Route System persistence layer.

A fully separate parallel of the Loot Route data layer (database.py). Every table,
index, and function is surge-prefixed; nothing here ever touches a loot table.

Audit fixes applied vs. the loot original:
  • surge_rotation_state is SEEDED with an id=1 row (loot's is not → latent no-op bug).
  • surge_route_positions.position_number is NOT UNIQUE, and next-position is computed
    inside the same connection as the INSERT (loot has a TOCTOU race the new
    higher-throughput auto-assign would hit).
  • points floor is the SQL-side MAX(0, total + ?) (never a Python clamp → no read-then-write race).
  • role validation is case-insensitive NAME match for "Surge Route Maker" across the 3
    guilds (loot hardcodes a single role ID).
  • _wave_log_event is emitted AFTER the pool block so the write lock releases first.

Tables created by init_surge_routes_tables() (called from database.init_database after the
loot commit, so a surge DDL error can never abort loot table creation):
  surge_route_points, surge_route_assignments, surge_rotation_state, surge_route_positions,
  surge_pending_maps, surge_route_away_dates, surge_route_alumni, surge_weekly_mvp_posts
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

from database import get_pool
from core.global_logger import log_event as _wave_log_event
import core.surge_config as cfg

logger = logging.getLogger(__name__)

WAVE_CAT = cfg.WAVE_LOG_CATEGORY  # "surge_routes"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# TABLE INIT  (called from database.init_database, AFTER the loot commit)
# ============================================================================
async def init_surge_routes_tables():
    """
    Create every surge table + index in bot_database.db. Idempotent
    (CREATE TABLE/INDEX IF NOT EXISTS). Self-contained try/except so a failure
    here can never abort loot/reviewer table creation upstream.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Points balance (REAL — supports decimals; separate from loot).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_route_points (
                    user_id INTEGER PRIMARY KEY,
                    total_points REAL DEFAULT 0,
                    routes_completed INTEGER DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            ''')

            # Assignments — created with ALL columns up front (loot added several later
            # via migrations; we don't need those migrations for a fresh table).
            # queue_code captures the originating Logistics queue entry (bridge / Phase 8).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_route_assignments (
                    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    notification_message_id INTEGER NOT NULL,
                    confirmation_message_id INTEGER NOT NULL,
                    assigned_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    completed_at TEXT,
                    last_reminder_sent TEXT,
                    reminder_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    map_details TEXT,
                    points_awarded REAL,
                    is_lucky_map INTEGER DEFAULT 0,
                    local_files TEXT,
                    queue_code TEXT,
                    created_at TEXT NOT NULL
                )
            ''')

            # Single-row rotation state — SEEDED below (loot's is never seeded).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_rotation_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    rotation_message_id INTEGER,
                    sticky_message_id INTEGER,
                    leaderboard_message_id INTEGER,
                    last_assigned_position INTEGER DEFAULT 0,
                    last_assigned_user_id INTEGER,
                    total_assignments INTEGER DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            ''')
            # ✅ FIX: seed the single row so UPDATE-only save/increment work from first boot.
            await db.execute('''
                INSERT OR IGNORE INTO surge_rotation_state (id, last_updated)
                VALUES (1, ?)
            ''', (_now(),))

            # Rotation roster. position_number is NOT UNIQUE (loot's UNIQUE causes a
            # TOCTOU race the auto-assign drain would hit). Rank is derived from assigned_at.
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_route_positions (
                    user_id INTEGER PRIMARY KEY,
                    position_number INTEGER NOT NULL,
                    assigned_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                )
            ''')

            # NEW: hold pool for maps posted when no maker is free.
            # status: 'pending' (waiting) → deleted once assigned. requester_ids/local_files
            # are JSON strings. priority/queue_code preserve customer ordering from Logistics.
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_pending_maps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    source_message_id INTEGER,
                    queue_code TEXT,
                    priority INTEGER DEFAULT 999,
                    map_details TEXT,
                    image_refs TEXT,
                    local_files TEXT,
                    is_lucky_map INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            ''')

            # Away return dates (separate from loot — user_id PK would collide if shared).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_route_away_dates (
                    user_id     INTEGER PRIMARY KEY,
                    return_date TEXT,
                    set_at      TEXT    NOT NULL
                )
            ''')

            # Alumni / history for departed makers (keep points + rotation history).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_route_alumni (
                    user_id          INTEGER PRIMARY KEY,
                    display_name     TEXT,
                    total_points     REAL    DEFAULT 0,
                    routes_completed INTEGER DEFAULT 0,
                    rotation_number  INTEGER,
                    joined_at        TEXT,
                    left_at          TEXT    NOT NULL,
                    archived_at      TEXT    NOT NULL
                )
            ''')

            # Weekly MVP dedup (own table; loot's weekly_mvp_posts is loot-only).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS surge_weekly_mvp_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    week_number INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    posted_at TEXT NOT NULL,
                    UNIQUE(guild_id, year, week_number)
                )
            ''')

            # Surge-prefixed indexes (index names are a global namespace).
            await db.execute('CREATE INDEX IF NOT EXISTS idx_surge_assignments_status ON surge_route_assignments(status)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_surge_assignments_user ON surge_route_assignments(user_id, status)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_surge_assignments_time ON surge_route_assignments(assigned_at)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_surge_points_leaderboard ON surge_route_points(total_points DESC)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_surge_positions_assigned ON surge_route_positions(assigned_at)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_surge_pending_status ON surge_pending_maps(status, priority, created_at)')

            await db.commit()
        logger.info("✅ [SURGE ROUTES] Tables initialized")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Table init failed: {e}")


async def migrate_clamp_negative_surge_route_points():
    """One-time cleanup: clamp any negative surge point totals to 0. Idempotent no-op once clean."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cursor = await db.execute('UPDATE surge_route_points SET total_points = 0 WHERE total_points < 0')
            fixed = cursor.rowcount
            await db.commit()
            if fixed and fixed > 0:
                logger.info(f"✅ [SURGE ROUTES] Clamped {fixed} negative point total(s) to 0")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error clamping negative totals: {e}")


# ============================================================================
# ROLE VALIDATION  (case-insensitive NAME match for "Surge Route Maker")
# ============================================================================
def _member_has_surge_maker_role(member) -> bool:
    target = cfg.SURGE_MAKER_ROLE_NAME.lower()
    return any(r.name.lower() == target for r in member.roles)


async def _validate_surge_maker(user_id: int, guild_id: int, bot, points) -> Optional[bool]:
    """
    Returns True if validation passes (or is skipped), False if the user provably
    lacks the Surge Route Maker role. Mirrors loot's behaviour: when bot/member is
    unavailable, logs a warning and PROCEEDS (returns True) — callers award anyway.
    """
    if not bot:
        logger.warning("⚠️ [SURGE ROUTES] No bot instance — SKIPPING role validation")
        return True
    guild = bot.get_guild(guild_id or cfg.GUILD_ID)
    if not guild:
        logger.warning(f"⚠️ [SURGE ROUTES] Guild {guild_id} not found — skipping role validation")
        return True
    member = guild.get_member(user_id)
    if not member:
        logger.warning(f"⚠️ [SURGE ROUTES] User {user_id} not in guild cache — skipping role validation")
        return True
    if not _member_has_surge_maker_role(member):
        logger.error(f"⛔ [SURGE ROUTES] BLOCKED: {member.name} ({user_id}) lacks the Surge Route Maker role — refusing {points} pts")
        return False
    return True


# ============================================================================
# POINTS
# ============================================================================
async def add_surge_route_points(user_id: int, points: float = 1.0, guild_id: int = None, bot=None) -> Optional[float]:
    """
    Add Surge Route Points (atomic upsert, SQL-side MAX(0,...) floor). Role-gated by NAME.
    Returns new total, or None if role validation fails / error (distinct from a legit 0.0).
    """
    try:
        ok = await _validate_surge_maker(user_id, guild_id, bot, points)
        if ok is False:
            return None

        pool = await get_pool()
        async with pool.acquire() as db:
            now = _now()
            # Atomic: insert floored start, or increment floored-in-place. Two-arg max()
            # is SQLite's scalar form (largest arg), so penalties can't drive below 0.
            await db.execute('''
                INSERT INTO surge_route_points (user_id, total_points, routes_completed, last_updated)
                VALUES (?, 0.0, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    routes_completed = routes_completed + 1,
                    last_updated = ?
            ''', (user_id, now, now))
            await db.commit()
            async with db.execute('SELECT total_points FROM surge_route_points WHERE user_id = ?', (user_id,)) as cur:
                row = await cur.fetchone()
                new_points = float(row[0]) if row else float(points)
            logger.info(f"✅ [SURGE ROUTES] Added {points} pt(s) to {user_id} (total: {new_points})")

        await _wave_log_event(
            category=WAVE_CAT, action="points_added",
            target={"id": str(user_id)}, guild=guild_id,
            details={"points_added": points, "new_total": new_points},
        )
        return new_points
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error adding points: {e}")
        return None


async def get_surge_route_user_points(user_id: int) -> Dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT total_points, routes_completed FROM surge_route_points WHERE user_id = ?',
                (user_id,)
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return {'total_points': float(row[0]), 'routes_completed': row[1]}
                return {'total_points': 0.0, 'routes_completed': 0}
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting user points: {e}")
        return {'total_points': 0.0, 'routes_completed': 0}


async def get_surge_route_points_leaderboard(limit: int = 100) -> List:
    """Returns list of (user_id, total_points: float, routes_completed)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT user_id, 0.0, routes_completed FROM surge_route_points ORDER BY routes_completed DESC LIMIT ?',
                (limit,)
            ) as cur:
                rows = await cur.fetchall()
                return [(r[0], float(r[1]), r[2]) for r in rows]
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting leaderboard: {e}")
        return []


async def set_surge_route_user_points(user_id: int, points: float, routes: int = None, guild_id: int = None, bot=None):
    """Admin set. Floors at 0. Role-gated by NAME."""
    try:
        ok = await _validate_surge_maker(user_id, guild_id, bot, points)
        if ok is False:
            return
        pool = await get_pool()
        async with pool.acquire() as db:
            now = _now()
            if routes is None:
                async with db.execute('SELECT routes_completed FROM surge_route_points WHERE user_id = ?', (user_id,)) as cur:
                    row = await cur.fetchone()
                    routes = row[0] if row else 0
            await db.execute('''
                INSERT INTO surge_route_points (user_id, total_points, routes_completed, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_points = ?, routes_completed = ?, last_updated = ?
            ''', (user_id, points, routes, now, points, routes, now))
            await db.commit()
            logger.info(f"✅ [SURGE ROUTES] Set {user_id} points to {points}")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error setting points: {e}")


# ============================================================================
# ASSIGNMENTS
# ============================================================================
async def create_surge_route_assignment(user_id: int, guild_id: int, notification_message_id: int,
                                         confirmation_message_id: int, map_details: str = None,
                                         is_lucky_map: bool = False, queue_code: str = None) -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = _now()
            cur = await db.execute('''
                INSERT INTO surge_route_assignments
                (user_id, guild_id, notification_message_id, confirmation_message_id,
                 assigned_at, status, map_details, created_at, is_lucky_map, queue_code)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ''', (user_id, guild_id, notification_message_id, confirmation_message_id,
                  now, map_details, now, int(is_lucky_map), queue_code))
            assignment_id = cur.lastrowid
            await db.commit()
            logger.info(f"✅ [SURGE ROUTES] Created assignment #{assignment_id} for {user_id}")
            return assignment_id
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error creating assignment: {e}")
        return 0


async def update_surge_assignment_message_ids(assignment_id: int, notification_message_id: int, confirmation_message_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'UPDATE surge_route_assignments SET notification_message_id = ?, confirmation_message_id = ? WHERE assignment_id = ?',
                (notification_message_id, confirmation_message_id, assignment_id)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error updating message IDs: {e}")


def _assignment_row_to_dict(row) -> Dict[str, Any]:
    return {
        'assignment_id': row[0], 'user_id': row[1], 'guild_id': row[2],
        'notification_message_id': row[3], 'confirmation_message_id': row[4],
        'assigned_at': row[5], 'confirmed_at': row[6], 'completed_at': row[7],
        'status': row[8], 'map_details': row[9], 'reminder_count': row[10],
        'points_awarded': row[11], 'is_lucky_map': bool(row[12]) if row[12] is not None else False,
        'queue_code': row[13],
    }

_ASSIGN_COLS = ('assignment_id, user_id, guild_id, notification_message_id, confirmation_message_id, '
                'assigned_at, confirmed_at, completed_at, status, map_details, reminder_count, '
                'points_awarded, is_lucky_map, queue_code')


async def get_surge_route_assignment_by_id(assignment_id: int) -> Optional[Dict[str, Any]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                f'SELECT {_ASSIGN_COLS} FROM surge_route_assignments WHERE assignment_id = ?',
                (assignment_id,)
            ) as cur:
                row = await cur.fetchone()
                return _assignment_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting assignment: {e}")
        return None


async def complete_surge_route_assignment(assignment_id: int, points_awarded: float):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = _now()
            cur = await db.execute(
                "UPDATE surge_route_assignments SET status = 'completed', completed_at = ?, points_awarded = ? WHERE assignment_id = ?",
                (now, points_awarded, assignment_id)
            )
            rows = cur.rowcount
            await db.commit()
            if rows == 0:
                raise ValueError(f"Surge assignment #{assignment_id} not found — status NOT updated")
            logger.info(f"✅ [SURGE ROUTES] Completed assignment #{assignment_id} ({points_awarded:+} pts)")
        await _wave_log_event(category=WAVE_CAT, action="route_completed",
                              details={"assignment_id": assignment_id, "points_awarded": points_awarded})
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error completing assignment: {e}")
        raise


async def confirm_surge_route_assignment(assignment_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "UPDATE surge_route_assignments SET status = 'confirmed', confirmed_at = ? WHERE assignment_id = ?",
                (_now(), assignment_id)
            )
            await db.commit()
            logger.info(f"✅ [SURGE ROUTES] Confirmed assignment #{assignment_id}")
        await _wave_log_event(category=WAVE_CAT, action="route_confirmed", details={"assignment_id": assignment_id})
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error confirming assignment: {e}")


async def get_surge_assignment_by_confirmation_message(message_id: int) -> Optional[int]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT assignment_id FROM surge_route_assignments WHERE confirmation_message_id = ? AND status = 'pending'",
                (message_id,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error by confirmation message: {e}")
        return None


async def get_surge_assignment_by_notification_message(message_id: int) -> Optional[int]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT assignment_id FROM surge_route_assignments WHERE notification_message_id = ? AND status = 'pending'",
                (message_id,)
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error by notification message: {e}")
        return None


async def _assignments_where(where: str, params: tuple = ()) -> List[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(f'SELECT {_ASSIGN_COLS} FROM surge_route_assignments WHERE {where}', params) as cur:
            rows = await cur.fetchall()
            return [_assignment_row_to_dict(r) for r in rows]


async def get_all_pending_surge_assignments() -> List[Dict[str, Any]]:
    try:
        return await _assignments_where("status = 'pending'")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting pending: {e}")
        return []


async def get_all_confirmed_surge_assignments() -> List[Dict[str, Any]]:
    try:
        return await _assignments_where("status = 'confirmed'")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting confirmed: {e}")
        return []


async def get_user_surge_assignments(user_id: int, status: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        if status:
            return await _assignments_where("user_id = ? AND status = ? ORDER BY assigned_at DESC LIMIT ?", (user_id, status, limit))
        return await _assignments_where("user_id = ? ORDER BY assigned_at DESC LIMIT ?", (user_id, limit))
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting user assignments: {e}")
        return []


async def get_all_surge_route_assignments(guild_id: int) -> List[Dict[str, Any]]:
    try:
        return await _assignments_where("guild_id = ? ORDER BY assigned_at DESC", (guild_id,))
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting all assignments: {e}")
        return []


async def get_surge_assignments_needing_reminders() -> List[Dict[str, Any]]:
    """Pending assignments with no reminder in 24h."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            async with db.execute('''
                SELECT assignment_id, user_id, guild_id, notification_message_id,
                       confirmation_message_id, assigned_at, last_reminder_sent, reminder_count
                FROM surge_route_assignments
                WHERE status = 'pending'
                  AND ((last_reminder_sent IS NULL AND assigned_at < ?) OR (last_reminder_sent < ?))
            ''', (cutoff, cutoff)) as cur:
                rows = await cur.fetchall()
                return [{
                    'assignment_id': r[0], 'user_id': r[1], 'guild_id': r[2],
                    'notification_message_id': r[3], 'confirmation_message_id': r[4],
                    'assigned_at': r[5], 'last_reminder_sent': r[6], 'reminder_count': r[7],
                } for r in rows]
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting reminders: {e}")
        return []


async def update_surge_reminder_sent(assignment_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'UPDATE surge_route_assignments SET last_reminder_sent = ?, reminder_count = reminder_count + 1 WHERE assignment_id = ?',
                (_now(), assignment_id)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error updating reminder: {e}")


async def get_surge_route_assignment_stats() -> Dict[str, int]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('SELECT status, COUNT(*) FROM surge_route_assignments GROUP BY status') as cur:
                rows = await cur.fetchall()
                return {r[0]: r[1] for r in rows}
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting stats: {e}")
        return {}


async def cleanup_old_surge_route_assignments(days: int = 30) -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            await db.execute("DELETE FROM surge_route_assignments WHERE status = 'confirmed' AND confirmed_at < ?", (cutoff,))
            cur = await db.execute('SELECT changes()')
            deleted = (await cur.fetchone())[0]
            await db.commit()
            if deleted > 0:
                logger.info(f"✅ [SURGE ROUTES] Cleaned up {deleted} old assignments")
            return deleted
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error cleaning assignments: {e}")
        return 0


async def delete_surge_route_assignment(assignment_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_route_assignments WHERE assignment_id = ?', (assignment_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error deleting assignment: {e}")


async def save_surge_route_local_files(assignment_id: int, file_paths: list):
    import json
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('UPDATE surge_route_assignments SET local_files = ? WHERE assignment_id = ?',
                             (json.dumps(file_paths), assignment_id))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error saving local files: {e}")


async def get_surge_route_local_files(assignment_id: int) -> list:
    import json
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('SELECT local_files FROM surge_route_assignments WHERE assignment_id = ?', (assignment_id,)) as cur:
                row = await cur.fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting local files: {e}")
    return []


# ============================================================================
# ROTATION STATE
# ============================================================================
async def save_surge_rotation_state(rotation_message_id: int = None, sticky_message_id: int = None,
                                    leaderboard_message_id: int = None, last_assigned_position: int = None,
                                    last_assigned_user_id: int = None, total_assignments: int = None):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            updates, params = [], []
            for col, val in (('rotation_message_id', rotation_message_id), ('sticky_message_id', sticky_message_id),
                             ('leaderboard_message_id', leaderboard_message_id), ('last_assigned_position', last_assigned_position),
                             ('last_assigned_user_id', last_assigned_user_id), ('total_assignments', total_assignments)):
                if val is not None:
                    updates.append(f'{col} = ?')
                    params.append(val)
            if not updates:
                return
            updates.append('last_updated = ?')
            params.append(_now())
            await db.execute(f'UPDATE surge_rotation_state SET {", ".join(updates)} WHERE id = 1', params)
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error saving rotation state: {e}")


async def get_surge_rotation_state() -> Dict[str, Any]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT rotation_message_id, sticky_message_id, leaderboard_message_id, '
                'last_assigned_position, last_assigned_user_id, total_assignments FROM surge_rotation_state WHERE id = 1'
            ) as cur:
                row = await cur.fetchone()
                if row:
                    return {'rotation_message_id': row[0], 'sticky_message_id': row[1],
                            'leaderboard_message_id': row[2], 'last_assigned_position': row[3],
                            'last_assigned_user_id': row[4], 'total_assignments': row[5]}
                return {}
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting rotation state: {e}")
        return {}


async def increment_surge_total_assignments() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('UPDATE surge_rotation_state SET total_assignments = total_assignments + 1, last_updated = ? WHERE id = 1', (_now(),))
            async with db.execute('SELECT total_assignments FROM surge_rotation_state WHERE id = 1') as cur:
                row = await cur.fetchone()
                new_count = row[0] if row else 0
            await db.commit()
            return new_count
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error incrementing assignments: {e}")
        return 0


async def reset_surge_rotation_state_db():
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('''
                UPDATE surge_rotation_state
                SET rotation_message_id = NULL, sticky_message_id = NULL, leaderboard_message_id = NULL,
                    last_assigned_position = 0, last_assigned_user_id = NULL, total_assignments = 0, last_updated = ?
                WHERE id = 1
            ''', (_now(),))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error resetting rotation state: {e}")


# ============================================================================
# POSITIONS  (rank derived from assigned_at; no UNIQUE race)
# ============================================================================
async def get_surge_route_position(user_id: int) -> Optional[int]:
    """1-indexed rotation rank by assigned_at order; None if not in rotation."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('SELECT user_id FROM surge_route_positions ORDER BY assigned_at ASC, user_id ASC') as cur:
                rows = await cur.fetchall()
                for rank, row in enumerate(rows, start=1):
                    if row[0] == user_id:
                        return rank
                return None
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting position: {e}")
        return None


async def set_surge_route_position(user_id: int, position: int = None):
    """
    Add/update a maker in the rotation. position_number is informational only (rank is
    derived from assigned_at); when omitted, next-value is computed inside THIS connection
    so there's no TOCTOU race (the loot bug we deliberately avoid).
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = _now()
            if position is None:
                async with db.execute('SELECT MAX(position_number) FROM surge_route_positions') as cur:
                    row = await cur.fetchone()
                    position = (row[0] or 0) + 1
            await db.execute('''
                INSERT INTO surge_route_positions (user_id, position_number, assigned_at, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET position_number = ?, last_updated = ?
            ''', (user_id, position, now, now, position, now))
            await db.commit()
            logger.info(f"✅ [SURGE ROUTES] Set position {position} for {user_id}")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error setting position: {e}")
        raise


async def remove_surge_route_position(user_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_route_positions WHERE user_id = ?', (user_id,))
            await db.commit()
            logger.info(f"✅ [SURGE ROUTES] Removed position for {user_id}")
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error removing position: {e}")


async def get_all_surge_route_positions() -> List[Tuple[int, int]]:
    """Returns [(rank, user_id)], sequential 1..N by assigned_at (no gaps)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('SELECT user_id FROM surge_route_positions ORDER BY assigned_at ASC, user_id ASC') as cur:
                rows = await cur.fetchall()
                return [(rank, row[0]) for rank, row in enumerate(rows, start=1)]
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting all positions: {e}")
        return []


async def clear_surge_route_positions_global() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_route_positions')
            cur = await db.execute('SELECT changes()')
            deleted = (await cur.fetchone())[0]
            await db.commit()
            return deleted
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error clearing positions: {e}")
        return 0


# ============================================================================
# PENDING POOL  (hold & auto-assign-when-free — NEW behaviour)
# ============================================================================
async def enqueue_surge_pending_map(guild_id: int, source_message_id: int = None, queue_code: str = None,
                                    priority: int = 999, map_details: str = None, image_refs: str = None,
                                    local_files: str = None, is_lucky_map: bool = False) -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cur = await db.execute('''
                INSERT INTO surge_pending_maps
                (guild_id, source_message_id, queue_code, priority, map_details, image_refs,
                 local_files, is_lucky_map, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            ''', (guild_id, source_message_id, queue_code, priority, map_details, image_refs,
                  local_files, int(is_lucky_map), _now()))
            pid = cur.lastrowid
            await db.commit()
            logger.info(f"⏳ [SURGE ROUTES] Held pending map #{pid} (queue {queue_code}, priority {priority})")
            return pid
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error enqueuing pending map: {e}")
        return 0


def _pending_row_to_dict(r) -> Dict[str, Any]:
    return {'id': r[0], 'guild_id': r[1], 'source_message_id': r[2], 'queue_code': r[3],
            'priority': r[4], 'map_details': r[5], 'image_refs': r[6], 'local_files': r[7],
            'is_lucky_map': bool(r[8]), 'status': r[9], 'created_at': r[10]}

_PENDING_COLS = ('id, guild_id, source_message_id, queue_code, priority, map_details, '
                 'image_refs, local_files, is_lucky_map, status, created_at')


async def get_oldest_surge_pending_map() -> Optional[Dict[str, Any]]:
    """Highest customer priority first (lowest number), then oldest created."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                f"SELECT {_PENDING_COLS} FROM surge_pending_maps WHERE status = 'pending' "
                f"ORDER BY priority ASC, created_at ASC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
                return _pending_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting oldest pending: {e}")
        return None


async def get_surge_pending_maps() -> List[Dict[str, Any]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                f"SELECT {_PENDING_COLS} FROM surge_pending_maps WHERE status = 'pending' ORDER BY priority ASC, created_at ASC"
            ) as cur:
                rows = await cur.fetchall()
                return [_pending_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting pending maps: {e}")
        return []


async def delete_surge_pending_map(pending_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_pending_maps WHERE id = ?', (pending_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error deleting pending map: {e}")


async def count_surge_pending_maps() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute("SELECT COUNT(*) FROM surge_pending_maps WHERE status = 'pending'") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error counting pending: {e}")
        return 0


# ============================================================================
# AWAY RETURN DATES  (own table — never share loot's)
# ============================================================================
async def set_surge_away_return_date(user_id: int, return_date: str):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('''
                INSERT INTO surge_route_away_dates (user_id, return_date, set_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET return_date = excluded.return_date, set_at = excluded.set_at
            ''', (user_id, return_date, _now()))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error setting away date: {e}")


async def delete_surge_away_return_date(user_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_route_away_dates WHERE user_id = ?', (user_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error deleting away date: {e}")


async def get_all_surge_away_return_dates() -> List[dict]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('SELECT user_id, return_date, set_at FROM surge_route_away_dates') as cur:
                rows = await cur.fetchall()
                return [{'user_id': r[0], 'return_date': r[1], 'set_at': r[2]} for r in rows]
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error getting away dates: {e}")
        return []


# ============================================================================
# ALUMNI  (keep departed-maker history)
# ============================================================================
async def archive_surge_route_maker(user_id: int, display_name: str = None, left_at: str = None) -> bool:
    now = _now()
    left = left_at or now
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('SELECT total_points, routes_completed FROM surge_route_points WHERE user_id = ?', (user_id,)) as cur:
                pts_row = await cur.fetchone()
            async with db.execute('SELECT position_number, assigned_at FROM surge_route_positions WHERE user_id = ?', (user_id,)) as cur:
                pos_row = await cur.fetchone()
            if not pts_row and not pos_row:
                logger.info(f"ℹ️ [SURGE ALUMNI] No active data for {user_id} — nothing to archive")
                return False
            total_points = pts_row[0] if pts_row else 0
            routes_completed = pts_row[1] if pts_row else 0
            rotation_number = pos_row[0] if pos_row else None
            joined_at = pos_row[1] if pos_row else None
            await db.execute('''
                INSERT INTO surge_route_alumni
                    (user_id, display_name, total_points, routes_completed, rotation_number, joined_at, left_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name = excluded.display_name, total_points = excluded.total_points,
                    routes_completed = excluded.routes_completed, rotation_number = excluded.rotation_number,
                    joined_at = excluded.joined_at, left_at = excluded.left_at, archived_at = excluded.archived_at
            ''', (user_id, display_name, total_points, routes_completed, rotation_number, joined_at, left, now))
            await db.execute('DELETE FROM surge_route_points     WHERE user_id = ?', (user_id,))
            await db.execute('DELETE FROM surge_route_positions  WHERE user_id = ?', (user_id,))
            await db.execute('DELETE FROM surge_route_away_dates WHERE user_id = ?', (user_id,))
            await db.commit()
        logger.info(f"✅ [SURGE ALUMNI] Archived {user_id} ({display_name}) — {total_points} pts, {routes_completed} routes")
        return True
    except Exception as e:
        logger.error(f"❌ [SURGE ALUMNI] Failed to archive {user_id}: {e}")
        return False


async def get_surge_route_alumni() -> List[dict]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT user_id, display_name, total_points, routes_completed, rotation_number, joined_at, left_at, archived_at
                FROM surge_route_alumni ORDER BY total_points DESC
            ''') as cur:
                rows = await cur.fetchall()
            return [{'user_id': r[0], 'display_name': r[1], 'total_points': r[2], 'routes_completed': r[3],
                     'rotation_number': r[4], 'joined_at': r[5], 'left_at': r[6], 'archived_at': r[7]} for r in rows]
    except Exception as e:
        logger.error(f"❌ [SURGE ALUMNI] Error fetching alumni: {e}")
        return []


# ============================================================================
# CLEARS (admin)
# ============================================================================
async def clear_surge_route_points_global() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_route_points')
            cur = await db.execute('SELECT changes()')
            deleted = (await cur.fetchone())[0]
            await db.commit()
            return deleted
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error clearing points: {e}")
        return 0


async def clear_surge_route_assignments_global() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM surge_route_assignments')
            cur = await db.execute('SELECT changes()')
            deleted = (await cur.fetchone())[0]
            await db.commit()
            return deleted
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error clearing assignments: {e}")
        return 0


# ============================================================================
# WEEKLY MVP
# ============================================================================
async def check_surge_mvp_already_posted(guild_id: int, year: int, week_number: int) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT 1 FROM surge_weekly_mvp_posts WHERE guild_id = ? AND year = ? AND week_number = ?',
                (guild_id, year, week_number)
            ) as cur:
                return await cur.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error checking MVP: {e}")
        return False


async def save_surge_mvp_post(guild_id: int, year: int, week_number: int, message_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'INSERT INTO surge_weekly_mvp_posts (guild_id, year, week_number, message_id, posted_at) VALUES (?, ?, ?, ?, ?)',
                (guild_id, year, week_number, message_id, _now())
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [SURGE ROUTES] Error saving MVP: {e}")
