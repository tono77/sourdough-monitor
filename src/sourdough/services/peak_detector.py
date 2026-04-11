"""Peak detection algorithm — pure business logic, no SQL.

Detects fermentation peak (first meaningful descent after growth).
Requires 2 consecutive declining readings to avoid triggering on noise.
"""

from sourdough.models import Measurement

# Thresholds
MIN_GROWTH = 10   # Must have grown at least 10 raw units from baseline
MIN_DECLINE = 3   # Cumulative decline must be at least 3 units


def detect_peak(
    recent: list[Measurement],
    baseline_nivel: float | None,
    max_nivel: float | None,
    peak_already_exists: bool,
) -> bool:
    """Determine if a fermentation peak has been reached.

    Args:
        recent: The 3+ most recent measurements (newest first).
        baseline_nivel: The first measurement's nivel_pct for this session.
        max_nivel: The maximum nivel_pct reached so far in the session.
        peak_already_exists: Whether a peak has already been flagged.

    Returns:
        True if a new peak is detected.
    """
    if peak_already_exists:
        return False

    if len(recent) < 3 or baseline_nivel is None or max_nivel is None:
        return False

    curr = recent[0]   # latest
    prev = recent[1]
    prev2 = recent[2]  # two readings ago

    if curr.nivel_pct is None or prev.nivel_pct is None or prev2.nivel_pct is None:
        return False

    # Two consecutive declines of meaningful magnitude
    two_consec_declines = (
        curr.nivel_pct < prev.nivel_pct
        and prev.nivel_pct < prev2.nivel_pct
        and (prev2.nivel_pct - curr.nivel_pct) >= MIN_DECLINE
    )

    # Must have had real growth from baseline
    had_real_growth = (max_nivel - baseline_nivel) >= MIN_GROWTH

    return two_consec_declines and had_real_growth
