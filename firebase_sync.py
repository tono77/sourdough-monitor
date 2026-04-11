#!/usr/bin/env python3
"""
Sourdough Monitor — Firebase + Google Drive Sync
Syncs measurement data to Firestore and photos to Google Drive.
"""

import json
import os
from pathlib import Path
from datetime import datetime

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# Google Drive
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# Firebase service account key path
SERVICE_ACCOUNT_PATH = DATA_DIR / "firebase-service-account.json"

# Google Drive OAuth paths
GDRIVE_CREDENTIALS_PATH = DATA_DIR / "gdrive_credentials.json"
GDRIVE_TOKEN_PATH = DATA_DIR / "gdrive_token.json"

# Google Drive scopes
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Module-level state
_firestore_db = None
_drive_service = None
_drive_folder_id = None


def init_firebase():
    """Initialize Firebase Admin SDK."""
    global _firestore_db

    if _firestore_db is not None:
        return _firestore_db

    if not SERVICE_ACCOUNT_PATH.exists():
        print(f"⚠️  Firebase service account key not found at {SERVICE_ACCOUNT_PATH}")
        print("   Download it from: https://console.firebase.google.com/project/sourdough-monitor-app/settings/serviceaccounts/adminsdk")
        return None

    try:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred)
        _firestore_db = firestore.client()
        print("🔥 Firebase initialized")
        return _firestore_db
    except Exception as e:
        print(f"⚠️  Firebase init error: {e}")
        return None


def init_gdrive():
    """Initialize Google Drive API client."""
    global _drive_service, _drive_folder_id

    if _drive_service is not None:
        return _drive_service

    if not GDRIVE_CREDENTIALS_PATH.exists():
        print(f"⚠️  Google Drive OAuth credentials not found at {GDRIVE_CREDENTIALS_PATH}")
        print("   Create OAuth credentials at: https://console.cloud.google.com/apis/credentials")
        return None

    creds = None

    # Load existing token
    if GDRIVE_TOKEN_PATH.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(GDRIVE_TOKEN_PATH), GDRIVE_SCOPES)
        except Exception:
            pass

    # Refresh or get new token
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GDRIVE_CREDENTIALS_PATH), GDRIVE_SCOPES
            )
            creds = flow.run_local_server(port=8090)

        # Save token for next time
        with open(GDRIVE_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    try:
        _drive_service = build("drive", "v3", credentials=creds)
        _drive_folder_id = _get_or_create_folder("SourdoughMonitor")
        print(f"📁 Google Drive ready (folder: {_drive_folder_id})")
        return _drive_service
    except Exception as e:
        print(f"⚠️  Google Drive init error: {e}")
        return None


def _get_or_create_folder(folder_name):
    """Get or create a Google Drive folder, returns folder ID."""
    global _drive_service

    # Search for existing folder
    results = _drive_service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    files = results.get("files", [])
    if files:
        return files[0]["id"]

    # Create folder
    file_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = _drive_service.files().create(
        body=file_metadata, fields="id"
    ).execute()

    folder_id = folder["id"]

    # Make folder viewable by anyone with link
    _drive_service.permissions().create(
        fileId=folder_id,
        body={"type": "anyone", "role": "reader"}
    ).execute()

    print(f"📁 Created Drive folder: {folder_name}")
    return folder_id


def upload_photo_to_drive(photo_path):
    """Upload a photo to Google Drive, returns the web view URL."""
    global _drive_service, _drive_folder_id

    if _drive_service is None:
        if init_gdrive() is None:
            return None

    photo_path = Path(photo_path)
    if not photo_path.exists():
        return None

    try:
        file_metadata = {
            "name": photo_path.name,
            "parents": [_drive_folder_id]
        }

        # Determine mime type
        ext = photo_path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(ext, "image/jpeg")

        media = MediaFileUpload(str(photo_path), mimetype=mime_type, resumable=True)

        file = _drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webContentLink, webViewLink"
        ).execute()

        file_id = file["id"]

        # Make file viewable by anyone with link
        _drive_service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"}
        ).execute()

        # Return direct thumbnail URL (works without auth)
        # Google Drive direct image URL format
        direct_url = f"https://drive.google.com/thumbnail?id={file_id}&sz=w800"

        return {
            "file_id": file_id,
            "url": direct_url,
            "view_url": file.get("webViewLink", ""),
        }

    except Exception as e:
        print(f"⚠️  Drive upload error: {e}")
        return None


def delete_drive_file(file_id):
    """Delete a file from Google Drive silently."""
    global _drive_service
    if _drive_service is None or not file_id:
        return
    try:
        _drive_service.files().delete(fileId=file_id).execute()
    except Exception:
        pass

def upload_video_to_drive(video_path, old_file_id=None):
    """Uploads the MP4 to Google Drive, returning the viewable link. Deletes old one if exists."""
    global _drive_service, _drive_folder_id
    if _drive_service is None:
        if init_gdrive() is None:
            return None

    video_path = Path(video_path)
    if not video_path.exists():
        return None

    if old_file_id:
        delete_drive_file(old_file_id)

    try:
        file_metadata = {
            "name": video_path.name,
            "parents": [_drive_folder_id]
        }
        media = MediaFileUpload(str(video_path), mimetype='video/mp4', resumable=True)

        file = _drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webContentLink, webViewLink"
        ).execute()

        file_id = file["id"]

        # Make file viewable by anyone with link
        _drive_service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"}
        ).execute()

        return {
            "file_id": file_id,
            "url": file.get("webContentLink"), # Direct download link
            "preview_url": file.get("webViewLink") # Google player link
        }
    except Exception as e:
        print(f"⚠️ Drive API Video Error: {e}")
        return None

