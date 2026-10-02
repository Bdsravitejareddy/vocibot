import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AudioChunk:
    audio: bytes
    sample_rate: int
    timestamp_ms: int
    encoding: str = "pcm_f32le"
    channels: int = 1
    waveform: Any = None
    vad_speech_proportion: float | None = None
    # Live preview passes decode greedily once; temperature fallback can take
    # several seconds per pass and is reserved for the authoritative final pass.
    live: bool = False


@dataclass(frozen=True)
class TranscriptDraft:
    text: str
    timestamp: str
    speaker: str = "UNKNOWN"
    start_ms: int | None = None
    end_ms: int | None = None
    language_code: str | None = None


class SpeechToTextProvider(Protocol):
    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        ...


class DemoSpeechToTextProvider:
    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        return []


class FasterWhisperProvider:
    """Lazy-loaded faster-whisper adapter; model size is configurable for local hardware."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "int8",
        model=None,
        *,
        cpu_threads: int = 4,
        num_workers: int = 1,
        vad_filter: bool = True,
        no_speech_threshold: float = 0.6,
        log_prob_threshold: float = -1.0,
        compression_ratio_threshold: float = 2.4,
        min_language_probability: float = 0.5,
        min_avg_logprob: float = -1.0,
        max_no_speech_probability: float = 0.6,
        max_compression_ratio: float = 2.4,
        initial_prompt: str | None = None,
        beam_size: int = 1,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = model
        self.cpu_threads = cpu_threads
        self.num_workers = num_workers
        self.vad_filter = vad_filter
        self.no_speech_threshold = no_speech_threshold
        self.log_prob_threshold = log_prob_threshold
        self.compression_ratio_threshold = compression_ratio_threshold
        self.min_language_probability = min_language_probability
        self.min_avg_logprob = min_avg_logprob
        self.max_no_speech_probability = max_no_speech_probability
        self.max_compression_ratio = max_compression_ratio
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        self.last_diagnostics: dict[str, object] = {}
        # Auto-detect chooses only among these (None: any language).
        self.allowed_languages: set[str] | None = None
        self._language_memory = LanguageMemory()

    def _detect_allowed(self, model, audio) -> str:
        if len(self.allowed_languages) == 1:
            return next(iter(self.allowed_languages))
        _, _, probabilities = model.detect_language(audio)
        return choose_language(dict(probabilities), self.allowed_languages) or next(iter(sorted(self.allowed_languages)))

    def _load(self):
        if self._model is None:
            import os

            # Local inference never performs an implicit first-run download.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                num_workers=self.num_workers,
            )
        return self._model

    def warmup(self) -> None:
        """Load and exercise the local model before microphone capture begins."""

        model = self._load()
        import numpy as np  # type: ignore[import-not-found]

        segments, _ = model.transcribe(
            np.zeros(8_000, dtype=np.float32),
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            no_speech_threshold=self.no_speech_threshold,
            log_prob_threshold=self.log_prob_threshold,
            compression_ratio_threshold=self.compression_ratio_threshold,
            condition_on_previous_text=False,
        )
        list(segments)

    def transcribe(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        model = self._load()
        import numpy as np  # type: ignore[import-not-found]

        if chunk.waveform is None:
            from .audio import decode_audio_payload

            audio = decode_audio_payload(
                chunk.audio,
                encoding=chunk.encoding,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels,
            ).waveform
        else:
            audio = np.asarray(chunk.waveform, dtype=np.float32)
        language_option: dict[str, object] = {}
        if language and language != "auto":
            language_option["language"] = language
        elif self.allowed_languages:
            language_option["language"] = self._language_memory.get(chunk) or self._language_memory.remember(chunk, self._detect_allowed(model, audio))
        segments, info = model.transcribe(
            audio,
            beam_size=self.beam_size,
            vad_filter=self.vad_filter,
            no_speech_threshold=self.no_speech_threshold,
            log_prob_threshold=self.log_prob_threshold,
            compression_ratio_threshold=self.compression_ratio_threshold,
            condition_on_previous_text=False,
            **({"temperature": 0.0} if chunk.live else {}),
            **language_option,
            **({"initial_prompt": self.initial_prompt} if self.initial_prompt else {}),
        )
        segment_list = list(segments)
        language_probability = getattr(info, "language_probability", None)
        rejected: list[dict[str, object]] = []
        accepted_segments = []
        for segment in segment_list:
            text = getattr(segment, "text", "").strip()
            no_speech_prob = getattr(segment, "no_speech_prob", None)
            avg_logprob = getattr(segment, "avg_logprob", None)
            compression_ratio = getattr(segment, "compression_ratio", None)
            reasons: list[str] = []
            if not text:
                reasons.append("empty_text")
            if no_speech_prob is not None and no_speech_prob > self.max_no_speech_probability:
                reasons.append("no_speech_probability")
            if avg_logprob is not None and avg_logprob < self.min_avg_logprob:
                reasons.append("low_average_log_probability")
            if compression_ratio is not None and compression_ratio > self.max_compression_ratio:
                reasons.append("high_compression_ratio")
            if language_probability is not None and language_probability < self.min_language_probability:
                reasons.append("low_language_probability")
            diagnostic = {
                "text": text,
                "avg_logprob": avg_logprob,
                "no_speech_prob": no_speech_prob,
                "compression_ratio": compression_ratio,
                "accepted": not reasons,
                "rejection_reason": ",".join(reasons) if reasons else None,
                "start_ms": chunk.timestamp_ms + int(segment.start * 1000),
                "end_ms": chunk.timestamp_ms + int(segment.end * 1000),
            }
            if reasons:
                rejected.append(diagnostic)
            else:
                accepted_segments.append(segment)
        self.last_diagnostics = {
            "language": getattr(info, "language", None),
            "language_probability": language_probability,
            "vad_filter": self.vad_filter,
            "no_speech_threshold": self.no_speech_threshold,
            "log_prob_threshold": self.log_prob_threshold,
            "compression_ratio_threshold": self.compression_ratio_threshold,
            "condition_on_previous_text": False,
            "initial_prompt": self.initial_prompt,
            "beam_size": self.beam_size,
            "vad_speech_proportion": chunk.vad_speech_proportion,
            "audio_rms": float(np.sqrt(np.mean(np.square(audio), dtype=np.float64))) if audio.size else 0.0,
            "audio_peak": float(np.max(np.abs(audio))) if audio.size else 0.0,
            "segments_rejected": rejected,
            "segments": [
                {
                    "text": getattr(segment, "text", "").strip(),
                    "avg_logprob": getattr(segment, "avg_logprob", None),
                    "no_speech_prob": getattr(segment, "no_speech_prob", None),
                    "compression_ratio": getattr(segment, "compression_ratio", None),
                    "start_ms": chunk.timestamp_ms + int(segment.start * 1000),
                    "end_ms": chunk.timestamp_ms + int(segment.end * 1000),
                    "accepted": True,
                }
                for segment in accepted_segments
            ],
        }
        return [
            TranscriptDraft(
                text=segment.text.strip(),
                timestamp=format_relative_timestamp(chunk.timestamp_ms + int(segment.start * 1000)),
                start_ms=chunk.timestamp_ms + int(segment.start * 1000),
                end_ms=chunk.timestamp_ms + int(segment.end * 1000),
                language_code=getattr(info, "language", None) or language,
            )
            for segment in accepted_segments
            if segment.text.strip()
        ]

    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        return self.transcribe(chunk, language=language)


class MlxWhisperProvider:
    """Whisper on the Apple Silicon GPU via MLX.

    Large-v3-turbo decodes an 8-12 s live buffer in ~0.4 s on an M-series GPU,
    fast enough for sub-2-second live text with large-model accuracy.  The
    same per-segment confidence filters as ``FasterWhisperProvider`` apply.
    """

    def __init__(
        self,
        model: str = "mlx-community/whisper-large-v3-turbo",
        *,
        no_speech_threshold: float = 0.6,
        log_prob_threshold: float = -1.0,
        compression_ratio_threshold: float = 2.4,
        min_avg_logprob: float = -1.0,
        max_no_speech_probability: float = 0.6,
        max_compression_ratio: float = 2.4,
        initial_prompt: str | None = None,
        transcribe=None,
        language_id_model: str | None = None,
        translation_model: str | None = None,
    ) -> None:
        self.model = model
        # The turbo model cannot identify Telugu (0/100 dataset clips) or
        # translate; the full large-v3 model does both (Telugu 93-97%).
        self.language_id_model = language_id_model or model
        self.translation_model = translation_model
        self.no_speech_threshold = no_speech_threshold
        self.log_prob_threshold = log_prob_threshold
        self.compression_ratio_threshold = compression_ratio_threshold
        self.min_avg_logprob = min_avg_logprob
        self.max_no_speech_probability = max_no_speech_probability
        self.max_compression_ratio = max_compression_ratio
        self.initial_prompt = initial_prompt
        self._transcribe = transcribe
        self.last_diagnostics: dict[str, object] = {}
        # Auto-detect chooses only among these (None: any language).
        self.allowed_languages: set[str] | None = None
        self._language_memory = LanguageMemory()

    def _load(self):
        if self._transcribe is None:
            import os

            # Local inference never performs an implicit first-run download.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            import mlx_whisper  # type: ignore[import-not-found]

            _keep_every_mlx_model_loaded()
            self._transcribe = mlx_whisper.transcribe
        return self._transcribe

    def _detect_allowed(self, audio) -> str:
        if len(self.allowed_languages) == 1:
            self.last_language_confidence = 1.0
            return next(iter(self.allowed_languages))
        probabilities = self.detect_language_probabilities(audio)
        chosen = choose_language(probabilities, self.allowed_languages) or next(iter(sorted(self.allowed_languages)))
        allowed_total = sum(probability for code, probability in probabilities.items() if code in self.allowed_languages) or 1.0
        self.last_language_confidence = probabilities.get(chosen, 0.0) / allowed_total
        return chosen

    def detect_language_probabilities(self, audio) -> dict[str, float]:
        """Whisper's language probabilities for the first 30 s (as transcribe does)."""

        import mlx.core as mx  # type: ignore[import-not-found]
        from mlx_whisper.audio import N_FRAMES, N_SAMPLES, log_mel_spectrogram, pad_or_trim  # type: ignore[import-not-found]
        from mlx_whisper.transcribe import ModelHolder  # type: ignore[import-not-found]

        _keep_every_mlx_model_loaded()
        model = ModelHolder.get_model(self.language_id_model, mx.float16)
        mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels, padding=N_SAMPLES)
        _, probabilities = model.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
        return dict(probabilities)

    def warmup(self) -> None:
        import numpy as np  # type: ignore[import-not-found]

        self._load()(np.zeros(16_000, dtype=np.float32), path_or_hf_repo=self.model, temperature=0.0, language="en", verbose=None)
        if self.allowed_languages and len(self.allowed_languages) > 1 and self.language_id_model != self.model:
            self.detect_language_probabilities(np.zeros(16_000, dtype=np.float32))

    def translate_chunk(self, chunk: AudioChunk, language: str, *, _depth: int = 0) -> list[TranscriptDraft]:
        """English translation of non-English speech, straight from the audio.

        Whisper's translation can loop ("I have been suffering ..." twelve
        times), invent text on noise, or skip most of a window. Repeated,
        highly compressible, low-confidence and non-English lines are dropped,
        and a piece whose translation covers too little of it is split at a
        pause and translated in halves.
        """

        import numpy as np  # type: ignore[import-not-found]

        if not self.translation_model:
            return []
        audio = np.asarray(chunk.waveform, dtype=np.float32)
        result = self._load()(
            audio,
            path_or_hf_repo=self.translation_model,
            task="translate",
            language=language,
            condition_on_previous_text=False,
            no_speech_threshold=self.no_speech_threshold,
            logprob_threshold=self.log_prob_threshold,
            compression_ratio_threshold=self.compression_ratio_threshold,
            verbose=None,
        )
        kept: list[TranscriptDraft] = []
        recent: list[str] = []
        covered = 0.0
        for segment in result.get("segments", []):
            text = str(segment.get("text", "")).strip()
            key = " ".join(re.findall(r"[a-z0-9']+", text.lower()))
            letters = [character for character in text if character.isalpha()]
            if not key or key in recent or not letters or sum(character.isascii() for character in letters) / len(letters) < 0.8:
                continue
            log_prob = segment.get("avg_logprob", 0.0)
            # Whisper's own silence rule: high no-speech *and* low confidence.
            if segment.get("compression_ratio", 0.0) > self.max_compression_ratio or log_prob < self.min_avg_logprob or (segment.get("no_speech_prob", 0.0) > self.max_no_speech_probability and log_prob < self.log_prob_threshold):
                continue
            start_ms = chunk.timestamp_ms + int(float(segment["start"]) * 1000)
            end_ms = chunk.timestamp_ms + int(float(segment["end"]) * 1000)
            covered += max(0.0, float(segment["end"]) - float(segment["start"]))
            kept.append(TranscriptDraft(text=text, timestamp=format_relative_timestamp(start_ms), start_ms=start_ms, end_ms=end_ms, language_code="en"))
            recent = (recent + [key])[-3:]
        seconds = len(audio) / chunk.sample_rate
        if _depth < 2 and seconds > 10 and covered < 0.4 * seconds:
            from .reconciliation import split_at_pauses

            halves = split_at_pauses(audio, chunk.sample_rate, seconds / 2 * 0.8)
            if len(halves) > 1:
                retried: list[TranscriptDraft] = []
                for begin, finish in halves:
                    part = AudioChunk(audio=b"", sample_rate=chunk.sample_rate, timestamp_ms=chunk.timestamp_ms + int(begin / chunk.sample_rate * 1000), waveform=np.ascontiguousarray(audio[begin:finish]))
                    retried += self.translate_chunk(part, language, _depth=_depth + 1)
                if sum((draft.end_ms or 0) - (draft.start_ms or 0) for draft in retried) > covered * 1000:
                    return retried
        return kept

    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        import numpy as np  # type: ignore[import-not-found]

        transcribe = self._load()
        if chunk.waveform is None:
            from .audio import decode_audio_payload

            audio = decode_audio_payload(chunk.audio, encoding=chunk.encoding, sample_rate=chunk.sample_rate, channels=chunk.channels).waveform
        else:
            audio = np.asarray(chunk.waveform, dtype=np.float32)
        options: dict[str, object] = {
            "path_or_hf_repo": self.model,
            "condition_on_previous_text": False,
            "no_speech_threshold": self.no_speech_threshold,
            "logprob_threshold": self.log_prob_threshold,
            "compression_ratio_threshold": self.compression_ratio_threshold,
            "verbose": None,
        }
        # Live: greedy only. Final: one retry at a higher temperature; more
        # retries cost ~25% more time without recovering more words.
        options["temperature"] = 0.0 if chunk.live else (0.0, 0.4)
        if language and language != "auto":
            options["language"] = language
        elif self.allowed_languages:
            options["language"] = self._language_memory.get(chunk) or self._language_memory.remember(chunk, self._detect_allowed(audio))
        if self.initial_prompt:
            options["initial_prompt"] = self.initial_prompt
        result = transcribe(audio, **options)
        detected_language = result.get("language") or language
        accepted: list[TranscriptDraft] = []
        rejected: list[dict[str, object]] = []
        for segment in result.get("segments", []):
            text = str(segment.get("text", "")).strip()
            start_ms = chunk.timestamp_ms + int(float(segment["start"]) * 1000)
            end_ms = chunk.timestamp_ms + int(float(segment["end"]) * 1000)
            reasons = []
            if not text:
                reasons.append("empty_text")
            if segment.get("no_speech_prob", 0.0) > self.max_no_speech_probability and segment.get("avg_logprob", 0.0) < self.min_avg_logprob:
                reasons.append("no_speech_probability")
            if segment.get("avg_logprob", 0.0) < self.min_avg_logprob:
                reasons.append("low_average_log_probability")
            if segment.get("compression_ratio", 0.0) > self.max_compression_ratio:
                reasons.append("high_compression_ratio")
            if reasons:
                rejected.append({"text": text, "start_ms": start_ms, "end_ms": end_ms, "rejection_reason": ",".join(reasons)})
                continue
            accepted.append(TranscriptDraft(text=text, timestamp=format_relative_timestamp(start_ms), start_ms=start_ms, end_ms=end_ms, language_code=detected_language))
        self.last_diagnostics = {
            "engine": "mlx_whisper",
            "model": self.model,
            "language": detected_language,
            "segments_rejected": rejected,
            "segments": [{"text": draft.text, "start_ms": draft.start_ms, "end_ms": draft.end_ms} for draft in accepted],
        }
        return accepted


