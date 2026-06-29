"""
Unified Weekly Loop -- tasks/unified_weekly_loop.py
Merges the old duties_scan.py (4h scanner) and weekly_checks.py (72h/168h awards)
into ONE hourly loop that is config-driven and preserves every reward/penalty/exemption path.

Spec: ai-hub/plans/unified_weekly_loop_specification.md (v2, 2026-06-22)

Cadence:
  - Every hour: incremental scan (delta-only message fetch, full req/modlog/reviews)
  - Hour 168: final full scan -> awards phase (placement WP, Bad penalties, rank-100 reward)
  - Mid-week warnings: REMOVED
  - Role monitor: folded into the hourly scan (no separate 30-min loop)
"""

import discord
from discord.ext import commands
import logging
import asyncio
import json
import math
import re
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Set, Any, List, Optional, Tuple

from core.helpers import (
    get_start_datetime,
    get_end_datetime,
    get_automation_config,
    get_readable_text_channels,
    safe_history_fetch,
    is_reply_to_other,
    extract_embed_content,
    check_if_user_is_away,
    is_user_normal_away,
    web_avatar_url,
)
from core.cache import config_cache
import database

logger = logging.getLogger('discord')


# ==================== CONSTANTS ====================

SOURCE_GUILDS = [988564962802810961, 971731167621574666]
REPORT_GUILD_ID = 1041450125391835186

REPORT_CHANNELS = {'req': 1213937694921728020}
LEADERBOARD_CHANNELS = {'req': 1467087539490783285}

MID_WEEK_HOURS = 72
FULL_WEEK_HOURS = 168

# Rate limiting
RATE_LIMIT_DELAY            = 1.2
DELAY_BETWEEN_CHANNELS      = 1.5
DELAY_BETWEEN_GUILDS        = 5.0
DELAY_BETWEEN_DUTIES        = 4.0
AUDIT_LOG_BATCH_SIZE        = 500
DELAY_BETWEEN_AUDIT_BATCHES = 2.5
MAX_RETRIES                 = 3
BATCH_DELAY                 = 2.0
DM_DELAY                    = 1.0

DUTY_CONFIG = {
    'req': {'emoji': '\U0001f5fa\ufe0f', 'name': 'Map Request Helper',
            'great': 50, 'good': 20, 'okay': 8},
}
RANK_MEDALS = {1: '\U0001f947', 2: '\U0001f948', 3: '\U0001f949'}


# ==================== RATE LIMIT TRACKER ====================

class RateLimitTracker:
    def __init__(self):
        self.hit_count = 0
        self.last_hit_time = None
        self.rate_limit_log_file = 'duties_scan_rate_limits.log'

    def log_rate_limit(self, retry_after: float, endpoint: str = "unknown"):
        self.hit_count += 1
        self.last_hit_time = datetime.now(timezone.utc)
        msg = (f"[{self.last_hit_time}] RATE LIMIT HIT on {endpoint} "
               f"- retry_after={retry_after}s (total hits: {self.hit_count})")
        logger.warning(msg)
        with open(self.rate_limit_log_file, 'a') as f:
            f.write(msg + '\n')

    def reset(self):
        self.hit_count = 0
        self.last_hit_time = None

rate_limit_tracker = RateLimitTracker()


# ==================== STATE (per-week lifecycle) ====================

_current_week_start: Optional[str] = None
_awards_done: bool = False
_last_scan_time: Optional[datetime] = None


# ==================== DUTY INFO EMBEDS ====================

_DUTY_INFO_FOOTER_TAG = "wdm-duty-info-v1"
REQ_BAD_PENALTY = 40  # Wave Points deducted for a Bad full-week map-request rank

DUTY_INFO_CONFIG = {
    'req': {
        'channel_id': 1467087539490783285,
        'title': '\U0001f5fa\ufe0f Map Request Helper Duty \u2014 How It Works',
        'color': 0x57F287,
        'ranks': (
            "\U0001f31f **Great:** 41+\n"
            "\u2b50 **Very Good:** 21 \u2013 40\n"
            "\u2705 **Good:** 10 \u2013 20\n"
            "\u274c **Bad:** 9 or below"
        ),
        'awards': (
            "\U0001f947 **1st place:** 150 WP\n"
            "\U0001f948 **2nd place:** 100 WP"
        ),
    },
}


def build_duty_info_embed(duty_type: str) -> Optional[discord.Embed]:
    cfg = DUTY_INFO_CONFIG.get(duty_type)
    if not cfg:
        return None
    embed = discord.Embed(
        title=cfg['title'],
        description=(
            "Welcome to the duty info hub! Here's everything you need to know "
            "about how this duty works, how you earn WP, and what happens "
            "if you slack off this week."
        ),
        color=cfg['color'],
    )
    embed.add_field(name="\U0001f4ca Performance Ranks (Full Week)", value=cfg['ranks'], inline=False)
    embed.add_field(name="\U0001f4b0 Weekly WP Awards", value=cfg['awards'], inline=False)
    embed.add_field(
        name="\u26a0\ufe0f Bad Performance Penalty",
        value=(
            f"Get a \u274c **Bad** rank? You lose **{REQ_BAD_PENALTY} WP** from your balance.\n"
            "\u2022 Deducted from your **main wallet**\n"
            f"\u2022 If your total WP is **below {REQ_BAD_PENALTY}** \u2192 your duty role is **automatically removed**\n"
            "\u2022 You'll get a DM telling you what happened"
        ),
        inline=False,
    )
    embed.add_field(
        name="\U0001f334 Away Role Exemption",
        value=(
            "Both **Away** and **Strike Immunity Away** roles are fully exempt from the Bad penalty.\n"
            "*If you're away, you won't lose WP or your duty role.*"
        ),
        inline=False,
    )
    embed.add_field(
        name="\u23f0 When Are Awards Given?",
        value="**At the end of every Full Week** (every 7 days).",
        inline=False,
    )
    embed.set_footer(text=_DUTY_INFO_FOOTER_TAG)
    return embed


async def post_duty_info_embeds(bot):
    """Post (or edit) the duty info embed in each duty's info channel. Called on startup."""
    for duty_type, cfg in DUTY_INFO_CONFIG.items():
        channel_id = cfg['channel_id']
        channel = bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"  Duty info channel {channel_id} ({duty_type}) not found")
            continue
        embed = build_duty_info_embed(duty_type)
        if embed is None:
            continue
        existing: Optional[discord.Message] = None
        try:
            async for message in channel.history(limit=50):
                if (message.author == bot.user and message.embeds
                        and message.embeds[0].footer
                        and message.embeds[0].footer.text == _DUTY_INFO_FOOTER_TAG):
                    existing = message
                    break
        except Exception as e:
            logger.error(f"  Error searching {duty_type} info channel history: {e}")
        try:
            if existing:
                await existing.edit(embed=embed)
                logger.info(f"  Edited {duty_type} duty info embed in channel {channel_id}")
            else:
                await channel.send(embed=embed)
                logger.info(f"  Posted new {duty_type} duty info embed in channel {channel_id}")
        except Exception as e:
            logger.error(f"  Failed to post {duty_type} duty info embed: {e}")


# ==================== WEEK HISTORY (past-weeks dropdown) ====================

_DUTIES_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'website', 'data', 'duties.json')
_MAX_WEEKS_HISTORY = 8


