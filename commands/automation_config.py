"""
Automation Configuration Commands
Configure automated reports and tasks
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone, timedelta
from core.helpers import *
from core.cache import config_cache
import logging
import asyncio
import database

# Roles allowed to use all force/admin commands alongside server administrators
FORCE_COMMANDS_ROLE_NAME = "Head Staff Insights"
FORCE_COMMANDS_ROLE_IDS = {1479788596511641694}  # Additional role IDs allowed to use force commands

def admin_or_force_role():
    """Check: server administrator OR holder of the Head Staff Insights role or allowed role IDs."""
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        if any(role.name == FORCE_COMMANDS_ROLE_NAME for role in ctx.author.roles):
            return True
        if any(role.id in FORCE_COMMANDS_ROLE_IDS for role in ctx.author.roles):
            return True
        raise commands.MissingPermissions(['administrator'])
    return commands.check(predicate)

# ✅ FIXED IMPORTS - Now uses unified_weekly_loop
from tasks.unified_weekly_loop import (
    process_single_duty,
    SOURCE_GUILDS,
    REPORT_GUILD_ID,
    MID_WEEK_HOURS,
    FULL_WEEK_HOURS
)

# ✅ HARDCODED: In case the import fails, use hardcoded value
if 'REPORT_GUILD_ID' not in dir():
    REPORT_GUILD_ID = 1041450125391835186  # Staff Hub guild ID

logger = logging.getLogger('discord')

# ==================== HELPER FUNCTIONS ====================

def load_config():
    """Load config.json"""
    import json
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config.json: {e}")
        return {}

def get_global_dates_from_config():
    """Get global dates from config.json in DD/MM/YYYY format"""
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
    
    # ✅ DON'T CONVERT - Keep as DD/MM/YYYY format
    return start_date, end_date

async def get_guild_names(bot):
    """Get guild names for data sources"""
    data_sources = []
    for guild_id in SOURCE_GUILDS:
        guild = bot.get_guild(guild_id)
        if guild:
            data_sources.append(guild.name)
    return data_sources

async def get_automation_config():
    """Get automation config from config.json (async version for weekly_roles)"""
    config = load_config()
    return config.get('automated_checks', {})

class AutomationConfig(commands.Cog):
    """Automation configuration and manual report commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='autoconfig', help='View automation settings and all force commands')
    @admin_or_force_role()
    async def autoconfig(self, ctx):
        """
        Display automation settings and available force report commands
        Usage: >autoconfig
        """
        try:
            # Get current dates from config
            start_date, end_date = get_global_dates_from_config()
            
            embed = discord.Embed(
                title="🤖 AUTOMATED REPORTS (Admin) [GLOBAL]",
                description="Configure automatic weekly activity reports with sequential processing",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            # Current Week Info
            if start_date and end_date:
                embed.add_field(
                    name="📅 Current Week Period",
                    value=f"**Start:** {start_date}\n**End:** {end_date}",
                    inline=False
                )
            
            # Global Config Commands
            embed.add_field(
                name="🌐 Global Configuration",
                value=(
                    "`>globalconfig setenddate <dd/mm/yyyy>` - Set week end date\n"
                    "`>enable <midweek/fullweek/export>` - Toggle automation\n"
                    "`>disable <midweek/fullweek/export>` - Toggle automation"
                ),
                inline=False
            )
            
            # Feature Comparison
            embed.add_field(
                name="ℹ️ Sequential Processing Details",
                value=(
                    "**Processing Order:** Req → Role\n\n"
                    "**Each duty completes fully:**\n"
                    "1️⃣ Scan activity (rate limited)\n"
                    "2️⃣ Send report to channel\n"
                    "3️⃣ Send DM warnings\n"
                    "4️⃣ Award VBucks (Full Week only)\n\n"
                    "✅ No duplicate scanning\n"
                    "✅ Rate limited (0.5s between calls)\n"
                    "⚠️ **ALL force commands BYPASS duplicate checks**"
                ),
                inline=False
            )
            
            embed.set_footer(text=f"Requested by {ctx.author} • Use commands to configure")
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Error in autoconfig command: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"Failed to display automation config: {str(e)}",
                color=discord.Color.red()
            ))
    
    @commands.command(name='enable', help='Enable automation type')
    @admin_or_force_role()
    async def enable(self, ctx, automation_type: str):
        """
        Enable specific automation type
        Usage: >enable <midweek/fullweek/export>
        """
        try:
            automation_type = automation_type.lower()
            valid_types = ['midweek', 'fullweek', 'export']
            
            if automation_type not in valid_types:
                await ctx.send(embed=discord.Embed(
                    title="❌ Invalid Type",
                    description=f"Please use: {', '.join(valid_types)}",
                    color=discord.Color.red()
                ))
                return
            
            guild_config = await config_cache.get_guild_config(ctx.guild.id)
            
            if 'automation' not in guild_config:
                guild_config['automation'] = {}
            
            config_key = f"{automation_type}_enabled"
            guild_config['automation'][config_key] = True
            
            await config_cache.save()
            
            type_names = {
                'midweek': '📊 Mid-Week Reports',
                'fullweek': '📈 Full-Week Reports',
                'export': '📤 Staff Sheet Export'
            }
            
            embed = discord.Embed(
                title="✅ Automation Enabled",
                description=f"{type_names[automation_type]} automation is now enabled",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.set_footer(text=f"Enabled by {ctx.author}")
            await ctx.send(embed=embed)
            
            logger.info(f"{automation_type} automation enabled in {ctx.guild.name} by {ctx.author}")
            
        except Exception as e:
            logger.error(f"Error in enable command: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Enable Error",
                description=f"Failed to enable automation: {str(e)}",
                color=discord.Color.red()
            ))
    
    @commands.command(name='disable', help='Disable automation type')
    @admin_or_force_role()
    async def disable(self, ctx, automation_type: str):
        """
        Disable specific automation type
        Usage: >disable <midweek/fullweek/export>
        """
        try:
            automation_type = automation_type.lower()
            valid_types = ['midweek', 'fullweek', 'export']
            
            if automation_type not in valid_types:
                await ctx.send(embed=discord.Embed(
                    title="❌ Invalid Type",
                    description=f"Please use: {', '.join(valid_types)}",
                    color=discord.Color.red()
                ))
                return
            
            guild_config = await config_cache.get_guild_config(ctx.guild.id)
            
            if 'automation' not in guild_config:
                guild_config['automation'] = {}
            
            config_key = f"{automation_type}_enabled"
            guild_config['automation'][config_key] = False
            
            await config_cache.save()
            
            type_names = {
                'midweek': '📊 Mid-Week Reports',
                'fullweek': '📈 Full-Week Reports',
                'export': '📤 Staff Sheet Export'
            }
            
            embed = discord.Embed(
                title="❌ Automation Disabled",
                description=f"{type_names[automation_type]} automation is now disabled",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.set_footer(text=f"Disabled by {ctx.author}")
            await ctx.send(embed=embed)
            
            logger.info(f"{automation_type} automation disabled in {ctx.guild.name} by {ctx.author}")
            
        except Exception as e:
            logger.error(f"Error in disable command: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Disable Error",
                description=f"Failed to disable automation: {str(e)}",
                color=discord.Color.red()
            ))

    @commands.command(name='runtick')
    @admin_or_force_role()
    async def run_tick(self, ctx):
        """Run the unified weekly loop tick right now instead of waiting for the next hour."""
        await ctx.send("Running weekly loop tick now...")
        try:
            from tasks.unified_weekly_loop import unified_tick
            await unified_tick(self.bot)
            await ctx.send("Tick complete.")
        except Exception as e:
            await ctx.send(f"Tick failed: {e}")
            logger.error(f"runtick failed: {e}", exc_info=True)

    @commands.command(name='setaway', aliases=['addaway'])
    @admin_or_force_role()
    async def set_away(self, ctx, user: discord.Member):
        """Add the Away role to a user (weekly reports only — no loot/surge effect)."""
        STAFFHUB_GUILD_ID = 1041450125391835186
        from core.helpers import AWAY_ROLE_ID
        staffhub = self.bot.get_guild(STAFFHUB_GUILD_ID)
        if not staffhub:
            await ctx.send("Can't find Staff Hub guild.")
            return
        member = staffhub.get_member(user.id)
        role = staffhub.get_role(AWAY_ROLE_ID) if staffhub else None
        if not member or not role:
            await ctx.send("User not in Staff Hub or Away role not found.")
            return
        if role in member.roles:
            await ctx.send(f"{user.mention} already has Away.")
            return
        await member.add_roles(role, reason=f"Away set by {ctx.author}")
        await ctx.send(f"Set {user.mention} as Away. They'll show the 🏖️ tag on weekly reports and skip penalties.")

    @commands.command(name='removeaway', aliases=['unaway'])
    @admin_or_force_role()
    async def remove_away(self, ctx, user: discord.Member):
        """Remove the Away role from a user."""
        STAFFHUB_GUILD_ID = 1041450125391835186
        from core.helpers import AWAY_ROLE_ID
        staffhub = self.bot.get_guild(STAFFHUB_GUILD_ID)
        member = staffhub.get_member(user.id) if staffhub else None
        role = staffhub.get_role(AWAY_ROLE_ID) if staffhub else None
        if not member or not role:
            await ctx.send("User not in Staff Hub or Away role not found.")
            return
        if role not in member.roles:
            await ctx.send(f"{user.mention} doesn't have Away.")
            return
        await member.remove_roles(role, reason=f"Away removed by {ctx.author}")
        await ctx.send(f"Removed Away from {user.mention}.")

    @commands.command(name='setimmunity', aliases=['addimmunity'])
    @admin_or_force_role()
    async def set_immunity(self, ctx, user: discord.Member):
        """Add the Away Immunity role — skips penalties silently, no 🏖️ tag on reports."""
        STAFFHUB_GUILD_ID = 1041450125391835186
        from core.helpers import AWAY_IMMUNITY_ROLE_ID
        staffhub = self.bot.get_guild(STAFFHUB_GUILD_ID)
        member = staffhub.get_member(user.id) if staffhub else None
        role = staffhub.get_role(AWAY_IMMUNITY_ROLE_ID) if staffhub else None
        if not member or not role:
            await ctx.send("User not in Staff Hub or Immunity role not found.")
            return
        if role in member.roles:
            await ctx.send(f"{user.mention} already has Immunity.")
            return
        await member.add_roles(role, reason=f"Away Immunity set by {ctx.author}")
        await ctx.send(f"Set {user.mention} as Away (Immunity). Penalties skipped, no away tag shown.")

    @commands.command(name='removeimmunity', aliases=['unimmunity'])
    @admin_or_force_role()
    async def remove_immunity(self, ctx, user: discord.Member):
        """Remove the Away Immunity role from a user."""
        STAFFHUB_GUILD_ID = 1041450125391835186
        from core.helpers import AWAY_IMMUNITY_ROLE_ID
        staffhub = self.bot.get_guild(STAFFHUB_GUILD_ID)
        member = staffhub.get_member(user.id) if staffhub else None
        role = staffhub.get_role(AWAY_IMMUNITY_ROLE_ID) if staffhub else None
        if not member or not role:
            await ctx.send("User not in Staff Hub or Immunity role not found.")
            return
        if role not in member.roles:
            await ctx.send(f"{user.mention} doesn't have Immunity.")
            return
        await member.remove_roles(role, reason=f"Away Immunity removed by {ctx.author}")
        await ctx.send(f"Removed Immunity from {user.mention}.")


