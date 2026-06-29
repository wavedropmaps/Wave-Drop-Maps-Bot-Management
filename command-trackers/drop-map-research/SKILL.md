---
name: drop-map-research
description: >
  Fortnite drop-map Discord server market research tracker. Collects daily member-count
  snapshots from Discord Discover for a tracked list of drop-map servers, stores them in
  a SQLite database, and generates HTML reports with market share charts, growth timelines,
  and 30-day predictions. Scripts live in command-trackers/drop-map-research/scripts/ inside the
  Wave Management Bot repo — tracked in git so data syncs across all machines.
---

# Drop Map Market Research

Tracks Discord member counts for Fortnite drop-map servers over time.
Run once a day to build up history, then generate HTML reports with charts.

**Data lives in `command-trackers/drop-map-research/data/`** — tracked in git, syncs via push/pull.

---

## Requirements

**Python 3** — on Windows use `python`, on Mac use `python3`.

**Playwright + Chromium** — install once:
```bash
pip install playwright
python -m playwright install chromium
```

---

## Scripts (all relative to bot repo root)

```
command-trackers/drop-map-research/scripts/collect.py         — scrape + save + report
command-trackers/drop-map-research/scripts/generate_report.py — report only
command-trackers/drop-map-research/scripts/manage_servers.py  — add/remove/list servers
command-trackers/drop-map-research/scripts/db.py              — DB setup (run once to init)
```

---

## Commands

| What user says | Action |
|---|---|
| `/drop-map-research` (no extra words) | **collect + report** — run immediately |
| "collect", "grab today's data" | **collect + report** |
| "generate report", "show charts" | **report only** |
| "add [server]" | **add server** |
| "remove [server]" | **remove server** |
| "list servers" | **list** |

**Default:** When invoked with `/drop-map-research` alone, immediately run collect.py without asking. Do not say "what would you like to do?" — just start.

---

## Collect (once a day)

```bash
# Mac
python3 command-trackers/drop-map-research/scripts/collect.py

# Windows
python command-trackers\drop-map-research\scripts\collect.py

# Bot use (no browser pop-up)
python command-trackers/drop-map-research/scripts/collect.py --no-browser
```

This does everything in one shot:
1. Scrapes `discord.com/servers` headlessly via Playwright
2. Saves snapshot to DB
3. Resolves due 30-day predictions (hit/miss)
4. Generates and opens the HTML report

---

## Generate Report Only

```bash
python3 command-trackers/drop-map-research/scripts/generate_report.py [--days 90]
```

---

## Manage Servers

```bash
python3 command-trackers/drop-map-research/scripts/manage_servers.py add "Server Name"
python3 command-trackers/drop-map-research/scripts/manage_servers.py remove "Server Name"
python3 command-trackers/drop-map-research/scripts/manage_servers.py list
```

---

## Discord Bot Command

`>rdropmap` — Management only. Runs collect, posts results embed to Discord.
Defined in `commands/drop_map_research_commands.py`.

---

## Notes

- For technical context on competitor map **imagery** sources (fn.gg vs Epic minimap, tile URLs), see [`ai-hub/research/fortnite-gg/drop-map-imagery.md`](../../ai-hub/research/fortnite-gg/drop-map-imagery.md).
- Data syncs via git push/pull — commit `data/data.db` and `data/reports/` after each run.
- Servers not on Discord Discovery show as ✗ — expected, not a bug.
- Running collect twice in one day is harmless (deduped by day for projections).
- On Windows: use `python` instead of `python3`.
