from datetime import timedelta

from fastapi.testclient import TestClient
import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.db import Base, SessionLocal, get_session
from app.main import app
from app.models import AuthSession, Consultation, Patient, SecurityEvent, User
from app.services.auth import hash_password, utcnow, verify_password
from conftest import TEST_PASSWORD, sign_in

PATIENT = {"patient_id": "SHARED-ID-1", "age": 40, "sex": "Female"}


@pytest.fixture
def fresh_database():
    """An empty database for first-run setup tests."""

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield factory
    app.dependency_overrides.pop(get_session, None)


def test_passwords_are_salted_scrypt_hashes() -> None:
    first, second = hash_password("a long passphrase"), hash_password("a long passphrase")
    assert first.startswith("scrypt$") and first != second
    assert verify_password("a long passphrase", first)
    assert not verify_password("a long passphrasE", first)


def test_first_run_setup_creates_the_admin_once_and_claims_existing_records(fresh_database) -> None:
    with fresh_database() as session:
        legacy_patient = Patient(patient_identifier="LEGACY-1", age=50, sex="Male")
        session.add(legacy_patient)
        session.flush()
        session.add(Consultation(patient_id=legacy_patient.id))
        session.commit()

    with TestClient(app) as client:
        assert client.get("/api/auth/status").json() == {"setup_required": True, "user": None}
        weak = client.post("/api/auth/setup", json={"username": "admin", "display_name": "Clinic Admin", "password": "short"})
        assert weak.status_code == 422
        created = client.post("/api/auth/setup", json={"username": "Admin", "display_name": "Clinic Admin", "password": TEST_PASSWORD})
        assert created.status_code == 200
        assert created.json()["user"]["username"] == "admin" and created.json()["user"]["role"] == "admin"
        assert client.get("/api/auth/status").json()["user"]["username"] == "admin"
        again = client.post("/api/auth/setup", json={"username": "intruder", "display_name": "X", "password": TEST_PASSWORD})
        assert again.status_code == 409
        assert client.get("/api/consultations").json()["items"][0]["patient"]["patient_identifier"] == "LEGACY-1"

    with fresh_database() as session:
        assert session.scalars(select(SecurityEvent.event)).all().count("setup_completed") == 1


def test_clinical_endpoints_require_sign_in() -> None:
    with TestClient(app) as client:
        assert client.get("/api/consultations").status_code == 401
        assert client.post("/api/consultations", json=PATIENT).status_code == 401
        assert client.get("/api/auth/me").status_code == 401


