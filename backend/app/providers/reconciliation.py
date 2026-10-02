from dataclasses import dataclass, field, replace
from time import perf_counter

import numpy as np

from .speech import AudioChunk, SpeechToTextProvider, TranscriptDraft


@dataclass
class ReconciliationResult:
    transcripts: list[TranscriptDraft] = field(default_factory=list)
    latency_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


class FinalReconciler:
    """Run one authoritative ASR pass over the complete captured waveform."""

    def run(self, waveform: np.ndarray, stt: SpeechToTextProvider, *, sample_rate: int, language: str | None = None) -> ReconciliationResult:
        started = perf_counter()
        audio = np.asarray(waveform, dtype=np.float32).reshape(-1)
        duration_ms = int(len(audio) / sample_rate * 1000)
        drafts = stt.transcribe_chunk(AudioChunk(audio=b"", sample_rate=sample_rate, timestamp_ms=0, encoding="pcm_f32le", channels=1, waveform=audio), language=language)
        accepted: list[TranscriptDraft] = []
        warnings: list[str] = []
        for draft in drafts:
            if draft.start_ms is not None and draft.end_ms is not None and 0 <= draft.start_ms < duration_ms < draft.end_ms:
                # Whisper pads a segment cut off by Stop past the end of the
                # audio; keep the words and clamp the bound.
                draft = replace(draft, end_ms=duration_ms)
            if draft.start_ms is None or draft.end_ms is None or not 0 <= draft.start_ms <= draft.end_ms <= duration_ms:
                warnings.append(f"Rejected final transcript timestamp {draft.start_ms}-{draft.end_ms}ms outside 0-{duration_ms}ms")
                continue
            accepted.append(draft)
        return ReconciliationResult(transcripts=accepted, latency_ms=(perf_counter() - started) * 1000, warnings=warnings)
