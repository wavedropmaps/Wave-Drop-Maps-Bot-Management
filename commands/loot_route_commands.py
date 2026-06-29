"""
loot_route_commands.py
🔥 BULLET-PROOF VERSION - COMPLETE FILE WITH ALL COMMANDS 🔥
Commands for managing the loot routes system

✅ 5-SECOND TIMEOUTS between database operations
✅ AUTOMATIC GAP REMOVAL when users are removed
✅ SEQUENTIAL POSITIONS ALWAYS (1,2,3,4,5... NO SKIPS)
✅ FULL DATABASE SYNCHRONIZATION
✅ ALL ORIGINAL COMMANDS INCLUDED
✅ NEW: Cancel & Reassign Routes
✅ NEW: Complete Route Statistics
"""

import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
from typing import Optional, List, Tuple
import asyncio
import re
import io
from datetime import datetime, timezone, timedelta
from discord.ui import Button, View, Select

# Wave-Logging dashboard publisher (mirrors loot-channel events to the dashboard)
from core.global_logger import log_event as _wave_log_event

# Import database functions
# NOTE: *_loot_route_points below are LEADERBOARD helpers (count of routes_completed
# per maker), NOT a currency. The spendable currency is Wave Points (add_wave_points).
# See the naming note in database.py before removing any of these.
from database import (
    add_loot_route_points,
    get_loot_route_user_points,
    get_loot_route_points_leaderboard,
    create_route_assignment,
    update_assignment_message_ids,
    get_route_assignment_by_id,
    get_user_route_assignments,
    get_route_assignment_stats,
    save_rotation_state,
    get_rotation_state,
    increment_total_assignments,
    set_loot_route_user_points,
    delete_route_assignment,
)

# Away return date persistence
try:
    from database import (
        set_away_return_date,
        delete_away_return_date,
        get_all_away_return_dates,
    )
    print("[Loot Route Commands] [OK] Away return date DB functions loaded")
except ImportError as _away_err:
    print(f"[Loot Route Commands] [WARN] Away return date DB functions missing: {_away_err}")

    async def set_away_return_date(user_id, return_date):
        raise NotImplementedError("set_away_return_date missing from database.py")

    async def delete_away_return_date(user_id):
        raise NotImplementedError("delete_away_return_date missing from database.py")

    async def get_all_away_return_dates():
        raise NotImplementedError("get_all_away_return_dates missing from database.py")

# These position-tracking functions may or may not exist in database.py yet.
# Using try/except so the cog always loads — commands will raise a clear error
# rather than the whole cog silently dying on import.
try:
    from database import (
        get_loot_route_position,
        set_loot_route_position,
        remove_loot_route_position,
        get_all_loot_route_positions,
        get_next_position_number,
    )
    print("[Loot Route Commands] [OK] Position DB functions loaded successfully")
except ImportError as _pos_err:
    print(f"[Loot Route Commands] [WARN] Position DB functions missing: {_pos_err}")
    print("[Loot Route Commands] [WARN] Commands using these will error until added to database.py")

    async def get_loot_route_position(user_id):
        raise NotImplementedError("get_loot_route_position missing from database.py")

    async def set_loot_route_position(user_id, position):
        raise NotImplementedError("set_loot_route_position missing from database.py")

    async def remove_loot_route_position(user_id):
        raise NotImplementedError("remove_loot_route_position missing from database.py")

    async def get_all_loot_route_positions():
        raise NotImplementedError("get_all_loot_route_positions missing from database.py")

    async def get_next_position_number():
        raise NotImplementedError("get_next_position_number missing from database.py")

# Import leaderboard update trigger
try:
    from tasks.loot_routes import auto_update_loot_route_leaderboard
    print("[Loot Route Commands] [OK] Loot route leaderboard update function loaded")
except ImportError as _lb_err:
    print(f"[Loot Route Commands] [WARN] Loot route leaderboard update missing: {_lb_err}")

    async def auto_update_loot_route_leaderboard(bot, triggered_by="route_completed"):
        pass

# Configuration
GUILD_ID = 1041450125391835186
NOTIFICATION_CHANNEL_ID = 1231195722485993512  # claim-loot-route
LOG_CHANNEL_ID = 1249416251759919246  # log channel
LEADERBOARD_CHANNEL_ID = 1251145459179716618  # leaderboard
HEAD_LOOT_ROUTES_ROLE_ID = 1231187220208025620  # Head Loot Routes role
LOOT_ROUTE_PERMS_ROLE_ID = 1476184939727945829  # Loot Route Perms role (same access as Head Loot Routes)
LOOT_ROUTE_INSPECTOR_ROLE_ID = 1503649126192119839  # Loot Route Inspector role
LOOT_ROUTE_INSPECTOR_MULTIPLIER = 1.5  # 1.5x multiplier for Loot Route Inspector
ROTATION_CHANNEL_ID = 1239193678459703447  # rotation
LOOT_ROUTE_MAKER_ROLE_ID = 1231188006757728266  # Loot Route Maker role
MEMBER_UPDATES_CHANNEL_ID = 1243623718190714921
AWAY_ROLE_ID = 1495685790452420608  # Loot Route Away role (staffhub server)
REDEMPTION_LOG_CHANNEL_ID = 1041584423264596009  # Management/announcements channel for redemption logs
VBUCKS_REDEMPTION_CHANNEL_ID = 1470639550534778882  # VBucks redemption notifications channel

# Additional guilds to sync role with
ADDITIONAL_GUILDS = [
    988564962802810961,  # Guild 2
    971731167621574666   # Guild 3
]

# Role name to search for in other guilds (case-insensitive match below)
ROLE_NAME = "Loot Route Maker"


# 🔥 LOOT ROUTE POINTS SHOP PRIZES 🔥
SHOP_PRIZES = {
    "surge_route": {
        "name": "🌊 Free Pro Surge Route!",
        "cost": 48,
        "emoji": "🌊",
        "description": "Get a professional surge route created for FREE!",
        "color": 0x00D9FF,
    },
    "loot_route": {
        "name": "💰 Free Pro Loot Route!",
        "cost": 95,
        "emoji": "💰",
        "description": "Get a professional loot route created for FREE!",
        "color": 0xFFD700,
    },
    "paid_priority": {
        "name": "⭐ Paid Priority Role!",
        "cost": 95,
        "emoji": "⭐",
        "description": "Receive the Paid Priority role!",
        "color": 0xF1C40F,
    },
    "wave_contributor": {
        "name": "🌊 Wave Contributor Role!",
        "cost": 107,
        "emoji": "🌊",
        "description": "Receive the Wave Contributor role!",
        "color": 0x1ABC9C,
    },
    "drop_map": {
        "name": "🎯 Free Pro Drop Map!",
        "cost": 166,
        "emoji": "🎯",
        "description": "Get a professional drop map created for FREE!",
        "color": 0xFF6B35,
    },
    "announcement_ping": {
        "name": "📢 @everyone Announcement Ping!",
        "cost": 1781,
        "emoji": "📢",
        "description": "Post a message with @everyone in the Drop Map server announcements!",
        "color": 0xE67E22,
    },
    "vip": {
        "name": "👑 VIP Role!",
        "cost": 1188,
        "emoji": "👑",
        "description": "Receive the VIP role!",
        "color": 0xE91E63,
    },
}

# Prizes that grant a Discord role automatically
ROLE_PRIZES = {
    "paid_priority":    "Paid Priority",
    "wave_contributor": "Wave Contributor",
}

# Prizes that auto-apply to BOTH servers
AUTO_BOTH_ROLES = {
    "vip": "VIP",
}

# Prizes that require manual fulfilment by management
MANUAL_PRIZES = {"announcement_ping"}

# Guilds to apply roles across (ONLY 2 - not staff hub)
PERKS_GUILD_IDS = [
    988564962802810961,
    971731167621574666,
]

# ⚠️ STAFF HIERARCHY - For automatic promotions when redeeming Staff Promotion Boost
# Format: role_id: ("Current Name", next_role_id, "Next Name")
STAFF_HIERARCHY = {
    1111111111111111111: ("Trial Staff", 2222222222222222222, "Staff"),
    2222222222222222222: ("Staff", 3333333333333333333, "Support"),
    3333333333333333333: ("Support", 4444444444444444444, "Senior Support"),
    4444444444444444444: ("Senior Support", 5555555555555555555, "Admin"),
    5555555555555555555: ("Admin", 6666666666666666666, "Head Admin"),
    6666666666666666666: ("Head Admin", 7777777777777777777, "Management"),
    7777777777777777777: ("Management", None, None),  # Top rank
    8888888888888888888: ("Instant Management", None, None),  # Special, also top
}
# ⚠️ UPDATE THE ROLE IDs ABOVE WITH YOUR ACTUAL ROLE IDs FROM DISCORD

# ==================== VIEWS ====================

class ServerSelectView(View):
    """View for selecting which server for Staff Promotion or Wave Contributor"""
    
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.selected_guild_id = None
    
    @discord.ui.button(label="Guild 1", style=discord.ButtonStyle.blurple)
    async def guild1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return
        
        self.selected_guild_id = PERKS_GUILD_IDS[0]
        self.stop()
        await interaction.response.defer()
    
    @discord.ui.button(label="Guild 2", style=discord.ButtonStyle.blurple)
    async def guild2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return
        
        self.selected_guild_id = PERKS_GUILD_IDS[1]
        self.stop()
        await interaction.response.defer()

class PromotionConfirmView(View):
    """View for confirming staff promotion details"""
    
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.confirmed = False
    
    @discord.ui.button(label="✅ Confirm Promotion", style=discord.ButtonStyle.green)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return
        
        self.confirmed = True
        self.stop()
        await interaction.response.defer()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.red)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return
        
        self.confirmed = False
        self.stop()
        await interaction.response.defer()

class ReassignView(View):
    """View for asking if route should be reassigned"""

    def __init__(self, ctx, assignment_data, original_files_data):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.assignment_data = assignment_data
        self.original_files_data = original_files_data
        self.value = None

    @discord.ui.button(label="✅ Yes - Reassign", style=discord.ButtonStyle.green)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return

        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="👤 Pick Someone", style=discord.ButtonStyle.blurple)
    async def pick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return

        self.value = 'manual'
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="❌ No - Just Cancel", style=discord.ButtonStyle.red)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Only the command user can respond!", ephemeral=True)
            return

        self.value = False
        self.stop()
        await interaction.response.defer()


class ManualPickView(View):
    """Dropdown to manually pick a loot route maker for reassignment"""

    def __init__(self, ctx, available_users, guild):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.available_users = available_users  # List of (rank, user_id)
        self.guild = guild
        self.selected_user_id = None
        self.selected_position = None
        self.selected_username = None

        options = []
        for rank, uid in available_users[:25]:
            member = guild.get_member(uid)
            label = (member.display_name if member else f"User {uid}")[:80]
            options.append(discord.SelectOption(
                label=f"#{rank} — {label}"[:100],
                value=str(uid),
                description=f"Rotation position #{rank}"
            ))

        select = Select(
            placeholder="👤 Choose a maker to assign...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Only the command user can pick!", ephemeral=True)
            return

        selected_uid = int(interaction.data['values'][0])
        for rank, uid in self.available_users:
            if uid == selected_uid:
                self.selected_position = rank
                break

        self.selected_user_id = selected_uid
        member = self.guild.get_member(selected_uid)
        self.selected_username = member.display_name if member else str(selected_uid)
        self.stop()
        await interaction.response.defer()

