"""
Core helper functions for the Discord Staff Activity Bot
Contains all shared utility functions used across commands
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import logging
import asyncio
import os
import json

# Set up logger
logger = logging.getLogger('discord')

# ==================== CONSTANTS ====================
PAGINATION_CHUNK_SIZE = 20
MAX_EMBED_LENGTH = 1900
MAX_EMBED_FIELD_LENGTH = 1024
MAX_EMBED_DESCRIPTION_LENGTH = 4096

# Away role IDs
AWAY_ROLE_ID = 1231259676457566250  # Normal away role
AWAY_IMMUNITY_ROLE_ID = 1495688613030133821  # Away role that also grants immunity (staffhub only)
# Backward-compat alias — older code/imports referenced this under its old
# "strike immunity" name. Same role ID, just clearer naming going forward.
STRIKE_IMMUNITY_AWAY_ROLE_ID = AWAY_IMMUNITY_ROLE_ID

# ==================== AUTOMATION HELPERS ====================

def get_automation_config():
    """
    Load automated_checks config from config.json
    
    Returns:
        dict: automation config or empty dict if file not found
    """
    config_path = 'config.json'
    if not os.path.exists(config_path):
        logger.warning("config.json not found")
        return {}
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config.get('automated_checks', {})
    except Exception as e:
        logger.error(f"Error reading automation config: {e}")
        return {}

def get_screenshot_channels():
    """
    Get screenshot channel IDs from config.json
    
    Returns:
        list: screenshot channel IDs or empty list if not found
    """
    config_path = 'config.json'
    if not os.path.exists(config_path):
        logger.warning("config.json not found")
        return []
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        staff_sheet_config = config.get('staff_sheet_config', {})
        return staff_sheet_config.get('screenshot_channel_ids', [])
    except Exception as e:
        logger.error(f"Error reading screenshot channels: {e}")
        return []

def get_staff_members_from_guild(guild):
    """
    Get all staff members from a guild using staff_roles_config
    
    Args:
        guild: Discord guild object
    
    Returns:
        list: List of staff members
    """
    config_path = 'config.json'
    if not os.path.exists(config_path):
        return []
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        staff_roles_config = config.get('staff_roles_config', {})
        general_staff_roles = staff_roles_config.get('general_staff', ['Trial Staff', 'Staff'])
        
        # Collect all staff members by role name
        all_staff = set()
        for role_name in general_staff_roles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                all_staff.update([m for m in role.members if not m.bot])
        
        return list(all_staff)
    except Exception as e:
        logger.error(f"Error getting staff members: {e}")
        return []

# ==================== DATE FUNCTIONS ====================

def parse_date(date_str):
    """Parse date string in dd/mm/yyyy format"""
    try:
        return datetime.strptime(date_str, '%d/%m/%Y').replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def get_start_datetime(date_str):
    """Get start of day datetime from date string"""
    dt = parse_date(date_str)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0) if dt else None

def get_end_datetime(date_str):
    """Get end of day datetime from date string"""
    dt = parse_date(date_str)
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999) if dt else None

def validate_date_range(start_date_str: str, end_date_str: str) -> tuple:
    """
    Validate that start_date is before end_date.
    Returns (is_valid, error_message)
    """
    start = parse_date(start_date_str)
    end = parse_date(end_date_str)
    
    if not start or not end:
        return False, "Invalid date format. Use dd/mm/yyyy"
    
    if start > end:
        return False, f"Start date ({start_date_str}) must be before end date ({end_date_str})"
    
    return True, None

# ==================== EMBED FUNCTIONS ====================

def create_error_embed(title: str, description: str, suggestion: str = None) -> discord.Embed:
    """Create a standardized error embed"""
    embed = discord.Embed(
        title=f"❌ {title}",
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )
    if suggestion:
        embed.add_field(name="💡 Suggestion", value=suggestion, inline=False)
    return embed

def create_success_embed(title: str, description: str) -> discord.Embed:
    """Create a standardized success embed"""
    embed = discord.Embed(
        title=f"✅ {title}",
        description=description,
        color=discord.Color.green()
    )
    return embed

def extract_embed_content(embed: discord.Embed) -> str:
    """
    Ultra-optimized embed text extraction.
    Pre-allocates list for better memory performance.
    """
    parts = []
    
    # Add basic fields
    if embed.title:
        parts.append(embed.title)
    if embed.description:
        parts.append(embed.description)
    if embed.footer and embed.footer.text:
        parts.append(embed.footer.text)
    if embed.author and embed.author.name:
        parts.append(embed.author.name)
    
    # Add embed fields
    if embed.fields:
        for field in embed.fields:
            if field.name:
                parts.append(field.name)
            if field.value:
                parts.append(field.value)
    
    return " ".join(parts).lower()

# ==================== PAGINATION ====================

async def send_paginated(ctx, lines: List[str], chunk_size: int = PAGINATION_CHUNK_SIZE):
    """
    Optimized paginated output with pre-calculated pages and efficient sending.
    Ensures messages never exceed Discord's 2000 character limit.
    """
    if not lines or len(lines) <= 1:
        return
    
    # Pre-calculate all pages
    pages = []
    current_batch = [lines[0]]  # Always include header
    current_length = len(lines[0])
    
    for line in lines[1:]:
        line_length = len(line) + 1  # +1 for newline
        
        # Check if adding this line would exceed limits
        if (len(current_batch) >= chunk_size + 1 or  # +1 for header
            current_length + line_length > MAX_EMBED_LENGTH):
            # Save current batch
            pages.append("\n".join(current_batch))
            # Start new batch with just the header and current line
            current_batch = [lines[0], line]
            current_length = len(lines[0]) + line_length
        else:
            current_batch.append(line)
            current_length += line_length
    
    # Add remaining lines
    if len(current_batch) > 1:
        pages.append("\n".join(current_batch))
    
    # Send all pages with minimal delay
    for i, page in enumerate(pages):
        await ctx.send(page)
        # Small delay between pages to avoid rate limits
        if i < len(pages) - 1:
            await asyncio.sleep(0.3)

# ==================== USER/MEMBER FUNCTIONS ====================

def web_avatar_url(asset, size=128):
    """
    Web-safe avatar URL for the Staff Hub website.

    Animated Discord avatars use a ``.gif`` URL which returns HTTP 415 when
    loaded cross-origin.  This helper swaps animated URLs to ``.webp?animated=true``
    (natively supported by ``<img>`` tags) and caps the size to keep page weight
    reasonable (default 128px ≈ 377 KB animated).

    Static avatars are returned unchanged (they're already ``.png``/``.webp``).

    Args:
        asset: A discord.py ``Asset`` object (e.g. ``member.display_avatar``).
               ``None`` is accepted and returns ``None``.
        size:  Image size in pixels (must be a power of 2, 16–4096).

    Returns:
        A URL string safe for cross-origin ``<img>`` use, or ``None``.
    """
    if not asset:
        return None
    url = str(asset.with_size(size).url)
    return url.replace('.gif?', '.webp?animated=true&') if '.gif?' in url else url

def get_member(ctx, member_id):
    """Get member from ID or return author"""
    if member_id is None:
        return ctx.author
    return ctx.guild.get_member(member_id)

def check_if_user_is_away(bot, user_id: int) -> bool:
    """
    Check if a user has either the normal Away role OR the immunity Away role.
    Either one marks them as "away" — they're skipped by automated penalties.

    Args:
        bot: Discord bot instance
        user_id: Discord user ID to check

    Returns:
        True if user has any away role (normal or immunity), False otherwise
    """
    try:
        for guild in bot.guilds:
            member = guild.get_member(user_id)
            if member:
                # Check if member has either away role
                for role in member.roles:
                    if role.id == AWAY_ROLE_ID or role.id == AWAY_IMMUNITY_ROLE_ID:
                        logger.info(f"✅ User {user_id} has away role (type: {'normal' if role.id == AWAY_ROLE_ID else 'immunity'}) in {guild.name}")
                        return True
        return False
    except Exception as e:
        logger.error(f"Error checking away role for user {user_id}: {e}")
        return False


def is_user_normal_away(bot, user_id: int) -> bool:
    """
    Check if a user has ONLY the normal Away role (not the immunity Away role).
    Used for weekly report display — only normal away users get the "🏖️ Away" tag.

    Args:
        bot: Discord bot instance
        user_id: Discord user ID to check

    Returns:
        True if user has normal away role, False otherwise (including immunity)
    """
    try:
        for guild in bot.guilds:
            member = guild.get_member(user_id)
            if member:
                # Check if member has the normal away role
                for role in member.roles:
                    if role.id == AWAY_ROLE_ID:
                        logger.info(f"✅ User {user_id} has normal away role in {guild.name}")
                        return True
        return False
    except Exception as e:
        logger.error(f"Error checking normal away role for user {user_id}: {e}")
        return False

# ==================== CONFIG VALIDATION ====================

async def check_dates_configured(ctx, config_cache):
    """
    Check if GLOBAL dates are configured
    Returns dates dict or None if not configured
    """
    global_dates = await config_cache.get_global_dates()
    
    if not global_dates.get('start_date'):
        embed = discord.Embed(
            title="Error",
            description="❌ Global start date is not configured. Use `>setdates <start> <end>`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return None
    if not global_dates.get('end_date'):
        embed = discord.Embed(
            title="Error",
            description="❌ Global end date is not configured. Use `>setdates <start> <end>`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return None
    
    # Return global dates in config format
    return {
        'start_date': global_dates['start_date'],
        'end_date': global_dates['end_date']
    }

# ==================== FORMATTING ====================

def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration"""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)

