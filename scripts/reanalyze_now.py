#!/usr/bin/env python3
"""
Toma una foto AHORA y la analiza con el prompt nuevo (comparativo).
Guarda el resultado en SQLite y sincroniza a Firestore para que el
dashboard se actualice inmediatamente.
"""

import sys, json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from analyze import analyze_photo, capture_photo
from db import init_db, get_baseline_foto, get_or_create_session, save_measurement, detect_peak

try:
    import firebase_sync as fb_sync
    FIREBASE_ENABLED = True
except ImportError:
    FIREBASE_ENABLED = False

print("=" * 60)
print("🔁  Re-análisis con prompt actualizado")
print("=" * 60)

conn = init_db()
session = get_or_create_session(conn)
session_id = session["id"]
print(f"📋  Sesión #{session_id} ({session['fecha']})")

# ── Baseline photo for comparative analysis ──────────────────────
baseline_foto = get_baseline_foto(conn, session_id)
mode = "comparativo" if baseline_foto else "single"
print(f"🖼  Modo: {mode}" + (f"  |  baseline: {Path(baseline_foto).name}" if baseline_foto else ""))

# ── Elapsed time ─────────────────────────────────────────────────
first_ts = conn.execute(
    "SELECT timestamp FROM mediciones WHERE sesion_id = ? ORDER BY id LIMIT 1",
    (session_id,)
).fetchone()
tiempo_min = None
if first_ts:
    try:
        inicio = datetime.fromisoformat(first_ts[0])
        tiempo_min = (datetime.now() - inicio).total_seconds() / 60
        print(f"⏱  Tiempo transcurrido: {tiempo_min:.0f} min")
    except Exception:
        pass

# ── Capture ──────────────────────────────────────────────────────
print("\n📸  Capturando foto...")
photo_path = capture_photo()
if not photo_path:
    print("❌  Captura falló — verifica la cámara")
    sys.exit(1)
print(f"✅  Foto: {Path(photo_path).name}")

# ── Analyze ──────────────────────────────────────────────────────
print("\n🤖  Enviando a Claude (prompt nuevo)...")
try:
    analysis = analyze_photo(
        photo_path,
        baseline_foto_path=baseline_foto,
        baseline_nivel=None,
        tiempo_min=tiempo_min
    )
    print(f"\n📊  Resultado Claude:")
    print(json.dumps(analysis, indent=4, ensure_ascii=False))
except Exception as e:
    print(f"❌  Error Claude: {e}")
    sys.exit(1)

# ── Save to DB ───────────────────────────────────────────────────
measurement = save_measurement(conn, session_id, photo_path, analysis)
timestamp = measurement["timestamp"]
print(f"\n💾  Guardado en SQLite: {timestamp}")

# ── Sync to Firebase ─────────────────────────────────────────────
if FIREBASE_ENABLED:
    try:
        fb_sync.init_all()
        drive_info = fb_sync.sync_full_cycle(
            session=session,
            measurement=measurement,
            photo_path=photo_path
        )
        url = drive_info.get("url") if drive_info else None
        print(f"☁️   Sincronizado a Firestore  |  Drive URL: {url or 'N/A'}")
    except Exception as e:
        print(f"⚠️   Firebase sync error: {e}")
else:
    print("⚠️   Firebase no configurado — solo guardado local")

# ── Summary ──────────────────────────────────────────────────────
nivel = analysis.get("nivel_pct")
baseline_row = conn.execute(
    "SELECT nivel_pct FROM mediciones WHERE sesion_id = ? AND nivel_pct IS NOT NULL ORDER BY id LIMIT 1",
    (session_id,)
).fetchone()
baseline_val = float(baseline_row[0]) if baseline_row else None

print("\n" + "=" * 60)
if nivel is not None and baseline_val is not None:
    growth = nivel - baseline_val
    print(f"✅  nivel_pct    : {nivel:.0f}")
    print(f"   baseline     : {baseline_val:.0f}")
    print(f"   crecimiento  : +{max(0, growth):.0f}%")
    print(f"   confianza    : {analysis.get('confianza', '?')}/5")
    alt_i = analysis.get('altura_inicial_pct')
    alt_a = analysis.get('altura_actual_pct')
    if alt_i and alt_a:
        print(f"   altura inicio: {alt_i}% frasco")
        print(f"   altura actual: {alt_a}% frasco")
else:
    print("⚠️   nivel_pct null — Claude no pudo medir")
print("=" * 60)
print("🌐  El dashboard debería actualizarse en ~5 segundos")

conn.close()
