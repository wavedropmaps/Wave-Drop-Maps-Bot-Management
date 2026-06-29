---
name: harness-complete-spec
description: "Complete specification of the 4-phase harness skill—all phases locked in, flow diagram, decision logic, inputs/outputs"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7edafa36-7802-47fe-8991-f773a1b263fa
---

# 🎯 Complete Harness Specification — Wave-Management-Bot

**The unified skill that orchestrates all 4 phases of autonomous feature development.**

---

## Overview

**One command:**
```bash
/harness "your task description"
```

**What it does:**
1. Planner → Brainstorm + Plan
2. Generator → Implement (or Ralph for big tasks)
3. Evaluator → Review + Verify + Validate
4. Feedback → Codify + Update-Memory + (optional) Consolidate

**Total time:** 25-120 minutes (depends on task size)

---

## PHASE 1: PLANNER (Understand + Design)

**Goal:** Turn task description into a concrete design + executable plan.

**Skills (In Order):**

### Step 1a: `/brainstorm`
- **Input:** Task description ("build a new leaderboard tracking system")
- **Output:** Design doc with:
  - System architecture
  - Data structures
  - API sketch
  - Gotchas identified
- **Time:** ~10 min
- **Stored:** `ai-hub/docs/` (for reference)

### Step 1b: `/piv-plan`
- **Input:** Task description + brainstorm output (in context)
- **Output:** `plans/<slug>-plan.md` with:
  - Affected files (exact line numbers)
  - Ordered tasks (dependency order)
  - Validation commands
  - Acceptance criteria
- **Time:** ~5 min
- **Stored:** `plans/` directory

### Step 1c: `/wave-analyst` (CONDITIONAL)
- **Trigger:** Only if task involves hard research or major decisions
- **Input:** Complex decision ("should we refactor X or rewrite Y?")
- **Output:** Analysis with risks, alternatives, expert disagreements
- **Time:** ~10 min
- **Stored:** `ai-hub/docs/` (for decision history)

---

## PHASE 2: GENERATOR (Execute the Plan)

**Goal:** Follow the plan, make edits, commit each logical step.

**Decision Tree:**

```
Is the plan breakable into parallel subtasks?
  YES → Use /split-and-verify (spawn subagents, each on own session)
  NO  → Continue

Is this a vague/research task (no detailed plan)?
  YES + task > 6 hours → Use ralph.py --worktree (autonomous loop)
  NO or task < 6 hours → Continue

Use /piv-implement (linear execution of plan)
```

### Path A: Structured Task (Normal)

#### `/piv-implement plans/<slug>-plan.md`
- **Input:** Plan file from Phase 1
- **Output:** Git commits (one per task)
- **Process:**
  1. Read plan
  2. For each task:
     - Open file at exact line
     - Make edit
     - Commit with task description
  3. All commits go to `master` branch (local)
- **Time:** 10-60 min
- **Git State:** master branch now has N new commits (not pushed yet)

### Path B: Parallelizable Task (Complex)

#### `/split-and-verify`
- **Input:** Task description + plan
- **Output:** Multiple verified branches
- **Process:**
  1. Split task into N independent subtasks
  2. Spawn N subagents, each on own session
  3. Each subagent runs /piv-implement on their subtask
  4. Each produces verified output
  5. Combine results into single branch
- **Time:** 30-90 min (parallel)
- **Git State:** master branch has merged commits from N subagents

### Path C: Autonomous Vague Task (Research)

#### `ralph.py --worktree` (6+ hour tasks)
- **Input:** `ralph/PROMPT.md` with vague spec
- **Output:** Git branch with iterative commits
- **Process:**
  1. Create isolated worktree + branch (`ralph/run-<timestamp>`)
  2. Feed spec to `claude -p` iteratively
  3. Claude figures it out, commits each iteration
  4. Loop until DONE.txt found or MAX_ITER reached
  5. Print summary with merge instructions
- **Time:** 30 min - 2+ hours
- **Git State:** New branch `ralph/run-<timestamp>` with multiple commits (not on master)

---

## PHASE 3: EVALUATOR (Check Quality)

**Goal:** Verify code meets standards and works.

**All steps run in parallel:**

### Step 3a: `/review`
- **Input:** Git diff (Phase 2 output)
- **Output:** `reports/<feature>-review.md` with PASS or CONCERNS
- **Checks:** AGENTS.md rules
  - Windows paths (pathlib.Path)?
  - SQLite async pool correct?
  - No direct user.send() calls?
  - Rate limit checks?
- **Time:** 2-5 min

