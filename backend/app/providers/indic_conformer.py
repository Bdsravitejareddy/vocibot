"""AI4Bharat IndicConformer for Indian-language speech, run with ONNX Runtime.

Whisper misspells most Telugu words; IndicConformer was trained on Indian
speech.  On the reference Telugu consultation it got 45% of words and 82%
of characters right against Whisper's 22% and 74%, in 2 s instead of 40 s.
It does not do English or translation, so Whisper keeps those (see
``IndicRoutingProvider``).

Each language is one ONNX graph exported from the official checkpoint
(``indicconformer_stt_<lang>_hybrid_rnnt_large.nemo``): log-mel features in,
per-frame log-probabilities over that language's 256 tokens plus blank out.
Features are computed in numpy (``indic_features``) and decoded greedily
(CTC); each frame is 40 ms, which gives word timings and lines split at
pauses.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading

import numpy as np

from .indic_features import FeatureExtractor
from .speech import AudioChunk, TranscriptDraft, format_relative_timestamp

# A pause this long between words starts a new transcript line.
LINE_PAUSE_SECONDS = 0.7
# Lines are also broken after this long, like Whisper's segments.
MAX_LINE_SECONDS = 12.0


class IndicConformerProvider:
    """Speech to text for the languages whose model is installed."""

    def __init__(self, models_dir: str | Path, *, threads: int = 0) -> None:
        self.models_dir = Path(models_dir)
        self.threads = threads
        self.languages = {path.parent.name for path in self.models_dir.glob("*/model.onnx") if (path.parent / "vocab.json").is_file()}
        self._sessions: dict[str, tuple[object, dict]] = {}
        self._features: FeatureExtractor | None = None
        self._lock = threading.Lock()
        self.last_diagnostics: dict[str, object] = {}

    def available(self) -> bool:
        return bool(self.languages) and (self.models_dir / "features.npz").is_file()

    def _load(self, language: str):
        with self._lock:
            if language not in self._sessions:
                import onnxruntime  # type: ignore[import-not-found]

                options = onnxruntime.SessionOptions()
                if self.threads:
                    options.intra_op_num_threads = self.threads
                session = onnxruntime.InferenceSession(str(self.models_dir / language / "model.onnx"), options, providers=["CPUExecutionProvider"])
                self._sessions[language] = (session, json.loads((self.models_dir / language / "vocab.json").read_text(encoding="utf-8")))
            if self._features is None:
                self._features = FeatureExtractor(self.models_dir / "features.npz")
            return self._sessions[language]

    def warmup(self, language: str) -> None:
        if language in self.languages:
            self.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(16_000, dtype=np.float32)), language)

    def words(self, audio: np.ndarray, language: str) -> list[tuple[str, float, float, float]]:
        """(word, start s, end s, score) for the audio."""

        session, vocab = self._load(language)
        features = self._features(audio)[None]  # type: ignore[misc]
        logprobs, _ = session.run(None, {"features": features, "length": np.array([features.shape[2]], dtype=np.int64)})
        return _ctc_words(logprobs[0], vocab)

    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        if language not in self.languages:
            raise ValueError(f"No IndicConformer model for language {language!r}")
        session, vocab = self._load(language)
        audio = np.asarray(chunk.waveform, dtype=np.float32).reshape(-1)
        if len(audio) < 1_600:  # under 0.1 s
            return []
        words = self.words(audio, language)
        drafts = []
        for line in _lines(words):
            start_ms = chunk.timestamp_ms + int(line[0][1] * 1000)
            end_ms = chunk.timestamp_ms + int(line[-1][2] * 1000)
            drafts.append(TranscriptDraft(text=" ".join(word for word, _, _, _ in line), timestamp=format_relative_timestamp(start_ms), start_ms=start_ms, end_ms=end_ms, language_code=language))
        confidence = float(np.mean([score for *_, score in words])) if words else None
        self.last_diagnostics = {"engine": "indic_conformer", "language": language, "segments": [{"text": draft.text, "start_ms": draft.start_ms, "end_ms": draft.end_ms} for draft in drafts], "avg_token_logprob": confidence}
        return drafts


def _ctc_words(logprobs: np.ndarray, vocab: dict) -> list[tuple[str, float, float, float]]:
    """Greedy CTC: (word, start s, end s, mean token log-prob) per word."""

    tokens, blank, step = vocab["vocab"], vocab["blank"], vocab["frame_seconds"]
    best = logprobs.argmax(axis=1)
    words: list[list] = []
    previous = blank
    for frame, token in enumerate(best):
        if token != blank and token != previous:
            piece = tokens[token]
            score = float(logprobs[frame, token])
            if piece.startswith("▁") or not words:
                words.append([piece.lstrip("▁"), frame * step, (frame + 1) * step, [score]])
            else:
                words[-1][0] += piece
                words[-1][2] = (frame + 1) * step
                words[-1][3].append(score)
        elif token != blank and words:
            words[-1][2] = (frame + 1) * step
        previous = token
    return [(text, start, end, float(np.mean(scores))) for text, start, end, scores in words if text]


def _lines(words: list[tuple[str, float, float, float]]) -> list[list[tuple[str, float, float, float]]]:
    lines: list[list] = []
    for word in words:
        if lines and word[1] - lines[-1][-1][2] < LINE_PAUSE_SECONDS and word[2] - lines[-1][0][1] <= MAX_LINE_SECONDS:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


# Indian consultations mix in English (the doctor's questions, medicine and
# test names). IndicConformer writes English speech as gibberish in the
# Indian script ("हाव लॉन्ग हेव" for "how long have"), so each final line
# is checked: when Whisper hears it as English this clearly (share of
# English vs the piece's language), Whisper's English transcript replaces it.
# On a Hindi/English consultation English lines scored 0.89-1.00, Hindi
# lines mostly 0.01-0.12; shorter lines are not judged.
ENGLISH_LINE_SHARE = 0.85
ENGLISH_LINE_MIN_SECONDS = 1.0
# Language per spoken stretch instead of per 28 s piece: people switch
# between Hindi and English every few seconds, and IndicConformer writes
# English as gibberish in Devanagari ("व्हेट इस थे प्रॉब्लम"). Each stretch of
# speech (split at pauses) goes to Whisper's English when it sounds English
# at least this much (English vs the piece's language), else IndicConformer.
SPAN_ENGLISH_SHARE = 0.5
SPAN_PAUSE_MS = 300
SPAN_MAX_SECONDS = 10.0
SPAN_MIN_JUDGED_SECONDS = 0.6
# An English piece is also checked stretch by stretch when an Indian
# language has at least this share of it (Whisper's language probabilities).
ENGLISH_PIECE_NATIVE_SHARE = 0.1
# Text is translated in groups of whole transcript lines up to this many
# words: single lines are often half a sentence, very long groups lose detail.
TRANSLATION_GROUP_WORDS = 20


class IndicRoutingProvider:
    """Whisper for detection, English and the live preview; IndicConformer for
    the final transcript of languages it has a model for; IndicTrans2 (when
    installed and enabled for the language) to translate that text, else
    Whisper translating from the audio."""

    def __init__(self, whisper, indic: IndicConformerProvider, translator=None, text_translation_languages: set[str] | None = None) -> None:
        object.__setattr__(self, "whisper", whisper)
        object.__setattr__(self, "indic", indic)
        object.__setattr__(self, "translator", translator)
        object.__setattr__(self, "text_translation_languages", set(text_translation_languages or ()))
        object.__setattr__(self, "last_diagnostics", {})

    def translates_text(self, language: str | None) -> bool:
        return self.translator is not None and language in self.text_translation_languages and language in self.indic.languages and self.translator.supports(language)

    def translate_text(self, drafts: list[TranscriptDraft], language: str) -> list[TranscriptDraft]:
        """English for a piece's transcript lines, in groups of whole lines;
        lines already in English are kept as they are."""

        groups: list[list[TranscriptDraft]] = []
        for draft in drafts:
            # English lines stay one per segment (each keeps its own speaker);
            # Indian-language lines are grouped for a better translation.
            same_kind = groups and draft.language_code != "en" and groups[-1][0].language_code != "en"
            if same_kind and len(" ".join(item.text for item in groups[-1] + [draft]).split()) <= TRANSLATION_GROUP_WORDS:
                groups[-1].append(draft)
            else:
                groups.append([draft])
        foreign = [group for group in groups if group[0].language_code != "en"]
        english = dict(zip(map(id, foreign), self.translator.translate([" ".join(item.text for item in group) for group in foreign], language))) if foreign else {}
        out = []
        for group in groups:
            text = " ".join(item.text for item in group) if group[0].language_code == "en" else english[id(group)]
            if text.strip():
                out.append(TranscriptDraft(text=text, timestamp=group[0].timestamp, start_ms=group[0].start_ms, end_ms=group[-1].end_ms, language_code="en"))
        return out

    def _speech_spans(self, audio: np.ndarray, rate: int) -> list[tuple[int, int]]:
        """Stretches of speech between pauses, at most SPAN_MAX_SECONDS."""

        from silero_vad import get_speech_timestamps, load_silero_vad  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]

        if getattr(self, "_vad", None) is None:
            object.__setattr__(self, "_vad", load_silero_vad())
        found = get_speech_timestamps(torch.from_numpy(np.ascontiguousarray(audio)), self._vad, sampling_rate=rate, min_silence_duration_ms=SPAN_PAUSE_MS, speech_pad_ms=100,
                                      max_speech_duration_s=SPAN_MAX_SECONDS)
        spans = [(int(item["start"]), int(item["end"])) for item in found]
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            # A very short stretch cannot be judged alone: join its neighbour.
            if merged and (end - start < SPAN_MIN_JUDGED_SECONDS * rate or merged[-1][1] - merged[-1][0] < SPAN_MIN_JUDGED_SECONDS * rate) and end - merged[-1][0] <= SPAN_MAX_SECONDS * rate:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        return merged

    def _by_span(self, chunk: AudioChunk, language: str) -> list[TranscriptDraft]:
        """The final transcript of a piece, language decided per stretch of
        speech: runs of English stretches get Whisper's English, the rest
        IndicConformer's words (one pass over the piece, split by word
        timings) and the line-by-line English check."""

        share = getattr(self.whisper, "english_share", None)
        allowed = self.whisper.allowed_languages
        audio = np.asarray(chunk.waveform, dtype=np.float32).reshape(-1)
        rate = chunk.sample_rate
        if share is None or (allowed and "en" not in allowed):
            return self.indic.transcribe_chunk(chunk, language)
        spans = self._speech_spans(audio, rate)
        english = [share(audio[start:end], language) >= SPAN_ENGLISH_SHARE for start, end in spans]
        if not any(english):
            return self.indic.transcribe_chunk(chunk, language)
        if all(english):
            return [replace(draft, language_code="en") for draft in self.whisper.transcribe_chunk(chunk, "en")]
        # Runs of neighbouring stretches in the same language.
        runs: list[list] = []
        for (start, end), is_english in zip(spans, english):
            if runs and runs[-1][2] == is_english:
                runs[-1][1] = end
            else:
                runs.append([start, end, is_english])
        words = self.indic.words(audio, language) if len(audio) >= 1_600 else []
        drafts: list[TranscriptDraft] = []
        for index, (start, end, is_english) in enumerate(runs):
            if is_english:
                piece = AudioChunk(audio=b"", sample_rate=rate, timestamp_ms=chunk.timestamp_ms + int(start / rate * 1000), waveform=np.ascontiguousarray(audio[start:end]))
                drafts += [replace(draft, language_code="en") for draft in self.whisper.transcribe_chunk(piece, "en")]
                continue
            # Words of this run (by their middle; the pauses between runs belong to the earlier run).
            begin = runs[index - 1][1] / rate if index else 0.0
            finish = runs[index + 1][0] / rate if index + 1 < len(runs) else len(audio) / rate
            own = [word for word in words if begin <= (word[1] + word[2]) / 2 < finish]
            lines = []
            for line in _lines(own):
                start_ms = chunk.timestamp_ms + int(line[0][1] * 1000)
                end_ms = chunk.timestamp_ms + int(line[-1][2] * 1000)
                lines.append(TranscriptDraft(text=" ".join(word for word, _, _, _ in line), timestamp=format_relative_timestamp(start_ms), start_ms=start_ms, end_ms=end_ms, language_code=language))
            # A short English question joined to a Hindi answer in one stretch
            # still gets the line-by-line English check.
            drafts += self._english_lines(chunk, lines, language)
        return sorted(drafts, key=lambda draft: draft.start_ms or 0)

    def _english_lines(self, chunk: AudioChunk, drafts: list[TranscriptDraft], language: str) -> list[TranscriptDraft]:
        """Lines spoken in English get Whisper's English transcript."""

        allowed = self.whisper.allowed_languages
        share = getattr(self.whisper, "english_share", None)
        if share is None or (allowed and "en" not in allowed) or chunk.waveform is None:
            return drafts
        audio = np.asarray(chunk.waveform, dtype=np.float32)
        rate = chunk.sample_rate
        out = []
        for draft in drafts:
            begin = max(0, int(((draft.start_ms or 0) - chunk.timestamp_ms) / 1000 * rate) - int(0.2 * rate))
            end = min(len(audio), int(((draft.end_ms or 0) - chunk.timestamp_ms) / 1000 * rate) + int(0.2 * rate))
            if end - begin < ENGLISH_LINE_MIN_SECONDS * rate:
                out.append(draft)
                continue
            if share(audio[begin:end], language) >= ENGLISH_LINE_SHARE:
                line = AudioChunk(audio=b"", sample_rate=rate, timestamp_ms=chunk.timestamp_ms + int(begin / rate * 1000), waveform=np.ascontiguousarray(audio[begin:end]))
                text = " ".join(item.text for item in self.whisper.transcribe_chunk(line, "en")).strip()
                if text:
                    draft = TranscriptDraft(text=text, timestamp=draft.timestamp, speaker=draft.speaker, start_ms=draft.start_ms, end_ms=draft.end_ms, language_code="en")
            out.append(draft)
        return out

    # restrict_languages() sets these on the session's speech provider.
    @property
    def allowed_languages(self):
        return self.whisper.allowed_languages

    @allowed_languages.setter
    def allowed_languages(self, value) -> None:
        self.whisper.allowed_languages = value

    @property
    def primary_language(self):
        return getattr(self.whisper, "primary_language", None)

    @primary_language.setter
    def primary_language(self, value) -> None:
        self.whisper.primary_language = value

    def __getattr__(self, name: str):
        # detect_piece_language, translate_chunk, last_language_confidence ...
        return getattr(self.whisper, name)

    def __setattr__(self, name: str, value) -> None:
        if name in ("allowed_languages", "primary_language", "last_diagnostics"):
            object.__setattr__(self, name, value) if name == "last_diagnostics" else type(self).__dict__[name].__set__(self, value)
        else:
            setattr(self.whisper, name, value)

    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        if not chunk.live and language in self.indic.languages:
            from ..config import settings

            if settings.final_language_per_span and language in {code.strip() for code in settings.final_language_per_span_languages.split(",")} and chunk.waveform is not None:
                drafts = self._by_span(chunk, language)
            else:
                drafts = self._english_lines(chunk, self.indic.transcribe_chunk(chunk, language), language)
            object.__setattr__(self, "last_diagnostics", self.indic.last_diagnostics)
            return drafts
        if not chunk.live and language == "en" and chunk.waveform is not None:
            from ..config import settings

            native = self._native_language(chunk) if settings.final_language_per_span_english_pieces else None
            if native:
                drafts = self._by_span(chunk, native)
                object.__setattr__(self, "last_diagnostics", {"engine": "per_span", "language": "en", "native": native})
                return drafts
        drafts = self.whisper.transcribe_chunk(chunk, language)
        object.__setattr__(self, "last_diagnostics", getattr(self.whisper, "last_diagnostics", {}))
        return drafts

    def _native_language(self, chunk: AudioChunk) -> str | None:
        """The Indian language most heard in an English piece, if any is
        enabled and heard enough to matter (else the piece stays English)."""

        allowed = set(self.whisper.allowed_languages or ()) & set(self.indic.languages)
        if not allowed:
            return None
        probabilities = self.whisper.detect_language_probabilities(np.asarray(chunk.waveform, dtype=np.float32))
        code = max(allowed, key=lambda item: probabilities.get(item, 0.0))
        return code if probabilities.get(code, 0.0) >= ENGLISH_PIECE_NATIVE_SHARE else None

    def warmup(self) -> None:
        warm = getattr(self.whisper, "warmup", None)
        if warm:
            warm()
        if self.primary_language in self.indic.languages:
            self.indic.warmup(self.primary_language)
