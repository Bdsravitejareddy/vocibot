from app.providers.local_pipeline import LocalAudioPipeline
from app.providers.speech import AudioChunk, TranscriptDraft
from app.providers.vad import ActivityResult


class FakeVAD:
    def detect(self, chunk):
        return ActivityResult(probability=0.9, has_speech=True, latency_ms=1.0)


class FakeSTT:
    def transcribe(self, chunk):
        return [TranscriptDraft(text="I have fever", timestamp="", start_ms=0, end_ms=500)]


class FakeAligner:
    def align(self, segments, audio, sample_rate):
        return [TranscriptDraft(text=segments[0].text, timestamp="", speaker="PATIENT", start_ms=20, end_ms=520)]


class FakeDiarizer:
    def diarize(self, audio, sample_rate):
        return []


def test_pipeline_filters_and_times_speech_stages() -> None:
    pipeline = LocalAudioPipeline(FakeVAD(), FakeSTT(), FakeAligner(), FakeDiarizer())
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=1000))
    assert [draft.text for draft in result.transcripts] == ["I have fever"]
    assert result.transcripts[0].start_ms == 1020
    assert result.timings["vad_ms"] >= 0


def test_pipeline_reports_silence_without_transcripts() -> None:
    class SilentVAD:
        def detect(self, chunk):
            return ActivityResult(probability=0.1, has_speech=False, latency_ms=1.0)

    pipeline = LocalAudioPipeline(SilentVAD(), FakeSTT(), FakeAligner(), FakeDiarizer())
    result = pipeline.process(AudioChunk(audio=b"audio", sample_rate=16_000, timestamp_ms=0))
    assert result.transcripts == []
    assert result.warnings[0].category == "VAD_REJECTION"
