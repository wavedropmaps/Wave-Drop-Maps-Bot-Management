---
name: guild-stats
description: >
  Wave Discord guild stats tracker. Collects and displays member count, online count,
  boosts, boost tier, channel count, and role count for Wave's own servers
  (Wave Free Dropmaps! and Wave Improvement Cord!) using the Discord REST API.
  Scripts live in command-trackers/guild-stats/scripts/ inside the Wave Management Bot repo
  — tracked in git so data syncs across all machines.

  Use this skill whenever the user wants to check how the Wave servers are growing,
  run a guild stats snapshot, see current member or online counts, view server analytics,
  check boost levels, see server growth trends, open the stats dashboard, or asks
  anything about the Wave server member numbers. Trigger for guilddash equivalent too.
---

# Guild Stats

Tracks member counts and key stats for Wave's own Discord servers over time.
Run once a day to build history, then view HTML reports with growth charts and trends.

**Data lives in `command-trackers/guild-stats/data/`** — tracked in git, syncs via push/pull.

---

## Requirements

**Python 3** — on Windows use `python`, on Mac use `python3`.  
**BOT_TOKEN** in `.env` at the repo root (already there).

No Playwright needed — uses the Discord REST API directly.

---

## Scripts (all relative to bot repo root)

```
command-trackers/guild-stats/scripts/collect.py          — collect + save + report
command-trackers/guild-stats/scripts/generate_report.py  — report only
command-trackers/guild-stats/scripts/db.py               — DB setup (auto-called on first run)
```

---

## Commands

| What user says | Action |
|---|---|
| `/guild-stats` (no extra words) | **collect + report** — run immediately |
| "collect", "grab today's stats" | **collect + report** |
| "show stats", "already ran today" | **show latest** — skip collection |
| "generate report", "show charts" | **report only** |

**Default:** When invoked with `/guild-stats` alone, use `--skip-if-today` so it never double-collects on the same day. Just start — don't ask what to do.

---

## Collect (once a day)

```bash
# Mac — smart: skips collection if already ran today, just shows latest
python3 command-trackers/guild-stats/scripts/collect.py --no-browser --skip-if-today

# Mac — force fresh collect regardless
python3 command-trackers/guild-stats/scripts/collect.py --no-browser

# Windows
python command-trackers\guild-stats\scripts\collect.py --no-browser --skip-if-today
```

Parse the `SNAPSHOT_RESULT: {...}` JSON line from stdout:
- `guilds` — list of strings, one per server
- `total_members` / `total_online` — combined totals
- `report_path` — path to generated HTML report
- `already_today` — true if today's snapshot was reused (not a fresh collect)

---

## Generate Report Only

```bash
python3 command-trackers/guild-stats/scripts/generate_report.py [--days 90]
```

---

## What to show the user

After running, display clearly:

```
Wave Free Dropmaps!          109,369 members · 11,933 online · Tier 3 (39 boosts)
Wave Improvement Cord!        30,621 members ·  3,652 online · Tier 3 (27 boosts)
──────────────────────────────────────────────────────────
Combined                     139,990 members · 15,585 online
```

If `already_today` is true, note it was already collected today and you're showing the cached snapshot. Offer to open the HTML report for charts and trends.

---

## Open the HTML report

```bash
open "<report_path>"
```

The report includes: member count over time, online count, boost progression,
growth velocity (week-over-week %), and a sortable stats table with 7d/30d growth
and 30-day projections.

---

## Discord Bot Command

`>guilddash` — Management only. Runs collect, posts results embed + uploads HTML report.
Defined in `commands/guild_stats_commands.py`.

---

## Notes

- Data syncs via git push/pull — commit `data/data.db` and `data/reports/` after each run.
- `--skip-if-today` checks UTC date — won't double-snapshot on the same day.
- On Windows: use `python` instead of `python3`, and backslashes in paths.
- Staff Hub (`1041450125391835186`) is intentionally excluded — only the 2 public servers.

## Tracked servers

| Guild ID | Server |
|---|---|
| `988564962802810961` | Wave Free Dropmaps! |
| `971731167621574666` | Wave Improvement Cord! \| Loot & Surge Routes & Tips & Tricks |
