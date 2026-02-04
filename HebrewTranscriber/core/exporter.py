from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import re
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
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


# ========== SRT File Parsing & Merge Utilities ==========

TIMESTAMP_PATTERN = re.compile(r'^\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}')


def _natural_sort_key(path: Path):
    """Natural sort key so AGENTS 2 sorts before AGENTS 10."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', str(path))]


def _bidi_text(text: str) -> str:
    """Apply BiDi algorithm for correct RTL rendering in PDF.
    Uses get_display() only - arabic_reshaper strips spaces from Hebrew.
    Replaces spaces with non-breaking spaces to prevent ReportLab
    Paragraph from collapsing them."""
    result = get_display(text)
    return result.replace(' ', '\u00a0')


def _group_into_paragraphs(text_lines: List[str], lines_per_paragraph: int = 6) -> List[str]:
    """Group subtitle lines into flowing paragraphs for readable output."""
    if not text_lines:
        return []

    paragraphs = []
    for i in range(0, len(text_lines), lines_per_paragraph):
        chunk = text_lines[i:i + lines_per_paragraph]
        paragraphs.append(' '.join(chunk))
    return paragraphs


def srt_to_text(srt_path: Path) -> List[str]:
    """Parse SRT file and return clean text lines (no timestamps, no indices)."""
    content = None
    for encoding in ['utf-8', 'utf-8-sig', 'cp1252', 'iso-8859-8']:
        try:
            content = srt_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        return []

    # Remove RTL marker if present
    content = content.replace('<!-- RTL_FIXED -->', '')

    lines = content.strip().split('\n')
    text_lines = []

    for line in lines:
        stripped = line.strip()
        # Skip empty lines
        if not stripped:
            continue
        # Skip index numbers (pure digits)
        if stripped.isdigit():
            continue
        # Skip timestamp lines
        if TIMESTAMP_PATTERN.match(stripped):
            continue
        # Keep text lines
        text_lines.append(stripped)

    return text_lines


def find_all_srts(folder: Path) -> List[Path]:
    """Recursively find all .srt files in folder and subfolders, natural sorted."""
    return sorted(folder.rglob("*.srt"), key=_natural_sort_key)


def find_all_srts_multi(folders: List[Path]) -> List[Path]:
    """Find all .srt files across multiple folders, natural sorted."""
    all_srts = []
    for folder in folders:
        all_srts.extend(folder.rglob("*.srt"))
    return sorted(all_srts, key=_natural_sort_key)


def export_srt_to_md(srt_path: Path, output_path: Path, title: Optional[str] = None):
    """Convert a single SRT file to RTL Markdown - one line per subtitle entry."""
    if title is None:
        title = srt_path.stem

    text_lines = srt_to_text(srt_path)
    if not text_lines:
        return

    content = f'''<div dir="rtl" style="text-align: right; font-family: 'David', 'Arial Hebrew', Arial, sans-serif;">

# {title}

---

'''
    for line in text_lines:
        content += f"{line}\n\n"

    content += "\n</div>\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding='utf-8')


def export_srt_to_pdf(srt_path: Path, output_path: Path, title: Optional[str] = None):
    """Convert a single SRT file to RTL PDF with flowing paragraphs."""
    if title is None:
        title = srt_path.stem

    text_lines = srt_to_text(srt_path)
    if not text_lines:
        return

    PDFExporter()  # ensure font is registered
    paragraphs = _group_into_paragraphs(text_lines)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=50, leftMargin=50,
        topMargin=50, bottomMargin=50
    )

    hebrew_style = ParagraphStyle(
        'Hebrew',
        fontName='Hebrew' if 'Hebrew' in pdfmetrics.getRegisteredFontNames() else 'Helvetica',
        fontSize=12, leading=20,
        alignment=TA_RIGHT, wordWrap='RTL'
    )
    title_style = ParagraphStyle(
        'HebrewTitle', parent=hebrew_style,
        fontSize=18, spaceAfter=20
    )

    story = [
        Paragraph(_bidi_text(title), title_style),
        Spacer(1, 20)
    ]

    for para in paragraphs:
        story.append(Paragraph(_bidi_text(para), hebrew_style))
        story.append(Spacer(1, 12))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)


def merge_srts_to_md(
    srt_files: List[Path],
    output_path: Path,
    title: str = "Merged Transcriptions"
):
    """Merge multiple SRT files into one RTL Markdown document - one line per subtitle entry."""
    if not srt_files:
        return

    content = f'''<div dir="rtl" style="text-align: right; font-family: 'David', 'Arial Hebrew', Arial, sans-serif;">

# {title}

נוצר: {datetime.now().strftime("%Y-%m-%d %H:%M")}

'''

    for srt_path in srt_files:
        section_title = srt_path.stem
        text_lines = srt_to_text(srt_path)

        content += f"\n---\n\n## {section_title}\n\n"

        for line in text_lines:
            content += f"{line}\n\n"

    content += "\n</div>\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding='utf-8')


def merge_srts_to_pdf(
    srt_files: List[Path],
    output_path: Path,
    title: str = "Merged Transcriptions"
):
    """Merge multiple SRT files into one RTL PDF document with flowing paragraphs."""
    if not srt_files:
        return

    PDFExporter()  # ensure font is registered

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=50, leftMargin=50,
        topMargin=50, bottomMargin=50
    )

    hebrew_style = ParagraphStyle(
        'Hebrew',
        fontName='Hebrew' if 'Hebrew' in pdfmetrics.getRegisteredFontNames() else 'Helvetica',
        fontSize=12, leading=20,
        alignment=TA_RIGHT, wordWrap='RTL'
    )
    title_style = ParagraphStyle(
        'HebrewTitle', parent=hebrew_style,
        fontSize=22, spaceAfter=30
    )
    section_style = ParagraphStyle(
        'HebrewSection', parent=hebrew_style,
        fontSize=16, spaceAfter=15, spaceBefore=10
    )

    story = [
        Paragraph(_bidi_text(title), title_style),
        Spacer(1, 30)
    ]

    for i, srt_path in enumerate(srt_files):
        if i > 0:
            story.append(PageBreak())

        section_title = srt_path.stem
        story.append(Paragraph(_bidi_text(section_title), section_style))
        story.append(Spacer(1, 10))

        text_lines = srt_to_text(srt_path)
        paragraphs = _group_into_paragraphs(text_lines)
        for para in paragraphs:
            story.append(Paragraph(_bidi_text(para), hebrew_style))
            story.append(Spacer(1, 12))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)
