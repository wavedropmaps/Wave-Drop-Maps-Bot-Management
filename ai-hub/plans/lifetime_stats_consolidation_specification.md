# Lifetime Stats Consolidation — Specification (v1, 2026-06-22)

> **Read this first.** Grounded in the ACTUAL current code + website (verified 2026-06-22),
> with all owner decisions baked in. Written so any agent can pick it up cold.
> Companion to `unified_weekly_loop_specification.md` — this plan EXTENDS the unified loop.
>
> **Golden rule:** READ the files named below + the live website before changing behaviour.
> Do NOT re-derive from memory.

---

## ⭐ HANDOFF — START HERE (for the implementing agent)

**You are building this from scratch. No code for it exists yet. This spec is your complete brief.**

**Prerequisite — already satisfied:** Project 1 (the Unified Weekly Loop) is **built, live, and
committed** (commit `e0421dc9`, `tasks/unified_weekly_loop.py`). This plan hooks into that loop's
hour-168 awards block (`unified_weekly_loop.py:1407`, guarded by
`check_report_already_sent('unified_weekly')`). It is running in production now.

**Ground rules (project-wide, non-negotiable):**
1. **Planning gate** — the owner controls when you write code. If anything is ambiguous, ask; do
   not expand scope. "Remove-only / add-only" means exactly that.
2. **Validation gate** — run `python ai-hub/gates/validate.py` and get exit 0 before claiming done.
3. **Never commit `bot_database.db` or `wave_logging_local/` logs.** Commit only the code/doc files
   you change. Commit to `master` (master-only repo). Do NOT push unless asked.
4. **Migration safety** — the one-time Sheet→DB import (§4) is the ONLY chance to capture lifetime
   history before the Sheets code is deleted. Run it, VERIFY totals, THEN build accumulation, THEN
   delete Sheets code. Order is in §9.
5. **Deleting roles + the WP-bonus mechanism is outward-facing** (touches real Discord roles and
   balances). Re-confirm with the owner immediately before executing §8's role deletion.
6. Update the **Progress Checklist (§11)** as you go, and keep this file the source of truth.

**Decisions are LOCKED in §2 — do not relitigate them.** Plain-count Lifetime tab (no tiers),
reviews summed from `bot_logs`, 3 main tabs + 4 lifetime sub-tabs, separate `/api/lifetime`, delete
Power Points + the 5 badge roles, retire `staff_insights.py`, lifetime = finalized-only.

---

## 0. Goal

