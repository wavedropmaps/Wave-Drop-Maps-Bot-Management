#!/usr/bin/env python3
"""
Collect Discord stats for tracked guilds via the REST API.
Reads BOT_TOKEN from .env at the repo root (no Playwright needed).

Usage:
    python collect.py
    python collect.py --dry-run
    python collect.py --no-browser
    python collect.py --skip-if-today    # show latest if already collected today
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT  = SCRIPT_DIR.parents[2]   # scripts/ → guild-stats/ → command-trackers/ → repo root

sys.path.insert(0, str(SCRIPT_DIR))
import db as db_module


def load_token():
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith("BOT_TOKEN="):
                    val = line[len("BOT_TOKEN="):].strip().strip('"').strip("'")
                    if val:
                        return val
    return os.environ.get("BOT_TOKEN")


def discord_get(path: str, token: str):
    url = f"https://discord.com/api/v10{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bot {token}",
        "User-Agent": "WaveManagementBot/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_guild_stats(guild_id: str, token: str) -> dict:
    guild = discord_get(f"/guilds/{guild_id}?with_counts=true", token)

    try:
        channels = discord_get(f"/guilds/{guild_id}/channels", token)
        channel_count = len(channels)
    except Exception:
        channel_count = None

    return {
        "name":          guild["name"],
        "member_count":  guild.get("approximate_member_count"),
        "online_count":  guild.get("approximate_presence_count"),
        "boost_count":   guild.get("premium_subscription_count", 0),
        "boost_tier":    guild.get("premium_tier", 0),
        "channel_count": channel_count,
        "role_count":    len(guild.get("roles", [])),
    }



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",       action="store_true", help="Print results without saving")
    parser.add_argument("--no-browser",    action="store_true", help="Skip auto-opening the report")
    parser.add_argument("--skip-if-today", action="store_true",
                        help="If already collected today, skip collection and just show latest")
    args = parser.parse_args()

    db_module.init_db()

    if args.skip_if_today and db_module.is_day_complete_today():
        print("Already collected today — showing latest snapshot.\n")
        latest = db_module.get_latest_per_guild()
        total_m = sum(r["member_count"] or 0 for r in latest)
        total_o = sum(r["online_count"]  or 0 for r in latest)
        for r in latest:
            print(f"  {r['name']}: {r['member_count']:,} members, "
                  f"{r['online_count']:,} online, "
                  f"Tier {r['boost_tier']} ({r['boost_count']} boosts)")
        print()

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "generate_report", SCRIPT_DIR / "generate_report.py"
        )
        rpt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rpt)
        report_path = rpt.build_report(open_browser=not args.no_browser)

        result = {
            "guilds": [
                f"{r['name']}: {r['member_count']:,} members | "
                f"{r['online_count']:,} online | "
                f"Tier {r['boost_tier']} ({r['boost_count']} boosts)"
                for r in latest
            ],
            "errors": [],
            "report_path": report_path or "",
            "total_members": total_m,
            "total_online": total_o,
            "already_today": True,
        }
        print(f"SNAPSHOT_RESULT: {json.dumps(result)}")
        return

    token = load_token()
    if not token:
        print("ERROR: BOT_TOKEN not found in .env or environment")
        sys.exit(1)

    guilds = db_module.get_active_guilds()
    if not guilds:
        print("No guilds tracked.")
        sys.exit(0)

    print(f"Collecting stats for {len(guilds)} guilds...\n")

    collected = {}
    errors    = []

    for g in guilds:
        guild_id = g["guild_id"]
        try:
            stats = fetch_guild_stats(guild_id, token)
            collected[guild_id] = stats
            print(
                f"  ✓  {stats['name']}: "
                f"{stats['member_count']:,} members, "
                f"{stats['online_count']:,} online, "
                f"Tier {stats['boost_tier']} ({stats['boost_count']} boosts)"
            )
            time.sleep(0.3)
        except urllib.error.HTTPError as e:
            msg = f"HTTP {e.code}: {e.reason}"
            errors.append(f"{g['name']} ({guild_id}): {msg}")
            print(f"  ✗  {g['name']}: {msg}")
        except Exception as e:
            errors.append(f"{g['name']} ({guild_id}): {e}")
            print(f"  ✗  {g['name']}: {e}")

    print()

    if args.dry_run:
        print("Dry run — not saving.")
        sys.exit(0)

    if not collected:
        result = {"guilds": [], "errors": errors, "report_path": "",
                  "total_members": 0, "total_online": 0}
        print(f"SNAPSHOT_RESULT: {json.dumps(result)}")
        sys.exit(0)

    for guild_id, stats in collected.items():
        db_module.upsert_guild(guild_id, stats["name"])
        db_module.save_snapshot(guild_id, stats)

    print(f"Snapshot saved: {len(collected)} guilds.")

    print("Generating report...")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "generate_report", SCRIPT_DIR / "generate_report.py"
    )
    rpt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpt)
    report_path = rpt.build_report(open_browser=not args.no_browser)

    total_members = sum((s["member_count"] or 0) for s in collected.values())
    total_online  = sum((s["online_count"]  or 0) for s in collected.values())

    result = {
        "guilds": [
            f"{s['name']}: {s['member_count']:,} members | "
            f"{s['online_count']:,} online | "
            f"Tier {s['boost_tier']} ({s['boost_count']} boosts)"
            for s in collected.values()
        ],
        "errors":        errors,
        "report_path":   report_path or "",
        "total_members": total_members,
        "total_online":  total_online,
        "coverage":      db_module.today_coverage(),
    }
    print(f"SNAPSHOT_RESULT: {json.dumps(result)}")


if __name__ == "__main__":
    main()
