import pytest

from app.services.approved_note_export import build_approved_note_payload


def test_export_requires_an_approved_consultation() -> None:
    with pytest.raises(ValueError, match="approved"):
        build_approved_note_payload({"status": "READY_FOR_REVIEW", "record": {}, "updates": []})


def test_export_includes_version_and_source_provenance() -> None:
    payload = build_approved_note_payload({
        "id": "consult-1",
        "status": "APPROVED",
        "patient": {"patient_identifier": "P-1"},
        "record": {"chief_complaint": "fever"},
        "updates": [{"field_name": "chief_complaint", "source_segment_ids": ["seg-1"]}],
    })
    assert payload["schema_version"] == "1"
    assert payload["record"]["chief_complaint"] == "fever"
    assert payload["provenance"]["chief_complaint"] == ["seg-1"]
