"""Consultation audio kept for compliance, retrieval and re-analysis."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from pathlib import Path
import threading
import wave

import numpy as np

from ..config import settings

logger = logging.getLogger(__name__)


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
    samples, sample_rate = read_pcm16(path)
    return samples.astype(np.float32) / 32767.0, sample_rate


def read_pcm16(path: Path) -> tuple[np.ndarray, int]:
    """The exact 16-bit samples of a WAV or FLAC recording."""

    if path.suffix == ".wav":
        with wave.open(str(path), "rb") as handle:
            if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                raise ValueError(f"unsupported recording format: {path.name}")
            return np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2"), handle.getframerate()
    import soundfile as sf  # type: ignore[import-not-found]

    samples, sample_rate = sf.read(str(path), dtype="int16")
    return samples.reshape(-1), sample_rate


# ---------------------------------------------------------------------------
# Storage optimisation: WAV (capture) -> FLAC (lossless) -> Opus (after N days)
# ---------------------------------------------------------------------------

AUDIO_MEDIA_TYPES = {"wav": "audio/wav", "flac": "audio/flac", "opus": "audio/ogg"}
# Opus at libsndfile compression level 0.9 encodes 16 kHz speech at ~26 kbps;
# transcription accuracy on the benchmark recordings was unchanged.
OPUS_COMPRESSION_LEVEL = 0.9
_maintenance_lock = threading.Lock()


def read_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode a stored recording (WAV, FLAC or Opus) to mono float32."""

    if path.suffix == ".wav":
        return read_recording(path)
    import soundfile as sf  # type: ignore[import-not-found]

    waveform, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    return waveform.mean(axis=1), sample_rate


def convert_recording(recording_id: str, target: str) -> bool:
    """Convert one stored recording; the source is deleted only after the new file verifies."""

    import soundfile as sf  # type: ignore[import-not-found]

    from ..db import SessionLocal
    from ..models import Recording

    with SessionLocal() as session:
        recording = session.get(Recording, recording_id)
        if recording is None:
            return False
        source = Path(recording.file_path)
        if not source.is_file() or recording.format == target:
            return False
        if recording.sha256 and file_sha256(source) != recording.sha256:
            logger.error("Recording %s does not match its fingerprint; not converting it", source.name)
            return False
        if target == "flac":
            # Encode the captured 16-bit samples directly (no float round
            # trip) and require the FLAC to decode to exactly the same samples.
            samples, sample_rate = read_pcm16(source)
            destination = source.with_suffix(".flac")
            sf.write(str(destination), samples, sample_rate, format="FLAC", subtype="PCM_16")
            decoded, _ = sf.read(str(destination), dtype="int16")
            if not np.array_equal(decoded.reshape(-1), samples):
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"FLAC verification failed for {source.name}")
        elif target == "opus":
            waveform, sample_rate = read_audio(source)
            destination = source.with_suffix(".ogg")
            sf.write(str(destination), waveform, sample_rate, format="OGG", subtype="OPUS", compression_level=OPUS_COMPRESSION_LEVEL)
            decoded, _ = sf.read(str(destination), dtype="float32")
            if abs(len(decoded) - len(waveform)) > sample_rate:
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"Opus verification failed for {source.name}")
        else:
            raise ValueError(f"unsupported recording format: {target}")
        if recording.original_sha256 is None and recording.format == "wav":
            recording.original_sha256 = recording.sha256
        recording.file_path = str(destination)
        recording.format = target
        recording.sha256 = file_sha256(destination)
        recording.size_bytes = destination.stat().st_size
        session.commit()
        source.unlink(missing_ok=True)
        logger.info("Recording %s stored as %s (%d bytes)", destination.name, target, recording.size_bytes)
        return True


def maintain_recordings(now: datetime | None = None) -> dict[str, int]:
    """Compress finished captures to FLAC and shrink old FLAC to Opus."""

    from sqlalchemy import select

    from ..db import SessionLocal
    from ..models import Recording

    counts = {"flac": 0, "opus": 0, "failed": 0}
    if not _maintenance_lock.acquire(blocking=False):
        return counts
    try:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=settings.recording_opus_after_days)
        with SessionLocal() as session:
            pending = [(item.id, "flac") for item in session.scalars(select(Recording).where(Recording.format == "wav", Recording.sha256.is_not(None)))]
            if settings.recording_opus_after_days > 0:
                pending += [(item.id, "opus") for item in session.scalars(select(Recording).where(Recording.format == "flac")) if _aware(item.started_at) <= cutoff]
        for recording_id, target in pending:
            try:
                if convert_recording(recording_id, target):
                    counts[target] += 1
            except Exception:
                counts["failed"] += 1
                logger.exception("Converting recording %s to %s failed", recording_id, target)
    finally:
        _maintenance_lock.release()
    return counts


def start_recording_maintenance() -> threading.Event:
    """Run maintenance now and then periodically on a daemon thread."""

    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                maintain_recordings()
            except Exception:
                logger.exception("Recording maintenance failed")
            stop.wait(settings.recording_maintenance_interval_hours * 3600)

    threading.Thread(target=loop, name="vocibot-recording-maintenance", daemon=True).start()
    return stop


def compress_soon() -> None:
    """Compress a just-finished capture without blocking the request."""

    threading.Thread(target=maintain_recordings, name="vocibot-recording-compress", daemon=True).start()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
