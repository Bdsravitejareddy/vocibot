from app.providers.diarization import DemoDiarizationProvider, PyannoteDiarizationProvider
from app.providers.speech import AudioChunk, DemoSpeechToTextProvider, FasterWhisperProvider
from app.providers.vad import DemoVoiceActivityDetector, SileroVoiceActivityDetector


def test_local_provider_seams_are_configurable_without_loading_heavy_models() -> None:
    chunk = AudioChunk(audio=b"demo", sample_rate=16000, timestamp_ms=0)
    assert DemoSpeechToTextProvider().transcribe_chunk(chunk) == []
    assert DemoVoiceActivityDetector().has_speech(chunk) is True
    assert DemoDiarizationProvider().diarize(chunk) == []
    assert FasterWhisperProvider(model_size="small", device="cpu").model_size == "small"
    assert SileroVoiceActivityDetector(threshold=0.7).threshold == 0.7
    assert PyannoteDiarizationProvider().diarize.__name__ == "diarize"
