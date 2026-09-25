from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from .speech import AudioChunk


class VoiceActivityDetector(Protocol):
    def detect(self, chunk: AudioChunk) -> "ActivityResult":
        ...

    def has_speech(self, chunk: AudioChunk) -> bool:
        ...


@dataclass(frozen=True)
class ActivityResult:
    probability: float
    has_speech: bool
    latency_ms: float


class DemoVoiceActivityDetector:
    def detect(self, chunk: AudioChunk) -> ActivityResult:
        return ActivityResult(probability=1.0 if chunk.audio else 0.0, has_speech=bool(chunk.audio), latency_ms=0.0)

    def has_speech(self, chunk: AudioChunk) -> bool:
        return self.detect(chunk).has_speech


class SileroVoiceActivityDetector:
    """Lazy-loaded Silero VAD seam; audio preprocessing remains local to the backend."""

    def __init__(self, threshold: float = 0.5, model=None) -> None:
        self.threshold = threshold
        self._model = model

    def _load(self):
        if self._model is None:
            from silero_vad import load_silero_vad  # type: ignore[import-not-found]
            self._model = load_silero_vad()
        return self._model

    def has_speech(self, chunk: AudioChunk) -> bool:
        return self.detect(chunk).has_speech

    def detect(self, chunk: AudioChunk) -> ActivityResult:
        started = perf_counter()
        injected_model = self._model is not None
        model = self._load()
        if injected_model:
            audio = chunk.audio
        else:
            import numpy as np  # type: ignore[import-not-found]
            import torch  # type: ignore[import-not-found]
            audio = torch.from_numpy(np.frombuffer(chunk.audio, dtype=np.float32).copy())
        if injected_model:
            confidence = float(model(audio, chunk.sample_rate).item())
        else:
            frame_size = 512 if chunk.sample_rate == 16_000 else 256
            probabilities = [float(model(audio[start:start + frame_size], chunk.sample_rate).item()) for start in range(0, len(audio) - frame_size + 1, frame_size)]
            confidence = max(probabilities, default=0.0)
        return ActivityResult(probability=confidence, has_speech=confidence >= self.threshold, latency_ms=(perf_counter() - started) * 1000)
