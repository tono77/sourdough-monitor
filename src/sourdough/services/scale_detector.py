"""Scale detection — reads the ml scale printed on the jar for absolute calibration.

Detects the regular pattern of horizontal tick marks on the jar's side, giving a
pixel→ml spacing. The absolute anchor is supplied separately: the user's red band
is placed at 300ml by convention, so `y_to_ml(y, scale, band_y=..., band_ml=300)`
converts any pixel y to ml.

Returns None when the scale cannot be detected (e.g. dark overnight photos).
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# The jar's red elastic band is placed at this ml value by convention
BAND_ML = 300.0

# Expected 50ml spacing range in pixels (camera zoom dependent)
MAJOR_SPACING_MIN = 60.0
MAJOR_SPACING_MAX = 130.0


def detect_scale(photo_path: str) -> Optional[dict]:
    """Detect the ml scale from a jar photo.

    Returns a dict with keys:
        px_per_50ml: float, pixels per 50ml (from major tick spacing)
        top_tick_y:  int, topmost detected tick (informational; unreliable anchor)
        tick_ys:     list[int], all detected tick y-coords (sorted top→bottom)
        n_ticks:     int, total number of ticks
        regularity:  float, 0-1 score for how regular the tick grid is

    Returns None if the scale cannot be reliably detected.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    img = cv2.imread(photo_path)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    band_y = _detect_band_y(img)

    ticks = _detect_tick_candidates(gray)
    if len(ticks) < 6:
        return None

    cluster = _pick_scale_cluster(ticks)
    if cluster is None:
        return None

    calib = _calibrate(cluster)
    if calib is None:
        return None

    # Sanity check: reject implausible spacing
    if not (MAJOR_SPACING_MIN <= calib["px_per_50ml"] <= MAJOR_SPACING_MAX):
        log.debug("Scale rejected: px_per_50ml=%.1f outside [%.0f, %.0f]",
                  calib["px_per_50ml"], MAJOR_SPACING_MIN, MAJOR_SPACING_MAX)
        return None

    calib["band_y"] = band_y  # may be None if band not detected
    log.info("Escala detectada: 50ml=%.1fpx, n=%d, reg=%.2f (top_y=%d, band_y=%s)",
             calib["px_per_50ml"], calib["n_ticks"],
             calib["regularity"], calib["top_tick_y"], band_y)
    return calib


def y_to_ml(y: float, scale: dict, band_y: float, band_ml: float = BAND_ML) -> float:
    """Convert a pixel y-coordinate to ml using the detected scale + band anchor.

    The band_y is the pixel y of the red elastic band (detected or calibrated),
    which by convention sits at 300ml on the jar.
    """
    delta_y = y - band_y
    return band_ml - (delta_y / scale["px_per_50ml"]) * 50.0


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _detect_band_y(img) -> Optional[int]:
    """Detect the red elastic band's pixel y-coord in the image.

    Restricts search to the horizontal center of the image (jar body) and the
    vertical middle-to-lower region (avoids reddish wooden artwork at the top
    and any table clutter at the bottom).
    """
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    y_start, y_end = int(h * 0.40), int(h * 0.90)
    x_start, x_end = int(w * 0.30), int(w * 0.70)
    roi = img[y_start:y_end, x_start:x_end]

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    # Elastic band red is vivid/saturated; tighten thresholds to exclude wood tones.
    red_mask1 = cv2.inRange(hsv, np.array([0, 140, 90]), np.array([10, 255, 255]))
    red_mask2 = cv2.inRange(hsv, np.array([170, 140, 90]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(red_mask1, red_mask2)

    # Require a row to have enough red pixels to count as "band"
    row_counts = red_mask.sum(axis=1) // 255
    min_width = int((x_end - x_start) * 0.15)
    band_rows = np.where(row_counts >= min_width)[0]
    if len(band_rows) < 5:
        return None
    return int(np.median(band_rows)) + y_start


def _detect_tick_candidates(gray) -> list[dict]:
    """Find horizontal tick-mark blobs via morphology + connected components."""
    import cv2
    import numpy as np

    h, w = gray.shape
    x0, x1 = int(w * 0.20), int(w * 0.80)
    y0, y1 = int(h * 0.10), int(h * 0.90)
    roi = gray[y0:y1, x0:x1]

    bw = cv2.adaptiveThreshold(
        roi, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV,
        blockSize=25, C=10,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 1))
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)

    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    ticks = []
    for i in range(1, n_labels):
        x, y, cw, ch, area = stats[i]
        if not (8 <= cw <= 80 and 1 <= ch <= 6 and area < cw * 6):
            continue
        ticks.append({
            "y": y0 + y + ch // 2,
            "x_left": x0 + x,
            "x_right": x0 + x + cw,
            "width": cw,
        })
    ticks.sort(key=lambda t: t["y"])

    # Merge ticks that are vertically adjacent and overlap horizontally
    merged = []
    for t in ticks:
        if merged and abs(t["y"] - merged[-1]["y"]) <= 3:
            prev = merged[-1]
            if not (t["x_right"] < prev["x_left"] or t["x_left"] > prev["x_right"]):
                prev["y"] = (prev["y"] + t["y"]) // 2
                prev["x_left"] = min(prev["x_left"], t["x_left"])
                prev["x_right"] = max(prev["x_right"], t["x_right"])
                prev["width"] = prev["x_right"] - prev["x_left"]
                continue
        merged.append(t)
    return merged


