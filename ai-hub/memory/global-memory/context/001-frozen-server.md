# Context: Frozen LikeC4 Dev Servers

**Date:** 2026-06-20
**Topic:** Generating Architecture Diagrams (LikeC4 / Mermaid)

## The Symptom
The AI agent was using the `likec4` skill to generate an architecture diagram. The AI edited the `.c4` file successfully, but the user complained that the browser tab (which was supposed to hot-reload) was not updating and remained "messy." The user felt the AI was ignoring instructions.

## The Root Cause
1. **Technical Failure:** The background dev server (`npx likec4 start`) froze and its file watcher silently crashed. Even though the AI was editing the files correctly, the HMR (Hot Module Replacement) stopped pushing updates to the browser.
2. **Conceptual Failure:** The AI modeled the architecture too literally. It drew separate boxes for every single internal configuration file (like `skills.json` and `.mcp.json`) instead of focusing on the high-level human conceptual flow (e.g., "The `.agents/` folder redirects to the `AGENTS.md` HQ").

## The Lesson Learned
1. **Model Conceptually, Not Literally:** When drawing diagrams, map the high-level flow that makes sense to a human. Do not map literal internal shim configs unless explicitly requested.
2. **Assume the Server Froze:** If you are running a background dev server and the user says the UI isn't updating, do not assume they are wrong. Use the task manager to `kill` the background process and restart it.
