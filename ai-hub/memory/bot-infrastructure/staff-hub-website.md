# Wave Staff Hub Website (self-hosted, Discord-gated) 🌐

> Referenced from `AGENTS.md` → Codebase Map. Read this before touching anything under `website/`, `cloudflare_pages*/`, `web_api.py`, or `staff_hub_serve.py`.

Two private websites served **from this PC** — no GitHub Pages, no cloud host.

**The two sites (one Flask, one tunnel, one supervisor):**
- `https://wavedropmaps.pages.dev` — **Wave Staff Hub** (9 leaderboard pages). Gated to **staff-guild membership** (`1041450125391835186`).
- `https://wave-logging.pages.dev` — **Wave-Logging dashboard**. Gated to the **Management role** (`1041582103927726170`) via OAuth `guilds.members.read`.

### Request flow (how a page load works)
```
Browser → <site>.pages.dev          = Cloudflare Pages "worker" (the edge gate)
        → Discord OAuth; on success sets a signed 30-day cookie (HMAC, edge-only)
        → worker proxies through the quick tunnel WITH the X-API-Key secret
        → cloudflared quick tunnel (rotating URL) → Flask web_api.py @ 127.0.0.1:5000
        → Flask serves static pages + JSON the BOT wrote to disk
```
- **Edge gate** = `cloudflare_pages/_worker.js` (hub) + `cloudflare_pages_logging/_worker.js` (logging): Discord OAuth, set/verify signed session cookie, fail closed if misconfigured, proxy to the tunnel.
- **Origin** = `web_api.py` (Flask, `127.0.0.1:5000`). Routes: `/` + static from `website/`; `/api/<page>` (bot-written JSON); `/logging` + `/logging/data/<p>` (logging site + `wave_logging_local/data/`); `/ping` (health).

