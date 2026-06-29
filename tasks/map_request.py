"""
Map Request Image Forwarding System
Automatically forwards images from source channels to report channels
UPLOADS ACTUAL IMAGE FILES - Not just URLs
Now also extracts description and game mode from queue embeds
"""

import discord
from discord.ext import commands
import logging
import re
import aiohttp
import io

logger = logging.getLogger('discord')

# ==================== QUEUE EMBED PARSING FUNCTIONS ====================
def parse_queue_embed(embed):
    """
    Parse Wave Logistics Bot queue embeds to extract description and game mode.
    
    Embed structure:
    - Single field with all content in the value
    - Format:
      First: 👥 **Requested by:** {user_mentions}
      Second: ⭐ **Priority:** {level} Level Priority Ranking\n- (<@&{role_id}>)
      Third (loot_route only): 🗺️ **Game Mode:** {game_mode}
      Fourth: 📝 **Description:** {description} (optional, always last)
    
    Returns: dict with 'description', 'game_mode', and 'server_mode'
    """
    if not embed.fields:
        return None
    
    # Get the single field value
    field_value = embed.fields[0].value
    
    # Initialize result
    result = {
        'description': '',
        'game_mode': '',
        'server_mode': 'drop_map'  # default
    }
    
    # Split by lines to analyze structure
    lines = field_value.split('\n')

    # Find description line. Match on the bold label only — the emoji prefix has
    # changed across Logistics bot versions (🗺️ → 🎮 for game mode), so don't pin it.
    for line in lines:
        if '**Description:**' in line:
            # Extract description text
            desc_match = re.search(r'\*\*Description:\*\*\s*(.+)', line)
            if desc_match:
                result['description'] = desc_match.group(1).strip()

    # Find game mode line (only present for loot_route)
    for line in lines:
        if '**Game Mode:**' in line:
            # Extract game mode text
            game_match = re.search(r'\*\*Game Mode:\*\*\s*(.+)', line)
            if game_match:
                result['game_mode'] = game_match.group(1).strip()
                result['server_mode'] = 'loot_route'

    return result

def format_queue_content(parsed_data):
    """
    Format parsed queue data into a clean message text.
    
    Returns: Formatted string with game mode (if present) and description
    """
    parts = []
    
    if parsed_data['game_mode']:
        parts.append(f"Game Mode: {parsed_data['game_mode']}")
    
    if parsed_data['description']:
        parts.append(f"Description: {parsed_data['description']}")
    
    return '\n'.join(parts) if parts else ""


async def download_embed_image(url: str, session: aiohttp.ClientSession) -> discord.File:
    """
    Download an image from a URL and return it as a discord.File.
    
    Args:
        url: The image URL to download
        session: aiohttp ClientSession
        
    Returns:
        discord.File object with the downloaded image
    """
    try:
        async with session.get(url) as response:
            if response.status == 200:
                # Read the image data
                image_data = await response.read()
                
                # Extract filename from URL or use default
                filename = url.split('/')[-1].split('?')[0]
                if not filename or '.' not in filename:
                    filename = f"image_{hash(url)}.png"
                
                # Create a file-like object
                file_obj = io.BytesIO(image_data)
                
                # Create discord.File
                return discord.File(file_obj, filename=filename)
            else:
                logger.warning(f"Failed to download image from {url}: HTTP {response.status}")
                return None
    except Exception as e:
        logger.error(f"Error downloading image from {url}: {e}")
        return None


# ==================== CONFIGURATION ====================
# Source Channel ID → Report Channel ID mapping
IMAGE_FORWARD_CONFIG = {
    # Source Guild: 1405570493691596820 (Another server)
    1210837116649742396: {  # Source channel
        'report_channel': 1367827706338742343,  # Report channel in guild 1041450125391835186
        'report_guild': 1041450125391835186,
        'source_guild': 1405570493691596820,
        'label': 'Other Server Maps'
    }
    # Note: the Improvement Cord loot queue channel (1131190892707979284) was removed.
    # Loot routes are now dispatched directly by loot_bridge.py in the Logistics Bot.
}

