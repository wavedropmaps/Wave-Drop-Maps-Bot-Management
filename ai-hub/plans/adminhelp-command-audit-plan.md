# Plan — Audit & Fix `>adminhelp` Command Suite

## Context
`>adminhelp` is the master admin help menu, built in `commands/utilities.py` as the
`AdminHelpView` class (a dropdown-navigated, 23-page embed system; pages defined in
`ADMIN_PAGES` at line ~646, command lives at line ~255). Over time the help pages have
drifted from the actual code: some listed commands were deleted (they now live only in
`ai-hub/deprecated/old-code/obsolete_commands.py`, which is NOT loaded), and several real,
live commands were never added to the menu.

A full inventory was taken by scanning every `@*.command(` / `@*.group(` decorator across
`commands/*.py` **and** `main.py`, then cross-checking each command name/alias listed on
`>adminhelp` against that inventory.

## Reason
Staff use `>adminhelp` as the source of truth for what they can run. Right now it:
- advertises commands that **error** when typed (ghosts), and
- **hides** commands that actually exist.
Both erode trust in the menu and cause support questions.

## Purpose
Make `>adminhelp` an accurate, complete, well-sorted reflection of the live command suite —
**help text only, no command behaviour changes.**

---

## Findings

### ❌ Ghost commands listed but NOT existing (remove)
| Command(s) | Page | Status |
|---|---|---|
| `>wavepoints` / `wp` / `mypoints` | Wave Points | deprecated-only |
| `>wpleaderboard` / `wplb` / `waveleaderboard` | Wave Points | deprecated-only |
| `>wavepointshop` / `wpshop` | Wave Points | deprecated-only |
| `>wavepointsredeem` / `wpr` / `wpredeem` | Wave Points | deprecated-only |
| `>forcereportstaffsheet` | Automation | does not exist — REMOVED |
| `>softforcereportstaffsheet` | Automation | does not exist — REMOVED |
| `>updatelootrouteleaderboard` | Loot Routes | does not exist — REMOVED |

> The Wave Points page is mostly fictional. Only real bot commands: `>wpset` (admin),
> `>pay <@user> <amount> <currency>` (10% tax). Everything else moved to the Staff Hub website.

### ➕ Real commands MISSING from the menu (add)
| Command | Source file | Target page |
|---|---|---|
| `>economysync` | `central_bank_commands.py` | Central Bank |
| `>surgeclean` | `surge_route_commands.py` | Surge Routes |
| `>mktdash` | `market_research_commands.py` | Statistics |
| `>landmarks` | `poi_names_commands.py` | Utilities |
| `>namedlocations` (`namedpois`/`locations`) | `poi_names_commands.py` | Utilities |
| `>rawdropmapwatermark` (`rawdmw`) | `auto_watermark.py` | Image Editor |
| `>rawlootroutewatermark` (`rawlrw`) | `auto_watermark.py` | Image Editor |
| `>refreshteam` | `utilities.py` (TeamCommands) | Maintenance |

### ✅ Verified correct (no change)
`>ratelimitstats` (real — defined in `main.py`, not a cog). All loot/surge/tips/voting/
config/predictions/database commands matched the menu.

---

## Steps
1. **Rewrite Wave Points page** (`get_wave_points_embed`) → keep only `>wpset` + `>pay`
   (fix `>pay` signature to include `<currency>`); point balance/shop/leaderboard/redeem
   to the website.
2. **Add the 8 missing commands** to their target pages (table above).
3. **Fix the Overview page** (`get_overview_embed`) summary lines to match (Wave Points,
   Statistics, Image Editor raw variants).
4. Keep page count / dropdown as-is — `landmarks`/`namedlocations` fold into Utilities,
   no new page needed.

## Out of scope
- No changes to command code/behaviour, only embed help text.
- No new dropdown pages.

## Already applied during investigation
- Automation page: removed `>forcereportstaffsheet` + `>softforcereportstaffsheet`.
- Loot Routes page: removed `>updatelootrouteleaderboard`.

## Open decision
- POI commands (`>landmarks`, `>namedlocations`): fold into **Utilities** (recommended) or
  give a dedicated **🗺️ Fortnite Info** page.
