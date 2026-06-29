"""
tasks/web_shop_processor.py

Bot-side processor for web shop redemptions queued by web_api.py.
Flask inserts pending rows in web_redemptions; this cog picks them up,
runs the full fulfilment logic (deduct WP, apply roles, ping Management),
and marks each row completed or failed.

Flask never calls add_wave_points or touches Discord — this cog does all of that.
"""
import json
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import database
from tasks.wave_points import get_wave_points, add_wave_points

VBUCKS_REDEEM_LOG_CHANNEL_ID = 1470639550534778882  # same as >vbucksredeem bot command
WP_PER_100_VBUCKS = 50  # fixed: 50 WP = 100 VBucks

logger = logging.getLogger('discord')

# ── Shop catalogue (must match web_api.py _ALL_PRIZES + wave_points_commands.py) ──

STAFF_PROMOTION_ROLES = {
    "Trial Staff → Staff":          "Staff",
    "Staff → Support":              "Support",
    "Support → Senior Support":     "Senior Support",
    "Senior Support → Admin":       "Admin",
    "Admin → Head Admin":           "Head Admin",
    "Head Admin → Management":      "Management",
    "Instant Management":           "Management",
}
PERKS_ROLES = {
    "Wave Contributor": "Wave Contributor",
    "Paid Priority":    "Paid Priority",
    "VIP":              "VIP",
}
ALL_GUILD_IDS = [988564962802810961, 1041450125391835186, 971731167621574666]
PERKS_GUILD_IDS = [988564962802810961, 971731167621574666]
MANAGEMENT_NOTIFY_CHANNEL_ID = 1041584423264596009
MANAGEMENT_ROLE_NAME = "Management"


async def _apply_role_to_guilds(bot, user_id: int, role_name: str, guild_ids: list) -> list[tuple[str, str]]:
    results = []
    for gid in guild_ids:
        guild = bot.get_guild(gid)
        if not guild:
            results.append((f"Guild {gid}", "not found"))
            continue
        member = guild.get_member(user_id)
        if not member:
            results.append((guild.name, "not a member"))
            continue
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            results.append((guild.name, f"role '{role_name}' not found"))
            continue
        if role in member.roles:
            results.append((guild.name, "already had role"))
            continue
        try:
            await member.add_roles(role, reason="Wave Points web shop redemption")
            results.append((guild.name, "applied"))
        except discord.Forbidden:
            results.append((guild.name, "missing permissions"))
        except Exception as exc:
            results.append((guild.name, str(exc)))
    return results


