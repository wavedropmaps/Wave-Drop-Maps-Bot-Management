---
name: harness-bootstrap-prompt
description: "One-shot setup prompt for brand new projects—audits, builds, deploys the complete harness with all prerequisites"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7edafa36-7802-47fe-8991-f773a1b263fa
---

# Harness Bootstrap — Complete Setup for New Projects

**This is a self-contained prompt. Give it to Claude with your new project, and it will:**

1. ✅ Audit what you have (AGENTS.md, validation gate, skills)
2. ✅ Build what you're missing (validation gate, foundational skills)
3. ✅ Create all documentation (thresholds, specs, logic)
4. ✅ Deploy the harness skill
5. ✅ Sync to all agents (Claude, Cursor, Copilot, etc.)
6. ✅ Test on a sample task
7. ✅ Give you a checklist

**Time to complete: 4-6 hours (depends on what's missing)**

---

# BOOTSTRAP PROMPT — Copy This and Use It

## START HERE

```
You are implementing a 4-phase autonomous development harness for a new project.
This harness will orchestrate planning → generation → evaluation → feedback for 
every feature.

Your mission:

PHASE 0: AUDIT
  1. List all files at repo root (AGENTS.md, CLAUDE.md, validation gate, skills folder)
  2. Check: Does AGENTS.md or CLAUDE.md exist? (if no, error stop)
  3. Check: Does validation gate exist? (gates/validate.py or equivalent)
  4. Check: Do foundational skills exist? (brainstorm, piv-plan, review, verify, etc.)
     IMPORTANT — some commands live INSIDE bundle skills, not as their own folder:
       * /brainstorm AND /verify  → provided by the `superpowers` skill
       * /review                  → provided by the `code-reviewer` skill
     So before deciding a command is "missing", check whether `superpowers` and
     `code-reviewer` are installed. If they are, /brainstorm, /verify, /review
     ALREADY work — do NOT rebuild them. Only the standalone skills
     (piv-plan, piv-implement, wave-analyst, split-and-verify, code-sparring,
     codify, update-memory, consolidate-memory) need their own folders.
  5. Output: Audit report with HAVE vs MISSING (note WHICH skill provides each command)

PHASE 1: BUILD MISSING PREREQUISITES
  
  A. If AGENTS.md doesn't exist:
     - Create AGENTS.md at repo root with:
       * Project overview (1-2 sentences)
       * Key conventions (naming, paths, language)
       * Critical gotchas (what NOT to do)
       * Codebase map (which doc explains which system)
     - Size: ~100 lines, filled with project-specific rules
  
  B. If validation gate doesn't exist:
     - Create ai-hub/gates/validate.py with:
       * Security checks (no .env, no API keys staged)
       * Lint checks (your project's linter)
       * Optional: type checking, tests
     - Size: ~50-100 lines, tailored to your project
  
  C. If foundational skills don't exist:
     - FIRST check the bundle skills (don't rebuild what these already provide):
       * `superpowers` installed?  → /brainstorm and /verify already work. SKIP rebuilding them.
       * `code-reviewer` installed? → /review already works. SKIP rebuilding it.
       (If superpowers/code-reviewer are MISSING, install them OR build standalone
        brainstorm/verify/review skills as a fallback.)
     - Standalone skills to build if missing (each gets its own folder):
       * /piv-plan — detailed plan from design
       * /piv-implement — execute the plan
       * /wave-analyst — decision/research analysis
       * /split-and-verify — parallel subagent execution
       * /code-sparring — adversarial review
       * /codify — record goals + decisions
       * /update-memory — save lessons
       * /consolidate-memory — synthesize related lessons
     - Location: ai-hub/skills/{skill-name}/SKILL.md
     - Don't reinvent; use standard implementations

PHASE 2: CREATE DOCUMENTATION
  
  Create these docs (adapt from Wave-Management-Bot templates):
  
  1. harness-decision-thresholds.md
     - When to use /wave-analyst (keywords, prompt size, complexity)
     - When to use /split-and-verify (parallel criteria)
     - When to use ralph.py (vague + 6+ hrs)
     - When to use /piv-implement (default)
     - Size: ~200 lines with project-specific examples

  2. harness-phase-mapping.md
     - Which skills in each phase
     - Primary vs alternative skills
     - When each activates
     - Size: ~150 lines

  3. harness-complete-spec.md
     - Phase 1-4 detailed flows
     - Complete flow diagram (ASCII art OK)
     - 2-3 examples relevant to YOUR project
     - Size: ~300 lines

  4. harness-detailed-logic.md
     - Each phase step-by-step
     - Decision trees with exact conditions
     - Complete end-to-end examples
     - Error handling logic
     - Size: ~400 lines

PHASE 3: BUILD & DEPLOY HARNESS SKILL
  
  Create ai-hub/skills/harness/SKILL.md
  
  The skill:
    - Takes input: /harness "task description" [flags]
    - Orchestrates all 4 phases
    - Makes all decisions (which path in Phase 2?)
    - Runs all reviewers in parallel (Phase 3)
    - Records completion & lessons (Phase 4)
    - Handles errors (validation fail, CONCERNS, timeouts)
  
  Size: ~400 lines (don't overthink; pseudocode + clear flow is fine)
  
  Critical sections:
    1. Phase 1: brainstorm → piv-plan → wave-analyst?
    2. Phase 2 decision tree: parallel? vague+6hrs? → pick path
    3. Phase 3 gate: all 4 reviewers parallel, gate logic
    4. Phase 4: codify → update-memory → consolidate-memory?

PHASE 4: SYNC TO ALL AGENTS
  
  Copy the harness skill to all agent directories:
    - .claude/commands/harness.md (Claude Code)
    - .cursor/rules/skill-harness.mdc (Cursor)
    - .qoder/skills/harness/SKILL.md (Qoder)
    - .agents/skills.json entry (Antigravity, if used)
  
  Run skill-sync if it exists in your project

PHASE 5: TEST HARNESS
  
  A. Create a test task (something real but small):
     Example: "add a new config option to the app"
  
  B. Run: /harness "add a new config option to the app"
  
  C. Verify each phase:
     Phase 1: brainstorm + plan output generated ✓
     Phase 2: commits made to master ✓
     Phase 3: all 4 reviewers ran, no FAIL ✓
     Phase 4: goals + lessons updated ✓
  
  D. Check: git log shows clean commits (one per task) ✓

PHASE 6: DOCUMENT & SHIP
  
  A. Add to README:
     ```
     ## Using the Harness
     
     /harness "your task"
     /harness --ralph "research task"
     /harness --parallel "refactor (split: A, B, C)"
     
     See ai-hub/memory/harness-complete-spec.md for details.
     ```
  
  B. Add to ai-hub/memory/MEMORY.md:
     - Link to harness-decision-thresholds.md
     - Link to harness-complete-spec.md
     - Link to harness-detailed-logic.md
  
  C. Commit: "feat: install 4-phase harness orchestrator"

OUTPUT (When complete):

Print a checklist:

  HARNESS BOOTSTRAP COMPLETE
  ==========================
  
  ✓ Phase 0: Audited prerequisites
  ✓ Phase 1: Built missing pieces (list what was created)
  ✓ Phase 2: Created documentation (4 docs created)
  ✓ Phase 3: Deployed harness skill
  ✓ Phase 4: Synced to all agents
  ✓ Phase 5: Tested on sample task
  ✓ Phase 6: Documented & committed
  
  Ready to use:
    /harness "your task description"
  
  Key files:
    - AGENTS.md (project rules)
    - ai-hub/gates/validate.py (validation gate)
    - ai-hub/skills/harness/ (orchestrator)
    - ai-hub/memory/harness-*.md (documentation)
  
  Next: Try /harness on a real project task
```

---

## END PROMPT

---

# How to Use This

### Option 1: Give to Claude Code (or another AI agent)

**Instructions for user:**

1. Copy the prompt above (from "BOOTSTRAP PROMPT" to "END PROMPT")
2. Open Claude Code in your new project directory
3. Paste the prompt
4. Claude will:
   - Audit what you have
   - Build what's missing
   - Deploy the harness
   - Test it
   - Give you a checklist

**Time:** 4-6 hours (automated, you don't touch anything)

### Option 2: Use as a Checklist (Do It Yourself)

If you prefer to build manually, use the bootstrap prompt as a checklist:

- [ ] Phase 0: Audit (list what you have)
- [ ] Phase 1: Build AGENTS.md (if missing)
- [ ] Phase 1: Build validation gate (if missing)
- [ ] Phase 1: Copy foundational skills (if missing)
- [ ] Phase 2: Create 4 documentation files
- [ ] Phase 3: Create harness skill
- [ ] Phase 4: Sync to all agents
- [ ] Phase 5: Test on sample task
- [ ] Phase 6: Document and commit

---

# What Gets Created

After bootstrap completes, your project has:

```
repo-root/
  AGENTS.md                          (project rules)
  ai-hub/
    gates/
      validate.py                    (validation gate)
    skills/
      superpowers/SKILL.md           (bundle — provides /brainstorm + /verify)
      code-reviewer/SKILL.md         (bundle — provides /review)
      piv-plan/SKILL.md              (standalone)
      piv-implement/SKILL.md         (standalone)
      wave-analyst/SKILL.md          (standalone)
      split-and-verify/SKILL.md      (standalone)
      code-sparring/SKILL.md         (standalone)
      codify/SKILL.md                (standalone)
      update-memory/SKILL.md         (standalone)
      consolidate-memory/SKILL.md    (standalone)
      harness/SKILL.md               (orchestrator ← THE BIG ONE)
    memory/
      harness-decision-thresholds.md
      harness-phase-mapping.md
      harness-complete-spec.md
      harness-detailed-logic.md
      MEMORY.md                      (updated with links)
```

**Total:** ~2000 lines of code + documentation, all in place, ready to use.

---

# Time Breakdown

| Phase | Time | What |
|-------|------|------|
| 0: Audit | 5 min | Check what exists |
| 1: Build | 60 min | Create AGENTS.md, gate, skills (or verify existing) |
| 2: Docs | 90 min | Create 4 documentation files |
| 3: Harness | 45 min | Write orchestrator skill |
| 4: Sync | 10 min | Copy to all agents |
| 5: Test | 20 min | Run on sample task |
| 6: Ship | 15 min | Commit, document, done |
| **TOTAL** | **4-6 hours** | Complete harness, ready to use |

---

# Success Criteria

After bootstrap, you can:

- [ ] Run `/harness "simple task"` → completes in 15 min, commits clean
- [ ] Run `/harness --ralph "research"` → autonomous loop works
- [ ] Run `/harness --parallel "refactoring"` → spawns subagents
- [ ] Phase 3 catches CONCERNS → asks user to fix or accept
- [ ] Phase 4 updates memory → lessons appear next session
- [ ] `git log --oneline` shows clean history (one commit per task)

If all 6 boxes are checked, bootstrap succeeded.

---

# Customization Notes

The bootstrap prompt is **framework-agnostic** but needs customization:

### In Phase 1A (AGENTS.md)
Replace placeholders with YOUR project:
- Language/framework (Python, JavaScript, Go, etc.)
- Database system (PostgreSQL, MongoDB, SQLite, etc.)
- API style (REST, GraphQL, gRPC, etc.)
- Testing framework (pytest, jest, mocha, etc.)
- Deployment target (Docker, Kubernetes, Serverless, etc.)
- Critical gotchas (what breaks people in your project?)

### In Phase 1B (validate.py)
Choose checks relevant to your project:
- Language linter (ruff, pylint, eslint, golangci-lint)
- Type checker (mypy, typescript, go build)
- Test suite (pytest, jest, cargo test)
- Security (bandit, semgrep, trivy)

### In Phase 2 (Documentation)
Use Wave-Management-Bot docs as templates, replace examples with yours:
- Instead of "drop-map accuracy research" → your project's research tasks
- Instead of "Discord bot gotchas" → your project's gotchas
- Instead of "SQLite async pool" → your project's database patterns

---

# If You Want to Skip Bootstrap

If you just want the harness WITHOUT prerequisites:

1. Download `harness-complete-spec.md` + `harness-detailed-logic.md`
2. Read them to understand how it works
3. Manually create AGENTS.md + validation gate
4. Manually create foundational skills (or ask Claude to build them)
5. Create `ai-hub/skills/harness/SKILL.md` manually

**Time:** 8-12 hours (more manual work, but you learn each step)

---

# FAQ

**Q: Do I need all foundational skills first?**
A: Yes. The harness calls them. If they don't exist, harness fails. Bootstrap builds them if missing. NOTE: `/brainstorm` + `/verify` come from the `superpowers` skill and `/review` comes from `code-reviewer` — if those two bundle skills are installed, those three commands already work and should NOT be rebuilt.

**Q: Can I use existing skills from another project?**
A: Yes — especially the bundle skills. If `superpowers` and `code-reviewer` are already installed, you get /brainstorm, /verify, and /review for free. The standalone skills (piv-plan, piv-implement, wave-analyst, etc.) are mostly project-agnostic, but `/review` (code-reviewer) reads YOUR AGENTS.md for project rules automatically.

**Q: How long does bootstrap actually take?**
A: 4-6 hours if you let an AI agent run it unattended. 10-15 hours if you do it manually and learn each step.

**Q: Can I run bootstrap on an existing project (not brand new)?**
A: Yes. Bootstrap audits first, only builds missing pieces. If you already have AGENTS.md + validation gate, it's faster (~2-3 hours).

**Q: What if validation gate fails in Phase 5 testing?**
A: Fix the gate first (update your linter config, add missing checks). Then re-run harness test. Bootstrap won't pass unless everything is green.

---

# Next Steps After Bootstrap

Once bootstrap completes:

1. **Try a real task:** `/harness "build feature X"`
2. **Iterate:** Run 3-5 harness tasks to build up memory
3. **Optimize:** After 5 tasks, agent becomes 30-40% faster (lessons kick in)
4. **Document:** Add project-specific patterns to AGENTS.md
5. **Scale:** Use `/harness --parallel` for big refactors

---

**Status:** Ready to use  
**Tested in:** Wave-Management-Bot  
**Adaptable to:** Any project with a validation gate  
**Next:** Copy the BOOTSTRAP PROMPT section and run it in your new project
