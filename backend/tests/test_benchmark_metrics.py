from app.services.benchmark_metrics import clinical_entity_recall


def test_clinical_entity_recall_reports_numeric_and_negation_sensitive_terms() -> None:
    result = clinical_entity_recall(
        "I have a cough and cold for two weeks. I feel nauseous and have a headache. The doctor said Dolo 650.",
        {"cough": "cough", "two weeks": "two weeks", "nausea": "nauseous", "headache": "headache", "dolo 650": "dolo 650"},
    )

    assert result == {"cough": True, "two weeks": True, "nausea": True, "headache": True, "dolo 650": True}
