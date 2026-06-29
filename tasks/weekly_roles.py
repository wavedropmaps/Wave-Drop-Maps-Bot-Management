"""
Weekly Roles Report - Awards 7/7 and Top Messenger roles
Scans both servers, awards roles in Staff Hub guild
✅ FIXED: Displays 7/7 users as @mentions like in the screenshot
✅ FIXED: Shows congratulations message properly formatted
"""

import discord
from discord.ext import commands
import logging
import traceback
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Set, List, Optional
import json

# Import helpers from core
from core.helpers import (
    get_readable_text_channels,
    safe_history_fetch
)

logger = logging.getLogger(__name__)

# ==================== CONSTANTS ====================
# Trigger time: 169h 30m after week start (30 minutes after staff insights)
WEEKLY_ROLES_HOURS = 169 + (30 / 60)  # = 169.5

# ==================== MESSAGE BANKS ====================
# ✅ CONGRATULATIONS MESSAGE BANK - Random selection each week
CONGRATULATIONS_MESSAGES = [
    "🎉 UNBELIEVABLE DEDICATION FROM {user}! YOU'VE EARNED <@&{role}> WITH {count} MESSAGES! 🎉",
    "🏆 CRUSHING IT! {user} ABSOLUTELY DOMINATED THIS WEEK WITH {count} MESSAGES - <@&{role}> IS YOURS! 🏆",
    "🌟 THE MESSAGING LEGEND RETURNS! {user} WITH AN INCREDIBLE {count} MESSAGES TAKES THE <@&{role}> CROWN! 🌟",
    "⚡ UNSTOPPABLE MOMENTUM! {user} IS ON FIRE WITH {count} MESSAGES - YOU'VE EARNED <@&{role}>! ⚡",
    "💪 WHAT A BEAST! {user} SHOWED UP WITH {count} MESSAGES AND CLAIMED THE <@&{role}> TITLE! 💪",
    "🔥 THE STREAK CONTINUES! {user} BRINGS {count} MESSAGES TO THE TABLE AND WINS <@&{role}>! 🔥",
    "🎯 LOCKED IN AND LOADED! {user} WITH {count} MESSAGES SECURES THE <@&{role}> ROLE! 🎯",
    "👑 ROYALTY STATUS CONFIRMED! {user} REIGNS SUPREME WITH {count} MESSAGES - <@&{role}> CHAMPION! 👑",
    "🚀 SKYROCKETING TO THE TOP! {user} LAUNCHES INTO <@&{role}> TERRITORY WITH {count} MESSAGES! 🚀",
    "✨ ABSOLUTELY GLOWING! {user} SHINES BRIGHT WITH {count} MESSAGES AND EARNS THE <@&{role}> BADGE! ✨",
]

# ✅ STREAK CONTINUATION MESSAGE BANK - For consecutive wins
STREAK_MESSAGES = [
    "AND THE LEGEND GROWS! {user} KEEPS THAT <@&{role}> CROWN FOR {weeks} CONSECUTIVE WEEKS NOW! 👑",
    "BACK-TO-BACK DOMINATION! {user} DEFENDS THEIR MESSAGING THRONE FOR WEEK #{weeks}! 🔥",
    "UNSTOPPABLE FORCE! {user} CONTINUES THE REIGN WITH {weeks} WEEKS OF <@&{role}> GREATNESS! 💪",
    "THE STREAK IS REAL! {user} MAKES IT {weeks} WEEKS IN A ROW AS <@&{role}> CHAMPION! ⚡",
    "DYNASTY STATUS! {user} HAS NOW OWNED <@&{role}> FOR {weeks} STRAIGHT WEEKS! 👑",
    "CAN'T STOP THE MOMENTUM! {user} EXTENDS THE WINNING STREAK TO {weeks} WEEKS! 🚀",
    "ALL HAIL {user}! {weeks} WEEKS OF CONSECUTIVE <@&{role}> DOMINATION! 👑✨",
    "BREAKING RECORDS! {user}'S {weeks}-WEEK MESSAGING STREAK IS ABSOLUTELY INSANE! 🔥",
]

# ==================== HELPER FUNCTIONS ====================

def get_start_datetime(start_date: str) -> datetime:
    """Convert start_date string to datetime at 00:00:00 UTC"""
    if '/' in start_date:
        dt = datetime.strptime(start_date, '%d/%m/%Y')
    else:
        dt = datetime.strptime(start_date, '%Y-%m-%d')
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

