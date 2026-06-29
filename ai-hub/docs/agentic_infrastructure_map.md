---
name: agentic-infrastructure-map
description: "Complete audit of all cross-agent automation, hooks, MCPs, skills, and feedback loops in Wave-Management-Bot"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7edafa36-7802-47fe-8991-f773a1b263fa
---

# 🤖 Agentic Infrastructure Map — Wave-Management-Bot

This document maps **every piece of AI automation, feedback, and cross-agent infrastructure** in the project. It's the master reference for how agents (Claude Code, Cursor, Copilot, future AI tools) learn about and improve your bot.

---

## 1. Knowledge Transfer & Learning

### 1.1 Memory System (claude-mem MCP)
- **Status:** ✅ Active on this Mac
- **What it does:** Auto-injects session context at the start of each conversation; persists learnings across sessions
- **Where it lives:** `~/.claude-mem/` (Mac-side database), `~/.claude/projects/-Users-kierenpatel-Downloads-Wave-Management-Bot-master/memory/` (readable notes)
- **Key files:**
  - `MEMORY.md` — the index (loaded into every session)
  - `project_wave_management_bot.md` — comprehensive bot overview
  - `bot-infrastructure/` — system-specific deep dives (Drop Map, VBucks, Strikes, Loot Routes, etc.)
  - `global-memory/` — lessons learned and mistakes to avoid
  - `session-summaries/` — past work summaries

**How to use:**
- Search past learnings: `/mem-search "keyword"`
- Add new learning: `/update-memory` or `consolidate-memory` skill
- Read this map in future sessions to understand what's already known

### 1.2 AGENTS.md (Master Instructions)
- **What it does:** Single source of truth for ALL agents (Claude Code, Cursor, Copilot, Antigravity, Qoder, etc.)
- **Where it lives:** `/Users/kierenpatel/Downloads/Wave-Management-Bot-master/AGENTS.md` (repo root)
- **Contains:**
  - Workflow rules (git, planning, scope discipline, validation gate)
  - Codebase map (links to deep docs per system)
  - Conventions & gotchas
  - `ai-hub/` folder sorting rules
  - Cross-platform code requirements

**Why this matters:** Every agent reads this file, so updates here cascade to all tools.

### 1.3 Skills — Cross-Agent Automation
- **Location:** `ai-hub/skills/` (portable, travels with repo)
- **Currently installed:**
  - `checkpoint` — save/resume session state
  - `update-memory` — capture learnings (post-mortems, lessons, decisions)
  - `consolidate-memory` — synthesize complex learnings
  - `wave-analyst` — 4-section analysis framework (proposals, bugs, decisions)
  - `decision-framework` — structured decision-making
  - `session-summary` — wrap up session for handoff
  - `schedule` — flag future tasks with dates
  - `likec4` — visualize architecture (C4 diagrams)
  - `learn` — ask questions about code
  - `repo-sync` — keep tools in sync with ai-hub/skills/
  - `prompt-engineering-deep-dive` — stress-test prompts before shipping
  - `doc-coauthoring` — collaborative document building
  - `web-artifacts-builder` — interactive visualizations
  - `theme-factory`, `brand-guidelines`, `doc-coauthoring` — content generation

**How to activate:**
- Run via Skill tool: `/skill-name [args]`
- Example: `/update-memory` to save a lesson; `/schedule` to flag follow-up work

### 1.4 Desktop Skills (Global)
- **wave-analyst** (`~/Desktop/wave-analyst.skill`) — rigorous analysis framework
- Accessible from ANY project on this Mac via `/wave-analyst`

---

## 2. Integration Points (MCPs & Tools)

### 2.1 Model Context Protocol (MCP) Servers
**Configured in `.mcp.json`:**

| Server | Purpose | Status |
|--------|---------|--------|
| **github** | Read/write repos, PRs, issues, branches | ✅ Active |
| **context-mode** | Compress/optimize token usage | ✅ Active |
| **codebase-search** | Search code, find references, outline | ✅ Active |
| **claude-mem** | Cross-session memory (global) | ✅ Active |

