"""
Goals System Commands
Set and track personal activity goals
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging

logger = logging.getLogger('discord')

DUTY_NAMES = {
    'role':    '👤 Role Giver',
    'req':     '🗺️ Map Request Helper',
    'modlog':  '🔨 Mod Commands',
    'message': '💬 Messages Sent'
}

DUTY_ORDER = ['role', 'req', 'modlog', 'message']

# Full-week thresholds (matching weekly_checks.py) — used as a floor reference
DUTY_THRESHOLDS = {'role': 30, 'req': 15, 'modlog': 0, 'message': 0}


# ==================== RECOMMENDATION ENGINE ====================

async def get_goal_recommendations(user_id: int, source_guilds: list, start_date: str, end_date: str):
    """
    Returns a dict of {duty: {'recommended': int, 'reason': str}} for all duties.

    Logic per duty:
      1. Pull this week's cached count (current pace).
      2. Pull full-week insights history, compute average over last 4 full weeks.
      3. Recommended = max(historical_avg * 1.15, projected_full_week, threshold floor)
         so it's always a meaningful stretch without being unrealistic.
      4. If no data at all, fall back to threshold + small nudge.
    """
    import database

    # --- Step 1: current week cached counts ---
    current = {d: 0 for d in DUTY_ORDER}
    for duty in DUTY_ORDER:
        for guild_id in source_guilds:
            cached = await database.get_cached_user_stats(
                guild_id, user_id, duty, start_date, end_date
            )
            if cached:
                current[duty] += cached.get('count', 0)

    # --- Step 2: historical full-week averages from insights history ---
    history = await database.get_staff_insights_history(user_id)

    # Only use full-week records (not midweek)
    full_week_records = [r for r in history if not r['is_midweek']]

    # Group by duty, take the last 4 full weeks (already sorted newest-first)
    hist_by_duty = {d: [] for d in DUTY_ORDER}
    for record in full_week_records:
        duty = record['duty_type']
        if duty in hist_by_duty:
            hist_by_duty[duty].append(record['count'])

    hist_avg = {}
    for duty, counts in hist_by_duty.items():
        recent = counts[:4]
        hist_avg[duty] = sum(recent) / len(recent) if recent else None

    # --- Step 3: build recommendations ---
    recs = {}
    for duty in DUTY_ORDER:
        threshold = DUTY_THRESHOLDS.get(duty, 0)
        avg = hist_avg.get(duty)
        cur = current[duty]

        candidates = []

        if avg is not None:
            # 15% stretch above recent average
            candidates.append(int(avg * 1.15))

        if cur > 0:
            # Rough full-week projection: assume ~2/3 through week on average
            candidates.append(int(cur * 1.5))

        if threshold > 0:
            # Always at least a bit above the pass threshold
            candidates.append(threshold + max(1, threshold // 4))

        if candidates:
            recommended = max(candidates)
            # Round to nearest sensible number
            if recommended >= 50:
                recommended = round(recommended / 5) * 5
            elif recommended >= 20:
                recommended = round(recommended / 2) * 2

            # Build reason string
            weeks_of_data = min(len(hist_by_duty[duty]), 4)
            if avg is not None and cur > 0:
                reason = f"Your {weeks_of_data}-wk avg is **{int(avg)}** and you're at **{cur}** so far this week"
            elif avg is not None:
                reason = f"Based on your {weeks_of_data}-week average of **{int(avg)}**"
            elif cur > 0:
                reason = f"Based on your current pace of **{cur}** this week"
            else:
                reason = "Based on the standard performance threshold"
        else:
            recommended = max(threshold + 1, 5)
            reason = "No history yet — start here and adjust as you go"

        recs[duty] = {'recommended': recommended, 'reason': reason}

    return recs


def build_recommendation_text(recs: dict, existing_goals: dict) -> str:
    """Build recommendation lines for duties the user hasn't set a goal for yet."""
    lines = []
    for duty in DUTY_ORDER:
        if duty in existing_goals:
            continue
        rec = recs.get(duty)
        if not rec:
            continue
        label = DUTY_NAMES.get(duty, duty)
        lines.append(
            f"{label}: **{rec['recommended']}**\n"
            f"↳ *{rec['reason']}*"
        )
    return "\n\n".join(lines) if lines else ""


