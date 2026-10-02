from types import SimpleNamespace
import sys
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


def test_silero_warmup_exercises_a_live_sized_audio_window() -> None:
    calls = []

    class Model:
        def __call__(self, audio, sample_rate):
            calls.append((audio.numel(), sample_rate))
            return SimpleNamespace(item=lambda: 0.8)

    SileroVoiceActivityDetector(model=Model()).warmup()

    assert calls == [(512, 16_000)] * 16


def test_faster_whisper_adapter_preserves_multilingual_text_and_relative_timestamps() -> None:
    segment = SimpleNamespace(text=" नमस्ते, I have fever ", start=0.25, end=1.5)
    model = SimpleNamespace(transcribe=lambda audio, **kwargs: ([segment], object()))
    drafts = FasterWhisperProvider(model_size="small", model=model).transcribe(chunk())
    assert drafts[0].text == "नमस्ते, I have fever"
    assert drafts[0].start_ms == 1250
    assert drafts[0].end_ms == 2500
    assert drafts[0].timestamp == "00:00:01"


def test_faster_whisper_records_model_confidence_diagnostics() -> None:
    segment = SimpleNamespace(text="hello", start=0.0, end=0.5, avg_logprob=-0.4, no_speech_prob=0.2, compression_ratio=1.1)
    info = SimpleNamespace(language="en", language_probability=0.97)
    captured = {}

    def transcribe(audio, **kwargs):
        captured.update(kwargs)
        return iter([segment]), info

    drafts = FasterWhisperProvider(model_size="small", model=SimpleNamespace(transcribe=transcribe)).transcribe(chunk())

    assert drafts[0].text == "hello"
    assert captured["vad_filter"] is True
    assert captured["condition_on_previous_text"] is False
    assert captured["beam_size"] == 1
    assert drafts[0].timestamp


def test_faster_whisper_passes_configured_initial_prompt() -> None:
    captured = {}

    def transcribe(audio, **kwargs):
        captured.update(kwargs)
        return iter([]), SimpleNamespace(language="en", language_probability=0.9)

    FasterWhisperProvider(model=SimpleNamespace(transcribe=transcribe), initial_prompt="Dolo 650, cough, nausea").transcribe(chunk())

    assert captured["initial_prompt"] == "Dolo 650, cough, nausea"


def test_faster_whisper_forwards_explicit_language_to_model() -> None:
    captured = {}

    def transcribe(audio, **kwargs):
        captured.update(kwargs)
        return iter([]), SimpleNamespace(language="te", language_probability=0.99)

    provider = FasterWhisperProvider(model=SimpleNamespace(transcribe=transcribe))
    provider.transcribe_chunk(chunk(), language="te")

    assert captured["language"] == "te"


def test_faster_whisper_loads_with_configured_cpu_parallelism(monkeypatch) -> None:
    captured = {}

    class Model:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    provider = FasterWhisperProvider(model_size="small", device="cpu", compute_type="int8", cpu_threads=6, num_workers=2)

    provider._load()

    assert captured["args"] == ("small",)
    assert captured["kwargs"] == {"device": "cpu", "compute_type": "int8", "cpu_threads": 6, "num_workers": 2}


def test_faster_whisper_rejects_low_confidence_segments() -> None:
    segment = SimpleNamespace(text="invented sentence", start=0.0, end=0.5, avg_logprob=-2.0, no_speech_prob=0.9, compression_ratio=1.1)
    info = SimpleNamespace(language="en", language_probability=0.2)
    provider = FasterWhisperProvider(model=SimpleNamespace(transcribe=lambda audio, **kwargs: (iter([segment]), info)))
    assert provider.transcribe(chunk()) == []
    assert provider.last_diagnostics["segments_rejected"][0]["rejection_reason"]


def test_pyannote_adapter_maps_configured_speaker_labels() -> None:
    class Annotation:
        def itertracks(self, yield_label=True):
            yield SimpleNamespace(start=0.1, end=1.2), None, "SPEAKER_00"

    provider = PyannoteDiarizationProvider(pipeline=lambda _: Annotation(), speaker_map={"SPEAKER_00": "DOCTOR"})
    turns = provider.diarize(b"audio", 16_000)
    assert turns[0].speaker == "DOCTOR"
    assert turns[0].start_ms == 100