**How MCPs work:**
- Agents use these tools automatically without re-asking for permission
- Tokens come from `GITHUB_TOKEN` env var (gitignored `.env`)
- New MCPs added via `.mcp.json` require Claude Code restart

### 2.2 Claude Code Permissions (`.claude/settings.json`)
**Permanently allowed without prompting:**
- `Bash(python -c ' *)'` — run Python one-liners
- `Bash(git add *)'` — stage files
- Skill(update-config)` — modify settings
- Chrome/Claude-in-Chrome navigation and inspection
- Computer-use screenshot + access requests

**Why configured:** Reduce permission spam for common, safe operations

---

## 3. Cross-Platform Agent Configuration

### 3.1 How Each Agent Finds Skills
Each AI tool has a native skills location. **Most do NOT auto-check `ai-hub/skills/`** — so skills are mirrored/copied:

| Agent | Native Skills Location | Status |
|-------|------------------------|--------|
| **Claude Code** | `.claude/commands/` | Copied `.md` files present |
| **Cursor** | `.cursor/rules/skill-*.mdc` | Copied `.mdc` files present |
| **Antigravity** | `.agents/skills.json` | Native pointer to `ai-hub/skills/` |
| **Qoder** | `.qoder/skills/{name}/SKILL.md` | Copied `SKILL.md` files per skill |
| **Kiro** | `.kiro/skills/` | Copied `.md` files present |

**The workaround:** When you update a skill in `ai-hub/skills/`, you must run:
```bash
/repo-sync
```
This copies changes to `.claude/`, `.cursor/`, `.qoder/`, etc. so all agents see the update.

---

## 4. Feedback Loops & Continuous Learning

### 4.1 Session Learning Workflow
1. **During a session:** Agent encounters a mistake, learns a pattern, or discovers a gotcha
2. **At session end:** User or agent calls `/update-memory` or `consolidate-memory` skill
3. **Skill action:**
   - Creates a detailed post-mortem in `ai-hub/memory/global-memory/context/`
   - Updates `ai-hub/memory/global-memory/lessons-learned.md` with a 1-line summary + hyperlink
4. **Next session:** New agent reads updated memory via `/mem-search` or session recap

**Example:** If an agent mistakes which folder is the "live" website:
- Creates `ai-hub/memory/global-memory/context/website-deployment-source.md`
- Adds to lessons-learned.md: `- [Live Website is website/, not wave-leaderboard-repo](context/website-deployment-source.md)`
- Next agent's session recap includes the lesson → no repeat mistake

### 4.2 Validation Gate (Enforcement)
**Required at project level:** Before marking ANY feature/fix done, run:
```bash
python ai-hub/gates/validate.py
```
Must exit with code 0. This gate can include:
- Type checking
- Test suite validation
- Bot command sanity checks
- Database integrity

**Why it matters:** Prevents agents from shipping broken code; forces quality discipline

### 4.3 Planning Mode Feedback
- **Rule:** During planning conversations, agents should NOT write code, create files, or run mkdir
- **Stored in:** `ai-hub/memory/feedback_planning_mode.md`
- **Why:** Planning phase is for alignment, not action — prevents premature commits

### 4.4 Git Discipline Feedback
- **Rule:** Master branch only; commit + push directly; no feature branches
- **Stored in:** `ai-hub/memory/feedback_git_workflow.md`
- **Why:** Simplifies coordination; all agents work on the same branch

---

## 5. Agentic Scripts & Automation

### 5.1 Bot-Side Scripts (Live Code)
These are **not** in `ai-hub/` because they're code-referenced by the bot:

| Script | Purpose | Location | Triggered By |
|--------|---------|----------|--------------|
| **validate.py** | Enforcement gate (must pass before shipping) | `ai-hub/gates/validate.py` | Manual: `python ai-hub/gates/validate.py` |
| **leaderboard_updater.py** | Auto-update bot state after VBucks/strikes/points changes | `core/leaderboard_updater.py` | Called by commands, tasks |
| **Weekly background tasks** | Strike removal, VBucks awards, role sync | `tasks/weekly_*.py` | Discord `@tasks.loop(hours=X)` decorator |

### 5.2 Data Trackers (Command-Invoked)
Live, Discord-command-invoked data tools (NOT in `ai-hub/`):

| Tracker | Purpose | Location | Trigger |
|---------|---------|----------|---------|
| **drop-map-research** | >rdropmap data collection & analysis | `command-trackers/drop-map-research/` | Discord command |
| **guild-stats** | >guilddash live stats | `command-trackers/guild-stats/` | Discord command |
| **market-research** | >marketresearch tools | `command-trackers/market-research/` | Discord command |

Each has: `scripts/`, `data/data.db` (tracked in git), `SKILL.md` (documentation)

### 5.3 Website Dev Server
**For local preview of `website/` (the live staff hub):**
```bash
python website/mock_server.py
```
Runs Flask server mocking API endpoints from `website/data/*.json`. Useful for testing frontend changes before deploy.

---

## 6. Hooks & Automated Triggers (Extensible)

### 6.1 Possible Hooks (Not Currently Configured)
Claude Code supports event-driven automation via hooks in `settings.json`. Examples you could add:

```json
{
  "hooks": {
    "beforeCommit": "python ai-hub/gates/validate.py",
    "afterToolCall": "echo 'Tool executed'; notify-send 'Done'",
    "onSessionStart": "echo 'Session started at $(date)'"
  }
}
```

**Common patterns:**
- `beforeCommit` → run validation gate
- `afterPush` → notify on deploy
- `onSessionStart` → load context
- `beforeEdit` → backup file

**How to add:** Use `/update-config` skill or edit `.claude/settings.json` directly

### 6.2 Current Hooks
**None currently active.** But the infrastructure is ready — hooks would go in `.claude/settings.json`.

---

## 7. Documentation & Architecture

### 7.1 Architecture Models (LikeC4)
- **Skill:** `likec4` — generates C4 diagrams
- **Use case:** Visualize bot → Discord, bot → GitHub, bot → Staff Hub flows
- **Example:** `/likec4 "map out Wave Management Bot architecture"`

### 7.2 Deep System Docs (Read These Before Editing)
Stored in `ai-hub/docs/` and linked in AGENTS.md:

| System | Doc |
|--------|-----|
| Core files & large cogs | `ai-hub/memory/bot-infrastructure/core-files.md` |
| Game systems (Strikes, VBucks, Wave Points, Loot Routes) | `ai-hub/memory/bot-infrastructure/systems.md` |
| Background loops & DM queue | `ai-hub/memory/bot-infrastructure/background-tasks.md` |
| Staff Hub Flask site | `ai-hub/memory/bot-infrastructure/staff-hub-website.md` |
| Data trackers (>rdropmap, >guilddash) | `ai-hub/memory/bot-infrastructure/command-trackers.md` |
| YOLO drop-spot detection model | `ai-hub/memory/bot-infrastructure/yolo-model.md` |

**Protocol:** When you significantly change a system's code, update its doc in `ai-hub/docs/`.

---

## 8. Activation Checklist (For New Sessions)

When starting work, agents should:

- [ ] Read AGENTS.md (master instructions)
- [ ] Search memory via `/mem-search` if the task relates to a known system
- [ ] Check MEMORY.md index (auto-loaded) for relevant context
- [ ] Before editing code, read the system's deep doc in `ai-hub/memory/bot-infrastructure/`
- [ ] Use `/wave-analyst` to stress-test any major decisions
- [ ] Run `/update-memory` or `consolidate-memory` at session end to capture learnings
- [ ] Before shipping, run `python ai-hub/gates/validate.py` (0 exit code required)

---

## 9. Future Enhancements (Roadmap)

Possible agentic infrastructure to add:

- **Pre-commit hook:** Auto-run validation gate
- **Post-push webhook:** Notify on deploy success/failure
- **Session health monitor:** Auto-flag inconsistencies or stale memory
- **Cross-agent sync:** Auto-update `.claude/commands/`, `.cursor/rules/`, etc. when a skill changes
- **LLM-judged code reviews:** Use `/code-review ultra` to spawn cloud agents

---

**Last updated:** 2026-06-22  
**Status:** Complete initial audit; no active hooks yet, but infrastructure ready for expansion  
**Owner:** Claude Code (maintained by agents + user feedback)
