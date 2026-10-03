from fastapi.testclient import TestClient
import numpy as np

from app.main import app
from app.providers.speech import AudioChunk, FasterWhisperProvider, MlxWhisperProvider, choose_language

KANNADA_FIRST = {"kn": 0.46, "te": 0.31, "ar": 0.12, "hi": 0.06, "en": 0.05}


def test_auto_detect_only_chooses_an_enabled_language() -> None:
    assert choose_language(KANNADA_FIRST, {"en", "te", "hi"}) == "te"
    assert choose_language(KANNADA_FIRST, None) is None
    assert choose_language({"ar": 1.0}, {"en", "te"}) is None


def test_mlx_engine_transcribes_in_the_best_enabled_language() -> None:
    calls = []
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: calls.append(options) or {"segments": [], "language": options.get("language")})
    provider.detect_language_probabilities = lambda audio: KANNADA_FIRST
    provider.allowed_languages = {"en", "te", "hi"}
    chunk = AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(16_000, dtype=np.float32))

    provider.transcribe_chunk(chunk, language=None)
    provider.transcribe_chunk(chunk, language="hi")  # an explicit choice is kept

    assert [call["language"] for call in calls] == ["te", "hi"]


def test_a_single_enabled_language_skips_detection() -> None:
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: {"segments": [], "language": options["language"]})
    provider.detect_language_probabilities = lambda audio: (_ for _ in ()).throw(AssertionError("detection should be skipped"))
    provider.allowed_languages = {"te"}
    assert provider._detect_allowed(np.zeros(16_000, dtype=np.float32)) == "te"


def test_cpu_engine_restricts_detection_too() -> None:
    class Model:
        def detect_language(self, audio):
            return "kn", 0.46, list(KANNADA_FIRST.items())

    provider = FasterWhisperProvider(model_size="small", device="cpu")
    provider.allowed_languages = {"en", "te", "hi"}
    assert provider._detect_allowed(Model(), np.zeros(16_000, dtype=np.float32)) == "te"


def test_language_settings_are_saved_and_cannot_be_empty() -> None:
    with TestClient(app) as client:
        before = client.get("/api/settings/languages").json()
        assert {"code": "kn", "name": "Kannada"} in before["available"] and before["available"][0]["code"] == "en"
        try:
            saved = client.put("/api/settings/languages", json={"enabled": ["en", "te", "hi", "zz"]}).json()
            assert saved["enabled"] == ["en", "te", "hi"]
            assert client.get("/api/settings/languages").json()["enabled"] == ["en", "te", "hi"]
            assert client.put("/api/settings/languages", json={"enabled": []}).status_code == 422
        finally:
            client.put("/api/settings/languages", json={"enabled": before["enabled"]})


def test_a_disabled_language_cannot_be_chosen_for_a_consultation(monkeypatch) -> None:
    from app.providers.local_pipeline import PipelineResult

    class Pipeline:
        def process(self, chunk, language=None):
            return PipelineResult()

    monkeypatch.setattr("app.api.audio.build_local_pipeline", Pipeline)
    with TestClient(app) as client:
        before = client.get("/api/settings/languages").json()["enabled"]
        try:
            client.put("/api/settings/languages", json={"enabled": ["en", "te"]})
            with client.websocket_connect("/api/consultations/lang-check/audio") as websocket:
                websocket.send_json({"sample_rate": 16_000, "language": "mr"})
                error = websocket.receive_json()
            assert error["type"] == "error" and "Enable it in Settings" in error["message"]
        finally:
            client.put("/api/settings/languages", json={"enabled": before})


def test_live_passes_reuse_the_detected_language_for_ten_seconds() -> None:
    detections = []
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: {"segments": [], "language": options["language"]})
    provider.detect_language_probabilities = lambda audio: detections.append(1) or KANNADA_FIRST
    provider.allowed_languages = {"en", "te"}

    # 4 s buffers: detected at the end of the first (4 s), re-checked once
    # 10 s of audio have passed since (the buffer ending at 14.5 s).
    for timestamp_ms in (0, 3_000, 9_000, 10_500, 12_000):
        provider.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=timestamp_ms, waveform=np.zeros(64_000, dtype=np.float32), live=True))
    assert len(detections) == 2

    provider.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(16_000, dtype=np.float32)))
    assert len(detections) == 3  # the final (non-live) pass always detects


def _live(start_ms: int, seconds: float) -> AudioChunk:
    return AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=start_ms, waveform=np.zeros(int(seconds * 16_000), dtype=np.float32), live=True)


def test_a_detection_on_a_short_greeting_is_not_locked_in() -> None:
    """'Namaste' / 'Hi doctor' alone was detected as English and kept for the
    whole Hindi or Telugu consultation, so the live preview stayed empty."""

    detections = []
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: {"segments": [], "language": options["language"]})
    provider.detect_language_probabilities = lambda audio: detections.append(1) or KANNADA_FIRST
    provider.allowed_languages = {"en", "te"}
    provider.transcribe_chunk(_live(0, 1.5))
    provider.transcribe_chunk(_live(0, 2.5))
    assert len(detections) == 2
    provider.transcribe_chunk(_live(0, 3.5))
    provider.transcribe_chunk(_live(0, 4.0))
    assert len(detections) == 3


