from fastapi.testclient import TestClient
import numpy as np
import time

import pytest

from app.main import app
from app.providers.local_pipeline import LocalAudioPipeline, PipelineResult
from app.providers.speech import TranscriptDraft


@pytest.fixture(autouse=True)
def _authorised(monkeypatch):
    # These tests cover audio handling; stream authorisation is tested in test_auth.py.
    monkeypatch.setattr("app.api.audio.authorise_stream", lambda websocket, consultation_id: True)


class FakePipeline:
    def __init__(self):
        self.language = None

    def process(self, chunk, language=None):
        self.language = language
        return PipelineResult(transcripts=[TranscriptDraft(text="I have fever", timestamp="", speaker="PATIENT", start_ms=0, end_ms=300)], timings={"vad_ms": 1.0, "transcription_ms": 2.0}, diagnostics={"language": language})


def test_audio_websocket_persists_received_audio_debug_wav(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: FakePipeline())
    monkeypatch.setattr("app.api.audio.settings.audio_debug_dir", str(tmp_path))
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(np.ones(25_600, dtype="<f4").tobytes())
            assert websocket.receive_json()["type"] == "status"
            transcript = websocket.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["text"] == "I have fever"
            websocket.send_json({"type": "stop"})
            assert _receive_until_stopped(websocket)
    assert (tmp_path / "test.wav").exists()
    assert (tmp_path / "test.json").exists()


def test_audio_websocket_emits_ready_status_transcript_and_stopped(monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: FakePipeline())
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(np.ones(25_600, dtype="<f4").tobytes())
            assert websocket.receive_json()["type"] == "status"
            transcript = websocket.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["text"] == "I have fever"
            websocket.send_json({"type": "stop"})
            assert _receive_until_stopped(websocket)


def test_audio_websocket_warms_the_pipeline_before_signaling_ready(monkeypatch) -> None:
    warmed = []

    class WarmablePipeline(FakePipeline):
        def warmup(self):
            warmed.append(True)

    monkeypatch.setattr("app.api.audio.build_local_pipeline", WarmablePipeline)
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/warmup-test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"

    assert warmed == [True]


def test_audio_websocket_forwards_language_and_rejects_unsupported_code(monkeypatch) -> None:
    pipeline = FakePipeline()
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: pipeline)
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/language-test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le", "language": "te"})
            ready = websocket.receive_json()
            assert ready["type"] == "ready"
            assert ready["language"] == "te"
            websocket.send_bytes(np.ones(25_600, dtype="<f4").tobytes())
            assert websocket.receive_json()["type"] == "status"
            assert pipeline.language == "te"
            websocket.receive_json()
            websocket.send_json({"type": "stop"})
            assert _receive_until_stopped(websocket)

        with client.websocket_connect("/api/consultations/invalid-language/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "language": "xx"})
            error = websocket.receive_json()
            assert error["type"] == "error"
            assert "Unsupported language code" in error["message"]


def test_audio_websocket_surfaces_exact_pipeline_failure(monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: (_ for _ in ()).throw(RuntimeError("WhisperX dependency unavailable: No module named whisperx")))
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            message = websocket.receive_json()
            assert message["type"] == "error"
            assert message["message"] == "Local audio pipeline is unavailable. See backend logs for details."
            assert "WhisperX dependency unavailable" not in message["message"]


def test_audio_websocket_stop_reconciles_the_complete_capture_once(monkeypatch) -> None:
    class FakeSTT:
        def __init__(self):
            self.waveforms = []

        def transcribe_chunk(self, chunk, language=None):
            self.waveforms.append(chunk.waveform.copy())
            return [TranscriptDraft(text="final transcript", timestamp="00:00:00", start_ms=0, end_ms=500)]

    class FinalPassPipeline:
        def __init__(self):
            self.stt = FakeSTT()

        def process(self, chunk, language=None):
            return PipelineResult(timings={"transcription_ms": 1.0})

    pipeline = FinalPassPipeline()
    replaced = []
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: pipeline)
    monkeypatch.setattr("app.api.audio.settings.ai_mode", "local")
    monkeypatch.setattr("app.api.audio.settings.audio_debug_dir", "")
    monkeypatch.setattr("app.api.audio.settings.asr_min_speech_seconds", 0.1)
    monkeypatch.setattr("app.api.audio.replace_with_reconciled_transcript", lambda session, consultation_id, drafts, **_kwargs: replaced.append(drafts))

    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/reconcile-test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            captured = np.ones(16_000, dtype="<f4")
            websocket.send_bytes(captured.tobytes())
            websocket.send_json({"type": "stop"})
            assert _receive_until_stopped(websocket)

    assert len(pipeline.stt.waveforms) == 1
    np.testing.assert_allclose(pipeline.stt.waveforms[0], captured, rtol=0, atol=1e-6)
    assert len(replaced) == 1
    assert [draft.text for draft in replaced[0]] == ["final transcript"]


