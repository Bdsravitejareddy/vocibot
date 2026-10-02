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
        response = httpx.post(f"{self.base_url}/api/generate", json={"model": self.model, "prompt": prompt, "format": "json", "stream": False, "options": {"temperature": 0}}, timeout=settings.ollama_timeout_seconds)
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
        if isinstance(raw, dict):
            raw["proposed_record"] = self._sanitize_record(raw.get("proposed_record"))
        if isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
            status_aliases = {"EXPLICITLY_SUPPORTED": "SUPPORTED", "SUPPORTED": "SUPPORTED", "UNCERTAIN": "NEEDS_REVIEW", "NEEDS_REVIEW": "NEEDS_REVIEW", "REJECTED": "REJECTED"}
            sanitized_candidates = []
            for candidate in raw["candidates"]:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("field_name"), str):
                    continue
                if candidate["field_name"] == "vitals":
                    candidate["value"] = OllamaClinicalExtractionProvider._vitals(candidate.get("value"))
                candidate["source_segment_ids"] = [item for item in candidate.get("source_segment_ids", []) if isinstance(item, str)]
                candidate["speaker"] = candidate.get("speaker") if candidate.get("speaker") in {"DOCTOR", "PATIENT", "UNKNOWN"} else "UNKNOWN"
                candidate["status"] = status_aliases.get(str(candidate.get("status", "REJECTED")).upper(), "REJECTED")
                sanitized_candidates.append(candidate)
            raw["candidates"] = sanitized_candidates
        return ExtractionResult.model_validate(raw)

    @staticmethod
    def _vitals(value: Any) -> dict[str, str]:
        """Models often emit readings as numbers (38.6); the record stores text."""

        if not isinstance(value, dict):
            return {}
        return {str(key): str(reading) for key, reading in value.items() if reading is not None and not isinstance(reading, (dict, list))}

    @staticmethod
    def _sanitize_record(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        safe: dict[str, Any] = {}
        list_fields = {"presenting_symptoms", "relevant_negatives", "medications", "allergies", "examination_findings"}
        for field_name in ClinicalRecord.model_fields:
            if field_name not in payload:
                continue
            value = payload[field_name]
            if field_name in list_fields:
                safe[field_name] = value if isinstance(value, list) else []
            elif field_name == "vitals":
                safe[field_name] = OllamaClinicalExtractionProvider._vitals(value)
            elif value is None or isinstance(value, str):
                safe[field_name] = value
        return safe

    @staticmethod
    def _prompt(transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> str:
        return (
            "Return strict JSON matching this shape: {proposed_record: ClinicalRecord, candidates: [{field_name, value, source_segment_ids, speaker, status}]}. "
            "Extract only explicitly supported facts. Every candidate must include one or more exact transcript source_segment_ids. "
            "Never diagnose from symptoms. Assessment and plan require DOCTOR statements. "
            "Preserve uncertainty. Missing values must stay null or empty. "
            "Do not treat a doctor's question as a patient fact. Combine adjacent transcript segments when one thought is split across them, and cite every segment needed to support the value. "
            "Do not use medical examples or prior knowledge to fill missing fields. Do not normalize uncertain words or numbers into a medication; preserve the raw wording and mark NEEDS_REVIEW when terminology is ambiguous.\n"
            f"CURRENT_RECORD={current_record.model_dump_json()}\n"
            f"TRANSCRIPT={json.dumps([segment.model_dump() for segment in transcript])}"
        )
