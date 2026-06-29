"""
Power Points Rewards - tasks/power_points_rewards.py

After a milestone sync, this module:
  1. Calculates each staff member's Power Points (same formula as the leaderboard)
  2. Assigns the correct badge role in the Staff Hub guild (only the highest tier)
  3. Awards a one-time Wave Points bonus for each new tier reached

Power Points formula:
  For each duty (message, role, req, modlog), check which tier the user reached.
  Bronze=1pt, Silver=2pt, Gold=4pt, Legend=8pt, God=16pt.
  Sum all earned points across all duties = Power Points.
"""

import asyncio
import logging
import traceback
from datetime import datetime, timezone

import database

logger = logging.getLogger('discord')

# ==================== CONFIGURATION ====================

STAFF_HUB_GUILD_ID = 1041450125391835186

# Duty thresholds — must match the leaderboard frontend exactly
DUTY_THRESHOLDS = {
    'message': {'Bronze': 1000,  'Silver': 3000,  'Gold': 8000,  'Legend': 10000, 'God': 50000},
    'role':    {'Bronze': 500,   'Silver': 1500,  'Gold': 4000,  'Legend': 5000,  'God': 25000},
    'req':     {'Bronze': 250,   'Silver': 750,   'Gold': 2000,  'Legend': 2500,  'God': 12500},
    'modlog':  {'Bronze': 50,    'Silver': 200,   'Gold': 500,   'Legend': 1000,  'God': 10000},
}

BADGE_WEIGHTS = {'Bronze': 1, 'Silver': 2, 'Gold': 4, 'Legend': 8, 'God': 16}
TIERS_ASC = ['Bronze', 'Silver', 'Gold', 'Legend', 'God']

# Power tier thresholds → Discord role IDs + Wave Points rewards
# Ordered highest-first for easy lookup
POWER_TIERS = [
    {'tier': 'God',    'min_pts': 64, 'role_id': 1508413031024169122, 'wave_reward': 500},
    {'tier': 'Legend', 'min_pts': 32, 'role_id': 1508412963718168687, 'wave_reward': 300},
    {'tier': 'Gold',   'min_pts': 16, 'role_id': 1508412960584765441, 'wave_reward': 100},
    {'tier': 'Silver', 'min_pts': 8,  'role_id': 1508412940489982022, 'wave_reward': 50},
    {'tier': 'Bronze', 'min_pts': 4,  'role_id': 1508412912715436133, 'wave_reward': 20},
]

ALL_POWER_ROLE_IDS = {t['role_id'] for t in POWER_TIERS}


# ==================== CALCULATION ====================

def calculate_power_points(scores: dict) -> int:
    """
    Calculate Power Points from a user's duty scores.
    Mirrors the frontend badgeScore() function exactly.

    Args:
        scores: dict like {"message": 12400, "role": 4800, "req": 980, "modlog": 620}

    Returns:
        int: total Power Points
    """
    total = 0
    for duty_key, thresholds in DUTY_THRESHOLDS.items():
        score = scores.get(duty_key, 0)
        if not isinstance(score, (int, float)):
            continue
        # Find highest tier reached for this duty
        highest = None
        for tier in TIERS_ASC:
            if score >= thresholds[tier]:
                highest = tier
        if highest:
            total += BADGE_WEIGHTS[highest]
    return total


def get_power_tier(power_points: int) -> dict | None:
    """Return the highest power tier dict the user qualifies for, or None."""
    for t in POWER_TIERS:
        if power_points >= t['min_pts']:
            return t
    return None


# ==================== DATABASE ====================

async def init_power_points_claimed_table():
    """Create the power_points_claimed table if it doesn't exist."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS power_points_claimed (
                user_id     INTEGER NOT NULL,
                tier        TEXT NOT NULL,
                claimed_at  TEXT NOT NULL,
                wave_reward INTEGER NOT NULL,
                PRIMARY KEY (user_id, tier)
            )
        ''')
        await db.commit()
    logger.info("✅ power_points_claimed table initialised")


async def get_claimed_tiers(user_id: int) -> set:
    """Return the set of tier names already claimed by this user."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT tier FROM power_points_claimed WHERE user_id = ?', (user_id,)
        ) as cursor:
            return {row[0] async for row in cursor}


