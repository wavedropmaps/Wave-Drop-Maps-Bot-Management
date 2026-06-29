"""
tasks/surge_routes.py — Surge Route assignment engine (Phases 3 + 4).

Mirrors tasks/loot_routes.py's rotation/assignment flow, adapted for surge:
  • watches the dedicated surge-maps channel (accepts human OR bot-forwarded image+text),
  • assigns the next available surge maker (skipping away users + those with an active route),
  • NEW: if no maker is free, HOLDS the map in surge_pending_maps and auto-assigns it the
    moment a maker frees up (on completion / away-return / new maker / startup sweep),
  • posts the claim card + confirmation, saves the image locally (surge_files/<id>/),
  • emits surge_routes web events instead of posting to a Discord log channel.

The leaderboard refresh hook (auto_update_surge_route_leaderboard) is a no-op stub here;
Phase 6 fills it in.
"""

import os
import re
import json
import random
import asyncio
import logging
import aiohttp
from datetime import datetime, timezone, date, timedelta
from collections import Counter

import discord
from discord.ext import commands, tasks

import core.surge_config as cfg
from core.global_logger import log_event as _wave_log_event
from core.helpers import web_avatar_url
from database import get_pool
import database_surge as sdb

logger = logging.getLogger(__name__)


def _find_role_by_name(guild: discord.Guild, name: str):
    target = name.lower()
    for r in guild.roles:
        if r.name.lower() == target:
            return r
    return None


# In-memory rotation pointer (loaded from DB on startup, mirrors loot).
surge_rotation_state = {
    'last_assigned_position': 0,
    'last_assigned_user_id': None,
    'total_assignments': 0,
}

_IMG_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp')


def user_has_surge_maker_role(guild: discord.Guild, user_id: int) -> bool:
    member = guild.get_member(user_id)
    if not member:
        return False
    target = cfg.SURGE_MAKER_ROLE_NAME.lower()
    return any(r.name.lower() == target for r in member.roles)


def _message_has_image_and_text(message: discord.Message):
    has_text = bool(message.content and message.content.strip())
    has_image = bool(message.attachments)
    if message.content:
        low = message.content.lower()
        if any(ext in low for ext in _IMG_EXT) or 'cdn.discordapp.com' in low or 'media.discordapp.net' in low:
            has_image = True
    return has_image, has_text


