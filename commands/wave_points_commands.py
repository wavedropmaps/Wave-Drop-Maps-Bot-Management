"""
Wave Points Commands - commands/wave_points_commands.py
All player-facing Wave Points commands:
  >wavepointshop        — show the prizes/redemption shop
  >wavepoints [user]    — check balance
  >wpset <user> <amt>   — admin: set a user's Wave Points
  >wpleaderboard        — top 20 Wave Points leaderboard
"""

import math
import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging

import database
from core.helpers import create_error_embed

# Import Wave Points DB helpers from the tasks file
from tasks.wave_points import (
    get_wave_points,
    set_wave_points,
    add_wave_points,
    get_wave_points_leaderboard,
)

logger = logging.getLogger('discord')

# ==================== SHOP PRIZES ====================
SHOP_PRIZES = {
    "Staff Promotions": [
        ("Trial Staff → Staff",          30),
        ("Staff → Support",              50),
        ("Support → Senior Support",    200),
        ("Senior Support → Admin",      350),
        ("Admin → Head Admin",          700),
        ("Head Admin → Management",     999),
        ("Instant Management",         5000),
    ],
    "Perks & Roles": [
        ("Wave Contributor",            450),
        ("Paid Priority",               400),
        ("Paid Promotions in Drop Map Announcements",          7500),
        ("Paid Promotions in Improvement Cord Announcements",  3000),
        ("VIP",                        5000),
    ],
    "In-Game Rewards": [
        ("Pro Drop Map",               700),
        ("Pro Loot Route",             400),
        ("Pro Surge Route",            200),
    ],
}

SHOP_EMOJIS = {
    "Staff Promotions": "📈",
    "Perks & Roles":    "🎖️",
    "In-Game Rewards":  "🗺️",
}

# Head Admin → Management requires 6 months minimum tenure
HA_MANAGEMENT_NOTE = (
    "⚠️ **Head Admin → Management** requires being Head Admin for **6 months**.\n"
    "⚡ **Instant Management** skips the promotion ladder — grants Management directly for **5,000 pts**."
)

# ==================== REDEMPTION CONFIG ====================

ALL_GUILD_IDS = [
    988564962802810961,
    1041450125391835186,
    971731167621574666,
]

PERKS_GUILD_IDS = [
    988564962802810961,
    971731167621574666,
]

INGAME_NOTIFY_CHANNEL_ID     = 1041584423264596009
INGAME_NOTIFY_ROLE_ID        = 1041584423264596009

# Channel where Management gets pinged for ALL redemptions
MANAGEMENT_NOTIFY_CHANNEL_ID = 1041584423264596009  # ← replace with your management channel ID
MANAGEMENT_ROLE_NAME         = "Management"

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

# Paid Announcement is a manual fulfilment (no role to assign automatically)
MANUAL_FULFILMENT_PRIZES = {"Paid Promotions in Drop Map Announcements", "Paid Promotions in Improvement Cord Announcements"}

ALL_PRIZES: dict[str, int] = {}
for _prizes in SHOP_PRIZES.values():
    for _name, _cost in _prizes:
        ALL_PRIZES[_name] = _cost


# ==================== WAVE PRIZE SELECT VIEW ====================

