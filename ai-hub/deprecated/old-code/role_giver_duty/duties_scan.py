"""
Duties Scan - Automated Full System Scan Every 4 Hours
Scans ALL staff activity across ALL duties and caches to database
Runs at EXACT 4-hour intervals: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC

Staff is found by DUTY ROLE NAME (same as weekly_checks.py):
  - role  : role name contains "role giver"
  - req   : role name == "map request helper"

Scan logic is IDENTICAL to weekly_checks.py for role / req.
modlog and message are scanned for ALL staff (union of the two groups)
and stored to DB, then all 4 duties exported to GitHub leaderboard.

Order per scan cycle:
  1. req   → scan → cache DB → update LB channel
  2. role  → scan → cache DB → update LB channel
  3. modlog → scan → cache DB
  4. message → scan → cache DB
  5. Export all 4 duties to GitHub JSON (duties_totals.json)

CHANGE (role scan optimisation):
  Previously scan_roles_for_member() was called once per member per guild,
  meaning 13 members × 2 guilds = 26 full audit-log sweeps. Each sweep used
  limit=None, which downloaded every role-update entry for the week and then
  filtered client-side — causing the bot to freeze for 10-20 minutes.

  Now scan_roles_all_members_in_guild() fetches the audit log ONCE per guild,
  iterates through all member_role_update entries in the date window, and
  buckets the count per user in a single pass. That is 2 audit-log sweeps
  total (one per guild) instead of 26, giving identical results in a fraction
  of the time. Rate-limit delays and the AUDIT_LOG_BATCH_SIZE sleep are
  preserved exactly.
"""

import discord
from discord.ext import commands
import logging
import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Set, Any, List, Optional

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
)
from core.cache import config_cache
import database

logger = logging.getLogger('discord')

# ==================== RATE LIMIT TRACKING ====================
class RateLimitTracker:
    """Track and log rate limits during scans"""
    def __init__(self):
        self.hit_count = 0
        self.last_hit_time = None
        self.rate_limit_log_file = 'duties_scan_rate_limits.log'

    def log_rate_limit(self, retry_after: float, endpoint: str = "unknown"):
        self.hit_count += 1
        self.last_hit_time = datetime.now(timezone.utc)
        msg = (
            f"[{self.last_hit_time}] ⚠️ RATE LIMIT HIT on {endpoint} "
            f"- retry_after={retry_after}s (total hits: {self.hit_count})"
        )
        logger.warning(msg)
        with open(self.rate_limit_log_file, 'a') as f:
            f.write(msg + '\n')

    def reset(self):
        self.hit_count = 0
        self.last_hit_time = None

rate_limit_tracker = RateLimitTracker()

# ==================== CONSTANTS ====================

VALID_SCAN_HOURS = [0, 4, 8, 12, 16, 20]

# Rate limiting — mirrors weekly_checks.py values
RATE_LIMIT_DELAY            = 1.2   # between per-member API calls
DELAY_BETWEEN_CHANNELS      = 1.5   # between channels in message scan
DELAY_BETWEEN_GUILDS        = 5.0   # between guilds
DELAY_BETWEEN_DUTIES        = 4.0   # between duty types
AUDIT_LOG_BATCH_SIZE        = 500   # sleep every N audit log entries
DELAY_BETWEEN_AUDIT_BATCHES = 2.5   # seconds to sleep per batch
MAX_RETRIES                 = 3

LEADERBOARD_CHANNELS = {
    'role':  1467087929468784660,
    'req':   1467087539490783285,
}

DUTY_CONFIG = {
    'role': {
        'emoji': '👤',
        'name':  'Role Giver',
        'great': 48, 'good': 24, 'okay': 8,
    },
    'req': {
        'emoji': '🗺️',
        'name':  'Map Request Helper',
        'great': 50, 'good': 20, 'okay': 8,
    },
}

RANK_MEDALS = {1: '🥇', 2: '🥈', 3: '🥉'}


# ==================== LEADERBOARD HELPERS ====================

def _status(count: int, thresholds: dict) -> str:
    if count >= thresholds['great']:
        return '🌟 Great'
    elif count >= thresholds['good']:
        return '✅ Good'
    elif count >= thresholds['okay']:
        return '⚠️ Okay'
    else:
        return '❌ Bad'


# ==================== DUTY INFO EMBEDS (static, posted on startup) ====================

# Sentinel string embedded in the footer so we can find/edit our own message later.
_DUTY_INFO_FOOTER_TAG = "wdm-duty-info-v1"

