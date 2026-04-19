"""Listen to a Firestore doc and kick off ML retraining when the dashboard asks.

Flow:
  1. Dashboard button writes `app_config/retrain_state` with
     `{ state: 'requested', requested_at: <ISO> }`.
  2. This service's Firestore listener fires.
  3. If `requested_at` is newer than the last handled request, spawn
     `scripts/ml/retrain_from_corrections.py` as a subprocess in a background
     thread so the monitor's main capture loop isn't blocked.
  4. While the subprocess runs, update `app_config/retrain_state` with the
     current step so the dashboard can show progress.
  5. On success, invoke the caller's `on_finished` callback so the monitor
     can gracefully exit after its next capture — launchd KeepAlive then
     restarts it and the new weights get loaded.

Safety:
  * Requests older than the monitor's startup time are ignored, so a
    stale pending request doesn't re-trigger on a fresh boot.
  * Only one retrain runs at a time. Additional requests while one is
    active are ignored (dashboard disables the button too).
  * Subprocess failures are reported back to Firestore and the monitor
    is NOT killed.
"""

import logging
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


class RetrainTrigger:
    """Firestore-driven retrain orchestrator."""

    def __init__(
        self,
        firebase_client,
        repo_root: Path,
        on_finished: Optional[Callable[[bool, Optional[float]], None]] = None,
    ):
        self._fb = firebase_client
        self._repo_root = repo_root
        self._on_finished = on_finished
        self._unsubscribe = None
        self._lock = threading.Lock()
        self._running_retrain = False
        # Only act on requests newer than this — otherwise a stale request
        # doc would re-trigger on every monitor restart.
        self._cutoff_iso = datetime.now().isoformat()
        self._last_handled_iso: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._fb is None or self._fb._db is None:
            log.warning("RetrainTrigger: Firestore not available — listener not started")
            return
        doc_ref = self._fb._db.collection("app_config").document("retrain_state")
        try:
            self._unsubscribe = doc_ref.on_snapshot(self._on_snapshot)
            log.info("RetrainTrigger listening on app_config/retrain_state (cutoff %s)",
                     self._cutoff_iso)
        except Exception as e:
            log.warning("RetrainTrigger: failed to attach listener: %s", e)

    def stop(self) -> None:
        if self._unsubscribe:
            try:
                self._unsubscribe.unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None

    # -- callbacks ---------------------------------------------------------

    def _on_snapshot(self, doc_snapshot, changes, read_time):
        """Firestore realtime callback (runs in firebase-admin's thread)."""
        if not doc_snapshot:
            return
        doc = doc_snapshot[0]
        if not doc.exists:
            return
        data = doc.to_dict() or {}
        state = data.get("state")
        requested_at = data.get("requested_at") or ""

        if state != "requested":
            return
        if not requested_at or requested_at < self._cutoff_iso:
            return  # stale
        if self._last_handled_iso and requested_at <= self._last_handled_iso:
            return  # already handled

        with self._lock:
            if self._running_retrain:
                log.info("RetrainTrigger: request ignored — retrain already running")
                return
            self._running_retrain = True
            self._last_handled_iso = requested_at

        log.info("RetrainTrigger: request %s — starting retrain", requested_at)
        t = threading.Thread(target=self._run, args=(requested_at,), daemon=False)
        t.start()

    # -- subprocess orchestration ------------------------------------------

    def _run(self, requested_at: str) -> None:
        started_at = datetime.now().isoformat()
        self._set_state(
            state="running",
            started_at=started_at,
            requested_at=requested_at,
            step="starting",
            message="Iniciando retrain…",
            finished_at=None, error=None,
        )

        script = self._repo_root / "scripts/ml/retrain_from_corrections.py"
        cmd = [sys.executable, str(script)]
        mae: Optional[float] = None
        success = False

        try:
            # Capture stdout so we can extract the final MAE for the status doc.
            # Stream lines to the log AND parse them for progress markers.
            proc = subprocess.Popen(
                cmd, cwd=str(self._repo_root),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    log.info("retrain: %s", line)
                # Coarse step detection so the dashboard can show progress.
                if "sync_corrections.py" in line:
                    self._update_step("sync", "Sincronizando correcciones…")
                elif "prepare_dataset.py" in line:
                    self._update_step("prepare", "Regenerando crops…")
                elif "train.py" in line:
                    self._update_step("train", "Entrenando modelo…")
                elif "Test MAE:" in line:
                    try:
                        mae = float(line.split("Test MAE:")[1].strip().rstrip("%"))
                    except (ValueError, IndexError):
                        pass
            rc = proc.wait()
            success = (rc == 0)
        except Exception as e:
            log.exception("RetrainTrigger: subprocess failed")
            self._set_state(
                state="error",
                finished_at=datetime.now().isoformat(),
                message="Retrain falló",
                error=str(e),
            )
            with self._lock:
                self._running_retrain = False
            if self._on_finished:
                try: self._on_finished(False, None)
                except Exception: log.exception("on_finished callback raised")
            return

        finished_at = datetime.now().isoformat()
        if success:
            self._set_state(
                state="success",
                finished_at=finished_at,
                step="restart",
                message=f"Retrain OK (MAE {mae:.2f}%). Reiniciando monitor…"
                         if mae is not None else "Retrain OK. Reiniciando monitor…",
                mae=mae,
                error=None,
            )
        else:
            self._set_state(
                state="error",
                finished_at=finished_at,
                message="Retrain falló — revisa los logs del monitor.",
                error="non-zero exit",
            )

        with self._lock:
            self._running_retrain = False
        if self._on_finished:
            try: self._on_finished(success, mae)
            except Exception: log.exception("on_finished callback raised")

    # -- Firestore helpers -------------------------------------------------

    def _update_step(self, step: str, message: str) -> None:
        self._set_state(step=step, message=message)

    def _set_state(self, **fields) -> None:
        if self._fb is None or self._fb._db is None:
            return
        try:
            self._fb._db.collection("app_config").document("retrain_state").set(
                fields, merge=True,
            )
        except Exception as e:
            log.warning("RetrainTrigger: state write failed: %s", e)
