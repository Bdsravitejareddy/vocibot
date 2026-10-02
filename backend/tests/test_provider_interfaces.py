from app.providers.diarization import DemoDiarizationProvider, PyannoteDiarizationProvider
from app.providers.factory import build_speech_provider
from app.providers.speech import AudioChunk, DemoSpeechToTextProvider, FasterWhisperProvider, MlxWhisperProvider, TranscriptDraft
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


def test_local_speech_provider_auto_selects_gpu_whisper_when_available(monkeypatch) -> None:
    monkeypatch.setattr("app.config.mlx_whisper_available", lambda: True)
    assert isinstance(build_speech_provider(Settings(_env_file=None, ai_mode="local")), MlxWhisperProvider)

    monkeypatch.setattr("app.config.mlx_whisper_available", lambda: False)
    assert isinstance(build_speech_provider(Settings(_env_file=None, ai_mode="local")), FasterWhisperProvider)
    assert isinstance(build_speech_provider(Settings(_env_file=None, ai_mode="local", stt_provider="whisper")), FasterWhisperProvider)


def test_mlx_whisper_filters_low_confidence_segments_and_offsets_timestamps() -> None:
    calls = []

    def fake_transcribe(audio, **options):
        calls.append(options)
        return {"language": "en", "segments": [
            {"start": 0.0, "end": 1.2, "text": " I have fever", "avg_logprob": -0.2, "no_speech_prob": 0.01, "compression_ratio": 1.1},
            {"start": 1.2, "end": 2.0, "text": " Thank you.", "avg_logprob": -1.6, "no_speech_prob": 0.9, "compression_ratio": 1.0},
        ]}

    provider = MlxWhisperProvider(model="local-model", transcribe=fake_transcribe)
    import numpy as np

    drafts = provider.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=5_000, waveform=np.zeros(32_000, dtype=np.float32), live=True), language="en")

    assert drafts == [TranscriptDraft(text="I have fever", timestamp="00:00:05", start_ms=5_000, end_ms=6_200, language_code="en")]
    assert calls[0]["temperature"] == 0.0 and calls[0]["language"] == "en" and calls[0]["path_or_hf_repo"] == "local-model"


def test_cpu_servers_can_use_a_larger_model_for_the_final_transcript(monkeypatch) -> None:
    from app.providers.factory import build_final_speech_provider

    monkeypatch.setattr("app.config.mlx_whisper_available", lambda: False)
    same = Settings(_env_file=None, ai_mode="local", whisper_model="small")
    split = Settings(_env_file=None, ai_mode="local", whisper_model="small", final_whisper_model="large-v3-turbo")

    assert build_final_speech_provider(same) is None
    final = build_final_speech_provider(split)
    assert isinstance(final, FasterWhisperProvider) and final.model_size == "large-v3-turbo"
