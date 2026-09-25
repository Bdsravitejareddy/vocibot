from fastapi.testclient import TestClient

from app.main import app
from app.providers.local_pipeline import LocalAudioPipeline, PipelineResult
from app.providers.speech import TranscriptDraft


class FakePipeline:
    def process(self, chunk):
        return PipelineResult(transcripts=[TranscriptDraft(text="I have fever", timestamp="", speaker="PATIENT", start_ms=0, end_ms=500)], timings={"vad_ms": 1.0, "transcription_ms": 2.0})


def test_audio_websocket_emits_ready_status_transcript_and_stopped(monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: FakePipeline())
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(b"audio")
            assert websocket.receive_json()["type"] == "status"
            transcript = websocket.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["text"] == "I have fever"
            websocket.send_json({"type": "stop"})
            assert websocket.receive_json()["type"] == "stopped"


def test_audio_websocket_surfaces_exact_pipeline_failure(monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: (_ for _ in ()).throw(RuntimeError("WhisperX dependency unavailable: No module named whisperx")))
    with TestClient(app) as client:
        with client.websocket_connect("/api/consultations/test/audio") as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1})
            message = websocket.receive_json()
            assert message["type"] == "error"
            assert "WhisperX dependency unavailable" in message["message"]
