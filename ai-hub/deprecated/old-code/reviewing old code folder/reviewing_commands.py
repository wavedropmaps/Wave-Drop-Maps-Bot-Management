import discord
from discord.ext import commands
import asyncio
import json
import re
from datetime import date, datetime, timezone, timedelta
from database import (
    get_pool,
    update_reviewer_tier,
    update_accuracy_streak,
    update_daily_streak,
    apply_penalty,
    get_reviewer_leaderboard_stats,
    calculate_base_points,
    calculate_final_points,
    get_milestone_notification_channel,
    set_milestone_notification_channel,
    log_daily_activity,
    log_thread_creation,
    log_thread_response,
    get_thread_info
)
from tasks.reviewing_tasks import auto_update_drop_map_leaderboard
from database import add_drop_map_reviewer, remove_drop_map_reviewer, get_daily_activity_summary
import logging

logger = logging.getLogger(__name__)

# ==================== DAILY SUMMARY HELPER ====================

async def push_daily_summary_for_session(guild_id: int, session_date):
    """Push daily activity summary to GitHub for a specific session."""
    try:
        from tasks.staff_hub_writer import push_daily_summary_to_github
        from database import get_challenges_for_session
        summary = await get_daily_activity_summary(guild_id, session_date)

        session_date_str = session_date if isinstance(session_date, str) else session_date.isoformat()

        try:
            challenges = await get_challenges_for_session(session_date_str)
        except Exception as e:
            logger.debug(f"Could not load challenges for {session_date_str}: {e}")
            challenges = []

        summary_payload = {
            "date": session_date_str,
            "guild_id": guild_id,
            "summary": {
                "total_points": summary['total_points'],
                "total_markers": summary['total_markers'],
                "active_reviewers": summary['active_reviewers'],
                "tier_promotions": summary['tier_promotions'],
                "milestone_hits": summary['milestone_hits']
            },
            "activities": summary['activities'],
            "challenges": challenges,
            "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        success = await push_daily_summary_to_github(summary_payload)
        if success:
            logger.info(f"✅ Daily summary pushed for {session_date_str}")
            return True
        else:
            logger.error(f"❌ Daily summary push failed for {session_date_str}")
            return False
    except Exception as e:
        logger.error(f"❌ Error pushing daily summary: {e}")
        return False

# Penalty mappings
PENALTY_CODES = {
    'marker_mistake': {'name': 'Marker Mistake', 'points': 20, 'code': 'A'},
    'skipped_oldest': {'name': 'Skipped Oldest Map', 'points': 20, 'code': 'B'},
    'abandoned_review': {'name': 'Abandoned Review', 'points': 10, 'code': 'D'},
    'no_thread': {'name': 'No Thread', 'points': 10, 'code': 'E'},
    'incomplete_claim': {'name': 'Incomplete Claim', 'points': 30, 'code': 'F'},
}

# ==================== NEW SYSTEM CONSTANTS (>add points / >endday / >closeday) ====================

# Valid base points values that users can enter at >add points
VALID_BASE_POINTS = [1, 1.5, 2, 3, 4]

# Tier multipliers
TIER_MULTIPLIERS = {
    'Master': 4.0,
    'Expert': 3.0,
    'Advanced': 2.0,
    'Intermediate': 1.5,
    'Beginner': 1.0,
}

# Accuracy thresholds (lower bounds, percent)
TIER_THRESHOLDS = {
    'Master': 96.67,
    'Expert': 90,
    'Advanced': 83.33,
    'Intermediate': 76.67,
    'Beginner': 0,
}

# Accuracy streak milestones: threshold (perfect markers) → bonus points
ACCURACY_MILESTONES = {
    5: 10,
    9: 100,
    19: 300,
    37: 750,
    50: 2000,
    100: 8000,
}

# Daily streak milestones: threshold (consecutive days) → bonus points
DAILY_MILESTONES = {
    2: 10,
    5: 100,
    14: 300,
    30: 750,
    180: 8000,
    365: 20000,
}


class ReviewingCommands(commands.Cog):
    """Main reviewing commands for drop map system"""

    def __init__(self, bot):
        self.bot = bot

    # ==================== THREAD RESPONSE TRACKING ====================

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """Log thread creation for response time tracking"""
        TARGET_CHANNEL_ID = 1476531469949075497

        # Only track threads in the specific channel
        if thread.parent_id != TARGET_CHANNEL_ID:
            return

        try:
            # Get the original message that started the thread
            original_message = thread.starter_message
            original_timestamp = None
            original_author_id = None

            # Try to fetch from cache first
            if original_message is None:
                try:
                    # Thread starter message ID is the same as thread ID
                    original_message = await thread.parent.fetch_message(thread.id)
                except Exception as e:
                    logger.debug(f"Could not fetch original message: {e}")

            # Extract data from original message
            if original_message is not None:
                original_timestamp = original_message.created_at.isoformat()
                original_author_id = original_message.author.id
                logger.debug(f"Got original message - author: {original_author_id}, timestamp: {original_timestamp}")
            else:
                logger.warning(f"⚠️ Could not fetch original message for thread {thread.id}")
                return

            # Only log if we have both author and timestamp
            if original_author_id is None or original_timestamp is None:
                logger.error(f"❌ Missing original message data for thread {thread.id}")
                return

            await log_thread_creation(thread.id, TARGET_CHANNEL_ID, original_author_id, original_timestamp)
            logger.info(f"✅ Logged thread creation: {thread.id} (original author: {original_author_id})")
        except Exception as e:
            logger.error(f"❌ Error logging thread creation: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track first response in threads and display points-per-marker bracket"""
        TARGET_CHANNEL_ID = 1476531469949075497

        # Ignore bot messages and system messages (e.g., thread creation notices)
        if message.author.bot or message.is_system():
            return

        # Only track messages in threads of the target channel
        if not isinstance(message.channel, discord.Thread):
            return

        if message.channel.parent_id != TARGET_CHANNEL_ID:
            return

        try:
            # Get thread info
            thread_info = await get_thread_info(message.channel.id)
            logger.debug(f"Thread info lookup for {message.channel.id}: {thread_info}")

            # If thread_info is None, try logging the thread first (race condition with on_thread_create)
            if not thread_info:
                try:
                    thread = message.channel
                    original_message = await thread.parent.get_partial_message(thread.starter_message_id).fetch()
                    await log_thread_creation(thread.id, TARGET_CHANNEL_ID, original_message.author.id, original_message.created_at)
                    thread_info = await get_thread_info(message.channel.id)
                    logger.info(f"⏱️ Auto-logged thread {message.channel.id}, retrying info lookup")
                except Exception as retry_err:
                    logger.debug(f"Could not auto-log thread: {retry_err}")

            # If thread_info is still None, skip
            if not thread_info:
                logger.error(f"❌ Could not get thread info for {message.channel.id} - skipping response")
                return

            logger.info(f"✅ Got thread info: {thread_info}")

            # If thread already has a first response, skip completely (never process again)
            if thread_info.get('first_responder_id'):
                logger.debug(f"Thread {message.channel.id} already has first response, skipping")
                return

            # First message in thread - calculate and log (from anyone, no restrictions)
            logger.info(f"Processing first response from {message.author.id} in thread {message.channel.id}")

            # Calculate response time from original message creation
            if isinstance(thread_info['thread_created_at'], str):
                thread_created_at = datetime.fromisoformat(thread_info['thread_created_at'])
                thread_created_at = thread_created_at.replace(tzinfo=timezone.utc)
            else:
                thread_created_at = thread_info['thread_created_at']

            response_time = message.created_at - thread_created_at
            response_seconds = response_time.total_seconds()

            # Determine bracket and points per marker
            if response_seconds <= 60:
                bracket = "Within 1 minute"
                points_per_marker = 4
            elif response_seconds <= 300:
                bracket = "Within 5 minutes"
                points_per_marker = 3
            elif response_seconds <= 1800:
                bracket = "Within 30 minutes"
                points_per_marker = 2
            elif response_seconds <= 3600:
                bracket = "Within 1 hour"
                points_per_marker = 1.5
            else:
                bracket = "After 1 hour"
                points_per_marker = 1

            # Send bracket embed
            minutes, seconds = divmod(int(response_seconds), 60)
            time_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

            embed = discord.Embed(
                title="⏱️ Response Time Bracket",
                description=f"**{bracket}**",
                color=discord.Color.gold()
            )
            embed.add_field(name="Response Time", value=time_str, inline=True)
            embed.add_field(name="Points Per Marker", value=f"**{points_per_marker}** pts", inline=True)
            embed.set_footer(text="✅ Response tracked and points will be awarded")

            # Thread starter messages can't be replied to (Discord treats them as system messages)
            if message.id == message.channel.id:
                await message.channel.send(embed=embed)
            else:
                await message.reply(embed=embed, mention_author=False)

            # Log response - marks thread as processed, never calculate again
            await log_thread_response(message.channel.id, message.author.id, int(response_seconds), bracket)
            logger.info(f"✅ Response tracked: {message.author.id} responded in {time_str} ({bracket})")

        except Exception as e:
            logger.error(f"❌ Error tracking thread response: {e}")

    @commands.command(name='setpointsmanual')
    @commands.has_permissions(administrator=True)
    async def set_points_manual(self, ctx, reviewer: discord.Member, adjustment: str):
        """
        Manually adjust points (admin only).
        Format: +50 or -20 (relative) or =500 (absolute)
        """
        pool = await get_pool()

        try:
            if adjustment.startswith('+'):
                amount = round(float(adjustment[1:]), 2)
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE reviewers SET total_points = total_points + ? WHERE user_id = ?",
                        (amount, reviewer.id)
                    )
                    await db.commit()
            elif adjustment.startswith('-'):
                amount = round(float(adjustment[1:]), 2)
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE reviewers SET total_points = MAX(0, total_points - ?) WHERE user_id = ?",
                        (amount, reviewer.id)
                    )
                    await db.commit()
            elif adjustment.startswith('='):
                amount = round(float(adjustment[1:]), 2)
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE reviewers SET total_points = ? WHERE user_id = ?",
                        (amount, reviewer.id)
                    )
                    await db.commit()
            else:
                await ctx.send("❌ Invalid format. Use +50, -20, or =500 (decimals OK: =498.5)")
                return

            embed = discord.Embed(
                title="✅ Points Adjusted",
                description=f"@{reviewer.name}",
                color=discord.Color.green()
            )
            embed.add_field(name="Adjustment", value=adjustment, inline=True)

            await ctx.send(embed=embed)

            # Trigger GitHub sync to update leaderboard
            await auto_update_drop_map_leaderboard(self.bot, triggered_by="setpointsmanual", force=True)

        except ValueError:
            await ctx.send("❌ Invalid amount.")

    @commands.command(name='setaccuracystreak')
    @commands.has_permissions(administrator=True)
    async def set_accuracy_streak_manual(self, ctx, reviewer: discord.Member, adjustment: str):
        """
        Manually adjust accuracy streak (admin only).
        Format: +5 or -2 (relative) or =10 (absolute)
        """
        pool = await get_pool()

        try:
            if adjustment.startswith('+'):
                amount = int(adjustment[1:])
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE accuracy_streaks SET current_streak = current_streak + ? WHERE reviewer_id = ?",
                        (amount, reviewer.id)
                    )
                    await db.commit()
            elif adjustment.startswith('-'):
                amount = int(adjustment[1:])
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE accuracy_streaks SET current_streak = MAX(0, current_streak - ?) WHERE reviewer_id = ?",
                        (amount, reviewer.id)
                    )
                    await db.commit()
            elif adjustment.startswith('='):
                amount = int(adjustment[1:])
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE accuracy_streaks SET current_streak = ? WHERE reviewer_id = ?",
                        (amount, reviewer.id)
                    )
                    await db.commit()
            else:
                await ctx.send("❌ Invalid format. Use +5, -2, or =10")
                return

            embed = discord.Embed(
                title="✅ Accuracy Streak Adjusted",
                description=f"@{reviewer.name}",
                color=discord.Color.green()
            )
            embed.add_field(name="Adjustment", value=adjustment, inline=True)
            await ctx.send(embed=embed)
            await auto_update_drop_map_leaderboard(self.bot, triggered_by="setaccuracystreak", force=True)

        except ValueError:
            await ctx.send("❌ Invalid amount.")

    @commands.command(name='setdailystreak')
    @commands.has_permissions(administrator=True)
    async def set_daily_streak_manual(self, ctx, reviewer: discord.Member, adjustment: str):
        """
        Manually adjust daily streak (admin only).
        Format: +3 or -1 (relative) or =7 (absolute)
        Awards milestone bonuses if streak hits 2, 5, 14, 30, 180, or 365 days.
        """
        pool = await get_pool()
        milestone_bonuses = {2: 10, 5: 100, 14: 300, 30: 750, 180: 8000, 365: 20000}
        bonus_awarded = 0

        try:
            new_streak = None
            async with pool.acquire() as db:
                if adjustment.startswith('+'):
                    amount = int(adjustment[1:])
                    await db.execute(
                        "UPDATE daily_streaks SET current_streak_days = current_streak_days + ? WHERE reviewer_id = ?",
                        (amount, reviewer.id)
                    )
                    # Get new streak value
                    async with db.execute(
                        "SELECT current_streak_days FROM daily_streaks WHERE reviewer_id = ?",
                        (reviewer.id,)
                    ) as cursor:
                        result = await cursor.fetchone()
                        new_streak = result[0] if result else 0
                elif adjustment.startswith('-'):
                    amount = int(adjustment[1:])
                    await db.execute(
                        "UPDATE daily_streaks SET current_streak_days = MAX(0, current_streak_days - ?) WHERE reviewer_id = ?",
                        (amount, reviewer.id)
                    )
                    # Get new streak value
                    async with db.execute(
                        "SELECT current_streak_days FROM daily_streaks WHERE reviewer_id = ?",
                        (reviewer.id,)
                    ) as cursor:
                        result = await cursor.fetchone()
                        new_streak = result[0] if result else 0
                elif adjustment.startswith('='):
                    amount = int(adjustment[1:])
                    new_streak = amount
                    await db.execute(
                        "UPDATE daily_streaks SET current_streak_days = ? WHERE reviewer_id = ?",
                        (amount, reviewer.id)
                    )
                else:
                    await ctx.send("❌ Invalid format. Use +3, -1, or =7")
                    return

                # Check if new streak hits a milestone and award bonus if not already awarded today
                if new_streak in milestone_bonuses:
                    async with db.execute(
                        "SELECT streak_bonus_this_day FROM daily_streaks WHERE reviewer_id = ?",
                        (reviewer.id,)
                    ) as cursor:
                        bonus_result = await cursor.fetchone()
                        current_bonus = bonus_result[0] if bonus_result else 0

                    if not current_bonus:
                        bonus_awarded = milestone_bonuses[new_streak]
                        await db.execute(
                            "UPDATE reviewers SET total_points = total_points + ? WHERE user_id = ?",
                            (bonus_awarded, reviewer.id)
                        )
                        await db.execute(
                            "UPDATE daily_streaks SET streak_bonus_this_day = ? WHERE reviewer_id = ?",
                            (bonus_awarded, reviewer.id)
                        )

                await db.commit()

            embed = discord.Embed(
                title="✅ Daily Streak Adjusted",
                description=f"@{reviewer.name}",
                color=discord.Color.green()
            )
            embed.add_field(name="Adjustment", value=adjustment, inline=True)
            embed.add_field(name="New Streak", value=f"{new_streak} days", inline=True)
            if bonus_awarded > 0:
                embed.add_field(name="🎉 Bonus Awarded", value=f"+{bonus_awarded} pts (Milestone!)", inline=True)
            await ctx.send(embed=embed)
            await auto_update_drop_map_leaderboard(self.bot, triggered_by="setdailystreak", force=True)

        except ValueError:
            await ctx.send("❌ Invalid amount.")

    @commands.command(name='setaccuracy')
    @commands.has_permissions(administrator=True)
    async def set_accuracy_manual(self, ctx, reviewer: discord.Member, adjustment: str):
        """
        Set a reviewer's accuracy by writing 30 ghost markers (admin only).
        Format: =95.5 (absolute, 0-100)

        Ghost markers mix into the rolling 30-marker window alongside real markers.
        Wrong ghosts are positioned at the NEWEST timestamps so they drain LAST as
        real reviews come in — preserving the admin's setting until the user has
        accumulated a full window of real data.

        Granularity is 1/30 (~3.33%). Requested value is rounded to closest achievable.
        """
        if not adjustment.startswith('='):
            await ctx.send("❌ Invalid format. Use =95.5 (absolute only)")
            return

        try:
            percentage = float(adjustment[1:])
        except ValueError:
            await ctx.send("❌ Invalid percentage.")
            return

        if percentage < 0 or percentage > 100:
            await ctx.send("❌ Accuracy must be between 0 and 100")
            return

        correct_count = round(percentage * 30 / 100)
        wrong_count = 30 - correct_count
        actual_pct = correct_count / 30 * 100

        import datetime
        now = datetime.datetime.utcnow()

        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "DELETE FROM ghost_markers WHERE reviewer_id = ?",
                (reviewer.id,)
            )

            # Correct ghosts first: older timestamps + lower IDs (drain first)
            for i in range(correct_count):
                ts = now - datetime.timedelta(seconds=30 - i)
                await db.execute(
                    """INSERT INTO ghost_markers
                       (reviewer_id, correct, timestamp, set_by_admin, set_at)
                       VALUES (?, 1, ?, ?, ?)""",
                    (reviewer.id, ts.isoformat(), ctx.author.id, now.isoformat())
                )

            # Wrong ghosts last: newer timestamps + higher IDs (drain last)
            for i in range(wrong_count):
                ts = now - datetime.timedelta(seconds=wrong_count - i)
                await db.execute(
                    """INSERT INTO ghost_markers
                       (reviewer_id, correct, timestamp, set_by_admin, set_at)
                       VALUES (?, 0, ?, ?, ?)""",
                    (reviewer.id, ts.isoformat(), ctx.author.id, now.isoformat())
                )

            await db.commit()

        new_tier, new_mult, new_acc = await update_reviewer_tier(reviewer.id)

        tier_emoji = {
            'Master': '👑', 'Expert': '⭐', 'Advanced': '📈',
            'Intermediate': '🎯', 'Beginner': '🌱'
        }.get(new_tier, '📊')

        embed = discord.Embed(
            title="✅ Accuracy Set via Ghost Markers",
            description=f"@{reviewer.name}",
            color=discord.Color.green()
        )
        embed.add_field(name="Requested", value=f"{percentage}%", inline=True)
        embed.add_field(
            name="Actual",
            value=f"{actual_pct:.2f}% ({correct_count}/30)",
            inline=True
        )
        embed.add_field(
            name="New Tier",
            value=f"{tier_emoji} {new_tier} ({new_mult}x)",
            inline=True
        )
        embed.add_field(
            name="How it works",
            value=(f"30 ghosts written ({correct_count} ✅ + {wrong_count} ❌). "
                   f"Wrong ghosts sit at the newest position — they drain LAST as real "
                   f"reviews come in. After 30 real reviews, ghosts are fully gone and "
                   f"real accuracy takes over."),
            inline=False
        )
        await ctx.send(embed=embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="setaccuracy", force=True)

    @commands.command(name='unlockaccuracy')
    @commands.has_permissions(administrator=True)
    async def unlock_accuracy(self, ctx, reviewer: discord.Member):
        """Delete all ghost markers for a reviewer so real markers fully drive tier."""
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM ghost_markers WHERE reviewer_id = ?",
                (reviewer.id,)
            ) as cursor:
                ghost_count = (await cursor.fetchone())[0]

            await db.execute(
                "DELETE FROM ghost_markers WHERE reviewer_id = ?",
                (reviewer.id,)
            )
            await db.commit()

        new_tier, new_mult, new_acc = await update_reviewer_tier(reviewer.id)

        tier_emoji = {
            'Master': '👑', 'Expert': '⭐', 'Advanced': '📈',
            'Intermediate': '🎯', 'Beginner': '🌱'
        }.get(new_tier, '📊')

        embed = discord.Embed(
            title="🔓 Ghost Markers Cleared",
            description=f"@{reviewer.name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Ghosts Deleted", value=str(ghost_count), inline=True)
        embed.add_field(name="New Tier", value=f"{tier_emoji} {new_tier} ({new_mult}x)", inline=True)
        embed.add_field(name="New Accuracy", value=f"{new_acc:.1f}%", inline=True)
        await ctx.send(embed=embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="unlockaccuracy", force=True)

    @commands.command(name='listoverrides')
    @commands.has_permissions(administrator=True)
    async def list_overrides(self, ctx):
        """List all reviewers currently affected by ghost markers (admin overrides)."""
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute("""
                SELECT
                    g.reviewer_id,
                    COUNT(*) as total,
                    SUM(g.correct) as correct,
                    MAX(g.set_at) as set_at,
                    MAX(g.set_by_admin) as set_by,
                    r.username
                FROM ghost_markers g
                LEFT JOIN reviewers r ON g.reviewer_id = r.user_id
                GROUP BY g.reviewer_id
                ORDER BY MAX(g.set_at) DESC
            """) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send("✅ No active ghost markers (no admin overrides in effect).")
            return

        embed = discord.Embed(
            title="📋 Active Ghost Overrides",
            description=f"{len(rows)} reviewer(s) with admin-set ghosts",
            color=discord.Color.gold()
        )

        lines = []
        for reviewer_id, total, correct, set_at, set_by, username in rows:
            target_pct = (correct / total * 100) if total else 0
            date = set_at[:10] if set_at else "unknown"
            display_name = username or f"user_{reviewer_id}"
            lines.append(
                f"• **{display_name}** — {correct}/{total} ghosts ({target_pct:.1f}%) — set {date}"
            )

        embed.add_field(
            name="Reviewers",
            value="\n".join(lines)[:1024],
            inline=False
        )
        embed.set_footer(text="Use >unlockaccuracy <user> to remove a user's ghosts.")
        await ctx.send(embed=embed)

    @commands.command(name='markers')
    @commands.has_permissions(administrator=True)
    async def markers_history(self, ctx, reviewer: discord.Member):
        """Show the last 30 markers for a reviewer, numbered (1 = most recent).

        Use `>setmarker @user <pos> <correct|wrong>` to flip a specific marker,
        or `>markerset @user <correct>/<total>` to bulk-replace all markers.
        """
        from database import update_reviewer_tier
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT id, correct, timestamp FROM reviewer_markers WHERE reviewer_id = ? ORDER BY timestamp DESC, id DESC LIMIT 30",
                (reviewer.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send(f"❌ {reviewer.mention} has no markers in `reviewer_markers`.")
            return

        lines = []
        correct_count = 0
        for pos, row in enumerate(rows, start=1):
            row_id, correct, ts = row[0], row[1], row[2]
            icon = "✓" if correct else "✗"
            if correct:
                correct_count += 1
            ts_str = str(ts)[:16] if ts else "—"
            lines.append(f"`{pos:>2}.` {icon}  {ts_str}")

        total = len(rows)
        accuracy = correct_count / total * 100

        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 1 > 1000:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)

        embed = discord.Embed(
            title=f"📋 Marker History — @{reviewer.name}",
            description=f"Showing last **{total}** markers (1 = most recent)",
            color=discord.Color.blurple()
        )
        for i, chunk in enumerate(chunks, 1):
            name = "Markers" if len(chunks) == 1 else f"Markers ({i}/{len(chunks)})"
            embed.add_field(name=name, value=chunk, inline=False)
        embed.add_field(name="Accuracy", value=f"**{correct_count}/{total} = {accuracy:.1f}%**", inline=False)
        embed.set_footer(text="Flip one: >setmarker @user <pos> correct|wrong  •  Bulk: >markerset @user X/Y")
        await ctx.send(embed=embed)

    @commands.command(name='setmarker')
    @commands.has_permissions(administrator=True)
    async def set_marker_state(self, ctx, reviewer: discord.Member, position: int = None, state: str = None):
        """Flip a specific marker (by position from >markers) to correct or wrong.

        Position is 1-indexed where 1 = most recent.
        State accepts: correct / right / c  •  wrong / incorrect / w.

        Usage:
          >setmarker @user                  (interactive — shows markers, prompts)
          >setmarker @user 3                (asks state only)
          >setmarker @user 3 wrong          (direct, no prompts)
        """
        from database import update_reviewer_tier

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        # Pull this reviewer's markers up front — used to validate inputs and show the picker
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT id, correct, timestamp FROM reviewer_markers WHERE reviewer_id = ? ORDER BY timestamp DESC, id DESC LIMIT 30",
                (reviewer.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send(f"❌ {reviewer.mention} has no markers — use `>markerset` to seed some.")
            return

        # Step 1: Position (interactive if missing)
        if position is None:
            lines = []
            for pos, row in enumerate(rows, start=1):
                _id, correct, ts = row[0], row[1], row[2]
                icon = "✓" if correct else "✗"
                ts_str = str(ts)[:16] if ts else "—"
                lines.append(f"`{pos:>2}.` {icon}  {ts_str}")

            chunks, current = [], ""
            for line in lines:
                if len(current) + len(line) + 1 > 1000:
                    chunks.append(current)
                    current = line
                else:
                    current = f"{current}\n{line}" if current else line
            if current:
                chunks.append(current)

            picker_embed = discord.Embed(
                title=f"✏️ Set Marker — @{reviewer.name}",
                description=f"Pick which marker to flip (1 = most recent, {len(rows)} markers total).",
                color=discord.Color.blurple()
            )
            for i, chunk in enumerate(chunks, 1):
                name = "Markers" if len(chunks) == 1 else f"Markers ({i}/{len(chunks)})"
                picker_embed.add_field(name=name, value=chunk, inline=False)
            picker_embed.set_footer(text=f"Reply with the position number (1–{len(rows)}). 60s timeout.")
            await ctx.send(embed=picker_embed)

            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60)
                position = int(msg.content.strip())
            except (ValueError, asyncio.TimeoutError):
                await ctx.send("❌ Invalid position or timed out — no change.")
                return

        # Validate position
        if position < 1 or position > 30:
            await ctx.send(f"❌ Position must be 1–30 (the calc window). Got {position}.")
            return
        if position > len(rows):
            await ctx.send(f"❌ Only {len(rows)} markers exist — position {position} is out of range.")
            return

        target = rows[position - 1]
        target_id   = target[0]
        old_correct = bool(target[1])
        target_ts   = target[2]
        current_icon = "✓" if old_correct else "✗"

        # Step 2: State (interactive if missing)
        if state is None:
            state_embed = discord.Embed(
                title=f"✏️ Set Marker #{position} — @{reviewer.name}",
                description=(
                    f"Currently: **{current_icon} {'correct' if old_correct else 'wrong'}**\n"
                    f"Marker time: `{str(target_ts)[:19] if target_ts else '—'}`\n\n"
                    f"Reply with: `correct` / `c` (✓) or `wrong` / `w` (✗)"
                ),
                color=discord.Color.orange()
            )
            state_embed.set_footer(text="60s timeout.")
            await ctx.send(embed=state_embed)

            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60)
                state = msg.content.strip()
            except asyncio.TimeoutError:
                await ctx.send("⏱️ Timed out — no change.")
                return

        # Resolve state
        state_lower = state.lower().strip()
        if state_lower in ('correct', 'right', 'c', 'true', '1', '✓'):
            new_correct = 1
            state_display = "correct ✓"
        elif state_lower in ('wrong', 'incorrect', 'w', 'false', '0', '✗'):
            new_correct = 0
            state_display = "wrong ✗"
        else:
            await ctx.send(f"❌ Invalid state `{state}`. Use `correct` or `wrong`.")
            return

        if bool(new_correct) == old_correct:
            await ctx.send(
                f"ℹ️ Marker #{position} for {reviewer.mention} is already {state_display} "
                f"({current_icon}). No change."
            )
            return

        async with pool.acquire() as db:
            await db.execute(
                "UPDATE reviewer_markers SET correct = ? WHERE id = ?",
                (new_correct, target_id)
            )
            await db.commit()

        new_tier, new_mult, new_acc = await update_reviewer_tier(reviewer.id)

        new_icon = "✓" if new_correct else "✗"
        embed = discord.Embed(
            title="✏️ Marker Updated",
            description=f"@{reviewer.name} — marker #{position}",
            color=discord.Color.green()
        )
        embed.add_field(name="Before", value=f"{current_icon} {'correct' if old_correct else 'wrong'}", inline=True)
        embed.add_field(name="After",  value=f"{new_icon} {state_display}", inline=True)
        embed.add_field(name="Marker Time", value=str(target_ts)[:19] if target_ts else "—", inline=False)
        embed.add_field(name="Recalculated", value=f"Tier **{new_tier}** ({new_mult}x) • Accuracy **{new_acc:.1f}%**", inline=False)
        await ctx.send(embed=embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="setmarker", force=True)

    @commands.command(name='markerset')
    @commands.has_permissions(administrator=True)
    async def marker_bulk_set(self, ctx, reviewer: discord.Member, ratio: str):
        """DESTRUCTIVE: replace ALL markers with a fresh set in `<correct>/<total>` ratio.

        Example: `>markerset @user 24/30` → wipes all markers, inserts 24 correct + 6 wrong.
        Total max 30 (the accuracy calc window). Requires ✅ confirmation.
        """
        from database import update_reviewer_tier
        from datetime import datetime, timezone

        try:
            correct_str, total_str = ratio.split('/')
            correct_n = int(correct_str.strip())
            total_n   = int(total_str.strip())
        except (ValueError, AttributeError):
            await ctx.send("❌ Invalid format. Use `<correct>/<total>` like `24/30`.")
            return

        if total_n < 1 or total_n > 30:
            await ctx.send(f"❌ Total must be 1–30 (the accuracy calc window). Got {total_n}.")
            return
        if correct_n < 0 or correct_n > total_n:
            await ctx.send(f"❌ Correct ({correct_n}) must be between 0 and total ({total_n}).")
            return

        wrong_n = total_n - correct_n

        # Confirm
        confirm_embed = discord.Embed(
            title="⚠️ Bulk Marker Replace — CONFIRM",
            description=f"This will **DELETE ALL** existing markers for {reviewer.mention} and replace them with:",
            color=discord.Color.orange()
        )
        confirm_embed.add_field(name="✓ Correct", value=str(correct_n), inline=True)
        confirm_embed.add_field(name="✗ Wrong",   value=str(wrong_n),   inline=True)
        confirm_embed.add_field(name="Total",     value=str(total_n),   inline=True)
        confirm_embed.add_field(name="Resulting Accuracy", value=f"**{correct_n/total_n*100:.1f}%**", inline=False)
        confirm_embed.set_footer(text="React ✅ within 30s to confirm, ❌ to cancel")
        msg = await ctx.send(embed=confirm_embed)
        await msg.add_reaction('✅')
        await msg.add_reaction('❌')

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', check=check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Confirmation timed out — markers NOT changed.")
            return

        if str(reaction.emoji) == '❌':
            await ctx.send("❌ Cancelled — markers unchanged.")
            return

        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute("DELETE FROM reviewer_markers WHERE reviewer_id = ?", (reviewer.id,))

            # Insert with staggered timestamps so order is deterministic (oldest first → newest last)
            base_ts = datetime.now(timezone.utc)
            for i in range(total_n):
                ts = base_ts.replace(microsecond=i * 1000).isoformat()
                is_correct = 1 if i < correct_n else 0
                await db.execute(
                    "INSERT INTO reviewer_markers (reviewer_id, correct, timestamp) VALUES (?, ?, ?)",
                    (reviewer.id, is_correct, ts)
                )
            await db.commit()

        new_tier, new_mult, new_acc = await update_reviewer_tier(reviewer.id)

        done_embed = discord.Embed(
            title="✅ Markers Replaced",
            description=f"@{reviewer.name} — fresh set of {total_n} markers",
            color=discord.Color.green()
        )
        done_embed.add_field(name="Set To", value=f"{correct_n}/{total_n} = **{correct_n/total_n*100:.1f}%**", inline=False)
        done_embed.add_field(name="Recalculated", value=f"Tier **{new_tier}** ({new_mult}x) • Accuracy **{new_acc:.1f}%**", inline=False)
        await ctx.send(embed=done_embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="markerset", force=True)

    @commands.command(name='settotalmarkers')
    @commands.has_permissions(administrator=True)
    async def set_total_markers_manual(self, ctx, reviewer: discord.Member, adjustment: str):
        """
        Manually set total markers reviewed (admin only).
        Format: +10 or -5 (relative) or =250 (absolute)
        """
        pool = await get_pool()

        try:
            new_total = None
            async with pool.acquire() as db:
                if adjustment.startswith('+'):
                    amount = int(adjustment[1:])
                    await db.execute(
                        "UPDATE reviewers SET total_markers_reviewed = total_markers_reviewed + ? WHERE user_id = ?",
                        (amount, reviewer.id)
                    )
                    # Get new total
                    async with db.execute(
                        "SELECT total_markers_reviewed FROM reviewers WHERE user_id = ?",
                        (reviewer.id,)
                    ) as cursor:
                        result = await cursor.fetchone()
                        new_total = result[0] if result else 0
                elif adjustment.startswith('-'):
                    amount = int(adjustment[1:])
                    await db.execute(
                        "UPDATE reviewers SET total_markers_reviewed = MAX(0, total_markers_reviewed - ?) WHERE user_id = ?",
                        (amount, reviewer.id)
                    )
                    # Get new total
                    async with db.execute(
                        "SELECT total_markers_reviewed FROM reviewers WHERE user_id = ?",
                        (reviewer.id,)
                    ) as cursor:
                        result = await cursor.fetchone()
                        new_total = result[0] if result else 0
                elif adjustment.startswith('='):
                    amount = int(adjustment[1:])
                    if amount < 0:
                        await ctx.send("❌ Total markers cannot be negative")
                        return
                    new_total = amount
                    await db.execute(
                        "UPDATE reviewers SET total_markers_reviewed = ? WHERE user_id = ?",
                        (amount, reviewer.id)
                    )
                else:
                    await ctx.send("❌ Invalid format. Use +10, -5, or =250")
                    return

                await db.commit()

            embed = discord.Embed(
                title="✅ Total Markers Adjusted",
                description=f"@{reviewer.name}",
                color=discord.Color.green()
            )
            embed.add_field(name="Adjustment", value=adjustment, inline=True)
            embed.add_field(name="New Total", value=f"{new_total} markers", inline=True)
            await ctx.send(embed=embed)
            await auto_update_drop_map_leaderboard(self.bot, triggered_by="settotalmarkers", force=True)

        except ValueError:
            await ctx.send("❌ Invalid amount.")

    @commands.command(name='setmilestonenotifications')
    @commands.has_permissions(administrator=True)
    async def set_milestone_notifications(self, ctx):
        """
        Enable and set channel/thread for milestone celebration messages.
        Usage: >setmilestonenotifications #channel
        If used in a thread, sets notifications to that thread.
        (Also re-enables if previously disabled)
        """
        guild_id = ctx.guild.id

        # Parse channel mention
        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
        else:
            await ctx.send("❌ Please mention a channel: >setmilestonenotifications #channel")
            return

        # Check if we're in a thread
        thread_id = None
        if isinstance(ctx.channel, discord.Thread):
            thread_id = ctx.channel.id

        await set_milestone_notification_channel(guild_id, channel.id, thread_id)

        embed = discord.Embed(
            title="✅ Milestone Notifications Set",
            description=f"Celebration messages will be sent to {channel.mention}",
            color=discord.Color.green()
        )
        if thread_id:
            thread = self.bot.get_channel(thread_id)
            embed.description += f" → {thread.mention}" if thread else f" (thread #{thread_id})"
        await ctx.send(embed=embed)

    @commands.command(name='getmilestonenotifications')
    @commands.has_permissions(administrator=True)
    async def get_milestone_notifications(self, ctx):
        """
        Show current milestone notification channel/thread.
        Usage: >getmilestonenotifications
        """
        guild_id = ctx.guild.id
        channel_id, thread_id = await get_milestone_notification_channel(guild_id)

        if channel_id:
            channel = self.bot.get_channel(channel_id)
            thread = self.bot.get_channel(thread_id) if thread_id else None
            channel_name = channel.mention if channel else f"<#{channel_id}>"
            thread_name = f" → {thread.mention}" if thread else ""
            await ctx.send(f"📢 Milestone notifications currently set to: {channel_name}{thread_name}")
        else:
            await ctx.send("📢 Milestone notifications are not configured.")

    @commands.command(name='disablemilestonenotifications')
    @commands.has_permissions(administrator=True)
    async def disable_milestone_notifications(self, ctx):
        """
        Disable milestone celebration notifications.
        Usage: >disablemilestonenotifications
        To re-enable: >setmilestonenotifications #channel
        """
        guild_id = ctx.guild.id
        await set_milestone_notification_channel(guild_id, None, None)
        embed = discord.Embed(
            title="✅ Milestone Notifications Disabled",
            description="To re-enable: `>setmilestonenotifications #channel`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

    async def _resolve_milestone_target(self, guild_id: int):
        """Resolve the milestone channel/thread for sending, robustly.

        bot.get_channel misses threads that are archived or not in cache — common
        right after >closeday archives the review threads, or after a restart — which
        is why celebration posts could silently vanish. Fall back to fetch_channel,
        and un-archive the thread so the message lands where it was configured.
        Returns a sendable channel/thread, or None if it can't be resolved.
        """
        channel_id, thread_id = await get_milestone_notification_channel(guild_id)
        target = None
        if thread_id:
            target = self.bot.get_channel(thread_id)
            if target is None:
                try:
                    target = await self.bot.fetch_channel(thread_id)
                except Exception:
                    target = None
        if target is None and channel_id:
            target = self.bot.get_channel(channel_id)
            if target is None:
                try:
                    target = await self.bot.fetch_channel(channel_id)
                except Exception:
                    target = None
        if isinstance(target, discord.Thread) and target.archived:
            try:
                await target.edit(archived=False)
            except Exception:
                pass
        return target

    @commands.command(name='addreviewer')
    @commands.has_permissions(administrator=True)
    async def add_reviewer(self, ctx, member: discord.Member):
        """
        Add a user as a Drop Map Reviewer.
        Adds them to database and gives them the Drop Map Reviewer role in both guilds.

        Usage: >addreviewer @user
        """
        results = await add_drop_map_reviewer(member.id, self.bot)

        embed = discord.Embed(
            title="✅ Drop Map Reviewer Added",
            description=f"@{member.name}",
            color=discord.Color.green()
        )

        for key, value in results.items():
            if key == 'database':
                embed.add_field(name="Database", value=value, inline=False)
            else:
                guild_id = key.split('_')[1] if '_' in key else key
                embed.add_field(name=f"Guild {guild_id}", value=value, inline=False)

        await ctx.send(embed=embed)

        # Trigger GitHub sync
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="reviewer_added", force=True)

    @commands.command(name='removereviewer')
    @commands.has_permissions(administrator=True)
    async def remove_reviewer(self, ctx, member: discord.Member):
        """
        Remove a user as a Drop Map Reviewer.
        Removes them from database and takes away the Drop Map Reviewer role from both guilds.

        Usage: >removereviewer @user
        """
        results = await remove_drop_map_reviewer(member.id, self.bot)

        embed = discord.Embed(
            title="🗑️ Drop Map Reviewer Removed",
            description=f"@{member.name}",
            color=discord.Color.red()
        )

        for key, value in results.items():
            if key == 'database':
                embed.add_field(name="Database", value=value, inline=False)
            else:
                guild_id = key.split('_')[1] if '_' in key else key
                embed.add_field(name=f"Guild {guild_id}", value=value, inline=False)

        await ctx.send(embed=embed)

        # Trigger GitHub sync
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="reviewer_removed", force=True)

    @commands.command(name='wipereviewing')
    @commands.has_permissions(administrator=True)
    async def wipe_reviewing(self, ctx):
        """Admin: WIPE all drop map reviewing data + reset GitHub JSONs.

        Procedure:
          1. Confirms no active session exists
          2. Shows what will be wiped
          3. Requires admin reaction confirmation
          4. Clears all reviewing DB tables
          5. Resets session_history.json, daily_summary.json, drop_map_reviewing.json on GitHub
          6. Re-syncs reviewers from Discord roles
        """
        pool = await get_pool()

        # 1. Check no active session
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT session_date FROM daily_sessions WHERE is_open = 1"
            ) as cursor:
                open_session = await cursor.fetchone()

        if open_session:
            session_date = open_session[0] if isinstance(open_session, tuple) else open_session['session_date']
            await ctx.send(f"❌ Cannot wipe — there's an active session for **{session_date}**. Run `>closeday` first.")
            return

        # 2. Count what's about to be wiped
        tables_to_wipe = [
            'reviewers', 'reviewers_temp', 'reviewer_markers',
            'ghost_markers', 'accuracy_streaks', 'daily_streaks',
            'daily_sessions', 'daily_activity_log', 'penalties',
            'session_counter'
        ]
        counts = {}
        async with pool.acquire() as db:
            for table in tables_to_wipe:
                try:
                    async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                        row = await cursor.fetchone()
                        counts[table] = row[0] if row else 0
                except Exception:
                    counts[table] = 0  # Table might not exist

        # 3. Show confirmation embed
        embed = discord.Embed(
            title="⚠️ WIPE REVIEWING DATA",
            description="This will **PERMANENTLY DELETE** all drop map reviewing data.\n\n**This cannot be undone.**",
            color=discord.Color.red()
        )
        table_lines = "\n".join(f"• `{t}`: **{c}** rows" for t, c in counts.items() if c > 0)
        if not table_lines:
            table_lines = "*(All tables already empty)*"
        embed.add_field(name="📦 DB Tables to Clear", value=table_lines, inline=False)
        embed.add_field(
            name="🌐 GitHub Files to Reset",
            value="• `session_history.json` → `{\"sessions\": []}`\n"
                  "• `daily_summary.json` → empty\n"
                  "• `drop_map_reviewing.json` → empty (will auto-rebuild on next push)",
            inline=False
        )
        embed.add_field(
            name="🔄 What Happens After",
            value="• Reviewers re-synced from Discord role on next bot restart\n"
                  "• Run `>newday` to start fresh session 1",
            inline=False
        )
        embed.set_footer(text="React ✅ to CONFIRM wipe or ❌ to cancel  •  60s timeout")

        msg = await ctx.send(embed=embed)
        await msg.add_reaction('✅')
        await msg.add_reaction('❌')

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Wipe cancelled.")
            return

        if str(reaction.emoji) == '❌':
            await ctx.send("❌ Wipe cancelled.")
            return

        # 4. Perform the wipe
        await ctx.send("🧹 Wiping database...")
        async with pool.acquire() as db:
            for table in tables_to_wipe:
                try:
                    await db.execute(f"DELETE FROM {table}")
                except Exception as e:
                    logger.error(f"Failed to clear {table}: {e}")
            await db.commit()

        # 5. Reset local + GitHub JSONs
        await ctx.send("🌐 Resetting local + GitHub JSON files...")
        from tasks.staff_hub_writer import replace_json_on_github
        import os

        empty_history = {"sessions": []}
        empty_summary = {
            "date": None,
            "guild_id": ctx.guild.id,
            "summary": {
                "total_points": 0,
                "total_markers": 0,
                "active_reviewers": 0,
                "tier_promotions": 0,
                "milestone_hits": 0
            },
            "activities": [],
            "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        empty_leaderboard = {
            "reviewers": [],
            "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        # Reset local files (project root/json_data/)
        local_files = {
            "drop_map_reviewing.json": empty_leaderboard,
            "session_history.json": empty_history,
            "daily_summary.json": empty_summary
        }
        for filename, content in local_files.items():
            try:
                local_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'json_data', filename)
                with open(local_path, 'w') as f:
                    json.dump(content, f, indent=2)
                logger.info(f"✅ Reset local {filename}")
            except Exception as e:
                logger.warning(f"⚠️ Could not reset local {filename}: {e}")

        # Reset GitHub files
        history_ok = await replace_json_on_github("session_history.json", empty_history)
        summary_ok = await replace_json_on_github("daily_summary.json", empty_summary)
        leaderboard_ok = await replace_json_on_github("drop_map_reviewing.json", empty_leaderboard)

        # 6. Re-sync reviewers from Discord roles
        await ctx.send("🔄 Re-syncing reviewers from Discord roles...")
        from database import sync_role_with_database
        await sync_role_with_database(self.bot)

        # 7. Final report
        result_embed = discord.Embed(
            title="✅ Reviewing Data Wiped",
            description="All reviewing data has been reset.",
            color=discord.Color.green()
        )
        result_embed.add_field(
            name="GitHub Files",
            value=f"• session_history.json: {'✅' if history_ok else '❌'}\n"
                  f"• daily_summary.json: {'✅' if summary_ok else '❌'}\n"
                  f"• drop_map_reviewing.json: {'✅' if leaderboard_ok else '❌'}",
            inline=False
        )
        result_embed.add_field(
            name="Next Steps",
            value="Run `>newday` to start a fresh session.",
            inline=False
        )
        await ctx.send(embed=result_embed)

    @commands.command(name='newday')
    @commands.has_permissions(administrator=True)
    async def new_day(self, ctx, session_date: str = None):
        """Open a new reviewing session for the day.

        Usage:
          >newday                    (opens for today, or next day after last closed)
          >newday 2026-05-12         (opens for specific date)
          >newday May 12             (opens for specific date this year)
        """
        from database import get_pool
        from datetime import datetime, date, timedelta

        guild_id = ctx.guild.id
        pool = await get_pool()

        # Determine the session date
        if not session_date:
            # Find the most recent session (open or closed) and default to next day
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT session_date FROM daily_sessions WHERE guild_id = ? ORDER BY session_date DESC LIMIT 1",
                    (guild_id,)
                ) as cursor:
                    last_session = await cursor.fetchone()

            if last_session:
                # Use the day after the most recent session (regardless of whether it's open/closed)
                last_date = datetime.strptime(last_session[0], '%Y-%m-%d').date()
                session_date = last_date + timedelta(days=1)
            else:
                # No previous sessions, default to today
                session_date = date.today()
        else:
            # Parse the provided date
            try:
                session_date = datetime.strptime(session_date, '%Y-%m-%d').date()
            except:
                try:
                    session_date = datetime.strptime(session_date, '%B %d').date()
                    session_date = session_date.replace(year=date.today().year)
                except:
                    await ctx.send("❌ Invalid date format. Use:\n  `>newday YYYY-MM-DD`  or  `>newday May 12`")
                    return

        async with pool.acquire() as db:
            # Check if session already open for this date
            async with db.execute(
                "SELECT is_open FROM daily_sessions WHERE guild_id = ? AND session_date = ?",
                (guild_id, session_date.isoformat())
            ) as cursor:
                existing = await cursor.fetchone()

            if existing and existing[0] == 1:
                embed = discord.Embed(
                    title="⚠️ SESSION ALREADY OPEN",
                    description=f"A reviewing session is **ALREADY OPEN** for:\n\n**{session_date.strftime('%A, %B %d, %Y')}**",
                    color=discord.Color.red()
                )
                embed.add_field(name="Date", value=session_date.isoformat(), inline=True)
                embed.add_field(name="Status", value="🔓 OPEN", inline=True)
                embed.add_field(name="Action Required", value=f"Close it first:\n`>closeday {session_date.isoformat()}`", inline=False)
                await ctx.send(embed=embed)
                return

            await db.execute(
                "INSERT INTO daily_sessions (guild_id, session_date, is_open) VALUES (?, ?, 1) ON CONFLICT(guild_id, session_date) DO UPDATE SET is_open = 1, closed_at = NULL",
                (guild_id, session_date.isoformat())
            )
            await db.commit()

        # Read the upcoming session number (the number this open session will get on >closeday).
        # Counter is global and is incremented at closeday — we only peek here.
        upcoming_session_id = None
        try:
            async with pool.acquire() as db:
                async with db.execute("SELECT next_session_id FROM session_counter WHERE id = 1") as cursor:
                    row = await cursor.fetchone()
                if row:
                    upcoming_session_id = row[0]
                else:
                    await db.execute("INSERT INTO session_counter (id, next_session_id) VALUES (1, 1)")
                    await db.commit()
                    upcoming_session_id = 1
        except Exception as e:
            logger.warning(f"Could not read next_session_id for newday announcement: {e}")

        # Pick daily challenges (1 per tier) — idempotent if already picked for this date
        try:
            from database import pick_challenges_for_session
            picked_challenges = await pick_challenges_for_session(session_date.isoformat())
        except Exception as e:
            logger.error(f"❌ Could not pick challenges for {session_date}: {e}")
            picked_challenges = []

        session_label = f"Session #{upcoming_session_id}" if upcoming_session_id is not None else "New Reviewing Session"

        embed = discord.Embed(
            title=f"🆕 {session_label} Opened",
            description=f"**{session_date.strftime('%A, %B %d, %Y')}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Status", value="✅ Open", inline=True)
        embed.add_field(name="Date", value=session_date.isoformat(), inline=True)
        if upcoming_session_id is not None:
            embed.add_field(name="Session #", value=f"`{upcoming_session_id}`", inline=True)
        embed.add_field(name="Accepting Reviews", value="`>addpoints`", inline=True)
        embed.add_field(name="Close Session", value=f"`>closeday {session_date.isoformat()}`", inline=True)

        if picked_challenges:
            tier_emoji = {'easy': '🟢', 'medium': '🔵', 'hard': '🟣'}
            challenge_lines = "\n".join(
                f"{tier_emoji.get(c['tier'], '🎯')} **{c['name']}** (+{c['reward']} pts) — _{c['description']}_"
                for c in picked_challenges
            )
            embed.add_field(name="🎯 Today's Challenges", value=challenge_lines, inline=False)

        await ctx.send(embed=embed)

        # Public hype: announce today's challenges to the milestone channel with @everyone
        if picked_challenges:
            try:
                ms_target = await self._resolve_milestone_target(ctx.guild.id)

                if ms_target:
                    tier_emoji = {'easy': '🟢', 'medium': '🔵', 'hard': '🟣'}
                    session_tag = f"SESSION #{upcoming_session_id}" if upcoming_session_id is not None else "NEW SESSION"
                    announce_embed = discord.Embed(
                        title=f"🆕  NEW DAY — {session_tag} — TODAY'S CHALLENGES UNLOCKED  🆕",
                        description=(
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"### 📅 {session_date.strftime('%A, %B %d, %Y')}\n"
                            + (f"### 🗂️ Session #{upcoming_session_id}\n\n" if upcoming_session_id is not None else "\n")
                            + "⚡ **FIRST REVIEWER to hit the target CLAIMS the challenge** — no one else can take it.\n"
                            "🏆 One reviewer could win all 3. **Move fast.**\n\n"
                            "Lock these in with `>addpoints`. Bonuses confirm at `>endday`.\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                        ),
                        color=discord.Color.from_rgb(255, 215, 0)
                    )
                    for c in picked_challenges:
                        te = tier_emoji.get(c['tier'], '🎯')
                        announce_embed.add_field(
                            name=f"{te} {c['tier'].upper()}  ·  {c['name']}  ·  +{c['reward']} pts",
                            value=f"_{c['description']}_",
                            inline=False
                        )
                    leaderboard_url = "https://wavedropmaps.pages.dev/reviewing_leaderboard_final.html"
                    announce_embed.add_field(
                        name="📊 Track Your Progress",
                        value=f"[**Live Leaderboard →**]({leaderboard_url})",
                        inline=False
                    )
                    announce_embed.set_footer(text="Get reviewing — bonus points + leaderboard glory await 🌊")

                    await ms_target.send(
                        content="@everyone",
                        embed=announce_embed,
                        allowed_mentions=discord.AllowedMentions(everyone=True)
                    )
            except Exception as e:
                logger.warning(f"Could not announce challenges to milestone channel: {e}")

        # Trigger leaderboard sync so challenges appear immediately
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="newday")

    @commands.command(name='closeday')
    @commands.has_permissions(administrator=True)
    async def close_day(self, ctx, session_date: str = None):
        """Close the currently-open reviewing session.

        Usage:
          >closeday                  (closes whichever session is currently open)
          >closeday 2026-05-12       (closes specific date's session)
        """
        from database import get_pool
        from datetime import datetime, date, timedelta

        guild_id = ctx.guild.id
        pool = await get_pool()

        if not session_date:
            # No date passed — find the open session for this guild
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT session_date FROM daily_sessions WHERE guild_id = ? AND is_open = 1 ORDER BY session_date DESC LIMIT 1",
                    (guild_id,)
                ) as cursor:
                    open_row = await cursor.fetchone()

            if not open_row:
                await ctx.send("❌ No open reviewing session to close. Run `>newday` first.")
                return

            open_date_str = open_row[0] if isinstance(open_row[0], str) else open_row[0].isoformat()
            session_date = datetime.strptime(open_date_str, '%Y-%m-%d').date()
        else:
            try:
                session_date = datetime.strptime(session_date, '%Y-%m-%d').date()
            except:
                await ctx.send("❌ Invalid date format. Use: `>closeday YYYY-MM-DD`")
                return

        async with pool.acquire() as db:
            # Check if session is open
            async with db.execute(
                "SELECT is_open FROM daily_sessions WHERE guild_id = ? AND session_date = ?",
                (guild_id, session_date.isoformat())
            ) as cursor:
                existing = await cursor.fetchone()

            if not existing or existing[0] == 0:
                await ctx.send(f"⚠️ **WARNING:** No open reviewing session for **{session_date.strftime('%A, %B %d, %Y')}**\n\n❌ Open one first with `>newday {session_date.isoformat()}`")
                return

            # ── COLLECT SUMMARY STATISTICS FOR THE DAY ──
            # Reviewers active
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM reviewers_temp WHERE submission_date = ?",
                (session_date.isoformat(),)
            ) as cursor:
                reviewer_count = (await cursor.fetchone())[0] or 0

            # Total markers reviewed (sum of markers_reviewed across all submissions)
            async with db.execute(
                "SELECT COALESCE(SUM(markers_reviewed), 0) FROM reviewers_temp WHERE submission_date = ?",
                (session_date.isoformat(),)
            ) as cursor:
                total_markers = (await cursor.fetchone())[0] or 0

            # Correct markers: actual_correct for verified, provisional_correct for unverified
            async with db.execute(
                "SELECT COALESCE(SUM(CASE WHEN verified = 1 THEN actual_correct ELSE provisional_correct END), 0) FROM reviewers_temp WHERE submission_date = ?",
                (session_date.isoformat(),)
            ) as cursor:
                correct_markers = (await cursor.fetchone())[0] or 0

            # Points awarded that day (verified final_points only)
            async with db.execute(
                "SELECT COALESCE(SUM(final_points), 0) FROM reviewers_temp WHERE submission_date = ? AND verified = 1",
                (session_date.isoformat(),)
            ) as cursor:
                points_awarded = (await cursor.fetchone())[0] or 0

            # Penalties applied that day
            async with db.execute(
                "SELECT COUNT(*), SUM(points_deducted) FROM penalties WHERE DATE(applied_date) = ?",
                (session_date.isoformat(),)
            ) as cursor:
                penalty_row = await cursor.fetchone()
                penalty_count = penalty_row[0] or 0
                penalty_deduction = penalty_row[1] or 0

            # Challenge points awarded that day
            async with db.execute(
                """SELECT COALESCE(SUM(dc.reward), 0)
                   FROM challenge_completions cc
                   JOIN daily_challenges dc ON dc.session_date = cc.session_date AND dc.challenge_id = cc.challenge_id
                   WHERE cc.session_date = ? AND cc.bonus_awarded = 1""",
                (session_date.isoformat(),)
            ) as cursor:
                challenge_points = (await cursor.fetchone())[0] or 0

            # Milestone points awarded that day
            async with db.execute(
                "SELECT COALESCE(SUM(milestone_bonus_total), 0) FROM reviewers_temp WHERE submission_date = ? AND verified = 1",
                (session_date.isoformat(),)
            ) as cursor:
                milestone_points = (await cursor.fetchone())[0] or 0

            # Unverified TEMP submissions for this date (warn admin if >endday wasn't run)
            async with db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM reviewers_temp WHERE submission_date = ? AND verified = 0",
                (session_date.isoformat(),)
            ) as cursor:
                temp_row = await cursor.fetchone()
                unverified_count = temp_row[0] or 0
                unverified_users = temp_row[1] or 0

            # Show summary embed first
            summary_embed = discord.Embed(
                title="📊 Daily Session Summary",
                description=f"**{session_date.strftime('%A, %B %d, %Y')}**",
                color=discord.Color.blue()
            )
            summary_embed.add_field(name="👥 Reviewers Active", value=str(reviewer_count), inline=True)
            summary_embed.add_field(name="📝 Total Markers", value=str(total_markers), inline=True)
            summary_embed.add_field(name="✅ Correct", value=f"{correct_markers}/{total_markers} ({(correct_markers/total_markers*100 if total_markers else 0):.1f}%)", inline=True)
            summary_embed.add_field(name="💰 Points Awarded", value=str(points_awarded), inline=True)
            summary_embed.add_field(name="🏆 Milestones Awarded", value=f"{milestone_points} pts", inline=True)
            summary_embed.add_field(name="🏅 Challenges Awarded", value=f"{challenge_points} pts", inline=True)
            summary_embed.add_field(name="⚠️ Penalties Applied", value=f"{penalty_count} penalties (-{penalty_deduction} pts)", inline=True)
            summary_embed.add_field(name="📅 Session Status", value="✅ Ready to close", inline=True)
            if unverified_count > 0:
                summary_embed.add_field(
                    name="🚨 UNVERIFIED SUBMISSIONS",
                    value=f"**{unverified_count}** TEMP row(s) from **{unverified_users}** reviewer(s) have NOT been verified.\n"
                          f"Run `>endday` first, or these submissions will be **lost** at close.\n"
                          f"React ✅ only if you intend to discard them.",
                    inline=False
                )
                summary_embed.color = discord.Color.orange()
            summary_embed.set_footer(text="React ✅ to confirm close, or ❌ to cancel")

            msg = await ctx.send(embed=summary_embed)
            await msg.add_reaction('✅')
            await msg.add_reaction('❌')

            # Wait for confirmation
            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ['✅', '❌'] and reaction.message.id == msg.id

            try:
                reaction, user = await self.bot.wait_for('reaction_add', check=check, timeout=60)
            except:
                await ctx.send("⏱️ Confirmation timed out. Session NOT closed.")
                return

            if str(reaction.emoji) == '❌':
                await ctx.send("❌ Session close cancelled.")
                return

            # ── POST CHALLENGE WINNERS SUMMARY TO MILESTONE CHANNEL ──
            # Fires AFTER admin confirms close but BEFORE the session is actually
            # closed in the DB — so the milestone channel gets a day-end recap of
            # who claimed today's challenges.
            try:
                async with db.execute(
                    """SELECT challenge_id, challenge_name, challenge_description, challenge_tier,
                              reward, winner_user_id
                       FROM daily_challenges
                       WHERE session_date = ?
                       ORDER BY CASE challenge_tier
                                  WHEN 'easy' THEN 1
                                  WHEN 'medium' THEN 2
                                  WHEN 'hard' THEN 3
                                  ELSE 4
                                END""",
                    (session_date.isoformat(),)
                ) as cursor:
                    challenge_rows = await cursor.fetchall()

                if challenge_rows:
                    ms_target = await self._resolve_milestone_target(ctx.guild.id)

                    if ms_target:
                        tier_emoji = {'easy': '🟢', 'medium': '🔵', 'hard': '🟣'}
                        winners_embed = discord.Embed(
                            title="🏆  CHALLENGE WINNERS — DAY RECAP  🏆",
                            description=(
                                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                f"### 📅 {session_date.strftime('%A, %B %d, %Y')}\n\n"
                                "Today's session is wrapping up. Here's who claimed the challenges:\n"
                                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                            ),
                            color=discord.Color.from_rgb(255, 215, 0)
                        )
                        for cid, cname, cdesc, ctier, creward, winner_id in challenge_rows:
                            te = tier_emoji.get(ctier, '🎯')
                            if winner_id:
                                async with db.execute(
                                    "SELECT username FROM reviewers WHERE user_id = ?",
                                    (winner_id,)
                                ) as cursor:
                                    urow = await cursor.fetchone()
                                winner_name = urow[0] if urow else f"User {winner_id}"
                                winner_text = f"🥇 <@{winner_id}> (**{winner_name}**) — +{creward} pts"
                            else:
                                winner_text = "❌ _Nobody claimed this one_"
                            winners_embed.add_field(
                                name=f"{te} {ctier.upper()}  ·  {cname}  ·  +{creward} pts",
                                value=f"_{cdesc}_\n{winner_text}",
                                inline=False
                            )
                        winners_embed.set_footer(text="GG to today's winners 🌊")

                        await ms_target.send(
                            content="@everyone",
                            embed=winners_embed,
                            allowed_mentions=discord.AllowedMentions(everyone=True, users=True)
                        )
            except Exception as e:
                logger.warning(f"Could not post challenge winners to milestone channel: {e}")

            # ── GRAB SESSION OPEN TIME BEFORE WE FLIP IS_OPEN ──
            async with db.execute(
                "SELECT opened_at FROM daily_sessions WHERE guild_id = ? AND session_date = ?",
                (guild_id, session_date.isoformat())
            ) as cursor:
                opened_row = await cursor.fetchone()
                session_opened_at = opened_row[0] if opened_row else None

            # ── CLOSE ALL ACTIVE THREADS IN THE REVIEW CHANNEL ──
            TARGET_CHANNEL_ID = 1476531469949075497
            try:
                review_channel = self.bot.get_channel(TARGET_CHANNEL_ID)
                if review_channel:
                    closed_count = 0
                    async for thread in review_channel.archived_threads(limit=None, private=False):
                        # Skip if already archived
                        continue

                    # Get active (non-archived) threads
                    for thread in review_channel.threads:
                        if not thread.archived:
                            try:
                                await thread.edit(archived=True)
                                closed_count += 1
                                logger.info(f"✅ Closed thread: {thread.id} ({thread.name})")
                            except Exception as e:
                                logger.error(f"❌ Failed to close thread {thread.id}: {e}")

                    if closed_count > 0:
                        await ctx.send(f"📁 Archived **{closed_count}** active thread(s) in reviewing channel")
                        logger.info(f"[closeday] Archived {closed_count} threads in channel {TARGET_CHANNEL_ID}")
            except Exception as e:
                logger.error(f"❌ Error closing threads: {e}")

            # ── ACTUALLY CLOSE THE SESSION ──
            await db.execute(
                "UPDATE daily_sessions SET is_open = 0, closed_at = CURRENT_TIMESTAMP WHERE guild_id = ? AND session_date = ?",
                (guild_id, session_date.isoformat())
            )

            # ── RESET STREAKS FOR REVIEWERS WHO DIDN'T REVIEW THIS SESSION ──
            # Build the set of users who actually had VERIFIED review activity within
            # the session's time window. We use the timestamp range (session opened_at
            # → now) instead of matching DATE(timestamp) == session_date, because
            # >endday verification may stamp markers on a different calendar day than
            # the session date (cross-midnight, next-day verification, etc.).
            participants = set()
            if session_opened_at:
                async with db.execute(
                    "SELECT DISTINCT reviewer_id FROM reviewer_markers WHERE timestamp >= ?",
                    (session_opened_at,)
                ) as cursor:
                    for row in await cursor.fetchall():
                        participants.add(row[0])

            # Reset BOTH streak types for everyone with an active streak (daily OR accuracy)
            # who is NOT a participant. The union covers the case where a reviewer's daily
            # streak was already 0 from a prior session but they still carry an accuracy
            # streak that needs to die when they skip another day.
            async with db.execute(
                """SELECT reviewer_id FROM daily_streaks    WHERE current_streak_days > 0
                   UNION
                   SELECT reviewer_id FROM accuracy_streaks WHERE current_streak > 0"""
            ) as cursor:
                active_reviewers = await cursor.fetchall()

            streaks_reset = 0
            for reviewer_row in active_reviewers:
                reviewer_id = reviewer_row[0]
                if reviewer_id in participants:
                    continue
                await db.execute(
                    "UPDATE daily_streaks SET current_streak_days = 0 WHERE reviewer_id = ?",
                    (reviewer_id,)
                )
                await db.execute(
                    """UPDATE accuracy_streaks
                       SET current_streak = 0, milestones_hit_this_session = '[]'
                       WHERE reviewer_id = ?""",
                    (reviewer_id,)
                )
                streaks_reset += 1
            logger.info(f"[closeday] session={session_date.isoformat()} participants={len(participants)} streaks_reset={streaks_reset} (both daily + accuracy)")

            # ── RESET DAILY BONUSES AND MILESTONE TRACKING FOR NEW DAY ──
            # Reset streak bonuses (allows new bonuses next session)
            await db.execute(
                "UPDATE daily_streaks SET streak_bonus_this_day = 0"
            )

            # Reset accuracy streak milestone tracking for new session
            await db.execute(
                "UPDATE accuracy_streaks SET milestones_hit_this_session = '[]'"
            )

            # ── CAPTURE SESSION HISTORY (lifetime points) ──
            # Get all reviewers and their total_points at session close time
            async with db.execute("SELECT user_id, username, total_points FROM reviewers") as cursor:
                reviewer_rows = await cursor.fetchall()

            reviewers_data = {}
            for row in reviewer_rows:
                username = row[1] if isinstance(row, tuple) else row['username']
                total_points = row[2] if isinstance(row, tuple) else row['total_points']
                if total_points > 0:
                    reviewers_data[username] = total_points

            # ── CAPTURE PER-REVIEWER SUBMISSION COUNT (for weekly quota tracking) ──
            # Each row in reviewers_temp = one >addpoints call = one submission = one "map".
            # Counted BEFORE the DELETE below. Join against reviewers so we use the same
            # username key as reviewers_data (reviewers_temp.username is the display name
            # at submission time, which may differ).
            async with db.execute(
                """SELECT r.username, COUNT(t.id)
                   FROM reviewers_temp t
                   JOIN reviewers r ON r.user_id = t.user_id
                   WHERE t.submission_date = ?
                   GROUP BY t.user_id, r.username""",
                (session_date.isoformat(),)
            ) as cursor:
                submission_rows = await cursor.fetchall()

            submissions_data = {}
            for row in submission_rows:
                username = row[0]
                count = row[1] or 0
                if count > 0:
                    submissions_data[username] = count
            logger.info(f"[closeday] submissions captured: {len(submissions_data)} reviewers, total={sum(submissions_data.values())} >addpoints calls")

            # Get next session_id (inline to avoid nested pool.acquire)
            async with db.execute("SELECT next_session_id FROM session_counter WHERE id = 1") as cursor:
                counter_row = await cursor.fetchone()

            if not counter_row:
                await db.execute("INSERT INTO session_counter (id, next_session_id) VALUES (1, 2)")
                session_id = 1
            else:
                session_id = counter_row[0]
                await db.execute("UPDATE session_counter SET next_session_id = ? WHERE id = 1", (session_id + 1,))

            # Calendar date labels (NOT real-time timestamps):
            # open_day = this session's session_date (set when >newday ran)
            # close_day = open_day + 1 calendar day (the next session's open_day)
            from datetime import timedelta
            open_day = session_date.isoformat()
            close_day = (session_date + timedelta(days=1)).isoformat()

            session_history_data = {
                "session_id": session_id,
                "open_day": open_day,
                "close_day": close_day,
                "reviewers": reviewers_data,
                "submissions": submissions_data
            }

            # ── CLEAR ALL TEMP SUBMISSIONS FOR THIS DATE ──
            # (Verified rows: points already written to MAIN. Unverified: admin chose to discard
            # by confirming close after the warning embed.)
            await db.execute(
                "DELETE FROM reviewers_temp WHERE submission_date = ?",
                (session_date.isoformat(),)
            )

            await db.commit()

        # ── PUSH SESSION HISTORY TO GITHUB ──
        try:
            from tasks.staff_hub_writer import push_session_history_to_github
            success = await push_session_history_to_github(session_history_data)
            if success:
                await ctx.send("📊 Session history updated on GitHub Pages")
        except Exception as e:
            logger.error(f"❌ Failed to push session history: {e}")

        # ── PUSH DAILY SUMMARY TO GITHUB ──
        try:
            from tasks.staff_hub_writer import push_daily_summary_to_github

            summary_data = {
                "date": session_date.isoformat(),
                "guild_id": guild_id,
                "summary": {
                    "total_points": int(points_awarded),
                    "total_markers": total_markers,
                    "active_reviewers": reviewer_count,
                    "tier_promotions": 0,
                    "milestone_hits": 0
                },
                "activities": [],
                "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            }

            # Get detailed activity log for the day
            async with pool.acquire() as db:
                async with db.execute(
                    """SELECT reviewer_id, action_type, total_markers, correct_markers, points_awarded,
                              penalty_deduction, tier_before, tier_after FROM daily_activity_log
                       WHERE guild_id = ? AND session_date = ? ORDER BY timestamp DESC""",
                    (guild_id, session_date.isoformat())
                ) as cursor:
                    activities = await cursor.fetchall()
                    for activity in activities:
                        summary_data["activities"].append({
                            "reviewer_id": activity[0],
                            "action": activity[1],
                            "markers": activity[2],
                            "correct": activity[3],
                            "points": activity[4],
                            "penalty": activity[5],
                            "tier_change": f"{activity[6]} → {activity[7]}" if activity[6] != activity[7] else "—"
                        })

            await push_daily_summary_to_github(summary_data)
            logger.info(f"✅ Daily summary pushed to GitHub for {session_date.isoformat()}")
        except Exception as e:
            logger.warning(f"⚠️ Could not push daily summary to GitHub: {e}")

        # Final confirmation embed
        embed = discord.Embed(
            title="🔒 Reviewing Session Closed",
            description=f"**{session_date.strftime('%A, %B %d, %Y')}**",
            color=discord.Color.green()
        )
        embed.add_field(name="✅ Status", value="Closed", inline=True)
        embed.add_field(name="📊 Summary", value=f"{reviewer_count} reviewers • {total_markers} markers • {points_awarded} pts awarded", inline=False)
        embed.add_field(name="📤 GitHub Sync", value="Daily summary pushed to leaderboard", inline=False)
        embed.add_field(name="Next Session", value=f"`>newday` will default to {(session_date + timedelta(days=1)).isoformat()}", inline=False)

        await ctx.send(embed=embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="day_closed")

    # ==================== NEW REVIEW SYSTEM: >addpoints / >endday ====================

    @commands.command(name='addpoints')
    async def add_points(self, ctx):
        """
        Submit your reviewing work for today. (user-facing)
        Flow: markers reviewed → base pts/marker → confirm
        Admin verifies correct count at >endday. Stacking supported (run multiple times).
        """
        import time
        start_time = time.time()
        timeout_limit = 180

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        guild_id = ctx.guild.id
        user_id = ctx.author.id
        pool = await get_pool()

        # Find the open session for this guild (whatever date the admin opened it for)
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT session_date FROM daily_sessions WHERE guild_id = ? AND is_open = 1 ORDER BY session_date DESC LIMIT 1",
                (guild_id,)
            ) as cursor:
                session = await cursor.fetchone()

        if not session:
            await ctx.send("❌ No active reviewing session. Wait for an admin to run `>newday`.")
            return

        # Use the OPEN session's date for submission, not today's calendar date
        session_date = session[0]
        today = session_date if isinstance(session_date, str) else session_date.isoformat()

        # Check user is a registered reviewer
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT current_tier, current_multiplier, accuracy_percentage FROM reviewers WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                reviewer = await cursor.fetchone()

        if not reviewer:
            await ctx.send("❌ You are not registered as a Drop Map Reviewer.")
            return

        tier = reviewer[0] or 'Beginner'
        tier_mult = TIER_MULTIPLIERS.get(tier, 1.0)
        current_accuracy = reviewer[2] or 0.0

        # Snapshot current streaks (locked at submission time)
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT current_streak FROM accuracy_streaks WHERE reviewer_id = ?",
                (user_id,)
            ) as cursor:
                acc_row = await cursor.fetchone()
            async with db.execute(
                "SELECT current_streak_days FROM daily_streaks WHERE reviewer_id = ?",
                (user_id,)
            ) as cursor:
                daily_row = await cursor.fetchone()

        acc_streak_snapshot = acc_row[0] if acc_row else 0
        daily_streak_snapshot = daily_row[0] if daily_row else 0

        # Step 1: Markers reviewed
        embed = discord.Embed(
            title="📊 Add Points — Step 1/2",
            description="How many **markers** did you review?",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Enter a whole number (e.g. 10)")
        await ctx.send(embed=embed)

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=timeout_limit - (time.time() - start_time))
            markers_reviewed = int(msg.content.strip())
            if markers_reviewed <= 0:
                await ctx.send("❌ Must be greater than 0.")
                return
            if markers_reviewed > 500:
                await ctx.send("❌ Maximum 500 markers per submission. Split into multiple `>addpoints` calls if needed.")
                return
        except (ValueError, asyncio.TimeoutError):
            await ctx.send("❌ Invalid input or timed out.")
            return

        # Step 2: Base points per marker
        valid_pts_str = " / ".join(str(v) for v in VALID_BASE_POINTS)
        embed = discord.Embed(
            title="📊 Add Points — Step 2/2",
            description=f"What are the **base points per marker**?\nValid: **{valid_pts_str}**",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=timeout_limit - (time.time() - start_time))
            base_pts = float(msg.content.strip())
            if base_pts not in VALID_BASE_POINTS:
                await ctx.send(f"❌ Invalid. Must be one of: {valid_pts_str}")
                return
        except (ValueError, asyncio.TimeoutError):
            await ctx.send("❌ Invalid input or timed out.")
            return

        # Rodrigo bonus removed — kept at 1.0 for backward-compat with reviewers_temp schema
        rodrigo_mult = 1.0

        # Base formula points (all markers assumed correct)
        provisional_base_pts = round(markers_reviewed * base_pts * rodrigo_mult * tier_mult, 2)

        # Read previous unverified temp submissions for this user this session.
        # Used to build an accurate running provisional streak instead of always
        # snapshotting from the committed DB (which doesn't update until >endday).
        async with pool.acquire() as db:
            async with db.execute(
                """SELECT COALESCE(SUM(markers_reviewed), 0), COUNT(*)
                   FROM reviewers_temp
                   WHERE user_id = ? AND submission_date = ? AND verified = 0""",
                (user_id, today)
            ) as cursor:
                prev_temp = await cursor.fetchone()

        prev_markers_this_session = prev_temp[0] if prev_temp else 0
        has_prior_submission_this_session = (prev_temp[1] > 0) if prev_temp else False

        # Provisional acc streak: committed base + all prior session markers + this submission
        running_acc_base = acc_streak_snapshot + prev_markers_this_session
        provisional_acc_streak = running_acc_base + markers_reviewed

        # Daily streak: only ever +1 from committed value regardless of stacked submissions
        provisional_daily_streak = daily_streak_snapshot + 1

        # Provisional milestone bonuses — display only, temp gets cleared at >closeday
        # Acc: check which milestones land between running base and new provisional streak
        prov_acc_milestone = sum(
            bonus for milestone, bonus in ACCURACY_MILESTONES.items()
            if running_acc_base < milestone <= provisional_acc_streak
        )
        # Daily: only estimate milestone on first submission — subsequent ones don't add +1
        prov_daily_milestone = 0 if has_prior_submission_this_session else DAILY_MILESTONES.get(provisional_daily_streak, 0)
        provisional_pts = round(provisional_base_pts + prov_acc_milestone + prov_daily_milestone, 2)

        # Confirmation preview
        embed = discord.Embed(
            title="📊 Confirm Submission",
            color=discord.Color.gold()
        )
        embed.add_field(name="Markers Reviewed", value=str(markers_reviewed), inline=True)
        embed.add_field(name="Base Pts/Marker", value=str(base_pts), inline=True)
        embed.add_field(name="Your Tier", value=f"{tier} ({tier_mult}x)", inline=True)
        embed.add_field(
            name="Provisional Points",
            value=f"**{provisional_pts} pts**\n`{markers_reviewed} × {base_pts} × {tier_mult} = {provisional_base_pts}`"
                  + (f"\n🔥 Acc milestone: +{prov_acc_milestone} pts" if prov_acc_milestone else "")
                  + (f"\n📅 Daily milestone: +{prov_daily_milestone} pts" if prov_daily_milestone else ""),
            inline=False
        )
        embed.set_footer(text="Type 'confirm' to submit or 'cancel' to abort")
        await ctx.send(embed=embed)

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=timeout_limit - (time.time() - start_time))
            if msg.content.strip().lower() not in ('confirm', 'yes', 'y', 'ok'):
                await ctx.send("❌ Submission cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("❌ Timed out.")
            return

        # Write to reviewers_temp — provisional_points includes milestone estimates
        async with pool.acquire() as db:
            await db.execute(
                """INSERT INTO reviewers_temp
                   (user_id, username, submission_date, markers_reviewed, base_points,
                    rodrigo_multiplier, provisional_correct, provisional_points,
                    provisional_accuracy_streak, provisional_daily_streak,
                    tier_at_submission, tier_multiplier_at_submission,
                    accuracy_streak_at_submission, daily_streak_at_submission)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, ctx.author.display_name, today,
                 markers_reviewed, base_pts, rodrigo_mult,
                 markers_reviewed, provisional_pts,
                 provisional_acc_streak, provisional_daily_streak,
                 tier, tier_mult,
                 acc_streak_snapshot, daily_streak_snapshot)
            )
            await db.commit()

        # Project tier_after assuming all claimed markers are correct (matches the
        # provisional_points / provisional_acc_streak optimism model).
        total_claimed_this_session = prev_markers_this_session + markers_reviewed
        slots_from_history = max(0, 30 - total_claimed_this_session)
        existing_correct = 0
        existing_total = 0
        if slots_from_history > 0:
            async with pool.acquire() as db:
                async with db.execute("""
                    SELECT correct FROM (
                        SELECT correct, timestamp, id FROM reviewer_markers WHERE reviewer_id = ?
                        UNION ALL
                        SELECT correct, timestamp, id FROM ghost_markers WHERE reviewer_id = ?
                    ) ORDER BY timestamp DESC, id DESC LIMIT ?
                """, (user_id, user_id, slots_from_history)) as cursor:
                    rows = await cursor.fetchall()
            existing_correct = sum(1 for r in rows if r[0])
            existing_total = len(rows)

        proj_window_total = existing_total + total_claimed_this_session
        proj_window_correct = existing_correct + total_claimed_this_session
        proj_accuracy = (proj_window_correct / proj_window_total * 100) if proj_window_total > 0 else 0.0

        if proj_window_total < 5:
            projected_tier = 'Beginner'
        elif proj_accuracy >= 96.67:
            projected_tier = 'Master'
        elif proj_accuracy >= 90:
            projected_tier = 'Expert'
        elif proj_accuracy >= 83.33:
            projected_tier = 'Advanced'
        elif proj_accuracy >= 76.67:
            projected_tier = 'Intermediate'
        else:
            projected_tier = 'Beginner'

        await log_daily_activity(
            guild_id, user_id, today,
            {
                'action_type': 'submission',
                'total_markers': markers_reviewed,
                'correct_markers': markers_reviewed,
                'points_awarded': provisional_pts,
                'penalty_deduction': 0,
                'accuracy_before': current_accuracy,
                'accuracy_after': proj_accuracy,
                'tier_before': tier,
                'tier_after': projected_tier,
                'daily_streak_bonus': prov_daily_milestone,
                'accuracy_streak_bonus': prov_acc_milestone,
                'daily_streak_value': provisional_daily_streak,
                'accuracy_streak_value': provisional_acc_streak,
            }
        )

        # Evaluate today's challenges — updates challenge_completions for this reviewer.
        challenge_results = []
        try:
            from database import evaluate_challenges_for_reviewer
            challenge_results = await evaluate_challenges_for_reviewer(user_id, today)
        except Exception as e:
            logger.error(f"❌ Challenge evaluation failed for user {user_id}: {e}")

        # Build a spicy hype message based on milestones hit
        milestone_hype = ""
        if prov_acc_milestone and prov_daily_milestone:
            milestone_hype = "\n\n💥 **DOUBLE MILESTONE INCOMING!** 🚀"
        elif prov_acc_milestone:
            milestone_hype = "\n\n🔥 **ACCURACY STREAK MILESTONE LOCKED IN!**"
        elif prov_daily_milestone:
            milestone_hype = "\n\n🌟 **DAILY MILESTONE LOCKED IN!**"

        leaderboard_url = "https://wavedropmaps.pages.dev/reviewing_leaderboard_final.html"

        embed = discord.Embed(
            title="🎯 Submission Logged — Nice Work!",
            description=f"You're crushing it, **{ctx.author.display_name}**! Your provisional points are now on the board.{milestone_hype}",
            color=discord.Color.from_rgb(0, 240, 255)
        )
        embed.add_field(name="📝 Markers", value=f"**{markers_reviewed}**", inline=True)
        embed.add_field(name="💰 Provisional Points", value=f"**{provisional_pts} pts**", inline=True)
        embed.add_field(name="🏆 Rank", value=f"**{tier}** ({tier_mult}x)", inline=True)
        if prov_acc_milestone:
            embed.add_field(name="🔥 Accuracy Streak Milestone (est.)", value=f"**+{prov_acc_milestone} pts**", inline=True)
        if prov_daily_milestone:
            embed.add_field(name="📅 Daily Milestone (est.)", value=f"**+{prov_daily_milestone} pts**", inline=True)
        embed.add_field(
            name="📊 Live Leaderboard",
            value=f"[**Click here to see where you rank →**]({leaderboard_url})",
            inline=False
        )
        embed.add_field(
            name="⏳ Status",
            value="**Awaiting admin verification** — points finalize when the session closes.",
            inline=False
        )
        embed.set_footer(text="Keep grinding — every marker counts 🚀")
        await ctx.send(embed=embed)

        try:
            dm_embed = discord.Embed(
                title="🎯 Submission Locked In!",
                description=f"Heyy **{ctx.author.display_name}** — your submission for **{today}** is officially recorded.{milestone_hype}",
                color=discord.Color.from_rgb(0, 240, 255)
            )
            dm_embed.add_field(name="📝 Markers", value=f"**{markers_reviewed}**", inline=True)
            dm_embed.add_field(name="⚡ Base Pts", value=f"**{base_pts}**/marker", inline=True)
            dm_embed.add_field(name="🏆 Rank", value=f"**{tier}** ({tier_mult}x)", inline=True)
            dm_embed.add_field(name="💰 Provisional Points", value=f"**{provisional_pts} pts**", inline=True)
            if prov_acc_milestone:
                dm_embed.add_field(name="🔥 Accuracy Streak Milestone (est.)", value=f"**+{prov_acc_milestone} pts**", inline=True)
            if prov_daily_milestone:
                dm_embed.add_field(name="📅 Daily Milestone (est.)", value=f"**+{prov_daily_milestone} pts**", inline=True)
            dm_embed.add_field(
                name="📊 Check Your Rank",
                value=f"[**Live Leaderboard →**]({leaderboard_url})",
                inline=False
            )
            dm_embed.add_field(
                name="⏳ Final Confirmation",
                value="Points lock in officially when the session closes. Until then, keep stacking! 🔥",
                inline=False
            )
            dm_embed.set_footer(text="You're a legend — thanks for keeping the maps clean 🌊")
            await ctx.author.send(embed=dm_embed)
        except Exception:
            pass

        # Challenge progress notifications — ONE-WINNER MODEL:
        # - was_new_completion: this user just WON the race (claimed the challenge)
        # - race_lost: hit the target but someone else claimed it first
        # - in_progress: still under target, race still open
        if challenge_results:
            new_wins = [r for r in challenge_results if r.get('was_new_completion')]
            race_losses = [r for r in challenge_results if r.get('race_lost')]
            in_progress = [r for r in challenge_results if not r.get('completed') and not r.get('race_lost') and r.get('current', 0) > 0]

            # Public announcement + winner DM for fresh race-wins
            for r in new_wins:
                tier_color = (discord.Color.from_rgb(0, 255, 136) if r['tier'] == 'easy'
                              else discord.Color.from_rgb(0, 240, 255) if r['tier'] == 'medium'
                              else discord.Color.from_rgb(255, 0, 255))
                announce = discord.Embed(
                    title=f"🏆  CHALLENGE CLAIMED — {r['name']}",
                    description=(
                        f"**{ctx.author.display_name}** WON the race for the **{r['tier'].upper()}** challenge!\n\n"
                        f"_{r['description']}_\n\n"
                        f"💰 **+{r['reward']} pts** locking in once verified by admin at the end of the day · "
                        f"🚫 **No one else can claim this one today.**"
                    ),
                    color=tier_color
                )
                announce.set_footer(text="Live progress on the leaderboard 🚀")
                await ctx.send(embed=announce)
                try:
                    dm = discord.Embed(
                        title=f"🏆 Challenge WON — {r['name']}",
                        description=(
                            f"You **claimed** today's **{r['tier'].upper()}** challenge — first to the line!\n\n"
                            f"_{r['description']}_\n\n"
                            f"💰 **+{r['reward']} pts** pending verification by admin at the end of the day\n"
                            f"🚫 Locked in — no other reviewer can take this one today."
                        ),
                        color=tier_color
                    )
                    await ctx.author.send(embed=dm)
                except Exception:
                    pass

            # Race-lost DM — they hit the target but came second
            for r in race_losses:
                try:
                    lost_dm = discord.Embed(
                        title=f"😔 Just Missed — {r['name']}",
                        description=(
                            f"You hit the target for **{r['name']}** ({r['current']}/{r['target']}) — "
                            f"but another reviewer claimed it first.\n\n"
                            f"_The race is over for this one today. Other challenges might still be open!_"
                        ),
                        color=discord.Color.from_rgb(120, 120, 120)
                    )
                    await ctx.author.send(embed=lost_dm)
                except Exception:
                    pass

            # Progress DM — still in the race
            if in_progress and not new_wins:
                progress_lines = "\n".join(
                    f"• **{r['name']}**: `{r['current']}/{r['target']}`" for r in in_progress[:3]
                )
                try:
                    prog_dm = discord.Embed(
                        title="🎯 Challenge Progress",
                        description=(
                            f"You're racing toward today's challenges:\n\n{progress_lines}\n\n"
                            f"⚡ **First to the finish wins — no second place.**"
                        ),
                        color=discord.Color.from_rgb(0, 240, 255)
                    )
                    prog_dm.set_footer(text="Keep stacking — beat the others to the line 🔥")
                    await ctx.author.send(embed=prog_dm)
                except Exception:
                    pass

        await auto_update_drop_map_leaderboard(self.bot, triggered_by="addpoints_submitted")

        # Push daily summary to show provisional activity
        await push_daily_summary_for_session(ctx.guild.id, today)

    @commands.command(name='preview')
    @commands.has_permissions(administrator=True)
    async def preview(self, ctx):
        """Admin: preview today's pending submissions and projected payout before running >endday."""
        guild_id = ctx.guild.id
        pool = await get_pool()
        tier_emoji_map = {'Master': '👑', 'Expert': '⭐', 'Advanced': '📈', 'Intermediate': '🎯', 'Beginner': '🌱'}

        async with pool.acquire() as db:
            async with db.execute(
                "SELECT session_date FROM daily_sessions WHERE guild_id = ? AND is_open = 1 ORDER BY session_date DESC LIMIT 1",
                (guild_id,)
            ) as cursor:
                session = await cursor.fetchone()

        if not session:
            await ctx.send("❌ No open reviewing session. Run `>newday` first.")
            return

        session_date = session[0]
        today = session_date if isinstance(session_date, str) else session_date.isoformat()

        async with pool.acquire() as db:
            async with db.execute(
                """SELECT user_id, username, markers_reviewed, base_points, rodrigo_multiplier,
                          tier_at_submission, provisional_points
                   FROM reviewers_temp
                   WHERE submission_date = ? AND verified = 0
                   ORDER BY user_id, submission_timestamp ASC""",
                (today,)
            ) as cursor:
                pending = await cursor.fetchall()

            async with db.execute(
                """SELECT COUNT(*), COALESCE(SUM(actual_correct), 0), COALESCE(SUM(markers_reviewed), 0), COALESCE(SUM(final_points), 0)
                   FROM reviewers_temp WHERE submission_date = ? AND verified = 1""",
                (today,)
            ) as cursor:
                verified_row = await cursor.fetchone()

        verified_count = verified_row[0]
        verified_correct = verified_row[1]
        verified_markers = verified_row[2]
        verified_points = verified_row[3]

        if not pending and verified_count == 0:
            await ctx.send(f"📭 No submissions yet for session **{today}**.")
            return

        by_user = {}
        for row in pending:
            by_user.setdefault(row[0], []).append(row)

        embed = discord.Embed(
            title=f"📋 >endday Preview — {today}",
            description=(
                f"**Pending:** {len(pending)} submission(s) across {len(by_user)} reviewer(s)\n"
                f"**Verified so far:** {verified_count} submission(s)"
            ),
            color=discord.Color.gold()
        )

        if pending:
            grand_markers = 0
            grand_provisional = 0.0
            lines = []
            for uid, subs in by_user.items():
                username = subs[0][1]
                user_markers = sum(s[2] for s in subs)
                user_prov = sum(s[6] for s in subs)
                tier = subs[0][5]
                te = tier_emoji_map.get(tier, '📊')
                grand_markers += user_markers
                grand_provisional += user_prov
                lines.append(
                    f"{te} **{username}** ({tier}) — `{len(subs)}` sub · `{user_markers}` markers · `{user_prov:.0f}` pts"
                )

            embed.add_field(
                name="🟡 Pending Reviewers",
                value="\n".join(lines),
                inline=False
            )
            embed.add_field(
                name="📊 Projected Day Totals (all verified at claimed)",
                value=(
                    f"**Markers:** `{grand_markers + verified_markers}` "
                    f"({verified_markers} verified + {grand_markers} claimed)\n"
                    f"**Points:** `{grand_provisional + verified_points:.0f}` "
                    f"({verified_points:.0f} locked in + {grand_provisional:.0f} pending)"
                ),
                inline=False
            )

        if verified_count > 0:
            embed.add_field(
                name="✅ Already Verified",
                value=f"`{verified_count}` submission(s) · `{verified_correct}/{verified_markers}` markers · `{verified_points:.0f}` pts awarded",
                inline=False
            )

        embed.set_footer(text="Read-only · Run >endday to verify pending submissions")
        await ctx.send(embed=embed)

    @commands.command(name='endday')
    @commands.has_permissions(administrator=True)
    async def end_day(self, ctx):
        """
        Show numbered list of pending submissions → admin picks by number → verify one at a time.
        Can run multiple times — picks up from wherever you left off.
        Type 'all' to verify all remaining, 'done' to pause and exit.
        """
        import time
        import uuid
        start_time = time.time()
        timeout_limit = 600  # 10 minutes per session

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        guild_id = ctx.guild.id
        pool = await get_pool()
        tier_emoji_map = {'Master': '👑', 'Expert': '⭐', 'Advanced': '📈', 'Intermediate': '🎯', 'Beginner': '🌱'}

        # Find open session
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT session_date FROM daily_sessions WHERE guild_id = ? AND is_open = 1 ORDER BY session_date DESC LIMIT 1",
                (guild_id,)
            ) as cursor:
                session = await cursor.fetchone()

        if not session:
            await ctx.send("❌ No open reviewing session. Run `>newday` first.")
            return

        session_date = session[0]
        today = session_date if isinstance(session_date, str) else session_date.isoformat()

        async def fetch_pending():
            async with pool.acquire() as db:
                async with db.execute(
                    """SELECT id, user_id, username, markers_reviewed, base_points, rodrigo_multiplier,
                              tier_at_submission, tier_multiplier_at_submission, provisional_points
                       FROM reviewers_temp
                       WHERE submission_date = ? AND verified = 0
                       ORDER BY submission_timestamp ASC""",
                    (today,)
                ) as cursor:
                    return await cursor.fetchall()

        async def fetch_verified_count():
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM reviewers_temp WHERE submission_date = ? AND verified = 1",
                    (today,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else 0

        async def show_submission_list(rows, verified_count):
            # Group by user_id, preserving first-appearance order
            by_reviewer = {}
            for row in rows:
                uid = row[1]
                by_reviewer.setdefault(uid, []).append(row)
            reviewers_list = list(by_reviewer.items())  # [(uid, [sub_rows...]), ...]

            lines = []
            for i, (uid, subs) in enumerate(reviewers_list, 1):
                username = subs[0][2]
                total_markers = sum(s[3] for s in subs)
                total_prov_pts = sum(s[8] for s in subs)
                sub_count = len(subs)
                sub_lines = []
                for s in subs:
                    _id, _uid, _uname, m, bp, _rm, tr, tm, pp = s
                    te = tier_emoji_map.get(tr, "📊")
                    sub_lines.append(
                        f"   · `{m}` markers @ `{bp}pts` · {te} {tr} → `{pp}` pts"
                    )
                plural = "s" if sub_count > 1 else ""
                lines.append(
                    f"**{i}. {username}** — {sub_count} sub{plural} · "
                    f"`{total_markers}` total markers · `{total_prov_pts}` prov pts\n"
                    + "\n".join(sub_lines)
                )

            embed = discord.Embed(
                title=f"📋 End Day — {today}",
                description="\n\n".join(lines) if lines else "*(none pending)*",
                color=discord.Color.blue()
            )
            embed.set_footer(
                text=f"✅ {verified_count} verified · ⏳ {len(rows)} pending across {len(reviewers_list)} reviewer(s)  |  number = verify · 'remove <n>' = delete a submission · 'all' · 'done'"
            )
            await ctx.send(embed=embed)
            return reviewers_list

        async def verify_one_sub(sub_row):
            """Verify ONE submission. No streak math — that's deferred to settle_streak_for_reviewer.
            Daily-streak prompt happens once per reviewer in verify_reviewer_subs after all subs are done.

            Returns (actual_correct, markers, final_pts, tier_after, tier_em_after_mult) on success,
            or None if the verification was aborted/timed out before commit.
            """
            sub_id, user_id, username, markers, base_pts, rodrigo_mult, tier, tier_mult, provisional_pts = sub_row

            # Check if tier has changed since submission
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT current_tier, current_multiplier FROM reviewers WHERE user_id = ?",
                    (user_id,)
                ) as cursor:
                    current = await cursor.fetchone()
            current_tier = current[0] if current else tier
            current_mult = current[1] if current else tier_mult
            tier_changed = current_tier != tier

            embed = discord.Embed(
                title=f"📝 Verify: {username}",
                color=discord.Color.orange()
            )
            embed.add_field(name="Claimed Markers", value=str(markers), inline=True)
            embed.add_field(name="Base Pts", value=f"{base_pts}/marker", inline=True)
            tier_display = f"{tier_emoji_map.get(tier, '📊')} {tier} ({tier_mult}x)"
            if tier_changed:
                tier_display += f" → {tier_emoji_map.get(current_tier, '📊')} {current_tier} ({current_mult}x) ⚠️"
            embed.add_field(name="Tier", value=tier_display, inline=True)
            embed.add_field(name="Provisional", value=f"{provisional_pts} pts", inline=True)
            embed.set_footer(text=f"How many correct? (0–{markers})  |  'skip' = all correct  |  'cancel' = discard submission")
            await ctx.send(embed=embed)

            cancelled = False
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=timeout_limit - (time.time() - start_time))
                content = msg.content.strip().lower()
                if content == 'cancel':
                    cancelled = True
                    actual_correct = 0
                elif content == 'skip':
                    actual_correct = markers
                else:
                    actual_correct = int(content)
                    if actual_correct < 0 or actual_correct > markers:
                        await ctx.send(f"⚠️ Out of range (0–{markers}). Using claimed count.")
                        actual_correct = markers
            except (ValueError, asyncio.TimeoutError):
                await ctx.send(f"⚠️ Timed out or invalid. Using claimed count ({markers}).")
                actual_correct = markers

            if cancelled:
                # Discard the submission entirely — no points, no marker rows, no accuracy
                # impact. Row is deleted so it doesn't pollute >closeday day totals or the
                # leaderboard's provisional overlay (both query reviewers_temp directly).
                async with pool.acquire() as db:
                    await db.execute(
                        "DELETE FROM reviewers_temp WHERE id = ?",
                        (sub_id,)
                    )
                    await db.commit()
                logger.info(f"[endday] CANCELLED submission id={sub_id} for {username} ({user_id}) — {markers} markers discarded by admin {ctx.author.id}")
                cancel_embed = discord.Embed(
                    description=f"❌ **Cancelled** — {markers}-marker submission discarded. No points awarded, no accuracy impact.",
                    color=discord.Color.dark_grey()
                )
                await ctx.send(embed=cancel_embed)
                return (0, 0, 0.0, current_tier, current_mult)

            final_pts = round(actual_correct * base_pts * rodrigo_mult * tier_mult, 2)

            # Commit points + markers to main table
            async with pool.acquire() as db:
                await db.execute(
                    """UPDATE reviewers
                       SET total_points = total_points + ?,
                           points_from_reviews = points_from_reviews + ?,
                           total_markers_reviewed = total_markers_reviewed + ?
                       WHERE user_id = ?""",
                    (final_pts, final_pts, markers, user_id)
                )
                await db.commit()

            # Insert markers into rolling window so tier recalc sees fresh data.
            # First `actual_correct` markers are correct, remainder are wrong.
            batch_id = f"endday_{today}_{str(uuid.uuid4())[:8]}"
            logger.info(f"[endday] Inserting {markers} markers for {username} ({user_id}), batch={batch_id}, correct={actual_correct}/{markers}")
            async with pool.acquire() as db:
                for i in range(markers):
                    is_correct = i < actual_correct
                    await db.execute(
                        """INSERT INTO reviewer_markers (reviewer_id, map_id, marker_number, correct, claimed_seconds)
                           VALUES (?, ?, ?, ?, ?)""",
                        (user_id, batch_id, i + 1, is_correct, 60)
                    )
                await db.commit()
            logger.info(f"[endday] Committed {markers} marker rows for {username} ({user_id})")

            # Auto-apply marker_mistake penalty for any wrong markers — one penalty per wrong marker
            mistake_penalty = 0
            if actual_correct < markers:
                wrong_count = markers - actual_correct
                for _ in range(wrong_count):
                    await apply_penalty(
                        user_id, 'marker_mistake',
                        f"{wrong_count} incorrect marker(s) detected during >endday verification"
                    )
                mistake_penalty = 20 * wrong_count
                logger.info(f"[endday] Auto-applied marker_mistake penalty (-{mistake_penalty} pts) for {username} ({user_id}) — {wrong_count} wrong marker(s)")

            # Recalculate tier based on updated last-30 window
            tier_after, mult_after, acc_after = await update_reviewer_tier(user_id)

            # Read CURRENT (pre-settle) streak values just so the audit columns aren't null.
            # The final correct values get patched after settle_streak_for_reviewer runs.
            async with pool.acquire() as db:
                async with db.execute("SELECT current_streak FROM accuracy_streaks WHERE reviewer_id = ?", (user_id,)) as cursor:
                    acc_row = await cursor.fetchone()
                async with db.execute("SELECT current_streak_days FROM daily_streaks WHERE reviewer_id = ?", (user_id,)) as cursor:
                    daily_row = await cursor.fetchone()
            acc_streak_pre = acc_row[0] if acc_row else 0
            daily_streak_pre = daily_row[0] if daily_row else 0

            # Mark TEMP row verified (provisional streak values; patched after settle)
            async with pool.acquire() as db:
                await db.execute(
                    """UPDATE reviewers_temp SET
                       verified = 1, verified_at = CURRENT_TIMESTAMP, verified_by_admin_id = ?,
                       actual_correct = ?, final_points = ?,
                       accuracy_streak_after = ?, daily_streak_after = ?,
                       milestone_bonus_total = ?
                       WHERE id = ?""",
                    (ctx.author.id, actual_correct, final_pts,
                     acc_streak_pre, daily_streak_pre,
                     0,
                     sub_id)
                )
                await db.commit()

            # Brief per-sub confirmation — full recap comes after the reviewer is fully done
            result_desc = f"✅ Verified — **{actual_correct}/{markers}**, +{final_pts:.2f} pts"
            if mistake_penalty:
                result_desc += f"\n⚠️ **-{mistake_penalty} pts** (marker mistake penalty auto-applied)"
            result_embed = discord.Embed(
                description=result_desc,
                color=discord.Color.green()
            )
            await ctx.send(embed=result_embed)

            return (actual_correct, markers, final_pts, tier_after, mult_after)

        async def reset_reviewer_day_entries(user_id, today_str):
            """Undo everything verify_one_sub committed for this reviewer today, so the admin
            can re-enter the correct-marker counts. Only touches TODAY's endday writes —
            historical markers, streaks, and the reviewer's account stay intact.

            Safe to call at the milestone-confirm step (before settle_streak_for_reviewer runs).
            Returns (subs_reset, total_pts_rolled_back, total_markers_rolled_back).
            """
            async with pool.acquire() as db:
                async with db.execute(
                    """SELECT id, markers_reviewed, COALESCE(final_points, 0)
                       FROM reviewers_temp
                       WHERE user_id = ? AND submission_date = ? AND verified = 1""",
                    (user_id, today_str)
                ) as cursor:
                    verified_rows = await cursor.fetchall()

                if not verified_rows:
                    return (0, 0.0, 0)

                sub_ids = [r[0] for r in verified_rows]
                total_markers = sum(int(r[1] or 0) for r in verified_rows)
                total_pts = sum(float(r[2] or 0) for r in verified_rows)

                await db.execute(
                    """UPDATE reviewers
                       SET total_points = MAX(0, total_points - ?),
                           points_from_reviews = MAX(0, points_from_reviews - ?),
                           total_markers_reviewed = MAX(0, total_markers_reviewed - ?)
                       WHERE user_id = ?""",
                    (total_pts, total_pts, total_markers, user_id)
                )

                await db.execute(
                    "DELETE FROM reviewer_markers WHERE reviewer_id = ? AND map_id LIKE ?",
                    (user_id, f"endday_{today_str}_%")
                )

                placeholders = ",".join("?" for _ in sub_ids)
                await db.execute(
                    f"""UPDATE reviewers_temp SET
                        verified = 0, verified_at = NULL, verified_by_admin_id = NULL,
                        actual_correct = NULL, final_points = NULL,
                        accuracy_streak_after = NULL, daily_streak_after = NULL,
                        milestone_bonus_total = 0
                        WHERE id IN ({placeholders})""",
                    sub_ids
                )
                await db.commit()

            await update_reviewer_tier(user_id)
            return (len(sub_ids), total_pts, total_markers)

        async def settle_streak_for_reviewer(uid, today_str, grant_daily_streak, total_correct_day, total_markers_day):
            """Settle streaks for the specific markers verified in this batch."""
            acc_milestone = 0
            daily_milestone = 0
            
            if total_correct_day < total_markers_day:
                # Any wrong → reset accuracy streak to 0, clear milestones
                async with pool.acquire() as db:
                    await db.execute(
                        """UPDATE accuracy_streaks
                           SET current_streak = 0,
                               milestones_hit_this_session = '[]',
                               last_mistake_timestamp = ?
                           WHERE reviewer_id = ?""",
                        (datetime.now(timezone.utc).isoformat(), uid)
                    )
                    await db.commit()
            else:
                # All correct → loop bulk increments
                for _ in range(total_correct_day):
                    bonus = await update_accuracy_streak(uid, True)
                    acc_milestone += bonus

            if grant_daily_streak:
                daily_milestone = await update_daily_streak(uid, today_str)

            # Mark settled
            async with pool.acquire() as db:
                await db.execute(
                    "UPDATE reviewers SET last_streak_settle_date = ? WHERE user_id = ?",
                    (today_str, uid)
                )
                await db.commit()

            return (acc_milestone, daily_milestone, total_markers_day, total_correct_day)

        async def preview_milestones_for_reviewer(uid, total_correct, total_markers, today_str, grant_daily_streak):
            """Preview milestone bonuses WITHOUT applying — mirrors update_accuracy_streak + update_daily_streak.

            Pure read; no writes. Used to show admin what WILL fire before they ✅ tick / ❌ skip.
            """
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT current_streak, milestones_hit_this_session FROM accuracy_streaks WHERE reviewer_id = ?",
                    (uid,)
                ) as cursor:
                    arow = await cursor.fetchone()
                async with db.execute(
                    "SELECT current_streak_days, streak_bonus_this_day, last_review_date FROM daily_streaks WHERE reviewer_id = ?",
                    (uid,)
                ) as cursor:
                    drow = await cursor.fetchone()

            current_acc = (arow[0] if arow else 0) or 0
            try:
                hit_session = json.loads(arow[1] or '[]') if arow else []
            except Exception:
                hit_session = []
            current_daily = (drow[0] if drow else 0) or 0
            daily_bonus_today = (drow[1] if drow else 0) or 0
            daily_last_review = drow[2] if drow else None

            # Acc milestones only fire on a perfect day (mirrors settle_streak_for_reviewer)
            acc_fired = []
            acc_total = 0
            will_reset = (total_correct < total_markers)
            projected_acc = 0 if will_reset else current_acc + total_correct

            if not will_reset and total_markers > 0:
                sim_hit = list(hit_session)
                for i in range(total_correct):
                    new_streak = current_acc + i + 1
                    if new_streak in ACCURACY_MILESTONES and new_streak not in sim_hit:
                        bonus = ACCURACY_MILESTONES[new_streak]
                        acc_total += bonus
                        acc_fired.append((new_streak, bonus))
                        sim_hit.append(new_streak)

            # Daily milestone fires once per session, only if grant_daily_streak
            daily_fired = []
            daily_total = 0
            same_session = (daily_last_review == today_str)
            if grant_daily_streak and not same_session:
                projected_daily = current_daily + 1
                if projected_daily in DAILY_MILESTONES and daily_bonus_today == 0:
                    bonus = DAILY_MILESTONES[projected_daily]
                    daily_total = bonus
                    daily_fired.append((projected_daily, bonus))
            else:
                projected_daily = current_daily

            return {
                'acc_total': acc_total,
                'acc_fired': acc_fired,
                'acc_will_reset': will_reset,
                'acc_current': current_acc,
                'acc_projected': projected_acc,
                'daily_total': daily_total,
                'daily_fired': daily_fired,
                'daily_current': current_daily,
                'daily_projected': projected_daily,
                'daily_same_session': same_session,
            }

        async def verify_reviewer_subs(uid, subs, daily_streak_confirmed):
            """Verify all of a reviewer's pending submissions, then settle streaks once based on day totals."""
            total_correct_day = 0
            total_markers_day = 0
            total_final_pts = 0.0
            username = subs[0][2]
            # Pre-settle tier (for tier-promotion comparison in DM hype)
            tier_before = subs[0][6]

            for sub_row in subs:
                result = await verify_one_sub(sub_row)
                if not result:  # timeout/error returned early
                    return  # leave remaining subs pending
                actual_correct, markers, final_pts, _tier_after, _mult_after = result
                total_correct_day += actual_correct
                total_markers_day += markers
                total_final_pts += final_pts

            # All subs for this reviewer are now verified — ask the daily-streak question
            # once, AFTER the full day is verified (so admin sees the day totals first).
            if uid in daily_streak_confirmed:
                grant_daily_streak = daily_streak_confirmed[uid]
            else:
                day_accuracy_pct = (total_correct_day / total_markers_day * 100) if total_markers_day > 0 else 0
                prompt_embed = discord.Embed(
                    title=f"📅 Daily Streak — {username}",
                    description=(
                        f"All submissions verified for **{username}** today.\n"
                        f"**Day Totals:** {total_correct_day}/{total_markers_day} correct ({day_accuracy_pct:.1f}%) · "
                        f"+{total_final_pts:.2f} base pts\n\n"
                        f"Did they complete a valid daily streak for this session? (`yes` / `no`)"
                    ),
                    color=discord.Color.blue()
                )
                await ctx.send(embed=prompt_embed)
                try:
                    streak_msg = await self.bot.wait_for(
                        'message', check=check,
                        timeout=timeout_limit - (time.time() - start_time)
                    )
                    grant_daily_streak = streak_msg.content.strip().lower() in ('yes', 'y')
                except asyncio.TimeoutError:
                    await ctx.send("⚠️ Timed out — daily streak not awarded.")
                    grant_daily_streak = False
                daily_streak_confirmed[uid] = grant_daily_streak

            # ── PREVIEW milestones BEFORE applying them ──
            # Review pts are already locked (committed in verify_one_sub). The breakdown below
            # is ONLY for the milestone bonus — admin can ✅ award or ❌ skip them independently.
            preview = await preview_milestones_for_reviewer(
                uid, total_correct_day, total_markers_day, today, grant_daily_streak
            )
            preview_total = preview['acc_total'] + preview['daily_total']

            breakdown_embed = discord.Embed(
                title=f"📋 Milestone Breakdown — {username}",
                description=(
                    f"**Day Totals:** {total_correct_day}/{total_markers_day} correct\n"
                    f"**Review Points (already locked):** `+{total_final_pts:.2f} pts`\n\n"
                    f"_The milestone bonus below is **separate** from the review points above._"
                ),
                color=discord.Color.blue()
            )

            acc_lines = []
            if preview['acc_will_reset']:
                acc_lines.append(f"❌ Streak resets ({preview['acc_current']} → 0)")
            else:
                acc_lines.append(f"📈 Streak: {preview['acc_current']} → **{preview['acc_projected']}** perfect markers")
                if preview['acc_fired']:
                    for new_streak, bonus in preview['acc_fired']:
                        acc_lines.append(f"🔥 Milestone @ {new_streak}: **+{bonus} pts**")
                else:
                    acc_lines.append("_(no milestone hit)_")
            breakdown_embed.add_field(
                name=f"🔥 Accuracy Bonus: +{preview['acc_total']} pts",
                value="\n".join(acc_lines),
                inline=False
            )

            daily_lines = []
            if not grant_daily_streak:
                daily_lines.append("⏭️ Daily streak NOT awarded (admin chose 'no')")
            elif preview['daily_same_session']:
                daily_lines.append(f"ℹ️ Already counted this session ({preview['daily_current']} days)")
            else:
                daily_lines.append(f"📅 Streak: {preview['daily_current']} → **{preview['daily_projected']}** days")
                if preview['daily_fired']:
                    for new_streak, bonus in preview['daily_fired']:
                        daily_lines.append(f"🎉 Milestone @ day {new_streak}: **+{bonus} pts**")
                else:
                    daily_lines.append("_(no milestone hit)_")
            breakdown_embed.add_field(
                name=f"📅 Daily Bonus: +{preview['daily_total']} pts",
                value="\n".join(daily_lines),
                inline=False
            )

            confirm_value_lines = []
            if preview_total > 0:
                confirm_value_lines.append(f"**React ✅** to confirm & award these milestones.")
            else:
                confirm_value_lines.append(f"**React ✅** to confirm the day.")
            confirm_value_lines.append(
                f"**React ❌** if you mis-typed the correct-marker counts for **{username}** — "
                f"their day will be rolled back so you can re-enter the numbers."
            )
            breakdown_embed.add_field(
                name=f"💰 Milestone Bonus Total: +{preview_total} pts",
                value="\n".join(confirm_value_lines),
                inline=False
            )
            breakdown_embed.set_footer(text="60s timeout — defaults to ✅ confirm.")

            confirm_msg = await ctx.send(embed=breakdown_embed)
            await confirm_msg.add_reaction('✅')
            await confirm_msg.add_reaction('❌')

            def reaction_check(reaction, user):
                return (user == ctx.author
                        and str(reaction.emoji) in ['✅', '❌']
                        and reaction.message.id == confirm_msg.id)

            try:
                reaction, _ = await self.bot.wait_for('reaction_add', check=reaction_check, timeout=60)
                admin_confirmed = (str(reaction.emoji) == '✅')
            except asyncio.TimeoutError:
                await ctx.send("⏱️ No tick — defaulting to ✅ confirm.")
                admin_confirmed = True

            # ❌ pressed → roll back today's endday writes for this reviewer so the admin
            # can re-enter the correct-marker counts. Streaks aren't touched (not settled yet).
            if not admin_confirmed:
                subs_reset, pts_rolled, markers_rolled = await reset_reviewer_day_entries(uid, today)
                daily_streak_confirmed.pop(uid, None)
                reset_embed = discord.Embed(
                    title=f"🔁 {username} — Day Reset",
                    description=(
                        f"Rolled back **{subs_reset}** submission(s) — `-{pts_rolled:.2f} pts` and "
                        f"`{markers_rolled}` markers removed from today's tally.\n\n"
                        f"They'll appear as **pending** again — pick them from the list to re-enter the correct counts."
                    ),
                    color=discord.Color.orange()
                )
                await ctx.send(embed=reset_embed)
                return

            # Settle streaks (always updates streak counters + applies milestone bonuses internally)
            acc_milestone, daily_milestone, day_total_markers, day_total_correct = \
                await settle_streak_for_reviewer(uid, today, grant_daily_streak, total_correct_day, total_markers_day)

            acc_milestone_awarded = acc_milestone
            daily_milestone_awarded = daily_milestone

            milestone_bonus_total = acc_milestone_awarded + daily_milestone_awarded

            # Recalc tier ONCE based on all the day's markers now in reviewer_markers
            tier_after, mult_after, _acc_after = await update_reviewer_tier(uid)

            # Fetch final streak values for display
            async with pool.acquire() as db:
                async with db.execute("SELECT current_streak FROM accuracy_streaks WHERE reviewer_id = ?", (uid,)) as cursor:
                    acc_row = await cursor.fetchone()
                async with db.execute("SELECT current_streak_days FROM daily_streaks WHERE reviewer_id = ?", (uid,)) as cursor:
                    daily_row = await cursor.fetchone()
            acc_streak_after = acc_row[0] if acc_row else 0
            daily_streak_after = daily_row[0] if daily_row else 0

            # Tier change vs. submission-time tier (also reused by the DM hype below)
            tier_hierarchy = {'Beginner': 1, 'Intermediate': 2, 'Advanced': 3, 'Expert': 4, 'Master': 5}
            tier_promoted = tier_after != tier_before
            is_promotion = tier_hierarchy.get(tier_after, 0) > tier_hierarchy.get(tier_before, 0)

            # ── PUBLIC ACHIEVEMENT ANNOUNCEMENT → milestone channel (confirmed) ──
            # Fires now that the day is settled, so streaks/tier/milestones are FINAL.
            # Covers exactly what the admin asked for: accuracy-streak milestones,
            # daily-streak milestones, and tier promotions (rank-ups). Not every
            # streak tick — only these meaningful events — so the channel stays useful.
            if acc_milestone_awarded > 0 or daily_milestone_awarded > 0 or is_promotion:
                try:
                    ms_target = await self._resolve_milestone_target(guild_id)
                    if ms_target:
                        member = ctx.guild.get_member(uid)
                        who = member.mention if member else f"**{username}**"
                        acc_fired = preview['acc_fired'] if acc_milestone_awarded > 0 else []
                        daily_fired = preview['daily_fired'] if daily_milestone_awarded > 0 else []
                        has_ms = bool(acc_fired or daily_fired)

                        if has_ms and is_promotion:
                            ann_title = "🏆  MILESTONE + RANK UP  🏆"
                            ann_color = discord.Color.from_rgb(255, 0, 255)
                        elif is_promotion:
                            ann_title = "🚀  RANK UP  🚀"
                            ann_color = discord.Color.from_rgb(255, 215, 0)
                        elif acc_fired and daily_fired:
                            ann_title = "💥  DOUBLE MILESTONE  💥"
                            ann_color = discord.Color.from_rgb(255, 0, 255)
                        elif acc_fired:
                            ann_title = "🔥  ACCURACY STREAK MILESTONE  🔥"
                            ann_color = discord.Color.from_rgb(0, 240, 255)
                        else:
                            ann_title = "📅  DAILY STREAK MILESTONE  📅"
                            ann_color = discord.Color.from_rgb(0, 255, 136)

                        ann = discord.Embed(
                            title=ann_title,
                            description=f"### {who} just locked it in!\n_Verified and awarded — it's official._",
                            color=ann_color
                        )
                        if member and member.display_avatar:
                            ann.set_thumbnail(url=member.display_avatar.url)

                        if acc_fired:
                            ann.add_field(
                                name="🔥 Accuracy Milestone" + ("s" if len(acc_fired) > 1 else ""),
                                value="\n".join(f"**{t}-marker perfect streak** · `+{b} pts`" for t, b in acc_fired),
                                inline=False
                            )
                        if daily_fired:
                            ann.add_field(
                                name="📅 Daily Streak Milestone" + ("s" if len(daily_fired) > 1 else ""),
                                value="\n".join(f"**{t}-day streak** · `+{b} pts`" for t, b in daily_fired),
                                inline=False
                            )
                        if is_promotion:
                            ann.add_field(
                                name="🚀 Tier Promotion",
                                value=f"{tier_emoji_map.get(tier_before, '📊')} **{tier_before}** → "
                                      f"{tier_emoji_map.get(tier_after, '📊')} **{tier_after}** ({mult_after}x)",
                                inline=False
                            )

                        ann.add_field(name="⚡ Streaks", value=f"🔥 {acc_streak_after} acc · 📅 {daily_streak_after} days", inline=True)
                        if milestone_bonus_total > 0:
                            ann.add_field(name="💰 Bonus", value=f"**+{milestone_bonus_total} pts**", inline=True)

                        leaderboard_url = "https://wavedropmaps.pages.dev/reviewing_leaderboard_final.html"
                        ann.add_field(name="📊 Leaderboard", value=f"[**Live →**]({leaderboard_url})", inline=False)
                        await ms_target.send(embed=ann)
                except Exception as e:
                    logger.warning(f"Could not send milestone channel announcement for {uid}: {e}")

            # Patch audit columns on this batch's rows (use awarded values, not gross)
            # We apply the full milestone_bonus_total to the first row of the batch, and 0 to the rest
            # so that SUM(milestone_bonus_total) across the day is accurate without duplicates.
            sub_ids = [s[0] for s in subs]
            async with pool.acquire() as db:
                for i, sub_id in enumerate(sub_ids):
                    await db.execute(
                        """UPDATE reviewers_temp SET
                           accuracy_streak_after = ?, daily_streak_after = ?,
                           milestone_bonus_total = ?
                           WHERE id = ?""",
                        (acc_streak_after, daily_streak_after,
                         milestone_bonus_total if i == 0 else 0,
                         sub_id)
                    )
                await db.commit()

            # Re-evaluate challenges with verified data
            challenges_completed = []
            try:
                from database import evaluate_challenges_for_reviewer
                challenges_completed = await evaluate_challenges_for_reviewer(uid, today)
            except Exception as e:
                logger.error(f"❌ Challenge re-eval failed for user {uid}: {e}")
                challenges_completed = []

            # Show challenges for admin confirmation — any win this user hasn't been paid
            # for yet. Wins claimed at >addpoints time have was_new_completion=False on
            # re-eval, so gate on completed + !bonus_awarded instead.
            new_challenges = [
                c for c in challenges_completed
                if c.get('completed') and not c.get('bonus_awarded')
            ]
            challenges_awarded = []
            challenge_bonus_total = 0

            if new_challenges:
                tier_emoji = {'easy': '🟢', 'medium': '🔵', 'hard': '🟣'}
                challenge_lines = []
                for c in new_challenges:
                    te = tier_emoji.get(c['tier'], '🎯')
                    challenge_lines.append(
                        f"{te} **{c['name']}** (+{c['reward']} pts)\n"
                        f"   _{c['description']}_"
                    )

                challenge_embed = discord.Embed(
                    title=f"🎯 Challenges — {username}",
                    description="\n\n".join(challenge_lines),
                    color=discord.Color.gold()
                )
                challenge_embed.add_field(
                    name="Confirmation",
                    value=f"**React ✅** to award {len(new_challenges)} challenge bonus(es) or **❌** to skip.",
                    inline=False
                )
                challenge_embed.set_footer(text="60s timeout — defaults to ✅ award.")

                challenge_msg = await ctx.send(embed=challenge_embed)
                await challenge_msg.add_reaction('✅')
                await challenge_msg.add_reaction('❌')

                def challenge_check(reaction, user):
                    return (user == ctx.author
                            and str(reaction.emoji) in ['✅', '❌']
                            and reaction.message.id == challenge_msg.id)

                try:
                    challenge_reaction, _ = await self.bot.wait_for('reaction_add', check=challenge_check, timeout=60)
                    award_challenges = (str(challenge_reaction.emoji) == '✅')
                except asyncio.TimeoutError:
                    await ctx.send("⏱️ No tick — defaulting to ✅ award challenges.")
                    award_challenges = True

                if award_challenges:
                    try:
                        from database import award_challenge_bonuses
                        challenges_awarded = await award_challenge_bonuses(uid, today)
                    except Exception as e:
                        logger.error(f"❌ Challenge award failed for user {uid}: {e}")
                    challenge_bonus_total = sum(reward for _, _, reward in challenges_awarded)
                else:
                    await ctx.send(f"⏭️ Skipped awarding challenges for {username}.")

            # Final recap embed — review pts and milestone bonus shown SEPARATELY (no merged total)
            accuracy_pct = (day_total_correct / day_total_markers * 100) if day_total_markers > 0 else 0
            recap_embed = discord.Embed(
                title=f"✅ {username} — Day Settled",
                color=discord.Color.green()
            )
            recap_embed.add_field(
                name="Day Totals",
                value=f"**{day_total_correct}/{day_total_markers}** correct ({accuracy_pct:.1f}%)",
                inline=True
            )
            recap_embed.add_field(name="💰 Review Points", value=f"+{total_final_pts:.2f} pts", inline=True)

            ms_lines = []
            if acc_milestone_awarded > 0:
                ms_lines.append(f"🔥 Acc: +{acc_milestone_awarded} pts")
            if daily_milestone_awarded > 0:
                ms_lines.append(f"📅 Daily: +{daily_milestone_awarded} pts")
            if not ms_lines:
                ms_lines.append("_(none earned)_")
            recap_embed.add_field(name="🏆 Milestone Bonus", value="\n".join(ms_lines), inline=True)

            recap_embed.add_field(name="Accuracy Streak", value=f"{acc_streak_after} markers 🔥", inline=True)
            recap_embed.add_field(name="Daily Streak", value=f"{daily_streak_after} days 📅", inline=True)
            recap_embed.add_field(name="Tier", value=f"{tier_emoji_map.get(tier_after, '📊')} {tier_after} ({mult_after}x)", inline=True)

            if challenges_awarded:
                ch_lines = "\n".join(f"🎯 **{cname}** — +{reward} pts" for _, cname, reward in challenges_awarded)
                recap_embed.add_field(
                    name=f"🏅 Challenge Bonus: +{challenge_bonus_total} pts",
                    value=ch_lines,
                    inline=False
                )

            await ctx.send(embed=recap_embed)

            # DM the reviewer with a HYPE day-rollup summary (uses day totals, not per-sub)
            try:
                user_obj = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
                if user_obj:
                    # tier_promoted / is_promotion computed once above (after tier recalc)

                    # Dynamic title + color based on day-total performance
                    if day_total_correct == day_total_markers and day_total_markers > 0:
                        title = "🔥 PERFECT REVIEW — ABSOLUTELY ELITE!"
                        color = discord.Color.from_rgb(255, 215, 0)  # gold
                        vibe = f"You went **{day_total_correct}/{day_total_markers}** — a flawless run. Snipers respect snipers. 🎯"
                    elif accuracy_pct >= 90:
                        title = "💎 STELLAR SESSION — TOP TIER ACCURACY!"
                        color = discord.Color.from_rgb(0, 240, 255)  # cyan
                        vibe = f"You nailed **{day_total_correct}/{day_total_markers}** at **{accuracy_pct:.1f}%** — pristine work. 🌊"
                    elif accuracy_pct >= 70:
                        title = "💪 SOLID SESSION — KEEP IT GOING!"
                        color = discord.Color.from_rgb(0, 255, 136)  # green
                        vibe = f"You hit **{day_total_correct}/{day_total_markers}** at **{accuracy_pct:.1f}%** — strong work, push for that perfect run next time! 🚀"
                    else:
                        title = "📊 SESSION VERIFIED — ROOM TO GROW!"
                        color = discord.Color.from_rgb(255, 107, 53)  # orange
                        vibe = f"You got **{day_total_correct}/{day_total_markers}** at **{accuracy_pct:.1f}%**. Every legend started somewhere — review the misses and come back stronger! 💪"

                    dm_embed = discord.Embed(
                        title=title,
                        description=f"Heyy **{user_obj.display_name}** — your **{today}** session is locked in!\n\n{vibe}",
                        color=color
                    )

                    # Main stats (day totals) — review pts and milestone bonus shown SEPARATELY
                    dm_embed.add_field(
                        name="🎯 Accuracy",
                        value=f"**{day_total_correct}/{day_total_markers}** ({accuracy_pct:.1f}%)",
                        inline=True
                    )
                    dm_embed.add_field(
                        name="💰 Review Points",
                        value=f"**+{total_final_pts:.2f} pts**",
                        inline=True
                    )
                    if milestone_bonus_total > 0:
                        dm_embed.add_field(
                            name="🏆 Milestone Bonus",
                            value=f"**+{milestone_bonus_total} pts**",
                            inline=True
                        )
                        dm_embed.add_field(
                            name="🥇 Current Rank",
                            value=f"{tier_emoji_map.get(tier_after, '📊')} **{tier_after}** ({mult_after}x)",
                            inline=False
                        )
                    else:
                        dm_embed.add_field(
                            name="🥇 Current Rank",
                            value=f"{tier_emoji_map.get(tier_after, '📊')} **{tier_after}** ({mult_after}x)",
                            inline=True
                        )

                    # Streak section with hype
                    streak_lines = []
                    if acc_streak_after > 0:
                        streak_lines.append(f"🔥 **Accuracy Streak:** {acc_streak_after} perfect markers")
                    if daily_streak_after > 0:
                        streak_lines.append(f"📅 **Daily Streak:** {daily_streak_after} days strong")
                    if streak_lines:
                        dm_embed.add_field(name="⚡ Your Streaks", value="\n".join(streak_lines), inline=False)

                    # Milestone celebrations — only fire if admin awarded (not skipped)
                    if acc_milestone_awarded > 0:
                        dm_embed.add_field(
                            name=f"🎉 ACCURACY STREAK MILESTONE UNLOCKED — {acc_streak_after} Perfect Markers!",
                            value=f"**+{acc_milestone_awarded} bonus pts** dropped into your wallet 💸",
                            inline=False
                        )
                    if daily_milestone_awarded > 0:
                        dm_embed.add_field(
                            name=f"📅 DAILY MILESTONE UNLOCKED — Day {daily_streak_after}!",
                            value=f"**+{daily_milestone_awarded} bonus pts** for the consistency grind 🏆",
                            inline=False
                        )

                    # Challenge bonuses celebration
                    if challenges_awarded:
                        ch_lines = "\n".join(f"🎯 **{cname}** · **+{reward} pts**" for _, cname, reward in challenges_awarded)
                        dm_embed.add_field(
                            name=f"🏅 CHALLENGE BONUS — +{challenge_bonus_total} pts",
                            value=ch_lines + "\n\n_Pure bonus for hitting today's challenges 🎯_",
                            inline=False
                        )

                    # Tier promotion celebration
                    if is_promotion:
                        dm_embed.add_field(
                            name="🚀 TIER UP! YOU'RE ASCENDING!",
                            value=f"{tier_emoji_map.get(tier_before, '📊')} **{tier_before}** → {tier_emoji_map.get(tier_after, '📊')} **{tier_after}** "
                                  f"(higher multiplier means MORE points per marker!) 💎",
                            inline=False
                        )
                    elif tier_promoted:
                        # Tier change but not a promotion — keep it light
                        dm_embed.add_field(
                            name="📊 Rank Adjusted",
                            value=f"{tier_emoji_map.get(tier_before, '📊')} {tier_before} → {tier_emoji_map.get(tier_after, '📊')} **{tier_after}** — keep grinding to climb back up! 🔥",
                            inline=False
                        )

                    # Leaderboard CTA
                    leaderboard_url = "https://wavedropmaps.pages.dev/reviewing_leaderboard_final.html"
                    dm_embed.add_field(
                        name="📊 See Where You Stack Up",
                        value=f"[**Live Leaderboard →**]({leaderboard_url})",
                        inline=False
                    )

                    dm_embed.set_footer(text="You're keeping the maps clean — legends only 🌊")
                    await user_obj.send(embed=dm_embed)
            except Exception:
                pass

        # Tracks which user_ids have already been asked about daily streak this session.
        # Prevents asking twice when a user has multiple stacked submissions.
        daily_streak_confirmed = {}  # user_id -> bool

        async def check_session_open():
            """Returns True if the session is still open. Guards against >closeday mid-loop."""
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT is_open FROM daily_sessions WHERE guild_id = ? AND session_date = ?",
                    (guild_id, today)
                ) as cursor:
                    row = await cursor.fetchone()
            return bool(row and row[0])

        async def remove_submission_flow(r_uid, r_subs):
            """Delete a specific PENDING submission (false/duplicate) without verifying it.
            Per-submission, not the whole day: if the reviewer stacked several, the admin
            picks which one. Same effect as the verify-step 'cancel' — the reviewers_temp
            row is dropped so it never reaches >closeday totals or the leaderboard overlay."""
            username = r_subs[0][2]
            if len(r_subs) == 1:
                chosen = list(r_subs)
            else:
                lines = [
                    f"`{i}.`  {s[3]} markers @ {s[4]}pts  →  {s[8]} prov pts"
                    for i, s in enumerate(r_subs, 1)
                ]
                pick = discord.Embed(
                    title=f"🗑️ Remove which submission — {username}?",
                    description="\n".join(lines) + "\n\nReply with the **submission number**, `all` to remove every one, or `cancel` to abort.",
                    color=discord.Color.orange()
                )
                await ctx.send(embed=pick)
                try:
                    pmsg = await self.bot.wait_for('message', check=check, timeout=timeout_limit - (time.time() - start_time))
                    pc = pmsg.content.strip().lower()
                except asyncio.TimeoutError:
                    await ctx.send("⏱️ Timed out — nothing removed.")
                    return
                if pc in ('cancel', 'abort', 'no', 'n'):
                    await ctx.send("↩️ Cancelled — nothing removed.")
                    return
                if pc == 'all':
                    chosen = list(r_subs)
                elif pc.isdigit() and 1 <= int(pc) <= len(r_subs):
                    chosen = [r_subs[int(pc) - 1]]
                else:
                    await ctx.send("❌ Invalid choice — nothing removed.")
                    return

            sub_ids = [s[0] for s in chosen]
            total_markers = sum(s[3] for s in chosen)
            async with pool.acquire() as db:
                placeholders = ",".join("?" for _ in sub_ids)
                await db.execute(
                    f"DELETE FROM reviewers_temp WHERE id IN ({placeholders}) AND verified = 0",
                    sub_ids
                )
                await db.commit()
            for s in chosen:
                logger.info(f"[endday] REMOVED submission id={s[0]} for {username} ({r_uid}) — {s[3]} markers discarded by admin {ctx.author.id}")
            await ctx.send(embed=discord.Embed(
                description=f"🗑️ **Removed {len(sub_ids)} submission(s)** for **{username}** — `{total_markers}` markers discarded. No points, no accuracy impact.",
                color=discord.Color.dark_grey()
            ))

        # ── MAIN LOOP ──
        while True:
            # Security: abort if session was closed externally (e.g. another admin ran >closeday)
            if not await check_session_open():
                await ctx.send("🔒 Session was closed externally. `>endday` aborted to prevent data corruption.")
                return

            rows = await fetch_pending()

            if not rows:
                verified_count = await fetch_verified_count()
                done_embed = discord.Embed(
                    title="🏁 All Submissions Verified",
                    description=f"**{verified_count}** submission(s) verified for **{today}**.\nRun `>closeday` to finalize.",
                    color=discord.Color.green()
                )
                await ctx.send(embed=done_embed)
                await auto_update_drop_map_leaderboard(self.bot, triggered_by="endday_complete")
                return

            verified_count = await fetch_verified_count()
            reviewers_list = await show_submission_list(rows, verified_count)

            try:
                msg = await self.bot.wait_for('message', check=check, timeout=timeout_limit - (time.time() - start_time))
                content = msg.content.strip().lower()
            except asyncio.TimeoutError:
                await ctx.send(f"⏱️ Timed out. Run `>endday` again to continue — **{len(reviewers_list)} reviewer(s)** still pending.")
                return

            if content in ('done', 'exit', 'stop', 'quit'):
                await ctx.send(f"⏸️ Paused. Run `>endday` again to continue — **{len(reviewers_list)} reviewer(s)** still pending.")
                return

            if content == 'all':
                for uid, subs in reviewers_list:
                    await verify_reviewer_subs(uid, subs, daily_streak_confirmed)
                    await auto_update_drop_map_leaderboard(self.bot, triggered_by="endday_verify")
                continue  # loop back to show (now-empty) list

            # Remove a specific (false) submission straight from the list — no verify step.
            # 'remove <reviewer #>' then pick which one if they stacked several.
            parts = content.split()
            if parts and parts[0] in ('remove', 'rm', 'delete', 'del'):
                if len(parts) < 2 or not parts[1].isdigit():
                    await ctx.send("❌ Usage: `remove <number>` — the reviewer's number from the list above.")
                    continue
                ridx = int(parts[1])
                if ridx < 1 or ridx > len(reviewers_list):
                    await ctx.send(f"❌ Enter a reviewer number between 1 and {len(reviewers_list)}.")
                    continue
                r_uid, r_subs = reviewers_list[ridx - 1]
                await remove_submission_flow(r_uid, r_subs)
                await auto_update_drop_map_leaderboard(self.bot, triggered_by="endday_remove")
                await push_daily_summary_for_session(ctx.guild.id, today)
                continue

            try:
                choice = int(content)
                if choice < 1 or choice > len(reviewers_list):
                    await ctx.send(f"❌ Enter a number between 1 and {len(reviewers_list)}, `remove <n>`, `all`, or `done`.")
                    continue
            except ValueError:
                await ctx.send(f"❌ Invalid input. Type a number (1–{len(reviewers_list)}), `remove <n>`, `all`, or `done`.")
                continue

            uid, subs = reviewers_list[choice - 1]
            await verify_reviewer_subs(uid, subs, daily_streak_confirmed)
            await auto_update_drop_map_leaderboard(self.bot, triggered_by="endday_verify")

            # Push daily summary after each verification to show updated state
            await push_daily_summary_for_session(ctx.guild.id, today)

    @commands.command(name='applypenalty')
    @commands.has_permissions(administrator=True)
    async def apply_penalty_cmd(self, ctx, reviewer: discord.Member = None, penalty_type: str = None, *, reason: str = ""):
        """Apply a single penalty to a reviewer.

        For the bulk Penalty C "everyone overdue" use case, see `>applypenaltymass`.

        Accepts: letter code (A–F), number (1–6), or full key (e.g. marker_mistake).

        Usage:
          >applypenalty                     (show all penalty types & codes)
          >applypenalty @user               (interactive — lists all types)
          >applypenalty @user b             (letter code)
          >applypenalty @user 2             (number from picker)
          >applypenalty @user no_thread     (full key)
          >applypenalty @user e Late reply  (with reason)
        """
        from database import apply_penalty

        penalty_options = [
            ('marker_mistake',   'A', 'Marker Mistake',     20),
            ('skipped_oldest',   'B', 'Skipped Oldest Map', 20),
            ('unclaimed_map',    'C', 'Unclaimed Map',      10),
            ('abandoned_review', 'D', 'Abandoned Review',   10),
            ('no_thread',        'E', 'No Thread',          10),
            ('incomplete_claim', 'F', 'Incomplete Claim',   30),
        ]
        valid_keys = [opt[0] for opt in penalty_options]
        letter_to_key = {opt[1].lower(): opt[0] for opt in penalty_options}

        def resolve_penalty(raw: str):
            c = (raw or "").strip().lower()
            if not c:
                return None
            if c in letter_to_key:
                return letter_to_key[c]
            if c in valid_keys:
                return c
            try:
                idx = int(c) - 1
                if 0 <= idx < len(penalty_options):
                    return penalty_options[idx][0]
            except ValueError:
                pass
            return None

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # No args → show help
        if reviewer is None:
            lines = "\n".join(
                f"`{i}.` **{code}** — {name} (-{pts} pts) · `{key}`"
                for i, (key, code, name, pts) in enumerate(penalty_options, 1)
            )
            help_embed = discord.Embed(
                title="⚠️ All Penalty Types",
                description=lines,
                color=discord.Color.orange()
            )
            help_embed.set_footer(text="Use >applypenalty @user <type> to apply a penalty · >applypenaltymass for bulk C")
            await ctx.send(embed=help_embed)
            return

        # Regular penalty mode (single user)
        if penalty_type is None:
            lines = "\n".join(
                f"`{i}.` **{code}** — {name} (-{pts} pts) · `{key}`"
                for i, (key, code, name, pts) in enumerate(penalty_options, 1)
            )
            list_embed = discord.Embed(
                title="⚠️ Apply Penalty — Pick a Type",
                description=f"Penalty target: {reviewer.mention}\n\n{lines}",
                color=discord.Color.orange()
            )
            list_embed.set_footer(text="Reply with letter (A–F), number (1–6), or full key. 60s timeout.")
            await ctx.send(embed=list_embed)

            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("⏱️ Timed out — penalty not applied.")
                return

            penalty_type = resolve_penalty(msg.content)
            if penalty_type is None:
                await ctx.send(
                    f"❌ Unknown penalty `{msg.content.strip()}`. "
                    f"Use A–F, 1–6, or one of: {', '.join(valid_keys)}"
                )
                return
        else:
            resolved = resolve_penalty(penalty_type)
            if resolved is None:
                lines = "\n".join(
                    f"• **{code}** / `{key}` — {name} (-{pts} pts)"
                    for (key, code, name, pts) in penalty_options
                )
                err_embed = discord.Embed(
                    title="❌ Invalid Penalty Type",
                    description=(
                        f"`{penalty_type}` is not a valid penalty.\n"
                        f"Accepts letter (A–F), number (1–6), or full key:\n\n{lines}"
                    ),
                    color=discord.Color.red()
                )
                await ctx.send(embed=err_embed)
                return
            penalty_type = resolved

        await apply_penalty(reviewer.id, penalty_type, reason or "Applied via >applypenalty")

        opt = next(o for o in penalty_options if o[0] == penalty_type)
        embed = discord.Embed(
            title="⚠️ Penalty Applied",
            description=f"@{reviewer.name}",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Penalty",
            value=f"**{opt[1]}** — {opt[2]} (-{opt[3]} pts) · `{penalty_type}`",
            inline=False
        )
        embed.add_field(name="Reason", value=reason or "-", inline=False)

        await ctx.send(embed=embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="penalty_applied", force=True)

    @commands.command(name='applypenaltymass')
    @commands.has_permissions(administrator=True)
    async def apply_penalty_mass(self, ctx, *, args: str = ""):
        """Apply Penalty C (Unclaimed Map) in bulk to all reviewers.

        Each non-immune reviewer loses `intervals × 10` pts. Asks for ✅ confirmation
        because it touches every reviewer at once.

        Flags:
          --intervals N     30-min intervals overdue (1–100). REQUIRED.
          --immune @user    Optional: one reviewer to skip.

        Usage:
          >applypenaltymass --intervals 3
          >applypenaltymass --immune @kiere --intervals 5
        """
        from database import get_pool
        import re

        if not args.strip():
            usage_embed = discord.Embed(
                title="⚠️ Apply Mass Penalty C (Unclaimed Map)",
                description=(
                    "Deducts **-10 pts per interval** from every reviewer (optionally minus one immune user).\n\n"
                    "**Required:** `--intervals N`\n"
                    "**Optional:** `--immune @user`\n\n"
                    "**Examples:**\n"
                    "`>applypenaltymass --intervals 3`\n"
                    "`>applypenaltymass --immune @kiere --intervals 5`"
                ),
                color=discord.Color.orange()
            )
            await ctx.send(embed=usage_embed)
            return

        immune_match = re.search(r'--immune\s+<@!?(\d+)>|--immune\s+(\d+)', args)
        intervals_match = re.search(r'--intervals\s+(\d+)', args)

        if not intervals_match:
            await ctx.send("❌ `--intervals N` is required. Example: `>applypenaltymass --intervals 3`")
            return

        intervals = int(intervals_match.group(1))
        if intervals <= 0 or intervals > 100:
            await ctx.send("❌ `--intervals` must be 1–100.")
            return

        immune_id = None
        if immune_match:
            immune_id = int(immune_match.group(1) or immune_match.group(2))

        points_per_interval = 10
        total_deduction = intervals * points_per_interval

        # Confirmation step — affects every reviewer, no undo
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute("SELECT COUNT(*) FROM reviewers") as cursor:
                row = await cursor.fetchone()
                total_reviewers = row[0] if row else 0
        affected_count = total_reviewers - (1 if immune_id else 0)

        confirm_embed = discord.Embed(
            title="⚠️ Confirm Mass Penalty C",
            description=(
                f"This will deduct **-{total_deduction} pts** from **{affected_count}** reviewer(s).\n\n"
                f"**Intervals:** {intervals} × {points_per_interval} pts\n"
                f"**Immune:** {f'<@{immune_id}>' if immune_id else '_(none)_'}\n\n"
                f"React ✅ to confirm or ❌ to cancel."
            ),
            color=discord.Color.red()
        )
        confirm_embed.set_footer(text="30s timeout — defaults to ❌ cancel.")
        msg = await ctx.send(embed=confirm_embed)
        await msg.add_reaction('✅')
        await msg.add_reaction('❌')

        def reaction_check(reaction, user):
            return (user == ctx.author
                    and str(reaction.emoji) in ['✅', '❌']
                    and reaction.message.id == msg.id)

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', check=reaction_check, timeout=30)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out — mass penalty NOT applied.")
            return

        if str(reaction.emoji) == '❌':
            await ctx.send("❌ Cancelled — mass penalty NOT applied.")
            return

        # Apply
        affected = 0
        async with pool.acquire() as db:
            async with db.execute("SELECT user_id FROM reviewers") as cursor:
                reviewers = await cursor.fetchall()

            for reviewer_row in reviewers:
                reviewer_id = reviewer_row[0]
                if immune_id and reviewer_id == immune_id:
                    continue

                reason_text = (
                    f"Penalty C (mass): {intervals} interval(s) × {points_per_interval} pts "
                    f"= -{total_deduction} pts"
                )
                await db.execute(
                    """INSERT INTO penalties (reviewer_id, penalty_type, points_deducted, reason, map_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (reviewer_id, 'unclaimed_map', total_deduction, reason_text, None)
                )
                await db.execute(
                    """UPDATE reviewers
                       SET total_points = MAX(0, total_points - ?),
                           penalties_deducted = penalties_deducted + ?
                       WHERE user_id = ?""",
                    (total_deduction, total_deduction, reviewer_id)
                )
                affected += 1

            await db.commit()

        result_embed = discord.Embed(
            title="⚠️ Mass Penalty C Applied",
            color=discord.Color.red()
        )
        result_embed.add_field(name="Intervals", value=str(intervals), inline=True)
        result_embed.add_field(name="Points Per Reviewer", value=f"**-{total_deduction} pts**", inline=True)
        result_embed.add_field(name="Reviewers Penalised", value=str(affected), inline=True)
        if immune_id:
            result_embed.add_field(name="Immune Reviewer", value=f"<@{immune_id}>", inline=False)

        await ctx.send(embed=result_embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="penalty_mass_applied", force=True)

    @commands.command(name='undopenalty')
    @commands.has_permissions(administrator=True)
    async def undo_penalty(self, ctx, reviewer: discord.Member = None):
        """Admin: reverse a penalty — refunds the points and deletes the penalty row.

        Usage:
          >undopenalty                 (pick from the 5 most recent penalties)
          >undopenalty @user           (undoes that user's most recent penalty)
        """
        pool = await get_pool()

        async def _execute_undo(uid, uname, pid, ptype, pts, reason, applied):
            async with pool.acquire() as db:
                await db.execute(
                    """UPDATE reviewers
                       SET total_points = total_points + ?,
                           penalties_deducted = MAX(0, penalties_deducted - ?)
                       WHERE user_id = ?""",
                    (pts, pts, uid)
                )
                await db.execute("DELETE FROM penalties WHERE id = ?", (pid,))
                await db.commit()
            logger.info(f"[undopenalty] Reversed penalty id={pid} on {uname} ({uid}) — refunded {pts} pts ({ptype})")
            result_embed = discord.Embed(
                title="↩️ Penalty Reversed",
                description=f"**{uname}** — refunded **+{pts} pts** ({ptype})",
                color=discord.Color.green()
            )
            if reason:
                result_embed.add_field(name="Original reason", value=reason, inline=False)
            result_embed.set_footer(text=f"Penalty applied: {str(applied).split('.')[0] if applied else '?'}")
            await ctx.send(embed=result_embed)
            await auto_update_drop_map_leaderboard(self.bot, triggered_by="penalty_reversed", force=True)

        if reviewer:
            async with pool.acquire() as db:
                async with db.execute(
                    """SELECT id, penalty_type, points_deducted, reason, applied_date
                       FROM penalties WHERE reviewer_id = ?
                       ORDER BY applied_date DESC, id DESC LIMIT 1""",
                    (reviewer.id,)
                ) as cursor:
                    row = await cursor.fetchone()
            if not row:
                await ctx.send(f"📭 No penalties on record for **{reviewer.display_name}**.")
                return
            pid, ptype, pts, reason, applied = row
            await _execute_undo(reviewer.id, reviewer.display_name, pid, ptype, pts, reason, applied)
            return

        async with pool.acquire() as db:
            async with db.execute(
                """SELECT p.id, p.reviewer_id, r.username, p.penalty_type, p.points_deducted, p.reason, p.applied_date
                   FROM penalties p
                   LEFT JOIN reviewers r ON p.reviewer_id = r.user_id
                   ORDER BY p.applied_date DESC, p.id DESC LIMIT 5"""
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send("📭 No penalties on record.")
            return

        lines = []
        for i, row in enumerate(rows, 1):
            pid, uid, uname, ptype, pts, reason, applied = row
            applied_str = str(applied).split('.')[0] if applied else '?'
            reason_str = f" — _{reason}_" if reason else ""
            lines.append(f"`{i}.` **{uname or f'User {uid}'}** · {ptype} **-{pts} pts** · {applied_str}{reason_str}")

        embed = discord.Embed(
            title="↩️ Recent Penalties — Pick One to Undo",
            description="\n".join(lines),
            color=discord.Color.orange()
        )
        embed.set_footer(text=f"Reply with a number 1–{len(rows)} or 'cancel' · 60s timeout")
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=60)
            content = msg.content.strip().lower()
            if content == 'cancel':
                await ctx.send("❌ Cancelled.")
                return
            idx = int(content) - 1
            if not (0 <= idx < len(rows)):
                await ctx.send(f"❌ Number out of range (1–{len(rows)}).")
                return
        except (ValueError, asyncio.TimeoutError):
            await ctx.send("❌ Invalid or timed out.")
            return

        pid, uid, uname, ptype, pts, reason, applied = rows[idx]
        await _execute_undo(uid, uname or f"User {uid}", pid, ptype, pts, reason, applied)

    @commands.command(name='addhelper')
    @commands.has_permissions(administrator=True)
    async def add_helper(self, ctx, helped: discord.Member, times: int):
        """Add helper assists with points awarded per help.
        Example: >addhelper @user 5
        (Awards 10 pts per help: 5 helps = 50 pts)
        """
        from database import get_pool
        from datetime import datetime

        if times <= 0:
            await ctx.send("❌ Times must be greater than 0")
            return

        if times > 100:
            await ctx.send("❌ Maximum 100 helps at once")
            return

        pts_per_help = 10
        total_bonus = times * pts_per_help

        pool = await get_pool()
        async with pool.acquire() as db:
            for _ in range(times):
                await db.execute(
                    "INSERT INTO helper_assists (helper_id, helped_reviewer_id, was_correct, base_bonus, applied_date) VALUES (?, ?, ?, ?, ?)",
                    (ctx.author.id, helped.id, 1, pts_per_help, datetime.now())
                )
            await db.execute(
                "UPDATE reviewers SET total_points = total_points + ? WHERE user_id = ?",
                (total_bonus, ctx.author.id)
            )
            await db.commit()

        embed = discord.Embed(
            title="✅ Helper Assists Added",
            color=discord.Color.green()
        )
        embed.add_field(name="Helper", value=ctx.author.mention, inline=True)
        embed.add_field(name="Helped", value=helped.mention, inline=True)
        embed.add_field(name="Times", value=str(times), inline=True)
        embed.add_field(name="Points Awarded", value=f"+{total_bonus} pts ({times} × {pts_per_help} pts)", inline=False)

        await ctx.send(embed=embed)
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="helper_added", force=True)

async def setup(bot):
    await bot.add_cog(ReviewingCommands(bot))
