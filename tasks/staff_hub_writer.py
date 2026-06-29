"""
staff_hub_writer.py — Wave Staff Hub LOCAL payload writer.

⚠️ GitHub push RETIRED 2026-06-14. This module no longer talks to GitHub at all.
The Wave Staff Hub is served entirely from this PC (Flask + Cloudflare tunnel,
https://wavedropmaps.pages.dev), reading the JSON files this module writes into
website/data/. The historic `push_*_to_github` names are kept ONLY so the ~18
existing callers across tasks/ and commands/ keep working unchanged — each now
simply writes the payload locally.

How the old GitHub sync worked (config, Contents API, per-file builders, the
github.io Pages site) is archived in:
  ai-hub/deprecated/HOW_STAFF_HUB_GITHUB_SYNC_WORKED.md
The full original code is recoverable from git history (commit before 2026-06-14).

NOTE: core/wave_logging_push.py is a SEPARATE system (the Wave-Logging dashboard,
a different repo) and still uses GitHub — it is NOT affected by this module.
"""

import os
import json
import logging
from pathlib import Path
from core.helpers import web_avatar_url

logger = logging.getLogger('discord')

# website/data/ — the Staff Hub's live data dir (Flask serves it at /api/<page>).
_WEBSITE_DATA_DIR = Path(__file__).resolve().parent.parent / 'website' / 'data'

# Maps old GitHub JSON filenames -> local Staff Hub data filenames (for the
# replace_json_on_github reset helper, which is called with GitHub-style names).
_GITHUB_TO_LOCAL = {
    'loot_routes_leaderboard.json': 'loot.json',
    'surge_routes_leaderboard.json': 'surge.json',
    'duties_totals.json': 'duties.json',
    'vbucks_leaderboard.json': 'vbucks.json',
    'economy_data.json': 'economy.json',
    'tips_tricks_leaderboard.json': 'tips.json',

    'daily_summary.json': 'daily_summary.json',
    'session_history.json': 'session_history.json',
}


