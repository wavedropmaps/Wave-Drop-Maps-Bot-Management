"""
tasks/tipsandtricks.py — Tips & Tricks Helper System background tasks.

Loops:
  bonus_check   — every 1h: bump unclaimed 7-day tasks to 2 pts
  weekly_mvp    — every Monday ~09:00 UTC: announce top helper

Exports:
  schedule_leaderboard_push(bot)  — debounced (1.5 s) leaderboard JSON build + GitHub push
                                    called from commands and database_tipsandtricks.complete_task
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands, tasks

import core.tipsandtricks_config as cfg
import database_tipsandtricks as db_tt
from core.helpers import web_avatar_url
from tasks.staff_hub_writer import push_tips_tricks_leaderboard_to_github

logger = logging.getLogger('discord')

# ── Debounce state ─────────────────────────────────────────────────────────
_push_task: Optional[asyncio.Task] = None


async def schedule_leaderboard_push(bot):
    """Debounced leaderboard push — cancels any pending push and schedules a new one 1.5s out."""
    global _push_task
    if _push_task and not _push_task.done():
        _push_task.cancel()
    _push_task = asyncio.create_task(_delayed_push(bot))


async def _delayed_push(bot):
    await asyncio.sleep(1.5)
    await push_leaderboard(bot)


# ── Discord resolution helper ──────────────────────────────────────────────

async def _resolve_user(bot, user_id: int) -> dict:
    """Return name + avatar_url for a user.  Tries guild cache first, then API fetch."""
    guild = bot.get_guild(cfg.GUILD_ID)
    if guild:
        member = guild.get_member(user_id)
        if member:
            return {"name": member.display_name, "avatar_url": web_avatar_url(member.display_avatar)}
    try:
        user = await bot.fetch_user(user_id)
        return {"name": str(user), "avatar_url": web_avatar_url(user.display_avatar)}
    except Exception:
        return {"name": f"User {user_id}", "avatar_url": ""}


# ── Leaderboard builder ────────────────────────────────────────────────────

async def push_leaderboard(bot):
    """
    Build tips_tricks_leaderboard.json and push to the wave-leaderboard GitHub repo.

    JSON schema:
      _meta:        { last_updated }
      leaderboard:  [ { user_id, name, avatar_url, total_points,
                        tasks_completed, lucky_tasks_completed, rank_delta } ]
      tasks:        [ { task_id, description, point_value, is_lucky, bonus_active,
                        status, created_at, claimed_by_id, claimed_by_name,
                        claimed_by_avatar } ]
      duties:       [ { code, name, assigned_user_id, assigned_name,
                        assigned_avatar, assigned_at } ]
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        snapshot_path = Path(cfg.TT_RANK_SNAPSHOT)

        # Load previous rank snapshot for delta calculation
        prev_ranks: dict = {}
        if snapshot_path.exists():
            try:
                prev_ranks = json.loads(snapshot_path.read_text(encoding='utf-8'))
            except Exception:
                pass

        # ── Leaderboard entries ────────────────────────────────────────────
        raw_lb = await db_tt.get_leaderboard()
        leaderboard = []
        new_snapshot: dict = {}

        for rank, row in enumerate(raw_lb, 1):
            uid = row['user_id']
            info = await _resolve_user(bot, uid)
            prev = prev_ranks.get(str(uid), rank)
            delta = prev - rank  # positive = moved up

            leaderboard.append({
                "user_id":               uid,
                "name":                  info["name"],
                "avatar_url":            info["avatar_url"],
                "total_points":          row['total_points'],
                "tasks_completed":       row['tasks_completed'],
                "lucky_tasks_completed": row['lucky_tasks_completed'],
                "rank_delta":            delta,
            })
            new_snapshot[str(uid)] = rank

        # Save updated snapshot
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(new_snapshot, indent=2), encoding='utf-8')

        # ── Tasks (available + claimed only — completed are archived) ──────
        all_tasks = await db_tt.get_all_tasks()
        tasks_out = []
        for t in all_tasks:
            claimed_name = claimed_avatar = None
            if t['claimed_by']:
                info = await _resolve_user(bot, t['claimed_by'])
                claimed_name = info['name']
                claimed_avatar = info['avatar_url']

            tasks_out.append({
                "task_id":         t['task_id'],
                "description":     t['description'],
                "point_value":     t['base_points'],
                "is_lucky":        bool(t['is_lucky']),
                "bonus_active":    bool(t['bonus_applied']),
                "status":          t['status'],
                "created_at":      t['created_at'],
                "claimed_by_id":   t['claimed_by'],
                "claimed_by_name": claimed_name,
                "claimed_by_avatar": claimed_avatar,
            })

        # ── Duty assignments ───────────────────────────────────────────────
        assignments = await db_tt.get_duty_assignments()
        duties_out = []
        for code in cfg.DUTY_CODES:
            entry: dict = {
                "code":             code,
                "name":             cfg.DUTY_NAMES[code],
                "assignees":        []
            }
            if code in assignments:
                for a in assignments[code]:
                    uid = a['user_id']
                    info = await _resolve_user(bot, uid)
                    entry["assignees"].append({
                        "user_id": uid,
                        "name":    info['name'],
                        "avatar":  info['avatar_url'],
                        "assigned_at": a['assigned_at']
                    })
            duties_out.append(entry)

        payload = {
            "_meta":       {"last_updated": now_iso},
            "leaderboard": leaderboard,
            "tasks":       tasks_out,
            "duties":      duties_out,
        }

        await push_tips_tricks_leaderboard_to_github(payload)

    except Exception as e:
        logger.error(f"❌ [T&T] Leaderboard push failed: {e}", exc_info=True)


