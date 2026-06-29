"""
database_tipsandtricks.py — Tips & Tricks Helper System persistence layer.

Tables (all tt_-prefixed, never touch loot/surge tables):
  tt_tasks             task pool; statuses: available → claimed → completed
  tt_helper_points     per-helper running balance + stats
  tt_duty_assignments  one row per assigned duty code (upsert-on-conflict)

Called from database.init_database after the surge block.
"""

import json
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict

from database import get_pool
import core.tipsandtricks_config as cfg

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# TABLE INIT
# ============================================================================

async def init_tipsandtricks_tables():
    """Create all T&T tables. Idempotent. Called from database.init_database."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS tt_tasks (
                    task_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    description   TEXT    NOT NULL,
                    base_points   INTEGER NOT NULL DEFAULT 1,
                    is_lucky      INTEGER NOT NULL DEFAULT 0,
                    bonus_applied INTEGER NOT NULL DEFAULT 0,
                    status        TEXT    NOT NULL DEFAULT 'available',
                    created_at    TEXT    NOT NULL,
                    created_by    INTEGER NOT NULL,
                    claimed_by    INTEGER,
                    claimed_at    TEXT,
                    completed_at  TEXT,
                    attachments   TEXT    NOT NULL DEFAULT '[]',
                    parent_task_id INTEGER,
                    completion_bonus INTEGER NOT NULL DEFAULT 0
                )
            ''')
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_tt_tasks_status ON tt_tasks(status)'
            )
            # Migration: add attachments column to existing tables
            try:
                await db.execute("ALTER TABLE tt_tasks ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'")
                await db.commit()
            except Exception:
                pass
            # Migration: add parent_task_id and completion_bonus for super tasks
            try:
                await db.execute("ALTER TABLE tt_tasks ADD COLUMN parent_task_id INTEGER")
                await db.execute("ALTER TABLE tt_tasks ADD COLUMN completion_bonus INTEGER NOT NULL DEFAULT 0")
                await db.commit()
            except Exception:
                pass
            # Index on parent_task_id — must be created AFTER the column migration above
            try:
                await db.execute(
                    'CREATE INDEX IF NOT EXISTS idx_tt_tasks_parent ON tt_tasks(parent_task_id)'
                )
                await db.commit()
            except Exception:
                pass

            await db.execute('''
                CREATE TABLE IF NOT EXISTS tt_helper_points (
                    user_id                INTEGER PRIMARY KEY,
                    total_points           REAL    NOT NULL DEFAULT 0,
                    tasks_completed        INTEGER NOT NULL DEFAULT 0,
                    lucky_tasks_completed  INTEGER NOT NULL DEFAULT 0,
                    last_updated           TEXT    NOT NULL
                )
            ''')

            # Migration to handle multiple users per duty:
            try:
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS tt_duty_assignments_new (
                        duty_code   TEXT    NOT NULL,
                        user_id     INTEGER NOT NULL,
                        assigned_at TEXT    NOT NULL,
                        assigned_by INTEGER NOT NULL,
                        PRIMARY KEY (duty_code, user_id)
                    )
                ''')
                # Attempt to copy existing data into the new table, ignoring duplicates
                await db.execute('INSERT OR IGNORE INTO tt_duty_assignments_new SELECT * FROM tt_duty_assignments')
                await db.execute('DROP TABLE tt_duty_assignments')
                await db.execute('ALTER TABLE tt_duty_assignments_new RENAME TO tt_duty_assignments')
                await db.commit()
            except Exception:
                # If migration fails or old table doesn't exist, just ensure the correct table exists
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS tt_duty_assignments (
                        duty_code   TEXT    NOT NULL,
                        user_id     INTEGER NOT NULL,
                        assigned_at TEXT    NOT NULL,
                        assigned_by INTEGER NOT NULL,
                        PRIMARY KEY (duty_code, user_id)
                    )
                ''')

            await db.commit()
        logger.info("✅ [T&T] Tables initialized")
    except Exception as e:
        logger.error(f"❌ [T&T] Table init failed: {e}")
        raise


# ============================================================================
# TASKS
# ============================================================================

async def create_task(description: str, created_by: int,
                      attachments: Optional[list] = None) -> dict:
    """
    Create a new available task. Lucky status (11%) is rolled here and stored;
    the multiplier fires at completion time, not creation.
    Returns {'task_id': int, 'is_lucky': bool}.
    attachments: list of {type, url, label} dicts (images, youtube, twitter, url).
    """
    is_lucky = 1 if random.random() < cfg.LUCKY_TASK_CHANCE else 0
    now = _now()
    att_json = json.dumps(attachments or [])
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            '''INSERT INTO tt_tasks
               (description, base_points, is_lucky, status, created_at, created_by, attachments)
               VALUES (?, ?, ?, 'available', ?, ?, ?)''',
            (description, cfg.BASE_TASK_POINTS, is_lucky, now, created_by, att_json),
        )
        task_id = cursor.lastrowid
        await db.commit()
    return {"task_id": task_id, "is_lucky": bool(is_lucky)}


async def create_super_task(parent_description: str, subtask_descriptions: List[str],
                            created_by: int, attachments: Optional[list] = None) -> dict:
    """
    Create a super task (parent) + N subtasks.
    Each subtask rolls for lucky independently.
    completion_bonus = base_points × number_of_subtasks (split equally when all done).
    Returns {'parent_task_id': int, 'subtask_ids': [list], 'completion_bonus': int}.
    """
    now = _now()
    att_json = json.dumps(attachments or [])
    completion_bonus = cfg.BASE_TASK_POINTS * len(subtask_descriptions)

    pool = await get_pool()
    async with pool.acquire() as db:
        # Create parent (marker only, not claimable)
        cursor = await db.execute(
            '''INSERT INTO tt_tasks
               (description, base_points, is_lucky, status, created_at, created_by,
                attachments, parent_task_id, completion_bonus)
               VALUES (?, ?, 0, 'available', ?, ?, ?, NULL, ?)''',
            (f"🎯 {parent_description}", 0, now, created_by, att_json, completion_bonus),
        )
        parent_id = cursor.lastrowid

        # Create N subtasks, each linked to parent
        subtask_ids = []
        for i, desc in enumerate(subtask_descriptions):
            is_lucky = 1 if random.random() < cfg.LUCKY_TASK_CHANCE else 0
            cursor = await db.execute(
                '''INSERT INTO tt_tasks
                   (description, base_points, is_lucky, status, created_at, created_by,
                    attachments, parent_task_id, completion_bonus)
                   VALUES (?, ?, ?, 'available', ?, ?, ?, ?, 0)''',
                (desc, cfg.BASE_TASK_POINTS, is_lucky, now, created_by, att_json, parent_id),
            )
            subtask_ids.append(cursor.lastrowid)

        await db.commit()

    return {
        "parent_task_id": parent_id,
        "subtask_ids": subtask_ids,
        "completion_bonus": completion_bonus
    }


async def get_task(task_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute('SELECT * FROM tt_tasks WHERE task_id = ?', (task_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_tasks_by_status(status: str) -> List[dict]:
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            'SELECT * FROM tt_tasks WHERE status = ? ORDER BY created_at ASC', (status,)
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_all_tasks() -> List[dict]:
    """Return all non-completed tasks for the website JSON."""
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            "SELECT * FROM tt_tasks WHERE status != 'completed' ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def claim_task(task_id: int, user_id: int) -> bool:
    """Claim an available task. Returns False if already claimed/completed."""
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            """UPDATE tt_tasks SET status='claimed', claimed_by=?, claimed_at=?
               WHERE task_id=? AND status='available'""",
            (user_id, _now(), task_id),
        )
        await db.commit()
    return cursor.rowcount > 0


async def unclaim_task(task_id: int, user_id: int) -> bool:
    """Unclaim a task — only the helper who claimed it may unclaim."""
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            """UPDATE tt_tasks SET status='available', claimed_by=NULL, claimed_at=NULL
               WHERE task_id=? AND claimed_by=? AND status='claimed'""",
            (task_id, user_id),
        )
        await db.commit()
    return cursor.rowcount > 0


async def complete_task(task_id: int, user_id: int, *, bot=None) -> Optional[dict]:
    """
    Complete a task the user has claimed. Points = base_points × lucky_multiplier.
    If part of a super task and all subtasks now complete, award bonus to all completers.
    Returns {'base_points': float, 'bonus_points': float, 'total_points': float},
    or None if the task isn't claimed by this user.
    """
    pool = await get_pool()
    bonus_awarded = 0.0

    async with pool.acquire() as db:
        cursor = await db.execute(
            """SELECT * FROM tt_tasks
               WHERE task_id=? AND claimed_by=? AND status='claimed'""",
            (task_id, user_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        task = dict(row)

        multiplier = cfg.LUCKY_TASK_MULTIPLIER if task['is_lucky'] else 1.0
        points = task['base_points'] * multiplier

        await db.execute(
            "UPDATE tt_tasks SET status='completed', completed_at=? WHERE task_id=?",
            (_now(), task_id),
        )
        # SQL-side upsert — no read/write race on the balance
        await db.execute(
            '''INSERT INTO tt_helper_points
               (user_id, total_points, tasks_completed, lucky_tasks_completed, last_updated)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 total_points          = MAX(0, total_points + excluded.total_points),
                 tasks_completed       = tasks_completed + 1,
                 lucky_tasks_completed = lucky_tasks_completed + excluded.lucky_tasks_completed,
                 last_updated          = excluded.last_updated''',
            (user_id, points, 1 if task['is_lucky'] else 0, _now()),
        )

        # Check if this is a super task subtask and if all subtasks are now complete
        if task['parent_task_id']:
            parent_id = task['parent_task_id']
            cursor = await db.execute(
                "SELECT * FROM tt_tasks WHERE parent_task_id=?",
                (parent_id,)
            )
            subtasks = [dict(r) for r in await cursor.fetchall()]
            all_completed = all(t['status'] == 'completed' for t in subtasks)

            if all_completed:
                # Award bonus to all who completed a subtask
                parent = await db.execute('SELECT * FROM tt_tasks WHERE task_id=?', (parent_id,))
                parent = dict(await parent.fetchone())
                bonus_per_person = parent['completion_bonus'] // len(subtasks)
                bonus_awarded = bonus_per_person

                for t in subtasks:
                    if t['claimed_by']:
                        await db.execute(
                            '''INSERT INTO tt_helper_points
                               (user_id, total_points, tasks_completed, lucky_tasks_completed, last_updated)
                               VALUES (?, ?, 0, 0, ?)
                               ON CONFLICT(user_id) DO UPDATE SET
                                 total_points = total_points + excluded.total_points,
                                 last_updated = excluded.last_updated''',
                            (t['claimed_by'], bonus_per_person, _now()),
                        )

        await db.commit()

    if bot:
        try:
            from tasks import tipsandtricks as _tt_tasks
            await _tt_tasks.schedule_leaderboard_push(bot)
        except Exception:
            pass

    return {
        "base_points": points,
        "bonus_points": bonus_awarded,
        "total_points": points + bonus_awarded
    }


async def admin_complete_task(task_id: int, for_user_id: int, *, bot=None) -> Optional[dict]:
    """Force-complete any non-completed task for a user (admin override).
    Returns {'base_points': float, 'bonus_points': float, 'total_points': float} or None."""
    pool = await get_pool()
    bonus_awarded = 0.0

    async with pool.acquire() as db:
        cursor = await db.execute('SELECT * FROM tt_tasks WHERE task_id=?', (task_id,))
        row = await cursor.fetchone()
        if not row or dict(row)['status'] == 'completed':
            return None
        task = dict(row)

        multiplier = cfg.LUCKY_TASK_MULTIPLIER if task['is_lucky'] else 1.0
        points = task['base_points'] * multiplier

        await db.execute(
            """UPDATE tt_tasks SET status='completed', completed_at=?, claimed_by=?
               WHERE task_id=?""",
            (_now(), for_user_id, task_id),
        )
        await db.execute(
            '''INSERT INTO tt_helper_points
               (user_id, total_points, tasks_completed, lucky_tasks_completed, last_updated)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 total_points          = MAX(0, total_points + excluded.total_points),
                 tasks_completed       = tasks_completed + 1,
                 lucky_tasks_completed = lucky_tasks_completed + excluded.lucky_tasks_completed,
                 last_updated          = excluded.last_updated''',
            (for_user_id, points, 1 if task['is_lucky'] else 0, _now()),
        )

        # Check if super task should award bonus
        if task['parent_task_id']:
            parent_id = task['parent_task_id']
            cursor = await db.execute(
                "SELECT * FROM tt_tasks WHERE parent_task_id=?",
                (parent_id,)
            )
            subtasks = [dict(r) for r in await cursor.fetchall()]
            all_completed = all(t['status'] == 'completed' for t in subtasks)

            if all_completed:
                parent = await db.execute('SELECT * FROM tt_tasks WHERE task_id=?', (parent_id,))
                parent = dict(await parent.fetchone())
                bonus_per_person = parent['completion_bonus'] // len(subtasks)
                bonus_awarded = bonus_per_person

                for t in subtasks:
                    if t['claimed_by']:
                        await db.execute(
                            '''INSERT INTO tt_helper_points
                               (user_id, total_points, tasks_completed, lucky_tasks_completed, last_updated)
                               VALUES (?, ?, 0, 0, ?)
                               ON CONFLICT(user_id) DO UPDATE SET
                                 total_points = total_points + excluded.total_points,
                                 last_updated = excluded.last_updated''',
                            (t['claimed_by'], bonus_per_person, _now()),
                        )

        await db.commit()

    if bot:
        try:
            from tasks import tipsandtricks as _tt_tasks
            await _tt_tasks.schedule_leaderboard_push(bot)
        except Exception:
            pass

    return {
        "base_points": points,
        "bonus_points": bonus_awarded,
        "total_points": points + bonus_awarded
    }


async def cancel_task(task_id: int) -> bool:
    """Cancel a task (mark as completed without awarding points).
    Returns True if successful, False if task not found or already completed."""
    pool = await get_pool()

    async with pool.acquire() as db:
        cursor = await db.execute('SELECT * FROM tt_tasks WHERE task_id=?', (task_id,))
        row = await cursor.fetchone()
        if not row or dict(row)['status'] == 'completed':
            return False

        await db.execute(
            """UPDATE tt_tasks SET status='completed', completed_at=?
               WHERE task_id=?""",
            (_now(), task_id),
        )
        await db.commit()

    return True


async def delete_task(task_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute('DELETE FROM tt_tasks WHERE task_id=?', (task_id,))
        await db.commit()
    return cursor.rowcount > 0


async def apply_unclaimed_bonus() -> int:
    """
    Bump base_points to 2 for any task that has been available for ≥7 days.
    Returns the number of tasks updated.  Called by the hourly background loop.
    """
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=cfg.UNCLAIMED_BONUS_DAYS)
    ).isoformat()
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            """UPDATE tt_tasks SET base_points=?, bonus_applied=1
               WHERE status='available' AND bonus_applied=0 AND created_at <= ?""",
            (cfg.UNCLAIMED_BONUS_POINTS, cutoff),
        )
        await db.commit()
    return cursor.rowcount


async def get_user_tasks(user_id: int) -> List[dict]:
    """Return all currently claimed (not completed) tasks for a helper."""
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            """SELECT * FROM tt_tasks WHERE claimed_by=? AND status='claimed'
               ORDER BY claimed_at ASC""",
            (user_id,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_super_task_progress(parent_task_id: int) -> dict:
    """
    Return completion progress for a super task.
    Returns {'total': int, 'completed': int, 'completers': [user_id, ...], 'bonus_per_person': int}
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        # Get parent to get bonus amount and total subtasks
        cursor = await db.execute('SELECT * FROM tt_tasks WHERE task_id=?', (parent_task_id,))
        parent = await cursor.fetchone()
        if not parent:
            return None
        parent = dict(parent)

        # Get all subtasks
        cursor = await db.execute(
            'SELECT * FROM tt_tasks WHERE parent_task_id=?',
            (parent_task_id,)
        )
        subtasks = [dict(r) for r in await cursor.fetchall()]
        total = len(subtasks)

        # Count completed and get list of completers
        completed = sum(1 for t in subtasks if t['status'] == 'completed')
        completers = [t['claimed_by'] for t in subtasks if t['status'] == 'completed' and t['claimed_by']]

    if total == 0:
        return None

    bonus_per_person = parent['completion_bonus'] // total if completed == total else 0
    return {
        'total': total,
        'completed': completed,
        'completers': completers,
        'bonus_per_person': bonus_per_person,
        'completion_bonus': parent['completion_bonus']
    }


