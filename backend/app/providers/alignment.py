from typing import Any


class WhisperXAligner:
    """Optional local word-alignment seam for Whisper transcripts."""

    def __init__(self, model_name: str = "WAV2VEC2_ASR_LARGE_LV60K_960H", model=None) -> None:
        self.model_name = model_name
        self._model = model

    def align(self, segments, audio=None, sample_rate: int = 16_000, language: str | None = None):
        if self._model is not None:
            return self._model.align(segments, audio, sample_rate)
        try:
            import whisperx  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(f"WhisperX dependency unavailable: {error}") from error
        if audio is None:
            return segments
        language_code = language or (segments[0].language_code if segments else None) or "en"
        model = whisperx.load_align_model(language_code=language_code, device="cpu", model_name=self.model_name)
        aligned = whisperx.align([segment.__dict__ for segment in segments], model[0], model[1], audio, device="cpu")
        return [type(segments[0])(**{**segment.__dict__, "start_ms": int(segment_data.get("start", 0) * 1000), "end_ms": int(segment_data.get("end", 0) * 1000)}) for segment, segment_data in zip(segments, aligned.get("segments", []))] if segments else []
