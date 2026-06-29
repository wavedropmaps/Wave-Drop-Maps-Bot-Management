"""DEPRECATED - thin re-export shim. All logic moved to tasks/unified_weekly_loop.py."""
import logging

logger = logging.getLogger('discord')

from tasks.unified_weekly_loop import (
    process_single_duty,
    SOURCE_GUILDS,
    REPORT_GUILD_ID,
    MID_WEEK_HOURS,
    FULL_WEEK_HOURS,
    REPORT_CHANNELS,
    get_performance_rank,
    get_ranking_explanation,
    remove_role_in_guilds,
    is_user_newly_added,
    create_report_embed,
    _augment_duties_hub_json,
    collect_staff_data_with_progress,
    collect_staff_data,
    get_global_dates_from_config,
    monitor_role_assignments,
)


# Inert cog — do NOT start the old loops. unified_weekly_loop handles everything.
class WeeklyChecks:
    """DEPRECATED — use UnifiedWeeklyLoop from tasks.unified_weekly_loop instead."""
    pass


async def setup(bot):
    logger.info("weekly_checks.py is DEPRECATED — all logic in tasks/unified_weekly_loop.py")
"""
Weekly Staff Activity Checks - COMPLETE REWRITE
✅ Sequential duty processing (scan → report → vbucks)
✅ Beautiful embed formatting (like the screenshot)
✅ Rate limiting to prevent API abuse
✅ Prevents duplicate scanning
✅ Improved name matching with word boundaries
✅ Progress updates in Discord and terminal
✅ Uses database functions directly
✅ Role scan accumulates counts across ALL guilds
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import logging
import database
import asyncio
from core.helpers import (
    get_start_datetime,
    get_end_datetime,
    safe_history_fetch,
    is_reply_to_other,
    extract_embed_content,
    check_if_user_is_away,
    is_user_normal_away
)
from core.cache import config_cache
import json
import traceback
import re
from math import ceil
from tasks.wave_points import add_wave_points, get_wave_points

logger = logging.getLogger('discord')

# ==================== CONSTANTS ====================
SOURCE_GUILDS = [988564962802810961, 971731167621574666]
REPORT_GUILD_ID = 1041450125391835186

REPORT_CHANNELS = {
    'req': 1213937694921728020
}

MID_WEEK_HOURS = 72
FULL_WEEK_HOURS = 168

# ==================== RATE LIMITING ====================
RATE_LIMIT_DELAY = 0.5  # 500ms between API calls
BATCH_DELAY = 2.0  # 2 seconds between processing batches
DM_DELAY = 1.0  # 1 second between DMs

# ==================== PERFORMANCE RANKING ====================

def get_performance_rank(count: int, report_type: str, period: str) -> dict:
    """Get performance ranking and message"""

    if period == "Mid-Week":
        if report_type == 'req':
            if count < 5:
                return {'rank': '❌ Bad', 'message': 'Need to do more', 'emoji': '❌'}
            elif 5 <= count <= 10:
                return {'rank': '✅ Good', 'message': 'Try to do more', 'emoji': '✅'}
            elif 11 <= count <= 20:
                return {'rank': '⭐ Very Good', 'message': '', 'emoji': '⭐'}
            else:
                return {'rank': '🌟 Great', 'message': '', 'emoji': '🌟'}
    elif period == "Full Week":
        if report_type == 'req':
            if count < 10:
                return {'rank': '❌ Bad', 'message': 'Need to do more', 'emoji': '❌'}
            elif 10 <= count <= 20:
                return {'rank': '✅ Good', 'message': '', 'emoji': '✅'}
            elif 21 <= count <= 40:
                return {'rank': '⭐ Very Good', 'message': '', 'emoji': '⭐'}
            else:
                return {'rank': '🌟 Great', 'message': '', 'emoji': '🌟'}
    return {'rank': 'N/A', 'message': '', 'emoji': '❓'}

def get_ranking_explanation(report_type: str, period: str) -> str:
    """Get ranking explanation"""

    if period == "Mid-Week":
        if report_type == 'req':
            return "🌟 Great (21+) | ⭐ Very Good (11–20) | ✅ Good (5–10) | ❌ Bad (≤4)"

    elif period == "Full Week":
        if report_type == 'req':
            return "🌟 Great (41+) | ⭐ Very Good (21–40) | ✅ Good (10–20) | ❌ Bad (≤9)"

    return "N/A"

async def remove_role_in_guilds(bot, user_id: int, duty_type: str) -> bool:
    """Remove a duty role from user across all SOURCE_GUILDS and REPORT_GUILD_ID."""
    # Map duty types to role name patterns
    role_patterns = {
        'req': 'map request helper'
    }

    role_pattern = role_patterns.get(duty_type)
    if not role_pattern:
        logger.error(f"Unknown duty type for role removal: {duty_type}")
        return False

    removed_from_any = False

    for guild_id in SOURCE_GUILDS + [REPORT_GUILD_ID]:
        guild = bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"  Guild {guild_id} not found for role removal")
            continue

        member = guild.get_member(user_id)
        if not member:
            logger.debug(f"  User {user_id} not in guild {guild.name}")
            continue

        # Find matching role
        role_to_remove = None
        for role in guild.roles:
            role_name_lower = role.name.lower()
            if role_pattern == 'map request helper':
                if role_name_lower == 'map request helper':
                    role_to_remove = role
                    break
            else:
                if role_pattern in role_name_lower:
                    role_to_remove = role
                    break

        if not role_to_remove:
            logger.debug(f"  {duty_type} role not found in guild {guild.name}")
            continue

        if role_to_remove not in member.roles:
            logger.debug(f"  User {user_id} doesn't have {duty_type} role in {guild.name}")
            continue

        try:
            await member.remove_roles(role_to_remove)
            logger.info(f"  ✅ Removed {duty_type} role from {member.name} in {guild.name}")
            removed_from_any = True
        except Exception as e:
            logger.error(f"  ❌ Failed to remove {duty_type} role from {member.name} in {guild.name}: {e}")

    return removed_from_any

# ==================== NEW MEMBER IMMUNITY ====================

async def is_user_newly_added(bot, user_id: int, duty_type: str, days_threshold: int = 4) -> bool:
    """
    Check if a user was added to a duty role within the last N days (from database).
    Returns True if newly added (immune), False if not.
    """
    return await database.is_user_newly_assigned(user_id, duty_type, days_threshold=days_threshold)

# ==================== SCANNING FUNCTIONS ====================

async def scan_requests(bot, guild, member, start_datetime, end_datetime):
    """
    Scan request channel
    ✅ Rate limited
    """
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
            request_channel, 
            limit=5000, 
            after=start_datetime, 
            before=end_datetime
        )
        
        for message in messages:
            # Only count messages where this member replied to someone else
            # (an actual help action), not every message they post here.
            if message.author.id == member.id and is_reply_to_other(message):
                count += 1

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Error scanning requests for {member.name}: {e}")

    return count

# ==================== EMBED REPORT CREATION ====================

def create_report_embed(duty_type: str, period: str, staff_data: dict, start_date: str, end_date: str, guild_names: list, bot=None, immune_users: set = None) -> discord.Embed:
    """
    Create a beautiful embed report (like the screenshot)

    immune_users: user_ids that are newly added (< 4 days). They are STILL shown
    in the activity list, tagged "🆕 New Staff", but are excluded from the
    rankings breakdown / performance percentages so they don't skew the stats
    (and they're already exempt from warnings/penalties/VBucks elsewhere).
    """
    if immune_users is None:
        immune_users = set()
    
    duty_info = {
        'req': {'emoji': '🗺️', 'name': 'Map Request Activity Report'},
    }
    
    info = duty_info.get(duty_type, {'emoji': '📊', 'name': 'Activity Report'})
    
    if period == "Mid-Week":
        title_period = f"{start_date} → {end_date} (Mid-Week)"
    else:
        title_period = f"{start_date} → {end_date} (Full Week)"
    
    embed = discord.Embed(
        title=f"{info['emoji']} {info['name']} - {title_period}",
        description=f"**Period:** {start_date} → {end_date}",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )
    
    sources_text = "\n".join([f"• {name}" for name in guild_names])
    embed.add_field(name="📊 Data Sources", value=sources_text, inline=False)
    
    sorted_staff = sorted(
        [(user_id, data) for user_id, data in staff_data.items()],
        key=lambda x: x[1][duty_type],
        reverse=True
    )
    
    activity_lines = []
    for idx, (user_id, data) in enumerate(sorted_staff, start=1):
        count = data[duty_type]

        away_tag = ""
        if bot and is_user_normal_away(bot, user_id):
            away_tag = " 🏖️ Away"

        if user_id in immune_users:
            # Newly added staff: shown for visibility, but immune this week —
            # no rank judgement, no penalty.
            line = f"{idx}. **{data['name']}**{away_tag} - {count} 🆕 New Staff • Immune this week (no penalty)"
        else:
            rank_info = get_performance_rank(count, duty_type, period)
            line = f"{idx}. **{data['name']}**{away_tag} - {count} {rank_info['rank']}"
            if rank_info['message']:
                line += f" • {rank_info['message']}"

        activity_lines.append(line)
    
    if activity_lines:
        activity_text = "\n".join(activity_lines)
        if len(activity_text) > 1024:
            chunks = []
            current_chunk = []
            current_length = 0
            
            for line in activity_lines:
                if current_length + len(line) + 1 > 1024:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = [line]
                    current_length = len(line)
                else:
                    current_chunk.append(line)
                    current_length += len(line) + 1
            
            if current_chunk:
                chunks.append("\n".join(current_chunk))
            
            for i, chunk in enumerate(chunks):
                field_name = "📋 Staff Activity" if i == 0 else f"Staff Activity (cont. {i})"
                embed.add_field(name=field_name, value=chunk, inline=False)
        else:
            embed.add_field(name="📋 Staff Activity", value=activity_text, inline=False)
    
    # Stats are computed over SCORED staff only (exclude immune/new staff) so the
    # rankings breakdown and percentages reflect who's actually being judged.
    scored_staff = {uid: data for uid, data in staff_data.items() if uid not in immune_users}
    new_staff_count = len(staff_data) - len(scored_staff)

    total_staff = len(scored_staff)
    active_staff = sum(1 for data in scored_staff.values() if data[duty_type] > 0)
    total_actions = sum(data[duty_type] for data in scored_staff.values())

    rank_counts = {'🌟': 0, '⭐': 0, '✅': 0, '⚠️': 0, '❌': 0}
    for user_id, data in scored_staff.items():
        count = data[duty_type]
        rank_info = get_performance_rank(count, duty_type, period)
        emoji = rank_info['emoji']
        if emoji in rank_counts:
            rank_counts[emoji] += 1

    summary_text = (
        f"**Total Staff:** {total_staff}\n"
        f"**Active Staff:** {active_staff}\n"
        f"**Total Actions:** {total_actions}"
    )
    if new_staff_count > 0:
        summary_text += f"\n**🆕 New Staff (immune):** {new_staff_count}"
    embed.add_field(name="📊 Summary", value=summary_text, inline=False)
    
    rankings_text = (
        f"🌟 Great: {rank_counts['🌟']}\n"
        f"⚠️ Okay: {rank_counts.get('⚠️', 0)}\n"
        f"❌ Bad: {rank_counts['❌']}"
    )
    
    if rank_counts.get('⭐', 0) > 0:
        rankings_text = f"🌟 Great: {rank_counts['🌟']}\n⭐ Very Good: {rank_counts['⭐']}\n✅ Good: {rank_counts['✅']}\n⚠️ Okay: {rank_counts.get('⚠️', 0)}\n❌ Bad: {rank_counts['❌']}"
    elif rank_counts.get('✅', 0) > 0:
        rankings_text = f"🌟 Great: {rank_counts['🌟']}\n✅ Good: {rank_counts['✅']}\n⚠️ Okay: {rank_counts.get('⚠️', 0)}\n❌ Bad: {rank_counts['❌']}"
    
    embed.add_field(name="🏆 Rankings Breakdown", value=rankings_text, inline=False)
    
    if total_staff > 0:
        great_percent = (rank_counts['🌟'] / total_staff) * 100
        bad_percent = (rank_counts['❌'] / total_staff) * 100
        performance_text = f"Great (4+): {great_percent:.0f}%\nBad (<1): {bad_percent:.0f}%"
        embed.add_field(name="📈 Performance:", value=performance_text, inline=False)
    
    embed.add_field(
        name="ℹ️ What do the rankings mean?",
        value=f"**Rankings:**\n{get_ranking_explanation(duty_type, period)}",
        inline=False
    )
    
    embed.set_footer(text=f"Generated at • {datetime.now(timezone.utc).strftime('%d/%m/%Y, %I:%M %p')}")
    
    return embed

# ==================== SEQUENTIAL DUTY PROCESSING ====================

async def process_single_duty(bot, duty_type, guild_ids, start_datetime, end_datetime, period, start_date, end_date, progress_message=None):
    """
    ✅ Process ONE duty completely: scan → report → warnings → vbucks
    ✅ Counts are accumulated across ALL guilds (no early-exit dedup)
    ✅ Full rate limiting throughout
    ✅ Beautiful embed reports
    ✅ FIXED: Uses database functions directly

    Returns: dict of {user_id: {'name': str, duty_type: count}}
    """
    
    thresholds = {
        'Mid-Week': {'req': 5},
        'Full Week': {'req': 10}
    }

    duty_names = {
        'req':   '🗺️ Map Request Helper'
    }

    duty_emoji = {
        'req': '🗺️',
    }
    
    emoji = duty_emoji.get(duty_type, '📊')
    
    logger.info(f"\n{emoji} ========================================")
    logger.info(f"{emoji} PROCESSING {duty_type.upper()} DUTY")
    logger.info(f"{emoji} Period: {period}")
    logger.info(f"{emoji} ========================================")
    
    if progress_message:
        try:
            await progress_message.edit(content=f"{emoji} **Processing {duty_type.upper()} duty...**\n\n**Step 1/5:** Finding staff members...")
        except:
            pass
    
    # ==================== STEP 1: FIND STAFF WITH THIS DUTY ====================
    
    staff_with_duty = {}
    
    for guild_id in guild_ids:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        
        logger.info(f"  📊 Finding {duty_type} staff in: {guild.name}")
        
        duty_roles = []
        
        for role in guild.roles:
            role_name_lower = role.name.lower()
            
            if duty_type == 'req' and role_name_lower == "map request helper":
                duty_roles.append(role)
                logger.info(f"    ✅ Found request role: {role.name} ({len(role.members)} members)")
        
        for role in duty_roles:
            for member in role.members:
                if not member.bot:
                    if member.id not in staff_with_duty:
                        staff_with_duty[member.id] = {
                            'name': member.name,
                            duty_type: 0
                        }
    
    logger.info(f"  ✅ Found {len(staff_with_duty)} total staff with {duty_type} duty")

    if len(staff_with_duty) == 0:
        logger.warning(f"  ⚠️ No staff found with {duty_type} duty - skipping")
        return staff_with_duty

    # ==================== STEP 1.5: IDENTIFY NEW MEMBERS (IMMUNE) ====================

    immune_users = set()
    logger.info(f"  🆕 Checking for newly added staff (immune if < 4 days)...")

    for user_id in list(staff_with_duty.keys()):
        is_new = await is_user_newly_added(bot, user_id, duty_type, days_threshold=4)
        if is_new:
            immune_users.add(user_id)

    if immune_users:
        logger.info(f"  🛡️ {len(immune_users)} immune user(s) found - will be excluded from report/penalties")

    # ==================== STEP 2: SCAN ACTIVITY ====================
    
    if progress_message:
        try:
            await progress_message.edit(content=f"{emoji} **Processing {duty_type.upper()} duty...**\n\n**Step 2/5:** Scanning activity across guilds...")
        except:
            pass
    
    logger.info(f"  {emoji} Scanning {duty_type} activity...")

    # ✅ FIXED: Loop every guild for every user and ACCUMULATE counts.
    # The old code used a scanned_users set which caused users to be skipped
    # after the first guild — meaning role givers only had one guild's audit
    # logs counted. Now we scan every guild a user appears in and add it up.
    for guild_id in guild_ids:
        guild = bot.get_guild(guild_id)
        if not guild:
            continue

        logger.info(f"    📡 Scanning {duty_type} in {guild.name}...")
        scanned_in_this_guild = 0

        for user_id in staff_with_duty.keys():
            member = guild.get_member(user_id)
            if not member:
                continue  # Not in this guild — skip this guild, still scan others

            if duty_type == 'req':
                count = await scan_requests(bot, guild, member, start_datetime, end_datetime)
            else:
                count = 0

            # ✅ FIXED: += accumulates across guilds instead of = which overwrote
            staff_with_duty[user_id][duty_type] += count
            scanned_in_this_guild += 1

            logger.debug(f"      {member.name}: +{count} {duty_type}s from {guild.name} (total: {staff_with_duty[user_id][duty_type]})")

        logger.info(f"    ✅ Scanned {scanned_in_this_guild} users in {guild.name}")

    total_scanned_count = sum(data[duty_type] for data in staff_with_duty.values())
    users_with_activity = sum(1 for data in staff_with_duty.values() if data[duty_type] > 0)
    
    logger.info(f"  ✅ {duty_type.upper()} SCAN COMPLETE:")
    logger.info(f"    • Total actions (raw): {total_scanned_count}")
    logger.info(f"    • Users with activity: {users_with_activity}/{len(staff_with_duty)}")

    # ==================== STEP 2.1: APPLY MANUAL OVERRIDES & DIVISORS ====================
    logger.info(f"  📝 Checking for manual duty overrides and divisors...")
    try:
        import os as _os
        duties_json_path = _os.path.join(_os.path.dirname(__file__), '..', 'duties_totals.json')
        if _os.path.exists(duties_json_path):
            with open(duties_json_path, 'r') as f:
                duties_data = json.load(f)
                overrides = duties_data.get(duty_type, {})
                
            for user_id in staff_with_duty.keys():
                uid_str = str(user_id)
                if uid_str in overrides:
                    entry = overrides[uid_str]
                    is_override = entry.get('is_override', False)
                    divisor = entry.get('divisor', 1)
                    
                    if is_override:
                        old_val = staff_with_duty[user_id][duty_type]
                        new_val = entry.get('count', old_val)
                        staff_with_duty[user_id][duty_type] = new_val
                        logger.info(f"    🔒 Override applied for {staff_with_duty[user_id]['name']}: {old_val} → {new_val}")
                    elif divisor and divisor > 1:
                        old_val = staff_with_duty[user_id][duty_type]
                        new_val = max(0, old_val // divisor)
                        staff_with_duty[user_id][duty_type] = new_val
                        logger.info(f"    ✂️ Divisor /{divisor} applied for {staff_with_duty[user_id]['name']}: {old_val} → {new_val}")
    except Exception as e:
        logger.error(f"  ❌ Error applying overrides: {e}")

    total_final_count = sum(data[duty_type] for data in staff_with_duty.values())
    if total_final_count != total_scanned_count:
        logger.info(f"  📊 Total actions (adjusted): {total_final_count}")
    
    await asyncio.sleep(BATCH_DELAY)
    
    # ==================== STEP 2.5: CLEANUP MISSING USERS ====================
    
    logger.info(f"  🧹 Checking for users no longer in {duty_type} duty...")
    
    try:
        all_db_users = await database.get_all_users_for_duty(duty_type)
        missing_users = set(all_db_users) - set(staff_with_duty.keys())
        
        if missing_users:
            logger.warning(f"  ⚠️ Found {len(missing_users)} user(s) no longer in {duty_type} duty - cleaning up...")
            
            cleanup_count = 0
            for user_id in missing_users:
                try:
                    # Single-wallet model: VBucks live in one shared `main` wallet and are
                    # NOT tied to a specific duty, so leaving a duty must NOT wipe the
                    # balance. Just note the departure (leaderboard hides them via role check).
                    cleanup_count += 1
                    logger.warning(f"    🧹 User {user_id} no longer in {duty_type} duty (economy untouched — shared wallet)")

                    await asyncio.sleep(RATE_LIMIT_DELAY)

                except Exception as e:
                    logger.error(f"    ❌ Failed to cleanup user {user_id}: {e}")
            
            logger.info(f"  ✅ Cleanup complete: {cleanup_count}/{len(missing_users)} users cleaned")
        else:
            logger.info(f"  ✅ All users still present - no cleanup needed")
    
    except Exception as e:
        logger.error(f"  ❌ Error during cleanup phase: {e}")
    
    # ==================== STEP 3: SEND EMBED REPORT ====================
    
    if progress_message:
        try:
            await progress_message.edit(content=f"{emoji} **Processing {duty_type.upper()} duty...**\n\n**Step 3/5:** Sending report to Discord...")
        except:
            pass
    
    # Send embed report to the configured Discord channel
    try:
        report_channel_id = REPORT_CHANNELS.get(duty_type)
        report_guild = bot.get_guild(REPORT_GUILD_ID)
        report_channel = report_guild.get_channel(report_channel_id) if report_guild and report_channel_id else None

        if report_channel:
            guild_names = [bot.get_guild(gid).name for gid in SOURCE_GUILDS if bot.get_guild(gid)]
            embed = create_report_embed(duty_type, period, staff_with_duty, start_date, end_date, guild_names, bot=bot, immune_users=immune_users)
            await report_channel.send(embed=embed)
            logger.info(f"  ✅ Report embed sent to #{report_channel.name}")
        else:
            logger.warning(f"  ⚠️ No report channel found for duty_type={duty_type}")

        await database.mark_report_sent(REPORT_GUILD_ID, duty_type, period, start_date, end_date)
        logger.info(f"  ✅ Logged report completion to database")
    except Exception as e:
        logger.error(f"  ❌ Failed to send report: {e}")

    await asyncio.sleep(BATCH_DELAY)

    # ==================== STEP 3.5: MID-WEEK WARNING DMs ====================

    if period == "Mid-Week":
        full_week_bad_threshold = {'req': 10}.get(duty_type, 0)
        duty_name = duty_names.get(duty_type, duty_type)

        warn_sent = 0
        warn_failed = 0

        for user_id, data in staff_with_duty.items():
            # Skip immune users
            if user_id in immune_users:
                logger.info(f"    ⏭️ {data['name']}: Newly added - skipping mid-week warning")
                continue

            count = data[duty_type]
            projected = count * 2
            mid_rank = get_performance_rank(count, duty_type, "Mid-Week")
            currently_bad = mid_rank['emoji'] == '❌'
            projected_bad = projected < full_week_bad_threshold

            if not currently_bad and not projected_bad:
                continue

            needed = max(0, full_week_bad_threshold - count)

            if currently_bad and projected_bad:
                headline = "⚠️ You're at risk of a penalty this week."
                detail = (
                    f"You're currently **❌ Bad** at mid-week and your projected score "
                    f"(**{projected}**) is still below the full week minimum of **{full_week_bad_threshold}**."
                )
            elif currently_bad:
                headline = "⚠️ You're below the mid-week target — but still on track if you push."
                detail = (
                    f"You're currently **❌ Bad** at mid-week, but your projected score "
                    f"(**{projected}**) would be above the full week minimum of **{full_week_bad_threshold}**. "
                    f"Keep going!"
                )
            else:
                headline = "⚠️ You're on track now, but your projected score puts you at risk."
                detail = (
                    f"Your current score is okay at mid-week, but if your pace stays the same, "
                    f"your projected full week score (**{projected}**) would be below the minimum of "
                    f"**{full_week_bad_threshold}**."
                )

            embed = discord.Embed(
                title=f"⚠️ Mid-Week Warning — {duty_name}",
                description=headline,
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="📈 Current Score", value=f"**{count}** actions", inline=True)
            embed.add_field(name="🔮 Projected Score", value=f"**{projected}** actions", inline=True)
            embed.add_field(name="🎯 Full Week Minimum", value=f"**{full_week_bad_threshold}** actions", inline=True)
            embed.add_field(name="📋 Detail", value=detail, inline=False)
            embed.add_field(
                name="❗ What happens if you end the week Bad?",
                value=(
                    f"You'll receive a **200 Wave Points penalty** deducted from your balance, "
                    f"or your **{duty_name} role will be removed** if your Wave Points are below 200.\n\n"
                    f"You still need **{needed} more action(s)** this week to be safe."
                ),
                inline=False
            )
            embed.set_footer(text="Mid-week performance warning")

            try:
                user = await bot.fetch_user(user_id)
                await user.send(embed=embed)
                warn_sent += 1
                logger.info(f"    ⚠️ Warning DM sent to {data['name']} (score={count}, projected={projected})")
            except discord.Forbidden:
                warn_failed += 1
                logger.warning(f"    ⚠️ Could not DM {data['name']} - DMs disabled")
            except Exception as dm_error:
                warn_failed += 1
                logger.error(f"    ❌ Failed to DM {data['name']}: {dm_error}")

            await asyncio.sleep(RATE_LIMIT_DELAY)

        logger.info(f"  ⚠️ Mid-week warnings: {warn_sent} sent, {warn_failed} failed")

    # ==================== STEP 4: PROCESS VBUCKS (Full Week Only) ====================
    
    if period == "Full Week":
        if progress_message:
            try:
                await progress_message.edit(content=f"{emoji} **Processing {duty_type.upper()} duty...**\n\n**Step 4/4:** Processing Wave Points...")
            except:
                pass

        user_dm_extras = {}  # user_id -> {'fields': [(name, val, inline)], 'color': Color}

        # ==================== WAVE POINTS ====================

        # Tracks per-user outcomes for hub JSON augmentation at end of Full Week
        duty_results: dict = {
            uid: {'wp_earned': 0, 'penalty_amount': 0, 'role_removed': False}  # TODO(cross-session): key renamed from 'vbucks_earned' — update Session B website consumer of duties.json
            for uid in staff_with_duty
        }

        logger.info(f"  🌊 Awarding {duty_type} Wave Points...")

        sorted_staff = sorted(
            [(user_id, data) for user_id, data in staff_with_duty.items()],
            key=lambda x: x[1][duty_type],
            reverse=True
        )

        if duty_type == 'req':
            awards = {1: 150, 2: 100}
        else:
            awards = {}

        strike_threshold = thresholds.get(period, {}).get(duty_type, 0)
        awarded = 0
        award_failed = 0
        max_rank = max(awards.keys()) if awards else 0

        for rank, (user_id, data) in enumerate(sorted_staff[:max_rank], start=1):
            # Skip newly added users from Wave Points award
            if user_id in immune_users:
                logger.info(f"    🆕 {data['name']}: Newly added - skipping Wave Points award")
                continue

            count = data[duty_type]

            if count >= strike_threshold and rank in awards:
                wp = awards[rank]

                try:
                    await add_wave_points(user_id, wp)
                    awarded += 1
                    duty_results.setdefault(user_id, {})['wp_earned'] = wp
                    logger.info(f"    🌊 {wp} Wave Points to {data['name']} (#{rank}, {count} actions)")

                    extras = user_dm_extras.setdefault(user_id, {'fields': [], 'color': None})
                    extras['color'] = discord.Color.gold()
                    wp_note = f"**+{wp}** Wave Points awarded (#{rank} in {duty_names.get(duty_type, duty_type)})"
                    extras['fields'].append(("🌊 Wave Points Awarded", wp_note, False))
                    logger.info(f"      ✅ Wave Points info stored for {data['name']} (will DM in Step 6)")

                except Exception as e:
                    award_failed += 1
                    logger.error(f"    ❌ Error awarding Wave Points to {data['name']}: {e}")

        logger.info(f"  🌊 Wave Points: {awarded} awarded, {award_failed} failed")

    # ==================== PHASE 5: PROCESS BAD PERFORMANCE PENALTIES (Full Week Only) ====================

    if period == "Full Week":
        logger.info(f"  ⚠️ Checking for Bad performance penalties...")

        penalized_count = 0
        role_removed_count = 0
        penalty_failed = 0
        PENALTY_AMOUNT = 200

        for user_id, data in staff_with_duty.items():
            count = data[duty_type]
            rank_info = get_performance_rank(count, duty_type, "Full Week")
            rank = rank_info['rank']

            # Check if user got "Bad" rank (has ❌ emoji at start)
            if not rank.startswith('❌'):
                continue

            # Skip newly added users
            if user_id in immune_users:
                logger.info(f"    🆕 {data['name']}: Newly added - exempt from penalty")
                continue

            # Skip away users (both normal away and the immunity away role)
            if check_if_user_is_away(bot, user_id):
                logger.info(f"    ⏭️ {data['name']}: Away user - exempt from penalty")
                continue

            try:
                # Get Wave Points balance
                wave_points = await get_wave_points(user_id)

                if wave_points < PENALTY_AMOUNT:
                    # NOT ENOUGH - remove role without deducting
                    logger.warning(f"    🗑️ {data['name']}: Bad rank, insufficient Wave Points ({wave_points}/{PENALTY_AMOUNT}) - removing {duty_type} role")

                    role_removed = await remove_role_in_guilds(bot, user_id, duty_type)

                    if role_removed:
                        role_removed_count += 1
                        duty_results.setdefault(user_id, {})['role_removed'] = True
                        logger.info(f"    ✅ Removed {duty_type} role from {data['name']}")

                        extras = user_dm_extras.setdefault(user_id, {'fields': [], 'color': None})
                        extras['color'] = discord.Color.red()
                        extras['fields'].append((
                            "❌ Role Removed — Bad Performance",
                            f"You didn't have enough Wave Points ({wave_points}/{PENALTY_AMOUNT}) to cover the penalty.\n"
                            f"Earn more Wave Points and contact staff to regain this role.",
                            False
                        ))
                        logger.info(f"      ✅ Role removal info stored for {data['name']} (will DM in Step 6)")
                    else:
                        logger.error(f"    ❌ Failed to remove role from {data['name']}")

                else:
                    # HAVE ENOUGH - flat 200 Wave Points deduction
                    await add_wave_points(user_id, -PENALTY_AMOUNT)

                    penalized_count += 1
                    duty_results.setdefault(user_id, {})['penalty_amount'] = PENALTY_AMOUNT
                    logger.warning(f"    💸 {data['name']}: Bad rank - deducted {PENALTY_AMOUNT} Wave Points")

                    extras = user_dm_extras.setdefault(user_id, {'fields': [], 'color': None})
                    extras['color'] = discord.Color.orange()
                    extras['fields'].append((
                        "⚠️ Penalty — Bad Performance",
                        f"**{PENALTY_AMOUNT} Wave Points** have been deducted from your balance.\n"
                        f"✅ **Role kept** — you had enough Wave Points to cover the penalty.",
                        False
                    ))
                    logger.info(f"      ✅ Penalty info stored for {data['name']} (will DM in Step 6)")

                await asyncio.sleep(RATE_LIMIT_DELAY)

            except Exception as e:
                penalty_failed += 1
                logger.error(f"    ❌ Error processing penalty for {data['name']}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        logger.info(f"  ⚠️ Penalties: {penalized_count} deducted, {role_removed_count} roles removed, {penalty_failed} failed")

    # ==================== STEP 6: COMBINED RESULTS DM (Full Week Only) ====================

    if period == "Full Week":
        logger.info(f"  📨 Sending combined weekly results DMs to all {len(staff_with_duty)} staff...")

        rank_colors = {
            '🌟': discord.Color.gold(),
            '⭐': discord.Color.blue(),
            '✅': discord.Color.green(),
            '⚠️': discord.Color.orange(),
            '❌': discord.Color.red(),
        }

        sorted_for_position = sorted(
            staff_with_duty.items(),
            key=lambda x: x[1][duty_type],
            reverse=True
        )
        position_map = {uid: pos + 1 for pos, (uid, _) in enumerate(sorted_for_position)}
        total_staff = len(staff_with_duty)
        threshold = thresholds.get(period, {}).get(duty_type, 0)
        duty_name = duty_names.get(duty_type, duty_type)

        dm_sent = 0
        dm_failed = 0

        for user_id, data in staff_with_duty.items():
            # Skip newly added users from results DM
            if user_id in immune_users:
                logger.info(f"    🆕 {data['name']}: Newly added - skipping results DM")
                continue

            count = data[duty_type]
            rank_info = get_performance_rank(count, duty_type, period)
            rank_label = rank_info['rank']
            rank_emoji = rank_info['emoji']
            position = position_map[user_id]

            extras = user_dm_extras.get(user_id, {})
            # Use special color if set (VBucks = gold, penalty = orange/red), else rank color
            color = extras.get('color') or rank_colors.get(rank_emoji, discord.Color.blurple())

            embed = discord.Embed(
                title=f"📊 Your Weekly Results — {duty_name}",
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="📈 Your Actions", value=f"**{count}**", inline=True)
            embed.add_field(name="🏅 Performance", value=rank_label, inline=True)
            embed.add_field(name="📊 Position", value=f"**#{position}** of {total_staff}", inline=True)

            if rank_info['message']:
                embed.add_field(name="💬", value=rank_info['message'], inline=False)

            # Append any VBucks/penalty/role-removal info
            for field_name, field_value, field_inline in extras.get('fields', []):
                embed.add_field(name=field_name, value=field_value, inline=field_inline)

            embed.set_footer(text="Weekly performance summary")

            try:
                user = await bot.fetch_user(user_id)
                await user.send(embed=embed)
                dm_sent += 1
                logger.info(f"    ✅ Results DM sent to {data['name']} ({rank_label}, #{position})")
            except discord.Forbidden:
                dm_failed += 1
                logger.warning(f"    ⚠️ Could not DM {data['name']} - DMs disabled")
            except Exception as dm_error:
                dm_failed += 1
                logger.error(f"    ❌ Failed to DM {data['name']}: {dm_error}")

            await asyncio.sleep(RATE_LIMIT_DELAY)

        logger.info(f"  📨 Results DMs: {dm_sent} sent, {dm_failed} failed")

    logger.info(f"{emoji} {duty_type.upper()} DUTY COMPLETE!\n")
    return staff_with_duty, duty_results if period == "Full Week" else {}

# ==================== HELPER FUNCTIONS ====================

def get_global_dates_from_config():
    """Get global dates from config.json"""
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

# ==================== HUB JSON AUGMENTATION ====================

async def _augment_duties_hub_json(all_duty_results: dict, start_date: str, end_date: str):
    """
    After Full Week processing completes, read the current duties.json written by
    duties_scan.py and overlay the real VBucks/penalty/role_removed
    values that were just computed, then write it back to the hub.
    """
    import json as _json
    import os as _os
    from tasks.staff_hub_writer import push_duties_to_github

    hub_path = _os.path.join(_os.path.dirname(__file__), '..', 'website', 'data', 'duties.json')
    try:
        with open(hub_path, 'r', encoding='utf-8') as _f:
            payload = _json.load(_f)
    except Exception as _e:
        logger.warning(f"  ⚠️ Could not read duties.json for augmentation: {_e}")
        return

    users = payload.get('users', {})
    updated = 0
    for duty_type, results in all_duty_results.items():
        for uid, outcome in results.items():
            uid_str = str(uid)
            if uid_str not in users:
                continue
            user_entry = users[uid_str]
            duties = user_entry.get('duties', {})
            if duty_type not in duties:
                continue
            d = duties[duty_type]
            d['wp_earned'] = outcome.get('wp_earned', 0)  # TODO(cross-session): key renamed from 'vbucks_earned' — update Session B website consumer of duties.json
            d['penalty_amount'] = outcome.get('penalty_amount', 0)
            d['role_removed']   = outcome.get('role_removed', False)
            updated += 1

    payload['_meta']['last_updated'] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    payload['_meta']['end_date'] = end_date

    # Snapshot the completed week into history before pushing
    completed_snapshot = {
        '_meta': dict(payload['_meta']),
        'users': dict(payload.get('users', {})),
    }
    weeks = list(payload.get('weeks', []))
    weeks.insert(0, completed_snapshot)
    payload['weeks'] = weeks[:8]  # keep last 8 completed weeks

    await push_duties_to_github(payload)
    logger.info(f"  ✅ Hub duties.json augmented + week snapshot saved ({updated} entries, {len(payload['weeks'])} weeks in history)")


# ==================== TIMING ====================

async def run_report_at_exact_time(bot, period: str, hours_to_wait: int):
    """
    Run report at exact time - SEQUENTIAL DUTY PROCESSING

    ✅ Processes each duty completely before moving to next
    ✅ Order: Req → Role
    ✅ Each duty: scan → report → vbucks
    """
    
    await bot.wait_until_ready()
    logger.info(f"✅ {period} task active and ready")
    
    while True:
        try:
            start_date, end_date = get_global_dates_from_config()
            
            if not start_date or not end_date:
                await asyncio.sleep(300)
                continue
            
            start_datetime = get_start_datetime(start_date)
            target_time = start_datetime + timedelta(hours=hours_to_wait)
            now = datetime.now(timezone.utc)

            # ✅ FIX: Calculate actual_end_date the same way as when running the report
            scan_end_datetime = start_datetime + timedelta(hours=hours_to_wait)
            if period == "Mid-Week":
                check_end_date = scan_end_datetime.strftime('%d/%m/%Y')
            else:
                check_end_date = end_date

            already_sent = False
            for report_type in ['req']:
                if await database.check_report_already_sent(
                    REPORT_GUILD_ID,
                    report_type,
                    period,
                    start_date,
                    check_end_date
                ):
                    already_sent = True
                    break
            
            if already_sent:
                logger.info(f"⏭️ {period} already sent for {start_date} - {end_date}, waiting for next week...")
                wait_until = start_datetime + timedelta(hours=FULL_WEEK_HOURS + 24)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                else:
                    await asyncio.sleep(300)
                continue
            
            time_diff = (target_time - now).total_seconds()
            
            if time_diff < -3600:
                hours_late = abs(time_diff) / 3600
                logger.warning(f"⚠️ {period} trigger missed by {hours_late:.1f}h - TOO LATE, skipping to next week")
                wait_until = start_datetime + timedelta(hours=FULL_WEEK_HOURS + 24)
                wait_seconds = (wait_until - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                else:
                    await asyncio.sleep(300)
                continue
            
            if time_diff > 0:
                logger.info(f"⏰ {period} report scheduled for {target_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                logger.info(f"   Waiting {time_diff/3600:.1f} hours ({time_diff:.0f} seconds)...")
                await asyncio.sleep(time_diff)
                
                now = datetime.now(timezone.utc)
                actual_diff = (now - target_time).total_seconds()
                
                if actual_diff > 3600:
                    logger.warning(f"⚠️ {period} woke up {actual_diff/3600:.1f}h late - skipping to next week")
                    wait_until = start_datetime + timedelta(hours=FULL_WEEK_HOURS + 24)
                    wait_seconds = (wait_until - now).total_seconds()
                    if wait_seconds > 0:
                        await asyncio.sleep(wait_seconds)
                    else:
                        await asyncio.sleep(300)
                    continue
            
            # ==================== RUN REPORTS ONE DUTY AT A TIME ====================
            
            logger.info(f"")
            logger.info(f"🚀 ========================================")
            logger.info(f"🚀 RUNNING {period.upper()} REPORT")
            logger.info(f"🚀 Processing Order: Req → Role")
            logger.info(f"🚀 Each duty: scan → report → vbucks")
            logger.info(f"🚀 ========================================")
            
            scan_end_datetime = start_datetime + timedelta(hours=hours_to_wait)
            
            if period == "Mid-Week":
                actual_end_date = scan_end_datetime.strftime('%d/%m/%Y')
            else:
                actual_end_date = end_date
            
            logger.info(f"🚀 Date: {start_date} to {actual_end_date}")
            
            all_duty_results: dict = {}  # {duty_type: {user_id: {...}}}
            for duty_type in ['req']:
                try:
                    _, dr = await process_single_duty(
                        bot=bot,
                        duty_type=duty_type,
                        guild_ids=SOURCE_GUILDS,
                        start_datetime=start_datetime,
                        end_datetime=scan_end_datetime,
                        period=period,
                        start_date=start_date,
                        end_date=actual_end_date,
                        progress_message=None
                    )
                    if dr:
                        all_duty_results[duty_type] = dr
                except Exception as duty_err:
                    logger.error(f"❌ Error processing {duty_type} duty (continuing to next): {duty_err}")
                    logger.error(traceback.format_exc())

                logger.info(f"⏳ Waiting {BATCH_DELAY}s before next duty...")
                await asyncio.sleep(BATCH_DELAY)

            # ── Augment hub duties.json with VBucks/penalty results ────────────
            if period == "Full Week" and all_duty_results:
                try:
                    await _augment_duties_hub_json(all_duty_results, start_date, actual_end_date)
                except Exception as _ae:
                    logger.error(f"❌ Failed to augment duties hub JSON: {_ae}")
            
            logger.info(f"")
            logger.info(f"✅ ========================================")
            logger.info(f"✅ {period.upper()} REPORT COMPLETE")
            logger.info(f"✅ All duties processed sequentially")
            logger.info(f"✅ Next report: {(start_datetime + timedelta(hours=FULL_WEEK_HOURS)).strftime('%Y-%m-%d %H:%M:%S UTC')}")
            logger.info(f"✅ ========================================")
            logger.info(f"")
            
            wait_until = start_datetime + timedelta(hours=FULL_WEEK_HOURS + 24)
            wait_seconds = (wait_until - datetime.now(timezone.utc)).total_seconds()
            if wait_seconds > 0:
                logger.info(f"💤 Sleeping for {wait_seconds/3600:.1f} hours until next period...")
                await asyncio.sleep(wait_seconds)
        
        except asyncio.CancelledError:
            logger.info(f"🛑 {period} task cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Error in {period} task: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(300)

# ==================== COG ====================

class WeeklyChecks(commands.Cog):
    """Automated staff activity reporting with sequential duty processing"""
    
    def __init__(self, bot):
        self.bot = bot
        self.midweek_task = None
        self.fullweek_task = None
        self.role_monitor_task = None
    
    async def cog_load(self):
        """Start background tasks"""
        logger.info("🚀 Starting weekly checks with sequential duty processing...")

        self.midweek_task = asyncio.create_task(
            run_report_at_exact_time(self.bot, "Mid-Week", MID_WEEK_HOURS)
        )
        self.fullweek_task = asyncio.create_task(
            run_report_at_exact_time(self.bot, "Full Week", FULL_WEEK_HOURS)
        )
        self.role_monitor_task = asyncio.create_task(
            monitor_role_assignments(self.bot)
        )

        logger.info(f"✅ Tasks created!")
        logger.info(f"   📅 Mid-Week: Triggers at {MID_WEEK_HOURS} hours (72h)")
        logger.info(f"   📅 Full Week: Triggers at {FULL_WEEK_HOURS} hours (168h)")
        logger.info(f"   🔍 Role Monitor: Scans every 30 minutes")
    
    def cog_unload(self):
        """Cancel background tasks"""
        if self.midweek_task:
            self.midweek_task.cancel()
        if self.fullweek_task:
            self.fullweek_task.cancel()
        if self.role_monitor_task:
            self.role_monitor_task.cancel()

        logger.info("🛑 Weekly checks stopped")

async def monitor_role_assignments(bot):
    """
    Background task that monitors servers for role assignments.
    Detects when users gain duty roles and logs the timestamp.
    Runs every 30 minutes.
    """
    await bot.wait_until_ready()
    logger.info("🔍 Role assignment monitoring started")

    while True:
        try:
            # Scan ALL source guilds so staff added only to guild 2 also get their
            # assignment timestamp recorded and receive the 4-day immunity window.
            for guild_id in SOURCE_GUILDS:
                guild = bot.get_guild(guild_id)
                if not guild:
                    logger.warning(f"Guild {guild_id} not found for role monitoring")
                    continue

                logger.info(f"🔍 Scanning {guild.name} for role assignments...")

                duty_roles = {}
                for role in guild.roles:
                    role_name_lower = role.name.lower()
                    if role_name_lower == "map request helper":
                        duty_roles[role.id] = ('req', role)

                for role_id, (duty_type, role) in duty_roles.items():
                    for member in role.members:
                        if member.bot:
                            continue

                        assignment_date = await database.get_role_assignment_date(member.id, duty_type)
                        if not assignment_date:
                            await database.log_role_assignment(member.id, duty_type)
                            logger.info(f"  🆕 Logged new {duty_type} role assignment: {member.name} (from {guild.name})")

                        await asyncio.sleep(0.1)

                logger.info(f"✅ Role assignment scan complete for {guild.name}")

            await asyncio.sleep(1800)  # 30 minutes between scans

        except asyncio.CancelledError:
            logger.info("🛑 Role monitoring task cancelled")
            raise
        except Exception as e:
            logger.error(f"❌ Error in role monitoring: {e}")
            await asyncio.sleep(300)  # 5 minutes on error


async def setup(bot):
    await bot.add_cog(WeeklyChecks(bot))

# ==================== EXPORT FOR MANUAL COMMANDS ====================

async def collect_staff_data_with_progress(bot, guild_ids, start_datetime, end_datetime, progress_message=None):
    """
    Legacy function for manual force commands
    Collects data for all duties sequentially, then returns combined dict
    """
    logger.info("📊 Manual data collection - processing all duties sequentially...")
    
    all_data = {}
    
    for duty_type in ['req']:
        duty_data, _ = await process_single_duty(
            bot=bot,
            duty_type=duty_type,
            guild_ids=guild_ids,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            period="Manual",
            start_date="N/A",
            end_date="N/A",
            progress_message=progress_message
        )

        for user_id, data in duty_data.items():
            if user_id not in all_data:
                all_data[user_id] = {
                    'name': data['name'],
                    'req': 0,
                }
            all_data[user_id][duty_type] = data.get(duty_type, 0)
    
    logger.info(f"✅ Manual collection complete: {len(all_data)} users total")
    
    return all_data

# Export for backward compatibility
collect_staff_data = collect_staff_data_with_progress