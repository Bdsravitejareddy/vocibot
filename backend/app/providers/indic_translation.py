"""English translation of Indian-language text with AI4Bharat IndicTrans2.

Whisper translated straight from the audio, and its errors reached the note
("Dolo six-fifty" became "$6.50", 101 °F "around 100"). Once IndicConformer
writes the Telugu or Hindi correctly, translating that text is more
faithful. IndicTrans2 (MIT licence) is run with CTranslate2, the engine
faster-whisper already bundles, from its official int8 export
(``indic-en-dist/ct2_int8_model``, 221 MB).

Pre- and post-processing follow IndicTrans2's ``inference/engine.py``:
numerals and long numbers are protected with placeholders, the text is
normalised and tokenised with indic-nlp-library, transliterated to
Devanagari (the model's shared script), split with the source
SentencePiece model and tagged ``<src> eng_Latn``; the output is
SentencePiece-joined, placeholders restored and Moses-detokenised.
The helpers below are adapted from IndicTrans2 (MIT licence).
"""

from __future__ import annotations

from pathlib import Path
import threading

import regex

# ISO code -> IndicTrans2 (FLORES) code for the languages VociBot offers.
FLORES = {
    "as": "asm_Beng", "bn": "ben_Beng", "gu": "guj_Gujr", "hi": "hin_Deva", "kn": "kan_Knda", "ml": "mal_Mlym",
    "mr": "mar_Deva", "ne": "npi_Deva", "or": "ory_Orya", "pa": "pan_Guru", "sa": "san_Deva", "sd": "snd_Arab",
    "ta": "tam_Taml", "te": "tel_Telu", "ur": "urd_Arab",
}
NOT_TRANSLITERATED = {"Arab", "Aran", "Olck", "Mtei", "Latn"}
MAX_TOKENS = 256

_DIGITS = {chr(base + offset): str(offset) for base in (0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66, 0x0660, 0x06F0) for offset in range(10)}
_EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"
_URL = r"\b(?<![\w/.])(?:(?:https?|ftp)://)?(?:(?:[\w-]+\.)+(?!\.))(?:[\w/\-?#&=%.]+)+(?!\.\w+)\b"
_NUMERAL = r"(~?\d+\.?\d*\s?%?\s?-?\s?~?\d+\.?\d*\s?%|~?\d+%|\d+[-\/.,:']\d+[-\/.,:'+]\d+(?:\.\d+)?|\d+[-\/.:'+]\d+(?:\.\d+)?)"
_OTHER = r"[A-Za-z0-9]*[#|@]\w+"


def _punctuation(text: str) -> str:
    for old, new in (("\r", ""), ("(", " ("), (")", ") "), ("( ", "("), (" )", ")"), (" :", ":"), (" ;", ";"), ("`", "'"), ("„", '"'), ("“", '"'), ("”", '"'), ("–", "-"), ("—", " - "), ("´", "'"), ("‘", "'"), ("‚", "'"), ("’", "'"), ("''", '"'), ("´´", '"'), ("…", "..."), (" « ", ' "'), ("« ", '"'), ("«", '"'), (" » ", '" '), (" »", '"'), ("»", '"'), (" %", "%"), (" ?", "?"), (" !", "!")):
        text = text.replace(old, new)
    text = regex.sub("[ ]{2,}", " ", text)
    text = regex.sub(r"\.{2,}", ".", text)
    text = regex.sub(r"\) ([\.!:?;,])", r")\1", text)
    text = regex.sub(r"(\d) %", r"\1%", text)
    text = regex.sub(r"\"([,\.]+)", r'\1"', text)
    text = regex.sub(r"(\d) (\d)", r"\1.\2", text)
    return text.strip(" ")


