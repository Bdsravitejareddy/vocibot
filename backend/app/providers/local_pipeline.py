from dataclasses import dataclass, field
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


class LocalAudioPipeline:
    def __init__(self, vad: VoiceActivityDetector, stt: SpeechToTextProvider, aligner: WhisperXAligner | None, diarizer: DiarizationProvider | None) -> None:
        self.vad = vad
        self.stt = stt
        self.aligner = aligner
        self.diarizer = diarizer

    def process(self, chunk: AudioChunk) -> PipelineResult:
        result = PipelineResult()
        started = perf_counter()
        activity: ActivityResult = self.vad.detect(chunk)
        result.timings["vad_ms"] = activity.latency_ms or (perf_counter() - started) * 1000
        if not activity.has_speech:
            result.warnings.append(PipelineWarning("VAD_REJECTION", f"Speech probability {activity.probability:.3f} below threshold"))
            return result
        stt_started = perf_counter()
        drafts = self.stt.transcribe(chunk)
        result.timings["transcription_ms"] = (perf_counter() - stt_started) * 1000
        if self.aligner is not None:
            align_started = perf_counter()
            aligned = self.aligner.align(drafts, chunk.audio, chunk.sample_rate)
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
        result.transcripts = [self._with_speaker(draft, turns, chunk.timestamp_ms) for draft in aligned]
        return result

    @staticmethod
    def _with_speaker(draft: TranscriptDraft, turns: list[SpeakerTurn], chunk_start_ms: int) -> TranscriptDraft:
        start = draft.start_ms if draft.start_ms is not None else chunk_start_ms
        end = draft.end_ms if draft.end_ms is not None else start
        if draft.start_ms is not None and draft.start_ms < chunk_start_ms:
            start += chunk_start_ms
            end += chunk_start_ms
        speaker = next((turn.speaker for turn in turns if start < chunk_start_ms + turn.end_ms and end >= chunk_start_ms + turn.start_ms), draft.speaker)
        return TranscriptDraft(text=draft.text, timestamp=draft.timestamp, speaker=speaker, start_ms=start, end_ms=end)
