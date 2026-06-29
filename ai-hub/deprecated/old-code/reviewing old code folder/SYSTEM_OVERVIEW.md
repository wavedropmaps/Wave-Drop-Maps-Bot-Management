# Drop Map Reviewing — How It Works

**Purpose:** Staff members review Fortnite drop map submissions. They check marker placements for accuracy, earn points based on speed and correctness, climb tiers, and redeem points for real rewards (AUD payouts, VBucks, roles).

---

## Session Flow

1. Admin runs `>newday` to open a session (creates a `daily_sessions` record, picks challenges, picks bonus map).
2. Reviewers claim maps via `>claim [map_id]` — first-come, fastest base points.
3. Reviewer checks markers, submits via `>submit [map_id] [correct] [total] [link]`.
4. Bot calculates points: `base_pts × marker_count × tier_multiplier × bonus_multiplier`.
5. Points are written to `reviewers` table, accuracy recalculated, tier updated.
6. Accuracy streak and daily streak are updated. Milestones trigger bonus awards.
7. At day end, admin runs `>endday` to close the session and post the daily summary.

---

## Tier System (based on last 30 markers)

| Tier | Accuracy | Multiplier |
|------|----------|------------|
| Master | ≥ 96.67% | 4× |
| Expert | ≥ 90% | 3× |
| Advanced | ≥ 83.33% | 2× |
| Intermediate | ≥ 76.67% | 1.5× |
| Beginner | < 76.67% | 1× |

Tier is recalculated on every submission from the sliding window of last 30 real markers (ghost markers are used to seed new reviewers).

---

## Base Points by Claim Speed

| Claim window | Base pts |
|-------------|----------|
| ≤ 1 min | 4 |
| ≤ 5 min | 3 |
| ≤ 30 min | 2 |
| ≤ 60 min | 1.5 |
| > 60 min | 1 |

---

## Point Formula

```
final_points = round(base_pts × marker_count × tier_multiplier)
if bonus_map: final_points × 2
```

Bonus map (daily lottery): one random map per session is flagged `is_daily_bonus_map`. First reviewer to complete it gets 2× multiplier.

---

## Accuracy Streak System

- Tracks consecutive perfectly-correct marker submissions (0 mistakes on a map).
- **Resets to 0 on any mistake** (wrong marker placement).
- Milestones trigger bonus points (one-time per streak, resets on streak break):

| Streak | Bonus |
|--------|-------|
| 5 | +10 pts |
| 9 | +100 pts |
| 19 | +300 pts |
| 37 | +750 pts |
| 50 | +2,000 pts |
| 1,000 | +8,000 pts (Legendary) |

---

## Daily Streak System

- Tracks consecutive days with at least 1 verified submission.
- Skipping a day resets it.
- Sessions where 0 markers are correct do NOT count.
- Milestones:

| Days | Bonus |
|------|-------|
| 2 | +10 pts |
| 5 | +100 pts |
| 14 | +300 pts |
| 30 | +750 pts |
| 180 | +8,000 pts |
| 365 | +20,000 pts |

---

## Penalty Types

| Type | Deduction |
|------|-----------|
| `marker_mistake` | -20 pts |
| `skipped_oldest` | -20 pts + lose base pts for that map |
| `unclaimed_map` | -10 pts per 30 min interval (not 22:00–12:00 UTC) |
| `abandoned_review` | -10 pts |
| `no_thread` | -10 pts |
| `incomplete_claim` | -30 pts |
| `other` | variable |

Points floor at 0 — penalties never push balance negative.

---

## Helper Assist System

- A reviewer can call in a helper for a complex map.
- If the helper's assessment matches the final result: helper +10 pts.
- If helper is wrong: helper -10 pts.
- Tracked in `helper_assists` table.

---

## Ghost Markers

- New reviewers have no accuracy history (last 30 = empty → 0%).
- Ghost markers are synthetic correct-marker rows seeded at onboarding to give new reviewers a fair starting accuracy (~96.67% by default — Master tier).
- They drain out naturally as real submissions fill the 30-marker window.
- Admin can override ghost marker counts with `>setoverride`.

---

## Daily Challenges

Each session, the bot picks a set of challenges from a fixed catalogue. Reviewers earn bonus points by hitting challenge targets during the session. Evaluated at session close.

