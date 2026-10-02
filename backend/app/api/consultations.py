from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Consultation, Patient, Recording, User
from .auth import client_ip, current_user
from ..services.auth import log_event
from ..services.processing import ACTIVE, ProcessingBusy, enqueue
from ..services.recordings import AUDIO_MEDIA_TYPES
from ..schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from ..services.consultations import approve_consultation, append_segment, create_consultation, delete_consultation, get_consultation, stop_consultation
from ..services.approved_note_export import build_approved_note_payload

router = APIRouter(prefix="/api/consultations", tags=["consultations"])


def clinician(user: User = Depends(current_user)) -> User:
    """A signed-in user allowed to work with clinical data."""

    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Please change your temporary password before continuing.")
    return user


def owned(consultation_id: str, user: User = Depends(clinician), session: Session = Depends(get_session)) -> Consultation:
    """The caller's own consultation; other users' consultations are reported as not found."""

    consultation = session.get(Consultation, consultation_id)
    if consultation is None or consultation.owner_id != user.id:
        raise HTTPException(status_code=404, detail="consultation not found")
    return consultation


@router.post("")
def create(payload: ConsultationCreate, user: User = Depends(clinician), session: Session = Depends(get_session)) -> dict:
    return get_consultation(session, create_consultation(session, payload, owner_id=user.id).id)


@router.get("")
def list_consultations(limit: int = 50, offset: int = 0, q: str = "", user: User = Depends(clinician), session: Session = Depends(get_session)) -> dict:
    """A page of the caller's consultations as light summaries (no transcripts)."""

    limit = min(max(limit, 1), 200)
    query = select(Consultation).join(Patient).where(Consultation.owner_id == user.id)
    if q.strip():
        term = f"%{q.strip().lower()}%"
        query = query.where(func.lower(Patient.patient_identifier).like(term) | func.lower(func.coalesce(Patient.name, "")).like(term) | func.lower(Consultation.session_code).like(term))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    rows = session.scalars(query.order_by(Consultation.created_at.desc()).limit(limit).offset(max(offset, 0))).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [summarise(item) for item in rows]}


def summarise(consultation: Consultation) -> dict:
    record = consultation.clinical_record.structured_data_json if consultation.clinical_record else {}
    return {
        "id": consultation.id,
        "session_code": consultation.session_code,
        "status": consultation.status,
        "started_at": consultation.started_at.isoformat(),
        "ended_at": consultation.ended_at.isoformat() if consultation.ended_at else None,
        "patient": {"id": consultation.patient.id, "patient_identifier": consultation.patient.patient_identifier, "name": consultation.patient.name, "age": consultation.patient.age, "sex": consultation.patient.sex},
        "chief_complaint": record.get("chief_complaint"),
        "has_audio": bool(consultation.recordings),
    }


@router.get("/{consultation_id}")
def detail(consultation_id: str, _: Consultation = Depends(owned), session: Session = Depends(get_session)) -> dict:
    try:
        return get_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{consultation_id}", status_code=204)
def discard(consultation_id: str, request: Request, consultation: Consultation = Depends(owned), user: User = Depends(clinician), session: Session = Depends(get_session)) -> None:
    session_code, status = consultation.session_code, consultation.status
    try:
        delete_consultation(session, consultation_id)
        # Clinical rows are gone; the security log keeps who discarded what.
        log_event(session, "consultation_discarded", actor=user, ip=client_ip(request), session_code=session_code, status=status)
        session.commit()
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{consultation_id}/segments")
def add_segment(consultation_id: str, payload: SegmentCreate, _: Consultation = Depends(owned), session: Session = Depends(get_session)) -> dict:
    try:
        return append_segment(session, consultation_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{consultation_id}/stop")
def stop(consultation_id: str, consultation: Consultation = Depends(owned), session: Session = Depends(get_session)) -> dict:
    """Finish recording; the final transcript and note are made in the background."""

    was_in_progress = consultation.status == "IN_PROGRESS"
    stop_consultation(session, consultation_id)
    session.refresh(consultation)
    if was_in_progress and consultation.recordings:
        try:
            enqueue(session, consultation, "transcribe,note")
        except ProcessingBusy:
            pass
    return get_consultation(session, consultation_id)


@router.post("/{consultation_id}/reanalyse")
def reanalyse(consultation_id: str, consultation: Consultation = Depends(owned), session: Session = Depends(get_session)) -> dict:
    """Queue a refill of the AI note from the saved transcript."""

    if consultation.status == "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="stop the consultation before re-analysing its note")
    if not consultation.transcript_segments:
        raise HTTPException(status_code=409, detail="this consultation has no transcript to analyse")
    _queue(session, consultation, "note")
    return get_consultation(session, consultation_id)


def _queue(session: Session, consultation: Consultation, plan: str) -> None:
    try:
        enqueue(session, consultation, plan)
    except ProcessingBusy as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{consultation_id}/retranscribe")
def retranscribe(consultation_id: str, consultation: Consultation = Depends(owned), session: Session = Depends(get_session)) -> dict:
    """Queue a fresh transcript from the stored audio, then a note refill."""

    if consultation.status == "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="stop the consultation before re-transcribing it")
    if not consultation.recordings:
        raise HTTPException(status_code=409, detail="this consultation has no stored audio")
    _queue(session, consultation, "transcribe,note")
    return get_consultation(session, consultation_id)


@router.get("/{consultation_id}/recordings/{recording_id}/audio")
def recording_audio(consultation_id: str, recording_id: str, _: Consultation = Depends(owned), session: Session = Depends(get_session)) -> FileResponse:
    recording = session.get(Recording, recording_id)
    if recording is None or recording.consultation_id != consultation_id or not Path(recording.file_path).is_file():
        raise HTTPException(status_code=404, detail="recording not found")
    return FileResponse(recording.file_path, media_type=AUDIO_MEDIA_TYPES.get(recording.format, "application/octet-stream"), filename=Path(recording.file_path).name)


@router.post("/{consultation_id}/approve")
def approve(consultation_id: str, payload: ApproveRequest, consultation: Consultation = Depends(owned), user: User = Depends(clinician), session: Session = Depends(get_session)) -> dict:
    if consultation.processing_status in ACTIVE:
        raise HTTPException(status_code=409, detail="The transcript and note are still being prepared; approve when they are ready.")
    try:
        approve_consultation(session, consultation_id, payload, actor_id=user.id)
        return get_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{consultation_id}/approved-note")
def approved_note(consultation_id: str, _: Consultation = Depends(owned), session: Session = Depends(get_session)) -> dict:
    try:
        return build_approved_note_payload(get_consultation(session, consultation_id))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
