"""
Power Hour - tasks/power_hour.py

A random special event that has a 5% chance of triggering at the start of each hour.
Each hour is evaluated independently — the bot rolls at the top of every hour.

Source guilds:
    988564962802810961
    971731167621574666

Announcement channel:
    1474715327974609117

How it works:
    • Every hour, at :00, the bot rolls a 5% chance
    • If triggered, Power Hour is active for exactly 1 hour
    • During that hour, activity is tracked in a temporary DB table
    • At the end of the hour, Wave Points are awarded and the table is cleared

Earning Wave Points during Power Hour:
    • Messages    — every 10 messages in either source guild   = +1 Wave Point
    • Role duties — every 5 role assignments in either guild   = +1 Wave Point
    • Requests    — every 1 request completed in either guild  = +1 Wave Point

Points are awarded ALL AT ONCE at the end of the hour, then the table is wiped.

Admin command:
    >powerhour   — manually force-trigger a Power Hour right now (Management/007/+)
"""

import asyncio
import math
import random
import logging
import re
import json
import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Set

import database
from core.helpers import get_readable_text_channels, safe_history_fetch, extract_embed_content, is_reply_to_other
from core.cache import config_cache
from tasks.wave_points import add_wave_points

logger = logging.getLogger('discord')

# One lock shared across all scheduler instances (e.g. after a session invalidation
# that causes the cog to reload). Only one coroutine can execute the roll block at
# a time — the rest will wait, then see hour_key already set and skip cleanly.
_roll_lock = asyncio.Lock()

# ==================== CONSTANTS ====================

SOURCE_GUILDS      = [988564962802810961, 971731167621574666]
ANNOUNCE_CHANNEL   = 1474715327974609117

TRIGGER_CHANCE      = 0.05   # 5% per hour (off-peak)
PEAK_TRIGGER_CHANCE = 0.10   # 10% per hour (peak window 13:00-21:00 UTC)
PEAK_HOUR_START     = 13     # 13:00 UTC inclusive
PEAK_HOUR_END       = 21     # 21:00 UTC exclusive (last peak roll at 20:00)
DURATION_SECONDS    = 3600   # 1 hour
DOUBLE_CHANCE       = 0.50   # 50% chance of being a Double Power Hour (2× points)


def get_trigger_chance(hour_utc=None):
    """
    Return the Power Hour trigger probability for the given UTC hour.
      Peak window  13:00 - 20:59 UTC  ->  20%
      Off-peak     all other hours    ->   5%
    If hour_utc is None the current UTC hour is used.
    """
    if hour_utc is None:
        hour_utc = datetime.now(timezone.utc).hour
    return PEAK_TRIGGER_CHANCE if PEAK_HOUR_START <= hour_utc < PEAK_HOUR_END else TRIGGER_CHANCE

# Thresholds per duty type to earn 1 Wave Point
MSG_PER_POINT      = 10
MSG_POINTS_MAX     = 50  # cap on points earned from messages in a single session
ROLE_PER_POINT     = 5
REQ_PER_POINT      = 1      # 1 request = 1 point
MOD_PER_POINT      = 2      # every 2 mod commands = 1 point

RATE_LIMIT_DELAY           = 0.5
DELAY_BETWEEN_CHANNELS     = 0.5
DELAY_BETWEEN_GUILDS       = 2.0
DELAY_BETWEEN_DUTIES       = 1.5

# Identifier used to find/match the pinned info message
INFO_MESSAGE_MARKER        = "⚡ POWER HOUR — HOW IT WORKS"


async def _get_announce_channel(bot):
    """Return the announce channel, falling back to fetch if not in cache yet."""
    channel = bot.get_channel(ANNOUNCE_CHANNEL)
    if channel:
        return channel
    try:
        channel = await bot.fetch_channel(ANNOUNCE_CHANNEL)
        return channel
    except Exception as e:
        logger.error(f"❌ Could not fetch Power Hour announce channel {ANNOUNCE_CHANNEL}: {e}")
        return None


# ==================== DATABASE ====================