# ============================================================================
# LEADERBOARD / POINTS
# ============================================================================

async def get_total_ttp() -> float:
    """Return the total T&T points currently held across all helpers."""
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute('SELECT COALESCE(SUM(total_points), 0) FROM tt_helper_points')
        row = await cursor.fetchone()
    return float(row[0]) if row else 0.0


def compute_ttp_market_tier(total_ttp: float, total_wp: float) -> int:
    """Derive the T&T market tier from the live supply ratio."""
    if total_wp <= 0:
        return 3  # default to baseline
    ratio = total_ttp / total_wp
    for threshold, tier in cfg.TTP_WP_TIER_THRESHOLDS:
        if ratio < threshold:
            return tier
    return 5


async def spend_helper_points(user_id: int, amount: float) -> Optional[float]:
    """
    Deduct `amount` from a helper's balance atomically.
    Returns the new balance, or None if balance is insufficient.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            'SELECT total_points FROM tt_helper_points WHERE user_id = ?', (user_id,)
        )
        row = await cursor.fetchone()
        if not row or row[0] < amount:
            return None
        new_bal = row[0] - amount
        await db.execute(
            'UPDATE tt_helper_points SET total_points = ?, last_updated = ? WHERE user_id = ?',
            (new_bal, _now(), user_id),
        )
        await db.commit()
    return new_bal


async def get_leaderboard() -> List[dict]:
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute(
            'SELECT * FROM tt_helper_points ORDER BY total_points DESC, tasks_completed DESC'
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def set_helper_points(user_id: int, points: float) -> None:
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            '''INSERT INTO tt_helper_points
               (user_id, total_points, tasks_completed, lucky_tasks_completed, last_updated)
               VALUES (?, ?, 0, 0, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 total_points = ?,
                 last_updated = excluded.last_updated''',
            (user_id, points, _now(), points),
        )
        await db.commit()


# ============================================================================
# DUTY ASSIGNMENTS
# ============================================================================

async def assign_duty(duty_code: str, user_id: int, assigned_by: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            '''INSERT INTO tt_duty_assignments (duty_code, user_id, assigned_at, assigned_by)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(duty_code, user_id) DO UPDATE SET
                 assigned_at = excluded.assigned_at,
                 assigned_by = excluded.assigned_by''',
            (duty_code, user_id, _now(), assigned_by),
        )
        await db.commit()


async def remove_duty(duty_code: str, user_id: Optional[int] = None) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        if user_id is not None:
            cursor = await db.execute(
                'DELETE FROM tt_duty_assignments WHERE duty_code=? AND user_id=?',
                (duty_code, user_id)
            )
        else:
            cursor = await db.execute(
                'DELETE FROM tt_duty_assignments WHERE duty_code=?',
                (duty_code,)
            )
        await db.commit()
    return cursor.rowcount > 0


async def get_duty_assignments() -> Dict[str, list]:
    """Return {duty_code: [{user_id, assigned_at, assigned_by}, ...]} for every assigned duty."""
    pool = await get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute('SELECT * FROM tt_duty_assignments ORDER BY assigned_at ASC')
        rows = await cursor.fetchall()
        
    result = {}
    for r in rows:
        code = r['duty_code']
        if code not in result:
            result[code] = []
        result[code].append(dict(r))
    return result