### Data is BOT-BUILT, never DB-queried by Flask (the core rule)
Flask only serves files. The **bot** builds each payload (it needs the live guild for names/avatars/roles — pure SQL can't) and writes it to disk:
- `tasks/staff_hub_writer.py` (formerly `github_sync.py`) — its `push_*_to_github(...)` fns write `website/data/<key>.json` locally (GitHub push retired 2026-06-14). Flask serves them at `/api/<key>`.
- Logging data → `core/wave_logging_push.py` writes `wave_logging_local/data/...` → served under `/logging/data/`.
- Allowlisted endpoints (`_API_PAGES` in `web_api.py`): `loot, surge, tips, milestones, duties, vbucks, economy, reviewing, daily_summary, session_history`.
- `website/` is a **FLAT mirror** of the old wave-leaderboard repo; pages keep original filenames so cross-links work. Each page fetches `/api/<its-key>` — only the `DATA_URL` line differs per page.

### How it runs (the supervisor)
- `staff_hub_serve.py` = **supervisor**: starts Flask + a free cloudflared quick tunnel, reads the **rotating** `https://<words>.trycloudflare.com` URL, rewrites the `const TUNNEL_URL = '...'` line in BOTH workers, and `wrangler pages deploy`s them so pages.dev follows the live tunnel. Restarts Flask/tunnel if either dies. `SITES` list = which projects it manages. CF creds (`CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`) come from `.env`.
- **Autostart at BOOT:** a Scheduled Task `WaveStaffHubAutostart` (registered by `setup_staff_hub_autostart.ps1`) — trigger "At startup" +60s, runs as `kiere` via **S4U** (whether-logged-on-or-not, no stored password) at highest privileges, action = `restart_staff_hub.ps1`. This **survives unattended Windows-Update reboots** — the old `WaveStaffHub.vbs` (Startup folder) only fired on interactive logon, so after a forced reboot the PC sat at the lock screen, the supervisor never came back, the tunnel died, and the site showed **Cloudflare Error 1016 ("Origin DNS error")** while the bot ran fine. The VBS is now disabled (renamed `WaveStaffHub.vbs.disabled` in the Startup folder) to avoid a double-launch race; re-enable only if you remove the task. Re-install/repair the task: `powershell -ExecutionPolicy Bypass -File setup_staff_hub_autostart.ps1` (needs elevation/UAC).
- **Reliable manual (re)start: `restart_staff_hub.ps1`** at repo root — NOT the old `Start-Process wscript ...WaveStaffHub.vbs` one-liner (it silently fails on the spaces in the Startup path).

### 🚫 DO NOT TOUCH / DO NOT DO
- **Don't start anything on port 5000.** That's the live Flask origin; a dev/preview server there takes the site down.
- **Don't hardcode or rely on the `TUNNEL_URL` value** in either `_worker.js` — supervisor-managed, rewritten on every restart (URL rotates). Keep the exact line format `const TUNNEL_URL = '...';`.
- **Don't run a second supervisor.** One `staff_hub_serve.py` only.
- **Don't make Flask write `bot_database.db`.** Flask has no `_bot_instance`, so a direct write SKIPS all bot side-effects (leaderboard auto-update, role removal, semantic logging) and risks WAL contention. All mutations MUST route through the bot — this is the gate for any future "website actions."
- **Don't commit `.env`** (holds `BOT_TOKEN`, `CLOUDFLARE_API_TOKEN`, `STAFF_HUB_SECRET`). Gitignored + untracked; keep it so.

### How to change things (recipes)
- **A page's look/markup:** edit its HTML/CSS in `website/` (keep the filename). No deploy — Flask serves it live; hard-refresh.
- **A leaderboard's DATA:** edit the payload builder in the owning task (`tasks/loot_routes.py`, `tasks/surge_routes.py`, `tasks/economy_sync.py`, …) AND the page's render code. The bot rewrites `website/data/<key>.json` on next data change.
- **A new data endpoint:** add the key to `_API_PAGES` in `web_api.py`; have the bot write `website/data/<key>.json`; page fetches `/api/<key>`.
- **Worker/auth/header logic:** edit `cloudflare_pages/_worker.js` (or `_logging`), then `npx wrangler pages deploy cloudflare_pages --project-name wavedropmaps --branch main --commit-dirty=true` (creds from `.env`), or just restart the supervisor (redeploys both). Preserve the `TUNNEL_URL` line format.
- **After editing `web_api.py`:** restart with `restart_staff_hub.ps1` (a FULL restart is required if `.env` changed so the supervisor re-reads it). Flask uses `load_dotenv(override=True)`.

### Running the website LOCALLY (dev preview — for any agent)
To preview the site on your own machine WITHOUT touching the live origin:
- **`python3 dev_server.py`** — the correct local preview; it mocks the `/api/*` endpoints from `website/data/*.json` and auto-picks a free port (~8080). Use this to see pages with data.
- **Static folder preview:** `python3 -m http.server <port> --directory <folder>` (e.g. `website/`, `wave_logging_site/`) for a quick look at static markup.
- ⚠️ **Never start a server on port 5000** — that's the live Flask origin; doing so takes the real site down.
- *(Claude Code users get these as one-click presets in `.claude/launch.json`; every other agent just runs the commands above — same thing, this is the portable version.)*

### Security model (origin auth — added 2026-06-14)
- **Edge gate** = per-site Discord OAuth + signed HMAC cookie (30-day), in the worker. **Origin auth** = shared secret `STAFF_HUB_SECRET`: both workers attach it as `X-API-Key` on every proxied request (stripping any client-supplied copy first); `web_api.py`'s `@app.before_request` requires it (constant-time `hmac.compare_digest`), exempts `/ping`, **fails closed (503)** if blank. Without it, anyone who learns the rotating tunnel URL could hit Flask directly; with it they get 403.
- Secret lives in `.env` (Flask) + as a Pages secret on BOTH projects (workers). Same value everywhere. The worker **strips the session cookie** before proxying, so Flask does NOT yet know the user's identity — for website write-actions later, the worker must forward the verified Discord user id (e.g. `X-Wave-User-Id`) and route the action through the bot.

### Verify it's healthy
- `Invoke-WebRequest http://localhost:5000/ping` → `{"status":"ok"}` (Flask).
- `Invoke-WebRequest https://wavedropmaps.pages.dev/ping` → `{"status":"ok"}` (full path).
- Raw tunnel `https://<words>.trycloudflare.com/api/vbucks` with no `X-API-Key` → **403** (origin locked).
- `staff_hub_serve.log` should end in `... deployed OK`.

**Full build history + per-page recipe: `ai-hub/deprecated/STAFF_HUB_PLAN.md`.**
