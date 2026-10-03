"""Transcription accuracy and live delay on reference recordings.

Recordings with a reference script (~/Desktop/voices): three English talks,
one Hindi narration (with an English reference translation) and one Telugu
doctor-patient consultation.  For each, with the clinic's enabled languages
and an optional primary language:

- final: the authoritative pass the note is written from (accuracy, detected
  languages, time);
- live: the rolling live preview replayed in real time (accuracy of the text
  shown live, delay from the end of each spoken line to its appearance,
  share of live text in the wrong script).

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/transcription_accuracy.py --primary te --out tmp/analytics/accuracy-te.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import statistics
import sys
import time
import unicodedata

sys.path.insert(0, str(Path(__file__).parent))

VOICES = Path.home() / "Desktop" / "voices"
RECORDINGS = [
    {"id": "english_cloud_keynote", "language": "en", "audio": "script 1 aud.mp3", "reference": "script_01_it_cloud_architecture_keynote.txt"},
    {"id": "english_university_address", "language": "en", "audio": "script 2 aud.mp3", "reference": "script_02_university_orientation_address.txt"},
    {"id": "english_heritage_walk", "language": "en", "audio": "scipt 3 aud.mp3", "reference": "script_03_heritage_tourism_architecture.txt"},
    {"id": "hindi_varanasi_narration", "language": "hi", "audio": "script 4 aud hind.mp3", "reference": "script_4_hindi_heritage_storytelling_narrative.txt", "section": "## 1.", "translation_section": "## 3."},
    {"id": "telugu_fever_consultation", "language": "te", "audio": "audio 5 telugu.mp3", "reference": "transcription 5 telugu.txt", "speaker_labels": True},
]
ENABLED = {"en", "te", "hi", "mr", "gu"}
# Facts of the Telugu consultation script, scored like note_quality.py.
TELUGU_NOTE_CASE = {
    "id": "telugu_fever_consultation",
    "expected": {
        "chief_complaint": [["headache", "head ache", "body", "fever"]],
        "duration": [["four days", "4 days"]],
        "presenting_symptoms": [["headache"], ["body", "ache"], ["fever"], ["chill"], ["weak", "tired", "fatigue"], ["nause"], ["appetite"]],
        "relevant_negatives": [["cough"], ["stomach", "abdominal"]],
        "vitals": [["101"], ["120"]],
        "assessment": [["viral"]],
        "plan": [["cbp", "blood test", "dengue", "malaria"], ["paracetamol"], ["ors", "fluid", "water", "rest"]],
        "follow_up": [["report", "tomorrow"]],
    },
    "must_not": {"presenting_symptoms": ["cough", "stomach pain", "sore throat", "vomit"]},
}
SCRIPTS = {"te": (0x0C00, 0x0C7F), "hi": (0x0900, 0x097F), "mr": (0x0900, 0x097F), "gu": (0x0A80, 0x0AFF)}


def reference_text(item: dict, section_key: str = "section") -> str:
    text = (VOICES / item["reference"]).read_text(encoding="utf-8")
    if item.get(section_key):
        start = text.index(item[section_key])
        rest = text[start:].split("\n", 1)[1]
        text = rest.split("\n## ", 1)[0]
    if item.get("speaker_labels"):
        text = "\n".join(line.split(":", 1)[1] if ":" in line else line for line in text.splitlines())
    return text


def words(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower()).replace("’", "'").replace("—", " ").replace("-", " ")
    text = re.sub(r"[​-‍]", "", text)
    return [w.strip("'") for w in re.findall(r"[^\s.,!?;:\"“”‘’()\[\]{}।॥…]+", text) if w.strip("'")]


def edit_distance(ref: list, hyp: list) -> int:
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[len(hyp)]


def accuracy(reference: str, hypothesis: str) -> dict:
    ref_words, hyp_words = words(reference), words(hypothesis)
    ref_chars, hyp_chars = list("".join(ref_words)), list("".join(hyp_words))
    return {
        "word_accuracy": round(1 - edit_distance(ref_words, hyp_words) / max(1, len(ref_words)), 4),
        "character_accuracy": round(1 - edit_distance(ref_chars, hyp_chars) / max(1, len(ref_chars)), 4),
        "reference_words": len(ref_words),
    }


def content_overlap(reference: str, hypothesis: str) -> float:
    """Share of the reference translation's content words present in ours."""

    stop = {"the", "a", "an", "of", "and", "to", "in", "is", "on", "that", "this", "it", "as", "are", "be", "with", "for", "by", "at", "from", "has", "have", "its", "their", "we", "you", "our"}
    ref = {w for w in words(reference) if w not in stop}
    hyp = {w for w in words(hypothesis) if w not in stop}
    return round(len(ref & hyp) / max(1, len(ref)), 4)


