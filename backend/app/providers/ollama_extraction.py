import json
from typing import Any

import httpx

from ..config import settings
from ..domain.types import ClinicalRecord, ExtractionResult, TranscriptSegmentInput


class OllamaClinicalExtractionProvider:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model

    def check_available(self) -> None:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            response.raise_for_status()
            models = {item.get("name") for item in response.json().get("models", [])}
            if models and self.model not in models:
                raise RuntimeError(f"Ollama model {self.model!r} is not installed; available models: {sorted(models)}")
        except Exception as error:
            raise RuntimeError(f"Ollama unavailable at {self.base_url}: {error}") from error

    def extract(self, transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> ExtractionResult:
        prompt = self._prompt(transcript, current_record)
        response = httpx.post(f"{self.base_url}/api/generate", json={"model": self.model, "prompt": prompt, "format": "json", "stream": False}, timeout=30)
        response.raise_for_status()
        payload: Any = response.json()
        raw = payload.get("response", payload)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict) and "proposed_record" not in raw and "candidates" not in raw:
            record = ClinicalRecord.model_validate(raw)
            if any(value not in (None, "", [], {}) for value in record.model_dump().values()):
                raise ValueError("Ollama returned clinical fields without proposed_record/candidates evidence; rejected")
            raw = {"proposed_record": record.model_dump(), "candidates": []}
        if isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
            status_aliases = {"EXPLICITLY_SUPPORTED": "SUPPORTED", "SUPPORTED": "SUPPORTED", "UNCERTAIN": "NEEDS_REVIEW", "NEEDS_REVIEW": "NEEDS_REVIEW", "REJECTED": "REJECTED"}
            for candidate in raw["candidates"]:
                if isinstance(candidate, dict):
                    candidate["status"] = status_aliases.get(str(candidate.get("status", "REJECTED")).upper(), "REJECTED")
        return ExtractionResult.model_validate(raw)

    @staticmethod
    def _prompt(transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> str:
        return (
            "Return strict JSON matching this shape: {proposed_record: ClinicalRecord, candidates: [{field_name, value, source_segment_ids, speaker, status}]}. "
            "Extract only explicitly supported facts. Every candidate must include one or more exact transcript source_segment_ids. "
            "Never diagnose from symptoms. Assessment and plan require DOCTOR statements. "
            "Preserve uncertainty. Missing values must stay null or empty.\n"
            f"CURRENT_RECORD={current_record.model_dump_json()}\n"
            f"TRANSCRIPT={json.dumps([segment.model_dump() for segment in transcript])}"
        )
