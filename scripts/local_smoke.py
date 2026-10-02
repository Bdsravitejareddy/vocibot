from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.providers.alignment import WhisperXAligner  # noqa: E402
from app.providers.diarization import PyannoteDiarizationProvider  # noqa: E402
from app.providers.local_pipeline import LocalAudioPipeline  # noqa: E402
from app.providers.speech import AudioChunk, FasterWhisperProvider  # noqa: E402
from app.providers.vad import SileroVoiceActivityDetector  # noqa: E402
from app.domain.types import ClinicalRecord, Speaker, TranscriptSegmentInput  # noqa: E402
from app.providers.ollama_extraction import OllamaClinicalExtractionProvider  # noqa: E402
from app.services.evidence import EvidenceValidator  # noqa: E402
from app.services.diagnostics import MockEMRUpdater  # noqa: E402
from app.services.smoke import build_report, run_mock_emr_flow  # noqa: E402


def hardware() -> dict[str, Any]:
    machine = platform.machine()
    result: dict[str, Any] = {"architecture": "Apple Silicon" if machine == "arm64" else "Intel/other", "machine": platform.platform()}
    try:
        output = subprocess.check_output(["system_profiler", "SPHardwareDataType"], text=True, stderr=subprocess.DEVNULL)
        for line in output.splitlines():
            if "Chip:" in line or "Memory:" in line or "Model Name:" in line:
                key, value = line.strip().split(":", 1)
                result[key.lower().replace(" ", "_")] = value.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def read_chunks(path: Path, chunk_ms: int = 1000):
    try:
        import soundfile as sf
    except ImportError as error:
        raise RuntimeError(f"soundfile is required to read float32 WAV input: {error}") from error
    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if int(sample_rate) != settings.audio_sample_rate:
        from scipy.signal import resample_poly
        samples = resample_poly(samples, settings.audio_sample_rate, int(sample_rate), axis=0).astype("float32")
        sample_rate = settings.audio_sample_rate
    channels = samples.shape[1]
    frames = max(1, int(sample_rate * chunk_ms / 1000))
    offset = 0
    for start in range(0, len(samples), frames):
        data = samples[start:start + frames]
        if len(data) == 0:
            continue
        yield AudioChunk(audio=data.tobytes(), sample_rate=int(sample_rate), timestamp_ms=offset)
        offset += int(len(data) / max(1, channels) / 4 / sample_rate * 1000)


def component_probe() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for name, loader in (
        ("silero_vad", lambda: SileroVoiceActivityDetector()),
        ("whisper", lambda: FasterWhisperProvider(model_size=settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)),
        ("whisperx", lambda: WhisperXAligner(model_name=settings.whisperx_model) if settings.whisperx_enabled else None),
        ("pyannote", lambda: PyannoteDiarizationProvider(model_name=settings.pyannote_model) if settings.diarization_enabled else None),
    ):
        try:
            loader()
            statuses[name] = "disabled by configuration" if ((name == "whisperx" and not settings.whisperx_enabled) or (name == "pyannote" and not settings.diarization_enabled)) else "configured (lazy; not executed)"
        except Exception as error:
            statuses[name] = f"unavailable: {error}"
    try:
        import httpx
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3)
        response.raise_for_status()
        statuses["ollama"] = f"reachable ({settings.ollama_model})"
    except Exception as error:
        statuses["ollama"] = f"unavailable: {error}"
    return statuses


