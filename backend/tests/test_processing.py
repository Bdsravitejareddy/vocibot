import threading
import time

from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.db import SessionLocal
from app.domain.types import CandidateClinicalUpdate, ClinicalRecord, EvidenceStatus, ExtractionResult, Speaker
from app.main import app
from app.models import Consultation
from app.providers.local_pipeline import PipelineResult
from app.providers.speech import TranscriptDraft
from app.services.inference import BATCH, ENGINE, LIVE, split_at_pauses
from app.services.processing import resume_unfinished, wait_until_idle
from conftest import sign_in


class ChunkSTT:
    """Answers each final-transcription piece with its length."""

    def __init__(self):
        self.pieces = []

    def transcribe_chunk(self, chunk, language=None):
        seconds = len(chunk.waveform) / 16_000
        self.pieces.append(round(seconds, 1))
        return [TranscriptDraft(text=f"I have had a fever for {len(self.pieces)} days.", timestamp="00:00:00", start_ms=0, end_ms=int(seconds * 1000) - 100)]


class Pipeline:
    def __init__(self, stt):
        self.stt = stt

    def process(self, chunk, language=None):
        return PipelineResult()


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.recordings.settings.recordings_dir", str(tmp_path))
    monkeypatch.setattr("app.api.audio.compress_soon", lambda: None)
    monkeypatch.setattr("app.api.audio.settings.audio_debug_dir", "")
    with TestClient(app) as test_client:
        sign_in(test_client)
        yield test_client


def speech_with_pauses(seconds: int) -> np.ndarray:
    """A tone that pauses for 0.5 s every 10 s, like sentences."""

    t = np.arange(seconds * 16_000) / 16_000
    tone = 0.3 * np.sin(2 * np.pi * 220 * t)
    tone[(t % 10) > 9.5] = 0.0
    return tone.astype("<f4")


def record(client, audio: np.ndarray) -> str:
    created = client.post("/api/consultations", json={"patient_id": f"P-{time.time_ns()}", "age": 30, "sex": "Female"}).json()
    with client.websocket_connect(f"/api/consultations/{created['id']}/audio") as websocket:
        websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le", "language": "en"})
        assert websocket.receive_json()["type"] == "ready"
        for start in range(0, len(audio), 16_000 * 5):
            websocket.send_bytes(audio[start:start + 16_000 * 5].tobytes())
        websocket.send_json({"type": "stop"})
        while websocket.receive_json()["type"] != "stopped":
            pass
    return created["id"]


def test_stop_returns_immediately_and_the_note_follows_from_the_saved_recording(client, monkeypatch) -> None:
    stt = ChunkSTT()
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: Pipeline(stt))

    class Extractor:
        def extract(self, transcript, current):
            return ExtractionResult(proposed_record=ClinicalRecord(), candidates=[CandidateClinicalUpdate(field_name="presenting_symptoms", value=["fever"], source_segment_ids=[transcript[0].id], speaker=Speaker.PATIENT, status=EvidenceStatus.SUPPORTED)])

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda _settings: Extractor())
    consultation_id = record(client, speech_with_pauses(75))

    stopped = client.post(f"/api/consultations/{consultation_id}/stop").json()
    assert stopped["status"] == "READY_FOR_REVIEW"
    assert stopped["processing"]["status"] in {"queued", "transcribing", "writing_note", "done"}
    assert client.post(f"/api/consultations/{consultation_id}/approve", json={"record": {}}).status_code in {200, 409}

    assert wait_until_idle(10)
    done = client.get(f"/api/consultations/{consultation_id}").json()
    assert done["processing"]["status"] == "done"
    # 75 s was transcribed as pieces of about 30 s, cut at pauses.
    assert len(stt.pieces) == 3 and all(20 <= piece <= 36 for piece in stt.pieces[:2]) and abs(sum(stt.pieces) - 75) < 0.2
    starts = [segment["timestamp"] for segment in done["transcript"]]
    assert starts[0] == "00:00:00" and starts[1] >= "00:00:20" and starts[2] >= "00:00:50"
    assert done["record"]["presenting_symptoms"] == ["fever"]


def test_a_failed_note_keeps_the_final_transcript_and_reports_the_failure(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: Pipeline(ChunkSTT()))
    monkeypatch.setattr("app.services.consultations.reanalyse_consultation", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("model crashed")))
    consultation_id = record(client, speech_with_pauses(5))

    client.post(f"/api/consultations/{consultation_id}/stop")
    assert wait_until_idle(10)
    failed = client.get(f"/api/consultations/{consultation_id}").json()

    assert failed["processing"]["status"] == "failed" and "model crashed" in failed["processing"]["error"]
    assert failed["transcript"][0]["text"] == "I have had a fever for 1 days."
    assert client.post(f"/api/consultations/{consultation_id}/approve", json={"record": {}}).status_code == 200


def test_queued_work_resumes_after_a_restart(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: Pipeline(ChunkSTT()))
    consultation_id = record(client, speech_with_pauses(3))
    client.post(f"/api/consultations/{consultation_id}/stop")
    assert wait_until_idle(10)
    with SessionLocal() as session:
        consultation = session.get(Consultation, consultation_id)
        consultation.processing_status = "transcribing"  # as if the app stopped mid-job
        consultation.processing_plan = "transcribe,note"
        session.commit()

    assert resume_unfinished() >= 1
    assert wait_until_idle(10)
    assert client.get(f"/api/consultations/{consultation_id}").json()["processing"]["status"] == "done"


def test_the_shared_engine_serves_live_previews_before_batch_work() -> None:
    order = []
    gate = threading.Event()
    ENGINE.submit(BATCH, gate.wait, 5)  # occupies the worker
    batch = [ENGINE.submit(BATCH, order.append, f"batch-{index}") for index in range(3)]
    live = ENGINE.submit(LIVE, order.append, "live")
    gate.set()
    for future in [*batch, live]:
        future.result(5)
    assert order[0] == "live"


def test_live_preview_slots_are_limited_but_audio_is_still_recorded(client, monkeypatch) -> None:
    monkeypatch.setattr("app.api.audio.build_local_pipeline", lambda: Pipeline(ChunkSTT()))
    monkeypatch.setattr("app.services.inference.settings.max_live_sessions", 0)
    created = client.post("/api/consultations", json={"patient_id": "BUSY-1", "age": 30, "sex": "Female"}).json()
    with client.websocket_connect(f"/api/consultations/{created['id']}/audio") as websocket:
        websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
        ready = websocket.receive_json()
        assert ready["type"] == "ready" and ready["live_preview"] is False
        assert "recorded" in websocket.receive_json()["message"]
        websocket.send_bytes(speech_with_pauses(2).tobytes())
        websocket.send_json({"type": "stop"})
        while websocket.receive_json()["type"] != "stopped":
            pass
    assert client.get(f"/api/consultations/{created['id']}").json()["recordings"][0]["duration_ms"] == 2_000


def test_cuts_land_in_pauses() -> None:
    audio = speech_with_pauses(65)
    spans = split_at_pauses(audio, 16_000, 30)
    assert spans[0][0] == 0 and spans[-1][1] == len(audio)
    for _, end in spans[:-1]:
        assert abs(audio[end]) == 0.0  # inside a pause
