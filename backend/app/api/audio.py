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
from concurrent.futures import ThreadPoolExecutor

from ..providers.reconciliation import FinalReconciler, IncrementalReconciler
from ..providers.speech import AudioChunk, TranscriptDraft
from ..providers.streaming import TranscriptCommitter, select_live_commits
from ..db import SessionLocal
from ..languages import enabled_languages, primary_language
from ..services.consultations import replace_with_reconciled_transcript
from ..services.live_cpu import LocalPipelineExecutor
from ..services.recordings import SessionRecorder, compress_soon, recording_path
from ..models import Consultation, Recording
from ..learning.scheduler import consultation_in_progress
from ..providers.vad import SileroVoiceActivityDetector

router = APIRouter(tags=["audio"])
logger = logging.getLogger(__name__)
def restrict_languages(stt, allowed: set[str], primary: str | None = None) -> None:
    if stt is not None and hasattr(stt, "allowed_languages"):
        stt.allowed_languages = set(allowed)
        stt.primary_language = primary if primary in allowed else None


def session_languages() -> set[str]:
    """The languages enabled in Settings; auto-detect chooses only among these."""

    with SessionLocal() as session:
        return set(enabled_languages(session))


def session_primary_language() -> str | None:
    with SessionLocal() as session:
        return primary_language(session)


def build_local_pipeline() -> LocalAudioPipeline:
    return LocalAudioPipeline(
        SileroVoiceActivityDetector(threshold=settings.silero_threshold),
        build_speech_provider(settings),
        WhisperXAligner(model_name=settings.whisperx_model) if settings.whisperx_enabled else None,
        PyannoteDiarizationProvider(model_name=settings.pyannote_model) if settings.diarization_enabled else None,
        # Whisper pads the last segment of a rolling buffer slightly past its
        # end; clip that instead of rejecting the segment.
        timestamp_tolerance_ms=1_000,
        max_trailing_overshoot_ms=3_000,
    )


# New audio between attempts to process completed final-pass pieces.
ADVANCE_EVERY_SECONDS = 5


def _advance_quietly(incremental: IncrementalReconciler, waveform: np.ndarray, consultation_id: str) -> None:
    """A failure here only means the piece is done after Stop instead."""

    try:
        incremental.advance(waveform)
    except Exception:
        logger.exception("Final pass during the consultation failed for %s; it will finish after Stop", consultation_id)


def persist_reconciled_transcript(consultation_id: str, transcripts: list[TranscriptDraft], translations: list[TranscriptDraft] | None = None) -> None:
    """Create and use the database session on the executor thread."""

    with SessionLocal() as session:
        replace_with_reconciled_transcript(session, consultation_id, transcripts, extract=False, translations=translations)


@router.websocket("/api/consultations/{consultation_id}/audio")
async def audio_stream(websocket: WebSocket, consultation_id: str) -> None:
    # The nightly learning cycle waits while any consultation is recording.
    with consultation_in_progress():
        await _audio_stream(websocket, consultation_id)


