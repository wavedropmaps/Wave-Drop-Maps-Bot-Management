---
name: repo-sync
description: >
  Safely sync this whole repo (ANY code — bot, website, tasks, configs) between the
  Windows runtime machine and the Mac (or origin) — pulling changes IN and committing
  + pushing changes OUT without breaking the live bot, database, or site. Use whenever
  the user says "smart push", "sync the repo", "pull the changes", "pull the Mac
  changes", "merge and push", "push the website/bot", or otherwise wants to reconcile
  this repo with GitHub. Encodes the hard-won rules: always back up first, NEVER
  overwrite the live bot_database.db, handle the running bot/Flask file locks, pick the
  right merge strategy, and restart the backend only when its code changed. The website
  is just the *easy* case — the dangerous parts (live DB, running processes, force-push
  while behind) apply to ALL changes, not only website ones.
---

# Repo Sync Skill (whole codebase, not just the website)

The deterministic mechanics live in `ai-hub/scripts/wave_sync.py`. This skill is
the **playbook** — the judgment around those tools. Always start with `status`.

```
python ai-hub/scripts/wave_sync.py status   # read-only assessment, run FIRST
python ai-hub/scripts/wave_sync.py backup    # timestamped backup branch
python ai-hub/scripts/wave_sync.py push      # commit + push + verify 0 0 (refuses if behind)
```

## The non-negotiable rules (these all came from real incidents)

1. **Back up before anything destructive.** A `backup-*` branch at HEAD. `push`
   does this automatically; before a pull/merge, run `backup` yourself.
2. **NEVER overwrite the live `bot_database.db`.** The Mac commits a *stale*
   snapshot of it; the running Windows bot holds the authoritative live DB.
   Replacing it rolls back points/vbucks and can corrupt WAL state.
3. **Schema is built by code, not by the .db file.** Keeping the live DB is
   correct — the bot runs `CREATE TABLE IF NOT EXISTS` + migrations on startup,
   so new features' tables appear automatically. Copying the Mac's DB gains
   nothing and loses live data.
4. **Runtime churn ≠ real work.** `bot_database.db`, `*.log`, `wave_logging_local/`,
   `website/data/*.json`, `json_data/`, `_worker.js` (tunnel URL), `.wrangler/` are
   machine-written. `status` separates these from real code/website edits.
5. **Restart the backend only if its code changed.** `web_api.py` change → run
   `restart_staff_hub.ps1` (Flask). `tasks/*.py` / `commands/*.py` / `database.py`
   change → restart the bot (`python main.py`). Static `website/*` is served live
   from disk — no restart, just a browser hard-refresh.

## PUSH OUT (local → origin)

1. `wave_sync.py status`. If it says **behind/diverged → do the PULL playbook first.**
2. If only ahead / local changes: `wave_sync.py push` (or `push -m "message"`).
   It backs up, commits real + churn, pushes, and prints `behind=0 ahead=0`.
3. If real code/website changed AND it affects the running services, restart per
   rule 5. Remind the user to hard-refresh the browser.

## PULL IN (origin/Mac → local) — the careful path

1. `wave_sync.py status` and `wave_sync.py backup`.
2. **Decide whose website wins** from the user's intent:
   - "my local site is perfect / keep mine" → resolve website paths as **ours**.
   - "pull the Mac's new design" → merge `-X theirs`.
3. Commit local runtime churn so the tree is clean enough to merge.
4. **If the merge will touch `bot_database.db` and the bot is running, it WILL
   fail on the file lock.** Then, and only then:
   a. Stop bot + Flask + supervisor (release locks).
   b. `git commit` the final live DB so HEAD has it (call it OURLIVE).
   c. `git merge -X theirs --no-edit origin/master`.
   d. `git checkout OURLIVE -- bot_database.db` to **restore the live DB**.
   e. Resolve any other conflicts (e.g. honor origin un-tracking a `*.log` with
      `git rm --cached`), finalize the merge commit.
   f. Restart bot, then `restart_staff_hub.ps1`. Verify 5001 + `/ping`.
5. **Verify**: website code identical to the intended source
   (`git diff --stat origin/master HEAD -- website` — only `data/*.json` should
   differ), no stray conflict markers, bot startup log clean (tables initialized,
   no malformed/no-such-column), `behind=0 ahead=0`.
6. Tell the user to hard-refresh; the change is per-page in the browser cache.

## The pre-push safety hook (recommended, both machines)

A git `pre-push` hook acts as an automatic **safety gate** on every `git push`.
The hook lives in the repo at `ai-hub/scripts/hooks/pre-push` (tracked, so both
machines get it on pull). Install it once per machine:

```
python ai-hub/scripts/wave_sync.py install-hook
```

Behaviour:
- **In sync / ahead** → push passes through silently (normal push).
- **Behind origin** → push is **BLOCKED** with a message telling you to run this
  skill ("pull the Mac changes") instead of force-pushing. In a terminal it
  offers an interactive `[y/N]` override; a non-interactive (agent/CI) push is
  blocked outright.

The hook is ONLY a guard — it never merges, never touches the DB, never stops a
process. The judgment work always stays here in the skill. This is the right
split: automatic gate to catch danger, human-triggered skill to handle it.

### Per-machine note
- **Windows** (runtime box): the dangerous case is pulling the Mac's stale DB
  over the live one — handled by the PULL playbook above.
- **Mac** (website dev box): no bot/DB, so the only real risk is "push while
  behind" → the hook catches it; then pull/merge, push.

## Gotchas seen in the wild
- `skip-worktree` is **not** honored by `git merge` when the file is actively
  changing — don't rely on it to protect the live DB. Stop the process instead.
- Browser/edge cache makes "nothing changed!" look real when the server is fine —
  always confirm server-side first (curl Flask), then blame the browser.
- `bot_database.db` > 50 MB triggers a GitHub *warning*, not a failure (intentional
  full-sync). Git LFS only if it ever starts rejecting.
