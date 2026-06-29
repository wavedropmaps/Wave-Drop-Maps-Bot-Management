"""
One-off backfill: reconstruct the lost 14/06/2026 -> 21/06/2026 week and inject
it into website/data/duties.json `weeks[]` so it shows in the past-weeks dropdown.

That week's live block was overwritten before week-history snapshotting existed,
but its raw counts survive in the `user_stats` cache and reviews survive in
`bot_logs`. We rebuild the snapshot using the EXACT same shape + rank formula as
tasks/unified_weekly_loop.py::_build_unified_hub_payload, pulling per-user meta
(name/top_role/avatar/away) from the current duties.json (same staff).

Run with the bot/web server up or down — it only touches files + reads the DB.
  python migrations/backfill_week_14_06_2026.py            # dry-run (preview)
  python migrations/backfill_week_14_06_2026.py --commit    # write it
"""

import os
import sys
import json
import math
import sqlite3
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.helpers import get_start_datetime, get_end_datetime  # noqa: E402

START = '14/06/2026'
END = '21/06/2026'
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'bot_database.db')
DUTIES_PATH = os.path.join(os.path.dirname(__file__), '..', 'website', 'data', 'duties.json')

REQ_THRESHOLDS = [(41, 'Great', '\U0001f31f'), (21, 'Very Good', '⭐'),
                  (10, 'Good', '✅'), (5, 'Okay', '⚠️'), (0, 'Bad', '❌')]


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _count(v):
    return v.get('count', 0) if isinstance(v, dict) else int(v or 0)


def main():
    commit = '--commit' in sys.argv
    conn = sqlite3.connect(DB_PATH)

    # 1. Cached duty counts for the week, merged across guilds the SAME way the
    #    live scan did: SUM counts across guilds, UNION the active-day strings.
    #    (user_stats holds one row per guild; the live board summed them.)
    stats = {'req': {}, 'modlog': {}, 'message': {}}
    rows = conn.execute(
        "SELECT user_id, check_type, data FROM user_stats WHERE start_date=? AND end_date=?",
        (START, END),
    ).fetchall()
    for uid, ct, data_json in rows:
        if ct not in stats:
            continue
        try:
            data = json.loads(data_json)
        except (TypeError, json.JSONDecodeError):
            continue
        key = int(uid)
        bucket = stats[ct].setdefault(key, {'count': 0, 'days': set()})
        bucket['count'] += _count(data)
        if isinstance(data, dict):
            for d in data.get('days', []):
                bucket['days'].add(d)
    # Convert day sets to lists so downstream code (which iterates 'days') works.
    for ct in stats:
        for key, b in stats[ct].items():
            b['days'] = sorted(b['days'])

    # 2. Reviews from bot_logs in the week window (persistent log).
    sdt, edt = get_start_datetime(START), get_end_datetime(END)
    reviews = {}
    for (aj,) in conn.execute(
        "SELECT actor_json FROM bot_logs WHERE category='hitl_review' "
        "AND action='review_completed' AND timestamp>=? AND timestamp<?",
        (_iso_z(sdt), _iso_z(edt)),
    ).fetchall():
        if not aj:
            continue
        try:
            uid = int(json.loads(aj).get('id'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        reviews[uid] = reviews.get(uid, 0) + 1
    conn.close()

    # 3. Per-user meta from the current duties.json (same staff roster).
    with open(DUTIES_PATH, 'r', encoding='utf-8') as f:
        duties = json.load(f)
    cur_users = duties.get('users', {})

    general_ids = set(stats['message'].keys()) | set(stats['modlog'].keys())
    req_ids = set(stats['req'].keys())
    all_ids = general_ids | req_ids

    # req positions: away last, then count desc (mirrors _positions)
    req_entries = sorted(
        [(uid, _count(stats['req'].get(uid, 0)), bool(cur_users.get(str(uid), {}).get('is_away')))
         for uid in req_ids],
        key=lambda e: (e[2], -e[1]),
    )
    req_pos = {uid: (i + 1, len(req_entries)) for i, (uid, _, _) in enumerate(req_entries)}

    users = {}
    for uid in all_ids:
        cu = cur_users.get(str(uid), {})
        entry = {
            'user_id': str(uid),
            'name': cu.get('name', f'User {uid}'),
            'top_role': cu.get('top_role', 'Trial Staff'),
            'role_tier': cu.get('role_tier', 'trial'),
            'avatar_url': cu.get('avatar_url'),
            'is_away': bool(cu.get('is_away')),
        }
        if cu.get('away_type'):
            entry['away_type'] = cu['away_type']

        if uid in req_ids:
            c = _count(stats['req'].get(uid, 0))
            label, emoji = 'Bad', '❌'
            for th, l, e in REQ_THRESHOLDS:
                if c >= th:
                    label, emoji = l, e
                    break
            pos, total = req_pos.get(uid, (0, 0))
            entry['duties'] = {'req': {
                'count': c, 'rank': label, 'rank_emoji': emoji,
                'position': pos, 'total_in_duty': total,
                'wp_earned': 0, 'penalty_amount': 0, 'role_removed': False,
            }}

        if uid in general_ids:
            mraw = stats['message'].get(uid, 0)
            messages = _count(mraw)
            days_set = set()
            if isinstance(mraw, dict):
                for d in mraw.get('days', []):
                    try:
                        days_set.add(datetime.fromisoformat(d).date().weekday() if isinstance(d, str) else d)
                    except Exception:
                        pass
            days_active = len(days_set)
            mod = _count(stats['modlog'].get(uid, 0))
            rev = int(reviews.get(uid, 0))
            rank_messages = min(math.ceil(messages / 70 * 100), 100)
            rank_days = min(math.ceil(days_active / 7 * 100), 100)
            rank_total = min(math.ceil((rank_messages + rank_days) / 2 + mod + rev), 100)
            entry['engagement'] = {
                'messages': messages, 'days_active': days_active,
                'mod_commands': mod, 'reviews': rev,
                'rank_messages': rank_messages, 'rank_days': rank_days, 'rank_total': rank_total,
            }
        users[str(uid)] = entry

    snapshot = {
        '_meta': {'start_date': START, 'end_date': END,
                  'last_updated': datetime.now(timezone.utc).isoformat(), 'period': 'Full Week'},
        'users': users,
    }

    print(f"Rebuilt {START} -> {END}: {len(users)} users "
          f"({len(general_ids)} general, {len(req_ids)} req, {sum(reviews.values())} reviews)")
    sample = sorted(users.values(), key=lambda u: u.get('engagement', {}).get('messages', 0), reverse=True)[:5]
    for u in sample:
        eng = u.get('engagement', {})
        print(f"  {u['name']}: msg={eng.get('messages')} mod={eng.get('mod_commands')} "
              f"rev={eng.get('reviews')} rank={eng.get('rank_total')}")

    if not commit:
        print("\nDRY RUN — no changes written. Re-run with --commit to inject into weeks[].")
        return

    weeks = [w for w in duties.get('weeks', []) if w.get('_meta', {}).get('start_date') != START]
    weeks.insert(0, snapshot)
    duties['weeks'] = weeks[:8]
    with open(DUTIES_PATH, 'w', encoding='utf-8') as f:
        json.dump(duties, f, ensure_ascii=False)
    print(f"\n✅ Injected {START} into weeks[] ({len(duties['weeks'])} weeks total). "
          f"Refresh the Weekly page — the past-week pill should appear.")


if __name__ == '__main__':
    main()