def format_number(num: int) -> str:
    """Format number with commas"""
    return f"{num:,}"

def get_readable_text_channels(guild):
    """
    Get all text channels in a guild that the bot can read
    
    Args:
        guild: Discord guild object
    
    Returns:
        List of text channels the bot can read
    """
    return [
        channel for channel in guild.text_channels
        if channel.permissions_for(guild.me).read_messages
        and channel.permissions_for(guild.me).read_message_history
    ]

async def safe_history_fetch(channel, limit=None, after=None, before=None):
    """
    Safely fetch message history from a channel with error handling and rate limit protection
    
    Args:
        channel: Discord channel object
        limit: Maximum number of messages to fetch
        after: Fetch messages after this datetime
        before: Fetch messages before this datetime
    
    Returns:
        List of messages
    """
    try:
        messages = []
        batch_count = 0
        async for message in channel.history(limit=limit, after=after, before=before):
            messages.append(message)
            batch_count += 1
            # Add small delay every 100 messages to avoid rate limits
            if batch_count % 100 == 0:
                await asyncio.sleep(0.5)
        return messages
    except discord.Forbidden:
        logger.warning(f"No permission to read history in channel {channel.name}")
        return []
    except discord.HTTPException as e:
        if e.status == 429:  # Rate limited
            logger.warning(f"Rate limited on {channel.name}, waiting 2s...")
            await asyncio.sleep(2)
        logger.error(f"HTTP error fetching history from {channel.name}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching history from {channel.name}: {e}")
        return []

