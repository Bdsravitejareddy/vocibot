"""Create a portable report after a manual browser microphone consultation.

Run the browser normally in local mode, stop the consultation, then run:
  .venv/bin/python scripts/manual_acceptance_report.py --consultation-id ID
"""

import argparse
import json
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consultation-id", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--debug-dir", default="/tmp/vocibot-audio-debug")
    parser.add_argument("--output", default="docs/superpowers/reports/manual-acceptance-report.json")
    args = parser.parse_args()
    with urllib.request.urlopen(f"{args.api_url}/api/consultations/{args.consultation_id}") as response:
        consultation = json.load(response)
    debug_path = Path(args.debug_dir) / f"{args.consultation_id}.json"
    debug = json.loads(debug_path.read_text()) if debug_path.exists() else {"error": f"debug report not found: {debug_path}"}
    report = {
        "consultation_id": args.consultation_id,
        "consultation": consultation,
        "audio": {key: value for key, value in debug.items() if key not in {"windows", "transcript"}},
        "asr_windows": debug.get("windows", []),
        "asr_transcript": debug.get("transcript", []),
        "notes": "Review the saved WAV against the transcript. This report contains no inferred facts beyond the application record.",
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(output.resolve())


if __name__ == "__main__":
    main()
