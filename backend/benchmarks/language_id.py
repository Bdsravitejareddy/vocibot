"""Language identification on the Indian-language dataset plus English clips.

Stage 1 (slow, GPU): Whisper large-v3 language probabilities for each clip,
saved to JSON.  Stage 2 (instant): accuracy for any enabled-language set and
primary-language weighting, from the saved probabilities.

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/language_id.py collect --per-language 100 --out lid.json
    PYTHONPATH=backend .venv/bin/python backend/benchmarks/language_id.py score lid.json --enabled en,te,hi,mr,gu --primary te
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

DATASET = Path.home() / "Desktop" / "Language Detection Dataset"
ENGLISH = [Path.home() / "Desktop" / "voices" / name for name in ("script 1 aud.mp3", "script 2 aud.mp3", "scipt 3 aud.mp3")]
CODES = {"Bengali": "bn", "Gujarati": "gu", "Hindi": "hi", "Kannada": "kn", "Malayalam": "ml", "Marathi": "mr", "Punjabi": "pa", "Tamil": "ta", "Telugu": "te", "Urdu": "ur", "English": "en"}
CLIP_SECONDS = 5.0


def load(path: Path):
    import numpy as np
    import soundfile as sf

    try:
        audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
    except Exception:
        from mlx_whisper.audio import load_audio

        return load_audio(str(path))
    if rate != 16_000:
        audio = np.interp(np.arange(0, len(audio), rate / 16_000), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def collect(args) -> None:
    from app.providers.speech import MlxWhisperProvider

    provider = MlxWhisperProvider(language_id_model="mlx-community/whisper-large-v3-mlx")
    rng = random.Random(7)
    rows = []
    jobs = []
    crops = [float(value) for value in args.crop.split(",")] if args.crop else [None]
    wanted = set(args.languages.split(",")) if args.languages else None
    for folder in sorted(p for p in DATASET.iterdir() if p.is_dir()):
        if wanted and CODES[folder.name] not in wanted:
            continue
        files = sorted(folder.glob("*.mp3"))
        jobs += [(CODES[folder.name], f) for f in rng.sample(files, min(args.per_language, len(files)))]
    def crop(audio, seconds):
        """The middle ``seconds`` of a clip (a short live-preview buffer)."""

        if seconds is None or len(audio) <= seconds * 16_000:
            return audio
        start = (len(audio) - int(seconds * 16_000)) // 2
        return audio[start:start + int(seconds * 16_000)]

    def detect(code, name, audio):
        for seconds in crops:
            piece = crop(audio, seconds)
            rows.append({"language": code, "clip": name, "seconds": round(len(piece) / 16_000, 2), "probabilities": {k: round(v, 5) for k, v in provider.detect_language_probabilities(piece).items() if v >= 1e-4}})

    for index, (code, path) in enumerate(jobs):
        detect(code, path.name, load(path))
        if index % 50 == 0:
            print(f"{index}/{len(jobs)}", flush=True)
    if not wanted or "en" in wanted:
        english = 0
        for path in ENGLISH:
            audio = load(path)
            step = int(CLIP_SECONDS * 16_000)
            for start in range(0, len(audio) - step, step):
                if english >= args.per_language:
                    break
                detect("en", f"{path.name}@{start // 16_000}s", audio[start:start + step])
                english += 1
    Path(args.out).write_text(json.dumps(rows))
    print(f"saved {len(rows)} clips to {args.out}")


def score_rows(rows, enabled: set[str] | None, primary: str | None, weight: float) -> dict[str, tuple[int, int]]:
    from app.providers.speech import choose_language

    results: dict[str, list[int]] = {}
    for row in rows:
        if enabled and row["language"] not in enabled:
            continue
        probabilities = row["probabilities"]
        if enabled:
            chosen = choose_language(probabilities, enabled, primary=primary, primary_weight=weight)
        else:
            chosen = max(probabilities, key=probabilities.get)
        hit = results.setdefault(row["language"], [0, 0])
        hit[0] += chosen == row["language"]
        hit[1] += 1
    return {code: (hits, total) for code, (hits, total) in results.items()}


def score(args) -> None:
    rows = json.loads(Path(args.file).read_text())
    if args.seconds:
        rows = [row for row in rows if abs(row["seconds"] - args.seconds) < 0.05]
    enabled = set(args.enabled.split(",")) if args.enabled else None
    for weight in [float(w) for w in args.weights.split(",")]:
        result = score_rows(rows, enabled, args.primary, weight)
        hits = sum(h for h, _ in result.values())
        total = sum(t for _, t in result.values())
        print(f"weight {weight}: overall {hits}/{total} = {hits / total:.1%}  " + "  ".join(f"{code} {h}/{t}={h / t:.0%}" for code, (h, t) in sorted(result.items())))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("collect")
    c.add_argument("--per-language", type=int, default=100)
    c.add_argument("--out", required=True)
    c.add_argument("--crop", default="", help="comma-separated seconds, e.g. 1.5,3 (default: whole clip)")
    c.add_argument("--languages", default="", help="comma-separated codes (default: all)")
    s = commands.add_parser("score")
    s.add_argument("file")
    s.add_argument("--enabled", default="")
    s.add_argument("--primary")
    s.add_argument("--weights", default="1")
    s.add_argument("--seconds", type=float, help="score only clips of this length")
    args = parser.parse_args()
    {"collect": collect, "score": score}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
