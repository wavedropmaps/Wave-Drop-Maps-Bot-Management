# 🧠 The Supercomputer Memory

The unified AI brain for Wave-Management-Bot. All knowledge about the project—systems, history, learnings, and current work—lives here, organized into five clearly defined areas.

## Structure

### `SUPERCOMPUTER.md` (this file)
Master index. Explains what each folder contains and what kinds of documents live there.

### `decisions.log`
Append-only log of architectural decisions. Each entry captures:
- **What** decision was made
- **Why** it was chosen (the reasoning)
- **What was rejected** (alternatives considered)
- **When** it was decided (date)

Format: `YYYY-MM-DD | system | decision | why | rejected: alternatives`

Example: "2026-06-22 | memory/tooling | Did NOT adopt jumbo.cli; built goals/ + decisions.log instead | claude-mem already covers memory | rejected: install jumbo-cli globally"

Used to avoid re-litigating decisions and understand the rationale behind code choices.

---

## `bot-infrastructure/` — Live System Documentation

Deep documentation on how the bot works **today**. If you're about to modify bot code, this is where you read first. Seven categories:

### `systems.md` (76 lines)
Overview of all game systems at a glance. Each system has:
- What it does (1-2 sentences)
- How it works (key components, database tables, configuration)
- Live code locations (where to find the implementation)
- Special rules or gotchas

Systems documented: Strikes, VBucks, Wave Points, Loot Routes, Surge Routes, Auto Watermark, and more.

### `core-files.md` (44 lines)
The biggest source files in the codebase and what each does:
- `main.py` — bot bootstrap and initialization
- `database.py` — schema, connection pool, query helpers
- Large cogs — command definitions and handlers

Helps agents navigate the code without getting lost.

### `background-tasks.md` (34 lines)
All background loops and scheduled jobs:
- Weekly auto-advance system
- Shared cross-bot DM queue
- Daily/hourly maintenance tasks

Documents timing, triggers, and data flows.

### `command-trackers.md` (77 lines)
The live data trackers invoked by Discord commands:
- `>rdropmap` and `>guilddash` — data collection and reporting
- Location and structure (lives in `~/command-trackers/` on Windows, not in ai-hub/)
- Integration points with the bot

### `staff-hub-website.md` (65 lines)
The Staff Hub website (Flask, Cloudflare workers):
- How the local preview works
- API endpoints served at `wavedropmaps.pages.dev`
- Database connections and authentication

Website code lives in `website/` (this repo).

### Deep-Dive Files
Specialized documentation for complex subsystems or incidents:
- `weekly-auto-advance-system.md` (206 lines) — detailed architecture of weekly advancement
- `weekly-roles-duplicate-fire-fix.md` (176 lines) — post-mortem on a bug, how it was fixed, what triggers it
- `yolo-model.md` (10 lines) — the drop-spot detection model
- `fortnite-gg.md` (28 lines) — fn.gg bot integration
- `cross-bot-interaction.md` — how Wave Management ⇄ Wave Logistics coordinate (shared DM DB, queue→channel bridge, shared proof channel). Mirrored identically in both repos.

Total: live system documentation (grows as systems are added).

---

## `global-memory/` — Continuous Learning Center

Knowledge accumulated over time. Lessons learned, gotchas discovered, patterns validated. Two parts:

### `lessons-learned.md` (20 lines)
Index of all learned rules and mistakes to avoid:
- Cross-platform constraints (Windows vs macOS paths)
- Database gotchas (WAL mode, connection pooling, transaction isolation)
- Discord API quirks (rate limits, permission caching, role lookups)
- Code patterns that didn't work
- Best practices discovered the hard way

Each line is a summary + hyperlink to a detailed post-mortem in `context/`.

### `context/` (subfolder)
Detailed post-mortems and explanations:
- One `.md` file per lesson or incident
- Explains: What went wrong (symptom), why it happened (root cause), what to do instead (the rule)
- Linked from `lessons-learned.md`

Example: A file explaining "Why we never parse Discord message state" would document the incident where state diverged from the database, the debugging process, and the rule: *always use the database as source of truth.*

---

## `session-summaries/` — Historical Archive

Records of completed work sessions and major projects. One file per session/milestone. Each captures:
- **What** was built (feature, fix, refactor, research)
- **Why** it mattered (the motivation or problem it solved)
- **When** it was done (date)
- **Decisions** made and alternatives rejected
- **Code locations** (which files changed, which still need work)
- **Linked sessions** (related work from other times)

Examples:
- `ai-tooling-portability-reorg.md` — how the ai-hub/ folder was reorganized
- `harness-engineering-integration.md` — work session where the harness orchestrator was built
- `investigate-auto-purge-trigger.md` — debugging session for a background task

Total: ~100 lines (growing as work completes).

---

## `goals/` — Active Work Items

Current work in progress. What the project is actively building or fixing. Not history—it's **now**.

### `README.md`
Master list of active goals. Shows priority, status, owner (if applicable), and links to individual goal files.

### `_TEMPLATE.md`
Copy this and rename to `NN-goal-name.md` when starting new work. Tracks:
- **Why** the goal matters (problem statement)
- **What** needs to be done (scope)
- **Blockers** (what's preventing progress)
- **Next steps** (what to do first)
- **Related goals** (connected work)

### `01-weekly-auto-advance.md`, etc.
Individual goal files, numbered in priority order. Updated as work progresses.

Total: ~75 lines (actively maintained throughout the project lifecycle).

---

## Summary: What Lives Where

| What you have | Where it goes |
|---|---|
| New game system (economy change, new command, new role) | `bot-infrastructure/systems.md` |
| Specialized implementation guide or incident deep-dive | New file in `bot-infrastructure/` |
| Discovered bug or learned a gotcha | `global-memory/context/` + link from `lessons-learned.md` |
| Completed work session or shipped feature | `session-summaries/` (new file) |
| Starting new work or planning feature | `goals/` (add to README.md + create goal file) |
| Architectural decision that affected codebase | `decisions.log` (append entry) |
| Raw research or throwaway experiment | `ai-hub/research/` or `ai-hub/scratch/` (outside memory/) |

---

*Entry point: AGENTS.md → points to this file. When in doubt, ask yourself: "Is this about **how the bot works now?** (infrastructure) **what we learned?** (global-memory) **what we built?** (session-summaries) **what we're building?** (goals) **why we chose this?** (decisions.log)"*
