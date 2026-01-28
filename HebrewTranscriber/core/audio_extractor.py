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
