import importlib.util
from typing import Any

from ..config import Settings, settings
from ..providers.ollama_extraction import OllamaClinicalExtractionProvider


def _check_import(module: str) -> str:
    try:
        if importlib.util.find_spec(module) is None:
            return f"unavailable: Python package {module!r} is not installed"
        return "ready"
    except Exception as error:
        return f"unavailable: {error}"


def _provider(status: str, error: str | None = None) -> dict[str, str]:
    result = {"status": status}
    if error:
        result["error"] = error
    return result


def runtime_status(config: Settings = settings) -> dict[str, Any]:
    providers: dict[str, dict[str, str]] = {
        "ollama": _provider("not_used"),
        "silero_vad": _provider("not_used"),
        "faster_whisper": _provider("not_used"),
        "whisperx": _provider("not_used"),
        "pyannote": _provider("not_used"),
    }
    if config.ai_mode == "local":
        for key, module in (("silero_vad", "silero_vad"), ("faster_whisper", "faster_whisper")):
            status = _check_import(module)
            providers[key] = _provider("ready" if status == "ready" else "unavailable", None if status == "ready" else status)
        if config.whisperx_enabled:
            status = _check_import("whisperx")
            providers["whisperx"] = _provider("ready" if status == "ready" else "unavailable", None if status == "ready" else status)
        else:
            providers["whisperx"] = _provider("disabled", "Set WHISPERX_ENABLED=true to enable local alignment")
        if config.diarization_enabled:
            status = _check_import("pyannote.audio")
            providers["pyannote"] = _provider("ready" if status == "ready" else "unavailable", None if status == "ready" else status)
        else:
            providers["pyannote"] = _provider("disabled", "Set DIARIZATION_ENABLED=true to enable local diarization")
        try:
            OllamaClinicalExtractionProvider(base_url=config.ollama_base_url, model=config.ollama_model).check_available()
            providers["ollama"] = _provider("ready")
        except Exception as error:
            providers["ollama"] = _provider("unavailable", str(error))
    return {"mode": config.ai_mode, "backend": {"status": "connected"}, "providers": providers}
