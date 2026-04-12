"""Main orchestrator — slim loop that delegates to injected services.

Replaces the old 376-line god-object monitor.py.
"""

import json
import logging
import signal
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from sourdough.config import AppConfig
from sourdough.db.connection import DatabaseManager
from sourdough.db.repository import (
    MeasurementRepository,
    SessionRepository,
    migrate_historical_data,
)
from sourdough.models import CalibrationBounds, Session
from sourdough.services import capture as capture_svc
from sourdough.services import charting, peak_detector, timelapse
from sourdough.services.analyzer import analyze_photo, run_opencv
from sourdough.services.measurement import compute_measurement
from sourdough.services.notifier import send_peak_alert, send_update_email

log = logging.getLogger(__name__)


class Monitor:
    """Orchestrates the capture → analyze → save → sync → notify pipeline."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._running = True
        self._db = DatabaseManager(config.db_path)
        self._firebase = None
        self._gdrive = None
        self._ml_predictor = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self, dashboard_only: bool = False) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._db.initialize()
        conn = self._db.connect()
        migrate_historical_data(conn)

        # Initialize Firebase (optional)
        self._init_integrations()

        if dashboard_only:
            log.info("Dashboard-only mode. Press Ctrl+C to stop.")
            while self._running:
                time.sleep(1)
            return

        # Monitoring mode
        interval = self.config.capture.interval_seconds
        email_interval = self.config.schedule.email_interval_seconds
        last_email_time: Optional[float] = None

        sched = self.config.schedule
        log.info("Sourdough Monitor started")
        log.info("  Capture interval: %ds (%d min)", interval, interval // 60)
        log.info("  Email interval: %ds (%d min)", email_interval, email_interval // 60)
        log.info("  Active hours: %02d:%02d - %02d:%02d",
                 sched.start_hour, sched.start_minute, sched.end_hour, sched.end_minute)

        while self._running:
            # Check hibernation
            if self._check_hibernation():
                self._sleep(60)
                continue

            # Get or create session
            sessions = SessionRepository(conn)
            measurements = MeasurementRepository(conn)
            session = sessions.get_or_create_today()
            log.info("Session #%d (%s)", session.id, session.fecha)

            # Run cycle
            drive_url = self._run_cycle(conn, session, sessions, measurements)

            # Email notification
            now = time.time()
            if last_email_time is None or (now - last_email_time) >= email_interval:
                self._send_email(session, measurements, drive_url)
                last_email_time = now

            # Wait for next cycle
            log.info("Next capture in %ds (%d min)", interval, interval // 60)
            self._sleep(interval)

        log.info("Monitor stopped")
        self._db.close()

    # ------------------------------------------------------------------
    # Cycle
    # ------------------------------------------------------------------

    def _run_cycle(
        self,
        conn,
        session: Session,
        sessions: SessionRepository,
        measurements: MeasurementRepository,
    ) -> Optional[str]:
        """Run a single capture → analyze → save → sync cycle."""
        drive_url = None

        # Flash screen for night captures
        capture_svc.flash_screen()
        photo_path = capture_svc.capture_photo(self.config)
        capture_svc.restore_screen()

        if not photo_path:
            log.warning("Capture failed, skipping cycle")
            return None

        log.info("Foto: %s", Path(photo_path).name)

        # Upload to Drive
        uploaded_photo = None
        if self._gdrive:
            uploaded_photo = self._gdrive.upload_photo(photo_path)
            if uploaded_photo:
                log.info("Photo uploaded to Drive: %s", Path(photo_path).name)
                drive_url = uploaded_photo.get("url")

        # Pull calibration from Firebase
        if self._firebase:
            self._sync_calibration(session, sessions)
            self._sync_corrections(session, measurements)

        # Refresh session after potential calibration update
        session = sessions.get_by_id(session.id)

        # Baseline
        baseline_foto = measurements.get_baseline_foto(session.id)

        # Corrections file
        corrections_file = self.config.data_dir / "dataset_corrections.json"

        # Analyze: Claude Vision
        log.info("Enviando foto a Claude Vision...")
        try:
            claude_result = analyze_photo(
                config=self.config,
                photo_path=photo_path,
                baseline_foto_path=baseline_foto,
                corrections_file=corrections_file if corrections_file.exists() else None,
            )
            log.info("Claude: %s", json.dumps(claude_result, indent=2, ensure_ascii=False))

            # Analyze: OpenCV (independent)
            cv_altura = None
            calibration = session.calibration if session.is_calibrated else None
            if calibration and calibration.is_complete:
                try:
                    cv_altura = run_opencv(photo_path, calibration)
                    if cv_altura is not None:
                        log.info("OpenCV: altura=%.1f%%", cv_altura)
                except Exception as e:
                    log.warning("OpenCV error: %s", e)

            # ML model prediction (independent)
            ml_altura = None
            if self._ml_predictor and self._ml_predictor.is_ready:
                try:
                    ml_altura = self._ml_predictor.predict(photo_path, calibration)
                    if ml_altura is not None:
                        log.info("ML: altura=%.1f%%", ml_altura)
                except Exception as e:
                    log.warning("ML prediction error: %s", e)

            # Fuse all measurements and calculate growth
            baseline_altura = measurements.get_baseline_altura(session.id)
            merged = compute_measurement(claude_result, cv_altura, baseline_altura, ml_altura)

            # Save to DB
            measurement = measurements.save(session.id, photo_path, merged)

            # Sync to Firebase
            if self._firebase:
                self._firebase.sync_measurement(session.id, measurement.to_dict(), uploaded_photo)

            # Chart
            log.info("Generando gráfico...")
            try:
                rows = measurements.get_chart_data(session.id)
                charting.make_chart(rows, self.config.charts_dir, session=session)
            except Exception as e:
                log.warning("Chart error: %s", e)

            # Timelapse
            log.info("Generando timelapse...")
            all_measurements = measurements.get_by_session(session.id)
            mp4_path = timelapse.generate_timelapse(session.id, all_measurements, self.config.data_dir)
            if mp4_path and self._gdrive:
                old_file_id = session.timelapse_file_id
                vid_data = self._gdrive.upload_video(mp4_path, old_file_id)
                if vid_data:
                    sessions.update_timelapse(session.id, vid_data["url"], vid_data["file_id"])
                    if self._firebase:
                        updated = sessions.get_by_id(session.id)
                        self._firebase.sync_session(sessions.to_dict(updated))
                    log.info("Timelapse uploaded to Drive")

            # Peak detection
            if measurement.es_peak:
                log.info("PEAK ALCANZADO!")
            else:
                self._check_peak(session, measurements, sessions)

        except Exception as e:
            log.error("Error análisis: %s", e)

        return drive_url

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_peak(self, session, measurements, sessions):
        """Run peak detection and mark if found."""
        recent = measurements.get_recent(session.id, limit=5)
        baseline = measurements.get_baseline_nivel(session.id)
        max_nivel = measurements.get_max_nivel(session.id)

        is_peak = peak_detector.detect_peak(
            recent=recent,
            baseline_nivel=baseline,
            max_nivel=max_nivel,
            peak_already_exists=measurements.peak_exists(session.id),
        )

        if is_peak:
            candidate = measurements.get_peak_candidate(session.id)
            if candidate:
                measurements.mark_peak(session.id, candidate["id"],
                                       candidate["nivel"], candidate["timestamp"])
                log.info("PEAK DETECTADO: %s%%", candidate["nivel"])
                send_peak_alert(self.config, session, candidate)

    def _send_email(self, session, measurements, drive_url):
        """Send periodic update email."""
        try:
            latest = measurements.get_latest(session.id)
            all_m = measurements.get_by_session(session.id)
            elapsed = 0.0
            if session.hora_inicio:
                start = datetime.fromisoformat(session.hora_inicio)
                elapsed = (datetime.now() - start).total_seconds() / 3600

            send_update_email(
                self.config, session, latest,
                measurement_count=len(all_m),
                elapsed_hours=elapsed,
                photo_url=drive_url,
            )
        except Exception as e:
            log.warning("Email error: %s", e)

    def _check_hibernation(self) -> bool:
        if self._firebase:
            try:
                if self._firebase.get_hibernate_state():
                    log.info("Masa en el refrigerador (Hibernando). Esperando...")
                    return True
            except Exception:
                pass
        return False

    def _sync_calibration(self, session, sessions):
        try:
            calib = self._firebase.pull_calibration(session.id)
            if calib:
                bounds = CalibrationBounds(**calib)
                sessions.update_calibration(session.id, bounds)
                log.info("Calibración sincronizada desde Firebase")
        except Exception as e:
            log.warning("Failed to pull calibration: %s", e)

    def _sync_corrections(self, session, measurements=None):
        try:
            corrections = self._firebase.pull_corrections(session.id)
            if corrections:
                # Save for Claude few-shot learning
                corrections_file = self.config.data_dir / "dataset_corrections.json"
                corrections_file.parent.mkdir(exist_ok=True)
                with open(corrections_file, "w") as f:
                    json.dump(corrections, f, indent=2)

                # Apply to local DB for ML training
                if measurements:
                    updated = measurements.apply_corrections(session.id, corrections)
                    if updated:
                        log.info("%d correcciones aplicadas a DB local (ML training)", updated)

                log.info("%d correcciones manuales cargadas", len(corrections))
        except Exception as e:
            log.warning("Failed to pull corrections: %s", e)

    def _init_integrations(self):
        """Initialize Firebase and Drive clients (optional)."""
        if not self.config.firebase_enabled:
            return
        try:
            from sourdough.integrations.firebase import FirebaseClient
            self._firebase = FirebaseClient(self.config)
            if self._firebase.init():
                log.info("Firebase initialized")
            else:
                self._firebase = None
        except ImportError:
            log.warning("Firebase SDK not available")
        except Exception as e:
            log.warning("Firebase init failed: %s", e)

        try:
            from sourdough.integrations.gdrive import DriveClient
            self._gdrive = DriveClient(self.config)
            if self._gdrive.init():
                log.info("Google Drive initialized")
            else:
                self._gdrive = None
        except ImportError:
            log.warning("Google Drive SDK not available")
        except Exception as e:
            log.warning("Google Drive init failed: %s", e)

        # ML model (optional)
        ml_model_path = self.config.ml_model_path
        if ml_model_path and ml_model_path.exists():
            try:
                from sourdough.services.ml_predictor import MLPredictor
                self._ml_predictor = MLPredictor(ml_model_path)
            except Exception as e:
                log.warning("ML predictor init failed: %s", e)

    def _sleep(self, seconds: float) -> None:
        """Sleep in small increments to allow graceful shutdown."""
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(2)

    def _signal_handler(self, signum, frame):
        log.info("Shutdown signal received, finishing current cycle...")
        self._running = False