def pull_hibernate_state():
    """Retrieve hibernation state to determine if monitoring is paused (refrigerator mode)."""
    global _firestore_db
    if _firestore_db is None:
        if init_firebase() is None:
            return False
    try:
        doc_ref = _firestore_db.collection("app_config").document("state")
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict().get("is_hibernating", False)
    except Exception as e:
        pass
    return False

def sync_session(session_data):
    """Sync session data to Firestore."""
    global _firestore_db

    if _firestore_db is None:
        if init_firebase() is None:
            return False

    try:
        session_id = str(session_data["id"])
        doc_ref = _firestore_db.collection("sesiones").document(session_id)

        doc_data = {
            "fecha": session_data.get("fecha", ""),
            "hora_inicio": session_data.get("hora_inicio", ""),
            "hora_fin": session_data.get("hora_fin"),
            "estado": session_data.get("estado", "activa"),
            "num_mediciones": session_data.get("num_mediciones", 0),
            "peak_nivel": session_data.get("peak_nivel"),
            "peak_timestamp": session_data.get("peak_timestamp"),
            "notas": session_data.get("notas"),
            "fondo_y_pct": session_data.get("fondo_y_pct"),
            "tope_y_pct": session_data.get("tope_y_pct"),
            "base_y_pct": session_data.get("base_y_pct"),
            "izq_x_pct": session_data.get("izq_x_pct"),
            "der_x_pct": session_data.get("der_x_pct"),
            "is_calibrated": session_data.get("is_calibrated", 0),
            "timelapse_url": session_data.get("timelapse_url"),
            "timelapse_file_id": session_data.get("timelapse_file_id"),
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        doc_ref.set(doc_data, merge=True)
        return True

    except Exception as e:
        print(f"⚠️  Firestore session sync error: {e}")
        return False


def pull_calibration(session_id):
    """Retrieve calibration info from Firestore for a given session."""
    global _firestore_db
    if _firestore_db is None:
        if init_firebase() is None:
            return None
    try:
        doc_ref = _firestore_db.collection("sesiones").document(str(session_id))
        doc = doc_ref.get()
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
        print(f"⚠️  Firestore pull calibration error: {e}")
    return None


def pull_corrections(session_id):
    """Fetch any user-corrected measurements from Firestore."""
    global _firestore_db
    if _firestore_db is None:
        if init_firebase() is None:
            return []
    try:
        meds_ref = _firestore_db.collection("sesiones").document(str(session_id)).collection("mediciones")
        query = meds_ref.where("is_manual_override", "==", True)
        docs = query.get()
        corrections = []
        for d in docs:
            data = d.to_dict()
            corrections.append(data)
        
        # Sort by timestamp ascending
        return sorted(corrections, key=lambda x: x.get("timestamp", ""))
    except Exception as e:
        print(f"⚠️  Firestore pull corrections error: {e}")
        return []

def sync_measurement(session_id, measurement_data, photo_drive_info=None):
    """Sync a measurement to Firestore (as subcollection of session)."""
    global _firestore_db

    if _firestore_db is None:
        if init_firebase() is None:
            return False

    try:
        session_doc = str(session_id)
        # Use timestamp as doc ID (always unique, human-readable)
        # Fallback to id only if timestamp is missing
        ts = measurement_data.get("timestamp") or str(measurement_data.get("id") or "")
        measurement_id = ts.replace(":", "-").replace(".", "-")  # Firestore-safe ID
        if not measurement_id:
            measurement_id = datetime.now().isoformat().replace(":", "-").replace(".", "-")

        doc_ref = (_firestore_db
                   .collection("sesiones").document(session_doc)
                   .collection("mediciones").document(measurement_id))

        # Encode the photo as a Base64 string for direct UI rendering
        foto_base64 = None
        try:
            foto_real_path = measurement_data.get("foto_path")
            if foto_real_path and os.path.exists(foto_real_path):
                import base64
                with open(foto_real_path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                    foto_base64 = f"data:image/jpeg;base64,{encoded_string}"
        except Exception as e:
            print(f"⚠️  Error encoding image to base64: {e}")

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
            "foto_base64": foto_base64
        }

        # Add photo URL from Drive if available
        if foto_base64:
            doc_data["foto_url"] = foto_base64
        elif photo_drive_info and photo_drive_info.get("url"):
            doc_data["foto_url"] = photo_drive_info.get("url")
        
        if photo_drive_info and photo_drive_info.get("preview_url"):
            doc_data["foto_preview"] = photo_drive_info.get("preview_url")
        
        if photo_drive_info and photo_drive_info.get("file_id"):
            doc_data["foto_drive_id"] = photo_drive_info.get("file_id")

        doc_ref.set(doc_data, merge=True)
        return True

    except Exception as e:
        print(f"⚠️  Firestore measurement sync error: {e}")
        return False


def sync_full_cycle(session, measurement, photo_path=None):
    """
    Convenience function: sync everything after a capture cycle.
    Called from monitor.py after each cycle.
    """
    # 1. Upload photo to Drive
    photo_drive_info = None
    if photo_path:
        photo_drive_info = upload_photo_to_drive(photo_path)
        if photo_drive_info:
            print(f"📤 Photo uploaded to Drive: {Path(photo_path).name}")

    # 2. Sync session to Firestore
    sync_session(session)

    # 3. Sync measurement to Firestore
    if measurement:
        sync_measurement(session["id"], measurement, photo_drive_info)

    return photo_drive_info


def init_all():
    """Initialize both Firebase and Google Drive. Call once at startup."""
    fb = init_firebase()
    gd = init_gdrive()
    return fb is not None and gd is not None