def is_reply_to_other(message) -> bool:
    """
    Return True if `message` is a reply to a DIFFERENT user's message.

    Used by the Map Request ("req") duty scans so that only *help* actions
    (replying to someone) count, not every message a staff member posts in
    the request channel.

    Policy (chosen for the request-count feature):
    - Counts replies to ANYONE — human or bot (requests may be posted by a
      bot/queue system, so we must not exclude bot targets).
    - Excludes self-replies (replying to your own message).
    - If the original message can't be resolved (e.g. it was deleted, so we
      only have a DeletedReferencedMessage / None), we still count it: it IS
      a reply, we just can't verify the author. This avoids under-counting
      helpers when an old request gets deleted.
    - Ignores non-reply references such as forwards or pin notifications by
      requiring MessageType.reply when that info is available.
    """
    ref = getattr(message, 'reference', None)
    if ref is None:
        return False  # not a reply at all

    # Make sure this is a genuine reply, not a forward / pin / crosspost ref.
    reply_type = getattr(discord.MessageType, 'reply', None)
    msg_type = getattr(message, 'type', None)
    if reply_type is not None and msg_type is not None and msg_type != reply_type:
        return False

    resolved = getattr(ref, 'resolved', None)
    if isinstance(resolved, discord.Message):
        # We have the original message — exclude replies to oneself.
        try:
            return resolved.author.id != message.author.id
        except Exception:
            return True
    # Original deleted / not resolved — still a reply, count it (lenient).
    return True

