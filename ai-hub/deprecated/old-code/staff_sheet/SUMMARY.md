# Staff Sheet System — Archive Summary

Retired: 2026-06-15. Replaced by the **Weekly Performance** page (`duties_leaderboard.html`) which covers the same engagement data plus duty staff in a unified hub page with historical week snapshots built into `duties.json`.

---

## What It Was

The Staff Sheet tracked **general staff only** (Trial Staff + Staff roles) across the two source guilds. It was not for duty staff (role givers, map req helpers) — those had their own system.

It produced two outputs in parallel:
1. A **Google Sheet** (written to the appropriate year/month/EDIT sheet in Google Drive)
2. A **JSON file** pushed to the wave-leaderboard repo (`website/staff_sheets/`) so the web page could serve historical weeks

The web page (`staff_sheet.html`) read those JSONs and displayed a sortable, archivable table.

---

## Metrics Collected

Per general staff member, scanned across both source guilds (Wave Free Dropmaps + Wave Improvement Cord):

| Column | Source | Formula |
|---|---|---|
| Messages | Channel history scan | Raw count across both guilds |
| Days Active | Channel history scan | Unique calendar days with ≥1 message |
| Rank (Messages) | Computed | `min(ceil(messages / 70 * 100), 100)` |
| Rank (Days) | Computed | `min(ceil(days_active / 7 * 100), 100)` |
| Mod Commands | Modlog embed scan | Count of modlog entries authored by user |
| **Rank Total** | Computed | `min(ceil((rank_msg + rank_days) / 2) + mod_cmds + improvement_points, 100)` |
| Improvement Points | Wave Improvement Cord messages | Raw message count in the improvement guild |

**Rank Total cap: 100.** Hitting 100 triggered a DM ("Congratulations! You earned 10 Wave Points") and credited 10 Wave Points via `bulk_credit_wave_points`.

---

## Bot Task: `tasks/staff_sheet.py`

**Trigger:** Originally ran at **167.5 hours** after week start (30 minutes before the 168h Full Week checks). Used a precise async sleep loop — not a discord.py `tasks.loop`. Had an execution lock + database dedup check to prevent double-runs.

