"""
Daily market tracker collection at 14:05 UTC.
Runs guild-stats, market-research, and drop-map-research collects sequentially.
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from discord.ext import commands, tasks

logger = logging.getLogger("discord")

REPO_ROOT = Path(__file__).resolve().parent.parent
COLLECT_SCRIPTS = [
    ("guild-stats", REPO_ROOT / "command-trackers" / "guild-stats" / "scripts" / "collect.py", 120),
    ("market-research", REPO_ROOT / "command-trackers" / "market-research" / "scripts" / "collect.py", 300),
    ("drop-map-research", REPO_ROOT / "command-trackers" / "drop-map-research" / "scripts" / "collect.py", 900),
]

COLLECT_HOUR_UTC = 14
COLLECT_MINUTE_UTC = 5


async def _run_collect(name: str, script: Path, timeout: int) -> tuple[bool, str]:
    if not script.exists():
        return False, f"script missing: {script}"
    env = {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script), "--no-browser",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(REPO_ROOT),
            env=env,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        ok = proc.returncode == 0
        tail = (stderr_b or stdout_b).decode("utf-8", errors="replace").strip()[-400:]
        return ok, tail if not ok else "ok"
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return False, f"timed out after {timeout}s"
    except Exception as e:
        return False, str(e)


class MarketTrackerLoop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_collect_loop.start()

    def cog_unload(self):
        self.daily_collect_loop.cancel()

    @tasks.loop(hours=24)
    async def daily_collect_loop(self):
        await self.bot.wait_until_ready()
        logger.info("📊 Starting daily market tracker collect chain (14:05 UTC)...")
        results = []
        for name, script, timeout in COLLECT_SCRIPTS:
            ok, msg = await _run_collect(name, script, timeout)
            status = "✅" if ok else "❌"
            logger.info(f"📊 {status} {name} collect: {msg[:200]}")
            results.append((name, ok, msg))

        overview_script = REPO_ROOT / "command-trackers" / "market-overview" / "scripts" / "generate_overview.py"
        if overview_script.exists():
            ok, msg = await _run_collect("market-overview", overview_script, 60)
            logger.info(f"📊 {'✅' if ok else '❌'} market-overview: {msg[:200]}")

        failed = [n for n, ok, _ in results if not ok]
        if failed:
            logger.warning(f"📊 Daily collect finished with failures: {', '.join(failed)}")
        else:
            logger.info("📊 Daily market tracker collect chain completed successfully.")

    @daily_collect_loop.before_loop
    async def _before_daily_collect(self):
        await self.bot.wait_until_ready()
        now = datetime.now(timezone.utc)
        target = now.replace(hour=COLLECT_HOUR_UTC, minute=COLLECT_MINUTE_UTC, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        sleep_s = (target - now).total_seconds()
        logger.info(
            f"📊 Market tracker loop sleeping {sleep_s / 3600:.1f}h "
            f"until {target.strftime('%Y-%m-%d %H:%M')} UTC"
        )
        await asyncio.sleep(sleep_s)


async def setup(bot):
    await bot.add_cog(MarketTrackerLoop(bot))
    logger.info("✅ MarketTrackerLoop cog loaded")