def test_failed_sign_ins_lock_the_account_with_one_generic_message() -> None:
    with TestClient(app) as client:
        user = sign_in(client)
        client.post("/api/auth/logout")
        unknown = client.post("/api/auth/login", json={"username": "nobody-here", "password": "whatever-it-is"})
        wrong = client.post("/api/auth/login", json={"username": user["username"], "password": "wrong-password!"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["detail"] == wrong.json()["detail"] == "Incorrect username or password."
        for _ in range(4):
            client.post("/api/auth/login", json={"username": user["username"], "password": "wrong-password!"})
        locked = client.post("/api/auth/login", json={"username": user["username"], "password": TEST_PASSWORD})
        assert locked.status_code == 401 and "Too many failed attempts" in locked.json()["detail"]

    with SessionLocal() as session:
        events = session.scalars(select(SecurityEvent.event).where(SecurityEvent.subject_user_id == user["id"])).all()
    assert "account_locked" in events and events.count("login_failed") >= 5


def test_each_clinician_sees_only_their_own_patients_and_consultations(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.services.recordings.settings.recordings_dir", str(tmp_path))
    with TestClient(app) as alice, TestClient(app) as bob:
        sign_in(alice)
        sign_in(bob)
        mine = alice.post("/api/consultations", json=PATIENT).json()
        theirs = bob.post("/api/consultations", json={**PATIENT, "patient_name": "Bob's patient"}).json()

        # Same identifier, different clinicians: two separate patient records.
        assert mine["patient"]["id"] != theirs["patient"]["id"]
        assert [item["id"] for item in alice.get("/api/consultations").json()["items"]] == [mine["id"]]
        assert [item["id"] for item in bob.get("/api/consultations").json()["items"]] == [theirs["id"]]

        for method, path, body in (
            ("get", f"/api/consultations/{mine['id']}", None),
            ("post", f"/api/consultations/{mine['id']}/stop", None),
            ("post", f"/api/consultations/{mine['id']}/reanalyse", None),
            ("post", f"/api/consultations/{mine['id']}/approve", {"record": {}}),
            ("get", f"/api/consultations/{mine['id']}/recordings/any/audio", None),
            ("delete", f"/api/consultations/{mine['id']}", None),
        ):
            response = bob.request(method, path, json=body)
            assert response.status_code == 404, (method, path, response.status_code)
        assert alice.get(f"/api/consultations/{mine['id']}").status_code == 200

        with pytest.raises(WebSocketDisconnect):
            with bob.websocket_connect(f"/api/consultations/{mine['id']}/audio") as websocket:
                websocket.receive_json()


def test_audio_stream_requires_sign_in_ownership_and_an_allowed_origin(monkeypatch) -> None:
    from app.providers.local_pipeline import PipelineResult

    class QuietPipeline:
        def process(self, chunk, language=None):
            return PipelineResult()

    monkeypatch.setattr("app.api.audio.build_local_pipeline", QuietPipeline)
    with TestClient(app) as client, TestClient(app) as anonymous:
        sign_in(client)
        consultation = client.post("/api/consultations", json=PATIENT).json()
        path = f"/api/consultations/{consultation['id']}/audio"

        with pytest.raises(WebSocketDisconnect):
            with anonymous.websocket_connect(path) as websocket:
                websocket.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path, headers={"origin": "https://evil.example"}) as websocket:
                websocket.receive_json()
        with client.websocket_connect(path, headers={"origin": "http://127.0.0.1:3000"}) as websocket:
            websocket.send_json({"sample_rate": 16_000, "channels": 1, "encoding": "pcm_f32le"})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_bytes(np.zeros(1_600, dtype="<f4").tobytes())
            websocket.send_json({"type": "stop"})
            while websocket.receive_json()["type"] != "stopped":
                pass


def test_temporary_passwords_must_be_changed_before_clinical_work() -> None:
    with TestClient(app) as admin_client, TestClient(app) as doctor:
        sign_in(admin_client, role="admin")
        created = admin_client.post("/api/admin/users", json={"username": "dr-new", "display_name": "Dr New", "password": "temporary-pass-1", "role": "clinician"})
        assert created.status_code == 201 and created.json()["must_change_password"] is True

        assert doctor.post("/api/auth/login", json={"username": "dr-new", "password": "temporary-pass-1"}).status_code == 200
        blocked = doctor.get("/api/consultations")
        assert blocked.status_code == 403 and "temporary password" in blocked.json()["detail"]

        assert doctor.post("/api/auth/password", json={"current_password": "wrong", "new_password": "a-better-password"}).status_code == 403
        assert doctor.post("/api/auth/password", json={"current_password": "temporary-pass-1", "new_password": "a-better-password"}).status_code == 204
        # Changing the password signs out every browser.
        assert doctor.get("/api/auth/me").status_code == 401
        assert doctor.post("/api/auth/login", json={"username": "dr-new", "password": "a-better-password"}).status_code == 200
        assert doctor.get("/api/consultations").status_code == 200


def test_only_admins_manage_accounts_and_deactivation_signs_the_user_out() -> None:
    with TestClient(app) as admin_client, TestClient(app) as doctor:
        admin = sign_in(admin_client, role="admin")
        clinician = sign_in(doctor)
        assert doctor.get("/api/admin/users").status_code == 403
        assert doctor.post("/api/admin/users", json={"username": "x-user", "display_name": "X", "password": TEST_PASSWORD}).status_code == 403

        assert admin_client.patch(f"/api/admin/users/{admin['id']}", json={"is_active": False}).status_code == 409
        assert admin_client.patch(f"/api/admin/users/{clinician['id']}", json={"is_active": False}).json()["is_active"] is False
        assert doctor.get("/api/auth/me").status_code == 401
        assert doctor.post("/api/auth/login", json={"username": clinician["username"], "password": TEST_PASSWORD}).status_code == 401

        events = admin_client.get("/api/admin/security-events").json()
        assert any(event["event"] == "user_updated" and event["subject_user_id"] == clinician["id"] for event in events)


def test_idle_sessions_expire() -> None:
    with TestClient(app) as client:
        user = sign_in(client)
        assert client.get("/api/auth/me").status_code == 200
        with SessionLocal() as session:
            for record in session.scalars(select(AuthSession).where(AuthSession.user_id == user["id"])):
                record.last_seen_at = utcnow() - timedelta(minutes=31)
            session.commit()
        assert client.get("/api/auth/me").status_code == 401


def test_session_cookie_is_http_only_and_not_readable_by_scripts() -> None:
    with TestClient(app) as client:
        with SessionLocal() as session:
            from app.services.auth import create_user

            create_user(session, username="cookie-check", display_name="Cookie Check", password=TEST_PASSWORD)
            session.commit()
        response = client.post("/api/auth/login", json={"username": "cookie-check", "password": TEST_PASSWORD})
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
        with SessionLocal() as session:
            stored = session.scalars(select(AuthSession.token_hash)).all()
        token = client.cookies.get("vocibot_session")
        assert token not in stored and len(stored[0]) == 64


def test_discarding_is_recorded_in_the_security_log() -> None:
    with TestClient(app) as client:
        user = sign_in(client)
        consultation = client.post("/api/consultations", json=PATIENT).json()
        assert client.delete(f"/api/consultations/{consultation['id']}").status_code == 204
    with SessionLocal() as session:
        event = session.scalars(select(SecurityEvent).where(SecurityEvent.event == "consultation_discarded", SecurityEvent.actor_user_id == user["id"])).one()
    assert event.detail["session_code"] == consultation["session_code"]
