"""Firebase/Firestore integration — class-based, no module globals."""

import logging
import os
from datetime import datetime
from typing import Optional

from sourdough.config import AppConfig

log = logging.getLogger(__name__)


class FirebaseClient:
    """Encapsulates all Firestore operations."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._db = None

    def init(self) -> bool:
        """Initialize Firebase Admin SDK. Returns True on success."""
        sa_path = self._config.firebase_service_account
        if sa_path is None or not sa_path.exists():
            log.warning("Firebase service account key not found")
            return False

        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not firebase_admin._apps:
                cred = credentials.Certificate(str(sa_path))
                firebase_admin.initialize_app(cred)

            self._db = firestore.client()
            return True
        except Exception as e:
            log.warning("Firebase init error: %s", e)
            return False

    # -- Session sync -------------------------------------------------------

    def sync_session(self, session_data: dict) -> bool:
        if self._db is None:
            return False
        try:
            from firebase_admin import firestore

            session_id = str(session_data["id"])
            doc_ref = self._db.collection("sesiones").document(session_id)
            doc_data = {
                k: v for k, v in session_data.items() if k != "id"
            }
            doc_data["updated_at"] = firestore.SERVER_TIMESTAMP
            doc_ref.set(doc_data, merge=True)
            return True
        except Exception as e:
            log.warning("Firestore session sync error: %s", e)
            return False

    # -- Measurement sync ---------------------------------------------------

    def sync_measurement(
        self,
        session_id: int,
        measurement_data: dict,
        photo_drive_info: Optional[dict] = None,
    ) -> bool:
        if self._db is None:
            return False
        try:
            session_doc = str(session_id)
            ts = measurement_data.get("timestamp") or datetime.now().isoformat()
            measurement_id = ts.replace(":", "-").replace(".", "-")

            doc_ref = (
                self._db.collection("sesiones").document(session_doc)
                .collection("mediciones").document(measurement_id)
            )

            # Encode photo as base64 for dashboard rendering
            foto_base64 = None
            foto_path = measurement_data.get("foto_path")
            if foto_path and os.path.exists(foto_path):
                try:
                    import base64
                    with open(foto_path, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode("utf-8")
                        foto_base64 = f"data:image/jpeg;base64,{encoded}"
                except Exception as e:
                    log.warning("Error encoding image: %s", e)

            doc_data = {
                "timestamp": measurement_data.get("timestamp", ""),
                "nivel_pct": measurement_data.get("nivel_pct"),
                "burbujas": measurement_data.get("burbujas", ""),
                "textura": measurement_data.get("textura", ""),
                "notas": measurement_data.get("notas", ""),
                "es_peak": measurement_data.get("es_peak", 0),
                "altura_y_pct": measurement_data.get("altura_y_pct"),
                "confianza": measurement_data.get("confianza"),
                "modo_analisis": measurement_data.get("modo_analisis"),
                "altura_pct": measurement_data.get("altura_pct"),
                "ml_altura_pct": measurement_data.get("ml_altura_pct"),
                "crecimiento_pct": measurement_data.get("crecimiento_pct"),
                "fuente": measurement_data.get("fuente"),
                "volumen_ml": measurement_data.get("volumen_ml"),
                "crecimiento_ml": measurement_data.get("crecimiento_ml"),
                "crecimiento_ml_pct": measurement_data.get("crecimiento_ml_pct"),
                "foto_base64": foto_base64,
            }

            if foto_base64:
                doc_data["foto_url"] = foto_base64
            elif photo_drive_info and photo_drive_info.get("url"):
                doc_data["foto_url"] = photo_drive_info["url"]

            if photo_drive_info:
                if photo_drive_info.get("preview_url"):
                    doc_data["foto_preview"] = photo_drive_info["preview_url"]
                if photo_drive_info.get("file_id"):
                    doc_data["foto_drive_id"] = photo_drive_info["file_id"]

            doc_ref.set(doc_data, merge=True)
            return True
        except Exception as e:
            log.warning("Firestore measurement sync error: %s", e)
            return False

    # -- Pulls from Firestore -----------------------------------------------

    def pull_calibration(self, session_id: int) -> Optional[dict]:
        if self._db is None:
            return None
        try:
            doc = self._db.collection("sesiones").document(str(session_id)).get()
            if doc.exists:
                data = doc.to_dict()
                if data.get("is_calibrated") == 1:
                    return {
                        "fondo_y_pct": data.get("fondo_y_pct"),
                        "tope_y_pct": data.get("tope_y_pct"),
                        "base_y_pct": data.get("base_y_pct"),
                        "izq_x_pct": data.get("izq_x_pct"),
                        "der_x_pct": data.get("der_x_pct"),
                    }
        except Exception as e:
            log.warning("Firestore pull calibration error: %s", e)
        return None

    def pull_corrections(self, session_id: int) -> list[dict]:
        if self._db is None:
            return []
        try:
            meds_ref = (
                self._db.collection("sesiones").document(str(session_id))
                .collection("mediciones")
            )
            docs = meds_ref.where("is_manual_override", "==", True).get()
            corrections = [d.to_dict() for d in docs]
            return sorted(corrections, key=lambda x: x.get("timestamp", ""))
        except Exception as e:
            log.warning("Firestore pull corrections error: %s", e)
            return []

    def pull_cycle_markers(self, session_id: int) -> list[dict]:
        """Pull cycle markers (is_ciclo=true) from Firestore mediciones."""
        if self._db is None:
            return []
        try:
            meds_ref = (
                self._db.collection("sesiones").document(str(session_id))
                .collection("mediciones")
            )
            docs = meds_ref.where("is_ciclo", "==", True).get()
            markers = [d.to_dict() for d in docs]
            return sorted(markers, key=lambda x: x.get("timestamp", ""))
        except Exception as e:
            log.warning("Firestore pull cycle markers error: %s", e)
            return []

    def sync_bread_window(self, session_id: int, state: str, timestamp: str) -> bool:
        """Update bread window state on the session document.

        Args:
            session_id: The session ID.
            state: "opened" or "closed".
            timestamp: ISO timestamp of the state change.
        """
        if self._db is None:
            return False
        try:
            doc_ref = self._db.collection("sesiones").document(str(session_id))
            if state == "opened":
                doc_ref.update({
                    "ventana_pan_activa": True,
                    "ventana_pan_inicio": timestamp,
                    "ventana_pan_fin": None,
                })
            elif state == "closed":
                doc_ref.update({
                    "ventana_pan_activa": False,
                    "ventana_pan_fin": timestamp,
                })
            log.info("Bread window state synced: %s", state)
            return True
        except Exception as e:
            log.warning("Firestore bread window sync error: %s", e)
            return False

    # -- Push notifications --------------------------------------------------

    def send_push_notification(self, title: str, body: str) -> bool:
        """Send a push notification via FCM to the registered web client."""
        if self._db is None:
            return False
        try:
            from firebase_admin import messaging

            # Read FCM token from Firestore
            token_doc = self._db.collection("app_config").document("fcm_token").get()
            if not token_doc.exists:
                log.warning("No FCM token registered — skipping push")
                return False

            fcm_token = token_doc.to_dict().get("token")
            if not fcm_token:
                log.warning("FCM token document is empty — skipping push")
                return False

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                webpush=messaging.WebpushConfig(
                    notification=messaging.WebpushNotification(
                        icon="/icons/icon-192.png",
                        badge="/icons/icon-192.png",
                    ),
                ),
                token=fcm_token,
            )
            messaging.send(message)
            log.info("Push notification sent: %s", title)
            return True
        except Exception as e:
            log.warning("FCM push error: %s", e)
            return False

    def get_hibernate_state(self) -> bool:
        if self._db is None:
            return False
        try:
            doc = self._db.collection("app_config").document("state").get()
            if doc.exists:
                return doc.to_dict().get("is_hibernating", False)
        except Exception:
            pass
        return False

    def get_capture_request_timestamp(self) -> str | None:
        """Dashboard-driven "capture now" signal.

        The dashboard writes `capture_requested_at` (ISO timestamp) into
        `app_config/state` when the user starts a new cycle, so we take a
        fresh photo of the just-refreshed masa instead of waiting for the
        next scheduled capture. Returns the string as-is; the monitor
        compares it against the last value it consumed.
        """
        if self._db is None:
            return None
        try:
            doc = self._db.collection("app_config").document("state").get()
            if doc.exists:
                return doc.to_dict().get("capture_requested_at")
        except Exception:
            pass
        return None