Kill the separate **milestones page** and the **Google Sheets dependency**, and move all-time
("lifetime") staff activity into the **database**, surfaced as a **Lifetime tab** on the existing
weekly stats page (`duties_leaderboard.html`). Also drop the Power Points tier/badge/WP system
entirely, and retire `staff_insights.py` (folding what's worth keeping into the unified loop).

---

## 1. System context — how it works TODAY (the "old" system)

### 1.1 Lifetime totals currently live in Google Sheets, NOT a DB
`tasks/staff_insights.py` (own cog `StaffInsightsAutomation`, scheduled **72.5h mid-week + 169h
full week**) scans 4 duties and writes them to **per-duty Google Sheets** in Drive folder
`STAFF_INSIGHTS_FOLDER_ID`. Each sheet layout (`staff_insights.py:943`):
- **A** = staff name · **C** = Rank (ARRAYFORMULA) · **D** = **cumulative all-time total (SUM)** ·
  **E+** = one column per weekly run.
- **The lifetime total is column D — it lives inside the sheet.** This is the persistence layer.

`sync_milestone_totals` (`staff_insights.py:1007`, full-week only) reads col D + latest weekly col →
writes `milestone_totals.json` → `push_milestones_to_github` (local write) → served at
`/api/milestones` → **`website/milestones.html`** (React `website/app.jsx`, title "Wave Staff —
Lifetime Activity").

### 1.2 What staff_insights scans (`scan_duty_activity`, `staff_insights.py:187`)
| Duty | Source | Counts |
|---|---|---|
| message | all readable text channels (both guilds) | every staff message |
| req | request channel | staff replies to others (`is_reply_to_other`) |
| modlog | modlog channel | bot embeds mentioning a staff user ID |
| role | `audit_logs(member_role_update, limit=None)` ⚠️ **unfiltered sweep = freeze bug** | role updates by staff |

Mid-week scans `role`+`req`; full week scans all four. **`role` is otherwise retired and NOT shown
on the page** — but the freeze-prone sweep still runs every full week.

### 1.3 The milestones page (`app.jsx`)
- Reads `/api/milestones`. Shows **3 duties**: Messages, Map Request, Mod Commands (role dropped).
- Per-duty **tier badges** Bronze→God (thresholds in `app.jsx:82`).
- **Power Points** system (`app.jsx:124`): sums tier weights → power tier → Wave Points reward.

### 1.4 Power Points is a LIVE roles + WP mechanism (`tasks/power_points_rewards.py`)
Not just UI. After milestone sync it: (a) **assigns 5 Discord badge roles** in Staff Hub guild
(role IDs below), (b) **awards one-time WP bonuses** per new tier (Bronze 20 → God 500).
Badge role IDs: God `1508413031024169122`, Legend `1508412963718168687`, Gold `1508412960584765441`,
Silver `1508412940489982022`, Bronze `1508412912715436133`.

### 1.5 The live weekly page (`website/duties_leaderboard.html`)
Vanilla JS, fetches `/api/duties` (written hourly by `unified_weekly_loop`). Today 2 tabs:
**General Staff** (`engagement`) + **Map Request** (`duties.req`).

### 1.6 `>goals` depends on `staff_insights_history`
`commands/goals.py:52` reads `database.get_staff_insights_history(uid)` to average the last 4 full
weeks. This DB table (`database.py:3062`) MUST keep being written. (Independent of the page.)

---

## 2. Owner decisions (LOCKED 2026-06-22)
1. **Move lifetime totals to the DB** + one-time import from Sheets so nothing resets to zero.
2. **Accumulate once per week** (at the unified loop's hour-168 awards step, behind the existing
   once-per-week DB guard) — never per hourly tick.
3. **Drop Tiers + Power Points entirely.** WP-bonus mechanism gone, NOT replaced.
4. **Delete the 5 badge roles entirely** from the Staff Hub guild on cutover (removes them from
   everyone + deletes the role objects).
5. **Page layout: 3 main tabs.** `General Staff` · `Map Request` · **`Lifetime`**. The Lifetime tab
   has **4 sub-tabs**: Messages · Mod Commands · Reviews · Map Request (each a sortable all-time
   leaderboard).
6. **Lifetime data served via a SEPARATE file**: `/api/lifetime` → `website/data/lifetime.json`
   (not bolted onto `duties.json`; lifetime changes weekly, not hourly).
7. **Reviews lifetime = direct all-time SUM from `bot_logs`** (authoritative, self-healing) — not
   accumulated.
8. **Retire `staff_insights.py` entirely** — fold lifetime accumulation + `staff_insights_history`
   writing into the unified loop; this also removes the duplicate 169h scan, the 72.5h mid-week
   scan, and the `role` freeze-sweep.
9. **Lifetime = finalized only** — shows totals as of the last completed week (updates once weekly),
   not lifetime + live current week.
10. **Keep `staff_insights_history`** table + `>goals` working.

---

## 3. New DB table

```sql
CREATE TABLE IF NOT EXISTS lifetime_totals (
    user_id     INTEGER NOT NULL,
    metric      TEXT NOT NULL,          -- 'message' | 'modlog' | 'req'  (reviews NOT stored — summed live)
    total       INTEGER NOT NULL DEFAULT 0,
    last_added_week TEXT,               -- start_date of the last week folded in (dup guard)
    updated_at  TEXT,
    PRIMARY KEY (user_id, metric)
);
```
- `reviews` is intentionally NOT in this table — it's summed all-time from `bot_logs` at build time.
- `last_added_week` prevents double-accumulation if the awards step somehow re-runs.

---

## 4. Migration (one-time, must run BEFORE first accumulation)

1. Read each duty sheet's **column D** (cumulative) for `message`, `req`, `modlog` (skip `role`).
2. UPSERT into `lifetime_totals` as the baseline (`last_added_week` = current `start_date` so the
   very next hour-168 doesn't double-add the current week).
3. `reviews` needs no import — it's summed from `bot_logs` all-time.
4. This is a throwaway script (keep it in `migrations/`); it needs Google creds, which still exist
   at migration time. After it runs + is verified, the Sheets code is deleted.

**Order is critical:** import → verify totals look right → THEN deploy the accumulation step.

---

## 5. Accumulation (in the unified loop, hour 168)

At the existing once-per-week awards block (`unified_weekly_loop.py:1407`, already guarded by
`check_report_already_sent('unified_weekly')`):
1. For each general-staff user, add this finalized week's `message`, `modlog`, `req` counts into
   `lifetime_totals` (guard with `last_added_week != start_date`).
2. Write `staff_insights_history` for `>goals` (port the existing write from staff_insights).
3. Rebuild `lifetime.json` (see §6) and write it locally.

No accumulation on hourly ticks — only here.

---

## 6. `lifetime.json` schema (served at `/api/lifetime`)

```json
{
  "_meta": { "last_updated": "ISO", "as_of_week": "14/06/2026" },
  "users": {
    "<uid>": {
      "user_id": "<uid>", "name": "...", "top_role": "...", "avatar_url": "...",
      "lifetime": { "message": 0, "modlog": 0, "req": 0, "reviews": 0 }
    }
  }
}
```
- `message/modlog/req` from `lifetime_totals`; `reviews` from the all-time `bot_logs` SUM.
- Add `lifetime` to `web_api.py`'s `_API_PAGES` allowlist so `/api/lifetime` serves.

---

## 7. Frontend (`website/duties_leaderboard.html`)

- Add a 3rd main tab **Lifetime**; fetch `/api/lifetime` (lazy — only on first open).
- Lifetime has **4 sub-tabs**: Messages · Mod Commands · Reviews · Map Request. Each = a sortable
  leaderboard of `lifetime[metric]` desc, reusing the existing row/avatar/name components.
- **Plain counts only** — no tiers, no badges, no power points.

---

## 8. Deletions / cleanup (after migration verified)

| Target | Action |
|---|---|
| `tasks/staff_insights.py` | archive → `ai-hub/deprecated/old-code/` (scan + Sheets + 72.5h/169h cog all go) |
| `tasks/power_points_rewards.py` | archive → deprecated |
| The 5 badge roles (IDs in §1.4) | **delete the role objects** from Staff Hub guild (one-time admin action / script) |
| `website/milestones.html` | delete |
| `website/app.jsx` | **delete** — VERIFIED only `milestones.html` loads it (`app.jsx:48` ref), so safe |
| `_API_PAGES` in `web_api.py:23` | remove `'milestones'`, **add `'lifetime'`** |
| `website/data/milestone_totals.json`, `milestone_totals.json` (root) | delete |
| `push_milestones_to_github` (`tasks/staff_hub_writer.py`) | remove after the call sites below are gone |
| `commands/automation_config.py` | remove `>forcereportstaffinsights` (~L586) + `>forcereporthalfweekstaffinsights` (~L666) **and** the milestone-sync block calling `push_milestones_to_github` (~L768–904); also help lines at `utilities.py:928–929` and `automation_config.py:144–145` |
| `tasks/__init__.py` | drop any staff_insights/power_points imports (verify none remain) |
| `main.py` | re-point/remove any staff_insights or power_points references |
| `tasks/power_points_rewards.py` | archive → deprecated (DUTY_THRESHOLDS/POWER_TIERS/role IDs live here) |

⚠️ `main.py` auto-loads every `tasks/*.py` — moving the two task files out of `tasks/` unloads them.

---

## 9. Build order
1. Add `lifetime_totals` table + DB helpers (get/upsert/sum, all-time reviews query).
2. Write + run the one-time Sheet→DB migration; **verify totals**.
3. Add accumulation + `staff_insights_history` write + `lifetime.json` build to the unified loop's
   hour-168 step.
4. Add `/api/lifetime` to `_API_PAGES`; build the Lifetime tab + 4 sub-tabs in
   `duties_leaderboard.html`; verify both render off real data.
5. Archive `staff_insights.py` + `power_points_rewards.py`; delete milestones page/app/route/json;
   remove the force commands.
6. Delete the 5 badge role objects from the Staff Hub guild.
7. `python ai-hub/gates/validate.py` must exit 0.

---

## 10. Hard "do NOT" list
- ❌ Do not deploy accumulation before the Sheet→DB import (week 1 would stack on zero).
- ❌ Do not accumulate on hourly ticks — only at the hour-168 guarded step.
- ❌ Do not store `reviews` in `lifetime_totals` — sum it from `bot_logs` (self-healing).
- ❌ Do not keep the `role` audit-log `limit=None` sweep — it dies with `staff_insights.py`.
- ❌ Do not break `staff_insights_history` / `>goals`.
- ❌ Do not add tiers/badges/power-points to the new Lifetime tab — plain counts only.

---

## 11. Progress checklist (implementing agent: tick as you go)

- [ ] **DB layer** — add `lifetime_totals` table (§3) + helpers: upsert/add, get-all, and an
      all-time reviews SUM from `bot_logs` (reuse the query shape in `unified_weekly_loop.py`'s
      `scan_reviews`).
- [ ] **Migration script** (`migrations/`) — read Sheets col D for message/req/modlog → UPSERT
      baseline with `last_added_week = current start_date`. RUN IT. **Verify totals look sane.**
- [ ] **Accumulation** — in `unified_weekly_loop.py` hour-168 block, add message/modlog/req to
      `lifetime_totals` (guard `last_added_week != start_date`); also write `staff_insights_history`
      (port from `staff_insights.py`); rebuild + write `lifetime.json`.
- [ ] **API** — add `'lifetime'` to `web_api.py:23` `_API_PAGES`; confirm `/api/lifetime` serves.
- [ ] **Frontend** — `duties_leaderboard.html`: add 3rd main tab `Lifetime` with 4 sub-tabs
      (Messages/Mod/Reviews/Map Request), plain sortable counts, lazy-fetch `/api/lifetime`.
- [ ] **Retire** — archive `staff_insights.py` + `power_points_rewards.py` to deprecated.
- [ ] **Delete milestones** — `milestones.html`, `app.jsx`, `milestone_totals.json`,
      `_API_PAGES` 'milestones', `push_milestones_to_github` + its call sites, the 2 force commands.
- [ ] **Delete the 5 badge roles** from the Staff Hub guild (CONFIRM with owner first).
- [ ] **Validate** — `python ai-hub/gates/validate.py` exit 0.
- [ ] **Restart bot** (supervisor / UTF-8 launch) → confirm unified loop loads, no errors on
      staff_insights/power_points, milestones page 404s cleanly.
- [ ] **Commit** (scoped; no DB/logs). Do not push unless asked.

## 12. Extra implementation notes / ideas

- **Testing without waiting a week:** the hour-168 accumulation is hard to test live. Add a
  temporary manual trigger (or a `>force` path) that runs the accumulation+lifetime.json build once
  for the current week, so you can verify end-to-end, then remove it. Guard against double-add via
  `last_added_week`.
- **Reuse, don't reinvent:** `name`, `top_role`, `avatar_url` for `lifetime.json` can come from the
  same helpers the unified loop already uses (`_get_member_role_info`, the avatar prefetch). Don't
  write a second role/avatar resolver.
- **Reviews are self-healing:** because lifetime reviews are summed live from `bot_logs` each build,
  they auto-correct if `bot_logs` is backfilled. Don't store them in `lifetime_totals`.
- **Migration is one-shot + irreversible-ish:** once the Sheets code is deleted you can't re-pull
  col D. Keep the migration script in `migrations/` (don't delete it) as the historical record of
  the baseline import.
- **Role deletion:** needs Manage Roles in the Staff Hub guild; role IDs are in §1.4. A one-time
  admin command or script is fine. This removes the badges from every member automatically.
- **Population note:** lifetime messages/mod/reviews are general-staff metrics; req is duty-holders.
  Each sub-tab should just filter to users who have data for that metric (same as the weekly tabs).

*Created 2026-06-22 (v1). Updated 2026-06-22 with handoff block, verified cleanup targets, progress
checklist + impl notes. Companion to unified_weekly_loop_specification.md (Project 1, live @ e0421dc9).*
