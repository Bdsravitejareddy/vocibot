from typing import Any

from .diagnostics import MockEMRUpdater


def build_report(hardware: dict[str, Any], models: dict[str, str], components: dict[str, str]) -> dict[str, Any]:
    return {"hardware": hardware, "models": models, "components": components, "latency_ms": {}, "unsupported_facts": [], "omissions": [], "errors": []}


def run_mock_emr_flow(updater: MockEMRUpdater, record: dict[str, Any]) -> dict[str, Any]:
    emr = updater.update(record)
    edited = {**record, "chief_complaint": f"{record.get('chief_complaint')}, corrected" if record.get("chief_complaint") else "Doctor-reviewed smoke note"}
    return {"mock_emr": {"updated": emr.updated, "reference": emr.reference}, "doctor_edit": edited, "reopened": {"status": "APPROVED", "record": edited}}
