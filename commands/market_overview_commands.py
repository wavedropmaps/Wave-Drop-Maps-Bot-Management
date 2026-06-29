"""
Cross-market executive overview — reads all three tracker DBs, posts HTML report.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import discord
from discord.ext import commands

logger = logging.getLogger("discord")

OVERVIEW_PY = (
    Path(__file__).resolve().parent.parent
    / "command-trackers" / "market-overview" / "scripts" / "generate_overview.py"
)


class MarketOverview(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="marketoverview", aliases=["mktoverview", "marketexec"])
    @commands.has_any_role("Management")
    async def marketoverview(self, ctx):
        """Generate the cross-market executive overview (guild + mktdash + rdropmap)."""
        embed = discord.Embed(
            title="📊 Market Overview",
            description="Building executive summary from tracker databases…",
            color=discord.Color.blue(),
        )
        msg = await ctx.send(embed=embed)

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(OVERVIEW_PY),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60)
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                embed.title = "❌ Market Overview — Failed"
                embed.description = stderr[-500:] or stdout[-500:]
                embed.color = discord.Color.red()
                await msg.edit(embed=embed)
                return

            report_path = None
            for line in stdout.splitlines():
                if line.startswith("Overview saved:"):
                    report_path = line.split(":", 1)[1].strip()

            embed.title = "✅ Market Overview"
            embed.description = "Cross-market executive summary generated."
            embed.color = discord.Color.green()
            await msg.edit(embed=embed)

            if report_path and Path(report_path).exists():
                await ctx.send(
                    content="📈 Market overview report:",
                    file=discord.File(report_path, filename=Path(report_path).name),
                )

        except asyncio.TimeoutError:
            embed.title = "⏱️ Market Overview — Timed Out"
            embed.description = "Generation took longer than 60 seconds."
            embed.color = discord.Color.red()
            await msg.edit(embed=embed)
        except Exception as e:
            logger.exception("[MarketOverview] error")
            embed.title = "❌ Market Overview — Error"
            embed.description = str(e)
            embed.color = discord.Color.red()
            await msg.edit(embed=embed)


async def setup(bot):
    await bot.add_cog(MarketOverview(bot))
    logger.info("✅ MarketOverview cog loaded")
