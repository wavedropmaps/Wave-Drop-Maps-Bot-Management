# Drop Map Reviewing — Full Removal Guide

Everything the coder needs to (1) strip reviewing from the bot cleanly and (2) archive it so it can be rebuilt from one prompt.

---

## Step 0 — Create the archive folder first (before touching anything)

```
old code/
└── reviewing old code folder/
    ├── reviewing_commands.py          ← copy of commands/reviewing_commands.py
    ├── drop_map_reviewing_config.py   ← copy of commands/drop_map_reviewing_config.py
    ├── reviewing_tasks.py             ← copy of tasks/reviewing_tasks.py
    ├── reviewing_leaderboard_final.html ← copy of website/reviewing_leaderboard_final.html
    ├── drop_map_reviewing.json        ← copy of json_data/drop_map_reviewing.json
    ├── SYSTEM_OVERVIEW.md             ← see Section 6 below
    ├── DATABASE_SCHEMA.md             ← see Section 7 below
    └── REBUILD_PROMPT.md              ← see Section 8 below
```

Copy all source files verbatim before deleting anything. Archive first, delete second.

---

## Step 1 — Delete these files entirely

| File | Notes |
|------|-------|
| `commands/reviewing_commands.py` | 3,882 lines — the full cog |
| `commands/drop_map_reviewing_config.py` | 101 lines — config constants |
| `tasks/reviewing_tasks.py` | 354 lines — background loops |
| `website/reviewing_leaderboard_final.html` | 4,853 lines — the Staff Hub page |
| `website/data/reviewing.json` | Staff Hub data payload |
| `json_data/drop_map_reviewing.json` | Local JSON snapshot |
| `wave-leaderboard-repo/reviewing_leaderboard_final.html` | Deprecated copy (already unused) |
| `wave-leaderboard-repo/drop_map_reviewing.json` | Deprecated copy (already unused) |
| `wave-leaderboard-repo/preview_reviewing.png` | Deprecated preview image |
| `commands/__pycache__/reviewing_commands.cpython-312.pyc` | Compiled cache |
| `commands/__pycache__/drop_map_reviewing_config.cpython-312.pyc` | Compiled cache |
| `tasks/__pycache__/reviewing_tasks.cpython-312.pyc` | Compiled cache |

**Windows only (after pulling):** delete `reviewers.db` from the bot desktop folder. It's a standalone SQLite file used only by reviewing. Causes no errors if left — it just sits there unused.

---

## Step 2 — Surgical removals from shared files

### `main.py` — remove lines 1183–1201 (entire try block)

```python
# DELETE THIS ENTIRE BLOCK:
    try:
        print("[GITHUB] Syncing latest data to GitHub...")
        from tasks.staff_hub_writer import push_drop_map_leaderboard_to_github

        # Fetch all reviewer stats and push to GitHub
        all_stats = await database.get_all_reviewer_leaderboard_stats()
        payload = {
            "reviewers": all_stats,
            "last_updated": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        success = await push_drop_map_leaderboard_to_github(payload)
        if success:
            print("[OK] Latest data pushed to GitHub on shutdown")
        else:
            print("[WARNING] Failed to push data to GitHub")
    except Exception as e:
        logger.error(f"Error pushing to GitHub on shutdown: {e}")
        print(f"[WARNING] Error pushing to GitHub on shutdown: {e}")
```

---

### `web_api.py` — line 23

Remove `'reviewing'` from the `_API_PAGES` list. The line currently reads:

```python
'economy', 'reviewing', 'daily_summary', 'session_history',
```

Change to:

```python
'economy', 'daily_summary', 'session_history',
```

---

### `tasks/staff_hub_writer.py`

**Line 40** — remove from the file-rename dict:
```python
'drop_map_reviewing.json': 'reviewing.json',   # DELETE this line
```

**Line 79** — remove this call:
```python
write_local_payload('reviewing.json', leaderboard_data)   # DELETE this line
```

**Line 110** — the `reset_staff_hub_file()` function docstring mentions reviewing. Check if the function itself is reviewing-only or shared with other systems. If reviewing-only, delete the whole function. If shared, just update the docstring.

---

### `commands/utilities.py`

**Line 722** — remove this entry from the tab list:
```python
('reviewing',      '👁️ Drop Map Reviewing',  'Daily workflow & reviewer mgmt'),
```

