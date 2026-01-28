"""
Complete Automated Pipeline Tab - One-click workflow from NotebookLM to embedded videos.

User does:
1. Select output folder
2. Login to NotebookLM
3. Select notebooks
4. Click START

System does automatically:
Scan → Download → Transcribe → RTL Fix → Embed
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QCheckBox, QListWidget,
    QListWidgetItem, QSplitter, QScrollArea
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path
import os

from core.transcriber import HebrewTranscriber
from core.audio_extractor import AudioExtractor
from core.exporter import SRTExporter
from core.subtitle_embedder import embed_subtitles, is_mkvmerge_available, VIDEO_FORMATS
from core.notebooklm_downloader import (
    NotebookLMDownloader, NotebookInfo, DownloadProgress
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


class FullPipelineWorker(QThread):
    """
    Worker that runs the COMPLETE pipeline automatically:
    Scan → Download → Transcribe → RTL Fix → Embed
    """
    log_update = pyqtSignal(str)
    stage_update = pyqtSignal(str, int)  # stage_name, progress_percent
    pipeline_complete = pyqtSignal(dict)

    def __init__(self, downloader, notebooks, output_folder, do_download, do_transcribe, do_embed):
        super().__init__()
        self.downloader = downloader
        self.notebooks = notebooks
        self.output_folder = Path(output_folder)
        self.do_download = do_download
        self.do_transcribe = do_transcribe
        self.do_embed = do_embed
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        if self.downloader:
            self.downloader.cancel()

    def run(self):
        results = {
            'scanned': 0,
            'downloaded': 0,
            'transcribed': 0,
            'embedded': 0,
            'rtl_fixed': 0,
            'errors': []
        }

        try:
            # ===== STAGE 1: SCAN FOR MEDIA =====
            self.log_update.emit("\n" + "=" * 50)
            self.log_update.emit("📡 STAGE 1: SCANNING FOR MEDIA")
            self.log_update.emit("=" * 50)
            self.stage_update.emit("Scanning notebooks...", 5)

            notebooks_with_media = self.downloader.scan_for_media(
                self.notebooks, self.log_update.emit
            )

            if self._cancelled:
                self.pipeline_complete.emit(results)
                return

            if not notebooks_with_media:
                self.log_update.emit("No media found in selected notebooks!")
                self.pipeline_complete.emit(results)
                return

            total_media = sum(
                len(nb.audio_artifacts) + len(nb.video_artifacts)
                for nb in notebooks_with_media
            )
            results['scanned'] = total_media
            self.log_update.emit(f"✓ Found {total_media} media files in {len(notebooks_with_media)} notebooks")

            # ===== STAGE 2: DOWNLOAD =====
            if self.do_download:
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("⬇️ STAGE 2: DOWNLOADING")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Downloading...", 20)

                self.output_folder.mkdir(parents=True, exist_ok=True)

                downloaded_files = self.downloader.download_artifacts(
                    notebooks_with_media,
                    self.output_folder,
                    download_audio=True,
                    download_video=True,
                    on_progress=lambda p: self.log_update.emit(
                        f"  [{p.current}/{p.total}] {p.current_file}"
                    )
                )

                if self._cancelled:
                    self.pipeline_complete.emit(results)
                    return

                results['downloaded'] = len(downloaded_files)
                self.log_update.emit(f"✓ Downloaded {len(downloaded_files)} files")

            # ===== STAGE 3: TRANSCRIBE =====
            if self.do_transcribe:
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("🎤 STAGE 3: TRANSCRIBING TO HEBREW")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Loading model...", 40)

                # Find all notebook subfolders
                nb_folders = [
                    f for f in self.output_folder.iterdir()
                    if f.is_dir() and f.name not in ('Subtitle_HEBREW', 'Embedded_Videos')
                ]

                # Collect all video files across notebook folders
                all_videos = []
                for nb_folder in nb_folders:
                    for vf in nb_folder.iterdir():
                        if vf.is_file() and vf.suffix.lower() in VIDEO_FORMATS:
                            all_videos.append((nb_folder, vf))

                if not all_videos:
                    self.log_update.emit("No video files to transcribe")
                else:
                    transcriber = HebrewTranscriber()
                    extractor = AudioExtractor()

                    self.log_update.emit("Loading ivrit-ai/whisper model...")
                    transcriber.load_model()
                    self.log_update.emit(f"Model loaded on {transcriber.device.upper()}")

                    total = len(all_videos)
                    for i, (nb_folder, video_path) in enumerate(all_videos):
                        if self._cancelled:
                            break

                        progress = 40 + int((i / total) * 30)
                        self.stage_update.emit(f"Transcribing {i+1}/{total}...", progress)
                        self.log_update.emit(f"  [{i+1}/{total}] {nb_folder.name}/{video_path.name}")

                        try:
                            audio_path = extractor.extract(str(video_path))
                            segments = transcriber.transcribe(audio_path)
                            Path(audio_path).unlink(missing_ok=True)

                            # Save SRT inside the notebook folder
                            srt_folder = nb_folder / "Subtitle_HEBREW"
                            srt_folder.mkdir(exist_ok=True)

                            srt_path = srt_folder / f"{video_path.stem}.srt"
                            SRTExporter().export(segments, str(srt_path), video_path.stem)

                            results['transcribed'] += 1
                            self.log_update.emit(f"    ✓ {srt_path.name}")

                        except Exception as e:
                            results['errors'].append((video_path.name, str(e)))
                            self.log_update.emit(f"    ✗ Error: {e}")

                    self.log_update.emit(f"✓ Transcribed {results['transcribed']} files")

            # ===== STAGE 4: RTL FIX + EMBED =====
            if self.do_embed and is_mkvmerge_available():
                self.log_update.emit("\n" + "=" * 50)
                self.log_update.emit("📀 STAGE 4: RTL FIX + EMBED SUBTITLES")
                self.log_update.emit("=" * 50)
                self.stage_update.emit("Embedding subtitles...", 75)

                # Process each notebook folder separately
                nb_folders = [
                    f for f in self.output_folder.iterdir()
                    if f.is_dir() and f.name not in ('Subtitle_HEBREW', 'Embedded_Videos')
                ]

                for nb_folder in nb_folders:
                    srt_folder = nb_folder / "Subtitle_HEBREW"
                    embed_folder = nb_folder / "Embedded_Videos"

                    if srt_folder.exists():
                        self.log_update.emit(f"\n--- {nb_folder.name} ---")
                        embed_result = embed_subtitles(
                            video_folder=nb_folder,
                            srt_folder=srt_folder,
                            output_folder=embed_folder,
                            log=self.log_update.emit,
                            skip_existing=True,
                            fix_rtl=True
                        )

                        results['embedded'] += len(embed_result.get('embedded', []))
                        results['rtl_fixed'] += embed_result.get('rtl_fixed', 0)

                if not nb_folders:
                    self.log_update.emit("No notebook folders found, skipping embed")

            # ===== COMPLETE =====
            self.stage_update.emit("Complete!", 100)
            self.log_update.emit("\n" + "=" * 50)
            self.log_update.emit("✅ PIPELINE COMPLETE!")
            self.log_update.emit("=" * 50)
            self.log_update.emit(f"  Scanned: {results['scanned']} media files")
            self.log_update.emit(f"  Downloaded: {results['downloaded']} files")
            self.log_update.emit(f"  Transcribed: {results['transcribed']} files")
            self.log_update.emit(f"  RTL Fixed: {results['rtl_fixed']} lines")
            self.log_update.emit(f"  Embedded: {results['embedded']} videos")

            if results['errors']:
                self.log_update.emit(f"  Errors: {len(results['errors'])}")

        except Exception as e:
            self.log_update.emit(f"\n❌ Pipeline error: {e}")
            results['errors'].append(("Pipeline", str(e)))

        self.pipeline_complete.emit(results)


# ========== MAIN TAB ==========

class PipelineTab(QWidget):
    """Automated pipeline tab - minimal clicks!"""

    def __init__(self):
        super().__init__()
        self.settings = QSettings('HebrewTranscriber', 'Pipeline')

        # State
        self.downloader = None
        self.notebooks = []
        self.output_folder = None

        # Workers
        self.auth_worker = None
        self.list_worker = None
        self.pipeline_worker = None

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === LEFT: Controls ===
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setMinimumWidth(480)
        left_scroll.setMaximumWidth(550)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(12)

        # Title
        title = QLabel("⚡ Automated Pipeline")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #4CAF50;")
        left_layout.addWidget(title)

        subtitle = QLabel("2 clicks: Login → START")
        subtitle.setStyleSheet("color: #666; font-size: 13px; margin-bottom: 5px;")
        left_layout.addWidget(subtitle)

        # ===== STEP 0: Output Folder (FIRST!) =====
        folder_group = QGroupBox("📁 Output Folder")
        folder_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        folder_layout = QHBoxLayout(folder_group)

        self.output_label = QLabel("Select folder first!")
        self.output_label.setStyleSheet("color: #666;")
        folder_layout.addWidget(self.output_label, 1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_output)
        folder_layout.addWidget(self.browse_btn)

        left_layout.addWidget(folder_group)

        # ===== STEP 1: Login =====
        login_group = QGroupBox("1️⃣ NotebookLM Login")
        login_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        login_layout = QVBoxLayout(login_group)

        self.login_btn = QPushButton("🌐 Launch Chrome & Login")
        self.login_btn.setStyleSheet("padding: 12px; font-size: 14px;")
        self.login_btn.clicked.connect(self.on_login)
        login_layout.addWidget(self.login_btn)

        self.login_status = QLabel("")
        login_layout.addWidget(self.login_status)

        left_layout.addWidget(login_group)

        # ===== STEP 2: Select Notebooks =====
        select_group = QGroupBox("2️⃣ Select Notebooks")
        select_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        select_layout = QVBoxLayout(select_group)

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
        select_layout.addLayout(btn_row)

        self.notebook_list = QListWidget()
        self.notebook_list.setMinimumHeight(350)
        self.notebook_list.setStyleSheet("""
            QListWidget {
                font-size: 13px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 6px 4px;
                border-bottom: 1px solid #eee;
            }
        """)
        select_layout.addWidget(self.notebook_list)

        self.notebook_count = QLabel("Login to see notebooks")
        self.notebook_count.setStyleSheet("color: #666;")
        select_layout.addWidget(self.notebook_count)

        left_layout.addWidget(select_group)

        # ===== OPTIONS =====
        options_group = QGroupBox("⚙️ Options")
        options_group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        options_layout = QVBoxLayout(options_group)

        self.download_cb = QCheckBox("Download videos")
        self.download_cb.setChecked(True)
        options_layout.addWidget(self.download_cb)

        self.transcribe_cb = QCheckBox("Transcribe to Hebrew SRT")
        self.transcribe_cb.setChecked(True)
        options_layout.addWidget(self.transcribe_cb)

        self.embed_cb = QCheckBox("RTL Fix + Embed subtitles")
        self.embed_cb.setChecked(True)
        if not is_mkvmerge_available():
            self.embed_cb.setChecked(False)
            self.embed_cb.setEnabled(False)
            self.embed_cb.setText("RTL Fix + Embed (MKVToolNix not found)")
        options_layout.addWidget(self.embed_cb)

        left_layout.addWidget(options_group)

        # ===== START BUTTON =====
        self.start_btn = QPushButton("▶️  START PIPELINE")
        self.start_btn.setStyleSheet("""
            QPushButton {
                padding: 18px;
                font-size: 18px;
                font-weight: bold;
                background-color: #4CAF50;
                color: white;
                border-radius: 10px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; color: #666; }
        """)
        self.start_btn.clicked.connect(self.on_start_pipeline)
        self.start_btn.setEnabled(False)
        left_layout.addWidget(self.start_btn)

        # Cancel
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.cancel_btn.setEnabled(False)
        left_layout.addWidget(self.cancel_btn)

        # Progress
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.stage_label = QLabel("Ready")
        self.stage_label.setStyleSheet("font-size: 13px;")
        progress_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        progress_layout.addWidget(self.progress_bar)

        left_layout.addWidget(progress_group)

        left_layout.addStretch()
        left_scroll.setWidget(left_widget)

        # === RIGHT: Log ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        log_title = QLabel("Pipeline Log")
        log_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        right_layout.addWidget(log_title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        right_layout.addWidget(self.log_text)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_widget)
        splitter.setSizes([480, 520])

        main_layout.addWidget(splitter)

    def load_settings(self):
        self.output_folder = self.settings.value('output_folder', '')
        if self.output_folder:
            self.output_label.setText(self.output_folder)
            self.output_label.setStyleSheet("color: #333;")

    def save_settings(self):
        if self.output_folder:
            self.settings.setValue('output_folder', self.output_folder)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_label.setText(folder)
            self.output_label.setStyleSheet("color: #333;")
            self.save_settings()
            self.update_start_button()

    def update_start_button(self):
        """Enable START only when we have: output folder + logged in + notebooks selected"""
        has_folder = bool(self.output_folder)
        has_login = self.downloader is not None
        has_selection = any(
            self.notebook_list.item(i).checkState() == Qt.CheckState.Checked
            for i in range(self.notebook_list.count())
        ) if self.notebook_list.count() > 0 else False

        self.start_btn.setEnabled(has_folder and has_login and has_selection)

    # ========== LOGIN ==========
    def on_login(self):
        self.login_btn.setEnabled(False)
        self.login_status.setText("Starting Chrome...")
        self.log_text.clear()
        self.log("🌐 Launching Chrome for NotebookLM login...")

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
            self.log("✓ Login successful!")
            self.list_notebooks()
        else:
            self.login_status.setText("✗ Failed")
            self.login_status.setStyleSheet("color: red;")
            self.log("✗ Login failed")

    # ========== LIST NOTEBOOKS ==========
    def list_notebooks(self):
        if not self.downloader:
            return

        self.refresh_btn.setEnabled(False)
        self.notebook_list.clear()
        self.notebook_count.setText("Loading...")

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

        self.notebook_count.setText(f"{len(notebooks)} notebooks found")
        self.log(f"📓 Found {len(notebooks)} notebooks")

        # Connect selection change to update start button
        self.notebook_list.itemChanged.connect(self.update_start_button)
        self.update_start_button()

    def select_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.update_start_button()

    def deselect_all(self):
        for i in range(self.notebook_list.count()):
            self.notebook_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.update_start_button()

    def on_refresh(self):
        self.list_notebooks()

    # ========== START PIPELINE ==========
    def on_start_pipeline(self):
        # Get selected notebooks
        selected = []
        for i in range(self.notebook_list.count()):
            item = self.notebook_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))

        if not selected:
            QMessageBox.warning(self, "Error", "Please select at least one notebook")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Error", "Please select output folder")
            return

        # Disable UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.login_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self.log("\n" + "🚀" * 20)
        self.log("STARTING AUTOMATED PIPELINE")
        self.log("🚀" * 20)
        self.log(f"Notebooks: {len(selected)}")
        self.log(f"Output: {self.output_folder}")

        # Start pipeline worker
        self.pipeline_worker = FullPipelineWorker(
            downloader=self.downloader,
            notebooks=selected,
            output_folder=self.output_folder,
            do_download=self.download_cb.isChecked(),
            do_transcribe=self.transcribe_cb.isChecked(),
            do_embed=self.embed_cb.isChecked()
        )
        self.pipeline_worker.log_update.connect(self.log)
        self.pipeline_worker.stage_update.connect(self.on_stage_update)
        self.pipeline_worker.pipeline_complete.connect(self.on_pipeline_complete)
        self.pipeline_worker.start()

    def on_stage_update(self, stage: str, progress: int):
        self.stage_label.setText(stage)
        self.progress_bar.setValue(progress)

    def on_pipeline_complete(self, results: dict):
        # Re-enable UI
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.login_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.stage_label.setText("Complete!")
        self.progress_bar.setValue(100)

        embedded = results.get('embedded', 0)
        transcribed = results.get('transcribed', 0)
        downloaded = results.get('downloaded', 0)

        # Show completion message
        msg = f"Pipeline Complete!\n\n"
        msg += f"Downloaded: {downloaded}\n"
        msg += f"Transcribed: {transcribed}\n"
        msg += f"Embedded: {embedded}"

        QMessageBox.information(self, "Complete", msg)

        # Open output folder
        if embedded > 0:
            embed_folder = Path(self.output_folder) / "Embedded_Videos"
            if embed_folder.exists():
                os.startfile(str(embed_folder))
        elif self.output_folder:
            os.startfile(str(self.output_folder))

    def on_cancel(self):
        if self.pipeline_worker:
            self.pipeline_worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.log("\n⚠️ Cancelling pipeline...")
