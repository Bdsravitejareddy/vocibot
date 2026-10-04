from datetime import datetime
import json

import httpx
import pytest

from app.config import settings
from app.learning import cycle, gate, gemini, scheduler, tips
from app.learning.deidentify import snippet
from app.learning.medicines import MedicineDictionary, correct_medicine_text, resolve_bare_strength

ENTRIES = [
    {"brand": "Dolo 650", "generic": "Paracetamol", "strengths": ["650 mg"], "spoken": ["dolo"]},
    {"brand": "Calpol", "generic": "Paracetamol", "strengths": ["500 mg", "650 mg"], "spoken": []},
    {"brand": "Montair LC", "generic": "Montelukast + Levocetirizine", "strengths": ["10 mg/5 mg"], "spoken": []},
    {"brand": "Glycomet", "generic": "Metformin", "strengths": ["500 mg"], "spoken": []},
    {"brand": "Azithral", "generic": "Azithromycin", "strengths": ["500 mg"], "spoken": []},
]


@pytest.fixture
def dictionary() -> MedicineDictionary:
    return MedicineDictionary([dict(entry) for entry in ENTRIES])


def test_misheard_brands_are_matched_by_sound_but_english_words_are_not(dictionary) -> None:
    assert dictionary.match("Kalpal")["brand"] == "Calpol"
    assert dictionary.match("Monter")["brand"] == "Montair LC"
    assert dictionary.match("Glycomat")["brand"] == "Glycomet"
    assert dictionary.match("coral") is None and dictionary.match("water") is None
    text, changes = correct_medicine_text("Take Azithril and Kalpal after food", dictionary)
    assert text == "Take Azithral and Calpol after food" and len(changes) == 2


def test_a_bare_strength_becomes_the_medicine_named_nearby_or_the_only_generic(dictionary) -> None:
    assert resolve_bare_strength("$650", dictionary, "I am taking dolo since yesterday") == "Dolo 650"
    only_metformin = MedicineDictionary([ENTRIES[3]])
    assert resolve_bare_strength("500", only_metformin, "") == "metformin 500 mg"
    assert resolve_bare_strength("500", dictionary, "") is None  # several generics sold as 500 mg
    assert resolve_bare_strength("$6.50", dictionary, "taking dolo") == "Dolo 650"  # "six fifty" written as money
    assert resolve_bare_strength("6.50", dictionary, "taking dolo") is None
    assert resolve_bare_strength("fever", dictionary, "") is None


def test_snippets_remove_names_numbers_phones_and_dates(dictionary) -> None:
    lines = ["Ramesh Kumawat, 45 years old, phone 98480 22334.", "Any medicines you are taking? $650 since 12/09. Continue Dolo at Sunshine Hospital."]
    text = snippet(lines, "$650", dictionary, words_each_side=20)
    assert "$650" in text and "Dolo" in text
    for leaked in ("Ramesh", "Kumawat", "45", "98480", "12/09", "Sunshine"):
        assert leaked not in text


def _learning(tmp_path, monkeypatch, active=None):
    MedicineDictionary([dict(entry) for entry in ENTRIES]).save(tmp_path / "medicines.json")
    if active is not None:
        (tmp_path / "active.json").write_text(json.dumps(active))
    monkeypatch.setattr(settings, "learning_dir", str(tmp_path))
    tips._cache.clear()


def test_corrections_only_apply_once_switched_on(tmp_path, monkeypatch) -> None:
    _learning(tmp_path, monkeypatch)
    record = {"medications": ["$650"], "plan": "Continue Kalpal"}
    assert tips.correct_record(record, "dolo") == [] and record["medications"] == ["$650"]
    _learning(tmp_path, monkeypatch, {"medicine_corrections": True})
    assert tips.correct_record(record, "taking dolo") == ["medications", "plan"]
    assert record == {"medications": ["Dolo 650"], "plan": "Continue Calpol"}
    assert tips.listening_hint() is None


class FakeResponses:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers["x-goog-api-key"]))
        status, body = self.script.pop(0)
        return httpx.Response(status, json=body, request=httpx.Request(method, url))


def test_gemini_skips_rejected_keys_falls_back_when_quota_is_spent_and_never_logs_keys(tmp_path, monkeypatch) -> None:
    answer = {"candidates": [{"content": {"parts": [{"text": "{\"ok\": true}"}]}}]}
    fake = FakeResponses([(401, {}), (429, {}), (429, {}), (429, {}), (429, {}), (200, answer)])
    monkeypatch.setattr(gemini.httpx, "request", fake)
    monkeypatch.setattr(gemini.time, "sleep", lambda seconds: None)
    client = gemini.GeminiClient(tmp_path / "audit.jsonl", keys=["SECRET-ONE", "SECRET-TWO"])
    client.model = "gemini-flash-latest"
    assert client.generate("list medicines", purpose="test", level="knowledge") == "{\"ok\": true}"
    assert client.model == gemini.FALLBACK_MODEL
    assert "SECRET-ONE" in client._rejected
    assert all(key == "SECRET-TWO" for _, key in fake.calls[1:])
    log = (tmp_path / "audit.jsonl").read_text()
    assert "SECRET" not in log and "list medicines" in log and log.count("\n") == 2


