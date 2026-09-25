from typing import Any


class WhisperXAligner:
    """Optional local word-alignment seam for Whisper transcripts."""

    def __init__(self, model_name: str = "large-v3") -> None:
        self.model_name = model_name

    def align(self, segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return segments
