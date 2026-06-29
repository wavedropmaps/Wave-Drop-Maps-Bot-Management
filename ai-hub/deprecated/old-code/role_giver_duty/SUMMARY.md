# Role Giver Duty — Archived Code

**Removed:** 2026-06-17

## What it did

Tracked how many times each "Role Giver" staff member assigned a Discord role during the week, by scanning the `member_role_update` audit log entries across the two source guilds (`988564962802810961`, `971731167621574666`).

Every 4 hours the duty scan ran and updated counts. At the end of each full week (168h) staff were ranked and awarded VBucks:
- 1st: 500 VBucks  
- 2nd: 300 VBucks  
- 3rd: 200 VBucks  

Bad performance (<24 roles/week) resulted in a 200 VBucks penalty. A 3-week consecutive "Great" streak earned a 1.5× multiplier on the award.

The "Role Givers" tab appeared on `duties_leaderboard.html`.

## Why it was removed

Owner decision — the Role Giver duty tracking is no longer needed.

## Files archived here

| File | Source |
|------|--------|
| `duties_scan.py` | `tasks/duties_scan.py` — contains the role scan logic (`scan_roles_for_member`, `scan_roles`) |
| `weekly_checks.py` | `tasks/weekly_checks.py` — contains reports, VBucks awards, penalties for the role duty |
| `duties_leaderboard.html` | `website/duties_leaderboard.html` — includes the Role Givers tab |
| `duties_totals.json` | `json_data/duties_totals.json` — snapshot of data at time of removal |

## What was NOT removed

- The `role` VBucks wallet in `database.py` — existing balances were preserved
- Historical `activity_streaks` data for `duty_type='role'`
- `commands/vbucks_system.py` — `>vbucks role` still shows existing balances
