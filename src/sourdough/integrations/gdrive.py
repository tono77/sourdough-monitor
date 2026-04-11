"""Google Drive integration — class-based, no module globals."""

import logging
from pathlib import Path
from typing import Optional

from sourdough.config import AppConfig

log = logging.getLogger(__name__)


class DriveClient:
    """Encapsulates Google Drive upload operations."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._service = None
        self._folder_id: Optional[str] = None

    def init(self) -> bool:
        """Initialize Google Drive API client. Returns True on success."""
        creds_path = self._config.gdrive_credentials
        if creds_path is None or not creds_path.exists():
            log.warning("Google Drive OAuth credentials not found")
            return False

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/drive.file"]
            token_path = self._config.gdrive_token
            creds = None

            if token_path and token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
                except Exception:
                    pass

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        creds = None
                if not creds:
                    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                    creds = flow.run_local_server(port=8090)

                if token_path:
                    with open(token_path, "w") as f:
                        f.write(creds.to_json())

            self._service = build("drive", "v3", credentials=creds)
            self._folder_id = self._get_or_create_folder("SourdoughMonitor")
            log.info("Google Drive ready (folder: %s)", self._folder_id)
            return True
        except Exception as e:
            log.warning("Google Drive init error: %s", e)
            return False

    # -- Upload operations ---------------------------------------------------

    def upload_photo(self, photo_path: str) -> Optional[dict]:
        """Upload a photo. Returns dict with file_id, url, view_url."""
        if self._service is None:
            return None

        photo = Path(photo_path)
        if not photo.exists():
            return None

        try:
            from googleapiclient.http import MediaFileUpload

            mime_types = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp",
            }
            mime = mime_types.get(photo.suffix.lower(), "image/jpeg")

            file_metadata = {"name": photo.name, "parents": [self._folder_id]}
            media = MediaFileUpload(str(photo), mimetype=mime, resumable=True)

            file = self._service.files().create(
                body=file_metadata, media_body=media,
                fields="id, webContentLink, webViewLink",
            ).execute()

            file_id = file["id"]
            self._make_public(file_id)

            return {
                "file_id": file_id,
                "url": f"https://drive.google.com/thumbnail?id={file_id}&sz=w800",
                "view_url": file.get("webViewLink", ""),
            }
        except Exception as e:
            log.warning("Drive upload error: %s", e)
            return None

    def upload_video(self, video_path: str, old_file_id: str | None = None) -> Optional[dict]:
        """Upload MP4 video. Deletes old version if exists."""
        if self._service is None:
            return None

        video = Path(video_path)
        if not video.exists():
            return None

        if old_file_id:
            self.delete_file(old_file_id)

        try:
            from googleapiclient.http import MediaFileUpload

            file_metadata = {"name": video.name, "parents": [self._folder_id]}
            media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)

            file = self._service.files().create(
                body=file_metadata, media_body=media,
                fields="id, webContentLink, webViewLink",
            ).execute()

            file_id = file["id"]
            self._make_public(file_id)

            return {
                "file_id": file_id,
                "url": file.get("webContentLink"),
                "preview_url": file.get("webViewLink"),
            }
        except Exception as e:
            log.warning("Drive video upload error: %s", e)
            return None

    def delete_file(self, file_id: str) -> None:
        if self._service is None or not file_id:
            return
        try:
            self._service.files().delete(fileId=file_id).execute()
        except Exception:
            pass

    # -- Helpers -------------------------------------------------------------

    def _get_or_create_folder(self, folder_name: str) -> str:
        results = self._service.files().list(
            q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            spaces="drive", fields="files(id, name)",
        ).execute()

        files = results.get("files", [])
        if files:
            return files[0]["id"]

        file_metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
        folder = self._service.files().create(body=file_metadata, fields="id").execute()
        folder_id = folder["id"]
        self._make_public(folder_id)
        log.info("Created Drive folder: %s", folder_name)
        return folder_id

    def _make_public(self, file_id: str) -> None:
        try:
            self._service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()
        except Exception:
            pass
