"""
Weekly Challenges - tasks/random_challenges.py

Week Start (at week start from config.json):
    5 challenges — one each for message, req, modlog, reviews, routes.
    Deck-based weighted mode pick with diversity / never-pair rules.

Mid-Week (+half_week_hours after week start, default 72h):
    3 challenges at difficulty 10 — bracket + race/24h + wild card (duties randomised).

Difficulty → target:
    Positively skewed curve per duty (slow growth at low difficulty, bigger jumps
    at the top). Difficulty 2 and 10 are anchored; message pins 8/9/10 explicitly.

Completion modes (see COMPLETION_MODE_LABEL / COMPLETION_MODE_CHECKERS):
    first_to_target, most_in_24h, consistency_gate, engagement_combo, balanced_staff,
    weekend_warrior, catchup_bracket, tiered_podium, closest_without_bust, route_runner,
    power_hour_overlap, proof_pipeline, underdog_24h, beat_last_week, active_week,
    seasonal_scramble.

Completion:
    Checked every hour by unified_weekly_loop. Winners use delta from baseline at announce.
    mode_params JSON stores eligibility, personal targets, multi-duty baselines, tier claims.

Scheduling:
    Fires on startup + precision sleep until week/mid-week times. DB rows act as
    a fire-once guard — if rows exist for the current week + phase, nothing fires again.

Dependencies:
    database.py              → get_pool()
    config.json              → global_dates.start_date  (format: DD/MM/YYYY)
    tasks/wave_points.py     → add_wave_points(user_id, amount, bot)
    tasks/unified_weekly_loop.py → check_and_complete_challenges(bot, all_stats)

Table:
    weekly_challenges (
        id, week_start, challenge_type, duty,
        target_count, difficulty, announced_at, message_id,
        completed_by_user, completed_at, description,
        baselines, completion_mode, expired_at, mode_params
    )
"""

import discord
from discord.ext import commands
import logging
import asyncio
import math
import random
import sqlite3
import statistics
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import json
import os

import database
from core.helpers import get_start_datetime, get_end_datetime

logger = logging.getLogger('discord')

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANNOUNCEMENT_CHANNEL_ID = 1475807412584841291   # Staff Hub
DUTIES_REPORT_GUILD_ID  = 1041450125391835186   # Guild used for guild-level lookups

CHALLENGE_DUTIES = ('message', 'req', 'modlog', 'reviews', 'routes')
WEEK_START_COUNT = 5
MIDWEEK_COUNT = 3
MIDWEEK_DIFFICULTY = 10

# Mode tiers for deck weights (staple → event)
_MODE_TIER_WEIGHT: dict[str, int] = {
    'first_to_target': 40,
    'beat_last_week': 40,
    'active_week': 40,
    'proof_pipeline': 40,
    'engagement_combo': 25,
    'balanced_staff': 25,
    'consistency_gate': 25,
    'weekend_warrior': 25,
    'catchup_bracket': 15,
    'underdog_24h': 15,
    'most_in_24h': 15,
    'tiered_podium': 8,
    'closest_without_bust': 8,
    'seasonal_scramble': 8,
    'route_runner': 5,
    'power_hour_overlap': 5,
}

BRACKET_MODES = frozenset({'catchup_bracket', 'underdog_24h', 'beat_last_week'})
H24_MODES = frozenset({'underdog_24h', 'most_in_24h'})
MULTI_DUTY_MODES = frozenset({'balanced_staff', 'route_runner'})
SLOW_BURN_MODES = frozenset({'closest_without_bust', 'tiered_podium'})
RACE_MODES = frozenset({'first_to_target', 'most_in_24h', 'underdog_24h', 'engagement_combo'})

# Valid (duty, mode) pairs for the deck
DUTY_ALLOWED_MODES: dict[str, frozenset[str]] = {
    'message': frozenset({
        'first_to_target', 'engagement_combo', 'active_week', 'weekend_warrior',
        'consistency_gate', 'seasonal_scramble', 'catchup_bracket', 'underdog_24h',
        'most_in_24h', 'tiered_podium', 'closest_without_bust', 'beat_last_week',
        'power_hour_overlap',
    }),
    'req': frozenset({
        'first_to_target', 'beat_last_week', 'catchup_bracket', 'closest_without_bust',
        'underdog_24h', 'most_in_24h', 'tiered_podium',
    }),
    'modlog': frozenset({
        'first_to_target', 'balanced_staff', 'route_runner', 'tiered_podium',
        'catchup_bracket', 'most_in_24h', 'closest_without_bust',
    }),
    'reviews': frozenset({
        'first_to_target', 'proof_pipeline', 'consistency_gate', 'catchup_bracket',
        'underdog_24h', 'most_in_24h', 'tiered_podium', 'closest_without_bust',
        'beat_last_week',
    }),
    'routes': frozenset({
        'first_to_target', 'route_runner', 'beat_last_week', 'tiered_podium',
        'catchup_bracket', 'closest_without_bust',
    }),
}

COMPLETION_MODE_LABEL = {
    'first_to_target': '🏁 First to Target',
    'most_in_24h': '⏱️ Most in 24 Hours',
    'consistency_gate': '📅 Consistency Gate',
    'engagement_combo': '🔥 Engagement Combo',
    'balanced_staff': '⚖️ Balanced Staff',
    'weekend_warrior': '🌴 Weekend Warrior',
    'catchup_bracket': '📈 Catch-up Bracket',
    'tiered_podium': '🏅 Tiered Podium',
    'closest_without_bust': '🎯 Closest Without Bust',
    'route_runner': '🗺️ Route Runner',
    'power_hour_overlap': '⚡ Power Hour Overlap',
    'proof_pipeline': '🔍 Proof Pipeline',
    'underdog_24h': '🐕 Underdog 24h',
    'beat_last_week': '📊 Beat Last Week',
    'active_week': '✅ Active Week',
    'seasonal_scramble': '🎲 Seasonal Scramble',
}

# Debounce live-progress embed edits (phase_key -> fingerprint)
_last_progress_snapshot: dict[str, str] = {}

# Wave Points paid to the challenge winner = difficulty × this multiplier
CHALLENGE_WP_MULTIPLIER = 10


def challenge_wp_reward(difficulty: int) -> int:
    """Convert challenge difficulty (1–10) to Wave Points awarded on win."""
    return int(difficulty) * CHALLENGE_WP_MULTIPLIER


# ---------------------------------------------------------------------------
# Difficulty → target (positively skewed, no tiers)
# ---------------------------------------------------------------------------
# exponent > 1 = positive skew (compressed low end, stretched high end)
_POSITIVE_SKEW = 1.4

# Owner-tuned anchors: difficulty 2 = approachable, 10 = stretch goal.
_DUTY_ANCHORS: dict[str, tuple[int, int]] = {
    'message': (165, 1600),
    'req':     (16,  150),
    'modlog':  (8,   80),
    'reviews': (8,   80),
    'routes':  (2,   12),
}

_DUTY_FLOOR: dict[str, int] = {
    'message': 50,
    'req':     8,
    'modlog':  4,
    'reviews': 2,
    'routes':  1,
}

# Message high-end pins (owner-tuned positive skew at the top)
_MESSAGE_HIGH_PINS: dict[int, int] = {8: 1000, 9: 1300, 10: 1600}
# Lower exponent = slightly higher targets for difficulties 3–7 (still pins 8–10)
_MESSAGE_MID_SKEW = 1.2


def _skew_frac(d: int, d_lo: int, d_hi: int, skew: float = _POSITIVE_SKEW) -> float:
    """Map difficulty level to 0..1 with positive skew."""
    if d_hi <= d_lo:
        return 1.0
    return ((d - d_lo) / (d_hi - d_lo)) ** skew


