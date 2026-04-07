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
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from db import init_db, get_or_create_session, close_session, save_measurement, detect_peak, migrate_historical_data, get_latest_measurement, get_session_measurements
from analyze import analyze_photo, capture_photo
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


def run_cycle(conn, session):
    """Run one capture + analyze + chart cycle."""
    session_id = session["id"]

    # 1. Capture photo
    photo_path = capture_photo()
    if not photo_path:
        log("⚠️ Capture failed, skipping cycle")
        return None

    # 2. Get baseline from session
    baseline = conn.execute(
        "SELECT nivel_pct FROM mediciones WHERE sesion_id = ? AND nivel_pct IS NOT NULL ORDER BY id LIMIT 1",
        (session_id,)
    ).fetchone()
    baseline_nivel = baseline[0] if baseline else None

    # 3. Analyze with Claude
    try:
        analysis = analyze_photo(photo_path, baseline_nivel)
        log(f"📊 Level: {analysis.get('nivel_pct')}% | Bubbles: {analysis.get('burbujas')} | {analysis.get('notas')}")
    except Exception as e:
        log(f"⚠️ Analysis failed: {e}")
        analysis = {
            "nivel_pct": None,
            "nivel_px": None,
            "burbujas": "N/A",
            "textura": "N/A",
            "notas": f"Analysis error: {str(e)[:80]}"
        }

    # 4. Save to database
    timestamp = save_measurement(conn, session_id, photo_path, analysis)

    # 5. Detect peak
    is_peak, peak_info = detect_peak(conn, session_id)
    if is_peak:
        log(f"🎯 PEAK DETECTED! Level: {peak_info['nivel']}% at {peak_info['timestamp']}")
        send_peak_alert(session, peak_info)

    # 5b. Sync to Firebase + Google Drive
    drive_url = None
    if FIREBASE_ENABLED:
        try:
            drive_info = fb_sync.sync_full_cycle(
                session=session,
                measurement={"id": None, "timestamp": timestamp, **analysis},
                photo_path=photo_path
            )
            if drive_info:
                drive_url = drive_info.get("url")
        except Exception as e:
            log(f"⚠️ Firebase sync error (continuing): {e}")

    # 6. Generate chart
    try:
        rows = load_session_data(conn, session_id)
        if rows:
            make_chart(rows, session_info=session)
    except Exception as e:
        log(f"⚠️ Chart generation failed: {e}")

    return analysis, drive_url


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
    email_interval = 1800  # 30 minutes
    last_email_time = None

    log(f"🍞 Sourdough Monitor started")
    log(f"   Capture interval: {capture_interval}s ({capture_interval/60:.0f} min)")
    log(f"   Email interval: {email_interval}s ({email_interval/60:.0f} min)")
    log(f"   Active hours: {config.get('schedule', {}).get('start_hour', 7)}:{config.get('schedule', {}).get('start_minute', 30):02d} - {config.get('schedule', {}).get('end_hour', 23)}:{config.get('schedule', {}).get('end_minute', 59):02d}")

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

        # Send email every 30 minutes
        now = time.time()
        if last_email_time is None or (now - last_email_time) >= email_interval:
            try:
                latest = get_latest_measurement(conn, session["id"])
                measurements = get_session_measurements(conn, session["id"])
                elapsed = 0
                if session.get("hora_inicio"):
                    start = datetime.fromisoformat(session["hora_inicio"])
                    elapsed = (datetime.now() - start).total_seconds() / 3600

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
