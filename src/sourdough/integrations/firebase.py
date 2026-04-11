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
                "nivel_px": measurement_data.get("nivel_px"),
                "burbujas": measurement_data.get("burbujas", ""),
                "textura": measurement_data.get("textura", ""),
                "notas": measurement_data.get("notas", ""),
                "es_peak": measurement_data.get("es_peak", 0),
                "altura_y_pct": measurement_data.get("altura_y_pct"),
                "confianza": measurement_data.get("confianza"),
                "modo_analisis": measurement_data.get("modo_analisis", "single"),
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