### Step 3b: `/verify`
- **Input:** Changed code + acceptance criteria from plan
- **Output:** Test results, feature checklist
- **Checks:** Does it work? Do tests pass?
- **Time:** 5-15 min

### Step 3c: `python ai-hub/gates/validate.py`
- **Input:** All code in commands/, core/, tasks/
- **Output:** Exit code (0 = pass, non-zero = fail)
- **Checks:**
  - Security (no secrets committed)
  - Lint (ruff check)
  - Skill sync (all agents stay in sync)
- **Time:** 2-5 min
- **Must Pass:** If exit code ≠ 0, fix issues before Phase 4

### Step 3d: `/code-sparring` (ALWAYS)
- **Input:** Changed code
- **Output:** Potential bugs, edge cases, anti-patterns
- **Checks:** Adversarial review (try to break it)
- **Time:** 5 min

**Gate:**
```
If ANY reviewer says CONCERNS:
  → Print findings
  → Ask: "Fix or accept risk?"
  → User decides (don't auto-pass)

If ALL say PASS:
  → Continue to Phase 4
```

---

## PHASE 4: FEEDBACK (Learn + Reflect)

**Goal:** Save what was learned, update goals, log decisions.

**All steps run in sequence:**

### Step 4a: `/codify`
- **Input:** What was completed, decisions made
- **Output:** Updated goal files + decision log
- **Updates:**
  - `ai-hub/memory/goals/<task>-goal.md` (mark done/in-progress/blocked)
  - `ai-hub/memory/decisions.log` (append decision + rationale + timestamp)
- **Time:** 2-5 min

### Step 4b: `/update-memory`
- **Input:** Lessons learned ("we discovered X", "we should always Y")
- **Output:** Context file + 1-line entry in lessons-learned.md
- **Creates:**
  - `ai-hub/memory/global-memory/context/<lesson-slug>.md` (detailed)
  - Updates `ai-hub/memory/global-memory/lessons-learned.md` (link + 1-liner)
- **Time:** 5-10 min

### Step 4c: `/consolidate-memory` (CONDITIONAL)
- **Trigger:** Only if findings span multiple systems or learnings are interconnected
- **Input:** Multiple related lessons from 4b
- **Output:** Master memory file with cross-links
- **Time:** 10 min

---

## Complete Flow Diagram

```
USER INPUT
   │
   ↓
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: PLANNER (15-25 min)                                │
├─────────────────────────────────────────────────────────────┤
│ /brainstorm ─→ design doc                                   │
│       ↓                                                      │
│ /piv-plan ──→ plans/<slug>-plan.md                          │
│       ↓                                                      │
│ /wave-analyst? (if hard research) ─→ analysis doc           │
└─────────────────────────────────────────────────────────────┘
   │
   ↓ (plan file ready)
   
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: GENERATOR (10-120 min)                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Is task parallelizable?                                    │
│   YES → /split-and-verify (spawn N subagents)             │
│   NO  → /piv-implement (linear)                           │
│                                                             │
│ Is task vague + 6+ hours?                                  │
│   YES → ralph.py --worktree (autonomous loop)             │
│   NO  → (already handled above)                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
   │
   ↓ (commits made, code changed)
   
┌─────────────────────────────────────────────────────────────┐
│ PHASE 3: EVALUATOR (14-30 min, PARALLEL)                   │
├─────────────────────────────────────────────────────────────┤
│ /review ──────────────→ reports/<feature>-review.md        │
│ /verify ──────────────→ test results + checklist           │
│ validate.py ──────────→ security + lint + sync (exit 0?)   │
│ /code-sparring ───────→ bug hunt + anti-patterns           │
│                ↓                                            │
│         ┌─────────────┐                                    │
│         │ ALL PASS?   │                                    │
│         └─────────────┘                                    │
│            YES ↓  NO ↓                                     │
│               │    (show concerns, user decides)          │
│               │    (can fix or accept risk)               │
│               ↓                                            │
└─────────────────────────────────────────────────────────────┘
   │
   ↓ (code validated, safe to merge)
   
┌─────────────────────────────────────────────────────────────┐
│ PHASE 4: FEEDBACK (17-30 min)                               │
├─────────────────────────────────────────────────────────────┤
│ /codify ───────────────→ goals/ + decisions.log            │
│ /update-memory ────────→ context/ + lessons-learned.md     │
│ /consolidate-memory? ──→ master memory (if complex)        │
└─────────────────────────────────────────────────────────────┘
   │
   ↓
DONE. Ready to push.
```

---

## Decision Logic (When Each Path Runs)

### Phase 1: Always
- Step 1a: `/brainstorm` ✅ ALWAYS
- Step 1b: `/piv-plan` ✅ ALWAYS
- Step 1c: `/wave-analyst` ❓ IF (hard research OR major decision)