def get_end_datetime(end_date: str) -> datetime:
    """Convert end_date string to datetime at 23:59:59 UTC"""
    if '/' in end_date:
        dt = datetime.strptime(end_date, '%d/%m/%Y')
    else:
        dt = datetime.strptime(end_date, '%Y-%m-%d')
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)

def load_config():
    """Load config.json"""
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config.json: {e}")
        return {}

def get_global_dates_from_config():
    """Get global dates from config.json"""
    config = load_config()
    
    # Try to get from global_dates first
    global_dates = config.get('global_dates', {})
    start_date = global_dates.get('start_date')
    end_date = global_dates.get('end_date')
    
    # Fallback to global if not in global_dates
    if not start_date or not end_date:
        global_config = config.get('global', {})
        start_date = global_config.get('start_date')
        end_date = global_config.get('end_date')
    
    return start_date, end_date

async def get_automation_config():
    """Get automation config from config.json"""
    config = load_config()
    return config.get('automated_checks', {})

# ==================== MAIN WEEKLY ROLES FUNCTION ====================

async def send_weekly_roles_report(
    bot,
    database,
    get_automation_config_func,
    start_date: str,
    end_date: str,
    is_test: bool = False
):
    """
    Weekly Roles Report - Awards 7/7 and Top Messenger roles
    """
    try:
        logger.info(f"🏆 Starting Weekly Roles Report for {start_date} → {end_date}")
        
        # ==================== HARDCODED TARGET GUILD ====================
        TARGET_GUILD_ID = 1041450125391835186  # Staff Hub
        TARGET_CHANNEL_ID = 1210834093017661490  # Channel to send report
        SEVEN_DAYS_ROLE_ID = 1043664233361051668  # 7/7 role ID
        TOP_MESSENGER_ROLE_ID = 1043653448022884453  # Top messenger role ID
        
        # ==================== GET TARGET GUILD ====================
        target_guild = bot.get_guild(TARGET_GUILD_ID)
        
        if not target_guild:
            logger.error(f"❌ Target guild {TARGET_GUILD_ID} not found!")
            return
        
        logger.info(f"✅ Target guild: {target_guild.name}")
        
        # ==================== GET CHANNEL AND ROLES ====================
        target_channel = target_guild.get_channel(TARGET_CHANNEL_ID)
        if not target_channel:
            logger.error(f"❌ Target channel {TARGET_CHANNEL_ID} not found!")
            return
        
        seven_days_role = target_guild.get_role(SEVEN_DAYS_ROLE_ID)
        top_messenger_role = target_guild.get_role(TOP_MESSENGER_ROLE_ID)
        
        if not seven_days_role or not top_messenger_role:
            logger.error(f"❌ Roles not found!")
            return
        
        logger.info(f"✅ Found roles and channel")
        
        # ==================== GET SOURCE GUILDS ====================
        auto_config = await get_automation_config_func()
        source_guilds = auto_config.get('source_guilds', [])
        
        if not source_guilds:
            logger.error("❌ No source guilds configured")
            return
        
        logger.info(f"📋 Source guilds: {source_guilds}")
        
        # ==================== STEP 1: REMOVE OLD ROLES ====================
        logger.info(f"🧹 Removing old weekly roles...")
        
        removed_count = 0
        for member in target_guild.members:
            if seven_days_role in member.roles or top_messenger_role in member.roles:
                try:
                    roles_to_remove = []
                    if seven_days_role in member.roles:
                        roles_to_remove.append(seven_days_role)
                    if top_messenger_role in member.roles:
                        roles_to_remove.append(top_messenger_role)
                    
                    await member.remove_roles(*roles_to_remove, reason="Weekly roles reset")
                    removed_count += 1
                    logger.info(f"  ✅ Removed roles from {member.name}")
                except Exception as e:
                    logger.error(f"  ❌ Error removing roles from {member.name}: {e}")
        
        logger.info(f"✅ Removed roles from {removed_count} members")
        
        # ==================== STEP 2: SCAN ALL GUILDS FOR ACTIVITY ====================
        start_datetime = get_start_datetime(start_date)
        end_datetime = get_end_datetime(end_date)
        
        user_message_stats = {}
        
        for guild_id in source_guilds:
            guild = bot.get_guild(guild_id)
            if not guild:
                logger.warning(f"⚠️ Guild {guild_id} not found")
                continue
            
            logger.info(f"🔍 Scanning {guild.name}...")
            
            text_channels = get_readable_text_channels(guild)
            
            for channel in text_channels:
                try:
                    messages = await safe_history_fetch(
                        channel,
                        limit=5000,
                        after=start_datetime,
                        before=end_datetime
                    )
                    
                    for message in messages:
                        if message.author.bot:
                            continue
                        
                        user_id = message.author.id
                        message_date = message.created_at.date()
                        
                        if user_id not in user_message_stats:
                            user_message_stats[user_id] = {
                                'name': message.author.name,
                                'count': 0,
                                'days': set()
                            }
                        
                        user_message_stats[user_id]['count'] += 1
                        user_message_stats[user_id]['days'].add(message_date)
                
                except Exception as e:
                    logger.error(f"  ❌ Error scanning {channel.name}: {e}")
        
        # ==================== STEP 3: FILTER TO STAFF ONLY ====================
        # ✅ FIXED: Only count users who have a staff role in the target guild.
        # Reads general_staff role names from config.json (same source as staff_sheet.py)
        # so the two systems always stay in sync.
        config = load_config()
        general_staff_role_names = config.get('staff_roles_config', {}).get('general_staff', [])
        logger.info(f"\U0001f4cb Staff roles to filter by: {general_staff_role_names}")

        # Build a set of member IDs who have at least one general_staff role
        staff_member_ids = set()
        for role_name in general_staff_role_names:
            role = discord.utils.get(target_guild.roles, name=role_name)
            if role:
                for m in role.members:
                    staff_member_ids.add(m.id)
                logger.info(f"  ✅ Role '{role_name}': {len(role.members)} members")
            else:
                logger.warning(f"  ⚠️ Role '{role_name}' not found in {target_guild.name}")

        if not staff_member_ids:
            logger.warning("⚠️ No staff members found via roles — falling back to guild membership filter")
            staff_member_ids = {uid for uid in user_message_stats if target_guild.get_member(uid) is not None}

        staff_only_stats = {
            uid: stats
            for uid, stats in user_message_stats.items()
            if uid in staff_member_ids
        }
        non_staff_filtered = len(user_message_stats) - len(staff_only_stats)
        logger.info(f"✅ Staff filter: kept {len(staff_only_stats)} staff, removed {non_staff_filtered} non-staff")
        user_message_stats = staff_only_stats

        # ==================== STEP 4: IDENTIFY 7/7 USERS ====================
        seven_days_users = []
        
        for user_id, stats in user_message_stats.items():
            if len(stats['days']) >= 7:
                seven_days_users.append(user_id)
                logger.info(f"  ✅ 7/7: {stats['name']} (active {len(stats['days'])} days)")
        
        logger.info(f"✅ Found {len(seven_days_users)} users active 7/7 days")
        
        # ==================== STEP 5 (FORMERLY 4): FIND TOP MESSENGER ====================
        if not user_message_stats:
            logger.warning("⚠️ No message activity found!")
            return
        
        top_user_id = max(user_message_stats.keys(), key=lambda uid: user_message_stats[uid]['count'])
        top_message_count = user_message_stats[top_user_id]['count']
        top_user_name = user_message_stats[top_user_id]['name']
        
        logger.info(f"🏆 Top messenger: {top_user_name} ({top_message_count} messages)")
        
        # ==================== STEP 5: AWARD 7/7 ROLES ====================
        awarded_count = 0
        
        for user_id in seven_days_users:
            member = target_guild.get_member(user_id)
            
            if not member:
                logger.debug(f"  ⏭️ User {user_id} not in target guild")
                continue
            
            try:
                await member.add_roles(seven_days_role, reason="Active 7/7 days")
                awarded_count += 1
                logger.info(f"  ✅ Awarded 7/7 role to {member.name}")
            except Exception as e:
                logger.error(f"  ❌ Error awarding role to {member.name}: {e}")
        
        logger.info(f"✅ Awarded 7/7 role to {awarded_count} members")
        
        # ==================== STEP 6: AWARD TOP MESSENGER ROLE ====================
        top_member = target_guild.get_member(top_user_id)
        
        if not top_member:
            logger.error(f"❌ Top messenger {top_user_id} not found in target guild")
            return
        
        try:
            await top_member.add_roles(top_messenger_role, reason=f"Top messenger with {top_message_count} messages")
            logger.info(f"✅ Awarded Top Messenger role to {top_member.name}")
        except Exception as e:
            logger.error(f"❌ Error awarding Top Messenger role: {e}")
        
        # ==================== STEP 7: UPDATE STREAKS ====================
        try:
            streak_result = await database.update_top_messenger_streak(top_user_id, start_date, end_date)
            current_streak = streak_result['current_streak']
            logger.info(f"✅ Updated streak for {top_user_name}: {current_streak} weeks (best: {streak_result['best_streak']}, total wins: {streak_result['total_wins']})")
        except Exception as e:
            logger.error(f"❌ Failed to update streak: {e}")
            current_streak = 1
        
        # ==================== STEP 8: SEND CONGRATULATIONS ====================
        # ✅ FIXED: Display 7/7 users with @mentions and use RANDOM MESSAGES from bank
        message_lines = []
        
        if seven_days_users:
            message_lines.append(f"🎉 **{len(seven_days_users)} STAFF MEMBERS WERE ACTIVE ALL 7 DAYS!** 🎉")
            message_lines.append("")
            
            # ✅ FIXED: Use actual role mention <@&ROLE_ID> so it pings/highlights correctly.
            # Plain text "@7/7 active" was never pinging the role.
            for user_id in seven_days_users:
                message_lines.append(f"<@{user_id}> <@&{SEVEN_DAYS_ROLE_ID}>")
            
            message_lines.append("")
        
        # ✅ RANDOM MESSAGE: Select random congratulations message from bank
        congratulations_template = random.choice(CONGRATULATIONS_MESSAGES)
        congratulations_message = congratulations_template.format(
            user=f"<@{top_user_id}>",
            role=TOP_MESSENGER_ROLE_ID,
            count=top_message_count
        )
        message_lines.append(congratulations_message)
        
        # ✅ RANDOM STREAK MESSAGE: If streak > 1, add random streak message from bank
        if current_streak > 1:
            message_lines.append("")
            streak_template = random.choice(STREAK_MESSAGES)
            streak_message = streak_template.format(
                user=f"<@{top_user_id}>",
                role=TOP_MESSENGER_ROLE_ID,
                weeks=current_streak
            )
            message_lines.append(streak_message)
        
        # ==================== STEP 9: SEND MESSAGE ====================
        final_message = "\n".join(message_lines)
        
        # Discord has a 2000 character limit, split if needed
        if len(final_message) > 2000:
            logger.warning(f"⚠️ Message too long, splitting...")
            
            # Send 7/7 section first
            seven_section_end = message_lines.index("") + 1 if "" in message_lines else len(message_lines) - 2
            part1 = "\n".join(message_lines[:seven_section_end])
            part2 = "\n".join(message_lines[seven_section_end:])
            
            if part1:
                await target_channel.send(part1)
            await target_channel.send(part2)
        else:
            await target_channel.send(final_message)
        
        logger.info(f"✅ Weekly roles report sent")
        
        # ==================== STEP 10: MARK AS SENT ====================
        if not is_test:
            try:
                # ✅ FIXED: Always mark against Staff Hub (1041450125391835186) — the same guild
                # that check_report_already_sent queries, so the duplicate check actually works.
                await database.mark_report_sent(
                    1041450125391835186,
                    'weekly_roles',
                    'Full Week',
                    start_date,
                    end_date
                )
                logger.info("✅ Marked as sent in database")
            except Exception as e:
                logger.error(f"❌ Failed to mark as sent: {e}")
        
        logger.info("✅ Weekly roles report completed")
        
    except Exception as e:
        logger.error(f"❌ Weekly roles report failed: {e}")
        logger.error(traceback.format_exc())
        raise

