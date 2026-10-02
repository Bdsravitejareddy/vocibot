from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..languages import enabled_languages
from .audio import restrict_languages
from ..config import settings
from ..models import Consultation, Recording
from ..providers.factory import build_speech_provider
from ..providers.reconciliation import FinalReconciler
from ..services.recordings import AUDIO_MEDIA_TYPES
from ..schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from ..services.consultations import ConsultationStateError, approve_consultation, append_segment, create_consultation, delete_consultation, extract_reconciled_clinical_record, get_consultation, reanalyse_consultation, retranscribe_consultation, stop_consultation
from ..services.approved_note_export import build_approved_note_payload

router = APIRouter(prefix="/api/consultations", tags=["consultations"])


@router.post("")
def create(payload: ConsultationCreate, session: Session = Depends(get_session)) -> dict:
    return get_consultation(session, create_consultation(session, payload).id)


@router.get("")
def list_consultations(session: Session = Depends(get_session)) -> list[dict]:
    consultations = session.scalars(select(Consultation).order_by(Consultation.created_at.desc())).all()
    return [get_consultation(session, consultation.id) for consultation in consultations]


@router.get("/{consultation_id}")
def detail(consultation_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return get_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{consultation_id}", status_code=204)
def discard(consultation_id: str, session: Session = Depends(get_session)) -> None:
    try:
        delete_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{consultation_id}/segments")
def add_segment(consultation_id: str, payload: SegmentCreate, session: Session = Depends(get_session)) -> dict:
    try:
        return append_segment(session, consultation_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{consultation_id}/stop")
def stop(consultation_id: str, infer_final_record: bool = False, session: Session = Depends(get_session)) -> dict:
    try:
        warnings: list[str] = []
        if infer_final_record:
            extract_reconciled_clinical_record(session, consultation_id, warnings=warnings, require_authoritative=True)
        stop_consultation(session, consultation_id)
        result = get_consultation(session, consultation_id)
        result["finalization_warnings"] = warnings
        return result
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{consultation_id}/reanalyse")
def reanalyse(consultation_id: str, session: Session = Depends(get_session)) -> dict:
    warnings: list[str] = []
    try:
        result = reanalyse_consultation(session, consultation_id, warnings=warnings)
    except ConsultationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    result["finalization_warnings"] = warnings
    return result


@router.post("/{consultation_id}/retranscribe")
def retranscribe(consultation_id: str, session: Session = Depends(get_session)) -> dict:
    stt = build_speech_provider(settings)
    restrict_languages(stt, set(enabled_languages(session)))

    def transcribe(waveform, sample_rate: int, language: str | None):
        result = FinalReconciler().run(waveform, stt, sample_rate=sample_rate, language=language)
        warnings.extend(result.warnings)
        return result

    warnings: list[str] = []
    try:
        result = retranscribe_consultation(session, consultation_id, transcribe, warnings=warnings)
    except ConsultationStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    result["finalization_warnings"] = warnings
    return result


@router.get("/{consultation_id}/recordings/{recording_id}/audio")
def recording_audio(consultation_id: str, recording_id: str, session: Session = Depends(get_session)) -> FileResponse:
    recording = session.get(Recording, recording_id)
    if recording is None or recording.consultation_id != consultation_id or not Path(recording.file_path).is_file():
        raise HTTPException(status_code=404, detail="recording not found")
    return FileResponse(recording.file_path, media_type=AUDIO_MEDIA_TYPES.get(recording.format, "application/octet-stream"), filename=Path(recording.file_path).name)


@router.post("/{consultation_id}/approve")
def approve(consultation_id: str, payload: ApproveRequest, session: Session = Depends(get_session)) -> dict:
    try:
        approve_consultation(session, consultation_id, payload)
        return get_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{consultation_id}/approved-note")
def approved_note(consultation_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        return build_approved_note_payload(get_consultation(session, consultation_id))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
