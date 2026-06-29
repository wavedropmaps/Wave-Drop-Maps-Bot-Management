# fortnite.gg — Bot Integration

> Referenced from `AGENTS.md` → Codebase Map. Deep research lives in [`ai-hub/research/fortnite-gg/`](../../research/fortnite-gg/README.md).

## What the bot uses from fn.gg

Staff submit **fortnite.gg links** (`?d=season/chapter/patch/code`) for drop maps, loot routes, and surge routes. The watermark cog (`commands/auto_watermark.py`) depends on:

- **Leaflet `CRS.Simple`** — flat pixel coords in `[[-256,0],[0,256]]` space (same as fn.gg's data files).
- **`window.Drawing`** — exact object coordinates for routes (polylines, markers, text labels); used for tight crop framing instead of YOLO screenshot detection.
- **`window.__wmbMap`** — captured Leaflet map instance (via init-script hook on `window.L`) for `fitBounds`, fractional zoom (`zoomSnap: 0`), and screenshots.
- **Cloudflare** — pages need real Chrome (`playwright` + `channel='chrome'`); static tiles/JS can be curl'd without challenge.

Commands: `>dmw` / `>dropmapwatermark`, `>lrw` / `>lootroutewatermark`, plus full-screenshot and zoom-diag variants.

## Deep research

| Topic | Read |
|---|---|
| fn.gg site architecture, tiles, data layer | [`how-fortnite-gg-works.md`](../../research/fortnite-gg/how-fortnite-gg-works.md) |
| Epic minimap vs fn.gg render, competitor sites, build pipeline | [`drop-map-imagery.md`](../../research/fortnite-gg/drop-map-imagery.md) |
| Why the watermark zoom looks "poor" (render window = host monitor; NOT a bug) | [`bot-render-zoom.md`](../../research/fortnite-gg/bot-render-zoom.md) |

**Render window = host monitor.** `RENDER_W/RENDER_H = _monitor_resolution()` and `RENDER_DPR = _screen_dpr()`, so output == a screenshot taken on this machine. A narrow monitor (1280×720 here) crowds fn.gg's fixed-size labels → looks zoomed-out; a wider monitor = roomier. Don't change `RENDER_*` without explicit say-so.

## Deprecated approach

Before June 2026 the watermark commands used YOLO models on screenshots. Replaced by reading fn.gg's own drawing data. See [`ai-hub/deprecated/yolo-watermark-detector/README.md`](../../deprecated/yolo-watermark-detector/README.md).
