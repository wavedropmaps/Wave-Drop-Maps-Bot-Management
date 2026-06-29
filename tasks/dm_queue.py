"""
Centralized Database-Driven DM Queue with Round-Robin Load Balancing
====================================================================
Single source of truth: shared SQLite database (dm_queue table).
Bots INSERT jobs. Database/Coordinator assigns to ONE bot. Worker sends.
No duplicates. Perfect round-robin when both bots have capacity.
"""

import asyncio
import aiosqlite
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import discord
from discord.ext import commands

logger = logging.getLogger('discord')

# ── Configuration constants ────────────────────────────────────────────────────
SHARED_DB = "C:/Users/kiere/Desktop/dm_shared_queue.db"
COORDINATOR_INTERVAL = 1.0
WORKER_INTERVAL = 1.0
HEARTBEAT_INTERVAL = 5.0
DM_PER_SECOND_GAP = 1.0
DM_WINDOW_LIMIT = 5
DM_WINDOW_SECONDS = 300.0
BOT_OFFLINE_THRESHOLD = 30.0
LOG_CHANNEL_ID = 1503714231566991441  # Queue manager dashboard
DM_SEND_LOG_CHANNEL = 1411032010494967838  # Individual DMs sent
DM_RECEIVE_LOG_CHANNEL = 1411027953046781982  # Individual DMs received

_dm_queue_instance: Optional["DMQueueCog"] = None


def _serialize_kwargs(content: Optional[str], kwargs: dict) -> str:
    """Convert discord objects to JSON for shared DB storage."""
    safe = {}
    if content is not None:
        safe['content'] = content
    for k, v in kwargs.items():
        if k == 'embed' and isinstance(v, discord.Embed):
            safe['embed'] = v.to_dict()
        elif k == 'embeds' and isinstance(v, list):
            safe['embeds'] = [e.to_dict() for e in v if isinstance(e, discord.Embed)]
        elif k == 'content' and v is not None:
            safe['content'] = v
    return json.dumps(safe)


def _deserialize_kwargs(kwargs_json: str) -> Tuple[Optional[str], dict]:
    """Returns (content, kwargs) reconstructed from shared DB JSON."""
    raw = json.loads(kwargs_json or '{}')
    content = raw.pop('content', None)
    result = {}
    if 'embed' in raw:
        result['embed'] = discord.Embed.from_dict(raw['embed'])
    if 'embeds' in raw:
        result['embeds'] = [discord.Embed.from_dict(d) for d in raw['embeds']]
    return content, result


class DMQueueCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._bot_id = None
        self._log_channel = None
        self._coordinator_task = None
        self._worker_task = None
        self._heartbeat_task = None
        self._recovery_task = None
        self._archive_cleanup_task = None
        self._dashboard_task = None
        self._note_cleanup_task = None

    async def cog_load(self):
        """Initialize database tables on load."""
        await self._init_db()
        logger.info("[DMQueue] DB ready")

    @commands.Cog.listener()
    async def on_ready(self):
        """Resolve log channel and start background tasks when bot is ready."""
        if self._bot_id:
            return  # Already started

        self._bot_id = self.bot.user.id
        logger.info(f"[DMQueue] Bot ID: {self._bot_id}")

        # Resolve log channel
        self._log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if self._log_channel:
            logger.info(f"[DMQueue] PRIMARY log channel resolved: {LOG_CHANNEL_ID}")
        else:
            logger.warning(f"[DMQueue] Log channel {LOG_CHANNEL_ID} not found")

        # Upsert bot into registry
        async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=30000")
            await db.execute("""
                INSERT INTO dm_bot_registry (bot_id, last_seen, last_send, sends_window)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(bot_id) DO UPDATE SET last_seen=excluded.last_seen
            """, (self._bot_id, time.time(), 0.0, json.dumps([])))
            await db.commit()

        # Register persistent views so buttons work after restarts
        self.bot.add_view(DashboardView(self))
        self.bot.add_view(LogMenuView(self))

        # Start background tasks
        self._coordinator_task = asyncio.create_task(self._coordinator_loop())
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._recovery_task = asyncio.create_task(self._recovery_loop())
        self._archive_cleanup_task = asyncio.create_task(self._archive_cleanup_loop())
        self._dashboard_task = asyncio.create_task(self._dashboard_loop())
        self._note_cleanup_task = asyncio.create_task(self._note_cleanup_loop())
        logger.info("[DMQueue] Cog loaded and started with dashboard")

    def cog_unload(self):
        """Cancel all background tasks on unload."""
        for task in [self._coordinator_task, self._worker_task, self._heartbeat_task, self._recovery_task, self._archive_cleanup_task, self._dashboard_task, self._note_cleanup_task]:
            if task and not task.done():
                task.cancel()
        logger.info("[DMQueue] Cog unloaded")

    def enqueue(self, user, content=None, **kwargs):
        """Called synchronously by main.py monkey-patch. Returns immediately.

        Pops the `_source` kwarg (used by reply_dm_duty and auto_reply to tag
        DMs so the post-send hook can decide whether to wipe the sticky note).
        """
        source = kwargs.pop('_source', None)
        asyncio.create_task(self._insert_job(user, content, kwargs, source))

    async def _insert_job(self, user, content, kwargs, source=None):
        """Insert DM job into shared database."""
        from tasks.reply_dm_state import wipe_note

        try:
            now = time.time()
            kwargs_json = _serialize_kwargs(content, kwargs)
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                await db.execute("""
                    INSERT INTO dm_queue
                    (source_bot_id, user_id, content, kwargs_json, status, created_at, source)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """, (self._bot_id, user.id, content, kwargs_json, now, source))
                await db.commit()

            # Eagerly wipe sticky note at ENQUEUE time, not just at delivery
            # time. Without this, there's a 1-11s gap between enqueue and
            # delivery where the note stays armed. If the user DMs the bot
            # during that window (e.g. replying to a previous weekly-check
            # DM), the auto-reply fires with the proof channel message even
            # though the new DM is about something completely unrelated.
            # reply_dm_duty DMs preserve the note (that send IS the arming).
            if source != 'reply_dm_duty':
                await wipe_note(user.id)

            logger.info(f"[DMQueue] ENQUEUED: user_id={user.id} source_bot={self._bot_id} source={source}")
        except Exception as e:
            logger.error(f"[DMQueue] Error inserting job: {e}", exc_info=True)

    # ── Background tasks ───────────────────────────────────────────────────────

    async def _coordinator_loop(self):
        """Assign pending DMs to capable bots (round-robin by last_send)."""
        while True:
            try:
                await asyncio.sleep(COORDINATOR_INTERVAL)
                now = time.time()

                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    db.row_factory = aiosqlite.Row

                    # Load online bots and their capacity
                    async with db.execute("""
                        SELECT bot_id, last_send, sends_window
                        FROM dm_bot_registry
                        WHERE last_seen > ?
                        ORDER BY last_send ASC
                    """, (now - BOT_OFFLINE_THRESHOLD,)) as cursor:
                        bots = await cursor.fetchall()

                    logger.debug(f"[DMQueue:COORD] Found {len(bots)} online bot(s)")

                    capable_bots = []
                    for bot_row in bots:
                        bot_id = bot_row['bot_id']
                        last_send = float(bot_row['last_send']) if bot_row['last_send'] is not None else 0.0
                        sends_window = json.loads(bot_row['sends_window'])

                        # Evict old timestamps
                        sends_window = [t for t in sends_window if t > now - DM_WINDOW_SECONDS]

                        # Check capacity
                        gap_ok = (now - last_send) >= DM_PER_SECOND_GAP
                        window_ok = len(sends_window) < DM_WINDOW_LIMIT

                        logger.debug(f"[DMQueue:COORD] Bot {bot_id}: gap_ok={gap_ok} window_ok={window_ok} sends_in_window={len(sends_window)}")

                        if gap_ok and window_ok:
                            capable_bots.append(bot_id)

                    logger.debug(f"[DMQueue:COORD] Capable bots: {capable_bots}")

                    if not capable_bots:
                        logger.debug(f"[DMQueue:COORD] No capable bots, skipping assignment")
                        continue

                    # Load pending DMs
                    async with db.execute("""
                        SELECT id, user_id, source_bot_id, source FROM dm_queue
                        WHERE status='pending'
                        ORDER BY created_at ASC
                        LIMIT 10
                    """) as cursor:
                        pending = await cursor.fetchall()

                    logger.debug(f"[DMQueue:COORD] Found {len(pending)} pending job(s)")

                    # Assign round-robin via CAS UPDATE
                    assigned_count = 0
                    for i, row in enumerate(pending):
                        # Capture all columns up-front — row_factory state can drift
                        # after a write happens on the same connection mid-loop.
                        job_id = row['id']
                        user_id = row['user_id']
                        source_bot_id = row['source_bot_id']
                        source = row['source']

                        # Auto-reply DMs must stay with the source bot that armed the sticky note
                        # Otherwise the wrong bot sends the auto-reply (consistency issue)
                        if source == 'auto_reply':
                            # Prefer source bot for sticky-note consistency
                            if source_bot_id in capable_bots:
                                bot_id = source_bot_id
                                logger.debug(f"[DMQueue:COORD] Auto-reply: forcing bot {bot_id} (source bot)")
                            elif (now - row['created_at']) > 300:
                                # Source bot offline >5min — fall back to any capable bot to prevent permanent loss
                                bot_id = capable_bots[i % len(capable_bots)]
                                logger.warning(f"[DMQueue:COORD] Auto-reply job {job_id}: source bot {source_bot_id} "
                                               f"offline >5m, falling back to bot {bot_id}")
                            else:
                                logger.debug(f"[DMQueue:COORD] Auto-reply job {job_id}: source bot {source_bot_id} not capable, deferring")
                                continue  # Still within grace period (source bot might come back)
                        else:
                            # Standard round-robin for other DM types
                            bot_id = capable_bots[i % len(capable_bots)]

                        result = await db.execute("""
                            UPDATE dm_queue
                            SET status='assigned', assigned_bot_id=?, assigned_at=?
                            WHERE id=? AND status='pending'
                        """, (bot_id, now, job_id))

                        if result.rowcount > 0:
                            logger.info(f"[DMQueue:COORD] ASSIGNED: job_id={job_id} -> bot_id={bot_id}")
                            assigned_count += 1
                            asyncio.create_task(self._log_event_assigned(job_id, user_id, bot_id))

                    if assigned_count > 0:
                        await db.commit()
                        logger.info(f"[DMQueue:COORD] Assigned {assigned_count} job(s) this cycle")

            except asyncio.CancelledError:
                logger.info("[DMQueue] Coordinator loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:COORD] ERROR: {e}", exc_info=True)

    async def _recovery_loop(self):
        """Recover stuck 'sending' jobs if assigned bot goes offline."""
        MAX_RETRIES = 3
        SENDING_TIMEOUT = 60.0  # Seconds

        while True:
            try:
                await asyncio.sleep(10.0)  # Check every 10 seconds
                now = time.time()

                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    db.row_factory = aiosqlite.Row

                    # Find stuck 'sending' OR long-stuck 'assigned' jobs
                    async with db.execute("""
                        SELECT id, assigned_bot_id, assigned_at, attempt_count, status
                        FROM dm_queue
                        WHERE status='sending'
                           OR (status='assigned' AND assigned_at < ?)
                    """, (now - SENDING_TIMEOUT,)) as cursor:
                        stuck_jobs = await cursor.fetchall()

                    for job in stuck_jobs:
                        job_id = job['id']
                        assigned_at = float(job['assigned_at']) if job['assigned_at'] else now
                        attempt_count = job['attempt_count']
                        sending_duration = now - assigned_at

                        # Recover regardless of whether bot is online — a hung send won't go offline
                        if sending_duration > SENDING_TIMEOUT:
                            if attempt_count < MAX_RETRIES:
                                await db.execute("""
                                    UPDATE dm_queue
                                    SET status='pending', attempt_count=attempt_count+1,
                                        assigned_bot_id=NULL, error_msg=NULL
                                    WHERE id=?
                                """, (job_id,))
                                logger.warning(f"[DMQueue:RECOVERY] RECOVERED: job_id={job_id} "
                                             f"(stuck >{SENDING_TIMEOUT}s, retry {attempt_count + 1}/{MAX_RETRIES})")
                            else:
                                logger.error(f"[DMQueue:RECOVERY] ARCHIVING: job_id={job_id} (max retries exceeded)")
                                async with db.execute("SELECT * FROM dm_queue WHERE id=?", (job_id,)) as cursor:
                                    row = await cursor.fetchone()
                                    if row:
                                        now_arch = time.time()
                                        await db.execute("""
                                            INSERT INTO dm_failed_archive
                                            (original_id, user_id, source_bot_id, assigned_bot_id, content, fail_reason,
                                             error_msg, attempt_count, created_at, failed_at, archived_at)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        """, (
                                            job_id, row['user_id'], row['source_bot_id'], row['assigned_bot_id'],
                                            row['content'], "Max retries", f"Max retries ({MAX_RETRIES}) exceeded",
                                            attempt_count, row['created_at'], now_arch, now_arch
                                        ))
                                        await db.execute("DELETE FROM dm_queue WHERE id=?", (job_id,))

                    if stuck_jobs:
                        await db.commit()

                    # Retry transient 'failed' jobs — but NEVER retry permanent user-side failures
                    async with db.execute("""
                        SELECT id, attempt_count FROM dm_queue
                        WHERE status='failed'
                          AND (failed_at IS NULL OR failed_at < ?)
                          AND error_category IS NOT 'user_error'
                          AND (error_msg IS NULL
                               OR (error_msg NOT LIKE '%Forbidden%'
                                   AND error_msg NOT LIKE '%NotFound%'))
                    """, (now - 30.0,)) as cursor:
                        failed_jobs = await cursor.fetchall()

                    for job in failed_jobs:
                        job_id = job['id']
                        attempt_count = job['attempt_count']
                        if attempt_count < MAX_RETRIES:
                            await db.execute("""
                                UPDATE dm_queue
                                SET status='pending', assigned_bot_id=NULL, error_msg=NULL
                                WHERE id=? AND status='failed'
                            """, (job_id,))
                            logger.warning(f"[DMQueue:RECOVERY] RETRYING failed job_id={job_id} "
                                           f"(attempt {attempt_count + 1}/{MAX_RETRIES})")
                        else:
                            async with db.execute("SELECT * FROM dm_queue WHERE id=?", (job_id,)) as cursor:
                                row = await cursor.fetchone()
                            if row:
                                now_arch = time.time()
                                await db.execute("""
                                    INSERT INTO dm_failed_archive
                                    (original_id, user_id, source_bot_id, assigned_bot_id, content, fail_reason,
                                     error_msg, attempt_count, created_at, failed_at, archived_at)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    job_id, row['user_id'], row['source_bot_id'], row['assigned_bot_id'],
                                    row['content'], "Max retries (transient)",
                                    row['error_msg'], attempt_count,
                                    row['created_at'], now_arch, now_arch
                                ))
                                await db.execute("DELETE FROM dm_queue WHERE id=?", (job_id,))
                                logger.error(f"[DMQueue:RECOVERY] ARCHIVED failed job_id={job_id} (max retries exceeded)")

                    if failed_jobs:
                        await db.commit()

            except asyncio.CancelledError:
                logger.info("[DMQueue] Recovery loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:RECOVERY] ERROR: {e}", exc_info=True)

    async def _archive_cleanup_loop(self):
        """Move successfully sent DMs older than 24h to archive."""
        ARCHIVE_AFTER_SECONDS = 86400  # 24 hours

        while True:
            try:
                await asyncio.sleep(600.0)  # Check every 10 minutes
                now = time.time()
                cutoff = now - ARCHIVE_AFTER_SECONDS

                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    db.row_factory = aiosqlite.Row

                    # Find all sent DMs older than 24h
                    async with db.execute("""
                        SELECT id, user_id, source_bot_id, assigned_bot_id, content, kwargs_json,
                               attempt_count, created_at, sent_at, batch_id, source
                        FROM dm_queue
                        WHERE status='sent' AND sent_at < ?
                    """, (cutoff,)) as cursor:
                        old_sent = await cursor.fetchall()

                    # Move to archive (include kwargs_json + source for log viewer replay)
                    for row in old_sent:
                        await db.execute("""
                            INSERT INTO dm_sent_archive
                            (original_id, user_id, source_bot_id, assigned_bot_id, content, kwargs_json,
                             attempt_count, created_at, sent_at, archived_at, batch_id, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            row['id'], row['user_id'], row['source_bot_id'], row['assigned_bot_id'],
                            row['content'], row['kwargs_json'] if 'kwargs_json' in row.keys() else '{}',
                            row['attempt_count'], row['created_at'], row['sent_at'], now,
                            row['batch_id'] if 'batch_id' in row.keys() else None,
                            row['source'] if 'source' in row.keys() else None,
                        ))
                        await db.execute("DELETE FROM dm_queue WHERE id=?", (row['id'],))

                    if old_sent:
                        await db.commit()
                        logger.info(f"[DMQueue:ARCHIVE] Archived {len(old_sent)} sent DMs to dm_sent_archive")

                    # Prune archive entries older than 30 days to prevent unbounded growth
                    archive_cutoff = now - (30 * 86400)
                    async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db2:
                        await db2.execute("PRAGMA journal_mode=WAL")
                        await db2.execute("PRAGMA busy_timeout=30000")
                        result_sent = await db2.execute(
                            "DELETE FROM dm_sent_archive WHERE archived_at < ?", (archive_cutoff,)
                        )
                        result_fail = await db2.execute(
                            "DELETE FROM dm_failed_archive WHERE archived_at < ?", (archive_cutoff,)
                        )
                        await db2.commit()
                        pruned = (result_sent.rowcount or 0) + (result_fail.rowcount or 0)
                        if pruned:
                            logger.info(f"[DMQueue:ARCHIVE] Pruned {pruned} archive entries older than 30 days")

            except asyncio.CancelledError:
                logger.info("[DMQueue] Archive cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:ARCHIVE] ERROR: {e}", exc_info=True)

    async def _note_cleanup_loop(self):
        """Delete reply_dm_note rows that are well past the 48h expiry.

        Notes are already ignored by get_active_note() once armed_at < now-48h,
        so this is purely housekeeping to keep the table small. Runs every 6h
        and deletes anything older than 4 days (2x the expiry, for margin).
        """
        CLEANUP_INTERVAL = 6 * 3600   # 6 hours
        CLEANUP_AGE = 4 * 24 * 3600   # 4 days

        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                cutoff = time.time() - CLEANUP_AGE

                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    cursor = await db.execute(
                        "DELETE FROM reply_dm_note WHERE armed_at < ?",
                        (cutoff,)
                    )
                    await db.commit()
                    if cursor.rowcount:
                        logger.info(f"[DMQueue:NOTE_CLEANUP] Deleted {cursor.rowcount} expired note(s)")

            except asyncio.CancelledError:
                logger.info("[DMQueue] Note cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:NOTE_CLEANUP] ERROR: {e}", exc_info=True)

    async def _worker_loop(self):
        """Claim assigned DMs and send them."""
        while True:
            try:
                await asyncio.sleep(WORKER_INTERVAL)

                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    db.row_factory = aiosqlite.Row

                    # Claim one assigned job
                    async with db.execute("""
                        SELECT id, user_id, content, kwargs_json, source
                        FROM dm_queue
                        WHERE assigned_bot_id=? AND status='assigned'
                        LIMIT 1
                    """, (self._bot_id,)) as cursor:
                        row = await cursor.fetchone()

                    if not row:
                        logger.debug(f"[DMQueue:WORKER] No assigned jobs for bot {self._bot_id}")
                        continue

                    job_id = row['id']
                    user_id = row['user_id']
                    logger.debug(f"[DMQueue:WORKER] Found assigned job: id={job_id} user={user_id}")

                    # Claim it
                    result = await db.execute("""
                        UPDATE dm_queue
                        SET status='sending'
                        WHERE id=? AND status='assigned'
                    """, (job_id,))

                    if result.rowcount == 0:
                        logger.warning(f"[DMQueue:WORKER] Failed to claim job {job_id} (race condition)")
                        continue  # Another bot claimed it

                    await db.commit()
                    logger.info(f"[DMQueue:WORKER] CLAIMED: job_id={job_id} user_id={user_id}")

                    # Send the DM
                    await self._send_job(row)

            except asyncio.CancelledError:
                logger.info("[DMQueue] Worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:WORKER] ERROR: {e}", exc_info=True)

    async def _send_job(self, row):
        """Send a single DM job."""
        import main as _main
        from tasks.reply_dm_state import wipe_note

        job_id = row['id']
        user_id = row['user_id']
        content = row['content']
        kwargs_json = row['kwargs_json']
        source = row['source'] if 'source' in row.keys() else None

        logger.debug(f"[DMQueue:SEND] Starting send for job_id={job_id} user_id={user_id} source={source}")

        try:
            user = await self.bot.fetch_user(user_id)
            content, kwargs = _deserialize_kwargs(kwargs_json)
            logger.debug(f"[DMQueue:SEND] Fetched user {user_id}: {user}")

            original_send = (
                _main._original_member_send
                if isinstance(user, discord.Member)
                else _main._original_user_send
            )

            msg = await original_send(user, content, **kwargs)
            logger.debug(f"[DMQueue:SEND] Message sent to {user_id}, msg={msg}")

            # Sticky-note wipe: only reply_dm_duty's DMs preserve the note
            # (that send IS the arming). Everything else — random welcome DMs,
            # queue-complete DMs, AND successful auto-reply sends — wipes it.
            # Wiping after auto_reply success is correct: the reply has been
            # delivered, so the note's job is done. Failed sends (Forbidden,
            # etc.) raise above and never reach this line, keeping the note
            # armed for a future retry.
            if source != 'reply_dm_duty':
                await wipe_note(user_id)

            # Update registry
            now = time.time()
            await self._update_registry_sent(now)
            logger.debug(f"[DMQueue:SEND] Updated registry with send time")

            # Mark as sent
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                await db.execute("""
                    UPDATE dm_queue
                    SET status='sent', sent_at=?
                    WHERE id=?
                """, (now, job_id))
                await db.commit()

            logger.info(f"[DMQueue:SEND] SUCCESS: job_id={job_id} user_id={user_id}")

            # Log events
            asyncio.create_task(self._log_event_sent(job_id, user_id))
            await self._log_sent(user, content, kwargs)

        except discord.Forbidden:
            logger.warning(f"[DMQueue:SEND] FORBIDDEN: job_id={job_id} user_id={user_id} (DMs disabled)")
            await self._mark_failed(job_id, "Forbidden: DMs disabled or blocked by user", permanent=True, error_category='user_error')
            asyncio.create_task(self._log_event_failed(job_id, user_id, "DMs disabled"))
        except discord.NotFound:
            logger.error(f"[DMQueue:SEND] NOT_FOUND: job_id={job_id} user_id={user_id} (user deleted or doesn't exist)")
            await self._mark_failed(job_id, "NotFound: User doesn't exist or was deleted", permanent=True, error_category='user_error')
            asyncio.create_task(self._log_event_failed(job_id, user_id, "User not found"))
        except discord.InvalidArgument as e:
            logger.error(f"[DMQueue:SEND] INVALID: job_id={job_id} user_id={user_id} (bad argument)")
            await self._mark_failed(job_id, f"InvalidArgument: {str(e)}", permanent=True, error_category='bot_error')
            asyncio.create_task(self._log_event_failed(job_id, user_id, "Invalid argument"))
        except Exception as e:
            err_str = str(e)
            if '429' in err_str or 'rate' in err_str.lower():
                error_category = 'bot_error'
            elif 'timeout' in err_str.lower() or 'connection' in err_str.lower():
                error_category = 'network_error'
            else:
                error_category = 'other'
            logger.error(f"[DMQueue:SEND] FAILED: job_id={job_id} user_id={user_id} error={e}", exc_info=True)
            await self._mark_failed(job_id, err_str, permanent=False, error_category=error_category)
            asyncio.create_task(self._log_event_failed(job_id, user_id, err_str))

    async def _update_registry_sent(self, send_time: float):
        """Update last_send and sends_window in registry."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row

                # Fetch current window
                async with db.execute("""
                    SELECT sends_window FROM dm_bot_registry
                    WHERE bot_id=?
                """, (self._bot_id,)) as cursor:
                    row = await cursor.fetchone()

                if row:
                    sends_window = json.loads(row['sends_window'])
                else:
                    sends_window = []

                # Evict old timestamps
                sends_window = [t for t in sends_window if t > send_time - DM_WINDOW_SECONDS]
                sends_window.append(send_time)

                await db.execute("""
                    INSERT INTO dm_bot_registry (bot_id, last_send, sends_window)
                    VALUES (?, ?, ?)
                    ON CONFLICT(bot_id) DO UPDATE SET
                        last_send=excluded.last_send,
                        sends_window=excluded.sends_window
                """, (self._bot_id, send_time, json.dumps(sends_window)))

                await db.commit()
        except Exception as e:
            logger.error(f"[DMQueue] Error updating registry: {e}", exc_info=True)

    async def _heartbeat_loop(self):
        """Update last_seen every 5 seconds to indicate bot is alive."""
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                now = time.time()

                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    await db.execute("""
                        INSERT INTO dm_bot_registry (bot_id, last_seen)
                        VALUES (?, ?)
                        ON CONFLICT(bot_id) DO UPDATE SET last_seen=excluded.last_seen
                    """, (self._bot_id, now))
                    await db.commit()

                logger.debug(f"[DMQueue:HB] Heartbeat sent for bot {self._bot_id}")

            except asyncio.CancelledError:
                logger.info("[DMQueue] Heartbeat loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:HB] ERROR: {e}", exc_info=True)

    # ── Database initialization ────────────────────────────────────────────────

    async def _init_db(self):
        """Create tables if they don't exist."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS dm_queue (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_bot_id   INTEGER NOT NULL,
                        user_id         INTEGER NOT NULL,
                        content         TEXT,
                        kwargs_json     TEXT DEFAULT '{}',
                        status          TEXT DEFAULT 'pending',
                        assigned_bot_id INTEGER,
                        attempt_count   INTEGER DEFAULT 0,
                        created_at      REAL NOT NULL,
                        assigned_at     REAL,
                        sent_at         REAL,
                        error_msg       TEXT
                    )
                """)

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dm_queue_status
                    ON dm_queue(status)
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS dm_bot_registry (
                        bot_id       INTEGER PRIMARY KEY,
                        last_seen    REAL DEFAULT 0,
                        last_send    REAL DEFAULT 0,
                        sends_window TEXT DEFAULT '[]'
                    )
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS dm_dashboard_config (
                        key   TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS dm_sent_archive (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_id     INTEGER NOT NULL,
                        user_id         INTEGER NOT NULL,
                        source_bot_id   INTEGER,
                        assigned_bot_id INTEGER,
                        content         TEXT,
                        attempt_count   INTEGER DEFAULT 0,
                        created_at      REAL,
                        sent_at         REAL,
                        archived_at     REAL NOT NULL
                    )
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS dm_failed_archive (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        original_id     INTEGER NOT NULL,
                        user_id         INTEGER NOT NULL,
                        source_bot_id   INTEGER,
                        assigned_bot_id INTEGER,
                        content         TEXT,
                        fail_reason     TEXT NOT NULL,
                        error_msg       TEXT,
                        attempt_count   INTEGER DEFAULT 0,
                        created_at      REAL,
                        failed_at       REAL,
                        archived_at     REAL NOT NULL
                    )
                """)

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dm_failed_archive_reason
                    ON dm_failed_archive(fail_reason)
                """)

                # ── Reply-DM Sticky Note ──────────────────────────────────
                # Armed by reply_dm_duty after each staff-reply forward DM.
                # Wiped by any other outbound bot DM or by the auto-reply firing.
                # One row per user (overwritten on re-arm). Notes expire after
                # 48h via the cutoff in get_active_note() and the cleanup loop.
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS reply_dm_note (
                        user_id        INTEGER PRIMARY KEY,
                        guild_id       INTEGER NOT NULL,
                        source_bot_id  INTEGER,
                        armed_at       REAL NOT NULL
                    )
                """)

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_reply_dm_note_armed_at
                    ON reply_dm_note(armed_at)
                """)

                # Drop the legacy auto_reply_queue table. Its UNIQUE(user_id)
                # constraint enforced "one auto-reply per user forever" which
                # is incompatible with the new note-based, re-armable system.
                await db.execute("DROP TABLE IF EXISTS auto_reply_queue")

                # Migration: add failed_at to dm_queue if not exists
                try:
                    await db.execute("ALTER TABLE dm_queue ADD COLUMN failed_at REAL")
                except Exception:
                    pass  # Column already exists

                # Migration: add source column to dm_queue (carries _source flag
                # from reply_dm_duty / auto_reply so the send hook knows whether
                # to wipe the sticky note after sending).
                try:
                    await db.execute("ALTER TABLE dm_queue ADD COLUMN source TEXT")
                except Exception:
                    pass  # Column already exists

                # Migration: add error_category for better failure classification
                for tbl in ("dm_queue", "dm_failed_archive"):
                    try:
                        await db.execute(f"ALTER TABLE {tbl} ADD COLUMN error_category TEXT")
                    except Exception:
                        pass

                # Migration: add kwargs_json + source to archive tables for log viewer
                for tbl in ("dm_sent_archive", "dm_failed_archive"):
                    try:
                        await db.execute(f"ALTER TABLE {tbl} ADD COLUMN kwargs_json TEXT DEFAULT '{{}}'")
                    except Exception:
                        pass
                    try:
                        await db.execute(f"ALTER TABLE {tbl} ADD COLUMN source TEXT")
                    except Exception:
                        pass

                # Migration: composite status+created_at index for faster coordinator queries
                try:
                    await db.execute("""
                        CREATE INDEX IF NOT EXISTS idx_dm_queue_status_created
                        ON dm_queue(status, created_at)
                    """)
                except Exception:
                    pass

                await db.commit()
            logger.info("[DMQueue] Database initialized")
        except Exception as e:
            logger.error(f"[DMQueue] DB init error: {e}", exc_info=True)

    # ── Persistent button interaction handler ─────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Handle persistent jobact:* button clicks from JobEventView.

        custom_id format: jobact:{action}:{job_id}  (action: view, retry, force)
        Works forever — no timeout, survives restarts.
        """
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get('custom_id', '')
        if not custom_id.startswith('jobact:'):
            return

        parts = custom_id.split(':')
        if len(parts) != 3:
            return
        action, job_id_str = parts[1], parts[2]
        try:
            job_id = int(job_id_str)
        except ValueError:
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        job, location = await self._jobact_fetch(job_id)

        if action == 'view':
            if not job:
                await interaction.followup.send(
                    f"⚠️ Job `#{job_id}` not found — archived or deleted.", ephemeral=True
                )
                return
            embed = _build_job_embed(job, location or 'active')
            view = JobDetailView(self, job, location or 'active')
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        elif action in ('retry', 'force'):
            if not job:
                await interaction.followup.send(f"⚠️ Job `#{job_id}` not found.", ephemeral=True)
                return
            try:
                src_bot = (job.get('source_bot_id') or self._bot_id) if action == 'force' else self._bot_id
                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    await db.execute("""
                        INSERT INTO dm_queue
                        (source_bot_id, user_id, content, kwargs_json, status, created_at, batch_id, source)
                        VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                    """, (
                        src_bot, job['user_id'], job.get('content'),
                        job.get('kwargs_json') or '{}', time.time(),
                        job.get('batch_id'), job.get('source'),
                    ))
                    await db.commit()
                verb = "Force-retried" if action == 'force' else "Re-queued"
                await interaction.followup.send(
                    f"✅ {verb} job `#{job_id}` for delivery.", ephemeral=True
                )
                logger.info(f"[DMQueue:JobAct] {action} job_id={job_id}")
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    async def _jobact_fetch(self, job_id: int) -> tuple:
        """Fetch a job from any table. Returns (job_dict, location)."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row
                for sql, location in [
                    ("SELECT * FROM dm_queue WHERE id=?", 'active'),
                    ("SELECT original_id as id, * FROM dm_sent_archive WHERE original_id=?", 'sent'),
                    ("SELECT original_id as id, * FROM dm_failed_archive WHERE original_id=?", 'failed'),
                ]:
                    async with db.execute(sql, (job_id,)) as c:
                        row = await c.fetchone()
                    if row:
                        return dict(row), location
        except Exception as e:
            logger.error(f"[DMQueue:JobAct] DB error fetching job {job_id}: {e}")
        return None, None

    # ── Log Viewer query helpers ───────────────────────────────────────────────

    async def _log_viewer_get_active(self, limit: int = 100) -> list:
        """Return active (pending/assigned/sending/failed) jobs as list of dicts."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT id, user_id, status, content, kwargs_json, created_at,
                           assigned_at, assigned_bot_id, attempt_count, error_msg,
                           error_category, batch_id, source
                    FROM dm_queue
                    WHERE status IN ('pending', 'assigned', 'sending', 'failed')
                    ORDER BY created_at ASC
                    LIMIT ?
                """, (limit,)) as cursor:
                    return [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"[DMQueue:LOG_VIEWER] Error fetching active: {e}", exc_info=True)
            return []

    async def _log_viewer_get_sent(self, limit: int = 100, hours: int = 24) -> list:
        """Return sent DMs from archive (last N hours) as list of dicts."""
        try:
            cutoff = time.time() - (hours * 3600)
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT original_id as id, user_id, source_bot_id, assigned_bot_id,
                           content, kwargs_json, attempt_count, created_at, sent_at,
                           archived_at, batch_id, source
                    FROM dm_sent_archive
                    WHERE archived_at > ?
                    ORDER BY archived_at DESC
                    LIMIT ?
                """, (cutoff, limit)) as cursor:
                    return [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"[DMQueue:LOG_VIEWER] Error fetching sent: {e}", exc_info=True)
            return []

    async def _log_viewer_get_failed(self, limit: int = 100) -> list:
        """Return failed DMs from archive as list of dicts."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT original_id as id, user_id, source_bot_id, assigned_bot_id,
                           content, kwargs_json, fail_reason, error_msg, error_category,
                           attempt_count, created_at, failed_at, archived_at, batch_id, source
                    FROM dm_failed_archive
                    ORDER BY failed_at DESC
                    LIMIT ?
                """, (limit,)) as cursor:
                    return [dict(r) for r in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"[DMQueue:LOG_VIEWER] Error fetching failed: {e}", exc_info=True)
            return []

    async def _mark_failed(self, job_id: int, error_msg: str, permanent: bool = False, error_category: str = 'other'):
        """Mark a job as failed. If permanent, move to archive and remove from queue."""
        try:
            now = time.time()
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row

                if permanent:
                    # Fetch full row first
                    async with db.execute("SELECT * FROM dm_queue WHERE id=?", (job_id,)) as cursor:
                        row = await cursor.fetchone()

                    if row:
                        # Derive fail_reason from error_msg
                        fail_reason = "Unknown"
                        if "Forbidden" in error_msg:
                            fail_reason = "DMs disabled"
                        elif "NotFound" in error_msg:
                            fail_reason = "User not found"
                        elif "InvalidArgument" in error_msg:
                            fail_reason = "Invalid"
                        elif "Max retries" in error_msg:
                            fail_reason = "Max retries"

                        # Insert into archive (with kwargs_json + source + error_category for log viewer)
                        await db.execute("""
                            INSERT INTO dm_failed_archive
                            (original_id, user_id, source_bot_id, assigned_bot_id, content, kwargs_json,
                             fail_reason, error_msg, error_category, attempt_count, created_at,
                             failed_at, archived_at, batch_id, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            job_id, row['user_id'], row['source_bot_id'], row['assigned_bot_id'],
                            row['content'], row['kwargs_json'] if 'kwargs_json' in row.keys() else '{}',
                            fail_reason, error_msg, error_category, row['attempt_count'],
                            row['created_at'], now, now,
                            row['batch_id'] if 'batch_id' in row.keys() else None,
                            row['source'] if 'source' in row.keys() else None,
                        ))

                        # Delete from active queue
                        await db.execute("DELETE FROM dm_queue WHERE id=?", (job_id,))
                        logger.info(f"[DMQueue] ARCHIVED: job_id={job_id} reason={fail_reason}")
                else:
                    # Transient failure: mark failed but keep in queue for retry
                    await db.execute("""
                        UPDATE dm_queue
                        SET status='failed', error_msg=?, error_category=?, failed_at=?
                        WHERE id=?
                    """, (error_msg, error_category, now, job_id))

                await db.commit()
        except Exception as e:
            logger.error(f"[DMQueue] Error marking failed: {e}", exc_info=True)

    async def _log_sent(self, user, content: Optional[str], kwargs: dict):
        """Log sent DM to the DM send log channel (not queue dashboard)."""
        try:
            channel = self.bot.get_channel(DM_SEND_LOG_CHANNEL)
            if not channel:
                logger.debug(f"[DMQueue:SEND] Channel {DM_SEND_LOG_CHANNEL} not cached, fetching...")
                try:
                    channel = await self.bot.fetch_channel(DM_SEND_LOG_CHANNEL)
                    logger.debug(f"[DMQueue:SEND] Successfully fetched channel {DM_SEND_LOG_CHANNEL}")
                except Exception as fetch_err:
                    logger.error(f"[DMQueue:SEND] Failed to fetch DM send log channel {DM_SEND_LOG_CHANNEL}: {fetch_err}")
                    return

            embed = discord.Embed(
                title="📬 DM Sent",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(
                name="To",
                value=f"{user.mention} ({user})\nID: `{user.id}`",
                inline=False
            )

            # Plain text
            if content:
                text = content if len(content) <= 1024 else content[:1021] + "..."
                embed.add_field(name="Content", value=text, inline=False)

            # Single embed
            sent_embed = kwargs.get('embed')
            if sent_embed:
                parts = []
                if sent_embed.title:
                    parts.append(f"**Title:** {sent_embed.title}")
                if sent_embed.description:
                    parts.append(f"**Desc:** {sent_embed.description[:200]}")
                if parts:
                    embed.add_field(name="Embed", value="\n".join(parts), inline=False)

            # Multiple embeds
            for i, e in enumerate(kwargs.get('embeds', []), 1):
                parts = []
                if e.title:
                    parts.append(f"**Title:** {e.title}")
                if e.description:
                    parts.append(f"**Desc:** {e.description[:200]}")
                if parts:
                    embed.add_field(name=f"Embed {i}", value="\n".join(parts), inline=False)

            # Files
            all_files = ([kwargs['file']] if 'file' in kwargs else []) + list(kwargs.get('files', []))
            if all_files:
                file_text = "\n".join(f"📎 {f.filename}" for f in all_files if hasattr(f, 'filename'))
                embed.add_field(name="Files", value=file_text[:1024], inline=False)

            if hasattr(user, 'avatar') and user.avatar:
                embed.set_thumbnail(url=user.avatar.url)

            await channel.send(embed=embed)
            logger.info(f"[DMQueue:SEND] Logged DM to user {user.id} in send log channel {DM_SEND_LOG_CHANNEL}")
        except Exception as e:
            logger.error(f"[DMQueue:SEND] Error logging DM: {e}", exc_info=True)

    async def _dashboard_loop(self):
        """Update full-system dashboard message every 30 seconds."""
        await asyncio.sleep(5)  # Wait for bot to fully initialize
        while True:
            try:
                await asyncio.sleep(30.0)

                if not self._log_channel:
                    continue

                now = time.time()
                cutoff_1h = now - 3600
                cutoff_6h = now - 21600
                cutoff_24h = now - 86400

                # ── Gather all stats in a single connection ──
                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    db.row_factory = aiosqlite.Row

                    # Active queue status counts
                    async with db.execute("SELECT status, COUNT(*) as c FROM dm_queue GROUP BY status") as cur:
                        status_counts = {r['status']: r['c'] for r in await cur.fetchall()}

                    # Bot registry
                    async with db.execute(
                        "SELECT bot_id, last_send, last_seen, sends_window FROM dm_bot_registry ORDER BY bot_id"
                    ) as cur:
                        bot_rows = await cur.fetchall()

                    # Archive totals
                    async with db.execute("SELECT COUNT(*) as c FROM dm_sent_archive") as cur:
                        archive_sent_count = (await cur.fetchone())['c']
                    async with db.execute(
                        "SELECT fail_reason, COUNT(*) as c FROM dm_failed_archive GROUP BY fail_reason"
                    ) as cur:
                        archive_fails = {r['fail_reason']: r['c'] for r in await cur.fetchall()}

                    # Time-windowed sent counts (active + archive)
                    async def _count_sent(cutoff):
                        async with db.execute(
                            "SELECT COUNT(*) as c FROM dm_queue WHERE status='sent' AND sent_at > ?", (cutoff,)
                        ) as cur:
                            a = (await cur.fetchone())['c']
                        async with db.execute(
                            "SELECT COUNT(*) as c FROM dm_sent_archive WHERE sent_at > ?", (cutoff,)
                        ) as cur:
                            b = (await cur.fetchone())['c']
                        return a + b

                    sent_1h = await _count_sent(cutoff_1h)
                    sent_6h = await _count_sent(cutoff_6h)
                    sent_24h = await _count_sent(cutoff_24h)

                    # Per-bot source→assigned pair counts (24h, active + archive)
                    pair_totals = {}
                    for sql in [
                        "SELECT source_bot_id as s, assigned_bot_id as a, COUNT(*) as c FROM dm_queue "
                        "WHERE status='sent' AND sent_at > ? GROUP BY s, a",
                        "SELECT source_bot_id as s, assigned_bot_id as a, COUNT(*) as c FROM dm_sent_archive "
                        "WHERE sent_at > ? GROUP BY s, a",
                    ]:
                        async with db.execute(sql, (cutoff_24h,)) as cur:
                            for r in await cur.fetchall():
                                key = (r['s'], r['a'])
                                pair_totals[key] = pair_totals.get(key, 0) + r['c']

                    # Delivery latency stats (24h)
                    async with db.execute("""
                        SELECT AVG(sent_at - created_at) as avg_lat,
                               MAX(sent_at - created_at) as max_lat,
                               MIN(sent_at - created_at) as min_lat
                        FROM dm_queue WHERE status='sent' AND sent_at > ?
                    """, (cutoff_24h,)) as cur:
                        lat = await cur.fetchone()
                        avg_lat = lat['avg_lat'] or 0
                        max_lat = lat['max_lat'] or 0
                        min_lat = lat['min_lat'] or 0

                    # Oldest pending job age
                    async with db.execute(
                        "SELECT MIN(created_at) as m FROM dm_queue WHERE status='pending'"
                    ) as cur:
                        r = await cur.fetchone()
                        oldest_pending = (now - r['m']) if r and r['m'] else 0

                    # Stuck jobs (assigned/sending > 60s)
                    async with db.execute(
                        "SELECT COUNT(*) as c FROM dm_queue WHERE status='assigned' AND assigned_at < ?",
                        (now - 60,)
                    ) as cur:
                        stuck_assigned = (await cur.fetchone())['c']
                    async with db.execute(
                        "SELECT COUNT(*) as c FROM dm_queue WHERE status='sending' AND assigned_at < ?",
                        (now - 60,)
                    ) as cur:
                        stuck_sending = (await cur.fetchone())['c']

                    # Sticky-note stats (active = armed within last 48h; expired = older rows still in table)
                    note_cutoff = now - (48 * 3600)
                    async with db.execute(
                        "SELECT COUNT(*) as c FROM reply_dm_note WHERE armed_at > ?",
                        (note_cutoff,)
                    ) as cur:
                        notes_active = (await cur.fetchone())['c']
                    async with db.execute(
                        "SELECT COUNT(*) as c FROM reply_dm_note WHERE armed_at <= ?",
                        (note_cutoff,)
                    ) as cur:
                        notes_expired = (await cur.fetchone())['c']

                    # Unique users DM'd in 24h (across active + archive)
                    async with db.execute("""
                        SELECT COUNT(*) as c FROM (
                            SELECT user_id FROM dm_queue WHERE status='sent' AND sent_at > ?
                            UNION
                            SELECT user_id FROM dm_sent_archive WHERE sent_at > ?
                        )
                    """, (cutoff_24h, cutoff_24h)) as cur:
                        unique_users_24h = (await cur.fetchone())['c']

                    # Failed count in 24h
                    async with db.execute(
                        "SELECT COUNT(*) as c FROM dm_failed_archive WHERE archived_at > ?",
                        (cutoff_24h,)
                    ) as cur:
                        failed_24h = (await cur.fetchone())['c']

                    # Recent activity (last 10 active-queue jobs)
                    async with db.execute("""
                        SELECT id, source_bot_id, assigned_bot_id, user_id, status, created_at, sent_at
                        FROM dm_queue ORDER BY created_at DESC LIMIT 10
                    """) as cur:
                        recent_jobs = await cur.fetchall()

                    # Recent permanent failures (last 6h)
                    async with db.execute("""
                        SELECT user_id, fail_reason, archived_at, source_bot_id, assigned_bot_id
                        FROM dm_failed_archive WHERE archived_at > ?
                        ORDER BY archived_at DESC LIMIT 5
                    """, (cutoff_6h,)) as cur:
                        recent_fails = await cur.fetchall()

                # ── Derived stats ──
                pending = status_counts.get('pending', 0)
                assigned = status_counts.get('assigned', 0)
                sending = status_counts.get('sending', 0)
                sent = status_counts.get('sent', 0)
                failed_transient = status_counts.get('failed', 0)
                total_active = pending + assigned + sending + sent + failed_transient

                total_ever_sent = sent + archive_sent_count
                total_failed_ever = sum(archive_fails.values())
                lifetime_success = (total_ever_sent / (total_ever_sent + total_failed_ever) * 100) \
                    if (total_ever_sent + total_failed_ever) > 0 else 100.0
                rate_per_min = sent_1h / 60.0 if sent_1h else 0
                est_clear_s = (pending / max(rate_per_min, 0.5) * 60) if pending > 0 else 0

                # Cross-bot share % (how much load is shared vs same-bot)
                cross_bot_count = sum(c for (s, a), c in pair_totals.items() if s != a and s and a)
                total_routed = sum(pair_totals.values())
                cross_bot_pct = (cross_bot_count / total_routed * 100) if total_routed else 0

                def _fmt_age(s):
                    if s is None: return "—"
                    if s < 60: return f"{s:.0f}s"
                    if s < 3600: return f"{s/60:.0f}m"
                    if s < 86400: return f"{s/3600:.1f}h"
                    return f"{s/86400:.1f}d"

                def _bot_label(bid):
                    if bid is None or bid == 0:
                        return "—"
                    u = self.bot.get_user(int(bid))
                    if u:
                        name = u.name
                        return name[:12] + ('…' if len(name) > 12 else '')
                    return f"Bot{str(bid)[-4:]}"

                # ── System health check ──
                bots_online = sum(
                    1 for row in bot_rows
                    if (now - float(row['last_seen'] or 0)) < BOT_OFFLINE_THRESHOLD
                )
                total_bots = len(bot_rows)
                has_stuck = stuck_assigned > 0 or stuck_sending > 0
                has_backlog = pending > 10

                if bots_online == total_bots and total_bots > 0 and not has_stuck and not has_backlog and lifetime_success >= 98:
                    health_icon = "🟢"
                    health_text = "All Systems Operational"
                    health_color = discord.Color.green()
                elif bots_online == 0:
                    health_icon = "🔴"
                    health_text = "CRITICAL — No bots online, DMs will queue up"
                    health_color = discord.Color.red()
                else:
                    health_icon = "🟡"
                    health_color = discord.Color.orange()
                    issues = []
                    if bots_online < total_bots:
                        issues.append(f"{total_bots - bots_online} bot(s) offline")
                    if has_stuck:
                        issues.append(f"{stuck_assigned + stuck_sending} stuck job(s)")
                    if has_backlog:
                        issues.append(f"{pending} DMs backlogged")
                    if lifetime_success < 98:
                        issues.append(f"success rate {lifetime_success:.1f}%")
                    health_text = "Degraded — " + ", ".join(issues)

                def _bar(pct, length=12):
                    """Visual progress bar for load balancing display."""
                    filled = round(pct / 100 * length)
                    return '█' * filled + '░' * (length - filled)

                # ── Build embed ──
                embed = discord.Embed(
                    title="📊 DM Queue — System Dashboard",
                    description=(
                        f"{health_icon} **{health_text}**\n\n"
                        f"Shared DM queue between both bots. Every outgoing DM from "
                        f"any cog is intercepted and inserted into a shared SQLite "
                        f"database. A coordinator loop assigns each DM to whichever "
                        f"bot has capacity, enabling automatic load balancing. The "
                        f"worker loop on each bot picks up its assigned DMs and "
                        f"delivers them.\n\n"
                        f"📋 `dm_shared_queue.db` • Bots online: **{bots_online}/{total_bots}** • "
                        f"Refreshes every 30s"
                    ),
                    color=health_color,
                    timestamp=datetime.now(timezone.utc)
                )

                # ── Field 1: Active Queue (pipeline stages) ──
                queue_v = (
                    f"🟦 Pending: **{pending}**"
                    + (f" *({_fmt_age(oldest_pending)} oldest)*" if oldest_pending else " *(awaiting assignment)*") + "\n"
                    f"🟨 Assigned: **{assigned}**"
                    + (f" ⚠️ {stuck_assigned} stuck" if stuck_assigned else " *(bot picked up)*") + "\n"
                    f"🟧 Sending: **{sending}**"
                    + (f" ⚠️ {stuck_sending} stuck" if stuck_sending else " *(in transit)*") + "\n"
                    f"✅ Sent: **{sent}** *(awaiting archive)*\n"
                    f"❌ Failed: **{failed_transient}** *(retryable)*\n"
                    f"📦 Total active rows: **{total_active}**"
                )
                embed.add_field(name="📬 Active Queue", value=queue_v, inline=True)

                # ── Field 2: Throughput ──
                tp_v = (
                    f"Last 1h: **{sent_1h}** DMs\n"
                    f"Last 6h: **{sent_6h}** DMs\n"
                    f"Last 24h: **{sent_24h}** DMs\n"
                    f"Unique users (24h): **{unique_users_24h}**\n"
                    f"Lifetime sent: **{total_ever_sent:,}** DMs\n"
                    f"Rate: **{rate_per_min:.1f}**/min"
                    + (f"\nEst. clear: **{_fmt_age(est_clear_s)}**" if pending > 0 else "")
                )
                embed.add_field(name="⚡ Throughput", value=tp_v, inline=True)

                # ── Field 3: Success & Latency ──
                lat_v = (
                    f"**Lifetime success:** {lifetime_success:.2f}%\n"
                    f"✉️ {total_ever_sent:,} sent / 🚫 {total_failed_ever} failed\n"
                    f"❌ Failed (24h): **{failed_24h}**\n"
                    f"\n**Latency** *(enqueue → delivered, 24h)*\n"
                    f"Avg: **{avg_lat:.1f}s** • Min: {min_lat:.1f}s\n"
                    f"Max: {max_lat:.0f}s"
                )
                embed.add_field(name="📈 Reliability", value=lat_v, inline=True)

                # ── Field 4: Cross-Bot Load Sharing (full width) ──
                src_groups = {}
                for (s, a), c in pair_totals.items():
                    if not s: continue
                    src_groups.setdefault(s, {})[a] = c

                if total_routed > 0:
                    # Rating based on closeness to 50% (perfect balance)
                    if cross_bot_pct >= 45:
                        balance_label = "Near-Perfect Balance"
                        balance_emoji = "🎯"
                    elif cross_bot_pct >= 30:
                        balance_label = "Good Balance"
                        balance_emoji = "✅"
                    elif cross_bot_pct >= 15:
                        balance_label = "Moderate"
                        balance_emoji = "📊"
                    else:
                        balance_label = "Low — one bot doing most work"
                        balance_emoji = "⚠️"

                    share_lines = [
                        f"{balance_emoji} **{cross_bot_pct:.0f}%** cross-bot — **{balance_label}**",
                        f"`{_bar(cross_bot_pct, 20)}` {cross_bot_count}/{total_routed} DMs shared",
                        f"",
                        f"*Cross-bot = DMs delivered by the OTHER bot, not the one that*",
                        f"*created them. 50% = perfect 50/50 sharing. 0% = no sharing.*",
                        f"",
                    ]
                    for src_id, asn_dict in sorted(src_groups.items()):
                        total = sum(asn_dict.values())
                        if total == 0: continue
                        self_count = asn_dict.get(src_id, 0)
                        shared_count = total - self_count
                        shared_pct = (shared_count / total * 100) if total else 0
                        share_lines.append(
                            f"**{_bot_label(src_id)}** created **{total}** DMs: "
                            f"🔄 {self_count} self-sent → ↔️ {shared_count} load-shared ({shared_pct:.0f}%)"
                        )
                    load_v = "\n".join(share_lines)[:1024]
                else:
                    load_v = "*No DMs sent in last 24h — both bots are idle*"
                embed.add_field(name="⚖️ Cross-Bot Load Sharing (24h)", value=load_v, inline=False)

                # ── Fields 5+: Per-bot detailed status ──
                for row in bot_rows:
                    bot_id = row['bot_id']
                    last_send = float(row['last_send']) if row['last_send'] else 0.0
                    last_seen = float(row['last_seen']) if row['last_seen'] else 0.0
                    sends_window = json.loads(row['sends_window'])
                    sends_window = [t for t in sends_window if t > now - DM_WINDOW_SECONDS]

                    seen_ago = now - last_seen
                    is_online = seen_ago < BOT_OFFLINE_THRESHOLD
                    send_ago = (now - last_send) if last_send else None

                    sourced_24h = sum(c for (s, a), c in pair_totals.items() if s == bot_id)
                    delivered_24h = sum(c for (s, a), c in pair_totals.items() if a == bot_id)

                    gap_ok = (send_ago is None) or (send_ago >= DM_PER_SECOND_GAP)
                    window_ok = len(sends_window) < DM_WINDOW_LIMIT
                    if gap_ok and window_ok:
                        capacity = "✅ Ready"
                    elif not gap_ok:
                        capacity = f"⏳ Gap cooldown ({DM_PER_SECOND_GAP - send_ago:.1f}s)"
                    else:
                        oldest_window = min(sends_window) if sends_window else now
                        reset_in = (oldest_window + DM_WINDOW_SECONDS) - now
                        capacity = f"⏳ Window full (resets {_fmt_age(reset_in)})"

                    bot_v = (
                        f"{'🟢 Online' if is_online else '🔴 OFFLINE'} ({_fmt_age(seen_ago)} ago)\n"
                        f"**Capacity:** {capacity}\n"
                        f"**Last send:** {_fmt_age(send_ago)}" + (" ago" if send_ago else "") + "\n"
                        f"**Rate window:** {len(sends_window)}/{DM_WINDOW_LIMIT} *({DM_WINDOW_SECONDS/60:.0f}min rolling)*\n"
                        f"**Sourced:** {sourced_24h} *(DMs created by this bot)*\n"
                        f"**Delivered:** {delivered_24h} *(DMs sent out by this bot)*"
                    )
                    embed.add_field(name=f"🤖 {_bot_label(bot_id)}", value=bot_v, inline=True)

                # ── Field: Archive ──
                arc_v = (
                    f"✉️ Sent: **{archive_sent_count:,}**\n"
                    f"🚫 DMs disabled: **{archive_fails.get('DMs disabled', 0)}**\n"
                    f"👻 Not found: **{archive_fails.get('User not found', 0)}**\n"
                    f"♻️ Max retries: **{archive_fails.get('Max retries', 0)}**\n"
                    f"❓ Other: **{archive_fails.get('Unknown', 0)}**\n"
                    f"📁 Total failed: **{total_failed_ever}**"
                )
                embed.add_field(name="🗄️ Archive (lifetime)", value=arc_v, inline=True)

                # ── Field: Reply-DM sticky notes ──
                note_v = (
                    f"🟢 Armed: **{notes_active}** *(active, ≤48h)*\n"
                    f"⌛ Expired: **{notes_expired}** *(pending cleanup)*\n\n"
                    f"*When staff replies via reply\\_dm\\_duty, a sticky note "
                    f"is armed for that user. If the user DMs back within 48h, "
                    f"the auto-reply fires with the proof channel link and the "
                    f"note is wiped. Notes expire after 48h and are cleaned up "
                    f"every 6h.*"
                )
                embed.add_field(name="📝 Sticky Notes", value=note_v, inline=True)

                # ── Field: Stuck jobs (conditional) ──
                if stuck_assigned or stuck_sending:
                    stuck_v = (
                        f"⚠️ **{stuck_assigned}** assigned >60s *(bot claimed but hasn't sent — worker hung?)*\n"
                        f"⚠️ **{stuck_sending}** sending >60s *(Discord API call hanging?)*\n\n"
                        f"*The recovery loop checks every 10s and auto-retries stuck "
                        f"jobs up to 3 times. If the assigned bot goes offline, the "
                        f"job is reset to pending for the other bot to pick up.*"
                    )
                    embed.add_field(name="🚨 Stuck Jobs", value=stuck_v, inline=False)

                # ── Field: Recent Activity (last 10 jobs) ──
                if recent_jobs:
                    status_em = {
                        'pending': '🟦', 'assigned': '🟨', 'sending': '🟧',
                        'sent': '✅', 'failed': '❌'
                    }
                    lines = []
                    for j in recent_jobs:
                        em = status_em.get(j['status'], '•')
                        src = _bot_label(j['source_bot_id'])
                        asn = _bot_label(j['assigned_bot_id']) if j['assigned_bot_id'] else '—'
                        age = _fmt_age(now - j['created_at'])
                        uid_short = str(j['user_id'])[-6:] if j['user_id'] else '——'
                        lines.append(f"{em} `#{j['id']:>4}` {src}→{asn} u:{uid_short} • {age}")
                    embed.add_field(
                        name="🕐 Recent Activity (last 10)",
                        value="\n".join(lines)[:1024],
                        inline=False
                    )

                # ── Field: Recent Failures (conditional) ──
                if recent_fails:
                    fail_lines = []
                    for f in recent_fails:
                        age = _fmt_age(now - f['archived_at'])
                        src = _bot_label(f['source_bot_id']) if f['source_bot_id'] else '—'
                        fail_lines.append(
                            f"❌ `{f['user_id']}` — {f['fail_reason']} — {src} src — {age} ago"
                        )
                    embed.add_field(
                        name="❌ Recent Permanent Failures (last 6h)",
                        value="\n".join(fail_lines)[:1024],
                        inline=False
                    )

                # Footer
                embed.set_footer(
                    text=f"Rendered by {_bot_label(self._bot_id)} • "
                         f"Refreshes every 30s • "
                         f"Pipeline: enqueue → pending → assigned → sending → sent → archive (24h)"
                )

                # Create view with action buttons
                view = DashboardView(self)

                # Load stored message ID from DB
                stored_id = None
                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        "SELECT value FROM dm_dashboard_config WHERE key='dashboard_message_id'"
                    ) as cursor:
                        row = await cursor.fetchone()
                        if row:
                            stored_id = int(row['value'])

                # Try editing existing message, fall back to sending new
                channel = self.bot.get_channel(LOG_CHANNEL_ID)
                if not channel:
                    logger.warning("[DMQueue:DASH] Log channel not found")
                    continue

                if stored_id:
                    try:
                        msg = await channel.fetch_message(stored_id)
                        await msg.edit(embed=embed, view=view)
                        try:
                            await msg.pin()
                        except discord.HTTPException:
                            pass  # Already pinned or other pin errors
                        logger.debug("[DMQueue:DASH] Dashboard message updated")
                    except discord.NotFound:
                        logger.warning("[DMQueue:DASH] Stored message deleted, posting new one")
                        stored_id = None

                if not stored_id:
                    msg = await channel.send(embed=embed, view=view)
                    try:
                        await msg.pin()
                    except discord.HTTPException:
                        pass  # Pin failed, message still updated though
                    async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                        await db.execute("PRAGMA journal_mode=WAL")
                        await db.execute("PRAGMA busy_timeout=30000")
                        await db.execute(
                            "INSERT INTO dm_dashboard_config (key, value) VALUES ('dashboard_message_id', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (str(msg.id),)
                        )
                        await db.commit()
                    logger.info(f"[DMQueue:DASH] Dashboard message created, id={msg.id}")

            except asyncio.CancelledError:
                logger.info("[DMQueue] Dashboard loop cancelled")
                break
            except Exception as e:
                logger.error(f"[DMQueue:DASH] Dashboard error: {e}", exc_info=True)

    async def _log_event(self, title: str, description: str, color=discord.Color.greyple()):
        """Log an event to the dashboard channel."""
        if not self._log_channel:
            try:
                self._log_channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                return

        try:
            embed = discord.Embed(
                title=title,
                description=description,
                color=color,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text=f"Bot {self._bot_id}")
            await self._log_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"[DMQueue:EVENT] Error logging event: {e}")

    async def _fetch_content_preview(self, job_id: int) -> str:
        """Fetch a short preview of the DM content for event log messages."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=5.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=5000")
                db.row_factory = aiosqlite.Row
                async with db.execute("SELECT content FROM dm_queue WHERE id=?", (job_id,)) as c:
                    row = await c.fetchone()
                if not row:
                    async with db.execute("SELECT content FROM dm_sent_archive WHERE original_id=?", (job_id,)) as c:
                        row = await c.fetchone()
                if not row:
                    async with db.execute("SELECT content FROM dm_failed_archive WHERE original_id=?", (job_id,)) as c:
                        row = await c.fetchone()
            if row and row['content']:
                content = row['content'].strip()
                return content[:120] + '…' if len(content) > 120 else content
        except Exception:
            pass
        return ''

    async def _ensure_log_channel(self) -> bool:
        if not self._log_channel:
            try:
                self._log_channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            except Exception:
                return False
        return True

    async def _log_event_assigned(self, job_id: int, user_id: int, assigned_bot_id: int):
        """Log when a DM is assigned — shows content preview + View Details button."""
        if not await self._ensure_log_channel():
            return
        try:
            preview = await self._fetch_content_preview(job_id)
            embed = discord.Embed(
                title="📌 DM Assigned",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="To", value=f"<@{user_id}> (`{user_id}`)", inline=True)
            embed.add_field(name="Job", value=f"`#{job_id}`", inline=True)
            embed.add_field(name="Assigned to Bot", value=f"`{assigned_bot_id}`", inline=True)
            if preview:
                embed.add_field(name="Message", value=f"```\n{preview}\n```", inline=False)
            embed.set_footer(text=f"Sent by Bot {self._bot_id}")
            view = JobEventView(self, job_id, 'assigned')
            await self._log_channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"[DMQueue:EVENT] Error logging assigned: {e}")

    async def _log_event_sent(self, job_id: int, user_id: int):
        """Log when a DM is sent — shows content preview + View Details + Retry buttons."""
        if not await self._ensure_log_channel():
            return
        try:
            preview = await self._fetch_content_preview(job_id)
            embed = discord.Embed(
                title="✅ DM Sent",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="To", value=f"<@{user_id}> (`{user_id}`)", inline=True)
            embed.add_field(name="Job", value=f"`#{job_id}`", inline=True)
            if preview:
                embed.add_field(name="Message", value=f"```\n{preview}\n```", inline=False)
            embed.set_footer(text=f"Sent by Bot {self._bot_id}")
            view = JobEventView(self, job_id, 'sent')
            await self._log_channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"[DMQueue:EVENT] Error logging sent: {e}")

    async def _log_event_failed(self, job_id: int, user_id: int, error: str):
        """Log when a DM fails — permanent failures shown differently, no retry button."""
        if not await self._ensure_log_channel():
            return
        try:
            is_permanent = any(x in error for x in ('Forbidden', 'NotFound', 'disabled', 'blocked'))

            if is_permanent:
                title = "🚫 DM Permanently Failed"
                color = discord.Color.dark_red()
                error_display = {
                    'Forbidden': '🔕 User has DMs disabled or blocked the bot',
                    'NotFound':  '👻 User account not found / deleted',
                }.get(next((k for k in ('Forbidden', 'NotFound') if k in error), ''),
                      f'❌ {error[:150]}')
            else:
                title = "❌ DM Failed (will retry)"
                color = discord.Color.red()
                error_display = f'`{error[:200]}`'

            preview = await self._fetch_content_preview(job_id)
            embed = discord.Embed(
                title=title,
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.add_field(name="To", value=f"<@{user_id}> (`{user_id}`)", inline=True)
            embed.add_field(name="Job", value=f"`#{job_id}`", inline=True)
            embed.add_field(name="Reason", value=error_display, inline=False)
            if is_permanent:
                embed.add_field(
                    name="Action",
                    value="⚠️ No retry — fix the user's DM settings before resending.",
                    inline=False
                )
            if preview:
                embed.add_field(name="Message", value=f"```\n{preview}\n```", inline=False)
            embed.set_footer(text=f"Sent by Bot {self._bot_id}")
            view = JobEventView(self, job_id, 'failed' if not is_permanent else 'failed_permanent')
            await self._log_channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"[DMQueue:EVENT] Error logging failed: {e}")

    async def _log_event_rate_limited(self, bot_id: int):
        """Log when a bot hits rate limit."""
        await self._log_event(
            title="⏱️ Rate Limited",
            description=f"Bot {bot_id} at capacity, queuing DMs",
            color=discord.Color.orange()
        )


