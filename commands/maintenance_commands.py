"""
Maintenance Commands (Admin)
Database maintenance and administration commands
"""

import discord
from discord.ext import commands
import asyncio
import psutil
import os
import sys
from datetime import datetime, timezone
import logging

import database

logger = logging.getLogger('discord')

MANAGEMENT_ROLES = ('007', '+', 'Management')

class MaintenanceCommands(commands.Cog):
    """MAINTENANCE (Admin) - Database maintenance and administration"""
    
    def __init__(self, bot):
        self.bot = bot

    # ==================== >poolstats ====================

    @commands.command(name='poolstats', help='View database connection pool health')
    @commands.has_any_role(*MANAGEMENT_ROLES)
    async def poolstats(self, ctx):
        """Show database connection pool performance metrics. Usage: >poolstats"""
        try:
            pool = await database.get_pool()

            available = len(pool._connections)
            total     = pool.pool_size
            active    = total - available
            usage_pct = int((active / total) * 100) if total > 0 else 0

            if usage_pct < 50:
                health = "🟢 Healthy"
                color  = discord.Color.green()
            elif usage_pct < 80:
                health = "🟡 Moderate Load"
                color  = discord.Color.gold()
            else:
                health = "🔴 High Load"
                color  = discord.Color.red()

            embed = discord.Embed(
                title="🔌 Database Connection Pool Stats",
                description=f"**Health:** {health}",
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(
                name="📊 Pool Status",
                value=(
                    f"**Total Connections:** {total}\n"
                    f"**Available:** {available}\n"
                    f"**Active Queries:** {active}\n"
                    f"**Usage:** {usage_pct}%"
                ),
                inline=False
            )
            embed.add_field(
                name="⚙️ Configuration",
                value=(
                    f"**Pool Size:** {pool.pool_size}\n"
                    f"**Database:** {pool.db_file}\n"
                    f"**Status:** {'✅ Initialized' if pool._initialized else '❌ Not initialized'}"
                ),
                inline=False
            )
            if usage_pct > 80:
                rec = "⚠️ **Warning:** Pool usage is high. Consider increasing pool size or optimising queries."
            elif usage_pct < 20:
                rec = "✅ **Healthy:** Pool has plenty of available connections."
            else:
                rec = "✅ **Normal:** Pool is operating within healthy parameters."
            embed.add_field(name="💡 Recommendation", value=rec, inline=False)
            embed.set_footer(text="Pool stats update in real-time")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in poolstats: {e}")
            await ctx.send(embed=discord.Embed(title="❌ Pool Stats Error", description=str(e), color=discord.Color.red()))

    # ==================== >testdb ====================

    @commands.command(name='testdb', help='Test database connection')
    @commands.has_any_role(*MANAGEMENT_ROLES)
    async def testdb(self, ctx):
        """Test that the database connection is alive. Usage: >testdb"""
        try:
            start = datetime.now()
            pool = await database.get_pool()
            async with pool.acquire() as db:
                async with db.execute('SELECT 1') as cursor:
                    await cursor.fetchone()
            elapsed_ms = (datetime.now() - start).total_seconds() * 1000

            embed = discord.Embed(
                title="✅ Database Connection OK",
                description=f"Round-trip: **{elapsed_ms:.1f}ms**",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="📁 File", value=pool.db_file, inline=True)
            embed.add_field(name="🔌 Pool", value=f"{'✅ Ready' if pool._initialized else '⚠️ Not init'}", inline=True)
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in testdb: {e}")
            await ctx.send(embed=discord.Embed(
                title="❌ Database Connection FAILED",
                description=str(e),
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            ))

    # ==================== >cachestats ====================

    @commands.command(name='cachestats', help='View cache and database stats')
    @commands.has_any_role(*MANAGEMENT_ROLES)
    async def cachestats(self, ctx):
        """Show SQLite cache, Discord cache, and memory stats. Usage: >cachestats"""
        try:
            embed = discord.Embed(
                title="📦 Cache & Database Stats",
                color=discord.Color.purple(),
                timestamp=datetime.now(timezone.utc)
            )

            # SQLite page cache stats — queried directly from the DB
            # FIX: bot.query_cache is never set in main.py, so we read PRAGMA stats instead
            try:
                pool = await database.get_pool()
                async with pool.acquire() as db:
                    async with db.execute("PRAGMA cache_size") as c:
                        cache_size_pages = (await c.fetchone())[0]
                    async with db.execute("PRAGMA page_size") as c:
                        page_size = (await c.fetchone())[0]
                    async with db.execute("PRAGMA page_count") as c:
                        page_count = (await c.fetchone())[0]
                    async with db.execute("PRAGMA freelist_count") as c:
                        freelist = (await c.fetchone())[0]
                    async with db.execute("PRAGMA wal_autocheckpoint") as c:
                        wal_checkpoint = (await c.fetchone())[0]
                    async with db.execute("PRAGMA journal_mode") as c:
                        journal_mode = (await c.fetchone())[0]

                # Negative cache_size = KB; positive = pages
                cache_str  = f"{abs(cache_size_pages) / 1024:.0f} MB" if cache_size_pages < 0 else f"{cache_size_pages:,} pages"
                db_size_mb = (page_count * page_size) / (1024 * 1024)
                free_mb    = (freelist * page_size) / (1024 * 1024)

                embed.add_field(
                    name="🗄️ SQLite Cache",
                    value=(
                        f"**Allocated Cache:** {cache_str}\n"
                        f"**Journal Mode:** {journal_mode.upper()}\n"
                        f"**WAL Checkpoint:** every {wal_checkpoint:,} pages\n"
                        f"**DB Size:** {db_size_mb:.2f} MB\n"
                        f"**Reclaimable Space:** {free_mb:.2f} MB (run `>vacuum`)"
                    ),
                    inline=False
                )
            except Exception as e:
                embed.add_field(name="🗄️ SQLite Cache", value=f"❌ Error: {e}", inline=False)

            # Discord internal cache
            try:
                embed.add_field(
                    name="🤖 Discord Cache",
                    value=(
                        f"**Guilds:** {len(self.bot.guilds)}\n"
                        f"**Users:** {len(self.bot.users):,}\n"
                        f"**Channels:** {len(list(self.bot.get_all_channels())):,}\n"
                        f"**Emojis:** {len(self.bot.emojis):,}"
                    ),
                    inline=False
                )
            except Exception as e:
                embed.add_field(name="🤖 Discord Cache", value=f"❌ Error: {e}", inline=False)

            # Memory
            try:
                process = psutil.Process(os.getpid())
                mem     = process.memory_info()
                embed.add_field(
                    name="🧠 Memory",
                    value=f"**RSS:** {mem.rss / 1024 / 1024:.1f} MB\n**Virtual:** {mem.vms / 1024 / 1024:.1f} MB",
                    inline=True
                )
            except Exception as e:
                embed.add_field(name="🧠 Memory", value=f"❌ Error: {e}", inline=True)

            embed.set_footer(text=f"Requested by {ctx.author}")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in cachestats: {e}")
            await ctx.send(embed=discord.Embed(title="❌ Cache Stats Error", description=str(e), color=discord.Color.red()))

    # ==================== >vacuum ====================

    @commands.command(name='vacuum', help='Optimize database performance')
    @commands.has_any_role(*MANAGEMENT_ROLES)
    async def vacuum(self, ctx):
        """Run SQLite VACUUM to reclaim space and optimise the database. Usage: >vacuum"""
        msg = await ctx.send(embed=discord.Embed(
            title="🔄 Optimising Database...",
            description="Running VACUUM — this may take a moment.",
            color=discord.Color.orange()
        ))
        try:
            start = datetime.now()
            pool  = await database.get_pool()
            async with pool.acquire() as db:
                # FIX: VACUUM cannot run inside a transaction.
                # Roll back any implicit open transaction on this connection first.
                try:
                    await db.rollback()
                except Exception:
                    pass
                await db.execute('VACUUM')
                await db.execute('PRAGMA optimize')
                # No commit — VACUUM and PRAGMA optimize are DDL, not transactional
            elapsed = (datetime.now() - start).total_seconds()

            embed = discord.Embed(
                title="✅ Database Optimised",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="⏱️ Duration", value=f"**{elapsed:.2f}s**", inline=True)
            embed.add_field(name="📁 Database", value=pool.db_file, inline=True)
            embed.set_footer(text="💡 Tip: Run this weekly for best performance")
            await msg.edit(embed=embed)

        except Exception as e:
            logger.error(f"Error in vacuum: {e}")
            await msg.edit(embed=discord.Embed(
                title="❌ Vacuum Failed",
                description=str(e),
                color=discord.Color.red()
            ))

    # ==================== >bothealth ====================

    @commands.command(name='bothealth', aliases=['health', 'status'], help='Full bot health dashboard in one embed')
    @commands.has_any_role(*MANAGEMENT_ROLES)
    async def bothealth(self, ctx):
        """
        All-in-one bot health dashboard.
        Shows uptime, latency, DB pool, cache, memory, and scheduled task status.
        Usage: >bothealth
        """
        try:
            embed = discord.Embed(
                title="🏥 Bot Health Dashboard",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            # ── UPTIME & LATENCY ──────────────────────────────────────────
            latency_ms = round(self.bot.latency * 1000, 1)
            lat_icon   = "🟢" if latency_ms < 100 else ("🟡" if latency_ms < 250 else "🔴")

            # FIX: main.py sets bot.launch_time = None at module load,
            # so hasattr() is always True — must also check for None
            launch_time = getattr(self.bot, 'launch_time', None)
            if launch_time is not None:
                delta      = datetime.now() - launch_time
                total_s    = int(delta.total_seconds())
                uptime_str = f"{total_s // 86400}d {(total_s % 86400) // 3600}h {(total_s % 3600) // 60}m"
            else:
                uptime_str = "Unknown (bot still starting)"

            embed.add_field(
                name="⏰ Uptime & Latency",
                value=(
                    f"**Uptime:** {uptime_str}\n"
                    f"**Latency:** {lat_icon} {latency_ms}ms\n"
                    f"**Servers:** {len(self.bot.guilds)}\n"
                    f"**Users cached:** {len(self.bot.users):,}"
                ),
                inline=True
            )

            # ── SYSTEM RESOURCES ──────────────────────────────────────────
            try:
                process  = psutil.Process(os.getpid())
                mem_mb   = process.memory_info().rss / 1024 / 1024
                cpu_pct  = process.cpu_percent(interval=0.1)
                mem_icon = "🟢" if mem_mb < 300 else ("🟡" if mem_mb < 600 else "🔴")
                res_val  = (
                    f"**Memory:** {mem_icon} {mem_mb:.1f} MB\n"
                    f"**CPU:** {cpu_pct:.1f}%\n"
                    f"**PID:** {os.getpid()}"
                )
            except Exception as e:
                res_val = f"❌ Error: {e}"

            embed.add_field(name="🧠 System Resources", value=res_val, inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            # ── DATABASE POOL ─────────────────────────────────────────────
            try:
                pool      = await database.get_pool()
                available = len(pool._connections)
                total     = pool.pool_size
                active    = total - available
                usage_pct = int((active / total) * 100) if total > 0 else 0
                pool_icon = "🟢" if usage_pct < 50 else ("🟡" if usage_pct < 80 else "🔴")
                db_val    = (
                    f"**Status:** {pool_icon} {usage_pct}% used\n"
                    f"**Active:** {active} / {total} connections\n"
                    f"**File:** {pool.db_file}"
                )
            except Exception as e:
                db_val = f"❌ Error: {e}"

            embed.add_field(name="🗄️ Database Pool", value=db_val, inline=True)

            # ── DB CACHE ──────────────────────────────────────────────────
            try:
                pool = await database.get_pool()
                async with pool.acquire() as db:
                    async with db.execute("PRAGMA page_count") as c:
                        page_count = (await c.fetchone())[0]
                    async with db.execute("PRAGMA page_size") as c:
                        page_size = (await c.fetchone())[0]
                    async with db.execute("PRAGMA freelist_count") as c:
                        freelist = (await c.fetchone())[0]
                    async with db.execute("PRAGMA journal_mode") as c:
                        journal_mode = (await c.fetchone())[0]

                db_size_mb = (page_count * page_size) / (1024 * 1024)
                free_mb    = (freelist * page_size) / (1024 * 1024)
                cache_val  = (
                    f"**Mode:** {journal_mode.upper()}\n"
                    f"**DB Size:** {db_size_mb:.2f} MB\n"
                    f"**Reclaimable:** {free_mb:.2f} MB"
                )
            except Exception as e:
                cache_val = f"❌ Error: {e}"

            embed.add_field(name="📦 DB Cache", value=cache_val, inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            # ── SCHEDULED TASKS ───────────────────────────────────────────
            scheduled = [
                ('cleanup_old_cache',         'DB Cleanup'),
                ('check_midweek_reports',     'Mid-Week Reports'),
                ('check_fullweek_reports',    'Full Week Reports'),
                ('check_inactivity_warnings', 'Inactivity Warnings'),
                ('update_live_leaderboards',  'Live Leaderboards'),
                ('auto_backup_database',      'Auto-Backup'),
                ('automated_cache_refresh',   'Cache Refresh'),
            ]

            # FIX: tasks live in cog modules not just __main__.
            # Scan all loaded modules that could contain task loops.
            task_globals = {}
            for mod_name, mod in sys.modules.items():
                if mod is None:
                    continue
                if mod_name in ('__main__', 'main') or mod_name.startswith(('commands.', 'tasks.', 'cogs.')):
                    try:
                        task_globals.update(vars(mod))
                    except TypeError:
                        pass

            task_lines = []
            for task_name, display in scheduled:
                task_obj = task_globals.get(task_name)
                if task_obj and hasattr(task_obj, 'is_running'):
                    if task_obj.is_running():
                        try:
                            nxt = task_obj.next_iteration
                            if nxt:
                                secs = (nxt - datetime.now(timezone.utc)).total_seconds()
                                if secs > 86400:
                                    eta = f"next in {secs/86400:.1f}d"
                                elif secs > 3600:
                                    eta = f"next in {secs/3600:.1f}h"
                                else:
                                    eta = f"next in {secs/60:.0f}m"
                            else:
                                eta = "active"
                        except Exception:
                            eta = "running"
                        task_lines.append(f"✅ **{display}** — {eta}")
                    else:
                        task_lines.append(f"❌ **{display}** — stopped")
                else:
                    task_lines.append(f"⚠️ **{display}** — not found")

            embed.add_field(
                name="⏰ Scheduled Tasks",
                value="\n".join(task_lines) if task_lines else "None found",
                inline=False
            )

            # ── ACTIVE USER TASKS ─────────────────────────────────────────
            try:
                tracker = getattr(self.bot, 'active_tasks', None)
                if tracker:
                    running = await tracker.get_active_tasks()
                    if running:
                        active_val = "\n".join(f"🔹 **{t['description']}** — {t['elapsed']:.0f}s" for t in running)
                    else:
                        active_val = "✅ No commands currently running"
                else:
                    active_val = "⚠️ Task tracker not attached to bot"
            except Exception as e:
                active_val = f"❌ Error: {e}"

            embed.add_field(name="🔄 Active Tasks", value=active_val, inline=False)

            embed.set_footer(text=f"Requested by {ctx.author} • Use >poolstats / >cachestats for detailed views")
            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"❌ Error in bothealth: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await ctx.send(embed=discord.Embed(
                title="❌ Health Dashboard Error",
                description=f"```{type(e).__name__}: {e}```",
                color=discord.Color.red()
            ))


async def setup(bot):
    await bot.add_cog(MaintenanceCommands(bot))
    logger.info("✅ MaintenanceCommands cog loaded")