def _read_existing_weeks() -> list:
    """Return the completed-week snapshots already stored in duties.json (or [])."""
    try:
        with open(_DUTIES_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('weeks', []) or []
    except Exception:
        return []


def _snapshot_completed_week():
    """
    Snapshot the week currently sitting in duties.json ({_meta, users}) into
    weeks[] (newest first, capped). Called at new-week detection so the just-
    finished week is preserved for the website's past-weeks dropdown before the
    new week's data overwrites the live block.
    """
    try:
        with open(_DUTIES_JSON_PATH, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except Exception as e:
        logger.warning(f"  Week snapshot skipped — could not read duties.json: {e}")
        return

    if not payload.get('users'):
        logger.info("  Week snapshot skipped — no users in current duties.json")
        return

    snap = {'_meta': payload.get('_meta', {}), 'users': payload.get('users', {})}
    weeks = payload.get('weeks', []) or []
    # Avoid duplicating if this exact week was already snapshotted
    snap_start = snap['_meta'].get('start_date')
    weeks = [w for w in weeks if w.get('_meta', {}).get('start_date') != snap_start]
    weeks.insert(0, snap)
    payload['weeks'] = weeks[:_MAX_WEEKS_HISTORY]

    try:
        with open(_DUTIES_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        logger.info(f"  Archived completed week {snap_start} into weeks[] "
                    f"({len(payload['weeks'])} weeks kept)")
    except Exception as e:
        logger.error(f"  Week snapshot write failed: {e}")


# ==================== CONFIG HELPER ====================

def get_global_dates_from_config():
    """Get global dates from config.json."""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        global_dates = config.get('global_dates', {})
        start_date = global_dates.get('start_date')
        end_date = global_dates.get('end_date')
        if not start_date or not end_date:
            global_config = config.get('global', {})
            start_date = global_config.get('start_date')
            end_date = global_config.get('end_date')
        return start_date, end_date
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return None, None


# ==================== STAFF DISCOVERY ====================

def find_staff_for_duty(guild: discord.Guild, duty_type: str) -> Dict[int, str]:
    """Find members who hold the duty role in this guild. Returns {user_id: display_name}."""
    staff: Dict[int, str] = {}
    for role in guild.roles:
        rn = role.name.lower()
        match = False
        if duty_type == 'req' and rn == 'map request helper':
            match = True
        if match:
            logger.info(f"    Found {duty_type} role: {role.name} ({len(role.members)} members)")
            for member in role.members:
                if not member.bot:
                    staff[member.id] = member.display_name
    return staff


def find_general_staff(guild: discord.Guild) -> Dict[int, str]:
    """Find all general staff members (Trial Staff / Staff roles). Returns {user_id: display_name}."""
    general_role_names: List[str] = []
    try:
        with open('config.json', 'r') as _f:
            _cfg = json.load(_f)
        general_role_names = [
            n.lower() for n in _cfg.get('staff_roles_config', {}).get('general_staff', [])
        ]
    except Exception:
        pass
    if not general_role_names:
        general_role_names = ['trial staff', 'staff']
    staff: Dict[int, str] = {}
    for role in guild.roles:
        rn = role.name.lower()
        if rn in general_role_names:
            for member in role.members:
                if not member.bot:
                    staff[member.id] = member.display_name
    return staff


# ==================== SCAN FUNCTIONS ====================

async def scan_requests_for_member(guild, member, start_datetime, end_datetime) -> int:
    """Scan request channel for this member's reply-to-other messages."""
    guild_config = await config_cache.get_guild_config(guild.id)
    request_channel_id = guild_config.get('request_channel_id')
    if not request_channel_id:
        return 0
    request_channel = guild.get_channel(request_channel_id)
    if not request_channel:
        return 0
    count = 0
    try:
        await asyncio.sleep(RATE_LIMIT_DELAY)
        messages = await safe_history_fetch(
            request_channel, limit=5000,
            after=start_datetime, before=end_datetime
        )
        for message in messages:
            if (message.author.id == member.id and not message.author.bot
                    and is_reply_to_other(message)):
                count += 1
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"    Error scanning requests for {member.name}: {e}")
    return count


async def scan_modlog_for_member(guild, member, start_datetime, end_datetime) -> int:
    """Scan modlog channel for bot embeds mentioning this member."""
    guild_config = await config_cache.get_guild_config(guild.id)
    modlog_channel_id = guild_config.get('modlog_channel_id') or guild_config.get('modlogs_channel_id')
    if not modlog_channel_id:
        return 0
    modlog_channel = guild.get_channel(modlog_channel_id)
    if not modlog_channel:
        return 0
    count = 0
    uid_str = str(member.id)
    try:
        await asyncio.sleep(RATE_LIMIT_DELAY)
        messages = await safe_history_fetch(
            modlog_channel, limit=5000,
            after=start_datetime, before=end_datetime
        )
        for message in messages:
            if message.author.bot and message.embeds:
                for embed in message.embeds:
                    content = extract_embed_content(embed)
                    if uid_str in content:
                        count += 1
                        break
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"    Error scanning modlog for {member.name}: {e}")
    return count


async def scan_messages_all_guilds_optimized(
    bot, all_staff: Dict[int, str], source_guilds: List[int],
    start_datetime: datetime, end_datetime: datetime,
    start_date: str, end_date: str,
) -> tuple:
    """Optimized message scan: fetch ALL messages once per channel, count by author.
    Returns ({user_id: {'count': int, 'days': [...]}}, {user_id: display_name})"""
    merged: Dict[int, int] = {}
    merged_days: Dict[int, set] = {}
    display_map: Dict[int, str] = {}
    for uid, name in all_staff.items():
        display_map[uid] = name
        merged[uid] = 0
        merged_days[uid] = set()

    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        logger.info(f"  Scanning messages in {guild.name}...")
        text_channels = get_readable_text_channels(guild)
        guild_counts: Dict[int, int] = {uid: 0 for uid in all_staff}
        guild_days: Dict[int, Set] = {uid: set() for uid in all_staff}
        for ch_idx, channel in enumerate(text_channels):
            if ch_idx > 0:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)
            try:
                messages = await safe_history_fetch(
                    channel, limit=5000,
                    after=start_datetime, before=end_datetime
                )
                for message in messages:
                    if message.author.id in all_staff and not message.author.bot:
                        guild_counts[message.author.id] = guild_counts.get(message.author.id, 0) + 1
                        guild_days[message.author.id].add(message.created_at.date())
            except discord.errors.RateLimited as e:
                rate_limit_tracker.log_rate_limit(e.retry_after, f"message_history/{channel.name}")
                await asyncio.sleep(e.retry_after + 1)
                try:
                    messages = await safe_history_fetch(
                        channel, limit=5000,
                        after=start_datetime, before=end_datetime
                    )
                    for message in messages:
                        if message.author.id in all_staff and not message.author.bot:
                            guild_counts[message.author.id] = guild_counts.get(message.author.id, 0) + 1
                            guild_days[message.author.id].add(message.created_at.date())
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"    Error scanning #{channel.name}: {e}")
        for uid, count in guild_counts.items():
            merged[uid] = merged.get(uid, 0) + count
            merged_days[uid] = merged_days.get(uid, set()) | guild_days[uid]
            if uid in all_staff:
                gm = guild.get_member(uid)
                display_map[uid] = gm.display_name if gm else all_staff[uid]
            days_list = sorted([d.isoformat() for d in guild_days[uid]])
            await cache_stat(guild_id, uid, 'message', {'count': count, 'days': days_list},
                             start_date, end_date)

    merged_with_days = {
        uid: {'count': merged[uid], 'days': sorted([d.isoformat() for d in merged_days[uid]])}
        for uid in merged
    }
    return merged_with_days, display_map


# ==================== INCREMENTAL MESSAGE SCAN ====================

async def scan_messages_incremental(
    bot, all_staff: Dict[int, str], source_guilds: List[int],
    after_dt: datetime, before_dt: datetime,
    start_date: str, end_date: str,
) -> tuple:
    """Delta-only message scan: fetch messages only after last scan time.
    Returns ({user_id: {'count': int, 'days': [...]}}, {user_id: display_name})
    These are DELTAS -- caller must merge with existing cached counts."""
    delta_counts: Dict[int, int] = {uid: 0 for uid in all_staff}
    delta_days: Dict[int, set] = {uid: set() for uid in all_staff}
    display_map: Dict[int, str] = dict(all_staff)

    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        text_channels = get_readable_text_channels(guild)
        for ch_idx, channel in enumerate(text_channels):
            if ch_idx > 0:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)
            try:
                messages = await safe_history_fetch(
                    channel, limit=5000,
                    after=after_dt, before=before_dt
                )
                for message in messages:
                    if message.author.id in all_staff and not message.author.bot:
                        delta_counts[message.author.id] += 1
                        delta_days[message.author.id].add(message.created_at.date())
            except Exception as e:
                logger.debug(f"    Incremental scan error #{channel.name}: {e}")

    # Build result with merged days from existing cache
    result = {}
    for uid in all_staff:
        existing = await database.get_cached_user_stats(
            source_guilds[0], uid, 'message', start_date, end_date
        ) if source_guilds else None
        old_count = 0
        old_days = []
        if existing:
            old_count = existing.get('count', 0)
            old_days = existing.get('days', [])
        new_count = old_count + delta_counts[uid]
        all_days = set(old_days) | {d.isoformat() for d in delta_days[uid]}
        result[uid] = {'count': new_count, 'days': sorted(all_days)}

    return result, display_map


# ==================== CACHE HELPER ====================

