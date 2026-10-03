from app.providers.indic_translation import FLORES, _protect, _punctuation


def test_numbers_pass_through_translation_unchanged() -> None:
    text, entities = _protect("బీపీ 120/80 టెంపరేచర్ ౧౦౧ డిగ్రీలు")
    assert "<ID1>" in text and entities["<ID1>"] == "120/80"
    assert "101" in text  # Telugu digits normalised; short numbers stay as they are


def test_punctuation_is_normalised_like_indictrans2() -> None:
    assert _punctuation("“జ్వరం” …  ఉంది ?") == '"జ్వరం" . ఉంది?'


def test_language_codes() -> None:
    assert FLORES["te"] == "tel_Telu" and FLORES["hi"] == "hin_Deva" and "en" not in FLORES


def test_transliteration_to_devanagari_matches_indic_nlp() -> None:
    from indicnlp.transliterate.unicode_transliterate import UnicodeIndicTransliterator

    from app.providers.indic_translation import to_devanagari

    for text, language in (("నాకు బాగా జ్వరంగా ఉంది, డోలో 650.", "te"), ("ಜ್ವರ ಇದೆ", "kn"), ("તાવ છે", "gu"), ("बुखार है", "hi")):
        assert to_devanagari(text, language) == UnicodeIndicTransliterator.transliterate(text, language, "hi")
