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

{corrections_context}
MÉTODO:
1. Busca la banda elástica roja como REFERENCIA visual.
2. Identifica dónde está la línea horizontal de la superficie superior de la MASA MADRE.
3. Usa las marcas/rayitas impresas en el vidrio para estimar la posición.
4. NO uses los píxeles de la imagen — la perspectiva deforma. Usa las marcas físicas del frasco.

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
        lines = ["HISTORIAL DE CORRECCIONES MANUALES RECIENTES DEL USUARIO:"]
        for c in recent:
            ts = c.get("timestamp", "").split("T")[-1][:5]
            lines.append(f"- A las {ts}, el usuario reportó que el nivel real de crecimiento era: {c.get('nivel_pct')}%.")
        lines.append("\nUtiliza esta escala como referencia absoluta para la foto de ahora.\n")
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
    """Run deterministic CV analysis. Returns surface position (0-100% of jar) or None."""
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

    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)

    # 1D horizontal brightness profile
    profile = [np.mean(gray[i, :]) for i in range(gray.shape[0])]

    kernel_size = max(5, int((base - tope) * 0.02))
    kernel = np.ones(kernel_size) / kernel_size
    profile_smooth = np.convolve(profile, kernel, mode="valid")

    bright_min = np.min(profile_smooth)
    bright_max = np.max(profile_smooth)
    threshold = (bright_min + bright_max) / 2.0

    # Mask red band glare
    if calibration.fondo_y_pct is not None:
        fondo_abs = int(height * (calibration.fondo_y_pct / 100.0))
        fondo_crop_idx = fondo_abs - tope - (kernel_size // 2)
        band_margin = int((base - tope) * 0.05)
        for i in range(max(0, fondo_crop_idx - band_margin),
                       min(len(profile_smooth), fondo_crop_idx + band_margin)):
            profile_smooth[i] = 0.0

    start_idx = int(len(profile_smooth) * 0.1)
    meniscus_idx = None
    for i in range(start_idx, len(profile_smooth)):
        if profile_smooth[i] > threshold:
            meniscus_idx = i
            break

    if meniscus_idx is None:
        meniscus_idx = int(np.argmax(profile_smooth[start_idx:])) + start_idx

    meniscus_idx += (kernel_size // 2)
    best_y = tope + meniscus_idx

    # Debug image
    try:
        debug_img = img.copy()
        cv2.rectangle(debug_img, (izq, tope), (der, base), (255, 0, 0), 2)
        cv2.line(debug_img, (izq, base), (der, base), (0, 255, 0), 3)
        cv2.line(debug_img, (izq, tope), (der, tope), (255, 255, 0), 3)
        cv2.line(debug_img, (izq, best_y), (der, best_y), (0, 0, 255), 4)
        cv2.imwrite(photo_path.replace(".jpg", "_cv_debug.jpg"), debug_img)
    except Exception:
        pass

    return round((best_y / height) * 100.0, 2)


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_photo(
    config: AppConfig,
    photo_path: str,
    baseline_foto_path: str | None = None,
    corrections_file: Path | None = None,
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
            baseline_context=baseline_ctx, corrections_context=corr_ctx,
        )
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": baseline_media, "data": baseline_b64}},
            {"type": "image", "source": {"type": "base64", "media_type": current_media, "data": current_b64}},
            {"type": "text", "text": prompt},
        ]
    else:
        prompt = PROMPT_UNIFIED.format(
            baseline_context="Se muestra 1 foto del frasco.",
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
