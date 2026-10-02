from pathlib import Path

import pytest


def test_packaged_backend_contains_silero_vad_model() -> None:
    packaged_backend = Path(__file__).parents[2] / "dist" / "runtime" / "backend" / "vocibot-api"
    if not packaged_backend.exists():
        pytest.skip("packaged backend has not been built")

    model = packaged_backend / "_internal" / "silero_vad" / "data" / "silero_vad.jit"
    assert model.is_file(), f"packaged backend is missing required VAD model: {model}"


def test_packaged_backend_contains_faster_whisper_vad_model() -> None:
    packaged_backend = Path(__file__).parents[2] / "dist" / "runtime" / "backend" / "vocibot-api"
    if not packaged_backend.exists():
        pytest.skip("packaged backend has not been built")

    model = packaged_backend / "_internal" / "faster_whisper" / "assets" / "silero_vad_v6.onnx"
    assert model.is_file(), f"packaged backend is missing required Whisper VAD model: {model}"
