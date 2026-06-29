import aiosqlite
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List, Tuple

# Semantic logging into Wave-Logging dashboard (bot_logs SQLite table).
# log_event is async, never raises (errors go to its own diagnostic logger),
# and uses an isolated `wave_log` logger namespace so DiscordTerminalHandler
# never sees it. Safe to call from any DB write function.
from core.global_logger import log_event as _wave_log_event


# Setup logger
logger = logging.getLogger(__name__)

# Helper function to convert Row objects to dicts
def row_to_dict(row):
    """Convert sqlite3.Row to dict, safely"""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        # Try direct dict conversion first (works for aiosqlite.Row)
        return dict(row)
    except (TypeError, ValueError) as e:
        logger.debug(f"Error converting row to dict: {e}")
        # Fallback: use keys() method if available
        if hasattr(row, 'keys'):
            try:
                return dict(zip(row.keys(), row))
            except:
                pass
    return row

# Configuration
DB_FILE = 'bot_database.db'
CACHE_RETENTION_DAYS = 30
VALID_CHECK_TYPES = {'message', 'role', 'req', 'modlog'}
# Single-wallet VBucks model — the legacy req/role/purge wallets were merged into
# `main` (see migrations/consolidate_vbucks_wallets.py). Everything routes to 'main'.
VALID_WALLET_TYPES = {'main'}
# ✅ LOOT ROUTES: Valid leaderboard message types
VALID_LEADERBOARD_TYPES = {'points', 'vbucks_req', 'vbucks_role'}

# ==================== BOT INSTANCE ====================
# Global bot instance for automatic removal
_bot_instance = None

def set_bot_instance(bot):
    """Set the bot instance for automatic strike removal"""
    global _bot_instance
    _bot_instance = bot
    logger.info("✅ Bot instance set for automatic strike removal")

def get_bot_instance():
    """Get the bot instance"""
    return _bot_instance

# ==================== CONNECTION POOL ====================

class DatabasePool:
    """Async SQLite connection pool for better performance"""
    __slots__ = ('db_file', 'pool_size', '_connections', '_semaphore', '_initialized')
    
    def __init__(self, db_file: str, pool_size: int = 5):
        self.db_file = db_file
        self.pool_size = pool_size
        self._connections = []
        self._semaphore = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize connection pool with optimized settings"""
        if self._initialized:
            return
        
        self._semaphore = asyncio.Semaphore(self.pool_size)
        
        for _ in range(self.pool_size):
            conn = await aiosqlite.connect(self.db_file)
            conn.row_factory = aiosqlite.Row
            
            # Performance optimizations
            await conn.execute('PRAGMA journal_mode=WAL')
            await conn.execute('PRAGMA synchronous=NORMAL')
            await conn.execute('PRAGMA cache_size=-64000')  # 64MB cache
            await conn.execute('PRAGMA temp_store=MEMORY')
            # Wait up to 30s for other writers (e.g. tasks/wave_logging.py
            # opens its own connections for bot_logs) instead of failing
            # instantly with "database is locked".
            await conn.execute('PRAGMA busy_timeout=30000')
            await conn.commit()
            
            self._connections.append(conn)
        
        self._initialized = True
    
    @asynccontextmanager
    async def acquire(self):
        """Get a connection from the pool"""
        if not self._initialized:
            await self.initialize()
        
        async with self._semaphore:
            if not self._connections:
                raise RuntimeError("Connection pool is empty")
            
            conn = self._connections.pop()
            try:
                yield conn
            finally:
                self._connections.append(conn)
    
    async def close_all(self):
        """Close all connections"""
        for conn in self._connections:
            await conn.close()
        self._connections.clear()
        self._initialized = False

# Global pool instance
_pool = None

async def get_pool() -> DatabasePool:
    """Get or create the database pool"""
    global _pool
    if _pool is None:
        _pool = DatabasePool(DB_FILE, pool_size=3)
        await _pool.initialize()
    return _pool

async def close_db():
    """Close database connection pool"""
    global _pool
    if _pool:
        await _pool.close_all()
        _pool = None

async def flush_critical_data():
    """
    Flush all critical data to disk before shutdown.
    Ensures session data, points, streaks, and penalties are saved.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Force commit all pending changes
            await db.commit()

            # Perform a checkpoint to ensure WAL is flushed to disk
            await db.execute('PRAGMA optimize')
            await db.commit()

        logger.info("✅ Critical data flushed to disk")
    except Exception as e:
        logger.error(f"❌ Error flushing critical data: {e}")
        raise

async def validate_critical_data_integrity():
    """
    Validate that critical data is intact on startup.
    This ensures the database wasn't corrupted or lost data on shutdown.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Check penalties table
            async with db.execute("SELECT COUNT(*) as count FROM penalties") as cursor:
                row = await cursor.fetchone()
                penalty_count = row['count'] if row else 0
                logger.info(f"✅ Penalties table intact: {penalty_count} penalties recorded")

        logger.info("✅ All critical data integrity checks passed")
        return True

    except Exception as e:
        logger.error(f"❌ Critical data integrity check failed: {e}")
        return False

# ==================== VALIDATION ====================

def validate_check_type(check_type: str):
    """Validate check_type to prevent invalid values"""
    if check_type not in VALID_CHECK_TYPES:
        raise ValueError(f"Invalid check_type: {check_type}. Must be one of {VALID_CHECK_TYPES}")

def validate_wallet_type(wallet_type: str):
    """✅ NEW: Validate wallet_type to prevent invalid values"""
    if wallet_type not in VALID_WALLET_TYPES:
        raise ValueError(f"Invalid wallet_type: {wallet_type}. Must be one of {VALID_WALLET_TYPES}")

def validate_leaderboard_type(leaderboard_type: str):
    """✅ LOOT ROUTES: Validate leaderboard_type"""
    if leaderboard_type not in VALID_LEADERBOARD_TYPES:
        raise ValueError(f"Invalid leaderboard_type: {leaderboard_type}. Must be one of {VALID_LEADERBOARD_TYPES}")

# ==================== INITIALIZATION ====================

async def init_database():
    """Initialize database with optimized schema"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
             
            # User stats table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    check_type TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    data TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    UNIQUE(guild_id, user_id, check_type, start_date, end_date)
                )
            ''')
            
            # Config change logs
            await db.execute('''
                CREATE TABLE IF NOT EXISTS config_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    change_type TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TEXT NOT NULL
                )
            ''')
            
            # (strike_points table removed — strike system was retired)

            # Sent reports tracking table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sent_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    report_type TEXT NOT NULL,
                    period TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE(guild_id, report_type, period, start_date, end_date)
                )
            ''')
            
            # User goals table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_goals (
                    user_id INTEGER NOT NULL,
                    duty_type TEXT NOT NULL,
                    target INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, duty_type)
                )
            ''')
            
            # Legacy activity_streaks table (unused — removed SESSION R24, 2026-06-22; DDL kept for DB compat)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS activity_streaks (
                    user_id INTEGER NOT NULL,
                    duty_type TEXT NOT NULL,
                    current_streak INTEGER DEFAULT 0,
                    last_week_result TEXT,
                    last_updated TEXT NOT NULL,
                    PRIMARY KEY (user_id, duty_type)
                )
            ''')


            # Milestone badge totals table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS milestone_totals (
                    user_id    INTEGER NOT NULL,
                    username   TEXT    NOT NULL,
                    duty_type  TEXT    NOT NULL,
                    total      INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT    NOT NULL,
                    PRIMARY KEY (user_id, duty_type)
                )
            ''')

            # ==================== LIFETIME TOTALS ====================
            # Accumulated weekly from the unified loop (message/modlog/req).
            # Reviews are NOT stored here — they're summed all-time from bot_logs at build time.
            await db.execute('''
                CREATE TABLE IF NOT EXISTS lifetime_totals (
                    user_id         INTEGER NOT NULL,
                    metric          TEXT NOT NULL,
                    total           INTEGER NOT NULL DEFAULT 0,
                    last_added_week TEXT,
                    updated_at      TEXT,
                    PRIMARY KEY (user_id, metric)
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS weekly_roles (
                    user_id INTEGER,
                    week_start TEXT,
                    week_end TEXT,
                    role_type TEXT,
                    current_streak INTEGER DEFAULT 1,
                    best_streak INTEGER DEFAULT 1,
                    total_wins INTEGER DEFAULT 1,
                    PRIMARY KEY (user_id, week_start, role_type)
                )
            ''')

            # Leaderboard message IDs table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS leaderboard_messages (
                    guild_id INTEGER NOT NULL,
                    duty_type TEXT NOT NULL,
                    message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    last_updated TEXT NOT NULL,
                    PRIMARY KEY (guild_id, duty_type)
                )
            ''')

            # Maintenance tracking table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS maintenance_tracking (
                    task_name TEXT PRIMARY KEY,
                    last_run TEXT NOT NULL
                )
            ''')

            # Predictions table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    creator_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    outcomes TEXT NOT NULL,
                    result TEXT
                )
            ''')

            # Prediction votes table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS prediction_votes (
                    prediction_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    choice TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    voted_at TEXT NOT NULL,
                    breakdown TEXT,
                    PRIMARY KEY (prediction_id, user_id),
                    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
                )
            ''')

            # ✅ VBucks reservations table (for locking VBucks without deducting)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vbucks_reservations (
                    user_id INTEGER NOT NULL,
                    wallet_type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    reference_id INTEGER,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, wallet_type, reason, reference_id)
                )
            ''')

            # ✅ LOOT ROUTES TABLES
            # Loot Route leaderboard tracking (routes_completed per maker).
            # NOTE: the spendable currency is Wave Points; this table only powers
            # the loot-route leaderboard. total_points is legacy (kept at 0.0).
            await db.execute('''
                CREATE TABLE IF NOT EXISTS loot_route_points (
                    user_id INTEGER PRIMARY KEY,
                    total_points INTEGER DEFAULT 0,
                    routes_completed INTEGER DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            ''')

            # Route assignments with reminder tracking
            await db.execute('''
                CREATE TABLE IF NOT EXISTS route_assignments (
                    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    notification_message_id INTEGER NOT NULL,
                    confirmation_message_id INTEGER NOT NULL,
                    assigned_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    last_reminder_sent TEXT,
                    reminder_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    map_details TEXT,
                    created_at TEXT NOT NULL
                )
            ''')

            # Hold pool: maps that arrived while every maker was busy/away.
            # Auto-assigned (oldest first) when a maker frees up. Idempotent — safe on every boot.
            await db.execute('''
                CREATE TABLE IF NOT EXISTS loot_pending_maps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    source_message_id INTEGER,
                    map_details TEXT,
                    image_refs TEXT,
                    local_files TEXT,
                    is_lucky_map INTEGER DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
            ''')

            # Rotation state persistence
            await db.execute('''
                CREATE TABLE IF NOT EXISTS rotation_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    rotation_message_id INTEGER,
                    sticky_message_id INTEGER,
                    leaderboard_message_id INTEGER,
                    last_assigned_position INTEGER DEFAULT 0,
                    last_assigned_user_id INTEGER,
                    total_assignments INTEGER DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            ''')

            # Weekly MVP posts tracking table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS weekly_mvp_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    week_number INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    posted_at TEXT NOT NULL,
                    UNIQUE(guild_id, year, week_number)
                )
            ''')

            # Staff insights history table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS staff_insights_history (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER NOT NULL,
                    user_name    TEXT,
                    duty_type    TEXT NOT NULL,
                    week_start   TEXT NOT NULL,
                    week_end     TEXT NOT NULL,
                    count        INTEGER DEFAULT 0,
                    is_midweek   INTEGER DEFAULT 0,
                    recorded_at  TEXT NOT NULL
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_insights_history_user
                ON staff_insights_history (user_id, week_start, duty_type)
            ''')

            # ✅ POSITION FIX: Permanent position assignments
            await db.execute('''
                CREATE TABLE IF NOT EXISTS loot_route_positions (
                    user_id INTEGER PRIMARY KEY,
                    position_number INTEGER NOT NULL UNIQUE,
                    assigned_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                )
            ''')

            # Composite indexes for faster queries
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_composite
                ON user_stats(guild_id, user_id, check_type, start_date, end_date, cached_at)
            ''')
            
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_config_logs_guild 
                ON config_logs(guild_id, changed_at)
            ''')
            
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_sent_reports 
                ON sent_reports(guild_id, report_type, period, start_date, end_date)
            ''')
            
            # ✅ Index for predictions
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_predictions_status 
                ON predictions(status)
            ''')
            
            # ✅ Indexes for VBucks reservations
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_vbucks_reservations_user 
                ON vbucks_reservations(user_id)
            ''')

            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_vbucks_reservations_reference 
                ON vbucks_reservations(reason, reference_id)
            ''')

            # ✅ LOOT ROUTES Indexes
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_assignments_status 
                ON route_assignments(status)
            ''')
            
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_assignments_user 
                ON route_assignments(user_id, status)
            ''')
            
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_assignments_time 
                ON route_assignments(assigned_at)
            ''')
            
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_loot_points_leaderboard
                ON loot_route_points(total_points DESC)
            ''')

            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_loot_positions_number
                ON loot_route_positions(position_number)
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS wave_points (
                    user_id         INTEGER PRIMARY KEY,
                    points          INTEGER DEFAULT 0,
                    last_rank_total INTEGER DEFAULT 0,
                    last_updated    TEXT NOT NULL
                )
            ''')

            # ==================== ROLE ASSIGNMENTS TRACKING ====================

            # Track when users are assigned to duty roles
            await db.execute('''
                CREATE TABLE IF NOT EXISTS role_assignments (
                    user_id         INTEGER NOT NULL,
                    duty_type       TEXT NOT NULL,
                    assigned_at     TEXT NOT NULL,
                    PRIMARY KEY (user_id, duty_type)
                )
            ''')

            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_role_assignments_user_duty
                ON role_assignments(user_id, duty_type)
            ''')

            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_role_assignments_timestamp
                ON role_assignments(assigned_at)
            ''')

            # ==================== CENTRAL BANK TABLES ====================

            # Single-row central bank reserves + settings
            await db.execute('''
                CREATE TABLE IF NOT EXISTS central_bank (
                    id           INTEGER PRIMARY KEY CHECK (id = 1),
                    reserves_vbucks   INTEGER DEFAULT 0,
                    reserves_points   INTEGER DEFAULT 0,
                    reserves_lrp      INTEGER DEFAULT 0,
                    fee_rate_pct  REAL    DEFAULT 5.0,
                    ptv_tax_pct   REAL    DEFAULT 50.0,
                    last_updated  TEXT    NOT NULL
                )
            ''')
            # Migrations for columns added after initial schema
            try:
                async with db.execute("PRAGMA table_info(central_bank)") as _cur:
                    _cols = {row[1] for row in await _cur.fetchall()}
                if "reserves_lrp" not in _cols:
                    await db.execute("ALTER TABLE central_bank ADD COLUMN reserves_lrp INTEGER DEFAULT 0")
                    await db.commit()
                    logger.info("✅ Migration: added reserves_lrp column to central_bank")
                if "reserves_srp" not in _cols:
                    await db.execute("ALTER TABLE central_bank ADD COLUMN reserves_srp INTEGER DEFAULT 0")
                    await db.commit()
                    logger.info("✅ Migration: added reserves_srp column to central_bank")
                if "ptv_tax_pct" not in _cols:
                    await db.execute("ALTER TABLE central_bank ADD COLUMN ptv_tax_pct REAL DEFAULT 50.0")
                    await db.commit()
                    logger.info("✅ Migration: added ptv_tax_pct column to central_bank")
            except Exception as _e:
                logger.error(f"❌ CRITICAL: Could not run central_bank column migration: {_e}")
                raise

            # Fee transaction log
            await db.execute('''
                CREATE TABLE IF NOT EXISTS transaction_fees (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       INTEGER NOT NULL,
                    fee_type      TEXT    NOT NULL,
                    amount_before INTEGER NOT NULL,
                    fee_collected INTEGER NOT NULL,
                    amount_after  INTEGER NOT NULL,
                    collected_at  TEXT    NOT NULL
                )
            ''')

            # Dynamic Stock Market for WP_VB (Tier System)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS exchange_market (
                    market_pair    TEXT PRIMARY KEY,
                    current_tier   INTEGER NOT NULL DEFAULT 3,
                    total_bought   INTEGER DEFAULT 0,
                    total_sold     INTEGER DEFAULT 0,
                    last_updated   TEXT NOT NULL
                )
            ''')

            # Check if previous_tier column exists, add if not
            async with db.execute("PRAGMA table_info(exchange_market)") as _cur:
                columns = {row[1] for row in await _cur.fetchall()}
                if 'previous_tier' not in columns:
                    try:
                        await db.execute("ALTER TABLE exchange_market ADD COLUMN previous_tier INTEGER DEFAULT 3")
                        logger.info("✅ Migration: added previous_tier column to exchange_market")
                    except Exception as _e:
                        logger.error(f"❌ CRITICAL: Could not add previous_tier to exchange_market: {_e}")

            # Daily snapshots for 24h/7d/30d % change calculations
            await db.execute('''
                CREATE TABLE IF NOT EXISTS market_rate_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_pair TEXT    NOT NULL,
                    tier        INTEGER NOT NULL,
                    ratio       REAL    NOT NULL,
                    recorded_at TEXT    NOT NULL
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_market_rate_history_pair_time
                ON market_rate_history (market_pair, recorded_at)
            ''')

            # Pre-seed exchange market if empty (Tier 3 is Baseline)
            await db.execute('''
                INSERT OR IGNORE INTO exchange_market (market_pair, current_tier, previous_tier, last_updated)
                VALUES ('WP_VB', 3, 3, ?)
            ''', (datetime.now(timezone.utc).isoformat(),))

            # Bank Bonds (Inflation Control)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS bank_bonds (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id        INTEGER NOT NULL,
                    amount_locked  INTEGER NOT NULL,
                    amount_payout  INTEGER NOT NULL,
                    bought_at      TEXT NOT NULL,
                    maturity_date  TEXT NOT NULL,
                    status         TEXT DEFAULT 'active'
                )
            ''')

            # The Central Bank Lottery Tickets
            await db.execute('''
                CREATE TABLE IF NOT EXISTS lottery_tickets (
                    ticket_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id        INTEGER NOT NULL,
                    bought_at      TEXT NOT NULL,
                    draw_date      TEXT NOT NULL
                )
            ''')

            # Lottery History Log
            await db.execute('''
                CREATE TABLE IF NOT EXISTS lottery_draws (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    draw_date      TEXT NOT NULL,
                    total_pot      INTEGER NOT NULL,
                    winner_id      INTEGER,
                    drawn_at       TEXT NOT NULL
                )
            ''')

            await db.execute('''
                CREATE TABLE IF NOT EXISTS wave_points_interest (
                    user_id          INTEGER PRIMARY KEY,
                    accrued_fraction REAL    DEFAULT 0.0,
                    last_paid_at     TEXT    NOT NULL,
                    total_earned     INTEGER DEFAULT 0
                )
            ''')

            # Away return dates — persists scheduled return dates across restarts
            await db.execute('''
                CREATE TABLE IF NOT EXISTS loot_route_away_dates (
                    user_id     INTEGER PRIMARY KEY,
                    return_date TEXT,
                    set_at      TEXT    NOT NULL
                )
            ''')

            # Staff away table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS staff_away_dates (
                    user_id     INTEGER PRIMARY KEY,
                    return_date TEXT,
                    set_at      TEXT    NOT NULL
                )
            ''')

            # Alumni / history table — stores data for makers who left the team
            await db.execute('''
                CREATE TABLE IF NOT EXISTS loot_route_alumni (
                    user_id          INTEGER PRIMARY KEY,
                    display_name     TEXT,
                    total_points     REAL    DEFAULT 0,
                    routes_completed INTEGER DEFAULT 0,
                    rotation_number  INTEGER,
                    joined_at        TEXT,
                    left_at          TEXT    NOT NULL,
                    archived_at      TEXT    NOT NULL
                )
            ''')

            # Thread response time tracking (for response time brackets)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS thread_responses (
                    thread_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    thread_created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    first_responder_id INTEGER,
                    first_response_at TIMESTAMP,
                    response_time_seconds INTEGER,
                    points_bracket TEXT
                )
            ''')

            # Analyze for query optimization
            await db.execute('ANALYZE')
            await db.commit()

            # Initialize individual tables
            await init_cache_table()
            await init_vbucks_table()
            await init_sent_reports_table()
            await init_loot_routes_tables()
            await init_wave_points_table()
            await init_web_exchanges_table()
            await init_web_bonds_table()

            # ✅ RUN MIGRATION TO ADD BREAKDOWN COLUMN
            await migrate_prediction_votes_add_breakdown()
            
            # ✅ RUN MIGRATION FOR ROUTE ASSIGNMENT COMPLETION COLUMNS
            await migrate_route_assignments_add_completion_columns()
            await migrate_route_assignments_add_lucky_map()
            await migrate_route_assignments_add_local_files()

            # ✅ MIGRATION: add left_at for wave points alumni tracking
            await migrate_wave_points_add_left_at()

            # ✅ ONE-TIME CLEANUP: clamp any pre-existing negative loot route totals to 0
            await migrate_clamp_negative_loot_route_points()

            # ✅ SURGE ROUTES: create all surge tables + clamp negatives. Lazily imported to
            # avoid a circular import (database_surge imports get_pool from this module).
            # Called AFTER the loot commit above, in its own try/except, so a surge DDL
            # error can never abort loot/reviewer table creation.
            try:
                import database_surge
                await database_surge.init_surge_routes_tables()
                await database_surge.migrate_clamp_negative_surge_route_points()
            except Exception as _surge_e:
                logger.error(f"❌ [SURGE ROUTES] init failed (loot tables unaffected): {_surge_e}")

            # ✅ TIPS & TRICKS: separate tables, never touches loot/surge.
            try:
                import database_tipsandtricks
                await database_tipsandtricks.init_tipsandtricks_tables()
            except Exception as _tt_e:
                logger.error(f"❌ [T&T] init failed (other tables unaffected): {_tt_e}")

            # Web shop redemption queue — Flask inserts, bot processor fulfils
            await db.execute('''
                CREATE TABLE IF NOT EXISTS web_redemptions (
                    id           TEXT PRIMARY KEY,
                    user_id      TEXT NOT NULL,
                    prize        TEXT NOT NULL,
                    cost         INTEGER NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    result_json  TEXT,
                    created_at   TEXT NOT NULL,
                    processed_at TEXT
                )
            ''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_web_redemptions_status ON web_redemptions(status)')
            await db.commit()

            logger.info("✅ All database tables initialized (including loot routes, surge routes, tips & tricks)")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

