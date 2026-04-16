"""Claude Vision analysis + OpenCV fallback.

Prompts are defined as module-level constants.
All dependencies (config, calibration) are passed as parameters.
"""

import base64
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

import requests

from sourdough.config import AppConfig
from sourdough.models import CalibrationBounds

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts (Spanish)
# ---------------------------------------------------------------------------

PROMPT_UNIFIED = """Eres un experto midiendo la altura de masa madre en un frasco de vidrio.

{baseline_context}

{crop_context}TAREA: Mide la posición de la SUPERFICIE de la masa en el frasco.
- 0% = el FONDO de la imagen (fondo del frasco)
- 100% = el TOPE de la imagen (tapa del frasco)

{calibration_context}{corrections_context}
IMPORTANTE: La masa madre es una sustancia BLANCA/CREMA que llena el frasco desde el fondo hacia arriba.
Puede ser translúcida — se pueden ver las marcas del vidrio A TRAVÉS de ella. No confundas la masa
con vidrio vacío. La masa termina donde se ve el vidrio claramente vacío (sin contenido detrás).

MÉTODO:
1. Busca la banda elástica roja como REFERENCIA visual fija.
2. Identifica dónde está la superficie de la MASA SÓLIDA (no la espuma).
   IMPORTANTE: La masa madre suele tener burbujas grandes en la parte superior.
   NO midas el tope de las burbujas — mide el último nivel continuo de masa sólida,
   donde termina el cuerpo denso y empiezan las burbujas grandes o la espuma.
3. Estima la posición como porcentaje del RECORRIDO VERTICAL entre el fondo y el tope de la imagen.
   IGNORA los números de mililitros (ml) impresos en el vidrio — NO son porcentajes.
   Usa las rayitas como referencia de distancia relativa, NO sus valores numéricos.
4. VERIFICACIÓN: si la masa está SOBRE la banda roja, altura_pct DEBE ser mayor que banda_pct.
   Si la masa está BAJO la banda roja, altura_pct DEBE ser menor que banda_pct.

Responde SOLO con JSON válido:
{{
  "altura_pct": <posición de la superficie de la masa, 0-100, ej: 45.0>,
  "banda_pct": <posición de la banda elástica roja, 0-100, ej: 30.0>,
  "burbujas": "<ninguna|pocas|muchas>",
  "textura": "<lisa|rugosa|muy_activa>",
  "notas": "<observación breve en español, máx 80 chars>",
  "confianza": <1-5>
}}
Si no puedes ver el frasco claramente, usa altura_pct: null."""


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _crop_to_jar(photo_path: str, calibration: "CalibrationBounds | None") -> str | None:
    """Crop image to jar region using calibration bounds. Returns path or None."""
    if not calibration or not calibration.is_complete:
        return None
    try:
        import cv2
        img = cv2.imread(photo_path)
        if img is None:
            return None
        h, w = img.shape[:2]
        # Add small margin around calibration bounds
        margin_x = int(w * 0.02)
        margin_y = int(h * 0.02)
        x1 = max(0, int(w * calibration.izq_x_pct / 100) - margin_x)
        x2 = min(w, int(w * calibration.der_x_pct / 100) + margin_x)
        y1 = max(0, int(h * calibration.tope_y_pct / 100) - margin_y)
        y2 = min(h, int(h * calibration.base_y_pct / 100) + margin_y)
        cropped = img[y1:y2, x1:x2]
        if cropped.size == 0:
            return None
        crop_path = photo_path.replace(".jpg", "_cropped.jpg")
        cv2.imwrite(crop_path, cropped)
        return crop_path
    except Exception as e:
        log.warning("Crop failed: %s", e)
        return None


def _compress_image(photo_path: str, target_size_mb: float = 3) -> str:
    compressed = photo_path.replace(".jpg", "_compressed.jpg")
    quality = 85
    for _ in range(5):
        subprocess.run(
            ["ffmpeg", "-i", photo_path, "-q:v", str(quality), "-y", compressed],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )
        if os.path.exists(compressed) and os.path.getsize(compressed) / (1024 * 1024) < target_size_mb:
            return compressed
        quality -= 5
    return compressed


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _detect_media_type(photo_path: str) -> str:
    ext = Path(photo_path).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(ext, "image/jpeg")


