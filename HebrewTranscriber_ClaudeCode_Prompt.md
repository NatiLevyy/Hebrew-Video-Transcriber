# Hebrew Video Transcriber - Claude Code Project

## IMPORTANT: START IMMEDIATELY
Do NOT ask for permissions or confirmations. Execute this entire project autonomously using the Ralph Loop methodology. Build everything, test it, and only stop when it's fully working.

---

## Project Goal
Build a lightweight, fast Desktop application for transcribing Hebrew videos (primarily NotebookLM outputs) with clean RTL output in MD/PDF formats.

---

## Required Skills - READ FIRST

Before writing any code, read these skill files:

```bash
# Read the skills in this order:
view /mnt/skills/user/project-setup/SKILL.md
view /mnt/skills/user/dev-best-practices/SKILL.md
```

If Ralph Loop files exist, use them. If not, create them according to the project-setup skill.

---

## Ralph Loop Setup

Create the following structure and execute autonomously:

### 1. Create PROMPT_plan.md
```markdown
# Hebrew Transcriber - Planning Phase

## Objective
Build a PyQt6 desktop app for Hebrew video transcription using ivrit-ai/whisper model.

## Success Criteria
- [ ] App launches without errors
- [ ] Drag & drop video files works
- [ ] Transcription completes with progress feedback
- [ ] Output files are valid RTL Hebrew (MD and PDF)
- [ ] Settings persist between sessions

## Architecture Decisions
- GUI: PyQt6 (native look, built-in RTL support)
- Transcription: faster-whisper + ivrit-ai model
- Audio: ffmpeg extraction
- PDF: reportlab with python-bidi for RTL

## Risk Mitigation
- No GPU: Fall back to CPU with int8 quantization
- Large files: Process in chunks, show real progress
- Missing ffmpeg: Check on startup, show install instructions
```

### 2. Create PROMPT_build.md
```markdown
# Hebrew Transcriber - Build Phase

## Implementation Order
1. Core transcription engine (no UI)
2. Audio extraction module
3. Export modules (MD, PDF with RTL)
4. Basic PyQt6 window
5. Drag & drop functionality
6. Progress tracking with QThread
7. Settings persistence
8. Polish and error handling

## Testing Strategy
- Test transcription with sample Hebrew audio
- Test RTL rendering in both MD and PDF
- Test GPU/CPU fallback
- Test with various video formats

## Definition of Done
- All modules have error handling
- UI is responsive during transcription
- Output files open correctly in standard viewers
```

### 3. Create AGENTS.md
```markdown
# Agent Roles

## Builder Agent
- Implements all code modules
- Follows dev-best-practices skill
- Creates clean, documented code

## Tester Agent  
- Runs each module after creation
- Verifies RTL output
- Tests edge cases

## Integrator Agent
- Connects all modules
- Ensures smooth data flow
- Handles threading properly
```

---

## Project Structure

Create this exact structure:

```
HebrewTranscriber/
├── main.py
├── requirements.txt
├── README.md
├── ui/
│   ├── __init__.py
│   ├── main_window.py
│   ├── drop_zone.py
│   └── styles.qss
├── core/
│   ├── __init__.py
│   ├── transcriber.py
│   ├── audio_extractor.py
│   └── exporter.py
├── utils/
│   ├── __init__.py
│   ├── config.py
│   └── helpers.py
└── fonts/
    └── (download NotoSansHebrew-Regular.ttf)
```

---

## Implementation Details

### requirements.txt
```
PyQt6>=6.5.0
faster-whisper>=1.0.0
torch>=2.0.0
reportlab>=4.0.0
python-bidi>=0.4.2
arabic-reshaper>=3.0.0
```

### main.py
```python
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from ui.main_window import MainWindow

def main():
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Hebrew Transcriber")
    app.setOrganizationName("HebrewTranscriber")
    
    # Load stylesheet
    with open("ui/styles.qss", "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

### core/transcriber.py
```python
from faster_whisper import WhisperModel
from typing import Callable, Optional, List, Dict
import torch

