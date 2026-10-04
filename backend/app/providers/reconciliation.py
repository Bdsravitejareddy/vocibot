from dataclasses import dataclass, field, replace
import threading
from time import perf_counter

import numpy as np

from .speech import AudioChunk, SpeechToTextProvider, TranscriptDraft

# Final transcription works in pieces of about this length, cut at pauses:
# each piece gets its own language (mixed Telugu/English consultations) and
# Whisper's 30-second window is used as designed.
FINAL_PIECE_SECONDS = 28.0
# Whisper writes at most 224 tokens per window, and Indian scripts take
# several tokens per letter: 28 s of Telugu speech overflowed it, so Whisper
# stopped mid-letter and skipped the rest of the window (a 15 s gap with the
# headache, fever and the doctor's first question in the reference
# consultation).  Speech in these scripts is transcribed in shorter pieces.
# Measured on the reference recordings (characters right, 28 s -> this):
# Telugu 56% -> 73% at 10 s; Hindi 91% -> 97% at 14 s.
DENSE_SCRIPT_PIECE_SECONDS = {
    **dict.fromkeys(("te", "kn", "ta", "ml", "si"), 10.0),
    **dict.fromkeys(("hi", "mr", "ne", "sa", "gu", "pa", "bn", "as", "or", "ur", "sd", "my", "km", "lo", "th", "am", "bo"), 14.0),
}
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


@dataclass
class _Piece:
    start: int
    end: int
    language: str | None
    confidence: float
    transcripts: list[TranscriptDraft]
    translations: list[TranscriptDraft]
    foreign: bool
    warnings: list[str]


class IncrementalReconciler:
    """The authoritative final pass, piece by piece, while the consultation runs.

    Each ~28 s piece (cut at a pause) gets its language detected, its
    transcript and its English translation as soon as it is complete, so at
    Stop only the last piece remains. A piece is cut only once the audio
    around the cut is complete, so cuts - and results - are the same as one
    pass over the whole recording (FinalReconciler).
    """

    def __init__(self, stt: SpeechToTextProvider, *, sample_rate: int, language: str | None = None, translate: bool = True) -> None:
        self.stt, self.sample_rate, self.language, self.translate = stt, sample_rate, language, translate
        self.pieces: list[_Piece] = []
        self.next_start = 0
        self._lock = threading.Lock()

    def advance(self, waveform: np.ndarray) -> int:
        """Process every piece that is complete in the audio so far; returns how many."""

        audio = np.asarray(waveform, dtype=np.float32).reshape(-1)
        done = 0
        with self._lock:
            while (cut := _next_cut(audio, self.next_start, self.sample_rate, FINAL_PIECE_SECONDS, complete=False)) is not None:
                self.pieces.append(self._process(audio, self.next_start, cut, None))
                self.next_start = cut
                done += 1
        return done

    def finish(self, waveform: np.ndarray) -> ReconciliationResult:
        started = perf_counter()
        audio = np.asarray(waveform, dtype=np.float32).reshape(-1)
        with self._lock:
            for start, end in split_at_pauses(audio[self.next_start:], self.sample_rate, FINAL_PIECE_SECONDS):
                self.pieces.append(self._process(audio, self.next_start + start, self.next_start + end, None))
            self.next_start = len(audio)
            if self.language is None and len(self.pieces) > 1:
                # A piece detected with low confidence (often a short or quiet
                # tail) takes the consultation's main language instead.
                spans = [(piece.start, piece.end) for piece in self.pieces]
                found = _with_dominant_language(spans, [(piece.language, piece.confidence) for piece in self.pieces])
                for index, (piece, (code, _)) in enumerate(zip(self.pieces, found)):
                    if code != piece.language:
                        self.pieces[index] = self._process(audio, piece.start, piece.end, code)
            duration_ms = int(len(audio) / self.sample_rate * 1000)
            transcripts, translations, warnings, foreign = [], [], [], False
            for piece in self.pieces:
                warnings += piece.warnings
                kept = [draft for draft in piece.transcripts if draft.end_ms is not None and draft.end_ms <= duration_ms]
                warnings += [f"Rejected final transcript timestamp {draft.start_ms}-{draft.end_ms}ms outside 0-{duration_ms}ms" for draft in piece.transcripts if draft not in kept]
                transcripts += kept
                translations += piece.translations
                foreign = foreign or piece.foreign
        return ReconciliationResult(transcripts=transcripts, translations=translations if foreign else [], latency_ms=(perf_counter() - started) * 1000, warnings=warnings)

    def _process(self, audio: np.ndarray, start: int, end: int, forced: str | None) -> _Piece:
        stt, sample_rate = self.stt, self.sample_rate
        language = forced or self.language
        detect = getattr(stt, "detect_piece_language", None)
        if language is None and detect is not None:
            # Language first (one encoder pass), then transcription at the
            # piece length that language's script needs.
            language, confidence = detect(audio[start:end])
            drafts, detected, _ = _transcribe_in_language(stt, audio, sample_rate, start, end, language)
        elif detect is not None:
            confidence = 1.0
            drafts, detected, _ = _transcribe_in_language(stt, audio, sample_rate, start, end, language)
        else:
            drafts, detected, confidence = _transcribe_piece(stt, audio, sample_rate, start, end, language)
        offset_ms = int(start / sample_rate * 1000)
        piece_end_ms = int(end / sample_rate * 1000)
        kept: list[TranscriptDraft] = []
        warnings: list[str] = []
        for draft in drafts:
            if draft.start_ms is not None and draft.end_ms is not None and offset_ms <= draft.start_ms < piece_end_ms < draft.end_ms:
                # Whisper pads a segment cut off at the end of a piece;
                # keep the words and clamp the bound.
                draft = replace(draft, end_ms=piece_end_ms)
            if draft.start_ms is None or draft.end_ms is None or not 0 <= draft.start_ms <= draft.end_ms:
                warnings.append(f"Rejected final transcript timestamp {draft.start_ms}-{draft.end_ms}ms")
                continue
            kept.append(draft)
        spoken = next((draft.language_code for draft in kept if draft.language_code), detected or language)
        translations: list[TranscriptDraft] = []
        foreign = False
        if spoken and spoken != "en" and self.translate and getattr(stt, "translates_text", lambda _: False)(spoken):
            # IndicTrans2 translates the (IndicConformer) text of the piece.
            foreign = True
            translations = stt.translate_text(kept, spoken) if kept else []
        elif spoken and spoken != "en" and self.translate and hasattr(stt, "translate_chunk"):
            foreign = True
            chunk = AudioChunk(audio=b"", sample_rate=sample_rate, timestamp_ms=offset_ms, encoding="pcm_f32le", channels=1, waveform=np.ascontiguousarray(audio[start:end]))
            translations = stt.translate_chunk(chunk, spoken)
        else:
            translations = [replace(draft, language_code="en") for draft in kept]
        return _Piece(start, end, detected or language, confidence, kept, translations, foreign, warnings)


