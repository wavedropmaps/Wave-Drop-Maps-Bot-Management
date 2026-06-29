"""SessionStart hook: print a one-glance summary of open goals.

Reads every ai-hub/memory/goals/*.md file, parses its frontmatter `status:`
and `title:`, and prints the in-progress / review goals so any agent starts
the session oriented. Pure stdlib, cross-platform (pathlib), and never raises
— a hook must not break the session, so all failures degrade to silence.
"""
from pathlib import Path

GOALS_DIR = Path(__file__).resolve().parent.parent / "memory" / "goals"
SURFACE = ("in-progress", "review")  # statuses worth showing at session start


def _frontmatter(text):
    """Return {key: value} from a leading --- ... --- YAML-ish block."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            out[key.strip()] = val.split("#", 1)[0].strip()
    return out


def main():
    if not GOALS_DIR.is_dir():
        return
    rows = []
    for path in sorted(GOALS_DIR.glob("*.md")):
        if path.name in ("README.md", "_TEMPLATE.md"):
            continue
        fm = _frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
        status = (fm.get("status") or "").lower()
        if status in SURFACE:
            rows.append((status, fm.get("title") or path.stem, path.name))

    if not rows:
        return  # nothing in flight — stay quiet
    rows.sort(key=lambda r: (r[0] != "review", r[1]))  # review first
    print("Open goals (ai-hub/memory/goals/):")
    for status, title, fname in rows:
        print(f"  [{status}] {title}  ->  {fname}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never break the session
