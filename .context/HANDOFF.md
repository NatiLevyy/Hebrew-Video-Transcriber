## Goal
Build a PyQt6 desktop application for transcribing Hebrew videos using the ivrit-ai/whisper model with RTL output. Version 1.0.4 adds unified pipeline tab and RTL fixer integration.

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

## Key Decisions
- **Model**: ivrit-ai/whisper-v2-d4 (Hebrew fine-tuned)
- **GUI Framework**: PyQt6 for native look and built-in RTL support
- **Audio extraction**: ffmpeg for broad format support
- **PDF RTL**: python-bidi + arabic-reshaper for correct Hebrew rendering
- **v1.0.2 Chrome CDP**: Google blocks Playwright automation. Solution: launch real Chrome with CDP
- **v1.0.3 Subtitle Embedding**: Using mkvmerge from MKVToolNix
- **v1.0.4 RTL Fix**: Automatic RTL punctuation fixing before embedding (from SubtitlePipeline)
- **v1.0.4 Unified Pipeline**: Single tab for complete workflow (Transcribe → RTL → Embed)

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
- `HebrewTranscriber/core/rtl_fixer.py` - **NEW v1.0.4** RTL punctuation fixer
- `HebrewTranscriber/ui/main_window.py` - PyQt6 GUI with tabs
- `HebrewTranscriber/ui/pipeline_tab.py` - **NEW v1.0.4** Unified pipeline tab
- `HebrewTranscriber/ui/notebooklm_tab.py` - NotebookLM downloader tab
- `HebrewTranscriber/ui/embedding_tab.py` - Subtitle embedding tab
- `HebrewTranscriber/ui/styles.qss` - Application styling

## Version History
- **v1.0.0** - Initial release with transcription functionality
- **v1.0.2** - Added NotebookLM batch downloader feature
- **v1.0.3** - Added subtitle embedding feature (SubtitlePipeline integration)
- **v1.0.4** - Added RTL fixer + Unified pipeline tab (complete workflow)

## External Dependencies
- **ffmpeg** - Audio extraction (required for transcription)
- **MKVToolNix** - Subtitle embedding (required for embed feature)
  - Download: https://mkvtoolnix.download/
