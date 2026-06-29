"""
auto_watermark.py — single command hub

Commands:
  >dropmapwatermark <url>  (alias: >dmw)
    Render fn.gg map → grid → user picks logo coords → pick opacity → watermark + logos → output
"""

import io
import os
import re
import ctypes
import asyncio
import functools
import logging
import json
import base64
import urllib.request
from pathlib import Path
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import discord
from discord.ext import commands
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger('discord')


# ══════════════════════════════════════════════════════════════════════════════
# SCREENSHOT CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def _monitor_resolution() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def _screen_dpr() -> float:
    """Actual display scale factor (1.0 = 100%, 1.5 = 150%, …) read from Windows,
    so the render tracks the screen dynamically instead of a hardcoded multiplier."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return max(1.0, user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


RENDER_W, RENDER_H = _monitor_resolution()
RENDER_DPR   = _screen_dpr()

# Viewport picker — both >dmw and >lrw render at a FIXED DPR of 2; only the
# viewport (CSS px) changes between presets. "Native" tracks the bot machine's
# own screen resolution (filled in at click time). Effective pixels = w·2 × h·2.
VIEWPORT_DPR = 2.0
VIEWPORT_PRESETS = [
    ("Native", None, None),   # → _monitor_resolution() at selection time
    ("720p",   1280,  720),
    ("1080p",  1920, 1080),
    ("2K",     2560, 1440),
    ("4K",     3840, 2160),
]
PAD_PX       = 60
MARKER_CLASS = 1
CONF         = 0.80
# networkidle cap. fn.gg is an ad/analytics-heavy SPA whose network rarely goes
# idle, so this wait almost always rode out to the old 20 s cap — pure dead time.
# Real readiness is polled separately (_wait_for_map: map + drawing data exist),
# so this is now just a short hedge for tiles to paint.
WAIT_LOAD_MS = 5000

BOT_DIR  = Path(__file__).parent.parent
WEIGHTS  = BOT_DIR / 'weights' / 'drop_spot_marker.pt'

# Single render worker: sync Playwright objects are thread-bound, so the
# persistent browser below MUST be created and used on exactly one thread. The
# executor only ever runs Playwright renders (image ops use the default loop
# executor), and renders are serialised by the interactive UX anyway.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='screenshot')

_CHROME_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)

# ── Persistent browser ─────────────────────────────────────────────────────────
# Chrome cold-launch was ~2-4 s of every render. Launch ONCE and reuse it,
# spinning up a fresh (cheap) context per render. Must only ever be touched from
# the single _executor thread.
_pw      = None   # the started sync_playwright() object
_browser = None   # the persistent Chromium instance


# Ad / analytics / tracker hosts to abort during load. fn.gg pulls in a lot of
# these and we waited for them to download before screenshotting — pure waste.
# Conservative DENYLIST (not allowlist) of well-known ad/analytics domains only:
# never map tiles, fn.gg itself, or cookie-consent frameworks (blocking consent
# scripts can hang the page — we already strip that UI + preset consent flags).
_AD_BLOCK_RE = re.compile(
    r"(doubleclick\.net|googlesyndication\.com|google-analytics\.com"
    r"|googletagmanager\.com|googleadservices\.com|adservice\.google"
    r"|amazon-adsystem\.com|adnxs\.com|scorecardresearch\.com"
    r"|quantserve\.com|moatads\.com|criteo\.|taboola\.com|outbrain\.com"
    r"|pubmatic\.com|rubiconproject\.com|casalemedia\.com|/gtag/|/gtm\.js)",
    re.I,
)


def _persistent_browser():
    """Return the shared Chromium, launching it once. Call only on the render
    worker thread (_executor, max_workers=1)."""
    global _pw, _browser
    from playwright.sync_api import sync_playwright
    if _browser is not None and _browser.is_connected():
        return _browser
    if _pw is None:
        _pw = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=True, channel='chrome')
    return _browser


@contextmanager
def _render_page(*, w, h, dpr, init_scripts=()):
    """Yield a fresh page on the persistent browser, tearing down only the
    context afterwards so the browser stays warm for the next render."""
    browser = _persistent_browser()
    ctx = browser.new_context(
        viewport={'width': w, 'height': h},
        device_scale_factor=dpr,
        user_agent=_CHROME_UA,
    )
    # Abort ad/analytics requests so they never download. Only matching URLs hit
    # this handler; everything else (map tiles, fn.gg scripts) passes natively.
    try:
        ctx.route(_AD_BLOCK_RE, lambda route: route.abort())
    except Exception:
        pass
    try:
        for s in init_scripts:
            ctx.add_init_script(s)
        yield ctx.new_page()
    finally:
        ctx.close()


def _shutdown_browser():
    """Close the persistent browser + Playwright. Must run on the render thread."""
    global _pw, _browser
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    _browser = None
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _pw = None


def _wait_for_map(page, cap_ms: int = 6000, interval: int = 150) -> bool:
    """Poll until fn.gg's captured map + drawing data exist, instead of sleeping a
    fixed time. Returns True as soon as both are present, False if the cap is hit."""
    waited = 0
    while waited < cap_ms:
        if page.evaluate("() => !!(window.__wmbMap && window.Drawing)"):
            return True
        page.wait_for_timeout(interval)
        waited += interval
    return False

_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    try {
        localStorage.setItem('fngg_selected', '{"poi":{},"spawns":{},"vaults":{},"quests":{}}');
        localStorage.setItem('fngg_opened', '{}');
        localStorage.setItem('fngg_new_poi', '1');
    } catch (e) {}
"""

# Capture the Leaflet map instance the instant fn.gg creates it. fn.gg keeps the
# map in a module closure (unreachable from `window` after load), so we trap the
# `window.L` assignment and register an addInitHook that stashes the instance on
# `window.__wmbMap`. This init-script runs at document-start — before fn.gg's
# bundle assigns window.L — so the hook is armed before the map is constructed.
_MAP_CAPTURE_SCRIPT = """
(function(){
    try {
        var _L;
        Object.defineProperty(window, 'L', {
            configurable: true,
            get: function(){ return _L; },
            set: function(v){
                _L = v;
                try {
                    if (v && v.Map && v.Map.addInitHook) {
                        v.Map.addInitHook(function(){ window.__wmbMap = this; });
                    }
                } catch (e) {}
            }
        });
    } catch (e) {}
})();
"""

_STRIP_UI = """
    document.body.className = '';
    const sels = [
        'header','#header','#menu','#toggle-sidebar','#resize-sidebar',
        '#open-filters','aside','nav','.banner',
        '[class*="ad-"]','[id*="ad-"]',
        '.cmpcontainer','[class*="cmp"]','[id*="cmp"]',
        '[class*="consent"]','[id*="consent"]',
        '[class*="cookie"]','[id*="cookie"]',
        '[class*="gdpr"]','[id*="gdpr"]',
        'iframe',
        '.leaflet-control-zoom','.leaflet-control-attribution'
    ];
    for (const s of sels) document.querySelectorAll(s).forEach(el => el.remove());
    const c = document.querySelector('#map') || document.querySelector('.leaflet-container');
    if (c) c.style.cssText = 'position:fixed!important;top:0!important;left:0!important;'
        + 'right:0!important;bottom:0!important;width:100vw!important;'
        + 'height:100vh!important;margin:0!important;z-index:9999';
    document.body.style.cssText = 'margin:0;padding:0;overflow:hidden';
    document.documentElement.style.cssText = 'margin:0;padding:0;overflow:hidden';
"""


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

LOGO_WAVE_PATH      = "assets/logo wave.png"
LOGO_TEXT_PATH      = "assets/TEXT_1_1.png"
WATERMARK_TILE_PATH = "assets/watermark_tile.png"

WATERMARK_OPACITY      = 64
WATERMARK_ANGLE        = -45
WATERMARK_TARGET_WIDTH = 0.60

LOGO_WAVE_SCALE    = 0.06
LOGO_CENTER_SCALE  = 0.25
LOGO_CENTER_OPACITY = 255
LOGO_CONTENT_ALPHA  = 60

TEXT_AVOID      = True
LOGO_PLACE_PAD  = 10
LOGO_SCAN_TOP   = 0.20


# ── Cached asset images ───────────────────────────────────────────────────────
# These three PNGs are re-read from disk on every watermark/logo op. Decode each
# once into an in-memory RGBA image and reuse it. .copy() detaches from PIL's lazy
# file handle so the fd doesn't stay open. Callers only ever read these (resize/
# crop/split/merge all return NEW images), so the cached originals are never mutated.
_LOGO_WAVE_IMG = None
_LOGO_TEXT_IMG = None
_WATERMARK_TILE_IMG = None


def _get_logo_wave():
    global _LOGO_WAVE_IMG
    if _LOGO_WAVE_IMG is None and os.path.exists(LOGO_WAVE_PATH):
        _LOGO_WAVE_IMG = Image.open(LOGO_WAVE_PATH).convert('RGBA').copy()
    return _LOGO_WAVE_IMG


def _get_logo_text():
    global _LOGO_TEXT_IMG
    if _LOGO_TEXT_IMG is None and os.path.exists(LOGO_TEXT_PATH):
        _LOGO_TEXT_IMG = Image.open(LOGO_TEXT_PATH).convert('RGBA').copy()
    return _LOGO_TEXT_IMG


def _get_watermark_tile():
    global _WATERMARK_TILE_IMG
    if _WATERMARK_TILE_IMG is None and os.path.exists(WATERMARK_TILE_PATH):
        _WATERMARK_TILE_IMG = Image.open(WATERMARK_TILE_PATH).convert('RGBA').copy()
    return _WATERMARK_TILE_IMG


# ══════════════════════════════════════════════════════════════════════════════
# RENDER PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def _detect_markers(img: Image.Image):
    # Reuse the shared, lazily-loaded YOLO cache in drop_spot_detector instead of
    # reloading the 210 MB .pt off disk on every call (this fn runs twice per render).
    # _get_model caches by path, so the model loads once and is reused thereafter.
    from utils.drop_spot_detector import _get_model, DROP_SPOT_MODEL_PATH
    # Pass the detector's own path constant (not str(WEIGHTS)) so this load shares
    # ONE cache entry with detect_drop_spot/detect_boxes — same model file, same key.
    model = _get_model(DROP_SPOT_MODEL_PATH)
    if model is None:
        return None
    results = model.predict(source=img, imgsz=1280, conf=CONF, verbose=False, save=False)
    boxes   = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return None
    cls  = boxes.cls.cpu().numpy().astype(int)
    xyxy = boxes.xyxy.cpu().numpy()
    m    = xyxy[cls == MARKER_CLASS]
    return m if len(m) > 0 else None


def _wait_until_loaded(page, cap_ms: int = WAIT_LOAD_MS):
    """Wait until the network goes idle (map tiles finished) instead of sleeping a
    fixed WAIT_LOAD_MS every time. Capped at cap_ms, so the worst case still matches
    the old fixed wait and a page with persistent connections just falls back to it.
    Fast loads return early — this is the bulk of the render-latency win, at no extra
    memory cost. (The preceding 2 s settle keeps networkidle from firing too early.)"""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    try:
        page.wait_for_load_state('networkidle', timeout=cap_ms)
    except PlaywrightTimeoutError:
        pass  # hit the cap — identical to the previous fixed wait


