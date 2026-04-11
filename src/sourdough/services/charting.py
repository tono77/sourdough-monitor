"""Matplotlib dark-mode fermentation charts.

Receives data as parameters — no database access.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from sourdough.models import Session

log = logging.getLogger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# Color palette (single source of truth for Python charts)
BG_OUTER = "#0f0f23"
BG_INNER = "#1a1a3e"
COLOR_LEVEL = "#e94560"
COLOR_BUBBLE = "#e8a045"
COLOR_PEAK = "#ffd700"
COLOR_GRID = "#555"
COLOR_TEXT = "#ccc"
COLOR_MUTED = "#888"


def make_chart(
    rows: list,
    charts_dir: Path,
    output_path: Path | None = None,
    session: Session | None = None,
) -> str | None:
    """Generate a dark-mode fermentation chart.

    Args:
        rows: List of sqlite3.Row or tuples (timestamp, nivel_pct, burbujas, textura, es_peak).
        charts_dir: Directory to save charts.
        output_path: Explicit output path, or auto-generated if None.
        session: Optional session info for the chart title.

    Returns:
        Path to the saved chart, or text report if matplotlib is unavailable.
    """
    if not HAS_MATPLOTLIB:
        return _make_text_report(rows, session)

    if not rows:
        return None

    charts_dir.mkdir(parents=True, exist_ok=True)

    times = [datetime.fromisoformat(r[0]) for r in rows]
    levels = [r[1] for r in rows]
    burbuja_map = {"ninguna": 0, "pocas": 1, "muchas": 2}
    burbujas = [burbuja_map.get(r[2], 0) for r in rows]
    peak_times = [datetime.fromisoformat(r[0]) for r in rows if r[4] == 1]
    peak_levels = [r[1] for r in rows if r[4] == 1]

    initial_level = levels[0] if levels else 100
    relative_levels = [(l - initial_level) for l in levels]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]},
    )
    fig.patch.set_facecolor(BG_OUTER)
    for ax in [ax1, ax2]:
        ax.set_facecolor(BG_INNER)
        ax.tick_params(colors=COLOR_MUTED)
        for spine in ax.spines.values():
            spine.set_color("#333")

    # Chart 1: Level change (relative)
    ax1.plot(times, relative_levels, color=COLOR_LEVEL, linewidth=2.5,
             marker="o", markersize=4, label="Cambio de nivel", zorder=3)
    ax1.fill_between(times, 0, relative_levels,
                     where=[l > 0 for l in relative_levels],
                     alpha=0.15, color=COLOR_LEVEL, label="Crecimiento")
    ax1.fill_between(times, 0, relative_levels,
                     where=[l < 0 for l in relative_levels],
                     alpha=0.15, color="#4a4a6a", label="Descenso")
    ax1.axhline(y=0, color=COLOR_GRID, linestyle="--", linewidth=1, alpha=0.5)

    if peak_times:
        peak_relative = [p - initial_level for p in peak_levels]
        ax1.scatter(peak_times, peak_relative, color=COLOR_PEAK, s=200, zorder=5,
                    marker="*", label=f"Peak ({peak_relative[0]:.0f}%)")
        ax1.annotate(
            f"PEAK\n+{peak_relative[0]:.0f}%",
            xy=(peak_times[0], peak_relative[0]),
            xytext=(15, -30), textcoords="offset points",
            color=COLOR_PEAK, fontsize=10, fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=COLOR_PEAK, lw=1.5),
        )

    session_label = f" — Sesión {session.fecha}" if session else ""
    ax1.set_ylabel("Cambio de nivel (Δ%)", color=COLOR_TEXT, fontsize=11)
    ax1.set_title(f"Sourdough Starter Monitor{session_label}",
                  color="white", fontsize=14, pad=15, fontweight="bold")
    ax1.legend(facecolor=BG_INNER, labelcolor=COLOR_TEXT, fontsize=8, edgecolor="#333")
    ax1.grid(axis="y", alpha=0.1, color=COLOR_GRID)

    # Chart 2: Bubble activity
    ax2.plot(times, burbujas, color=COLOR_BUBBLE, linewidth=2.5,
             marker="o", markersize=6, label="Actividad", zorder=3)
    ax2.fill_between(times, burbujas, alpha=0.2, color=COLOR_BUBBLE)
    ax2.set_ylabel("Burbujas", color=COLOR_TEXT, fontsize=10)
    ax2.set_yticks([0, 1, 2])
    ax2.set_yticklabels(["Ninguna", "Pocas", "Muchas"], color="#aaa", fontsize=8)
    ax2.set_ylim(-0.2, 2.5)
    ax2.legend(facecolor=BG_INNER, labelcolor=COLOR_TEXT, fontsize=8,
               edgecolor="#333", loc="upper left")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax2.grid(axis="y", alpha=0.1, color=COLOR_GRID)

    # Stats footer
    if levels:
        elapsed = (times[-1] - times[0]).total_seconds() / 3600
        max_rel = max(relative_levels)
        stats = (
            f"Mediciones: {len(levels)} │ Tiempo: {elapsed:.1f}h │ "
            f"Inicio: {initial_level:.0f}% │ Máx cambio: +{max_rel:.0f}%"
        )
        fig.text(0.5, 0.02, stats, ha="center", color="#666", fontsize=9, family="monospace")

    plt.xticks(rotation=30, color=COLOR_MUTED)
    plt.tight_layout(rect=[0, 0.05, 1, 1])

    if output_path is None:
        output_path = charts_dir / f"sourdough_{datetime.now().strftime('%Y%m%d_%H%M')}.png"

    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=BG_OUTER)
    plt.close()
    log.info("Chart saved: %s", output_path)
    return str(output_path)


def _make_text_report(rows: list, session: Session | None = None) -> str | None:
    if not rows:
        return "No data yet."

    times = [datetime.fromisoformat(r[0]) for r in rows]
    levels = [r[1] for r in rows]
    max_level = max(levels)
    max_idx = levels.index(max_level)
    elapsed = (times[-1] - times[0]).total_seconds() / 3600

    header = "SOURDOUGH MONITOR"
    if session:
        header += f" — {session.fecha}"

    lines = [
        header, "=" * 40,
        f"Mediciones: {len(rows)}",
        f"Tiempo: {elapsed:.1f}h",
        f"Nivel actual: {levels[-1]:.0f}%",
        f"Máximo: {max_level:.0f}% a las {times[max_idx].strftime('%H:%M')}",
        f"Estado: {'Descenso' if levels[-1] < max_level else 'Crecimiento'}",
        "", "Historial:",
    ]
    for t, l in zip(times, levels):
        bar = "█" * int(l / 10)
        lines.append(f"  {t.strftime('%H:%M')} │ {l:6.1f}% │ {bar}")

    return "\n".join(lines)
