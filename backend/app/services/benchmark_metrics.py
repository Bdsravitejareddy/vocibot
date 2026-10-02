def clinical_entity_recall(transcript: str, entities: dict[str, str]) -> dict[str, bool]:
    normalized = " ".join(transcript.lower().split())
    return {name: phrase.lower() in normalized for name, phrase in entities.items()}
