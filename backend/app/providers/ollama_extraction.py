import json
from typing import Any

import httpx

from ..config import settings
from ..domain.types import ClinicalRecord, ExtractionResult, TranscriptSegmentInput


class OllamaClinicalExtractionProvider:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    def extract(self, transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> ExtractionResult:
        prompt = self._prompt(transcript, current_record)
        response = httpx.post(f"{self.base_url}/api/generate", json={"model": self.model, "prompt": prompt, "format": "json", "stream": False}, timeout=30)
        response.raise_for_status()
        payload: Any = response.json()
        raw = payload.get("response", payload)
        if isinstance(raw, str):
            raw = json.loads(raw)
        return ExtractionResult.model_validate(raw)

    @staticmethod
    def _prompt(transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> str:
        return (
            "Return strict JSON matching ExtractionResult. Extract only explicitly supported facts. "
            "Never diagnose from symptoms. Assessment and plan require DOCTOR statements. "
            "Preserve uncertainty. Missing values must stay null or empty.\n"
            f"CURRENT_RECORD={current_record.model_dump_json()}\n"
            f"TRANSCRIPT={json.dumps([segment.model_dump() for segment in transcript])}"
        )
