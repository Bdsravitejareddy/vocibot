from app.domain.types import ClinicalRecord, EvidenceStatus, Speaker, TranscriptSegmentInput
from app.providers.demo_extraction import DemoClinicalExtractionProvider
from app.providers.ollama_extraction import OllamaClinicalExtractionProvider
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


def test_ollama_malformed_candidate_metadata_is_sanitized(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"proposed_record":{"presenting_symptoms":"patient"},"candidates":[{"field_name":"chief_complaint","value":"Fever","source_segment_ids":["s1"],"speaker":"","status":"SUPPORTED"}]}' }

    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", lambda *args, **kwargs: Response())
    result = OllamaClinicalExtractionProvider().extract(segments(("s1", Speaker.PATIENT, "Doctor, I have fever.")), ClinicalRecord())

    assert result.proposed_record.presenting_symptoms == []
    assert result.candidates[0].speaker == Speaker.UNKNOWN


def test_ollama_prompt_does_not_seed_unrelated_clinical_facts() -> None:
    prompt = OllamaClinicalExtractionProvider._prompt(
        segments(("s1", Speaker.PATIENT, "I have a cough and cold for two weeks.")),
        ClinicalRecord(),
    )

    assert "Fever" not in prompt
    assert "Paracetamol" not in prompt


def test_ollama_numeric_vitals_are_kept_as_text(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"proposed_record":{"vitals":{"temperature":38.6,"pulse":96}},"candidates":[{"field_name":"vitals","value":{"temperature":38.6,"pulse":96},"source_segment_ids":["s1"],"speaker":"DOCTOR","status":"SUPPORTED"}]}'}

    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", lambda *args, **kwargs: Response())
    result = OllamaClinicalExtractionProvider().extract(segments(("s1", Speaker.DOCTOR, "Temperature 38.6, pulse 96, oxygen saturation normal.")), ClinicalRecord())

    assert result.proposed_record.vitals == {"temperature": "38.6", "pulse": "96"}
    assert result.candidates[0].value == {"temperature": "38.6", "pulse": "96"}


def test_ollama_odd_candidate_shapes_do_not_sink_the_note(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"candidates":[{"field_name":"chief_complaint","value":"Fever","source_segment_ids":[["s0"]],"speaker":["PATIENT","DOCTOR"],"status":"SUPPORTED"},{"field_name":"duration","value":"three days","source_segment_ids":"s0","speaker":"PATIENT","status":"SUPPORTED"}]}'}

    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", lambda *args, **kwargs: Response())
    result = OllamaClinicalExtractionProvider().extract(segments(("s1", Speaker.PATIENT, "Doctor, I have had a fever for three days.")), ClinicalRecord())

    assert [(c.field_name, c.source_segment_ids, c.speaker) for c in result.candidates] == [("chief_complaint", ["s1"], Speaker.PATIENT), ("duration", ["s1"], Speaker.PATIENT)]



def test_a_recording_that_is_not_a_consultation_gets_an_empty_note(monkeypatch) -> None:
    """A travel video recorded by mistake filled chief complaint with
    "Namaste and welcome" and symptoms with "cool morning air"."""

    calls = []
    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", lambda *args, **kwargs: calls.append(1))
    travel = segments(
        ("x0", Speaker.UNKNOWN, "Namaste and welcome to Kashi."),
        ("x1", Speaker.UNKNOWN, "The cool morning air is touching the waves of the Ganges."),
        ("x2", Speaker.UNKNOWN, "A stream of time flowing without stopping, without getting tired."),
    )
    result = OllamaClinicalExtractionProvider().extract(travel, ClinicalRecord())
    assert result.candidates == [] and calls == []


def test_health_vocabulary_decides_whether_a_note_is_attempted() -> None:
    from app.providers.ollama_extraction import mentions_health

    # Test17: the note model, asked "is this a consultation?", answered "No."
    assert mentions_health(["Hi Doctor, how are you?", "My name is Ravi.", "I have a severe headache.", "It has been going on for about 10 days."])
    assert mentions_health(["Hi doctor, I have fever."])
    assert mentions_health(["I have a fever", "and I feel tired and weak"])  # one clinical, two everyday
    assert not mentions_health(["we keep bleeding money on idle clusters", "load tests"])  # one clinical, one everyday
    assert not mentions_health(["this sacred city teaches us patience"])
    assert mentions_health(["నాకు బాగా జ్వరంగా ఉంది"])  # not translated: cannot tell, so try
    assert not mentions_health(["Good morning everyone and a warm welcome to the annual Cloud Engineering Summit."])
    assert not mentions_health(["Can you hear me? Hello? Hello?"])
    assert not mentions_health(["flowing without stopping, without getting tired"])  # one everyday word


def test_a_medication_must_name_a_drug() -> None:
    assert OllamaClinicalExtractionProvider._coerce("medications", ["medicine", "medicine meds", "some tablets for stomach pain", "Dolo 650", "paracetamol 500 mg", "650"]) == ["Dolo 650", "paracetamol 500 mg", "650"]
