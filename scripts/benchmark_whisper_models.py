"""Benchmark faster-whisper models against one fixed control recording.

Example:
  .venv/bin/python scripts/benchmark_whisper_models.py \
    --audio /tmp/vocibot-audio-debug/05ac15b5-7c4a-47f5-8b94-8dae0bc777a9.wav
"""

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import soundfile as sf
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.benchmark_metrics import clinical_entity_recall


REFERENCE = (
    "This is a transcription test. The patient has had a headache for three days. "
    "There is no fever. There is no cough. The patient is taking paracetamol."
)


def words(text: str) -> list[str]:
    return [word.strip(".,!?'").lower() for word in text.split() if word.strip(".,!?'")]


def wer(reference: str, hypothesis: str) -> float:
    expected, actual = words(reference), words(hypothesis)
    row = list(range(len(actual) + 1))
    for index, expected_word in enumerate(expected, 1):
        next_row = [index]
        for actual_index, actual_word in enumerate(actual, 1):
            next_row.append(min(next_row[-1] + 1, row[actual_index] + 1, row[actual_index - 1] + (expected_word != actual_word)))
        row = next_row
    return row[-1] / max(1, len(expected))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True)
    parser.add_argument("--models", nargs="+", default=["small", "medium", "large-v3"])
    parser.add_argument("--output", default="docs/superpowers/reports/whisper-benchmark.json")
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--entity", action="append", default=[], help="Entity label=phrase; may be repeated")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--initial-prompt", default="")
    args = parser.parse_args()

    audio, sample_rate = sf.read(args.audio, dtype="float32")
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    if sample_rate != 16_000:
        from scipy.signal import resample_poly
        from math import gcd
        divisor = gcd(sample_rate, 16_000)
        audio = resample_poly(audio, 16_000 // divisor, sample_rate // divisor).astype("float32")
    duration = len(audio) / 16_000
    results = []
    for model_name in args.models:
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        started = time.perf_counter()
        error = None
        transcript = ""
        diagnostics = []
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(model_name, device="auto", compute_type="int8")
            segments, info = model.transcribe(
                audio,
                beam_size=args.beam_size,
                vad_filter=True,
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                condition_on_previous_text=False,
                **({"initial_prompt": args.initial_prompt} if args.initial_prompt else {}),
            )
            segment_list = list(segments)
            transcript = " ".join(segment.text.strip() for segment in segment_list).strip()
            diagnostics = [{
                "text": segment.text.strip(),
                "start": segment.start,
                "end": segment.end,
                "avg_logprob": getattr(segment, "avg_logprob", None),
                "no_speech_prob": getattr(segment, "no_speech_prob", None),
                "compression_ratio": getattr(segment, "compression_ratio", None),
            } for segment in segment_list]
            language = getattr(info, "language", None)
            language_probability = getattr(info, "language_probability", None)
        except Exception as exc:  # benchmark must report unavailable models explicitly
            error = f"{type(exc).__name__}: {exc}"
            language = None
            language_probability = None
        latency = time.perf_counter() - started
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        results.append({
            "model": model_name,
            "transcript": transcript,
            "latency_seconds": latency,
            "real_time_factor": latency / max(duration, 0.001),
            "max_rss_delta": after - before,
            "word_error_rate": None if error else wer(args.reference, transcript),
            "clinical_entity_recall": None if error else clinical_entity_recall(transcript, dict(item.split("=", 1) for item in args.entity)),
            "language": language,
            "language_probability": language_probability,
            "segments": diagnostics,
            "error": error,
        })

    report = {"audio": str(Path(args.audio).resolve()), "input_sample_rate": sample_rate, "model_sample_rate": 16_000, "duration_seconds": duration, "reference": args.reference, "configuration": {"beam_size": args.beam_size, "initial_prompt": args.initial_prompt, "vad_filter": True, "condition_on_previous_text": False}, "results": results}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