class HebrewTranscriber:
    """
    Hebrew transcription using ivrit-ai fine-tuned Whisper model.
    Automatically selects GPU if available, falls back to CPU.
    """
    
    MODEL_ID = "ivrit-ai/whisper-v2-d4"
    # Alternative faster model: "ivrit-ai/whisper-large-v3-turbo-ct2"
    
    def __init__(self):
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"
    
    def load_model(self, progress_callback: Optional[Callable] = None):
        """Load the model. Call this before transcribe()."""
        if progress_callback:
            progress_callback("Loading ivrit-ai model...")
        
        self.model = WhisperModel(
            self.MODEL_ID,
            device=self.device,
            compute_type=self.compute_type,
            download_root="./models"
        )
        
        if progress_callback:
            progress_callback(f"Model loaded on {self.device.upper()}")
    
    def transcribe(
        self,
        audio_path: str,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> List[Dict]:
        """
        Transcribe audio file to Hebrew text with timestamps.
        
        Args:
            audio_path: Path to audio file (WAV recommended)
            progress_callback: Function receiving progress 0-100
            
        Returns:
            List of segments: [{"start": float, "end": float, "text": str}, ...]
        """
        if self.model is None:
            self.load_model()
        
        segments, info = self.model.transcribe(
            audio_path,
            language="he",
            task="transcribe",
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200
            ),
            word_timestamps=False
        )
        
        results = []
        total_duration = info.duration
        
        for segment in segments:
            results.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            })
            
            if progress_callback and total_duration > 0:
                progress = min(100, (segment.end / total_duration) * 100)
                progress_callback(progress)
        
        return results
```

### core/audio_extractor.py
```python
import subprocess
import shutil
from pathlib import Path
from typing import Optional

class AudioExtractor:
    """Extract audio from video files using ffmpeg."""
    
    SUPPORTED_FORMATS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.wmv'}
    
    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
    
    def _find_ffmpeg(self) -> Optional[str]:
        """Locate ffmpeg executable."""
        return shutil.which("ffmpeg")
    
    def is_available(self) -> bool:
        """Check if ffmpeg is available."""
        return self.ffmpeg_path is not None
    
    def extract(self, video_path: str, output_path: Optional[str] = None) -> str:
        """
        Extract audio from video file.
        
        Args:
            video_path: Path to video file
            output_path: Optional output path (defaults to same name .wav)
            
        Returns:
            Path to extracted audio file
        """
        if not self.is_available():
            raise RuntimeError(
                "ffmpeg not found. Please install ffmpeg:\n"
                "Windows: choco install ffmpeg\n"
                "Mac: brew install ffmpeg\n"
                "Linux: sudo apt install ffmpeg"
            )
        
        video_path = Path(video_path)
        
        if video_path.suffix.lower() not in self.SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {video_path.suffix}")
        
        if output_path is None:
            output_path = video_path.with_suffix('.wav')
        else:
            output_path = Path(output_path)
        
        cmd = [
            self.ffmpeg_path,
            '-y',                    # Overwrite output
            '-i', str(video_path),   # Input file
            '-vn',                   # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '16000',          # 16kHz (optimal for Whisper)
            '-ac', '1',              # Mono
            str(output_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg error: {result.stderr}")
        
        return str(output_path)
```

### core/exporter.py
```python
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_RIGHT
from bidi.algorithm import get_display
import arabic_reshaper

def format_timestamp(seconds: float) -> str:
    """Convert seconds to MM:SS format."""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"

class MarkdownExporter:
    """Export transcription to RTL Markdown."""
    
    def export(
        self,
        segments: List[Dict],
        output_path: str,
        title: str = "Transcription"
    ):
        """
        Export segments to Markdown file with RTL support.
        
        Args:
            segments: List of {"start", "end", "text"} dicts
            output_path: Output file path
            title: Document title
        """
        output_path = Path(output_path)
        
        content = f'''<div dir="rtl" style="text-align: right; font-family: 'David', 'Arial Hebrew', Arial, sans-serif;">

# {title}

📅 נוצר: {datetime.now().strftime("%Y-%m-%d %H:%M")}

---

'''
        
        for seg in segments:
            timestamp = format_timestamp(seg['start'])
            text = seg['text']
            content += f"**[{timestamp}]** {text}\n\n"
        
        content += "\n</div>\n"
        
        output_path.write_text(content, encoding='utf-8')


class PDFExporter:
    """Export transcription to RTL PDF."""
    
    FONT_PATH = "fonts/NotoSansHebrew-Regular.ttf"
    
    def __init__(self):
        self._register_font()
    
    def _register_font(self):
        """Register Hebrew font for PDF generation."""
        font_path = Path(self.FONT_PATH)
        
        if not font_path.exists():
            # Try to download or use system font
            import urllib.request
            font_path.parent.mkdir(exist_ok=True)
            url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansHebrew/NotoSansHebrew-Regular.ttf"
            try:
                urllib.request.urlretrieve(url, font_path)
            except Exception:
                # Fall back to Arial if available
                pass
        
        if font_path.exists():
            pdfmetrics.registerFont(TTFont('Hebrew', str(font_path)))
    
    def _reshape_hebrew(self, text: str) -> str:
        """Apply BiDi algorithm for correct RTL rendering."""
        reshaped = arabic_reshaper.reshape(text)
        return get_display(reshaped)
    
    def export(
        self,
        segments: List[Dict],
        output_path: str,
        title: str = "Transcription"
    ):
        """
        Export segments to PDF with RTL Hebrew support.
        
        Args:
            segments: List of {"start", "end", "text"} dicts
            output_path: Output file path
            title: Document title
        """
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=50,
            leftMargin=50,
            topMargin=50,
            bottomMargin=50
        )
        
        # Hebrew paragraph style
        hebrew_style = ParagraphStyle(
            'Hebrew',
            fontName='Hebrew' if 'Hebrew' in pdfmetrics.getRegisteredFontNames() else 'Helvetica',
            fontSize=12,
            leading=20,
            alignment=TA_RIGHT,
            wordWrap='RTL'
        )
        
        title_style = ParagraphStyle(
            'HebrewTitle',
            parent=hebrew_style,
            fontSize=18,
            spaceAfter=20
        )
        
        story = []
        
        # Title
        story.append(Paragraph(self._reshape_hebrew(title), title_style))
        story.append(Spacer(1, 20))
        
        # Content
        for seg in segments:
            timestamp = format_timestamp(seg['start'])
            text = self._reshape_hebrew(seg['text'])
            
            para = Paragraph(f"[{timestamp}] {text}", hebrew_style)
            story.append(para)
            story.append(Spacer(1, 10))
        
        doc.build(story)
```

### ui/main_window.py
```python
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QTextEdit,
    QFileDialog, QRadioButton, QButtonGroup, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from pathlib import Path

from core.transcriber import HebrewTranscriber
from core.audio_extractor import AudioExtractor
from core.exporter import MarkdownExporter, PDFExporter
from utils.config import Config


class TranscriptionWorker(QThread):
    """Worker thread for transcription to keep UI responsive."""
    
    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, video_path: str):
        super().__init__()
        self.video_path = video_path
        self.transcriber = HebrewTranscriber()
        self.extractor = AudioExtractor()
    
    def run(self):
        try:
            # Extract audio
            self.status.emit("מחלץ אודיו מהסרטון...")
            audio_path = self.extractor.extract(self.video_path)
            
            # Load model
            self.status.emit("טוען מודל תמלול...")
            self.transcriber.load_model()
            
            # Transcribe
            self.status.emit("מתמלל...")
            segments = self.transcriber.transcribe(
                audio_path,
                progress_callback=lambda p: self.progress.emit(int(p))
            )
            
            # Cleanup temp audio
            Path(audio_path).unlink(missing_ok=True)
            
            self.finished.emit(segments)
            
        except Exception as e:
            self.error.emit(str(e))


