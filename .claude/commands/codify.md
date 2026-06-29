---
name: codify
description: After real work, update goal status in ai-hub/memory/goals/ and append durable decisions to ai-hub/memory/decisions.log. The maintenance/"write" half of the lightweight memory system (paired with the SessionStart goals hook). Use when a task finishes or meaningfully advances, or when the user says "codify", "capture this", or "update goals".
---

# codify — capture the session's outcome

The portable source of truth for the `/codify` workflow. Claude Code reads the
copy at `.claude/commands/codify.md`; other agents read this file from
`ai-hub/skills/`. Keep the two in sync.

Run when work is actually finished or has meaningfully advanced. Maintain the
two memory artifacts so they don't go stale.

## 1. Update goals
- Find the relevant goal(s) in `ai-hub/memory/goals/*.md`.
- Flip `status:` to match reality: `backlog → in-progress → review → done`.
- Tick satisfied `- [ ]` acceptance criteria.
- If work began with no goal file, offer to create one from `_TEMPLATE.md`
  (ask first; don't create goals for trivial changes).

## 2. Log decisions
- For each non-obvious choice (approach picked over alternatives, trade-off,
  architectural call), append ONE line to `ai-hub/memory/decisions.log`,
  newest at the bottom, exact format:

  `YYYY-MM-DD | system | decision | why | rejected: alternatives`

- Only durable decisions — ones a future agent would re-litigate. Append-only;
  never edit past lines.

## 3. Report
- Summarise what changed (goals moved, decisions logged) in chat.
- Do not commit or push unless explicitly asked.

If nothing meaningful happened, say so and change nothing.

## How it fits
- **Read half (auto):** the `SessionStart` hook runs
  `ai-hub/scripts/goals_status.py`, surfacing open goals at session start.
- **Write half (this skill):** updates goals + decisions on demand.
- claude-mem still auto-captures observations in parallel; `decisions.log` is
  the curated, greppable record of the ones that matter long-term.