class FinalReconciler:
    """The authoritative pass over the complete captured waveform."""

    def run(self, waveform: np.ndarray, stt: SpeechToTextProvider, *, sample_rate: int, language: str | None = None, translate: bool = True) -> ReconciliationResult:
        return IncrementalReconciler(stt, sample_rate=sample_rate, language=language, translate=translate).finish(waveform)

    # Kept for callers of the old helpers.
    @staticmethod
    def _transcribe_piece(stt, audio, sample_rate: int, start: int, end: int, language: str | None):
        return _transcribe_piece(stt, audio, sample_rate, start, end, language)


def _transcribe_in_language(stt, audio, sample_rate: int, start: int, end: int, language: str | None):
    limit = DENSE_SCRIPT_PIECE_SECONDS.get(language or "")
    if limit is None or end - start <= limit * sample_rate * 1.25:
        return _transcribe_piece(stt, audio, sample_rate, start, end, language)
    drafts: list[TranscriptDraft] = []
    for sub_start, sub_end in split_at_pauses(audio[start:end], sample_rate, limit):
        sub_drafts, _, _ = _transcribe_piece(stt, audio, sample_rate, start + sub_start, start + sub_end, language)
        drafts += sub_drafts
    return drafts, language, 1.0


def _transcribe_piece(stt, audio, sample_rate: int, start: int, end: int, language: str | None):
    chunk = AudioChunk(audio=b"", sample_rate=sample_rate, timestamp_ms=int(start / sample_rate * 1000), encoding="pcm_f32le", channels=1, waveform=np.ascontiguousarray(audio[start:end]))
    drafts = stt.transcribe_chunk(chunk, language=language)
    detected = next((draft.language_code for draft in drafts if draft.language_code), language)
    confidence = 1.0 if language else float(getattr(stt, "last_language_confidence", 1.0))
    return drafts, detected, confidence


def _with_dominant_language(spans: list[tuple[int, int]], found: list[tuple[str | None, float]]) -> list[tuple[str | None, float]]:
    """A piece detected with low confidence (often a short or quiet tail)
    takes the consultation's main language instead."""

    weights: dict[str, float] = {}
    for (start, end), (code, confidence) in zip(spans, found):
        if code and confidence >= UNCERTAIN_LANGUAGE:
            weights[code] = weights.get(code, 0.0) + (end - start)
    dominant = max(weights, key=weights.get) if weights else None
    if dominant is None or len(spans) < 2:
        return found
    return [(dominant, confidence) if code != dominant and confidence < UNCERTAIN_LANGUAGE else (code, confidence) for code, confidence in found]


_WINDOW_SECONDS = 0.02  # 20 ms energy frames
_SEARCH_SECONDS = 4.0  # look up to 4 s either side for a pause


def _next_cut(waveform: np.ndarray, start: int, sample_rate: int, target_seconds: float, *, complete: bool) -> int | None:
    """Where the piece starting at ``start`` ends: about ``target_seconds``
    later, at the quietest moment nearby; None if the rest is the last piece
    (or, while recording, if the audio around the cut is not complete yet)."""

    total = len(waveform)
    target = int(target_seconds * sample_rate)
    window = int(_WINDOW_SECONDS * sample_rate)
    search = int(_SEARCH_SECONDS * sample_rate)
    if total - start <= target * 1.25:
        return None
    ideal = start + target
    if not complete and total < ideal + search + window:
        return None
    low, high = max(start + target // 2, ideal - search), min(total - window, ideal + search)
    region = np.abs(waveform[low:high + window]).astype(np.float32)
    frames = len(region) // window
    if frames <= 0:
        return ideal
    energy = region[: frames * window].reshape(frames, window).mean(axis=1)
    return low + int(np.argmin(energy)) * window + window // 2


def split_at_pauses(waveform: np.ndarray, sample_rate: int, target_seconds: float) -> list[tuple[int, int]]:
    """Cut points about every ``target_seconds``, moved to the quietest moment nearby."""

    total = len(waveform)
    if total == 0:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    while (cut := _next_cut(waveform, start, sample_rate, target_seconds, complete=True)) is not None:
        spans.append((start, cut))
        start = cut
    spans.append((start, total))
    return spans