def write_local_payload(filename: str, payload: dict) -> None:
    """Atomically write a Staff Hub payload to website/data/<filename>.
    Never raises into the caller."""
    try:
        _WEBSITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        dst = _WEBSITE_DATA_DIR / filename
        tmp = dst.with_suffix(dst.suffix + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        os.replace(tmp, dst)
        logger.debug(f"  💾 [Staff Hub] wrote website/data/{filename}")
    except Exception as e:
        logger.warning(f"⚠️ [Staff Hub] Could not write local payload {filename}: {e}")


# ── Per-page writers (names preserved for existing callers) ──────────────────

async def push_duties_to_github(duties_data: dict):
    write_local_payload('duties.json', duties_data)
    return True


async def push_vbucks_leaderboard_to_github(vbucks_data: dict) -> bool:
    write_local_payload('vbucks.json', vbucks_data)
    return True


async def push_daily_summary_to_github(summary_data: dict) -> bool:
    write_local_payload('daily_summary.json', summary_data)
    return True


async def push_session_history_to_github(session_data: dict) -> bool:
    """Append ONE session to the local session_history.json (the page reads
    {sessions:[...]}). Mirrors the old append-to-GitHub behaviour, locally."""
    try:
        sh_path = _WEBSITE_DATA_DIR / 'session_history.json'
        local = {"sessions": []}
        if sh_path.exists():
            with open(sh_path, 'r', encoding='utf-8') as f:
                local = json.load(f)
        local.setdefault('sessions', []).append(session_data)
        _WEBSITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = sh_path.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(local, f)
        os.replace(tmp, sh_path)
        return True
    except Exception as e:
        logger.warning(f"⚠️ [Staff Hub] session_history local append failed: {e}")
        return False


async def replace_json_on_github(filename: str, content: dict) -> bool:
    """Overwrite/reset a Staff Hub data file (used by the reviewing reset cmd).
    Maps the old GitHub filename to the local website/data file."""
    local = _GITHUB_TO_LOCAL.get(filename, filename)
    write_local_payload(local, content)
    return True


async def push_loot_route_leaderboard_to_github(leaderboard_data: dict) -> bool:
    write_local_payload('loot.json', leaderboard_data)
    return True


async def push_surge_route_leaderboard_to_github(leaderboard_data: dict) -> bool:
    write_local_payload('surge.json', leaderboard_data)
    return True


async def push_economy_dashboard_to_github(economy_data: dict) -> bool:
    write_local_payload('economy.json', economy_data)
    return True


async def push_staff_sheet_to_github(staff_payload: dict, week_id: str) -> bool:
    """Write a week's staff sheet to website/staff_sheets/<week_id>.json (served
    statically) and refresh the local index."""
    try:
        wk_dir = _WEBSITE_DATA_DIR.parent / 'staff_sheets'
        wk_dir.mkdir(parents=True, exist_ok=True)
        wk_path = wk_dir / f'{week_id}.json'
        tmp = wk_path.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(staff_payload, f)
        os.replace(tmp, wk_path)
    except Exception as e:
        logger.warning(f"⚠️ [Staff Hub] staff sheet week file local write failed: {e}")
    return await update_staff_sheets_index(week_id, staff_payload.get('_meta', {}))


async def update_staff_sheets_index(week_id: str, week_meta: dict) -> bool:
    """Maintain website/staff_sheets_index.json: dedupe by id, sort newest→oldest,
    mark the top 4 isRecent."""
    from datetime import datetime
    new_entry = {"id": week_id}
    if week_meta.get('start_date') and week_meta.get('end_date'):
        new_entry['start_date'] = week_meta['start_date']
        new_entry['end_date'] = week_meta['end_date']
        try:
            sd = datetime.strptime(week_meta['start_date'], '%d/%m/%Y')
            ed = datetime.strptime(week_meta['end_date'], '%d/%m/%Y')
            new_entry['group'] = ed.strftime('%B %Y')
            if sd.month == ed.month:
                new_entry['label'] = f"{sd.strftime('%b')} {sd.day} - {ed.day}"
            else:
                new_entry['label'] = f"{sd.strftime('%b %d')} - {ed.strftime('%b %d')}"
            new_entry['_sort'] = ed.strftime('%Y%m%d')
        except Exception:
            new_entry['group'] = 'Archive'
            new_entry['label'] = week_id
    try:
        idx_path = _WEBSITE_DATA_DIR.parent / 'staff_sheets_index.json'
        local_index = []
        if idx_path.exists():
            with open(idx_path, 'r', encoding='utf-8') as f:
                parsed = json.load(f)
                if isinstance(parsed, list):
                    local_index = parsed
        local_index = [w for w in local_index if w.get('id') != week_id]
        local_index.append(dict(new_entry))
        local_index.sort(key=lambda w: w.get('_sort', ''), reverse=True)
        cleaned = []
        for i, w in enumerate(local_index):
            w = {k: v for k, v in w.items() if k != '_sort'}
            w['isRecent'] = (i < 4)
            cleaned.append(w)
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = idx_path.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cleaned, f, indent=2)
        os.replace(tmp, idx_path)
        return True
    except Exception as e:
        logger.warning(f"⚠️ [Staff Hub] staff_sheets_index local update failed: {e}")
        return False


async def push_events_to_github(events_data: dict) -> bool:
    write_local_payload('events.json', events_data)
    return True


async def push_tips_tricks_leaderboard_to_github(leaderboard_data: dict) -> bool:
    write_local_payload('tips.json', leaderboard_data)
    return True


STAFF_HUB_GUILD_ID = 1041450125391835186


async def push_team_hierarchy_to_hub(bot) -> bool:
    """Rebuild team_hierarchy.json via the hierarchy cache (canonical source).
    Kept for backwards-compat — callers unchanged; delegates to force_rebuild."""
    try:
        from tasks.hierarchy_cache import force_rebuild
        return await force_rebuild(bot)
    except Exception as e:
        logger.warning(f"⚠️ [Team] Failed to rebuild team hierarchy: {e}")
        return False


async def setup(bot):
    """Required setup function for bot extensions."""
    logger.info("✅ Staff Hub local payload writer loaded (GitHub sync retired)")
