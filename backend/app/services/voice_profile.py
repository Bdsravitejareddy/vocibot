"""Doctor voice profiles: is this stretch of the consultation the doctor?

The doctor reads a few prompted sentences once (enrolment). Each is turned
into a voice fingerprint (a 192-number ECAPA-TDNN speaker embedding,
SpeechBrain ``spkrec-ecapa-voxceleb``, Apache-2.0); the profile is their
average plus a threshold set from how alike the doctor's own samples are.
After a consultation each transcript line's audio is compared with the
profile: close enough is the doctor, anything else (patient, relative,
attendant) is not.

The model is built from SpeechBrain's modules and the downloaded weights
directly, so nothing is fetched at run time.
"""

from __future__ import annotations

from pathlib import Path
import threading

import numpy as np

SAMPLE_RATE = 16_000
# Shorter audio gives an unreliable fingerprint ("Yes.", "Hmm").
MIN_SECONDS = 1.0


class VoiceEncoder:
    def __init__(self, model_dir: str | Path) -> None:
        self.model_dir = Path(model_dir)
        self._lock = threading.Lock()
        self._modules = None

    def available(self) -> bool:
        return (self.model_dir / "embedding_model.ckpt").is_file()

    def _load(self):
        with self._lock:
            if self._modules is None:
                import torch  # type: ignore[import-not-found]
                from speechbrain.lobes.features import Fbank  # type: ignore[import-not-found]
                from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN  # type: ignore[import-not-found]
                from speechbrain.processing.features import InputNormalization  # type: ignore[import-not-found]

                model = ECAPA_TDNN(input_size=80, channels=[1024, 1024, 1024, 1024, 3072], kernel_sizes=[5, 3, 3, 3, 1], dilations=[1, 2, 3, 4, 1], attention_channels=128, lin_neurons=192)
                model.load_state_dict(torch.load(self.model_dir / "embedding_model.ckpt", map_location="cpu"))
                model.eval()
                self._modules = (torch, Fbank(n_mels=80), InputNormalization(norm_type="sentence", std_norm=False), model)
            return self._modules

    def speech_only(self, audio: np.ndarray) -> np.ndarray:
        """The speech in ``audio`` with pauses and background removed (Silero
        VAD): silence makes a poor fingerprint."""

        torch = self._load()[0]
        with self._lock:
            if getattr(self, "_vad", None) is None:
                from silero_vad import load_silero_vad  # type: ignore[import-not-found]

                self._vad = load_silero_vad()
        from silero_vad import get_speech_timestamps  # type: ignore[import-not-found]

        wave = torch.tensor(np.asarray(audio, dtype=np.float32))
        spans = get_speech_timestamps(wave, self._vad, sampling_rate=SAMPLE_RATE, min_speech_duration_ms=200)
        return np.concatenate([audio[span["start"]:span["end"]] for span in spans]) if spans else np.empty(0, dtype=np.float32)

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """Unit-length voice fingerprint of 16 kHz mono audio."""

        if len(audio) < 0.5 * SAMPLE_RATE:
            raise ValueError("too little speech for a voice fingerprint")
        torch, features, normalise, model = self._load()
        with torch.inference_mode():
            wave = torch.tensor(np.asarray(audio, dtype=np.float32).reshape(1, -1))
            feats = normalise(features(wave), torch.ones(1))
            vector = model(feats).squeeze().numpy().astype(np.float64)
        return vector / (np.linalg.norm(vector) or 1.0)


# How alike two fingerprints of the same voice are depends on the microphone
# and sentence length, so the threshold comes from the doctor's own samples:
# their typical similarity to each other, less a margin, within limits.
# The margin is wide because enrolment samples are recorded together: on the
# clinic's recordings the same voice scored ~0.8 within a session but ~0.57
# in another session, while other voices scored at most 0.47 (most < 0.2).
THRESHOLD_MARGIN = 0.30
THRESHOLD_RANGE = (0.40, 0.55)
# Below threshold minus this, the line is clearly someone else; in between,
# the voice is not trusted and the content decides.
UNSURE_BAND = 0.10
MIN_SAMPLES = 5


