#!/usr/bin/env python3
"""
Sourdough Monitor — Chart generation
Creates dark-mode fermentation graphs with matplotlib.
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

BASE_DIR = Path(__file__).resolve().parent
CHARTS_DIR = BASE_DIR / "charts"


def load_session_data(conn, session_id):
    """Load measurements for a specific session."""
    rows = conn.execute("""
        SELECT timestamp, nivel_pct, burbujas, textura, es_peak
        FROM mediciones
        WHERE sesion_id = ? AND nivel_pct IS NOT NULL
        ORDER BY id ASC
    """, (session_id,)).fetchall()
    return rows


def make_chart(rows, output_path=None, session_info=None):
    """Generate a dark-mode fermentation chart."""
    if not HAS_MATPLOTLIB:
        return make_text_report(rows, session_info)

    if not rows:
        return None

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    times = [datetime.fromisoformat(r[0]) for r in rows]
    levels = [r[1] for r in rows]
    burbuja_map = {"ninguna": 0, "pocas": 1, "muchas": 2}
    burbujas = [burbuja_map.get(r[2], 0) for r in rows]
    peak_times = [datetime.fromisoformat(r[0]) for r in rows if r[4] == 1]
    peak_levels = [r[1] for r in rows if r[4] == 1]

    initial_level = levels[0] if levels else 100
    relative_levels = [(l - initial_level) for l in levels]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                    gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#0f0f23')
    for ax in [ax1, ax2]:
        ax.set_facecolor('#1a1a3e')
        ax.tick_params(colors='#888')
        for spine in ax.spines.values():
            spine.set_color('#333')

    # Chart 1: Level change (relative)
    ax1.plot(times, relative_levels, color='#e94560', linewidth=2.5,
             marker='o', markersize=4, label='Cambio de nivel', zorder=3)
    ax1.fill_between(times, 0, relative_levels,
                     where=[l > 0 for l in relative_levels],
                     alpha=0.15, color='#e94560', label='Crecimiento')
    ax1.fill_between(times, 0, relative_levels,
                     where=[l < 0 for l in relative_levels],
                     alpha=0.15, color='#4a4a6a', label='Descenso')
    ax1.axhline(y=0, color='#555', linestyle='--', linewidth=1, alpha=0.5)

    if peak_times:
        peak_relative = [p - initial_level for p in peak_levels]
        ax1.scatter(peak_times, peak_relative, color='#ffd700', s=200, zorder=5,
                   marker='*', label=f'Peak ({peak_relative[0]:.0f}%)')
        ax1.annotate(f'🎯 PEAK\n+{peak_relative[0]:.0f}%',
                    xy=(peak_times[0], peak_relative[0]),
                    xytext=(15, -30), textcoords='offset points',
                    color='#ffd700', fontsize=10, fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color='#ffd700', lw=1.5))

    session_label = ""
    if session_info:
        session_label = f" — Sesión {session_info.get('fecha', '')}"

    ax1.set_ylabel('Cambio de nivel (Δ%)', color='#ccc', fontsize=11)
    ax1.set_title(f'🍞 Sourdough Starter Monitor{session_label}',
                  color='white', fontsize=14, pad=15, fontweight='bold')
    ax1.legend(facecolor='#1a1a3e', labelcolor='#ccc', fontsize=8,
              edgecolor='#333')
    ax1.grid(axis='y', alpha=0.1, color='#555')

    # Chart 2: Bubble activity
    colors_segment = ['#3a3a5a', '#e8a045', '#e94560']
    ax2.plot(times, burbujas, color='#e8a045', linewidth=2.5,
             marker='o', markersize=6, label='Actividad', zorder=3)
    ax2.fill_between(times, burbujas, alpha=0.2, color='#e8a045')

    ax2.set_ylabel('Burbujas', color='#ccc', fontsize=10)
    ax2.set_yticks([0, 1, 2])
    ax2.set_yticklabels(['Ninguna', 'Pocas', 'Muchas'], color='#aaa', fontsize=8)
    ax2.set_ylim(-0.2, 2.5)
    ax2.legend(facecolor='#1a1a3e', labelcolor='#ccc', fontsize=8,
              edgecolor='#333', loc='upper left')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax2.grid(axis='y', alpha=0.1, color='#555')

    # Stats footer
    if levels:
        elapsed = (times[-1] - times[0]).total_seconds() / 3600
        max_rel = max(relative_levels)
        stats = (f"Mediciones: {len(levels)} │ Tiempo: {elapsed:.1f}h │ "
                f"Inicio: {initial_level:.0f}% │ Máx cambio: +{max_rel:.0f}%")
        fig.text(0.5, 0.02, stats, ha='center', color='#666', fontsize=9,
                family='monospace')

    plt.xticks(rotation=30, color='#888')
    plt.tight_layout(rect=[0, 0.05, 1, 1])

    if output_path is None:
        output_path = CHARTS_DIR / f"sourdough_{datetime.now().strftime('%Y%m%d_%H%M')}.png"

    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#0f0f23')
    plt.close()
    print(f"📊 Chart saved: {output_path}")
    return str(output_path)


def make_text_report(rows, session_info=None):
    """Text-based report when matplotlib is unavailable."""
    if not rows:
        return "No data yet."

    times = [datetime.fromisoformat(r[0]) for r in rows]
    levels = [r[1] for r in rows]
    max_level = max(levels)
    max_idx = levels.index(max_level)
    elapsed = (times[-1] - times[0]).total_seconds() / 3600

    header = "🍞 SOURDOUGH MONITOR"
    if session_info:
        header += f" — {session_info.get('fecha', '')}"

    report = f"""
{header}
{"=" * 40}
Mediciones: {len(rows)}
Tiempo: {elapsed:.1f}h
Nivel actual: {levels[-1]:.0f}%
Máximo: {max_level:.0f}% a las {times[max_idx].strftime('%H:%M')}
Estado: {"⬇️ Descenso" if levels[-1] < max_level else "⬆️ Crecimiento"}

Historial:
"""
    for t, l, b in zip(times, levels, [r[2] for r in rows]):
        bar = "█" * int(l / 10)
        report += f"  {t.strftime('%H:%M')} │ {l:6.1f}% │ {bar} │ 🫧{b}\n"

    return report


if __name__ == "__main__":
    from db import init_db, get_all_sessions, load_session_data as _unused

    conn = init_db()

    # If session_id provided as argument, use it
    if len(sys.argv) > 1:
        session_id = int(sys.argv[1])
        session = dict(conn.execute("SELECT * FROM sesiones WHERE id = ?", (session_id,)).fetchone())
        rows = load_session_data(conn, session_id)
    else:
        # Use latest session
        sessions = get_all_sessions(conn)
        if not sessions:
            print("No sessions found.")
            sys.exit(0)
        session = sessions[0]
        rows = load_session_data(conn, session["id"])

    if not rows:
        print("No measurement data for this session.")
    else:
        result = make_chart(rows, session_info=session)
        if result and result.endswith(".png"):
            print(f"Chart: {result}")
        elif result:
            print(result)

    conn.close()
