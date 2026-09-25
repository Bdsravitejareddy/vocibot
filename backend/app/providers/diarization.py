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

    def diarize(self, chunk: AudioChunk) -> list[SpeakerTurn]:
        raise RuntimeError("PyannoteDiarizationProvider requires a configured local pyannote pipeline")