Challenge catalogue (with eval functions in database.py):
`marathon_day`, `stack_king`, `single_sub_volume`, `lucky_7`, `high_roller`, `variety_hour`, `perfect_5`, `quality_control`, `first_reviewer`, `early_bird`, `quiet_hero`, `hat_trick`, `cleanup_crew`, `even_steven`, `steady_hand`, `odd_eddie`, `mirror`, `first_cleanup`, `first_strike`, `rolling_stone`, `lone_wolf`, `diamond_run`, `burst_mode`, `marathon_leader`

---

## Random Bonus Events (from HTML rewards shop tab)

| Event | Bonus | Trigger |
|-------|-------|---------|
| Odd Eddie | +20 pts | Submit with odd marker count |
| Even Steven | +20 pts | Submit with even marker count |
| Mirror | +30 pts | Two subs with exact same marker count |
| First Cleanup | +25 pts | First reviewer to submit at base value 1 today |
| Lone Wolf | +30 pts | Submit when no other reviewer has in past 2h |
| Early Bird | +20 pts | Submit within 30 min of `>newday` |
| First Reviewer | +25 pts | First sub of the session |
| Cleanup Crew | +25 pts | Submit using base-pt value of 1 |
| High Roller | +30 pts | Submit using base-pt value of 4 |

---

## Rewards Shop (point costs — as of removal date, after 1.5× increase)

| Points | Reward |
|--------|--------|
| 225 | Free Pro Surge Route |
| 300 | Paid Priority Role |
| 539 | Wave Contributor Role |
| 821 | Free Pro Loot Route |
| 854 | 800 V-Bucks Gift |
| 870 | $3 AUD Payout |
| 1,125 | Skip Day (10 markers) |
| 1,131 | Free Pro Drop Map |
| 1,166 | Promotion |
| 1,205 | $7.50 AUD Payout |
| 1,775 | $15 AUD Payout |
| 2,276 | @everyone Ping |
| 2,570 | $25 AUD Payout |
| 2,781 | VIP Role |
| 3,122 | $33 AUD Payout |
| 3,419 | $40 AUD Payout |
| 3,867 | $50 AUD Payout |
| 5,768 | $80 AUD Payout |
| 6,348 | $100 AUD Payout |
| 8,570 | $150 AUD Payout |
| 10,890 | $200 AUD Payout |
| 12,950 | $225 AUD Payout |
| 13,781 | $250 AUD Payout |

---

## Key Config IDs (from `drop_map_reviewing_config.py`)

See the archived `drop_map_reviewing_config.py` — it holds every channel ID, role ID, and tunable constant used by the system.

---

## Bot Commands

**Staff commands (all staff):**
- `>myreviews` — personal stats, tier, accuracy, streaks, lifetime points
- `>reviewingleaderboard` — top reviewers sorted by points
- `>preview [date]` — preview points summary for a session

**Admin commands:**
- `>newday` — open a new review session
- `>endday` — close session, post daily summary
- `>claim [map_id]` — claim a map for review
- `>submit [map_id] [correct] [total] [link]` — submit results
- `>addpoints <@user> [pts]` — manual point adjustment
- `>removepoints <@user> [pts]` — manual deduction
- `>addpenalty <@user> [type]` — apply a penalty
- `>setoverride <@user> [count]` — set ghost marker count
- `>listoverrides` — list active ghost overrides
- `>addreviewer <@user>` — register + grant role
- `>removereviewer <@user>` — de-register + strip role
- `>wipereviewing` — ⚠️ wipe ALL data (2-step confirm)
- `>dropmapreviewing enable/disable/status` — toggle system

---

## Entanglements (what was wired into shared files)

```
reviewing_commands.py
  └── imports: database.py (all reviewer functions)
  └── imports: drop_map_reviewing_config.py
  └── imports: tasks.staff_hub_writer (push_drop_map_leaderboard_to_github)

reviewing_tasks.py
  └── imports: database.py (reviewer functions)
  └── background loops: reminder (1h), cleanup (24h)

main.py
  └── shutdown: get_all_reviewer_leaderboard_stats() → push to Staff Hub

database.py
  └── reviewers.db connection (separate from bot_database.db)
  └── 15 tables, 40+ functions, all reviewing-only

multi_guild_role_commands.py
  └── granting Drop Map Reviewer role → calls add_drop_map_reviewer()
  └── removing Drop Map Reviewer role → calls remove_drop_map_reviewer()

utilities.py
  └── get_reviewing_embed() → reviewing help tab in >adminhelp

web_api.py
  └── /api/reviewing → serves website/data/reviewing.json

staff_hub_writer.py
  └── push_drop_map_leaderboard_to_github() → writes website/data/reviewing.json

database_backup.py
  └── backs up reviewers.db and json_data/drop_map_reviewing.json
```
