#!/usr/bin/env python3
"""
Hard-reset tracker snapshot history (keeps server/guild rosters).

Usage:
  python reset_tracker_data.py --dry-run
  python reset_tracker_data.py --confirm
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
TRACKERS = [
    ("guild-stats", ["snapshots"]),
    ("market-research", ["snapshots"]),
    ("drop-map-research", ["snapshots", "predictions"]),
]


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _wipe_db(tracker: str, tables: list[str], dry_run: bool) -> dict[str, int]:
    data_dir = REPO / "command-trackers" / tracker / "data"
    db_path = data_dir / "data.db"
    if not db_path.exists():
        return {t: 0 for t in tables}

    conn = sqlite3.connect(str(db_path))
    before = {t: _count(conn, t) for t in tables}
    if not dry_run:
        for t in tables:
            if before[t]:
                conn.execute(f"DELETE FROM {t}")
        conn.commit()
        stamp = data_dir / "RESET_AT.txt"
        stamp.write_text(
            f"Snapshots reset at {datetime.now(timezone.utc).isoformat()} UTC\n",
            encoding="utf-8",
        )
    after = {t: _count(conn, t) for t in tables}
    conn.close()
    return before, after


def main():
    parser = argparse.ArgumentParser(description="Wipe all tracker snapshot history")
    parser.add_argument("--dry-run", action="store_true", help="Show counts only")
    parser.add_argument("--confirm", action="store_true", help="Execute delete (required)")
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("ERROR: Pass --dry-run to preview or --confirm to execute.")
        sys.exit(1)

    mode = "DRY RUN" if args.dry_run else "RESET"
    print(f"=== Tracker snapshot {mode} ===\n")

    for tracker, tables in TRACKERS:
        before, after = _wipe_db(tracker, tables, dry_run=args.dry_run)
        print(f"[{tracker}]")
        for t in tables:
            print(f"  {t}: {before[t]} rows -> {after[t]} rows")
        print()

    if args.dry_run:
        print("No changes made. Re-run with --confirm to wipe.")
    else:
        print("Done. Run fresh collects before regenerating reports.")


if __name__ == "__main__":
    main()
