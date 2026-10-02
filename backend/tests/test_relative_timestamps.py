from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import TranscriptSegment
from app.schemas import ConsultationCreate, SegmentCreate
from app.services.consultations import append_segment, create_consultation, get_consultation
from app.domain.types import Speaker


def test_transcript_persistence_is_relative_not_wall_clock():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    consultation = create_consultation(session, ConsultationCreate(patient_id="TIME-001", age=30, sex="Female"))
    append_segment(session, consultation.id, SegmentCreate(id="t1", speaker=Speaker.PATIENT, text="hello", timestamp="00:00:07", sequence_number=0))
    loaded = get_consultation(session, consultation.id)
    assert loaded["transcript"][0]["timestamp"] == "00:00:07"
    stored = session.get(TranscriptSegment, "t1")
    assert stored.timestamp == "00:00:07"