async def mark_tier_claimed(user_id: int, tier: str, wave_reward: int):
    """Record that a user has claimed a specific tier bonus."""
    pool = await database.get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT OR IGNORE INTO power_points_claimed (user_id, tier, claimed_at, wave_reward)
            VALUES (?, ?, ?, ?)
        ''', (user_id, tier, now, wave_reward))
        await db.commit()


# ==================== MAIN SYNC ====================

async def sync_power_rewards(bot, milestone_data: dict):
    """
    Process Power Points rewards for all staff in milestone_data.

    For each staff member:
      1. Calculate their Power Points from their duty scores
      2. Determine their highest Power Tier
      3. In the Staff Hub guild: remove all lower badge roles, add the correct one
      4. Award any unclaimed Wave Points bonuses

    Args:
        bot:            Discord bot instance
        milestone_data: dict from sync_milestone_totals, keyed by display name
                        Each value has duty scores + "uid" field
    """
    logger.info("🏆 ============================================")
    logger.info("🏆 POWER POINTS REWARDS SYNC")
    logger.info("🏆 ============================================")

    # Ensure DB table exists
    await init_power_points_claimed_table()

    # Get Staff Hub guild
    guild = bot.get_guild(STAFF_HUB_GUILD_ID)
    if not guild:
        logger.error(f"  ❌ Staff Hub guild {STAFF_HUB_GUILD_ID} not found — skipping power rewards")
        return

    # Import wave points helper
    from tasks.wave_points import add_wave_points

    roles_updated = 0
    bonuses_awarded = 0
    total_wave_awarded = 0

    for display_name, entry in milestone_data.items():
        try:
            user_id = entry.get('uid')
            if not user_id:
                continue

            # Build scores dict from the milestone entry
            scores = {}
            for duty_key in DUTY_THRESHOLDS:
                val = entry.get(duty_key, 0)
                if isinstance(val, (int, float)):
                    scores[duty_key] = int(val)

            # Calculate Power Points
            power_pts = calculate_power_points(scores)
            if power_pts < 1:
                continue  # No tier earned

            tier_info = get_power_tier(power_pts)
            if not tier_info:
                continue

            # Find the member in the Staff Hub guild
            member = guild.get_member(user_id)
            if not member:
                logger.debug(f"  ⚠️ {display_name} ({user_id}) not in Staff Hub — skipping")
                continue

            # ── Role Management ──
            # Remove all power roles that are NOT the correct one
            correct_role_id = tier_info['role_id']
            roles_to_remove = []
            has_correct_role = False

            for role in member.roles:
                if role.id in ALL_POWER_ROLE_IDS:
                    if role.id == correct_role_id:
                        has_correct_role = True
                    else:
                        roles_to_remove.append(role)

            # Remove wrong roles
            if roles_to_remove:
                try:
                    await member.remove_roles(*roles_to_remove, reason=f"Power Tier update → {tier_info['tier']}")
                    removed_names = ', '.join(r.name for r in roles_to_remove)
                    logger.info(f"  🔄 {display_name}: removed old roles [{removed_names}]")
                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to remove roles for {display_name}: {e}")

            # Add correct role if missing
            if not has_correct_role:
                correct_role = guild.get_role(correct_role_id)
                if correct_role:
                    try:
                        await member.add_roles(correct_role, reason=f"Power Tier earned: {tier_info['tier']} ({power_pts} pts)")
                        logger.info(f"  ✅ {display_name}: assigned {tier_info['tier']} role ({power_pts} pts)")
                        roles_updated += 1
                    except Exception as e:
                        logger.warning(f"  ⚠️ Failed to add {tier_info['tier']} role for {display_name}: {e}")
                else:
                    logger.warning(f"  ⚠️ Role {correct_role_id} ({tier_info['tier']}) not found in guild")

            # ── Wave Points Bonuses ──
            # Award one-time bonuses for all tiers the user qualifies for
            claimed = await get_claimed_tiers(user_id)

            for pt in POWER_TIERS:
                if power_pts >= pt['min_pts'] and pt['tier'] not in claimed:
                    try:
                        await add_wave_points(user_id, pt['wave_reward'], bot=bot)
                        await mark_tier_claimed(user_id, pt['tier'], pt['wave_reward'])
                        logger.info(
                            f"  🌊 {display_name}: +{pt['wave_reward']} Wave Points "
                            f"({pt['tier']} bonus — first time)"
                        )
                        bonuses_awarded += 1
                        total_wave_awarded += pt['wave_reward']
                    except Exception as e:
                        logger.warning(f"  ⚠️ Failed to award {pt['tier']} bonus for {display_name}: {e}")

        except Exception as e:
            logger.error(f"  ❌ Error processing {display_name}: {e}")
            logger.error(traceback.format_exc())

    logger.info(f"🏆 Power Rewards complete:")
    logger.info(f"  📊 Roles updated: {roles_updated}")
    logger.info(f"  🎁 Bonuses awarded: {bonuses_awarded}")
    logger.info(f"  🌊 Total Wave Points awarded: {total_wave_awarded}")


# ==================== ONE-TIME BACKFILL MIGRATION ====================

async def migrate_existing_badge_roles(bot, apply: bool = True) -> dict:
    """
    ONE-TIME backfill: give every current badge-holder their correct Power Points
    tier role in the Staff Hub guild WITHOUT awarding the wave-point bonuses.

    To stop the regular weekly sync from later back-paying these people, every
    tier a user currently qualifies for is recorded in `power_points_claimed`
    (reward amount logged) but the points are NOT added. New tiers earned after
    this migration still pay normally going forward.

    Reads duty scores from the `milestone_totals` DB table.

    Args:
        bot:   a connected Discord bot/client with member cache available
        apply: when False, only computes + returns the summary (no role/DB writes)

    Returns:
        summary dict with counts.
    """
    summary = {"qualified": 0, "roles_assigned": 0, "already_correct": 0,
               "wrong_removed": 0, "tiers_marked": 0, "not_in_guild": 0,
               "skipped_points": 0, "errors": 0}

    await init_power_points_claimed_table()

    guild = bot.get_guild(STAFF_HUB_GUILD_ID)
    if not guild:
        logger.error(f"  ❌ Staff Hub guild {STAFF_HUB_GUILD_ID} not found — migration aborted")
        return summary

    # Ensure the full member list is loaded before lookups.
    try:
        if not guild.chunked:
            await guild.chunk()
    except Exception as e:
        logger.warning(f"  ⚠️ Could not chunk guild members: {e}")

    # Load scores grouped by user from the milestone_totals table.
    pool = await database.get_pool()
    users: dict[int, dict] = {}
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT user_id, username, duty_type, total FROM milestone_totals"
        ) as cursor:
            async for user_id, username, duty_type, total in cursor:
                entry = users.setdefault(user_id, {"username": username, "scores": {}})
                entry["username"] = username
                if isinstance(total, (int, float)):
                    entry["scores"][duty_type] = int(total)

    logger.info(f"  📊 Backfill scanning {len(users)} users "
                f"({'APPLY' if apply else 'DRY RUN'})")

    for user_id, data in users.items():
        try:
            name = data["username"]
            power_pts = calculate_power_points(data["scores"])
            tier_info = get_power_tier(power_pts)
            if not tier_info:
                continue
            summary["qualified"] += 1

            member = guild.get_member(user_id)
            if member is None:
                summary["not_in_guild"] += 1
                continue

            correct_role_id = tier_info["role_id"]
            wrong_roles = [r for r in member.roles
                           if r.id in ALL_POWER_ROLE_IDS and r.id != correct_role_id]
            has_correct = any(r.id == correct_role_id for r in member.roles)
            qualifying_tiers = [t for t in POWER_TIERS if power_pts >= t["min_pts"]]

            if not apply:
                summary["roles_assigned"] += (0 if has_correct else 1)
                summary["already_correct"] += (1 if has_correct else 0)
                summary["wrong_removed"] += len(wrong_roles)
                summary["tiers_marked"] += len(qualifying_tiers)
                summary["skipped_points"] += sum(t["wave_reward"] for t in qualifying_tiers)
                logger.info(f"    · {name}: {power_pts} pts → {tier_info['tier']} "
                            f"({'has role' if has_correct else 'would assign'})")
                continue

            # ── APPLY ──
            if wrong_roles:
                try:
                    await member.remove_roles(*wrong_roles, reason=f"Power backfill → {tier_info['tier']}")
                    summary["wrong_removed"] += len(wrong_roles)
                except Exception as e:
                    logger.warning(f"    ⚠️ remove roles failed for {name}: {e}")

            if not has_correct:
                role = guild.get_role(correct_role_id)
                if role:
                    try:
                        await member.add_roles(role, reason=f"Power backfill: {tier_info['tier']} ({power_pts} pts, role only)")
                        summary["roles_assigned"] += 1
                        logger.info(f"    ✅ {name}: assigned {tier_info['tier']} ({power_pts} pts)")
                    except Exception as e:
                        summary["errors"] += 1
                        logger.warning(f"    ⚠️ add role failed for {name}: {e}")
                else:
                    summary["errors"] += 1
                    logger.warning(f"    ⚠️ role {correct_role_id} not found")
            else:
                summary["already_correct"] += 1

            # Mark every qualifying tier claimed WITHOUT paying.
            already = await get_claimed_tiers(user_id)
            for t in qualifying_tiers:
                if t["tier"] not in already:
                    try:
                        await mark_tier_claimed(user_id, t["tier"], t["wave_reward"])
                        summary["tiers_marked"] += 1
                        summary["skipped_points"] += t["wave_reward"]
                    except Exception as e:
                        logger.warning(f"    ⚠️ mark claimed {t['tier']} failed for {name}: {e}")

            await asyncio.sleep(0.4)  # gentle on the rate limit

        except Exception as e:
            summary["errors"] += 1
            logger.error(f"    ❌ error on user {user_id}: {e}")

    logger.info(f"  🏁 Backfill {'applied' if apply else 'dry-run'}: {summary}")
    return summary


# ==================== EXTENSION ENTRY POINT ====================
# This file is a utility module imported by tasks/staff_insights.py
# (`from tasks.power_points_rewards import sync_power_rewards`), not a cog.
# But main.py's cog discovery picks up every .py in tasks/, so we provide
# a no-op setup() to satisfy the loader instead of crashing on startup.
async def setup(bot):
    """No-op — this module is imported by other cogs, not loaded as a cog itself."""
    pass
