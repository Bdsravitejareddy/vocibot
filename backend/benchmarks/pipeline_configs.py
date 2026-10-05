"""The clinic's real recordings through the full pipeline (transcript,
translation, note) under one configuration, to compare engine choices.

Outputs contain patient conversations: keep them on this computer, never in git.

    # A: Whisper only   B: IndicConformer + Whisper audio translation   C: current
    INDIC_ASR_MODELS_DIR= PYTHONPATH=backend .venv/bin/python backend/benchmarks/pipeline_configs.py A VB-20261005-SYJAZB ...
    INDIC_TEXT_TRANSLATION_LANGUAGES= PYTHONPATH=backend .venv/bin/python backend/benchmarks/pipeline_configs.py B VB-...
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "backend/benchmarks")
from transcription_accuracy import load_audio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.api.audio import build_local_pipeline, restrict_languages
from app.db import Base
from app.providers.reconciliation import FinalReconciler
from app.schemas import ConsultationCreate
from app.services import consultations as service

R = Path.home() / "Library/Application Support/vocibot/recordings"
CODES = sys.argv[2:]
pipeline = build_local_pipeline()
restrict_languages(pipeline.stt, {"en", "te", "hi", "ta", "mr", "gu"})
print("ENGINE", type(pipeline.stt).__name__, flush=True)
for code in CODES:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    audio = load_audio(R / f"{code}.flac")
    started = time.perf_counter()
    result = FinalReconciler().run(audio, pipeline.stt, sample_rate=16_000)
    c = service.create_consultation(db, ConsultationCreate(patient_id=code[-6:], age=40, sex="Female"))
    service.replace_with_reconciled_transcript(db, c.id, result.transcripts, extract=False, translations=result.translations)
    loaded = service.extract_reconciled_clinical_record(db, c.id)
    note = {k: v for k, v in loaded["record"].items() if v not in (None, "", [], {})}
    print(json.dumps({"label": sys.argv[1], "session": code, "seconds": round(time.perf_counter() - started, 1),
                      "transcript": [f"[{l.get('language_code')}] {l['text']}" for l in loaded["transcript"]],
                      "translation": [l["text"] for l in loaded.get("translation") or []],
                      "fields": len(note), "note": note}, ensure_ascii=False), flush=True)
