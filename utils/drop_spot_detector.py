"""
Local YOLO detectors for watermark placement.

Two on-device models, lazy-loaded and thread-safe. Both answer the same question
from different angles — "where is the important content the watermark must NOT cover?"

  • weights/drop_spot_marker.pt  (detect)  — drop spot + marker bounding boxes
        classes: {0: 'Drop-spot-detection', 1: 'Marker'}
  • weights/glider_lines.pt      (segment) — glider / flight-path line pixel masks
        classes: {0: 'Glider line'}

Pipeline (matches image_editor.paste_center_logo): detect the drop spot/marker first,
then segment the glider lines; both feed the placement "avoid" map.

Public surface consumed by image_editor.py:
  • detect_drop_spot(img)      -> (cx, cy, w, h) | None        place the stamp ABOVE this box
  • detect_boxes(img)          -> [(cx, cy, w, h), ...]        every drop-spot/marker box (avoid)
  • glider_line_mask(img)      -> np.ndarray[bool] (H×W) | None True = glider pixel, keep clear
  • detect_text_boxes(img)     -> [(x1, y1, x2, y2), ...]      on-map text boxes (avoid, easyocr)
  • is_available()             -> bool                         drop-spot model loadable?

Both .pt files live in weights/ and are tracked via Git LFS (.gitattributes).
Replaces the retired single-class models/drop_spot_detector.pt (yolo26x).
"""
import logging
import os
import threading
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger('discord')

# ==================== CONFIG ====================
# Weights were ARCHIVED 2026-06 to ai-hub/deprecated/yolo-watermark-detector/weights/
# when this detector was parked (framing now uses fn.gg window.Drawing — see
# commands/auto_watermark.py:render_and_crop_fit). This file is in utils/, so go up
# one level to the repo root, then into the archive. Only consulted if the detector
# is reactivated (env WMB_YOLO_DETECTOR=1).
_REPO_ROOT           = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WEIGHTS_DIR         = os.path.join(_REPO_ROOT, "ai-hub", "deprecated", "yolo-watermark-detector", "weights")
DROP_SPOT_MODEL_PATH = os.path.join(_WEIGHTS_DIR, "drop_spot_marker.pt")  # detect: Drop-spot-detection, Marker
GLIDER_MODEL_PATH    = os.path.join(_WEIGHTS_DIR, "glider_lines.pt")      # segment: Glider line

INFERENCE_IMGSZ      = 1280   # both models trained at 1280
CONFIDENCE_THRESHOLD = 0.30   # min confidence for a drop-spot/marker box (0.0-1.0)
GLIDER_CONFIDENCE    = 0.30   # min confidence for a glider-line mask

# ==================== KILL SWITCH (parked 2026-06) ====================
# The watermark commands now frame from fn.gg's own window.Drawing data + Leaflet
# fitBounds (see commands/auto_watermark.py:render_and_crop_fit), so these YOLO
# detectors are no longer used. Parked so they never import ultralytics / load the
# ~210 MB weights → zero CPU/RAM at idle. To REACTIVATE: set env WMB_YOLO_DETECTOR=1
# (or flip the default below to "1"). _get_model() short-circuits when disabled.
DETECTOR_ENABLED = os.environ.get("WMB_YOLO_DETECTOR", "0") == "1"
_disabled_logged = False

# ==================== LAZY MODEL LOADS ====================
# Keyed by path so the same loader serves both models. A path maps to a YOLO
# instance once loaded, or lands in _load_failed so we never retry a bad load.
_models: dict = {}
_load_failed: set = set()
_lock = threading.Lock()


