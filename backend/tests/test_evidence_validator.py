from app.domain.types import CandidateClinicalUpdate, ClinicalRecord, EvidenceStatus, Speaker, TranscriptSegmentInput
from app.services.evidence import EvidenceValidator


def transcript() -> list[TranscriptSegmentInput]:
    return [TranscriptSegmentInput(id="p1", speaker=Speaker.PATIENT, text="I have fever for three days", timestamp="2026-09-26T10:00:00Z", sequence_number=0)]


def test_rejects_candidate_with_unknown_source_segment() -> None:
    candidate = CandidateClinicalUpdate(field_name="chief_complaint", value="fever", source_segment_ids=["missing"], speaker=Speaker.PATIENT, status=EvidenceStatus.SUPPORTED)
    result = EvidenceValidator().validate(candidate.field_name, candidate.value, candidate.source_segment_ids, transcript())
    assert result.status == EvidenceStatus.REJECTED


def test_requires_doctor_statement_for_assessment() -> None:
    candidate = CandidateClinicalUpdate(field_name="assessment", value="viral infection", source_segment_ids=["p1"], speaker=Speaker.PATIENT, status=EvidenceStatus.SUPPORTED)
    result = EvidenceValidator().validate(candidate.field_name, candidate.value, candidate.source_segment_ids, transcript())
    assert result.status == EvidenceStatus.REJECTED


def test_preserves_uncertainty_as_needs_review() -> None:
    segments = [TranscriptSegmentInput(id="d1", speaker=Speaker.DOCTOR, text="This may be viral", timestamp="2026-09-26T10:00:00Z", sequence_number=0)]
    candidate = CandidateClinicalUpdate(field_name="assessment", value="may be viral", source_segment_ids=["d1"], speaker=Speaker.DOCTOR, status=EvidenceStatus.SUPPORTED)
    result = EvidenceValidator().validate(candidate.field_name, candidate.value, candidate.source_segment_ids, segments)
    assert result.status == EvidenceStatus.NEEDS_REVIEW
