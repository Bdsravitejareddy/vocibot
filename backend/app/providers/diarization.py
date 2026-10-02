from dataclasses import dataclass
from typing import Protocol

from .speech import AudioChunk


@dataclass(frozen=True)
class SpeakerTurn:
    speaker: str
    start_ms: int
    end_ms: int


class DiarizationProvider(Protocol):
    def diarize(self, chunk: AudioChunk) -> list[SpeakerTurn]:
        ...


class DemoDiarizationProvider:
    def diarize(self, chunk: AudioChunk) -> list[SpeakerTurn]:
        return []


class PyannoteDiarizationProvider:
    """Local pyannote-compatible seam; diarization stays optional for the MVP."""

    def __init__(self, pipeline=None, speaker_map: dict[str, str] | None = None, model_name: str = "pyannote/speaker-diarization-3.1") -> None:
        self._pipeline = pipeline
        self.speaker_map = speaker_map or {}
        self.model_name = model_name

    def _load(self):
        if self._pipeline is None:
            try:
                from pyannote.audio import Pipeline  # type: ignore[import-not-found]
                self._pipeline = Pipeline.from_pretrained(self.model_name)
            except Exception as error:
                raise RuntimeError(f"pyannote model/dependency unavailable ({self.model_name}): {error}") from error
        return self._pipeline

    def diarize(self, audio: bytes, sample_rate: int) -> list[SpeakerTurn]:
        annotation = self._load()({"waveform": audio, "sample_rate": sample_rate})
        return [SpeakerTurn(speaker=self.speaker_map.get(label, "UNKNOWN"), start_ms=int(turn.start * 1000), end_ms=int(turn.end * 1000)) for turn, _, label in annotation.itertracks(yield_label=True)]