async def init_cache_table():
    """Initialize cache tables (already created in init_database)"""
    logger.info("✅ Cache tables initialized")

async def init_vbucks_table():
    logger.info("✅ VBucks table initialized")

async def init_sent_reports_table():
    logger.info("✅ Sent reports table initialized")

async def init_loot_routes_tables():
    logger.info("✅ Loot routes tables initialized")


async def get_role_assignment_date(user_id: int, duty_type: str):
    """Return the assigned_at timestamp for a user's duty role, or None if not recorded."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT assigned_at FROM role_assignments WHERE user_id = ? AND duty_type = ?",
            (user_id, duty_type)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def log_role_assignment(user_id: int, duty_type: str):
    """Record when a user was first seen with a duty role (INSERT OR IGNORE — doesn't overwrite)."""
    from datetime import datetime, timezone
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "INSERT OR IGNORE INTO role_assignments (user_id, duty_type, assigned_at) VALUES (?, ?, ?)",
            (user_id, duty_type, datetime.now(timezone.utc).isoformat())
        )
        await db.commit()


async def _ensure_profile_customization_table(db):
    await db.execute(
        """CREATE TABLE IF NOT EXISTS profile_card_customization (
            user_id TEXT PRIMARY KEY,
            settings_json TEXT NOT NULL,
            updated_at TEXT
        )"""
    )


async def get_profile_customization(user_id) -> str:
    """Return the owner's saved profile-card customization as a JSON string (or '{}')."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await _ensure_profile_customization_table(db)
        async with db.execute(
            "SELECT settings_json FROM profile_card_customization WHERE user_id = ?",
            (str(user_id),)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else '{}'


async def set_profile_customization(user_id, settings_json: str):
    """Upsert a profile owner's card customization. Caller MUST have verified ownership."""
    from datetime import datetime, timezone
    pool = await get_pool()
    async with pool.acquire() as db:
        await _ensure_profile_customization_table(db)
        await db.execute(
            """INSERT INTO profile_card_customization (user_id, settings_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 settings_json = excluded.settings_json,
                 updated_at    = excluded.updated_at""",
            (str(user_id), settings_json, datetime.now(timezone.utc).isoformat())
        )
        await db.commit()


async def migrate_wave_points_add_left_at():
    """Add left_at column to wave_points for alumni tracking (NULL = active)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('ALTER TABLE wave_points ADD COLUMN left_at TEXT')
            await db.commit()
            logger.info("✅ [WAVE POINTS] Added left_at column to wave_points (alumni tracking)")
    except Exception as e:
        if 'duplicate column' in str(e).lower() or 'already exists' in str(e).lower():
            pass  # already migrated
        else:
            logger.error(f"❌ [WAVE POINTS] Error adding left_at column: {e}")


async def get_user_goals(user_id: int) -> dict:
    """Return {duty_type: target} for a user."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT duty_type, target FROM user_goals WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.error(f"❌ Error getting user goals: {e}")
        return {}

async def set_user_goal(user_id: int, duty_type: str, target: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                '''INSERT OR REPLACE INTO user_goals (user_id, duty_type, target, created_at)
                   VALUES (?, ?, ?, ?)''',
                (user_id, duty_type, target, now)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error setting user goal: {e}")

async def delete_user_goal(user_id: int, duty_type: str):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'DELETE FROM user_goals WHERE user_id = ? AND duty_type = ?',
                (user_id, duty_type)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error deleting user goal: {e}")


async def clear_user_goals_global():
    """Clear ALL user goals"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM user_goals')
            cursor = await db.execute('SELECT changes()')
            deleted = (await cursor.fetchone())[0]
            await db.commit()
            logger.info(f"✅ Cleared {deleted} user goal records (global)")
            return deleted
    except Exception as e:
        logger.error(f"❌ Error clearing user goals: {e}")
        return 0

# ==================== WEEKLY ROLES FUNCTIONS ====================

async def record_weekly_role_award(pool, user_id: int, week_start: str, week_end: str, role_type: str):
    """Record a weekly role award"""
    async with pool.acquire() as db:
        await db.execute('''
            INSERT OR IGNORE INTO weekly_roles 
            (user_id, week_start, week_end, role_type, current_streak, best_streak, total_wins)
            VALUES (?, ?, ?, ?, 1, 1, 1)
        ''', (user_id, week_start, week_end, role_type))
        await db.commit()

async def get_last_week_role_winners(week_start: str, week_end: str, role_type: str):
    """Get users who won a specific role last week"""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute('''
            SELECT user_id FROM weekly_roles
            WHERE week_start = ? AND week_end = ? AND role_type = ?
        ''', (week_start, week_end, role_type)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_top_messenger_streak(pool, user_id: int):
    """Get top messenger streak info for a user"""
    async with pool.acquire() as db:
        cursor = await db.execute('''
            SELECT current_streak, best_streak, total_wins
            FROM weekly_roles
            WHERE user_id = ? AND role_type = 'top_messenger'
            ORDER BY week_start DESC
            LIMIT 1
        ''', (user_id,))
        
        result = await cursor.fetchone()
        if result:
            return {
                'current_streak': result[0],
                'best_streak': result[1],
                'total_wins': result[2]
            }
        return {'current_streak': 0, 'best_streak': 0, 'total_wins': 0}

async def update_top_messenger_streak(user_id: int, week_start: str, week_end: str):
    """
    Record a Top Messenger win and update the user's streak + best streak + total wins.
    Safe to call even if this is the user's first win ever.
    Returns dict with current_streak, best_streak, total_wins.
    """
    def to_iso(date_str: str) -> str:
        """Convert dd/mm/yyyy or yyyy-mm-dd to yyyy-mm-dd for correct SQLite string ordering."""
        if '/' in date_str:
            dt = datetime.strptime(date_str, '%d/%m/%Y')
            return dt.strftime('%Y-%m-%d')
        return date_str  # already ISO

    # ✅ FIXED: Always store week_start/week_end as ISO (yyyy-mm-dd) so that
    # ORDER BY week_start DESC works correctly as a string sort in SQLite.
    # The old dd/mm/yyyy format broke at month boundaries — e.g. '28/02' sorted
    # AFTER '07/03' because '2' > '0', causing the wrong row to be returned as
    # "most recent" and incorrectly resetting the streak.
    week_start_iso = to_iso(week_start)
    week_end_iso   = to_iso(week_end)

    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Get the most recent win — ORDER BY week_start DESC is now correct
            # because dates are stored as ISO strings (yyyy-mm-dd).
            async with db.execute('''
                SELECT current_streak, best_streak, total_wins, week_start
                FROM weekly_roles
                WHERE user_id = ? AND role_type = 'top_messenger'
                ORDER BY week_start DESC
                LIMIT 1
            ''', (user_id,)) as cursor:
                row = await cursor.fetchone()

            if row:
                total_wins = row[2] + 1
                last_week_start_str = row[3]

                is_consecutive = False
                try:
                    fmt = '%d/%m/%Y' if '/' in last_week_start_str else '%Y-%m-%d'
                    last_week_start = datetime.strptime(last_week_start_str, fmt).replace(tzinfo=timezone.utc)
                    this_week_start_dt = datetime.strptime(week_start_iso, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    is_consecutive = (this_week_start_dt - last_week_start).days == 7
                except Exception:
                    is_consecutive = False

                if is_consecutive:
                    current_streak = row[0] + 1
                else:
                    current_streak = 1  # streak broken — start fresh

                best_streak = max(row[1], current_streak)
            else:
                current_streak = 1
                best_streak    = 1
                total_wins     = 1

            await db.execute('''
                INSERT INTO weekly_roles
                    (user_id, week_start, week_end, role_type, current_streak, best_streak, total_wins)
                VALUES (?, ?, ?, 'top_messenger', ?, ?, ?)
            ''', (user_id, week_start_iso, week_end_iso, current_streak, best_streak, total_wins))
            await db.commit()

            logger.info(
                f"✅ Top Messenger streak updated for {user_id}: "
                f"streak={current_streak}, best={best_streak}, total={total_wins}"
            )
            return {
                'current_streak': current_streak,
                'best_streak':    best_streak,
                'total_wins':     total_wins,
            }
    except Exception as e:
        logger.error(f"❌ Failed to update top_messenger streak for {user_id}: {e}")
        return {'current_streak': 0, 'best_streak': 0, 'total_wins': 0}


async def get_leaderboard_message_id(guild_id: int, duty_type: str):
    """Get stored leaderboard message ID"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT message_id, channel_id FROM leaderboard_messages WHERE guild_id = ? AND duty_type = ?',
                (guild_id, duty_type)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0], row[1]
                return None
    except Exception as e:
        logger.error(f"❌ Error getting leaderboard message ID: {e}")
        return None

