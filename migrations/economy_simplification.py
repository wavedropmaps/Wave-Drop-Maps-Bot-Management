"""
Economy Simplification Migration — Phase 0
==========================================
Converts LRP, SRP, and TTP balances to Wave Points at baseline rates.
Run ONCE on the main machine with the bot STOPPED.

Rates:
  1 LRP = 4 WP
  1 SRP = 3 WP
  1 TTP = 40 WP

What this does:
  1. Adds LRPx4 + SRPx3 + TTPx40 to each user's wave_points balance
  2. Multiplies loot_route_points.total_points x 4  (column now means WP earned)
  3. Multiplies surge_route_points.total_points x 3
  4. Multiplies tt_helper_points.total_points x 40
  5. Folds bank reserves_lrpx4 + reserves_srpx3 into reserves_points
  6. Zeroes reserves_lrp and reserves_srp
  7. Wipes route_converted_wp table

Usage:
  python migrations/economy_simplification.py           # dry-run preview
  python migrations/economy_simplification.py --commit  # apply for real

Safety:
  - Writes a sentinel row to a migration_log table on completion.
  - Refuses to run again if the sentinel exists.
  - Entire operation is one atomic transaction (rolls back on any error).
"""

import sqlite3
import sys
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'bot_database.db')
MIGRATION_ID = 'economy_simplification_v1'

LRP_RATE = 4    # 1 LRP -> 4 WP
SRP_RATE = 3    # 1 SRP -> 3 WP
TTP_RATE = 40   # 1 TTP -> 40 WP

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

    lrp_users = con.execute('SELECT user_id, total_points FROM loot_route_points WHERE total_points > 0').fetchall()
    srp_users = con.execute('SELECT user_id, total_points FROM surge_route_points WHERE total_points > 0').fetchall()
    ttp_users = con.execute('SELECT user_id, total_points FROM tt_helper_points WHERE total_points > 0').fetchall()

    bank = con.execute('SELECT reserves_lrp, reserves_srp, reserves_points FROM central_bank WHERE id = 1').fetchone()
    bank_lrp   = bank['reserves_lrp']   if bank else 0
    bank_srp   = bank['reserves_srp']   if bank else 0
    bank_wp    = bank['reserves_points'] if bank else 0

    total_wp_from_lrp = sum(r['total_points'] * LRP_RATE for r in lrp_users)
    total_wp_from_srp = sum(r['total_points'] * SRP_RATE for r in srp_users)
    total_wp_from_ttp = sum(r['total_points'] * TTP_RATE for r in ttp_users)
    bank_wp_gain = int(bank_lrp * LRP_RATE + bank_srp * SRP_RATE)

    rcwp_count = con.execute('SELECT COUNT(*) FROM route_converted_wp').fetchone()[0]

    # ── print preview ────────────────────────────────────────────────────────
    print()
    print('=' * 60)
    print('  ECONOMY SIMPLIFICATION MIGRATION - PREVIEW')
    print('=' * 60)
    print(f'  Database : {db_path}')
    print(f'  Mode     : {"[COMMIT] will write to DB" if COMMIT else "[DRY-RUN] read-only"}')
    print()
    print('  USER WALLET CONVERSIONS')
    print(f'    LRP holders  : {len(lrp_users):>5}  users  (+{total_wp_from_lrp:,.0f} WP total)')
    print(f'    SRP holders  : {len(srp_users):>5}  users  (+{total_wp_from_srp:,.0f} WP total)')
    print(f'    TTP holders  : {len(ttp_users):>5}  users  (+{total_wp_from_ttp:,.0f} WP total)')
    print()
    print('  LEADERBOARD COLUMN RESCALE')
    print(f'    loot_route_points.total_points  x {LRP_RATE}  (now = WP earned)')
    print(f'    surge_route_points.total_points x {SRP_RATE}  (now = WP earned)')
    print(f'    tt_helper_points.total_points   x {TTP_RATE} (now = WP earned)')
    print()
    print('  CENTRAL BANK')
    print(f'    reserves_lrp  : {bank_lrp:>8,}  -> 0  (+{int(bank_lrp * LRP_RATE):,} to reserves_points)')
    print(f'    reserves_srp  : {bank_srp:>8,}  -> 0  (+{int(bank_srp * SRP_RATE):,} to reserves_points)')
    print(f'    reserves_points before : {bank_wp:,}')
    print(f'    reserves_points after  : {bank_wp + bank_wp_gain:,}')
    print()
    print('  OTHER')
    print(f'    route_converted_wp rows to wipe: {rcwp_count}')
    print()

    if not COMMIT:
        print('  [!] DRY-RUN only. Run with --commit to apply.')
        print('=' * 60)
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

        # 1. Credit WP to users for their LRP
        for row in lrp_users:
            wp_gain = int(row['total_points'] * LRP_RATE)
            if wp_gain <= 0:
                continue
            con.execute('''
                INSERT INTO wave_points (user_id, points, last_rank_total, last_updated)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    points = points + excluded.points,
                    last_updated = excluded.last_updated
            ''', (row['user_id'], wp_gain, now))

        # 2. Credit WP to users for their SRP
        for row in srp_users:
            wp_gain = int(row['total_points'] * SRP_RATE)
            if wp_gain <= 0:
                continue
            con.execute('''
                INSERT INTO wave_points (user_id, points, last_rank_total, last_updated)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    points = points + excluded.points,
                    last_updated = excluded.last_updated
            ''', (row['user_id'], wp_gain, now))

        # 3. Credit WP to users for their TTP
        for row in ttp_users:
            wp_gain = int(row['total_points'] * TTP_RATE)
            if wp_gain <= 0:
                continue
            con.execute('''
                INSERT INTO wave_points (user_id, points, last_rank_total, last_updated)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    points = points + excluded.points,
                    last_updated = excluded.last_updated
            ''', (row['user_id'], wp_gain, now))

        # 4. Rescale loot_route_points leaderboard column (LRP -> WP equivalent)
        con.execute(f'UPDATE loot_route_points SET total_points = ROUND(total_points * {LRP_RATE}), last_updated = ?', (now,))

        # 5. Rescale surge_route_points leaderboard column
        con.execute(f'UPDATE surge_route_points SET total_points = ROUND(total_points * {SRP_RATE}), last_updated = ?', (now,))

        # 6. Rescale tt_helper_points leaderboard column
        con.execute(f'UPDATE tt_helper_points SET total_points = ROUND(total_points * {TTP_RATE}), last_updated = ?', (now,))

        # 7. Fold bank LRP/SRP reserves into WP reserves
        if bank:
            con.execute('''
                UPDATE central_bank SET
                    reserves_points = reserves_points + ? + ?,
                    reserves_lrp    = 0,
                    reserves_srp    = 0,
                    last_updated    = ?
                WHERE id = 1
            ''', (int(bank_lrp * LRP_RATE), int(bank_srp * SRP_RATE), now))

        # 8. Wipe route_converted_wp
        con.execute('DELETE FROM route_converted_wp')

        # 9. Record sentinel
        con.execute('INSERT INTO migration_log (id, applied_at) VALUES (?, ?)', (MIGRATION_ID, now))

        con.execute('COMMIT')

        print()
        print('  [OK] Migration applied successfully.')
        print('  Restart the bot to pick up the code changes.')
        print('=' * 60)

    except Exception as e:
        con.execute('ROLLBACK')
        print(f'\n  [ERR] Error -- rolled back: {e}')
        raise
    finally:
        con.close()


if __name__ == '__main__':
    run()
