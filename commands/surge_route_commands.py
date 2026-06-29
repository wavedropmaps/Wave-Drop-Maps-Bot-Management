"""
commands/surge_route_commands.py — Surge Route staff commands.

Phase 2 (roster): >addsurgemaker, >removesurgemaker, >surgerotation, >syncsurgepositions.
Later phases add assignment / completion / redemption / admin commands to this cog.

Mirrors the Loot Route roster commands but:
  • the Surge Route Maker role is matched purely by case-insensitive NAME across all 3
    guilds (no hardcoded per-guild ID),
  • departed makers are archived to surge_route_alumni (history kept),
  • there is NO Discord log channel — roster changes emit _wave_log_event(category="surge_routes").
"""

import re
import os
import json
import shutil
import random
import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

import core.surge_config as cfg
from core.global_logger import log_event as _wave_log_event
import database_surge as sdb
from commands.loot_route_commands import PromotionConfirmView

logger = logging.getLogger('discord')

# Permission gate for surge roster/admin commands.
SURGE_ADMIN_ROLES = ('007', '+', 'Management', cfg.HEAD_SURGE_ROUTES_ROLE_NAME)
# Makers can redeem their own points.
SURGE_REDEEM_ROLES = ('007', '+', 'Management', cfg.HEAD_SURGE_ROUTES_ROLE_NAME, cfg.SURGE_MAKER_ROLE_NAME)


def _find_role_by_name(guild: discord.Guild, name: str):
    """Case-insensitive role lookup within a guild."""
    target = name.lower()
    for r in guild.roles:
        if r.name.lower() == target:
            return r
    return None


class SurgeCancelReassignView(discord.ui.View):
    """3-button prompt shown after cancelling a surge assignment."""

    def __init__(self, ctx):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.value = None  # True = auto, 'manual' = pick, False = no reassign

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


class SurgeManualPickView(discord.ui.View):
    """Dropdown to manually pick a surge maker for reassignment."""

    def __init__(self, ctx, available_users, guild):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.available_users = available_users  # [(rank, user_id)]
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

        select = discord.ui.Select(placeholder="👤 Choose a maker to assign...", options=options)
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


