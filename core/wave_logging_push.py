"""
core/wave_logging_push.py — Wave-Logging dashboard publisher (LOCAL ONLY).

Drains unpushed rows from the `bot_logs` table, assembles them into the exact delta /
rolled-up / manifest layout the dashboard (`wave_logging_site/assets/script.js`) reads,
writes them to the local mirror (wave_logging_local/data/), then marks the rows pushed.
The local mirror is served by Flask at /logging/data/ and fronted by
wave-logging.pages.dev (Management role-gated). GitHub push RETIRED 2026-06-14.

Layout the site expects (verified against script.js fetchEventsForCategory):
  • today:    data/<bot>/<category>/<YYYY-MM-DD>/<HHMMSS>.json   = {pushed_at, events:[...]}
              data/<bot>/<category>/<YYYY-MM-DD>/_manifest.json  = {day, files:[...], updated_at}
  • past day: data/<bot>/<category>/<YYYY-MM-DD>.json            = {events:[...]}  (rolled up)
Events drop the internal `id` (kept only to mark_pushed). `<bot>` = BOT_NAME ("manager").

assemble_files() is a PURE function (no IO) so it can be unit-tested without touching
the DB. push_unpushed_events() does the real fetch → write-local-mirror → mark_pushed
cycle and is called by the wave_logging cog's loop.
"""

import os
import json
import base64
import logging
from datetime import datetime, timezone
from collections import defaultdict
from typing import Optional, List, Tuple, Dict, Any

import aiohttp

from core.global_logger import fetch_unpushed, mark_pushed, BOT_NAME

logger = logging.getLogger("discord")

GITHUB_API = "https://api.github.com"
LOCAL_ROOT = os.path.join("wave_logging_local", "data")  # local mirror of what we publish


def _utc_now():
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _day_of(ts: str) -> str:
    """'YYYY-MM-DD' from an ISO timestamp string (events store ...Z)."""
    return (ts or "")[:10]


def _strip_id(event: dict) -> dict:
    return {k: v for k, v in event.items() if k != "id"}


def assemble_files(events: List[dict], now: datetime,
                   existing_manifests: Dict[str, dict] = None,
                   existing_rolled: Dict[str, dict] = None) -> List[Tuple[str, dict]]:
    """
    PURE: turn a batch of unpushed events into a list of (relative_path, json_obj)
    files to write/push. `relative_path` is under data/ (e.g. "manager/loot_routes/2026-06-07/120000.json").

    existing_manifests: {rel_dir: manifest_dict} for today's dirs already on disk/repo.
    existing_rolled:    {rel_path: rolled_dict} for past-day rolled files already present.
    Both let us append rather than overwrite. Missing → created fresh.
    """
    existing_manifests = existing_manifests or {}
    existing_rolled = existing_rolled or {}
    section = BOT_NAME
    today = now.strftime("%Y-%m-%d")
    hms = now.strftime("%H%M%S")
    pushed_iso = _iso_z(now)

    groups: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for e in events:
        groups[(e.get("category", "uncategorized"), _day_of(e.get("timestamp", "")))].append(e)

    out: List[Tuple[str, dict]] = []
    for (category, day), evs in sorted(groups.items()):
        clean = [_strip_id(e) for e in evs]
        if day == today:
            rel_dir = f"{section}/{category}/{day}"
            fname = f"{hms}.json"
            out.append((f"{rel_dir}/{fname}", {"pushed_at": pushed_iso, "events": clean}))
            manifest = dict(existing_manifests.get(rel_dir) or {"day": day, "files": []})
            files = list(manifest.get("files", []))
            if fname not in files:
                files.append(fname)
            manifest["day"] = day
            manifest["files"] = sorted(set(files))
            manifest["updated_at"] = pushed_iso
            out.append((f"{rel_dir}/_manifest.json", manifest))
        else:
            rel_path = f"{section}/{category}/{day}.json"
            rolled = dict(existing_rolled.get(rel_path) or {"events": []})
            rolled["events"] = list(rolled.get("events", [])) + clean
            out.append((rel_path, rolled))
    return out


# ──────────────────────── local mirror helpers ────────────────────────
def _local_path(rel: str) -> str:
    return os.path.join(LOCAL_ROOT, *rel.split("/"))


def _read_local_json(rel: str) -> Optional[dict]:
    p = _local_path(rel)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _write_local_json(rel: str, obj: dict):
    p = _local_path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _load_existing_context(events: List[dict], now: datetime):
    """Read any existing manifests (today) / rolled files (past days) from the local mirror."""
    section = BOT_NAME
    today = now.strftime("%Y-%m-%d")
    manifests, rolled = {}, {}
    seen_dirs, seen_rolled = set(), set()
    for e in events:
        cat = e.get("category", "uncategorized")
        day = _day_of(e.get("timestamp", ""))
        if day == today:
            rel_dir = f"{section}/{cat}/{day}"
            if rel_dir not in seen_dirs:
                seen_dirs.add(rel_dir)
                m = _read_local_json(f"{rel_dir}/_manifest.json")
                if m:
                    manifests[rel_dir] = m
        else:
            rel_path = f"{section}/{cat}/{day}.json"
            if rel_path not in seen_rolled:
                seen_rolled.add(rel_path)
                r = _read_local_json(rel_path)
                if r:
                    rolled[rel_path] = r
    return manifests, rolled


# ── GitHub push RETIRED 2026-06-14 ──────────────────────────────────────────
# The Wave-Logging dashboard now reads the LOCAL mirror (wave_logging_local/data/)
# served by Flask at /logging/data/, fronted by wave-logging.pages.dev (Management
# role-gated). The old Contents-API push (_load_github_cfg / _gh_put) was removed.


async def push_unpushed_events(bot=None) -> int:
    """
    Drain bot_logs → write the LOCAL mirror (read by the Wave-Logging dashboard at
    wave-logging.pages.dev via Flask /logging/data/) → mark_pushed.
    GitHub push retired 2026-06-14. Returns events written this cycle. Never raises.
    """
    events = await fetch_unpushed(limit=5000)
    if not events:
        return 0

    now = _utc_now()
    manifests, rolled = _load_existing_context(events, now)
    files = assemble_files(events, now, existing_manifests=manifests, existing_rolled=rolled)
    pushed_ids = [e["id"] for e in events if "id" in e]

    # Write the LOCAL mirror (served by the dashboard at wave-logging.pages.dev via
    # Flask /logging/data/). GitHub push retired 2026-06-14. mark_pushed only if ALL
    # writes succeed (else retry next cycle).
    all_ok = True
    for rel, obj in files:
        try:
            _write_local_json(rel, obj)
        except Exception as e:
            all_ok = False
            logger.warning(f"[wave_logging_push] local mirror write failed for {rel}: {e}")

    if all_ok:
        await mark_pushed(pushed_ids)
        logger.info(f"[wave_logging_push] wrote {len(pushed_ids)} event(s) across {len(files)} file(s) (local)")
        return len(pushed_ids)

    logger.error("[wave_logging_push] some local writes failed — NOT marking pushed (will retry next cycle)")
    return 0