**Lines 1519–1622** — delete the entire `get_reviewing_embed()` method:
```python
def get_reviewing_embed(self):
    ...  # 103 lines, ends at line 1622
```

Also check the `AdminHelpView` dropdown switch statement — there will be a `case 'reviewing':` or `elif section == 'reviewing':` branch that calls `get_reviewing_embed()`. Remove that branch too.

---

### `database_backups/database_backup.py`

**Line 46** — remove from backup list:
```python
"reviewers.db",
```

**Line 50** — remove from backup list:
```python
"json_data/drop_map_reviewing.json",
```

**Line 103** — remove from WAL checkpoint list:
```python
_WAL_DBS = ["bot_database.db", "reviewers.db", "wave_bot.db"]
# Change to:
_WAL_DBS = ["bot_database.db", "wave_bot.db"]
```

---

### `database.py` — the big one (273 references across lines 165–5821)

This is the most complex file. Work top-to-bottom. Each section is clearly commented in the source.

#### 2a. Startup integrity check — lines ~165–187

Remove the block that does `SELECT COUNT(*) FROM reviewers` during startup validation. It's inside the `validate_data_integrity()` function or similar. Find and remove just the reviewers check — leave the rest of the integrity checks untouched.

#### 2b. Table definitions in `init_database()` — lines 743–1028

Remove the entire `# ==================== DROP MAP REVIEWING SYSTEM ====================` block. It starts at line 743 and covers these tables and their indexes:

| Table | Approx line |
|-------|-------------|
| `reviewers` | 747 |
| `reviewer_markers` | 766 |
| `ghost_markers` + index | 783 |
| `accuracy_streaks` | 800 |
| `daily_streaks` | 814 |
| `reviewer_maps` (submitted maps) | ~825 |
| `marker_reviews` | 850 |
| `helper_assists` | 882 |
| `daily_bonus_maps` | 897 |
| `daily_sessions` | 921 |
| `session_counter` | 934 |
| `daily_activity_log` | 960 |
| `reviewers_temp` + indexes | 984 |

All tables from line 743 to ~1028 are reviewing-only. Safe to remove the entire block.

#### 2c. Migration functions — lines 2402–2500

Remove these 4 functions:
```
migrate_reviewers_temp_add_streak_columns()       line 2402
migrate_reviewers_add_last_streak_settle_date()   line 2426
migrate_reviewers_add_tier_locked()               line 2444
cleanup_drained_ghost_markers()                   line 2500
```

#### 2d. Reviewer management functions — lines 3509–3875

Remove these 4 functions:
```
add_drop_map_reviewer(user_id, bot)    line 3509
remove_drop_map_reviewer(user_id, bot) line 3608
sync_reviewer_usernames(bot)           line 3753
cleanup_drop_map_reviewers(bot)        line 3802
```

Note: `add_drop_map_reviewer` and `remove_drop_map_reviewer` are also called from `commands/multi_guild_role_commands.py` when granting/removing the Drop Map Reviewer role. Search that file for those calls and remove the lazy imports and calls. The role sync itself can stay — just remove the reviewing DB hook.

#### 2e. Core reviewing logic — lines 3875–4438

Remove these functions in one block:
```
calculate_tier_from_accuracy()         line 3875
update_reviewer_tier()                 line 3889
recalculate_all_reviewer_tiers()       line 3947
calculate_final_points()               line 3993
update_accuracy_streak()               line 4003
update_daily_streak()                  line 4072
apply_penalty()                        line 4142
get_reviewer_leaderboard_stats()       line 4192
get_all_reviewer_leaderboard_stats()   line 4242
```

Stop at line ~4438 — `get_vbucks_leaderboard()` at line 4438 belongs to VBucks, NOT reviewing. Do not remove it.

#### 2f. Activity logging — lines 4863–4950

Remove:
```
log_daily_activity()          line 4863
get_daily_activity_summary()  line 4893
get_next_session_id()         line 4950
```

#### 2g. Daily challenges system — lines 5054–~5820

