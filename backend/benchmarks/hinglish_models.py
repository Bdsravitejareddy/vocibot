"""Whisper models trained on mixed Hindi-English speech, on the code-mix test
conversations (reference transcripts) and optionally the clinic's recordings.

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/hinglish_models.py ~/vocibot-models/zero-stt-hinglish --out tmp/analytics/hinglish-shunya.json [--real VB-...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from codemix import CASES, DEVANAGARI, LATIN, RECORDINGS, recall, script_scores  # noqa: E402
from transcription_accuracy import accuracy, load_audio, words  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--out", required=True)
    parser.add_argument("--real", nargs="*", default=[])
    parser.add_argument("--language", default=None, help="force a decoder language token, e.g. hi")
    args = parser.parse_args()
    import torch
    from transformers import pipeline

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    asr = pipeline("automatic-speech-recognition", model=args.model, device=device, torch_dtype=torch.float32)
    options = {"task": "transcribe", **({"language": args.language} if args.language else {})}
    rows = []
    for case in CASES:
        audio = load_audio(HERE / "codemix_cases" / f"{case['id']}.wav")
        reference = " ".join(text for _, text in case["lines"])
        started = time.perf_counter()
        text = asr({"raw": audio, "sampling_rate": 16_000}, return_timestamps=True, generate_kwargs=options)["text"]
        rows.append({"id": case["id"], **accuracy(reference, text), **script_scores(reference, text), "seconds": round(time.perf_counter() - started, 1), "text": text})
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "text"}), flush=True)
    for code in args.real:
        audio = load_audio(RECORDINGS / f"{code}.flac")
        started = time.perf_counter()
        text = asr({"raw": audio, "sampling_rate": 16_000}, return_timestamps=True, generate_kwargs=options)["text"]
        hyp = words(text)
        rows.append({"id": code, "latin_words": sum(1 for w in hyp if LATIN.match(w)), "devanagari_words": sum(1 for w in hyp if DEVANAGARI.search(w)), "seconds": round(time.perf_counter() - started, 1), "text": text})
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "text"}), flush=True)
    synthetic = [row for row in rows if "word_accuracy" in row]
    summary = {"model": Path(args.model).name, "word_accuracy": round(sum(r["word_accuracy"] for r in synthetic) / len(synthetic), 4),
               "english_recall": round(sum(r["english_recall"] for r in synthetic) / len(synthetic), 4), "hindi_recall": round(sum(r["hindi_recall"] for r in synthetic) / len(synthetic), 4)}
    print("SUMMARY " + json.dumps(summary), flush=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