### Phase 2: One of Three
```
IF task is breakable into parallel subtasks:
  → /split-and-verify (subagents in parallel)
ELSE IF task is vague AND > 6 hours:
  → ralph.py --worktree (autonomous loop)
ELSE:
  → /piv-implement (linear execution)
```

### Phase 3: All Four, Always
- Step 3a: `/review` ✅ ALWAYS
- Step 3b: `/verify` ✅ ALWAYS
- Step 3c: `validate.py` ✅ ALWAYS (must pass)
- Step 3d: `/code-sparring` ✅ ALWAYS

### Phase 4: All Three
- Step 4a: `/codify` ✅ ALWAYS
- Step 4b: `/update-memory` ✅ ALWAYS
- Step 4c: `/consolidate-memory` ❓ IF (multiple related lessons)

---

## Example: Quick 10-Minute Fix

```
/harness "fix typo in staff_sheet.py"

PHASE 1 (5 min):
  /brainstorm → "just fix the typo, no architecture needed"
  /piv-plan → plans/typo-fix-plan.md (1 task: "fix line 42")

PHASE 2 (2 min):
  /piv-implement plans/typo-fix-plan.md → 1 commit

PHASE 3 (5 min):
  /review → PASS
  /verify → PASS
  validate.py → exit 0
  /code-sparring → "looks good"

PHASE 4 (3 min):
  /codify → updated goals
  /update-memory → "typos caught by code-sparring"

TOTAL: ~15 min
```

---

## Example: Complex 2-Hour Research Task

```
/harness --ralph "research how to improve drop-map detection accuracy"

PHASE 1 (10 min):
  /brainstorm → "consider YOLO model tuning, data augmentation, post-processing"
  /piv-plan → plans/drop-map-research-plan.md (vague, research-focused)
  /wave-analyst → "should we retrain or optimize existing model?"

PHASE 2 (90 min):
  ralph.py --worktree --db-isolate → ralph/run-20260622-143000
    Iteration 1: Try YOLO tuning → commit
    Iteration 2: Test augmentation → commit
    Iteration 3: Compare results → commit
    Iteration 4: Choose best approach → DONE.txt

PHASE 3 (20 min):
  /review → CONCERNS (check GPU memory usage)
  /verify → PASS (tests pass)
  validate.py → exit 0
  /code-sparring → "potential memory leak in iteration 3"

PHASE 4 (15 min):
  /codify → research goal marked DONE, decision: "chose augmentation over retrain"
  /update-memory → "YOLO tuning requires careful batch size + augmentation combo"
  /consolidate-memory → linked to prior YOLO learnings

TOTAL: ~135 min (~2.25 hours)
```

---

## Git State at Each Phase End

### After Phase 1
```
master branch:
  - No new commits
  - New files: plans/<slug>-plan.md, ai-hub/docs/<analysis>.md
  - Git status: clean (only new untracked files)
```

### After Phase 2
```
master branch:
  - N new commits (one per task)
  - Modified files: commands/*.py, core/*.py, tasks/*.py, etc.
  - Git status: uncommitted changes already committed
  
OR (if ralph.py):
  ralph/run-<timestamp> branch:
    - M new commits (iterative work)
    - Branch ready to merge
```

### After Phase 3
```
master branch:
  - Same commits as Phase 2
  - New files: reports/<feature>-review.md
  - Git status: clean (all changes committed)
  
Decision: PASS or CONCERNS (user decides next step)
```

### After Phase 4
```
master branch:
  - Same commits as Phase 2
  - Memory updated: ai-hub/memory/goals/, decisions.log, lessons-learned.md
  - Git status: clean
  
Ready for: git push origin master
```

---

## Usage

```bash
# Simple task
/harness "fix the typo in staff_sheet.py"

# Feature with design
/harness "build a new accuracy streak leaderboard"

# Research task (autonomous, 6+ hours)
/harness --ralph "research how to detect YOLO edge cases"

# Complex task with parallel subtasks
/harness --parallel "refactor drop-map system (split into: data, ui, scoring)"
```

---

## Summary: What You Get

✅ **Planner:** Brainstorm + detailed plan  
✅ **Generator:** Execute (linear, parallel, or autonomous)  
✅ **Evaluator:** Multi-reviewer consensus (PASS or CONCERNS)  
✅ **Feedback:** Goals updated, decisions logged, lessons saved  

**One command. All phases. Autonomous execution.**

---

**Last updated:** 2026-06-22  
**Status:** Ready to build  
**Next step:** Implement the harness skill