class WavePrizeSelectView(discord.ui.View):
    """Dropdown menu for selecting Wave Points shop prizes"""

    def __init__(self, user_id: int, user_points: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.user_points = user_points
        self.selected_prize = None

        # Create options for all prizes
        options = []
        for category, prizes in SHOP_PRIZES.items():
            emoji = SHOP_EMOJIS.get(category, "🎁")
            for prize_name, cost in prizes:
                can_afford = user_points >= cost

                label = f"{emoji} {prize_name[:80]}"
                description = f"{cost} pts"
                if not can_afford:
                    description += f" - Need {cost - user_points} more"

                options.append(discord.SelectOption(
                    label=label,
                    value=prize_name,
                    description=description[:100],
                    emoji=emoji
                ))

        select = discord.ui.Select(
            placeholder="🎁 Select a prize to redeem...",
            options=options,
            custom_id="wave_prize_select",
            min_values=1,
            max_values=1
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can select!", ephemeral=True)
            return

        self.selected_prize = interaction.data['values'][0]
        prize_cost = ALL_PRIZES.get(self.selected_prize, 0)
        if self.user_points < prize_cost:
            await interaction.response.send_message(
                f"❌ You need **{prize_cost} Wave Points** but only have **{self.user_points}**!",
                ephemeral=True
            )
            return

        self.stop()
        await interaction.response.defer()


class WavePointsCommands(commands.Cog):
    """All Wave Points commands"""

    def __init__(self, bot):
        self.bot = bot

    # ==================== SHOP ====================
    # Redemption moved to the Staff Hub website: wavedropmaps.pages.dev/economy.html


    # ==================== BALANCE ====================

    # ==================== ADMIN COMMANDS ====================

    @commands.command(name='wpset')
    @commands.has_permissions(administrator=True)
    async def wp_set(self, ctx, user: discord.Member, amount: int):
        """
        Admin: Set a user's Wave Points to an exact amount.
        Usage: >wpset @User 150
        """
        try:
            if amount < 0:
                await ctx.send(embed=create_error_embed("Invalid Amount", "Amount must be 0 or greater."))
                return

            await set_wave_points(user.id, amount)

            embed = discord.Embed(
                title="🌊 Wave Points Updated",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="👤 User",       value=user.mention,            inline=True)
            embed.add_field(name="💎 New Balance", value=f"**{amount:,} pts**", inline=True)
            embed.set_footer(text=f"Set by {ctx.author}")
            await ctx.send(embed=embed)
            logger.info(f"🛠️  Admin {ctx.author} set {user}'s Wave Points to {amount}")

        except Exception as e:
            logger.error(f"❌ Error in wpset: {e}")
            await ctx.send(embed=create_error_embed("Set Error", str(e)))

    # ==================== LEADERBOARD ====================


    # ==================== LOOT ROUTES ↔ WAVE POINTS ====================

    # ==================== PLAYER TO PLAYER TRADING ====================

    @commands.command(name='pay')
    @commands.has_any_role('Staff', 'Trial Staff', 'Loot Route Maker')
    async def pay_user(self, ctx, user: discord.Member, amount: int, currency: str):
        """Send Wave Points or VBucks to another user with a 10% tax."""
        if amount <= 0:
            return await ctx.send("❌ Amount must be positive.")
        if user.id == ctx.author.id:
            return await ctx.send("❌ You can't pay yourself.")

        currency = currency.lower()
        if currency in ['wp', 'wavepoints', 'points', 'p']:
            curr = 'wp'
            wallet = await get_wave_points(ctx.author.id)
            emoji = "🌊"
        elif currency in ['vb', 'vbucks', 'v']:
            curr = 'vb'
            wallet = await database.get_vbucks(ctx.author.id, 'main')
            emoji = "💎"
        else:
            return await ctx.send("❌ Invalid currency. Use `wp` or `vb`.")

        if wallet < amount:
            return await ctx.send(f"❌ You only have **{wallet}** {emoji}.")

        tax = max(1, math.floor(amount * 0.10))
        net = amount - tax

        pool = await database.get_pool()
        async with pool.acquire() as db:
            if curr == 'wp':
                await db.execute('UPDATE central_bank SET reserves_points = reserves_points + ? WHERE id = 1', (tax,))
            elif curr == 'vb':
                await db.execute('UPDATE central_bank SET reserves_vbucks = reserves_vbucks + ? WHERE id = 1', (tax,))
            await db.commit()

        if curr == 'wp':
            await add_wave_points(ctx.author.id, -amount, bot=self.bot, reason="P2P transfer sent")
            await add_wave_points(user.id, net, bot=self.bot, reason="P2P transfer received")
        elif curr == 'vb':
            await database.set_vbucks(ctx.author.id, 'main', wallet - amount)
            target_vb = await database.get_vbucks(user.id, 'main')
            await database.set_vbucks(user.id, 'main', target_vb + net)

        embed = discord.Embed(title="💸 Payment Sent!", color=0x00ff88)
        embed.add_field(name="Sent", value=f"**{amount}** {emoji}", inline=True)
        embed.add_field(name="10% Tax", value=f"**-{tax}** {emoji}", inline=True)
        embed.add_field(name="Received", value=f"**{net}** {emoji}", inline=True)
        embed.set_footer(text="P2P Trading Tax goes directly to the Central Bank.")
        await ctx.send(f"{user.mention}", embed=embed)


async def setup(bot):
    await bot.add_cog(WavePointsCommands(bot))
