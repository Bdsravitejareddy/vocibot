from app.domain.types import EvidenceStatus, Speaker, TranscriptSegmentInput
from app.services.evidence import EvidenceValidator


def test_currency_amount_in_medication_context_stays_needs_review() -> None:
    segments = [TranscriptSegmentInput(id="p1", speaker=Speaker.PATIENT, text="also recommended $650 for fever last time", timestamp="00:00:01", sequence_number=0)]

    result = EvidenceValidator().validate("medications", ["$650"], ["p1"], segments)

    assert result.status == EvidenceStatus.NEEDS_REVIEW


def test_explicit_dolo_650_is_supported_without_rewriting_raw_evidence() -> None:
    segments = [TranscriptSegmentInput(id="p1", speaker=Speaker.PATIENT, text="I took Dolo 650", timestamp="00:00:01", sequence_number=0)]

    result = EvidenceValidator().validate("medications", ["Dolo 650"], ["p1"], segments)

    assert result.status == EvidenceStatus.SUPPORTED