# ══════════════════════════════════════════════════════════════════════════════
#  LOG VIEWER — View, retry, and force-retry individual DMs
# ══════════════════════════════════════════════════════════════════════════════

class JobEventView(discord.ui.View):
    """Per-job buttons on dashboard event messages. Persistent (timeout=None)."""

    def __init__(self, cog: 'DMQueueCog', job_id: int, event_type: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.job_id = job_id
        self.event_type = event_type

        self.add_item(discord.ui.Button(
            label=f"📋 View Job #{job_id}",
            style=discord.ButtonStyle.secondary,
            custom_id=f"jobact:view:{job_id}",
        ))
        if event_type == 'sent':
            self.add_item(discord.ui.Button(
                label="↩ Retry", style=discord.ButtonStyle.primary,
                custom_id=f"jobact:retry:{job_id}",
            ))
        elif event_type == 'failed':
            self.add_item(discord.ui.Button(
                label="💪 Force Retry", style=discord.ButtonStyle.danger,
                custom_id=f"jobact:force:{job_id}",
            ))
        # event_type == 'failed_permanent' → only View button (no retry for hopeless failures)


def _build_job_embed(job: dict, location: str) -> discord.Embed:
    """Build a detailed embed for a single DM job."""
    job_id = job.get('id') or job.get('original_id', '?')
    user_id = job.get('user_id', '?')

    if location == 'sent':
        color, icon, status_text = discord.Color.green(), "✅", "SENT"
    elif location == 'failed':
        color, icon = discord.Color.red(), "❌"
        status_text = f"FAILED — {job.get('fail_reason') or 'Unknown'}"
    else:
        color, icon = discord.Color.blue(), "🔄"
        status_text = (job.get('status') or 'unknown').upper()

    embed = discord.Embed(
        title=f"{icon}  JOB #{job_id}",
        description=f"**{status_text}**",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="To", value=f"<@{user_id}>  (`{user_id}`)", inline=True)
    embed.add_field(name="Attempts", value=str(job.get('attempt_count', 0)), inline=True)
    created = job.get('created_at')
    if created:
        embed.add_field(name="Created", value=f"<t:{int(created)}:R>", inline=True)
    if location == 'sent' and job.get('sent_at'):
        embed.add_field(name="Sent", value=f"<t:{int(job['sent_at'])}:R>", inline=True)
    elif location == 'failed' and job.get('failed_at'):
        embed.add_field(name="Failed", value=f"<t:{int(job['failed_at'])}:R>", inline=True)
    if job.get('source'):
        embed.add_field(name="Source", value=f"`{job['source']}`", inline=True)
    if job.get('batch_id'):
        embed.add_field(name="Batch", value=f"`{job['batch_id']}`", inline=True)
    content = job.get('content') or ''
    if content:
        preview = content[:500] + '...' if len(content) > 500 else content
        embed.add_field(name="Content", value=f"```\n{preview}\n```", inline=False)
    if location == 'failed':
        err = job.get('error_msg') or ''
        cat = job.get('error_category') or 'other'
        if err:
            embed.add_field(name=f"Error  (`{cat}`)", value=f"```\n{err[:300]}\n```", inline=False)
    return embed


class JobDetailView(discord.ui.View):
    """Buttons for a single DM job detail: Retry / Force Retry / Delete."""

    def __init__(self, cog: 'DMQueueCog', job: dict, location: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.job = job
        self.location = location
        if location == 'sent':
            btn = discord.ui.Button(label="↩ Retry (Re-send)", style=discord.ButtonStyle.primary, emoji="↩️")
            btn.callback = self._retry
            self.add_item(btn)
        elif location == 'failed':
            btn = discord.ui.Button(label="💪 Force Retry", style=discord.ButtonStyle.danger, emoji="💪")
            btn.callback = self._force_retry
            self.add_item(btn)
        elif location == 'active' and job.get('status') in ('pending', 'assigned'):
            btn = discord.ui.Button(label="🗑 Delete Job", style=discord.ButtonStyle.danger, emoji="🗑️")
            btn.callback = self._delete
            self.add_item(btn)

    async def _requeue(self, interaction, src_bot):
        job = self.job
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                await db.execute("""
                    INSERT INTO dm_queue
                    (source_bot_id, user_id, content, kwargs_json, status, created_at, batch_id, source)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                """, (
                    src_bot, job['user_id'], job.get('content'),
                    job.get('kwargs_json') or '{}', time.time(),
                    job.get('batch_id'), job.get('source'),
                ))
                await db.commit()
            await interaction.response.send_message(
                f"✅ Job `#{job.get('id')}` re-queued for delivery.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    async def _retry(self, interaction: discord.Interaction):
        await self._requeue(interaction, self.cog._bot_id)

    async def _force_retry(self, interaction: discord.Interaction):
        await self._requeue(interaction, self.job.get('source_bot_id') or self.cog._bot_id)

    async def _delete(self, interaction: discord.Interaction):
        job = self.job
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                result = await db.execute(
                    "DELETE FROM dm_queue WHERE id=? AND status IN ('pending', 'assigned')",
                    (job['id'],)
                )
                await db.commit()
            if result.rowcount:
                await interaction.response.send_message(f"🗑️ Job `#{job['id']}` deleted.", ephemeral=True)
            else:
                await interaction.response.send_message(
                    "⚠️ Could not delete — job may have already been claimed.", ephemeral=True
                )
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


class LogListView(discord.ui.View):
    """Paginated list of DM jobs with per-row [View] buttons."""

    PAGE_SIZE = 8

    def __init__(self, cog: 'DMQueueCog', jobs: list, title: str, color: discord.Color, location: str):
        super().__init__(timeout=180)
        self.cog = cog
        self.jobs = jobs
        self.title = title
        self.color = color
        self.location = location
        self.page = 0
        self._build_page()

    def _build_page(self):
        self.clear_items()
        start = self.page * self.PAGE_SIZE
        page_jobs = self.jobs[start:start + self.PAGE_SIZE]
        total_pages = max(1, (len(self.jobs) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        for job in page_jobs:
            job_id = job.get('id') or job.get('original_id', '?')
            user_id = job.get('user_id', '?')
            btn = discord.ui.Button(
                label=f"#{job_id} → user {user_id}",
                style=discord.ButtonStyle.secondary,
            )
            btn.callback = self._make_view_callback(dict(job), self.location)
            self.add_item(btn)
        if self.page > 0:
            prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.grey, row=4)
            prev_btn.callback = self._prev
            self.add_item(prev_btn)
        if (self.page + 1) < total_pages:
            next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.grey, row=4)
            next_btn.callback = self._next
            self.add_item(next_btn)

    def _make_view_callback(self, job: dict, location: str):
        async def callback(interaction: discord.Interaction):
            embed = _build_job_embed(job, location)
            view = JobDetailView(self.cog, job, location)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return callback

    def _build_list_embed(self) -> discord.Embed:
        start = self.page * self.PAGE_SIZE
        total_pages = max(1, (len(self.jobs) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        page_jobs = self.jobs[start:start + self.PAGE_SIZE]
        lines = []
        for job in page_jobs:
            job_id = job.get('id') or job.get('original_id', '?')
            user_id = job.get('user_id', '?')
            ts = job.get('created_at')
            time_str = f"<t:{int(ts)}:R>" if ts else "?"
            if self.location == 'sent':
                icon = "✅"
            elif self.location == 'failed':
                icon = f"❌ `{job.get('fail_reason') or job.get('error_category') or '?'}`"
            else:
                icon = {"pending": "⏳", "assigned": "📋", "sending": "📤", "failed": "❌"}.get(job.get('status'), "🔄")
            lines.append(f"{icon}  `#{job_id}` → <@{user_id}> ({time_str})")
        embed = discord.Embed(
            title=self.title,
            description="\n".join(lines) if lines else "*No jobs found.*",
            color=self.color,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{total_pages}  •  {len(self.jobs)} total")
        return embed

    async def _prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._build_page()
        await interaction.response.edit_message(embed=self._build_list_embed(), view=self)

    async def _next(self, interaction: discord.Interaction):
        self.page += 1
        self._build_page()
        await interaction.response.edit_message(embed=self._build_list_embed(), view=self)


class LogMenuView(discord.ui.View):
    """Entry-point view: choose Active / Sent / Failed log category. Persistent."""

    def __init__(self, cog: 'DMQueueCog'):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="📤 Active Jobs", style=discord.ButtonStyle.primary, custom_id="logmenu:active")
    async def active(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        jobs = await self.cog._log_viewer_get_active()
        view = LogListView(self.cog, jobs, "📤 Active DM Jobs", discord.Color.blue(), 'active')
        await interaction.followup.send(embed=view._build_list_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="✅ Sent (24h)", style=discord.ButtonStyle.success, custom_id="logmenu:sent")
    async def sent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        jobs = await self.cog._log_viewer_get_sent()
        view = LogListView(self.cog, jobs, "✅ Sent DMs (last 24h)", discord.Color.green(), 'sent')
        await interaction.followup.send(embed=view._build_list_embed(), view=view, ephemeral=True)

    @discord.ui.button(label="❌ Failed", style=discord.ButtonStyle.danger, custom_id="logmenu:failed")
    async def failed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        jobs = await self.cog._log_viewer_get_failed()
        view = LogListView(self.cog, jobs, "❌ Failed DMs", discord.Color.red(), 'failed')
        await interaction.followup.send(embed=view._build_list_embed(), view=view, ephemeral=True)


class DashboardView(discord.ui.View):
    """Interactive buttons for dashboard actions."""

    def __init__(self, cog: DMQueueCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Retry Stuck", custom_id="dmq:retry_failed", style=discord.ButtonStyle.danger, emoji="🔄")
    async def retry_failed(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Retry failed DMs (only retryable ones, skip permanent failures)."""
        await interaction.response.defer()
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row

                # Only retry transient failures (not DMs disabled, user not found, etc)
                await db.execute("""
                    UPDATE dm_queue
                    SET status='pending', attempt_count=attempt_count+1, error_msg=NULL
                    WHERE status='failed'
                    AND error_msg NOT LIKE '%Forbidden%'
                    AND error_msg NOT LIKE '%NotFound%'
                    AND error_msg NOT LIKE '%InvalidArgument%'
                """)
                await db.commit()

                async with db.execute("SELECT COUNT(*) as count FROM dm_queue WHERE status='pending'") as cursor:
                    row = await cursor.fetchone()
                    count = row['count'] if row else 0

            await interaction.followup.send(f"✅ Retried transient failures. Now {count} pending.", ephemeral=True)
            logger.info(f"[DMQueue:DASH] Retry failed button used: {count} DMs reset to pending")
        except Exception as e:
            logger.error(f"[DMQueue:DASH] Error in retry_failed: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Clear Queue", custom_id="dmq:clear_db", style=discord.ButtonStyle.secondary, emoji="🗑️")
    async def clear_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Clear active DM queue (pending/assigned/sending/sent/failed) — archives are preserved."""
        await interaction.response.send_message(
            "⚠️ **Are you sure?** This will delete all active queue DMs. Archives are preserved.",
            ephemeral=True,
            delete_after=30.0
        )

        # Add confirm button
        async def confirm_clear(confirm_interaction: discord.Interaction):
            await confirm_interaction.response.defer()
            try:
                async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.execute("PRAGMA busy_timeout=30000")
                    await db.execute("DELETE FROM dm_queue")
                    await db.commit()

                await confirm_interaction.followup.send("✅ Active queue cleared! (Archives preserved)", ephemeral=True)
                logger.info("[DMQueue:DASH] Active queue cleared by user action")
            except Exception as e:
                logger.error(f"[DMQueue:DASH] Error clearing database: {e}")
                await confirm_interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

        confirm_view = discord.ui.View()
        confirm_button = discord.ui.Button(label="Yes, Clear Active Queue", style=discord.ButtonStyle.danger)
        confirm_button.callback = confirm_clear
        confirm_view.add_item(confirm_button)

        await interaction.edit_original_response(view=confirm_view)

    @discord.ui.button(label="Reset Rate Limit", custom_id="dmq:bypass_ratelimit", style=discord.ButtonStyle.primary, emoji="⚡")
    async def bypass_rate_limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Allow a bot to send immediately, bypassing rate limit."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row

                async with db.execute("SELECT bot_id FROM dm_bot_registry ORDER BY bot_id") as cursor:
                    bots = await cursor.fetchall()

            if not bots:
                await interaction.response.send_message("❌ No bots registered", ephemeral=True)
                return

            # Create dropdown for bot selection
            class BotSelectView(discord.ui.View):
                def __init__(self, bot_list):
                    super().__init__()
                    self.bot_list = bot_list

                @discord.ui.select(
                    placeholder="Select a bot to bypass rate limit",
                    min_values=1,
                    max_values=1,
                    options=[discord.SelectOption(label=f"Bot {bot['bot_id']}", value=str(bot['bot_id'])) for bot in bots]
                )
                async def select_bot(self, select_interaction: discord.Interaction, select: discord.ui.Select):
                    await select_interaction.response.defer()
                    bot_id = int(select.values[0])

                    try:
                        async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                            await db.execute("PRAGMA journal_mode=WAL")
                            await db.execute("PRAGMA busy_timeout=30000")
                            # Reset rate limit counters for selected bot
                            await db.execute("""
                                UPDATE dm_bot_registry
                                SET last_send=0, sends_window='[]'
                                WHERE bot_id=?
                            """, (bot_id,))
                            await db.commit()

                        await select_interaction.followup.send(f"✅ Rate limit bypassed for Bot {bot_id}", ephemeral=True)
                        logger.info(f"[DMQueue:DASH] Rate limit bypassed for bot {bot_id}")
                    except Exception as e:
                        logger.error(f"[DMQueue:DASH] Error bypassing rate limit: {e}")
                        await select_interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

            select_view = BotSelectView(bots)
            await interaction.response.send_message("Choose a bot:", view=select_view, ephemeral=True, delete_after=30.0)
        except Exception as e:
            logger.error(f"[DMQueue:DASH] Error in bypass_rate_limit: {e}")
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @discord.ui.button(label="Logs", custom_id="dmq:logs", style=discord.ButtonStyle.secondary, emoji="📋")
    async def view_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Open the DM log viewer — browse, inspect, and retry individual DMs."""
        view = LogMenuView(self.cog)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📋 DM Log Viewer",
                description=(
                    "Browse individual DMs by status.\n"
                    "Click any job to see full details + retry options."
                ),
                color=discord.Color.blurple(),
            ),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="Force Assign", custom_id="dmq:force_send", style=discord.ButtonStyle.success, emoji="📤")
    async def force_send_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Force send all pending DMs from one bot."""
        try:
            async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                db.row_factory = aiosqlite.Row

                async with db.execute("SELECT bot_id FROM dm_bot_registry ORDER BY bot_id") as cursor:
                    bots = await cursor.fetchall()

            if not bots:
                await interaction.response.send_message("❌ No bots registered", ephemeral=True)
                return

            class ForceSelectView(discord.ui.View):
                def __init__(self, bot_list, cog_ref):
                    super().__init__()
                    self.bot_list = bot_list
                    self.cog = cog_ref

                @discord.ui.select(
                    placeholder="Select a bot to send all its assigned DMs",
                    min_values=1,
                    max_values=1,
                    options=[discord.SelectOption(label=f"Bot {bot['bot_id']}", value=str(bot['bot_id'])) for bot in bots]
                )
                async def select_bot(self, select_interaction: discord.Interaction, select: discord.ui.Select):
                    await select_interaction.response.defer()
                    bot_id = int(select.values[0])

                    try:
                        async with aiosqlite.connect(SHARED_DB, timeout=10.0) as db:
                            await db.execute("PRAGMA journal_mode=WAL")
                            await db.execute("PRAGMA busy_timeout=30000")
                            db.row_factory = aiosqlite.Row

                            # Get all pending jobs and reassign to this bot
                            async with db.execute("""
                                SELECT id FROM dm_queue WHERE status='pending'
                            """) as cursor:
                                pending = await cursor.fetchall()

                            for job in pending:
                                await db.execute("""
                                    UPDATE dm_queue
                                    SET status='assigned', assigned_bot_id=?, assigned_at=?
                                    WHERE id=? AND status='pending'
                                """, (bot_id, time.time(), job['id']))

                            await db.commit()

                        await select_interaction.followup.send(f"✅ Assigned {len(pending)} pending DMs to Bot {bot_id}", ephemeral=True)
                        logger.info(f"[DMQueue:DASH] Force send: {len(pending)} DMs assigned to bot {bot_id}")
                    except Exception as e:
                        logger.error(f"[DMQueue:DASH] Error in force send: {e}")
                        await select_interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

            select_view = ForceSelectView(bots, self.cog)
            await interaction.response.send_message("Choose a bot:", view=select_view, ephemeral=True, delete_after=30.0)
        except Exception as e:
            logger.error(f"[DMQueue:DASH] Error in force_send_all: {e}")
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)


async def setup(bot):
    global _dm_queue_instance
    cog = DMQueueCog(bot)
    _dm_queue_instance = cog
    await bot.add_cog(cog)
    logger.info("[DMQueue] Cog registered")
