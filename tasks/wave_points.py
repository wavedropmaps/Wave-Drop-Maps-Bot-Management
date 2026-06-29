"""
Wave Points Task - tasks/wave_points.py
Hooks into the staff sheet pipeline and converts Rank Totals → Wave Points.
Every time the staff sheet is written, this task reads the rank_total for each
staff member and credits them at the rate of 10 Wave Points per 1 Rank Total.

Table created here:
    wave_points (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0,
                 last_rank_total INTEGER DEFAULT 0, last_updated TEXT)
"""

import discord
from discord.ext import tasks, commands
import logging
from datetime import datetime, timezone

import database

logger = logging.getLogger('discord')

STAFF_HUB_GUILD_ID = 1041450125391835186  # WAVE Drop Map Staff Hub

# ==================== DATABASE HELPERS ====================

async def init_wave_points_table():
    """Create the wave_points table if it doesn't already exist."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS wave_points (
                user_id         INTEGER PRIMARY KEY,
                points          INTEGER DEFAULT 0,
                last_rank_total INTEGER DEFAULT 0,
                last_updated    TEXT NOT NULL
            )
        ''')
        await db.commit()
    logger.info("✅ wave_points table initialised")


async def get_wave_points(user_id: int) -> int:
    """Return the current Wave Points balance for a user (0 if none)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT points FROM wave_points WHERE user_id = ?', (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def set_wave_points(user_id: int, points: int):
    """Overwrite a user's Wave Points balance."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT INTO wave_points (user_id, points, last_rank_total, last_updated)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                points       = excluded.points,
                last_updated = excluded.last_updated
        ''', (user_id, points, now))
        await db.commit()


async def add_wave_points(user_id: int, amount: int, bot=None, reason: str | None = None) -> int:
    """Add (or subtract) Wave Points and return the new balance."""
    current = await get_wave_points(user_id)
    new_total = current + amount
    await set_wave_points(user_id, new_total)

    # Wave-Logging dashboard event — all wave point changes flow through here
    # (set_wave_points + remove_wave_points both call add_wave_points).
    try:
        from core.global_logger import log_event as _wave_log_event
        details = {
            "change": amount,
            "balance_before": current,
            "balance_after": new_total,
        }
        if reason:
            details["reason"] = reason
        await _wave_log_event(
            category="wave_points",
            action="points_changed",
            target={"id": str(user_id)},
            details=details,
        )
    except Exception:
        pass  # logging must never break wp flow

    return new_total


async def remove_wave_points(user_id: int, amount: int, bot=None, reason: str | None = None) -> int:
    """Subtract Wave Points and return the new balance.
    Thin wrapper around add_wave_points with a negated amount — the caller
    is expected to verify balance first (see >buybond / >buylottery).
    `amount` should be positive; we negate it here. If the caller passes
    a negative number we still do the sensible thing (treat as magnitude).
    """
    return await add_wave_points(user_id, -abs(int(amount)), bot=bot, reason=reason)


async def get_wave_points_leaderboard(limit: int = 20) -> list:
    """Return top active (non-alumni) users sorted by Wave Points descending."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT user_id, points FROM wave_points WHERE left_at IS NULL ORDER BY points DESC LIMIT ?',
            (limit,)
        ) as cursor:
            return await cursor.fetchall()


# ==================== RANK TOTAL → WAVE POINTS CONVERSION ====================

PERFECT_RANK_TOTAL     = 100  # Must score exactly 100 to earn points
WAVE_POINTS_FOR_PERFECT = 10  # Reward for hitting 100 Rank Total


async def credit_wave_points_from_rank_total(user_id: int, rank_total: int, bot=None):
    """
    Called by the staff sheet task after each sheet write.
    Awards 10 Wave Points ONLY if the staff member scored exactly 100 Rank Total.
    Anything below 100 earns nothing.
    We store last_rank_total to avoid double-crediting if the sheet reruns.

    Args:
        user_id:    Discord user ID
        rank_total: The Rank Total value from the staff sheet (0-100)
        bot:        Bot instance — passed through to add_wave_points so the leaderboard auto-updates
    """
    try:
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT points, last_rank_total FROM wave_points WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()

        current_points  = row[0] if row else 0
        last_rank_total = row[1] if row else 0

        # Only award if this is a new/different rank_total (avoids re-crediting on reruns)
        if rank_total == last_rank_total and row is not None:
            logger.debug(f"ℹ️  Wave points already credited for user {user_id} (rank_total={rank_total})")
            return current_points

        # Update last_rank_total regardless of whether they earned points
        pool = await database.get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute('''
                INSERT INTO wave_points (user_id, points, last_rank_total, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    last_rank_total = excluded.last_rank_total,
                    last_updated    = excluded.last_updated
            ''', (user_id, current_points, rank_total, now))
            await db.commit()

        # Must hit exactly 100 to earn Wave Points
        if rank_total < PERFECT_RANK_TOTAL:
            logger.info(f"ℹ️  No Wave Points for user {user_id} — rank_total={rank_total} (needs 100)")
            return current_points

        # Use add_wave_points so the leaderboard auto-updates via bot
        earned    = WAVE_POINTS_FOR_PERFECT
        new_total = await add_wave_points(user_id, earned, bot=bot, reason="Perfect rank total (100)")

        logger.info(
            f"💎 Wave Points credited: user={user_id} rank_total={rank_total} "
            f"earned={earned} new_total={new_total}"
        )
        return new_total

    except Exception as e:
        logger.error(f"❌ Failed to credit wave points for user {user_id}: {e}")
        return 0


