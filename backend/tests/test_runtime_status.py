from app.config import Settings
from app.services.runtime_status import runtime_status


def test_demo_runtime_status_is_explicitly_demo() -> None:
    result = runtime_status(Settings(ai_mode="demo"))
    assert result["mode"] == "demo"
    assert result["backend"]["status"] == "connected"


def test_local_runtime_status_reports_provider_health_without_fallback(monkeypatch) -> None:
    monkeypatch.setattr("app.services.runtime_status._check_import", lambda module: "ready" if module == "numpy" else "unavailable: missing")
    result = runtime_status(Settings(ai_mode="local", whisperx_enabled=False, diarization_enabled=False))
    assert result["mode"] == "local"
    assert result["providers"]["ollama"]["status"] in {"ready", "unavailable"}
    assert result["providers"]["whisperx"]["status"] == "disabled"
    assert result["providers"]["pyannote"]["status"] == "disabled"
    assert "demo" not in str(result).lower()
