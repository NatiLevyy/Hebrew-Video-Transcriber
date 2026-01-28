from faster_whisper import WhisperModel
from typing import Callable, Optional, List, Dict
import torch

class HebrewTranscriber:
    """
    Hebrew transcription using ivrit-ai fine-tuned Whisper model.
    Automatically selects GPU if available, falls back to CPU.
    """

    MODEL_ID = "ivrit-ai/whisper-large-v3-turbo-ct2"

    def __init__(self):
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.compute_type = "float16" if self.device == "cuda" else "int8"

    def load_model(self, progress_callback: Optional[Callable] = None):
        """Load the model. Call this before transcribe()."""
        if progress_callback:
            progress_callback("Loading ivrit-ai model...")

        self.model = WhisperModel(
            self.MODEL_ID,
            device=self.device,
            compute_type=self.compute_type
        )

        if progress_callback:
            progress_callback(f"Model loaded on {self.device.upper()}")

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> List[Dict]:
        """
        Transcribe audio file to Hebrew text with timestamps.

        Args:
            audio_path: Path to audio file (WAV recommended)
            progress_callback: Function receiving progress 0-100

        Returns:
            List of segments: [{"start": float, "end": float, "text": str}, ...]
        """
        if self.model is None:
            self.load_model()

        segments, info = self.model.transcribe(
            audio_path,
            language="he",
            task="transcribe",
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200
            ),
            word_timestamps=False
        )

        results = []
        total_duration = info.duration

        for segment in segments:
            results.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip()
            })

            if progress_callback and total_duration > 0:
                progress = min(100, (segment.end / total_duration) * 100)
                progress_callback(progress)

        return results
