---
name: scripts-inventory
description: "Complete audit of all Python scripts, gates, tasks, and automation in Wave-Management-Bot—what they do, when they run, and how to use them"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7edafa36-7802-47fe-8991-f773a1b263fa
---

# 📜 Scripts Inventory — Wave-Management-Bot

A complete catalog of every automation script, background task, validation gate, and data tracker in the project.

---

## 0. Utility & Automation Scripts (ai-hub/scripts/)

### `ai-hub/scripts/sync_agent_skills.py`
**What it does:** Syncs all skills from `ai-hub/skills/` to every agent's native skills folder

**Targets:**
- `.claude/commands/` — Claude Code (.md files)
- `.cursor/rules/` — Cursor IDE (skill-*.mdc files)
- `.qoder/skills/` — Qoder (SKILL.md in per-skill directories)

**How to run:**
```bash
python ai-hub/scripts/sync_agent_skills.py
```

**Triggers:** Auto-run as step 3 of `validate.py`

**Why:** Each agent has a different skills-discovery format. This script is the sync engine that keeps them all in lock-step.

---

### `ai-hub/scripts/ralph.py` & `ralph.sh` ⭐ **Multi-Turn Agentic Loop**

**What it does:** Feeds a spec (PROMPT.md) to the Claude CLI (`claude -p`) repeatedly until task is complete or iteration cap reached.

**Two modes:**

#### 1. In-Place (Simple)
```bash
python ai-hub/scripts/ralph.py
```
- Runs on your current branch in this directory
- Commits after each iteration
- Simple, but commits to whatever branch you're on

#### 2. Self-Isolating Worktree (Safe, Parallelizable)
```bash
python ai-hub/scripts/ralph.py --worktree
```
or
```bash
RALPH_WORKTREE=1 python ai-hub/scripts/ralph.py
```

**What this does:**
- Creates a fresh git worktree on a new branch (ralph/run-<timestamp>)
- Agent runs in isolation — your main checkout never moves
- Each worktree is independent; you can launch **5+ in parallel** and each runs on its own branch
- On completion, prints a summary with merge instructions

**Options:**

| Flag | Env Var | Purpose |
|------|---------|---------|
| `--worktree` | `RALPH_WORKTREE=1` | Run in isolated worktree |
| `--branch NAME` | `RALPH_BRANCH=NAME` | Custom branch name (default ralph/run-<ts>) |
| `--db-isolate` | `RALPH_DB_ISOLATE=1` | Copy bot_database.db into worktree (agent can mutate freely) |
| `--cleanup` | `RALPH_CLEANUP=1` | Delete worktree on success (branch kept) |

**Environment:**
- `RALPH_MAX_ITER=15` (default) — iteration cap
- `RALPH_ITER_TIMEOUT=1800` (default, seconds) — per-iteration timeout
- `RALPH_WORKTREE_DIR=../ralph-worktrees` — where worktrees are stored

**The Flow:**
1. Ralph reads `ralph/PROMPT.md` from your repo
2. Each iteration: feeds spec to `claude -p` (Agent SDK CLI)
3. Claude makes edits, runs commands, commits work
4. Ralph checks for `ralph/DONE.txt` — if found, spec is complete
5. Iteration finishes, repeats (up to MAX_ITER)
6. Summary printed with merge/review instructions

**Example — parallel multi-agent:**
```bash
# Terminal 1: Agent A on feature-x
RALPH_WORKTREE=1 RALPH_BRANCH=agent-a python ralph.py

# Terminal 2: Agent B on feature-y (same time)
RALPH_WORKTREE=1 RALPH_BRANCH=agent-b python ralph.py

# Both run in parallel; each has its own worktree + DB copy
# Once both finish, review both branches and merge to master
```

**Why it matters:** This is how you run **multi-agent projects** — agents work in parallel without stepping on each other's commits.

