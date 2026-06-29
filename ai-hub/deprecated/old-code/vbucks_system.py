"""
VBucks System - commands/vbucks_system.py
VBucks balance viewing and admin config commands.
Transfer/redemption commands removed — use the Staff Hub website.
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from core.helpers import create_error_embed
import database
import logging

logger = logging.getLogger('discord')


class VBucksSystem(commands.Cog):
    """VBucks viewing and configuration commands."""

    def __init__(self, bot):
        self.bot = bot

    # ==================== VIEWING COMMANDS ====================

    @commands.group(name='vbucks', help='VBucks commands', invoke_without_command=True)
    async def vbucks(self, ctx, user: discord.Member = None):
        """View VBucks balance for a user. Usage: >vbucks [user]"""
        try:
            target = user or ctx.author
            embed = discord.Embed(
                title=f"💰 VBucks Balance - {target.display_name}",
                description="Current VBucks totals",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )
            total_vbucks = await database.get_vbucks(target.id, 'main')
            embed.add_field(name="💎 VBucks Wallet", value=f"💰 **{total_vbucks:,}** VBucks", inline=False)
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in vbucks command: {e}")
            await ctx.send(embed=create_error_embed("VBucks Error", f"Failed to retrieve VBucks: {str(e)}"))

    # ==================== ADMIN COMMANDS ====================

    @commands.command(name='vbucksconfig', help='View VBucks settings')
    @commands.has_permissions(administrator=True)
    async def vbucksconfig(self, ctx):
        """View VBucks configuration and settings. Usage: >vbucksconfig"""
        try:
            embed = discord.Embed(
                title="⚙️ VBucks Configuration",
                description="Current VBucks system settings",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            pool = await database.get_pool()
            async with pool.acquire() as db:
                async with db.execute('SELECT SUM(total_vbucks) FROM vbucks') as cursor:
                    result = await cursor.fetchone()
                    total_circulation = result[0] if result and result[0] else 0
                async with db.execute('SELECT COUNT(DISTINCT user_id) FROM vbucks WHERE total_vbucks > 0') as cursor:
                    result = await cursor.fetchone()
                    active_users = result[0] if result and result[0] else 0
            embed.add_field(name="💰 Total VBucks in Circulation", value=f"**{total_circulation:,}** VBucks", inline=False)
            embed.add_field(name="👥 Active Users", value=f"**{active_users}** users with VBucks", inline=False)
            embed.add_field(name="📊 Wallet", value="💎 Single Main Wallet", inline=False)
            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in vbucksconfig command: {e}")
            await ctx.send(embed=create_error_embed("Config Error", f"Failed to retrieve configuration: {str(e)}"))


async def setup(bot):
    await bot.add_cog(VBucksSystem(bot))
