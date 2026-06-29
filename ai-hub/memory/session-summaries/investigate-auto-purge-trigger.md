# Auto Purge Trigger Investigation

**Date:** 2026-06-19  
**Topic:** Investigating why unreplied messages were mysteriously getting deleted, and adding global debugging to find rogue delete triggers.

---

## What we built / discussed

- Investigated user reports that unreplied messages were being deleted automatically for no reason.
- Discovered that the `ReplyDMOutbound` 5-minute Auto Purge performs a "Clean Sweep": when a user gets a reply, it deletes the reply, the original message, AND all previous unpinned messages from that user in the channel.
- Discovered that the Wave Logistics (new proof system) bot replying to users triggers this purge, because the system treats *any* bot reply as a staff reply.
- To prove/monitor this (and catch any other rogue deletions), we used the `/superpowers` `debug` framework.
- Added a global `discord.Message.delete` monkey-patch in `main.py` to print a highly visible `[ULTRA-DEBUG]` alert with a full stack trace to the console whenever the bot deletes any message.

## Key decisions

- Rather than guessing which file was calling `.delete()`, we hijacked the base Discord library function itself to force the bot to confess exactly where the trigger came from (via `traceback.format_stack()`).

## Files changed

- `main.py` — Patched `discord.Message.delete` right at startup to log all deletions with their call stack.

## Things to remember

- The `ReplyDMOutbound` system sweeps up *all* past unreplied messages when a user gets *one* reply.
- The `is_staff` check intentionally includes `message.author.bot`, meaning other automated systems (like Wave Logistics) will accidentally trigger the 5-minute purge and DM systems of the Wave Management Bot.