def _protect(text: str) -> tuple[str, dict[str, str]]:
    """Numbers like 120/80 and 10.5 pass through translation unchanged."""

    text = "".join(_DIGITS.get(character, character) for character in text.strip("\n"))
    entities: dict[str, str] = {}
    serial = 1
    for pattern in (_EMAIL, _URL, _NUMERAL, _OTHER):
        for match in set(regex.findall(pattern, text)):
            compact = match.replace(".", "") if pattern == _URL else match.replace(" ", "").replace(".", "").replace(":", "") if pattern == _NUMERAL else match
            if pattern in (_URL, _NUMERAL) and len(compact) < 4:
                continue
            placeholder = f"<ID{serial}>"
            entities[placeholder] = entities[f"< ID{serial} >"] = match
            text = text.replace(match, placeholder)
            serial += 1
    return regex.sub(r"\s+", " ", text).replace(">/", ">"), entities


def to_devanagari(text: str, language: str) -> str:
    """indic-nlp's UnicodeIndicTransliterator for Brahmic scripts: the
    Unicode blocks are laid out alike, so a letter moves by a fixed offset.
    (That module imports pandas, which the app does not bundle.)"""

    from indicnlp import langinfo  # type: ignore[import-not-found]

    if language not in langinfo.SCRIPT_RANGES or language == "hi":
        return text
    source, target = langinfo.SCRIPT_RANGES[language][0], langinfo.SCRIPT_RANGES["hi"][0]
    out = []
    for character in text:
        offset = ord(character) - source
        if langinfo.COORDINATED_RANGE_START_INCLUSIVE <= offset <= langinfo.COORDINATED_RANGE_END_INCLUSIVE and character not in "\u0964\u0965":
            character = chr(target + offset)
        out.append(character)
    return "".join(out)


class IndicTranslator:
    """Indian languages -> English, sentence by sentence."""

    def __init__(self, model_dir: str | Path, *, threads: int = 0, beam_size: int = 5) -> None:
        self.model_dir = Path(model_dir)
        self.threads = threads
        self.beam_size = beam_size
        self._lock = threading.Lock()
        self._loaded = None

    def available(self) -> bool:
        return (self.model_dir / "model.bin").is_file() and (self.model_dir / "vocab" / "model.SRC").is_file()

    def supports(self, language: str | None) -> bool:
        return language in FLORES

    def _load(self):
        with self._lock:
            if self._loaded is None:
                import ctranslate2  # type: ignore[import-not-found]
                import sentencepiece  # type: ignore[import-not-found]
                from indicnlp.normalize.indic_normalize import IndicNormalizerFactory  # type: ignore[import-not-found]
                from indicnlp.tokenize import indic_tokenize  # type: ignore[import-not-found]
                from sacremoses import MosesDetokenizer  # type: ignore[import-not-found]

                translator = ctranslate2.Translator(str(self.model_dir), device="cpu", compute_type="int8", intra_threads=self.threads)
                pieces = sentencepiece.SentencePieceProcessor(model_file=str(self.model_dir / "vocab" / "model.SRC"))
                self._loaded = (translator, pieces, IndicNormalizerFactory(), indic_tokenize, MosesDetokenizer(lang="en"))
            return self._loaded

    def translate(self, sentences: list[str], language: str) -> list[str]:
        """English for each sentence (empty input gives empty output)."""

        if not sentences:
            return []
        translator, pieces, normalizers, tokenize, detokenizer = self._load()
        source = FLORES[language]
        normalizer = normalizers.get_normalizer(language)
        batch, entities = [], []
        for sentence in sentences:
            text, protected = _protect(_punctuation(sentence))
            text = " ".join(tokenize.trivial_tokenize(normalizer.normalize(text.strip()), language))
            if source.split("_")[1] not in NOT_TRANSLITERATED:
                text = to_devanagari(text, language).replace(" ् ", "्")
            tokens = pieces.encode(text, out_type=str)[:MAX_TOKENS]
            batch.append([source, "eng_Latn", *tokens])
            entities.append(protected)
        results = translator.translate_batch(batch, max_batch_size=4096, batch_type="tokens", max_input_length=MAX_TOKENS + 2, max_decoding_length=256, beam_size=self.beam_size)
        english = []
        for result, protected in zip(results, entities):
            text = "".join(result.hypotheses[0]).replace("▁", " ").strip()
            for placeholder, value in protected.items():
                text = text.replace(placeholder, value)
            english.append(detokenizer.detokenize(text.split(" ")))
        return english
