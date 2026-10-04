"""The learned tips the pipeline uses, and where they are kept.

<learning dir>/
  medicines.json   medicine dictionary (general knowledge)
  active.json      which tips the nightly cycle switched on after testing
  reports/         one report per nightly run (what was tried, the before/after numbers)
  gemini-audit.jsonl  every request sent to Gemini

A tip only takes effect once the nightly cycle tested it and found a
meaningful improvement with nothing made worse (learning/cycle.py).
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from ..config import settings
from .medicines import BARE_STRENGTH, MedicineDictionary, correct_medicine_text, resolve_bare_strength

_cache: dict[str, tuple[float, object]] = {}


def learning_dir() -> Path:
    return Path(settings.learning_dir).expanduser() if settings.learning_dir else Path(settings.recordings_dir).expanduser().parent / "learning"


def _cached(path: Path, load):
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return load(None)
    hit = _cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    value = load(path)
    _cache[str(path)] = (stamp, value)
    return value


def active() -> dict:
    return _cached(learning_dir() / "active.json", lambda path: json.loads(path.read_text(encoding="utf-8")) if path else {})


def medicines() -> MedicineDictionary:
    return _cached(learning_dir() / "medicines.json", lambda path: MedicineDictionary.load(path) if path else MedicineDictionary([]))


def medicine_corrections_on() -> bool:
    return bool(active().get("medicine_corrections"))


def listening_hint() -> str | None:
    """Words for Whisper to listen for in the final transcript, if switched on."""

    words = active().get("listening_hints") or []
    return ("Medicines: " + ", ".join(words) + ".") if words else None


def is_medicine_word(text: str) -> bool:
    brands = medicines().brand_words()
    return any(word in brands for word in re.findall(r"[a-z]+", text.lower()))


def correct_record(record: dict, context: str) -> list[str]:
    """Correct medicine names in the medications and plan fields in place;
    returns the fields changed (to be flagged for review)."""

    dictionary = medicines()
    if not medicine_corrections_on() or not dictionary.entries:
        return []
    changed: list[str] = []
    items = []
    for item in record.get("medications") or []:
        fixed = resolve_bare_strength(item, dictionary, context) if BARE_STRENGTH.match(item) else None
        if fixed is None:
            fixed, edits = correct_medicine_text(item, dictionary)
            fixed = fixed if edits else None
        if fixed and fixed != item:
            changed.append("medications")
        items.append(fixed or item)
    if record.get("medications"):
        record["medications"] = items
    if record.get("plan"):
        fixed, edits = correct_medicine_text(record["plan"], dictionary)
        if edits:
            record["plan"] = fixed
            changed.append("plan")
    return sorted(set(changed))
