import hashlib
import wave

from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.main import app
from app.providers.local_pipeline import PipelineResult
from app.providers.speech import TranscriptDraft


class QuietPipeline:
    def process(self, chunk, language=None):
        return PipelineResult()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.recordings.settings.recordings_dir", str(tmp_path))
    monkeypatch.setattr("app.api.audio.build_local_pipeline", QuietPipeline)
    monkeypatch.setattr("app.api.audio.settings.audio_debug_dir", "")
    with TestClient(app) as test_client:
        yield test_client


def record_session(client, seconds: float = 1.0, language: str = "en") -> dict:
    created = client.post("/api/consultations", json={"patient_id": f"REC-{np.random.randint(1e9)}", "age": 40, "sex": "Female"}).json()
    with client.websocket_connect(f"/api/consultations/{created['id']}/audio") as websocket:
        websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le", "language": language})
        assert websocket.receive_json()["type"] == "ready"
        tone = (0.2 * np.sin(np.linspace(0, 440 * 2 * np.pi * seconds, int(16_000 * seconds)))).astype("<f4")
        websocket.send_bytes(tone.tobytes())
        websocket.send_json({"type": "stop"})
        while websocket.receive_json()["type"] != "stopped":
            pass
    client.post(f"/api/consultations/{created['id']}/stop")
    return client.get(f"/api/consultations/{created['id']}").json()


def test_each_session_gets_a_readable_unique_id(client) -> None:
    first = client.post("/api/consultations", json={"patient_id": "ID-1", "age": 40, "sex": "Female"}).json()
    second = client.post("/api/consultations", json={"patient_id": "ID-2", "age": 40, "sex": "Female"}).json()

    assert first["session_code"].startswith("VB-") and len(first["session_code"]) == len("VB-20261002-") + 6
    assert first["session_code"] != second["session_code"]
    for created in (first, second):
        client.delete(f"/api/consultations/{created['id']}")


def test_live_session_audio_is_stored_named_by_session_id_with_a_fingerprint(client, tmp_path) -> None:
    consultation = record_session(client, seconds=1.5)

    [recording] = consultation["recordings"]
    path = tmp_path / recording["file_name"]
    assert recording["file_name"] == f"{consultation['session_code']}.wav"
    assert recording["available"] and recording["language_code"] == "en"
    assert recording["duration_ms"] == 1_500
    assert recording["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    with wave.open(str(path)) as handle:
        assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate(), handle.getnframes()) == (1, 2, 16_000, 24_000)

    audio = client.get(f"/api/consultations/{consultation['id']}/recordings/{recording['id']}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"
    assert audio.content == path.read_bytes()

    assert client.delete(f"/api/consultations/{consultation['id']}").status_code == 204
    assert not path.exists()


def test_retranscription_uses_stored_audio_and_refuses_altered_files(client, tmp_path, monkeypatch) -> None:
    consultation = record_session(client)
    [recording] = consultation["recordings"]
    heard = []

    class FakeSTT:
        def transcribe_chunk(self, chunk, language=None):
            heard.append((len(chunk.waveform), language))
            return [TranscriptDraft(text="It feels really dizzy.", timestamp="00:00:00", start_ms=0, end_ms=900)]

    monkeypatch.setattr("app.api.consultations.build_speech_provider", lambda _settings: FakeSTT())
    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda _settings: (_ for _ in ()).throw(RuntimeError("no llm in tests")))

    response = client.post(f"/api/consultations/{consultation['id']}/retranscribe")
    assert response.status_code == 200
    assert [segment["text"] for segment in response.json()["transcript"]] == ["It feels really dizzy."]
    assert heard == [(16_000, "en")]

    path = tmp_path / recording["file_name"]
    path.write_bytes(path.read_bytes()[:-2] + b"\x00\x01")
    tampered = client.post(f"/api/consultations/{consultation['id']}/retranscribe")
    assert tampered.status_code == 409 and "altered" in tampered.json()["detail"]
    client.delete(f"/api/consultations/{consultation['id']}")


def test_consultations_without_audio_cannot_be_retranscribed(client) -> None:
    created = client.post("/api/consultations", json={"patient_id": "NO-AUDIO-1", "age": 40, "sex": "Female"}).json()
    client.post(f"/api/consultations/{created['id']}/stop")

    response = client.post(f"/api/consultations/{created['id']}/retranscribe")

    assert response.status_code == 409 and "no stored audio" in response.json()["detail"]
    client.delete(f"/api/consultations/{created['id']}")
