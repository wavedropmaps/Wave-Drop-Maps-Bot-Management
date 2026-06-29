"""
commands/tipsandtricks.py — Tips & Tricks Helper System commands.

Admin (Head T&T) commands:
  >addsupertask "Parent" | "Sub1" | "Sub2" ...   create a multi-claim super task

Helper commands:
  >tttasks                           list available tasks
  >claimtttask <id>                  claim a task
  >unclaim <id>                      unclaim your claimed task
  >completetask <id>                 mark your claimed task as completed (earns points)
  >mytttasks                         show your currently claimed tasks
  >ttleaderboard                     top-10 helpers by points
  >tthelp                            help embed
"""

import discord
from discord.ext import commands
import logging

import core.tipsandtricks_config as cfg
import database_tipsandtricks as db_tt
from core.global_logger import log_event as _wave_log_event

logger = logging.getLogger('discord')


# ── Permission helpers ──────────────────────────────────────────────────────

def _is_head_tt(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    if ctx.author.guild_permissions.administrator:
        return True
    admin_names_lower = {r.lower() for r in cfg.TT_ADMIN_ROLES}
    return any(role.name.lower() in admin_names_lower for role in ctx.author.roles)


def _is_tt_helper(ctx: commands.Context) -> bool:
    if not ctx.guild:
        return False
    if _is_head_tt(ctx):
        return True
    return any(role.name.lower() == cfg.TT_HELPER_ROLE_NAME.lower() for role in ctx.author.roles)


# ── Shop select view ────────────────────────────────────────────────────────

# ── Embed helpers ───────────────────────────────────────────────────────────

def _task_line(task: dict) -> str:
    badges = []
    if task['is_lucky']:
        badges.append("⚡ LUCKY")
    if task['bonus_applied']:
        badges.append("🔥 BONUS")
    badge_str = f"  `{'  '.join(badges)}`" if badges else ""
    pts = task['base_points']
    mult = f" ×{cfg.LUCKY_TASK_MULTIPLIER:.0f}" if task['is_lucky'] else ""
    return f"**#{task['task_id']}** · {pts}pt{mult}{badge_str}\n{task['description']}"


async def _super_task_line(task: dict) -> str:
    """Format a super task with progress indicator."""
    if not task['parent_task_id']:
        return _task_line(task)  # Not a super task

    # This is a super task parent — show progress
    progress = await db_tt.get_super_task_progress(task['task_id'])
    if not progress:
        return _task_line(task)

    completed = progress['completed']
    total = progress['total']
    bonus = progress['completion_bonus']
    pct = (completed / total * 100) if total > 0 else 0
    bar = "█" * completed + "░" * (total - completed)

    return (f"**#{task['task_id']}** 🎯 SUPER TASK ({completed}/{total} done)\n"
            f">>> {task['description']}\n"
            f"📊 `[{bar}]` {pct:.0f}% | 🏆 +{bonus} WP bonus (split when done)")


# ── Cog ─────────────────────────────────────────────────────────────────────

def _find_role_by_name(guild: discord.Guild, name: str) -> discord.Role | None:
    name_lower = name.lower()
    return next((r for r in guild.roles if r.name.lower() == name_lower), None)


class TipsAndTricksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Role sync helpers ───────────────────────────────────────────────────

    async def _tt_role_in_guilds(self, user_id: int, add: bool, role_name: str) -> dict:
        """Add/remove a role by NAME across all 3 guilds. Returns per-guild status dict."""
        results = {}
        for gid in cfg.GUILD_IDS:
            guild = self.bot.get_guild(gid)
            if not guild:
                results[gid] = "⚠️ Bot not in guild"
                continue
            member = guild.get_member(user_id)
            if not member:
                results[gid] = "⚠️ User not in guild"
                continue
            role = _find_role_by_name(guild, role_name)
            if not role:
                results[gid] = f"⚠️ Role '{role_name}' not found"
                continue
            has = role in member.roles
            try:
                if add and not has:
                    await member.add_roles(role)
                    results[gid] = "✅ Added role"
                elif add and has:
                    results[gid] = "ℹ️ Already has role"
                elif not add and has:
                    await member.remove_roles(role)
                    results[gid] = "✅ Removed role"
                else:
                    results[gid] = "ℹ️ Doesn't have role"
            except Exception as e:
                results[gid] = f"❌ Error: {e}"
        return results

    def _tt_role_status_field(self, role_results: dict) -> str:
        out = ""
        for gid, res in role_results.items():
            g = self.bot.get_guild(gid)
            out += f"**{g.name if g else f'Guild {gid}'}:** {res}\n"
        return out[:1024]

    # ── HEAD T&T COMMANDS ───────────────────────────────────────────────────

    @commands.command(name='addsupertask')
    async def add_super_task(self, ctx, *, description: str = ''):
        """
        Create a multi-claim super task with N subtasks.
        Format: >addsupertask "Parent Title" | "Subtask 1" | "Subtask 2" | "Subtask 3" | ...
        Each subtask can be claimed/completed by different helpers.
        Completion bonus is split equally when all subtasks are done.
        """
        if not _is_head_tt(ctx):
            return await ctx.send("❌ You need the **Head Tips & Tricks** role to create tasks.")
        if not description or '|' not in description:
            return await ctx.send(
                "❌ Format: `>addsupertask \"Parent Title\" | \"Subtask 1\" | \"Subtask 2\" | ...`"
            )

        parts = [p.strip().strip('"\'') for p in description.split('|')]
        parent_desc = parts[0]
        subtask_descs = parts[1:]

        if len(subtask_descs) < 2:
            return await ctx.send("❌ Provide at least 2 subtasks (separate with `|`).")
        if len(subtask_descs) > 20:
            return await ctx.send("❌ Max 20 subtasks per super task.")

        # Collect attachments (same as regular tasks)
        attachments = []
        for att in ctx.message.attachments:
            if att.content_type and att.content_type.startswith('image/'):
                attachments.append({'type': 'image', 'url': att.url, 'label': att.filename})
            else:
                attachments.append({'type': 'file', 'url': att.url, 'label': att.filename})

        result = await db_tt.create_super_task(parent_desc, subtask_descs, ctx.author.id, attachments)
        parent_id = result['parent_task_id']
        subtask_ids = result['subtask_ids']
        completion_bonus = result['completion_bonus']

        embed = discord.Embed(color=discord.Color.from_rgb(255, 215, 0))
        embed.title = "🎯 Super Task Created"
        embed.description = f">>> **{parent_desc}**"
        embed.add_field(
            name="📊 Subtasks",
            value="\n".join(f"**#{sid}** · {desc}" for sid, desc in zip(subtask_ids, subtask_descs)),
            inline=False
        )
        embed.add_field(
            name="💰 Rewards Per Subtask",
            value=f"{cfg.BASE_TASK_POINTS} WP (base)\nUp to 2× if lucky ⚡",
            inline=True
        )
        embed.add_field(
            name="🏆 Completion Bonus",
            value=f"{completion_bonus} WP total (split equally when all {len(subtask_ids)} done)",
            inline=True
        )
        embed.add_field(
            name="📢 How it works",
            value=(
                "Helpers claim individual subtasks (`>claimtttask #ID`)\n"
                "Each completes their own work (`>completetask #ID`)\n"
                "When all subtasks done → everyone gets bonus split!"
            ),
            inline=False
        )
        embed.set_footer(text="✓ Super task ready")
        await ctx.send(embed=embed)

        await _wave_log_event(
            category=cfg.WAVE_LOG_CATEGORY, action="super_task_created",
            actor=ctx.author, guild=ctx.guild,
            details={
                "parent_id": parent_id, "subtask_ids": subtask_ids,
                "parent_desc": parent_desc, "completion_bonus": completion_bonus
            },
        )

        if cfg.TT_LOG_CHANNEL_ID:
            log_ch = ctx.guild.get_channel(cfg.TT_LOG_CHANNEL_ID)
            if log_ch:
                await log_ch.send(
                    f"🎯 **Super task #{parent_id}** created by {ctx.author.mention}\n"
                    f"**{parent_desc}** ({len(subtask_ids)} subtasks, {completion_bonus} WP bonus)"
                )

    # ── ROLE GIVE / REMOVE (3-guild sync, mirrors >addlootmaker pattern) ───

    @commands.command(name='addtipshelper', aliases=['addtipsandtrickshelper'])
    @commands.has_any_role(*cfg.TT_ADMIN_ROLES)
    async def add_tips_helper(self, ctx: commands.Context, user: discord.Member):
        """Add Tips and Tricks Helper role in all 3 guilds + announce. Usage: >addtipshelper @user"""
        if ctx.guild.id != cfg.GUILD_ID:
            return await ctx.send("❌ This command only works in the main server.")

        status = await ctx.send(f"🔄 Adding {user.mention} as a Tips & Tricks Helper...")

        role_results = await self._tt_role_in_guilds(user.id, add=True, role_name=cfg.TT_HELPER_ROLE_NAME)

        embed = discord.Embed(title="✅ Tips & Tricks Helper Added", color=discord.Color.green())
        embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
        embed.add_field(name="🌐 Role Sync (All Guilds)", value=self._tt_role_status_field(role_results), inline=False)
        await status.delete()
        await ctx.send(embed=embed)

        # Announcement
        announce_ch = ctx.guild.get_channel(cfg.TT_ANNOUNCEMENTS_CHANNEL_ID)
        if announce_ch:
            await announce_ch.send(embed=discord.Embed(
                title="✅ New Tips & Tricks Helper",
                description=f"{user.mention} has joined the **Tips & Tricks Helper** team! 💡",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            ))

        await _wave_log_event(
            category=cfg.WAVE_LOG_CATEGORY, action="helper_added",
            actor=ctx.author, target={"id": str(user.id)}, guild=ctx.guild,
            details={"role": cfg.TT_HELPER_ROLE_NAME},
        )

        try:
            from tasks import tipsandtricks as _tt
            await _tt.schedule_leaderboard_push(self.bot)
        except Exception:
            pass

    @commands.command(name='removetipshelper', aliases=['removetipsandtrickshelper'])
    @commands.has_any_role(*cfg.TT_ADMIN_ROLES)
    async def remove_tips_helper(self, ctx: commands.Context, *, user_input: str):
        """Remove Tips and Tricks Helper role in all 3 guilds. Usage: >removetipshelper @user|ID"""
        if ctx.guild.id != cfg.GUILD_ID:
            return await ctx.send("❌ This command only works in the main server.")

        m = re.match(r'<@!?(\d+)>', user_input.strip())
        if m:
            target_id = int(m.group(1))
        elif user_input.strip().isdigit():
            target_id = int(user_input.strip())
        else:
            return await ctx.send("❌ Please provide a valid user mention or ID.")

        member = ctx.guild.get_member(target_id)
        display_name = member.display_name if member else f"User {target_id}"

        status = await ctx.send(f"🔄 Removing {display_name} from Tips & Tricks Helper role...")

        role_results = await self._tt_role_in_guilds(target_id, add=False, role_name=cfg.TT_HELPER_ROLE_NAME)

        embed = discord.Embed(title="✅ Tips & Tricks Helper Removed", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{display_name} ({target_id})", inline=False)
        embed.add_field(name="🌐 Role Sync (All Guilds)", value=self._tt_role_status_field(role_results), inline=False)
        await status.delete()
        await ctx.send(embed=embed)

        # Announcement
        announce_ch = ctx.guild.get_channel(cfg.TT_ANNOUNCEMENTS_CHANNEL_ID)
        if announce_ch:
            mention = member.mention if member else f"<@{target_id}>"
            await announce_ch.send(embed=discord.Embed(
                title="❌ Tips & Tricks Helper Left",
                description=f"{mention} has been **removed** from the Tips & Tricks Helper role.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            ))

        await _wave_log_event(
            category=cfg.WAVE_LOG_CATEGORY, action="helper_removed",
            actor=ctx.author, target={"id": str(target_id)}, guild=ctx.guild,
            details={"role": cfg.TT_HELPER_ROLE_NAME},
        )

        try:
            from tasks import tipsandtricks as _tt
            await _tt.schedule_leaderboard_push(self.bot)
        except Exception:
            pass

    # ── HELPER COMMANDS ─────────────────────────────────────────────────────

    @commands.command(name='tttasks')
    async def list_tasks(self, ctx):
        """Show all available tasks."""
        if not _is_tt_helper(ctx):
            return await ctx.send("❌ You need the **Tips & Tricks Helper** role.")

        tasks = await db_tt.get_tasks_by_status('available')
        if not tasks:
            return await ctx.send("✅ No tasks available right now — check back later!")

        # Separate super task parents from regular tasks
        regular_tasks = [t for t in tasks if not t['parent_task_id']]
        super_tasks = {}
        for t in tasks:
            if t['parent_task_id']:
                pid = t['parent_task_id']
                if pid not in super_tasks:
                    super_tasks[pid] = []
                super_tasks[pid].append(t)

        # Build description with super tasks first (with progress), then regular tasks
        lines = []

        # Get all parents for super tasks
        all_parents = {}
        for pid in super_tasks.keys():
            parent = await db_tt.get_task(pid)
            if parent:
                all_parents[pid] = parent
                progress = await db_tt.get_super_task_progress(pid)
                if progress:
                    lines.append(
                        f"**#{pid}** 🎯 SUPER ({progress['completed']}/{progress['total']} done)\n"
                        f">>> {parent['description']}\n"
                        f"🏆 +{progress['completion_bonus']} WP bonus"
                    )
                    # Show subtasks indented
                    for st in super_tasks[pid]:
                        badges = "⚡ LUCKY" if st['is_lucky'] else ""
                        lines.append(f"  ↳ **#{st['task_id']}** {st['description']} {badges}")

        # Add regular tasks
        for t in regular_tasks[:20]:
            lines.append(_task_line(t))

        description = "\n\n".join(lines[:50])  # Limit total lines

        embed = discord.Embed(
            title=f"📋 Available Tasks ({len(tasks)})",
            color=discord.Color.from_rgb(255, 140, 26),
            description=description if description else "No tasks available",
        )
        if len(tasks) > 20:
            embed.set_footer(text=f"Showing tasks · Use >tttasks again to see more")
        else:
            embed.set_footer(text="Pick a task and claim it!")
        embed.add_field(
            name="🎯 How to earn",
            value="`>claimtttask <task_id>` → complete work → `>completetask <id>`",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name='claimtttask')
    async def claim_task(self, ctx, task_id: int):
        """Claim an available task and reserve it for yourself."""
        if not _is_tt_helper(ctx):
            return await ctx.send("❌ You need the **Tips & Tricks Helper** role.")

        task = await db_tt.get_task(task_id)
        if not task:
            return await ctx.send(f"❌ Task `#{task_id}` not found.")
        if task['status'] != 'available':
            return await ctx.send(f"❌ Task `#{task_id}` is already **{task['status']}**.")

        success = await db_tt.claim_task(task_id, ctx.author.id)
        if not success:
            return await ctx.send(f"❌ Could not claim task `#{task_id}` — someone else may have just claimed it.")

        pts = task['base_points']
        if task['is_lucky']:
            pts_str = f"⚡ **LUCKY** — you'll earn **{pts * cfg.LUCKY_TASK_MULTIPLIER:.0f} pts** on completion!"
            reward_color = discord.Color.from_rgb(255, 215, 0)
        elif task['bonus_applied']:
            pts_str = f"🔥 **BONUS** — {pts} pts (unclaimed bonus active)"
            reward_color = discord.Color.from_rgb(255, 100, 0)
        else:
            pts_str = f"{pts} WP on completion"
            reward_color = discord.Color.from_rgb(255, 140, 26)

        embed = discord.Embed(color=reward_color)
        embed.title = f"✅ Task #{task_id} Claimed"
        embed.description = f">>> {task['description']}"
        embed.add_field(
            name="💰 Reward",
            value=pts_str,
            inline=False
        )
        embed.add_field(
            name="⏱️ Next step",
            value=f"Complete your work, then run `>completetask {task_id}`",
            inline=False
        )
        embed.set_footer(text="You've got this! 🎯")
        await ctx.send(embed=embed)

    @commands.command(name='unclaim')
    async def unclaim_task(self, ctx, task_id: int):
        """Unclaim a task you previously claimed."""
        if not _is_tt_helper(ctx):
            return await ctx.send("❌ You need the **Tips & Tricks Helper** role.")

        success = await db_tt.unclaim_task(task_id, ctx.author.id)
        if success:
            await ctx.send(f"↩️ Task `#{task_id}` unclaimed — it's available for others again.")
        else:
            await ctx.send(f"❌ You don't have task `#{task_id}` claimed.")

    @commands.command(name='completetask')
    async def complete_task(self, ctx, task_id: int):
        """Mark your claimed task as completed and earn points."""
        if not _is_tt_helper(ctx):
            return await ctx.send("❌ You need the **Tips & Tricks Helper** role.")

        result = await db_tt.complete_task(task_id, ctx.author.id, bot=self.bot)
        if result is None:
            return await ctx.send(
                f"❌ Task `#{task_id}` isn't claimed by you, or doesn't exist."
            )

        task = await db_tt.get_task(task_id)  # fetch for lucky badge and parent info
        lucky_str = " ⚡ **LUCKY TASK!**" if (task and task['is_lucky']) else ""

        # Check if bonus was awarded
        bonus_str = ""
        if result['bonus_points'] > 0:
            bonus_str = (
                f"\n🏆 **SUPER TASK COMPLETE!** All subtasks done!\n"
                f"You got **+{result['bonus_points']:.0f} WP bonus** (split equally)"
            )

        # Credit total WP to spendable wallet; tt_helper_points tracks leaderboard stat
        from tasks.wave_points import add_wave_points as _add_wp
        new_wp = await _add_wp(ctx.author.id, int(result['total_points']))

        await ctx.send(
            f"🎉 Task `#{task_id}` completed!{lucky_str}{bonus_str}\n"
            f"You earned **+{result['total_points']:g} WP** (balance: {new_wp:,} WP)."
        )

        await _wave_log_event(
            category=cfg.WAVE_LOG_CATEGORY, action="task_completed",
            actor=ctx.author, guild=ctx.guild,
            details={
                "task_id": task_id, "base_points": result['base_points'],
                "bonus_points": result['bonus_points'], "total_points": result['total_points'],
                "is_lucky": bool(task and task['is_lucky']),
                "parent_task_id": task['parent_task_id'] if task else None,
            },
        )

        if cfg.TT_LOG_CHANNEL_ID:
            log_ch = ctx.guild.get_channel(cfg.TT_LOG_CHANNEL_ID)
            if log_ch:
                log_msg = (
                    f"✅ {ctx.author.mention} completed task **#{task_id}**"
                    + (" ⚡ LUCKY" if (task and task['is_lucky']) else "")
                    + f" (+{result['total_points']:g} WP)"
                )
                if result['bonus_points'] > 0:
                    log_msg += " 🏆 **SUPER TASK BONUS!**"
                await log_ch.send(log_msg)

    @commands.command(name='tthelp')
    async def tt_help(self, ctx):
        """Tips & Tricks system help."""
        embed = discord.Embed(
            title="💡 Tips & Tricks Helper System",
            description="Earn **Wave Points (WP)** by completing content tasks. Redeem in `>wpshop`.",
            color=discord.Color.from_rgb(255, 140, 26),
        )
        embed.add_field(
            name="📋 Helper Commands",
            value=(
                "`>tttasks` — 👀 browse available tasks\n"
                "`>claimtttask <id>` — 🎯 reserve a task\n"
                "`>completetask <id>` — ✅ submit work & earn WP\n"
                "`>unclaim <id>` — ↩️ drop a task"
            ),
            inline=False,
        )
        embed.add_field(
            name="🏆 Earning Rates",
            value=(
                "**Base:** 40 WP per task\n"
                "**⚡ Lucky (11% chance):** 80 WP (2× multiplier)\n"
                "**🔥 Bonus (7+ days unclaimed):** +80 WP\n"
                "**Super Task Bonus:** shared when all subtasks done"
            ),
            inline=False,
        )
        if _is_head_tt(ctx):
            embed.add_field(
                name="🔧 Head Commands",
                value=(
                    "`>addsupertask \"Parent\" | \"Sub1\" | \"Sub2\" ...` — 🎯 multi-claim task\n"
                    "`>addtipshelper / >removetipshelper` — 📊 manage roster"
                ),
                inline=False,
            )
        embed.set_footer(text="📊 T&T Leaderboard → wavedropmaps.pages.dev/tips_tricks_leaderboard.html")
        await ctx.send(embed=embed)

    # (ttredeem and ttptowp removed — tasks now pay WP directly)


async def setup(bot):
    await bot.add_cog(TipsAndTricksCog(bot))
    logger.info("✅ TipsAndTricksCog loaded")