def render_and_crop(url: str, crop: bool = True) -> bytes:
    with _render_page(w=RENDER_W, h=RENDER_H, dpr=RENDER_DPR,
                      init_scripts=[_INIT_SCRIPT]) as page:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(2000)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        _wait_until_loaded(page)

        page.evaluate(_STRIP_UI)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        page.wait_for_timeout(3000)

        png1   = page.screenshot()
        img1   = Image.open(io.BytesIO(png1)).convert('RGB')
        boxes1 = _detect_markers(img1)

        # Union YOLO markers with the DOM/canvas content bounds (text labels,
        # drawn boxes/arrows) so the pan centres EVERYTHING, not just markers —
        # otherwise text above/below the marker cluster drifts off-viewport.
        cb1 = page.evaluate(_CONTENT_BOUNDS_JS)

        if boxes1 is not None:
            miny1 = float(boxes1[:, 1].min())
            maxy1 = float(boxes1[:, 3].max())
            if cb1 is not None:
                miny1 = min(miny1, cb1['top']    * RENDER_DPR)
                maxy1 = max(maxy1, cb1['bottom'] * RENDER_DPR)
            needed_bottom = PAD_PX - (img1.height - maxy1)
            needed_top    = PAD_PX - miny1
            drag_logical  = (needed_bottom - needed_top) / 2 / RENDER_DPR
            if abs(drag_logical) > 1:
                cx, cy = RENDER_W // 2, RENDER_H // 2
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(cx, int(cy - drag_logical), steps=30)
                page.mouse.up()
                page.wait_for_timeout(3000)

        cb2  = page.evaluate(_CONTENT_BOUNDS_JS)
        png2 = page.screenshot()

    if not crop:
        return png2

    img2   = Image.open(io.BytesIO(png2)).convert('RGB')
    boxes2 = _detect_markers(img2)
    if boxes2 is None:
        raise RuntimeError("No Marker-class boxes detected")

    # Crop = YOLO marker bbox ∪ DOM/canvas content bounds, so text labels that sit
    # outside the marker cluster (e.g. "Look For Tags") are never sliced off.
    crop_l = float(boxes2[:, 0].min())
    crop_t = float(boxes2[:, 1].min())
    crop_r = float(boxes2[:, 2].max())
    crop_b = float(boxes2[:, 3].max())
    if cb2 is not None:
        crop_l = min(crop_l, cb2['left']   * RENDER_DPR)
        crop_t = min(crop_t, cb2['top']    * RENDER_DPR)
        crop_r = max(crop_r, cb2['right']  * RENDER_DPR)
        crop_b = max(crop_b, cb2['bottom'] * RENDER_DPR)

    left   = max(0,           int(crop_l - PAD_PX))
    top    = max(0,           int(crop_t - PAD_PX))
    right  = min(img2.width,  int(crop_r + PAD_PX))
    bottom = min(img2.height, int(crop_b + PAD_PX))

    buf = io.BytesIO()
    img2.crop((left, top, right, bottom)).save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


# True content extent (CSS px) of everything the route author drew:
#   • DOM layer  — markers/pins, SVG shapes, text tooltips, image overlays.
#   • Canvas layer — fn.gg renders lines, arrows, boxes, circles AND text labels
#     onto a single Leaflet <canvas> in the overlay pane. Those are NOT DOM
#     elements, so getBoundingClientRect can't see them. We read the canvas's
#     non-transparent pixel bbox and map it back to screen coords, then union.
_CONTENT_BOUNDS_JS = """
() => {
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity, n = 0;

    // --- DOM-drawn objects ---
    // NOTE: ".leaflet-marker-icon *" is required — fn.gg text labels ("Look For
    // Tags" etc.) are classless child <div>s that OVERFLOW their marker-icon
    // wrapper (wrapper ~117x10, text ~176x18, hanging left/above the anchor).
    // Measuring only the wrapper under-counts the extent and the crop slices text.
    document.querySelectorAll(
        '.leaflet-marker-icon, .leaflet-marker-icon *, path.leaflet-interactive, .leaflet-tooltip, .leaflet-image-layer'
    ).forEach(el => {
        const k = el.getBoundingClientRect();
        if (k.width > 0 && k.height > 0) {
            if (k.left < l) l = k.left;  if (k.top < t) t = k.top;
            if (k.right > r) r = k.right; if (k.bottom > b) b = k.bottom; n++;
        }
    });

    // --- Canvas-drawn vector layer (lines, boxes, circles, text) ---
    const cv = document.querySelector('.leaflet-overlay-pane canvas');
    if (cv) {
        try {
            const rect = cv.getBoundingClientRect();
            const W = cv.width, H = cv.height;
            const d = cv.getContext('2d').getImageData(0, 0, W, H).data;
            let cx0 = Infinity, cy0 = Infinity, cx1 = -Infinity, cy1 = -Infinity, cn = 0;
            for (let y = 0; y < H; y++) {
                const row = y * W;
                for (let x = 0; x < W; x++) {
                    if (d[(row + x) * 4 + 3] > 10) {
                        if (x < cx0) cx0 = x; if (y < cy0) cy0 = y;
                        if (x > cx1) cx1 = x; if (y > cy1) cy1 = y; cn++;
                    }
                }
            }
            if (cn > 0) {
                const sx = rect.width / W, sy = rect.height / H;
                const cl = rect.left + cx0 * sx, ct = rect.top + cy0 * sy;
                const cr = rect.left + cx1 * sx, cb = rect.top + cy1 * sy;
                if (cl < l) l = cl; if (ct < t) t = ct;
                if (cr > r) r = cr; if (cb > b) b = cb; n += cn;
            }
        } catch (e) { /* tainted canvas — fall back to DOM bounds */ }
    }

    if (n === 0) return null;
    return {left: l, top: t, right: r, bottom: b};
}
"""


# Tiny crop margin (screenshot px) for the loot-route DOM crop — just enough to
# avoid clipping the outermost pixel, no wasted border. ~5 CSS px at DPR 3.
LOOT_ROUTE_PAD_PX = 15


def render_and_crop_dom(url: str, crop: bool = True) -> bytes:
    """Locate the route from its true content extent — DOM objects unioned with
    the overlay <canvas> pixel bounds (fn.gg draws lines/boxes/text on canvas).
    Zooms out until the whole route fits the viewport, pans it to centre, then
    crops tight to the content (tiny LOOT_ROUTE_PAD_PX margin) so nothing is
    clipped and no space is wasted."""
    PAD_CSS = LOOT_ROUTE_PAD_PX / RENDER_DPR  # margin expressed in CSS px
    cx, cy  = RENDER_W // 2, RENDER_H // 2     # viewport centre (CSS px)

    with _render_page(w=RENDER_W, h=RENDER_H, dpr=RENDER_DPR,
                      init_scripts=[_INIT_SCRIPT]) as page:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(2000)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        _wait_until_loaded(page)

        page.evaluate(_STRIP_UI)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        page.wait_for_timeout(3000)

        # 1) Zoom out (scroll down) until the whole route fits + padding.
        for _ in range(8):
            b = page.evaluate(_CONTENT_BOUNDS_JS)
            if b is None:
                break
            fits_w = (b['right'] - b['left']) + 2 * PAD_CSS <= RENDER_W
            fits_h = (b['bottom'] - b['top']) + 2 * PAD_CSS <= RENDER_H
            if fits_w and fits_h:
                break
            page.mouse.move(cx, cy)
            page.mouse.wheel(0, 240)        # positive deltaY = zoom out
            page.wait_for_timeout(1200)

        # 2) Pan so the content is centred — guarantees padding on all sides.
        b = page.evaluate(_CONTENT_BOUNDS_JS)
        if b is not None:
            dx = cx - (b['left'] + b['right']) / 2
            dy = cy - (b['top'] + b['bottom']) / 2
            if abs(dx) > 1 or abs(dy) > 1:
                page.mouse.move(cx, cy)
                page.mouse.down()
                page.mouse.move(int(cx + dx), int(cy + dy), steps=30)
                page.mouse.up()
                page.wait_for_timeout(1500)

        bounds = page.evaluate(_CONTENT_BOUNDS_JS)
        png    = page.screenshot()

    if not crop:
        return png

    if bounds is None:
        raise RuntimeError("No map objects detected on the page")

    img    = Image.open(io.BytesIO(png)).convert('RGB')
    left   = max(0,          int(bounds['left']   * RENDER_DPR - LOOT_ROUTE_PAD_PX))
    top    = max(0,          int(bounds['top']    * RENDER_DPR - LOOT_ROUTE_PAD_PX))
    right  = min(img.width,  int(bounds['right']  * RENDER_DPR + LOOT_ROUTE_PAD_PX))
    bottom = min(img.height, int(bounds['bottom'] * RENDER_DPR + LOOT_ROUTE_PAD_PX))

    buf = io.BytesIO()
    img.crop((left, top, right, bottom)).save(buf, format='PNG')
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════════════════
# TIGHTEST-FIT RENDER (window.Drawing + Leaflet fitBounds)
# ══════════════════════════════════════════════════════════════════════════════
# fn.gg is Leaflet on CRS.Simple with zoomSnap:0 (smooth fractional zoom) and it
# exposes window.Drawing = the route author's exact objects (polyline / polygon /
# rectangle / circle / circlemarker[+tooltip] / marker), each as CRS.Simple
# [lat,lng] data. Instead of scroll-wheeling out and guessing the frame from
# pixel detection (which can't tell the route from fn.gg's own base spawn markers
# drawn on the same shared canvas, and which is dominated by fixed-size text
# label boxes), we:
#   1. fitBounds to ALL drawn objects  → zooms IN so the route fills the frame
#   2. zoom out the *minimum* needed so the fixed-pixel-size text labels also fit
#   3. crop tight to the real content (geometry projected ∪ arrow/text label DOM)
# Text labels are fixed screen-size and DON'T shrink with zoom, so they set a
# hard minimum frame width — the loop converges onto that, no wasted ocean.