async def setup(bot):
    await bot.add_cog(AutomationConfig(bot))
    logger.info("✅ AutomationConfig cog loaded - ALL FORCE COMMANDS BYPASS DUPLICATE CHECKS")
    @commands.command(name='resetweeklychallenges')
    @admin_or_force_role()
    async def reset_weekly_challenges(self, ctx):
        """
        Reset weekly challenges for the current week.
        Usage: >resetweeklychallenges
        """
        await ctx.send("🔄 **Resetting Weekly Challenges...**")
        
        try:
            start_date, end_date = get_global_dates_from_config()
            if not start_date:
                await ctx.send("❌ No week start date in config!")
                return
            
            pool = await database.get_pool()
            async with pool.acquire() as db:
                await db.execute(
                    'DELETE FROM weekly_challenges WHERE week_start = ?',
                    (start_date,)
                )
                await db.commit()
            
            from tasks.random_challenges import _push_events_payload
            asyncio.ensure_future(_push_events_payload(ctx.bot))
            
            await ctx.send(
                f"✅ **Weekly Challenges Reset!**\n"
                f"**Week:** {start_date}\n\n"
                f"🆕 New challenges will generate on next run\n"
                f"💡 Use `>challengeinfo` to learn more"
            )
            logger.info(f"✅ Challenges reset for {start_date}")
            
        except Exception as e:
            logger.error(f"❌ Reset error: {e}", exc_info=True)
            await ctx.send(f"❌ Failed: {str(e)}")

    @commands.command(name='challengeinfo')
    @admin_or_force_role()
    async def challenge_info(self, ctx):
        """
        Display Wave Staff Bot features & challenge system info.
        Usage: >challengeinfo
        """
        try:
            embed = discord.Embed(
                title="🌊 WAVE STAFF BOT - System Overview",
                description="Automated staff activity tracking & gamification",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            
            embed.add_field(
                name="❓ What is Wave Staff Bot?",
                value=(
                    "A Discord staff management system that:\n"
                    "🎯 Tracks staff activity 24/7\n"
                    "📊 Generates automated weekly reports\n"
                    "🏆 Gamifies completion with weekly challenges\n"
                    "🌐 Publishes live leaderboards\n"
                    "💎 Awards premium currency (Wave Points & V-Bucks)"
                ),
                inline=False
            )
            
            embed.add_field(
                name="⚡ Core Features",
                value=(
                    "**Activity Tracking**\n"
                    "• Monitors: Requests, Messages, Modlog\n"
                    "• Real-time per staff member\n\n"
                    "**Automated Reports**\n"
                    "• Mid-Week (72h): Progress + warnings\n"
                    "• Full Week (168h): Final rankings + rewards\n\n"
                    "**Live Leaderboards**\n"
                    "• Public dashboard (GitHub Pages)\n"
                    "• Real-time ranks with medals\n"
                    "• V-Bucks badges for top 3\n\n"
                    "**Reward Systems**\n"
                    "• Wave Points: Win challenges\n"
                    "• V-Bucks: Top 3 per duty\n"
                    "• Strikes: Penalize low activity"
                ),
                inline=False
            )
            
            embed.add_field(
                name="🎯 Weekly Challenge System",
                value=(
                    "**What are Challenges?**\n"
                    "Gamified tasks staff race to complete\n"
                    "Winners earn **Wave Points** (exclusive)\n\n"
                    "**Schedule:**\n"
                    "📅 Week Start: 5 random challenges\n"
                    "⚡ Mid-Week: 2 difficulty-10 (hardest)\n\n"
                    "**How They Work:**\n"
                    "• Scan every 4 hours\n"
                    "• First to target WINS\n"
                    "• Ties = random winner\n"
                    "• Public announcement + DM"
                ),
                inline=False
            )
            
            embed.add_field(
                name="📈 Challenge Tiers (Doubled)",
                value=(
                    "**Half | Okay | Good | Great**\n"
                    "Req: 16 | 32 | 80 | 200\n"
                    "Msg: 100 | 200 | 400 | 800\n"
                    "Log: 8 | 20 | 40 | 80"
                ),
                inline=False
            )
            
            embed.add_field(
                name="💎 Wave Points",
                value=(
                    "Premium currency for challenge wins\n"
                    "Reward = difficulty × 10 (10–100 WP per win)\n"
                    "Up to 7 challenges per week (5 + 2 mid-week)\n"
                    "Public leaderboard on Events page"
                ),
                inline=False
            )
            
            embed.add_field(
                name="✍️ Challenge Flavour Text",
                value=(
                    "Each challenge gets a random hype line from a template pool:\n\n"
                    "'Race to 400 Messages and claim victory!'\n\n"
                    "• Tone scales with difficulty (chill → epic)\n"
                    "• Shown in Discord + on the Events page"
                ),
                inline=False
            )
            
            embed.set_footer(text="Wave Staff Bot v1.0 | Admin Command")
            await ctx.send(embed=embed)
            logger.info(f"✅ Challenge info displayed")
            
        except Exception as e:
            logger.error(f"❌ Info error: {e}", exc_info=True)
            await ctx.send(f"❌ Failed: {str(e)}")