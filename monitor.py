#!/usr/bin/env python3
"""
Sourdough Monitor — Main Orchestrator
Manages fermentation sessions, capture cycles, analysis, notifications, and dashboard.

Usage:
    python3 monitor.py              # Start monitoring (capture + analyze + dashboard)
    python3 monitor.py --dashboard  # Start dashboard only (no capture)
"""

import sys
import os
import json
import time
import signal
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import db
from db import init_db, get_or_create_session, close_session, save_measurement, detect_peak, migrate_historical_data, get_latest_measurement, get_session_measurements, get_baseline_foto
from analyze import analyze_photo, capture_photo
import timelapse
from chart import load_session_data, make_chart
from notify import send_update_email, send_peak_alert
from dashboard import run_server

# Firebase + Google Drive sync (optional — gracefully disabled if not configured)
try:
    import firebase_sync as fb_sync
    FIREBASE_ENABLED = True
except ImportError:
    FIREBASE_ENABLED = False

CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "data" / "sourdough.log"

# Global flag for graceful shutdown
running = True


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def log(msg):
    """Log message to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_in_active_hours(config):
    """Check if current time is within monitoring hours."""
    now = datetime.now()
    schedule = config.get("schedule", {})
    start_h = schedule.get("start_hour", 7)
    start_m = schedule.get("start_minute", 30)
    end_h = schedule.get("end_hour", 23)
    end_m = schedule.get("end_minute", 59)

    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=end_m, second=59, microsecond=0)

    return start <= now <= end


def seconds_until_start(config):
    """Calculate seconds until next monitoring window opens."""
    now = datetime.now()
    schedule = config.get("schedule", {})
    start_h = schedule.get("start_hour", 7)
    start_m = schedule.get("start_minute", 30)

    next_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    if next_start <= now:
        next_start += timedelta(days=1)

    return (next_start - now).total_seconds()


def flash_screen():
    """Produce a 'soft flash' by turning on the screen and opening a blank white page."""
    try:
        # Wake display
        subprocess.run(["caffeinate", "-u", "-t", "2"], check=False)
        # Create a blank white HTML file
        flash_file = Path("data/flash.html").resolve()
        with open(flash_file, "w") as f:
            f.write("<html><body style='background-color:white; margin:0;'></body></html>")
        # Open in Safari to bounce light
        subprocess.run(["open", "-a", "Safari", str(flash_file)], check=False)
        time.sleep(1.5) # Wait for Safari to render the white page
    except Exception as e:
        log(f"⚠️ Soft flash warning: {e}")

def restore_screen():
    """Close the blank white page."""
    try:
        subprocess.run(["osascript", "-e", 'tell application "Safari" to close front window'], check=False)
    except Exception:
        pass


def run_cycle(conn, session):
    """Run a single capture and analyze cycle."""
    session_id = session["id"]
    analysis = None
    uploaded_photo = None

    # 0. Soft Flash for night captures
    flash_screen()

    # 1. Capture photo
    photo_path = capture_photo()
    
    # 0.5 Restore screen
    restore_screen()

    if not photo_path:
        log("⚠️ Capture failed, skipping cycle")
        return None

    path_obj = Path(photo_path)
    log(f"✅  Foto: {path_obj.name}")

    # Upload to Drive in background
    uploaded_photo = None
    if FIREBASE_ENABLED:
        uploaded_photo = fb_sync.upload_photo_to_drive(photo_path)
        if uploaded_photo:
            log(f"📤 Photo uploaded to Drive: {path_obj.name}")

    # 2. Extract baseline
    baseline_row = conn.execute(
        "SELECT nivel_pct FROM mediciones WHERE sesion_id = ? AND nivel_pct IS NOT NULL ORDER BY id ASC LIMIT 1",
        (session_id,)
    ).fetchone()
    baseline_nivel = float(baseline_row[0]) if baseline_row else None
    baseline_foto = get_baseline_foto(conn, session_id)  # path to first photo of session

    # 2b. Pull calibration bounds and user corrections from Firestore
    corrections_file = Path("data/dataset_corrections.json")
    if FIREBASE_ENABLED:
        try:
            calib = fb_sync.pull_calibration(session_id)
            if calib:
                conn.execute(
                    "UPDATE sesiones SET fondo_y_pct = ?, tope_y_pct = ?, is_calibrated = 1 WHERE id = ?",
                    (calib["fondo_y_pct"], calib["tope_y_pct"], session_id)
                )
                conn.commit()
                log(f"📐 Calibración sincronizada: fondo={calib['fondo_y_pct']:.1f}%, tope={calib['tope_y_pct']:.1f}%")
            
            # Pull user corrections (Few-shot learning examples)
            corrections = fb_sync.pull_corrections(session_id)
            if corrections:
                import json
                corrections_file.parent.mkdir(exist_ok=True)
                with open(corrections_file, "w") as f:
                    json.dump(corrections, f, indent=2)
                log(f"🧠 {len(corrections)} correcciones manuales cargadas para In-Context Learning.")
        except Exception as e:
            log(f"⚠️ Failed to pull firebase data: {e}")

    # Compute elapsed time since first measurement
    first_ts = conn.execute(
        "SELECT MIN(timestamp) FROM mediciones WHERE sesion_id = ?",
        (session_id,)
    ).fetchone()[0]
    
    # 3. Analyze image
    log("🤖  Enviando foto a motor IA local...")
    try:
        analysis = analyze_photo(photo_path, baseline_foto)
        log("\n📊  Resultado Motor Local:")
        log(json.dumps(analysis, indent=4))
        
        # 4. Save to DB
        measurement = db.save_measurement(
            conn, session_id, photo_path, analysis
        )
        if measurement:
            if FIREBASE_ENABLED:
                fb_sync.sync_measurement(session_id, measurement, uploaded_photo)
                
            # Render static chart
            log("📈  Generando gráfico actualizado...")
            try:
                make_chart(load_session_data(conn, session_id), session_info=session)
            except Exception as e:
                log(f"⚠️ Chart error: {e}")
            
            # --- 5. Timelapse Generation ---
            log("🎬  Generando MP4 Timelapse...")
            mp4_path = timelapse.generate_timelapse(session_id, conn)
            if mp4_path and FIREBASE_ENABLED:
                # Retrieve current session to check for old timelapse file ID
                curr_session = session
                old_file_id = curr_session.get("timelapse_file_id") if curr_session else None
                
                vid_data = fb_sync.upload_video_to_drive(mp4_path, old_file_id)
                if vid_data:
                    # Update local DB
                    conn.execute("UPDATE sesiones SET timelapse_url = ?, timelapse_file_id = ? WHERE id = ?",
                                 (vid_data["url"], vid_data["file_id"], session_id))
                    conn.commit()
                    # Sync to Firebase
                    fb_sync.sync_session(dict(curr_session, timelapse_url=vid_data["url"], timelapse_file_id=vid_data["file_id"]))
                    log(f"🎬 Timelapse MP4 subido a Drive! ({vid_data['url']})")

            # Check peak
            if measurement.get('es_peak'):
                log("🎯 ¡PEAK ALCANZADO!")
        else:
            log("⚠️ Failed to save measurement")
            
    except Exception as e:
        log(f"❌  Error análisis: {str(e)}")

    return analysis, (uploaded_photo["url"] if uploaded_photo else None)


def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    global running
    log("🛑 Shutdown signal received, finishing current cycle...")
    running = False


def main():
    global running

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    dashboard_only = "--dashboard" in sys.argv
    config = load_config()

    # Initialize database
    conn = init_db()

    # Initialize Firebase + Drive sync
    if FIREBASE_ENABLED:
        try:
            fb_sync.init_all()
        except Exception as e:
            log(f"⚠️ Firebase sync init failed (continuing without sync): {e}")
    migrate_historical_data(conn)

    # Start dashboard server in background thread
    dashboard_config = config.get("dashboard", {})
    port = dashboard_config.get("port", 8080)
    host = dashboard_config.get("host", "0.0.0.0")

    dashboard_thread = threading.Thread(
        target=run_server,
        args=(host, port),
        daemon=True
    )
    dashboard_thread.start()
    log(f"🌐 Dashboard: http://localhost:{port}")

    if dashboard_only:
        log("📊 Dashboard-only mode. Press Ctrl+C to stop.")
        while running:
            time.sleep(1)
        return

    # Monitoring mode
    capture_interval = config.get("capture", {}).get("interval_seconds", 300)
    schedule = config.get("schedule", {})
    email_interval = schedule.get("email_interval_seconds", 3600)
    last_email_time = None

    log(f"🍞 Sourdough Monitor started")
    log(f"   Capture interval: {capture_interval}s ({capture_interval/60:.0f} min)")
    log(f"   Email interval: {email_interval}s ({email_interval/60:.0f} min)")
    log(f"   Active hours: {schedule.get('start_hour', 7)}:{schedule.get('start_minute', 0):02d} - {schedule.get('end_hour', 23)}:{schedule.get('end_minute', 0):02d} (monitoring + emails)")
    log(f"   Outside hours: process keeps running, no captures/emails")

    while running:
        config = load_config()  # Reload config each cycle

        if not is_in_active_hours(config):
            # Close any active session
            try:
                session = get_or_create_session(conn)
                if session.get("estado") == "activa":
                    close_session(conn, session["id"])
                    log(f"🌙 Session #{session['id']} closed (outside active hours)")
            except Exception:
                pass

            wait_secs = seconds_until_start(config)
            log(f"💤 Outside active hours. Next window in {wait_secs/3600:.1f}h")

            # Sleep in small increments to allow shutdown
            sleep_until = time.time() + wait_secs
            while running and time.time() < sleep_until:
                time.sleep(5)
            continue

        # Get or create today's session
        session = get_or_create_session(conn)
        log(f"📋 Session #{session['id']} ({session['fecha']})")

        # Run capture + analyze cycle
        analysis, drive_url = run_cycle(conn, session)

        # Send email every hour
        now = time.time()
        if last_email_time is None or (now - last_email_time) >= email_interval:
            try:
                latest = get_latest_measurement(conn, session["id"])
                measurements = get_session_measurements(conn, session["id"])
                elapsed = 0
                if session.get("hora_inicio"):
                    start = datetime.fromisoformat(session["hora_inicio"])
                    elapsed = (datetime.now() - start).total_seconds() / 3600

                # Normalize nivel: first measurement = 0%, rest = delta from baseline
                valid = [m for m in measurements if m.get("nivel_pct") is not None]
                if latest and latest.get("nivel_pct") is not None and valid:
                    baseline = float(valid[0]["nivel_pct"])
                    norm_nivel = round(float(latest["nivel_pct"]) - baseline, 1)
                    latest = {**latest, "nivel_pct": norm_nivel}

                send_update_email(session, latest, len(measurements), elapsed,
                                  photo_url=drive_url)
                last_email_time = now
            except Exception as e:
                log(f"⚠️ Email error: {e}")
                last_email_time = now  # Don't retry immediately

        # Wait for next cycle
        log(f"⏳ Next capture in {capture_interval}s ({capture_interval/60:.0f} min)")
        sleep_until = time.time() + capture_interval
        while running and time.time() < sleep_until:
            time.sleep(2)

    # Graceful shutdown
    log("👋 Monitor stopped")
    conn.close()


if __name__ == "__main__":
    main()