def build_profile(fingerprints: list[np.ndarray]) -> dict:
    """Average voice and threshold from enrolment fingerprints.

    Each sample is compared with the average of the others; a sample far
    from the rest (noise, a different reader) is reported so it can be
    recorded again.
    """

    if len(fingerprints) < MIN_SAMPLES:
        raise ValueError(f"Record at least {MIN_SAMPLES} sentences.")
    stacked = np.stack(fingerprints)
    leave_one_out = []
    for index in range(len(stacked)):
        others = np.delete(stacked, index, axis=0).mean(axis=0)
        leave_one_out.append(float(stacked[index] @ (others / np.linalg.norm(others))))
    centre = stacked.mean(axis=0)
    centre /= np.linalg.norm(centre)
    typical = float(np.median(leave_one_out))
    threshold = float(np.clip(typical - THRESHOLD_MARGIN, *THRESHOLD_RANGE))
    return {
        "embedding": [round(float(value), 6) for value in centre],
        "threshold": round(threshold, 3),
        "sample_scores": [round(score, 3) for score in leave_one_out],
        # Far from the doctor's other samples: noise or another voice.
        "outliers": [index for index, score in enumerate(leave_one_out) if score < typical - 0.25],
    }


def judge(similarity: float, threshold: float) -> str | None:
    """DOCTOR, PATIENT (anyone else), or None when the voice is not conclusive."""

    if similarity >= threshold:
        return "DOCTOR"
    if similarity < threshold - UNSURE_BAND:
        return "PATIENT"
    return None


def best_match(fingerprint: np.ndarray, profiles: list[dict]) -> tuple[float, float]:
    """(similarity, threshold) of the closest enrolled doctor."""

    scored = [(float(fingerprint @ np.asarray(profile["embedding"])), float(profile["threshold"])) for profile in profiles]
    return max(scored, key=lambda item: item[0] - item[1]) if scored else (0.0, 1.0)


PROFILES_KEY = "voice_profiles"


def stored_profiles(session) -> list[dict]:
    from ..models import AppSetting

    row = session.get(AppSetting, PROFILES_KEY)
    return list(row.value) if row and isinstance(row.value, list) else []


def load_recording(path: str):
    """A consultation recording as 16 kHz mono float32, or None."""

    try:
        import soundfile  # type: ignore[import-not-found]

        audio, rate = soundfile.read(path, dtype="float32", always_2d=True)
    except Exception:
        return None
    audio = audio.mean(axis=1)
    if rate != SAMPLE_RATE:
        from math import gcd

        from scipy.signal import resample_poly  # type: ignore[import-not-found]

        divisor = gcd(rate, SAMPLE_RATE)
        audio = resample_poly(audio, SAMPLE_RATE // divisor, rate // divisor).astype(np.float32)
    return audio


# Longest stretch of a line that is fingerprinted (long lines: the start).
MAX_LINE_SECONDS = 12.0


def voice_labels(audio: np.ndarray, starts: list[float | None], profiles: list[dict], encoder: VoiceEncoder) -> list[str | None]:
    """DOCTOR / PATIENT per line from its voice, None where not conclusive.

    A line runs from its start to the next line's start.
    """

    labels: list[str | None] = []
    duration = len(audio) / SAMPLE_RATE
    for index, start in enumerate(starts):
        following = next((value for value in starts[index + 1:] if value is not None and start is not None and value > start), None)
        if start is None:
            labels.append(None)
            continue
        end = min(following if following is not None else duration, start + MAX_LINE_SECONDS, duration)
        piece = encoder.speech_only(audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)])
        if len(piece) < MIN_SECONDS * SAMPLE_RATE:
            labels.append(None)
            continue
        similarity, threshold = best_match(encoder.embed(piece), profiles)
        labels.append(judge(similarity, threshold))
    return labels