async def save_leaderboard_message_id(guild_id: int, duty_type: str, message_id: int, channel_id: int):
    """Save leaderboard message ID"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute('''
                INSERT INTO leaderboard_messages (guild_id, duty_type, message_id, channel_id, last_updated)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, duty_type) DO UPDATE SET
                    message_id = ?,
                    channel_id = ?,
                    last_updated = ?
            ''', (guild_id, duty_type, message_id, channel_id, now, 
                  message_id, channel_id, now))
            await db.commit()
            logger.info(f"✅ Saved leaderboard message ID for guild {guild_id}, duty {duty_type}")
    except Exception as e:
        logger.error(f"❌ Error saving leaderboard message ID: {e}")

async def delete_leaderboard_message_id(guild_id: int, duty_type: str):
    """Delete stored leaderboard message ID"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'DELETE FROM leaderboard_messages WHERE guild_id = ? AND duty_type = ?',
                (guild_id, duty_type)
            )
            await db.commit()
            logger.info(f"✅ Deleted leaderboard message ID for guild {guild_id}, duty {duty_type}")
    except Exception as e:
        logger.error(f"❌ Error deleting leaderboard message ID: {e}")

async def clear_leaderboard_messages_global():
    """Clear ALL leaderboard message IDs"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM leaderboard_messages')
            cursor = await db.execute('SELECT changes()')
            deleted = (await cursor.fetchone())[0]
            await db.commit()
            logger.info(f"✅ Cleared {deleted} leaderboard message records (global)")
            return deleted
    except Exception as e:
        logger.error(f"❌ Error clearing leaderboard messages: {e}")
        return 0

# ==================== MAINTENANCE TRACKING ====================

async def get_maintenance_last_run(task_name: str) -> Optional[str]:
    """Get last run time for a maintenance task"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT last_run FROM maintenance_tracking WHERE task_name = ?',
                (task_name,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ Error getting maintenance last run: {e}")
        return None

async def set_maintenance_last_run(task_name: str, timestamp: str):
    """Set last run time for a maintenance task"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('''
                INSERT INTO maintenance_tracking (task_name, last_run)
                VALUES (?, ?)
                ON CONFLICT(task_name) DO UPDATE SET last_run = ?
            ''', (task_name, timestamp, timestamp))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error setting maintenance last run: {e}")

async def vacuum_database():
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('VACUUM')
            logger.info("✅ Database vacuumed successfully")
    except Exception as e:
        logger.error(f"❌ Error vacuuming database: {e}")

async def check_report_already_sent(guild_id: int, report_type: str, period: str, start_date: str, end_date: str) -> bool:
    """Check if a report has already been sent for this guild/type/period/date range."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                '''SELECT 1 FROM sent_reports
                   WHERE guild_id = ? AND report_type = ? AND period = ?
                     AND start_date = ? AND end_date = ?
                   LIMIT 1''',
                (guild_id, report_type, period, start_date, end_date)
            ) as cursor:
                return await cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ Error checking sent report: {e}")
        return False

async def mark_report_sent(guild_id: int, report_type: str, period: str, start_date: str, end_date: str):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                '''INSERT OR IGNORE INTO sent_reports
                   (guild_id, report_type, period, start_date, end_date, sent_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (guild_id, report_type, period, start_date, end_date, now)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error marking report sent: {e}")

async def clear_sent_reports_global() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cursor = await db.execute('DELETE FROM sent_reports')
            deleted = cursor.rowcount
            await db.commit()
            logger.info(f"✅ Cleared {deleted} sent report records")
            return deleted
    except Exception as e:
        logger.error(f"❌ Error clearing sent reports: {e}")
        return 0

async def get_cached_user_stats(guild_id: int, user_id: int, check_type: str, start_date: str, end_date: str):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                '''SELECT data FROM user_stats
                   WHERE guild_id=? AND user_id=? AND check_type=?
                     AND start_date=? AND end_date=?''',
                (guild_id, user_id, check_type, start_date, end_date)
            ) as cursor:
                row = await cursor.fetchone()
                return json.loads(row[0]) if row else None
    except Exception as e:
        logger.error(f"❌ Error getting cached user stats: {e}")
        return None


async def get_cached_week_stats(start_date: str, end_date: str) -> dict:
    """All cached duty counts for a week, merged across guilds (highest count wins)."""
    merged: dict = {}
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                '''SELECT user_id, check_type, data FROM user_stats
                   WHERE start_date=? AND end_date=?''',
                (start_date, end_date),
            ) as cursor:
                rows = await cursor.fetchall()
        for user_id, check_type, data_json in rows:
            try:
                data = json.loads(data_json)
            except (TypeError, json.JSONDecodeError):
                continue
            bucket = merged.setdefault(check_type, {})
            uid = str(user_id)
            prev = bucket.get(uid)
            if prev is None:
                bucket[uid] = data
                continue
            prev_c = prev.get('count', 0) if isinstance(prev, dict) else int(prev or 0)
            new_c = data.get('count', 0) if isinstance(data, dict) else int(data or 0)
            if new_c >= prev_c:
                bucket[uid] = data
    except Exception as e:
        logger.error(f"❌ Error loading cached week stats: {e}")
    return merged

async def set_cached_user_stats(guild_id: int, user_id: int, check_type: str,
                                start_date: str, end_date: str, data, cache_time: str = None):
    try:
        if cache_time is None:
            cache_time = datetime.now(timezone.utc).isoformat()
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                '''INSERT OR REPLACE INTO user_stats
                   (guild_id, user_id, check_type, start_date, end_date, data, cached_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (guild_id, user_id, check_type, start_date, end_date, json.dumps(data), cache_time)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error caching user stats: {e}")

async def clear_user_stats_global() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cursor = await db.execute('DELETE FROM user_stats')
            deleted = cursor.rowcount
            await db.commit()
            logger.info(f"✅ Cleared {deleted} user stat records")
            return deleted
    except Exception as e:
        logger.error(f"❌ Error clearing user stats: {e}")
        return 0

# ==================== PREDICTIONS DATABASE FUNCTIONS ====================

async def create_prediction_db(user_id: int, title: str, description: str, end_date: str, outcomes: list) -> int:
    """Create a new prediction in database"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Get next ID
            async with db.execute('SELECT MAX(id) FROM predictions') as cursor:
                row = await cursor.fetchone()
                next_id = (row[0] + 1) if row and row[0] else 1
            
            now = datetime.now(timezone.utc).isoformat()
            
            await db.execute('''
                INSERT INTO predictions (id, title, description, end_date, creator_id, created_at, status, outcomes, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                next_id,
                title,
                description,
                end_date,
                user_id,
                now,
                'active',
                ','.join(outcomes),
                None
            ))
            
            await db.commit()
            logger.info(f"✅ Created prediction #{next_id}: {title}")
        # Wave-Logging dashboard event
        await _wave_log_event(
            category="goals_phour_predictions",
            action="prediction_created",
            actor={"id": str(user_id)},
            details={
                "prediction_id": next_id,
                "title": title,
                "description": description,
                "end_date": end_date,
                "outcomes": outcomes,
            },
        )
        return next_id
    except Exception as e:
        logger.error(f"❌ Error creating prediction: {e}")
        raise

