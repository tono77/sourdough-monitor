#!/usr/bin/env python3
"""Prepare ML training dataset from existing photos + DB labels.

Extracts calibrated crops from photos, pairs them with altura labels,
and saves to data/ml_dataset/ with a labels.csv for training.

Usage:
    python scripts/ml/prepare_dataset.py
"""

import csv
import os
import sqlite3
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Install Pillow: pip install Pillow")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "fermento.db"
OUTPUT_DIR = BASE_DIR / "data" / "ml_dataset"

# Default crop boundaries for uncalibrated sessions (center 60% of image)
DEFAULT_CROP = {
    "izq_x_pct": 25.0,
    "der_x_pct": 75.0,
    "tope_y_pct": 20.0,
    "base_y_pct": 85.0,
}


def get_calibration(conn, session_id):
    """Get calibration bounds for a session, falling back to defaults."""
    row = conn.execute(
        "SELECT izq_x_pct, der_x_pct, tope_y_pct, base_y_pct, fondo_y_pct, is_calibrated "
        "FROM sesiones WHERE id = ?",
        (session_id,),
    ).fetchone()

    if row and row[5] == 1 and row[0] is not None and row[1] is not None:
        return {
            "izq_x_pct": row[0],
            "der_x_pct": row[1],
            "tope_y_pct": row[2],
            "base_y_pct": row[3],
            "fondo_y_pct": row[4],
            "calibrated": True,
        }
    return {**DEFAULT_CROP, "fondo_y_pct": None, "calibrated": False}


def crop_jar(img, calib):
    """Crop the jar region from a photo using calibration bounds."""
    w, h = img.size
    left = int(w * calib["izq_x_pct"] / 100)
    right = int(w * calib["der_x_pct"] / 100)
    top = int(h * calib["tope_y_pct"] / 100)
    bottom = int(h * calib["base_y_pct"] / 100)
    return img.crop((left, top, right, bottom))


def compute_label(row, calib):
    """Determine the best available label for this measurement.

    Priority:
    1. altura_pct (v2 fused, most reliable) — not yet populated
    2. altura_y_pct (OpenCV or Claude single mode absolute position)
    3. Estimate from nivel_pct if calibration available

    Returns altura_pct (0-100 of jar) or None.
    """
    # v2 fused position
    if row["altura_pct"] is not None:
        return float(row["altura_pct"])

    # OpenCV/Claude absolute position
    if row["altura_y_pct"] is not None:
        return float(row["altura_y_pct"])

    # Skip measurements without usable labels
    return None


def main():
    if not DB_PATH.exists():
        sys.exit(f"Database not found: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Fetch all measurements with photos
    rows = conn.execute("""
        SELECT m.id, m.sesion_id, m.foto_path, m.nivel_pct,
               m.altura_y_pct, m.altura_pct, m.burbujas, m.textura,
               m.timestamp, m.confianza
        FROM mediciones m
        WHERE m.foto_path IS NOT NULL
        ORDER BY m.id ASC
    """).fetchall()

    print(f"Total measurements with photos: {len(rows)}")

    # Prepare output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    crops_dir = OUTPUT_DIR / "crops"
    crops_dir.mkdir(exist_ok=True)

    # Cache calibration per session
    calib_cache = {}
    samples = []
    skipped_no_label = 0
    skipped_no_photo = 0

    for row in rows:
        row = dict(row)
        foto_path = row["foto_path"]

        # Check photo exists
        if not os.path.exists(foto_path):
            skipped_no_photo += 1
            continue

        # Get label
        session_id = row["sesion_id"]
        if session_id not in calib_cache:
            calib_cache[session_id] = get_calibration(conn, session_id)
        calib = calib_cache[session_id]

        label = compute_label(row, calib)
        if label is None:
            skipped_no_label += 1
            continue

        # Crop and save
        try:
            img = Image.open(foto_path)
            cropped = crop_jar(img, calib)
            crop_filename = f"s{session_id}_{Path(foto_path).stem}.jpg"
            crop_path = crops_dir / crop_filename
            cropped.save(crop_path, "JPEG", quality=90)

            samples.append({
                "filename": crop_filename,
                "altura_pct": round(label, 2),
                "session_id": session_id,
                "calibrated": calib["calibrated"],
                "burbujas": row["burbujas"] or "",
                "textura": row["textura"] or "",
                "timestamp": row["timestamp"] or "",
            })
        except Exception as e:
            print(f"  Error processing {foto_path}: {e}")

    conn.close()

    # Write labels CSV
    labels_path = OUTPUT_DIR / "labels.csv"
    with open(labels_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "filename", "altura_pct", "session_id", "calibrated",
            "burbujas", "textura", "timestamp",
        ])
        writer.writeheader()
        writer.writerows(samples)

    print(f"\nDataset prepared:")
    print(f"  Samples: {len(samples)}")
    print(f"  Skipped (no label): {skipped_no_label}")
    print(f"  Skipped (no photo): {skipped_no_photo}")
    print(f"  Crops: {crops_dir}")
    print(f"  Labels: {labels_path}")

    # Show distribution
    if samples:
        labels = [s["altura_pct"] for s in samples]
        print(f"\nLabel distribution:")
        print(f"  Min: {min(labels):.1f}%")
        print(f"  Max: {max(labels):.1f}%")
        print(f"  Mean: {sum(labels)/len(labels):.1f}%")
        calibrated_count = sum(1 for s in samples if s["calibrated"])
        print(f"  Calibrated: {calibrated_count}/{len(samples)} ({calibrated_count/len(samples)*100:.0f}%)")


if __name__ == "__main__":
    main()
