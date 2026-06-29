"""
One-shot migration: collapse the 4-wallet VBucks model into a single `main` wallet.

Before: vbucks rows keyed on (user_id, duty_type) where duty_type ∈ {main, req, role, purge}.
After:  every user's balances are summed into a single duty_type='main' row; all other
        rows are deleted. Reservations are likewise collapsed onto wallet_type='main'
        (amounts summed per (user_id, reason, reference_id) to respect the PK).

Safe to run more than once (idempotent — a second run is a no-op once only `main` remains).
Always takes a timestamped backup of bot_database.db first.

Run:  python migrations/consolidate_vbucks_wallets.py
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime, timezone

# Resolve repo root regardless of where the script is launched from.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "bot_database.db")


def _backup() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(ROOT, "database_backups", f"pre_wallet_merge_{stamp}.db")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(DB_PATH, dest)
    return dest


def _report(conn, label):
    print(f"\n── {label} ──")
    rows = conn.execute(
        "SELECT duty_type, COUNT(*), COALESCE(SUM(total_vbucks),0) "
        "FROM vbucks GROUP BY duty_type ORDER BY duty_type"
    ).fetchall()
    if not rows:
        print("  (no vbucks rows)")
    for dt, cnt, total in rows:
        print(f"  {dt:<6} users={cnt:<4} total={total:,}")


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        sys.exit(1)

    backup = _backup()
    print(f"✅ Backup written: {backup}")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("BEGIN IMMEDIATE")
        _report(conn, "BEFORE")

        # ── 1. Sum every user's wallets into a single main balance ──
        totals = conn.execute(
            "SELECT user_id, COALESCE(SUM(total_vbucks),0) "
            "FROM vbucks GROUP BY user_id"
        ).fetchall()

        now = datetime.now(timezone.utc).isoformat()
        # Wipe the table, then re-insert one main row per user with a positive total.
        conn.execute("DELETE FROM vbucks")
        merged = 0
        for user_id, total in totals:
            if total and total > 0:
                conn.execute(
                    "INSERT INTO vbucks (user_id, duty_type, total_vbucks, last_updated) "
                    "VALUES (?, 'main', ?, ?)",
                    (user_id, total, now),
                )
                merged += 1

        # ── 2. Collapse reservations onto the main wallet ──
        #     PK is (user_id, wallet_type, reason, reference_id); sum across wallet_types.
        res_count = 0
        try:
            agg = conn.execute(
                "SELECT user_id, reason, reference_id, COALESCE(SUM(amount),0), MIN(created_at) "
                "FROM vbucks_reservations GROUP BY user_id, reason, reference_id"
            ).fetchall()
            conn.execute("DELETE FROM vbucks_reservations")
            for user_id, reason, reference_id, amount, created_at in agg:
                if amount and amount > 0:
                    conn.execute(
                        "INSERT INTO vbucks_reservations "
                        "(user_id, wallet_type, amount, reason, reference_id, created_at) "
                        "VALUES (?, 'main', ?, ?, ?, ?)",
                        (user_id, amount, reason, reference_id, created_at or now),
                    )
                    res_count += 1
        except sqlite3.OperationalError as e:
            print(f"  ⚠️  Skipped reservations ({e})")

        _report(conn, "AFTER")
        conn.commit()
        print(f"\n✅ Merged {merged} users onto the main wallet; {res_count} reservations collapsed.")
        print("   Rollback if needed by restoring the backup above.")
    except Exception:
        conn.rollback()
        print("❌ Migration failed — rolled back. DB unchanged.")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
