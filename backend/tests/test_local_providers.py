from types import SimpleNamespace

from app.providers.diarization import PyannoteDiarizationProvider
from app.providers.speech import AudioChunk, FasterWhisperProvider
from app.providers.vad import SileroVoiceActivityDetector


def chunk() -> AudioChunk:
    return AudioChunk(audio=b"\x00" * 16, sample_rate=16_000, timestamp_ms=1000)


def test_silero_adapter_returns_probability_and_speech_decision() -> None:
    detector = SileroVoiceActivityDetector(threshold=0.5, model=lambda audio, rate: SimpleNamespace(item=lambda: 0.8))
    result = detector.detect(chunk())
    assert result.has_speech is True
    assert result.probability == 0.8


def test_faster_whisper_adapter_preserves_multilingual_text_and_absolute_timestamps() -> None:
    segment = SimpleNamespace(text=" नमस्ते, I have fever ", start=0.25, end=1.5)
    model = SimpleNamespace(transcribe=lambda audio, **kwargs: ([segment], object()))
    drafts = FasterWhisperProvider(model_size="small", model=model).transcribe(chunk())
    assert drafts[0].text == "नमस्ते, I have fever"
    assert drafts[0].start_ms == 1250
    assert drafts[0].end_ms == 2500


def test_pyannote_adapter_maps_configured_speaker_labels() -> None:
    class Annotation:
        def itertracks(self, yield_label=True):
            yield SimpleNamespace(start=0.1, end=1.2), None, "SPEAKER_00"

    provider = PyannoteDiarizationProvider(pipeline=lambda _: Annotation(), speaker_map={"SPEAKER_00": "DOCTOR"})
    turns = provider.diarize(b"audio", 16_000)
    assert turns[0].speaker == "DOCTOR"
    assert turns[0].start_ms == 100
