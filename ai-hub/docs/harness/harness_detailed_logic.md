---
name: harness-detailed-logic
description: "Complete detailed breakdown of harness logic—when each skill activates, when they run together, exact conditions and flow"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7edafa36-7802-47fe-8991-f773a1b263fa
---

# Harness — Complete Detailed Logic

## USER INPUT

```
/harness "task description" [--ralph] [--parallel]
```

---

# PHASE 1: PLANNER — Complete Flow

## Step 1.1: Always Run `/brainstorm`

**Trigger:** ALWAYS (every harness run)

**Input:**
- User's task description
- Task complexity (rough estimate)

**Process:**
1. Brainstorm reads the description
2. Outputs design doc with:
   - System architecture sketch
   - Data structures needed
   - API/interface design
   - Known gotchas

**Output:** Design document (in memory, for context)

**Next:** Continue to Step 1.2

---

## Step 1.2: Always Run `/piv-plan`

**Trigger:** ALWAYS (every harness run)

**Input:**
- Original task description
- Brainstorm output (in context)

**Process:**
1. Plan reads the brainstorm output
2. Reads relevant code files from AGENTS.md codebase map
3. Writes detailed `plans/<slug>-plan.md` with:
   - Read-before-implementing files (exact line numbers)
   - Modify files (exact changes)
   - Create files (new paths)
   - Ordered tasks (1, 2, 3... in dependency order)
   - Validation commands for each task
   - Acceptance criteria checklist

**Output:** `plans/<slug>-plan.md`

**Next:** Check if wave-analyst should run

---

## Step 1.3: CONDITIONAL `/wave-analyst`

**Trigger:** IF ANY of these are true:
- Task description contains words: "research", "investigate", "explore", "decide", "should we"
- User passes `--research` flag
- Brainstorm output mentions "major decision" or "uncertain approach"

**Input:**
- Original task description
- Brainstorm output

