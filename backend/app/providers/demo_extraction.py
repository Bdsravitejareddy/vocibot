import re

from ..domain.types import CandidateClinicalUpdate, ClinicalRecord, EvidenceStatus, ExtractionResult, Speaker, TranscriptSegmentInput


class DemoClinicalExtractionProvider:
    """Conservative offline extractor for the scripted demo and local smoke tests."""

    def extract(self, transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> ExtractionResult:
        record = current_record.model_copy(deep=True)
        candidates: list[CandidateClinicalUpdate] = []

        for segment in transcript:
            text = segment.text.strip()
            lower = text.lower()
            if segment.speaker == Speaker.PATIENT and "fever" in lower:
                record.chief_complaint = record.chief_complaint or "Fever"
                if "Fever" not in record.presenting_symptoms:
                    record.presenting_symptoms.append("Fever")
                self._add_candidate(candidates, "chief_complaint", "Fever", segment, Speaker.PATIENT)
                self._add_candidate(candidates, "presenting_symptoms", list(record.presenting_symptoms), segment, Speaker.PATIENT)
                match = re.search(r"(?:for|since)\s+((?:\d+|one|two|three|four|five)\s+(?:days?|weeks?))", lower)
                if match:
                    duration = {"three days": "3 days", "one day": "1 day", "two days": "2 days"}.get(match.group(1), match.group(1))
                    record.duration = duration
                    self._add_candidate(candidates, "duration", duration, segment, Speaker.PATIENT)
            if segment.speaker == Speaker.PATIENT and "dry cough" in lower:
                if "Dry cough" not in record.presenting_symptoms:
                    record.presenting_symptoms.append("Dry cough")
                self._add_candidate(candidates, "presenting_symptoms", list(record.presenting_symptoms), segment, Speaker.PATIENT)
                match = re.search(r"since\s+(yesterday|today|\d+\s+days?)", lower)
                if match and not record.duration:
                    record.duration = match.group(1)
                    self._add_candidate(candidates, "duration", record.duration, segment, Speaker.PATIENT)
            elif segment.speaker == Speaker.PATIENT and re.search(r"\bcough\b", lower):
                if "Cough" not in record.presenting_symptoms:
                    record.presenting_symptoms.append("Cough")
                if record.chief_complaint is None:
                    record.chief_complaint = "Cough"
                    self._add_candidate(candidates, "chief_complaint", "Cough", segment, Speaker.PATIENT)
                self._add_candidate(candidates, "presenting_symptoms", list(record.presenting_symptoms), segment, Speaker.PATIENT)
            if segment.speaker == Speaker.PATIENT and (lower == "no." or "no breathing difficulty" in lower or "no breathing" in lower):
                value = "No breathing difficulty reported"
                if value not in record.relevant_negatives:
                    record.relevant_negatives.append(value)
                self._add_candidate(candidates, "relevant_negatives", list(record.relevant_negatives), segment, Speaker.PATIENT)
            if segment.speaker == Speaker.PATIENT and "paracetamol" in lower:
                if "Paracetamol" not in record.medications:
                    record.medications.append("Paracetamol")
                self._add_candidate(candidates, "medications", list(record.medications), segment, Speaker.PATIENT)
            if segment.speaker == Speaker.DOCTOR and "could possibly be viral" in lower:
                record.assessment = "Possible viral illness"
                self._add_candidate(candidates, "assessment", record.assessment, segment, Speaker.DOCTOR)
            if segment.speaker == Speaker.DOCTOR and lower.startswith("assessment:"):
                value = text.split(":", 1)[1].strip()
                if value:
                    record.assessment = value
                    self._add_candidate(candidates, "assessment", value, segment, Speaker.DOCTOR)
            if segment.speaker == Speaker.DOCTOR and lower.startswith("plan:"):
                value = text.split(":", 1)[1].strip()
                if value:
                    record.plan = value
                    self._add_candidate(candidates, "plan", value, segment, Speaker.DOCTOR)

        return ExtractionResult(proposed_record=record, candidates=candidates)

    @staticmethod
    def _add_candidate(candidates: list[CandidateClinicalUpdate], field_name: str, value: object, segment: TranscriptSegmentInput, speaker: Speaker) -> None:
        for candidate in candidates:
            if candidate.field_name == field_name and candidate.value == value:
                if segment.id not in candidate.source_segment_ids:
                    candidate.source_segment_ids.append(segment.id)
                return
        candidates.append(CandidateClinicalUpdate(field_name=field_name, value=value, source_segment_ids=[segment.id], speaker=speaker, status=EvidenceStatus.SUPPORTED))
