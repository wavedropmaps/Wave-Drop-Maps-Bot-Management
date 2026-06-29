# Session Handoff — Wave Staff Hub: architecture decisions + backbone partially built

## Where it started
User shared `wave_staff_hub_plan.md` and `wave_drop_maps_diagrams.html` as a planning brief for an interactive staff website. The session was entirely planning and architecture — no features were spec'd, decisions were made about what to cut and how to build. The plan had errors that were identified and corrected before any real code was written.

## Decisions locked + what shipped

- **Cut Vercel entirely** — Flask serves both the HTML files and the API. No proxy layer needed.
- **Cut GitHub JSON out of staff hub data path** — Flask reads from `bot_database.db` directly and returns live data. No push lag, no stale JSON in `website/`. GitHub JSON pushes (`github_sync.py`) continue unchanged for the existing GitHub Pages leaderboards only.
- **Existing GitHub Pages leaderboards are untouched** — `wave-leaderboard` repo and all its HTML files stay as-is. The new staff hub is a completely separate thing.
- **Flask + Cloudflare Tunnel = the whole hosting solution** — Windows machine is the server. Cloudflare Tunnel gives port 5000 a public HTTPS URL. No external hosting.
- **Folder structure decided**: `website/web_api.py`, `website/pages/`, `website/assets/` — nothing else in `website/`.
- **Two-phase security**: Phase 1 now (X-API-Key on POSTs, Flask-Limiter, input validation, debug=False). Phase 2 after pages work (Discord OAuth — closes the fake user_id hole).
- **async fix identified**: `database.py` is async, Flask is sync — every DB call in `web_api.py` needs `asyncio.run(...)` wrapper.
- **Flask installed** — `pip install flask python-dotenv` done.
- **`.env` updated** — `STAFF_HUB_SECRET=changeme` added at `C:\Users\kiere\Desktop\Wave Management Bot\.env`. Value must be changed to something real before going live.
- **`web_api.py` created** — at `C:\Users\kiere\Desktop\Wave Management Bot\web_api.py`. Has `/` and `/ping` only. No data endpoints yet.
- **`staff_hub/index.html` created** — placeholder only. **Folder name is wrong** — decision was `website/` not `staff_hub/`. Rename has not happened yet.

## Key files for next session

- `C:\Users\kiere\Desktop\Wave Management Bot\web_api.py` — the Flask backbone, read this first
- `C:\Users\kiere\Desktop\Wave Management Bot\staff_hub\index.html` — placeholder, wrong folder name, needs moving
- `C:\Users\kiere\Desktop\Wave Management Bot\.env` — `STAFF_HUB_SECRET` added but value is `changeme`, needs a real secret
- `C:\Users\kiere\.claude\projects\C--Users-kiere-Desktop-Wave-Management-Bot\memory\MEMORY.md` — project memory index

## Running state

- Background processes: none
- Dev servers / ports: none — Flask has never been run yet
- Open worktrees / branches: none

## Verification — how to confirm things still work

- `python -c "import flask; print(flask.__version__)"` — should print `3.1.3`
- `python website/web_api.py` from `C:\Users\kiere\Desktop\Wave Management Bot\` then `localhost:5000/ping` in browser — should return `{"status": "ok"}`

## Deferred + open questions

- Deferred: Discord OAuth (Phase 2 security) — pushed until at least one page is working
- Deferred: Cloudflare Tunnel setup — pushed until Flask is confirmed working locally
- Deferred: all data endpoints (`/api/loot`, `/api/vbucks`, etc.) — pushed until folder structure is correct
- Deferred: all HTML pages (`loot.html`, `vbucks.html`, etc.) — one at a time after backbone confirmed
- Open: `STAFF_HUB_SECRET` value — user needs to set this to a real random string before tunnel goes live
- Open: which leaderboard page to build first — loot rotation was implied but not confirmed

## Pick up here

Rename `staff_hub/` to `website/`, create `website/pages/` and `website/assets/` subfolders, move `web_api.py` into `website/`, update the static folder path in `web_api.py`, run Flask locally, and confirm `localhost:5000/ping` returns `{"status": "ok"}` before touching anything else.
