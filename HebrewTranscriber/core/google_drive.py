"""
Google Drive integration for Hebrew Video Transcriber.
Provides OAuth2 authentication and file upload to Google Drive.
"""

from pathlib import Path
from typing import List, Optional, Callable
from datetime import datetime
import json
import os

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False

# OAuth2 scopes - only file creation, not full drive access
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# App folder structure
APP_FOLDER_NAME = "HebrewTranscriber"


def is_google_api_available() -> bool:
    """Check if Google API packages are installed."""
    return GOOGLE_API_AVAILABLE


def _get_credentials_dir() -> Path:
    """Get directory for storing OAuth credentials."""
    if os.name == 'nt':
        app_data = Path(os.environ.get('APPDATA', str(Path.home())))
        cred_dir = app_data / 'HebrewTranscriber' / 'google_credentials'
    else:
        cred_dir = Path.home() / '.HebrewTranscriber' / 'google_credentials'
    cred_dir.mkdir(parents=True, exist_ok=True)
    return cred_dir


def _get_token_path() -> Path:
    """Get path to stored OAuth token."""
    return _get_credentials_dir() / 'token.json'


def _get_client_secrets_path() -> Path:
    """Get path to client secrets file (user must provide this)."""
    return _get_credentials_dir() / 'client_secrets.json'


