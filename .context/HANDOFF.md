## Goal
Build a PyQt6 desktop application for transcribing Hebrew videos using the ivrit-ai/whisper model with RTL output in MD/PDF formats. Version 1.0.3 adds subtitle embedding feature (from SubtitlePipeline integration).

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
- [x] **v1.0.2** Created GitHub repo and pushed: https://github.com/NatiLevyy/Hebrew-Video-Transcriber
- [x] **v1.0.3** Created core/subtitle_embedder.py - MKVToolNix-based subtitle embedding (from SubtitlePipeline)
- [x] **v1.0.3** Created ui/embedding_tab.py - Subtitle embedding UI tab
- [x] **v1.0.3** Added Embed Subtitles tab to main window

## In Progress
- [ ] Testing v1.0.3 subtitle embedding feature

## Key Decisions
- **Model**: ivrit-ai/whisper-v2-d4 (Hebrew fine-tuned)
- **GUI Framework**: PyQt6 for native look and built-in RTL support
- **Audio extraction**: ffmpeg for broad format support
- **PDF RTL**: python-bidi + arabic-reshaper for correct Hebrew rendering
- **v1.0.2 Chrome CDP**: Google blocks Playwright automation. Solution: launch real Chrome with `--remote-debugging-port=9222` and connect via CDP
- **v1.0.2 Per-operation connections**: Playwright sync API isn't thread-safe. Each QThread creates own connection
- **v1.0.2 UI Layout**: Horizontal splitter with controls on left, log on right
- **v1.0.3 Subtitle Embedding**: Integrated from SubtitlePipeline project using mkvmerge (MKVToolNix)
- **v1.0.3 Video Format**: Input supports MP4/MKV/AVI/MOV/WebM, output is always MKV with embedded subtitles

## Known Issues
- Warning about pkg_resources deprecation in ctranslate2 (does not affect functionality)
- Font download for PDF may fail if network unavailable (falls back to Helvetica)
- Node url.parse() deprecation warning from Playwright (harmless)
- **v1.0.3**: Requires MKVToolNix to be installed separately for embedding feature

## Next Steps
1. Test subtitle embedding with downloaded videos
2. Consider adding auto-embed option after transcription completes
3. Add batch embedding progress indicator

## Important Files
- `HebrewTranscriber/main.py` - Application entry point
- `HebrewTranscriber/core/transcriber.py` - Whisper transcription engine
- `HebrewTranscriber/core/audio_extractor.py` - ffmpeg audio extraction
- `HebrewTranscriber/core/exporter.py` - MD/PDF export with RTL
- `HebrewTranscriber/core/notebooklm_downloader.py` - NotebookLM batch downloader
- `HebrewTranscriber/core/subtitle_embedder.py` - **NEW v1.0.3** MKVToolNix subtitle embedding
- `HebrewTranscriber/ui/main_window.py` - PyQt6 GUI with tabs
- `HebrewTranscriber/ui/notebooklm_tab.py` - NotebookLM downloader tab
- `HebrewTranscriber/ui/embedding_tab.py` - **NEW v1.0.3** Subtitle embedding tab
- `HebrewTranscriber/ui/styles.qss` - Application styling
- `HebrewTranscriber/utils/config.py` - Settings persistence

## Version History
- **v1.0.0** - Initial release with transcription functionality
- **v1.0.2** - Added NotebookLM batch downloader feature with tab-based UI
- **v1.0.3** - Added subtitle embedding feature (SubtitlePipeline integration)

## External Dependencies
- **ffmpeg** - Audio extraction (required for transcription)
- **MKVToolNix** - Subtitle embedding (required for v1.0.3 embed feature)
  - Download: https://mkvtoolnix.download/