def test_audio_websocket_stop_is_acknowledged_when_record_replacement_fails(monkeypatch) -> None:
    class FakeSTT:
        def transcribe_chunk(self, chunk, language=None):
            return [TranscriptDraft(text="final transcript", timestamp="00:00:00", start_ms=0, end_ms=500)]

    class FinalPassPipeline:
        def __init__(self):
            self.stt = FakeSTT()

        def process(self, chunk, language=None):
            return PipelineResult(timings={"transcription_ms": 1.0})

    monkeypatch.setattr("app.api.audio.build_local_pipeline", FinalPassPipeline)
    monkeypatch.setattr("app.api.audio.settings.ai_mode", "local")
    monkeypatch.setattr("app.api.audio.settings.audio_debug_dir", "")
    monkeypatch.setattr("app.api.audio.settings.asr_min_speech_seconds", 0.1)
    monkeypatch.setattr(
        "app.api.audio.replace_with_reconciled_transcript",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("extractor timed out")),
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/reconcile-failure/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(np.ones(8_000, dtype="<f4").tobytes())
            websocket.send_json({"type": "stop"})
            received = []
            for _ in range(5):
                received.append(websocket.receive_json())
                if received[-1]["type"] == "stopped":
                    break

    finalization_messages = [message for message in received if message["type"] in {"warning", "stopped"}]
    assert [message["type"] for message in finalization_messages] == ["warning", "stopped"]
    assert finalization_messages[0]["category"] == "FINALIZATION"


def test_audio_websocket_stop_has_a_bounded_finalization_timeout(monkeypatch) -> None:
    class BlockingSTT:
        def transcribe_chunk(self, chunk, language=None):
            time.sleep(0.2)
            return [TranscriptDraft(text="late final", timestamp="00:00:00", start_ms=0, end_ms=500)]

    class BlockingFinalPassPipeline:
        def __init__(self):
            self.stt = BlockingSTT()

        def process(self, chunk, language=None):
            return PipelineResult(timings={"transcription_ms": 1.0})

    monkeypatch.setattr("app.api.audio.build_local_pipeline", BlockingFinalPassPipeline)
    monkeypatch.setattr("app.api.audio.settings.ai_mode", "local")
    monkeypatch.setattr("app.api.audio.settings.audio_debug_dir", "")
    monkeypatch.setattr("app.api.audio.settings.asr_min_speech_seconds", 0.1)
    monkeypatch.setattr("app.api.audio.settings.asr_finalization_timeout_seconds", 0.02)

    started = time.perf_counter()
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/reconcile-timeout/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(np.ones(8_000, dtype="<f4").tobytes())
            websocket.send_json({"type": "stop"})
            messages = []
            for _ in range(5):
                messages.append(websocket.receive_json())
                if messages[-1]["type"] == "stopped":
                    break

    assert time.perf_counter() - started < 0.15
    finalization_messages = [message for message in messages if message["type"] in {"warning", "stopped"}]
    assert [message["type"] for message in finalization_messages] == ["warning", "stopped"]
    assert "too long" in finalization_messages[0]["message"]


def _receive_until_stopped(websocket) -> bool:
    for _ in range(10):
        if websocket.receive_json()["type"] == "stopped":
            return True
    return False


def test_audio_websocket_holds_back_unsettled_text_as_partial(monkeypatch) -> None:
    class TrailingSpeechPipeline:
        def process(self, chunk, language=None):
            end_ms = chunk.timestamp_ms + int(len(chunk.waveform) / 16)
            return PipelineResult(transcripts=[
                TranscriptDraft(text="I have fever", timestamp="", start_ms=0, end_ms=400),
                TranscriptDraft(text="since two", timestamp="", start_ms=500, end_ms=end_ms),
            ])

    monkeypatch.setattr("app.api.audio.build_local_pipeline", TrailingSpeechPipeline)
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/partial-test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(np.ones(16_000, dtype="<f4").tobytes())
            assert websocket.receive_json()["type"] == "status"
            transcript = websocket.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["text"] == "I have fever"
            partial = websocket.receive_json()
            assert partial == {"type": "partial", "text": "since two", "start_ms": 500}
            websocket.send_json({"type": "stop"})
            assert _receive_until_stopped(websocket)