DUTY_INFO_CONFIG = {
    'role': {
        'channel_id': 1467087929468784660,
        'title': '👤 Role Giver Duty — How It Works',
        'color': 0x5865F2,
        'ranks': (
            "🌟 **Great:** 81+\n"
            "⭐ **Very Good:** 65 – 80\n"
            "✅ **Good:** 41 – 64\n"
            "⚠️ **Okay:** 24 – 40\n"
            "❌ **Bad:** below 24"
        ),
        'awards': (
            "🥇 **1st place:** 500 VBucks\n"
            "🥈 **2nd place:** 300 VBucks\n"
            "🥉 **3rd place:** 200 VBucks"
        ),
    },
    'req': {
        'channel_id': 1467087539490783285,
        'title': '🗺️ Map Request Helper Duty — How It Works',
        'color': 0x57F287,
        'ranks': (
            "🌟 **Great:** 41+\n"
            "⭐ **Very Good:** 21 – 40\n"
            "✅ **Good:** 10 – 20\n"
            "❌ **Bad:** 9 or below"
        ),
        'awards': (
            "🥇 **1st place:** 300 VBucks\n"
            "🥈 **2nd place:** 200 VBucks"
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
            "about how this duty works, how you earn VBucks, and what happens "
            "if you slack off this week."
        ),
        color=cfg['color'],
    )

    embed.add_field(
        name="📊 Performance Ranks (Full Week)",
        value=cfg['ranks'],
        inline=False,
    )

    embed.add_field(
        name="💰 Weekly VBucks Awards",
        value=cfg['awards'],
        inline=False,
    )

    embed.add_field(
        name="🔥 Activity Streak Bonus",
        value=(
            "Get a 🌟 **Great** rank for **3 weeks in a row** to unlock a **1.5× multiplier**!\n"
            "• Week 1 Great → ✅ Streak started (1/3)\n"
            "• Week 2 Great → ✅ Streak continues (2/3)\n"
            "• Week 3 Great → ✅ Streak complete (3/3)\n"
            "• Week 4 award → 🔥 **1.5× VBucks bonus applied!**\n"
            "*Streak resets after the multiplier triggers.*"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚠️ Bad Performance Penalty",
        value=(
            "Get a ❌ **Bad** rank? You lose **200 VBucks** from your total balance.\n"
            "• Drains in order: **main → req → role**\n"
            "• If your total VBucks is **0** → your duty role is **automatically removed** from all servers\n"
            "• You'll get a DM telling you what happened"
        ),
        inline=False,
    )

    embed.add_field(
        name="🌴 Away Role Exemption",
        value=(
            "Both **Away** and **Strike Immunity Away** roles are fully exempt from the Bad penalty.\n"
            "*If you're away, you won't lose VBucks or your duty role.*"
        ),
        inline=False,
    )

    embed.add_field(
        name="⏰ When Are Awards Given?",
        value=(
            "**At the end of every Full Week** (every 7 days).\n"
            "*Mid-Week reports are warnings only — no awards or penalties apply.*"
        ),
        inline=False,
    )

    embed.set_footer(text=_DUTY_INFO_FOOTER_TAG)
    return embed


async def post_duty_info_embeds(bot):
    """
    Post (or edit) the duty info embed in each duty's info channel.
    Called once on bot startup. Edits existing message if found via footer tag,
    otherwise posts a new one.
    """
    for duty_type, cfg in DUTY_INFO_CONFIG.items():
        channel_id = cfg['channel_id']
        channel = bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"  ⚠️ Duty info channel {channel_id} ({duty_type}) not found")
            continue

        embed = build_duty_info_embed(duty_type)
        if embed is None:
            continue

        existing: Optional[discord.Message] = None
        try:
            async for message in channel.history(limit=50):
                if (
                    message.author == bot.user
                    and message.embeds
                    and message.embeds[0].footer
                    and message.embeds[0].footer.text == _DUTY_INFO_FOOTER_TAG
                ):
                    existing = message
                    break
        except Exception as e:
            logger.error(f"  ❌ Error searching {duty_type} info channel history: {e}")

        try:
            if existing:
                await existing.edit(embed=embed)
                logger.info(f"  ✅ Edited {duty_type} duty info embed in channel {channel_id}")
            else:
                await channel.send(embed=embed)
                logger.info(f"  ✅ Posted new {duty_type} duty info embed in channel {channel_id}")
        except Exception as e:
            logger.error(f"  ❌ Failed to post {duty_type} duty info embed: {e}")


# ==================== STAFF DISCOVERY (by role name) ====================

def find_staff_for_duty(guild: discord.Guild, duty_type: str) -> Dict[int, str]:
    """
    Find members who hold the duty role in this guild.
    Matches role names exactly as weekly_checks.py does:
      role  : 'role giver' in role.name.lower()
      req   : role.name.lower() == 'map request helper'

    Returns {user_id: display_name}
    """
    staff: Dict[int, str] = {}

    for role in guild.roles:
        rn    = role.name.lower()
        match = False
        if duty_type == 'role' and 'role giver' in rn:
            match = True
        elif duty_type == 'req' and rn == 'map request helper':
            match = True

        if match:
            logger.info(f"    ✅ Found {duty_type} role: {role.name} ({len(role.members)} members)")
            for member in role.members:
                if not member.bot:
                    staff[member.id] = member.display_name

    return staff


def find_general_staff(guild: discord.Guild) -> Dict[int, str]:
    """
    Find all general staff members (Trial Staff / Staff roles) in a guild.
    Uses staff_roles_config.general_staff role names from config.json.
    Falls back to checking for 'trial staff' or 'staff' in role names.
    Returns {user_id: display_name}
    """
    general_role_names: List[str] = []
    try:
        with open('config.json', 'r') as _f:
            _cfg = json.load(_f)
        general_role_names = [
            n.lower()
            for n in _cfg.get('staff_roles_config', {}).get('general_staff', [])
        ]
    except Exception:
        pass

    if not general_role_names:
        general_role_names = ['trial staff', 'staff']

    staff: Dict[int, str] = {}
    for role in guild.roles:
        rn = role.name.lower()
        if rn in general_role_names:
            logger.info(f"    ✅ Found general staff role: {role.name} ({len(role.members)} members)")
            for member in role.members:
                if not member.bot:
                    staff[member.id] = member.display_name

    return staff


# ==================== SCAN FUNCTIONS ====================

async def scan_roles_for_member(
    guild: discord.Guild,
    member: discord.Member,
    start_datetime: datetime,
    end_datetime: datetime,
) -> int:
    """
    Matches weekly_checks.py exactly — passes user=member so Discord filters
    server-side. Only returns entries for this specific member within the date
    range, so it's fast regardless of how large the server's audit log is.
    """
    count = 0
    try:
        await asyncio.sleep(RATE_LIMIT_DELAY)
        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.member_role_update,
            user=member,
            after=start_datetime,
            before=end_datetime,
            limit=5000,
        ):
            count += 1

    except asyncio.CancelledError:
        raise
    except discord.Forbidden:
        logger.warning(f"    ⚠️ No audit log permission in {guild.name}")
    except Exception as e:
        logger.error(f"    ❌ Error scanning roles for {member.name}: {e}")

    return count