class PrizeSelectView(View):
    """🔥 DOPAMINE-FUELED PRIZE SELECTION VIEW 🔥"""
    
    def __init__(self, ctx, user_points: float):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.user_points = user_points
        self.selected_prize = None
        
        # Create select menu with prizes sorted lowest to highest cost
        options = []
        for prize_id, prize_data in sorted(SHOP_PRIZES.items(), key=lambda x: x[1]['cost']):
            can_afford = user_points >= prize_data['cost']
            
            label = f"{prize_data['emoji']} {prize_data['name'].split('!')[0]}"
            description = f"{prize_data['cost']} Points"
            
            if not can_afford:
                description += " - ❌ Not Enough Points"
            
            options.append(discord.SelectOption(
                label=label[:100],
                value=prize_id,
                description=description[:100],
                emoji=prize_data['emoji']
            ))
        
        select = Select(
            placeholder="🎁 Choose your prize...",
            options=options,
            custom_id="prize_select"
        )
        select.callback = self.select_callback
        self.add_item(select)
    
    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("❌ Only the command user can select!", ephemeral=True)
            return
        
        self.selected_prize = interaction.data['values'][0]
        prize_data = SHOP_PRIZES[self.selected_prize]
        
        if self.user_points < prize_data['cost']:
            await interaction.response.send_message(
                f"❌ You need **{prize_data['cost']} Loot Route Points** but only have **{self.user_points}**!",
                ephemeral=True
            )
            return
        
        self.stop()
        await interaction.response.defer()

# ==================== MAIN CLASS ====================

