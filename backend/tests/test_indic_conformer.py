import json

import numpy as np

from app.providers.indic_conformer import IndicConformerProvider, IndicRoutingProvider, _ctc_words, _lines
from app.providers.speech import AudioChunk, TranscriptDraft

VOCAB = {"vocab": ["▁నాకు", "▁జ్వ", "రం", "▁ఉంది"], "blank": 4, "frame_seconds": 0.04}


def frames(*tokens: int) -> np.ndarray:
    logprobs = np.full((len(tokens), 5), -20.0, dtype=np.float32)
    for frame, token in enumerate(tokens):
        logprobs[frame, token] = -0.1
    return logprobs


def test_greedy_ctc_joins_word_pieces_and_times_words() -> None:
    # నాకు _ _ జ్వ జ్వ రం (pause of 20 frames) ఉంది
    words = _ctc_words(frames(0, 4, 4, 1, 1, 2, *[4] * 20, 3), VOCAB)
    assert [word for word, *_ in words] == ["నాకు", "జ్వరం", "ఉంది"]
    assert words[1][1] == 3 * 0.04 and abs(words[1][2] - 6 * 0.04) < 1e-9
    # The 0.8 s pause starts a new line.
    assert [[word for word, *_ in line] for line in _lines(words)] == [["నాకు", "జ్వరం"], ["ఉంది"]]


class FakeWhisper:
    def __init__(self) -> None:
        self.allowed_languages = None
        self.primary_language = None
        self.calls = []

    def transcribe_chunk(self, chunk, language=None):
        self.calls.append((chunk.live, language))
        return [TranscriptDraft(text="whisper", timestamp="", start_ms=0, end_ms=1, language_code=language)]

    def translate_chunk(self, chunk, language):
        return [TranscriptDraft(text="I have a fever.", timestamp="", start_ms=0, end_ms=1, language_code="en")]


class FakeIndic:
    languages = {"te", "hi"}
    last_diagnostics = {"engine": "indic_conformer"}

    def __init__(self) -> None:
        self.calls = []

    def transcribe_chunk(self, chunk, language=None):
        self.calls.append(language)
        return [TranscriptDraft(text="నాకు జ్వరం ఉంది", timestamp="", start_ms=0, end_ms=1, language_code=language)]


def chunk(live: bool) -> AudioChunk:
    return AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=np.zeros(16_000, dtype=np.float32), live=live)


def test_final_telugu_and_hindi_go_to_indicconformer_everything_else_to_whisper() -> None:
    whisper, indic = FakeWhisper(), FakeIndic()
    router = IndicRoutingProvider(whisper, indic)
    assert router.transcribe_chunk(chunk(False), "te")[0].text == "నాకు జ్వరం ఉంది"
    assert router.last_diagnostics["engine"] == "indic_conformer"
    router.transcribe_chunk(chunk(False), "en")
    router.transcribe_chunk(chunk(True), "te")  # live preview stays on Whisper
    router.transcribe_chunk(chunk(False), None)
    assert indic.calls == ["te"]
    assert whisper.calls == [(False, "en"), (True, "te"), (False, None)]
    # Language settings and translation reach Whisper.
    router.allowed_languages = {"en", "te"}
    router.primary_language = "te"
    assert whisper.allowed_languages == {"en", "te"} and whisper.primary_language == "te"
    assert router.translate_chunk(chunk(False), "te")[0].text == "I have a fever."


def test_models_are_found_per_language(tmp_path) -> None:
    for code in ("te", "hi"):
        (tmp_path / code).mkdir()
        (tmp_path / code / "model.onnx").write_bytes(b"")
        (tmp_path / code / "vocab.json").write_text(json.dumps(VOCAB))
    (tmp_path / "ta").mkdir()  # incomplete: no vocabulary
    (tmp_path / "ta" / "model.onnx").write_bytes(b"")
    provider = IndicConformerProvider(tmp_path)
    assert provider.languages == {"te", "hi"} and not provider.available()
    (tmp_path / "features.npz").write_bytes(b"")
    assert provider.available()


def test_the_factory_adds_indicconformer_only_when_models_are_installed(tmp_path) -> None:
    from app.config import Settings
    from app.providers.factory import build_speech_provider

    assert not isinstance(build_speech_provider(Settings(ai_mode="local", stt_provider="whisper")), IndicRoutingProvider)
    (tmp_path / "te").mkdir()
    (tmp_path / "te" / "model.onnx").write_bytes(b"")
    (tmp_path / "te" / "vocab.json").write_text(json.dumps(VOCAB))
    (tmp_path / "features.npz").write_bytes(b"")
    routed = build_speech_provider(Settings(ai_mode="local", stt_provider="whisper", indic_asr_models_dir=str(tmp_path)))
    assert isinstance(routed, IndicRoutingProvider) and routed.indic.languages == {"te"}
