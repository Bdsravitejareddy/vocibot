from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain.types import CandidateClinicalUpdate, ClinicalRecord, EvidenceStatus, ExtractionResult, Speaker
from app.schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from app.services.consultations import approve_consultation, append_segment, create_consultation, get_consultation, stop_consultation
from app.providers.speech import TranscriptDraft
from app.domain.types import CandidateClinicalUpdate, ExtractionResult
from app.services.consultations import replace_with_reconciled_transcript


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


def test_transcript_language_code_is_persisted_for_review_and_extraction() -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="LANG-TE-001", age=30, sex="Female"))

    append_segment(
        session,
        consultation.id,
        SegmentCreate(id="te-1", speaker=Speaker.PATIENT, text="నమస్కారం", timestamp="00:00:01", sequence_number=0, language_code="te"),
    )

    loaded = get_consultation(session, consultation.id)
    assert loaded["transcript"][0]["language_code"] == "te"


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


def test_malformed_local_extraction_value_is_rejected_without_breaking_transcript(monkeypatch) -> None:
    class MalformedProvider:
        def extract(self, transcript, current):
            return ExtractionResult(
                proposed_record=ClinicalRecord(),
                candidates=[
                    CandidateClinicalUpdate(field_name="presenting_symptoms", value="patient", source_segment_ids=["s1"], speaker=Speaker.UNKNOWN, status=EvidenceStatus.SUPPORTED),
                ],
            )

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda settings: MalformedProvider())
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="MALFORMED-001", age=30, sex="Male"))

    result = append_segment(session, consultation.id, SegmentCreate(id="s1", speaker=Speaker.UNKNOWN, text="patient", timestamp="2026-09-26T10:32:05Z", sequence_number=0))

    assert result["duplicate"] is False
    assert result["consultation"]["transcript"][0]["text"] == "patient"
    assert result["consultation"]["record"]["presenting_symptoms"] == []


def test_unavailable_local_extractor_keeps_transcript_reviewable(monkeypatch) -> None:
    def unavailable(_settings):
        raise RuntimeError("local extraction service is unavailable")

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", unavailable)
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="NO-EXTRACT-001", age=30, sex="Female"))

    result = append_segment(session, consultation.id, SegmentCreate(id="offline-1", speaker=Speaker.PATIENT, text="ನನಗೆ ಜ್ವರ ಇದೆ", timestamp="00:00:01", sequence_number=0, language_code="kn"))

    assert result["consultation"]["transcript"][0]["text"] == "ನನಗೆ ಜ್ವರ ಇದೆ"
    assert result["consultation"]["record"]["chief_complaint"] is None


def test_reconciled_transcript_reextracts_cross_segment_facts(monkeypatch) -> None:
    class ReconciledProvider:
        def extract(self, transcript, current):
            ids = [item.id for item in transcript]
            return ExtractionResult(
                proposed_record=current,
                candidates=[
                    CandidateClinicalUpdate(field_name="duration", value="2 weeks", source_segment_ids=[ids[0], ids[1]], speaker=Speaker.UNKNOWN, status=EvidenceStatus.SUPPORTED),
                    CandidateClinicalUpdate(field_name="presenting_symptoms", value=["Cough", "Cold", "Nauseous", "Headache"], source_segment_ids=[ids[0], ids[2]], speaker=Speaker.UNKNOWN, status=EvidenceStatus.SUPPORTED),
                ],
            )

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda settings: ReconciledProvider())
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="RECON-001", age=30, sex="Female"))
    result = replace_with_reconciled_transcript(session, consultation.id, [
        TranscriptDraft(text="I've had it for", timestamp="00:00:01", start_ms=1000, end_ms=1800),
        TranscriptDraft(text="Two weeks", timestamp="00:00:02", start_ms=2000, end_ms=2600),
        TranscriptDraft(text="a cough and cold; I am feeling nauseous and headache", timestamp="00:00:03", start_ms=3000, end_ms=5000),
    ])

    assert result["record"]["duration"] == "2 weeks"
    assert result["record"]["presenting_symptoms"] == ["Cough", "Cold", "Nauseous", "Headache"]
