---
name: harness
description: 4-phase autonomous feature development orchestrator—planner → generator → evaluator → feedback
---

# /harness — Execute Now

You are running the 4-phase harness. This is not documentation — these are your instructions. Execute each phase in order. Do not skip steps. Do not summarize what you're about to do — just do it.

**Task args:** {{args}}

---

## PHASE 1: PLANNER

### Step 1.1 — Brainstorm (ALWAYS)

Invoke the `brainstorm` skill now with the task args. The brainstorm skill will:
- Sketch the system architecture
- Identify data structures needed
- Surface gotchas and risks

After brainstorm completes, hold its output in context. You will feed it to piv-plan.

### Step 1.2 — Plan (ALWAYS)

Invoke the `piv-plan` skill now with:
- The original task args
- The brainstorm output from Step 1.1 as context

The plan skill will produce a file at `ai-hub/plans/<slug>-plan.md` containing:
- Exact files to read before implementing (with line numbers)
- Ordered tasks (1, 2, 3...) with exact edits
- Validation commands per task
- Acceptance criteria checklist
- **For bug fixes:** The plan MUST include a task to write a failing test script BEFORE writing the fix (TDD).

After piv-plan completes, note the plan file path. You will pass it to Phase 2.

### Step 1.3 — Wave Analyst (CONDITIONAL)

Run wave-analyst ONLY IF any of these are true:
- Args contain words: "research", "investigate", "explore", "decide", "should we"
- User passed `--research` flag
- Brainstorm output says "major decision" or "uncertain approach"

If condition met: invoke `wave-analyst` skill with the task args + brainstorm output.
If condition not met: skip this step entirely, proceed to Phase 2.

---

## PHASE 2: GENERATOR

Choose exactly ONE path. Do not run more than one.

### Decision Tree

**Question 1:** Do the args contain "split into:", "separate:", "parallel:", "independent" — or was `--parallel` flag passed?
- YES → Run Path A (split-and-verify)
- NO → Question 2

**Question 2:** Are the args vague ("figure out", "research", "explore") AND was `--ralph` flag passed?
- YES → Run Path B (ralph.py)
- NO → Run Path C (piv-implement) — this is the default

---

### Path A — Parallel (split-and-verify)

Invoke the `split-and-verify` skill with:
- The plan file from Step 1.2
- The original task args

Split-and-verify will spawn parallel subagents and merge results to master. When it completes, proceed to Phase 3.

---

### Path B — Autonomous (ralph.py)

Run ralph.py in a worktree:

```
python ai-hub/scripts/ralph.py --worktree
```

Before running, write the task spec to `ralph/PROMPT.md` based on the plan from Step 1.2.

Ralph will iterate autonomously until it writes `ralph/DONE.txt` or hits MAX_ITER (15). When ralph exits, note the branch name (`ralph/run-<timestamp>`). Proceed to Phase 3.

---

### Path C — Linear (piv-implement) — DEFAULT

Invoke the `piv-implement` skill with the plan file path from Step 1.2:

```
/piv-implement ai-hub/plans/<slug>-plan.md
```

Piv-implement will read the plan, make each edit in order, and commit after each task. When it completes, proceed to Phase 3.

---

## PHASE 3: EVALUATOR

Run ALL FIVE of these. Run them now, one after another (or note results as you go).

### Step 3.1 — Code Review

Invoke the `code-review` skill on the current git diff. It checks AGENTS.md rules:
- Windows paths (pathlib.Path used?)
- SQLite async pool correct?
- No direct user.send() calls?
- Rate limit checks in place?

Record result: PASS or CONCERNS (with details).

### Step 3.2 — Verify

Invoke the `verify` skill (from superpowers). It checks:
- Do acceptance criteria from the plan pass?
- Does the feature work as intended?

Record result: PASS or CONCERNS (with details).

### Step 3.3 — Validate Gate (HARD GATE)

Run:
```
python ai-hub/gates/validate.py
```

If exit code ≠ 0: record CONCERNS (with the specific error output). Do not stop immediately—the Phase 3 Gate Logic will handle the auto-retry loop.

If exit code = 0: record PASS, continue.

### Step 3.4 — Code Sparring

Invoke the `code-sparring` skill on the changed code. It will adversarially hunt for:
- Bugs and edge cases
- Race conditions or deadlocks
- Anti-patterns

