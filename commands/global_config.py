"""
Global Configuration Commands
Manage global settings that affect ALL servers the bot is in
✅ FIXED: Now properly reads config.json directly
✅ NEW: parse_date() accepts many formats and auto-normalises to dd/mm/yyyy
✅ NEW: >globalconfig setdates <start> <end> — set both dates in one command
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging
import json
import os
import asyncio

logger = logging.getLogger('discord')

class GlobalConfig(commands.Cog):
    """Commands for managing global configuration [ALL SERVERS]"""

    def __init__(self, bot):
        self.bot = bot
        self.config_file = 'config.json'

    # ==================== CONFIG I/O ====================

    def load_config(self):
        """Load config from JSON file"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}

    def save_config(self, config):
        """Save config to JSON file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise

    # ==================== DATE PARSING ====================

    def parse_date(self, raw: str) -> str:
        """
        Accept many common date formats and always return dd/mm/yyyy.

        Accepted inputs (examples):
          01/03/2026   1/3/2026     (slash-separated, day-first)
          01-03-2026   1-3-2026     (dash-separated, day-first)
          01.03.2026                (dot-separated)
          01032026                  (no separator, 8 digits)
          2026-03-01   2026/03/01   (ISO / year-first)

        Raises ValueError with a friendly message if nothing matches.
        """
        raw = raw.strip()

        formats = [
            '%d/%m/%Y', '%d/%m/%y',   # 01/03/2026  or  01/03/26
            '%d-%m-%Y', '%d-%m-%y',   # 01-03-2026
            '%d.%m.%Y', '%d.%m.%y',   # 01.03.2026
            '%Y-%m-%d',               # 2026-03-01  (ISO 8601)
            '%Y/%m/%d',               # 2026/03/01
            '%d%m%Y',                 # 01032026   (no separator, 8 digits)
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(raw, fmt)
                return dt.strftime('%d/%m/%Y')   # always stored as dd/mm/yyyy
            except ValueError:
                continue

        raise ValueError(
            f"`{raw}` isn't a recognised date.\n"
            f"Accepted formats: `01/03/2026`, `1-3-2026`, `2026-03-01`, `01032026`"
        )

    # ==================== SHARED DB RESET ====================

    async def _reset_db(self):
        """Clear the tables that must be wiped on a date change."""
        import database
        reports = await database.clear_sent_reports_global()
        stats   = await database.clear_user_stats_global()
        goals   = await database.clear_user_goals_global()
        pool = await database.get_pool()
        async with pool.acquire() as db:
            await db.execute("DELETE FROM maintenance_tracking")
            await db.commit()
        logger.info(f"DB cleared — reports:{reports} stats:{stats} goals:{goals} + maintenance_tracking")
        return reports, stats, goals

    # ==================== VIEW ====================

    @commands.group(name='globalconfig', aliases=['globalc'], invoke_without_command=True,
                    help="View or edit global configuration (affects all servers).")
    @commands.has_any_role('007', '+', 'Management')
    async def globalconfig(self, ctx):
        """View global configuration settings. Usage: >globalconfig"""
        try:
            config = self.load_config()
            global_config = config.get('global_dates', {})

            embed = discord.Embed(
                title="🌐 Global Configuration",
                description="These settings apply to **all servers**",
                color=discord.Color.purple(),
                timestamp=datetime.now(timezone.utc)
            )

            start_date = global_config.get('start_date')
            end_date   = global_config.get('end_date')

            if start_date and end_date:
                try:
                    start_dt = datetime.strptime(start_date, '%d/%m/%Y')
                    end_dt   = datetime.strptime(end_date,   '%d/%m/%Y')
                    now      = datetime.now()
                    duration = (end_dt - start_dt).days + 1

                    if start_dt <= now <= end_dt:
                        remaining = (end_dt - now).days + 1
                        status = f"🟢 Active ({remaining} days remaining)"
                    elif now < start_dt:
                        status = f"🟡 Upcoming (starts in {(start_dt - now).days} days)"
                    else:
                        status = "🔴 Ended"

                    embed.add_field(
                        name="📅 Global Dates",
                        value=(
                            f"**Start:** {start_date}\n"
                            f"**End:** {end_date}\n"
                            f"**Duration:** {duration} days\n"
                            f"**Status:** {status}"
                        ),
                        inline=False
                    )
                except Exception:
                    embed.add_field(
                        name="📅 Global Dates",
                        value=f"**Start:** {start_date}\n**End:** {end_date}",
                        inline=False
                    )
            else:
                embed.add_field(
                    name="📅 Global Dates",
                    value=f"**Start:** {start_date or 'Not set'}\n**End:** {end_date or 'Not set'}",
                    inline=False
                )

            embed.set_footer(text=(
                ">globalconfig setdates <start> <end>  |  "
                ">globalconfig setstartdate <date>  |  >globalconfig setenddate <date>"
            ))
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in globalconfig: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"Failed to retrieve global configuration: {e}",
                color=discord.Color.red()
            ))

    # ==================== SET BOTH DATES (NEW) ====================

    @globalconfig.command(name='setdates',
                          help="Set start AND end date in one command. Auto-converts any format. WARNING: Clears database!")
    @commands.has_any_role('007', '+', 'Management')
    async def setdates(self, ctx, start: str, end: str):
        """
        Set global start AND end date for ALL servers in one go.
        Auto-accepts: dd/mm/yyyy  d/m/yyyy  dd-mm-yyyy  2026-03-01  01032026

        Usage:   >globalconfig setdates <start> <end>
        Example: >globalconfig setdates 01/03/2026 07/03/2026
        Example: >globalconfig setdates 2026-03-01 2026-03-07
        """
        # Parse both (fail fast before any DB touch)
        try:
            parsed_start = self.parse_date(start)
        except ValueError as e:
            return await ctx.send(embed=discord.Embed(
                title="❌ Invalid Start Date", description=str(e), color=discord.Color.red()
            ))

        try:
            parsed_end = self.parse_date(end)
        except ValueError as e:
            return await ctx.send(embed=discord.Embed(
                title="❌ Invalid End Date", description=str(e), color=discord.Color.red()
            ))

        # Sanity: start must be <= end
        if datetime.strptime(parsed_start, '%d/%m/%Y') > datetime.strptime(parsed_end, '%d/%m/%Y'):
            return await ctx.send(embed=discord.Embed(
                title="❌ Date Range Invalid",
                description=f"Start `{parsed_start}` must be before end `{parsed_end}`.",
                color=discord.Color.red()
            ))

        duration = (datetime.strptime(parsed_end, '%d/%m/%Y') - datetime.strptime(parsed_start, '%d/%m/%Y')).days + 1

        # Note any auto-corrections made
        notes = []
        if start != parsed_start:
            notes.append(f"Start `{start}` → `{parsed_start}`")
        if end != parsed_end:
            notes.append(f"End `{end}` → `{parsed_end}`")
        note_text = ("\n\n📝 **Auto-converted:** " + "  |  ".join(notes)) if notes else ""

        msg = await ctx.send(embed=discord.Embed(
            title="⚠️ Database Reset Warning",
            description=(
                f"Setting dates to **{parsed_start}** → **{parsed_end}** ({duration} days) will:\n\n"
                f"🗑️ Clear all **sent reports**\n"
                f"🗑️ Clear all **user stats**\n"
                f"🗑️ Clear all **user goals**\n"
                f"🗑️ Clear **maintenance tracking**\n\n"
                f"Affects **all {len(self.bot.guilds)} servers**.\n\n"
                f"Updating in 5 seconds...{note_text}"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        ))

        await asyncio.sleep(5)

        # Save to config
        config = self.load_config()
        old_start = config.get('global_dates', {}).get('start_date')
        old_end   = config.get('global_dates', {}).get('end_date')

        for key in ('global_dates', 'global'):
            if key not in config:
                config[key] = {}
            config[key]['start_date'] = parsed_start
            config[key]['end_date']   = parsed_end

        self.save_config(config)
        self.bot.dispatch('dates_updated')   # ← wake up challenge scheduler
        reports, stats, goals = await self._reset_db()

        success = discord.Embed(
            title="✅ Global Dates Updated",
            description=(
                f"**Start:** {parsed_start}\n"
                f"**End:**   {parsed_end}\n"
                f"**Duration:** {duration} days\n"
                f"🌐 Affects **all {len(self.bot.guilds)} servers**\n\n"
                f"**Database Cleared:**\n"
                f"• 🗑️ Sent reports: {reports} cleared\n"
                f"• 🗑️ User stats:   {stats} cleared\n"
                f"• 🗑️ User goals:   {goals} cleared\n"
                f"• 🗑️ Maintenance tracking: cleared\n\n"
                f"✅ Ready for new tracking period!{note_text}"
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        if old_start or old_end:
            success.add_field(
                name="Previous Dates",
                value=f"Start: {old_start or 'none'}  →  End: {old_end or 'none'}",
                inline=False
            )

        await msg.edit(embed=success)
        logger.info(f"Dates set {parsed_start}→{parsed_end} by {ctx.author} (was {old_start}→{old_end})")

    # ==================== SET START DATE ====================

    @globalconfig.command(name='setstartdate',
                          help="Set the global start date. Accepts any common format. WARNING: Clears database!")
    @commands.has_any_role('007', '+', 'Management')
    async def setstartdate(self, ctx, date: str):
        """
        Set global start date for ALL servers.
        Auto-accepts: dd/mm/yyyy  d/m/yyyy  dd-mm-yyyy  2026-03-01  01032026

        Usage:   >globalconfig setstartdate <date>
        Example: >globalconfig setstartdate 01/03/2026
        """
        try:
            parsed = self.parse_date(date)
        except ValueError as e:
            return await ctx.send(embed=discord.Embed(
                title="❌ Invalid Date Format", description=str(e), color=discord.Color.red()
            ))

        note = f"\n\n📝 Auto-converted `{date}` → `{parsed}`" if date != parsed else ""

        msg = await ctx.send(embed=discord.Embed(
            title="⚠️ Database Reset Warning",
            description=(
                f"Setting global start date to **{parsed}** will:\n\n"
                f"🗑️ Clear all **sent reports**\n"
                f"🗑️ Clear all **user stats**\n"
                f"🗑️ Clear all **user goals**\n\n"
                f"Affects **all {len(self.bot.guilds)} servers**.\n\n"
                f"Updating in 5 seconds...{note}"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        ))

        await asyncio.sleep(5)

        config = self.load_config()
        old = config.get('global_dates', {}).get('start_date')
        for key in ('global_dates', 'global'):
            if key not in config:
                config[key] = {}
            config[key]['start_date'] = parsed
        self.save_config(config)
        self.bot.dispatch('dates_updated')   # ← wake up challenge scheduler
        reports, stats, goals = await self._reset_db()

        success = discord.Embed(
            title="✅ Global Start Date Updated",
            description=(
                f"**New Start Date:** {parsed}\n"
                f"🌐 Affects **all {len(self.bot.guilds)} servers**\n\n"
                f"**Database Cleared:**\n"
                f"• 🗑️ Sent reports: {reports} cleared\n"
                f"• 🗑️ User stats:   {stats} cleared\n"
                f"• 🗑️ User goals:   {goals} cleared\n"
                f"• 🗑️ Maintenance tracking: cleared\n\n"
                f"✅ Ready for new tracking period!{note}"
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        if old:
            success.add_field(name="Previous Start Date", value=old, inline=False)
        await msg.edit(embed=success)
        logger.info(f"Start date set to {parsed} by {ctx.author} (was {old})")

    # ==================== SET END DATE ====================

    @globalconfig.command(name='setenddate',
                          help="Set the global end date. Accepts any common format. WARNING: Clears database!")
    @commands.has_any_role('007', '+', 'Management')
    async def setenddate(self, ctx, date: str):
        """
        Set global end date for ALL servers.
        Auto-accepts: dd/mm/yyyy  d/m/yyyy  dd-mm-yyyy  2026-03-01  01032026

        Usage:   >globalconfig setenddate <date>
        Example: >globalconfig setenddate 07/03/2026
        """
        try:
            parsed = self.parse_date(date)
        except ValueError as e:
            return await ctx.send(embed=discord.Embed(
                title="❌ Invalid Date Format", description=str(e), color=discord.Color.red()
            ))

        note = f"\n\n📝 Auto-converted `{date}` → `{parsed}`" if date != parsed else ""

        msg = await ctx.send(embed=discord.Embed(
            title="⚠️ Database Reset Warning",
            description=(
                f"Setting global end date to **{parsed}** will:\n\n"
                f"🗑️ Clear all **sent reports**\n"
                f"🗑️ Clear all **user stats**\n"
                f"🗑️ Clear all **user goals**\n\n"
                f"Affects **all {len(self.bot.guilds)} servers**.\n\n"
                f"Updating in 5 seconds...{note}"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        ))

        await asyncio.sleep(5)

        config = self.load_config()
        old = config.get('global_dates', {}).get('end_date')
        for key in ('global_dates', 'global'):
            if key not in config:
                config[key] = {}
            config[key]['end_date'] = parsed
        self.save_config(config)
        self.bot.dispatch('dates_updated')   # ← wake up challenge scheduler
        reports, stats, goals = await self._reset_db()

        success = discord.Embed(
            title="✅ Global End Date Updated",
            description=(
                f"**New End Date:** {parsed}\n"
                f"🌐 Affects **all {len(self.bot.guilds)} servers**\n\n"
                f"**Database Cleared:**\n"
                f"• 🗑️ Sent reports: {reports} cleared\n"
                f"• 🗑️ User stats:   {stats} cleared\n"
                f"• 🗑️ User goals:   {goals} cleared\n"
                f"• 🗑️ Maintenance tracking: cleared\n\n"
                f"✅ Ready for new tracking period!{note}"
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        if old:
            success.add_field(name="Previous End Date", value=old, inline=False)
        await msg.edit(embed=success)
        logger.info(f"End date set to {parsed} by {ctx.author} (was {old})")


async def setup(bot):
    """Load the Global Configuration cog"""
    await bot.add_cog(GlobalConfig(bot))