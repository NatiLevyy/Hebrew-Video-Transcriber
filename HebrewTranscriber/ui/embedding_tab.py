"""
Subtitle Embedding Tab - Embed Hebrew SRT subtitles into video files.

Uses MKVToolNix to create MKV files with embedded Hebrew subtitles.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path

from core.subtitle_embedder import embed_subtitles, is_mkvmerge_available


class EmbedWorker(QThread):
    """Worker thread for subtitle embedding."""
    progress_update = pyqtSignal(int, int)  # current, total
    log_update = pyqtSignal(str)
    embed_complete = pyqtSignal(dict)

    def __init__(self, video_folder, srt_folder, output_folder, skip_existing):
        super().__init__()
        self.video_folder = video_folder
        self.srt_folder = srt_folder
        self.output_folder = output_folder
        self.skip_existing = skip_existing

    def run(self):
        result = embed_subtitles(
            video_folder=self.video_folder,
            srt_folder=self.srt_folder,
            output_folder=self.output_folder,
            log=self.log_update.emit,
            progress=self.progress_update.emit,
            skip_existing=self.skip_existing
        )
        self.embed_complete.emit(result)


class EmbeddingTab(QWidget):
    """Tab widget for subtitle embedding functionality."""

    def __init__(self):
        super().__init__()
        self.settings = QSettings('HebrewTranscriber', 'Embedding')
        self.worker = None
        self.init_ui()
        self.load_settings()
        self.check_mkvmerge()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Info box
        info_group = QGroupBox("About Subtitle Embedding")
        info_layout = QVBoxLayout(info_group)

        info_text = QLabel(
            "Embed Hebrew SRT subtitles into video files using MKVToolNix.\n"
            "• Requires MKVToolNix installed (free): https://mkvtoolnix.download/\n"
            "• Supports MP4, MKV, AVI, MOV, WebM input formats\n"
            "• Output is always MKV with embedded Hebrew subtitle track"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)

        self.mkvmerge_status = QLabel()
        self.mkvmerge_status.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.mkvmerge_status)

        layout.addWidget(info_group)

        # Folders Group
        folders_group = QGroupBox("Folders")
        folders_layout = QVBoxLayout(folders_group)

        # Video folder
        video_layout = QHBoxLayout()
        video_layout.addWidget(QLabel("Videos:"))
        self.video_path_label = QLabel("Not selected")
        self.video_path_label.setObjectName("pathLabel")
        video_layout.addWidget(self.video_path_label, 1)
        self.video_browse_btn = QPushButton("...")
        self.video_browse_btn.setMaximumWidth(30)
        self.video_browse_btn.clicked.connect(self.browse_video_folder)
        video_layout.addWidget(self.video_browse_btn)
        folders_layout.addLayout(video_layout)

        # SRT folder
        srt_layout = QHBoxLayout()
        srt_layout.addWidget(QLabel("SRT Files:"))
        self.srt_path_label = QLabel("Not selected")
        self.srt_path_label.setObjectName("pathLabel")
        srt_layout.addWidget(self.srt_path_label, 1)
        self.srt_browse_btn = QPushButton("...")
        self.srt_browse_btn.setMaximumWidth(30)
        self.srt_browse_btn.clicked.connect(self.browse_srt_folder)
        srt_layout.addWidget(self.srt_browse_btn)
        folders_layout.addLayout(srt_layout)

        # Output folder
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output:"))
        self.output_path_label = QLabel("Not selected")
        self.output_path_label.setObjectName("pathLabel")
        output_layout.addWidget(self.output_path_label, 1)
        self.output_browse_btn = QPushButton("...")
        self.output_browse_btn.setMaximumWidth(30)
        self.output_browse_btn.clicked.connect(self.browse_output_folder)
        output_layout.addWidget(self.output_browse_btn)
        folders_layout.addLayout(output_layout)

        # Auto-detect button
        self.auto_detect_btn = QPushButton("Auto-detect from Transcription output")
        self.auto_detect_btn.clicked.connect(self.auto_detect_folders)
        folders_layout.addWidget(self.auto_detect_btn)

        layout.addWidget(folders_group)

        # Options Group
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        self.skip_existing_cb = QCheckBox("Skip videos that already have output MKV")
        self.skip_existing_cb.setChecked(True)
        options_layout.addWidget(self.skip_existing_cb)

        layout.addWidget(options_group)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Embed button
        self.embed_btn = QPushButton("Embed Subtitles")
        self.embed_btn.setObjectName("embedBtn")
        self.embed_btn.setStyleSheet("""
            QPushButton#embedBtn {
                background-color: #4CAF50;
                color: white;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton#embedBtn:hover {
                background-color: #45a049;
            }
            QPushButton#embedBtn:disabled {
                background-color: #cccccc;
            }
        """)
        self.embed_btn.clicked.connect(self.start_embedding)
        layout.addWidget(self.embed_btn)

        # Log area
        log_label = QLabel("Log:")
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.log_text.setMinimumHeight(200)
        layout.addWidget(self.log_text)

        layout.addStretch()

    def check_mkvmerge(self):
        """Check if MKVToolNix is installed."""
        if is_mkvmerge_available():
            self.mkvmerge_status.setText("✓ MKVToolNix found")
            self.mkvmerge_status.setStyleSheet("color: green; font-weight: bold;")
            self.embed_btn.setEnabled(True)
        else:
            self.mkvmerge_status.setText("✗ MKVToolNix NOT found - Please install it first!")
            self.mkvmerge_status.setStyleSheet("color: red; font-weight: bold;")
            self.embed_btn.setEnabled(False)

    def load_settings(self):
        """Load saved folder paths."""
        self.video_folder = self.settings.value('video_folder', '')
        self.srt_folder = self.settings.value('srt_folder', '')
        self.output_folder = self.settings.value('output_folder', '')

        if self.video_folder:
            self.video_path_label.setText(self.video_folder)
        if self.srt_folder:
            self.srt_path_label.setText(self.srt_folder)
        if self.output_folder:
            self.output_path_label.setText(self.output_folder)

    def save_settings(self):
        """Save folder paths."""
        self.settings.setValue('video_folder', self.video_folder)
        self.settings.setValue('srt_folder', self.srt_folder)
        self.settings.setValue('output_folder', self.output_folder)

    def browse_video_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Video Folder")
        if folder:
            self.video_folder = folder
            self.video_path_label.setText(folder)
            self.save_settings()

    def browse_srt_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select SRT Folder")
        if folder:
            self.srt_folder = folder
            self.srt_path_label.setText(folder)
            self.save_settings()

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_path_label.setText(folder)
            self.save_settings()

    def auto_detect_folders(self):
        """Try to auto-detect folders from transcription output."""
        # Try to find the last used transcription output folder
        transcription_settings = QSettings('HebrewTranscriber', 'Config')
        last_output = transcription_settings.value('last_output_dir', '')

        if not last_output or not Path(last_output).exists():
            # Try NotebookLM download folder
            notebooklm_settings = QSettings('HebrewTranscriber', 'NotebookLM')
            last_output = notebooklm_settings.value('output_path', '')

        if last_output and Path(last_output).exists():
            output_path = Path(last_output)

            # SRT folder is typically Subtitle_HEBREW inside output
            srt_path = output_path / "Subtitle_HEBREW"

            if srt_path.exists():
                self.srt_folder = str(srt_path)
                self.srt_path_label.setText(str(srt_path))

            # Video folder is the parent (same as output)
            self.video_folder = str(output_path)
            self.video_path_label.setText(str(output_path))

            # Output folder for embedded videos
            embedded_path = output_path / "Embedded_Videos"
            self.output_folder = str(embedded_path)
            self.output_path_label.setText(str(embedded_path))

            self.save_settings()
            self.log("Auto-detected folders from last transcription output")
        else:
            QMessageBox.information(
                self,
                "Auto-detect",
                "Could not find previous transcription output.\nPlease select folders manually."
            )

    def log(self, msg: str):
        """Add message to log."""
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def start_embedding(self):
        """Start the embedding process."""
        # Validate folders
        if not self.video_folder or not Path(self.video_folder).exists():
            QMessageBox.warning(self, "Error", "Please select a valid video folder")
            return

        if not self.srt_folder or not Path(self.srt_folder).exists():
            QMessageBox.warning(self, "Error", "Please select a valid SRT folder")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Error", "Please select an output folder")
            return

        # Clear log
        self.log_text.clear()

        # Disable UI
        self.embed_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Start worker
        self.worker = EmbedWorker(
            video_folder=Path(self.video_folder),
            srt_folder=Path(self.srt_folder),
            output_folder=Path(self.output_folder),
            skip_existing=self.skip_existing_cb.isChecked()
        )
        self.worker.progress_update.connect(self.on_progress)
        self.worker.log_update.connect(self.log)
        self.worker.embed_complete.connect(self.on_complete)
        self.worker.start()

    def on_progress(self, current: int, total: int):
        """Update progress bar."""
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)

    def on_complete(self, result: dict):
        """Handle embedding completion."""
        self.embed_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        embedded_count = len(result.get('embedded', []))
        failed_count = len(result.get('failed', []))

        if embedded_count > 0:
            QMessageBox.information(
                self,
                "Complete",
                f"Successfully embedded {embedded_count} videos!\n"
                f"Output folder: {result.get('output_folder', '')}"
            )
            # Open output folder
            import os
            output_folder = result.get('output_folder')
            if output_folder and Path(output_folder).exists():
                os.startfile(str(output_folder))
        elif failed_count > 0:
            QMessageBox.warning(
                self,
                "Errors",
                f"Embedding failed for {failed_count} videos.\nCheck the log for details."
            )
        else:
            QMessageBox.information(
                self,
                "Complete",
                "No videos were processed.\nCheck that video and SRT files match."
            )