async def get_prediction_db(prediction_id: int) -> dict:
    """Get prediction from database"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT id, title, description, end_date, creator_id, created_at, status, outcomes, result
                FROM predictions WHERE id = ?
            ''', (prediction_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'title': row[1],
                        'description': row[2],
                        'end_date': row[3],
                        'creator_id': row[4],
                        'created_at': row[5],
                        'status': row[6],
                        'outcomes': row[7].split(','),
                        'result': row[8]
                    }
                return None
    except Exception as e:
        logger.error(f"❌ Error getting prediction: {e}")
        return None

async def get_active_predictions_db() -> list:
    """Get all active predictions"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT id, title, description, end_date, creator_id, created_at, status, outcomes, result
                FROM predictions WHERE status = 'active'
            ''') as cursor:
                rows = await cursor.fetchall()
                return [{
                    'id': row[0],
                    'title': row[1],
                    'description': row[2],
                    'end_date': row[3],
                    'creator_id': row[4],
                    'created_at': row[5],
                    'status': row[6],
                    'outcomes': row[7].split(','),
                    'result': row[8]
                } for row in rows]
    except Exception as e:
        logger.error(f"❌ Error getting active predictions: {e}")
        return []

async def get_recent_predictions_db(limit: int = 30) -> list:
    """Active predictions first, then most-recently settled — for the website
    Events tab (so just-resolved predictions linger briefly before dropping off)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT id, title, description, end_date, creator_id, created_at, status, outcomes, result
                FROM predictions
                ORDER BY (status = 'active') DESC, id DESC
                LIMIT ?
            ''', (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [{
                    'id': row[0], 'title': row[1], 'description': row[2],
                    'end_date': row[3], 'creator_id': row[4], 'created_at': row[5],
                    'status': row[6], 'outcomes': row[7].split(','), 'result': row[8]
                } for row in rows]
    except Exception as e:
        logger.error(f"❌ Error getting recent predictions: {e}")
        return []

async def place_vote_db(prediction_id: int, user_id: int, choice: str, amount: int, breakdown: dict = None):
    """✅ FIXED: Place or update vote in database with wallet breakdown"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            voted_at = datetime.now(timezone.utc).isoformat()
            
            # ✅ FIXED: Convert breakdown to JSON string
            breakdown_json = json.dumps(breakdown) if breakdown else json.dumps({'main': amount})
            
            await db.execute('''
                INSERT INTO prediction_votes (prediction_id, user_id, choice, amount, voted_at, breakdown)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(prediction_id, user_id) DO UPDATE SET
                    choice = ?,
                    amount = ?,
                    voted_at = ?,
                    breakdown = ?
            ''', (prediction_id, user_id, choice, amount, voted_at, breakdown_json,
                  choice, amount, voted_at, breakdown_json))
            await db.commit()
            logger.info(f"✅ User {user_id} voted {choice} with {amount} VBucks on prediction #{prediction_id}")
        # Wave-Logging dashboard event
        await _wave_log_event(
            category="goals_phour_predictions",
            action="prediction_vote_placed",
            actor={"id": str(user_id)},
            details={
                "prediction_id": prediction_id,
                "choice": choice,
                "amount": amount,
                "breakdown": breakdown,
            },
        )
    except Exception as e:
        logger.error(f"❌ Error placing vote: {e}")
        raise

async def get_votes_db(prediction_id: int) -> dict:
    """Get all votes for a prediction with wallet breakdown"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT user_id, choice, amount, voted_at, breakdown
                FROM prediction_votes WHERE prediction_id = ?
            ''', (prediction_id,)) as cursor:
                rows = await cursor.fetchall()
                result = {}
                for row in rows:
                    breakdown = None
                    if row[4]:  # If breakdown exists
                        try:
                            breakdown = json.loads(row[4])
                        except:
                            breakdown = {'main': row[2]}  # Fallback to main wallet
                    
                    result[row[0]] = {
                        'choice': row[1],
                        'amount': row[2],
                        'voted_at': row[3],
                        'breakdown': breakdown
                    }
                return result
    except Exception as e:
        logger.error(f"❌ Error getting votes: {e}")
        return {}

async def get_vote_summary_db(prediction_id: int) -> dict:
    """Get vote summary with counts and totals"""
    try:
        prediction = await get_prediction_db(prediction_id)
        if not prediction:
            return {}
        
        votes = await get_votes_db(prediction_id)
        
        summary = {}
        for outcome in prediction['outcomes']:
            summary[outcome.lower()] = {'count': 0, 'total': 0}
        
        for user_id, vote_data in votes.items():
            choice = vote_data['choice']
            summary[choice]['count'] += 1
            summary[choice]['total'] += vote_data['amount']
        
        total_pool = sum(data['total'] for data in summary.values())
        
        return {
            'outcomes': summary,
            'total_pool': total_pool
        }
    except Exception as e:
        logger.error(f"❌ Error getting vote summary: {e}")
        return {}

async def update_prediction_status_db(prediction_id: int, status: str, result: str = None):
    """Update prediction status and result"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('''
                UPDATE predictions SET status = ?, result = ?
                WHERE id = ?
            ''', (status, result, prediction_id))
            await db.commit()
            logger.info(f"✅ Updated prediction #{prediction_id} status to '{status}'")
        # Wave-Logging dashboard event
        await _wave_log_event(
            category="goals_phour_predictions",
            action="prediction_status_changed",
            details={"prediction_id": prediction_id, "status": status, "result": result},
        )
    except Exception as e:
        logger.error(f"❌ Error updating prediction status: {e}")
        raise

async def get_user_votes_db(user_id: int) -> list:
    """Get all active votes for a user"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT pv.prediction_id, pv.choice, pv.amount, p.title, p.end_date
                FROM prediction_votes pv
                JOIN predictions p ON pv.prediction_id = p.id
                WHERE pv.user_id = ? AND p.status = 'active'
            ''', (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [{
                    'id': row[0],
                    'choice': row[1],
                    'amount': row[2],
                    'title': row[3],
                    'end_date': row[4]
                } for row in rows]
    except Exception as e:
        logger.error(f"❌ Error getting user votes: {e}")
        return []

async def get_prediction_stats() -> dict:
    """Get prediction system statistics"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            stats = {}
            
            async with db.execute('SELECT COUNT(*) FROM predictions') as cursor:
                stats['total_predictions'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM predictions WHERE status = "active"') as cursor:
                stats['active_predictions'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM predictions WHERE status = "ended"') as cursor:
                stats['ended_predictions'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM predictions WHERE status = "cancelled"') as cursor:
                stats['cancelled_predictions'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM prediction_votes') as cursor:
                stats['total_votes'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT SUM(amount) FROM prediction_votes') as cursor:
                row = await cursor.fetchone()
                stats['total_vbucks_predicted'] = row[0] if row[0] else 0
            
            return stats
    except Exception as e:
        logger.error(f"❌ Error getting prediction stats: {e}")
        return {}

# ==================== DATABASE MIGRATION ====================

async def migrate_prediction_votes_add_breakdown():
    """✅ Add breakdown column to prediction_votes table if it doesn't exist"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Check if column already exists
            async with db.execute("PRAGMA table_info(prediction_votes)") as cursor:
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                if 'breakdown' not in column_names:
                    # Add the column
                    await db.execute('''
                        ALTER TABLE prediction_votes 
                        ADD COLUMN breakdown TEXT
                    ''')
                    await db.commit()
                    logger.info("✅ Added 'breakdown' column to prediction_votes table")
                else:
                    logger.info("✅ 'breakdown' column already exists")
    except Exception as e:
        logger.error(f"❌ Error migrating prediction_votes: {e}")
        raise

# ==================== ✅ LOOT ROUTES FUNCTIONS ====================
#
# ⚠️ NAMING NOTE — READ BEFORE DELETING ANYTHING NAMED loot_route_points:
# "Loot Route Points" used to be a spendable CURRENCY. It is GONE — the bot-wide
# spendable currency is now Wave Points (WP). The `loot_route_points` table below
# is NOT a wallet/currency anymore; it is the LOOT ROUTE LEADERBOARD tracker —
# it only counts `routes_completed` per maker (the `total_points` column is legacy
# and stays 0). WP is credited separately via tasks.wave_points.add_wave_points.
# Do not delete this table/functions thinking it's the dead currency — doing so
# breaks the loot-route leaderboard and crashes startup (it's imported at module
# top-level by commands/loot_route_commands.py and tasks/loot_routes.py).

async def migrate_clamp_negative_loot_route_points():
    """
    One-time cleanup: clamp any existing negative Loot Route Point totals to 0.
    Negative balances were possible before the MAX(0, ...) floor was added to
    add_loot_route_points(). Safe to run on every startup — it only touches rows
    that are actually below 0, so once everything is clean it's a harmless no-op.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cursor = await db.execute(
                'UPDATE loot_route_points SET total_points = 0 WHERE total_points < 0'
            )
            fixed = cursor.rowcount
            await db.commit()
            if fixed and fixed > 0:
                logger.info(f"✅ [LOOT ROUTES] Clamped {fixed} negative point total(s) to 0")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error clamping negative point totals: {e}")


async def add_loot_route_points(user_id: int, points: float = 1.0, guild_id: int = None, bot = None) -> Optional[float]:
    """
    ✅ SECURED V2.1: Add Loot Route Points to a user's total with ROLE VALIDATION
    ⛔ BLOCKS Loot Route Points from being given to users WITHOUT Loot Route Maker role

    Args:
        user_id: Discord user ID
        points: Loot Route Points to add (supports decimals)
        guild_id: Guild ID for role validation (required for security)
        bot: Bot instance for fetching guild/member (required for security)

    Returns:
        Optional[float]: New total Loot Route Points, or None if role validation
        fails or an error occurs (distinct from a legitimate total of 0.0)
    """
    try:
        # ✅ CRITICAL ROLE VALIDATION
        LOOT_ROUTE_MAKER_ROLE_ID = 1231188006757728266
        GUILD_ID = 1041450125391835186

        # Use provided guild_id or default
        target_guild_id = guild_id or GUILD_ID

        # If bot instance provided, validate role
        if bot:
            guild = bot.get_guild(target_guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    has_role = any(role.id == LOOT_ROUTE_MAKER_ROLE_ID for role in member.roles)
                    if not has_role:
                        logger.error(f"⛔ [LOOT ROUTES] BLOCKED: User {member.name} ({user_id}) does NOT have Loot Route Maker role!")
                        logger.error(f"⛔ [LOOT ROUTES] Cannot give {points} Loot Route Points to user without role!")
                        return None
                    logger.info(f"✅ [LOOT ROUTES] Role validation passed for user {member.name} ({user_id})")
                else:
                    logger.warning(f"⚠️ [LOOT ROUTES] User {user_id} not found in guild - skipping role validation")
            else:
                logger.warning(f"⚠️ [LOOT ROUTES] Guild {target_guild_id} not found - skipping role validation")
        else:
            logger.warning(f"⚠️ [LOOT ROUTES] No bot instance provided - SKIPPING ROLE VALIDATION (SECURITY RISK!)")

        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()

            # Atomic upsert: insert with starting value, or increment in-place.
            # This avoids the read-then-write race condition that caused points to
            # reset when two pool connections operated concurrently.
            # ✅ FLOOR AT 0: penalties (e.g. late routes at -5) must never push a
            # user's total below 0. MAX(0, ...) clamps both the first-route insert
            # and the running total so negative balances can't exist. The two-arg
            # SQLite max() is the scalar form (largest argument), not the aggregate.
            await db.execute('''
                INSERT INTO loot_route_points (user_id, total_points, routes_completed, last_updated)
                VALUES (?, 0.0, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    routes_completed = routes_completed + 1,
                    last_updated = ?
            ''', (user_id, now, now))

            await db.commit()

            # Read back the committed total so we return the real value
            async with db.execute(
                'SELECT total_points FROM loot_route_points WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                new_points = float(row[0]) if row else points

            logger.info(f"✅ [LOOT ROUTES] Added {points} Loot Route Point(s) to user {user_id} (total: {new_points})")
        # Wave-Logging dashboard event (outside pool block so the lock is released first)
        await _wave_log_event(
            category="loot_routes",
            action="points_added",
            target={"id": str(user_id)},
            guild=guild_id,
            details={"points_added": points, "new_total": new_points},
        )
        return new_points
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error adding Loot Route Points: {e}")
        return None


async def get_loot_route_user_points(user_id: int) -> Dict[str, Any]:
    """Get user's Loot Route Points and routes completed (RETURNS FLOAT)"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT total_points, routes_completed FROM loot_route_points WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'total_points': float(row[0]),
                        'routes_completed': row[1]
                    }
                return {'total_points': 0.0, 'routes_completed': 0}
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting user Loot Route Points: {e}")
        return {'total_points': 0.0, 'routes_completed': 0}


async def get_loot_route_points_leaderboard(limit: int = 100) -> List:
    """
    Get loot route leaderboard sorted by Loot Route Points (RETURNS FLOAT)
    Returns: List of (user_id, total_points, routes_completed)
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT user_id, 0.0, routes_completed FROM loot_route_points ORDER BY routes_completed DESC LIMIT ?',
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                # Convert Loot Route Points to float
                return [(row[0], float(row[1]), row[2]) for row in rows]
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting leaderboard: {e}")
        return []


async def set_loot_route_user_points(user_id: int, points: float, routes: int = None, guild_id: int = None, bot = None):
    """
    ✅ SECURED V2.1: Manually set user's Loot Route Points with ROLE VALIDATION
    ⛔ BLOCKS Loot Route Points from being set for users WITHOUT Loot Route Maker role

    Args:
        user_id: Discord user ID
        points: Loot Route Points to set (supports decimals)
        routes: Routes completed (optional)
        guild_id: Guild ID for role validation (required for security)
        bot: Bot instance for fetching guild/member (required for security)
    """
    try:
        # ✅ CRITICAL ROLE VALIDATION
        LOOT_ROUTE_MAKER_ROLE_ID = 1231188006757728266
        GUILD_ID = 1041450125391835186

        # Use provided guild_id or default
        target_guild_id = guild_id or GUILD_ID

        # If bot instance provided, validate role
        if bot:
            guild = bot.get_guild(target_guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    has_role = any(role.id == LOOT_ROUTE_MAKER_ROLE_ID for role in member.roles)
                    if not has_role:
                        logger.error(f"⛔ [LOOT ROUTES] BLOCKED: User {member.name} ({user_id}) does NOT have Loot Route Maker role!")
                        logger.error(f"⛔ [LOOT ROUTES] Cannot set {points} Loot Route Points for user without role!")
                        return
                    logger.info(f"✅ [LOOT ROUTES] Role validation passed for user {member.name} ({user_id})")
                else:
                    logger.warning(f"⚠️ [LOOT ROUTES] User {user_id} not found in guild - skipping role validation")
            else:
                logger.warning(f"⚠️ [LOOT ROUTES] Guild {target_guild_id} not found - skipping role validation")
        else:
            logger.warning(f"⚠️ [LOOT ROUTES] No bot instance provided - SKIPPING ROLE VALIDATION (SECURITY RISK!)")

        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()

            if routes is None:
                # Get current routes count
                async with db.execute(
                    'SELECT routes_completed FROM loot_route_points WHERE user_id = ?',
                    (user_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    routes = row[0] if row else 0

            await db.execute('''
                INSERT INTO loot_route_points (user_id, total_points, routes_completed, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    total_points = ?,
                    routes_completed = ?,
                    last_updated = ?
            ''', (user_id, points, routes, now, points, routes, now))

            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Set user {user_id} Loot Route Points to {points}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error setting user Loot Route Points: {e}")


async def clear_loot_route_points_global():
    """Clear ALL Loot Route Points"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM loot_route_points')
            cursor = await db.execute('SELECT changes()')
            deleted = (await cursor.fetchone())[0]
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Cleared {deleted} Loot Route Point records")
            return deleted
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error clearing Loot Route Points: {e}")
        return 0


async def create_route_assignment(
    user_id: int,
    guild_id: int,
    notification_message_id: int,
    confirmation_message_id: int,
    map_details: str = None,
    is_lucky_map: bool = False
) -> int:
    """
    Create a new route assignment
    Returns assignment_id
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()

            cursor = await db.execute('''
                INSERT INTO route_assignments
                (user_id, guild_id, notification_message_id, confirmation_message_id,
                 assigned_at, status, map_details, created_at, is_lucky_map)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            ''', (user_id, guild_id, notification_message_id, confirmation_message_id,
                  now, map_details, now, int(is_lucky_map)))
            
            assignment_id = cursor.lastrowid
            await db.commit()
            
            logger.info(f"✅ [LOOT ROUTES] Created assignment #{assignment_id} for user {user_id}")
            return assignment_id
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error creating assignment: {e}")
        return 0

async def update_assignment_message_ids(assignment_id: int, notification_message_id: int, confirmation_message_id: int):
    """Update message IDs for an existing assignment"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('''
                UPDATE route_assignments 
                SET notification_message_id = ?, confirmation_message_id = ?
                WHERE assignment_id = ?
            ''', (notification_message_id, confirmation_message_id, assignment_id))
            
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Updated message IDs for assignment #{assignment_id}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error updating message IDs: {e}")

async def get_route_assignment_by_id(assignment_id: int) -> Optional[Dict[str, Any]]:
    """Get route assignment details by ID"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT assignment_id, user_id, guild_id, notification_message_id,
                       confirmation_message_id, assigned_at, confirmed_at, status,
                       map_details, reminder_count, is_lucky_map
                FROM route_assignments
                WHERE assignment_id = ?
            ''', (assignment_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'assignment_id': row[0],
                        'user_id': row[1],
                        'guild_id': row[2],
                        'notification_message_id': row[3],
                        'confirmation_message_id': row[4],
                        'assigned_at': row[5],
                        'confirmed_at': row[6],
                        'status': row[7],
                        'map_details': row[8],
                        'reminder_count': row[9],
                        'is_lucky_map': bool(row[10]) if row[10] is not None else False,
                    }
                return None
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting assignment by ID: {e}")
        return None


# ── Loot hold pool (maps that arrived while every maker was busy) ──────────────
_LOOT_PENDING_COLS = ('id, guild_id, source_message_id, map_details, image_refs, '
                      'local_files, is_lucky_map, status, created_at')

def _loot_pending_row_to_dict(r) -> Dict[str, Any]:
    return {'id': r[0], 'guild_id': r[1], 'source_message_id': r[2], 'map_details': r[3],
            'image_refs': r[4], 'local_files': r[5], 'is_lucky_map': bool(r[6]),
            'status': r[7], 'created_at': r[8]}

async def enqueue_loot_pending_map(guild_id: int, source_message_id: int = None,
                                   map_details: str = None, image_refs: str = None,
                                   local_files: str = None, is_lucky_map: bool = False) -> int:
    """Hold a map (FIFO) when no maker is free. Returns the pending id (0 on error)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cur = await db.execute('''
                INSERT INTO loot_pending_maps
                (guild_id, source_message_id, map_details, image_refs, local_files,
                 is_lucky_map, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            ''', (guild_id, source_message_id, map_details, image_refs, local_files,
                  int(is_lucky_map), datetime.now(timezone.utc).isoformat()))
            pid = cur.lastrowid
            await db.commit()
            logger.info(f"⏳ [LOOT ROUTES] Held pending map #{pid} (no maker free)")
            return pid
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error enqueuing pending map: {e}")
        return 0

async def get_oldest_loot_pending_map() -> Optional[Dict[str, Any]]:
    """Oldest held map first (FIFO)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                f"SELECT {_LOOT_PENDING_COLS} FROM loot_pending_maps WHERE status='pending' "
                f"ORDER BY created_at ASC, id ASC LIMIT 1") as cur:
                row = await cur.fetchone()
                return _loot_pending_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting oldest pending: {e}")
        return None

