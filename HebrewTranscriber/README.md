# Hebrew Video Transcriber

A lightweight PyQt6 desktop application for transcribing Hebrew videos using the ivrit-ai/whisper model.

## Features

- Drag & drop video files
- Hebrew transcription using ivrit-ai fine-tuned Whisper
- RTL output in Markdown and PDF formats
- Automatic GPU/CPU selection
- Persistent settings

## Requirements

- Python 3.10+
- ffmpeg (for audio extraction)

## Installation

```bash
# Install ffmpeg
# Windows: choco install ffmpeg
# Mac: brew install ffmpeg
# Linux: sudo apt install ffmpeg

# Install Python dependencies
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

1. Drag & drop a video file or click to browse
2. Select output directory
3. Choose output format (Markdown, PDF, or both)
4. Click "תמלל" to start transcription

## Supported Formats

- MP4, MKV, AVI, MOV, WebM, M4V, WMV
