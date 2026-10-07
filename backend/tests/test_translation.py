import numpy as np

from app.domain.types import CandidateClinicalUpdate, ClinicalRecord, EvidenceStatus, ExtractionResult, Speaker
from app.providers.reconciliation import FinalReconciler, split_at_pauses
from app.providers.speech import AudioChunk, MlxWhisperProvider, TranscriptDraft
from app.schemas import ConsultationCreate
from app.services.consultations import create_consultation, delete_consultation, extract_reconciled_clinical_record, get_consultation, replace_with_reconciled_transcript
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def speech_with_pauses(seconds: int) -> np.ndarray:
    t = np.arange(seconds * 16_000) / 16_000
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    tone[(t % 10) > 9.5] = 0.0
    return tone


class MixedSTT:
    """First piece Telugu, second English; records what was translated."""

    def __init__(self):
        self.translated = []

    def transcribe_chunk(self, chunk, language=None):
        telugu = chunk.timestamp_ms == 0
        return [TranscriptDraft(text="నాకు జ్వరం ఉంది" if telugu else "The temperature is 101.", timestamp="", start_ms=chunk.timestamp_ms, end_ms=chunk.timestamp_ms + 2_000, language_code="te" if telugu else "en")]

    def translate_chunk(self, chunk, language):
        self.translated.append((chunk.timestamp_ms, language))
        return [TranscriptDraft(text="I have a fever.", timestamp="", start_ms=chunk.timestamp_ms, end_ms=chunk.timestamp_ms + 2_000, language_code="en")]


def test_mixed_language_consultations_are_handled_piece_by_piece(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "final_piece_seconds", 28.0)  # written for 28 s pieces
    stt = MixedSTT()
    result = FinalReconciler().run(speech_with_pauses(55), stt, sample_rate=16_000)

    assert [draft.language_code for draft in result.transcripts] == ["te", "en"]
    assert len(stt.translated) == 1 and stt.translated[0][1] == "te"  # only the Telugu piece is translated
    assert [draft.text for draft in result.translations] == ["I have a fever.", "The temperature is 101."]


def test_english_consultations_get_no_translation() -> None:
    class EnglishSTT(MixedSTT):
        def transcribe_chunk(self, chunk, language=None):
            return [TranscriptDraft(text="I have a cough.", timestamp="", start_ms=chunk.timestamp_ms, end_ms=chunk.timestamp_ms + 1_000, language_code="en")]

    stt = EnglishSTT()
    assert FinalReconciler().run(speech_with_pauses(40), stt, sample_rate=16_000).translations == []
    assert stt.translated == []


def test_translation_drops_repetition_loops_and_low_confidence_lines() -> None:
    looped = {"segments": [{"start": 2.0 * i, "end": 2.0 * i + 2, "text": " I have been suffering from pain in my body for the past 4 days.", "avg_logprob": -0.3, "compression_ratio": 1.4, "no_speech_prob": 0.01} for i in range(12)]
              + [{"start": 30.0, "end": 32.0, "text": " The temperature is 101 degrees.", "avg_logprob": -0.2, "compression_ratio": 1.2, "no_speech_prob": 0.01},
                 {"start": 32.0, "end": 34.0, "text": " doctor doctor doctor doctor doctor doctor", "avg_logprob": -0.4, "compression_ratio": 3.1, "no_speech_prob": 0.02},
                 {"start": 34.0, "end": 36.0, "text": " Thank you for watching.", "avg_logprob": -1.4, "compression_ratio": 1.0, "no_speech_prob": 0.9}]}
    calls = []
    provider = MlxWhisperProvider(model="turbo", translation_model="large-v3", transcribe=lambda audio, **options: calls.append(options) or looped)

    drafts = provider.translate_chunk(AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=60_000, waveform=np.zeros(16_000, dtype=np.float32)), "te")

    assert [draft.text for draft in drafts] == ["I have been suffering from pain in my body for the past 4 days.", "The temperature is 101 degrees."]
    assert drafts[1].start_ms == 90_000 and drafts[1].timestamp == "00:01:30"
    assert calls[0]["task"] == "translate" and calls[0]["language"] == "te" and calls[0]["path_or_hf_repo"] == "large-v3"


