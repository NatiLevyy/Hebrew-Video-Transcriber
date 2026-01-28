"""
Complete Pipeline Tab - Full workflow from NotebookLM to embedded videos.

Steps:
1. Login to NotebookLM (Chrome CDP)
2. Scan & Select notebooks
3. Download videos
4. Transcribe to Hebrew SRT
5. Fix RTL punctuation
6. Embed subtitles into videos
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QCheckBox, QListWidget,
    QListWidgetItem, QSplitter, QFrame, QScrollArea,
    QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path
import os

from core.transcriber import HebrewTranscriber
from core.audio_extractor import AudioExtractor
from core.exporter import SRTExporter
from core.subtitle_embedder import embed_subtitles, is_mkvmerge_available, VIDEO_FORMATS
from core.notebooklm_downloader import (
    NotebookLMDownloader, launch_chrome, is_chrome_running,
    connect_to_chrome, safe_disconnect, NotebookInfo, DownloadProgress
)


# ========== WORKERS ==========

class AuthWorker(QThread):
    """Worker for NotebookLM authentication."""
    status_update = pyqtSignal(str)
    auth_complete = pyqtSignal(bool, object)

    def run(self):
        downloader = NotebookLMDownloader()
        success = downloader.authenticate(self.status_update.emit)
        self.auth_complete.emit(success, downloader if success else None)


class ListNotebooksWorker(QThread):
    """Worker for listing notebooks."""
    status_update = pyqtSignal(str)
    list_complete = pyqtSignal(list)

    def __init__(self, downloader):
        super().__init__()
        self.downloader = downloader

    def run(self):
        notebooks = self.downloader.list_notebooks(self.status_update.emit)
        self.list_complete.emit(notebooks)


class ScanMediaWorker(QThread):
    """Worker for scanning notebooks for media."""
    status_update = pyqtSignal(str)
    scan_complete = pyqtSignal(list)

    def __init__(self, downloader, notebooks):
        super().__init__()
        self.downloader = downloader
        self.notebooks = notebooks

    def run(self):
        notebooks_with_media = self.downloader.scan_for_media(
            self.notebooks, self.status_update.emit
        )
        self.scan_complete.emit(notebooks_with_media)


class DownloadWorker(QThread):
    """Worker for downloading media."""
    progress_update = pyqtSignal(object)
    download_complete = pyqtSignal(list)

    def __init__(self, downloader, notebooks, output_dir):
        super().__init__()
        self.downloader = downloader
        self.notebooks = notebooks
        self.output_dir = output_dir

    def run(self):
        files = self.downloader.download_artifacts(
            self.notebooks,
            self.output_dir,
            download_audio=True,
            download_video=True,
            on_progress=self.progress_update.emit
        )
        self.download_complete.emit(files)


class TranscribeWorker(QThread):
    """Worker for transcription."""
    log_update = pyqtSignal(str)
    progress_update = pyqtSignal(int, int)
    transcribe_complete = pyqtSignal(dict)

    def __init__(self, video_files, srt_folder):
        super().__init__()
        self.video_files = video_files
        self.srt_folder = srt_folder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        results = {'transcribed': [], 'failed': []}

        if not self.video_files:
            self.transcribe_complete.emit(results)
            return

        transcriber = HebrewTranscriber()
        extractor = AudioExtractor()

        self.log_update.emit("Loading transcription model...")
        try:
            transcriber.load_model()
            self.log_update.emit(f"Model loaded on {transcriber.device.upper()}")
        except Exception as e:
            self.log_update.emit(f"ERROR: {e}")
            self.transcribe_complete.emit(results)
            return

        self.srt_folder.mkdir(parents=True, exist_ok=True)
        total = len(self.video_files)

        for i, video_path in enumerate(self.video_files):
            if self._cancelled:
                break

            video_path = Path(video_path)
            self.progress_update.emit(i + 1, total)
            self.log_update.emit(f"[{i+1}/{total}] {video_path.name}")

            try:
                # Extract audio
                audio_path = extractor.extract(str(video_path))

                # Transcribe
                segments = transcriber.transcribe(audio_path)

                # Cleanup
                Path(audio_path).unlink(missing_ok=True)

                # Save SRT
                srt_path = self.srt_folder / f"{video_path.stem}.srt"
                SRTExporter().export(segments, str(srt_path), video_path.stem)

                results['transcribed'].append(video_path.name)
                self.log_update.emit(f"  ✓ {srt_path.name}")

            except Exception as e:
                results['failed'].append((video_path.name, str(e)))
                self.log_update.emit(f"  ✗ Error: {e}")

        self.transcribe_complete.emit(results)


class EmbedWorker(QThread):
    """Worker for RTL fix + embedding."""
    log_update = pyqtSignal(str)
    progress_update = pyqtSignal(int, int)
    embed_complete = pyqtSignal(dict)

    def __init__(self, video_folder, srt_folder, output_folder):
        super().__init__()
        self.video_folder = video_folder
        self.srt_folder = srt_folder
        self.output_folder = output_folder

    def run(self):
        result = embed_subtitles(
            video_folder=self.video_folder,
            srt_folder=self.srt_folder,
            output_folder=self.output_folder,
            log=self.log_update.emit,
            progress=self.progress_update.emit,
            skip_existing=True,
            fix_rtl=True
        )
        self.embed_complete.emit(result)


# ========== MAIN TAB ==========

class PipelineTab(QWidget):
    """Complete pipeline tab with all steps."""

    def __init__(self):
        super().__init__()
        self.settings = QSettings('HebrewTranscriber', 'Pipeline')

        # State
        self.downloader = None
        self.notebooks = []
        self.notebooks_with_media = []
        self.downloaded_files = []
        self.output_folder = None

        # Workers
        self.auth_worker = None
        self.list_worker = None
        self.scan_worker = None
        self.download_worker = None
        self.transcribe_worker = None
        self.embed_worker = None

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === LEFT: Steps Panel (scrollable) ===
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(500)
        left_scroll.setMaximumWidth(600)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(8)

        # Title
        title = QLabel("⚡ Complete Pipeline")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #4CAF50;")
        left_layout.addWidget(title)

        # ===== STEP 1: NotebookLM Login =====
        step1_group = QGroupBox("Step 1: NotebookLM Login")
        step1_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        step1_layout = QVBoxLayout(step1_group)

        step1_info = QLabel("Launch Chrome and login to your Google account")
        step1_info.setStyleSheet("color: #666; font-size: 11px;")
        step1_layout.addWidget(step1_info)

        self.login_btn = QPushButton("🌐 Launch Chrome & Login")
        self.login_btn.setStyleSheet("padding: 10px; font-size: 13px;")
        self.login_btn.clicked.connect(self.on_login)
        step1_layout.addWidget(self.login_btn)

        self.login_status = QLabel("")
        step1_layout.addWidget(self.login_status)

        left_layout.addWidget(step1_group)

        # ===== STEP 2: Select Notebooks =====
        step2_group = QGroupBox("Step 2: Select Notebooks")
        step2_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        step2_layout = QVBoxLayout(step2_group)

        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_btn = QPushButton("Deselect")
        self.deselect_btn.clicked.connect(self.deselect_all)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.refresh_btn.setEnabled(False)
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_btn)
        btn_row.addWidget(self.refresh_btn)
        step2_layout.addLayout(btn_row)

        self.notebook_list = QListWidget()
        self.notebook_list.setMinimumHeight(150)
        self.notebook_list.setMaximumHeight(200)
        step2_layout.addWidget(self.notebook_list)

        self.scan_btn = QPushButton("🔍 Scan Selected for Media")
        self.scan_btn.setStyleSheet("padding: 8px; background-color: #2196F3; color: white;")
        self.scan_btn.clicked.connect(self.on_scan)
        self.scan_btn.setEnabled(False)
        step2_layout.addWidget(self.scan_btn)

        left_layout.addWidget(step2_group)

        # ===== STEP 3: Download =====
        step3_group = QGroupBox("Step 3: Download Videos")
        step3_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        step3_layout = QVBoxLayout(step3_group)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Output Folder:"))
        self.output_label = QLabel("Not selected")
        self.output_label.setStyleSheet("color: #666;")
        folder_row.addWidget(self.output_label, 1)
        self.browse_btn = QPushButton("...")
        self.browse_btn.setMaximumWidth(30)
        self.browse_btn.clicked.connect(self.browse_output)
        folder_row.addWidget(self.browse_btn)
        step3_layout.addLayout(folder_row)

        self.download_btn = QPushButton("⬇️ Download Media")
        self.download_btn.setStyleSheet("padding: 10px; font-size: 13px;")
        self.download_btn.clicked.connect(self.on_download)
        self.download_btn.setEnabled(False)
        step3_layout.addWidget(self.download_btn)

        self.download_progress = QProgressBar()
        self.download_progress.setVisible(False)
        step3_layout.addWidget(self.download_progress)

        left_layout.addWidget(step3_group)

        # ===== STEP 4: Transcribe =====
        step4_group = QGroupBox("Step 4: Transcribe to Hebrew")
        step4_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        step4_layout = QVBoxLayout(step4_group)

        self.transcribe_info = QLabel("Transcribe downloaded videos using ivrit-ai/whisper")
        self.transcribe_info.setStyleSheet("color: #666; font-size: 11px;")
        step4_layout.addWidget(self.transcribe_info)

        self.transcribe_btn = QPushButton("🎤 Transcribe Videos")
        self.transcribe_btn.setStyleSheet("padding: 10px; font-size: 13px;")
        self.transcribe_btn.clicked.connect(self.on_transcribe)
        self.transcribe_btn.setEnabled(False)
        step4_layout.addWidget(self.transcribe_btn)

        self.transcribe_progress = QProgressBar()
        self.transcribe_progress.setVisible(False)
        step4_layout.addWidget(self.transcribe_progress)

        left_layout.addWidget(step4_group)

        # ===== STEP 5: RTL Fix + Embed =====
        step5_group = QGroupBox("Step 5: RTL Fix + Embed Subtitles")
        step5_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        step5_layout = QVBoxLayout(step5_group)

        # MKVToolNix status
        self.mkvmerge_status = QLabel()
        if is_mkvmerge_available():
            self.mkvmerge_status.setText("✓ MKVToolNix found")
            self.mkvmerge_status.setStyleSheet("color: green; font-size: 11px;")
        else:
            self.mkvmerge_status.setText("⚠ MKVToolNix not found - Install from mkvtoolnix.download")
            self.mkvmerge_status.setStyleSheet("color: orange; font-size: 11px;")
        step5_layout.addWidget(self.mkvmerge_status)

        self.embed_btn = QPushButton("📀 Fix RTL & Embed Subtitles")
        self.embed_btn.setStyleSheet("padding: 10px; font-size: 13px;")
        self.embed_btn.clicked.connect(self.on_embed)
        self.embed_btn.setEnabled(False)
        step5_layout.addWidget(self.embed_btn)

        self.embed_progress = QProgressBar()
        self.embed_progress.setVisible(False)
        step5_layout.addWidget(self.embed_progress)

        left_layout.addWidget(step5_group)

        # ===== RUN ALL Button =====
        self.run_all_btn = QPushButton("▶️ RUN COMPLETE PIPELINE")
        self.run_all_btn.setStyleSheet("""
            QPushButton {
                padding: 15px;
                font-size: 16px;
                font-weight: bold;
                background-color: #4CAF50;
                color: white;
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.run_all_btn.clicked.connect(self.on_run_all)
        self.run_all_btn.setEnabled(False)
        left_layout.addWidget(self.run_all_btn)

        # Cancel button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setEnabled(False)
        left_layout.addWidget(self.cancel_btn)

        left_layout.addStretch()
        left_scroll.setWidget(left_widget)

        # === RIGHT: Log Panel ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        log_title = QLabel("Pipeline Log")
        log_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        right_layout.addWidget(log_title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        right_layout.addWidget(self.log_text)

        # Summary
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("font-size: 12px; padding: 5px; background: #f0f0f0; border-radius: 4px;")
        right_layout.addWidget(self.summary_label)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_widget)
        splitter.setSizes([500, 500])

        main_layout.addWidget(splitter)

    def load_settings(self):
        self.output_folder = self.settings.value('output_folder', '')
        if self.output_folder:
            self.output_label.setText(self.output_folder)

    def save_settings(self):
        if self.output_folder:
            self.settings.setValue('output_folder', self.output_folder)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def update_summary(self, text: str):
        self.summary_label.setText(text)

    # ========== STEP 1: Login ==========
    def on_login(self):
        self.login_btn.setEnabled(False)
        self.login_status.setText("Starting Chrome...")
        self.log_text.clear()
        self.log("=== Step 1: NotebookLM Login ===")

        self.auth_worker = AuthWorker()
        self.auth_worker.status_update.connect(self.log)
        self.auth_worker.auth_complete.connect(self.on_auth_complete)
        self.auth_worker.start()

    def on_auth_complete(self, success: bool, downloader):
        self.login_btn.setEnabled(True)
        if success:
            self.downloader = downloader
            self.login_status.setText("✓ Connected!")
            self.login_status.setStyleSheet("color: green; font-weight: bold;")
            self.refresh_btn.setEnabled(True)
            self.log("Login successful!")
            self.list_notebooks()
        else:
            self.login_status.setText("✗ Failed")
            self.login_status.setStyleSheet("color: red;")

    # ========== STEP 2: List & Select Notebooks ==========
    def list_notebooks(self):
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
        notebooks.sort(key=lambda nb: nb.title.lower())
        self.notebooks = notebooks
        self.notebook_list.clear()
        self.refresh_btn.setEnabled(True)

        for nb in notebooks:
            item = QListWidgetItem(f"{nb.emoji} {nb.title}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, nb)
            self.notebook_list.addItem(item)

        self.scan_btn.setEnabled(len(notebooks) > 0)
        self.log(f"Found {len(notebooks)} notebooks")
        self.update_summary(f"📓 {len(notebooks)} notebooks found")

    def select_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Checked)

    def deselect_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    def on_refresh(self):
        self.notebooks_with_media = []
        self.download_btn.setEnabled(False)
        self.list_notebooks()

    def on_scan(self):
        selected = []
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected:
            QMessageBox.warning(self, "Error", "Please select at least one notebook")
            return

        self.scan_btn.setEnabled(False)
        self.log(f"\n=== Step 2: Scanning {len(selected)} notebooks ===")

        self.scan_worker = ScanMediaWorker(self.downloader, selected)
        self.scan_worker.status_update.connect(self.log)
        self.scan_worker.scan_complete.connect(self.on_scan_complete)
        self.scan_worker.start()

    def on_scan_complete(self, notebooks_with_media):
        self.notebooks_with_media = notebooks_with_media
        self.scan_btn.setEnabled(True)

        # Update list with media counts
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            nb = item.data(Qt.ItemDataRole.UserRole)
            media_nb = next((n for n in notebooks_with_media if n.project_id == nb.project_id), None)
            if media_nb:
                a = len(media_nb.audio_artifacts)
                v = len(media_nb.video_artifacts)
                item.setText(f"{nb.emoji} {nb.title} [{a}a, {v}v]")
                item.setData(Qt.ItemDataRole.UserRole, media_nb)

        if notebooks_with_media:
            self.download_btn.setEnabled(True)
            total_a = sum(len(nb.audio_artifacts) for nb in notebooks_with_media)
            total_v = sum(len(nb.video_artifacts) for nb in notebooks_with_media)
            self.log(f"Ready: {len(notebooks_with_media)} notebooks, {total_a} audio, {total_v} video")
            self.update_summary(f"🎬 {total_a + total_v} media files ready to download")
        else:
            self.log("No media found")

    # ========== STEP 3: Download ==========
    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_label.setText(folder)
            self.save_settings()

    def on_download(self):
        if not self.notebooks_with_media:
            QMessageBox.warning(self, "Error", "No media to download")
            return
        if not self.output_folder:
            QMessageBox.warning(self, "Error", "Please select output folder")
            return

        self.download_btn.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_progress.setValue(0)
        self.cancel_btn.setEnabled(True)

        output_dir = Path(self.output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        self.log(f"\n=== Step 3: Downloading to {self.output_folder} ===")

        self.download_worker = DownloadWorker(
            self.downloader, self.notebooks_with_media, output_dir
        )
        self.download_worker.progress_update.connect(self.on_download_progress)
        self.download_worker.download_complete.connect(self.on_download_complete)
        self.download_worker.start()

    def on_download_progress(self, progress):
        if progress.total > 0:
            pct = int(progress.current / progress.total * 100)
            self.download_progress.setValue(pct)
        self.log(f"[{progress.status}] {progress.current}/{progress.total} {progress.current_file}")

    def on_download_complete(self, files):
        self.downloaded_files = files
        self.download_btn.setEnabled(True)
        self.download_progress.setVisible(False)
        self.cancel_btn.setEnabled(False)

        self.log(f"Downloaded {len(files)} files")
        self.update_summary(f"⬇️ Downloaded {len(files)} files")

        if files:
            self.transcribe_btn.setEnabled(True)

    # ========== STEP 4: Transcribe ==========
    def on_transcribe(self):
        if not self.output_folder:
            QMessageBox.warning(self, "Error", "No output folder set")
            return

        # Find video files
        output_path = Path(self.output_folder)
        video_files = [f for f in output_path.iterdir()
                      if f.is_file() and f.suffix.lower() in VIDEO_FORMATS]

        if not video_files:
            QMessageBox.warning(self, "Error", "No video files found in output folder")
            return

        self.transcribe_btn.setEnabled(False)
        self.transcribe_progress.setVisible(True)
        self.transcribe_progress.setValue(0)
        self.cancel_btn.setEnabled(True)

        srt_folder = output_path / "Subtitle_HEBREW"

        self.log(f"\n=== Step 4: Transcribing {len(video_files)} videos ===")

        self.transcribe_worker = TranscribeWorker(video_files, srt_folder)
        self.transcribe_worker.log_update.connect(self.log)
        self.transcribe_worker.progress_update.connect(
            lambda c, t: self.transcribe_progress.setValue(int(c/t*100) if t else 0)
        )
        self.transcribe_worker.transcribe_complete.connect(self.on_transcribe_complete)
        self.transcribe_worker.start()

    def on_transcribe_complete(self, results):
        self.transcribe_btn.setEnabled(True)
        self.transcribe_progress.setVisible(False)
        self.cancel_btn.setEnabled(False)

        count = len(results.get('transcribed', []))
        self.log(f"Transcribed {count} files")
        self.update_summary(f"🎤 Transcribed {count} files")

        if count > 0 and is_mkvmerge_available():
            self.embed_btn.setEnabled(True)

    # ========== STEP 5: RTL + Embed ==========
    def on_embed(self):
        if not self.output_folder:
            return

        output_path = Path(self.output_folder)
        srt_folder = output_path / "Subtitle_HEBREW"
        embed_folder = output_path / "Embedded_Videos"

        if not srt_folder.exists():
            QMessageBox.warning(self, "Error", "No SRT files found. Run transcription first.")
            return

        self.embed_btn.setEnabled(False)
        self.embed_progress.setVisible(True)
        self.embed_progress.setValue(0)
        self.cancel_btn.setEnabled(True)

        self.log(f"\n=== Step 5: RTL Fix + Embedding ===")

        self.embed_worker = EmbedWorker(output_path, srt_folder, embed_folder)
        self.embed_worker.log_update.connect(self.log)
        self.embed_worker.progress_update.connect(
            lambda c, t: self.embed_progress.setValue(int(c/t*100) if t else 0)
        )
        self.embed_worker.embed_complete.connect(self.on_embed_complete)
        self.embed_worker.start()

    def on_embed_complete(self, result):
        self.embed_btn.setEnabled(True)
        self.embed_progress.setVisible(False)
        self.cancel_btn.setEnabled(False)

        count = len(result.get('embedded', []))
        rtl = result.get('rtl_fixed', 0)
        self.log(f"\n✅ PIPELINE COMPLETE!")
        self.log(f"Embedded: {count} videos")
        self.log(f"RTL lines fixed: {rtl}")
        self.update_summary(f"✅ Complete! {count} videos with embedded Hebrew subtitles")

        # Open output folder
        output = result.get('output_folder')
        if output and Path(output).exists():
            QMessageBox.information(self, "Complete", f"Pipeline complete!\n\nEmbedded {count} videos.")
            os.startfile(str(output))

    # ========== RUN ALL ==========
    def on_run_all(self):
        # This button runs the complete pipeline automatically
        # For now, guide user through steps
        QMessageBox.information(
            self, "Run Pipeline",
            "Please follow the steps in order:\n\n"
            "1. Login to NotebookLM\n"
            "2. Select notebooks and scan for media\n"
            "3. Download videos\n"
            "4. Transcribe\n"
            "5. Embed subtitles\n\n"
            "Each step will enable the next when ready."
        )

    def on_cancel(self):
        if self.downloader:
            self.downloader.cancel()
        if self.transcribe_worker:
            self.transcribe_worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.log("Cancelling...")
