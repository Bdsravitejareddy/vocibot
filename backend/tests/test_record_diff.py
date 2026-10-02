from app.domain.types import ClinicalRecord, EvidenceStatus
from app.services.record_diff import diff_clinical_record


def test_diff_emits_changed_fields_and_keeps_evidence() -> None:
    current = ClinicalRecord()
    proposed = current.model_copy(update={"chief_complaint": "Fever", "duration": "3 days"})
    changes = diff_clinical_record(current, proposed, {"chief_complaint": ["s2"], "duration": ["s2"]})
    assert [(change.field_name, change.new_value) for change in changes] == [("chief_complaint", "Fever"), ("duration", "3 days")]
    assert changes[0].source_segment_ids == ["s2"]


def test_doctor_edited_field_is_not_overwritten_by_ai() -> None:
    current = ClinicalRecord(chief_complaint="Doctor corrected fever")
    proposed = current.model_copy(update={"chief_complaint": "Fever"})
    changes = diff_clinical_record(current, proposed, {"chief_complaint": ["s2"]}, doctor_edited_fields={"chief_complaint"})
    assert changes == []
