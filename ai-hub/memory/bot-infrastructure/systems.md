# System Architectures (high-level)

> Referenced from `AGENTS.md` → Codebase Map. Read the relevant section before changing that system.

### Strike System 🚨
- 4 phases: **issuance → DB → auto-removal → viewing**.
- Issuance during **Full Week reports only** (not mid-week). Thresholds: purge=10, req=15, role=30.
- `database.update_strike_points(user_id, duty_type, change, bot=None)` is the chokepoint — it auto-triggers `tasks.strike_functions.check_and_remove_role_for_strikes()` when total hits 3+.
- Role match: substring on role name ("purge", "role giver", "map request").
- Removal sends embed DM with reinstatement instructions. Leaderboard auto-updates.
- Away users (role `1231259676457566250` or strike-immunity `1495688613030133821`) are **skipped from warnings, strikes, and weekly WP awards**.
- Commands: `>strikeview`, `>strikes`, `>strikes set`, `>strikeconfig`.

### VBucks System 💰
- **VBucks are now a fixed-price WP shop prize**, not a separately-earned currency. The market, exchange, wallets, and weekly VBucks awards are removed post-economy-unification.
- **Buy price:** 50 WP = 100 VBucks (increments up to 5,000 WP → 10,000 VBucks) — purchased via the Staff Hub economy page.
- **Legacy balances** were converted to Wave Points at 15 WP per 100 VBucks (1,000 VB → 150 WP) by `migrations/vbucks_to_wp.py`.
- `vbucks` table and `get_vbucks`/`set_vbucks`/`add_vbucks` DB helpers are **retained** (frozen post-migration) but no new code should write VBucks awards.
- `>vbucks [user]` shows balance (expected 0 post-migration). `>vbucksconfig` shows total in circulation.
- Performance ranks per duty have specific count thresholds (e.g. Role: Great 101+, Very Good 81-100, Good 51-80, Okay 30-50, Bad <30 → strike).