async def scan_channels_parallel(text_channels, members, start_datetime, end_datetime, ctx):
    """
    Scan multiple channels for member activity with rate limiting
    
    Args:
        text_channels: List of text channels to scan
        members: List of members to track
        start_datetime: Start date for scanning
        end_datetime: End date for scanning
        ctx: Command context
    
    Returns:
        Dictionary mapping members to their stats (count and days)
    """
    member_stats = {}
    
    for member in members:
        member_stats[member] = {'count': 0, 'days': set()}
    
    for i, channel in enumerate(text_channels):
        try:
            # Add delay between channels to avoid rate limits
            if i > 0 and i % 5 == 0:
                await asyncio.sleep(1)
            
            messages = await safe_history_fetch(
                channel, limit=5000, after=start_datetime, before=end_datetime
            )
            
            for message in messages:
                if message.author in members and not message.author.bot:
                    member_stats[message.author]['count'] += 1
                    member_stats[message.author]['days'].add(message.created_at.date())
                    
        except Exception as e:
            logger.error(f"Error scanning channel {channel.name}: {e}")
            continue
    
    return member_stats

async def predict_end_of_week_performance(user_id, duty_type, current_count, start_date_str, end_date_str):
    """
    Predict end-of-week performance based on current pace
    
    Args:
        user_id: Discord user ID
        duty_type: Type of duty (req, role, etc.)
        current_count: Current count
        start_date_str: Start date string
        end_date_str: End date string
    
    Returns:
        Formatted prediction string or None
    """
    try:
        start_dt = get_start_datetime(start_date_str)
        end_dt = get_end_datetime(end_date_str)
        now = datetime.now(timezone.utc)
        
        if not start_dt or not end_dt:
            return None
        
        elapsed_hours = (now - start_dt).total_seconds() / 3600
        total_hours = (end_dt - start_dt).total_seconds() / 3600
        
        if elapsed_hours <= 0:
            return None
        
        days_elapsed = elapsed_hours / 24
        daily_rate = current_count / days_elapsed
        total_days = total_hours / 24
        projected_total = int(daily_rate * total_days)
        
        duty_names = {
            'req': 'requests',
            'role': 'roles',
            'modlog': 'mod commands',
            'message': 'messages'
        }
        
        duty_name = duty_names.get(duty_type, duty_type)
        
        return (
            f"\n\n🔮 **End-of-Week Prediction:**\n"
            f"• **Current Pace:** {daily_rate:.1f} {duty_name} per day\n"
            f"• **Projected Total:** ~{projected_total} {duty_name}"
        )
        
    except Exception as e:
        logger.error(f"Error predicting performance: {e}")
        return None

# ==================== CHANNEL RESTRICTIONS ====================

async def is_allowed_channel(ctx):
    """
    Check if command is used in an allowed channel.
    Works with threads and forum posts by checking the parent channel.
    Works with your existing config.json structure.
    """
    from core.cache import config_cache

    try:
        guild_config = await config_cache.get_guild_config(ctx.guild.id)
        allowed_channels = guild_config.get('allowed_command_channels', [])

        # If no channels configured, allow everywhere
        if not allowed_channels:
            return True

        # Get the channel ID to check
        channel_id = ctx.channel.id

        # If command is in a thread or forum post, check the parent channel instead
        if isinstance(ctx.channel, (discord.Thread, discord.abc.GuildChannel)):
            if hasattr(ctx.channel, 'parent_id') and ctx.channel.parent_id:
                channel_id = ctx.channel.parent_id

        # Check if current channel is allowed
        if channel_id not in allowed_channels:
            embed = discord.Embed(
                title="❌ Wrong Channel",
                description="This command can only be used in designated staff command channels (or threads/posts within them).",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return False

        return True

    except Exception as e:
        logger.error(f"Error checking allowed channel: {e}")
        return True  # On error, allow the command to prevent breaking