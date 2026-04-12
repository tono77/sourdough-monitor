"""Measurement fusion service — combines Claude + OpenCV and calculates growth.

Two-layer architecture:
  Layer 1: Raw position measurement (where is the surface in the jar, 0-100%)
  Layer 2: Growth calculation (how much has it grown from baseline)
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# OpenCV weight when calibration is available (fixed)
CV_WEIGHT = 3.0


def compute_measurement(
    claude_result: dict,
    cv_altura: float | None,
    baseline_altura: float | None,
) -> dict:
    """Fuse Claude + OpenCV readings and compute growth.

    Args:
        claude_result: Raw dict from Claude Vision analysis.
        cv_altura: OpenCV surface position (0-100% of jar), or None.
        baseline_altura: First measurement's altura_pct for this session.

    Returns:
        Dict with standardized fields ready for DB storage.
    """
    # --- Layer 1: Extract and fuse surface position ---
    claude_altura = _extract_claude_altura(claude_result)
    claude_confianza = claude_result.get("confianza")

    altura_pct, fuente = _fuse(claude_altura, claude_confianza, cv_altura)

    # --- Layer 2: Calculate growth from baseline ---
    crecimiento_pct = None
    if altura_pct is not None and baseline_altura is not None and baseline_altura > 0:
        crecimiento_pct = round(
            ((altura_pct - baseline_altura) / baseline_altura) * 100, 1
        )

    # --- Build merged result ---
    merged = {
        # Qualitative (pass-through from Claude)
        "burbujas": claude_result.get("burbujas", ""),
        "textura": claude_result.get("textura", ""),
        "notas": claude_result.get("notas", ""),
        "confianza": claude_confianza,
        # Quantitative (computed)
        "altura_pct": altura_pct,
        "crecimiento_pct": crecimiento_pct,
        "fuente": fuente,
        # Backwards compatibility
        "nivel_pct": crecimiento_pct,
        "altura_y_pct": altura_pct,
        "modo_analisis": fuente,
    }

    log.info(
        "Medición: altura=%.1f%% (%s) | crecimiento=%s%% | baseline=%.1f%%",
        altura_pct or 0, fuente or "none",
        f"{crecimiento_pct:+.1f}" if crecimiento_pct is not None else "N/A",
        baseline_altura or 0,
    )

    return merged


def _extract_claude_altura(result: dict) -> float | None:
    """Extract surface position from Claude's response (either mode)."""
    # Try the unified field first (new prompt)
    for key in ("altura_pct", "altura_y_pct", "altura_actual_pct"):
        val = result.get(key)
        if val is not None:
            return float(val)
    return None


def _fuse(
    claude_altura: float | None,
    claude_confianza: int | None,
    cv_altura: float | None,
) -> tuple[Optional[float], Optional[str]]:
    """Weighted average of Claude and OpenCV positions.

    Returns:
        (fused_altura, source_label)
    """
    if claude_altura is not None and cv_altura is not None:
        c_weight = float(claude_confianza) if claude_confianza else 2.0
        total = c_weight + CV_WEIGHT
        fused = (c_weight * claude_altura + CV_WEIGHT * cv_altura) / total
        return round(fused, 1), "fusionado"

    if claude_altura is not None:
        return round(claude_altura, 1), "claude"

    if cv_altura is not None:
        return round(cv_altura, 1), "opencv"

    return None, None
