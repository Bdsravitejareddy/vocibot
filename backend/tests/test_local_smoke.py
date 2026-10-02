from app.services.diagnostics import MockEMRUpdater
from app.services.smoke import build_report, run_mock_emr_flow


def test_smoke_report_contains_hardware_models_and_stage_results() -> None:
    report = build_report({"architecture": "Apple Silicon", "ram_gb": 48}, {"whisper_model": "small", "ollama_model": "qwen2.5:7b-instruct"}, {"silero_vad": "unavailable"})
    assert report["hardware"]["architecture"] == "Apple Silicon"
    assert report["models"]["whisper_model"] == "small"
    assert report["components"]["silero_vad"] == "unavailable"


def test_smoke_flow_updates_mock_emr_then_reopens_approved_record() -> None:
    flow = run_mock_emr_flow(MockEMRUpdater(), {"chief_complaint": "Fever"})
    assert flow["mock_emr"]["updated"] is True
    assert flow["doctor_edit"]["chief_complaint"] == "Fever, corrected"
    assert flow["reopened"]["status"] == "APPROVED"