# contentBox(): screen-px bbox of the real route content — every window.Drawing
# object projected to the screen, unioned with the DOM boxes of the arrow markers
# and text labels (so a label's full rendered width is included, never clipped).
# Deliberately ignores fn.gg base spawn markers (chests/wood/…) — they're not in
# window.Drawing, so they can never inflate the frame.
_FIT_HELPER = """
    const map = window.__wmbMap, D = window.Drawing;
    const contentBox = () => {
        let l=1e9,t=1e9,r=-1e9,b=-1e9;
        const add=(x,y)=>{ if(x<l)l=x; if(y<t)t=y; if(x>r)r=x; if(y>b)b=y; };
        const proj=(la,lo)=>{ const p=map.latLngToContainerPoint([la,lo]); return [p.x,p.y]; };
        const walk=p=>{ if(typeof p[0]==='number'){ const xy=proj(p[0],p[1]); add(xy[0],xy[1]); } else p.forEach(walk); };
        // lines / areas / rects / point markers — just their vertices
        ['polyline','polygon','rectangle','marker'].forEach(c=>(D[c]||[]).forEach(o=>{ if(o.latlng) walk(o.latlng); }));
        // circles: radius is in MAP units → include the whole RING, not just the
        // centre (else a chest ring near the edge gets sliced by the crop).
        (D.circle||[]).forEach(o=>{ if(o.latlng){
            const c=map.latLngToContainerPoint([o.latlng[0],o.latlng[1]]);
            let rpx=0;
            if(o.radius){ const e=map.latLngToContainerPoint([o.latlng[0],o.latlng[1]+o.radius]); rpx=Math.abs(e.x-c.x); }
            add(c.x-rpx,c.y-rpx); add(c.x+rpx,c.y+rpx);
        }});
        // circlemarkers: radius is in PIXELS (fixed-size dot) — small ring round the anchor
        (D.circlemarker||[]).forEach(o=>{ if(o.latlng){
            const c=map.latLngToContainerPoint([o.latlng[0],o.latlng[1]]); const rpx=(o.radius||10);
            add(c.x-rpx,c.y-rpx); add(c.x+rpx,c.y+rpx);
        }});
        // DOM arrow markers + text labels — INCLUDING children. fn.gg renders a
        // label's text as a child <div> that OVERFLOWS its marker wrapper, so
        // measuring only the wrapper under-counts and the crop slices the text.
        // Base spawn layers are off (init script), so every .leaflet-marker-icon
        // here is route content — safe to measure them all + their children.
        document.querySelectorAll('.leaflet-marker-icon, .leaflet-marker-icon *').forEach(el=>{
            const k=el.getBoundingClientRect(); if(k.width>0){ add(k.left,k.top); add(k.right,k.bottom); }
        });
        return (l>r)?null:[l,t,r,b];
    };
"""

# fitBounds to the geographic extent of every drawn object (anchors). Returns
# false if the map/drawing isn't reachable so the caller can fall back.
_FIT_GEOM_JS = """(pad)=>{
    const map=window.__wmbMap, D=window.Drawing; if(!map||!D) return false;
    let la0=1e9,lo0=1e9,la1=-1e9,lo1=-1e9;
    const w=p=>{ if(typeof p[0]==='number'){ la0=Math.min(la0,p[0]); la1=Math.max(la1,p[0]); lo0=Math.min(lo0,p[1]); lo1=Math.max(lo1,p[1]); } else p.forEach(w); };
    ['polyline','polygon','rectangle','circlemarker','marker'].forEach(c=>(D[c]||[]).forEach(o=>{ if(o.latlng) w(o.latlng); }));
    // circle radius is in MAP units — extend bounds by it so the full ring fits
    (D.circle||[]).forEach(o=>{ if(o.latlng){ const la=o.latlng[0], lo=o.latlng[1], rr=o.radius||0;
        la0=Math.min(la0,la-rr); la1=Math.max(la1,la+rr); lo0=Math.min(lo0,lo-rr); lo1=Math.max(lo1,lo+rr); }});
    if(la0>la1) return false;
    map.fitBounds([[la0,lo0],[la1,lo1]], {padding:[pad,pad], animate:false});
    return true;
}"""

# Measure real content; if it overflows (viewport - margin), zoom out the minimum
# needed (×1.02 fudge so it converges in 1-3 steps), re-centre on the content.
# Returns {cw,ch,fits} or null if data vanished.
_FIT_ADJUST_JS = "(margin)=>{" + _FIT_HELPER + """
    if(!map||!D) return null;
    const cb=contentBox(); if(!cb) return null;
    const l=cb[0],t=cb[1],r=cb[2],b=cb[3]; const cw=r-l, ch=b-t;
    const VW=innerWidth, VH=innerHeight, aW=VW-2*margin, aH=VH-2*margin;
    const fits = cw<=aW && ch<=aH;
    const centerLL = map.containerPointToLatLng(L.point((l+r)/2,(t+b)/2));
    let z=map.getZoom();
    if(!fits){ const scale=Math.max(cw/aW, ch/aH); z = z - Math.log2(scale*1.02); }
    map.setView(centerLL, z, {animate:false});
    return {cw:Math.round(cw), ch:Math.round(ch), fits:fits};
}"""

_CONTENT_BOX_JS = "()=>{" + _FIT_HELPER + " return contentBox(); }"


# Pad (CSS px) added around the content box when cropping the final tight frame.
FIT_CROP_PAD = 12


def _render_fit_raw(url: str, *, w=None, h=None, dpr=None):
    """Playwright body of the tight-fit render. Returns
    ``(full_png_bytes, content_bbox_css)`` where content_bbox_css is
    ``[left, top, right, bottom]`` in CSS px, OR ``(None, None)`` if fn.gg's map /
    window.Drawing couldn't be reached (caller should fall back to legacy).

    The full (uncropped) viewport screenshot is returned so callers can crop it
    themselves — the framing-nudge UI reuses it to zoom/pan WITHOUT re-rendering.

    w/h/dpr override the module-level RENDER_* constants — the viewport picker
    passes the chosen size and a fixed DPR of 2 for both >dmw and >lrw."""
    _w   = w   or RENDER_W
    _h   = h   or RENDER_H
    _dpr = dpr or RENDER_DPR

    MARGIN = 26  # CSS px breathing room while deciding the fit zoom
    png = None
    cb = None
    need_fallback = False

    with _render_page(w=_w, h=_h, dpr=_dpr,
                      init_scripts=[_MAP_CAPTURE_SCRIPT, _INIT_SCRIPT]) as page:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        page.evaluate(_STRIP_UI)
        page.evaluate("window.dispatchEvent(new Event('resize'))")

        # No networkidle wait — fn.gg's network never goes quiet, so that wait was
        # pure dead time. Poll for the only thing that matters (map + drawing data
        # exist), then a short settle so the tiles finish painting before the shot.
        if not _wait_for_map(page):
            need_fallback = True
        elif not page.evaluate(_FIT_GEOM_JS, 30):
            need_fallback = True
        else:
            page.wait_for_timeout(500)  # let tiles paint + fitBounds settle (1st redraw)
            prev_cw = None
            for _ in range(6):
                res = page.evaluate(_FIT_ADJUST_JS, MARGIN)
                if res is None:
                    need_fallback = True
                    break
                if res['fits']:
                    break
                # A long fixed-size label sets a hard min width — once the frame
                # stops shrinking, more zoom-out is pointless. Stop early.
                if prev_cw is not None and abs(prev_cw - res['cw']) < 5:
                    break
                prev_cw = res['cw']
                # Only pay the redraw settle when we're actually adjusting again —
                # no wasted wait on the iteration that already fits before the shot.
                page.wait_for_timeout(350)
            if not need_fallback:
                cb = page.evaluate(_CONTENT_BOX_JS)
                png = page.screenshot()
                if not cb:
                    need_fallback = True

    if need_fallback or png is None:
        return None, None
    return png, cb


def crop_fit_box(png: bytes, cb, pad: float = FIT_CROP_PAD) -> bytes:
    """Crop a full viewport screenshot to the content box (CSS px) + pad."""
    img    = Image.open(io.BytesIO(png)).convert('RGB')
    left   = max(0,          int(cb[0] * RENDER_DPR - pad * RENDER_DPR))
    top    = max(0,          int(cb[1] * RENDER_DPR - pad * RENDER_DPR))
    right  = min(img.width,  int(cb[2] * RENDER_DPR + pad * RENDER_DPR))
    bottom = min(img.height, int(cb[3] * RENDER_DPR + pad * RENDER_DPR))
    buf = io.BytesIO()
    img.crop((left, top, right, bottom)).save(buf, format='PNG')
    img.close()
    buf.seek(0)
    return buf.read()


def render_and_crop_fit(url: str, crop: bool = True) -> bytes:
    """Render an fn.gg drawing framed TIGHT to the route, with NOTHING cut off.

    Uses fn.gg's own data (window.Drawing) + the Leaflet map (captured via
    addInitHook) to fitBounds on every drawn object, then zooms out the minimum
    needed so the fixed-size text labels also fit, then crops tight. Falls back to
    render_and_crop_dom (legacy scroll-and-detect) if the map or drawing data
    can't be reached — e.g. fn.gg changes structure, or a link with no drawing."""
    png, cb = _render_fit_raw(url)
    if png is None:
        logger.info("render_and_crop_fit: fit data unavailable — falling back to legacy DOM render (%s)", url)
        return render_and_crop_dom(url, crop=crop)
    return png if not crop else crop_fit_box(png, cb)


# ══════════════════════════════════════════════════════════════════════════════
# ZOOM LADDER (>zoomtest) — screenshot the route at several real map-zoom levels
# ══════════════════════════════════════════════════════════════════════════════
# Reads the baseline (what >lrw auto-fits to), then setView()s the live Leaflet map
# to a spread of zoom levels around it and screenshots each — so you can eyeball
# which zoom looks right. NO crop, NO watermark, NO logo. Full viewport each time.
_ZOOM_BASE_JS = ("()=>{ const m=window.__wmbMap; const c=m.getCenter(); "
                 "return {zoom:m.getZoom(), lat:c.lat, lng:c.lng, minZoom:m.getMinZoom(), maxZoom:m.getMaxZoom()}; }")
_SETVIEW_JS = "(a)=>{ const m=window.__wmbMap; m.setView([a.lat,a.lng], a.zoom, {animate:false}); return m.getZoom(); }"


def render_zoom_ladder(url: str, step: float = 0.5, n_each: int = 2):
    """Render the fn.gg route at (2*n_each + 1) zoom levels around the auto-fit zoom.
    Returns a list of (delta, actual_zoom, jpeg_bytes), ordered most-zoomed-OUT →
    most-zoomed-IN. Screenshot only. Raises if fn.gg's map/data can't be reached."""
    MARGIN = 26
    shots = []
    with _render_page(w=RENDER_W, h=RENDER_H, dpr=RENDER_DPR,
                      init_scripts=[_MAP_CAPTURE_SCRIPT, _INIT_SCRIPT]) as page:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(2000)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        _wait_until_loaded(page)
        page.evaluate(_STRIP_UI)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        page.wait_for_timeout(2500)

        if not page.evaluate("() => !!(window.__wmbMap && window.Drawing)"):
            raise RuntimeError("couldn't read fn.gg map / drawing data for this link")

        # Reproduce the >lrw auto-fit so 'normal' (delta 0) == what >lrw uses.
        page.evaluate(_FIT_GEOM_JS, 30)
        page.wait_for_timeout(700)
        prev_cw = None
        for _ in range(6):
            res = page.evaluate(_FIT_ADJUST_JS, MARGIN)
            page.wait_for_timeout(600)
            if res is None or res['fits']:
                break
            if prev_cw is not None and abs(prev_cw - res['cw']) < 5:
                break
            prev_cw = res['cw']

        base = page.evaluate(_ZOOM_BASE_JS)
        Z = base['zoom']
        deltas = ([round(-step * i, 3) for i in range(n_each, 0, -1)]
                  + [0.0]
                  + [round(step * i, 3) for i in range(1, n_each + 1)])
        for d in deltas:
            z = max(base['minZoom'], min(base['maxZoom'], Z + d))
            actual = page.evaluate(_SETVIEW_JS, {'lat': base['lat'], 'lng': base['lng'], 'zoom': z})
            page.wait_for_timeout(650)
            shots.append((d, actual, page.screenshot()))

    out = []
    for d, z, png in shots:
        img = Image.open(io.BytesIO(png)).convert('RGB')
        s = 1920 / img.width if img.width > 1920 else 1
        if s < 1:
            img = img.resize((int(img.width * s), int(img.height * s)))
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        img.close()
        out.append((d, z, buf.getvalue()))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