def _get_model(path: str):
    """Lazy-load a YOLO model by path. Thread-safe; caches success and failure."""
    # Parked: bail before importing ultralytics or loading any weights → no CPU/RAM.
    if not DETECTOR_ENABLED:
        global _disabled_logged
        if not _disabled_logged:
            logger.info("YOLO drop-spot detector is parked (WMB_YOLO_DETECTOR off) — using fn.gg window.Drawing instead.")
            _disabled_logged = True
        return None
    if path in _models:
        return _models[path]
    if path in _load_failed:
        return None

    with _lock:
        # Re-check after acquiring the lock
        if path in _models:
            return _models[path]
        if path in _load_failed:
            return None

        try:
            if not os.path.exists(path):
                logger.warning(f"YOLO model not found at {path} - detector disabled for this model")
                _load_failed.add(path)
                return None

            from ultralytics import YOLO
            logger.info(f"Loading YOLO model from {path} ...")
            model = YOLO(path)
            _models[path] = model
            logger.info(f"Loaded YOLO model: {os.path.basename(path)} (task={model.task})")
            return model

        except ImportError:
            logger.warning("ultralytics not installed - local detection disabled. Run: pip install ultralytics")
            _load_failed.add(path)
            return None
        except Exception as e:
            logger.error(f"Failed to load YOLO model {path}: {e}")
            _load_failed.add(path)
            return None


def _as_rgb(img):
    """YOLO predicts cleanest on 3-channel RGB; the editor hands us RGBA bases."""
    return img.convert('RGB') if hasattr(img, 'convert') else img


def is_available() -> bool:
    """True if the primary drop-spot detector can be used."""
    return _get_model(DROP_SPOT_MODEL_PATH) is not None


# ==================== DROP SPOT DETECTION ====================
def detect_drop_spot(img) -> Optional[Tuple[float, float, float, float]]:
    """
    Highest-confidence drop-spot/marker box as (cx, cy, w, h) in original pixel space, or None.

    Drop-in replacement for the retired Roboflow-API version — same signature and return shape.
    """
    model = _get_model(DROP_SPOT_MODEL_PATH)
    if model is None:
        return None

    try:
        results = model.predict(
            source=_as_rgb(img),
            imgsz=INFERENCE_IMGSZ,
            conf=CONFIDENCE_THRESHOLD,
            verbose=False,
            save=False,
        )
        if not results:
            return None

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return None

        boxes = result.boxes.xywh.cpu().numpy()   # (cx, cy, w, h)
        confs = result.boxes.conf.cpu().numpy()
        clss  = result.boxes.cls.cpu().numpy().astype(int)
        names = result.names

        # "The drop spot" = the Drop-spot-detection class. Anchor on the most-confident
        # one; only fall back to other classes (e.g. Marker pins) if no drop-spot box hit.
        ds_pool = [i for i in range(len(clss)) if str(names.get(int(clss[i]), "")).lower().startswith("drop")]
        pool = ds_pool if ds_pool else list(range(len(confs)))
        best_idx = max(pool, key=lambda i: confs[i])
        cx, cy, w, h = boxes[best_idx]

        logger.info(f"Drop spot detected (local) '{names.get(int(clss[best_idx]), '?')}' at ({cx:.0f}, {cy:.0f}) conf={confs[best_idx]:.2f}")
        return float(cx), float(cy), float(w), float(h)

    except Exception as e:
        logger.warning(f"Local drop-spot detection failed: {e}")
        return None


def detect_boxes(img, conf_threshold: float = None) -> List[Tuple[float, float, float, float]]:
    """Every detection box (drop spots + markers, any class) as (cx, cy, w, h).

    Feeds the placement avoid map — the logo must not cover a drop spot or a marker pin.
    Empty list if nothing found or the model is unavailable.
    """
    model = _get_model(DROP_SPOT_MODEL_PATH)
    if model is None:
        return []

    threshold = conf_threshold if conf_threshold is not None else CONFIDENCE_THRESHOLD
    try:
        results = model.predict(
            source=_as_rgb(img),
            imgsz=INFERENCE_IMGSZ,
            conf=threshold,
            verbose=False,
            save=False,
        )
        if not results:
            return []
        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            return []
        boxes = result.boxes.xywh.cpu().numpy()
        return [(float(b[0]), float(b[1]), float(b[2]), float(b[3])) for b in boxes]
    except Exception as e:
        logger.warning(f"Local box detection failed: {e}")
        return []


