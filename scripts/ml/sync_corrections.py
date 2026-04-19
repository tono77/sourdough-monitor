#!/usr/bin/env python3
"""Pull manual corrections from Firestore and merge into manual_labels.json.

The dashboard's canvas editor writes corrections to Firestore with the
`manual_*` prefix. This script translates those back to the flat schema
prepare_dataset.py already understands, dedupes against the existing
manual_labels.json by (session_id, timestamp), and writes the merged file.

Run this before `prepare_dataset.py` + `train.py` whenever you want the
retraining set to pick up new dashboard corrections.

Usage:
    .venv/bin/python3 scripts/ml/sync_corrections.py
    .venv/bin/python3 scripts/ml/sync_corrections.py --dry-run
"""

import argparse
import json
import sqlite3
import sys
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without writing manual_labels.json.")
    args = ap.parse_args()

    root = find_repo_root(Path(__file__).parent)
    sys.path.insert(0, str(root / "src"))

    from sourdough.integrations.firebase import FirebaseClient
    from sourdough.config import load_config

    cfg = load_config()
    fb = FirebaseClient(cfg)
    if not fb.init():
        sys.exit("Firestore no inicializó — revisa data/firebase-service-account.json.")

    labels_path = root / "data" / "ml_dataset" / "manual_labels.json"
    labels_path.parent.mkdir(parents=True, exist_ok=True)

    existing = []
    if labels_path.exists():
        with open(labels_path) as f:
            existing = json.load(f)
    print(f"Labels existentes: {len(existing)}")

    # Key existing entries by (session_id, timestamp[:19]) for dedup.
    existing_map = {}
    for e in existing:
        key = (int(e["session_id"]), (e.get("timestamp") or "")[:19])
        existing_map[key] = e

    # Need the local DB to recover foto_path + local measurement id for each
    # correction (Firestore doesn't store foto_path).
    conn = sqlite3.connect(str(root / "data" / "fermento.db"))
    conn.row_factory = sqlite3.Row

    # Pull all sessions and scan each for manual corrections.
    sessions = fb._db.collection("sesiones").get()
    pulled = 0
    merged_new = 0
    updated = 0
    skipped_no_photo = 0

    for s in sessions:
        sid_str = s.id
        try:
            sid = int(sid_str)
        except ValueError:
            continue
        meds = (fb._db.collection("sesiones").document(sid_str)
                .collection("mediciones")
                .where("is_manual_override", "==", True).get())
        for m in meds:
            d = m.to_dict()
            if "manual_tope_y_pct" not in d or "manual_surface_y_pct" not in d:
                # Legacy is_manual_override without canvas-editor fields.
                continue
            ts = d.get("timestamp", "")
            key = (sid, ts[:19])
            pulled += 1

            # Find foto_path + local measurement id by matching timestamp prefix.
            row = conn.execute(
                "SELECT id, foto_path FROM mediciones "
                "WHERE sesion_id = ? AND timestamp LIKE ?",
                (sid, ts[:19] + "%"),
            ).fetchone()
            if not row or not row["foto_path"]:
                skipped_no_photo += 1
                continue

            entry = {
                "id": row["id"],
                "session_id": sid,
                "foto_path": row["foto_path"],
                "timestamp": ts,
                "cv_altura_pct": float(d.get("ml_altura_pct") or 0),  # legacy field
                "tope_y_pct":   float(d["manual_tope_y_pct"]),
                "base_y_pct":   float(d["manual_base_y_pct"]),
                "izq_x_pct":    float(d["manual_izq_x_pct"]),
                "der_x_pct":    float(d["manual_der_x_pct"]),
                "surface_y_pct": float(d["manual_surface_y_pct"]),
                "altura_pct":   float(d.get("altura_pct") or 0),
            }

            if key in existing_map:
                # Overwrite existing entry with the latest correction.
                existing_map[key] = entry
                updated += 1
            else:
                existing_map[key] = entry
                merged_new += 1

    conn.close()

    merged = list(existing_map.values())
    merged.sort(key=lambda e: (e["session_id"], e["timestamp"]))

    print(f"\nCorrecciones pulladas de Firestore: {pulled}")
    print(f"  Nuevas (append):       {merged_new}")
    print(f"  Actualizadas (update): {updated}")
    print(f"  Saltadas (sin foto):   {skipped_no_photo}")
    print(f"Total merged: {len(merged)}")

    # Distribution check
    buckets = [0] * 10
    for e in merged:
        a = e.get("altura_pct", 0)
        buckets[min(int(a // 10), 9)] += 1
    print("\nDistribución final por decil (altura_pct):")
    for i, n in enumerate(buckets):
        bar = "#" * n
        flag = ""
        if n < 3:
            flag = "  ⚠ cobertura baja"
        print(f"  {i*10:3d}-{(i+1)*10:3d}%: {n:>3}  {bar}{flag}")

    if args.dry_run:
        print("\n[dry-run] no se escribió manual_labels.json")
        return

    with open(labels_path, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"\nEscrito: {labels_path}")


if __name__ == "__main__":
    main()