def _load_corrections(corrections_file: Path) -> str:
    """Build corrections context string from dataset_corrections.json."""
    if not corrections_file.exists():
        return ""
    try:
        with open(corrections_file) as f:
            corrections = json.load(f)
        if not corrections:
            return ""
        recent = corrections[-3:]
        lines = ["CORRECCIONES MANUALES RECIENTES (posición absoluta en frasco):"]
        for c in recent:
            ts = c.get("timestamp", "").split("T")[-1][:5]
            # Prefer altura_pct (absolute position) over nivel_pct (growth)
            altura = c.get("altura_pct_corrected") or c.get("altura_pct")
            if altura is not None:
                lines.append(f"- A las {ts}, la posición real de la masa en el frasco era: {altura}%.")
            else:
                # Fallback: nivel_pct is growth, not useful for absolute position
                pass
        if len(lines) <= 1:
            return ""
        lines.append("\nUsa estas referencias para calibrar tu lectura de la foto actual.\n")
        return "\n".join(lines)
    except Exception:
        return ""


def _parse_response(text: str) -> dict:
    """Extract JSON from Claude's response, stripping markdown fences."""
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)


# ---------------------------------------------------------------------------
# OpenCV fallback
# ---------------------------------------------------------------------------

def run_opencv(photo_path: str, calibration: CalibrationBounds) -> Optional[float]:
    """Texture + color CV analysis. Returns surface position (0-100% of jar) or None.

    Uses row-wise texture (std of brightness) as the primary signal to distinguish
    dough (textured, opaque) from empty glass (smooth, shows background).
    Color mask provides secondary validation.

    Key insight: dough has high row std (bubbles, texture), empty glass has low std.
    This is lighting-independent — works day, night, and with flash.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    if not calibration.is_complete:
        return None

    img = cv2.imread(photo_path)
    if img is None:
        return None

    height, width = img.shape[:2]
    izq = int(width * (calibration.izq_x_pct / 100.0))
    der = int(width * (calibration.der_x_pct / 100.0))
    base = int(height * (calibration.base_y_pct / 100.0))
    tope = int(height * (calibration.tope_y_pct / 100.0))

    if izq >= der or tope >= base:
        return None

    cropped = img[tope:base, izq:der]
    if cropped.size == 0:
        return None

    crop_h, crop_w = cropped.shape[:2]
    hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

    # --- Auto-detect lid boundary ---
    center_margin = int(crop_w * 0.15)
    center_gray = gray[:, center_margin:crop_w - center_margin]
    center_hsv = hsv[:, center_margin:crop_w - center_margin]
    lid_end = 0
    search_limit = min(int(crop_h * 0.20), crop_h)
    for row in range(search_limit):
        v_mean = float(np.mean(center_hsv[row, :, 2]))
        row_std = float(np.std(center_gray[row, :].astype(float)))
        if v_mean < 130 and row_std > 40:
            lid_end = row
    lid_end += 1

    # --- Detect red band ---
    red_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([10, 255, 255]))
    red_mask2 = cv2.inRange(hsv, np.array([170, 80, 80]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(red_mask1, red_mask2)
    red_rows = np.where(red_mask.any(axis=1))[0]
    detected_band_y = int(np.median(red_rows)) if len(red_rows) > 10 else None

    band_y_crop = None
    if calibration.fondo_y_pct is not None:
        band_y_crop = int(height * (calibration.fondo_y_pct / 100.0)) - tope
    elif detected_band_y is not None:
        band_y_crop = detected_band_y

    band_margin = max(15, int(crop_h * 0.05))
    b_start = max(0, band_y_crop - band_margin) if band_y_crop else 0
    b_end = min(crop_h, band_y_crop + band_margin) if band_y_crop else 0

    # --- Per-row texture score ---
    # Dough: high row std (45-65) due to bubbles, texture, grain
    # Empty glass: low row std (20-35) — uniform wall/background visible
    window = 2
    row_texture = np.zeros(crop_h)
    for i in range(crop_h):
        r1 = max(0, i - window)
        r2 = min(crop_h, i + window + 1)
        row_texture[i] = np.mean([
            np.std(center_gray[r, :].astype(float)) for r in range(r1, r2)
        ])

    # --- Adaptive color mask (reference-based) ---
    center_strip = center_hsv
    ref_start = (band_y_crop + int(crop_h * 0.06)) if band_y_crop else int(crop_h * 0.65)
    ref_start = min(ref_start, int(crop_h * 0.75))
    ref_end = min(ref_start + int(crop_h * 0.15), int(crop_h * 0.92))
    ref_region = center_strip[ref_start:ref_end]

    ref_v = ref_region[:, :, 2].flatten().astype(float)
    ref_s = ref_region[:, :, 1].flatten().astype(float)
    v_p10 = float(np.percentile(ref_v, 10))
    s_p5 = float(np.percentile(ref_s, 5))
    s_p95 = float(np.percentile(ref_s, 95))

    s_lo = max(0, int(s_p5 - 10))
    s_hi = min(255, int(s_p95 + 10))
    v_lo = max(80, int(v_p10 - 10))
    dough_mask = cv2.inRange(center_strip,
                             np.array([0, s_lo, v_lo]), np.array([180, s_hi, 255]))
    if band_y_crop is not None:
        dough_mask[b_start:b_end, :] = 0

    row_color = np.array([np.mean(dough_mask[i, :] > 0) for i in range(crop_h)])

    # --- Learn thresholds from dough reference ---
    dough_texture = row_texture[ref_start:ref_end]
    texture_p25 = float(np.percentile(dough_texture, 25))
    texture_threshold = max(30.0, texture_p25 * 0.70)

    log.debug("Thresholds: texture=%.1f (ref_p25=%.1f), color: S=[%d-%d] V>=%d",
              texture_threshold, texture_p25, s_lo, s_hi, v_lo)

    # --- Choose signal based on lighting ---
    # High reference texture (>35) = good contrast (daylight) → use texture
    # Low reference texture (<35) = low contrast (night/flash) → use color
    color_threshold = 0.35
    use_texture = texture_p25 > 35
    log.debug("Signal: %s (ref_p25=%.1f)", "texture" if use_texture else "color", texture_p25)

    def row_signal(i):
        """Returns True if row i looks like dough."""
        if use_texture:
            return row_texture[i] >= texture_threshold
        else:
            return row_color[i] >= color_threshold

    # --- Band-anchored surface detection ---
    min_run = max(4, int(crop_h * 0.025))
    surface_idx = lid_end  # default: jar full

    if band_y_crop is not None:
        # Probe zone: 10-20% of crop above the band
        probe_start = max(lid_end, band_y_crop - int(crop_h * 0.20))
        probe_end = max(lid_end, band_y_crop - int(crop_h * 0.10))
        if probe_end > probe_start:
            probe_vals = [row_signal(i) for i in range(probe_start, probe_end)]
            dough_above_band = sum(probe_vals) / len(probe_vals) > 0.5
        else:
            dough_above_band = True

        log.debug("Band probe: dough_above=%s", dough_above_band)

        if not dough_above_band:
            # Dough is AT or BELOW the band — scan down from band to find where dough ends
            surface_idx = b_end
            run_count = 0
            for i in range(b_end, min(crop_h, int(crop_h * 0.95))):
                if not row_signal(i):
                    run_count += 1
                    if run_count >= min_run:
                        surface_idx = i - min_run
                        break
                else:
                    run_count = 0
        else:
            # Dough is ABOVE the band — scan up from band to find surface
            run_count = 0
            for i in range(b_start, lid_end, -1):
                if not row_signal(i):
                    run_count += 1
                    if run_count >= min_run:
                        surface_idx = i + min_run
                        break
                else:
                    run_count = 0
            if run_count < min_run:
                surface_idx = lid_end

    best_y = tope + surface_idx

    # --- Debug image ---
    try:
        debug_img = img.copy()
        cv2.rectangle(debug_img, (izq, tope), (der, base), (255, 0, 0), 2)
        cv2.line(debug_img, (izq, base), (der, base), (0, 255, 0), 3)
        cv2.line(debug_img, (izq, tope), (der, tope), (255, 255, 0), 3)
        cv2.line(debug_img, (izq, best_y), (der, best_y), (0, 0, 255), 4)
        # Band
        if band_y_crop is not None:
            band_abs = tope + band_y_crop
            cv2.line(debug_img, (izq, band_abs), (der, band_abs), (0, 255, 255), 2)
        if detected_band_y is not None:
            det_abs = tope + detected_band_y
            cv2.line(debug_img, (izq, det_abs), (der, det_abs), (255, 0, 255), 2)
        cv2.imwrite(photo_path.replace(".jpg", "_cv_debug.jpg"), debug_img)
    except Exception:
        pass

    # Normalize: 0% = base (jar bottom), 100% = lid_end (effective jar top)
    # Using lid_end instead of tope avoids counting the metallic lid as fillable space
    effective_tope = tope + lid_end
    if best_y <= effective_tope:
        result = 100.0  # dough reaches or exceeds the jar opening
    else:
        result = round(((base - best_y) / (base - effective_tope)) * 100.0, 1)
    result = min(result, 100.0)
    log.info("OpenCV HSV: surface=%d, lid_end=%d, band=%s, det_band=%s → %.1f%%",
             surface_idx, lid_end, band_y_crop, detected_band_y, result)
    return result


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_photo(
    config: AppConfig,
    photo_path: str,
    baseline_foto_path: str | None = None,
    corrections_file: Path | None = None,
    calibration: "CalibrationBounds | None" = None,
) -> dict:
    """Analyze a fermentation photo with Claude Vision.

    Returns a dict with: altura_pct, banda_pct, burbujas, textura, notas, confianza.
    OpenCV runs separately via run_opencv() and fusion happens in measurement.py.
    """
    api_key = config.anthropic_api_key
    if not api_key:
        raise ValueError("No ANTHROPIC_API_KEY configured")

    model = config.claude_model

    # Crop to jar region if calibrated (sends Claude a focused image)
    cropped_path = _crop_to_jar(photo_path, calibration)
    photo_to_encode = cropped_path or photo_path
    if os.path.getsize(photo_to_encode) > 4 * 1024 * 1024:
        photo_to_encode = _compress_image(photo_to_encode)
    current_b64 = _encode_image(photo_to_encode)
    current_media = _detect_media_type(photo_to_encode)

    # Corrections context
    corr_ctx = ""
    if corrections_file:
        corr_ctx = _load_corrections(corrections_file)

    # Calibration context — tell Claude where the band actually is
    calib_ctx = ""
    if calibration and calibration.is_complete and calibration.fondo_y_pct is not None:
        band_jar_pct = (
            (calibration.base_y_pct - calibration.fondo_y_pct)
            / (calibration.base_y_pct - calibration.tope_y_pct)
            * 100
        )
        calib_ctx = (
            f"\nREFERENCIA CALIBRADA: La banda elástica roja está a ~{band_jar_pct:.0f}% del frasco "
            f"(medido desde el fondo). Esto es un DATO CONOCIDO, úsalo como ancla.\n"
        )

    # Context about cropping
    crop_ctx = ""
    if cropped_path:
        crop_ctx = (
            "NOTA: La imagen ya está recortada al interior del frasco. "
            "El borde inferior de la imagen = fondo del frasco, el borde superior = tapa.\n\n"
        )

    # Decide if we have a baseline photo for comparative mode
    use_baseline = (
        baseline_foto_path is not None
        and Path(baseline_foto_path).exists()
        and str(baseline_foto_path) != str(photo_path)
    )

    if use_baseline:
        baseline_ctx = "Se muestran 2 fotos: IMAGEN 1 es la referencia inicial del día, IMAGEN 2 es la actual."
        baseline_cropped = _crop_to_jar(str(baseline_foto_path), calibration)
        baseline_to_encode = baseline_cropped or str(baseline_foto_path)
        if os.path.getsize(baseline_to_encode) > 4 * 1024 * 1024:
            baseline_to_encode = _compress_image(baseline_to_encode)
        baseline_b64 = _encode_image(baseline_to_encode)
        baseline_media = _detect_media_type(baseline_foto_path)

        prompt = PROMPT_UNIFIED.format(
            baseline_context=baseline_ctx,
            crop_context=crop_ctx,
            calibration_context=calib_ctx,
            corrections_context=corr_ctx,
        )
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": baseline_media, "data": baseline_b64}},
            {"type": "image", "source": {"type": "base64", "media_type": current_media, "data": current_b64}},
            {"type": "text", "text": prompt},
        ]
    else:
        prompt = PROMPT_UNIFIED.format(
            baseline_context="Se muestra 1 foto del frasco.",
            crop_context=crop_ctx,
            calibration_context=calib_ctx,
            corrections_context=corr_ctx,
        )
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": current_media, "data": current_b64}},
            {"type": "text", "text": prompt},
        ]

    # Call Claude API
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": content}],
        },
        timeout=30,
    )

    try:
        raw = response.json()
        if "content" not in raw:
            log.warning("Claude unexpected response: %s", raw)
        analysis = _parse_response(raw["content"][0]["text"])
    except Exception as e:
        log.warning("Failed to parse Claude response: %s", e)
        analysis = {
            "burbujas": "pocas",
            "textura": "lisa",
            "notas": "Medición por OpenCV (Claude no disponible)",
        }

    return analysis
