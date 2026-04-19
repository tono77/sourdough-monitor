#!/usr/bin/env python3
"""Run MLPredictor against past measurements and write ml_altura_pct to Firestore.

Useful after deploying the new Firestore schema so the dashboard can show
historical ML predictions without waiting for fresh captures.

By default, only processes measurements from today. Use --since or --days
to widen the window.

Usage:
    .venv/bin/python3 scripts/ml/backfill_ml_altura.py                  # today
    .venv/bin/python3 scripts/ml/backfill_ml_altura.py --days 3         # last 3 days
    .venv/bin/python3 scripts/ml/backfill_ml_altura.py --since 2026-04-10
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(10):
        if (p / "data" / "fermento.db").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    sys.exit("Could not locate data/fermento.db walking up from the script.")


def main():
    ap = argparse.ArgumentParser(description="Backfill ml_altura_pct on past measurements.")
    ap.add_argument("--days", type=int, default=None,
                    help="Process the last N days (default: today only).")
    ap.add_argument("--since", type=str, default=None,
                    help="ISO date (YYYY-MM-DD). Process measurements on or after this date.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without writing to Firestore.")
    args = ap.parse_args()

    root = find_repo_root(Path(__file__).parent)
    sys.path.insert(0, str(root / "src"))

    # Compute the start timestamp cutoff.
    if args.since:
        cutoff = args.since
    elif args.days is not None:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
    else:
        cutoff = datetime.now().strftime("%Y-%m-%d")

    print(f"Cutoff: timestamp >= {cutoff}")

    # Local DB has the foto_path; Firestore has the doc we need to update.
    conn = sqlite3.connect(str(root / "data" / "fermento.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT m.id, m.sesion_id, m.timestamp, m.foto_path,
               m.altura_pct AS current_altura,
               s.tope_y_pct, s.base_y_pct, s.izq_x_pct, s.der_x_pct,
               s.is_calibrated
        FROM mediciones m
        LEFT JOIN sesiones s ON s.id = m.sesion_id
        WHERE m.timestamp >= ?
          AND m.foto_path IS NOT NULL
        ORDER BY m.timestamp ASC
    """, (cutoff,)).fetchall()
    conn.close()

    print(f"Mediciones encontradas: {len(rows)}")
    if not rows:
        print("Nada que backfillear.")
        return

    # Initialize model (uses .venv's torch).
    from sourdough.services.ml_predictor import MLPredictor
    from sourdough.models import CalibrationBounds
    predictor = MLPredictor(root / "data" / "ml_model.pth")
    if not predictor.is_ready:
        sys.exit("MLPredictor no cargó — revisa data/ml_model.pth y el entorno torch.")

    # Initialize Firestore (unless dry-run).
    fb = None
    if not args.dry_run:
        from sourdough.integrations.firebase import FirebaseClient
        from sourdough.config import load_config
        cfg = load_config()
        fb = FirebaseClient(cfg)
        if not fb.init():
            sys.exit("Firestore no inicializó — revisa data/firebase-service-account.json.")

    processed = updated = skipped_missing = skipped_failed = 0
    for r in rows:
        foto_path = r["foto_path"]
        if not os.path.exists(foto_path):
            skipped_missing += 1
            continue

        cal = CalibrationBounds(
            izq_x_pct=r["izq_x_pct"], der_x_pct=r["der_x_pct"],
            tope_y_pct=r["tope_y_pct"], base_y_pct=r["base_y_pct"],
            fondo_y_pct=None,
        ) if r["is_calibrated"] else None

        pred = predictor.predict(foto_path, cal)
        processed += 1
        if pred is None:
            skipped_failed += 1
            continue

        ts = r["timestamp"]
        sid = r["sesion_id"]
        doc_id = ts.replace(":", "-").replace(".", "-")
        current = r["current_altura"]
        delta = (pred - current) if isinstance(current, (int, float)) else None
        delta_str = f"Δ={delta:+.1f}%" if delta is not None else "(sin altura fusionada)"

        print(f"  s{sid} {ts[:19]} — ML={pred:.1f}% · fused={current if current is not None else '—'}  {delta_str}")

        if args.dry_run:
            continue

        try:
            doc_ref = (
                fb._db.collection("sesiones").document(str(sid))
                .collection("mediciones").document(doc_id)
            )
            doc_ref.set({"ml_altura_pct": pred}, merge=True)
            updated += 1
        except Exception as e:
            print(f"    ! Error actualizando: {e}")
            skipped_failed += 1

    print("\nResumen:")
    print(f"  Procesadas:            {processed}")
    print(f"  Actualizadas (FS):     {updated}{' (dry-run)' if args.dry_run else ''}")
    print(f"  Sin foto en disco:     {skipped_missing}")
    print(f"  Errores de modelo/FS:  {skipped_failed}")


if __name__ == "__main__":
    main()
