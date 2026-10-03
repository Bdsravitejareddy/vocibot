"""Score a note model on the clinical benchmark cases.

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/note_quality.py --model qwen2.5:7b [--cpu-only] [--threads 4]

Reports, per case and overall: expected facts captured (after evidence
checking, exactly as the app fills the form), "must not" violations,
seconds per note, prompt/answer token speed and the model's memory.
"""

import argparse
import json
from pathlib import Path
import time

import httpx

from app.config import settings
from app.domain.types import ClinicalRecord, TranscriptSegmentInput
from app.providers.ollama_extraction import OllamaClinicalExtractionProvider
from app.services.consultations import _apply_validated_candidates
from app.services.speaker_roles import SpeakerRoleLabeler

CASES = json.loads((Path(__file__).parent / "clinical_note_cases.json").read_text())


def field_text(value) -> str:
    if isinstance(value, list):
        return " | ".join(map(str, value)).lower()
    if isinstance(value, dict):
        return " | ".join(f"{k} {v}" for k, v in value.items()).lower()
    return str(value or "").lower()


def score(case: dict, record: ClinicalRecord) -> dict:
    data = record.model_dump()
    hits, misses, violations = 0, [], []
    for field, facts in case["expected"].items():
        text = field_text(data.get(field))
        for alternatives in facts:
            if any(term in text for term in alternatives):
                hits += 1
            else:
                misses.append(f"{field}:{alternatives[0]}")
    for field, terms in case.get("must_not", {}).items():
        text = field_text(data.get(field))
        violations += [f"{field}:{term}" for term in terms if term in text]
    total = sum(len(facts) for facts in case["expected"].values())
    return {"hits": hits, "total": total, "misses": misses, "violations": violations}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--out")
    parser.add_argument("--roles", action="store_true", help="label lines doctor/patient first, as the app does")
    args = parser.parse_args()
    settings.ollama_num_gpu = 0 if args.cpu_only else -1
    settings.ollama_num_thread = args.threads
    settings.ollama_timeout_seconds = 1800
    provider = OllamaClinicalExtractionProvider(model=args.model)
    # Unload every other model so memory is measured for this one alone.
    for other in httpx.get(f"{settings.ollama_base_url}/api/ps").json().get("models", []):
        httpx.post(f"{settings.ollama_base_url}/api/generate", json={"model": other["name"], "keep_alive": 0}, timeout=60)
    # Warm-up loads the model so timings below are steady-state.
    warm = [TranscriptSegmentInput(id="w0", speaker="UNKNOWN", text="I have a cough.", timestamp="00:00:00", sequence_number=0)]
    load_started = time.perf_counter()
    provider.extract(warm, ClinicalRecord())
    load_s = time.perf_counter() - load_started
    loaded = httpx.get(f"{settings.ollama_base_url}/api/ps").json().get("models", [])
    results = []
    for case in CASES:
        started = time.perf_counter()
        speakers = SpeakerRoleLabeler(model=args.model).label(case["lines"]) if args.roles else ["UNKNOWN"] * len(case["lines"])
        transcript = [TranscriptSegmentInput(id=f"{case['id']}-final-{index}", speaker=speaker, text=text, timestamp="00:00:00", sequence_number=index) for index, (text, speaker) in enumerate(zip(case["lines"], speakers))]
        try:
            result = provider.extract(transcript, ClinicalRecord())
            record, _, _ = _apply_validated_candidates(result, ClinicalRecord(), transcript)
            error = None
        except Exception as exc:  # a malformed answer counts as an empty note
            record, error = ClinicalRecord(), f"{type(exc).__name__}: {exc}"[:200]
        seconds = time.perf_counter() - started
        stats = getattr(provider, "last_stats", {})
        rate = lambda count, duration: round(count / (duration / 1e9), 1) if count and duration else None  # noqa: E731
        results.append({"case": case["id"], "seconds": round(seconds, 1), **score(case, record), "error": error,
                        "prompt_tokens": stats.get("prompt_eval_count"), "answer_tokens": stats.get("eval_count"),
                        "prompt_tok_s": rate(stats.get("prompt_eval_count"), stats.get("prompt_eval_duration")),
                        "answer_tok_s": rate(stats.get("eval_count"), stats.get("eval_duration")), "num_ctx": stats.get("num_ctx")})
        print(json.dumps(results[-1]), flush=True)
    hits = sum(item["hits"] for item in results)
    total = sum(item["total"] for item in results)
    summary = {"model": args.model, "cpu_only": args.cpu_only, "threads": args.threads, "load_s": round(load_s, 1),
               "memory_gb": round(sum(item.get("size", 0) for item in loaded if item.get("name") == args.model) / 1e9, 2),
               "facts_captured": f"{hits}/{total}", "recall": round(hits / total, 3),
               "violations": sum(len(item["violations"]) for item in results), "errors": sum(1 for item in results if item["error"]),
               "seconds_per_note": round(sum(item["seconds"] for item in results) / len(results), 1),
               "answer_tok_s": round(sum(item["answer_tok_s"] or 0 for item in results) / len(results), 1),
               "prompt_tok_s": round(sum(item["prompt_tok_s"] or 0 for item in results) / len(results), 1)}
    print("SUMMARY " + json.dumps(summary), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "cases": results}, indent=1))


if __name__ == "__main__":
    main()
