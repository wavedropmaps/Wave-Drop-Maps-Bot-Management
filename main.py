"""
Main Bot Entry Point - WITH RATE LIMIT DETECTION
Discord Staff Activity Bot

[OK] COMPREHENSIVE RATE LIMIT TRACKING & LOGGING
[OK] Warns when requests get low (<3 remaining)
[OK] Full alerts on actual rate limit hits
[OK] Logs all rate limits to rate_limits.log file  ← NOW ACTUALLY WORKS
[OK] Tracks rate limits by route/bucket
[OK] Shows recent activity when rate limited
✅ Auto-deletes old logs, keeps only 5 most recent
"""

import discord
import discord.abc

# ✅ STORE ORIGINAL DISCORD SEND METHODS FROM BASE CLASS (immune to patching)
_original_messageable_send = discord.abc.Messageable.send

from discord.ext import commands

# Create wrapper functions that call the base method
async def _original_user_send(self, *args, **kwargs):
    return await _original_messageable_send(self, *args, **kwargs)

async def _original_member_send(self, *args, **kwargs):
    return await _original_messageable_send(self, *args, **kwargs)

# ✅ ADD GLOBAL MESSAGE DELETION DEBUG HOOK
_original_message_delete = discord.Message.delete

async def _patched_message_delete(self, *args, **kwargs):
    import traceback
    print("\n" + "!"*60)
    print(f"[ULTRA-DEBUG] 🚨 BOT IS DELETING A MESSAGE 🚨")
    print(f"Message ID: {self.id}")
    print(f"Author: {self.author} (ID: {self.author.id if hasattr(self.author, 'id') else 'N/A'})")
    print(f"Channel: {getattr(self.channel, 'name', 'Unknown')} (ID: {getattr(self.channel, 'id', 'N/A')})")
    print(f"Content: {self.content[:150]}")
    print("[ULTRA-DEBUG] Call Stack (Who triggered this delete?):")
    # Print the stack trace so we can see EXACTLY which file/line caused the deletion
    tb = ''.join(traceback.format_stack()[-8:-1])
    print(tb)
    print("!"*60 + "\n")
    return await _original_message_delete(self, *args, **kwargs)

discord.Message.delete = _patched_message_delete

from datetime import datetime, timezone
import logging
import os
from dotenv import load_dotenv
import asyncio
import traceback
import difflib
from pathlib import Path
import database
import json
import sys
from tasks import leaderboard_updater
from database_backups import database_backup

# [OK] Export for use in cogs
__all__ = ['bot', 'log_sent_dm']

# Configure Python import system to discover local modules
# This ensures that the commands/ directory can be imported as a package
workspace_root = Path(__file__).parent
commands_dir = workspace_root / 'commands'

if str(commands_dir) not in sys.path:
    sys.path.append(str(commands_dir))
    sys.path.append(str(workspace_root))

# ==================== EARLY STARTUP LOGGING ====================
print("="*60)
print("[BOT] BOT STARTUP SEQUENCE INITIATED")
print("="*60)
print(f"[DATE] Timestamp: {datetime.now()}")
print(f"[PYTHON] Python Version: {sys.version}")
print(f"[DISCORD] Discord.py Version: {discord.__version__}")
print(f"[DIR] Working Directory: {os.getcwd()}")
print(f"[DIR] Script Location: {Path(__file__).parent}")
print("-"*60)

# Add a massive separator to the log file
logger = logging.getLogger('discord')
logger.info("\n" + "="*100)
logger.info("="*100)
logger.info("[ROCKET][ROCKET][ROCKET] NEW BOT STARTUP - " + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') + " [ROCKET][ROCKET][ROCKET]")
logger.info("="*100)
logger.info("="*100 + "\n")

# Load environment variables
print("[ENV] Loading environment variables...")
try:
    load_dotenv()
    print("[OK] .env file loaded successfully")
except Exception as e:
    print(f"[ERROR] ERROR loading .env: {e}")
    traceback.print_exc()

# Check for .env file
env_path = Path('.env')
if env_path.exists():
    print(f"[OK] .env file found at: {env_path.absolute()}")
else:
    print(f"[WARN] WARNING: .env file NOT found at: {env_path.absolute()}")

# Setup logging
print("\n[LOG] Setting up logging system...")
try:
    from logging.handlers import RotatingFileHandler

    # Force all log timestamps to UTC
    logging.Formatter.converter = __import__('time').gmtime

    # Create logs/ folder
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)

    # Custom rotating handler that names files by date on rollover
    class DateNamedRotatingHandler(RotatingFileHandler):
        """Rotates at maxBytes, naming each new file by the current UTC date.
        If multiple files are created on the same day, appends _2, _3, etc."""
        def _current_log_path(self):
            date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            base = logs_dir / f"bot_{date_str}.log"
            if not base.exists():
                return str(base)
            counter = 2
            while True:
                candidate = logs_dir / f"bot_{date_str}_{counter}.log"
                if not candidate.exists():
                    return str(candidate)
                counter += 1

        def doRollover(self):
            if self.stream:
                self.stream.close()
                self.stream = None
            self.baseFilename = self._current_log_path()
            self.stream = self._open()

    # Pick today's log file as the initial file
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    initial_log = logs_dir / f"bot_{date_str}.log"

    file_handler = DateNamedRotatingHandler(
        filename=str(initial_log),
        maxBytes=30 * 1024 * 1024,  # 30 MB
        backupCount=0,              # we handle naming ourselves
        encoding='utf-8'
    )

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logging.root.setLevel(logging.INFO)
    logging.root.handlers = []
    logging.root.addHandler(file_handler)
    logging.root.addHandler(stream_handler)

    logger = logging.getLogger('discord')
    logger.setLevel(logging.INFO)
    print("[OK] Logging system initialized (timestamps in UTC)")
    print(f"[FOLDER] Log folder: {logs_dir.absolute()}")
    print(f"[FILE] Current log file: {initial_log.absolute()} (rotates at 30 MB)")
except Exception as e:
    print(f"[ERROR] ERROR setting up logging: {e}")
    traceback.print_exc()
    logger = logging.getLogger('discord')