# Live passes re-detect the language at most this often (ms of session audio).
LIVE_LANGUAGE_RECHECK_MS = 10_000


class LanguageMemory:
    """The language last detected in a live session, re-checked every 10 s.

    Detection costs a full extra encoder pass (~0.6 s on the GPU), so live
    passes reuse it; a switch (e.g. English to Telugu) is followed within 10 s.
    """

    def __init__(self) -> None:
        self.language: str | None = None
        self.detected_at_ms: int | None = None

    def get(self, chunk: "AudioChunk") -> str | None:
        if not chunk.live or self.language is None or self.detected_at_ms is None:
            return None
        return self.language if 0 <= chunk.timestamp_ms - self.detected_at_ms < LIVE_LANGUAGE_RECHECK_MS else None

    def remember(self, chunk: "AudioChunk", language: str) -> str:
        if chunk.live:
            self.language, self.detected_at_ms = language, chunk.timestamp_ms
        return language


def _keep_every_mlx_model_loaded() -> None:
    """mlx-whisper caches a single model; keep each one used (turbo for speech,
    large-v3 for language identification and translation) instead of
    reloading on every switch."""

    import importlib

    # mlx_whisper re-exports a *function* named transcribe, which shadows the
    # module of the same name for "import ... as"; load the module itself.
    mlx_transcribe = importlib.import_module("mlx_whisper.transcribe")

    if getattr(mlx_transcribe.ModelHolder, "_vocibot_cache", None) is not None:
        return
    from mlx_whisper.load_models import load_model  # type: ignore[import-not-found]

    cache: dict = {}

    def get_model(cls, model_path, dtype):
        key = (model_path, dtype)
        if key not in cache:
            cache[key] = load_model(model_path, dtype=dtype)
        return cache[key]

    mlx_transcribe.ModelHolder._vocibot_cache = cache
    mlx_transcribe.ModelHolder.get_model = classmethod(get_model)


def choose_language(probabilities: dict[str, float], allowed: set[str] | None) -> str | None:
    """The most likely language among the enabled ones (None: no restriction)."""

    if not allowed:
        return None
    candidates = {code: probability for code, probability in probabilities.items() if code in allowed}
    return max(candidates, key=candidates.get) if candidates else None


def format_relative_timestamp(timestamp_ms: int) -> str:
    """Format consultation-relative time; never use wall-clock time for audio."""

    total_seconds = max(0, int(timestamp_ms // 1000))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
