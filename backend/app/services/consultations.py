from datetime import datetime, timezone
import logging
from pathlib import Path
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.types import ClinicalRecord, ConsultationStatus, EvidenceStatus, RecordUpdateType, Speaker, TranscriptSegmentInput
from ..models import ClinicalRecord as ClinicalRecordModel
from ..models import Consultation, Patient, Recording, RecordUpdate, TranscriptSegment
from ..config import settings
from ..providers.factory import build_extraction_provider
from ..providers.speech import TranscriptDraft
from ..schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from .evidence import EvidenceValidator
from .record_diff import diff_clinical_record


_RELATIVE_TIMESTAMP = re.compile(r"^(\d{2,}:)?\d{2}:\d{2}$")
logger = logging.getLogger(__name__)


def _extract_or_leave_reviewable(transcript_inputs: list[TranscriptSegmentInput], current: ClinicalRecord, warnings: list[str] | None = None):
    try:
        return build_extraction_provider(settings).extract(transcript_inputs, current)  # type: ignore[arg-type]
    except Exception:
        logger.exception("Local clinical extraction failed; preserving transcript for clinician review")
        if warnings is not None:
            warnings.append("Clinical note inference did not finish. The final transcript is available for manual review.")
        return None


class ConsultationStateError(ValueError):
    """The consultation exists but is not in a state that allows the action."""


def _apply_validated_candidates(result, current: ClinicalRecord, transcript_inputs: list[TranscriptSegmentInput]) -> tuple[ClinicalRecord, dict[str, list[str]], set[str]]:
    """Apply evidence-checked candidates to the record.

    SUPPORTED values fill their field.  NEEDS_REVIEW values are grounded in the
    transcript but hedged or ambiguous; they fill the field flagged for review
    unless a SUPPORTED value exists.  REJECTED values never reach the record.
    """

    validator = EvidenceValidator()
    validated_record = current.model_copy(deep=True)
    evidence: dict[str, list[str]] = {}
    needs_review: set[str] = set()
    supported_fields: set[str] = set()
    for candidate in result.candidates if result is not None else []:
        validated = validator.validate(candidate.field_name, candidate.value, candidate.source_segment_ids, transcript_inputs, claimed_speaker=candidate.speaker)  # type: ignore[arg-type]
        if validated.status not in {EvidenceStatus.SUPPORTED, EvidenceStatus.NEEDS_REVIEW} or not hasattr(validated_record, candidate.field_name):
            continue
        if validated.status == EvidenceStatus.NEEDS_REVIEW and candidate.field_name in supported_fields:
            continue
        data = validated_record.model_dump()
        data[candidate.field_name] = validated.value
        try:
            validated_record = ClinicalRecord.model_validate(data)
        except Exception:
            continue
        evidence[candidate.field_name] = validated.source_segment_ids
        if validated.status == EvidenceStatus.SUPPORTED:
            supported_fields.add(candidate.field_name)
            needs_review.discard(candidate.field_name)
        else:
            needs_review.add(candidate.field_name)
    return validated_record, evidence, needs_review


def _ai_update_type(field_name: str, needs_review: set[str]) -> str:
    return (RecordUpdateType.AI_NEEDS_REVIEW if field_name in needs_review else RecordUpdateType.AI_EXTRACTED).value


