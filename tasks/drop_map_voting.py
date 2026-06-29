"""
Drop Map Voting — startup reconciliation task.

On bot ready:
  1. Wait for the DropMapVoting cog to be loaded.
  2. Refresh all leaderboard card embeds to match current DB state.
     (Handles the case where votes happened while the bot was down — though
      that can't actually happen here since votes go through the bot, this is
      cheap insurance and also useful after manual DB edits.)
"""

import discord
from discord.ext import commands
import asyncio
import logging

logger = logging.getLogger('discord')

_RECONCILE_LOCK = asyncio.Lock()
_RECONCILED = False


async def _reconcile(bot: commands.Bot):
    """Refresh every card embed once."""
    global _RECONCILED
    async with _RECONCILE_LOCK:
        if _RECONCILED:
            return
        cog = bot.get_cog("DropMapVoting")
        if cog is None:
            logger.warning("[DropMapVoting Task] Cog not loaded — skipping reconcile")
            return
        try:
            await cog.refresh_ranks()
            _RECONCILED = True
            logger.info("[DropMapVoting Task] Startup reconciliation complete")
        except Exception as e:
            logger.error(f"[DropMapVoting Task] Reconcile failed: {e}")


class DropMapVotingStartup(commands.Cog):
    """Tiny cog whose only job is to trigger reconciliation when the bot is ready."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Defer slightly so the main cog has a chance to finish cog_load
        await asyncio.sleep(2)
        await _reconcile(self.bot)


async def setup(bot: commands.Bot):
    await bot.add_cog(DropMapVotingStartup(bot))
