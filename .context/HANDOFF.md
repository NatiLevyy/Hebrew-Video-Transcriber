## Goal
Build a PyQt6 desktop application for transcribing Hebrew videos using the ivrit-ai/whisper model with RTL output in MD/PDF formats. Version 1.0.2 adds NotebookLM batch downloader feature.

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
- [x] Installed all dependencies (PyQt6, faster-whisper, torch, reportlab, etc.)
- [x] Verified all imports work correctly
- [x] App launches successfully
- [x] **v1.0.2** Created core/notebooklm_downloader.py - Playwright-based NotebookLM downloader
- [x] **v1.0.2** Created ui/notebooklm_tab.py - NotebookLM batch downloader UI tab
- [x] **v1.0.2** Refactored main_window.py to use tabs (Transcription + NotebookLM)
- [x] **v1.0.2** Updated styles.qss with tab widget styles and new UI components
- [x] **v1.0.2** Updated requirements.txt with playwright and requests

## In Progress
- [ ] User testing: Login → List notebooks → Select → Scan for media → Download

## Key Decisions
- **Model**: ivrit-ai/whisper-v2-d4 (Hebrew fine-tuned)
- **GUI Framework**: PyQt6 for native look and built-in RTL support
- **Audio extraction**: ffmpeg for broad format support
- **PDF RTL**: python-bidi + arabic-reshaper for correct Hebrew rendering
- **v1.0.2 Chrome CDP**: Google blocks Playwright automation. Solution: launch real Chrome with `--remote-debugging-port=9222` and connect via CDP
- **v1.0.2 Per-operation connections**: Playwright sync API isn't thread-safe. Each QThread creates own connection
- **v1.0.2 UI Layout**: Horizontal splitter with controls on left, log on right

## Known Issues
- Warning about pkg_resources deprecation in ctranslate2 (does not affect functionality)
- Font download for PDF may fail if network unavailable (falls back to Helvetica)
- Node url.parse() deprecation warning from Playwright (harmless)

## Next Steps
1. Test NotebookLM login and notebook scanning
2. Verify downloaded files can be transcribed by the Transcription tab
3. If no media found, may need to adjust regex patterns or add more wait time

## Important Files
- `HebrewTranscriber/main.py` - Application entry point
- `HebrewTranscriber/core/transcriber.py` - Whisper transcription engine
- `HebrewTranscriber/core/audio_extractor.py` - ffmpeg audio extraction
- `HebrewTranscriber/core/exporter.py` - MD/PDF export with RTL
- `HebrewTranscriber/core/notebooklm_downloader.py` - **NEW** NotebookLM batch downloader
- `HebrewTranscriber/ui/main_window.py` - PyQt6 GUI with tabs
- `HebrewTranscriber/ui/notebooklm_tab.py` - **NEW** NotebookLM downloader tab
- `HebrewTranscriber/ui/styles.qss` - Application styling
- `HebrewTranscriber/utils/config.py` - Settings persistence

## Version History
- **v1.0.0** - Initial release with transcription functionality
- **v1.0.2** - Added NotebookLM batch downloader feature with tab-based UI