async def scan_requests_for_member(
    guild: discord.Guild,
    member: discord.Member,
    start_datetime: datetime,
    end_datetime: datetime,
) -> int:
    """
    EXACT copy of weekly_checks.scan_requests logic:
    - Reads request_channel_id from guild config
    - message.author.id == member.id
    """
    guild_config       = await config_cache.get_guild_config(guild.id)
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
            # Only count messages where this member replied to someone else
            # (an actual help action), not every message they post here.
            if (message.author.id == member.id and not message.author.bot
                    and is_reply_to_other(message)):
                count += 1

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"    ❌ Error scanning requests for {member.name}: {e}")

    return count


async def scan_modlog_for_member(
    guild: discord.Guild,
    member: discord.Member,
    start_datetime: datetime,
    end_datetime: datetime,
) -> int:
    """
    Scans modlog_channel_id for bot embeds mentioning this member's user ID.
    """
    guild_config = await config_cache.get_guild_config(guild.id)
    modlog_channel_id = guild_config.get('modlog_channel_id') or guild_config.get('modlogs_channel_id')
    if not modlog_channel_id:
        return 0

    modlog_channel = guild.get_channel(modlog_channel_id)
    if not modlog_channel:
        return 0

    count   = 0
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
        logger.error(f"    ❌ Error scanning modlog for {member.name}: {e}")

    return count


# ==================== OPTIMIZED MESSAGE SCAN (all members in one pass) ====================

async def scan_messages_all_guilds_optimized(
    bot,
    all_staff: Dict[int, str],
    source_guilds: List[int],
    start_datetime: datetime,
    end_datetime: datetime,
    start_date: str,
    end_date: str,
) -> tuple:
    """
    Optimized message scan: fetch ALL messages once per channel, count by author.
    Returns ({user_id: {'count': int, 'days': [...]}}, {user_id: display_name})
    """
    merged:      Dict[int, int]  = {}
    merged_days: Dict[int, set]  = {}
    display_map: Dict[int, str]  = {}

    for uid, name in all_staff.items():
        display_map[uid]  = name
        merged[uid]       = 0
        merged_days[uid]  = set()

    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)

        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        logger.info(f"  📨 Scanning messages in {guild.name}...")
        text_channels = get_readable_text_channels(guild)
        logger.info(f"    📋 Checking {len(text_channels)} channels...")

        guild_counts: Dict[int, int] = {uid: 0 for uid in all_staff}
        guild_days:   Dict[int, Set] = {uid: set() for uid in all_staff}

        for ch_idx, channel in enumerate(text_channels):
            if ch_idx > 0:
                await asyncio.sleep(DELAY_BETWEEN_CHANNELS)

            logger.debug(f"    • [{ch_idx+1}/{len(text_channels)}] Fetching from #{channel.name}...")
            try:
                messages = await safe_history_fetch(
                    channel, limit=5000,
                    after=start_datetime, before=end_datetime
                )
                channel_count = 0
                for message in messages:
                    if message.author.id in all_staff and not message.author.bot:
                        guild_counts[message.author.id] = guild_counts.get(message.author.id, 0) + 1
                        guild_days[message.author.id].add(message.created_at.date())
                        channel_count += 1
                logger.debug(f"      ✅ Found {channel_count} messages in #{channel.name}")

            except discord.errors.RateLimited as e:
                rate_limit_tracker.log_rate_limit(e.retry_after, f"message_history/{channel.name}")
                logger.warning(f"    ⏸️ Rate limited on #{channel.name} — waiting {e.retry_after}s...")
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
                    logger.debug(f"      ✅ Retry successful for #{channel.name}")
                except Exception as retry_err:
                    logger.error(f"    ❌ Retry failed for #{channel.name}: {retry_err}")

            except Exception as e:
                logger.error(f"    ❌ Error scanning #{channel.name}: {e}")

        for uid, count in guild_counts.items():
            merged[uid]      = merged.get(uid, 0) + count
            merged_days[uid] = merged_days.get(uid, set()) | guild_days[uid]
            if uid in all_staff:
                display_map[uid] = guild.get_member(uid).display_name if guild.get_member(uid) else all_staff[uid]
            days_list = sorted([d.isoformat() for d in guild_days[uid]])
            await cache_stat(guild_id, uid, 'message', {'count': count, 'days': days_list}, start_date, end_date)

        logger.info(f"    ✅ Cached message counts for {len(guild_counts)} users in {guild.name}")

    merged_with_days = {
        uid: {
            'count': merged[uid],
            'days':  sorted([d.isoformat() for d in merged_days[uid]])
        }
        for uid in merged
    }

    logger.info(f"  ✅ message: {len([u for u, v in merged_with_days.items() if v['count'] > 0])} users with messages")
    return merged_with_days, display_map


# ==================== CACHE HELPER ====================