def _build_skewed_target_table(
    anchor_2: int,
    anchor_10: int,
    floor: int,
) -> dict[int, int]:
    """
    Map difficulty 1–10 → weekly target via positively skewed interpolation.
    Guarantees strict monotonic increase and difficulty 10 == anchor_10.
    """
    table: dict[int, int] = {
        1: max(floor, anchor_2 // 2),
        2: anchor_2,
    }
    prev = anchor_2
    for d in range(3, 10):
        frac = _skew_frac(d, 2, 10)
        t = int(round(anchor_2 + frac * (anchor_10 - anchor_2)))
        t = min(t, anchor_10 - (10 - d))
        table[d] = max(prev + 1, t)
        prev = table[d]
    table[10] = anchor_10
    return table


def _build_message_target_table() -> dict[int, int]:
    """Message targets: skewed 1–7 up to pin@8, then owner pins for 8/9/10."""
    anchor_2 = _DUTY_ANCHORS['message'][0]
    pin_8 = _MESSAGE_HIGH_PINS[8]
    floor = _DUTY_FLOOR['message']
    table: dict[int, int] = {
        1: max(floor, anchor_2 // 2),
        2: anchor_2,
    }
    prev = anchor_2
    for d in range(3, 8):
        frac = ((d - 2) / (8 - 2)) ** _MESSAGE_MID_SKEW
        t = int(round(anchor_2 + frac * (pin_8 - anchor_2)))
        table[d] = max(prev + 1, t)
        prev = table[d]
    table.update(_MESSAGE_HIGH_PINS)
    return table


def _build_all_difficulty_targets() -> dict[str, dict[int, int]]:
    tables: dict[str, dict[int, int]] = {}
    for duty in CHALLENGE_DUTIES:
        if duty == 'message':
            tables[duty] = _build_message_target_table()
        else:
            a2, a10 = _DUTY_ANCHORS[duty]
            floor = _DUTY_FLOOR[duty]
            tables[duty] = _build_skewed_target_table(a2, a10, floor)
    return tables


DIFFICULTY_TARGETS: dict[str, dict[int, int]] = _build_all_difficulty_targets()


def target_for_difficulty(duty: str, difficulty: int) -> int:
    """Return the weekly target count for a duty at difficulty 1–10."""
    d = max(1, min(10, int(difficulty)))
    return DIFFICULTY_TARGETS[duty][d]

# ---------------------------------------------------------------------------
# Date-change wake-up event
# ---------------------------------------------------------------------------
# Set by the Cog listener when GlobalConfig dispatches 'dates_updated'.
# The scheduler uses _interruptible_sleep() so it reacts immediately instead
# of waiting out its original multi-hour sleep.
_reschedule_event: asyncio.Event | None = None


def _get_reschedule_event() -> asyncio.Event:
    global _reschedule_event
    if _reschedule_event is None:
        _reschedule_event = asyncio.Event()
    return _reschedule_event


async def _interruptible_sleep(seconds: float) -> bool:
    """
    Sleep for up to `seconds`, but wake immediately if dates change.

    Returns:
        True  → woken early by a date-change event (re-evaluate now)
        False → slept the full duration naturally
    """
    event = _get_reschedule_event()
    event.clear()
    try:
        await asyncio.wait_for(asyncio.shield(event.wait()), timeout=seconds)
        event.clear()
        logger.info("⚡ Challenge scheduler woken early — dates were updated")
        return True   # interrupted
    except asyncio.TimeoutError:
        return False  # natural expiry


DUTY_EMOJI = {
    'req':     '📋',
    'message': '💬',
    'modlog':  '📝',
    'reviews': '🔍',
    'routes':  '🗺️',
}

# Human-readable labels
DUTY_LABEL = {
    'req':     'Map Requests',
    'message': 'Messages',
    'modlog':  'Modlog Actions',
    'reviews': 'Proof Reviews',
    'routes':  'Route Completions',
}

# Which roles qualify — informational only (shown in embed).
# Actual eligibility comes from all_stats being pre-filtered by duties_scan.
DUTY_ROLE_LABEL = {
    'req':     'Map Request Helper',
    'message': 'All Staff',
    'modlog':  'All Staff',
    'reviews': 'All Staff',
    'routes':  'Loot / Surge Route Makers',
}

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def init_challenges_table():
    """Create weekly_challenges table if not present."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS weekly_challenges (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                week_start        TEXT    NOT NULL,
                challenge_type    TEXT    NOT NULL,
                duty              TEXT    NOT NULL,
                target_count      INTEGER NOT NULL,
                difficulty        INTEGER NOT NULL,
                announced_at      TEXT,
                message_id        INTEGER,
                completed_by_user INTEGER,
                completed_at      TEXT,
                description       TEXT,
                baselines         TEXT,
                completion_mode   TEXT    NOT NULL DEFAULT 'first_to_target',
                expired_at        TEXT
            )
        ''')
        for col_sql, label in (
            ('ALTER TABLE weekly_challenges ADD COLUMN description TEXT', 'description'),
            ('ALTER TABLE weekly_challenges ADD COLUMN baselines TEXT', 'baselines'),
            (
                "ALTER TABLE weekly_challenges ADD COLUMN completion_mode TEXT "
                "NOT NULL DEFAULT 'first_to_target'",
                'completion_mode',
            ),
            ('ALTER TABLE weekly_challenges ADD COLUMN expired_at TEXT', 'expired_at'),
            ('ALTER TABLE weekly_challenges ADD COLUMN mode_params TEXT', 'mode_params'),
        ):
            try:
                await db.execute(col_sql)
                logger.info(f"✅ Migrated weekly_challenges: added {label} column")
            except Exception:
                pass
        await db.commit()
    logger.info("✅ weekly_challenges table initialised")


def _challenge_row_dict(row) -> dict:
    """Map a weekly_challenges row to a dict (tuple or sqlite Row)."""
    if hasattr(row, 'keys'):
        return dict(row)
    cols = (
        'id', 'week_start', 'challenge_type', 'duty', 'target_count', 'difficulty',
        'announced_at', 'message_id', 'completed_by_user', 'completed_at', 'description',
        'baselines', 'completion_mode', 'expired_at', 'mode_params',
    )
    return {col: row[i] if i < len(row) else None for i, col in enumerate(cols)}


def _extract_count(raw) -> int:
    """Extract integer count from all_stats values (int or dict with count/total)."""
    if isinstance(raw, dict):
        if 'count' in raw:
            return int(raw['count'] or 0)
        if 'total' in raw:
            return int(raw['total'] or 0)
        for v in raw.values():
            if isinstance(v, (int, float)):
                return int(v)
        return 0
    return int(raw or 0)


def get_count_value(val) -> int:
    """Prefer count key for dict stats, fallback int, then total."""
    if isinstance(val, dict):
        if 'count' in val and isinstance(val['count'], (int, float)):
            return int(val['count'])
        if 'total' in val and isinstance(val['total'], (int, float)):
            return int(val['total'])
        for v in val.values():
            if isinstance(v, (int, float)):
                return int(v)
        return 0
    return int(val) if isinstance(val, (int, float)) else 0


def compute_rank_total(uid: int, all_stats: dict) -> int:
    """
    Engagement rank_total matching unified_weekly_loop:
      rank_messages = min(ceil(messages/70*100), 100)
      rank_days = min(ceil(days_active/7*100), 100)
      rank_total = min(ceil((rank_messages+rank_days)/2) + modlog + reviews, 100)
    """
    msg_raw = all_stats.get('message', {}).get(uid, 0)
    if isinstance(msg_raw, dict):
        messages = int(msg_raw.get('count', 0))
        days_list = msg_raw.get('days', [])
        days_set = set()
        for d in days_list:
            try:
                if isinstance(d, str):
                    days_set.add(datetime.fromisoformat(d).date().weekday())
                else:
                    days_set.add(d)
            except Exception:
                pass
        days_active = len(days_set)
    else:
        messages = int(msg_raw or 0)
        days_active = 0

    modlog_raw = all_stats.get('modlog', {}).get(uid, 0)
    modlog = get_count_value(modlog_raw)

    reviews_raw = all_stats.get('reviews', {}).get(uid, 0)
    reviews = get_count_value(reviews_raw)

    rank_messages = min(math.ceil(messages / 70 * 100), 100)
    rank_days = min(math.ceil(days_active / 7 * 100), 100)
    return min(math.ceil((rank_messages + rank_days) / 2) + modlog + reviews, 100)


def _parse_baselines(raw) -> dict[int, int]:
    """Parse per-user baseline JSON stored on a challenge row."""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return {}
    out: dict[int, int] = {}
    for uid, count in data.items():
        try:
            out[int(uid)] = int(count or 0)
        except (TypeError, ValueError):
            continue
    return out


def _parse_mode_params(raw) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _days_elapsed_in_week() -> int:
    try:
        with open('config.json', 'r') as f:
            start = json.load(f).get('global_dates', {}).get('start_date')
        if not start:
            return 7
        week_start = datetime.strptime(start, '%d/%m/%Y').replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc).date() - week_start.date()).days + 1
        return max(1, min(7, elapsed))
    except Exception:
        return 7


def _all_uids_in_stats(all_stats: dict) -> set[int]:
    uids: set[int] = set()
    for duty in CHALLENGE_DUTIES:
        for uid in all_stats.get(duty, {}):
            try:
                uids.add(int(uid))
            except (TypeError, ValueError):
                continue
    return uids


def _message_weekdays(uid: int, all_stats: dict) -> set[int]:
    msg_raw = all_stats.get('message', {}).get(uid, {})
    if not isinstance(msg_raw, dict):
        return set()
    weekdays: set[int] = set()
    for d in msg_raw.get('days', []):
        try:
            if isinstance(d, str):
                weekdays.add(datetime.fromisoformat(d).weekday())
            else:
                weekdays.add(int(d))
        except Exception:
            pass
    return weekdays


def _message_active_days_count(uid: int, all_stats: dict) -> int:
    msg_raw = all_stats.get('message', {}).get(uid, {})
    if not isinstance(msg_raw, dict):
        return 0
    unique_dates: set = set()
    for d in msg_raw.get('days', []):
        try:
            if isinstance(d, str):
                unique_dates.add(datetime.fromisoformat(d).date())
            else:
                unique_dates.add(d)
        except Exception:
            pass
    return len(unique_dates)


def _review_stats(uid: int, all_stats: dict) -> tuple[int, int]:
    raw = all_stats.get('reviews', {}).get(uid, 0)
    if isinstance(raw, dict):
        return int(raw.get('count', 0)), int(raw.get('unique_days', 0))
    return int(raw or 0), 0


def _pick_best_delta(deltas: dict[int, int]) -> int | None:
    if not deltas:
        return None
    max_delta = max(deltas.values())
    if max_delta <= 0:
        return None
    tied = [uid for uid, d in deltas.items() if d == max_delta]
    return random.choice(tied)


async def _fetch_combined_route_counts() -> dict[int, int]:
    """Completed loot + surge routes in the current config week."""
    loot = await _fetch_route_counts_week('loot')
    surge = await _fetch_route_counts_week('surge')
    combined = dict(loot)
    for uid, cnt in surge.items():
        combined[int(uid)] = combined.get(int(uid), 0) + int(cnt)
    return combined


async def _count_active_route_makers() -> int:
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT COUNT(DISTINCT user_id) FROM loot_route_positions'
            ) as cur:
                row = await cur.fetchone()
            loot_n = int(row[0] or 0) if row else 0
            try:
                async with db.execute(
                    'SELECT COUNT(DISTINCT user_id) FROM surge_route_positions'
                ) as cur2:
                    row2 = await cur2.fetchone()
                surge_n = int(row2[0] or 0) if row2 else 0
            except Exception:
                surge_n = 0
        return max(loot_n, surge_n)
    except Exception:
        return 0


async def _ph_fired_last_week() -> bool:
    try:
        with open('config.json', 'r') as f:
            start = json.load(f).get('global_dates', {}).get('start_date')
        if not start:
            return True
        week_start = datetime.strptime(start, '%d/%m/%Y').replace(tzinfo=timezone.utc)
        prior = (week_start - timedelta(days=7)).date()
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                """SELECT 1 FROM power_hour_state WHERE hour_key IS NOT NULL
                   AND hour_key != 'CANCELLED' LIMIT 1"""
            ) as cur:
                if await cur.fetchone():
                    return True
        return False
    except Exception:
        return True


def _season_active() -> bool:
    try:
        with open('config.json', 'r') as f:
            return bool(json.load(f).get('challenge_season', {}).get('active'))
    except Exception:
        return False


def _prior_week_start(week_start: str) -> str:
    dt = datetime.strptime(week_start, '%d/%m/%Y').replace(tzinfo=timezone.utc)
    return (dt - timedelta(days=7)).strftime('%d/%m/%Y')


async def _get_week_modes(week_start: str, challenge_type: str | None = None) -> set[str]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        if challenge_type:
            async with db.execute(
                'SELECT completion_mode FROM weekly_challenges WHERE week_start = ? AND challenge_type = ?',
                (week_start, challenge_type),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                'SELECT completion_mode FROM weekly_challenges WHERE week_start = ?',
                (week_start,),
            ) as cur:
                rows = await cur.fetchall()
    return {r[0] for r in rows if r and r[0]}


async def _get_week_duty_mode_pairs(week_start: str, challenge_type: str) -> set[tuple[str, str]]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT duty, completion_mode FROM weekly_challenges WHERE week_start = ? AND challenge_type = ?',
            (week_start, challenge_type),
        ) as cur:
            rows = await cur.fetchall()
    return {(r[0], r[1]) for r in rows if r}


async def _fetch_route_counts_week(route_type: str = 'loot') -> dict[int, int]:
    from core.helpers import get_start_datetime, get_end_datetime
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f)
        gd = cfg.get('global_dates', {})
        start_dt = get_start_datetime(gd['start_date'])
        end_dt = get_end_datetime(gd['end_date'])
    except Exception:
        return {}
    table = 'route_assignments' if route_type == 'loot' else 'surge_route_assignments'
    start_s = start_dt.isoformat()
    end_s = end_dt.isoformat()
    counts: dict[int, int] = {}
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                f"""SELECT user_id, COUNT(*) FROM {table}
                    WHERE status = 'completed'
                      AND completed_at IS NOT NULL
                      AND completed_at >= ? AND completed_at < ?""",
                (start_s, end_s),
            ) as cur:
                rows = await cur.fetchall()
        for uid, cnt in rows:
            counts[int(uid)] = int(cnt)
    except Exception as e:
        logger.warning(f"⚠️ _fetch_route_counts_week({route_type}): {e}")
    return counts


async def _fetch_prior_week_targets(duty: str) -> dict[int, int]:
    """Prior finalized week counts per user for beat_last_week."""
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f)
        start = cfg.get('global_dates', {}).get('start_date')
        if not start:
            return {}
        week_start = datetime.strptime(start, '%d/%m/%Y').replace(tzinfo=timezone.utc)
        prior_start = (week_start - timedelta(days=7)).strftime('%d/%m/%Y')
        pool = await database.get_pool()
        out: dict[int, int] = {}
        async with pool.acquire() as db:
            async with db.execute(
                """SELECT user_id, count FROM staff_insights_history
                   WHERE duty_type = ? AND week_start = ? AND is_midweek = 0""",
                (duty, prior_start),
            ) as cur:
                rows = await cur.fetchall()
        for uid, cnt in rows:
            out[int(uid)] = int(cnt or 0)
        return out
    except Exception as e:
        logger.warning(f"⚠️ _fetch_prior_week_targets({duty}): {e}")
        return {}


async def update_mode_params(challenge_id: int, params: dict, bot=None):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE weekly_challenges SET mode_params = ? WHERE id = ?',
            (json.dumps(params), challenge_id),
        )
        await db.commit()
    asyncio.ensure_future(_push_events_payload(bot))


async def _enrich_mode_params_at_fire(
    ch: dict,
    baselines_all: dict[str, dict[int, int]],
    bot=None,
) -> dict:
    """Attach fire-time mode_params (eligibility, personal targets, multi-duty baselines)."""
    mode = ch.get('completion_mode', 'first_to_target')
    duty = ch['duty']
    params = dict(ch.get('mode_params') or {})
    duty_counts = baselines_all.get(duty, {})

    if mode == 'catchup_bracket':
        ranked = sorted(duty_counts.items(), key=lambda x: x[1])
        half = max(1, len(ranked) // 2)
        params.setdefault('delta', 25)
        params['eligible_uids'] = [int(uid) for uid, _ in ranked[:half]]

    elif mode == 'underdog_24h':
        if duty_counts:
            vals = sorted(duty_counts.values())
            median = vals[len(vals) // 2]
            params['eligible_uids'] = [int(uid) for uid, c in duty_counts.items() if c <= median]

    elif mode == 'beat_last_week':
        prior = await _fetch_prior_week_targets(duty)
        personal: dict[str, int] = {}
        all_uids = set(duty_counts) | set(prior)
        if prior:
            bump = max(5, ch['target'] // 4)
            for uid in all_uids:
                personal[str(uid)] = int(prior.get(uid, 0)) + bump
        elif duty_counts:
            import statistics
            med = int(statistics.median(duty_counts.values()))
            bump = max(5, ch['target'] // 4)
            for uid in duty_counts:
                personal[str(uid)] = med + bump
        params['personal_targets'] = personal

    elif mode == 'balanced_staff':
        duties = params.get('duties', ['modlog', 'reviews'])
        multi_bl: dict[str, dict[str, int]] = {}
        for d in duties:
            multi_bl[d] = {str(k): v for k, v in baselines_all.get(d, {}).items()}
        params['baselines'] = multi_bl

    elif mode == 'proof_pipeline':
        params.setdefault('target', ch['target'])
        params.setdefault('min_days', min(6, max(3, ch['difficulty'] // 2)))

    elif mode == 'seasonal_scramble':
        try:
            with open('config.json', 'r') as f:
                season = json.load(f).get('challenge_season') or {}
            if season.get('active'):
                params['label'] = season.get('label', 'Season')
                params['duty'] = season.get('duty', duty)
                params['multiplier'] = float(season.get('multiplier', 1.25))
        except Exception:
            pass

    elif mode == 'route_runner':
        params.setdefault('routes_target', 2)
        params.setdefault('modlog_target', 30)
        params.setdefault('route_type', 'loot')
        params['modlog_baselines'] = {
            str(k): v for k, v in baselines_all.get('modlog', {}).items()
        }

    elif mode == 'tiered_podium':
        base_wp = challenge_wp_reward(ch['difficulty'])
        params.setdefault('tiers', [
            {'threshold': ch['target'], 'wp': base_wp},
            {'threshold': max(1, int(ch['target'] * 0.85)), 'wp': max(10, int(base_wp * 0.6))},
            {'threshold': max(1, int(ch['target'] * 0.7)), 'wp': max(10, int(base_wp * 0.3))},
        ])
        params.setdefault('claimed', [])

    elif mode == 'closest_without_bust':
        params.setdefault('target', ch['target'])
        params.setdefault('resolve', 'week_end')

    elif mode == 'power_hour_overlap':
        params.setdefault('ph_baseline', None)

    return params


async def _ensure_reviews_extended(all_stats: dict) -> dict:
    """Return all_stats copy with reviews as {count, unique_days} dicts."""
    reviews = all_stats.get('reviews', {})
    if not reviews:
        return all_stats
    sample = next(iter(reviews.values()), None)
    if isinstance(sample, dict) and 'count' in sample:
        return all_stats
    from core.helpers import get_start_datetime, get_end_datetime
    from tasks.unified_weekly_loop import scan_reviews_extended
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f)
        gd = cfg.get('global_dates', {})
        start_dt = get_start_datetime(gd['start_date'])
        end_dt = get_end_datetime(gd['end_date'])
        extended = await scan_reviews_extended(start_dt, end_dt)
    except Exception:
        extended = {int(uid): {'count': int(c), 'unique_days': 0} for uid, c in reviews.items()}
    enriched = dict(all_stats)
    enriched['reviews'] = extended
    return enriched


async def _build_current_all_stats(bot) -> dict:
    """Current week duty stats for challenge resolution (cache + reviews extended)."""
    from core.helpers import get_start_datetime, get_end_datetime
    from tasks.unified_weekly_loop import scan_reviews_extended
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f)
        gd = cfg.get('global_dates', {})
        start_date, end_date = gd.get('start_date'), gd.get('end_date')
        if not start_date or not end_date:
            return {}
        cached = await database.get_cached_week_stats(start_date, end_date)
        all_stats: dict = {'req': {}, 'modlog': {}, 'message': {}, 'reviews': {}}
        for duty in ('req', 'modlog', 'message'):
            for uid_str, data in cached.get(duty, {}).items():
                uid = int(uid_str)
                if isinstance(data, dict):
                    all_stats[duty][uid] = data
                else:
                    all_stats[duty][uid] = {'count': int(data or 0)}
        start_dt = get_start_datetime(start_date)
        end_dt = get_end_datetime(end_date)
        all_stats['reviews'] = await scan_reviews_extended(start_dt, end_dt)
        combined = await _fetch_combined_route_counts()
        all_stats['routes'] = {uid: {'count': c} for uid, c in combined.items()}
        return all_stats
    except Exception as e:
        logger.warning(f"⚠️ _build_current_all_stats: {e}")
        return {}


async def _enrich_all_stats_for_modes(all_stats: dict) -> dict:
    stats = await _ensure_reviews_extended(all_stats)
    stats = dict(stats)
    try:
        from tasks.power_hour import get_power_hour_state
        ph = await get_power_hour_state()
        stats['_ph_active'] = bool(ph.get('active'))
    except Exception:
        stats['_ph_active'] = False
    loot = await _fetch_route_counts_week('loot')
    surge = await _fetch_route_counts_week('surge')
    combined = await _fetch_combined_route_counts()
    stats['_route_counts'] = {'loot': loot, 'surge': surge, 'combined': combined}
    if 'routes' not in stats or not stats.get('routes'):
        stats['routes'] = {uid: {'count': c} for uid, c in combined.items()}
    return stats


async def _award_challenge_winner(bot, ch: dict, winner_id: int, wp_reward: int | None = None):
    cid = ch['id']
    duty = ch['duty']
    target = ch['target_count']
    difficulty = ch['difficulty']
    mode = ch.get('completion_mode') or 'first_to_target'
    claimed = await record_completion(cid, winner_id, bot=bot)
    if not claimed:
        return False
    logger.info(f"  🏆 Challenge {cid} ({duty} ×{target}, {mode}) won by user {winner_id}")
    reward = wp_reward if wp_reward is not None else challenge_wp_reward(difficulty)
    try:
        from tasks.wave_points import add_wave_points
        new_total = await add_wave_points(winner_id, reward, bot=bot, reason="Challenge reward")
        logger.info(f"  💎 +{reward} WP → user {winner_id} (new total: {new_total})")
    except Exception as e:
        logger.error(f"  ❌ Failed to award Wave Points: {e}")
    await announce_winner(bot, winner_id, {
        'duty': duty, 'target': target, 'difficulty': difficulty, 'completion_mode': mode,
    })
    return True


async def _process_tiered_podium(bot, ch: dict, all_stats: dict) -> bool:
    """Award at most one unclaimed tier per hourly check."""
    params = _parse_mode_params(ch.get('mode_params'))
    tiers = params.get('tiers')
    if not tiers:
        t = ch['target_count']
        base_wp = challenge_wp_reward(ch['difficulty'])
        tiers = [
            {'threshold': t, 'wp': base_wp},
            {'threshold': max(1, int(t * 0.85)), 'wp': max(10, int(base_wp * 0.6))},
            {'threshold': max(1, int(t * 0.7)), 'wp': max(10, int(base_wp * 0.3))},
        ]
        params['tiers'] = tiers
    claimed = list(params.get('claimed', []))
    claimed_uids = {int(c['uid']) for c in claimed}
    claimed_indices = {int(c['tier_index']) for c in claimed}
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    sorted_tiers = sorted(enumerate(tiers), key=lambda x: int(x[1].get('threshold', 0)), reverse=True)
    for tier_index, tier in sorted_tiers:
        if tier_index in claimed_indices:
            continue
        threshold = int(tier.get('threshold', ch['target_count']))
        wp = int(tier.get('wp', challenge_wp_reward(ch['difficulty'])))
        qualified = [(uid, d) for uid, d in deltas.items() if d >= threshold and uid not in claimed_uids]
        if not qualified:
            continue
        max_delta = max(d for _, d in qualified)
        tied = [uid for uid, d in qualified if d == max_delta]
        winner = random.choice(tied)
        try:
            from tasks.wave_points import add_wave_points
            await add_wave_points(winner, wp, bot=bot, reason="Challenge tier reward")
            logger.info(f"  🏅 Tier {tier_index} of challenge {ch['id']} → user {winner} (+{wp} WP)")
        except Exception as e:
            logger.error(f"  ❌ Tiered podium WP award failed: {e}")
            return False
        claimed.append({'uid': winner, 'tier_index': tier_index, 'wp': wp})
        params['claimed'] = claimed
        await update_mode_params(ch['id'], params, bot=bot)
        await announce_winner(bot, winner, {
            'duty': duty, 'target': threshold, 'difficulty': ch['difficulty'],
            'completion_mode': 'tiered_podium',
        })
        if len(claimed) >= len(tiers):
            await record_completion(ch['id'], winner, bot=bot)
        return True
    return False


async def snapshot_duty_baselines(bot) -> dict[str, dict[int, int]]:
    """
    Snapshot current week duty counts per user (one count per duty).
    Uses DB cache for req/modlog/message and scan_reviews for reviews.
    """
    from core.helpers import get_start_datetime, get_end_datetime
    from tasks.unified_weekly_loop import scan_reviews

    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        gd = config.get('global_dates', {})
        start_date, end_date = gd.get('start_date'), gd.get('end_date')
    except Exception as e:
        logger.error(f"❌ snapshot_duty_baselines: config read failed: {e}")
        return {duty: {} for duty in CHALLENGE_DUTIES}

    if not start_date or not end_date:
        return {duty: {} for duty in CHALLENGE_DUTIES}

    baselines: dict[str, dict[int, int]] = {duty: {} for duty in CHALLENGE_DUTIES}
    cached = await database.get_cached_week_stats(start_date, end_date)
    for duty in ('req', 'modlog', 'message'):
        for uid_str, data in cached.get(duty, {}).items():
            try:
                baselines[duty][int(uid_str)] = _extract_count(data)
            except (TypeError, ValueError):
                continue

    try:
        start_dt = get_start_datetime(start_date)
        end_dt = get_end_datetime(end_date)
        review_counts = await scan_reviews(start_dt, end_dt)
        baselines['reviews'] = {int(uid): int(cnt) for uid, cnt in review_counts.items()}
    except Exception as e:
        logger.warning(f"⚠️ snapshot_duty_baselines: reviews scan failed: {e}")

    try:
        baselines['routes'] = await _fetch_combined_route_counts()
    except Exception as e:
        logger.warning(f"⚠️ snapshot_duty_baselines: routes scan failed: {e}")

    return baselines


async def get_challenges_for_phase(week_start: str, challenge_type: str) -> list:
    """Return all DB rows for a given week + phase (week_start | mid_week)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT * FROM weekly_challenges WHERE week_start = ? AND challenge_type = ?',
            (week_start, challenge_type)
        ) as cur:
            return await cur.fetchall()


async def get_all_active_challenges(week_start: str) -> list:
    """Return every challenge row for the current week."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT * FROM weekly_challenges WHERE week_start = ?',
            (week_start,)
        ) as cur:
            return await cur.fetchall()


async def save_challenge(week_start: str, challenge_type: str, duty: str,
                         target: int, difficulty: int, description: str | None = None,
                         baselines: str | None = None,
                         completion_mode: str = 'first_to_target',
                         mode_params: str | None = None,
                         bot=None):
    """Insert a new challenge row and record announced_at."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            INSERT INTO weekly_challenges
                (week_start, challenge_type, duty, target_count, difficulty,
                 announced_at, description, baselines, completion_mode, mode_params)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            week_start, challenge_type, duty, target, difficulty,
            datetime.now(timezone.utc).isoformat(), description, baselines,
            completion_mode or 'first_to_target', mode_params,
        ))
        await db.commit()
    asyncio.ensure_future(_push_events_payload(bot))