def _detect_stride(density: np.ndarray) -> int:
    sig  = density.astype(np.float64) - density.mean()
    if sig.std() == 0:
        return 0
    corr = np.correlate(sig, sig, mode='full')[len(density) - 1:]
    if len(corr) < 30:
        return 0
    search = corr[20:]
    peaks  = [(i + 20, search[i]) for i in range(1, len(search) - 1)
              if search[i] > search[i - 1] and search[i] > search[i + 1]]
    if not peaks:
        return 0
    return int(max(peaks, key=lambda p: p[1])[0])


def _make_seamless(tile: Image.Image) -> Image.Image:
    arr  = np.array(tile)
    alph = arr[:, :, 3]
    rows = np.where(alph.sum(axis=1) > 0)[0]
    cols = np.where(alph.sum(axis=0) > 0)[0]
    if len(rows) == 0 or len(cols) == 0:
        return tile
    top, left   = int(rows[0]), int(cols[0])
    rs = _detect_stride(alph.sum(axis=1))
    cs = _detect_stride(alph.sum(axis=0))
    if rs <= 0 or cs <= 0:
        return tile.crop((left, top, int(cols[-1]) + 1, int(rows[-1]) + 1))
    new_h = ((int(rows[-1]) - top + 1) // rs) * rs
    new_w = ((int(cols[-1]) - left + 1) // cs) * cs
    if new_h <= 0 or new_w <= 0:
        return tile.crop((left, top, int(cols[-1]) + 1, int(rows[-1]) + 1))
    return tile.crop((left, top, left + new_w, top + new_h))


def build_watermark_pattern(width: int, height: int) -> Image.Image:
    """Expensive, OPACITY-INDEPENDENT half of the watermark: tile the design across
    a rotated canvas and crop to (width, height). Returns an RGBA layer at the tile's
    NATIVE alpha (the asset is a faint design, ~11% mean alpha — that faintness is
    intentional). apply_watermark_opacity then scales this linearly. Do NOT binarize
    the alpha here: forcing every inked pixel to 255 destroys the design's faintness
    and makes even the lowest opacity look near-solid."""
    tile_src = _get_watermark_tile()
    if tile_src is None:
        logger.warning("⚠️ Watermark tile not found: %s — skipping", WATERMARK_TILE_PATH)
        return Image.new('RGBA', (width, height), (0, 0, 0, 0))
    tile  = _make_seamless(tile_src)
    scale = max(1, int(width * WATERMARK_TARGET_WIDTH)) / tile.width
    tile  = tile.resize((max(1, int(tile.width * scale)), max(1, int(tile.height * scale))), Image.LANCZOS)
    diag  = int(np.sqrt(width**2 + height**2)) + max(tile.size) * 2
    canvas = Image.new('RGBA', (diag, diag), (0, 0, 0, 0))
    tw, th = tile.size
    for y in range(0, diag, th):
        for x in range(0, diag, tw):
            canvas.paste(tile, (x, y), tile)
    rot = canvas.rotate(WATERMARK_ANGLE, expand=False, resample=Image.BICUBIC)
    canvas.close()   # diag×diag buffer (~hundreds of MB) — release before holding rot
    cx  = (rot.width  - width)  // 2
    cy  = (rot.height - height) // 2
    out = rot.crop((cx, cy, cx + width, cy + height))
    rot.close()      # same size as canvas — release now that the crop is taken
    return out


def apply_watermark_opacity(pattern: Image.Image, opacity: int = None) -> Image.Image:
    """Cheap: scale a pattern's alpha to the requested opacity, matching the old
    path EXACTLY. Note the SQUARE: build_watermark_pattern tiles via
    ``canvas.paste(tile, pos, tile)``, which uses the tile's alpha as its own mask
    and so squares it (A → A²/255). The old code baked opacity into the tile
    *before* that paste, so opacity got squared too. Applying it here (after the
    paste) means we must square it ourselves — (opacity/255)² — or the watermark
    comes out ~255/opacity times too strong (the '100% opacity' bug)."""
    if opacity is None:
        opacity = WATERMARK_OPACITY
    k = (opacity / 255.0) ** 2
    r, g, b, a = pattern.split()
    return Image.merge('RGBA', (r, g, b, a.point(lambda px: int(px * k))))


def generate_diagonal_text_watermark(width: int, height: int, opacity: int = None) -> Image.Image:
    """Back-compat wrapper: build the pattern then apply opacity in one shot."""
    return apply_watermark_opacity(build_watermark_pattern(width, height), opacity)


def process_watermark_only(input_bytes: bytes, opacity: int = None,
                           pattern: Image.Image = None) -> bytes:
    """Composite the watermark onto the image. If a precomputed full-strength
    ``pattern`` (from build_watermark_pattern, matching the image size) is given,
    only the cheap opacity-scale + composite run here — the heavy tile+rotate was
    already done in the background."""
    original = Image.open(io.BytesIO(input_bytes)).convert('RGBA')
    try:
        if pattern is None:
            pattern = build_watermark_pattern(*original.size)
        wm  = apply_watermark_opacity(pattern, opacity)
        out = Image.alpha_composite(original, wm)
        wm.close()                       # watermark layer no longer needed
        buf = io.BytesIO()
        rgb = out.convert('RGB')
        rgb.save(buf, format='PNG')
        rgb.close()
        out.close()
        buf.seek(0)
        return buf.read()
    finally:
        original.close()                 # always release the base buffer, even on error


def _crop_to_content(img: Image.Image, alpha_thresh: int) -> Image.Image:
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    alpha  = np.array(img.split()[3])
    ys, xs = np.where(alpha > alpha_thresh)
    if len(xs) == 0:
        return img
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def _prep_center_logo(base: Image.Image, width_frac: float = LOGO_CENTER_SCALE):
    text_src = _get_logo_text()
    if text_src is None:
        return None
    full     = _crop_to_content(text_src, 0)
    a0       = np.array(full.split()[3])
    ys, xs   = np.where(a0 > 128)
    if len(xs) == 0:
        sx0, sy0, sw0, sh0 = 0, 0, full.width, full.height
    else:
        sx0, sy0 = int(xs.min()), int(ys.min())
        sw0, sh0 = int(xs.max()) - sx0 + 1, int(ys.max()) - sy0 + 1
    scale = (base.width * width_frac) / sw0
    logo  = full.resize((max(1, round(full.width * scale)), max(1, round(full.height * scale))), Image.LANCZOS)
    r, g, b, a = logo.split()
    logo  = Image.merge('RGBA', (r, g, b, a.point(lambda px: int(px * LOGO_CENTER_OPACITY / 255))))
    return logo, (round(sx0 * scale), round(sy0 * scale)), (round(sw0 * scale), round(sh0 * scale))


def paste_corner_logo(base: Image.Image) -> Image.Image:
    logo = _get_logo_wave()
    if logo is None:
        logger.warning("⚠️ Wave logo not found: %s", LOGO_WAVE_PATH)
        return base
    target_w = int(base.width * LOGO_WAVE_SCALE)
    target_h = int(logo.height * (target_w / logo.width))
    logo     = logo.resize((target_w, target_h), Image.LANCZOS)
    base.paste(logo, (0, base.height - target_h), logo)
    return base


def _load_roboflow_config():
    try:
        with open('config.json', 'r') as f:
            cfg = json.load(f).get('roboflow', {})
    except Exception:
        cfg = {}
    # Prefer the env var (kept in the gitignored .env); fall back to config.json.
    env_key = os.getenv('ROBOFLOW_API_KEY')
    if env_key:
        cfg['api_key'] = env_key
    return cfg


def _detect_drop_spot_roboflow(img: Image.Image):
    cfg = _load_roboflow_config()
    if not cfg.get('api_key'):
        return None
    try:
        buf     = io.BytesIO()
        img.convert('RGB').save(buf, format='JPEG', quality=90)
        img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        url     = (
            f"https://detect.roboflow.com/{cfg['project']}/{cfg['version']}"
            f"?api_key={cfg['api_key']}&confidence={cfg.get('confidence', 60)}&overlap={cfg.get('overlap', 50)}"
        )
        req = urllib.request.Request(url, data=img_b64.encode(),
                                     headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            preds = json.loads(resp.read().decode()).get('predictions', [])
        if not preds:
            return None
        best = max(preds, key=lambda p: p['confidence'])
        return best['x'], best['y'], best['width'], best['height']
    except Exception as e:
        logger.warning("Roboflow detection failed: %s", e)
        return None


def detect_drop_spot(img: Image.Image):
    try:
        from utils.drop_spot_detector import detect_drop_spot as _local, is_available
        if is_available():
            return _local(img)
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Local detector error: %s", e)
    return _detect_drop_spot_roboflow(img)


def build_avoid_map(img: Image.Image):
    w, h   = img.size
    base   = np.zeros((h, w), dtype=bool)
    glider = np.zeros((h, w), dtype=bool)

    def _fill(x1, y1, x2, y2):
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(w, int(x2)), min(h, int(y2))
        if x2 > x1 and y2 > y1:
            base[y1:y2, x1:x2] = True

    try:
        from utils.drop_spot_detector import glider_line_mask, detect_boxes
        gm = glider_line_mask(img)
        if gm is not None and gm.shape == glider.shape:
            glider = gm
        for cx, cy, bw, bh in detect_boxes(img):
            _fill(cx - bw/2, cy - bh/2, cx + bw/2, cy + bh/2)
        if TEXT_AVOID:
            from utils.drop_spot_detector import detect_text_boxes
            for x1, y1, x2, y2 in detect_text_boxes(img):
                _fill(x1, y1, x2, y2)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("avoid map: %s", e)
    return base, glider


def find_logo_spot(img: Image.Image, w: int, h: int,
                   base_avoid: np.ndarray, glider: np.ndarray, drop: tuple = None) -> tuple:
    iw, ih   = img.size
    pad      = LOGO_PLACE_PAD
    top_lim  = int(ih * LOGO_SCAN_TOP)
    bot_lim  = int(ih * (1.0 - LOGO_SCAN_TOP))
    qx_left  = iw / 4.0
    qx_right = 3.0 * iw / 4.0

    def clampx(x):
        return max(0, min(iw - w, int(round(x))))

    if not drop:
        return clampx(iw / 2 - w / 2), max(0, min(ih - h, int(ih / 2 - h / 2)))

    ds_cx, ds_cy, ds_w, ds_h = drop
    band_half = ih / 30.0

    def col_layers(xleft):
        xx = clampx(xleft)
        return base_avoid[:, xx:xx+w].any(axis=1), glider[:, xx:xx+w].any(axis=1), xx

    def eff_win(base_r, glid_r, yy):
        yy = max(0, min(ih - h, int(yy)))
        if abs((yy + h/2) - ds_cy) > band_half:
            return base_r[yy:yy+h]
        return base_r[yy:yy+h] | glid_r[yy:yy+h]

    cl    = ds_cx - w / 2.0
    col_x = {
        "C":  cl,
        "L1": cl - 0.5 * w,
        "R1": cl + 0.5 * w,
        "L2": max(cl - w, qx_left),
        "R2": min(cl + w, qx_right - w),
    }
    layers = {n: col_layers(x) for n, x in col_x.items()}

    def center_levels(direction):
        base_r, glid_r, _ = layers["C"]
        out = []
        if direction == "up":
            y = min(int(ds_cy - ds_h/2 - pad - h), ih - h)
            for _ in range(80):
                if y < top_lim: break
                yy = max(0, y); out.append(yy)
                win = eff_win(base_r, glid_r, yy)
                if not win.any(): break
                ny = (yy + int(np.argmax(win))) - pad - h
                if ny >= y: break
                y = ny
        else:
            y = int(ds_cy + ds_h/2 + pad)
            for _ in range(80):
                if y + h > bot_lim: break
                out.append(y)
                win = eff_win(base_r, glid_r, y)
                if not win.any(): break
                ny = (y + int(np.where(win)[0][-1])) + pad
                if ny <= y: break
                y = ny
        return out

    def order(levs):
        n = len(levs)
        if n == 0: return
        yield ("C", levs[0])
        for N in range(1, n + 1):
            yield ("L1", levs[N-1]); yield ("R1", levs[N-1])
            if N < n: yield ("C", levs[N])
            yield ("L2", levs[N-1]); yield ("R2", levs[N-1])

    for direction in ("up", "down"):
        for col, y in order(center_levels(direction)):
            base_r, glid_r, xx = layers[col]
            if not eff_win(base_r, glid_r, y).any():
                return xx, max(0, min(ih - h, int(y)))

    return clampx(iw/2 - w/2), max(0, min(ih - h, int(ih/2 - h/2)))


def process_image_manual(input_bytes: bytes, xpct: float, ypct: float,
                         width_frac: float = LOGO_CENTER_SCALE) -> bytes:
    """Watermark already applied — stamp center logo at (xpct, ypct) + corner wave logo.
    width_frac controls the center logo's solid-core width as a fraction of image width."""
    base   = Image.open(io.BytesIO(input_bytes)).convert('RGBA')
    try:
        iw, ih = base.size
        prep   = _prep_center_logo(base, width_frac)
        if prep is not None:
            logo, (sx, sy), (sw, sh) = prep
            cx, cy = int(iw * xpct), int(ih * ypct)
            tx, ty = cx - sw // 2, cy - sh // 2
            base.paste(logo, (tx - sx, ty - sy), logo)
        base = paste_corner_logo(base)
        buf  = io.BytesIO()
        rgb  = base.convert('RGB')
        rgb.save(buf, format='PNG')
        rgb.close()
        return buf.getvalue()
    finally:
        base.close()


def process_loot_route_logo(input_bytes: bytes, xpct: float, ypct: float) -> bytes:
    """Watermark already applied — stamp ONLY the small wave logo, centred on
    the grid-chosen (xpct, ypct). No center text logo, no auto corner logo."""
    base   = Image.open(io.BytesIO(input_bytes)).convert('RGBA')
    try:
        iw, ih = base.size
        logo = _get_logo_wave()
        if logo is None:
            logger.warning("⚠️ Wave logo not found: %s", LOGO_WAVE_PATH)
        else:
            target_w = max(1, int(iw * LOGO_WAVE_SCALE))
            target_h = max(1, int(logo.height * (target_w / logo.width)))
            logo     = logo.resize((target_w, target_h), Image.LANCZOS)
            cx, cy   = int(iw * xpct), int(ih * ypct)
            base.paste(logo, (cx - target_w // 2, cy - target_h // 2), logo)
        buf = io.BytesIO()
        rgb = base.convert('RGB')
        rgb.save(buf, format='PNG')
        rgb.close()
        return buf.getvalue()
    finally:
        base.close()


# ── Placement-preview helpers ──────────────────────────────────────────────
# footprint_fn(input_bytes, xpct, ypct) -> list of (x0,y0,x1,y1) the logo(s)
# will occupy. Keep these in sync with the matching logo processors above.
def loot_route_footprint(input_bytes: bytes, xpct: float, ypct: float):
    """Box for the single wave logo, centred on (xpct, ypct)."""
    base   = Image.open(io.BytesIO(input_bytes))
    iw, ih = base.size
    boxes  = []
    logo = _get_logo_wave()
    if logo is not None:
        target_w = max(1, int(iw * LOGO_WAVE_SCALE))
        target_h = max(1, int(logo.height * (target_w / logo.width)))
        cx, cy   = int(iw * xpct), int(ih * ypct)
        boxes.append((cx - target_w // 2, cy - target_h // 2,
                      cx + target_w // 2, cy + target_h // 2))
    return boxes


def drop_map_footprint(input_bytes: bytes, xpct: float, ypct: float,
                       width_frac: float = LOGO_CENTER_SCALE):
    """Boxes for both drop-map logos — grid-placed center logo + auto corner
    wave logo. Mirrors process_image_manual + paste_corner_logo placement.
    width_frac matches the center logo size chosen via the preview resize buttons."""
    base   = Image.open(io.BytesIO(input_bytes)).convert('RGBA')
    iw, ih = base.size
    boxes  = []
    prep   = _prep_center_logo(base, width_frac)
    if prep is not None:
        _logo, (sx, sy), (sw, sh) = prep
        cx, cy = int(iw * xpct), int(ih * ypct)
        tx, ty = cx - sw // 2, cy - sh // 2
        boxes.append((tx, ty, tx + sw, ty + sh))
    logo = _get_logo_wave()
    if logo is not None:
        target_w = int(iw * LOGO_WAVE_SCALE)
        target_h = int(logo.height * (target_w / logo.width))
        boxes.append((0, ih - target_h, target_w, ih))
    return boxes


def process_loot_route_logo_bl(input_bytes: bytes, xpct: float = None, ypct: float = None) -> bytes:
    """BL shortcut — stamp the wave logo in the bottom-left corner (coords
    ignored), identical placement to the drop-map auto corner logo."""
    base = Image.open(io.BytesIO(input_bytes)).convert('RGBA')
    try:
        base = paste_corner_logo(base)
        buf  = io.BytesIO()
        rgb  = base.convert('RGB')
        rgb.save(buf, format='PNG')
        rgb.close()
        return buf.getvalue()
    finally:
        base.close()


def loot_route_footprint_bl(input_bytes: bytes, xpct: float = None, ypct: float = None):
    """Footprint box for the bottom-left wave logo (matches paste_corner_logo)."""
    base   = Image.open(io.BytesIO(input_bytes))
    iw, ih = base.size
    boxes  = []
    logo = _get_logo_wave()
    if logo is not None:
        target_w = int(iw * LOGO_WAVE_SCALE)
        target_h = int(logo.height * (target_w / logo.width))
        boxes.append((0, ih - target_h, target_w, ih))
    return boxes


def process_loot_route_logo_br(input_bytes: bytes, xpct: float = None, ypct: float = None) -> bytes:
    """BR shortcut — stamp the wave logo in the bottom-right corner."""
    base = Image.open(io.BytesIO(input_bytes)).convert('RGBA')
    try:
        logo = _get_logo_wave()
        if logo is not None:
            target_w = int(base.width * LOGO_WAVE_SCALE)
            target_h = int(logo.height * (target_w / logo.width))
            logo     = logo.resize((target_w, target_h), Image.LANCZOS)
            base.paste(logo, (base.width - target_w, base.height - target_h), logo)
        buf = io.BytesIO()
        rgb = base.convert('RGB')
        rgb.save(buf, format='PNG')
        rgb.close()
        return buf.getvalue()
    finally:
        base.close()


def loot_route_footprint_br(input_bytes: bytes, xpct: float = None, ypct: float = None):
    """Footprint box for the bottom-right wave logo."""
    base   = Image.open(io.BytesIO(input_bytes))
    iw, ih = base.size
    boxes  = []
    logo = _get_logo_wave()
    if logo is not None:
        target_w = int(iw * LOGO_WAVE_SCALE)
        target_h = int(logo.height * (target_w / logo.width))
        boxes.append((iw - target_w, ih - target_h, iw, ih))
    return boxes


# Transient previews (grid, placement box) are display-only thumbnails Discord
# shrinks anyway, so we cap their width here for speed. The FINAL output and the
# render screenshot are never downscaled — quality of the deliverable is untouched.
PREVIEW_MAX_W = 1500


def _downscale_preview(img: Image.Image):
    """Return (possibly-downscaled image, scale factor). Bilinear is plenty for a
    throwaway preview and far faster than the full-res draw+encode."""
    if img.width <= PREVIEW_MAX_W:
        return img, 1.0
    s = PREVIEW_MAX_W / img.width
    return img.resize((PREVIEW_MAX_W, max(1, int(img.height * s))), Image.BILINEAR), s


def render_preview_box(input_bytes: bytes, boxes) -> bytes:
    """Draw red outline rectangle(s) showing the logo footprint(s)."""
    base = Image.open(io.BytesIO(input_bytes)).convert('RGB')
    try:
        base, s = _downscale_preview(base)   # display-only — scale boxes to match
        draw = ImageDraw.Draw(base)
        lw   = max(3, base.width // 300)
        for (x0, y0, x1, y1) in boxes:
            draw.rectangle([x0 * s, y0 * s, x1 * s, y1 * s], outline=(255, 0, 0), width=lw)
        buf = io.BytesIO()
        base.save(buf, format='PNG')
        buf.seek(0)
        return buf.read()
    finally:
        base.close()


def _grid_font(size: int):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_percent_grid(input_bytes: bytes) -> bytes:
    """1% grid — hairline every 1%, brighter every 5%, bold+labelled every 10%.
    Grid is percentage-based, so downscaling the display thumbnail changes nothing
    about the coordinates the user reads off it."""
    base   = Image.open(io.BytesIO(input_bytes)).convert('RGB')
    base, _ = _downscale_preview(base)
    iw, ih = base.size
    ov     = Image.new('RGBA', (iw, ih), (0, 0, 0, 0))
    od     = ImageDraw.Draw(ov)
    font   = _grid_font(max(16, iw // 80))

    for p in range(0, 101):
        x = int(iw * p / 100)
        y = int(ih * p / 100)
        if p % 10 == 0:
            col, wd = (255, 255, 255, 200), 2
        elif p % 5 == 0:
            col, wd = (255, 255, 255, 100), 1
        else:
            col, wd = (255, 255, 255, 35), 1
        od.line([x, 0, x, ih], fill=col, width=wd)
        od.line([0, y, iw, y], fill=col, width=wd)
        if p % 10 == 0:
            od.rectangle([x + 2, 2, x + 46, 28], fill=(0, 0, 0, 170))
            od.text((x + 4, 4), str(p), fill=(0, 255, 255, 255), font=font)
            od.rectangle([2, y + 2, 50, y + 28], fill=(0, 0, 0, 170))
            od.text((4, y + 4), str(p), fill=(255, 200, 0, 255), font=font)

    out = Image.alpha_composite(base.convert('RGBA'), ov).convert('RGB')
    buf = io.BytesIO()
    out.save(buf, format='PNG')
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# OPACITY VIEW
# ══════════════════════════════════════════════════════════════════════════════

class DropMapOpacityView(discord.ui.View):
    def __init__(self, img_bytes: bytes, xpct: float, ypct: float, author_id: int,
                 logo_processor=process_image_manual, output_name: str = "dropmapwatermark",
                 placement_label: str = None, pattern_future=None):
        super().__init__(timeout=120)
        self.img_bytes       = img_bytes
        self.xpct            = xpct
        self.ypct            = ypct
        self.author_id       = author_id
        self.logo_processor  = logo_processor
        self.output_name     = output_name
        self.placement_label = placement_label
        # asyncio future building the full-strength watermark pattern in the
        # background (started right after the crop). Awaited at opacity time —
        # usually already done, so the heavy tile+rotate is hidden behind clicks.
        self.pattern_future  = pattern_future

    @discord.ui.button(label="📍 Normal (30%)", style=discord.ButtonStyle.primary)
    async def normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your request.", ephemeral=True)
            return
        await self._process(interaction, 76)

    @discord.ui.button(label="🌥️ Mid (26%)", style=discord.ButtonStyle.secondary)
    async def mid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your request.", ephemeral=True)
            return
        await self._process(interaction, 66)

    @discord.ui.button(label="❄️ Snow (23%)", style=discord.ButtonStyle.primary)
    async def snow(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your request.", ephemeral=True)
            return
        await self._process(interaction, 59)

    async def _process(self, interaction: discord.Interaction, opacity: int):
        await interaction.response.defer()
        pct = round(opacity / 255 * 100)
        try:
            logger.info("%s [%s]: watermark phase (%d%%)", self.output_name, interaction.user, pct)
            await interaction.edit_original_response(
                content=f"🎨 **[2/3] Applying watermark...** ({pct}% opacity)", view=None)
            # Use the background-built pattern if it's ready (the common case) so
            # only the cheap opacity-scale + composite run now. Falls back to
            # building inline if the precompute failed or wasn't started.
            pattern = None
            if self.pattern_future is not None:
                try:
                    pattern = await self.pattern_future
                except Exception:
                    logger.exception("%s: watermark precompute failed — building inline", self.output_name)
            watermarked = await interaction.client.loop.run_in_executor(
                None, functools.partial(process_watermark_only, self.img_bytes, opacity, pattern))
            logger.info("%s [%s]: watermark done — %d bytes", self.output_name, interaction.user, len(watermarked))

            logger.info("%s [%s]: logo phase (%.0f%%, %.0f%%)",
                        self.output_name, interaction.user, self.xpct * 100, self.ypct * 100)
            await interaction.edit_original_response(content="🖼️ **[3/3] Placing logo...**")
            final = await interaction.client.loop.run_in_executor(
                None, self.logo_processor, watermarked, self.xpct, self.ypct)
            logger.info("%s [%s]: logo done — %d bytes", self.output_name, interaction.user, len(final))

            loc  = self.placement_label or f"{self.xpct*100:.0f}%, {self.ypct*100:.0f}%"
            file = discord.File(io.BytesIO(final), filename=f"{self.output_name}.png")
            await interaction.edit_original_response(
                content=f"✅ **Done!** — {pct}% opacity, logo at {loc}",
                attachments=[file], view=None)
            logger.info("%s [%s]: complete", self.output_name, interaction.user)
        except Exception as e:
            logger.exception("%s post-process failed for %s", self.output_name, interaction.user)
            await interaction.edit_original_response(
                content=f"❌ Failed: `{str(e)[:200]}`", view=None)


# ══════════════════════════════════════════════════════════════════════════════
# PLACEMENT PREVIEW VIEW
# ══════════════════════════════════════════════════════════════════════════════

class PreviewConfirmView(discord.ui.View):
    """Confirm the logo placement, live-resize the centre logo (➖/➕), or restart
    the whole command from scratch.

    When ``resizable`` is True the view caches the rendered map bytes and redraws
    the red footprint box on every size change — no Playwright re-render. The
    chosen size lands in ``self.scale`` for the caller to bind into the final
    logo processor.
    """

    def __init__(self, author_id: int, *, png_bytes: bytes = None, xpct: float = None,
                 ypct: float = None, footprint_fn=None, coord_label: str = "",
                 scale: float = LOGO_CENTER_SCALE, resizable: bool = False,
                 step: float = 0.03, min_scale: float = 0.05, max_scale: float = 0.60):
        super().__init__(timeout=180)
        self.author_id    = author_id
        self.png_bytes    = png_bytes
        self.xpct         = xpct
        self.ypct         = ypct
        self.footprint_fn = footprint_fn
        self.coord_label  = coord_label
        self.scale        = scale
        self.resizable    = resizable
        self.step         = step
        self.min_scale    = min_scale
        self.max_scale    = max_scale
        self.result       = None  # 'confirm' | 'cancel' | None (timeout)
        self._redraw_token = 0    # monotonic — drops stale resize redraws (race guard)

        if resizable:
            smaller = discord.ui.Button(label="➖ Smaller", style=discord.ButtonStyle.secondary, row=0)
            bigger  = discord.ui.Button(label="➕ Bigger",  style=discord.ButtonStyle.secondary, row=0)
            smaller.callback = self._make_resize(-step)
            bigger.callback  = self._make_resize(+step)
            self.add_item(smaller)
            self.add_item(bigger)

    def caption(self) -> str:
        if self.resizable:
            return (f"👀 **Preview** — red box shows the logo at **{self.coord_label}**, "
                    f"size **{self.scale * 100:.0f}%** of width.\n"
                    "➖/➕ to resize  •  ✅ Confirm  •  ↩️ Re-place (pick a new spot).")
        return (f"👀 **Preview** — the red box shows where the logo will go & how big "
                f"(**{self.coord_label}**). Confirm, or re-place to pick a new spot.")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your request.", ephemeral=True)
            return False
        return True

    def _make_resize(self, delta: float):
        async def _cb(interaction: discord.Interaction):
            await interaction.response.defer()
            new = min(self.max_scale, max(self.min_scale, round(self.scale + delta, 4)))
            if abs(new - self.scale) < 1e-9:
                return  # already at a limit — nothing to redraw
            self.scale = new
            # Race guard: each click bumps the token. If a newer click lands while
            # this redraw is in the executor, the newer one wins and we drop this
            # stale edit — prevents out-of-order message updates from button mashing.
            self._redraw_token += 1
            token = self._redraw_token
            loop  = interaction.client.loop
            boxes = await loop.run_in_executor(
                None, self.footprint_fn, self.png_bytes, self.xpct, self.ypct, self.scale)
            prev  = await loop.run_in_executor(None, render_preview_box, self.png_bytes, boxes)
            if token != self._redraw_token:
                return  # superseded by a newer resize — discard this stale redraw
            file = discord.File(io.BytesIO(prev), filename="preview.png")
            await interaction.edit_original_response(
                content=self.caption(), attachments=[file], view=self)
        return _cb

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = 'confirm'
        await interaction.response.edit_message(
            content="✅ **Confirmed** — pick opacity next.", attachments=[], view=None)
        self.stop()

    @discord.ui.button(label="↩️ Re-place", style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.result = 'cancel'
        await interaction.response.edit_message(
            content="↩️ **Re-placing** — pick a new spot (reusing the render)...",
            attachments=[], view=None)
        self.stop()


# ══════════════════════════════════════════════════════════════════════════════
# FRAMING NUDGE  ("scroll-wheel fine touches")
# ══════════════════════════════════════════════════════════════════════════════
# The auto fit returns the FULL viewport screenshot. These helpers + view let the
# user zoom/pan the crop rectangle over that already-captured image — no Playwright
# re-render, just instant PIL crops. Zoom-in = tighter on the route (drops edge
# labels if they choose); zoom-out grows back toward the full viewport.

def make_framing_base(full_png: bytes, target_w: int = 1400):
    """One-time prep: decode the full screenshot, return a downscaled preview base
    (bytes) plus full-res dims and the preview scale factor."""
    img = Image.open(io.BytesIO(full_png)).convert('RGB')
    W, H = img.size
    scale = min(1.0, target_w / W)
    base = img.resize((max(1, int(W * scale)), max(1, int(H * scale)))) if scale < 1 else img.copy()
    img.close()
    buf = io.BytesIO()
    base.save(buf, format='PNG')
    base.close()
    return buf.getvalue(), W, H, scale


def render_framing_preview(base_png: bytes, rect_scaled) -> bytes:
    """Draw the crop rectangle (red) on the downscaled preview base."""
    base = Image.open(io.BytesIO(base_png)).convert('RGB')
    try:
        d  = ImageDraw.Draw(base)
        lw = max(3, base.width // 250)
        d.rectangle([int(v) for v in rect_scaled], outline=(255, 0, 0), width=lw)
        buf = io.BytesIO()
        base.save(buf, format='PNG')
        buf.seek(0)
        return buf.read()
    finally:
        base.close()


def crop_full(full_png: bytes, rect) -> bytes:
    """Crop the full-res screenshot to rect [x0,y0,x1,y1] (full-res px)."""
    img = Image.open(io.BytesIO(full_png)).convert('RGB')
    try:
        x0, y0, x1, y1 = [int(v) for v in rect]
        buf = io.BytesIO()
        img.crop((x0, y0, x1, y1)).save(buf, format='PNG')
        buf.seek(0)
        return buf.read()
    finally:
        img.close()


class FramingNudgeView(discord.ui.View):
    """Zoom/pan the final crop over the already-rendered full viewport (no re-render).

    ``rect`` is the crop rectangle in FULL-res px. On ✅ the chosen crop lands in
    ``self.result_bytes`` for the caller to use as the working image."""

    def __init__(self, author_id: int, full_png: bytes, base_png: bytes,
                 W: int, H: int, scale: float, init_rect):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.full_png  = full_png
        self.base_png  = base_png
        self.W, self.H = W, H
        self.scale     = scale
        self.rect      = list(init_rect)
        self.init_rect = list(init_rect)
        self.result_bytes = None
        self._tok = 0  # race guard — newest click wins

    def caption(self) -> str:
        rw = (self.rect[2] - self.rect[0]) / self.W * 100
        return (f"🔍 **Fine-tune the frame** — the red box is your final image "
                f"(**{rw:.0f}%** of the render width).\n"
                "➖/➕ zoom  •  ⬅️⬆️⬇️➡️ pan  •  ↺ reset  •  ✅ use this")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("This isn't your request.", ephemeral=True)
            return False
        return True

    def _clamp(self, r):
        x0, y0, x1, y1 = r
        w = min(x1 - x0, self.W)
        h = min(y1 - y0, self.H)
        x0 = max(0, min(x0, self.W - w)); y0 = max(0, min(y0, self.H - h))
        return [x0, y0, x0 + w, y0 + h]

    def _zoom(self, factor: float):
        x0, y0, x1, y1 = self.rect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = min((x1 - x0) * factor, self.W); h = min((y1 - y0) * factor, self.H)
        w = max(w, self.W * 0.1); h = max(h, self.H * 0.1)
        self.rect = self._clamp([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2])

    def _pan(self, dxf: float, dyf: float):
        x0, y0, x1, y1 = self.rect
        dx, dy = (x1 - x0) * dxf, (y1 - y0) * dyf
        self.rect = self._clamp([x0 + dx, y0 + dy, x1 + dx, y1 + dy])

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self._tok += 1; tok = self._tok
        loop = interaction.client.loop
        rs   = [v * self.scale for v in self.rect]
        prev = await loop.run_in_executor(None, render_framing_preview, self.base_png, rs)
        if tok != self._tok:
            return
        file = discord.File(io.BytesIO(prev), filename="framing.png")
        await interaction.edit_original_response(content=self.caption(), attachments=[file], view=self)

    @discord.ui.button(label="➖ Zoom out", style=discord.ButtonStyle.secondary, row=0)
    async def zoom_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._zoom(1.18); await self._refresh(interaction)

    @discord.ui.button(label="➕ Zoom in", style=discord.ButtonStyle.secondary, row=0)
    async def zoom_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._zoom(1 / 1.18); await self._refresh(interaction)

    @discord.ui.button(label="↺ Reset", style=discord.ButtonStyle.secondary, row=0)
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.rect = list(self.init_rect); await self._refresh(interaction)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary, row=1)
    async def pan_left(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._pan(-0.12, 0); await self._refresh(interaction)

    @discord.ui.button(label="⬆️", style=discord.ButtonStyle.primary, row=1)
    async def pan_up(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._pan(0, -0.12); await self._refresh(interaction)

    @discord.ui.button(label="⬇️", style=discord.ButtonStyle.primary, row=1)
    async def pan_down(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._pan(0, 0.12); await self._refresh(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary, row=1)
    async def pan_right(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._pan(0.12, 0); await self._refresh(interaction)

    @discord.ui.button(label="✅ Use this frame", style=discord.ButtonStyle.success, row=2)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        loop = interaction.client.loop
        self.result_bytes = await loop.run_in_executor(None, crop_full, self.full_png, self.rect)
        await interaction.edit_original_response(content="✅ **Frame locked in.**", attachments=[], view=None)
        self.stop()


class ViewportPickerView(discord.ui.View):
    """Pick the render viewport before rendering. Every preset renders at DPR 2;
    only the viewport width/height changes. 'Native' tracks the bot machine's own
    screen resolution. On timeout the caller defaults to Native."""

    def __init__(self, author_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.choice = None   # (label, w, h) once a button is clicked
        for label, w, h in VIEWPORT_PRESETS:
            self.add_item(self._make_button(label, w, h))

    def _make_button(self, label, w, h):
        style = discord.ButtonStyle.success if w is None else discord.ButtonStyle.primary
        btn = discord.ui.Button(label=label, style=style)

        async def _cb(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message("This isn't your request.", ephemeral=True)
                return
            rw, rh = _monitor_resolution() if w is None else (w, h)
            self.choice = (label, rw, rh)
            await interaction.response.defer()
            self.stop()

        btn.callback = _cb
        return btn


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class FullyReadyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Warm Chrome up in the background at startup so the FIRST >dmw/>lrw of the
        # session doesn't pay the ~2-4 s cold-launch. Runs on the render thread;
        # failures are harmless (the next real render just launches normally).
        try:
            _executor.submit(_persistent_browser)
        except Exception:
            pass

    def cog_unload(self):
        """Tear down the persistent browser on the render thread when the cog
        unloads, so Chrome doesn't leak across reloads."""
        try:
            _executor.submit(_shutdown_browser)
        except Exception:
            pass

    async def _framing_nudge(self, ctx, status_msg, full_png, cb, *, dpr=None):
        """Show the zoom/pan framing UI over the freshly-rendered full viewport.
        Starts framed exactly like the auto fit (content box + pad); the user can
        zoom in tighter or pan. Returns the chosen crop bytes, or None on timeout.

        dpr must match the DPR used to render full_png so CSS-px content-box
        coordinates are correctly mapped to physical pixel crop coordinates."""
        _dpr = dpr or RENDER_DPR
        loop = asyncio.get_event_loop()
        base_png, W, H, scale = await loop.run_in_executor(None, make_framing_base, full_png)
        pad = FIT_CROP_PAD * _dpr
        init_rect = [
            max(0, cb[0] * _dpr - pad),
            max(0, cb[1] * _dpr - pad),
            min(W, cb[2] * _dpr + pad),
            min(H, cb[3] * _dpr + pad),
        ]
        view = FramingNudgeView(ctx.author.id, full_png, base_png, W, H, scale, init_rect)
        rs   = [v * scale for v in init_rect]
        prev = await loop.run_in_executor(None, render_framing_preview, base_png, rs)
        try:
            await status_msg.delete()
        except Exception:
            pass
        msg = await ctx.send(
            view.caption(),
            file=discord.File(io.BytesIO(prev), filename="framing.png"),
            view=view,
        )
        await view.wait()
        if view.result_bytes is None:
            try:
                await msg.edit(content="⏰ Framing timed out.", attachments=[], view=None)
            except Exception:
                pass
            return None
        return view.result_bytes

    async def _watermark_flow(self, ctx, url, *, render_fn, logo_processor, footprint_fn,
                              output_name, bl_logo_processor=None, bl_footprint_fn=None,
                              br_logo_processor=None, br_footprint_fn=None,
                              resizable=False, raw_render_fn=None, render_dpr=None):
        """Shared pipeline: render fn.gg map ONCE → (optional framing nudge) → grid
        coords → placement preview (confirm / resize / re-place) → opacity picker.
        Re-place and typos reuse the render; only Playwright never repeats.

        render_fn         — render_and_crop (YOLO markers) or render_and_crop_dom (DOM bounds)
        raw_render_fn     — if set, the framing-nudge path: returns (full_png, content_box);
                            the user zooms/pans the crop before the grid step (no re-render)
        render_dpr        — DPR used by raw_render_fn; forwarded to _framing_nudge so
                            CSS-px content-box coords map correctly to physical pixels
        logo_processor    — process_image_manual (center+corner) or process_loot_route_logo (single)
        footprint_fn      — drop_map_footprint or loot_route_footprint (preview boxes)
        bl_logo_processor — if set, typing "BL" at the grid uses this (bottom-left shortcut)
        bl_footprint_fn   — preview footprint for the BL shortcut
        br_logo_processor — if set, typing "BR" at the grid uses this (bottom-right shortcut)
        br_footprint_fn   — preview footprint for the BR shortcut
        """
        if url is None:
            await ctx.send(f"Provide a fortnite.gg URL.  `>{output_name} https://fortnite.gg/...`")
            return
        url = url.strip().lstrip('<').rstrip('>').strip()
        if 'fortnite.gg' not in url:
            await ctx.send("That doesn't look like an fn.gg link.")
            return

        loop = asyncio.get_event_loop()

        # ── Viewport pick ──────────────────────────────────────────────────────
        # Both commands use the tight-fit path; let the user choose the render size
        # up front. All presets render at DPR 2 — only the viewport changes. The
        # chosen size rebuilds raw_render_fn so the rest of the flow is unchanged.
        if raw_render_fn is not None:
            picker   = ViewportPickerView(ctx.author.id)
            pick_msg = await ctx.send(
                "🖥️ **Pick render size** — all render at DPR 2; only the viewport changes.\n"
                "**Native** = this machine's screen  •  bigger = sharper but slower (4K is heaviest).",
                view=picker,
            )
            await picker.wait()
            label, vw, vh = picker.choice or ("Native", *_monitor_resolution())
            try:
                await pick_msg.delete()
            except Exception:
                pass
            raw_render_fn = functools.partial(_render_fit_raw, w=vw, h=vh, dpr=VIEWPORT_DPR)
            render_dpr    = VIEWPORT_DPR
            logger.info("%s [%s]: viewport %s (%d×%d @ DPR %g)",
                        output_name, ctx.author, label, vw, vh, VIEWPORT_DPR)

        def _check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        # ── [1/3] Render ONCE ──────────────────────────────────────────────────
        # Re-placing or a typo loops back to the grid and REUSES these bytes — only
        # the ~30 s Playwright render never repeats.
        logger.info("%s [%s]: render start — %s", output_name, ctx.author, url)
        status_msg = await ctx.send("🎯 **[1/3] Rendering map...** (~30 s)")
        png_bytes = None
        try:
            if raw_render_fn is not None:
                # Tight-fit path: render the full viewport + content box, then let the
                # user nudge the frame (zoom/pan) before anything else — no re-render.
                full_png, cb = await loop.run_in_executor(_executor, raw_render_fn, url)
                if full_png is not None and cb is not None:
                    png_bytes = await self._framing_nudge(ctx, status_msg, full_png, cb, dpr=render_dpr)
                    if png_bytes is None:   # timed out during framing
                        return
                else:
                    # fit unavailable — fall back to the legacy cropped render
                    png_bytes = await loop.run_in_executor(_executor, render_and_crop_dom, url)
            else:
                png_bytes = await loop.run_in_executor(_executor, render_fn, url)
            logger.info("%s [%s]: render done — %d bytes", output_name, ctx.author, len(png_bytes))
        except FileNotFoundError as e:
            await status_msg.edit(content=f"❌ Missing weights: {e}")
            return
        except RuntimeError as e:
            await status_msg.edit(content=f"❌ Detection failed: {e}")
            return
        except Exception as e:
            await status_msg.edit(content=f"❌ Error: {e}")
            logger.exception("%s render error", output_name)
            return
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Kick off the watermark pattern build NOW, in the background. It depends
        # only on the cropped image SIZE (not its content or the chosen opacity),
        # which is fixed from here on — so by the time the user picks an opacity it's
        # already done, hiding the ~10-12 s tile+rotate behind the grid/placement
        # clicks. Re-place reuses the same bytes, so the future stays valid.
        try:
            _wm_w, _wm_h   = Image.open(io.BytesIO(png_bytes)).size
            pattern_future = loop.run_in_executor(None, build_watermark_pattern, _wm_w, _wm_h)
        except Exception:
            pattern_future = None

        # Re-place loop: grid → preview, repeated on "Re-place"/typo (no re-render).
        while True:
            # ── Send grid ──────────────────────────────────────────────────────
            grid_bytes = await loop.run_in_executor(None, render_percent_grid, png_bytes)
            corner_hints = []
            if bl_logo_processor:
                corner_hints.append("`BL` for bottom-left")
            if br_logo_processor:
                corner_hints.append("`BR` for bottom-right")
            bl_hint = ("  •  or type " + "  •  or ".join(corner_hints)) if corner_hints else ""
            grid_msg   = await ctx.send(
                f"📐 **Reply with `X Y`** to place the logo (e.g. `50 40`){bl_hint}\n"
                "Cyan = X across  •  Orange = Y down",
                file=discord.File(io.BytesIO(grid_bytes), filename="grid.png")
            )
            logger.info("%s [%s]: grid sent, waiting for coords", output_name, ctx.author)

            # ── Wait for X Y reply ─────────────────────────────────────────────
            try:
                reply = await ctx.bot.wait_for('message', check=_check, timeout=120)
            except asyncio.TimeoutError:
                await grid_msg.edit(content="⏰ Timed out.", attachments=[], view=None)
                return

            # ── Parse placement (X Y, "BL" bottom-left, or "BR" bottom-right) ──
            content = reply.content.strip()
            if bl_logo_processor is not None and content.upper() == 'BL':
                x, y        = 0.0, 100.0
                coord_label = "bottom-left (BL)"
                active_logo = bl_logo_processor
                active_fp   = bl_footprint_fn
                logger.info("%s [%s]: placement BL (bottom-left)", output_name, ctx.author)
            elif br_logo_processor is not None and content.upper() == 'BR':
                x, y        = 100.0, 100.0
                coord_label = "bottom-right (BR)"
                active_logo = br_logo_processor
                active_fp   = br_footprint_fn
                logger.info("%s [%s]: placement BR (bottom-right)", output_name, ctx.author)
            else:
                parts = content.split()
                try:
                    x = float(parts[0].rstrip('%'))
                    y = float(parts[1].rstrip('%'))
                    if not (0 <= x <= 100 and 0 <= y <= 100):
                        raise ValueError
                except (IndexError, ValueError):
                    for _m in (reply, grid_msg):
                        try:
                            await _m.delete()
                        except Exception:
                            pass
                    corner_err = []
                    if bl_logo_processor:
                        corner_err.append("`BL` for bottom-left")
                    if br_logo_processor:
                        corner_err.append("`BR` for bottom-right")
                    corner_suffix = ("  or " + "  or ".join(corner_err) + ".") if corner_err else "."
                    await ctx.send(
                        "❌ Couldn't read that — reply with two numbers like `50 40`"
                        + corner_suffix
                        + " Let's try again.")
                    continue
                coord_label = f"{x:.0f}%, {y:.0f}%"
                active_logo = logo_processor
                active_fp   = footprint_fn
                logger.info("%s [%s]: coords %.0f%% %.0f%%", output_name, ctx.author, x, y)

            # ── Delete grid + reply ────────────────────────────────────────────
            try:
                await grid_msg.delete()
                await reply.delete()
            except Exception:
                pass

            # ── Placement preview (Confirm / Resize / Re-place) ────────────────
            can_resize    = resizable and active_logo is process_image_manual
            boxes         = await loop.run_in_executor(None, active_fp, png_bytes, x / 100.0, y / 100.0)
            preview_bytes = await loop.run_in_executor(None, render_preview_box, png_bytes, boxes)
            pview         = PreviewConfirmView(
                ctx.author.id,
                png_bytes=png_bytes, xpct=x / 100.0, ypct=y / 100.0,
                footprint_fn=active_fp, coord_label=coord_label, resizable=can_resize,
            )
            preview_msg   = await ctx.send(
                pview.caption(),
                file=discord.File(io.BytesIO(preview_bytes), filename="preview.png"),
                view=pview,
            )
            await pview.wait()

            if pview.result == 'confirm':
                logger.info("%s [%s]: preview confirmed (size %.0f%%)",
                            output_name, ctx.author, pview.scale * 100)
                if can_resize:
                    active_logo = functools.partial(process_image_manual, width_frac=pview.scale)
                    coord_label = f"{coord_label} · size {pview.scale * 100:.0f}%"
                break
            if pview.result == 'cancel':
                logger.info("%s [%s]: preview re-place (reusing render)", output_name, ctx.author)
                continue
            # Timeout
            logger.info("%s [%s]: preview timed out", output_name, ctx.author)
            try:
                await preview_msg.edit(content="⏰ Timed out.", attachments=[], view=None)
            except Exception:
                pass
            return

        # ── [2/3] Opacity picker ──────────────────────────────────────────────
        view = DropMapOpacityView(png_bytes, x / 100.0, y / 100.0, ctx.author.id,
                                  logo_processor=active_logo, output_name=output_name,
                                  placement_label=coord_label, pattern_future=pattern_future)
        await ctx.send(
            f"🎨 **[2/3] Pick watermark opacity** — logo at **{coord_label}**",
            view=view
        )

    @commands.command(name='dropmapwatermark', aliases=['dmw'])
    async def dropmapwatermark(self, ctx, url: str = None):
        """Render fn.gg map → grid coords → watermark + center & corner logos.
        Usage: >dropmapwatermark <fortnite.gg URL>
        """
        await self._watermark_flow(
            ctx, url,
            render_fn=render_and_crop_fit,
            raw_render_fn=_render_fit_raw,
            logo_processor=process_image_manual,
            footprint_fn=drop_map_footprint,
            output_name="dropmapwatermark",
            resizable=True,
        )

    @commands.command(name='lootroutewatermark', aliases=['lrw'])
    async def lootroutewatermark(self, ctx, url: str = None):
        """Render fn.gg route (DOM object detection) → grid coords → watermark +
        single small wave logo at chosen coords.
        Usage: >lootroutewatermark <fortnite.gg URL>
        """
        await self._watermark_flow(
            ctx, url,
            render_fn=render_and_crop_fit,
            raw_render_fn=_render_fit_raw,   # sized by the viewport picker (DPR 2)
            logo_processor=process_loot_route_logo,
            footprint_fn=loot_route_footprint,
            output_name="lootroutewatermark",
            bl_logo_processor=process_loot_route_logo_bl,
            bl_footprint_fn=loot_route_footprint_bl,
            br_logo_processor=process_loot_route_logo_br,
            br_footprint_fn=loot_route_footprint_br,
        )

    async def _raw_render_flow(self, ctx, url, *, render_fn, output_name):
        """Debug variant: render exactly like the watermark flow (same zoom-out /
        pan), but send the FULL uncropped viewport screenshot — no grid, no
        watermark — so the final zoom level is visible."""
        if url is None:
            await ctx.send(f"Provide a fortnite.gg URL.  `>{output_name} https://fortnite.gg/...`")
            return
        url = url.strip().lstrip('<').rstrip('>').strip()
        if 'fortnite.gg' not in url:
            await ctx.send("That doesn't look like an fn.gg link.")
            return

        loop = asyncio.get_event_loop()
        logger.info("%s [%s]: raw render start — %s", output_name, ctx.author, url)
        status_msg = await ctx.send("🎯 **Rendering map (uncropped)...** (~30 s)")
        try:
            png_bytes = await loop.run_in_executor(
                _executor, functools.partial(render_fn, url, crop=False))
            logger.info("%s [%s]: raw render done — %d bytes", output_name, ctx.author, len(png_bytes))
        except Exception as e:
            await status_msg.edit(content=f"❌ Error: {e}")
            logger.exception("%s render error", output_name)
            return
        await status_msg.delete()

        def _to_jpeg(data: bytes) -> bytes:
            img = Image.open(io.BytesIO(data)).convert('RGB')
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            img.close()
            return buf.getvalue()

        filename = "raw_render.png"
        if len(png_bytes) > 9_500_000:  # full DPR-3 screenshot can exceed Discord's 10 MB cap
            png_bytes = await loop.run_in_executor(None, _to_jpeg, png_bytes)
            filename  = "raw_render.jpg"
        await ctx.send(
            f"🖼️ Full uncropped render — `{output_name}`",
            file=discord.File(io.BytesIO(png_bytes), filename=filename),
        )

    @commands.command(name='rawdropmapwatermark', aliases=['rawdmw'])
    async def rawdropmapwatermark(self, ctx, url: str = None):
        """Render fn.gg map exactly like >dmw but send the full uncropped screenshot.
        Usage: >rawdropmapwatermark <fortnite.gg URL>
        """
        await self._raw_render_flow(ctx, url, render_fn=render_and_crop_fit,
                                    output_name="rawdropmapwatermark")

    @commands.command(name='rawlootroutewatermark', aliases=['rawlrw'])
    async def rawlootroutewatermark(self, ctx, url: str = None):
        """Render fn.gg route exactly like >lrw (same fit) but send the full
        uncropped screenshot so the zoom level is visible.
        Usage: >rawlootroutewatermark <fortnite.gg URL>
        """
        await self._raw_render_flow(ctx, url, render_fn=render_and_crop_fit,
                                    output_name="rawlootroutewatermark")

    @commands.command(name='zoomtest', aliases=['zt'])
    async def zoomtest(self, ctx, url: str = None, step: float = 0.5):
        """Render an fn.gg route at 5 zoom levels (2 out · normal · 2 in) and post
        them all, so you can see which zoom looks right. Screenshot only — no
        watermark, no logo, no crop. Standalone; does NOT affect >lrw / >dmw.
        Usage: >zoomtest <fortnite.gg URL> [step]   (step default 0.5)
        """
        if url is None:
            await ctx.send("Provide a fortnite.gg URL.  `>zoomtest https://fortnite.gg/...  [step]`")
            return
        url = url.strip().lstrip('<').rstrip('>').strip()
        if 'fortnite.gg' not in url:
            await ctx.send("That doesn't look like an fn.gg link.")
            return
        try:
            step = max(0.1, min(2.0, float(step)))
        except (TypeError, ValueError):
            step = 0.5

        loop = asyncio.get_event_loop()
        status = await ctx.send(f"🔎 **Rendering 5 zoom levels** (step {step})… (~40 s)")
        try:
            shots = await loop.run_in_executor(
                _executor, functools.partial(render_zoom_ladder, url, step))
        except Exception as e:
            await status.edit(content=f"❌ Error: {e}")
            logger.exception("zoomtest render error")
            return
        if not shots:
            await status.edit(content="❌ Nothing rendered.")
            return
        try:
            await status.delete()
        except Exception:
            pass

        files, lines = [], []
        for i, (d, z, jpg) in enumerate(shots, 1):
            if abs(d) < 1e-9:
                tag, name = "⭐ NORMAL (what `>lrw` uses)", f"{i}_NORMAL.jpg"
            elif d < 0:
                tag, name = f"zoomed OUT  ({d})", f"{i}_out_{abs(d)}.jpg"
            else:
                tag, name = f"zoomed IN  (+{d})", f"{i}_in_{d}.jpg"
            files.append(discord.File(io.BytesIO(jpg), filename=name))
            lines.append(f"**{i}.** {tag}  ·  map zoom `{z:.2f}`")
        await ctx.send(
            "🔎 **Zoom ladder** — most zoomed-out → most zoomed-in. "
            "Tell me which number looks right and I'll set `>lrw`/`>dmw` to it:\n"
            + "\n".join(lines),
            files=files,
        )


async def setup(bot):
    await bot.add_cog(FullyReadyCog(bot))
    logger.info("✅ FullyReadyCog loaded")
