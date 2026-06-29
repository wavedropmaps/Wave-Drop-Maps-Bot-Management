"""
Server Configuration Commands
Manage server-specific settings like channels and roles
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from core.helpers import *
from core.cache import config_cache
import logging

logger = logging.getLogger('discord')


class ServerConfig(commands.Cog):
    """Commands for server configuration"""

    def __init__(self, bot):
        self.bot = bot

    # ==================== HELPERS ====================

    async def log_config_change(self, ctx, change_description: str):
        """Log a config change to the guild's logging channel"""
        if not ctx.guild:
            return

        guild_config = await config_cache.get_guild_config(ctx.guild.id)
        log_channel_id = guild_config.get('logging_channel_id')
        if not log_channel_id:
            return

        log_channel = ctx.guild.get_channel(log_channel_id)
        if not log_channel:
            return

        embed = discord.Embed(
            title="Config Change Logged",
            description=change_description,
            color=discord.Color.orange(),
            timestamp=ctx.message.created_at
        )
        embed.set_author(
            name=f"{ctx.author} (ID: {ctx.author.id})",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else None
        )
        try:
            await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(
                f"Failed to log config change to guild {ctx.guild.id}, "
                f"channel {log_channel_id}: {e}"
            )

    # ==================== CONFIG GROUP ====================

    @commands.group(name='config', invoke_without_command=True)
    @commands.has_any_role('007', '+', 'Management')
    async def config(self, ctx):
        """
        View or edit server-specific configuration.
        Usage: >config
        Subcommands: setloggingchannel, setrequestchannel,
                     setmodlogschannel, setallowedchannels
        """
        try:
            guild_config = await config_cache.get_guild_config(ctx.guild.id)

            embed = discord.Embed(
                title=f"⚙️ Server Configuration - {ctx.guild.name}",
                description=(
                    "Configure channels for **THIS** server only.\n"
                    "`>config` - View current settings\n"
                    "`>config setloggingchannel <id>`\n"
                    "`>config setrequestchannel <id>`\n"
                    "`>config setmodlogschannel <id>`\n"
                    "`>config setallowedchannels <id...>`"
                ),
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            # Request channel
            request_ch = ctx.guild.get_channel(guild_config.get('request_channel_id'))
            embed.add_field(
                name="📝 Request Channel",
                value=request_ch.mention if request_ch else (
                    str(guild_config.get('request_channel_id'))
                    if guild_config.get('request_channel_id') else "❌ Not set"
                ),
                inline=False
            )

            # Modlogs channel
            modlogs_ch = ctx.guild.get_channel(guild_config.get('modlogs_channel_id'))
            embed.add_field(
                name="🔨 Modlogs Channel",
                value=modlogs_ch.mention if modlogs_ch else (
                    str(guild_config.get('modlogs_channel_id'))
                    if guild_config.get('modlogs_channel_id') else "❌ Not set"
                ),
                inline=False
            )

            # Logging channel
            logging_ch = ctx.guild.get_channel(guild_config.get('logging_channel_id'))
            embed.add_field(
                name="📋 Logging Channel",
                value=logging_ch.mention if logging_ch else (
                    str(guild_config.get('logging_channel_id'))
                    if guild_config.get('logging_channel_id') else "❌ Not set"
                ),
                inline=False
            )

            # Allowed command channels
            allowed = guild_config.get('allowed_command_channels') or []
            if allowed:
                mentions = []
                for ch_id in allowed:
                    ch = ctx.guild.get_channel(ch_id)
                    mentions.append(ch.mention if ch else str(ch_id))
                allowed_value = ", ".join(mentions)
            else:
                allowed_value = "❌ Not set"
            embed.add_field(
                name="✅ Allowed Command Channels",
                value=allowed_value,
                inline=False
            )

            # Global dates
            global_dates = await config_cache.get_global_dates()
            start_date = global_dates.get('start_date', 'Not set')
            end_date = global_dates.get('end_date', 'Not set')
            embed.add_field(
                name="📅 Global Dates",
                value=f"**Start:** {start_date}\n**End:** {end_date}",
                inline=False
            )

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in config command: {e}")
            await ctx.send(embed=create_error_embed(
                "Configuration Error",
                f"Failed to display config: {str(e)}"
            ))

    # ==================== CONFIG SUBCOMMANDS ====================

    @config.command(name='setloggingchannel', help='Set the logging channel for config changes.')
    @commands.has_any_role('007', '+', 'Management')
    async def set_logging_channel(self, ctx, channel_id: int):
        """
        Set the logging channel for config changes.
        Usage: >config setloggingchannel <id>
        """
        try:
            guild_name = ctx.guild.name
            guild_config = await config_cache.get_guild_config(ctx.guild.id)

            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                return await ctx.send(embed=create_error_embed(
                    "Invalid Channel",
                    f"Channel ID `{channel_id}` does not exist in **{guild_name}**.",
                    "**How to get a channel ID:**\n1. Right-click a channel\n2. Click 'Copy Channel ID'"
                ))

            if not isinstance(channel, discord.TextChannel):
                return await ctx.send(embed=create_error_embed(
                    "Invalid Channel Type",
                    f"{channel.mention} is not a text channel."
                ))

            permissions = channel.permissions_for(ctx.guild.me)
            if not permissions.send_messages:
                await ctx.send(embed=discord.Embed(
                    title="⚠️ Missing Permissions",
                    description=f"I can't send messages in {channel.mention}. Please grant **Send Messages**.",
                    color=discord.Color.orange()
                ))
            if not permissions.embed_links:
                await ctx.send(embed=discord.Embed(
                    title="⚠️ Missing Permissions",
                    description=f"I can't embed links in {channel.mention}. Please grant **Embed Links**.",
                    color=discord.Color.orange()
                ))

            old_value = guild_config.get('logging_channel_id')
            guild_config['logging_channel_id'] = channel_id
            await config_cache.save()

            await ctx.send(embed=discord.Embed(
                title="✅ Success",
                description=f"Logging channel set to {channel.mention}",
                color=discord.Color.green()
            ))

            old_ch = ctx.guild.get_channel(old_value) if old_value else None
            await self.log_config_change(ctx,
                f"{ctx.author.mention} changed Logging Channel in **{guild_name}**\n"
                f"**Old:** {old_ch.mention if old_ch else 'Not set'}\n"
                f"**New:** {channel.mention} (`{channel_id}`)"
            )

        except Exception as e:
            logger.error(f"Error in setloggingchannel: {e}")
            await ctx.send(embed=create_error_embed("Error", str(e)))

    @config.command(name='setrequestchannel', help='Set the channel where map requests are counted from.')
    @commands.has_any_role('007', '+', 'Management')
    async def set_request_channel(self, ctx, channel_id: int):
        """
        Set the request channel.
        Usage: >config setrequestchannel <id>
        """
        try:
            guild_name = ctx.guild.name
            guild_config = await config_cache.get_guild_config(ctx.guild.id)

            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                return await ctx.send(embed=create_error_embed(
                    "Invalid Channel",
                    f"Channel ID `{channel_id}` does not exist in **{guild_name}**.",
                    "**How to get a channel ID:**\n1. Right-click a channel\n2. Click 'Copy Channel ID'"
                ))

            if not isinstance(channel, discord.TextChannel):
                return await ctx.send(embed=create_error_embed(
                    "Invalid Channel Type",
                    f"{channel.mention} is not a text channel."
                ))

            permissions = channel.permissions_for(ctx.guild.me)
            if not permissions.read_message_history:
                await ctx.send(embed=discord.Embed(
                    title="⚠️ Missing Permissions",
                    description=f"I can't read message history in {channel.mention}. Please grant **Read Message History**.",
                    color=discord.Color.orange()
                ))

            old_value = guild_config.get('request_channel_id')
            guild_config['request_channel_id'] = channel_id
            await config_cache.save()

            await ctx.send(embed=discord.Embed(
                title="✅ Success",
                description=f"Request channel set to {channel.mention}",
                color=discord.Color.green()
            ))

            old_ch = ctx.guild.get_channel(old_value) if old_value else None
            await self.log_config_change(ctx,
                f"{ctx.author.mention} changed Request Channel in **{guild_name}**\n"
                f"**Old:** {old_ch.mention if old_ch else 'Not set'}\n"
                f"**New:** {channel.mention} (`{channel_id}`)"
            )

        except Exception as e:
            logger.error(f"Error in setrequestchannel: {e}")
            await ctx.send(embed=create_error_embed("Error", str(e)))

    @config.command(name='setmodlogschannel', help='Set the Wick moderation logs channel.')
    @commands.has_any_role('007', '+', 'Management')
    async def set_modlogs_channel(self, ctx, channel_id: int):
        """
        Set the modlogs channel.
        Usage: >config setmodlogschannel <id>
        """
        try:
            guild_name = ctx.guild.name
            guild_config = await config_cache.get_guild_config(ctx.guild.id)

            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                return await ctx.send(embed=create_error_embed(
                    "Invalid Channel",
                    f"Channel ID `{channel_id}` does not exist in **{guild_name}**.",
                    "**How to get a channel ID:**\n1. Right-click a channel\n2. Click 'Copy Channel ID'"
                ))

            if not isinstance(channel, discord.TextChannel):
                return await ctx.send(embed=create_error_embed(
                    "Invalid Channel Type",
                    f"{channel.mention} is not a text channel."
                ))

            permissions = channel.permissions_for(ctx.guild.me)
            if not permissions.read_message_history:
                await ctx.send(embed=discord.Embed(
                    title="⚠️ Missing Permissions",
                    description=f"I can't read message history in {channel.mention}. Please grant **Read Message History**.",
                    color=discord.Color.orange()
                ))

            old_value = guild_config.get('modlogs_channel_id')
            guild_config['modlogs_channel_id'] = channel_id
            await config_cache.save()

            await ctx.send(embed=discord.Embed(
                title="✅ Success",
                description=f"Modlogs channel set to {channel.mention}",
                color=discord.Color.green()
            ))

            old_ch = ctx.guild.get_channel(old_value) if old_value else None
            await self.log_config_change(ctx,
                f"{ctx.author.mention} changed Modlogs Channel in **{guild_name}**\n"
                f"**Old:** {old_ch.mention if old_ch else 'Not set'}\n"
                f"**New:** {channel.mention} (`{channel_id}`)"
            )

        except Exception as e:
            logger.error(f"Error in setmodlogschannel: {e}")
            await ctx.send(embed=create_error_embed("Error", str(e)))

    @config.command(name='setallowedchannels', help='Set channels where this bot can respond to commands.')
    @commands.has_any_role('007', '+', 'Management')
    async def set_allowed_channels(self, ctx, *channel_ids: int):
        """
        Set the allowed command channels (space-separated IDs).
        Usage: >config setallowedchannels <id> [id2] [id3...]
        Example: >config setallowedchannels 123456789 987654321
        """
        try:
            guild_name = ctx.guild.name

            if not channel_ids:
                return await ctx.send(embed=create_error_embed(
                    "No Channels Provided",
                    "Please provide at least one channel ID.",
                    "**Example:** `>config setallowedchannels 123456789 987654321`"
                ))

            guild_config = await config_cache.get_guild_config(ctx.guild.id)

            # Validate ALL channels before saving any
            validated_channels = []
            for cid in channel_ids:
                channel = ctx.guild.get_channel(cid)
                if not channel:
                    return await ctx.send(embed=create_error_embed(
                        "Invalid Channel",
                        f"Channel ID `{cid}` does not exist in **{guild_name}**.",
                        "No changes were made. Verify all channel IDs are correct."
                    ))
                if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                    return await ctx.send(embed=create_error_embed(
                        "Invalid Channel Type",
                        f"{channel.mention} (ID: `{cid}`) is not a text or forum channel.",
                        "No changes were made. All channels must be text or forum channels."
                    ))
                validated_channels.append(channel)

            old_list = guild_config.get('allowed_command_channels') or []
            old_str = "Not set" if not old_list else ", ".join(
                ctx.guild.get_channel(ch_id).mention
                if ctx.guild.get_channel(ch_id) else str(ch_id)
                for ch_id in old_list
            )

            guild_config['allowed_command_channels'] = list(channel_ids)
            await config_cache.save()

            new_mentions = [ch.mention for ch in validated_channels]
            await ctx.send(embed=discord.Embed(
                title="✅ Success",
                description=f"Allowed command channels set to {', '.join(new_mentions)}",
                color=discord.Color.green()
            ))

            await self.log_config_change(ctx,
                f"{ctx.author.mention} changed Allowed Command Channels in **{guild_name}**\n"
                f"**Old:** {old_str}\n"
                f"**New:** {', '.join(new_mentions)}"
            )

        except Exception as e:
            logger.error(f"Error in setallowedchannels: {e}")
            await ctx.send(embed=create_error_embed("Error", str(e)))

    # ==================== LEGACY CHANNEL/ROLE COMMANDS ====================

    @commands.command(name='setchannel', help='Set a channel for a specific duty type')
    @commands.has_permissions(administrator=True)
    async def setchannel(self, ctx, channel_type: str, channel: discord.TextChannel):
        """
        Configure channels for different duty types.
        Usage: >setchannel <req/ping/uptime/logging> #channel
        """
        try:
            channel_type = channel_type.lower()
            valid_types = ['req', 'ping', 'uptime', 'logging']

            if channel_type not in valid_types:
                await ctx.send(embed=create_error_embed(
                    "Invalid Channel Type",
                    f"Please use one of: {', '.join(valid_types)}"
                ))
                return

            guild_config = await config_cache.get_guild_config(ctx.guild.id)

            channel_map = {
                'req': 'request_channel_id',
                'ping': 'ping_channel_id',
                'uptime': 'uptime_channel_id',
                'logging': 'logging_channel_id'
            }

            config_key = channel_map[channel_type]
            guild_config[config_key] = channel.id
            await config_cache.save()

            embed = discord.Embed(
                title="✅ Channel Configured",
                description=f"Successfully set {channel_type.upper()} channel",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Channel Type", value=f"📋 {channel_type.upper()}", inline=True)
            embed.add_field(name="Channel", value=channel.mention, inline=True)
            embed.set_footer(text=f"Set by {ctx.author}")
            await ctx.send(embed=embed)

            logger.info(f"{channel_type.upper()} channel set to {channel.name} in {ctx.guild.name}")

        except Exception as e:
            logger.error(f"Error in setchannel command: {e}")
            await ctx.send(embed=create_error_embed(
                "Configuration Error",
                f"Failed to set channel: {str(e)}"
            ))


async def setup(bot):
    await bot.add_cog(ServerConfig(bot))