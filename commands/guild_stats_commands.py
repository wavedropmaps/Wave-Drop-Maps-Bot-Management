"""
Guild Stats Dashboard — tracks member count and key stats for the bot's own guilds over time.
Displays the latest HTML report (no re-collect).
"""

import discord
from discord.ext import commands
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger('discord')

REPORTS_DIR = Path(__file__).parent.parent / 'command-trackers' / 'guild-stats' / 'data' / 'reports'


class GuildStats(commands.Cog):
    """Member count and key stats dashboard for Wave's own Discord servers."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='guilddash')
    @commands.has_any_role('Management')
    async def guilddash(self, ctx):
        """Show the latest guild stats report."""
        embed = discord.Embed(
            title="📊 Guild Stats",
            color=discord.Color.blue(),
        )

        try:
            # Find the latest report file
            if not REPORTS_DIR.exists():
                embed.title = "❌ Guild Stats"
                embed.description = "No reports directory found."
                embed.color = discord.Color.red()
                await ctx.send(embed=embed)
                return

            report_files = sorted(REPORTS_DIR.glob('report_*.html'), reverse=True)
            if not report_files:
                embed.title = "❌ Guild Stats"
                embed.description = "No reports generated yet. Run the automatic task at 14:05 UTC."
                embed.color = discord.Color.red()
                await ctx.send(embed=embed)
                return

            latest_report = report_files[0]
            report_date = latest_report.stem.replace('report_', '')

            embed.description = f"Latest snapshot from **{report_date}**"
            embed.color = discord.Color.green()
            await ctx.send(embed=embed)

            # Upload the latest report
            try:
                file = discord.File(str(latest_report), filename=latest_report.name)
                await ctx.send(
                    content="📈 Full dashboard report:",
                    file=file,
                )
                logger.info(f"[GuildStats] Sent latest report: {latest_report.name}")
            except Exception as e:
                logger.warning(f"[GuildStats] Failed to upload report: {e}")
                await ctx.send(f"Report saved to: `{latest_report}`")

        except Exception as e:
            embed.title = "❌ Guild Stats — Error"
            embed.description = str(e)
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            logger.exception("[GuildStats] Unexpected error")


async def setup(bot):
    await bot.add_cog(GuildStats(bot))
    logger.info("✅ GuildStats cog loaded")
