#!/usr/bin/env python3
"""
Upload historical photos to Google Drive and update Firestore with their URLs.

This script reads all measurements from SQLite, finds ones that have a local
photo file but no Drive URL in Firestore, uploads them, and updates Firestore.

Usage: python3 upload_photos_to_drive.py [--dry-run]
"""

import sys
import os
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db import init_db, get_all_sessions, get_session_measurements
import firebase_sync as fb

DRY_RUN = "--dry-run" in sys.argv


def main():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    print(f"📸 Upload historical photos to Google Drive [{mode}]")
    print("=" * 60)

    # Init DB
    conn = init_db()

    # Init Firebase
    db_fb = fb.init_firebase()
    if not db_fb:
        print("❌ Firebase not available. Aborting.")
        return

    # Init Google Drive
    if not DRY_RUN:
        drive = fb.init_gdrive()
        if not drive:
            print("❌ Google Drive not available. Aborting.")
            return
    else:
        print("⚠️  Dry run — no uploads will happen")

    sessions = get_all_sessions(conn)
    print(f"\n📅 Found {len(sessions)} sessions in SQLite\n")

    total_uploaded = 0
    total_skipped = 0
    total_missing = 0
    total_already_done = 0
    errors = []

    for session in sessions:
        sid = session["id"]
        measurements = get_session_measurements(conn, sid)
        with_photos = [m for m in measurements if m.get("foto_path")]

        print(f"Session #{sid} ({session['fecha']}) — {len(measurements)} total, {len(with_photos)} with foto_path")

        for m in with_photos:
            foto_path = Path(m["foto_path"])
            ts = m.get("timestamp", "")
            measurement_id = ts.replace(":", "-").replace(".", "-")

            if not measurement_id:
                print(f"  ⚠️  Skipping — no timestamp (id={m.get('id')})")
                total_skipped += 1
                continue

            # Check if photo file exists on disk
            if not foto_path.exists():
                print(f"  📁 Missing on disk: {foto_path.name}")
                total_missing += 1
                continue

            # Check if Firestore doc already has foto_url
            doc_ref = (db_fb
                       .collection("sesiones").document(str(sid))
                       .collection("mediciones").document(measurement_id))

            doc = doc_ref.get()
            if doc.exists and doc.to_dict().get("foto_url"):
                total_already_done += 1
                continue  # Already has a Drive URL, skip silently

            print(f"  ⬆️  Uploading: {foto_path.name} ({foto_path.stat().st_size / 1024:.0f}KB)", end="", flush=True)

            if DRY_RUN:
                print(" [skipped — dry run]")
                total_uploaded += 1
                continue

            # Upload to Drive
            drive_info = fb.upload_photo_to_drive(str(foto_path))

            if drive_info:
                # Update Firestore doc with photo URL
                doc_ref.set({
                    "foto_url": drive_info["url"],
                    "foto_drive_id": drive_info["file_id"],
                }, merge=True)
                print(f" ✅")
                total_uploaded += 1
            else:
                print(f" ❌ Upload failed")
                errors.append(str(foto_path))

            # Small delay to avoid Drive API rate limits
            time.sleep(0.3)

    print("\n" + "=" * 60)
    print(f"✅ Uploaded:       {total_uploaded}")
    print(f"⏭️  Already done:  {total_already_done}")
    print(f"📁 Missing files: {total_missing}")
    print(f"⚠️  Errors:        {len(errors)}")

    if errors:
        print("\nFailed uploads:")
        for e in errors:
            print(f"  - {e}")

    conn.close()
    print("\n🎉 Done! Refresh the dashboard to see all photos in the gallery.")


if __name__ == "__main__":
    main()