async def init_power_hour_tables():
    """Create the power_hour_state and power_hour_activity tables."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        # Tracks whether a Power Hour is currently active / has fired this hour
        await db.execute('''
            CREATE TABLE IF NOT EXISTS power_hour_state (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                active             INTEGER DEFAULT 0,
                hour_key           TEXT,
                start_time         TEXT,
                end_time           TEXT,
                is_double          INTEGER DEFAULT 0,
                status_message_id  INTEGER DEFAULT NULL,
                start_message_id   INTEGER DEFAULT NULL,
                end_message_id     INTEGER DEFAULT NULL
            )
        ''')
        # Temp accumulator — wiped after each Power Hour ends
        await db.execute('''
            CREATE TABLE IF NOT EXISTS power_hour_activity (
                user_id      INTEGER PRIMARY KEY,
                messages     INTEGER DEFAULT 0,
                roles        INTEGER DEFAULT 0,
                requests     INTEGER DEFAULT 0,
                mod_commands INTEGER DEFAULT 0
            )
        ''')
        # Migration: add mod_commands if missing from older DB
        try:
            await db.execute('ALTER TABLE power_hour_activity ADD COLUMN mod_commands INTEGER DEFAULT 0')
            logger.info("✅ Migrated power_hour_activity: added mod_commands column")
        except Exception:
            pass  # Column already exists
        # Migration: add status_message_id if missing from older DB
        try:
            await db.execute('ALTER TABLE power_hour_state ADD COLUMN status_message_id INTEGER DEFAULT NULL')
            logger.info("✅ Migrated power_hour_state: added status_message_id column")
        except Exception:
            pass  # Column already exists
        # Migration: add start_message_id if missing from older DB
        try:
            await db.execute('ALTER TABLE power_hour_state ADD COLUMN start_message_id INTEGER DEFAULT NULL')
            logger.info("✅ Migrated power_hour_state: added start_message_id column")
        except Exception:
            pass  # Column already exists
        # Migration: add end_message_id if missing from older DB
        try:
            await db.execute('ALTER TABLE power_hour_state ADD COLUMN end_message_id INTEGER DEFAULT NULL')
            logger.info("✅ Migrated power_hour_state: added end_message_id column")
        except Exception:
            pass  # Column already exists
        # Migration: add is_double if missing from older DB
        try:
            await db.execute('ALTER TABLE power_hour_state ADD COLUMN is_double INTEGER DEFAULT 0')
            logger.info("✅ Migrated power_hour_state: added is_double column")
        except Exception:
            pass  # Column already exists
        for col, typedef in (
            ('last_roll', 'REAL'),
            ('last_roll_chance', 'REAL'),
            ('last_roll_triggered', 'INTEGER DEFAULT 0'),
            ('last_roll_at', 'TEXT'),
            ('last_roll_is_double', 'INTEGER DEFAULT 0'),
            ('last_roll_hour_key', 'TEXT'),
        ):
            try:
                await db.execute(f'ALTER TABLE power_hour_state ADD COLUMN {col} {typedef}')
                logger.info(f"✅ Migrated power_hour_state: added {col} column")
            except Exception:
                pass

        # Ensure the single-row state record exists
        await db.execute('''
            INSERT OR IGNORE INTO power_hour_state (id, active, hour_key, start_time, end_time, status_message_id)
            VALUES (1, 0, NULL, NULL, NULL, NULL)
        ''')
        await db.commit()
    logger.info("✅ Power Hour tables initialised")


async def get_power_hour_state() -> dict:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('''
            SELECT active, hour_key, start_time, end_time, is_double,
                   last_roll, last_roll_chance, last_roll_triggered,
                   last_roll_at, last_roll_is_double, last_roll_hour_key
            FROM power_hour_state WHERE id = 1
        ''') as cur:
            row = await cur.fetchone()
    if not row:
        return {
            'active': False, 'hour_key': None, 'start_time': None, 'end_time': None,
            'is_double': False, 'last_roll': None, 'last_roll_chance': None,
            'last_roll_triggered': False, 'last_roll_at': None,
            'last_roll_is_double': False, 'last_roll_hour_key': None,
        }
    return {
        'active':              bool(row[0]),
        'hour_key':            row[1],
        'start_time':          row[2],
        'end_time':            row[3],
        'is_double':           bool(row[4]) if row[4] is not None else False,
        'last_roll':           row[5],
        'last_roll_chance':    row[6],
        'last_roll_triggered': bool(row[7]) if row[7] is not None else False,
        'last_roll_at':        row[8],
        'last_roll_is_double': bool(row[9]) if row[9] is not None else False,
        'last_roll_hour_key':  row[10],
    }


async def save_last_roll(roll: float, chance: float, triggered: bool, hour_key: str,
                         is_double: bool = False):
    """Persist the latest hourly roll result for the events page."""
    pool = await database.get_pool()
    now = datetime.now(timezone.utc).isoformat()
    async with pool.acquire() as db:
        await db.execute('''
            UPDATE power_hour_state SET
                last_roll=?, last_roll_chance=?, last_roll_triggered=?,
                last_roll_at=?, last_roll_is_double=?, last_roll_hour_key=?
            WHERE id=1
        ''', (roll, chance, 1 if triggered else 0, now, 1 if is_double else 0, hour_key))
        await db.commit()


async def update_last_roll_is_double(is_double: bool):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE power_hour_state SET last_roll_is_double=? WHERE id=1',
            (1 if is_double else 0,)
        )
        await db.commit()


async def set_power_hour_active(start: datetime, end: datetime, hour_key: str, is_double: bool = False):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        # active=1 and hour_key are already written by the scheduler before
        # run_power_hour is spawned — we just fill in the timing details here.
        await db.execute(
            'UPDATE power_hour_state SET active=1, hour_key=?, start_time=?, end_time=?, is_double=? WHERE id=1',
            (hour_key, start.isoformat(), end.isoformat(), 1 if is_double else 0)
        )
        await db.commit()


async def set_power_hour_inactive():
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE power_hour_state SET active=0, start_time=NULL, end_time=NULL WHERE id=1'
        )
        await db.commit()


async def set_power_hour_cancelled():
    """
    Mark Power Hour as inactive AND corrupt hour_key to 'CANCELLED'.
    This ensures any sleeping run_power_hour task sees a key mismatch
    on wake-up and aborts instead of scanning/awarding points.
    """
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE power_hour_state SET active=0, hour_key=?, start_time=NULL, end_time=NULL WHERE id=1',
            ('CANCELLED',)
        )
        await db.commit()


# Public alias — lets external modules use the safe fetch-fallback helper
# without importing the private _get_announce_channel directly.
get_announce_channel = _get_announce_channel


async def clear_activity_table():
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('DELETE FROM power_hour_activity')
        await db.commit()


async def get_all_activity() -> list:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT user_id, messages, roles, requests, mod_commands FROM power_hour_activity') as cur:
            return await cur.fetchall()


async def get_status_message_id() -> int | None:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT status_message_id FROM power_hour_state WHERE id=1') as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def save_status_message_id(msg_id: int | None):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE power_hour_state SET status_message_id=? WHERE id=1',
            (msg_id,)
        )
        await db.commit()


async def get_start_message_id() -> int | None:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT start_message_id FROM power_hour_state WHERE id=1') as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def save_start_message_id(msg_id: int | None):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE power_hour_state SET start_message_id=? WHERE id=1',
            (msg_id,)
        )
        await db.commit()


async def get_end_message_id() -> int | None:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT end_message_id FROM power_hour_state WHERE id=1') as cur:
            row = await cur.fetchone()
    return row[0] if row and row[0] else None


async def save_end_message_id(msg_id: int | None):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE power_hour_state SET end_message_id=? WHERE id=1',
            (msg_id,)
        )
        await db.commit()


async def update_roll_status_message(bot, triggered: bool, roll: float, hour_key: str, is_double: bool = False):
    """
    Delete the previous roll status message and post a new one.
    Always exactly 1 message in the channel showing the latest roll result.
    """
    channel = await _get_announce_channel(bot)
    if not channel:
        return

    # Delete old status message if it exists
    old_msg_id = await get_status_message_id()
    if old_msg_id:
        try:
            old_msg = await channel.fetch_message(old_msg_id)
            await old_msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    now = datetime.now(timezone.utc)
    chance = get_trigger_chance(now.hour)
    peak_label = " • 🔥 **PEAK HOURS**" if chance == PEAK_TRIGGER_CHANCE else ""
    if triggered:
        double_label = " • ⚡⚡ **DOUBLE POWER HOUR!**" if is_double else ""
        content = (
            f"⚡ **Power Hour triggered!** Roll: `{roll:.4f}` (needed < `{chance}`){peak_label}{double_label} "
            f"— <t:{int(now.timestamp())}:t> UTC"
        )
    else:
        content = (
            f"🎲 **No Power Hour this hour.** Roll: `{roll:.4f}` (needed < `{chance}`){peak_label} "
            f"— <t:{int(now.timestamp())}:t> UTC"
        )

    try:
        msg = await channel.send(content)
        await save_status_message_id(msg.id)
    except Exception as e:
        logger.error(f"❌ Failed to send roll status message: {e}")


# ==================== INFO MESSAGE ====================

def _build_power_hour_info(bot=None) -> str:
    """Build the Power Hour info message content with real guild names if bot is available."""
    if bot:
        guild_names = [g.name for g in [bot.get_guild(gid) for gid in SOURCE_GUILDS] if g]
        servers_text = " & ".join(f"**{n}**" for n in guild_names) if guild_names else "**both Wave Management servers**"
    else:
        servers_text = "**both Wave Management servers**"

    return (
        f"# {INFO_MESSAGE_MARKER}\n\n"
        "A random event that rolls **every hour** — **10% chance** between 13:00–21:00 UTC, **5% chance** all other hours.\n"
        "When it fires, it lasts **exactly 1 hour** \u2014 then points are calculated and awarded.\n\n"
        "## \u26a1\u26a1 Double Power Hour\n"
        f"Every Power Hour has a **{int(DOUBLE_CHANCE*100)}% chance** to become a **Double Power Hour**, where all Wave Points earned are **2\u00d7**!\n"
        "Watch the announcement — the start embed will show `⚡⚡ DOUBLE POWER HOUR` if you're in luck.\n\n"
        "## \U0001f30a How to Earn Wave Points\n"
        f"\U0001f4e8 **Messages** \u2014 every **{MSG_PER_POINT} messages** sent in either server \u2192 **+1 Wave Point**\n"
        f"\U0001f5fa\ufe0f **Map Requests** \u2014 every **{REQ_PER_POINT} request** completed \u2192 **+1 Wave Point**\n"
        f"\U0001f6e1\ufe0f **Mod Commands** \u2014 every **{MOD_PER_POINT} mod commands** used \u2192 **+1 Wave Point**\n"
        f"*(All values above are **doubled** during a Double Power Hour)*\n\n"
        "## \u23f0 When Are Points Awarded?\n"
        "All points are calculated and awarded **at the end of the hour** in one go.\n"
        "You will NOT receive them mid-event \u2014 keep grinding until time is up!\n\n"
        "## \U0001f3b2 How Does It Trigger?\n"
        "Every hour at :00, the bot rolls for a chance to start.\n"
        f"**Peak hours (13:00–21:00 UTC):** `{int(PEAK_TRIGGER_CHANCE*100)}%` chance — **Off-peak:** `{int(TRIGGER_CHANCE*100)}%` chance\n"
        f"If triggered, there is then a **{int(DOUBLE_CHANCE*100)}% chance** it becomes a **Double Power Hour** (2\u00d7 points).\n"
        "Each hour is completely independent \u2014 missing one roll has no effect on the next.\n"
        "Watch this channel for the roll result every hour and for the \u26a1 event announcement.\n\n"
        "## \U0001f4e1 Active Servers\n"
        f"Activity is tracked across {servers_text} simultaneously.\n"
        "It does not matter which server you are active in \u2014 both count equally.\n\n"
        "## \u26a0\ufe0f Penalties\n"
        "Spamming or cheating will get you disqualified instantly and possibly removed from staff."
    )


# In-memory cache of the info message ID (same pattern as wave points shop)
_power_hour_info_message_id = None


async def auto_update_power_hour_info(bot):
    """
    Post or edit the Power Hour info message in the announce channel.
    Mirrors the exact pattern of auto_update_wave_points_shop in leaderboard_updater.py:
      1. If we have a cached message ID, try to fetch & edit it
      2. If not found, scan channel history for the marker
      3. If still not found, create a new message
    """
    global _power_hour_info_message_id

    try:
        channel = await _get_announce_channel(bot)
        if not channel:
            logger.error(f"❌ Power Hour info channel {ANNOUNCE_CHANNEL} not found")
            return False

        content = _build_power_hour_info(bot)

        # Step 1: try cached message ID
        if _power_hour_info_message_id:
            try:
                msg = await channel.fetch_message(_power_hour_info_message_id)
                await msg.edit(content=content)
                logger.info("✅ Power Hour info message updated (edited existing)")
                return True
            except discord.NotFound:
                _power_hour_info_message_id = None

        # Step 2: scan history for the marker
        async for msg in channel.history(limit=50):
            if msg.author.id == bot.user.id and INFO_MESSAGE_MARKER in msg.content:
                _power_hour_info_message_id = msg.id
                await msg.edit(content=content)
                logger.info("✅ Power Hour info message found and updated")
                return True

        # Step 3: create fresh
        msg = await channel.send(content)
        _power_hour_info_message_id = msg.id
        logger.info("✅ Power Hour info message created (new)")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to update Power Hour info message: {e}")
        return False


# ==================== SCAN HELPERS ====================

def find_staff_for_duty(guild: discord.Guild, duty_type: str) -> Dict[int, str]:
    """Find members with the given duty role. Mirrors duties_scan.py logic."""
    staff: Dict[int, str] = {}
    for role in guild.roles:
        rn = role.name.lower()
        match = False
        if duty_type == 'req' and rn == 'map request helper':
            match = True
        if match:
            for member in role.members:
                if not member.bot:
                    staff[member.id] = member.display_name
    return staff


async def scan_messages_during_hour(bot, start_dt: datetime, end_dt: datetime) -> Dict[int, int]:
    """Count messages per STAFF member across all source guilds during the Power Hour window.
    Only users who hold at least one duty role (req) are counted.
    Regular members who happen to be active are ignored.
    """
    counts: Dict[int, int] = {}

    # Build the full set of staff IDs across both guilds and all duty types
    staff_ids: Set[int] = set()
    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if guild:
            for duty in ['role', 'req']:
                staff_ids.update(find_staff_for_duty(guild, duty).keys())

    if not staff_ids:
        logger.warning("  ⚡ [Power Hour] No staff found for message scan — skipping")
        return counts

    logger.info(f"  ⚡ [Power Hour] Message scan restricted to {len(staff_ids)} staff members")

    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        logger.info(f"  ⚡ [Power Hour] Scanning messages in {guild.name}...")
        text_channels = get_readable_text_channels(guild)

        for idx, channel in enumerate(text_channels):
            if idx > 0:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)
            try:
                messages = await safe_history_fetch(
                    channel, limit=5000, after=start_dt, before=end_dt
                )
                for msg in messages:
                    if not msg.author.bot and msg.author.id in staff_ids:
                        counts[msg.author.id] = counts.get(msg.author.id, 0) + 1
            except Exception as e:
                logger.error(f"    ❌ Error scanning {channel.name}: {e}")

        await asyncio.sleep(DELAY_BETWEEN_GUILDS)

    return counts


async def scan_roles_during_hour(bot, start_dt: datetime, end_dt: datetime) -> Dict[int, int]:
    """Count role-duty actions per staff member across source guilds via audit logs."""
    counts: Dict[int, int] = {}
    scanned: Set[int] = set()

    all_staff: Dict[int, str] = {}
    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if guild:
            all_staff.update(find_staff_for_duty(guild, 'role'))

    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        logger.info(f"  ⚡ [Power Hour] Scanning role duties in {guild.name}...")

        for user_id in list(all_staff.keys()):
            if user_id in scanned:
                continue
            member = guild.get_member(user_id)
            if not member:
                continue

            count = 0
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)
                async for entry in guild.audit_logs(
                    action=discord.AuditLogAction.member_role_update,
                    after=start_dt, before=end_dt, limit=5000
                ):
                    if entry.user and entry.user.id == member.id:
                        count += 1
            except discord.Forbidden:
                logger.warning(f"    ⚠️ No audit log access in {guild.name}")
            except Exception as e:
                logger.error(f"    ❌ Role scan error for {member.name}: {e}")

            counts[user_id] = counts.get(user_id, 0) + count
            scanned.add(user_id)

        await asyncio.sleep(DELAY_BETWEEN_GUILDS)

    return counts


async def scan_requests_during_hour(bot, start_dt: datetime, end_dt: datetime) -> Dict[int, int]:
    """Count requests completed per staff member across source guilds."""
    counts: Dict[int, int] = {}
    scanned: Set[int] = set()

    all_staff: Dict[int, str] = {}
    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if guild:
            all_staff.update(find_staff_for_duty(guild, 'req'))

    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        guild_config = await config_cache.get_guild_config(guild.id)
        req_channel_id = guild_config.get('request_channel_id')
        if not req_channel_id:
            continue
        req_channel = guild.get_channel(req_channel_id)
        if not req_channel:
            continue

        logger.info(f"  ⚡ [Power Hour] Scanning requests in {guild.name}...")

        for user_id in list(all_staff.keys()):
            if user_id in scanned:
                continue
            member = guild.get_member(user_id)
            if not member:
                continue

            count = 0
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)
                messages = await safe_history_fetch(
                    req_channel, limit=5000, after=start_dt, before=end_dt
                )
                for msg in messages:
                    # Only count messages where this member replied to someone
                    # else (an actual help action), not every message posted.
                    if msg.author.id == member.id and is_reply_to_other(msg):
                        count += 1
            except Exception as e:
                logger.error(f"    ❌ Request scan error for {member.name}: {e}")

            counts[user_id] = counts.get(user_id, 0) + count
            scanned.add(user_id)

        await asyncio.sleep(DELAY_BETWEEN_GUILDS)

    return counts


async def scan_mod_commands_during_hour(bot, start_dt: datetime, end_dt: datetime) -> Dict[int, int]:
    """Count mod commands per staff member across source guilds via modlog channel."""
    counts: Dict[int, int] = {}
    scanned: Set[int] = set()

    # Get union of all duty staff across guilds
    all_staff: Dict[int, str] = {}
    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if guild:
            for duty in ['role', 'req']:
                all_staff.update(find_staff_for_duty(guild, duty))

    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        guild_config = await config_cache.get_guild_config(guild.id)
        modlog_channel_id = guild_config.get('modlog_channel_id') or guild_config.get('modlogs_channel_id')
        if not modlog_channel_id:
            continue
        modlog_channel = guild.get_channel(modlog_channel_id)
        if not modlog_channel:
            continue

        logger.info(f"  ⚡ [Power Hour] Scanning mod commands in {guild.name}...")

        try:
            await asyncio.sleep(RATE_LIMIT_DELAY)
            messages = await safe_history_fetch(
                modlog_channel, limit=5000, after=start_dt, before=end_dt
            )
        except Exception as e:
            logger.error(f"    ❌ Could not fetch modlog channel: {e}")
            continue

        for user_id in list(all_staff.keys()):
            if user_id in scanned:
                continue
            member = guild.get_member(user_id)
            if not member:
                continue

            uid_str = str(member.id)
            count = 0
            for msg in messages:
                if msg.author.bot and msg.embeds:
                    for embed in msg.embeds:
                        content = extract_embed_content(embed)
                        if uid_str in content:
                            count += 1
                            break

            counts[user_id] = counts.get(user_id, 0) + count
            scanned.add(user_id)

        await asyncio.sleep(DELAY_BETWEEN_GUILDS)

    return counts


# ==================== POINT CALCULATION ====================

def calculate_points(messages: int, roles: int, requests: int, mod_commands: int = 0, is_double: bool = False) -> int:
    """Convert raw activity counts into Wave Points. Doubles all points if is_double=True."""
    pts = 0
    pts += min(math.floor(messages / MSG_PER_POINT), MSG_POINTS_MAX)
    pts += math.floor(roles        / ROLE_PER_POINT)
    pts += math.floor(requests     / REQ_PER_POINT)
    pts += math.floor(mod_commands / MOD_PER_POINT)
    if is_double:
        pts *= 2
    return pts


# ==================== ANNOUNCE ====================

async def send_start_embed(bot, end_dt: datetime, is_double: bool = False):
    """Send the Power Hour start announcement embed."""
    channel = await _get_announce_channel(bot)
    if not channel:
        logger.error(f"❌ Power Hour announce channel {ANNOUNCE_CHANNEL} not found")
        return

    if is_double:
        title  = "⚡⚡ DOUBLE POWER HOUR IS LIVE!"
        colour = 0xFF4500   # deep orange-red to stand out from normal gold
        intro  = (
            "🔥 **DOUBLE POINTS ACTIVE!** A rare Double Power Hour has just started — "
            "every Wave Point you earn this hour is worth **2×**!\n\n"
            f"**Ends:** <t:{int(end_dt.timestamp())}:R> (<t:{int(end_dt.timestamp())}:t> UTC)\n\n"
            "⏳ **Points are awarded automatically at the end of the hour.**"
        )
        pts_suffix = " × **2 (DOUBLE!)**"
        footer = f"⚡⚡ Double Power Hour • 50% chance when Power Hour fires • {int(PEAK_TRIGGER_CHANCE*100)}% peak / {int(TRIGGER_CHANCE*100)}% off-peak"
    else:
        title  = "⚡ POWER HOUR IS LIVE!"
        colour = 0xFFD700
        intro  = (
            "A special event has just started — **everything counts for Wave Points** "
            "for the next hour!\n\n"
            f"**Ends:** <t:{int(end_dt.timestamp())}:R> (<t:{int(end_dt.timestamp())}:t> UTC)\n\n"
            "⏳ **Points are awarded automatically at the end of the hour.**"
        )
        pts_suffix = ""
        footer = f"⚡ Power Hour • {int(PEAK_TRIGGER_CHANCE*100)}% chance 13:00-21:00 UTC • {int(TRIGGER_CHANCE*100)}% off-peak"

    embed = discord.Embed(
        title=title,
        description=intro,
        color=colour,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(
        name="🌊 How to Earn Wave Points",
        value=(
            f"📨 **Messages** — every **{MSG_PER_POINT} messages** sent in either server → **+1 pt**{pts_suffix}\n"
            f"🗺️ **Map Requests** — every **1 request** completed → **+1 pt**{pts_suffix}\n"
            f"🛡️ **Mod Commands** — every **{MOD_PER_POINT} mod commands** used → **+1 pt**{pts_suffix}"
        ),
        inline=False
    )
    embed.add_field(
        name="⏰ When Do I Get My Points?",
        value=(
            "Points are calculated and awarded **at the end of the hour** automatically.\n"
            "Keep grinding — everything you do right now counts!"
        ),
        inline=False
    )
    guild_names = [g.name for g in [bot.get_guild(gid) for gid in SOURCE_GUILDS] if g]
    servers_value = " & ".join(f"**{n}**" for n in guild_names) if guild_names else "Both Wave Management servers"

    embed.add_field(
        name="📡 Active Servers",
        value=f"{servers_value} are tracking activity simultaneously.",
        inline=False
    )
    embed.set_footer(text=footer)

    try:
        # Ghost ping @here (send then immediately delete)
        ghost = await channel.send("@here")
        await ghost.delete()
        msg = await channel.send(embed=embed)
        await save_start_message_id(msg.id)
        logger.info(f"✅ Power Hour start embed sent (double={is_double})")
    except Exception as e:
        logger.error(f"❌ Failed to send Power Hour embed: {e}")


async def send_end_embed(bot, payments: list, total_pts: int, start_dt: datetime, end_dt: datetime, is_double: bool = False):
    """Send the Power Hour end summary embed."""
    channel = await _get_announce_channel(bot)
    if not channel:
        return

    double_note = " *(2× Double Power Hour)*" if is_double else ""
    embed = discord.Embed(
        title="⚡⚡ Double Power Hour Over!" if is_double else "⚡ Power Hour Over!",
        description=(
            f"**{total_pts:,} Wave Points**{double_note} were awarded across **{len(payments)}** staff member(s)!\n\n"
            f"[How Power Hour works](https://discord.com/channels/1041450125391835186/1474715327974609117/1474762757256777851)\n"
            f"[What you can spend Wave Points on](https://discord.com/channels/1041450125391835186/1474681667548352585/1490594215741358192)\n\n"
            f"Ran from <t:{int(start_dt.timestamp())}:t> → <t:{int(end_dt.timestamp())}:t> UTC"
        ),
        color=0xFF4500 if is_double else 0x00D9FF,
        timestamp=datetime.now(timezone.utc)
    )

    if payments:
        top = sorted(payments, key=lambda x: x[1], reverse=True)[:10]
        lines = []
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, (uid, pts) in enumerate(top, 1):
            medal = medals.get(i, f"`{i}.`")
            lines.append(f"{medal} <@{uid}> — **+{pts:,} pts**")
        embed.add_field(name="🏆 Top Earners", value="\n".join(lines), inline=False)

    footer_suffix = " • 🔥 DOUBLE POINTS were active this hour!" if is_double else ""
    embed.set_footer(text=f"⚡ Power Hour complete • Points added to Wave Point balances{footer_suffix}")

    try:
        msg = await channel.send(embed=embed)
        await save_end_message_id(msg.id)
    except Exception as e:
        logger.error(f"❌ Failed to send Power Hour end embed: {e}")



async def dm_power_hour_earners(bot, payments: list, start_dt: datetime, end_dt: datetime, is_double: bool = False):
    """DM every earner a personal summary of what they earned during Power Hour."""
    for uid, pts, msgs, roles, reqs, mods in payments:
        try:
            user = bot.get_user(uid) or await bot.fetch_user(uid)
            if not user:
                continue

            double_note = "\n🔥 **This was a Double Power Hour — all your points were doubled!**" if is_double else ""
            embed = discord.Embed(
                title="⚡⚡ Double Power Hour — Your Earnings!" if is_double else "⚡ Power Hour — Your Earnings!",
                description=f"The Power Hour just ended and you earned **+{pts:,} Wave Points**!{double_note}",
                color=0xFF4500 if is_double else 0x00D9FF,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(
                name="⏱️ Session",
                value=f"<t:{int(start_dt.timestamp())}:t> → <t:{int(end_dt.timestamp())}:t> UTC",
                inline=False
            )

            # Build per-duty breakdown lines (only show duties with activity)
            # For doubles, show base pts → doubled pts so it's clear
            breakdown_lines = []
            if msgs:
                base = math.floor(msgs / MSG_PER_POINT)
                final = base * 2 if is_double else base
                dbl = f" × 2 = **+{final}**" if is_double else f"**+{final}**"
                breakdown_lines.append(f"📨 **Messages** — {msgs} sent → {dbl} pt{'s' if final != 1 else ''}")
            if reqs:
                base = math.floor(reqs / REQ_PER_POINT)
                final = base * 2 if is_double else base
                dbl = f" × 2 = **+{final}**" if is_double else f"**+{final}**"
                breakdown_lines.append(f"🗺️ **Map Requests** — {reqs} completed → {dbl} pt{'s' if final != 1 else ''}")
            if mods:
                base = math.floor(mods / MOD_PER_POINT)
                final = base * 2 if is_double else base
                dbl = f" × 2 = **+{final}**" if is_double else f"**+{final}**"
                breakdown_lines.append(f"🛡️ **Mod Commands** — {mods} used → {dbl} pt{'s' if final != 1 else ''}")

            if breakdown_lines:
                embed.add_field(
                    name="📊 Breakdown",
                    value="\n".join(breakdown_lines),
                    inline=False
                )

            embed.add_field(name="💎 Total Earned", value=f"**+{pts:,} pts**", inline=True)
            embed.set_footer(text="Use >wavepoints to check your current balance")
            await user.send(embed=embed)
        except discord.Forbidden:
            logger.debug(f"  ℹ️ Could not DM user {uid} (DMs disabled)")
        except Exception as e:
            logger.warning(f"  ⚠️ Failed to DM Power Hour earner {uid}: {e}")


# ==================== CORE POWER HOUR LOGIC ====================

async def run_power_hour(bot):
    """
    Execute a full Power Hour:
      1. Guard against concurrent runs
      2. Record start in DB
      3. Send announcement embed
      4. Wait 1 hour
      5. Validate state wasn't overwritten during sleep
      6. Delete the now-expired "POWER HOUR IS LIVE!" start embed
      7. Scan all duty types using locally-captured start/end times
      8. Calculate and award Wave Points
      9. Send end embed, clear old end embed
      10. Clear activity table, mark inactive
    """
    # ── Guard: never run two Power Hours concurrently ──────────────────────
    # The scheduler already wrote active=1 before spawning this task.
    # A duplicate is only real if start_time is already committed (meaning
    # another full run_power_hour got through), not just the pre-lock.
    state = await get_power_hour_state()
    if state['active'] and state['start_time'] is not None:
        logger.warning("⚡ Power Hour already active — ignoring duplicate trigger")
        return

    # Capture times locally — never re-read from DB after sleeping, as a
    # concurrent trigger could overwrite them and corrupt the scan window.
    now      = datetime.now(timezone.utc)
    start_dt = now
    end_dt   = now + timedelta(seconds=DURATION_SECONDS)
    hour_key = now.strftime('%Y-%m-%d-%H')

    logger.info(f"⚡ Power Hour STARTING — runs until {end_dt.strftime('%H:%M')} UTC")

    # ── Roll for Double Power Hour (50/50) ────────────────────────────────
    is_double = random.random() < DOUBLE_CHANCE
    logger.info(f"⚡ Double Power Hour roll: {'YES 🔥' if is_double else 'no'}")

    await update_last_roll_is_double(is_double)
    asyncio.ensure_future(push_power_hour_to_events(bot))

    # Update roll status message now that we know if it's double
    now_ts    = datetime.now(timezone.utc)
    hour_key2 = now_ts.strftime('%Y-%m-%d-%H')
    await update_roll_status_message(bot, triggered=True, roll=0.0, hour_key=hour_key2, is_double=is_double)

    # Delete both the previous Power Hour's start and end embeds before the
    # new start embed goes up, so the channel doesn't show stale messages.
    announce_ch = await _get_announce_channel(bot)

    old_start_msg_id = await get_start_message_id()
    if old_start_msg_id:
        try:
            if announce_ch:
                old_start_msg = await announce_ch.fetch_message(old_start_msg_id)
                await old_start_msg.delete()
                logger.info(f"🗑️ Deleted previous Power Hour start embed ({old_start_msg_id})")
        except (discord.NotFound, discord.Forbidden):
            pass
        except Exception as e:
            logger.warning(f"⚠️ Could not delete old start embed: {e}")
        await save_start_message_id(None)

    old_end_msg_id = await get_end_message_id()
    if old_end_msg_id:
        try:
            if announce_ch:
                old_end_msg = await announce_ch.fetch_message(old_end_msg_id)
                await old_end_msg.delete()
                logger.info(f"🗑️ Deleted previous Power Hour end embed ({old_end_msg_id})")
        except (discord.NotFound, discord.Forbidden):
            pass
        except Exception as e:
            logger.warning(f"⚠️ Could not delete old end embed: {e}")
        await save_end_message_id(None)

    await clear_activity_table()
    await set_power_hour_active(now, end_dt, hour_key, is_double=is_double)
    await send_start_embed(bot, end_dt, is_double=is_double)

    # Keep the info message up to date whenever a new Power Hour fires
    try:
        await auto_update_power_hour_info(bot)
    except Exception as e:
        logger.warning(f"⚠️ Could not update Power Hour info message on trigger: {e}")

    # Wait for the hour to pass
    await asyncio.sleep(DURATION_SECONDS)

    logger.info("⚡ Power Hour ending — running scans...")

    # ── Validate state wasn't mutated while we slept ────────────────────────
    # If a second trigger somehow ran and overwrote hour_key, abort to avoid
    # double-scanning the same window or awarding points for the wrong period.
    current_state = await get_power_hour_state()
    if current_state['hour_key'] != hour_key:
        logger.warning(
            f"⚡ Power Hour state changed during sleep "
            f"(expected hour_key={hour_key}, got {current_state['hour_key']}) — aborting payout"
        )
        return

    # ── Scan all duty types using the locally captured start/end times ───────
    try:
        msg_counts   = await scan_messages_during_hour(bot, start_dt, end_dt)
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)
        role_counts  = await scan_roles_during_hour(bot, start_dt, end_dt)
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)
        req_counts   = await scan_requests_during_hour(bot, start_dt, end_dt)
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)
        mod_counts   = await scan_mod_commands_during_hour(bot, start_dt, end_dt)
    except Exception as e:
        logger.error(f"❌ Power Hour scan error: {e}")
        await set_power_hour_inactive()
        await clear_activity_table()
        return

    # Merge all users
    all_users: Set[int] = (
        set(msg_counts.keys()) |
        set(role_counts.keys()) |
        set(req_counts.keys()) |
        set(mod_counts.keys())
    )

    payments = []
    total_pts = 0

    for uid in all_users:
        msgs    = msg_counts.get(uid, 0)
        roles   = role_counts.get(uid, 0)
        reqs    = req_counts.get(uid, 0)
        mods    = mod_counts.get(uid, 0)
        pts     = calculate_points(msgs, roles, reqs, mods, is_double=is_double)

        if pts > 0:
            try:
                await add_wave_points(uid, pts, bot=bot, reason="Power hour reward")
                payments.append((uid, pts, msgs, roles, reqs, mods))
                total_pts += pts
                logger.info(
                    f"  💰 Power Hour: user={uid} msgs={msgs} roles={roles} "
                    f"reqs={reqs} mods={mods} → +{pts} pts"
                    f"{' (2× double)' if is_double else ''}"
                )
            except Exception as e:
                logger.error(f"  ❌ Failed to award pts to {uid}: {e}")

    logger.info(f"✅ Power Hour complete — {total_pts} pts awarded to {len(payments)} users{' (DOUBLE)' if is_double else ''}")

    await send_end_embed(bot, [(uid, pts) for uid, pts, *_ in payments], total_pts, start_dt, end_dt, is_double=is_double)
    await dm_power_hour_earners(bot, payments, start_dt, end_dt, is_double=is_double)
    await set_power_hour_inactive()
    await clear_activity_table()

    # Push completed Power Hour data to the events page on the Staff Hub
    payments_dict = {uid: pts for uid, pts, *_ in payments}
    asyncio.ensure_future(_push_ph_to_events(bot, start_dt, end_dt, is_double, total_pts, payments_dict))

    # Clear end message ID AFTER everything is done so next trigger doesn't delete this message
    await save_end_message_id(None)


# ==================== EVENTS PAGE PUSH ====================

def _compute_power_hour_meta() -> dict:
    now = datetime.now(timezone.utc)
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    chance = get_trigger_chance(next_hour.hour)
    return {
        'next_roll_at': next_hour.isoformat(),
        'trigger_chance': chance,
        'is_peak': chance == PEAK_TRIGGER_CHANCE,
    }


def _last_roll_from_state(state: dict) -> dict | None:
    if state.get('last_roll') is None:
        return None
    return {
        'hour_key': state.get('last_roll_hour_key'),
        'roll': state['last_roll'],
        'chance': state['last_roll_chance'],
        'triggered': bool(state.get('last_roll_triggered')),
        'is_double': bool(state.get('last_roll_is_double')),
        'rolled_at': state.get('last_roll_at'),
    }


def _active_power_hour_from_state(state: dict) -> dict | None:
    if not state.get('active'):
        return None
    is_double = bool(state.get('is_double'))
    mult = 2 if is_double else 1
    return {
        'status': 'active',
        'start_time': state.get('start_time'),
        'end_time': state.get('end_time'),
        'multiplier': mult,
        'is_double': is_double,
        'name': 'Double Power Hour' if is_double else 'Power Hour',
        'description': 'Points awarded automatically when the hour ends',
    }


async def push_power_hour_to_events(bot):
    """Refresh power-hour meta, last roll, and active session in events.json."""
    try:
        from tasks.staff_hub_writer import push_events_to_github
        from tasks.random_challenges import build_challenges_payload
        events_path = Path(__file__).resolve().parent.parent / 'website' / 'data' / 'events.json'
        existing = {}
        if events_path.exists():
            try:
                existing = json.loads(events_path.read_text(encoding='utf-8'))
            except Exception:
                existing = {}
        ph_history = existing.get('power_hours', [])
        fresh = await build_challenges_payload(bot)
        existing.update({k: v for k, v in fresh.items() if k != 'power_hours'})
        existing['power_hours'] = ph_history
        state = await get_power_hour_state()
        existing['power_hour_meta'] = _compute_power_hour_meta()
        existing['last_roll'] = _last_roll_from_state(state)
        existing['active_power_hour'] = _active_power_hour_from_state(state)
        await push_events_to_github(existing)
    except Exception as e:
        logger.warning(f"push_power_hour_to_events error: {e}")


async def _push_ph_to_events(bot, start_dt, end_dt, is_double, total_pts, payments):
    """Append a finished Power Hour entry to events.json."""
    try:
        from tasks.staff_hub_writer import push_events_to_github
        from tasks.random_challenges import build_challenges_payload
        events_path = Path(__file__).resolve().parent.parent / 'website' / 'data' / 'events.json'
        existing = {}
        if events_path.exists():
            try:
                existing = json.loads(events_path.read_text(encoding='utf-8'))
            except Exception:
                existing = {}
        top_earners = []
        for uid, pts in sorted(payments.items(), key=lambda x: x[1], reverse=True)[:10]:
            user = bot.get_user(int(uid)) if bot else None
            if user is None and bot:
                try:
                    user = await bot.fetch_user(int(uid))
                except Exception:
                    user = None
            top_earners.append({
                'username': user.display_name if user else str(uid),
                'points': pts,
            })
        mult = 2 if is_double else 1
        ph_name = 'Double Power Hour' if is_double else 'Power Hour'
        earner_count = len(payments)
        ph_entry = {
            'start_time': start_dt.isoformat() if hasattr(start_dt, 'isoformat') else str(start_dt),
            'end_time': end_dt.isoformat() if hasattr(end_dt, 'isoformat') else str(end_dt),
            'is_double': bool(is_double),
            'multiplier': mult,
            'status': 'ended',
            'name': ph_name,
            'label': ph_name,
            'description': f'{total_pts} WP awarded · {earner_count} earner{"s" if earner_count != 1 else ""}',
            'total_points': total_pts,
            'earner_count': earner_count,
            'top_earners': top_earners,
        }
        ph_list = existing.get('power_hours', [])
        ph_list.insert(0, ph_entry)
        existing['power_hours'] = ph_list[:10]
        fresh = await build_challenges_payload(bot)
        existing.update({k: v for k, v in fresh.items() if k != 'power_hours'})
        state = await get_power_hour_state()
        existing['power_hour_meta'] = _compute_power_hour_meta()
        existing['last_roll'] = _last_roll_from_state(state)
        existing['active_power_hour'] = None
        await push_events_to_github(existing)
    except Exception as e:
        logger.warning(f"_push_ph_to_events error: {e}")


# ==================== HOURLY LOOP ====================

async def power_hour_scheduler(bot):
    """
    Runs forever. At the top of each hour, rolls 5% chance.
    Each hour is independent — checks DB to avoid double-firing.
    """
    await bot.wait_until_ready()
    logger.info("✅ Power Hour scheduler active")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Sleep until the top of the next hour
            next_hour = (now + timedelta(hours=1)).replace(
                minute=0, second=0, microsecond=0
            )
            wait_secs = (next_hour - now).total_seconds()
            logger.info(f"⚡ Power Hour: next roll in {wait_secs/60:.1f}min at {next_hour.strftime('%H:%M')} UTC")
            await asyncio.sleep(wait_secs)

            now      = datetime.now(timezone.utc)
            hour_key = now.strftime('%Y-%m-%d-%H')

            # Guard: if we woke up with < 2s to spare the sleep was essentially
            # a no-op (e.g. bot restarted at 22:59:59). Wait a beat so multiple
            # scheduler instances that all slept to the same boundary don't all
            # proceed simultaneously before any DB write has landed.
            if wait_secs < 2.0:
                await asyncio.sleep(2.0)
                now      = datetime.now(timezone.utc)
                hour_key = now.strftime('%Y-%m-%d-%H')

            # Acquire the roll lock — if another scheduler instance (e.g. from a
            # session invalidation + reconnect) already holds it, we wait here,
            # then the hour_key check below will see it was already handled.
            async with _roll_lock:
                # Check if already fired this hour
                state = await get_power_hour_state()
                if state['hour_key'] == hour_key:
                    logger.info(f"⚡ Power Hour already handled for hour {hour_key} — skipping roll")
                    continue

                # Roll — probability depends on peak window (13:00-21:00 UTC = 20%, off-peak = 5%)
                chance  = get_trigger_chance(now.hour)
                is_peak = chance == PEAK_TRIGGER_CHANCE
                roll    = random.random()
                logger.info(
                    f"⚡ Power Hour roll: {roll:.4f} (need < {chance}) "
                    f"{'[PEAK 13-21 UTC — 10%]' if is_peak else '[off-peak — 5%]'}"
                )

                if roll < chance:
                    logger.info("🎉 Power Hour triggered!")
                    await save_last_roll(roll, chance, True, hour_key)
                    await update_roll_status_message(bot, triggered=True, roll=roll, hour_key=hour_key)
                    # ── Lock the DB row BEFORE spawning the task so the scheduler
                    # can never see active=0 and overwrite hour_key in the gap
                    # between create_task() and run_power_hour's first DB write.
                    pool = await database.get_pool()
                    async with pool.acquire() as db:
                        await db.execute(
                            'UPDATE power_hour_state SET active=1, hour_key=? WHERE id=1',
                            (hour_key,)
                        )
                        await db.commit()
                    asyncio.create_task(run_power_hour(bot))
                else:
                    # Mark this hour as checked (no event) so we don't re-roll.
                    # Guard: never overwrite hour_key while a Power Hour is active —
                    # doing so would cause the running Power Hour to abort its payout.
                    current_state = await get_power_hour_state()
                    if not current_state['active']:
                        pool = await database.get_pool()
                        async with pool.acquire() as db:
                            await db.execute(
                                'UPDATE power_hour_state SET hour_key=? WHERE id=1',
                                (hour_key,)
                            )
                            await db.commit()
                    else:
                        logger.info(f"⚡ Power Hour active — skipping hour_key update for {hour_key} to avoid aborting payout")
                    await update_roll_status_message(bot, triggered=False, roll=roll, hour_key=hour_key)
                    logger.info(f"⚡ Power Hour did not trigger this hour ({roll:.4f} >= {chance})")
                    await save_last_roll(roll, chance, False, hour_key)

                asyncio.ensure_future(push_power_hour_to_events(bot))

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"❌ Power Hour scheduler error: {e}")
            await asyncio.sleep(60)


# ==================== COG ====================

class PowerHourCog(commands.Cog):
    """Power Hour — background task cog: hourly roll + scheduler."""

    def __init__(self, bot):
        self.bot  = bot
        self.task = None

    async def cog_load(self):
        await init_power_hour_tables()
        await self._recover_stale_state()
        self.task = asyncio.create_task(power_hour_scheduler(self.bot))
        asyncio.create_task(self._post_info_when_ready())
        asyncio.ensure_future(push_power_hour_to_events(self.bot))
        logger.info("✅ PowerHourCog loaded")

    async def _recover_stale_state(self):
        """
        On startup, check if the DB still has active=1 from a previous run.
        If end_time has already passed (or is missing), the Power Hour was
        orphaned by a crash — clear it so the scheduler isn't stuck all day.
        """
        state = await get_power_hour_state()
        if not state['active']:
            return

        now = datetime.now(timezone.utc)
        end_time = state.get('end_time')

        stale = False
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time)
                if now >= end_dt:
                    stale = True
            except Exception:
                stale = True  # Corrupt timestamp — treat as stale
        else:
            # active=1 but no end_time means the pre-lock wrote active=1
            # but run_power_hour never committed start/end — also stale.
            stale = True

        if stale:
            logger.warning(
                f"⚡ [Startup] Stale Power Hour state found (active=1, end_time={end_time}) "
                f"— bot was likely restarted mid-event. Clearing orphaned state."
            )
            await set_power_hour_inactive()
            await clear_activity_table()
            logger.info("⚡ [Startup] Stale state cleared — scheduler will resume normally.")

    async def _post_info_when_ready(self):
        await self.bot.wait_until_ready()
        await auto_update_power_hour_info(self.bot)

    def cog_unload(self):
        if self.task:
            self.task.cancel()
        logger.info("🛑 PowerHourCog unloaded")


async def setup(bot):
    await bot.add_cog(PowerHourCog(bot))
    logger.info("✅ Power Hour task cog loaded")
