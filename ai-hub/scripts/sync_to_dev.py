"""
sync_to_dev.py — Sync between private and public dev repo.

Usage:
    python ai-hub/scripts/sync_to_dev.py          # push your changes → dev repo
    python ai-hub/scripts/sync_to_dev.py --pull   # pull dev changes → your main folder

The script respects the dev repo's .gitignore — secrets, DBs, logs never cross over.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PRIVATE_DIR = Path(r"C:\Users\kiere\Desktop\Wave Management Bot")
DEV_DIR     = Path(r"C:\Users\kiere\Desktop\Wave Management Bot Dev")

# Files/folders that never go into the dev repo
EXCLUDE = {
    ".env",
    "credentials.json",
    ".git",
    ".headroom",
    "__pycache__",
    "node_modules",
    "database_backups",
    "wave_logging_local",
    "logs",
    ".ruff_cache",
    ".wrangler",
    ".tmp_screenshot",
    ".DS_Store",
}

EXCLUDE_EXTENSIONS = {".db", ".db-wal", ".db-shm", ".pyc"}


def is_excluded(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE:
            return True
    if path.suffix in EXCLUDE_EXTENSIONS:
        return True
    return False


def sync_push():
    """Copy safe files from private → dev folder, then commit and push."""
    print("Syncing private → dev repo...")

    # Copy files from private to dev (skipping excluded)
    for src in PRIVATE_DIR.rglob("*"):
        rel = src.relative_to(PRIVATE_DIR)
        if is_excluded(rel):
            continue
        dst = DEV_DIR / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # Remove files in dev that no longer exist in private (and aren't excluded)
    for dst in DEV_DIR.rglob("*"):
        rel = dst.relative_to(DEV_DIR)
        if is_excluded(rel):
            continue
        src = PRIVATE_DIR / rel
        if not src.exists() and dst.is_file():
            print(f"  Removing deleted file: {rel}")
            dst.unlink()

    # Git commit and push
    result = subprocess.run(
        ["git", "add", "-A"],
        cwd=DEV_DIR, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"git add failed: {result.stderr}")
        sys.exit(1)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=DEV_DIR
    )
    if result.returncode == 0:
        print("Nothing changed — dev repo is already up to date.")
        return

    subprocess.run(
        ["git", "commit", "-m", "chore: sync from private repo"],
        cwd=DEV_DIR, check=True
    )
    subprocess.run(
        ["git", "push", "origin", "master"],
        cwd=DEV_DIR, check=True
    )
    print("Done. Dev repo updated.")


def sync_pull():
    """Pull latest from dev repo and copy changed source files → private folder."""
    print("Pulling dev repo changes → private folder...")

    # Pull latest from dev remote
    subprocess.run(
        ["git", "pull", "origin", "master"],
        cwd=DEV_DIR, check=True
    )

    # Copy files from dev to private (skipping excluded)
    for src in DEV_DIR.rglob("*"):
        rel = src.relative_to(DEV_DIR)
        if is_excluded(rel):
            continue
        dst = PRIVATE_DIR / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    print("Done. Changes copied to your private folder.")
    print("Review the changes, test the bot, then commit to your private repo when ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull", action="store_true", help="Pull dev changes into private folder")
    args = parser.parse_args()

    if args.pull:
        sync_pull()
    else:
        sync_push()
