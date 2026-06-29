"""
Leaderboard Updater - tasks/leaderboard_updater.py

VBucks leaderboard removed as part of economy unification to Wave Points.
Public API stubs are kept for compatibility with database.py and main.py callers.
"""

import asyncio
import logging

logger = logging.getLogger('discord')


# ==================== VBUCKS LEADERBOARD STUBS ====================
# These functions are called by database.py (add_vbucks/set_vbucks hooks) and
# main.py (startup refresh / background loop). They are no-ops post-unification.

async def auto_update_vbucks_leaderboard(bot, duty_type: str = "all", triggered_by: str = "vbucks_change"):
    """Stub — VBucks leaderboard removed post-economy-unification."""
    pass


async def update_all_vbucks_leaderboards(bot, triggered_by: str = "manual_update"):
    """Stub — VBucks leaderboard removed post-economy-unification."""
    pass


async def update_all_leaderboards(bot, triggered_by: str = "manual_update"):
    """Stub — no VBucks leaderboards to refresh post-economy-unification."""
    logger.debug(f"update_all_leaderboards called (triggered_by={triggered_by}): no-op")
    return {}


async def startup_refresh_all_leaderboards(bot):
    """Stub — VBucks leaderboard removed; nothing to refresh on startup."""
    logger.info("🚀 [Startup] Leaderboard refresh skipped (VBucks leaderboard removed)")
    return {}


async def leaderboard_refresh_loop(bot):
    """Background refresh loop — no-op after VBucks leaderboard removal."""
    await bot.wait_until_ready()
    logger.info("🔄 Leaderboard refresh loop started (no-op)")
    while True:
        await asyncio.sleep(86400)


async def setup(bot):
    """Setup function for Discord.py to load this module as an extension."""
    pass