# ==================== EXACT TIMING IMPLEMENTATION ====================

async def run_weekly_roles_at_exact_time(bot):
    """Calculate exact trigger time and wait until then"""
    await bot.wait_until_ready()
    
    # ✅ FIXED: Import database AFTER bot is ready so the module is fully initialised
    import database
    logger.info(f"✅ Weekly roles task active — database available")
    
    while True:
        try:
            start_date, end_date = get_global_dates_from_config()
            
            if not start_date or not end_date:
                logger.warning("⚠️ No dates configured, retrying in 5 minutes")
                await asyncio.sleep(300)
                continue
            
            start_datetime = get_start_datetime(start_date)
            target_time = start_datetime + timedelta(hours=WEEKLY_ROLES_HOURS)
            now = datetime.now(timezone.utc)
            
            logger.info(f"📅 Checking weekly roles for {start_date} → {end_date}")
            logger.info(f"⏰ Target time: {target_time} | Current time: {now}")
            
            already_sent = await database.check_report_already_sent(
                1041450125391835186,
                'weekly_roles',
                'Full Week',
                start_date,
                end_date
            )
            logger.info(f"📊 Database check: already_sent = {already_sent}")
            
            if already_sent:
                logger.info(f"⏭️ Already sent for this week, waiting for new week...")
                next_week_start = start_datetime + timedelta(days=7)
                next_trigger_time = next_week_start + timedelta(hours=WEEKLY_ROLES_HOURS)
                wait_seconds = (next_trigger_time - now).total_seconds()
                
                if wait_seconds <= 0:
                    logger.warning(f"⚠️ Next trigger time already passed, waiting 1 day")
                    await asyncio.sleep(86400)
                else:
                    logger.info(f"⏰ Next trigger: {next_trigger_time} (in {wait_seconds/3600:.1f}h)")
                    await asyncio.sleep(wait_seconds)
                continue
            
            time_diff = (target_time - now).total_seconds()
            logger.info(f"⏱️ Time difference: {time_diff/3600:.1f}h (target - now)")

            if time_diff > 0:
                # Target time hasn't arrived yet — sleep until it does
                logger.info(f"⏰ Scheduled for {target_time} (in {time_diff/3600:.1f}h)")
                await asyncio.sleep(time_diff)

                # After waking, check we didn't sleep way too long (e.g. OS suspend).
                # Either way, still fire — already_sent = False means it genuinely hasn't run.
                now = datetime.now(timezone.utc)
                actual_diff = (now - target_time).total_seconds()
                if actual_diff > 10800:
                    logger.warning(
                        f"⚠️ Woke up {actual_diff/3600:.1f}h after target — "
                        f"bot was likely suspended. Firing catch-up now."
                    )
                    # Fall through to fire — do NOT skip
            else:
                # Target time has already passed and already_sent = False.
                # Bot was offline/restarting when the report was due — fire immediately.
                hours_late = abs(time_diff) / 3600
                logger.warning(
                    f"⚠️ Missed trigger by {hours_late:.1f}h (was due {target_time}) — "
                    f"firing catch-up immediately"
                )
            
            logger.info(f"🏆 ========================")
            logger.info(f"🏆 RUNNING WEEKLY ROLES REPORT")
            logger.info(f"🏆 ========================")
            
            await send_weekly_roles_report(
                bot=bot,
                database=database,
                get_automation_config_func=get_automation_config,
                start_date=start_date,
                end_date=end_date,
                is_test=False
            )
            
            logger.info("=" * 50)
            logger.info("✅ WEEKLY ROLES REPORT COMPLETED SUCCESSFULLY")
            logger.info("=" * 50)
            
            # Wait for next week's trigger time
            next_week_start = start_datetime + timedelta(days=7)
            next_trigger_time = next_week_start + timedelta(hours=WEEKLY_ROLES_HOURS)
            wait_seconds = (next_trigger_time - datetime.now(timezone.utc)).total_seconds()
            
            if wait_seconds <= 0:
                logger.warning(f"⚠️ Next trigger time already passed, waiting 1 day")
                await asyncio.sleep(86400)
            else:
                logger.info(f"⏰ Next trigger: {next_trigger_time} (in {wait_seconds/3600:.1f}h)")
                await asyncio.sleep(wait_seconds)
        
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            logger.error(traceback.format_exc())
            await asyncio.sleep(300)

# ==================== COG SETUP ====================

class WeeklyRolesTask(commands.Cog):
    """Automated weekly roles task"""
    
    def __init__(self, bot):
        self.bot = bot
        self.task = None
        logger.info("✅ Weekly Roles task initialized")
    
    async def cog_load(self):
        """Start background task"""
        logger.info("🚀 Starting Weekly Roles automation...")
        logger.info(f"⏰ Will run at {WEEKLY_ROLES_HOURS}h after week start")
        
        # ✅ FIXED: Don't check DB here — bot.database isn't set yet at cog_load time.
        # The task itself waits for bot.wait_until_ready() before touching the DB.
        self.task = asyncio.create_task(run_weekly_roles_at_exact_time(self.bot))
        logger.info(f"✅ Task created! (will activate when bot is ready)")
    
    def cog_unload(self):
        """Stop background task"""
        if self.task:
            self.task.cancel()
        logger.info("🛑 Task stopped")

async def setup(bot):
    """Setup function"""
    await bot.add_cog(WeeklyRolesTask(bot))