def run(audio_path: Path) -> dict[str, Any]:
    report = build_report(hardware(), {"whisper_model": settings.whisper_model, "ollama_model": settings.ollama_model}, component_probe())
    report["input_audio"] = str(audio_path)
    vad = SileroVoiceActivityDetector(threshold=settings.silero_threshold)
    stt = FasterWhisperProvider(model_size=settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute_type)
    pipeline = LocalAudioPipeline(vad, stt, WhisperXAligner(settings.whisperx_model) if settings.whisperx_enabled else None, PyannoteDiarizationProvider(model_name=settings.pyannote_model) if settings.diarization_enabled else None)
    transcripts = []
    for chunk in read_chunks(audio_path):
        started = time.perf_counter()
        try:
            result = pipeline.process(chunk)
            report["latency_ms"].update({key: round(value, 2) for key, value in result.timings.items()})
            report["warnings"] = [warning.__dict__ for warning in result.warnings]
            transcripts.extend(result.transcripts)
        except Exception as error:
            report["errors"].append({"category": "PIPELINE", "message": str(error), "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
            break
    report["components"]["silero_vad"] = "executed" if "vad_ms" in report["latency_ms"] else report["components"]["silero_vad"]
    report["components"]["whisper"] = "executed" if "transcription_ms" in report["latency_ms"] else report["components"]["whisper"]
    report["components"]["whisperx"] = "disabled by configuration" if not settings.whisperx_enabled else report["components"]["whisperx"]
    report["components"]["pyannote"] = "disabled by configuration" if not settings.diarization_enabled else report["components"]["pyannote"]
    report["transcript_count"] = len(transcripts)
    extraction_record = ClinicalRecord()
    if transcripts:
        extraction_started = time.perf_counter()
        transcript_inputs = [TranscriptSegmentInput(id=f"local-{index}", speaker=Speaker(draft.speaker) if draft.speaker in Speaker else Speaker.UNKNOWN, text=draft.text, timestamp=datetime.now(timezone.utc).isoformat(), sequence_number=index) for index, draft in enumerate(transcripts)]
        try:
            extraction = OllamaClinicalExtractionProvider().extract(transcript_inputs, extraction_record)
            report["latency_ms"]["extraction_ms"] = round((time.perf_counter() - extraction_started) * 1000, 2)
            validator = EvidenceValidator()
            for candidate in extraction.candidates:
                validated = validator.validate(candidate.field_name, candidate.value, candidate.source_segment_ids, transcript_inputs)
                if validated.status.value == "REJECTED":
                    report["unsupported_facts"].append({"field": candidate.field_name, "value": candidate.value, "source_segment_ids": candidate.source_segment_ids})
                elif validated.status.value == "NEEDS_REVIEW":
                    report.setdefault("needs_review", []).append({"field": candidate.field_name, "value": candidate.value})
                elif hasattr(extraction_record, candidate.field_name):
                    setattr(extraction_record, candidate.field_name, candidate.value)
        except Exception as error:
            report["errors"].append({"category": "EXTRACTION", "message": str(error)})
    else:
        report["omissions"].append("No speech transcript was produced from the supplied audio")
    if transcripts and all(len(draft.text.split()) < 3 for draft in transcripts):
        report["omissions"].append("The available audio fixture was not a full spoken consultation; transcription was too short to validate English clinical coverage")
    report["mock_flow"] = run_mock_emr_flow(MockEMRUpdater(), extraction_record.model_dump())
    report["persistence_flow"] = _run_persistence_flow(transcripts, extraction_record.model_dump(), report)
    report["transcripts"] = [draft.__dict__ for draft in transcripts]
    return report


def _run_persistence_flow(transcripts, record: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            created = client.post("/api/consultations", json={"patient_id": f"SMOKE-{int(time.time())}", "patient_name": "Local smoke", "age": 42, "sex": "Prefer not to say"}).json()
            for index, draft in enumerate(transcripts):
                client.post(f"/api/consultations/{created['id']}/segments", json={"id": f"smoke-{created['id']}-{index}", "speaker": draft.speaker if draft.speaker in {"DOCTOR", "PATIENT", "UNKNOWN"} else "UNKNOWN", "text": draft.text, "timestamp": datetime.now(timezone.utc).isoformat(), "sequence_number": index})
            client.post(f"/api/consultations/{created['id']}/stop")
            editable = client.get(f"/api/consultations/{created['id']}").json()["record"]
            editable["chief_complaint"] = editable.get("chief_complaint") or "Doctor-reviewed smoke note"
            approved = client.post(f"/api/consultations/{created['id']}/approve", json={"record": editable}).json()
            reopened = client.get(f"/api/consultations/{created['id']}").json()
            return {"approved_status": approved["status"], "reopened_status": reopened["status"], "consultation_id": created["id"]}
    except Exception as error:
        report["errors"].append({"category": "PERSISTENCE", "message": str(error)})
        return {"error": str(error)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VociBot local model smoke test")
    parser.add_argument("--audio", type=Path, required=True, help="32-bit float PCM WAV fixture or microphone capture")
    parser.add_argument("--mode", choices=("demo", "local"), default="local")
    args = parser.parse_args()
    if args.mode != settings.ai_mode:
        print(f"WARNING: requested --mode={args.mode}, but AI_MODE={settings.ai_mode}; local adapters are still exercised", file=sys.stderr)
    report = run(args.audio)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    output = ROOT / "docs/superpowers/reports/2026-09-26-vocibot-local-smoke.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Report written to {output}")


if __name__ == "__main__":
    main()
