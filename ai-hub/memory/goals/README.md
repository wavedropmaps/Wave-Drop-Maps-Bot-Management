# Goals

Lightweight work-tracking. One file per goal. The `SessionStart` hook reads the
`status:` field of every goal here and shows a summary at the start of each
session, so any agent (Claude, Copilot, …) starts oriented on what's in flight.

## How it works

- **Start a goal:** copy `_TEMPLATE.md` to `NN-short-name.md`, fill it in, set
  `status: in-progress`.
- **Advance / close it:** run `/codify` (or just tell the agent) — it flips the
  `status:` field and logs any decision to `../decisions.log`.
- **Statuses:** `backlog` → `in-progress` → `review` → `done`.

`done` goals can stay for history or be deleted — they no longer show in the
session summary (the hook only surfaces `in-progress` and `review`).

## File format

Frontmatter drives the automation — keep `status:` and `title:` accurate; the
body is free-form.