def _pick_scale_cluster(ticks: list[dict]) -> list[dict] | None:
    """Score tick clusters sharing an x_left by regularity; return the best."""
    import numpy as np

    if not ticks:
        return None

    xs = np.array([t["x_left"] for t in ticks])
    x_min, x_max = int(xs.min()), int(xs.max())
    hist = np.zeros(x_max - x_min + 1, dtype=int)
    for x in xs:
        hist[int(x) - x_min] += 1
    smoothed = np.convolve(hist, np.ones(5), mode="same")

    candidate_xs = np.argsort(smoothed)[::-1][:15] + x_min
    best_score, best_cluster = 0.0, None
    for peak_x in candidate_xs:
        cluster = [t for t in ticks if abs(t["x_left"] - peak_x) <= 5]
        if len(cluster) < 6:
            continue
        cluster.sort(key=lambda t: t["y"])
        ys = np.array([t["y"] for t in cluster])
        diffs = np.diff(ys)
        if len(diffs) < 3:
            continue
        med = float(np.median(diffs))
        if med < 8 or med > 150:
            continue
        regular = 0
        for d in diffs:
            for mult in (1, 2, 3, 4, 5):
                if abs(d - med * mult) / (med * mult) < 0.25:
                    regular += 1
                    break
        regularity = regular / len(diffs)
        if regularity < 0.7:
            continue
        score = len(cluster) * regularity
        if score > best_score:
            best_score = score
            best_cluster = cluster
    return best_cluster


def _calibrate(cluster: list[dict]) -> dict | None:
    """From a cluster of ticks, derive 50ml pixel spacing and the top tick y."""
    import numpy as np

    widths = np.array([t["width"] for t in cluster])
    ys = np.array([t["y"] for t in cluster])

    # Major ticks have larger extent than minors. Use the widest ~35% as majors.
    w_thresh = np.percentile(widths, 65)
    major_mask = widths >= w_thresh
    major_ys = np.sort(ys[major_mask]) if major_mask.sum() >= 3 else np.sort(ys)
    if len(major_ys) < 3:
        return None

    diffs = np.diff(major_ys)
    # 50ml spacing: use the MEDIAN of differences — this is the major-to-major gap
    # when the widths-based classification was correct. If the dough hides some,
    # the median still reflects 50ml.
    px_per_50ml = float(np.median(diffs))

    all_diffs = np.diff(np.sort(ys))
    med_all = float(np.median(all_diffs))
    regular = sum(
        1 for d in all_diffs
        if any(abs(d - med_all * k) / (med_all * k) < 0.25 for k in (1, 2, 3, 4, 5))
    )
    regularity = regular / max(len(all_diffs), 1)

    return {
        "top_tick_y": int(ys.min()),
        "tick_ys": [int(y) for y in sorted(ys.tolist())],
        "px_per_50ml": px_per_50ml,
        "n_ticks": len(cluster),
        "regularity": round(regularity, 3),
    }
