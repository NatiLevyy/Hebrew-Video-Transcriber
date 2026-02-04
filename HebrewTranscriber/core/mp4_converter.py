"""
MP4 Converter - Convert videos to MP4 with hard-burned Hebrew subtitles.

Uses FFmpeg to burn SRT subtitles directly into the video stream,
producing WhatsApp-compatible MP4 files. Supports GPU acceleration
(NVENC, QSV, AMF) with automatic detection and CPU fallback.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass

from core.subtitle_embedder import match_srt_to_video, VIDEO_FORMATS
from core.rtl_fixer import fix_rtl_folder


@dataclass
class ConvertResult:
    """Result of converting a single video."""
    success: bool
    video_file: Path
    output_file: Optional[Path] = None
    srt_file: Optional[Path] = None
    error: Optional[str] = None


def find_ffmpeg() -> Optional[str]:
    """Find ffmpeg executable."""
    return shutil.which("ffmpeg")


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available."""
    return find_ffmpeg() is not None


# Cache for detected encoder
_cached_encoder: Optional[str] = None


def detect_hw_encoder(ffmpeg_path: str, log: Optional[Callable[[str], None]] = None) -> str:
    """
    Detect the best available H.264 encoder.

    Tries GPU-accelerated encoders first, falls back to CPU.
    Order: h264_nvenc (NVIDIA) → h264_qsv (Intel) → h264_amf (AMD) → libx264 (CPU)

    Returns:
        Encoder name string for FFmpeg -c:v parameter.
    """
    global _cached_encoder
    if _cached_encoder is not None:
        return _cached_encoder

    if log is None:
        log = lambda x: None

    # Query available encoders
    try:
        result = subprocess.run(
            [ffmpeg_path, "-encoders"],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        encoder_output = result.stdout
    except Exception:
        _cached_encoder = "libx264"
        return _cached_encoder

    # Try GPU encoders in preference order
    gpu_encoders = [
        ("h264_nvenc", "NVIDIA GPU"),
        ("h264_qsv", "Intel QuickSync"),
        ("h264_amf", "AMD GPU"),
    ]

    for encoder, label in gpu_encoders:
        if encoder in encoder_output:
            log(f"GPU encoder detected: {label} ({encoder})")
            _cached_encoder = encoder
            return _cached_encoder

    log("No GPU encoder found, using CPU (libx264)")
    _cached_encoder = "libx264"
    return _cached_encoder


def convert_single(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    ffmpeg_path: str,
    encoder: str,
    log: Optional[Callable[[str], None]] = None
) -> ConvertResult:
    """
    Convert a single video to MP4 with hard-burned subtitles.

    Args:
        video_path: Input video file
        srt_path: SRT subtitle file to burn in
        output_path: Output MP4 file
        ffmpeg_path: Path to ffmpeg executable
        encoder: H.264 encoder to use (e.g. h264_nvenc, libx264)
        log: Optional logging callback

    Returns:
        ConvertResult
    """
    if log is None:
        log = lambda x: None

    try:
        # Ensure output has .mp4 extension
        if output_path.suffix.lower() != '.mp4':
            output_path = output_path.with_suffix('.mp4')

        # Build subtitle filter string
        # Escape special characters in path for FFmpeg filter syntax
        # On Windows: C:\path -> C\\:/path (escape backslashes first, then colon)
        srt_str = str(srt_path.absolute())
        srt_str = srt_str.replace('\\', '/')
        srt_str = srt_str.replace(':', '\\:')

        # For GPU encoders, we need to ensure pixel format is compatible
        if encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
            # GPU encoders need specific pixel format
            video_filter = (
                f"subtitles='{srt_str}'"
                f":force_style='FontSize=24,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,Outline=2,MarginV=25',"
                f"format=yuv420p"
            )
        else:
            video_filter = (
                f"subtitles='{srt_str}'"
                f":force_style='FontSize=24,PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,Outline=2,MarginV=25'"
            )

        # Build FFmpeg command
        cmd = [
            ffmpeg_path,
            "-y",                    # Overwrite output
            "-i", str(video_path),   # Input video
            "-vf", video_filter,     # Video filter (subtitles + pixel format)
            "-c:v", encoder,         # Video encoder
            "-c:a", "aac",           # Audio codec
            "-b:a", "128k",          # Audio bitrate
        ]

        # Add encoder-specific settings
        if encoder == "libx264":
            cmd.extend(["-preset", "medium", "-crf", "23"])
        elif encoder == "h264_nvenc":
            cmd.extend(["-preset", "p4", "-rc", "vbr", "-cq", "23", "-b:v", "0"])
        elif encoder == "h264_qsv":
            cmd.extend(["-preset", "medium", "-global_quality", "23"])
        elif encoder == "h264_amf":
            cmd.extend(["-quality", "balanced", "-rc", "vbr_latency", "-qp_i", "23", "-qp_p", "23"])

        cmd.append(str(output_path))

        # Run FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            # If GPU encoder fails, try CPU fallback
            if encoder != "libx264":
                log(f"    GPU encoder failed, trying CPU fallback...")
                return convert_single(video_path, srt_path, output_path, ffmpeg_path, "libx264", log)

            return ConvertResult(
                success=False,
                video_file=video_path,
                srt_file=srt_path,
                error=f"FFmpeg error:  return code {result.returncode} ({result.stderr[-200:] if result.stderr else 'Unknown error'})"
            )

        if not output_path.exists():
            return ConvertResult(
                success=False,
                video_file=video_path,
                srt_file=srt_path,
                error="Output file not created"
            )

        return ConvertResult(
            success=True,
            video_file=video_path,
            output_file=output_path,
            srt_file=srt_path
        )

    except Exception as e:
        return ConvertResult(
            success=False,
            video_file=video_path,
            srt_file=srt_path,
            error=str(e)
        )


def convert_to_mp4(
    video_folder: Path,
    srt_folder: Path,
    output_folder: Path,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    skip_existing: bool = True,
    fix_rtl: bool = True
) -> Dict:
    """
    Convert all videos in a folder to MP4 with hard-burned Hebrew subtitles.

    Args:
        video_folder: Folder containing original video files
        srt_folder: Folder containing Hebrew SRT files
        output_folder: Folder for output MP4 files
        log: Optional logging callback
        progress: Optional progress callback (current, total)
        skip_existing: Skip conversion if output MP4 already exists
        fix_rtl: Fix RTL punctuation before burning (default: True)

    Returns:
        Dict with 'converted', 'failed', 'skipped', 'no_subtitle', 'output_folder', 'encoder', 'rtl_fixed'
    """
    if log is None:
        log = lambda x: None

    # Check FFmpeg availability
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        log("ERROR: FFmpeg not found!")
        log("Please install FFmpeg and ensure it's in your PATH")
        return {
            'converted': [],
            'failed': [("System", "FFmpeg not installed")],
            'skipped': [],
            'no_subtitle': [],
            'output_folder': output_folder,
            'encoder': None,
            'rtl_fixed': 0
        }

    # Fix RTL if needed (in case Stage 4 was skipped)
    rtl_fixed_count = 0
    if fix_rtl and srt_folder.exists():
        log("=== RTL Fix (if needed) ===")
        rtl_result = fix_rtl_folder(srt_folder, log=log)
        rtl_fixed_count = rtl_result.get('total_lines_fixed', 0)
        log("")

    # Detect best encoder
    log("=== Detecting encoder ===")
    encoder = detect_hw_encoder(ffmpeg_path, log=log)

    log("=== Converting to MP4 (hard-burned subs) ===")

    # Find video files
    video_files = sorted([
        f for f in video_folder.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_FORMATS
    ])

    if not video_files:
        log("No video files found")
        return {
            'converted': [],
            'failed': [],
            'skipped': [],
            'no_subtitle': [],
            'output_folder': output_folder,
            'encoder': encoder,
            'rtl_fixed': rtl_fixed_count
        }

    log(f"Found {len(video_files)} video files")

    # Check SRT folder exists
    if not srt_folder.exists():
        log(f"SRT folder not found: {srt_folder}")
        return {
            'converted': [],
            'failed': [],
            'skipped': [],
            'no_subtitle': [v.name for v in video_files],
            'output_folder': output_folder,
            'encoder': encoder,
            'rtl_fixed': rtl_fixed_count
        }

    # Match with SRTs
    matches = match_srt_to_video(video_files, srt_folder)

    matched_count = sum(1 for srt in matches.values() if srt is not None)
    log(f"Matched {matched_count}/{len(video_files)} with subtitles")

    # Create output folder
    output_folder.mkdir(parents=True, exist_ok=True)

    converted = []
    failed = []
    skipped = []
    no_subtitle = []

    for i, (video, srt) in enumerate(matches.items()):
        output_name = video.stem + ".mp4"
        output_path = output_folder / output_name

        if progress:
            progress(i + 1, len(video_files))

        # No subtitle for this file
        if srt is None:
            no_subtitle.append(video.name)
            log(f"  {video.name}: No matching SRT")
            continue

        # Verify SRT exists and has content
        if not srt.exists() or srt.stat().st_size < 50:
            no_subtitle.append(video.name)
            log(f"  {video.name}: SRT file empty or invalid")
            continue

        # Skip if output exists
        if skip_existing and output_path.exists():
            skipped.append(video.name)
            log(f"  {video.name}: Output exists, skipping")
            continue

        # Convert
        log(f"  {video.name} -> {output_name} [{encoder}]...")
        result = convert_single(video, srt, output_path, ffmpeg_path, encoder, log)

        if result.success:
            converted.append(result.output_file)
            log(f"  {video.name} -> {output_name}")
        else:
            failed.append((video.name, result.error))
            log(f"  {video.name}: {result.error}")

    log(f"\n=== MP4 Conversion Complete ===")
    log(f"Converted: {len(converted)}, Skipped: {len(skipped)}, Failed: {len(failed)}, No SRT: {len(no_subtitle)}")

    return {
        'converted': converted,
        'failed': failed,
        'skipped': skipped,
        'no_subtitle': no_subtitle,
        'output_folder': output_folder,
        'encoder': encoder,
        'rtl_fixed': rtl_fixed_count
    }
