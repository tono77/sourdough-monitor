"""Bread window detection — fires when growth crosses the bake threshold.

The "bread window" is the optimal time to use the sourdough for baking:
- Opens when crecimiento_pct >= THRESHOLD
- Closes when crecimiento_pct drops below THRESHOLD after having been above

Returns state changes only — callers decide how to notify.
"""

import logging
from typing import Optional

from sourdough.models import Measurement

log = logging.getLogger(__name__)

THRESHOLD = 90.0  # 90% growth = ready for bread


def check_bread_window(
    current: Measurement,
    window_already_open: bool,
) -> Optional[str]:
    """Check if the bread window state changed.

    Args:
        current: The latest measurement.
        window_already_open: Whether the window was already open.

    Returns:
        "opened" if window just opened,
        "closed" if window just closed,
        None if no change.
    """
    growth = current.crecimiento_pct
    if growth is None:
        return None

    is_above = growth >= THRESHOLD

    if is_above and not window_already_open:
        log.info("VENTANA PARA PAN ABIERTA — crecimiento %.1f%%", growth)
        return "opened"

    if not is_above and window_already_open:
        log.info("VENTANA PARA PAN CERRADA — crecimiento %.1f%%", growth)
        return "closed"

    return None
