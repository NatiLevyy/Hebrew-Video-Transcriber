"""
MP4 Conversion Tab - Convert videos to MP4 with hard-burned Hebrew subtitles.

Standalone tab for converting video files + SRT subtitles into
WhatsApp-compatible MP4 files with permanently burned-in subtitles.
Uses FFmpeg with automatic GPU acceleration detection.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path
import os

from core.mp4_converter import convert_to_mp4, is_ffmpeg_available


class MP4ConvertWorker(QThread):
    """Worker thread for MP4 conversion."""
    progress_update = pyqtSignal(int, int)  # current, total
    log_update = pyqtSignal(str)
    convert_complete = pyqtSignal(dict)

    def __init__(self, video_folder, srt_folder, output_folder, skip_existing):
        super().__init__()
        self.video_folder = video_folder
        self.srt_folder = srt_folder
        self.output_folder = output_folder
        self.skip_existing = skip_existing

    def run(self):
        result = convert_to_mp4(
            video_folder=self.video_folder,
            srt_folder=self.srt_folder,
            output_folder=self.output_folder,
            log=self.log_update.emit,
            progress=self.progress_update.emit,
            skip_existing=self.skip_existing,
            fix_rtl=True
        )
        self.convert_complete.emit(result)


class MP4Tab(QWidget):
    """Tab widget for standalone MP4 conversion with hard-burned subtitles."""

    def __init__(self):
        super().__init__()
        self.settings = QSettings('HebrewTranscriber', 'MP4Convert')
        self.worker = None
        self.init_ui()
        self.load_settings()
        self.check_ffmpeg()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Info box
        info_group = QGroupBox("About MP4 Conversion")
        info_layout = QVBoxLayout(info_group)

        info_text = QLabel(
            "Convert videos to MP4 with hard-burned Hebrew subtitles.\n"
            "• Subtitles are permanently burned into the video (cannot be toggled off)\n"
            "• Output is MP4 — compatible with WhatsApp, Telegram, etc.\n"
            "• Automatically uses GPU acceleration if available (NVIDIA/Intel/AMD)\n"
            "• Requires FFmpeg installed and in PATH"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)

        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setStyleSheet("font-weight: bold;")
        info_layout.addWidget(self.ffmpeg_status)

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

        self.skip_existing_cb = QCheckBox("Skip videos that already have output MP4")
        self.skip_existing_cb.setChecked(True)
        options_layout.addWidget(self.skip_existing_cb)

        layout.addWidget(options_group)

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Convert button
        self.convert_btn = QPushButton("Convert to MP4")
        self.convert_btn.setObjectName("convertBtn")
        self.convert_btn.setStyleSheet("""
            QPushButton#convertBtn {
                background-color: #2196F3;
                color: white;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton#convertBtn:hover {
                background-color: #1976D2;
            }
            QPushButton#convertBtn:disabled {
                background-color: #cccccc;
            }
        """)
        self.convert_btn.clicked.connect(self.start_conversion)
        layout.addWidget(self.convert_btn)

        # Log area
        log_label = QLabel("Log:")
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        self.log_text.setMinimumHeight(200)
        layout.addWidget(self.log_text)

        layout.addStretch()

    def check_ffmpeg(self):
        """Check if FFmpeg is installed."""
        if is_ffmpeg_available():
            self.ffmpeg_status.setText("✓ FFmpeg found")
            self.ffmpeg_status.setStyleSheet("color: green; font-weight: bold;")
            self.convert_btn.setEnabled(True)
        else:
            self.ffmpeg_status.setText("✗ FFmpeg NOT found - Please install it first!")
            self.ffmpeg_status.setStyleSheet("color: red; font-weight: bold;")
            self.convert_btn.setEnabled(False)

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
        transcription_settings = QSettings('HebrewTranscriber', 'Config')
        last_output = transcription_settings.value('last_output_dir', '')

        if not last_output or not Path(last_output).exists():
            notebooklm_settings = QSettings('HebrewTranscriber', 'NotebookLM')
            last_output = notebooklm_settings.value('output_path', '')

        if last_output and Path(last_output).exists():
            output_path = Path(last_output)

            srt_path = output_path / "Subtitle_HEBREW"
            if srt_path.exists():
                self.srt_folder = str(srt_path)
                self.srt_path_label.setText(str(srt_path))

            self.video_folder = str(output_path)
            self.video_path_label.setText(str(output_path))

            mp4_path = output_path / "WhatsApp_Videos"
            self.output_folder = str(mp4_path)
            self.output_path_label.setText(str(mp4_path))

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

    def start_conversion(self):
        """Start the MP4 conversion process."""
        if not self.video_folder or not Path(self.video_folder).exists():
            QMessageBox.warning(self, "Error", "Please select a valid video folder")
            return

        if not self.srt_folder or not Path(self.srt_folder).exists():
            QMessageBox.warning(self, "Error", "Please select a valid SRT folder")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Error", "Please select an output folder")
            return

        self.log_text.clear()

        self.convert_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = MP4ConvertWorker(
            video_folder=Path(self.video_folder),
            srt_folder=Path(self.srt_folder),
            output_folder=Path(self.output_folder),
            skip_existing=self.skip_existing_cb.isChecked()
        )
        self.worker.progress_update.connect(self.on_progress)
        self.worker.log_update.connect(self.log)
        self.worker.convert_complete.connect(self.on_complete)
        self.worker.start()

    def on_progress(self, current: int, total: int):
        """Update progress bar."""
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)

    def on_complete(self, result: dict):
        """Handle conversion completion."""
        self.convert_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        converted_count = len(result.get('converted', []))
        failed_count = len(result.get('failed', []))
        encoder = result.get('encoder', 'unknown')

        if converted_count > 0:
            QMessageBox.information(
                self,
                "Complete",
                f"Successfully converted {converted_count} videos to MP4!\n"
                f"Encoder used: {encoder}\n"
                f"Output folder: {result.get('output_folder', '')}"
            )
            output_folder = result.get('output_folder')
            if output_folder and Path(output_folder).exists():
                os.startfile(str(output_folder))
        elif failed_count > 0:
            QMessageBox.warning(
                self,
                "Errors",
                f"Conversion failed for {failed_count} videos.\nCheck the log for details."
            )
        else:
            QMessageBox.information(
                self,
                "Complete",
                "No videos were processed.\nCheck that video and SRT files match."
            )
