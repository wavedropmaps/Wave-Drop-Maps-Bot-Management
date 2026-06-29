---
name: harness-phase-mapping
description: "Skill mapping for each harness phase—which skills could run, when to choose them, what they output"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7edafa36-7802-47fe-8991-f773a1b263fa
---

# Harness Phase Mapping — Skill Selection by Phase

This document maps **all available skills** to each of the 4 harness phases. The user will choose which skills belong in each phase.

---

## PHASE 1: PLANNER (Understand + Design the Task)

**Purpose:** Turn a vague task description into a concrete, actionable plan.

**Candidates:**

### Primary (Most Used)
- **`/piv-plan`** — Read code, write detailed `plans/<slug>-plan.md`
  - Output: Line-by-line task list, validation commands
  - Time: ~5 min
  - Best for: Structured tasks with clear scope

### Alternative Planners (Choose 1 If)
- **`/brainstorm`** (superpowers) — Design before you code
  - Output: Design decisions, architecture sketch, gotchas
  - Time: ~10 min
  - Best for: "I have an idea but not sure how to implement"
  - Difference: Outputs design doc, not an executable plan

- **`/wave-analyst`** — 4-section analysis framework
  - Output: Problem statement, risks, alternatives, disagreements
  - Time: ~10 min
  - Best for: "Is this decision right?" or "Should we do X or Y?"
  - Difference: Outputs decision analysis, not implementation plan

- **`/gsd`** (Get Shit Done) — 5-phase structured framework
  - Output: Structured context, subagent assignments, milestone plan
  - Time: ~15 min
  - Best for: Big projects with multiple phases
  - Difference: Breaks into milestones, not tasks

### Secondary/Parallel (Run In Addition)
- **`/likec4`** — Architecture visualization
  - When: After /plan, if you want to see the system model
  - Output: C4 diagram of affected components
  - Time: ~5 min
  - Use: Visual confirmation that plan touches right pieces

- **`/learn`** — Ask questions about codebase
  - When: If plan has uncertainties about existing code
  - Output: Answers to specific questions
  - Use: Clarify how something works before planning

---

## PHASE 2: GENERATOR (Execute the Plan)

**Purpose:** Follow the plan, make edits, commit each logical step.

**Candidates:**

### Primary (Always Runs)
- **`/piv-implement plans/<slug>`** — Follow the plan step-by-step
  - Input: `plans/<slug>-plan.md`
  - Output: Git commits (one per task), changed files
  - Time: 10-60 min
  - Best for: Executing a detailed plan

### Alternative: Autonomous Agent (For Vague Tasks)
- **`ralph.py --worktree`** (wrapped as skill) — Multi-turn loop
  - Input: Vague spec in `ralph/PROMPT.md`
  - Output: Git branch with multiple commits (iterative figuring-out)
  - Time: 30 min - 2+ hours
  - Best for: "Figure this out" tasks (no plan upfront)
  - Difference: Iterates, doesn't follow a plan

### Alternative: Subagent-Based Build (For Complex Work)
- **`/build`** (superpowers) — Build with subagents
  - Input: Task description + architecture
  - Output: Distributed work, coordinated commits
  - Time: 30 min - 2 hours
  - Best for: Large projects split across multiple agents
  - Difference: Parallelizes work, /implement is linear

### Secondary (Run After Main Generator)
- **`/split-and-verify`** — Split task + verify independently
  - When: If task is complex, run in parallel with /implement
  - Output: Multiple verified branches
  - Use: Run multiple agents on the same task, verify each independently

---

## PHASE 3: EVALUATOR (Check Quality + Rules)

**Purpose:** Verify the generated code meets standards and works.

**Candidates:**

### Primary (Always Runs)
- **`/review`** (code-reviewer) — Check against AGENTS.md rules
  - Input: Git diff from Phase 2
  - Output: `reports/<feature>-review.md` with PASS or CONCERNS
  - Time: 2-5 min
  - Best for: Code quality, Windows paths, SQLite patterns, DM queue rules

