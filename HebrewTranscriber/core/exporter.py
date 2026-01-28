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


def format_timestamp_srt(seconds: float) -> str:
    """Convert seconds to SRT format HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{mins:02d}:{secs:02d},{millis:03d}"


class SRTExporter:
    """Export transcription to SRT subtitle format."""

    def export(
        self,
        segments: List[Dict],
        output_path: str,
        title: str = "Transcription"
    ):
        """
        Export segments to SRT file.

        Args:
            segments: List of {"start", "end", "text"} dicts
            output_path: Output file path
            title: Document title (unused for SRT)
        """
        output_path = Path(output_path)

        lines = []
        for i, seg in enumerate(segments, 1):
            start_time = format_timestamp_srt(seg['start'])
            end_time = format_timestamp_srt(seg['end'])
            text = seg['text']

            lines.append(f"{i}")
            lines.append(f"{start_time} --> {end_time}")
            lines.append(text)
            lines.append("")  # Empty line between entries

        output_path.write_text("\n".join(lines), encoding='utf-8')


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
        No timestamps - just line breaks between segments.

        Args:
            segments: List of {"start", "end", "text"} dicts
            output_path: Output file path
            title: Document title
        """
        output_path = Path(output_path)

        content = f'''<div dir="rtl" style="text-align: right; font-family: 'David', 'Arial Hebrew', Arial, sans-serif;">

# {title}

נוצר: {datetime.now().strftime("%Y-%m-%d %H:%M")}

---

'''

        for seg in segments:
            text = seg['text']
            content += f"{text}\n\n"

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
        No timestamps - just line breaks between segments.

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

        # Content - no timestamps, just text
        for seg in segments:
            text = self._reshape_hebrew(seg['text'])
            para = Paragraph(text, hebrew_style)
            story.append(para)
            story.append(Spacer(1, 10))

        doc.build(story)
