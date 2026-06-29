# Kiro Configuration

This folder contains Kiro-specific configuration for the Wave Management Bot project.

## Skills

Skills are synchronized from the canonical source at `ai-hub/skills/` to enable native `/` command discovery in Kiro.

### Setup

- **Source of truth:** `ai-hub/skills/` (each skill lives in its own subfolder as `SKILL.md`)
- **Kiro copy:** `.kiro/skills/` (flat `.md` files for native discovery)
- **Config pointer:** `.kiro/skills.json` (points to `ai-hub/skills/` for reference)

### Syncing Skills

When you add or update a skill in `ai-hub/skills/<name>/SKILL.md`, sync it to Kiro:

```powershell
# Copy all skills from ai-hub to .kiro/skills
Get-ChildItem ai-hub\skills -Directory | ForEach-Object {
    $skillName = $_.Name
    Copy-Item "ai-hub\skills\$skillName\SKILL.md" ".kiro\skills\$skillName.md"
}
```

Or for a single skill:
```powershell
Copy-Item "ai-hub\skills\checkpoint\SKILL.md" ".kiro\skills\checkpoint.md"
```

### Available Skills

All 25 skills from `ai-hub/skills/` are now available as `/` commands in Kiro:

- `/checkpoint` - Save progress to survive session interruptions
- `/resume` - Resume from last checkpoint
- `/wave-analyst` - Rigorous analysis framework for decisions
- `/session-summary` - End-of-session summary
- `/session-handoff` - Structured handoff before clearing context
- `/update-memory` - Save lessons to persistent memory
- `/consolidate-memory` - Merge/clean memory files
- `/gsd` - Get Shit Done structured dev framework
- `/superpowers` - Agentic dev with brainstorm/debug/TDD/build/verify
- `/code-sparring` - Aggressive devil's-advocate code review
- `/frontend-design` - UI/UX specialist for React/Vue/HTML/CSS
- `/prompt-engineering-deep-dive` - Deep questioning for prompts (append "95")
- `/skill-creator` - Create/modify skills, run evals
- `/agent-reach` - Research/search/lookup via web
- `/setup-cowork` - Guided cowork setup
- `/schedule` - Create scheduled tasks
- `/likec4` - Software architecture diagrams (C4 models)
- `/pdf` - PDF operations (read/extract/merge/split/OCR)
- `/docx` - Word document operations
- `/pptx` - PowerPoint operations
- `/xlsx` - Spreadsheet operations
- `/piv-plan` - PIV planning skill
- `/piv-implement` - PIV implementation skill
- `/code-reviewer` - Code review skill
- `/split-and-verify` - Split and verify skill

## Cross-Agent Compatibility

This project supports multiple AI IDEs with a unified skills architecture:

| Agent | Skills Location | Discovery Method |
|-------|----------------|------------------|
| **Kiro** | `.kiro/skills/` | Native (copied `.md` files) |
| **Antigravity** | `.agents/skills.json` | Native pointer to `ai-hub/skills/` |
| **Claude Code** | `.claude/commands/` | Native (copied `.md` files) |
| **Cursor** | `.cursor/rules/skill-*.mdc` | Native (copied `.mdc` files) |

All agents share the same canonical source: `ai-hub/skills/`
