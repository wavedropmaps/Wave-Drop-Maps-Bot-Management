# Animated Avatar (Animated WebP) Plan

**Status:** Planning — awaiting size decision, then ready to build.
**Created:** 2026-06-22.
**Goal:** Show **animated profile pictures on the Staff Hub website** — exactly like they animate in Discord — for staff who have animated avatars (e.g. xvmet `1483116358400081993`, hash `a_5aca2251cbecfd2f0d9da6dddcfc25ea`).

---

## 🧠 Context

- Animated Discord avatars have a hash prefixed `a_`. discord.py's `display_avatar.url` returns a **`.gif`** URL for these.
- A prior session (commit `165543da`, then `fd813331`) swapped `.gif?` → `.png?` everywhere to stop avatars breaking. That made them **work but static** — the animation is lost.
- Current live state (Windows, 2026-06-22): `economy.json` + `duties.json` show **0 gif, all png** — static fix is live and working. Windows is fully synced with `origin/master` (`0 0`).
- The avatar URL transform is **duplicated across 9 live files** in `tasks/` as `str(...display_avatar.url).replace('.gif?', '.png?')`.

## 🔬 Verified Facts (curl-tested against the real CDN, not assumed)

| URL format (size=1024) | Result |
|---|---|
| `.gif?size=1024` | **HTTP 415**, `application/json` — genuinely broken cross-origin. This is the real root cause. |
| `.webp?size=1024` | 200, `image/webp`, **static** first frame (~21 KB) |
| `.webp?animated=true&size=1024` | 200, `image/webp`, **animated** (✓) |
| `.png?size=1024` | 200, static (~240 KB) |

**Animated WebP file size by `size` param** (the performance catch):
`64`→125 KB · `128`→377 KB · `256`→1.0 MB · `1024`→**2.6 MB**.

## 📐 Rules / Constraints

- **Cross-platform:** bot runs on Windows; use `pathlib.Path`; no Mac-only tricks.
- **Master only**, commit + push to `origin/master`.
- **Validation gate:** `python ai-hub/gates/validate.py` must exit 0 before claiming done.
- **Scope discipline:** only the avatar URL transform changes. No bonus refactors.
- **Animated WebP renders natively in a plain `<img>` tag** → **no frontend/HTML/CSS changes required.**
- **Don't touch deprecated files** (`ai-hub/deprecated/old-code/staff_sheet/staff_sheet.py`, `.../duties_scan.py`) — they're dead, replaced by `unified_weekly_loop.py`.
- Static (non-animated) avatars must keep behaving exactly as today.

## 💡 Ideas & Theories (why this shape)

- **Theory — only animated URLs contain `.gif?`.** Static avatars are already `.png`/never `.gif`. So a transform keyed on the substring `.gif?` touches *only* animated avatars and is safe by construction. ✅ matches the verified facts.
- **Idea — one shared helper, not 9 string edits.** The `.replace('.gif?', '.png?')` line is copy-pasted in 9 places. Editing the string 9× is brittle and drift-prone. A single helper centralizes both the format swap **and** the size cap, so the 2.6 MB problem is solved in one spot.
- **Theory — size is the real risk, not correctness.** Correctness is proven. The only way this regresses UX is page weight. Capping animated avatars at 128px (377 KB) keeps a 25-row leaderboard reasonable while still animating.
- **Alternative considered & rejected:** discord.py has no built-in `animated=true` webp helper in our version, so string manipulation on the URL is the pragmatic path.

---

## 🔧 The Helper

Add one shared util (home TBD — read where `tasks/` already import shared helpers, likely `core/`):

```python
def web_avatar_url(asset, size=128):
    """Web-safe avatar URL. Animated avatars -> animated webp (Discord .gif 415s cross-origin)."""
    if not asset:
        return None
    url = str(asset.with_size(size).url)
    return url.replace('.gif?', '.webp?animated=true&') if '.gif?' in url else url
```

## 📋 Steps

1. **Add the helper** to the shared util module (verify import home first).
2. **Replace the 9 live call sites** in `tasks/`:
   `economy_sync.py` (×2), `staff_hub_writer.py`, `tipsandtricks.py` (×2), `staff_insights.py`,
   `loot_routes.py` (×3), `surge_routes.py` (×2), `bot_admin_api.py` (×3), `unified_weekly_loop.py` (×2).
   *(Skip deprecated `staff_sheet.py` / `duties_scan.py`.)*
3. **Check `web_api.py:211`** — hardcodes `.png?size=128`. If hash starts with `a_`, emit animated webp; else stays static.
4. **Patch the live JSON** (`website/data/economy.json`, `duties.json`, …) so animated PFPs appear immediately without waiting for the next task cycle.
5. **Validate** — `python ai-hub/gates/validate.py` → exit 0.
6. **Restart the bot** on Windows so tasks regenerate URLs.
7. **Verify live** — curl a regenerated URL (expect 200 `image/webp` animated); spot-check xvmet on leaderboard + profile.
8. **Commit + push** to `origin/master`.

## 🔓 Open Decision

**Avatar size for animated webp:**
- **128px (377 KB) — recommended.** Avatars render small site-wide; safe for leaderboards.
- 256px (1 MB) — crisper on the profile page, heavier.
