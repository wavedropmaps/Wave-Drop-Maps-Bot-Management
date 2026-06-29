# Drop Map Reviewing — Database Schema

## Database: `reviewers.db` (separate SQLite file)

All reviewing tables live in this file, NOT in `bot_database.db`. On rebuild, `database.py` would open a separate async connection pool to `reviewers.db`.

## Tables

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

> **Full column definitions:** read `database.py` git history (commit before removal) or the archived `reviewing_commands.py` which references every column by name.

## database.py Functions Removed

### Startup integrity check (~lines 165–187)
Block doing `SELECT COUNT(*) FROM reviewers` during startup validation.

### Table definitions in init_database() (lines 743–1028)
Entire `# ==================== DROP MAP REVIEWING SYSTEM ====================` block — 13 tables + indexes.

### Migration functions (lines 2402–2500)
- `migrate_reviewers_temp_add_streak_columns()`
- `migrate_reviewers_add_last_streak_settle_date()`
- `migrate_reviewers_add_tier_locked()`
- `cleanup_drained_ghost_markers()`

### Reviewer management functions (lines 3509–3875)
- `add_drop_map_reviewer(user_id, bot)`
- `remove_drop_map_reviewer(user_id, bot)`
- `sync_reviewer_usernames(bot)`
- `cleanup_drop_map_reviewers(bot)`

### Core reviewing logic functions (lines 3875–4438)
- `calculate_tier_from_accuracy()`
- `update_reviewer_tier()`
- `recalculate_all_reviewer_tiers()`
- `calculate_final_points()`
- `update_accuracy_streak()`
- `update_daily_streak()`
- `apply_penalty()`
- `get_reviewer_leaderboard_stats()`
- `get_all_reviewer_leaderboard_stats()`

### Activity logging functions (lines 4863–4950)
- `log_daily_activity()`
- `get_daily_activity_summary()`
- `get_next_session_id()`

### Daily challenges system (lines 5054–5820)
- `migrate_create_daily_challenges_tables()`
- All `_eval_*` challenge evaluator functions (24 functions)
- `pick_challenges_for_session()`
- `evaluate_challenges_for_reviewer()`
- `award_challenge_bonuses()`
- `get_challenges_for_session()`
