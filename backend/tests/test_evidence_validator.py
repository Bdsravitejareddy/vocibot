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


def test_value_must_be_semantically_supported_by_cited_transcript() -> None:
    segments = [TranscriptSegmentInput(id="p1", speaker=Speaker.PATIENT, text="There is no fever and I have a headache.", timestamp="2026-09-26T10:00:00Z", sequence_number=0)]

    result = EvidenceValidator().validate("chief_complaint", "Fever", ["p1"], segments)

    assert result.status == EvidenceStatus.NEEDS_REVIEW


def test_duration_can_be_supported_by_adjacent_transcript_segments() -> None:
    segments = [
        TranscriptSegmentInput(id="p1", speaker=Speaker.PATIENT, text="I've had it for", timestamp="00:00:01", sequence_number=0),
        TranscriptSegmentInput(id="p2", speaker=Speaker.PATIENT, text="Two weeks", timestamp="00:00:02", sequence_number=1),
    ]

    result = EvidenceValidator().validate("history_present_illness", "I've had it for two weeks", ["p1", "p2"], segments)

    assert result.status == EvidenceStatus.SUPPORTED
    assert result.source_segment_ids == ["p1", "p2"]


def test_multiple_symptoms_can_be_supported_across_adjacent_segments() -> None:
    segments = [
        TranscriptSegmentInput(id="p1", speaker=Speaker.PATIENT, text="a cough and cold", timestamp="00:00:01", sequence_number=0),
        TranscriptSegmentInput(id="p2", speaker=Speaker.PATIENT, text="I am also feeling nauseous and headache", timestamp="00:00:02", sequence_number=1),
    ]

    result = EvidenceValidator().validate("presenting_symptoms", ["Cough", "Cold", "Nauseous", "Headache"], ["p1", "p2"], segments)

    assert result.status == EvidenceStatus.SUPPORTED