Record result: PASS or CONCERNS (with details).

### Step 3.5 — Fresh Eyes Sanity Check

Spawn a new background subagent using the `invoke_subagent` tool. Give it ONLY the original task description and the current git diff (do NOT give it your full conversation history or the plan file). Ask it: "Does this code change actually solve the stated problem cleanly, or did we overcomplicate it/miss the point?"

Since the subagent spawns with an empty context window, it will provide an unbiased, 'fresh eyes' sanity check on the code.

Record result: PASS or CONCERNS (with details).

---

### Phase 3 Gate Logic

After all five complete:

**IF validate.py failed (Step 3.3) OR any of 3.1, 3.2, 3.4, or 3.5 say CONCERNS:**
Initiate the **Auto-Retry Loop**:
1. Take all the errors and concerns gathered.
2. Pipe them back to **Phase 2 (Generator)** and instruct the agent/subagent to fix them.
3. Re-run Phase 3 from the beginning.
4. You may do this up to **3 times**.
5. If it still fails after 3 retries, THEN stop, print the concerns, and ask the user:
> "Validation failed 3 times. Do you want to step in and fix them, or accept the risk and continue to Phase 4?"
Wait for user response:
- "fix" → Stop here. User will fix and re-run.
- "accept" → Continue to Phase 4, noting the accepted concerns.

**IF all five say PASS (or pass after auto-retry):**
Print: "✅ All checks passed. Proceeding to Phase 4."
Continue to Phase 4.

---

## PHASE 4: FEEDBACK

Only reach here if Phase 3 passed (or user accepted concerns).

### Step 4.1 — Codify (ALWAYS)

Invoke the `codify` skill. Pass it:
- What was completed in this harness run
- Any decisions made during planning or implementation

Codify will update:
- `ai-hub/memory/goals/<task>-goal.md` (mark done/in-progress)
- `ai-hub/memory/decisions.log` (append decision + rationale + timestamp)

### Step 4.2 — Update Memory (ALWAYS)

Invoke the `update-memory` skill. Reflect on this harness run and pass it:
- Lessons learned
- Mistakes made or near-misses caught by Phase 3
- Patterns discovered

Update-memory will create a context file and add a link to `ai-hub/memory/global-memory/lessons-learned.md`.

### Step 4.3 — Consolidate Memory (CONDITIONAL)

Run consolidate-memory ONLY IF:
- 3 or more lessons came out of Step 4.2
- The lessons span multiple systems
- They are clearly related to each other

If condition met: invoke `consolidate-memory` skill with the lessons from Step 4.2.
If condition not met: skip this step.

### Step 4.4 — Worktree Cleanup & Merge (CONDITIONAL)

Run this ONLY IF:
- Phase 2 used Path B (`ralph.py`) which created a separate git worktree branch.
- Phase 3 passed successfully.

If condition met:
- Run `git merge <ralph-branch-name>` into master.
- Delete the temporary worktree and branch to keep the environment clean.

---

## DONE

After Phase 4 completes, print a summary:

```
✅ HARNESS COMPLETE
═══════════════════════════════
Phase 1 — Plan:        ✅ Done
Phase 2 — Generate:    ✅ Done  [which path: implement/parallel/ralph]
Phase 3 — Evaluate:    ✅ Done  [PASS / CONCERNS ACCEPTED]
Phase 4 — Feedback:    ✅ Done

Commits on master: [list commit hashes + messages]
Plan file: ai-hub/plans/<slug>-plan.md
Lessons saved: [list any new context files]

Ready to push:
  git push origin master
```

---

## Error Handling

**If any skill invocation fails or errors:**
- Print what failed and why
- Ask user: "Should I retry, skip this step, or stop the harness?"
- Wait for their answer before continuing

**If a plan file is not produced by piv-plan:**
- Tell the user the plan was not generated
- Do not proceed to Phase 2 — a plan is required

**If ralph.py is not found:**
- Tell the user: "ralph.py not found at ai-hub/scripts/ralph.py"
- Fall back to Path C (piv-implement) instead

**If a skill is not available:**
- Note which skill is missing
- Skip that specific step
- Continue with remaining steps in the phase
- Report the skip in the final summary