def test_a_stuck_buffer_is_rechecked_and_rejected_passes_forget_the_language() -> None:
    detections = []
    segment = {"segments": [{"text": "foreign", "start": 0.0, "end": 3.0, "avg_logprob": -1.6, "no_speech_prob": 0.1, "compression_ratio": 1.0}]}
    good = {"segments": [{"text": "జ్వరం ఉంది", "start": 0.0, "end": 3.0, "avg_logprob": -0.3, "no_speech_prob": 0.1, "compression_ratio": 1.0}]}
    replies = iter([good, good, segment, good])
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: {**next(replies), "language": options["language"]})
    provider.detect_language_probabilities = lambda audio: detections.append(1) or KANNADA_FIRST
    provider.allowed_languages = {"en", "te"}
    provider.transcribe_chunk(_live(0, 4))  # detected
    # Nothing accepted, so the buffer start stays at 0 while audio grows:
    # re-checked by the end of the audio, not the (stuck) start.
    provider.transcribe_chunk(_live(0, 15))
    assert len(detections) == 2
    provider.transcribe_chunk(_live(0, 16))  # every line rejected: forget
    provider.transcribe_chunk(_live(0, 17))
    assert len(detections) == 3


TELUGU_NEAR_HINDI = {"hi": 0.40, "te": 0.30, "en": 0.20, "ta": 0.10}
CLEAR_HINDI = {"hi": 0.85, "te": 0.05, "en": 0.05, "ur": 0.05}


def test_the_primary_language_wins_near_ties_but_not_clear_speech() -> None:
    enabled = {"en", "te", "hi"}
    assert choose_language(TELUGU_NEAR_HINDI, enabled) == "hi"
    assert choose_language(TELUGU_NEAR_HINDI, enabled, primary="te") == "te"
    assert choose_language(CLEAR_HINDI, enabled, primary="te") == "hi"
    assert choose_language({"en": 0.9, "te": 0.1}, enabled, primary="te") == "en"


def test_the_engine_uses_the_primary_language_and_reports_weighted_confidence() -> None:
    calls = []
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: calls.append(options) or {"segments": [], "language": options.get("language")})
    provider.detect_language_probabilities = lambda audio: TELUGU_NEAR_HINDI
    provider.allowed_languages = {"en", "te", "hi"}
    provider.primary_language = "te"
    provider.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(16_000, dtype=np.float32)))
    assert calls[0]["language"] == "te"
    assert abs(provider.last_language_confidence - 0.6) < 1e-6  # 0.3x3 / (0.9 + 0.4 + 0.2)


def test_primary_language_setting() -> None:
    with TestClient(app) as client:
        before = client.get("/api/settings/languages").json()
        try:
            saved = client.put("/api/settings/languages", json={"enabled": ["en", "te", "hi"], "primary": "te"}).json()
            assert saved["primary"] == "te"
            # Omitted: unchanged.
            assert client.put("/api/settings/languages", json={"enabled": ["en", "te", "hi"]}).json()["primary"] == "te"
            # Must be enabled.
            assert client.put("/api/settings/languages", json={"enabled": ["en", "te", "hi"], "primary": "ta"}).status_code == 422
            # Disabling it clears it.
            assert client.put("/api/settings/languages", json={"enabled": ["en", "hi"]}).json()["primary"] is None
            client.put("/api/settings/languages", json={"enabled": ["en", "te", "hi"], "primary": "te"})
            assert client.put("/api/settings/languages", json={"enabled": ["en", "te", "hi"], "primary": None}).json()["primary"] is None
        finally:
            client.put("/api/settings/languages", json={"enabled": before["enabled"], "primary": before.get("primary")})


def test_live_detection_hears_recent_session_audio_not_just_the_short_buffer() -> None:
    heard = []
    provider = MlxWhisperProvider(model="local", transcribe=lambda audio, **options: {"segments": [], "language": options["language"]})
    provider.detect_language_probabilities = lambda audio: heard.append(len(audio) / 16_000) or TELUGU_NEAR_HINDI
    provider.allowed_languages = {"en", "te", "hi"}
    # 0-2 s (too short to keep), then the same buffer grown to 2.5 s.
    provider.transcribe_chunk(_live(0, 2))
    provider.transcribe_chunk(_live(0, 2.5))
    # A line was committed: the next buffer starts at 2.5 s and is 1 s long,
    # but detection hears all 3.5 s of the session so far.
    provider.transcribe_chunk(_live(2_500, 1))
    assert heard == [2.0, 2.5, 3.5]
    # 3.5 s heard: remembered, no detection for the next passes.
    provider.transcribe_chunk(_live(2_500, 2))
    assert len(heard) == 3
    # Recent audio is capped at 8 s.
    provider._language_memory.forget()
    provider.transcribe_chunk(_live(4_500, 8))
    assert heard[-1] == 8.0
