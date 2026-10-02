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
    frame_count: int = 0
    speech_frame_count: int = 0
    speech_duration_ms: float = 0.0


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

    def warmup(self) -> None:
        """Load and exercise the local VAD model before microphone capture begins."""

        import numpy as np  # type: ignore[import-not-found]

        self.detect(
            AudioChunk(
                audio=b"",
                sample_rate=16_000,
                timestamp_ms=0,
                waveform=np.zeros(8_000, dtype=np.float32),
            )
        )

    def detect(self, chunk: AudioChunk) -> ActivityResult:
        started = perf_counter()
        model = self._load()
        import numpy as np  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]

        if chunk.waveform is None:
            from .audio import decode_audio_payload

            waveform = decode_audio_payload(
                chunk.audio,
                encoding=chunk.encoding,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels,
            ).waveform
            sample_rate = 16_000
        else:
            waveform = np.asarray(chunk.waveform, dtype=np.float32)
            sample_rate = chunk.sample_rate

        audio = torch.from_numpy(np.ascontiguousarray(waveform, dtype=np.float32))
        frame_size = 512 if sample_rate == 16_000 else 256
        probabilities = []
        for start in range(0, audio.numel(), frame_size):
            frame = audio[start:start + frame_size]
            if frame.numel() < frame_size:
                frame = torch.nn.functional.pad(frame, (0, frame_size - frame.numel()))
            probabilities.append(float(model(frame, sample_rate).item()))
        confidence = max(probabilities, default=0.0)
        speech_frame_count = sum(probability >= self.threshold for probability in probabilities)
        speech_duration_ms = speech_frame_count * frame_size / sample_rate * 1000
        return ActivityResult(
            probability=confidence,
            has_speech=confidence >= self.threshold,
            latency_ms=(perf_counter() - started) * 1000,
            frame_count=len(probabilities),
            speech_frame_count=speech_frame_count,
            speech_duration_ms=speech_duration_ms,
        )


class OnnxSileroVoiceActivityDetector(SileroVoiceActivityDetector):
    """The Silero VAD shipped with faster-whisper, run through ONNX Runtime.

    Same decisions as the PyTorch build without loading PyTorch: roughly
    700 MB less to install and ~300 MB less memory, which matters on small
    Windows machines.
    """

    def _load(self):
        if self._model is None:
            from faster_whisper.vad import get_vad_model  # type: ignore[import-not-found]

            self._model = get_vad_model()
        return self._model

    def detect(self, chunk: AudioChunk) -> ActivityResult:
        started = perf_counter()
        model = self._load()
        import numpy as np  # type: ignore[import-not-found]

        if chunk.waveform is None:
            from .audio import decode_audio_payload

            waveform = decode_audio_payload(chunk.audio, encoding=chunk.encoding, sample_rate=chunk.sample_rate, channels=chunk.channels).waveform
        else:
            waveform = np.asarray(chunk.waveform, dtype=np.float32).reshape(-1)
        frame_size = 512
        padded = np.pad(waveform, (0, (-len(waveform)) % frame_size)) if len(waveform) else np.zeros(frame_size, dtype=np.float32)
        probabilities = np.asarray(model(np.ascontiguousarray(padded, dtype=np.float32)), dtype=np.float32).reshape(-1)
        confidence = float(probabilities.max(initial=0.0))
        speech_frame_count = int((probabilities >= self.threshold).sum())
        return ActivityResult(
            probability=confidence,
            has_speech=confidence >= self.threshold,
            latency_ms=(perf_counter() - started) * 1000,
            frame_count=int(probabilities.size),
            speech_frame_count=speech_frame_count,
            speech_duration_ms=speech_frame_count * frame_size / 16_000 * 1000,
        )
