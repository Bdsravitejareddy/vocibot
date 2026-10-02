from dataclasses import dataclass, field, replace
from time import perf_counter

import numpy as np

from .speech import AudioChunk, SpeechToTextProvider, TranscriptDraft

# Final transcription works in pieces of about this length, cut at pauses:
# each piece gets its own language (mixed Telugu/English consultations) and
# Whisper's 30-second window is used as designed.
FINAL_PIECE_SECONDS = 28.0
# Below this share of the enabled languages' probability a piece's language
# counts as uncertain.
UNCERTAIN_LANGUAGE = 0.6


@dataclass
class ReconciliationResult:
    transcripts: list[TranscriptDraft] = field(default_factory=list)
    # English translation for non-English speech; empty when all English.
    translations: list[TranscriptDraft] = field(default_factory=list)
    latency_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


class FinalReconciler:
    """The authoritative pass over the complete captured waveform."""

    def run(self, waveform: np.ndarray, stt: SpeechToTextProvider, *, sample_rate: int, language: str | None = None, translate: bool = True) -> ReconciliationResult:
        started = perf_counter()
        audio = np.asarray(waveform, dtype=np.float32).reshape(-1)
        duration_ms = int(len(audio) / sample_rate * 1000)
        accepted: list[TranscriptDraft] = []
        translations: list[TranscriptDraft] = []
        warnings: list[str] = []
        any_foreign = False
        spans = split_at_pauses(audio, sample_rate, FINAL_PIECE_SECONDS)
        pieces = [self._transcribe_piece(stt, audio, sample_rate, start, end, language) for start, end in spans]
        if language is None and len(pieces) > 1:
            # A piece detected with low confidence (often a short or quiet
            # tail) takes the consultation's main language instead.
            weights: dict[str, float] = {}
            for (start, end), (_, detected, confidence) in zip(spans, pieces):
                if detected and confidence >= UNCERTAIN_LANGUAGE:
                    weights[detected] = weights.get(detected, 0.0) + (end - start)
            dominant = max(weights, key=weights.get) if weights else None
            for index, ((start, end), (_, detected, confidence)) in enumerate(zip(spans, pieces)):
                if dominant and detected != dominant and confidence < UNCERTAIN_LANGUAGE:
                    pieces[index] = self._transcribe_piece(stt, audio, sample_rate, start, end, dominant)
        for (start, end), (drafts, detected, _) in zip(spans, pieces):
            offset_ms = int(start / sample_rate * 1000)
            piece_end_ms = int(end / sample_rate * 1000)
            chunk = AudioChunk(audio=b"", sample_rate=sample_rate, timestamp_ms=offset_ms, encoding="pcm_f32le", channels=1, waveform=np.ascontiguousarray(audio[start:end]))
            piece: list[TranscriptDraft] = []
            for draft in drafts:
                if draft.start_ms is not None and draft.end_ms is not None and offset_ms <= draft.start_ms < piece_end_ms < draft.end_ms:
                    # Whisper pads a segment cut off at the end of a piece;
                    # keep the words and clamp the bound.
                    draft = replace(draft, end_ms=piece_end_ms)
                if draft.start_ms is None or draft.end_ms is None or not 0 <= draft.start_ms <= draft.end_ms <= duration_ms:
                    warnings.append(f"Rejected final transcript timestamp {draft.start_ms}-{draft.end_ms}ms outside 0-{duration_ms}ms")
                    continue
                piece.append(draft)
            accepted += piece
            spoken = next((draft.language_code for draft in piece if draft.language_code), detected or language)
            if spoken and spoken != "en" and translate and hasattr(stt, "translate_chunk"):
                any_foreign = True
                translations += stt.translate_chunk(chunk, spoken)
            else:
                translations += [replace(draft, language_code="en") for draft in piece]
        return ReconciliationResult(transcripts=accepted, translations=translations if any_foreign else [], latency_ms=(perf_counter() - started) * 1000, warnings=warnings)


    @staticmethod
    def _transcribe_piece(stt, audio, sample_rate: int, start: int, end: int, language: str | None):
        chunk = AudioChunk(audio=b"", sample_rate=sample_rate, timestamp_ms=int(start / sample_rate * 1000), encoding="pcm_f32le", channels=1, waveform=np.ascontiguousarray(audio[start:end]))
        drafts = stt.transcribe_chunk(chunk, language=language)
        detected = next((draft.language_code for draft in drafts if draft.language_code), language)
        confidence = 1.0 if language else float(getattr(stt, "last_language_confidence", 1.0))
        return drafts, detected, confidence


def split_at_pauses(waveform: np.ndarray, sample_rate: int, target_seconds: float) -> list[tuple[int, int]]:
    """Cut points about every ``target_seconds``, moved to the quietest moment nearby."""

    total = len(waveform)
    target = int(target_seconds * sample_rate)
    if total <= target * 1.25:
        return [(0, total)] if total else []
    window = int(0.02 * sample_rate)  # 20 ms energy frames
    search = int(4 * sample_rate)  # look up to 4 s either side for a pause
    spans: list[tuple[int, int]] = []
    start = 0
    while total - start > target * 1.25:
        ideal = start + target
        low, high = max(start + target // 2, ideal - search), min(total - window, ideal + search)
        region = np.abs(waveform[low:high + window]).astype(np.float32)
        frames = len(region) // window
        if frames <= 0:
            cut = ideal
        else:
            energy = region[: frames * window].reshape(frames, window).mean(axis=1)
            cut = low + int(np.argmin(energy)) * window + window // 2
        spans.append((start, cut))
        start = cut
    spans.append((start, total))
    return spans
