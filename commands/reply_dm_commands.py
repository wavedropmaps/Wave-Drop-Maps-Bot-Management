"""
Reply DM Commands
Configure the channel, staff role, log channel, and auto-delete for the reply-DM system.
"""

import discord
from discord.ext import commands
from core.cache import config_cache
import logging

logger = logging.getLogger('discord')


class ReplyDMCommands(commands.Cog):
    """Setup commands for the reply-DM system"""

    def __init__(self, bot):
        self.bot = bot

    @commands.group(name='replydm')
    @commands.has_any_role('007', '+', 'Management')
    async def replydm(self, ctx):
        pass

    @replydm.command(name='enable')
    @commands.has_any_role('007', '+', 'Management')
    async def enable(self, ctx):
        """Enable the reply-DM system for this server."""
        await config_cache.update_guild_config(ctx.guild.id, {'reply_dm_enabled': True})
        await ctx.send(embed=discord.Embed(
            title="✅ Reply DM Enabled",
            description=(
                "Staff/bot replies in the configured channel will now DM the original message author.\n\n"
                "Make sure you have set:\n"
                "`>replydm setchannel #channel`\n"
                "`>replydm setrole @Role`"
            ),
            color=discord.Color.green()
        ))
        logger.info(f"[ReplyDM] Guild {ctx.guild.id}: system ENABLED")

    @replydm.command(name='disable')
    @commands.has_any_role('007', '+', 'Management')
    async def disable(self, ctx):
        """Disable the reply-DM system for this server."""
        await config_cache.update_guild_config(ctx.guild.id, {'reply_dm_enabled': False})
        await ctx.send(embed=discord.Embed(
            title="🛑 Reply DM Disabled",
            description="The reply-DM system is now **off** for this server. No DMs will be sent until re-enabled.",
            color=discord.Color.red()
        ))
        logger.info(f"[ReplyDM] Guild {ctx.guild.id}: system DISABLED")

    @replydm.command(name='setchannel')
    @commands.has_any_role('007', '+', 'Management')
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel to monitor for staff replies."""
        await config_cache.update_guild_config(ctx.guild.id, {'reply_dm_channel_id': channel.id})
        await ctx.send(embed=discord.Embed(
            title="✅ Monitored Channel Set",
            description=f"Now watching {channel.mention} for staff replies.",
            color=discord.Color.green()
        ))
        logger.info(f"[ReplyDM] Guild {ctx.guild.id}: monitored channel set to {channel.id}")

    @replydm.command(name='setrole')
    @commands.has_any_role('007', '+', 'Management')
    async def set_role(self, ctx, *roles: discord.Role):
        """Set the role(s) whose replies trigger a DM. Can specify multiple roles."""
        if not roles:
            await ctx.send("❌ Please provide at least one role.")
            return
        role_ids = [r.id for r in roles]
        role_names = ", ".join(f"**{r.name}**" for r in roles)
        await config_cache.update_guild_config(ctx.guild.id, {'reply_dm_staff_role_ids': role_ids})
        await ctx.send(embed=discord.Embed(
            title="✅ Staff Roles Set",
            description=f"Replies from members with {role_names} will trigger DMs.",
            color=discord.Color.green()
        ))
        logger.info(f"[ReplyDM] Guild {ctx.guild.id}: staff roles set to {role_ids}")

    @replydm.command(name='toggleautodelete')
    @commands.has_any_role('007', '+', 'Management')
    async def toggle_autodelete(self, ctx):
        """Toggle auto-delete on/off."""
        config  = await config_cache.get_guild_config(ctx.guild.id)
        new_val = not config.get('reply_dm_autodelete_enabled', False)
        await config_cache.update_guild_config(ctx.guild.id, {'reply_dm_autodelete_enabled': new_val})
        await ctx.send(embed=discord.Embed(
            title=f"Auto-Delete {'✅ Enabled' if new_val else '❌ Disabled'}",
            description=(
                "When staff replies and the DM is sent:\n"
                "• Original member message + staff reply deleted after **5 minutes**\n"
                "• **All of that member's earlier messages in the channel are also deleted along with the pair**\n"
                "• Unreplied member messages deleted after **12 hours**\n"
                "• ⭐ **Pinned messages are NEVER deleted**\n"
                "Timers survive bot restarts."
            ) if new_val else "Auto-delete is now **disabled**.",
            color=discord.Color.green() if new_val else discord.Color.red()
        ))
        logger.info(f"[ReplyDM] Guild {ctx.guild.id}: autodelete set to {new_val}")

    @replydm.command(name='status')
    @commands.has_any_role('007', '+', 'Management')
    async def status(self, ctx):
        """Show live reply-DM status: queue depth, active delete timers."""
        guild_config = await config_cache.get_guild_config(ctx.guild.id)
        channel_id   = guild_config.get('reply_dm_channel_id')
        duty_cog     = ctx.bot.cogs.get('ReplyDMDuty')
        channel      = ctx.guild.get_channel(channel_id) if channel_id else None

        embed = discord.Embed(
            title=f"📊 Reply DM Status — {ctx.guild.name}",
            color=discord.Color.blurple()
        )

        queue_depth = duty_cog._dm_queue.qsize() if duty_cog else 0
        embed.add_field(name="DM Queue", value=f"{queue_depth} pending", inline=True)

        delete_timers = len(duty_cog._msg_delete_tasks) if duty_cog else 0
        embed.add_field(name="3-Min Delete Timers", value=str(delete_timers), inline=True)

        expiry_timers = len(duty_cog._unreplied_expiry_tasks) if duty_cog else 0
        embed.add_field(name="12-Hour Expiry Timers", value=str(expiry_timers), inline=True)

        staff_mention_timers = len(duty_cog._staff_mention_delete_tasks) if duty_cog else 0
        embed.add_field(name="10-Min Staff Mention Timers", value=str(staff_mention_timers), inline=True)

        embed.set_footer(text=f"Channel: #{channel.name}" if channel else "No channel configured")
        await ctx.send(embed=embed)

    @replydm.command(name='config')
    @commands.has_any_role('007', '+', 'Management')
    async def config(self, ctx):
        """View the current reply-DM configuration for this server."""
        guild_config = await config_cache.get_guild_config(ctx.guild.id)

        channel_id = guild_config.get('reply_dm_channel_id')
        role_ids   = guild_config.get('reply_dm_staff_role_ids', [])
        autodelete = guild_config.get('reply_dm_autodelete_enabled', False)

        embed = discord.Embed(
            title=f"⚙️ Reply DM Config — {ctx.guild.name}",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="Monitored Channel",
            value=f"<#{channel_id}>" if channel_id else "Not set",
            inline=False
        )
        staff_roles_str = " ".join(f"<@&{rid}>" for rid in role_ids) if role_ids else "Not set"
        embed.add_field(
            name="Staff Roles",
            value=staff_roles_str,
            inline=False
        )
        embed.add_field(
            name="Auto-Delete",
            value=(
                "✅ Enabled\n"
                "• Replied pair (original + staff reply) → deleted 5 min after DM sent\n"
                "• **All of that member's earlier messages in the channel are deleted at the same time**\n"
                "• Unreplied member messages → deleted after 12 hours\n"
                "• ⭐ **Pinned messages are NEVER deleted**"
            ) if autodelete else "❌ Disabled",
            inline=False
        )
        embed.set_footer(text=">replydm setchannel | setrole | toggleautodelete | status")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ReplyDMCommands(bot))
    logger.info("✅ ReplyDMCommands cog loaded")
