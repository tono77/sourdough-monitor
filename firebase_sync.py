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
            "updated_at": firestore.SERVER_TIMESTAMP,
        }

        doc_ref.set(doc_data, merge=True)
        return True

    except Exception as e:
        print(f"⚠️  Firestore session sync error: {e}")
        return False


def sync_measurement(session_id, measurement_data, photo_drive_info=None):
    """Sync a measurement to Firestore (as subcollection of session)."""
    global _firestore_db

    if _firestore_db is None:
        if init_firebase() is None:
            return False

    try:
        session_doc = str(session_id)
        measurement_id = str(measurement_data.get("id", measurement_data.get("timestamp", "")))

        doc_ref = (_firestore_db
                   .collection("sesiones").document(session_doc)
                   .collection("mediciones").document(measurement_id))

        doc_data = {
            "timestamp": measurement_data.get("timestamp", ""),
            "nivel_pct": measurement_data.get("nivel_pct"),
            "nivel_px": measurement_data.get("nivel_px"),
            "burbujas": measurement_data.get("burbujas", ""),
            "textura": measurement_data.get("textura", ""),
            "notas": measurement_data.get("notas", ""),
            "es_peak": measurement_data.get("es_peak", 0),
        }

        # Add photo URL from Drive if available
        if photo_drive_info:
            doc_data["foto_url"] = photo_drive_info.get("url", "")
            doc_data["foto_drive_id"] = photo_drive_info.get("file_id", "")

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
