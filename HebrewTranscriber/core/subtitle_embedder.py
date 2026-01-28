"""
Subtitle Embedder - Embed Hebrew subtitles into video files.

Uses mkvmerge (from MKVToolNix) to add Hebrew subtitle track to videos.
Supports MP4/MKV input, outputs MKV with embedded Hebrew subtitles.
Includes automatic RTL fixing for Hebrew subtitles.
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass

from core.rtl_fixer import fix_rtl_folder, fix_rtl_file


# Supported video formats
VIDEO_FORMATS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.wmv'}


@dataclass
class EmbedResult:
    """Result of embedding a subtitle."""
    success: bool
    video_file: Path
    output_file: Optional[Path] = None
    srt_file: Optional[Path] = None
    error: Optional[str] = None


def find_mkvmerge() -> Optional[Path]:
    """Find mkvmerge executable."""
    path = shutil.which("mkvmerge")
    if path:
        return Path(path)

    common_paths = [
        Path("C:/Program Files/MKVToolNix/mkvmerge.exe"),
        Path("C:/Program Files (x86)/MKVToolNix/mkvmerge.exe"),
    ]
    for p in common_paths:
        if p.exists():
            return p

    return None


def is_mkvmerge_available() -> bool:
    """Check if mkvmerge is available."""
    return find_mkvmerge() is not None


def match_srt_to_video(video_files: List[Path], srt_folder: Path) -> Dict[Path, Optional[Path]]:
    """
    Match SRT files to video files by filename stem.

    Returns dict mapping video path to SRT path (or None if no match).
    """
    srt_files = list(srt_folder.glob("*.srt"))
    srt_by_stem = {srt.stem.lower(): srt for srt in srt_files}

    matches = {}
    for video in video_files:
        video_stem = video.stem.lower()

        # Try exact match first
        if video_stem in srt_by_stem:
            matches[video] = srt_by_stem[video_stem]
            continue

        # Try partial match (video stem contains SRT stem or vice versa)
        matched = None
        for srt_stem, srt_path in srt_by_stem.items():
            if srt_stem in video_stem or video_stem in srt_stem:
                matched = srt_path
                break

        matches[video] = matched

    return matches


def embed_single(
    video_path: Path,
    srt_path: Path,
    output_path: Path,
    language: str = "heb",
    track_name: str = "Hebrew",
    default_track: bool = True,
    log: Optional[Callable[[str], None]] = None
) -> EmbedResult:
    """
    Embed a subtitle into a video file.

    Args:
        video_path: Input video file (MP4, MKV, etc.)
        srt_path: Hebrew SRT file to embed
        output_path: Output MKV file
        language: Language code (default: heb)
        track_name: Track name (default: Hebrew)
        default_track: Set as default subtitle (default: True)
        log: Optional logging callback

    Returns:
        EmbedResult
    """
    if log is None:
        log = lambda x: None

    try:
        mkvmerge = find_mkvmerge()
        if not mkvmerge:
            return EmbedResult(
                success=False,
                video_file=video_path,
                srt_file=srt_path,
                error="mkvmerge not found. Install MKVToolNix from https://mkvtoolnix.download/"
            )

        # Ensure output has .mkv extension
        if output_path.suffix.lower() != '.mkv':
            output_path = output_path.with_suffix('.mkv')

        # Build command
        cmd = [
            str(mkvmerge),
            "-o", str(output_path),
            str(video_path),
            "--language", f"0:{language}",
            "--track-name", f"0:{track_name}",
        ]

        if default_track:
            cmd.extend(["--default-track", "0:yes"])

        cmd.append(str(srt_path))

        # Run mkvmerge
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        # mkvmerge returns 0 for success, 1 for warnings (still success), 2+ for errors
        if result.returncode > 1:
            return EmbedResult(
                success=False,
                video_file=video_path,
                srt_file=srt_path,
                error=f"mkvmerge failed: {result.stderr[:200]}"
            )

        if not output_path.exists():
            return EmbedResult(
                success=False,
                video_file=video_path,
                srt_file=srt_path,
                error="Output file not created"
            )

        return EmbedResult(
            success=True,
            video_file=video_path,
            output_file=output_path,
            srt_file=srt_path
        )

    except Exception as e:
        return EmbedResult(
            success=False,
            video_file=video_path,
            srt_file=srt_path,
            error=str(e)
        )


def embed_subtitles(
    video_folder: Path,
    srt_folder: Path,
    output_folder: Path,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    skip_existing: bool = True,
    fix_rtl: bool = True
) -> Dict:
    """
    Embed Hebrew subtitles into all video files.

    Args:
        video_folder: Folder containing video files
        srt_folder: Folder containing Hebrew SRT files
        output_folder: Folder for output MKV files
        log: Optional logging callback
        progress: Optional progress callback (current, total)
        skip_existing: Skip embedding if output MKV already exists
        fix_rtl: Fix RTL punctuation before embedding (default: True)

    Returns:
        Dict with 'embedded', 'failed', 'skipped', 'no_subtitle', 'output_folder', 'rtl_fixed'
    """
    if log is None:
        log = lambda x: None

    # Check mkvmerge availability
    if not is_mkvmerge_available():
        log("ERROR: MKVToolNix not found!")
        log("Please install from: https://mkvtoolnix.download/")
        return {
            'embedded': [],
            'failed': [("System", "MKVToolNix not installed")],
            'skipped': [],
            'no_subtitle': [],
            'output_folder': output_folder,
            'rtl_fixed': 0
        }

    # Step 1: Fix RTL in SRT files before embedding
    rtl_fixed_count = 0
    if fix_rtl and srt_folder.exists():
        log("=== Step 1: RTL Fix ===")
        rtl_result = fix_rtl_folder(srt_folder, log=log)
        rtl_fixed_count = rtl_result.get('total_lines_fixed', 0)
        log("")

    log("=== Step 2: Subtitle Embedding ===")

    # Find video files
    video_files = sorted([
        f for f in video_folder.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_FORMATS
    ])

    if not video_files:
        log("No video files found")
        return {
            'embedded': [],
            'failed': [],
            'skipped': [],
            'no_subtitle': [],
            'output_folder': output_folder
        }

    log(f"Found {len(video_files)} video files")

    # Check SRT folder exists
    if not srt_folder.exists():
        log(f"SRT folder not found: {srt_folder}")
        return {
            'embedded': [],
            'failed': [],
            'skipped': [],
            'no_subtitle': [v.name for v in video_files],
            'output_folder': output_folder
        }

    # Match with SRTs
    matches = match_srt_to_video(video_files, srt_folder)

    matched_count = sum(1 for srt in matches.values() if srt is not None)
    log(f"Matched {matched_count}/{len(video_files)} with subtitles")

    # Create output folder
    output_folder.mkdir(parents=True, exist_ok=True)

    embedded = []
    failed = []
    skipped = []
    no_subtitle = []

    for i, (video, srt) in enumerate(matches.items()):
        # Output filename (same name but .mkv extension)
        output_name = video.stem + ".mkv"
        output_path = output_folder / output_name

        if progress:
            progress(i + 1, len(video_files))

        # No subtitle for this file
        if srt is None:
            no_subtitle.append(video.name)
            log(f"⚠ {video.name}: No matching SRT")
            continue

        # Verify SRT exists and has content
        if not srt.exists() or srt.stat().st_size < 50:
            no_subtitle.append(video.name)
            log(f"⚠ {video.name}: SRT file empty or invalid")
            continue

        # Skip if output exists
        if skip_existing and output_path.exists():
            skipped.append(video.name)
            log(f"⏭ {video.name}: Output exists")
            continue

        # Embed
        log(f"📝 {video.name}...")
        result = embed_single(video, srt, output_path)

        if result.success:
            embedded.append(result.output_file)
            log(f"✓ {video.name} → {output_name}")
        else:
            failed.append((video.name, result.error))
            log(f"✗ {video.name}: {result.error}")

    log(f"\n=== Complete ===")
    log(f"Embedded: {len(embedded)}, Skipped: {len(skipped)}, Failed: {len(failed)}, No SRT: {len(no_subtitle)}")
    if rtl_fixed_count > 0:
        log(f"RTL lines fixed: {rtl_fixed_count}")

    return {
        'embedded': embedded,
        'failed': failed,
        'skipped': skipped,
        'no_subtitle': no_subtitle,
        'output_folder': output_folder,
        'rtl_fixed': rtl_fixed_count
    }
