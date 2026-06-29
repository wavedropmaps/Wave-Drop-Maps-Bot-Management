"""
Manual Duties - commands/manual_duties.py

Admin commands to manually override or penalise a user's duty count in
duties_totals.json and immediately update the Staff Hub.

Commands:
  >setduty       <user_id> <duty> <value>    — hard-set a user's count
  >setdivisor    <user_id> <duty> <divisor>  — apply a penalty divisor (2-10)
  >removedivisor <user_id> <duty>            — remove a divisor
  >getduty       <user_id>                   — show current counts + any divisors
  >dutyinfo                                  — usage reference

Duty names: req, modlog, message, reviews
Requires: Management, 007, or + role
"""

import discord
from discord.ext import commands
from datetime import datetime, timezone
import json
import logging
import os

logger = logging.getLogger('discord')

VALID_DUTIES     = ['req', 'modlog', 'message', 'reviews']
DUTIES_JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'json_data', 'duties_totals.json')


# ==================== HELPERS ====================

def load_duties_json() -> dict:
    try:
        with open(DUTIES_JSON_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("⚠️ duties_totals.json not found — starting fresh")
        return {}
    except Exception as e:
        logger.error(f"❌ Failed to load duties_totals.json: {e}")
        return {}


def save_duties_json(data: dict) -> bool:
    try:
        with open(DUTIES_JSON_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save duties_totals.json: {e}")
        return False


async def resolve_user(ctx, target: str):
    """Resolve a mention or raw user ID to (user_id, display_name)."""
    if ctx.message.mentions:
        m = ctx.message.mentions[0]
        return m.id, m.display_name
    try:
        uid = int(target.strip('<@!>'))
        member = ctx.guild.get_member(uid)
        if not member:
            try:
                member = await ctx.guild.fetch_member(uid)
            except discord.NotFound:
                pass
        return uid, member.display_name if member else f"User {uid}"
    except ValueError:
        return None, None


async def push_to_github(duties_data: dict):
    from tasks.staff_hub_writer import push_duties_to_github
    await push_duties_to_github(duties_data)


def stamp_meta(duties_data: dict, ctx, note: str):
    if '_meta' not in duties_data:
        duties_data['_meta'] = {}
    duties_data['_meta']['last_updated'] = datetime.now(timezone.utc).isoformat()
    duties_data['_meta']['last_manual_edit'] = {
        'by': str(ctx.author),
        'note': note,
        'at': datetime.now(timezone.utc).isoformat()
    }


# ==================== COG ====================

class ManualDuties(commands.Cog):
    """Manual override + divisor penalty commands for duties_totals.json."""

    def __init__(self, bot):
        self.bot = bot

    # ==================== >setduty ====================

    @commands.command(name='setduty')
    @commands.has_any_role('Management', '007', '+')
    async def set_duty(self, ctx, target: str, duty: str, value: int):
        """
        Hard-set a user's duty count and push to GitHub immediately.

        Usage:   >setduty <@user|user_id> <duty> <value>
        Example: >setduty 123456789012345678 role 42
        """
        user_id, display_name = await resolve_user(ctx, target)
        if not user_id:
            await ctx.send(embed=discord.Embed(title="❌ Invalid User",
                description="Please mention a user or provide their user ID.",
                color=discord.Color.red()))
            return

        duty = duty.lower()
        if duty not in VALID_DUTIES:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Duty",
                description=f"`{duty}` is not valid.\nValid duties: `{'`, `'.join(VALID_DUTIES)}`",
                color=discord.Color.red()))
            return

        if value < 0:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Value",
                description="Value must be 0 or greater.",
                color=discord.Color.red()))
            return

        duties_data = load_duties_json()
        if duty not in duties_data:
            duties_data[duty] = {}

        uid_str   = str(user_id)
        old_entry = duties_data[duty].get(uid_str, {})
        old_value = old_entry.get('count', 0)
        raw_count = old_entry.get('raw_count', old_value)

        # Update count + name, preserve any existing divisor, and flag as override
        duties_data[duty][uid_str] = {
            **old_entry, 
            'name': display_name, 
            'count': value, 
            'raw_count': raw_count,
            'uid': user_id,
            'is_override': True
        }
        stamp_meta(duties_data, ctx, f"setduty {display_name} {duty}: {old_value}→{value} (override applied)")

        if not save_duties_json(duties_data):
            await ctx.send(embed=discord.Embed(title="❌ Save Failed",
                description="Failed to save locally. Check logs.", color=discord.Color.red()))
            return

        logger.info(f"✏️ [ManualDuties] {ctx.author} setduty {display_name} ({user_id}) {duty}: {old_value} → {value}")

        status = await ctx.send(embed=discord.Embed(title="⏳ Updating Staff Hub...",
            description=f"**{display_name}** `{duty}`: `{old_value}` → `{value}`",
            color=discord.Color.orange()))

        try:
            await push_to_github(duties_data)
            await status.edit(embed=discord.Embed(
                title="✅ Duty Updated",
                description=(
                    f"**User:** {display_name}\n"
                    f"**Duty:** `{duty}`\n"
                    f"**Count:** `{old_value}` → `{value}`\n\n"
                    f"✅ Staff Hub updated. (Override flag applied)"
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            ).set_footer(text=f"By {ctx.author}"))
        except Exception as e:
            logger.error(f"❌ Staff Hub update failed in setduty: {e}")
            await status.edit(embed=discord.Embed(
                title="⚠️ Saved Locally — Staff Hub Update Failed",
                description=f"Saved locally but Staff Hub update failed.\nError: `{e}`",
                color=discord.Color.orange()))

    # ==================== >setdivisor ====================

    @commands.command(name='setdivisor')
    @commands.has_any_role('Management', '007', '+')
    async def set_divisor(self, ctx, target: str, duty: str, divisor: int):
        """
        Apply a score penalty divisor to a user's duty count.
        Their real scanned count gets divided by this number before showing
        on the leaderboard — and stays applied automatically every future scan.

        Usage:   >setdivisor <@user|user_id> <duty> <divisor>
        Example: >setdivisor 123456789012345678 role 2

        Divisor must be between 2 and 10.
        Use >removedivisor to clear it.
        """
        user_id, display_name = await resolve_user(ctx, target)
        if not user_id:
            await ctx.send(embed=discord.Embed(title="❌ Invalid User",
                description="Please mention a user or provide their user ID.",
                color=discord.Color.red()))
            return

        duty = duty.lower()
        if duty not in VALID_DUTIES:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Duty",
                description=f"`{duty}` is not valid.\nValid duties: `{'`, `'.join(VALID_DUTIES)}`",
                color=discord.Color.red()))
            return

        if not (2 <= divisor <= 10):
            await ctx.send(embed=discord.Embed(title="❌ Invalid Divisor",
                description="Divisor must be between **2** and **10**.\nExample: `>setdivisor @user role 2`",
                color=discord.Color.red()))
            return

        duties_data = load_duties_json()
        if duty not in duties_data:
            duties_data[duty] = {}

        uid_str       = str(user_id)
        old_entry     = duties_data[duty].get(uid_str, {})
        old_divisor   = old_entry.get('divisor', 1)
        current_count = old_entry.get('count', 0)
        raw_count     = old_entry.get('raw_count', current_count)

        # Apply divisor to the raw count
        new_count = max(0, raw_count // divisor)

        duties_data[duty][uid_str] = {
            **old_entry,
            'name':      display_name,
            'uid':       user_id,
            'count':     new_count,
            'raw_count': raw_count,
            'divisor':   divisor,
        }
        stamp_meta(duties_data, ctx,
            f"setdivisor {display_name} {duty}: /{old_divisor}→/{divisor} raw={raw_count} displayed={new_count}")

        if not save_duties_json(duties_data):
            await ctx.send(embed=discord.Embed(title="❌ Save Failed",
                description="Failed to save locally. Check logs.", color=discord.Color.red()))
            return

        logger.info(
            f"✂️ [ManualDuties] {ctx.author} setdivisor {display_name} ({user_id}) "
            f"{duty}: /{old_divisor} → /{divisor} | raw={raw_count} displayed={new_count}"
        )

        status = await ctx.send(embed=discord.Embed(title="⏳ Updating Staff Hub...",
            description=f"Applying `/{divisor}` penalty to **{display_name}** `{duty}`...",
            color=discord.Color.orange()))

        try:
            await push_to_github(duties_data)
            await status.edit(embed=discord.Embed(
                title="✂️ Divisor Applied",
                description=(
                    f"**User:** {display_name}\n"
                    f"**Duty:** `{duty}`\n"
                    f"**Divisor:** `/{old_divisor}` → `/{divisor}`\n"
                    f"**Real count:** `{raw_count}`\n"
                    f"**Displayed count:** `{new_count}` *(= {raw_count} ÷ {divisor})*\n\n"
                    f"Every future scan will automatically apply this divisor.\n"
                    f"Use `>removedivisor {user_id} {duty}` to clear it."
                ),
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            ).set_footer(text=f"By {ctx.author}"))
        except Exception as e:
            logger.error(f"❌ Staff Hub update failed in setdivisor: {e}")
            await status.edit(embed=discord.Embed(
                title="⚠️ Saved Locally — Staff Hub Update Failed",
                description=f"Saved locally but Staff Hub update failed.\nError: `{e}`",
                color=discord.Color.orange()))

    # ==================== >removedivisor ====================

    @commands.command(name='removedivisor')
    @commands.has_any_role('Management', '007', '+')
    async def remove_divisor(self, ctx, target: str, duty: str):
        """
        Remove a divisor penalty from a user's duty, restoring their real count.

        Usage:   >removedivisor <@user|user_id> <duty>
        Example: >removedivisor 123456789012345678 role
        """
        user_id, display_name = await resolve_user(ctx, target)
        if not user_id:
            await ctx.send(embed=discord.Embed(title="❌ Invalid User",
                description="Please mention a user or provide their user ID.",
                color=discord.Color.red()))
            return

        duty = duty.lower()
        if duty not in VALID_DUTIES:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Duty",
                description=f"`{duty}` is not valid.\nValid duties: `{'`, `'.join(VALID_DUTIES)}`",
                color=discord.Color.red()))
            return

        duties_data = load_duties_json()
        uid_str = str(user_id)
        entry   = duties_data.get(duty, {}).get(uid_str)

        if not entry:
            await ctx.send(embed=discord.Embed(title="❌ No Entry Found",
                description=f"**{display_name}** has no entry in `{duty}` — nothing to remove.",
                color=discord.Color.red()))
            return

        old_divisor = entry.get('divisor', 1)
        if old_divisor <= 1:
            await ctx.send(embed=discord.Embed(title="ℹ️ No Divisor Set",
                description=f"**{display_name}** has no active divisor on `{duty}`.",
                color=discord.Color.greyple()))
            return

        # Restore raw count as displayed count and strip divisor fields
        raw_count = entry.get('raw_count', entry.get('count', 0))
        entry['count'] = raw_count
        entry.pop('divisor', None)
        entry.pop('raw_count', None)
        duties_data[duty][uid_str] = entry
        stamp_meta(duties_data, ctx,
            f"removedivisor {display_name} {duty}: removed /{old_divisor}, restored count={raw_count}")

        if not save_duties_json(duties_data):
            await ctx.send(embed=discord.Embed(title="❌ Save Failed",
                description="Failed to save locally. Check logs.", color=discord.Color.red()))
            return

        logger.info(
            f"✅ [ManualDuties] {ctx.author} removedivisor {display_name} ({user_id}) "
            f"{duty}: removed /{old_divisor}, restored count={raw_count}"
        )

        status = await ctx.send(embed=discord.Embed(title="⏳ Updating Staff Hub...",
            description=f"Removing `/{old_divisor}` from **{display_name}** `{duty}`...",
            color=discord.Color.orange()))

        try:
            await push_to_github(duties_data)
            await status.edit(embed=discord.Embed(
                title="✅ Divisor Removed",
                description=(
                    f"**User:** {display_name}\n"
                    f"**Duty:** `{duty}`\n"
                    f"**Removed divisor:** `/{old_divisor}`\n"
                    f"**Restored count:** `{raw_count}`\n\n"
                    f"Their real scanned count will now show normally."
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            ).set_footer(text=f"By {ctx.author}"))
        except Exception as e:
            logger.error(f"❌ Staff Hub update failed in removedivisor: {e}")
            await status.edit(embed=discord.Embed(
                title="⚠️ Saved Locally — Staff Hub Update Failed",
                description=f"Saved locally but Staff Hub update failed.\nError: `{e}`",
                color=discord.Color.orange()))

    # ==================== >removeoverride ====================

    @commands.command(name='removeoverride')
    @commands.has_any_role('Management', '007', '+')
    async def remove_override(self, ctx, target: str, duty: str):
        """
        Remove a manual override from a user's duty, restoring their real count.

        Usage:   >removeoverride <@user|user_id> <duty>
        Example: >removeoverride 123456789012345678 role
        """
        user_id, display_name = await resolve_user(ctx, target)
        if not user_id:
            await ctx.send(embed=discord.Embed(title="❌ Invalid User",
                description="Please mention a user or provide their user ID.",
                color=discord.Color.red()))
            return

        duty = duty.lower()
        if duty not in VALID_DUTIES:
            await ctx.send(embed=discord.Embed(title="❌ Invalid Duty",
                description=f"`{duty}` is not valid.\nValid duties: `{'`, `'.join(VALID_DUTIES)}`",
                color=discord.Color.red()))
            return

        duties_data = load_duties_json()
        uid_str = str(user_id)
        entry   = duties_data.get(duty, {}).get(uid_str)

        if not entry:
            await ctx.send(embed=discord.Embed(title="❌ No Entry Found",
                description=f"**{display_name}** has no entry in `{duty}` — nothing to remove.",
                color=discord.Color.red()))
            return

        is_override = entry.get('is_override', False)
        if not is_override:
            await ctx.send(embed=discord.Embed(title="ℹ️ No Override Set",
                description=f"**{display_name}** has no active manual override on `{duty}`.",
                color=discord.Color.greyple()))
            return

        # Restore raw count as displayed count (and apply divisor if active)
        raw_count = entry.get('raw_count', entry.get('count', 0))
        divisor = entry.get('divisor', 1)
        new_count = raw_count // divisor if divisor > 1 else raw_count
        
        entry['count'] = new_count
        entry.pop('is_override', None)
        # If no divisor, we can pop raw_count as well
        if divisor <= 1:
            entry.pop('raw_count', None)

        duties_data[duty][uid_str] = entry
        stamp_meta(duties_data, ctx,
            f"removeoverride {display_name} {duty}: removed override, restored count={new_count}")

        if not save_duties_json(duties_data):
            await ctx.send(embed=discord.Embed(title="❌ Save Failed",
                description="Failed to save locally. Check logs.", color=discord.Color.red()))
            return

        logger.info(
            f"✅ [ManualDuties] {ctx.author} removeoverride {display_name} ({user_id}) "
            f"{duty}: removed override, restored count={new_count}"
        )

        status = await ctx.send(embed=discord.Embed(title="⏳ Updating Staff Hub...",
            description=f"Removing override from **{display_name}** `{duty}`...",
            color=discord.Color.orange()))

        try:
            await push_to_github(duties_data)
            await status.edit(embed=discord.Embed(
                title="✅ Override Removed",
                description=(
                    f"**User:** {display_name}\n"
                    f"**Duty:** `{duty}`\n"
                    f"**Restored count:** `{new_count}`\n\n"
                    f"Their real scanned count will now show normally."
                ),
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            ).set_footer(text=f"By {ctx.author}"))
        except Exception as e:
            logger.error(f"❌ Staff Hub update failed in removeoverride: {e}")
            await status.edit(embed=discord.Embed(
                title="⚠️ Saved Locally — Staff Hub Update Failed",
                description=f"Saved locally but Staff Hub update failed.\nError: `{e}`",
                color=discord.Color.orange()))

    # ==================== >getduty ====================

    @commands.command(name='getduty')
    @commands.has_any_role('Management', '007', '+')
    async def get_duty(self, ctx, target: str):
        """
        Show a user's current duty counts, raw counts, and any active divisors.

        Usage: >getduty <@user|user_id>
        """
        user_id, display_name = await resolve_user(ctx, target)
        if not user_id:
            await ctx.send(embed=discord.Embed(title="❌ Invalid User",
                description="Please mention a user or provide their user ID.",
                color=discord.Color.red()))
            return

        uid_str     = str(user_id)
        duties_data = load_duties_json()
        lines       = []
        found_any   = False

        for duty in VALID_DUTIES:
            entry = duties_data.get(duty, {}).get(uid_str)
            if entry:
                count     = entry.get('count', 0)
                raw       = entry.get('raw_count')
                divisor   = entry.get('divisor', 1)
                override  = entry.get('is_override', False)
                found_any = True
                
                parts = [f"`{duty:<8}` — **{count}**"]
                
                if override and divisor > 1:
                    parts.append(f"*(raw: {raw} ÷ {divisor})* ✂️ 🔒 **(Override Active)**")
                elif override:
                    parts.append(f"*(raw: {raw})* 🔒 **(Override Active)**")
                elif divisor > 1:
                    parts.append(f"*(raw: {raw} ÷ {divisor})* ✂️")
                    
                lines.append(" ".join(parts))
            else:
                lines.append(f"`{duty:<8}` — *not in data*")

        meta         = duties_data.get('_meta', {})
        last_updated = meta.get('last_updated', 'Unknown')[:19].replace('T', ' ')

        embed = discord.Embed(
            title=f"📊 Duty Counts — {display_name}",
            description='\n'.join(lines),
            color=discord.Color.blue() if found_any else discord.Color.greyple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text=f"Last scan: {last_updated} UTC")
        await ctx.send(embed=embed)

    # ==================== >dutyinfo ====================

    @commands.command(name='dutyinfo')
    @commands.has_any_role('Management', '007', '+')
    async def duty_info(self, ctx):
        """List all manual duty commands and usage."""
        embed = discord.Embed(title="📋 Manual Duty Commands", color=discord.Color.blue())
        embed.add_field(name=">setduty", inline=False,
            value=(
                "Hard-set a user's duty count.\n"
                "`>setduty <user_id> <duty> <value>`\n"
                "`>setduty 123456789 req 42`"
            ))
        embed.add_field(name=">setdivisor", inline=False,
            value=(
                "Apply a penalty — real scanned count gets divided before showing on the leaderboard. "
                "Persists through every future scan automatically.\n"
                "`>setdivisor <user_id> <duty> <divisor>`\n"
                "`>setdivisor 123456789 req 2` *(halves their req count)*\n"
                "Divisor must be between **2** and **10**."
            ))
        embed.add_field(name=">removedivisor", inline=False,
            value=(
                "Remove a divisor and restore their real count.\n"
                "`>removedivisor <user_id> <duty>`\n"
                "`>removedivisor 123456789 req`"
            ))
        embed.add_field(name=">removeoverride", inline=False,
            value=(
                "Remove a manual override and restore their real count.\n"
                "`>removeoverride <user_id> <duty>`\n"
                "`>removeoverride 123456789 req`"
            ))
        embed.add_field(name=">getduty", inline=False,
            value=(
                "View counts for all 4 metrics. Shows raw count, divisor, and override flags if active.\n"
                "`>getduty <user_id>`"
            ))
        embed.add_field(name="Valid metric names", inline=False,
            value="`req`  `modlog`  `message`  `reviews`")
        await ctx.send(embed=embed)

    # ==================== Error handlers ====================

    @set_duty.error
    async def set_duty_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(title="❌ Missing Arguments",
                description="**Usage:** `>setduty <user_id> <duty> <value>`\nExample: `>setduty 123456789 req 42`",
                color=discord.Color.red()))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=discord.Embed(title="❌ Bad Argument",
                description="Value must be a whole number e.g. `42`.", color=discord.Color.red()))
        elif isinstance(error, commands.MissingAnyRole):
            await ctx.send(embed=discord.Embed(title="🔒 No Permission",
                description="Management, 007, or + role required.", color=discord.Color.red()))

    @set_divisor.error
    async def set_divisor_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(title="❌ Missing Arguments",
                description="**Usage:** `>setdivisor <user_id> <duty> <divisor>`\nExample: `>setdivisor 123456789 role 2`",
                color=discord.Color.red()))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=discord.Embed(title="❌ Bad Argument",
                description="Divisor must be a whole number between 2 and 10.", color=discord.Color.red()))
        elif isinstance(error, commands.MissingAnyRole):
            await ctx.send(embed=discord.Embed(title="🔒 No Permission",
                description="Management, 007, or + role required.", color=discord.Color.red()))

    @remove_divisor.error
    async def remove_divisor_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(title="❌ Missing Arguments",
                description="**Usage:** `>removedivisor <user_id> <duty>`\nExample: `>removedivisor 123456789 req`",
                color=discord.Color.red()))
        elif isinstance(error, commands.MissingAnyRole):
            await ctx.send(embed=discord.Embed(title="🔒 No Permission",
                description="Management, 007, or + role required.", color=discord.Color.red()))

    @remove_override.error
    async def remove_override_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(title="❌ Missing Arguments",
                description="**Usage:** `>removeoverride <user_id> <duty>`\nExample: `>removeoverride 123456789 req`",
                color=discord.Color.red()))
        elif isinstance(error, commands.MissingAnyRole):
            await ctx.send(embed=discord.Embed(title="🔒 No Permission",
                description="Management, 007, or + role required.", color=discord.Color.red()))

    @get_duty.error
    async def get_duty_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=discord.Embed(title="❌ Missing Argument",
                description="**Usage:** `>getduty <user_id>`", color=discord.Color.red()))
        elif isinstance(error, commands.MissingAnyRole):
            await ctx.send(embed=discord.Embed(title="🔒 No Permission",
                description="Management, 007, or + role required.", color=discord.Color.red()))


async def setup(bot):
    await bot.add_cog(ManualDuties(bot))
    logger.info("✅ ManualDuties cog loaded")