"""
tasks/away_role_sync.py — Sync away roles to database every 12 hours.

Checks all 3 away role IDs:
  - Loot route away (1495685790452420608)
  - Surge route away (1513082353986306048)
  - General staff away (1231259676457566250)

Syncs to both loot_route_away_dates and surge_route_away_dates.
"""

import logging
import asyncio
from datetime import datetime, timezone
from discord.ext import commands, tasks

import database

logger = logging.getLogger('discord')
STAFF_HUB_GUILD_ID = 1041450125391835186

# Away role IDs (all 3)
LOOT_ROUTE_AWAY_ROLE_ID = 1495685790452420608
SURGE_ROUTE_AWAY_ROLE_ID = 1513082353986306048
GENERAL_STAFF_AWAY_ROLE_ID = 1231259676457566250


class AwayRoleSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.away_role_sync_loop.start()

    async def cog_unload(self):
        self.away_role_sync_loop.cancel()

    @tasks.loop(hours=12)
    async def away_role_sync_loop(self):
        """Every 12 hours: sync away role members to database."""
        try:
            guild = self.bot.get_guild(STAFF_HUB_GUILD_ID)
            if not guild:
                logger.warning(f"[AWAY_SYNC] Guild {STAFF_HUB_GUILD_ID} not found")
                return

            # Get all 3 away roles
            loot_away_role = guild.get_role(LOOT_ROUTE_AWAY_ROLE_ID)
            surge_away_role = guild.get_role(SURGE_ROUTE_AWAY_ROLE_ID)
            staff_away_role = guild.get_role(GENERAL_STAFF_AWAY_ROLE_ID)

            if not loot_away_role and not surge_away_role and not staff_away_role:
                logger.warning(f"[AWAY_SYNC] No away roles found")
                return

            # Collect users per role
            loot_away_users = set()
            surge_away_users = set()
            staff_away_users = set()

            if loot_away_role:
                loot_away_users = {m.id for m in loot_away_role.members if not m.bot}
                logger.info(f"[AWAY_SYNC] Loot away: {len(loot_away_users)} users")
            if surge_away_role:
                surge_away_users = {m.id for m in surge_away_role.members if not m.bot}
                logger.info(f"[AWAY_SYNC] Surge away: {len(surge_away_users)} users")
            if staff_away_role:
                staff_away_users = {m.id for m in staff_away_role.members if not m.bot}
                logger.info(f"[AWAY_SYNC] Staff away: {len(staff_away_users)} users")

            # ═══ LOOT ROUTE AWAY ═══
            await self._sync_role_to_db(
                database,
                loot_away_users,
                'loot',
                'set_away_return_date',
                'delete_away_return_date',
                'get_all_away_return_dates'
            )

            # ═══ SURGE ROUTE AWAY ═══
            import database_surge as sdb
            await self._sync_role_to_db(
                sdb,
                surge_away_users,
                'surge',
                'set_surge_away_return_date',
                'delete_surge_away_return_date',
                'get_all_surge_away_return_dates'
            )

            # ═══ STAFF AWAY → STAFF DB ═══
            await self._sync_role_to_db(
                database,
                staff_away_users,
                'staff',
                'set_staff_away_return_date',
                'delete_staff_away_return_date',
                'get_all_staff_away_return_dates'
            )

        except Exception as e:
            logger.error(f"[AWAY_SYNC] Loop error: {e}", exc_info=True)

    async def _sync_role_to_db(self, db, users, label, add_fn, remove_fn, get_fn):
        """Helper: sync a set of users to a database."""
        try:
            await_list = await getattr(db, get_fn)()
            perm_users = {int(a['user_id']) for a in await_list if not a.get('return_date')}

            to_add = users - perm_users
            for uid in to_add:
                try:
                    await getattr(db, add_fn)(uid, None)
                    logger.info(f"[AWAY_SYNC] {label}: Added {uid}")
                except Exception as e:
                    logger.error(f"[AWAY_SYNC] {label}: Error adding {uid}: {e}")

            to_remove = perm_users - users
            for uid in to_remove:
                try:
                    await getattr(db, remove_fn)(uid)
                    logger.info(f"[AWAY_SYNC] {label}: Removed {uid}")
                except Exception as e:
                    logger.error(f"[AWAY_SYNC] {label}: Error removing {uid}: {e}")

            logger.info(f"[AWAY_SYNC] {label} sync: +{len(to_add)}, -{len(to_remove)}")
        except Exception as e:
            logger.error(f"[AWAY_SYNC] {label} error: {e}", exc_info=True)

    @away_role_sync_loop.before_loop
    async def before_away_role_sync_loop(self):
        """Wait for bot to be ready before starting the loop."""
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(AwayRoleSync(bot))
