"""One-shot headless duties board refresh (no Discord login). Safe while bot is running."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import database
from tasks.unified_weekly_loop import (
    refresh_duties_hub_from_cache,
    get_global_dates_from_config,
    _duties_json_path,
)


class _HeadlessBot:
    guilds = []

    def get_guild(self, _guild_id):
        return None


async def main():
    await database.init_database()
    before = {}
    try:
        with open(_duties_json_path(), 'r', encoding='utf-8') as f:
            before = json.load(f).get('_meta', {})
    except Exception:
        pass
    cfg_start, cfg_end = get_global_dates_from_config()
    print(f"Config week: {cfg_start} -> {cfg_end}")
    print(f"Before:      {before.get('start_date')} -> {before.get('end_date')}")
    ok = await refresh_duties_hub_from_cache(_HeadlessBot())
    with open(_duties_json_path(), 'r', encoding='utf-8') as f:
        after = json.load(f)
    meta = after.get('_meta', {})
    print(f"After:       {meta.get('start_date')} -> {meta.get('end_date')} ({len(after.get('users', {}))} users)")
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
