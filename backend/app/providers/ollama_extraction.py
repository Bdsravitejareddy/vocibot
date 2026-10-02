import json
import re
from typing import Any

import httpx

from ..config import settings
from ..domain.types import ClinicalRecord, ExtractionResult, TranscriptSegmentInput

LIST_FIELDS = {"presenting_symptoms", "relevant_negatives", "medications", "allergies", "examination_findings"}
# Values a model uses to say "not discussed"; a missing field must stay empty.
# Small local models can loop ("feeling dizzy, feeling sick, ...") until the
# token limit; penalise repeats and bound the output.  The transcript prompt of
# a long consultation needs more than Ollama's small default context.
OLLAMA_OPTIONS = {"temperature": 0, "repeat_penalty": 1.15, "num_predict": 1536}
# Rough characters per token for English clinical speech in Llama/Qwen tokenizers.
CHARS_PER_TOKEN = 3.2
SPEAKER_LABELS = {"DOCTOR": "Doctor", "PATIENT": "Patient", "UNKNOWN": "Speaker", "Speaker.DOCTOR": "Doctor", "Speaker.PATIENT": "Patient", "Speaker.UNKNOWN": "Speaker"}


def context_size(prompt: str) -> int:
    """Context just large enough for this prompt and the answer.

    The KV cache grows with the context (~0.13 MB per token for an 8B model),
    so sizing it per consultation keeps the note model's memory small.
    """

    needed = int(len(prompt) / CHARS_PER_TOKEN) + OLLAMA_OPTIONS["num_predict"] + 256
    rounded = -(-needed // 1024) * 1024
    return max(2048, min(settings.ollama_max_context, rounded))


PLACEHOLDERS = {"none", "n/a", "na", "nil", "null", "unknown", "not mentioned", "not discussed", "not stated", "not provided", "not applicable", "no information", "-", ""}


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
        options = {**OLLAMA_OPTIONS, "num_ctx": context_size(prompt)}
        if settings.ollama_num_gpu >= 0:
            options["num_gpu"] = settings.ollama_num_gpu
        if settings.ollama_num_thread > 0:
            options["num_thread"] = settings.ollama_num_thread
        response = httpx.post(f"{self.base_url}/api/generate", json={"model": self.model, "prompt": prompt, "format": "json", "stream": False, "keep_alive": settings.ollama_keep_alive, "options": options}, timeout=settings.ollama_timeout_seconds)
        response.raise_for_status()
        payload: Any = response.json()
        self.last_stats = {key: payload.get(key) for key in ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration")} | {"num_ctx": options["num_ctx"]}
        raw = payload.get("response", payload)
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict) and "candidates" in raw:
            # Only evidence-backed candidates fill the record; the model is not
            # asked for a duplicate proposed record (8B models loop on it).
            raw.setdefault("proposed_record", {})
        if isinstance(raw, dict) and "proposed_record" not in raw and "candidates" not in raw:
            record = ClinicalRecord.model_validate(raw)
            if any(value not in (None, "", [], {}) for value in record.model_dump().values()):
                raise ValueError("Ollama returned clinical fields without proposed_record/candidates evidence; rejected")
            raw = {"proposed_record": record.model_dump(), "candidates": []}
        if isinstance(raw, dict):
            raw["proposed_record"] = self._sanitize_record(raw.get("proposed_record"))
        short_ids = {f"s{index}": segment.id for index, segment in enumerate(transcript)} | {str(index): segment.id for index, segment in enumerate(transcript)}
        if isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
            status_aliases = {"EXPLICITLY_SUPPORTED": "SUPPORTED", "SUPPORTED": "SUPPORTED", "UNCERTAIN": "NEEDS_REVIEW", "NEEDS_REVIEW": "NEEDS_REVIEW", "REJECTED": "REJECTED"}
            sanitized_candidates = []
            for candidate in raw["candidates"]:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("field_name"), str):
                    continue
                if candidate["field_name"] == "vitals":
                    candidate["value"] = OllamaClinicalExtractionProvider._vitals(candidate.get("value"))
                else:
                    candidate["value"] = OllamaClinicalExtractionProvider._coerce(candidate["field_name"], candidate.get("value"))
                if candidate["value"] in (None, [], {}):
                    continue
                # The prompt cites segments by short ids (s0, s1, ...); map them back.
                # Models also send one id as a string, or nested lists.
                cited = candidate.get("source_segment_ids", [])
                cited = [cited] if isinstance(cited, (str, int)) else cited if isinstance(cited, list) else []
                flat = [inner for item in cited for inner in (item if isinstance(item, list) else [item])]
                candidate["source_segment_ids"] = [short_ids.get(str(item).strip().lower(), str(item)) for item in flat if isinstance(item, (str, int))]
                speaker = candidate.get("speaker")
                speaker = speaker[0] if isinstance(speaker, list) and speaker else speaker
                candidate["speaker"] = speaker if isinstance(speaker, str) and speaker in {"DOCTOR", "PATIENT", "UNKNOWN"} else "UNKNOWN"
                candidate["status"] = status_aliases.get(str(candidate.get("status", "REJECTED")).upper(), "REJECTED")
                sanitized_candidates.append(candidate)
            raw["candidates"] = sanitized_candidates
        return ExtractionResult.model_validate(raw)

    @staticmethod
    def _coerce(field_name: str, value: Any) -> Any:
        """Shape a model value to its field: lists stay lists, text stays text."""

        if field_name in LIST_FIELDS:
            items = value if isinstance(value, list) else re.split(r"\s*(?:[,;\n]|\band\b)\s*", value) if isinstance(value, str) else []
            cleaned = [str(item).strip(" .") for item in items if isinstance(item, (str, int, float))]
            return [item for item in cleaned if item.lower() not in PLACEHOLDERS]
        if isinstance(value, list):
            value = "; ".join(str(item) for item in value if isinstance(item, (str, int, float)))
        if isinstance(value, (int, float)):
            value = str(value)
        if not isinstance(value, str) or value.strip(" .").lower() in PLACEHOLDERS:
            return None
        return value.strip()

    @staticmethod
    def _vitals(value: Any) -> dict[str, str]:
        """Models often emit readings as numbers (38.6); the record stores text."""

        if not isinstance(value, dict):
            return {}
        return {str(key): str(reading) for key, reading in value.items() if reading is not None and not isinstance(reading, (dict, list)) and str(reading).strip().lower() not in PLACEHOLDERS}

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
                safe[field_name] = OllamaClinicalExtractionProvider._coerce(field_name, value) if isinstance(value, list) else []
            elif field_name == "vitals":
                safe[field_name] = OllamaClinicalExtractionProvider._vitals(value)
            else:
                safe[field_name] = OllamaClinicalExtractionProvider._coerce(field_name, value)
        return safe

    @staticmethod
    def _prompt(transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> str:
        return (
            "Return strict JSON matching this shape: {candidates: [{field_name, value, source_segment_ids, speaker, status}]}. "
            "ClinicalRecord fields: chief_complaint (text: the patient's main problem in a few words, as the patient describes it, never a diagnosis), duration (text), presenting_symptoms (array of short strings, one symptom each), "
            "history_present_illness (text), relevant_negatives (array, e.g. \"no fever\"), past_medical_history (text), medications (array), allergies (array), "
            "vitals (object of text readings), examination_findings (array: what the doctor observed when examining), assessment (text: the doctor's stated impression), "
            "plan (text: treatment, prescriptions and referrals the doctor proposes), follow_up (text). "
            "Emit at most one candidate per field; array fields take a JSON array value of distinct items, never a comma-separated string and never the same item twice. Use the patient's own symptom words where possible. "
            "Speaker labels may be UNKNOWN because speakers are not separated: set each candidate's speaker to DOCTOR or PATIENT from the content "
            "(questions, examination instructions, impressions and plans are DOCTOR; the patient or a companion describing the illness is PATIENT). "
            "A symptom the patient denies belongs in relevant_negatives, not presenting_symptoms. Never write placeholders such as none or not mentioned: omit the candidate. "
            "examination_findings are only what the doctor observed while examining (e.g. eye movements, temperature reading); a doctor's 'it sounds like X' or 'this looks like X' is the assessment. "
            "Earlier diagnoses, investigations and specialist opinions from before this visit belong in past_medical_history. "
            "history_present_illness summarises only facts stated in the transcript: never add a symptom the patient did not report. "
            "Extract only explicitly supported facts. Every candidate must include one or more source_segment_ids: the s-numbers of the transcript lines that state it (e.g. [\"s3\", \"s4\"]). "
            "Never diagnose from symptoms. Assessment and plan require DOCTOR statements. "
            "Preserve uncertainty. Missing values must stay null or empty. "
            "Do not treat a doctor's question as a patient fact. Combine adjacent transcript segments when one thought is split across them, and cite every segment needed to support the value. "
            "Do not use medical examples or prior knowledge to fill missing fields. Do not normalize uncertain words or numbers into a medication; preserve the raw wording and mark NEEDS_REVIEW when terminology is ambiguous.\n"
            + (f"CURRENT_RECORD={current_record.model_dump_json(exclude_defaults=True)}\n" if current_record.model_dump(exclude_defaults=True) else "")
            + "TRANSCRIPT (one line per segment: id, speaker, words):\n"
            + "\n".join(f"s{index} [{SPEAKER_LABELS.get(str(segment.speaker), 'Speaker')}] {segment.text}" for index, segment in enumerate(transcript))
        )
