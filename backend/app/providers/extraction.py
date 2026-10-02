from typing import Protocol

from ..domain.types import ClinicalRecord, ExtractionResult, TranscriptSegmentInput


class ClinicalExtractionProvider(Protocol):
    def extract(self, transcript: list[TranscriptSegmentInput], current_record: ClinicalRecord) -> ExtractionResult:
        ...