async def cache_stat(
    guild_id: int,
    user_id: int,
    duty_type: str,
    count,
    start_date: str,
    end_date: str,
    scan_completed: bool = True,
):
    """
    Cache a single user's duty count to the database.
    Never overwrites a higher existing count (protects against partial scans).
    If scan_completed=False, skips the write entirely.
    """
    if not scan_completed:
        logger.debug(f"    ⏭️ Skipping cache write for {user_id} {duty_type}: scan did not complete cleanly")
        return

    try:
        if isinstance(count, dict):
            data = count
        else:
            data = {'count': count}

        new_count = data.get('count', 0)

        existing = await database.get_cached_user_stats(
            guild_id, user_id, duty_type, start_date, end_date
        )
        if existing:
            existing_count = existing.get('count', 0)
            if new_count < existing_count:
                logger.debug(
                    f"    ⏭️ Skipping cache write for {user_id} {duty_type}: "
                    f"new={new_count} < existing={existing_count}"
                )
                return

        await database.set_cached_user_stats(
            guild_id=guild_id,
            user_id=user_id,
            check_type=duty_type,
            start_date=start_date,
            end_date=end_date,
            data=data,
            cache_time=datetime.now(timezone.utc).isoformat()
        )
    except Exception as e:
        logger.error(f"    ❌ Failed to cache {duty_type} for user {user_id}: {e}")


# ==================== PER-DUTY SCAN ACROSS ALL GUILDS ====================

async def scan_duty_all_guilds(
    bot,
    duty_type: str,
    source_guilds: List[int],
    start_datetime: datetime,
    end_datetime: datetime,
    start_date: str,
    end_date: str,
) -> tuple[Dict[int, int], Dict[int, str]]:
    """
    Find staff by role name for this duty, scan every guild, cache to DB.
    Returns ({user_id: total_count}, {user_id: display_name}) merged across guilds.

    All duties (including role) use the per-member approach from weekly_checks.py.
    Role scan passes user=member so Discord filters server-side — fast and accurate.
    """
    all_staff:          Dict[int, str] = {}
    member_display_map: Dict[int, str] = {}

    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        found = find_staff_for_duty(guild, duty_type)
        for uid, name in found.items():
            all_staff[uid]          = name
            member_display_map[uid] = name

    logger.info(f"  👥 {duty_type}: found {len(all_staff)} staff members with this duty role")

    if not all_staff:
        logger.warning(f"  ⚠️ No staff found for {duty_type} — check role names in Discord")
        return {}, {}

    merged_counts: Dict[int, int] = {uid: 0 for uid in all_staff}

    # ── ALL DUTIES: per-member scan (matches weekly_checks.py exactly) ──────

    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            logger.info(f"  ⏸️ Waiting {DELAY_BETWEEN_GUILDS}s before next guild...")
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)

        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        logger.info(f"  🔍 Scanning {duty_type} in {guild.name}...")
        scanned_in_guild = 0

        for user_id in list(all_staff.keys()):
            member = guild.get_member(user_id)
            if not member:
                continue

            scan_ok = True
            if duty_type == 'req':
                count = await scan_requests_for_member(guild, member, start_datetime, end_datetime)
            elif duty_type == 'role':
                count = await scan_roles_for_member(guild, member, start_datetime, end_datetime)
            else:
                count = 0

            merged_counts[user_id] = merged_counts.get(user_id, 0) + count
            scanned_in_guild += 1
            await cache_stat(guild_id, user_id, duty_type, count, start_date, end_date, scan_completed=scan_ok)
            logger.debug(f"    {member.display_name}: {count} {duty_type}s")

        logger.info(f"  ✅ Scanned {scanned_in_guild} users in {guild.name} for {duty_type}")

    logger.info(f"  ✅ {duty_type} TOTAL: {len(merged_counts)} users scanned")
    return merged_counts, member_display_map


async def scan_modlog_all_guilds(
    bot,
    all_staff: Dict[int, str],
    source_guilds: List[int],
    start_datetime: datetime,
    end_datetime: datetime,
    start_date: str,
    end_date: str,
) -> tuple:
    """Scan modlog for all staff (union of all duty staff) across all guilds."""
    merged:      Dict[int, int] = {}
    display_map: Dict[int, str] = {}

    for uid, name in all_staff.items():
        display_map[uid] = name
        merged[uid]      = 0

    for guild_idx, guild_id in enumerate(source_guilds):
        if guild_idx > 0:
            await asyncio.sleep(DELAY_BETWEEN_GUILDS)

        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        logger.info(f"  📋 Scanning modlog in {guild.name}...")

        for user_id in list(all_staff.keys()):
            member = guild.get_member(user_id)
            if not member:
                continue

            count = await scan_modlog_for_member(guild, member, start_datetime, end_datetime)
            merged[user_id]      = merged.get(user_id, 0) + count
            display_map[user_id] = member.display_name
            await cache_stat(guild_id, user_id, 'modlog', count, start_date, end_date)

    logger.info(f"  ✅ modlog: {len(merged)} users scanned")
    return merged, display_map


# ==================== UNIFIED HUB PAYLOAD BUILDER ====================

def _get_member_role_info(bot, uid: int, guild_ids: list):
    """Return (top_role_name, role_tier) for a user by checking all source guilds."""
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
    if duty_type == 'role':
        thresholds = [(81, 'Great', '🌟'), (61, 'Very Good', '⭐'), (41, 'Good', '✅'), (24, 'Okay', '⚠️'), (0, 'Bad', '❌')]
    else:  # req
        thresholds = [(41, 'Great', '🌟'), (21, 'Very Good', '⭐'), (10, 'Good', '✅'), (5, 'Okay', '⚠️'), (0, 'Bad', '❌')]
    for threshold, label, emoji in thresholds:
        if count >= threshold:
            return label, emoji
    return 'Bad', '❌'


