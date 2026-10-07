"""Time left after Stop: the final pass is fed the audio in 5 s steps during
the consultation (as api/audio.py does); finish() is what remains at Stop.

    FINAL_PIECE_SECONDS=14 PYTHONPATH=backend .venv/bin/python backend/benchmarks/stop_tail.py FILE...
"""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from transcription_accuracy import load_audio  # noqa: E402


def main() -> None:
    from app.api.audio import ADVANCE_EVERY_SECONDS, build_local_pipeline, restrict_languages
    from app.config import settings
    from app.providers.reconciliation import IncrementalReconciler

    pipeline = build_local_pipeline()
    restrict_languages(pipeline.stt, {"en", "te", "hi", "ta", "mr", "gu"})
    for path in sys.argv[1:]:
        audio = load_audio(Path(path).expanduser())
        reconciler = IncrementalReconciler(pipeline.stt, sample_rate=16_000)
        during = 0.0
        step = int(ADVANCE_EVERY_SECONDS * 16_000)
        for end in range(step, len(audio), step):
            started = time.perf_counter()
            reconciler.advance(audio[:end])
            during += time.perf_counter() - started
        left = (len(audio) - reconciler.next_start) / 16_000
        started = time.perf_counter()
        result = reconciler.finish(audio)
        print(json.dumps({"file": Path(path).name, "piece_s": settings.final_piece_seconds or 28, "audio_s": round(len(audio) / 16_000, 1),
                          "audio_left_at_stop_s": round(left, 1), "after_stop_s": round(time.perf_counter() - started, 1), "during_s": round(during, 1),
                          "lines": len(result.transcripts)}), flush=True)


if __name__ == "__main__":
    main()
