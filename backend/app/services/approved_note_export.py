from typing import Any


def build_approved_note_payload(consultation: dict[str, Any]) -> dict[str, Any]:
    """Create a versioned, offline connector payload after clinician approval."""
    if consultation.get("status") != "APPROVED":
        raise ValueError("consultation must be approved before export")
    updates = consultation.get("updates", [])
    provenance: dict[str, list[str]] = {}
    for update in updates:
        field_name = update.get("field_name")
        source_ids = update.get("source_segment_ids", [])
        if field_name and source_ids:
            provenance.setdefault(field_name, [])
            provenance[field_name] = list(dict.fromkeys(provenance[field_name] + source_ids))
    return {
        "schema_version": "1",
        "consultation_id": consultation.get("id"),
        "patient": consultation.get("patient", {}),
        "record": consultation.get("record", {}),
        "provenance": provenance,
    }
