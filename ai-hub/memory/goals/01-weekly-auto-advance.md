---
title: Weekly auto-advance + duplicate-fire fix
status: backlog            # backlog | in-progress | review | done
created: 2026-06-22
scope: tasks/weekly_checks.py, tasks/weekly_roles.py, tasks/periodic_week_rollover.py
note: User clarified this goal is background context only. The actual work requested was admin panel Set Away button + status section (✅ DONE, commit a9b213fb).
---

## Objective

Stop the weekly cycle from getting stuck on stale dates and stop the weekly
roles report from firing twice. Root cause: `config.json` was never advanced to
the next week, so on restart the bot saw the same dates and re-ran / looped.

## Acceptance criteria

- [ ] Fast path: after the full-week report completes, dates immediately
      advance to the next week.
- [ ] Safety net: `periodic_week_rollover.py` (every 37h) detects a passed
      `end_date` and auto-advances even if `weekly_checks` didn't run.
- [ ] `weekly_roles` no longer double-fires on bot restart for an
      already-sent week.
- [ ] `config.json` global dates update correctly on advance.
- [ ] Verified on the bot (Windows) before commit.
- [ ] Committed + pushed to origin/master.

## Notes

- New cog: `tasks/periodic_week_rollover.py` — independent safety loop.
- Background to the design: see
  `ai-hub/memory/bot-infrastructure/weekly-auto-advance-system.md` and
  `weekly-roles-duplicate-fire-fix.md`.
- Currently in the working tree only (uncommitted) — hence status `review`,
  not `done`. Flip to `done` via /codify once verified + pushed.
