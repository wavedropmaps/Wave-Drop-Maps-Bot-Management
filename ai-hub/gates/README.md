# ✓ Gates — Validation & Enforcement

Pre-commit checks that must pass before shipping code. Enforcement gates prevent broken or unsafe code from being committed.

## Contents

### `validate.py` (58 lines)
Main validation gate (cross-platform). **Must pass before claiming any work is done.**

Runs three checks in sequence:
1. **Security check** — prevent `.env`, `config.json`, `credentials.json` from being committed
2. **Lint check** — ruff linting on `commands/`, `core/`, `tasks/` (ignores acceptable legacy style nits)
3. **Skill sync** — syncs `ai-hub/skills/` to `.claude/`, `.cursor/`, `.qoder/`, etc.

**How to run:**
```bash
python ai-hub/gates/validate.py
```

**Use this version on Windows.** Must exit with code `0`. If it fails, fix the issue and run again.

### `validate.sh` (23 lines)
Bash version of the validation gate (macOS/Linux only).

Same checks as `validate.py` but in shell script form. **Use this on Mac/Linux if you prefer bash.**

**How to run:**
```bash
bash ai-hub/gates/validate.sh
```

### `security_check.py` (17 lines)
Prevents accidental commits of secrets. Checks for:
- `.env` — environment variables (tokens, API keys)
- `config.json` — configuration with credentials
- `credentials.json` — explicit credentials file

If any are modified (staged or unstaged), exits with code 1 and blocks the commit.

---

## When to Run

**Before you say work is done:** Always run `validate.py`. It's a hard requirement in AGENTS.md.

---

*Referenced from AGENTS.md → Validation Gate (ACTIVE ENFORCEMENT). Run before every commit.*
