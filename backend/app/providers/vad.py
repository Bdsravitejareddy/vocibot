from typing import Protocol

from .speech import AudioChunk


class VoiceActivityDetector(Protocol):
    def has_speech(self, chunk: AudioChunk) -> bool:
        ...


class DemoVoiceActivityDetector:
    def has_speech(self, chunk: AudioChunk) -> bool:
        return bool(chunk.audio)


class SileroVoiceActivityDetector:
    """Lazy-loaded Silero VAD seam; audio preprocessing remains local to the backend."""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self._model = None

    def _load(self):
        if self._model is None:
            from silero_vad import load_silero_vad  # type: ignore[import-not-found]
            self._model = load_silero_vad()
        return self._model

    def has_speech(self, chunk: AudioChunk) -> bool:
        import numpy as np  # type: ignore[import-not-found]

        model = self._load()
        audio = np.frombuffer(chunk.audio, dtype=np.float32)
        confidence = float(model(audio, chunk.sample_rate).item())
        return confidence >= self.threshold
