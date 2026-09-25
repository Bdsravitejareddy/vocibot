from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Consultation
from ..schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from ..services.consultations import approve_consultation, append_segment, create_consultation, get_consultation, stop_consultation

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


@router.post("/{consultation_id}/segments")
def add_segment(consultation_id: str, payload: SegmentCreate, session: Session = Depends(get_session)) -> dict:
    try:
        return append_segment(session, consultation_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{consultation_id}/stop")
def stop(consultation_id: str, session: Session = Depends(get_session)) -> dict:
    try:
        stop_consultation(session, consultation_id)
        return get_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{consultation_id}/approve")
def approve(consultation_id: str, payload: ApproveRequest, session: Session = Depends(get_session)) -> dict:
    try:
        approve_consultation(session, consultation_id, payload)
        return get_consultation(session, consultation_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