### Secondary (Run In Parallel)
- **`/verify`** (superpowers) — Verify work is actually done
  - When: Run alongside /review
  - Output: Test results, feature checklist, "does it work?"
  - Time: 5-15 min
  - Use: Functional verification (vs code review)

- **`validate.py`** (validation gate) — Lint + security + sync
  - When: Run before phase 4
  - Output: Exit code 0 = pass, non-zero = fail
  - Time: 2-5 min
  - Use: Catch lint errors, secret leaks, malformed code

- **`/code-sparring`** — Adversarial code review
  - When: Optional, if you want aggressive scrutiny
  - Output: Potential bugs, edge cases, anti-patterns
  - Time: 10 min
  - Use: Deep code quality check (not just rules)

---

## PHASE 4: FEEDBACK (Learn + Reflect)

**Purpose:** Save lessons learned, update memory, prepare for next cycle.

**Candidates:**

### Primary (Always Runs)
- **`/update-memory`** — Save lessons learned
  - Input: What you learned, what went wrong
  - Output: Context file + entry in `lessons-learned.md`
  - Time: 5-10 min
  - Best for: New patterns, mistakes to avoid

### Secondary (Run If Needed)
- **`/consolidate-memory`** — Synthesize complex learnings
  - When: If findings are complex (multiple lessons, conflicting patterns)
  - Output: Synthesized memory entry with multiple cross-links
  - Time: 10 min
  - Use: Complex insights that span multiple systems

- **`/checkpoint`** — Save session state for resume
  - When: After success, if task is ongoing to multiple sessions
  - Output: `.claude/progress.json` with full state
  - Time: 2 min
  - Use: Continuity across sessions

- **`/session-handoff`** — Wrap up session for fresh agent
  - When: At very end, before clearing context
  - Output: Handoff summary for next session
  - Time: 5 min
  - Use: Knowledge transfer if work continues with fresh context

---

## OPTIONAL: TRANSITION PHASES

These could run between main phases:

### After Planner → Before Generator
- **`/learn`** — Clarify uncertainties from plan
- **`/likec4`** — Visualize architecture before coding

### After Generator → Before Evaluator
- **`validate.py`** — Fail fast on syntax/lint (don't let bad code get reviewed)

### After Evaluator → Before Feedback
- **`/verify`** — Functional test (if not already run in phase 3)

---

## DECISION MATRIX: Which Skills to Choose?

| Scenario | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|----------|---------|---------|---------|---------|
| **Quick fix** (10 min) | /piv-plan | /piv-implement | /review | /update-memory |
| **Feature with unknowns** (30 min) | /brainstorm + /piv-plan | /piv-implement | /review + /verify | /update-memory |
| **Big project** (2+ hours) | /gsd + /likec4 | /build or ralph.py | /review + /code-sparring + validate.py | /consolidate-memory + /checkpoint |
| **Bug fix** (5 min) | /piv-plan | /piv-implement | /review | /update-memory |
| **Architecture decision** | /wave-analyst + /likec4 | (none) | (none) | /update-memory |
| **Research task** | (vague spec) | ralph.py --worktree | /review + /verify | /consolidate-memory |

---

## Summary: Skills Inventory by Phase

**Phase 1 (Planner):**
- piv-plan ⭐
- brainstorm, wave-analyst, gsd (alternatives)
- likec4, learn (parallel)

**Phase 2 (Generator):**
- piv-implement ⭐
- ralph.py, build (alternatives)
- split-and-verify (parallel)

**Phase 3 (Evaluator):**
- review ⭐
- verify, validate.py, code-sparring (parallel)

**Phase 4 (Feedback):**
- update-memory ⭐
- consolidate-memory, checkpoint, session-handoff (alternatives/parallel)

---

**Your turn:** Tell me which skills you want in each phase. Example:

```
Phase 1: /piv-plan (primary) + /likec4 (optional, if architecture touch)
Phase 2: /piv-implement (primary) + ralph.py (if --ralph flag set)
Phase 3: /review (primary) + /verify (parallel)
Phase 4: /update-memory (primary)
```

Or however you want to organize it.
