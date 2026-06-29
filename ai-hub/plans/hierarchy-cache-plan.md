# Hierarchy Cache — Plan

## Context
Role hierarchy data is currently scanned in two separate places:
- `tasks/unified_weekly_loop.py` (`_get_member_role_info`) — runs once a week, writes `top_role`/`role_tier` into `duties.json`
- `tasks/staff_hub_writer.py` (`push_team_hierarchy_to_hub`) — runs on demand via `>refreshteam`

Both scan different guild sets and have diverging TIER_ORDER logic. This caused a bug where a source-guild ticket role named "Support 🤝" matched the `support` keyword and showed on the duties page as if the user had a Support staff role.

## Reason / Purpose
- Single source of truth for role hierarchy across the whole bot
- Scan Staff Hub guild only (clean canonical role names, not source-guild noise)
- Role changes reflect within seconds via `on_member_update` event
- Hourly full scan as safety net
- Kills the need for `>refreshteam` (team_hierarchy.json rebuilds automatically)
- Weekly loop reads from cache — no more stale week-old role data on the duties page

---

## New File: `tasks/hierarchy_cache.py`

### Responsibilities
1. On cog load: run an initial full scan immediately
2. Register `on_member_update` listener for instant per-user updates
3. Run hourly full scan as safety net
4. Write `json_data/role_hierarchy_cache.json` (all staff, keyed by user ID)
5. Write `website/data/team_hierarchy.json` (leadership slice only, replaces `>refreshteam`)

### Guild
Staff Hub only: `1041450125391835186`

---

## TIER_ORDER (single canonical definition, lives in hierarchy_cache.py)

| Tier rank | Tier key     | Role names to match                                                                 | Match strategy       |
|-----------|-------------|--------------------------------------------------------------------------------------|----------------------|
| 0         | `board`     | Fruss, Founder, Owner                                                                | exact name           |
| 1         | `executive` | Executive Director                                                                   | substring            |
| 2         | `head_func` | Head Staff, Head Operations, Head Marketing (incl. "Head Staff \| Management" etc)  | substring            |
| 3         | `sub_head`  | Head Recruiter, Head of Learning & Development, Head Loot Routes, Head Tips & Tricks, Head Surge Routes, Head Logistics, Head Promoting | substring |
| 4         | `mgmt`      | Management                                                                           | exact                |
| 5         | `head_admin`| Head Admin                                                                           | exact                |
| 6         | `sradmin`   | Senior Admin                                                                         | exact                |
| 7         | `admin`     | Admin                                                                                | exact (NOT substring — avoids matching Head Admin / Senior Admin) |
| 8         | `srsup`     | Senior Support                                                                       | exact                |
| 9         | `sup`       | Support                                                                              | exact (NOT substring — avoids matching ticket/bot roles) |
| 10        | `helper`    | Loot Route Maker, Tips & Tricks Helper, Surge Route Maker, Promoters                | exact                |
| 11        | `staff`     | Staff, @Map Request Helper                                                           | exact                |
| 12        | `trial`     | Trial Staff                                                                          | exact                |

**Rule:** iterate roles sorted by Discord position (highest first). First match wins. Exact match = full `rname == keyword`. Substring = `keyword in rname`. Tier 0 board roles use exact name match only.

---

## Cache File: `json_data/role_hierarchy_cache.json`

```json
{
  "_meta": {
    "updated_at": "2026-06-25T14:00:00Z",
    "guild_id": 1041450125391835186,
    "member_count": 87
  },
  "994646489387237407": {
    "name": "godman4786",
    "top_role": "Staff",
    "tier": "staff",
    "tier_rank": 11,
    "avatar_url": "https://cdn.discordapp.com/..."
  }
}
```

---

## Team Hierarchy File: `website/data/team_hierarchy.json`

Same shape as today. Built from the cache by filtering to leadership tiers only (tier_rank 0–5 = board through head_admin). The `_TEAM_ROLE_MAP` slots map to those tiers.

Leadership slots written:
- `founder` — tier 0 (Fruss / Founder / Owner)
- `executive_director` — tier 1
- `head_staff` — tier 2, role name contains "Head Staff"
- `head_operations` — tier 2, role name contains "Head Operations"
- `head_marketing` — tier 2, role name contains "Head Marketing"
- `head_recruiter` — tier 3, role name contains "Head Recruiter"
- `head_ld` — tier 3, role name contains "Learning & Development" or "Head L&D"
- `head_loot_routes` — tier 3, role name contains "Head Loot"
- `head_tips_tricks` — tier 3, role name contains "Head Tips"
- `head_surge_routes` — tier 3, role name contains "Head Surge"
- `head_logistics` — tier 3, role name contains "Head Logistics"
- `head_promoting` — tier 3, role name contains "Head Promot"
- `management` — tier 4
- `head_admin` — tier 5

Each slot is a list of `{name, avatar_url, user_id}` entries (empty list = vacant, shown as N/A on team page).

---

## Changes to Existing Files

### `tasks/unified_weekly_loop.py`
- `_get_member_role_info()` replaced with a cache read:
  ```python
  from tasks.hierarchy_cache import get_cached_role
  top_role, role_tier = get_cached_role(uid)  # returns ('Trial Staff', 'trial') if not found
  ```
- `TIER_ORDER` list inside `unified_weekly_loop.py` deleted (no longer needed)

### `tasks/staff_hub_writer.py`
- `push_team_hierarchy_to_hub()` kept as a thin wrapper that calls the cache task's rebuild function (so `>refreshteam` still works as a manual trigger but just forces a cache rebuild)
- `_TEAM_ROLE_MAP` deleted — team hierarchy is now derived from the cache

### `commands/utilities.py`
- `>refreshteam` command updated to call `hierarchy_cache.force_rebuild()` instead of `push_team_hierarchy_to_hub` directly

---

## Public API (exported from hierarchy_cache.py)

```python
def get_cached_role(uid: int) -> tuple[str, str]:
    """Return (top_role_name, tier_key) for a user. Falls back to ('Trial Staff', 'trial')."""

async def force_rebuild(bot) -> bool:
    """Trigger a full rescan immediately. Called by >refreshteam."""
```

---

## Task Registration

In `main.py` (or wherever cogs load): add `tasks.hierarchy_cache` to the extensions list.

The cog registers:
- `tasks.HierarchyCacheTask` — hourly loop (`hours=1`)
- `on_member_update` listener

---

## What Does NOT Change
- `global_logger.py` top_role logging — left alone for now
- The duties leaderboard HTML page — no changes needed, it reads `duties.json` which will now have fresh data
- The team HTML page — no changes needed, reads `team_hierarchy.json` same as before
- Source guild scanning in the weekly loop for duty stats (messages, reqs, etc.) — unchanged

---

## Validation
Run `python ai-hub/gates/validate.py` before marking done.
