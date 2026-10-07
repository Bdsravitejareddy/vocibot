"""A Whisper fine-tuned on Indian conversational speech that writes Hindi and
Hindi-English mixed speech in Roman letters, the way Hinglish is typed:
"Doctor mujhe tin din se fever hai aur body pain bhi bahut hai."
(Oriserve Whisper-Hindi2Hinglish-Apex, Apache 2.0, from Whisper large-v3.)

Run with transformers on the Apple GPU, one short piece at a time (on whole
recordings it can loop: "I am scared. I am scared. ..."); a line that
repeats itself is dropped.
"""

from __future__ import annotations

from pathlib import Path
import threading
import zlib

import numpy as np

from .speech import GPU_LOCK, AudioChunk, TranscriptDraft, format_relative_timestamp

# Like Whisper's own check: text that compresses this well is a loop.
MAX_COMPRESSION_RATIO = 2.4


def _repetitive(text: str) -> bool:
    data = text.encode("utf-8")
    return len(data) > 40 and len(data) / len(zlib.compress(data)) > MAX_COMPRESSION_RATIO


class HinglishWhisper:
    def __init__(self, model_dir: str | Path) -> None:
        self.model_dir = Path(model_dir).expanduser()
        self._pipe = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        return (self.model_dir / "config.json").is_file() and any(self.model_dir.glob("*.safetensors"))

    def _load(self):
        with self._lock:
            if self._pipe is None:
                import torch  # type: ignore[import-not-found]
                from transformers import pipeline  # type: ignore[import-not-found]

                device = "mps" if torch.backends.mps.is_available() else "cpu"
                # Half precision on the Apple GPU returned empty text for a
                # Whisper fine-tune; full precision is reliable.
                self._pipe = pipeline("automatic-speech-recognition", model=str(self.model_dir), device=device, torch_dtype=torch.float32)
            return self._pipe

    def transcribe_chunk(self, chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]:
        audio = np.asarray(chunk.waveform, dtype=np.float32).reshape(-1)
        if len(audio) < 1_600:
            return []
        pipe = self._load()
        with GPU_LOCK:
            result = pipe({"raw": audio, "sampling_rate": chunk.sample_rate}, return_timestamps=True,
                          generate_kwargs={"task": "transcribe", "no_repeat_ngram_size": 6})
        drafts = []
        for part in result.get("chunks") or [{"text": result.get("text", ""), "timestamp": (0.0, len(audio) / chunk.sample_rate)}]:
            text = str(part.get("text", "")).strip()
            start, end = part.get("timestamp") or (0.0, None)
            end = end if end is not None else len(audio) / chunk.sample_rate
            if not text or _repetitive(text):
                continue
            start_ms, end_ms = chunk.timestamp_ms + int(float(start or 0) * 1000), chunk.timestamp_ms + int(float(end) * 1000)
            drafts.append(TranscriptDraft(text=text, timestamp=format_relative_timestamp(start_ms), start_ms=start_ms, end_ms=end_ms, language_code=language or "hi"))
        return drafts
