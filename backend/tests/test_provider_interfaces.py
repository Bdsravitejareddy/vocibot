from app.providers.diarization import DemoDiarizationProvider, PyannoteDiarizationProvider
from app.providers.factory import build_speech_provider
from app.providers.speech import AudioChunk, DemoSpeechToTextProvider, FasterWhisperProvider
from app.providers.vad import DemoVoiceActivityDetector, SileroVoiceActivityDetector
from app.config import Settings


def test_local_provider_seams_are_configurable_without_loading_heavy_models() -> None:
    chunk = AudioChunk(audio=b"demo", sample_rate=16000, timestamp_ms=0)
    assert DemoSpeechToTextProvider().transcribe_chunk(chunk) == []
    assert DemoVoiceActivityDetector().has_speech(chunk) is True
    assert DemoDiarizationProvider().diarize(chunk) == []
    assert FasterWhisperProvider(model_size="small", device="cpu").model_size == "small"
    assert SileroVoiceActivityDetector(threshold=0.7).threshold == 0.7
    assert PyannoteDiarizationProvider().diarize.__name__ == "diarize"


def test_local_speech_provider_defaults_to_whisper_without_loading_model() -> None:
    config = Settings(_env_file=None, ai_mode="local")

    provider = build_speech_provider(config)

    assert isinstance(provider, FasterWhisperProvider)
