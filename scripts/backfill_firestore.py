#!/usr/bin/env python3
"""
Backfill Firestore with all measurements from SQLite.
Run once to recover historical data lost due to the "None" document ID bug.

Usage: python3 backfill_firestore.py
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db import init_db, get_all_sessions, get_session_measurements
import firebase_sync as fb

def main():
    print("🔄 Backfill Firestore from SQLite...")

    # Init DB
    conn = init_db()

    # Init Firebase
    db_fb = fb.init_firebase()
    if not db_fb:
        print("❌ Firebase not available. Aborting.")
        return

    sessions = get_all_sessions(conn)
    print(f"📅 Found {len(sessions)} sessions in SQLite")

    total_synced = 0
    for session in sessions:
        sid = session["id"]
        measurements = get_session_measurements(conn, sid)
        print(f"\n  Session #{sid} ({session['fecha']}) — {len(measurements)} measurements")

        # Sync session doc
        fb.sync_session(session)

        for m in measurements:
            ts = m.get("timestamp", "")
            measurement_id = ts.replace(":", "-").replace(".", "-")
            if not measurement_id:
                print(f"    ⚠️  Skipping measurement with no timestamp (id={m.get('id')})")
                continue

            doc_ref = (db_fb
                       .collection("sesiones").document(str(sid))
                       .collection("mediciones").document(measurement_id))

            doc_data = {
                "timestamp": ts,
                "nivel_pct": m.get("nivel_pct"),
                "nivel_px": m.get("nivel_px"),
                "burbujas": m.get("burbujas", ""),
                "textura": m.get("textura", ""),
                "notas": m.get("notas", ""),
                "es_peak": m.get("es_peak", 0),
                # No foto_url for historical data (Drive URLs not stored in SQLite)
            }

            doc_ref.set(doc_data, merge=True)
            total_synced += 1

        print(f"    ✅ Synced {len(measurements)} measurements")

    print(f"\n✅ Backfill complete: {total_synced} measurements synced to Firestore")
    conn.close()

if __name__ == "__main__":
    main()
