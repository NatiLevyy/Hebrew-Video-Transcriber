## Goal
Build a PyQt6 desktop application for transcribing Hebrew videos using the ivrit-ai/whisper model with RTL output. Version 1.0.7 adds notebook caching and Google Drive integration.

## Completed
- [x] Created project directory structure
- [x] Created requirements.txt with all dependencies
- [x] Built core/transcriber.py - Hebrew transcription using ivrit-ai/whisper-v2-d4
- [x] Built core/audio_extractor.py - ffmpeg-based audio extraction
- [x] Built core/exporter.py - Markdown and PDF exporters with RTL support
- [x] Built ui/main_window.py - Main application window with drag & drop
- [x] Built ui/styles.qss - Modern green-themed stylesheet
- [x] Built utils/config.py - Persistent settings using QSettings
- [x] Created main.py entry point
- [x] App launches successfully
- [x] **v1.0.2** Created core/notebooklm_downloader.py - Playwright-based NotebookLM downloader
- [x] **v1.0.2** Created ui/notebooklm_tab.py - NotebookLM batch downloader UI tab
- [x] **v1.0.2** Created GitHub repo: https://github.com/NatiLevyy/Hebrew-Video-Transcriber
- [x] **v1.0.3** Created core/subtitle_embedder.py - MKVToolNix-based subtitle embedding
- [x] **v1.0.3** Created ui/embedding_tab.py - Subtitle embedding UI tab
- [x] **v1.0.4** Created core/rtl_fixer.py - RTL punctuation fixer (from SubtitlePipeline)
- [x] **v1.0.4** Integrated RTL fix into embedding process (automatic before embedding)
- [x] **v1.0.4** Created ui/pipeline_tab.py - Unified pipeline: Transcribe → RTL Fix → Embed
- [x] **v1.0.5** Fully automated one-click pipeline (Login → START runs everything)
- [x] **v1.0.5** Created HebrewTranscriber.spec for PyInstaller EXE packaging
- [x] **v1.0.5** Built HebrewTranscriber.exe (213MB) in dist/ folder
- [x] **v1.0.5** Fixed lazy loading for notebook discovery (scroll loop + Method 3 fallback)
- [x] **v1.0.5** Per-notebook folder structure (each notebook gets its own subfolder)
- [x] **v1.0.5** Search box for notebook list filtering
- [x] **v1.0.6** SRT parsing functions (srt_to_text, find_all_srts) in exporter.py
- [x] **v1.0.6** Single SRT export to MD/PDF (export_srt_to_md, export_srt_to_pdf)
- [x] **v1.0.6** Merge all SRTs into unified MD/PDF (merge_srts_to_md, merge_srts_to_pdf)
- [x] **v1.0.6** Pipeline Stage 3.5: auto export/merge after transcription
- [x] **v1.0.6** Standalone "Merge All SRTs" button in Pipeline tab
- [x] **v1.0.6** Merge SRT buttons in Transcription tab (MD/PDF/Both)
- [x] **v1.0.6** Fixed PDF title spacing (arabic_reshaper strips Hebrew spaces, use get_display only)
- [x] **v1.0.6** PDF uses flowing paragraphs (6 lines grouped), MD keeps one-line-per-entry
- [x] **v1.0.6** Multi-folder merge dialog: "Scan Parent Folder" shows subfolders as checkboxes
- [x] **v1.0.6** Replaced broken QFileDialog multi-select hack with reliable checkbox approach
- [x] **v1.0.7** Notebook caching - JSON cache to avoid re-scanning all notebooks every time
- [x] **v1.0.7** "Refresh" button checks for new notebooks (uses cache)
- [x] **v1.0.7** "Full Scan" button ignores cache and rescans all notebooks
- [x] **v1.0.7** Google Drive integration with OAuth2 authentication
- [x] **v1.0.7** Manual "Upload to Drive" button with file selection dialog
- [x] **v1.0.7** Drive folder structure: HebrewTranscriber/YYYY-MM/[Notebook]/[files]
- [x] **v1.0.7** MP4 conversion tab exists for standalone SRT→MP4 embedding
- [x] **v1.0.7** Fixed GPU encoder fallback - auto-switches to libx264 (CPU) if GPU encoder fails
- [x] **v1.1.0** Fixed PyQt6 compatibility (downgraded to 6.7.0 for Windows DLL issues)

