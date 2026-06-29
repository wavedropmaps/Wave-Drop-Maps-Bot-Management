# Core Files — one read per session (don't re-read)

> Referenced from `AGENTS.md` → Codebase Map. The largest, most-touched files. Summaries here let you avoid re-reading them.

### `main.py` (~1295 lines) — Bot entry point
- Loads `.env`, sets up rotating UTC log handlers (`logs/`), configures rate-limit detection by monkey-patching `discord.HTTPClient`.
- Adds `commands/` to `sys.path`, dynamically loads all cogs from `commands/` and `tasks/`.
- Stores `_original_user_send` / `_original_member_send` (from `discord.abc.Messageable.send`) BEFORE patching — these are used by the DM queue worker to actually deliver DMs without re-entering the monkey-patch loop.
- Monkey-patches `discord.User.send` and `discord.Member.send` to route ALL outbound DMs through the shared DM queue (`DMQueueCog.enqueue()`). Any cog calling `user.send()` is automatically intercepted — no per-cog changes needed. The patch returns `None` immediately (fire-and-forget); callers must not use the return value.
- Defines `bot` and `log_sent_dm` (exported via `__all__`).
- Wires `database.set_bot_instance(bot)` so auto-removal logic can reach Discord.
- Logs setup happens before cog loads — see early `print("="*60)` block.

### `database.py` (5852 lines) — All persistence
- **Connection pool** (`DatabasePool`, 5 connections, semaphore-gated, PRAGMA-tuned: WAL, NORMAL sync, 64MB cache, 30s busy_timeout).
- **Tables:** `vbucks`, `vbucks_reservations`, `strike_points`, `wave_points`, `loot_route_positions`, `loot_route_points`, `route_assignments`, `away_return_dates`, `cache`, `config`, and many more.
- **Pattern:** every write function takes optional `bot=None` — if provided, triggers leaderboard auto-update + (for strikes) auto role removal at 3+ points.
- **Wallet types:** `'main'`, `'req'`, `'role'`, `'purge'` (validated against `VALID_WALLET_TYPES`).
- **Helper:** `row_to_dict()` safely converts `aiosqlite.Row` to dict.
- **Semantic logging:** Writes also emit events to `core.global_logger.log_event` for the Wave-Logging dashboard.
- **`_bot_instance` global** — set once at startup so DB functions can dispatch Discord side-effects without circular imports.

### `commands/drop_map_voting.py` (2155 lines) — Weekly drop spot voting
- Forum-thread-based community vote on which Fortnite drop spot gets a map next.
- Flow: `/addvoting` submits spot (DM image upload, 5-min timeout) → pinned card with ▲ vote button in forum thread `1508289287169511496` → 1 submission/member, 2 votes/member max.
- **Weekly cycle: Sunday 00:00 UTC** — top spot wins, posted to queue channel `1210837116649742396` as Paid Priority, announced in leaderboard thread, all cards deleted, DB wiped.
- On startup, catches up if a Sunday passed while bot was down.
- Admin: `/votingclear`, `/votingpick`, `/votingconfig`.
- **Fuzzy dedupe** at 0.75 similarity (`difflib`). Image dir: `assets/drop_map_voting_images/`, 8 MB cap.

### `commands/utilities.py` (1875 lines) — Helpers + help system
- `Utilities` cog: `>ping`, `>uptime`, `>invitecount`, `>dm`, `>help`, `>adminhelp`.
- Rich **HelpView / AdminHelpView** classes (`discord.ui.View`) with dropdown + button nav for nested help embeds (Stats, Goals, Rewards Economy, Wave Points, Predictions, etc.).
- This is the canonical place for **shared embed/UI scaffolding** — don't reinvent.
- Imports from `core.helpers` (utility functions) and `core.cache` (config_cache).

### `commands/multi_guild_role_commands.py` (1374 lines) — 3-guild role sync
- Wizard commands: `>dutyrolegive`, `>dutyroleremove`, `>staffrolegive`, `>staffroleremove`.
- Adds/removes a role by **case-insensitive name match** across all 3 guilds (`GUILD_IDS` constant).
- **Allowlisted role names** — `DUTY_ROLES` (Drop Map Reviewer, Loot Route Maker, etc.) vs `STAFF_ROLES` (Management, Head Admin, Admin, Support, etc.). Duty commands can't grant staff roles and vice versa.
- **Permission gates:** duty cmds → Admin perm OR `Head Admin` role; staff cmds → Admin perm only.
- Head Admin users (without Admin perm) get **1 use / command / 24h** rate limit (file: `head_admin_role_sync_rate_limit.json`).
- Wizard timeout 60s, max 25 users/wizard, compact summary if >6 users.
- Specialty: `Drop Map Reviewer` triggers `add_drop_map_reviewer` / `remove_drop_map_reviewer` DB hooks (imported lazily, tolerates absence).
