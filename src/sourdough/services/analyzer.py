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

TAREA: Mide la posición de la SUPERFICIE de la masa en el frasco.
- 0% = el FONDO INTERIOR del frasco (vacío total)
- 100% = la TAPA del frasco (lleno hasta arriba)

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
3. Estima la posición como porcentaje del RECORRIDO VERTICAL entre el fondo y la tapa.
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
    """Run deterministic CV analysis. Returns surface position (0-100% of jar) or None.

    Uses a glass-score (brightness × uniformity) to find the empty glass zone,
    then detects where it transitions to dough.  The red elastic band is
    excluded using fondo_y_pct.

    NOTE: OpenCV is a secondary signal — Claude Vision is the primary source.
    This measurement is only used in fusion when it roughly agrees with Claude.
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

    crop_h = cropped.shape[0]
    kernel_size = max(5, int(crop_h * 0.02))
    kernel = np.ones(kernel_size) / kernel_size
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

    # Per-row mean brightness and std
    row_means = np.array([np.mean(gray[i, :].astype(float)) for i in range(crop_h)])
    row_stds = np.array([np.std(gray[i, :].astype(float)) for i in range(crop_h)])

    mean_smooth = np.convolve(row_means, kernel, mode="valid")
    std_smooth = np.convolve(row_stds, kernel, mode="valid")
    n = len(mean_smooth)

    # Glass-score: empty glass = BRIGHT (wall behind) + UNIFORM (no texture)
    # Normalize to 0-1
    m_min, m_max = mean_smooth.min(), mean_smooth.max()
    s_min, s_max = std_smooth.min(), std_smooth.max()
    mean_norm = (mean_smooth - m_min) / (m_max - m_min + 1e-6)
    std_norm = (std_smooth - s_min) / (s_max - s_min + 1e-6)
    glass_score = mean_norm * (1 - std_norm)

    # Mask band region
    band_idx = None
    if calibration.fondo_y_pct is not None:
        band_y_crop = int(height * (calibration.fondo_y_pct / 100.0)) - tope
        band_idx = band_y_crop - kernel_size // 2
        band_margin = max(15, int(crop_h * 0.05))
        b_start = max(0, band_idx - band_margin)
        b_end = min(n, band_idx + band_margin)

    cap_end = int(n * 0.05)
    table_start = int(n * 0.85)

    # Find peak glass-score in upper half (the empty glass zone)
    upper_end = int(n * 0.55)
    search = glass_score[cap_end:upper_end].copy()
    if band_idx is not None:
        for i in range(len(search)):
            abs_i = i + cap_end
            if b_start <= abs_i <= b_end:
                search[i] = 0

    glass_peak_idx = int(np.argmax(search)) + cap_end
    glass_peak_val = glass_score[glass_peak_idx]

    # Scan downward from glass peak: surface = where glass_score drops
    threshold = glass_peak_val * 0.5
    min_run = max(3, int(n * 0.015))
    run_count = 0
    meniscus_idx = None

    for i in range(glass_peak_idx, table_start):
        if band_idx is not None and b_start <= i <= b_end:
            continue
        if glass_score[i] < threshold:
            run_count += 1
            if run_count >= min_run:
                meniscus_idx = i - min_run + 1
                break
        else:
            run_count = 0

    if meniscus_idx is None:
        meniscus_idx = cap_end

    meniscus_idx += (kernel_size // 2)
    best_y = tope + meniscus_idx

    # Debug image
    try:
        debug_img = img.copy()
        cv2.rectangle(debug_img, (izq, tope), (der, base), (255, 0, 0), 2)
        cv2.line(debug_img, (izq, base), (der, base), (0, 255, 0), 3)
        cv2.line(debug_img, (izq, tope), (der, tope), (255, 255, 0), 3)
        cv2.line(debug_img, (izq, best_y), (der, best_y), (0, 0, 255), 4)
        # Draw band exclusion zone in magenta
        if calibration.fondo_y_pct is not None:
            band_y_abs = int(height * (calibration.fondo_y_pct / 100.0))
            bm = max(10, int(crop_h * 0.04))
            cv2.line(debug_img, (izq, band_y_abs - bm), (der, band_y_abs - bm), (255, 0, 255), 1)
            cv2.line(debug_img, (izq, band_y_abs + bm), (der, band_y_abs + bm), (255, 0, 255), 1)
        cv2.imwrite(photo_path.replace(".jpg", "_cv_debug.jpg"), debug_img)
    except Exception:
        pass

    # Normalize within jar bounds: 0% = fondo (base), 100% = tapa (tope)
    return round(((base - best_y) / (base - tope)) * 100.0, 2)


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

    # Prepare current photo
    photo_to_encode = photo_path
    if os.path.getsize(photo_path) > 4 * 1024 * 1024:
        photo_to_encode = _compress_image(photo_path)
    current_b64 = _encode_image(photo_to_encode)
    current_media = _detect_media_type(photo_path)

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

    # Decide if we have a baseline photo for comparative mode
    use_baseline = (
        baseline_foto_path is not None
        and Path(baseline_foto_path).exists()
        and str(baseline_foto_path) != str(photo_path)
    )

    if use_baseline:
        baseline_ctx = "Se muestran 2 fotos: IMAGEN 1 es la referencia inicial del día, IMAGEN 2 es la actual."
        baseline_to_encode = str(baseline_foto_path)
        if os.path.getsize(baseline_foto_path) > 4 * 1024 * 1024:
            baseline_to_encode = _compress_image(baseline_foto_path)
        baseline_b64 = _encode_image(baseline_to_encode)
        baseline_media = _detect_media_type(baseline_foto_path)

        prompt = PROMPT_UNIFIED.format(
            baseline_context=baseline_ctx,
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