Remove the entire challenges block:
```
migrate_create_daily_challenges_tables()     line 5054
_challenge_by_id()                           line 5151
_eval_marathon_day()                         line 5162
_eval_stack_king()                           line 5170
_eval_single_sub_volume()                    line 5178
_eval_lucky_7()                              line 5186
_eval_high_roller()                          line 5195
_eval_variety_hour()                         line 5203
_eval_perfect_5()                            line 5211
_eval_quality_control()                      line 5222
_eval_first_reviewer()                       line 5236
_eval_early_bird()                           line 5244
_eval_quiet_hero()                           line 5264
_eval_hat_trick()                            line 5280
_eval_cleanup_crew()                         line 5298
_eval_even_steven()                          line 5306
_eval_steady_hand()                          line 5314
_eval_odd_eddie()                            line 5327
_eval_mirror()                               line 5335
_eval_first_cleanup()                        line 5345
_eval_first_strike()                         line 5355
_eval_rolling_stone()                        line 5365
_eval_lone_wolf()                            line 5385
_eval_diamond_run()                          line 5413
_eval_burst_mode()                           line 5422
_eval_marathon_leader()                      line 5456
pick_challenges_for_session()                line 5505
evaluate_challenges_for_reviewer()           line 5550
award_challenge_bonuses()                    line 5662
get_challenges_for_session()                 line 5699
```

Stop before `get_market_tier()` at line 5821 — that belongs to the economy system.

---

### `commands/multi_guild_role_commands.py`

Search for `add_drop_map_reviewer` and `remove_drop_map_reviewer`. There will be lazy imports and calls when the `Drop Map Reviewer` role is granted/removed. Remove those calls. The role sync wizard itself stays — just cut the reviewing DB hook that fires alongside it.

---

## Step 3 — Verify bot loads cleanly

After all removals, restart the bot (or on Mac, do a dry import check):

```bash
python -c "import main" 2>&1 | head -40
```

The bot should load all cogs without `ImportError` or `AttributeError`. Common issues to catch:
- Something still importing `from commands.reviewing_commands import ...`
- `utilities.py` still calling `get_reviewing_embed()` somewhere
- `multi_guild_role_commands.py` still lazy-importing the removed DB functions

---

## Step 4 — Commit message

```
Remove Drop Map Reviewing system entirely

Deleted: reviewing_commands.py, drop_map_reviewing_config.py,
reviewing_tasks.py, reviewing_leaderboard_final.html, and related
JSON/data files. Surgical removals from database.py (15 tables, ~40
functions), main.py, web_api.py, utilities.py, staff_hub_writer.py,
database_backup.py, and multi_guild_role_commands.py.

All source files and system documentation archived to:
old code/reviewing old code folder/
```

---

## Section 6 — SYSTEM_OVERVIEW.md (copy into archive)

### Drop Map Reviewing — How It Works

**Purpose:** Staff members review Fortnite drop map submissions. They check marker placements for accuracy, earn points based on speed and correctness, climb tiers, and redeem points for real rewards (AUD payouts, VBucks, roles).

---

### Session Flow

1. Admin runs `>newday` to open a session (creates a `daily_sessions` record, picks challenges, picks bonus map).
2. Reviewers claim maps via `>claim [map_id]` — first-come, fastest base points.
3. Reviewer checks markers, submits via `>submit [map_id] [correct] [total] [link]`.
4. Bot calculates points: `base_pts × marker_count × tier_multiplier × bonus_multiplier`.
5. Points are written to `reviewers` table, accuracy recalculated, tier updated.
6. Accuracy streak and daily streak are updated. Milestones trigger bonus awards.
7. At day end, admin runs `>endday` to close the session and post the daily summary.

---

### Tier System (based on last 30 markers)

| Tier | Accuracy | Multiplier |
|------|----------|------------|
| Master | ≥ 96.67% | 4× |
| Expert | ≥ 90% | 3× |
| Advanced | ≥ 83.33% | 2× |
| Intermediate | ≥ 76.67% | 1.5× |
| Beginner | < 76.67% | 1× |

Tier is recalculated on every submission from the sliding window of last 30 real markers (ghost markers are used to seed new reviewers).

---

### Base Points by Claim Speed

| Claim window | Base pts |
|-------------|----------|
| ≤ 1 min | 4 |
| ≤ 5 min | 3 |
| ≤ 30 min | 2 |
| ≤ 60 min | 1.5 |
| > 60 min | 1 |

---

### Point Formula

```
final_points = round(base_pts × marker_count × tier_multiplier)
if bonus_map: final_points × 2
```

Bonus map (daily lottery): one random map per session is flagged `is_daily_bonus_map`. First reviewer to complete it gets 2× multiplier.

---

### Accuracy Streak System

