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

    # Unsupported values are rejected outright so nothing invented is shown.
    assert result.status == EvidenceStatus.REJECTED


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


def _unknown(*texts: str) -> list[TranscriptSegmentInput]:
    return [TranscriptSegmentInput(id=f"u{index}", speaker=Speaker.UNKNOWN, text=text, timestamp="00:00:00", sequence_number=index) for index, text in enumerate(texts)]


def test_symptom_word_forms_match_what_the_patient_said() -> None:
    segments = _unknown("It feels really dizzy and sometimes I feel sick and nauseous.", "Yeah, I've had a couple of headaches, like really bad ones.")

    result = EvidenceValidator().validate("presenting_symptoms", ["dizziness", "nausea", "headache"], ["u0", "u1"], segments)

    assert result.status == EvidenceStatus.SUPPORTED
    assert result.value == ["dizziness", "nausea", "headache"]


def test_list_items_are_judged_one_by_one() -> None:
    segments = _unknown("It feels really dizzy and sometimes I feel sick and nauseous.", "No, I haven't been sick. I just feel nauseous.")

    result = EvidenceValidator().validate("presenting_symptoms", ["dizziness", "vomiting"], ["u0", "u1"], segments)

    assert result.status == EvidenceStatus.SUPPORTED
    assert result.value == ["dizziness"]


def test_contracted_negations_support_relevant_negatives() -> None:
    segments = _unknown("I mean, I get the odd cough but I don't think it's like a fever.")

    assert EvidenceValidator().validate("relevant_negatives", ["no fever"], ["u0"], segments).status == EvidenceStatus.SUPPORTED
    assert EvidenceValidator().validate("presenting_symptoms", ["fever"], ["u0"], segments).status == EvidenceStatus.REJECTED


def test_doctor_fields_accept_extractor_attribution_only_without_patient_labels() -> None:
    unknown = _unknown("From what you're describing it sounds absolutely like an inner ear disturbance.")
    patient = [TranscriptSegmentInput(id="p0", speaker=Speaker.PATIENT, text=unknown[0].text, timestamp="00:00:00", sequence_number=0)]
    validator = EvidenceValidator()

    assert validator.validate("assessment", "inner ear disturbance", ["u0"], unknown, claimed_speaker=Speaker.DOCTOR).status == EvidenceStatus.SUPPORTED
    assert validator.validate("assessment", "inner ear disturbance", ["u0"], unknown, claimed_speaker=Speaker.PATIENT).status == EvidenceStatus.REJECTED
    assert validator.validate("assessment", "inner ear disturbance", ["p0"], patient, claimed_speaker=Speaker.DOCTOR).status == EvidenceStatus.REJECTED


def test_narrative_plan_is_grounded_by_most_of_its_words_but_inventions_are_rejected() -> None:
    segments = _unknown("What we could try would be some regular stemetil.", "If things aren't settling then it would be reasonable to seek the ENT opinion, I can do a referral letter.")
    validator = EvidenceValidator()

    plan = validator.validate("plan", "regular stemetil; ENT referral letter if not settling", ["u0", "u1"], segments, claimed_speaker=Speaker.DOCTOR)
    invented = validator.validate("follow_up", "follow up with patient in a week", ["u1"], segments, claimed_speaker=Speaker.DOCTOR)

    assert plan.status == EvidenceStatus.SUPPORTED
    assert invented.status == EvidenceStatus.REJECTED


def test_chief_complaint_cannot_be_the_doctors_diagnosis() -> None:
    segments = _unknown("This looks like a viral upper respiratory infection.")

    result = EvidenceValidator().validate("chief_complaint", "viral upper respiratory infection", ["u0"], segments, claimed_speaker=Speaker.DOCTOR)

    assert result.status == EvidenceStatus.REJECTED


def test_a_negation_stops_at_the_end_of_its_clause() -> None:
    segments = _unknown("No chest pain, but I feel very tired.", "No, I haven't been sick. I just feel nauseous.")
    validator = EvidenceValidator()

    assert validator.validate("presenting_symptoms", ["very tired"], ["u0"], segments).status == EvidenceStatus.SUPPORTED
    assert validator.validate("relevant_negatives", ["no chest pain"], ["u0"], segments).status == EvidenceStatus.SUPPORTED
    assert validator.validate("presenting_symptoms", ["nauseous"], ["u1"], segments).status == EvidenceStatus.SUPPORTED
    assert validator.validate("presenting_symptoms", ["sick"], ["u1"], segments).status == EvidenceStatus.REJECTED
    assert validator.validate("relevant_negatives", ["no tingling or numbness"], ["u0"], _unknown("No tingling or numbness in my feet.")).status == EvidenceStatus.SUPPORTED
