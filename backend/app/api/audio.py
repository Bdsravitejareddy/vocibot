import logging
import json
import asyncio
from pathlib import Path
from time import perf_counter

import numpy as np

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..providers.alignment import WhisperXAligner
from ..providers.audio import audio_metrics, decode_audio_payload, save_debug_wav
from ..providers.diarization import PyannoteDiarizationProvider
from ..providers.factory import build_speech_provider
from ..providers.local_pipeline import LocalAudioPipeline
from ..providers.reconciliation import FinalReconciler
from ..providers.speech import AudioChunk
from ..providers.streaming import TranscriptCommitter
from ..db import SessionLocal
from ..services.consultations import replace_with_reconciled_transcript
from ..services.live_cpu import LocalPipelineExecutor
from ..providers.vad import SileroVoiceActivityDetector

router = APIRouter(tags=["audio"])
logger = logging.getLogger(__name__)
SUPPORTED_LANGUAGE_CODES = {"auto", "en", "te", "hi", "mr", "gu"}


def build_local_pipeline() -> LocalAudioPipeline:
    return LocalAudioPipeline(
        SileroVoiceActivityDetector(threshold=settings.silero_threshold),
        build_speech_provider(settings),
        WhisperXAligner(model_name=settings.whisperx_model) if settings.whisperx_enabled else None,
        PyannoteDiarizationProvider(model_name=settings.pyannote_model) if settings.diarization_enabled else None,
    )


