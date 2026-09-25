from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import settings
from ..providers.alignment import WhisperXAligner
from ..providers.diarization import PyannoteDiarizationProvider
from ..providers.local_pipeline import LocalAudioPipeline
from ..providers.speech import AudioChunk, FasterWhisperProvider
from ..providers.vad import SileroVoiceActivityDetector

router = APIRouter(tags=["audio"])


def build_local_pipeline() -> LocalAudioPipeline:
    return LocalAudioPipeline(
        SileroVoiceActivityDetector(threshold=settings.silero_threshold),
        FasterWhisperProvider(model_size=settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type),
        WhisperXAligner(model_name=settings.whisperx_model),
        PyannoteDiarizationProvider(model_name=settings.pyannote_model),
    )


@router.websocket("/api/consultations/{consultation_id}/audio")
async def audio_stream(websocket: WebSocket, consultation_id: str) -> None:
    await websocket.accept()
    try:
        metadata = await websocket.receive_json()
        sample_rate = int(metadata.get("sample_rate", settings.audio_sample_rate))
        channels = int(metadata.get("channels", 1))
        pipeline = build_local_pipeline()
    except Exception as error:
        await websocket.send_json({"type": "error", "category": "INITIALIZATION", "message": str(error)})
        return
    await websocket.send_json({"type": "ready", "consultation_id": consultation_id, "sample_rate": sample_rate, "channels": channels})
    timestamp_ms = 0
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if message.get("text"):
                if message["text"] == '{"type":"stop"}' or message["text"] == '{"type": "stop"}':
                    await websocket.send_json({"type": "stopped"})
                    return
                continue
            audio = message.get("bytes")
            if not audio:
                continue
            chunk = AudioChunk(audio=audio, sample_rate=sample_rate, timestamp_ms=timestamp_ms)
            try:
                result = pipeline.process(chunk)
            except Exception as error:
                await websocket.send_json({"type": "error", "category": "PIPELINE", "message": str(error)})
                continue
            await websocket.send_json({"type": "status", "timings": result.timings})
            for warning in result.warnings:
                await websocket.send_json({"type": "warning", "category": warning.category, "message": warning.message})
            for index, draft in enumerate(result.transcripts):
                await websocket.send_json({"type": "transcript", "id": f"local-{timestamp_ms}-{index}", "text": draft.text, "speaker": draft.speaker, "timestamp": draft.timestamp, "start_ms": draft.start_ms, "end_ms": draft.end_ms, "sequence_number": index})
            timestamp_ms += int(len(audio) / max(1, channels) / 4 / sample_rate * 1000)
    except WebSocketDisconnect:
        return
