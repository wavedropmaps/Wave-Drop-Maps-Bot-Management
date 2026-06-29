"""
Maintenance Tasks
Background task for database VACUUM optimization every 6 hours.
Backups are handled separately by database_backups/database_backup.py (runs every 24h).
"""

from discord.ext import tasks, commands
from datetime import datetime, timedelta
import logging
import database
from core.global_logger import log_event as _wave_log_event
from tasks.staff_hub_writer import push_team_hierarchy_to_hub

logger = logging.getLogger('discord')


class MaintenanceTasks(commands.Cog):
    """Database maintenance — VACUUM only. Backups handled by database_backup.py."""

    def __init__(self, bot):
        self.bot = bot
        self.start_tasks()

    async def _get_last_run(self, task_name: str) -> datetime:
        try:
            last_run = await database.get_maintenance_last_run(task_name)
            if last_run:
                return datetime.fromisoformat(last_run)
            return datetime.min
        except Exception as e:
            logger.error(f"Error getting last run time for {task_name}: {e}")
            return datetime.min

    async def _set_last_run(self, task_name: str):
        try:
            await database.set_maintenance_last_run(task_name, datetime.now().isoformat())
        except Exception as e:
            logger.error(f"Error setting last run time for {task_name}: {e}")

    async def _should_run_task(self, task_name: str, interval_hours: int) -> bool:
        last_run = await self._get_last_run(task_name)
        time_since = datetime.now() - last_run
        should_run = time_since >= timedelta(hours=interval_hours)
        if not should_run:
            logger.debug(f"⏭️ Skipping {task_name} — last run {time_since.total_seconds()/3600:.1f}h ago (needs {interval_hours}h)")
        return should_run

    def start_tasks(self):
        if not self.auto_vacuum.is_running():
            self.auto_vacuum.start()
            logger.info("✅ Maintenance task started (VACUUM every 6h)")
        if not self.refresh_team_hierarchy.is_running():
            self.refresh_team_hierarchy.start()

    def stop_tasks(self):
        if self.auto_vacuum.is_running():
            self.auto_vacuum.cancel()
        if self.refresh_team_hierarchy.is_running():
            self.refresh_team_hierarchy.cancel()
        logger.info("✅ Maintenance task stopped")

    def cog_unload(self):
        self.stop_tasks()

    @tasks.loop(hours=6)
    async def auto_vacuum(self):
        """Run SQLite VACUUM every 6 hours to keep the DB optimised."""
        try:
            if not await self._should_run_task('database_maintenance', 6):
                return
            logger.info("🔧 Running VACUUM optimization...")
            start = datetime.now()
            await database.vacuum_database()
            await self._set_last_run('database_maintenance')
            elapsed = (datetime.now() - start).total_seconds()
            logger.info("✅ VACUUM complete")
            await _wave_log_event(
                category="maintenance",
                action="vacuum_complete",
                details={"elapsed_seconds": round(elapsed, 2)},
            )
        except Exception as e:
            logger.error(f"❌ Auto-vacuum failed: {e}")
            await _wave_log_event(
                category="maintenance",
                action="vacuum_failed",
                details={"error": str(e)},
            )

    @auto_vacuum.before_loop
    async def before_vacuum(self):
        await self.bot.wait_until_ready()

    @tasks.loop(hours=6)
    async def refresh_team_hierarchy(self):
        await push_team_hierarchy_to_hub(self.bot)

    @refresh_team_hierarchy.before_loop
    async def before_refresh_team(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(MaintenanceTasks(bot))
    logger.info("✅ Maintenance tasks cog loaded")
