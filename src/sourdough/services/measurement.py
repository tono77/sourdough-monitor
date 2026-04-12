"""Measurement fusion service — combines Claude + OpenCV and calculates growth.

Two-layer architecture:
  Layer 1: Raw position measurement (where is the surface in the jar, 0-100%)
  Layer 2: Growth calculation (how much has it grown from baseline)
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Weights for fusion (higher = more trusted)
CV_WEIGHT = 3.0
ML_WEIGHT = 5.0


def compute_measurement(
    claude_result: dict,
    cv_altura: float | None,
    baseline_altura: float | None,
    ml_altura: float | None = None,
) -> dict:
    """Fuse Claude + OpenCV + ML readings and compute growth.

    Args:
        claude_result: Raw dict from Claude Vision analysis.
        cv_altura: OpenCV surface position (0-100% of jar), or None.
        baseline_altura: First measurement's altura_pct for this session.
        ml_altura: ML model surface position (0-100% of jar), or None.

    Returns:
        Dict with standardized fields ready for DB storage.
    """
    # --- Layer 1: Extract and fuse surface position ---
    claude_altura = _extract_claude_altura(claude_result)
    claude_confianza = claude_result.get("confianza")

    altura_pct, fuente = _fuse(claude_altura, claude_confianza, cv_altura, ml_altura)

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
    ml_altura: float | None = None,
) -> tuple[Optional[float], Optional[str]]:
    """Weighted average of all available position sources.

    Returns:
        (fused_altura, source_label)
    """
    sources: list[tuple[float, float, str]] = []  # (value, weight, name)

    if claude_altura is not None:
        c_weight = float(claude_confianza) if claude_confianza else 2.0
        sources.append((claude_altura, c_weight, "claude"))
    if cv_altura is not None:
        sources.append((cv_altura, CV_WEIGHT, "opencv"))
    if ml_altura is not None:
        sources.append((ml_altura, ML_WEIGHT, "ml"))

    if not sources:
        return None, None

    if len(sources) == 1:
        return round(sources[0][0], 1), sources[0][2]

    total_weight = sum(w for _, w, _ in sources)
    fused = sum(v * w for v, w, _ in sources) / total_weight
    names = "+".join(n for _, _, n in sources)
    return round(fused, 1), f"fusionado({names})"
