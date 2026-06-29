# Plan — `>dmw` / `>lrw`: viewport picker + render speedup

*Drafted 2026-06-24. Status: PROPOSED (not built). Scope chosen by owner: "just plan it" for now; default viewport = Native.*

## Context

Both `>dropmapwatermark` (`>dmw`) and `>lootroutewatermark` (`>lrw`) share one render pipeline in
[`commands/auto_watermark.py`](../../commands/auto_watermark.py):
`_watermark_flow` → `_render_fit_raw` → Playwright/Chrome → fn.gg `window.Drawing` + Leaflet fitBounds
→ framing nudge → grid → preview → opacity.

Current render config (lines ~33–57):
- **`>dmw`** renders at the **monitor's native resolution** (`RENDER_W/H` via `GetSystemMetrics`)
  and **native DPR** (`RENDER_DPR` via `GetDpiForSystem`, i.e. 1.0 or 1.5 — *not* 2).
- **`>lrw`** is hardcoded to **2560×1440 @ DPR 2** (`LRW_RENDER_W/H/DPR`, added in commit 7e2856b9
  for sharper watermarks).

Each command takes ~30 s to render.

## Reason

1. **Owner wants a viewport chooser** at the start of each command — first option "Native" (whatever
   screen the bot runs on), then preset sizes (720p / 1080p / 2K / 4K). **DPR pinned to 2 for all**;
   only the viewport `w×h` changes.
2. **Owner wants both commands faster.** Investigation shows the ~30 s is *almost entirely fixed
   waiting*, not resolution:
   - Chrome cold-launches on **every** command (~2–4 s).
   - Hardcoded `wait_for_timeout` sleeps in `_render_fit_raw`: 2000 + 2500 + 700 ms ≈ 5.2 s.
   - Fit-adjust loop: up to 6 × 600 ms ≈ 3.6 s (already early-exits when frame stops shrinking).
   - fn.gg network load: variable, mostly unavoidable.
   - Resolution/DPR only affects the **final screenshot encode + PIL crop**, NOT the 30 s body.

## Purpose

Make `>dmw`/`>lrw` (a) let the operator pick the render viewport up front, and (b) render
meaningfully faster — without changing the watermark/placement UX downstream.

---

## Part A — Viewport picker

**Where:** new step at the very start of `_watermark_flow`, before "[1/3] Rendering map".
A Discord button row (View) offering presets. Selection sets `(w, h, dpr=2)` passed into the
render functions.

**Presets (all DPR 2; only viewport changes):**

| Label  | Viewport `w×h` | Effective px @ DPR2 |
|--------|----------------|---------------------|
| Native (default) | `_monitor_resolution()` | e.g. 1920×1080 → 3840×2160 |
| 720p   | 1280×720   | 2560×1440 |
| 1080p  | 1920×1080  | 3840×2160 |
| 2K     | 2560×1440  | 5120×2880 |
| 4K     | 3840×2160  | 7680×4320 |

- **Default = Native** (on timeout or no pick, proceed with Native @ DPR2).
- This unifies `>dmw` and `>lrw`: both flow through the same picker. `LRW_RENDER_*` constants become
  just the "2K" preset; `>lrw`'s current behavior = picking 2K.
- **Note `RENDER_DPR` change:** today `>dmw` uses native DPR (often 1.0/1.5). Pinning DPR 2 makes
  `>dmw` output sharper/larger than before — intended, confirm with owner it's desired for dmw too.

**Plumbing:** `_render_fit_raw` already accepts `w/h/dpr` overrides. The framing-nudge path
(`raw_render_fn` partial) already forwards them. Need to:
- thread the chosen `(w,h,dpr)` from the picker into the `functools.partial(_render_fit_raw, ...)`
  and into `render_dpr=` for `_framing_nudge`.
- **Fix latent bug:** `crop_fit_box` (line ~600) uses module-level `RENDER_DPR`, not the passed dpr.
  Only matters on the legacy crop path (not the nudge path lrw uses), but should take the active dpr
  to stay correct once dpr is variable.

**4K caveat:** 7680×4320 ≈ 33 MP. Full-viewport PNG in memory is large and slow to encode; raw flow
already falls back to JPEG above 9.5 MB. Framing-nudge sends *crops* so final file is usually fine.
Offer 4K but expect it to be the slowest option (fights the speedup goal).

---

## Part B — Render speedup

Ordered by payoff. Each is independent; can ship incrementally.

1. **Persistent browser instance (biggest win).**
   Launch one `chromium` (channel='chrome', headless) when the cog loads (or lazily on first use),
   keep it on the cog, and create a fresh **context** per render (cheap) instead of relaunching
   Chrome each time. Close context after each render; close browser on cog unload.
   - Saves ~2–4 s/command (cold start).
   - Care: thread-safety — renders run in `_executor` (ThreadPoolExecutor, max_workers=2). Sync
     Playwright objects are not thread-safe across threads. Options: (a) a single dedicated render
     thread with its own browser, or (b) keep per-call `sync_playwright()` but reuse a long-lived
     browser via a lock. Pick (a) for cleanliness — serialize renders on one worker thread that owns
     the browser. (Renders are already effectively serialized by UX anyway.)

2. **Replace blind sleeps with poll-until-ready.**
   - The `wait_for_timeout(2000)` after goto and `wait_for_timeout(2500)` after `_STRIP_UI` →
     poll `window.__wmbMap && window.Drawing` readiness on a short interval with a cap, exit as soon
     as ready. Most loads are ready well before 2.5 s.
   - The `wait_for_timeout(700)` fitBounds settle + per-iteration `600` ms → reduce to ~250–300 ms;
     the loop already detects when the content box stops changing.
   - Expected saving: ~3–5 s without harming reliability (keep generous caps as fallback).

3. **(Optional) keep a warm page / pre-navigated fn.gg tab** — likely overkill; skip unless 1+2
   aren't enough.

**Estimated result:** ~30 s → roughly 12–18 s for native/1080p; 2K similar; 4K stays heavier due to
encode cost.

---

## Files touched
- `commands/auto_watermark.py` — picker View + step, render plumbing, persistent-browser refactor,
  wait trimming, `crop_fit_box` dpr fix.

## Validation
- Run `python ai-hub/gates/validate.py` (must exit 0).
- Manual: `>dmw`/`>lrw` with each preset on a real fn.gg link; confirm crop quality, file size under
  Discord 10 MB, and wall-clock improvement.

## Open questions for owner
1. Pin DPR 2 for `>dmw` too (sharper but larger than today's native-DPR output)? Assumed **yes**.
2. Build order if/when greenlit: picker first, or speedup first? (Speedup is independent and helps
   every command immediately.)
