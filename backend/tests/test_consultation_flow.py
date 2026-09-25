from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain.types import ClinicalRecord, Speaker
from app.schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from app.services.consultations import approve_consultation, append_segment, create_consultation, get_consultation, stop_consultation


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def test_consultation_flow_persists_transcript_record_and_audit_evidence() -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="DEMO-001", patient_name="Demo Patient", age=42, sex="Female"))
    append_segment(session, consultation.id, SegmentCreate(id="s1", speaker=Speaker.PATIENT, text="I've had fever for three days.", timestamp="2026-09-26T10:32:05Z", sequence_number=0))
    append_segment(session, consultation.id, SegmentCreate(id="s2", speaker=Speaker.PATIENT, text="No breathing difficulty.", timestamp="2026-09-26T10:32:17Z", sequence_number=1))
    stop_consultation(session, consultation.id)
    final = approve_consultation(session, consultation.id, ApproveRequest(record=ClinicalRecord(chief_complaint="Fever")))
    assert final.status == "APPROVED"
    loaded = get_consultation(session, consultation.id)
    assert [segment["id"] for segment in loaded["transcript"]] == ["s1", "s2"]
    assert loaded["record"]["chief_complaint"] == "Fever"
    assert any(update["source_segment_ids"] == ["s1"] for update in loaded["updates"])
    assert any(update["update_type"] == "DOCTOR_APPROVED" for update in loaded["updates"])


def test_duplicate_segment_does_not_duplicate_transcript_or_audit() -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="DEMO-002", age=30, sex="Male"))
    segment = SegmentCreate(id="same", speaker=Speaker.PATIENT, text="I have fever.", timestamp="2026-09-26T10:32:05Z", sequence_number=0)
    first = append_segment(session, consultation.id, segment)
    second = append_segment(session, consultation.id, segment)
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    loaded = get_consultation(session, consultation.id)
    assert len(loaded["transcript"]) == 1
    assert len(loaded["updates"]) == 2


def test_approval_is_rejected_while_consultation_is_in_progress() -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="DEMO-003", age=55, sex="Female"))
    try:
        approve_consultation(session, consultation.id, ApproveRequest(record=ClinicalRecord()))
    except ValueError as error:
        assert "ready for review" in str(error).lower()
    else:
        raise AssertionError("approval should require a stopped consultation")


def test_doctor_edit_wins_without_deleting_ai_history() -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="DEMO-004", age=65, sex="Male"))
    append_segment(session, consultation.id, SegmentCreate(id="s1", speaker=Speaker.PATIENT, text="I've had fever.", timestamp="2026-09-26T10:32:05Z", sequence_number=0))
    stop_consultation(session, consultation.id)
    approve_consultation(session, consultation.id, ApproveRequest(record=ClinicalRecord(chief_complaint="Recurrent fever")))
    loaded = get_consultation(session, consultation.id)
    assert loaded["record"]["chief_complaint"] == "Recurrent fever"
    assert any(update["update_type"] == "AI_EXTRACTED" for update in loaded["updates"])
    assert any(update["update_type"] == "DOCTOR_EDITED" for update in loaded["updates"])