def _build_unified_hub_payload(
    bot, all_stats: dict, all_display: dict, avatar_cache: dict,
    general_staff_ids: set, source_guilds: list,
    start_date: str, end_date: str,
) -> dict:
    """Build the new user-centric duties.json schema for the Wave Staff Hub page."""
    import math
    from datetime import datetime, timezone

    # Collect all unique UIDs
    duty_uids: dict[int, set] = {}  # uid → set of duty types they hold
    for dt in ('req', 'role'):
        for uid in set(all_stats.get(dt, {}).keys()) | set(all_display.get(dt, {}).keys()):
            duty_uids.setdefault(int(uid), set()).add(dt)

    all_uids = set(duty_uids.keys()) | general_staff_ids

    # Compute positions per duty type (sorted by count desc, away last)
    def _positions(duty_type: str) -> dict:
        stats = all_stats.get(duty_type, {})
        display = all_display.get(duty_type, {})
        entries = []
        for uid in set(stats.keys()) | set(display.keys()):
            count = stats.get(uid, 0)
            if isinstance(count, dict):
                count = count.get('count', 0)
            entries.append((int(uid), count, check_if_user_is_away(bot, uid)))
        entries.sort(key=lambda e: (e[2], -e[1]))  # away last, then count desc
        return {uid: (pos + 1, len(entries)) for pos, (uid, _, _) in enumerate(entries)}

    role_positions = _positions('role')
    req_positions  = _positions('req')

    users = {}
    for uid in all_uids:
        uid = int(uid)
        name = (
            all_display.get('role', {}).get(uid) or
            all_display.get('req', {}).get(uid) or
            all_display.get('message', {}).get(uid) or
            all_display.get('modlog', {}).get(uid) or
            f'User {uid}'
        )
        avatar_url = avatar_cache.get(uid)
        is_away = check_if_user_is_away(bot, uid)
        away_type = 'normal' if is_user_normal_away(bot, uid) else ('immunity' if is_away else None)
        top_role, role_tier = _get_member_role_info(bot, uid, source_guilds)

        entry: dict = {
            'user_id': uid,
            'name': name,
            'top_role': top_role,
            'role_tier': role_tier,
            'avatar_url': avatar_url,
            'is_away': is_away,
        }
        if away_type:
            entry['away_type'] = away_type

        # ── Duties ────────────────────────────────────────────────────────
        if uid in duty_uids:
            entry['duties'] = {}
            for dt in ('role', 'req'):
                if dt not in duty_uids[uid]:
                    continue
                raw = all_stats.get(dt, {}).get(uid, 0)
                count = raw.get('count', 0) if isinstance(raw, dict) else int(raw)
                rank_label, rank_emoji = _duty_rank(count, dt)
                pos_info = role_positions if dt == 'role' else req_positions
                pos, total = pos_info.get(uid, (0, 0))
                entry['duties'][dt] = {
                    'count': count,
                    'rank': rank_label,
                    'rank_emoji': rank_emoji,
                    'position': pos,
                    'total_in_duty': total,
                    'vbucks_earned': 0,   # filled by weekly_checks at 168h
                    'penalty_amount': 0,
                    'role_removed': False,
                    'streak_bonus': False,
                }

        # ── Engagement (general staff only) ───────────────────────────────
        if uid in general_staff_ids:
            msg_raw = all_stats.get('message', {}).get(uid, 0)
            if isinstance(msg_raw, dict):
                messages = int(msg_raw.get('count', 0))
                days_list = msg_raw.get('days', [])
                from datetime import datetime as _dt
                days_set = set()
                for d in days_list:
                    try:
                        days_set.add(_dt.fromisoformat(d).date().weekday() if isinstance(d, str) else d)
                    except Exception:
                        pass
                days_active = len(days_set)
            else:
                messages = int(msg_raw)
                days_active = 0
            mod_commands = int(all_stats.get('modlog', {}).get(uid, 0))
            rank_messages = min(math.ceil(messages / 70 * 100), 100)
            rank_days     = min(math.ceil(days_active / 7 * 100), 100)
            rank_total    = min(math.ceil((rank_messages + rank_days) / 2 + mod_commands), 100)
            entry['engagement'] = {
                'messages': messages,
                'days_active': days_active,
                'mod_commands': mod_commands,
                'rank_messages': rank_messages,
                'rank_days': rank_days,
                'rank_total': rank_total,
            }

        users[str(uid)] = entry

    return {
        '_meta': {
            'start_date': start_date,
            'end_date': end_date,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'period': 'Full Week',
        },
        'users': users,
    }


# ==================== MAIN SCAN FUNCTION ====================

