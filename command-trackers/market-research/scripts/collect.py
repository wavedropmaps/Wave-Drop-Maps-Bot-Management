#!/usr/bin/env python3
"""
Collect live member/online counts for competitor improvement cord servers.
Uses Discord's public invite API — no browser, no Playwright, no joining.

Usage:
    python collect.py
    python collect.py --dry-run
    python collect.py --no-browser
    python collect.py --skip-if-today
"""

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import db as db_module

DISCORD_API = "https://discord.com/api/v9/invites/{}?with_counts=true"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def extract_invite_code(invite_url: str):
    """Extract the invite code from a discord.gg or discord.com/invite URL."""
    m = re.search(r'discord(?:\.gg|\.com/invite)/([^/?#\s]+)', invite_url)
    return m.group(1) if m else None


def fetch_server_stats(server: dict):
    """Returns (stats_dict, None) on success or (None, error_str) on failure."""
    invite_url = server["invite"]
    code = extract_invite_code(invite_url)

    if not code:
        return None, f"no Discord invite code in URL: {invite_url}"

    url = DISCORD_API.format(code)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        members = data.get("approximate_member_count")
        online  = data.get("approximate_presence_count")

        if members is None:
            return None, "API returned no member count"

        guild_name = data.get("guild", {}).get("name", "")
        return {"member_count": members, "online_count": online, "guild_name": guild_name}, None

    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "invite invalid or expired (404)"
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)


def collect_all(servers):
    results = {}
    errors  = []

    for s in servers:
        print(f"  → {s['name']}…", end=" ", flush=True)
        stats, err = fetch_server_stats(s)
        if stats:
            results[s["key"]] = stats
            m = stats["member_count"]
            o = stats["online_count"] or 0
            guild_name = stats.get("guild_name", "")
            extra = f" [guild: {guild_name}]" if guild_name and guild_name.lower() != s["name"].lower() else ""
            print(f"{m:,} members, {o:,} online{extra}")
        else:
            errors.append(f"{s['name']}: {err}")
            print(f"failed — {err}")
        time.sleep(0.3)

    return results, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--no-browser",    action="store_true")
    parser.add_argument("--skip-if-today", action="store_true")
    args = parser.parse_args()

    db_module.init_db()

    if args.skip_if_today and db_module.already_collected_today():
        print("Already collected today — showing latest snapshot.\n")
        latest = db_module.get_latest_per_server()
        for r in latest:
            m = r["member_count"] or 0
            o = r["online_count"]  or 0
            print(f"  {r['name']}: {m:,} members, {o:,} online")
        print()

        spec = importlib.util.spec_from_file_location("generate_report", SCRIPT_DIR / "generate_report.py")
        rpt  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rpt)
        report_path = rpt.build_report(open_browser=not args.no_browser)

        total_m = sum(r["member_count"] or 0 for r in latest)
        total_o = sum(r["online_count"]  or 0 for r in latest)
        result  = {
            "servers":       [f"{r['name']}: {r['member_count'] or 0:,} members | {r['online_count'] or 0:,} online" for r in latest],
            "errors":        [],
            "report_path":   report_path or "",
            "total_members": total_m,
            "total_online":  total_o,
            "already_today": True,
        }
        print(f"SNAPSHOT_RESULT: {json.dumps(result)}")
        return

    servers = db_module.get_active_servers()
    if not servers:
        print("No servers configured.")
        sys.exit(0)

    print(f"Collecting stats for {len(servers)} servers via Discord API…\n")
    results, errors = collect_all(servers)
    print()

    if args.dry_run:
        print("Dry run — not saving.")
        sys.exit(0)

    if not results:
        result = {"servers": [], "errors": errors, "report_path": "", "total_members": 0, "total_online": 0}
        print(f"SNAPSHOT_RESULT: {json.dumps(result)}")
        sys.exit(0)

    snapshot_for_pred = {key: {"member_count": s["member_count"]} for key, s in results.items()}
    db_module.check_and_resolve_predictions(snapshot_for_pred)

    for key, stats in results.items():
        db_module.save_snapshot(key, stats["member_count"], stats["online_count"])
        db_module.record_success(key)

    db_module.maybe_create_predictions(snapshot_for_pred)

    deactivated = []
    for s in servers:
        if s["key"] not in results:
            fails = db_module.record_fail(s["key"])
            if fails >= db_module.CONSECUTIVE_FAIL_LIMIT and s["key"] != "wave":
                db_module.deactivate_server(s["key"])
                deactivated.append(s["name"])
                print(f"  ✗  {s['name']} removed after {fails} consecutive failures.")

    if deactivated:
        errors.append(f"Auto-removed ({', '.join(deactivated)}) after {db_module.CONSECUTIVE_FAIL_LIMIT} consecutive failures.")

    print(f"Snapshot saved: {len(results)} servers.")

    print("Generating report…")
    spec = importlib.util.spec_from_file_location("generate_report", SCRIPT_DIR / "generate_report.py")
    rpt  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpt)
    report_path = rpt.build_report(open_browser=not args.no_browser)

    latest  = db_module.get_latest_per_server()
    total_m = sum(r["member_count"] or 0 for r in latest)
    total_o = sum(r["online_count"]  or 0 for r in latest)

    result = {
        "servers":       [f"{r['name']}: {r['member_count'] or 0:,} members | {r['online_count'] or 0:,} online" for r in latest],
        "errors":        errors,
        "report_path":   report_path or "",
        "total_members": total_m,
        "total_online":  total_o,
        "coverage":      db_module.today_coverage(),
    }
    print(f"SNAPSHOT_RESULT: {json.dumps(result)}")


if __name__ == "__main__":
    main()
