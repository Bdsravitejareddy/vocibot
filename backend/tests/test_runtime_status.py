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


def test_local_runtime_status_reports_installed_indic_languages_without_exposing_the_folder(monkeypatch, tmp_path) -> None:
    for code in ("te", "hi"):
        (tmp_path / code).mkdir()
        (tmp_path / code / "model.onnx").write_bytes(b"onnx")
        (tmp_path / code / "vocab.json").write_text("{}")
    (tmp_path / "features.npz").write_bytes(b"npz")
    monkeypatch.setattr("app.services.runtime_status._check_import", lambda module: "ready")

    result = runtime_status(Settings(ai_mode="local", indic_asr_models_dir=str(tmp_path)))

    assert result["providers"]["indic_conformer"] == {"status": "ready", "languages": ["hi", "te"]}
    assert str(tmp_path) not in str(result)


def test_runtime_status_reports_text_translation_languages(monkeypatch, tmp_path) -> None:
    (tmp_path / "vocab").mkdir()
    (tmp_path / "vocab" / "model.SRC").write_bytes(b"spm")
    (tmp_path / "model.bin").write_bytes(b"ct2")
    monkeypatch.setattr("app.services.runtime_status._check_import", lambda module: "ready")
    result = runtime_status(Settings(ai_mode="local", indic_translation_model_dir=str(tmp_path), indic_text_translation_languages="hi"))
    assert result["providers"]["indic_translation"] == {"status": "ready", "languages": ["hi"]}
