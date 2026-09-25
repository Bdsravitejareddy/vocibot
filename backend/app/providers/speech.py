from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioChunk:
    audio: bytes
    sample_rate: int
    timestamp_ms: int


@dataclass(frozen=True)
class TranscriptDraft:
    text: str
    timestamp: str
    speaker: str = "UNKNOWN"
    start_ms: int | None = None
    end_ms: int | None = None


class SpeechToTextProvider(Protocol):
    def transcribe_chunk(self, chunk: AudioChunk) -> list[TranscriptDraft]:
        ...


class DemoSpeechToTextProvider:
    def transcribe_chunk(self, chunk: AudioChunk) -> list[TranscriptDraft]:
        return []


class FasterWhisperProvider:
    """Lazy-loaded faster-whisper adapter; model size is configurable for local hardware."""

    def __init__(self, model_size: str = "large-v3", device: str = "auto", compute_type: str = "int8") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe_chunk(self, chunk: AudioChunk) -> list[TranscriptDraft]:
        raise RuntimeError("FasterWhisperProvider requires a local audio decoder and faster-whisper extras")