def test_the_cycle_runs_only_at_night_after_eleven() -> None:
    last = datetime(2026, 10, 3, 23, 30)
    assert not scheduler.due(last, datetime(2026, 10, 4, 22, 59))
    assert scheduler.due(last, datetime(2026, 10, 4, 23, 1))
    assert scheduler.due(last, datetime(2026, 10, 5, 2, 0))  # Mac woke up after midnight
    assert not scheduler.due(last, datetime(2026, 10, 5, 9, 0))  # never during clinic hours
    assert not scheduler.due(datetime(2026, 10, 4, 23, 5), datetime(2026, 10, 5, 1, 0))


def test_busy_while_a_consultation_records() -> None:
    with scheduler.consultation_in_progress():
        assert scheduler.clinic_is_busy()


NUMBERS = {"medicines_in_note": 4, "medicines_total": 13, "wrong_medicines": 6, "note_facts": 60, "note_facts_total": 70, "note_false_facts": 0, "unresolved_recent": 3}


def test_only_a_meaningful_improvement_with_nothing_worse_is_accepted() -> None:
    assert gate.meaningful_improvement(NUMBERS, {**NUMBERS, "medicines_in_note": 8, "wrong_medicines": 2})[0]
    assert not gate.meaningful_improvement(NUMBERS, NUMBERS)[0]
    assert not gate.meaningful_improvement(NUMBERS, {**NUMBERS, "medicines_in_note": 9, "note_facts": 59})[0]
    assert not gate.meaningful_improvement(NUMBERS, {**NUMBERS, "medicines_in_note": 9, "note_false_facts": 1})[0]
    assert gate.meaningful_improvement(NUMBERS, {**NUMBERS, "unresolved_recent": 1})[0]


def _cycle(tmp_path, monkeypatch, after):
    monkeypatch.setattr(settings, "learning_dir", str(tmp_path))
    monkeypatch.setattr(cycle, "_setting", lambda key, default: {"cloud_learning": "off"}.get(key, default))
    monkeypatch.setattr(cycle, "language_mix", lambda: {"consultations": 0})
    monkeypatch.setattr(cycle, "unresolved_values", lambda dictionary, days=7: [])
    monkeypatch.setattr(cycle, "_pipeline", lambda: None)
    monkeypatch.setattr(gate, "evaluate", lambda folder, pipeline: dict(after if (folder / "active.json").exists() else NUMBERS))
    return cycle.run_cycle("test")


def test_the_cycle_switches_on_tips_only_when_the_gate_passes(tmp_path, monkeypatch) -> None:
    report = _cycle(tmp_path, monkeypatch, {**NUMBERS, "medicines_in_note": 8, "wrong_medicines": 2})
    assert report["decision"] == "accepted", report
    assert json.loads((tmp_path / "active.json").read_text()) == {"medicine_corrections": True}
    assert len(MedicineDictionary.load(tmp_path / "medicines.json").entries) > 300
    assert not (tmp_path / "candidate").exists() and len(list((tmp_path / "reports").glob("*.json"))) == 1
    assert _cycle(tmp_path, monkeypatch, NUMBERS)["steps"][-1] == {"step": "gate", "skipped": "nothing new to test"}


def test_the_cycle_keeps_the_old_tips_when_nothing_improves(tmp_path, monkeypatch) -> None:
    report = _cycle(tmp_path, monkeypatch, {**NUMBERS, "medicines_in_note": 9, "note_facts": 55})
    assert report["decision"] == "rejected" and "note facts 60->55" in report["summary"]
    assert not (tmp_path / "active.json").exists()


def test_learning_api_refuses_to_run_during_a_consultation_and_validates_the_level(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    stored = {}
    monkeypatch.setattr(cycle, "_setting", lambda key, default: stored.get(key, default))
    monkeypatch.setattr(cycle, "_store", lambda key, value: stored.__setitem__(key, value))
    monkeypatch.setattr("app.api.learning.keychain_keys", lambda: ["k1", "k2"])
    client = TestClient(app)
    assert client.put("/api/learning", json={"cloud_level": "everything"}).status_code == 422
    status = client.put("/api/learning", json={"cloud_level": "snippets"}).json()
    assert status["cloud_level"] == "snippets" and status["gemini_keys"] == 2 and "k1" not in json.dumps(status)
    with scheduler.consultation_in_progress():
        assert client.post("/api/learning/run").status_code == 409
