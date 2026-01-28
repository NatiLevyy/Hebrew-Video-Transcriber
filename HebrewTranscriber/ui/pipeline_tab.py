"""
Unified Pipeline Tab - Complete workflow: Download → Transcribe → Embed

This tab provides a unified interface for the complete video processing pipeline:
1. Download videos from NotebookLM
2. Transcribe to Hebrew subtitles (SRT)
3. Fix RTL and embed subtitles into videos
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QGroupBox,
    QFileDialog, QMessageBox, QCheckBox, QListWidget,
    QListWidgetItem, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from pathlib import Path
import os

from core.transcriber import HebrewTranscriber
from core.audio_extractor import AudioExtractor
from core.exporter import SRTExporter
from core.subtitle_embedder import embed_subtitles, is_mkvmerge_available, VIDEO_FORMATS


class PipelineWorker(QThread):
    """Worker thread for the complete pipeline."""
    log_update = pyqtSignal(str)
    progress_update = pyqtSignal(int, int, str)  # current, total, stage
    stage_complete = pyqtSignal(str, dict)  # stage_name, result
    pipeline_complete = pyqtSignal(dict)

    def __init__(self, video_files, output_folder, do_transcribe, do_embed):
        super().__init__()
        self.video_files = video_files
        self.output_folder = Path(output_folder)
        self.do_transcribe = do_transcribe
        self.do_embed = do_embed
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        results = {
            'transcribed': [],
            'embedded': [],
            'failed': [],
            'srt_folder': None,
            'output_folder': None
        }

        total_files = len(self.video_files)
        if total_files == 0:
            self.log_update.emit("No video files to process")
            self.pipeline_complete.emit(results)
            return

        # Create output folders
        self.output_folder.mkdir(parents=True, exist_ok=True)
        srt_folder = self.output_folder / "Subtitle_HEBREW"
        srt_folder.mkdir(exist_ok=True)
        embedded_folder = self.output_folder / "Embedded_Videos"

        results['srt_folder'] = srt_folder
        results['output_folder'] = embedded_folder

        # Stage 1: Transcription
        if self.do_transcribe:
            self.log_update.emit("\n" + "=" * 50)
            self.log_update.emit("STAGE 1: TRANSCRIPTION")
            self.log_update.emit("=" * 50)

            transcriber = HebrewTranscriber()
            extractor = AudioExtractor()

            self.log_update.emit("Loading transcription model...")
            try:
                transcriber.load_model()
                self.log_update.emit(f"Model loaded on {transcriber.device.upper()}")
            except Exception as e:
                self.log_update.emit(f"ERROR loading model: {e}")
                self.pipeline_complete.emit(results)
                return

            for i, video_path in enumerate(self.video_files):
                if self._cancelled:
                    self.log_update.emit("Cancelled by user")
                    break

                video_path = Path(video_path)
                filename = video_path.name
                self.progress_update.emit(i + 1, total_files, "Transcribing")
                self.log_update.emit(f"\n[{i+1}/{total_files}] {filename}")

                try:
                    # Extract audio
                    self.log_update.emit(f"  Extracting audio...")
                    audio_path = extractor.extract(str(video_path))

                    # Transcribe
                    self.log_update.emit(f"  Transcribing...")
                    segments = transcriber.transcribe(audio_path)

                    # Cleanup temp audio
                    Path(audio_path).unlink(missing_ok=True)

                    # Save SRT
                    srt_path = srt_folder / f"{video_path.stem}.srt"
                    SRTExporter().export(segments, str(srt_path), video_path.stem)

                    results['transcribed'].append(video_path.name)
                    self.log_update.emit(f"  ✓ Saved: {srt_path.name}")

                except Exception as e:
                    results['failed'].append((filename, f"Transcription: {str(e)}"))
                    self.log_update.emit(f"  ✗ Error: {e}")

            self.stage_complete.emit("transcription", {
                'transcribed': len(results['transcribed']),
                'failed': len([f for f in results['failed'] if 'Transcription' in f[1]])
            })

        # Stage 2: Embedding (with RTL fix)
        if self.do_embed and not self._cancelled:
            self.log_update.emit("\n" + "=" * 50)
            self.log_update.emit("STAGE 2: RTL FIX + EMBEDDING")
            self.log_update.emit("=" * 50)

            if not is_mkvmerge_available():
                self.log_update.emit("ERROR: MKVToolNix not installed!")
                self.log_update.emit("Please install from: https://mkvtoolnix.download/")
            else:
                # Get video folder (parent of first video, or output folder)
                video_folder = self.video_files[0].parent if self.video_files else self.output_folder

                embed_result = embed_subtitles(
                    video_folder=video_folder,
                    srt_folder=srt_folder,
                    output_folder=embedded_folder,
                    log=self.log_update.emit,
                    progress=lambda c, t: self.progress_update.emit(c, t, "Embedding"),
                    skip_existing=True,
                    fix_rtl=True
                )

                results['embedded'] = embed_result.get('embedded', [])
                for fail in embed_result.get('failed', []):
                    results['failed'].append(fail)

                self.stage_complete.emit("embedding", {
                    'embedded': len(results['embedded']),
                    'rtl_fixed': embed_result.get('rtl_fixed', 0)
                })

        self.pipeline_complete.emit(results)


class PipelineTab(QWidget):
    """Unified pipeline tab for complete workflow."""

    def __init__(self):
        super().__init__()
        self.settings = QSettings('HebrewTranscriber', 'Pipeline')
        self.video_files = []
        self.worker = None
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

        # Title
        title = QLabel("Complete Pipeline")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #4CAF50;")
        left_layout.addWidget(title)

        subtitle = QLabel("Download → Transcribe → Embed (All in One)")
        subtitle.setStyleSheet("color: #666; margin-bottom: 10px;")
        left_layout.addWidget(subtitle)

        # Video Files Group
        files_group = QGroupBox("1. Video Files")
        files_layout = QVBoxLayout(files_group)

        btn_layout = QHBoxLayout()
        self.add_files_btn = QPushButton("Add Videos")
        self.add_files_btn.clicked.connect(self.add_video_files)
        self.add_folder_btn = QPushButton("Add Folder")
        self.add_folder_btn.clicked.connect(self.add_video_folder)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_files)
        btn_layout.addWidget(self.add_files_btn)
        btn_layout.addWidget(self.add_folder_btn)
        btn_layout.addWidget(self.clear_btn)
        files_layout.addLayout(btn_layout)

        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(150)
        files_layout.addWidget(self.file_list)

        self.file_count_label = QLabel("0 files selected")
        files_layout.addWidget(self.file_count_label)

        left_layout.addWidget(files_group)

        # Output Group
        output_group = QGroupBox("2. Output Folder")
        output_layout = QHBoxLayout(output_group)

        self.output_path_label = QLabel("Not selected")
        self.output_path_label.setObjectName("pathLabel")
        output_layout.addWidget(self.output_path_label, 1)

        self.output_browse_btn = QPushButton("...")
        self.output_browse_btn.setMaximumWidth(30)
        self.output_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_browse_btn)

        left_layout.addWidget(output_group)

        # Options Group
        options_group = QGroupBox("3. Pipeline Steps")
        options_layout = QVBoxLayout(options_group)

        self.transcribe_cb = QCheckBox("Transcribe videos to Hebrew SRT")
        self.transcribe_cb.setChecked(True)
        options_layout.addWidget(self.transcribe_cb)

        self.embed_cb = QCheckBox("Fix RTL + Embed subtitles into videos")
        self.embed_cb.setChecked(True)
        options_layout.addWidget(self.embed_cb)

        # MKVToolNix status
        self.mkvmerge_status = QLabel()
        if is_mkvmerge_available():
            self.mkvmerge_status.setText("✓ MKVToolNix found")
            self.mkvmerge_status.setStyleSheet("color: green; font-size: 11px;")
        else:
            self.mkvmerge_status.setText("⚠ MKVToolNix not found (embedding disabled)")
            self.mkvmerge_status.setStyleSheet("color: orange; font-size: 11px;")
            self.embed_cb.setChecked(False)
            self.embed_cb.setEnabled(False)
        options_layout.addWidget(self.mkvmerge_status)

        left_layout.addWidget(options_group)

        # Progress
        progress_group = QGroupBox("4. Progress")
        progress_layout = QVBoxLayout(progress_group)

        self.stage_label = QLabel("Ready")
        self.stage_label.setStyleSheet("font-weight: bold;")
        progress_layout.addWidget(self.stage_label)

        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)

        left_layout.addWidget(progress_group)

        # Action Buttons
        btn_layout2 = QHBoxLayout()

        self.start_btn = QPushButton("▶ Start Pipeline")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setStyleSheet("""
            QPushButton#startBtn {
                background-color: #4CAF50;
                color: white;
                padding: 15px;
                font-size: 16px;
                font-weight: bold;
                border-radius: 6px;
            }
            QPushButton#startBtn:hover {
                background-color: #45a049;
            }
            QPushButton#startBtn:disabled {
                background-color: #cccccc;
            }
        """)
        self.start_btn.clicked.connect(self.start_pipeline)
        btn_layout2.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_pipeline)
        btn_layout2.addWidget(self.cancel_btn)

        left_layout.addLayout(btn_layout2)
        left_layout.addStretch()

        # === RIGHT SIDE - Log ===
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        log_label = QLabel("Pipeline Log:")
        right_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        right_layout.addWidget(self.log_text)

        # Add to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([450, 550])

        main_layout.addWidget(splitter)

    def load_settings(self):
        self.output_folder = self.settings.value('output_folder', '')
        if self.output_folder:
            self.output_path_label.setText(self.output_folder)

    def save_settings(self):
        self.settings.setValue('output_folder', self.output_folder)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def add_video_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Video Files",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm *.m4v *.wmv)"
        )
        for f in files:
            if f not in [str(v) for v in self.video_files]:
                self.video_files.append(Path(f))
                self.file_list.addItem(Path(f).name)
        self.update_file_count()

    def add_video_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Video Folder")
        if folder:
            folder_path = Path(folder)
            for f in folder_path.iterdir():
                if f.is_file() and f.suffix.lower() in VIDEO_FORMATS:
                    if f not in self.video_files:
                        self.video_files.append(f)
                        self.file_list.addItem(f.name)
            self.update_file_count()

            # Auto-set output folder
            if not self.output_folder:
                self.output_folder = folder
                self.output_path_label.setText(folder)
                self.save_settings()

    def clear_files(self):
        self.video_files = []
        self.file_list.clear()
        self.update_file_count()

    def update_file_count(self):
        count = len(self.video_files)
        self.file_count_label.setText(f"{count} file{'s' if count != 1 else ''} selected")

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_path_label.setText(folder)
            self.save_settings()

    def start_pipeline(self):
        # Validation
        if not self.video_files:
            QMessageBox.warning(self, "Error", "Please add video files first")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Error", "Please select an output folder")
            return

        if not self.transcribe_cb.isChecked() and not self.embed_cb.isChecked():
            QMessageBox.warning(self, "Error", "Please select at least one pipeline step")
            return

        # Clear log and start
        self.log_text.clear()
        self.log("=" * 50)
        self.log("STARTING PIPELINE")
        self.log("=" * 50)
        self.log(f"Videos: {len(self.video_files)}")
        self.log(f"Output: {self.output_folder}")
        self.log(f"Transcribe: {'Yes' if self.transcribe_cb.isChecked() else 'No'}")
        self.log(f"Embed: {'Yes' if self.embed_cb.isChecked() else 'No'}")

        # Disable UI
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.add_files_btn.setEnabled(False)
        self.add_folder_btn.setEnabled(False)

        # Start worker
        self.worker = PipelineWorker(
            video_files=self.video_files.copy(),
            output_folder=self.output_folder,
            do_transcribe=self.transcribe_cb.isChecked(),
            do_embed=self.embed_cb.isChecked()
        )
        self.worker.log_update.connect(self.log)
        self.worker.progress_update.connect(self.on_progress)
        self.worker.stage_complete.connect(self.on_stage_complete)
        self.worker.pipeline_complete.connect(self.on_complete)
        self.worker.start()

    def cancel_pipeline(self):
        if self.worker:
            self.worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.log("Cancelling...")

    def on_progress(self, current: int, total: int, stage: str):
        self.stage_label.setText(f"{stage}: {current}/{total}")
        if total > 0:
            self.progress_bar.setValue(int((current / total) * 100))

    def on_stage_complete(self, stage: str, result: dict):
        self.log(f"\n✓ {stage.upper()} complete: {result}")

    def on_complete(self, results: dict):
        # Re-enable UI
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.add_files_btn.setEnabled(True)
        self.add_folder_btn.setEnabled(True)
        self.stage_label.setText("Complete!")
        self.progress_bar.setValue(100)

        # Summary
        self.log("\n" + "=" * 50)
        self.log("PIPELINE COMPLETE")
        self.log("=" * 50)
        self.log(f"Transcribed: {len(results.get('transcribed', []))}")
        self.log(f"Embedded: {len(results.get('embedded', []))}")
        self.log(f"Failed: {len(results.get('failed', []))}")

        if results.get('failed'):
            self.log("\nFailed files:")
            for name, error in results['failed']:
                self.log(f"  - {name}: {error}")

        # Show completion message
        transcribed = len(results.get('transcribed', []))
        embedded = len(results.get('embedded', []))

        if transcribed > 0 or embedded > 0:
            msg = f"Pipeline complete!\n\nTranscribed: {transcribed}\nEmbedded: {embedded}"
            QMessageBox.information(self, "Complete", msg)

            # Open output folder
            output = results.get('output_folder')
            if output and Path(output).exists():
                os.startfile(str(output))
            elif self.output_folder:
                os.startfile(str(self.output_folder))
        else:
            QMessageBox.warning(self, "Complete", "Pipeline finished but no files were processed.")
