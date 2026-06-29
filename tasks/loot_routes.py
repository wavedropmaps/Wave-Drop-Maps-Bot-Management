"""
Loot Routes - Automatic Map Rotation System
✅ VERSION 2.1 - FIXED POSITION NUMBERS TO MATCH ROTATION + ROLE VALIDATION ✅
✅ Leaderboard position numbers MUST match rotation message exactly
✅ Loot Route Points can ONLY be given to users with Loot Route Maker role
✅ Edits existing rotation message to track assignments
✅ Detects forwarded map requests from Map Request Forwarder bot
✅ DATABASE INTEGRATION: Loot Route Points, leaderboards, and 24-hour reminder system
✅ Auto-updates leaderboard when routes are completed
✅ Sends 24-hour reminders until user confirms assignment
✅ AUTOMATIC LEADERBOARD MANAGEMENT: Creates/updates on startup + every 24 hours
✅ LEADERBOARD FORMAT: ROTATION_POSITION. Name (UserID) - Loot Route Points
"""

import discord
from discord.ext import commands, tasks
import re
import asyncio
import random
import json
import os
from collections import Counter
from typing import Optional, List, Tuple
from datetime import datetime, timezone, date, timedelta
import logging

# Wave-Logging dashboard publisher (mirrors loot-channel events to the dashboard;
# category "loot_routes" → data/manager/loot_routes/ on the Wave-Logging repo)
from core.global_logger import log_event as _wave_log_event
from core.helpers import web_avatar_url

