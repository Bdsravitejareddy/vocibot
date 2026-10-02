from collections.abc import Callable
from pathlib import Path
import tempfile
import wave

import numpy as np

from .speech import AudioChunk, TranscriptDraft, format_relative_timestamp


class IndicConformerProvider:
    """Lazy adapter for a local AI4Bharat IndicConformer NeMo checkpoint."""

    def __init__(
        self,
        model_path: str,
        device: str = "auto",
        *,
        model_loader: Callable[[str], object] | None = None,
    ) -> None:
        self.model_path = model_path
        self.device = device
        self._model_loader = model_loader
        self._model: object | None = None
        self.last_diagnostics: dict[str, object] = {}

    def _load(self) -> object:
        if self._model is not None:
            return self._model
        if self._model_loader is not None:
            self._model = self._model_loader(self.model_path)
            return self._model
        if not Path(self.model_path).is_file():
            raise RuntimeError(f"IndicConformer checkpoint not found: {self.model_path}")
        try:
            from nemo.collections.asr.models import ASRModel  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                "IndicConformer runtime unavailable; install the optional backend[indic-asr] dependencies"
            ) from error
        try:
            map_location = None if self.device == "auto" else self.device
            self._model = ASRModel.restore_from(restore_path=self.model_path, map_location=map_location)
        except Exception as error:
            raise RuntimeError(f"Unable to load IndicConformer checkpoint: {error}") from error
        return self._model

    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        if not language or language == "auto":
            raise ValueError("IndicConformer requires an explicit language code")
        model = self._load()
        if chunk.waveform is None:
            from .audio import decode_audio_payload

            waveform = decode_audio_payload(
                chunk.audio,
                encoding=chunk.encoding,
                sample_rate=chunk.sample_rate,
                channels=chunk.channels,
            ).waveform
        else:
            waveform = np.asarray(chunk.waveform, dtype=np.float32)
        samples = np.clip(waveform, -1.0, 1.0)
        samples = (samples * 32767).astype("<i2")
        temporary_audio = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio_path = Path(temporary_audio.name)
        temporary_audio.close()
        try:
            with wave.open(str(audio_path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(chunk.sample_rate)
                stream.writeframes(samples.tobytes())
            raw_result = model.transcribe(  # type: ignore[attr-defined]
                [str(audio_path)],
                batch_size=1,
                logprobs=False,
                language_id=language,
            )
        finally:
            audio_path.unlink(missing_ok=True)
        raw_text = raw_result[0] if raw_result else ""
        text = str(getattr(raw_text, "text", raw_text)).strip()
        duration_ms = int(len(waveform) / chunk.sample_rate * 1000)
        self.last_diagnostics = {
            "engine": "indic_conformer",
            "language": language,
            "language_probability": None,
            "segment_count": 1 if text else 0,
        }
        if not text:
            return []
        return [
            TranscriptDraft(
                text=text,
                timestamp=format_relative_timestamp(chunk.timestamp_ms),
                start_ms=chunk.timestamp_ms,
                end_ms=chunk.timestamp_ms + duration_ms,
                language_code=language,
            )
        ]
