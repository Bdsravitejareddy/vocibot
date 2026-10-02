from app.config import Settings
from app.services.runtime_status import runtime_status


def test_demo_runtime_status_is_explicitly_demo() -> None:
    result = runtime_status(Settings(ai_mode="demo"))
    assert result["mode"] == "demo"
    assert result["backend"]["status"] == "connected"


def test_local_runtime_status_reports_provider_health_without_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.services.runtime_status._check_import", lambda _module: "ready")
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    result = runtime_status(Settings(ai_mode="local", whisperx_enabled=False, diarization_enabled=False))
    assert result["mode"] == "local"
    assert result["providers"]["ollama"]["status"] in {"ready", "unavailable"}
    assert result["providers"]["whisperx"]["status"] == "disabled"
    assert result["providers"]["pyannote"]["status"] == "disabled"
    assert result["providers"]["speech_to_text"]["status"] == "missing_model"
    assert "demo" not in str(result).lower()


def test_local_runtime_status_reports_selected_indic_engine_without_exposing_model_path(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "indic-multi.nemo"
    checkpoint.write_bytes(b"checkpoint")
    monkeypatch.setattr("app.services.runtime_status._check_import", lambda module: "ready")

    result = runtime_status(Settings(ai_mode="local", stt_provider="indic_conformer", indic_conformer_model_path=str(checkpoint)))

    assert result["providers"]["speech_to_text"]["engine"] == "indic_conformer"
    assert result["providers"]["speech_to_text"]["status"] == "configured"
    assert str(checkpoint) not in str(result)
