"""
Central Bank Commands - commands/central_bank_commands.py

Management/Administrator-only Discord commands for viewing and controlling
the central bank reserves.

Interest and conversion-fee systems removed (economy unification to Wave Points).
Bonds and lottery remain active.

Commands:
  >bank                              — view reserves
  >bankinject <user> [pts]           — inject Wave Points from reserves to a user
  >bankbroadcast [pts]               — spread Wave Points reserves evenly to ALL users with a balance
  >banksetreserves <pts>             — admin only: manually set Wave Points reserve amount (emergency use)

Access control:
  Most commands require the 'Management', '007', or '+' role, OR Administrator permission.
  >banksetreserves requires Administrator only.
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import logging

import database
import database_economy
from core.helpers import create_error_embed

logger = logging.getLogger('discord')

MANAGEMENT_ROLES = ('Management', '007', '+')


def is_bank_admin():
    """Check: user is administrator OR has a management role."""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        role_names = {r.name for r in ctx.author.roles}
        if role_names & set(MANAGEMENT_ROLES):
            return True
        raise commands.CheckFailure("You need **Administrator** or a **Management** role to use bank commands.")
    return commands.check(predicate)


class CentralBankCommands(commands.Cog):
    """Central bank management commands."""

    def __init__(self, bot):
        self.bot = bot

    # ==================== >bank ====================

    @commands.command(name='bank', aliases=['centralbank', 'bankreserves'])
    @is_bank_admin()
    async def bank_status(self, ctx):
        """
        View the current state of the central bank.
        Usage: >bank
        """
        try:
            bank = await database.get_central_bank()

            embed = discord.Embed(
                title="🏦 Central Bank",
                description="Current reserves",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="🌊 Wave Points Reserves", value=f"**{bank['reserves_points']:,}** pts",    inline=True)
            embed.add_field(name="💎 VBucks Reserves",      value=f"**{bank['reserves_vbucks']:,}** VBucks", inline=True)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in bank command: {e}")
            await ctx.send(embed=create_error_embed("Bank Error", str(e)))

    # ==================== >bankinject ====================

    @commands.command(name='bankinject', aliases=['inject', 'bankgive'])
    @is_bank_admin()
    async def bank_inject(self, ctx, user: discord.Member, amount: int = 0, reserve_type: str = 'points'):
        """
        Inject Wave Points or VBucks from reserves to a specific user.
        VBucks are always sent to the user's main wallet.
        Usage: >bankinject @User 50            — give 50 Wave Points from WP reserves
               >bankinject @User 800 vbucks    — give 800 VBucks from VBucks reserves (→ main wallet)
               >bankinject @User 50 points     — explicitly give Wave Points
        """
        try:
            if amount <= 0:
                await ctx.send(embed=create_error_embed("Invalid Amount", "Specify a positive amount to inject."))
                return

            rtype = reserve_type.lower().strip()
            if rtype in ('vb', 'vbucks', 'v'):
                rtype = 'vbucks'
            elif rtype in ('pts', 'points', 'wp', 'wavepoints', 'p'):
                rtype = 'points'
            else:
                await ctx.send(embed=create_error_embed(
                    "Invalid Reserve Type",
                    "Use `points` (Wave Points) or `vbucks` (VBucks).\n"
                    "Example: `>bankinject @User 100 vbucks`"
                ))
                return

            bank = await database.get_central_bank()

            if rtype == 'vbucks':
                if bank['reserves_vbucks'] < amount:
                    await ctx.send(embed=create_error_embed(
                        "Insufficient VBucks Reserves",
                        f"Only **{bank['reserves_vbucks']:,}** VBucks in reserves. Cannot inject **{amount:,}**."
                    ))
                    return
                await database.inject_vbucks_to_user(user.id, amount)
                bank_after = await database.get_central_bank()
                embed = discord.Embed(
                    title="🏦 VBucks Injected",
                    description=f"💎 **{amount:,}** VBucks → {user.mention}'s **main wallet**",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(
                    name="📊 Reserves After",
                    value=f"💎 VBucks: **{bank_after['reserves_vbucks']:,}**\n🌊 Points: **{bank_after['reserves_points']:,}**",
                    inline=False
                )
                logger.info(f"🏦 Injected {amount} VBucks to {user} (main wallet) by {ctx.author}")

            else:
                if bank['reserves_points'] < amount:
                    await ctx.send(embed=create_error_embed(
                        "Insufficient Wave Points Reserves",
                        f"Only **{bank['reserves_points']:,}** Wave Points in reserves. Cannot inject **{amount:,}**."
                    ))
                    return
                await database.inject_points_to_user(user.id, amount)
                bank_after = await database.get_central_bank()
                embed = discord.Embed(
                    title="🏦 Wave Points Injected",
                    description=f"🌊 **{amount:,}** Wave Points → {user.mention}'s balance",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(
                    name="📊 Reserves After",
                    value=f"🌊 Points: **{bank_after['reserves_points']:,}**\n💎 VBucks: **{bank_after['reserves_vbucks']:,}**",
                    inline=False
                )
                logger.info(f"🏦 Injected {amount} WP to {user} by {ctx.author}")

            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"Injected by {ctx.author}")
            await ctx.send(embed=embed)

        except ValueError as e:
            await ctx.send(embed=create_error_embed("Injection Failed", str(e)))
        except Exception as e:
            logger.error(f"❌ Error in bankinject: {e}")
            await ctx.send(embed=create_error_embed("Injection Error", str(e)))

    # ==================== >bankbroadcast ====================

    @commands.command(name='bankbroadcast', aliases=['broadcast', 'injectall'])
    @is_bank_admin()
    async def bank_broadcast(self, ctx, amount: int = 0, reserve_type: str = 'points'):
        """
        Spread Wave Points or VBucks reserves evenly across all users with a Wave Points balance.
        VBucks are distributed to each user's main wallet.
        React ✅ to confirm or ❌ to cancel (30s timeout).
        Usage: >bankbroadcast 100              — split 100 Wave Points among all active users
               >bankbroadcast 1600 vbucks      — split 1600 VBucks among all active users (→ main wallets)
        """
        try:
            if amount <= 0:
                await ctx.send(embed=create_error_embed("Invalid Amount", "Specify a positive amount to broadcast."))
                return

            rtype = reserve_type.lower().strip()
            if rtype in ('vb', 'vbucks', 'v'):
                rtype = 'vbucks'
            elif rtype in ('pts', 'points', 'wp', 'wavepoints', 'p'):
                rtype = 'points'
            else:
                await ctx.send(embed=create_error_embed(
                    "Invalid Reserve Type",
                    "Use `points` (Wave Points) or `vbucks` (VBucks).\n"
                    "Example: `>bankbroadcast 1000 vbucks`"
                ))
                return

            bank = await database.get_central_bank()
            reserve_key = 'reserves_vbucks' if rtype == 'vbucks' else 'reserves_points'

            if bank[reserve_key] < amount:
                label = "VBucks" if rtype == 'vbucks' else "Wave Points"
                await ctx.send(embed=create_error_embed(
                    f"Insufficient {label} Reserves",
                    f"Only **{bank[reserve_key]:,}** {label} in reserves."
                ))
                return

            pool = await database.get_pool()
            async with pool.acquire() as db:
                async with db.execute('SELECT DISTINCT user_id FROM wave_points WHERE points > 0 AND left_at IS NULL') as cursor:
                    all_users = [row[0] for row in await cursor.fetchall()]

            if not all_users:
                await ctx.send(embed=create_error_embed("No Users", "No users found with a Wave Points balance."))
                return

            user_count   = len(all_users)
            per_user_amt = amount // user_count

            if per_user_amt == 0:
                label = "VBucks" if rtype == 'vbucks' else "Wave Points"
                await ctx.send(embed=create_error_embed(
                    "Too Small",
                    f"**{amount:,}** {label} ÷ **{user_count}** users = 0 each. Increase the amount."
                ))
                return

            total_out = per_user_amt * user_count
            emoji     = "💎" if rtype == 'vbucks' else "🌊"
            label     = "VBucks (→ main wallet)" if rtype == 'vbucks' else "Wave Points"

            confirm_embed = discord.Embed(
                title="⚠️ Confirm Broadcast",
                description=(
                    f"This will distribute {label} to **{user_count}** users:\n\n"
                    f"{emoji} **{per_user_amt:,}** each (total: **{total_out:,}**)\n\n"
                    "React ✅ to confirm or ❌ to cancel."
                ),
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            msg = await ctx.send(embed=confirm_embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == msg.id

            try:
                reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            except Exception:
                await msg.edit(embed=discord.Embed(title="⏰ Timed out", color=discord.Color.red()))
                return

            if str(reaction.emoji) == "❌":
                await msg.edit(embed=discord.Embed(title="❌ Broadcast cancelled", color=discord.Color.red()))
                return

            success = 0
            for user_id in all_users:
                try:
                    if rtype == 'vbucks':
                        await database.inject_vbucks_to_user(user_id, per_user_amt)
                    else:
                        await database.inject_points_to_user(user_id, per_user_amt)
                    success += 1
                except Exception as e:
                    logger.warning(f"⚠️ Broadcast failed for user {user_id}: {e}")

            bank_after = await database.get_central_bank()

            result_embed = discord.Embed(title="🏦 Broadcast Complete", color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
            result_embed.add_field(name="👥 Users Credited",    value=f"**{success}/{user_count}**", inline=True)
            result_embed.add_field(name=f"{emoji} Per User",    value=f"**{per_user_amt:,}** {label}", inline=True)
            result_embed.add_field(
                name="📊 Reserves After",
                value=f"🌊 Points: **{bank_after['reserves_points']:,}**\n💎 VBucks: **{bank_after['reserves_vbucks']:,}**",
                inline=False
            )
            result_embed.set_footer(text=f"Broadcast by {ctx.author}")
            await msg.edit(embed=result_embed)
            logger.info(f"🏦 Broadcast {per_user_amt} {rtype} to {success} users by {ctx.author}")

        except Exception as e:
            logger.error(f"❌ Error in bankbroadcast: {e}")
            await ctx.send(embed=create_error_embed("Broadcast Error", str(e)))

    # ==================== >banksetreserves ====================

    @commands.command(name='banksetreserves', aliases=['setreserves'])
    @commands.has_permissions(administrator=True)
    async def bank_set_reserves(self, ctx, amount: int, reserve_type: str = 'points'):
        """
        Emergency: manually set Wave Points or VBucks reserve amount (does NOT deduct from users).
        Administrator only.
        Usage: >banksetreserves 200            — set Wave Points reserves to 200
               >banksetreserves 5000 vbucks    — set VBucks reserves to 5000
        """
        try:
            if amount < 0:
                await ctx.send(embed=create_error_embed("Invalid Amount", "Reserves cannot be negative."))
                return

            rtype = reserve_type.lower().strip()
            if rtype in ('vb', 'vbucks', 'v'):
                rtype = 'vbucks'
            elif rtype in ('pts', 'points', 'wp', 'wavepoints', 'p'):
                rtype = 'points'
            else:
                await ctx.send(embed=create_error_embed(
                    "Invalid Reserve Type",
                    "Use `points` (Wave Points) or `vbucks` (VBucks).\n"
                    "Example: `>banksetreserves 5000 vbucks`"
                ))
                return

            pool = await database.get_pool()
            async with pool.acquire() as db:
                now = datetime.now(timezone.utc).isoformat()
                if rtype == 'vbucks':
                    await db.execute(
                        'UPDATE central_bank SET reserves_vbucks = ?, last_updated = ? WHERE id = 1',
                        (amount, now)
                    )
                else:
                    await db.execute(
                        'UPDATE central_bank SET reserves_points = ?, last_updated = ? WHERE id = 1',
                        (amount, now)
                    )
                await db.commit()

            bank_after = await database.get_central_bank()
            emoji = "💎" if rtype == 'vbucks' else "🌊"
            label = "VBucks" if rtype == 'vbucks' else "Wave Points"

            embed = discord.Embed(title="🏦 Reserves Set", color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
            embed.add_field(name=f"{emoji} {label} Reserves", value=f"**{amount:,}**", inline=True)
            embed.add_field(
                name="📊 All Reserves Now",
                value=f"🌊 Points: **{bank_after['reserves_points']:,}**\n💎 VBucks: **{bank_after['reserves_vbucks']:,}**",
                inline=False
            )
            embed.set_footer(text=f"Set by {ctx.author}")
            await ctx.send(embed=embed)
            logger.warning(f"🏦 {label} reserves manually set to {amount} by {ctx.author}")

        except Exception as e:
            logger.error(f"❌ Error in banksetreserves: {e}")
            await ctx.send(embed=create_error_embed("Reserve Error", str(e)))

    # ==================== >buybond ====================

    # Bond tiers: duration_days -> flat return % (paid in full for the lock period)
    BOND_TIERS = {
        7:  7.5,
        14: 15.0,
        30: 30.0,
        60: 50.0,
    }

    # ==================== >mybonds ====================


async def setup(bot):
    await bot.add_cog(CentralBankCommands(bot))
    await database.init_central_bank()
    logger.info("✅ CentralBankCommands cog loaded")
