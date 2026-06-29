import discord
from discord.ext import commands, tasks
import logging
import asyncio
from datetime import datetime, timezone, timedelta

import database
import database_economy
from core.helpers import web_avatar_url
from tasks.staff_hub_writer import push_economy_dashboard_to_github

logger = logging.getLogger('discord')

async def compile_economy_data(bot=None) -> dict:
    """Compile economy data for the dashboard."""
    total_wp = await database_economy.get_total_wave_points()

    # Bank reserves
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT reserves_points, reserves_vbucks, fee_rate_pct FROM central_bank WHERE id=1') as cursor:
            row = await cursor.fetchone()

    if row:
        reserves_wp, reserves_vb, fee_rate = row
    else:
        reserves_wp, reserves_vb, fee_rate = 0, 0, 5.0

    # Top WP Holders
    leaderboard = []
    async with pool.acquire() as db:
        async with db.execute('SELECT user_id, points FROM wave_points WHERE left_at IS NULL ORDER BY points DESC LIMIT 50') as cursor:
            rows = await cursor.fetchall()
            for uid, points in rows:
                user = bot.get_user(uid) if bot else None
                name = user.display_name if user else f"User {uid}"
                leaderboard.append({
                    "name": name,
                    "user_id": str(uid),
                    "avatar_url": web_avatar_url(user.display_avatar) if user else None,
                    "wp": points,
                })

    # Top Bond Holders
    bondholders = []
    async with pool.acquire() as db:
        async with db.execute('''
            SELECT user_id, SUM(amount_locked), SUM(amount_payout), MIN(maturity_date)
            FROM bank_bonds
            WHERE status = "ACTIVE"
            GROUP BY user_id
            ORDER BY SUM(amount_locked) DESC
            LIMIT 10
        ''') as cursor:
            rows = await cursor.fetchall()
            for uid, locked, payout, next_maturity in rows:
                user = bot.get_user(uid) if bot else None
                name = user.display_name if user else f"User {uid}"
                bondholders.append({
                    "name": name,
                    "user_id": str(uid),
                    "avatar_url": web_avatar_url(user.display_avatar) if user else None,
                    "locked": locked,
                    "yield": payout - locked,
                    "maturity": next_maturity,
                })

    economy_data = {
        "central_bank": {
            "reserves_wp": reserves_wp,
            "reserves_vb": reserves_vb,
            "fee_rate": f"{fee_rate}%",
            "p2p_tax": "10.0%"
        },
        "redemptions": await database.get_all_successful_redemptions(),
        "leaderboard": leaderboard,
        "bondholders": bondholders
    }

    return economy_data


# ==================== EVENT-DRIVEN AUTO-PUSH (debounced) ====================
# Mirrors the loot route leaderboard pattern: a market trade schedules a push,
# rapid back-to-back trades collapse into a single GitHub commit. The daily
# 00:05 UTC loop stays as the backstop sync.

_debounce_economy_task = None
_debounce_economy_bot = None


async def auto_update_economy_dashboard(bot, triggered_by="trade"):
    """Automatic trigger on a market trade (>ptv, >vtp) — pushes fresh data immediately."""
    global _debounce_economy_task, _debounce_economy_bot

    if _debounce_economy_task:
        try:
            _debounce_economy_task.cancel()
        except Exception:
            pass

    _debounce_economy_bot = bot
    _debounce_economy_task = asyncio.create_task(_wait_then_push_economy(triggered_by))


async def _wait_then_push_economy(triggered_by: str):
    """Wait 10s, then compile + push (debounces a burst of trades)."""
    try:
        await asyncio.sleep(10)
        economy_data = await compile_economy_data(bot=_debounce_economy_bot)
        success = await push_economy_dashboard_to_github(economy_data)
        if success:
            logger.info(f"✅ Economy dashboard auto-pushed (trigger: {triggered_by})")
        await _refresh_route_leaderboards(_debounce_economy_bot, triggered_by)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"❌ Economy dashboard auto-push failed ({triggered_by}): {e}")


async def _refresh_route_leaderboards(bot, triggered_by: str):
    """The route leaderboards' commands card shows the live LRP/SRP→WP market
    rate, so every economy push also refreshes both leaderboard JSONs."""
    try:
        from tasks.loot_routes import auto_update_loot_route_leaderboard
        from tasks.surge_routes import auto_update_surge_route_leaderboard
        await auto_update_loot_route_leaderboard(bot, triggered_by=f"economy_{triggered_by}")
        await auto_update_surge_route_leaderboard(bot, triggered_by=f"economy_{triggered_by}")
    except Exception as e:
        logger.warning(f"⚠️ Route leaderboard refresh after economy push failed ({triggered_by}): {e}")


