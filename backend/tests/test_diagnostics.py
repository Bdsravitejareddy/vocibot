from app.services.diagnostics import LocalPipelineDiagnostics, MockEMRUpdater


def test_diagnostics_records_latency_and_error_categories() -> None:
    diagnostics = LocalPipelineDiagnostics()
    diagnostics.record_timing("transcription_ms", 42.5)
    diagnostics.record_warning("OMISSION", "No allergies stated")
    assert diagnostics.timings["transcription_ms"] == 42.5
    assert diagnostics.warnings[0]["category"] == "OMISSION"


def test_mock_emr_update_returns_local_reference() -> None:
    result = MockEMRUpdater().update({"chief_complaint": "Fever"})
    assert result.updated is True
    assert result.reference.startswith("mock-emr-")
