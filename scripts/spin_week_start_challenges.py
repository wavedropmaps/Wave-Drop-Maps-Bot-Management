"""One-shot week-start challenge spin: deck pick, DB, website events.json, Discord announce."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / '.env')

import discord

import database
from tasks.random_challenges import (
    _challenge_row_dict,
    generate_week_start_challenges,
    get_challenges_for_phase,
    init_challenges_table,
    spin_week_start_challenges,
)


def _read_week_start() -> str:
    with open(ROOT / 'config.json', 'r', encoding='utf-8') as f:
        start = json.load(f).get('global_dates', {}).get('start_date')
    if not start:
        raise SystemExit('No global_dates.start_date in config.json')
    return start


async def _dry_run(week_start: str) -> None:
    challenges = await generate_week_start_challenges(week_start_str=week_start)
    print(f'DRY RUN — week {week_start} — {len(challenges)} challenge(s):\n')
    for i, ch in enumerate(challenges, 1):
        print(
            f"  {i}. {ch['duty']:8} | {ch.get('completion_mode', '?'):22} | "
            f"diff {ch['difficulty']} | target {ch['target']}"
        )
        desc = (ch.get('ai_description') or '').split('\n')[0]
        if desc:
            print(f"     {desc}")


async def _live_spin(week_start: str, force: bool) -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise SystemExit('BOT_TOKEN not set in .env')

    await database.init_database()
    await init_challenges_table()

    existing = await get_challenges_for_phase(week_start, 'week_start')
    if existing and not force:
        raise SystemExit(
            f'Week-start challenges already exist for {week_start} '
            f'({len(existing)} row(s)). Pass --force to replace.'
        )

    result_holder: dict = {'rows': None, 'error': None}

    class SpinClient(discord.Client):
        async def on_ready(self):
            try:
                rows = await spin_week_start_challenges(
                    self, week_start, replace=force,
                )
                result_holder['rows'] = rows
            except Exception as exc:
                result_holder['error'] = exc
            finally:
                await self.close()

    client = SpinClient(intents=discord.Intents.default())
    await client.login(token)
    await client.connect(reconnect=False)

    if result_holder['error']:
        raise result_holder['error']

    rows = result_holder['rows']
    if rows is None:
        raise SystemExit('Spin returned no rows (fire-once guard may have blocked).')

    print(f'\nSpun {len(rows)} week-start challenge(s) for {week_start}:\n')
    for i, row in enumerate(rows, 1):
        ch = _challenge_row_dict(row)
        print(
            f"  {i}. {ch['duty']:8} | {ch.get('completion_mode', '?'):22} | "
            f"diff {ch['difficulty']} | target {ch['target_count']}"
        )

    events_path = ROOT / 'website' / 'data' / 'events.json'
    if events_path.exists():
        data = json.loads(events_path.read_text(encoding='utf-8'))
        n = len(data.get('challenges', []))
        print(f'\nwebsite/data/events.json: {n} challenge(s), week_start={data.get("week_start")!r}')


def main():
    parser = argparse.ArgumentParser(description='Spin week-start weekly challenges')
    parser.add_argument(
        '--force', action='store_true',
        help='Replace existing week_start rows for this week before spinning',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Print generated challenges only (no DB, Discord, or website)',
    )
    args = parser.parse_args()
    week_start = _read_week_start()

    if args.dry_run:
        asyncio.run(_dry_run(week_start))
    else:
        asyncio.run(_live_spin(week_start, args.force))


if __name__ == '__main__':
    main()
