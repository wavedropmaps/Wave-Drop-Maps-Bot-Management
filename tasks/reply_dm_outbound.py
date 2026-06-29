"""
Outbound DM Sender
Monitors a configured channel for staff replies and DMs the original message author.
DMs are sent directly to the shared dm_queue database (no local queueing).
Auto-delete: original member message + staff reply deleted 5 min after DM is sent (opt-in).
Unreplied expiry: member messages with no staff reply deleted after 12 hours (opt-in).
Both timers survive bot restarts.
"""

import discord
from discord.ext import commands
import logging
import asyncio
from typing import Dict, Set, Optional

from core.cache import config_cache
from tasks.reply_dm_state import arm_note
import database

logger = logging.getLogger('discord')

AUTODELETE_DELAY           = 300    # seconds before deleting original + staff reply (5 minutes)
UNREPLIED_MSG_DELETE_DELAY = 43200  # seconds before deleting unreplied member messages (12 hours)


def _dm_fail_reason(e: Exception) -> str:
    if isinstance(e, discord.Forbidden):
        return "Member has DMs disabled or has blocked the bot"
    if isinstance(e, discord.NotFound):
        return "Member not found"
    if isinstance(e, discord.HTTPException):
        return f"HTTP {e.status}: {e.text}"
    return str(e)


class ReplyDMView(discord.ui.View):
    """Buttons on failed DM log entries: Retry DM and Cancel DM Attempt."""

    def __init__(self, bot, member_id: int, dm_content: str, guild_id: int = 0):
        super().__init__(timeout=None)
        self.bot = bot
        self.member_id = member_id
        self.dm_content = dm_content
        self.guild_id = guild_id
        self._retry_count = 0

    @discord.ui.button(label="Retry DM", style=discord.ButtonStyle.primary, emoji="🔄")
    async def retry_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._retry_count += 1
        try:
            user = await self.bot.fetch_user(self.member_id)
            await user.send(self.dm_content, _source="reply_dm_duty")
            if self.guild_id:
                await arm_note(self.member_id, self.guild_id, self.bot.user.id)
            embed = interaction.message.embeds[0]
            embed.title = "✅ DM Resolved (Retried Successfully)"
            embed.color = discord.Color.green()
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            reason = _dm_fail_reason(e)
            embed = interaction.message.embeds[0]
            if self._retry_count >= 2:
                button.disabled = True
                embed.description = f"❌ **Final retry failed**\nReason: {reason}"
            else:
                embed.description = f"❌ **Retry {self._retry_count} failed**\nReason: {reason}"
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cancel DM Attempt", style=discord.ButtonStyle.secondary, emoji="🚫")
    async def cancel_dm(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        embed.title = "🚫 DM Attempt Cancelled"
        embed.color = discord.Color.greyple()
        embed.description = "This DM attempt has been voided by staff."
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)