async def perform_full_scan(bot):
    """
    Full duty scan — order: req → role → modlog → message → export to GitHub
    """
    try:
        rate_limit_tracker.reset()

        logger.info("\n" + "=" * 80)
        logger.info("🔍 STARTING FULL DUTY SCAN")
        logger.info("=" * 80)
        logger.info(f"⏰ Scan started at: {datetime.now(timezone.utc)}")
        logger.info(f"📍 Rate limit tracker initialized (will log all hits)")

        logger.info("📋 Loading configuration...")
        auto_config   = get_automation_config()
        source_guilds = auto_config.get('source_guilds', [])

        if not source_guilds:
            logger.warning("⚠️ No source guilds configured")
            return

        logger.info(f"  ✅ Loaded {len(source_guilds)} source guild(s): {source_guilds}")

        with open('config.json', 'r') as f:
            config = json.load(f)

        global_dates = config.get('global_dates', {})
        start_date   = global_dates.get('start_date')
        end_date     = global_dates.get('end_date')

        if not start_date or not end_date:
            logger.warning("⚠️ No global dates configured")
            return

        start_datetime = get_start_datetime(start_date)
        end_datetime   = get_end_datetime(end_date)

        logger.info(f"📅 Scan period : {start_date} → {end_date}")
        logger.info(f"🏢 Source guilds: {source_guilds}")

        all_staff_union: Dict[int, str] = {}
        all_stats:       Dict[str, Any] = {}
        all_display:     Dict[str, Any] = {}

        # ── 1. REQ ───────────────────────────────────────────────────────────
        logger.info("\n" + "─" * 60)
        logger.info("📋 [1/4] SCANNING: req (Map Request Helper)")
        logger.info("─" * 60)
        logger.info("  ⏱️ Starting req scan...")
        req_counts, req_display = await scan_duty_all_guilds(
            bot, 'req', source_guilds, start_datetime, end_datetime, start_date, end_date
        )
        all_stats['req']   = req_counts
        all_display['req'] = req_display
        all_staff_union.update(req_display)
        logger.info(f"  ✅ req scan complete: {len(req_counts)} users with counts")
        logger.info(f"  📊 Total req counts: {sum(req_counts.values())} actions found")
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # ── 2. ROLE ──────────────────────────────────────────────────────────
        logger.info("\n" + "─" * 60)
        logger.info("📋 [2/4] SCANNING: role (Role Giver)")
        logger.info("─" * 60)
        logger.info("  ⏱️ Starting role scan (optimised single-sweep per guild)...")
        role_counts, role_display = await scan_duty_all_guilds(
            bot, 'role', source_guilds, start_datetime, end_datetime, start_date, end_date
        )
        all_stats['role']   = role_counts
        all_display['role'] = role_display
        all_staff_union.update(role_display)
        logger.info(f"  ✅ role scan complete: {len(role_counts)} users with counts")
        logger.info(f"  📊 Total role counts: {sum(role_counts.values())} actions found")
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # ── Collect general staff ─────────────────────────────────────────────
        logger.info("\n" + "─" * 60)
        logger.info("👥 Collecting general staff for modlog + message scans...")
        logger.info("─" * 60)
        general_staff_ids: set = set()
        for guild_id in source_guilds:
            guild = bot.get_guild(guild_id)
            if not guild:
                continue
            general      = find_general_staff(guild)
            general_staff_ids.update(int(uid) for uid in general.keys())
            before_count = len(all_staff_union)
            all_staff_union.update(general)
            added = len(all_staff_union) - before_count
            logger.info(f"  ✅ {guild.name}: found {len(general)} general staff ({added} new to union)")
        logger.info(f"  📋 Total staff union for modlog/message: {len(all_staff_union)} members")

        # ── 4. MODLOG ────────────────────────────────────────────────────────
        logger.info("\n" + "─" * 60)
        logger.info("📋 [3/4] SCANNING: modlog (Mod Commands)")
        logger.info("─" * 60)
        logger.info("  ⏱️ Starting modlog scan...")
        logger.info(f"  📋 Scanning for {len(all_staff_union)} staff members...")
        modlog_counts, modlog_display = await scan_modlog_all_guilds(
            bot, all_staff_union, source_guilds, start_datetime, end_datetime, start_date, end_date
        )
        all_stats['modlog']   = modlog_counts
        all_display['modlog'] = modlog_display
        logger.info(f"  ✅ modlog scan complete: {len(modlog_counts)} users scanned")
        logger.info(f"  📊 Total modlog counts: {sum(modlog_counts.values())} commands found")
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # ── 5. MESSAGES ──────────────────────────────────────────────────────
        logger.info("\n" + "─" * 60)
        logger.info("📋 [4/4] SCANNING: message (Messages)")
        logger.info("─" * 60)
        logger.info("  ⏱️ Starting message scan (OPTIMIZED MODE)...")
        logger.info(f"  📨 Scanning for {len(all_staff_union)} staff members...")
        message_counts, message_display = await scan_messages_all_guilds_optimized(
            bot, all_staff_union, source_guilds, start_datetime, end_datetime, start_date, end_date
        )
        all_stats['message']   = message_counts
        all_display['message'] = message_display
        logger.info(f"  ✅ message scan complete: {len(message_counts)} users with message data")
        logger.info(
            f"  📊 Total messages found: "
            f"{sum(v['count'] if isinstance(v, dict) else v for v in message_counts.values())} messages"
        )
        await asyncio.sleep(DELAY_BETWEEN_DUTIES)

        # ── Save + push to GitHub ─────────────────────────────────────────────
        logger.info("\n" + "─" * 60)
        logger.info("📤 Saving duties data to GitHub...")
        logger.info("─" * 60)
        try:
            import os as _os
            duties_data = {}
            logger.info(f"  📝 Building export data for 5 duty types...")

            duties_data['_meta'] = {
                'start_date':  start_date,
                'end_date':    end_date,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }

            # Load existing JSON so we can preserve any divisors set by >setdivisor
            existing_duties_data = {}
            try:
                _existing_path = _os.path.join(_os.path.dirname(__file__), '..', 'json_data', 'duties_totals.json')
                if _os.path.exists(_existing_path):
                    import json as _json_existing
                    with open(_existing_path, 'r') as _ef:
                        existing_duties_data = _json_existing.load(_ef)
            except Exception as _e:
                logger.warning(f'  ⚠️ Could not load existing duties_totals.json for divisor check: {_e}')

            # Pre-fetch avatars ONCE per unique user across all duties.
            # Fetching inside the per-duty loop caused up to 88 rapid /users/{id}
            # calls with no delay → 429 rate-limit burst. Now we fetch each user
            # once with a 500 ms gap (~11 s total for 22 staff, well under limits).
            _all_export_uids: set = set()
            for _dt in ['req', 'role', 'modlog', 'message']:
                _all_export_uids |= set(all_stats.get(_dt, {}).keys()) | set(all_display.get(_dt, {}).keys())
            logger.info(f"  🖼️ Pre-fetching avatars for {len(_all_export_uids)} unique user(s)...")
            _avatar_cache: Dict[int, Optional[str]] = {}
            for _uid in _all_export_uids:
                try:
                    _u = await bot.fetch_user(int(_uid))
                    _avatar_cache[int(_uid)] = str(_u.display_avatar.url) if _u and _u.display_avatar else None
                except Exception as _ae:
                    logger.debug(f"      ⚠️ Avatar fetch failed for {_uid}: {_ae}")
                    _avatar_cache[int(_uid)] = None
                await asyncio.sleep(0.5)  # 500 ms between fetches — safe under Discord rate limits
            logger.info(f"  ✅ Avatar pre-fetch complete ({len(_avatar_cache)} cached)")

            for duty_type in ['req', 'role', 'modlog', 'message']:
                duties_data[duty_type] = {}
                stats    = all_stats.get(duty_type, {})
                members  = all_display.get(duty_type, {})
                all_uids = set(stats.keys()) | set(members.keys())
                logger.info(f"    • {duty_type}: {len(all_uids)} users total ({len(stats)} with scan data)")

                for uid in all_uids:
                    days_of_week_active = 0
                    if (
                        duty_type == 'message'
                        and isinstance(stats.get(uid), dict)
                        and 'days' in stats.get(uid, {})
                    ):
                        days_list = stats[uid].get('days', [])
                        if isinstance(days_list, list) and days_list:
                            from datetime import datetime as dt_module
                            days_of_week_set = set()
                            for day_str in days_list:
                                try:
                                    date_obj = dt_module.fromisoformat(day_str).date() if isinstance(day_str, str) else day_str
                                    days_of_week_set.add(date_obj.weekday())
                                except Exception:
                                    pass
                            days_of_week_active = len(days_of_week_set)

                    count = stats.get(uid, 0)
                    if isinstance(count, dict):
                        count = count.get('count', 0)

                    # Apply manual override or divisor if set
                    raw_count      = count
                    existing_entry = existing_duties_data.get(duty_type, {}).get(str(uid), {})
                    
                    is_override    = existing_entry.get('is_override', False)
                    divisor        = existing_entry.get('divisor', 1)

                    if is_override:
                        count = existing_entry.get('count', 0)
                        logger.info(f'    🔒 Override preserved for {uid} {duty_type}: {count} (raw: {raw_count})')
                    elif divisor and divisor > 1:
                        count = max(0, count // divisor)
                        logger.info(f'    ✂️ Divisor /{divisor} applied to {uid} {duty_type}: {raw_count} → {count}')

                    entry = {
                        'name':  members.get(uid, f'User {uid}'),
                        'count': count,
                        'uid':   uid
                    }

                    if is_override:
                        entry['is_override'] = True
                        entry['raw_count'] = raw_count

                    if divisor and divisor > 1:
                        entry['divisor']   = divisor
                        if not is_override:
                            entry['raw_count'] = raw_count

                    if duty_type == 'message' and days_of_week_active > 0:
                        entry['days_of_week_active'] = days_of_week_active

                    # Check away status — away users can't earn points and are exempt from penalties
                    if check_if_user_is_away(bot, uid):
                        if is_user_normal_away(bot, uid):
                            entry['away'] = 'normal'
                        else:
                            entry['away'] = 'away_immunity'

                    # Avatar URL — use pre-fetched cache (avoids per-iteration API calls)
                    entry['avatar_url'] = _avatar_cache.get(int(uid))

                    duties_data[duty_type][str(uid)] = entry

            json_path = _os.path.join(_os.path.dirname(__file__), '..', 'json_data', 'duties_totals.json')
            logger.info(f"  💾 Writing to {json_path}...")
            with open(json_path, 'w') as f:
                import json as _json
                _json.dump(duties_data, f, indent=2)
            logger.info(f"  ✅ Saved duties_totals.json locally")

            # ── Build + push NEW unified schema to hub ─────────────────────
            logger.info(f"  🔗 Building unified hub schema...")
            try:
                import json as _json, os as _os
                from tasks.staff_hub_writer import push_duties_to_github
                hub_payload = _build_unified_hub_payload(
                    bot, all_stats, all_display, _avatar_cache,
                    general_staff_ids, source_guilds,
                    start_date, end_date,
                )
                # Carry forward completed-week history from existing file
                _hub_path = _os.path.join(_os.path.dirname(__file__), '..', 'website', 'data', 'duties.json')
                try:
                    with open(_hub_path, 'r', encoding='utf-8') as _hf:
                        _existing = _json.load(_hf)
                    hub_payload['weeks'] = _existing.get('weeks', [])
                except Exception:
                    hub_payload['weeks'] = []
                await push_duties_to_github(hub_payload)
                logger.info(f"  ✅ Hub payload pushed ({len(hub_payload.get('users', {}))} users)")
            except Exception as _pe:
                logger.warning(f"  ⚠️ Hub payload push failed: {_pe}")

        except Exception as e:
            logger.error(f"  ❌ Failed to save duties data: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # ── Other leaderboard systems ─────────────────────────────────────────
        logger.info("\n📊 Triggering other leaderboard updates...")
        try:
            from tasks.leaderboard_updater import auto_update_vbucks_leaderboard
            # Single call rebuilds the combined role+req web leaderboard and pushes once.
            try:
                await auto_update_vbucks_leaderboard(bot, "all", triggered_by="duty_scan_completion")
            except Exception as e:
                logger.error(f"  ❌ vbucks web LB: {e}")
            # (strike leaderboard call removed — strike system retired)
        except ImportError:
            logger.warning("⚠️ leaderboard_updater not found — skipping")

        # ── Check and award weekly challenges ─────────────────────────────────
        logger.info("\n📊 Checking for challenge completions...")
        try:
            from tasks.random_challenges import check_and_complete_challenges
            await check_and_complete_challenges(bot, all_stats)
            logger.info("✅ Challenge completion check complete")
        except Exception as e:
            logger.error(f"❌ Challenge check error: {e}")

        logger.info("\n" + "=" * 80)
        logger.info("✅ FULL DUTY SCAN COMPLETE")
        logger.info("=" * 80)
        logger.info(f"📊 FINAL SUMMARY:")
        logger.info(f"  • req:     {len(all_stats.get('req', {}))} users")
        logger.info(f"  • role:    {len(all_stats.get('role', {}))} users")
        logger.info(f"  • modlog:  {len(all_stats.get('modlog', {}))} users")
        logger.info(f"  • message: {len(all_stats.get('message', {}))} users")
        logger.info(f"  ⏰ Scan finished at: {datetime.now(timezone.utc)}")
        logger.info(f"  📡 Rate limits encountered: {rate_limit_tracker.hit_count}")
        if rate_limit_tracker.hit_count > 0:
            logger.info(f"     (See duties_scan_rate_limits.log for details)")
        logger.info(f"  ✨ Export complete - leaderboard updated on GitHub")

    except Exception as e:
        logger.error(f"❌ Error in perform_full_scan: {e}")
        import traceback
        logger.error(traceback.format_exc())


# ==================== EXACT TIMING LOOP ====================

async def run_scans_at_exact_intervals(bot):
    """Run duty scans at EXACT 4-hour marks: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC"""
    await bot.wait_until_ready()
    logger.info("✅ Duty scans task is now active and waiting for triggers")

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Clash check with major reports — skip if within ±2 hours of any scheduled task
            try:
                with open('config.json', 'r') as f:
                    config = json.load(f)
                global_dates = config.get('global_dates', {})
                start_date   = global_dates.get('start_date')
                if start_date:
                    start_dt    = get_start_datetime(start_date)
                    major_times = [
                        start_dt + timedelta(hours=72),
                        start_dt + timedelta(hours=72 + 30/60),
                        start_dt + timedelta(hours=168),
                        start_dt + timedelta(hours=168 + 30/60),
                        start_dt + timedelta(hours=169),
                        start_dt + timedelta(hours=169 + 30/60),
                    ]
                    CLASH_BUFFER = 2 * 3600
                    for rt in major_times:
                        if abs((now - rt).total_seconds()) < CLASH_BUFFER:
                            logger.info(f"⏭️ Skipping — within 2 hours of major report at {rt}")
                            await asyncio.sleep(300)
                            continue
            except Exception:
                pass

            # Next valid scan hour
            next_hour = None
            for hour in VALID_SCAN_HOURS:
                candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
                if candidate > now:
                    next_hour = candidate
                    break
            if not next_hour:
                tomorrow  = now + timedelta(days=1)
                next_hour = tomorrow.replace(hour=VALID_SCAN_HOURS[0], minute=0, second=0, microsecond=0)

            wait_seconds = (next_hour - now).total_seconds()
            logger.info(f"⏰ Next duty scan: {next_hour} UTC (in {wait_seconds / 3600:.1f}h)")
            await asyncio.sleep(wait_seconds)

            now = datetime.now(timezone.utc)
            if (now - next_hour).total_seconds() > 3600:
                logger.warning(f"⚠️ Woke up too late — skipping this scan")
                continue

            logger.info(f"🕐 RUNNING 4-HOUR DUTY SCAN at {now}")
            await perform_full_scan(bot)
            logger.info(f"✅ 4-HOUR DUTY SCAN COMPLETE")

        except Exception as e:
            logger.error(f"❌ Error in duty scan scheduler: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await asyncio.sleep(300)


# ==================== COG ====================

class DutiesScansCog(commands.Cog):
    """Background duty scan every 4 hours with exact timing"""

    def __init__(self, bot):
        self.bot  = bot
        self.task = None
        logger.info("✅ Duty scans automation initialized")

    async def cog_load(self):
        logger.info("🚀 Starting Duty scans automation...")
        logger.info(f"🕐 Valid scan hours: {VALID_SCAN_HOURS} UTC")
        logger.info(
            f"📋 Leaderboard channels: role={LEADERBOARD_CHANNELS['role']}, "
            f"req={LEADERBOARD_CHANNELS['req']}"
        )
        self.task = asyncio.create_task(run_scans_at_exact_intervals(self.bot))
        logger.info("✅ Task created! (will activate when bot is ready)")

    def cog_unload(self):
        if self.task:
            self.task.cancel()
        logger.info("🛑 Duty scans loop stopped")


async def setup(bot):
    await bot.add_cog(DutiesScansCog(bot))
    logger.info("✅ Duty scans cog loaded")