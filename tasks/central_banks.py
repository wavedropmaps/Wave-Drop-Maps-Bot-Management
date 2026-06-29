"""
Central Bank - tasks/central_banks.py

Resolves matured bonds and pays tiered daily APR interest at midnight UTC.
APR tiers: ≥1000 WP → 15%  |  ≥500 WP → 10%  |  ≥250 WP → 7%  |  ≥50 WP → 5%
"""

import asyncio
import logging
import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import database
from tasks.wave_points import add_wave_points

logger = logging.getLogger('discord')

# ── APR tiers (checked highest-first) ─────────────────────────────────────────
APR_TIERS = [
    (1000, 15),
    (500,  10),
    (250,   7),
    (50,    5),
]


async def run_interest_pass(bot):
    """Pay daily APR interest to all qualifying users (≥50 WP)."""
    try:
        import main as _main
        rows = await database.get_all_wave_points_for_interest()
        paid = 0
        for row in rows:
            user_id = row['user_id']
            balance = row['points']

            apr = 0
            for threshold, rate in APR_TIERS:
                if balance >= threshold:
                    apr = rate
                    break

            if apr == 0:
                continue

            payout = round(balance * apr / 100 / 365)
            if payout == 0:
                continue

            await add_wave_points(user_id, payout, bot=bot, reason=f"Daily interest ({apr}% APR)")
            paid += 1

            try:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                if user:
                    await _main._original_user_send(
                        user, f"💰 Daily interest: +{payout} WP ({apr}% APR)"
                    )
            except Exception as dm_err:
                logger.warning(f"⚠️ Could not DM interest to {user_id}: {dm_err}")

        logger.info(f"💰 Interest pass complete — paid {paid} user(s)")
    except Exception as e:
        logger.error(f"❌ Interest pass error: {e}")


# ==================== COG (daily loop) ====================

class CentralBankTask(commands.Cog):
    """Background task cog: resolves matured bonds and pays daily APR interest at midnight UTC."""

    def __init__(self, bot):
        self.bot = bot
        self._daily_bond_check.start()

    def cog_unload(self):
        self._daily_bond_check.cancel()

    @tasks.loop(hours=24)
    async def _daily_bond_check(self):
        try:
            import database_economy
            from tasks.economy_sync import compile_economy_data
            from tasks.staff_hub_writer import push_economy_dashboard_to_github

            matured = await database_economy.resolve_matured_bonds()
            if matured:
                for b in matured:
                    user_id = b['user_id']
                    payout = b['amount_payout']
                    await add_wave_points(user_id, payout, bot=self.bot, reason="Bond maturity payout")
                    logger.info(f"🏦 Bond matured for user {user_id}: Paid {payout} WP")

                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                    if user:
                        embed = discord.Embed(
                            title="🏦 Bank Bond Matured!",
                            description=f"Your Bank Bond has matured. **{payout} Wave Points** have been deposited into your account!",
                            color=0x00ff88
                        )
                        await user.send(embed=embed)

                logger.info(f"🏦 {len(matured)} bond(s) matured — updating leaderboard...")
                economy_data = await compile_economy_data(bot=self.bot)
                success = await push_economy_dashboard_to_github(economy_data)
                if success:
                    logger.info(f"✅ Leaderboard updated with bond yield data")
                else:
                    logger.warning(f"⚠️  Failed to update leaderboard after bond maturity")

        except Exception as e:
            logger.error(f"❌ Daily bond check error: {e}")

        await run_interest_pass(self.bot)

    @_daily_bond_check.before_loop
    async def _before_daily_bond_check(self):
        """Sleep until 00:05 UTC tomorrow before starting the 24h loop."""
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        )
        sleep_seconds = (tomorrow_midnight - now).total_seconds()
        logger.info(
            f"💤 Bond check task sleeping {sleep_seconds/3600:.1f}h "
            f"until {tomorrow_midnight.strftime('%Y-%m-%d %H:%M')} UTC"
        )
        await asyncio.sleep(sleep_seconds)


async def setup(bot):
    cog = CentralBankTask(bot)
    await bot.add_cog(cog)
    logger.info("✅ CentralBankTask cog loaded")