class GoogleDriveUploader:
    """Handles Google Drive authentication and file uploads."""

    def __init__(self):
        self.credentials: Optional[Credentials] = None
        self.service = None
        self._folder_cache = {}  # Cache folder IDs to avoid repeated lookups

    def is_api_available(self) -> bool:
        """Check if Google API packages are installed."""
        return GOOGLE_API_AVAILABLE

    def is_client_secrets_configured(self) -> bool:
        """Check if client_secrets.json exists."""
        return _get_client_secrets_path().exists()

    def get_client_secrets_path(self) -> str:
        """Return path where user should place client_secrets.json."""
        return str(_get_client_secrets_path())

    def is_authenticated(self) -> bool:
        """Check if we have valid credentials."""
        if not GOOGLE_API_AVAILABLE:
            return False

        if self.credentials and self.credentials.valid:
            return True

        token_path = _get_token_path()
        if token_path.exists():
            try:
                self.credentials = Credentials.from_authorized_user_file(
                    str(token_path), SCOPES
                )
                if self.credentials.valid:
                    return True
                if self.credentials.expired and self.credentials.refresh_token:
                    self.credentials.refresh(Request())
                    self._save_token()
                    return True
            except Exception:
                pass

        return False

    def authenticate(self, on_status: Callable[[str], None] = None) -> bool:
        """
        Authenticate with Google Drive using OAuth2.
        Opens browser for user consent if needed.
        """
        if not GOOGLE_API_AVAILABLE:
            if on_status:
                on_status("ERROR: Google API packages not installed. Run: pip install google-auth google-auth-oauthlib google-api-python-client")
            return False

        if not self.is_client_secrets_configured():
            if on_status:
                on_status(f"ERROR: client_secrets.json not found at {_get_client_secrets_path()}")
            return False

        try:
            # Try to load existing token
            token_path = _get_token_path()
            if token_path.exists():
                self.credentials = Credentials.from_authorized_user_file(
                    str(token_path), SCOPES
                )

            # Refresh if expired
            if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                if on_status:
                    on_status("Refreshing authentication token...")
                self.credentials.refresh(Request())
                self._save_token()

            # If no valid credentials, start OAuth flow
            if not self.credentials or not self.credentials.valid:
                if on_status:
                    on_status("Opening browser for Google authentication...")

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(_get_client_secrets_path()), SCOPES
                )
                self.credentials = flow.run_local_server(port=0)
                self._save_token()

            # Build the Drive service
            self.service = build('drive', 'v3', credentials=self.credentials)

            if on_status:
                on_status("Google Drive authentication successful!")

            return True

        except Exception as e:
            if on_status:
                on_status(f"Authentication failed: {str(e)}")
            return False

    def _save_token(self):
        """Save credentials to token file for reuse."""
        token_path = _get_token_path()
        with open(token_path, 'w') as f:
            f.write(self.credentials.to_json())

    def logout(self):
        """Clear stored credentials."""
        token_path = _get_token_path()
        if token_path.exists():
            token_path.unlink()
        self.credentials = None
        self.service = None
        self._folder_cache = {}

    def _get_or_create_folder(
        self,
        folder_name: str,
        parent_id: Optional[str] = None
    ) -> str:
        """Get folder ID, creating it if it doesn't exist."""
        cache_key = f"{parent_id or 'root'}:{folder_name}"
        if cache_key in self._folder_cache:
            return self._folder_cache[cache_key]

        # Search for existing folder
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"
        else:
            query += " and 'root' in parents"

        results = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])
        if files:
            folder_id = files[0]['id']
        else:
            # Create folder
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]

            folder = self.service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()
            folder_id = folder.get('id')

        self._folder_cache[cache_key] = folder_id
        return folder_id

    def _ensure_folder_structure(self, notebook_name: str) -> str:
        """
        Create folder structure: HebrewTranscriber/YYYY-MM/NotebookName/
        Returns the final folder ID.
        """
        # HebrewTranscriber/
        app_folder_id = self._get_or_create_folder(APP_FOLDER_NAME)

        # YYYY-MM/
        date_folder = datetime.now().strftime("%Y-%m")
        date_folder_id = self._get_or_create_folder(date_folder, app_folder_id)

        # NotebookName/
        # Sanitize notebook name for Drive
        safe_name = "".join(c for c in notebook_name if c.isalnum() or c in " _-").strip()[:100]
        if not safe_name:
            safe_name = "Unnamed"
        notebook_folder_id = self._get_or_create_folder(safe_name, date_folder_id)

        return notebook_folder_id

    def upload_file(
        self,
        local_path: Path,
        notebook_name: str,
        on_progress: Callable[[int], None] = None
    ) -> Optional[str]:
        """
        Upload a single file to Google Drive.

        Returns:
            File ID if successful, None otherwise.
        """
        if not self.service:
            return None

        try:
            folder_id = self._ensure_folder_structure(notebook_name)

            file_metadata = {
                'name': local_path.name,
                'parents': [folder_id]
            }

            # Determine mime type
            suffix = local_path.suffix.lower()
            mime_types = {
                '.mp4': 'video/mp4',
                '.mkv': 'video/x-matroska',
                '.webm': 'video/webm',
                '.srt': 'text/plain',
                '.md': 'text/markdown',
                '.pdf': 'application/pdf',
                '.mp3': 'audio/mpeg',
                '.wav': 'audio/wav',
            }
            mime_type = mime_types.get(suffix, 'application/octet-stream')

            media = MediaFileUpload(
                str(local_path),
                mimetype=mime_type,
                resumable=True
            )

            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status and on_progress:
                    on_progress(int(status.progress() * 100))

            return response.get('id')

        except HttpError as e:
            raise Exception(f"Upload failed: {e}")

    def upload_files(
        self,
        files: List[tuple],  # List of (local_path, notebook_name)
        on_progress: Callable[[int, int, str, int], None] = None
        # (current_file, total_files, filename, percent)
    ) -> dict:
        """
        Upload multiple files to Google Drive.

        Returns:
            {"uploaded": [paths], "failed": [(path, error)]}
        """
        results = {"uploaded": [], "failed": []}
        total = len(files)

        for i, (local_path, notebook_name) in enumerate(files):
            local_path = Path(local_path)

            if on_progress:
                on_progress(i + 1, total, local_path.name, 0)

            try:
                file_id = self.upload_file(
                    local_path,
                    notebook_name,
                    on_progress=lambda p: on_progress(i + 1, total, local_path.name, p) if on_progress else None
                )
                if file_id:
                    results["uploaded"].append(str(local_path))
                else:
                    results["failed"].append((str(local_path), "Unknown error"))
            except Exception as e:
                results["failed"].append((str(local_path), str(e)))

        return results