class SurgeRouteCommands(commands.Cog):
    """Staff commands for the Surge Route rotation."""

    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------------------------- helpers
    async def safe_delay(self, seconds: int):
        try:
            await asyncio.sleep(seconds)
        except Exception:
            pass

    async def _refresh_surge_leaderboard(self, triggered_by: str):
        """Trigger the surge leaderboard refresh if the Phase-6 task exists yet; else no-op."""
        try:
            from tasks.surge_routes import auto_update_surge_route_leaderboard
            asyncio.create_task(auto_update_surge_route_leaderboard(self.bot, triggered_by=triggered_by))
        except Exception:
            pass  # Phase 6 not built yet — safe no-op


    async def _role_in_guilds(self, user_id: int, add: bool) -> dict:
        """Add/remove the 'Surge Route Maker' role by NAME across all 3 guilds."""
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
            role = _find_role_by_name(guild, cfg.SURGE_MAKER_ROLE_NAME)
            if not role:
                results[gid] = f"⚠️ Role '{cfg.SURGE_MAKER_ROLE_NAME}' not found"
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

    def _role_status_field(self, role_results: dict) -> str:
        out = ""
        for gid, res in role_results.items():
            g = self.bot.get_guild(gid)
            out += f"**{g.name if g else f'Guild {gid}'}:** {res}\n"
        return out[:1024]

    async def send_role_change_log(self, guild: discord.Guild, user: discord.Member, action: str, executor: discord.Member):
        """Send log message when Surge Route Maker role is added/removed."""
        try:
            from datetime import datetime, timezone
            log_channel = guild.get_channel(cfg.SURGE_MEMBER_UPDATES_CHANNEL_ID)
            if not log_channel:
                return
            color = discord.Color.green() if action == 'added' else discord.Color.orange()
            embed = discord.Embed(
                title=f"{'✅' if action == 'added' else '🔴'} Surge Route Maker Role {action.title()}",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(
                name="User",
                value=f"{user.mention} ({user.display_name})\nID: {user.id}",
                inline=True,
            )
            if executor:
                embed.add_field(
                    name="Added by" if action == 'added' else "Removed by",
                    value=f"{executor.mention} ({executor.display_name})",
                    inline=True,
                )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"User ID: {user.id}")
            await log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"[Surge Route Commands] ⚠️ Role change log error: {e}")

    # ---------------------------------------------------------------- add
    @commands.command(name="addsurgeroutemaker", aliases=["addsurgemaker"])
    @commands.has_any_role(*SURGE_ADMIN_ROLES)
    async def add_surge_route_maker(self, ctx: commands.Context, user: discord.Member):
        """Add a user to the surge rotation (3-guild role sync + points init). Usage: >addsurgemaker @user"""
        if ctx.guild.id != cfg.GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return
        surge_cog = self.bot.get_cog('SurgeRoutes')
        if surge_cog:
            surge_cog.skip_auto_regen = True  # we handle the role change explicitly
        try:
            status = await ctx.send(f"🔄 Adding {user.mention} to the surge route system...")

            if await sdb.get_surge_route_position(user.id):
                rank = await sdb.get_surge_route_position(user.id)
                await status.edit(content=f"❌ {user.mention} is already in the rotation (rank #{rank}).")
                return

            # 1) Roles across all 3 guilds (do this first so points-init role check passes)
            await status.edit(content="🎭 Syncing roles across all guilds...")
            role_results = await self._role_in_guilds(user.id, add=True)

            # 2) Rotation slot (assigned_at = now → goes to the end of the rotation)
            await status.edit(content="💾 Adding to rotation...")
            await sdb.set_surge_route_position(user.id)
            await self.safe_delay(1)
            user_rank = await sdb.get_surge_route_position(user.id)
            if not user_rank:
                raise Exception(f"Insert verification failed — {user.id} not in rotation after insert")

            # 3) Initialize points (role now present → validation passes)
            await sdb.set_surge_route_user_points(user.id, 0.0, 0, guild_id=ctx.guild.id, bot=self.bot)

            total = len(await sdb.get_all_surge_route_positions())

            await _wave_log_event(
                category=cfg.WAVE_LOG_CATEGORY, action="maker_added",
                actor=ctx.author, target={"id": str(user.id)}, guild=ctx.guild,
                details={"rank": user_rank, "total_makers": total},
            )
            await self._refresh_surge_leaderboard("rotation_add")

            embed = discord.Embed(title="✅ Surge Route Maker Added", color=discord.Color.green())
            embed.add_field(name="User", value=f"{user.mention} ({user.id})", inline=False)
            embed.add_field(name="Rotation Position", value=f"**#{user_rank}** (last in line)", inline=True)
            embed.add_field(name="Total Makers", value=f"{total}", inline=True)
            embed.add_field(name="🌐 Role Sync (All Guilds)", value=self._role_status_field(role_results), inline=False)
            if user.display_avatar:
                embed.set_thumbnail(url=user.display_avatar.url)
            await status.delete()
            await ctx.send(embed=embed)
            await self.send_role_change_log(ctx.guild, user, 'added', ctx.author)

            try:
                await user.send(embed=discord.Embed(
                    title="⚡ You're now a Surge Route Maker!",
                    description=(f"You've been added to the surge rotation at position **#{user_rank}**.\n"
                                 "You'll be assigned surge routes in turn. Complete them fast for the most points!"),
                    color=discord.Color.orange(),
                ))
            except Exception:
                pass

            # A newly-free maker may be able to take a held map.
            if surge_cog:
                await surge_cog.drain_pending_pool(reason="new_maker")
        except Exception as e:
            logger.error(f"[SURGE ROUTES] add maker error: {e}")
            import traceback; traceback.print_exc()
            await ctx.send(embed=discord.Embed(title="❌ Error Adding User", description=f"```{e}```", color=discord.Color.red()))
        finally:
            if surge_cog:
                surge_cog.skip_auto_regen = False

    # ---------------------------------------------------------------- remove
    @commands.command(name="removesurgeroutemaker", aliases=["removesurgemaker"])
    @commands.has_any_role(*SURGE_ADMIN_ROLES)
    async def remove_surge_route_maker(self, ctx: commands.Context, *, user_input: str):
        """Remove a user from the surge rotation (archives history, removes role in all guilds). Usage: >removesurgemaker @user|ID"""
        if ctx.guild.id != cfg.GUILD_ID:
            await ctx.send("❌ This command only works in the main server.")
            return

        user_input = user_input.strip()
        m = re.match(r'<@!?(\d+)>', user_input)
        if m:
            target_id = int(m.group(1))
        elif user_input.isdigit():
            target_id = int(user_input)
        else:
            await ctx.send("❌ Please provide a valid user mention or ID.")
            return

        member = ctx.guild.get_member(target_id)
        display_name = member.display_name if member else f"User {target_id}"

        surge_cog = self.bot.get_cog('SurgeRoutes')
        if surge_cog:
            surge_cog.skip_auto_regen = True  # we handle the role change explicitly
        try:
            status = await ctx.send(f"🔄 Removing {display_name} ({target_id})...")
            had_position = await sdb.get_surge_route_position(target_id) is not None

            # Archive → moves points/position to surge_route_alumni and deletes from active tables.
            archived = await sdb.archive_surge_route_maker(target_id, display_name=display_name)
            # Belt-and-braces: ensure no residual active rows even if archive found nothing.
            if not archived:
                await sdb.remove_surge_route_position(target_id)

            # Remove the role across all 3 guilds.
            await status.edit(content="🎭 Removing role across all guilds...")
            role_results = await self._role_in_guilds(target_id, add=False)

            total = len(await sdb.get_all_surge_route_positions())
            await _wave_log_event(
                category=cfg.WAVE_LOG_CATEGORY, action="maker_removed",
                actor=ctx.author, target={"id": str(target_id)}, guild=ctx.guild,
                details={"archived": archived, "total_makers": total},
            )
            await self._refresh_surge_leaderboard("rotation_remove")

            embed = discord.Embed(title="✅ Surge Route Maker Removed", color=discord.Color.green())
            embed.add_field(name="User", value=f"{display_name} ({target_id})", inline=False)
            embed.add_field(
                name="Data",
                value=("📦 History archived to alumni (points kept)" if archived
                       else ("ℹ️ Was not in the rotation — cleaned up any residual data" if not had_position
                             else "📦 Removed from rotation")),
                inline=False,
            )
            embed.add_field(name="Remaining Makers", value=f"{total} (ranks auto-resequenced)", inline=True)
            embed.add_field(name="🌐 Role Sync (All Guilds)", value=self._role_status_field(role_results), inline=False)
            if member and member.display_avatar:
                embed.set_thumbnail(url=member.display_avatar.url)
            await status.delete()
            await ctx.send(embed=embed)
            if member:
                await self.send_role_change_log(ctx.guild, member, 'removed', ctx.author)

        except Exception as e:
            logger.error(f"[SURGE ROUTES] remove maker error: {e}")
            import traceback; traceback.print_exc()
            await ctx.send(embed=discord.Embed(title="❌ Error Removing User", description=f"```{e}```", color=discord.Color.red()))
        finally:
            if surge_cog:
                surge_cog.skip_auto_regen = False

async def setup(bot):
    await bot.add_cog(SurgeRouteCommands(bot))
    logger.info("✅ SurgeRouteCommands cog loaded")
