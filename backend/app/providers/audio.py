"""Decode browser audio into the waveform contract used by local models."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np


class AudioDecodeError(ValueError):
    """Raised when an audio payload cannot be decoded safely."""


@dataclass(frozen=True)
class DecodedAudio:
    waveform: np.ndarray
    sample_rate: int
    source_sample_rate: int
    source_channels: int
    encoding: str


def audio_metrics(waveform: np.ndarray, *, sample_rate: int, silence_threshold: float = 0.01) -> dict[str, float]:
    """Return audibility diagnostics for a decoded mono waveform."""

    samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return {"duration_ms": 0.0, "rms": 0.0, "peak": 0.0, "clipping_percent": 0.0, "silence_percent": 100.0}
    return {
        "duration_ms": samples.size / sample_rate * 1000.0,
        "rms": float(np.sqrt(np.mean(np.square(samples), dtype=np.float64))),
        "peak": float(np.max(np.abs(samples))),
        "clipping_percent": float(np.mean(np.abs(samples) >= 0.999) * 100.0),
        "silence_percent": float(np.mean(np.abs(samples) < silence_threshold) * 100.0),
    }


def save_debug_wav(path: Path, payload: bytes, *, encoding: str, sample_rate: int, channels: int) -> DecodedAudio:
    """Decode one received stream payload and persist a playable diagnostic WAV."""

    decoded = decode_audio_payload(
        payload,
        encoding=encoding,
        sample_rate=sample_rate,
        channels=channels,
        target_sample_rate=sample_rate,
    )
    try:
        import soundfile as sf  # type: ignore[import-not-found]

        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), decoded.waveform, decoded.sample_rate, subtype="PCM_16")
    except Exception as error:
        raise AudioDecodeError(f"Unable to persist debug WAV: {error}") from error
    return decoded


def decode_audio_payload(
    payload: bytes,
    *,
    encoding: str,
    sample_rate: int,
    channels: int,
    target_sample_rate: int = 16_000,
) -> DecodedAudio:
    """Decode an explicitly-described payload and return mono float32 audio.

    The current browser provider uses a ScriptProcessorNode, so its payload is
    raw little-endian Float32 PCM. Container payloads are intentionally handled
    separately through soundfile; raw bytes are never passed to a model.
    """

    if not payload:
        raise AudioDecodeError("Audio payload is empty")
    if sample_rate <= 0:
        raise AudioDecodeError(f"Invalid source sample rate: {sample_rate}")
    if channels <= 0:
        raise AudioDecodeError(f"Invalid channel count: {channels}")

    normalized_encoding = encoding.lower().strip()
    if normalized_encoding in {"pcm_f32le", "audio/raw;encoding=pcm_f32le"}:
        item_size = np.dtype("<f4").itemsize
        if len(payload) % (item_size * channels):
            raise AudioDecodeError("Float32 PCM payload is not aligned to its channel count")
        samples = np.frombuffer(payload, dtype="<f4").copy()
        source_rate = sample_rate
        source_channels = channels
    elif normalized_encoding in {"pcm_s16le", "audio/raw;encoding=pcm_s16le"}:
        item_size = np.dtype("<i2").itemsize
        if len(payload) % (item_size * channels):
            raise AudioDecodeError("Int16 PCM payload is not aligned to its channel count")
        samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        source_rate = sample_rate
        source_channels = channels
    elif normalized_encoding.startswith("audio/") or payload[:4] == b"RIFF":
        try:
            import soundfile as sf  # type: ignore[import-not-found]

            samples, source_rate = sf.read(BytesIO(payload), dtype="float32", always_2d=True)
        except Exception as error:
            raise AudioDecodeError(
                f"Unable to decode {encoding} audio container; install a decoder for this format: {error}"
            ) from error
        source_channels = int(samples.shape[1]) if samples.ndim == 2 else 1
        samples = np.asarray(samples, dtype=np.float32)
    else:
        raise AudioDecodeError(f"Unsupported audio encoding: {encoding}")

    if samples.ndim == 1:
        if samples.size % source_channels:
            raise AudioDecodeError("Decoded audio is not aligned to its channel count")
        samples = samples.reshape(-1, source_channels)
    if samples.size == 0:
        raise AudioDecodeError("Decoded audio contains no samples")

    mono = np.asarray(samples, dtype=np.float32).reshape(-1, source_channels).mean(axis=1)
    waveform = _resample(mono, int(source_rate), target_sample_rate)
    return DecodedAudio(
        waveform=np.ascontiguousarray(waveform, dtype=np.float32),
        sample_rate=target_sample_rate,
        source_sample_rate=int(source_rate),
        source_channels=source_channels,
        encoding=normalized_encoding,
    )


def _resample(waveform: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return waveform.astype(np.float32, copy=False)
    try:
        from scipy.signal import resample_poly  # type: ignore[import-not-found]

        from math import gcd

        divisor = gcd(source_rate, target_rate)
        return np.asarray(resample_poly(waveform, target_rate // divisor, source_rate // divisor), dtype=np.float32)
    except ImportError:
        target_size = max(1, round(waveform.size * target_rate / source_rate))
        source_positions = np.linspace(0.0, 1.0, waveform.size, endpoint=False)
        target_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
        return np.asarray(np.interp(target_positions, source_positions, waveform), dtype=np.float32)
