#!/usr/bin/env python3
"""Stratified sampler for the manual labeling round.

Picks up to N photos per decile of the current CV altura_pct reading,
so the ML retraining set covers the full 0-100 range instead of
collapsing on the 40-60% band where the old fused labels clustered.

Output: data/ml_dataset/samples_to_label.json

Usage:
    python scripts/labeling/select_samples.py [--per-bucket 25] [--seed 42]
"""

import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path


def find_repo_root(start: Path) -> Path:
    """Walk up from `start` until we see data/fermento.db (supports worktrees)."""
    p = start.resolve()
    for _ in range(10):
        if (p / "data" / "fermento.db").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    sys.exit("Could not locate data/fermento.db walking up from the script.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-bucket", type=int, default=25,
                    help="Max samples per 10%% decile (default: 25 → 250 total)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", type=Path, default=None,
                    help="Override output path")
    args = ap.parse_args()

    root = find_repo_root(Path(__file__).parent)
    db_path = root / "data" / "fermento.db"
    output = args.output or (root / "data" / "ml_dataset" / "samples_to_label.json")
    output.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT m.id, m.sesion_id, m.foto_path, m.timestamp,
               m.altura_pct AS cv_altura_pct,
               s.tope_y_pct, s.base_y_pct, s.izq_x_pct, s.der_x_pct,
               s.is_calibrated
        FROM mediciones m
        LEFT JOIN sesiones s ON s.id = m.sesion_id
        WHERE m.foto_path IS NOT NULL
          AND m.altura_pct IS NOT NULL
    """).fetchall()
    conn.close()

    # Filter to photos that exist on disk
    valid = [dict(r) for r in rows if os.path.exists(r["foto_path"])]
    print(f"Mediciones con foto+altura en DB: {len(rows)}")
    print(f"Con foto en disco: {len(valid)}")

    # Stratify into 10 deciles
    buckets: dict[int, list[dict]] = {i: [] for i in range(10)}
    for r in valid:
        a = r["cv_altura_pct"]
        idx = min(int(a // 10), 9)
        buckets[idx].append(r)

    print("\nDisponibles por decil (antes de muestreo):")
    for i in range(10):
        lo, hi = i * 10, (i + 1) * 10
        print(f"  {lo:3d}-{hi:3d}%: {len(buckets[i])}")

    rng = random.Random(args.seed)
    picked: list[dict] = []
    for i in range(10):
        pool = buckets[i]
        if not pool:
            continue
        k = min(args.per_bucket, len(pool))
        picked.extend(rng.sample(pool, k))

    # Shuffle the final order so sessions/deciles don't clump during labeling
    rng.shuffle(picked)

    # Shape output: only what the UI needs
    samples = []
    for r in picked:
        samples.append({
            "id": r["id"],
            "session_id": r["sesion_id"],
            "foto_path": r["foto_path"],
            "timestamp": r["timestamp"],
            "cv_altura_pct": round(r["cv_altura_pct"], 1),
            "calibration": {
                "tope_y_pct": r["tope_y_pct"],
                "base_y_pct": r["base_y_pct"],
                "izq_x_pct": r["izq_x_pct"],
                "der_x_pct": r["der_x_pct"],
                "is_calibrated": bool(r["is_calibrated"]),
            },
        })

    with open(output, "w") as f:
        json.dump(samples, f, indent=2)

    print(f"\nSeleccionadas: {len(samples)}")
    print(f"Escritas a: {output}")


if __name__ == "__main__":
    main()