def wrong_script_share(text: str, language: str) -> float:
    """Share of letters not in the expected script (Telugu written as Hindi ...)."""

    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    if language == "en":
        return round(sum(not c.isascii() for c in letters) / len(letters), 4)
    low, high = SCRIPTS[language]
    return round(sum(not (low <= ord(c) <= high) for c in letters) / len(letters), 4)


def load_audio(path: Path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if rate != 16_000:
        from math import gcd

        divisor = gcd(rate, 16_000)
        audio = resample_poly(audio, 16_000 // divisor, rate // divisor).astype(np.float32)
    return audio


def build_provider(primary: str | None):
    from app.api.audio import build_local_pipeline, restrict_languages

    pipeline = build_local_pipeline()
    try:
        restrict_languages(pipeline.stt, ENABLED, primary)
    except TypeError:  # versions before the primary language
        restrict_languages(pipeline.stt, ENABLED)
    if hasattr(pipeline, "warmup"):
        pipeline.warmup()
    return pipeline


def run_final(pipeline, audio) -> dict:
    from app.providers.reconciliation import FinalReconciler

    started = time.perf_counter()
    result = FinalReconciler().run(audio, pipeline.stt, sample_rate=16_000, language=None)
    return {
        "seconds": round(time.perf_counter() - started, 1),
        "text": " ".join(draft.text for draft in result.transcripts),
        "translation": " ".join(draft.text for draft in result.translations),
        "languages": [draft.language_code for draft in result.transcripts],
        "drafts": result.transcripts,
        "translation_drafts": result.translations,
    }


def run_live(pipeline, audio) -> dict:
    """The live loop of api/audio.py, fed at real-time speed: a pass sees the
    audio that arrived while the previous pass ran."""

    from app.config import settings
    from app.providers.speech import AudioChunk
    from app.providers.streaming import TranscriptCommitter, select_live_commits

    rate = 16_000
    holdback, max_buffer = int(settings.asr_live_holdback_seconds * 1000), int(settings.asr_live_max_buffer_seconds * 1000)
    step, minimum = int(settings.asr_live_step_seconds * rate), int(settings.asr_min_speech_seconds * rate)
    committer = TranscriptCommitter()
    pipeline.stt._language_memory.__init__()
    buffer_start_ms, clock = 0, 0.0
    shown: list[tuple[float, object]] = []
    pass_seconds = []
    while True:
        arrived = min(len(audio), int(clock * rate))
        if arrived >= len(audio) and buffer_start_ms * 16 >= len(audio) - minimum:
            break
        segment = audio[buffer_start_ms * 16:arrived]
        if len(segment) < max(minimum, step):
            if arrived >= len(audio):
                break
            clock += settings.asr_live_step_seconds
            continue
        started = time.perf_counter()
        result = pipeline.process(AudioChunk(audio=b"", sample_rate=rate, timestamp_ms=buffer_start_ms, encoding="pcm_f32le", channels=1, waveform=segment, live=True), language=None)
        took = time.perf_counter() - started
        pass_seconds.append(took)
        clock = max(clock + took, clock + settings.asr_live_step_seconds)
        buffer_end_ms = buffer_start_ms + int(len(segment) / 16)
        decision = select_live_commits(result.transcripts, buffer_start_ms=buffer_start_ms, buffer_end_ms=buffer_end_ms, holdback_ms=holdback, max_buffer_ms=max_buffer)
        for draft in committer.add(decision.committed):
            shown.append((clock, draft))
        settled = decision.commit_until_ms
        if settled is None and not result.transcripts and buffer_end_ms - buffer_start_ms > holdback and (result.diagnostics.get("accepted") is False or buffer_end_ms - buffer_start_ms >= 2 * max_buffer):
            settled = buffer_end_ms - holdback
        if settled and settled > buffer_start_ms:
            buffer_start_ms = settled
        if arrived >= len(audio) and settled is None:
            break
    delays = [max(0.0, at - draft.end_ms / 1000) for at, draft in shown if draft.end_ms is not None]
    return {
        "text": " ".join(draft.text for _, draft in shown),
        "lines": len(shown),
        "line_delay_median_s": round(statistics.median(delays), 2) if delays else None,
        "line_delay_p90_s": round(sorted(delays)[int(len(delays) * 0.9)], 2) if delays else None,
        "pass_median_s": round(statistics.median(pass_seconds), 2) if pass_seconds else None,
        "pass_max_s": round(max(pass_seconds), 2) if pass_seconds else None,
        "languages": [draft.language_code for _, draft in shown],
    }


def write_note(final: dict, item: dict) -> dict:
    """The note as the app writes it: from the English translation (or the
    transcript), evidence-checked, plus symptoms the translation lost."""

    from note_quality import score

    from app.domain.types import ClinicalRecord, Speaker, TranscriptSegmentInput
    from app.providers.ollama_extraction import OllamaClinicalExtractionProvider, mentions_health
    from app.services.consultations import _apply_validated_candidates
    from app.services.native_terms import add_terms_lost_in_translation

    def segments(drafts, tag):
        return [TranscriptSegmentInput(id=f"c-{tag}-{index}", speaker=Speaker.UNKNOWN, text=draft.text, timestamp=draft.timestamp, sequence_number=index) for index, draft in enumerate(drafts)]

    original = segments(final["drafts"], "final")
    source = segments(final["translation_drafts"], "en") if final["translation_drafts"] else original
    started = time.perf_counter()
    result = OllamaClinicalExtractionProvider().extract(source, ClinicalRecord())
    record, evidence, needs_review = _apply_validated_candidates(result, ClinicalRecord(), source)
    if final["translation_drafts"] and mentions_health(item.text for item in source):
        record = add_terms_lost_in_translation(record, evidence, needs_review, original)
    filled = {key: value for key, value in record.model_dump().items() if value not in (None, "", [], {})}
    note = {"seconds": round(time.perf_counter() - started, 1), "fields_filled": len(filled), "record": filled}
    if item["id"] == TELUGU_NOTE_CASE["id"]:
        note |= score(TELUGU_NOTE_CASE, record)
    return note


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary")
    parser.add_argument("--skip-final", action="store_true")
    parser.add_argument("--skip-note", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--only")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    pipeline = build_provider(args.primary)
    report = []
    for item in RECORDINGS:
        if args.only and args.only not in item["id"]:
            continue
        audio = load_audio(VOICES / item["audio"])
        reference = reference_text(item)
        row = {"id": item["id"], "language": item["language"], "audio_s": round(len(audio) / 16_000, 1), "primary": args.primary}
        live = run_live(pipeline, audio) if not args.skip_live else {"text": "", "languages": []}
        row["live"] = {} if args.skip_live else {**{k: v for k, v in live.items() if k not in ("text", "languages")}, **accuracy(reference, live["text"]), "wrong_script_share": wrong_script_share(live["text"], item["language"])}
        if not args.skip_final:
            final = run_final(pipeline, audio)
            row["final"] = {"seconds": final["seconds"], **accuracy(reference, final["text"]), "wrong_script_share": wrong_script_share(final["text"], item["language"]), "languages": sorted(set(filter(None, final["languages"])))}
            if item.get("translation_section"):
                row["final"]["translation_overlap"] = content_overlap(reference_text(item, "translation_section"), final["translation"])
            row["final_text"], row["final_translation"] = final["text"], final["translation"]
            if not args.skip_note:
                row["note"] = write_note(final, item)
        row["live_text"] = live["text"]
        report.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.endswith("_text") and k != "final_translation"}, ensure_ascii=False), flush=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
