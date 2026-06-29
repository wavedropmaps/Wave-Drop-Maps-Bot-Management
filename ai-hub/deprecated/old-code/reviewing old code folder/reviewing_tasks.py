import discord
from discord.ext import commands, tasks
import asyncio
import json
from datetime import datetime, timezone, date, timedelta
from database import (
    get_pool,
    get_all_reviewer_leaderboard_stats,
    cleanup_drop_map_reviewers,
    sync_reviewer_usernames,
    sync_role_with_database,
    recalculate_all_reviewer_tiers,
    get_daily_activity_summary,
)
import logging

logger = logging.getLogger(__name__)

# Debounce window for GitHub pushes. Each sync produces ~3 commits (drop_map,
# daily_summary, session_history); a longer window collapses bursts so we stay
# comfortably under GitHub Pages' soft limit of ~10 builds/hour.
_DEBOUNCE_SECONDS = 60

# Global debounce state
_debounce_drop_map_task = None
_debounce_drop_map_bot = None


async def auto_update_drop_map_leaderboard(bot, triggered_by="review_submitted", force=False):
    """
    AUTOMATIC TRIGGER on ANY data change.
    Debounces rapid changes (see _DEBOUNCE_SECONDS) into a single GitHub sync.

    Pass force=True for single manual admin commands to skip the debounce wait.

    Called from:
      - database.update_reviewer_tier()
      - database.apply_penalty()
      - database.update_accuracy_streak()
      - database.update_daily_streak()
      - commands (addpoints / endday)
    """
    global _debounce_drop_map_task, _debounce_drop_map_bot

    # Cancel any pending update
    if _debounce_drop_map_task:
        try:
            _debounce_drop_map_task.cancel()
        except:
            pass

    _debounce_drop_map_bot = bot

    if force:
        _debounce_drop_map_task = asyncio.create_task(_do_update_drop_map_leaderboard())
    else:
        _debounce_drop_map_task = asyncio.create_task(
            _wait_then_update_drop_map_leaderboard()
        )


async def _wait_then_update_drop_map_leaderboard():
    try:
        await asyncio.sleep(_DEBOUNCE_SECONDS)
        await _do_update_drop_map_leaderboard()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"❌ Error in drop map leaderboard update: {e}")


