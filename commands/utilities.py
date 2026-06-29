"""
Utility Commands
Basic bot utility and information commands
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
from core.helpers import *
from core.cache import config_cache
import logging
import traceback
from discord.ui import Button, View, Select
import asyncio

logger = logging.getLogger('discord')


class Utilities(commands.Cog):
    """Basic utility commands for the bot"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ping', help='Check bot latency and response time')
    async def ping(self, ctx):
        """
        Display bot latency
        Usage: >ping
        """
        try:
            latency = round(self.bot.latency * 1000, 2)

            embed = discord.Embed(
                title="🏓 Pong!",
                description=f"Bot latency: **{latency}ms**",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )

            if latency < 100:
                status = "🟢 Excellent"
            elif latency < 200:
                status = "🟡 Good"
            elif latency < 500:
                status = "🟠 Fair"
            else:
                status = "🔴 Poor"

            embed.add_field(name="Connection Status", value=status, inline=False)
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in ping command: {e}")
            await ctx.send(embed=create_error_embed("Ping Error", f"Failed to check latency: {str(e)}"))

    @commands.command(name='uptime', help='Shows how long the bot has been online')
    async def uptime(self, ctx):
        """
        Display bot uptime
        Usage: >uptime
        """
        try:
            now = datetime.now()

            if not hasattr(self.bot, 'launch_time'):
                await ctx.send(embed=create_error_embed("Uptime Error", "Bot launch time not recorded."))
                return

            delta = now - self.bot.launch_time
            total_seconds = int(delta.total_seconds())
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60

            uptime_parts = []
            if days > 0:
                uptime_parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours > 0:
                uptime_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                uptime_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            uptime_parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

            embed = discord.Embed(
                title="⏰ Bot Uptime",
                description=f"**Uptime:** {', '.join(uptime_parts)}",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(
                name="Started At",
                value=self.bot.launch_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                inline=False
            )
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in uptime command: {e}")
            await ctx.send(embed=create_error_embed("Uptime Error", f"Failed to retrieve uptime: {str(e)}"))

    @commands.command(name='invitecount', help='Get the total number of active invites for this server')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff')
    async def invitecount(self, ctx):
        """
        Display total active server invites and a breakdown by creator.
        Usage: >invitecount
        """
        try:
            invites = await ctx.guild.invites()

            total_uses = sum(inv.uses for inv in invites)

            by_creator = {}
            for inv in invites:
                inviter = inv.inviter
                name = inviter.display_name if inviter else "Unknown / Vanity"
                by_creator[name] = by_creator.get(name, 0) + inv.uses

            embed = discord.Embed(
                title=f"📨 Server Invites — {ctx.guild.name}",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Total Active Invite Links", value=str(len(invites)), inline=True)
            embed.add_field(name="Total Uses (All Time)", value=str(total_uses), inline=True)

            if by_creator:
                sorted_creators = sorted(by_creator.items(), key=lambda x: x[1], reverse=True)
                top = "\n".join(
                    f"**{name}:** {uses} use{'s' if uses != 1 else ''}"
                    for name, uses in sorted_creators[:10]
                )
                embed.add_field(name="Top Inviters", value=top or "No data", inline=False)

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)

        except discord.Forbidden:
            await ctx.send(embed=create_error_embed(
                "Missing Permissions",
                "I need the **Manage Guild** permission to view invites."
            ))
        except Exception as e:
            logger.error(f"Error in invitecount command: {e}")
            await ctx.send(embed=create_error_embed("Invite Error", f"Failed to fetch invites: {str(e)}"))

    
    @commands.command(name='dm', help='Send a direct message to a specified user')
    @commands.has_any_role('007', '+', 'Management')
    async def dm(self, ctx, user_id: int, *, message: str):
        """
        Send a DM to any user by ID
        Usage: >dm <user_id> <message>
        Example: >dm 123456789 Hello, this is a staff message.
        """
        logger.info(f"DM command called by {ctx.author} for user {user_id}")
        
        try:
            user = await self.bot.fetch_user(user_id)
            logger.info(f"Fetched user: {user} ({user.id})")
        except discord.NotFound:
            logger.error(f"User {user_id} not found")
            return await ctx.send(embed=create_error_embed(
                "User Not Found",
                f"No user with ID `{user_id}` exists."
            ))
        except Exception as e:
            logger.error(f"Error fetching user: {e}")
            return await ctx.send(embed=create_error_embed("Error", f"Could not fetch user: {e}"))

        try:
            logger.info(f"Attempting to send DM to {user}...")
            await user.send(message)
            logger.info(f"DM sent successfully to {user}")
            
            await ctx.send(embed=discord.Embed(
                title="✅ Success",
                description=f"Message sent to {user.mention} (`{user_id}`)",
                color=discord.Color.green()
            ))
        except discord.Forbidden:
            logger.error(f"Forbidden: User {user} has DMs disabled")
            await ctx.send(embed=discord.Embed(
                title="❌ Error",
                description=f"Failed to send DM to {user.mention} - They may have DMs disabled or blocked the bot.",
                color=discord.Color.red()
            ))
        except Exception as e:
            logger.error(f"Error sending DM: {e}")
            logger.error(traceback.format_exc())
            await ctx.send(embed=create_error_embed("DM Error", f"Failed to send DM: {str(e)}"))

    @commands.command(name='help', help='Show quick command reference for staff')
    @commands.has_any_role('007', '+', 'Management', 'Staff', 'Trial Staff', 'Loot Route Maker', 'Surge Route Maker')
    async def help_staff(self, ctx, command_name: str = None, subcommand_name: str = None):
        """Interactive help menu with dynamic buttons OR specific command help"""

        if command_name:
            cmd = self.bot.get_command(command_name)

            if cmd and isinstance(cmd, commands.Group) and subcommand_name:
                subcmd = cmd.get_command(subcommand_name)
                if subcmd:
                    cmd = subcmd
                else:
                    return await ctx.send(f"❌ Subcommand `{subcommand_name}` not found in `{command_name}`.")

            if cmd:
                embed = discord.Embed(
                    title=f"📖 Help - {cmd.qualified_name}",
                    description=cmd.help or "No description available.",
                    color=discord.Color.blue()
                )

                usage_text = f"`>{cmd.qualified_name}"
                if cmd.usage:
                    usage_text += f" {cmd.usage}"
                usage_text += "`"
                if cmd.help:
                    usage_text += f"\n{cmd.help}"

                embed.add_field(name="📝 Usage", value=usage_text, inline=False)

                if cmd.aliases:
                    embed.add_field(
                        name="🔀 Aliases",
                        value=", ".join([f"`>{alias}`" for alias in cmd.aliases]),
                        inline=False
                    )

                if isinstance(cmd, commands.Group):
                    subcommand_lines = [
                        f"`{subcmd.name}` - {subcmd.help or 'No description'}"
                        for subcmd in cmd.commands
                    ]
                    if subcommand_lines:
                        embed.add_field(
                            name="📋 Subcommands",
                            value="\n".join(subcommand_lines),
                            inline=False
                        )
                        embed.set_footer(text=f"Use >help {cmd.name} <subcommand> for detailed info")

                return await ctx.send(embed=embed)
            else:
                return await ctx.send(f"❌ Command `{command_name}` not found.")

        view = HelpView(ctx)
        embed = view.get_main_embed()
        view.create_buttons_for_view('main')
        await ctx.send(embed=embed, view=view)

    @commands.command(name='adminhelp', aliases=['ah', 'ha'], help='Shows comprehensive admin help')
    @commands.has_any_role('007', '+', 'Management', 'Head Loot Routes', 'Head Surge Routes', 'Head Tips & Tricks')
    async def admin_help_command(self, ctx):
        """Admin help with HelpView navigation. Lands on overview page."""
        view = AdminHelpView(ctx)
        embed = view.get_overview_embed()
        await ctx.send(embed=embed, view=view)

    async def _send_loot_routes_help(self, ctx):
        """Send ONLY the Loot Routes help page — used for Head Loot Routes role"""
        embed = discord.Embed(
            title="📚 Loot Routes System - Command Guide",
            color=discord.Color.blue(),
            description="**🗺️ Loot Routes System - Your Available Commands**"
        )

        embed.add_field(
            name="🗺️ **LOOT ROUTE MAKERS**",
            value="See the **Staff Hub website** for loot route stats & history.",
            inline=False
        )

        embed.add_field(
            name="🗺️ **HEAD LOOT ROUTES**",
            value=(
                "`>showrotationdb` - View DB state\n"
                "• Users, points, routes, sync status\n\n"
                "`>updateleaderboard` - Rebuild rotation/leaderboard\n\n"
                "`>fixlootroutesync` - Check sync issues\n\n"
                "`>cleanlootroutedb` - Auto-fix sync\n"
                "• Remove users in DB without role, resequence\n\n"
                "`>addlootroutemaker @user`\n"
                "• Add to rotation, init points\n"
                "• Add role in 3 guilds, update leaderboard\n\n"
                "`>removelootroutemaker @user` or `<ID>`\n"
                "• Works with mentions OR IDs\n"
                "• Delete data, auto-resequence (no gaps)\n"
                "• Remove roles from 3 guilds\n\n"
                "`>addroute @user [msg]`\n"
                "• Interactive: image + description\n"
                "• Creates assignment, DMs user\n\n"
                "`>cancelroute <id>`\n"
                "• Delete messages, remove from DB\n"
                "• DMs user, optional reassign\n\n"
                "`>lootroutedone <id>`\n"
                "• Awards points by speed:\n"
                "24h: 2.0 | 48h: 1.5 | 4d: 1.0 | 4d+: 0.5\n\n"
                "`>lootrouteaway @user` - Mark away\n\n"
                "`>lootrouteremoveaway @user` - Remove away"
            ),
            inline=False
        )

        embed.set_footer(text="💡 Type >adminhelp <command> for details | Head Loot Routes Access")
        await ctx.send(embed=embed)




class HelpDropdown(discord.ui.Select):
    def __init__(self, current_view: str):
        options = [
            discord.SelectOption(label="📌 Quick Commands", value="main",         description="Back to the main menu",             emoji="📌", default=(current_view == 'main')),
            discord.SelectOption(label="📊 View Stats",     value="stats",        description="Check your activity and performance", emoji="📊", default=(current_view == 'stats')),
            discord.SelectOption(label="🎯 Goals",          value="goals",        description="View and manage your goals",          emoji="🎯", default=(current_view == 'goals')),
            discord.SelectOption(label="💰 Rewards | 🏦 Economy System", value="rewards_economy", description="WP Shop, VBucks Prizes, Central Bank & Bonds", emoji="💰", default=(current_view == 'rewards_economy')),
            discord.SelectOption(label="🌊 Wave Points",    value="wave_points",  description="Wave Points shop and balance",        emoji="🌊", default=(current_view == 'wave_points')),
            discord.SelectOption(label="🗺️ Loot Routes",   value="loot_routes",  description="Loot route rotation & points",        emoji="🗺️", default=(current_view == 'loot_routes')),
            discord.SelectOption(label="⚡ Surge Routes",   value="surge_routes", description="Surge route rotation & points",       emoji="⚡", default=(current_view == 'surge_routes')),
        ]
        super().__init__(placeholder="📂 Navigate to a section...", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: HelpView = self.view
        value = self.values[0]
        view.current_view = value
        view.create_buttons_for_view(value)

        embed_map = {
            'main':            view.get_main_embed,
            'stats':           view.get_stats_embed,
            'goals':           view.get_goals_embed,
            'rewards_economy': view.get_rewards_economy_embed,
            'wave_points':     view.get_wave_points_embed,
            'loot_routes':     view.get_loot_routes_embed,
            'surge_routes':    view.get_surge_routes_embed,
        }
        await interaction.response.edit_message(embed=embed_map[value](), view=view)


class HelpView(View):
    def __init__(self, ctx):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.current_view = 'main'

    def get_main_embed(self):
        embed = discord.Embed(
            title="📚 Staff Activity Bot - Quick Commands",
            description="Essential commands for staff members",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📌 Quick Commands",
            value=(
                "`>help` - Show this menu\n"
                "`>ping` - Check bot status\n"
                "`>uptime` - Bot uptime\n"
                "`>invitecount` - Get total server invites\n"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click buttons below to explore | Use >adminhelp for admin commands")
        return embed

    def get_stats_embed(self):
        embed = discord.Embed(
            title="📊 Your Stats (View Activity)",
            description="Check your personal activity and performance",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="History",
            value=(
                "*See your full activity history on the Profile page on the Staff Hub website*\n\n"
                "**Comparison:**\n"
                "`>compare <user1> <user2>` - Compare two staff members\n"
                "*Add a user ID to check someone else's stats*"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click 📌 Quick Commands to go back")
        return embed

    def get_goals_embed(self):
        embed = discord.Embed(
            title="🎯 Goal Tracking",
            description="Set and track personal activity goals",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Commands",
            value=(
                "`>goal` - View your personal goals and progress\n"
                "`>goal set <duty> <target>` - Set a new goal\n"
                "`>goal remove <duty>` - Remove a specific goal\n"
                "`>goal clear` - Clear all your goals"
            ),
            inline=False
        )
        embed.add_field(
            name="Examples",
            value=(
                "`>goal set role 50` - Set role goal to 50\n"
                "`>goal set role 100` - Set role goal to 100"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click 📌 Quick Commands to go back")
        return embed

    def get_rewards_economy_embed(self):
        embed = discord.Embed(
            title="💰 Rewards | 🏦 Economy System",
            description="Earn Wave Points from duties — spend them in the shop or buy VBucks prizes",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="🌊 How You Earn Wave Points",
            value=(
                "**🏆 Weekly Map Request Placement** — awarded at the end of each full week:\n"
                "• 🥇 **1st place:** +**150 WP**\n"
                "• 🥈 **2nd place:** +**100 WP**\n\n"
                "**📋 Staff Sheet** — hit **Rank 100** → +**30 WP**\n\n"
                "**⚡ Power Hour** — random 5% chance each hour, lasts 1h. Every Power Hour has a **50% chance to go Double (2× points)!**\n"
                "• Every **10 messages** → +1 pt\n"
                "• Every **5 role duties** → +1 pt\n"
                "• Every **1 map request** → +1 pt\n"
                "• Every **2 mod commands** → +1 pt\n\n"
                "Away roles are exempt from all penalties & rewards"
            ),
            inline=False
        )
        embed.add_field(
            name="⚠️ Bad Performance Penalty",
            value=(
                "Get a ❌ **Bad** rank? You lose **40 Wave Points** from your balance.\n"
                "• If balance = 0 → Your duty role is **removed** automatically\n"
                "• Contact staff to regain your role\n"
                "• You'll be notified via DM when this happens"
            ),
            inline=False
        )
        embed.add_field(
            name="🎁 Prizes (Shop)",
            value=(
                "Spend your Wave Points on prizes via the Staff Hub website:\n"
                "**[Open Economy Page](https://wavedropmaps.pages.dev/economy.html)**"
            ),
            inline=False
        )
        embed.add_field(
            name="💸 P2P Payments",
            value=(
                "`>pay <user> <amount>` — Send Wave Points to another user\n"
                " • Subject to 10% Central Bank P2P tax"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click 📌 Quick Commands to go back")
        return embed

    def get_wave_points_embed(self):
        embed = discord.Embed(
            title="🌊 Wave Points",
            description="Earn WP from duties — balances, leaderboard, and shop are on the Staff Hub website",
            color=0x00D9FF
        )
        embed.add_field(
            name="👀 Viewing & 🛒 Spending",
            value=(
                "Wave Points balances, leaderboards, and the prize shop are on the **Staff Hub website**.\n"
                "**[Open the Website](https://wavedropmaps.pages.dev/)**"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 How to Earn",
            value=(
                "🏆 **Weekly Map Request Placement** — end of each full week:\n"
                "　🥇 1st place → **+150 WP** · 🥈 2nd place → **+100 WP**\n\n"
                "📋 **Staff Sheet** — hit **Rank 100** → **+30 WP**\n\n"
                "⚡ **Power Hour** — 5% random chance per hour, lasts 1h. **50% chance to go Double (2× points)**\n"
                "　📨 Every **10 messages** → +1 pt\n"
                "　👤 Every **5 role duties** → +1 pt\n"
                "　🗺️ Every **1 map request** → +1 pt\n"
                "　🛡️ Every **2 mod commands** → +1 pt\n"
                "　*See <#1474715327974609117> for Power Hour announcements*"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click 📌 Quick Commands to go back")
        return embed



    def get_loot_routes_embed(self):
        embed = discord.Embed(
            title="🗺️ Loot Routes",
            description="Build loot routes in rotation and earn **Wave Points (WP)** directly.",
            color=0x57F287
        )
        embed.add_field(
            name="👀 Viewing",
            value="See the **Staff Hub website** for your loot route WP, rank & history.",
            inline=False
        )
        embed.add_field(
            name="🛒 Spending",
            value="Spend WP on prizes in the shop on the **Staff Hub website**",
            inline=False
        )
        embed.add_field(
            name="💡 How It Works",
            value=(
                "A loot map is posted → you're assigned **in rotation** → build it and post your "
                "**fortnite.gg** link in the submission channel → staff run `>lootroutedone`.\n\n"
                "**WP by speed:** ≤12h **10** · ≤24h **8** · ≤48h **4** · ≤3d **2** · ≤4d **0** · >4d **penalty**\n"
                "**Multipliers:** 👑 Head Loot Routes **2×** · 🕵️ Inspector **1.5×** · 🍀 Lucky Map **2×**"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click 📌 Quick Commands to go back")
        return embed

    def get_surge_routes_embed(self):
        embed = discord.Embed(
            title="⚡ Surge Routes",
            description="Build surge routes in rotation and earn **Wave Points (WP)** directly.",
            color=0x00D9FF
        )
        embed.add_field(
            name="🛒 Spending",
            value="Spend WP on prizes in the shop on the **Staff Hub website**",
            inline=False
        )
        embed.add_field(
            name="💡 How It Works",
            value=(
                "A surge map is posted → you're assigned **in rotation** → build it and post your "
                "**fortnite.gg** link in the surge submission channel → staff run `>surgedone`.\n\n"
                "**Points by speed:** ≤12h **5** · ≤24h **4** · ≤48h **2** · ≤3d **1** · ≤4d **0** · >4d **penalty** _(half of loot — a surge route is worth half a loot route)_\n"
                "**Multipliers:** 👑 Head Surge **2×** · 🕵️ Inspector **1.5×** · 🍀 Lucky Map **2×**"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Click 📌 Quick Commands to go back")
        return embed

    def create_buttons_for_view(self, current_view):
        self.clear_items()
        self.add_item(HelpDropdown(current_view))

    async def stats_callback(self, interaction: discord.Interaction):
        self.current_view = 'stats'
        self.create_buttons_for_view('stats')
        await interaction.response.edit_message(embed=self.get_stats_embed(), view=self)

    async def goals_callback(self, interaction: discord.Interaction):
        self.current_view = 'goals'
        self.create_buttons_for_view('goals')
        await interaction.response.edit_message(embed=self.get_goals_embed(), view=self)

    async def rewards_economy_callback(self, interaction: discord.Interaction):
        self.current_view = 'rewards_economy'
        self.create_buttons_for_view('rewards_economy')
        await interaction.response.edit_message(embed=self.get_rewards_economy_embed(), view=self)

    async def wave_points_callback(self, interaction: discord.Interaction):
        self.current_view = 'wave_points'
        self.create_buttons_for_view('wave_points')
        await interaction.response.edit_message(embed=self.get_wave_points_embed(), view=self)

    async def back_callback(self, interaction: discord.Interaction):
        self.current_view = 'main'
        self.create_buttons_for_view('main')
        await interaction.response.edit_message(embed=self.get_main_embed(), view=self)


ADMIN_PAGES = [
    ('overview',       '🏠 Overview',             'All categories at a glance'),
    ('utilities',      '🔧 Utilities',            'Basic bot commands'),
    ('server_config',  '⚙️ Server Config',       'This server settings'),
    ('global_config',  '🌍 Global Config',        'All servers settings'),
    ('automation',     '📊 Reports & Automation', 'Auto reports & force commands'),
    ('staff_stats',    '👥 Staff Stats',          'Activity tracking commands'),
    ('goals',          '🎯 Personal Goals',       'Duty goals & progress tracking'),
    ('wave_points',    '🌊 Wave Points',          'Wave Points & shop'),
    ('central_bank',   '🏦 Central Bank',         'Reserves & interest'),
    ('power_hour',     '⚡ Power Hour',           'Force/cancel Power Hour'),
    ('loot_routes',    '🗺️ Loot Routes',         'Route assignments & rotation'),
    ('surge_routes',   '⚡ Surge Routes',         'Surge rotation, assignments & shop'),
    ('tips_tricks',    '💡 Tips & Tricks',        'T&T helper tasks, shop & commands'),

    ('voting',         '🗳️ Drop Map Voting',     'Community vote system & cycle'),
    ('image_editor',   '🖼️ Image Editor',        'Watermark / render / upscale'),
    ('reply_dm',       '📧 DM Reply System',      'Auto DM replies'),
    ('manual_duties',  '👥 Manual Duties',        'Override duty counts'),
    ('role_sync',      '🎭 Role Sync',            'Multi-guild role wizard'),
    ('maintenance',    '🔧 Maintenance',          'Bot health & diagnostics'),
    ('database',       '💾 Database Tools',       '⚠️ Destructive clear commands'),
    ('statistics',     '📈 Statistics',           'Drop map market research & data'),
]


class AdminHelpDropdown(discord.ui.Select):
    def __init__(self, current_view: str):
        options = [
            discord.SelectOption(
                label=label, value=value, description=desc,
                emoji=label.split(' ')[0],
                default=(current_view == value)
            )
            for value, label, desc in ADMIN_PAGES
        ]
        super().__init__(
            placeholder="📂 Navigate to a command module...",
            min_values=1, max_values=1,
            options=options, row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: AdminHelpView = self.view
        value = self.values[0]
        view.current_view = value
        view.refresh_dropdown()
        embed_method = getattr(view, f'get_{value}_embed')
        await interaction.response.edit_message(embed=embed_method(), view=view)


class AdminHelpView(View):
    def __init__(self, ctx):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.current_view = 'overview'
        self.add_item(AdminHelpDropdown(self.current_view))

    def refresh_dropdown(self):
        self.clear_items()
        self.add_item(AdminHelpDropdown(self.current_view))

    # ───── PAGE 1: Overview ─────
    def get_overview_embed(self):
        embed = discord.Embed(
            title="📚 Admin Help — All Systems",
            description=(
                "Pick a category from the **dropdown below**.\n"
                "Each page lists every command in that area, grouped by role.\n"
                "Type `>adminhelp` for this menu, or `>help <command>` for one command's details."
            ),
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="🔧 Core",
            value=(
                "🔧 **Utilities** — `>ping`, `>uptime`, `>dm`, `>invitecount`, `>landmarks`, `>namedlocations`\n"
                "⚙️ **Server Config** — `>config`, `>setchannel`, `>setstaff`\n"
                "🌍 **Global Config** — `>globalconfig` (week dates)\n"
                "📊 **Reports & Automation** — `>autoconfig`, `>force*`, away immunity"
            ),
            inline=False
        )
        embed.add_field(
            name="📈 Activity & Currencies",
            value=(
                "👥 **Staff Stats** — `>compare`\n"
                "🎯 **Personal Goals** — `>goal`, `>goal set`, `>goal remove`, `>goal clear`\n"
                "🌊 **Wave Points** — `>wpset`, `>pay` · website for balance/shop\n"
                "🏦 **Central Bank** — `>bank`, `>bankinject`, `>bankbroadcast`, `>banksetreserves`\n"
                "⚡ **Power Hour** — `>powerhour`, `>cancelpowerhour`"
            ),
            inline=False
        )
        embed.add_field(
            name="🎯 Reviewing, Routes & Voting",
            value=(
                "🗺️ **Loot Routes** — `>addroute`, `>lootroutedone`, `>cancelroute`, rotation tools\n"
                "⚡ **Surge Routes** — `>addsurgemaker`, `>removesurgemaker`\n"
                "💡 **Tips & Tricks** — `>addtttask`, `>assignttduty`, `>addtipshelper`, tasks pay WP directly\n"
                "🗳️ **Drop Map Voting** — `/addvoting`, `>VotingToggle`, `>VotingClear`, `>VotingPick`, `>EndVoting`, `>VotingReset`, `>VotingRewards`, `>ToggleStickyMessage`"
            ),
            inline=False
        )
        embed.add_field(
            name="🛠️ Operations",
            value=(
                "🖼️ **Image Editor** — `>dmw`, `>lrw`, `>rawdmw`, `>rawlrw` (raw uncropped renders)\n"
                "📧 **DM Reply System** — `>replydm` group (auto-DM config)\n"
                "👥 **Manual Duties** — `>setduty`, `>setdivisor`, `>getduty`, `>dutyinfo`\n"
                "🎭 **Role Sync** — `>dutyrolegive`, `>dutyroleremove`, `>staffrolegive`, `>staffroleremove`\n"
                "🔧 **Maintenance** — `>bothealth`, `>poolstats`, `>vacuum`, `>ratelimitstats`\n"
                "💾 **Database Tools** — `>clear*` commands ⚠️ (destructive)\n"
                "📈 **Statistics** — `>rdropmap`, `>mktdash` (market research) · `>guilddash` (guild stats)"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Use the dropdown below to navigate all sections")
        return embed

    # ───── PAGE 2: Utilities ─────
    def get_utilities_embed(self):
        embed = discord.Embed(
            title="🔧 Utilities — Basic Bot Commands",
            description="Available to all staff.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="🔌 Status & Info",
            value=(
                "`>ping` — Bot latency (color-coded status)\n"
                "`>uptime` — Time since the bot launched\n"
                "`>invitecount` — Total active invites + top 10 inviters"
            ),
            inline=False
        )
        embed.add_field(
            name="📬 Communication (Admin only)",
            value=(
                "`>dm <user_id> <message>` — Send a DM to any user by ID"
            ),
            inline=False
        )
        embed.add_field(
            name="📖 Help Commands",
            value=(
                "`>help` — Interactive staff help menu\n"
                "`>help <command> [subcommand]` — Detailed info on one command\n"
                "`>adminhelp` — This admin help menu\n"
                " aliases: `>ah` / `>ha`"
            ),
            inline=False
        )
        embed.add_field(
            name="🗺️ Fortnite POI Commands",
            value=(
                "`>landmarks` — Current Fortnite landmarks (unnamed POIs)\n"
                "`>namedlocations` — Current Fortnite named locations\n"
                " aliases: `>namedpois` / `>locations`"
            ),
            inline=False
        )
        embed.set_footer(text="💡 All commands shown work for all staff unless noted")
        return embed

    # ───── PAGE 3: Server Config ─────
    def get_server_config_embed(self):
        embed = discord.Embed(
            title="⚙️ Server Config — This Server",
            description="Configure channels and staff role for THIS server only.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="👁️ View Current Config",
            value="`>config` — Show this server's full configuration",
            inline=False
        )
        embed.add_field(
            name="📺 Channel Subcommands",
            value=(
                "`>config setloggingchannel <id>` — Config-change log channel\n"
                "`>config setrequestchannel <id>` — Map request channel\n"
                "`>config setmodlogschannel <id>` — Wick mod logs channel\n"
                "`>config setallowedchannels <id...>` — Allowed-command channels"
            ),
            inline=False
        )
        embed.add_field(
            name="🔧 Legacy Commands (Administrator perm)",
            value=(
                "`>setchannel <type> <#channel>` — Set duty channel\n"
                "　types: `req` / `ping` / `uptime` / `logging`\n"
                "`>setstaff <@role>` — Set the staff role used for tracking"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Required roles: 007 / + / Management")
        return embed

    # ───── PAGE 4: Global Config ─────
    def get_global_config_embed(self):
        embed = discord.Embed(
            title="🌍 Global Config — All Servers",
            description="Settings that affect ALL servers the bot is in.",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="👁️ View Global Settings",
            value=(
                "`>globalconfig` — Show start/end dates + active status\n"
                "　alias: `>globalc`"
            ),
            inline=False
        )
        embed.add_field(
            name="📅 Set Week Dates",
            value=(
                "`>globalconfig setstartdate <date>` — Set only start date\n"
                "`>globalconfig setenddate <date>` — Set only end date\n"
                "`>globalconfig setdates <start> <end>` — Set both at once\n\n"
                "**Accepted formats:** `dd/mm/yyyy`, `d/m/yyyy`, `dd-mm-yyyy`, `2026-03-01`, `01032026`"
            ),
            inline=False
        )
        embed.add_field(
            name="⚠️ Important",
            value=(
                "Changing dates **clears** these tables across ALL servers (5s warning):\n"
                "• `sent_reports` • `user_stats` • `user_goals` • `maintenance_tracking`"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Required roles: 007 / + / Management")
        return embed

    # ───── PAGE 5: Reports & Automation ─────
    def get_automation_embed(self):
        embed = discord.Embed(
            title="📊 Reports & Automation",
            description="Configure auto reports, force them now, manage away immunity.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🤖 Configuration",
            value=(
                "`>autoconfig` — View automation settings + force commands list\n"
                "`>enable <type>` — Enable an automation type\n"
                "`>disable <type>` — Disable an automation type\n"
                "　types: `midweek` / `fullweek` / `export`"
            ),
            inline=False
        )
        embed.add_field(
            name="⏰ Auto Schedule (from week start)",
            value=(
                "• Mid-Week Reports: 72h\n"
                "• Mid-Week Insights: 72h (+30min delay)\n"
                "• Full Week Reports: 168h\n"
                "• Staff Sheet: 168h (+30min delay)\n"
                "• Full Week Insights: 169h\n"
                "• Weekly Roles: 170h\n"
                "• Duty Scans: every 4h (00/04/08/12/16/20 UTC)\n"
                "*If bot misses by >1h, task skips that week entirely.*"
            ),
            inline=False
        )
        embed.add_field(
            name="🎯 Weekly Challenges",
            value=(
                "`>challengeinfo` — View current weekly challenges\n"
                "`>resetweeklychallenges` — Force reset/reroll challenges NOW"
            ),
            inline=False
        )
        embed.add_field(
            name="⚡ Force Tick",
            value=(
                "`>runtick` — Run the unified weekly loop tick immediately (don't wait for next hour)"
            ),
            inline=False
        )
        embed.add_field(
            name="🏖️ Away & Immunity Roles",
            value=(
                "`>setaway <@user>` — Add Away role (weekly reports only, no loot/surge effect)\n"
                "　alias: `>addaway`\n"
                "`>removeaway <@user>` — Remove Away role\n"
                "　alias: `>unaway`\n"
                "`>setimmunity <@user>` — Add Away Immunity — skips penalties silently, no tag on reports\n"
                "　alias: `>addimmunity`\n"
                "`>removeimmunity <@user>` — Remove Away Immunity\n"
                "　alias: `>unimmunity`"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: Administrator OR Head Staff Insights")
        return embed

    # ───── PAGE 6: Staff Stats ─────
    def get_staff_stats_embed(self):
        embed = discord.Embed(
            title="👥 Staff Stats — Activity Tracking",
            description="View any staff member's activity, streaks, and head-to-head comparisons.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📊 Viewing Stats",
            value=(
                "Individual staff member stats have moved to the **Staff Hub website**.\n"
                "Log in at **[wavedropmaps.pages.dev](https://wavedropmaps.pages.dev/)** to see detailed individual stat profiles."
            ),
            inline=False
        )
        embed.add_field(
            name="🔥 Timeline",
            value=(
                "*Full week-by-week history is shown on your Profile page on the Staff Hub website*"
            ),
            inline=False
        )
        embed.add_field(
            name="⚔️ Head-to-Head",
            value=(
                "`>compare <user1_id> <user2_id>` — BATTLE two staff members\n"
                "*Scoring: messages 1pt/70, roles/reqs/modlogs/days 1pt each*\n"
                "*Labels: NECK AND NECK / CLOSE BATTLE / CLEAR VICTOR / TOTAL DOMINATION*"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: 007 / + / Management / Staff / Trial Staff")
        return embed

    # ───── PAGE 7: Personal Goals ─────
    def get_goals_embed(self):
        embed = discord.Embed(
            title="🎯 Personal Goals — Duty Progress Tracking",
            description="Set weekly targets for your own duties and track progress in real time.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="👀 Viewing Progress",
            value=(
                "`>goal` — Show your current goals + live progress bars\n"
                "　• Shows % complete, colour-coded status, and AI-suggested goals for unset duties\n"
                "　• No goals set yet? Shows recommended targets based on your history"
            ),
            inline=False
        )
        embed.add_field(
            name="✏️ Managing Goals",
            value=(
                "`>goal set <duty> <target>` — Set a target for a duty\n"
                "　e.g. `>goal set role 250` · `>goal set req 50`\n"
                "　Max target: 10,000 · Must be a positive number\n\n"
                "`>goal remove <duty>` — Remove one duty's goal\n"
                "　aliases: `>goal delete` / `>goal rm`\n\n"
                "`>goal clear` — Remove ALL your goals at once"
            ),
            inline=False
        )
        embed.add_field(
            name="✅ Valid Duty Types",
            value=(
                "• `role` — Roles given\n"
                "• `req` — Map requests completed\n"
                "• `modlog` — Mod commands used\n"
                "• `message` — Messages sent"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Goals are personal — only you can see/set your own · All staff can use")
        return embed

    # ───── PAGE 8: Wave Points ─────
    def get_wave_points_embed(self):
        embed = discord.Embed(
            title="🌊 Wave Points — Admin Commands",
            description="Most WP features moved to the Staff Hub website. Only admin commands remain in-bot.",
            color=0x00D9FF
        )
        embed.add_field(
            name="🛠️ Admin Commands",
            value=(
                "`>wpset <@user> <amount>` — Set a user's Wave Points to exact value\n"
                "`>pay <@user> <amount>` — Send Wave Points to another user\n"
                " • P2P transfers: 10% Central Bank tax applies"
            ),
            inline=False
        )
        embed.add_field(
            name="🌐 Website Features",
            value=(
                "Balance, leaderboard, shop, and redemption are on the **Staff Hub website**:\n"
                "**[wavedropmaps.pages.dev](https://wavedropmaps.pages.dev/)**"
            ),
            inline=False
        )
        embed.add_field(
            name="💡 Earning",
            value=(
                "🏆 **Weekly Map Request Placement** — 1st → 150 WP · 2nd → 100 WP\n"
                "📋 **Staff Sheet** — Rank 100 → +30 WP\n"
                "⚡ **Power Hour** — 5% chance per hour · 50% chance to go Double (2×)"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Shop prizes and leaderboard on the Staff Hub website")
        return embed

    # ───── PAGE 10: Central Bank ─────
    def get_central_bank_embed(self):
        embed = discord.Embed(
            title="🏦 Central Bank — Reserves & Bonds",
            description="Manage Wave Points + VBucks reserves. Interest and fee system removed.",
            color=discord.Color.dark_teal()
        )
        embed.add_field(
            name="👀 Viewing",
            value=(
                "`>bank` — Current WP + VBucks reserves\n"
                "　aliases: `>centralbank` / `>bankreserves`"
            ),
            inline=False
        )
        embed.add_field(
            name="🛠️ Management",
            value=(
                "`>bankinject <@user> <amount> [points/vbucks]` — Transfer reserves → user\n"
                "　aliases: `>inject` / `>bankgive` — VBucks always go to main wallet\n"
                "`>bankbroadcast <amount> [points/vbucks]` — Split reserves across all users\n"
                "　aliases: `>broadcast` / `>injectall` — requires ✅ confirm"
            ),
            inline=False
        )
        embed.add_field(
            name="🚨 Emergency (Administrator perm only)",
            value=(
                "`>banksetreserves <amount> [points/vbucks]` — Overwrite reserves\n"
                " alias: `>setreserves` — bypasses user deductions, emergency use only"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: Management / 007 / + (admin perm for setreserves)")
        return embed

    # ───── PAGE 11: Power Hour ─────
    def get_power_hour_embed(self):
        embed = discord.Embed(
            title="⚡ Power Hour — Force/Cancel",
            description="Random 5% chance event each hour. Earn extra Wave Points for activity.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="🛠️ Commands",
            value=(
                "`>powerhour` — Force-trigger Power Hour NOW\n"
                "　aliases: `>ph` / `>forcepowerhour`\n"
                "`>cancelpowerhour` — Cancel active Power Hour (no points awarded)\n"
                "　aliases: `>cancelph` / `>phcancel`"
            ),
            inline=False
        )
        embed.add_field(
            name="⏰ How It Works",
            value=(
                "• **Duration:** 1 hour\n"
                "• **Trigger:** 5% random chance at start of every hour\n"
                "• **Announcement:** <#1474715327974609117>\n"
                "• **Points awarded:** at the end automatically"
            ),
            inline=False
        )
        embed.add_field(
            name="🏆 Earning Rates (during Power Hour)",
            value=(
                "• Every **10 messages** → +1 Wave Point\n"
                "• Every **5 roles given** → +1 Wave Point\n"
                "• Every **1 request completed** → +1 Wave Point\n"
                "• Every **2 mod commands** → +1 Wave Point"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: Management / 007 / +")
        return embed

    # ───── PAGE 12: Loot Routes ─────
    def get_loot_routes_embed(self):
        embed = discord.Embed(
            title="🗺️ Loot Routes — Full Command Reference",
            description="Route assignments, rotation, and shop redemptions across 3 guilds.",
            color=discord.Color.teal()
        )
        embed.add_field(
            name="👤 USER COMMANDS (Makers)",
            value=(
                "`>lootroutestats` — All pending + recent history\n"
                "　aliases: `>routestats` / `>stats` / `>assignmentstats`\n"
                "`>lootrouteaway [user] [return_date]` — Mark away (admins can target others)\n"
                "`>lootrouteremoveaway [user]` — Remove away status"
            ),
            inline=False
        )
        embed.add_field(
            name="🎯 HEAD / LOOT ROUTE PERMS (Lifecycle)",
            value=(
                "`>addroute <@user> [msg]` — Interactive: attach image + description\n"
                "`>cancelroute <id>` — Delete messages + optional reassign next person\n"
                "`>lootroutedone <id>` — Mark complete & award points by speed bracket\n"
                "`>addlootroutemaker <@user>` — Add to rotation + role across 3 guilds\n"
                "`>removelootroutemaker <@user/ID>` — Remove + wipe data + resequence"
            ),
            inline=False
        )
        embed.add_field(
            name="🏆 Points by Speed (when `>lootroutedone` runs)",
            value=(
                "• ⚡ ≤12h → **2.5 pts**   • 🏃 ≤24h → **2 pts**   • 🚶 ≤48h → **1 pt**\n"
                "• ≤72h → **0.5 pts**   • ≤96h → **0 pts**   • >96h → **−1 penalty**\n"
                "**Multipliers:** Head Loot Routes 2x · Inspector 1.5x · Lucky Map 2x"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Most cmds: 007 / + / Management / Head Loot Routes / Loot Route Perms")
        return embed

    # ───── PAGE: Surge Routes ─────
    def get_surge_routes_embed(self):
        embed = discord.Embed(
            title="⚡ Surge Routes — Full Command Reference",
            description="Manage the surge route maker roster across 3 guilds.",
            color=0x00D9FF
        )
        embed.add_field(
            name="👥 Roster Management",
            value=(
                "`>addsurgemaker @user` — Add to rotation (3-guild role sync + points init)\n"
                "　alias: `>addsurgeroutemaker`\n"
                "`>removesurgemaker @user|id` — Remove from rotation (archives history, removes role)\n"
                "　alias: `>removesurgeroutemaker`"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: 007 / + / Management / Head Surge Routes")
        return embed

    # ───── PAGE: Tips & Tricks ─────
    def get_tips_tricks_embed(self):
        embed = discord.Embed(
            title="💡 Tips & Tricks — Full Command Reference",
            description="T&T Helpers manage Fortnite strategy content. They earn **Wave Points (WP)** directly by completing tasks.",
            color=0xFF8C1A,
        )
        embed.add_field(
            name="👤 HELPER COMMANDS",
            value=(
                "`>tttasks` — browse all available tasks\n"
                "`>claimtttask <id>` — reserve a task\n"
                "`>completetask <id>` — mark done & earn WP\n"
                "`>unclaim <id>` — drop a claimed task\n"
                "`>mytttasks` — show your currently claimed tasks\n"
                "`>ttleaderboard` — top-10 helpers by T&T points\n"
                "`>tthelp` — helper-facing help embed"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔧 HEAD / ADMIN COMMANDS",
            value=(
                "`>addtipshelper <@user>` — add to roster (3-guild role sync)\n"
                "`>removetipshelper <@user|id>` — remove from roster\n"
                "`>addtttask <description>` — create task (attach images, paste YouTube/Twitter/URLs)\n"
                "`>addsupertask <description>` — create multi-claim super task with N subtasks (Head T&T only)\n"
                "`>removetttask <id>` — delete any task\n"
                "`>forcecompletetask <id> <@user>` — force-complete for a helper\n"
                "`>settttpoints <@user> <pts>` — override a helper's WP total\n"
                "`>assignttduty <CODE> <@user>` — assign a duty slot\n"
                "`>removeduty <CODE>` — unassign a duty slot\n"
                "`>ttduties` — list all duty codes and current assignments"
            ),
            inline=False,
        )
        embed.add_field(
            name="🌊 WP Earn Rates",
            value=(
                "• Base task = **40 WP** · Lucky task (11% chance rolled at creation) = **80 WP** (2× multiplier)\n"
                "• Task unclaimed **7+ days** → base bumps to **80 WP** (Lucky + 7-day = **160 WP**)\n"
                "• WP floor at 0 — no negative balances"
            ),
            inline=False,
        )
        embed.add_field(
            name="📌 Duty Codes",
            value=(
                "`SPAWNS` · `SURGE` · `CREATIVE` · `PRONOTES` · `GAMESTAGES` · "
                "`LOADOUTS` · `MECHANICS` · `DROPSPOTS` · `LOOTPOOLS`"
            ),
            inline=False,
        )
        embed.set_footer(text="💡 Admin cmds: Management / 007 / + / Head Tips & Tricks")
        return embed

    # ───── PAGE 14: Drop Map Voting ─────
    def get_voting_embed(self):
        embed = discord.Embed(
            title="🗳️ Drop Map Voting — Full Command Reference",
            description="Community-driven weekly voting system for drop spot submissions.",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="📋 SYSTEM OVERVIEW",
            value=(
                "**Flow:**\n"
                "1. Members run `/addvoting` to submit a Fortnite drop spot\n"
                "2. Cards live in pinned forum thread with ▲ vote button (live count)\n"
                "3. Rules: 1 submission/member at a time, 2 votes/member max\n"
                "4. Every Sunday at 00:00 UTC the top-voted spot wins:\n"
                "　　• Image + voters posted to queue channel as Paid Priority\n"
                "　　• Winner announced in leaderboard thread\n"
                "　　• All cards deleted, DB wiped — fresh week starts"
            ),
            inline=False
        )
        embed.add_field(
            name="👥 MEMBER COMMANDS",
            value=(
                "`/addvoting` — Submit a drop spot for voting\n"
                "　Opens modal: spot name + description\n"
                "　Then DM image (PNG/JPG/GIF/WEBP, max 8MB) or skip\n"
                "　5 min timeout for image submission\n\n"
                "**Voting:** Click ▲ button on cards (2 votes/week max)"
            ),
            inline=False
        )
        embed.add_field(
            name="🛠️ ADMIN COMMANDS",
            value=(
                "`>VotingToggle on|off|status` — Enable/disable /addvoting\n"
                "　ON by default — turn off to block submissions in this server\n\n"
                "`>VotingClear <@user>` — Remove member's submission + card\n"
                "　Deletes from forum + database\n\n"
                "`>VotingPick <spot>` — Manually pick winner (run cycle NOW)\n"
                "　Specify spot by exact name shown on card\n"
                "　Posts to queue + announces + resets leaderboard\n\n"
                "`>EndVoting` — End voting cycle early (before Sunday)\n"
                "　Useful to end voting on Friday or any day\n"
                "　Runs full cycle: picks winner → posts → resets\n\n"
                "`>VotingReset` — **Silent** clean reset (no announcements)\n"
                "　Wipes DB + deletes all cards\n"
                "　No winner, no auto-submission, no DMs\n\n"
                "`>VotingRewards on|off|status` — Toggle role rewards\n"
                "　Disabled by default (OFF)\n"
                "　Awards 🗳️ Weekly Voter role to voters each week\n\n"
                "`>ToggleStickyMessage on|off|status` — Toggle sticky info\n"
                "　ON by default (info kept visible in queue channel)\n"
                "　Turn off to stop posting/updating sticky message\n\n"
                "`>VotingConfig` — Show current config + stats"
            ),
            inline=False
        )
        embed.add_field(
            name="⚙️ CONFIG DETAILS",
            value=(
                "**Channels:**\n"
                "• Forum: Drop Map Voting forum\n"
                "• Leaderboard: Pinned thread inside forum (holds cards + announcements)\n"
                "• Queue: Wave Logistics bot queue (where winners posted)\n\n"
                "**Limits:**\n"
                "• 1 submission per member at a time\n"
                "• 2 votes per member max\n"
                "• 75% fuzzy match threshold (prevents duplicate submissions)\n"
                "• 5 min DM timeout for image (default)\n"
                "• Max image size: 8 MB"
            ),
            inline=False
        )
        embed.add_field(
            name="🔄 WEEKLY CYCLE",
            value=(
                "**Automatic:** Every Sunday at 00:00 UTC\n"
                "• Top-voted spot (with 1+ votes) wins\n"
                "• 0-vote weeks are skipped (no cycle runs)\n"
                "• On bot startup: cycle catches up if any Sundays passed\n"
                "• Scheduler checks every 10 minutes\n\n"
                "**What the cycle does:**\n"
                "1. Post winner to queue channel with Paid Priority role\n"
                "2. Announce winner in leaderboard thread with voter list\n"
                "3. Delete all cards from forum\n"
                "4. Wipe database (fresh week)\n"
                "5. Log: winner name, vote count, voter count"
            ),
            inline=False
        )
        embed.add_field(
            name="💾 DATABASE TABLES",
            value=(
                "`drop_map_voting_spots` — Submissions (id, name, description, image_path, submitter)\n"
                "`drop_map_voting_votes` — Vote records (user_id, spot_id, timestamp)\n"
                "`drop_map_voting_cycle` — Cycle tracking (last_cycle_end, cycles_completed)"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Staff: /addvoting only | Admin: all commands")
        return embed

    # ───── PAGE 15: Image Editor ─────
    def get_image_editor_embed(self):
        embed = discord.Embed(
            title="🖼️ Image Editor — Watermark Commands",
            description="Pass a fortnite.gg URL — bot renders the map and watermarks it.",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="🗺️ Drop Map Watermark",
            value=(
                "`>dropmapwatermark <fortnite.gg link>` — Render fn.gg map → detect grid coords\n"
                "　→ watermark tile + center logo + bottom-left wave logo\n"
                "　alias: `>dmw`"
            ),
            inline=False
        )
        embed.add_field(
            name="📍 Loot Route Watermark",
            value=(
                "`>lootroutewatermark <fortnite.gg link>` — Render fn.gg route → DOM object detection\n"
                " → watermark tile + small wave logo at chosen coordinates\n"
                " alias: `>lrw`"
            ),
            inline=False
        )
        embed.add_field(
            name="📸 Raw Renders (Uncropped)",
            value=(
                "`>rawdropmapwatermark <fortnite.gg link>` — Full uncropped screenshot (same as >dmw)\n"
                " alias: `>rawdmw`\n"
                "`>rawlootroutewatermark <fortnite.gg link>` — Full uncropped screenshot (same as >lrw)\n"
                " alias: `>rawlrw`"
            ),
            inline=False
        )
        embed.set_footer(text="💡 No role restriction — open to all who can run commands")
        return embed

    # ───── PAGE 16: DM Reply System ─────
    def get_reply_dm_embed(self):
        embed = discord.Embed(
            title="📧 DM Reply System",
            description="Auto-DM users when staff reply to them in a monitored channel.",
            color=discord.Color.light_gray()
        )
        embed.add_field(
            name="🔧 Configuration",
            value=(
                "`>replydm setchannel <channel>` — Channel to monitor for staff replies\n"
                "`>replydm setrole <role...>` — Roles whose replies trigger a DM (multiple OK)\n"
                "`>replydm setlogchannel <channel>` — Where DM success/failure logs appear\n"
                "`>replydm toggleautodelete` — Toggle auto-delete on/off"
            ),
            inline=False
        )
        embed.add_field(
            name="👀 Viewing",
            value=(
                "`>replydm config` — Full configuration view\n"
                "`>replydm status` — Live queue depth + active delete timers"
            ),
            inline=False
        )
        embed.add_field(
            name="🗑️ Auto-Delete Behavior (when enabled)",
            value=(
                "• Replied member message + staff reply deleted **5 min** after DM\n"
                "• User's earlier messages in channel also deleted\n"
                "• Unreplied member messages deleted after **12 hours**\n"
                "• **Pinned messages are NEVER deleted**"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: 007 / + / Management")
        return embed

    # ───── PAGE 17: Manual Duties ─────
    def get_manual_duties_embed(self):
        embed = discord.Embed(
            title="👥 Manual Duties — Override Counts",
            description="Hard-set or divisor-adjust users' duty counts. Auto-pushes to GitHub.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="🔧 Commands",
            value=(
                "`>setduty <user> <duty> <value>` — Hard-set count (push to GitHub)\n"
                "`>setdivisor <user> <duty> <divisor>` — Apply penalty divisor (2-10)\n"
                "　count = raw_count ÷ divisor (persists across scans)\n"
                "`>removeoverride <user> <duty>` — Remove manual override\n"
                "`>removedivisor <user> <duty>` — Remove divisor, restore raw count\n"
                "`>getduty <user>` — Show all 4 duty counts + active divisors/overrides\n"
                "`>dutyinfo` — Static usage examples"
            ),
            inline=False
        )
        embed.add_field(
            name="✅ Valid Duty Types",
            value=(
                "• `req` — Map requests\n"
                "• `role` — Roles given\n"
                "• `modlog` — Mod commands\n"
                "• `message` — Messages sent"
            ),
            inline=False
        )
        embed.add_field(
            name="📝 Examples",
            value=(
                "`>setduty @kieren role 250` — Set kieren's role count to 250\n"
                "`>removeoverride @kieren role` — Restore kieren's real role count\n"
                "`>setdivisor @kieren message 3` — Penalize: message count ÷ 3\n"
                "`>removedivisor @kieren message` — Restore raw message count"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: Management / 007 / +")
        return embed

    # ───── PAGE 18: Role Sync ─────
    def get_role_sync_embed(self):
        embed = discord.Embed(
            title="🎭 Role Sync — Multi-Guild Role Wizard",
            description=(
                "Interactive wizard commands to **add or remove a role across all 3 servers** "
                "in one go. Each command opens a 3-step wizard:\n"
                "**Step 1:** send **one or more** user IDs (space/comma/newline separated, max 25)  →  "
                "**Step 2:** type role name  →  "
                "**Step 3:** click Submit / Cancel.\n\n"
                "Wizards auto-cancel after 60s of inactivity or 3 invalid attempts. "
                "Type `cancel` at any text prompt to abort. Multi-user runs show live progress."
            ),
            color=discord.Color.purple()
        )

        embed.add_field(
            name="🟦 Duty Role Commands",
            value=(
                "`>dutyrolegive` — Give a duty role across all 3 servers\n"
                "`>dutyroleremove` — Remove a duty role across all 3 servers\n"
                "**Allowlist:** Drop Map Tester · Drop Map Maker · "
                "Promoters · Loot Route Maker · Tips & Tricks Helper · Surge Route Maker · "
                "Map Request Helper\n"
                "**Permission:** Administrator perm **OR** has the `Head Admin` role\n"
                "**⏱️ Rate limit:** Head Admin role holders get **1 use per command per 24h** "
                "(give + remove are separate buckets). Admins are unrestricted. Cooldown is only "
                "consumed on full success across all users + guilds **AND** when at least one "
                "actual role change happened — so a no-op run (everyone already had the role) "
                "doesn't burn your daily slot. Persists across bot restarts."
            ),
            inline=False
        )

        embed.add_field(
            name="🟥 Staff Role Commands",
            value=(
                "`>staffrolegive` — Give a staff role across all 3 servers\n"
                "`>staffroleremove` — Remove a staff role across all 3 servers\n"
                "**Allowlist:** Management · Head Admin · Senior Admin · Admin · "
                "Senior Support · Support · Staff · Trial Staff\n"
                "**Permission:** Administrator perm only"
            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ Specialty Roles (Full Sync)",
            value=(
                "Some duty roles trigger **extra database/leaderboard setup** automatically:\n"
                "• **Loot Route Maker** → wizard triggers `>addlootroutemaker` / "
                "`>removelootroutemaker` for full rotation + points + leaderboard handling\n"
                "• **Surge Route Maker** → wizard triggers `>addsurgeroutemaker` / "
                "`>removesurgeroutemaker`\n"
                "All other roles are plain Discord role add/remove."
            ),
            inline=False
        )

        embed.add_field(
            name="🛡️ Security Model",
            value=(
                "• Allowlists are enforced per command — `>dutyrolegive` literally **cannot** "
                "grant Management/Head Admin/Admin, and `>staffrolegive` cannot grant Loot Route "
                "Maker etc.\n"
                "• Refuses `@everyone`, managed roles (boosters/bots), and any role at or above "
                "the bot's top role.\n"
                "• Wizard is locked to the staff member who started it — other users get "
                "blocked from buttons and follow-up messages.\n"
                "• Every role change is logged in each server's Discord audit log with "
                "`reason='by <executor> via <command> wizard'`."
            ),
            inline=False
        )

        embed.add_field(
            name="📊 Results Format",
            value=(
                "When the wizard finishes, the bot posts **two messages**:\n"
                "**1. Wizard message** edits to a small green `✅ Sync Complete — full results below ↓` "
                "indicator so the wizard clearly shows it finished.\n"
                "**2. Fresh results message** appears right below with the full breakdown:\n"
                "  • **Summary** — `✅ X succeeded · ⚠️ Y partial · ❌ Z failed`\n"
                "  • **👤 Per-User** — full per-server lines for ≤6 users; compact "
                "`✅ @user` one-liners for 7-25 users\n"
                "  • **🌐 Per-Guild breakdown** (one section per server) — `✅ Added`, "
                "`ℹ️ Already had role`, `⚠️ Not in this server` (with @mentions so you know "
                "who to invite), `⚠️ Role missing`, `❌ Errors`. Lets you spot at a glance "
                "things like *'5 of 13 users aren't in Server C'*.\n\n"
                "Specialty roles (Loot Route Maker / Surge Route Maker) skip the per-guild "
                "section — their per-user fields show leaderboard outcomes from the "
                "delegated commands instead."
            ),
            inline=False
        )

        embed.add_field(
            name="📝 Examples",
            value=(
                "**Single user:**\n"
                "1. `>dutyrolegive`  →  reply `123456789012345678`  →  reply `Loot Route Maker`  →  Submit\n"
                "2. Bot triggers `>addlootroutemaker` and posts results.\n\n"
                "**Multi-user (up to 25):**\n"
                "1. `>dutyrolegive`  →  reply `111 222 333` (or `111, 222, 333`)\n"
                "2. Reply `Promoters`  →  Submit\n"
                "3. Bot loops users with live `Processing 2/3...` progress, then "
                "shows per-user + per-guild results.\n\n"
                "**Strict validation:** if ANY user ID in your list isn't valid (not numeric, or "
                "not a member of any of the 3 guilds), the wizard rejects the **whole list** and "
                "re-prompts — no partial role changes happen."
            ),
            inline=False
        )

        embed.set_footer(text="💡 Permission: Administrator perm (Discord permission, NOT the staff 'Admin' role)")
        return embed

    # ───── PAGE 19: Maintenance ─────
    def get_maintenance_embed(self):
        embed = discord.Embed(
            title="🔧 Maintenance — Health & Diagnostics",
            description="Bot health, DB pool, cache, memory, scheduled-task status.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="⭐ All-in-One Health",
            value=(
                "`>bothealth` — Full dashboard: uptime, latency, DB pool, cache, memory, schedules\n"
                "　aliases: `>health` / `>status`"
            ),
            inline=False
        )
        embed.add_field(
            name="📊 Specific Diagnostics",
            value=(
                "`>poolstats` — DB connection pool usage (color-coded health)\n"
                "`>testdb` — Test DB connection round-trip latency\n"
                "`>cachestats` — Query cache hit rate + Discord cache + memory\n"
                "`>ratelimitstats` — Rate limit tracker stats\n"
                "　aliases: `>rlstats` / `>rls`"
            ),
            inline=False
        )
        embed.add_field(
            name="🛠️ Database Optimization",
            value=(
                "`>vacuum` — VACUUM + PRAGMA optimize (reclaim space, update stats)\n"
                "*Recommended weekly*"
            ),
            inline=False
        )
        embed.set_footer(text="💡 Roles: Management / 007 / +")
        return embed

    # ───── PAGE 19: Database Tools ─────
    def get_database_embed(self):
        embed = discord.Embed(
            title="💾 Database Tools",
            description=(
                "Generic commands that work on **any** table in the database automatically.\n"
                "No per-table commands needed — just pass the table name.\n"
                "Run `>dbinfo` to see every table name and row count."
            ),
            color=discord.Color.red()
        )
        embed.add_field(
            name="👀 Viewing",
            value=(
                "`>dbinfo` — Row counts for every table in the DB (dynamic)\n"
                "`>dbtable <name>` — Paginated ◀ ▶ viewer for any table\n"
                "　e.g. `>dbtable wave_points`, `>dbtable vbucks`, `>dbtable loot_routes`\n"
                "`>clearcache` — Clear RAM config cache + reload from disk"
            ),
            inline=False
        )
        embed.add_field(
            name="🗑️ Clearing Tables",
            value=(
                "`>dbclear <name>` — DELETE all rows from any table (✅ confirm)\n"
                "　e.g. `>dbclear user_stats`, `>dbclear wave_points`, `>dbclear vbucks`\n\n"
                "**Special behaviour:**\n"
                "• `central_bank` / `rotation_state` → **reset to defaults** (not deleted — "
                "bot requires these rows to exist)\n"
                "• `predictions` → automatically clears `prediction_votes` first (FK)"
            ),
            inline=False
        )
        embed.add_field(
            name="☢️ NUCLEAR OPTION",
            value=(
                "`>cleardatabase` — **Wipe entire database** (2-step ✅ confirm)\n"
                "Clears every table; singletons reset to defaults."
            ),
            inline=False
        )
        embed.set_footer(text="💡 ALL: 007 / + / Management • Use ONLY when absolutely necessary")
        return embed

    # ───── PAGE 24: Statistics ─────
    def get_statistics_embed(self):
        embed = discord.Embed(
            title="📈 Statistics — Market Research & Guild Stats",
            description="Track competitor server growth AND your own guild member counts over time.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="🏠 Guild Stats Dashboard (Management only)",
            value=(
                "`>guilddash` — Snapshot member count, online count, boosts, channels & roles\n"
                "　for Wave's own servers. Instant (uses Discord API directly).\n"
                "　Posts a summary embed + uploads the full HTML report as a file.\n"
                "　Data: `command-trackers/guild-stats/data/data.db` · Reports: `command-trackers/guild-stats/data/reports/`"
            ),
            inline=False
        )
        embed.add_field(
            name="📊 Drop Map Market Research (Management only)",
            value=(
                "`>rdropmap` — Scrape Discord Discovery for all tracked drop-map servers,\n"
                " save a snapshot, and generate a full HTML report with charts.\n"
                " Takes ~2–3 minutes. Posts results directly in Discord.\n"
                "`>mktdash` — Collect a fresh market snapshot and post the dashboard report.\n"
                "`>marketoverview` — Cross-market executive overview across all trackers\n"
                "　aliases: `>mktoverview` / `>marketexec`"
            ),
            inline=False
        )
        embed.add_field(
            name="🔍 What's Tracked",
            value=(
                "Wave Free Dropmaps · DROPMAPS EHLAN · Royal Drop Maps · Free Dropmaps\n"
                "Nova Free Dropmaps & Tips · Titan Free Dropmaps & Tips · NA Drops\n"
                "DROP MAZTER · dropmap.net · SenanF Improvement Server"
            ),
            inline=False
        )
        embed.add_field(
            name="📁 Data & Sync",
            value=(
                "Database: `command-trackers/drop-map-research/data/data.db` — tracked in git.\n"
                "After each run, commit & push so all machines stay in sync.\n"
                "Reports: `command-trackers/drop-map-research/data/reports/`"
            ),
            inline=False
        )
        embed.add_field(
            name="🖥️ Manual Scripts (any machine)",
            value=(
                "`python command-trackers/drop-map-research/scripts/collect.py` — collect + report\n"
                "`python command-trackers/drop-map-research/scripts/generate_report.py` — report only\n"
                "`python command-trackers/drop-map-research/scripts/manage_servers.py list` — tracked servers"
            ),
            inline=False
        )
        embed.set_footer(text="One-time setup: pip install playwright && python -m playwright install chromium")
        return embed


async def setup(bot):
    await bot.add_cog(Utilities(bot))