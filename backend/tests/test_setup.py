from app.domain.types import ClinicalRecord, ConsultationStatus, EvidenceStatus


def test_empty_clinical_record_contains_only_unset_values() -> None:
    record = ClinicalRecord()
    assert record.chief_complaint is None
    assert record.presenting_symptoms == []
    assert record.vitals == {}
    assert ConsultationStatus.IN_PROGRESS.value == "IN_PROGRESS"
    assert EvidenceStatus.NEEDS_REVIEW.value == "NEEDS_REVIEW"
