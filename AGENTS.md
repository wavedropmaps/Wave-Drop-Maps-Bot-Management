# Wave-Management-Bot — Agent Context (HQ / master instructions)

> **This is the single source of truth for EVERY AI agent on this project** — Claude Code, Antigravity/Gemini, Cursor, Copilot, and any other. It lives at the repo root as `AGENTS.md` (the cross-agent standard). The root `CLAUDE.md` is a thin 9-line shim that imports this file (Claude Code reads `CLAUDE.md`, not `AGENTS.md`) — **never duplicate rules into it; edit here.**

This file is the lean **router**: always-needed rules + a map. Deep per-system detail lives in `ai-hub/docs/` (see the **Codebase Map** below) — read the relevant doc only when you touch that area. Custom cross-agent skills live in `ai-hub/skills/`.

### Memory layering (per machine)

Claude Code on each machine **merges** memory files, broadest → most specific:
1. **`~/.claude/CLAUDE.md`** — that machine's GLOBAL/personal file (Mac and Windows each have their own; **NOT synced** through git).
2. **`./CLAUDE.md` → `@AGENTS.md`** — THIS shared project brain (synced via git, identical on every machine).
3. **`./CLAUDE.local.md`** — optional per-machine project prefs (gitignored).

**Rule of thumb:** machine-specific things (absolute paths like `C:\Users\kiere\…` vs `~/Downloads/…`, personal shortcuts) belong in that machine's global `~/.claude/CLAUDE.md`. Shared project rules belong **HERE** in `AGENTS.md`.

### Skills & MCP tools — where they live & how each agent finds them

- **Skills** → all live in **`ai-hub/skills/`** (one portable hub; travels with the repo).
- **MCP tools** → defined in **`.mcp.json`** at the repo root (the cross-agent standard — most agents auto-read it; tokens come from the gitignored `.env`).

**Important — there is NO universal skills-discovery standard yet.** Each agent auto-looks for skills only in its *own* default spot, and **none of them auto-check `ai-hub/skills/`.** So if you are an agent and your skills don't appear:
1. They ARE here — read/use them directly from `ai-hub/skills/`.
2. To make them auto-discover (e.g. show in a `/` menu), this repo needs **your agent's native pointer** aimed at `ai-hub/skills/`.

**Existing agent configurations:**
- **Kiro** → `.kiro/skills/` (copied `.md` files from `ai-hub/skills/`)
- **Antigravity** → `.agents/skills.json` (native pointer to `ai-hub/skills/`)
- **Claude Code** → `.claude/commands/` (copied `.md` files)
- **Cursor** → `.cursor/rules/skill-*.mdc` (copied `.mdc` files)
- **Qoder** → `.qoder/skills/{name}/SKILL.md` (copied `SKILL.md` files, directory per skill)

If you're a new agent without one, **set up your native skills pointer to `ai-hub/skills/` (or ask the user to)** — it's a one-time, tiny config file that then travels with the repo.

---

## Project Snapshot

**Wave-Management-Bot** is a Discord bot (discord.py, prefix `>`) that manages staff activity, rewards, and performance metrics across **3 guilds** for a Fortnite drop map community.

- **Source code + Runtime:** Windows machine (`C:\Users\kiere\Desktop\Wave Management Bot`)
- **Deploy flow:** Work directly on Windows, commit and push to `origin/master`
- **Cross-platform rule:** All bot-side code must work on Windows — use `pathlib.Path`, no macOS-only tricks (no `git credential-osxkeychain`, etc.)
- **Database:** SQLite (`bot_database.db`) with 5-connection async pool, WAL mode, 64MB cache
- **Guilds:** Staff Hub `1041450125391835186`, Source guilds `988564962802810961` & `971731167621574666`

---

## Workflow Rules (READ FIRST)

### Validation Gate (ACTIVE ENFORCEMENT)
- **Rule:** Never complete a feature or claim a task is done without first running `python ai-hub/gates/validate.py` and ensuring a 0 exit code. This is a hard requirement.

### Git
- **Master branch only.** No feature branches. Commit and push directly to `origin/master`.
- When working in worktrees: push worktree → `origin/master`, then sync main repo.

### Planning Mode
- If the user signals planning (e.g. "we're still planning", "let me think", "I'll tell you how I want it") **do not write code, create files, or run mkdir**.
- Repo/file creation by the user is **preparation**, not a build signal. Wait for an explicit "build it", "go ahead", or "start coding".

### Infrastructure & Meta-Docs
- **Entry point:** Read `ai-hub/docs/README.md` to understand project infrastructure (scripts, automation, agent coordination, validation gates).
- **How agents learn:** Memory system at `ai-hub/memory/SUPERCOMPUTER.md` persists learnings across sessions.
- **Bot systems:** Deep docs on Strikes, VBucks, Routes, etc. live in `ai-hub/memory/bot-infrastructure/`.

### Cross-Platform Code
- Bot-side code runs on Windows. Use `pathlib.Path` everywhere.
- Mac-only tooling (`push_leaderboard_html.py` uses macOS keychain) should stay Mac-side and never be moved into the bot's runtime path.
- For new bot-side GitHub auth, use a Personal Access Token in env var — not keychain.

### Scope Discipline
- Do only what is explicitly requested. Do not add extra logging, features, or refactors unless asked.
- "Remove-only", "resume-only", "rename-only" means exactly that — no bonus work.
- If the scope seems ambiguous, ask before expanding.

### Repo Structure
- The ACTIVE website code lives in `website/` inside this repo. The old `wave-leaderboard-repo/` is **DEPRECATED** (now archived in `ai-hub/deprecated/`) — never edit HTML/JS there.
- Before making any code edits, run a verification pre-flight: use Bash and Read to confirm which repo and folder is the ACTIVE deployment target (check git remotes, recent commits, and any deploy config) rather than trusting memory. Show verification results before proceeding and flag any mismatch between assumptions and reality.

