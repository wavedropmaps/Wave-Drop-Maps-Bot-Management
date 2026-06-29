# AI Tooling Portability Reorg

**Date:** 2026-06-20  
**Topic:** Reorganized all AI files into a portable structure so the project works in any agent/machine, mapped the full Claude setup (skills, MCPs, memory), and audited secrets.

---

## What we built / discussed

- **Cleaned up stray AI files:** deleted an orphaned `~/Downloads/.claude/` (a session once ran from Downloads), removed 2 dead Cloudflare worker backups + a 29 MB `.tmp_screenshot/` scratch project + `.ruff_cache`.
- **`AGENTS.md` is now the master.** Moved the whole `CLAUDE.md` brain → root `AGENTS.md` (the cross-agent standard). `CLAUDE.md` is now a 9-line `@AGENTS.md` import shim. Deleted the duplicate `.agents/AGENTS.md` (one AGENTS.md only). Added a memory-layering note + a "where does a new file go?" sorting rule to AGENTS.md.
- **Built `ai-hub/`** — the central hub for AI work product: `skills/ research/ docs/ summaries/ scratch/ deprecated/`. Moved the old `claude/` content + top-level `docs/` in. Killed the confusing `claude/` (no-dot) folder entirely.
- **`command-trackers/` stays top-level** (NOT in the hub) — it's live, code-referenced tooling (`>rdropmap`/`>guilddash`/`>market`); moving it would break the scripts' `.env` path-walks.
- **Skills made portable:** copied all 18 personal skills from the Claude app into `ai-hub/skills/`, and **created a new `likec4` skill** (architecture-as-code, validated via skill-creator). 19 total, all travel with the repo.
- **MCPs:** made `github` global (user scope, all projects on this Mac); added a project `.mcp.json` (github + context-mode) with the token wired to gitignored `.env`.
- **Memory mapped:** discovered the "18 memory files" + `~/.claude-mem/` are BOTH claude-mem (proved via code path + session-id link) — one plugin, two halves. Wrote a global `~/.claude/CLAUDE.md` signpost pointing memory → claude-mem.
- **gitignore hardened:** `.DS_Store`, stray `database.db`, tool caches, `*.err.log`.
- **Committed + pushed** everything (commit `41e1acb`, 224 files).

## Key decisions

- **Root config files must stay at root** (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json`) — agents hardcode those discovery paths; only *content* goes in `ai-hub/`. ("Addresses vs contents.")
- **Keep `CLAUDE.md` shim, don't delete it** — Claude Code reads `CLAUDE.md`, NOT `AGENTS.md` (confirmed in official docs); deleting it would blind Claude. It carries zero rules, so "one source of truth" still holds.
- **Migration DBs (`pre_wallet_merge_*.db`) stay tracked** — user wants them as offsite PC-failure insurance (only auto `backup_*` dumps are ignored).
- **Secrets to be secured ON WINDOWS, not Mac** — avoids the "pull deletes the file" footgun since the bot's files live on Windows. Repo being made permanently Private.

## Files changed

- `AGENTS.md` (was `CLAUDE.md`) — promoted to master; added layering + sorting-rule + ai-hub/command-trackers sections
- `CLAUDE.md` — new 9-line `@AGENTS.md` shim
- `.mcp.json` (new) — github + context-mode, token via `${GITHUB_TOKEN}`
- `.gitignore` — caches, `.DS_Store`, `*.err.log`, stray db
- `commands/{drop_map_research,guild_stats,market_research}_commands.py`, `commands/utilities.py`, `tasks/staff_hub_writer.py` — updated `claude/` → `command-trackers/` / `ai-hub/` paths
- `ai-hub/**` — entire hub created (19 skills, docs, deprecated bin)

## Things to remember

- **The 18 "Claude memory" files are claude-mem's output**, written into `~/.claude/projects/<project>/memory/`. They do NOT travel (per-machine). claude-mem's DB engine lives in `~/.claude-mem/`.
- **`.env` is the secure file** — gitignored; the bot reads it, secrets never enter git. Each machine needs its own `.env` + `credentials.json` (not synced).
- **Secret audit (still committed, to fix on Windows):** `config.json` → `github.token` + `roboflow.api_key`; `credentials.json` → a full Google service-account private key. A Windows securing prompt was handed off; rotation recommended as the bulletproof fix.
- **Personal skills live in an EPHEMERAL app folder** (`~/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin/<uuid>/<uuid>/skills/`) — UUID path changes every session, so the `ai-hub/skills/` copies are the only reliable home.
- `likec4` skill packaged to `~/Desktop/likec4.skill` for installing in the Claude app.
