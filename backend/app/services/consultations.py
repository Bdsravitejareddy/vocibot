from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.types import ClinicalRecord, ConsultationStatus, RecordUpdateType, TranscriptSegmentInput
from ..models import ClinicalRecord as ClinicalRecordModel
from ..models import Consultation, Patient, RecordUpdate, TranscriptSegment
from ..config import settings
from ..providers.factory import build_extraction_provider
from ..schemas import ApproveRequest, ConsultationCreate, SegmentCreate
from .evidence import EvidenceValidator
from .record_diff import diff_clinical_record


def create_consultation(session: Session, payload: ConsultationCreate) -> Consultation:
    patient = session.scalar(select(Patient).where(Patient.patient_identifier == payload.patient_id))
    if patient is None:
        patient = Patient(patient_identifier=payload.patient_id, name=payload.patient_name, age=payload.age, sex=payload.sex)
        session.add(patient)
        session.flush()
    else:
        patient.name = payload.patient_name or patient.name
        patient.age = payload.age
        patient.sex = payload.sex
    consultation = Consultation(patient_id=patient.id, status=ConsultationStatus.IN_PROGRESS.value)
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
    existing = session.get(TranscriptSegment, payload.id)
    if existing is not None and existing.consultation_id == consultation.id:
        return {"duplicate": True, "consultation": get_consultation(session, consultation_id)}
    if consultation.status != ConsultationStatus.IN_PROGRESS.value:
        raise ValueError("consultation is not in progress")
    segment = TranscriptSegment(id=payload.id, consultation_id=consultation.id, speaker=payload.speaker.value, text=payload.text, timestamp=datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00")), sequence_number=payload.sequence_number)
    session.add(segment)
    session.flush()
    transcript = list(session.scalars(select(TranscriptSegment).where(TranscriptSegment.consultation_id == consultation.id).order_by(TranscriptSegment.sequence_number)))
    transcript_inputs = [TranscriptSegmentInput(
        id=item.id, speaker=item.speaker, text=item.text, timestamp=item.timestamp.isoformat(), sequence_number=item.sequence_number
    ) for item in transcript]
    current = ClinicalRecord.model_validate(consultation.clinical_record.structured_data_json)
    result = build_extraction_provider(settings).extract(transcript_inputs, current)  # type: ignore[arg-type]
    validator = EvidenceValidator()
    evidence: dict[str, list[str]] = {}
    validated_record = current.model_copy(deep=True)
    for candidate in result.candidates:
        validated = validator.validate(candidate.field_name, candidate.value, candidate.source_segment_ids, transcript_inputs)  # type: ignore[arg-type]
        if validated.status.value == "SUPPORTED" and hasattr(validated_record, candidate.field_name):
            setattr(validated_record, candidate.field_name, candidate.value)
            evidence[candidate.field_name] = candidate.source_segment_ids
    doctor_edited_fields = {update.field_name for update in consultation.updates if update.update_type == RecordUpdateType.DOCTOR_EDITED.value}
    changes = diff_clinical_record(current, validated_record, evidence, doctor_edited_fields)
    for change in changes:
        session.add(RecordUpdate(consultation_id=consultation.id, field_name=change.field_name, previous_value=change.previous_value, new_value=change.new_value, source_transcript_segment_ids=change.source_segment_ids, update_type=RecordUpdateType.AI_EXTRACTED.value))
    if changes:
        record_data = current.model_dump()
        for change in changes:
            record_data[change.field_name] = change.new_value
        consultation.clinical_record.structured_data_json = record_data
        consultation.clinical_record.version += 1
    session.commit()
    return {"duplicate": False, "consultation": get_consultation(session, consultation_id)}


def stop_consultation(session: Session, consultation_id: str) -> Consultation:
    consultation = _find_consultation(session, consultation_id)
    if consultation.status != ConsultationStatus.IN_PROGRESS.value:
        return consultation
    consultation.status = ConsultationStatus.READY_FOR_REVIEW.value
    consultation.ended_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(consultation)
    return consultation


def approve_consultation(session: Session, consultation_id: str, payload: ApproveRequest) -> Consultation:
    consultation = _find_consultation(session, consultation_id)
    if consultation.status != ConsultationStatus.READY_FOR_REVIEW.value:
        raise ValueError("consultation must be ready for review before approval")
    current = ClinicalRecord.model_validate(consultation.clinical_record.structured_data_json)
    doctor_changes = diff_clinical_record(current, payload.record, {field: [] for field in payload.record.model_dump()}, set())
    for change in doctor_changes:
        session.add(RecordUpdate(consultation_id=consultation.id, field_name=change.field_name, previous_value=change.previous_value, new_value=change.new_value, source_transcript_segment_ids=[], update_type=RecordUpdateType.DOCTOR_EDITED.value))
    consultation.clinical_record.structured_data_json = payload.record.model_dump()
    consultation.clinical_record.version += 1
    session.add(RecordUpdate(consultation_id=consultation.id, field_name="__approval__", previous_value=ConsultationStatus.READY_FOR_REVIEW.value, new_value=ConsultationStatus.APPROVED.value, source_transcript_segment_ids=[], update_type=RecordUpdateType.DOCTOR_APPROVED.value))
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
        "status": consultation.status,
        "started_at": consultation.started_at.isoformat(),
        "ended_at": consultation.ended_at.isoformat() if consultation.ended_at else None,
        "patient": {"id": consultation.patient.id, "patient_identifier": consultation.patient.patient_identifier, "name": consultation.patient.name, "age": consultation.patient.age, "sex": consultation.patient.sex},
        "transcript": [{"id": item.id, "speaker": item.speaker, "text": item.text, "timestamp": item.timestamp.isoformat(), "sequence_number": item.sequence_number} for item in transcript_rows],
        "record": record,
        "updates": [{"id": update.id, "field_name": update.field_name, "previous_value": update.previous_value, "new_value": update.new_value, "source_segment_ids": update.source_transcript_segment_ids, "updated_at": update.updated_at.isoformat(), "update_type": update.update_type} for update in update_rows],
    }
