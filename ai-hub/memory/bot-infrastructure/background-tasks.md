# Background Tasks (`tasks/` directory) + Shared DM Queue

> Referenced from `AGENTS.md` → Codebase Map.

## Background Tasks (`tasks/` directory)

- `leaderboard_updater.py` — auto-updates VBucks leaderboard (GitHub Pages JSON) on data change (debounced). Wave Points leaderboard lives on the staff hub website, not Discord.
- `staff_sheet.py` — syncs spreadsheet → Discord.
- `weekly_checks.py` — 72h mid-week warnings, 168h full-week strikes + VBucks awards.
- `weekly_roles.py` — weekly role assignments.
- `power_hour.py`, `random_challenges.py`, `duties_scan.py`.
- `random_challenges.py` — weekly challenge scheduler + 15 completion modes (checked hourly from `unified_weekly_loop`). Modes: `first_to_target`, `most_in_24h`, `consistency_gate`, `engagement_combo`, `balanced_staff`, `weekend_warrior`, `catchup_bracket`, `tiered_podium`, `closest_without_bust`, `route_runner`, `power_hour_overlap`, `proof_pipeline`, `underdog_24h`, `beat_last_week`, `active_week`, `seasonal_scramble`. Week-start rotation: message → engagement_combo/active_week/weekend_warrior (+ seasonal_scramble when `challenge_season.active`); req → beat_last_week/first_to_target; modlog → balanced_staff/first_to_target; reviews → proof_pipeline. Mid-week: catchup_bracket + underdog_24h (falls back to most_in_24h if no eligible underdogs). `mode_params` JSON stores fire-time eligibility, personal targets, tier claims, PH baselines.
- **`random_challenges.py`** — week-start (**5** duties incl. routes) + mid-week (**3**) challenges; deck-weighted mode pick with never-pair rules; 16 completion modes; hourly check via `unified_weekly_loop`; `mode_params` JSON on `weekly_challenges` rows.
- `dm_queue.py` — `DMQueueCog`, the shared cross-bot DM queue. See **Shared DM Queue System** below.
- `reply_dm_outbound.py` — watches a configured channel for staff replies to user messages; DMs the user via the shared queue with `_source='reply_dm_duty'` and arms a sticky note. Has retry/cancel buttons on failed-DM log entries.
- `reply_dm_inbound.py` — `AutoReplyCog`; listens for incoming DMs; if the user has an armed sticky note AND this bot armed it, fires the guild-specific auto-reply text.
- `reply_dm_state.py` — helper module (not a cog) with `arm_note`, `wipe_note`, `get_active_note` primitives for the `reply_dm_note` table in the shared DB.
- `maintenance.py`, `staff_hub_writer.py` (formerly `github_sync.py` — now the Staff Hub local data writer; GitHub push retired 2026-06-14), `map_request.py`.
- `strike_functions.py` — auto role removal at 3+ strikes (called from `database.update_strike_points`).
- `wave_logging.py` — logs events to `bot_logs` table + terminal capture. No push loops (push_wave_logging was a Mac-side no-op, removed). Separate SQLite connections are why DB pool has 30s busy_timeout.

## Shared DM Queue System 📬
- **Why it exists:** Both Wave Management Bot and Wave Logistics Bot run on this Windows machine. They share one SQLite DB (`C:/Users/kiere/Desktop/dm_shared_queue.db`, NOT `bot_database.db`) so outbound DMs are load-balanced across both bots without double-sending or exceeding Discord rate limits.
- **Interception:** `main.py` monkey-patches `discord.User.send` and `discord.Member.send` at startup. Every `user.send()` across ALL cogs on both bots is intercepted and routed through `DMQueueCog.enqueue()` — no per-cog changes needed. Calls return `None` immediately (fire-and-forget).
- **Flow:** `enqueue()` inserts the job → **coordinator loop** (1s) assigns to a capable bot via round-robin CAS UPDATE → **worker loop** (1s) on each bot claims and delivers using the stored original send methods → marks `sent`, logs to Discord.
- **Rate limits enforced:** 1 DM/second gap + max 5 DMs per 5-minute rolling window per bot.
- **Recovery loop** (10s): resets jobs stuck in `assigned`/`sending` >60s back to `pending`; max 3 retries before archiving to `dm_failed_archive`.
- **Job statuses:** `pending` → `assigned` → `sending` → `sent` → archive after 24h → pruned after 30d.
- **Failure categories:** `user_error` (Forbidden/NotFound — permanent, archived immediately), `bot_error`/`network_error` (retryable).
- **Dashboard:** Channel `1503714231566991441` — live system overview updated every 30s (queue stages, throughput, reliability, latency, per-bot status, cross-bot load sharing).
- **DM log channels:** Outbound `1411032010494967838` (logged after delivery), Inbound `1411027953046781982` (logged by `log_received_dm()` in `main.py` on_message).
- **`_source` tag:** `enqueue()` pops a `_source` kwarg before inserting — `'reply_dm_duty'` preserves the sticky note; `'auto_reply'` wipes note only after delivery succeeds; `None` wipes note at enqueue time.
- **Dual-module-instance quirk:** `tasks.dm_queue` can exist twice in memory due to import order. `_resolve_dm_queue_cog()` in `main.py` has 3 fallback resolver paths (get_cog → cogs walk → sys.modules singleton).
- **Sticky-note subsystem (`reply_dm_note` table):** Staff sends a reply via `reply_dm_outbound` → DM queued with `_source='reply_dm_duty'` → `arm_note(user_id, guild_id, source_bot_id)` fires. If the user DMs back within 48h, `AutoReplyCog` (`reply_dm_inbound.py`) fires the guild-specific auto-reply — but ONLY on the bot that armed the note (`source_bot_id == self.bot.user.id`), preventing both bots from replying. Notes expire after 48h, cleaned up every 6h.
