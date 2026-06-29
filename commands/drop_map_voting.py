"""
Drop Map Voting — community-driven weekly voting on which Fortnite drop spots
get a drop map made next.

Flow:
- Members run /addvoting to submit a spot (name + description, image via DM)
- Cards live in a pinned forum thread with a ▲ vote button (live count)
- 1 submission per member at a time; 2 votes per member max
- Every Sunday at 00:00 UTC the top-voted spot wins:
    • Image + voters posted to the queue channel as Paid Priority
    • Winner announced in the leaderboard forum thread
    • All cards deleted, DB wiped — fresh start for the next week
- On bot startup the cycle catches up if a Sunday passed while the bot was down

Admin commands:
  /votingclear <@user>   — remove that member's submission + card
  /votingpick <spot>     — manually run the weekly cycle with this spot as winner
  /votingconfig          — show the current config
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import logging
import os
import re
import difflib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Tuple

import database

logger = logging.getLogger('discord')

# ============================================================================
# CONFIG  (edit here for channel/role/threshold tuning)
# ============================================================================

# The forum channel
DROP_MAP_VOTING_FORUM_CHANNEL_ID = 1507612863144001626
# The leaderboard thread (where voting cards and info message are posted)
DROP_MAP_VOTING_LEADERBOARD_THREAD_ID = 1508289287169511496
# The submissions thread (where members submit spots — holds the pinned Submit button)
DROP_MAP_VOTING_SUBMISSIONS_THREAD_ID = 1508030522746605690

# The Wave Logistics queue channel — the winning spot gets posted here every week
DROP_MAP_QUEUE_CHANNEL_ID = 1210837116649742396
# Guild that hosts the queue channel (for fetching member objects for mentions)
DROP_MAP_QUEUE_GUILD_ID   = 1405570493691596820

# The sticky message channel — where the voting info message is kept as the latest message
STICKY_MESSAGE_CHANNEL_ID = 1210837226884300820

# The Wave Logistics bot command channel — for sending >addmap commands
DROP_MAP_ADDMAP_COMMAND_CHANNEL_ID = 1493874248081739836

# Paid Priority role is looked up by name (same as existing systems)
PAID_PRIORITY_ROLE_NAME = "Paid Priority"

# Weekly Voter role — awarded to anyone who votes that week
WEEKLY_VOTER_ROLE_ID = 1507968116309753940

# Where downloaded spot images get saved
DROP_MAP_VOTING_IMAGES_DIR = Path("assets/drop_map_voting_images")

DM_IMAGE_TIMEOUT_SECONDS = 300       # 5 minutes for the submitter to DM the image
FUZZY_MATCH_THRESHOLD    = 0.75      # similarity ratio that counts as a duplicate
MAX_VOTES_PER_MEMBER     = 2

ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGE_BYTES    = 8 * 1024 * 1024  # 8 MB

VOTE_BUTTON_PREFIX = "dmv_vote_"   # custom_id prefix → dmv_vote_<spot_id>
SUBMIT_BUTTON_CUSTOM_ID = "dmv_submit_button"   # persistent pinned "Submit Drop Spot" button

# Weekly cycle: every Sunday at 00:00 UTC
CYCLE_WEEKDAY      = 6   # Monday=0 … Sunday=6
CYCLE_HOUR_UTC     = 0
CYCLE_MINUTE_UTC   = 0


# ============================================================================
# DB INIT
# ============================================================================

async def _ensure_tables():
    """Create tables if they don't exist. Idempotent."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        # Config table for voting rewards per guild
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_config (
                guild_id              INTEGER PRIMARY KEY,
                rewards_enabled       BOOLEAN DEFAULT 0,
                sticky_message_enabled BOOLEAN DEFAULT 1,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Migrations: add new columns if they don't exist
        try:
            async with db.execute("PRAGMA table_info(drop_map_voting_config)") as cursor:
                cols = {row["name"] for row in await cursor.fetchall()}
            if "sticky_message_enabled" not in cols:
                await db.execute("ALTER TABLE drop_map_voting_config ADD COLUMN sticky_message_enabled BOOLEAN DEFAULT 1")
                logger.info("[DropMapVoting] Added sticky_message_enabled column to config table")
            if "addvoting_enabled" not in cols:
                await db.execute("ALTER TABLE drop_map_voting_config ADD COLUMN addvoting_enabled BOOLEAN DEFAULT 1")
                logger.info("[DropMapVoting] Added addvoting_enabled column to config table")
        except Exception as e:
            logger.warning(f"[DropMapVoting] Could not run config table migrations: {e}")
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_spots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                spot_name       TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                description     TEXT,
                image_path      TEXT,
                submitter_id    INTEGER NOT NULL UNIQUE,
                submitter_name  TEXT NOT NULL,
                message_id      INTEGER,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_dmv_spots_normalized
            ON drop_map_voting_spots(normalized_name)
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_votes (
                user_id    INTEGER NOT NULL,
                spot_id    INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, spot_id),
                FOREIGN KEY (spot_id) REFERENCES drop_map_voting_spots(id) ON DELETE CASCADE
            )
        ''')
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_dmv_votes_spot
            ON drop_map_voting_votes(spot_id)
        ''')
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_dmv_votes_user
            ON drop_map_voting_votes(user_id)
        ''')
        # Single-row table tracking when the cycle last ran
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_cycle (
                id               INTEGER PRIMARY KEY CHECK (id = 1),
                last_cycle_end   TIMESTAMP,
                cycles_completed INTEGER DEFAULT 0
            )
        ''')
        await db.execute(
            "INSERT OR IGNORE INTO drop_map_voting_cycle (id, last_cycle_end, cycles_completed) "
            "VALUES (1, NULL, 0)"
        )

        # Single-row table tracking the sticky message ID in the queue channel
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_sticky_message (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                message_id      INTEGER,
                channel_id      INTEGER,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Single-row table tracking the info sticky message ID in the leaderboard thread
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_info_sticky (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                message_id      INTEGER,
                thread_id       INTEGER,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute(
            "INSERT OR IGNORE INTO drop_map_voting_info_sticky (id, message_id, thread_id) "
            "VALUES (1, NULL, NULL)"
        )
        # Single-row table tracking the pinned Submit button message in the submissions thread
        await db.execute('''
            CREATE TABLE IF NOT EXISTS drop_map_voting_submit_button (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                message_id      INTEGER,
                thread_id       INTEGER,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute(
            "INSERT OR IGNORE INTO drop_map_voting_submit_button (id, message_id, thread_id) "
            "VALUES (1, NULL, NULL)"
        )
        await db.execute(
            "INSERT OR IGNORE INTO drop_map_voting_sticky_message (id, message_id, channel_id) "
            "VALUES (1, NULL, NULL)"
        )

        # Migration: drop the old loot_tier/drop_heat/reason columns if they exist
        # (SQLite < 3.35 can't DROP COLUMN — rebuild the table if old schema is present)
        await _migrate_old_schema(db)

        await db.commit()


async def _migrate_old_schema(db):
    """If the spots table still has the old columns, rebuild it."""
    async with db.execute("PRAGMA table_info(drop_map_voting_spots)") as cursor:
        cols = {row["name"] for row in await cursor.fetchall()}
    old_cols = {"reason", "loot_tier", "drop_heat"}
    if not (old_cols & cols):
        return
    logger.info("[DropMapVoting] Migrating spots table to new schema (dropping reason/loot_tier/drop_heat)")
    await db.execute('''
        CREATE TABLE drop_map_voting_spots_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            spot_name       TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            description     TEXT,
            image_path      TEXT,
            submitter_id    INTEGER NOT NULL UNIQUE,
            submitter_name  TEXT NOT NULL,
            message_id      INTEGER,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Old `reason` maps to new `description`
    desc_col = "reason" if "reason" in cols else "description"
    await db.execute(f'''
        INSERT INTO drop_map_voting_spots_new
        (id, spot_name, normalized_name, description, image_path,
         submitter_id, submitter_name, message_id, created_at)
        SELECT id, spot_name, normalized_name, {desc_col}, image_path,
               submitter_id, submitter_name, message_id, created_at
        FROM drop_map_voting_spots
    ''')
    await db.execute("DROP TABLE drop_map_voting_spots")
    await db.execute("ALTER TABLE drop_map_voting_spots_new RENAME TO drop_map_voting_spots")
    await db.execute('''
        CREATE INDEX IF NOT EXISTS idx_dmv_spots_normalized
        ON drop_map_voting_spots(normalized_name)
    ''')


# ============================================================================
# DB HELPERS
# ============================================================================

def _normalize(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


async def _get_spot_by_submitter(user_id: int) -> Optional[dict]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT * FROM drop_map_voting_spots WHERE submitter_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return database.row_to_dict(row) if row else None


async def _get_spot_by_id(spot_id: int) -> Optional[dict]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT * FROM drop_map_voting_spots WHERE id = ?", (spot_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return database.row_to_dict(row) if row else None


async def _get_spot_by_name(name: str) -> Optional[dict]:
    """Case-insensitive exact match by spot_name."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT * FROM drop_map_voting_spots WHERE LOWER(spot_name) = LOWER(?)",
            (name,)
        ) as cursor:
            row = await cursor.fetchone()
            return database.row_to_dict(row) if row else None


async def _all_spots_ordered_by_votes() -> List[dict]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute('''
            SELECT s.*, COALESCE(v.vote_count, 0) AS vote_count
            FROM drop_map_voting_spots s
            LEFT JOIN (
                SELECT spot_id, COUNT(*) AS vote_count
                FROM drop_map_voting_votes
                GROUP BY spot_id
            ) v ON v.spot_id = s.id
            ORDER BY vote_count DESC, s.created_at ASC
        ''') as cursor:
            rows = await cursor.fetchall()
            return [database.row_to_dict(r) for r in rows]


async def _all_normalized_names() -> List[Tuple[int, str, str]]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT id, spot_name, normalized_name FROM drop_map_voting_spots"
        ) as cursor:
            rows = await cursor.fetchall()
            return [(r["id"], r["spot_name"], r["normalized_name"]) for r in rows]


async def _find_duplicate(new_name: str) -> Optional[dict]:
    new_norm = _normalize(new_name)
    if not new_norm:
        return None
    existing = await _all_normalized_names()
    for spot_id, spot_name, norm in existing:
        ratio = difflib.SequenceMatcher(None, new_norm, norm).ratio()
        if ratio >= FUZZY_MATCH_THRESHOLD:
            return {"id": spot_id, "spot_name": spot_name}
    return None


async def _insert_spot(
    spot_name: str, description: str, submitter_id: int, submitter_name: str
) -> int:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        cursor = await db.execute('''
            INSERT INTO drop_map_voting_spots
            (spot_name, normalized_name, description, submitter_id, submitter_name)
            VALUES (?, ?, ?, ?, ?)
        ''', (spot_name, _normalize(spot_name), description or None,
              submitter_id, submitter_name))
        await db.commit()
        return cursor.lastrowid


async def _set_spot_message_id(spot_id: int, message_id: int):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE drop_map_voting_spots SET message_id = ? WHERE id = ?",
            (message_id, spot_id)
        )
        await db.commit()


async def _set_spot_image_path(spot_id: int, image_path: str):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE drop_map_voting_spots SET image_path = ? WHERE id = ?",
            (image_path, spot_id)
        )
        await db.commit()


def _delete_spot_image_files(spot_id: int):
    """Remove the on-disk image(s) for a spot ({spot_id}.<ext>). Best-effort —
    a missing file or unlink error must never break the DB operation."""
    try:
        for f in DROP_MAP_VOTING_IMAGES_DIR.glob(f"{spot_id}.*"):
            try:
                f.unlink()
            except OSError as e:
                logger.warning(f"[DropMapVoting] Could not delete image {f}: {e}")
    except Exception as e:
        logger.warning(f"[DropMapVoting] Image cleanup failed for spot {spot_id}: {e}")


def _wipe_all_image_files():
    """Remove every file in the voting images dir. Best-effort; keeps the dir."""
    try:
        if DROP_MAP_VOTING_IMAGES_DIR.exists():
            for f in DROP_MAP_VOTING_IMAGES_DIR.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError as e:
                        logger.warning(f"[DropMapVoting] Could not delete image {f}: {e}")
    except Exception as e:
        logger.warning(f"[DropMapVoting] Bulk image cleanup failed: {e}")


async def _delete_spot(spot_id: int):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM drop_map_voting_spots WHERE id = ?", (spot_id,))
        # votes cascade-delete via FK
        await db.commit()
    # Delete the image only after the DB row is gone, so a crash can't leave a
    # live row pointing at a missing file.
    _delete_spot_image_files(spot_id)


async def _wipe_all_spots():
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute("DELETE FROM drop_map_voting_votes")
        await db.execute("DELETE FROM drop_map_voting_spots")
        await db.commit()
    # DB wiped — now drop the orphaned image files so the dir doesn't grow weekly.
    _wipe_all_image_files()


async def _user_vote_count(user_id: int) -> int:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT COUNT(*) AS c FROM drop_map_voting_votes WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["c"] if row else 0


async def _user_has_voted_on(user_id: int, spot_id: int) -> bool:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT 1 FROM drop_map_voting_votes WHERE user_id = ? AND spot_id = ?",
            (user_id, spot_id)
        ) as cursor:
            return (await cursor.fetchone()) is not None


async def _add_vote(user_id: int, spot_id: int) -> bool:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        try:
            await db.execute(
                "INSERT INTO drop_map_voting_votes (user_id, spot_id) VALUES (?, ?)",
                (user_id, spot_id)
            )
            await db.commit()
            return True
        except Exception:
            return False


async def _remove_vote(user_id: int, spot_id: int):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "DELETE FROM drop_map_voting_votes WHERE user_id = ? AND spot_id = ?",
            (user_id, spot_id)
        )
        await db.commit()


async def _vote_count_for_spot(spot_id: int) -> int:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT COUNT(*) AS c FROM drop_map_voting_votes WHERE spot_id = ?",
            (spot_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["c"] if row else 0


async def _total_votes_this_week() -> int:
    """Get total votes cast this week (all spots combined)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT COUNT(*) AS c FROM drop_map_voting_votes"
        ) as cursor:
            row = await cursor.fetchone()
            return row["c"] if row else 0


async def _voters_for_spot(spot_id: int) -> List[int]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT user_id FROM drop_map_voting_votes WHERE spot_id = ? ORDER BY created_at ASC",
            (spot_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r["user_id"] for r in rows]


async def _get_last_cycle_end() -> Optional[datetime]:
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT last_cycle_end FROM drop_map_voting_cycle WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            if not row or not row["last_cycle_end"]:
                return None
            value = row["last_cycle_end"]
            if isinstance(value, str):
                # SQLite returns timestamp as string
                try:
                    dt = datetime.fromisoformat(value.replace(" ", "T"))
                except ValueError:
                    return None
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            return value


async def _set_last_cycle_end(when: datetime):
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE drop_map_voting_cycle SET last_cycle_end = ?, "
            "cycles_completed = cycles_completed + 1 WHERE id = 1",
            (when.isoformat(),)
        )
        await db.commit()


async def _is_voting_rewards_enabled(guild_id: int) -> bool:
    """Check if voting rewards are enabled for this guild (default: False)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT rewards_enabled FROM drop_map_voting_config WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return bool(row["rewards_enabled"]) if row else False


async def _toggle_voting_rewards(guild_id: int, enabled: bool):
    """Enable or disable voting rewards for this guild."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT OR REPLACE INTO drop_map_voting_config (guild_id, rewards_enabled, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (guild_id, int(enabled))
        )
        await db.commit()


async def _get_sticky_message_id() -> Optional[int]:
    """Get the stored sticky message ID."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT message_id FROM drop_map_voting_sticky_message WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row["message_id"] if row else None


async def _set_sticky_message_id(message_id: int):
    """Update the sticky message ID."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE drop_map_voting_sticky_message SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (message_id,)
        )
        await db.commit()


