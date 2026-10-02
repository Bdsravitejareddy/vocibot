"""Shared test setup: an isolated database per run and signed-in API clients."""

import os
import secrets
import tempfile

# Must run before the app is imported: settings are read at import time.
_TEST_DIR = tempfile.mkdtemp(prefix="vocibot-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR}/vocibot-test.sqlite"
os.environ.setdefault("RECORDINGS_DIR", f"{_TEST_DIR}/recordings")

TEST_PASSWORD = "correct-horse-battery"


def sign_in(client, *, role: str = "clinician", username: str | None = None) -> dict:
    """Create an account directly and sign the TestClient in as it."""

    from app.db import SessionLocal
    from app.services.auth import create_user

    name = username or f"dr-{secrets.token_hex(4)}"
    with SessionLocal() as session:
        create_user(session, username=name, display_name=f"Dr {name}", password=TEST_PASSWORD, role=role)
        session.commit()
    response = client.post("/api/auth/login", json={"username": name, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["user"]
