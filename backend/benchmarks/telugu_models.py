"""Telugu transcription engines on Telugu consultations with reference text:
the reference consultation (~/Desktop/voices) and telugu_cases/ (synthetic,
two with English words mixed in).

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/telugu_models.py current|<model folder> --out tmp/analytics/te-<name>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from transcription_accuracy import RECORDINGS, VOICES, accuracy, load_audio, reference_text  # noqa: E402

CASES = json.loads((HERE / "telugu_cases" / "cases.json").read_text(encoding="utf-8"))


def items() -> list[tuple[str, np.ndarray, str]]:
    reference = next(item for item in RECORDINGS if item["id"] == "telugu_fever_consultation")
    out = [(reference["id"], load_audio(VOICES / reference["audio"]), reference_text(reference))]
    for case in CASES:
        out.append((case["id"], load_audio(HERE / "telugu_cases" / f"{case['id']}.wav"), " ".join(text for _, text in case["lines"])))
    return out


def current_engine():
    from app.api.audio import build_local_pipeline, restrict_languages
    from app.providers.reconciliation import FinalReconciler

    pipeline = build_local_pipeline()
    restrict_languages(pipeline.stt, {"en", "te", "hi", "ta", "mr", "gu"})
    return lambda audio: " ".join(draft.text for draft in FinalReconciler().run(audio, pipeline.stt, sample_rate=16_000).transcripts)


def hf_engine(model_dir: str):
    import torch
    from transformers import pipeline

    from app.providers.reconciliation import split_at_pauses

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    asr = pipeline("automatic-speech-recognition", model=model_dir, device=device, torch_dtype=torch.float32)
    config = asr.model.config
    own = asr.model.generation_config
    if getattr(own, "lang_to_id", None) and getattr(own, "no_timestamps_token_id", None) and not getattr(own, "task_to_id", None):
        # Its own (extended) vocabulary: complete its settings from its tokenizer.
        own.task_to_id = {task: asr.tokenizer.convert_tokens_to_ids(f"<|{task}|>") for task in ("transcribe", "translate")}
        own.is_multilingual = True
        if hasattr(asr, "generation_config"):
            asr.generation_config = own
    elif not getattr(own, "lang_to_id", None) or not getattr(own, "no_timestamps_token_id", None):
        # Fine-tunes saved with an old transformers: take the decoding settings
        # of the OpenAI model they were trained from.
        from transformers import GenerationConfig

        base = "openai/whisper-large-v3" if config.num_mel_bins == 128 else "openai/whisper-large-v2" if config.d_model == 1280 else "openai/whisper-medium" if config.d_model == 1024 else "openai/whisper-small"
        asr.model.generation_config = GenerationConfig.from_pretrained(base)
        if hasattr(asr, "generation_config"):
            asr.generation_config = asr.model.generation_config

    shift = config.vocab_size - 51866 if config.num_mel_bins == 128 and config.vocab_size > 51866 else 0

    def run(audio):
        texts = []
        for start, end in split_at_pauses(audio, 16_000, 14.0):
            if shift:
                # Extended vocabulary (BuzzASR): Whisper large-v3's special
                # tokens moved up by the added tokens; its tokenizer files
                # disagree, so the start sequence is given directly.
                features = asr.feature_extractor(audio[start:end], sampling_rate=16_000, return_tensors="pt").input_features.to(device)
                prompt = torch.tensor([[50258 + shift, 50299 + shift, 50360 + shift, 50364 + shift]]).to(device)
                out = asr.model.generate(features, decoder_input_ids=prompt, max_new_tokens=220, no_repeat_ngram_size=6)
                texts.append(asr.tokenizer.decode(out[0][4:], skip_special_tokens=True).strip())
                continue
            result = asr({"raw": audio[start:end], "sampling_rate": 16_000}, generate_kwargs={"language": "te", "task": "transcribe", "no_repeat_ngram_size": 6})
            texts.append(result["text"].strip())
        return " ".join(texts)

    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    engine = current_engine() if args.engine == "current" else hf_engine(args.engine)
    rows = []
    for name, audio, reference in items():
        started = time.perf_counter()
        text = engine(audio)
        rows.append({"id": name, **accuracy(reference, text), "seconds": round(time.perf_counter() - started, 1), "audio_s": round(len(audio) / 16_000, 1), "text": text})
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "text"}, ensure_ascii=False), flush=True)
    mean = lambda key: round(sum(row[key] for row in rows) / len(rows), 4)  # noqa: E731
    summary = {"engine": Path(args.engine).name, "word_accuracy": mean("word_accuracy"), "character_accuracy": mean("character_accuracy"),
               "seconds_per_minute_of_audio": round(sum(r["seconds"] for r in rows) / sum(r["audio_s"] for r in rows) * 60, 1)}
    print("SUMMARY " + json.dumps(summary), flush=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