**Process:**
1. Wave-analyst analyzes the decision/research problem
2. Outputs 4-section analysis:
   - Problem statement (what's the actual decision?)
   - Risks & gotchas (what could go wrong?)
   - Alternatives (what else could we do?)
   - Expert disagreement (where do smart people disagree?)

**Output:** Analysis document

**When Happens:** ~5 min after piv-plan completes

**Next:** All Phase 1 skills done → Move to Phase 2

---

## Phase 1 Summary

```
EVERY HARNESS:
  brainstorm (10 min) → design doc
       ↓
  piv-plan (5 min) → plans/<slug>-plan.md
       ↓
  IF (hard research OR decision):
    wave-analyst (10 min) → analysis doc

Total Phase 1: 15-25 min
```

---

# PHASE 2: GENERATOR — Complete Flow

## Decision Tree Entry

**Question 1:** Is task breakable into independent parallel subtasks?

```
IF YES (e.g., "refactor X (split into: A, B, C)"): → Go to Section 2.1
IF NO: → Go to Question 2
```

---

## Section 2.1: Parallel Path (if breakable)

**Trigger:** Task description contains:
- "split into:", "separate:", "parallel:", "independent"
- OR user passes `--parallel` flag

**Skill:** `/split-and-verify`

**Process:**
1. Harness receives plan with breakable subtasks
2. Spawns `/split-and-verify` with plan
3. Split-and-verify does:
   - Reads plan
   - Identifies N independent subtasks
   - Spawns N subagents, each on own session/branch
   - Each subagent runs `/piv-implement` on their subtask
   - Each produces verified output + branch
   - Combines all branches into single master branch
4. All commits merged to `master` (local)

**Time:** 30-90 min (parallel, so faster than serial)

**Output:** `master` branch with N merged commits

**Next:** Phase 3 (Evaluator)

---

## Question 2 (if NOT parallel)

**Question:** Is this a vague/research task that will take 6+ hours?

```
IF YES (vague spec + 6+ hrs): → Go to Section 2.2
IF NO (clear plan + < 6 hrs): → Go to Section 2.3
```

---

## Section 2.2: Autonomous Path (if vague + 6+ hours)

**Trigger:**
- User passes `--ralph` flag
- OR task description is vague ("figure out", "research", "explore")
- AND estimated time > 6 hours

**Skill:** `ralph.py --worktree`

**Process:**
1. Harness creates `ralph/PROMPT.md` from plan (spec)
2. Spawns `ralph.py --worktree --db-isolate` in background
3. Ralph creates:
   - New git worktree at `../ralph-worktrees/ralph-run-<timestamp>`
   - New git branch `ralph/run-<timestamp>`
   - Copy of `bot_database.db` (isolated for this run)
4. Ralph loop runs:
   - Feeds spec to `claude -p` (Agent SDK CLI)
   - Claude makes edits, commits (Iteration 1)
   - Ralph checks for `ralph/DONE.txt`
   - If not found: feed to Claude again (Iteration 2)
   - Repeat until DONE.txt or MAX_ITER (15) reached
5. Final state:
   - Branch `ralph/run-<timestamp>` has N commits
   - Log at `ralph/ralph.log` with all iterations
   - Summary printed with merge instructions

**Time:** 30 min to 2+ hours (autonomous, agent figures it out)

**Output:** 
- New branch `ralph/run-<timestamp>` (not on master yet)
- Log file with iteration history
- Ready for merge

**Next:** Checkout the ralph branch locally, then Phase 3 (Evaluator)

---

## Section 2.3: Linear Path (default, clear plan + < 6 hours)

**Trigger:** 
- NOT parallel (no --parallel flag, task isn't breakable)
- NOT vague/long (no --ralph flag, task is clear + < 6 hrs)

**Skill:** `/piv-implement plans/<slug>-plan.md`

**Process:**
1. Harness passes plan file to piv-implement
2. Piv-implement reads plan file:
   - Exact files to modify (line numbers)
   - Ordered tasks (1, 2, 3...)
3. For each task:
   - Open file at exact line
   - Make edit (insert/delete/modify)
   - Commit with task description
   - Move to next task
4. All commits go to `master` branch (local)
5. After all tasks done, validate each one

**Time:** 10-60 min (depends on # of tasks)

**Output:** `master` branch with N new commits (one per task)

**Next:** Phase 3 (Evaluator)

---

## Phase 2 Summary

```
PHASE 2 DECISION TREE:

Question 1: Task breakable into parallel subtasks?
  YES → /split-and-verify (30-90 min parallel)
  NO  → Question 2

Question 2: Vague task + 6+ hours?
  YES → ralph.py --worktree (30 min - 2+ hrs autonomous)
  NO  → /piv-implement (10-60 min linear)

All paths output: Git branch with new commits (ready for review)
```

---

# PHASE 3: EVALUATOR — Complete Flow

## All Four Skills Run IN PARALLEL

**Trigger:** ALWAYS (always, for every harness, no conditions)

**Skills:**
1. `/review`
2. `/verify`
3. `python ai-hub/gates/validate.py`
4. `/code-sparring`

### Skill 3.1: `/review` (ALWAYS)

**Input:** Git diff from Phase 2

**Checks:**
- Windows paths? (use `pathlib.Path`?)
- SQLite async pool? (5 connections, WAL mode?)
- DM queue? (user.send() intercepted correctly?)
- Rate limit checks? (< 3 requests remaining?)
- Cross-guild role sync? (consistent across 3 guilds?)

**Output:** `reports/<feature>-review.md` with:
```
PASS: All AGENTS.md rules met
  ✓ Windows paths
  ✓ SQLite pool
  ✓ DM queue
  ✓ Rate limits

OR

CONCERNS:
  ✗ Line 42: Using os.path instead of pathlib.Path
  ✗ Line 156: Async pool not using 5-connection limit
  → See details in report
```

**Time:** 2-5 min

**Runs in parallel with:** 3.2, 3.3, 3.4

---

### Skill 3.2: `/verify` (ALWAYS)

**Input:**
- Changed code
- Acceptance criteria from plan

**Checks:**
- Do tests pass?
- Does feature work as intended?
- Do all acceptance criteria pass?

**Output:** `test-results.md` with:
```
Test Results:
  ✓ test_drop_map_claim() passed
  ✓ test_streak_increment() passed
  ✓ test_concurrent_claims() passed

Feature Checklist:
  ✓ Users can claim maps
  ✓ Streaks persist
  ✓ Leaderboard updates

Verdict: PASS
```

**Time:** 5-15 min

**Runs in parallel with:** 3.1, 3.3, 3.4

---

### Skill 3.3: `validate.py` (ALWAYS)

**Input:** All code in `commands/`, `core/`, `tasks/`

**Checks:**
1. Security (via `security_check.py`):
   - No `.env` files staged?
   - No API keys in code?
   - No secrets committed?
   
2. Lint (via `ruff`):
   - Syntax errors?
   - Import issues?
   - Style violations? (ignoring legacy nits)

3. Sync (via `sync_agent_skills.py`):
   - All skills synced to `.claude/`, `.cursor/`, `.qoder/`?

**Output:**
```
Exit Code 0 = PASS
  ✓ Security check passed
  ✓ Lint passed
  ✓ Skills synced

OR

Exit Code 1+ = FAIL
  ✗ Security: .env file found in staging
  → Fix and re-run: python ai-hub/gates/validate.py
```

**Time:** 2-5 min

**Runs in parallel with:** 3.1, 3.2, 3.4

**CRITICAL:** If exit code ≠ 0, harness STOPS here. User must fix.

---

### Skill 3.4: `/code-sparring` (ALWAYS)

**Input:** Changed code

**Checks:**
- Try to find bugs (adversarial)
- Edge cases? (empty lists, null fields, off-by-one?)
- Anti-patterns? (N+1 queries, blocking calls, race conditions?)
- Performance? (O(n²) where should be O(n)?)

**Output:** `code-sparring-findings.md` with:
```
Potential Issues:
  ⚠ Line 78: Off-by-one in streak calculation
     If streak = 0, line 78 would return -1 instead of 0
     Risk: Low (only edge case)
  
  ⚠ Line 156: Async pool not checking connection limit
     If 10 requests hit simultaneously, pool only has 5 connections
     Risk: High (could deadlock)
     
  ⚠ Line 220: user.send() called directly (should use queue)
     Risk: High (bypasses DM interception)

Verdict: CONCERNS
```

**Time:** 5 min

**Runs in parallel with:** 3.1, 3.2, 3.3

---

## After All Four Complete (Gate Logic)

```
Wait for ALL FOUR to finish (they run in parallel, so wait for slowest)

Then check results:

IF validate.py exit code ≠ 0:
  → STOP HARNESS
  → Print: "Fix these issues, then re-run harness"
  → User must fix and re-run

IF all 4 say PASS (no CONCERNS):
  → Continue to Phase 4
  → Print: "All checks passed! Proceeding to feedback phase."

IF any of 3.1, 3.2, 3.4 say CONCERNS:
  → Print all concerns
  → Ask user: "Fix these or accept risk?"
  → User chooses:
    - "Fix" → go back to Phase 2 (re-implement)
    - "Accept" → continue to Phase 4 with noted concerns
```

---

## Phase 3 Summary

```
PHASE 3 (PARALLEL):

review ────────→ rules compliance (PASS or CONCERNS)
verify ────────→ tests pass (PASS or CONCERNS)
validate.py ───→ security + lint (PASS or FAIL)
code-sparring ─→ bug hunt (PASS or CONCERNS)
       ↓ (all done, check results)
       
Gate:
  validate.py = FAIL? → STOP, fix, re-run
  All others = PASS? → Continue to Phase 4
  Any = CONCERNS? → Show findings, ask user (fix or accept risk)

Total Phase 3: 14-30 min (parallel, so not sum of times)
```

---

# PHASE 4: FEEDBACK — Complete Flow

**Trigger:** ONLY if Phase 3 passed (or user accepted concerns)

## Step 4.1: Always Run `/codify`

**Trigger:** ALWAYS (every harness that reaches Phase 4)

**Input:**
- What was completed
- Decisions made during harness

**Process:**
1. Harness prompts user: "What did this harness complete? Any decisions?"
2. Codify updates:
   - `ai-hub/memory/goals/<task>-goal.md`:
     ```
     Status: IN_PROGRESS → DONE (or BLOCKED)
     Completion: 0% → 100%
     Finished: 2026-06-22 14:30
     ```
   - `ai-hub/memory/decisions.log`:
     ```
     [2026-06-22 14:30] DECISION: Use YOLO tuning instead of retraining
     Harness: drop-map-research
     Rationale: Faster iteration, same accuracy gains
     Owner: harness
     ```

**Output:**
- Updated goal files
- New entries in decisions.log

**Time:** 2-5 min

**Next:** Step 4.2

---

## Step 4.2: Always Run `/update-memory`

**Trigger:** ALWAYS (every harness that reaches Phase 4)

**Input:**
- Lessons learned from this harness run
- Mistakes made
- Patterns discovered

**Process:**
1. Harness asks user: "What did you learn? Any mistakes to avoid next time?"
2. Update-memory creates:
   - `ai-hub/memory/global-memory/context/<lesson-slug>.md`:
     ```
     # Lesson: YOLO Async Pool Management
     
     ## Incident
     Harness run drop-map-research tried to spawn 10 YOLO queries.
     Database deadlocked because pool only has 5 connections.
     
     ## Root Cause
     Code didn't check async pool connection limit before spawning queries.
     
     ## New Rule
     Always spawn N concurrent async operations where N ≤ pool size (5).
     Use semaphore or queue to throttle.
     
     ## Example
     [code example of correct pattern]
     ```
   - Updates `ai-hub/memory/global-memory/lessons-learned.md`:
     ```
     - [YOLO Async Pool Management](context/yolo-async-pool.md)
     ```

**Output:**
- New context file
- Updated lessons-learned.md with link

**Time:** 5-10 min

**Next:** Check if consolidate-memory should run

---

## Step 4.3: CONDITIONAL `/consolidate-memory`

**Trigger:** IF ANY of these:
- User has 3+ lessons from this harness run
- Lessons span multiple systems (e.g., "async pool" + "DM queue" + "rate limits")
- User says "these lessons are related"

**Input:**
- Multiple lessons from Step 4.2
- Prior related lessons from memory

**Process:**
1. Consolidate-memory reads all related lessons
2. Finds connections between them
3. Writes master memory file:
   ```
   # Master: Wave-Management-Bot Infrastructure Patterns
   
   ## Connection 1: Concurrency Limits
   - Async pool: 5 connections
   - DM queue: single-threaded
   - Rate limits: <3 requests remaining
   → All enforce different concurrency constraints
   
   ## Connection 2: Interception Patterns
   - DM queue intercepts user.send()
   - Rate limit checks intercept API calls
   → Similar pattern, different contexts
   
   ## Connection 3: Cross-Guild Sync
   - Roles must stay consistent across 3 guilds
   - Rate limits affect sync speed
   → Concurrency + consistency interplay
   ```
4. Updates `lessons-learned.md` to point to master file instead of 3 separate ones

**Output:**
- Master memory file with cross-links
- Updated lessons-learned.md

**Time:** 10 min

**When Happens:** Only if findings are complex/related (optional)

---

## Phase 4 Summary

```
PHASE 4 (SEQUENTIAL):

Step 4.1: /codify (2-5 min) → goals/ + decisions.log updated
   ↓
Step 4.2: /update-memory (5-10 min) → context/ + lessons-learned.md updated
   ↓
Step 4.3: /consolidate-memory? (10 min)
  IF (multiple related lessons):
    → master memory file + cross-links
  ELSE:
    → skip

Total Phase 4: 7-25 min
```

---

# COMPLETE HARNESS EXAMPLE: 10-MINUTE FIX

```
USER INPUT:
  /harness "fix typo in staff_sheet.py line 42"

─────────────────────────────────────────────────────────────

PHASE 1 (5 min):
  
  /brainstorm
    Input: "fix typo in staff_sheet.py line 42"
    Output: "Simple fix, no architecture needed"
  
  /piv-plan
    Input: Brainstorm output
    Output: plans/staff-sheet-typo-plan.md
      Task 1: Fix typo on line 42 (change "namee" to "name")
      Validation: Lint passes, no syntax errors
  
  /wave-analyst?
    Condition: Hard research? NO
    Result: SKIPPED

─────────────────────────────────────────────────────────────

PHASE 2 (2 min):
  
  Question 1: Breakable into parallel tasks?
    Answer: NO (just one edit)
  
  Question 2: Vague + 6+ hours?
    Answer: NO (clear, 1 minute)
  
  /piv-implement plans/staff-sheet-typo-plan.md
    Task 1: Edit line 42, change "namee" to "name"
    Commit: "fix: correct spelling of 'name' in staff_sheet.py"
  
  Output: master branch with 1 new commit

─────────────────────────────────────────────────────────────

PHASE 3 (5 min, PARALLEL):
  
  /review
    Check: Windows paths? SQLite pool? DM queue? Rate limits?
    Output: PASS (trivial fix, no gotchas)
  
  /verify
    Check: Tests pass? Feature works?
    Output: PASS (typo fix, tests still pass)
  
  validate.py
    Check: Security? Lint? Sync?
    Output: exit 0 (PASS)
  
  /code-sparring
    Check: Bugs? Edge cases?
    Output: PASS (just a typo fix)
  
  Gate: All PASS → Continue to Phase 4

─────────────────────────────────────────────────────────────

PHASE 4 (3 min):
  
  /codify
    Input: "Fixed typo in staff_sheet.py"
    Output: goals/ updated (typo fix marked DONE)
  
  /update-memory
    Input: "Typos caught by code-sparring"
    Output: context/typo-prevention.md created
  
  /consolidate-memory?
    Condition: Multiple related lessons? NO
    Result: SKIPPED

─────────────────────────────────────────────────────────────

DONE. Ready to push.
  git push origin master

Total time: ~15 min
```

---

# COMPLETE HARNESS EXAMPLE: 2-HOUR RESEARCH TASK

```
USER INPUT:
  /harness --ralph "research how to improve drop-map detection accuracy"

─────────────────────────────────────────────────────────────

PHASE 1 (15 min):
  
  /brainstorm
    Input: "research how to improve drop-map detection"
    Output: Design doc
      "Consider YOLO model tuning, data augmentation, 
       post-processing filters. Maybe retrain from scratch?"
  
  /piv-plan
    Input: Brainstorm output
    Output: plans/drop-map-research-plan.md
      Task 1: Investigate YOLO tuning (batch size, learning rate)
      Task 2: Implement data augmentation pipeline
      Task 3: Compare results (tuning vs augmentation vs both)
      Task 4: Choose best approach
      Note: Vague research, exact implementation TBD
  
  /wave-analyst?
    Condition: Hard research? YES (word "research" in description)
    /wave-analyst runs:
      Input: "Should we retrain YOLO or optimize existing?"
      Output: analysis/drop-map-retrain-decision.md
        Problem: Accuracy plateau at 92%
        Risks:
          - Retraining expensive (GPU time, data labeling)
          - Tuning might plateau even lower
        Alternatives:
          - Keep current model + post-processing filters
          - Collect more training data (time intensive)
          - Use ensemble of models
        Expert disagreement:
          - ML team: "retrain, data is the answer"
          - Infrastructure team: "tune existing, faster iteration"

─────────────────────────────────────────────────────────────

PHASE 2 (90 min):
  
  Question 1: Breakable into parallel tasks?
    Answer: NO (research needs sequential iteration)
  
  Question 2: Vague + 6+ hours?
    Answer: YES (vague spec, 2+ hour estimate, --ralph flag)
  
  ralph.py --worktree --db-isolate
    Creates: ralph/run-20260622-143000 branch
    Creates: Isolated copy of bot_database.db
    
    Iteration 1 (20 min):
      Claude reads plan
      Tries: YOLO tuning (batch=16, lr=0.001)
      Runs benchmark test
      Commits: "ralph iter 1: YOLO tuning attempt"
    
    Iteration 2 (20 min):
      Claude reads iter 1 results
      Tries: Data augmentation (rotation, scale, flip)
      Runs benchmark test
      Commits: "ralph iter 2: data augmentation attempt"
    
    Iteration 3 (20 min):
      Claude compares results
      Tries: Combined (tuning + augmentation)
      Runs benchmark test
      Commits: "ralph iter 3: combined approach"
    
    Iteration 4 (20 min):
      Claude analyzes all three
      Writes DONE.txt: "Best approach: augmentation only, +3% accuracy"
      Commits: "ralph iter 4: analysis complete"
    
    ralph.py exits
    Output: ralph/run-20260622-143000 branch ready to merge

─────────────────────────────────────────────────────────────

PHASE 3 (20 min, PARALLEL):
  
  /review
    Check: Windows paths? SQLite pool? DM queue? Rate limits?
    Output: CONCERNS (Line 156: ralph used 10 async queries, 
                      pool only has 5 connections)
  
  /verify
    Check: Tests pass? Feature works?
    Output: CONCERNS (Benchmark test passed, but under low load.
                      Real-world test timed out due to pool issues)
  
  validate.py
    Check: Security? Lint? Sync?
    Output: exit 0 (PASS)
  
  /code-sparring
    Check: Bugs? Edge cases?
    Output: CONCERNS (Memory leak in iteration 3, potential 
                      deadlock in concurrent scenarios)
  
  Gate: CONCERNS found
    Print all 3 concerns
    Ask user: "Fix these or accept risk?"
    
    User chooses: "Fix"
    Harness tells user:
      "Go back to Phase 2, fix these issues in the code"
      (User manually edits or re-runs harness with new spec)

─────────────────────────────────────────────────────────────

(User fixes concerns, re-runs /harness or manually fixes)

PHASE 3 (Round 2, 15 min):
  
  /review → PASS
  /verify → PASS
  validate.py → exit 0 (PASS)
  /code-sparring → PASS
  
  Gate: All PASS → Continue to Phase 4

─────────────────────────────────────────────────────────────

PHASE 4 (20 min):
  
  /codify
    Input: "Chose data augmentation approach, decided against retraining"
    Output: goals/drop-map-research.md marked DONE
            decisions.log appended:
              "[2026-06-22 15:30] DECISION: Use data augmentation over retraining
               Rationale: +3% accuracy improvement, faster iteration
               Owner: harness/drop-map-research"
  
  /update-memory
    Input: "Learned: async pool max 5 connections, always use semaphore for concurrent ops"
           "Learned: YOLO augmentation more effective than tuning for this dataset"
           "Learned: Memory management critical in iterative ML workflows"
    Output: context/async-pool-semaphore-pattern.md created
            context/yolo-augmentation-vs-tuning.md created
            context/ml-memory-management.md created
            lessons-learned.md updated with 3 new links
  
  /consolidate-memory?
    Condition: Multiple related lessons? YES (3 lessons, all infrastructure/ML patterns)
    /consolidate-memory runs:
      Input: The 3 lessons above
      Output: master/ml-infrastructure-patterns.md
        Section 1: Concurrency (async pool, semaphores, queues)
        Section 2: Memory management (iterations, garbage collection)
        Section 3: Data optimization (augmentation vs tuning, dataset composition)
      Updates lessons-learned.md to point to master file

─────────────────────────────────────────────────────────────

DONE. Ready to push.
  git checkout master
  git merge ralph/run-20260622-143000
  git push origin master

Total time: ~150 min (~2.5 hours)
```

---

# DECISION MATRIX: When Each Skill Runs

| Skill | Phase | Always? | Condition | Runs With |
|-------|-------|---------|-----------|-----------|
| `/brainstorm` | 1 | ✅ YES | — | /piv-plan |
| `/piv-plan` | 1 | ✅ YES | — | /brainstorm |
| `/wave-analyst` | 1 | ❌ NO | Hard research OR "decide/research/investigate" in description | /piv-plan (optional) |
| `/piv-implement` | 2 | ❓ MAYBE | Clear plan + < 6 hrs + NOT parallel | (runs alone) |
| `/split-and-verify` | 2 | ❓ MAYBE | Breakable into parallel subtasks | (runs alone) |
| `ralph.py` | 2 | ❓ MAYBE | Vague spec + 6+ hrs + --ralph flag | (runs alone) |
| `/review` | 3 | ✅ YES | — | /verify, validate.py, /code-sparring (all parallel) |
| `/verify` | 3 | ✅ YES | — | /review, validate.py, /code-sparring (all parallel) |
| `validate.py` | 3 | ✅ YES | — | /review, /verify, /code-sparring (all parallel) |
| `/code-sparring` | 3 | ✅ YES | — | /review, /verify, validate.py (all parallel) |
| `/codify` | 4 | ✅ YES | Phase 3 passed | /update-memory |
| `/update-memory` | 4 | ✅ YES | Phase 3 passed | /codify |
| `/consolidate-memory` | 4 | ❌ NO | Multiple related lessons | /update-memory (optional) |

---

# Summary: Skill Activation Rules

```
PHASE 1: Always run brainstorm + piv-plan
         Optionally run wave-analyst (if hard research)

PHASE 2: RUN ONE OF THREE:
           - /piv-implement (default, clear plan < 6 hrs)
           - /split-and-verify (breakable into parallel tasks)
           - ralph.py (vague spec + 6+ hours)

PHASE 3: ALWAYS run ALL FOUR in parallel:
           - /review (rules compliance)
           - /verify (functional testing)
           - validate.py (security + lint)
           - /code-sparring (adversarial code review)
         If ANY CONCERNS → ask user (fix or accept)
         If validate.py FAILS → stop harness, user must fix

PHASE 4: ALWAYS run codify + update-memory
         Optionally run consolidate-memory (if multiple related lessons)
```

---

**Last updated:** 2026-06-22  
**Status:** Complete detailed specification ready for implementation