async def get_loot_pending_maps() -> List[Dict[str, Any]]:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                f"SELECT {_LOOT_PENDING_COLS} FROM loot_pending_maps WHERE status='pending' "
                f"ORDER BY created_at ASC, id ASC") as cur:
                rows = await cur.fetchall()
                return [_loot_pending_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting pending maps: {e}")
        return []

async def delete_loot_pending_map(pending_id: int):
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM loot_pending_maps WHERE id = ?', (pending_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error deleting pending map: {e}")

async def count_loot_pending_maps() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute("SELECT COUNT(*) FROM loot_pending_maps WHERE status='pending'") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error counting pending: {e}")
        return 0

async def migrate_route_assignments_add_completion_columns():
    """Add completed_at and points_awarded columns to route_assignments if missing"""
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            await db.execute('ALTER TABLE route_assignments ADD COLUMN completed_at TEXT')
            logger.info("✅ [LOOT ROUTES] Added completed_at column to route_assignments")
        except Exception:
            pass  # Column already exists
        try:
            await db.execute('ALTER TABLE route_assignments ADD COLUMN points_awarded REAL')
            logger.info("✅ [LOOT ROUTES] Added points_awarded column to route_assignments")
        except Exception:
            pass  # Column already exists
        await db.commit()

async def migrate_route_assignments_add_lucky_map():
    """Add is_lucky_map column to route_assignments if missing"""
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            await db.execute(
                'ALTER TABLE route_assignments ADD COLUMN is_lucky_map INTEGER DEFAULT 0'
            )
            logger.info("✅ [LOOT ROUTES] Added is_lucky_map column to route_assignments")
        except Exception:
            pass  # Column already exists
        await db.commit()


async def migrate_route_assignments_add_local_files():
    """Add local_files column to route_assignments for CDN-expiry resilience"""
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            await db.execute(
                'ALTER TABLE route_assignments ADD COLUMN local_files TEXT'
            )
            logger.info("✅ [LOOT ROUTES] Added local_files column to route_assignments")
        except Exception:
            pass  # Column already exists
        await db.commit()


async def save_route_local_files(assignment_id: int, file_paths: list):
    """Store JSON list of local file paths for an assignment"""
    import json
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'UPDATE route_assignments SET local_files = ? WHERE assignment_id = ?',
            (json.dumps(file_paths), assignment_id)
        )
        await db.commit()