# ==================== LOG CLEANUP (KEEP ONLY 5 MOST RECENT) ====================

def cleanup_old_logs(logs_path: Path, keep: int = 5):
    """
    Deletes old bot_*.log files, keeping only the `keep` most recent ones.
    Never touches rate_limits.log or bot.log.
    """
    try:
        # Only target bot date-stamped log files
        log_files = sorted(
            [f for f in logs_path.glob('bot_*.log') if f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True  # newest first
        )

        to_delete = log_files[keep:]  # everything beyond the 5 most recent

        if to_delete:
            print(f"\n[CLEAN] Log cleanup: found {len(log_files)} log files, keeping {keep}, deleting {len(to_delete)}")
            for old_log in to_delete:
                try:
                    old_log.unlink()
                    print(f"   [DEL] Deleted: {old_log.name}")
                    logger.info(f"🗑️ Deleted old log: {old_log.name}")
                except Exception as e:
                    print(f"   [WARN] Could not delete {old_log.name}: {e}")
                    logger.warning(f"Could not delete old log {old_log.name}: {e}")
        else:
            print(f"\n[CLEAN] Log cleanup: {len(log_files)} log file(s) present, no cleanup needed (limit: {keep})")

    except Exception as e:
        print(f"[WARN] Log cleanup failed: {e}")
        logger.warning(f"Log cleanup failed: {e}")

# Run cleanup immediately on startup (after logging is set up)
cleanup_old_logs(logs_dir, keep=5)

# Bot Token
print("\n[KEY] Checking bot token...")
BOT_TOKEN = os.getenv('BOT_TOKEN')
if BOT_TOKEN:
    token_preview = BOT_TOKEN[:10] + "..." + BOT_TOKEN[-5:] if len(BOT_TOKEN) > 15 else "***"
    print(f"[OK] BOT_TOKEN found (length: {len(BOT_TOKEN)}, preview: {token_preview})")
else:
    print("[ERROR] ERROR: BOT_TOKEN not found in environment variables!")

# Bot setup with all intents
print("\n[BOT] Creating bot instance...")
try:
    intents = discord.Intents.all()
    print(f"[OK] Intents configured")
    
    bot = commands.Bot(
        command_prefix='>',
        intents=intents,
        case_insensitive=True,
        help_command=None
    )
    print("[OK] Bot instance created successfully")
    print(f"   - Command prefix: >")
    print(f"   - Case insensitive: True")
    print(f"   - Help command: Disabled")
except Exception as e:
    print(f"[ERROR] ERROR creating bot instance: {e}")
    traceback.print_exc()
    sys.exit(1)

# ✅ SET BOT INSTANCE FOR AUTOMATIC STRIKE REMOVAL
print("\n[LINK] Setting bot instance for database...")
try:
    database.set_bot_instance(bot)
    print("[OK] Database bot instance set")
except Exception as e:
    print(f"[WARN] WARNING setting database bot instance: {e}")

# ==================== RATE LIMIT DETECTION & LOGGING ====================

print("\n[LIGHTNING] Setting up rate limit detection...")

# Track rate limits
rate_limit_tracker = {
    'total_hits': 0,
    'warnings': 0,
    'by_route': {},
    'by_resource': {},
    'recent_hits': []
}
# ✅ Attach to bot immediately so cogs can access via self.bot.rate_limit_tracker
bot.rate_limit_tracker = rate_limit_tracker

# ── Helper: write a line to rate_limits.log ───────────────────────────────────
def _write_rate_limit_log(lines: str):
    """Safely append to rate_limits.log — used by both warning and error paths."""
    try:
        with open(str(logs_dir / 'rate_limits.log'), 'a', encoding='utf-8') as f:
            f.write(lines)
    except Exception as log_error:
        logger.error(f"Failed to write to rate_limits.log: {log_error}")

# Monkey-patch HTTPClient to log rate limits
from discord.http import HTTPClient
_original_request = HTTPClient.request

async def _patched_request(self, *args, **kwargs):
    """Patched request method that logs rate limit info"""
    route_info = args[0] if args else 'unknown'
    route_str = str(route_info)
    
    try:
        response = await _original_request(self, *args, **kwargs)
        
        # Log rate limit headers if present
        if hasattr(response, 'headers'):
            remaining = response.headers.get('X-RateLimit-Remaining')
            limit = response.headers.get('X-RateLimit-Limit')
            reset_after = response.headers.get('X-RateLimit-Reset-After')
            bucket = response.headers.get('X-RateLimit-Bucket')
            scope = response.headers.get('X-RateLimit-Scope', 'user')
            
            # Track by bucket
            if bucket:
                if bucket not in rate_limit_tracker['by_route']:
                    rate_limit_tracker['by_route'][bucket] = {
                        'route': route_str,
                        'hits': 0,
                        'limit': limit,
                        'last_remaining': remaining,
                        'scope': scope
                    }
                rate_limit_tracker['by_route'][bucket]['hits'] += 1
                rate_limit_tracker['by_route'][bucket]['last_remaining'] = remaining
            
            # Warn if getting close to limit
            if remaining and limit:
                remaining_int = int(remaining)
                limit_int = int(limit)
                
                # WARNING: Less than 3 requests remaining
                if remaining_int < 3 and limit_int > 10:
                    rate_limit_tracker['warnings'] += 1
                    
                    warning_msg = (
                        f"[WARN] RATE LIMIT WARNING #{rate_limit_tracker['warnings']}\n"
                        f"   Route: {route_str}\n"
                        f"   Bucket: {bucket}\n"
                        f"   Scope: {scope}\n"
                        f"   Remaining: {remaining}/{limit}\n"
                        f"   Reset in: {reset_after}s"
                    )
                    
                    logger.warning(warning_msg)
                    print(f"\n{warning_msg}\n")
                    
                    # Track recent activity
                    hit_entry = {
                        'timestamp': datetime.now().isoformat(),
                        'route': route_str,
                        'bucket': bucket,
                        'scope': scope,
                        'remaining': remaining_int,
                        'limit': limit_int
                    }
                    rate_limit_tracker['recent_hits'].append(hit_entry)
                    
                    # Keep only last 100 hits
                    rate_limit_tracker['recent_hits'] = rate_limit_tracker['recent_hits'][-100:]

                    # ✅ FIX: Write warnings to rate_limits.log
                    # (discord.py retries 429s internally so the except block rarely fires —
                    #  writing here ensures the file actually gets populated)
                    _write_rate_limit_log(
                        f"[{hit_entry['timestamp']}] [WARN] WARNING #{rate_limit_tracker['warnings']} | "
                        f"Route: {route_str} | Bucket: {bucket} | Scope: {scope} | "
                        f"Remaining: {remaining}/{limit} | Reset in: {reset_after}s\n"
                    )
                    # Wave-Logging dashboard event (rate_limits tab)
                    try:
                        from core.global_logger import log_event as _wl_event
                        _spawn(_wl_event(
                            category="rate_limits",
                            action="rate_limit_warning",
                            details={
                                "warning_number": rate_limit_tracker['warnings'],
                                "route": route_str,
                                "bucket": bucket,
                                "scope": scope,
                                "remaining": remaining,
                                "limit": limit,
                                "reset_after": reset_after,
                            },
                        ))
                    except Exception:
                        pass

        return response
        
    except discord.HTTPException as e:
        if e.status == 429:
            # 🚨 ACTUAL RATE LIMIT HIT
            # Note: discord.py usually handles 429s internally (retries before raising),
            # so this block fires rarely — the warning block above is the primary logger.
            rate_limit_tracker['total_hits'] += 1
            
            retry_after = e.response.headers.get('Retry-After', 'unknown') if hasattr(e, 'response') else 'unknown'
            global_limit = e.response.headers.get('X-RateLimit-Global', False) if hasattr(e, 'response') else False
            scope = e.response.headers.get('X-RateLimit-Scope', 'user') if hasattr(e, 'response') else 'user'
            bucket = e.response.headers.get('X-RateLimit-Bucket', 'unknown') if hasattr(e, 'response') else 'unknown'
            
            error_msg = (
                f"\n{'='*70}\n"
                f"[ALERT] RATE LIMIT HIT #{rate_limit_tracker['total_hits']}\n"
                f"{'='*70}\n"
                f"Timestamp: {datetime.now()}\n"
                f"Route: {route_str}\n"
                f"Bucket: {bucket}\n"
                f"Scope: {scope}\n"
                f"Global: {global_limit}\n"
                f"Retry After: {retry_after}s\n"
                f"Error: {e.text if hasattr(e, 'text') else str(e)}\n"
                f"{'='*70}\n"
            )
            
            logger.error(error_msg)
            print(error_msg)

            # Build recent activity lines
            recent_lines = "".join(
                f"  [{h['timestamp']}] {h['route']} | "
                f"{h['remaining']}/{h['limit']} remaining | "
                f"Bucket: {h.get('bucket', 'N/A')}\n"
                for h in rate_limit_tracker['recent_hits'][-10:]
            )

            _write_rate_limit_log(
                f"\n{'='*70}\n"
                f"[{datetime.now()}] [ALERT] RATE LIMIT HIT #{rate_limit_tracker['total_hits']}\n"
                f"{'='*70}\n"
                f"Route: {route_str}\n"
                f"Bucket: {bucket}\n"
                f"Scope: {scope}\n"
                f"Global: {global_limit}\n"
                f"Retry After: {retry_after}s\n"
                f"Error: {e.text if hasattr(e, 'text') else str(e)}\n\n"
                f"RECENT ACTIVITY (last 10 requests):\n"
                f"{recent_lines}"
                f"\n{'='*70}\n"
            )

            print(f"[NOTE] Rate limit logged to: logs/rate_limits.log")

            # Wave-Logging dashboard event (rate_limits tab — actual 429 hit)
            try:
                from core.global_logger import log_event as _wl_event
                _spawn(_wl_event(
                    category="rate_limits",
                    action="rate_limit_hit",
                    details={
                        "hit_number": rate_limit_tracker['total_hits'],
                        "route": route_str,
                        "bucket": bucket,
                        "scope": scope,
                        "global": global_limit,
                        "retry_after": retry_after,
                        "error_text": e.text if hasattr(e, 'text') else str(e),
                    },
                ))
            except Exception:
                pass

        raise

HTTPClient.request = _patched_request
print("[OK] Rate limit detection enabled")
print("   [CHART] Rate limits will be logged to: logs/rate_limits.log")
print("   [WARN] Warnings at <3 remaining requests (now logged to file [OK])")
print("   [ALERT] Full alerts on actual rate limit hits")

# Add command to check rate limit stats
@bot.command(name='ratelimitstats', aliases=['rlstats', 'rls'])
@commands.has_any_role('007', '+', 'Management')
async def rate_limit_stats(ctx):
    """Show rate limit statistics"""
    
    embed = discord.Embed(
        title="[LIGHTNING] Rate Limit Statistics",
        color=discord.Color.orange(),
        timestamp=datetime.now(timezone.utc)
    )
    
    embed.add_field(
        name="[CHART] Overall Stats",
        value=(
            f"**Total Rate Limit Hits:** {rate_limit_tracker['total_hits']}\n"
            f"**Warnings Issued:** {rate_limit_tracker['warnings']}\n"
            f"**Tracked Buckets:** {len(rate_limit_tracker['by_route'])}"
        ),
        inline=False
    )
    
    # Show most active routes
    if rate_limit_tracker['by_route']:
        top_routes = sorted(
            rate_limit_tracker['by_route'].items(),
            key=lambda x: x[1]['hits'],
            reverse=True
        )[:5]
        
        routes_text = ""
        for bucket, data in top_routes:
            routes_text += (
                f"**Bucket:** `{bucket[:30]}...`\n"
                f"├─ Hits: {data['hits']}\n"
                f"├─ Limit: {data.get('limit', 'N/A')}\n"
                f"└─ Last Remaining: {data.get('last_remaining', 'N/A')}\n\n"
            )
        
        embed.add_field(
            name="[FIRE] Top 5 Most Used Routes",
            value=routes_text[:1024] if routes_text else "No data",
            inline=False
        )
    
    # Show recent warnings
    if rate_limit_tracker['recent_hits']:
        recent_text = ""
        for hit in rate_limit_tracker['recent_hits'][-5:]:
            recent_text += (
                f"`{hit['timestamp']}`\n"
                f"└─ {hit['remaining']}/{hit['limit']} remaining\n"
            )
        
        embed.add_field(
            name="[WARN] Recent Warnings",
            value=recent_text[:1024] if recent_text else "No warnings",
            inline=False
        )
    
    embed.set_footer(text="Use >ratelimitstats to check rate limit status")
    
    await ctx.send(embed=embed)

# Store bot launch time for uptime tracking
bot.launch_time = None

# ==================== DM LOGGING - SIMPLE VERSION ====================

RECEIVE_LOG_CHANNEL = 1411027953046781982
SEND_LOG_CHANNEL = 1411032010494967838

print(f"\n[MAIL] DM Logging configured:")
print(f"   - Receive channel: {RECEIVE_LOG_CHANNEL}")
print(f"   - Send channel: {SEND_LOG_CHANNEL}")

# ── Define logging function BEFORE monkey-patch (functions below will call it) ──
async def _log_sent_dm_internal(user, content=None, kwargs=None):
    """Logs any DM the bot sends — text, embeds, files, all of it."""
    if kwargs is None:
        kwargs = {}
    try:
        channel = bot.get_channel(SEND_LOG_CHANNEL)
        if not channel:
            try:
                channel = await bot.fetch_channel(SEND_LOG_CHANNEL)
            except Exception as fetch_err:
                logger.debug(f"[LOG_DM] Skipping DM log — channel fetch failed: {fetch_err}")
                return

        logger.info(f"[LOG_DM] Logging DM to user {user.id} in channel {SEND_LOG_CHANNEL}")

        embed = discord.Embed(
            title="[OUTBOX] DM Sent",
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
            embed.add_field(name="[SPEECH] Content", value=text, inline=False)

        # Single embed
        sent_embed = kwargs.get('embed')
        if sent_embed:
            parts = []
            if sent_embed.title:       parts.append(f"**Title:** {sent_embed.title}")
            if sent_embed.description: parts.append(f"**Desc:** {sent_embed.description[:200]}")
            if sent_embed.footer.text: parts.append(f"**Footer:** {sent_embed.footer.text}")
            if sent_embed.fields:      parts.append(f"**Fields:** {', '.join(f.name for f in sent_embed.fields[:5])}")
            embed.add_field(name="[CLIPBOARD] Embed", value="\n".join(parts) if parts else "*(empty)*", inline=False)

        # Multiple embeds
        for i, e in enumerate(kwargs.get('embeds', []), 1):
            parts = []
            if e.title:       parts.append(f"**Title:** {e.title}")
            if e.description: parts.append(f"**Desc:** {e.description[:200]}")
            embed.add_field(name=f"[CLIPBOARD] Embed {i}", value="\n".join(parts) if parts else "*(empty)*", inline=False)

        # Files
        all_files = ([kwargs['file']] if 'file' in kwargs else []) + list(kwargs.get('files', []))
        if all_files:
            embed.add_field(name=f"[FOLDER] Files ({len(all_files)})", value="\n".join(f"[PAPERCLIP] {f.filename}" for f in all_files if hasattr(f, 'filename'))[:1024], inline=False)

        # Fallback if nothing logged
        if not content and not sent_embed and not kwargs.get('embeds') and not all_files:
            embed.add_field(name="[WARN] Note", value="*DM sent but no loggable content detected*", inline=False)

        if hasattr(user, 'avatar') and user.avatar:
            embed.set_thumbnail(url=user.avatar.url)

        await channel.send(embed=embed)
        logger.info(f"[LOG_DM] Successfully logged DM to user {user.id}")

        # Wave-Logging dashboard event (dms_sent tab)
        try:
            from core.global_logger import log_event as _wl_event
            sent_embed_obj = kwargs.get('embed')
            await _wl_event(
                category="dms_sent",
                action="dm_sent",
                target=user,
                details={
                    "content": (content or "")[:1500] if content else None,
                    "embed_title": sent_embed_obj.title if sent_embed_obj else None,
                    "embed_description": (sent_embed_obj.description or "")[:500] if sent_embed_obj else None,
                    "extra_embeds": len(kwargs.get('embeds', [])),
                    "file_count": len(([kwargs['file']] if 'file' in kwargs else []) + list(kwargs.get('files', []))),
                },
            )
        except Exception:
            pass
    except Exception as e:
        logger.error(f"[LOG_DM] Error logging sent DM: {e}", exc_info=True)

# ── Patch BOTH User.send and Member.send ──────────────────────────────────────
# discord.Member.send and discord.User.send are SEPARATE methods.
# Every file that calls member.send() bypasses a User-only patch.
# Patching both here means EVERY outgoing DM across ALL cogs gets caught
# automatically — no changes needed in any other file.
# _original_user_send and _original_member_send stored at top of file (before imports)

_resolver_diag_logged = {'get_cog': False, 'cogs_walk': False, 'sys_modules': False, 'all_failed': False}

def _resolve_dm_queue_cog():
    """Resolve the DMQueueCog via three fallback paths.

    Why so many paths: bot.get_cog('DMQueueCog') is observed to return None
    intermittently even when the cog is loaded. The dual-module-instance quirk
    (tasks.dm_queue exists twice in memory because reply_dm_inbound.py imports it
    before discord.py loads it as an extension) means lookups can land on
    instance A while the live cog lives on instance B. Walk all paths."""
    cog = bot.get_cog('DMQueueCog')
    if cog is not None:
        if not _resolver_diag_logged['get_cog']:
            logger.info("[DMQueue:RESOLVE] First success via bot.get_cog")
            _resolver_diag_logged['get_cog'] = True
        return cog

    for c in bot.cogs.values():
        if type(c).__name__ == 'DMQueueCog':
            if not _resolver_diag_logged['cogs_walk']:
                logger.warning("[DMQueue:RESOLVE] get_cog returned None — found via bot.cogs walk (cog registered under unexpected key)")
                _resolver_diag_logged['cogs_walk'] = True
            return c

    import sys
    mod = sys.modules.get('tasks.dm_queue')
    if mod is not None:
        inst = getattr(mod, '_dm_queue_instance', None)
        if inst is not None:
            if not _resolver_diag_logged['sys_modules']:
                logger.warning("[DMQueue:RESOLVE] Falling back to sys.modules singleton — cog not in bot.cogs at all")
                _resolver_diag_logged['sys_modules'] = True
            return inst

    if not _resolver_diag_logged['all_failed']:
        logger.error(f"[DMQueue:RESOLVE] All resolver paths failed. bot.cogs keys: {list(bot.cogs.keys())}")
        _resolver_diag_logged['all_failed'] = True
    return None


# Strong references to fire-and-forget background tasks. asyncio keeps only a
# WEAK ref to a Task, so without this the GC can collect (and silently cancel) a
# task mid-run, dropping the work. The done-callback removes each task when it
# finishes, so this set only ever holds currently-running tasks — it self-drains
# and can't grow unbounded.
_background_tasks: set = set()


def _spawn(coro):
    """Schedule a background coroutine while holding a strong reference to it."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _patched_user_send(self, content=None, **kwargs):
    """Routes all User DMs through the rate-limit queue."""
    inst = _resolve_dm_queue_cog()
    if inst is not None:
        inst.enqueue(self, content=content, **kwargs)
        return None
    # Fallback: cog not loaded yet (very early startup, before load_extensions completes)
    logger.warning(f"[DMQueue] PATCH_FALLBACK: Cog not found! Sending directly to {self}")
    result = await _original_user_send(self, content=content, **kwargs)
    _spawn(_log_sent_dm_internal(self, content=content, kwargs=kwargs))
    return result

async def _patched_member_send(self, content=None, **kwargs):
    """Routes all Member DMs through the rate-limit queue."""
    inst = _resolve_dm_queue_cog()
    if inst is not None:
        inst.enqueue(self, content=content, **kwargs)
        return None
    # Fallback: cog not loaded yet (very early startup, before load_extensions completes)
    logger.warning(f"[DMQueue] PATCH_FALLBACK: Cog not found! Sending directly to {self}")
    result = await _original_member_send(self, content=content, **kwargs)
    _spawn(_log_sent_dm_internal(self, content=content, kwargs=kwargs))
    return result

discord.User.send   = _patched_user_send
discord.Member.send = _patched_member_send
print("[OK] DM logging monkey-patch applied (User.send + Member.send)")

@bot.event
async def on_message(message):
    """Process commands and log received DMs"""
    if message.guild is None and not message.author.bot:
        _spawn(log_received_dm(message))
    await bot.process_commands(message)

async def _get_last_sent_dm(user_id: int):
    """Return (summary, sent_at) of the most recent outbound DM to user_id, or (None, None)."""
    try:
        import aiosqlite as _aio
        import json as _json
        import time as _time
        SHARED_DB = "C:/Users/kiere/Desktop/dm_shared_queue.db"
        async with _aio.connect(SHARED_DB, timeout=5.0) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            db.row_factory = _aio.Row
            # Check active queue (recently sent, not yet archived) and archive together
            async with db.execute("""
                SELECT content, kwargs_json, sent_at FROM (
                    SELECT content, kwargs_json, sent_at FROM dm_queue
                    WHERE user_id=? AND status='sent' AND sent_at IS NOT NULL
                    UNION ALL
                    SELECT content, kwargs_json, sent_at FROM dm_sent_archive
                    WHERE user_id=?
                )
                ORDER BY sent_at DESC
                LIMIT 1
            """, (user_id, user_id)) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None, None
        text = row['content']
        if not text:
            try:
                kw = _json.loads(row['kwargs_json'] or '{}')
                emb = kw.get('embed') or (kw.get('embeds') or [None])[0]
                if emb:
                    parts = []
                    if emb.get('title'): parts.append(emb['title'])
                    if emb.get('description'): parts.append(emb['description'][:200])
                    text = " — ".join(parts) if parts else "*embed (no text)*"
                else:
                    text = "*no text content*"
            except Exception:
                text = "*unknown*"
        sent_at = row['sent_at']
        return text[:400], sent_at
    except Exception as e:
        logger.debug(f"[log_received_dm] could not fetch last sent DM: {e}")
        return None, None


async def log_received_dm(message):
    """Log a DM received from a user"""
    try:
        channel = bot.get_channel(RECEIVE_LOG_CHANNEL)
        if not channel:
            return

        embed = discord.Embed(
            title="[INBOX] DM Received",
            color=discord.Color.blue(),
            timestamp=message.created_at
        )
        embed.add_field(
            name="From",
            value=f"{message.author.mention} ({message.author})\nID: `{message.author.id}`",
            inline=False
        )

        content = message.content if message.content else "*No text*"
        if len(content) > 1024:
            content = content[:1021] + "..."
        embed.add_field(name="Message", value=content, inline=False)

        if message.attachments:
            attachments = "\n".join([f"[{a.filename}]({a.url})" for a in message.attachments])
            embed.add_field(name="Attachments", value=attachments[:1024], inline=False)

        # Show the last thing the bot said to this user for context
        last_text, last_sent_at = await _get_last_sent_dm(message.author.id)
        if last_text:
            import time as _time
            age_s = _time.time() - last_sent_at
            if age_s < 3600:
                age_str = f"{int(age_s // 60)}m ago"
            elif age_s < 86400:
                age_str = f"{age_s / 3600:.1f}h ago"
            else:
                age_str = f"{age_s / 86400:.1f}d ago"
            snippet = last_text if len(last_text) <= 300 else last_text[:297] + "..."
            embed.add_field(name=f"↩️ Last bot msg ({age_str})", value=snippet, inline=False)

        if message.author.avatar:
            embed.set_thumbnail(url=message.author.avatar.url)

        await channel.send(embed=embed)
    except Exception as e:
        logger.error(f"Error logging received DM: {e}")

async def log_sent_dm(bot_instance, user, content):
    """Public function for manual logging"""
    await _log_sent_dm_internal(user, content)

# ==================== COG LOADING ====================

def find_cog_files():
    """Scan directories and find all Python files (excluding __init__.py and __pycache__)"""
    print("\n[MAG] Scanning for cog files...")
    base_dir = Path(__file__).parent
    print(f"   Base directory: {base_dir.absolute()}")
    
    extensions = []
    
    # Scan commands directory
    commands_dir = base_dir / 'commands'
    print(f"\n   [FOLDER] Scanning: {commands_dir}")
    if commands_dir.exists() and commands_dir.is_dir():
        print(f"      [OK] Directory exists")
        py_files = [f for f in commands_dir.glob('*.py') if not f.name.startswith('_')]
        for py_file in py_files:
            module = f'commands.{py_file.stem}'
            extensions.append(module)
            print(f"         [OK] {module}")
        if not py_files:
            print(f"         [WARN] No .py files found")
    else:
        print(f"      [ERROR] Not found")
    
    # Scan tasks directory
    tasks_dir = base_dir / 'tasks'
    print(f"\n   [FOLDER] Scanning: {tasks_dir}")
    if tasks_dir.exists() and tasks_dir.is_dir():
        print(f"      [OK] Directory exists")
        py_files = [f for f in tasks_dir.glob('*.py') if not f.name.startswith('_')]
        for py_file in py_files:
            module = f'tasks.{py_file.stem}'
            extensions.append(module)
            print(f"         [OK] {module}")
        if not py_files:
            print(f"         [WARN] No .py files found")
    else:
        print(f"      [ERROR] Not found")
    
    print(f"\n   [CHART] Total extensions found: {len(extensions)}")
    return extensions

async def load_extensions():
    """Load all command extensions/cogs"""
    print("\n[PACKAGE] Loading extensions...")
    
    extensions = find_cog_files()
    
    if not extensions:
        logger.warning("[WARN] No cog files found!")
        print("[WARN] WARNING: No cog files found to load!")
        return
    
    loaded = []
    failed = []
    
    for extension in extensions:
        try:
            print(f"\n   [HOURGLASS] Loading {extension}...")
            await bot.load_extension(extension)
            loaded.append(extension)
            print(f"   [OK] {extension} loaded successfully")
        except commands.ExtensionNotFound:
            failed.append(f"{extension} (not found)")
            print(f"   [ERROR] {extension} - Extension not found")
        except commands.NoEntryPointError:
            failed.append(f"{extension} (no setup)")
            print(f"   [ERROR] {extension} - No setup() function")
        except Exception as e:
            logger.error(f"[ERROR] Failed to load {extension}: {e}")
            failed.append(f"{extension} ({type(e).__name__})")
            print(f"   [ERROR] {extension} - Error: {type(e).__name__}: {e}")
            traceback.print_exc()
    
    # Summary
    print(f"\n[CHART] Extension Loading Summary:")
    print(f"   [OK] Loaded: {len(loaded)}/{len(extensions)}")
    if failed:
        print(f"   [ERROR] Failed: {len(failed)}")
    
    logger.info(f"[PACKAGE] Loaded {len(loaded)}/{len(extensions)} extensions" + (f" ({len(failed)} failed)" if failed else ""))
    
    if failed:
        print("\n[ERROR] Failed Extensions:")
        for ext in failed:
            print(f"   • {ext}")
            logger.warning(f"  • {ext}")

@bot.event
async def on_ready():
    """Called when bot is ready"""
    print("\n" + "="*60)
    print("[OK] BOT READY EVENT TRIGGERED")
    print("="*60)

    # Validate critical data integrity on startup
    print("[CHECK] Validating critical data integrity...")
    await database.validate_critical_data_integrity()
    print("[OK] Data integrity validation complete")
    logger.info("[HEALTH] Data integrity validation passed")

    # Sync app_commands (slash commands) with Discord
    print("\n[SLASH] Syncing slash commands with Discord...")
    try:
        synced = await bot.tree.sync()
        print(f"[OK] Synced {len(synced)} slash commands")
        logger.info(f"[OK] Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"[ERROR] Failed to sync slash commands: {e}")
        print(f"[ERROR] Failed to sync slash commands: {e}")
        traceback.print_exc()

    print(f"[BOT] Bot User: {bot.user}")
    print(f"[ID] Bot ID: {bot.user.id}")
    print(f"[HOME] Guilds: {len(bot.guilds)}")
    print(f"[NOTE] Commands: {len([c for c in bot.commands])}")

    for i, guild in enumerate(bot.guilds, 1):
        print(f"   {i}. {guild.name} (ID: {guild.id}, Members: {guild.member_count})")

    print("="*60)
    
    logger.info(f"[OK] {bot.user} ready | {len(bot.guilds)} guilds | {len([c for c in bot.commands])} commands")
    logger.info("\n" + "="*100)
    logger.info("[OK] BOT STARTUP COMPLETE - Now fully operational")
    logger.info("[HEALTH] All systems pass health check. Bot is fully operational.")
    logger.info("="*100 + "\n")
    
    if bot.launch_time is None:
        bot.launch_time = datetime.now()
        print(f"[CLOCK] Launch time recorded: {bot.launch_time}")
    
    # ── VBucks leaderboards: post or edit on startup ──────────────────────────
    print("\n[VBUCKS] Updating VBucks leaderboards on startup...")
    try:
        await leaderboard_updater.update_all_vbucks_leaderboards(bot, triggered_by="bot_startup")
        print("[OK] VBucks leaderboards startup update complete")
    except Exception as e:
        logger.error(f"[ERROR] VBucks leaderboards startup update failed: {e}")
        print(f"[ERROR] VBucks leaderboards startup update failed: {e}")
        traceback.print_exc()

    # ── Duty info embeds (role + req): static info, post/edit on startup ─────
    print("\n[DUTY-INFO] Posting duty info embeds...")
    try:
        from tasks.unified_weekly_loop import post_duty_info_embeds
        await post_duty_info_embeds(bot)
        print("[OK] Duty info embeds startup post complete")
    except Exception as e:
        logger.error(f"[ERROR] Duty info embeds startup post failed: {e}")
        print(f"[ERROR] Duty info embeds startup post failed: {e}")
        traceback.print_exc()

    # ── Start 24h database backup loop ───────────────────────────────────────
    print("\n[DISK] Starting 24h database backup loop...")
    try:
        backup_task = asyncio.create_task(database_backup.schedule_backup_loop())
        bot.backup_task = backup_task
        logger.info("[OK] 24h backup loop started")
        print("[OK] 24h backup loop started successfully")
        print("   - Backups run every 24h, last 7 kept")
        print("   - Stored in: database_backups/")
    except Exception as e:
        logger.error(f"[ERROR] Failed to start backup loop: {e}")
        print(f"[ERROR] Failed to start backup loop: {e}")
        traceback.print_exc()
    # ──────────────────────────────────────────────────────────────────────────

    print("\n[OK] Bot is now fully operational!")
    print("="*60)

# ==================== GLOBAL CHANNEL CHECK ====================

@bot.check
def global_command_check(ctx):
    """Global check - restrict commands to allowed channels only"""
    if ctx.guild is None:
        return True

    try:
        config_path = 'config.json'
        if not os.path.exists(config_path):
            return True

        with open(config_path, 'r') as f:
            config = json.load(f)

        guild_id_str = str(ctx.guild.id)
        guild_configs = config.get('guild_configs', {})

        if guild_id_str not in guild_configs:
            return True

        guild_config = guild_configs[guild_id_str]
        allowed_channels = guild_config.get('allowed_command_channels', [])

        if not allowed_channels:
            return True

        # Get the channel ID to check
        channel_id = ctx.channel.id

        # If command is in a thread or forum post, check the parent channel instead
        if isinstance(ctx.channel, (discord.Thread, discord.abc.GuildChannel)):
            if hasattr(ctx.channel, 'parent_id') and ctx.channel.parent_id:
                channel_id = ctx.channel.parent_id

        if channel_id in allowed_channels:
            return True
        else:
            return False

    except Exception as e:
        logger.error(f"Error in channel check: {e}")
        return True

# ==================== EVENT HANDLERS ====================

@bot.event
async def on_command(ctx):
    """Log command usage"""
    logger.info(f">{ctx.command} | {ctx.author} | {ctx.guild.name if ctx.guild else 'DM'}")

@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    
    if isinstance(error, commands.CheckFailure):
        return
    
    if isinstance(error, commands.CommandNotFound):
        # Respect allowed_command_channels — global check doesn't run for unknown commands
        if not global_command_check(ctx):
            return

        try:
            command_name = ctx.message.content.split()[0][1:]
        except (IndexError, AttributeError):
            command_name = "unknown"

        # Build a pool of every command name + alias for fuzzy matching
        known = []
        for cmd in bot.commands:
            known.append(cmd.name)
            known.extend(cmd.aliases)
        suggestions = difflib.get_close_matches(command_name.lower(), known, n=3, cutoff=0.6)

        embed = discord.Embed(
            title="❌ Command Not Found",
            description=f"The command `>{command_name}` doesn't exist.",
            color=discord.Color.red()
        )

        if suggestions:
            embed.add_field(
                name="🤔 Did you mean?",
                value="\n".join(f"• `>{s}`" for s in suggestions),
                inline=False
            )

        embed.add_field(
            name="💡 Need Help?",
            value="Use `>help` to see all available commands.",
            inline=False
        )
        embed.set_footer(text=f"Requested by {ctx.author}")

        await ctx.send(embed=embed)
        return
    
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="[ERROR] Missing Permissions",
            description="You don't have permission to use this command.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="Required Permissions",
            value=", ".join(error.missing_permissions),
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    if isinstance(error, commands.MissingAnyRole):
        embed = discord.Embed(
            title="[ERROR] Missing Required Role",
            description="You don't have the required role to use this command.",
            color=discord.Color.red()
        )
        roles = ", ".join([f"`{role}`" for role in error.missing_roles])
        embed.add_field(
            name="Required Roles (any of)",
            value=roles,
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="[ERROR] Missing Argument",
            description=f"Missing required argument: `{error.param.name}`",
            color=discord.Color.red()
        )
        embed.add_field(
            name="[BULB] Help",
            value=f"Use `>help {ctx.command}` for usage info.",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    if isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="[ERROR] Invalid Argument",
            description="Invalid argument provided.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="[BULB] Help",
            value=f"Use `>help {ctx.command}` for usage info.",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    if isinstance(error, commands.CommandOnCooldown):
        embed = discord.Embed(
            title="[HOURGLASS] Command on Cooldown",
            description=f"This command is on cooldown.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Try Again In",
            value=f"{error.retry_after:.1f} seconds",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    logger.error(f"Error in command {ctx.command}: {error}")
    logger.error(traceback.format_exc())
    
    embed = discord.Embed(
        title="[ERROR] Error",
        description="An error occurred while executing this command.",
        color=discord.Color.red()
    )
    embed.add_field(
        name="What to do?",
        value="Please try again or contact an admin if the issue persists.",
        inline=False
    )
    embed.set_footer(text=f"Error: {type(error).__name__}")
    await ctx.send(embed=embed)

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler for events"""
    logger.error(f"Error in event {event}:")
    logger.error(traceback.format_exc())
    print(f"\n[ERROR] ERROR in event {event}:")
    traceback.print_exc()

async def shutdown():
    """Cleanup function called on bot shutdown"""
    print("\n" + "="*60)
    print("[STOP] SHUTDOWN SEQUENCE INITIATED")
    print("="*60)
    logger.info("Shutting down...")
    
    try:
        # Cancel backup task if it exists
        if hasattr(bot, 'backup_task') and bot.backup_task:
            print("[DISK] Cancelling backup scheduler task...")
            bot.backup_task.cancel()
            try:
                await bot.backup_task
            except asyncio.CancelledError:
                pass
            print("[OK] Backup scheduler cancelled")
    except Exception as e:
        logger.error(f"Error cancelling backup task: {e}")
        print(f"[ERROR] Error cancelling backup task: {e}")
    
    try:
        print("[DISK] Flushing critical data to disk...")
        await database.flush_critical_data()
        print("[OK] Critical data flushed")
    except Exception as e:
        logger.error(f"Error flushing critical data: {e}")
        print(f"[WARNING] Error flushing critical data: {e}")

    try:
        print("[DISK] Closing database connection...")
        await database.close_db()
        print("[OK] Database closed")
    except Exception as e:
        logger.error(f"Error closing database: {e}")
        print(f"[ERROR] Error closing database: {e}")
    
    try:
        print("[BOT] Closing bot connection...")
        await bot.close()
        print("[OK] Bot closed")
    except Exception as e:
        logger.error(f"Error closing bot: {e}")
        print(f"[ERROR] Error closing bot: {e}")
    
    print("="*60)
    print("[OK] SHUTDOWN COMPLETE")
    print("="*60)

async def main():
    """Main entry point"""
    print("\n" + "="*60)
    print("[TARGET] MAIN FUNCTION STARTED")
    print("="*60)
    
    # ✅ FORCE FRESH LOGIN (NOT SESSION RESUME)
    print("\n[LOCK] Forcing fresh login (clearing cached session)...")
    try:
        # Remove cached session to force fresh login
        if hasattr(bot, '_connection') and bot._connection:
            # Clear the session state without breaking _get_websocket
            if hasattr(bot._connection, '_session_id'):
                bot._connection._session_id = None
                logger.info("[OK] Cleared session ID - will do fresh login")
                print("[OK] Session ID cleared - fresh login will be forced")
            else:
                logger.info("[OK] No session ID to clear")
                print("[OK] No session ID to clear")
        else:
            logger.info("[OK] No existing connection to clear")
            print("[OK] No existing connection to clear")
    except Exception as e:
        logger.warning(f"⚠️  Could not clear session ID: {e}")
        print(f"[WARN] Warning: Could not clear session ID: {e}")
    
    if not BOT_TOKEN:
        print("[ERROR] FATAL ERROR: BOT_TOKEN not found in .env file!")
        logger.error("❌ BOT_TOKEN not found in .env file!")
        print("="*60)
        return
    
    try:
        async with bot:
            print("\n[PACKAGE] Loading bot extensions...")

            # ✅ Ensure database file exists before initialization
            print("\n[DISK] Checking database file...")
            db_file = 'bot_database.db'
            if not os.path.exists(db_file):
                print(f"[CREATE] Database file not found, creating: {db_file}")
                # Create empty file by opening and closing a connection
                import aiosqlite
                async with aiosqlite.connect(db_file) as conn:
                    await conn.commit()
                print(f"[OK] Database file created: {db_file}")
            else:
                print(f"[OK] Database file exists: {db_file}")

            # ✅ Initialize database BEFORE loading cogs so they can use it in setup()
            print("\n[DISK] Initializing database...")
            try:
                await database.init_database()
                logger.info("[OK] Database initialized")
                print("[OK] Database initialized successfully")
            except Exception as e:
                logger.error(f"[ERROR] Database init failed: {e}")
                print(f"[ERROR] Database initialization failed: {e}")
                traceback.print_exc()
            
            # ✅ Initialize database backup system
            print("\n[DISK] Initializing database backup system...")
            try:
                await database_backup.initialize_backup_system()
                logger.info("[OK] Database backup system initialized")
                print("[OK] Database backup system initialized successfully")
            except Exception as e:
                logger.error(f"[ERROR] Database backup system init failed: {e}")
                print(f"[ERROR] Database backup system initialization failed: {e}")
                traceback.print_exc()
            
            await load_extensions()
            
            print("\n[ROCKET] STARTING BOT CONNECTION TO DISCORD (FRESH LOGIN)...")
            print("   This may take a few seconds...")
            print("   Waiting for on_ready event...")
            print("   [LOCK] This will be a FRESH login, not a session resume")
            print("-"*60)
            
            logger.info("[ROCKET] Starting bot with FORCED FRESH LOGIN...")
            await bot.start(BOT_TOKEN)
            
    except discord.LoginFailure as e:
        print("\n" + "="*60)
        print("[ERROR] LOGIN FAILURE")
        print("="*60)
        print(f"Error: {e}")
        print("\nSolution: Check your BOT_TOKEN in .env file")
        print("="*60)
        logger.error(f"Login failure: {e}")
        traceback.print_exc()
        
    except discord.PrivilegedIntentsRequired as e:
        print("\n" + "="*60)
        print("[ERROR] PRIVILEGED INTENTS ERROR")
        print("="*60)
        print(f"Error: {e}")
        print("\nSolution: Enable privileged intents in Discord Developer Portal")
        print("="*60)
        logger.error(f"Privileged intents required: {e}")
        traceback.print_exc()
        
    except Exception as e:
        print("\n" + "="*60)
        print("[ERROR] UNEXPECTED ERROR DURING BOT START")
        print("="*60)
        print(f"Error Type: {type(e).__name__}")
        print(f"Error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        print("="*60)
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        
    finally:
        print("\n[REFRESH] Entering shutdown sequence...")
        await shutdown()

if __name__ == "__main__":
    print("\n" + "="*80)
    print(" "*20 + "DISCORD BOT STARTUP")
    print("="*80)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + "="*60)
        print("[WARN] BOT STOPPED BY USER (Ctrl+C)")
        print("="*60)
        logger.info("Bot stopped (Ctrl+C)")
    except Exception as e:
        print("\n" + "="*60)
        print("[ERROR] FATAL ERROR IN MAIN EXECUTION")
        print("="*60)
        print(f"Error Type: {type(e).__name__}")
        print(f"Error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        print("="*60)
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
    
    print("\n" + "="*80)
    print(" "*25 + "SCRIPT ENDED")
    print("="*80)   