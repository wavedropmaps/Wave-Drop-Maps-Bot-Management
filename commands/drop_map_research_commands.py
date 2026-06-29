"""
Drop Map Research Commands
Displays the latest HTML report (no re-collect).
"""

import discord
from discord.ext import commands
import logging
from pathlib import Path

logger = logging.getLogger('discord')

REPORTS_DIR = Path(__file__).parent.parent / 'command-trackers' / 'drop-map-research' / 'data' / 'reports'


class DropMapResearch(commands.Cog):
    """Market research for Fortnite drop-map Discord servers."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='rdropmap')
    @commands.has_any_role('Management')
    async def rdropmap(self, ctx):
        """Show the latest drop map research report."""
        embed = discord.Embed(
            title="📊 Drop Map Research",
            color=discord.Color.blue()
        )

        try:
            # Find the latest report file
            if not REPORTS_DIR.exists():
                embed.title = "❌ Drop Map Research"
                embed.description = "No reports directory found."
                embed.color = discord.Color.red()
                await ctx.send(embed=embed)
                return

            report_files = sorted(REPORTS_DIR.glob('report_*.html'), reverse=True)
            if not report_files:
                embed.title = "❌ Drop Map Research"
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
                await ctx.send(content="📈 Full drop map market dashboard:", file=file)
                logger.info(f"[DropMapResearch] Sent latest report: {latest_report.name}")
            except Exception as e:
                logger.warning(f"[DropMapResearch] Failed to upload report: {e}")
                await ctx.send(f"Report saved to: `{latest_report}`")

        except Exception as e:
            embed.title = "❌ Drop Map Research — Error"
            embed.description = str(e)
            embed.color = discord.Color.red()
            await ctx.send(embed=embed)
            logger.exception(f"[DropMapResearch] Unexpected error")


async def setup(bot):
    await bot.add_cog(DropMapResearch(bot))
    logger.info("✅ DropMapResearch cog loaded")