async def get_route_local_files(assignment_id: int) -> list:
    """Return list of local file paths for an assignment, or empty list"""
    import json
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT local_files FROM route_assignments WHERE assignment_id = ?',
            (assignment_id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return []
    return []






async def complete_route_assignment(assignment_id: int, points_awarded: float):
    """Mark assignment as completed with points awarded and completion time"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()

            # Ensure the columns exist (safe to call repeatedly)
            try:
                await db.execute('ALTER TABLE route_assignments ADD COLUMN completed_at TEXT')
                await db.commit()
            except Exception:
                pass  # Column already exists
            try:
                await db.execute('ALTER TABLE route_assignments ADD COLUMN points_awarded REAL')
                await db.commit()
            except Exception:
                pass  # Column already exists

            cursor = await db.execute('''
                UPDATE route_assignments
                SET status = 'completed', completed_at = ?, points_awarded = ?
                WHERE assignment_id = ?
            ''', (now, points_awarded, assignment_id))
            rows_updated = cursor.rowcount  # Read BEFORE commit
            await db.commit()

            if rows_updated == 0:
                logger.error(
                    f"❌ [LOOT ROUTES] complete_route_assignment: NO ROWS UPDATED for assignment #{assignment_id}!"
                )
                raise ValueError(
                    f"Assignment #{assignment_id} not found in DB — status was NOT updated to 'completed'"
                )

            # Verify the update actually persisted
            async with db.execute(
                "SELECT status FROM route_assignments WHERE assignment_id = ?",
                (assignment_id,)
            ) as check:
                row = await check.fetchone()
                if not row or row[0] != 'completed':
                    raise ValueError(
                        f"Assignment #{assignment_id} UPDATE appeared to succeed but status is still '{row[0] if row else 'missing'}'"
                    )

            logger.info(
                f"✅ [LOOT ROUTES] Completed assignment #{assignment_id} ({points_awarded:+} pts) — verified in DB"
            )
        # Wave-Logging dashboard event
        await _wave_log_event(
            category="loot_routes",
            action="route_completed",
            details={"assignment_id": assignment_id, "points_awarded": points_awarded},
        )
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error completing assignment: {e}")
        raise  # Re-raise so the calling command surfaces the failure


async def confirm_route_assignment(assignment_id: int):
    """Mark assignment as confirmed when user reacts"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            
            await db.execute('''
                UPDATE route_assignments 
                SET status = 'confirmed', confirmed_at = ?
                WHERE assignment_id = ?
            ''', (now, assignment_id))
            
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Confirmed assignment #{assignment_id}")
        # Wave-Logging dashboard event
        await _wave_log_event(
            category="loot_routes",
            action="route_confirmed",
            details={"assignment_id": assignment_id},
        )
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error confirming assignment: {e}")

async def get_assignment_by_confirmation_message(message_id: int) -> Optional[int]:
    """Get assignment ID from confirmation message ID"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT assignment_id FROM route_assignments WHERE confirmation_message_id = ?',
                (message_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting assignment by confirmation message: {e}")
        return None

async def get_assignment_by_notification_message(message_id: int) -> Optional[int]:
    """Get assignment ID from notification message ID"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT assignment_id FROM route_assignments WHERE notification_message_id = ? AND status = "pending"',
                (message_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting assignment by notification message: {e}")
        return None

async def get_assignments_needing_reminders() -> List[Dict[str, Any]]:
    """
    Get all pending assignments that need reminders
    (24+ hours since last reminder or assignment)
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc)
            cutoff = (now - timedelta(hours=24)).isoformat()
            
            async with db.execute('''
                SELECT assignment_id, user_id, guild_id, notification_message_id, 
                       confirmation_message_id, assigned_at, last_reminder_sent, reminder_count
                FROM route_assignments
                WHERE status = 'pending' 
                AND (
                    (last_reminder_sent IS NULL AND assigned_at < ?)
                    OR (last_reminder_sent < ?)
                )
            ''', (cutoff, cutoff)) as cursor:
                rows = await cursor.fetchall()
                
                results = []
                for row in rows:
                    results.append({
                        'assignment_id': row[0],
                        'user_id': row[1],
                        'guild_id': row[2],
                        'notification_message_id': row[3],
                        'confirmation_message_id': row[4],
                        'assigned_at': row[5],
                        'last_reminder_sent': row[6],
                        'reminder_count': row[7]
                    })
                
                return results
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting assignments needing reminders: {e}")
        return []

async def update_reminder_sent(assignment_id: int):
    """Update last reminder timestamp and increment counter"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            
            await db.execute('''
                UPDATE route_assignments 
                SET last_reminder_sent = ?, reminder_count = reminder_count + 1
                WHERE assignment_id = ?
            ''', (now, assignment_id))
            
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Updated reminder for assignment #{assignment_id}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error updating reminder: {e}")

async def get_user_route_assignments(user_id: int, status: str = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Get assignment history for a user"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            if status:
                query = '''
                    SELECT assignment_id, assigned_at, confirmed_at, status, reminder_count, completed_at
                    FROM route_assignments
                    WHERE user_id = ? AND status = ?
                    ORDER BY assigned_at DESC
                    LIMIT ?
                '''
                params = (user_id, status, limit)
            else:
                query = '''
                    SELECT assignment_id, assigned_at, confirmed_at, status, reminder_count, completed_at
                    FROM route_assignments
                    WHERE user_id = ?
                    ORDER BY assigned_at DESC
                    LIMIT ?
                '''
                params = (user_id, limit)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                
                results = []
                for row in rows:
                    results.append({
                        'assignment_id': row[0],
                        'assigned_at': row[1],
                        'confirmed_at': row[2],
                        'status': row[3],
                        'reminder_count': row[4],
                        'completed_at': row[5],
                    })
                
                return results
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting user assignments: {e}")
        return []

async def get_all_route_assignments(guild_id: int) -> List[Dict[str, Any]]:
    """
    ✅ Get all ACTIVE route assignments for a guild — pending or confirmed only.
    Used when reassigning cancelled routes to find who is ACTUALLY working a map
    right now, so they can be skipped from reassignment.

    A 'completed' route means the person already finished and is NOT working a
    map — they must remain eligible for reassignment. Including completed (or any
    other non-active status) here caused >cancelroute to report "No Available
    Users" because everyone who finished a route in the last ~30 days looked busy.
    This matches the canonical active-assignment definition used by
    get_all_pending_assignments() + get_all_confirmed_assignments().

    Args:
        guild_id: The Discord guild/server ID

    Returns:
        List of assignment dicts with keys: user_id, status, assigned_at, etc.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            query = '''
                SELECT assignment_id, user_id, guild_id, assigned_at, status,
                       notification_message_id, confirmation_message_id, completed_at
                FROM route_assignments
                WHERE guild_id = ? AND status IN ('pending', 'confirmed')
                ORDER BY assigned_at DESC
            '''
            params = (guild_id,)
            
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                
                results = []
                for row in rows:
                    results.append({
                        'assignment_id': row[0],
                        'user_id': row[1],
                        'guild_id': row[2],
                        'assigned_at': row[3],
                        'status': row[4],
                        'notification_message_id': row[5],
                        'confirmation_message_id': row[6],
                        'completed_at': row[7],
                    })
                
                return results
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting all route assignments: {e}")
        return []

async def get_route_assignment_stats() -> Dict[str, int]:
    """Get overall assignment statistics"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            stats = {}
            
            async with db.execute('SELECT COUNT(*) FROM route_assignments') as cursor:
                stats['total_assignments'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM route_assignments WHERE status = "pending"') as cursor:
                stats['pending_assignments'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM route_assignments WHERE status = "confirmed"') as cursor:
                stats['confirmed_assignments'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT AVG(reminder_count) FROM route_assignments WHERE status = "confirmed"') as cursor:
                row = await cursor.fetchone()
                stats['avg_reminders'] = round(row[0], 2) if row[0] else 0
            
            return stats
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting assignment stats: {e}")
        return {}

async def save_rotation_state(
    rotation_message_id: int = None,
    sticky_message_id: int = None,
    leaderboard_message_id: int = None,
    last_assigned_position: int = None,
    last_assigned_user_id: int = None,
    total_assignments: int = None
):
    """Save rotation state to database"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            
            # Build update query dynamically based on what's provided
            updates = []
            params = []
            
            if rotation_message_id is not None:
                updates.append('rotation_message_id = ?')
                params.append(rotation_message_id)
            
            if sticky_message_id is not None:
                updates.append('sticky_message_id = ?')
                params.append(sticky_message_id)
            
            if leaderboard_message_id is not None:
                updates.append('leaderboard_message_id = ?')
                params.append(leaderboard_message_id)
            
            if last_assigned_position is not None:
                updates.append('last_assigned_position = ?')
                params.append(last_assigned_position)
            
            if last_assigned_user_id is not None:
                updates.append('last_assigned_user_id = ?')
                params.append(last_assigned_user_id)
            
            if total_assignments is not None:
                updates.append('total_assignments = ?')
                params.append(total_assignments)
            
            if not updates:
                return
            
            updates.append('last_updated = ?')
            params.append(now)
            
            query = f'UPDATE rotation_state SET {", ".join(updates)} WHERE id = 1'
            
            await db.execute(query, params)
            await db.commit()
            logger.info("✅ [LOOT ROUTES] Saved rotation state")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error saving rotation state: {e}")

async def get_rotation_state() -> Dict[str, Any]:
    """Get current rotation state from database"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT rotation_message_id, sticky_message_id, leaderboard_message_id, last_assigned_position, last_assigned_user_id, total_assignments FROM rotation_state WHERE id = 1'
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'rotation_message_id': row[0],
                        'sticky_message_id': row[1],
                        'leaderboard_message_id': row[2],
                        'last_assigned_position': row[3],
                        'last_assigned_user_id': row[4],
                        'total_assignments': row[5]
                    }
                return {}
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting rotation state: {e}")
        return {}

async def increment_total_assignments() -> int:
    """Increment and return new total assignments count"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            
            await db.execute(
                'UPDATE rotation_state SET total_assignments = total_assignments + 1, last_updated = ? WHERE id = 1',
                (now,)
            )
            
            async with db.execute('SELECT total_assignments FROM rotation_state WHERE id = 1') as cursor:
                row = await cursor.fetchone()
                new_count = row[0] if row else 0
            
            await db.commit()
            return new_count
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error incrementing assignments: {e}")
        return 0

async def cleanup_old_route_assignments(days: int = 30):
    """Remove confirmed assignments older than X days"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            
            await db.execute(
                'DELETE FROM route_assignments WHERE status = "confirmed" AND confirmed_at < ?',
                (cutoff,)
            )
            
            cursor = await db.execute('SELECT changes()')
            deleted = (await cursor.fetchone())[0]
            
            await db.commit()
            
            if deleted > 0:
                logger.info(f"✅ [LOOT ROUTES] Cleaned up {deleted} old assignments")
            
            return deleted
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error cleaning up assignments: {e}")
        return 0

async def clear_route_assignments_global():
    """Clear ALL route assignments"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM route_assignments')
            cursor = await db.execute('SELECT changes()')
            deleted = (await cursor.fetchone())[0]
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Cleared {deleted} assignment records")
            return deleted
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error clearing assignments: {e}")
        return 0

async def reset_rotation_state_db():
    """Reset rotation state (admin only)"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute('''
                UPDATE rotation_state
                SET rotation_message_id = NULL,
                    sticky_message_id = NULL,
                    leaderboard_message_id = NULL,
                    last_assigned_position = 0,
                    last_assigned_user_id = NULL,
                    total_assignments = 0,
                    last_updated = ?
                WHERE id = 1
            ''', (now,))
            await db.commit()
            logger.info("✅ [LOOT ROUTES] Reset rotation state")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error resetting rotation state: {e}")

async def check_mvp_already_posted(guild_id: int, year: int, week_number: int) -> bool:
    """Check if MVP has already been posted for this week"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT 1 FROM weekly_mvp_posts WHERE guild_id = ? AND year = ? AND week_number = ?',
                (guild_id, year, week_number)
            ) as cursor:
                return await cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error checking MVP post: {e}")
        return False

async def save_mvp_post(guild_id: int, year: int, week_number: int, message_id: int):
    """Record that MVP has been posted for this week"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                '''INSERT INTO weekly_mvp_posts (guild_id, year, week_number, message_id, posted_at)
                   VALUES (?, ?, ?, ?, ?)''',
                (guild_id, year, week_number, message_id, now)
            )
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Recorded MVP post for week {week_number}/{year}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error saving MVP post: {e}")

async def get_loot_route_position(user_id: int) -> Optional[int]:
    """
    Get the user's CURRENT ROTATION RANK (1-indexed) — the same number shown next to
    their name in the rotation message. Returns None if user is not in the rotation.
    Rank is computed from assigned_at order, not the legacy position_number column.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT user_id FROM loot_route_positions ORDER BY assigned_at ASC, user_id ASC'
            ) as cursor:
                rows = await cursor.fetchall()
                for rank, row in enumerate(rows, start=1):
                    if row[0] == user_id:
                        return rank
                return None
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting position: {e}")
        return None

async def set_loot_route_position(user_id: int, position: int):
    """Assign a permanent position to a user"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            
            await db.execute('''
                INSERT INTO loot_route_positions (user_id, position_number, assigned_at, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    position_number = ?,
                    last_updated = ?
            ''', (user_id, position, now, now, position, now))
            
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Set position {position} for user {user_id}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error setting position: {e}")
        raise

async def remove_loot_route_position(user_id: int):
    """Remove user's position (when removed from rotation)"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM loot_route_positions WHERE user_id = ?', (user_id,))
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Removed position for user {user_id}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error removing position: {e}")

async def get_all_loot_route_positions() -> List[Tuple[int, int]]:
    """
    Get all loot route makers with their CURRENT ROTATION RANK.
    Sorted by assigned_at (oldest first), with user_id as deterministic tiebreaker.
    Returns: List of (rank, user_id) where rank is the 1-indexed position in the rotation.
    Ranks are always sequential 1..N with no gaps — they reflect the rotation order users
    were added, not the legacy position_number column.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT user_id FROM loot_route_positions ORDER BY assigned_at ASC, user_id ASC'
            ) as cursor:
                rows = await cursor.fetchall()
                return [(rank, row[0]) for rank, row in enumerate(rows, start=1)]
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting all positions: {e}")
        return []

async def archive_loot_route_maker(user_id: int, display_name: str = None, left_at: str = None) -> bool:
    """
    Move a loot route maker who lost their role to the alumni history table.
    Copies their points + rotation data, then removes them from the active tables.
    Their route_assignments rows stay intact for historical stats.

    Returns True if archived successfully, False if no active record found.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    left = left_at or now

    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Fetch active points record
            async with db.execute(
                'SELECT total_points, routes_completed, last_updated FROM loot_route_points WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                pts_row = await cursor.fetchone()

            # Fetch rotation position record
            async with db.execute(
                'SELECT position_number, assigned_at FROM loot_route_positions WHERE user_id = ?',
                (user_id,)
            ) as cursor:
                pos_row = await cursor.fetchone()

            if not pts_row and not pos_row:
                logger.info(f"ℹ️ [ALUMNI] No active loot route data for {user_id} — nothing to archive")
                return False

            total_points     = pts_row[0] if pts_row else 0
            routes_completed = pts_row[1] if pts_row else 0
            rotation_number  = pos_row[0] if pos_row else None
            joined_at        = pos_row[1] if pos_row else None

            # Upsert into alumni table (handles re-joining and re-leaving)
            await db.execute('''
                INSERT INTO loot_route_alumni
                    (user_id, display_name, total_points, routes_completed,
                     rotation_number, joined_at, left_at, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name     = excluded.display_name,
                    total_points     = excluded.total_points,
                    routes_completed = excluded.routes_completed,
                    rotation_number  = excluded.rotation_number,
                    joined_at        = excluded.joined_at,
                    left_at          = excluded.left_at,
                    archived_at      = excluded.archived_at
            ''', (user_id, display_name, total_points, routes_completed,
                  rotation_number, joined_at, left, now))

            # Remove from active loot route tables
            await db.execute('DELETE FROM loot_route_points    WHERE user_id = ?', (user_id,))
            await db.execute('DELETE FROM loot_route_positions WHERE user_id = ?', (user_id,))
            await db.execute('DELETE FROM loot_route_away_dates WHERE user_id = ?', (user_id,))

            await db.commit()

        logger.info(
            f"✅ [ALUMNI] Archived loot route maker {user_id} ({display_name}) — "
            f"{total_points} pts, {routes_completed} routes, rotation #{rotation_number}"
        )
        return True

    except Exception as e:
        logger.error(f"❌ [ALUMNI] Failed to archive loot route maker {user_id}: {e}")
        return False


async def get_loot_route_alumni() -> List[dict]:
    """Fetch all alumni (former loot route makers), ordered by most points."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT user_id, display_name, total_points, routes_completed,
                       rotation_number, joined_at, left_at, archived_at
                FROM loot_route_alumni
                ORDER BY total_points DESC
            ''') as cursor:
                rows = await cursor.fetchall()
        return [
            {
                'user_id': r[0], 'display_name': r[1],
                'total_points': r[2], 'routes_completed': r[3],
                'rotation_number': r[4], 'joined_at': r[5],
                'left_at': r[6], 'archived_at': r[7],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"❌ [ALUMNI] Error fetching alumni: {e}")
        return []


async def get_next_position_number() -> int:
    """Get the next available position number (always highest + 1, never reuse gaps)"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT MAX(position_number) FROM loot_route_positions'
            ) as cursor:
                row = await cursor.fetchone()
                max_pos = row[0] if row and row[0] else 0
                return max_pos + 1
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting next position: {e}")
        return 1

async def sync_positions_from_role_members(guild_id: int, role_members: List[int]):
    """
    Sync positions from role members (initial setup only)
    Assigns sequential positions to existing role members
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            
            # Get existing positions
            async with db.execute('SELECT user_id FROM loot_route_positions') as cursor:
                existing = set(row[0] for row in await cursor.fetchall())
            
            # Only add NEW members (don't touch existing positions)
            new_members = [uid for uid in role_members if uid not in existing]
            
            if not new_members:
                logger.info(f"✅ [LOOT ROUTES] All role members already have positions")
                return
            
            # Get next available position
            next_pos = await get_next_position_number()
            
            # Assign positions to new members
            for uid in new_members:
                await db.execute('''
                    INSERT INTO loot_route_positions (user_id, position_number, assigned_at, last_updated)
                    VALUES (?, ?, ?, ?)
                ''', (uid, next_pos, now, now))
                next_pos += 1
            
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Synced {len(new_members)} new positions")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error syncing positions: {e}")

async def clear_loot_route_positions_global():
    """Clear ALL position assignments (admin only)"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM loot_route_positions')
            cursor = await db.execute('SELECT changes()')
            deleted = (await cursor.fetchone())[0]
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Cleared {deleted} position assignments")
            return deleted
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error clearing positions: {e}")
        return 0

async def delete_route_assignment(assignment_id: int):
    """Delete a route assignment from database"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                "DELETE FROM route_assignments WHERE assignment_id = ?",
                (assignment_id,)
            )
            await db.commit()
            logger.info(f"✅ [LOOT ROUTES] Deleted assignment #{assignment_id}")
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error deleting assignment: {e}")


async def get_all_pending_assignments() -> list:
    """Get all pending route assignments"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('PRAGMA wal_checkpoint(PASSIVE)')
            async with db.execute("""
                SELECT 
                    assignment_id,
                    user_id,
                    assigned_at,
                    reminder_count,
                    map_details
                FROM route_assignments
                WHERE status = 'pending'
                ORDER BY assigned_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                
                assignments = []
                for row in rows:
                    assignments.append({
                        'assignment_id': row[0],
                        'user_id': row[1],
                        'assigned_at': row[2],
                        'reminder_count': row[3],
                        'map_details': row[4],
                        'status': 'pending',
                    })
                
                return assignments
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting pending assignments: {e}")
        return []


async def get_all_confirmed_assignments() -> list:
    """Get all confirmed (reacted by user, but not yet marked done by staff) route assignments"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('PRAGMA wal_checkpoint(PASSIVE)')
            async with db.execute("""
                SELECT 
                    assignment_id,
                    user_id,
                    assigned_at,
                    reminder_count,
                    map_details
                FROM route_assignments
                WHERE status = 'confirmed'
                ORDER BY assigned_at DESC
            """) as cursor:
                rows = await cursor.fetchall()
                
                assignments = []
                for row in rows:
                    assignments.append({
                        'assignment_id': row[0],
                        'user_id': row[1],
                        'assigned_at': row[2],
                        'reminder_count': row[3],
                        'map_details': row[4],
                        'status': 'confirmed',
                    })
                
                return assignments
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting confirmed assignments: {e}")
        return []


async def get_recent_assignment_history(limit: int = 30) -> list:
    """Get recent assignment history including completed, cancelled, confirmed"""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            # Force WAL checkpoint so all pool connections see the latest committed writes
            await db.execute('PRAGMA wal_checkpoint(PASSIVE)')
            async with db.execute("""
                SELECT 
                    assignment_id,
                    user_id,
                    guild_id,
                    status,
                    assigned_at,
                    confirmed_at,
                    map_details,
                    completed_at,
                    points_awarded
                FROM route_assignments
                ORDER BY assigned_at DESC
                LIMIT ?
            """, (limit,)) as cursor:
                rows = await cursor.fetchall()
                
                history = []
                for row in rows:
                    history.append({
                        'assignment_id': row[0],
                        'user_id': row[1],
                        'guild_id': row[2],
                        'status': row[3],
                        'assigned_at': row[4],
                        'confirmed_at': row[5],
                        'map_details': row[6],
                        'completed_at': row[7],
                        'points_awarded': row[8],
                    })
                
                return history
    except Exception as e:
        logger.error(f"❌ [LOOT ROUTES] Error getting assignment history: {e}")
        return []

async def save_staff_insight_batch(stats: dict, duty_type: str, week_start: str, week_end: str, is_midweek: bool = False):
    """
    Save scan results for all users in one batch after an insights export.

    Args:
        stats       — dict of {user_id: {'name': str, 'count': int}}  (from scan_duty_activity)
        duty_type   — 'role' | 'req' | 'modlog' | 'message'
        week_start  — 'DD/MM/YYYY'
        week_end    — 'DD/MM/YYYY'
        is_midweek  — True if this is a mid-week export
    """
    if not stats:
        return

    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            is_midweek_int = 1 if is_midweek else 0

            rows = []
            for user_id, data in stats.items():
                rows.append((
                    user_id,
                    data.get('name', f'User {user_id}'),
                    duty_type,
                    week_start,
                    week_end,
                    data.get('count', 0),
                    is_midweek_int,
                    now
                ))

            # Upsert — if a record for this user+duty+week already exists, update the count
            await db.executemany('''
                INSERT INTO staff_insights_history
                    (user_id, user_name, duty_type, week_start, week_end, count, is_midweek, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING
            ''', rows)

            # If you'd rather overwrite duplicates, swap the above with:
            # ON CONFLICT(user_id, duty_type, week_start, is_midweek) DO UPDATE SET
            #     count = excluded.count,
            #     user_name = excluded.user_name,
            #     recorded_at = excluded.recorded_at

            await db.commit()
            logger.info(f"✅ Saved {len(rows)} insights history records ({duty_type}, {week_start}→{week_end})")

    except Exception as e:
        logger.error(f"❌ Error in save_staff_insight_batch: {e}")


async def get_staff_insights_history(user_id: int) -> list:
    """
    Retrieve all recorded weekly insights for a user, newest first.

    Returns a list of dicts:
        [{'duty_type', 'week_start', 'week_end', 'count', 'is_midweek', 'recorded_at'}, ...]
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute('''
                SELECT duty_type, week_start, week_end, count, is_midweek, recorded_at
                FROM staff_insights_history
                WHERE user_id = ?
                ORDER BY week_start DESC, is_midweek ASC, duty_type ASC
            ''', (user_id,)) as cursor:
                rows = await cursor.fetchall()

            return [
                {
                    'duty_type':   row[0],
                    'week_start':  row[1],
                    'week_end':    row[2],
                    'count':       row[3],
                    'is_midweek':  bool(row[4]),
                    'recorded_at': row[5],
                }
                for row in rows
            ]

    except Exception as e:
        logger.error(f"❌ Error in get_staff_insights_history: {e}")
        return []


async def clear_staff_insights_history_global():
    """Wipe ALL insights history (admin use only)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            cursor = await db.execute('DELETE FROM staff_insights_history')
            await db.commit()
            deleted = cursor.rowcount
            logger.info(f"✅ Cleared {deleted} staff insights history records")
            return deleted
    except Exception as e:
        logger.error(f"❌ Error in clear_staff_insights_history_global: {e}")
        return 0

async def init_wave_points_table():
    """Initialize wave_points table"""
    pool = await get_pool()
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
    logger.info("✅ wave_points table initialized")



async def get_vbucks_leaderboard(duty_type: str, limit: int = 100) -> list:
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                '''SELECT user_id, total_vbucks, last_updated FROM vbucks
                   WHERE duty_type = ? ORDER BY total_vbucks DESC LIMIT ?''',
                (duty_type, limit)
            ) as cursor:
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"❌ Error getting vbucks leaderboard: {e}")
        return []

async def get_vbucks(user_id: int, duty_type: str) -> int:
    """Get VBucks balance for a user in a specific wallet. Returns 0 if not found."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT total_vbucks FROM vbucks WHERE user_id = ? AND duty_type = ?',
            (user_id, duty_type)
        ) as cursor:
            row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def set_vbucks(user_id: int, duty_type: str, amount: int, bot=None) -> bool:
    """Set VBucks to a specific amount for a user in a specific duty wallet."""
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        if amount <= 0:
            await db.execute(
                'DELETE FROM vbucks WHERE user_id = ? AND duty_type = ?',
                (user_id, duty_type)
            )
        else:
            await db.execute('''
                INSERT INTO vbucks (user_id, duty_type, total_vbucks, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, duty_type) DO UPDATE SET
                    total_vbucks = ?,
                    last_updated = ?
            ''', (user_id, duty_type, amount, now, amount, now))
        await db.commit()
        # Wave-Logging dashboard event
        await _wave_log_event(
            category="vbucks",
            action="vbucks_set",
            target={"id": str(user_id)},
            details={"amount": amount, "wallet": duty_type},
        )
        # Rebuild the Staff Hub economy/VBucks-leaderboard JSON on any balance
        # change (redemptions, awards, manual sets). Debounced ~10s so a burst
        # (e.g. weekly awards) collapses into a single push. Lazy import avoids
        # a circular dependency with tasks.economy_sync.
        if bot is not None:
            try:
                from tasks.economy_sync import auto_update_economy_dashboard
                await auto_update_economy_dashboard(bot, triggered_by="vbucks")
            except Exception as e:
                logger.debug(f"[set_vbucks] economy auto-update skipped: {e}")
        return True


async def add_vbucks(user_id: int, duty_type: str = 'main', amount: int = 0, bot=None) -> int:
    """Add (or subtract) VBucks for a user.

    Single-wallet model: `duty_type` is accepted for backward-compatibility with
    legacy callers but everything is credited to the `main` wallet. Balance floors
    at 0. Returns the new balance.
    """
    current = await get_vbucks(user_id, 'main')
    new_total = max(0, current + int(amount))
    await set_vbucks(user_id, 'main', new_total, bot=bot)
    return new_total


# ── VBucks reservations (locks balance without deducting; used by predictions) ──
# Single-wallet model: every reservation is against `main`. The `wallet_type`
# argument is accepted for backward-compatibility with legacy callers and ignored.

async def get_reserved_vbucks(user_id: int, wallet_type: str = 'main') -> int:
    """Total VBucks currently locked (reserved) for a user across all reasons."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT COALESCE(SUM(amount), 0) FROM vbucks_reservations WHERE user_id = ?',
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return int(row[0]) if row and row[0] else 0


async def get_available_vbucks(user_id: int, wallet_type: str = 'main') -> int:
    """Spendable balance = main wallet total minus everything currently reserved."""
    total = await get_vbucks(user_id, 'main')
    reserved = await get_reserved_vbucks(user_id)
    return max(0, total - reserved)


async def reserve_vbucks(user_id: int, wallet_type: str = 'main', amount: int = 0,
                         reason: str = '', reference_id: int = None) -> bool:
    """Lock VBucks (stays in the wallet but becomes unavailable). Adds to any
    existing reservation for the same (reason, reference_id)."""
    if amount is None or amount <= 0:
        return False
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT INTO vbucks_reservations (user_id, wallet_type, amount, reason, reference_id, created_at)
            VALUES (?, 'main', ?, ?, ?, ?)
            ON CONFLICT(user_id, wallet_type, reason, reference_id)
                DO UPDATE SET amount = amount + excluded.amount
        ''', (user_id, int(amount), reason, reference_id, now))
        await db.commit()
    return True


async def release_reservation(user_id: int, wallet_type: str = 'main',
                              reason: str = '', reference_id: int = None) -> int:
    """Release (unlock) a user's reservation for a given (reason, reference_id).
    Returns the amount that was released."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT COALESCE(SUM(amount), 0) FROM vbucks_reservations '
            'WHERE user_id = ? AND reason = ? AND reference_id IS ?',
            (user_id, reason, reference_id)
        ) as cur:
            row = await cur.fetchone()
        released = int(row[0]) if row and row[0] else 0
        await db.execute(
            'DELETE FROM vbucks_reservations WHERE user_id = ? AND reason = ? AND reference_id IS ?',
            (user_id, reason, reference_id)
        )
        await db.commit()
    return released


async def get_user_reservation_breakdown(user_id: int, reason: str = None,
                                         reference_id: int = None) -> dict:
    """Return the user's reserved amount as a single-wallet breakdown {'main': N}."""
    reserved = await get_reserved_vbucks(user_id)
    return {'main': reserved} if reserved else {}


async def log_transaction_fee(user_id: int, fee_type: str, amount_before: int, fee: int, amount_after: int):
    """Record a fee collection in the transaction log."""
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT INTO transaction_fees (user_id, fee_type, amount_before, fee_collected, amount_after, collected_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, fee_type, amount_before, fee, amount_after, now))
        await db.commit()


async def get_fee_history(limit: int = 20) -> list:
    """Return recent fee collection records."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute('''
            SELECT user_id, fee_type, amount_before, fee_collected, amount_after, collected_at
            FROM transaction_fees
            ORDER BY collected_at DESC
            LIMIT ?
        ''', (limit,)) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    'user_id':       r[0],
                    'fee_type':      r[1],
                    'amount_before': r[2],
                    'fee_collected': r[3],
                    'amount_after':  r[4],
                    'collected_at':  r[5],
                }
                for r in rows
            ]

async def init_wave_points_interest():
    """Ensure the interest-tracking table exists."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS wave_points_interest (
                user_id          INTEGER PRIMARY KEY,
                accrued_fraction REAL    DEFAULT 0.0,
                last_paid_at     TEXT    NOT NULL,
                total_earned     INTEGER DEFAULT 0
            )
        ''')
        await db.commit()
    logger.info("✅ wave_points_interest table initialised")


async def get_interest_record(user_id: int) -> dict | None:
    """Return the interest record for a user, or None if they have none."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT user_id, accrued_fraction, last_paid_at, total_earned '
            'FROM wave_points_interest WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {
        'user_id':          row[0],
        'accrued_fraction': row[1],
        'last_paid_at':     row[2],
        'total_earned':     row[3],
    }


async def upsert_interest_record(user_id: int, accrued_fraction: float, total_earned: int):
    """Create or update the interest record for a user."""
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT INTO wave_points_interest (user_id, accrued_fraction, last_paid_at, total_earned)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                accrued_fraction = excluded.accrued_fraction,
                last_paid_at     = excluded.last_paid_at,
                total_earned     = excluded.total_earned
        ''', (user_id, accrued_fraction, now, total_earned))
        await db.commit()


