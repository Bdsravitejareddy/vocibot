"""Consultation audio kept for compliance, retrieval and re-analysis."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import wave

import numpy as np

from ..config import settings


@dataclass(frozen=True)
class FinishedRecording:
    path: Path
    duration_ms: int
    sha256: str


class SessionRecorder:
    """Stream 16-bit mono PCM to a WAV file as audio arrives.

    Writing incrementally keeps memory flat and leaves a playable file even if
    the app stops mid-consultation (only the header length would be stale).
    """

    def __init__(self, path: Path, sample_rate: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.sample_rate = sample_rate
        self.frames = 0
        self._file = wave.open(str(path), "wb")
        self._file.setnchannels(1)
        self._file.setsampwidth(2)
        self._file.setframerate(sample_rate)

    def write(self, waveform: np.ndarray) -> None:
        samples = np.clip(np.asarray(waveform, dtype=np.float32).reshape(-1), -1.0, 1.0)
        self._file.writeframes((samples * 32767.0).astype("<i2").tobytes())
        self.frames += samples.size

    def close(self) -> FinishedRecording:
        self._file.close()
        return FinishedRecording(path=self.path, duration_ms=int(self.frames / self.sample_rate * 1000), sha256=file_sha256(self.path))


def recordings_dir() -> Path:
    return Path(settings.recordings_dir).expanduser()


def recording_path(session_code: str) -> Path:
    """A new file named by the session ID; later parts of one session get -2, -3."""

    directory = recordings_dir()
    candidate = directory / f"{session_code}.wav"
    part = 2
    while candidate.exists():
        candidate = directory / f"{session_code}-{part}.wav"
        part += 1
    return candidate


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_recording(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError(f"unsupported recording format: {path.name}")
        frames = handle.readframes(handle.getnframes())
        return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32767.0, handle.getframerate()
