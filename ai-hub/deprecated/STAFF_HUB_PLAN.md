# Wave Staff Hub — Build Plan & Progress

**Goal:** Replicate the GitHub Pages site (`Desktop\wave-leaderboard`) **exactly** — same homepage with nav cards linking to all sections, same look — but served entirely from this PC with **live `bot_database.db` data and ZERO GitHub dependency**. No fallback; PC/tunnel down = site down (accepted). GitHub Pages retired once done.

**URL:** `https://wavedropmaps.pages.dev` → Cloudflare `_worker.js` proxies to the quick tunnel → Flask (`web_api.py`) on this PC. (cloudflare_pages/_worker.js)

---

## Architecture (corrected after investigation 2026-06-13)

**The original "Flask reads `bot_database.db` directly" plan was WRONG** — it cannot produce a faithful replica. The leaderboard payloads are built by bot-side functions (e.g. `tasks/loot_routes.py::_do_update_loot_route_leaderboard`) that resolve **display names, avatars, and role membership** (maker/away roles) from the **live bot/guild** (`guild.get_member`, `guild.fetch_member`, `role.members`). A standalone Flask process has no bot → would render `User 12345`, no avatars, no role filtering.

**Correct architecture (simpler + robust):** the bot ALREADY builds each page's exact payload on every change (debounced) to push to GitHub. We add a few lines so it **also writes the payload to a local file** (`website/data/<page>.json`). **Flask just serves that file** — no per-request DB load, no Discord rate-limit risk, identical-by-construction to the GitHub version, live within the debounce window, zero GitHub dependency.

**Folder layout:** `website/` is a **FLAT mirror** of the wave-leaderboard repo (all `.html` + `images/` + `loot_route_assets/` + `wave-guide.js`/`app.jsx`/`styles.css` at root) so cross-links and asset paths work unchanged, plus a new `website/data/` for the local JSON payloads. Flask: `static_folder=website, static_url_path=''`; explicit routes `/`→`index.html`, `/api/<page>`→`data/<page>.json` (no-cache), `/ping`.

---

## Per-page recipe (loot first, then repeat)

For each page X:
1. **Seed** `website/data/X.json` from the freshly-pulled `wave-leaderboard/X.json` (real current data, correct shape).
2. **Copy** `X.html` + its local assets into `website/` (flat). Copy `images/` + `loot_route_assets/` once.
3. **Localize images:** replace `https://raw.githubusercontent.com/wavedropmaps/wave-leaderboard/main/` → `/` in the HTML (handle the `DATA_URL` line separately — it shares the prefix).
4. **Flip data source:** `const DATA_URL = '...github...X.json'` → `'/api/X'`.
5. **Bot wiring (the "live" part):** in the bot builder that produces X's payload, add a local-file write to `website/data/X.json` (atomic: temp + os.replace), alongside the existing GitHub push. Keep the GitHub push for now (parallel path, retired later).
6. **Flask route** `/api/X` → serve `website/data/X.json`.
7. **Deploy** (`npx wrangler pages deploy website ...`) + **verify** end-to-end on pages.dev (renders, live data, no console errors, nav links).

External CDN libs (chart.js via jsdelivr) are kept — not part of the GitHub data path. Discord CDN avatars kept — unavoidable, not GitHub.

---

## Page checklist

- [x] **homepage** (`index.html`) — static nav page, no data endpoint. Copied flat. ✅ live
- [x] **loot** (`loot_routes_leaderboard.html`) ← `push_loot_route_leaderboard_to_github`→`loot.json`; /api/loot; images+loot_route_assets localized. ✅ live, verified
- [x] **surge** (`surge_routes_leaderboard.html`) ← `push_surge_route_leaderboard_to_github`→`surge.json`; /api/surge; surge_route_assets localized. ✅ live, verified
- [x] **tips & tricks** (`tips_tricks_leaderboard.html`) ← `push_tips_tricks_leaderboard_to_github`→`tips.json`; /api/tips. ✅ live, verified
- [x] **milestones** (`milestones.html` + `app.jsx`) ← `push_milestones_to_github`→`milestones.json`; /api/milestones (DATA_URL flipped in app.jsx). ✅ live, verified
- [x] **duties** (`duties_leaderboard.html`) — TWO files: /api/duties (`push_duties_to_github`→duties.json) + /api/vbucks (`push_vbucks_leaderboard_to_github`→vbucks.json). ✅ live, verified (2 broken imgs = Discord avatar 404s, pre-existing)
- [x] **economy** (`economy.html`) — relative `fetch('economy_data.json')`→`/api/economy` (`push_economy_dashboard_to_github`→economy.json); React/Babel cdnjs. ✅ live, verified
- [x] **reviewing** (`reviewing_leaderboard_final.html`) — THREE files: /api/reviewing, /api/daily_summary, /api/session_history. session_history mirrored via SPECIAL local-append (push receives one session, not the array). ✅ live, verified
- [x] **staff sheet** (`staff_sheet.html`) — MULTI-FILE: staff_sheets_index.json + staff_sheets/<week>.json served STATICALLY from website root (no page edit). Both push fns mirror locally; index merged against the LOCAL file for independence. ✅ live, verified
- [x] **FINAL CHECK** — full pages.dev sweep: 9 pages + 12 data endpoints + 3 assets all HTTP 200; every page render-checked (live data, zero console errors); homepage nav all 8 cards resolve. ✅

