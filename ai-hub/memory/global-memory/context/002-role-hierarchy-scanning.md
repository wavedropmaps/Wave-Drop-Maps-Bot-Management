# Context: Role Hierarchy Scanning Pitfalls

## The Symptom
A staff member (godman4786) appeared on the duties leaderboard page with the role "Support 🤝" — a role that doesn't exist in the staff hierarchy. The user reported it as a "wrong role hierarchy mix up."

## The Root Cause
Three compounding issues in the old `_get_member_role_info` function in `unified_weekly_loop.py`:

1. **Wrong guild scope.** The function scanned the two *source guilds* (the public Fortnite drop-map Discord servers) instead of the Staff Hub guild. Those source guilds contain non-staff roles like "Support 🤝" (a ticket-bot role) that happen to contain the keyword "support".

2. **Substring matching on short, ambiguous keywords.** The old TIER_ORDER used `any(kw in rname for kw in keywords)` for every tier. The keyword `'support'` matched "Support 🤝" because the string "support" appears in it. Similarly, `'admin'` as a substring would match "Head Admin" or "Senior Admin" before those tiers were checked — making tier ordering fragile.

3. **Stale data.** The scan only ran once per week (weekly loop), so a removed role could show for up to 7 days.

## The Lesson Learned

**Rule 1 — Scope role scans to the canonical guild only.**
Always scan the Staff Hub guild (`1041450125391835186`) for role hierarchy. Never derive staff roles from source/public guilds — they contain bot/ticket/vanity roles with colliding names.

**Rule 2 — Use exact matching for short or ambiguous tier keywords.**
Any tier whose keyword is a substring of a higher tier's role name MUST use exact matching (`role.name.lower() == keyword`), not substring (`keyword in role.name`). Affected tiers: `admin`, `support`, `staff`, `management`. Use substring only for long, unique prefixes like "Executive Director", "Head Operations", etc.

**Rule 3 — Two-layer cache pattern for role freshness.**
For any role-derived data shown on the website: use `on_member_update` to patch the single changed user instantly, plus an hourly full rescan as a safety net. Never rely solely on a weekly scan for data that can change any time a role is added/removed.

## The Fix
New `tasks/hierarchy_cache.py`:
- Scans Staff Hub only
- 13-tier `TIER_ORDER` with `'exact'` vs `'substring'` per tier
- `on_member_update` listener for instant single-user patches
- Hourly full scan loop as safety net
- `get_cached_role(uid)` public API consumed by weekly loop and any future system
- Rebuilds `team_hierarchy.json` automatically (killed the need for `>refreshteam`)
