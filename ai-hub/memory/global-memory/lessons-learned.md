# Global Memory: Lessons Learned & Rules

This file is part of the agent's **Procedural Memory**. It contains historical context, project-specific rules, and lessons learned from past mistakes. 

> **Agent Instruction:** Before starting complex tasks, check this file to ensure you don't repeat past mistakes. If you make a mistake or solve a tricky problem, append the lesson learned here so future agents benefit.

## General Rules
- Always use `pathlib.Path` for file operations to ensure cross-platform compatibility (Windows bot runtime vs Mac dev).
- **ALWAYS write plans to `ai-hub/plans/` — never leave a plan only in chat.** When the user asks for "a plan" (or you're in planning mode), the deliverable is a `*-plan.md` file in `ai-hub/plans/` (per the `AGENTS.md` sorting rule: forward-looking = what to build/change). Presenting it in chat is fine *in addition*, but the file must exist.
- **Every plan must contain these sections, in this order:** **CONTEXT** (background + current state, verified not assumed) → **RULES** (constraints/gates/scope it must respect) → **IDEAS & THEORIES** (why this shape, alternatives considered/rejected) → then the concrete steps + any open decisions. A plan that's just a step list is incomplete.

## Bot Infrastructure Lessons
- **[Role Hierarchy Scanning — Scope + Match Mode](context/002-role-hierarchy-scanning.md):** Always scan Staff Hub guild only for role hierarchy (source guilds have noise roles). Use exact matching for short tier keywords (admin, support, staff) — substring matching causes collisions with ticket/bot roles and higher-tier role names. Use a two-layer cache: `on_member_update` for instant patches + hourly full rescan as safety net.
- **[Vanity Roles Are Not Tiers](context/003-vanity-roles-not-tiers.md):** Never add a role to TIER_ORDER or _TEAM_SLOTS based on its name alone — verify it is an actual organisational tier. Roles named after individuals (e.g. "Fruss") are vanity/personal roles, NOT hierarchy tiers. When unsure, ask the user before adding.

## Discord.py Gotchas
- Never use `user.send()`'s return value because it's monkey-patched to return `None` when going through our DM queue system. Use `_original_user_send` if an immediate unqueued DM is required.

## Architecture & Documentation
- **[Model Concepts, Not Configs](context/001-frozen-server.md):** When generating architecture diagrams (like C4 models), do not map out every literal, low-level config file (e.g., `skills.json`, `CLAUDE.md`) as separate boxes unless explicitly asked. Humans think conceptually. Model the high-level flow (e.g., "The `.agents/` folder redirects to the `AGENTS.md` HQ"). Read the linked context for the full history.
- **[Frozen Dev Servers](context/001-frozen-server.md):** If you are running a dev server in the background (like `npx likec4 start` or Vite) and the user reports that their browser isn't updating after you made file changes, the server's file watcher has frozen. Do not argue with the user or assume they are wrong. Use the `manage_task` tool to kill the stuck task and restart it. Read the linked context for the full history.
