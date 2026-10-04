"""A dictionary of medicines prescribed in Indian clinics, and the corrections
it allows without a doctor: misheard brand names ("Azithril" -> Azithral)
and values that cannot be a medicine ("$650").

The dictionary is general knowledge (built by the nightly cycle, optionally
with Gemini at the "knowledge only" level - no patient data); corrections are
tested before the cycle switches them on, and every corrected field is
flagged for the doctor's review.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import unicodedata

CATEGORIES = (
    "fever and pain relief (analgesics, antipyretics, NSAIDs)",
    "antibiotics and antifungals",
    "stomach and digestion (antacids, PPIs, antiemetics, antidiarrhoeals, laxatives)",
    "cough, cold and allergy (antihistamines, cough syrups, montelukast combinations, nasal sprays)",
    "diabetes",
    "blood pressure, heart and cholesterol",
    "thyroid and hormones",
    "children's syrups and drops",
    "vitamins, minerals and supplements",
    "asthma inhalers and nebulisation",
)


def knowledge_prompt(category: str, count: int = 40) -> str:
    return (
        f"List the {count} medicine brands most commonly prescribed in Indian general practice for: {category}. "
        "For each, give the brand as written on the strip, the generic name(s), the usual strengths, and how patients and doctors "
        "commonly SAY or MISSPELL it, including how speech recognition might write it in English letters, Devanagari, Telugu and Tamil script. "
        'Return JSON: {"medicines": [{"brand": "...", "generic": "...", "strengths": ["..."], "spoken": ["..."]}]}. '
        "Only real, currently marketed brands; if unsure about a brand, leave it out."
    )


def _latin(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text.lower()))


def _sound(text: str) -> str:
    """How a brand name sounds, roughly: "Kalpal" and "Calpol" -> "klpl",
    "Monter" and "Montair" -> "mntr", "Glycomat" and "Glycomet" -> "glkmt"."""

    word = re.sub(r"[^a-z]", "", _latin(text))
    if not word:
        return ""
    word = re.sub(r"c(?=[eiy])", "s", word)  # soft c: Crocin ~ Crosin
    for old, new in (("ph", "f"), ("ck", "k"), ("q", "k"), ("x", "ks"), ("z", "s"), ("w", "v"), ("c", "k"), ("y", "i")):
        word = word.replace(old, new)
    word = re.sub(r"(?<=[bdgkpstv])h", "", word)  # th/dh/kh -> t/d/k
    word = re.sub(r"(.)\1+", r"\1", word)
    return word[0] + re.sub(r"[aeiou]", "", word[1:])


def _english_words() -> set[str]:
    """Ordinary English words; the list's capitalised entries are proper
    names ("Ramesh") and are left out."""

    try:
        return {word for word in (line.strip() for line in open("/usr/share/dict/words", encoding="utf-8")) if word.islower()}
    except OSError:
        return set()


_ENGLISH: set[str] | None = None


class MedicineDictionary:
    def __init__(self, entries: list[dict]) -> None:
        self.entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("brand")]
        self._names: dict[str, dict] = {}
        self._sounds: dict[str, list[tuple[str, dict]]] = {}
        for entry in self.entries:
            for name in [entry["brand"], *(entry.get("spoken") or [])]:
                key = _latin(name) if name.isascii() else name.strip().lower()
                if len(key) >= 3:
                    self._names.setdefault(key, entry)
                for word in name.split()[:1] if name.isascii() else []:
                    sound = _sound(word)
                    if len(sound) >= 3:
                        self._sounds.setdefault(sound, []).append((_latin(word), entry))

    @classmethod
    def load(cls, path: Path) -> "MedicineDictionary":
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")).get("medicines", []))
        except (OSError, ValueError):
            return cls([])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"medicines": self.entries}, ensure_ascii=False, indent=1), encoding="utf-8")

    def merge(self, entries: list[dict]) -> int:
        known = {entry["brand"].lower() for entry in self.entries}
        added = [entry for entry in entries if isinstance(entry, dict) and entry.get("brand") and entry["brand"].lower() not in known]
        self.__init__(self.entries + added)
        return len(added)

    def brand_words(self) -> set[str]:
        """Lower-case brand names (first word), e.g. {"dolo", "crocin"}."""

        return {entry["brand"].split()[0].lower() for entry in self.entries if len(entry["brand"].split()[0]) >= 3}

    def match(self, word: str, threshold: float = 0.84) -> dict | None:
        """The medicine a (mis)heard word most likely names, or None.

        Exact names and spoken forms first; then words that sound the same
        ("Kalpal" -> Calpol). Ordinary English words are never matched.
        """

        global _ENGLISH
        key = _latin(word) if word.isascii() else word.strip().lower()
        if len(key) < 4:
            return None
        if key in self._names:
            return self._names[key]
        if not word.isascii():
            return None
        if _ENGLISH is None:
            _ENGLISH = _english_words()
        if key in _ENGLISH:
            return None
        candidates = self._sounds.get(_sound(word), [])
        scored = sorted(((SequenceMatcher(None, key, name).ratio(), entry) for name, entry in candidates), key=lambda item: -item[0])
        if scored and scored[0][0] >= 0.6:
            return scored[0][1]
        best, score = None, 0.0
        for name, entry in self._names.items():
            if not name.isascii() or abs(len(name) - len(key)) > 3:
                continue
            ratio = SequenceMatcher(None, key, name).ratio()
            if ratio > score:
                best, score = entry, ratio
        return best if score >= threshold else None


# "$650", "650", "Rs 650", "$6.50": a strength without a medicine (speech
# recognition writes "six fifty" as money).
BARE_STRENGTH = re.compile(r"^\s*(?:(?:[$₹]|rs\.?\s*)\s*(\d{1,2})\.(\d{2})|(?:[$₹]|rs\.?\s*)?\s*(\d{2,4}))(?:\s*mg)?\s*$", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z][A-Za-z.\-]{2,}")


def correct_medicine_text(text: str, dictionary: MedicineDictionary) -> tuple[str, list[str]]:
    """Misheard brand names in ``text`` replaced by the dictionary's spelling;
    returns the new text and what was changed."""

    changes: list[str] = []

    def replace(match: re.Match) -> str:
        word = match.group(0)
        entry = dictionary.match(word.rstrip("."))
        if entry is None:
            return word
        brand_first = entry["brand"].split()[0]
        if word.lower().rstrip(".") == brand_first.lower():
            return word
        changes.append(f"{word} -> {brand_first}")
        return brand_first

    return WORD.sub(replace, text), changes


def resolve_bare_strength(value: str, dictionary: MedicineDictionary, context: str) -> str | None:
    """"$650" -> the medicine named nearby, or the one generic sold in that
    strength (650 -> paracetamol 650 mg); None if it cannot be told."""

    found = BARE_STRENGTH.match(value)
    if not found:
        return None
    strength = found.group(3) or found.group(1) + found.group(2)
    for word in WORD.findall(context):
        entry = dictionary.match(word)
        if entry and any(strength in str(item) for item in entry.get("strengths") or []):
            return f"{entry['brand'].split()[0]} {strength}"
    # The same generic is written several ways ("Paracetamol", "Paracetamol
    # (Acetaminophen)"): compare the first word of single-ingredient generics.
    generics = {re.split(r"[\s(]", str(entry.get("generic", "")).strip().lower())[0] for entry in dictionary.entries
                if "+" not in str(entry.get("generic", "")) and any(re.fullmatch(rf"{strength}\s*(?:mg)?", str(item).strip().lower()) for item in entry.get("strengths") or [])}
    generics.discard("")
    if len(generics) == 1:
        return f"{generics.pop()} {strength} mg"
    return None