async def get_all_wave_points_for_interest() -> list[dict]:
    """
    Return all users who currently hold ≥ INTEREST_MIN_BALANCE Wave Points.
    Used by the daily interest task to know who qualifies.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT user_id, points FROM wave_points WHERE points >= ? AND left_at IS NULL',
            (INTEREST_MIN_BALANCE,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [{'user_id': r[0], 'points': r[1]} for r in rows]

INTEREST_APR        = 0.10
INTEREST_DAILY_RATE = INTEREST_APR / 365
INTEREST_MIN_BALANCE = 50            # minimum Wave Points to qualify

# ==================== CENTRAL BANK DB HELPERS ====================

from datetime import date

def _current_week_start() -> str:
    """Return the most recent Saturday (week start) as YYYY-MM-DD."""
    today = date.today()
    days_since_saturday = (today.weekday() - 5) % 7
    saturday = today - timedelta(days=days_since_saturday)
    return saturday.isoformat()


async def init_central_bank():
    """Ensure the central bank singleton row exists."""
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT OR IGNORE INTO central_bank (id, reserves_vbucks, reserves_points, reserves_lrp, reserves_srp, fee_rate_pct, ptv_tax_pct, last_updated)
            VALUES (1, 0, 0, 0, 0, 5.0, 50.0, ?)
        ''', (now,))
        await db.commit()
    logger.info("✅ Central bank initialised")


async def get_central_bank() -> dict:
    """Return the central bank state as a dict."""
    await init_central_bank()
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT reserves_vbucks, reserves_points, reserves_lrp, reserves_srp, fee_rate_pct, ptv_tax_pct, last_updated FROM central_bank WHERE id = 1'
        ) as cursor:
            row = await cursor.fetchone()
            return {
                'reserves_vbucks': row[0],
                'reserves_points': row[1],
                'reserves_lrp':    row[2],
                'reserves_srp':    row[3],
                'fee_rate_pct':    row[4],
                'ptv_tax_pct':     row[5] if row[5] is not None else 50.0,
                'last_updated':    row[6],
            }


async def add_to_central_bank(vbucks: int = 0, points: int = 0, lrp: int = 0, srp: int = 0):
    """Add vbucks, points, LRP, and/or SRP to central bank reserves."""
    await init_central_bank()
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            UPDATE central_bank
            SET reserves_vbucks = reserves_vbucks + ?,
                reserves_points = reserves_points + ?,
                reserves_lrp    = reserves_lrp + ?,
                reserves_srp    = reserves_srp + ?,
                last_updated    = ?
            WHERE id = 1
        ''', (vbucks, points, lrp, srp, now))
        await db.commit()


async def set_fee_rate(new_rate: float):
    """Update the fee rate (percentage, e.g. 2.0 = 2%)."""
    await init_central_bank()
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            'UPDATE central_bank SET fee_rate_pct = ?, last_updated = ? WHERE id = 1',
            (new_rate, now)
        )
        await db.commit()


async def set_ptv_tax_rate(new_rate: float):
    """Update the WP→VBucks exit tax (percentage). Applies to >ptv only."""
    await init_central_bank()
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            'UPDATE central_bank SET ptv_tax_pct = ?, last_updated = ? WHERE id = 1',
            (new_rate, now)
        )
        await db.commit()


async def inject_vbucks_to_user(user_id: int, amount: int):
    """Deduct from central bank reserves and credit to a user's main VBucks wallet."""
    bank = await get_central_bank()
    if bank['reserves_vbucks'] < amount:
        raise ValueError(f"Insufficient reserves ({bank['reserves_vbucks']:,} VBucks available)")
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            'UPDATE central_bank SET reserves_vbucks = reserves_vbucks - ?, last_updated = ? WHERE id = 1',
            (amount, now)
        )
        await db.execute('''
            INSERT INTO vbucks (user_id, duty_type, total_vbucks, last_updated)
            VALUES (?, 'main', ?, ?)
            ON CONFLICT(user_id, duty_type) DO UPDATE SET
                total_vbucks = total_vbucks + ?,
                last_updated = ?
        ''', (user_id, amount, now, amount, now))
        await db.commit()


async def inject_points_to_user(user_id: int, amount: int):
    """Deduct from central bank point reserves and credit Wave Points to a user."""
    bank = await get_central_bank()
    if bank['reserves_points'] < amount:
        raise ValueError(f"Insufficient reserves ({bank['reserves_points']:,} Wave Points available)")
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute(
            'UPDATE central_bank SET reserves_points = reserves_points - ?, last_updated = ? WHERE id = 1',
            (amount, now)
        )
        await db.commit()
    from tasks.wave_points import add_wave_points
    return await add_wave_points(user_id, amount)


# ==================== CENTRAL BANK CONVENIENCE ALIASES ====================
# Called by central_banks.py fee logic

async def add_to_vbucks_reserves(amount: int):
    """Add VBucks to central bank reserves (from >ptv conversion fees)."""
    await add_to_central_bank(vbucks=amount, points=0)


async def add_to_points_reserves(amount: int):
    """Add Wave Points to central bank reserves (from >vtp conversion fees)."""
    await add_to_central_bank(vbucks=0, points=amount)


async def record_fee(user_id: int, gross_amount: int, fee: int, fee_type: str):
    """Record a fee collection in the transaction log (alias for log_transaction_fee)."""
    net = gross_amount - fee
    await log_transaction_fee(user_id, fee_type, gross_amount, fee, net)

# ==================== MILESTONE TOTALS ====================

async def upsert_milestone_total(user_id: int, username: str, duty_type: str, total: int):
    """
    Insert or update a staff member's all-time total for one duty type.
    Called automatically after each full-week staff insights export.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        await db.execute('''
            INSERT INTO milestone_totals (user_id, username, duty_type, total, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, duty_type) DO UPDATE SET
                username   = excluded.username,
                total      = excluded.total,
                updated_at = excluded.updated_at
        ''', (user_id, username, duty_type, total, now))
        await db.commit()

# ==================== DATABASE FUNCTION TO ADD ====================
# Add this function to database.py

async def get_all_users_for_duty(duty_type: str) -> list:
    """
    Get all user IDs that have any data (VBucks or Strikes) for a specific duty
    Used to find users who have left but still have records
    
    Args:
        duty_type: 'role', 'req', or 'main'
    
    Returns:
        list of user IDs
    """
    validate_wallet_type(duty_type)
    pool = await get_pool()
    
    try:
        async with pool.acquire() as db:
            # Get users with VBucks for this duty
            async with db.execute(
                'SELECT DISTINCT user_id FROM vbucks WHERE duty_type = ? ORDER BY user_id',
                (duty_type,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"❌ Failed to get users for {duty_type} duty: {e}")
        return []


# ==================== ALTERNATIVE: If you want to include strikes too ====================

async def get_all_users_for_duty_with_activity(duty_type: str) -> set:
    """
    Get all user IDs that have ANY data (VBucks OR Strikes) for a specific duty
    More comprehensive than just VBucks
    
    Args:
        duty_type: 'role', 'req', or 'main'
    
    Returns:
        set of user IDs
    """
    validate_wallet_type(duty_type)
    pool = await get_pool()
    
    try:
        users = set()
        async with pool.acquire() as db:
            # Get users with VBucks
            async with db.execute(
                'SELECT DISTINCT user_id FROM vbucks WHERE duty_type = ?',
                (duty_type,)
            ) as cursor:
                rows = await cursor.fetchall()
                users.update([row[0] for row in rows])

            # (strike_points lookup removed — strike system retired;
            #  only VBucks holders are now considered "active for duty")

        return users
    
    except Exception as e:
        logger.error(f"❌ Failed to get users with activity for {duty_type} duty: {e}")
        return set()

# ==================== LOOT ROUTE AWAY RETURN DATES ====================

async def set_away_return_date(user_id: int, return_date: str):
    """
    Upsert a scheduled return date for a user on away.
    return_date should be an ISO date string: 'YYYY-MM-DD'
    """
    pool = await get_pool()
    now = datetime.now(timezone.utc).isoformat()
    async with pool.acquire() as db:
        await db.execute('''
            INSERT INTO loot_route_away_dates (user_id, return_date, set_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                return_date = excluded.return_date,
                set_at      = excluded.set_at
        ''', (user_id, return_date, now))
        await db.commit()
    logger.info(f"✅ Away return date set for user {user_id}: {return_date}")


async def delete_away_return_date(user_id: int):
    """Remove the scheduled return date for a user (called when away is manually cleared)."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'DELETE FROM loot_route_away_dates WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()
    logger.info(f"✅ Away return date cleared for user {user_id}")


async def get_all_away_return_dates() -> list[dict]:
    """
    Return all scheduled return dates.
    Used on bot startup to reload the in-memory dict.
    Returns: list of {'user_id': int, 'return_date': str, 'set_at': str}
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT user_id, return_date, set_at FROM loot_route_away_dates'
        ) as cursor:
            rows = await cursor.fetchall()
    return [{'user_id': r[0], 'return_date': r[1], 'set_at': r[2]} for r in rows]


# ==================== STAFF AWAY DATES ====================

async def set_staff_away_return_date(user_id: int, return_date: str):
    """Upsert a scheduled return date for staff away."""
    pool = await get_pool()
    now = datetime.now(timezone.utc).isoformat()
    async with pool.acquire() as db:
        await db.execute('''
            INSERT INTO staff_away_dates (user_id, return_date, set_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                return_date = excluded.return_date,
                set_at      = excluded.set_at
        ''', (user_id, return_date, now))
        await db.commit()
    logger.info(f"✅ Staff away return date set for user {user_id}: {return_date}")


async def delete_staff_away_return_date(user_id: int):
    """Remove the scheduled return date for staff away."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'DELETE FROM staff_away_dates WHERE user_id = ?',
            (user_id,)
        )
        await db.commit()
    logger.info(f"✅ Staff away return date cleared for user {user_id}")


