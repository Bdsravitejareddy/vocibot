from app.domain.types import ClinicalRecord, EvidenceStatus, Speaker, TranscriptSegmentInput
from app.providers.demo_extraction import DemoClinicalExtractionProvider
from app.services.evidence import EvidenceValidator


def segments(*items: tuple[str, Speaker, str]) -> list[TranscriptSegmentInput]:
    return [TranscriptSegmentInput(id=key, speaker=speaker, text=text, timestamp="10:32:05", sequence_number=index) for index, (key, speaker, text) in enumerate(items)]


def test_demo_extraction_populates_only_supported_facts() -> None:
    transcript = segments(
        ("s1", Speaker.DOCTOR, "What brings you in today?"),
        ("s2", Speaker.PATIENT, "I've had fever for three days."),
        ("s3", Speaker.DOCTOR, "Any cough?"),
        ("s4", Speaker.PATIENT, "Yes, a dry cough since yesterday."),
        ("s5", Speaker.DOCTOR, "Any breathing difficulty?"),
        ("s6", Speaker.PATIENT, "No."),
        ("s7", Speaker.DOCTOR, "Are you taking any medication?"),
        ("s8", Speaker.PATIENT, "Just paracetamol."),
    )
    result = DemoClinicalExtractionProvider().extract(transcript, ClinicalRecord())
    assert result.proposed_record.chief_complaint == "Fever"
    assert result.proposed_record.duration == "3 days"
    assert result.proposed_record.presenting_symptoms == ["Fever", "Dry cough"]
    assert result.proposed_record.relevant_negatives == ["No breathing difficulty reported"]
    assert result.proposed_record.medications == ["Paracetamol"]
    assert result.proposed_record.assessment is None
    assert result.proposed_record.plan is None
    assert result.proposed_record.vitals == {}
    assert all(candidate.status == EvidenceStatus.SUPPORTED for candidate in result.candidates)


def test_uncertain_doctor_statement_stays_uncertain_and_symptoms_do_not_become_diagnosis() -> None:
    transcript = segments(
        ("s1", Speaker.PATIENT, "I have a cough."),
        ("s2", Speaker.DOCTOR, "This could possibly be viral."),
    )
    result = DemoClinicalExtractionProvider().extract(transcript, ClinicalRecord())
    assert result.proposed_record.assessment == "Possible viral illness"
    assert result.proposed_record.chief_complaint == "Cough"
    assert result.proposed_record.plan is None


def test_unsupported_information_is_rejected_by_evidence_validator() -> None:
    validator = EvidenceValidator()
    accepted = validator.validate("chief_complaint", "Fever", ["s1"], segments(("s1", Speaker.PATIENT, "I have fever.")))
    rejected = validator.validate("assessment", "Pneumonia", ["missing"], segments(("s1", Speaker.PATIENT, "I have cough.")))
    assert accepted.status == EvidenceStatus.SUPPORTED
    assert rejected.status == EvidenceStatus.REJECTED