### Data Accuracy
- Never report member counts, stats, or metrics from web listings or memory — always verify directly from source/script output.
- If a number can't be verified live, say so explicitly rather than estimating.

### Skills Workflow
- When building a skill: use the skill-creator tool and package the `.skill` file to Desktop. Skills are repo-local in `ai-hub/skills/`, not tied to the Claude account.
- Do NOT convert MCP-server tools into static `.skill` files — that loses their live functionality.

---

## Conventions & Gotchas

- **Adding new bot side-effects to DB writes:** follow the pattern — accept optional `bot` arg, trigger via `leaderboard_updater.auto_update_*` and lazy-import to avoid circular deps.
- **Logging:** `logger = logging.getLogger('discord')` in command files; database uses `logging.getLogger(__name__)`. UTC timestamps via `logging.Formatter.converter = time.gmtime`.
- **Rate limit log:** separate `rate_limits.log` file. Bot warns at <3 requests remaining.
- **Sending DMs without going through the queue:** use `_original_user_send` / `_original_member_send` from `main.py` (imported as `import main as _main`). Never call `user.send()` directly if you need an un-intercepted send — the monkey-patch will re-enqueue it.
- **`user.send()` return value:** always `None` after the monkey-patch. Callers must not use the return value.
- **Sticky messages:** delete + repost pattern, lock-guarded to prevent concurrent posts.
- **Role lookup across guilds:** always case-insensitive name match (role IDs differ per server).
- **Don't parse Discord messages for state.** DB is source of truth. Messages are rebuilt from DB.

---

## `ai-hub/` Folder Organisation

All AI-generated scratch, research, docs, summaries, and skill files live under **`ai-hub/`** (the central AI hub, reorganised from the old `claude/` folder on 2026-06-19). Live, code-referenced tooling does NOT go here.

### Sorting rule — where does a new file go? (apply top to bottom, first match wins)

1. **Is it code the bot imports/runs, OR referenced by a path in code?** (a cog, a task, a script a command shells out to, a `data.db` a command reads) → leave it where the code expects it (`commands/`, `tasks/`, `command-trackers/`, etc.). **NEVER move it into `ai-hub/`** — that breaks the path the code uses.
2. **Is it agent/tool config an IDE auto-discovers at a fixed location?** (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.qoder/`, `.mcp.json`, `.agents/`) → repo **root**, never moved.
3. **Otherwise it's AI work product → `ai-hub/`**, filed by type:
   - a reusable skill → `ai-hub/skills/`
   - a plan, spec, or roadmap (forward-looking — what to BUILD/change) → `ai-hub/plans/`
   - general docs or AI architecture models → `ai-hub/docs/`
   - bot systems/infrastructure docs → `ai-hub/memory/bot-infrastructure/`
   - rules/mistakes to avoid → `ai-hub/memory/global-memory/`
   - research / data-gathering output → `ai-hub/research/`
   - a session summary → `ai-hub/memory/session-summaries/`
   - a throwaway experiment → `ai-hub/scratch/`
   - anything retired / superseded / dead-but-kept → `ai-hub/deprecated/`

When in doubt between "live tooling" (rule 1) and "AI work product" (rule 3): if removing the file would break a command or the bot, it's rule 1.

### Folder reference — all 9 directories

Each folder has a README explaining what it contains. Read the README when you need to understand or add something to that area.

- **`ai-hub/skills/`** — cross-agent skill `.md` files (no README; use `/` menu to invoke)
- **`ai-hub/docs/`** — [`README.md`](ai-hub/docs/README.md) — project infrastructure docs, scripts inventory, architecture diagrams
- **`ai-hub/memory/`** — [`SUPERCOMPUTER.md`](ai-hub/memory/SUPERCOMPUTER.md) — unified AI brain, learnings, systems deep-dives
- **`ai-hub/plans/`** — [`README.md`](ai-hub/plans/README.md) — forward-looking plans, specs, roadmaps (what to build/change)
- **`ai-hub/research/`** — [`README.md`](ai-hub/research/README.md) — research artifacts, technical investigations by topic
- **`ai-hub/gates/`** — [`README.md`](ai-hub/gates/README.md) — validation gates, security checks, pre-commit enforcement
- **`ai-hub/scripts/`** — [`README.md`](ai-hub/scripts/README.md) — developer automation (ralph, skill sync, hooks)
- **`ai-hub/deprecated/`** — [`README.md`](ai-hub/deprecated/README.md) — the attic: retired code, dead website repo, historical reference
- **`ai-hub/scratch/`** — [`README.md`](ai-hub/scratch/README.md) — throwaway experiments, one-off debugging
- **NOT in the hub:** the live, Discord-command-invoked trackers live in a **top-level `command-trackers/`** folder (code-referenced bot tooling, not scratch/research).

---

## `command-trackers/` Folder

Top-level folder (sibling of `ai-hub/`) holding the **live, Discord-command-invoked data trackers** (`drop-map-research/`, `guild-stats/`, `market-research/`). Each has its own `scripts/`, `data/data.db` (tracked in git), `data/reports/`, and `SKILL.md`. Kept at root (NOT in `ai-hub/`) because it's code-referenced — the `commands/*.py` cogs shell out to these scripts. Full detail: `ai-hub/docs/command-trackers.md`.

---

*Last updated: 2026-06-21. Restructured into a lean router (~140 lines) — deep per-system detail moved to `ai-hub/docs/*.md`, linked in the Codebase Map. When a system's code changes significantly, update its doc in `ai-hub/docs/`. (Promoted from `CLAUDE.md` to root `AGENTS.md` 2026-06-19.)*