### Wave Points System 🌊
- **Single currency.** WP is what staff earn, hold, and spend. No market, no exchange, no exit tax.
- **Earning:**
  - Full-week Req rank: **150 WP** (rank 1) / **100 WP** (rank 2). *(Removed 2026-06-22: legacy `activity_streaks` 1.5× multiplier after 3 consecutive "Great" weeks — dead system, mode #24 not built on it.)*
  - Power Hour (5% hourly chance, 1h): messages/roles/requests/modcmds → WP.
  - Staff sheet score ≥100 → +10 WP.
  - Drop Map Reviewing, Tips & Tricks tasks → WP directly.
  - Loot/Surge Route completions → WP by speed bracket.
- **Bad performance penalty (map request):** flat **−40 WP** (role removed if balance is below 40).
- **Shop:** roles, perks, in-game rewards, VBucks card prizes — on the Staff Hub website.
- **APR interest removed** (decision #6 — fixed prize prices + compound interest = price drift). Bonds + lottery remain.
- `database.add_wave_points(user_id, amount, bot=None)` is the single write path. Leaderboard auto-updates on every change (debounced 1.5s).

> ⚠️ **Co-edit rule:** Any change to economy mechanics (earning rates, commands, award types, currency names, shop items, penalties) **must also update `website/wave-guide.js`** in the same commit. The guide is a static doc file — it has zero connection to bot code and will silently drift if not touched. Learned from the VBucks→WP unification where the guide kept stale LRP/SRP/APR/VBucks-award copy until a follow-up pass.

### Loot Route System 🗺️
- Sequential rotation, **no gaps ever** — rank is derived live from `loot_route_positions` ORDER BY `assigned_at ASC, user_id ASC`, so removing a user auto-resequences ranks 1..N with no gaps. `position_number` column is **vestigial** (never read for ranking). `resequence_positions()` is now effectively a dead no-op because `get_all_loot_route_positions()` already returns gap-free ranks.
- Auto-assign when image+text posted to `#maps-not-taken` (`1205406903463710750`). Skips away users + users with active (pending/confirmed) assignments. **Hold pool (mirrors surge):** if no maker is free, the map is **held** (image downloaded + queued in `loot_pending_maps`, ⏳ reaction) and auto-assigned **oldest-first** when a maker frees up — no more double-assign. `find_next_available_user(allow_fallback=False)` returns None → hold. `drain_loot_pending_pool()` is lock-guarded and wired to **startup** (maps held while down), **route completed (`>done`)**, **new maker added**, and **away-return**. `_assign_loot_map()` assigns from either live attachments or the held map's saved files.
- **33% Lucky Map chance** (`LUCKY_MAP_CHANCE = 0.33`) — 2× multiplier, applied AFTER role multiplier (so Head + Lucky = base × 2 × 2 = 4×). Positive points only.
- **Points tiers** (`>done`, time from assignment to fortnite.gg-link submission):
  - ≤12h: **10** | ≤24h: **8** | ≤48h: **4** | ≤72h (3d): **2** | ≤96h (4d): **0** | >4d: penalty **−4** the first day over, then **−1 per extra day** (`-(3 + days_over)`)
  - Totals **floor at 0** (`MAX(0, …)` in the DB upsert + startup clamp migration) — penalties never push a balance negative.
- **Role multipliers** (positive points only — penalties never multiplied; the two are `elif`, so they do NOT stack — Head wins if a user has both):
  - Head Loot Routes (`1231187220208025620`): 2×
  - Loot Route Inspector (`1503649126192119839`): 1.5×
- Points are a **single global total per user** (`loot_route_points.total_points`, REAL) — not per-guild; `guild_id` is threaded through the API but storage is global.
- **Role-gated:** `add_loot_route_points` / `set_loot_route_user_points` block users lacking the **Loot Route Maker** role (`1231188006757728266`) — BUT validation is silently skipped if no `bot` is passed or the member isn't cached (points added anyway).
- **Leaderboard** lives on the local **Wave Staff Hub** (`wavedropmaps.pages.dev`, served from the PC), not Discord — **migrated off GitHub Pages 2026-06-14**: `tasks/loot_routes.py` builds a rich JSON payload (players, live rotation queue + `next_up_rank`, lucky-map history, global/weekly trend charts, rank deltas vs `json_data/loot_route_rank_snapshot.json`) and `tasks/staff_hub_writer.push_loot_route_leaderboard_to_github` (formerly `github_sync.py`, now a local-only writer) writes `website/data/loot.json`, served by Flask at `/api/loot`. Debounced **1.5s** (despite "5-second debounce" comments). Roster source = `loot_route_positions` so 0-route makers still appear; anyone who lost the Maker role is filtered out.
- Background loops: hourly reminders (>24h pending), daily cleanup (delete confirmed >30d), Monday weekly MVP.
- Key channels: rotation `1239193678459703447`, claim/notify `1231195722485993512`, leaderboard `1251145459179716618`, maps-not-taken `1205406903463710750`.
- Source of truth = DB. Discord messages are derived displays; never parse them back.
- **Customer-facing queue is a SEPARATE bot** — the **Wave Logistics Bot** (`C:\Users\kiere\Desktop\Wave Logistics Bot`, prefix `-z `) owns the priority request queue (loot/surge routes) in public servers. It does NOT share this DB. Users submit requests via voting or `-z addmap` commands. **Bridge (push model):** `Wave Logistics Bot/Tasks/loot_bridge.py` runs a 60s sweep: fetches undispatched loot requests, posts them to Management bot's `#maps-not-taken` (`1205406903463710750`) with queue code hidden in image filename (`loot-q<code>-p<prio>-<original>.png`). Management bot's `loot_routes.py` watcher extracts the code and stores it with the assignment. On `>done` completion, Management bot fires `-z removequeue <code>` back to Logistics to drop the entry. Loot + surge share ONE Logistics queue (alphabetical code sequence; `route_type` column distinguishes); each user holds max 1 active loot + 1 active surge request (per-type duplicate check). Mac checkout of the Logistics repo: `~/Downloads/wave-logistics-bot-master`.
- **Loot logging migration (Phase 10):** loot route events (auto/manual maker join/leave, weekly MVP, assignment) now *also* emit to the Wave-Logging dashboard via `core.global_logger.log_event(category="loot_routes")` (commit `8de17ac`). The Discord log channels were **kept, not retired** (owner decision) — the dashboard mirrors, it doesn't replace. The duplicate auto join/leave Discord post was removed; the command-triggered one stays (commit `04c1aee`).

### Auto Watermark System 🎨
- **Two commands:** `>dropmapwatermark` (`>dmw`) renders fn.gg drop maps with center + corner logos; `>lootroutewatermark` (`>lrw`) renders fn.gg loot routes at **2560×1440 @ DPR 2** (sharper) with a single small wave logo.
- **Shared pipeline:** Render map (Playwright + Chrome, ~30s, happens ONCE) → optional framing nudge (zoom/pan the crop, no re-render) → grid display (user replies `X Y` or `BL`/`BR` shortcuts for loot routes) → placement preview (red box, confirm/re-place/resize) → opacity picker → output. **Re-place loops reuse the render** — only Playwright never repeats.
- **Rendering strategy:** Uses `window.Drawing` (fn.gg's author-drawn objects) + Leaflet map instance (captured via init hook) to `fitBounds` on all geometry, then zooms out minimum needed for fixed-size text labels to fit. Falls back to legacy DOM/canvas bounds detection if fit data unavailable (e.g. old fn.gg version or no drawing). Content bounds JS scans both DOM elements AND canvas overlay pixel data (fn.gg draws lines/boxes/text on canvas).
- **Detection & placement:** YOLO model (`drop_spot_marker.pt`, 210 MB, cached) finds drop spots (confidence 0.80) on drop maps; falls back to Roboflow API if local model unavailable. Logo auto-placement avoids YOLO boxes, glider-line masks, and text boxes — tries center-up, center-down, sides in priority order.
- **Image processing:** Watermark is a diagonal text tile (seamless, rotated −45°, tuned opacity 59–76/255). Wave logo scales to ~6% of width (corner), text logo ~25% (center, resizable on drop maps). Grid overlay for placement (1% lines, brighter @ 5%, bold @ 10%).
- **Debug/test:** `>rawdropmapwatermark` / `>rawlootroutewatermark` send full uncropped viewport (shows final zoom level). `>zoomtest [step]` renders 5 zoom levels around baseline so user picks which looks right.
- **Assets:** `assets/logo wave.png`, `assets/TEXT_1_1.png`, `assets/watermark_tile.png` (all RGBA), `weights/drop_spot_marker.pt` (must exist).
- **Threading:** ThreadPoolExecutor(max_workers=2) for Playwright; heavy image ops (watermark, cropping) run in executor. Discord loop interleaves UI waits, renders, button handlers.

### Surge Route System ⚡ (parallel to Loot Routes — separate tables/roles/balance)
- A **clone of the Loot Route backbone** for "surge routes," built as a fully parallel product. **Does NOT share loot's tables, roles, or points** — everything is surge-prefixed.
- **Config single-source:** `core/surge_config.py` — every ID/role/channel/tunable/shop entry. Key channels: map-request trigger `1416770574042140804`, claim/notify (assignment card + confirm) `1513082739908153354`, submission (`>surgedone` scans) `1417091772810526760`, **MVP + join/leave announcements** `1414072054457569322` (`SURGE_MVP_CHANNEL_ID`), redemption reuses management `1041584423264596009`.
- **Data layer:** `database_surge.py` (8 surge-prefixed tables: positions, points, assignments, rotation_state, pending_maps, away_dates, alumni, weekly_mvp), wired into `init_database`.
- **Engine:** `tasks/surge_routes.py` — map watcher, assign-or-**hold** (NEW pending-pool: if no maker free, hold the map with ⏳ and auto-assign the oldest-by-priority when one frees up via `drain_pending_pool`), leaderboard builder, 3 loops (reminder 1h, cleanup 24h, MVP Mondays).
- **Commands:** `commands/surge_route_commands.py` — `>addsurgemaker`/`>removesurgemaker` (3-guild role sync + posts join/leave announcement to `SURGE_MVP_CHANNEL_ID`), `>surgerotation`, `>addsurge`, `>cancelsurge`, `>surgedone`, `>surgeredeem`, `>surgeaway`/`>surgeback`, `>setsurgepoints`, `>oversurgepoints`, `>mysurges`, `>surgestats`, `>surgerolecheck`. Admin-gated by `SURGE_ADMIN_ROLES`.
- **Leaderboard:** local **Wave Staff Hub** (`wavedropmaps.pages.dev`, migrated off GitHub Pages 2026-06-14) — `tasks/staff_hub_writer.push_surge_route_leaderboard_to_github` (formerly `github_sync.py`) writes `website/data/surge.json`, served at `/api/surge`.
- **Auto-bootstrap:** "Surge Route Maker" is in `SPECIALTY_ROLES` (`multi_guild_role_commands.py`), so `>dutyrolegive`/`>dutyroleremove` invoke `add/remove_surge_route_maker`.
- **Wave-Logging dashboard:** all surge events log under `category="surge_routes"` (`cfg.WAVE_LOG_CATEGORY`) → `data/manager/surge_routes/`.
- **Cross-bot bridge (push model):** `Wave Logistics Bot/Tasks/surge_bridge.py` runs a 60s sweep: fetches undispatched surge requests, posts them to Management bot's `#surge-maps` (`1416770574042140804`) with queue code hidden in image filename (`surge-q<code>-p<prio>-<original>.png`). Management bot's `surge_routes.py` watcher extracts the code and stores it with the assignment. On `>surgedone` completion, Management bot fires `-z removequeue <code>` back to Logistics to drop the entry. Separate DB.
- Full build history + per-phase smoke-tests: `SURGE_ROUTE_PLAN.md`.
