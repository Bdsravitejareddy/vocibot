"""Mixed Hindi-English speech: the final transcript and the live preview.

Synthetic conversations with reference transcripts (codemix_cases/, English
words written in English, Hindi in Devanagari) and, optionally, the clinic's
own recordings (no reference: English words recovered vs the audio
translation, fragment lines, live delay).

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/codemix.py --label before --out tmp/analytics/codemix-before.json [--real VB-20261005-QF74KR ...]

Outputs for real recordings contain conversations: keep them out of git.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from transcription_accuracy import accuracy, load_audio, run_final, run_live, words  # noqa: E402

CASES = json.loads((HERE / "codemix_cases" / "cases.json").read_text(encoding="utf-8"))
RECORDINGS = Path.home() / "Library/Application Support/vocibot/recordings"
LATIN = re.compile(r"^[a-z0-9']+$")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def recall(reference: list[str], hypothesis: list[str]) -> float:
    ref, hyp = Counter(reference), Counter(hypothesis)
    return round(sum(min(count, hyp[word]) for word, count in ref.items()) / max(1, sum(ref.values())), 4)


def script_scores(reference: str, hypothesis: str) -> dict:
    ref, hyp = words(reference), words(hypothesis)
    return {"english_recall": recall([w for w in ref if LATIN.match(w)], [w for w in hyp if LATIN.match(w)]),
            "hindi_recall": recall([w for w in ref if DEVANAGARI.search(w)], [w for w in hyp if DEVANAGARI.search(w)])}


def fragments(drafts) -> int:
    return sum(1 for draft in drafts if len(words(draft.text)) <= 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--real", nargs="*", default=[])
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()
    from app.api.audio import build_local_pipeline, restrict_languages

    pipeline = build_local_pipeline()
    restrict_languages(pipeline.stt, {"en", "te", "hi", "ta", "mr", "gu"})
    rows = []
    for case in CASES:
        audio = load_audio(HERE / "codemix_cases" / f"{case['id']}.wav")
        reference = " ".join(text for _, text in case["lines"])
        final = run_final(pipeline, audio)
        row = {"id": case["id"], "final": {**accuracy(reference, final["text"]), **script_scores(reference, final["text"]), "fragments": fragments(final["drafts"]), "seconds": final["seconds"]}, "final_text": final["text"]}
        if not args.skip_live:
            live = run_live(pipeline, audio)
            row["live"] = {**accuracy(reference, live["text"]), **script_scores(reference, live["text"]), "delay_median_s": live["line_delay_median_s"], "delay_p90_s": live["line_delay_p90_s"]}
            row["live_text"] = live["text"]
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.endswith("_text")}), flush=True)
    for code in args.real:
        audio = load_audio(RECORDINGS / f"{code}.flac")
        final = run_final(pipeline, audio)
        translation = [w for w in words(final["translation"]) if LATIN.match(w)]
        hyp = words(final["text"])
        row = {"id": code, "final": {"english_words_recovered": recall(translation, [w for w in hyp if LATIN.match(w)]), "devanagari_words": sum(1 for w in hyp if DEVANAGARI.search(w)),
                                     "latin_words": sum(1 for w in hyp if LATIN.match(w)), "lines": len(final["drafts"]), "fragments": fragments(final["drafts"]), "seconds": final["seconds"]}, "final_text": final["text"]}
        if not args.skip_live:
            live = run_live(pipeline, audio)
            row["live"] = {"english_words_recovered": recall(translation, [w for w in words(live["text"]) if LATIN.match(w)]), "words": len(words(live["text"])), "delay_median_s": live["line_delay_median_s"], "delay_p90_s": live["line_delay_p90_s"]}
            row["live_text"] = live["text"]
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.endswith("_text")}), flush=True)
    synthetic = [row for row in rows if row["id"] in {case["id"] for case in CASES}]
    mean = lambda part, key: round(sum(row[part][key] for row in synthetic) / len(synthetic), 4)  # noqa: E731
    summary = {"label": args.label, "final_word_accuracy": mean("final", "word_accuracy"), "final_english_recall": mean("final", "english_recall"), "final_hindi_recall": mean("final", "hindi_recall"),
               "final_fragments": sum(row["final"]["fragments"] for row in synthetic)}
    if not args.skip_live:
        summary |= {"live_word_accuracy": mean("live", "word_accuracy"), "live_delay_p90_s": max(row["live"]["delay_p90_s"] or 0 for row in synthetic)}
    print("SUMMARY " + json.dumps(summary), flush=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