class SurgeRoutes(commands.Cog):
    """Automatic surge-route rotation + hold-pool assignment engine."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.skip_auto_regen = False          # set by the roster commands during add/remove
        self._init_task = None
        self._drain_lock = asyncio.Lock()     # serialize pending-pool drains
        self._assign_lock = asyncio.Lock()    # prevent race between handle_surge_request and drain
        self.setup_listeners()
        logger.info("[Surge Routes] ⚡ Assignment engine loaded")

    async def cog_load(self):
        self._init_task = asyncio.create_task(self._init_when_ready())
        for loop in (self.surge_reminder_loop, self.surge_cleanup_loop, self.surge_mvp_loop):
            if not loop.is_running():
                loop.start()

    async def _init_when_ready(self):
        await self.bot.wait_until_ready()
        try:
            st = await sdb.get_surge_rotation_state()
            if st:
                surge_rotation_state.update(st)
            # If maps were held while makers were busy/offline, try to place them now.
            await self.drain_pending_pool(reason="startup")
            # Sync the leaderboard to GitHub on startup (mirrors loot).
            await auto_update_surge_route_leaderboard(self.bot, triggered_by="bot_startup")
        except Exception as e:
            logger.error(f"[Surge Routes] init error: {e}")

    def cog_unload(self):
        if self._init_task:
            self._init_task.cancel()
        for loop in (self.surge_reminder_loop, self.surge_cleanup_loop, self.surge_mvp_loop):
            if loop.is_running():
                loop.cancel()

    # =====================================================================
    # BACKGROUND LOOPS
    # =====================================================================
    @tasks.loop(hours=1)
    async def surge_reminder_loop(self):
        """DM makers with pending surge routes older than 24h, and alert Head Surge Routes staff."""
        try:
            due = await sdb.get_surge_assignments_needing_reminders()
            guild = self.bot.get_guild(cfg.GUILD_ID)
            if not guild:
                return
            for a in due:
                await self._send_surge_reminder(a, guild)

            # Auto-return: clear the away role for anyone whose scheduled return date has passed.
            away_role = guild.get_role(cfg.SURGE_AWAY_ROLE_ID)
            if away_role:
                today_iso = date.today().isoformat()
                for entry in await sdb.get_all_surge_away_return_dates():
                    if (entry.get('return_date') or "") <= today_iso:
                        member = guild.get_member(entry['user_id'])
                        if member and away_role in member.roles:
                            try:
                                await member.remove_roles(away_role, reason="Surge away period ended")
                            except Exception:
                                pass
                        await sdb.delete_surge_away_return_date(entry['user_id'])
        except Exception as e:
            logger.error(f"[Surge Routes] reminder loop error: {e}")

    @surge_reminder_loop.before_loop
    async def _before_reminder(self):
        await self.bot.wait_until_ready()

    async def _send_surge_reminder(self, assignment: dict, guild: discord.Guild):
        """Send DM reminder to user and alert Head Surge Routes staff."""
        try:
            user = await self.bot.fetch_user(assignment['user_id'])
            notification_channel = guild.get_channel(cfg.SURGE_NOTIFICATION_CHANNEL_ID)
            if not notification_channel:
                return

            # Get message link
            try:
                confirm_msg = await notification_channel.fetch_message(assignment['confirmation_message_id'])
                message_link = confirm_msg.jump_url
            except:
                message_link = f"https://discord.com/channels/{assignment['guild_id']}/{cfg.SURGE_NOTIFICATION_CHANNEL_ID}/{assignment['confirmation_message_id']}"

            reminder_count = assignment['reminder_count'] + 1

            # ── DM the assigned user ──────────────────────────────────────
            reminder_text = f"⚡ **Surge Route Reminder #{reminder_count}**\n\n"
            reminder_text += f"You have a pending surge route assignment that needs completion!\n\n"
            reminder_text += f"Assignment details:\n{message_link}\n\n"
            reminder_text += f"_This is reminder #{reminder_count}. You will receive reminders every 24 hours until you complete the route._"

            try:
                await user.send(reminder_text)
                logger.info(f"[Surge Routes] 📨 Sent reminder #{reminder_count} to user {user.name}")
            except discord.Forbidden:
                logger.warning(f"[Surge Routes] ⚠️ Cannot DM user {assignment['user_id']} - DMs disabled")

            # ── Alert Head Surge Routes staff on every reminder cycle ──────
            await self._alert_head_surge_routes(
                guild=guild,
                user=user,
                assignment_id=assignment['assignment_id'],
                reminder_count=reminder_count,
                message_link=message_link,
            )

            # Update database
            await sdb.update_surge_reminder_sent(assignment['assignment_id'])

        except Exception as e:
            logger.error(f"[Surge Routes] ❌ Error sending reminder: {e}")

    async def _alert_head_surge_routes(
        self,
        guild: discord.Guild,
        user: discord.User,
        assignment_id: int,
        reminder_count: int,
        message_link: str,
    ):
        """
        DM every Head Surge Routes role member to notify them that someone
        has not completed their assignment confirmation after 24+ hours.
        Fires on every reminder cycle (every 24 hours) until they complete.
        """
        head_role = guild.get_role(cfg.HEAD_SURGE_ROUTES_ROLE_ID)
        if not head_role:
            logger.warning(f"[Surge Routes] ⚠️ Head Surge Routes role {cfg.HEAD_SURGE_ROUTES_ROLE_ID} not found — skipping staff alert")
            return

        staff_members = [m for m in head_role.members if not m.bot and m.id != user.id]
        if not staff_members:
            logger.info(f"[Surge Routes] ℹ️ No Head Surge Routes staff to alert")
            return

        hours_unconfirmed = reminder_count * 24
        alert_text = (
            f"⚠️ **Surge Route Incomplete — Reminder #{reminder_count}**\n\n"
            f"**{user.display_name}** (`{user.id}`) has **not completed** their surge route "
            f"assignment after **{hours_unconfirmed} hours**.\n\n"
            f"**Assignment ID:** #{assignment_id}\n"
            f"**Route link:** {message_link}\n\n"
            f"_Please follow up with them if needed._"
        )

        sent = 0
        for staff in staff_members:
            try:
                await staff.send(alert_text)
                sent += 1
            except discord.Forbidden:
                logger.warning(f"[Surge Routes] ⚠️ Cannot DM Head Surge Routes staff {staff.name} - DMs disabled")
            except Exception as e:
                logger.warning(f"[Surge Routes] ⚠️ Error DMing staff {staff.name}: {e}")
            await asyncio.sleep(0.5)  # avoid rate limits

        logger.info(f"[Surge Routes] 📣 Alerted {sent}/{len(staff_members)} Head Surge Routes staff about incomplete assignment #{assignment_id} (reminder #{reminder_count})")

    @tasks.loop(hours=24)
    async def surge_cleanup_loop(self):
        """Delete confirmed surge assignments older than 30 days."""
        try:
            await sdb.cleanup_old_surge_route_assignments(days=30)
        except Exception as e:
            logger.error(f"[Surge Routes] cleanup loop error: {e}")

    @surge_cleanup_loop.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def surge_mvp_loop(self):
        """On Mondays, announce last week's top surge maker in the MVP channel (once/week)."""
        try:
            today = date.today()
            if today.weekday() != 0:  # Monday only
                return
            iso = today.isocalendar()
            year, week = iso[0], iso[1]
            if await sdb.check_surge_mvp_already_posted(cfg.GUILD_ID, year, week):
                return
            guild = self.bot.get_guild(cfg.GUILD_ID)
            channel = guild.get_channel(cfg.SURGE_MEMBER_UPDATES_CHANNEL_ID) if guild else None
            if not channel:
                return
            pool = await get_pool()
            async with pool.acquire() as db:
                async with db.execute(
                    "SELECT user_id, SUM(points_awarded) as weekly_pts FROM surge_route_assignments "
                    "WHERE status='completed' AND points_awarded>0 AND completed_at >= datetime('now','-7 days') "
                    "GROUP BY user_id ORDER BY weekly_pts DESC LIMIT 5") as c:
                    rows = await c.fetchall()
            if not rows:
                return
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            lines = []
            for i, (uid, pts) in enumerate(rows):
                member = guild.get_member(uid)
                name = member.display_name if member else f"<@{uid}>"
                lines.append(f"{medals[i]} **{name}** — `{round(pts or 0, 1)} pts`")
            today = date.today()
            week_str = today.strftime("%d %B %Y").lstrip("0")
            mvp_uid, mvp_pts = rows[0]
            msg_content = (
                f"🏆 **Weekly Surge Route MVP** — Week of {week_str}\n\n"
                f"{chr(10).join(lines)}\n\n"
                f"⚡ Congratulations <@{mvp_uid}> for topping the leaderboard this week with **{round(mvp_pts or 0, 1)} points**!"
            )
            msg = await channel.send(msg_content)
            await sdb.save_surge_mvp_post(cfg.GUILD_ID, year, week, msg.id)
        except Exception as e:
            logger.error(f"[Surge Routes] MVP loop error: {e}")

    @surge_mvp_loop.before_loop
    async def _before_mvp(self):
        await self.bot.wait_until_ready()

    # =====================================================================
    # LISTENERS
    # =====================================================================
    def setup_listeners(self):

        @self.bot.listen('on_message')
        async def on_surge_map_message(message: discord.Message):
            if not (message.guild and message.guild.id == cfg.GUILD_ID
                    and message.channel.id == cfg.SURGE_MAP_REQUEST_CHANNEL_ID):
                return
            has_image, has_text = _message_has_image_and_text(message)
            if message.author.bot:
                # Accept bot-forwarded requests (the Logistics bridge) only if they carry image+text.
                if not (has_image and has_text):
                    return
                logger.info(f"[Surge Routes] ✅ Forwarded surge map from bot {message.author.name}")
            else:
                if not (has_image and has_text):
                    await message.add_reaction("⚠️")
                    return
            await self.handle_surge_request(message)

        @self.bot.listen('on_raw_reaction_add')
        async def on_surge_confirmation(payload: discord.RawReactionActionEvent):
            if payload.user_id == self.bot.user.id:
                return
            if payload.channel_id != cfg.SURGE_NOTIFICATION_CHANNEL_ID:
                return
            guild = self.bot.get_guild(payload.guild_id)
            channel = guild.get_channel(payload.channel_id) if guild else None
            if not channel:
                return
            try:
                message = await channel.fetch_message(payload.message_id)
            except Exception:
                return
            # Accept a reaction on EITHER the confirmation embed OR the route card (notification).
            assignment_id = await sdb.get_surge_assignment_by_confirmation_message(payload.message_id)
            if not assignment_id:
                assignment_id = await sdb.get_surge_assignment_by_notification_message(payload.message_id)
            if assignment_id:
                assignment = await sdb.get_surge_route_assignment_by_id(assignment_id)
                # Only the assigned maker's reaction counts.
                if not assignment or assignment.get('user_id') != payload.user_id:
                    return
                await sdb.confirm_surge_route_assignment(assignment_id)
                # Remove the confirmation embed no matter which message was reacted to.
                conf_id = assignment.get('confirmation_message_id')
                try:
                    conf_msg = message if (conf_id and conf_id == payload.message_id) else (await channel.fetch_message(conf_id) if conf_id else None)
                    if conf_msg:
                        await conf_msg.delete()
                except Exception:
                    pass

        @self.bot.listen('on_member_update')
        async def on_surge_role_change(before: discord.Member, after: discord.Member):
            if after.guild.id != cfg.GUILD_ID:
                return

            # Away role removed → the maker is back and may be able to take a held map.
            before_away = any(r.id == cfg.SURGE_AWAY_ROLE_ID for r in before.roles)
            after_away = any(r.id == cfg.SURGE_AWAY_ROLE_ID for r in after.roles)
            if before_away and not after_away:
                await self.drain_pending_pool(reason="away_return")

            target = cfg.SURGE_MAKER_ROLE_NAME.lower()
            had = any(r.name.lower() == target for r in before.roles)
            has = any(r.name.lower() == target for r in after.roles)
            if had == has:
                return
            if self.skip_auto_regen:
                return  # a roster command is handling this explicitly
            if had and not has:
                # Role removed manually → archive history + refresh.
                try:
                    await sdb.archive_surge_route_maker(after.id, display_name=after.display_name)
                except Exception as e:
                    logger.error(f"[Surge Routes] archive on role-loss failed: {e}")
                await _wave_log_event(category=cfg.WAVE_LOG_CATEGORY, action="maker_role_removed",
                                      target={"id": str(after.id)}, guild=after.guild)
            await auto_update_surge_route_leaderboard(self.bot, triggered_by="role_change")

    # =====================================================================
    # ROTATION SELECTION
    # =====================================================================
    async def find_next_available_surge_user(self, guild: discord.Guild):
        """Next maker not away and without an active (pending/confirmed) assignment, else None."""
        positions = await sdb.get_all_surge_route_positions()  # [(rank, uid)] by assigned_at
        if not positions:
            return None

        away_role = guild.get_role(cfg.SURGE_AWAY_ROLE_ID)
        away_ids = {m.id for m in away_role.members} if away_role else set()

        active = await sdb.get_all_pending_surge_assignments() + await sdb.get_all_confirmed_surge_assignments()
        busy_ids = {a['user_id'] for a in active}

        # Start search just after whoever we assigned last (round-robin).
        last_uid = surge_rotation_state.get('last_assigned_user_id')
        start = 0
        if last_uid:
            for i, (_, uid) in enumerate(positions):
                if uid == last_uid:
                    start = i + 1
                    break

        n = len(positions)
        for off in range(n):
            rank, uid = positions[(start + off) % n]
            if uid in away_ids or uid in busy_ids:
                continue
            return (rank, uid)
        return None  # everyone away or busy → caller holds the map

    # =====================================================================
    # HANDLE INCOMING MAP  (assign or hold)
    # =====================================================================
    async def handle_surge_request(self, message: discord.Message, queue_code: str = None,
                                   priority: int = 999):
        guild = message.guild
        is_lucky = random.random() < cfg.LUCKY_MAP_CHANCE
        text = message.content or ""

        # Cross-bot bridge: the Logistics dispatch hides the queue code + customer
        # priority in the attachment filename (surge-q<code>-p<n>-…) so staff see a
        # clean post. URL-only dispatches (and pre-rename messages) instead carry a
        #   [surge-bridge] queue:<code> priority:<n>
        # marker line, possibly as `-# ` subtext. Parse whichever is present (so
        # completion can fire -z removequeue) and strip the marker from the display.
        if queue_code is None:
            for att in message.attachments:
                fm = re.match(r'surge-q([A-Za-z0-9]+)-p(\d+)-', att.filename or "")
                if fm:
                    queue_code, priority = fm.group(1), int(fm.group(2))
                    break
        if queue_code is None:
            qm = re.search(r'queue:(\S+)', text)
            if qm:
                queue_code = qm.group(1)
            pm = re.search(r'priority:(\d+)', text)
            if pm:
                priority = int(pm.group(1))
        text = re.sub(r'(?:-# *)?\[surge-bridge\][^\n]*\n?', '', text).strip()
        image_urls = [a.url for a in message.attachments]
        if not image_urls and message.content:
            # bot-forwarded CDN url in text
            for tok in message.content.split():
                low = tok.lower()
                if 'cdn.discordapp.com' in low or 'media.discordapp.net' in low or low.endswith(_IMG_EXT):
                    image_urls.append(tok)

        # _assign_lock serializes find_next_available + _assign so that a concurrent drain
        # can't claim the same free maker before the DB record is committed.
        async with self._assign_lock:
            nxt = await self.find_next_available_surge_user(guild)
            if nxt is None:
                # HOLD: persist with downloaded image so it survives restarts.
                held_dir = os.path.join(cfg.SURGE_FILES_DIR, "pending")
                local = await self._download_images(image_urls, held_dir, prefix=f"{message.id}")
                await sdb.enqueue_surge_pending_map(
                    guild_id=guild.id, source_message_id=message.id, queue_code=queue_code,
                    priority=priority, map_details=text[:500] if text else None,
                    image_refs=json.dumps(image_urls), local_files=json.dumps(local),
                    is_lucky_map=is_lucky,
                )
                try:
                    await message.add_reaction("⏳")
                except Exception:
                    pass
                await _wave_log_event(category=cfg.WAVE_LOG_CATEGORY, action="map_held",
                                      guild=guild, details={"reason": "no_maker_available", "queue_code": queue_code})
                await auto_update_surge_route_leaderboard(self.bot, triggered_by="map_held")
                return

            rank, uid = nxt
            if not user_has_surge_maker_role(guild, uid):
                logger.error(f"[Surge Routes] ⛔ {uid} in rotation but lacks the Surge Route Maker role")
                try:
                    await message.add_reaction("⚠️")
                except Exception:
                    pass
                return

            await self._assign(guild, uid, rank, text, image_urls, is_lucky, queue_code,
                               source_attachments=message.attachments)
        try:
            await message.add_reaction("✅")
        except Exception:
            pass

    # =====================================================================
    # CORE ASSIGN
    # =====================================================================
    async def _assign(self, guild, user_id, rank, text, image_urls, is_lucky, queue_code,
                      source_attachments=None, source_local_files=None, source="auto", actor=None):
        notify = guild.get_channel(cfg.SURGE_NOTIFICATION_CHANNEL_ID)
        if not notify:
            logger.error("[Surge Routes] notification channel not found")
            return None

        assignment_id = await sdb.create_surge_route_assignment(
            user_id=user_id, guild_id=guild.id, notification_message_id=0, confirmation_message_id=0,
            map_details=text[:500] if text else None, is_lucky_map=is_lucky, queue_code=queue_code,
        )
        if not assignment_id:
            return None

        header = (f"⚡🍀 **LUCKY SURGE ROUTE #{assignment_id}** 🍀\n<@{user_id}>\n🎉 **2× points on this route!**"
                  if is_lucky else f"⚡ **Surge Route #{assignment_id}**\n<@{user_id}>")
        if text:
            header += f"\n{text}"

        files = await self._build_files(assignment_id, image_urls, source_attachments, source_local_files)
        try:
            notif_msg = await notify.send(content=header, files=files) if files else await notify.send(content=header)
        except Exception as e:
            logger.error(f"[Surge Routes] failed to post assignment card: {e}")
            return None

        confirm_embed = discord.Embed(
            description=(f"<@{user_id}>, react to confirm you've seen this surge route and will complete it.\n\n"
                         f"**Assignment ID:** #{assignment_id}\n\n"
                         f"Can't do it? DM <@&{cfg.HEAD_SURGE_ROUTES_ROLE_ID}> immediately."),
            color=0xE67E22,
        )
        confirm_msg = await notify.send(embed=confirm_embed)
        await sdb.update_surge_assignment_message_ids(assignment_id, notif_msg.id, confirm_msg.id)

        # Persist the saved local files for >cancelsurge reassignment.
        saved = await self._download_images(image_urls, os.path.join(cfg.SURGE_FILES_DIR, str(assignment_id)),
                                            prefix="img") if image_urls else []
        if saved:
            await sdb.save_surge_route_local_files(assignment_id, saved)

        # Update rotation pointer.
        surge_rotation_state['last_assigned_user_id'] = user_id
        surge_rotation_state['last_assigned_position'] = rank
        new_total = await sdb.increment_surge_total_assignments()
        surge_rotation_state['total_assignments'] = new_total
        await sdb.save_surge_rotation_state(last_assigned_user_id=user_id, last_assigned_position=rank,
                                            total_assignments=new_total)

        # DM the maker.
        try:
            member = guild.get_member(user_id)
            if member:
                await member.send(
                    (f"⚡🍀 **LUCKY SURGE ROUTE ASSIGNMENT!** (#{assignment_id})\n"
                     f"Complete it fast for **2× points**! {notif_msg.jump_url}\n\nReact on the confirmation to acknowledge."
                     if is_lucky else
                     f"⚡ **New Surge Route Assignment** (#{assignment_id})\n{notif_msg.jump_url}\n\nReact on the confirmation to acknowledge.")
                )
        except Exception:
            pass

        # Assignment log feed (auto + manual) — mirrors loot's LOG_CHANNEL_ID one-liner.
        log_channel = guild.get_channel(cfg.SURGE_MAPS_WORKED_ON_CHANNEL_ID)
        if log_channel:
            if source == "manual":
                emoji, label = ("🔧", f"Surge Manual #{assignment_id}")
            elif source == "reassign":
                emoji, label = ("♻️", f"Surge Reassign #{assignment_id}")
            else:
                emoji, label = ("⚡", f"Surge Auto #{assignment_id}")
            by = f" by {actor}" if actor else ""
            if is_lucky:
                log_content = f"{emoji}🍀 **LUCKY {label}**{by} — <@{user_id}> — **2× points!** {notif_msg.jump_url}"
            else:
                log_content = f"{emoji} **{label}**{by} — <@{user_id}> {notif_msg.jump_url}"
            try:
                await log_channel.send(content=log_content)
            except Exception as e:
                logger.error(f"[Surge Routes] failed to post assignment log: {e}")

        await _wave_log_event(category=cfg.WAVE_LOG_CATEGORY, action="route_assigned",
                              target={"id": str(user_id)}, guild=guild,
                              details={"assignment_id": assignment_id, "is_lucky_map": is_lucky,
                                       "queue_code": queue_code, "rank": rank})
        await auto_update_surge_route_leaderboard(self.bot, triggered_by="route_assigned")
        logger.info(f"[Surge Routes] ✅ Assigned #{assignment_id} to {user_id} (rank {rank}, lucky={is_lucky})")
        return assignment_id

    # =====================================================================
    # PENDING-POOL DRAIN  (assign held maps to freed-up makers)
    # =====================================================================
    async def drain_pending_pool(self, reason: str = "drain"):
        """Assign held maps (highest customer priority first) while makers are free."""
        async with self._drain_lock:
            guild = self.bot.get_guild(cfg.GUILD_ID)
            if not guild:
                return
            placed = 0
            while True:
                if await sdb.count_surge_pending_maps() == 0:
                    break
                pending = None
                aid = None
                # _assign_lock: hold across find+assign so handle_surge_request can't race us.
                async with self._assign_lock:
                    nxt = await self.find_next_available_surge_user(guild)
                    if nxt is None:
                        break  # no free maker → leave the rest held
                    pending = await sdb.get_oldest_surge_pending_map()
                    if not pending:
                        break
                    rank, uid = nxt
                    if not user_has_surge_maker_role(guild, uid):
                        break
                    image_urls = json.loads(pending.get('image_refs') or '[]')
                    local_files = json.loads(pending.get('local_files') or '[]')
                    aid = await self._assign(
                        guild, uid, rank, pending.get('map_details') or "", image_urls,
                        bool(pending.get('is_lucky_map')), pending.get('queue_code'),
                        source_local_files=local_files,
                    )
                if not aid:
                    break  # don't drop the pending map if assignment failed
                await sdb.delete_surge_pending_map(pending['id'])
                placed += 1
            if placed:
                logger.info(f"[Surge Routes] drained {placed} held map(s) ({reason})")
                await auto_update_surge_route_leaderboard(self.bot, triggered_by=f"drain_{reason}")

    # =====================================================================
    # FILE HELPERS
    # =====================================================================
    async def _download_images(self, urls, dest_dir: str, prefix: str = "img") -> list:
        if not urls:
            return []
        os.makedirs(dest_dir, exist_ok=True)
        saved = []
        try:
            async with aiohttp.ClientSession() as session:
                for i, url in enumerate(urls):
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                name = url.split('?')[0].split('/')[-1] or f"{prefix}_{i}.png"
                                dest = os.path.join(dest_dir, f"{prefix}_{i}_{name}")
                                with open(dest, 'wb') as f:
                                    f.write(await resp.read())
                                saved.append(dest)
                    except Exception as e:
                        logger.warning(f"[Surge Routes] image download failed ({url}): {e}")
        except Exception as e:
            logger.warning(f"[Surge Routes] download session error: {e}")
        return saved

    async def _build_files(self, assignment_id, image_urls, source_attachments, source_local_files):
        """Build discord.File list for the assignment card from attachments / local files / URLs."""
        files = []
        try:
            if source_attachments:
                for att in source_attachments:
                    files.append(await att.to_file())
            elif source_local_files:
                for p in source_local_files:
                    if os.path.exists(p):
                        files.append(discord.File(p))
            elif image_urls:
                tmp = await self._download_images(image_urls, os.path.join(cfg.SURGE_FILES_DIR, "tmp"),
                                                  prefix=f"a{assignment_id}")
                for p in tmp:
                    files.append(discord.File(p))
        except Exception as e:
            logger.warning(f"[Surge Routes] build files error: {e}")
        return files


