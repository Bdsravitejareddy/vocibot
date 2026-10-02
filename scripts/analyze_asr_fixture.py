"""Read-only analysis of a saved VociBot consultation WAV/diagnostics pair."""

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--consultation-id", required=True)
    parser.add_argument("--debug-dir", default="/tmp/vocibot-audio-debug")
    parser.add_argument("--database", default="vocibot.db")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    debug_path = Path(args.debug_dir) / f"{args.consultation_id}.json"
    wav_path = Path(args.debug_dir) / f"{args.consultation_id}.wav"
    diagnostics = json.loads(debug_path.read_text())
    report = {
        "consultation_id": args.consultation_id,
        "wav_path": str(wav_path),
        "diagnostics_path": str(debug_path),
        "audio": {key: diagnostics.get(key) for key in ("input_encoding", "mime_type", "source_sample_rate", "decoded_sample_rate", "channel_count", "whisper_sample_rate", "received_duration_ms", "rms", "peak", "clipping_percent", "silence_percent")},
        "window_count": len(diagnostics.get("windows", [])),
        "vad_accepted_windows": sum(bool(window.get("diagnostics", {}).get("accepted")) for window in diagnostics.get("windows", [])),
        "vad_rejected_windows": sum(not bool(window.get("diagnostics", {}).get("accepted")) for window in diagnostics.get("windows", [])),
        "live_transcript": diagnostics.get("transcript", []),
        "final_reconciliation": diagnostics.get("final_reconciliation", {}),
    }
    con = sqlite3.connect(args.database); con.row_factory = sqlite3.Row
    consultation = con.execute("""select c.id,p.patient_identifier,c.started_at,c.ended_at,c.status,cr.structured_data_json from consultations c join patients p on p.id=c.patient_id left join clinical_records cr on cr.consultation_id=c.id where c.id=?""", (args.consultation_id,)).fetchone()
    if consultation:
        report["consultation"] = dict(consultation)
        if report["consultation"].get("structured_data_json"):
            report["consultation"]["structured_data"] = json.loads(report["consultation"].pop("structured_data_json"))
    con.close()
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2) + "\n")
    print(output.resolve())


if __name__ == "__main__":
    main()
