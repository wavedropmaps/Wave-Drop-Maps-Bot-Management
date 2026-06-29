# YOLO watermark detector — PARKED 2026-06

These two models powered the `>dmw` / `>lrw` watermark commands **before** the render
was rewritten to frame from fn.gg's own data:

- `weights/drop_spot_marker.pt` (210 MB) — detects drop-spot + marker boxes in a screenshot.
- `weights/glider_lines.pt` (55 MB) — segments glider / flight-path lines ("guidelines").

## Why parked
The watermark commands now read **`window.Drawing`** (fn.gg's exact object coordinates)
and use the live Leaflet map (`fitBounds`, CRS.Simple, zoomSnap:0) to frame the route —
no pixel-guessing model needed. See `commands/auto_watermark.py:render_and_crop_fit`.

The detector code still lives at **`utils/drop_spot_detector.py`** but is gated by a kill
switch so it never imports ultralytics/torch or loads these weights → **0 CPU / 0 RAM**.

## The models were only ever needed for one thing
Knowing where objects are **in the final screenshot** (after crop/nudge), for *automatic*
logo placement. Current placement is the manual `% grid`, so nothing consumes it. If we
add auto-placement later, `window.Drawing` (carried through the crop transform) is the
better source — these models may stay retired.

## How to reactivate
1. Set env `WMB_YOLO_DETECTOR=1` (or flip `DETECTOR_ENABLED` default in `utils/drop_spot_detector.py`).
2. `_WEIGHTS_DIR` in that file already points here, so the weights load from this folder.
3. The old consumer functions (`render_and_crop`, `detect_drop_spot`, `build_avoid_map`,
   `find_logo_spot`) still exist in `commands/auto_watermark.py` (dormant, no callers).
