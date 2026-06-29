"""
Automated DM Rotation System
Monitors rotation channels and DMs users when it's their turn
AUTOMATION ONLY - NO MANUAL COMMANDS
"""

import discord
from discord.ext import commands
import re
import logging

logger = logging.getLogger('discord')

# ==================== CONFIGURATION ====================

AWAY_ROLE_ID = 1495685790452420608  # Loot Route Away role (staffhub server)
AWAY_ANNOUNCE_CHANNEL_ID = 1321707708923248661

# Channel configurations
ROTATION_CHANNELS = {
    1210837029693300768: {  # Drop Map channel
        'name': 'Drop Map',
        'master_message_id': 1442847901327036527,
        'rotation_list_channel': 1321707643492106268,
        'notification_text': "🗺️ **It's your turn to DM for Drop Map rotations!**\n\nPlease check the rotation channel and handle your DM duties."
    },
    1131191033150050385: {  # Loot Route channel
        'name': 'Loot Route',
        'master_message_id': 1442848083804426302,
        'rotation_list_channel': 1321707643492106268,
        'notification_text': "💰 **It's your turn to DM for Loot Route rotations!**\n\nPlease check the rotation channel and handle your DM duties."
    }
}

# Emoji number mapping — keycap emojis ONLY.
# Plain digit strings ('1', '2' etc.) intentionally excluded because
# '1' in message_content would match any message containing the digit 1.
EMOJI_NUMBERS = {
    '1️⃣': 1, '2️⃣': 2, '3️⃣': 3, '4️⃣': 4, '5️⃣': 5,
    '6️⃣': 6, '7️⃣': 7, '8️⃣': 8, '9️⃣': 9, '🔟': 10,
}

