# 📖 Docs — Project Documentation

General project documentation. Not system-specific (that's bot-infrastructure/) and not forward-looking (that's plans/).

## Contents

### `agentic_infrastructure_map.md` (275 lines)
How agents (Claude Code, Cursor, Copilot) stay coordinated across sessions.

**What it covers:**
- Memory system (how learnings persist between sessions)
- Skills and automation tools available
- MCP servers and tools
- Cross-agent syncing (keeping all tools in lock-step)
- Validation gates (enforcement before shipping)
- Feedback loops (capture mistakes, learn, prevent repeats)

**Simple version:** This is the infrastructure that lets agents collaborate and learn from each other without repeating past mistakes.

### `scripts_inventory.md` (555 lines)
Catalog of automation tools developers use.

**What it covers:**
- Syncing scripts (keep skills in sync across Claude Code, Cursor, Qoder, etc.)
- Ralph (run multiple agents in parallel on isolated branches)
- Validation gates (pre-shipping checks)
- Background tasks and automation
- Data trackers (Discord-command-invoked tools)

**Simple version:** This is the toolbox of scripts you run to automate dev work—testing, syncing, running parallel agents, etc.

### `architecture/` (Skill Output Folder)
LikeC4 skill output. C4 diagrams of bot architecture (diagram source, PNGs, interactive HTML).

**Note:** This is NOT the project's architecture itself—it's where the `/likec4` skill saves its diagrams.

### `harness/` (Skill Output Folder)
Harness orchestrator documentation. The 4-phase autonomous development cycle (Planner → Generator → Evaluator → Feedback).

**Files:**
- `harness_complete_spec.md` — Full specification
- `harness_detailed_logic.md` — Complete flow with decision trees
- `harness_decision_thresholds.md` — Exact criteria for decisions
- `harness_phase_mapping.md` — Which skills belong in each phase
- `harness_bootstrap_prompt.md` — Setup for new projects
- `harness_implementation_prompt.md` — Implementation guide

**Note:** This is NOT project architecture—it's documentation/output from the harness skill.

---

*Referenced from `AGENTS.md` → `ai-hub/` organization. Complements `ai-hub/memory/` (history + systems) and `ai-hub/plans/` (forward work).*
