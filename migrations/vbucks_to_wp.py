"""
VBucks → Wave Points Migration — vbucks_to_wp_v1
=================================================
Converts all held VBucks balances to Wave Points at the locked migration rate:
  15 WP = 100 VBucks  (1,000 VB → 150 WP)

⚠️  This rate is INTENTIONALLY lower than the buy price (50 WP = 100 VB).
    It deflates the VBucks overhang rather than dumping WP into circulation.
    Do NOT "fix" this asymmetry — see the plan.

Run ONCE on the main machine with the bot STOPPED and all sessions merged.

What this does:
  1. Credits each user ROUND(total_vbucks * 15 / 100) Wave Points.
  2. Zeros all vbucks table balances.
  3. Converts central-bank VBucks reserves at 15/100 into WP reserves, zeros VB reserves.
  4. Asserts no open prediction pools (settle them first if any exist).
  5. Writes sentinel row 'vbucks_to_wp_v1' to migration_log.

Usage:
  python migrations/vbucks_to_wp.py           # dry-run preview (safe to run any time)
  python migrations/vbucks_to_wp.py --commit  # apply for real (bot must be stopped)

Safety:
  - Idempotent: refuses to run again if the sentinel exists.
  - Entire operation is one atomic transaction (rolls back on any error).
"""

import sqlite3
import sys
import os
from datetime import datetime, timezone

DB_PATH      = os.path.join(os.path.dirname(__file__), '..', 'bot_database.db')
MIGRATION_ID = 'vbucks_to_wp_v1'

# Locked migration rate: this many WP per 100 VBucks.
# MUST match the plan's decision #2 — do not change.
WP_PER_100_VB = 15

COMMIT = '--commit' in sys.argv


def run():
    db_path = os.path.abspath(DB_PATH)
    if not os.path.exists(db_path):
        print(f"❌  Database not found at: {db_path}")
        sys.exit(1)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    # ── idempotency guard ────────────────────────────────────────────────────
    con.execute('''
        CREATE TABLE IF NOT EXISTS migration_log (
            id          TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL
        )
    ''')
    con.commit()

    if con.execute('SELECT 1 FROM migration_log WHERE id = ?', (MIGRATION_ID,)).fetchone():
        print(f"✅  Migration '{MIGRATION_ID}' already applied. Nothing to do.")
        con.close()
        return

    # ── gather preview data ──────────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()

    # Sum VBucks per user across all wallet types (handles both single-row and
    # multi-row-per-user schemas gracefully).
    vb_users = con.execute('''
        SELECT user_id, SUM(total_vbucks) AS holdings
        FROM vbucks
        WHERE total_vbucks > 0
        GROUP BY user_id
        HAVING SUM(total_vbucks) > 0
    ''').fetchall()

    bank = con.execute(
        'SELECT reserves_points, reserves_vbucks FROM central_bank WHERE id = 1'
    ).fetchone()
    bank_wp_before  = bank['reserves_points']  if bank else 0
    bank_vb_before  = bank['reserves_vbucks']  if bank else 0
    bank_wp_gain    = round(bank_vb_before * WP_PER_100_VB / 100)
    bank_wp_after   = bank_wp_before + bank_wp_gain

    total_vb_in_wallets  = sum(r['holdings'] for r in vb_users)
    total_wp_to_credit   = sum(round(r['holdings'] * WP_PER_100_VB / 100) for r in vb_users)

    # ── check for open prediction pools ─────────────────────────────────────
    open_pools = 0
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM prediction_pools WHERE status = 'OPEN'"
        ).fetchone()
        open_pools = row[0] if row else 0
    except sqlite3.OperationalError:
        pass  # table may not exist yet

    # ── print preview ────────────────────────────────────────────────────────
    print()
    print('=' * 65)
    print('  VBUCKS → WAVE POINTS MIGRATION — PREVIEW')
    print('=' * 65)
    print(f'  Database  : {db_path}')
    print(f'  Mode      : {"[COMMIT] will write to DB" if COMMIT else "[DRY-RUN] read-only"}')
    print(f'  Rate      : {WP_PER_100_VB} WP per 100 VBucks  (1,000 VB → {WP_PER_100_VB * 10} WP)')
    print()
    print('  USER WALLET CONVERSIONS')
    print(f'    VBucks holders  : {len(vb_users):>5}  users')
    print(f'    Total VBucks    : {total_vb_in_wallets:>10,}  VBucks → zeroed')
    print(f'    Total WP gain   : {total_wp_to_credit:>10,}  WP credited to users')
    print()
    print('  CENTRAL BANK')
    print(f'    reserves_vbucks : {bank_vb_before:>10,}  → 0  (+{bank_wp_gain:,} to reserves_points)')
    print(f'    reserves_points : {bank_wp_before:>10,}  → {bank_wp_after:,}')
    print()

    if open_pools > 0:
        print(f'  ⚠️  WARNING: {open_pools} open prediction pool(s) detected!')
        print(f'      Settle or cancel all open predictions BEFORE running --commit.')
        if COMMIT:
            print()
            print('  [!] Aborting — open prediction pools must be settled first.')
            print('=' * 65)
            con.close()
            sys.exit(1)
    else:
        print('  PREDICTIONS: no open pools found ✅')
    print()

    if not COMMIT:
        print('  [!] DRY-RUN only. Run with --commit to apply.')
        print('=' * 65)
        con.close()
        return

    # ── confirmation prompt ──────────────────────────────────────────────────
    answer = input('  Apply migration? Type YES to confirm: ').strip()
    if answer != 'YES':
        print('  Aborted.')
        con.close()
        return

    # ── apply (single atomic transaction) ───────────────────────────────────
    try:
        con.execute('BEGIN')

        # 1. Credit WP to each user for their VBucks holdings
        for row in vb_users:
            wp_gain = round(row['holdings'] * WP_PER_100_VB / 100)
            if wp_gain <= 0:
                continue
            con.execute('''
                INSERT INTO wave_points (user_id, points, last_rank_total, last_updated)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    points       = points + excluded.points,
                    last_updated = excluded.last_updated
            ''', (row['user_id'], wp_gain, now))

        # 2. Zero all VBucks balances
        con.execute('UPDATE vbucks SET total_vbucks = 0 WHERE total_vbucks > 0')

        # 3. Convert bank VBucks reserves → WP reserves; zero VB reserves
        if bank and bank_vb_before > 0:
            con.execute('''
                UPDATE central_bank
                SET reserves_points  = reserves_points + ?,
                    reserves_vbucks  = 0,
                    last_updated     = ?
                WHERE id = 1
            ''', (bank_wp_gain, now))

        # 4. Write sentinel
        con.execute('INSERT INTO migration_log (id, applied_at) VALUES (?, ?)', (MIGRATION_ID, now))

        con.execute('COMMIT')

        print()
        print('  [OK] Migration applied successfully.')
        print(f'       {len(vb_users)} users credited, {total_vb_in_wallets:,} VBucks zeroed.')
        print(f'       Bank: +{bank_wp_gain:,} WP reserves, VBucks reserves zeroed.')
        print('  Restart the bot to pick up the code changes.')
        print('=' * 65)

    except Exception as e:
        con.execute('ROLLBACK')
        print(f'\n  [ERR] Error — rolled back: {e}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
