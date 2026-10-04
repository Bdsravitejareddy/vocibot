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


class FakeTranslator:
    def __init__(self) -> None:
        self.batches = []

    def supports(self, language):
        return language in {"te", "hi"}

    def translate(self, sentences, language):
        self.batches.append((sentences, language))
        return [f"EN({sentence})" for sentence in sentences]


def test_text_translation_groups_whole_lines_and_keeps_their_timing() -> None:
    translator = FakeTranslator()
    router = IndicRoutingProvider(FakeWhisper(), FakeIndic(), translator, {"te"})
    assert router.translates_text("te") and not router.translates_text("hi") and not router.translates_text("en")
    lines = [TranscriptDraft(text=" ".join(["పదం"] * words), timestamp=f"00:00:0{index}", start_ms=index * 1000, end_ms=index * 1000 + 900, language_code="te") for index, words in enumerate((8, 8, 8, 25))]
    english = router.translate_text(lines, "te")
    # 8 + 8 words fit in one group of 20; the next 8 start a new one; 25 alone.
    assert [len(sentence.split()) for sentence in translator.batches[0][0]] == [16, 8, 25]
    assert [(draft.start_ms, draft.end_ms, draft.language_code) for draft in english] == [(0, 1900, "en"), (2000, 2900, "en"), (3000, 3900, "en")]


def test_the_final_pass_translates_text_where_enabled_and_audio_elsewhere() -> None:
    from app.providers.reconciliation import FinalReconciler

    class Detecting(FakeWhisper):
        language = "te"
        audio_translations = 0

        def detect_piece_language(self, audio):
            return self.language, 0.95

        def translate_chunk(self, chunk, language):
            self.audio_translations += 1
            return super().translate_chunk(chunk, language)

    whisper, translator = Detecting(), FakeTranslator()
    router = IndicRoutingProvider(whisper, FakeIndic(), translator, {"te"})
    audio = np.full(16_000 * 8, 0.1, dtype=np.float32)
    result = FinalReconciler().run(audio, router, sample_rate=16_000)
    assert [draft.text for draft in result.translations] == ["EN(నాకు జ్వరం ఉంది)"] and whisper.audio_translations == 0
    whisper.language = "hi"  # Hindi not enabled for text translation: Whisper from the audio
    result = FinalReconciler().run(audio, router, sample_rate=16_000)
    assert [draft.text for draft in result.translations] == ["I have a fever."] and whisper.audio_translations == 1


def test_english_lines_in_an_indian_language_piece_get_whispers_english() -> None:
    class Whisper(FakeWhisper):
        def english_share(self, audio, native):
            return 0.95 if float(np.abs(audio).mean()) > 0.3 else 0.05

        def transcribe_chunk(self, chunk, language=None):
            self.calls.append((chunk.live, language))
            return [TranscriptDraft(text="How long have you had this?", timestamp="", start_ms=chunk.timestamp_ms, end_ms=chunk.timestamp_ms + 1000, language_code="en")]

    class Indic(FakeIndic):
        def transcribe_chunk(self, chunk, language=None):
            return [TranscriptDraft(text="हाव लॉन्ग हेव", timestamp="00:00:00", start_ms=0, end_ms=2000, language_code="hi"),
                    TranscriptDraft(text="तीन महीने", timestamp="00:00:02", start_ms=2000, end_ms=4000, language_code="hi"),
                    TranscriptDraft(text="हाँ", timestamp="00:00:04", start_ms=4000, end_ms=4500, language_code="hi")]

    whisper = Whisper()
    whisper.allowed_languages = {"en", "hi"}
    router = IndicRoutingProvider(whisper, Indic(), FakeTranslator(), {"hi"})
    audio = np.concatenate([np.full(32_000, 0.5), np.full(32_000, 0.05), np.full(8_000, 0.5)]).astype(np.float32)
    lines = router.transcribe_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=audio, live=False), "hi")
    # English line replaced; Hindi line kept; the 0.5 s line is too short to judge.
    assert [(line.text, line.language_code) for line in lines] == [("How long have you had this?", "en"), ("तीन महीने", "hi"), ("हाँ", "hi")]
    # Only the Hindi lines are translated; the English one is kept as it is.
    english = router.translate_text(lines, "hi")
    assert [line.text for line in english] == ["How long have you had this?", "EN(तीन महीने हाँ)"]
    two_english = router.translate_text([lines[0], lines[0]], "hi")
    assert len(two_english) == 2  # English lines are not merged (each keeps its speaker)
