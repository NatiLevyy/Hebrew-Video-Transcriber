"""
NotebookLM Batch Downloader Tab for Hebrew Transcriber.
Two-step workflow: List notebooks -> Select -> Scan for media -> Download
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QProgressBar,
    QTextEdit, QGroupBox, QFileDialog, QMessageBox,
    QComboBox, QSplitter
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path


class AuthWorker(QThread):
    """Worker thread for authentication."""
    status_update = pyqtSignal(str)
    auth_complete = pyqtSignal(bool, object)

    def run(self):
        from core.notebooklm_downloader import NotebookLMDownloader
        downloader = NotebookLMDownloader()
        success = downloader.authenticate(self.status_update.emit)
        self.auth_complete.emit(success, downloader if success else None)


class ListNotebooksWorker(QThread):
    """Worker thread for listing notebooks (titles only, fast)."""
    status_update = pyqtSignal(str)
    list_complete = pyqtSignal(list)

    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader

    def run(self):
        notebooks = self.downloader.list_notebooks(self.status_update.emit)
        self.list_complete.emit(notebooks)


class ScanMediaWorker(QThread):
    """Worker thread for scanning selected notebooks for media."""
    status_update = pyqtSignal(str)
    scan_complete = pyqtSignal(list)

    def __init__(self, downloader, notebooks):
        super().__init__()
        self.downloader = downloader
        self.notebooks = notebooks

    def run(self):
        notebooks_with_media = self.downloader.scan_for_media(self.notebooks, self.status_update.emit)
        self.scan_complete.emit(notebooks_with_media)


class DownloadWorker(QThread):
    """Worker thread for downloading."""
    progress_update = pyqtSignal(object)
    download_complete = pyqtSignal(list)

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
    """Tab widget for NotebookLM batch downloading."""

    def __init__(self):
        super().__init__()
        self.downloader = None
        self.notebooks = []  # All notebooks (titles)
        self.notebooks_with_media = []  # Scanned notebooks with media
        self.settings = QSettings('HebrewTranscriber', 'NotebookLM')
        self.auth_worker = None
        self.list_worker = None
        self.scan_worker = None
        self.download_worker = None
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === LEFT SIDE - Controls ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(10)

        # Auth Group
        auth_group = QGroupBox("Google Login")
        auth_layout = QVBoxLayout(auth_group)

        info_label = QLabel("Click to open Chrome and log in to Google.")
        info_label.setWordWrap(True)
        auth_layout.addWidget(info_label)

        self.login_btn = QPushButton("Launch Chrome")
        self.login_btn.setObjectName("loginBtn")
        self.login_btn.clicked.connect(self.on_login)
        auth_layout.addWidget(self.login_btn)

        self.auth_status = QLabel("")
        auth_layout.addWidget(self.auth_status)

        left_layout.addWidget(auth_group)

        # Notebooks Group
        notebooks_group = QGroupBox("Notebooks (select to scan for media)")
        notebooks_layout = QVBoxLayout(notebooks_group)

        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("Deselect")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        self.refresh_btn = QPushButton("Refresh List")
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.refresh_btn.setEnabled(False)
        btn_layout.addWidget(self.select_all_btn)
        btn_layout.addWidget(self.deselect_all_btn)
        btn_layout.addWidget(self.refresh_btn)
        notebooks_layout.addLayout(btn_layout)

        self.notebook_list = QListWidget()
        self.notebook_list.setMinimumHeight(350)
        self.notebook_list.setMinimumWidth(400)
        notebooks_layout.addWidget(self.notebook_list)

        # Scan button
        self.scan_btn = QPushButton("Scan Selected for Media")
        self.scan_btn.setObjectName("scanBtn")
        self.scan_btn.clicked.connect(self.on_scan_selected)
        self.scan_btn.setEnabled(False)
        self.scan_btn.setStyleSheet("background-color: #2196F3; color: white; padding: 8px;")
        notebooks_layout.addWidget(self.scan_btn)

        left_layout.addWidget(notebooks_group)

        # Download Group
        download_group = QGroupBox("Download")
        download_layout = QVBoxLayout(download_group)

        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Output:"))
        self.output_path_label = QLabel()
        self.output_path_label.setObjectName("pathLabel")
        folder_layout.addWidget(self.output_path_label, 1)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setMaximumWidth(30)
        self.browse_btn.clicked.connect(self.browse_output)
        folder_layout.addWidget(self.browse_btn)
        download_layout.addLayout(folder_layout)

        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Type:"))
        self.download_type = QComboBox()
        self.download_type.addItems(["Both", "Audio Only", "Video Only"])
        type_layout.addWidget(self.download_type)
        type_layout.addStretch()
        download_layout.addLayout(type_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        download_layout.addWidget(self.progress_bar)

        btn_layout2 = QHBoxLayout()
        self.download_btn = QPushButton("Download Media")
        self.download_btn.setObjectName("downloadBtn")
        self.download_btn.clicked.connect(self.on_download)
        self.download_btn.setEnabled(False)
        btn_layout2.addWidget(self.download_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setEnabled(False)
        btn_layout2.addWidget(self.cancel_btn)
        download_layout.addLayout(btn_layout2)

        left_layout.addWidget(download_group)
        left_layout.addStretch()

        # === RIGHT SIDE - Log ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        log_label = QLabel("Log:")
        right_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        right_layout.addWidget(self.log_text)

        # Add to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([550, 450])

        main_layout.addWidget(splitter)

    def load_settings(self):
        default_path = str(Path.home() / 'NotebookLM_Downloads')
        self.output_path = self.settings.value('output_path', default_path)
        self.output_path_label.setText(self.output_path)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def on_login(self):
        self.login_btn.setEnabled(False)
        self.auth_status.setText("Starting...")
        self.log_text.clear()
        self.log("Starting authentication...")

        self.auth_worker = AuthWorker()
        self.auth_worker.status_update.connect(self.on_auth_status)
        self.auth_worker.auth_complete.connect(self.on_auth_complete)
        self.auth_worker.start()

    def on_auth_status(self, status: str):
        self.auth_status.setText(status[:50])
        self.log(status)

    def on_auth_complete(self, success: bool, downloader):
        self.login_btn.setEnabled(True)

        if success:
            self.downloader = downloader
            self.auth_status.setText("Connected!")
            self.refresh_btn.setEnabled(True)
            self.log("Authentication successful. Loading notebook list...")
            self.list_notebooks()
        else:
            self.auth_status.setText("Failed")
            self.log("Authentication failed.")

    def list_notebooks(self):
        """Step 1: Get list of notebook titles (fast)."""
        if not self.downloader:
            return

        self.refresh_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.notebook_list.clear()

        self.list_worker = ListNotebooksWorker(self.downloader)
        self.list_worker.status_update.connect(self.log)
        self.list_worker.list_complete.connect(self.on_list_complete)
        self.list_worker.start()

    def on_list_complete(self, notebooks):
        """Notebooks listed - show titles for selection."""
        # Sort alphabetically by title
        notebooks.sort(key=lambda nb: nb.title.lower())
        self.notebooks = notebooks
        self.notebook_list.clear()
        self.refresh_btn.setEnabled(True)

        for nb in notebooks:
            # Show just title (no media count yet)
            item_text = f"{nb.emoji} {nb.title}"
            item = QListWidgetItem(item_text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, nb)
            self.notebook_list.addItem(item)

        self.scan_btn.setEnabled(len(notebooks) > 0)
        self.auth_status.setText(f"Found {len(notebooks)} notebooks")
        self.log(f"Found {len(notebooks)} notebooks. Select notebooks and click 'Scan Selected for Media'.")

    def on_scan_selected(self):
        """Step 2: Scan selected notebooks for audio/video."""
        selected = []
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select at least one notebook to scan.")
            return

        self.scan_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.log(f"\nScanning {len(selected)} notebooks for media...")

        self.scan_worker = ScanMediaWorker(self.downloader, selected)
        self.scan_worker.status_update.connect(self.log)
        self.scan_worker.scan_complete.connect(self.on_scan_complete)
        self.scan_worker.start()

    def on_scan_complete(self, notebooks_with_media):
        """Media scan complete - show results and enable download."""
        self.notebooks_with_media = notebooks_with_media
        self.scan_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)

        # Update list to show media counts
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            nb = item.data(Qt.ItemDataRole.UserRole)

            # Find if this notebook has media
            media_nb = next((n for n in notebooks_with_media if n.project_id == nb.project_id), None)

            if media_nb:
                audio_count = len(media_nb.audio_artifacts)
                video_count = len(media_nb.video_artifacts)
                item.setText(f"{nb.emoji} {nb.title} [{audio_count}a, {video_count}v]")
                item.setData(Qt.ItemDataRole.UserRole, media_nb)
                item.setCheckState(Qt.CheckState.Checked)  # Keep selected
            else:
                # Not scanned or no media
                if item.checkState() == Qt.CheckState.Checked:
                    item.setText(f"{nb.emoji} {nb.title} [no media]")

        if notebooks_with_media:
            self.download_btn.setEnabled(True)
            total_audio = sum(len(nb.audio_artifacts) for nb in notebooks_with_media)
            total_video = sum(len(nb.video_artifacts) for nb in notebooks_with_media)
            self.log(f"\nReady to download: {len(notebooks_with_media)} notebooks, {total_audio} audio, {total_video} video")
        else:
            self.log("\nNo media found in selected notebooks.")

    def select_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Checked)

    def deselect_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def on_refresh(self):
        if self.downloader:
            self.notebooks_with_media = []
            self.download_btn.setEnabled(False)
            self.list_notebooks()

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder")
        if folder:
            self.output_path = folder
            self.output_path_label.setText(folder)
            self.settings.setValue('output_path', folder)

    def on_download(self):
        """Download media from scanned notebooks."""
        if not self.notebooks_with_media:
            QMessageBox.warning(self, "No Media", "No media to download. Scan notebooks first.")
            return

        output_dir = Path(self.output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        dl_type = self.download_type.currentIndex()
        audio = dl_type in [0, 1]
        video = dl_type in [0, 2]

        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        total_files = sum(
            (len(nb.audio_artifacts) if audio else 0) + (len(nb.video_artifacts) if video else 0)
            for nb in self.notebooks_with_media
        )
        self.log(f"\nDownloading {total_files} files...")

        self.download_worker = DownloadWorker(
            self.downloader, self.notebooks_with_media, output_dir, audio, video
        )
        self.download_worker.progress_update.connect(self.on_progress)
        self.download_worker.download_complete.connect(self.on_download_complete)
        self.download_worker.start()

    def on_cancel(self):
        if self.downloader:
            self.downloader.cancel()
        self.cancel_btn.setEnabled(False)
        self.log("Cancelling...")

    def on_progress(self, progress):
        percent = int(progress.current / progress.total * 100) if progress.total > 0 else 0
        self.progress_bar.setValue(percent)

        status = {"downloading": "...", "completed": "OK", "failed": "X"}.get(progress.status, "")
        self.log(f"[{status}] {progress.current}/{progress.total} {progress.current_file}")

    def on_download_complete(self, files):
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setValue(100)

        self.log(f"\nDone! Downloaded {len(files)} files.")

        if files:
            QMessageBox.information(self, "Complete", f"Downloaded {len(files)} files!")
            import os
            os.startfile(str(self.output_path))