# Import database functions - ✅ FIXED: Using correct function names from database.py
# NOTE: *_loot_route_points are LEADERBOARD helpers (routes_completed count), NOT a
# currency. Spendable currency is Wave Points. See naming note in database.py.
from database import (
    get_pool,
    add_loot_route_points,
    get_loot_route_user_points,
    get_loot_route_points_leaderboard,
    create_route_assignment,
    update_assignment_message_ids,  # ✅ NEW: Update message IDs after creation
    confirm_route_assignment,
    get_assignment_by_confirmation_message,
    get_assignment_by_notification_message,
    get_route_assignment_by_id,
    get_assignments_needing_reminders,
    update_reminder_sent,
    save_rotation_state,
    get_rotation_state,
    increment_total_assignments,
    cleanup_old_route_assignments,
    get_all_loot_route_positions,
    get_all_away_return_dates,
    enqueue_loot_pending_map,
    get_oldest_loot_pending_map,
    count_loot_pending_maps,
    delete_loot_pending_map,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================
GUILD_ID = 1041450125391835186
MAP_REQUEST_CHANNEL_ID = 1205406903463710750  # maps-not-taken
ROTATION_CHANNEL_ID = 1239193678459703447  # rotation
NOTIFICATION_CHANNEL_ID = 1231195722485993512  # claim-loot-route
LOG_CHANNEL_ID = 1249416251759919246  # assignment log channel (auto + manual assignments)
MEMBER_UPDATES_CHANNEL_ID = 1243623718190714921  # member updates (role changes, weekly MVP)
LEADERBOARD_CHANNEL_ID = 1251145459179716618  # leaderboard
AWAY_ROLE_ID = 1495685790452420608  # Loot Route Away role (staffhub server)
LOOT_ROUTE_MAKER_ROLE_ID = 1231188006757728266  # Loot Route Maker role
HEAD_LOOT_ROUTES_ROLE_ID = 1231187220208025620  # Head Loot Routes role

LUCKY_MAP_CHANCE = 0.33  # 33% chance of a Lucky Map per assignment

# Track rotation state (loaded from database on startup)
rotation_state = {
    'last_assigned_position': 0,
    'last_assigned_user_id': None,
    'total_assignments': 0,
    'sticky_message_id': None,
}


# ============================================================================
# ✅ ROLE VALIDATION HELPER
# ============================================================================

def user_has_loot_route_role(guild: discord.Guild, user_id: int) -> bool:
    """
    ✅ CRITICAL: Check if user has Loot Route Maker role
    Users WITHOUT this role CANNOT receive Loot Route Points
    """
    member = guild.get_member(user_id)
    if not member:
        return False
    
    has_role = any(role.id == LOOT_ROUTE_MAKER_ROLE_ID for role in member.roles)
    
    if not has_role:
        logger.warning(f"[Loot Routes] ⛔ BLOCKED: User {member.name} ({user_id}) does NOT have Loot Route Maker role!")
    
    return has_role


# ============================================================================
# LOOT ROUTES CLASS
# ============================================================================

class LootRoutes(commands.Cog):  # ✅ Added (commands.Cog) inheritance
    """Handles automatic map rotation system with database integration"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.skip_auto_regen = False
        self._init_task = None
        self._sticky_lock = asyncio.Lock()  # Prevents double-posting the sticky message
        self._drain_lock = asyncio.Lock()   # Serializes hold-pool drains (no double-assign)
        self._assign_lock = asyncio.Lock()  # Prevents race between handle_map_request and drain
        self.setup_listeners()
        print("[Loot Routes] ✅ Map rotation system loaded")
        print("[Loot Routes] 🔥 VERSION 2.1 - POSITION NUMBERS MATCH ROTATION + ROLE VALIDATION")

    async def cog_load(self):
        """Spawn initialize() as a background task so it waits for bot ready without blocking setup()"""
        self._init_task = asyncio.create_task(self._initialize_when_ready())

    async def _initialize_when_ready(self):
        """Wait for bot to be ready, then run initialize()"""
        await self.bot.wait_until_ready()
        await self.initialize()

    def cog_unload(self):
        if self._init_task:
            self._init_task.cancel()
        if self.reminder_check_loop.is_running():
            self.reminder_check_loop.cancel()
        if self.daily_cleanup_loop.is_running():
            self.daily_cleanup_loop.cancel()
        if self.weekly_mvp_loop.is_running():
            self.weekly_mvp_loop.cancel()
    
    async def initialize(self):
        """Initialize and load rotation state from database"""
        try:
            # Database is initialized by main bot - just load rotation state
            saved_state = await get_rotation_state()
            if saved_state:
                rotation_state.update(saved_state)
                print(f"[Loot Routes] ✅ Loaded rotation state from database")
                print(f"[Loot Routes]    - Last position: {rotation_state['last_assigned_position']}")
                print(f"[Loot Routes]    - Total assignments: {rotation_state['total_assignments']}")
            
            # ✅ ONE-TIME MIGRATION: archive pre-existing non-team members
            # After this runs once, on_member_update handles it automatically going forward.
            try:
                from database import archive_loot_route_maker, get_pool
                _MIGRATION = 'loot_route_alumni_initial_archive'
                pool = await get_pool()
                async with pool.acquire() as db:
                    async with db.execute(
                        'SELECT 1 FROM migrations WHERE migration_name = ?', (_MIGRATION,)
                    ) as cur:
                        already_done = await cur.fetchone()

                if not already_done:
                    guild = self.bot.get_guild(GUILD_ID)
                    if guild:
                        maker_role = guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
                        if maker_role:
                            maker_ids = {m.id for m in maker_role.members}
                            async with pool.acquire() as db:
                                async with db.execute('SELECT user_id FROM loot_route_positions') as cur:
                                    pos_ids = {row[0] for row in await cur.fetchall()}
                                async with db.execute('SELECT user_id FROM loot_route_points') as cur:
                                    pts_ids = {row[0] for row in await cur.fetchall()}
                            orphans = (pos_ids | pts_ids) - maker_ids
                            if orphans:
                                print(f"[Loot Routes] 📦 One-time migration: archiving {len(orphans)} non-team member(s)...")
                                for uid in orphans:
                                    member = guild.get_member(uid)
                                    display_name = member.display_name if member else None
                                    archived = await archive_loot_route_maker(user_id=uid, display_name=display_name)
                                    print(f"[Loot Routes] {'📦 Archived' if archived else 'ℹ️ No data for'} {uid} ({display_name})")
                            else:
                                print("[Loot Routes] ✅ One-time migration: no orphaned makers found")

                        # Mark migration complete — never runs again
                        async with pool.acquire() as db:
                            await db.execute(
                                'INSERT OR IGNORE INTO migrations (migration_name) VALUES (?)', (_MIGRATION,)
                            )
                            await db.commit()
                        print("[Loot Routes] ✅ One-time alumni migration complete — flagged in migrations table")
                else:
                    print("[Loot Routes] ⏭️ Alumni migration already ran — skipping")
            except Exception as e:
                print(f"[Loot Routes] ⚠️ Alumni migration failed: {e}")

            # ✅ SYNC LOOT ROUTE LEADERBOARD TO GITHUB PAGES ON STARTUP
            try:
                print("[Loot Routes] 🌐 Syncing loot route leaderboard to GitHub on startup...")
                await auto_update_loot_route_leaderboard(self.bot, triggered_by="bot_startup")
                print("[Loot Routes] ✅ GitHub Pages leaderboard synced")
            except Exception as e:
                print(f"[Loot Routes] ⚠️ GitHub Pages sync failed on startup: {e}")

            # Start background tasks
            if not self.reminder_check_loop.is_running():
                self.reminder_check_loop.start()
                print("[Loot Routes] ✅ Started reminder check loop")
            
            if not self.daily_cleanup_loop.is_running():
                self.daily_cleanup_loop.start()
                print("[Loot Routes] ✅ Started daily cleanup loop")
            
            # ✅ START WEEKLY MVP LOOP
            if not self.weekly_mvp_loop.is_running():
                self.weekly_mvp_loop.start()
                print("[Loot Routes] ✅ Started weekly MVP loop")

            # Drain any maps that were held while the bot was down (assign to free makers).
            try:
                held = await count_loot_pending_maps()
                if held:
                    print(f"[Loot Routes] ⏳ {held} held map(s) found on startup — draining...")
                    await self.drain_loot_pending_pool(reason="startup")
            except Exception as e:
                print(f"[Loot Routes] ⚠️ Startup drain failed: {e}")

        except Exception as e:
            print(f"[Loot Routes] ❌ Initialization error: {e}")
            import traceback
            traceback.print_exc()
    
    def setup_listeners(self):
        """Register event listeners"""
        
        @self.bot.listen('on_message')
        async def on_loot_route_message(message: discord.Message):
            """Listen for map requests"""
            
            # Check if in correct guild and channel
            if not (message.guild and 
                    message.guild.id == GUILD_ID and 
                    message.channel.id == MAP_REQUEST_CHANNEL_ID):
                return
            
            # ✅ SMART DETECTION: Allow bot messages ONLY if they contain images/attachments
            if message.author.bot:
                has_image = False
                has_text = bool(message.content.strip()) if message.content else False
                
                if message.attachments:
                    has_image = True
                
                if message.content:
                    if any(ext in message.content.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                        has_image = True
                    if 'cdn.discordapp.com' in message.content or 'media.discordapp.net' in message.content:
                        has_image = True
                
                if not (has_image and has_text):
                    print(f"[Loot Routes] ⏭️ Ignoring bot message - Missing image or text (Image: {has_image}, Text: {has_text})")
                    return
                
                print(f"[Loot Routes] ✅ DETECTED FORWARDED MAP REQUEST from bot: {message.author.name}")
            else:
                has_image = False
                has_text = bool(message.content.strip()) if message.content else False
                
                if message.attachments:
                    has_image = True
                
                if message.content:
                    if any(ext in message.content.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                        has_image = True
                    if 'cdn.discordapp.com' in message.content or 'media.discordapp.net' in message.content:
                        has_image = True
                
                if not (has_image and has_text):
                    print(f"[Loot Routes] ⏭️ Ignoring message - Missing image or text (Image: {has_image}, Text: {has_text})")
                    await message.add_reaction("⚠️")
                    return
            
            print(f"[Loot Routes] ✅ MAP REQUEST DETECTED in #{message.channel.name}")
            await self.handle_map_request(message)
        
        @self.bot.listen('on_message')
        async def on_claim_loot_route_message(message: discord.Message):
            """Listen for ANY message in claim-loot-route channel to repost sticky"""
            
            if not (message.guild and 
                    message.guild.id == GUILD_ID and 
                    message.channel.id == NOTIFICATION_CHANNEL_ID):
                return
            
            if message.author.id == self.bot.user.id and "📌" in message.content and "Loot Route Resources" in message.content:
                return
            
            await asyncio.sleep(0.5)
            await self.update_sticky_message(message.guild)
        
        @self.bot.listen('on_raw_reaction_add')
        async def on_confirmation_reaction(payload: discord.RawReactionActionEvent):
            """Handle confirmation reactions to mark assignments complete.
            Uses on_raw_reaction_add so it works even after a bot restart
            when the message is no longer in the cache.
            """

            # Ignore bot reactions
            if payload.user_id == self.bot.user.id:
                return

            # Only care about the notification channel
            if payload.channel_id != NOTIFICATION_CHANNEL_ID:
                return

            print(f"[Loot Routes] 🔔 Raw reaction detected from user {payload.user_id} on message {payload.message_id}")

            # Fetch the guild/channel so we can get the full message from the API
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return

            channel = guild.get_channel(payload.channel_id)
            if not channel:
                return

            # Always fetch from API — don't rely on cache
            try:
                message = await channel.fetch_message(payload.message_id)
            except Exception as e:
                print(f"[Loot Routes] ⚠️ Could not fetch message {payload.message_id}: {e}")
                return

            # Accept a reaction on EITHER the confirmation embed OR the route card (notification message)
            assignment_id = await get_assignment_by_confirmation_message(payload.message_id)
            if not assignment_id:
                assignment_id = await get_assignment_by_notification_message(payload.message_id)

            print(f"[Loot Routes] 🔍 Looking for assignment with confirmation message ID: {payload.message_id}")
            print(f"[Loot Routes] 📊 Found assignment ID: {assignment_id}")

            if assignment_id:
                assignment = await get_route_assignment_by_id(assignment_id)

                # Only the assigned user's reaction counts
                if not assignment or assignment.get('user_id') != payload.user_id:
                    print(f"[Loot Routes] ⏭️ Ignored reaction from non-assigned user {payload.user_id} on assignment #{assignment_id}")
                    return

                if assignment.get('status') == 'pending':
                    await confirm_route_assignment(assignment_id)
                    print(f"[Loot Routes] ✅ Marked assignment #{assignment_id} as confirmed")
                conf_id = assignment.get('confirmation_message_id')
                try:
                    conf_msg = message if (conf_id and conf_id == payload.message_id) else (await channel.fetch_message(conf_id) if conf_id else None)
                    if conf_msg:
                        await conf_msg.delete()
                        print(f"[Loot Routes] ✅ User {payload.user_id} confirmed assignment #{assignment_id} - Deleted confirmation embed")
                except Exception as e:
                    print(f"[Loot Routes] ⚠️ Could not delete confirmation message: {e}")
            else:
                print(f"[Loot Routes] ❌ Could not find assignment for confirmation message {payload.message_id}")
            
        @self.bot.listen('on_member_update')
        async def on_loot_route_role_change(before: discord.Member, after: discord.Member):
            """Detect when Loot Route Maker role is added/removed and regenerate rotation"""
            
            # Only monitor the specific guild
            if after.guild.id != GUILD_ID:
                return
            
            # Check if Loot Route Maker role changed
            before_roles = set(role.id for role in before.roles)
            after_roles = set(role.id for role in after.roles)
            
            # Check if the Loot Route Maker role was added or removed
            role_added = LOOT_ROUTE_MAKER_ROLE_ID in after_roles and LOOT_ROUTE_MAKER_ROLE_ID not in before_roles
            role_removed = LOOT_ROUTE_MAKER_ROLE_ID in before_roles and LOOT_ROUTE_MAKER_ROLE_ID not in after_roles

            # Away role removed → maker is back; a held map may now be assignable.
            if AWAY_ROLE_ID in before_roles and AWAY_ROLE_ID not in after_roles:
                asyncio.create_task(self.drain_loot_pending_pool(reason="away_return"))

            if role_added or role_removed:
                # ✅ Skip if manual operation in progress
                if self.skip_auto_regen:
                    print(f"[Loot Routes] ⏭️ Skipping auto-regen (manual operation in progress)")
                    return
                
                action = "added to" if role_added else "removed from"
                print(f"[Loot Routes] 🔄 Loot Route Maker role {action} {after.name} - Regenerating rotation...")

                # NOTE: The Discord join/leave announcement is NOT posted here.
                # Staff add/remove makers via >dutyrolegive / >dutyroleremove, which
                # invoke the loot add/remove commands → those post the announcement
                # (see send_role_change_log). Posting here too would double-announce.
                # We still mirror EVERY role change to the Wave-Logging dashboard below
                # (universal catch-all — covers direct-UI role edits that bypass commands).
                await _wave_log_event(
                    category="loot_routes",
                    action="maker_joined" if role_added else "maker_left",
                    target=after,
                    guild=after.guild,
                    details={"source": "role_change"},
                )

                # Archive maker to alumni table when role is removed
                if role_removed:
                    try:
                        from database import archive_loot_route_maker
                        archived = await archive_loot_route_maker(
                            user_id=after.id,
                            display_name=after.display_name,
                        )
                        if archived:
                            print(f"[Loot Routes] 📦 Archived {after.name} to loot_route_alumni table")
                        else:
                            print(f"[Loot Routes] ℹ️ {after.name} had no active loot route data to archive")
                    except Exception as e:
                        print(f"[Loot Routes] ❌ Failed to archive alumni data for {after.name}: {e}")

                print(f"[Loot Routes] ✅ Role change processed for {after.name} — syncing GitHub Pages leaderboard")
                asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="role_change"))

                # A newly-added maker is free → try to assign any held maps.
                if role_added:
                    asyncio.create_task(self.drain_loot_pending_pool(reason="new_maker"))
    
    @tasks.loop(hours=1)
    async def reminder_check_loop(self):
        """Check for assignments needing reminders every hour"""
        try:
            print("[Loot Routes] 🔔 Checking for assignments needing reminders...")
            
            assignments = await get_assignments_needing_reminders()
            
            if not assignments:
                print("[Loot Routes] ℹ️ No reminders needed")
                return
            
            print(f"[Loot Routes] 📨 Sending {len(assignments)} reminder(s)...")
            
            for assignment in assignments:
                await self.send_reminder(assignment)
                await asyncio.sleep(2)  # Rate limiting
            
            print(f"[Loot Routes] ✅ Sent {len(assignments)} reminder(s)")
            
        except Exception as e:
            print(f"[Loot Routes] ❌ Error in reminder loop: {e}")
            import traceback
            traceback.print_exc()
    
    @reminder_check_loop.before_loop
    async def before_reminder_check(self):
        """Wait for bot to be ready before starting loop"""
        await self.bot.wait_until_ready()
    
    @tasks.loop(hours=24)
    async def daily_cleanup_loop(self):
        """Clean up old confirmed assignments daily"""
        try:
            deleted = await cleanup_old_route_assignments(days=30)
            if deleted > 0:
                print(f"[Loot Routes] 🗑️ Cleaned up {deleted} old assignments")
        except Exception as e:
            print(f"[Loot Routes] ❌ Error in cleanup loop: {e}")
    
    @daily_cleanup_loop.before_loop
    async def before_daily_cleanup(self):
        """Wait for bot to be ready before starting loop"""
        await self.bot.wait_until_ready()
    
    @tasks.loop(hours=24)
    async def weekly_mvp_loop(self):
        """Every Monday post the weekly Loot Route MVP to the log channel"""
        try:
            now = datetime.now(timezone.utc)
            if now.weekday() != 0:  # 0 = Monday
                return

            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return

            log_channel = guild.get_channel(MEMBER_UPDATES_CHANNEL_ID)
            if not log_channel:
                return

            this_week = now.isocalendar()[1]  # ISO week number
            this_year = now.year

            # ✅ NEW: Check database instead of message history to prevent race conditions
            from database import check_mvp_already_posted
            if await check_mvp_already_posted(guild.id, this_year, this_week):
                print(f"[Loot Routes] ⏭️ Weekly MVP already posted for week {this_week}/{this_year} — skipping")
                return

            # Query top earners over the last 7 days
            from database import get_pool as _get_pool
            pool = await _get_pool()
            async with pool.acquire() as db:
                async with db.execute(
                    """SELECT user_id, SUM(points_awarded) as weekly_pts
                       FROM route_assignments
                       WHERE status = 'completed'
                         AND completed_at >= datetime('now', '-7 days')
                         AND points_awarded > 0
                       GROUP BY user_id
                       ORDER BY weekly_pts DESC
                       LIMIT 5""",
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                print("[Loot Routes] ℹ️ No completions this week — skipping MVP post")
                return

            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            lines = []
            for i, (uid, pts) in enumerate(rows):
                member = guild.get_member(uid)
                name = member.display_name if member else f"<@{uid}>"
                lines.append(f"{medals[i]} **{name}** — `{pts:.1f} pts`")

            week_str = now.strftime("%d %B %Y").lstrip("0")
            mvp_uid = rows[0][0]
            mvp_pts = rows[0][1]

            leaderboard_text = "\n".join(lines).strip()
            msg_content = (
                f"🏆 **Weekly Loot Route MVP** — Week of {week_str}\n\n"
                f"{leaderboard_text}\n\n"
                f"🎉 Congratulations <@{mvp_uid}> for topping the leaderboard this week with **{mvp_pts:.1f} points**! 🍀"
            ).strip()

            posted_msg = await log_channel.send(msg_content)

            # ✅ Mirror to Wave-Logging dashboard
            await _wave_log_event(
                category="loot_routes",
                action="weekly_mvp",
                target={"id": str(mvp_uid)},
                guild=guild,
                details={
                    "week": this_week,
                    "year": this_year,
                    "mvp_points": round(float(mvp_pts), 1),
                    "top": [{"id": str(uid), "points": round(float(pts), 1)} for uid, pts in rows],
                },
            )

            # ✅ NEW: Save to database so we never post twice for the same week
            from database import save_mvp_post
            await save_mvp_post(guild.id, this_year, this_week, posted_msg.id)
            print(f"[Loot Routes] ✅ Weekly MVP posted for week {this_week}/{this_year}")

        except Exception as e:
            print(f"[Loot Routes] ❌ Error in weekly MVP loop: {e}")
            import traceback
            traceback.print_exc()

    @weekly_mvp_loop.before_loop
    async def before_weekly_mvp(self):
        await self.bot.wait_until_ready()
    
    async def send_reminder(self, assignment: dict):
        """Send DM reminder to user about pending confirmation, and alert Head Loot Routes staff."""
        try:
            user = await self.bot.fetch_user(assignment['user_id'])

            guild = self.bot.get_guild(assignment['guild_id'])
            if not guild:
                return

            notification_channel = guild.get_channel(NOTIFICATION_CHANNEL_ID)
            if not notification_channel:
                return

            # Get message link
            try:
                confirm_msg = await notification_channel.fetch_message(assignment['confirmation_message_id'])
                message_link = confirm_msg.jump_url
            except:
                message_link = f"https://discord.com/channels/{assignment['guild_id']}/{NOTIFICATION_CHANNEL_ID}/{assignment['confirmation_message_id']}"

            reminder_count = assignment['reminder_count'] + 1

            # ── DM the assigned user ──────────────────────────────────────
            reminder_text = f"🗺️ **Loot Route Reminder #{reminder_count}**\n\n"
            reminder_text += f"You have a pending loot route assignment that needs confirmation!\n\n"
            reminder_text += f"Please react to the confirmation message to acknowledge you've seen the assignment:\n"
            reminder_text += f"{message_link}\n\n"
            reminder_text += f"_This is reminder #{reminder_count}. You will receive reminders every 24 hours until you confirm._"

            try:
                await user.send(reminder_text)
                print(f"[Loot Routes] 📨 Sent reminder #{reminder_count} to user {user.name}")
            except discord.Forbidden:
                print(f"[Loot Routes] ⚠️ Cannot DM user {assignment['user_id']} - DMs disabled")

            # ── Alert Head Loot Routes staff on every reminder cycle ──────
            await self._alert_head_loot_routes(
                guild=guild,
                user=user,
                assignment_id=assignment['assignment_id'],
                reminder_count=reminder_count,
                message_link=message_link,
            )

            # Update database
            await update_reminder_sent(assignment['assignment_id'])

        except discord.Forbidden:
            print(f"[Loot Routes] ⚠️ Cannot DM user {assignment['user_id']} - DMs disabled")
        except Exception as e:
            print(f"[Loot Routes] ❌ Error sending reminder: {e}")

    async def _alert_head_loot_routes(
        self,
        guild: discord.Guild,
        user: discord.User,
        assignment_id: int,
        reminder_count: int,
        message_link: str,
    ):
        """
        DM every Head Loot Routes role member to notify them that someone
        has not reacted to their assignment confirmation after 24+ hours.
        Fires on every reminder cycle (every 24 hours) until they confirm.
        """
        head_role = guild.get_role(HEAD_LOOT_ROUTES_ROLE_ID)
        if not head_role:
            print(f"[Loot Routes] ⚠️ Head Loot Routes role {HEAD_LOOT_ROUTES_ROLE_ID} not found — skipping staff alert")
            return

        staff_members = [m for m in head_role.members if not m.bot and m.id != user.id]
        if not staff_members:
            print(f"[Loot Routes] ℹ️ No Head Loot Routes staff to alert")
            return

        hours_unconfirmed = reminder_count * 24
        alert_text = (
            f"⚠️ **Loot Route Unconfirmed — Reminder #{reminder_count}**\n\n"
            f"**{user.display_name}** (`{user.id}`) has **not reacted** to their loot route "
            f"confirmation message after **{hours_unconfirmed} hours**.\n\n"
            f"**Assignment ID:** #{assignment_id}\n"
            f"**Confirmation message:** {message_link}\n\n"
            f"_Please follow up with them if needed._"
        )

        sent = 0
        for staff in staff_members:
            try:
                await staff.send(alert_text)
                sent += 1
            except discord.Forbidden:
                print(f"[Loot Routes] ⚠️ Cannot DM Head Loot Routes staff {staff.name} - DMs disabled")
            except Exception as e:
                print(f"[Loot Routes] ⚠️ Error DMing staff {staff.name}: {e}")
            await asyncio.sleep(0.5)  # avoid rate limits

        print(f"[Loot Routes] 📣 Alerted {sent}/{len(staff_members)} Head Loot Routes staff about unconfirmed assignment #{assignment_id} (reminder #{reminder_count})")

    
    async def update_sticky_message(self, guild: discord.Guild):
        """
        Updates or creates the sticky message in claim-loot-route channel
        with helpful resource links. Deletes old sticky and posts new one at bottom.
        Uses a lock to prevent concurrent calls from double-posting.
        """
        async with self._sticky_lock:
            notification_channel = guild.get_channel(NOTIFICATION_CHANNEL_ID)
            if not notification_channel:
                return
            
            sticky_content = "**📌 Loot Route Resources**\n\n"
            sticky_content += f"<#{1425770558435364934}> Check out for making your route the best route!\n"
            sticky_content += f"<#{1284417570815868959}> Examples of perfect loot routes made before!\n"
            sticky_content += f"<#{1434730999820062720}> Guide of the whole loot route system here in wave!\n\n"
            sticky_content += "[Loot Routes key information](https://wavedropmaps.pages.dev/loot_routes_leaderboard.html)"
            
            try:
                if rotation_state['sticky_message_id']:
                    try:
                        old_sticky = await notification_channel.fetch_message(rotation_state['sticky_message_id'])
                        await old_sticky.delete()
                        print("[Loot Routes] 🗑️ Deleted old sticky message")
                    except discord.NotFound:
                        print("[Loot Routes] ⚠️ Old sticky message not found")
                    except Exception as e:
                        print(f"[Loot Routes] ⚠️ Error deleting old sticky: {e}")
                
                # Delete ALL existing stickies from history before posting a new one
                # Collect first, then delete (can't delete while iterating history)
                to_delete = []
                async for message in notification_channel.history(limit=100):
                    if message.author.id == self.bot.user.id and "📌" in message.content and "Loot Route Resources" in message.content:
                        to_delete.append(message)
                for msg in to_delete:
                    try:
                        await msg.delete()
                        print("[Loot Routes] 🗑️ Deleted existing sticky message")
                    except Exception:
                        pass
                
                sticky_msg = await notification_channel.send(sticky_content)
                rotation_state['sticky_message_id'] = sticky_msg.id
                print("[Loot Routes] ✅ Created new sticky message at bottom")
                
                # Save to database
                await save_rotation_state(sticky_message_id=sticky_msg.id)
                
            except Exception as e:
                print(f"[Loot Routes] ❌ Error updating sticky message: {e}")
    
    async def find_next_available_user(self, guild: discord.Guild, allow_fallback: bool = True) -> Optional[Tuple[int, int, str]]:
        """
        ✅ FIXED: Finds the next user in rotation who:
        - Does NOT have the away role
        - Does NOT already have an ACTIVE (pending or confirmed) assignment
        READS FROM DATABASE (not from message parsing which is error-prone)
        Returns: (position, user_id, username)
        """
        # ✅ READ DIRECTLY FROM DB - the source of truth
        try:
            from database import get_all_loot_route_positions
            positions = await get_all_loot_route_positions()
            if not positions:
                print("[Find Next User] ❌ No positions in database")
                return None

            positions.sort(key=lambda x: x[0])
            print(f"[Find Next User] 📋 Found {len(positions)} positions from database")
        except Exception as e:
            print(f"[Find Next User] ❌ Error reading positions from DB: {e}")
            return None

        # Build rotation_list from DB (position, user_id, name, is_away)
        rotation_list = []
        for position, user_id in positions:
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except:
                    member = None

            is_away = False
            if member:
                away_role = guild.get_role(AWAY_ROLE_ID)
                if away_role and away_role in member.roles:
                    is_away = True

            name = member.name if member else f"User {user_id}"
            rotation_list.append((position, user_id, name, is_away))

        # ✅ GET ONLY ACTIVE ASSIGNMENTS (pending + confirmed, NOT completed!)
        skip_user_ids = []
        try:
            from database import get_all_pending_assignments, get_all_confirmed_assignments
            pending_assignments = await get_all_pending_assignments()
            confirmed_assignments = await get_all_confirmed_assignments()

            # Only skip users with ACTIVE assignments (pending or confirmed)
            # Do NOT include completed assignments!
            active_assignments = pending_assignments + confirmed_assignments
            skip_user_ids = [a['user_id'] for a in active_assignments]

            print(f"[Find Next User] 📋 Found {len(pending_assignments)} pending + {len(confirmed_assignments)} confirmed = {len(skip_user_ids)} ACTIVE assignments")
        except ImportError:
            print("[Find Next User] ⚠️ Could not import assignment functions")
        except Exception as e:
            print(f"[Find Next User] ⚠️ Error getting active assignments: {e}")
        
        # Determine starting rank from last_assigned_user_id (robust to roster changes)
        last_user_id = rotation_state.get('last_assigned_user_id')
        last_rank = 0
        if last_user_id:
            for pos, uid, _name, _is_away in rotation_list:
                if uid == last_user_id:
                    last_rank = pos
                    break
        if last_rank == 0:
            last_rank = rotation_state.get('last_assigned_position', 0) or 0
            if last_rank > len(rotation_list):
                last_rank = 0

        start_pos = last_rank + 1
        if start_pos > len(rotation_list):
            start_pos = 1

        # ✅ FIXED: Loop checks BOTH away status AND active assignments (NOT completed!)
        for offset in range(len(rotation_list)):
            index = (start_pos - 1 + offset) % len(rotation_list)
            pos, uid, name, is_away = rotation_list[index]
            
            if is_away:
                print(f"[Find Next User] ⏭️  Position {pos}: {name} is AWAY - skipping")
                continue
            
            if uid in skip_user_ids:
                print(f"[Find Next User] ⏭️  Position {pos}: {name} has ACTIVE assignment - skipping")
                continue
            
            print(f"[Find Next User] ✅ Found available user: {name} at position {pos}")
            return (pos, uid, name)
        
        # Everyone busy/away. With allow_fallback the caller gets the first user
        # (legacy double-assign); without it we return None so the caller HOLDS the map.
        if rotation_list and allow_fallback:
            pos, uid, name, _ = rotation_list[0]
            print(f"[Find Next User] ⚠️  All rotation members have ACTIVE assignments! Returning first user as fallback: {name}")
            return (pos, uid, name)

        print("[Find Next User] ❌ No free maker available" + ("" if rotation_list else " (no rotation list)"))
        return None
    
    async def find_next_available_user_with_skip(
        self,
        guild: discord.Guild,
        skip_user_ids: Optional[List[int]] = None
    ) -> Optional[Tuple[int, int, str]]:
        """Find next available user in rotation, skipping away users and those in skip_user_ids."""
        if skip_user_ids is None:
            skip_user_ids = []

        try:
            positions = await get_all_loot_route_positions()
        except Exception as e:
            print(f"[Find Next User] ❌ Error reading positions from DB: {e}")
            return None

        if not positions:
            print("[Find Next User] ❌ No positions in database")
            return None

        positions.sort(key=lambda x: x[0])

        rotation_list = []
        away_role = guild.get_role(AWAY_ROLE_ID)
        for position, user_id in positions:
            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except Exception:
                    member = None
            is_away = bool(member and away_role and away_role in member.roles)
            name = member.name if member else f"User {user_id}"
            rotation_list.append((position, user_id, name, is_away))

        last_user_id = rotation_state.get('last_assigned_user_id')
        last_rank = 0
        if last_user_id:
            for pos, uid, _name, _is_away in rotation_list:
                if uid == last_user_id:
                    last_rank = pos
                    break
        if last_rank == 0:
            last_rank = rotation_state.get('last_assigned_position', 0) or 0
            if last_rank > len(rotation_list):
                last_rank = 0

        start_pos = last_rank + 1 if last_rank else 1
        if start_pos > len(rotation_list):
            start_pos = 1

        print(f"[Find Next User] 🔍 Starting search from position {start_pos}")
        if skip_user_ids:
            print(f"[Find Next User] ⏭️  Skipping {len(skip_user_ids)} users with active assignments")

        for offset in range(len(rotation_list)):
            index = (start_pos - 1 + offset) % len(rotation_list)
            pos, uid, name, is_away = rotation_list[index]
            if is_away:
                print(f"[Find Next User] ⏭️  Position {pos}: {name} is AWAY - skipping")
                continue
            if uid in skip_user_ids:
                print(f"[Find Next User] ⏭️  Position {pos}: {name} has active route - skipping")
                continue
            print(f"[Find Next User] ✅ Found available user: {name} at position {pos}")
            return (pos, uid, name)

        print("[Find Next User] ⚠️  All rotation members have active assignments!")
        return None
    
    async def handle_map_request(self, message: discord.Message):
        """Assign a new map to the next free maker, or HOLD it if everyone is busy."""
        print(f"\n{'='*60}\n[Loot Routes] 🗺️ MAP REQUEST FROM {message.author.name}\n{'='*60}")
        guild = message.guild
        text_content = message.content if message.content else ""
        image_urls = [a.url for a in message.attachments]
        if not image_urls and message.content:
            for tok in message.content.split():
                low = tok.lower()
                if ('cdn.discordapp.com' in low or 'media.discordapp.net' in low
                        or any(low.endswith(e) for e in ('.png', '.jpg', '.jpeg', '.gif', '.webp'))):
                    image_urls.append(tok)

        # Loot-bridge cross-bot: extract the Logistics queue code hidden in the filename
        # (loot-q<code>-p<priority>-<orig>.png) or in the subtext fallback line.
        # Strip the subtext marker so makers see clean text.
        logistics_queue_code = None
        for att in message.attachments:
            fm = re.match(r'loot-q([A-Za-z0-9]+)-p(\d+)-', att.filename or "")
            if fm:
                logistics_queue_code = fm.group(1)
                break
        if logistics_queue_code is None:
            bm = re.search(r'\[loot-bridge\] queue:(\S+)', text_content)
            if bm:
                logistics_queue_code = bm.group(1)
        if logistics_queue_code:
            # Remove the subtext marker line before passing text to the maker.
            text_content = re.sub(r'\s*-#\s*\[loot-bridge\].*', '', text_content).strip()
            print(f"[Loot Routes] 🔗 Loot-bridge request — Logistics queue code: {logistics_queue_code}")

        # _assign_lock serializes find_next_available_user + _assign_loot_map so that a
        # concurrent drain can't also claim the same free maker before the DB record lands.
        async with self._assign_lock:
            next_user = await self.find_next_available_user(guild, allow_fallback=False)
            if not next_user:
                # No free maker → HOLD the map (survives restarts); auto-assigns when one frees up.
                await self._hold_loot_map(message, text_content, image_urls)
                return

            position, user_id, username = next_user
            is_lucky_map = random.random() < LUCKY_MAP_CHANCE
            if not user_has_loot_route_role(guild, user_id):
                print(f"[Loot Routes] ⛔ {username} ({user_id}) in rotation but lacks the Loot Route Maker role")
                asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="role_mismatch_detected"))
                try:
                    await message.add_reaction("⚠️")
                except Exception:
                    pass
                return

            await self._assign_loot_map(guild, position, user_id, username, is_lucky_map,
                                        text_content, attachments=message.attachments, source_message=message)

    async def _hold_loot_map(self, message: discord.Message, text_content: str = None, image_urls=None):
        """Download the map image and queue it (FIFO) until a maker frees up."""
        import os, json as _json
        guild = message.guild
        is_lucky_map = random.random() < LUCKY_MAP_CHANCE
        if text_content is None:
            text_content = message.content or ""
        if image_urls is None:
            image_urls = [a.url for a in message.attachments]
        local = await self._download_loot_images(image_urls, os.path.join('route_files', 'pending'), prefix=str(message.id))
        await enqueue_loot_pending_map(
            guild_id=guild.id, source_message_id=message.id,
            map_details=text_content[:500] if text_content else None,
            image_refs=_json.dumps(image_urls), local_files=_json.dumps(local),
            is_lucky_map=is_lucky_map,
        )
        try:
            await message.add_reaction("⏳")
        except Exception:
            pass
        print("[Loot Routes] ⏳ Held map (no maker free) — will auto-assign when someone is available.")
        try:
            await _wave_log_event(category="loot_routes", action="map_held", guild=guild,
                                  details={"reason": "no_maker_available"})
        except Exception:
            pass

    async def _download_loot_images(self, urls, dest_dir: str, prefix: str = "img") -> list:
        """Download image URLs to dest_dir. Returns saved local paths."""
        import os, aiohttp
        saved = []
        if not urls:
            return saved
        os.makedirs(dest_dir, exist_ok=True)
        try:
            async with aiohttp.ClientSession() as session:
                for i, url in enumerate(urls):
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                ext = '.png'
                                for e in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
                                    if e in url.lower():
                                        ext = e
                                        break
                                dest = os.path.join(dest_dir, f"{prefix}_{i}{ext}")
                                with open(dest, 'wb') as f:
                                    f.write(await resp.read())
                                saved.append(dest)
                    except Exception as e:
                        print(f"[Loot Routes] ⚠️ Could not download {url}: {e}")
        except Exception as e:
            print(f"[Loot Routes] ⚠️ Image download session failed: {e}")
        return saved

    async def _assign_loot_map(self, guild, position, user_id, username, is_lucky_map,
                               text_content, attachments=None, local_file_paths=None, source_message=None):
        """Create the assignment + post card/confirm + DM + log. Works from live
        attachments OR saved local file paths (for held maps being drained)."""
        import os, json as _json
        try:
            rotation_state['last_assigned_position'] = position
            rotation_state['last_assigned_user_id'] = user_id
            new_total = await increment_total_assignments()
            rotation_state['total_assignments'] = new_total
            await save_rotation_state(last_assigned_position=position, last_assigned_user_id=user_id,
                                      total_assignments=new_total)

            notification_channel = guild.get_channel(NOTIFICATION_CHANNEL_ID)
            if not notification_channel:
                print("[Loot Routes] ❌ Notification channel not found")
                return None

            assignment_id = await create_route_assignment(
                user_id=user_id, guild_id=guild.id,
                notification_message_id=0, confirmation_message_id=0,
                map_details=text_content[:500] if text_content else None,
                is_lucky_map=is_lucky_map,
            )

            if is_lucky_map:
                notification_text = (f"🍀 **LUCKY MAP #{assignment_id}** 🍀\n<@{user_id}>\n"
                                     f"🎉 **2x Point Bonus is active on this route!**")
            else:
                notification_text = f"**Loot Route #{assignment_id}**\n<@{user_id}>"
            if text_content:
                notification_text += f"\n{text_content}"

            files = []
            if attachments:
                files = [await a.to_file() for a in attachments]
            elif local_file_paths:
                files = [discord.File(p) for p in local_file_paths if p and os.path.exists(p)]

            if files:
                notification_msg = await notification_channel.send(content=notification_text, files=files)
            else:
                notification_msg = await notification_channel.send(content=notification_text)

            confirmation_embed = discord.Embed(
                description=(f"<@{user_id}>, please react to this message to confirm you have seen the "
                             f"assignment and will complete the route.\n\n**Assignment ID:** #{assignment_id}\n\n"
                             f"If you are unable to complete this route, please DM <@&{HEAD_LOOT_ROUTES_ROLE_ID}> immediately."),
                color=0x57F287,
            )
            confirmation_msg = await notification_channel.send(embed=confirmation_embed)
            await update_assignment_message_ids(assignment_id, notification_msg.id, confirmation_msg.id)

            # Persist the route image to route_files/<id> so >cancelroute can reassign later.
            try:
                from database import save_route_local_files
                save_dir = os.path.join('route_files', str(assignment_id))
                os.makedirs(save_dir, exist_ok=True)
                saved_paths = []
                if attachments:
                    saved_paths = await self._download_loot_images([a.url for a in attachments], save_dir, prefix="att")
                elif local_file_paths:
                    import shutil
                    for p in local_file_paths:
                        if p and os.path.exists(p):
                            dest = os.path.join(save_dir, os.path.basename(p))
                            try:
                                shutil.copy2(p, dest)
                                saved_paths.append(dest)
                            except Exception:
                                pass
                if saved_paths:
                    await save_route_local_files(assignment_id, saved_paths)
            except Exception as _e:
                print(f"[Loot Routes] ⚠️ Local file save failed (non-fatal): {_e}")

            if source_message:
                try:
                    await source_message.add_reaction("✅")
                except Exception:
                    pass
                try:
                    await source_message.remove_reaction("⏳", source_message.guild.me)
                except Exception:
                    pass

            # DM the maker (fall back to fetch_user if not cached in the guild).
            try:
                recipient = guild.get_member(user_id) or self.bot.get_user(user_id)
                if recipient is None:
                    try:
                        recipient = await self.bot.fetch_user(user_id)
                    except Exception:
                        recipient = None
                if recipient:
                    if is_lucky_map:
                        dm_message = (f"🍀 **LUCKY MAP ASSIGNMENT!**\n**Assignment ID:** #{assignment_id}\n\n"
                                      f"🎉 You've landed a **Lucky Map**! Complete it fast to earn **2× the normal points!**\n\n"
                                      f"Check the details here:\n{notification_msg.jump_url}\n\n"
                                      f"**IMPORTANT:** Please react to the confirmation message to acknowledge you've seen this assignment.")
                    else:
                        dm_message = (f"🗺️ **New Loot Route Assignment**\n**Assignment ID:** #{assignment_id}\n\n"
                                      f"You've been assigned a new loot route! Please check the details here:\n{notification_msg.jump_url}\n\n"
                                      f"**IMPORTANT:** Please react to the confirmation message to acknowledge you've seen this assignment.\n\n"
                                      f"Thank you for your contribution to the team!")
                    await recipient.send(dm_message)
            except discord.Forbidden:
                print(f"[Loot Routes] ⚠️ Could not DM {username} - DMs are disabled")
            except Exception as e:
                print(f"[Loot Routes] ⚠️ Error sending DM to {username}: {e}")

            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                if is_lucky_map:
                    log_content = f"🍀 **LUCKY MAP Auto #{assignment_id}** — <@{user_id}> — **2x Bonus Active!** {notification_msg.jump_url}"
                else:
                    log_content = f"🤖 **Auto #{assignment_id}** - <@{user_id}> {notification_msg.jump_url}"
                await log_channel.send(content=log_content)

            await _wave_log_event(category="loot_routes", action="route_assigned",
                                  target={"id": str(user_id)}, guild=guild,
                                  details={"assignment_id": assignment_id, "is_lucky_map": bool(is_lucky_map), "source": "auto"})

            await self.update_sticky_message(guild)
            print(f"[Loot Routes] ✅ Assigned #{assignment_id} to {username} (Position #{position})")
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="route_assigned"))
            return assignment_id
        except Exception as e:
            print(f"[Loot Routes] ❌ Assign error: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def drain_loot_pending_pool(self, reason: str = "drain"):
        """Assign held maps (oldest first) while free makers exist. Lock-guarded."""
        import os, json as _json
        async with self._drain_lock:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return
            assigned_any = False
            while True:
                if await count_loot_pending_maps() == 0:
                    break
                local_files = []
                pending = None
                aid = None
                # _assign_lock: hold across find+assign so handle_map_request can't race us
                # and claim the same free maker before the DB record is committed.
                async with self._assign_lock:
                    nxt = await self.find_next_available_user(guild, allow_fallback=False)
                    if not nxt:
                        break  # no free maker — leave the rest held
                    pending = await get_oldest_loot_pending_map()
                    if not pending:
                        break
                    pos, uid, name = nxt
                    if not user_has_loot_route_role(guild, uid):
                        print(f"[Loot Routes] ⛔ drain: {uid} lacks Loot Route Maker role — stopping")
                        break
                    try:
                        local_files = _json.loads(pending.get('local_files') or '[]')
                    except Exception:
                        local_files = []
                    # Fetch the original #maps-not-taken message so we can swap ⏳ → ✅
                    source_msg = None
                    src_msg_id = pending.get('source_message_id')
                    if src_msg_id:
                        try:
                            maps_ch = guild.get_channel(MAP_REQUEST_CHANNEL_ID)
                            if maps_ch:
                                source_msg = await maps_ch.fetch_message(int(src_msg_id))
                        except Exception:
                            pass
                    aid = await self._assign_loot_map(guild, pos, uid, name, bool(pending.get('is_lucky_map')),
                                                      pending.get('map_details') or "", local_file_paths=local_files,
                                                      source_message=source_msg)
                if not aid:
                    break  # don't drop the held map if assignment failed
                await delete_loot_pending_map(pending['id'])
                for p in local_files:
                    try:
                        if p and os.path.exists(p):
                            os.remove(p)
                    except Exception:
                        pass
                assigned_any = True
            if assigned_any:
                print(f"[Loot Routes] ✅ Hold-pool drain ({reason}) assigned held map(s).")

# ============================================================================
# LOOT ROUTE LEADERBOARD SYNC (auto-update on points/routes)
# ============================================================================

_debounce_loot_route_task = None
_debounce_loot_route_bot = None


async def auto_update_loot_route_leaderboard(bot, triggered_by="route_completed"):
    """
    AUTOMATIC TRIGGER on loot route data change.
    Uses 5-second debounce to collapse rapid changes into single GitHub sync.

    Called from:
      - database.add_loot_route_points()
      - database.confirm_route_assignment()
      - commands (lootroutesredeem, etc.)
    """
    global _debounce_loot_route_task, _debounce_loot_route_bot

    if _debounce_loot_route_task:
        try:
            _debounce_loot_route_task.cancel()
        except:
            pass

    _debounce_loot_route_bot = bot
    _debounce_loot_route_task = asyncio.create_task(
        _wait_then_update_loot_route_leaderboard()
    )


async def _wait_then_update_loot_route_leaderboard():
    """Wait 1.5 seconds, then do actual update (debounce rapid changes)"""
    try:
        await asyncio.sleep(1.5)
        await _do_update_loot_route_leaderboard()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"❌ Error in loot route leaderboard update: {e}")


async def _do_update_loot_route_leaderboard():
    """Fetch loot route stats and push to GitHub"""
    global _debounce_loot_route_task
    from database import get_loot_route_points_leaderboard, get_all_loot_route_positions, get_loot_route_position

    try:
        # Use loot_route_positions as the source of truth so everyone in the
        # rotation appears — including members with 0 routes completed who have
        # no entry in loot_route_points yet.
        rotation_positions = await get_all_loot_route_positions()  # [(rank, user_id), ...]
        all_rotation_ids = [uid for _, uid in rotation_positions]

        if not all_rotation_ids:
            logger.info("ℹ️ No loot route makers in rotation yet")
            return

        # Fetch existing points records and build a lookup dict
        leaderboard_data = await get_loot_route_points_leaderboard(limit=500)
        points_lookup = {uid: (pts, routes) for uid, pts, routes in leaderboard_data}

        # Build leaderboard_data covering ALL rotation members (0-route members get 0/0)
        full_leaderboard = []
        for uid in all_rotation_ids:
            pts, routes = points_lookup.get(uid, (0.0, 0))
            full_leaderboard.append((uid, pts, routes))

        # Sort by routes completed descending (rotation order as tiebreaker)
        full_leaderboard.sort(key=lambda x: x[2], reverse=True)

        # Enrich with Discord user info
        bot = _debounce_loot_route_bot
        if not bot:
            logger.warning("⚠️ Bot not available for user enrichment")
            return

        guild = bot.get_guild(1041450125391835186)  # GUILD_ID
        if not guild:
            logger.warning("❌ Main guild not found")
            return

        LOOT_ROUTE_MAKER_ROLE_ID = 1231188006757728266
        maker_role = guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
        maker_member_ids = {m.id for m in maker_role.members} if maker_role else set()

        # Pre-compute who holds the all-time fastest completion (for badge)
        fastest_user_id = None
        try:
            async with (await get_pool()).acquire() as db:
                async with db.execute(
                    """SELECT user_id FROM route_assignments
                       WHERE status='completed' AND points_awarded > 0
                       ORDER BY (julianday(completed_at) - julianday(assigned_at)) ASC LIMIT 1"""
                ) as cur:
                    row = await cur.fetchone()
                    if row:
                        fastest_user_id = row[0]
        except Exception:
            pass

        # Pre-compute who has completed at least one lucky map
        lucky_completers = set()
        try:
            async with (await get_pool()).acquire() as db:
                async with db.execute(
                    "SELECT DISTINCT user_id FROM route_assignments WHERE is_lucky_map=1 AND status='completed'"
                ) as cur:
                    for row in await cur.fetchall():
                        lucky_completers.add(row[0])
        except Exception:
            pass

        players = []
        for user_id, total_points, routes_completed in full_leaderboard:
            # Skip users who no longer have the Loot Route Maker role
            if maker_role and user_id not in maker_member_ids:
                logger.info(f"⏭️ Skipping {user_id} — no longer a Loot Route Maker")
                continue

            member = guild.get_member(user_id)
            if not member:
                try:
                    member = await guild.fetch_member(user_id)
                except:
                    member = None

            avatar_url = web_avatar_url(member.display_avatar) if member else None
            display_name = member.display_name if member else f"User {user_id}"

            # Get rotation rank
            rotation_rank = await get_loot_route_position(user_id)

            # Calculate avg times, weekly points, active flag, streak
            avg_time_str = "—"
            avg_reaction_str = "—"
            streak = 0
            avg_completion_hours_raw = None
            try:
                async with (await get_pool()).acquire() as db:
                    async with db.execute(
                        """SELECT
                               AVG(CAST((julianday(completed_at) - julianday(assigned_at)) AS REAL) * 24),
                               AVG(CAST((julianday(confirmed_at) - julianday(assigned_at)) AS REAL) * 24),
                               NULL
                           FROM route_assignments
                           WHERE user_id = ? AND status = 'completed'""",
                        (user_id,),
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            if row[0]:
                                hours = row[0]
                                avg_completion_hours_raw = round(hours, 2)
                                if hours < 1:
                                    avg_time_str = f"{int(hours * 60)}m"
                                elif hours < 24:
                                    avg_time_str = f"{hours:.1f}h"
                                else:
                                    avg_time_str = f"{hours / 24:.1f}d"
                            if row[1]:
                                react_h = row[1]
                                if react_h < 1:
                                    avg_reaction_str = f"{int(react_h * 60)}m"
                                elif react_h < 24:
                                    avg_reaction_str = f"{react_h:.1f}h"
                                else:
                                    avg_reaction_str = f"{react_h / 24:.1f}d"
                            pass

                    # Streak: consecutive weeks with ≥1 completed route (going backwards)
                    async with db.execute(
                        """SELECT DISTINCT date(completed_at, '-' || ((cast(strftime('%w', completed_at) as integer) + 6) % 7) || ' days')
                           FROM route_assignments
                           WHERE user_id = ? AND status = 'completed'
                           ORDER BY 1 DESC""",
                        (user_id,),
                    ) as cursor:
                        streak_weeks = await cursor.fetchall()

                    if streak_weeks:
                        today_d = date.today()
                        cur_wk = today_d - timedelta(days=today_d.weekday())
                        expected_wk = None
                        for (w_str,) in streak_weeks:
                            try:
                                w = date.fromisoformat(w_str)
                            except Exception:
                                break
                            if expected_wk is None:
                                if w >= cur_wk - timedelta(weeks=1):
                                    expected_wk = w
                                else:
                                    break
                            if w == expected_wk:
                                streak += 1
                                expected_wk -= timedelta(weeks=1)
                            else:
                                break
            except Exception as e:
                logger.warning(f"⚠️ Error calculating stats for {user_id}: {e}")

            badges = []
            if routes_completed >= 1:
                badges.append("first_route")
            if routes_completed >= 10:
                badges.append("routes_10")
            if routes_completed >= 25:
                badges.append("routes_25")
            if user_id == fastest_user_id:
                badges.append("fastest")
            if user_id in lucky_completers:
                badges.append("lucky_map")

            players.append({
                "user_id": str(user_id),
                "display_name": display_name,
                "avatar_url": avatar_url,
                "routes_completed": routes_completed,
                "avg_completion_time": avg_time_str,
                "avg_completion_hours": avg_completion_hours_raw,
                "avg_reaction_time": avg_reaction_str,
                "rotation_rank": rotation_rank,
                "is_active": routes_completed > 0,
                "streak": streak,
                "badges": badges,
            })

        # Position delta: compare current ranks to previous snapshot
        _RANK_SNAPSHOT = os.path.join('json_data', 'loot_route_rank_snapshot.json')
        prev_positions = {}
        try:
            if os.path.exists(_RANK_SNAPSHOT):
                with open(_RANK_SNAPSHOT, 'r') as f:
                    prev_positions = json.load(f)
        except Exception:
            pass

        new_snapshot = {}
        for i, player in enumerate(players):
            uid_str = str(player['user_id'])
            rank = i + 1
            prev = prev_positions.get(uid_str)
            player['rank_delta'] = (prev - rank) if prev is not None else None
            new_snapshot[uid_str] = rank

        try:
            with open(_RANK_SNAPSHOT, 'w') as f:
                json.dump(new_snapshot, f)
        except Exception:
            pass

        # Build rotation queue data
        rotation = []
        next_up_rank = None
        try:
            rotation_positions = await get_all_loot_route_positions()

            _AWAY_ROLE_ID = 1495685790452420608
            away_role = guild.get_role(_AWAY_ROLE_ID)
            away_user_ids = {m.id for m in away_role.members} if away_role else set()

            async with (await get_pool()).acquire() as db:
                async with db.execute(
                    "SELECT user_id, status, is_lucky_map FROM route_assignments WHERE status IN ('pending', 'confirmed')"
                ) as cursor:
                    active_rows = await cursor.fetchall()
                active_assignments = {row[0]: {'status': row[1], 'is_lucky': bool(row[2])} for row in active_rows}

                async with db.execute(
                    "SELECT user_id, assigned_at FROM loot_route_positions"
                ) as cursor:
                    joined_rows = await cursor.fetchall()
                joined_dates = {row[0]: row[1] for row in joined_rows}

            players_by_uid = {p['user_id']: p for p in players}

            for rank, uid in rotation_positions:
                rot_member = guild.get_member(uid)
                if not rot_member:
                    try:
                        rot_member = await guild.fetch_member(uid)
                    except Exception:
                        rot_member = None

                display_name = rot_member.display_name if rot_member else f"User {uid}"
                avatar_url = web_avatar_url(rot_member.display_avatar) if rot_member else None
                is_away = uid in away_user_ids
                assignment_data = active_assignments.get(uid)
                assignment_status = assignment_data['status'] if assignment_data else None
                is_lucky = assignment_data.get('is_lucky', False) if assignment_data else False
                p_data = players_by_uid.get(uid, {})

                rotation.append({
                    "rank": rank,
                    "user_id": str(uid),
                    "display_name": display_name,
                    "avatar_url": avatar_url,
                    "is_away": is_away,
                    "assignment_status": assignment_status,
                    "is_lucky_map": is_lucky,
                    "routes_completed": p_data.get("routes_completed", 0),
                    "streak": p_data.get("streak", 0),
                    "joined_at": joined_dates.get(uid),
                })

                if next_up_rank is None and not is_away and assignment_status is None:
                    next_up_rank = rank
        except Exception as e:
            logger.warning(f"⚠️ Error fetching rotation data: {e}")

        # Build lucky maps data
        lucky_maps = []
        try:
            async with (await get_pool()).acquire() as db:
                async with db.execute(
                    """SELECT assignment_id, user_id, assigned_at, completed_at, points_awarded
                       FROM route_assignments
                       WHERE is_lucky_map = 1 AND status = 'completed'
                       ORDER BY completed_at DESC"""
                ) as cursor:
                    lucky_rows = await cursor.fetchall()

            for row in lucky_rows:
                assignment_id, lucky_user_id, assigned_at_str, completed_at_str, points_awarded = row
                member = guild.get_member(lucky_user_id)
                if not member:
                    try:
                        member = await guild.fetch_member(lucky_user_id)
                    except Exception:
                        member = None

                display_name = member.display_name if member else f"User {lucky_user_id}"
                avatar_url = web_avatar_url(member.display_avatar) if member else None

                hours_taken = None
                try:
                    if assigned_at_str and completed_at_str:
                        assigned_dt = datetime.fromisoformat(assigned_at_str.replace('Z', '+00:00'))
                        completed_dt = datetime.fromisoformat(completed_at_str.replace('Z', '+00:00'))
                        hours_taken = round((completed_dt - assigned_dt).total_seconds() / 3600, 1)
                except Exception:
                    pass

                lucky_maps.append({
                    "assignment_id": assignment_id,
                    "user_id": str(lucky_user_id),
                    "display_name": display_name,
                    "avatar_url": avatar_url,
                    "completed_at": completed_at_str,
                    "hours_taken": hours_taken,
                    "points_awarded": points_awarded,
                })
        except Exception as e:
            logger.warning(f"⚠️ Error fetching lucky map data: {e}")

        lucky_maps_stats = {
            "total_triggered": len(lucky_maps),
        }

        # Top 10 players by lucky map count (for bar chart)
        _lucky_counts = Counter()
        _lucky_names = {}
        for m in lucky_maps:
            uid = m["user_id"]
            _lucky_counts[uid] += 1
            _lucky_names[uid] = m["display_name"]
        top10_lucky_maps = [
            {"display_name": _lucky_names[uid], "count": cnt}
            for uid, cnt in _lucky_counts.most_common(10)
        ]

        # --- Global stats ---
        global_stats = {
            "total_routes": 0,
            "avg_completion_hours": None,
            "fastest_hours": None,
            "fastest_user": None,
            "total_makers": 0,
            "total_lucky_maps": len(lucky_maps),
        }
        try:
            async with (await get_pool()).acquire() as db:
                async with db.execute(
                    """SELECT COUNT(*),
                              AVG(CAST((julianday(completed_at) - julianday(assigned_at)) AS REAL) * 24),
                              MIN(CAST((julianday(completed_at) - julianday(assigned_at)) AS REAL) * 24),
                              COUNT(DISTINCT user_id)
                       FROM route_assignments
                       WHERE status = 'completed'"""
                ) as cursor:
                    gs_row = await cursor.fetchone()
                if gs_row and gs_row[0]:
                    global_stats["total_routes"] = gs_row[0] or 0
                    global_stats["avg_completion_hours"] = round(gs_row[1], 1) if gs_row[1] else None
                    global_stats["fastest_hours"] = round(gs_row[2], 1) if gs_row[2] else None
                    global_stats["total_makers"] = gs_row[3] or 0
                if global_stats["fastest_hours"] is not None:
                    async with db.execute(
                        """SELECT user_id FROM route_assignments
                           WHERE status = 'completed'
                           ORDER BY (julianday(completed_at) - julianday(assigned_at)) ASC LIMIT 1"""
                    ) as cursor:
                        f_row = await cursor.fetchone()
                    if f_row:
                        f_uid = f_row[0]
                        f_member = guild.get_member(f_uid)
                        if not f_member:
                            try:
                                f_member = await guild.fetch_member(f_uid)
                            except Exception:
                                f_member = None
                        global_stats["fastest_user"] = f_member.display_name if f_member else f"User {f_uid}"
        except Exception as e:
            logger.warning(f"⚠️ Error fetching global stats: {e}")

        # --- Weekly data (last 16 weeks) ---
        weekly_data = []
        try:
            async with (await get_pool()).acquire() as db:
                async with db.execute(
                    """SELECT
                           date(completed_at, '-' || ((cast(strftime('%w', completed_at) as integer) + 6) % 7) || ' days') as week_monday,
                           COUNT(*) as routes
                       FROM route_assignments
                       WHERE status = 'completed'
                         AND completed_at >= datetime('now', '-112 days')
                       GROUP BY week_monday
                       ORDER BY week_monday ASC"""
                ) as cursor:
                    wk_rows = await cursor.fetchall()
            for wk_row in wk_rows:
                week_str = wk_row[0]
                try:
                    wdt = datetime.strptime(week_str, "%Y-%m-%d")
                    # Cross-platform: %-d is Unix-only, blows up on Windows
                    label = wdt.strftime("%d %b").lstrip("0")
                except Exception:
                    label = week_str
                weekly_data.append({
                    "week": week_str,
                    "label": label,
                    "routes": wk_row[1] or 0,
                })
        except Exception as e:
            logger.warning(f"⚠️ Error fetching weekly data: {e}")

        # --- Per-user cumulative route history (top 5 by routes completed) ---
        route_history = []
        try:
            top5_ids = [p["user_id"] for p in players[:5]]
            today = date.today()
            today_monday = (today - timedelta(days=today.weekday())).isoformat()
            async with (await get_pool()).acquire() as db:
                for uid in top5_ids:
                    async with db.execute(
                        """SELECT
                               date(completed_at, '-' || ((cast(strftime('%w', completed_at) as integer) + 6) % 7) || ' days') as week_monday,
                               COUNT(*) as weekly_routes
                           FROM route_assignments
                           WHERE user_id = ? AND status = 'completed' AND points_awarded > 0
                             AND completed_at >= datetime('now', '-112 days')
                           GROUP BY week_monday
                           ORDER BY week_monday ASC""",
                        (uid,)
                    ) as cursor:
                        rh_rows = await cursor.fetchall()

                    history = []
                    cumulative = 0
                    for rh_row in rh_rows:
                        cumulative += rh_row[1] or 0
                        history.append({"week": rh_row[0], "cumulative": cumulative})

                    player_data = next((p for p in players if p["user_id"] == uid), None)
                    real_total = player_data["routes_completed"] if player_data else cumulative
                    if not history or history[-1]["week"] < today_monday:
                        history.append({"week": today_monday, "cumulative": real_total})

                    if not history:
                        continue

                    display_nm = player_data["display_name"] if player_data else f"User {uid}"
                    route_history.append({"user_id": str(uid), "display_name": display_nm, "history": history})
        except Exception as e:
            logger.warning(f"⚠️ Error fetching route history: {e}")

        # Build payload
        payload = {
            "players": players,
            "lucky_maps": lucky_maps,
            "lucky_maps_stats": lucky_maps_stats,
            "top10_lucky_maps": top10_lucky_maps,
            "global_stats": global_stats,
            "weekly_data": weekly_data,
            "route_history": route_history,
            "rotation": rotation,
            "next_up_rank": next_up_rank,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"📊 [Loot Routes] Prepared {len(players)} players for leaderboard")

        # Push to GitHub
        try:
            from tasks.staff_hub_writer import push_loot_route_leaderboard_to_github
            success = await push_loot_route_leaderboard_to_github(payload)
            if success:
                logger.info("✅ [Loot Routes] Leaderboard pushed to GitHub")
            else:
                logger.warning("⚠️ [Loot Routes] Leaderboard push returned False")
        except Exception as e:
            logger.error(f"❌ [Loot Routes] Failed to push leaderboard: {e}")

    except Exception as e:
        logger.error(f"❌ Error updating loot route leaderboard: {e}")
        import traceback
        traceback.print_exc()


async def setup(bot: commands.Bot):
    """Setup function for extension loading"""
    loot_routes = LootRoutes(bot)
    
    # ✅ add_cog triggers cog_load() which spawns initialize() as a background task
    await bot.add_cog(loot_routes)
    
    print("[Loot Routes] ✅ Extension loaded successfully with database integration")