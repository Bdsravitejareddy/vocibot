import math
import re

from ..domain.types import CandidateClinicalUpdate, EvidenceStatus, Speaker, TranscriptSegmentInput
from .clinical_normalization import medication_needs_review


DOCTOR_ONLY_FIELDS = {"assessment", "plan", "follow_up"}
NARRATIVE_MIN_TOKENS = 5
NARRATIVE_COVERAGE = 0.75
NEGATIONS = {"no", "not", "without", "denies", "denied", "never", "nor", "none"}
# "don't" tokenizes to "don" + "t": these stems negate the words that follow.
NEGATION_STEMS = {"don", "doesn", "didn", "haven", "hasn", "hadn", "isn", "wasn", "aren", "weren", "can", "couldn", "won"}
HEDGES = {"possible", "possibly", "probable", "probably", "likely", "maybe", "may", "might", "suspected", "query", "perhaps"}
STOPWORDS = {"a", "an", "the", "for", "of", "since", "reported", "patient", "has", "have", "had", "is", "there", "and", "or", "with", "to", "in", "on", "at", "some", "any", "very", "really"}


class EvidenceValidator:
    def validate(self, field_name: str, value: object, source_segment_ids: list[str], transcript: list[TranscriptSegmentInput], claimed_speaker: Speaker | None = None) -> CandidateClinicalUpdate:
        sources = {segment.id: segment for segment in transcript}
        segments = [sources[segment_id] for segment_id in source_segment_ids if segment_id in sources]
        if not segments or not value:
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=source_segment_ids, speaker=Speaker.UNKNOWN, status=EvidenceStatus.REJECTED)
        if field_name in DOCTOR_ONLY_FIELDS and not _attributable_to_doctor(segments, claimed_speaker):
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=source_segment_ids, speaker=Speaker.PATIENT, status=EvidenceStatus.REJECTED)
        # The chief complaint is the patient's problem, never the doctor's diagnosis.
        if field_name == "chief_complaint" and (claimed_speaker == Speaker.DOCTOR or all(segment.speaker == Speaker.DOCTOR for segment in segments)):
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=source_segment_ids, speaker=Speaker.DOCTOR, status=EvidenceStatus.REJECTED)
        speaker = segments[0].speaker if segments[0].speaker != Speaker.UNKNOWN or claimed_speaker is None else claimed_speaker
        normalized = str(value).lower()
        if field_name in {"medications", "allergies"} and medication_needs_review(value, [segment.text for segment in segments]):
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=EvidenceStatus.NEEDS_REVIEW)
        # ASR splits one spoken sentence across segments and extractors often
        # cite only part of it, so the joined evidence includes each cited
        # segment's immediate neighbours.
        texts = [segment.text for segment in segments]
        context = _with_neighbours(segments, transcript)
        if len(context) > len(segments):
            texts.append(" ".join(segment.text for segment in context))
        if isinstance(value, list):
            # Judge list items one by one: one unsupported item (e.g. a symptom
            # the patient denied) must not discard the supported ones.
            supported_items = [item for item in value if _is_semantically_supported(item, texts)]
            if not supported_items:
                return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=EvidenceStatus.REJECTED)
            value = supported_items
            normalized = str(value).lower()
        elif not _is_semantically_supported(value, texts):
            # Not grounded in what was said: never shown, so nothing is invented.
            return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=EvidenceStatus.REJECTED)
        status = EvidenceStatus.NEEDS_REVIEW if any(marker in normalized for marker in ("maybe", "may be", "possibly", "possible", "uncertain", "could be")) else EvidenceStatus.SUPPORTED
        return CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id for segment in segments], speaker=speaker, status=status)


def _is_semantically_supported(value: object, texts: list[str]) -> bool:
    values = value if isinstance(value, list) else [value]
    # A fact may be split across adjacent ASR segments: joining the evidence
    # allows phrases such as "I've had it for" + "Two weeks".  Evidence is the
    # cited segments plus their immediate neighbours, never the whole transcript.
    joint_text = " ".join(texts)
    evidence_texts = [*texts, joint_text]
    return all(_single_value_supported(str(item), evidence_texts) for item in values if item not in (None, ""))


def _with_neighbours(segments: list[TranscriptSegmentInput], transcript: list[TranscriptSegmentInput]) -> list[TranscriptSegmentInput]:
    ordered = sorted(transcript, key=lambda segment: segment.sequence_number)
    cited = {segment.id for segment in segments}
    keep = set()
    for index, segment in enumerate(ordered):
        if segment.id in cited:
            keep.update(range(max(0, index - 1), min(len(ordered), index + 2)))
    return [ordered[index] for index in sorted(keep)]


def _attributable_to_doctor(segments: list[TranscriptSegmentInput], claimed_speaker: Speaker | None) -> bool:
    """Assessment and plan must be the doctor's words.

    Without diarization every live segment is UNKNOWN; then the extractor's
    attribution is accepted unless a cited segment is labelled PATIENT.  The
    doctor reviews and approves every field before it is saved.
    """

    if any(segment.speaker == Speaker.DOCTOR for segment in segments):
        return True
    return claimed_speaker == Speaker.DOCTOR and all(segment.speaker == Speaker.UNKNOWN for segment in segments)


def _single_value_supported(value: str, texts: list[str]) -> bool:
    value_tokens = _tokens(value)
    if not value_tokens:
        return False
    value_is_negative = value_tokens[0] in NEGATIONS
    value_has_negation = any(token in NEGATIONS for token in value_tokens) or any(token in NEGATION_STEMS and next_token == "t" for token, next_token in zip(value_tokens, value_tokens[1:]))
    content_tokens = [token for token in value_tokens if token not in STOPWORDS and token not in NEGATIONS and token not in HEDGES]
    if not content_tokens:
        return False
    for text in texts:
        text_tokens = _tokens(text)
        matched = sum(1 for token in content_tokens if any(_same_word(token, candidate) for candidate in text_tokens))
        # Short facts (a symptom, a drug) must match every word.  Narrative
        # fields (history, assessment, plan) are summaries: most of their
        # substance must come from the cited words.
        required = len(content_tokens) if len(content_tokens) < NARRATIVE_MIN_TOKENS else math.ceil(NARRATIVE_COVERAGE * len(content_tokens))
        if matched < required:
            continue
        negated = _contains_negation(text_tokens, content_tokens)
        # "No fever" needs a denial in the source; "fever" must not be denied
        # there unless the value itself carries the negation ("if not settling").
        if value_is_negative and not negated:
            continue
        if negated and not value_has_negation:
            continue
        return True
    return False


def _tokens(value: str) -> list[str]:
    normalized = value.lower().replace("3", "three").replace("2", "two").replace("1", "one")
    return re.findall(r"[a-z]+", normalized)


def _same_word(left: str, right: str) -> bool:
    """Match word forms: dizzy/dizziness, nauseous/nausea, headache/headaches."""

    if left == right:
        return True
    shorter = min(len(left), len(right))
    if shorter < 4:
        return False
    prefix = 0
    for a, b in zip(left, right):
        if a != b:
            break
        prefix += 1
    return prefix >= max(4, shorter - 3)


def _contains_negation(tokens: list[str], content_tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if token in NEGATIONS or (token in NEGATION_STEMS and index + 1 < len(tokens) and tokens[index + 1] == "t"):
            window = tokens[index + 1:index + 9]
            if any(_same_word(candidate, word) for candidate in content_tokens for word in window):
                return True
    return False
