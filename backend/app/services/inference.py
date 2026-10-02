"""One shared speech engine for every signed-in clinician.

All speech inference goes through a single worker thread and one copy of
each model, so memory stays fixed however many consultations run at once:
more users mean a longer queue, never more RAM. Live previews are served
first, then final transcripts, then batch work (re-transcription).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
from dataclasses import dataclass, field
import itertools
import logging
import queue
import threading
from typing import Any, Callable

import numpy as np

from ..config import settings
from ..providers.speech import AudioChunk, TranscriptDraft, format_relative_timestamp

logger = logging.getLogger(__name__)

LIVE, FINAL, BATCH = 0, 1, 2
PRIORITY_NAMES = {LIVE: "live", FINAL: "final", BATCH: "batch"}


@dataclass(order=True)
class _Job:
    priority: int
    sequence: int
    run: Callable[[], Any] = field(compare=False)
    future: Future = field(compare=False)


class InferenceEngine:
    def __init__(self) -> None:
        self._queue: queue.PriorityQueue[_Job] = queue.PriorityQueue()
        self._sequence = itertools.count()
        self._pipeline = None
        self._final_stt = None
        self._pipeline_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self.live_sessions: set[str] = set()
        self._live_lock = threading.Lock()

    # --- models ------------------------------------------------------------

    def pipeline(self, factory: Callable[[], Any]):
        """The shared pipeline, built once from ``factory`` on first use."""

        with self._pipeline_lock:
            if self._pipeline is None:
                self._pipeline = factory()
            return self._pipeline

    def final_stt(self, live_stt):
        """The final-transcript model: a dedicated one if configured, else the live one."""

        with self._pipeline_lock:
            if self._final_stt is None:
                from ..providers.factory import build_final_speech_provider

                self._final_stt = build_final_speech_provider(settings) or live_stt
            return self._final_stt

    def reset(self) -> None:
        """Forget the shared models (tests, or after changing models)."""

        with self._pipeline_lock:
            self._pipeline = None
            self._final_stt = None

    # --- scheduling --------------------------------------------------------

    def submit(self, priority: int, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        self._ensure_worker()
        future: Future = Future()
        self._queue.put(_Job(priority, next(self._sequence), lambda: function(*args, **kwargs), future))
        return future

    async def run(self, priority: int, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.wrap_future(self.submit(priority, function, *args, **kwargs))

    def run_blocking(self, priority: int, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return self.submit(priority, function, *args, **kwargs).result()

    def queue_depth(self) -> int:
        return self._queue.qsize()

    def _ensure_worker(self) -> None:
        with self._start_lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="vocibot-inference", daemon=True)
                self._worker.start()

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if not job.future.set_running_or_notify_cancel():
                continue
            try:
                job.future.set_result(job.run())
            except BaseException as error:  # noqa: BLE001 - delivered to the caller
                job.future.set_exception(error)

    # --- live admission ----------------------------------------------------

    def admit_live(self, consultation_id: str) -> bool:
        """Reserve a live-preview slot; beyond the limit audio is still recorded."""

        with self._live_lock:
            if consultation_id in self.live_sessions or len(self.live_sessions) < settings.max_live_sessions:
                self.live_sessions.add(consultation_id)
                return True
            return False

    def release_live(self, consultation_id: str) -> None:
        with self._live_lock:
            self.live_sessions.discard(consultation_id)

    # --- final transcription ----------------------------------------------

    def transcribe_recording(self, stt, waveform: np.ndarray, sample_rate: int, language: str | None, *, priority: int = FINAL) -> tuple[list[TranscriptDraft], list[str]]:
        """Transcribe a whole recording as short jobs split at pauses.

        Each piece is a separate queue job, so live previews of other
        clinicians are served between pieces instead of waiting for the
        entire recording (minutes on a CPU).
        """

        drafts: list[TranscriptDraft] = []
        warnings: list[str] = []
        for start, end in split_at_pauses(waveform, sample_rate, settings.asr_final_chunk_seconds):
            piece = np.ascontiguousarray(waveform[start:end], dtype=np.float32)
            offset_ms = int(start / sample_rate * 1000)
            piece_ms = int(len(piece) / sample_rate * 1000)
            chunk = AudioChunk(audio=b"", sample_rate=sample_rate, timestamp_ms=0, encoding="pcm_f32le", channels=1, waveform=piece)
            for draft in self.run_blocking(priority, stt.transcribe_chunk, chunk, language=language):
                if draft.start_ms is None or draft.end_ms is None or not 0 <= draft.start_ms < piece_ms:
                    warnings.append(f"Rejected final transcript timestamp {draft.start_ms}-{draft.end_ms}ms outside 0-{piece_ms}ms")
                    continue
                start_ms = draft.start_ms + offset_ms
                end_ms = min(draft.end_ms, piece_ms) + offset_ms
                drafts.append(TranscriptDraft(text=draft.text, timestamp=format_relative_timestamp(start_ms), speaker=draft.speaker, start_ms=start_ms, end_ms=end_ms, language_code=draft.language_code))
        return drafts, warnings


def split_at_pauses(waveform: np.ndarray, sample_rate: int, target_seconds: float) -> list[tuple[int, int]]:
    """Cut points about every ``target_seconds``, moved to the quietest moment nearby."""

    total = len(waveform)
    target = int(target_seconds * sample_rate)
    if total <= target * 1.25:
        return [(0, total)] if total else []
    window = int(0.02 * sample_rate)  # 20 ms energy frames
    search = int(4 * sample_rate)  # look up to 4 s either side for a pause
    spans: list[tuple[int, int]] = []
    start = 0
    while total - start > target * 1.25:
        ideal = start + target
        low, high = max(start + target // 2, ideal - search), min(total - window, ideal + search)
        region = np.abs(waveform[low:high + window]).astype(np.float32)
        frames = len(region) // window
        if frames <= 0:
            cut = ideal
        else:
            energy = region[: frames * window].reshape(frames, window).mean(axis=1)
            cut = low + int(np.argmin(energy)) * window + window // 2
        spans.append((start, cut))
        start = cut
    spans.append((start, total))
    return spans


ENGINE = InferenceEngine()
