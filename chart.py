#!/usr/bin/env python3
"""
Sourdough Monitor — Generador de gráficos
Crea gráficas del proceso de fermentación en tiempo real.
"""

import sqlite3
import json
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

WORKSPACE = Path("/Users/moltbot/.openclaw/workspace/sourdough")
DB_PATH = WORKSPACE / "data" / "fermento.db"
CHARTS_DIR = WORKSPACE / "charts"

def load_data():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT timestamp, nivel_pct, burbujas, textura, es_peak
        FROM mediciones
        WHERE nivel_pct IS NOT NULL
        ORDER BY id ASC
    """).fetchall()
    conn.close()
    return rows

def make_chart(rows, output_path=None):
    if not HAS_MATPLOTLIB:
        print("matplotlib no disponible — generando reporte texto")
        return make_text_report(rows)

    times = [datetime.fromisoformat(r[0]) for r in rows]
    levels = [r[1] for r in rows]
    burbuja_map = {"ninguna": 0, "pocas": 1, "muchas": 2}
    burbujas = [burbuja_map.get(r[2], 0) for r in rows]
    peak_times = [datetime.fromisoformat(r[0]) for r in rows if r[4] == 1]
    peak_levels = [r[1] for r in rows if r[4] == 1]

    # Calcular cambio relativo desde el nivel inicial
    initial_level = levels[0] if levels else 100
    relative_levels = [(l - initial_level) for l in levels]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.patch.set_facecolor('#1a1a2e')
    for ax in [ax1, ax2]:
        ax.set_facecolor('#16213e')
        ax.tick_params(colors='white')
        ax.spines['bottom'].set_color('#444')
        ax.spines['top'].set_color('#444')
        ax.spines['left'].set_color('#444')
        ax.spines['right'].set_color('#444')

    # Gráfico 1: Cambio de nivel (relativo al inicio)
    ax1.plot(times, relative_levels, color='#e94560', linewidth=2.5, marker='o', markersize=4, label='Cambio de nivel')
    ax1.fill_between(times, 0, relative_levels, where=[l > 0 for l in relative_levels],
                     alpha=0.2, color='#e94560', label='Crecimiento')
    ax1.fill_between(times, 0, relative_levels, where=[l < 0 for l in relative_levels],
                     alpha=0.2, color='#4a4a6a', label='Descenso')
    ax1.axhline(y=0, color='#888', linestyle='--', linewidth=1, label='Nivel inicial')

    if peak_times:
        peak_relative = [p - initial_level for p in peak_levels]
        ax1.scatter(peak_times, peak_relative, color='#ffd700', s=150, zorder=5,
                   marker='★', label=f'Peak detectado ({peak_relative[0]:.0f}%)')
        ax1.annotate(f'🎯 PEAK\n{peak_relative[0]:.0f}%',
                    xy=(peak_times[0], peak_relative[0]),
                    xytext=(15, -30), textcoords='offset points',
                    color='#ffd700', fontsize=9,
                    arrowprops=dict(arrowstyle='->', color='#ffd700'))

    ax1.set_ylabel('Cambio de nivel (Δ%)', color='white', fontsize=11)
    ax1.set_title('🍞 Sourdough Starter Monitor — Cambio Relativo desde Inicio', color='white', fontsize=14, pad=15)
    ax1.legend(facecolor='#1a1a2e', labelcolor='white', fontsize=8)
    ax1.yaxis.label.set_color('white')

    # Gráfico 2: Actividad burbujas — mostrar línea de evolución
    colors_bub = ['#4a4a6a', '#e8a045', '#e94560']
    bub_labels = ['Ninguna', 'Pocas', 'Muchas']
    
    # Línea de tendencia de burbujas
    ax2.plot(times, burbujas, color='#e8a045', linewidth=2.5, marker='o', markersize=6, label='Actividad burbujas')
    ax2.fill_between(times, burbujas, alpha=0.3, color='#e8a045')
    
    # Colorear las áreas según intensidad
    if len(times) > 1:
        for i in range(len(times)-1):
            mid_color = colors_bub[burbujas[i]] if i < len(burbujas) else '#4a4a6a'
            ax2.fill_between([times[i], times[i+1]], 0, [burbujas[i], burbujas[i+1]],
                           color=mid_color, alpha=0.5)
    
    ax2.set_ylabel('Intensidad\nburbujas', color='white', fontsize=10)
    ax2.set_yticks([0, 1, 2])
    ax2.set_yticklabels(bub_labels, color='white', fontsize=8)
    ax2.set_ylim(-0.2, 2.5)
    ax2.legend(facecolor='#1a1a2e', labelcolor='white', fontsize=8, loc='upper left')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())

    # Stats
    if levels:
        elapsed = (times[-1] - times[0]).total_seconds() / 3600
        max_relative = max(relative_levels) if relative_levels else 0
        min_relative = min(relative_levels) if relative_levels else 0
        stats_txt = (f"Mediciones: {len(levels)} | "
                    f"Tiempo: {elapsed:.1f}h | "
                    f"Nivel inicial: {initial_level:.0f}% | "
                    f"Rango: {min_relative:.0f}% a {max_relative:.0f}%")
        fig.text(0.5, 0.02, stats_txt, ha='center', color='#888', fontsize=9)

    plt.xticks(rotation=30, color='white')
    plt.tight_layout(rect=[0, 0.05, 1, 1])

    if output_path is None:
        output_path = CHARTS_DIR / f"sourdough_{datetime.now().strftime('%Y%m%d_%H%M')}.png"
    
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    plt.close()
    print(f"✅ Gráfico guardado: {output_path}")
    return str(output_path)

def make_text_report(rows):
    """Reporte en texto si matplotlib no está disponible."""
    if not rows:
        return "Sin datos todavía."
    
    times = [datetime.fromisoformat(r[0]) for r in rows]
    levels = [r[1] for r in rows]
    max_level = max(levels)
    max_idx = levels.index(max_level)
    elapsed = (times[-1] - times[0]).total_seconds() / 3600
    
    report = f"""
🍞 SOURDOUGH MONITOR — Reporte
{"="*40}
Mediciones: {len(rows)}
Tiempo transcurrido: {elapsed:.1f}h
Nivel actual: {levels[-1]:.0f}%
Máximo alcanzado: {max_level:.0f}% a las {times[max_idx].strftime('%H:%M')}
Estado: {"⬇️ En descenso" if levels[-1] < max_level else "⬆️ En crecimiento"}

Historial:
"""
    for t, l, b in zip(times, levels, [r[2] for r in rows]):
        bar = "█" * int(l/10)
        report += f"  {t.strftime('%H:%M')} | {l:6.1f}% | {bar} | 🫧{b}\n"
    
    return report

if __name__ == "__main__":
    rows = load_data()
    if not rows:
        print("Sin datos todavía. Espera al menos 1 medición.")
    else:
        result = make_chart(rows)
        if isinstance(result, str) and result.endswith(".png"):
            print(f"Gráfico: {result}")
        else:
            print(result)
