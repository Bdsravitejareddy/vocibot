from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain.types import CandidateClinicalUpdate, ClinicalRecord, EvidenceStatus, ExtractionResult, Speaker
from app.schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from app.services.consultations import ConsultationStateError, approve_consultation, append_segment, create_consultation, delete_consultation, extract_reconciled_clinical_record, get_consultation, reanalyse_consultation, stop_consultation
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


def test_provisional_live_segment_is_persisted_without_clinical_extraction(monkeypatch) -> None:
    extraction_calls = []

    def must_not_extract(_settings):
        extraction_calls.append(True)
        raise AssertionError("provisional live ASR must not populate the clinical record")

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", must_not_extract)
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="LIVE-001", age=42, sex="Female"))

    result = append_segment(
        session,
        consultation.id,
        SegmentCreate(
            id="live-1",
            speaker=Speaker.UNKNOWN,
            text="unmonitor",
            timestamp="00:00:35",
            sequence_number=0,
            provisional=True,
        ),
    )

    assert result["consultation"]["transcript"][0]["text"] == "unmonitor"
    assert result["consultation"]["record"]["chief_complaint"] is None
    assert result["consultation"]["updates"] == []
    assert extraction_calls == []


def test_final_inference_refuses_a_provisional_only_transcript(monkeypatch) -> None:
    extraction_calls = []

    def must_not_extract(_settings):
        extraction_calls.append(True)
        raise AssertionError("provisional transcript must never reach clinical inference")

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", must_not_extract)
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="LIVE-SAFETY-001", age=42, sex="Female"))
    append_segment(
        session,
        consultation.id,
        SegmentCreate(id="live-wrong", speaker=Speaker.UNKNOWN, text="unmonitor", timestamp="00:00:35", sequence_number=0, provisional=True),
    )
    warnings = []

    result = extract_reconciled_clinical_record(session, consultation.id, warnings=warnings, require_authoritative=True)

    assert extraction_calls == []
    assert result["record"]["chief_complaint"] is None
    assert warnings == ["Clinical note inference was skipped because no authoritative final transcript was available."]


def test_client_cannot_spoof_an_authoritative_final_segment_id() -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="LIVE-SPOOF-001", age=42, sex="Female"))

    try:
        append_segment(
            session,
            consultation.id,
            SegmentCreate(
                id=f"{consultation.id}-final-0",
                speaker=Speaker.PATIENT,
                text="Fever",
                timestamp="00:00:01",
                sequence_number=0,
                provisional=True,
            ),
        )
    except ValueError as error:
        assert "server-reserved" in str(error)
    else:
        raise AssertionError("client supplied final transcript IDs must be rejected")


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


def test_reconciled_transcript_reports_nonfatal_extraction_failure(monkeypatch) -> None:
    def unavailable(_settings):
        raise RuntimeError("local model timed out")

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", unavailable)
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="RECON-WARN-001", age=30, sex="Female"))
    warnings = []

    result = replace_with_reconciled_transcript(
        session,
        consultation.id,
        [TranscriptDraft(text="Final accurate transcript", timestamp="00:00:00", start_ms=0, end_ms=1000)],
        warnings=warnings,
    )

    assert result["transcript"][0]["text"] == "Final accurate transcript"
    assert warnings == ["Clinical note inference did not finish. The final transcript is available for manual review."]


def test_discarding_a_consultation_removes_its_transcript_record_audit_and_orphan_patient() -> None:
    from app.models import ClinicalRecord as ClinicalRecordModel, Consultation, Patient, RecordUpdate, TranscriptSegment

    session = make_session()
    kept = create_consultation(session, ConsultationCreate(patient_id="KEEP-1", age=50, sex="Male"))
    test_run = create_consultation(session, ConsultationCreate(patient_id="TEST-1", age=40, sex="Female"))
    append_segment(session, test_run.id, SegmentCreate(id="t1", speaker=Speaker.PATIENT, text="I've had fever for three days.", timestamp="2026-09-26T10:32:05Z", sequence_number=0))
    stop_consultation(session, test_run.id)
    approve_consultation(session, test_run.id, ApproveRequest(record=ClinicalRecord(chief_complaint="Fever")))

    delete_consultation(session, test_run.id)

    assert [item.id for item in session.query(Consultation).all()] == [kept.id]
    assert session.query(TranscriptSegment).count() == 0
    assert session.query(RecordUpdate).count() == 0
    assert session.query(ClinicalRecordModel).count() == 1
    assert [item.patient_identifier for item in session.query(Patient).all()] == ["KEEP-1"]


def test_discarding_one_visit_keeps_a_patient_with_other_visits() -> None:
    from app.models import Patient

    session = make_session()
    first = create_consultation(session, ConsultationCreate(patient_id="SAME-1", age=40, sex="Female"))
    second = create_consultation(session, ConsultationCreate(patient_id="SAME-1", age=40, sex="Female"))

    delete_consultation(session, first.id)

    assert get_consultation(session, second.id)["patient"]["patient_identifier"] == "SAME-1"
    assert session.query(Patient).count() == 1


def test_discard_endpoint_deletes_once_then_reports_not_found() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        created = client.post("/api/consultations", json={"patient_id": "API-TEST", "age": 33, "sex": "Male"}).json()
        assert client.delete(f"/api/consultations/{created['id']}").status_code == 204
        assert client.get(f"/api/consultations/{created['id']}").status_code == 404
        assert client.delete(f"/api/consultations/{created['id']}").status_code == 404


