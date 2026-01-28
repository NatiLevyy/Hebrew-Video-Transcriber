from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QTextEdit,
    QFileDialog, QRadioButton, QButtonGroup, QMessageBox,
    QListWidget, QListWidgetItem, QTabWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from pathlib import Path
import os

from core.transcriber import HebrewTranscriber
from core.audio_extractor import AudioExtractor
from core.exporter import MarkdownExporter, PDFExporter, SRTExporter
from utils.config import Config


class BatchTranscriptionWorker(QThread):
    """Worker thread for batch transcription."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    file_completed = pyqtSignal(str, list)  # filename, segments
    all_finished = pyqtSignal()
    error = pyqtSignal(str, str)  # filename, error message

    def __init__(self, video_paths: list):
        super().__init__()
        self.video_paths = video_paths
        self.transcriber = HebrewTranscriber()
        self.extractor = AudioExtractor()

    def run(self):
        try:
            # Load model once for all files
            self.status.emit("טוען מודל תמלול...")
            self.transcriber.load_model()

            total_files = len(self.video_paths)

            for idx, video_path in enumerate(self.video_paths):
                filename = Path(video_path).name
                try:
                    # Extract audio
                    self.status.emit(f"[{idx+1}/{total_files}] מחלץ אודיו: {filename}")
                    audio_path = self.extractor.extract(video_path)

                    # Transcribe
                    self.status.emit(f"[{idx+1}/{total_files}] מתמלל: {filename}")
                    segments = self.transcriber.transcribe(
                        audio_path,
                        progress_callback=lambda p: self.progress.emit(int(p))
                    )

                    # Cleanup temp audio
                    Path(audio_path).unlink(missing_ok=True)

                    self.file_completed.emit(video_path, segments)

                except Exception as e:
                    self.error.emit(filename, str(e))

            self.all_finished.emit()

        except Exception as e:
            self.error.emit("כללי", str(e))


class DropZone(QLabel):
    """Drag & drop zone for video files."""

    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setText("גרור קבצי וידאו לכאן\nאו לחץ לבחירה")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("dropZone")
        self.setMinimumHeight(120)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("dragOver", True)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setProperty("dragOver", False)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragOver", False)
        self.style().polish(self)

        valid_files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if Path(file_path).suffix.lower() in AudioExtractor.SUPPORTED_FORMATS:
                valid_files.append(file_path)

        if valid_files:
            self.files_dropped.emit(valid_files)
        else:
            QMessageBox.warning(self, "שגיאה", "לא נמצאו קבצי וידאו תקינים")

    def mousePressEvent(self, event):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "בחר קבצי וידאו",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.wav *.mp3)"
        )
        if file_paths:
            self.files_dropped.emit(file_paths)


class TranscriptionTab(QWidget):
    """Tab widget for transcription functionality."""

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.file_list = []
        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.on_files_selected)
        layout.addWidget(self.drop_zone)

        # File list
        self.file_list_widget = QListWidget()
        self.file_list_widget.setMaximumHeight(100)
        self.file_list_widget.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout.addWidget(self.file_list_widget)

        # Clear list button
        clear_btn = QPushButton("נקה רשימה")
        clear_btn.clicked.connect(self.clear_file_list)
        layout.addWidget(clear_btn)

        # Output directory
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("תיקיית יעד:"))
        self.dir_label = QLabel(self.config.last_output_dir or "לא נבחרה")
        self.dir_label.setObjectName("pathLabel")
        dir_layout.addWidget(self.dir_label, 1)

        browse_btn = QPushButton("בחר...")
        browse_btn.clicked.connect(self.browse_output_dir)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)

        # Format selection
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("פורמט:"))

        self.format_group = QButtonGroup()
        self.md_radio = QRadioButton("Markdown")
        self.pdf_radio = QRadioButton("PDF")
        self.both_radio = QRadioButton("שניהם")

        self.format_group.addButton(self.md_radio, 1)
        self.format_group.addButton(self.pdf_radio, 2)
        self.format_group.addButton(self.both_radio, 3)

        # Load saved preference
        saved_format = self.config.output_format
        if saved_format == "pdf":
            self.pdf_radio.setChecked(True)
        elif saved_format == "both":
            self.both_radio.setChecked(True)
        else:
            self.md_radio.setChecked(True)

        format_layout.addWidget(self.md_radio)
        format_layout.addWidget(self.pdf_radio)
        format_layout.addWidget(self.both_radio)
        format_layout.addStretch()
        layout.addLayout(format_layout)

        # SRT info label
        srt_label = QLabel("קבצי SRT יישמרו אוטומטית בתיקיית Subtitle_HEBREW")
        srt_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(srt_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Transcribe button
        self.transcribe_btn = QPushButton("תמלל")
        self.transcribe_btn.setObjectName("transcribeBtn")
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self.start_transcription)
        layout.addWidget(self.transcribe_btn)

        # Log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setPlaceholderText("לוג פעילות...")
        layout.addWidget(self.log)

    def log_message(self, message: str):
        self.log.append(message)

    def browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "בחר תיקיית יעד",
            self.config.last_output_dir
        )
        if dir_path:
            self.config.last_output_dir = dir_path
            self.dir_label.setText(dir_path)

    def on_files_selected(self, file_paths: list):
        for fp in file_paths:
            if fp not in self.file_list:
                self.file_list.append(fp)
                item = QListWidgetItem(Path(fp).name)
                self.file_list_widget.addItem(item)

        self.drop_zone.setText(f"נבחרו {len(self.file_list)} קבצים")
        self.transcribe_btn.setEnabled(len(self.file_list) > 0)
        self.log_message(f"נוספו {len(file_paths)} קבצים לרשימה")

    def clear_file_list(self):
        self.file_list = []
        self.file_list_widget.clear()
        self.drop_zone.setText("גרור קבצי וידאו לכאן\nאו לחץ לבחירה")
        self.transcribe_btn.setEnabled(False)

    def start_transcription(self):
        if not self.file_list:
            return

        output_dir = self.config.last_output_dir
        if not output_dir:
            QMessageBox.warning(self, "שגיאה", "נא לבחור תיקיית יעד")
            return

        # Save format preference
        if self.pdf_radio.isChecked():
            self.config.output_format = "pdf"
        elif self.both_radio.isChecked():
            self.config.output_format = "both"
        else:
            self.config.output_format = "md"

        # Disable UI during transcription
        self.transcribe_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        # Start worker thread
        self.worker = BatchTranscriptionWorker(self.file_list.copy())
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.log_message)
        self.worker.file_completed.connect(self.on_file_completed)
        self.worker.all_finished.connect(self.on_all_finished)
        self.worker.error.connect(self.on_transcription_error)
        self.worker.start()

    def on_file_completed(self, video_path: str, segments: list):
        output_dir = Path(self.config.last_output_dir)
        title = Path(video_path).stem

        # Create Subtitle_HEBREW folder for SRT files
        srt_folder = output_dir / "Subtitle_HEBREW"
        srt_folder.mkdir(exist_ok=True)

        # Always export SRT to Subtitle_HEBREW folder
        srt_path = srt_folder / f"{title}.srt"
        SRTExporter().export(segments, str(srt_path), title)
        self.log_message(f"SRT נשמר: {srt_path}")

        # Export MD/PDF based on selection
        if self.md_radio.isChecked() or self.both_radio.isChecked():
            md_path = output_dir / f"{title}.md"
            MarkdownExporter().export(segments, str(md_path), title)
            self.log_message(f"MD נשמר: {md_path}")

        if self.pdf_radio.isChecked() or self.both_radio.isChecked():
            pdf_path = output_dir / f"{title}.pdf"
            PDFExporter().export(segments, str(pdf_path), title)
            self.log_message(f"PDF נשמר: {pdf_path}")

    def on_all_finished(self):
        # Reset UI
        self.progress_bar.setVisible(False)
        self.transcribe_btn.setEnabled(True)
        self.log_message("כל התמלולים הושלמו בהצלחה!")

        # Open output folder
        os.startfile(str(self.config.last_output_dir))

    def on_transcription_error(self, filename: str, error: str):
        self.log_message(f"שגיאה ב-{filename}: {error}")
        if filename == "כללי":
            self.progress_bar.setVisible(False)
            self.transcribe_btn.setEnabled(True)
            QMessageBox.critical(self, "שגיאה", error)


class MainWindow(QMainWindow):
    """Main application window with tabs."""

    def __init__(self):
        super().__init__()
        self.config = Config()

        self.setup_ui()
        self.setWindowTitle("מתמלל עברית - Hebrew Transcriber v1.0.2")
        self.setMinimumSize(1050, 750)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)  # Tabs LTR

        # Transcription tab
        self.transcription_tab = TranscriptionTab(self.config)
        self.tab_widget.addTab(self.transcription_tab, "Transcription / תמלול")

        # NotebookLM tab
        from ui.notebooklm_tab import NotebookLMTab
        self.notebooklm_tab = NotebookLMTab()
        self.tab_widget.addTab(self.notebooklm_tab, "NotebookLM")

        layout.addWidget(self.tab_widget)