async def bulk_credit_wave_points(staff_records: list, bot=None):
    """
    Bulk version called by the staff sheet after a full sheet write.

    Args:
        staff_records: list of dicts with keys 'user_id' and 'rank_total'
        bot:           Bot instance — passed through so the leaderboard auto-updates on each credit
    """
    if not staff_records:
        return

    logger.info(f"🔄 Bulk-crediting Wave Points for {len(staff_records)} staff members...")
    for record in staff_records:
        await credit_wave_points_from_rank_total(
            record['user_id'],
            record['rank_total'],
            bot=bot
        )
    logger.info("✅ Bulk Wave Points credit complete")


# ==================== COG ====================

class WavePointsTask(commands.Cog):
    """
    Background cog for Wave Points.
    Exposes the init helper so main.py can call it on startup.
    The actual point-crediting is triggered from staff_sheet.py via
    bulk_credit_wave_points(), not from a timed loop.
    """

    def __init__(self, bot):
        self.bot = bot
        self._ready_sweep_done = False  # guard so on_ready only sweeps once

    async def cog_load(self):
        await init_wave_points_table()
        logger.info("✅ WavePointsTask cog loaded")
        # NOTE: leaderboard update + sweep are deferred to on_ready
        # so the guild cache is fully populated before we touch member data.

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready_sweep_done:
            return
        self._ready_sweep_done = True
        # Sweep for any users who left while the bot was offline
        await self._sweep_left_users()

    async def _sweep_left_users(self):
        """Remove wave_points rows for anyone no longer in the staff hub guild."""
        removed = await cleanup_wave_points_for_left_users(self.bot, [STAFF_HUB_GUILD_ID])
        if removed:
            logger.info(f"🧹 Startup sweep: archived {len(removed)} user(s) as wave_points alumni (left while offline)")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Mark wave_points row as alumni when a user leaves the staff hub guild (preserves balance for rejoin)."""
        if member.guild.id != STAFF_HUB_GUILD_ID:
            return
        now = datetime.now(timezone.utc).isoformat()
        pool = await database.get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'UPDATE wave_points SET left_at = ? WHERE user_id = ? AND left_at IS NULL',
                (now, member.id)
            )
            await db.commit()
        logger.info(f"🎓 Archived wave_points for {member} ({member.id}) as alumni — left guild {STAFF_HUB_GUILD_ID}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Restore wave_points alumni status when a former member rejoins the staff hub guild."""
        if member.guild.id != STAFF_HUB_GUILD_ID:
            return
        pool = await database.get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT points, left_at FROM wave_points WHERE user_id = ? AND left_at IS NOT NULL',
                (member.id,)
            ) as cursor:
                row = await cursor.fetchone()
            if row:
                await db.execute(
                    'UPDATE wave_points SET left_at = NULL WHERE user_id = ?',
                    (member.id,)
                )
                await db.commit()
                logger.info(
                    f"🔄 Restored {member} ({member.id}) wave_points alumni → active "
                    f"({row[0]} pts, left {row[1]})"
                )


async def setup(bot):
    await bot.add_cog(WavePointsTask(bot))


# ==================== LEFT-SERVER CLEANUP ====================

async def cleanup_wave_points_for_left_users(bot, source_guilds: list) -> list:
    """
    Startup sweep: marks wave_points rows as alumni for any active user who is
    no longer present in *any* of the supplied source guilds (e.g. they left
    while the bot was offline). Points are preserved so they restore on rejoin.

    Returns a list of user_ids that were archived.
    """
    present = set()
    for guild_id in source_guilds:
        guild = bot.get_guild(guild_id)
        if not guild:
            logger.warning(f"  ⚠️ Guild {guild_id} not found during wave_points cleanup")
            continue
        for member in guild.members:
            if not member.bot:
                present.add(member.id)

    logger.info(f"🧹 wave_points cleanup: {len(present)} users present across {len(source_guilds)} guild(s)")

    archived = []
    try:
        pool = await database.get_pool()
        now = datetime.now(timezone.utc).isoformat()
        async with pool.acquire() as db:
            async with db.execute("SELECT user_id FROM wave_points WHERE left_at IS NULL") as cur:
                tracked = [row[0] async for row in cur]

        gone = [uid for uid in tracked if uid not in present]

        if gone:
            async with pool.acquire() as db:
                for uid in gone:
                    await db.execute(
                        "UPDATE wave_points SET left_at = ? WHERE user_id = ? AND left_at IS NULL",
                        (now, uid)
                    )
                    logger.info(f"    🎓 Archived user {uid} in wave_points (left while offline)")
                await db.commit()
            archived = gone
            logger.info(f"  ✅ Archived {len(gone)} left-server user(s) in wave_points (alumni)")
        else:
            logger.info("  ✅ All wave_points users still present in at least one guild")

    except Exception as e:
        logger.error(f"  ❌ Failed wave_points left-server cleanup: {e}")

    return archived