class DMingSystem(commands.Cog):
    """Automated rotation DM notification system"""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def parse_rotation_list(self, message):
        """
        Parse the master rotation message to extract user order.
        Supports:
          - "1. <@id>"  or  "1 <@id>"       (plain number)
          - "1️⃣ <@id>"                       (keycap emoji — as shown in rotation messages)
        """
        rotation_map = {}

        # Reverse EMOJI_NUMBERS so we can look up emoji → int
        emoji_to_num = {e: n for e, n in EMOJI_NUMBERS.items()}

        try:
            content = message.content
            lines = content.split('\n')

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # ── Format: "1️⃣ <@id>" (keycap emoji) ──────────────────────
                for emoji, number in emoji_to_num.items():
                    if line.startswith(emoji):
                        match = re.search(r'<@!?(\d+)>', line)
                        if match:
                            user_id = int(match.group(1))
                            rotation_map[number] = user_id
                            logger.info(f"✅ Parsed position {number}: user {user_id} (keycap emoji)")
                        break
                else:
                    # ── Format: "1. <@id>" or "1 <@id>" (plain number) ───────
                    match = re.match(r'^(\d+)[.\s]\s*<@!?(\d+)>', line)
                    if match:
                        position = int(match.group(1))
                        user_id = int(match.group(2))
                        rotation_map[position] = user_id
                        logger.info(f"✅ Parsed position {position}: user {user_id} (plain number)")

            logger.info(f"📋 Parsed {len(rotation_map)} rotation positions")
            return rotation_map

        except Exception as e:
            logger.error(f"❌ Error parsing rotation list: {e}")
            return {}
    
    def extract_rotation_number_from_message(self, message):
        """
        Extract rotation number from a message.
        Matches emoji numbers OR contextual plain-text numbers
        (e.g., "drop 1", "loot 5", "rotation 3")

        Args:
            message: Discord message object

        Returns:
            int: rotation number or None
        """
        content = message.content

        # ✅ PRIORITY 1: Check for keycap emoji numbers (e.g. 1️⃣)
        for emoji, number in EMOJI_NUMBERS.items():
            if emoji in content:
                logger.info(f"✅ Found rotation number {number} from emoji {emoji}")
                return number

        # ✅ PRIORITY 2: Check reactions on the message
        for reaction in message.reactions:
            emoji_str = str(reaction.emoji)
            if emoji_str in EMOJI_NUMBERS:
                number = EMOJI_NUMBERS[emoji_str]
                logger.info(f"✅ Found rotation number {number} from reaction {emoji_str}")
                return number

        # ✅ PRIORITY 3: Look for contextual plain-text patterns
        # Match patterns like: "drop 1", "loot 5", "rotation 3", "1. item", etc.
        patterns = [
            r'(?:drop|dming|rotation|route|loot)\s*([1-9]|10)',  # "drop 1" or "loot 5"
            r'^([1-9]|10)\s*[.:-]',  # "1. item" or "1: item" at start of message
            r'(?:^|\s)([1-9]|10)(?:\s|$)',  # Standalone number surrounded by spaces
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                number = int(match.group(1))
                logger.info(f"✅ Found rotation number {number} from text pattern: '{pattern}'")
                return number

        logger.debug(f"ℹ️ No rotation number detected in message: '{content}'")
        return None

    def member_has_away_role(self, guild, user_id):
        """Check if a member has the away role"""
        member = guild.get_member(user_id)
        if not member:
            return False
        return any(role.id == AWAY_ROLE_ID for role in member.roles)

    async def send_away_announcement(self, guild, user_id, rotation_type, trigger_message):
        """
        Post in the away announce channel that the person is away
        and someone else needs to handle the DMing
        """
        try:
            announce_channel = self.bot.get_channel(AWAY_ANNOUNCE_CHANNEL_ID)
            if not announce_channel:
                logger.error(f"❌ Away announce channel {AWAY_ANNOUNCE_CHANNEL_ID} not found!")
                return

            member = guild.get_member(user_id)
            member_mention = member.mention if member else f"<@{user_id}>"
            message_link = f"https://discord.com/channels/{guild.id}/{trigger_message.channel.id}/{trigger_message.id}"

            await announce_channel.send(
                f"@everyone Can someone do the DMing for **{rotation_type}**?\n\n"
                f"{member_mention} is currently **away** and is unable to handle their rotation.\n\n"
                f"📨 **Message that needs to be handled:** {message_link}"
            )
            logger.info(f"✅ Sent away announcement for user {user_id} in {rotation_type}")

        except Exception as e:
            logger.error(f"❌ Error sending away announcement: {e}")

    async def send_dm_notification(self, user_id, rotation_type, channel_id):
        """
        Send DM notification to a user
        
        Args:
            user_id: Discord user ID to notify
            rotation_type: Name of rotation (e.g., "Drop Map")
            channel_id: Channel ID where rotation is happening
        """
        try:
            logger.info(f"🔔 Attempting to DM user {user_id} for {rotation_type}...")
            user = await self.bot.fetch_user(user_id)
            logger.info(f"✅ User {user_id} found: {user.name}#{user.discriminator}")
            
            embed = discord.Embed(
                title=f"🔔 Rotation Notification - {rotation_type}",
                description=ROTATION_CHANNELS[channel_id]['notification_text'],
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="📍 Channel",
                value=f"<#{channel_id}>",
                inline=False
            )
            
            embed.set_footer(text="Automated notification from Rotation System")
            
            await user.send(embed=embed)
            logger.info(f"✅ Successfully sent DM to user {user_id} ({user.name}) for {rotation_type}")
            
        except discord.NotFound:
            logger.error(f"❌ User {user_id} not found in Discord!")
        except discord.Forbidden:
            logger.warning(f"⚠️ Cannot DM user {user_id} - they may have DMs closed or bot blocked")
        except discord.HTTPException as e:
            logger.error(f"❌ HTTP error sending DM to user {user_id}: {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error sending DM to user {user_id}: {type(e).__name__}: {e}")
    
    def parse_arrow_user(self, content: str) -> int | None:
        """
        Find the user ID on the line containing the ⬅️ Next Assignment arrow.
        Returns user_id or None.
        """
        for line in content.split('\n'):
            if '⬅' in line:
                match = re.search(r'<@!?(\d+)>', line)
                if match:
                    return int(match.group(1))
        return None

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """
        Fire whenever a message is edited.
        Match by master_message_id so we know exactly which rotation it is.
        """
        # Build lookup: master_message_id -> channel_id config key
        master_to_channel = {
            cfg['master_message_id']: ch_id
            for ch_id, cfg in ROTATION_CHANNELS.items()
        }

        if payload.message_id not in master_to_channel:
            return

        channel_id = master_to_channel[payload.message_id]
        channel_config = ROTATION_CHANNELS[channel_id]
        rotation_type = channel_config['name']

        # Get updated content — prefer payload data, else fetch
        new_content = (payload.data or {}).get('content')
        if not new_content:
            try:
                ch = self.bot.get_channel(payload.channel_id)
                if not ch:
                    return
                msg = await ch.fetch_message(payload.message_id)
                new_content = msg.content
            except Exception as e:
                logger.error(f"❌ Could not fetch edited rotation message: {e}")
                return

        if '⬅' not in new_content:
            return

        user_id = self.parse_arrow_user(new_content)
        if not user_id:
            logger.debug(f"ℹ️ Arrow found but no user mention on that line ({rotation_type})")
            return

        logger.info(f"🔄 Rotation updated — next up: user {user_id} ({rotation_type})")

        ch = self.bot.get_channel(payload.channel_id)
        guild = ch.guild if ch else None

        if guild and self.member_has_away_role(guild, user_id):
            class _FakeMsg:
                def __init__(self, channel, msg_id):
                    self.channel = channel
                    self.id = msg_id
            logger.info(f"😴 User {user_id} is away — sending announcement ({rotation_type})")
            await self.send_away_announcement(guild, user_id, rotation_type, _FakeMsg(ch, payload.message_id))
        else:
            logger.info(f"📨 Sending DM to user {user_id} ({rotation_type})")
            await self.send_dm_notification(user_id, rotation_type, channel_id)

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Listen for messages in rotation channels and trigger DM notifications
        AUTOMATIC - NO COMMANDS NEEDED
        """
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Check if message is in a rotation channel
        if message.channel.id not in ROTATION_CHANNELS:
            return
        
        channel_config = ROTATION_CHANNELS[message.channel.id]
        rotation_type = channel_config['name']
        master_message_id = channel_config['master_message_id']
        rotation_list_channel_id = channel_config.get('rotation_list_channel', message.channel.id)
        
        logger.info(f"📨 New message in {rotation_type} rotation channel from {message.author.name}: '{message.content}'")
        
        # Extract rotation number from message
        rotation_number = self.extract_rotation_number_from_message(message)
        
        if rotation_number is None:
            logger.debug(f"ℹ️ No rotation number found in message - ignoring")
            return
        
        logger.info(f"🎯 Detected rotation number: {rotation_number}")
        
        # Fetch the rotation list channel
        try:
            rotation_list_channel = self.bot.get_channel(rotation_list_channel_id)
            if not rotation_list_channel:
                logger.error(f"❌ Rotation list channel {rotation_list_channel_id} not found! Check channel ID.")
                return
            logger.info(f"✅ Found rotation list channel: {rotation_list_channel.name}")
        except Exception as e:
            logger.error(f"❌ Error accessing rotation list channel: {e}")
            return
        
        # Fetch the master rotation message from the rotation list channel
        try:
            logger.info(f"📥 Fetching master rotation message (ID: {master_message_id})...")
            master_message = await rotation_list_channel.fetch_message(master_message_id)
            logger.info(f"✅ Found master rotation message")
        except discord.NotFound:
            logger.error(f"❌ Master rotation message {master_message_id} not found in channel {rotation_list_channel.name}! Check message ID.")
            return
        except Exception as e:
            logger.error(f"❌ Error fetching master message: {type(e).__name__}: {e}")
            return
        
        # Parse rotation list
        logger.info(f"🔍 Parsing rotation list from master message...")
        rotation_map = await self.parse_rotation_list(master_message)
        
        if not rotation_map:
            logger.error(f"❌ Rotation map is empty! Could not parse master message. Content:\n{master_message.content}")
            return
        
        if rotation_number not in rotation_map:
            logger.warning(f"⚠️ Rotation number {rotation_number} not found in rotation map. Available: {list(rotation_map.keys())}")
            return
        
        # Get user ID for this rotation number
        user_id = rotation_map[rotation_number]
        logger.info(f"✅ Rotation {rotation_number} → User ID {user_id}")
        
        # ✅ CHECK IF USER IS AWAY - announce in channel instead of DMing
        if self.member_has_away_role(message.guild, user_id):
            logger.info(f"😴 User {user_id} has away role - sending announcement instead of DM")
            await self.send_away_announcement(message.guild, user_id, rotation_type, message)
        else:
            # Send DM notification as normal
            logger.info(f"📨 User {user_id} is not away - sending DM notification...")
            await self.send_dm_notification(user_id, rotation_type, message.channel.id)

async def setup(bot):
    await bot.add_cog(DMingSystem(bot))
    logger.info("✅ DMingSystem cog loaded (Automation Only)")