class DropZone(QLabel):
    """Drag & drop zone for video files."""
    
    file_dropped = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setText("גרור קובץ וידאו לכאן\nאו לחץ לבחירה")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("dropZone")
        self.setMinimumHeight(150)
    
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
        
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if Path(file_path).suffix.lower() in AudioExtractor.SUPPORTED_FORMATS:
                self.file_dropped.emit(file_path)
                return
        
        QMessageBox.warning(self, "שגיאה", "פורמט קובץ לא נתמך")
    
    def mousePressEvent(self, event):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "בחר קובץ וידאו",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.webm)"
        )
        if file_path:
            self.file_dropped.emit(file_path)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.current_file = None
        self.worker = None
        
        self.setup_ui()
        self.setWindowTitle("🎬 מתמלל עברית - Hebrew Transcriber")
        self.setMinimumSize(500, 600)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    
    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.file_dropped.connect(self.on_file_selected)
        layout.addWidget(self.drop_zone)
        
        # Output directory
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("📁 תיקיית יעד:"))
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
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # Transcribe button
        self.transcribe_btn = QPushButton("🚀 תמלל")
        self.transcribe_btn.setObjectName("transcribeBtn")
        self.transcribe_btn.setEnabled(False)
        self.transcribe_btn.clicked.connect(self.start_transcription)
        layout.addWidget(self.transcribe_btn)
        
        # Log area
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
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
    
    def on_file_selected(self, file_path: str):
        self.current_file = file_path
        self.drop_zone.setText(f"✓ {Path(file_path).name}")
        self.transcribe_btn.setEnabled(True)
        self.log_message(f"נבחר: {file_path}")
    
    def start_transcription(self):
        if not self.current_file:
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
        self.worker = TranscriptionWorker(self.current_file)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.status.connect(self.log_message)
        self.worker.finished.connect(self.on_transcription_complete)
        self.worker.error.connect(self.on_transcription_error)
        self.worker.start()
    
    def on_transcription_complete(self, segments: list):
        output_dir = Path(self.config.last_output_dir)
        title = Path(self.current_file).stem
        
        # Export based on selection
        if self.md_radio.isChecked() or self.both_radio.isChecked():
            md_path = output_dir / f"{title}.md"
            MarkdownExporter().export(segments, str(md_path), title)
            self.log_message(f"✓ נשמר: {md_path}")
        
        if self.pdf_radio.isChecked() or self.both_radio.isChecked():
            pdf_path = output_dir / f"{title}.pdf"
            PDFExporter().export(segments, str(pdf_path), title)
            self.log_message(f"✓ נשמר: {pdf_path}")
        
        # Reset UI
        self.progress_bar.setVisible(False)
        self.transcribe_btn.setEnabled(True)
        self.log_message("✓ התמלול הושלם בהצלחה!")
        
        # Open output folder
        import os
        os.startfile(str(output_dir))
    
    def on_transcription_error(self, error: str):
        self.progress_bar.setVisible(False)
        self.transcribe_btn.setEnabled(True)
        self.log_message(f"❌ שגיאה: {error}")
        QMessageBox.critical(self, "שגיאה", error)
