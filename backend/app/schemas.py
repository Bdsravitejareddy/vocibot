from pydantic import BaseModel, Field

from .domain.types import ClinicalRecord, ConsultationStatus, Speaker


class ConsultationCreate(BaseModel):
    patient_id: str = Field(min_length=1, max_length=120)
    patient_name: str | None = Field(default=None, max_length=200)
    age: int = Field(ge=0, le=130)
    sex: str = Field(min_length=1, max_length=40)


class SegmentCreate(BaseModel):
    id: str = Field(min_length=1)
    speaker: Speaker
    text: str = Field(min_length=1)
    timestamp: str
    sequence_number: int = Field(ge=0)
    language_code: str | None = Field(default=None, max_length=20)


class ApproveRequest(BaseModel):
    record: ClinicalRecord
