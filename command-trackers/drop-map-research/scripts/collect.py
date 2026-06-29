#!/usr/bin/env python3
"""
Collect Discord member counts for all tracked servers using Playwright.
Reads servers from the DB, scrapes discord.com/servers, saves snapshot.

Usage:
    python collect.py
    python collect.py --dry-run      # print results without saving
    python collect.py --no-browser   # skip auto-opening the report (for bot use)
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

# Force UTF-8 stdout so Windows cp1252 doesn't choke on ✓/✗
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(SKILL_ROOT, "scripts"))

import db as db_module

# Load bot token for guild-preview API calls
def _load_bot_token():
    import pathlib
    env_path = pathlib.Path(__file__).parent.parent.parent.parent / ".env"
    if not env_path.exists():
        # try backup
        backups = sorted((pathlib.Path(__file__).parent.parent.parent.parent / "database_backups").glob("*/.env"))
        env_path = backups[-1] if backups else None
    if env_path:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None

_BOT_TOKEN = _load_bot_token()


def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("Playwright not installed. Run: pip install playwright")
        sys.exit(1)

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
    except Exception as e:
        if "Executable doesn't exist" in str(e):
            print("Chromium not downloaded yet. Installing now...")
            import subprocess
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        else:
            raise


def parse_num(s):
    return int(re.sub(r"[^\d]", "", s)) if s else 0


def name_matches(result_name, target_name):
    STOP = {"the", "a", "an", "and", "or", "of", "&"}

    def sig_words(name):
        return set(re.sub(r"[^a-z0-9 ]", "", name.lower()).split()) - STOP

    target_words = sig_words(target_name)
    result_words = sig_words(result_name)

    if not target_words:
        return False

    overlap = len(target_words & result_words)
    needed = max(1, len(target_words) - 1)

    if overlap < needed:
        return False

    extra = result_words - target_words
    if extra and len(target_words) <= 3:
        return False

    return True


def parse_cards(page_text):
    body = page_text.split("Heads up")[0]
    results = []
    pattern = re.compile(r"([^\n]+)\n[^\n]+\n([\d,]+)\nOnline\n([\d,]+)\nMembers")
    for m in pattern.finditer(body):
        name    = m.group(1).strip().rstrip("!")
        online  = parse_num(m.group(2))
        members = parse_num(m.group(3))
        if members > 0:
            results.append((name, members, online))
    return results


def fetch_via_guild_id(guild_id):
    """Use Discord's guild preview API with bot token — works for Community/discoverable guilds."""
    if not _BOT_TOKEN:
        return None
    url = f"https://discord.com/api/v10/guilds/{guild_id}/preview"
    headers = {
        "User-Agent": "DiscordBot (https://example.com, 1.0)",
        "Authorization": f"Bot {_BOT_TOKEN}",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        members = data.get("approximate_member_count")
        online  = data.get("approximate_presence_count")
        if members:
            return {"members": members, "online": online or 0}
    except Exception as e:
        print(f"    guild preview API error: {e}")
    return None


def fetch_via_invite(invite_code):
    """Use Discord's public invite API — no auth needed, returns member+online counts."""
    url = f"https://discord.com/api/v9/invites/{invite_code}?with_counts=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        members = data.get("approximate_member_count")
        online  = data.get("approximate_presence_count")
        if members:
            return {"members": members, "online": online or 0}
    except Exception as e:
        print(f"    invite API error: {e}")
    return None


def scrape_servers(servers):
    from playwright.sync_api import sync_playwright

    found = {}
    not_found = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        for idx, (name, query) in enumerate(servers):
            # Longer initial pause + extra pause every 3 servers to avoid Discord rate limiting
            if idx == 0:
                time.sleep(3)
            elif idx % 3 == 0:
                time.sleep(5)

            url = f"https://discord.com/servers?query={query.replace(' ', '+')}"
            result = None
            last_error = None

            for attempt in range(3):
                try:
                    page.goto(url, wait_until="networkidle", timeout=40000)
                    time.sleep(3)
                    result = page.inner_text("body")
                    break
                except Exception as e:
                    last_error = e
                    if attempt < 2:
                        time.sleep(6)

            if result is None:
                not_found.append((name, f"error: {last_error}"))
                time.sleep(4)
                continue

            if "0 RESULTS FOUND" in result or "NO RESULTS FOUND" in result:
                not_found.append((name, "not on Discord Discovery"))
                time.sleep(3)
                continue

            cards = parse_cards(result)
            match = None
            for rank, (card_name, members, online) in enumerate(cards, 1):
                if name_matches(card_name, name):
                    match = (card_name, members, online, rank)
                    break

            if match:
                card_name, members, online, rank = match
                found[name] = {"members": members, "online": online, "discovery_rank": rank}
                label = f"  (matched '{card_name}')" if card_name.lower() != name.lower() else ""
                print(f"  ✓  {name}: {members:,} members, {online:,} online{label}")
            else:
                top = cards[0][0] if cards else "?"
                not_found.append((name, f"no match (top result: '{top}')"))

            time.sleep(3)

        browser.close()

    return found, not_found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",    action="store_true", help="Print results without saving")
    parser.add_argument("--no-browser", action="store_true", help="Skip auto-opening the HTML report")
    args = parser.parse_args()

    db_module.init_db()

    import sqlite3
    conn = sqlite3.connect(db_module.DB_PATH)
    rows = conn.execute(
        "SELECT name, search_query, invite_code, guild_id FROM servers WHERE active = 1 ORDER BY name"
    ).fetchall()
    conn.close()

    if not rows:
        print("No servers tracked. Add some with: manage_servers.py add \"Server Name\"")
        sys.exit(0)

    print(f"Collecting data for {len(rows)} servers...\n")

    found = {}
    not_found = []

    # ── Phase 1: guild-id servers (bot token preview API) ───────────────────
    guild_rows   = [(r[0], r[3]) for r in rows if r[3]]
    invite_rows  = [(r[0], r[2]) for r in rows if r[2] and not r[3]]
    discovery_rows = [(r[0], r[1]) for r in rows if not r[2] and not r[3]]

    if guild_rows:
        print(f"  [guild preview API] {len(guild_rows)} server(s)...")
        for name, gid in guild_rows:
            result = fetch_via_guild_id(gid)
            if result:
                found[name] = result
                print(f"  ✓  {name}: {result['members']:,} members, {result['online']:,} online  (guild)")
            else:
                not_found.append((name, "guild preview API returned no data"))
                print(f"  ✗  {name}: guild preview API failed")
            time.sleep(0.3)
        print()

    # ── Phase 2: invite-code servers (fast, no browser needed) ──────────────
    if invite_rows:
        print(f"  [invite API] {len(invite_rows)} server(s)...")
        for name, code in invite_rows:
            result = fetch_via_invite(code)
            if result:
                found[name] = result
                print(f"  ✓  {name}: {result['members']:,} members, {result['online']:,} online  (invite)")
            else:
                not_found.append((name, "invite API returned no data"))
                print(f"  ✗  {name}: invite API failed")
            time.sleep(0.5)
        print()

    # ── Phase 3: Discovery scrape for the rest ───────────────────────────────
    if discovery_rows:
        print(f"  [Discord Discovery] {len(discovery_rows)} server(s)...")
        ensure_playwright()
        disc_found, disc_not_found = scrape_servers(discovery_rows)
        found.update(disc_found)
        not_found.extend(disc_not_found)

    print()
    if not_found:
        print(f"Not found ({len(not_found)}):")
        for name, reason in not_found:
            print(f"  ✗  {name}: {reason}")
        print()

    if not found:
        print("No servers found — nothing to save.")
        result = {"found": [], "not_found": [f"{n}: {r}" for n, r in not_found], "report_path": ""}
        print(f"SNAPSHOT_RESULT: {json.dumps(result)}")
        sys.exit(0)

    if args.dry_run:
        print("Dry run — not saving.")
        print(json.dumps(found, indent=2))
        sys.exit(0)

    db_module.save_snapshot(found)
    db_module.check_and_resolve_predictions(found)
    db_module.maybe_create_predictions(found)

    print(f"\nSnapshot saved: {len(found)} servers collected.")

    print("Generating report...")
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "generate_report",
        pathlib.Path(__file__).parent / "generate_report.py"
    )
    rpt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rpt)
    report_path = rpt.build_report(open_browser=not args.no_browser)

    result = {
        "found":     [f"{name}: {data['members']:,} members, {data['online']:,} online" for name, data in found.items()],
        "not_found": [f"{name}: {reason}" for name, reason in not_found],
        "report_path": report_path or "",
        "coverage":  db_module.today_coverage(),
    }
    print(f"SNAPSHOT_RESULT: {json.dumps(result)}")


if __name__ == "__main__":
    main()
