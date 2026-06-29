# Unified Weekly Loop — Specification (v2, rewritten 2026-06-22)

> **Read this first.** This v2 replaces the original spec, which was written against a
> wrong model of the live code and would have deleted the Map Request economy. This
> version is grounded in the ACTUAL current code + website and bakes in the owner's
> decisions. It is written so any agent can pick it up cold — no prior context needed.
>
> **Golden rule for whoever builds this:** before changing behaviour, READ the files
> named below and the live website page. Do NOT re-derive from memory.

---

## 0. System context — how things work TODAY (the "old system")

### 0.1 The data flow (live)
```
config.json (global_dates: start_date/end_date, DD/MM/YYYY, UTC)
        │
        ▼
tasks/duties_scan.py        ── runs every 4h (00/04/08/12/16/20 UTC)
   scans: req, modlog, message, reviews → caches to DB
   writes: website/data/duties.json   (via tasks/staff_hub_writer.py, LOCAL file write)
        │
        ▼
web_api.py  (Flask)  serves  GET /api/duties  ← reads website/data/duties.json off disk
        │
        ▼
website/duties_leaderboard.html   (two tabs: "General Staff" + "Map Request")
```
There is **no GitHub** in this path anymore — `staff_hub_writer.py` writes the local
file and Flask serves it. (`push_duties_to_github` is a legacy name; it's local now.)

### 0.2 The three tasks today
| File | Cadence | Role |
|---|---|---|
| `tasks/duties_scan.py` | **every 4h** | THE scanner. Builds `duties.json` (`_build_unified_hub_payload`), runs challenge completion checks, applies `>setdivisor`/override, updates VBucks LB, pre-fetches avatars. |
| `tasks/weekly_checks.py` | **72h (Mid-Week) + 168h (Full Week)** + 30-min role monitor | THE awards engine. Mid-week warnings; Full-Week Map Request placement awards (150/100 WP), −200 WP Bad penalties + duty-role removal, away/new-staff exemptions, results DMs; `_augment_duties_hub_json` overlays award/penalty outcomes into `duties.json` + snapshots `weeks[]`. |
| `tasks/staff_sheet.py` | **already retired** (cog loads but starts no task) | Holds Google Sheets export + a separate "10 WP to rank_total≥100" rule. Dormant. |

### 0.3 The website page (`website/duties_leaderboard.html`)
- **General Staff tab** → reads `users[*].engagement` → `{messages, days_active, mod_commands, reviews, rank_messages, rank_days, rank_total}`. Sorted by `rank_total`.
- **Map Request tab** (`buildDuty`, ~line 351) → reads `users[*].duties.req` → `{count, rank, position, ...}`. Columns: rank #, Member, **Requests**, **Performance** pill, **WP Penalty** (renders `−200 WP` when rank == Bad and not away).
- Away users render an "Away" pill instead of a rank.

### 0.4 The score math (LIVE — KEEP EXACTLY)
From `tasks/duties_scan.py:931`:
```python
rank_messages = min(ceil(messages / 70 * 100), 100)
rank_days     = min(ceil(days_active / 7 * 100), 100)
rank_total    = min(ceil((rank_messages + rank_days) / 2 + mod_commands + reviews), 100)
```
messages & days are **averaged**, then mod + reviews are **added on top**, capped at 100.
**This stays as-is.** (The old spec wrongly divided all four by 2 — do NOT do that.)

### 0.5 Away + new-staff immunity (KEEP)
- **Away** — `core/helpers.py:241` `check_if_user_is_away(bot, uid)` → true if member has
  `AWAY_ROLE_ID` *or* `AWAY_IMMUNITY_ROLE_ID`. Away users are **skipped by penalties** and
  shown as "Away". `is_user_normal_away()` only drives the 🏖️ display tag.
- **New-staff (<4 days)** — table `role_assignments` (`database.py:526`). `log_role_assignment`
  (INSERT-OR-IGNORE, first-seen only) + `get_role_assignment_date`. A user assigned a duty role
  < 4 days ago is **immune**: shown but no rank judgement, no penalty, no award.

---

## 1. What we're actually doing (the "new system")

Consolidate the **scanner** and the **awards engine** into ONE file `tasks/unified_weekly_loop.py`
that runs **hourly**, is config-driven, and preserves every reward/penalty/exemption path.
This is a **refactor + cadence change**, NOT a behaviour rewrite.

### 1.1 Old → New, at a glance
| Concern | OLD | NEW |
|---|---|---|
| Scanner cadence | every 4h (`duties_scan`) | **every hour** (incremental — see §3) |
| Awards trigger | 72h + 168h (`weekly_checks`) | **hour 168 only** (Full Week) |
| Mid-week **warnings** | sent at 72h | ❌ **removed** |
| Mid-week **challenges** | `random_challenges` own loop @ +73h | ✅ **kept, untouched** (separate file/loop) |
| Map Request awards/penalties/role-removal | `weekly_checks` 168h | ✅ **kept** (move into unified loop awards step) |
| Rank-100 engagement reward | retired "10 WP" in `staff_sheet` | ✅ **30 WP + DM** to **everyone** with `rank_total == 100` |
| rank_total formula | `duties_scan:931` | ✅ **identical** |
| Away / new-staff immunity | exemption at awards | ✅ **kept**; new-staff check **folded into hourly scan** (drops the separate 30-min loop) |
| `>setdivisor` / overrides | applied in scan + weekly_checks | ✅ **kept**, wired into the unified loop |
| modlog scan method | modlog-channel embed read (`scan_modlog_for_member`) | ✅ **keep channel-embed method** — NOT audit-log sweeps (those froze the bot 10–20 min) |
| Weekly challenges completion | called from scan | ✅ **kept** (call `check_and_complete_challenges` from hourly scan) |
| VBucks leaderboard update | called from scan | ❌ **removed** (not needed) |
| `weeks[]` history snapshot | written by `weekly_checks` | ❌ **removed** (site now does file-stats history) |
| Google Sheets export | `staff_sheet` | ❌ **archived** to `ai-hub/deprecated/old-code/` |

---

## 2. Week lifecycle (config-driven)

- Week dates live in `config.json['global_dates']` as `start_date`/`end_date` (`DD/MM/YYYY`, UTC).
- Convert with `core.helpers.get_start_datetime` / `get_end_datetime`.
- **New-week detection:** every hourly tick, compare `start_date` to the in-memory `current_week`.
  If changed → reset per-week flags (`awards_done = False`), clear/rotate the incremental cache.
- **Hours elapsed** = `(now_utc - start_dt).total_seconds() / 3600`.
- **Awards fire once** at `hours_elapsed >= 168` and guarded by a DB marker (`mark_report_sent`
  / `check_report_already_sent`, report_type `'unified_weekly'`) so a restart can't double-award.
- Challenges are NOT handled here — `tasks/random_challenges.py::challenge_scheduler` keeps its
  own loop (week-start + mid-week + new-week wait). The unified loop only calls
  `check_and_complete_challenges(bot, all_stats)` after each scan to award completions.

---

## 3. Hourly scan — make it cheap (the one new bit of engineering)

The live scan crawls every readable channel in both source guilds with rate-limit delays.
Running that **hourly** at full re-scan = 4× today's load + clashes with the 168h awards.
So the hourly scan must be **incremental**:

- Track a per-week "last scanned at" timestamp.
- Each hour, fetch only messages **after** the last scan, add deltas into the DB cache
  (existing `database.get/set_cached_user_stats`, or a small `duties_weekly_cache` table).
- `req` and `modlog` (channel-embed reads) and `reviews` (DB query, no API) are cheap — keep.
- On **new-week detection**, reset the cache so counts start from zero.
- Keep a **clash guard**: if the tick lands within the awards window, run the final full scan
  then awards, and don't double-run.

modlog scanning stays the **channel-embed** method (`scan_modlog_for_member`) or, if true audit
logs are wanted, the **`user=member` server-side-filtered** form (`duties_scan.py:329`). Never the
unfiltered `audit_logs(action=message_delete)` sweep.

---

## 4. Awards phase (hour 168) — preserve ALL of it

Run a final scan to lock the week, then in order:

### 4.1 Map Request duty (unchanged from `weekly_checks.py`)
- Rank each member by `req` count (Full Week thresholds: Bad <10, Good 10–20, Very Good 21–40, Great 41+).
- **Placement awards:** #1 → 150 WP, #2 → 100 WP (only if count ≥ threshold).
- **Bad penalty:** if rank == Bad and **not away** and **not new-staff**:
  - WP ≥ 200 → deduct 200 WP (role kept).
  - WP < 200 → **remove the Map Request role** across all guilds.
- Write outcomes (`wp_earned`, `penalty_amount`, `role_removed`) back into `duties.json`
  (`users[uid].duties.req`) so the website's WP-Penalty column stays accurate.
- Send the combined results DM to each scored member.

### 4.2 Engagement rank-100 reward (the changed bit)
- For every user with `engagement.rank_total == 100`:
  - award **30 WP** (was 10),
  - send a congratulations DM.
- Keep the current "==100 → reward" logic exactly (owner wants it this way — yes, many active
  staff will hit it; that is intended).
- **Away check only — NOT new-staff.** (Decision 2026-06-22.) New-staff immunity exists to shield
  people from *penalties* before they've had a fair week. The rank-100 bonus has **no penalty
  side**, so a new staffer earning it early is harmless and allowed. Do NOT add a new-staff guard
  here — that is intentional, not a bug. (New-staff immunity applies ONLY to the Map Request duty
  in §4.1, which is the only thing with a penalty.)

### 4.3 Exemptions
- **Map Request duty (§4.1):** apply **both** away AND new-staff guards (it has penalties).
- **Rank-100 engagement bonus (§4.2):** apply **away only** (no penalty → no new-staff guard).

```python
# Map Request duty (penalty path):
if check_if_user_is_away(bot, uid): skip penalty/award
if user_assigned_less_than_4_days_ago(uid, 'req'): skip penalty/award

# Rank-100 bonus (reward only):
if check_if_user_is_away(bot, uid): skip   # away ONLY by design
```
New-staff first-seen recording is now done inside the hourly scan (it already walks the roles),
so the standalone 30-min `monitor_role_assignments` loop is removed.

---

## 5. duties.json schema (unchanged — the website depends on it)

Top level: `{ "_meta": {...}, "users": { "<uid>": {...} } }` (no `weeks[]` anymore).
Each user: `user_id, name, top_role, role_tier, avatar_url, is_away` (+ optional `away_type`),
plus:
- `engagement` (general staff): `messages, days_active, mod_commands, reviews, rank_messages, rank_days, rank_total`
- `duties.req` (Map Request holders): `count, rank, rank_emoji, position, total_in_duty, wp_earned, penalty_amount, role_removed`

Reuse `_build_unified_hub_payload` from `duties_scan.py` as the starting point.

---

## 6. Files

### CREATE
- `tasks/unified_weekly_loop.py` — merges the scan (incremental) + the 168h awards + exemptions + overrides + challenge-completion call.

### MODIFY
- `config.json` — (optional) add a configurable scan cadence if we don't hardcode hourly.
- `commands/manual_duties.py` / `>setdivisor` path — point overrides at the unified loop (logic unchanged).

### ARCHIVE → `ai-hub/deprecated/old-code/`
- `tasks/staff_sheet.py` (Google Sheets export + retired trigger)
- `tasks/duties_scan.py`
- `tasks/weekly_checks.py`

Each gets a `RETIRED.md` pointing here. **Note:** `main.py` auto-loads every `tasks/*.py`
(`find_cog_files`, ~line 841), so MOVING the old files out of `tasks/` is what unloads them —
no manual cog-list edit needed. Also re-point `main.py:955`
(`from tasks.duties_scan import post_duty_info_embeds`) to the new module.

### KEEP UNTOUCHED
- `tasks/random_challenges.py` (own scheduler loop, week-start + mid-week challenges)
- `core/helpers.py` (away helpers, datetime helpers, safe_history_fetch)
- `database.py` (`role_assignments`, cache, `mark_report_sent`)
- `web_api.py` + `website/duties_leaderboard.html` (consumers — schema must stay compatible)

---

## 7. Build / migration order
1. Build `unified_weekly_loop.py` next to the old tasks (don't delete yet).
2. Temporarily disable the old cogs' loops (or test on staging) to avoid double scans.
3. Verify `duties.json` still matches the website schema (both tabs render).
4. Run one simulated cycle: new-week reset → hourly increments → hour-168 awards (once).
5. Confirm: placement awards, Bad penalties/role-removal (away + new-staff exempt), 30-WP rank-100 DMs (away exempt only — new staff eligible by design), override/divisor, challenge completions.
6. Move the three old files to `ai-hub/deprecated/old-code/` + add RETIRED.md; re-point the `post_duty_info_embeds` import.
7. `python ai-hub/gates/validate.py` must exit 0 before claiming done.

---

## 8. Hard "do NOT" list (mistakes from v1)
- ❌ Do not change the `rank_total` formula. Keep `(rank_messages+rank_days)/2 + mod + reviews`, cap 100.
- ❌ Do not use `audit_logs(action=message_delete)` for modlog. Channel-embed read (or `user=`-filtered).
- ❌ Do not full-re-scan every hour. Increment from last scan.
- ❌ Do not drop Map Request placement awards / penalties / role-removal.
- ❌ Do not remove away or new-staff exemptions from the **Map Request duty** (§4.1).
- ❌ Do NOT add a new-staff guard to the **rank-100 bonus** (§4.2). Away-only is intentional — the bonus has no penalty, so new staff are eligible. (A future agent "fixing" this would be reverting an owner decision.)
- ❌ Do not break the `duties.json` schema the website reads (`engagement` + `duties.req`).
- ❌ Do not touch the challenges loop, except to keep calling `check_and_complete_challenges`.

*Last updated: 2026-06-22 (v2). Supersedes v1, which was archived as inaccurate.*
