"""Peak detection algorithm — pure business logic, no SQL.

Detects fermentation peak (first meaningful descent after growth).
Requires 2 consecutive declining readings to avoid triggering on noise.
Operates on crecimiento_pct (volumetric growth from baseline).
"""

from datetime import datetime

from sourdough.models import Measurement

# Thresholds (in % of volumetric growth)
MIN_GROWTH = 30    # Must have grown at least 30% from baseline before peak is possible
MIN_DECLINE = 5    # Cumulative decline must be at least 5% to confirm peak
MIN_HOURS = 2.0    # Minimum fermentation time before peak is eligible


def detect_peak(
    recent: list[Measurement],
    baseline_nivel: float | None,
    max_nivel: float | None,
    peak_already_exists: bool,
    session_start: str | None = None,
) -> bool:
    """Determine if a fermentation peak has been reached.

    Args:
        recent: The 3+ most recent measurements (newest first).
        baseline_nivel: The first measurement's crecimiento_pct (usually 0).
        max_nivel: The maximum crecimiento_pct reached so far.
        peak_already_exists: Whether a peak has already been flagged.
        session_start: ISO timestamp of session start (for min time check).

    Returns:
        True if a new peak is detected.
    """
    if peak_already_exists:
        return False

    if len(recent) < 3 or baseline_nivel is None or max_nivel is None:
        return False

    # Minimum fermentation time check
    if session_start and recent[0].timestamp:
        try:
            start = datetime.fromisoformat(session_start)
            now = datetime.fromisoformat(recent[0].timestamp)
            elapsed_hours = (now - start).total_seconds() / 3600
            if elapsed_hours < MIN_HOURS:
                return False
        except (ValueError, TypeError):
            pass

    curr = recent[0]   # latest
    prev = recent[1]
    prev2 = recent[2]  # two readings ago

    # Use crecimiento_pct if available, fall back to nivel_pct
    def _get_growth(m: Measurement) -> float | None:
        return m.crecimiento_pct if m.crecimiento_pct is not None else m.nivel_pct

    c_val = _get_growth(curr)
    p_val = _get_growth(prev)
    p2_val = _get_growth(prev2)

    if c_val is None or p_val is None or p2_val is None:
        return False

    # Two consecutive declines of meaningful magnitude
    two_consec_declines = (
        c_val < p_val
        and p_val < p2_val
        and (p2_val - c_val) >= MIN_DECLINE
    )

    # Must have had real growth from baseline
    had_real_growth = (max_nivel - (baseline_nivel or 0)) >= MIN_GROWTH

    return two_consec_declines and had_real_growth