class EconomySync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.economy_sync_loop.start()
        self.web_bond_loop.start()

    def cog_unload(self):
        self.economy_sync_loop.cancel()
        self.web_bond_loop.cancel()

    @tasks.loop(hours=24)
    async def economy_sync_loop(self):
        """Compiles economy data into JSON and pushes to GitHub every 24h."""
        try:
            # Wait until bot is ready
            await self.bot.wait_until_ready()

            economy_data = await compile_economy_data(bot=self.bot)

            # Push to GitHub
            success = await push_economy_dashboard_to_github(economy_data)
            if success:
                logger.info("✅ Economy dashboard synced to GitHub successfully.")
            await _refresh_route_leaderboards(self.bot, "nightly_sync")

        except Exception as e:
            logger.error(f"❌ Error in economy_sync_loop: {e}")

    @economy_sync_loop.before_loop
    async def _before_economy_sync(self):
        """Always push fresh economy data on startup, then sleep until 00:05 UTC tomorrow."""
        await self.bot.wait_until_ready()

        # Always push on startup so code changes (new markets, rate changes, etc.)
        # take effect immediately rather than waiting for the next nightly sync.
        # record_market_snapshot is idempotent per UTC day so no duplicate entries.
        try:
            logger.info("💱 Startup economy sync — compiling and pushing fresh data...")
            economy_data = await compile_economy_data(bot=self.bot)
            await push_economy_dashboard_to_github(economy_data)
            await _refresh_route_leaderboards(self.bot, "startup")
        except Exception as e:
            logger.error(f"❌ Error in economy startup sync: {e}")

        now = datetime.now(timezone.utc)
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        )
        sleep_seconds = (tomorrow_midnight - now).total_seconds()
        logger.info(
            f"💱 Economy sync sleeping {sleep_seconds/3600:.1f}h "
            f"until {tomorrow_midnight.strftime('%Y-%m-%d %H:%M')} UTC"
        )
        await asyncio.sleep(sleep_seconds)

    @tasks.loop(seconds=2)
    async def web_bond_loop(self):
        try:
            pending = await database.fetch_pending_web_bonds(limit=3)
            for row in pending:
                claimed = await database.claim_web_bond(row['id'])
                if not claimed:
                    continue
                try:
                    result = await _execute_web_bond(self.bot, row)
                    await database.complete_web_bond(row['id'], result)
                    logger.info(f"✅ Web bond {row['id'][:8]} completed: {row['days']}d {row['amount']} WP")
                except Exception as e:
                    await database.fail_web_bond(row['id'], str(e))
                    logger.warning(f"⚠️ Web bond {row['id'][:8]} failed: {e}")
        except Exception as e:
            logger.error(f"❌ web_bond_loop error: {e}")

    @web_bond_loop.before_loop
    async def _before_web_bond_loop(self):
        await self.bot.wait_until_ready()


_BOND_TIERS = {7: 15.0, 14: 30.0, 30: 60.0, 60: 100.0}


async def _execute_web_bond(bot, row: dict) -> dict:
    from tasks.wave_points import get_wave_points, remove_wave_points

    user_id = int(row['user_id'])
    days    = int(row['days'])
    amount  = int(row['amount'])

    if days not in _BOND_TIERS:
        raise ValueError(f'Invalid bond duration: {days}')

    apr     = _BOND_TIERS[days]
    payout  = round(amount * (1 + apr / 100))
    interest = payout - amount

    current_wp = await get_wave_points(user_id)
    if current_wp < amount:
        raise ValueError(f'Insufficient WP: have {current_wp:,}, need {amount:,}')

    await remove_wave_points(user_id, amount, bot=bot)
    await database_economy.create_bond(user_id, amount, payout, days=days)
    await auto_update_economy_dashboard(bot, triggered_by='web_bond')

    from datetime import datetime, timezone, timedelta
    maturity_date = (datetime.now(timezone.utc) + timedelta(days=days)).strftime('%d %b %Y')
    return {
        'amount_locked': amount,
        'amount_payout': payout,
        'interest': interest,
        'apr': apr,
        'days': days,
        'maturity_date': maturity_date,
    }


async def setup(bot):
    await bot.add_cog(EconomySync(bot))
