from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ConsultationStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"


class RecordUpdateType(StrEnum):
    AI_EXTRACTED = "AI_EXTRACTED"
    DOCTOR_EDITED = "DOCTOR_EDITED"
    DOCTOR_APPROVED = "DOCTOR_APPROVED"


class EvidenceStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"
    DOCTOR_EDITED = "DOCTOR_EDITED"
    DOCTOR_APPROVED = "DOCTOR_APPROVED"


class Speaker(StrEnum):
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"
    UNKNOWN = "UNKNOWN"


class ClinicalRecord(BaseModel):
    chief_complaint: str | None = None
    duration: str | None = None
    presenting_symptoms: list[str] = Field(default_factory=list)
    history_present_illness: str | None = None
    relevant_negatives: list[str] = Field(default_factory=list)
    past_medical_history: str | None = None
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    vitals: dict[str, str] = Field(default_factory=dict)
    examination_findings: list[str] = Field(default_factory=list)
    assessment: str | None = None
    plan: str | None = None
    follow_up: str | None = None


class TranscriptSegmentInput(BaseModel):
    id: str
    speaker: Speaker
    text: str
    timestamp: str
    sequence_number: int
    language_code: str | None = None


class CandidateClinicalUpdate(BaseModel):
    field_name: str
    value: Any
    source_segment_ids: list[str]
    speaker: Speaker
    status: EvidenceStatus


class ExtractionResult(BaseModel):
    proposed_record: ClinicalRecord
    candidates: list[CandidateClinicalUpdate]
