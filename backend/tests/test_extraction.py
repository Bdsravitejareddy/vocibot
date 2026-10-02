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
    result = OllamaClinicalExtractionProvider().extract(segments(("s1", Speaker.PATIENT, "I have fever.")), ClinicalRecord())

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
    result = OllamaClinicalExtractionProvider().extract(segments(("s1", Speaker.DOCTOR, "Temperature 38.6, pulse 96.")), ClinicalRecord())

    assert result.proposed_record.vitals == {"temperature": "38.6", "pulse": "96"}
    assert result.candidates[0].value == {"temperature": "38.6", "pulse": "96"}


def test_ollama_odd_candidate_shapes_do_not_sink_the_note(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": '{"candidates":[{"field_name":"chief_complaint","value":"Fever","source_segment_ids":[["s0"]],"speaker":["PATIENT","DOCTOR"],"status":"SUPPORTED"},{"field_name":"duration","value":"three days","source_segment_ids":"s0","speaker":"PATIENT","status":"SUPPORTED"}]}'}

    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", lambda *args, **kwargs: Response())
    result = OllamaClinicalExtractionProvider().extract(segments(("s1", Speaker.PATIENT, "I have had a fever for three days.")), ClinicalRecord())

    assert [(c.field_name, c.source_segment_ids, c.speaker) for c in result.candidates] == [("chief_complaint", ["s1"], Speaker.PATIENT), ("duration", ["s1"], Speaker.PATIENT)]


def test_a_recording_that_is_not_a_consultation_gets_an_empty_note(monkeypatch) -> None:
    """A travel video recorded by mistake filled chief complaint with
    "Namaste and welcome" and symptoms with "cool morning air"."""

    calls = []

    class Response:
        def __init__(self, body: dict) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self.body

    def post(url, json, **kwargs):
        calls.append(json)
        if "format" not in json:  # the yes/no consultation check
            return Response({"response": "No."})
        return Response({"response": '{"candidates": [{"field_name": "chief_complaint", "value": "Namaste and welcome", "source_segment_ids": ["s0"], "speaker": "PATIENT", "status": "SUPPORTED"}]}'})

    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", post)
    travel = segments(("x0", Speaker.UNKNOWN, "Namaste and welcome to Kashi."), ("x1", Speaker.UNKNOWN, "The cool morning air is touching the waves of the Ganges."))
    result = OllamaClinicalExtractionProvider().extract(travel, ClinicalRecord())
    assert result.candidates == [] and len(calls) == 1


def test_the_consultation_check_failing_never_loses_a_note(monkeypatch) -> None:
    import httpx

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"response": '{"candidates": [{"field_name": "chief_complaint", "value": "fever", "source_segment_ids": ["s0"], "speaker": "PATIENT", "status": "SUPPORTED"}]}'}

    def post(url, json, **kwargs):
        if "format" not in json:
            raise httpx.ConnectError("busy")
        return Response()

    monkeypatch.setattr("app.providers.ollama_extraction.httpx.post", post)
    result = OllamaClinicalExtractionProvider().extract(segments(("x0", Speaker.PATIENT, "I have a fever.")), ClinicalRecord())
    assert [candidate.value for candidate in result.candidates] == ["fever"]
