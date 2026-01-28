# Add NotebookLM Batch Downloader Feature

## Overview
Add a new feature to the Hebrew Transcriber app that batch downloads all audio/video podcasts from multiple NotebookLM notebooks. The user wants to download all their AI-generated podcast videos from NotebookLM for transcription.

## Research Findings
- NotebookLM videos/audio are served from `lh3.googleusercontent.com/notebooklm/` URLs
- These URLs require Google authentication cookies to download
- The `notebooklm-kit` npm package (https://github.com/photon-hq/notebooklm-kit) provides a TypeScript SDK for NotebookLM
- Playwright is needed for Google authentication (no official API exists)
- Audio downloads as WAV, videos download as MP4

## Implementation Requirements

### 1. New Tab: "NotebookLM Downloader"
Add a new tab to the PyQt6 app with these features:

**Authentication Section:**
- Google Email input field
- Google Password input field  
- "Login & Scan Notebooks" button
- Status label showing authentication state
- Save credentials checkbox (store in QSettings, encrypted)

**Notebook List Section:**
- QListWidget showing all notebooks with checkboxes
- Each item shows: notebook emoji, title, artifact count
- "Select All" / "Deselect All" buttons
- "Refresh List" button

**Download Section:**
- Output folder selector (default: same as transcription output)
- Download format options: Audio Only, Video Only, Both
- Progress bar showing overall progress
- QTextEdit log showing download status per file
- "Download Selected" button
- "Cancel" button

### 2. Backend Implementation

Create `core/notebooklm_downloader.py`:
```python
"""
NotebookLM Batch Downloader using Playwright for authentication
and direct HTTP requests for downloading.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable
import json
import re
import time
import requests
from playwright.sync_api import sync_playwright, Browser, Page

@dataclass
class NotebookInfo:
    project_id: str
    title: str
    emoji: str
    audio_artifacts: List[dict]  # [{id, title, url}]
    video_artifacts: List[dict]  # [{id, title, url}]

@dataclass  
class DownloadProgress:
    current: int
    total: int
    current_file: str
    status: str  # "downloading", "completed", "failed"

class NotebookLMDownloader:
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.cookies = None
        self.auth_token = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        
    def authenticate(self, on_status: Callable[[str], None] = None) -> bool:
        """
        Authenticate with Google using Playwright.
        Returns True if successful.
        """
        with sync_playwright() as p:
            # Launch browser (headless=False for first login to handle 2FA if needed)
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            
            try:
                if on_status:
                    on_status("Navigating to NotebookLM...")
                    
                # Go to NotebookLM (will redirect to Google login)
                page.goto("https://notebooklm.google.com/")
                page.wait_for_load_state("networkidle")
                
                # Check if already logged in
                if "notebooklm.google.com" in page.url and "accounts.google.com" not in page.url:
                    if on_status:
                        on_status("Already logged in!")
                else:
                    if on_status:
                        on_status("Logging in with Google...")
                    
                    # Enter email
                    page.fill('input[type="email"]', self.email)
                    page.click('#identifierNext')
                    page.wait_for_timeout(2000)
                    
                    # Enter password
                    page.fill('input[type="password"]', self.password)
                    page.click('#passwordNext')
                    page.wait_for_timeout(3000)
                    
                    # Wait for NotebookLM to load
                    page.wait_for_url("**/notebooklm.google.com/**", timeout=60000)
                
                if on_status:
                    on_status("Extracting authentication tokens...")
                
                # Extract cookies
                cookies = context.cookies()
                self.cookies = {c['name']: c['value'] for c in cookies}
                
                # Extract auth token from page
                self.auth_token = page.evaluate("() => window.WIZ_global_data?.SNlM0e || ''")
                
                if on_status:
                    on_status("Authentication successful!")
                    
                return True
                
            except Exception as e:
                if on_status:
                    on_status(f"Authentication failed: {str(e)}")
                return False
            finally:
                browser.close()
    
    def list_notebooks(self, on_status: Callable[[str], None] = None) -> List[NotebookInfo]:
        """
        List all notebooks and their audio/video artifacts.
        """
        notebooks = []
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            # Add cookies
            cookie_list = [{'name': k, 'value': v, 'domain': '.google.com', 'path': '/'} 
                          for k, v in self.cookies.items()]
            context.add_cookies(cookie_list)
            
            page = context.new_page()
            
            try:
                if on_status:
                    on_status("Loading NotebookLM...")
                    
                page.goto("https://notebooklm.google.com/")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(3000)
                
                if on_status:
                    on_status("Scanning notebooks...")
                
                # Extract notebook data from page
                # NotebookLM uses specific data attributes we can scrape
                notebook_elements = page.query_selector_all('[data-notebook-id]')
                
                # Alternative: intercept network requests
                # The page makes RPC calls that return notebook data
                # We can also extract from window.__INITIAL_STATE__ or similar
                
                # For now, let's use a more reliable method:
                # Navigate through the page and extract data
                
                # Get all notebook cards/items
                items = page.locator('a[href*="/notebook/"]').all()
                
                for item in items:
                    href = item.get_attribute('href')
                    if href:
                        project_id = href.split('/notebook/')[-1].split('?')[0]
                        title = item.inner_text() or "Untitled"
                        
                        notebooks.append(NotebookInfo(
                            project_id=project_id,
                            title=title,
                            emoji="📓",
                            audio_artifacts=[],
                            video_artifacts=[]
                        ))
                
                if on_status:
                    on_status(f"Found {len(notebooks)} notebooks. Scanning artifacts...")
                
                # For each notebook, get its artifacts
                for i, nb in enumerate(notebooks):
                    if on_status:
                        on_status(f"Scanning notebook {i+1}/{len(notebooks)}: {nb.title}")
                    
                    page.goto(f"https://notebooklm.google.com/notebook/{nb.project_id}")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)
                    
                    # Look for audio/video elements
                    # Audio overviews have specific patterns
                    audio_links = page.locator('a[href*="lh3.googleusercontent.com"][href*="=m22"]').all()
                    video_links = page.locator('a[href*="lh3.googleusercontent.com"][href*="-dv"]').all()
                    
                    # Also check for download buttons and their associated URLs
                    # NotebookLM stores media URLs in data attributes or script tags
                    
                    # Extract from page content
                    content = page.content()
                    
                    # Find audio URLs (pattern: =m22 without -dv)
                    audio_pattern = r'https://lh3\.googleusercontent\.com/notebooklm/[^"\s]+?=m22(?!-dv)[^"\s]*\?authuser=\d+'
                    audio_urls = list(set(re.findall(audio_pattern, content)))
                    
                    # Find video URLs (pattern: =m22-dv)
                    video_pattern = r'https://lh3\.googleusercontent\.com/notebooklm/[^"\s]+?=m22-dv[^"\s]*\?authuser=\d+'
                    video_urls = list(set(re.findall(video_pattern, content)))
                    
                    for j, url in enumerate(audio_urls):
                        nb.audio_artifacts.append({
                            'id': f'audio_{j}',
                            'title': f'{nb.title} - Audio {j+1}',
                            'url': url
                        })
                    
                    for j, url in enumerate(video_urls):
                        nb.video_artifacts.append({
                            'id': f'video_{j}',
                            'title': f'{nb.title} - Video {j+1}',
                            'url': url
                        })
                
                return notebooks
                
            finally:
                browser.close()
    
    def download_artifacts(
        self,
        notebooks: List[NotebookInfo],
        output_dir: Path,
        download_audio: bool = True,
        download_video: bool = True,
        on_progress: Callable[[DownloadProgress], None] = None
    ) -> List[Path]:
        """
        Download all artifacts from selected notebooks.
        Returns list of downloaded file paths.
        """
        downloaded = []
        
        # Build list of all files to download
        files_to_download = []
        for nb in notebooks:
            if download_audio:
                for artifact in nb.audio_artifacts:
                    files_to_download.append({
                        'url': artifact['url'],
                        'filename': self._sanitize_filename(artifact['title']) + '.wav',
                        'type': 'audio'
                    })
            if download_video:
                for artifact in nb.video_artifacts:
                    files_to_download.append({
                        'url': artifact['url'],
                        'filename': self._sanitize_filename(artifact['title']) + '.mp4',
                        'type': 'video'
                    })
        
        total = len(files_to_download)
        
        # Create session with cookies
        session = requests.Session()
        for name, value in self.cookies.items():
            session.cookies.set(name, value)
        
        for i, file_info in enumerate(files_to_download):
            if on_progress:
                on_progress(DownloadProgress(
                    current=i + 1,
                    total=total,
                    current_file=file_info['filename'],
                    status="downloading"
                ))
            
            try:
                output_path = output_dir / file_info['filename']
                
                # Download with streaming
                response = session.get(file_info['url'], stream=True)
                response.raise_for_status()
                
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                downloaded.append(output_path)
                
                if on_progress:
                    on_progress(DownloadProgress(
                        current=i + 1,
                        total=total,
                        current_file=file_info['filename'],
                        status="completed"
                    ))
                    
            except Exception as e:
                if on_progress:
                    on_progress(DownloadProgress(
                        current=i + 1,
                        total=total,
                        current_file=f"{file_info['filename']} - ERROR: {str(e)}",
                        status="failed"
                    ))
        
        return downloaded
    
    def _sanitize_filename(self, name: str) -> str:
        """Remove invalid characters from filename."""
        return re.sub(r'[<>:"/\\|?*]', '_', name)[:200]
```

### 3. UI Implementation

Create `ui/notebooklm_tab.py`:
```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QListWidget, QListWidgetItem, QProgressBar,
    QTextEdit, QGroupBox, QCheckBox, QFileDialog, QMessageBox,
    QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path

class AuthWorker(QThread):
    status_update = pyqtSignal(str)
    auth_complete = pyqtSignal(bool, object)  # success, downloader
    
    def __init__(self, email, password):
        super().__init__()
        self.email = email
        self.password = password
    
    def run(self):
        from core.notebooklm_downloader import NotebookLMDownloader
        downloader = NotebookLMDownloader(self.email, self.password)
        success = downloader.authenticate(self.status_update.emit)
        self.auth_complete.emit(success, downloader if success else None)

class ScanWorker(QThread):
    status_update = pyqtSignal(str)
    scan_complete = pyqtSignal(list)  # List[NotebookInfo]
    
    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader
    
    def run(self):
        notebooks = self.downloader.list_notebooks(self.status_update.emit)
        self.scan_complete.emit(notebooks)

class DownloadWorker(QThread):
    progress_update = pyqtSignal(object)  # DownloadProgress
    download_complete = pyqtSignal(list)  # List[Path]
    
    def __init__(self, downloader, notebooks, output_dir, audio, video):
        super().__init__()
        self.downloader = downloader
        self.notebooks = notebooks
        self.output_dir = output_dir
        self.download_audio = audio
        self.download_video = video
    
    def run(self):
        files = self.downloader.download_artifacts(
            self.notebooks,
            self.output_dir,
            self.download_audio,
            self.download_video,
            self.progress_update.emit
        )
        self.download_complete.emit(files)

class NotebookLMTab(QWidget):
    def __init__(self):
        super().__init__()
        self.downloader = None
        self.notebooks = []
        self.settings = QSettings('HebrewTranscriber', 'NotebookLM')
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # === Authentication Group ===
        auth_group = QGroupBox("התחברות ל-Google / Google Authentication")
        auth_layout = QVBoxLayout(auth_group)
        
        # Email
        email_layout = QHBoxLayout()
        email_layout.addWidget(QLabel("Email:"))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("your.email@gmail.com")
        email_layout.addWidget(self.email_input)
        auth_layout.addLayout(email_layout)
        
        # Password
        pass_layout = QHBoxLayout()
        pass_layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        pass_layout.addWidget(self.password_input)
        auth_layout.addLayout(pass_layout)
        
        # Save credentials checkbox
        self.save_creds_cb = QCheckBox("שמור פרטי התחברות / Save credentials")
        auth_layout.addWidget(self.save_creds_cb)
        
        # Login button and status
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("התחבר וסרוק מחברות / Login & Scan")
        self.login_btn.clicked.connect(self.on_login)
        btn_layout.addWidget(self.login_btn)
        self.auth_status = QLabel("")
        btn_layout.addWidget(self.auth_status)
        auth_layout.addLayout(btn_layout)
        
        layout.addWidget(auth_group)
        
        # === Notebooks Group ===
        notebooks_group = QGroupBox("מחברות / Notebooks")
        notebooks_layout = QVBoxLayout(notebooks_group)
        
        # Buttons
        nb_btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("בחר הכל / Select All")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("בטל בחירה / Deselect All")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.refresh_btn = QPushButton("רענן / Refresh")
        self.refresh_btn.clicked.connect(self.on_refresh)
        nb_btn_layout.addWidget(self.select_all_btn)
        nb_btn_layout.addWidget(self.deselect_all_btn)
        nb_btn_layout.addWidget(self.refresh_btn)
        notebooks_layout.addLayout(nb_btn_layout)
        
        # Notebook list
        self.notebook_list = QListWidget()
        notebooks_layout.addWidget(self.notebook_list)
        
        layout.addWidget(notebooks_group)
        
        # === Download Group ===
        download_group = QGroupBox("הורדה / Download")
        download_layout = QVBoxLayout(download_group)
        
        # Output folder
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("תיקיית יעד / Output:"))
        self.output_path = QLineEdit()
        folder_layout.addWidget(self.output_path)
        self.browse_btn = QPushButton("עיון...")
        self.browse_btn.clicked.connect(self.browse_output)
        folder_layout.addWidget(self.browse_btn)
        download_layout.addLayout(folder_layout)
        
        # Download options
        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("סוג הורדה / Download type:"))
        self.download_type = QComboBox()
        self.download_type.addItems(["אודיו + וידאו / Both", "אודיו בלבד / Audio Only", "וידאו בלבד / Video Only"])
        options_layout.addWidget(self.download_type)
        download_layout.addLayout(options_layout)
        
        # Progress
        self.progress_bar = QProgressBar()
        download_layout.addWidget(self.progress_bar)
        
        # Log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        download_layout.addWidget(self.log_text)
        
        # Download button
        btn_layout = QHBoxLayout()
        self.download_btn = QPushButton("הורד נבחרים / Download Selected")
        self.download_btn.clicked.connect(self.on_download)
        self.download_btn.setEnabled(False)
        btn_layout.addWidget(self.download_btn)
        self.cancel_btn = QPushButton("ביטול / Cancel")
        self.cancel_btn.setEnabled(False)
        btn_layout.addWidget(self.cancel_btn)
        download_layout.addLayout(btn_layout)
        
        layout.addWidget(download_group)
    
    def load_settings(self):
        if self.settings.value('save_credentials', False, type=bool):
            self.save_creds_cb.setChecked(True)
            self.email_input.setText(self.settings.value('email', ''))
            # Note: In production, encrypt the password
            self.password_input.setText(self.settings.value('password', ''))
        self.output_path.setText(self.settings.value('output_path', str(Path.home() / 'NotebookLM_Downloads')))
    
    def save_settings(self):
        self.settings.setValue('save_credentials', self.save_creds_cb.isChecked())
        if self.save_creds_cb.isChecked():
            self.settings.setValue('email', self.email_input.text())
            self.settings.setValue('password', self.password_input.text())
        else:
            self.settings.remove('email')
            self.settings.remove('password')
        self.settings.setValue('output_path', self.output_path.text())
    
    def on_login(self):
        email = self.email_input.text().strip()
        password = self.password_input.text()
        
        if not email or not password:
            QMessageBox.warning(self, "שגיאה", "נא להזין אימייל וסיסמה")
            return
        
        self.save_settings()
        self.login_btn.setEnabled(False)
        self.auth_status.setText("מתחבר...")
        
        self.auth_worker = AuthWorker(email, password)
        self.auth_worker.status_update.connect(lambda s: self.auth_status.setText(s))
        self.auth_worker.auth_complete.connect(self.on_auth_complete)
        self.auth_worker.start()
    
    def on_auth_complete(self, success, downloader):
        self.login_btn.setEnabled(True)
        
        if success:
            self.downloader = downloader
            self.auth_status.setText("✓ מחובר! סורק מחברות...")
            self.scan_notebooks()
        else:
            self.auth_status.setText("✗ התחברות נכשלה")
    
    def scan_notebooks(self):
        if not self.downloader:
            return
        
        self.scan_worker = ScanWorker(self.downloader)
        self.scan_worker.status_update.connect(lambda s: self.log_text.append(s))
        self.scan_worker.scan_complete.connect(self.on_scan_complete)
        self.scan_worker.start()
    
    def on_scan_complete(self, notebooks):
        self.notebooks = notebooks
        self.notebook_list.clear()
        
        for nb in notebooks:
            audio_count = len(nb.audio_artifacts)
            video_count = len(nb.video_artifacts)
            item_text = f"{nb.emoji} {nb.title} ({audio_count} audio, {video_count} video)"
            
            item = QListWidgetItem(item_text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, nb)
            self.notebook_list.addItem(item)
        
        self.download_btn.setEnabled(True)
        self.auth_status.setText(f"✓ נמצאו {len(notebooks)} מחברות")
    
    def select_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Checked)
    
    def deselect_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Unchecked)
    
    def on_refresh(self):
        if self.downloader:
            self.scan_notebooks()
    
    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "בחר תיקייה")
        if folder:
            self.output_path.setText(folder)
    
    def on_download(self):
        # Get selected notebooks
        selected = []
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        
        if not selected:
            QMessageBox.warning(self, "שגיאה", "נא לבחור לפחות מחברת אחת")
            return
        
        output_dir = Path(self.output_path.text())
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Download options
        dl_type = self.download_type.currentIndex()
        audio = dl_type in [0, 1]  # Both or Audio Only
        video = dl_type in [0, 2]  # Both or Video Only
        
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log_text.clear()
        
        self.download_worker = DownloadWorker(
            self.downloader, selected, output_dir, audio, video
        )
        self.download_worker.progress_update.connect(self.on_progress)
        self.download_worker.download_complete.connect(self.on_download_complete)
        self.download_worker.start()
    
    def on_progress(self, progress):
        self.progress_bar.setValue(int(progress.current / progress.total * 100))
        
        status_emoji = "⏳" if progress.status == "downloading" else ("✓" if progress.status == "completed" else "✗")
        self.log_text.append(f"{status_emoji} [{progress.current}/{progress.total}] {progress.current_file}")
    
    def on_download_complete(self, files):
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        
        self.log_text.append(f"\n✓ הושלם! הורדו {len(files)} קבצים")
        QMessageBox.information(self, "הושלם", f"הורדו {len(files)} קבצים בהצלחה!")
```

### 4. Integration

In `main.py`, add the new tab:
```python
from ui.notebooklm_tab import NotebookLMTab

# In MainWindow.__init__:
self.tab_widget.addTab(NotebookLMTab(), "NotebookLM")
```

### 5. Requirements

Add to `requirements.txt`:
```
playwright>=1.40.0
```

Run after install:
```bash
playwright install chromium
```

### 6. Key Features

1. **Google Authentication**: Uses Playwright to handle Google login (supports accounts without 2FA)
2. **Notebook Scanning**: Automatically finds all notebooks and their audio/video artifacts
3. **Batch Download**: Downloads multiple files with progress tracking
4. **Hebrew UI**: Bilingual interface (Hebrew + English)
5. **Settings Persistence**: Saves credentials and output path between sessions
6. **Progress Feedback**: Real-time progress bar and detailed log

### 7. URL Pattern Recognition

The downloader looks for these URL patterns in NotebookLM pages:
- **Audio**: `https://lh3.googleusercontent.com/notebooklm/...=m22?authuser=0`
- **Video**: `https://lh3.googleusercontent.com/notebooklm/...=m22-dv?authuser=0`

### 8. Error Handling

- Handle authentication failures gracefully
- Retry failed downloads
- Show clear error messages in Hebrew
- Log all operations for debugging

### 9. Testing

Test with:
1. Fresh login (no saved credentials)
2. Saved credentials login
3. Multiple notebooks with various artifact counts
4. Large file downloads
5. Network interruption handling

## DO NOT ASK - JUST DO

Start by reading the SKILL.md files, then implement the NotebookLM downloader feature. Create all necessary files and integrate with the existing app structure.