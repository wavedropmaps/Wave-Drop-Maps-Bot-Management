import discord
from discord.ext import commands
import json
import logging

logger = logging.getLogger(__name__)


class DropMapReviewingConfig(commands.Cog):
    """Configuration commands for Drop Map Reviewing system"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='dropmapreviewing')
    @commands.has_permissions(administrator=True)
    async def drop_map_reviewing_config(self, ctx, action: str = None, *args):
        """
        Admin command to enable/disable drop map reviewing system in this server.

        Examples:
          >dropmapreviewing enable
          >dropmapreviewing disable
          >dropmapreviewing status
        """
        guild_id = ctx.guild.id

        if action == 'enable':
            embed = discord.Embed(
                title="✅ Drop Map Reviewing Enabled",
                description=f"System is now active in **{ctx.guild.name}**",
                color=discord.Color.green()
            )
            embed.add_field(name="Status", value="✅ Enabled", inline=True)
            embed.add_field(name="Guild", value=f"{ctx.guild.name} ({guild_id})", inline=True)
            embed.add_field(name="Features", value="✓ >addreviewer\n✓ >removereviewer\n✓ >newday / >addpoints / >endday / >closeday", inline=False)

            await ctx.send(embed=embed)

        elif action == 'disable':
            embed = discord.Embed(
                title="❌ Drop Map Reviewing Disabled",
                description=f"System is now disabled in **{ctx.guild.name}**",
                color=discord.Color.red()
            )
            embed.add_field(name="Status", value="❌ Disabled", inline=True)
            embed.add_field(name="Note", value="Data remains in database. Re-enable anytime.", inline=False)

            await ctx.send(embed=embed)

        elif action == 'status':
            embed = discord.Embed(
                title="🔍 Drop Map Reviewing Status",
                description=f"**{ctx.guild.name}**",
                color=discord.Color.blue()
            )
            embed.add_field(name="Status", value="✅ Enabled", inline=True)
            embed.add_field(name="Guild ID", value=f"{guild_id}", inline=True)
            embed.add_field(name="Active Commands", value=
                "➕ `>addreviewer` - Add user as reviewer\n"
                "➖ `>removereviewer` - Remove user as reviewer\n"
                "🆕 `>newday` / `>closeday` - Open / close session\n"
                "📝 `>addpoints` - Reviewer self-submits work\n"
                "🔚 `>endday` - Admin verifies submissions",
                inline=False
            )

            await ctx.send(embed=embed)

        else:
            embed = discord.Embed(
                title="⚙️ Drop Map Reviewing Configuration",
                color=discord.Color.blue()
            )
            embed.add_field(name="Setup Commands", value=
                "`>dropmapreviewing enable` — Enable system\n"
                "`>dropmapreviewing disable` — Disable system\n"
                "`>dropmapreviewing status` — Check status",
                inline=False
            )
            embed.add_field(name="Core Commands", value=
                "`>addreviewer @user` — Add reviewer\n"
                "`>removereviewer @user` — Remove reviewer\n"
                "`>newday` / `>closeday` — Open / close session\n"
                "`>addpoints` / `>endday` — Submit & verify reviews",
                inline=False
            )
            embed.add_field(name="Example Workflow", value=
                "1️⃣ `>dropmapreviewing enable` (setup)\n"
                "2️⃣ `>addreviewer @john` (add reviewers)\n"
                "3️⃣ `>newday` (open session)\n"
                "4️⃣ `>addpoints` (reviewer submits) → `>endday` (admin verifies)\n"
                "5️⃣ `>closeday` (finalize)",
                inline=False
            )

            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(DropMapReviewingConfig(bot))
