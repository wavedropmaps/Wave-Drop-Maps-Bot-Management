import logging
from datetime import datetime, timezone, timedelta
from database import get_pool, init_central_bank

logger = logging.getLogger('discord')

# ==================== GLOBAL SUPPLY HELPERS ====================

async def get_total_wave_points() -> int:
    """Total WP held by users only — bank reserves excluded (treated as out of circulation)."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT SUM(points) FROM wave_points') as cursor:
            row = await cursor.fetchone()
            return max(1, int(row[0]) if row and row[0] else 1)  # Avoid division by zero

async def get_total_vbucks() -> int:
    """Total VBucks held by users only — bank reserves excluded (treated as out of circulation)."""
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT SUM(total_vbucks) FROM vbucks') as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row and row[0] else 0


# ==================== BANK BONDS ====================

async def create_bond(user_id: int, amount_locked: int, amount_payout: int, days: int = 14) -> bool:
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        maturity = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        await db.execute('''
            INSERT INTO bank_bonds (user_id, amount_locked, bought_at, maturity_date, amount_payout, status)
            VALUES (?, ?, ?, ?, ?, 'ACTIVE')
        ''', (user_id, amount_locked, now, maturity, amount_payout))
        await db.commit()
        return True

async def get_active_bonds(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as db:
        async with db.execute('SELECT id, amount_locked, maturity_date, amount_payout FROM bank_bonds WHERE user_id = ? AND status = "ACTIVE"', (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [{'id': r[0], 'amount_locked': r[1], 'maturity_date': r[2], 'amount_payout': r[3]} for r in rows]

async def resolve_matured_bonds() -> list:
    """Finds bonds past maturity, marks them resolved, and returns them for payout."""
    pool = await get_pool()
    async with pool.acquire() as db:
        now = datetime.now(timezone.utc).isoformat()
        async with db.execute('SELECT id, user_id, amount_payout FROM bank_bonds WHERE status = "ACTIVE" AND maturity_date <= ?', (now,)) as cursor:
            rows = await cursor.fetchall()
            
        matured = [{'id': r[0], 'user_id': r[1], 'amount_payout': r[2]} for r in rows]
        
        for b in matured:
            await db.execute('UPDATE bank_bonds SET status = "RESOLVED" WHERE id = ?', (b['id'],))
            
        await db.commit()
        return matured


# ==================== LOTTERY ====================

