from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.domain.types import Speaker, TranscriptSegmentInput
from app.models import TranscriptSegment, TranslationSegment
from app.schemas import ConsultationCreate
from app.services import consultations as service
from app.services.speaker_roles import SpeakerRoleLabeler


class Response:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"response": self.text}


def label(monkeypatch, answer: str, lines: list[str]) -> list[str]:
    monkeypatch.setattr("app.services.speaker_roles.httpx.post", lambda *args, **kwargs: Response(answer))
    return SpeakerRoleLabeler().label(lines)


def test_labels_are_read_per_line_and_bad_answers_leave_lines_unlabelled(monkeypatch) -> None:
    lines = ["What brings you in?", "I have a fever.", "Any cough?", "No."]
    assert label(monkeypatch, '{"0": "D", "1": "P", "2": "D", "3": "p"}', lines) == ["DOCTOR", "PATIENT", "DOCTOR", "PATIENT"]
    # A missing or mixed line is unknown; the others keep their labels.
    assert label(monkeypatch, '{"0": "D", "1": "M", "3": "P"}', lines) == ["DOCTOR", "UNKNOWN", "UNKNOWN", "PATIENT"]
    assert label(monkeypatch, '{"roles": ["D", "P", "D", "P"]}', lines) == ["DOCTOR", "PATIENT", "DOCTOR", "PATIENT"]
    assert label(monkeypatch, '{"roles": ["D", "P"]}', lines) == ["UNKNOWN"] * 4  # wrong length: not trusted
    assert label(monkeypatch, "not json", lines) == ["UNKNOWN"] * 4


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def test_telugu_lines_take_the_role_of_the_english_line_they_fall_under(monkeypatch) -> None:
    session = make_session()
    consultation = service.create_consultation(session, ConsultationCreate(patient_id="ROLES-1", age=30, sex="Female"))
    for index, (start, text) in enumerate((("00:00:00", "ఏం ఇబ్బంది ఉంది?"), ("00:00:03", "నాకు జ్వరం ఉంది"), ("00:00:05", "నాలుగు రోజులుగా"), ("00:00:09", "పారాసిటమాల్ వేసుకోండి"))):
        session.add(TranscriptSegment(id=f"{consultation.id}-final-{index}", consultation_id=consultation.id, speaker="UNKNOWN", text=text, timestamp=start, sequence_number=index))
    for index, (start, text) in enumerate((("00:00:00", "What is the problem?"), ("00:00:03", "I have had a fever for four days."), ("00:00:09", "Take paracetamol."))):
        session.add(TranslationSegment(id=f"{consultation.id}-en-{index}", consultation_id=consultation.id, text=text, timestamp=start, sequence_number=index))
    session.commit()
    monkeypatch.setattr(service.settings, "ai_mode", "local")
    monkeypatch.setattr("app.services.speaker_roles.httpx.post", lambda *args, **kwargs: Response('{"0": "D", "1": "P", "2": "D"}'))
    assert service._recognise_speakers(session, consultation)
    loaded = service.get_consultation(session, consultation.id)
    assert [line["speaker"] for line in loaded["translation"]] == ["DOCTOR", "PATIENT", "DOCTOR"]
    assert [line["speaker"] for line in loaded["transcript"]] == ["DOCTOR", "PATIENT", "PATIENT", "DOCTOR"]


def test_a_doctors_field_cited_only_to_the_patient_is_flagged_for_review() -> None:
    lines = [TranscriptSegmentInput(id=f"en-{index}", speaker=speaker, text="...", timestamp="00:00:00", sequence_number=index) for index, speaker in enumerate((Speaker.DOCTOR, Speaker.PATIENT, Speaker.DOCTOR))]
    needs_review: set[str] = set()
    lines.append(TranscriptSegmentInput(id="en-3", speaker=Speaker.UNKNOWN, text="...", timestamp="00:00:00", sequence_number=3))
    service._check_who_said_it(lines, {"plan": ["en-1"], "assessment": ["en-2"], "presenting_symptoms": ["en-1"], "follow_up": ["en-0", "en-1"], "vitals": ["en-1", "en-3"]}, needs_review)
    # A plan only the patient (or an unrecognised speaker) said is flagged.
    assert needs_review == {"plan", "vitals"}


def test_recognised_roles_are_hidden_from_the_note_model() -> None:
    lines = [TranscriptSegmentInput(id="en-0", speaker=Speaker.DOCTOR, text="Take paracetamol.", timestamp="00:00:00", sequence_number=0)]
    assert service._for_extraction(lines, True)[0].speaker == Speaker.UNKNOWN
    assert service._for_extraction(lines, False)[0].speaker == Speaker.DOCTOR
