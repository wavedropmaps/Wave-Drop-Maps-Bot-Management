"""
Wave Logging — Wave Management Bot side

Cog that:
  • captures slash commands (completion + errors)
  • captures bot lifecycle (startup / graceful shutdown)
  • captures rate limit hits
  • runs the 30-min drain to the local Wave-Logging mirror
  • runs the nightly rollup that compacts yesterday's deltas into one file

Every event funnels through `core.global_logger.log_event` which writes
to the bot_logs SQLite table. The push loop drains unpushed rows into
delta JSON files and writes them to wave_logging_local/data/.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.global_logger import (
    BOT_NAME,
    ensure_table,
    install_terminal_log_capture,
    log_event,
    serialize_message,
)
from core.wave_logging_push import push_unpushed_events

logger = logging.getLogger("discord")


class WaveLoggingCog(commands.Cog):
    """Top-level cog for the new wave-logging system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._installed_listeners = False
        self._startup_logged = False

    # ----- cog lifecycle -----

    async def cog_load(self) -> None:
        await ensure_table()
        self._install_app_command_listeners()
        # Mirror every logger.* call (INFO+) into bot_logs under
        # category="terminal_logs" so the dashboard's Terminal Logs tab
        # populates. Idempotent — safe to re-call on cog reload.
        install_terminal_log_capture()
        # Drain bot_logs to the local mirror every 30 min (served by Flask at
        # wave-logging.pages.dev). Dormant until next restart.
        if not self._wave_log_push_loop.is_running():
            self._wave_log_push_loop.start()
        logger.info("[wave_logging] Cog loaded — table ensured, listeners installed, terminal capture + push loop on")

    def cog_unload(self) -> None:
        if self._wave_log_push_loop.is_running():
            self._wave_log_push_loop.cancel()
        logger.info("[wave_logging] Cog unloaded")

    # ----- Wave-Logging local mirror drain loop -----

    @tasks.loop(minutes=30)
    async def _wave_log_push_loop(self) -> None:
        try:
            await push_unpushed_events(self.bot)
        except Exception as e:
            logger.error(f"[wave_logging] push loop error: {e}")

    @_wave_log_push_loop.before_loop
    async def _before_push_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ----- slash command auto-capture -----

    def _install_app_command_listeners(self) -> None:
        """Attach completion + error handlers directly onto bot.tree.
        We override existing handlers carefully — chaining the previous one so
        nothing already wired up gets broken."""
        if self._installed_listeners:
            return

        tree = self.bot.tree

        prev_on_completion = getattr(tree, "on_completion", None)
        prev_on_error = getattr(tree, "on_error", None)

        async def _on_completion(interaction: discord.Interaction, command: app_commands.Command):
            try:
                ns = getattr(interaction, "namespace", None)
                ns_dict = dict(ns.__dict__) if ns else None
                await log_event(
                    category="commands",
                    action="slash_command_completed",
                    actor=interaction.user,
                    guild=interaction.guild,
                    details={
                        "command": getattr(command, "qualified_name", str(command)),
                        "channel_id": str(interaction.channel_id) if interaction.channel_id else None,
                        "channel_name": getattr(interaction.channel, "name", None),
                        "namespace": ns_dict,
                        "interaction_id": str(interaction.id),
                        "interaction_locale": str(getattr(interaction, "locale", None)),
                        "guild_locale": str(getattr(interaction, "guild_locale", None)),
                        "type": str(getattr(interaction, "type", None)),
                    },
                )
            except Exception as e:
                logger.error(f"[wave_logging] on_completion log failed: {e}")
            if callable(prev_on_completion):
                try:
                    await prev_on_completion(interaction, command)
                except Exception as e:
                    logger.error(f"[wave_logging] chained prev on_completion failed: {e}")

        async def _on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            try:
                cmd_name = "unknown"
                if interaction.command is not None:
                    cmd_name = getattr(interaction.command, "qualified_name", str(interaction.command))
                tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                ns = getattr(interaction, "namespace", None)
                ns_dict = dict(ns.__dict__) if ns else None
                await log_event(
                    category="errors",
                    action="slash_command_error",
                    actor=interaction.user,
                    guild=interaction.guild,
                    details={
                        "command": cmd_name,
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                        "traceback": tb,
                        "namespace": ns_dict,
                        "interaction_id": str(interaction.id),
                        "channel_id": str(interaction.channel_id) if interaction.channel_id else None,
                        "channel_name": getattr(interaction.channel, "name", None),
                    },
                )
            except Exception as e:
                logger.error(f"[wave_logging] on_error log failed: {e}")
            if callable(prev_on_error):
                try:
                    await prev_on_error(interaction, error)
                except Exception as e:
                    logger.error(f"[wave_logging] chained prev on_error failed: {e}")

        tree.on_completion = _on_completion  # type: ignore[assignment]
        tree.on_error = _on_error            # type: ignore[assignment]

        self._installed_listeners = True
        logger.info("[wave_logging] App command listeners installed on bot.tree")

    # ----- classic prefix command capture (>cmd) -----

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        try:
            await log_event(
                category="commands",
                action="prefix_command_completed",
                actor=ctx.author,
                guild=ctx.guild,
                details={
                    "command": ctx.command.qualified_name if ctx.command else "unknown",
                    "prefix": ctx.prefix,
                    "invoked_with": getattr(ctx, "invoked_with", None),
                    "args": [str(a) for a in (getattr(ctx, "args", []) or [])[2:]],
                    "kwargs": {k: str(v) for k, v in (getattr(ctx, "kwargs", {}) or {}).items()},
                    "channel_id": str(ctx.channel.id) if ctx.channel else None,
                    "channel_name": getattr(ctx.channel, "name", None),
                    "message": serialize_message(ctx.message) if ctx.message else None,
                },
            )
        except Exception as e:
            logger.error(f"[wave_logging] on_command_completion log failed: {e}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        try:
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            await log_event(
                category="errors",
                action="prefix_command_error",
                actor=ctx.author,
                guild=ctx.guild,
                details={
                    "command": ctx.command.qualified_name if ctx.command else "unknown",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                    "traceback": tb,
                    "message": serialize_message(ctx.message) if ctx.message else None,
                },
            )
        except Exception as e:
            logger.error(f"[wave_logging] on_command_error log failed: {e}")

    # ----- bot lifecycle -----

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready fires every reconnect — only log the first time per process
        if self._startup_logged:
            return
        self._startup_logged = True
        try:
            await log_event(
                category="bot_lifecycle",
                action="bot_started",
                actor={"id": str(self.bot.user.id) if self.bot.user else None,
                       "name": str(self.bot.user) if self.bot.user else BOT_NAME},
                details={
                    "guild_count": len(self.bot.guilds),
                    "guilds": [
                        {"id": str(g.id), "name": g.name, "member_count": g.member_count}
                        for g in self.bot.guilds
                    ],
                    "command_count": len(list(self.bot.commands)),
                },
            )
        except Exception as e:
            logger.error(f"[wave_logging] on_ready log failed: {e}")

    @commands.Cog.listener()
    async def on_disconnect(self) -> None:
        # Fires on every reconnect cycle too — note it but keep it light
        try:
            await log_event(
                category="bot_lifecycle",
                action="bot_disconnected",
                actor={"id": str(self.bot.user.id) if self.bot.user else None,
                       "name": str(self.bot.user) if self.bot.user else BOT_NAME},
            )
        except Exception:
            pass  # don't even log the failure — disconnect path is fragile

    @commands.Cog.listener()
    async def on_resumed(self) -> None:
        try:
            await log_event(
                category="bot_lifecycle",
                action="bot_resumed",
                actor={"id": str(self.bot.user.id) if self.bot.user else None,
                       "name": str(self.bot.user) if self.bot.user else BOT_NAME},
            )
        except Exception as e:
            logger.error(f"[wave_logging] on_resumed log failed: {e}")



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WaveLoggingCog(bot))