- Tracks consecutive perfectly-correct marker submissions (0 mistakes on a map).
- **Resets to 0 on any mistake** (wrong marker placement).
- Milestones trigger bonus points (one-time per streak, resets on streak break):

| Streak | Bonus |
|--------|-------|
| 5 | +10 pts |
| 9 | +100 pts |
| 19 | +300 pts |
| 37 | +750 pts |
| 50 | +2,000 pts |
| 1,000 | +8,000 pts (Legendary) |

---

### Daily Streak System

- Tracks consecutive days with at least 1 verified submission.
- Skipping a day resets it.
- Sessions where 0 markers are correct do NOT count.
- Milestones:

| Days | Bonus |
|------|-------|
| 2 | +10 pts |
| 5 | +100 pts |
| 14 | +300 pts |
| 30 | +750 pts |
| 180 | +8,000 pts |
| 365 | +20,000 pts |

---

### Penalty Types

| Type | Deduction |
|------|-----------|
| `marker_mistake` | -20 pts |
| `skipped_oldest` | -20 pts + lose base pts for that map |
| `unclaimed_map` | -10 pts per 30 min interval (not 22:00–12:00 UTC) |
| `abandoned_review` | -10 pts |
| `no_thread` | -10 pts |
| `incomplete_claim` | -30 pts |
| `other` | variable |

Points floor at 0 — penalties never push balance negative.

---

### Helper Assist System

- A reviewer can call in a helper for a complex map.
- If the helper's assessment matches the final result: helper +10 pts.
- If helper is wrong: helper -10 pts.
- Tracked in `helper_assists` table.

---

### Ghost Markers

- New reviewers have no accuracy history (last 30 = empty → 0%).
- Ghost markers are synthetic correct-marker rows seeded at onboarding to give new reviewers a fair starting accuracy (~96.67% by default — Master tier).
- They drain out naturally as real submissions fill the 30-marker window.
- Admin can override ghost marker counts with `>setoverride`.

---

### Daily Challenges

Each session, the bot picks a set of challenges from a fixed catalogue. Reviewers earn bonus points by hitting challenge targets during the session. Evaluated at session close.

Challenge catalogue (with eval functions in database.py):
`marathon_day`, `stack_king`, `single_sub_volume`, `lucky_7`, `high_roller`, `variety_hour`, `perfect_5`, `quality_control`, `first_reviewer`, `early_bird`, `quiet_hero`, `hat_trick`, `cleanup_crew`, `even_steven`, `steady_hand`, `odd_eddie`, `mirror`, `first_cleanup`, `first_strike`, `rolling_stone`, `lone_wolf`, `diamond_run`, `burst_mode`, `marathon_leader`

---

### Random Bonus Events (from HTML rewards shop tab)

| Event | Bonus | Trigger |
|-------|-------|---------|
| Odd Eddie | +20 pts | Submit with odd marker count |
| Even Steven | +20 pts | Submit with even marker count |
| Mirror | +30 pts | Two subs with exact same marker count |
| First Cleanup | +25 pts | First reviewer to submit at base value 1 today |
| Lone Wolf | +30 pts | Submit when no other reviewer has in past 2h |
| Early Bird | +20 pts | Submit within 30 min of `>newday` |
| First Reviewer | +25 pts | First sub of the session |
| Cleanup Crew | +25 pts | Submit using base-pt value of 1 |
| High Roller | +30 pts | Submit using base-pt value of 4 |

---

### Rewards Shop (point costs — as of removal date, after 1.5× increase)

| Points | Reward |
|--------|--------|
| 225 | Free Pro Surge Route |
| 300 | Paid Priority Role |
| 539 | Wave Contributor Role |
| 821 | Free Pro Loot Route |
| 854 | 800 V-Bucks Gift |
| 870 | $3 AUD Payout |
| 1,125 | Skip Day (10 markers) |
| 1,131 | Free Pro Drop Map |
| 1,166 | Promotion |
| 1,205 | $7.50 AUD Payout |
| 1,775 | $15 AUD Payout |
| 2,276 | @everyone Ping |
| 2,570 | $25 AUD Payout |
| 2,781 | VIP Role |
| 3,122 | $33 AUD Payout |
| 3,419 | $40 AUD Payout |
| 3,867 | $50 AUD Payout |
| 5,768 | $80 AUD Payout |
| 6,348 | $100 AUD Payout |
| 8,570 | $150 AUD Payout |
| 10,890 | $200 AUD Payout |
| 12,950 | $225 AUD Payout |
| 13,781 | $250 AUD Payout |

