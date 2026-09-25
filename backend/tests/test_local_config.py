import pytest

from app.config import Settings
from app.providers.factory import LocalProviderError, build_extraction_provider
from app.providers.ollama_extraction import OllamaClinicalExtractionProvider


def test_local_settings_use_practical_development_models() -> None:
    settings = Settings(ai_mode="local")
    assert settings.ai_mode == "local"
    assert settings.whisper_model == "small"
    assert settings.ollama_model == "llama3.1:8b"


def test_local_mode_does_not_fall_back_when_ollama_dependency_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(OllamaClinicalExtractionProvider, "check_available", lambda self: (_ for _ in ()).throw(RuntimeError("connection refused")))
    with pytest.raises(LocalProviderError, match="connection refused"):
        build_extraction_provider(Settings(ai_mode="local"))


def test_demo_mode_stays_deterministic() -> None:
    provider = build_extraction_provider(Settings(ai_mode="demo"))
    assert provider.__class__.__name__ == "DemoClinicalExtractionProvider"
