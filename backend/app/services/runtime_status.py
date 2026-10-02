import importlib.util
import os
from pathlib import Path
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
        "indic_conformer": _provider("not_used"),
        "speech_to_text": {"status": "not_used", "engine": config.stt_provider, "model": ""},
        "whisperx": _provider("not_used"),
        "pyannote": _provider("not_used"),
    }
    if config.ai_mode == "local":
        for key, module in (("silero_vad", "onnxruntime" if config.vad_engine == "onnx" else "silero_vad"),):
            status = _check_import(module)
            providers[key] = _provider("ready" if status == "ready" else "unavailable", None if status == "ready" else status)
        stt_provider = config.resolved_stt_provider
        if stt_provider == "mlx_whisper":
            status = _check_import("mlx_whisper")
            configured_path = Path(config.mlx_whisper_model).expanduser()
            cache_path = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / ("models--" + config.mlx_whisper_model.replace("/", "--"))
            cached = configured_path.is_dir() or (cache_path.exists() and any((cache_path / "snapshots").glob("*/*.safetensors")))
            readiness = "ready" if status == "ready" and cached else "missing_dependency" if status != "ready" else "missing_model"
            error = status if status != "ready" else None if cached else "MLX Whisper model is not provisioned locally; run scripts/provision_local_models.py --engine mlx_whisper before offline use"
            providers["speech_to_text"] = {"status": readiness, "engine": "mlx_whisper", "model": config.mlx_whisper_model, **({"error": error} if error else {})}
        elif stt_provider == "whisper":
            status = _check_import("faster_whisper")
            configured_path = Path(config.whisper_model).expanduser()
            cache_path = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub" / f"models--Systran--faster-whisper-{config.whisper_model}"
            cached = configured_path.is_dir() or any((cache_path / "snapshots").glob("*/model.bin")) if cache_path.exists() else configured_path.is_dir()
            readiness = "ready" if status == "ready" and cached else "missing_dependency" if status != "ready" else "missing_model"
            error = status if status != "ready" else None if cached else "Whisper model is not provisioned locally; run scripts/provision_local_models.py before offline use"
            providers["faster_whisper"] = _provider(readiness, error)
            providers["speech_to_text"] = {"status": readiness, "engine": "whisper", "model": config.whisper_model, **({"error": error} if error else {})}
        elif stt_provider == "indic_conformer":
            dependency_status = _check_import("nemo.collections.asr")
            model_available = bool(config.indic_conformer_model_path and Path(config.indic_conformer_model_path).is_file())
            error = None if dependency_status == "ready" else dependency_status
            if not model_available:
                error = "IndicConformer checkpoint is missing; provision a local model and set INDIC_CONFORMER_MODEL_PATH"
            ready = dependency_status == "ready" and model_available
            readiness = "configured" if ready else "missing_dependency" if dependency_status != "ready" else "missing_model"
            if ready:
                error = "Checkpoint and dependency are configured; model load and inference have not been verified."
            providers["indic_conformer"] = _provider(readiness, error)
            providers["speech_to_text"] = {"status": readiness, "engine": "indic_conformer", "model": "configured local checkpoint" if model_available else "missing", **({"error": error} if error else {})}
        else:
            error = f"Unsupported STT_PROVIDER={config.stt_provider!r}; expected auto, mlx_whisper, whisper or indic_conformer"
            providers["speech_to_text"] = {"status": "unavailable", "engine": config.stt_provider, "model": "", "error": error}
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
