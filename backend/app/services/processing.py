"""Background processing after Stop: final transcript, then the clinical note.

Jobs run one at a time on a single worker, so the note model (the largest
memory user) is only ever loaded once and used by one job at a time, no
matter how many clinicians finish consultations together. Job state lives
in the database, so work queued before a restart resumes afterwards.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import queue
import threading

from sqlalchemy import func, select

from ..db import SessionLocal
from ..models import Consultation

logger = logging.getLogger(__name__)

ACTIVE = ("queued", "transcribing", "writing_note")
_jobs: queue.Queue[str] = queue.Queue()
_start_lock = threading.Lock()
_worker: threading.Thread | None = None


class ProcessingBusy(Exception):
    """The consultation already has queued or running processing."""


def enqueue(session, consultation: Consultation, plan: str) -> None:
    """Queue processing stages ("transcribe,note" or "note") for a consultation."""

    if consultation.processing_status in ACTIVE:
        raise ProcessingBusy("This consultation is already being processed.")
    consultation.processing_plan = plan
    consultation.processing_status = "queued"
    consultation.processing_error = None
    consultation.processing_warnings = []
    consultation.processing_queued_at = datetime.now(timezone.utc)
    session.commit()
    _ensure_worker()
    _jobs.put(consultation.id)


def describe(session, consultation: Consultation) -> dict:
    position = None
    if consultation.processing_status == "queued" and consultation.processing_queued_at is not None:
        position = session.scalar(select(func.count()).select_from(Consultation).where(Consultation.processing_status.in_(ACTIVE), Consultation.processing_queued_at < consultation.processing_queued_at))
    return {
        "status": consultation.processing_status,
        "plan": consultation.processing_plan,
        "error": consultation.processing_error,
        "warnings": consultation.processing_warnings or [],
        "jobs_ahead": position,
    }


def resume_unfinished() -> int:
    """Re-queue jobs interrupted by a restart, oldest first."""

    with SessionLocal() as session:
        pending = session.scalars(select(Consultation).where(Consultation.processing_status.in_(ACTIVE)).order_by(Consultation.processing_queued_at)).all()
        for consultation in pending:
            consultation.processing_status = "queued"
        session.commit()
        ids = [consultation.id for consultation in pending]
    if ids:
        _ensure_worker()
        for consultation_id in ids:
            _jobs.put(consultation_id)
    return len(ids)


def wait_until_idle(timeout: float = 30.0) -> bool:
    """Block until every queued job has finished (tests and shutdown)."""

    done = threading.Event()

    def watch() -> None:
        _jobs.join()
        done.set()

    threading.Thread(target=watch, daemon=True).start()
    return done.wait(timeout)


def _ensure_worker() -> None:
    global _worker
    with _start_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="vocibot-processing", daemon=True)
            _worker.start()


def _work() -> None:
    while True:
        consultation_id = _jobs.get()
        try:
            run_job(consultation_id)
        except Exception:
            logger.exception("Processing failed for consultation %s", consultation_id)
        finally:
            _jobs.task_done()


def run_job(consultation_id: str) -> None:
    from .consultations import ConsultationStateError, reanalyse_consultation, replace_transcript_from_recordings

    warnings: list[str] = []

    def set_status(status: str, *, error: str | None = None) -> None:
        with SessionLocal() as session:
            consultation = session.get(Consultation, consultation_id)
            if consultation is not None:
                consultation.processing_status = status
                consultation.processing_warnings = list(warnings)
                if error is not None:
                    consultation.processing_error = error
                session.commit()

    with SessionLocal() as session:
        consultation = session.get(Consultation, consultation_id)
        if consultation is None or consultation.processing_status not in ACTIVE:
            return
        plan = {stage for stage in consultation.processing_plan.split(",") if stage}
    try:
        if "transcribe" in plan:
            set_status("transcribing")
            with SessionLocal() as session:
                try:
                    replace_transcript_from_recordings(session, consultation_id, _final_transcriber(warnings))
                except ConsultationStateError as error:
                    # Keep the live transcript and still write the note from it.
                    warnings.append(f"The final transcript could not be made ({error}); the live transcript was kept.")
        if "note" in plan:
            set_status("writing_note")
            with SessionLocal() as session:
                try:
                    reanalyse_consultation(session, consultation_id, warnings=warnings)
                except ConsultationStateError as error:
                    warnings.append(f"No note was written: {error}.")
        set_status("done")
    except Exception as error:
        logger.exception("Processing failed for consultation %s", consultation_id)
        set_status("failed", error=str(error) or error.__class__.__name__)


def _final_transcriber(warnings: list[str]):
    from ..api import audio as audio_api
    from .inference import ENGINE, FINAL

    pipeline = ENGINE.pipeline(audio_api.build_local_pipeline)
    stt = ENGINE.final_stt(pipeline.stt)

    def transcribe(waveform, sample_rate: int, language: str | None):
        drafts, chunk_warnings = ENGINE.transcribe_recording(stt, waveform, sample_rate, language, priority=FINAL)
        warnings.extend(chunk_warnings)
        return drafts

    return transcribe