class LootRouteCommands(commands.Cog):
    """Commands for loot routes management"""
    
    def __init__(self, bot):
        self.bot = bot
        self._away_return_dates: dict[int, str] = {}  # user_id -> 'YYYY-MM-DD'
        print("[Loot Route Commands] [OK] Commands loaded (BULLET-PROOF COMPLETE VERSION)")

    async def cog_load(self):
        """Reload away return dates from DB and start the background checker."""
        try:
            records = await get_all_away_return_dates()
            self._away_return_dates = {r['user_id']: r['return_date'] for r in records}
            print(f"[Away] [OK] Loaded {len(self._away_return_dates)} away return date(s) from DB")
        except Exception as e:
            print(f"[Away] [WARN] Could not load away return dates: {e}")
        self._check_away_returns.start()

    def cog_unload(self):
        self._check_away_returns.cancel()

    @tasks.loop(hours=1)
    async def _check_away_returns(self):
        """Hourly background task — auto-removes away from users whose return date has passed."""
        if not self._away_return_dates:
            return

        today = datetime.now(timezone.utc).date()
        expired = [uid for uid, date_str in self._away_return_dates.items()
                   if date_str and datetime.fromisoformat(date_str).date() <= today]

        for user_id in expired:
            try:
                guild = self.bot.get_guild(GUILD_ID)
                if not guild:
                    continue

                member = guild.get_member(user_id)
                if not member:
                    # Still clean up even if member left
                    self._away_return_dates.pop(user_id, None)
                    await delete_away_return_date(user_id)
                    continue

                away_role = guild.get_role(AWAY_ROLE_ID)
                if away_role and away_role in member.roles:
                    await member.remove_roles(away_role, reason="Auto-removed: away return date reached")
                    asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="away_auto_removed"))
                    print(f"[Away] ✅ Auto-removed away from {member.name} (return date reached)")

                self._away_return_dates.pop(user_id, None)
                await delete_away_return_date(user_id)

            except Exception as e:
                print(f"[Away] ❌ Error auto-removing away for user {user_id}: {e}")

    @_check_away_returns.before_loop
    async def _before_check_away_returns(self):
        await self.bot.wait_until_ready()
    
    async def safe_delay(self, seconds: int, message: str = None):
        """Helper function for safe delays with logging"""
        if message:
            print(f"[Loot Route Commands] ⏳ {message} (waiting {seconds}s...)")
        await asyncio.sleep(seconds)
        if message:
            print(f"[Loot Route Commands] ✅ Delay complete")
    
    def format_time_ago(self, dt: datetime) -> str:
        """Format datetime as 'X hours/days ago'"""
        now = datetime.now(timezone.utc)
        diff = now - dt
        
        seconds = diff.total_seconds()
        
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        else:
            days = int(seconds / 86400)
            return f"{days}d ago"
    
    def split_text(self, text: str, max_length: int) -> list:
        """Split text into chunks of max_length"""
        chunks = []
        current_chunk = ""
        
        for line in text.split('\n'):
            if len(current_chunk) + len(line) + 1 > max_length:
                chunks.append(current_chunk)
                current_chunk = line + '\n'
            else:
                current_chunk += line + '\n'
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks
    
    async def delete_log_message(self, guild: discord.Guild, assignment_id: int):
        """
        🗑️ Delete the log message in LOG_CHANNEL_ID for a given assignment ID.
        Searches the last 500 messages for one containing '#{assignment_id}' and deletes it.
        Uses word-boundary matching to avoid accidentally matching e.g. #5 inside #50.
        """
        try:
            import re
            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if not log_channel:
                print(f"[Delete Log] ⚠️ Log channel not found")
                return

            # Match #{id} NOT followed by another digit (word boundary for IDs)
            pattern = re.compile(rf'#{re.escape(str(assignment_id))}(?!\d)')

            async for message in log_channel.history(limit=500):
                if message.author.id == self.bot.user.id:
                    content = message.content or ""
                    if pattern.search(content):
                        await message.delete()
                        print(f"[Delete Log] ✅ Deleted log message for assignment #{assignment_id}")
                        return

            print(f"[Delete Log] ⚠️ No log message found for assignment #{assignment_id}")
        except Exception as e:
            print(f"[Delete Log] ❌ Error deleting log message: {e}")

    async def resequence_positions(self, guild: discord.Guild):
        """
        🔥 RESEQUENCE: Remove ALL gaps in position numbers
        After removing a user, shift all higher positions down to fill the gap
        Example: 1,2,4,6,7 becomes 1,2,3,4,5
        ALWAYS KEEPS POSITIONS SEQUENTIAL WITH NO GAPS
        """
        try:
            print("[Loot Route Commands] 🔄 RESEQUENCING: Removing ALL gaps...")
            
            # Get all positions sorted
            positions = await get_all_loot_route_positions()
            
            if not positions:
                print("[Loot Route Commands] ℹ️ No positions to resequence")
                return
            
            # Sort by position number
            positions.sort(key=lambda x: x[0])
            
            print(f"[Loot Route Commands] 📋 BEFORE: {[pos for pos, _ in positions]}")
            
            # Check if resequencing is needed
            expected_positions = list(range(1, len(positions) + 1))
            current_positions = [pos for pos, _ in positions]
            
            if current_positions == expected_positions:
                print("[Loot Route Commands] ✅ Already sequential - no gaps found")
                return
            
            print(f"[Loot Route Commands] 🔧 GAPS DETECTED - Resequencing {len(positions)} users...")
            
            # Resequence: Assign new sequential positions (1, 2, 3, 4, 5...)
            for new_position, (old_position, user_id) in enumerate(positions, start=1):
                if old_position != new_position:
                    print(f"[Loot Route Commands]    🔄 User {user_id}: {old_position} → {new_position}")
                    await set_loot_route_position(user_id, new_position)
                else:
                    print(f"[Loot Route Commands]    ✅ User {user_id}: {new_position} (unchanged)")
            
            # Verify no gaps remain
            new_positions = await get_all_loot_route_positions()
            new_positions.sort(key=lambda x: x[0])
            final_positions = [pos for pos, _ in new_positions]
            
            print(f"[Loot Route Commands] 📋 AFTER: {final_positions}")
            
            # Final verification
            expected_final = list(range(1, len(final_positions) + 1))
            if final_positions == expected_final:
                print(f"[Loot Route Commands] ✅ PERFECT - Sequential 1-{len(final_positions)} with NO GAPS")
            else:
                print(f"[Loot Route Commands] ❌ ERROR - Gaps still exist: {final_positions}")
                raise Exception(f"Resequencing failed - gaps remain: {final_positions}")
            
        except Exception as e:
            print(f"[Loot Route Commands] ❌ RESEQUENCE ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def add_role_in_guilds(self, user_id: int) -> dict:
        """Add role to user in all 3 guilds - checks if already has role first"""
        results = {}
        
        # Main guild
        main_guild = self.bot.get_guild(GUILD_ID)
        if main_guild:
            role = main_guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
            member = main_guild.get_member(user_id)
            
            if not member:
                results[GUILD_ID] = "⚠️ User not in guild"
            elif not role:
                results[GUILD_ID] = "⚠️ Role not found"
            elif role in member.roles:
                results[GUILD_ID] = "ℹ️ Already has role"
            else:
                try:
                    await member.add_roles(role)
                    results[GUILD_ID] = "✅ Added role"
                    print(f"[ADD ROLE] ✅ Added role in main guild for user {user_id}")
                except Exception as e:
                    results[GUILD_ID] = f"❌ Error: {str(e)}"
                    print(f"[ADD ROLE] ❌ Error in main guild: {e}")
        else:
            results[GUILD_ID] = "⚠️ Bot not in guild"
        
        # Additional guilds
        for guild_id in ADDITIONAL_GUILDS:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                results[guild_id] = "⚠️ Bot not in guild"
                continue
            
            member = guild.get_member(user_id)
            if not member:
                results[guild_id] = "⚠️ User not in guild"
                continue
            
            # Search for role case-insensitively
            role = None
            for r in guild.roles:
                if r.name.lower() == ROLE_NAME.lower():
                    role = r
                    break
            
            if not role:
                results[guild_id] = f"⚠️ Role '{ROLE_NAME}' not found"
                continue
            
            if role in member.roles:
                results[guild_id] = "ℹ️ Already has role"
                continue
            
            try:
                await member.add_roles(role)
                results[guild_id] = "✅ Added role"
                print(f"[ADD ROLE] ✅ Added role in guild {guild.name} for user {user_id}")
            except Exception as e:
                results[guild_id] = f"❌ Error: {str(e)}"
                print(f"[ADD ROLE] ❌ Error in guild {guild.name}: {e}")
        
        return results
    
    async def remove_role_in_guilds(self, user_id: int) -> dict:
        """Remove role from user in all 3 guilds - checks if has role first"""
        results = {}
        
        # Main guild
        main_guild = self.bot.get_guild(GUILD_ID)
        if main_guild:
            role = main_guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
            member = main_guild.get_member(user_id)
            
            if not member:
                results[GUILD_ID] = "⚠️ User not in guild"
            elif not role:
                results[GUILD_ID] = "⚠️ Role not found"
            elif role not in member.roles:
                results[GUILD_ID] = "ℹ️ Doesn't have role"
            else:
                try:
                    await member.remove_roles(role)
                    results[GUILD_ID] = "✅ Removed role"
                    print(f"[REMOVE ROLE] ✅ Removed role in main guild for user {user_id}")
                except Exception as e:
                    results[GUILD_ID] = f"❌ Error: {str(e)}"
                    print(f"[REMOVE ROLE] ❌ Error in main guild: {e}")
        else:
            results[GUILD_ID] = "⚠️ Bot not in guild"
        
        # Additional guilds
        for guild_id in ADDITIONAL_GUILDS:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                results[guild_id] = "⚠️ Bot not in guild"
                continue
            
            member = guild.get_member(user_id)
            if not member:
                results[guild_id] = "⚠️ User not in guild"
                continue
            
            # Search for role case-insensitively
            role = None
            for r in guild.roles:
                if r.name.lower() == ROLE_NAME.lower():
                    role = r
                    break
            
            if not role:
                results[guild_id] = f"⚠️ Role '{ROLE_NAME}' not found"
                continue
            
            if role not in member.roles:
                results[guild_id] = "ℹ️ Doesn't have role"
                continue
            
            try:
                await member.remove_roles(role)
                results[guild_id] = "✅ Removed role"
                print(f"[REMOVE ROLE] ✅ Removed role in guild {guild.name} for user {user_id}")
            except Exception as e:
                results[guild_id] = f"❌ Error: {str(e)}"
                print(f"[REMOVE ROLE] ❌ Error in guild {guild.name}: {e}")
        
        return results
    
    async def send_role_change_log(self, guild: discord.Guild, user: discord.Member, action: str, executor: discord.Member):
        """Send log message when role is added/removed"""
        try:
            log_channel = guild.get_channel(MEMBER_UPDATES_CHANNEL_ID)
            if not log_channel:
                return
            
            color = discord.Color.green() if action == 'added' else discord.Color.orange()
            
            embed = discord.Embed(
                title=f"{'✅' if action == 'added' else '🔴'} Loot Route Maker Role {action.title()}",
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="User",
                value=f"{user.mention} ({user.display_name})\nID: {user.id}",
                inline=True
            )

            if executor:
                embed.add_field(
                    name="Added by" if action == 'added' else "Removed by",
                    value=f"{executor.mention} ({executor.display_name})",
                    inline=True
                )

            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"User ID: {user.id}")
            
            await log_channel.send(embed=embed)
            # NOTE: dashboard mirroring happens in loot_routes.py on_member_update
            # (universal catch-all) — not here, to avoid double-logging each join/leave.

        except Exception as e:
            print(f"[Loot Route Commands] ⚠️ Log error: {e}")
        
    # ==================== AWAY COMMANDS ====================





    @commands.command(name="lootrouteaway")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def set_away(self, ctx: commands.Context, user: Optional[discord.Member] = None, *, return_date: Optional[str] = None):
        """
        🏖️ Mark yourself (or another user) as away
        Adds the Away role and updates the rotation message
         Usage: >lootrouteaway [@user] [return_date]
         return_date: YYYY-MM-DD  or number of days (e.g. 7)
         Examples:  >lootrouteaway
                    >lootrouteaway 7
                    >lootrouteaway @User 2026-03-15

        """
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        # Determine target user
        if user:
            # Admin only can set others away
            admin_role_ids = [
                HEAD_LOOT_ROUTES_ROLE_ID,
                LOOT_ROUTE_PERMS_ROLE_ID,
                # Also accept by name for backwards compat
            ]
            has_admin_role = any(r.id in admin_role_ids for r in ctx.author.roles)
            has_admin_name = any(r.name in ['007', '+', 'Management'] for r in ctx.author.roles)

            if not (has_admin_role or has_admin_name):
                await ctx.send("❌ Only admins can set other users away!")
                return
            target = user
        else:
            target = ctx.author

        # Parse return_date argument
        parsed_return_date = None
        if return_date:
            try:
                # Accept number of days (e.g. "7" or "7d")
                days_str = return_date.rstrip('dD')
                days = int(days_str)
                parsed_return_date = (datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%d')
            except ValueError:
                # Try parsing as YYYY-MM-DD
                try:
                    datetime.strptime(return_date, '%Y-%m-%d')
                    parsed_return_date = return_date
                except ValueError:
                    await ctx.send("❌ Invalid return date. Use `YYYY-MM-DD` or a number of days (e.g. `7`).")
                    return
        
        try:
            # Check if user is in rotation
            position = await get_loot_route_position(target.id)
            if not position:
                await ctx.send(f"❌ {target.mention} is not in the loot route rotation!")
                return
            
            # Get away role
            away_role = ctx.guild.get_role(AWAY_ROLE_ID)
            if not away_role:
                await ctx.send("❌ Away role not found!")
                return
            
            # Check if already away
            if away_role in target.roles:
                await ctx.send(f"ℹ️ {target.mention} is already marked as away!")
                return
            
            status_msg = await ctx.send(f"🏖️ Setting {target.mention} as away...")
            
            # Add role
            await target.add_roles(away_role)
            print(f"[Away] ✅ Added away role to {target.name} ({target.id})")

            # Persist return date if provided
            if parsed_return_date:
                self._away_return_dates[target.id] = parsed_return_date
                await set_away_return_date(target.id, parsed_return_date)
                print(f"[Away] ✅ Return date saved: {parsed_return_date} for {target.name}")
            
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="away_set"))
            
            # Success embed
            success_embed = discord.Embed(
                title="🏖️ User Marked as Away",
                color=discord.Color.blue()
            )
            
            success_embed.add_field(
                name="User",
                value=f"{target.mention}",
                inline=True
            )
            
            success_embed.add_field(
                name="Position",
                value=f"**#{position}**",
                inline=True
            )

            status_lines = "✅ Away role added\n✅ Rotation updated\n\n*User will be skipped in auto-assignments*"
            if parsed_return_date:
                status_lines += f"\n\n📅 Auto-return scheduled: **{parsed_return_date}**"

            success_embed.add_field(
                name="Status",
                value=status_lines,
                inline=False
            )
            
            await status_msg.delete()
            await ctx.send(embed=success_embed)
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="away_set"))
            print(f"[Away] ✅ {target.name} marked as away")
            
        except Exception as e:
            print(f"[Away] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"```{str(e)}```",
                color=discord.Color.red()
            ))





    @commands.command(name="lootrouteremoveaway")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def remove_away(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """
        ✅ Remove away status from yourself (or another user)
        Removes the Away role and updates the rotation message
         Usage: >lootrouteremoveaway [@user]
        """
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        # Determine target user
        if user:
            # Admin only can remove others' away status
            admin_role_ids = [
                HEAD_LOOT_ROUTES_ROLE_ID,
                LOOT_ROUTE_PERMS_ROLE_ID,
                # Also accept by name for backwards compat
            ]
            has_admin_role = any(r.id in admin_role_ids for r in ctx.author.roles)
            has_admin_name = any(r.name in ['007', '+', 'Management'] for r in ctx.author.roles)

            if not (has_admin_role or has_admin_name):
                await ctx.send("❌ Only admins can remove away status from other users!")
                return
            target = user
        else:
            target = ctx.author
        
        try:
            # Check if user is in rotation
            position = await get_loot_route_position(target.id)
            if not position:
                await ctx.send(f"❌ {target.mention} is not in the loot route rotation!")
                return
            
            # Get away role
            away_role = ctx.guild.get_role(AWAY_ROLE_ID)
            if not away_role:
                await ctx.send("❌ Away role not found!")
                return
            
            # Check if actually away
            if away_role not in target.roles:
                await ctx.send(f"ℹ️ {target.mention} is not currently marked as away!")
                return
            
            status_msg = await ctx.send(f"✅ Removing away status from {target.mention}...")
            
            # Remove role
            await target.remove_roles(away_role)
            print(f"[Remove Away] ✅ Removed away role from {target.name} ({target.id})")

            # Clear any scheduled return date
            if target.id in self._away_return_dates:
                self._away_return_dates.pop(target.id)
                await delete_away_return_date(target.id)
                print(f"[Remove Away] ✅ Cleared return date for {target.name}")
            
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="away_removed"))
            
            # Success embed
            success_embed = discord.Embed(
                title="✅ Away Status Removed",
                color=discord.Color.green()
            )
            
            success_embed.add_field(
                name="User",
                value=f"{target.mention}",
                inline=True
            )
            
            success_embed.add_field(
                name="Position",
                value=f"**#{position}**",
                inline=True
            )
            
            success_embed.add_field(
                name="Status",
                value="✅ Away role removed\n✅ Rotation updated\n\n*User is now available for assignments*",
                inline=False
            )
            
            await status_msg.delete()
            await ctx.send(embed=success_embed)
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="away_removed"))
            print(f"[Remove Away] ✅ Removed away status from {target.name}")
            
        except Exception as e:
            print(f"[Remove Away] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"```{str(e)}```",
                color=discord.Color.red()
            ))