async def cache_stat(guild_id, user_id, duty_type, count, start_date, end_date,
                     scan_completed=True):
    """Cache a duty count to the database. Never overwrites a higher existing count."""
    if not scan_completed:
        return
    try:
        data = count if isinstance(count, dict) else {'count': count}
        new_count = data.get('count', 0)
        existing = await database.get_cached_user_stats(
            guild_id, user_id, duty_type, start_date, end_date
        )
        if existing:
            existing_count = existing.get('count', 0)
            if new_count < existing_count:
                return
        await database.set_cached_user_stats(
            guild_id=guild_id, user_id=user_id, check_type=duty_type,
            start_date=start_date, end_date=end_date,
            data=data, cache_time=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error(f"    Failed to cache {duty_type} for user {user_id}: {e}")


# ==================== PER-DUTY SCAN ACROSS GUILDS ====================

async def scan_duty_all_guilds(bot, duty_type, source_guilds, start_datetime, end_datetime,
                               start_date, end_date):
    """Find staff by role name, scan every guild, cache to DB.
    Returns ({user_id: total_count}, {user_id: display_name})."""
    all_staff: Dict[int, str] = {}
    member_display_map: Dict[int, str] = {}
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        found = find_staff_for_duty(guild, duty_type)
        for uid, name in found.items():
            all_staff[uid] = name
            member_display_map[uid] = name

    if not all_staff:
        return {}, {}

    merged_counts: Dict[int, int] = {uid: 0 for uid in all_staff}
    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        for user_id in list(all_staff.keys()):
            member = guild.get_member(user_id)
            if not member:
                continue
            if duty_type == 'req':
                count = await scan_requests_for_member(guild, member, start_datetime, end_datetime)
            else:
                count = 0
            merged_counts[user_id] += count
            await cache_stat(guild_id, user_id, duty_type, count, start_date, end_date)

    return merged_counts, member_display_map


async def scan_modlog_all_guilds(bot, all_staff, source_guilds, start_datetime, end_datetime,
                                  start_date, end_date):
    """Scan modlog for all staff across all guilds."""
    merged: Dict[int, int] = {uid: 0 for uid in all_staff}
    display_map: Dict[int, str] = dict(all_staff)
    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        for user_id in list(all_staff.keys()):
            member = guild.get_member(user_id)
            if not member:
                continue
            count = await scan_modlog_for_member(guild, member, start_datetime, end_datetime)
            merged[user_id] += count
            display_map[user_id] = member.display_name
            await cache_stat(guild_id, user_id, 'modlog', count, start_date, end_date)
    return merged, display_map


# ==================== HITL REVIEW SCAN ====================

def _iso_z(dt: datetime) -> str:
    """Format datetime for bot_logs comparison."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def scan_reviews_extended(start_datetime, end_datetime) -> Dict[int, Dict[str, int]]:
    """
    Count HITL proof-review clicks per staff member (cross-bot, from bot_logs).
    Returns {user_id: {'count': N, 'unique_days': D}} where unique_days is the
    number of distinct calendar days with at least one review.
  """
    import aiosqlite
    counts: Dict[int, int] = {}
    review_days: Dict[int, Set] = {}
    start_s = _iso_z(start_datetime)
    end_s = _iso_z(end_datetime)
    try:
        async with aiosqlite.connect(database.DB_FILE) as conn:
            await conn.execute("PRAGMA busy_timeout=30000")
            cursor = await conn.execute(
                """SELECT actor_json, timestamp FROM bot_logs
                   WHERE category = 'hitl_review' AND action = 'review_completed'
                     AND timestamp >= ? AND timestamp < ?""",
                (start_s, end_s),
            )
            rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"  scan_reviews failed: {e}")
        return {}
    for actor_json, timestamp in rows:
        if not actor_json:
            continue
        try:
            actor = json.loads(actor_json)
            uid = int(actor.get('id'))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        counts[uid] = counts.get(uid, 0) + 1
        if timestamp:
            try:
                ts = timestamp.replace('Z', '+00:00') if isinstance(timestamp, str) else timestamp
                day = datetime.fromisoformat(ts).date()
                review_days.setdefault(uid, set()).add(day)
            except (TypeError, ValueError):
                pass
    return {
        uid: {'count': counts[uid], 'unique_days': len(review_days.get(uid, set()))}
        for uid in counts
    }


async def scan_reviews(start_datetime, end_datetime) -> Dict[int, int]:
    """Count HITL proof-review clicks per staff member (cross-bot, from bot_logs). No API calls."""
    extended = await scan_reviews_extended(start_datetime, end_datetime)
    return {uid: data['count'] for uid, data in extended.items()}


async def scan_role_adds_all_staff(bot, all_staff, source_guilds, start_datetime, end_datetime) -> Dict[int, int]:
    """
    Scan audit logs for ROLE ADDS only (not removes) by general staff members.
    Works like the message scan — detects any staff member giving roles across source guilds.
    Returns {user_id: count_of_role_adds}
    """
    counts: Dict[int, int] = {}
    staff_ids = set(int(uid) for uid in all_staff.keys())

    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        try:
            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.member_role_update,
                after=start_datetime,
                before=end_datetime,
                limit=None,
            ):
                actor_id = entry.user.id if entry.user else None
                if actor_id not in staff_ids:
                    continue
                # entry.after.roles contains the delta of roles added (empty on removes)
                after_roles = getattr(entry.after, 'roles', None)
                if after_roles:
                    counts[actor_id] = counts.get(actor_id, 0) + 1
        except Exception as e:
            logger.warning(f"  scan_role_adds failed for guild {guild_id}: {e}")

    return counts


# ==================== LIFETIME ACCUMULATION + JSON BUILDER ====================

def _extract_count(raw) -> int:
    """Extract integer count from all_stats values (may be int or dict with 'count')."""
    if isinstance(raw, dict):
        return int(raw.get('count', 0))
    return int(raw)


async def _accumulate_lifetime(all_stats: dict, general_staff_ids: set, start_date: str):
    """
    Accumulate finalized weekly message/modlog/req into lifetime_totals
    and write staff_insights_history for >goals.
    Called only at hour-168 (once per week), guarded by dup check.
    """
    # Build user_metrics: {uid: {'message': N, 'modlog': N, 'req': N}}
    user_metrics = {}
    for uid in general_staff_ids:
        metrics = {}
        for metric in ('message', 'modlog', 'req'):
            raw = all_stats.get(metric, {}).get(uid, 0)
            c = _extract_count(raw)
            if c > 0:
                metrics[metric] = c
        if metrics:
            user_metrics[uid] = metrics

    # 1. Accumulate into lifetime_totals (dup-guarded by last_added_week)
    await database.upsert_lifetime_totals_batch(user_metrics, start_date)

    # 2. Write staff_insights_history for >goals
    now = datetime.now(timezone.utc).isoformat()
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            rows = []
            for uid, metrics in user_metrics.items():
                for duty_type, count in metrics.items():
                    rows.append((uid, duty_type, count))
            if rows:
                await db.executemany('''
                    INSERT INTO staff_insights_history
                        (user_id, user_name, duty_type, week_start, week_end, count, is_midweek, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT DO NOTHING
                ''', [
                    (uid, f'User {uid}', dt, start_date, '', cnt, now)
                    for uid, dt, cnt in rows
                ])
                await db.commit()
                logger.info(f"  staff_insights_history: {len(rows)} rows written")
    except Exception as e:
        logger.error(f"  staff_insights_history write failed: {e}")


async def _build_and_write_lifetime_json(bot, source_guilds: list) -> bool:
    """
    Build lifetime.json from lifetime_totals + all-time bot_logs reviews.
    Writes to website/data/lifetime.json.
    """
    try:
        lt = await database.get_all_lifetime_totals()
        reviews = await database.get_all_time_reviews()

        # Merge all known user IDs
        all_uids = set(lt.keys()) | set(reviews.keys())

        # Build user info lookup
        user_info = {}
        for gid in source_guilds:
            guild = bot.get_guild(gid)
            if not guild:
                continue
            for m in guild.members:
                if m.bot:
                    continue
                if m.id not in user_info:
                    from tasks.hierarchy_cache import get_cached_role
                    top_role, role_tier, _ = get_cached_role(m.id)
                    user_info[m.id] = {
                        'name': m.display_name,
                        'top_role': top_role,
                        'avatar_url': web_avatar_url(m.display_avatar),
                    }

        # Build payload
        users = {}
        for uid in all_uids:
            info = user_info.get(uid)
            if not info:
                continue
            user_lt = lt.get(uid, {})
            users[str(uid)] = {
                'user_id': str(uid),
                'name': info['name'],
                'top_role': info['top_role'],
                'avatar_url': info['avatar_url'],
                'lifetime': {
                    'message': user_lt.get('message', 0),
                    'modlog':  user_lt.get('modlog', 0),
                    'req':     user_lt.get('req', 0),
                    'reviews': reviews.get(uid, 0),
                },
            }

        # Read current start_date for as_of_week
        start_date = ''
        try:
            with open('config.json', 'r') as f:
                cfg = json.load(f)
            gd = cfg.get('global_dates', cfg.get('global', {}))
            start_date = gd.get('start_date', '')
        except Exception:
            pass

        payload = {
            '_meta': {
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'as_of_week': start_date,
            },
            'users': users,
        }

        from tasks.staff_hub_writer import write_local_payload
        write_local_payload('lifetime.json', payload)
        logger.info(f"  ✅ lifetime.json written ({len(users)} users)")
        return True
    except Exception as e:
        logger.error(f"  lifetime.json build failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


# ==================== HUB PAYLOAD BUILDER ====================

def _get_member_role_info(bot, uid: int, guild_ids: list):
    """Return (top_role_name, role_tier) for a user across source guilds."""
    TIER_ORDER = [
        ('board',   ['board', 'co-owner', 'owner', 'founder']),
        ('head',    ['head management', 'head manager']),
        ('mgmt',    ['management']),
        ('admin',   ['head admin', 'admin']),
        ('sradmin', ['senior admin']),
        ('sup',     ['head support', 'support']),
        ('srsup',   ['senior support']),
        ('staff',   ['staff']),
        ('trial',   ['trial staff', 'trial']),
    ]
    best_idx = len(TIER_ORDER)
    best_name = 'Trial Staff'
    best_tier = 'trial'
    for guild_id in guild_ids:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        member = guild.get_member(uid)
        if not member:
            continue
        for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
            rname = role.name.lower()
            for idx, (tier, keywords) in enumerate(TIER_ORDER):
                if idx >= best_idx:
                    break
                if any(kw in rname for kw in keywords):
                    best_idx = idx
                    best_name = role.name
                    best_tier = tier
                    break
    return best_name, best_tier


def _duty_rank(count: int, duty_type: str) -> tuple:
    """Return (rank_label, rank_emoji) for a duty count."""
    thresholds = [(41, 'Great', '\U0001f31f'), (21, 'Very Good', '\u2b50'),
                  (10, 'Good', '\u2705'), (5, 'Okay', '\u26a0\ufe0f'), (0, 'Bad', '\u274c')]
    for threshold, label, emoji in thresholds:
        if count >= threshold:
            return label, emoji
    return 'Bad', '\u274c'


def _build_unified_hub_payload(
    bot, all_stats: dict, all_display: dict, avatar_cache: dict,
    general_staff_ids: set, source_guilds: list,
    start_date: str, end_date: str,
) -> dict:
    """Build the duties.json payload for the Wave Staff Hub page."""
    duty_uids: dict = {}
    for dt in ('req',):
        for uid in set(all_stats.get(dt, {}).keys()) | set(all_display.get(dt, {}).keys()):
            duty_uids.setdefault(int(uid), set()).add(dt)
    all_uids = set(duty_uids.keys()) | general_staff_ids

    def _positions(duty_type):
        stats = all_stats.get(duty_type, {})
        display = all_display.get(duty_type, {})
        entries = []
        for uid in set(stats.keys()) | set(display.keys()):
            count = stats.get(uid, 0)
            if isinstance(count, dict):
                count = count.get('count', 0)
            entries.append((int(uid), count, check_if_user_is_away(bot, uid)))
        entries.sort(key=lambda e: (e[2], -e[1]))
        return {uid: (pos + 1, len(entries)) for pos, (uid, _, _) in enumerate(entries)}

    req_positions = _positions('req')
    users = {}
    for uid in all_uids:
        uid = int(uid)
        name = (all_display.get('req', {}).get(uid) or all_display.get('message', {}).get(uid)
                or all_display.get('modlog', {}).get(uid) or f'User {uid}')
        avatar_url = avatar_cache.get(uid)
        is_away = check_if_user_is_away(bot, uid)
        away_type = 'normal' if is_user_normal_away(bot, uid) else ('immunity' if is_away else None)
        from tasks.hierarchy_cache import get_cached_role, _get_display_role_for_activity_page
        top_role, role_tier, has_staff_role = get_cached_role(uid)
        display_role, display_tier = _get_display_role_for_activity_page(bot, uid)
        entry: dict = {
            'user_id': str(uid), 'name': name, 'top_role': top_role,
            'role_tier': role_tier, 'display_role': display_role, 'display_tier': display_tier,
            'has_staff_role': has_staff_role,
            'avatar_url': avatar_url, 'is_away': is_away,
        }
        if away_type:
            entry['away_type'] = away_type
        # Duties
        if uid in duty_uids:
            entry['duties'] = {}
            for dt in ('req',):
                if dt not in duty_uids[uid]:
                    continue
                raw = all_stats.get(dt, {}).get(uid, 0)
                count = raw.get('count', 0) if isinstance(raw, dict) else int(raw)
                rank_label, rank_emoji = _duty_rank(count, dt)
                pos, total = req_positions.get(uid, (0, 0))
                entry['duties'][dt] = {
                    'count': count, 'rank': rank_label, 'rank_emoji': rank_emoji,
                    'position': pos, 'total_in_duty': total,
                    'wp_earned': 0, 'penalty_amount': 0, 'role_removed': False,
                }
        # Engagement (general staff)
        if uid in general_staff_ids:
            msg_raw = all_stats.get('message', {}).get(uid, 0)
            if isinstance(msg_raw, dict):
                messages = int(msg_raw.get('count', 0))
                days_list = msg_raw.get('days', [])
                days_set = set()
                for d in days_list:
                    try:
                        days_set.add(datetime.fromisoformat(d).date().weekday() if isinstance(d, str) else d)
                    except Exception:
                        pass
                days_active = len(days_set)
            else:
                messages = int(msg_raw)
                days_active = 0
            mod_commands = int(all_stats.get('modlog', {}).get(uid, 0))
            reviews_raw = all_stats.get('reviews', {}).get(uid, 0)
            reviews = int(reviews_raw.get('count', 0) if isinstance(reviews_raw, dict) else reviews_raw or 0)
            # KEEP EXACT FORMULA: (rank_messages+rank_days)/2 + mod + reviews, cap 100
            rank_messages = min(math.ceil(messages / 70 * 100), 100)
            rank_days = min(math.ceil(days_active / 7 * 100), 100)
            rank_total = min(math.ceil((rank_messages + rank_days) / 2 + mod_commands + reviews), 100)
            entry['engagement'] = {
                'messages': messages, 'days_active': days_active,
                'mod_commands': mod_commands, 'reviews': reviews,
                'rank_messages': rank_messages, 'rank_days': rank_days, 'rank_total': rank_total,
            }
        users[str(uid)] = entry
    return {
        '_meta': {
            'start_date': start_date, 'end_date': end_date,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'period': 'Full Week',
        },
        'users': users,
        # Carry forward completed-week history so the hourly overwrite never
        # wipes the past-weeks dropdown on the website.
        'weeks': _read_existing_weeks(),
    }


# ==================== PERFORMANCE RANKING (from weekly_checks) ====================

def get_performance_rank(count: int, report_type: str, period: str) -> dict:
    """Get performance ranking for a duty count."""
    if period == "Mid-Week":
        if report_type == 'req':
            if count < 5:
                return {'rank': '\u274c Bad', 'message': 'Need to do more', 'emoji': '\u274c'}
            elif count <= 10:
                return {'rank': '\u2705 Good', 'message': 'Try to do more', 'emoji': '\u2705'}
            elif count <= 20:
                return {'rank': '\u2b50 Very Good', 'message': '', 'emoji': '\u2b50'}
            else:
                return {'rank': '\U0001f31f Great', 'message': '', 'emoji': '\U0001f31f'}
    elif period == "Full Week":
        if report_type == 'req':
            if count < 10:
                return {'rank': '\u274c Bad', 'message': 'Need to do more', 'emoji': '\u274c'}
            elif count <= 20:
                return {'rank': '\u2705 Good', 'message': '', 'emoji': '\u2705'}
            elif count <= 40:
                return {'rank': '\u2b50 Very Good', 'message': '', 'emoji': '\u2b50'}
            else:
                return {'rank': '\U0001f31f Great', 'message': '', 'emoji': '\U0001f31f'}
    return {'rank': 'N/A', 'message': '', 'emoji': '\u2753'}


def get_ranking_explanation(report_type: str, period: str) -> str:
    if period == "Mid-Week" and report_type == 'req':
        return "\U0001f31f Great (21+) | \u2b50 Very Good (11\u201320) | \u2705 Good (5\u201310) | \u274c Bad (\u22644)"
    elif period == "Full Week" and report_type == 'req':
        return "\U0001f31f Great (41+) | \u2b50 Very Good (21\u201340) | \u2705 Good (10\u201320) | \u274c Bad (\u22649)"
    return "N/A"


# ==================== ROLE REMOVAL ====================

async def remove_role_in_guilds(bot, user_id: int, duty_type: str) -> bool:
    """Remove a duty role from user across all SOURCE_GUILDS and REPORT_GUILD_ID."""
    role_patterns = {'req': 'map request helper'}
    role_pattern = role_patterns.get(duty_type)
    if not role_pattern:
        return False
    removed_from_any = False
    for guild_id in SOURCE_GUILDS + [REPORT_GUILD_ID]:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        member = guild.get_member(user_id)
        if not member:
            continue
        role_to_remove = None
        for role in guild.roles:
            rn = role.name.lower()
            if role_pattern == 'map request helper':
                if rn == 'map request helper':
                    role_to_remove = role
                    break
            else:
                if role_pattern in rn:
                    role_to_remove = role
                    break
        if not role_to_remove or role_to_remove not in member.roles:
            continue
        try:
            await member.remove_roles(role_to_remove)
            logger.info(f"  Removed {duty_type} role from {member.name} in {guild.name}")
            removed_from_any = True
        except Exception as e:
            logger.error(f"  Failed to remove {duty_type} role from {member.name} in {guild.name}: {e}")
    return removed_from_any


# ==================== NEW MEMBER IMMUNITY ====================

async def is_user_newly_added(bot, user_id: int, duty_type: str, days_threshold: int = 4) -> bool:
    """Check if a user was added to a duty role within the last N days."""
    try:
        assignment_date = await database.get_role_assignment_date(user_id, duty_type)
        if not assignment_date:
            return False
        if isinstance(assignment_date, str):
            assignment_date = datetime.fromisoformat(assignment_date)
            if assignment_date.tzinfo is None:
                assignment_date = assignment_date.replace(tzinfo=timezone.utc)
        days_since = (datetime.now(timezone.utc) - assignment_date).total_seconds() / 86400
        return days_since < days_threshold
    except Exception:
        return False


# ==================== EMBED REPORT CREATION ====================

def create_report_embed(duty_type, period, staff_data, start_date, end_date,
                        guild_names, bot=None, immune_users=None):
    """Create the weekly report embed."""
    if immune_users is None:
        immune_users = set()
    duty_info = {'req': {'emoji': '\U0001f5fa\ufe0f', 'name': 'Map Request Activity Report'}}
    info = duty_info.get(duty_type, {'emoji': '\U0001f4ca', 'name': 'Activity Report'})
    title_period = f"{start_date} \u2192 {end_date} ({period})"
    embed = discord.Embed(
        title=f"{info['emoji']} {info['name']} - {title_period}",
        description=f"**Period:** {start_date} \u2192 {end_date}",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="\U0001f4ca Data Sources",
                    value="\n".join([f"\u2022 {n}" for n in guild_names]), inline=False)
    sorted_staff = sorted(staff_data.items(), key=lambda x: x[1][duty_type], reverse=True)
    activity_lines = []
    for idx, (user_id, data) in enumerate(sorted_staff, 1):
        count = data[duty_type]
        away_tag = " \U0001f3d6\ufe0f Away" if bot and is_user_normal_away(bot, user_id) else ""
        if user_id in immune_users:
            line = f"{idx}. **{data['name']}**{away_tag} - {count} \U0001f195 New Staff \u2022 Immune"
        else:
            rank_info = get_performance_rank(count, duty_type, period)
            line = f"{idx}. **{data['name']}**{away_tag} - {count} {rank_info['rank']}"
            if rank_info['message']:
                line += f" \u2022 {rank_info['message']}"
        activity_lines.append(line)
    if activity_lines:
        activity_text = "\n".join(activity_lines)
        if len(activity_text) > 1024:
            chunks, current, cur_len = [], [], 0
            for line in activity_lines:
                if cur_len + len(line) + 1 > 1024:
                    chunks.append("\n".join(current))
                    current, cur_len = [line], len(line)
                else:
                    current.append(line)
                    cur_len += len(line) + 1
            if current:
                chunks.append("\n".join(current))
            for i, chunk in enumerate(chunks):
                name = "\U0001f4cb Staff Activity" if i == 0 else f"Staff Activity (cont. {i})"
                embed.add_field(name=name, value=chunk, inline=False)
        else:
            embed.add_field(name="\U0001f4cb Staff Activity", value=activity_text, inline=False)
    scored = {uid: d for uid, d in staff_data.items() if uid not in immune_users}
    total_staff = len(scored)
    active_staff = sum(1 for d in scored.values() if d[duty_type] > 0)
    total_actions = sum(d[duty_type] for d in scored.values())
    new_count = len(staff_data) - len(scored)
    summary = f"**Total Staff:** {total_staff}\n**Active:** {active_staff}\n**Actions:** {total_actions}"
    if new_count > 0:
        summary += f"\n**\U0001f195 New Staff (immune):** {new_count}"
    embed.add_field(name="\U0001f4ca Summary", value=summary, inline=False)
    rank_counts = {'\U0001f31f': 0, '\u2b50': 0, '\u2705': 0, '\u26a0\ufe0f': 0, '\u274c': 0}
    for uid, d in scored.items():
        ri = get_performance_rank(d[duty_type], duty_type, period)
        if ri['emoji'] in rank_counts:
            rank_counts[ri['emoji']] += 1
    rankings = f"\U0001f31f Great: {rank_counts['\U0001f31f']}"
    if rank_counts.get('\u2b50', 0) > 0:
        rankings += f"\n\u2b50 Very Good: {rank_counts['\u2b50']}"
    rankings += (f"\n\u2705 Good: {rank_counts['\u2705']}"
                 f"\n\u26a0\ufe0f Okay: {rank_counts.get('\u26a0\ufe0f', 0)}"
                 f"\n\u274c Bad: {rank_counts['\u274c']}")
    embed.add_field(name="\U0001f3c6 Rankings Breakdown", value=rankings, inline=False)
    embed.add_field(name="\u2139\ufe0f Rankings",
                    value=f"**Rankings:**\n{get_ranking_explanation(duty_type, period)}", inline=False)
    embed.set_footer(text=f"Generated at \u2022 {datetime.now(timezone.utc).strftime('%d/%m/%Y, %I:%M %p')}")
    return embed


# ==================== PROCESS SINGLE DUTY (from weekly_checks) ====================

async def process_single_duty(bot, duty_type, guild_ids, start_datetime, end_datetime,
                               period, start_date, end_date, progress_message=None):
    """Process ONE duty: scan -> report -> WP awards/penalties -> results DMs.
    Returns: (staff_with_duty, duty_results) where duty_results is {} for non-Full-Week."""
    from tasks.wave_points import add_wave_points, get_wave_points

    thresholds = {'Mid-Week': {'req': 5}, 'Full Week': {'req': 10}}
    duty_names = {'req': 'Map Request Helper'}
    emoji = '\U0001f5fa\ufe0f' if duty_type == 'req' else '\U0001f4ca'
    logger.info(f"\n{emoji} PROCESSING {duty_type.upper()} DUTY - Period: {period}")

    # Step 1: Find staff with this duty
    staff_with_duty = {}
    for guild_id in guild_ids:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        for role in guild.roles:
            rn = role.name.lower()
            if duty_type == 'req' and rn == "map request helper":
                for member in role.members:
                    if not member.bot and member.id not in staff_with_duty:
                        staff_with_duty[member.id] = {'name': member.name, duty_type: 0}
    logger.info(f"  Found {len(staff_with_duty)} total staff with {duty_type} duty")
    if not staff_with_duty:
        return staff_with_duty, {}

    # Step 1.5: Identify new members (immune < 4 days)
    immune_users = set()
    for user_id in list(staff_with_duty.keys()):
        if await is_user_newly_added(bot, user_id, duty_type, days_threshold=4):
            immune_users.add(user_id)
    if immune_users:
        logger.info(f"  {len(immune_users)} immune user(s) found")

    # Step 2: Scan activity across guilds
    for guild_id in guild_ids:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        for user_id in staff_with_duty:
            member = guild.get_member(user_id)
            if not member:
                continue
            count = await scan_requests_for_member(guild, member, start_datetime, end_datetime) if duty_type == 'req' else 0
            staff_with_duty[user_id][duty_type] += count

    # Step 2.1: Apply manual overrides & divisors
    try:
        import os as _os
        _dj = _os.path.join(_os.path.dirname(__file__), '..', 'json_data', 'duties_totals.json')
        if _os.path.exists(_dj):
            with open(_dj, 'r') as f:
                _dd = json.load(f)
                _ov = _dd.get(duty_type, {})
            for uid in staff_with_duty:
                us = str(uid)
                if us in _ov:
                    ent = _ov[us]
                    if ent.get('is_override', False):
                        staff_with_duty[uid][duty_type] = ent.get('count', staff_with_duty[uid][duty_type])
                    elif ent.get('divisor', 1) > 1:
                        staff_with_duty[uid][duty_type] = max(0, staff_with_duty[uid][duty_type] // ent['divisor'])
    except Exception as e:
        logger.error(f"  Error applying overrides: {e}")
    await asyncio.sleep(BATCH_DELAY)

    # Step 2.5: Cleanup missing users
    try:
        all_db = await database.get_all_users_for_duty(duty_type)
        missing = set(all_db) - set(staff_with_duty.keys())
        if missing:
            logger.warning(f"  {len(missing)} user(s) no longer in {duty_type} duty")
    except Exception as e:
        logger.error(f"  Error during cleanup: {e}")

    # Step 3: Send embed report
    try:
        rc_id = REPORT_CHANNELS.get(duty_type)
        rg = bot.get_guild(REPORT_GUILD_ID)
        rc = rg.get_channel(rc_id) if rg and rc_id else None
        if rc:
            gn = [bot.get_guild(gid).name for gid in SOURCE_GUILDS if bot.get_guild(gid)]
            embed = create_report_embed(duty_type, period, staff_with_duty, start_date, end_date,
                                        gn, bot=bot, immune_users=immune_users)
            await rc.send(embed=embed)
        await database.mark_report_sent(REPORT_GUILD_ID, duty_type, period, start_date, end_date)
    except Exception as e:
        logger.error(f"  Failed to send report: {e}")
    await asyncio.sleep(BATCH_DELAY)

    # Mid-week warnings: REMOVED per spec section 1.1
    duty_results = {uid: {'wp_earned': 0, 'penalty_amount': 0, 'role_removed': False} for uid in staff_with_duty}
    user_dm_extras = {}

    if period == "Full Week":
        # Step 4: Wave Points placement awards
        logger.info(f"  Awarding {duty_type} Wave Points...")
        sorted_staff = sorted(staff_with_duty.items(), key=lambda x: x[1][duty_type], reverse=True)
        awards = {1: 150, 2: 100} if duty_type == 'req' else {}
        strike_thr = thresholds.get(period, {}).get(duty_type, 0)
        awarded = 0
        max_rank = max(awards.keys()) if awards else 0
        for rank, (uid, data) in enumerate(sorted_staff[:max_rank], start=1):
            if uid in immune_users:
                continue
            cnt = data[duty_type]
            if cnt >= strike_thr and rank in awards:
                wp = awards[rank]
                try:
                    await add_wave_points(uid, wp, reason=f"Weekly duty award (#{rank})")
                    awarded += 1
                    duty_results.setdefault(uid, {})['wp_earned'] = wp
                    ex = user_dm_extras.setdefault(uid, {'fields': [], 'color': None})
                    ex['color'] = discord.Color.gold()
                    ex['fields'].append(("Wave Points Awarded", f"**+{wp}** WP (#{rank})", False))
                except Exception as e:
                    logger.error(f"  Error awarding WP to {data['name']}: {e}")
        logger.info(f"  Wave Points: {awarded} awarded")

        # Step 5: Bad performance penalties
        logger.info(f"  Checking Bad penalties...")
        pen_count = role_rm_count = 0
        PENALTY = REQ_BAD_PENALTY
        for uid, data in staff_with_duty.items():
            cnt = data[duty_type]
            ri = get_performance_rank(cnt, duty_type, "Full Week")
            if not ri['rank'].startswith('\u274c') or uid in immune_users or check_if_user_is_away(bot, uid):
                continue
            try:
                wp_bal = await get_wave_points(uid)
                if wp_bal < PENALTY:
                    rm = await remove_role_in_guilds(bot, uid, duty_type)
                    if rm:
                        role_rm_count += 1
                        duty_results.setdefault(uid, {})['role_removed'] = True
                        ex = user_dm_extras.setdefault(uid, {'fields': [], 'color': None})
                        ex['color'] = discord.Color.red()
                        ex['fields'].append(("Role Removed", f"Insufficient WP ({wp_bal}/{PENALTY}).", False))
                else:
                    await add_wave_points(uid, -PENALTY, reason="Weekly strike penalty")
                    pen_count += 1
                    duty_results.setdefault(uid, {})['penalty_amount'] = PENALTY
                    ex = user_dm_extras.setdefault(uid, {'fields': [], 'color': None})
                    ex['color'] = discord.Color.orange()
                    ex['fields'].append(("Penalty", f"**{PENALTY} WP** deducted. Role kept.", False))
                await asyncio.sleep(RATE_LIMIT_DELAY)
            except Exception as e:
                logger.error(f"  Penalty error for {data['name']}: {e}")
        logger.info(f"  Penalties: {pen_count} deducted, {role_rm_count} roles removed")

        # Step 6: Combined results DM
        logger.info(f"  Sending results DMs...")
        rc = {'\U0001f31f': discord.Color.gold(), '\u2b50': discord.Color.blue(),
              '\u2705': discord.Color.green(), '\u26a0\ufe0f': discord.Color.orange(),
              '\u274c': discord.Color.red()}
        sp = sorted(staff_with_duty.items(), key=lambda x: x[1][duty_type], reverse=True)
        pm = {u: p+1 for p, (u, _) in enumerate(sp)}
        ts = len(staff_with_duty)
        ds = df = 0
        for uid, data in staff_with_duty.items():
            if uid in immune_users:
                continue
            cnt = data[duty_type]
            ri = get_performance_rank(cnt, duty_type, period)
            ex = user_dm_extras.get(uid, {})
            col = ex.get('color') or rc.get(ri['emoji'], discord.Color.blurple())
            emb = discord.Embed(title=f"Weekly Results - {duty_names.get(duty_type, duty_type)}",
                                color=col, timestamp=datetime.now(timezone.utc))
            emb.add_field(name="Actions", value=f"**{cnt}**", inline=True)
            emb.add_field(name="Performance", value=ri['rank'], inline=True)
            emb.add_field(name="Position", value=f"**#{pm[uid]}** of {ts}", inline=True)
            if ri['message']:
                emb.add_field(name="Note", value=ri['message'], inline=False)
            for fn, fv, fi in ex.get('fields', []):
                emb.add_field(name=fn, value=fv, inline=fi)
            emb.set_footer(text="Weekly performance summary")
            try:
                u = await bot.fetch_user(uid)
                await u.send(embed=emb)
                ds += 1
            except discord.Forbidden:
                df += 1
            except Exception:
                df += 1
            await asyncio.sleep(RATE_LIMIT_DELAY)
        logger.info(f"  DMs: {ds} sent, {df} failed")

    logger.info(f"{emoji} {duty_type.upper()} DUTY COMPLETE!")
    return staff_with_duty, duty_results if period == "Full Week" else {}


# ==================== HUB JSON AUGMENTATION ====================

async def _augment_duties_hub_json(all_duty_results: dict, start_date: str, end_date: str):
    """Overlay WP/penalty/role_removed into duties.json after awards."""
    import os as _os
    from tasks.staff_hub_writer import push_duties_to_github
    hub_path = _os.path.join(_os.path.dirname(__file__), '..', 'website', 'data', 'duties.json')
    try:
        with open(hub_path, 'r', encoding='utf-8') as _f:
            payload = json.load(_f)
    except Exception as _e:
        logger.warning(f"  Could not read duties.json: {_e}")
        return
    users = payload.get('users', {})
    updated = 0
    for dt, results in all_duty_results.items():
        for uid, outcome in results.items():
            us = str(uid)
            if us not in users:
                continue
            duties = users[us].get('duties', {})
            if dt not in duties:
                continue
            d = duties[dt]
            d['wp_earned'] = outcome.get('wp_earned', 0)
            d['penalty_amount'] = outcome.get('penalty_amount', 0)
            d['role_removed'] = outcome.get('role_removed', False)
            updated += 1
    payload['_meta']['last_updated'] = datetime.now(timezone.utc).isoformat()
    payload['_meta']['end_date'] = end_date
    await push_duties_to_github(payload)
    logger.info(f"  Hub augmented ({updated} entries)")


# ==================== ROLE ASSIGNMENT SCANNING (folded into hourly) ====================

async def _scan_role_assignments(bot):
    """One-pass role assignment scan (replaces old 30-min monitor loop)."""
    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        for role in guild.roles:
            if role.name.lower() == "map request helper":
                for member in role.members:
                    if member.bot:
                        continue
                    ad = await database.get_role_assignment_date(member.id, 'req')
                    if not ad:
                        await database.log_role_assignment(member.id, 'req')
                        logger.info(f"  Logged new req role assignment: {member.name}")

# Backward-compatible alias for shim re-export
monitor_role_assignments = _scan_role_assignments


# ==================== LEGACY EXPORT ====================

async def collect_staff_data_with_progress(bot, guild_ids, start_datetime, end_datetime, progress_message=None):
    """Legacy function for manual force commands."""
    logger.info("Manual data collection - processing all duties sequentially...")
    all_data = {}
    for duty_type in ['req']:
        duty_data, _ = await process_single_duty(
            bot=bot, duty_type=duty_type, guild_ids=guild_ids,
            start_datetime=start_datetime, end_datetime=end_datetime,
            period="Manual", start_date="N/A", end_date="N/A",
            progress_message=progress_message)
        for uid, data in duty_data.items():
            if uid not in all_data:
                all_data[uid] = {'name': data['name'], 'req': 0}
            all_data[uid][duty_type] = data.get(duty_type, 0)
    return all_data

collect_staff_data = collect_staff_data_with_progress


# ==================== FAST HUB REFRESH (DB cache, no channel scans) ====================

def _duties_json_path():
    return os.path.join(os.path.dirname(__file__), '..', 'website', 'data', 'duties.json')


def _duties_json_week() -> tuple:
    """Return (start_date, end_date) from the on-disk duties.json, or ('', '')."""
    try:
        with open(_duties_json_path(), 'r', encoding='utf-8') as f:
            meta = json.load(f).get('_meta', {})
        return meta.get('start_date', ''), meta.get('end_date', '')
    except Exception:
        return '', ''


def _member_display_name(bot, uid: int, source_guilds: list, fallback: str) -> str:
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        member = guild.get_member(uid)
        if member:
            return member.display_name
    return fallback


def _member_avatar_url(bot, uid: int, source_guilds: list, fallback=None):
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        member = guild.get_member(uid)
        if member and member.display_avatar:
            return web_avatar_url(member.display_avatar)
    return fallback


async def refresh_duties_hub_from_cache(bot) -> bool:
    """Rebuild duties.json from DB cache + in-memory guild members. Seconds, not minutes."""
    start_date, end_date = get_global_dates_from_config()
    if not start_date or not end_date:
        logger.warning("refresh_duties_hub_from_cache: no week dates in config")
        return False

    auto_config = get_automation_config()
    source_guilds = auto_config.get('source_guilds', [])
    if not source_guilds:
        logger.warning("refresh_duties_hub_from_cache: no source guilds")
        return False

    cached = await database.get_cached_week_stats(start_date, end_date)
    existing_users = {}
    try:
        with open(_duties_json_path(), 'r', encoding='utf-8') as f:
            existing_users = json.load(f).get('users', {})
    except Exception:
        pass

    all_stats = {'req': {}, 'modlog': {}, 'message': {}, 'reviews': {}}
    all_display = {'req': {}, 'modlog': {}, 'message': {}}

    for check_type in ('req', 'modlog', 'message'):
        for uid_str, data in cached.get(check_type, {}).items():
            uid = int(uid_str)
            if isinstance(data, dict):
                all_stats[check_type][uid] = data
            else:
                all_stats[check_type][uid] = {'count': int(data or 0)}

    general_staff_ids: set = set()
    all_uids: set = set()
    guilds_live = any(bot.get_guild(gid) for gid in source_guilds)

    if guilds_live:
        for guild_id in source_guilds:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            general_staff_ids.update(int(u) for u in find_general_staff(guild))
            all_uids.update(general_staff_ids)
            req_staff = find_staff_for_duty(guild, 'req')
            all_uids.update(req_staff.keys())
            all_display['req'].update(req_staff)
    else:
        # Bot not connected (CLI refresh) — roster from last duties.json + cache.
        for uid_str, row in existing_users.items():
            uid = int(uid_str)
            all_uids.add(uid)
            if row.get('engagement') is not None:
                general_staff_ids.add(uid)
            if row.get('duties'):
                general_staff_ids.add(uid)
            name = row.get('name', f'User {uid}')
            if row.get('duties', {}).get('req') is not None:
                all_display['req'][uid] = name
            if row.get('engagement') is not None:
                all_display['message'][uid] = name
                all_display['modlog'][uid] = name

    for check_type in ('req', 'modlog', 'message'):
        all_uids.update(all_stats[check_type].keys())
        for uid in all_stats[check_type]:
            all_uids.add(int(uid))
            if check_type == 'message' or check_type == 'modlog':
                general_staff_ids.add(int(uid))

    av_cache = {}
    for uid in all_uids:
        fallback_name = existing_users.get(str(uid), {}).get('name', f'User {uid}')
        name = _member_display_name(bot, uid, source_guilds, fallback_name) if guilds_live else fallback_name
        for check_type in ('req', 'modlog', 'message'):
            if uid in all_stats[check_type]:
                all_display[check_type][uid] = name
        av_cache[uid] = (
            _member_avatar_url(bot, uid, source_guilds, existing_users.get(str(uid), {}).get('avatar_url'))
            if guilds_live
            else existing_users.get(str(uid), {}).get('avatar_url')
        )

    start_dt = get_start_datetime(start_date)
    end_dt = get_end_datetime(end_date)
    all_stats['reviews'] = await scan_reviews_extended(start_dt, end_dt)

    hp = _build_unified_hub_payload(
        bot, all_stats, all_display, av_cache,
        general_staff_ids, source_guilds, start_date, end_date,
    )

    # Headless: preserve away/role metadata the live guild cache would have supplied.
    if not guilds_live:
        for uid_str, row in hp.get('users', {}).items():
            prev = existing_users.get(uid_str, {})
            for key in ('is_away', 'away_type', 'top_role', 'role_tier', 'has_staff_role', 'name', 'avatar_url'):
                if prev.get(key) is not None:
                    row[key] = prev[key]

    from tasks.staff_hub_writer import push_duties_to_github
    await push_duties_to_github(hp)
    logger.info(
        f"Fast duties hub refresh: {start_date} -> {end_date} "
        f"({len(hp.get('users', {}))} users, DB cache — no channel scan)"
    )
    return True


async def sync_duties_week_if_stale(bot) -> bool:
    """If config week != duties.json week, rewrite hub payload immediately."""
    cfg_start, cfg_end = get_global_dates_from_config()
    if not cfg_start:
        return False
    json_start, _ = _duties_json_week()
    if json_start == cfg_start:
        return False
    logger.info(f"Duties week stale ({json_start!r} != {cfg_start!r}) — fast cache refresh")
    return await refresh_duties_hub_from_cache(bot)


# ==================== PERFORM FULL SCAN (exported for automation_config) ====================

async def perform_full_scan(bot):
    """Full duty scan: req -> modlog -> message -> reviews -> export to hub."""
    try:
        rate_limit_tracker.reset()
        logger.info("\n" + "=" * 60)
        logger.info("STARTING FULL DUTY SCAN")
        logger.info("=" * 60)
        auto_config = get_automation_config()
        source_guilds = auto_config.get('source_guilds', [])
        if not source_guilds:
            logger.warning("No source guilds configured")
            return
        with open('config.json', 'r') as f:
            config = json.load(f)
        gd = config.get('global_dates', {})
        start_date, end_date = gd.get('start_date'), gd.get('end_date')
        if not start_date or not end_date:
            logger.warning("No global dates configured")
            return
        start_dt = get_start_datetime(start_date)
        end_dt = get_end_datetime(end_date)
        logger.info(f"Scan period: {start_date} -> {end_date}")

        all_staff_union = {}
        all_stats = {}
        all_display = {}

        # 1. REQ
        rc, rd = await scan_duty_all_guilds(bot, 'req', source_guilds, start_dt, end_dt, start_date, end_date)
        all_stats['req'] = rc
        all_display['req'] = rd
        all_staff_union.update(rd)
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # General staff
        general_staff_ids = set()
        for gid in source_guilds:
            g = bot.get_guild(gid)
            if not g:
                continue
            gen = find_general_staff(g)
            general_staff_ids.update(int(u) for u in gen)
            all_staff_union.update(gen)

        # 2. MODLOG
        mc, md = await scan_modlog_all_guilds(bot, all_staff_union, source_guilds, start_dt, end_dt, start_date, end_date)
        all_stats['modlog'] = mc
        all_display['modlog'] = md
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # 3. MESSAGES
        msgc, msgd = await scan_messages_all_guilds_optimized(bot, all_staff_union, source_guilds, start_dt, end_dt, start_date, end_date)
        all_stats['message'] = msgc
        all_display['message'] = msgd
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # 4. REVIEWS
        all_stats['reviews'] = await scan_reviews_extended(start_dt, end_dt)

        # Save + push hub
        try:
            import os as _os
            dd = {'_meta': {'start_date': start_date, 'end_date': end_date,
                            'last_updated': datetime.now(timezone.utc).isoformat()}}
            existing = {}
            try:
                ep = _os.path.join(_os.path.dirname(__file__), '..', 'json_data', 'duties_totals.json')
                if _os.path.exists(ep):
                    with open(ep, 'r') as ef:
                        existing = json.load(ef)
            except Exception:
                pass
            # Avatar pre-fetch
            all_uids = set()
            for dt in ['req', 'modlog', 'message']:
                all_uids |= set(all_stats.get(dt, {}).keys()) | set(all_display.get(dt, {}).keys())
            av_cache = {}
            for uid in all_uids:
                try:
                    u = await bot.fetch_user(int(uid))
                    raw = str(u.display_avatar.url) if u and u.display_avatar else None
                    av_cache[int(uid)] = web_avatar_url(u.display_avatar) if u and u.display_avatar else None
                except Exception:
                    av_cache[int(uid)] = None
                await asyncio.sleep(0.5)
            for dt in ['req', 'modlog', 'message']:
                dd[dt] = {}
                stats = all_stats.get(dt, {})
                members = all_display.get(dt, {})
                uids = set(stats.keys()) | set(members.keys())
                for uid in uids:
                    dwa = 0
                    if dt == 'message' and isinstance(stats.get(uid), dict) and 'days' in stats.get(uid, {}):
                        dl = stats[uid].get('days', [])
                        ds2 = set()
                        for d in dl:
                            try:
                                ds2.add(datetime.fromisoformat(d).date().weekday() if isinstance(d, str) else d)
                            except Exception:
                                pass
                        dwa = len(ds2)
                    cnt = stats.get(uid, 0)
                    if isinstance(cnt, dict):
                        cnt = cnt.get('count', 0)
                    raw_cnt = cnt
                    ee = existing.get(dt, {}).get(str(uid), {})
                    is_ov = ee.get('is_override', False)
                    div = ee.get('divisor', 1)
                    if is_ov:
                        cnt = ee.get('count', 0)
                    elif div and div > 1:
                        cnt = max(0, cnt // div)
                    entry = {'name': members.get(uid, f'User {uid}'), 'count': cnt, 'uid': uid}
                    if is_ov:
                        entry['is_override'] = True
                        entry['raw_count'] = raw_cnt
                    if div and div > 1:
                        entry['divisor'] = div
                        if not is_ov:
                            entry['raw_count'] = raw_cnt
                    if dt == 'message' and dwa > 0:
                        entry['days_of_week_active'] = dwa
                    if check_if_user_is_away(bot, uid):
                        entry['away'] = 'normal' if is_user_normal_away(bot, uid) else 'away_immunity'
                    entry['avatar_url'] = av_cache.get(int(uid))
                    dd[dt][str(uid)] = entry
            jp = _os.path.join(_os.path.dirname(__file__), '..', 'json_data', 'duties_totals.json')
            with open(jp, 'w') as f:
                json.dump(dd, f, indent=2)
            logger.info("  Saved duties_totals.json")
            try:
                from tasks.staff_hub_writer import push_duties_to_github
                hp = _build_unified_hub_payload(bot, all_stats, all_display, av_cache,
                                                general_staff_ids, source_guilds, start_date, end_date)
                await push_duties_to_github(hp)
                logger.info(f"  Hub pushed ({len(hp.get('users', {}))} users)")
            except Exception as pe:
                logger.warning(f"  Hub push failed: {pe}")
        except Exception as e:
            logger.error(f"  Failed to save duties: {e}")

        # Challenges
        try:
            from tasks.random_challenges import check_and_complete_challenges
            await check_and_complete_challenges(bot, all_stats)
        except Exception as e:
            logger.error(f"  Challenge error: {e}")

        logger.info("FULL DUTY SCAN COMPLETE")
    except Exception as e:
        logger.error(f"Error in perform_full_scan: {e}")
        import traceback
        logger.error(traceback.format_exc())


# ==================== UNIFIED HOURLY TICK ====================

async def unified_tick(bot):
    """One hourly tick: check week lifecycle, run scan, fire awards at hour 168."""
    global _current_week_start, _awards_done, _last_scan_time

    try:
        start_date, end_date = get_global_dates_from_config()
        if not start_date or not end_date:
            return

        start_dt = get_start_datetime(start_date)
        end_dt = get_end_datetime(end_date)
        now = datetime.now(timezone.utc)
        hours_elapsed = (now - start_dt).total_seconds() / 3600

        # New week detection
        if start_date != _current_week_start:
            # On a real rollover (not first boot), archive the week currently in
            # duties.json into weeks[] BEFORE the new week's data overwrites it,
            # so the website's past-weeks dropdown keeps the completed week.
            if _current_week_start is not None:
                _snapshot_completed_week()
            _current_week_start = start_date
            _awards_done = False
            _last_scan_time = None
            logger.info(f"New week detected: {start_date} -> {end_date}")
            try:
                await refresh_duties_hub_from_cache(bot)
            except Exception as e:
                logger.warning(f"  Fast hub refresh on new week failed: {e}")

        # Role assignment scan (folded from old 30-min loop)
        await _scan_role_assignments(bot)

        auto_config = get_automation_config()
        source_guilds = auto_config.get('source_guilds', [])
        if not source_guilds:
            return

        # Find all staff
        all_staff = {}
        for guild_id in source_guilds:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            all_staff.update(find_general_staff(guild))
            all_staff.update(find_staff_for_duty(guild, 'req'))

        if not all_staff:
            return

        # Scan: incremental messages if we have a baseline, otherwise full
        if _last_scan_time is not None:
            msg_counts, msg_display = await scan_messages_incremental(
                bot, all_staff, source_guilds, _last_scan_time, now, start_date, end_date)
        else:
            msg_counts, msg_display = await scan_messages_all_guilds_optimized(
                bot, all_staff, source_guilds, start_dt, end_dt, start_date, end_date)

        # Req + modlog + reviews always full (cheap)
        req_counts, req_display = await scan_duty_all_guilds(
            bot, 'req', source_guilds, start_dt, end_dt, start_date, end_date)
        modlog_counts, modlog_display = await scan_modlog_all_guilds(
            bot, all_staff, source_guilds, start_dt, end_dt, start_date, end_date)
        review_counts = await scan_reviews_extended(start_dt, end_dt)
        role_add_counts = await scan_role_adds_all_staff(bot, all_staff, source_guilds, start_dt, end_dt)
        combined_reviews = {
            uid: {'count': review_counts.get(uid, {}).get('count', 0) + role_add_counts.get(uid, 0)}
            for uid in all_staff.keys()
        }

        _last_scan_time = now

        # Build + push hub payload
        general_staff_ids = set()
        for guild_id in source_guilds:
            guild = bot.get_guild(guild_id)
            if guild:
                general_staff_ids.update(int(u) for u in find_general_staff(guild))

        all_stats = {'req': req_counts, 'modlog': modlog_counts,
                     'message': msg_counts, 'reviews': combined_reviews}
        all_display = {'req': req_display, 'modlog': modlog_display, 'message': msg_display}

        try:
            av_cache = {}
            for uid in set(all_staff.keys()):
                try:
                    u = await bot.fetch_user(int(uid))
                    raw = str(u.display_avatar.url) if u and u.display_avatar else None
                    av_cache[int(uid)] = web_avatar_url(u.display_avatar) if u and u.display_avatar else None
                except Exception:
                    av_cache[int(uid)] = None
                await asyncio.sleep(0.3)
            hp = _build_unified_hub_payload(
                bot, all_stats, all_display, av_cache,
                general_staff_ids, source_guilds, start_date, end_date)
            from tasks.staff_hub_writer import push_duties_to_github
            await push_duties_to_github(hp)
        except Exception as e:
            logger.warning(f"  Hourly hub push failed: {e}")

        # Challenge completions
        try:
            from tasks.random_challenges import check_and_complete_challenges
            await check_and_complete_challenges(bot, all_stats)
        except Exception as e:
            logger.debug(f"  Challenge check: {e}")

        # Awards fire once at hour 168
        if hours_elapsed >= 168 and not _awards_done:
            if not await database.check_report_already_sent(
                    REPORT_GUILD_ID, 'req', 'unified_weekly', start_date, end_date):
                logger.info("Hour 168 reached - running awards phase")

                # Final full scan to lock data
                await perform_full_scan(bot)

                # Process req duty awards
                all_duty_results = {}
                try:
                    _, dr = await process_single_duty(
                        bot, 'req', SOURCE_GUILDS, start_dt, end_dt,
                        "Full Week", start_date, end_date)
                    if dr:
                        all_duty_results['req'] = dr
                except Exception as e:
                    logger.error(f"  Awards phase error: {e}")

                # Augment hub with award outcomes
                if all_duty_results:
                    try:
                        await _augment_duties_hub_json(all_duty_results, start_date, end_date)
                    except Exception as e:
                        logger.error(f"  Hub augmentation error: {e}")

                # Rank-100 engagement reward: 30 WP + DM
                try:
                    from tasks.wave_points import add_wave_points
                    hp2 = _build_unified_hub_payload(
                        bot, all_stats, all_display, {},
                        general_staff_ids, source_guilds, start_date, end_date)
                    r100_count = 0
                    for uid_str, entry in hp2.get('users', {}).items():
                        eng = entry.get('engagement', {})
                        if eng.get('rank_total') == 100:
                            uid = int(uid_str)
                            if check_if_user_is_away(bot, uid):
                                continue
                            try:
                                await add_wave_points(uid, 30, reason="Engagement bonus (rank total 100)")
                                r100_count += 1
                                try:
                                    user = await bot.fetch_user(uid)
                                    variations = [
                                        {
                                            "title": "🏆 ELITE CONTRIBUTOR",
                                            "description": "You've reached Rank 100 this week—top tier status unlocked.\n**+30 WP** earned for your dominance."
                                        },
                                        {
                                            "title": "🔥 PEAK PERFORMANCE",
                                            "description": "Rank 100! You're absolutely crushing it this week.\n**+30 WP** as recognition for the elite activity."
                                        },
                                        {
                                            "title": "⭐ LEGENDARY WEEK",
                                            "description": "You hit Rank 100—that's rare air.\n**+30 WP** awarded for reaching the summit."
                                        }
                                    ]
                                    variant = variations[uid % 3]
                                    emb = discord.Embed(
                                        title=variant["title"],
                                        description=variant["description"],
                                        color=discord.Color.gold(),
                                        timestamp=datetime.now(timezone.utc))
                                    await user.send(embed=emb)
                                except Exception:
                                    pass
                            except Exception as e:
                                logger.error(f"  Rank-100 reward error for {uid}: {e}")
                    logger.info(f"  Rank-100 rewards: {r100_count} awarded")
                except Exception as e:
                    logger.error(f"  Rank-100 phase error: {e}")

                # Lifetime accumulation + staff_insights_history + lifetime.json
                try:
                    await _accumulate_lifetime(all_stats, general_staff_ids, start_date)
                    await _build_and_write_lifetime_json(bot, source_guilds)
                except Exception as e:
                    logger.error(f"  Lifetime accumulation error: {e}")

                await database.mark_report_sent(
                    REPORT_GUILD_ID, 'req', 'unified_weekly', start_date, end_date)
                _awards_done = True
                logger.info("Awards phase complete")

                # Archive the just-finished week (with final awards now in
                # duties.json) into weeks[] BEFORE advancing — robust against a
                # restart between the roll and the next tick. Idempotent (dedups
                # by start_date), so the new-week-detection snapshot is harmless.
                try:
                    _snapshot_completed_week()
                except Exception as e:
                    logger.error(f"  Week snapshot (pre-advance) failed: {e}")

                # ── Auto-advance the week (LAST step, only after this week is
                # fully processed + marked sent, so no data is ever lost) ──────
                try:
                    _advance_week_in_config(start_date, end_date)
                except Exception as e:
                    logger.error(f"  Week auto-advance failed: {e}")

    except Exception as e:
        logger.error(f"Error in unified_tick: {e}")
        import traceback
        logger.error(traceback.format_exc())


# ==================== WEEK AUTO-ADVANCE ====================

def _advance_week_in_config(old_start: str, old_end: str):
    """
    Roll config.json forward to the next week: new start = old end,
    new end = old end + 7 days (DD/MM/YYYY). Updates both `global_dates` and the
    legacy `global` block. Called ONLY as the final step of the hour-168 awards
    phase, after the week is fully scanned, awarded, accumulated, and marked sent
    — so a late run never loses data, and the report marker prevents double-runs.
    """
    old_end_dt = datetime.strptime(old_end, '%d/%m/%Y')
    new_start = old_end_dt.strftime('%d/%m/%Y')
    new_end = (old_end_dt + timedelta(days=7)).strftime('%d/%m/%Y')

    with open('config.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    for key in ('global_dates', 'global'):
        if isinstance(cfg.get(key), dict):
            cfg[key]['start_date'] = new_start
            cfg[key]['end_date'] = new_end

    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    logger.info(f"📅 Week auto-advanced: {old_start}→{old_end}  ⟶  {new_start}→{new_end}")


# ==================== HOURLY LOOP ====================

async def unified_hourly_loop(bot):
    """Run unified_tick every hour on the hour."""
    await bot.wait_until_ready()
    logger.info("Unified weekly loop active and waiting for hour marks")

    # Build lifetime.json once on startup so the DB baseline renders immediately
    # (otherwise the Lifetime tab/profile stay empty until the next hour-168).
    try:
        with open('config.json', 'r') as _f:
            _cfg = json.load(_f)
        _sg = _cfg.get('automated_checks', {}).get('source_guilds', [])
        if _sg:
            await _build_and_write_lifetime_json(bot, _sg)
            logger.info("Startup lifetime.json build complete")
    except Exception as e:
        logger.warning(f"Startup lifetime.json build failed: {e}")

    # If config week advanced but duties.json is still on the old week, fix the
    # hub label + counts from DB cache now (don't wait up to 60 min for :00 tick).
    try:
        if await sync_duties_week_if_stale(bot):
            global _current_week_start
            _current_week_start, _ = get_global_dates_from_config()
    except Exception as e:
        logger.warning(f"Startup duties week sync failed: {e}")

    while True:
        try:
            now = datetime.now(timezone.utc)
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            wait_secs = (next_hour - now).total_seconds()
            logger.info(f"Next hourly tick: {next_hour} UTC (in {wait_secs/60:.0f}min)")
            await asyncio.sleep(wait_secs)
            logger.info(f"Running hourly tick at {datetime.now(timezone.utc)}")
            await unified_tick(bot)
        except asyncio.CancelledError:
            logger.info("Unified hourly loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in hourly loop: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await asyncio.sleep(300)


# ==================== COG ====================

class UnifiedWeeklyLoop(commands.Cog):
    """Unified hourly scan + 168h awards. Replaces duties_scan + weekly_checks."""

    def __init__(self, bot):
        self.bot = bot
        self.task = None

    async def cog_load(self):
        logger.info("Starting Unified Weekly Loop...")
        self.task = asyncio.create_task(unified_hourly_loop(self.bot))
        logger.info("Unified weekly loop task created")

    def cog_unload(self):
        if self.task:
            self.task.cancel()
        logger.info("Unified weekly loop stopped")


async def setup(bot):
    await bot.add_cog(UnifiedWeeklyLoop(bot))
    logger.info("Unified Weekly Loop cog loaded")
