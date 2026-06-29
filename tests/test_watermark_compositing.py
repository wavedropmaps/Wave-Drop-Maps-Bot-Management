"""
Snapshot/invariant tests for the drop-map watermark compositing.

The whole point of the placement preview is that the red footprint box
(`drop_map_footprint`) matches where the logo actually lands
(`process_image_manual`). These tests guard that they never drift — including
across the `width_frac` size control wired into the ➖/➕ resize buttons.

Runnable two ways:
    python3 tests/test_watermark_compositing.py     # standalone (no pytest needed)
    pytest tests/test_watermark_compositing.py       # if pytest is installed

Asset images (assets/TEXT_1_1.png, assets/logo wave.png) must exist; the test
chdirs to the repo root so the module's relative asset paths resolve.
"""

import io
import os
import sys

import numpy as np
from PIL import Image

# Make the repo importable and asset-relative paths resolvable from anywhere.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)
os.chdir(_REPO_ROOT)

from commands.auto_watermark import (  # noqa: E402
    process_image_manual,
    drop_map_footprint,
    LOGO_CENTER_SCALE,
)

BASE_W, BASE_H = 800, 600
CHANGE_THRESH  = 2   # per-pixel RGB delta that counts as "logo painted here"


def _base_bytes():
    """A flat mid-gray canvas so any logo pixel shows up as a diff."""
    img = Image.new('RGB', (BASE_W, BASE_H), (128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _painted_bbox(base_bytes, out_bytes, exclude_box=None):
    """Bounding box of pixels that changed between base and output, optionally
    masking out a region (the auto corner wave logo) so we measure only the
    center logo."""
    a = np.asarray(Image.open(io.BytesIO(base_bytes)).convert('RGB'), dtype=np.int16)
    b = np.asarray(Image.open(io.BytesIO(out_bytes)).convert('RGB'), dtype=np.int16)
    changed = np.abs(a - b).sum(axis=2) > CHANGE_THRESH
    if exclude_box is not None:
        x0, y0, x1, y1 = (int(round(v)) for v in exclude_box)
        changed[max(0, y0):y1, max(0, x0):x1] = False
    ys, xs = np.where(changed)
    assert len(xs) > 0, "no logo pixels detected — compositing produced no change"
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _check_one(xfrac, yfrac, width_frac):
    base = _base_bytes()

    boxes = drop_map_footprint(base, xfrac, yfrac, width_frac)
    assert len(boxes) >= 1, "expected at least the center-logo footprint box"
    core = boxes[0]                      # center logo (solid-core) box
    corner = boxes[1] if len(boxes) > 1 else None
    cx0, cy0, cx1, cy1 = core
    core_w, core_h = cx1 - cx0, cy1 - cy0

    # 1) Footprint box is centered on the clicked point (within integer rounding).
    target_x, target_y = BASE_W * xfrac, BASE_H * yfrac
    box_cx, box_cy = (cx0 + cx1) / 2, (cy0 + cy1) / 2
    assert abs(box_cx - target_x) <= 1.0, f"footprint X off: {box_cx} vs {target_x}"
    assert abs(box_cy - target_y) <= 1.0, f"footprint Y off: {box_cy} vs {target_y}"

    # 2) Footprint width honors width_frac (solid core == width_frac of image width).
    assert abs(core_w - width_frac * BASE_W) <= 2, \
        f"footprint width {core_w} != {width_frac * BASE_W:.1f} (width_frac broken)"

    # 3) The ACTUAL paint contains the footprint box (the red box never claims
    #    space the logo doesn't cover). Painted pixels include the soft glow, so
    #    painted bbox should be a superset of the solid-core footprint.
    out = process_image_manual(base, xfrac, yfrac, width_frac)
    px0, py0, px1, py1 = _painted_bbox(base, out, exclude_box=corner)
    tol = 2
    assert px0 <= cx0 + tol and py0 <= cy0 + tol and px1 >= cx1 - tol and py1 >= cy1 - tol, \
        f"footprint {core} not contained by painted bbox {(px0, py0, px1, py1)}"

    # 4) The painted center aligns with the clicked point (gross-drift guard;
    #    generous tolerance absorbs any asymmetry in the logo's glow halo).
    paint_cx, paint_cy = (px0 + px1) / 2, (py0 + py1) / 2
    assert abs(paint_cx - target_x) <= max(6, 0.2 * core_w), \
        f"painted center X drifted: {paint_cx} vs {target_x}"
    assert abs(paint_cy - target_y) <= max(6, 0.2 * core_h), \
        f"painted center Y drifted: {paint_cy} vs {target_y}"

    return core_w


def test_footprint_matches_paste():
    for xf, yf in [(0.5, 0.4), (0.3, 0.6), (0.5, 0.5)]:
        for wf in [0.15, LOGO_CENTER_SCALE, 0.40]:
            _check_one(xf, yf, wf)


def test_size_is_monotonic():
    small = _check_one(0.5, 0.5, 0.15)
    mid   = _check_one(0.5, 0.5, 0.30)
    big   = _check_one(0.5, 0.5, 0.50)
    assert small < mid < big, f"width not monotonic in width_frac: {small} {mid} {big}"


def test_default_matches_legacy_behavior():
    """Calling with no width_frac must equal calling with LOGO_CENTER_SCALE —
    proves the new optional arg didn't change existing renders."""
    base = _base_bytes()
    a = process_image_manual(base, 0.5, 0.4)
    b = process_image_manual(base, 0.5, 0.4, LOGO_CENTER_SCALE)
    assert a == b, "default width_frac drifted from legacy LOGO_CENTER_SCALE behavior"


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL  {name}: {e}")
    print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILED'}")
    sys.exit(1 if failures else 0)