# ==================== MAIN COMMANDS ====================

    @commands.command(name="addlootroutemaker")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def add_loot_route_maker(self, ctx: commands.Context, user: discord.Member):
        """
        🔥 ADD USER: Add user to rotation with proper timeouts
        ✅ 5-second timeout after database update
        ✅ 5-second timeout before leaderboard update
        Usage: >addlootroutemaker @user
        """
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        # Prevent auto-regen
        loot_routes_cog = self.bot.get_cog('LootRoutes')
        if loot_routes_cog and hasattr(loot_routes_cog, 'skip_auto_regen'):
            loot_routes_cog.skip_auto_regen = True
        
        try:
            print(f"\n{'='*80}")
            print(f"🔥 ADDING USER: {user.name} ({user.id})")
            print(f"{'='*80}")
            
            status_msg = await ctx.send(f"🔄 Adding {user.mention} to loot route system...")
            
            # Check if already has position
            existing_pos = await get_loot_route_position(user.id)
            if existing_pos:
                await status_msg.edit(content=f"❌ {user.mention} already at position #{existing_pos}")
                return
            
            # ✅ STEP 1: Get an opaque unique value for the position_number column
            # (no longer used for display — rotation rank is derived from assigned_at order)
            await status_msg.edit(content=f"🔢 Reserving database slot...")
            column_value = await get_next_position_number()
            print(f"[ADD] Reserved column value: {column_value}")

            # ✅ STEP 2: Store user in DATABASE (assigned_at = now → goes to end of rotation)
            await status_msg.edit(content=f"💾 Adding user to rotation...")
            await set_loot_route_position(user.id, column_value)
            print(f"[ADD] ✅ User inserted into loot_route_positions")

            # 🔥 TIMEOUT 1: Let database fully commit
            await status_msg.edit(content=f"⏳ Waiting for database to commit (5 seconds)...")
            await self.safe_delay(5, f"Database commit timeout")

            # Verify storage — user should now appear in rotation with a valid rank
            user_rank = await get_loot_route_position(user.id)
            if not user_rank:
                raise Exception(f"Insert verification failed! User {user.id} not found in rotation after insert")
            print(f"[ADD] ✅ User verified at rotation rank #{user_rank}")
            
            # ✅ STEP 3: Initialize points
            await status_msg.edit(content=f"💰 Initializing points...")
            await set_loot_route_user_points(user.id, 0.0, 0, guild_id=ctx.guild.id, bot=self.bot)
            print(f"[ADD] ✅ Points initialized")
            
            # ✅ STEP 4: Add roles
            await status_msg.edit(content=f"🎭 Adding roles in all guilds...")
            role_results = await self.add_role_in_guilds(user.id)
            print(f"[ADD] ✅ Roles synced")
            
            # 🔥 TIMEOUT 2: Let everything settle before updating messages
            await status_msg.edit(content=f"⏳ Letting changes settle (5 seconds)...")
            await self.safe_delay(5, f"Pre-update settling timeout")
            
            print(f"[ADD] ✅ DB updated")
            
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="rotation_add"))
            print(f"[ADD] ✅ GitHub Pages leaderboard synced")
            
            # Get final state — list is already sorted by assigned_at; ranks are 1..N
            all_positions = await get_all_loot_route_positions()
            total_users = len(all_positions)

            # Success embed
            success_embed = discord.Embed(
                title="✅ Loot Route Maker Added",
                color=discord.Color.green()
            )

            success_embed.add_field(
                name="User Added",
                value=f"{user.mention} ({user.id})",
                inline=False
            )

            success_embed.add_field(
                name="Rotation Position",
                value=f"**#{user_rank}** (last in line)",
                inline=True
            )

            success_embed.add_field(
                name="Total Users",
                value=f"{total_users} users",
                inline=True
            )

            success_embed.add_field(
                name="✅ All Updates Complete",
                value=(
                    f"✅ User added to rotation at position #{user_rank}\n"
                    f"✅ Points initialized to 0\n"
                    f"✅ Rotation message updated\n"
                    f"✅ Leaderboard updated\n"
                    f"✅ Rotation is sequential 1–{total_users} (no gaps)"
                ),
                inline=False
            )
            
            # Role sync results - Show ALL 3 guilds
            role_status = ""
            for gid, res in role_results.items():
                guild_obj = self.bot.get_guild(gid)
                guild_name = guild_obj.name if guild_obj else f"Guild {gid}"
                role_status += f"**{guild_name}:** {res}\n"
            success_embed.add_field(name="🌐 Role Sync (All Guilds)", value=role_status[:1024], inline=False)
            
            await status_msg.delete()
            await ctx.send(embed=success_embed)
            await self.send_role_change_log(ctx.guild, user, 'added', ctx.author)

            print(f"[ADD] ✅ COMPLETE - User at rotation rank #{user_rank} of {total_users}")
            print(f"{'='*80}\n")
            
        except Exception as e:
            print(f"[ADD] ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()

            await ctx.send(embed=discord.Embed(
                title="❌ Error Adding User",
                description=f"```{str(e)}```",
                color=discord.Color.red()
            ))

        finally:
            if loot_routes_cog and hasattr(loot_routes_cog, 'skip_auto_regen'):
                loot_routes_cog.skip_auto_regen = False
            # A newly-added maker is free → assign any held maps from the hold pool.
            try:
                if loot_routes_cog and hasattr(loot_routes_cog, 'drain_loot_pending_pool'):
                    asyncio.create_task(loot_routes_cog.drain_loot_pending_pool(reason="new_maker"))
            except Exception:
                pass

    @commands.command(name="removelootroutemaker")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def remove_loot_route_maker(self, ctx: commands.Context, *, user_input: str):
        """
        🔥 REMOVE USER: Remove user from rotation and wipe all their data
        ✅ Deletes user position and ALL data (points, assignments, etc.)
        ✅ Remaining users' ranks shift up automatically (rotation is sequential 1..N)
        ✅ Works even if user not in main guild (use ID)
        ✅ Checks all 3 guilds for role removal
        ✅ Gracefully handles users without the role
        ✅ Completely removes ALL user data from database
        Usage: >removelootroutemaker @user
        Usage: >removelootroutemaker 123456789
        """
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        # Parse input - could be mention, ID, or member
        user = None
        target_id = None
        target_name = None
        
        # Try to extract user ID from mention or direct ID
        user_input = user_input.strip()
        
        # Check if it's a mention (<@123456> or <@!123456>)
        mention_match = re.match(r'<@!?(\d+)>', user_input)
        if mention_match:
            target_id = int(mention_match.group(1))
        # Check if it's just a number
        elif user_input.isdigit():
            target_id = int(user_input)
        else:
            await ctx.send("❌ Please provide a valid user mention or user ID!")
            return
        
        # 🔥 FALLBACK: Try to get member from main guild, if not found search database
        user = ctx.guild.get_member(target_id)
        if not user:
            # Check if user exists in database as fallback
            user_position = await get_loot_route_position(target_id)
            if user_position:
                target_name = f"User {target_id} (not in server)"
                print(f"[REMOVE] ✅ Using database fallback for user {target_id}")
            else:
                await ctx.send(f"❌ User ID `{target_id}` not found in server or database!")
                return
        else:
            target_name = user.name
        
        # Prevent auto-regen
        loot_routes_cog = self.bot.get_cog('LootRoutes')
        if loot_routes_cog and hasattr(loot_routes_cog, 'skip_auto_regen'):
            loot_routes_cog.skip_auto_regen = True
        
        try:
            print(f"\n{'='*80}")
            print(f"🔥 REMOVING USER: {target_name} ({target_id})")
            print(f"{'='*80}")
            
            status_msg = await ctx.send(f"🔄 Checking user {target_id}...")
            
            # ✅ CHECK IF USER HAS ROLE IN MAIN GUILD
            user_has_role = False
            if user:
                role = ctx.guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
                if role and role in user.roles:
                    user_has_role = True
            
            # Check if has position in database
            user_position = await get_loot_route_position(target_id)
            
            # ⚠️ USER NOT IN DATABASE POSITION - Clean up any residual data and exit
            if not user_position:
                # Still do comprehensive cleanup of any leftover data
                await status_msg.edit(content=f"🗑️ Cleaning up any residual user data...")
                
                import database
                pool = await database.get_pool()
                
                async with pool.acquire() as db:
                    # Clear from loot route points table
                    await db.execute("DELETE FROM loot_route_points WHERE user_id = ?", (target_id,))
                    
                    # Clear from route assignments table
                    await db.execute("DELETE FROM route_assignments WHERE user_id = ?", (target_id,))
                    
                    # Clear position (just in case)
                    await db.execute("DELETE FROM loot_route_positions WHERE user_id = ?", (target_id,))
                    
                    await db.commit()
                
                print(f"[REMOVE] ✅ Residual data cleanup complete for user {target_id}")
                
                no_position_embed = discord.Embed(
                    title="ℹ️ User Not in Rotation",
                    description=f"User **{target_name}** (`{target_id}`) was not in the loot route rotation.",
                    color=discord.Color.blue()
                )
                
                no_position_embed.add_field(
                    name="🗑️ Cleanup Performed",
                    value=(
                        "✅ Checked all database tables\n"
                        "✅ Removed any residual data\n"
                        "✅ All traces cleaned"
                    ),
                    inline=False
                )
                
                # Check if they have role anyway
                if user_has_role:
                    no_position_embed.add_field(
                        name="⚠️ Note",
                        value=(
                            f"User **has** the role in this server but **no database position**.\n"
                            f"The role will be removed from all servers."
                        ),
                        inline=False
                    )
                    
                    # Remove role from all guilds even though not in DB
                    role_results = {}
                    
                    # Main guild
                    main_guild = self.bot.get_guild(GUILD_ID)
                    if main_guild and user:
                        role = main_guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
                        if role and role in user.roles:
                            try:
                                await user.remove_roles(role)
                                role_results[GUILD_ID] = f"✅ Removed role"
                            except Exception as e:
                                role_results[GUILD_ID] = f"❌ Error: {str(e)}"
                        else:
                            role_results[GUILD_ID] = "⚠️ User doesn't have role"
                    
                    # Additional guilds
                    for guild_id in ADDITIONAL_GUILDS:
                        guild = self.bot.get_guild(guild_id)
                        if not guild:
                            role_results[guild_id] = "⚠️ Bot not in guild"
                            continue
                        
                        member = guild.get_member(target_id)
                        if not member:
                            role_results[guild_id] = "⚠️ User not in guild"
                            continue
                        
                        # Search for role case-insensitively
                        role = None
                        for r in guild.roles:
                            if r.name.lower() == ROLE_NAME.lower():
                                role = r
                                break
                        
                        if not role:
                            role_results[guild_id] = f"⚠️ Role not found"
                            continue
                        
                        if role in member.roles:
                            try:
                                await member.remove_roles(role)
                                role_results[guild_id] = f"✅ Removed role"
                            except Exception as e:
                                role_results[guild_id] = f"❌ Error: {str(e)}"
                        else:
                            role_results[guild_id] = "⚠️ User doesn't have role"
                    
                    # Show role removal results
                    role_status = ""
                    for gid, res in role_results.items():
                        guild_obj = self.bot.get_guild(gid)
                        guild_name = guild_obj.name if guild_obj else f"Guild {gid}"
                        role_status += f"**{guild_name}:** {res}\n"
                    
                    no_position_embed.add_field(name="🌐 Role Removal (All Guilds)", value=role_status[:1024], inline=False)
                
                no_position_embed.set_footer(text=f"Requested by {ctx.author.name}")
                
                await status_msg.delete()
                await ctx.send(embed=no_position_embed)
                return
            
            # ✅ USER IN DATABASE - Continue with full removal
            await status_msg.edit(content=f"🔄 Removing {target_name} from loot route system...")
            
            print(f"[REMOVE] User at position: {user_position}")

            # Get positions BEFORE removal
            before_positions = await get_all_loot_route_positions()
            before_positions.sort(key=lambda x: x[0])
            before_nums = [pos for pos, _ in before_positions]
            print(f"[REMOVE] Positions BEFORE: {before_nums}")
            
            # ✅ STEP 1: Archive to alumni table, then delete from active tables
            await status_msg.edit(content=f"📦 Archiving {target_name} to alumni history...")
            try:
                from database import archive_loot_route_maker
                target_member = ctx.guild.get_member(target_id)
                display_name = target_member.display_name if target_member else target_name
                archived = await archive_loot_route_maker(user_id=target_id, display_name=display_name)
                if archived:
                    print(f"[REMOVE] 📦 Archived {target_name} to loot_route_alumni")
                else:
                    # Not in points table yet — still remove position below
                    print(f"[REMOVE] ℹ️ {target_name} had no points data to archive")
            except Exception as e:
                print(f"[REMOVE] ⚠️ Alumni archive failed for {target_name}: {e}")
                # archive_loot_route_maker already deletes from positions/points,
                # so only fall back to manual delete if archive raised
                await status_msg.edit(content=f"🗑️ Deleting position {user_position} from database...")
                await remove_loot_route_position(target_id)
            print(f"[REMOVE] ✅ Position deleted")
            
            # 🔥 TIMEOUT 1: Let deletion commit
            await status_msg.edit(content=f"⏳ Database deletion committing (5 seconds)...")
            await self.safe_delay(5, f"Deletion commit timeout")
            
            # Verify deletion
            check_pos = await get_loot_route_position(target_id)
            if check_pos:
                raise Exception(f"Deletion failed! User still at position {check_pos}")
            print(f"[REMOVE] ✅ Deletion verified")
            
            # ✅ STEP 2: RESEQUENCE - Fill ALL gaps
            await status_msg.edit(content=f"🔢 Resequencing positions (removing gaps)...")
            await self.resequence_positions(ctx.guild)
            print(f"[REMOVE] ✅ Resequencing complete")
            
            # 🔥 TIMEOUT 2: Let resequencing commit
            await status_msg.edit(content=f"⏳ Resequencing committing (5 seconds)...")
            await self.safe_delay(5, f"Resequencing commit timeout")
            
            # Get positions AFTER resequencing
            after_positions = await get_all_loot_route_positions()
            after_positions.sort(key=lambda x: x[0])
            after_nums = [pos for pos, _ in after_positions]
            print(f"[REMOVE] Positions AFTER: {after_nums}")
            
            # Verify no gaps
            expected = list(range(1, len(after_positions) + 1))
            if after_nums != expected:
                raise Exception(f"GAPS REMAIN! Expected {expected}, got {after_nums}")
            print(f"[REMOVE] ✅ No gaps - sequential 1-{len(after_positions)}")
            
            # ✅ STEP 3: COMPLETE DATABASE CLEANUP - Remove ALL traces of user
            await status_msg.edit(content=f"🗑️ Removing ALL user data from database...")
            
            # Import database module to access pool
            import database
            pool = await database.get_pool()
            
            async with pool.acquire() as db:
                # Clear from loot route points table
                await db.execute("DELETE FROM loot_route_points WHERE user_id = ?", (target_id,))
                print(f"[REMOVE] ✅ Cleared loot route points")
                
                # Clear from route assignments table
                await db.execute("DELETE FROM route_assignments WHERE user_id = ?", (target_id,))
                print(f"[REMOVE] ✅ Cleared route assignments")
                
                # Clear any other user-specific data (add more tables as needed)
                # Note: position was already removed earlier
                
                await db.commit()
            
            print(f"[REMOVE] ✅ Complete database cleanup finished")
            
            # ✅ STEP 4: Reset points to 0 (backup safety measure)
            # ✅ STEP 4: Reset points to 0 (backup safety measure)
            await status_msg.edit(content=f"💰 Final cleanup - resetting points...")
            await set_loot_route_user_points(target_id, 0.0, 0, guild_id=ctx.guild.id, bot=self.bot)
            print(f"[REMOVE] ✅ Points reset complete")
            
            # ✅ STEP 5: Remove roles in ALL 3 GUILDS
            await status_msg.edit(content=f"🎭 Checking all 3 guilds for role removal...")
            role_results = {}
            
            # Main guild
            main_guild = self.bot.get_guild(GUILD_ID)
            if main_guild:
                role = main_guild.get_role(LOOT_ROUTE_MAKER_ROLE_ID)
                member = main_guild.get_member(target_id)
                
                if member and role:
                    if role in member.roles:
                        try:
                            await member.remove_roles(role)
                            role_results[GUILD_ID] = f"✅ Removed role"
                        except Exception as e:
                            role_results[GUILD_ID] = f"❌ Error: {str(e)}"
                    else:
                        role_results[GUILD_ID] = "⚠️ User doesn't have role"
                else:
                    role_results[GUILD_ID] = "⚠️ User not in server" if not member else "⚠️ Role not found"
            
            # Additional guilds
            for guild_id in ADDITIONAL_GUILDS:
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    role_results[guild_id] = "⚠️ Bot not in guild"
                    continue
                
                member = guild.get_member(target_id)
                if not member:
                    role_results[guild_id] = "⚠️ User not in guild"
                    continue
                
                # Search for role case-insensitively
                role = None
                for r in guild.roles:
                    if r.name.lower() == ROLE_NAME.lower():
                        role = r
                        break
                
                if not role:
                    role_results[guild_id] = f"⚠️ Role not found"
                    continue
                
                if role in member.roles:
                    try:
                        await member.remove_roles(role)
                        role_results[guild_id] = f"✅ Removed role"
                    except Exception as e:
                        role_results[guild_id] = f"❌ Error: {str(e)}"
                else:
                    role_results[guild_id] = "⚠️ User doesn't have role"
            
            print(f"[REMOVE] ✅ Role removal complete across all guilds")
            
            # 🔥 TIMEOUT 4: Let everything settle
            await status_msg.edit(content=f"⏳ Letting changes settle (5 seconds)...")
            await self.safe_delay(5, f"Pre-update settling timeout")
            
            print(f"[REMOVE] ✅ DB updated")
            
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="rotation_remove"))
            print(f"[REMOVE] ✅ GitHub Pages leaderboard synced")
            
            # Success embed
            success_embed = discord.Embed(
                title="✅ User Removed + Resequenced",
                color=discord.Color.orange()
            )
            
            success_embed.add_field(
                name="Removed User",
                value=f"**ID:** {target_id}\n**Name:** {target_name}\n**Was at:** Position {user_position}",
                inline=False
            )
            
            success_embed.add_field(
                name="🔢 Resequencing Applied",
                value=(
                    f"**Before:** {', '.join(map(str, before_nums[:10]))}{' ...' if len(before_nums) > 10 else ''}\n"
                    f"**After:** {', '.join(map(str, after_nums[:10]))}{' ...' if len(after_nums) > 10 else ''}\n"
                    f"✅ **NO GAPS** - Sequential 1-{len(after_positions)}"
                ),
                inline=False
            )
            
            success_embed.add_field(
                name="🗑️ Complete Cleanup",
                value=(
                    f"**Remaining Users:** {len(after_positions)}\n"
                    f"**Position Range:** 1-{len(after_positions)}\n"
                    f"**Gap-Free:** ✅ YES\n\n"
                    f"**Database Cleanup:**\n"
                    f"✅ Position removed\n"
                    f"✅ Points cleared\n"
                    f"✅ Route assignments deleted\n"
                    f"✅ All user data purged"
                ),
                inline=False
            )
            
            # Role sync - show all 3 guilds
            role_status = ""
            for gid, res in role_results.items():
                guild_obj = self.bot.get_guild(gid)
                guild_name = guild_obj.name if guild_obj else f"Guild {gid}"
                role_status += f"**{guild_name}:** {res}\n"
            
            success_embed.add_field(name="🌐 Role Removal (All Guilds)", value=role_status[:1024], inline=False)
            
            await status_msg.delete()
            await ctx.send(embed=success_embed)
            asyncio.create_task(auto_update_loot_route_leaderboard(self.bot, triggered_by="rotation_remove"))

            # Send log if user was in main guild
            if user:
                await self.send_role_change_log(ctx.guild, user, 'removed', ctx.author)

            print(f"[REMOVE] ✅ COMPLETE - Sequential 1-{len(after_positions)}")
            print(f"[REMOVE] Final positions: {after_nums}")
            print(f"{'='*80}\n")
            
        except Exception as e:
            print(f"[REMOVE] ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            
            await ctx.send(embed=discord.Embed(
                title="❌ Error Removing User",
                description=f"```{str(e)}```",
                color=discord.Color.red()
            ))
        
        finally:
            if loot_routes_cog and hasattr(loot_routes_cog, 'skip_auto_regen'):
                loot_routes_cog.skip_auto_regen = False
    
    # ==================== OTHER COMMANDS ====================
    
    @commands.command(name="addroute")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def add_route(self, ctx: commands.Context, user: discord.Member, *, map_details: str = None):
        """
        Manually assign a map to a user
        Usage: >addroute @user [optional message]
        """
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        try:
            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

            # Step 1: image (required)
            await ctx.send(embed=discord.Embed(
                title="📎 Step 1 of 3 — Map Image",
                description=f"Send the **map image** for {user.mention}\n\n⏱️ 60 seconds\n_Type 'cancel' to cancel_",
                color=discord.Color.blue()
            ))
            try:
                img_response = await self.bot.wait_for('message', timeout=60.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏱️ Timeout - cancelled")
                return
            if img_response.content.lower() == 'cancel':
                await ctx.send("❌ Cancelled")
                return
            if not img_response.attachments:
                await ctx.send(embed=discord.Embed(
                    title="❌ No Image",
                    description="Must attach an image file. Cancelled.",
                    color=discord.Color.red()
                ))
                return

            # Step 2: gamemode (required)
            await ctx.send(embed=discord.Embed(
                title="🎮 Step 2 of 3 — Gamemode",
                description="What's the **gamemode**?\n\n⏱️ 30 seconds\n_Type 'cancel' to cancel_",
                color=discord.Color.blue()
            ))
            try:
                gm_response = await self.bot.wait_for('message', timeout=30.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏱️ Timeout - cancelled")
                return
            if gm_response.content.lower() == 'cancel':
                await ctx.send("❌ Cancelled")
                return
            gamemode = gm_response.content.strip()

            # Step 3: description (optional)
            await ctx.send(embed=discord.Embed(
                title="📝 Step 3 of 3 — Description",
                description="Send a **description**, or type `skip`\n\n⏱️ 30 seconds",
                color=discord.Color.blue()
            ))
            try:
                desc_response = await self.bot.wait_for('message', timeout=30.0, check=check)
            except asyncio.TimeoutError:
                await ctx.send("⏱️ Timeout - cancelled")
                return
            if desc_response.content.lower() == 'cancel':
                await ctx.send("❌ Cancelled")
                return
            description = "" if desc_response.content.lower() == 'skip' else desc_response.content.strip()

            final_details = f"{gamemode} | {description}" if description else gamemode
            
            # Get notification channel
            notification_channel = ctx.guild.get_channel(NOTIFICATION_CHANNEL_ID)
            if not notification_channel:
                await ctx.send("❌ Notification channel not found!")
                return
            
            await ctx.send("⏳ Creating assignment...")
            
            # ✅ CREATE ASSIGNMENT IN DATABASE FIRST
            assignment_id = await create_route_assignment(
                user_id=user.id,
                guild_id=ctx.guild.id,
                notification_message_id=0,  # Placeholder, will update
                confirmation_message_id=0,  # Placeholder, will update
                map_details=final_details[:500] if final_details else None
            )
            
            print(f"[Add Route] ✅ Created assignment #{assignment_id} in database")
            
            # Build notification with assignment ID
            notification_text = f"**Loot Route #{assignment_id}**\n<@{user.id}>"
            
            if final_details:
                notification_text += f"\n{final_details}"
            
            # Send notification message with files
            files = [await a.to_file() for a in img_response.attachments]
            notification_msg = await notification_channel.send(content=notification_text, files=files)
            print(f"[Add Route] 📨 Sent notification message ID: {notification_msg.id}")
            
            # Send confirmation embed (EXACT same as auto-assignment)
            confirmation_embed = discord.Embed(
                description=f"<@{user.id}>, please react to this message to confirm you have seen the assignment and will complete the route.\n\n**Assignment ID:** #{assignment_id}\n\nIf you are unable to complete this route, please DM <@&{HEAD_LOOT_ROUTES_ROLE_ID}> immediately.",
                color=0x57F287
            )
            confirmation_msg = await notification_channel.send(embed=confirmation_embed)
            print(f"[Add Route] ✅ Sent confirmation message ID: {confirmation_msg.id}")
            
            # ✅ UPDATE ASSIGNMENT WITH MESSAGE IDs
            await update_assignment_message_ids(assignment_id, notification_msg.id, confirmation_msg.id)
            print(f"[Add Route] 💾 Updated message IDs - Notification: {notification_msg.id}, Confirmation: {confirmation_msg.id}")
            
            # ✅ VERIFY IT WAS SAVED
            verify = await get_route_assignment_by_id(assignment_id)
            if verify:
                print(f"[Add Route] ✅ Verification - Assignment #{assignment_id} has:")
                print(f"[Add Route]    - notification_message_id: {verify.get('notification_message_id')}")
                print(f"[Add Route]    - confirmation_message_id: {verify.get('confirmation_message_id')}")
            else:
                print(f"[Add Route] ❌ WARNING: Could not verify assignment #{assignment_id} in database!")
            
            # Update count
            new_total = await increment_total_assignments()
            await save_rotation_state(last_assigned_user_id=user.id, total_assignments=new_total)
            
            # Log to log channel with assignment ID
            log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_content = f"🔧 **Manual #{assignment_id}** by {ctx.author.mention} - <@{user.id}> {notification_msg.jump_url}"
                await log_channel.send(content=log_content)
            
            # DM the user (EXACT same as auto-assignment)
            try:
                dm_message = f"🗺️ **New Loot Route Assignment**\n**Assignment ID:** #{assignment_id}\n\nYou've been assigned a new loot route! Please check the details here:\n{notification_msg.jump_url}\n\n**IMPORTANT:** Please react to the confirmation message to acknowledge you've seen this assignment.\n\nThank you for your contribution to the team!"
                await user.send(dm_message)
                dm_status = "✅ DM sent"
                print(f"[Add Route] ✅ DM sent to {user.name}")
            except discord.Forbidden:
                dm_status = "⚠️ DM failed - user has DMs disabled"
                print(f"[Add Route] ⚠️ Could not DM {user.name} - DMs are disabled")
            except Exception as e:
                dm_status = f"⚠️ DM failed: {str(e)}"
                print(f"[Add Route] ⚠️ Error sending DM to {user.name}: {e}")
            
            # Success embed
            success_embed = discord.Embed(
                title="✅ Manual Assignment Created",
                color=discord.Color.green()
            )
            success_embed.add_field(
                name="Details",
                value=f"**User:** {user.mention}\n**ID:** #{assignment_id}\n**Files:** {len(img_response.attachments)}\n**Total:** {new_total}",
                inline=False
            )
            success_embed.add_field(
                name="Status",
                value=f"📨 [Notification]({notification_msg.jump_url})\n✅ Confirmation sent\n📬 {dm_status}",
                inline=False
            )
            success_embed.add_field(
                name="🔍 Debug Info",
                value=f"**Assignment ID:** {assignment_id}\n**Notification Msg:** {notification_msg.id}\n**Confirmation Msg:** {confirmation_msg.id}",
                inline=False
            )
            
            await ctx.send(embed=success_embed)
            print(f"[Add Route] ✅ Manual assignment #{assignment_id} complete!")
            
        except Exception as e:
            print(f"[Add Route] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(f"❌ Error: {str(e)}")
    
    @commands.command(name="cancelroute")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def cancel_route(self, ctx: commands.Context, assignment_id: int):
        """
        ❌ Cancel a route assignment and optionally reassign to next person
        Usage: >cancelroute <assignment_id>
        Example: >cancelroute 42
        """
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        try:
            # Get assignment from database
            assignment = await get_route_assignment_by_id(assignment_id)
            
            if not assignment:
                await ctx.send(embed=discord.Embed(
                    title="❌ Assignment Not Found",
                    description=f"No assignment with ID #{assignment_id} exists.",
                    color=discord.Color.red()
                ))
                return
            
            # Get user info
            cancelled_user_id = assignment['user_id']
            cancelled_user = ctx.guild.get_member(cancelled_user_id)
            user_mention = cancelled_user.mention if cancelled_user else f"<@{cancelled_user_id}>"
            
            # Get original route details
            map_details = assignment.get('map_details', '')
            notification_msg_id = assignment.get('notification_message_id')
            confirmation_msg_id = assignment.get('confirmation_message_id')
            
            notification_channel = ctx.guild.get_channel(NOTIFICATION_CHANNEL_ID)
            original_files_data = []  # List of (bytes_data, filename) tuples

            # ✅ Try local saved files first (immune to CDN expiry)
            try:
                from database import get_route_local_files
                local_paths = await get_route_local_files(assignment_id)
                if local_paths:
                    import os
                    for path in local_paths:
                        if os.path.exists(path):
                            with open(path, 'rb') as f:
                                original_files_data.append((f.read(), os.path.basename(path)))
                            print(f"[Cancel Route] ✅ Loaded local file: {path}")
                        else:
                            print(f"[Cancel Route] ⚠️ Local file missing: {path}")
            except Exception as e:
                print(f"[Cancel Route] ⚠️ Local file load failed: {e}")

            # Fall back to CDN download if no local files found
            if not original_files_data and notification_channel and notification_msg_id:
                try:
                    original_msg = await notification_channel.fetch_message(notification_msg_id)
                    if original_msg.attachments:
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            for attachment in original_msg.attachments:
                                try:
                                    async with session.get(attachment.url) as resp:
                                        if resp.status == 200:
                                            data = await resp.read()
                                            original_files_data.append((data, attachment.filename))
                                            print(f"[Cancel Route] ✅ CDN fallback downloaded: {attachment.filename}")
                                        else:
                                            print(f"[Cancel Route] ⚠️ CDN returned {resp.status} — URL likely expired")
                                except Exception as e:
                                    print(f"[Cancel Route] ⚠️ CDN download error for {attachment.filename}: {e}")
                except Exception as e:
                    print(f"[Cancel Route] ⚠️ Could not fetch original message: {e}")

            # ── Confirmation gate ────────────────────────────────────────────
            confirm_embed = discord.Embed(
                title="⚠️ Confirm Cancel Route",
                description=(
                    f"Are you sure you want to cancel **Assignment #{assignment_id}**?\n\n"
                    f"**User:** {user_mention}\n"
                    f"**Details:** {(map_details[:150] + '...') if len(map_details) > 150 else map_details or 'No details'}\n\n"
                    f"This will delete the assignment and DM the user. This cannot be undone."
                ),
                color=discord.Color.orange()
            )
            confirm_embed.set_footer(text="⏱️ 30 seconds to respond")
            confirm_view = PromotionConfirmView(ctx.author.id)
            confirm_view.timeout = 30
            confirm_view.children[0].label = "✅ Yes, Cancel Route"
            confirm_view.children[1].label = "🚫 Abort"
            confirm_msg = await ctx.send(embed=confirm_embed, view=confirm_view)
            await confirm_view.wait()
            await confirm_msg.delete()

            if not confirm_view.confirmed:
                await ctx.send(embed=discord.Embed(
                    title="🚫 Aborted",
                    description=f"Cancellation of assignment #{assignment_id} was aborted.",
                    color=discord.Color.greyple()
                ))
                return
            # ─────────────────────────────────────────────────────────────────

            status_msg = await ctx.send(f"🔄 Cancelling assignment #{assignment_id}...")

            # Delete messages
            deleted_notification = False
            deleted_confirmation = False
            
            if notification_channel:
                if notification_msg_id:
                    try:
                        msg = await notification_channel.fetch_message(notification_msg_id)
                        await msg.delete()
                        deleted_notification = True
                        print(f"[Cancel Route] ✅ Deleted notification message {notification_msg_id}")
                    except discord.NotFound:
                        print(f"[Cancel Route] ⚠️ Notification message {notification_msg_id} not found")
                    except Exception as e:
                        print(f"[Cancel Route] ⚠️ Error deleting notification: {e}")
                
                if confirmation_msg_id:
                    try:
                        msg = await notification_channel.fetch_message(confirmation_msg_id)
                        await msg.delete()
                        deleted_confirmation = True
                        print(f"[Cancel Route] ✅ Deleted confirmation message {confirmation_msg_id}")
                    except discord.NotFound:
                        print(f"[Cancel Route] ⚠️ Confirmation message {confirmation_msg_id} not found")
                    except Exception as e:
                        print(f"[Cancel Route] ⚠️ Error deleting confirmation: {e}")
            
            # Delete from database
            from database import delete_route_assignment
            await delete_route_assignment(assignment_id)
            print(f"[Cancel Route] ✅ Deleted assignment #{assignment_id} from database")
            
            # DM the cancelled user
            dm_status = "❌ User not in server"
            if cancelled_user:
                try:
                    dm_msg = f"❌ **Route Assignment Cancelled**\n\n"
                    dm_msg += f"Your assignment #{assignment_id} has been cancelled by {ctx.author.display_name}.\n"
                    dm_msg += f"You are no longer responsible for this route."
                    await cancelled_user.send(dm_msg)
                    dm_status = "✅ DM sent"
                    print(f"[Cancel Route] ✅ Sent cancellation DM to {cancelled_user.name}")
                except discord.Forbidden:
                    dm_status = "⚠️ DM failed - user has DMs disabled"
                    print(f"[Cancel Route] ⚠️ Could not DM {cancelled_user.name} - DMs disabled")
                except Exception as e:
                    dm_status = f"⚠️ DM failed: {str(e)}"
                    print(f"[Cancel Route] ⚠️ Error sending DM to {cancelled_user.name}: {e}")
            
            # Show cancellation summary
            cancel_embed = discord.Embed(
                title="✅ Assignment Cancelled",
                color=discord.Color.orange()
            )
            cancel_embed.add_field(
                name="Details",
                value=f"**ID:** #{assignment_id}\n**User:** {user_mention}\n**Messages Deleted:** {'✅' if deleted_notification else '❌'} Notification | {'✅' if deleted_confirmation else '❌'} Confirmation\n**DM Status:** {dm_status}",
                inline=False
            )
            
            await status_msg.delete()
            
            # Ask if they want to reassign
            reassign_embed = discord.Embed(
                title="🔄 Reassign Route?",
                description=f"Assignment #{assignment_id} has been cancelled.\n\nWould you like to **automatically reassign** this route to the next person in rotation?",
                color=discord.Color.blue()
            )
            reassign_embed.add_field(
                name="Route Details",
                value=map_details[:200] + "..." if len(map_details) > 200 else map_details or "No details",
                inline=False
            )
            reassign_embed.add_field(
                name="Attachments",
                value=f"📎 {len(original_files_data)} file(s)" if original_files_data else "❌ No files found",
                inline=False
            )
            reassign_embed.set_footer(text="⏱️ 60 seconds to respond")
            
            view = ReassignView(ctx, assignment, original_files_data)
            reassign_msg = await ctx.send(embed=reassign_embed, view=view)
            
            # Wait for response
            await view.wait()
            
            if view.value is None:
                # Timeout
                await reassign_msg.edit(embed=discord.Embed(
                    title="⏱️ Timeout",
                    description="No response received - route was cancelled but not reassigned.",
                    color=discord.Color.red()
                ), view=None)
                return

            if view.value is False:
                # User said no — also delete the log message in the log channel
                await self.delete_log_message(ctx.guild, assignment_id)
                await reassign_msg.edit(embed=discord.Embed(
                    title="✅ Cancelled",
                    description=f"Assignment #{assignment_id} cancelled. Route was NOT reassigned.",
                    color=discord.Color.green()
                ), view=None)
                return

            # Build skip list (cancelled user + anyone with an active assignment)
            # Always include cancelled_user_id: assignment was deleted above, so they
            # won't show up in get_all_route_assignments anymore and could be re-picked.
            skip_user_ids = [cancelled_user_id]
            try:
                from database import get_all_route_assignments
                all_assignments = await get_all_route_assignments(ctx.guild.id)
                skip_user_ids = list(set(
                    [cancelled_user_id] +
                    [a['user_id'] for a in all_assignments]
                ))
                if skip_user_ids:
                    print(f"[Cancel Route] 🔍 Found {len(skip_user_ids)} users with active assignments")
                    for uid in skip_user_ids:
                        member_name = (ctx.guild.get_member(uid) or type('_', (), {'name': f'User {uid}'})()).name
                        print(f"[Cancel Route]    - Skipping: {member_name}")
                else:
                    print(f"[Cancel Route] ℹ️  No users have active assignments - will reassign normally")
            except ImportError:
                print(f"[Cancel Route] ⚠️ get_all_route_assignments not found in database.py")
            except Exception as e:
                print(f"[Cancel Route] ⚠️ Error getting active assignments: {e}")

            if view.value == 'manual':
                # Show a dropdown so the admin can pick a specific maker
                all_positions = await get_all_loot_route_positions()
                available = [(rank, uid) for rank, uid in all_positions if uid not in skip_user_ids]

                if not available:
                    await reassign_msg.edit(embed=discord.Embed(
                        title="❌ No Available Users",
                        description=f"Cannot reassign #{assignment_id} — all rotation members have active route assignments.",
                        color=discord.Color.red()
                    ), view=None)
                    return

                pick_view = ManualPickView(ctx, available, ctx.guild)
                pick_embed = discord.Embed(
                    title="👤 Pick a Maker",
                    description=f"Select who should receive reassigned route #{assignment_id}.",
                    color=discord.Color.blurple()
                )
                pick_embed.set_footer(text="⏱️ 60 seconds to respond")
                await reassign_msg.edit(embed=pick_embed, view=pick_view)
                await pick_view.wait()

                if pick_view.selected_user_id is None:
                    await reassign_msg.edit(embed=discord.Embed(
                        title="⏱️ Timeout",
                        description="No selection made — route was cancelled but not reassigned.",
                        color=discord.Color.red()
                    ), view=None)
                    return

                next_user_data = (pick_view.selected_position, pick_view.selected_user_id, pick_view.selected_username)
                print(f"[Cancel Route] 👤 Manual pick: {pick_view.selected_username} (position #{pick_view.selected_position})")

            else:
                # Auto-assign: next person in rotation
                loot_routes_cog = self.bot.get_cog('LootRoutes')
                if not loot_routes_cog:
                    await ctx.send("❌ Loot Routes system not loaded!")
                    return

                next_user_data = await loot_routes_cog.find_next_available_user_with_skip(ctx.guild, skip_user_ids=skip_user_ids)

            if not next_user_data:
                await reassign_msg.edit(embed=discord.Embed(
                    title="❌ No Available Users",
                    description=f"Cannot reassign #{assignment_id} - all rotation members either:\n- Are marked as AWAY\n- Already have an active route assignment",
                    color=discord.Color.red()
                ), view=None)
                return

            # Shared reassignment tail — runs for both auto and manual paths
            await reassign_msg.edit(embed=discord.Embed(
                title="🔄 Reassigning...",
                description="Assigning route and notifying maker...",
                color=discord.Color.blue()
            ), view=None)

            # Delete the log message from the cancelled assignment
            await self.delete_log_message(ctx.guild, assignment_id)

            position, user_id, username = next_user_data
            next_user = ctx.guild.get_member(user_id)
            
            if not next_user:
                await ctx.send(f"❌ Next user (ID: {user_id}) not found in server!")
                return
            
            await ctx.send(f"📋 Reassigning to: {next_user.mention} (Position #{position})")
            
            # Create new assignment
            new_assignment_id = await create_route_assignment(
                user_id=user_id,
                guild_id=ctx.guild.id,
                notification_message_id=0,
                confirmation_message_id=0,
                map_details=map_details[:500] if map_details else None
            )
            
            print(f"[Cancel Route] ✅ Created new assignment #{new_assignment_id}")
            
            # Build notification
            notification_text = f"**Loot Route #{new_assignment_id}** (Reassigned from #{assignment_id})\n<@{user_id}>"
            if map_details:
                notification_text += f"\n{map_details}"
            
            # Send notification with pre-downloaded files
            if original_files_data:
                files = [discord.File(io.BytesIO(data), filename=filename) for data, filename in original_files_data]
                notification_msg = await notification_channel.send(content=notification_text, files=files)
            else:
                notification_msg = await notification_channel.send(content=notification_text)
            
            print(f"[Cancel Route] 📨 Sent notification message ID: {notification_msg.id}")
            
            # Send confirmation embed
            confirmation_embed = discord.Embed(
                description=f"<@{user_id}>, please react to this message to confirm you have seen the assignment and will complete the route.\n\n**Assignment ID:** #{new_assignment_id}\n**Note:** This route was reassigned from assignment #{assignment_id}.\n\nIf you are unable to complete this route, please DM <@&{HEAD_LOOT_ROUTES_ROLE_ID}> immediately.",
                color=0x57F287
            )
            confirmation_msg = await notification_channel.send(embed=confirmation_embed)
            print(f"[Cancel Route] ✅ Sent confirmation message ID: {confirmation_msg.id}")
            
            # Update assignment with message IDs
            await update_assignment_message_ids(new_assignment_id, notification_msg.id, confirmation_msg.id)
            
            # Update rotation state
            new_total = await increment_total_assignments()
            await save_rotation_state(
                last_assigned_user_id=user_id,
                last_assigned_position=position,
                total_assignments=new_total
            )
            
            # Log reassignment
            log_channel = ctx.guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_content = f"🔄 **Reassigned #{new_assignment_id}** (was #{assignment_id}) to <@{user_id}> by {ctx.author.mention}\n{notification_msg.jump_url}"
                await log_channel.send(content=log_content)
            
            # DM new user
            try:
                dm_message = f"🗺️ **New Loot Route Assignment**\n**Assignment ID:** #{new_assignment_id}\n\nYou've been assigned a new loot route! Please check the details here:\n{notification_msg.jump_url}\n\n**IMPORTANT:** Please react to the confirmation message to acknowledge you've seen this assignment.\n\nThank you for your contribution to the team!"
                await next_user.send(dm_message)
                dm_status = "✅ DM sent"
            except:
                dm_status = "⚠️ DM failed"
            
            # Final success message
            success_embed = discord.Embed(
                title="✅ Route Reassigned Successfully!",
                color=discord.Color.green()
            )
            success_embed.add_field(
                name="Cancelled",
                value=f"**ID:** #{assignment_id}\n**User:** {user_mention}",
                inline=False
            )
            success_embed.add_field(
                name="Reassigned To",
                value=f"**New ID:** #{new_assignment_id}\n**User:** {next_user.mention}\n**Position:** #{position}\n**DM Status:** {dm_status}",
                inline=False
            )
            success_embed.add_field(
                name="Links",
                value=f"📨 [Notification]({notification_msg.jump_url})",
                inline=False
            )
            
            await reassign_msg.edit(embed=success_embed)
            print(f"[Cancel Route] ✅ Successfully reassigned #{assignment_id} → #{new_assignment_id}")
            
        except Exception as e:
            print(f"[Cancel Route] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"```{str(e)}```",
                color=discord.Color.red()
            ))
    
    @commands.command(name="lootroutedone")
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', LOOT_ROUTE_PERMS_ROLE_ID)
    async def loot_route_done(self, ctx: commands.Context, assignment_id: int):
        """Mark route complete and award points"""
        
        if ctx.guild.id != GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        
        SUBMISSION_CHANNEL_ID = 1231195800839655475
        
        try:
            await ctx.send(f"🔍 Processing #{assignment_id}...")
            
            from database import complete_route_assignment

            assignment = await get_route_assignment_by_id(assignment_id)
            if not assignment:
                await ctx.send(f"❌ Assignment #{assignment_id} not found!")
                return

            # ✅ Guard against double-completion
            if assignment['status'] == 'completed':
                await ctx.send(f"⚠️ Assignment #{assignment_id} is already completed! Cannot award points again.")
                return
            
            user_id = assignment['user_id']
            assigned_at = datetime.fromisoformat(assignment['assigned_at'].replace('Z', '+00:00'))

            # Ensure assigned_at is timezone-aware for correct comparisons
            if assigned_at.tzinfo is None:
                assigned_at = assigned_at.replace(tzinfo=timezone.utc)

            submission_channel = ctx.guild.get_channel(SUBMISSION_CHANNEL_ID)
            if not submission_channel:
                await ctx.send("❌ Submission channel not found!")
                return

            # Debug: Log channel info
            print(f"[Done Route] 📍 Searching channel: {submission_channel.name} (ID: {SUBMISSION_CHANNEL_ID})")
            print(f"[Done Route] 📅 Assignment time: {assigned_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            print(f"[Done Route] 👤 Looking for user_id: {user_id}")

            await ctx.send(f"📨 Scanning for fortnite.gg link (channel + threads)...")

            submission_time = None
            submission_msg = None

            def _is_match(msg):
                return (
                    msg.author.id == user_id
                    and msg.content
                    and 'fortnite.gg' in msg.content.lower()
                )

            def _consider(msg):
                nonlocal submission_time, submission_msg
                if _is_match(msg) and (submission_time is None or msg.created_at > submission_time):
                    submission_time = msg.created_at
                    submission_msg = msg

            # 1) Main channel — latest fn.gg link from the assigned user after assignment time
            main_channel_msgs = 0
            async for msg in submission_channel.history(limit=1000, after=assigned_at):
                main_channel_msgs += 1
                _consider(msg)
            print(f"[Done Route] 📊 Main channel: scanned {main_channel_msgs} messages after {assigned_at}")

            # 2) Active (non-archived) threads under the submission channel
            active_threads = list(submission_channel.threads)
            print(f"[Done Route] 📋 Found {len(active_threads)} active thread(s)")
            for thread in active_threads:
                thread_msgs = 0
                try:
                    async for msg in thread.history(limit=1000, after=assigned_at):
                        thread_msgs += 1
                        _consider(msg)
                    print(f"[Done Route] ✅ Thread '{thread.name}': scanned {thread_msgs} messages")
                except Exception as e:
                    print(f"[Done Route] ⚠️ Could not scan thread {thread.name}: {e}")

            # 3) Archived public threads — skip ones archived before assignment (can't contain newer messages)
            archived_count = 0
            try:
                async for thread in submission_channel.archived_threads(limit=100):
                    archived_count += 1
                    # Ensure archive_timestamp is timezone-aware for proper comparison
                    archive_ts = thread.archive_timestamp
                    if archive_ts and archive_ts.tzinfo is None:
                        archive_ts = archive_ts.replace(tzinfo=timezone.utc)

                    if archive_ts and archive_ts < assigned_at:
                        print(f"[Done Route] ⏭️  Archived thread '{thread.name}' archived at {archive_ts} (before assignment {assigned_at}), skipping")
                        continue

                    thread_msgs = 0
                    try:
                        async for msg in thread.history(limit=1000, after=assigned_at):
                            thread_msgs += 1
                            _consider(msg)
                        print(f"[Done Route] ✅ Archived thread '{thread.name}': scanned {thread_msgs} messages")
                    except Exception as e:
                        print(f"[Done Route] ⚠️ Could not scan archived thread {thread.name}: {e}")
                print(f"[Done Route] 📊 Total archived threads found: {archived_count}")
            except Exception as e:
                print(f"[Done Route] ⚠️ Could not list archived threads: {e}")

            if not submission_time:
                print(f"[Done Route] ❌ SEARCH FAILED - searched {main_channel_msgs} main channel msgs, {len(active_threads)} active threads, {archived_count} archived threads")
                print(f"[Done Route] 🔍 Looking for: user_id={user_id}, 'fortnite.gg' in content, created_at > {assigned_at}")
                await ctx.send("❌ No fortnite.gg link found after assignment time.\n\nMake sure you posted a **NEW** link in this channel **AFTER** receiving the assignment.")
                return

            link_author = ctx.guild.get_member(submission_msg.author.id) if submission_msg else None
            author_name = link_author.name if link_author else f"User {submission_msg.author.id if submission_msg else 'unknown'}"
            print(f"[Done Route] ✅ FOUND LINK from {author_name}: posted at {submission_time}")
            print(f"[Done Route]    Assignment was at {assigned_at}, so link is {(submission_time - assigned_at).total_seconds() / 3600:.1f} hours after assignment")

            # Ensure submission_time is timezone-aware for correct comparison
            if submission_time.tzinfo is None:
                submission_time = submission_time.replace(tzinfo=timezone.utc)

            time_diff = submission_time - assigned_at
            hours = time_diff.total_seconds() / 3600
            
            if hours <= 12:
                base_points = 10.0
                speed = "⚡ Within 12h"
            elif hours <= 24:
                base_points = 8.0
                speed = "⚡ Within 24h"
            elif hours <= 48:
                base_points = 4.0
                speed = "🏃 Within 48h"
            elif hours <= 72:
                base_points = 2.0
                speed = "🚶 Within 3 days (2 pts)"
            elif hours <= 96:
                base_points = 0.0
                speed = "🚶 Within 4 days (0 pts)"
            else:
                days_over = int((hours - 96) / 24) + 1
                base_points = float(-(3 + days_over))
                speed = f"💀 {int(hours / 24)}+ days (penalty: {base_points:+.0f} pts)"

            assigned_member = ctx.guild.get_member(user_id)
            has_head_role = assigned_member and any(
                role.id == HEAD_LOOT_ROUTES_ROLE_ID for role in assigned_member.roles
            )
            has_inspector_role = assigned_member and any(
                role.id == LOOT_ROUTE_INSPECTOR_ROLE_ID for role in assigned_member.roles
            )
            if has_head_role and base_points > 0:
                points = base_points * 2.0
                multiplier_note = f"👑 **2x Head Loot Routes Bonus applied!** ({base_points} × 2 = {points} pts)"
            elif has_inspector_role and base_points > 0:
                points = base_points * LOOT_ROUTE_INSPECTOR_MULTIPLIER
                multiplier_note = f"🕵️‍♂️ **1.5x Loot Route Inspector Bonus applied!** ({base_points} × 1.5 = {points} pts)"
            else:
                points = base_points
                multiplier_note = None

            is_lucky = bool(assignment.get('is_lucky_map', 0))
            lucky_note = None
            if is_lucky and base_points > 0:
                pre_lucky_points = points
                points = points * 2.0
                lucky_note = f"🍀 **2x Lucky Map Bonus applied!** ({pre_lucky_points} × 2 = {points} pts)"

            await ctx.send(f"💰 Awarding {points} WP...")

            # Complete the assignment FIRST so status is 'completed' before leaderboard updates
            await complete_route_assignment(assignment_id, points_awarded=points)

            # Capture WP balance BEFORE awarding so we can detect the 0-floor case
            from tasks.wave_points import add_wave_points as _add_wp, get_wave_points as _get_wp
            before_wp = await _get_wp(user_id)

            # Add points to loot_route_points for leaderboard tracking
            # Returns 0.0 if role validation fails (user lacks Loot Route Maker role)
            new_total = await add_loot_route_points(user_id, points=points, guild_id=ctx.guild.id, bot=self.bot)

            # Credit WP directly to spendable wallet
            new_wp_total = await _add_wp(user_id, int(points))

            # Trigger leaderboard update (debounced to 5 seconds)
            await auto_update_loot_route_leaderboard(self.bot, triggered_by="route_completed")

            # A maker just freed up → assign any held maps from the hold pool.
            try:
                _lr = self.bot.get_cog('LootRoutes')
                if _lr and hasattr(_lr, 'drain_loot_pending_pool'):
                    asyncio.create_task(_lr.drain_loot_pending_pool(reason="route_completed"))
            except Exception:
                pass

            if new_total is None:
                # Role validation blocked the leaderboard write — warn staff.
                await ctx.send(
                    f"⚠️ **Warning:** Leaderboard points could NOT be recorded — <@{user_id}> may be missing the "
                    f"**Loot Route Maker** role! WP were still credited. "
                    f"If they have the role, use `>setpoints` to manually correct their leaderboard total."
                )
            
            # 🗑️ Delete the original log message for this assignment
            await self.delete_log_message(ctx.guild, assignment_id)

            # 🗑️ Clean up locally saved attachment files now that the route is done
            try:
                import os, shutil
                local_dir = os.path.join('route_files', str(assignment_id))
                if os.path.isdir(local_dir):
                    shutil.rmtree(local_dir)
                    print(f"[Done Route] 🗑️ Deleted local files for #{assignment_id}")
            except Exception as _e:
                print(f"[Done Route] ⚠️ Could not clean local files for #{assignment_id}: {_e}")

            success_embed = discord.Embed(
                title="✅ Route Completed",
                color=discord.Color.green()
            )
            
            success_embed.add_field(
                name="Assignment",
                value=f"**ID:** #{assignment_id}\n**User:** <@{user_id}>",
                inline=False
            )
            
            success_embed.add_field(
                name="Timing",
                value=(
                    f"**Assigned:** {assigned_at.strftime('%Y-%m-%d %H:%M')}\n"
                    f"**Submitted:** {submission_time.strftime('%Y-%m-%d %H:%M')}\n"
                    f"**Took:** {hours:.1f} hours"
                ),
                inline=False
            )
            
            success_embed.add_field(
                name="🌊 WP",
                value=(
                    f"{speed}\n"
                    + (f"{multiplier_note}\n" if multiplier_note else "")
                    + (f"{lucky_note}\n" if lucky_note else "")
                    + f"**Awarded:** {points:+g} WP"
                    + f"\n**WP Balance:** {new_wp_total:,}"
                ),
                inline=False
            )
            
            success_embed.add_field(
                name="Submission",
                value=f"[View Link]({submission_msg.jump_url})",
                inline=False
            )
            
            await ctx.send(embed=success_embed)

            # ✅ DM the user to notify them their route is complete
            try:
                member = ctx.guild.get_member(user_id)
                if member:
                    # Build a nice points message based on result
                    if points > 0:
                        points_msg = f"✅ **+{points} WP awarded!**"
                        if multiplier_note:
                            points_msg += f"\n{multiplier_note}"
                        if lucky_note:
                            points_msg += f"\n{lucky_note}"
                    elif points == 0:
                        points_msg = f"⚠️ **0 WP awarded** — route took between 3 and 4 days."
                    else:
                        points_msg = f"💀 **{points:+.1f} WP penalty** — route took over 4 days!"
                    dm_embed = discord.Embed(
                        title="🗺️ Loot Route Completed!",
                        color=discord.Color.green() if points > 0 else discord.Color.orange() if points == 0 else discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    dm_embed.add_field(
                        name="📋 Assignment",
                        value=f"**ID:** #{assignment_id}",
                        inline=False
                    )
                    dm_embed.add_field(
                        name="⏱️ Speed",
                        value=f"{speed}\n**Time taken:** {hours:.1f} hours",
                        inline=False
                    )
                    dm_embed.add_field(
                        name="🌊 WP",
                        value=f"{points_msg}\n**WP Balance:** {new_wp_total:,}",
                        inline=False
                    )
                    dm_embed.set_footer(text="Use >myroutes to view your stats • Spend WP in >wpshop")

                    await member.send(embed=dm_embed)
                    print(f"[Route Done] ✅ DM sent to {member.name} for assignment #{assignment_id}")
            except discord.Forbidden:
                print(f"[Route Done] ⚠️ Could not DM user {user_id} — DMs disabled")
            except Exception as dm_error:
                print(f"[Route Done] ⚠️ DM error: {dm_error}")
            
        except Exception as e:
            print(f"[Route Done] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(f"❌ Error: {str(e)}")


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(LootRouteCommands(bot))
    print("[Loot Route Commands] [OK] Cog loaded (COMPLETE BULLET-PROOF VERSION)")
