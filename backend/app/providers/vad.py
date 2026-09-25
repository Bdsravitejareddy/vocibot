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

    def has_speech(self, chunk: AudioChunk) -> bool:
        raise RuntimeError("SileroVoiceActivityDetector requires the local silero-vad extra")