async def _audio_stream(websocket: WebSocket, consultation_id: str) -> None:
    await websocket.accept()
    # One model and one in-flight pass per consultation: the rolling buffer
    # always transcribes the newest audio, so extra workers only add latency
    # contention and memory.
    pipeline_executor = LocalPipelineExecutor(workers=1)
    try:
        metadata = await websocket.receive_json()
        sample_rate = int(metadata.get("sample_rate", settings.audio_sample_rate))
        channels = int(metadata.get("channels", 1))
        encoding = str(metadata.get("encoding", "pcm_f32le"))
        mime_type = str(metadata.get("mime_type", "audio/raw"))
        language = str(metadata.get("language", "auto")).lower()
        allowed = session_languages()
        if language != "auto" and language not in allowed:
            await websocket.send_json({"type": "error", "category": "INITIALIZATION", "message": f"Unsupported language code: {language}. Enable it in Settings first."})
            await websocket.close(code=1008)
            return
        if settings.ai_mode == "local" and settings.stt_provider == "indic_conformer" and language == "auto":
            await websocket.send_json({"type": "error", "category": "INITIALIZATION", "message": "Select a language before using IndicConformer; automatic language detection is unavailable for this engine."})
            await websocket.close(code=1008)
            return
        pipeline = build_local_pipeline()
        restrict_languages(getattr(pipeline, "stt", None), allowed, session_primary_language())
        warmup = getattr(pipeline, "warmup", None)
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
    received_audio = bytearray()
    recorder: SessionRecorder | None = None
    recording_checked = False

    def start_recording() -> SessionRecorder | None:
        """Keep the consultation's audio; unknown consultations are not recorded."""

        with SessionLocal() as session:
            consultation = session.get(Consultation, consultation_id)
            if consultation is None:
                return None
            return SessionRecorder(recording_path(consultation.session_code), settings.audio_sample_rate)

    def finish_recording() -> None:
        nonlocal recorder
        if recorder is None:
            return
        active, recorder = recorder, None
        try:
            finished = active.close()
            with SessionLocal() as session:
                session.add(Recording(consultation_id=consultation_id, file_path=str(finished.path), duration_ms=finished.duration_ms, sample_rate=active.sample_rate, language_code=None if language == "auto" else language, sha256=finished.sha256, original_sha256=finished.sha256, format="wav", size_bytes=finished.path.stat().st_size))
                session.commit()
            # Lossless FLAC conversion runs off the request path.
            compress_soon()
        except Exception:
            logger.exception("Saving the recording failed for consultation %s", consultation_id)
    debug_windows: list[dict[str, object]] = []
    debug_transcripts: list[dict[str, object]] = []
    received_waveforms: list[np.ndarray] = []
    # The final pass runs piece by piece during the consultation on its own
    # thread, so at Stop only the last piece is left.
    incremental = IncrementalReconciler(pipeline.stt, sample_rate=settings.audio_sample_rate, language=None if language == "auto" else language) if settings.ai_mode == "local" and getattr(pipeline, "stt", None) is not None else None
    finalizer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vocibot-final")
    advance_job: asyncio.Future | None = None
    received_samples = 0
    samples_at_last_advance = 0
    final_reconciliation: dict[str, object] = {}
    capture_started_at: float | None = None
    first_text_latency_ms: float | None = None
    latest_capture_end_ms = 0

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
            "out_of_order_live_segments": committer.out_of_order_count,
            **audio_metrics(debug_audio.waveform, sample_rate=debug_audio.sample_rate),
        }
        (debug_dir / f"{consultation_id}.json").write_text(json.dumps(debug_report, indent=2) + "\n")
        logger.info("Audio debug artifact %s", json.dumps(debug_report, sort_keys=True))
    sample_rate_hz = settings.audio_sample_rate
    step_samples = max(1, int(settings.asr_live_step_seconds * sample_rate_hz))
    min_speech_samples = max(1, int(settings.asr_min_speech_seconds * sample_rate_hz))
    holdback_ms = int(settings.asr_live_holdback_seconds * 1000)
    max_buffer_ms = int(settings.asr_live_max_buffer_seconds * 1000)
    committer = TranscriptCommitter()
    audio_queue: asyncio.Queue[np.ndarray | None] = asyncio.Queue()
    send_lock = asyncio.Lock()

    async def send_json(message: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(message)

    async def infer_payload(waveform: np.ndarray, payload_timestamp_ms: int) -> object | None:
        duration_ms = int(len(waveform) / sample_rate_hz * 1000)
        try:
            chunk = AudioChunk(audio=b"", sample_rate=sample_rate_hz, timestamp_ms=payload_timestamp_ms, encoding="pcm_f32le", channels=1, waveform=waveform, live=True)
            result = await pipeline_executor.run(pipeline.process, chunk, language=None if language == "auto" else language)
            logger.info(
                "ASR live buffer consultation=%s start_ms=%s end_ms=%s timings=%s diagnostics=%s",
                consultation_id,
                payload_timestamp_ms,
                payload_timestamp_ms + duration_ms,
                result.timings,
                result.diagnostics,
            )
            debug_windows.append({
                "start_ms": payload_timestamp_ms,
                "end_ms": payload_timestamp_ms + duration_ms,
                "audio": audio_metrics(waveform, sample_rate=sample_rate_hz),
                "timings": result.timings,
                "diagnostics": result.diagnostics,
                "warnings": [warning.message for warning in result.warnings],
            })
        except Exception:
            logger.exception(
                "Local audio pipeline failed for consultation %s: encoding=%s mime_type=%s sample_rate=%s channels=%s samples=%s",
                consultation_id,
                encoding,
                mime_type,
                sample_rate,
                channels,
                len(waveform),
            )
            await send_json({"type": "error", "category": "PIPELINE", "message": "Local microphone audio could not be processed. See backend logs for details."})
            return None
        return result

    async def publish_result(buffer_start_ms: int, buffer_end_ms: int, result: object | None) -> int | None:
        """Publish settled segments and return the capture time they settle."""

        nonlocal transcript_sequence, first_text_latency_ms
        if result is None:
            return None
        await send_json({"type": "status", "timings": result.timings, "diagnostics": result.diagnostics})
        for warning in result.warnings:
            if warning.category in {"ALIGNMENT_DISABLED", "DIARIZATION_DISABLED", "VAD_REJECTION", "TIMESTAMP_REJECTED"}:
                continue
            await send_json({"type": "warning", "category": warning.category, "message": warning.message})
        decision = select_live_commits(
            result.transcripts,
            buffer_start_ms=buffer_start_ms,
            buffer_end_ms=buffer_end_ms,
            holdback_ms=holdback_ms,
            max_buffer_ms=max_buffer_ms,
        )
        for draft in committer.add(decision.committed):
            if first_text_latency_ms is None and capture_started_at is not None:
                first_text_latency_ms = (perf_counter() - capture_started_at) * 1000
            debug_transcripts.append({"text": draft.text, "speaker": draft.speaker, "timestamp": draft.timestamp, "start_ms": draft.start_ms, "end_ms": draft.end_ms, "language_code": draft.language_code})
            await send_json({"type": "transcript", "id": f"local-{transcript_sequence}-{draft.start_ms}", "text": draft.text, "speaker": draft.speaker, "timestamp": draft.timestamp, "start_ms": draft.start_ms, "end_ms": draft.end_ms, "sequence_number": transcript_sequence, "language_code": draft.language_code})
            transcript_sequence += 1
        tentative_text = " ".join(draft.text.strip() for draft in decision.tentative).strip()
        await send_json({"type": "partial", "text": tentative_text, "start_ms": decision.tentative[0].start_ms if decision.tentative else None})
        if decision.commit_until_ms is not None:
            return decision.commit_until_ms
        no_speech = result.diagnostics.get("accepted") is False
        if not result.transcripts and buffer_end_ms - buffer_start_ms > holdback_ms and (no_speech or buffer_end_ms - buffer_start_ms >= 2 * max_buffer_ms):
            # Silence (per VAD), or speech the decoder could not transcribe
            # confidently for a whole buffer: keep only the trailing holdback
            # so a word that is just starting is still heard next step.  A
            # low-confidence pass over real speech is retried with more context.
            return buffer_end_ms - holdback_ms
        return None

    async def process_audio_queue() -> None:
        """Re-transcribe the unsettled audio buffer, always on the newest audio.

        Exactly one inference runs at a time.  Audio that arrives meanwhile is
        appended to the buffer and included in the next pass, so the live
        preview cannot fall behind real time no matter how slow a pass is.
        """

        nonlocal latest_capture_end_ms
        buffer = np.empty(0, dtype=np.float32)
        buffer_start_ms = 0
        samples_at_last_pass = 0
        in_flight: asyncio.Task[object | None] | None = None
        in_flight_span: tuple[int, int] = (0, 0)
        next_audio: asyncio.Task[np.ndarray | None] = asyncio.create_task(audio_queue.get())

        def maybe_start_pass() -> None:
            nonlocal in_flight, in_flight_span, samples_at_last_pass
            if in_flight is not None or len(buffer) < min_speech_samples:
                return
            if len(buffer) - samples_at_last_pass < step_samples:
                return
            samples_at_last_pass = len(buffer)
            end_ms = buffer_start_ms + int(len(buffer) / sample_rate_hz * 1000)
            in_flight_span = (buffer_start_ms, end_ms)
            in_flight = asyncio.create_task(infer_payload(buffer.copy(), buffer_start_ms))

        try:
            while True:
                wait_for: set[asyncio.Task[object]] = {next_audio}
                if in_flight is not None:
                    wait_for.add(in_flight)
                done, _ = await asyncio.wait(wait_for, return_when=asyncio.FIRST_COMPLETED)
                if in_flight is not None and in_flight in done:
                    result = in_flight.result()
                    in_flight = None
                    settled_ms = await publish_result(*in_flight_span, result)
                    if settled_ms is not None and settled_ms > buffer_start_ms:
                        drop = min(len(buffer), int((settled_ms - buffer_start_ms) / 1000 * sample_rate_hz))
                        buffer = buffer[drop:]
                        buffer_start_ms += int(drop / sample_rate_hz * 1000)
                        samples_at_last_pass = max(0, samples_at_last_pass - drop)
                if next_audio in done:
                    decoded_waveform = next_audio.result()
                    if decoded_waveform is None:
                        # Stop: the authoritative full-recording pass replaces
                        # the live preview, so only let a running pass finish.
                        if in_flight is not None:
                            await in_flight
                        return
                    buffer = np.concatenate((buffer, decoded_waveform))
                    latest_capture_end_ms = buffer_start_ms + int(len(buffer) / sample_rate_hz * 1000)
                    next_audio = asyncio.create_task(audio_queue.get())
                maybe_start_pass()
        finally:
            if not next_audio.done():
                next_audio.cancel()

    worker = asyncio.create_task(process_audio_queue())
    wait_for_executor_shutdown = True
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("text"):
                if message["text"] == '{"type":"stop"}' or message["text"] == '{"type": "stop"}':
                    reconciled = None
                    try:
                        # Non-English consultations are also translated (~1/3 of
                        # the recording's length), so allow for long recordings.
                        recorded_seconds = sum(len(waveform) for waveform in received_waveforms) / settings.audio_sample_rate
                        async with asyncio.timeout(settings.asr_finalization_timeout_seconds * max(1.0, recorded_seconds / 180)):
                            await audio_queue.put(None)
                            await worker
                            if settings.ai_mode == "local" and received_waveforms:
                                complete_waveform = np.concatenate(received_waveforms)
                                if advance_job is not None:
                                    await advance_job  # a piece being processed during the consultation
                                if incremental is not None:
                                    reconciled = await asyncio.get_running_loop().run_in_executor(finalizer, incremental.finish, complete_waveform)
                                else:
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
                    except TimeoutError:
                        # A native inference call cannot be killed safely from
                        # Python. Acknowledge Stop and do not wait for that
                        # worker during cleanup; the process stays responsive.
                        wait_for_executor_shutdown = False
                        final_reconciliation["error"] = "finalization_timeout"
                        logger.error("Final audio reconciliation timed out for consultation %s", consultation_id)
                        await send_json({"type": "warning", "category": "FINALIZATION", "message": "Final transcription took too long. The captured live preview remains available for review."})
                    except Exception as error:
                        logger.exception("Final audio reconciliation failed for consultation %s", consultation_id)
                        final_reconciliation["error"] = str(error)
                        await send_json({"type": "warning", "category": "FINALIZATION", "message": "Final transcription could not replace the live preview. The captured preview remains available for review."})
                    if reconciled is not None:
                        for warning in reconciled.warnings:
                            await send_json({"type": "warning", "category": "FINALIZATION", "message": warning})
                        if not reconciled.transcripts:
                            await send_json({"type": "warning", "category": "FINALIZATION", "message": "No reliable final transcript was produced. The captured live preview remains available for review."})
                        else:
                            try:
                                # This transaction only replaces transcript rows;
                                # slow local-LLM extraction runs later via /stop.
                                persist_reconciled_transcript(consultation_id, reconciled.transcripts, reconciled.translations)
                            except Exception as error:
                                logger.exception("Final transcript persistence failed for consultation %s", consultation_id)
                                final_reconciliation["error"] = str(error)
                                await send_json({"type": "warning", "category": "FINALIZATION", "message": "Final transcription could not replace the live preview. The captured preview remains available for review."})
                    persist_debug_audio()
                    finish_recording()
                    await send_json({"type": "stopped"})
                    return
                continue
            audio = message.get("bytes")
            if not audio:
                continue
            if capture_started_at is None:
                capture_started_at = perf_counter()
            if settings.audio_debug_dir:
                received_audio.extend(audio)
            decoded = decode_audio_payload(audio, encoding=encoding, sample_rate=sample_rate, channels=channels)
            received_waveforms.append(decoded.waveform)
            received_samples += len(decoded.waveform)
            if incremental is not None and (advance_job is None or advance_job.done()) and received_samples - samples_at_last_advance >= ADVANCE_EVERY_SECONDS * settings.audio_sample_rate:
                samples_at_last_advance = received_samples
                advance_job = asyncio.get_running_loop().run_in_executor(finalizer, _advance_quietly, incremental, np.concatenate(received_waveforms), consultation_id)
            if not recording_checked:
                recording_checked = True
                try:
                    recorder = start_recording()
                except Exception:
                    logger.exception("Starting the recording failed for consultation %s", consultation_id)
            if recorder is not None:
                recorder.write(decoded.waveform)
            await audio_queue.put(decoded.waveform)
    except WebSocketDisconnect:
        return
    finally:
        if not worker.done():
            worker.cancel()
        pipeline_executor.close(wait=wait_for_executor_shutdown)
        finalizer.shutdown(wait=False, cancel_futures=True)
        persist_debug_audio()
        finish_recording()
