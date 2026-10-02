from dataclasses import dataclass, field, replace
from time import perf_counter

from .alignment import WhisperXAligner
from .diarization import DiarizationProvider, SpeakerTurn
from .speech import AudioChunk, SpeechToTextProvider, TranscriptDraft
from .vad import ActivityResult, VoiceActivityDetector


@dataclass(frozen=True)
class PipelineWarning:
    category: str
    message: str


@dataclass
class PipelineResult:
    transcripts: list[TranscriptDraft] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[PipelineWarning] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)


class LocalAudioPipeline:
    def __init__(self, vad: VoiceActivityDetector, stt: SpeechToTextProvider, aligner: WhisperXAligner | None, diarizer: DiarizationProvider | None, *, timestamp_tolerance_ms: int = 100) -> None:
        self.vad = vad
        self.stt = stt
        self.aligner = aligner
        self.diarizer = diarizer
        self.timestamp_tolerance_ms = timestamp_tolerance_ms

    def warmup(self) -> None:
        """Make local models ready before the client begins streaming audio."""

        for provider in (self.vad, self.stt):
            warmup = getattr(provider, "warmup", None)
            if callable(warmup):
                warmup()

    def process(self, chunk: AudioChunk, language: str | None = None) -> PipelineResult:
        result = PipelineResult()
        started = perf_counter()
        if chunk.waveform is None:
            from .audio import decode_audio_payload

            decoded = decode_audio_payload(
                chunk.audio,
                encoding=chunk.encoding,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels,
            )
            chunk = replace(chunk, waveform=decoded.waveform, sample_rate=decoded.sample_rate, channels=1)
        activity: ActivityResult = self.vad.detect(chunk)
        result.timings["vad_ms"] = activity.latency_ms or (perf_counter() - started) * 1000
        result.diagnostics.update({
            "window_start_ms": chunk.timestamp_ms,
            "window_end_ms": chunk.timestamp_ms + int(len(chunk.waveform) / chunk.sample_rate * 1000),
            "vad_probability": activity.probability,
            "vad_frame_count": activity.frame_count,
            "speech_frame_count": activity.speech_frame_count,
            "speech_duration_ms": activity.speech_duration_ms,
            "accepted": activity.has_speech,
            "requested_language": language,
        })
        if not activity.has_speech:
            result.diagnostics["rejection_reason"] = "insufficient_speech_activity"
            result.warnings.append(PipelineWarning("VAD_REJECTION", f"Speech probability {activity.probability:.3f} below threshold"))
            return result
        speech_proportion = activity.speech_frame_count / activity.frame_count if activity.frame_count else None
        chunk = replace(chunk, vad_speech_proportion=speech_proportion)
        stt_started = perf_counter()
        drafts = self.stt.transcribe_chunk(chunk, language=language)
        result.timings["transcription_ms"] = (perf_counter() - stt_started) * 1000
        result.diagnostics["asr"] = getattr(self.stt, "last_diagnostics", {})
        detected_language = result.diagnostics["asr"].get("language") if isinstance(result.diagnostics["asr"], dict) else None
        detected_language = detected_language or (language if language and language != "auto" else None)
        drafts = [
            replace(draft, language_code=draft.language_code or detected_language)
            for draft in drafts
        ]
        if self.aligner is not None:
            align_started = perf_counter()
            aligned = self.aligner.align(drafts, chunk.audio, chunk.sample_rate, language=detected_language)
            result.timings["alignment_ms"] = (perf_counter() - align_started) * 1000
        else:
            aligned = drafts
            result.warnings.append(PipelineWarning("ALIGNMENT_DISABLED", "WhisperX alignment is disabled; set WHISPERX_ENABLED=true to enable its local checkpoint"))
        if self.diarizer is not None:
            diar_started = perf_counter()
            turns = self.diarizer.diarize(chunk.audio, chunk.sample_rate)
            result.timings["diarization_ms"] = (perf_counter() - diar_started) * 1000
        else:
            turns = []
            result.warnings.append(PipelineWarning("DIARIZATION_DISABLED", "pyannote diarization is disabled; set DIARIZATION_ENABLED=true to enable its local model"))
        window_start_ms = chunk.timestamp_ms
        window_end_ms = window_start_ms + int(len(chunk.waveform) / chunk.sample_rate * 1000)
        accepted: list[TranscriptDraft] = []
        rejected = 0
        for draft in aligned:
            candidate = self._with_speaker(draft, turns, window_start_ms)
            candidate = self._clip_small_timestamp_padding(candidate, window_start_ms, window_end_ms)
            if (
                candidate.start_ms is None
                or candidate.end_ms is None
                or not window_start_ms <= candidate.start_ms <= candidate.end_ms <= window_end_ms
            ):
                rejected += 1
                result.warnings.append(
                    PipelineWarning(
                        "TIMESTAMP_REJECTED",
                        f"Transcript timestamps {candidate.start_ms}-{candidate.end_ms}ms fall outside "
                        f"audio window {window_start_ms}-{window_end_ms}ms",
                    )
                )
                continue
            accepted.append(candidate)
        result.diagnostics["accepted_transcript_count"] = len(accepted)
        result.diagnostics["rejected_transcript_count"] = rejected
        result.transcripts = accepted
        return result

    def _clip_small_timestamp_padding(self, draft: TranscriptDraft, window_start_ms: int, window_end_ms: int) -> TranscriptDraft:
        """Clip Whisper's short live-window padding without admitting distant timestamps."""

        if draft.start_ms is None or draft.end_ms is None:
            return draft
        start = max(window_start_ms, draft.start_ms) if draft.start_ms >= window_start_ms - self.timestamp_tolerance_ms else draft.start_ms
        end = min(window_end_ms, draft.end_ms) if draft.end_ms <= window_end_ms + self.timestamp_tolerance_ms else draft.end_ms
        return replace(draft, start_ms=start, end_ms=end)

    @staticmethod
    def _with_speaker(draft: TranscriptDraft, turns: list[SpeakerTurn], chunk_start_ms: int) -> TranscriptDraft:
        start = draft.start_ms if draft.start_ms is not None else chunk_start_ms
        end = draft.end_ms if draft.end_ms is not None else start
        if draft.start_ms is not None and draft.start_ms < chunk_start_ms:
            start += chunk_start_ms
            end += chunk_start_ms
        speaker = next((turn.speaker for turn in turns if start < chunk_start_ms + turn.end_ms and end >= chunk_start_ms + turn.start_ms), draft.speaker)
        return TranscriptDraft(text=draft.text, timestamp=draft.timestamp, speaker=speaker, start_ms=start, end_ms=end, language_code=draft.language_code)