**Bash equivalent:** `ralph.sh` does the same thing but is pure bash (for systems without Python installed on the bot's Windows machine).

---

### `ai-hub/scripts/wave_sync.py` ⭐ **Safe Git Sync Mechanics**

**What it does:** Deterministic, safe git sync engine. Handles status checks, backups, and pushes with full safety guards.

**Subcommands:**

#### `wave_sync.py status` (Read-only, run FIRST)
```bash
python ai-hub/scripts/wave_sync.py status
```

**Outputs:**
- How many commits behind/ahead of origin/master
- Incoming code changes (non-runtime files)
- Local uncommitted changes (classified as "real code" vs "runtime churn")
- Is bot_database.db locked (bot running)?
- Do any backup branches exist?
- Guidance on what to do next

**Key insight:** Distinguishes **real code** (worth reviewing) from **runtime churn** (bot/supervisor writing logs, cache, JSON data)

#### `wave_sync.py backup`
```bash
python ai-hub/scripts/wave_sync.py backup
```

Creates a timestamped backup branch at HEAD (so you can safely try risky things).

#### `wave_sync.py push` (Main sync)
```bash
python ai-hub/scripts/wave_sync.py push [-m "message"]
```

**Does:**
1. Fetches latest from origin
2. Refuses if you're behind (prevents force-push accidents)
3. Creates backup branch
4. Commits all changes (`-m` for custom message)
5. Pushes to origin/master
6. Verifies local == remote

**Safety gates:**
- Won't push if you're behind origin — you must pull first
- Creates backup before push
- Classifies runtime churn as safe to commit (logs, DB WAL files, JSON state)

**Ignores (won't block) these runtime files:**
- `.db`, `.db-wal`, `.db-shm` (SQLite artifacts)
- `.log` files
- `wave_logging_local/`, `website/data/*.json`, `json_data/`
- `database_backups/`, `twitter_feed`, `duties_totals`, `.wrangler/`
- (All patterns in `RUNTIME_PATTERNS` list)

#### `wave_sync.py pre-push-check`
**Git hook (automatic):** Runs before you push to check if you're behind origin. Blocks unsafe pushes.

#### `wave_sync.py install-hook`
```bash
python ai-hub/scripts/wave_sync.py install-hook
```

Activates the pre-push hook (run once per machine).

**Why:** The hook lives in git (`ai-hub/scripts/hooks/pre-push`), so updates travel automatically. No need to re-install.

---

### `ai-hub/scripts/hooks/`
**What it contains:** Git hooks (called automatically by git on events)

- **`pre-push`** — Runs before push; blocks if you're behind origin (via wave_sync.py)

**To activate (once per machine):**
```bash
python ai-hub/scripts/wave_sync.py install-hook
```

---

## 1. Validation Gates (Enforcement)

Scripts that must pass before shipping code.

### `ai-hub/gates/validate.py` ⭐ **REQUIRED BEFORE SHIPPING**
**What it does:**
- Runs security check (protected files not staged)
- Lints `commands/`, `core/`, `tasks/` with Ruff (ignores legacy nits)
- Syncs skills from `ai-hub/skills/` to `.claude/`, `.cursor/`, etc.

**How to run:**
```bash
python ai-hub/gates/validate.py
```

**Exit code:** Must be 0. If non-zero, don't ship.

**When to run:** Before every commit/push. Can be automated via pre-commit hook (add to `.claude/settings.json` hooks).

### `ai-hub/gates/security_check.py`
**What it does:**
- Prevents accidentally committing secrets (env files, tokens, API keys)
- Checks staged files against a blocklist

**Triggered by:** `validate.py` (step 1)

---

## 2. Background Tasks (Auto-Running Discord Events)

Scripts that run on timers, triggered by Discord.py's `@tasks.loop()` decorator. All live in `tasks/`.

### Core System Tasks

| Task File | Purpose | Trigger | Frequency |
|-----------|---------|---------|-----------|
| `weekly_checks.py` | Weekly role syncing, database maintenance | `@tasks.loop(hours=168)` | Every 7 days |
| `weekly_roles.py` | Staff role updates, permissions sync | `@tasks.loop(hours=X)` | Weekly |
| `auto_cleanup_task.py` | Purge ghost pings, old messages | Background loop | On schedule |
| `periodic_week_rollover.py` | Week boundary logic, streaks reset | `@tasks.loop()` | Start of week |

### Economic & Reward Tasks

| Task File | Purpose | Trigger |
|-----------|---------|---------|
| `power_points_rewards.py` | Distribute power points / wave points | Weekly auto-reward |
| `wave_points.py` | Manage wave points system state | Event-driven + periodic |
| `power_hour.py` | Special high-earning window | Scheduled events |
| `web_shop_processor.py` | Process shop purchases, redemptions | On-demand + sync |

### Loot & Routing Tasks

| Task File | Purpose |
|-----------|---------|
| `loot_routes.py` | Auto-assign loot routes, manage rotations |
| `surge_routes.py` | Manage surge routes, confirmation flow |
| `rotation_notifier.py` | Alert staff when rotations change |

### Map & Research Tasks

| Task File | Purpose |
|-----------|---------|
| `map_request.py` | Forward map requests to source |
| `random_challenges.py` | Generate random drop-map challenges |

### Engagement & Leaderboard Tasks

| Task File | Purpose |
|-----------|---------|
| `accuracy_streaks.py` | Track consecutive perfect markers, milestones |
| `duties_scan.py` | Audit staff duty completion, assign points |
| `staff_insights.py` | Generate analytics, populate staff insights |
| `staff_sheet.py` | Sync staff sheet (roles, earnings, stats) |
| `tipsandtricks.py` | Rotate tips, educational messages |

### DM & Communication Tasks

| Task File | Purpose | Key Detail |
|-----------|---------|------------|
| `dm_queue.py` | Shared cross-bot DM queue (Wave Logistics) | Shared with Logistics bot; see [[wave_logistics_queue_architecture]] |
| `reply_dm_inbound.py` | Handle incoming DMs | Queued, state-tracked |
| `reply_dm_outbound.py` | Send queued DMs to users | 5-minute auto-purge on sent |
| `reply_dm_state.py` | Maintain DM queue state | Database-backed |

### Utility Tasks

| Task File | Purpose |
|-----------|---------|
| `wave_logging.py` | Log bot events (errors, commands, state changes) |
| `bot_admin_api.py` | Admin endpoints for bot control |
| `tippy_join_tasks.py` | Track new member joins, onboarding |
| `twitter.py` | Post stats to Twitter (if enabled) |
| `predictions_engine.py` | Run prediction model (if YOLO enabled) |
| `maintenance.py` | General maintenance tasks |
| `leaderboard_updater.py` | Update leaderboards (stubs post-economy-unification) |

**How they work:**
- Loaded via `tasks/__init__.py` into the bot's cog system
- Discord.py automatically calls methods on schedule
- Errors are logged to `rate_limits.log` and `discord.log`

---

## 3. Data Trackers (Command-Invoked Scripts)

Discord command-triggered data collection & reporting tools. Each lives in `command-trackers/{tracker-name}/`.

### `command-trackers/drop-map-research/`
**Discord command:** `>rdropmap`  
**Purpose:** Research, track, and analyze drop map data across sessions

**Structure:**
- `scripts/db.py` — SQLite database (drop map entries)
- `scripts/collect.py` — Collect user submissions
- `scripts/generate_report.py` — Generate drop map analysis reports
- `data/data.db` — Live database (tracked in git)
- `data/reports/` — Generated reports

### `command-trackers/guild-stats/`
**Discord command:** `>guilddash`  
**Purpose:** Live dashboard of guild stats, member activity, earnings

**Structure:**
- `scripts/db.py` — Guild stats database
- `scripts/collect.py` — Collect current stats
- `scripts/generate_report.py` — Render stats dashboard

### `command-trackers/market-research/`
**Discord command:** `>marketresearch`  
**Purpose:** Track market conditions, economy state, trading patterns

**Structure:**
- `scripts/db.py` — Market data database
- `scripts/collect.py` — Collect market snapshots
- `scripts/generate_report.py` — Market analysis

**Common pattern** (all three trackers follow this):
1. User runs Discord command (`>rdropmap`, `>guilddash`, `>marketresearch`)
2. Bot calls tracker's `scripts/collect.py`
3. Tracker queries live database, Discord API, etc.
4. `scripts/generate_report.py` formats & embeds result
5. Result posted to Discord channel

---

## 4. Website & Dev Server Scripts

### `website/mock_server.py`
**What it does:** Local Flask-like development server for testing the staff hub website

**How to run:**
```bash
python website/mock_server.py
```

**Serves:**
- `http://localhost:8080` — static files from `website/`
- `http://localhost:8080/api/economy` — mock economy data (VBucks, Wave Points leaderboards)
- Uses `MOCK_ECONOMY` dict — edit it to test different states

**When to use:** Before deploying website changes; test without hitting live API

**Port:** 8080 (change in code if needed)

### `website/` (Live deployment)
- Flask server runs on Windows (dev machine)
- Cloudflared tunnel exposes to wavedropmaps.pages.dev
- Static assets in `website/` directory
- **Note:** `wave-leaderboard-repo/` is DEPRECATED — never edit it

---

## 5. Core Helper Modules (Not Direct Scripts, But Power Tasks)

### `core/leaderboard_updater.py`
**What it does:** Stubs only (post-economy-unification, VBucks leaderboard removed)

**Key functions (all no-ops now):**
- `async auto_update_vbucks_leaderboard(bot, ...)` — stub
- `async update_all_vbucks_leaderboards(bot, ...)` — stub
- `async update_all_leaderboards(bot, ...)` — stub

**Why:** Called by database hooks and startup code; kept for compatibility.

### `core/helpers.py`
**What it does:** Shared utility functions (role lookup, color parsing, Discord ID handling, etc.)

**Used by:** All cogs and tasks via `from core.helpers import *`

---

## 6. Script Execution Flows

### Flow 1: Feature Ship
```
1. Write code / make changes
2. Run: python ai-hub/gates/validate.py
3. If exit code 0 → commit + push
4. If exit code ≠ 0 → fix issues, re-run
```

### Flow 2: Background Task Execution (Auto)
```
1. Bot starts
2. tasks/__init__.py loaded (registers all @tasks.loop tasks)
3. Discord.py calls each task on its schedule
4. Task writes to database, posts to Discord
5. Errors logged to rate_limits.log
```

### Flow 3: Data Tracker Invocation
```
1. User types: >rdropmap [args]
2. Discord fires command handler
3. Handler calls: command-trackers/drop-map-research/scripts/collect.py
4. collect.py queries database, returns data
5. Handler calls: generate_report.py
6. Report formatted as Discord embed, posted to channel
```

### Flow 4: Website Testing
```
1. On Mac: python website/mock_server.py
2. Browser: http://localhost:8080
3. Loads static files + mock /api/economy
4. Test UI before pushing to wavedropmaps.pages.dev
```

---

## 7. Logging & Observability

### Log Files
- **`discord.log`** — Bot events (startup, shutdowns, errors)
- **`rate_limits.log`** — Discord API rate-limit warnings (alerts if <3 requests remain)
- **`wave_logging.py`** — Central logging task (can be extended with custom events)

### Timestamps
- All logs use **UTC** (via `logging.Formatter.converter = time.gmtime`)
- Commands log their invocation + result

---

## 8. Script Dependency Graph

```
Validation & Sync (Pre-ship gates)
  validate.py (REQUIRED BEFORE SHIPPING)
    ├─ security_check.py (blocks secrets)
    ├─ ruff lint (syntax/style)
    └─ sync_agent_skills.py (keep all agents in sync)
  
  wave_sync.py (Safe git operations)
    ├─ status (read-only, run first)
    ├─ backup (create safe point)
    └─ push (safe commit + push)
    
Multi-agent Automation (Ralph)
  ralph.py / ralph.sh (Agentic loop driver)
    ├─ Reads: ralph/PROMPT.md
    ├─ Calls: claude -p (iteratively)
    ├─ Mode A: in-place (simple, commits to current branch)
    └─ Mode B: --worktree (isolated, parallelizable)
         └─ Optionally: --db-isolate (agent gets copy of bot_database.db)
         
Live Bot Runtime
  Tasks (auto-run on Discord.py loop)
    ├─ weekly_checks.py ─→ database.py
    ├─ power_points_rewards.py ─→ database.py
    ├─ loot_routes.py ─→ database.py
    ├─ dm_queue.py ─→ reply_dm_outbound.py
    └─ leaderboard_updater.py (stubs)
  
  Commands (Discord-triggered)
    ├─ >rdropmap ─→ command-trackers/drop-map-research/
    ├─ >guilddash ─→ command-trackers/guild-stats/
    └─ >marketresearch ─→ command-trackers/market-research/

Development & Testing
  website/
    └─ mock_server.py (local Flask, http://localhost:8080)
```

---

## 9. Quick Reference: "I Need to..."

| Goal | Command |
|------|---------|
| **Before shipping code** | `python ai-hub/gates/validate.py` (must exit 0) |
| **Check git sync status** | `python ai-hub/scripts/wave_sync.py status` |
| **Create safe backup branch** | `python ai-hub/scripts/wave_sync.py backup` |
| **Safe commit + push** | `python ai-hub/scripts/wave_sync.py push` |
| **Setup pre-push hook** (once per machine) | `python ai-hub/scripts/wave_sync.py install-hook` |
| **Run multi-turn agent task** | `RALPH_WORKTREE=1 python ai-hub/scripts/ralph.py` (creates isolated worktree) |
| **Sync skills to all agents** | `python ai-hub/scripts/sync_agent_skills.py` (or auto via validate.py) |
| **Test website locally** | `python website/mock_server.py` then `http://localhost:8080` |
| **View bot's recent logs** | Check `discord.log` and `rate_limits.log` (bot's Windows directory) |
| **Add a new background task** | Add `.py` to `tasks/`, register in `tasks/__init__.py`, use `@tasks.loop()` |
| **Add a new data tracker** | Create `command-trackers/my-tracker/scripts/{db,collect,generate_report}.py`, add Discord cog |
| **Debug a non-running task** | Check registration in `tasks/__init__.py` and `@tasks.loop()` decorator |
| **Check if secrets leak into git** | `python ai-hub/gates/security_check.py` |

---

## 10. Script Execution Patterns

### Pattern: Validation before ship
```bash
# Must pass before every commit/push
python ai-hub/gates/validate.py
# Runs: security check → lint → skill sync
# Exit code 0 = OK to ship
```

### Pattern: Safe git workflow
```bash
# Step 1: Check status (always safe)
python ai-hub/scripts/wave_sync.py status

# Step 2: If behind origin, pull via skill (`repo-sync`) or CLI (`git pull`)

# Step 3: Safe push
python ai-hub/scripts/wave_sync.py push -m "my changes"
# Auto-creates backup, commits, pushes, verifies sync
```

### Pattern: Multi-agent parallelization (Ralph)
```bash
# Terminal 1 — Agent A on isolated branch
RALPH_WORKTREE=1 RALPH_BRANCH=feature-a python ai-hub/scripts/ralph.py

# Terminal 2 — Agent B on isolated branch (same time)
RALPH_WORKTREE=1 RALPH_BRANCH=feature-b python ai-hub/scripts/ralph.py

# Both run in parallel; merge branches afterward
```

### Pattern: Development & testing
```bash
# Dev server for website testing
python website/mock_server.py
# Loads static files + mocks /api/economy
# Open: http://localhost:8080
```

---

## 11. Future Enhancements

- [ ] **Pre-commit hook via settings.json:** Auto-run `validate.py` before commits (configure hooks)
- [ ] **Post-push webhook:** Deploy to Windows bot after push
- [ ] **Ralph dashboard:** Real-time monitoring of multi-agent runs
- [ ] **Task health monitor:** Alert if background task hasn't run in X hours
- [ ] **Logging aggregator:** Stream `discord.log` from Windows to Mac for central viewing
- [ ] **Ralph + CI/CD:** Trigger multi-agent runs on PR creation or on-demand

---

## 12. Key Insights

1. **validate.py is the enforcement gate** — nothing ships without a 0 exit code
2. **wave_sync.py prevents accidents** — blocks behind-origin pushes, creates backups, classifies runtime churn
3. **ralph.py scales multi-agent work** — worktree isolation lets you run 5+ agents in parallel
4. **sync_agent_skills.py keeps agents aligned** — Claude, Cursor, Qoder all get fresh skills automatically
5. **All scripts are cross-platform** — Python-first (runs on Windows too; bash scripts for Mac/Linux)

---

**Last updated:** 2026-06-22  
**Status:** Complete utility & automation scripts inventory; all core patterns documented; ralph multi-agent pattern ready for scale
