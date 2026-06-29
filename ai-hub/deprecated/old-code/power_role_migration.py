"""
power_role_migration.py — ONE-TIME startup migration (self-disabling)
================================================================================
On the next bot startup this runs exactly once: it gives every current
badge-holder their correct Power Points tier role in the Staff Hub guild
(role only — NO wave points), then records a flag in the `migrations` table so
it never runs again.

The heavy lifting lives in tasks/power_points_rewards.migrate_existing_badge_roles().
This cog is just the "run once on boot, then flag it" wrapper.

Safety:
  - In-memory guard prevents re-running if on_ready fires again (reconnects).
  - DB flag (`migrations` table) prevents re-running across restarts.
  - If the migration raises, the flag is NOT set, so it retries next startup.
================================================================================
"""

import logging
from datetime import datetime, timezone

from discord.ext import commands

import database
from tasks.power_points_rewards import migrate_existing_badge_roles

logger = logging.getLogger('discord')

# Bump the version suffix if you ever need to intentionally re-run a backfill.
MIGRATION_NAME = 'power_roles_backfill_v1'


async def _ensure_migrations_table():
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS migrations (
                migration_name TEXT PRIMARY KEY,
                executed_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()


async def _is_done(name: str) -> bool:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT 1 FROM migrations WHERE migration_name = ?', (name,)) as cur:
            return await cur.fetchone() is not None


async def _mark_done(name: str):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'INSERT OR IGNORE INTO migrations (migration_name, executed_at) VALUES (?, ?)',
            (name, datetime.now(timezone.utc).isoformat())
        )
        await db.commit()


class PowerRoleMigration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._ran_this_session = False

    @commands.Cog.listener()
    async def on_ready(self):
        # on_ready can fire multiple times (gateway reconnects) — guard it.
        if self._ran_this_session:
            return
        self._ran_this_session = True

        try:
            await _ensure_migrations_table()

            if await _is_done(MIGRATION_NAME):
                logger.info(f"⏭️ Migration '{MIGRATION_NAME}' already applied — skipping")
                return

            logger.info(f"🚀 Running one-time Power role backfill '{MIGRATION_NAME}'…")
            summary = await migrate_existing_badge_roles(self.bot, apply=True)

            # Only flag as done if it actually completed without aborting.
            await _mark_done(MIGRATION_NAME)
            logger.info(
                f"✅ Power role backfill complete and flagged. "
                f"Roles assigned: {summary.get('roles_assigned', 0)}, "
                f"tiers marked claimed (no pay): {summary.get('tiers_marked', 0)}, "
                f"wave points skipped: {summary.get('skipped_points', 0)}, "
                f"errors: {summary.get('errors', 0)}"
            )
        except Exception as e:
            # Do NOT mark done — it'll retry on the next startup.
            logger.error(f"❌ Power role backfill failed (will retry next startup): {e}", exc_info=True)


async def setup(bot):
    await bot.add_cog(PowerRoleMigration(bot))