async def _do_update_drop_map_leaderboard():
    """
    Actually fetch ALL reviewer stats, save locally, then push to GitHub.
    Runs once per debounce window (see _DEBOUNCE_SECONDS).
    (Works like duties_scan - save locally first, THEN push)
    """
    global _debounce_drop_map_task
    import os

    try:
        all_stats = await get_all_reviewer_leaderboard_stats()

        logger.info(f"📊 Fetched {len(all_stats)} reviewers from database")

        # ── INJECT PROVISIONAL TEMP DATA ──
        # Unverified TEMP rows for today count as provisional and are shown on leaderboard
        try:
            from database import get_pool as get_db_pool
            pool = await get_db_pool()
            async with pool.acquire() as db:
                async with db.execute(
                    """SELECT user_id,
                              SUM(provisional_points),
                              MAX(provisional_accuracy_streak),
                              MAX(provisional_daily_streak),
                              SUM(markers_reviewed)
                       FROM reviewers_temp
                       WHERE verified = 0
                       GROUP BY user_id""",
                ) as cursor:
                    prov_rows = await cursor.fetchall()

            provisional_by_user = {}
            for row in prov_rows:
                uid = row[0] if isinstance(row, tuple) else row['user_id']
                pts = row[1] if isinstance(row, tuple) else row[1]
                acc_streak = row[2] if isinstance(row, tuple) else row[2]
                daily_streak = row[3] if isinstance(row, tuple) else row[3]
                markers = row[4] if isinstance(row, tuple) else row[4]
                provisional_by_user[uid] = {
                    'points': round(pts or 0, 2),
                    'accuracy_streak': acc_streak or 0,
                    'daily_streak': daily_streak or 0,
                    'reviews': markers or 0
                }

            for stat in all_stats:
                prov = provisional_by_user.get(stat['user_id'], {})
                prov_acc = prov.get('accuracy_streak', 0)
                prov_daily = prov.get('daily_streak', 0)
                stat['provisional_points'] = prov.get('points', 0)
                stat['points_display'] = round(stat['points'] + prov.get('points', 0), 2)
                stat['provisional_accuracy_streak'] = prov_acc
                # provisional_acc is already the full total (base + new markers), use directly
                stat['accuracy_streak_display'] = prov_acc if prov_acc > 0 else stat['accuracy_streak']
                stat['provisional_daily_streak'] = prov_daily
                # provisional_daily is already the full total, use directly
                stat['daily_streak_display'] = prov_daily if prov_daily > 0 else stat['daily_streak']
                stat['provisional_reviews'] = prov.get('reviews', 0)
                stat['reviews_display'] = stat['reviews'] + prov.get('reviews', 0)
        except Exception as e:
            logger.debug(f"Could not inject provisional TEMP data: {e}")
            for stat in all_stats:
                stat['provisional_points'] = 0
                stat['points_display'] = stat['points']
                stat['provisional_accuracy_streak'] = 0
                stat['accuracy_streak_display'] = stat['accuracy_streak']
                stat['provisional_daily_streak'] = 0
                stat['daily_streak_display'] = stat['daily_streak']
                stat['provisional_reviews'] = 0
                stat['reviews_display'] = stat['reviews']

        # ── COMPUTE TIER-UP GAP ──
        # For each non-Master reviewer, find the smallest N where adding N correct markers
        # to their last-30 window would push their accuracy across the next tier threshold.
        # Optimistic projection (assumes claimed-correct) — matches the provisional model.
        TIER_LADDER = ['Beginner', 'Intermediate', 'Advanced', 'Expert', 'Master']
        TIER_THRESHOLDS_LB = {'Intermediate': 76.67, 'Advanced': 83.33, 'Expert': 90, 'Master': 96.67}
        try:
            pool2 = await get_db_pool()
            async with pool2.acquire() as db2:
                for stat in all_stats:
                    current_tier = stat.get('tier', 'Beginner') or 'Beginner'
                    if current_tier == 'Master' or current_tier not in TIER_LADDER:
                        stat['next_tier_name'] = None
                        stat['next_tier_markers_needed'] = None
                        stat['next_tier_threshold'] = None
                        continue
                    next_tier_name = TIER_LADDER[TIER_LADDER.index(current_tier) + 1]
                    next_threshold = TIER_THRESHOLDS_LB[next_tier_name]
                    user_id = stat['user_id']
                    async with db2.execute("""
                        SELECT correct FROM (
                            SELECT correct, timestamp, id FROM reviewer_markers WHERE reviewer_id = ?
                            UNION ALL
                            SELECT correct, timestamp, id FROM ghost_markers WHERE reviewer_id = ?
                        ) ORDER BY timestamp DESC, id DESC LIMIT 30
                    """, (user_id, user_id)) as cursor:
                        rows = await cursor.fetchall()
                    current_window = [bool(r[0]) for r in rows]
                    gap = None
                    for n in range(1, 51):
                        total_after = min(len(current_window) + n, 30)
                        if total_after < 5:
                            continue
                        if n >= 30:
                            projected_acc = 100.0
                        else:
                            surviving = current_window[:max(0, 30 - n)]
                            projected_acc = (n + sum(1 for v in surviving if v)) / total_after * 100
                        if projected_acc >= next_threshold:
                            gap = n
                            break
                    stat['next_tier_name'] = next_tier_name if gap else None
                    stat['next_tier_markers_needed'] = gap
                    stat['next_tier_threshold'] = next_threshold if gap else None
        except Exception as e:
            logger.debug(f"Could not compute tier-up gaps: {e}")
            for stat in all_stats:
                stat.setdefault('next_tier_name', None)
                stat.setdefault('next_tier_markers_needed', None)
                stat.setdefault('next_tier_threshold', None)

        # Enrich with Discord user data (display name + avatar URL).
        # IMPORTANT: prefer the in-memory cache (get_user) — fetch_user hits
        # /users/{id} and is the main culprit when this task runs on every
        # admin action (16+ reviewers × frequent triggers → user rate limit).
        bot = _debounce_drop_map_bot
        if bot:
            for stat in all_stats:
                user = bot.get_user(stat['user_id'])
                if user is None:
                    try:
                        user = await bot.fetch_user(stat['user_id'])
                    except Exception as e:
                        logger.debug(f"Could not fetch Discord user {stat['user_id']}: {e}")
                        user = None
                if user is not None:
                    stat['display_name'] = user.display_name or user.name
                    stat['avatar_url'] = user.display_avatar.url if user.display_avatar else None
                else:
                    stat['display_name'] = f"User {stat['user_id']}"
                    stat['avatar_url'] = None

        # Build JSON payload (matches HTML expectations)
        payload = {
            "reviewers": all_stats,
            "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        # ── SAVE LOCALLY FIRST (like duties_scan does) ──
        json_path = os.path.join(os.path.dirname(__file__), '..', 'json_data', 'drop_map_reviewing.json')
        logger.info(f"💾 Saving to {json_path}...")
        try:
            with open(json_path, 'w') as f:
                json.dump(payload, f, indent=2)
            logger.info(f"✅ Saved drop_map_reviewing.json locally")
        except Exception as e:
            logger.error(f"❌ Failed to save locally: {e}")
            # Continue anyway - still try to push to GitHub

        # ── THEN PUSH TO GITHUB ──
        logger.info(f"🔗 Pushing to GitHub ({len(all_stats)} reviewers)...")
        try:
            from tasks.staff_hub_writer import push_drop_map_leaderboard_to_github, push_daily_summary_to_github

            success = await push_drop_map_leaderboard_to_github(payload)

            if success:
                logger.info(f"✅ Drop map leaderboard synced to GitHub ({len(all_stats)} reviewers)")
            else:
                logger.error(f"❌ GitHub push failed - check logs and config.json token")

            # Push daily summary for the CURRENT session.
            # The bot's clock is session-based (>newday … >closeday), NOT calendar-based —
            # a "day" might be 1 hour or several real days, so we must not filter by
            # date('now', '-N days'). Just pick whichever session is open right now;
            # if nothing is open, fall back to the most recently closed session.
            try:
                from database import get_pool as get_db_pool
                pool = await get_db_pool()
                async with pool.acquire() as db:
                    async with db.execute(
                        """SELECT guild_id, session_date FROM daily_sessions
                           WHERE is_open = 1
                           ORDER BY opened_at DESC LIMIT 1"""
                    ) as cursor:
                        target_row = await cursor.fetchone()
                    if not target_row:
                        async with db.execute(
                            """SELECT guild_id, session_date FROM daily_sessions
                               ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT 1"""
                        ) as cursor:
                            target_row = await cursor.fetchone()

                if target_row:
                    guild_id = target_row[0] if isinstance(target_row, tuple) else target_row['guild_id']
                    session_date = target_row[1] if isinstance(target_row, tuple) else target_row['session_date']

                    summary = await get_daily_activity_summary(guild_id, session_date)

                    session_date_str = session_date if isinstance(session_date, str) else session_date.isoformat()
                    try:
                        from database import get_challenges_for_session
                        challenges_for_date = await get_challenges_for_session(session_date_str)
                    except Exception as e:
                        logger.debug(f"Could not load challenges for {session_date_str}: {e}")
                        challenges_for_date = []

                    summary_payload = {
                        "date": session_date_str,
                        "guild_id": guild_id,
                        "summary": {
                            "total_points": summary['total_points'],
                            "total_markers": summary['total_markers'],
                            "active_reviewers": summary['active_reviewers'],
                            "tier_promotions": summary['tier_promotions'],
                            "milestone_hits": summary['milestone_hits']
                        },
                        "activities": summary['activities'],
                        "challenges": challenges_for_date,
                        "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                    }

                    success = await push_daily_summary_to_github(summary_payload)
                    if success:
                        logger.info(f"✅ Daily summary pushed for {session_date_str} ({len(challenges_for_date)} challenges)")
                    else:
                        logger.error(f"❌ Daily summary push failed for {session_date_str}")
                else:
                    logger.debug("No open or closed sessions found — skipping daily summary push")
            except Exception as e:
                logger.error(f"❌ Error pushing daily summary: {e}")
                import traceback
                logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"❌ GitHub push exception: {e}")

    except Exception as e:
        logger.error(f"❌ Error updating drop map leaderboard: {e}")
        import traceback
        logger.error(traceback.format_exc())

    finally:
        _debounce_drop_map_task = None


class ReviewingTasks(commands.Cog):
    """Background tasks for drop map reviewing system"""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Sync roles/usernames, clean up reviewers, and sync database to GitHub on bot startup"""
        if not self.bot.user:
            return

        # Sync Discord role members with database
        logger.info("🔗 Syncing Discord role members with database...")
        await sync_role_with_database(self.bot)

        # Sync Discord usernames with database (handles username changes)
        logger.info("🔄 Syncing Discord usernames with database...")
        await sync_reviewer_usernames(self.bot)

        # Clean up reviewers without the role and set accuracy to 100%
        logger.info("🧹 Cleaning up drop map reviewers (removing non-reviewers, setting 100% accuracy)...")
        await cleanup_drop_map_reviewers(self.bot)

        # Recalculate all reviewer tiers based on last 30 markers
        logger.info("📊 Recalculating reviewer ranks based on accuracy...")
        await recalculate_all_reviewer_tiers()

        # Sync database to GitHub
        logger.info("📊 Syncing drop map reviewing data to GitHub on startup...")
        await auto_update_drop_map_leaderboard(self.bot, triggered_by="bot_startup")


async def setup(bot):
    await bot.add_cog(ReviewingTasks(bot))
