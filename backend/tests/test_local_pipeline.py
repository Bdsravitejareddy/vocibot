from app.providers.local_pipeline import LocalAudioPipeline
from app.providers.speech import AudioChunk, TranscriptDraft
import numpy as np
from app.providers.vad import ActivityResult


class FakeVAD:
    def detect(self, chunk):
        return ActivityResult(probability=0.9, has_speech=True, latency_ms=1.0)


class FakeSTT:
    def transcribe_chunk(self, chunk, language=None):
        return [TranscriptDraft(text="I have fever", timestamp="", start_ms=0, end_ms=500)]


class FakeAligner:
    def align(self, segments, audio, sample_rate, language=None):
        return [TranscriptDraft(text=segments[0].text, timestamp="", speaker="PATIENT", start_ms=20, end_ms=520)]


class FakeDiarizer:
    def diarize(self, audio, sample_rate):
        return []


def test_pipeline_filters_and_times_speech_stages() -> None:
    pipeline = LocalAudioPipeline(FakeVAD(), FakeSTT(), FakeAligner(), FakeDiarizer())
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=1000, waveform=np.ones(16_000, dtype=np.float32)))
    assert [draft.text for draft in result.transcripts] == ["I have fever"]
    assert result.transcripts[0].start_ms == 1020
    assert result.timings["vad_ms"] >= 0


def test_pipeline_reports_silence_without_transcripts() -> None:
    class SilentVAD:
        def detect(self, chunk):
            return ActivityResult(probability=0.1, has_speech=False, latency_ms=1.0)

    pipeline = LocalAudioPipeline(SilentVAD(), FakeSTT(), FakeAligner(), FakeDiarizer())
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=0, waveform=np.ones(512, dtype=np.float32)))
    assert result.transcripts == []
    assert result.warnings[0].category == "VAD_REJECTION"


def test_pipeline_exposes_window_vad_and_asr_diagnostics() -> None:
    class DiagnosticVAD(FakeVAD):
        def detect(self, chunk):
            return ActivityResult(probability=0.8, has_speech=True, latency_ms=1.0, frame_count=4, speech_frame_count=3, speech_duration_ms=96.0)

    class DiagnosticSTT(FakeSTT):
        last_diagnostics = {"language": "en", "language_probability": 0.9, "segments": [{"no_speech_prob": 0.1, "avg_logprob": -0.2}]}

    pipeline = LocalAudioPipeline(DiagnosticVAD(), DiagnosticSTT(), None, None)
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=2000, waveform=np.ones(512, dtype=np.float32)))

    assert result.diagnostics["vad_probability"] == 0.8
    assert result.diagnostics["speech_duration_ms"] == 96.0
    assert result.diagnostics["asr"]["language"] == "en"


def test_pipeline_passes_selected_language_and_keeps_detected_language_on_transcript() -> None:
    class LanguageAwareSTT:
        last_diagnostics = {"language": "te", "language_probability": 0.94}

        def __init__(self):
            self.language = None

        def transcribe_chunk(self, chunk, language=None):
            self.language = language
            return [TranscriptDraft(text="నమస్కారం", timestamp="00:00:00", start_ms=0, end_ms=500, language_code="te")]

    stt = LanguageAwareSTT()
    pipeline = LocalAudioPipeline(FakeVAD(), stt, None, None)

    result = pipeline.process(
        AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=0, waveform=np.ones(16_000, dtype=np.float32)),
        language="te",
    )

    assert stt.language == "te"
    assert result.transcripts[0].language_code == "te"
    assert result.diagnostics["asr"]["language"] == "te"


def test_pipeline_rejects_transcript_timestamps_outside_audio_window() -> None:
    class OutOfBoundsSTT(FakeSTT):
        def transcribe_chunk(self, chunk, language=None):
            return [TranscriptDraft(text="hallucinated", timestamp="", start_ms=0, end_ms=5000)]

    pipeline = LocalAudioPipeline(FakeVAD(), OutOfBoundsSTT(), None, None)
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=1000, waveform=np.ones(512, dtype=np.float32)))

    assert result.transcripts == []
    assert result.warnings[-1].category == "TIMESTAMP_REJECTED"


def test_pipeline_clips_small_live_model_timestamp_padding_to_the_audio_boundary() -> None:
    class PaddedSTT(FakeSTT):
        def transcribe_chunk(self, chunk, language=None):
            return [TranscriptDraft(text="live word", timestamp="", start_ms=0, end_ms=500)]

    pipeline = LocalAudioPipeline(FakeVAD(), PaddedSTT(), None, None)
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=0, waveform=np.ones(7_200, dtype=np.float32)))

    assert [draft.text for draft in result.transcripts] == ["live word"]
    assert result.transcripts[0].end_ms == 450