async def get_all_staff_away_return_dates() -> list[dict]:
    """Return all scheduled staff away return dates."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT user_id, return_date, set_at FROM staff_away_dates ORDER BY user_id'
        ) as cursor:
            rows = await cursor.fetchall()
    return [{'user_id': r[0], 'return_date': r[1], 'set_at': r[2]} for r in rows]

# ==================== REPLY DM PENDING DELETES ====================

async def init_reply_dm_tables():
    """Create reply DM pending deletes tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS reply_dm_pending_deletes (
                message_id     INTEGER PRIMARY KEY,
                channel_id     INTEGER NOT NULL,
                staff_reply_id INTEGER DEFAULT 0,
                delete_at      REAL    NOT NULL,
                member_id      INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS reply_dm_pending_staff_mention_deletes (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                delete_at  REAL    NOT NULL
            )
        ''')
        await db.commit()

async def add_reply_dm_pending_delete(message_id: int, channel_id: int, staff_reply_id: int, delete_at: float, member_id: int = 0):
    """Save a pending auto-delete job so it survives bot restarts."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'INSERT OR REPLACE INTO reply_dm_pending_deletes '
                '(message_id, channel_id, staff_reply_id, delete_at, member_id) '
                'VALUES (?, ?, ?, ?, ?)',
                (message_id, channel_id, staff_reply_id, delete_at, member_id)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error saving pending delete: {e}")

async def remove_reply_dm_pending_delete(message_id: int):
    """Remove a completed or cancelled pending auto-delete job."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM reply_dm_pending_deletes WHERE message_id = ?', (message_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error removing pending delete: {e}")

async def get_reply_dm_pending_deletes() -> list:
    """Load all pending auto-delete jobs on startup."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT message_id, channel_id, staff_reply_id, delete_at, member_id FROM reply_dm_pending_deletes'
            ) as cursor:
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"❌ Error loading pending deletes: {e}")
        return []

async def add_staff_mention_pending_delete(message_id: int, channel_id: int, delete_at: float):
    """Save a pending staff-mention delete job so it survives bot restarts."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute(
                'INSERT OR REPLACE INTO reply_dm_pending_staff_mention_deletes VALUES (?, ?, ?)',
                (message_id, channel_id, delete_at)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error saving pending staff-mention delete: {e}")

async def remove_staff_mention_pending_delete(message_id: int):
    """Remove a completed or cancelled staff-mention delete job."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            await db.execute('DELETE FROM reply_dm_pending_staff_mention_deletes WHERE message_id = ?', (message_id,))
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Error removing pending staff-mention delete: {e}")

async def get_staff_mention_pending_deletes() -> list:
    """Load all pending staff-mention delete jobs on startup."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT message_id, channel_id, delete_at FROM reply_dm_pending_staff_mention_deletes'
            ) as cursor:
                return await cursor.fetchall()
    except Exception as e:
        logger.error(f"❌ Error loading pending staff-mention deletes: {e}")
        return []


async def get_milestone_notification_channel(guild_id: int) -> tuple:
    """Get the milestone notification channel/thread for a guild."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT milestone_notification_channel, milestone_notification_thread FROM guild_settings WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if result:
                return (result[0], result[1]) if isinstance(result, tuple) else (result['milestone_notification_channel'], result['milestone_notification_thread'])
            return (None, None)


async def set_milestone_notification_channel(guild_id: int, channel_id: int = None, thread_id: int = None) -> None:
    """Set the milestone notification channel/thread for a guild."""
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """INSERT INTO guild_settings (guild_id, milestone_notification_channel, milestone_notification_thread, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(guild_id) DO UPDATE SET
               milestone_notification_channel = excluded.milestone_notification_channel,
               milestone_notification_thread = excluded.milestone_notification_thread,
               updated_at = CURRENT_TIMESTAMP""",
            (guild_id, channel_id, thread_id)
        )
        await db.commit()


# ==================== THREAD RESPONSE TRACKING ====================

async def log_thread_creation(thread_id: int, channel_id: int, creator_id: int, original_message_timestamp: str = None) -> None:
    """Log a new thread creation.
    
    Args:
        original_message_timestamp: ISO format timestamp of the original message the thread was created from.
                                    If None, falls back to CURRENT_TIMESTAMP.
    """
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            if original_message_timestamp:
                await db.execute(
                    """INSERT INTO thread_responses (thread_id, channel_id, creator_id, thread_created_at)
                       VALUES (?, ?, ?, ?)""",
                    (thread_id, channel_id, creator_id, original_message_timestamp)
                )
            else:
                await db.execute(
                    """INSERT INTO thread_responses (thread_id, channel_id, creator_id, thread_created_at)
                       VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                    (thread_id, channel_id, creator_id)
                )
            await db.commit()
            logger.info(f"✅ Inserted thread_responses: thread_id={thread_id}, channel_id={channel_id}, creator_id={creator_id}")
        except Exception as e:
            logger.error(f"❌ Error logging thread creation: {e}", exc_info=True)


async def log_thread_response(thread_id: int, responder_id: int, response_time_seconds: int, points_bracket: str) -> None:
    """Log the first response in a thread."""
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            await db.execute(
                """UPDATE thread_responses
                   SET first_responder_id = ?, first_response_at = CURRENT_TIMESTAMP,
                       response_time_seconds = ?, points_bracket = ?
                   WHERE thread_id = ? AND first_responder_id IS NULL""",
                (responder_id, response_time_seconds, points_bracket, thread_id)
            )
            await db.commit()
        except Exception as e:
            logger.debug(f"Error logging thread response: {e}")


async def get_thread_info(thread_id: int) -> dict:
    """Get thread creation info if it hasn't been responded to yet."""
    pool = await get_pool()
    async with pool.acquire() as db:
        try:
            # First, check what columns exist
            async with db.execute("PRAGMA table_info(thread_responses)") as cursor:
                columns = await cursor.fetchall()
                col_names = [col[1] for col in columns]
                logger.debug(f"thread_responses columns: {col_names}")

            async with db.execute(
                "SELECT * FROM thread_responses WHERE thread_id = ?",
                (thread_id,)
            ) as cursor:
                result = await cursor.fetchone()
                if result:
                    data = row_to_dict(result)
                    logger.info(f"✅ Found thread info: {data}")
                    return data
                logger.info(f"⚠️ No thread info found for thread_id={thread_id}")
                return None
        except Exception as e:
            logger.error(f"❌ Error getting thread info: {e}", exc_info=True)
            return None


async def get_market_tier(market_pair: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT current_tier FROM exchange_market WHERE market_pair = ?', (market_pair,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 3

async def update_market_stats(market_pair: str, amount_bought: int, amount_sold: int):
    # Increment total_bought and total_sold, and maybe adjust tier if thresholds hit.
    pass # to be implemented


# ==================== WEB EXCHANGES ====================

async def init_web_exchanges_table():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS web_exchanges (
                id            TEXT    PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                exchange_type TEXT    NOT NULL,
                amount_in     REAL    NOT NULL,
                status        TEXT    NOT NULL DEFAULT 'pending',
                result_json   TEXT,
                created_at    REAL    NOT NULL,
                updated_at    REAL    NOT NULL
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_web_exchanges_status ON web_exchanges (status, created_at)'
        )
        await db.commit()


async def insert_web_exchange(user_id: int, exchange_type: str, amount_in: float) -> str:
    import time, uuid as _uuid
    eid = str(_uuid.uuid4())
    now = time.time()
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            'INSERT INTO web_exchanges (id, user_id, exchange_type, amount_in, status, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (eid, user_id, exchange_type, amount_in, 'pending', now, now)
        )
        await db.commit()
    return eid


async def fetch_pending_web_exchanges(limit: int = 5) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT id, user_id, exchange_type, amount_in FROM web_exchanges "
            "WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [{'id': r[0], 'user_id': r[1], 'exchange_type': r[2], 'amount_in': r[3]} for r in rows]


async def claim_web_exchange(eid: str) -> bool:
    import time
    pool = await get_pool()
    async with pool.acquire() as db:
        cur = await db.execute(
            "UPDATE web_exchanges SET status='processing', updated_at=? "
            "WHERE id=? AND status='pending'",
            (time.time(), eid)
        )
        await db.commit()
    return cur.rowcount == 1


async def complete_web_exchange(eid: str, result: dict):
    import time, json as _json
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE web_exchanges SET status='completed', result_json=?, updated_at=? WHERE id=?",
            (_json.dumps(result), time.time(), eid)
        )
        await db.commit()


async def fail_web_exchange(eid: str, error: str):
    import time, json as _json
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE web_exchanges SET status='failed', result_json=?, updated_at=? WHERE id=?",
            (_json.dumps({'error': error}), time.time(), eid)
        )
        await db.commit()


async def get_web_exchange(eid: str, user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT id, status, result_json FROM web_exchanges WHERE id=? AND user_id=?',
            (eid, user_id)
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {'id': row[0], 'status': row[1], 'result_json': row[2]}


async def get_web_exchange_history(user_id: int, limit: int = 10) -> list:
    import json as _json
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            'SELECT id, exchange_type, amount_in, status, result_json, created_at '
            'FROM web_exchanges WHERE user_id=? ORDER BY created_at DESC LIMIT ?',
            (user_id, limit)
        ) as cur:
            rows = await cur.fetchall()
    out = []
    for r in rows:
        result = None
        if r[4]:
            try:
                result = _json.loads(r[4])
            except Exception:
                pass
        out.append({
            'id': r[0], 'exchange_type': r[1], 'amount_in': r[2],
            'status': r[3], 'result': result, 'created_at': r[5]
        })
    return out


# ==================== WEB BONDS ====================

async def init_web_bonds_table():
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS web_bonds (
                id          TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL,
                days        INTEGER NOT NULL,
                amount      INTEGER NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'pending',
                result_json TEXT,
                created_at  REAL    NOT NULL,
                updated_at  REAL    NOT NULL
            )
        ''')
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_web_bonds_status ON web_bonds (status, created_at)'
        )
        await db.commit()


async def fetch_pending_web_bonds(limit: int = 5) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute(
            "SELECT id, user_id, days, amount FROM web_bonds "
            "WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?",
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
    return [{'id': r[0], 'user_id': r[1], 'days': r[2], 'amount': r[3]} for r in rows]


async def claim_web_bond(eid: str) -> bool:
    import time
    pool = await get_pool()
    async with pool.acquire() as db:
        cur = await db.execute(
            "UPDATE web_bonds SET status='processing', updated_at=? "
            "WHERE id=? AND status='pending'",
            (time.time(), eid)
        )
        await db.commit()
    return cur.rowcount > 0


async def complete_web_bond(eid: str, result: dict):
    import time, json as _json
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE web_bonds SET status='completed', result_json=?, updated_at=? WHERE id=?",
            (_json.dumps(result), time.time(), eid)
        )
        await db.commit()


async def fail_web_bond(eid: str, error: str):
    import time, json as _json
    pool = await get_pool()
    async with pool.acquire() as db:
        await db.execute(
            "UPDATE web_bonds SET status='failed', result_json=?, updated_at=? WHERE id=?",
            (_json.dumps({'error': error}), time.time(), eid)
        )
        await db.commit()

# ==================== WEB SHOP ====================

# ==================== LIFETIME TOTALS ====================

async def upsert_lifetime_totals_batch(
    user_metrics: Dict[int, Dict[str, int]],
    start_date: str,
) -> None:
    """
    Accumulate finalized weekly counts into lifetime_totals.

    Args:
        user_metrics: {user_id: {'message': N, 'modlog': N, 'req': N}}
        start_date:   week start_date (DD/MM/YYYY) — used as dup guard.

    Only adds if last_added_week != start_date (prevents double-accumulation).
    """
    if not user_metrics:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            for uid, metrics in user_metrics.items():
                for metric, count in metrics.items():
                    if count <= 0:
                        continue
                    # Check dup guard
                    async with db.execute(
                        'SELECT last_added_week FROM lifetime_totals WHERE user_id = ? AND metric = ?',
                        (uid, metric),
                    ) as cur:
                        row = await cur.fetchone()
                    if row and row[0] == start_date:
                        continue  # already accumulated this week
                    await db.execute('''
                        INSERT INTO lifetime_totals (user_id, metric, total, last_added_week, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, metric) DO UPDATE SET
                            total           = total + excluded.total,
                            last_added_week = excluded.last_added_week,
                            updated_at      = excluded.updated_at
                    ''', (uid, metric, count, start_date, now))
            await db.commit()
            logger.info(f"✅ Lifetime totals accumulated for {len(user_metrics)} users (week {start_date})")
    except Exception as e:
        logger.error(f"❌ Error in upsert_lifetime_totals_batch: {e}")


async def set_lifetime_totals_baseline(
    user_metrics: Dict[int, Dict[str, int]],
    start_date: str,
) -> None:
    """
    One-time migration: SET (not add) lifetime baseline from Google Sheets.
    Sets last_added_week = start_date so the first accumulation doesn't double-add.
    """
    if not user_metrics:
        return
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            now = datetime.now(timezone.utc).isoformat()
            for uid, metrics in user_metrics.items():
                for metric, total in metrics.items():
                    await db.execute('''
                        INSERT INTO lifetime_totals (user_id, metric, total, last_added_week, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(user_id, metric) DO UPDATE SET
                            total           = excluded.total,
                            last_added_week = excluded.last_added_week,
                            updated_at      = excluded.updated_at
                    ''', (uid, metric, total, start_date, now))
            await db.commit()
            logger.info(f"✅ Lifetime baseline set for {len(user_metrics)} users (from Sheets migration)")
    except Exception as e:
        logger.error(f"❌ Error in set_lifetime_totals_baseline: {e}")


async def get_all_lifetime_totals() -> Dict[int, Dict[str, int]]:
    """
    Read all lifetime_totals rows.
    Returns {user_id: {'message': N, 'modlog': N, 'req': N}}.
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                'SELECT user_id, metric, total FROM lifetime_totals'
            ) as cur:
                rows = await cur.fetchall()
        result: Dict[int, Dict[str, int]] = {}
        for uid, metric, total in rows:
            result.setdefault(uid, {})[metric] = total
        return result
    except Exception as e:
        logger.error(f"❌ Error in get_all_lifetime_totals: {e}")
        return {}


async def get_all_time_reviews() -> Dict[int, int]:
    """
    Sum ALL reviews from bot_logs (all-time, no date filter).
    Self-healing — always reflects the authoritative source.
    Returns {user_id: total_review_count}.
    """
    import aiosqlite
    counts: Dict[int, int] = {}
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("PRAGMA busy_timeout=30000")
            cursor = await conn.execute(
                "SELECT actor_json FROM bot_logs "
                "WHERE category = 'hitl_review' AND action = 'review_completed'"
            )
            rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"  get_all_time_reviews failed: {e}")
        return counts
    for (actor_json,) in rows:
        if not actor_json:
            continue
        try:
            actor = json.loads(actor_json)
            uid = int(actor.get('id'))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        counts[uid] = counts.get(uid, 0) + 1
    return counts


async def get_all_successful_redemptions() -> list:
    """Get all successful redemptions to be saved in JSON for the profile pages."""
    try:
        pool = await get_pool()
        async with pool.acquire() as db:
            async with db.execute(
                "SELECT user_id, prize, cost, created_at, processed_at "
                "FROM web_redemptions "
                "WHERE status IN ('completed', 'success') "
                "ORDER BY created_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"❌ Error getting redemptions: {e}")
        return []