## Key Decisions
- **Model**: ivrit-ai/whisper-v2-d4 (Hebrew fine-tuned)
- **GUI Framework**: PyQt6 for native look and built-in RTL support
- **Audio extraction**: ffmpeg for broad format support
- **PDF RTL**: python-bidi + arabic-reshaper for correct Hebrew rendering
- **v1.0.2 Chrome CDP**: Google blocks Playwright automation. Solution: launch real Chrome with CDP
- **v1.0.3 Subtitle Embedding**: Using mkvmerge from MKVToolNix
- **v1.0.4 RTL Fix**: Automatic RTL punctuation fixing before embedding (from SubtitlePipeline)
- **v1.0.5 Unified Pipeline**: 2-click workflow (Login + START) runs: Scan → Download → Transcribe → RTL → Embed
- **v1.0.6 Multi-folder**: QFileDialog multi-select hack doesn't work on Windows/PyQt6. Solution: "Scan Parent Folder" shows subfolders as checkable items
- **v1.0.6 PDF Hebrew**: arabic_reshaper strips spaces from Hebrew. Use get_display() only (no reshape) for correct title/text rendering
- **v1.0.7 Notebook Caching**: JSON file at %APPDATA%\HebrewTranscriber\notebooks_cache.json stores notebook list
- **v1.0.7 Google Drive**: OAuth2 with drive.file scope (only files created by app). User must provide client_secrets.json

## Known Issues
- Warning about pkg_resources deprecation in ctranslate2 (harmless)
- **v1.0.3+**: Requires MKVToolNix to be installed separately for embedding feature

## Important Files
- `HebrewTranscriber/main.py` - Application entry point
- `HebrewTranscriber/core/transcriber.py` - Whisper transcription engine
- `HebrewTranscriber/core/audio_extractor.py` - ffmpeg audio extraction
- `HebrewTranscriber/core/exporter.py` - MD/PDF/SRT export with RTL
- `HebrewTranscriber/core/notebooklm_downloader.py` - NotebookLM batch downloader
- `HebrewTranscriber/core/subtitle_embedder.py` - MKVToolNix subtitle embedding
- `HebrewTranscriber/core/rtl_fixer.py` - RTL punctuation fixer
- `HebrewTranscriber/ui/main_window.py` - PyQt6 GUI with tabs
- `HebrewTranscriber/ui/pipeline_tab.py` - Fully automated pipeline tab
- `HebrewTranscriber/ui/notebooklm_tab.py` - NotebookLM downloader tab
- `HebrewTranscriber/ui/embedding_tab.py` - Subtitle embedding tab
- `HebrewTranscriber/ui/styles.qss` - Application styling
- `HebrewTranscriber/core/google_drive.py` - Google Drive OAuth2 and file upload
- `HebrewTranscriber.spec` - PyInstaller build configuration

## Version History
- **v1.0.0** - Initial release with transcription functionality
- **v1.0.2** - Added NotebookLM batch downloader feature
- **v1.0.3** - Added subtitle embedding feature (SubtitlePipeline integration)
- **v1.0.4** - Added RTL fixer + Unified pipeline tab (complete workflow)
- **v1.0.5** - Fully automated one-click pipeline + EXE packaging + lazy loading fix + per-notebook folders + search box
- **v1.0.6** - SRT export & merge: convert SRTs to MD/PDF, merge all SRTs into one unified document
- **v1.0.7** - Notebook caching + Google Drive integration (OAuth2 upload with file selection)
- **v1.1.0** - PyQt6 compatibility fix, MP4 tab fully functional, GPU→CPU encoder fallback

## External Dependencies
- **ffmpeg** - Audio extraction (required for transcription)
- **MKVToolNix** - Subtitle embedding (required for embed feature)
  - Download: https://mkvtoolnix.download/
- **Google Drive API** (optional) - For uploading files to Drive
  - User must create Google Cloud project and place `client_secrets.json` at:
    `%APPDATA%\HebrewTranscriber\google_credentials\client_secrets.json`

## Building EXE
```bash
cd g:\Projects\Hebrew-Video-Transcriber
python -m PyInstaller HebrewTranscriber.spec --noconfirm
```
Output: `dist/HebrewTranscriber.exe` (213MB)