def test_hedged_grounded_value_fills_the_field_flagged_for_review(monkeypatch) -> None:
    from app.domain.types import Speaker as S

    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="REVIEW-1", age=30, sex="Female"))
    drafts = [
        TranscriptDraft(text="It feels really dizzy and sometimes I feel nauseous.", timestamp="00:00:01", start_ms=0, end_ms=2_000),
        TranscriptDraft(text="This may be an inner ear problem.", timestamp="00:00:03", start_ms=2_000, end_ms=4_000),
    ]
    replace_with_reconciled_transcript(session, consultation.id, drafts, extract=False)
    prefix = f"{consultation.id}-final-"

    class Extractor:
        def extract(self, transcript, current):
            return ExtractionResult(proposed_record=ClinicalRecord(), candidates=[
                CandidateClinicalUpdate(field_name="presenting_symptoms", value=["dizziness", "nausea"], source_segment_ids=[prefix + "0"], speaker=S.PATIENT, status=EvidenceStatus.SUPPORTED),
                CandidateClinicalUpdate(field_name="assessment", value="may be an inner ear problem", source_segment_ids=[prefix + "1"], speaker=S.DOCTOR, status=EvidenceStatus.SUPPORTED),
                CandidateClinicalUpdate(field_name="follow_up", value="review in one week", source_segment_ids=[prefix + "1"], speaker=S.DOCTOR, status=EvidenceStatus.SUPPORTED),
            ])

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda _settings: Extractor())
    loaded = extract_reconciled_clinical_record(session, consultation.id, require_authoritative=True)

    assert loaded["record"]["presenting_symptoms"] == ["dizziness", "nausea"]
    assert loaded["record"]["assessment"] == "may be an inner ear problem"
    assert loaded["record"]["follow_up"] is None
    update_types = {update["field_name"]: update["update_type"] for update in loaded["updates"]}
    assert update_types == {"presenting_symptoms": "AI_EXTRACTED", "assessment": "AI_NEEDS_REVIEW"}


def _finished_with_transcript(session, patient_id: str, lines: list[str]):
    consultation = create_consultation(session, ConsultationCreate(patient_id=patient_id, age=30, sex="Female"))
    replace_with_reconciled_transcript(session, consultation.id, [TranscriptDraft(text=text, timestamp=f"00:00:0{index}", start_ms=index * 1_000, end_ms=index * 1_000 + 900) for index, text in enumerate(lines)], extract=False)
    stop_consultation(session, consultation.id)
    return consultation, f"{consultation.id}-final-"


def test_reanalysis_refills_ai_fields_and_keeps_doctor_edits(monkeypatch) -> None:
    from app.domain.types import Speaker as S

    session = make_session()
    consultation, prefix = _finished_with_transcript(session, "REANALYSE-1", ["It feels really dizzy and I feel nauseous.", "I've had a couple of bad headaches."])
    approve_consultation(session, consultation.id, ApproveRequest(record=ClinicalRecord(chief_complaint="Vertigo — doctor wording", history_present_illness="labyrinthitis")))

    class Extractor:
        def extract(self, transcript, current):
            return ExtractionResult(proposed_record=ClinicalRecord(), candidates=[
                CandidateClinicalUpdate(field_name="chief_complaint", value="dizziness", source_segment_ids=[prefix + "0"], speaker=S.PATIENT, status=EvidenceStatus.SUPPORTED),
                CandidateClinicalUpdate(field_name="presenting_symptoms", value=["dizziness", "nausea", "headaches"], source_segment_ids=[prefix + "0", prefix + "1"], speaker=S.PATIENT, status=EvidenceStatus.SUPPORTED),
            ])

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda _settings: Extractor())
    warnings: list[str] = []
    loaded = reanalyse_consultation(session, consultation.id, warnings=warnings)

    assert loaded["record"]["chief_complaint"] == "Vertigo — doctor wording"
    assert loaded["record"]["presenting_symptoms"] == ["dizziness", "nausea", "headaches"]
    assert loaded["record"]["history_present_illness"] == "labyrinthitis"  # doctor-edited at approval
    assert loaded["status"] == "READY_FOR_REVIEW"
    assert loaded["updates"][-1]["update_type"] == "REOPENED_FOR_REVIEW"
    assert warnings == []


def test_reanalysis_keeps_the_note_when_extraction_fails(monkeypatch) -> None:
    session = make_session()
    consultation, _prefix = _finished_with_transcript(session, "REANALYSE-2", ["I have had a fever for three days."])
    approve_consultation(session, consultation.id, ApproveRequest(record=ClinicalRecord(chief_complaint="Fever")))

    class Broken:
        def extract(self, transcript, current):
            raise RuntimeError("ollama down")

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda _settings: Broken())
    warnings: list[str] = []
    loaded = reanalyse_consultation(session, consultation.id, warnings=warnings)

    assert loaded["record"]["chief_complaint"] == "Fever"
    assert loaded["status"] == "APPROVED"
    assert warnings and "did not finish" in warnings[0]


def test_reanalysis_is_refused_while_recording() -> None:
    import pytest

    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="REANALYSE-3", age=30, sex="Female"))

    with pytest.raises(ConsultationStateError):
        reanalyse_consultation(session, consultation.id, warnings=[])
