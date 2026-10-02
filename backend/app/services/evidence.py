import re

from ..domain.types import CandidateClinicalUpdate, EvidenceStatus, Speaker, TranscriptSegmentInput
from .clinical_normalization import medication_needs_review


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
        if field_name in {"medications", "allergies"} and medication_needs_review(value, [segment.text for segment in segments]):
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=EvidenceStatus.NEEDS_REVIEW)
        if not _is_semantically_supported(value, [segment.text for segment in segments]):
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=EvidenceStatus.NEEDS_REVIEW)
        status = EvidenceStatus.NEEDS_REVIEW if any(marker in normalized for marker in ("maybe", "may be", "possibly", "possible", "uncertain", "could be")) else EvidenceStatus.SUPPORTED
        return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=status)


def _is_semantically_supported(value: object, texts: list[str]) -> bool:
    values = value if isinstance(value, list) else [value]
    # A final fact may be split across adjacent ASR segments. The cited segment
    # set is immutable evidence; joining only those cited texts allows phrases
    # such as "I've had it for" + "Two weeks" without consulting uncited text.
    joint_text = " ".join(texts)
    evidence_texts = [*texts, joint_text]
    return all(_single_value_supported(str(item), evidence_texts) for item in values if item not in (None, ""))


def _single_value_supported(value: str, texts: list[str]) -> bool:
    value_tokens = _tokens(value)
    if not value_tokens:
        return False
    value_is_negative = value_tokens[0] in {"no", "not", "without", "denies", "denied"}
    content_tokens = [token for token in value_tokens if token not in {"a", "an", "the", "for", "of", "since", "reported", "patient", "has", "have", "had", "is", "there"}]
    for text in texts:
        text_tokens = _tokens(text)
        if not all(token in text_tokens for token in content_tokens):
            continue
        if not value_is_negative and _contains_negation(text_tokens, content_tokens):
            continue
        if value_is_negative and not _contains_negation(text_tokens, content_tokens[1:] if content_tokens and content_tokens[0] in {"no", "not", "without", "denies", "denied"} else content_tokens):
            continue
        return True
    return False


def _tokens(value: str) -> list[str]:
    normalized = value.lower().replace("3", "three").replace("2", "two").replace("1", "one")
    return re.findall(r"[a-z]+", normalized)


def _contains_negation(tokens: list[str], content_tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if token in {"no", "not", "without", "denies", "denied"} and any(candidate in tokens[index + 1:index + 5] for candidate in content_tokens):
            return True
    return False
