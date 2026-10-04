"""Before/after test set for the nightly learning cycle.

Synthetic consultations (macOS Indian voices, two speakers, real Indian
medicine brands) plus the clinic's Hindi/English recording that mentions
Dolo 650. Each runs through the app's own services (final pass, translation,
doctor/patient labels, note, evidence checks) on a throw-away database.

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/learning_eval.py --label before --out tmp/analytics/learn-before.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).parent
TESTSET = HERE.parent / "app" / "learning" / "testset"
CASES = json.loads((TESTSET / "cases.json").read_text(encoding="utf-8"))
REAL = [{"id": "real_hindi_dolo (VB-20261004-6JDV2P)", "language": "hi", "audio": str(Path.home() / "Library/Application Support/vocibot/recordings/VB-20261004-6JDV2P.flac"),
         "medications": [["dolo", "paracetamol"]], "symptoms": ["sleep"]}]
GENERIC = re.compile(r"^(?:some |a |the |any )*(?:medicines?|meds?|tablets?|pills?|drugs?)$")


def run_case(case: dict, audio) -> dict:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api.audio import build_local_pipeline, restrict_languages
    from app.db import Base
    from app.providers.reconciliation import FinalReconciler
    from app.schemas import ConsultationCreate
    from app.services import consultations as service

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    pipeline = run_case.pipeline
    started = time.perf_counter()
    result = FinalReconciler().run(audio, pipeline.stt, sample_rate=16_000)
    consultation = service.create_consultation(session, ConsultationCreate(patient_id=case["id"][:60], age=40, sex="Female"))
    service.replace_with_reconciled_transcript(session, consultation.id, result.transcripts, extract=False, translations=result.translations)
    loaded = service.extract_reconciled_clinical_record(session, consultation.id)
    seconds = time.perf_counter() - started
    record = loaded["record"]
    meds_text = " | ".join(record.get("medications") or []).lower()
    plan_text = (record.get("plan") or "").lower()
    transcript = " ".join(line["text"] for line in loaded["transcript"]).lower() + " " + " ".join(line["text"] for line in loaded.get("translation") or []).lower()
    found = [any(alias in meds_text or alias in plan_text for alias in aliases) for aliases in case["medications"]]
    heard = [any(alias in transcript for alias in aliases) for aliases in case["medications"]]
    wrong = [item for item in (record.get("medications") or []) if not any(alias in item.lower() for aliases in case["medications"] for alias in aliases)]
    symptoms_text = (" ".join(record.get("presenting_symptoms") or []) + " " + (record.get("chief_complaint") or "") + " " + (record.get("history_present_illness") or "")).lower()
    symptoms = [term in symptoms_text for term in case["symptoms"]]
    return {"id": case["id"], "seconds": round(seconds, 1), "medicines_in_note": f"{sum(found)}/{len(found)}", "medicines_heard": f"{sum(heard)}/{len(heard)}",
            "wrong_medications": wrong, "symptoms": f"{sum(symptoms)}/{len(symptoms)}", "medications": record.get("medications"), "plan": record.get("plan"),
            "_found": sum(found), "_total": len(found), "_heard": sum(heard), "_wrong": len(wrong), "_sym": sum(symptoms), "_sym_total": len(symptoms)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(HERE))
    from transcription_accuracy import load_audio
    from app.api.audio import build_local_pipeline, restrict_languages

    run_case.pipeline = build_local_pipeline()
    restrict_languages(run_case.pipeline.stt, {"en", "te", "hi", "ta", "mr", "gu"})
    rows = []
    for case in CASES + REAL:
        audio = load_audio(Path(case.get("audio") or TESTSET / f"{case['id']}.wav"))
        row = run_case(case, audio)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.startswith("_")}, ensure_ascii=False), flush=True)
    total = {key: sum(row[key] for row in rows) for key in ("_found", "_total", "_heard", "_wrong", "_sym", "_sym_total")}
    summary = {"label": args.label, "medicines_in_note": f"{total['_found']}/{total['_total']}", "medicines_heard_in_transcript": f"{total['_heard']}/{total['_total']}",
               "wrong_medications": total["_wrong"], "symptoms": f"{total['_sym']}/{total['_sym_total']}", "seconds_per_case": round(sum(row["seconds"] for row in rows) / len(rows), 1)}
    print("SUMMARY " + json.dumps(summary))
    Path(args.out).write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