async def _get_info_sticky_message_id() -> Optional[int]:
    """Get the stored info sticky message ID (in leaderboard thread)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT message_id FROM drop_map_voting_info_sticky WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row["message_id"] if row else None


async def _set_info_sticky_message_id(message_id: int):
    """Update the info sticky message ID."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE drop_map_voting_info_sticky SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (message_id,)
        )
        await db.commit()


async def _get_submit_button_message_id() -> Optional[int]:
    """Get the stored Submit-button message ID (in submissions thread)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT message_id FROM drop_map_voting_submit_button WHERE id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row["message_id"] if row else None


async def _set_submit_button_message_id(message_id: int):
    """Update the Submit-button message ID."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE drop_map_voting_submit_button SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (message_id,)
        )
        await db.commit()


async def _is_sticky_message_enabled(guild_id: int) -> bool:
    """Check if sticky message is enabled for this guild."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT sticky_message_enabled FROM drop_map_voting_config WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            # Default to enabled if no config exists
            return row["sticky_message_enabled"] if row else True


async def _set_sticky_message_enabled(guild_id: int, enabled: bool):
    """Set whether sticky message is enabled for this guild."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT OR REPLACE INTO drop_map_voting_config (guild_id, sticky_message_enabled, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP)",
            (guild_id, int(enabled))
        )
        await db.commit()


async def _is_addvoting_enabled(guild_id: int) -> bool:
    """Check if /addvoting is enabled for this guild (default: True)."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT addvoting_enabled FROM drop_map_voting_config WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            # Default to enabled if no config row exists yet
            if row is None or row["addvoting_enabled"] is None:
                return True
            return bool(row["addvoting_enabled"])


async def _set_addvoting_enabled(guild_id: int, enabled: bool):
    """Enable or disable /addvoting for this guild."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO drop_map_voting_config (guild_id, addvoting_enabled, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(guild_id) DO UPDATE SET addvoting_enabled = excluded.addvoting_enabled, "
            "updated_at = excluded.updated_at",
            (guild_id, int(enabled))
        )
        await db.commit()


# ============================================================================
# WEEKLY CYCLE TIMING
# ============================================================================

def _next_cycle_end(after: datetime) -> datetime:
    """Return the next Sunday-00:00-UTC strictly after `after` (UTC)."""
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    after_utc = after.astimezone(timezone.utc)
    # weekday: Mon=0 … Sun=6
    days_ahead = (CYCLE_WEEKDAY - after_utc.weekday()) % 7
    candidate = after_utc.replace(
        hour=CYCLE_HOUR_UTC, minute=CYCLE_MINUTE_UTC, second=0, microsecond=0
    ) + timedelta(days=days_ahead)
    if candidate <= after_utc:
        candidate += timedelta(days=7)
    return candidate


def _previous_cycle_end(before: datetime) -> datetime:
    """Return the most recent Sunday-00:00-UTC at or before `before` (UTC)."""
    if before.tzinfo is None:
        before = before.replace(tzinfo=timezone.utc)
    before_utc = before.astimezone(timezone.utc)
    days_back = (before_utc.weekday() - CYCLE_WEEKDAY) % 7
    candidate = before_utc.replace(
        hour=CYCLE_HOUR_UTC, minute=CYCLE_MINUTE_UTC, second=0, microsecond=0
    ) - timedelta(days=days_back)
    if candidate > before_utc:
        candidate -= timedelta(days=7)
    return candidate


# ============================================================================
# EMBED BUILDERS
# ============================================================================

RANK_DECORATION = {
    1: ("🥇", 0xFFD700),  # gold
    2: ("🥈", 0xC0C0C0),  # silver
    3: ("🥉", 0xCD7F32),  # bronze
}
DEFAULT_RANK_COLOR = 0x5865F2


def _rank_decoration(rank: int) -> Tuple[str, int]:
    return RANK_DECORATION.get(rank, ("🗺️", DEFAULT_RANK_COLOR))


