"""Measure live-style rolling-window ASR configurations on one fixed WAV."""

import argparse
import json
import sys
import time
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.providers.speech import AudioChunk, FasterWhisperProvider
from app.providers.vad import SileroVoiceActivityDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", default="docs/superpowers/reports/streaming-benchmark.json")
    parser.add_argument("--model", default="small")
    parser.add_argument("--initial-prompt", default="")
    args = parser.parse_args()
    waveform, source_rate = sf.read(args.audio, dtype="float32")
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    if source_rate != 16_000:
        divisor = gcd(source_rate, 16_000)
        waveform = resample_poly(waveform, 16_000 // divisor, source_rate // divisor).astype("float32")
    results = []
    for window_seconds, overlap_seconds in ((1.5, 0.3), (2.0, 0.5), (3.0, 0.75)):
        model = FasterWhisperProvider(model_size=args.model, beam_size=1, initial_prompt=args.initial_prompt or None)
        vad = SileroVoiceActivityDetector()
        window_size = int(window_seconds * 16_000)
        step = window_size - int(overlap_seconds * 16_000)
        accepted_windows = 0
        texts = []
        first_text_audio_ms = None
        first_text_processing_latency = None
        started = time.perf_counter()
        for start in range(0, max(1, len(waveform) - window_size + 1), step):
            end = min(len(waveform), start + window_size)
            chunk = AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=int(start / 16), waveform=waveform[start:end])
            activity = vad.detect(chunk)
            if not activity.has_speech:
                continue
            accepted_windows += 1
            drafts = model.transcribe(chunk)
            if drafts and first_text_audio_ms is None:
                first_text_audio_ms = drafts[0].start_ms
                first_text_processing_latency = time.perf_counter() - started
            texts.extend(draft.text for draft in drafts)
        latency = time.perf_counter() - started
        results.append({
            "window_seconds": window_seconds,
            "overlap_seconds": overlap_seconds,
            "audio_duration_seconds": len(waveform) / 16_000,
            "speech_windows": accepted_windows,
            "first_text_audio_ms": first_text_audio_ms,
            "processing_latency_seconds": latency,
            "first_text_processing_latency_seconds": first_text_processing_latency,
            "finalization_latency_seconds": latency,
            "real_time_factor": latency / max(len(waveform) / 16_000, 0.001),
            "transcript": " ".join(texts),
            "diagnostics": model.last_diagnostics,
        })
    report = {"audio": str(Path(args.audio).resolve()), "model": args.model, "sample_rate": 16_000, "results": results}
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
