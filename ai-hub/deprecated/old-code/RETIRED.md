# Retired Code — duties_scan.py + weekly_checks.py

These files were consolidated into **`tasks/unified_weekly_loop.py`** on 2026-06-22.

| Old file | Role | Now in |
|---|---|---|
| `duties_scan.py` | 4-hour scanner + hub payload builder | `unified_weekly_loop.py` |
| `weekly_checks.py` | 72h/168h awards engine + role monitor | `unified_weekly_loop.py` |

**Spec:** `ai-hub/plans/unified_weekly_loop_specification.md` (v2)

## What changed
- Cadence: every 4h + 72h/168h → **every hour** (incremental scan)
- Mid-week warnings: **removed**
- Role monitor (30-min loop): **folded into hourly scan**
- Rank-100 engagement reward: 10 WP → **30 WP**
- `weeks[]` history snapshot: **removed** (site does file-stats)
- VBucks leaderboard update: **removed**

## What stayed the same
- `rank_total` formula: `(rank_messages+rank_days)/2 + mod + reviews`, cap 100
- Map Request placement awards (150/100 WP)
- Bad penalty (-200 WP or role removal)
- Away + new-staff (<4 days) immunity
- Modlog channel-embed scan method
- `duties.json` schema for website