@router.websocket("/api/consultations/{consultation_id}/audio")
async def audio_stream(websocket: WebSocket, consultation_id: str) -> None:
    await websocket.accept()
    primary_live_workers = settings.asr_parallel_workers if settings.ai_mode == "local" else 1
    reserve_live_workers = settings.asr_reserve_workers if settings.ai_mode == "local" else 0
    live_workers = primary_live_workers + reserve_live_workers
    pipeline_executor = LocalPipelineExecutor(workers=live_workers)
    try:
        metadata = await websocket.receive_json()
        sample_rate = int(metadata.get("sample_rate", settings.audio_sample_rate))
        channels = int(metadata.get("channels", 1))
        encoding = str(metadata.get("encoding", "pcm_f32le"))
        mime_type = str(metadata.get("mime_type", "audio/raw"))
        language = str(metadata.get("language", "auto")).lower()
        if language not in SUPPORTED_LANGUAGE_CODES:
            await websocket.send_json({"type": "error", "category": "INITIALIZATION", "message": f"Unsupported language code: {language}"})
            await websocket.close(code=1008)
            return
        if settings.ai_mode == "local" and settings.stt_provider == "indic_conformer" and language == "auto":
            await websocket.send_json({"type": "error", "category": "INITIALIZATION", "message": "Select a language before using IndicConformer; automatic language detection is unavailable for this engine."})
            await websocket.close(code=1008)
            return
        # Native CTranslate2 models are not thread-safe for concurrent calls.
        # Give each live CPU worker an independent pipeline/model instead.
        pipelines = [build_local_pipeline() for _ in range(live_workers)]
        pipeline = pipelines[0]
        # Load each independent native model before capture starts.  Warming
        # sequentially avoids a large temporary CPU spike during startup.
        for candidate in pipelines:
            warmup = getattr(candidate, "warmup", None)
            if callable(warmup):
                await pipeline_executor.run(warmup)
    except Exception as error:
        logger.exception("Local audio initialization failed for consultation %s", consultation_id)
        pipeline_executor.close()
        await websocket.send_json({"type": "error", "category": "INITIALIZATION", "message": "Local audio pipeline is unavailable. See backend logs for details."})
        await websocket.close(code=1011)
        return
    await websocket.send_json({"type": "ready", "consultation_id": consultation_id, "sample_rate": sample_rate, "channels": channels, "encoding": encoding, "mime_type": mime_type, "language": language})
    timestamp_ms = 0
    transcript_sequence = 0
    pending_waveform = np.empty(0, dtype=np.float32)
    pending_start_ms = 0
    received_audio = bytearray()
    debug_windows: list[dict[str, object]] = []
    debug_transcripts: list[dict[str, object]] = []
    received_waveforms: list[np.ndarray] = []
    final_reconciliation: dict[str, object] = {}
    capture_started_at: float | None = None
    first_text_latency_ms: float | None = None
    latest_capture_end_ms = 0
    skipped_stale_live_windows = 0

    def persist_debug_audio() -> None:
        if not settings.audio_debug_dir or not received_audio:
            return
        debug_dir = Path(settings.audio_debug_dir)
        debug_path = debug_dir / f"{consultation_id}.wav"
        debug_audio = save_debug_wav(debug_path, bytes(received_audio), encoding=encoding, sample_rate=sample_rate, channels=channels)
        output_audio = decode_audio_payload(bytes(received_audio), encoding=encoding, sample_rate=sample_rate, channels=channels)
        debug_report = {
            "consultation_id": consultation_id,
            "input_encoding": encoding,
            "mime_type": mime_type,
            "source_sample_rate": debug_audio.source_sample_rate,
            "decoded_sample_rate": debug_audio.sample_rate,
            "channel_count": debug_audio.source_channels,
            "whisper_sample_rate": output_audio.sample_rate,
            "received_duration_ms": audio_metrics(debug_audio.waveform, sample_rate=debug_audio.sample_rate)["duration_ms"],
            "debug_wav": str(debug_path),
            "windows": debug_windows,
            "transcript": debug_transcripts,
            "final_reconciliation": final_reconciliation,
            "first_text_latency_ms": first_text_latency_ms,
            "skipped_stale_live_windows": skipped_stale_live_windows,
            "out_of_order_live_segments": committer.out_of_order_count,
            **audio_metrics(debug_audio.waveform, sample_rate=debug_audio.sample_rate),
        }
        (debug_dir / f"{consultation_id}.json").write_text(json.dumps(debug_report, indent=2) + "\n")
        logger.info("Audio debug artifact %s", json.dumps(debug_report, sort_keys=True))
    window_samples = max(1, int(settings.asr_window_seconds * settings.audio_sample_rate))
    overlap_samples = min(window_samples - 1, max(0, int(settings.asr_overlap_seconds * settings.audio_sample_rate)))
    step_samples = window_samples - overlap_samples
    min_speech_samples = max(1, int(settings.asr_min_speech_seconds * settings.audio_sample_rate))
    committer = TranscriptCommitter()
    audio_queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
    send_lock = asyncio.Lock()

    async def send_json(message: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    async def infer_payload(active_pipeline: LocalAudioPipeline, waveform: np.ndarray, payload_timestamp_ms: int) -> tuple[int, object | None]:
        duration_ms = int(len(waveform) / settings.audio_sample_rate * 1000)
        if len(waveform) < min_speech_samples:
            logger.info("ASR window rejected consultation=%s start_ms=%s end_ms=%s rejection=below_minimum_window", consultation_id, payload_timestamp_ms, payload_timestamp_ms + duration_ms)
            return duration_ms, None
        try:
            chunk = AudioChunk(audio=b"", sample_rate=settings.audio_sample_rate, timestamp_ms=payload_timestamp_ms, encoding="pcm_f32le", channels=1, waveform=waveform)
            # Two CTranslate2 workers keep up with incoming 450 ms windows; the
            # queue below still publishes their results in capture order.
            result = await pipeline_executor.run(active_pipeline.process, chunk, language=None if language == "auto" else language)
            logger.info(
                "ASR window consultation=%s start_ms=%s end_ms=%s duration_ms=%s audio=%s timings=%s warnings=%s",
                consultation_id,
                payload_timestamp_ms,
                payload_timestamp_ms + duration_ms,
                duration_ms,
                audio_metrics(waveform, sample_rate=settings.audio_sample_rate),
                result.timings,
                {"diagnostics": result.diagnostics, "warnings": [warning.message for warning in result.warnings]},
            )
            debug_windows.append({
                "start_ms": payload_timestamp_ms,
                "end_ms": payload_timestamp_ms + duration_ms,
                "audio": audio_metrics(waveform, sample_rate=settings.audio_sample_rate),
                "timings": result.timings,
                "diagnostics": result.diagnostics,
                "warnings": [warning.message for warning in result.warnings],
            })
        except Exception:
            logger.exception(
                "Local audio pipeline failed for consultation %s: encoding=%s mime_type=%s sample_rate=%s channels=%s bytes=%s",
                consultation_id,
                encoding,
                mime_type,
                sample_rate,
                channels,
                len(waveform),
            )
            await send_json({"type": "error", "category": "PIPELINE", "message": "Local microphone audio could not be processed. See backend logs for details."})
            return duration_ms, None
        return duration_ms, result

    async def publish_result(payload_timestamp_ms: int, duration_ms: int, result: object | None) -> None:
        nonlocal transcript_sequence, first_text_latency_ms, skipped_stale_live_windows
        if result is None:
            return
        segment_end_ms = payload_timestamp_ms + duration_ms
        processing_delay_ms = (
            (perf_counter() - capture_started_at) * 1000 - segment_end_ms
            if capture_started_at is not None
            else 0
        )
        if (
            latest_capture_end_ms - segment_end_ms > settings.asr_live_max_staleness_seconds * 1000
            or processing_delay_ms > settings.asr_live_max_staleness_seconds * 1000
        ):
            # Live preview must describe what the clinician is hearing now.  The
            # complete audio is reconciled at Stop, so discarding a late preview
            # result cannot drop it from the authoritative transcript.
            skipped_stale_live_windows += 1
            return
        await send_json({"type": "status", "timings": result.timings, "diagnostics": result.diagnostics})
        for warning in result.warnings:
            await send_json({"type": "warning", "category": warning.category, "message": warning.message})
        for index, draft in enumerate(committer.add(result.transcripts)):
            if first_text_latency_ms is None and capture_started_at is not None:
                first_text_latency_ms = (perf_counter() - capture_started_at) * 1000
            debug_transcripts.append({"text": draft.text, "speaker": draft.speaker, "timestamp": draft.timestamp, "start_ms": draft.start_ms, "end_ms": draft.end_ms, "language_code": draft.language_code})
            await send_json({"type": "transcript", "id": f"local-{payload_timestamp_ms}-{index}", "text": draft.text, "speaker": draft.speaker, "timestamp": draft.timestamp, "start_ms": draft.start_ms, "end_ms": draft.end_ms, "sequence_number": transcript_sequence, "language_code": draft.language_code})
            transcript_sequence += 1

    async def process_audio_queue() -> None:
        nonlocal pending_waveform, pending_start_ms, timestamp_ms, latest_capture_end_ms
        in_flight: list[tuple[int, LocalAudioPipeline, asyncio.Task[tuple[int, object | None]], float]] = []
        ready_windows: list[tuple[np.ndarray, int]] = []
        available_pipelines = list(pipelines[:primary_live_workers])
        reserve_pipelines = list(pipelines[primary_live_workers:])
        available_reserve_pipelines = list(reserve_pipelines)

        async def publish_completed(done: set[asyncio.Task[object]]) -> None:
            # A rare short-window decode can take several seconds.  Publish a
            # later completed window rather than make the clinician wait behind
            # it; TranscriptCommitter safely discards the eventual stale draft,
            # and the authoritative final pass preserves the complete capture.
            completed = sorted(
                (item for item in in_flight if item[2] in done),
                key=lambda item: item[0],
            )
            for payload_timestamp_ms, active_pipeline, task, started_at in completed:
                in_flight.remove((payload_timestamp_ms, active_pipeline, task, started_at))
                duration_ms, result = await task
                (available_reserve_pipelines if active_pipeline in reserve_pipelines else available_pipelines).append(active_pipeline)
                await publish_result(payload_timestamp_ms, duration_ms, result)
            schedule_available()

        def schedule_available() -> None:
            def primary_stalled() -> bool:
                return any(
                    active_pipeline not in reserve_pipelines
                    and perf_counter() - started_at >= settings.asr_live_stall_seconds
                    for _, active_pipeline, _, started_at in in_flight
                )

            while ready_windows and (available_pipelines or available_reserve_pipelines):
                latest_timestamp_ms = ready_windows[-1][1]
                while (
                    len(ready_windows) > 1
                    and latest_timestamp_ms - ready_windows[0][1] > settings.asr_live_max_staleness_seconds * 1000
                ):
                    # Prefer the newest audio when a pathological decoder has
                    # fallen behind.  Final reconciliation remains complete.
                    ready_windows.pop(0)
                if primary_stalled() and available_reserve_pipelines:
                    active_pipeline = available_reserve_pipelines.pop(0)
                elif available_pipelines:
                    active_pipeline = available_pipelines.pop(0)
                else:
                    break
                window, payload_timestamp_ms = ready_windows.pop(0)
                in_flight.append((
                    payload_timestamp_ms,
                    active_pipeline,
                    asyncio.create_task(infer_payload(active_pipeline, window, payload_timestamp_ms)),
                    perf_counter(),
                ))

        def enqueue(window: np.ndarray, payload_timestamp_ms: int) -> None:
            ready_windows.append((window, payload_timestamp_ms))
            schedule_available()

        async def wait_for_work_or_audio(next_audio: asyncio.Task[np.ndarray | None]) -> tuple[asyncio.Task[np.ndarray | None], bool]:
            wait_for: set[asyncio.Task[object]] = {next_audio}
            wait_for.update(item[2] for item in in_flight)
            done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)
            await publish_completed(done)
            return next_audio, next_audio in done

        async def flush() -> None:
            while in_flight or ready_windows:
                schedule_available()
                if in_flight:
                    done, _ = await asyncio.wait(
                        [item[2] for item in in_flight],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    await publish_completed(done)

        next_audio = asyncio.create_task(audio_queue.get())
        accepting_audio = True
        while accepting_audio or in_flight or ready_windows:
            if accepting_audio:
                next_audio, audio_ready = await wait_for_work_or_audio(next_audio)
                if not audio_ready:
                    continue
                decoded_waveform = next_audio.result()
                if decoded_waveform is None:
                    accepting_audio = False
                    if len(pending_waveform) >= min_speech_samples:
                        enqueue(pending_waveform.copy(), pending_start_ms)
                    await flush()
                    return
                next_audio = asyncio.create_task(audio_queue.get())
            else:
                await flush()
                return
            if not len(pending_waveform):
                pending_start_ms = timestamp_ms
            pending_waveform = np.concatenate((pending_waveform, decoded_waveform))
            latest_capture_end_ms = pending_start_ms + int(len(pending_waveform) / settings.audio_sample_rate * 1000)
            while len(pending_waveform) >= window_samples:
                window = pending_waveform[:window_samples].copy()
                enqueue(window, pending_start_ms)
                pending_waveform = pending_waveform[step_samples:]
                pending_start_ms += int(step_samples / settings.audio_sample_rate * 1000)
                timestamp_ms = pending_start_ms + int(len(pending_waveform) / settings.audio_sample_rate * 1000)

    worker = asyncio.create_task(process_audio_queue())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("text"):
                if message["text"] == '{"type":"stop"}' or message["text"] == '{"type": "stop"}':
                    await audio_queue.put(None)
                    await worker
                    if settings.ai_mode == "local" and received_waveforms:
                        complete_waveform = np.concatenate(received_waveforms)
                        reconciled = await pipeline_executor.run(
                            FinalReconciler().run,
                            complete_waveform,
                            pipeline.stt,
                            sample_rate=settings.audio_sample_rate,
                            language=None if language == "auto" else language,
                        )
                        final_reconciliation.update({
                            "latency_ms": reconciled.latency_ms,
                            "warnings": reconciled.warnings,
                            "transcript": [{"text": draft.text, "speaker": draft.speaker, "timestamp": draft.timestamp, "start_ms": draft.start_ms, "end_ms": draft.end_ms, "language_code": draft.language_code} for draft in reconciled.transcripts],
                            "live_transcript_count": len(debug_transcripts),
                            "final_transcript_count": len(reconciled.transcripts),
                        })
                        if reconciled.transcripts:
                            with SessionLocal() as session:
                                replace_with_reconciled_transcript(session, consultation_id, reconciled.transcripts)
                    persist_debug_audio()
                    await send_json({"type": "stopped"})
                    return
                continue
            audio = message.get("bytes")
            if not audio:
                continue
            if capture_started_at is None:
                capture_started_at = perf_counter()
            received_audio.extend(audio)
            decoded = decode_audio_payload(audio, encoding=encoding, sample_rate=sample_rate, channels=channels)
            received_waveforms.append(decoded.waveform)
            await audio_queue.put(decoded.waveform)
    except WebSocketDisconnect:
        return
    finally:
        if not worker.done():
            worker.cancel()
        pipeline_executor.close()
        persist_debug_audio()