**Now retired:** `cog_load()` was made a no-op on 2026-06-15. The cog still loads (so `main.py` doesn't error) but does nothing.

### Key Steps (when active)

1. Load `config.json` → get `source_guilds`, `staff_roles_config.general_staff` (role names to scan)
2. Find the Google Drive EDIT sheet: navigates `year_folder → month_folder → sheet with "edit" in name`, renames it to `"Staff Sheet {Month} {start} - {end} {year}"`
3. Scan all text channels in both guilds for messages by general staff members (limit 5000/channel)
4. Scan modlog channels for embeds containing staff member IDs
5. Compute all metrics, sort by `role_priority` then `-rank_total`
6. Write rows A2:I{N} to the sheet, add `=ROUND(AVERAGE(...))` formulas in the average row
7. Apply Google Sheets color formatting (column tints matching the HTML's spreadsheet aesthetic)
8. Push JSON to wave-leaderboard repo via `push_staff_sheet_to_github(payload, week_id)` where `week_id = "{year}-W{week:02d}"`
9. Credit Wave Points to all members, DM rank-100 users

### External Dependencies (not in current bot)

- `gspread` — Google Sheets client
- `google.oauth2.service_account.Credentials` — service account auth
- `googleapiclient.discovery.build` — Drive API + Sheets API
- `credentials.json` — Google service account key file (gitignored, must be on disk)
- Google Drive folder structure: `{year}/{month_abbr}/` with an EDIT spreadsheet inside

---

## Web Page: `staff_sheet.html`

### Data Format

The page fetched two things from `website/staff_sheets/`:

**`staff_sheets_index.json`** — list of all available weeks:
```json
[
  {"id": "2026-W24", "label": "May 31 - Jun 06", "group": "June 2026", "isRecent": true},
  {"id": "2026-W23", "label": "May 24 - May 30", "group": "May 2026", "isRecent": true},
  ...
]
```

**`staff_sheets/{week_id}.json`** — per-week data:
```json
{
  "_meta": {
    "start_date": "31/05/2026",
    "end_date":   "06/06/2026",
    "last_updated": "2026-06-07T09:38:08+00:00",
    "sheet_name": "Staff Sheet May 31st - June 6th 2026"
  },
  "staff": [
    {
      "name":               "fruss.",
      "role":               "Fruss",
      "messages":           521,
      "days_active":        7,
      "rank_messages":      100,
      "rank_days":          100,
      "mod_commands":       8,
      "rank_total":         100,
      "improvement_points": 86,
      "user_id":            123456789,
      "avatar_url":         "https://cdn.discordapp.com/avatars/..."
    }
  ]
}
```

### Week Selector UI

- Up to 4 recent weeks shown as **inline pills** (styled buttons in `#recentScroller`)
- Older weeks in a **dropdown** (`#dropdownMenu`), grouped by month label from `index.json`
- Clicking any week calls `selectWeek(id)` → fetches `staff_sheets/{id}.json` → re-renders table

### Sortable Table

9 columns, all sortable by clicking the header:

| # | Key | Color |
|---|---|---|
| 1 | name | Cyan |
| 2 | role | Blue (sorts by `ROLE_HIERARCHY` position, not alphabetically) |
| 3 | messages | Green |
| 4 | days_active | Purple |
| 5 | rank_messages | Light green |
| 6 | rank_days | Light purple |
| 7 | mod_commands | Red |
| 8 | rank_total | Amber/gold badge |
| 9 | improvement_points | Pink |

Default sort: `role ASC` (hierarchy order), tiebroken by `rank_total DESC` — matching how the Google Sheet was laid out.

Rank Total badge: gold glow at 100, standard gold 40-99, grey for low scores.

Average row appended at bottom (gold row, matching the Google Sheet's average footer row).

Role tier color coded via left border accent on each row + colored `role-badge` chip.

### Role Hierarchy

`ROLE_HIERARCHY` constant defined identically in both `staff_sheet.html` (JS) and `tasks/staff_sheet.py` (Python) — must be kept in sync if restored. Controls role sort order and tier badge color.

---

## What Replaced It

`duties_leaderboard.html` — **General Staff tab** — shows the same core metrics (Messages, Days Active, Mod Cmds, Rank Total) but:
- Data comes from `duties.json` (written by `duties_scan.py` every 4h)
- Historical weeks stored in `duties.json` under a `weeks[]` array (snapshotted at end of Full Week)
- No Google Sheets dependency
- No separate per-week JSON files or index file

The `duties_scan.py` engagement scan replaced the `staff_sheet.py` message scan, feeding the same metrics into the new schema.

---

## How to Restore

If you need to bring the staff sheet back:

1. **Restore the web page:** copy `staff_sheet.html` back to `website/staff_sheet.html`
2. **Re-add to nav:** add `{ file: 'staff_sheet.html', label: 'Staff Sheet' }` to `PAGES` array in `wave-nav.js`
3. **Re-add to web_api.py** `_API_PAGES`: add `'staff_sheet'` (if serving JSON from Flask)
4. **Restore the bot task:** un-retire `cog_load()` in `tasks/staff_sheet.py` to restart the 167.5h trigger loop
5. **Restore Google credentials:** ensure `credentials.json` is on the Windows machine with Sheets + Drive scopes
6. **Restore data files:** the `website/staff_sheets/` folder (week JSONs + index) and `staff_sheets_index.json` need to be on disk; the bot will write new ones from the next weekly run
7. **Install Python deps:** `pip install gspread google-auth google-api-python-client` on Windows

Everything else (rank formulas, column layout, ROLE_HIERARCHY) is preserved verbatim in the archived files here.

## 2026-06-22 — Google Sheets export fully retired
`tasks/staff_sheet.py` moved here. Owner no longer uses the manual `>forcereportstaffsheet` /
`>softforcereportstaffsheet` commands, which were the last live callers of
`export_to_google_sheets`. Removed: both commands in commands/automation_config.py, the
`tasks/__init__.py` import/__all__ entry, and the 'Staff Sheet Export' status label in
commands/maintenance_commands.py. The 167.5h auto-trigger was already retired earlier.