---

### Key Config IDs (from `drop_map_reviewing_config.py`)

Check `commands/drop_map_reviewing_config.py` before deleting — it holds every channel ID, role ID, and tunable constant used by the system. Copy the whole file to the archive verbatim so the rebuild has exact IDs.

---

### Bot Commands

**Staff commands (all staff):**
- `>myreviews` — personal stats, tier, accuracy, streaks, lifetime points
- `>reviewingleaderboard` — top reviewers sorted by points
- `>preview [date]` — preview points summary for a session

**Admin commands:**
- `>newday` — open a new review session
- `>endday` — close session, post daily summary
- `>claim [map_id]` — claim a map for review
- `>submit [map_id] [correct] [total] [link]` — submit results
- `>addpoints <@user> [pts]` — manual point adjustment
- `>removepoints <@user> [pts]` — manual deduction
- `>addpenalty <@user> [type]` — apply a penalty
- `>setoverride <@user> [count]` — set ghost marker count
- `>listoverrides` — list active ghost overrides
- `>addreviewer <@user>` — register + grant role
- `>removereviewer <@user>` — de-register + strip role
- `>wipereviewing` — ⚠️ wipe ALL data (2-step confirm)
- `>dropmapreviewing enable/disable/status` — toggle system

---

## Section 7 — DATABASE_SCHEMA.md (copy into archive)

### Database: `reviewers.db` (separate SQLite file)

All reviewing tables live in this file, NOT in `bot_database.db`. On rebuild, `database.py` would open a separate async connection pool to `reviewers.db`.

### Tables

**`reviewers`** — main reviewer profile
```sql
user_id INTEGER PRIMARY KEY,
username TEXT NOT NULL,
total_points INTEGER DEFAULT 0,
points_from_reviews INTEGER DEFAULT 0,
points_from_streaks INTEGER DEFAULT 0,
points_from_bonuses INTEGER DEFAULT 0,
points_from_helpers INTEGER DEFAULT 0,
penalties_deducted INTEGER DEFAULT 0,
current_tier TEXT DEFAULT 'Beginner',
current_multiplier REAL DEFAULT 1.0,
accuracy_percentage REAL DEFAULT 0.0,
total_markers_reviewed INTEGER DEFAULT 0
-- (check source file for full column list — ~15-20 cols)
```

**`reviewer_markers`** — real marker history (sliding 30-window)
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
reviewer_id INTEGER NOT NULL,
map_id TEXT,
marker_number INTEGER,
is_correct BOOLEAN,
timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
FOREIGN KEY(reviewer_id) REFERENCES reviewers(user_id),
UNIQUE(reviewer_id, map_id, marker_number)
```

**`ghost_markers`** — synthetic seed markers for new reviewers
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
reviewer_id INTEGER NOT NULL,
is_correct BOOLEAN DEFAULT 1,
timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
FOREIGN KEY(reviewer_id) REFERENCES reviewers(user_id)
-- INDEX: idx_ghost_markers_lookup ON ghost_markers(reviewer_id, timestamp DESC, id DESC)
```

**`accuracy_streaks`** — consecutive perfect submissions
```sql
reviewer_id INTEGER PRIMARY KEY,
-- current streak count, milestone flags, etc.
FOREIGN KEY(reviewer_id) REFERENCES reviewers(user_id)
```

**`daily_streaks`** — consecutive active days
```sql
reviewer_id INTEGER PRIMARY KEY,
-- current streak, last review date, milestones hit
FOREIGN KEY(reviewer_id) REFERENCES reviewers(user_id)
```

