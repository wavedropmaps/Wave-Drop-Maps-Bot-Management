# Command-Backed Data Trackers

> Referenced from `AGENTS.md` → Codebase Map. The live, Discord-command-invoked data trackers in the top-level `command-trackers/` folder.

## Drop Map Market Research

Scripts at `command-trackers/drop-map-research/` — see `command-trackers/drop-map-research/SKILL.md` for full docs.

- **Discord command:** `>rdropmap` (Management only) — defined in `commands/drop_map_research_commands.py`
- **Manual collect:** `python3 command-trackers/drop-map-research/scripts/collect.py` (Mac) / `python command-trackers\drop-map-research\scripts\collect.py` (Windows)
- **Data:** `command-trackers/drop-map-research/data/data.db` + `data/reports/` — **tracked in git**, syncs via push/pull
- **One-time setup on a new machine:** `pip install playwright && python -m playwright install chromium`
- After each collect run on Windows, commit the updated `data.db` and push so Mac stays in sync.

## Guild Stats Dashboard

Scripts at `command-trackers/guild-stats/` — tracks member counts and key stats for the bot's **own** guilds over time.

- **Discord command:** `>guilddash` (Management only) — defined in `commands/guild_stats_commands.py`
- **Guilds tracked:** `988564962802810961` (Wave Free Dropmaps!), `971731167621574666` (Wave Improvement Cord!)
- **Stats per snapshot:** member count, online count, boost count, boost tier, channel count, role count
- **Manual collect:** `python3 command-trackers/guild-stats/scripts/collect.py` (Mac) / `python command-trackers\guild-stats\scripts\collect.py` (Windows)
- **Data:** `command-trackers/guild-stats/data/data.db` + `data/reports/` — **tracked in git**, syncs via push/pull
- **No extra dependencies** — uses the Discord REST API directly with `BOT_TOKEN` from `.env` (no Playwright)
- Run daily at **14:05 UTC** via `tasks/market_tracker_loop.py` (or use `>guilddash` manually)
- After each collect run on Windows, commit the updated `data.db` and push so Mac stays in sync.

## Improvement Cord Market Research

Scripts at `command-trackers/market-research/` — competitor improvement cord tracker.

- **Discord command:** `>mktdash` (Management only) — `commands/market_research_commands.py`
- **Manual collect:** `python command-trackers\market-research\scripts\collect.py`
- **Data:** `command-trackers/market-research/data/data.db` + `data/reports/`
- **Daily auto-collect:** `tasks/market_tracker_loop.py` at 14:05 UTC (after guild-stats)

## Cross-Market Overview

Scripts at `command-trackers/market-overview/` — see `command-trackers/market-overview/SKILL.md`

- **Discord command:** `>marketoverview` (Management only) — `commands/market_overview_commands.py`
- **Generate:** `python command-trackers/market-overview/scripts/generate_overview.py`
- Reads all three tracker DBs — no extra scraping
- Auto-generated after daily collect chain

## Shared metrics & data quality

`command-trackers/shared/`:

| Module | Purpose |
|--------|---------|
| `metrics.py` | Share delta, HHI, growth capture, online normalization, red flags, **coverage audit** (`audit_day_coverage`, `first_seen_dates`) |
| `report_fragments.py` | Donut renormalize, table expand, small multiples, **coverage banner** |
| `coverage_report.py` | `prepare_coverage_context()` wired into all `generate_report.py` scripts |
| `market_report_extras.py` | Market KPI row helpers (mktdash + rdropmap) |
| `reset_tracker_data.py` | One-time hard wipe of all `snapshots` (+ drop-map `predictions`). Keeps rosters. `--dry-run` / `--confirm` |

### Coverage rules (partial scans + new servers)

- A UTC day is **complete** only when every **expected** entity has a snapshot that day.
- **Expected roster on day D** = active servers/guilds where `first_seen <= D` (first snapshot date, or `added_at` from roster).
- **New server added later** does not flag older days as incomplete; share charts use that day's roster only (no retroactive backfill).
- **Incomplete days** are excluded from aggregate charts (totals, stacked share %, HHI inputs) and listed in an amber **Data coverage** banner at the top of each dashboard.
- `--skip-if-today` on manual collects skips only when today's day is **fully covered** (not merely `COUNT(*) > 0`).

### Hard reset workflow

```powershell
python command-trackers/shared/reset_tracker_data.py --dry-run
python command-trackers/shared/reset_tracker_data.py --confirm
python command-trackers/guild-stats/scripts/collect.py --no-browser
python command-trackers/market-research/scripts/collect.py --no-browser
python command-trackers/drop-map-research/scripts/collect.py --no-browser
python command-trackers/market-overview/scripts/generate_overview.py --no-browser
```

Verify `SNAPSHOT_RESULT` shows `"coverage": {"complete": true}` for each tracker before committing `data.db`.
