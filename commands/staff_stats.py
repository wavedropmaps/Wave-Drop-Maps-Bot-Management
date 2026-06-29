"""
Staff Statistics Commands
Display staff activity statistics from the database
"""

import json
import os
import re
import time
import discord
from discord.ext import commands
from datetime import datetime, timezone
from core.helpers import (
    create_error_embed,
    check_dates_configured,
    get_member,
    get_start_datetime,
    get_end_datetime,
    get_automation_config,
    get_readable_text_channels,
    safe_history_fetch,
    scan_channels_parallel,
    extract_embed_content,
    predict_end_of_week_performance,
)
from core.cache import config_cache
import database
import logging

logger = logging.getLogger('discord')



# ==================== DUTIES JSON HELPERS ====================

# Path to duties_totals.json — written by duties_scan.py in the bot root
DUTIES_JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'json_data', 'duties_totals.json')


def _read_duties_json() -> dict:
    """
    Load duties_totals.json from disk. Returns empty dict if missing/malformed.
    Structure:
      { "_meta": {...}, "req": {"uid": {"name","count","uid"}},
        "role": {...}, "modlog": {...}, "message": {"uid": {..., "days_of_week_active"}} }
    """
    try:
        with open(DUTIES_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("⚠️ duties_totals.json not found — duties_scan hasn't run yet this week")
        return {}
    except Exception as e:
        logger.error(f"❌ Failed to read duties_totals.json: {e}")
        return {}


def _get_user_count(duties: dict, duty_type: str, user_id: int) -> int:
    """Pull a single user's count for a duty type from the loaded JSON."""
    entry = duties.get(duty_type, {}).get(str(user_id))
    if not entry:
        return 0
    return entry.get('count', 0)


def _last_updated(duties: dict) -> str:
    """Return human-readable last-updated string from _meta."""
    ts = duties.get('_meta', {}).get('last_updated')
    if not ts:
        return 'Unknown'
    try:
        return datetime.fromisoformat(ts).strftime('%d %b, %H:%M UTC')
    except Exception:
        return ts


def _get_last_scan_datetime(duties: dict) -> datetime:
    """Extract the last duties scan timestamp as a datetime object."""
    ts = duties.get('_meta', {}).get('last_updated')
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


class StaffStats(commands.Cog):
    """Commands for viewing staff statistics"""

    def __init__(self, bot):
        self.bot = bot

    # ==================== HELPER ====================

    async def send_stat_embed(self, ctx, title: str, member: discord.Member, fields: list):
        """Send a standard stat result embed"""
        embed = discord.Embed(
            title=title,
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(
            name=f"{member} (ID: {member.id})",
            icon_url=member.avatar.url if member.avatar else None
        )
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        await ctx.send(embed=embed)

    async def _scan_for_live_updates(self, ctx, start_dt: datetime, end_dt: datetime = None) -> dict:
        """
        Scan channels for activity since last duties scan up to now.
        Returns a dict with structure: {"req": {...}, "role": {...}, "modlog": {...}, "message": {...}}
        """
        if end_dt is None:
            end_dt = datetime.now(timezone.utc)
        
        # Get source guilds to scan
        auto_config = get_automation_config()
        source_guilds = auto_config.get('source_guilds', [])
        if not source_guilds:
            source_guilds = [ctx.guild.id]
        
        live_data = {
            'req': {},
            'role': {},
            'modlog': {},
            'message': {}
        }
        
        logger.info(f"🔄 Scanning for live updates from {start_dt} to {end_dt}")
        
        # Get readable channels from each source guild
        all_channels = []
        for guild_id in source_guilds:
            guild = self.bot.get_guild(guild_id)
            if guild:
                readable = get_readable_text_channels(guild)
                all_channels.extend(readable)
        
        if not all_channels:
            logger.warning("⚠️ No readable channels found for live scanning")
            return live_data
        
        # Collect members to scan across all source guilds
        all_members = []
        for guild_id in source_guilds:
            guild = self.bot.get_guild(guild_id)
            if guild:
                all_members.extend([m for m in guild.members if not m.bot])

        # scan_channels_parallel returns {member: {"count": int, "days": set}}
        # It only tracks message counts - req/role/modlog come from the DB cache
        try:
            scan_result = await scan_channels_parallel(
                all_channels,
                all_members,
                start_dt,
                end_dt,
                ctx
            )

            if scan_result and isinstance(scan_result, dict):
                for member, stats in scan_result.items():
                    count = stats.get("count", 0)
                    if count > 0:
                        uid = str(member.id)
                        live_data["message"][uid] = {
                            "name": str(member),
                            "count": count,
                            "uid": member.id
                        }
        except Exception as e:
            logger.error(f"❌ Error during live scanning: {e}")
        
        return live_data
    
    def _merge_duty_counts(self, cached: dict, live: dict) -> dict:
        """
        Merge cached duties counts with live scan counts.
        Live counts are added on top of cached counts.
        """
        merged = {}
        
        # Start with all cached entries
        for duty_type in ['req', 'role', 'modlog', 'message']:
            merged[duty_type] = {}
            
            # Add cached data
            for uid, data in cached.get(duty_type, {}).items():
                merged[duty_type][uid] = {
                    'name': data.get('name', 'Unknown'),
                    'count': data.get('count', 0),
                    'uid': data.get('uid', int(uid))
                }
            
            # Add live data on top
            for uid, data in live.get(duty_type, {}).items():
                if uid not in merged[duty_type]:
                    merged[duty_type][uid] = {
                        'name': data.get('name', 'Unknown'),
                        'count': 0,
                        'uid': data.get('uid', int(uid))
                    }
                merged[duty_type][uid]['count'] += data.get('count', 0)
        
        return merged

    def _get_days_of_week_count(self, active_dates: set) -> int:
        """Count how many unique days of the week (0-7) have activity"""
        if not active_dates:
            return 0
        
        days_of_week_set = set()
        for date in active_dates:
            day_num = date.weekday()  # 0=Monday, 6=Sunday
            days_of_week_set.add(day_num)
        
        return len(days_of_week_set)

    def _format_days_of_week(self, active_dates: set) -> str:
        """
        Given a set of active dates, return formatted string of days of week
        with count and emojis for each day.
        Example: "🟦 Mon (2) • 🟩 Tue (3) • 🟪 Wed (1) • ..."
        """
        days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_emojis = ["🟦", "🟩", "🟪", "🟥", "🟨", "🟦", "🟩"]
        day_counts = {i: 0 for i in range(7)}
        
        for date in active_dates:
            day_num = date.weekday()  # 0=Monday, 6=Sunday
            day_counts[day_num] += 1
        
        formatted_days = []
        for day_num in range(7):
            count = day_counts[day_num]
            if count > 0:
                formatted_days.append(f"{day_emojis[day_num]} {days_of_week[day_num][:3]} ({count})")
        
        if not formatted_days:
            return "No active days"
        
        return " • ".join(formatted_days)

    async def _resolve_source_guilds(self, ctx) -> list:
        """Return source guilds from automation config, falling back to current guild."""
        auto_config = get_automation_config()
        source_guilds = auto_config.get('source_guilds', [])

        if not source_guilds:
            source_guilds = [ctx.guild.id]
            await ctx.send(
                "ℹ️ No source guilds configured — scanning current server only. "
                "Use `>autoconfig addsourceguild <id>` to add more servers."
            )
        else:
            guild_names = []
            for gid in source_guilds:
                guild = self.bot.get_guild(gid)
                guild_names.append(guild.name if guild else f"Unknown ({gid})")
            await ctx.send(
                f"🌐 Scanning **{len(source_guilds)}** source guild(s): {', '.join(guild_names)}"
            )

        return source_guilds

    # ==================== STAFFSTATS GROUP ====================

    # ==================== COMPARE COMMAND ====================

    @commands.command(name='compare', help='⚔️ BATTLE TWO STAFF MEMBERS - Who will win?')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def compare(self, ctx, member1_id: int, member2_id: int):
        """
        Compare complete stats between two staff members.
        Usage: >compare <member_id1> <member_id2>
        SCORING: Messages: 70=1pt, Roles/Requests/Modlogs: 1=1pt, Days Active: 1=1pt
        """
        cmd_start = time.time()
        # Send loading message
        loading_msg = await ctx.send("⚔️ Initializing staff battle arena... (this may take 1-5 minutes)")

        member1 = ctx.guild.get_member(member1_id)
        member2 = ctx.guild.get_member(member2_id)

        if not member1:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed("Member Not Found", f"Could not find member with ID {member1_id}"))
        if not member2:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed("Member Not Found", f"Could not find member with ID {member2_id}"))

        config = await check_dates_configured(ctx, config_cache)
        if not config:
            await loading_msg.delete()
            return

        start_date = config['start_date']
        end_date = config['end_date']
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)

        duties = _read_duties_json()
        if not duties:
            await loading_msg.delete()
            return await ctx.send(embed=create_error_embed(
                "No Data", "duties_totals.json not found or empty — duties_scan hasn't run yet this week."
            ))

        # Get last scan time and perform live scanning
        last_scan_dt = _get_last_scan_datetime(duties)
        live_updates = await self._scan_for_live_updates(ctx, last_scan_dt or start_datetime, datetime.now(timezone.utc))
        merged_duties = self._merge_duty_counts(duties, live_updates)

        def get_member_stats(member):
            uid            = member.id
            total_messages = _get_user_count(merged_duties, 'message', uid)
            total_roles    = _get_user_count(merged_duties, 'role',    uid)
            total_requests = _get_user_count(merged_duties, 'req',     uid)
            total_modlogs  = _get_user_count(merged_duties, 'modlog',  uid)
            days_active    = merged_duties.get('message', {}).get(str(uid), {}).get('days_of_week_active', 0)
            message_points = total_messages // 70
            total_activity = message_points + days_active + total_roles + total_requests + total_modlogs
            return {
                'messages': total_messages, 'message_points': message_points,
                'days_active': days_active, 'roles': total_roles,
                'requests': total_requests,
                'modlogs': total_modlogs, 'total': total_activity
            }

        stats1 = get_member_stats(member1)
        stats2 = get_member_stats(member2)

        if stats1['total'] > stats2['total']:
            winner, loser = member1, member2
            winner_stats, loser_stats = stats1, stats2
        elif stats2['total'] > stats1['total']:
            winner, loser = member2, member1
            winner_stats, loser_stats = stats2, stats1
        else:
            winner = None
            winner_stats, loser_stats = stats1, stats2

        def format_stat(stat1, stat2, name1, name2, emoji):
            if stat1 > stat2:
                diff = stat1 - stat2
                pct = int((diff / stat2 * 100)) if stat2 > 0 else 100
                return f"{emoji} **{name1}:** `{stat1}` 🏆\n{name2}: `{stat2}`\n**{name1} leads by {diff}** ({pct}% ahead)"
            elif stat2 > stat1:
                diff = stat2 - stat1
                pct = int((diff / stat1 * 100)) if stat1 > 0 else 100
                return f"{emoji} {name1}: `{stat1}`\n**{name2}**: `{stat2}` 🏆\n**{name2} leads by {diff}** ({pct}% ahead)"
            else:
                return f"{emoji} **TIED** 🤝\n{name1}: `{stat1}`\n{name2}: `{stat2}`"

        def format_messages(s1m, s2m, s1p, s2p, n1, n2):
            if s1p > s2p:
                diff = s1p - s2p
                pct = int((diff / s2p * 100)) if s2p > 0 else 100
                return f"💬 **{n1}:** `{s1m}` 🏆\n{n2}: `{s2m}`\n**{n1} leads by {diff}** ({pct}% ahead)"
            elif s2p > s1p:
                diff = s2p - s1p
                pct = int((diff / s1p * 100)) if s1p > 0 else 100
                return f"💬 {n1}: `{s1m}`\n**{n2}**: `{s2m}` 🏆\n**{n2} leads by {diff}** ({pct}% ahead)"
            else:
                return f"💬 **TIED** 🤝\n{n1}: `{s1m}`\n{n2}: `{s2m}`"

        embed = discord.Embed(
            title="⚔️ STAFF BATTLE RESULTS ⚔️",
            description=f"**{member1.name}** vs **{member2.name}**\n**Period:** {duties.get('_meta',{}).get('start_date','?')} → {duties.get('_meta',{}).get('end_date','?')}\n**Data as of:** {_last_updated(duties)}\n✅ **Live Updates Included** (since last scan)",
            color=discord.Color.gold() if winner else discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=(winner or member1).avatar.url if (winner or member1).avatar else None)
        embed.add_field(name=f"🥊 {member1.name}", value=f"**Total Score:** `{stats1['total']}`", inline=True)
        embed.add_field(name="⚡ VS ⚡", value="━━━━━", inline=True)
        embed.add_field(name=f"🥊 {member2.name}", value=f"**Total Score:** `{stats2['total']}`", inline=True)
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)
        embed.add_field(name="📨 Messages Sent", value=format_messages(stats1['messages'], stats2['messages'], stats1['message_points'], stats2['message_points'], member1.name, member2.name), inline=False)
        embed.add_field(name="📅 Days Active", value=format_stat(stats1['days_active'], stats2['days_active'], member1.name, member2.name, "📆"), inline=False)
        embed.add_field(name="👤 Role Giving", value=format_stat(stats1['roles'], stats2['roles'], member1.name, member2.name, "🎭"), inline=True)
        embed.add_field(name="🗺️ Map Requests", value=format_stat(stats1['requests'], stats2['requests'], member1.name, member2.name, "🗂️"), inline=True)
        embed.add_field(name="🔨 Mod Commands", value=format_stat(stats1['modlogs'], stats2['modlogs'], member1.name, member2.name, "⚒️"), inline=True)
        embed.add_field(name="", value="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", inline=False)

        if winner:
            diff = abs(winner_stats['total'] - loser_stats['total'])
            pct = int((diff / loser_stats['total'] * 100)) if loser_stats['total'] > 0 else 100
            if pct < 10: intensity, battle_emoji = "🔥 NECK AND NECK! 🔥", "⚔️"
            elif pct < 30: intensity, battle_emoji = "⚡ CLOSE BATTLE! ⚡", "🥊"
            elif pct < 50: intensity, battle_emoji = "💪 CLEAR VICTOR! 💪", "👑"
            else: intensity, battle_emoji = "🚀 TOTAL DOMINATION! 🚀", "💥"
            outcome = (
                f"## {battle_emoji} {winner.mention} WINS! {battle_emoji}\n\n{intensity}\n\n"
                f"🥇 **{winner.name}** Total: `{winner_stats['total']}`\n"
                f"🥈 **{loser.name}** Total: `{loser_stats['total']}`\n\n"
                f"**Victory Margin:** **{diff} points** (**{pct}% ahead**)\n\n"
                f"*{winner.name} is crushing it! Will you step up to the challenge?* 💪"
            )
        else:
            outcome = (
                f"## 🤝 PERFECT TIE! 🤝\n\n**BOTH WARRIORS SCORED:** `{stats1['total']}`\n\n"
                f"🔥 Incredible match! Both staff members are performing at the EXACT same level!\n\n"
                f"*Can anyone break this deadlock?* ⚡"
            )
        embed.add_field(name="📊 BATTLE OUTCOME", value=outcome, inline=False)
        embed.set_footer(
            text=f"⚡ Battle completed in {time.time() - cmd_start:.2f}s | Think you can win? Prove it! • Today at {datetime.now().strftime('%I:%M %p')}",
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None
        )
        
        # Delete loading message
        try:
            await loading_msg.delete()
        except:
            pass
        
        await ctx.send(embed=embed)



    # ==================== INSIGHTS HISTORY ====================

async def setup(bot):
    await bot.add_cog(StaffStats(bot))