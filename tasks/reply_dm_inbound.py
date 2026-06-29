"""
Inbound DM Listener (sticky-note model)
========================================
Listens for incoming DMs. If the user has an armed sticky note
(placed by reply_dm_outbound after forwarding a staff reply), fire the
guild-specific auto-reply text and disarm the note.

If no armed note exists → stay silent. The "spam everyone once" behavior
of the old auto_reply_queue is gone.

Notes are stored in the shared DB `reply_dm_note` table. See
`tasks/reply_dm_state.py` for the arm/wipe/get helpers.
"""

import logging

import discord
from discord.ext import commands

from tasks.reply_dm_state import get_active_note

logger = logging.getLogger('discord')

# Per-guild auto-reply text. Each guild's message points at that guild's
# own proof channel link. If a guild isn't in this dict (shouldn't happen
# in practice — only two guilds use reply_dm_outbound), the listener stays
# silent rather than sending a generic fallback.
AUTO_REPLY_BY_GUILD = {
    988564962802810961: (
        "Hi {user_mention}! 👋\n\n"
        "Thanks for reaching out! If you're sending proof, please post it in "
        "https://discord.com/channels/988564962802810961/1210798761329295440 "
        "on the server instead — a staff member will review it and give you the role. "
        "That way nothing gets lost in DMs!\n\n"
        "Thank you for taking the time to DM me — we appreciate it! Have a blessed day! 💙"
    ),
    971731167621574666: (
        "Hi {user_mention}! 👋\n\n"
        "Thanks for reaching out! If you're sending proof, please post it in "
        "https://discord.com/channels/971731167621574666/1188088624345002035 "
        "on the server instead — a staff member will review it and give you the role. "
        "That way nothing gets lost in DMs!\n\n"
        "Thank you for taking the time to DM me — we appreciate it! Have a blessed day! 💙"
    ),
}


class AutoReplyCog(commands.Cog):
    """Fires a guild-specific auto-reply when a member with an armed note DMs the bot."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[AutoReply] Cog ready — listening for incoming DMs")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Only DMs from real users
        if message.guild is not None or message.author.bot:
            return

        # Skip command invocations — don't intercept "-z help" etc
        if message.content.startswith(self.bot.command_prefix):
            return

        try:
            note = await get_active_note(message.author.id)
            if note is None:
                # No armed note → stay silent
                return

            guild_id, source_bot_id = note

            # Only fire auto-reply if THIS bot sent the original reply_dm_outbound message.
            # Without this check, both bots would see the incoming DM and both would
            # try to send the auto-reply.
            if source_bot_id != self.bot.user.id:
                logger.debug(
                    f"[AutoReply] Skipping DM from {message.author.id} — "
                    f"note was armed by bot {source_bot_id}, not this bot {self.bot.user.id}"
                )
                return

            template = AUTO_REPLY_BY_GUILD.get(guild_id)
            if template is None:
                logger.warning(
                    f"[AutoReply] No template configured for guild {guild_id} "
                    f"(user {message.author.id}). Skipping."
                )
                return

            reply_text = template.format(user_mention=message.author.mention)

            # _source="auto_reply" tags this DM so the dm_queue worker knows
            # this is a success-gated wipe path. The worker wipes the note
            # only after the original_send actually succeeds in Discord —
            # if it fails (Forbidden, etc.) the note stays armed for retry.
            await message.author.send(reply_text, _source="auto_reply")
            logger.info(
                f"[AutoReply] QUEUED for user={message.author.id} guild={guild_id}"
            )

        except Exception as e:
            logger.error(f"[AutoReply] Error handling DM from {message.author.id}: {e}", exc_info=True)


async def setup(bot):
    await bot.add_cog(AutoReplyCog(bot))
    logger.info("✅ AutoReplyCog loaded")