```

### utils/config.py
```python
from PyQt6.QtCore import QSettings

class Config:
    """Persistent settings manager."""
    
    def __init__(self):
        self.settings = QSettings('HebrewTranscriber', 'Settings')
    
    @property
    def last_output_dir(self) -> str:
        return self.settings.value('last_output_dir', '')
    
    @last_output_dir.setter
    def last_output_dir(self, value: str):
        self.settings.setValue('last_output_dir', value)
    
    @property
    def output_format(self) -> str:
        return self.settings.value('output_format', 'md')
    
    @output_format.setter
    def output_format(self, value: str):
        self.settings.setValue('output_format', value)
```

### ui/styles.qss
```css
QMainWindow {
    background-color: #f8f9fa;
}

QLabel {
    font-family: "Segoe UI", "Arial Hebrew", sans-serif;
    font-size: 13px;
}

#dropZone {
    background-color: #ffffff;
    border: 2px dashed #dee2e6;
    border-radius: 12px;
    font-size: 14px;
    color: #6c757d;
}

#dropZone[dragOver="true"] {
    background-color: #e7f5ff;
    border-color: #339af0;
}

#pathLabel {
    color: #495057;
    padding: 5px 10px;
    background-color: #e9ecef;
    border-radius: 4px;
}

QPushButton {
    background-color: #e9ecef;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #dee2e6;
}

#transcribeBtn {
    background-color: #40c057;
    color: white;
    font-size: 16px;
    font-weight: bold;
    padding: 12px 30px;
    border-radius: 8px;
}

#transcribeBtn:hover {
    background-color: #37b24d;
}

#transcribeBtn:disabled {
    background-color: #adb5bd;
}

QProgressBar {
    border: none;
    border-radius: 6px;
    background-color: #e9ecef;
    height: 20px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #40c057;
    border-radius: 6px;
}

QTextEdit {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 8px;
    padding: 10px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 12px;
}

QRadioButton {
    font-size: 13px;
    spacing: 8px;
}
```

---

## Execution Instructions

### Phase 1: Setup
```bash
# Create project directory
mkdir -p HebrewTranscriber/{ui,core,utils,fonts}

# Create all __init__.py files
touch HebrewTranscriber/ui/__init__.py
touch HebrewTranscriber/core/__init__.py
touch HebrewTranscriber/utils/__init__.py

# Create requirements.txt and install
cd HebrewTranscriber
pip install -r requirements.txt --break-system-packages
```

### Phase 2: Build Core
1. Create `core/transcriber.py`
2. Create `core/audio_extractor.py`
3. Create `core/exporter.py`
4. Test each module independently

### Phase 3: Build UI
1. Create `ui/styles.qss`
2. Create `ui/main_window.py`
3. Create `main.py`

### Phase 4: Integration & Test
```bash
# Run the app
python main.py
```

### Phase 5: Fix Issues
- If any errors occur, fix them immediately
- Test with a real video file
- Verify RTL rendering in output files

---

## Validation Checklist

Before reporting completion:

- [ ] App launches without errors
- [ ] Drag & drop works for video files
- [ ] Browse button works for selecting output directory
- [ ] Progress bar updates during transcription
- [ ] Markdown output has correct RTL formatting
- [ ] PDF output renders Hebrew correctly
- [ ] Settings persist after restart
- [ ] Error messages display in Hebrew
- [ ] Log shows all operations

---

## DO NOT ASK - JUST DO

1. Read the skills
2. Create the project structure
3. Write all the code
4. Test everything
5. Fix any issues
6. Report when fully working

Start now.
