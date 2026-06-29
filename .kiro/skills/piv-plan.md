---
name: plan
description: Analyze a ticket or feature description, read the codebase, identify risks, and write a context-rich implementation plan to plans/<feature-slug>-plan.md. No code is written in this phase.
disable-model-invocation: true
---

# /plan — Analyze + Plan a Feature

**Usage:** `/plan <ticket-or-feature-description>`

Produces a context-rich implementation plan. **No code is written in this phase.**

---

## Process

### 1. Understand the ticket

Extract from `$ARGUMENTS`:
- Feature type (new capability / enhancement / bug fix / refactor)
- Affected resources and layers (model, schema, service, route, frontend)
- Acceptance criteria

### 2. Read the codebase

Load `AGENTS.md` first for naming + pattern rules. Then read:

- Every existing file that will be **modified** — get real line numbers.
- The closest analogue to what you're building (e.g., building a new discord command → read existing cogs).
- Load relevant context modules from `ai-hub/docs/` or `ai-hub/memory/` (see the Codebase Map in `AGENTS.md`).

Identify:
- Files to modify (with line refs)
- New files to create
- Migration needed? (any new table or column → yes)

### 3. Think through risks

- Edge cases (empty lists, null fields, concurrent requests)
- Database concurrency (SQLite 5-connection async pool, WAL mode)
- Discord rate limits (check `rate_limits.log`)
- Cross-platform differences (use `pathlib.Path` for Windows compatibility)
- Task loops and DMs (never call `user.send()` directly)

### 4. Write the plan to a file

Use the **Write tool** to create the file `plans/<feature-slug>-plan.md` — this is a required deliverable, not optional. Do **NOT** just print the plan in your response; `/implement` reads it from disk, so the file must exist. Use this structure:

```markdown
# Plan: <Feature Name>

## Ticket
<ticket ID and one-sentence description>

## Affected Files
### Read before implementing
- `<path>` (lines N-M) — <why>
### Modify
- `<path>` — <what changes>
### Create
- `<path>` — <purpose>

## Ordered Tasks

### Task 1 — <action> <target>
- What: <specific change>
- Pattern: `<path>:L<line>` — <what to mirror>
- Gotcha: <known trap if any>
- Validate: `<exact shell command>`

### Task 2 — ...

(continue for all tasks in dependency order)

## Validation Gate
Run these in order after all tasks are done:
```
bash ai-hub/gates/validate.sh
```

## Acceptance Criteria
- [ ] <measurable criterion 1>
- [ ] <measurable criterion 2>
- [ ] All validation gate commands pass
```

### 5. Confirm

After writing the plan file, output:
- Path: `plans/<feature-slug>-plan.md`
- Complexity: Low / Medium / High
- Key risks
- Confidence score (N/10 that `/implement` will succeed first-pass)

---

**Handoff:** Pass the plan path to `/implement plans/<feature-slug>-plan.md`.
