Rebuild the Drop Map Reviewing system for Wave-Management-Bot (discord.py, prefix `>`).

This is a Discord bot system for staff to review Fortnite drop map submissions and earn
points redeemable for real rewards. All source files and exact specifications are in this
archive folder. Use them as the single source of truth.

FILES IN THIS ARCHIVE:
- reviewing_commands.py        → the full command cog (3,882 lines)
- drop_map_reviewing_config.py → all channel IDs, role IDs, constants
- reviewing_tasks.py           → background loops (hourly reminders, daily cleanup, etc.)
- reviewing_leaderboard_final.html → the full Staff Hub leaderboard page (4,853 lines)
- SYSTEM_OVERVIEW.md           → complete system documentation
- DATABASE_SCHEMA.md           → all 15 table definitions with columns

HOW TO REBUILD:
1. Copy reviewing_commands.py back to commands/
2. Copy drop_map_reviewing_config.py back to commands/
3. Copy reviewing_tasks.py back to tasks/
4. Copy reviewing_leaderboard_final.html back to website/
5. Re-add the database tables and functions to database.py (see DATABASE_SCHEMA.md for
   tables; the full function code is in reviewing_commands.py imports and database.py
   archived copy — recover from git history)
6. Re-add these lines to the shared files:
   - main.py: the shutdown leaderboard push block (see ENTANGLEMENTS in SYSTEM_OVERVIEW)
   - web_api.py: add 'reviewing' back to _API_PAGES
   - staff_hub_writer.py: add push_drop_map_leaderboard_to_github() back + dict entry
   - utilities.py: add reviewing tab tuple + get_reviewing_embed() method
   - database_backup.py: add reviewers.db back to FILES_TO_BACKUP + _WAL_DBS
   - multi_guild_role_commands.py: re-add SPECIALTY_REVIEWER, lazy import, and
     _handle_specialty_reviewer_raw() method + all if/elif branches

The system used a SEPARATE SQLite database (reviewers.db). Re-create it by adding the
CREATE TABLE blocks back to init_database() in database.py.

Bot prefix: `>`. Guild IDs: see drop_map_reviewing_config.py.
