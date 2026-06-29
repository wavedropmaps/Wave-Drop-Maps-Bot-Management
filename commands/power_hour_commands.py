"""
Power Hour Commands - commands/power_hour_commands.py

Admin/management commands for the Power Hour system.

Commands:
  >powerhour       — manually force-trigger a Power Hour right now
  >cancelpowerhour — cancel an ongoing Power Hour immediately
"""

import asyncio
import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging

from tasks.power_hour import (
    get_power_hour_state,
    set_power_hour_cancelled,
    clear_activity_table,
    run_power_hour,
    update_roll_status_message,
    get_announce_channel,
    get_start_message_id,
    save_start_message_id,
    save_last_roll,
    push_power_hour_to_events,
)

logger = logging.getLogger('discord')


class PowerHourCommands(commands.Cog):
    """Commands for managing and inspecting the Power Hour system."""

    def __init__(self, bot):
        self.bot = bot

    # ==================== >powerhour ====================

    @commands.command(name='powerhour', aliases=['ph', 'forcepowerhour'])
    @commands.has_any_role('Management', '007', '+')
    async def force_power_hour(self, ctx):
        """
        Manually trigger a Power Hour right now. Management/007/+ only.
        Usage: >powerhour
        """
        state = await get_power_hour_state()
        if state['active']:
            await ctx.send(embed=discord.Embed(
                title="⚡ Already Active!",
                description="A Power Hour is already running. Check the announcement channel.",
                color=discord.Color.orange()
            ))
            return

        await ctx.send(embed=discord.Embed(
            title="⚡ Power Hour Triggered!",
            description="Manually started by management. Watch the announcement channel!",
            color=discord.Color.gold()
        ))
        logger.info(f"⚡ Power Hour manually triggered by {ctx.author}")

        # Mirror the scheduler exactly: update roll status in the announce channel
        # before handing off to run_power_hour, so the channel reflects the trigger.
        # roll=0.0 signals a manual/forced trigger (no random roll was made).
        now      = datetime.now(timezone.utc)
        hour_key = now.strftime('%Y-%m-%d-%H')
        await save_last_roll(0.0, 1.0, True, hour_key)
        await update_roll_status_message(self.bot, triggered=True, roll=0.0, hour_key=hour_key)
        asyncio.ensure_future(push_power_hour_to_events(self.bot))

        asyncio.create_task(run_power_hour(self.bot))

    # ==================== >cancelpowerhour ====================

    @commands.command(name='cancelpowerhour', aliases=['cancelph', 'phcancel'])
    @commands.has_any_role('Management', '007', '+')
    async def cancel_power_hour(self, ctx):
        """
        Cancel an ongoing Power Hour immediately. No points are awarded.
        Management/007/+ only.
        Usage: >cancelpowerhour
        """
        state = await get_power_hour_state()
        if not state['active']:
            await ctx.send(embed=discord.Embed(
                title="⚡ No Active Power Hour",
                description="There is no Power Hour currently running.",
                color=discord.Color.greyple()
            ))
            return

        # Corrupt hour_key → 'CANCELLED' so the sleeping run_power_hour task
        # sees a key mismatch when it wakes up and aborts without scanning or
        # awarding any points. Without this, set_power_hour_inactive() alone
        # does NOT stop the sleeping task.
        await set_power_hour_cancelled()
        await clear_activity_table()

        # Delete the live "POWER HOUR IS LIVE!" start embed from the announce
        # channel so it doesn't stay visible after the event is gone.
        announce_ch = await get_announce_channel(self.bot)
        if announce_ch:
            start_msg_id = await get_start_message_id()
            if start_msg_id:
                try:
                    start_msg = await announce_ch.fetch_message(start_msg_id)
                    await start_msg.delete()
                    logger.info(f"🗑️ Deleted Power Hour start embed ({start_msg_id}) on cancel")
                except (discord.NotFound, discord.Forbidden):
                    pass
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete start embed on cancel: {e}")
                await save_start_message_id(None)

            # Post a public cancellation notice in the announce channel.
            try:
                await announce_ch.send(embed=discord.Embed(
                    title="🛑 Power Hour Cancelled",
                    description="The ongoing Power Hour has been cancelled by management. No points will be awarded.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                ))
            except Exception as e:
                logger.warning(f"⚠️ Could not post cancellation notice to announce channel: {e}")

        # Confirm back in the command channel too.
        await ctx.send(embed=discord.Embed(
            title="🛑 Power Hour Cancelled",
            description="The ongoing Power Hour has been stopped. No points will be awarded.",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        ))
        logger.info(f"🛑 Power Hour manually cancelled by {ctx.author}")
        asyncio.ensure_future(push_power_hour_to_events(self.bot))


async def setup(bot):
    await bot.add_cog(PowerHourCommands(bot))
    logger.info("✅ PowerHourCommands cog loaded")