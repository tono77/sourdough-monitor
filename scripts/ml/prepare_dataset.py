#!/usr/bin/env python3
"""Build the ML training dataset from the manual labeling round.

Reads data/ml_dataset/manual_labels.json (produced by scripts/labeling/server.py)
and for each entry:
  - opens the referenced photo
  - crops to the per-photo jar rectangle [izq_x_pct, tope_y_pct, der_x_pct, base_y_pct]
  - saves the crop to data/ml_dataset/crops/
  - writes an entry to labels.csv with altura_pct as the regression target

Per-photo crops let the model see a normalized jar view regardless of camera
drift between sessions, which was the whole point of the manual relabeling.

Usage:
    python scripts/ml/prepare_dataset.py
"""

import csv
import json
import os
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
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Install Pillow: pip install Pillow")

    root = find_repo_root(Path(__file__).parent)
    labels_json = root / "data" / "ml_dataset" / "manual_labels.json"
    crops_dir = root / "data" / "ml_dataset" / "crops"
    labels_csv = root / "data" / "ml_dataset" / "labels.csv"

    if not labels_json.exists():
        sys.exit(f"Manual labels not found: {labels_json}\n"
                 "Run the labeling UI first: scripts/labeling/server.py")

    with open(labels_json) as f:
        entries = json.load(f)

    print(f"Manual labels loaded: {len(entries)}")

    crops_dir.mkdir(parents=True, exist_ok=True)

    samples = []
    skipped_missing = 0
    skipped_bounds = 0

    for e in entries:
        foto_path = e.get("foto_path")
        if not foto_path or not os.path.exists(foto_path):
            skipped_missing += 1
            continue

        tope = e["tope_y_pct"]
        base = e["base_y_pct"]
        izq  = e["izq_x_pct"]
        der  = e["der_x_pct"]

        if base <= tope or der <= izq:
            skipped_bounds += 1
            continue

        try:
            img = Image.open(foto_path).convert("RGB")
            w, h = img.size
            left   = int(w * izq  / 100)
            right  = int(w * der  / 100)
            top    = int(h * tope / 100)
            bottom = int(h * base / 100)
            crop = img.crop((left, top, right, bottom))

            crop_name = f"s{e['session_id']}_m{e['id']}.jpg"
            crop.save(crops_dir / crop_name, "JPEG", quality=90)

            samples.append({
                "filename": crop_name,
                "altura_pct": round(float(e["altura_pct"]), 2),
                "session_id": e["session_id"],
                "measurement_id": e["id"],
                "timestamp": e.get("timestamp", ""),
                "cv_altura_pct": round(float(e.get("cv_altura_pct", 0)), 2),
            })
        except Exception as err:
            print(f"  Error with {foto_path}: {err}")

    with open(labels_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "filename", "altura_pct", "session_id", "measurement_id",
            "timestamp", "cv_altura_pct",
        ])
        writer.writeheader()
        writer.writerows(samples)

    print(f"\nDataset ready:")
    print(f"  Crops:              {len(samples)}")
    print(f"  Skipped (no photo): {skipped_missing}")
    print(f"  Skipped (bad box):  {skipped_bounds}")
    print(f"  Crops dir:          {crops_dir}")
    print(f"  Labels CSV:         {labels_csv}")

    if samples:
        labels = [s["altura_pct"] for s in samples]
        print(f"\nLabel distribution:")
        print(f"  Min / Max / Mean:  {min(labels):.1f}% / {max(labels):.1f}% / {sum(labels)/len(labels):.1f}%")
        buckets = [0] * 10
        for a in labels:
            buckets[min(int(a // 10), 9)] += 1
        for i, n in enumerate(buckets):
            bar = "#" * n
            print(f"  {i*10:3d}-{(i+1)*10:3d}%: {n:>3}  {bar}")


if __name__ == "__main__":
    main()
