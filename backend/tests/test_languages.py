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

    for timestamp_ms in (0, 3_000, 9_000, 10_500, 12_000):
        provider.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=timestamp_ms, waveform=np.zeros(16_000, dtype=np.float32), live=True))
    assert len(detections) == 2  # at 0 s and again at 10.5 s

    provider.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(16_000, dtype=np.float32)))
    assert len(detections) == 3  # the final (non-live) pass always detects
