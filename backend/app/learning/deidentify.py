"""De-identified snippets for the "snippets" cloud-learning level.

Only a short piece of the English transcript around one suspicious value is
ever sent, and before that: digits other than the value become "#", words
that look like names (capitalised, not an English word, not a known
medicine) become "[name]", and phone numbers, dates and ages are removed.
"""

from __future__ import annotations

import re

from .medicines import MedicineDictionary, _english_words

_PHONE = re.compile(r"\+?\d[\d\s\-]{7,}\d")
_DATE = re.compile(r"\b\d{1,2}[/.\-]\d{1,2}(?:[/.\-]\d{2,4})?\b")
_AGE = re.compile(r"\b\d{1,3}\s*(?:years?|yrs?|year-old|months?)\s*(?:old)?\b", re.IGNORECASE)
_ENGLISH: set[str] | None = None


def deidentify(text: str, keep: str, dictionary: MedicineDictionary) -> str:
    """``text`` with identifying details removed; ``keep`` (the value being
    asked about) is left as it is."""

    global _ENGLISH
    if _ENGLISH is None:
        _ENGLISH = _english_words()
    placeholder = "\x00"
    text = text.replace(keep, placeholder) if keep else text
    text = _PHONE.sub("[phone]", text)
    text = _DATE.sub("[date]", text)
    text = _AGE.sub("[age]", text)
    text = re.sub(r"\d", "#", text)

    def name(match: re.Match) -> str:
        # Capitalised mid-sentence ("at Sunshine Hospital") is a name unless
        # it is a known medicine; at a sentence start, only if not English.
        word = match.group(0)
        starts_sentence = not text[:match.start()].strip() or text[:match.start()].rstrip()[-1] in ".?!:"
        if dictionary.match(word) or (starts_sentence and word.lower() in _ENGLISH):
            return word
        return "[name]"

    text = re.sub(r"(?<![\w\[])[A-Z][a-z]{2,}\b", name, text)
    return text.replace(placeholder, keep)


def snippet(lines: list[str], value: str, dictionary: MedicineDictionary, words_each_side: int = 8) -> str | None:
    """A few English words either side of ``value``, de-identified."""

    text = " ".join(lines)
    at = text.lower().find(value.lower())
    if at < 0:
        return None
    before = text[:at].split()[-words_each_side:]
    after = text[at + len(value):].split()[:words_each_side]
    return deidentify(" ".join([*before, value, *after]), value, dictionary)
