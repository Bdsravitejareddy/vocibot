from ..domain.types import CandidateClinicalUpdate, EvidenceStatus, Speaker, TranscriptSegmentInput


class EvidenceValidator:
    def validate(self, field_name: str, value: object, source_segment_ids: list[str], transcript: list[TranscriptSegmentInput]) -> CandidateClinicalUpdate:
        sources = {segment.id: segment for segment in transcript}
        segments = [sources[segment_id] for segment_id in source_segment_ids if segment_id in sources]
        if not segments or not value:
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=source_segment_ids, speaker=Speaker.UNKNOWN, status=EvidenceStatus.REJECTED)
        if field_name in {"assessment", "plan", "follow_up"} and not any(segment.speaker == Speaker.DOCTOR for segment in segments):
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=source_segment_ids, speaker=Speaker.PATIENT, status=EvidenceStatus.REJECTED)
        speaker = segments[0].speaker
        normalized = str(value).lower()
        status = EvidenceStatus.NEEDS_REVIEW if any(marker in normalized for marker in ("maybe", "may be", "possibly", "possible", "uncertain", "could be")) else EvidenceStatus.SUPPORTED
        return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=status)
