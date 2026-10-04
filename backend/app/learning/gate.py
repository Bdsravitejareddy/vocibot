"""The test every learned change must pass before it is switched on.

Fixed test set, shipped with the app (no patient data): consultations with
two synthetic Indian voices naming common Indian medicines, run through the
real pipeline, plus the English note benchmark. A candidate is accepted only
if medicines in the note improve (or wrong medicines fall) and nothing else
gets worse.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path

from ..config import settings

TESTSET = Path(__file__).parent / "testset"


@contextmanager
def using(learning_folder: Path):
    """Run the pipeline with the tips in ``learning_folder``."""

    from . import tips

    previous = settings.learning_dir
    settings.learning_dir = str(learning_folder)
    tips._cache.clear()
    try:
        yield
    finally:
        settings.learning_dir = previous
        tips._cache.clear()


def _medicine_cases(pipeline) -> dict:
    import soundfile as sf
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ..db import Base
    from ..providers.reconciliation import FinalReconciler
    from ..schemas import ConsultationCreate
    from ..services import consultations as service

    found = total = wrong = 0
    details = []
    for case in json.loads((TESTSET / "cases.json").read_text(encoding="utf-8")):
        audio, _ = sf.read(TESTSET / f"{case['id']}.wav", dtype="float32")
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        result = FinalReconciler().run(audio, pipeline.stt, sample_rate=16_000)
        consultation = service.create_consultation(session, ConsultationCreate(patient_id=case["id"][:60], age=40, sex="Female"))
        service.replace_with_reconciled_transcript(session, consultation.id, result.transcripts, extract=False, translations=result.translations)
        record = service.extract_reconciled_clinical_record(session, consultation.id)["record"]
        meds = " | ".join(record.get("medications") or []).lower() + " | " + (record.get("plan") or "").lower()
        hits = sum(any(alias in meds for alias in aliases) for aliases in case["medications"])
        bad = [item for item in record.get("medications") or [] if not any(alias in item.lower() for aliases in case["medications"] for alias in aliases)]
        found, total, wrong = found + hits, total + len(case["medications"]), wrong + len(bad)
        details.append({"case": case["id"], "medicines": f"{hits}/{len(case['medications'])}", "wrong": bad})
        session.close()
    return {"medicines_in_note": found, "medicines_total": total, "wrong_medicines": wrong, "cases": details}


def _note_benchmark() -> dict:
    from ..domain.types import ClinicalRecord, TranscriptSegmentInput
    from ..providers.ollama_extraction import OllamaClinicalExtractionProvider
    from ..services.consultations import _apply_validated_candidates
    from .tips import correct_record

    provider = OllamaClinicalExtractionProvider()
    hits = total = false = 0
    for case in json.loads((TESTSET / "note_cases.json").read_text(encoding="utf-8")):
        lines = [TranscriptSegmentInput(id=f"{case['id']}-{index}", speaker="UNKNOWN", text=text, timestamp="00:00:00", sequence_number=index) for index, text in enumerate(case["lines"])]
        record, _, _ = _apply_validated_candidates(provider.extract(lines, ClinicalRecord()), ClinicalRecord(), lines)
        data = record.model_dump()
        correct_record(data, " ".join(case["lines"]))
        text = {field: (" | ".join(map(str, value)) if isinstance(value, list) else " | ".join(f"{k} {v}" for k, v in value.items()) if isinstance(value, dict) else str(value or "")).lower() for field, value in data.items()}
        for field, facts in case["expected"].items():
            for alternatives in facts:
                hits += any(term in text.get(field, "") for term in alternatives)
                total += 1
        for field, terms in case.get("must_not", {}).items():
            false += sum(term in text.get(field, "") for term in terms)
    return {"note_facts": hits, "note_facts_total": total, "note_false_facts": false}


def evaluate(learning_folder: Path, pipeline) -> dict:
    with using(learning_folder):
        return {**_medicine_cases(pipeline), **_note_benchmark()}


def meaningful_improvement(before: dict, after: dict) -> tuple[bool, str]:
    unresolved = before.get("unresolved_recent", 0), after.get("unresolved_recent", 0)
    better = (after["medicines_in_note"] > before["medicines_in_note"] or after["wrong_medicines"] < before["wrong_medicines"]
              or unresolved[1] < unresolved[0])
    worse = (unresolved[1] > unresolved[0] or after["note_facts"] < before["note_facts"] or after["note_false_facts"] > before["note_false_facts"]
             or after["medicines_in_note"] < before["medicines_in_note"] or after["wrong_medicines"] > before["wrong_medicines"])
    summary = (f"medicines in note {before['medicines_in_note']}->{after['medicines_in_note']}/{after['medicines_total']}, "
               f"wrong medicines {before['wrong_medicines']}->{after['wrong_medicines']}, "
               f"note facts {before['note_facts']}->{after['note_facts']}/{after['note_facts_total']}, "
               f"false facts {before['note_false_facts']}->{after['note_false_facts']}, "
               f"unresolved medicine values in recent notes {unresolved[0]}->{unresolved[1]}")
    return better and not worse, summary