class MapRequestForwarder(commands.Cog):
    """Forwards map request images from source guilds to report guild"""
    
    def __init__(self, bot):
        self.bot = bot
        logger.info("[OK] Map Request Forwarder initialized")
        logger.info(f"   Monitoring {len(IMAGE_FORWARD_CONFIG)} source channels")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages in configured source channels"""
        
        # Ignore our own bot messages to prevent loops, but process other bots
        if message.author == self.bot.user:
            return
        
        # Check if this is a configured source channel
        if message.channel.id not in IMAGE_FORWARD_CONFIG:
            return

        # Log that we detected a message in a monitored channel
        logger.info(f"[MAP] Message detected in monitored channel {message.channel.id} from {message.author}")
        logger.info(f"[MAP]   Has attachments: {len(message.attachments)}")
        logger.info(f"[MAP]   Has embeds: {len(message.embeds)}")
        
        # Check if message has attachments or embeds with images
        has_attachments = len(message.attachments) > 0
        has_embed_images = any(embed.image or embed.thumbnail for embed in message.embeds)
        
        if not has_attachments and not has_embed_images:
            logger.info(f"   No attachments or embed images found, skipping")
            return
        
        # Log embed details for debugging
        if message.embeds:
            for i, embed in enumerate(message.embeds):
                logger.info(f"   Embed {i+1}:")
                logger.info(f"     Title: {embed.title}")
                logger.info(f"     Description: {embed.description}")
                logger.info(f"     Fields: {len(embed.fields)}")
                for j, field in enumerate(embed.fields):
                    logger.info(f"       Field {j+1}: {field.name} = {field.value[:100]}...")
                logger.info(f"     Image: {embed.image}")
                logger.info(f"     Thumbnail: {embed.thumbnail}")
        
        # Get configuration for this source channel
        config = IMAGE_FORWARD_CONFIG[message.channel.id]
        
        # Forward the images
        await self.forward_images(message, config)
    
    async def forward_images(self, message, config):
        """Forward images from source message to report channel - UPLOADS ACTUAL FILES"""
        try:
            # Get report channel
            report_channel = self.bot.get_channel(config['report_channel'])
            
            if not report_channel:
                logger.error(f"[ERROR] Report channel {config['report_channel']} not found")
                return
            
            # Get source guild name for logging only
            source_guild = self.bot.get_guild(config['source_guild'])
            guild_name = source_guild.name if source_guild else "Unknown Server"
            
            # Prepare text content - start with original message content
            content = message.content if message.content else ""
            
            # [OK] PARSE QUEUE EMBEDS FOR ADDITIONAL CONTENT
            queue_text = ""
            if message.embeds:
                logger.info(f"   Processing {len(message.embeds)} embed(s)")
                for i, embed_obj in enumerate(message.embeds):
                    logger.info(f"   Embed {i+1}: {len(embed_obj.fields)} field(s)")
                    # Check if this is a queue embed (has fields)
                    if embed_obj.fields:
                        logger.info(f"   Parsing embed with fields...")
                        parsed = parse_queue_embed(embed_obj)
                        if parsed:
                            logger.info(f"   Parsed data: desc='{parsed['description']}', game_mode='{parsed['game_mode']}', server_mode='{parsed['server_mode']}'")
                            formatted = format_queue_content(parsed)
                            if formatted:
                                queue_text = formatted
                                logger.info(f"[MAP] Extracted queue data: {parsed['server_mode']} mode")
                        else:
                            logger.info(f"   No queue data parsed from embed")
                    else:
                        logger.info(f"   Embed has no fields, skipping queue parsing")
            
            # Combine content: original message + queue text
            final_content = content
            if queue_text:
                if final_content:
                    final_content = f"{final_content}\n\n{queue_text}"
                else:
                    final_content = queue_text
            
            # Collect all files to send (attachments + embed images)
            files_to_send = []
            
            # [OK] UPLOAD ACTUAL IMAGE FILES FROM ATTACHMENTS
            if message.attachments:
                for attachment in message.attachments:
                    # Convert attachment to file (works for images and other files)
                    file = await attachment.to_file()
                    files_to_send.append(file)
            
            # Download embed images as files
            if message.embeds:
                async with aiohttp.ClientSession() as session:
                    for embed_obj in message.embeds:
                        # Download embed image if present
                        if embed_obj.image and embed_obj.image.url:
                            file = await download_embed_image(embed_obj.image.url, session)
                            if file:
                                files_to_send.append(file)
                                logger.info(f"   Downloaded embed image: {embed_obj.image.url}")
                        
                        # Download embed thumbnail if present
                        if embed_obj.thumbnail and embed_obj.thumbnail.url:
                            file = await download_embed_image(embed_obj.thumbnail.url, session)
                            if file:
                                files_to_send.append(file)
                                logger.info(f"   Downloaded embed thumbnail: {embed_obj.thumbnail.url}")
            
            # Send message with text + all files in ONE message
            if files_to_send:
                await report_channel.send(content=final_content, files=files_to_send)
                logger.info(
                    f"[OK] Forwarded {len(files_to_send)} file(s) from {message.author} in {guild_name} "
                    f"to report channel {config['report_channel']}"
                )
                logger.info(f"   Content: {final_content[:100]}{'...' if len(final_content) > 100 else ''}")
            elif final_content:
                # If no files but we have content, send just the content
                await report_channel.send(final_content)
                logger.info(
                    f"[OK] Forwarded text content from {message.author} in {guild_name} "
                    f"to report channel {config['report_channel']}"
                )
                logger.info(f"   Content: {final_content[:100]}{'...' if len(final_content) > 100 else ''}")
        
        except discord.Forbidden:
            logger.error(f"[ERROR] No permission to send to report channel {config['report_channel']}")
        except discord.HTTPException as e:
            logger.error(f"[ERROR] Failed to forward image: {e}")
        except Exception as e:
            logger.error(f"[ERROR] Unexpected error forwarding image: {e}")
            import traceback
            traceback.print_exc()


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(MapRequestForwarder(bot))
    logger.info("[OK] Map Request Forwarder cog loaded")