def test_the_note_is_written_from_the_english_translation(monkeypatch) -> None:
    session = make_session()
    consultation = create_consultation(session, ConsultationCreate(patient_id="TE-1", age=22, sex="Female"))
    replace_with_reconciled_transcript(
        session, consultation.id,
        [TranscriptDraft(text="నిన్న రాత్రి నుంచి జ్వరం ఉంది", timestamp="00:00:00", start_ms=0, end_ms=2_000, language_code="te")],
        extract=False,
        translations=[TranscriptDraft(text="I have had a fever since last night.", timestamp="00:00:00", start_ms=0, end_ms=2_000, language_code="en")],
    )
    seen = []

    class Extractor:
        def extract(self, transcript, current):
            seen.append([segment.text for segment in transcript])
            return ExtractionResult(proposed_record=ClinicalRecord(), candidates=[CandidateClinicalUpdate(field_name="presenting_symptoms", value=["fever"], source_segment_ids=[transcript[0].id], speaker=Speaker.PATIENT, status=EvidenceStatus.SUPPORTED)])

    monkeypatch.setattr("app.services.consultations.build_extraction_provider", lambda _settings: Extractor())
    loaded = extract_reconciled_clinical_record(session, consultation.id, require_authoritative=True)

    assert seen == [["I have had a fever since last night."]]
    assert loaded["record"]["presenting_symptoms"] == ["fever"]
    assert loaded["updates"][0]["source_segment_ids"] == [f"{consultation.id}-en-0"]
    assert loaded["transcript"][0]["text"] == "నిన్న రాత్రి నుంచి జ్వరం ఉంది"  # the record keeps the original
    assert [item["text"] for item in loaded["translation"]] == ["I have had a fever since last night."]

    delete_consultation(session, consultation.id)
    from app.models import TranslationSegment
    assert session.query(TranslationSegment).count() == 0


def test_pieces_cover_the_whole_recording() -> None:
    audio = speech_with_pauses(95)
    spans = split_at_pauses(audio, 16_000, 28)
    assert spans[0][0] == 0 and spans[-1][1] == len(audio) and all(a < b for a, b in spans)


def test_dense_scripts_are_transcribed_in_short_pieces_so_whisper_does_not_overflow(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "final_piece_seconds", 28.0)  # written for 28 s pieces
    """28 s of Telugu overflowed Whisper's 224-token window: it stopped
    mid-letter and skipped the rest (a 15 s gap)."""

    class DetectingSTT:
        def __init__(self, language):
            self.language, self.chunks, self.detections = language, [], 0

        def detect_piece_language(self, audio):
            self.detections += 1
            return self.language, 0.95

        def transcribe_chunk(self, chunk, language=None):
            self.chunks.append((len(chunk.waveform) / 16_000, language))
            return [TranscriptDraft(text="పదం" if language == "te" else "word", timestamp="", start_ms=chunk.timestamp_ms, end_ms=chunk.timestamp_ms + 1_000, language_code=language)]

        def translate_chunk(self, chunk, language):
            return []

    telugu = DetectingSTT("te")
    FinalReconciler().run(speech_with_pauses(28), telugu, sample_rate=16_000)
    assert telugu.detections == 1
    assert len(telugu.chunks) == 3 and all(seconds <= 12.5 and language == "te" for seconds, language in telugu.chunks)

    english = DetectingSTT("en")
    FinalReconciler().run(speech_with_pauses(28), english, sample_rate=16_000)
    assert english.chunks == [(28.0, "en")]


def test_processing_during_the_consultation_cuts_the_same_pieces_as_after_stop() -> None:
    from app.providers.reconciliation import IncrementalReconciler

    class Recorder:
        def __init__(self) -> None:
            self.spans = []

        def transcribe_chunk(self, chunk, language=None):
            self.spans.append((chunk.timestamp_ms, chunk.timestamp_ms + int(len(chunk.waveform) / 16)))
            return [TranscriptDraft(text="I have a cough.", timestamp="", start_ms=chunk.timestamp_ms, end_ms=chunk.timestamp_ms + 500, language_code="en")]

    rng = np.random.default_rng(3)
    audio = (speech_with_pauses(130) * (0.5 + rng.random(130 * 16_000))).astype(np.float32)
    after_stop = Recorder()
    expected = FinalReconciler().run(audio, after_stop, sample_rate=16_000)

    live = Recorder()
    incremental = IncrementalReconciler(live, sample_rate=16_000)
    done_during = 0
    for end in range(0, len(audio), 3 * 16_000):  # audio arrives 3 s at a time
        done_during += incremental.advance(audio[:end])
    assert done_during >= 2  # most pieces were done before Stop
    result = incremental.finish(audio)
    assert live.spans == after_stop.spans
    assert [(draft.start_ms, draft.text) for draft in result.transcripts] == [(draft.start_ms, draft.text) for draft in expected.transcripts]
