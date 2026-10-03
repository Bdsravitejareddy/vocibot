"""Live preview on the clinic's own Telugu recordings (no reference script):
share of live text in the wrong script, and which languages were shown.

    PYTHONPATH=backend .venv/bin/python backend/benchmarks/real_recordings.py --primary te FILE...
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from transcription_accuracy import build_provider, load_audio, run_live, wrong_script_share  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--primary")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    pipeline = build_provider(args.primary)
    for path in args.files:
        live = run_live(pipeline, load_audio(Path(path)))
        print(json.dumps({"label": args.label, "file": Path(path).name, "wrong_script_share": wrong_script_share(live["text"], "te"), "languages": live["languages"], "lines": live["lines"], "line_delay_median_s": live["line_delay_median_s"], "text": live["text"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