**`marker_reviews`** — full submission records
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
reviewer_id INTEGER NOT NULL,
map_id TEXT,
-- correct/total markers, base pts, final pts, tier at time, timestamps
time_to_review_minutes INTEGER,
FOREIGN KEY(reviewer_id) REFERENCES reviewers(user_id)
```

**`helper_assists`** — helper assist outcomes
```sql
helper_id INTEGER,
helped_reviewer_id INTEGER,
-- map_id, was_correct, points_awarded
FOREIGN KEY(helper_id) REFERENCES reviewers(user_id),
FOREIGN KEY(helped_reviewer_id) REFERENCES reviewers(user_id)
```

**`daily_bonus_maps`** — which map is the bonus map per session
```sql
-- session_date, map_id, is_claimed, claimed_by, bonus_applied_to_reviewer
FOREIGN KEY(claimed_by) REFERENCES reviewers(user_id)
```

**`daily_sessions`** — session open/close records
```sql
-- session_date, opened_at, closed_at, session_opened_by, first_reviewer_claimed, etc.
```

**`session_counter`** — global incrementing session ID
```sql
reviewer_id INTEGER NOT NULL,
-- (used for get_next_session_id())
```

**`daily_activity_log`** — per-reviewer per-session event log (feeds the activity tab in HTML)
```sql
-- guild_id, reviewer_id, session_date, action_type, action_data JSON, timestamp
```

**`reviewers_temp`** — staging table for in-progress submissions
```sql
-- user_id, submission_date, verified flag + indexes
```

**`daily_challenges`** — which challenges are active per session
```sql
-- session_date, challenge_id, challenge_data JSON, etc.
```

**`challenge_completions`** — which reviewers completed which challenges
```sql
-- session_date, user_id, challenge_id, bonus_pts_awarded, completed_at
```

> **Full column definitions:** read `database.py` lines 747–1028 and 5063–5090 before deleting. Copy exact CREATE TABLE SQL into this file.

---

## Section 8 — REBUILD_PROMPT.md (copy into archive)

```
Rebuild the Drop Map Reviewing system for Wave-Management-Bot (discord.py, prefix `>`).

This is a Discord bot system for staff to review Fortnite drop map submissions and earn 
points redeemable for real rewards. All source files and exact specifications are in this 
archive folder. Use them as the single source of truth.

FILES IN THIS ARCHIVE:
- reviewing_commands.py        → the full command cog (3,882 lines)
- drop_map_reviewing_config.py → all channel IDs, role IDs, constants
- reviewing_tasks.py           → background loops (hourly reminders, daily cleanup, etc.)
- reviewing_leaderboard_final.html → the full Staff Hub leaderboard page (4,853 lines)
- SYSTEM_OVERVIEW.md           → complete system documentation
- DATABASE_SCHEMA.md           → all 15 table definitions with columns

HOW TO REBUILD:
1. Copy reviewing_commands.py back to commands/
2. Copy drop_map_reviewing_config.py back to commands/
3. Copy reviewing_tasks.py back to tasks/
4. Copy reviewing_leaderboard_final.html back to website/
5. Re-add the database tables and functions to database.py (see DATABASE_SCHEMA.md for 
   tables; the full function code is in reviewing_commands.py imports and database.py 
   archived copy)
6. Re-add these lines to the shared files:
   - main.py: the shutdown leaderboard push block (see ENTANGLEMENTS in SYSTEM_OVERVIEW)
   - web_api.py: add 'reviewing' back to _API_PAGES
   - staff_hub_writer.py: add reviewing JSON write back
   - utilities.py: add reviewing tab and get_reviewing_embed()
   - database_backup.py: add reviewers.db back to backup lists
   - multi_guild_role_commands.py: re-add add/remove_drop_map_reviewer hooks

The system used a SEPARATE SQLite database (reviewers.db). Re-create it by adding the 
CREATE TABLE blocks back to init_database() in database.py.

Bot prefix: `>`. Guild IDs: see drop_map_reviewing_config.py.
```

---

## Quick reference — what touches what

```
reviewing_commands.py
  └── imports: database.py (all reviewer functions)
  └── imports: drop_map_reviewing_config.py
  └── imports: tasks.staff_hub_writer (push_drop_map_leaderboard_to_github)

reviewing_tasks.py
  └── imports: database.py (reviewer functions)
  └── background loops: reminder (1h), cleanup (24h)

main.py
  └── shutdown: get_all_reviewer_leaderboard_stats() → push to Staff Hub

database.py
  └── reviewers.db connection (separate from bot_database.db)
  └── 15 tables, 40+ functions, all reviewing-only

multi_guild_role_commands.py
  └── granting Drop Map Reviewer role → calls add_drop_map_reviewer()
  └── removing Drop Map Reviewer role → calls remove_drop_map_reviewer()

utilities.py
  └── get_reviewing_embed() → reviewing help tab in >help

web_api.py
  └── /api/reviewing → serves website/data/reviewing.json

staff_hub_writer.py
  └── push_drop_map_leaderboard_to_github() → writes website/data/reviewing.json

database_backup.py
  └── backs up reviewers.db and json_data/drop_map_reviewing.json
```
