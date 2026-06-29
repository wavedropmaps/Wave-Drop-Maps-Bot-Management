# scripts/

Developer automation and utility scripts for project maintenance, agent loops, and cross-tool synchronization.

**What lives here:**
- **ralph.py / ralph.sh** — Headless Claude CLI loop driver. Feeds prompts to Claude repeatedly until done, with isolated worktree mode for parallel agent scaling.
- **sync_agent_skills.py** — Syncs skills from `ai-hub/skills/` to agent discovery directories (Claude, Cursor, Qoder, etc.).
- **goals_status.py** — SessionStart hook. Displays in-progress and review goals from `ai-hub/memory/goals/`.
- **wave_sync.py** — Safe git sync mechanics (status, backup, push) for the Wave bot repo.
- **hooks/** — Git hooks (post-checkout, post-commit, post-merge, pre-push) for automated workflows.

Browse by filename for new utilities.
