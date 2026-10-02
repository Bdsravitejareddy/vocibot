from typing import Any

from pydantic import BaseModel, Field

from ..domain.types import ClinicalRecord


class RecordFieldChange(BaseModel):
    field_name: str
    previous_value: Any
    new_value: Any
    source_segment_ids: list[str] = Field(default_factory=list)


def diff_clinical_record(current: ClinicalRecord, proposed: ClinicalRecord, evidence: dict[str, list[str]], doctor_edited_fields: set[str] | None = None) -> list[RecordFieldChange]:
    protected = doctor_edited_fields or set()
    changes: list[RecordFieldChange] = []
    current_data = current.model_dump()
    proposed_data = proposed.model_dump()
    for field_name, new_value in proposed_data.items():
        if field_name in protected or new_value in (None, [], {}):
            continue
        previous_value = current_data[field_name]
        if previous_value != new_value:
            changes.append(RecordFieldChange(field_name=field_name, previous_value=previous_value, new_value=new_value, source_segment_ids=evidence.get(field_name, [])))
    return changes