async def _notify_management(bot, user_id: int, prize: str, cost: int, category: str):
    try:
        channel = bot.get_channel(MANAGEMENT_NOTIFY_CHANNEL_ID)
        if not channel:
            return
        mgmt_role = discord.utils.get(channel.guild.roles, name=MANAGEMENT_ROLE_NAME)
        ping = mgmt_role.mention if mgmt_role else "@Management"
        emoji = {"promotion": "📈", "perk": "🎖️", "ingame": "🗺️"}.get(category, "🎁")
        embed = discord.Embed(
            title=f"{emoji} Wave Points Web Shop Redemption",
            description=f"<@{user_id}> redeemed **{prize}** via the Staff Hub website.",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Prize", value=prize, inline=True)
        embed.add_field(name="Cost",  value=f"{cost:,} pts", inline=True)
        embed.add_field(name="User",  value=f"<@{user_id}> (`{user_id}`)", inline=True)
        embed.set_footer(text="Wave Points Web Shop")
        await channel.send(content=ping, embed=embed)
    except Exception as exc:
        logger.error(f"[WebShop] management notify failed: {exc}")


async def _process_one(bot, row) -> dict:
    """Fulfil a single pending redemption. Returns result dict."""
    rid      = row['id']
    user_id  = int(row['user_id'])
    prize    = row['prize']
    cost     = int(row['cost'])

    balance = await get_wave_points(user_id)
    if balance < cost:
        return {'success': False, 'message': f"Insufficient balance ({balance:,} pts, need {cost:,})."}

    new_balance = await add_wave_points(user_id, -cost, bot=bot, reason=f"Shop: {prize}")

    if prize in STAFF_PROMOTION_ROLES:
        role_name = STAFF_PROMOTION_ROLES[prize]
        if prize == "Head Admin → Management":
            await _notify_management(bot, user_id, prize, cost, 'promotion')
            return {
                'success': True,
                'new_balance': new_balance,
                'message': "Redemption submitted! Management will verify your tenure and apply the role.",
                'auto_role': False,
            }
        results = await _apply_role_to_guilds(bot, user_id, role_name, ALL_GUILD_IDS)
        await _notify_management(bot, user_id, prize, cost, 'promotion')
        lines = "; ".join(f"{g}: {s}" for g, s in results)
        return {'success': True, 'new_balance': new_balance, 'message': lines, 'auto_role': True}

    elif prize in PERKS_ROLES:
        role_name = PERKS_ROLES[prize]
        gids = [988564962802810961] if prize == "Paid Priority" else PERKS_GUILD_IDS
        results = await _apply_role_to_guilds(bot, user_id, role_name, gids)
        await _notify_management(bot, user_id, prize, cost, 'perk')
        lines = "; ".join(f"{g}: {s}" for g, s in results)
        return {'success': True, 'new_balance': new_balance, 'message': lines, 'auto_role': True}

    else:
        # In-game rewards and Paid Promotions — manual fulfilment
        await _notify_management(bot, user_id, prize, cost, 'ingame')
        return {
            'success': True,
            'new_balance': new_balance,
            'message': "Redemption logged! Management will contact you to arrange your reward.",
            'auto_role': False,
        }


async def _process_vbucks_redemption(bot, row) -> dict:
    """Charge Wave Points for VBucks prize, DM user, log to channel."""
    user_id = int(row['user_id'])
    amount = int(row['amount'])  # VBucks amount being redeemed

    cost_wp = amount * WP_PER_100_VBUCKS // 100

    balance_wp = await get_wave_points(user_id)
    if balance_wp < cost_wp:
        return {'success': False, 'message': f"Insufficient Wave Points ({balance_wp:,} pts, need {cost_wp:,})."}

    new_balance = await add_wave_points(user_id, -cost_wp, bot=bot, reason=f"VBucks shop: {amount:,} VB")

    # DM the user with redemption instructions
    try:
        user = await bot.fetch_user(user_id)
        dm_msg = (
            f"# 🎉 VBucks Redemption Successful!\n\n"
            f"You redeemed **{amount:,} VBucks** via the Staff Hub!\n\n"
            f"💎 Cost: **{cost_wp:,} Wave Points** (New balance: {new_balance:,} pts)\n\n"
            f"🎁 How to Claim Your VBucks:\n"
            f"1. Join the rewards server: https://discord.gg/SufksxcGDy\n"
            f"2. Upon joining, drop your Epic Games tag in the designated channel\n"
            f"3. Management will process your reward!\n"
            f"4. Check the pinned message for more info\n\n"
            f"Thank you for your hard work and dedication!"
        )
        await user.send(dm_msg)
    except Exception as exc:
        logger.warning(f"[WebShopVB] Could not DM {user_id}: {exc}")

    # Log to redeem channel
    try:
        channel = bot.get_channel(VBUCKS_REDEEM_LOG_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="💎 VBucks Redeemed (Web Shop)",
                description=f"<@{user_id}> redeemed **{amount:,} VBucks** via the Staff Hub.",
                color=discord.Color.purple(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="💸 Wave Points Spent", value=f"**{cost_wp:,}** WP", inline=False)
            embed.add_field(name="💰 WP Balance After", value=f"**{new_balance:,}** pts", inline=False)
            await channel.send(embed=embed)
    except Exception as exc:
        logger.warning(f"[WebShopVB] Could not log to channel: {exc}")

    return {'success': True, 'new_balance': new_balance, 'message': f"Redeemed {amount:,} VBucks! Check your DMs for instructions."}


class WebShopProcessor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._loop.start()
        self._vbucks_loop.start()

    def cog_unload(self):
        self._loop.cancel()
        self._vbucks_loop.cancel()

    @tasks.loop(seconds=5)
    async def _loop(self):
        try:
            pool = await database.get_pool()
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT * FROM web_redemptions WHERE status='pending' ORDER BY created_at ASC LIMIT 10"
                ) as cur:
                    rows = await cur.fetchall()

            for row in rows:
                rid = row['id']
                # Mark processing to avoid double-pick
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE web_redemptions SET status='processing' WHERE id=? AND status='pending'",
                        (rid,),
                    )
                    await db.commit()
                try:
                    result = await _process_one(self.bot, row)
                    status = 'completed' if result.get('success') else 'failed'
                except Exception as exc:
                    logger.error(f"[WebShop] error processing {rid}: {exc}")
                    result = {'success': False, 'message': str(exc)}
                    status = 'failed'
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE web_redemptions SET status=?, result_json=?, processed_at=? WHERE id=?",
                        (status, json.dumps(result), datetime.now(timezone.utc).isoformat(), rid),
                    )
                    await db.commit()
                logger.info(f"[WebShop] {rid} → {status}: {result.get('message','')[:80]}")
        except Exception as exc:
            logger.error(f"[WebShop] processor loop error: {exc}")

    @_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=5)
    async def _vbucks_loop(self):
        try:
            pool = await database.get_pool()
            # Ensure table exists (idempotent)
            async with pool.acquire() as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS web_vbucks_redemptions (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        amount INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        result_json TEXT,
                        created_at TEXT NOT NULL,
                        processed_at TEXT
                    )
                """)
                await db.commit()
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT * FROM web_vbucks_redemptions WHERE status='pending' ORDER BY created_at ASC LIMIT 10"
                ) as cur:
                    rows = await cur.fetchall()

            for row in rows:
                rid = row['id']
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE web_vbucks_redemptions SET status='processing' WHERE id=? AND status='pending'",
                        (rid,),
                    )
                    await db.commit()
                try:
                    result = await _process_vbucks_redemption(self.bot, row)
                    status = 'completed' if result.get('success') else 'failed'
                except Exception as exc:
                    logger.error(f"[WebShopVB] error processing {rid}: {exc}")
                    result = {'success': False, 'message': str(exc)}
                    status = 'failed'
                async with pool.acquire() as db:
                    await db.execute(
                        "UPDATE web_vbucks_redemptions SET status=?, result_json=?, processed_at=? WHERE id=?",
                        (status, json.dumps(result), datetime.now(timezone.utc).isoformat(), rid),
                    )
                    await db.commit()
                logger.info(f"[WebShopVB] {rid} → {status}: {result.get('message','')[:80]}")
        except Exception as exc:
            logger.error(f"[WebShopVB] processor loop error: {exc}")

    @_vbucks_loop.before_loop
    async def _before_vbucks(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(WebShopProcessor(bot))
