import re


def medication_needs_review(value: object, texts: list[str]) -> bool:
    """Reject ambiguous numeric/currency medication candidates without rewriting evidence."""

    values = value if isinstance(value, list) else [value]
    for item in values:
        candidate = str(item).strip()
        if re.fullmatch(r"\$?\s*\d+(?:\.\d+)?", candidate):
            return True
        if "$" in candidate and not any(re.search(r"\b(?:dolo|paracetamol|ibuprofen|tablet|medicine|medication)\b", text, re.IGNORECASE) for text in texts):
            return True
    return False