# ============================================================================
# LEADERBOARD (Phase 6) — builds the payload and pushes surge_routes_leaderboard.json
# to the wave-leaderboard repo (distinct filename from loot → purely additive).
# ============================================================================
_debounce_surge_task = None
_debounce_surge_bot = None


async def auto_update_surge_route_leaderboard(bot, triggered_by="route_completed"):
    """Debounced trigger — collapses rapid changes into a single GitHub push."""
    global _debounce_surge_task, _debounce_surge_bot
    if _debounce_surge_task:
        try:
            _debounce_surge_task.cancel()
        except Exception:
            pass
    _debounce_surge_bot = bot
    _debounce_surge_task = asyncio.create_task(_wait_then_update_surge_leaderboard())


async def _wait_then_update_surge_leaderboard():
    try:
        await asyncio.sleep(1.5)
        await _do_update_surge_leaderboard()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[Surge Routes] leaderboard update error: {e}")


def _fmt_dur(hours):
    if hours is None:
        return "—"
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 24:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


async def _do_update_surge_leaderboard():
    bot = _debounce_surge_bot
    if not bot:
        return
    guild = bot.get_guild(cfg.GUILD_ID)
    if not guild:
        return

    rotation_positions = await sdb.get_all_surge_route_positions()  # [(rank, uid)]
    all_ids = [uid for _, uid in rotation_positions]
    if not all_ids:
        logger.info("[Surge Routes] no makers in rotation — skipping leaderboard")
        return

    points_lookup = {uid: (pts, routes) for uid, pts, routes in await sdb.get_surge_route_points_leaderboard(limit=500)}
    full = [(uid, *points_lookup.get(uid, (0.0, 0))) for uid in all_ids]
    full.sort(key=lambda x: x[2], reverse=True)

    maker_role = _find_role_by_name(guild, cfg.SURGE_MAKER_ROLE_NAME)
    maker_ids = {m.id for m in maker_role.members} if maker_role else set()

    pool = await get_pool()

    fastest_uid = None
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT user_id FROM surge_route_assignments WHERE status='completed' AND points_awarded>0 "
            "ORDER BY (julianday(completed_at)-julianday(assigned_at)) ASC LIMIT 1") as c:
            row = await c.fetchone()
            if row:
                fastest_uid = row[0]
    lucky_completers = set()
    async with pool.acquire() as db:
        async with db.execute("SELECT DISTINCT user_id FROM surge_route_assignments WHERE is_lucky_map=1 AND status='completed'") as c:
            for r in await c.fetchall():
                lucky_completers.add(r[0])

    # Build rotation rank lookup from the already-fetched positions list (avoids N per-maker DB queries).
    rotation_rank_map = {uid: rank for rank, uid in rotation_positions}

    # Bulk-fetch avg completion hours for all makers in one query.
    avg_hours_map = {}
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT user_id, AVG(CAST((julianday(completed_at)-julianday(assigned_at)) AS REAL)*24) "
            "FROM surge_route_assignments WHERE status='completed' GROUP BY user_id") as c:
            for row in await c.fetchall():
                avg_hours_map[row[0]] = round(row[1], 2) if row[1] else None

    players = []
    for uid, total_points, routes_completed in full:
        if maker_role and uid not in maker_ids:
            continue
        member = guild.get_member(uid)
        name = member.display_name if member else f"User {uid}"
        avatar = web_avatar_url(member.display_avatar) if member else None
        rotation_rank = rotation_rank_map.get(uid)
        avg_hours = avg_hours_map.get(uid)

        badges = []
        if routes_completed >= 1:
            badges.append("first_route")
        if routes_completed >= 10:
            badges.append("routes_10")
        if routes_completed >= 25:
            badges.append("routes_25")
        if uid == fastest_uid:
            badges.append("fastest")
        if uid in lucky_completers:
            badges.append("lucky_map")

        players.append({
            "user_id": str(uid), "display_name": name, "avatar_url": avatar,
            "routes_completed": routes_completed,
            "avg_completion_time": _fmt_dur(avg_hours), "avg_completion_hours": avg_hours,
            "rotation_rank": rotation_rank,
            "is_active": routes_completed > 0, "badges": badges,
        })

    # Rank deltas vs snapshot
    snap_path = cfg.SURGE_RANK_SNAPSHOT
    prev = {}
    try:
        if os.path.exists(snap_path):
            with open(snap_path) as f:
                prev = json.load(f)
    except Exception:
        pass
    new_snap = {}
    for i, p in enumerate(players):
        rank = i + 1
        uid_s = str(p['user_id'])
        p['rank_delta'] = (prev[uid_s] - rank) if uid_s in prev else None
        new_snap[uid_s] = rank
    try:
        os.makedirs(os.path.dirname(snap_path), exist_ok=True)
        with open(snap_path, 'w') as f:
            json.dump(new_snap, f)
    except Exception:
        pass

    # Rotation queue + next up
    away_role = guild.get_role(cfg.SURGE_AWAY_ROLE_ID)
    away_ids = {m.id for m in away_role.members} if away_role else set()
    async with pool.acquire() as db:
        async with db.execute("SELECT user_id, status FROM surge_route_assignments WHERE status IN ('pending','confirmed')") as c:
            active = {r[0]: r[1] for r in await c.fetchall()}
    players_by_uid = {p['user_id']: p for p in players}
    rotation, next_up_rank = [], None
    for rank, uid in rotation_positions:
        mem = guild.get_member(uid)
        is_away = uid in away_ids
        status = active.get(uid)
        pd = players_by_uid.get(uid, {})
        rotation.append({
            "rank": rank, "user_id": str(uid),
            "display_name": mem.display_name if mem else f"User {uid}",
            "avatar_url": web_avatar_url(mem.display_avatar) if mem else None,
            "is_away": is_away, "assignment_status": status,
            "routes_completed": pd.get("routes_completed", 0),
        })
        if next_up_rank is None and not is_away and status is None:
            next_up_rank = rank

    # Lucky maps
    lucky_maps = []
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT assignment_id, user_id, assigned_at, completed_at, points_awarded FROM surge_route_assignments "
            "WHERE is_lucky_map=1 AND status='completed' ORDER BY completed_at DESC") as c:
            for aid, luid, a_at, c_at, pa in await c.fetchall():
                mem = guild.get_member(luid)
                hrs = None
                try:
                    if a_at and c_at:
                        hrs = round((datetime.fromisoformat(c_at.replace('Z', '+00:00'))
                                     - datetime.fromisoformat(a_at.replace('Z', '+00:00'))).total_seconds() / 3600, 1)
                except Exception:
                    pass
                lucky_maps.append({"assignment_id": aid, "user_id": str(luid),
                                   "display_name": mem.display_name if mem else f"User {luid}",
                                   "completed_at": c_at, "hours_taken": hrs, "points_awarded": pa})
    lucky_counts = Counter(m["user_id"] for m in lucky_maps)
    lucky_names = {m["user_id"]: m["display_name"] for m in lucky_maps}
    top10_lucky = [{"display_name": lucky_names[u], "count": cnt} for u, cnt in lucky_counts.most_common(10)]

    # Global + weekly
    global_stats = {"total_routes": 0, "avg_completion_hours": None,
                    "fastest_hours": None, "total_makers": 0, "total_lucky_maps": len(lucky_maps)}
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT COUNT(*), AVG(CAST((julianday(completed_at)-julianday(assigned_at)) AS REAL)*24), "
            "MIN(CAST((julianday(completed_at)-julianday(assigned_at)) AS REAL)*24), COUNT(DISTINCT user_id) "
            "FROM surge_route_assignments WHERE status='completed'") as c:
            r = await c.fetchone()
            if r and r[0]:
                global_stats.update({"total_routes": r[0] or 0,
                                     "avg_completion_hours": round(r[1], 1) if r[1] else None,
                                     "fastest_hours": round(r[2], 1) if r[2] else None, "total_makers": r[3] or 0})
    weekly_data = []
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT date(completed_at, '-' || ((cast(strftime('%w', completed_at) as integer)+6)%7) || ' days') wk, "
            "COUNT(*) FROM surge_route_assignments "
            "WHERE status='completed' AND completed_at >= datetime('now','-112 days') "
            "GROUP BY wk ORDER BY wk ASC") as c:
            for wk, routes in await c.fetchall():
                try:
                    label = datetime.strptime(wk, "%Y-%m-%d").strftime("%d %b").lstrip("0")
                except Exception:
                    label = wk
                weekly_data.append({"week": wk, "label": label, "routes": routes or 0})

    # --- Per-user cumulative route history (top 5 by routes completed; last ~16 weeks) ---
    route_history = []
    try:
        top5_ids = [p["user_id"] for p in sorted(players, key=lambda p: p.get("routes_completed", 0), reverse=True)[:5]]
        today = date.today()
        today_monday = (today - timedelta(days=today.weekday())).isoformat()
        _wk_expr = ("date(completed_at, '-' || ((cast(strftime('%w', completed_at) as integer)+6)%7) || ' days')")
        async with pool.acquire() as db:
            for uid in top5_ids:
                pdata = next((p for p in players if p["user_id"] == uid), None)
                disp = pdata["display_name"] if pdata else f"User {uid}"

                # cumulative routes
                async with db.execute(
                    f"SELECT {_wk_expr} wk, COUNT(*) FROM surge_route_assignments "
                    "WHERE user_id=? AND status='completed' AND points_awarded>0 "
                    "AND completed_at >= datetime('now','-112 days') GROUP BY wk ORDER BY wk ASC", (uid,)) as c:
                    r_rows = await c.fetchall()
                rhist, rcum = [], 0
                for wk, n in r_rows:
                    rcum += n or 0
                    rhist.append({"week": wk, "cumulative": rcum})
                real_routes = pdata["routes_completed"] if pdata else rcum
                if not rhist or rhist[-1]["week"] < today_monday:
                    rhist.append({"week": today_monday, "cumulative": real_routes})
                if rhist:
                    route_history.append({"user_id": str(uid), "display_name": disp, "history": rhist})
    except Exception as e:
        logger.warning(f"[Surge Routes] history build failed: {e}")

    payload = {
        "players": players, "rotation": rotation, "next_up_rank": next_up_rank,
        "lucky_maps": lucky_maps,
        "lucky_maps_stats": {"total_triggered": len(lucky_maps)},
        "top10_lucky_maps": top10_lucky, "global_stats": global_stats, "weekly_data": weekly_data,
        "route_history": route_history,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"📊 [Surge Routes] Prepared {len(players)} players for leaderboard")
    try:
        from tasks.staff_hub_writer import push_surge_route_leaderboard_to_github
        await push_surge_route_leaderboard_to_github(payload)
    except Exception as e:
        logger.error(f"[Surge Routes] leaderboard push failed: {e}")


async def setup(bot):
    await bot.add_cog(SurgeRoutes(bot))
    logger.info("✅ SurgeRoutes cog loaded")
