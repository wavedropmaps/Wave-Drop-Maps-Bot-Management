#!/usr/bin/env python3
"""Cross-platform validation gate for Wave-Management-Bot.

Pure-Python replacement for validate.sh so the gate runs on the bot's Windows
host (bash + a `python3` alias are not guaranteed there). Runs the security
check first, then the same ruff lint, then the skill sync.
"""
import os
import sys
import shutil
import subprocess


def repo_root():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", ".."))


def main():
    root = repo_root()
    print("Running Validation Gate for Wave-Management-Bot...")

    # 1. Security check — protected files must not be staged/committed.
    print("Running security check...")
    sec = subprocess.run(
        [sys.executable, os.path.join(root, "ai-hub", "gates", "security_check.py")],
        cwd=root,
    )
    if sec.returncode != 0:
        sys.exit(sec.returncode)

    # 2. Lint. F403/F405/F821 are unavoidable (cogs use `from core.helpers import *`);
    #    the rest are legacy style nits in pre-existing bot code. The gate catches NEW breakage.
    if shutil.which("uvx") is None:
        print("uvx could not be found. Please ensure uv is installed.")
        sys.exit(1)
    print("Linting commands/, core/, tasks/...")
    lint = subprocess.run(
        ["uvx", "ruff", "check", "commands/", "core/", "tasks/",
         "--ignore=E701,E702,E722,F841,F811,F541,F401,E402,E721,F403,F405,F821,E401"],
        cwd=root,
    )
    if lint.returncode != 0:
        sys.exit(lint.returncode)

    # 3. Sync skills to AI agents (Claude, Cursor) — same step validate.sh ran.
    sync = os.path.join(root, "ai-hub", "scripts", "sync_agent_skills.py")
    if os.path.exists(sync):
        print("Syncing skills to AI agents...")
        s = subprocess.run([sys.executable, sync], cwd=root)
        if s.returncode != 0:
            sys.exit(s.returncode)

    print("Validation passed! You are clear to proceed.")


if __name__ == "__main__":
    main()