def _relative_timestamp(value: str, consultation_started_at: datetime) -> str:
    """Normalize incoming transcript time to consultation-relative HH:MM:SS."""

    if _RELATIVE_TIMESTAMP.match(value):
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 2:
            total_seconds = parts[0] * 60 + parts[1]
        else:
            total_seconds = parts[-3] * 3600 + parts[-2] * 60 + parts[-1]
        if total_seconds < 0:
            raise ValueError("transcript timestamp cannot be negative")
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("transcript timestamp must be consultation-relative HH:MM:SS") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    started = consultation_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = max(0, int((parsed - started).total_seconds()))
    hours, remainder = divmod(elapsed, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def create_consultation(session: Session, payload: ConsultationCreate, *, owner_id: str | None = None) -> Consultation:
    # Patients belong to one clinician: the same identifier under another
    # clinician is a different, invisible patient record.
    patient = session.scalar(select(Patient).where(Patient.patient_identifier == payload.patient_id, Patient.owner_id.is_(None) if owner_id is None else Patient.owner_id == owner_id))
    if patient is None:
        patient = Patient(owner_id=owner_id, patient_identifier=payload.patient_id, name=payload.patient_name, age=payload.age, sex=payload.sex)
        session.add(patient)
        session.flush()
    else:
        patient.name = payload.patient_name or patient.name
        patient.age = payload.age
        patient.sex = payload.sex
    consultation = Consultation(owner_id=owner_id, patient_id=patient.id, status=ConsultationStatus.IN_PROGRESS.value)
    session.add(consultation)
    session.flush()
    session.add(ClinicalRecordModel(consultation_id=consultation.id, structured_data_json=ClinicalRecord().model_dump(), version=1))
    session.commit()
    session.refresh(consultation)
    return consultation


def _find_consultation(session: Session, consultation_id: str) -> Consultation:
    consultation = session.get(Consultation, consultation_id)
    if consultation is None:
        raise ValueError("consultation not found")
    return consultation


def append_segment(session: Session, consultation_id: str, payload: SegmentCreate) -> dict:
    consultation = _find_consultation(session, consultation_id)
    if payload.id.startswith(f"{consultation.id}-final-"):
        raise ValueError("transcript segment id uses a server-reserved finalization prefix")
    existing = session.get(TranscriptSegment, payload.id)
    if existing is not None and existing.consultation_id == consultation.id:
        return {"duplicate": True, "consultation": get_consultation(session, consultation_id)}
    if consultation.status != ConsultationStatus.IN_PROGRESS.value:
        raise ValueError("consultation is not in progress")
    segment = TranscriptSegment(id=payload.id, consultation_id=consultation.id, speaker=payload.speaker.value, text=payload.text, language_code=payload.language_code, timestamp=_relative_timestamp(payload.timestamp, consultation.started_at), sequence_number=payload.sequence_number)
    session.add(segment)
    session.flush()
    # Rolling-window ASR is intentionally low latency and may contain partial
    # words. Persist it for the live transcript, but never let it populate the
    # clinical record. The authoritative full-recording pass replaces these
    # fragments and performs extraction once when recording stops.
    if payload.provisional:
        session.commit()
        return {"duplicate": False, "consultation": get_consultation(session, consultation_id)}
    transcript = list(session.scalars(select(TranscriptSegment).where(TranscriptSegment.consultation_id == consultation.id).order_by(TranscriptSegment.sequence_number)))
    transcript_inputs = [TranscriptSegmentInput(
        id=item.id, speaker=item.speaker, text=item.text, timestamp=item.timestamp, sequence_number=item.sequence_number, language_code=item.language_code
    ) for item in transcript]
    current = ClinicalRecord.model_validate(consultation.clinical_record.structured_data_json)
    result = _extract_or_leave_reviewable(transcript_inputs, current)
    validated_record, evidence, needs_review = _apply_validated_candidates(result, current, transcript_inputs)
    doctor_edited_fields = {update.field_name for update in consultation.updates if update.update_type == RecordUpdateType.DOCTOR_EDITED.value}
    changes = diff_clinical_record(current, validated_record, evidence, doctor_edited_fields)
    for change in changes:
        session.add(RecordUpdate(consultation_id=consultation.id, field_name=change.field_name, previous_value=change.previous_value, new_value=change.new_value, source_transcript_segment_ids=change.source_segment_ids, update_type=_ai_update_type(change.field_name, needs_review)))
    if changes:
        record_data = current.model_dump()
        for change in changes:
            record_data[change.field_name] = change.new_value
        consultation.clinical_record.structured_data_json = record_data
        consultation.clinical_record.version += 1
    session.commit()
    return {"duplicate": False, "consultation": get_consultation(session, consultation_id)}


def replace_with_reconciled_transcript(
    session: Session,
    consultation_id: str,
    drafts: list[TranscriptDraft],
    *,
    warnings: list[str] | None = None,
    extract: bool = True,
) -> dict:
    """Commit the authoritative ASR transcript before optional note extraction."""

    consultation = _find_consultation(session, consultation_id)
    if consultation.status != ConsultationStatus.IN_PROGRESS.value:
        return get_consultation(session, consultation_id)
    for item in list(consultation.transcript_segments):
        session.delete(item)
    for update in list(consultation.updates):
        if update.update_type == RecordUpdateType.AI_EXTRACTED.value:
            session.delete(update)
    consultation.clinical_record.structured_data_json = ClinicalRecord().model_dump()
    consultation.clinical_record.version += 1
    session.flush()
    for index, draft in enumerate(drafts):
        speaker = draft.speaker if draft.speaker in {Speaker.DOCTOR.value, Speaker.PATIENT.value, Speaker.UNKNOWN.value} else Speaker.UNKNOWN.value
        session.add(TranscriptSegment(
            id=f"{consultation.id}-final-{index}",
            consultation_id=consultation.id,
            speaker=speaker,
            text=draft.text,
            language_code=draft.language_code,
            timestamp=draft.timestamp,
            sequence_number=index,
        ))
    session.commit()
    if not extract:
        return get_consultation(session, consultation_id)
    return extract_reconciled_clinical_record(session, consultation_id, warnings=warnings)


def extract_reconciled_clinical_record(
    session: Session,
    consultation_id: str,
    *,
    warnings: list[str] | None = None,
    require_authoritative: bool = False,
) -> dict:
    """Extract a note from the already-committed authoritative transcript."""

    consultation = _find_consultation(session, consultation_id)
    transcript_rows = session.scalars(select(TranscriptSegment).where(TranscriptSegment.consultation_id == consultation.id).order_by(TranscriptSegment.sequence_number)).all()
    authoritative_prefix = f"{consultation.id}-final-"
    if require_authoritative and (not transcript_rows or any(not item.id.startswith(authoritative_prefix) for item in transcript_rows)):
        if warnings is not None:
            warnings.append("Clinical note inference was skipped because no authoritative final transcript was available.")
        return get_consultation(session, consultation_id)
    transcript_inputs = [TranscriptSegmentInput(id=item.id, speaker=item.speaker, text=item.text, timestamp=item.timestamp, sequence_number=item.sequence_number, language_code=item.language_code) for item in transcript_rows]
    current = ClinicalRecord()
    result = _extract_or_leave_reviewable(transcript_inputs, current, warnings)
    validated_record, evidence, needs_review = _apply_validated_candidates(result, current, transcript_inputs)
    changes = diff_clinical_record(current, validated_record, evidence, set())
    for change in changes:
        session.add(RecordUpdate(consultation_id=consultation.id, field_name=change.field_name, previous_value=change.previous_value, new_value=change.new_value, source_transcript_segment_ids=change.source_segment_ids, update_type=_ai_update_type(change.field_name, needs_review)))
    if changes:
        consultation.clinical_record.structured_data_json = validated_record.model_dump()
        consultation.clinical_record.version += 1
    session.commit()
    return get_consultation(session, consultation_id)


def reanalyse_consultation(session: Session, consultation_id: str, *, warnings: list[str]) -> dict:
    """Regenerate the AI-filled note of a finished consultation from its transcript.

    Fields the doctor edited are kept.  AI-filled fields are replaced by the
    new analysis, including being cleared when no longer supported.  An
    approved consultation returns to review because its note has changed.
    """

    consultation = _find_consultation(session, consultation_id)
    if consultation.status == ConsultationStatus.IN_PROGRESS.value:
        raise ConsultationStateError("stop the consultation before re-analysing its note")
    transcript_rows = session.scalars(select(TranscriptSegment).where(TranscriptSegment.consultation_id == consultation.id).order_by(TranscriptSegment.sequence_number)).all()
    if not transcript_rows:
        raise ConsultationStateError("this consultation has no transcript to analyse")
    transcript_inputs = [TranscriptSegmentInput(id=item.id, speaker=item.speaker, text=item.text, timestamp=item.timestamp, sequence_number=item.sequence_number, language_code=item.language_code) for item in transcript_rows]
    result = _extract_or_leave_reviewable(transcript_inputs, ClinicalRecord(), warnings)
    if result is None:
        # Extraction failed: leave the existing note exactly as it was.
        return get_consultation(session, consultation_id)
    analysed, evidence, needs_review = _apply_validated_candidates(result, ClinicalRecord(), transcript_inputs)
    current = ClinicalRecord.model_validate(consultation.clinical_record.structured_data_json)
    doctor_edited_fields = {update.field_name for update in consultation.updates if update.update_type == RecordUpdateType.DOCTOR_EDITED.value}
    refreshed = analysed.model_dump()
    for field_name in doctor_edited_fields & set(refreshed):
        refreshed[field_name] = getattr(current, field_name)
    previous = current.model_dump()
    changed = [field_name for field_name in refreshed if refreshed[field_name] != previous[field_name]]
    for field_name in changed:
        session.add(RecordUpdate(consultation_id=consultation.id, field_name=field_name, previous_value=previous[field_name], new_value=refreshed[field_name], source_transcript_segment_ids=evidence.get(field_name, []), update_type=_ai_update_type(field_name, needs_review)))
    if changed:
        consultation.clinical_record.structured_data_json = refreshed
        consultation.clinical_record.version += 1
        if consultation.status == ConsultationStatus.APPROVED.value:
            session.add(RecordUpdate(consultation_id=consultation.id, field_name="__approval__", previous_value=ConsultationStatus.APPROVED.value, new_value=ConsultationStatus.READY_FOR_REVIEW.value, source_transcript_segment_ids=[], update_type=RecordUpdateType.REOPENED_FOR_REVIEW.value))
            consultation.status = ConsultationStatus.READY_FOR_REVIEW.value
    else:
        warnings.append("Re-analysis found no changes to the note.")
    session.commit()
    return get_consultation(session, consultation_id)


def retranscribe_consultation(session: Session, consultation_id: str, transcribe, *, warnings: list[str]) -> dict:
    """Re-transcribe a finished consultation from its stored audio, then refill the note.

    ``transcribe(waveform, sample_rate, language)`` returns transcript drafts.
    Each recording's SHA-256 is verified first: altered audio is never used.
    """

    from .recordings import file_sha256, read_audio

    consultation = _find_consultation(session, consultation_id)
    if consultation.status == ConsultationStatus.IN_PROGRESS.value:
        raise ConsultationStateError("stop the consultation before re-transcribing it")
    if not consultation.recordings:
        raise ConsultationStateError("this consultation has no stored audio")
    drafts: list[TranscriptDraft] = []
    offset_ms = 0
    for recording in consultation.recordings:
        path = Path(recording.file_path)
        if not path.is_file():
            raise ConsultationStateError(f"recording {path.name} is missing")
        if recording.sha256 and file_sha256(path) != recording.sha256:
            raise ConsultationStateError(f"recording {path.name} does not match its stored fingerprint; it may have been altered")
        waveform, sample_rate = read_audio(path)
        for draft in transcribe(waveform, sample_rate, recording.language_code):
            start = (draft.start_ms or 0) + offset_ms
            end = (draft.end_ms or draft.start_ms or 0) + offset_ms
            drafts.append(TranscriptDraft(text=draft.text, timestamp=_format_offset(start), speaker=draft.speaker, start_ms=start, end_ms=end, language_code=draft.language_code))
        offset_ms += int(len(waveform) / sample_rate * 1000)
    if not drafts:
        raise ConsultationStateError("no speech was recognised in the stored audio")
    for item in list(consultation.transcript_segments):
        session.delete(item)
    session.flush()
    for index, draft in enumerate(drafts):
        session.add(TranscriptSegment(id=f"{consultation.id}-final-{index}", consultation_id=consultation.id, speaker=draft.speaker if draft.speaker in {Speaker.DOCTOR.value, Speaker.PATIENT.value} else Speaker.UNKNOWN.value, text=draft.text, language_code=draft.language_code, timestamp=draft.timestamp, sequence_number=index))
    if consultation.status == ConsultationStatus.APPROVED.value:
        # The approved note was based on the old transcript.
        session.add(RecordUpdate(consultation_id=consultation.id, field_name="__approval__", previous_value=ConsultationStatus.APPROVED.value, new_value=ConsultationStatus.READY_FOR_REVIEW.value, source_transcript_segment_ids=[], update_type=RecordUpdateType.REOPENED_FOR_REVIEW.value))
        consultation.status = ConsultationStatus.READY_FOR_REVIEW.value
    session.commit()
    session.expire(consultation, ["transcript_segments"])
    return reanalyse_consultation(session, consultation_id, warnings=warnings)


def _format_offset(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def stop_consultation(session: Session, consultation_id: str) -> Consultation:
    consultation = _find_consultation(session, consultation_id)
    if consultation.status != ConsultationStatus.IN_PROGRESS.value:
        return consultation
    consultation.status = ConsultationStatus.READY_FOR_REVIEW.value
    consultation.ended_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(consultation)
    return consultation


def delete_consultation(session: Session, consultation_id: str) -> None:
    """Permanently discard a consultation: transcript, record and audit trail.

    The patient is removed too when no other consultation refers to them.
    """

    consultation = _find_consultation(session, consultation_id)
    patient = consultation.patient
    recording_files = [Path(recording.file_path) for recording in consultation.recordings]
    session.delete(consultation)
    session.flush()
    remaining = session.scalars(select(Consultation.id).where(Consultation.patient_id == patient.id).limit(1)).first()
    if remaining is None:
        session.delete(patient)
    session.commit()
    for path in recording_files:
        path.unlink(missing_ok=True)


def approve_consultation(session: Session, consultation_id: str, payload: ApproveRequest, *, actor_id: str | None = None) -> Consultation:
    consultation = _find_consultation(session, consultation_id)
    if consultation.status != ConsultationStatus.READY_FOR_REVIEW.value:
        raise ValueError("consultation must be ready for review before approval")
    current = ClinicalRecord.model_validate(consultation.clinical_record.structured_data_json)
    doctor_changes = diff_clinical_record(current, payload.record, {field: [] for field in payload.record.model_dump()}, set())
    for change in doctor_changes:
        session.add(RecordUpdate(consultation_id=consultation.id, field_name=change.field_name, previous_value=change.previous_value, new_value=change.new_value, source_transcript_segment_ids=[], update_type=RecordUpdateType.DOCTOR_EDITED.value, actor_user_id=actor_id))
    consultation.clinical_record.structured_data_json = payload.record.model_dump()
    consultation.clinical_record.version += 1
    session.add(RecordUpdate(consultation_id=consultation.id, field_name="__approval__", previous_value=ConsultationStatus.READY_FOR_REVIEW.value, new_value=ConsultationStatus.APPROVED.value, source_transcript_segment_ids=[], update_type=RecordUpdateType.DOCTOR_APPROVED.value, actor_user_id=actor_id))
    consultation.status = ConsultationStatus.APPROVED.value
    session.commit()
    session.refresh(consultation)
    return consultation


def get_consultation(session: Session, consultation_id: str) -> dict:
    consultation = _find_consultation(session, consultation_id)
    record = consultation.clinical_record.structured_data_json if consultation.clinical_record else ClinicalRecord().model_dump()
    transcript_rows = session.scalars(select(TranscriptSegment).where(TranscriptSegment.consultation_id == consultation.id).order_by(TranscriptSegment.sequence_number)).all()
    update_rows = session.scalars(select(RecordUpdate).where(RecordUpdate.consultation_id == consultation.id).order_by(RecordUpdate.updated_at)).all()
    return {
        "id": consultation.id,
        "session_code": consultation.session_code,
        "status": consultation.status,
        "started_at": consultation.started_at.isoformat(),
        "ended_at": consultation.ended_at.isoformat() if consultation.ended_at else None,
        "patient": {"id": consultation.patient.id, "patient_identifier": consultation.patient.patient_identifier, "name": consultation.patient.name, "age": consultation.patient.age, "sex": consultation.patient.sex},
        "recordings": [{"id": item.id, "started_at": item.started_at.isoformat(), "duration_ms": item.duration_ms, "sample_rate": item.sample_rate, "language_code": item.language_code, "sha256": item.sha256, "original_sha256": item.original_sha256, "format": item.format, "size_bytes": item.size_bytes, "file_name": Path(item.file_path).name, "available": Path(item.file_path).is_file()} for item in consultation.recordings],
        "transcript": [{"id": item.id, "speaker": item.speaker, "text": item.text, "timestamp": item.timestamp, "sequence_number": item.sequence_number, "language_code": item.language_code} for item in transcript_rows],
        "record": record,
        "updates": [{"id": update.id, "field_name": update.field_name, "previous_value": update.previous_value, "new_value": update.new_value, "source_segment_ids": update.source_transcript_segment_ids, "updated_at": update.updated_at.isoformat(), "update_type": update.update_type, "actor_user_id": update.actor_user_id} for update in update_rows],
    }
