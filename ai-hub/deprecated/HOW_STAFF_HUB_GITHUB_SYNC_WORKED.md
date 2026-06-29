# How the Staff Hub GitHub Sync Worked (ARCHIVED — retired 2026-06-14)

This documents the GitHub-push system that `tasks/github_sync.py` used to run, **before** it was retired in favour of the local Wave Staff Hub (`https://wavedropmaps.pages.dev`, served from the PC). Kept in case it ever needs to be restored or referenced. The **full original code is recoverable from git history** (the commit immediately before 2026-06-14).

## What it did
The bot built leaderboard/stats payloads and **pushed them as JSON files to a GitHub repo** (`wavedropmaps/wave-leaderboard`), which was served publicly via **GitHub Pages** at `https://wavedropmaps.github.io/wave-leaderboard/`. The static HTML pages in that repo fetched those JSON files (via `raw.githubusercontent.com`) to render the leaderboards. That whole path is now replaced by Flask serving `website/data/*.json` locally.

## Config (`config.json` → `"github"` block)
```json
"github": {
  "token": "<classic PAT, 'repo' scope>",
  "username": "wavedropmaps",
  "repo": "wave-leaderboard",
  "branch": "main"
}
```
Loaded by `load_github_config()`. ⚠️ This block is **still present** because `core/wave_logging_push.py` (a SEPARATE system, see below) reads the same token. The token was exposed (git history + chat) and should be **rotated** on GitHub.

## API pattern (GitHub Contents API)
For each file, per push function:
1. `GET /repos/{user}/{repo}/contents/{file}` → read current `sha`.
2. `PUT /repos/{user}/{repo}/contents/{file}` with body `{message, content: base64(json), branch, sha}`.
3. On `409` (SHA mismatch from concurrent writes): re-fetch SHA and retry, up to 3×.
4. Rate-limit handling (`_check_rate_limit_headers`, `_handle_rate_limit`, `_api_call_with_backoff`): on `429`/`403 rate-limit`, wait until `x-ratelimit-reset` or exponential backoff (2,4,8…s).

## Files pushed + which builder produced each
| GitHub file | Builder (bot-side) | Push fn |
|---|---|---|
| `milestone_totals.json` | `tasks/staff_insights.py::sync_milestone_totals` (+ Google Sheets) | `push_milestones_to_github` |
| `duties_totals.json` | `tasks/duties_scan.py::perform_full_scan` | `push_duties_to_github` |
| `vbucks_leaderboard.json` | `tasks/leaderboard_updater.py::build_vbucks_leaderboard_data` | `push_vbucks_leaderboard_to_github` |
| `drop_map_reviewing.json` | `tasks/reviewing_tasks.py::_do_update_drop_map_leaderboard` | `push_drop_map_leaderboard_to_github` |
| `daily_summary.json` | reviewing tasks | `push_daily_summary_to_github` |
| `session_history.json` | reviewing (**APPEND**: GET existing → append one session → PUT full array `{sessions:[...]}`) | `push_session_history_to_github` |
| `loot_routes_leaderboard.json` | `tasks/loot_routes.py::_do_update_loot_route_leaderboard` | `push_loot_route_leaderboard_to_github` |
| `surge_routes_leaderboard.json` | `tasks/surge_routes.py::_do_update_surge_leaderboard` | `push_surge_route_leaderboard_to_github` |
| `economy_data.json` | `tasks/economy_sync.py::compile_economy_data` | `push_economy_dashboard_to_github` |
| `staff_sheets/<week>.json` + `staff_sheets_index.json` | `tasks/staff_sheet.py::export_to_google_sheets` | `push_staff_sheet_to_github` + `update_staff_sheets_index` |
| `tips_tricks_leaderboard.json` | `tasks/tipsandtricks.py::push_leaderboard` | `push_tips_tricks_leaderboard_to_github` |

Special helpers:
- `replace_json_on_github(filename, content)` — overwrote/reset a file (used by the reviewing wipe/reset command).
- `update_staff_sheets_index(week_id, week_meta)` — maintained the index: dedupe by `id`, sort newest→oldest by an internal `_sort` (`YYYYMMDD`), mark the top 4 `isRecent`, strip `_sort` before writing.
- The payloads **require the live bot/guild** (display names, avatars, role membership) — they could not be built from SQL alone. That's why the new system has the bot build the payload and write it locally (rather than Flask querying the DB directly).

## How it was retired (2026-06-14)
`tasks/github_sync.py` was rewritten so every `push_*_to_github` / `replace_json_on_github` now writes **only** to `website/data/` (the Staff Hub's live dir, served by Flask at `/api/<page>`). All GitHub API code (`aiohttp`, `load_github_config`, the rate-limit helpers, the Contents-API PUT logic) was removed. **Function names were kept** so the callers across `tasks/` and `commands/` need no changes. `setup(bot)` kept (the module loads as a bot extension). The file was then **renamed `tasks/github_sync.py` → `tasks/staff_hub_writer.py`** to reflect its new job, and all 15 importing files updated (`tasks.github_sync` → `tasks.staff_hub_writer`).

## To restore GitHub push (if ever needed)
1. `git show <pre-2026-06-14-commit>:tasks/github_sync.py` to recover the original.
2. Ensure `aiohttp` is installed and the `config.json` `"github"` block has a valid PAT.
3. Re-add the `import aiohttp/base64/asyncio` lines.

## NOT affected by this retirement
`core/wave_logging_push.py` is a **different** system — it pushes the **Wave-Logging dashboard** to a separate `Wave-Logging` GitHub repo and was never migrated to the Staff Hub. It still uses GitHub (reads the same `config.json` token directly). Left intact.