## ✅ MIGRATION COMPLETE (2026-06-13)
All 9 pages live at https://wavedropmaps.pages.dev, served from the PC, zero GitHub *data/asset* dependency. 11 push functions in `github_sync.py` now mirror payloads to `website/data/` (+ staff_sheets root files) via `write_local_payload` / specialized writers.

### ⚠️ OPERATIONAL STATUS
1. **RESTART THE BOT (still pending — only YOU can do this).** The running bot still has the OLD `github_sync.py`; live data mirroring activates only after restart. Until then the site serves the SEEDED snapshot (accurate as of migration). After restart, each page refreshes on its builder's next trigger.
2. ✅ **Tunnel durability — SOLVED.** `staff_hub_serve.py` is a supervisor that starts Flask + the quick tunnel, auto-captures the rotating URL, rewrites `_worker.js`, and `wrangler`-redeploys — so `wavedropmaps.pages.dev` always follows the tunnel (~30s). Watchdog restarts either process if it dies and re-syncs. (Logs are ASCII-only — Windows cp1252 console crashes on emoji; learned the hard way.)
3. ✅ **Auto-start on boot — SOLVED (no admin).** Startup-folder launcher `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WaveStaffHub.vbs` runs the supervisor hidden at logon (logs → `staff_hub_serve.log`). Alternative admin path: `register_staff_hub_boot.ps1` (scheduled task — needs an elevated PowerShell; the non-admin VBS is preferred). Remove the .vbs to disable.
4. Optional polish: localize `og:image`/`og:url` meta (still github.io — social cards only, non-functional); add deploy-retry in supervisor for slow-network-at-boot; retire GitHub push + Pages once trusted.

## 🔐 AUTH GATE (built, STAGED — not live yet)
**Decision:** Discord OAuth, gated on membership of the Staff Hub guild (`1041450125391835186`, which is staff-only), enforced at the **Cloudflare edge** (unauth never reaches the PC), reusing the bot's Discord application. 30-day session. Built in `cloudflare_pages/_worker.auth.js` (red-teamed by a 4-lens adversarial workflow before go-live). Live `_worker.js` is the open proxy — untouched so nobody is locked out while building.

**Go-live checklist (when back at the PC, after user pastes Client ID + Secret):**
1. Discord Dev Portal → bot's app → OAuth2: copy **Client ID** + **Client Secret**; add redirect `https://wavedropmaps.pages.dev/__auth/callback`.
2. Generate a session secret: `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
3. Set Pages project vars/secrets (dashboard or wrangler): `DISCORD_CLIENT_ID` (var), `DISCORD_CLIENT_SECRET` (secret), `SESSION_SECRET` (secret). `wrangler pages secret put <NAME> --project-name wavedropmaps`.
4. In `_worker.auth.js` set `GATE_ENFORCED = true` (fail-closed: a missing/weak secret then 503s instead of serving the site open). Then replace `_worker.js` with its content (KEEP the supervisor-managed `const TUNNEL_URL=...` line so `staff_hub_serve.py` keeps auto-updating it), deploy.
5. Test: member logs in → reaches site; non-member → "staff only" 403; expired/forged cookie → bounced to login. Note: `/ping` stays open for the supervisor health check.

**Red-team (4-lens adversarial review, 2026-06-13):** lock is SOUND — no session forgery without SESSION_SECRET, no guild-check bypass for non-members, no path-trick bypass. Hardening applied to `_worker.auth.js`: edge-cache protection (`Cache-Control: private, no-store` on gated responses, prevents CF serving authed pages to others), session cookie stripped before proxying upstream, `getCookie` won't 500 on a malformed cookie, `GATE_ENFORCED` fail-closed switch + min 32-char `SESSION_SECRET`. **Known accepted trade-off:** a 30-day session is NOT re-checked against live guild membership — a staffer removed from the guild keeps web access until their session expires (≤30 days). Inherent to "remember 30 days"; mitigate later with a shorter TTL or periodic re-validation if tighter revocation is wanted. (`/__auth/logout` clears their cookie immediately if done on their device.)

**Staff UX:** open pages.dev → redirected to Discord → "Authorize" once (reads identify + guild list) → if in the Staff Hub guild, in for 30 days; else denied. No bot-linking, no commands.

---

## Notes / gotchas
- Local `wave-leaderboard` checkout: `git pull --rebase --autostash` before reading pages (was 29 behind). A leftover `autostash` stash exists as backup; conflicted files restored to clean remote versions.
- The bot must be running for live data; if bot down (PC up) data is stale-but-served (accepted).
- TODO (post-migration): quick-tunnel URL rotates on restart (hardcoded in `_worker.js`) — automate; auto-start Flask + tunnel on boot; Discord OAuth before any non-public data; retire GitHub push + Pages.
