---
name: market-overview
description: >
  Executive cross-market overview for Wave Discord trackers. Reads latest snapshots
  from guild-stats, market-research, and drop-map-research databases and generates
  a single HTML summary. Use for "market position", "executive summary", "how are we
  doing across markets", or >marketoverview equivalent.
---

# Market Overview

One-page executive summary across all three tracker dashboards.

**No scraping** — reads existing `data.db` files from:
- `command-trackers/guild-stats/`
- `command-trackers/market-research/`
- `command-trackers/drop-map-research/`

## Generate

```bash
python command-trackers/market-overview/scripts/generate_overview.py
```

Output: `command-trackers/market-overview/data/reports/overview_YYYY-MM-DD.html`

## Discord

`>marketoverview` — Management only (`commands/market_overview_commands.py`)

## Daily refresh

Generated automatically after the 14:05 UTC collect chain in `tasks/market_tracker_loop.py`.