# ==================== GLIDER LINE SEGMENTATION ====================
def glider_line_mask(img, conf_threshold: float = None) -> Optional[np.ndarray]:
    """
    Segment glider lines and return a full-image boolean mask (True = glider-line pixel),
    sized to the ORIGINAL image as (H, W) so it lines up with image_editor's edge map.

    Masks ONLY — reads result.masks and never the segmentation model's bounding boxes.
    Returns None if the segmentation model is unavailable or nothing was found.
    Consumed as an "avoid" map: the watermark/stamp must not be placed over these pixels.
    """
    model = _get_model(GLIDER_MODEL_PATH)
    if model is None:
        return None

    threshold = conf_threshold if conf_threshold is not None else GLIDER_CONFIDENCE

    try:
        results = model.predict(
            source=_as_rgb(img),
            imgsz=INFERENCE_IMGSZ,
            conf=threshold,
            verbose=False,
            save=False,
            retina_masks=True,   # upsample masks to native resolution
        )
        if not results:
            return None

        result = results[0]
        if result.masks is None or len(result.masks) == 0:
            return None

        # masks.data: (N, mh, mw) in {0,1}. OR every instance into one coverage mask.
        data = result.masks.data.cpu().numpy()
        combined = data.any(axis=0)  # (mh, mw) bool

        # Target shape is (H, W) so it lines up with the placement avoid map.
        oh, ow = (img.size[1], img.size[0]) if hasattr(img, "size") else result.orig_shape[:2]
        if combined.shape != (oh, ow):
            from PIL import Image as _Image
            resized = _Image.fromarray((combined * 255).astype(np.uint8)).resize((ow, oh), _Image.NEAREST)
            combined = np.array(resized) > 127

        logger.info(f"Glider lines segmented (local): {len(data)} instance(s), {int(combined.sum())} px")
        return combined.astype(bool)

    except Exception as e:
        logger.warning(f"Local glider-line segmentation failed: {e}")
        return None


# ==================== TEXT DETECTION (easyocr) ====================
_ocr_reader = None
_ocr_failed = False


def _get_ocr():
    """Lazy-load the easyocr reader once (like the YOLO models). Thread-safe."""
    global _ocr_reader, _ocr_failed
    if _ocr_reader is not None:
        return _ocr_reader
    if _ocr_failed:
        return None
    with _lock:
        if _ocr_reader is not None:
            return _ocr_reader
        if _ocr_failed:
            return None
        try:
            import easyocr
            logger.info("Loading easyocr reader for on-map text detection...")
            _ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            logger.info("easyocr reader loaded")
            return _ocr_reader
        except ImportError:
            logger.warning("easyocr not installed - text avoidance disabled. Run: pip install easyocr")
            _ocr_failed = True
            return None
        except Exception as e:
            logger.error(f"Failed to load easyocr: {e}")
            _ocr_failed = True
            return None


def detect_text_boxes(img) -> List[Tuple[int, int, int, int]]:
    """Detect on-map text and return TIGHT boxes as (x1, y1, x2, y2) pixel corners.

    Uses easyocr's detect() (box localisation only, no character recognition) — faster,
    and we only need where the text is, not what it says. Empty list if easyocr is
    unavailable. The boxes are easyocr's exact detected bounds — no padding added.
    """
    reader = _get_ocr()
    if reader is None:
        return []
    try:
        arr = np.array(img.convert('RGB')) if hasattr(img, 'convert') else np.array(img)
        horizontal, free = reader.detect(arr)
        boxes = []
        # horizontal_list[0]: axis-aligned boxes as [x_min, x_max, y_min, y_max]
        for b in (horizontal[0] if horizontal else []):
            x0, x1, y0, y1 = (int(v) for v in b)
            boxes.append((x0, y0, x1, y1))
        # free_list[0]: rotated text as 4-point polygons -> take tight bounds
        for poly in (free[0] if free else []):
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            boxes.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
        if boxes:
            logger.info(f"Text detected (easyocr): {len(boxes)} box(es)")
        return boxes
    except Exception as e:
        logger.warning(f"Text detection failed: {e}")
        return []