async def mark_challenge_expired(challenge_id: int, bot=None) -> bool:
    """Mark an uncompleted challenge as expired. Returns True if this call claimed it."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute('''
            UPDATE weekly_challenges
            SET expired_at = ?
            WHERE id = ? AND completed_by_user IS NULL AND expired_at IS NULL
        ''', (datetime.now(timezone.utc).isoformat(), challenge_id))
        await db.commit()
        asyncio.ensure_future(_push_events_payload(bot))
        return cursor.rowcount > 0


async def record_completion(challenge_id: int, user_id: int, bot=None):
    """
    Mark a challenge as won. WHERE completed_by_user IS NULL prevents a race
    condition between concurrent scans from awarding the same challenge twice.
    Returns True if this call claimed the row, False if it was already claimed.
    """
    pool = await database.get_pool()
    async with pool.acquire() as db:
        try:
            await db.execute("ALTER TABLE weekly_challenges ADD COLUMN winner_name TEXT")
        except Exception:
            pass
        winner_name = await _resolve_display_name(bot, user_id)
        cursor = await db.execute('''
            UPDATE weekly_challenges
            SET completed_by_user = ?, completed_at = ?, winner_name = ?
            WHERE id = ? AND completed_by_user IS NULL
        ''', (user_id, datetime.now(timezone.utc).isoformat(), winner_name, challenge_id))
        await db.commit()
        asyncio.ensure_future(_push_events_payload(bot))
        return cursor.rowcount > 0


async def save_announcement_message_id(week_start: str, challenge_type: str, message_id: int):
    """Save the announcement message ID for a challenge phase (for editing instead of reposting)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            UPDATE weekly_challenges
            SET message_id = ?
            WHERE week_start = ? AND challenge_type = ?
        ''', (message_id, week_start, challenge_type))
        await db.commit()


async def get_announcement_message_id(week_start: str, challenge_type: str) -> int | None:
    """Get the message ID for a challenge phase announcement."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT message_id FROM weekly_challenges WHERE week_start = ? AND challenge_type = ? LIMIT 1',
            (week_start, challenge_type)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

# ---------------------------------------------------------------------------
# Challenge generation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Challenge Description Templates
# ---------------------------------------------------------------------------

# Difficulty-tiered template pools. We pick from the matching pool so the
# tone scales with the challenge's difficulty (1-3 chill, 4-7 hyped, 8-10 epic).
_DESC_TEMPLATES_LOW = [
    "Warm up the engines — first to {target} {duty} takes it.",
    "Easy glory — race to {target} {duty} and grab the W.",
    "Quick win available: be first to {target} {duty}.",
    "{target} {duty}. One winner. Don't sleep on this one.",
]

_DESC_TEMPLATES_MID = [
    "Race to {target} {duty} and claim victory!",
    "Show your skill — first to reach {target} {duty} wins!",
    "Lock in and grind — {target} {duty} between you and the prize!",
    "Outwork everyone — first to {target} {duty} takes the bag.",
    "{target} {duty}. Move fast. Stay sharp.",
]

_DESC_TEMPLATES_HIGH = [
    "Be the first to crush {target} {duty} — glory awaits!",
    "Master the art of {duty} — hit {target} before anyone else!",
    "Push the limits — first to {target} {duty} takes it all!",
    "Legends only: {target} {duty}. First to finish writes history.",
    "No mercy. No second place. First to {target} {duty} wins.",
]


def _make_challenge_description(duty: str, target: int, difficulty: int) -> str:
    """Pick an exciting challenge description from a difficulty-scaled template pool."""
    duty_label = DUTY_LABEL.get(duty, duty.capitalize())
    if difficulty <= 3:
        pool = _DESC_TEMPLATES_LOW
    elif difficulty <= 7:
        pool = _DESC_TEMPLATES_MID
    else:
        pool = _DESC_TEMPLATES_HIGH
    return random.choice(pool).format(target=target, duty=duty_label)


def _pick_challenge(duty: str, difficulty: int | None = None) -> dict:
    """Build a challenge dict: roll difficulty 1–10, look up target from stats table."""
    if difficulty is None:
        difficulty = random.randint(1, 10)
    else:
        difficulty = max(1, min(10, int(difficulty)))
    target = target_for_difficulty(duty, difficulty)
    return {'duty': duty, 'target': target, 'difficulty': difficulty}


def _mode_description(duty: str, target: int, difficulty: int, mode: str, params: dict) -> str:
    """Human challenge blurb for a completion mode."""
    duty_label = DUTY_LABEL.get(duty, duty.capitalize())
    if mode == 'engagement_combo':
        th = params.get('threshold', 85)
        return f"First to Engagement Rank {th}+ wins!"
    if mode == 'active_week':
        return f"Hit {target} {duty_label} across {params.get('min_days', 5)}+ active days!"
    if mode == 'weekend_warrior':
        return f"Hit {target} {duty_label} with activity on Saturday AND Sunday!"
    if mode == 'balanced_staff':
        targets = params.get('targets', {})
        parts = [f"{DUTY_LABEL.get(d, d)} {v}" for d, v in targets.items()]
        return f"First to hit ALL bars: {' AND '.join(parts)}!"
    if mode == 'proof_pipeline':
        return (
            f"Complete {params.get('target', target)} reviews across "
            f"{params.get('min_days', 4)}+ distinct days!"
        )
    if mode == 'beat_last_week':
        return f"Beat your personal target — outdo last week on {duty_label}!"
    if mode == 'catchup_bracket':
        return f"Bottom-half bracket: first +{params.get('delta', 25)} {duty_label} wins!"
    if mode == 'underdog_24h':
        return f"Underdogs only — most {duty_label} in 24h wins!"
    if mode == 'closest_without_bust':
        return f"Closest to {target} {duty_label} without going over — resolved at week end!"
    if mode == 'route_runner':
        return (
            f"Complete {params.get('routes_target', 2)} routes AND "
            f"{params.get('modlog_target', 30)} modlog actions!"
        )
    if mode == 'power_hour_overlap':
        return f"First to {target} {duty_label} during an active Power Hour!"
    if mode == 'tiered_podium':
        return f"Tiered podium — multiple winners at different thresholds!"
    if mode == 'seasonal_scramble':
        label = params.get('label', 'Season')
        return f"{label} scramble — {params.get('multiplier', 1.25)}× progress on {duty_label}!"
    return _make_challenge_description(duty, target, difficulty)


def _mode_params_for(duty: str, mode: str, difficulty: int) -> dict:
    """Build mode_params for a (duty, mode) pair at generation time."""
    d = difficulty
    if mode == 'engagement_combo':
        return {'threshold': max(75, min(95, 70 + d * 2))}
    if mode == 'active_week':
        return {'min_days': 5}
    if mode == 'balanced_staff':
        return {
            'duties': ['modlog', 'reviews'],
            'targets': {
                'modlog': max(8, d * 5),
                'reviews': max(4, d * 2),
            },
        }
    if mode == 'proof_pipeline':
        return {
            'target': target_for_difficulty('reviews', d),
            'min_days': min(6, max(3, d // 2 + 1)),
        }
    if mode == 'catchup_bracket':
        return {'delta': max(15, d * 2)}
    if mode == 'route_runner':
        if duty == 'routes':
            return {
                'routes_target': max(2, d // 3),
                'modlog_target': max(20, d * 4),
                'route_type': 'combined',
            }
        return {'routes_target': 2, 'modlog_target': 30, 'route_type': 'loot'}
    return {}


class _PickCtx:
    __slots__ = (
        'picked_modes', 'picked_pairs', 'last_week_modes', 'monday_pairs',
        'route_makers', 'ph_ok', 'season',
    )

    def __init__(
        self,
        picked_modes: set[str] | None = None,
        picked_pairs: set[tuple[str, str]] | None = None,
        last_week_modes: set[str] | None = None,
        monday_pairs: set[tuple[str, str]] | None = None,
        route_makers: int = 0,
        ph_ok: bool = True,
        season: bool = False,
    ):
        self.picked_modes = picked_modes or set()
        self.picked_pairs = picked_pairs or set()
        self.last_week_modes = last_week_modes or set()
        self.monday_pairs = monday_pairs or set()
        self.route_makers = route_makers
        self.ph_ok = ph_ok
        self.season = season


async def _build_pick_context(week_start: str) -> _PickCtx:
    prior = _prior_week_start(week_start) if week_start else ''
    last_modes = await _get_week_modes(prior) if prior else set()
    return _PickCtx(
        last_week_modes=last_modes,
        route_makers=await _count_active_route_makers(),
        ph_ok=await _ph_fired_last_week(),
        season=_season_active(),
    )


def _never_pair_blocks(mode: str, duty: str, ctx: _PickCtx) -> bool:
    if mode in ctx.picked_modes:
        return True
    if mode in ctx.last_week_modes:
        return True
    if (duty, mode) in ctx.monday_pairs:
        return True
    if mode in BRACKET_MODES and ctx.picked_modes & BRACKET_MODES:
        return True
    if mode in H24_MODES and ctx.picked_modes & H24_MODES:
        return True
    if mode in MULTI_DUTY_MODES and ctx.picked_modes & MULTI_DUTY_MODES:
        return True
    if mode in SLOW_BURN_MODES and ctx.picked_modes & SLOW_BURN_MODES:
        return True
    if mode == 'seasonal_scramble' and not ctx.season:
        return True
    if mode == 'power_hour_overlap' and not ctx.ph_ok:
        return True
    if mode == 'route_runner' and duty == 'routes' and ctx.route_makers < 2:
        return True
    return False


def _deck_candidates(
    duty: str,
    ctx: _PickCtx,
    require: frozenset[str] | None = None,
    ignore_last_week: bool = False,
) -> list[tuple[str, int]]:
    allowed = DUTY_ALLOWED_MODES.get(duty, frozenset())
    saved_last = ctx.last_week_modes
    if ignore_last_week:
        ctx.last_week_modes = set()
    out: list[tuple[str, int]] = []
    for mode in allowed:
        if require and mode not in require:
            continue
        if _never_pair_blocks(mode, duty, ctx):
            continue
        w = _MODE_TIER_WEIGHT.get(mode, 10)
        if w > 0:
            out.append((mode, w))
    ctx.last_week_modes = saved_last
    return out


def _weighted_pick_mode(candidates: list[tuple[str, int]]) -> str | None:
    total = sum(w for _, w in candidates)
    if total <= 0:
        return None
    roll = random.uniform(0, total)
    upto = 0.0
    for mode, w in candidates:
        upto += w
        if roll <= upto:
            return mode
    return candidates[-1][0]


def _pick_mode_for_duty(
    duty: str,
    ctx: _PickCtx,
    require: frozenset[str] | None = None,
) -> str:
    for ignore_last in (False, True):
        candidates = _deck_candidates(duty, ctx, require=require, ignore_last_week=ignore_last)
        mode = _weighted_pick_mode(candidates)
        if mode:
            return mode
    allowed = DUTY_ALLOWED_MODES.get(duty, frozenset())
    if 'first_to_target' in allowed and not _never_pair_blocks('first_to_target', duty, ctx):
        return 'first_to_target'
    for mode in sorted(allowed, key=lambda m: -_MODE_TIER_WEIGHT.get(m, 0)):
        if not _never_pair_blocks(mode, duty, ctx):
            return mode
    return 'first_to_target'


def _register_pick(ctx: _PickCtx, duty: str, mode: str) -> None:
    ctx.picked_modes.add(mode)
    ctx.picked_pairs.add((duty, mode))


def _finalize_challenge(ch: dict, duty: str, mode: str, params: dict) -> dict:
    ch['completion_mode'] = mode
    ch['mode_params'] = params
    if mode == 'proof_pipeline':
        ch['target'] = int(params.get('target', ch['target']))
    ch['ai_description'] = _mode_description(
        duty, ch['target'], ch['difficulty'], mode, params,
    )
    return ch


async def generate_week_start_challenges(
    bot=None,
    week_start_str: str | None = None,
) -> list[dict]:
    """Returns 5 challenges — one per duty, deck-weighted mode pick."""
    if not week_start_str:
        week_start_str = await _get_week_start()
    ctx = await _build_pick_context(week_start_str or '')
    challenges = []
    for duty in CHALLENGE_DUTIES:
        ch = _pick_challenge(duty)
        mode = _pick_mode_for_duty(duty, ctx)
        params = _mode_params_for(duty, mode, ch['difficulty'])
        _register_pick(ctx, duty, mode)
        challenges.append(_finalize_challenge(ch, duty, mode, params))
    return challenges


async def generate_midweek_challenges(
    bot=None,
    week_start_str: str | None = None,
) -> list[dict]:
    """Returns 3 difficulty-10 challenges: bracket + race + wild card."""
    if not week_start_str:
        week_start_str = await _get_week_start()
    ctx = await _build_pick_context(week_start_str or '')
    if week_start_str:
        ctx.monday_pairs = await _get_week_duty_mode_pairs(week_start_str, 'week_start')
    duties = random.sample(list(CHALLENGE_DUTIES), k=MIDWEEK_COUNT)
    slot_requires: list[frozenset[str] | None] = [
        BRACKET_MODES,
        RACE_MODES,
        None,
    ]
    challenges = []
    for duty, require in zip(duties, slot_requires):
        ch = _pick_challenge(duty, difficulty=MIDWEEK_DIFFICULTY)
        mode = _pick_mode_for_duty(duty, ctx, require=require)
        params = _mode_params_for(duty, mode, ch['difficulty'])
        _register_pick(ctx, duty, mode)
        challenges.append(_finalize_challenge(ch, duty, mode, params))
    return challenges

# ---------------------------------------------------------------------------
# Announcement helpers
# ---------------------------------------------------------------------------

def _challenge_field(ch: dict, progress_line: str | None = None) -> tuple[str, str]:
    """Return (name, value) strings for an embed field describing a challenge."""
    emoji      = DUTY_EMOJI.get(ch['duty'], '🎯')
    duty_label = DUTY_LABEL.get(ch['duty'], ch['duty'].capitalize())
    role_label = DUTY_ROLE_LABEL.get(ch['duty'], 'Staff')
    mode       = ch.get('completion_mode', 'first_to_target')
    mode_label = COMPLETION_MODE_LABEL.get(mode, mode)
    target     = ch.get('target', ch.get('target_count', 0))
    name  = f"{emoji} {duty_label} Challenge"

    ai_desc = ch.get('ai_description', f"First to reach {target} {duty_label}")

    value = (
        f"**{ai_desc}**\n"
        f"**Target:** {target} {duty_label}\n"
        f"⚡ Difficulty: `{ch['difficulty']}/10`\n"
        f"🎮 Mode: {mode_label}\n"
        f"👥 Eligible: *{role_label}*\n"
        f"💎 Reward: **{challenge_wp_reward(ch['difficulty'])} Wave Points**"
    )
    if progress_line:
        value += f"\n📊 **Progress:** {progress_line}"
    if ch.get('expired'):
        value += "\n⛔ **No winner this week**"
    return name, value


async def _get_announcement_channel(bot) -> discord.TextChannel | None:
    channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
    if not channel:
        logger.error(f"❌ Announcement channel {ANNOUNCEMENT_CHANNEL_ID} not found")
    return channel


async def announce_week_start(bot, challenges: list[dict], week_start: str):
    channel = await _get_announcement_channel(bot)
    if not channel:
        return

    embed = discord.Embed(
        title="🔥 WEEKLY CHALLENGES UNLEASHED! 🔥",
        description=(
            "FIVE challenges just dropped! 💎\n"
            "Be the **FIRST** to dominate and claim your **Wave Points**!\n\n"
            f"📅 Week: `{week_start}`"
        ),
        color=discord.Color.gold()
    )
    for i, ch in enumerate(challenges, 1):
        name, value = _challenge_field(ch)
        embed.add_field(name=f"⚡ Challenge {i} — {name}", value=value, inline=False)
    embed.set_footer(text="🏆 Race to victory! Checked every hour")
    
    # Check if message already exists from a previous bot run
    existing_msg_id = await get_announcement_message_id(week_start, 'week_start')
    
    try:
        if existing_msg_id:
            # Edit existing message
            existing_msg = await channel.fetch_message(existing_msg_id)
            await existing_msg.edit(embed=embed)
            logger.info("✅ Week-start challenge message updated (edited existing)")
        else:
            # Post new message
            msg = await channel.send("👻 @everyone — **NEW CHALLENGES LIVE!** 🚀🔥", embed=embed)
            await save_announcement_message_id(week_start, 'week_start', msg.id)
            logger.info("✅ Week-start challenges announced (new message)")
    except discord.NotFound:
        # Message was deleted, post new one
        msg = await channel.send("👻 @everyone — **NEW CHALLENGES LIVE!** 🚀🔥", embed=embed)
        await save_announcement_message_id(week_start, 'week_start', msg.id)
        logger.info("✅ Week-start challenges announced (previous message was deleted, posted new)")


async def announce_midweek(bot, challenges: list[dict], week_start: str):
    channel = await _get_announcement_channel(bot)
    if not channel:
        return

    embed = discord.Embed(
        title="🌪️ MID-WEEK MAYHEM — DIFFICULTY 10! 🌪️",
        description=(
            "THREE brutal challenges just dropped mid-week! 🔥\n"
            "This is YOUR chance to prove yourself. **WIN BIG!** 💎\n\n"
            f"📅 Week: `{week_start}`"
        ),
        color=discord.Color.red()
    )
    for i, ch in enumerate(challenges, 1):
        name, value = _challenge_field(ch)
        embed.add_field(name=f"🎯 Mayhem {i} — {name}", value=value, inline=False)
    embed.set_footer(text="🏆 Only the STRONGEST will prevail! Checked every hour")
    
    # Check if message already exists from a previous bot run
    existing_msg_id = await get_announcement_message_id(week_start, 'mid_week')
    
    try:
        if existing_msg_id:
            # Edit existing message
            existing_msg = await channel.fetch_message(existing_msg_id)
            await existing_msg.edit(embed=embed)
            logger.info("✅ Mid-week challenge message updated (edited existing)")
        else:
            # Post new message
            msg = await channel.send("👻 @everyone — **MAYHEM CHALLENGE LIVE!** ⚡🔥", embed=embed)
            await save_announcement_message_id(week_start, 'mid_week', msg.id)
            logger.info("✅ Mid-week challenge announced (new message)")
    except discord.NotFound:
        # Message was deleted, post new one
        msg = await channel.send("👻 @everyone — **MAYHEM CHALLENGE LIVE!** ⚡🔥", embed=embed)
        await save_announcement_message_id(week_start, 'mid_week', msg.id)
        logger.info("✅ Mid-week challenge announced (previous message was deleted, posted new)")


async def delete_challenge_message(bot, challenge_id: int):
    """Delete the announcement message for a completed challenge."""
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT message_id FROM weekly_challenges WHERE id = ?',
                (challenge_id,)
            ) as cur:
                row = await cur.fetchone()
        
        if not row or not row[0]:
            logger.debug(f"  ℹ️ No message ID stored for challenge {challenge_id}")
            return
        
        message_id = row[0]
        channel = await _get_announcement_channel(bot)
        if not channel:
            logger.warning(f"  ⚠️ Could not get announcement channel to delete message {message_id}")
            return
        
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
            logger.info(f"  🗑️ Deleted challenge announcement message {message_id}")
        except discord.NotFound:
            logger.warning(f"  ⚠️ Message {message_id} not found (already deleted?)")
        except Exception as e:
            logger.error(f"  ❌ Failed to delete message {message_id}: {e}")
    
    except Exception as e:
        logger.error(f"  ❌ delete_challenge_message error: {e}")


async def announce_winner(bot, user_id: int, challenge: dict):
    """Announce winner in channel and send them a personal DM."""
    channel = await _get_announcement_channel(bot)
    if not channel:
        return

    duty_label = DUTY_LABEL.get(challenge['duty'], challenge['duty'].capitalize())
    try:
        user    = await bot.fetch_user(user_id)
        mention = user.mention
    except Exception:
        mention = f"<@{user_id}>"

    # Public announcement in channel
    embed = discord.Embed(
        title="🏆 CHALLENGE CONQUERED! 🏆",
        description=(
            f"🎯 {mention} **DOMINATED** the\n"
            f"**{duty_label} ×{challenge['target']}** challenge!\n\n"
            f"💎 **+{challenge_wp_reward(challenge['difficulty'])} WAVE POINTS** UNLOCKED! 🔥"
        ),
        color=discord.Color.gold()
    )
    await channel.send(embed=embed)
    logger.info(f"🏆 Winner announced: user={user_id} duty={challenge['duty']} target={challenge['target']}")
    
    # Send DM to winner
    try:
        user = await bot.fetch_user(user_id)
        dm_embed = discord.Embed(
            title="🏆 CONGRATULATIONS! 🏆",
            description=(
                f"🎉 You **DOMINATED** the **{duty_label} ×{challenge['target']}** challenge!\n\n"
                f"💎 **+{challenge_wp_reward(challenge['difficulty'])} WAVE POINTS** added to your account! 🌟"
            ),
            color=discord.Color.gold()
        )
        dm_embed.set_footer(text="Keep crushing it! 🔥")
        await user.send(embed=dm_embed)
        logger.info(f"✉️ DM sent to winner {user_id}")
    except Exception as e:
        logger.warning(f"⚠️ Could not send DM to winner {user_id}: {e}")

# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

async def _get_week_start() -> str | None:
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        return config.get('global_dates', {}).get('start_date')
    except Exception as e:
        logger.error(f"❌ Could not read config.json: {e}")
        return None

# ---------------------------------------------------------------------------
# Completion checking — called hourly by unified_weekly_loop
# ---------------------------------------------------------------------------

def _compute_deltas(duty_counts: dict, baselines: dict[int, int]) -> dict[int, int]:
    """Current count minus baseline per user (only users present in duty_counts)."""
    deltas: dict[int, int] = {}
    for uid, raw in duty_counts.items():
        try:
            uid_i = int(uid)
        except (TypeError, ValueError):
            continue
        current = get_count_value(raw)
        base = baselines.get(uid_i, 0)
        deltas[uid_i] = max(0, current - base)
    return deltas


def _top_delta_lines(deltas: dict[int, int], limit: int = 3) -> str:
    """Format top-N delta counts for embed progress display."""
    if not deltas:
        return 'No activity yet'
    ranked = sorted(deltas.items(), key=lambda x: x[1], reverse=True)[:limit]
    parts = [f"<@{uid}> +{cnt}" for uid, cnt in ranked if cnt > 0]
    return ' · '.join(parts) if parts else 'No progress yet'


def _pick_winner_from_deltas(
    deltas: dict[int, int],
    target: int,
    mode: str,
    announced_at: str | None,
) -> int | None:
    """Select a winner based on completion mode and delta counts."""
    if not deltas:
        return None

    now = datetime.now(timezone.utc)
    if mode == 'most_in_24h':
        if not announced_at:
            return None
        try:
            announced_dt = datetime.fromisoformat(announced_at)
            if announced_dt.tzinfo is None:
                announced_dt = announced_dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
        if now < announced_dt + timedelta(hours=24):
            return None
        max_delta = max(deltas.values())
        if max_delta <= 0:
            return None
        tied = [uid for uid, d in deltas.items() if d == max_delta]
        return random.choice(tied)

    # first_to_target: among users meeting target, highest delta wins (random tie)
    qualified = [(uid, d) for uid, d in deltas.items() if d >= target]
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _delta_winner_for_challenge(ch: dict, all_stats: dict, mode: str) -> int | None:
    """Shared delta-from-baseline path for duty-count challenge modes."""
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    duty_counts = all_stats.get(duty, {})
    if not duty_counts:
        return None
    deltas = _compute_deltas(duty_counts, baselines)
    return _pick_winner_from_deltas(
        deltas, ch['target_count'], mode, ch.get('announced_at'),
    )


def _check_first_to_target(ch: dict, all_stats: dict) -> int | None:
    return _delta_winner_for_challenge(ch, all_stats, 'first_to_target')


def _check_most_in_24h(ch: dict, all_stats: dict) -> int | None:
    return _delta_winner_for_challenge(ch, all_stats, 'most_in_24h')


def _check_consistency_gate(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    min_days = int(params.get('min_days', 6))
    required = min(min_days, _days_elapsed_in_week())
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    target = ch['target_count']
    qualified: list[tuple[int, int]] = []
    for uid, delta in deltas.items():
        if delta < target:
            continue
        active_days = _message_active_days_count(uid, all_stats) if duty == 'message' else _message_active_days_count(uid, all_stats)
        if active_days >= required:
            qualified.append((uid, delta))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_engagement_combo(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    threshold = int(params.get('threshold', 85))
    qualified = [
        (uid, compute_rank_total(uid, all_stats))
        for uid in _all_uids_in_stats(all_stats)
        if compute_rank_total(uid, all_stats) >= threshold
    ]
    if not qualified:
        return None
    max_rank = max(rt for _, rt in qualified)
    tied = [uid for uid, rt in qualified if rt == max_rank]
    return random.choice(tied)


def _check_balanced_staff(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    duties = params.get('duties', ['modlog', 'reviews'])
    targets = params.get('targets', {})
    multi_bl = params.get('baselines', {})
    qualified: list[tuple[int, int]] = []
    for uid in _all_uids_in_stats(all_stats):
        passes = True
        min_delta = 0
        for d in duties:
            bl_raw = multi_bl.get(d, {})
            baselines = {int(k): int(v) for k, v in bl_raw.items()}
            deltas = _compute_deltas(all_stats.get(d, {}), baselines)
            delta = deltas.get(uid, 0)
            need = int(targets.get(d, 0))
            if delta < need:
                passes = False
                break
            min_delta = max(min_delta, delta)
        if passes:
            qualified.append((uid, min_delta))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_weekend_warrior(ch: dict, all_stats: dict) -> int | None:
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    target = ch['target_count']
    qualified: list[tuple[int, int]] = []
    for uid, delta in deltas.items():
        if delta < target:
            continue
        wds = _message_weekdays(uid, all_stats)
        if 5 in wds and 6 in wds:
            qualified.append((uid, delta))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_catchup_bracket(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    eligible = {int(u) for u in params.get('eligible_uids', [])}
    delta_needed = int(params.get('delta', 25))
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    qualified = [(uid, d) for uid, d in deltas.items() if uid in eligible and d >= delta_needed]
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_tiered_podium(ch: dict, all_stats: dict) -> int | None:
    """Handled in check_and_complete_challenges — stub returns None."""
    return None


def _hours_since_week_start() -> float:
    try:
        with open('config.json', 'r') as f:
            start = json.load(f).get('global_dates', {}).get('start_date')
        if not start:
            return 0.0
        week_start = datetime.strptime(start, '%d/%m/%Y').replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - week_start).total_seconds() / 3600
    except Exception:
        return 0.0


def _check_closest_without_bust(ch: dict, all_stats: dict, *, force_week_end: bool = False) -> int | None:
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    target = ch['target_count']
    under = {uid: d for uid, d in deltas.items() if d <= target}
    if not force_week_end:
        exact = [uid for uid, d in under.items() if d == target]
        if exact:
            return random.choice(exact)
        return None
    if not under:
        return None
    closest = max(under.values())
    tied = [uid for uid, d in under.items() if d == closest]
    return random.choice(tied)


def _check_route_runner(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    routes_target = int(params.get('routes_target', 2))
    modlog_target = int(params.get('modlog_target', 30))
    route_type = params.get('route_type', 'loot')
    if ch.get('duty') == 'routes':
        route_type = 'combined'
    route_counts = all_stats.get('_route_counts', {}).get(route_type, {})
    modlog_bl = params.get('modlog_baselines', {})
    if modlog_bl:
        baselines = {int(k): int(v) for k, v in modlog_bl.items()}
    else:
        baselines = _parse_baselines(ch.get('baselines'))
    modlog_deltas = _compute_deltas(all_stats.get('modlog', {}), baselines)
    qualified: list[tuple[int, int]] = []
    for uid, routes in route_counts.items():
        uid = int(uid)
        if routes < routes_target:
            continue
        if modlog_deltas.get(uid, 0) < modlog_target:
            continue
        qualified.append((uid, modlog_deltas.get(uid, 0)))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


async def _check_power_hour_overlap(ch: dict, all_stats: dict) -> int | None:
    if not all_stats.get('_ph_active'):
        return None
    params = _parse_mode_params(ch.get('mode_params'))
    duty = ch['duty']
    duty_counts = all_stats.get(duty, {})
    if params.get('ph_baseline') is None:
        params['ph_baseline'] = {
            str(uid): get_count_value(raw) for uid, raw in duty_counts.items()
        }
        await update_mode_params(ch['id'], params)
        return None
    ph_bl = {int(k): int(v) for k, v in params.get('ph_baseline', {}).items()}
    deltas: dict[int, int] = {}
    for uid, raw in duty_counts.items():
        try:
            uid_i = int(uid)
        except (TypeError, ValueError):
            continue
        deltas[uid_i] = max(0, get_count_value(raw) - ph_bl.get(uid_i, 0))
    qualified = [(uid, d) for uid, d in deltas.items() if d >= ch['target_count']]
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_proof_pipeline(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    target = int(params.get('target', ch['target_count']))
    min_days = int(params.get('min_days', 4))
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get('reviews', {}), baselines)
    qualified: list[tuple[int, int]] = []
    for uid, delta in deltas.items():
        if delta < target:
            continue
        _, unique_days = _review_stats(uid, all_stats)
        if unique_days >= min_days:
            qualified.append((uid, delta))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_underdog_24h(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    eligible = {int(u) for u in params.get('eligible_uids', [])}
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    if not eligible:
        return _pick_winner_from_deltas(deltas, ch['target_count'], 'most_in_24h', ch.get('announced_at'))
    filtered = {uid: d for uid, d in deltas.items() if uid in eligible}
    return _pick_winner_from_deltas(filtered, ch['target_count'], 'most_in_24h', ch.get('announced_at'))


def _check_beat_last_week(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    personal = params.get('personal_targets', {})
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    qualified: list[tuple[int, int]] = []
    for uid, delta in deltas.items():
        pt = personal.get(str(uid), personal.get(uid, ch['target_count']))
        try:
            need = int(pt)
        except (TypeError, ValueError):
            need = ch['target_count']
        if delta >= need:
            qualified.append((uid, delta))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_active_week(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    min_days = int(params.get('min_days', 5))
    duty = ch['duty']
    baselines = _parse_baselines(ch.get('baselines'))
    deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
    target = ch['target_count']
    qualified: list[tuple[int, int]] = []
    for uid, delta in deltas.items():
        if delta < target:
            continue
        if _message_active_days_count(uid, all_stats) >= min_days:
            qualified.append((uid, delta))
    if not qualified:
        return None
    max_delta = max(d for _, d in qualified)
    tied = [uid for uid, d in qualified if d == max_delta]
    return random.choice(tied)


def _check_seasonal_scramble(ch: dict, all_stats: dict) -> int | None:
    params = _parse_mode_params(ch.get('mode_params'))
    duty = params.get('duty', ch['duty'])
    baselines = _parse_baselines(ch.get('baselines'))
    multiplier = float(params.get('multiplier', 1.25))
    scaled: dict[int, int] = {}
    for uid, raw in all_stats.get(duty, {}).items():
        uid_i = int(uid)
        current = get_count_value(raw)
        base = baselines.get(uid_i, 0)
        scaled[uid_i] = int(max(0, current - base) * multiplier)
    return _pick_winner_from_deltas(scaled, ch['target_count'], 'first_to_target', ch.get('announced_at'))


COMPLETION_MODE_CHECKERS = {
    'first_to_target': _check_first_to_target,
    'most_in_24h': _check_most_in_24h,
    'consistency_gate': _check_consistency_gate,
    'engagement_combo': _check_engagement_combo,
    'balanced_staff': _check_balanced_staff,
    'weekend_warrior': _check_weekend_warrior,
    'catchup_bracket': _check_catchup_bracket,
    'tiered_podium': _check_tiered_podium,
    'closest_without_bust': _check_closest_without_bust,
    'route_runner': _check_route_runner,
    'power_hour_overlap': _check_power_hour_overlap,
    'proof_pipeline': _check_proof_pipeline,
    'underdog_24h': _check_underdog_24h,
    'beat_last_week': _check_beat_last_week,
    'active_week': _check_active_week,
    'seasonal_scramble': _check_seasonal_scramble,
}


async def _update_live_progress(bot, week_start: str, phase: str, rows: list[dict],
                                all_stats: dict):
    """Edit the phase announcement embed with top-3 deltas (debounced)."""
    msg_id = await get_announcement_message_id(week_start, phase)
    if not msg_id:
        return

    progress_payload = []
    embed_challenges = []
    for ch in rows:
        if ch.get('completed_by_user') or ch.get('expired_at'):
            embed_challenges.append(ch)
            continue
        duty = ch['duty']
        baselines = _parse_baselines(ch.get('baselines'))
        deltas = _compute_deltas(all_stats.get(duty, {}), baselines)
        top3 = sorted(deltas.items(), key=lambda x: x[1], reverse=True)[:3]
        progress_payload.append((ch['id'], duty, top3))
        ch_copy = dict(ch)
        ch_copy['target'] = ch['target_count']
        ch_copy['ai_description'] = ch.get('description') or _deterministic_description(
            ch['id'], duty, ch['target_count'], ch['difficulty']
        )
        ch_copy['progress_line'] = _top_delta_lines(deltas)
        embed_challenges.append(ch_copy)

    fingerprint = json.dumps(progress_payload, sort_keys=True)
    phase_key = f"{week_start}:{phase}"
    if _last_progress_snapshot.get(phase_key) == fingerprint:
        return
    _last_progress_snapshot[phase_key] = fingerprint

    channel = await _get_announcement_channel(bot)
    if not channel:
        return

    if phase == 'week_start':
        title = "🔥 WEEKLY CHALLENGES UNLEASHED! 🔥"
        desc = (
            "FIVE challenges just dropped! 💎\n"
            "Be the **FIRST** to dominate and claim your **Wave Points**!\n\n"
            f"📅 Week: `{week_start}`"
        )
        color = discord.Color.gold()
        footer = "🏆 Race to victory! Checked every hour"
        prefix = "⚡ Challenge"
    else:
        title = "🌪️ MID-WEEK MAYHEM — DIFFICULTY 10! 🌪️"
        desc = (
            "THREE brutal challenges just dropped mid-week! 🔥\n"
            "This is YOUR chance to prove yourself. **WIN BIG!** 💎\n\n"
            f"📅 Week: `{week_start}`"
        )
        color = discord.Color.red()
        footer = "🏆 Only the STRONGEST will prevail! Checked every hour"
        prefix = "🎯 Mayhem"

    embed = discord.Embed(title=title, description=desc, color=color)
    for i, ch in enumerate(embed_challenges, 1):
        name, value = _challenge_field(
            {
                'duty': ch['duty'],
                'target': ch.get('target', ch.get('target_count', 0)),
                'difficulty': ch['difficulty'],
                'completion_mode': ch.get('completion_mode', 'first_to_target'),
                'ai_description': ch.get('ai_description'),
                'expired': bool(ch.get('expired_at')),
            },
            progress_line=ch.get('progress_line'),
        )
        embed.add_field(name=f"{prefix} {i} — {name}", value=value, inline=False)
    embed.set_footer(text=footer)

    try:
        msg = await channel.fetch_message(msg_id)
        await msg.edit(embed=embed)
        logger.debug(f"📊 Live progress updated for {phase} challenges")
    except discord.NotFound:
        logger.debug(f"📊 Progress update skipped — {phase} message {msg_id} not found")
    except Exception as e:
        logger.warning(f"⚠️ Live progress edit failed for {phase}: {e}")


async def check_and_complete_challenges(bot, all_stats: dict):
    """
    Called hourly by unified_weekly_loop with the current all_stats dict.
    Winners are based on delta from baseline snapshot at announce time.
    """
    if not all_stats:
        return

    try:
        week_start = await _get_week_start()
        if not week_start:
            logger.warning("⚠️ check_and_complete_challenges: no start_date in config")
            return

        all_stats = await _enrich_all_stats_for_modes(all_stats)

        raw_rows = await get_all_active_challenges(week_start)
        if not raw_rows:
            logger.debug("check_and_complete_challenges: no active challenges this week")
            return

        rows = [_challenge_row_dict(r) for r in raw_rows]
        logger.info(f"🔍 Checking {len(rows)} challenge(s) for completion…")

        by_phase: dict[str, list[dict]] = {}
        for ch in rows:
            by_phase.setdefault(ch['challenge_type'], []).append(ch)

        for phase, phase_rows in by_phase.items():
            await _update_live_progress(bot, week_start, phase, phase_rows, all_stats)

        for ch in rows:
            if ch.get('completed_by_user') or ch.get('expired_at'):
                continue

            cid = ch['id']
            duty = ch['duty']
            target = ch['target_count']
            difficulty = ch['difficulty']
            mode = ch.get('completion_mode') or 'first_to_target'

            if mode == 'tiered_podium':
                await _process_tiered_podium(bot, ch, all_stats)
                continue

            if mode == 'power_hour_overlap':
                winner_id = await _check_power_hour_overlap(ch, all_stats)
            elif mode == 'closest_without_bust':
                winner_id = _check_closest_without_bust(ch, all_stats)
                if winner_id is None and _hours_since_week_start() >= 168:
                    winner_id = _check_closest_without_bust(ch, all_stats, force_week_end=True)
            else:
                checker = COMPLETION_MODE_CHECKERS.get(mode)
                if checker is None:
                    logger.warning(f"  Challenge {cid}: unknown completion mode {mode!r} — skipping")
                    continue
                winner_id = checker(ch, all_stats)

            if winner_id is None:
                logger.debug(f"  Challenge {cid} ({duty} ×{target}, {mode}): no winner yet")
                continue

            await _award_challenge_winner(bot, ch, winner_id)

    except Exception as e:
        logger.error(f"❌ check_and_complete_challenges error: {e}", exc_info=True)

# ---------------------------------------------------------------------------
# Background scheduler — fires challenges on time, once per phase per week
# ---------------------------------------------------------------------------

def _load_schedule_config() -> tuple[str | None, int]:
    """
    Read config.json and return (week_start_str, half_week_hours).
    Returns (None, 72) on any error.
    """
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f)
        week_start_str   = cfg.get('global_dates', {}).get('start_date')
        half_week_hours  = (
            cfg.get('automated_checks', {})
               .get('schedule', {})
               .get('half_week_hours', 72)
        )
        return week_start_str, half_week_hours
    except Exception as e:
        logger.error(f"❌ Could not read config.json: {e}")
        return None, 72


async def challenge_scheduler(bot):
    """
    Precision scheduler — sleeps until the exact moment each phase is due.

    Logic per loop iteration:
      1. Read week_start + half_week_hours from config.
      2. Compute week_start_dt and midweek_dt.
      3. If week_start phase hasn't fired yet AND we haven't reached week_start_dt yet,
         sleep until week_start_dt then fire week-start challenges.
      4. If mid-week phase hasn't fired yet AND we haven't reached midweek_dt yet,
         sleep until midweek_dt then fire mid-week challenge.
      5. If both phases already fired for this week, sleep 1 hour and re-check
         (catches week rollover without busy-looping).

    The DB row existence check is the fire-once guard — even if the bot restarts
    mid-sleep the check prevents double-firing.
    """
    await bot.wait_until_ready()
    logger.info("✅ Weekly challenge scheduler started")

    # On startup: fire any missed phases immediately (bot was offline)
    await _fire_due_challenges(bot)

    while True:
        try:
            week_start_str, half_week_hours = _load_schedule_config()
            if not week_start_str:
                logger.warning("⚠️ No start_date in config — retrying in 60s")
                await asyncio.sleep(60)
                continue

            week_start_dt = datetime.strptime(week_start_str, "%d/%m/%Y").replace(tzinfo=timezone.utc)
            midweek_dt    = week_start_dt + timedelta(hours=half_week_hours)
            now           = datetime.now(timezone.utc)

            week_start_done = bool(await get_challenges_for_phase(week_start_str, 'week_start'))
            midweek_done    = bool(await get_challenges_for_phase(week_start_str, 'mid_week'))

            # ── Case 1: week-start phase not yet fired and not yet due ──────────
            if not week_start_done and now < week_start_dt:
                wait = (week_start_dt - now).total_seconds()
                logger.info(f"⏳ Sleeping {wait/3600:.2f}h until week-start challenges fire at {week_start_dt} UTC")
                interrupted = await _interruptible_sleep(wait)
                if interrupted:
                    continue  # dates changed — re-read config from top
                await _fire_week_start(bot, week_start_str)
                continue  # re-evaluate after firing

            # ── Case 2: mid-week phase not yet fired and not yet due ────────────
            if not midweek_done and now < midweek_dt:
                wait = (midweek_dt - now).total_seconds()
                logger.info(f"⏳ Sleeping {wait/3600:.2f}h until mid-week challenge fires at {midweek_dt} UTC")
                interrupted = await _interruptible_sleep(wait)
                if interrupted:
                    continue  # dates changed — re-read config from top
                await _fire_midweek(bot, week_start_str)
                continue  # re-evaluate after firing

            # ── Case 3: both phases done — sleep until exact week end then clean up ─
            week_end_dt = week_start_dt + timedelta(days=7)
            if now < week_end_dt:
                wait = (week_end_dt - now).total_seconds()
                logger.info(f"⏳ Sleeping {wait/3600:.2f}h until week ends at {week_end_dt} UTC — then cleaning up messages")
                interrupted = await _interruptible_sleep(wait)
                if interrupted:
                    continue  # dates changed — skip old-week cleanup, re-evaluate

            logger.info(f"🗑️ Week ended — cleaning up challenge messages for {week_start_str}")
            await delete_week_messages(bot, week_start_str)
            await delete_old_challenge_rows(week_start_str)
            logger.info("💤 Cleanup done — waiting for new week in config.json")
            await _interruptible_sleep(3600)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"❌ Challenge scheduler error: {e}", exc_info=True)
            await _interruptible_sleep(60)


async def _fire_due_challenges(bot):
    """
    Startup catch-up: fire any phases that are already due but not yet in the DB.
    Called once on bot startup before the main precision loop begins.
    """
    try:
        week_start_str, half_week_hours = _load_schedule_config()
        if not week_start_str:
            return

        week_start_dt = datetime.strptime(week_start_str, "%d/%m/%Y").replace(tzinfo=timezone.utc)
        midweek_dt    = week_start_dt + timedelta(hours=half_week_hours)
        now           = datetime.now(timezone.utc)

        if now >= week_start_dt and not await get_challenges_for_phase(week_start_str, 'week_start'):
            logger.info("🎯 Startup catch-up: generating week-start challenges (missed while offline)…")
            await _fire_week_start(bot, week_start_str)

        if now >= midweek_dt and not await get_challenges_for_phase(week_start_str, 'mid_week'):
            logger.info("⚡ Startup catch-up: generating mid-week challenge (missed while offline)…")
            await _fire_midweek(bot, week_start_str)

    except Exception as e:
        logger.error(f"❌ Startup catch-up error: {e}", exc_info=True)


async def spin_week_start_challenges(
    bot,
    week_start_str: str,
    *,
    replace: bool = False,
) -> list | None:
    """
    Manually spin week-start challenges (deck pick + DB + Discord + website).
    Returns DB rows after fire, or None if rows already exist and replace=False.
    """
    if await get_challenges_for_phase(week_start_str, 'week_start'):
        if not replace:
            return None
        pool = await database.get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "DELETE FROM weekly_challenges WHERE week_start = ? AND challenge_type = 'week_start'",
                (week_start_str,),
            )
            await db.commit()
    await _fire_week_start(bot, week_start_str)
    return await get_challenges_for_phase(week_start_str, 'week_start')


async def _fire_week_start(bot, week_start_str: str):
    """Generate and announce week-start challenges (fire-once guard inside)."""
    if await get_challenges_for_phase(week_start_str, 'week_start'):
        logger.info("✅ Week-start challenges already exist — skipping")
        return
    try:
        logger.info("🎯 Generating week-start challenges…")
        challenges = await generate_week_start_challenges(bot, week_start_str)
        baselines_all = await snapshot_duty_baselines(bot)
        for ch in challenges:
            duty_baselines = baselines_all.get(ch['duty'], {})
            mode_params = await _enrich_mode_params_at_fire(ch, baselines_all, bot)
            ch['mode_params'] = mode_params
            await save_challenge(
                week_start_str, 'week_start',
                ch['duty'], ch['target'], ch['difficulty'],
                description=ch.get('ai_description'),
                baselines=json.dumps({str(k): v for k, v in duty_baselines.items()}),
                completion_mode=ch.get('completion_mode', 'first_to_target'),
                mode_params=json.dumps(mode_params),
                bot=bot,
            )
        await announce_week_start(bot, challenges, week_start_str)
        logger.info("✅ Week-start challenges fired")
    except Exception as e:
        logger.error(f"❌ _fire_week_start error: {e}", exc_info=True)


async def _fire_midweek(bot, week_start_str: str):
    """Generate and announce the mid-week challenge (fire-once guard inside)."""
    if await get_challenges_for_phase(week_start_str, 'mid_week'):
        logger.info("✅ Mid-week challenge already exists — skipping")
        return
    try:
        logger.info("⚡ Generating mid-week challenges…")
        challenges = await generate_midweek_challenges(bot, week_start_str)
        baselines_all = await snapshot_duty_baselines(bot)
        for ch in challenges:
            duty_baselines = baselines_all.get(ch['duty'], {})
            mode_params = await _enrich_mode_params_at_fire(ch, baselines_all, bot)
            if ch.get('completion_mode') == 'underdog_24h' and not mode_params.get('eligible_uids'):
                ch['completion_mode'] = 'most_in_24h'
                mode_params = {}
            ch['mode_params'] = mode_params
            await save_challenge(
                week_start_str, 'mid_week',
                ch['duty'], ch['target'], ch['difficulty'],
                description=ch.get('ai_description'),
                baselines=json.dumps({str(k): v for k, v in duty_baselines.items()}),
                completion_mode=ch.get('completion_mode', 'first_to_target'),
                mode_params=json.dumps(mode_params),
                bot=bot,
            )
        await announce_midweek(bot, challenges, week_start_str)
        logger.info("✅ Mid-week challenges fired")
    except Exception as e:
        logger.error(f"❌ _fire_midweek error: {e}", exc_info=True)


async def expire_unwon_challenges(bot, week_start_str: str):
    """Mark unwon challenges expired and update announcement embeds / post replies."""
    channel = await _get_announcement_channel(bot)
    if not channel:
        logger.warning("⚠️ expire_unwon_challenges: announcement channel not found")
        return

    for phase in ('week_start', 'mid_week'):
        raw_rows = await get_challenges_for_phase(week_start_str, phase)
        if not raw_rows:
            continue

        rows = [_challenge_row_dict(r) for r in raw_rows]
        unwon = [
            r for r in rows
            if not r.get('completed_by_user') and not r.get('expired_at')
        ]
        if not unwon:
            continue

        end_stats = await _enrich_all_stats_for_modes(await _build_current_all_stats(bot))
        still_unwon = []
        for ch in unwon:
            if ch.get('completion_mode') == 'closest_without_bust':
                winner_id = _check_closest_without_bust(ch, end_stats, force_week_end=True)
                if winner_id is not None:
                    await _award_challenge_winner(bot, ch, winner_id)
                    continue
            still_unwon.append(ch)
        unwon = still_unwon

        for ch in unwon:
            await mark_challenge_expired(ch['id'], bot=bot)

        msg_id = await get_announcement_message_id(week_start_str, phase)
        if msg_id:
            try:
                expired_rows = []
                for ch in rows:
                    ch_copy = dict(ch)
                    ch_copy['target'] = ch['target_count']
                    ch_copy['ai_description'] = ch.get('description') or _deterministic_description(
                        ch['id'], ch['duty'], ch['target_count'], ch['difficulty']
                    )
                    if not ch.get('completed_by_user'):
                        ch_copy['expired'] = True
                    expired_rows.append(ch_copy)

                if phase == 'week_start':
                    title = "🔥 WEEKLY CHALLENGES — WEEK ENDED 🔥"
                    desc = f"📅 Week: `{week_start_str}` — final status"
                    color = discord.Color.dark_grey()
                    footer = "Week complete"
                    prefix = "⚡ Challenge"
                else:
                    title = "🌪️ MID-WEEK MAYHEM — WEEK ENDED 🌪️"
                    desc = f"📅 Week: `{week_start_str}` — final status"
                    color = discord.Color.dark_grey()
                    footer = "Week complete"
                    prefix = "🎯 Mayhem"

                embed = discord.Embed(title=title, description=desc, color=color)
                for i, ch in enumerate(expired_rows, 1):
                    name, value = _challenge_field({
                        'duty': ch['duty'],
                        'target': ch['target'],
                        'difficulty': ch['difficulty'],
                        'completion_mode': ch.get('completion_mode', 'first_to_target'),
                        'ai_description': ch.get('ai_description'),
                        'expired': ch.get('expired', False),
                    })
                    embed.add_field(name=f"{prefix} {i} — {name}", value=value, inline=False)
                embed.set_footer(text=footer)

                msg = await channel.fetch_message(msg_id)
                await msg.edit(embed=embed)
                logger.info(f"  ✅ Updated {phase} embed with expired status")
            except discord.NotFound:
                logger.info(f"  ℹ️ {phase} message {msg_id} not found for expire edit")
            except Exception as e:
                logger.error(f"  ❌ Failed to edit {phase} embed on expire: {e}")

        for ch in unwon:
            duty_label = DUTY_LABEL.get(ch['duty'], ch['duty'].capitalize())
            try:
                await channel.send(
                    f"⛔ No winner this week for the **{duty_label}** challenge."
                )
            except Exception as e:
                logger.warning(f"  ⚠️ Could not post no-winner reply for challenge {ch['id']}: {e}")

    logger.info(f"✅ Expired unwon challenges for week {week_start_str}")


async def delete_week_messages(bot, week_start_str: str):
    """
    Expire unwon challenges, update embeds, then delete announcement messages.
    Called automatically 7 days after week_start.
    """
    try:
        await expire_unwon_challenges(bot, week_start_str)

        channel = await _get_announcement_channel(bot)
        if not channel:
            logger.warning("⚠️ delete_week_messages: announcement channel not found")
            return

        for phase in ('week_start', 'mid_week'):
            msg_id = await get_announcement_message_id(week_start_str, phase)
            if not msg_id:
                logger.info(f"  ℹ️ No message ID stored for {phase} — skipping")
                continue
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.delete()
                logger.info(f"  🗑️ Deleted {phase} challenge message (ID {msg_id}) for week {week_start_str}")
            except discord.NotFound:
                logger.info(f"  ℹ️ {phase} message {msg_id} already deleted")
            except Exception as e:
                logger.error(f"  ❌ Failed to delete {phase} message {msg_id}: {e}")

        logger.info(f"✅ Week cleanup complete for {week_start_str}")
    except Exception as e:
        logger.error(f"❌ delete_week_messages error: {e}", exc_info=True)


async def delete_old_challenge_rows(current_week_start: str):
    """
    Delete uncompleted challenge rows from old weeks. Completed rows are kept
    for analytics regardless of age.
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            cursor = await db.execute(
                'DELETE FROM weekly_challenges '
                'WHERE week_start != ? AND completed_by_user IS NULL',
                (current_week_start,)
            )
            await db.commit()
            deleted = cursor.rowcount
            logger.info(
                f"🗑️ Deleted {deleted} uncompleted old challenge row(s) "
                f"(kept completed rows + current week {current_week_start})"
            )
    except Exception as e:
        logger.error(f"❌ delete_old_challenge_rows error: {e}", exc_info=True)

# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class WeeklyChallengesCog(commands.Cog):
    """Weekly challenges — auto-fires on schedule, completion checked hourly."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await init_challenges_table()
        self.bot.loop.create_task(challenge_scheduler(self.bot))
        asyncio.ensure_future(_push_events_payload(self.bot))
        logger.info("✅ Weekly Challenges cog loaded")

    @commands.Cog.listener()
    async def on_dates_updated(self):
        """
        Fired by GlobalConfig whenever start_date or end_date changes.
        Wakes the sleeping scheduler so it re-reads config immediately instead
        of waiting out its original multi-hour sleep.
        """
        logger.info("📅 on_dates_updated received — waking challenge scheduler")
        _get_reschedule_event().set()


async def _resolve_display_name(bot, user_id, fallback: str | None = None) -> str:
    """Resolve a Discord display name, falling back to stored name then raw user id."""
    if not user_id:
        return '—'
    uid = int(user_id)
    if bot:
        user = bot.get_user(uid)
        if user is None:
            try:
                user = await bot.fetch_user(uid)
            except Exception:
                user = None
        if user:
            return user.display_name
    return fallback or str(uid)


async def _resolve_avatar_url(bot, user_id) -> str | None:
    """Resolve a Discord user's avatar URL, returning None on failure."""
    if not user_id or not bot:
        return None
    uid = int(user_id)
    user = bot.get_user(uid)
    if user is None:
        try:
            user = await bot.fetch_user(uid)
        except Exception:
            return None
    if user:
        return str(user.display_avatar.url)
    return None


def _deterministic_description(challenge_id: int, duty: str, target: int, difficulty: int) -> str:
    """Stable flavour text for challenges saved before description column existed."""
    duty_label = DUTY_LABEL.get(duty, duty.capitalize())
    if difficulty <= 3:
        pool = _DESC_TEMPLATES_LOW
    elif difficulty <= 7:
        pool = _DESC_TEMPLATES_MID
    else:
        pool = _DESC_TEMPLATES_HIGH
    flair = pool[challenge_id % len(pool)].format(target=target, duty=duty_label)
    wp = challenge_wp_reward(difficulty)
    return (
        f"{flair}\n"
        f"First to {target} {duty_label} · Difficulty {difficulty}/10 · Reward {wp} WP"
    )


async def _enrich_challenge_row(ch: dict, bot=None) -> dict:
    """Map a weekly_challenges DB row to website display fields."""
    duty = ch.get('duty', '')
    target = ch.get('target_count', ch.get('target', 0))
    difficulty = ch.get('difficulty', 0)
    cid = ch.get('id', 0)
    emoji = DUTY_EMOJI.get(duty, '🎯')
    duty_label = DUTY_LABEL.get(duty, duty.capitalize())
    completed_by = ch.get('completed_by_user')
    expired_at = ch.get('expired_at')
    stored_desc = ch.get('description')
    if stored_desc:
        description = stored_desc
    else:
        description = _deterministic_description(cid, duty, target, difficulty)
    winner = None
    winner_avatar = None
    if completed_by:
        winner = await _resolve_display_name(bot, completed_by, fallback=ch.get('winner_name'))
        winner_avatar = await _resolve_avatar_url(bot, completed_by)
    if completed_by:
        status = 'completed'
    elif expired_at:
        status = 'expired'
    else:
        status = 'active'
    return {
        'id': cid,
        'duty': duty,
        'target_count': target,
        'difficulty': difficulty,
        'challenge_type': ch.get('challenge_type'),
        'completion_mode': ch.get('completion_mode', 'first_to_target'),
        'name': f"{emoji} {duty_label} Challenge",
        'description': description,
        'reward': challenge_wp_reward(difficulty),
        'status': status,
        'winner': winner,
        'winner_avatar': winner_avatar,
        'completed_at': ch.get('completed_at'),
        'expired_at': expired_at,
    }


async def build_challenges_payload(bot=None):
    """Build the events.json challenges section from the current week's challenges."""
    import aiosqlite
    _DB = Path(__file__).resolve().parent.parent / 'bot_database.db'
    try:
        with open(Path(__file__).resolve().parent.parent / 'config.json', 'r') as _f:
            week_start = json.load(_f).get('global_dates', {}).get('start_date', '')
    except Exception:
        week_start = ''
    challenges = []
    leaderboard = []
    try:
        async with aiosqlite.connect(str(_DB)) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                "SELECT * FROM weekly_challenges WHERE week_start = ? ORDER BY id ASC",
                (week_start,)
            )
            for row in rows:
                challenges.append(await _enrich_challenge_row(dict(row), bot))
            lb_rows = await db.execute_fetchall(
                "SELECT completed_by_user, winner_name, COUNT(*) as wins, SUM(difficulty) as points "
                "FROM weekly_challenges "
                "WHERE completed_by_user IS NOT NULL AND week_start = ? "
                "GROUP BY completed_by_user ORDER BY wins DESC, points DESC LIMIT 20",
                (week_start,)
            )
            for i, row in enumerate(lb_rows):
                entry = dict(row)
                name = await _resolve_display_name(bot, entry['completed_by_user'], fallback=entry.get('winner_name'))
                leaderboard.append({
                    'rank': i + 1,
                    'name': name,
                    'username': name,
                    'user_id': entry['completed_by_user'],
                    'points': entry['points'] * CHALLENGE_WP_MULTIPLIER,
                    'wins': entry['wins'],
                })
    except Exception as e:
        logger.warning(f"build_challenges_payload error: {e}")
    return {
        'week_start': week_start,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'challenges': challenges,
        'leaderboard': leaderboard,
    }


async def _push_events_payload(bot=None):
    """Merge fresh challenge data into events.json, preserving power-hour fields."""
    try:
        from tasks.staff_hub_writer import push_events_to_github
        events_path = Path(__file__).resolve().parent.parent / 'website' / 'data' / 'events.json'
        existing = {}
        if events_path.exists():
            try:
                existing = json.loads(events_path.read_text(encoding='utf-8'))
            except Exception:
                existing = {}
        preserve_keys = (
            'power_hours', 'power_hour_meta', 'last_roll', 'active_power_hour',
        )
        preserved = {k: existing[k] for k in preserve_keys if k in existing}
        fresh = await build_challenges_payload(bot)
        existing.update(fresh)
        existing.update(preserved)
        existing.setdefault('power_hours', [])
        await push_events_to_github(existing)
    except Exception as e:
        logger.warning(f"_push_events_payload error: {e}")


async def setup(bot):
    await bot.add_cog(WeeklyChallengesCog(bot))