# ── Background loops ───────────────────────────────────────────────────────

class TipsAndTricksTasksCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bonus_check.start()
        self.weekly_mvp.start()

    def cog_unload(self):
        self.bonus_check.cancel()
        self.weekly_mvp.cancel()

    @tasks.loop(hours=1)
    async def bonus_check(self):
        """Every hour: bump any 7-day-unclaimed tasks to 2 pts, then push."""
        try:
            count = await db_tt.apply_unclaimed_bonus()
            if count:
                logger.info(f"[T&T] Bonus applied to {count} unclaimed task(s)")
                await push_leaderboard(self.bot)
        except Exception as e:
            logger.error(f"[T&T] bonus_check error: {e}")

    @bonus_check.before_loop
    async def before_bonus_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def weekly_mvp(self):
        """Fire on Mondays to announce the week's top helper."""
        try:
            now = datetime.now(timezone.utc)
            if now.weekday() != 0:  # 0 = Monday
                return
            if not cfg.TT_ANNOUNCEMENTS_CHANNEL_ID:
                return

            lb = await db_tt.get_leaderboard()
            if not lb:
                return

            top = lb[0]
            guild = self.bot.get_guild(cfg.GUILD_ID)
            if not guild:
                return

            ch = guild.get_channel(cfg.TT_ANNOUNCEMENTS_CHANNEL_ID)
            if not ch:
                return

            member = guild.get_member(top['user_id'])
            name = member.mention if member else f"User {top['user_id']}"

            embed = discord.Embed(
                title="🏆 Weekly T&T MVP",
                description=f"{name} leads the Tips & Tricks leaderboard!",
                color=0xFFD700,
            )
            embed.add_field(name="Points", value=f"{top['total_points']:g}")
            embed.add_field(name="Tasks Completed", value=str(top['tasks_completed']))
            await ch.send(embed=embed)

        except Exception as e:
            logger.error(f"[T&T] weekly_mvp error: {e}")

    @weekly_mvp.before_loop
    async def before_weekly_mvp(self):
        await self.bot.wait_until_ready()
        # Align to 09:00 UTC
        now = datetime.now(timezone.utc)
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())


async def setup(bot):
    await bot.add_cog(TipsAndTricksTasksCog(bot))
    logger.info("✅ TipsAndTricksTasksCog loaded")
