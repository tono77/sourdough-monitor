"""Measurement fusion service — combines Claude + OpenCV and calculates growth.

Two-layer architecture:
  Layer 1: Raw position measurement (where is the surface in the jar, 0-100%)
  Layer 2: Growth calculation (how much has it grown from baseline)
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Weights for fusion (higher = more trusted)
# OpenCV (HSV) is the most reliable — deterministic, calibrated.
# Claude struggles with translucent dough.
# ML excluded from fusion until retrained with better ground truth.
CV_WEIGHT = 5.0
CLAUDE_WEIGHT = 3.0
# When Claude and OpenCV disagree, trust OpenCV (not Claude)
DISAGREEMENT_THRESHOLD = 20.0
# Circuit breaker: OpenCV saturating to an extreme (full jar or empty jar)
# is a known failure mode — the `scan_up` loop falls back to `lid_end` when
# it can't find a dough→glass transition (flash reflections, ml markings on
# empty glass above the band can read as "textured" = dough). When CV hits
# these extremes AND Claude strongly disagrees, prefer Claude.
CV_SATURATION_HIGH = 98.0
CV_SATURATION_LOW = 2.0
# Second circuit breaker: even below saturation, if Claude is internally
# coherent (reports both altura AND banda) and CV disagrees by >= 25%,
# prefer Claude. Catches two failure modes observed on 2026-04-17:
#   - CV latches onto a wrong band (tablecloth stripe) → altura ~89%
#   - CV scans up through bubbly foam layer during peak fermentation and
#     can't find a dough→glass transition → altura 80-88% while real
#     solid-dough surface per Claude is ~57%.
# Threshold lowered from 40 to 25 after the 2026-04-17 12:00 foam incident.
HUGE_DISAGREEMENT_THRESHOLD = 25.0


def compute_measurement(
    claude_result: dict,
    cv_altura: float | None,
    baseline_altura: float | None,
    ml_altura: float | None = None,
    is_new_cycle: bool = False,
) -> dict:
    """Fuse Claude + OpenCV + ML readings and compute growth.

    Args:
        claude_result: Raw dict from Claude Vision analysis.
        cv_altura: OpenCV surface position (0-100% of jar), or None.
        baseline_altura: First measurement's altura_pct for this cycle.
        ml_altura: ML model surface position (0-100% of jar), or None.
        is_new_cycle: True if a cycle marker was recently set and this is
            the first or an early measurement in the new cycle.

    Returns:
        Dict with standardized fields ready for DB storage.
    """
    # --- Layer 1: Extract and fuse surface position ---
    claude_altura = _extract_claude_altura(claude_result)
    claude_confianza = claude_result.get("confianza")
    claude_banda = claude_result.get("banda_pct")

    # Circuit breaker: OpenCV saturated to an extreme AND Claude is
    # internally consistent (reports both altura and banda) and strongly
    # disagrees → discard OpenCV. Saturation is a known failure mode where
    # the scan_up loop can't find the dough→glass transition.
    cv_saturated = cv_altura is not None and (
        cv_altura >= CV_SATURATION_HIGH or cv_altura <= CV_SATURATION_LOW
    )
    claude_coherent = (
        claude_altura is not None and claude_banda is not None
    )
    if (cv_saturated and claude_coherent and cv_altura is not None
            and abs(cv_altura - claude_altura) > DISAGREEMENT_THRESHOLD):
        log.warning(
            "OpenCV saturado descartado: CV=%.1f%% (extremo), Claude=%.1f%% "
            "(banda=%.1f%%). Probable falla por reflejos/marcas del vidrio.",
            cv_altura, claude_altura, claude_banda,
        )
        cv_altura = None

    # Second circuit breaker: massive disagreement + coherent Claude → trust
    # Claude. Catches non-saturated CV failures where the band anchor drifts
    # (e.g. CV detected band on tablecloth stripe instead of the real red band).
    if (cv_altura is not None and claude_coherent
            and abs(cv_altura - claude_altura) >= HUGE_DISAGREEMENT_THRESHOLD):
        log.warning(
            "OpenCV descartado por desacuerdo masivo: CV=%.1f%%, Claude=%.1f%% "
            "(banda=%.1f%%, diff>=%.0f). Probable fallo en detección de banda.",
            cv_altura, claude_altura, claude_banda, HUGE_DISAGREEMENT_THRESHOLD,
        )
        cv_altura = None

    # Spatial consistency check: if Claude says mass is below band but
    # OpenCV says mass is well above, Claude is likely misreading the
    # translucent dough as empty glass. Override with OpenCV.
    # (Skipped when CV was already discarded by the circuit breaker.)
    if (cv_altura is not None
            and claude_altura is not None and claude_banda is not None
            and claude_altura < claude_banda  # Claude says mass below band
            and cv_altura > claude_banda):     # OpenCV says mass above band
        log.warning(
            "Claude inconsistente: masa=%.1f%% < banda=%.1f%%, pero OpenCV=%.1f%%. "
            "Descartando Claude (probable confusión masa translúcida/vidrio)",
            claude_altura, claude_banda, cv_altura,
        )
        claude_altura = None

    altura_pct, fuente = _fuse(claude_altura, claude_confianza, cv_altura, ml_altura)

    # --- Layer 2: Calculate growth from baseline ---
    crecimiento_pct = None
    if altura_pct is not None:
        if baseline_altura is None:
            # This is the first measurement of the cycle — growth = 0%
            crecimiento_pct = 0.0
        elif baseline_altura > 0:
            crecimiento_pct = round(
                ((altura_pct - baseline_altura) / baseline_altura) * 100, 1
            )

    # --- Generate coherent notes based on final fused values ---
    notas = _generate_notas(
        altura_pct, crecimiento_pct, fuente,
        claude_result.get("burbujas", ""),
        claude_result.get("textura", ""),
        claude_result.get("notas", ""),
        is_new_cycle=is_new_cycle,
        opinion_panadero=claude_result.get("opinion_panadero", ""),
    )

    # --- Build merged result ---
    merged = {
        # Qualitative (pass-through from Claude)
        "burbujas": claude_result.get("burbujas", ""),
        "textura": claude_result.get("textura", ""),
        "notas": notas,
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


def _generate_notas(
    altura: float | None,
    crecimiento: float | None,
    fuente: str | None,
    burbujas: str,
    textura: str,
    claude_notas: str,
    is_new_cycle: bool = False,
    opinion_panadero: str = "",
) -> str:
    """Generate description consistent with the fused measurement values.

    When instrumental sources (OpenCV/ML) override Claude's altura, Claude's
    notes may describe what it saw (e.g. foam near top) rather than the actual
    solid dough level. This function builds a coherent description.

    When is_new_cycle is True, notes reflect the cycle restart context instead
    of describing the level as "dropping" (which would be misleading after a feed).
    """
    # If Claude was the sole source and no cycle context needed, pass through
    if (fuente == "claude" or fuente is None) and not is_new_cycle:
        return claude_notas

    if altura is None:
        return claude_notas

    # Build description from actual values
    parts = []

    # Cycle context takes priority
    if is_new_cycle:
        parts.append("Inicio de nuevo ciclo")

    # Level description
    if altura >= 85:
        parts.append("Masa muy alta en el frasco")
    elif altura >= 65:
        parts.append("Masa alta en el frasco")
    elif altura >= 45:
        parts.append("Masa a media altura")
    elif altura >= 25:
        parts.append("Masa baja en el frasco")
    else:
        parts.append("Masa muy baja en el frasco")

    # Activity
    bub_map = {"muchas": "con muchas burbujas", "pocas": "con pocas burbujas"}
    if burbujas in bub_map:
        parts.append(bub_map[burbujas])

    tex_map = {"muy_activa": "superficie muy activa", "rugosa": "superficie rugosa"}
    if textura in tex_map:
        parts.append(tex_map[textura])

    # Growth trend — skip "bajando" if it's a new cycle (the drop is expected)
    if crecimiento is not None and not is_new_cycle:
        if crecimiento >= 80:
            parts.append("cerca de punto maximo")
        elif crecimiento >= 30:
            parts.append("creciendo bien")
        elif crecimiento <= -20:
            parts.append("bajando")
    elif crecimiento is not None and is_new_cycle and crecimiento > 0:
        parts.append("comenzando a crecer")

    result = ", ".join(parts)
    if opinion_panadero:
        result += f". 🧑‍🍳 {opinion_panadero}"
    return result


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
    """Weighted fusion — OpenCV is primary when available, Claude secondary.

    When OpenCV and Claude disagree strongly, Claude is discarded (not OpenCV),
    because Claude consistently misreads translucent dough as empty glass.

    Returns:
        (fused_altura, source_label)
    """
    sources: list[tuple[float, float, str]] = []  # (value, weight, name)

    # OpenCV is the primary source when calibrated — deterministic and reliable.
    if cv_altura is not None:
        sources.append((cv_altura, CV_WEIGHT, "opencv"))

    # Claude is included only if it roughly agrees with OpenCV.
    # Claude struggles with translucent dough and ml markings on the jar.
    if claude_altura is not None:
        if cv_altura is not None and abs(cv_altura - claude_altura) > DISAGREEMENT_THRESHOLD:
            log.info("Claude descartado: %.1f%% vs OpenCV %.1f%% (diff > %d%%)",
                     claude_altura, cv_altura, DISAGREEMENT_THRESHOLD)
        else:
            c_weight = min(float(claude_confianza), CLAUDE_WEIGHT) if claude_confianza else CLAUDE_WEIGHT
            sources.append((claude_altura, c_weight, "claude"))

    # ML model excluded — undertrained, consistently reads ~38% regardless of actual level.
    # Will be re-added after retraining with corrected ground truth data.
    if ml_altura is not None:
        log.info("ML ignorado (no incluido en fusión): %.1f%%", ml_altura)

    if not sources:
        # No instrumental sources — fall back to Claude alone
        if claude_altura is not None:
            c_weight = min(float(claude_confianza), CLAUDE_WEIGHT) if claude_confianza else CLAUDE_WEIGHT
            return round(claude_altura, 1), "claude"
        return None, None

    if len(sources) == 1:
        return round(sources[0][0], 1), sources[0][2]

    total_weight = sum(w for _, w, _ in sources)
    fused = sum(v * w for v, w, _ in sources) / total_weight
    names = "+".join(n for _, _, n in sources)
    return round(fused, 1), f"fusionado({names})"