# ==================== COG ====================

class Goals(commands.Cog):
    """Commands for goal tracking"""

    def __init__(self, bot):
        self.bot = bot

    async def _get_source_guilds(self, ctx) -> list:
        from core.helpers import get_automation_config
        auto_config = get_automation_config()
        guilds = auto_config.get('source_guilds', [])
        return guilds or [ctx.guild.id]

    @commands.group(name='goal', invoke_without_command=True, help='View your personal goals and progress')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def goal(self, ctx):
        """Show current goals and progress"""
        import database
        from core.cache import config_cache

        user_id = ctx.author.id
        goals = await database.get_user_goals(user_id)
        source_guilds = await self._get_source_guilds(ctx)

        global_dates = await config_cache.get_global_dates()
        start_date = global_dates.get('start_date')
        end_date = global_dates.get('end_date')

        # ── No goals set → show recommendations ──────────────────────────
        if not goals:
            embed = discord.Embed(
                title="🎯 Personal Goals",
                description=(
                    "You haven't set any goals yet!\n\n"
                    "**Set a goal:**\n"
                    "`>goal set <duty> <target>`\n\n"
                    "**Available duties:** `role` · `req` · `modlog` · `message`"
                ),
                color=discord.Color.blue()
            )

            if start_date and end_date:
                try:
                    recs = await get_goal_recommendations(user_id, source_guilds, start_date, end_date)
                    rec_text = build_recommendation_text(recs, {})
                    if rec_text:
                        embed.add_field(
                            name="💡 Recommended Goals For You",
                            value=rec_text,
                            inline=False
                        )
                except Exception as e:
                    logger.error(f"Error generating recommendations: {e}")

            embed.set_footer(text="Use >goal set <duty> <number> to set a goal")
            return await ctx.send(embed=embed)

        # ── Has goals → show progress ─────────────────────────────────────
        if not start_date or not end_date:
            return await ctx.send(embed=discord.Embed(
                title="Error",
                description="❌ Global dates are not configured. Contact an admin.",
                color=discord.Color.red()
            ))

        embed = discord.Embed(
            title="🎯 Your Personal Goals",
            description=f"**Period:** {start_date} → {end_date}",
            color=discord.Color.green()
        )

        for duty, target in goals.items():
            current = 0
            for guild_id in source_guilds:
                cached = await database.get_cached_user_stats(
                    guild_id, user_id, duty, start_date, end_date
                )
                current += cached.get('count', 0) if cached else 0

            progress = min(100, int((current / target) * 100)) if target > 0 else 0
            bar = "█" * (progress // 10) + "░" * (10 - progress // 10)

            if current >= target:
                status = "✅ COMPLETE!"
            elif progress >= 75:
                status = "🟢 On track"
            elif progress >= 50:
                status = "🟡 Making progress"
            else:
                status = "🔴 Needs work"

            embed.add_field(
                name=DUTY_NAMES.get(duty, duty.title()),
                value=f"**Progress:** {current}/{target} ({progress}%)\n`{bar}`\n{status}",
                inline=False
            )

        # Recommendations for duties without goals
        unset = [d for d in DUTY_ORDER if d not in goals]
        if unset:
            try:
                recs = await get_goal_recommendations(user_id, source_guilds, start_date, end_date)
                lines = []
                for duty in unset:
                    rec = recs.get(duty)
                    if rec:
                        label = DUTY_NAMES.get(duty, duty)
                        lines.append(f"{label}: **{rec['recommended']}** — *{rec['reason']}*")
                if lines:
                    embed.add_field(
                        name="💡 Suggested Goals for Remaining Duties",
                        value="\n".join(lines),
                        inline=False
                    )
            except Exception as e:
                logger.error(f"Error generating recommendations in goal view: {e}")

        embed.set_footer(text="Use >goal set <duty> <number> to update goals • >goal clear to reset")
        await ctx.send(embed=embed)

    @goal.command(name='set', help='Set a goal for a specific duty')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def goal_set(self, ctx, duty: str, target: int):
        """Set a goal for a duty"""
        import database
        from core.helpers import create_error_embed
        from core.cache import config_cache

        valid_duties = ['role', 'req', 'modlog', 'message']
        if duty.lower() not in valid_duties:
            return await ctx.send(embed=create_error_embed(
                "Invalid Duty",
                f"Duty must be one of: {', '.join([f'`{d}`' for d in valid_duties])}",
                "**Example:** `>goal set role 50`"
            ))

        if target <= 0:
            return await ctx.send(embed=create_error_embed(
                "Invalid Target",
                "Target must be a positive number",
                "**Example:** `>goal set role 50`"
            ))

        if target > 10000:
            return await ctx.send(embed=create_error_embed(
                "Target Too High",
                "Target cannot exceed 10,000",
                "Be realistic with your goals!"
            ))

        duty = duty.lower()
        await database.set_user_goal(ctx.author.id, duty, target)

        embed = discord.Embed(
            title="✅ Goal Set!",
            description=(
                f"**Duty:** {DUTY_NAMES.get(duty, duty.title())}\n"
                f"**Target:** {target} actions\n\n"
                f"Use `>goal` to check your progress!"
            ),
            color=discord.Color.green()
        )

        # Recommendations for other duties not yet set
        try:
            global_dates = await config_cache.get_global_dates()
            start_date = global_dates.get('start_date')
            end_date = global_dates.get('end_date')

            if start_date and end_date:
                source_guilds = await self._get_source_guilds(ctx)
                existing_goals = await database.get_user_goals(ctx.author.id)  # includes the one just set

                recs = await get_goal_recommendations(ctx.author.id, source_guilds, start_date, end_date)
                rec_text = build_recommendation_text(recs, existing_goals)

                if rec_text:
                    embed.add_field(
                        name="💡 Suggested Goals for Other Duties",
                        value=rec_text,
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="🎯 All Duties Covered!",
                        value="You have goals set for every duty. Nice work!",
                        inline=False
                    )
        except Exception as e:
            logger.error(f"Error generating post-set recommendations: {e}")

        await ctx.send(embed=embed)
        logger.info(f"Goal set by {ctx.author.id} - {duty}: {target}")

    @goal.command(name='remove', aliases=['delete', 'rm'], help='Remove a specific goal')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def goal_remove(self, ctx, duty: str):
        """Remove a specific goal"""
        import database
        from core.helpers import create_error_embed

        valid_duties = ['role', 'req', 'modlog', 'message']
        if duty.lower() not in valid_duties:
            return await ctx.send(embed=create_error_embed(
                "Invalid Duty",
                f"Duty must be one of: {', '.join([f'`{d}`' for d in valid_duties])}"
            ))

        duty = duty.lower()
        goals = await database.get_user_goals(ctx.author.id)
        if duty not in goals:
            return await ctx.send(embed=create_error_embed(
                "No Goal Found",
                f"You don't have a goal set for `{duty}`",
                "Use `>goal` to see your current goals"
            ))

        await database.delete_user_goal(ctx.author.id, duty)

        await ctx.send(embed=discord.Embed(
            title="✅ Goal Removed",
            description=f"Your {DUTY_NAMES.get(duty, duty)} goal has been removed.",
            color=discord.Color.green()
        ))
        logger.info(f"Goal removed by {ctx.author.id} - {duty}")

    @goal.command(name='clear', help='Clear all your goals')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def goal_clear(self, ctx):
        """Clear all goals"""
        import database

        goals = await database.get_user_goals(ctx.author.id)
        if not goals:
            return await ctx.send(embed=discord.Embed(
                title="ℹ️ No Goals",
                description="You don't have any goals set.",
                color=discord.Color.blue()
            ))

        await database.clear_user_goals(ctx.author.id)
        await ctx.send(embed=discord.Embed(
            title="✅ All Goals Cleared",
            description="All your personal goals have been removed.",
            color=discord.Color.green()
        ))
        logger.info(f"All goals cleared by {ctx.author.id}")


async def setup(bot):
    """Load the Goals cog"""
    await bot.add_cog(Goals(bot))