def _build_card_embed(
    spot: dict, rank: int, vote_count: int, submitter_avatar_url: Optional[str] = None
) -> discord.Embed:
    """Big banner image + bold rank trophy style."""
    medal, color = _rank_decoration(rank)
    safe_name    = discord.utils.escape_markdown(spot["spot_name"])

    embed = discord.Embed(
        title=f"{medal}  #{rank}   {safe_name}",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    if submitter_avatar_url:
        embed.set_author(
            name=f"Submitted by {spot['submitter_name']}",
            icon_url=submitter_avatar_url,
        )
    else:
        embed.set_author(name=f"Submitted by {spot['submitter_name']}")

    # Description as a dedicated field
    description = spot.get("description") or "*No description provided.*"
    embed.add_field(
        name="📝 Description",
        value=description,
        inline=False,
    )

    # Vote count (no flame bar — vote count is shown on the ▲ button)
    embed.add_field(
        name=f"Votes  ·  {vote_count}",
        value="*be the first to vote*" if vote_count == 0 else "​",
        inline=False,
    )

    if spot.get("image_path"):
        filename = os.path.basename(spot["image_path"])
        embed.set_image(url=f"attachment://{filename}")
    else:
        embed.add_field(
            name="📸 Image",
            value="*Pending — submitter was DMed*",
            inline=False,
        )

    embed.set_footer(text="Top voted spot wins every Sunday · 00:00 UTC")
    return embed


def _vote_bar(count: int) -> str:
    if count <= 0:
        return ""
    # Cap visual representation at 25 flames so cards don't get out of hand
    capped = min(count, 25)
    return "🔥" * capped + ("…" if count > 25 else "")


def _build_winner_announcement_embed(spot: dict, vote_count: int, voter_ids: List[int], total_votes: int = 0) -> discord.Embed:
    """Embed posted in the leaderboard thread when a winner is picked."""
    embed = discord.Embed(
        title=f"🏆 Weekly Winner: {discord.utils.escape_markdown(spot['spot_name'])}",
        description=(
            f"With **{vote_count}** vote{'s' if vote_count != 1 else ''}, "
            f"**{spot['spot_name']}** has been added to the drop map queue with "
            f"**Paid Priority**.\n\n"
            f"{spot.get('description') or ''}"
        ),
        color=0xFFD700,
        timestamp=datetime.now(timezone.utc),
    )

    # Vote bar showing voting power
    bar = _vote_bar(vote_count)
    embed.add_field(
        name="🔥 Voting Power",
        value=bar if bar else "1 vote",
        inline=True,
    )

    # Weekly voting stats
    if total_votes > 0:
        percentage = round((vote_count / total_votes) * 100, 1)
        embed.add_field(
            name="📊 Weekly Stats",
            value=f"{vote_count} of {total_votes} votes ({percentage}%)",
            inline=True,
        )

    if voter_ids:
        mentions = " ".join(f"<@{uid}>" for uid in voter_ids[:20])
        more = f" + {len(voter_ids) - 20} more" if len(voter_ids) > 20 else ""
        embed.add_field(
            name="🗳️ Voters credited as requesters",
            value=mentions + more,
            inline=False,
        )
    embed.set_footer(
        text="A fresh week of voting starts now. Run /addvoting to submit your spot."
    )
    if spot.get("image_path"):
        filename = os.path.basename(spot["image_path"])
        embed.set_image(url=f"attachment://{filename}")
    return embed


def _build_queue_field_value(voter_ids: List[int], description: str, paid_priority_role_id: Optional[int]) -> str:
    """Match the Wave Logistics Bot queue embed format that tasks/map_request.py parses."""
    lines = []
    if voter_ids:
        mentions = " ".join(f"<@{uid}>" for uid in voter_ids)
    else:
        mentions = "*(no voters)*"
    lines.append(f"👥 **Requested by:** {mentions}")

    if paid_priority_role_id:
        lines.append(
            f"⭐ **Priority:** Top Level Priority Ranking\n"
            f"- (<@&{paid_priority_role_id}>)"
        )
    else:
        lines.append(f"⭐ **Priority:** Top Level Priority Ranking")

    if description:
        lines.append(f"📝 **Description:** {description}")
    return "\n".join(lines)


# ============================================================================
# UI VIEWS
# ============================================================================

class EntryButtonView(discord.ui.View):
    """Sent in response to /addvoting. One button → opens the submission modal."""

    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This submission button isn't for you. Run `/addvoting` yourself.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="📝 Submit Drop Spot", style=discord.ButtonStyle.blurple)
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = await _get_spot_by_submitter(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                f"❌ You've already submitted **{existing['spot_name']}** this cycle. "
                f"Wait until next Sunday's reset (or it winning) before submitting again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(SubmitModal())


class SubmitButtonView(discord.ui.View):
    """Persistent view for the pinned 'Submit Drop Spot' message in the submissions
    thread. Unlike EntryButtonView, this has NO author check — anyone can click it,
    and it survives bot restarts (timeout=None + fixed custom_id)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📝 Submit Drop Spot",
        style=discord.ButtonStyle.blurple,
        custom_id=SUBMIT_BUTTON_CUSTOM_ID,
    )
    async def submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Respect the per-guild enable toggle (same as /addvoting)
        guild_id = interaction.guild_id
        if guild_id and not await _is_addvoting_enabled(guild_id):
            await interaction.response.send_message(
                "❌ Drop map voting isn't enabled right now.", ephemeral=True
            )
            return

        existing = await _get_spot_by_submitter(interaction.user.id)
        if existing:
            await interaction.response.send_message(
                f"❌ You've already submitted **{existing['spot_name']}** this cycle. "
                f"Wait until next Sunday's reset (or it winning) before submitting again.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(SubmitModal())


class SubmitModal(discord.ui.Modal, title="🗺️ Submit a Drop Spot"):
    spot_name = discord.ui.TextInput(
        label="Spot Name",
        placeholder="e.g. Tilted Towers",
        min_length=2,
        max_length=80,
        required=True,
        style=discord.TextStyle.short,
    )
    description = discord.ui.TextInput(
        label="Description of the Place",
        placeholder="What is this drop spot? Where is it? Why is it good?",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        spot_name   = self.spot_name.value.strip()
        description = (self.description.value or "").strip()
        user        = interaction.user

        existing = await _get_spot_by_submitter(user.id)
        if existing:
            await interaction.response.send_message(
                f"❌ You've already submitted **{existing['spot_name']}** this cycle.",
                ephemeral=True,
            )
            return

        dup = await _find_duplicate(spot_name)
        if dup:
            await interaction.response.send_message(
                f"❌ **{dup['spot_name']}** is already on the leaderboard. "
                f"Go vote on it instead!",
                ephemeral=True,
            )
            return

        spot_id = await _insert_spot(spot_name, description, user.id, str(user))

        cog: "DropMapVoting" = interaction.client.get_cog("DropMapVoting")
        if cog is None:
            await interaction.response.send_message(
                "⚠️ Bot is not ready. Try again in a moment.", ephemeral=True
            )
            return

        try:
            await cog.post_new_card(spot_id)
        except Exception as e:
            logger.error(f"[DropMapVoting] Failed to post card for spot {spot_id}: {e}")
            await interaction.response.send_message(
                "⚠️ Saved your submission, but failed to post the card. Ping a mod.",
                ephemeral=True,
            )
            return

        await cog.refresh_ranks(debounce=True)

        try:
            await interaction.response.send_message(
                f"✅ Submitted **{spot_name}**! Check your DMs — reply with an image "
                f"of the spot in the next {DM_IMAGE_TIMEOUT_SECONDS // 60} minutes, "
                f"or type `skip`.",
                ephemeral=True,
            )
        except Exception:
            pass

        interaction.client.loop.create_task(cog.collect_image_via_dm(user, spot_id))


class VoteButtonView(discord.ui.View):
    """Persistent view carrying the ▲N vote button for a single spot."""

    def __init__(self, spot_id: int, vote_count: int):
        super().__init__(timeout=None)
        self.spot_id = spot_id
        # Style: gray when 0 votes, blurple otherwise
        style = discord.ButtonStyle.gray if vote_count == 0 else discord.ButtonStyle.blurple
        button = discord.ui.Button(
            label=f"▲ {vote_count}",
            style=style,
            custom_id=f"{VOTE_BUTTON_PREFIX}{spot_id}",
        )
        button.callback = self._on_vote
        self.add_item(button)

    async def _on_vote(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        spot_id = self.spot_id

        logger.info(f"[DropMapVoting] Vote button clicked by {interaction.user} (ID: {user_id}) on spot #{spot_id}")

        # Confirm the spot still exists (could have been wiped by a cycle reset)
        spot = await _get_spot_by_id(spot_id)
        if spot is None:
            logger.warning(f"[DropMapVoting] ⚠️ Spot #{spot_id} not found (cycle may have reset)")
            await interaction.response.send_message(
                "⚠️ This spot is no longer in the voting (the cycle may have just reset).",
                ephemeral=True,
            )
            return

        already_voted = await _user_has_voted_on(user_id, spot_id)
        if already_voted:
            await _remove_vote(user_id, spot_id)
            action = "removed"
            logger.info(f"[DropMapVoting] Vote removed: {interaction.user} on {spot['spot_name']}")
        else:
            current = await _user_vote_count(user_id)
            if current >= MAX_VOTES_PER_MEMBER:
                logger.info(f"[DropMapVoting] ℹ️ {interaction.user} already has {current} votes (max: {MAX_VOTES_PER_MEMBER})")
                await interaction.response.send_message(
                    f"❌ You've used both your votes ({MAX_VOTES_PER_MEMBER}). "
                    f"Click ▲ on a spot you've already voted on to free a slot.",
                    ephemeral=True,
                )
                return
            inserted = await _add_vote(user_id, spot_id)
            if not inserted:
                logger.warning(f"[DropMapVoting] ⚠️ Vote insertion failed for {interaction.user} on spot #{spot_id}")
                await interaction.response.send_message(
                    "⚠️ Vote already counted.", ephemeral=True
                )
                return
            action = "added"
            logger.info(f"[DropMapVoting] Vote added: {interaction.user} on {spot['spot_name']}")

            # Award Weekly Voter role when someone votes (if enabled for this guild)
            cog: "DropMapVoting" = interaction.client.get_cog("DropMapVoting")
            if cog and interaction.guild:
                await cog._award_weekly_voter_role(interaction.user, interaction.guild.id)

            # Send confirmation DM to the voter
            if cog and interaction.guild:
                votes_remaining = MAX_VOTES_PER_MEMBER - await _user_vote_count(user_id)
                asyncio.create_task(
                    cog._send_vote_confirmation_dm(
                        interaction.user, spot, interaction.guild.id, votes_remaining
                    )
                )

        cog: "DropMapVoting" = interaction.client.get_cog("DropMapVoting")
        if cog:
            await cog.refresh_ranks(debounce=True)

        try:
            await interaction.response.send_message(
                f"✅ Vote {action}. {await _user_vote_count(user_id)}/{MAX_VOTES_PER_MEMBER} votes used.",
                ephemeral=True,
            )
        except Exception:
            pass


# ============================================================================
# COG
# ============================================================================

class DropMapVoting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._refresh_lock = asyncio.Lock()
        self._cycle_lock   = asyncio.Lock()
        self._sticky_post_lock = asyncio.Lock()   # prevents concurrent sticky reposts
        self._submit_button_lock = asyncio.Lock()  # prevents concurrent Submit-button reposts
        self._catch_up_done = False
        self._sticky_message_posted = False
        self._sticky_check_pending = False   # debounce: only one check task at a time
        self._info_check_pending   = False   # debounce: only one info-check task at a time
        self._refresh_pending = False        # debounce: skip queued refresh if one already waiting

    async def cog_load(self):
        logger.info("[DropMapVoting] ========== STARTUP ==========")
        logger.info("[DropMapVoting] Starting cog load...")

        try:
            await _ensure_tables()
            logger.info("[DropMapVoting] ✅ Database tables ensured")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to ensure tables: {e}")
            return

        try:
            DROP_MAP_VOTING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"[DropMapVoting] ✅ Images directory ready: {DROP_MAP_VOTING_IMAGES_DIR}")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to create images dir: {e}")

        try:
            spots = await _all_spots_ordered_by_votes()
            logger.info(f"[DropMapVoting] ✅ Loaded {len(spots)} existing spots from database")
            for spot in spots:
                self.bot.add_view(VoteButtonView(spot["id"], spot["vote_count"]))
                logger.debug(f"[DropMapVoting]   - Spot #{spot['id']}: {spot['spot_name']} ({spot['vote_count']} votes)")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to load spots: {e}")

        # Register the persistent Submit-button view so the pinned button keeps
        # working across restarts (anyone can click it — no per-message author check)
        try:
            self.bot.add_view(SubmitButtonView())
            logger.info("[DropMapVoting] ✅ Submit-button persistent view registered")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to register Submit-button view: {e}")

        # Start the periodic info message task (runs every 5 min, retries on failure)
        try:
            if not self.info_message_task.is_running():
                self.info_message_task.start()
                logger.info("[DropMapVoting] ✅ Info message task started (will run every 5 min)")
            else:
                logger.info("[DropMapVoting] ℹ️ Info message task already running")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to start info message task: {e}")

        # Sticky message will be posted on bot ready via on_ready() handler

        # Start the cycle scheduler (runs every hour)
        try:
            if not self.cycle_scheduler.is_running():
                self.cycle_scheduler.start()
                logger.info("[DropMapVoting] ✅ Cycle scheduler started")
            else:
                logger.info("[DropMapVoting] ℹ️ Cycle scheduler already running")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to start scheduler: {e}")

        logger.info("[DropMapVoting] ========== STARTUP COMPLETE ==========\n")

    def cog_unload(self):
        if self.cycle_scheduler.is_running():
            self.cycle_scheduler.cancel()
        if self.info_message_task.is_running():
            self.info_message_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._sticky_message_posted:
            self._sticky_message_posted = True
            try:
                logger.info("[DropMapVoting] Bot ready, posting sticky message to queue channel...")
                await self._post_sticky_message()
                logger.info("[DropMapVoting] ✅ Sticky message posted")
            except Exception as e:
                logger.error(f"[DropMapVoting] ❌ Failed to post sticky message: {e}")

            try:
                logger.info("[DropMapVoting] Ensuring pinned Submit button in submissions thread...")
                await self._ensure_submit_button_pinned()
                logger.info("[DropMapVoting] ✅ Submit button ensured")
            except Exception as e:
                logger.error(f"[DropMapVoting] ❌ Failed to ensure Submit button: {e}")

    @app_commands.command(name="addvoting", description="Submit a drop spot for the weekly vote")
    async def addvoting(self, interaction: discord.Interaction):
        logger.info(f"[DropMapVoting] /addvoting command started by {interaction.user} (ID: {interaction.user.id})")

        # Check if voting is enabled for this guild
        guild_id = interaction.guild_id
        if guild_id and not await _is_addvoting_enabled(guild_id):
            await interaction.response.send_message(
                "❌ Drop map voting isn't enabled in this server.",
                ephemeral=True,
            )
            return

        existing = await _get_spot_by_submitter(interaction.user.id)
        if existing:
            logger.info(f"[DropMapVoting] ℹ️ {interaction.user} already has submission: {existing['spot_name']}")
            await interaction.response.send_message(
                f"❌ You've already submitted **{existing['spot_name']}** this cycle. "
                f"Wait for Sunday's reset (or your map to win) before submitting another.",
                ephemeral=True,
            )
            return

        logger.info(f"[DropMapVoting] ✅ {interaction.user} can submit (no existing submission)")

        embed = discord.Embed(
            title="🗺️ Submit a Drop Spot",
            description=(
                "Click the button below to open the submission form.\n\n"
                "**Rules:**\n"
                "• 1 submission per member at a time\n"
                "• The top voted spot each week gets added to the queue with Paid Priority\n"
                f"• Vote for other maps in <#{DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}>\n"
                "• You'll be DMed afterwards to send an image"
            ),
            color=0x5865F2,
        )
        await interaction.response.send_message(
            embed=embed,
            view=EntryButtonView(interaction.user.id),
        )

    # ──────────── Admin Commands ────────────

    @commands.command(name="VotingClear")
    @commands.has_permissions(administrator=True)
    async def voting_clear(self, ctx: commands.Context, member: discord.Member):
        """Admin: clear a member's submission from the voting system."""
        spot = await _get_spot_by_submitter(member.id)
        if not spot:
            await ctx.reply(f"ℹ️ {member.mention} has no active submission.", mention_author=False)
            return

        # Delete their card from the thread
        thread = await self.get_leaderboard_thread()
        if thread and spot.get("message_id"):
            try:
                msg = await thread.fetch_message(spot["message_id"])
                await msg.delete()
            except Exception as e:
                logger.warning(f"[DropMapVoting] Could not delete card on clear: {e}")

        await _delete_spot(spot["id"])
        await self.refresh_ranks()
        await ctx.reply(
            f"🗑️ Cleared **{spot['spot_name']}** (submitted by {member.mention}).",
            mention_author=False,
        )

    @commands.command(name="VotingPick")
    @commands.has_permissions(administrator=True)
    async def voting_pick(self, ctx: commands.Context, *, spot_name: str):
        """Admin: manually pick a winner now. Runs the full weekly cycle."""
        spot = await _get_spot_by_name(spot_name)
        if not spot:
            await ctx.reply(
                f"❌ No spot named **{spot_name}** found. Use the exact name shown on the card.",
                mention_author=False,
            )
            return

        await ctx.reply(
            f"⏳ Running cycle with **{spot['spot_name']}** as the winner…",
            mention_author=False,
        )
        try:
            await self.run_cycle(forced_winner_id=spot["id"])
        except Exception as e:
            logger.exception(f"[DropMapVoting] Forced cycle failed: {e}")
            await ctx.reply(f"❌ Cycle failed: `{e}`", mention_author=False)
            return
        await ctx.reply("✅ Cycle complete. Leaderboard reset for a new week.", mention_author=False)

    @commands.command(name="VotingConfig")
    @commands.has_permissions(administrator=True)
    async def voting_config(self, ctx: commands.Context):
        """Admin: show current config."""
        last_cycle = await _get_last_cycle_end()
        next_cycle = _next_cycle_end(datetime.now(timezone.utc))
        spots = await _all_spots_ordered_by_votes()
        total_votes = sum(s["vote_count"] for s in spots)

        embed = discord.Embed(title="⚙️ Drop Map Voting Config", color=0x5865F2)
        embed.add_field(
            name="Channels",
            value=(
                f"Forum: <#{DROP_MAP_VOTING_FORUM_CHANNEL_ID}> (`{DROP_MAP_VOTING_FORUM_CHANNEL_ID}`)\n"
                f"Leaderboard thread: <#{DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}> "
                f"(`{DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}`)\n"
                f"Queue channel: <#{DROP_MAP_QUEUE_CHANNEL_ID}> (`{DROP_MAP_QUEUE_CHANNEL_ID}`)"
            ),
            inline=False,
        )
        embed.add_field(
            name="Limits",
            value=(
                f"Votes per member: **{MAX_VOTES_PER_MEMBER}**\n"
                f"Submissions per member: **1 at a time**\n"
                f"Fuzzy match threshold: **{FUZZY_MATCH_THRESHOLD}**\n"
                f"DM image timeout: **{DM_IMAGE_TIMEOUT_SECONDS // 60} min**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Cycle",
            value=(
                f"Last cycle: **{last_cycle.isoformat() if last_cycle else 'never'}**\n"
                f"Next cycle: **{next_cycle.isoformat()}** (Sunday 00:00 UTC)\n"
                f"Active spots: **{len(spots)}**\n"
                f"Total votes: **{total_votes}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Files",
            value=f"Images dir: `{DROP_MAP_VOTING_IMAGES_DIR}`",
            inline=False,
        )
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="EndVoting")
    @commands.has_permissions(administrator=True)
    async def end_voting(self, ctx: commands.Context):
        """Admin: End the voting cycle immediately (before Sunday)."""
        await ctx.reply(
            "⏳ Ending voting cycle early...",
            mention_author=False,
        )
        try:
            await self.run_cycle()
            await ctx.reply("✅ Voting cycle ended early. Leaderboard reset for next week.", mention_author=False)
        except Exception as e:
            logger.exception(f"[DropMapVoting] Early cycle failed: {e}")
            await ctx.reply(f"❌ Cycle failed: `{e}`", mention_author=False)

    @commands.command(name="VotingRewards")
    @commands.has_permissions(administrator=True)
    async def voting_rewards(self, ctx: commands.Context, action: str = None):
        """Enable or disable voting rewards (Weekly Voter role). OFF by default.
        Usage: >VotingRewards on|off|status"""

        if not ctx.guild:
            await ctx.reply("❌ This command only works in servers.", mention_author=False)
            return

        action = (action or "status").lower()

        if action == "on":
            await _toggle_voting_rewards(ctx.guild.id, True)
            await ctx.reply("✅ Voting rewards **enabled**. Members will now earn 🗳️ Weekly Voter role when voting.", mention_author=False)

        elif action == "off":
            await _toggle_voting_rewards(ctx.guild.id, False)
            await ctx.reply("✅ Voting rewards **disabled**. Members will no longer earn roles from voting.", mention_author=False)

        elif action == "status":
            enabled = await _is_voting_rewards_enabled(ctx.guild.id)
            status = "🟢 **ENABLED**" if enabled else "🔴 **DISABLED**"
            await ctx.reply(
                f"**Voting Rewards Status:** {status}\n"
                f"Use `>VotingRewards on` or `>VotingRewards off` to toggle.",
                mention_author=False
            )
        else:
            await ctx.reply(f"❌ Unknown action: `{action}`. Use `on`, `off`, or `status`.", mention_author=False)

    @commands.command(name="VotingReset")
    @commands.has_permissions(administrator=True)
    async def voting_reset(self, ctx: commands.Context):
        """Admin: Silent clean reset. Wipes database + deletes all cards. No announcements, no auto-submission.
        Usage: >VotingReset"""
        await ctx.reply(
            "⏳ Running silent reset (no announcements)...",
            mention_author=False,
        )
        try:
            # Step 1: Delete all cards from the leaderboard thread
            logger.info("[DropMapVoting] [SILENT RESET] Deleting all cards from leaderboard thread...")
            try:
                await self._delete_all_cards()
                logger.info("[DropMapVoting] [SILENT RESET] ✅ Cards deleted")
            except Exception as e:
                logger.error(f"[DropMapVoting] [SILENT RESET] ❌ Failed to delete cards: {e}")

            # Step 2: Wipe the database (spots and votes)
            logger.info("[DropMapVoting] [SILENT RESET] Wiping database...")
            await _wipe_all_spots()
            logger.info("[DropMapVoting] [SILENT RESET] ✅ Database wiped")

            # Step 3: Mark cycle as just completed so scheduler doesn't immediately fire
            await _set_last_cycle_end(datetime.now(timezone.utc))
            logger.info("[DropMapVoting] [SILENT RESET] ✅ Cycle timer reset")

            # Step 4: Re-ensure info message is pinned (in case it got deleted)
            logger.info("[DropMapVoting] [SILENT RESET] Ensuring info message is pinned...")
            try:
                await self._ensure_info_message_pinned()
                logger.info("[DropMapVoting] [SILENT RESET] ✅ Info message ensured")
            except Exception as e:
                logger.error(f"[DropMapVoting] [SILENT RESET] ❌ Failed to ensure info message: {e}")

            await ctx.reply(
                "✅ **Silent reset complete!**\n"
                "• All spots and votes wiped from database\n"
                "• All cards deleted from leaderboard thread\n"
                "• Info message re-pinned (if needed)\n"
                "• No winner announced, no auto-submission sent\n"
                "• Cycle timer reset — ready for fresh week",
                mention_author=False
            )
        except Exception as e:
            logger.exception(f"[DropMapVoting] Silent reset failed: {e}")
            await ctx.reply(f"❌ Reset failed: `{e}`", mention_author=False)

    @commands.command(name="VotingToggle")
    @commands.has_permissions(administrator=True)
    async def voting_toggle(self, ctx: commands.Context, action: str = None):
        """Enable or disable /addvoting in this server. ON by default.
        Usage: >VotingToggle on|off|status"""

        if not ctx.guild:
            await ctx.reply("❌ This command only works in servers.", mention_author=False)
            return

        action = (action or "status").lower()

        if action == "on":
            await _set_addvoting_enabled(ctx.guild.id, True)
            await ctx.reply(
                "✅ Drop map voting **enabled**. Members can now use `/addvoting` in this server.",
                mention_author=False,
            )
        elif action == "off":
            await _set_addvoting_enabled(ctx.guild.id, False)
            await ctx.reply(
                "✅ Drop map voting **disabled**. `/addvoting` will return an error in this server.",
                mention_author=False,
            )
        elif action == "status":
            enabled = await _is_addvoting_enabled(ctx.guild.id)
            status = "🟢 **ENABLED**" if enabled else "🔴 **DISABLED**"
            await ctx.reply(
                f"**Drop Map Voting Status:** {status}\n"
                f"Use `>VotingToggle on` or `>VotingToggle off` to toggle.",
                mention_author=False,
            )
        else:
            await ctx.reply(
                f"❌ Unknown action: `{action}`. Use `on`, `off`, or `status`.",
                mention_author=False,
            )

    @commands.command(name="ToggleStickyMessage")
    @commands.has_permissions(administrator=True)
    async def toggle_sticky_message(self, ctx: commands.Context, action: str = None):
        """Enable or disable the sticky voting info message in the queue channel. ON by default.
        Usage: >ToggleStickyMessage on|off|status"""

        if not ctx.guild:
            await ctx.reply("❌ This command only works in servers.", mention_author=False)
            return

        action = (action or "status").lower()

        if action == "on":
            await _set_sticky_message_enabled(ctx.guild.id, True)
            await ctx.reply("✅ Sticky voting message **enabled**. The voting info will now be kept visible in the queue channel.", mention_author=False)

        elif action == "off":
            await _set_sticky_message_enabled(ctx.guild.id, False)
            await ctx.reply("✅ Sticky voting message **disabled**. The voting info message will no longer be posted to the queue channel.", mention_author=False)

        elif action == "status":
            enabled = await _is_sticky_message_enabled(ctx.guild.id)
            status = "🟢 **ENABLED**" if enabled else "🔴 **DISABLED**"
            await ctx.reply(
                f"**Sticky Message Status:** {status}\n"
                f"Use `>ToggleStickyMessage on` or `>ToggleStickyMessage off` to toggle.",
                mention_author=False
            )
        else:
            await ctx.reply(f"❌ Unknown action: `{action}`. Use `on`, `off`, or `status`.", mention_author=False)

    @voting_clear.error
    @voting_pick.error
    @voting_config.error
    @voting_rewards.error
    @voting_reset.error
    @voting_toggle.error
    @toggle_sticky_message.error
    @end_voting.error
    async def _admin_err(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Admin only.", mention_author=False)
        else:
            logger.exception(f"[DropMapVoting] admin command error: {error}")
            await ctx.reply(f"❌ Error: `{error}`", mention_author=False)

    # ──────────── public API used by views ────────────

    async def get_leaderboard_thread(self) -> Optional[discord.Thread]:
        """Get the leaderboard thread directly by hardcoded ID."""
        logger.info(f"[DropMapVoting] Attempting to fetch leaderboard thread: {DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}")

        # Try local cache first
        thread = self.bot.get_channel(DROP_MAP_VOTING_LEADERBOARD_THREAD_ID)
        if thread is not None:
            logger.info(f"[DropMapVoting] ✅ Found thread in cache: {thread.name}")
            if isinstance(thread, discord.Thread):
                return thread
            else:
                logger.warning(f"[DropMapVoting] Cache returned {type(thread).__name__}, not a Thread")

        # Try fetching from Discord
        try:
            logger.info(f"[DropMapVoting] Fetching thread from Discord: {DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}")
            thread = await self.bot.fetch_channel(DROP_MAP_VOTING_LEADERBOARD_THREAD_ID)
            logger.info(f"[DropMapVoting] ✅ Fetched thread: {thread.name} (type: {type(thread).__name__})")

            if isinstance(thread, discord.Thread):
                return thread
            else:
                logger.error(f"[DropMapVoting] Fetched ID is {type(thread).__name__}, not Thread!")
                logger.error(f"[DropMapVoting] This might be a ForumChannel. Try using the actual thread ID.")
                return None

        except discord.NotFound:
            logger.error(f"[DropMapVoting] ❌ Thread {DROP_MAP_VOTING_LEADERBOARD_THREAD_ID} not found (404)")
            logger.error(f"[DropMapVoting] Please verify the thread ID is correct!")
            return None
        except discord.Forbidden:
            logger.error(f"[DropMapVoting] ❌ No permission to access thread {DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}")
            return None
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Error fetching thread: {type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    async def get_queue_channel(self) -> Optional[discord.TextChannel]:
        channel = self.bot.get_channel(DROP_MAP_QUEUE_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(DROP_MAP_QUEUE_CHANNEL_ID)
            except Exception as e:
                logger.error(f"[DropMapVoting] Could not fetch queue channel: {e}")
                return None
        return channel

    async def _resolve_submitter_avatar(self, submitter_id: int) -> Optional[str]:
        try:
            user = self.bot.get_user(submitter_id) or await self.bot.fetch_user(submitter_id)
            return user.display_avatar.url if user else None
        except Exception:
            return None

    async def _send_vote_confirmation_dm(
        self,
        user: discord.User,
        spot: dict,
        guild_id: int,
        votes_remaining: int,
    ):
        """DM the voter with a nice confirmation message after they cast a vote."""
        try:
            spot_name = spot.get("spot_name", "Unknown Spot")
            spot_msg_id = spot.get("message_id")
            submitter_name = spot.get("submitter_name", "Unknown")

            # Build the link to the spot card message
            if spot_msg_id:
                spot_link = (
                    f"https://discord.com/channels/{guild_id}/"
                    f"{DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}/{spot_msg_id}"
                )
                spot_link_line = f"🔗 [Jump to {spot_name}]({spot_link})"
            else:
                spot_link_line = f"📍 **Spot:** {spot_name}"

            # Build votes-remaining message
            if votes_remaining > 0:
                votes_line = f"🗳️ You have **{votes_remaining}** vote{'s' if votes_remaining != 1 else ''} remaining this week."
            else:
                votes_line = "🗳️ You've used **all your votes** for this week!"

            embed = discord.Embed(
                title="✅ Vote Confirmed!",
                description=(
                    f"Your vote for **{spot_name}** has been counted! 🎉\n\n"
                    f"{spot_link_line}\n"
                    f"👤 *Submitted by {submitter_name}*\n\n"
                    f"{votes_line}"
                ),
                color=0x00FF7F,
                timestamp=datetime.now(timezone.utc),
            )

            embed.add_field(
                name="📝 Want your own spot in the running?",
                value=(
                    "Submit your own drop spot for a chance to win:\n"
                    "1️⃣ Head to https://discord.com/channels/988564962802810961/1508030522746605690\n"
                    "2️⃣ Run `/addvoting` and fill in spot name + description\n"
                    "3️⃣ DM the bot an image of your spot (or skip)\n"
                    "• **1 submission** per person per week"
                ),
                inline=False,
            )

            embed.add_field(
                name="🏆 How voting works",
                value=(
                    "• Vote for up to **2 spots** per week (click ▲ on cards)\n"
                    "• Click ▲ again on a spot to remove your vote\n"
                    "• Every **Sunday at 00:00 UTC**, the top-voted spot wins\n"
                    "• The winner gets made into a **FREE map** for everyone who voted for it 🚀"
                ),
                inline=False,
            )

            embed.set_footer(text="Wave Drop Maps · Community Voting")

            await user.send(embed=embed)
            logger.info(f"[DropMapVoting] ✅ Sent vote confirmation DM to {user}")
        except discord.Forbidden:
            logger.info(f"[DropMapVoting] Could not DM {user} (DMs closed)")
        except Exception as e:
            logger.error(f"[DropMapVoting] Failed to send vote confirmation DM to {user}: {e}")

    async def _award_weekly_voter_role(self, user: discord.User, guild_id: int):
        """Assign the Weekly Voter role to a user when they vote (if rewards enabled)."""
        try:
            # Check if rewards are enabled for this guild
            if not await _is_voting_rewards_enabled(guild_id):
                return

            # Get the role from the first available guild where the bot has perms
            role = None
            for guild in self.bot.guilds:
                role = guild.get_role(WEEKLY_VOTER_ROLE_ID)
                if role:
                    break

            if not role:
                logger.warning(f"[DropMapVoting] Weekly Voter role {WEEKLY_VOTER_ROLE_ID} not found")
                return

            # Get the member in a guild and add the role
            for guild in self.bot.guilds:
                try:
                    member = guild.get_member(user.id) or await guild.fetch_member(user.id)
                    if member and role not in member.roles:
                        await member.add_roles(role)
                        logger.info(f"[DropMapVoting] Awarded Weekly Voter role to {user}")
                    break
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"[DropMapVoting] Failed to award Weekly Voter role: {e}")

    async def _remove_weekly_voter_role_from_all(self):
        """Remove Weekly Voter role from all members (on weekly reset)."""
        try:
            role = None
            target_guild = None
            for guild in self.bot.guilds:
                role = guild.get_role(WEEKLY_VOTER_ROLE_ID)
                if role:
                    target_guild = guild
                    break

            if not role or not target_guild:
                logger.warning(f"[DropMapVoting] Could not find Weekly Voter role for removal")
                return

            # Remove role from all members who have it
            for member in target_guild.members:
                if role in member.roles:
                    try:
                        await member.remove_roles(role)
                    except Exception as e:
                        logger.warning(f"[DropMapVoting] Could not remove role from {member}: {e}")

            logger.info(f"[DropMapVoting] Removed Weekly Voter role from all members (weekly reset)")
        except Exception as e:
            logger.error(f"[DropMapVoting] Failed to remove Weekly Voter roles: {e}")

    async def _ensure_info_message_pinned(self):
        """Post the voting info message as a sticky message in the leaderboard thread.
        Works like the sticky message in the queue channel: delete old, post fresh at bottom (NO pin)."""
        try:
            thread = await self.get_leaderboard_thread()
            if thread is None:
                logger.warning("[DropMapVoting] Could not get leaderboard thread for info message")
                return

            info_text = _build_voting_info_message()

            # Delete the old info sticky message if it exists
            old_msg_id = await _get_info_sticky_message_id()
            if old_msg_id:
                try:
                    old_msg = await thread.fetch_message(old_msg_id)
                    await old_msg.delete()
                    logger.info(f"[DropMapVoting] Deleted old info sticky message {old_msg_id}")
                except discord.NotFound:
                    logger.info("[DropMapVoting] Old info sticky message already deleted")
                except Exception as e:
                    logger.warning(f"[DropMapVoting] Could not delete old info sticky message: {e}")

            # Clean up any leftover OLD pinned info messages from previous pin-based version
            try:
                pinned = await thread.pins()
                for msg in pinned:
                    if msg.content and msg.content.startswith("🗳️"):
                        try:
                            await msg.unpin()
                            await msg.delete()
                            logger.info(f"[DropMapVoting] Cleaned up old pinned info message {msg.id}")
                        except Exception as e:
                            logger.warning(f"[DropMapVoting] Could not clean old pinned info message: {e}")
            except Exception as e:
                logger.warning(f"[DropMapVoting] Could not check pinned messages: {e}")

            # Post fresh info sticky message at the bottom (no pin)
            logger.info("[DropMapVoting] Posting fresh info sticky message...")
            msg = await thread.send(info_text)
            await _set_info_sticky_message_id(msg.id)
            logger.info(f"[DropMapVoting] ✅ Posted fresh info sticky message: {msg.id}")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to post info sticky message: {e}")
            import traceback
            traceback.print_exc()

    async def get_submissions_thread(self) -> Optional[discord.Thread]:
        """Get the submissions thread (holds the pinned Submit button) by hardcoded ID."""
        thread = self.bot.get_channel(DROP_MAP_VOTING_SUBMISSIONS_THREAD_ID)
        if isinstance(thread, discord.Thread):
            return thread
        try:
            thread = await self.bot.fetch_channel(DROP_MAP_VOTING_SUBMISSIONS_THREAD_ID)
            if isinstance(thread, discord.Thread):
                return thread
            logger.error(
                f"[DropMapVoting] Submissions ID {DROP_MAP_VOTING_SUBMISSIONS_THREAD_ID} "
                f"is {type(thread).__name__}, not a Thread"
            )
            return None
        except Exception as e:
            logger.error(f"[DropMapVoting] Could not fetch submissions thread: {e}")
            return None

    def _is_submit_button_message(self, msg: discord.Message) -> bool:
        """True if a message is one of our pinned Submit-button cards."""
        if msg.author.id != self.bot.user.id:
            return False
        return bool(msg.embeds) and (msg.embeds[0].title or "") == "🗺️ Submit a Drop Spot"

    def _build_submit_button_embed(self) -> discord.Embed:
        """The embed shown on the pinned Submit-button message."""
        return discord.Embed(
            title="🗺️ Submit a Drop Spot",
            description=(
                "Click the button below to open the submission form — "
                "no command needed.\n\n"
                "**Rules:**\n"
                "• 1 submission per member at a time\n"
                "• The top voted spot each week gets added to the queue with Paid Priority\n"
                f"• Vote for other maps in <#{DROP_MAP_VOTING_LEADERBOARD_THREAD_ID}>\n"
                "• You'll be DMed afterwards to send an image"
            ),
            color=0x5865F2,
        )

    async def _ensure_submit_button_pinned(self):
        """Post (and pin) the 'Submit Drop Spot' button message in the submissions
        thread. True pin — posted once and kept; only reposted if it goes missing.

        Lock-guarded + dedupe-swept: concurrent callers (on_ready + the periodic
        task) can't double-post, and any stray duplicate buttons are removed so
        exactly one pinned button survives. The existing message's embed is kept
        in sync, so wording/link changes propagate without a manual repost."""
        async with self._submit_button_lock:
            try:
                thread = await self.get_submissions_thread()
                if thread is None:
                    logger.warning("[DropMapVoting] Could not get submissions thread for Submit button")
                    return

                embed = self._build_submit_button_embed()

                # If a tracked message already exists and is still there, keep it (true pin).
                old_msg_id = await _get_submit_button_message_id()
                if old_msg_id:
                    try:
                        existing = await thread.fetch_message(old_msg_id)
                        if not existing.pinned:
                            try:
                                await existing.pin()
                            except Exception as e:
                                logger.warning(f"[DropMapVoting] Could not (re)pin Submit button: {e}")
                        # Refresh the embed if the wording/link drifted
                        cur = existing.embeds[0].description if existing.embeds else None
                        if cur != embed.description:
                            try:
                                await existing.edit(embed=embed, view=SubmitButtonView())
                                logger.info("[DropMapVoting] Updated Submit button embed content")
                            except Exception as e:
                                logger.warning(f"[DropMapVoting] Could not update Submit button embed: {e}")
                        # Clean up any OTHER stray button copies, keeping this one
                        await self._dedupe_submit_buttons(thread, keep_id=existing.id)
                        logger.debug("[DropMapVoting] Submit button already present")
                        return
                    except discord.NotFound:
                        logger.info("[DropMapVoting] Stored Submit button was deleted, reposting...")
                    except Exception as e:
                        logger.warning(f"[DropMapVoting] Could not verify Submit button: {e}")
                        return

                # No valid tracked message — remove any leftover button copies first
                await self._dedupe_submit_buttons(thread, keep_id=None)

                msg = await thread.send(embed=embed, view=SubmitButtonView())
                await _set_submit_button_message_id(msg.id)
                try:
                    await msg.pin()
                except Exception as e:
                    logger.warning(f"[DropMapVoting] Posted Submit button but could not pin it: {e}")
                logger.info(f"[DropMapVoting] ✅ Posted pinned Submit button: {msg.id}")
            except Exception as e:
                logger.error(f"[DropMapVoting] ❌ Failed to ensure Submit button: {e}")
                import traceback
                traceback.print_exc()

    async def _dedupe_submit_buttons(self, thread: discord.Thread, keep_id: Optional[int]):
        """Delete every Submit-button message in the thread except keep_id (if any)."""
        try:
            pinned = await thread.pins()
        except Exception as e:
            logger.warning(f"[DropMapVoting] Could not list pins for dedupe: {e}")
            return
        for msg in pinned:
            if msg.id == keep_id:
                continue
            if self._is_submit_button_message(msg):
                try:
                    await msg.delete()
                    logger.info(f"[DropMapVoting] Removed duplicate Submit button {msg.id}")
                except Exception as e:
                    logger.warning(f"[DropMapVoting] Could not delete duplicate Submit button {msg.id}: {e}")

    async def post_new_card(self, spot_id: int):
        spot = await _get_spot_by_id(spot_id)
        if spot is None:
            return
        thread = await self.get_leaderboard_thread()
        if thread is None:
            raise RuntimeError("Leaderboard thread not available")

        rank       = await self._compute_rank(spot_id)
        vote_count = await _vote_count_for_spot(spot_id)
        avatar_url = await self._resolve_submitter_avatar(spot["submitter_id"])
        embed      = _build_card_embed(spot, rank, vote_count, avatar_url)
        view       = VoteButtonView(spot_id, vote_count)

        message = await thread.send(embed=embed, view=view)
        await _set_spot_message_id(spot_id, message.id)
        self.bot.add_view(view, message_id=message.id)

    async def _compute_rank(self, spot_id: int) -> int:
        ordered = await _all_spots_ordered_by_votes()
        for i, s in enumerate(ordered, start=1):
            if s["id"] == spot_id:
                return i
        return len(ordered)

    async def refresh_ranks(self, *, debounce: bool = False):
        # If debounce=True and a refresh is already queued/running, skip this one
        if debounce:
            if self._refresh_pending or self._refresh_lock.locked():
                return
            self._refresh_pending = True
        try:
            async with self._refresh_lock:
                self._refresh_pending = False
                thread = await self.get_leaderboard_thread()
                if thread is None:
                    return
                ordered = await _all_spots_ordered_by_votes()
                for new_rank, spot in enumerate(ordered, start=1):
                    if not spot.get("message_id"):
                        continue
                    try:
                        msg = await thread.fetch_message(spot["message_id"])
                    except discord.NotFound:
                        logger.warning(
                            f"[DropMapVoting] Card message {spot['message_id']} missing — skipping"
                        )
                        continue
                    except Exception as e:
                        logger.error(f"[DropMapVoting] fetch_message failed: {e}")
                        continue

                    vote_count = spot["vote_count"]
                    avatar_url = await self._resolve_submitter_avatar(spot["submitter_id"])
                    new_embed  = _build_card_embed(spot, new_rank, vote_count, avatar_url)
                    new_view   = VoteButtonView(spot["id"], vote_count)

                    # Only edit if anything actually changed
                    old_embed = msg.embeds[0] if msg.embeds else None
                    needs_edit = (
                        old_embed is None
                        or old_embed.title != new_embed.title
                        or _embed_field_value(old_embed, f"🔥 Votes  ·  {vote_count}") is None
                    )
                    if not needs_edit:
                        continue

                    try:
                        await msg.edit(embed=new_embed, view=new_view)
                        self.bot.add_view(new_view, message_id=msg.id)
                        await asyncio.sleep(1)  # pace edits to avoid 429s
                    except Exception as e:
                        logger.error(f"[DropMapVoting] Failed to edit card {spot['id']}: {e}")
        finally:
            self._refresh_pending = False

    async def collect_image_via_dm(self, user: discord.User, spot_id: int):
        try:
            dm = await user.create_dm()
            await dm.send(
                f"📸 Reply to this DM with an **image of your spot** "
                f"(PNG/JPG/GIF/WEBP, max 8 MB), a **fortnite.gg link** to auto-screenshot, "
                f"or type `skip` to submit without one.\n"
                f"You have {DM_IMAGE_TIMEOUT_SECONDS // 60} minutes."
            )
        except discord.Forbidden:
            logger.info(f"[DropMapVoting] Could not DM {user} — DMs closed")
            return

        def _check(m: discord.Message):
            return m.author.id == user.id and m.channel.id == dm.id

        try:
            reply = await self.bot.wait_for(
                'message', check=_check, timeout=DM_IMAGE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            try:
                await dm.send("⏰ Time's up. Your spot is saved without an image.")
            except Exception:
                pass
            await self._finalize_card_after_dm(spot_id, image_path=None)
            return

        content = (reply.content or "").strip()
        content_lower = content.lower()

        if content_lower == "skip":
            await dm.send("👍 Saved without an image.")
            await self._finalize_card_after_dm(spot_id, image_path=None)
            return

        # fn.gg link → auto-render with DOM crop (same as loot route watermark)
        fngg_match = re.search(r'https?://(?:www\.)?fortnite\.gg/\S+', content)
        if fngg_match and not reply.attachments:
            url = fngg_match.group(0).strip('<>').strip()
            status_msg = await dm.send("🎯 Rendering your map from fortnite.gg… (~30 s)")
            try:
                from commands.auto_watermark import render_and_crop_dom, _executor
                loop = asyncio.get_event_loop()
                png_bytes = await loop.run_in_executor(_executor, render_and_crop_dom, url)
            except Exception as e:
                logger.error(f"[DropMapVoting] render_and_crop_dom failed for spot {spot_id}: {e}")
                await status_msg.edit(content=f"⚠️ Couldn't render that link (`{str(e)[:120]}`). Saved without an image.")
                await self._finalize_card_after_dm(spot_id, image_path=None)
                return

            DROP_MAP_VOTING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            local_path = DROP_MAP_VOTING_IMAGES_DIR / f"{spot_id}.png"
            try:
                local_path.write_bytes(png_bytes)
            except Exception as e:
                logger.error(f"[DropMapVoting] Failed to save rendered image for spot {spot_id}: {e}")
                await status_msg.edit(content="⚠️ Couldn't save the rendered image. Saved without an image.")
                await self._finalize_card_after_dm(spot_id, image_path=None)
                return

            rel_path = str(local_path).replace("\\", "/")
            await _set_spot_image_path(spot_id, rel_path)
            await status_msg.edit(content="✅ Map rendered and attached to your spot. Thanks!")
            await self._finalize_card_after_dm(spot_id, image_path=rel_path)
            return

        if not reply.attachments:
            await dm.send("⚠️ No image attached. Saved without an image.")
            await self._finalize_card_after_dm(spot_id, image_path=None)
            return

        attachment = reply.attachments[0]
        ext = (attachment.filename.rsplit(".", 1)[-1] or "").lower()
        if ext not in ALLOWED_IMAGE_EXTS:
            await dm.send(f"⚠️ `.{ext}` isn't a supported image type. Saved without an image.")
            await self._finalize_card_after_dm(spot_id, image_path=None)
            return
        if attachment.size > MAX_IMAGE_BYTES:
            await dm.send(f"⚠️ That image is too large. Saved without an image.")
            await self._finalize_card_after_dm(spot_id, image_path=None)
            return

        DROP_MAP_VOTING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        local_path = DROP_MAP_VOTING_IMAGES_DIR / f"{spot_id}.{ext}"
        try:
            await attachment.save(fp=str(local_path))
        except Exception as e:
            logger.error(f"[DropMapVoting] Failed to save image for spot {spot_id}: {e}")
            await dm.send("⚠️ Couldn't save the image. Spot saved without an image.")
            await self._finalize_card_after_dm(spot_id, image_path=None)
            return

        rel_path = str(local_path).replace("\\", "/")
        await _set_spot_image_path(spot_id, rel_path)
        await dm.send("✅ Image attached to your spot. Thanks!")
        await self._finalize_card_after_dm(spot_id, image_path=rel_path)

    async def _finalize_card_after_dm(self, spot_id: int, image_path: Optional[str]):
        thread = await self.get_leaderboard_thread()
        if thread is None:
            return
        spot = await _get_spot_by_id(spot_id)
        if not spot or not spot.get("message_id"):
            return

        rank       = await self._compute_rank(spot_id)
        vote_count = await _vote_count_for_spot(spot_id)
        avatar_url = await self._resolve_submitter_avatar(spot["submitter_id"])
        embed      = _build_card_embed(spot, rank, vote_count, avatar_url)
        view       = VoteButtonView(spot_id, vote_count)

        try:
            msg = await thread.fetch_message(spot["message_id"])
        except Exception as e:
            logger.error(f"[DropMapVoting] Could not fetch card to finalize: {e}")
            return

        attachments = []
        if image_path:
            try:
                attachments = [discord.File(image_path)]
            except Exception as e:
                logger.error(f"[DropMapVoting] Could not attach image file: {e}")

        try:
            await msg.edit(embed=embed, view=view, attachments=attachments)
            self.bot.add_view(view, message_id=msg.id)
        except Exception as e:
            logger.error(f"[DropMapVoting] Could not edit card after DM: {e}")

    # ──────────── Weekly cycle ────────────

    @tasks.loop(minutes=10)
    async def cycle_scheduler(self):
        """Every 10 minutes, check if a cycle is due and run it if so."""
        logger.debug("[DropMapVoting] Cycle scheduler tick - checking if cycle is due...")
        try:
            await self._check_and_run_cycle()
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ cycle_scheduler error: {e}")

    @cycle_scheduler.before_loop
    async def _before_scheduler(self):
        await self.bot.wait_until_ready()
        # Run catch-up immediately on startup
        try:
            await self._check_and_run_cycle()
            self._catch_up_done = True
        except Exception as e:
            logger.exception(f"[DropMapVoting] startup catch-up failed: {e}")

    async def _check_and_run_cycle(self):
        """Called by the scheduler. Acquires the cycle lock, checks if cycle is due."""
        async with self._cycle_lock:
            now = datetime.now(timezone.utc)
            last = await _get_last_cycle_end()
            due = _previous_cycle_end(now)

            if last is None or last < due:
                logger.info(
                    f"[DropMapVoting] 🔔 CYCLE DUE!\n"
                    f"  Now: {now.isoformat()}\n"
                    f"  Last: {last.isoformat() if last else 'never'}\n"
                    f"  Due: {due.isoformat()}"
                )
                ran = await self._run_cycle_internal()
                # Always update last_cycle_end so we don't re-fire each tick even on skip-week
                await _set_last_cycle_end(due)
                return ran
            else:
                logger.debug(f"[DropMapVoting] Cycle not due yet. Next due: {due.isoformat()}")
            return False

    # ──────────── Periodic info message task ────────────

    @tasks.loop(minutes=5)
    async def info_message_task(self):
        """Run every 5 minutes to verify info sticky exists. Only reposts if missing/gone."""
        logger.debug("[DropMapVoting] Verifying info sticky message exists...")
        try:
            thread = await self.get_leaderboard_thread()
            if thread is None:
                logger.warning("[DropMapVoting] Could not get thread for info sticky verification")
                return

            info_msg_id = await _get_info_sticky_message_id()

            # If no stored ID, post fresh
            if not info_msg_id:
                logger.info("[DropMapVoting] No info sticky stored, posting fresh...")
                await self._ensure_info_message_pinned()
                return

            # Verify the stored message still exists
            try:
                await thread.fetch_message(info_msg_id)
                logger.debug("[DropMapVoting] Info sticky verified, no action needed")
            except discord.NotFound:
                logger.info("[DropMapVoting] Stored info sticky was deleted, reposting...")
                await self._ensure_info_message_pinned()
            except Exception as e:
                logger.warning(f"[DropMapVoting] Could not verify info sticky: {e}")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Info message task failed: {e}")

        # Also verify the pinned Submit button still exists (repost+pin if gone)
        try:
            await self._ensure_submit_button_pinned()
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Submit-button verification failed: {e}")

    @info_message_task.before_loop
    async def _before_info_message_task(self):
        await self.bot.wait_until_ready()
        # Add a small delay to ensure all channels/threads are cached
        await asyncio.sleep(5)
        logger.info("[DropMapVoting] Bot ready, proceeding with info message task...")

    async def run_cycle(self, forced_winner_id: Optional[int] = None):
        """External entrypoint (admin >VotingPick uses this). Acquires the lock."""
        async with self._cycle_lock:
            await self._run_cycle_internal(forced_winner_id=forced_winner_id)
            # Manual pick: mark cycle as done so the scheduler won't immediately re-fire
            await _set_last_cycle_end(datetime.now(timezone.utc))

    async def _run_cycle_internal(self, forced_winner_id: Optional[int] = None) -> bool:
        """Actual cycle work. MUST be called with self._cycle_lock held.
        Returns True if a winner was picked and posted, False if skipped."""
        logger.info("[DropMapVoting] ========== CYCLE EXECUTION START ==========")

        if forced_winner_id is not None:
            logger.info(f"[DropMapVoting] Forced winner mode: spot #{forced_winner_id}")
            winner = await _get_spot_by_id(forced_winner_id)
            if winner is None:
                raise RuntimeError(f"Forced winner spot {forced_winner_id} not found")
            vote_count = await _vote_count_for_spot(winner["id"])
        else:
            spots = await _all_spots_ordered_by_votes()
            logger.info(f"[DropMapVoting] Found {len(spots)} total spots")
            if not spots:
                logger.info("[DropMapVoting] ⏭️ SKIP: No spots submitted")
                return False
            winner = spots[0]
            vote_count = winner["vote_count"]
            logger.info(f"[DropMapVoting] Top spot: {winner['spot_name']} ({vote_count} votes)")
            if vote_count == 0:
                logger.info("[DropMapVoting] ⏭️ SKIP: Top spot has 0 votes")
                return False

        voter_ids = await _voters_for_spot(winner["id"])
        logger.info(f"[DropMapVoting] 🏆 WINNER: {winner['spot_name']} ({len(voter_ids)} voters)")

        try:
            logger.info("[DropMapVoting] Auto-running >addmap in Wave Logistics Bot...")
            await self._auto_addmap_in_wave_logistics(winner, voter_ids)
            logger.info("[DropMapVoting] ✅ Auto-addmap successful")
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ Failed to auto-add map to Wave Logistics: {e}")
            # Continue with announcement so users know their spot won

        try:
            logger.info("[DropMapVoting] Announcing winner in leaderboard...")
            await self._announce_winner_in_thread(winner, vote_count, voter_ids)
            logger.info("[DropMapVoting] ✅ Winner announcement successful")
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ Failed to announce winner: {e}")

        try:
            logger.info("[DropMapVoting] Deleting all voting cards...")
            await self._delete_all_cards()
            logger.info("[DropMapVoting] ✅ Cards deleted")
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ Failed to delete cards on reset: {e}")

        # Re-ensure info message is pinned (in case it got deleted during cleanup)
        try:
            logger.info("[DropMapVoting] Ensuring info message is pinned post-cycle...")
            await self._ensure_info_message_pinned()
            logger.info("[DropMapVoting] ✅ Info message ensured")
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ Failed to ensure info message post-cycle: {e}")

        # Remove Weekly Voter role from everyone (fresh week)
        try:
            logger.info("[DropMapVoting] Removing Weekly Voter role from all members...")
            await self._remove_weekly_voter_role_from_all()
            logger.info("[DropMapVoting] ✅ Roles removed")
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ Failed to remove Weekly Voter roles on reset: {e}")

        try:
            logger.info("[DropMapVoting] Wiping voting database...")
            await _wipe_all_spots()
            logger.info("[DropMapVoting] ✅ Database wiped")
        except Exception as e:
            logger.exception(f"[DropMapVoting] ❌ Failed to wipe database: {e}")

        logger.info(
            f"[DropMapVoting] ========== CYCLE COMPLETE ==========\n"
            f"  Winner: {winner['spot_name']}\n"
            f"  Votes: {vote_count}\n"
            f"  Voters: {len(voter_ids)}\n"
        )
        return True

    async def _auto_addmap_in_wave_logistics(self, spot: dict, voter_ids: List[int]):
        """Auto-run >addmap in Wave Logistics Bot command channel to create the map."""
        try:
            # Get the command channel
            channel = self.bot.get_channel(DROP_MAP_ADDMAP_COMMAND_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(DROP_MAP_ADDMAP_COMMAND_CHANNEL_ID)
                except Exception as e:
                    logger.warning(f"[DropMapVoting] Command channel {DROP_MAP_ADDMAP_COMMAND_CHANNEL_ID} unavailable: {e}")
                    return

            # Format the spot name and description safely (escape quotes)
            spot_name = spot['spot_name'].replace('"', '\\"')
            description = (spot.get('description') or '').replace('"', '\\"')

            # Format user IDs (just the raw IDs, not mentions)
            users_str = " ".join(str(uid) for uid in voter_ids) if voter_ids else ""

            # The stored image_path is a LOCAL path on this bot's machine — not a
            # valid URL, which makes the Logistics bot's queue embed fail with
            # "Not a well formed URL" (error 50035). So we upload the actual image
            # file as an attachment on the command message; the Logistics bot's
            # _addmap_automated prefers the attachment's CDN URL over --image.
            image_file = None
            resolved_img = None
            image_path = spot.get('image_path')
            if image_path:
                candidate = Path(image_path)
                if not candidate.is_absolute():
                    # image_path is stored relative to the repo root; resolve it
                    # robustly regardless of the process's working directory.
                    candidate = Path(__file__).resolve().parent.parent / image_path
                if candidate.exists():
                    try:
                        image_file = discord.File(str(candidate), filename=candidate.name)
                        resolved_img = candidate
                    except Exception as e:
                        logger.warning(f"[DropMapVoting] Could not open image {candidate} for addmap: {e}")
                else:
                    logger.warning(f"[DropMapVoting] Image file not found for addmap: {candidate}")

            # Build the -z addmap command matching Wave Logistics Bot format:
            # -z addmap new --spot-name "name" --image url --users id1 id2 --description "desc"
            # --image is a placeholder when the image rides along as an attachment;
            # falls back to the raw path so the command is still well-formed.
            image_arg = resolved_img.name if resolved_img else (image_path or "none")
            addmap_command = (
                f"-z addmap new "
                f'--spot-name "{spot_name}" '
                f"--image {image_arg} "
                f"--users {users_str} "
                f'--description "{description}"'
            )

            # Send the command (with the image attachment) to the command channel
            if image_file is not None:
                await channel.send(addmap_command, file=image_file)
            else:
                await channel.send(addmap_command)
            logger.info(f"[DropMapVoting] ✅ Auto-addmap command sent to Wave Logistics: {spot_name}")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed in _auto_addmap_in_wave_logistics: {e}")
            raise

    async def _post_to_queue(self, spot: dict, voter_ids: List[int]):
        channel = await self.get_queue_channel()
        if channel is None:
            raise RuntimeError("Queue channel unavailable")

        # Resolve the Paid Priority role ID in the queue guild
        paid_priority_role_id = None
        guild = self.bot.get_guild(DROP_MAP_QUEUE_GUILD_ID)
        if guild:
            role = discord.utils.find(
                lambda r: r.name == PAID_PRIORITY_ROLE_NAME, guild.roles
            )
            if role:
                paid_priority_role_id = role.id

        field_value = _build_queue_field_value(
            voter_ids, spot.get("description") or "", paid_priority_role_id
        )
        embed = discord.Embed(color=0xFFD700)
        embed.add_field(name="​", value=field_value, inline=False)
        vote_count = len(voter_ids)
        embed.set_footer(text=f"🗳️ Community vote winner ({vote_count} votes) · {spot['spot_name']}")

        file = None
        if spot.get("image_path") and os.path.exists(spot["image_path"]):
            try:
                filename = os.path.basename(spot["image_path"])
                file = discord.File(spot["image_path"], filename=filename)
                embed.set_image(url=f"attachment://{filename}")
            except Exception as e:
                logger.error(f"[DropMapVoting] Could not attach winner image: {e}")

        if file:
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)

    async def _announce_winner_in_thread(self, spot: dict, vote_count: int, voter_ids: List[int]):
        thread = await self.get_leaderboard_thread()
        if thread is None:
            return
        total_votes = await _total_votes_this_week()
        embed = _build_winner_announcement_embed(spot, vote_count, voter_ids, total_votes)
        file = None
        if spot.get("image_path") and os.path.exists(spot["image_path"]):
            try:
                filename = os.path.basename(spot["image_path"])
                file = discord.File(spot["image_path"], filename=filename)
            except Exception:
                pass
        if file:
            await thread.send(embed=embed, file=file)
        else:
            await thread.send(embed=embed)

    async def _delete_all_cards(self):
        thread = await self.get_leaderboard_thread()
        if thread is None:
            return

        logger.info("[DropMapVoting] Deleting all voting cards from leaderboard thread...")
        deleted_count = 0

        # Get the info sticky message ID from database so we can preserve it
        info_msg_id = await _get_info_sticky_message_id()
        if info_msg_id:
            logger.info(f"[DropMapVoting] Will preserve info sticky message {info_msg_id}")

        # Delete all messages except the info sticky message and thread starter
        async for msg in thread.history(limit=None):
            # Skip the info sticky message
            if info_msg_id and msg.id == info_msg_id:
                continue
            # Skip the thread starter message (has same ID as the thread itself in forum posts)
            if msg.id == thread.id:
                logger.info(f"[DropMapVoting] Skipping thread starter message {msg.id}")
                continue
            # Skip Discord system messages
            if msg.type in (discord.MessageType.thread_created, discord.MessageType.channel_name_change):
                continue
            # Delete the card message
            try:
                await msg.delete()
                deleted_count += 1
                logger.debug(f"[DropMapVoting] Deleted message {msg.id}")
            except Exception as e:
                logger.warning(f"[DropMapVoting] Could not delete message {msg.id}: {e}")

        logger.info(f"[DropMapVoting] ✅ Deleted {deleted_count} card messages from leaderboard")

    # ──────────── Sticky message management ────────────

    async def _post_sticky_message(self):
        """Post the sticky voting info message to the queue channel."""
        # Check if sticky message is enabled
        guild_id = GUILD_ID if 'GUILD_ID' in globals() else None
        if not guild_id:
            # Fallback: get first guild from cache or use hardcoded guild
            try:
                guild_id = list(self.bot.guilds)[0].id if self.bot.guilds else None
            except:
                guild_id = DROP_MAP_QUEUE_GUILD_ID

        sticky_enabled = await _is_sticky_message_enabled(guild_id)
        if not sticky_enabled:
            logger.info("[DropMapVoting] Sticky message is disabled, skipping post")
            return

        try:
            # Try cache first, then fetch from Discord
            channel = self.bot.get_channel(STICKY_MESSAGE_CHANNEL_ID)
            if channel is None:
                channel = await self.bot.fetch_channel(STICKY_MESSAGE_CHANNEL_ID)

            sticky_msg_id = await _get_sticky_message_id()
            if sticky_msg_id:
                try:
                    old_msg = await channel.fetch_message(sticky_msg_id)
                    # Message still exists — don't repost
                    logger.info(f"[DropMapVoting] Sticky message {sticky_msg_id} already exists, skipping repost")
                    return
                except discord.NotFound:
                    logger.info("[DropMapVoting] Old sticky message was deleted, will repost")
                except Exception as e:
                    logger.warning(f"[DropMapVoting] Could not verify old sticky message: {e}")

            sticky_text = (
                "🗳️  **WAVE COMMUNITY GOVERNANCE VOTING**\n\n"
                "📝 **SUBMIT FOR FREE**\n"
                "└─ Post your map submission in <#1508030522746605690>\n"
                "   • **1 submission** per person each week\n"
                "   • Submissions **cannot be changed** once posted\n\n"
                "🗺️ **YOUR VOTE MATTERS**\n"
                "└─ Vote in <#1508289287169511496> for the drop maps you want made\n"
                "   • **2 votes** per person each week\n\n"
                "🏆 **MOST VOTES WIN**\n"
                "└─ The map with the **highest votes** in <#1508289287169511496> wins\n"
                "   • Selected map gets added to <#1210837116649742396>\n"
                "   • **Made for FREE for anyone that voted for that map** 🚀"
            )

            new_msg = await channel.send(sticky_text)
            await _set_sticky_message_id(new_msg.id)
            logger.info(f"[DropMapVoting] ✅ Posted sticky message: {new_msg.id}")
        except Exception as e:
            logger.error(f"[DropMapVoting] ❌ Failed to post sticky message: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Monitor the sticky message channel and leaderboard thread for new messages.
        Smart filter: ignore ONLY our own sticky/info messages, but trigger reposts on
        any other message (including bot-sent queue/card messages)."""
        # Handle sticky message in queue channel
        if message.channel.id == STICKY_MESSAGE_CHANNEL_ID:
            # Smart filter: only ignore if this message IS the sticky itself
            stored_sticky_id = await _get_sticky_message_id()
            if stored_sticky_id and message.id == stored_sticky_id:
                return  # This is our sticky — don't infinite loop

            # Check if sticky message is enabled
            guild_id = DROP_MAP_QUEUE_GUILD_ID if 'DROP_MAP_QUEUE_GUILD_ID' in globals() else (message.guild.id if message.guild else None)
            if not await _is_sticky_message_enabled(guild_id):
                return

            # Debounce: only one check task at a time — burst of messages won't spawn N tasks
            if not self._sticky_check_pending:
                self._sticky_check_pending = True
                asyncio.create_task(self._check_sticky_after_delay())

        # Handle info message in leaderboard thread
        elif isinstance(message.channel, discord.Thread) and message.channel.id == DROP_MAP_VOTING_LEADERBOARD_THREAD_ID:
            # Smart filter: only ignore if this message IS the info sticky itself
            stored_info_id = await _get_info_sticky_message_id()
            if stored_info_id and message.id == stored_info_id:
                return  # This is our info sticky — don't infinite loop

            # Debounce: only one check task at a time
            if not self._info_check_pending:
                self._info_check_pending = True
                asyncio.create_task(self._check_info_message_after_delay())

    async def _check_sticky_after_delay(self):
        """Wait 30 seconds, then check if sticky message is still the latest."""
        # Check if sticky message is enabled before doing anything
        guild_id = DROP_MAP_QUEUE_GUILD_ID if 'DROP_MAP_QUEUE_GUILD_ID' in globals() else None
        if not await _is_sticky_message_enabled(guild_id):
            self._sticky_check_pending = False
            return

        await asyncio.sleep(30)
        # Clear the debounce flag now — any messages that arrive after this
        # point should schedule a fresh check once we're done.
        self._sticky_check_pending = False

        async with self._sticky_post_lock:
            try:
                # Try cache first, then fetch from Discord
                channel = self.bot.get_channel(STICKY_MESSAGE_CHANNEL_ID)
                if channel is None:
                    try:
                        channel = await self.bot.fetch_channel(STICKY_MESSAGE_CHANNEL_ID)
                    except Exception:
                        return

                sticky_msg_id = await _get_sticky_message_id()
                if not sticky_msg_id:
                    logger.info("[DropMapVoting] No sticky message ID stored, posting new one")
                    await self._post_sticky_message()
                    return

                # Get the latest messages
                async for msg in channel.history(limit=1):
                    if msg.id != sticky_msg_id:
                        logger.info("[DropMapVoting] Sticky message is no longer latest, reposting...")
                        await self._post_sticky_message()
                    else:
                        logger.debug("[DropMapVoting] Sticky message is still latest, no action needed")
                    return
            except Exception as e:
                logger.error(f"[DropMapVoting] Error checking sticky message: {e}")

    async def _check_info_message_after_delay(self):
        """Wait 30 seconds, then check if info message is still the latest pinned message in leaderboard thread."""
        await asyncio.sleep(30)
        # Clear the debounce flag so messages arriving after this point
        # can schedule a fresh check.
        self._info_check_pending = False

        try:
            thread = await self.get_leaderboard_thread()
            if thread is None:
                return

            info_msg_id = await _get_info_sticky_message_id()
            if not info_msg_id:
                logger.info("[DropMapVoting] No info sticky message ID stored, posting new one")
                await self._ensure_info_message_pinned()
                return

            # Check if info sticky is still the latest message in the thread
            async for msg in thread.history(limit=1):
                if msg.id != info_msg_id:
                    logger.info("[DropMapVoting] Info sticky is no longer latest, reposting at bottom...")
                    await self._ensure_info_message_pinned()
                else:
                    logger.debug("[DropMapVoting] Info sticky is still latest, no action needed")
                return
        except Exception as e:
            logger.error(f"[DropMapVoting] Error checking info sticky message: {e}")


# ============================================================================

def _embed_field_value(embed: discord.Embed, name: str) -> Optional[str]:
    for f in embed.fields:
        if f.name == name:
            return f.value
    return None


def _build_voting_info_message() -> str:
    """Build the voting info message for the leaderboard thread."""
    return (
        "**🗳️  WAVE COMMUNITY GOVERNANCE VOTING**\n"
        "Your voice shapes which drop spot gets made next!\n\n"
        "**📝 SUBMIT A DROP SPOT**\n"
        "Vote in https://discord.com/channels/988564962802810961/1508030522746605690 → fill in name + description → DM an image (or skip)\n"
        "• 1 submission per person per week\n\n"
        "**🗺️ VOTE FOR SPOTS**\n"
        "Click the ▲ button on any spot card\n"
        "• Vote limit: 2 per person per week\n\n"
        "**🏆 THE WINNER**\n"
        "Every Sunday, the top-voted spot wins and gets made for FREE with Paid Priority!\n"
        "• Everyone who voted for that map gets added to the queue with it\n\n"
        "**⭐ EARN REWARDS**\n"
        "🗳️ Weekly Voter role\n"
        "• Free Maps made for the community!"
    )


async def setup(bot):
    await bot.add_cog(DropMapVoting(bot))
