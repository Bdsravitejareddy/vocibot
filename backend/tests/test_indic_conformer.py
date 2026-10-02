import numpy as np
import pytest

from app.providers.indic_conformer import IndicConformerProvider
from app.providers.speech import AudioChunk


def test_indic_conformer_preserves_regional_script_and_passes_language_id(tmp_path) -> None:
    calls = []

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            calls.append((audio, kwargs))
            return ["నమస్కారం"]

    provider = IndicConformerProvider(
        model_path=str(tmp_path / "indic-te.nemo"),
        model_loader=lambda _: FakeModel(),
    )
    chunk = AudioChunk(
        audio=b"",
        sample_rate=16_000,
        timestamp_ms=1_000,
        waveform=np.zeros(320, dtype=np.float32),
    )

    drafts = provider.transcribe_chunk(chunk, language="te")

    assert drafts[0].text == "నమస్కారం"
    assert calls[0][1]["language_id"] == "te"
    assert calls[0][1]["logprobs"] is False
    assert provider.last_diagnostics["language"] == "te"
    assert provider.last_diagnostics["engine"] == "indic_conformer"


def test_indic_conformer_loads_model_only_when_first_transcribing(tmp_path) -> None:
    loads = []

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            return ["હેલો"]

    def load(model_path):
        loads.append(model_path)
        return FakeModel()

    provider = IndicConformerProvider(model_path=str(tmp_path / "indic-gu.nemo"), model_loader=load)

    assert loads == []
    provider.transcribe_chunk(
        AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(320, dtype=np.float32)),
        language="gu",
    )

    assert loads == [str(tmp_path / "indic-gu.nemo")]


def test_indic_conformer_reports_missing_optional_nemo_dependency(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "indic-te.nemo"
    model_path.write_bytes(b"test checkpoint")
    real_import = __import__

    def import_without_nemo(name, *args, **kwargs):
        if name.startswith("nemo.collections.asr"):
            raise ImportError("No module named nemo")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", import_without_nemo)
    provider = IndicConformerProvider(model_path=str(model_path))
    chunk = AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(320, dtype=np.float32))

    with pytest.raises(RuntimeError, match=r"backend\[indic-asr\]"):
        provider.transcribe_chunk(chunk, language="te")