class ReplyDMDuty(commands.Cog):
    """Watches a channel for staff replies and DMs the original author via shared dm_queue."""

    def __init__(self, bot):
        self.bot = bot
        # message_id -> pending 5-min auto-delete task
        self._msg_delete_tasks: Dict[int, asyncio.Task] = {}
        # message_id -> pending 12h unreplied expiry task
        self._unreplied_expiry_tasks: Dict[int, asyncio.Task] = {}
        # message_id -> pending 10-min staff-mention delete task
        self._staff_mention_delete_tasks: Dict[int, asyncio.Task] = {}

    # ==================== STARTUP ====================

    @commands.Cog.listener()
    async def on_ready(self):
        # Init DB table
        await database.init_reply_dm_tables()

        # Reload pending 5-min auto-deletes from DB
        try:
            pending = await database.get_reply_dm_pending_deletes()
            now_ts = discord.utils.utcnow().timestamp()
            for message_id, channel_id, staff_reply_id, delete_at, member_id in pending:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    await database.remove_reply_dm_pending_delete(message_id)
                    continue
                remaining = max(10, int(delete_at - now_ts))
                self._schedule_msg_delete(channel, message_id, staff_reply_id, delay=remaining, save_to_db=False, member_id=member_id or 0)
            if pending:
                logger.info(f"[ReplyDM] Reloaded {len(pending)} pending auto-delete(s) from DB")
        except Exception as e:
            logger.error(f"[ReplyDM] Failed to reload pending deletes: {e}")

        # Rebuild 12h expiry timers from channel history
        for guild in self.bot.guilds:
            try:
                config = await config_cache.get_guild_config(guild.id)
                if not config.get('reply_dm_autodelete_enabled'):
                    continue
                channel_id     = config.get('reply_dm_channel_id')
                staff_role_ids = config.get('reply_dm_staff_role_ids', [])
                if not channel_id or not staff_role_ids:
                    continue
                channel = guild.get_channel(channel_id)
                if channel:
                    await self._rebuild_expiry_timers(guild, channel, staff_role_ids)
            except Exception as e:
                logger.error(f"[ReplyDM] on_ready expiry rebuild error for guild {guild.id}: {e}")

        # Reload pending staff-mention deletes from DB
        try:
            pending = await database.get_staff_mention_pending_deletes()
            now_ts = discord.utils.utcnow().timestamp()
            for message_id, channel_id, delete_at in pending:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    await database.remove_staff_mention_pending_delete(message_id)
                    continue
                remaining = max(10, int(delete_at - now_ts))
                self._schedule_staff_mention_delete(channel, message_id, delay=remaining, save_to_db=False)
            if pending:
                logger.info(f"[ReplyDM] Reloaded {len(pending)} pending staff-mention delete(s) from DB")
        except Exception as e:
            logger.error(f"[ReplyDM] Failed to reload staff-mention deletes: {e}")

    async def _rebuild_expiry_timers(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        staff_role_ids: list
    ):
        try:
            messages = [m async for m in channel.history(limit=500)]

            replied_ids: Set[int] = set()
            for msg in messages:
                if msg.reference and msg.reference.message_id:
                    # Bots are always treated as staff; humans need a staff role
                    if msg.author.bot:
                        replied_ids.add(msg.reference.message_id)
                    else:
                        member = guild.get_member(msg.author.id)
                        if member and any(r.id in staff_role_ids for r in member.roles):
                            replied_ids.add(msg.reference.message_id)

            now = discord.utils.utcnow()
            count = 0
            for msg in messages:
                if msg.author.bot or msg.reference or msg.id in replied_ids or msg.pinned:
                    continue
                age = (now - msg.created_at).total_seconds()
                remaining = UNREPLIED_MSG_DELETE_DELAY - age
                if remaining > 0:
                    self._schedule_unreplied_expiry(channel, msg.id, delay=max(10, int(remaining)))
                    count += 1
                else:
                    # Past 12h already — delete shortly
                    self._schedule_unreplied_expiry(channel, msg.id, delay=10)
                    count += 1

            logger.info(f"[ReplyDM] Guild {guild.id}: {count} expiry timers rebuilt")
        except Exception as e:
            logger.error(f"[ReplyDM] Expiry rebuild failed for guild {guild.id}: {e}")

    # ==================== MESSAGE LISTENER ====================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Allow bot replies (e.g. AI proof detection) — only skip non-guild messages
        if not message.guild:
            return

        config     = await config_cache.get_guild_config(message.guild.id)
        channel_id = config.get('reply_dm_channel_id')

        if not channel_id or message.channel.id != channel_id:
            return

        staff_role_ids = config.get('reply_dm_staff_role_ids', [])
        autodelete     = config.get('reply_dm_autodelete_enabled', False)

        # Bots acting as staff (AI reviewer etc.) are always treated as staff.
        # Human members must have a configured staff role.
        is_staff = message.author.bot or (
            staff_role_ids and any(r.id in staff_role_ids for r in message.author.roles)
        )

        # Detect bare staff-role-ping messages and schedule 10-min deletion.
        # Use case: a regular member posts just "@Support" / "@Head Admin" with no
        # text to get attention — once noticed it's useless clutter, delete fast.
        is_bare_staff_ping = False
        if autodelete and not message.author.bot and not message.reference and not message.pinned:
            if message.role_mentions and staff_role_ids and all(r.id in staff_role_ids for r in message.role_mentions):
                content_stripped = message.content
                for role in message.role_mentions:
                    content_stripped = content_stripped.replace(f'<@&{role.id}>', '')
                if not any(c.isalnum() for c in content_stripped):
                    is_bare_staff_ping = True
                    self._schedule_staff_mention_delete(message.channel, message.id)

        # Schedule 12h expiry for non-reply human member messages — skip bare pings
        if autodelete and not message.author.bot and not message.reference and not message.pinned and not is_bare_staff_ping:
            self._schedule_unreplied_expiry(message.channel, message.id)

        if not message.reference or not is_staff:
            return

        # Fetch the original message
        try:
            if isinstance(message.reference.resolved, discord.Message):
                original = message.reference.resolved
            else:
                original = await message.channel.fetch_message(message.reference.message_id)
        except Exception as e:
            logger.error(f"[ReplyDM] Could not fetch original message: {e}")
            return

        if original.author.bot or original.pinned:
            return

        # Build DM content
        replier_type = "An automated review" if message.author.bot else "A staff member"
        dm_lines = [f"📨 **{message.guild.name}**\n", f"{replier_type} has replied to your message:\n"]
        if message.content:
            dm_lines.append(message.content)
        if message.attachments:
            dm_lines.append("\n".join(a.url for a in message.attachments))
        dm_content = "\n".join(dm_lines)

        # Cancel 12h expiry — message got replied to
        expiry = self._unreplied_expiry_tasks.pop(original.id, None)
        if expiry and not expiry.done():
            expiry.cancel()

        # Send DM directly (intercepted by shared dm_queue system)
        try:
            user = await self.bot.fetch_user(original.author.id)
            await user.send(dm_content, _source="reply_dm_duty")
            logger.info(f"[ReplyDM] DM sent to {original.author}")

            # Arm sticky note for auto-reply
            await arm_note(original.author.id, message.guild.id, self.bot.user.id)

            # Schedule auto-delete if enabled
            if autodelete:
                self._schedule_msg_delete(message.channel, original.id, message.id, member_id=original.author.id)

        except discord.Forbidden:
            logger.warning(f"[ReplyDM] Cannot DM {original.author} — DMs disabled or blocked")
        except Exception as e:
            logger.error(f"[ReplyDM] Error sending DM to {original.author}: {e}")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Cancel any pending expiry task when a message is manually deleted."""
        expiry = self._unreplied_expiry_tasks.pop(message.id, None)
        if expiry and not expiry.done():
            expiry.cancel()

        staff_mention_delete = self._staff_mention_delete_tasks.pop(message.id, None)
        if staff_mention_delete and not staff_mention_delete.done():
            staff_mention_delete.cancel()
            await database.remove_staff_mention_pending_delete(message.id)

    # ==================== AUTO-DELETE (5 min, DB-persisted) ====================

    def _schedule_msg_delete(
        self,
        channel: discord.TextChannel,
        message_id: int,
        staff_reply_id: int = 0,
        delay: int = AUTODELETE_DELAY,
        save_to_db: bool = True,
        member_id: int = 0,
    ):
        existing = self._msg_delete_tasks.get(message_id)
        if existing and not existing.done():
            existing.cancel()

        if save_to_db:
            delete_at = discord.utils.utcnow().timestamp() + delay
            asyncio.create_task(
                database.add_reply_dm_pending_delete(message_id, channel.id, staff_reply_id, delete_at, member_id)
            )

        async def _do_delete():
            await asyncio.sleep(delay)
            for mid in filter(None, [message_id, staff_reply_id]):
                try:
                    msg = await channel.fetch_message(mid)
                    await msg.delete()
                    logger.info(f"[ReplyDM] Auto-deleted message {mid} from #{channel.name}")
                except discord.NotFound:
                    pass
                except Exception as e:
                    logger.error(f"[ReplyDM] Failed to auto-delete message {mid}: {e}")

            # Purge all earlier messages from this same member in the channel
            if member_id:
                purged = 0
                try:
                    async for old_msg in channel.history(limit=None, before=discord.Object(id=message_id)):
                        if old_msg.author.id != member_id or old_msg.pinned:
                            continue
                        try:
                            await old_msg.delete()
                            purged += 1
                            logger.info(f"[ReplyDM] Auto-deleted earlier message {old_msg.id} from member {member_id} in #{channel.name}")
                        except discord.NotFound:
                            pass
                        except Exception as e:
                            logger.error(f"[ReplyDM] Failed to delete earlier message {old_msg.id}: {e}")
                except Exception as e:
                    logger.error(f"[ReplyDM] Error scanning channel history for earlier messages: {e}")
                if purged:
                    logger.info(f"[ReplyDM] Purged {purged} earlier message(s) from member {member_id} in #{channel.name}")

            await database.remove_reply_dm_pending_delete(message_id)
            self._msg_delete_tasks.pop(message_id, None)

        task = asyncio.create_task(_do_delete())
        self._msg_delete_tasks[message_id] = task

    # ==================== UNREPLIED EXPIRY (12 hours) ====================

    def _schedule_unreplied_expiry(self, channel: discord.TextChannel, message_id: int, delay: int = UNREPLIED_MSG_DELETE_DELAY):
        existing = self._unreplied_expiry_tasks.get(message_id)
        if existing and not existing.done():
            return  # already scheduled

        async def _do_expiry():
            await asyncio.sleep(delay)
            try:
                msg = await channel.fetch_message(message_id)
                await msg.delete()
                logger.info(f"[ReplyDM] Expired unreplied message {message_id} from #{channel.name}")
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error(f"[ReplyDM] Failed to delete expired message {message_id}: {e}")
            finally:
                self._unreplied_expiry_tasks.pop(message_id, None)

        task = asyncio.create_task(_do_expiry())
        self._unreplied_expiry_tasks[message_id] = task

    # ==================== STAFF MENTION DELETE (10 minutes, DB-persisted) ====================

    def _schedule_staff_mention_delete(self, channel: discord.TextChannel, message_id: int, delay: int = 600, save_to_db: bool = True):
        existing = self._staff_mention_delete_tasks.get(message_id)
        if existing and not existing.done():
            existing.cancel()

        if save_to_db:
            delete_at = discord.utils.utcnow().timestamp() + delay
            asyncio.create_task(
                database.add_staff_mention_pending_delete(message_id, channel.id, delete_at)
            )

        async def _do_delete():
            await asyncio.sleep(delay)
            try:
                msg = await channel.fetch_message(message_id)
                await msg.delete()
                logger.info(f"[ReplyDM] Auto-deleted staff-mention message {message_id} from #{channel.name}")
            except discord.NotFound:
                pass
            except Exception as e:
                logger.error(f"[ReplyDM] Failed to auto-delete staff-mention message {message_id}: {e}")
            await database.remove_staff_mention_pending_delete(message_id)
            self._staff_mention_delete_tasks.pop(message_id, None)

        task = asyncio.create_task(_do_delete())
        self._staff_mention_delete_tasks[message_id] = task


async def setup(bot):
    await bot.add_cog(ReplyDMDuty(bot))
    logger.info("✅ ReplyDMDuty cog loaded")
